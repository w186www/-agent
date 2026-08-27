"""知识库灌入服务：文本提取 -> 清洗 -> 切分 -> 向量化 -> 写 Qdrant -> 原文落 MySQL。

- extract_text(file_path)：按扩展名提取全文（.pdf/.docx/.doc，与 parse_tender 同源逻辑）；
- clean_text(text)：清洗（去零宽字符、删独立页码行、压缩多换行、合并空白），提升向量化质量；
- chunk_text(text)：滑动窗口切分（size=500 / overlap=50），优先回退到句子终止符
  （。！？\\n）截断，避免从句子中间切断，MD5 去重；
- ensure_collection(client, kb_type, embeddings)：集合不存在时创建，向量维度自适配
  （先 embed 一条探针文本取实际维度，避免配置猜测）；
- ingest_bidding_doc(db, doc_id, file_path, doc_title)：完整灌入流程。同文档重传时先清
  Qdrant 旧向量与 MySQL 旧切片再写入，保证幂等；Embedding 服务不可用（缺 DASHSCOPE_API_KEY）
  或 Qdrant 不可用时标记 status=2 并返回错误，不抛出。

知识库只做单文档灌入与状态更新，不做链路组装、不定义 Prompt。
"""

import hashlib
import re
import uuid
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import KbChunk, KbDocument
from ..log import get_logger
from .llm import get_embeddings
from .memory import get_qdrant_client, qdrant_collection_of

logger = get_logger("kb_ingest")


def extract_text(file_path: str) -> str:
    """按扩展名提取文件全文（.pdf/.docx/.doc/.txt），失败抛出异常。"""
    p = Path(file_path)
    if not p.exists():
        raise ValueError(f"文件不存在：{file_path}")
    ext = p.suffix.lower()
    if ext == ".pdf":
        import fitz  # PyMuPDF

        doc = fitz.open(str(p))
        try:
            page_texts = [page.get_text() for page in doc]
        finally:
            doc.close()
        # 扫描版判定：平均每页字符数 < 20 视为扫描件，走 OCR 兜底；电子版直接返回
        avg_chars = sum(len(t) for t in page_texts) / max(len(page_texts), 1)
        if avg_chars < 20:
            from .ocr import ocr_pdf

            return ocr_pdf(p)
        return "\n".join(page_texts)
    elif ext == ".docx":
        from docx import Document

        doc = Document(str(p))
        lines: list[str] = []
        for para in doc.paragraphs:
            text = (para.text or "").strip()
            if not text:
                continue
            # 识别 Heading 1/2/3（兼容中文“标题 1/2/3”），注入 # / ## / ### 标记，
            # 让切片器优先按标题结构切分，不丢文档层级
            style_name = (para.style.name or "") if para.style else ""
            level = 0
            if style_name.startswith(("Heading", "标题")):
                for ch in reversed(style_name):
                    if ch.isdigit():
                        level = int(ch)
                        break
            lines.append(f"{'#' * level} {text}" if 1 <= level <= 3 else text)
        return "\n".join(lines)
    elif ext == ".doc":
        # python-docx 无法解析真正的旧版 .doc（OLE），尝试读取，失败则提示转换
        try:
            from docx import Document

            doc = Document(str(p))
            return "\n".join(para.text for para in doc.paragraphs)
        except Exception as exc:
            raise ValueError("旧版 .doc 格式无法直接解析，请转换为 .pdf 或 .docx 后重新上传") from exc
    elif ext == ".txt":
        return p.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"不支持的文件格式：{ext or '无扩展名'}（仅支持 .pdf/.docx/.doc/.txt）")


def clean_text(text: str) -> str:
    """清洗原始文本：去零宽字符、删独立页码行、压缩多换行、合并空白。

    顺序不可调换：先删页码行（依赖行结构），再压多换行与合并空白。
    """
    # 1. 去零宽字符（ZWSP/ZWNJ/ZWJ/BOM）
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    # 2. 删独立页码行（整行只有 1-4 位数字）
    text = re.sub(r"^\s*\d{1,4}\s*$", "", text, flags=re.MULTILINE)
    # 3. 压缩多换行（含空白行的连续换行）
    text = re.sub(r"\n\s*\n+", "\n", text)
    # 4. 合并空白（半角/全角空格与制表符，不影响换行）
    text = re.sub(r"[ \t\u3000]+", " ", text)
    return text.strip()


# 递归智能切片：分隔符按优先级排列（\n### 最优先，"" 兜底逐字符切分）
# keep_separator="end"：分隔符保留在块尾（标题/标点不丢结构），避免句号被拼到块首
_SPLIT_SEPARATORS = ["\n###", "\n##", "\n#", "\n\n", "。", "！", "？", "；", "，", " ", ""]
_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
    separators=_SPLIT_SEPARATORS,
    keep_separator="end",
)


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """递归智能切片：按优先级分隔符（标题/段落/句号/逗号/空格）递归切分，MD5 去重。

    相比纯字符滑窗，优先在标题（# 层级）与句子边界切分，避免切断语义；
    传入 size/overlap 可覆盖默认配置（测试用）。其余业务逻辑与默认切分一致。
    """
    if size or overlap:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=size or settings.chunk_size,
            chunk_overlap=overlap or settings.chunk_overlap,
            separators=_SPLIT_SEPARATORS,
            keep_separator="end",
        )
    else:
        splitter = _SPLITTER
    text = text.strip()
    if not text:
        return []

    seen: set[str] = set()
    chunks: list[str] = []
    for chunk in splitter.split_text(text):
        chunk = chunk.strip()
        md5 = hashlib.md5(chunk.encode("utf-8")).hexdigest()
        if chunk and md5 not in seen:  # MD5 去重
            seen.add(md5)
            chunks.append(chunk)
    return chunks


def ensure_collection(client, kb_type: int, embeddings) -> int | None:
    """确保 kb_type 对应 collection 存在（向量维度自适配），返回维度；Embedding 不可用时返回 None。"""
    collection = qdrant_collection_of(kb_type)
    try:
        if client.collection_exists(collection):
            info = client.get_collection(collection)
            return int(info.config.params.vectors.size)
        # 集合不存在：先取一条探针向量获得实际维度，再创建
        probe = embeddings.embed("维度探测文本")
        from qdrant_client.models import Distance, VectorParams

        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=len(probe), distance=Distance.COSINE),
        )
        logger.info("创建 Qdrant collection %s dim=%d", collection, len(probe))
        return len(probe)
    except Exception as exc:
        logger.warning("ensure_collection 失败 collection=%s: %s", collection, exc)
        return None


def _delete_doc_chunks(db: Session, client, doc_id: int, kb_type: int) -> None:
    """同文档重传覆盖：清掉该文档在 Qdrant 与 MySQL 中的旧切片（幂等保证）。

    Qdrant 侧用 payload 过滤删除（point.id 为 UUID，直接按 doc_id 过滤字段删更稳）；
    集合不存在或删除失败时降级（不阻断重新灌入，新写入会覆盖旧点）。
    """
    collection = qdrant_collection_of(kb_type)
    try:
        if client.collection_exists(collection):
            client.delete(
                collection_name=collection,
                points_selector=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
            )
    except Exception as exc:
        logger.warning("Qdrant 旧切片删除失败（降级继续）doc_id=%s: %s", doc_id, exc)
    db.execute(delete(KbChunk).where(KbChunk.doc_id == doc_id))


def _save_chunks(db: Session, doc_id: int, chunks: list[tuple[str, str, int]]) -> None:
    """将切片原文批量写入 MySQL kb_chunks（vector_id 与 Qdrant point id 一一对应）。"""
    db.add_all(
        [
            KbChunk(
                doc_id=doc_id,
                vector_id=vector_id,
                chunk_index=chunk_index,
                content=content,
                char_count=len(content),
            )
            for vector_id, content, chunk_index in chunks
        ]
    )


def ingest_bidding_doc(db: Session, doc_id: int, file_path: str, doc_title: str, kb_type: int = 2) -> dict:
    """将历史标书文档向量化并灌入 Qdrant，原文落 MySQL，更新 kb_documents 状态。

    返回：{"doc_id", "status"(1=已向量化/2=处理失败), "chunks"(向量块数), "error"(失败原因)}。
    异常不向上抛出，统一记录为处理失败（失败时回滚，保留旧切片数据）。
    """
    doc = db.get(KbDocument, doc_id)
    if doc is None:
        raise ValueError(f"kb_documents 记录不存在：id={doc_id}")
    try:
        raw_text = extract_text(file_path)
        text = clean_text(raw_text)
        if len(raw_text) != len(text):
            logger.info("清洗完成 doc_id=%d 原始=%d字符 → 清洗后=%d字符", doc_id, len(raw_text), len(text))
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("文件提取文本为空")

        embeddings = get_embeddings()
        client = get_qdrant_client()
        dim = ensure_collection(client, kb_type, embeddings)
        if dim is None:
            raise ValueError("Embedding 服务不可用（检查 DASHSCOPE_API_KEY）或 Qdrant 创建集合失败")

        # 同文档重传覆盖：先清旧向量与旧切片，保证幂等
        _delete_doc_chunks(db, client, doc_id, kb_type)

        vectors = embeddings.embed_documents(chunks)
        # 双份存储：Qdrant 只存向量 + 检索过滤字段（不存原文），原文落 MySQL kb_chunks，
        # 两边通过同一个 UUID（point id = kb_chunks.vector_id）关联
        points = []
        chunk_rows: list[tuple[str, str, int]] = []
        for idx, chunk in enumerate(chunks):
            vector_id = str(uuid.uuid4())
            points.append(
                PointStruct(
                    id=vector_id,
                    vector=vectors[idx],
                    payload={
                        "doc_id": doc_id,
                        "doc_title": doc_title,
                        "chunk_index": idx,
                        "user_id": doc.user_id,
                    },
                )
            )
            chunk_rows.append((vector_id, chunk, idx))
        client.upsert(collection_name=qdrant_collection_of(kb_type), points=points)

        _save_chunks(db, doc_id, chunk_rows)
        doc.chunk_count = len(chunks)
        doc.status = 1
        db.commit()
        logger.info("ingest_bidding_doc 完成 doc_id=%d chunks=%d title=%s", doc_id, len(chunks), doc_title)
        return {"doc_id": doc_id, "status": 1, "chunks": len(chunks)}
    except Exception as exc:
        db.rollback()  # 失败回滚：保留旧切片，避免删除旧数据后新数据写入失败导致数据丢失
        doc.status = 2
        db.commit()
        logger.warning("ingest_bidding_doc 失败 doc_id=%d: %s", doc_id, exc)
        return {"doc_id": doc_id, "status": 2, "chunks": 0, "error": str(exc)}
