"""Agent 图层（LangGraph）：状态机定义，执行招投标"搜索→下载→解析→生成→自检→人工审核"全流程。

- AgentState：状态结构（messages 使用 add_messages reducer；tender_parsed/human_confirmed/rag_* 为
  流程标志与 RAG 召回结果；bidding_sections/compliance_result 为生成内容与自检结果；
  selfcheck_done/selfcheck_approved/generate_retries 驱动第二个 HITL 与重试上限）；
- agent_node：LLM 决策节点，绑定 search/download/parse 三件套，流式调用模型
  （保证 astream_events 能产出 on_chat_model_stream token 事件）；当 rag_context 非空时
  视为"RAG 召回后的最终回复轮"，注入参考片段且不再绑定工具，避免再次触发工具调用；
- tool_node：工具执行节点（LangGraph 内置 ToolNode，自动处理工具调用与异常）；
- review_parsed_node：解析结果人工确认节点（第一个 HITL，interrupt() 暂停等待用户确认）；
- rag_recall_node：用户确认后从 Qdrant 历史标书库（kb_type=2）检索相似段落，写入 rag_context；
- generate_node：标书生成节点（固定节点，非 LLM 自主调用），参考历史标书生成投标文件各部分；
- selfcheck_node：废标自检节点（固定节点），对生成的标书做废标项/格式/错别字三维度检查；
- review_selfcheck_node：自检结果人工审核节点（第二个 HITL，interrupt() 暂停等待审核）；
- should_generate / should_continue / should_continue_after_review / should_after_generate /
  should_continue_after_selfcheck：条件路由；
- build_bidding_graph()：组装编译图（模块级 MemorySaver 单例 checkpointer —— 同一进程内
  /chat/stream 与 /chat/{thread_id}/resume 必须共享检查点才能恢复中断）。

本轮实现标书生成 + 废标自检 + 第二个 HITL（自检审核）；两个中断点均采用 interrupt() 函数方式
（langgraph 0.2.x 的 interrupt_before + Command(resume=dict) 不会更新 state 字段，实测）。
"""

import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from sqlalchemy import select

from ..config import settings
from ..db.models import AssessmentRecord
from ..db.session import SessionLocal
from ..log import get_logger
from .llm import get_deepseek
from .memory import get_bidding_context
from .prompt_layer import (
    get_assessment_agent_prompt,
    get_bidding_router_prompt,
)
from .tools import (
    confirm_assessment,
    download_tender,
    generate_bidding,
    generate_checklist,
    generate_topology,
    get_assessment_status,
    parse_tender,
    review_bidding,
    search_tender,
    self_check,
    submit_assessment_record,
)
from ..services.assessment_service import sync_assessment_session_title

logger = get_logger("graph")

# 招投标 Agent 工具集（与 build_bidding_chain 保持一致；generate_bidding/self_check 为固定节点工具，
# 不绑定到 bind_tools，由 should_generate 路由后作为图节点直接调用）
# review_bidding 按规格作为 LLM 可调用工具（用户可能随时上传投标文件，不走标准图流程）
_AGENT_TOOLS = [search_tender, download_tender, parse_tender, review_bidding]

# 模块级单例 checkpointer：/chat/stream 与 /chat/{thread_id}/resume 必须共享同一内存检查点，
# 否则 resume 请求查不到中断时的 thread_id 状态（生产环境后续换 SqliteSaver 持久化）
_CHECKPOINTER = MemorySaver()


class AgentState(TypedDict):
    """图状态：消息列表 + HITL 流程标志 + RAG 召回结果 + 标书生成/自检结果。

    messages 使用 add_messages reducer 追加新消息；tender_parsed 由工具轮次检测得到，
    human_confirmed 由第一个 HITL resume 注入；bidding_sections/compliance_result 由
    generate/selfcheck 节点写入；selfcheck_approved 由第二个 HITL resume 注入。
    tender_info 由 /chat/stream 在"开始编写"请求时注入（parse_tender 结果 JSON 字符串）。
    """

    messages: Annotated[list, add_messages]
    tender_parsed: bool        # 招标文件是否已解析完成（检测到 parse_tender 的 ToolMessage）
    human_confirmed: bool      # 用户是否已确认解析结果（resume 时注入 True）
    rag_context: str           # RAG 检索到的历史标书片段（含给 LLM 的输出指令）
    rag_reference_doc_ids: list[int]  # 检索命中的 kb_documents.doc_id（写入 bidding_tasks.reference_doc_ids）
    rag_doc_titles: list[str]  # 命中的标书标题（供最终回复引用）
    tender_info: str           # parse_tender 解析结果（JSON 字符串），"开始编写"请求时注入
    bidding_sections: dict     # 生成的投标文件各部分内容（generate 节点写入）
    compliance_result: dict    # 自检结果（selfcheck 节点写入）
    selfcheck_done: bool       # 自检是否完成
    selfcheck_approved: bool   # 自检是否通过人工审核（第二个 HITL resume 注入）
    generate_retries: int      # 标书生成重试次数（驳回重新生成时递增，超过上限提示人工处理）
    generate_exhausted: bool   # 重试是否已达上限（强制结束路由用）


def _has_parsed(state: AgentState) -> bool:
    """messages 中是否存在 parse_tender 的成功 ToolMessage（招标文件已解析完成）。"""
    return any(
        isinstance(m, ToolMessage) and getattr(m, "name", None) == "parse_tender" and m.content
        for m in state["messages"]
    )


def _extract_project_name(state: AgentState) -> str | None:
    """从 messages 中解析 parse_tender 的 ToolMessage，提取 project_name 用于 RAG 检索。"""
    for m in state["messages"]:
        if not (isinstance(m, ToolMessage) and getattr(m, "name", None) == "parse_tender"):
            continue
        try:
            parsed = json.loads(m.content)
        except (TypeError, json.JSONDecodeError):
            continue
        name = parsed.get("project_name") if isinstance(parsed, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()[:50]
    return None


def _extract_tender_info(state: AgentState) -> str:
    """从 messages 中提取最后一次 parse_tender 的 ToolMessage 内容（JSON 字符串）。

    供 generate/selfcheck 节点与 /chat/stream 的"开始编写"初始化使用；
    无解析结果时返回 "{}"，保证工具入参为合法 JSON。
    """
    for m in reversed(state["messages"]):
        if not (isinstance(m, ToolMessage) and getattr(m, "name", None) == "parse_tender"):
            continue
        if not m.content:
            continue
        try:
            parsed = json.loads(m.content)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and not parsed.get("error"):
            return m.content
    return "{}"


def prepare_generate_state(tender_info: str) -> dict:
    """为"开始编写"请求构造初始 state 字段（/chat/stream 调用）。

    参数为 parse_tender 解析结果（JSON 字符串，由路由层从会话历史 tool_calls 中提取——
    数据库消息只有 Human/AI 两类，parse_tender 的 ToolMessage 不在其中，需从 tool_calls 恢复）。
    据此重新执行 RAG 召回（参考标书与解析结果在同一会话内稳定，重复检索幂等）；
    Embedding/Qdrant 不可用时降级为"未命中"提示，不阻塞生成流程。
    """
    project_name = "等保测评"
    try:
        parsed = json.loads(tender_info) if isinstance(tender_info, str) else {}
        if isinstance(parsed, dict):
            name = parsed.get("project_name")
            if isinstance(name, str) and name.strip():
                project_name = name.strip()[:50]
    except (TypeError, json.JSONDecodeError):
        pass
    try:
        result = get_bidding_context(project_name)
    except Exception as exc:
        logger.warning("prepare_generate_state RAG 检索异常（降级为空）: %s", exc)
        result = {}
    doc_ids = result.get("reference_doc_ids") or []
    doc_titles = result.get("doc_titles") or []
    if doc_ids:
        rag_context = (
            f"已从历史标书库检索到 {len(doc_ids)} 份参考标书"
            + (f"：{', '.join(doc_titles)}" if doc_titles else "")
            + "。片段如下：\n"
            + result.get("context", "")
        )
    else:
        rag_context = (
            "历史标书库检索未命中（知识库为空或 Embedding 服务不可用）。"
            "请在回复中如实告知用户未找到参考标书，建议先上传历史标书。"
        )
    return {"tender_info": tender_info, "rag_context": rag_context, "human_confirmed": True}


def agent_node(state: AgentState) -> dict:
    """LLM 决策节点：绑定工具 -> 组装 system + 历史消息 -> 流式调用模型 -> 返回新消息。

    RAG 召回完成后（rag_context 非空）进入最终回复轮：注入参考标书片段作为 system 上下文，
    且不再绑定工具（避免再次触发工具调用），只生成面向用户的总结回复。
    使用 model.stream 聚合完整回复（含 tool_calls），保证外层 astream_events
    能捕获 on_chat_model_stream 逐 token 事件；LLM 调用失败时返回兜底消息，不中断图。
    """
    try:
        model = get_deepseek()
        prompt = get_bidding_router_prompt()
        # 取路由 Prompt 的 system 文案作为 SystemMessage，历史消息紧随其后
        system_text = prompt.messages[0].prompt.template
        if state.get("rag_context"):
            # RAG 召回后的最终回复轮：注入参考标书上下文，不再绑定工具
            system_text = (
                system_text
                + "\n\n## 参考历史标书片段（RAG 召回，仅供风格与结构参考）\n"
                + state["rag_context"]
                + "\n\n本轮为最终回复：请根据参考标书上下文，告知用户已找到的参考标书情况并说明可以开始编写投标文件；不要调用任何工具。"
            )
        else:
            model = model.bind_tools(_AGENT_TOOLS)
        messages = [SystemMessage(content=system_text)] + list(state["messages"])

        chunks = list(model.stream(messages))
        if not chunks:
            logger.warning("agent_node 模型无输出")
            return {"messages": [AIMessage(content="抱歉，处理时出现错误，请重试")]}
        aggregated = chunks[0]
        for chunk in chunks[1:]:
            aggregated += chunk
        return {"messages": [aggregated]}
    except Exception as exc:
        logger.exception("agent_node LLM 调用失败")
        return {"messages": [AIMessage(content="抱歉，处理时出现错误，请重试")]}


# 工具执行节点：LangGraph 内置 ToolNode，自动处理并行工具调用与异常
tool_node = ToolNode(_AGENT_TOOLS)


def review_parsed_node(state: AgentState) -> dict:
    """解析结果人工审核节点：interrupt() 暂停等待用户确认。

    首次执行时 interrupt() 抛出 GraphInterrupt 暂停图（astream_events 正常结束，
    get_state.next 指向本节点）；用户确认后 resume 调用 Command(resume={"confirmed": True})，
    interrupt() 返回该确认值并写入 human_confirmed，由 should_continue_after_review 路由到 rag_recall。

    注：langgraph 0.2.x 的 interrupt_before + Command(resume=dict) 不会更新 state 字段（实测），
    故采用 interrupt() 函数方式传递确认值，语义明确可靠。
    """
    decision = interrupt({"prompt": "请确认解析结果是否合适，确认后继续检索历史标书"})
    confirmed = (
        decision.get("confirmed", False) if isinstance(decision, dict) else bool(decision)
    )
    logger.info("review_parsed 收到用户确认: %s", confirmed)
    return {"human_confirmed": confirmed}


def rag_recall_node(state: AgentState) -> dict:
    """RAG 召回节点：从解析结果提取项目名称，检索 Qdrant 历史标书库（kb_type=2）。

    检索结果写入 rag_context（供 agent 最终回复参考）与 rag_reference_doc_ids；
    同时返回一条 AIMessage 明确告知检索结果（命中份数 / 未命中提示），避免依赖
    模型自行发挥而输出偏离；Embedding 不可用 / Qdrant 无数据时降级为"未找到参考标书"提示，不报错。
    """
    project_name = _extract_project_name(state) or "等保测评"
    try:
        result = get_bidding_context(project_name)
    except Exception as exc:
        logger.warning("rag_recall 检索异常（降级为空）: %s", exc)
        result = {}
    doc_ids = result.get("reference_doc_ids") or []
    doc_titles = result.get("doc_titles") or []
    if doc_ids:
        rag_context = (
            f"已从历史标书库检索到 {len(doc_ids)} 份参考标书"
            + (f"：{', '.join(doc_titles)}" if doc_titles else "")
            + "。片段如下：\n"
            + result.get("context", "")
        )
        prompt_msg = (
            f"已找到 {len(doc_ids)} 份参考标书"
            + (f"：{', '.join(doc_titles)}。" if doc_titles else "。")
            + "可以开始编写投标文件了，请说「开始编写」。"
        )
    else:
        rag_context = (
            "历史标书库检索未命中（知识库为空或 Embedding 服务不可用）。"
            "请在回复中如实告知用户未找到参考标书，建议先上传历史标书，再继续编写。"
        )
        prompt_msg = (
            "未找到参考标书（历史标书库为空或检索服务不可用）。"
            "建议先上传历史标书，再继续编写投标文件。"
        )
    logger.info("rag_recall 完成 project=%s hits=%d", project_name, len(doc_ids))
    return {
        "rag_context": rag_context,
        "rag_reference_doc_ids": doc_ids,
        "rag_doc_titles": doc_titles,
        "messages": [AIMessage(content=prompt_msg)],
    }


def generate_node(state: AgentState) -> dict:
    """标书生成节点：固定调用 generate_bidding 工具，参考历史标书生成投标文件各部分。

    tender_info 优先取注入的 state 字段，缺失时从消息中提取 parse_tender 结果；
    重试次数（驳回后重新生成）超过 bidding_max_retries 时停止并提示人工处理。
    生成结果写入 bidding_sections，并返回提示消息驱动后续自检流程。
    """
    retries = int(state.get("generate_retries") or 0) + 1
    if retries > settings.bidding_max_retries:
        logger.warning("标书生成已达最大重试次数 %d 次，建议人工处理", settings.bidding_max_retries)
        return {
            "messages": [AIMessage(content="多次重新生成仍未通过自检，已达最大重试次数，建议人工处理投标文件。")],
            "generate_retries": retries,
            "generate_exhausted": True,
        }

    tender_info = state.get("tender_info") or _extract_tender_info(state)
    rag_context = state.get("rag_context") or ""
    result = generate_bidding(tender_info, rag_context)
    try:
        sections = json.loads(result) if isinstance(result, str) else {}
    except (TypeError, json.JSONDecodeError):
        sections = {"error": "标书生成返回非法 JSON", "detail": str(result)[:200]}
    if "error" in sections:
        logger.warning("generate_bidding 返回错误: %s", sections.get("detail"))
        return {
            "messages": [AIMessage(content=f"标书生成失败：{sections.get('detail')}")],
            "generate_retries": retries,
        }
    logger.info("generate_node 完成 project=%s 各部分=%s", _extract_project_name(state) or "未知", list(sections.keys()))
    return {
        "messages": [AIMessage(content="投标文件已生成，正在进行废标自检…")],
        "bidding_sections": sections,
        "generate_retries": retries,
        "generate_exhausted": False,
    }


def selfcheck_node(state: AgentState) -> dict:
    """废标自检节点：固定调用 self_check 工具，对生成的标书做三维度检查。

    自检结果写入 compliance_result 并标记 selfcheck_done，随后进入第二个 HITL 等待人工审核。
    """
    sections = state.get("bidding_sections") or {}
    tender_info = state.get("tender_info") or _extract_tender_info(state)
    result = self_check(json.dumps(sections, ensure_ascii=False), tender_info)
    try:
        compliance = json.loads(result) if isinstance(result, str) else {}
    except (TypeError, json.JSONDecodeError):
        compliance = {"error": "自检返回非法 JSON", "detail": str(result)[:200]}
    if "error" in compliance:
        logger.warning("self_check 返回错误: %s", compliance.get("detail"))
        return {
            "messages": [AIMessage(content=f"废标自检失败：{compliance.get('detail')}")],
            "compliance_result": compliance,
            "selfcheck_done": True,
        }
    logger.info(
        "selfcheck_node 完成 overall=%s %s",
        compliance.get("overall_status"), compliance.get("summary", ""),
    )
    return {
        "messages": [AIMessage(content="废标自检完成，等待人工审核。")],
        "compliance_result": compliance,
        "selfcheck_done": True,
    }


def review_selfcheck_node(state: AgentState) -> dict:
    """自检结果人工审核节点（第二个 HITL 中断点）。

    interrupt() 暂停图等待用户审核；resume 时 Command(resume={"approved": bool,
    "modified_sections": {...}}) 的审核值经 interrupt() 返回：approved=True 表示通过
    （可携带 modified_sections 更新投标内容），False 表示驳回重新生成。
    与 review_parsed 一致，采用 interrupt() 函数方式而非 interrupt_before（实测可靠）。
    """
    decision = interrupt({"prompt": "请审核投标文件自检结果：通过 / 驳回重新生成 / 修改后通过"})
    approved = False
    modified_sections = None
    if isinstance(decision, dict):
        approved = bool(decision.get("approved", False))
        modified_sections = decision.get("modified_sections")
    logger.info("review_selfcheck 收到审核: approved=%s modified=%s", approved, modified_sections is not None)
    update: dict = {"selfcheck_approved": approved}
    if isinstance(modified_sections, dict) and modified_sections:
        update["bidding_sections"] = modified_sections
    return update


def should_generate(state: AgentState) -> str:
    """agent 之后的条件路由：用户说"开始编写"且满足前置条件时进入标书生成，否则回退正常路由。

    触发条件：解析结果已确认（human_confirmed）、RAG 已召回（rag_context）、尚未生成过
    （bidding_sections 为空）、最后一条消息为用户消息且含"开始编写"。
    last_message 必须是 HumanMessage，避免 rag_recall 后 agent 的最终回复中含"开始编写"
    字样时误触发生成（该轮应正常结束）。
    """
    last_message = state["messages"][-1]
    content = getattr(last_message, "content", None)
    if (
        state.get("human_confirmed")
        and state.get("rag_context")
        and not state.get("bidding_sections")
        and isinstance(last_message, HumanMessage)
        and isinstance(content, str)
        and "开始编写" in content
    ):
        logger.info("用户要求开始编写，进入 generate 节点")
        return "generate"
    return should_continue(state)


def should_after_generate(state: AgentState) -> str:
    """generate 之后的路由：生成成功且未达重试上限 -> selfcheck；失败/超限 -> 结束。"""
    if state.get("generate_exhausted") or not state.get("bidding_sections"):
        logger.info("generate 未产出有效标书（失败或已达重试上限），结束")
        return END
    return "selfcheck"


def should_continue_after_selfcheck(state: AgentState) -> str:
    """自检审核后的路由：审核通过 -> 结束；驳回 -> 回到 generate 重新生成。"""
    if state.get("selfcheck_approved"):
        logger.info("自检审核通过，结束图流程")
        return END
    logger.info("自检审核驳回，回到 generate 重新生成")
    return "generate"


def should_continue(state: AgentState) -> str:
    """条件路由（agent 之后）：有 tool_calls 进 tools；解析完成且用户未确认进 review_parsed 中断；否则结束。

    附带保险：工具调用轮次达到 GRAPH_MAX_ITERATIONS 时强制结束，防止图死循环。
    """
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_rounds = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
        if tool_rounds >= settings.graph_max_iterations:
            logger.warning("图达到最大工具轮次 %d，强制结束", settings.graph_max_iterations)
            return END
        return "tools"
    if _has_parsed(state) and not state.get("human_confirmed"):
        logger.info("解析完成且用户未确认，进入 review_parsed HITL 中断")
        return "review_parsed"
    return END


def should_continue_after_review(state: AgentState) -> str:
    """审核节点后的路由：用户确认 -> RAG 召回；未确认（非正常路径）-> 结束。"""
    if state.get("human_confirmed"):
        logger.info("用户已确认解析结果，进入 rag_recall")
        return "rag_recall"
    return END


def build_bidding_graph():
    """组装并编译招投标 Agent 图。

    流程：agent <-> tools 循环执行工具链；解析完成后经 review_parsed（第一个 HITL）中断等待确认，
    确认后经 rag_recall 召回历史标书再回 agent；用户说"开始编写"时经 generate -> selfcheck ->
    review_selfcheck（第二个 HITL）中断等待自检审核；审核通过结束，驳回回 generate 重新生成
    （超过 bidding_max_retries 停止并提示人工处理）。
    checkpointer 使用模块级单例（同一进程内 stream/resume 共享）。
    """
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("review_parsed", review_parsed_node)
    graph.add_node("rag_recall", rag_recall_node)
    graph.add_node("generate", generate_node)
    graph.add_node("selfcheck", selfcheck_node)
    graph.add_node("review_selfcheck", review_selfcheck_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent", should_generate,
        {"tools": "tools", "review_parsed": "review_parsed", "generate": "generate", END: END},
    )
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges(
        "review_parsed", should_continue_after_review,
        {"rag_recall": "rag_recall", END: END},
    )
    graph.add_edge("rag_recall", "agent")
    # 标书生成 -> 自检 -> 第二个 HITL（生成失败/重试超限直接结束）
    graph.add_conditional_edges(
        "generate", should_after_generate,
        {"selfcheck": "selfcheck", END: END},
    )
    graph.add_edge("selfcheck", "review_selfcheck")
    graph.add_conditional_edges(
        "review_selfcheck", should_continue_after_selfcheck,
        {"generate": "generate", END: END},
    )
    # recursion_limit 由调用方通过 config 传入（langgraph 0.2.x 不支持 compile 参数）
    return graph.compile(checkpointer=_CHECKPOINTER)


# ---------------------------------------------------------------------------
# 技术线（测评核查）：清单生成状态机
# - agent_node：绑定 generate_checklist，由 LLM 自主决定何时生成清单
# - tools：ToolNode 执行 generate_checklist
# - checklist_node：解析工具结果写入 assessment_records（每个控制点一条 status=0）
# - analyze_screenshot / compare_records 不绑定（由截图上传 / 人工记录提交触发，见 routers/assessment.py）
# ---------------------------------------------------------------------------


class TechnicalAgentState(TypedDict):
    """技术线图状态：消息列表 + 清单生成标志。

    messages 使用 add_messages reducer 追加新消息；checklist_generated 由 checklist 节点写入；
    session_id/user_id 为写库必需（由路由层注入 initial_state）。
    """

    messages: Annotated[list, add_messages]
    system_level: int          # 0=二级, 1=三级, 2=四级
    system_name: str           # 被测系统名称
    checklist_generated: bool  # 清单是否已写入 assessment_records
    session_id: int            # 目标会话（写库用，路由层注入）
    user_id: int               # 目标用户（写库用，路由层注入）


# 技术线 Agent 工具集：generate_checklist（生成清单）+ 对话驱动测评操作工具（状态查询/人工记录提交/确认驳回）+ 拓扑生成。
# analyze_screenshot / compare_records 作为固定节点由 REST 接口触发（不绑定）
_ASSESSMENT_AGENT_TOOLS = [
    generate_checklist,
    get_assessment_status,
    submit_assessment_record,
    confirm_assessment,
    generate_topology,
]


def _extract_checklist_result(state: TechnicalAgentState) -> str | None:
    """从 messages 中提取最后一次 generate_checklist 的成功 ToolMessage 内容（JSON 字符串）。"""
    for m in reversed(state["messages"]):
        if not (isinstance(m, ToolMessage) and getattr(m, "name", None) == "generate_checklist"):
            continue
        if not m.content:
            continue
        try:
            parsed = json.loads(m.content)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and not parsed.get("error"):
            return m.content
    return None


def assessment_agent_node(state: TechnicalAgentState) -> dict:
    """技术线 LLM 节点：绑定测评工具集，注入当前会话/用户上下文，流式调用模型。

    会话上下文注入 system prompt：测评操作工具（get_assessment_status/submit_assessment_record/
    confirm_assessment）的 session_id 参数必须使用当前会话 ID。
    """
    try:
        model = get_deepseek().bind_tools(_ASSESSMENT_AGENT_TOOLS)
        prompt = get_assessment_agent_prompt()
        system_text = prompt.messages[0].prompt.template
        session_id = int(state.get("session_id") or 0)
        user_id = int(state.get("user_id") or 0)
        system_text = (
            f"{system_text}\n\n当前会话 ID：{session_id}；当前用户 ID：{user_id}。"
            "get_assessment_status / submit_assessment_record / confirm_assessment 的 session_id 参数必须填当前会话 ID。"
        )
        messages = [SystemMessage(content=system_text)] + list(state["messages"])
        chunks = list(model.stream(messages))
        if not chunks:
            logger.warning("assessment_agent_node 模型无输出")
            return {"messages": [AIMessage(content="抱歉，处理时出现错误，请重试")]}
        aggregated = chunks[0]
        for chunk in chunks[1:]:
            aggregated += chunk
        return {"messages": [aggregated]}
    except Exception as exc:
        logger.exception("assessment_agent_node LLM 调用失败")
        return {"messages": [AIMessage(content="抱歉，处理时出现错误，请重试")]}


def assessment_checklist_node(state: TechnicalAgentState) -> dict:
    """清单生成后处理：提取 generate_checklist 结果，写入 assessment_records（status=0 待测评）。"""
    result_text = _extract_checklist_result(state)
    if result_text is None:
        return {
            "messages": [AIMessage(content="未获取到测评清单生成结果，请重试。")],
            "checklist_generated": False,
        }
    try:
        parsed = json.loads(result_text)
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    checklist = parsed.get("checklist") if isinstance(parsed, dict) else None
    if not isinstance(checklist, list) or not checklist:
        return {
            "messages": [AIMessage(content="测评清单生成失败，模型未返回有效控制点列表。")],
            "checklist_generated": False,
        }

    now = int(__import__("time").time())
    level = int(state.get("system_level") or 1)
    session_id = int(state.get("session_id") or 0)
    user_id = int(state.get("user_id") or 0)
    records: list[AssessmentRecord] = []
    # 重新生成场景：先清空该会话旧清单，再写入新控制点（避免重复堆积）
    with SessionLocal() as db:
        for old in db.scalars(
            select(AssessmentRecord).where(AssessmentRecord.session_id == session_id)
        ).all():
            db.delete(old)
        for item in checklist[: settings.assessment_max_checklist]:
            if not isinstance(item, dict):
                continue
            records.append(AssessmentRecord(
                user_id=user_id,
                session_id=session_id,
                system_level=level,
                checklist_code=str(item.get("checklist_code") or "")[:32],
                checklist_name=str(item.get("checklist_name") or "")[:128],
                assessment_command=(str(item.get("assessment_command") or "") or None)[:512],
                status=0,
                confidence=0.0,
                created_at=now,
                updated_at=now,
            ))
        db.add_all(records)
        # 会话标题同步为"被测系统名 等保X级测评"（工作台清单标题与会话同名）
        sync_assessment_session_title(db, session_id, parsed.get("system_name") or "", level)
        db.commit()
    logger.info("assessment_checklist_node 写入 %d 个控制点 session=%s", len(records), session_id)
    return {
        "checklist_generated": True,
        "messages": [AIMessage(content=f"测评清单已生成，共 {len(records)} 个控制点，请组员按命令执行测评并上传截图。")],
    }


def assessment_should_continue(state: TechnicalAgentState) -> str:
    """技术线条件路由：有 tool_calls 进 tools；清单已生成且未写库进 checklist；否则结束。"""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_rounds = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
        if tool_rounds >= settings.graph_max_iterations:
            logger.warning("技术线图达到最大工具轮次 %d，强制结束", settings.graph_max_iterations)
            return END
        return "tools"
    if _extract_checklist_result(state) is not None and not state.get("checklist_generated"):
        return "checklist"
    return END


def build_assessment_graph():
    """组装并编译技术线 Agent 图（测评清单生成链路）。

    流程：agent <-> tools 循环执行工具链；generate_checklist 结果出现后进入 checklist 节点
    写入 assessment_records（status=0 待测评），随后结束。
    截图分析（analyze_screenshot）与比对（compare_records）由 REST 接口触发，不在本图内。
    """
    graph = StateGraph(TechnicalAgentState)
    graph.add_node("agent", assessment_agent_node)
    graph.add_node("tools", ToolNode(_ASSESSMENT_AGENT_TOOLS))
    graph.add_node("checklist", assessment_checklist_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        assessment_should_continue,
        {"tools": "tools", "checklist": "checklist", END: END},
    )
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=_CHECKPOINTER)
