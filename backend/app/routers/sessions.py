"""路由层：会话管理与消息查询（需认证）。

- GET/POST/PUT/DELETE /sessions：会话列表分页、新建、改标题、删除（级联清理资源）
- GET /sessions/{session_id}/messages：消息分页，支持游标（before_id）与偏移（page/page_size）两种方式
- 所有操作校验会话归属当前用户
"""

from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import (
    AssessmentRecord,
    BiddingTask,
    ChatMessage,
    ChatSession,
    KbChunk,
    KbDocument,
    Resource,
    ReviewTask,
    TopologyRecord,
    User,
)
from ..db.session import get_db
from ..exceptions import BusinessError, ErrorCode
from ..log import get_logger
from ..schemas.chat import ChatMessageOut, SessionCreate, SessionOut, SessionUpdate
from ..schemas.common import ApiResponse
from ..security import get_current_user
from ..services.minio_client import get_minio_client, object_key_of

router = APIRouter(tags=["会话管理"])
logger = get_logger("sessions")

# 意图类型 -> 默认标题（未传标题时使用）
_INTENT_TITLES = {
    0: "新对话",
    1: "招投标任务",
    2: "测评核查",
    3: "知识问答",
}


def _get_owned_session(db: Session, user: User, session_id: int) -> ChatSession:
    """按归属校验获取会话，不存在或不属于当前用户时抛 404。"""
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在", status_code=404)
    return session


@router.get("/sessions", response_model=ApiResponse, summary="会话列表（分页，按角色筛选）")
def list_sessions(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    role_type: int | None = Query(default=None, ge=0, le=1, description="角色类型筛选：0=商务，1=技术"),
    intent_type: int | None = Query(default=None, ge=0, le=3, description="意图类型筛选：0=对话，1=招投标，2=测评核查，3=知识问答"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """分页查询当前用户会话，按更新时间倒序。"""
    query = select(ChatSession).where(ChatSession.user_id == current_user.id)
    if role_type is not None:
        query = query.where(ChatSession.role_type == role_type)
    if intent_type is not None:
        query = query.where(ChatSession.intent_type == intent_type)

    total = _count_sessions(db, current_user.id, role_type, intent_type)

    rows = db.scalars(
        query.order_by(ChatSession.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return ApiResponse(code=0, message="success", data={
        "items": [SessionOut.model_validate(s).model_dump() for s in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/sessions/{session_id}/topology", response_model=ApiResponse, summary="查询会话网络拓扑")
def get_session_topology(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """查询会话最新生成的网络拓扑数据（topology_data 合并 summary，供前端 Vue Flow 渲染）。"""
    _get_owned_session(db, current_user, session_id)
    record = db.scalar(
        select(TopologyRecord)
        .where(TopologyRecord.session_id == session_id, TopologyRecord.user_id == current_user.id)
        .order_by(TopologyRecord.updated_at.desc())
        .limit(1)
    )
    if record is None or not record.topology_data:
        return ApiResponse(code=0, message="success", data=None, detail=None)
    data = dict(record.topology_data)
    if record.topology_summary:
        data["summary"] = record.topology_summary
    return ApiResponse(code=0, message="success", data=data, detail=None)


@router.post("/sessions/{session_id}/attachment/clear", response_model=ApiResponse, summary="清空会话绑定附件")
def clear_session_attachment(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """清空会话级绑定附件（移除后后续消息不再自动携带该附件内容）。"""
    session = _get_owned_session(db, current_user, session_id)
    session.attachment_name = None
    session.attachment_text = None
    db.commit()
    return ApiResponse(code=0, message="success", data=None, detail=None)


def _count_sessions(db: Session, user_id: int, role_type: int | None, intent_type: int | None = None) -> int:
    """统计当前用户会话数（可选按角色类型 / 意图类型筛选）。"""
    query = select(__import__("sqlalchemy").func.count()).select_from(ChatSession).where(
        ChatSession.user_id == user_id
    )
    if role_type is not None:
        query = query.where(ChatSession.role_type == role_type)
    if intent_type is not None:
        query = query.where(ChatSession.intent_type == intent_type)
    return db.scalar(query) or 0


@router.post("/sessions", response_model=ApiResponse, summary="新建会话")
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """新建会话：必传 role_type 与 intent_type，标题缺省按意图自动生成。"""
    session = ChatSession(
        user_id=current_user.id,
        role_type=body.role_type,
        intent_type=body.intent_type,
        title=body.title or _INTENT_TITLES.get(body.intent_type, "新对话"),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ApiResponse(code=0, message="创建成功", data=SessionOut.model_validate(session).model_dump())


@router.put("/sessions/{session_id}", response_model=ApiResponse, summary="编辑会话标题")
def update_session(
    session_id: int,
    body: SessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """修改会话标题（校验归属）。"""
    session = _get_owned_session(db, current_user, session_id)
    session.title = body.title
    db.commit()
    db.refresh(session)
    return ApiResponse(code=0, message="更新成功", data=SessionOut.model_validate(session).model_dump())


def _collect_resource_ids(messages: list[ChatMessage]) -> set[int]:
    """解析消息 tool_calls，收集引用的 resources.id（arguments/result 中 resource_id 字段）。"""
    ids: set[int] = set()
    for message in messages:
        for call in message.tool_calls or []:
            if not isinstance(call, dict):
                continue
            for key in ("arguments", "result"):
                payload = call.get(key)
                if isinstance(payload, dict):
                    resource_id = payload.get("resource_id")
                    if isinstance(resource_id, int):
                        ids.add(resource_id)
    return ids


def _delete_resources(db: Session, resource_ids: set[int]) -> None:
    """删除资源元数据与 MinIO 对象（先删对象，再删元数据，MinIO 不可用不阻断）。"""
    resources = db.scalars(select(Resource).where(Resource.id.in_(resource_ids))).all()
    if not resources:
        return
    try:
        client = get_minio_client()
    except Exception:
        logger.warning("MinIO 不可用，仅删除资源元数据，对象文件待人工清理")
        client = None
    for resource in resources:
        if client is not None:
            object_key = object_key_of(resource.storage_path)
            if object_key:
                try:
                    client.remove_object(settings.minio_bucket, object_key)
                except Exception:
                    logger.warning("MinIO 对象删除失败 storage_path=%s", resource.storage_path)
        db.delete(resource)


@router.delete("/sessions/{session_id}", response_model=ApiResponse, summary="删除会话")
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """删除会话及全部关联数据（校验归属）：子表记录、会话本身、tool_calls 引用的资源。"""
    session = _get_owned_session(db, current_user, session_id)

    # 先收集 tool_calls 引用的资源 ID，再删消息，避免引用丢失
    messages = db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)).all()
    resource_ids = _collect_resource_ids(messages)

    # 先删全部关联子记录（FK 未配置级联），再删会话本身，避免外键约束报错
    for model in (ChatMessage, BiddingTask, AssessmentRecord, ReviewTask, TopologyRecord):
        db.execute(delete(model).where(model.session_id == session_id))
    db.delete(session)

    # 删除资源元数据与 MinIO 对象（resources 与会话无外键，同一事务内提交）
    if resource_ids:
        _delete_resources(db, resource_ids)

    db.commit()
    return ApiResponse(code=0, message="删除成功", data=None)


def _resolve_task_payload(db: Session, session: ChatSession) -> Any:
    """按会话意图类型解析 task_id 任务卡片数据。

    - intent_type=1（招投标）：返回 {"id", "status"}，指向最近一条 bidding_tasks；
    - intent_type=2（测评核查）：返回该会话下全部 assessment_records 摘要列表；
    - intent_type=0/3（对话/知识问答）：无任务卡片，返回 None。
    """
    if session.intent_type == 1:
        task = db.scalar(
            select(BiddingTask)
            .where(BiddingTask.session_id == session.id)
            .order_by(BiddingTask.id.desc())
            .limit(1)
        )
        if task is None:
            return None
        return {"id": task.id, "status": task.status}

    if session.intent_type == 2:
        records = db.scalars(
            select(AssessmentRecord)
            .where(AssessmentRecord.session_id == session.id)
            .order_by(AssessmentRecord.checklist_code)
        ).all()
        if not records:
            return None
        return [
            {
                "id": r.id,
                "status": r.status,
                "checklist_code": r.checklist_code,
                "checklist_name": r.checklist_name,
                "confidence": r.confidence,
            }
            for r in records
        ]

    return None


def _resolve_reference_sources(message: ChatMessage, db: Session) -> list[dict]:
    """按 reference_sources（chunk_id + score）回查 kb_chunks/kb_documents 重拼完整来源。

    知识块已删除时返回"该参考片段已被删除"提示，保证历史消息仍能回显来源。
    返回结构：{"chunk_id", "resource_id", "chunk_index", "file_name", "score", "text"}。
    """
    refs = message.reference_sources or []
    if not refs:
        return []
    chunk_ids = [r["chunk_id"] for r in refs if r.get("chunk_id")]
    if not chunk_ids:
        return []
    chunks = db.scalars(select(KbChunk).where(KbChunk.id.in_(chunk_ids))).all()
    chunk_map = {c.id: c for c in chunks}
    doc_ids = {c.doc_id for c in chunks}
    doc_map: dict = {}
    if doc_ids:
        for doc in db.scalars(select(KbDocument).where(KbDocument.id.in_(doc_ids))).all():
            doc_map[doc.id] = doc

    sources: list[dict] = []
    for ref in refs:
        chunk = chunk_map.get(ref.get("chunk_id"))
        if chunk is None:
            sources.append({
                "chunk_id": ref.get("chunk_id"),
                "resource_id": None, "chunk_index": None, "file_name": None,
                "score": ref.get("score"), "text": "该参考片段已被删除",
            })
            continue
        doc = doc_map.get(chunk.doc_id)
        sources.append({
            "chunk_id": chunk.id,
            "resource_id": chunk.doc_id,
            "chunk_index": chunk.chunk_index,
            "file_name": Path(doc.file_path).name if doc and doc.file_path else (doc.doc_title if doc else ""),
            "score": ref.get("score"),
            "text": chunk.content,
        })
    return sources


@router.get("/sessions/{session_id}/messages", response_model=ApiResponse, summary="按会话分页查询消息")
def list_messages(
    session_id: int,
    page: int | None = Query(default=None, ge=1, description="页码（配合 page_size，按时间正序偏移分页）"),
    page_size: int | None = Query(default=None, ge=1, le=100, description="每页条数（偏移分页模式）"),
    before_id: int | None = Query(default=None, description="游标：返回 id 小于该值的更早消息"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数（游标模式）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """分页查询消息，返回结果均按时间正序。

    两种分页方式（二选一）：
    - 游标模式（默认）：before_id 为游标向前翻页，适合"上拉加载更早消息"；
    - 偏移模式：page + page_size，按 created_at 升序偏移分页（接口规范）。
    每条消息附带会话的 intent_type 与任务卡片数据 task_id。
    """
    session = _get_owned_session(db, current_user, session_id)
    task_payload = _resolve_task_payload(db, session)

    def enrich(message: ChatMessage) -> dict:
        item = ChatMessageOut.model_validate(message).model_dump()
        item["intent_type"] = session.intent_type
        item["task_id"] = task_payload
        # 知识问答引用来源：按 reference_sources 回查 kb_chunks/kb_documents 重拼完整 sources
        item["sources"] = _resolve_reference_sources(message, db)
        return item

    # 偏移分页：按 created_at 升序（page/page_size 模式）
    if page is not None:
        size = page_size or 20
        total = db.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)
        ) or 0
        rows = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
        return ApiResponse(code=0, message="success", data={
            "items": [enrich(m) for m in rows],
            "total": total,
            "page": page,
            "page_size": size,
            "has_more": page * size < total,
        })

    # 游标分页：返回最近 limit 条，以 before_id 向前翻页
    query = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    rows = db.scalars(query).all()

    # 反转为时间正序，便于前端直接渲染
    items = [enrich(m) for m in reversed(rows)]
    return ApiResponse(code=0, message="success", data={
        "items": items,
        "has_more": len(rows) == limit,
        "before_id": rows[0].id if rows else None,
    })
