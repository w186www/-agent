"""路由层：流式聊天（SSE）与人工审核（HITL）。

- POST /chat/stream：SSE 流式聊天，按意图类型分发链路（对话/知识问答/招投标/测评核查），
  流中下发事件：token / tool_call / task_created / hitl / done / error；
- POST /review/{review_task_id}：提交人工审核结果，更新审核任务与源任务状态；
- POST /chat/{thread_id}/resume：恢复 HITL 中断的招投标对话，支持两个中断点
  （review_parsed 解析确认 / review_selfcheck 自检审核）。

链路编排复用 AI 三层：模型层（get_deepseek）+ 提示词层（get_xxx_prompt / build_chain）
+ 记忆层（get_session_memory / RAG 上下文），工具层（app.ai.tools）执行真实工具。
招投标链路为 LangGraph 状态机：搜索→下载→解析→（HITL1）→RAG 召回→标书生成→自检→（HITL2）。
"""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.graph import build_assessment_graph, prepare_generate_state
from ..ai.llm import get_deepseek
from ..ai.memory import (
    build_memory_prompt,
    format_retrieved_chunks,
    get_rag_context,
    get_session_memory,
    search_similar_chunks,
    should_retrieve,
)
from ..ai.prompt_layer import (
    build_bidding_graph,
    build_chain,
    get_knowledge_prompt,
)
from ..config import settings
from ..db.models import AssessmentRecord, BiddingTask, ChatMessage, ChatSession, ReviewTask, TopologyRecord, User
from ..db.session import get_db
from ..exceptions import BusinessError, ErrorCode
from ..log import get_logger
from ..schemas.chat import ResumeRequest, ReviewRequest, StreamChatRequest
from ..schemas.common import ApiResponse
from ..security import get_current_user

router = APIRouter(tags=["流式聊天与审核"])
logger = get_logger("chat_stream")

# 审核动作 -> review_tasks.review_result（0=通过，1=驳回，2=修改后通过）
_ACTION_TO_RESULT = {"approve": 0, "reject": 1, "modified": 2}

# review_tasks.task_type：0=审核（报价/自检/投标文件），1=低置信度复核，2=解析结果确认，3=自检审核
_REVIEW_TYPE_PARSED = 2
_REVIEW_TYPE_SELFCHECK = 3
# 投标文件审核的 review_data 标记：task_type=0 同时承载报价/投标文件审核，
# 以 review_data["bidding_review"]=True 与报价审核区分（前端据此渲染对应审核面板）
_BIDDING_REVIEW_MARKER = "bidding_review"

# LangGraph 固定节点工具（generate/selfcheck 为图节点直接调用，不在 bind_tools 中，
# SSE 事件通过 on_chain_end 捕获后按工具调用事件推送）
_FIXED_NODE_TOOLS = {"generate": "generate_bidding", "selfcheck": "self_check"}


def _sse(event: dict) -> str:
    """SSE 事件序列化：data: {json}\n\n"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _with_heartbeat(inner, interval: float = 10.0):
    """给 SSE 流加心跳：inner 空闲超过 interval 秒时输出 ': ping' 注释行。

    浏览器/中间层可能在"响应头之后长时间无数据"时中断连接（net::ERR_ABORTED），
    心跳保持连接活跃；SSE 注释行（冒号开头）不触发前端事件解析，纯保活用途。
    """
    iterator = inner.__aiter__()
    next_task = asyncio.ensure_future(anext(iterator))
    sleep_task = asyncio.ensure_future(asyncio.sleep(interval))
    # 响应头之后立即输出启动心跳，覆盖首个事件前的首包延迟窗口
    yield ": start\n\n"
    while True:
        done, _ = await asyncio.wait({next_task, sleep_task}, return_when=asyncio.FIRST_COMPLETED)
        if next_task in done:
            try:
                yield next_task.result()
            except StopAsyncIteration:
                break
            next_task = asyncio.ensure_future(anext(iterator))
            sleep_task = asyncio.ensure_future(asyncio.sleep(interval))
        else:
            yield ": ping\n\n"
            sleep_task = asyncio.ensure_future(asyncio.sleep(interval))
    for task in (next_task, sleep_task):
        if not task.done():
            task.cancel()


def _tool_call_payload(call: dict) -> dict:
    """tool_call 事件载荷：tool_name/arguments/result/duration_ms（与前端 streamChat.ts 约定对齐）。

    注：落库 tool_calls 保持 name 字段（消息持久化），仅事件载荷按前端契约命名为 tool_name。
    """
    return {
        "tool_name": call["name"],
        "arguments": call["arguments"],
        "result": call["result"],
        "duration_ms": call["duration_ms"],
    }


def _now() -> int:
    return int(time.time())


def _parse_review_data(parse_result: str | None) -> dict:
    """parse_tender 工具结果（JSON 字符串）-> hitl review_data 结构化卡片字段。

    字段与前端「解析结果确认卡片」对齐：项目名称/预算/截止日期/资格要求/评分表/废标项。
    解析失败或无结果时返回空结构，保证卡片字段齐全。
    """
    empty = {
        "project_name": "",
        "budget": None,
        "deadline": None,
        "qualification_requirements": [],
        "scoring_items": [],
        "disqualification_items": [],
    }
    if not parse_result:
        return empty
    try:
        parsed = json.loads(parse_result)
    except (json.JSONDecodeError, TypeError):
        return empty
    if not isinstance(parsed, dict):
        return empty
    return {
        "project_name": parsed.get("project_name") or "",
        "budget": parsed.get("budget"),
        "deadline": parsed.get("deadline"),
        "qualification_requirements": parsed.get("qualification_requirements") or [],
        "scoring_items": parsed.get("scoring_items") or [],
        "disqualification_items": parsed.get("disqualification_items") or [],
    }


def _infer_system_level(content: str) -> int:
    """从用户消息推断等保级别：0=二级，1=三级，2=四级（默认三级）。"""
    if "二级" in content:
        return 0
    if "四级" in content:
        return 2
    return 1


def _extract_parse_result_from_db(db: Session, session_id: int) -> str | None:
    """从会话最新 assistant 消息的 tool_calls 中提取最近一次 parse_tender 的成功结果。

    数据库消息只存 Human/AI 两类，parse_tender 的 ToolMessage 不在其中，但工具调用记录
    （name=parse_tender + result=JSON）已持久化在 chat_messages.tool_calls，"开始编写"
    请求据此恢复招标解析结果用于标书生成。
    """
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == 1)
        .order_by(ChatMessage.id.desc()).limit(30)
    ).all()
    for msg in messages:
        for call in (msg.tool_calls or []):
            if not isinstance(call, dict) or call.get("name") != "parse_tender":
                continue
            result = call.get("result")
            if not isinstance(result, str) or not result.strip():
                continue
            try:
                parsed = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict) and not parsed.get("error"):
                return result
    return None


def _selfcheck_review_data(bidding_sections, compliance_result) -> dict:
    """自检审核 hitl 的 review_data：投标内容 + 三维度自检结果 + 汇总。"""
    return {
        "bidding_sections": bidding_sections or {},
        "compliance_result": compliance_result or {},
        "summary": (compliance_result or {}).get("summary", ""),
    }


def _review_summary(review: ReviewTask) -> dict:
    """审核任务摘要（GET /review 列表项）：按 task_type / review_data 形状派生展示字段。"""
    data = review.review_data or {}
    if review.task_type == 1:
        category = "低置信度复核"
        title = f"{data.get('checklist_name') or '测评控制点'} — 人工复核"
        summary = data.get("confidence")
        confidence = f"置信度 {data.get('confidence', '?')}"
    elif review.task_type == 2:
        category = "解析结果确认"
        title = data.get("project_name") or "招标文件解析"
        summary = data.get("budget") or "待确认"
        confidence = "等待人工确认"
    elif review.task_type == 3:
        category = "自检审核"
        title = "投标文件自检"
        summary = data.get("summary") or "待审核"
        confidence = "等待人工确认"
    elif data.get(_BIDDING_REVIEW_MARKER):
        category = "投标文件审核"
        title = "投标文件审核"
        summary = data.get("summary") or "待审核"
        human_count = sum(
            1 for i in (data.get("items") or []) if isinstance(i, dict) and i.get("need_human")
        )
        confidence = f"{human_count} 项需人工确认"
    else:
        category = "报价审核"
        title = "报价审核"
        summary = data.get("ai_suggestion") or "待审核"
        confidence = "等待人工确认"
    return {
        "review_task_id": review.id,
        "task_type": review.task_type,
        "source_type": review.source_type,
        "source_id": review.source_id,
        "category": category,
        "title": title,
        "summary": summary,
        "confidence": confidence,
        "created_at": review.created_at,
    }


def _apply_node_end(task, data: dict) -> None:
    """generate/selfcheck 节点完成时落库中间状态（规格：generate=2 编写中，selfcheck=3 废标检查中）。

    node_end 事件由 _iter_graph_events 在固定节点完成时产出；调用方在事件循环内处理
    后需自行 commit，终态（4/5）由事件循环结束后的状态联动统一写入。
    """
    if task is None:
        return
    node = data.get("node")
    output = data.get("output") or {}
    if node == "generate":
        task.bidding_sections = output.get("bidding_sections")
        task.status = 2
    elif node == "selfcheck":
        task.compliance_result = output.get("compliance_result")
        task.status = 3
    task.updated_at = _now()


def _mark_review_task(
    db: Session, session_id: int, source_id: int, task_type: int, review_result: int
) -> None:
    """标记会话下指定类型最新一条待审核的招投标审核任务为已审核（resume 联动审核）。

    同一 bidding_task 可能挂多个类型待审任务（解析确认/自检审核），必须按 task_type 过滤，
    否则会把未到期的审核任务误标为已处理。
    """
    review = db.scalar(
        select(ReviewTask)
        .where(
            ReviewTask.session_id == session_id,
            ReviewTask.source_type == 0,
            ReviewTask.source_id == source_id,
            ReviewTask.task_type == task_type,
            ReviewTask.status == 0,
        )
        .order_by(ReviewTask.id.desc()).limit(1)
    )
    if review is not None:
        review.review_result = review_result
        review.status = 1
        review.reviewed_at = _now()


async def _iter_graph_events(graph, config, initial_state=None, resume_command=None):
    """统一迭代招投标图事件，产出 (kind, data) 元组（/chat/stream 与 resume 复用）。

    kind 取值：
    - "token"：LLM 流式文本或固定节点提示消息，data 为文本；
    - "tool_call"：绑定工具（search/download/parse）或固定节点工具（generate/self_check）
      调用完成，data 为 {"name", "arguments", "result", "duration_ms"}；
    - "node_end"：generate/selfcheck 节点完成，data 为 {"node", "output"}（供调用方落库）。
    """
    pending_tools: dict[str, dict] = {}
    node_starts: dict[str, float] = {}
    event_input = resume_command if resume_command is not None else initial_state
    async for event in graph.astream_events(event_input, config=config, version="v2"):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = getattr(event["data"].get("chunk"), "content", None)
            if content:
                yield ("token", content)
        elif kind == "on_tool_start":
            run_id = event.get("run_id")
            name = event.get("name")
            if name and run_id:
                pending_tools[run_id] = {
                    "name": name,
                    "arguments": event["data"].get("input"),
                    "start": time.perf_counter(),
                }
        elif kind == "on_tool_end":
            run_id = event.get("run_id")
            call = pending_tools.pop(run_id, None)
            if call is not None:
                output = event["data"].get("output")
                if hasattr(output, "content"):
                    output = output.content
                call["result"] = output
                call["duration_ms"] = round((time.perf_counter() - call.pop("start")) * 1000)
                yield ("tool_call", call)
        elif kind in ("on_chain_start", "on_chain_end"):
            name = event.get("name")
            if kind == "on_chain_start" and name in _FIXED_NODE_TOOLS:
                node_starts[name] = time.perf_counter()
            elif kind == "on_chain_end" and name in _FIXED_NODE_TOOLS:
                output = event["data"].get("output") or {}
                duration_ms = round(
                    (time.perf_counter() - node_starts.pop(name, time.perf_counter())) * 1000
                )
                # 节点返回的提示消息转 token 事件，让前端看到流程进度
                for msg in output.get("messages") or []:
                    content = getattr(msg, "content", None)
                    if content:
                        yield ("token", content)
                if name == "generate":
                    node_result = output.get("bidding_sections") or {"error": "标书生成未产出内容"}
                    node_arguments = {"section": "all"}
                else:
                    node_result = output.get("compliance_result") or {"error": "自检未产出结果"}
                    node_arguments = {}
                yield ("tool_call", {
                    "name": _FIXED_NODE_TOOLS[name],
                    "arguments": node_arguments,
                    "result": node_result,
                    "duration_ms": duration_ms,
                })
                yield ("node_end", {"node": name, "output": output})
            elif kind == "on_chain_end" and name == "checklist":
                # 技术线清单节点：把写库完成的确认消息转 token 事件（清单数据由 task_created 推送）
                output = event["data"].get("output") or {}
                for msg in output.get("messages") or []:
                    content = getattr(msg, "content", None)
                    if content:
                        yield ("token", content)


@router.post("/chat/stream", summary="流式聊天（SSE）")
def chat_stream(
    req: StreamChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 流式聊天。事件类型约定（与前端 streamChat.ts 对齐）：

    - token：增量文本，字段 content；
    - tool_call：Agent 工具调用，payload 含 tool_name/arguments/result/duration_ms；
    - task_created：任务创建，payload 含 intent_type/task_id（intent=2 时 task_id 为控制点摘要列表）；
    - hitl：人工审核触发，payload 含 review_task_id/task_type/source_type/source_id/review_data；
    - done：流结束；error：错误，payload.message 为错误信息。
    """
    # 校验会话归属（鉴权失败直接返回 404 而非 SSE 错误）
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == req.session_id, ChatSession.user_id == current_user.id
        )
    )
    if session is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在", status_code=404)
    # 保存用户消息（AI 消息在流式生成结束后保存）
    db.add(ChatMessage(
        user_id=current_user.id, session_id=req.session_id, role=0,
        request_id=f"u{_now()}", content=req.content, created_at=_now(),
    ))
    db.commit()

    async def generate():
        tool_calls: list[dict] = []
        ai_content = ""
        retrieved_chunks: list[dict] = []
        try:
            intent_type = req.intent_type
            prompt = None
            rag_context = ""
            task_payload = None
            hitl_payload = None
            extra_vars: dict = {}

            # ---------- 招投标链路（LangGraph 状态机：搜索→解析→(HITL1)→RAG→生成→自检→(HITL2)） ----------
            if intent_type == 1:
                memory = get_session_memory(req.session_id, db=db)
                graph = build_bidding_graph()
                # 初始 state：历史消息 + 当前用户消息（每个请求独立 thread_id，为后续 HITL 预留）
                # 上传场景（upload_purpose=1/5）：把文件路径写入消息上下文，
                # 供 Agent 直接调用 parse_tender（招标文件）或 review_bidding（投标文件）
                user_content = req.content
                if req.upload_purpose in (1, 5) and req.file_path:
                    file_kind = "招标" if req.upload_purpose == 1 else "投标"
                    user_content = (
                        f"{req.content}\n\n[上传文件] 用户上传了{file_kind}文件，文件路径：{req.file_path}"
                    )
                    # 投标文件审核：若会话中已解析过招标文件，注入解析结果供交叉比对废标项
                    if req.upload_purpose == 5:
                        tender_info = _extract_parse_result_from_db(db, req.session_id)
                        if tender_info:
                            user_content += f"\n[招标文件解析结果（JSON，用于交叉比对）] {tender_info}"
                messages = list(memory.buffer_as_messages) + [HumanMessage(content=user_content)]
                thread_id = f"req-{req.session_id}-{_now()}"
                config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": settings.graph_recursion_limit,
                }
                initial_state: dict = {"messages": messages}
                # "开始编写"请求：从会话历史 tool_calls 恢复招标解析结果并重召回参考标书，
                # 注入 human_confirmed/rag_context/tender_info，驱动 generate 链路
                if "开始编写" in req.content:
                    tender_info = _extract_parse_result_from_db(db, req.session_id)
                    if tender_info:
                        initial_state.update(prepare_generate_state(tender_info))
                        logger.info("[graph] 识别到开始编写请求，注入生成初始状态 thread_id=%s", thread_id)

                # 先创建/复用招投标任务（status=0 初始），供 generate/selfcheck 节点落库中间状态
                now = _now()
                task = db.scalar(
                    select(BiddingTask)
                    .where(BiddingTask.session_id == req.session_id)
                    .order_by(BiddingTask.id.desc()).limit(1)
                )
                if task is None:
                    task = BiddingTask(
                        user_id=current_user.id, session_id=req.session_id,
                        tender_title=req.content[:50] or "招投标任务", status=0,
                        reference_doc_ids=[], created_at=now, updated_at=now,
                    )
                    db.add(task)
                    db.commit()
                # 上传场景业务联动（/upload/file 已写入，此处兜底确保文件路径在任务上）：
                # upload_purpose=1 -> tender_file_path；upload_purpose=5 -> bidding_sections.uploaded_bidding_file
                if req.upload_purpose == 1 and req.file_path and not task.tender_file_path:
                    task.tender_file_path = req.file_path
                    db.commit()
                elif req.upload_purpose == 5 and req.file_path:
                    task.bidding_sections = dict(task.bidding_sections or {})
                    task.bidding_sections["uploaded_bidding_file"] = req.file_path
                    db.commit()

                async for kind, data in _iter_graph_events(graph, config, initial_state=initial_state):
                    if kind == "token":
                        ai_content += data
                        yield _sse({"type": "token", "content": data})
                    elif kind == "tool_call":
                        tool_calls.append(data)
                        yield _sse({"type": "tool_call", "payload": _tool_call_payload(data)})
                    elif kind == "node_end":
                        # 中间状态落库：generate 完成=2 编写中 / selfcheck 完成=3 废标检查中
                        _apply_node_end(task, data)
                        db.commit()

                # 图执行状态：next 指向哪个节点 = 中断在哪个 HITL（review_parsed / review_selfcheck）
                graph_state = graph.get_state(config)
                pending_node = graph_state.next[0] if getattr(graph_state, "next", None) else None
                final_values = graph_state.values or {}
                if pending_node:
                    logger.info("[graph] interrupt at %s thread_id=%s", pending_node, thread_id)

                # 投标文件审核结果（upload_purpose=5）：Agent 调用 review_bidding 后，
                # 结果创建为审核任务并触发 HITL（需人工逐条确认 need_human 项）
                bidding_review_result = next(
                    (c["result"] for c in tool_calls if c["name"] == "review_bidding" and c.get("result")),
                    None,
                )

                # 终态落库：标题取搜索结果首条（超出截断）
                now = _now()
                tender_title = req.content[:50] or "招投标任务"
                search_result = next(
                    (c["result"] for c in tool_calls if c["name"] == "search_tender" and c.get("result")),
                    None,
                )
                if search_result:
                    try:
                        parsed = json.loads(search_result)
                        if isinstance(parsed, list) and parsed and parsed[0].get("title"):
                            tender_title = str(parsed[0]["title"])[:100]
                    except (json.JSONDecodeError, TypeError):
                        pass
                # 状态流转：review_parsed 中断=1（已解析待确认）；review_selfcheck 中断=4（待人工审核）
                # 并写入生成内容与自检结果；正常结束按 selfcheck_approved 判定 5/2；
                # 投标文件审核（review_bidding）结果待人工确认=4
                if pending_node == "review_selfcheck":
                    task.status = 4
                    if final_values.get("bidding_sections") is not None:
                        task.bidding_sections = final_values.get("bidding_sections")
                    if final_values.get("compliance_result") is not None:
                        task.compliance_result = final_values.get("compliance_result")
                elif pending_node == "review_parsed":
                    task.status = 1
                elif final_values.get("selfcheck_approved"):
                    task.status = 5
                    if final_values.get("bidding_sections") is not None:
                        task.bidding_sections = final_values.get("bidding_sections")
                    if final_values.get("compliance_result") is not None:
                        task.compliance_result = final_values.get("compliance_result")
                elif bidding_review_result is not None:
                    task.status = 4
                else:
                    task.status = 2
                task.tender_title = tender_title
                task.reference_doc_ids = []
                task.updated_at = now
                db.commit()
                db.refresh(task)
                task_payload = {"id": task.id, "status": task.status}
                yield _sse({"type": "task_created", "payload": {"intent_type": 1, "task_id": task_payload}})

                # HITL 中断：推送对应审核卡片（review_data 结构化，含 thread_id 供 resume）
                if pending_node == "review_parsed":
                    parse_result = next(
                        (c["result"] for c in tool_calls if c["name"] == "parse_tender" and c.get("result")),
                        None,
                    )
                    hitl_payload = {
                        "review_task_id": None, "task_type": _REVIEW_TYPE_PARSED, "source_type": 0,
                        "source_id": task.id, "thread_id": thread_id,
                        "review_data": _parse_review_data(parse_result),
                    }
                elif pending_node == "review_selfcheck":
                    hitl_payload = {
                        "review_task_id": None, "task_type": _REVIEW_TYPE_SELFCHECK, "source_type": 0,
                        "source_id": task.id, "thread_id": thread_id,
                        "review_data": _selfcheck_review_data(
                            final_values.get("bidding_sections"), final_values.get("compliance_result"),
                        ),
                    }
                elif bidding_review_result is not None:
                    # 投标文件审核：review_bidding 结果暂存 review_tasks.review_data（task_type=0/source_type=0），
                    # 不新建独立报告表；结果带 bidding_review 标记与报价审核区分
                    try:
                        parsed_review = json.loads(bidding_review_result) if isinstance(bidding_review_result, str) else {}
                    except (json.JSONDecodeError, TypeError):
                        parsed_review = {"error": "投标文件审核结果无法解析"}
                    if not isinstance(parsed_review, dict):
                        parsed_review = {"error": "投标文件审核结果格式异常"}
                    parsed_review.setdefault(_BIDDING_REVIEW_MARKER, True)
                    hitl_payload = {
                        "review_task_id": None, "task_type": 0, "source_type": 0,
                        "source_id": task.id,
                        "review_data": parsed_review,
                    }

            # ---------- 测评核查链路（技术线状态机：Agent 自主调用 generate_checklist -> checklist 节点写库） ----------
            elif intent_type == 2:
                memory = get_session_memory(req.session_id, db=db)
                graph = build_assessment_graph()
                # 附件场景：优先用本次消息临时携带的提取文本（上传资产核查表后发送）；
                # 否则读取会话级绑定附件（对话助手上传附件时存入 sessions.attachment_text），
                # 拼为【资产核查表内容】前缀注入本轮上下文，供 generate_topology 使用
                user_content = req.content
                file_text = req.file_extracted_text
                if not file_text and req.session_id is not None:
                    sess = db.get(ChatSession, req.session_id)
                    if sess is not None and sess.user_id == current_user.id and sess.attachment_text:
                        file_text = sess.attachment_text
                if file_text:
                    user_content = (
                        f"{req.content}\n\n[用户上传了附件（资产核查表），其内容如下]\n{file_text}"
                    )
                messages = list(memory.buffer_as_messages) + [HumanMessage(content=user_content)]
                thread_id = f"assess-{req.session_id}-{_now()}"
                config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": settings.graph_recursion_limit,
                }
                initial_state: dict = {
                    "messages": messages,
                    "session_id": req.session_id,
                    "user_id": current_user.id,
                    "system_level": _infer_system_level(req.content),
                }
                async for kind, data in _iter_graph_events(graph, config, initial_state=initial_state):
                    if kind == "token":
                        ai_content += data
                        yield _sse({"type": "token", "content": data})
                    elif kind == "tool_call":
                        tool_calls.append(data)
                        yield _sse({"type": "tool_call", "payload": _tool_call_payload(data)})

                # 拓扑生成：Agent 调用 generate_topology 后，覆盖写入 TopologyRecord 并推送 topology 事件
                topology_result = next(
                    (c["result"] for c in tool_calls if c["name"] == "generate_topology" and c.get("result")),
                    None,
                )
                if topology_result:
                    try:
                        parsed = json.loads(topology_result)
                    except (TypeError, json.JSONDecodeError):
                        parsed = {}
                    if isinstance(parsed, dict) and isinstance(parsed.get("nodes"), list) and parsed["nodes"]:
                        now = _now()
                        for old in db.scalars(
                            select(TopologyRecord).where(
                                TopologyRecord.session_id == req.session_id,
                                TopologyRecord.user_id == current_user.id,
                            )
                        ).all():
                            db.delete(old)
                        db.flush()
                        db.add(TopologyRecord(
                            session_id=req.session_id, user_id=current_user.id,
                            asset_file_path=req.file_path or "资产核查表",
                            topology_data={k: v for k, v in parsed.items() if k != "summary"},
                            topology_summary=parsed.get("summary"),
                            status=1, created_at=now, updated_at=now,
                        ))
                        db.commit()
                        yield _sse({"type": "topology", "payload": {"topology_data": parsed}})

                # 清单生成后：推送 task_created（task_type=assessment，含控制点摘要列表供前端渲染）
                records = db.scalars(
                    select(AssessmentRecord)
                    .where(AssessmentRecord.session_id == req.session_id, AssessmentRecord.user_id == current_user.id)
                    .order_by(AssessmentRecord.checklist_code)
                ).all()
                task_payload = [
                    {"id": r.id, "status": r.status, "checklist_code": r.checklist_code,
                     "checklist_name": r.checklist_name, "confidence": r.confidence}
                    for r in records
                ]
                yield _sse({"type": "task_created", "payload": {"intent_type": 2, "task_id": task_payload}})

            # ---------- 对话 / 知识问答链路 ----------
            else:
                prompt = get_knowledge_prompt()
                # 知识问答（intent=3）：轻量意图判断 → 检索（企业库按 user_id 隔离）→ 注入【参考资料】
                if intent_type == 3 and should_retrieve(req.content):
                    retrieved_chunks = search_similar_chunks(
                        req.content, current_user.id, db=db, top_k=3
                    )
                    rag_context = format_retrieved_chunks(retrieved_chunks)

            # 文本流式生成（DeepSeek）；招投标/测评核查链路由图状态机产出，跳过
            if intent_type not in (1, 2):
                chain = build_chain(get_deepseek(), prompt)
                memory = get_session_memory(req.session_id, db=db)
                variables = build_memory_prompt(memory, rag_context or None)
                variables.update(extra_vars)
                # 对话 / 知识问答附件：优先使用本次消息临时携带的提取文本；
                # 否则读取会话级绑定附件（上传时存入 sessions.attachment_text），
                # 拼为【附件内容】前缀注入本轮上下文
                file_text = req.file_extracted_text
                if not file_text and req.session_id is not None:
                    sess = db.get(ChatSession, req.session_id)
                    if sess is not None and sess.user_id == current_user.id and sess.attachment_text:
                        file_text = sess.attachment_text
                user_input = req.content
                if file_text:
                    user_input = (
                        f"[用户上传了附件，其内容如下]\n{file_text}\n\n"
                        f"[用户问题]\n{req.content}"
                    )
                variables["input"] = user_input
                async for chunk in chain.astream(variables):
                    if chunk:
                        ai_content += chunk
                        yield _sse({"type": "token", "content": chunk})

            # 创建 HITL 审核任务并下发事件
            if hitl_payload is not None:
                now = _now()
                review = ReviewTask(
                    user_id=current_user.id, session_id=req.session_id,
                    task_type=hitl_payload["task_type"], source_type=hitl_payload["source_type"],
                    source_id=hitl_payload["source_id"],
                    review_data=hitl_payload["review_data"], status=0, created_at=now,
                )
                db.add(review)
                db.commit()
                db.refresh(review)
                hitl_payload["review_task_id"] = review.id
                yield _sse({"type": "hitl", "payload": hitl_payload})

            # 保存 AI 消息（正文 + 工具调用记录 + 知识问答引用来源）
            db.add(ChatMessage(
                user_id=current_user.id, session_id=req.session_id, role=1,
                request_id=f"a{_now()}", content=ai_content,
                tool_calls=tool_calls or None, created_at=_now(),
                reference_sources=[
                    {"chunk_id": s["chunk_id"], "score": s["score"]}
                    for s in retrieved_chunks
                ] or None,
            ))
            db.commit()

            done_payload: dict = {"session_id": req.session_id}
            if retrieved_chunks:
                done_payload["sources"] = retrieved_chunks
            yield _sse({"type": "done", "payload": done_payload})
        except Exception as exc:
            logger.exception("chat_stream 流式生成失败")
            yield _sse({"type": "error", "payload": {"message": f"流式生成失败：{exc}"}})

    return StreamingResponse(
        _with_heartbeat(generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/review/{review_task_id}", response_model=ApiResponse, summary="提交人工审核结果")
def submit_review(
    review_task_id: int,
    req: ReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """HITL 审核：更新审核任务状态，并联动更新源任务（招投标任务 / 测评核查记录）状态。"""
    review = db.get(ReviewTask, review_task_id)
    if review is None or review.user_id != current_user.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "审核任务不存在", status_code=404)
    if review.status != 0:
        raise BusinessError(ErrorCode.VALIDATION, "该审核任务已处理")

    now = _now()
    review.review_result = _ACTION_TO_RESULT[req.action]
    review.review_comment = req.comment
    review.reviewer_id = current_user.id
    review.status = 1
    review.reviewed_at = now

    # 联动更新源任务状态：通过/修改后通过 -> 已完成；驳回 -> 退回待人工处理
    # （自检审核驳回按规格退回 2=编写中，等待重新生成；其余驳回退回 4=待人工审核）
    if review.task_type == _REVIEW_TYPE_SELFCHECK and req.action == "reject":
        source_status = 2
    else:
        source_status = 5 if req.action in ("approve", "modified") else 4
    if review.source_type == 0:
        task = db.get(BiddingTask, review.source_id)
        if task is not None:
            # 修改后通过：用前端提交的修改内容覆盖投标文件各部分
            if req.action == "modified" and req.modified_sections:
                task.bidding_sections = req.modified_sections
            task.status = source_status
            task.updated_at = now
    elif review.source_type == 1:
        record = db.get(AssessmentRecord, review.source_id)
        if record is not None:
            record.status = source_status
            record.updated_at = now
            # 复核结果写回对话（测评核查与对话助手互通）
            result_note = "已确认通过" if source_status == 5 else "已驳回待整改"
            from ..services.assessment_service import write_report_message

            write_report_message(
                db, record.user_id, record.session_id,
                f"【测评核查】第 {record.checklist_code} 项（{record.checklist_name}）{result_note}。",
            )

    db.commit()
    return ApiResponse(code=0, message="审核完成", data={
        "review_task_id": review.id,
        "review_result": review.review_result,
        "status": review.status,
        "source_type": review.source_type,
        "source_id": review.source_id,
        "source_status": source_status,
    })


@router.get("/review", response_model=ApiResponse, summary="审核任务列表（待审核/已审核）")
def list_reviews(
    status: int = 0,
    session_id: int | None = Query(default=None, description="按会话（测评项目/招投标任务）筛选，为空返回全部"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """获取当前用户的审核任务列表，按 task_type 分组返回摘要。

    status=0 待审核，1 已审核；groups 结构：{task_type: [摘要, ...]}，
    摘要字段：review_task_id/task_type/source_type/source_id/category/title/summary/confidence/created_at。
    session_id 非空时只返回该会话（测评项目）下的审核任务。
    """
    query = select(ReviewTask).where(
        ReviewTask.user_id == current_user.id, ReviewTask.status == status
    )
    if session_id is not None:
        query = query.where(ReviewTask.session_id == session_id)
    reviews = db.scalars(query.order_by(ReviewTask.id.desc())).all()
    groups: dict[int, list[dict]] = {}
    for review in reviews:
        groups.setdefault(review.task_type, []).append(_review_summary(review))
    return ApiResponse(code=0, message="success", data={
        "status": status,
        "total": len(reviews),
        "groups": groups,
    })


@router.get("/review/{review_task_id}", response_model=ApiResponse, summary="审核任务详情")
def get_review(
    review_task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """获取审核任务详情：完整 review_data + review_result + review_comment + reviewer 信息。"""
    review = db.get(ReviewTask, review_task_id)
    if review is None or review.user_id != current_user.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "审核任务不存在", status_code=404)
    reviewer = None
    if review.reviewer_id is not None:
        reviewer_user = db.get(User, review.reviewer_id)
        if reviewer_user is not None:
            reviewer = {
                "username": reviewer_user.username,
                "display_name": reviewer_user.display_name,
            }
    return ApiResponse(code=0, message="success", data={
        "review_task_id": review.id,
        "task_type": review.task_type,
        "source_type": review.source_type,
        "source_id": review.source_id,
        "review_data": review.review_data,
        "review_result": review.review_result,
        "review_comment": review.review_comment,
        "reviewer": reviewer,
        "status": review.status,
        "created_at": review.created_at,
        "reviewed_at": review.reviewed_at,
    })


@router.post("/chat/{thread_id}/resume", summary="恢复 HITL 中断的招投标对话（SSE）")
def resume_chat(
    thread_id: str,
    req: ResumeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """恢复被 HITL 中断的图执行（Command(resume=...)），支持两个中断点。

    - parsed_review（第一个 HITL，review_parsed）：resume={"confirmed": bool}，
      确认后执行 review_parsed -> rag_recall -> agent 召回链路，联动更新
      bidding_tasks（reference_doc_ids + status=2 编写中）；
    - selfcheck_review（第二个 HITL，review_selfcheck）：resume={"approved": bool,
      "modified_sections": {...}}，通过后 status=5（已完成）；驳回后图回到
      generate 重新生成，再次中断时 status=4（待人工审核）并更新投标内容与自检结果。
    resume 类型必须与当前中断点匹配，否则返回错误事件。
    """
    # 校验会话归属与意图（鉴权失败直接返回 404 而非 SSE 错误）
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == req.session_id, ChatSession.user_id == current_user.id
        )
    )
    if session is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在", status_code=404)
    if session.intent_type != 1:
        raise BusinessError(ErrorCode.VALIDATION, "仅招投标会话支持 HITL 恢复")

    graph = build_bidding_graph()
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.graph_recursion_limit,
    }
    # 图状态 next 非空 = 处于中断待确认；为空表示已完成或 thread_id 不存在
    state = graph.get_state(config)
    pending_node = getattr(state, "next", None)
    pending_node = pending_node[0] if pending_node else None
    if pending_node is None:
        raise BusinessError(ErrorCode.VALIDATION, "该对话未处于待确认状态或已结束")
    # resume 类型必须与当前中断点匹配（review_parsed / review_selfcheck）
    expected = "review_parsed" if req.review_type == "parsed_review" else "review_selfcheck"
    if pending_node != expected:
        raise BusinessError(
            ErrorCode.VALIDATION,
            f"当前中断点为 {pending_node}，与恢复类型 {req.review_type} 不匹配",
        )

    async def generate():
        ai_content = ""
        tool_calls: list[dict] = []
        try:
            # 解析确认不通过：标记审核任务为驳回并直接结束，不做图恢复
            if req.review_type == "parsed_review" and not req.confirmed:
                logger.info("[graph] resume（用户不确认解析结果）thread_id=%s", thread_id)
                task = db.scalar(
                    select(BiddingTask)
                    .where(BiddingTask.session_id == req.session_id)
                    .order_by(BiddingTask.id.desc()).limit(1)
                )
                if task is not None:
                    _mark_review_task(db, req.session_id, task.id, _REVIEW_TYPE_PARSED, 1)
                    db.commit()
                yield _sse({"type": "done", "payload": {"session_id": req.session_id}})
                return

            # 组装 resume 载荷：解析确认 / 自检审核（含修改后通过的投标内容）
            if req.review_type == "parsed_review":
                resume_command = Command(resume={"confirmed": True})
            else:
                resume_command = Command(resume={
                    "approved": req.approved,
                    "modified_sections": req.modified_sections,
                })
            logger.info("[graph] resume(%s) thread_id=%s approved=%s", req.review_type, thread_id, req.approved)

            # 任务先查询（驳回重新生成时 generate/selfcheck 节点落库中间状态 2/3）
            task = db.scalar(
                select(BiddingTask)
                .where(BiddingTask.session_id == req.session_id)
                .order_by(BiddingTask.id.desc()).limit(1)
            )
            async for kind, data in _iter_graph_events(graph, config, resume_command=resume_command):
                if kind == "token":
                    ai_content += data
                    yield _sse({"type": "token", "content": data})
                elif kind == "tool_call":
                    tool_calls.append(data)
                    yield _sse({"type": "tool_call", "payload": _tool_call_payload(data)})
                elif kind == "node_end":
                    # 驳回重新生成链路：generate 完成=2 / selfcheck 完成=3
                    _apply_node_end(task, data)
                    db.commit()

            # 恢复完成：状态联动（bidding_tasks 落库 + 审核任务联动 + 新一轮 HITL 卡片）
            now = _now()
            final_state = graph.get_state(config)
            pending_after = getattr(final_state, "next", None)
            pending_after = pending_after[0] if pending_after else None
            values = final_state.values or {}
            task_id = task.id if task is not None else 0
            hitl_payload = None

            if req.review_type == "parsed_review":
                # 解析确认通过：标记审核任务已通过，写入 RAG 命中的 doc_id，status=2 编写中
                _mark_review_task(db, req.session_id, task_id, _REVIEW_TYPE_PARSED, 0)
                doc_ids = values.get("rag_reference_doc_ids") or []
                if task is not None:
                    task.reference_doc_ids = list(doc_ids)
                    task.status = 2
                    task.updated_at = now
            elif req.approved and pending_after is None:
                # 自检审核通过（含修改后通过）：status=5 已完成，modified_sections 覆盖投标内容
                _mark_review_task(
                    db, req.session_id, task_id, _REVIEW_TYPE_SELFCHECK,
                    2 if req.modified_sections else 0,
                )
                if task is not None:
                    task.bidding_sections = req.modified_sections or values.get("bidding_sections")
                    task.compliance_result = values.get("compliance_result")
                    task.status = 5
                    task.updated_at = now
            elif pending_after == "review_selfcheck":
                # 自检审核驳回 -> 图回到 generate 重新生成 -> 自检 -> 再次中断：
                # 标记旧审核任务为驳回，更新投标内容/自检结果，status=4 并推送新一轮审核卡片
                _mark_review_task(db, req.session_id, task_id, _REVIEW_TYPE_SELFCHECK, 1)
                if task is not None:
                    task.bidding_sections = values.get("bidding_sections")
                    task.compliance_result = values.get("compliance_result")
                    task.status = 4
                    task.updated_at = now
                hitl_payload = {
                    "review_task_id": None, "task_type": _REVIEW_TYPE_SELFCHECK, "source_type": 0,
                    "source_id": task_id, "thread_id": thread_id,
                    "review_data": _selfcheck_review_data(
                        values.get("bidding_sections"), values.get("compliance_result"),
                    ),
                }
            else:
                # 驳回后生成失败或已达最大重试次数：保留内容，status=4 待人工处理
                _mark_review_task(db, req.session_id, task_id, _REVIEW_TYPE_SELFCHECK, 1)
                if task is not None:
                    task.bidding_sections = values.get("bidding_sections")
                    task.compliance_result = values.get("compliance_result")
                    task.status = 4
                    task.updated_at = now
            db.commit()

            # 新一轮 HITL 中断：创建审核任务并推送 hitl 事件
            if hitl_payload is not None:
                review = ReviewTask(
                    user_id=current_user.id, session_id=req.session_id,
                    task_type=hitl_payload["task_type"], source_type=hitl_payload["source_type"],
                    source_id=hitl_payload["source_id"],
                    review_data=hitl_payload["review_data"], status=0, created_at=_now(),
                )
                db.add(review)
                db.commit()
                db.refresh(review)
                hitl_payload["review_task_id"] = review.id
                yield _sse({"type": "hitl", "payload": hitl_payload})

            # 保存 AI 消息（正文 + 工具调用记录）
            if ai_content or tool_calls:
                db.add(ChatMessage(
                    user_id=current_user.id, session_id=req.session_id, role=1,
                    request_id=f"a{_now()}", content=ai_content,
                    tool_calls=tool_calls or None, created_at=_now(),
                ))
                db.commit()
            yield _sse({"type": "done", "payload": {"session_id": req.session_id}})
        except Exception as exc:
            logger.exception("resume 流式生成失败")
            yield _sse({"type": "error", "payload": {"message": f"恢复失败：{exc}"}})

    return StreamingResponse(
        _with_heartbeat(generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
