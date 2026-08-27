# 请在现有项目结构中实现"给 LLM 挂载第一个工具（联网搜索招标）"，严格遵循已有四层架构（llm.py / prompt_layer.py / memory.py / tools.py），不破坏现有代码。

## 目标

用户说"帮我搜索等保招标"时，Agent 自主调用 `search_tender` 工具进行联网搜索，返回真实搜索结果，并对结果做初步筛选和推荐说明，而非原样转发。

## tools.py — 新增 search_tender 工具

1. 使用 `@tool` 装饰器定义 `search_tender(keyword: str, max_results: int = 10) -> str`；
2. 工具描述（docstring）要清晰，让 LLM 知道何时调用：`搜索招标公告网站，根据关键词查找招标信息。返回标题、URL、发布日期、截止日期、摘要。keyword: 搜索关键词（如"等保三级 招标"）`；
3. 内部调用 Tavily API（`tavily.TavilyClient`，API Key 从环境变量 `TAVILY_API_KEY` 读取）；
4. 通过 `include_domains` 参数限定招标网站域名，域名列表从 `settings` 读取（如 `settings.TENDER_SITES`，默认值 `["cebpub.com", "ccgp.gov.cn", "bidcenter.com.cn"]`）；
5. 对 Tavily 返回结果做结构化提取，每条结果包含：`title`（标题）、`url`（链接）、`published_date`（发布日期）、`score`（Tavily 相关度评分）、`content`（摘要前 200 字）；
6. 返回 JSON 字符串，格式见下方示例；
7. 异常处理：Tavily 调用失败时返回 `{"error": "搜索服务暂时不可用", "detail": "..."}`，不抛异常中断流程；
8. 加日志：记录搜索关键词、返回结果数量、耗时。

`search_tender` 返回示例：

```json
[
    {
        "title": "XX市公安局网络安全等级保护测评服务采购公告",
        "url": "https://www.cebpub.com/xxx",
        "published_date": "2026-08-05",
        "score": 0.95,
        "content": "项目预算80万元，需具备等保三级测评资质..."
    }
]
```

## prompt_layer.py — 组装带工具的链路

1. 新增 `get_bidding_router_prompt()`：路由 Prompt，system 部分定义角色为"等保测评商务助手"，约束：收到招标搜索请求时调用 `search_tender` 工具，拿到结果后对每条结果分析与用户需求的匹配度，输出推荐（哪几条值得重点关注及原因），不要原样转发原始搜索结果；
2. 新增 `build_bidding_chain(memory)`：组装函数，内部调用 `get_deepseek()` 获取模型实例，调用 `model.bind_tools([search_tender])` 绑定工具，组装为可执行链路；memory 由调用方传入，不在本层创建；
3. 提示词层不做工具实例化（工具从 tools.py 导入），不碰数据库，不直接调 Tavily。

## llm.py — 无改动

模型层已有 `get_deepseek()`，无需修改。只确认 DeepSeek 实例的 `model` 参数支持 function calling（deepseek-chat 模型支持）。

## memory.py — 无改动

记忆层暂不改动。本轮只验证工具调用，历史记忆保持现有逻辑。

## routers — 调用入口

1. 对话路由中，当 `intent_type=1`（招投标）时，调用 `build_bidding_chain(memory)` 而非裸 LLM；
2. 使用 LangChain `AgentExecutor` 执行链路，`max_iterations=5`，`handle_parsing_errors=True`；
3. 流式返回时，工具调用过程通过 SSE 事件 `type=tool_call` 推送给前端（含 `tool_name`、`arguments`、`result` 摘要、`duration_ms`），工具调用完成后的最终文本通过 `type=token` 推送；
4. 工具调用记录写入 `chat_messages.tool_calls` JSON 字段。

## config.py — 新增配置项

1. `TAVILY_API_KEY`：Tavily API 密钥，从环境变量读取；
2. `TENDER_SITES`：招标网站域名列表，默认 `["cebpub.com", "ccgp.gov.cn", "bidcenter.com.cn"]`；
3. `TAVILY_MAX_RESULTS`：单次搜索最大结果数，默认 10。

## requirements.txt — 新增依赖

```
tavily-python==0.5.*
```

## 验证标准

1. `curl POST /chat` 发送 `{"content": "帮我搜索等保招标", "intent_type": 1}`，返回中包含真实招标搜索结果（非 LLM 编造）；
2. 前端 SSE 收到 `type=tool_call` 事件，`tool_name=search_tender`；
3. Agent 返回的不是原始 JSON，而是经过 LLM 筛选后的推荐说明（如"找到 5 条结果，其中第 2 条和第 4 条与等保三级相关，建议重点关注"）；
4. `chat_messages.tool_calls` 写入了工具调用记录；
5. Tavily API 失败时，Agent 返回友好提示而非 500 报错。

## 约束

- 不引入 LangGraph，本轮仍用 LangChain `AgentExecutor`；
- 不做 HITL 中断，本轮是全自动工具调用；
- 不做文档解析（parse_tender / download_tender），下一轮再加；
- 不做 RAG 召回，本轮工具只有 `search_tender` 一个；
- `tools.py` 中预留 `download_tender` 和 `parse_tender` 的函数签名和 docstring，函数体用 `raise NotImplementedError`，让 LLM 知道有这些工具但本轮不可调用（不绑定到 bind_tools）。


# 请在现有项目结构中实现"串联文档下载与解析工具链"，在上一轮 search_tender 基础上新增 download_tender 和 parse_tender 两个工具，让 Agent 能自主完成"搜索→下载→解析"三步链式调用。

## 目标

用户说"帮我搜索等保招标，找到合适的解析一下"时，Agent 自主执行：
1. 调用 `search_tender` 搜索招标公告
2. 从结果中选择一条，调用 `download_tender` 下载招标文件
3. 调用 `parse_tender` 解析文件，提取预算、评分表、资格要求、废标项
4. 把解析结果整理后返回给用户

## tools.py — 实现 download_tender 和 parse_tender

### download_tender(url: str) -> str

1. 使用 `@tool` 装饰器，docstring：`下载招标文件。从招标公告页面提取附件下载链接并下载。url: 招标公告页面 URL。返回本地文件路径`；
2. 使用 `httpx` 请求公告页面，设置超时 30 秒，User-Agent 伪装浏览器；
3. 用正则或 BeautifulSoup 解析 HTML，提取附件下载链接（.pdf / .doc / .docx / .zip）；
4. 下载附件到 `settings.UPLOAD_DIR/tenders/` 目录，文件名用 `{timestamp}_{原文件名}` 防冲突；
5. 返回 JSON 字符串：`{"file_path": "/data/uploads/tenders/xxx.pdf", "file_name": "招标文件.pdf", "file_size": 1234567}`；
6. 异常处理：页面无法访问 / 找不到附件 / 下载失败，返回 `{"error": "...", "detail": "..."}`，不抛异常；
7. 加日志：记录 URL、提取到的附件数、下载耗时、文件大小。

### parse_tender(file_path: str) -> str

1. 使用 `@tool` 装饰器，docstring：`解析招标文件，提取关键信息。file_path: 招标文件本地路径。返回结构化 JSON，包含预算金额、评分标准、资格要求、废标项`；
2. 根据 `file_path` 后缀分流：
   - `.pdf`：用 `PyMuPDF（fitz）` 提取全文文本
   - `.docx`：用 `python-docx` 提取全文文本
   - `.doc`：用 `python-docx` 尝试，失败则返回错误提示建议转 PDF
   - 其他后缀：返回 `{"error": "不支持的文件格式"}`
3. 将提取的全文交给 DeepSeek（调用 `get_deepseek()`）做结构化提取，Prompt 要求提取以下字段：
   - `budget`：预算金额（字符串，如"80万元"）
   - `scoring_items`：评分表项列表，每项含 `item`（评分项名称）、`max_score`（满分）、`description`（评分说明）
   - `qualification_requirements`：资格要求列表（字符串数组）
   - `disqualification_items`：废标项列表（字符串数组）
   - `deadline`：投标截止日期（字符串）
   - `project_name`：项目名称
4. 返回 JSON 字符串，格式见下方示例；
5. 异常处理：文件不存在 / 解析失败 / LLM 提取超时，返回 `{"error": "...", "detail": "..."}`；
6. 加日志：记录文件路径、文本长度、各字段提取耗时。

`parse_tender` 返回示例：

```json
{
    "project_name": "XX市公安局网络安全等级保护测评服务采购",
    "budget": "80万元",
    "deadline": "2026-08-20",
    "qualification_requirements": [
        "具备网络安全等级保护测评机构推荐证书",
        "近三年内承担过等保三级测评项目不少于3个"
    ],
    "scoring_items": [
        {"item": "技术方案", "max_score": 40, "description": "测评方案完整性、技术路线合理性"},
        {"item": "商务报价", "max_score": 30, "description": "最低有效报价得满分，按比例计算"},
        {"item": "企业资质", "max_score": 15, "description": "相关资质证书数量和质量"},
        {"item": "项目团队", "max_score": 15, "description": "团队人员资质和经验"}
    ],
    "disqualification_items": [
        "未按要求缴纳投标保证金",
        "投标文件未按规定格式签署盖章",
        "报价超过项目预算金额",
        "资格证明文件不全"
    ]
}
```

## prompt_layer.py — 更新路由 Prompt

1. 更新 `get_bidding_router_prompt()`：system 部分新增指引——当用户要求"解析"或"看看详情"时，从搜索结果中选择最相关的一条，调用 `download_tender` 下载，再调用 `parse_tender` 解析，最后把解析结果整理为用户可读的摘要返回；
2. 更新 `build_bidding_chain(memory)`：`bind_tools` 从 `[search_tender]` 改为 `[search_tender, download_tender, parse_tender]`；
3. AgentExecutor 的 `max_iterations` 从 5 调到 8（三步链式调用需要更多迭代空间）。

## config.py — 新增配置项

1. `UPLOAD_DIR`：文件上传根目录，默认 `"./data/uploads"`；
2. `TENDER_DIR`：招标文件存储子目录，默认 `"{UPLOAD_DIR}/tenders"`，启动时自动创建；
3. `PARSE_MAX_TEXT_LENGTH`：传给 LLM 解析的最大文本长度，默认 50000 字符，超出截断。

## requirements.txt — 新增依赖

```
beautifulsoup4==4.12.*
lxml==5.*
pymupdf==1.24.*
python-docx==1.1.*
httpx==0.27.*
```

## routers — 无改动

对话路由逻辑不变，`intent_type=1` 仍调 `build_bidding_chain`，SSE 推送逻辑不变。新增的 `tool_call` 事件会自动覆盖三个工具。

## 验证标准

1. 用户说"帮我搜索等保招标，找到合适的解析一下"，Agent 自主完成搜索→下载→解析三步，不需要用户逐步指令；
2. SSE 流中出现两次 `tool_call` 事件：先 `download_tender`，后 `parse_tender`；
3. 返回给用户的是结构化摘要（项目名称、预算、截止日期、资格要求、废标项），而非原始文件全文；
4. `chat_messages.tool_calls` 写入了两个工具的调用记录；
5. `download_tender` 失败时（如附件链接无法访问），Agent 返回友好提示并建议用户手动上传文件，不直接 500；
6. `parse_tender` 对不支持的文件格式返回明确错误，不崩溃。

## 约束

- 仍不引入 LangGraph，本轮继续用 `AgentExecutor`；
- 仍不做 HITL 中断，本轮是全自动三步链式调用；
- 不做 RAG 召回，本轮工具只有 `search_tender` + `download_tender` + `parse_tender` 三个；
- 不做自检（self_check），下一轮再加；
- 下载的文件暂存本地目录，不接 MinIO（MinIO 改造在后续步骤）；
- `parse_tender` 内部调 LLM 做结构化提取，用已有的 `get_deepseek()`，不新建模型实例。



# 请在现有项目结构中将 AgentExecutor 迁移为 LangGraph StateGraph 状态机架构，功能保持不变（搜索→下载→解析三步链式调用），为后续 HITL 中断做准备。

## 目标

用户说"帮我搜索等保招标，找到合适的解析一下"时，Agent 的行为与上一轮完全一致（自主完成搜索→下载→解析三步），但底层执行引擎从 LangChain `AgentExecutor` 替换为 LangGraph `StateGraph`。本轮不新增任何功能，只做架构迁移。

## 新建 graph.py — 状态机定义

### 1. AgentState 状态定义

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
```

- `messages`：消息列表，使用 `add_messages` reducer，新消息追加到列表末尾而非覆盖；
- 不额外存 `tool_calls`，工具调用信息已在 AIMessage 的 `tool_calls` 属性中。

### 2. agent_node(state) — LLM 节点

1. 从 `state["messages"]` 取出消息列表；
2. 调用 `get_deepseek()` 获取模型实例，`bind_tools([search_tender, download_tender, parse_tender])` 绑定工具；
3. 使用 `get_bidding_router_prompt()` 获取 system prompt，组装为 `[SystemMessage(...)] + state["messages"]`；
4. 调用 `model.invoke(messages)`，返回 `{"messages": [response]}`；
5. 异常处理：LLM 调用失败时返回 `{"messages": [AIMessage(content="抱歉，处理时出现错误，请重试")]}`，不抛异常中断图。

### 3. tool_node — 工具执行节点

1. 使用 LangGraph 内置 `ToolNode`：`ToolNode([search_tender, download_tender, parse_tender])`；
2. 或自定义函数：从最后一条 AIMessage 的 `tool_calls` 中提取工具调用，执行对应工具，返回 `{"messages": [ToolMessage(...), ...]}`；
3. 推荐使用内置 `ToolNode`，自动处理并行工具调用和异常。

### 4. should_continue(state) — 条件路由函数

```python
def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "__end__"
```

- 检查最后一条消息是否有 `tool_calls`；
- 有则路由到 `"tools"` 节点，无则路由到 `END`。

### 5. build_bidding_graph() — 组装并编译

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

def build_bidding_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=MemorySaver())
```

- 两个节点：`agent`（LLM 决策）+ `tools`（工具执行）；
- 入口为 `agent`，条件边路由到 `tools` 或 `END`，`tools` 执行后回到 `agent`；
- 使用 `MemorySaver` 作为 checkpointer（内存级别），为后续 HITL 中断预留持久化能力（HITL 步骤再换 `SqliteSaver`）；
- 返回 `CompiledGraph`，支持 `.invoke()` / `.stream()` / `.astream()` / `.astream_events()`。

## prompt_layer.py — 更新

1. 保留 `get_bidding_router_prompt()` 不变；
2. `build_bidding_chain(memory)` 标记为 `@deprecated`，函数体保留但不再被调用；
3. 新增 `build_bidding_graph()`：内部调用 `graph.py` 的 `build_bidding_graph()`，返回编译后的图实例；
4. 提示词层不再组装 Chain，只提供 Prompt 和图构建入口。

## tools.py — 无改动

三个工具 `search_tender`、`download_tender`、`parse_tender` 的定义完全不变，`graph.py` 直接导入使用。

## llm.py — 无改动

`get_deepseek()` 不变，`agent_node` 内部调用。

## memory.py — 无改动

`get_session_memory(session_id)` 不变，由 routers 在构建初始 state 时调用。

## routers — 更新调用入口

### 1. 替换链路调用

```python
# 旧
chain = build_bidding_chain(memory)
result = await chain.ainvoke({"input": user_input})

# 新
graph = build_bidding_graph()
messages = memory.buffer_as_messages + [HumanMessage(content=user_input)]
result = await graph.ainvoke(
    {"messages": messages},
    config={"configurable": {"thread_id": request_id}}
)
```

### 2. 流式推送改用 astream_events

```python
async for event in graph.astream_events(
    {"messages": messages},
    config={"configurable": {"thread_id": request_id}},
    version="v2"
):
    kind = event["event"]
    if kind == "on_chat_model_stream":
        chunk = event["data"]["chunk"]
        if chunk.content:
            yield sse_event("token", {"content": chunk.content})
    elif kind == "on_tool_start":
        yield sse_event("tool_call", {
            "tool_name": event["name"],
            "arguments": event["data"].get("input", ""),
            "status": "start"
        })
    elif kind == "on_tool_end":
        output = event["data"].get("output", "")
        yield sse_event("tool_call", {
            "tool_name": event["name"],
            "result": str(output)[:500],
            "status": "end"
        })
```

- `on_chat_model_stream`：逐 token 推送，对应前端 `type=token` 事件；
- `on_tool_start` / `on_tool_end`：工具调用生命周期，对应前端 `type=tool_call` 事件；
- `version="v2"` 固定，v1 已弃用。

### 3. 消息持久化

1. 图执行完成后，从 `result["messages"]` 取出最后的 AIMessage 作为助手回复；
2. 将用户消息和助手回复写入 `chat_messages` 表（逻辑与之前一致）；
3. 工具调用记录从 AIMessage 的 `tool_calls` 和 ToolMessage 中提取，写入 `chat_messages.tool_calls` JSON 字段。

### 4. thread_id 与 checkpointer

1. 每个请求使用唯一的 `thread_id`（用 `request_id`），传入 `config={"configurable": {"thread_id": ...}}`；
2. `MemorySaver` 会按 `thread_id` 保存状态快照，同一 thread 的多次调用可恢复状态（为 HITL 做准备）；
3. 本轮不使用恢复功能，但配置好以便下一轮直接用。

## config.py — 新增配置

1. `GRAPH_MAX_ITERATIONS`：图最大循环次数，默认 10（防止死循环）；
2. `GRAPH_RECURSION_LIMIT`：LangGraph 递归限制，默认 25。

## requirements.txt — 新增依赖

```
langgraph==0.2.*
langgraph-checkpoint==0.2.*
```

## 验证标准

1. 用户说"帮我搜索等保招标，找到合适的解析一下"，Agent 行为与上一轮完全一致：自主完成搜索→下载→解析三步；
2. SSE 流中 `type=token` 和 `type=tool_call` 事件与上一轮一致，前端无感知变化；
3. `chat_messages` 表写入正常，`tool_calls` JSON 字段记录完整；
4. 服务日志中出现 `[graph]` 前缀的日志，显示节点执行顺序（agent → tools → agent → tools → agent → END）；
5. `should_continue` 正确路由：有 tool_calls 时进 tools 节点，无 tool_calls 时结束；
6. 连续多次对话（同一 session）正常工作，历史消息从 DB 加载后注入初始 state。

## 约束

- 不做 HITL 中断，本轮只迁移架构，`MemorySaver` 虽已配置但不使用 interrupt 功能；
- 不做 RAG 召回，工具仍是 `search_tender` + `download_tender` + `parse_tender` 三个；
- 不做自检（self_check），下一轮再加；
- `build_bidding_chain` 保留代码但标记 deprecated，不删除（避免破坏其他可能的引用）；
- 不接 MinIO，下载文件仍存本地目录；
- `astream_events` 的 `version` 参数固定为 `"v2"`（v1 已弃用）。



# 请在现有 LangGraph 状态机基础上实现两个增强：（A）第一个 HITL 中断点——解析结果人工确认；（B）RAG 召回历史标书——为下一步标书编写做准备。

## 目标

用户说"帮我搜索等保招标，找到合适的解析一下"时，Agent 自主完成搜索→下载→解析三步后，**不再直接返回最终摘要**，而是：
1. 将解析结果（项目名称、预算、评分表、资格要求、废标项）整理为结构化卡片推送给前端
2. 触发 HITL 中断，等待用户确认"这个招标项目合适，继续"
3. 用户确认后，Agent 调用 RAG 从 Qdrant 历史标书库（kb_type=2）检索相似段落
4. 将检索到的历史标书片段作为上下文，告知用户"已找到 N 份参考标书，可以开始编写"

## A. HITL 中断点实现

### graph.py — 更新状态机

#### 1. AgentState 新增字段

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    tender_parsed: bool       # 招标文件是否已解析完成
    human_confirmed: bool     # 用户是否已确认解析结果
    rag_context: str          # RAG 检索到的历史标书片段
```

#### 2. 新增 review_parsed_node

```python
def review_parsed_node(state: AgentState) -> AgentState:
    """解析结果人工审核节点。此节点本身不做事，只是中断点占位。"""
    return state
```

#### 3. 新增 rag_recall_node

```python
def rag_recall_node(state: AgentState) -> AgentState:
    """RAG 召回历史标书。从 state 中提取项目名称，调用 memory.get_bidding_context() 检索。"""
    # 从 messages 中提取 parse_tender 的结果（项目名称）
    # 调用 get_bidding_context(project_name) 检索历史标书
    # 返回 {"rag_context": "检索到的片段...", "messages": [AIMessage("已找到N份参考标书...")]}
```

#### 4. 更新条件路由

```python
def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    # 工具调用完毕后，检查是否解析完成
    if state.get("tender_parsed") and not state.get("human_confirmed"):
        return "review_parsed"  # 进入 HITL 中断
    return "__end__"

def should_continue_after_review(state: AgentState) -> str:
    """审核节点后的路由。"""
    if state.get("human_confirmed"):
        return "rag_recall"     # 用户确认 → RAG 召回
    return "__end__"            # 用户未确认 → 结束
```

#### 5. 更新 build_bidding_graph()

```python
def build_bidding_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("review_parsed", review_parsed_node)
    graph.add_node("rag_recall", rag_recall_node)
    
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    
    # HITL 中断：在 review_parsed 节点前中断
    graph.add_edge("review_parsed", "review_parsed")  # 自环占位，实际由 interrupt 控制
    graph.add_conditional_edges("review_parsed", should_continue_after_review)
    
    graph.add_edge("rag_recall", "agent")  # RAG 结果回到 agent 生成最终回复
    
    # 使用 interrupt_before 在 review_parsed 前暂停
    return graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["review_parsed"]
    )
```

#### 6. tools 节点更新

`parse_tender` 工具执行后，在 ToolNode 或自定义 tool_node 中设置 `tender_parsed=True`：

```python
# 自定义 tool_node 中：
result = tool.invoke(tool_call)
if tool_call["name"] == "parse_tender":
    # 解析完成，设置标志
    return {
        "messages": [ToolMessage(...)],
        "tender_parsed": True
    }
```

若使用内置 ToolNode，则在 agent_node 的后处理中检测 parse_tender 的 ToolMessage，设置 `tender_parsed`。

### routers — HITL 恢复接口

#### 1. 新增 POST /chat/{thread_id}/resume

```python
@router.post("/chat/{thread_id}/resume")
async def resume_chat(thread_id: str, body: ResumeRequest):
    """恢复被 HITL 中断的对话。"""
    graph = build_bidding_graph()
    # 设置 human_confirmed = True
    result = await graph.ainvoke(
        Command(resume={"human_confirmed": True}),
        config={"configurable": {"thread_id": thread_id}}
    )
    # 流式返回后续结果
```

#### 2. SSE 推送 hitl 事件

当图执行到 `interrupt_before=["review_parsed"]` 时，routers 检测到图暂停：

```python
# astream_events 中检测中断
async for event in graph.astream_events(...):
    if event["event"] == "on_interrupt":
        # 图被中断，推送 hitl 事件
        yield sse_event("hitl", {
            "task_type": "parsed_review",
            "thread_id": thread_id,
            "review_data": {
                "project_name": "...",
                "budget": "...",
                "deadline": "...",
                "qualification_requirements": [...],
                "disqualification_items": [...]
            }
        })
```

#### 3. 前端交互流程

1. 前端收到 `type=hitl` 事件，渲染解析结果确认卡片（项目名称、预算、截止日期、资格要求、废标项）
2. 用户点击「确认合适，开始编写」→ POST `/chat/{thread_id}/resume`
3. 后端恢复图执行，进入 `rag_recall` 节点 → `agent` 节点生成最终回复
4. 后续 SSE 流继续推送 token 和最终回复

## B. RAG 召回历史标书

### memory.py — 实现 get_bidding_context

```python
def get_bidding_context(tender_title: str, top_k: int = 5) -> dict:
    """从 Qdrant 历史标书库检索相似段落。
    
    返回：
    {
        "context": "检索到的标书片段拼接文本",
        "doc_ids": [3, 7, 12],
        "doc_titles": ["XX项目标书", "YY项目标书", ...]
    }
    """
    # 1. 调用 get_embeddings() 将 tender_title 向量化
    # 2. 查询 Qdrant collection "kb_type_2" (历史标书库)
    # 3. 按 similarity 排序取 top_k
    # 4. 返回 context + doc_ids + doc_titles
```

### Qdrant Collection 初始化

#### 1. 新建 qdrant_client.py

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

def get_qdrant() -> QdrantClient:
    """返回 Qdrant 客户端实例。"""
    return QdrantClient(url=settings.QDRANT_URL)

def init_collections():
    """初始化知识库 collection。"""
    client = get_qdrant()
    # 历史标书库
    if not client.collection_exists("bidding_history"):
        client.create_collection(
            "bidding_history",
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
        )
    # 等保标准库
    if not client.collection_exists("assessment_standard"):
        client.create_collection(...)
    # 企业本地库
    if not client.collection_exists("enterprise_local"):
        client.create_collection(...)
```

#### 2. 新建 kb_ingest.py — 知识库灌入

```python
def ingest_bidding_doc(doc_id: int, file_path: str, doc_title: str):
    """将历史标书文档向量化并灌入 Qdrant。"""
    # 1. 读取文件，提取文本
    # 2. 按 chunk_size=500, overlap=50 切分
    # 3. 调用 get_embeddings() 批量向量化
    # 4. 写入 Qdrant "bidding_history" collection，payload 含 doc_id, doc_title, chunk_text
    # 5. 更新 kb_documents.chunk_count 和 status=1
```

### rag_recall_node — 调用 RAG

```python
def rag_recall_node(state: AgentState) -> AgentState:
    # 从 state["messages"] 中提取 parse_tender 的结果
    # 找到项目名称
    project_name = extract_project_name(state["messages"])
    
    # 调用 RAG 检索
    rag_result = get_bidding_context(project_name, top_k=5)
    
    # 返回 RAG 上下文 + 提示消息
    return {
        "rag_context": rag_result["context"],
        "messages": [AIMessage(
            content=f"已找到 {len(rag_result['doc_ids'])} 份参考标书："
                    f"{', '.join(rag_result['doc_titles'])}。"
                    f"可以开始编写投标文件了，请说"开始编写"。"
        )]
    }
```

### agent_node — 注入 RAG 上下文

`agent_node` 中，当 `state.get("rag_context")` 非空时，将 RAG 上下文注入 system prompt：

```python
def agent_node(state: AgentState):
    system_prompt = get_bidding_router_prompt()
    if state.get("rag_context"):
        system_prompt += f"\n\n## 参考历史标书片段\n{state['rag_context']}"
    messages = [SystemMessage(system_prompt)] + state["messages"]
    # ...
```

## config.py — 新增配置

1. `QDRANT_URL`：Qdrant 服务地址，默认 `"http://localhost:6333"`
2. `QDRANT_COLLECTION_BIDDING`：历史标书 collection 名，默认 `"bidding_history"`
3. `QDRANT_COLLECTION_STANDARD`：等保标准 collection 名，默认 `"assessment_standard"`
4. `QDRANT_COLLECTION_ENTERPRISE`：企业本地 collection 名，默认 `"enterprise_local"`
5. `EMBEDDING_MODEL`：Embedding 模型名，默认 `"BAAI/bge-large-zh-v1.5"`
6. `EMBEDDING_DIM`：向量维度，默认 1024
7. `RAG_TOP_K`：RAG 检索返回数量，默认 5
8. `CHUNK_SIZE`：文本切分大小，默认 500
9. `CHUNK_OVERLAP`：切分重叠，默认 50

## requirements.txt — 新增依赖

```
qdrant-client==1.11.*
sentence-transformers==3.*
langgraph-checkpoint-sqlite==0.2.*
```

## 数据库 — 新增 API

1. `POST /kb/upload`：上传历史标书文档，创建 `kb_documents` 记录（kb_type=2），调用 `ingest_bidding_doc()` 向量化灌入 Qdrant；
2. `GET /kb/documents?kb_type=`：查看知识库文档列表。

## 验证标准

### HITL 中断

1. 用户说"帮我搜索等保招标，找到合适的解析一下"，Agent 完成搜索→下载→解析三步后，SSE 流暂停，推送 `type=hitl` 事件；
2. 前端渲染解析结果确认卡片，展示项目名称、预算、截止日期、资格要求、废标项；
3. 用户点击「确认」后，POST `/chat/{thread_id}/resume`，图恢复执行；
4. 服务日志显示 `[graph] interrupt at review_parsed` → `[graph] resume` → `[graph] rag_recall` → `[graph] agent`；
5. 未点击确认时，图保持中断状态，不继续执行。

### RAG 召回

6. 用户确认后，Agent 从 Qdrant 检索历史标书，返回"已找到 N 份参考标书"的提示；
7. `bidding_tasks.reference_doc_ids` 写入了检索到的 `doc_id` 列表；
8. `bidding_tasks.status` 从 1（已解析）更新为 2（编写中）；
9. Qdrant 无数据时，Agent 提示"未找到参考标书，建议先上传历史标书"，不报错。

### 知识库灌入

10. `POST /kb/upload` 上传一份历史标书 PDF，`kb_documents` 创建记录且 `status` 变为 1（已向量化）；
11. Qdrant `bidding_history` collection 中可查到对应的向量数据。

## 约束

- 本轮只实现第一个 HITL（解析结果确认），不做第二个 HITL（自检审核）；
- 本轮 RAG 只做历史标书库（kb_type=2）的检索和灌入，等保标准库和企业本地库的灌入下一轮再加；
- `agent_node` 的工具仍只有 `search_tender` + `download_tender` + `parse_tender`，本轮不新增标书编写工具；
- `MemorySaver` 仍用内存级别，HITL 恢复在同一进程内完成；生产环境后续换 `SqliteSaver` 持久化；
- 不做标书生成（`generate_bidding`），下一轮（step5）再加；
- 不做自检（`self_check`），下下轮（step5）再加。


# 请在现有 LangGraph 状态机基础上实现：（A）标书生成工具——参考 RAG 召回的历史标书编写投标文件；（B）废标自检工具——对生成的标书逐条检查废标项/格式/错字；（C）第二个 HITL 中断点——自检结果人工审核。本步完成后，商务线招投标全流程闭环。

## 目标

用户确认解析结果、RAG 召回历史标书后，说"开始编写"，Agent 自主执行：
1. 调用 `generate_bidding` 工具，参考历史标书风格生成投标文件各部分（公司简介、资质、项目团队，报价标注"待人工审核"）
2. 调用 `self_check` 工具，对生成的标书逐条检查：废标项是否全部满足、格式是否符合招标文件要求、错别字检查
3. 自检通过后触发第二个 HITL 中断，等待用户审核自检结果
4. 用户审核通过后，`bidding_tasks.status` 更新为 5（已完成），返回最终投标文件

## A. generate_bidding 工具

### tools.py — 新增 generate_bidding

```python
@tool
def generate_bidding(tender_info: str, rag_context: str, section: str = "all") -> str:
    """根据招标信息和历史标书参考，生成投标文件的指定部分。
    tender_info: parse_tender 返回的招标文件解析结果（JSON 字符串）
    rag_context: RAG 检索到的历史标书片段
    section: 生成哪个部分，可选 all/company_profile/qualification/project_team/pricing
    返回结构化 JSON，包含生成的各部分内容
    """
```

#### 实现要点

1. 解析 `tender_info`（JSON 字符串）获取项目名称、资格要求、评分表等；
2. 将 `rag_context`（历史标书片段）作为风格参考注入 Prompt；
3. 调用 `get_deepseek()` 生成投标文件各部分：
   - `company_profile`：公司简介（参考历史标书的写法和篇幅）
   - `qualification`：资质响应（逐条对应招标文件的资格要求，明确"满足/具备"）
   - `project_team`：项目团队（项目经理 + 测评人员，参考历史标书的团队结构）
   - `pricing`：报价部分**不生成具体金额**，标注"（待人工审核）"
4. 返回 JSON 字符串：

```json
{
    "company_profile": "公司成立于...",
    "qualification": "具备网络安全等级保护测评机构推荐证书...",
    "project_team": "项目经理1名，持有CISP证书...",
    "pricing": "（待人工审核）"
}
```

5. 异常处理：LLM 生成失败返回 `{"error": "...", "detail": "..."}`；
6. 加日志：记录项目名称、生成分区、各部分字数、耗时。

### prompt_layer.py — 新增标书生成 Prompt

```python
def get_bidding_generation_prompt() -> str:
    """标书生成 Prompt。约束：
    - 参考 rag_context 中历史标书的风格、结构和篇幅
    - 资质部分逐条响应招标文件的资格要求
    - 报价部分不生成具体金额
    - 输出格式为 JSON
    """
```

### graph.py — 新增 generate 节点

```python
def generate_node(state: AgentState) -> AgentState:
    """标书生成节点。当用户说"开始编写"且 rag_context 非空时触发。"""
    # 1. 从 state 提取 tender_info（parse_tender 结果）和 rag_context
    # 2. 调用 generate_bidding 工具
    # 3. 将结果写入 state
    # 4. 更新 bidding_tasks.bidding_sections + status=2（编写中）
    return {
        "messages": [...],
        "bidding_sections": {...}
    }
```

## B. self_check 工具

### tools.py — 新增 self_check

```python
@tool
def self_check(bidding_sections: str, tender_info: str) -> str:
    """对生成的投标文件进行自检。逐条检查废标项是否满足、格式是否符合要求、错别字。
    bidding_sections: generate_bidding 返回的投标内容（JSON 字符串）
    tender_info: parse_tender 返回的招标文件解析结果（JSON 字符串）
    返回自检结果 JSON
    """
```

#### 实现要点

1. 解析 `bidding_sections` 和 `tender_info`；
2. 调用 `get_deepseek()` + `get_compliance_prompt()` 做三维度检查：
   - **废标项检查**：逐条对照 `tender_info.disqualification_items`，检查投标内容是否满足，输出 pass/warning/danger
   - **格式检查**：检查投标文件格式是否符合招标文件要求（签章、格式、份数等，基于解析结果中的评分表格式要求）
   - **错别字检查**：扫描投标内容中的错别字和用词不当
3. 返回 JSON 字符串：

```json
{
    "overall_status": "pass",
    "disqualification_check": [
        {"item": "投标保证金比例", "type": "废标项", "status": "pass", "detail": "已包含保证金缴纳承诺"},
        {"item": "投标文件签署盖章", "type": "废标项", "status": "warning", "detail": "需人工确认盖章页"}
    ],
    "format_check": [
        {"item": "文件格式", "status": "pass", "detail": "符合招标文件要求"}
    ],
    "typo_check": [
        {"item": "公司简介第3段", "status": "warning", "detail": ""具备"疑似应为"具备""}
    ],
    "summary": "共检查8项，通过6项，警告2项，危险0项"
}
```

4. 异常处理：LLM 检查失败返回 `{"error": "...", "detail": "..."}`；
5. 加日志：记录检查项数、通过/警告/危险数量、耗时。

### prompt_layer.py — 复用 compliance_prompt

`get_compliance_prompt()` 已在 ref-backend-arch.md 中定义，本轮直接使用，无需新增。

### graph.py — 新增 selfcheck 节点

```python
def selfcheck_node(state: AgentState) -> AgentState:
    """废标自检节点。标书生成后自动触发。"""
    # 1. 从 state 提取 bidding_sections 和 tender_info
    # 2. 调用 self_check 工具
    # 3. 将结果写入 state
    # 4. 更新 bidding_tasks.compliance_result + status=3（废标检查中）
    return {
        "messages": [...],
        "compliance_result": {...},
        "selfcheck_done": True
    }
```

## C. 第二个 HITL 中断点

### AgentState 新增字段

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    tender_parsed: bool
    human_confirmed: bool
    rag_context: str
    bidding_sections: dict        # 新增：生成的投标内容
    compliance_result: dict       # 新增：自检结果
    selfcheck_done: bool          # 新增：自检是否完成
    selfcheck_approved: bool      # 新增：自检是否通过人工审核
```

### graph.py — 更新状态机

```python
def build_bidding_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("review_parsed", review_parsed_node)
    graph.add_node("rag_recall", rag_recall_node)
    graph.add_node("generate", generate_node)          # 新增
    graph.add_node("selfcheck", selfcheck_node)        # 新增
    graph.add_node("review_selfcheck", review_selfcheck_node)  # 新增：第二个 HITL

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    
    # 第一个 HITL
    graph.add_conditional_edges("review_parsed", should_continue_after_review)
    graph.add_edge("rag_recall", "agent")
    
    # 标书生成 → 自检 → 第二个 HITL
    graph.add_conditional_edges("agent", should_generate)  # 新增路由：用户说"开始编写"时进 generate
    graph.add_edge("generate", "selfcheck")               # 生成完自动自检
    graph.add_edge("selfcheck", "review_selfcheck")       # 自检完进入审核中断
    graph.add_conditional_edges("review_selfcheck", should_continue_after_selfcheck)
    
    return graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["review_parsed", "review_selfcheck"]  # 两个中断点
    )
```

### should_generate 路由

```python
def should_generate(state: AgentState) -> str:
    """判断是否进入标书生成。"""
    last_message = state["messages"][-1]
    if (state.get("human_confirmed") 
        and state.get("rag_context")
        and not state.get("bidding_sections")
        and "开始编写" in last_message.content):
        return "generate"
    return should_continue(state)  # 回退到正常路由
```

### should_continue_after_selfcheck

```python
def should_continue_after_selfcheck(state: AgentState) -> str:
    """自检审核后的路由。"""
    if state.get("selfcheck_approved"):
        return "__end__"  # 审核通过 → 结束
    return "generate"     # 审核驳回 → 重新生成
```

### review_selfcheck_node

```python
def review_selfcheck_node(state: AgentState) -> AgentState:
    """自检结果人工审核节点。中断点占位。"""
    return state
```

### routers — 更新恢复接口

`POST /chat/{thread_id}/resume` 支持两种恢复场景：

```python
@router.post("/chat/{thread_id}/resume")
async def resume_chat(thread_id: str, body: ResumeRequest):
    graph = build_bidding_graph()
    
    if body.review_type == "parsed_review":
        # 第一个 HITL：解析结果确认
        result = await graph.ainvoke(
            Command(resume={"human_confirmed": True}),
            config={"configurable": {"thread_id": thread_id}}
        )
    elif body.review_type == "selfcheck_review":
        # 第二个 HITL：自检结果审核
        update = {"selfcheck_approved": body.approved}  # True=通过, False=驳回重做
        if body.modified_sections:
            # 用户修改了部分内容，更新 bidding_sections
            update["bidding_sections"] = body.modified_sections
        result = await graph.ainvoke(
            Command(resume=update),
            config={"configurable": {"thread_id": thread_id}}
        )
    
    # 流式返回后续结果
```

### SSE 推送第二个 hitl 事件

```python
# 自检完成后推送
yield sse_event("hitl", {
    "task_type": "selfcheck_review",
    "thread_id": thread_id,
    "review_data": {
        "bidding_sections": state["bidding_sections"],
        "compliance_result": state["compliance_result"],
        "summary": "共检查8项，通过6项，警告2项，危险0项"
    }
})
```

### bidding_tasks 状态流转

| 节点 | status |
|------|--------|
| generate 完成 | 2（编写中） |
| selfcheck 完成 | 3（废标检查中） |
| review_selfcheck 中断 | 4（待人工审核） |
| 用户审核通过 | 5（已完成） |
| 用户审核驳回 → 重新 generate | 回到 2 |

## 数据库 — 新增审核接口

1. `POST /review/{review_task_id}`：提交审核结果
   - body: `{ "review_result": 0|1|2, "review_comment": "...", "modified_sections": {...} }`
   - review_result=0（通过）→ 更新 bidding_tasks.status=5，写入 review_tasks
   - review_result=1（驳回）→ 触发重新生成，bidding_tasks.status 回到 2
   - review_result=2（修改后通过）→ 用 modified_sections 更新 bidding_sections，status=5

## 前端 — 更新审核面板

### BiddingWorkbench.vue 新增自检审核面板

- `type=hitl` 且 `task_type=selfcheck_review` 时，右侧渲染自检审核面板：
  - 上半区：展示生成的投标内容（`bidding_sections` 各部分，可编辑）
  - 下半区：展示自检结果（`compliance_result`，pass/warning/danger 三色标注，可展开详情）
  - 底部按钮：「通过」「驳回（重新生成）」「修改后通过」
- 「通过」→ POST `/review/{id}` `{ review_result: 0 }`
- 「驳回」→ POST `/review/{id}` `{ review_result: 1 }`，图回到 generate 节点重新生成
- 「修改后通过」→ POST `/review/{id}` `{ review_result: 2, modified_sections: {...} }`

## config.py — 新增配置

1. `BIDDING_MAX_RETRIES`：标书生成最大重试次数（驳回后重新生成），默认 3
2. `SELFCHECK_MODEL`：自检使用的模型，默认用 `get_deepseek()`，可配置为更强模型

## 验证标准

### 标书生成

1. 用户确认解析结果 + RAG 召回后，说"开始编写"，Agent 调用 `generate_bidding` 生成投标文件；
2. 生成的 `bidding_sections` 包含 company_profile / qualification / project_team 四部分，pricing 标注"（待人工审核）"；
3. 生成内容参考了 RAG 召回的历史标书风格（篇幅、结构相似）；
4. `bidding_tasks.bidding_sections` 写入生成结果，`status` 更新为 2；
5. SSE 流推送 `type=tool_call` 事件，`tool_name=generate_bidding`。

### 废标自检

6. 标书生成后自动触发 `self_check`，不需要用户指令；
7. 自检结果包含废标项检查、格式检查、错别字检查三个维度；
8. 每项标注 pass/warning/danger，有 detail 说明；
9. `bidding_tasks.compliance_result` 写入自检结果，`status` 更新为 3；
10. SSE 流推送 `type=tool_call` 事件，`tool_name=self_check`。

### 第二个 HITL

11. 自检完成后，SSE 流暂停，推送 `type=hitl` 事件，`task_type=selfcheck_review`；
12. 前端渲染自检审核面板，展示投标内容 + 自检结果；
13. 用户点击「通过」→ `bidding_tasks.status` 更新为 5（已完成），图结束；
14. 用户点击「驳回」→ 图回到 generate 节点重新生成，`bidding_tasks.status` 回到 2；
15. 用户点击「修改后通过」→ 用修改后的内容更新 `bidding_sections`，`status` 更新为 5；
16. 驳回重试超过 `BIDDING_MAX_RETRIES` 次后，Agent 提示"已达最大重试次数，建议人工处理"。

## 约束

- 本轮只做商务线标书生成 + 自检 + 第二个 HITL，不做技术线测评核查；
- `generate_bidding` 和 `self_check` 作为 LangGraph 节点调用，不绑定到 `bind_tools`（不是 LLM 自主调用的工具，而是图流程的固定节点）；
- 报价部分始终标注"待人工审核"，不生成具体金额；
- 自检只做废标项/格式/错字三个维度，不做评分预估（评分由评委打分，Agent 不预测）；
- `MemorySaver` 仍用内存级别，两个 HITL 恢复在同一进程内完成；
- 不做用户上传招标/投标文件审核（step6 再加）。



# 请在现有项目基础上实现用户自主上传场景：（A）上传招标文件——Agent 解析后走与自动搜索相同的流程；（B）上传投标文件——Agent 审核废标项/格式/错字，不确定项触发人工确认。同时完善 review_tasks 审核工作流的闭环。

## 目标

本步覆盖两种用户主动上传场景，与前面的自动搜索流程形成互补：

**场景一（上传招标文件）**：
1. 用户在对话框上传招标文件（PDF/Word），说"帮我解析这个招标文件"
2. Agent 调用 `parse_tender` 解析，提取预算/评分表/资格要求/废标项
3. 触发第一个 HITL（解析结果确认）→ RAG 召回 → 标书生成 → 自检 → 第二个 HITL
4. 与自动搜索流程完全一致，只是入口从"搜索"变成"上传"

**场景二（上传投标文件审核）**：
1. 用户上传已写好的投标文件（PDF/Word），说"帮我审核这个投标文件"
2. Agent 调用 `review_bidding` 工具，解析投标文件内容
3. 若用户同时上传了招标文件，Agent 交叉比对；若未上传招标文件，Agent 只做格式和错字检查
4. 审核结果中不确定/有疑问的地方触发人工确认
5. 用户确认后生成审核报告

## A. 上传招标文件流程

### routers — 更新对话路由

对话路由中，当用户消息带 `file_extracted_text`（文件附件）且 `intent_type=1` 时：

1. 判断文件类型：
   - 若 `upload_purpose=1`（招标文件）→ 走招标文件解析流程
   - 若 `upload_purpose=5`（投标文件，新增）→ 走投标文件审核流程
2. 招标文件解析流程：将文件路径写入 `bidding_tasks.tender_file_path`，设置 `tender_parsed=False`，让 Agent 自主调用 `parse_tender`；
3. 图流程不变：agent → tools(parse_tender) → review_parsed(HITL) → rag_recall → generate → selfcheck → review_selfcheck(HITL) → END。

### graph.py — agent_node 识别上传场景

`agent_node` 的 system prompt 中增加上传场景指引：

```python
def get_bidding_router_prompt() -> str:
    return """你是等保测评商务助手。
    
    ## 工作模式
    1. 用户说"搜索招标"→ 调用 search_tender → download_tender → parse_tender
    2. 用户上传招标文件并说"解析"→ 直接调用 parse_tender（文件路径已在上下文中）
    3. 用户上传投标文件并说"审核"→ 调用 review_bidding
    4. 用户确认解析结果后说"开始编写"→ 进入标书生成流程
    
    ## 约束
    - 解析完成后必须等待用户确认，不要直接开始编写
    - 报价部分不生成具体金额
    """
```

### 前端 — 上传入口

BiddingWorkbench.vue 对话区底部新增上传按钮：

1. 点击后弹出文件选择器，选择 PDF/Word 文件；
2. 上传时传 `upload_purpose=1`（招标文件）或 `upload_purpose=5`（投标文件）；
3. 上传成功后，在对话框自动填充消息："我上传了一份招标文件，帮我解析" / "我上传了一份投标文件，帮我审核"；
4. 用户可修改消息后发送，或直接发送。

## B. review_bidding 工具

### tools.py — 新增 review_bidding

```python
@tool
def review_bidding(bidding_file_path: str, tender_info: str = "") -> str:
    """审核投标文件。检查废标项、格式、错字，返回审核结果。
    bidding_file_path: 投标文件本地路径
    tender_info: 招标文件解析结果（JSON 字符串），可选。有则交叉比对，无则只查格式和错字
    返回审核结果 JSON
    """
```

#### 实现要点

1. 根据 `bidding_file_path` 后缀提取文本（复用 `parse_tender` 的文本提取逻辑）：
   - `.pdf`：PyMuPDF
   - `.docx`：python-docx
   - `.doc`：python-docx 尝试，失败提示转 PDF
2. 将投标文件文本交给 DeepSeek 做结构化审核：
   - **有 `tender_info`**：逐条对照废标项检查 + 格式检查 + 错字检查
   - **无 `tender_info`**：只做格式检查 + 错字检查 + 常见废标项通用检查
3. 返回 JSON 字符串：

```json
{
    "overall_status": "warning",
    "items": [
        {
            "item": "投标保证金缴纳",
            "type": "废标项",
            "status": "pass",
            "detail": "投标文件中包含保证金缴纳承诺函",
            "confidence": 0.95,
            "need_human": false
        },
        {
            "item": "法定代表人签字",
            "type": "废标项",
            "status": "warning",
            "detail": "签字页图片模糊，无法确认是否为法定代表人亲笔签字",
            "confidence": 0.62,
            "need_human": true
        },
        {
            "item": "错别字",
            "type": "格式",
            "status": "warning",
            "detail": "第3页第2段"侧试"疑为"测试"",
            "confidence": 0.88,
            "need_human": false
        }
    ],
    "summary": "共检查12项，通过9项，警告3项，危险0项，需人工确认1项"
}
```

4. `need_human=true` 的项触发人工确认；
5. 异常处理：文件不存在 / 解析失败返回 `{"error": "...", "detail": "..."}`。

### prompt_layer.py — 新增审核 Prompt

```python
def get_bidding_review_prompt() -> str:
    """投标文件审核 Prompt。约束：
    - 逐条检查废标项，标注 pass/warning/danger
    - 不确定项 need_human=true
    - 有招标文件时交叉比对，无则做通用检查
    - 输出结构化 JSON
    """
```

## C. 审核工作流闭环

### review_tasks 完整生命周期

| 阶段 | 触发条件 | task_type | source_type | review_data |
|------|----------|-----------|-------------|-------------|
| 报价审核 | 标书生成后自检通过 | 0 | 0（bidding_tasks） | pricing_section + ai_suggestion |
| 自检审核 | 自检完成 | 0 | 0 | bidding_sections + compliance_result |
| 投标文件审核 | 用户上传投标文件 | 0 | 0 | review_bidding 结果 |
| 低置信度复核 | confidence < 0.80 | 1 | 1（assessment_records） | ai_result + human_result + confidence |

### routers — 完善审核接口

#### 1. POST /review/{review_task_id} — 统一审核提交

```python
@router.post("/review/{review_task_id}")
async def submit_review(review_task_id: int, body: ReviewRequest, user: User):
    """提交审核结果，恢复对应流程。"""
    # 1. 查询 review_tasks 记录，校验 user_id
    # 2. 更新 review_tasks: review_result, review_comment, reviewer_id, status=1, reviewed_at
    # 3. 根据 source_type 和 task_type 分发：
    #    - task_type=0, source_type=0: 更新 bidding_tasks
    #    - task_type=1, source_type=1: 更新 assessment_records
    # 4. 恢复 LangGraph 流程（如果有 thread_id 关联）
```

#### 2. GET /review?status=0 — 待审核列表

```python
@router.get("/review")
async def list_reviews(status: int = 0, user: User):
    """获取当前用户的审核任务列表。status=0 待审核，1 已审核。"""
    # 返回: review_task_id, task_type, source_type, source_id, review_data 摘要, created_at
```

#### 3. GET /review/{review_task_id} — 审核详情

```python
@router.get("/review/{review_task_id}")
async def get_review(review_task_id: int, user: User):
    """获取审核任务详情。"""
    # 返回: 完整 review_data + review_result + review_comment + reviewer 信息
```

### 前端 — 审核工作台

#### ReviewWorkbench.vue（审核工作台）

1. 左侧：待审核任务列表（`GET /review?status=0`），按 `task_type` 分组：
   - 报价审核（task_type=0）→ 显示项目名称 + 报价金额 + AI 建议
   - 低置信度复核（task_type=1）→ 显示控制点 + AI 结果 vs 人工结果 + 置信度
2. 右侧：审核详情面板（点击列表项后展示）：
   - 报价审核：展示 `review_data.pricing_section` + `tender_budget` + `ai_suggestion`，按钮「通过」「驳回」「修改后通过」
   - 低置信度复核：展示 `comparison_result` 差异对比 + `kb_references` 参考 + `confidence` 进度条，按钮「通过」「驳回」
3. 提交审核：POST `/review/{id}`，提交后从待审核列表移除，刷新列表。

#### BiddingWorkbench.vue — 投标文件审核面板

- `type=hitl` 且 `task_type=bidding_review` 时，右侧渲染投标文件审核面板：
  - 展示审核结果列表（每项：item / type / status 三色 / detail / confidence）
  - `need_human=true` 的项高亮，提供「确认通过」「确认不通过」「跳过」按钮
  - 全部确认后，点击「生成审核报告」→ POST `/review/{id}` 提交最终结果

## D. upload_purpose 扩展

### resources 表 — 新增 upload_purpose=5

| upload_purpose | 用途 | storage_scene | 业务联动 |
|----------------|------|---------------|----------|
| 0 | 普通资源 | 0 | 无 |
| 1 | 招标文件 | 0 | 更新 bidding_tasks.tender_file_path |
| 2 | 历史标书 | 0 | 创建 kb_documents + Qdrant 灌入 |
| 3 | 测评截图 | 0 | 更新 assessment_records.screenshot_path |
| 4 | 资产核查表 | 2 | 提取内容供 Agent 生成拓扑 |
| **5** | **投标文件** | **0** | **触发 review_bidding 审核流程** |

### upload_service_minio.py — 更新联动

```python
async def handle_upload(file, user_id, upload_purpose, session_id=None):
    # ... 上传到 MinIO + 写 resources 表 ...
    
    if upload_purpose == 5:
        # 投标文件：写入 file_extracted_text 供对话上下文用
        extracted_text = extract_text(file_path)
        # 关联到当前 session 的 bidding_tasks
        if session_id:
            task = get_bidding_task_by_session(session_id)
            if task:
                # 更新 task，标记有待审核投标文件
                task.bidding_sections = task.bidding_sections or {}
                task.bidding_sections["uploaded_bidding_file"] = file_path
```

## config.py — 新增配置

1. `REVIEW_CONFIDENCE_THRESHOLD`：人工确认置信度阈值，默认 0.75，低于此值的审核项 `need_human=true`
2. `BIDDING_REVIEW_MAX_ITEMS`：投标文件审核最大检查项数，默认 20

## 验证标准

### 上传招标文件

1. 用户上传招标文件 PDF，说"帮我解析"，Agent 调用 `parse_tender` 解析；
2. 解析结果触发第一个 HITL，前端渲染确认卡片；
3. 用户确认后走 RAG → 生成 → 自检 → 第二个 HITL，流程与自动搜索完全一致；
4. `bidding_tasks.tender_file_path` 写入上传文件路径。

### 上传投标文件审核

5. 用户上传投标文件 Word，说"帮我审核"，Agent 调用 `review_bidding`；
6. 若同时有招标文件，交叉比对废标项；若无，只查格式和错字；
7. 审核结果中 `need_human=true` 的项触发 HITL，前端渲染审核面板；
8. 用户逐项确认后，POST `/review/{id}` 提交，生成审核报告；
9. `review_tasks` 创建记录（task_type=0, source_type=0），审核结果写入 `review_data`。

### 审核工作流闭环

10. `GET /review?status=0` 返回当前用户所有待审核任务，按 task_type 分组；
11. 审核人提交结果后，`review_tasks.status` 更新为 1，`reviewed_at` 写入时间戳；
12. `bidding_tasks` 或 `assessment_records` 的 status 根据审核结果联动更新；
13. 拒驳回退（review_result=1）正确触发对应流程回退。

## 约束

- 本轮只做商务线上传场景，不做技术线截图上传（技术线截图上传已在 ref-frontend-spec.md 中定义，实际实现在技术线步骤）；
- `review_bidding` 作为 LLM 可调用的工具（`bind_tools`），不是固定图节点——因为用户可能随时上传投标文件，不走标准图流程；
- 上传招标文件复用现有图流程（parse_tender → HITL → RAG → generate → selfcheck → HITL），不新建图；
- 审核报告暂存 `review_tasks.review_data`，不做独立报告表；
- `need_human` 判断基于 `confidence < REVIEW_CONFIDENCE_THRESHOLD`；
- 本步完成后商务线全流程闭环，下一步进入技术线开发。


# 请在 AssessmentWorkbench.vue 中实现网络拓扑图渲染模块，使用 Vue Flow 展示 Agent 生成的节点和边数据，支持分层布局、安全域分组、节点交互和导出功能。

## 目标

用户上传资产核查表后，Agent 调用 `generate_topology` 返回 `topology_data`（nodes + edges + security_zones + summary）。前端在对话区上方新增「网络拓扑图」标签页，用 Vue Flow 渲染交互式拓扑图。

## 依赖安装

```bash
npm install @vue-flow/core @vue-flow/background @vue-flow/controls @vue-flow/minimap
```

## 组件结构

```
src/components/topology/
├── TopologyPanel.vue          # 拓扑图主面板（标签页 + Vue Flow + 操作栏）
├── TopologyNode.vue           # 自定义节点组件（设备图标 + 信息卡）
├── TopologyEdge.vue           # 自定义边组件（带标签的连线）
├── SecurityZoneGroup.vue      # 安全域虚线框分组
├── TopologyDetailDrawer.vue   # 节点详情抽屉（点击节点弹出）
└── useTopology.ts             # 拓扑图数据转换 + 自动布局 composable
```

## useTopology.ts — 数据转换与布局

### 功能

1. 将后端 `topology_data`（原始 JSON）转换为 Vue Flow 支持的 `nodes` 和 `edges` 格式；
2. 按 `layer` 字段自动分层布局，遵循标准网络三层架构：核心层在顶部 → 汇聚层在中间 → 接入层在底部；
3. 按 `security_zones` 生成分组信息。

### 接口

```typescript
import { ref, computed } from 'vue'
import type { Node, Edge } from '@vue-flow/core'

interface RawTopologyData {
  nodes: Array<{
    id: string
    label: string           // 设备名称，如"核心交换机-01"
    type: string            // switch / router / firewall / server / database
    ip: string              // 设备 IP 地址，如"192.168.1.1"
    mac: string             // MAC 地址（可选）
    layer: string           // core（核心层）/ aggregation（汇聚层）/ access（接入层）
    zone: string            // 所属安全域，如"DMZ区" / "内网区" / "服务器区"
    device_model: string    // 设备型号（可选），如"H3C S5500"
    description: string     // 设备描述（可选）
  }>
  edges: Array<{
    id: string
    source: string
    target: string
    label: string           // 如"千兆" / "万兆"
    bandwidth: string       // 带宽（可选），如"1Gbps"
  }>
  security_zones: Array<{
    zone_name: string       // 安全域名称，如"DMZ区"
    nodes: string[]         // node id 列表
    description: string     // 域描述，如"对外服务区域"
    risk_level: string      // 风险等级（可选），如"高" / "中" / "低"
  }>
  summary: string
}

export function useTopology(rawData: Ref<RawTopologyData | null>) {
  const nodes = ref<Node[]>([])
  const edges = ref<Edge[]>([])
  const zones = ref<SecurityZoneGroup[]>([])

  // 布局参数 — 标准三层架构：核心层（顶部）→ 汇聚层（中间）→ 接入层（底部）
  const LAYER_Y_MAP = {
    core: 80,          // 核心层：核心交换机、核心路由器
    aggregation: 260,  // 汇聚层：汇聚交换机、防火墙
    access: 440,       // 接入层：接入交换机、服务器、数据库
  }
  const NODE_SPACING_X = 200
  const START_X = 120

  // 将原始数据转换为 Vue Flow 格式并自动布局
  watch(rawData, (data) => {
    if (!data) return
    
    // 1. 节点布局：按 layer 分层，同层内均匀分布
    const layerGroups: Record<string, any[]> = { core: [], aggregation: [], access: [] }
    data.nodes.forEach(node => {
      const layer = node.layer || 'access'
      if (!layerGroups[layer]) layerGroups[layer] = []
      layerGroups[layer].push(node)
    })

    const positionedNodes: Node[] = []
    Object.entries(layerGroups).forEach(([layer, nodes]) => {
      const y = LAYER_Y_MAP[layer] || 400
      nodes.forEach((node, index) => {
        const x = START_X + index * NODE_SPACING_X
        positionedNodes.push({
          id: node.id,
          type: 'topology-node',      // 自定义节点类型
          position: { x, y },
          data: {
            label: node.label,         // 设备名称
            deviceType: node.type,     // switch/firewall/server/database
            ip: node.ip,               // IP 地址
            mac: node.mac,             // MAC 地址
            layer: node.layer,         // 核心层/汇聚层/接入层
            zone: node.zone,           // 所属安全域
            deviceModel: node.device_model,    // 设备型号
            description: node.description,     // 设备描述
          },
        })
      })
    })
    nodes.value = positionedNodes

    // 2. 边转换
    edges.value = data.edges.map(edge => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'topology-edge',          // 自定义边类型
      label: edge.label,
      animated: true,                 // 连线动画
    }))

    // 3. 安全域分组（计算包围框）
    zones.value = data.security_zones.map(zone => {
      const zoneNodeIds = zone.nodes
      const zoneNodes = positionedNodes.filter(n => zoneNodeIds.includes(n.id))
      if (zoneNodes.length === 0) return null

      const minX = Math.min(...zoneNodes.map(n => n.position.x)) - 40
      const maxX = Math.max(...zoneNodes.map(n => n.position.x)) + 160
      const minY = Math.min(...zoneNodes.map(n => n.position.y)) - 30
      const maxY = Math.max(...zoneNodes.map(n => n.position.y)) + 80

      return {
        id: zone.zone_name,
        label: zone.zone_name,
        description: zone.description,
        bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
      }
    }).filter(Boolean)
  }, { immediate: true })

  return { nodes, edges, zones, summary: computed(() => rawData.value?.summary || '') }
}
```

## TopologyPanel.vue — 主面板

### 功能

1. 标签页切换：对话 | 拓扑图
2. Vue Flow 画布：渲染节点和边
3. 安全域虚线框：用 SVG overlay 绘制
4. 操作栏：导出 PNG、重置布局、显示/隐藏标签
5. 底部摘要：Agent 生成的拓扑分析文字

### 模板

```vue
<template>
  <div class="topology-panel" v-if="topologyData">
    <!-- 标签切换 -->
    <div class="tabs">
      <button :class="{ active: activeTab === 'chat' }" @click="activeTab = 'chat'">对话</button>
      <button :class="{ active: activeTab === 'topology' }" @click="activeTab = 'topology'">
        网络拓扑图
      </button>
    </div>

    <!-- 拓扑图画布 -->
    <div v-show="activeTab === 'topology'" class="topology-canvas">
      <!-- 操作栏 -->
      <div class="topology-toolbar">
        <button @click="exportPng">导出 PNG</button>
        <button @click="resetLayout">重置布局</button>
        <label class="toggle">
          <input type="checkbox" v-model="showLabels" /> 显示标签
        </label>
        <label class="toggle">
          <input type="checkbox" v-model="showZones" /> 安全域分组
        </label>
      </div>

      <!-- Vue Flow 画布 -->
      <VueFlow
        :nodes="nodes"
        :edges="edges"
        :default-viewport="{ zoom: 0.8 }"
        :min-zoom="0.3"
        :max-zoom="2"
        fit-view-on-init
      >
        <Background pattern-color="#aaa" :gap="16" />
        <Controls />
        <MiniMap />

        <!-- 自定义节点 -->
        <template #node-topology-node="props">
          <TopologyNode v-bind="props" @click="openDetail" />
        </template>

        <!-- 自定义边 -->
        <template #edge-topology-edge="props">
          <TopologyEdge v-bind="props" :show-label="showLabels" />
        </template>
      </VueFlow>

      <!-- 安全域分组 overlay -->
      <SecurityZoneGroup
        v-if="showZones"
        :zones="zones"
      />

      <!-- 底部摘要 -->
      <div class="topology-summary">
        <h4>拓扑分析</h4>
        <p>{{ summary }}</p>
      </div>
    </div>
  </div>
</template>
```

### 脚本

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import TopologyNode from './TopologyNode.vue'
import TopologyEdge from './TopologyEdge.vue'
import SecurityZoneGroup from './SecurityZoneGroup.vue'
import TopologyDetailDrawer from './TopologyDetailDrawer.vue'
import { useTopology } from './useTopology'

const props = defineProps<{
  topologyData: RawTopologyData | null
}>()

const activeTab = ref<'chat' | 'topology'>('chat')
const showLabels = ref(true)
const showZones = ref(true)
const selectedNode = ref(null)

const { nodes, edges, zones, summary } = useTopology(toRef(props, 'topologyData'))
const { onNodeClick, toObject } = useVueFlow()

// 节点点击 → 打开详情抽屉
onNodeClick(({ node }) => {
  selectedNode.value = node.data
})

// 导出 PNG
function exportPng() {
  // 使用 html-to-image 或 dom-to-image 导出
  const canvas = document.querySelector('.vue-flow__viewport')
  // 简化：截图 canvas 区域
  // 实际可用 html-to-image 库：import { toPng } from 'html-to-image'
}

// 重置布局
function resetLayout() {
  // 重新触发 useTopology 的布局计算
}
</script>
```

### 样式

```css
.topology-panel {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  overflow: hidden;
}

.tabs {
  display: flex;
  border-bottom: 1px solid var(--el-border-color);
}
.tabs button {
  padding: 8px 16px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}
.tabs button.active {
  color: var(--el-color-primary);
  border-bottom: 2px solid var(--el-color-primary);
}

.topology-canvas {
  height: 500px;
  position: relative;
}

.topology-toolbar {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 10;
  display: flex;
  gap: 8px;
  align-items: center;
}

.topology-summary {
  padding: 12px 16px;
  border-top: 1px solid var(--el-border-color);
  background: var(--el-fill-color-light);
  max-height: 120px;
  overflow-y: auto;
}
.topology-summary h4 {
  margin: 0 0 4px;
  font-size: 14px;
}
.topology-summary p {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
```

## TopologyNode.vue — 自定义节点

### 功能

1. 根据 `deviceType` 显示不同图标和颜色；
2. 显示设备名称、IP 地址、设备型号；
3. 按 `layer` 显示层级标签（核心层/汇聚层/接入层）；
4. 选中状态高亮；
5. 点击触发详情弹窗。

### 模板

```vue
<template>
  <div class="topology-node" :class="[`type-${data.deviceType}`, `layer-${data.layer}`]">
    <!-- 层级标签 -->
    <div class="layer-badge">{{ layerLabel }}</div>
    <!-- 设备图标 -->
    <div class="node-icon">
      <svg v-if="data.deviceType === 'switch'" viewBox="0 0 24 24">
        <!-- 交换机图标：多个端口 -->
        <rect x="3" y="8" width="18" height="8" rx="1" fill="currentColor"/>
        <circle cx="7" cy="12" r="1" fill="#fff"/><circle cx="11" cy="12" r="1" fill="#fff"/>
        <circle cx="15" cy="12" r="1" fill="#fff"/><circle cx="19" cy="12" r="1" fill="#fff"/>
      </svg>
      <svg v-if="data.deviceType === 'router'" viewBox="0 0 24 24">
        <!-- 路由器图标 -->
        <rect x="4" y="10" width="16" height="8" rx="2" fill="currentColor"/>
        <circle cx="8" cy="6" r="1.5" fill="currentColor"/><circle cx="16" cy="6" r="1.5" fill="currentColor"/>
        <line x1="8" y1="7" x2="8" y2="10" stroke="currentColor" stroke-width="1"/>
        <line x1="16" y1="7" x2="16" y2="10" stroke="currentColor" stroke-width="1"/>
      </svg>
      <svg v-if="data.deviceType === 'firewall'" viewBox="0 0 24 24">
        <!-- 防火墙图标：砖墙 -->
        <rect x="3" y="5" width="18" height="14" rx="1" fill="currentColor"/>
        <line x1="3" y1="10" x2="21" y2="10" stroke="#fff" stroke-width="1"/>
        <line x1="3" y1="14" x2="21" y2="14" stroke="#fff" stroke-width="1"/>
        <line x1="9" y1="5" x2="9" y2="10" stroke="#fff" stroke-width="1"/>
        <line x1="15" y1="5" x2="15" y2="10" stroke="#fff" stroke-width="1"/>
        <line x1="7" y1="10" x2="7" y2="14" stroke="#fff" stroke-width="1"/>
        <line x1="13" y1="10" x2="13" y2="14" stroke="#fff" stroke-width="1"/>
        <line x1="17" y1="10" x2="17" y2="14" stroke="#fff" stroke-width="1"/>
      </svg>
      <svg v-if="data.deviceType === 'server'" viewBox="0 0 24 24">
        <!-- 服务器图标：机架 -->
        <rect x="5" y="4" width="14" height="5" rx="1" fill="currentColor"/>
        <rect x="5" y="11" width="14" height="5" rx="1" fill="currentColor"/>
        <rect x="5" y="18" width="14" height="3" rx="1" fill="currentColor"/>
        <circle cx="8" cy="6.5" r="0.8" fill="#fff"/><circle cx="8" cy="13.5" r="0.8" fill="#fff"/>
      </svg>
      <svg v-if="data.deviceType === 'database'" viewBox="0 0 24 24">
        <!-- 数据库图标：圆柱体 -->
        <ellipse cx="12" cy="6" rx="8" ry="2.5" fill="currentColor"/>
        <path d="M4 6 V18 a8 2.5 0 0 0 16 0 V6" fill="currentColor"/>
        <ellipse cx="12" cy="6" rx="8" ry="2.5" fill="none" stroke="#fff" stroke-width="0.5"/>
        <ellipse cx="12" cy="12" rx="8" ry="2.5" fill="none" stroke="#fff" stroke-width="0.5"/>
      </svg>
    </div>
    <!-- 设备信息 -->
    <div class="node-info">
      <span class="node-label">{{ data.label }}</span>
      <span class="node-ip">{{ data.ip }}</span>
      <span class="node-model" v-if="data.deviceModel">{{ data.deviceModel }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps(['data'])

const layerLabel = computed(() => {
  const map = { core: '核心层', aggregation: '汇聚层', access: '接入层' }
  return map[props.data?.layer] || ''
})
</script>
```

### 节点类型样式

```css
.topology-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 2px solid #ddd;
  background: #fff;
  min-width: 140px;
  cursor: pointer;
  transition: all 0.2s;
}
.topology-node:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transform: translateY(-1px);
}

/* 按设备类型着色 */
.type-switch    { border-color: #3b82f6; }  /* 蓝色 */
.type-router    { border-color: #3b82f6; }  /* 蓝色 */
.type-firewall  { border-color: #ef4444; }  /* 红色 */
.type-server    { border-color: #22c55e; }  /* 绿色 */
.type-database  { border-color: #a855f7; }  /* 紫色 */

/* 按层级加左侧色条 */
.layer-core        { border-left: 4px solid #f59e0b; }      /* 核心层-橙色 */
.layer-aggregation { border-left: 4px solid #3b82f6; }      /* 汇聚层-蓝色 */
.layer-access      { border-left: 4px solid #22c55e; }      /* 接入层-绿色 */

/* 层级标签 */
.layer-badge {
  position: absolute;
  top: -10px;
  left: 8px;
  font-size: 10px;
  font-weight: 600;
  color: #6b7280;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

/* 图标背景色 */
.type-switch .node-icon    { background: #dbeafe; }
.type-router .node-icon    { background: #dbeafe; }
.type-firewall .node-icon  { background: #fee2e2; }
.type-server .node-icon    { background: #dcfce7; }
.type-database .node-icon  { background: #f3e8ff; }

.node-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.node-icon svg {
  width: 20px;
  height: 20px;
}

.node-info {
  display: flex;
  flex-direction: column;
}
.node-label {
  font-size: 13px;
  font-weight: 500;
  color: #1f2937;
}
.node-ip {
  font-size: 11px;
  color: #6b7280;
  font-family: monospace;
}
.node-model {
  font-size: 10px;
  color: #9ca3af;
}
```

## TopologyEdge.vue — 自定义边

### 功能

1. 带标签的贝塞尔曲线连线；
2. 连线动画（数据流动效果）；
3. 可切换显示/隐藏标签。

```vue
<template>
  <BaseEdge :id="id" :path="path" :style="edgeStyle" :marker-end="markerEnd" />
  <EdgeText
    v-if="showLabel && label"
    :x="centerX"
    :y="centerY"
    :label="label"
  />
</template>

<script setup>
import { computed } from 'vue'
import { BaseEdge, EdgeText, getBezierPath } from '@vue-flow/core'

const props = defineProps({
  id: String,
  sourceX: Number,
  sourceY: Number,
  targetX: Number,
  targetY: Number,
  sourcePosition: String,
  targetPosition: String,
  label: String,
  showLabel: Boolean,
})

const { path, labelX: centerX, labelY: centerY } = getBezierPath(props)

const edgeStyle = computed(() => ({
  stroke: '#94a3b8',
  strokeWidth: 2,
  strokeDasharray: '0',
}))
</script>
```

## SecurityZoneGroup.vue — 安全域分组

### 功能

用虚线框包围同安全域的节点，显示域名称和描述。

```vue
<template>
  <svg class="zone-overlay">
    <g v-for="zone in zones" :key="zone.id">
      <rect
        :x="zone.bounds.x"
        :y="zone.bounds.y"
        :width="zone.bounds.width"
        :height="zone.bounds.height"
        fill="rgba(99, 102, 241, 0.05)"
        stroke="#6366f1"
        stroke-width="1.5"
        stroke-dasharray="6 4"
        rx="8"
      />
      <text
        :x="zone.bounds.x + 8"
        :y="zone.bounds.y + 16"
        fill="#6366f1"
        font-size="12"
        font-weight="600"
      >
        {{ zone.label }}
      </text>
    </g>
  </svg>
</template>

<style scoped>
.zone-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}
</style>
```

## TopologyDetailDrawer.vue — 节点详情抽屉

点击节点时从右侧滑出，显示设备完整信息：

```vue
<template>
  <el-drawer v-model="visible" title="设备详情" size="320px">
    <div v-if="node" class="detail-content">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="设备名称">{{ node.label }}</el-descriptions-item>
        <el-descriptions-item label="IP 地址">{{ node.ip }}</el-descriptions-item>
        <el-descriptions-item label="设备类型">{{ deviceTypeLabel }}</el-descriptions-item>
        <el-descriptions-item label="网络层级">{{ layerLabel }}</el-descriptions-item>
        <el-descriptions-item label="所属安全域">{{ node.zoneName || '未分组' }}</el-descriptions-item>
      </el-descriptions>

      <!-- 安全建议（可选，从 topology_summary 中提取相关内容） -->
      <div v-if="node.suggestion" class="suggestion">
        <h5>安全建议</h5>
        <p>{{ node.suggestion }}</p>
      </div>
    </div>
  </el-drawer>
</template>
```

## AssessmentWorkbench.vue — 集成拓扑图

在现有 AssessmentWorkbench.vue 中集成 TopologyPanel：

```vue
<template>
  <div class="assessment-workbench">
    <!-- 左侧：控制点列表 -->
    <div class="left-panel">...</div>

    <!-- 中间：对话 + 拓扑图 -->
    <div class="center-panel">
      <!-- 拓扑图面板（有数据时显示） -->
      <TopologyPanel
        :topology-data="currentTopology"
        v-if="currentTopology"
      />
      <!-- 对话区 -->
      <div class="chat-area">...</div>
    </div>

    <!-- 右侧：详情/复核面板 -->
    <div class="right-panel">...</div>
  </div>
</template>

<script setup>
import TopologyPanel from '@/components/topology/TopologyPanel.vue'

// 当 SSE 收到 topology_data 事件时更新
const currentTopology = ref(null)

// 在 useSessionStreamSender 中监听 topology 事件
watch(() => streamSender.topologyData, (data) => {
  currentTopology.value = data
})
</script>
```

## SSE 事件扩展

在 `streamChat.ts` 的事件类型中新增 `type=topology`：

```typescript
// 新增事件类型
case 'topology':
  // payload 含 topology_data（nodes + edges + security_zones + summary）
  onTopology?.(payload.topology_data)
  break
```

后端在 `topology_node` 执行完成后，通过 SSE 推送 `type=topology` 事件：

```python
# routers 中
yield sse_event("topology", {
    "topology_data": {
        "nodes": result["nodes"],
        "edges": result["edges"],
        "security_zones": result["security_zones"],
        "summary": result["summary"]
    }
})
```

## 验证标准

1. 用户上传资产核查表，Agent 生成拓扑数据后，前端自动切换到「网络拓扑图」标签页；
2. 节点按设备类型显示不同图标和边框颜色（交换机蓝 / 防火墙红 / 服务器绿 / 数据库紫）；
3. 节点按层级分层布局（core 在顶部 / boundary 中间 / access 底部）；
4. 连线带标签（如"千兆"），有动画效果；
5. 安全域用虚线框包围，显示域名称；
6. 点击节点弹出详情抽屉，显示设备完整信息；
7. 「导出 PNG」按钮可将拓扑图导出为图片；
8. 「重置布局」按钮恢复初始分层布局；
9. 鼠标滚轮缩放、拖拽平移正常工作；
10. 底部显示 Agent 生成的拓扑分析文字。

## 约束

- Vue Flow 版本 1.x，Node 20+ 构建；
- 不引入 D3 等额外图表库，布局用手动坐标计算（按 layer 分层 + 同层均匀分布）；
- 节点图标用内联 SVG，不依赖外部图标库（避免打包体积过大）；
- 安全域分组用 SVG overlay 绘制，不用 Vue Flow 内置 grouping（避免节点拖拽时分组错位）；
- 导出 PNG 用 `html-to-image` 库，不依赖 canvas 手动截图；
- 拓扑图面板高度固定 500px，不随节点数量变化（内部可滚动缩放）。
