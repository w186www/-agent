"""业务层：MinIO 对象存储上传逻辑（当前运行版本）。

架构：元数据与文件解耦
- MySQL resources 表存元数据（file_hash + user_id 联合唯一实现用户级去重）；
- MinIO 存原文件，storage_path 格式 minio://{bucket}/{object_key}；
- /upload/file 路由入口不变，仅底层存储实现切换（旧逻辑见 upload_service.py，教学保留）。

upload_purpose 业务联动：
- 0=普通资源：仅保存
- 1=招标文件：更新 bidding_tasks.tender_file_path
- 2=历史标书：创建 kb_documents 记录（kb_type=2）并向 Qdrant 灌入向量
- 3=测评截图：更新 assessment_records.screenshot_path
- 4=资产核查表：storage_scene=2，只提取内容不存原文件，供 Agent 生成拓扑数据
- 5=投标文件：写入 bidding_tasks.bidding_sections.uploaded_bidding_file，
  供 review_bidding 工具定位文件做废标项/格式/错字审核

注意：storage_scene=2 只提取文件内容，不上传原文件、不创建元数据记录。
"""

import hashlib
import io
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import (
    AssessmentRecord,
    BiddingTask,
    ChatMessage,
    ChatSession,
    KbDocument,
    Resource,
    User,
)
from ..exceptions import BusinessError, ErrorCode
from ..log import get_logger
from .minio_client import get_minio_client, storage_path_of

logger = get_logger("upload")

# 图片 MIME 前缀
IMAGE_PREFIX = "image/"

# 资源类型 / 存储场景 / 上传用途枚举（与 resources 表注释一致）
RESOURCE_TYPE_DOC = 0       # 文档（PDF/Word/Excel）
RESOURCE_TYPE_IMAGE = 1     # 图片（测评截图）
SCENE_LONG = 0              # 长过期：1 个月（招标文件/历史标书/测评截图）
SCENE_SHORT = 1             # 短过期：2 小时（对话临时附件）
SCENE_EXTRACT_ONLY = 2      # 只提取内容不存原文件

# 各存储场景对应的过期时长（秒）
_EXPIRE_SECONDS = {
    SCENE_LONG: 30 * 24 * 3600,
    SCENE_SHORT: 2 * 3600,
}

# 文本类扩展名（可直接按文本解码提取内容）
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log", ".xml", ".yaml", ".yml"}


def _md5_of_file(content: bytes) -> str:
    """计算文件内容的 MD5 哈希。"""
    return hashlib.md5(content).hexdigest()


def _detect_file_type(content_type: str | None) -> int:
    """根据 MIME 类型判断资源类型：1=图片，0=文档。"""
    if content_type and content_type.startswith(IMAGE_PREFIX):
        return RESOURCE_TYPE_IMAGE
    return RESOURCE_TYPE_DOC


def _get_extension(filename: str) -> str:
    """从文件名提取扩展名（含点），无扩展名返回空字符串。"""
    return Path(filename).suffix.lower()


def _extract_text(content: bytes, ext: str) -> str | None:
    """提取文件文本内容。

    支持文本类（按 utf-8/utf-16/gbk 解码）与 PDF / DOCX（PyMuPDF / python-docx 解析）；
    其他二进制格式返回 None。
    """
    if ext in _TEXT_EXTENSIONS:
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "gbk"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None
    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=content, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        except Exception:
            return None
    if ext == ".docx":
        try:
            from docx import Document

            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return None
    return None


def _build_object_key(user_id: int, md5: str, ext: str) -> str:
    """构造 MinIO object_key：按用户 ID 分目录 + MD5 文件名（去重）。"""
    return f"users/{user_id}/{md5}{ext}"


def _expire_time_of(storage_scene: int) -> int | None:
    """根据存储场景计算资源过期时间（Unix 秒），场景 2 不落盘无过期。"""
    seconds = _EXPIRE_SECONDS.get(storage_scene)
    if seconds is None:
        return None
    return int(time.time()) + seconds


def _find_or_create_resource(db: Session, user: User, content: bytes, filename: str,
                             content_type: str | None, storage_scene: int,
                             upload_purpose: int) -> tuple[Resource, bool]:
    """去重预查（代码层）+ 落 MinIO + 建元数据（数据库唯一键兜底）。返回 (资源, 是否新建)。"""
    md5 = _md5_of_file(content)
    ext = _get_extension(filename or "file")

    # 代码层预查：同用户同 MD5 直接复用已有资源
    existing = db.scalar(
        select(Resource).where(Resource.file_hash == md5, Resource.user_id == user.id)
    )
    if existing is not None:
        return existing, False

    object_key = _build_object_key(user.id, md5, ext)
    client = get_minio_client()
    client.put_object(
        settings.minio_bucket,
        object_key,
        io.BytesIO(content),
        length=len(content),
        content_type=content_type or "application/octet-stream",
    )

    resource = Resource(
        resource_type=_detect_file_type(content_type),
        storage_scene=storage_scene,
        upload_purpose=upload_purpose,
        file_name=filename or object_key,
        file_hash=md5,
        storage_path=storage_path_of(object_key),
        user_id=user.id,
        expire_time=_expire_time_of(storage_scene),
    )
    db.add(resource)
    try:
        db.commit()
    except IntegrityError:
        # 数据库唯一键兜底：并发下同 MD5 已被写入，回滚并复用
        db.rollback()
        logger.info("资源唯一键冲突，复用已存在资源 md5=%s user=%s", md5, user.id)
        resource = db.scalar(
            select(Resource).where(Resource.file_hash == md5, Resource.user_id == user.id)
        )
        return resource, False
    db.refresh(resource)
    return resource, True


def _link_bidding_task(db: Session, user: User, resource: Resource, session_id: int | None) -> None:
    """upload_purpose=1：更新关联招投标任务的招标文件路径。"""
    if session_id is None:
        return
    task = db.scalar(
        select(BiddingTask)
        .where(BiddingTask.session_id == session_id, BiddingTask.user_id == user.id)
        .order_by(BiddingTask.id.desc())
        .limit(1)
    )
    if task is None:
        return
    task.tender_file_path = resource.storage_path
    db.commit()


def _link_assessment_record(db: Session, user: User, resource: Resource, session_id: int | None) -> None:
    """upload_purpose=3：更新关联测评核查记录的截图路径。"""
    if session_id is None:
        return
    record = db.scalar(
        select(AssessmentRecord)
        .where(AssessmentRecord.session_id == session_id, AssessmentRecord.user_id == user.id)
        .order_by(AssessmentRecord.id.desc())
        .limit(1)
    )
    if record is None:
        return
    record.screenshot_path = resource.storage_path
    db.commit()


def _link_bidding_review(db: Session, user: User, resource: Resource, session_id: int | None) -> None:
    """upload_purpose=5：把上传的投标文件路径写入关联招投标任务，供 review_bidding 审核。

    写入 bidding_sections.uploaded_bidding_file（minio:// 存储路径），
    Agent 审核时由 review_bidding 工具据此定位并拉取文件。
    """
    if session_id is None:
        return
    task = db.scalar(
        select(BiddingTask)
        .where(BiddingTask.session_id == session_id, BiddingTask.user_id == user.id)
        .order_by(BiddingTask.id.desc())
        .limit(1)
    )
    if task is None:
        return
    task.bidding_sections = dict(task.bidding_sections or {})
    task.bidding_sections["uploaded_bidding_file"] = resource.storage_path
    db.commit()


def _link_kb_document(db: Session, user: User, resource: Resource, content: bytes) -> None:
    """upload_purpose=2：创建历史标书知识库记录（kb_type=2）并向 Qdrant 灌入向量。"""
    doc = KbDocument(
        user_id=user.id,
        kb_type=2,
        doc_title=resource.file_name,
        doc_source=f"历史标书 {resource.file_name}",
        file_path=resource.storage_path,
        status=1,  # 已向量化
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        _index_into_qdrant(doc.id, resource.file_name, content)
    except Exception:
        # 向量库不可用不阻断上传，标为待处理由后续任务重试
        doc.status = 0
        db.commit()
        logger.warning("Qdrant 灌入失败，标书 id=%s 标记待处理", doc.id)


def _index_into_qdrant(doc_id: int, title: str, content: bytes) -> None:
    """向 Qdrant 灌入历史标书向量（占位 embedding：确定性 hash 向量，可检索）。

    说明：原型阶段用文本的确定性哈希向量实现可检索；后续接入语义
    embedding 模型时，仅需替换本函数的向量生成逻辑。
    """
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    text = _extract_text(content, _get_extension(title))
    if not text:
        return

    # 按 500 字符切块
    chunks = [text[i:i + 500] for i in range(0, len(text), 500)] or [""]

    client = QdrantClient(url=settings.qdrant_url)
    vectors = []
    payloads = []
    for idx, chunk in enumerate(chunks):
        vector = _hash_vector(chunk)
        vectors.append(vector)
        payloads.append(qm.PointStruct(
            # Qdrant 要求 point ID 为无符号整数或 UUID，此处用 doc_id*100000+idx 保证唯一
            id=doc_id * 100000 + idx,
            vector=vector,
            payload={"doc_id": doc_id, "chunk_index": idx, "text": chunk},
        ))

    if not client.collection_exists(settings.qdrant_collection):
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qm.VectorParams(size=len(vectors[0]), distance=qm.Distance.COSINE),
        )
    client.upsert(collection_name=settings.qdrant_collection, points=payloads)


def _hash_vector(text: str, dim: int = 64) -> list[float]:
    """确定性文本哈希向量（占位 embedding，后续可替换为语义模型）。"""
    vector = [0.0] * dim
    for i, ch in enumerate(text):
        vector[i % dim] += float(hash(ch)) % 1e6 / 1e6 - 0.5
    norm = sum(v * v for v in vector) ** 0.5 or 1.0
    return [v / norm for v in vector]


def save_file_minio(
    db: Session,
    user: User,
    content: bytes,
    filename: str,
    content_type: str | None,
    upload_purpose: int = 0,
    storage_scene: int = 0,
    session_id: int | None = None,
    message_id: int | None = None,
) -> dict:
    """上传文件到 MinIO 并写入元数据，返回资源信息。

    - storage_scene=2（资产核查表/对话附件）：只提取文件内容返回，不存文件、不建元数据；
      对话附件（upload_purpose != 4）额外把提取文本写入 message_id 对应消息的 file_extracted_text
    - 图片：额外更新用户 avatar 字段
    - upload_purpose 触发对应业务联动（见模块文档）
    """
    if len(content) > settings.max_upload_size:
        raise BusinessError(
            ErrorCode.VALIDATION,
            f"文件大小超过限制（最大 {settings.max_upload_size // 1024 // 1024}MB）",
            status_code=413,
        )

    # 资产核查表强制只提取内容，不落盘
    if upload_purpose == 4:
        storage_scene = SCENE_EXTRACT_ONLY

    file_type = _detect_file_type(content_type)
    ext = _get_extension(filename or "file")
    md5 = _md5_of_file(content)

    # 场景 2：只提取内容，不上传原文件
    if storage_scene == SCENE_EXTRACT_ONLY:
        extracted = _extract_text(content, ext)
        logger.info("storage_scene=2 仅提取内容 user=%s md5=%s extracted=%s",
                    user.id, md5, len(extracted) if extracted else 0)
        # 对话附件（非资产核查表）：提取文本绑定到目标会话（会话级附件，随消息自动注入）
        if upload_purpose != 4:
            if session_id is not None:
                session = db.get(ChatSession, session_id)
                if session is not None and session.user_id == user.id:
                    session.attachment_name = filename
                    session.attachment_text = extracted
                    db.commit()
                    logger.info("对话附件提取文本已绑定 sessions id=%s", session.id)
            elif message_id is not None:
                message = db.get(ChatMessage, message_id)
                if message is not None and message.user_id == user.id:
                    message.file_name = filename
                    message.file_extracted_text = extracted
                    db.commit()
                    logger.info("对话附件提取文本已写入 chat_messages id=%s", message.id)
        return {
            "type": "document" if file_type == RESOURCE_TYPE_DOC else "image",
            "path": None,
            "filename": filename,
            "size": len(content),
            "original_name": filename,
            "extracted_text": extracted,
            "expire_time": None,
        }

    # 常规存储：MinIO + 元数据（去重）
    resource, created = _find_or_create_resource(
        db, user, content, filename, content_type, storage_scene, upload_purpose
    )

    # 图片：更新用户头像
    if resource.resource_type == RESOURCE_TYPE_IMAGE:
        user.avatar = resource.storage_path
        db.commit()

    # upload_purpose 业务联动
    if upload_purpose == 1:
        _link_bidding_task(db, user, resource, session_id)
    elif upload_purpose == 2:
        _link_kb_document(db, user, resource, content)
    elif upload_purpose == 3:
        _link_assessment_record(db, user, resource, session_id)
    elif upload_purpose == 5:
        _link_bidding_review(db, user, resource, session_id)

    return {
        "type": "image" if resource.resource_type == RESOURCE_TYPE_IMAGE else "document",
        "path": resource.storage_path,
        "filename": resource.file_name,
        "size": len(content),
        "original_name": filename,
        "resource_id": resource.id,
        "expire_time": resource.expire_time,
        "deduplicated": not created,
    }
