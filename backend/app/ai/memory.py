"""记忆层：只负责历史记忆构建与检索增强。

- get_session_memory(session_id)：从 chat_messages 按 session_id 查历史消息，
  按 created_at 排序，构造 LangChain ConversationBufferWindowMemory
  （role=0 为 HumanMessage，role=1 为 AIMessage，窗口默认最近 20 轮）；
- get_rag_context(query, kb_types)：搜索增强，并行查询 Qdrant 多个 collection
  （kb_type=0 等保标准库 / 1 企业本地库 / 2 历史标书库），合并按 similarity 排序返回 top-k；
- get_bidding_context(tender_title)：招投标专用检索（kb_type=2 历史标书库），
  返回相似段落供 Agent 参考风格结构，同时返回引用 doc_id 列表（写入 bidding_tasks.reference_doc_ids）；
- get_assessment_context(checklist_code)：测评核查专用检索（kb_type=0 + 1），
  返回 kb_references 结构（写入 assessment_records.kb_references）；
- build_memory_prompt(memory, rag_context)：历史 + 检索结果组装为 Prompt 变量。

记忆层不做模型调用、不组装 Chain、不定义 Prompt。
"""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from langchain.memory import ConversationBufferWindowMemory
from langchain_core.messages import AIMessage, HumanMessage
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import ChatMessage, KbChunk, KbDocument
from ..db.session import SessionLocal
from ..log import get_logger
from .llm import get_embeddings

logger = get_logger("memory")

# kb_type -> 知识库名称（与 kb_documents 表注释一致）
KB_TYPE_NAMES = {0: "等保标准库", 1: "企业本地库", 2: "历史标书库"}


def qdrant_collection_of(kb_type: int) -> str:
    """kb_type 对应的 Qdrant collection 名称（按知识库类型分 collection）。"""
    return f"{settings.qdrant_collection}_{kb_type}"


@lru_cache(maxsize=1)
def get_qdrant_client():
    """Qdrant 客户端（懒加载，避免无 Qdrant 时阻塞启动）。"""
    from qdrant_client import QdrantClient

    return QdrantClient(url=settings.qdrant_url)


def get_session_memory(
    session_id: int, k: int | None = None, db: Session | None = None
) -> ConversationBufferWindowMemory:
    """按 session_id 构造窗口记忆。

    历史消息按 created_at 升序载入；窗口默认保留最近 settings.memory_window_k 轮，
    超出时由 ConversationBufferWindowMemory 截断早期消息，避免 token 溢出。
    """
    window = k or settings.memory_window_k
    memory = ConversationBufferWindowMemory(k=window, return_messages=False)

    own_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        messages = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        ).all()
        for msg in messages:
            text = (msg.content or "").strip()
            if not text:
                continue
            if msg.role == 0:
                memory.chat_memory.add_message(HumanMessage(content=text))
            else:
                memory.chat_memory.add_message(AIMessage(content=text))
    finally:
        if own_session:
            db.close()
    return memory


def _query_collection(
    client, kb_type: int, query_vector: list[float], top_k: int, user_id: int | None = None
) -> list[dict]:
    """查询单个 collection，返回命中片段元数据；集合不存在或检索失败时降级为空。

    Qdrant 只存向量与过滤字段（不存原文），故这里只取 vector_id + 过滤字段，
    原文由 get_rag_context 统一回查 MySQL kb_chunks。
    企业本地库（1）/历史标书库（2）按 user_id 隔离；等保标准库（0）为公共库不过滤。
    """
    collection = qdrant_collection_of(kb_type)
    try:
        if not client.collection_exists(collection):
            logger.info("Qdrant collection 不存在，跳过检索 kb_type=%s collection=%s", kb_type, collection)
            return []
        query_filter = None
        if kb_type in (1, 2) and user_id is not None:
            query_filter = Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            )
        # qdrant-client 版本兼容：>=1.14 移除 search()，统一用 query_points()
        if hasattr(client, "query_points"):
            resp = client.query_points(
                collection_name=collection, query=query_vector,
                query_filter=query_filter, limit=top_k,
            )
            hits = resp.points if resp is not None else []
        else:
            hits = client.search(
                collection_name=collection, query_vector=query_vector,
                query_filter=query_filter, limit=top_k,
            )
    except Exception:
        logger.exception("Qdrant 检索失败 kb_type=%s", kb_type)
        return []
    snippets = []
    for hit in hits:
        payload = hit.payload or {}
        snippets.append({
            "vector_id": str(hit.id),
            "doc_id": payload.get("doc_id"),
            "chunk_index": payload.get("chunk_index"),
            "score": float(hit.score),
            "kb_type": kb_type,
        })
    return snippets


def get_rag_context(
    query: str, kb_types: list[int], top_k: int | None = None,
    db: Session | None = None, user_id: int | None = None,
) -> list[dict]:
    """并行检索多个知识库 collection，合并结果按相似度降序返回 top-k 片段。

    片段结构：{"text", "chunk_id", "doc_id", "chunk_index", "score", "kb_type"}。
    Qdrant 不存原文，命中后按 vector_id 回查 MySQL kb_chunks 取原文与主键 id；
    原文缺失（历史脏数据）时该条降级丢弃。
    """
    if not query or not kb_types:
        return []
    k = top_k or settings.rag_top_k
    client = get_qdrant_client()
    query_vector = get_embeddings().embed(query)
    with ThreadPoolExecutor(max_workers=len(kb_types)) as pool:
        results = pool.map(
            lambda t: _query_collection(client, t, query_vector, k, user_id=user_id), kb_types
        )
    merged = [snippet for group in results for snippet in group]
    merged.sort(key=lambda s: s["score"], reverse=True)
    merged = merged[:k]

    vector_ids = [s["vector_id"] for s in merged]
    texts: dict[str, str] = {}
    chunk_ids: dict[str, int] = {}
    if vector_ids:
        own_session = db is None
        if db is None:
            db = SessionLocal()
        try:
            rows = db.scalars(select(KbChunk).where(KbChunk.vector_id.in_(vector_ids))).all()
            texts = {row.vector_id: row.content for row in rows}
            chunk_ids = {row.vector_id: row.id for row in rows}
        finally:
            if own_session:
                db.close()
    return [
        {**s, "text": texts[s["vector_id"]], "chunk_id": chunk_ids.get(s["vector_id"])}
        for s in merged
        if texts.get(s["vector_id"])
    ]


def get_bidding_context(
    tender_title: str, top_k: int | None = None, db: Session | None = None
) -> dict:
    """招投标专用搜索增强：查历史标书库（kb_type=2），返回相似段落与引用 doc_id 列表。

    Embedding 服务不可用（缺 DASHSCOPE_API_KEY）或 Qdrant 检索失败时降级返回空结果，
    不抛异常（供 LangGraph rag_recall 节点安全调用）。

    返回：{"context": 段落文本, "reference_doc_ids": [doc_id...], "doc_titles": [标题...]}。
    """
    try:
        snippets = get_rag_context(tender_title, [2], top_k, db=db)
    except Exception as exc:
        logger.warning("get_bidding_context 检索失败（降级为空）: %s", exc)
        snippets = []
    context = "\n\n".join(f"[历史标书 {s['doc_id']}] {s['text']}" for s in snippets)
    reference_doc_ids = sorted({s["doc_id"] for s in snippets if s.get("doc_id") is not None})

    # 补充文档标题（kb_documents）
    doc_titles: list[str] = []
    if reference_doc_ids:
        titles: dict = {}
        db = SessionLocal()
        try:
            for doc in db.scalars(select(KbDocument).where(KbDocument.id.in_(reference_doc_ids))).all():
                titles[doc.id] = doc.doc_title
        finally:
            db.close()
        doc_titles = [titles.get(doc_id, "") for doc_id in reference_doc_ids if titles.get(doc_id)]
    return {
        "context": context,
        "reference_doc_ids": reference_doc_ids,
        "doc_titles": doc_titles,
    }


def get_assessment_context(
    checklist_code: str, checklist_name: str | None = None, top_k: int | None = None,
    db: Session | None = None,
) -> list[dict]:
    """测评核查专用搜索增强：查等保标准库（kb_type=0）+ 企业本地库（kb_type=1）。

    返回 kb_references 结构（供写入 assessment_records.kb_references）：
    [{"doc_id", "doc_title", "kb_type", "chunk", "similarity"}...]。
    """
    query = checklist_name or checklist_code
    snippets = get_rag_context(query, [0, 1], top_k, db=db)

    # 补充文档标题（kb_documents）
    doc_ids = {s["doc_id"] for s in snippets if s.get("doc_id") is not None}
    titles: dict = {}
    if doc_ids:
        own_session = db is None
        if db is None:
            db = SessionLocal()
        try:
            for doc in db.scalars(select(KbDocument).where(KbDocument.id.in_(doc_ids))).all():
                titles[doc.id] = doc.doc_title
        finally:
            if own_session:
                db.close()
    return [
        {
            "doc_id": s["doc_id"],
            "doc_title": titles.get(s["doc_id"], KB_TYPE_NAMES.get(s["kb_type"], "")),
            "kb_type": s["kb_type"],
            "chunk": s["text"],
            "similarity": round(s["score"], 4),
        }
        for s in snippets
    ]


def build_memory_prompt(memory: ConversationBufferWindowMemory, rag_context: str | None = None) -> dict:
    """将历史记忆与 RAG 检索结果组装为 Prompt 变量。

    返回 {"history": 历史对话文本, "rag_context": 检索片段文本}，供调用方合并进 Prompt 变量。
    rag_context 无检索命中时填充空字符串，保证 Prompt 模板变量齐全。
    """
    return {
        "history": memory.load_memory_variables({}).get("history", ""),
        "rag_context": rag_context or "",
    }


# ---------------------------------------------------------------------------
# RAG 对话链路：意图判断 / 检索 / 注入 / 来源（知识问答 intent=3）
# ---------------------------------------------------------------------------

# 确认语 / 礼貌语（整句精确匹配，不触发检索）
_ACK_WORDS = {"好的", "可以", "是的", "嗯", "嗯嗯", "对", "没问题", "知道了", "明白", "收到", "好"}
_PLEASANTRIES = {"谢谢", "多谢", "辛苦了", "感谢", "谢谢您"}
# 推进语（前缀匹配，不触发检索）
_CONTINUE_PREFIXES = ("继续", "接着", "下一步", "然后", "开始吧", "开始", "请继续")


def should_retrieve(request_text: str) -> bool:
    """轻量意图判断：跳过空输入、极短输入、确认语、礼貌语与推进语。

    返回 True 表示该轮用户输入值得触发知识库检索（避免对寒暄/推进消耗 Embedding 与 Qdrant）。
    """
    text = (request_text or "").strip()
    if len(text) < 2:
        return False
    if text in _ACK_WORDS or text in _PLEASANTRIES:
        return False
    if any(text.startswith(w) for w in _CONTINUE_PREFIXES):
        return False
    return True


def search_similar_chunks(
    query: str, user_id: int | None = None, db: Session | None = None, top_k: int = 3
) -> list[dict]:
    """知识问答专用检索：等保标准库（公共）+ 企业本地库（按 user_id 隔离）。

    返回完整来源结构（SSE done 与历史消息回显共用）：
    [{"chunk_id", "resource_id", "chunk_index", "file_name", "score", "text"}]。
    检索失败/无命中降级为空列表，不抛异常。
    """
    try:
        snippets = get_rag_context(query, [0, 1], top_k, db=db, user_id=user_id)
    except Exception as exc:
        logger.warning("search_similar_chunks 检索失败（降级为空）: %s", exc)
        return []
    doc_ids = {s["doc_id"] for s in snippets if s.get("doc_id")}
    file_names: dict = {}
    if doc_ids:
        own_session = db is None
        if db is None:
            db = SessionLocal()
        try:
            for doc in db.scalars(select(KbDocument).where(KbDocument.id.in_(doc_ids))).all():
                file_names[doc.id] = Path(doc.file_path).name if doc.file_path else doc.doc_title
        finally:
            if own_session:
                db.close()
    return [
        {
            "chunk_id": s.get("chunk_id"),
            "resource_id": s.get("doc_id"),
            "chunk_index": s.get("chunk_index"),
            "file_name": file_names.get(s.get("doc_id"), ""),
            "score": round(s["score"], 4),
            "text": s["text"],
        }
        for s in snippets
    ]


def format_retrieved_chunks(retrieved_chunks: list[dict]) -> str:
    """将检索片段组装为注入文本，结构为【参考资料】+【用户问题】，作为 rag_context 使用。"""
    if not retrieved_chunks:
        return ""
    parts = [f"[参考片段 {i + 1}] {c['text']}" for i, c in enumerate(retrieved_chunks)]
    return "【参考资料】\n" + "\n".join(parts) + "\n\n【用户问题】"
