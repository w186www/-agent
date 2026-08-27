"""路由层：知识库管理（需认证）。

- POST /kb/upload：上传历史标书文件，创建 kb_documents 记录（kb_type=2）并向量化灌入 Qdrant；
- GET /kb/documents：分页查询知识库文档列表（可按 kb_type 筛选）。

历史标书走本地存储（kb_ingest 需要本地文件路径提取文本），不走 MinIO；
向量化失败（缺 DASHSCOPE_API_KEY / Qdrant 不可用）时记录 status=2，返回友好错误，不中断。
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.kb_ingest import ingest_bidding_doc
from ..config import settings
from ..db.models import KbDocument, User
from ..db.session import get_db
from ..log import get_logger
from ..schemas.common import ApiResponse
from ..security import get_current_user

router = APIRouter(prefix="/kb", tags=["知识库"])
logger = get_logger("kb")

# 知识库本地文件目录（ingest 需要本地路径提取文本）
_KB_DIR = Path(settings.upload_dir) / "kb"


def _kb_doc_payload(doc: KbDocument) -> dict:
    """KbDocument -> 响应结构。"""
    return {
        "id": doc.id,
        "kb_type": doc.kb_type,
        "doc_title": doc.doc_title,
        "file_path": doc.file_path,
        "chunk_count": doc.chunk_count,
        "status": doc.status,  # 0=待处理，1=已向量化，2=处理失败
        "created_at": doc.created_at,
    }


@router.post("/upload", response_model=ApiResponse, summary="上传历史标书并向量化灌入知识库")
async def upload_kb_document(
    file: UploadFile,
    doc_title: str | None = Form(default=None, description="文档标题，缺省用文件名"),
    kb_type: int = Form(default=2, ge=0, le=2, description="知识库类型：0=等保标准库，1=企业本地库，2=历史标书库（本轮固定历史标书）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """上传历史标书：本地落盘 + 创建 kb_documents 记录 + 向量化灌入 Qdrant。"""
    content = await file.read()
    if not content:
        return ApiResponse(code=1, message="文件内容为空", data=None)
    if len(content) > settings.max_upload_size:
        return ApiResponse(code=1, message=f"文件超过大小限制（{settings.max_upload_size // (1024 * 1024)}MB）", data=None)

    title = (doc_title or file.filename or "未命名标书").strip()
    doc = KbDocument(
        user_id=current_user.id, kb_type=kb_type, doc_title=title,
        file_path="", chunk_count=0, status=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 落盘：{doc_id}_{原文件名}，防冲突
    _KB_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or f"doc_{doc.id}").name
    file_path = str(_KB_DIR / f"{doc.id}_{safe_name}")
    Path(file_path).write_bytes(content)
    doc.file_path = file_path
    db.commit()

    # 向量化灌入（失败标记 status=2，返回错误信息）
    ingest = ingest_bidding_doc(db, doc.id, file_path, doc.doc_title, kb_type=doc.kb_type)
    db.refresh(doc)
    payload = _kb_doc_payload(doc)
    payload["ingest"] = ingest
    if ingest.get("status") != 1:
        return ApiResponse(code=1, message=ingest.get("error") or "向量化失败", data=payload)
    return ApiResponse(code=0, message="上传并向量化成功", data=payload)


@router.get("/documents", response_model=ApiResponse, summary="知识库文档列表")
def list_kb_documents(
    kb_type: int | None = Query(default=None, ge=0, le=2, description="知识库类型筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """分页查询当前用户的知识库文档（按创建时间倒序）。"""
    query = select(KbDocument).where(KbDocument.user_id == current_user.id)
    if kb_type is not None:
        query = query.where(KbDocument.kb_type == kb_type)
    total = db.scalar(select(func.count()).select_from(KbDocument).where(
        KbDocument.user_id == current_user.id,
        *( [KbDocument.kb_type == kb_type] if kb_type is not None else [] ),
    )) or 0
    rows = db.scalars(
        query.order_by(KbDocument.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ApiResponse(code=0, message="success", data={
        "items": [_kb_doc_payload(d) for d in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    })
