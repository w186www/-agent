# 请在现有项目基础上实现技术线核心流程：（A）测评清单生成工具——根据等保级别生成控制点清单和对应测评命令；（B）VLM 截图分析工具——用 Qwen-VL 识别测评截图内容；（C）比对与置信度判断——AI 结果与人工记录比对，低于阈值触发人工复核。本步是技术线的主干，不涉及 HITL（下一步加）。

## 目标

技术用户说"开始 XX 系统等保三级测评"时，Agent 自主执行：
1. 调用 `generate_checklist` 工具，根据等保级别（三级）生成控制点清单，每个控制点含编号、名称、测评命令
2. 将清单写入 `assessment_records` 表（每个控制点一条记录，status=0 待测评）
3. 组员按命令执行测评并截图上传，Agent 调用 `analyze_screenshot` 工具用 Qwen-VL 识别截图
4. Agent 调用 `compare_records` 工具，将 VLM 识别结果与组员填写的人工记录比对
5. 置信度 >= 0.80 自动通过（status=3），< 0.80 标记待人工复核（status=4）

## A. generate_checklist 工具

### tools.py — 新增 generate_checklist

```python
@tool
def generate_checklist(system_level: str, system_name: str = "") -> str:
    """根据等保级别生成测评控制点清单和对应测评命令。
    system_level: 等保级别，如"二级"/"三级"/"四级"
    system_name: 被测系统名称（可选，用于个性化命令）
    返回结构化 JSON，包含控制点列表
    """
```

#### 实现要点

1. 调用 `get_deepseek()` 生成控制点清单，Prompt 约束：
   - 依据 GB/T 22239-2019 标准生成对应级别的控制点
   - 每个控制点包含：`checklist_code`（编号如 `8.1.4.1`）、`checklist_name`（名称如 `身份鉴别`）、`assessment_command`（测评命令）
   - 测评命令区分操作系统：Windows 用 `net accounts` / `secedit /export` 等，Linux 用 `cat /etc/login.defs` / `cat /etc/pam.d/system-auth` 等
   - 覆盖技术要求五大类：物理安全、网络安全、主机安全、应用安全、数据安全
2. 返回 JSON 字符串：

```json
{
    "system_level": "三级",
    "system_name": "XX业务系统",
    "checklist": [
        {
            "checklist_code": "8.1.4.1",
            "checklist_name": "身份鉴别",
            "category": "主机安全",
            "assessment_command": "Windows: net accounts\nLinux: cat /etc/login.defs | grep PASS",
            "description": "检查操作系统身份鉴别机制配置情况"
        },
        {
            "checklist_code": "8.1.3.1",
            "checklist_name": "访问控制",
            "category": "主机安全",
            "assessment_command": "Windows: icacls C:\\\nLinux: ls -la /etc/passwd",
            "description": "检查文件系统访问控制配置"
        }
    ],
    "total_count": 35
}
```

3. 异常处理：LLM 生成失败返回 `{"error": "...", "detail": "..."}`；
4. 加日志：记录等保级别、控制点数量、耗时。

### prompt_layer.py — 新增测评清单 Prompt

```python
def get_checklist_generation_prompt() -> str:
    """测评清单生成 Prompt。约束：
    - 依据 GB/T 22239-2019 标准生成
    - 每个控制点必须有可执行的测评命令
    - Windows 和 Linux 命令都给出
    - 覆盖五大技术要求类别
    """
```

### graph.py — 新建技术线状态机

#### 1. TechnicalAgentState

```python
class TechnicalAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    system_level: int          # 0=二级, 1=三级, 2=四级
    system_name: str           # 被测系统名称
    checklist_generated: bool  # 清单是否已生成
    current_record_id: int     # 当前正在处理的 assessment_record_id
    screenshot_analyzed: bool  # 截图是否已分析
    comparison_done: bool      # 比对是否完成
    confidence: float          # 置信度
    need_human: bool           # 是否需要人工复核
```

#### 2. 节点定义

```python
def agent_node(state: TechnicalAgentState):
    """技术线 LLM 节点。绑定工具：generate_checklist, analyze_screenshot, compare_records"""
    model = get_deepseek().bind_tools([generate_checklist, analyze_screenshot, compare_records])
    system_prompt = get_assessment_prompt()
    messages = [SystemMessage(system_prompt)] + state["messages"]
    response = model.invoke(messages)
    return {"messages": [response]}

def checklist_node(state: TechnicalAgentState):
    """清单生成后处理：写入 assessment_records 表。"""
    # 从 messages 中提取 generate_checklist 的结果
    # 为每个控制点创建 assessment_records 记录（status=0 待测评）
    # 返回 checklist_generated=True

def screenshot_node(state: TechnicalAgentState):
    """VLM 截图分析节点。"""
    # 从 state 获取 screenshot_path 和 checklist_item
    # 调用 analyze_screenshot 工具
    # 更新 assessment_records.vlm_analysis

def compare_node(state: TechnicalAgentState):
    """比对节点。VLM 结果 vs 人工记录。"""
    # 调用 compare_records 工具
    # 更新 assessment_records.comparison_result + confidence
    # 根据 confidence 设置 status:
    #   >= 0.80 → status=3 (自动通过)
    #   < 0.80  → status=4 (待人工复核)

def should_continue(state: TechnicalAgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "__end__"
```

#### 3. build_assessment_graph()

```python
def build_assessment_graph():
    graph = StateGraph(TechnicalAgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode([generate_checklist, analyze_screenshot, compare_records]))
    graph.add_node("checklist", checklist_node)
    graph.add_node("screenshot", screenshot_node)
    graph.add_node("compare", compare_node)
    
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    
    return graph.compile(checkpointer=MemorySaver())
```

### routers — 技术线调用入口

对话路由中，当 `intent_type=2`（测评核查）时：

```python
graph = build_assessment_graph()
messages = memory.buffer_as_messages + [HumanMessage(content=user_input)]
result = await graph.ainvoke(
    {"messages": messages, "system_level": session.system_level},
    config={"configurable": {"thread_id": request_id}}
)
```

SSE 推送逻辑与商务线一致（`on_chat_model_stream` → token，`on_tool_start/end` → tool_call）。

新增 `type=task_created` 事件推送：清单生成后推送 `task_type=assessment`，含 `assessment_records` 列表。

## B. analyze_screenshot 工具

### tools.py — 新增 analyze_screenshot

```python
@tool
def analyze_screenshot(image_path: str, checklist_item: str) -> str:
    """用 VLM 分析测评截图，识别与测评控制点相关的配置信息。
    image_path: 截图文件路径
    checklist_item: 测评控制点名称，如"身份鉴别"
    返回 VLM 分析结果 JSON
    """
```

#### 实现要点

1. 调用 `get_qwen_vl()` 获取多模态模型实例；
2. 使用 `get_vlm_prompt(checklist_item)` 构建 Prompt，要求识别截图中与该控制点相关的配置信息；
3. 将截图作为 image 输入给 Qwen-VL：

```python
from langchain_core.messages import HumanMessage

model = get_qwen_vl()
message = HumanMessage(
    content=[
        {"type": "text", "text": get_vlm_prompt(checklist_item)},
        {"type": "image_url", "image_url": {"url": f"file://{image_path}"}},
    ]
)
response = model.invoke([message])
```

4. 解析 VLM 返回，结构化为：

```json
{
    "recognized_text": "Password minimum length: 8\nPassword complexity: enabled",
    "detected_items": ["密码策略已启用", "最小长度8位", "复杂度要求开启"],
    "raw_response": "VLM 原始返回内容..."
}
```

5. 异常处理：图片不存在 / VLM 调用失败返回 `{"error": "...", "detail": "..."}`；
6. 加日志：记录图片路径、控制点名称、识别项数、耗时。

### llm.py — 确认 get_qwen_vl()

```python
def get_qwen_vl():
    """返回 Qwen-VL 多模态模型实例。"""
    from langchain_community.chat_models import ChatTongyi
    return ChatTongyi(
        model="qwen-vl-max",
        dashscope_api_key=settings.DASHSCOPE_API_KEY
    )
```

## C. compare_records 工具

### tools.py — 新增 compare_records

```python
@tool
def compare_records(vlm_result: str, human_record: str, checklist_code: str) -> str:
    """比对 VLM 分析结果与人工记录，判断一致性并计算置信度。
    vlm_result: analyze_screenshot 返回的 JSON 字符串
    human_record: 组员人工填写的结果记录
    checklist_code: 测评控制点编号
    返回比对结果 JSON，含 consistent, ai_result, human_result, diff_detail, confidence
    """
```

#### 实现要点

1. 调用 `get_deepseek()` 做比对判断：
   - 解析 `vlm_result` 中的 `detected_items` 和 `recognized_text`
   - 与 `human_record` 逐项对比
   - 判断是否一致（`consistent: true/false`）
   - 计算置信度（0.0~1.0）：
     - 完全一致 → 0.90~1.00
     - 部分一致 → 0.60~0.89
     | 完全不一致 → 0.00~0.59
2. 同时从 Qdrant 企业本地库（kb_type=1）检索特殊情况说明，作为置信度调整依据：

```python
def compare_records(vlm_result, human_record, checklist_code):
    # 1. LLM 比对
    comparison = llm_compare(vlm_result, human_record)
    
    # 2. RAG 检索企业本地库特殊情况
    kb_refs = get_assessment_context(checklist_code)
    
    # 3. 如果有特殊情况说明，调整置信度
    if kb_refs and comparison["consistent"] == False:
        # 检查 kb_refs 是否解释了差异原因
        # 如果解释了（如"堡垒机统一管理"），提高置信度
        comparison["confidence"] = adjust_confidence(comparison, kb_refs)
        comparison["kb_references"] = kb_refs
    
    return comparison
```

3. 返回 JSON 字符串：

```json
{
    "consistent": false,
    "ai_result": "密码策略已配置（最小长度8位，复杂度开启）",
    "human_result": "密码策略未配置",
    "diff_detail": "截图显示已启用密码策略，人工记录为未配置",
    "confidence": 0.62,
    "kb_references": [
        {
            "doc_id": 5,
            "doc_title": "XX系统特殊配置说明",
            "matched_text": "该系统使用堡垒机统一管理密码策略，本地不显示...",
            "similarity": 0.87
        }
    ]
}
```

4. 异常处理：LLM 比对失败返回 `{"error": "...", "detail": "..."}`。

### prompt_layer.py — 新增比对 Prompt

```python
def get_comparison_prompt() -> str:
    """比对 Prompt。约束：
    - 逐项对比 VLM 识别结果和人工记录
    - 明确标注一致/不一致
    - 不一致时给出差异详情
    - 输出置信度（0.0~1.0）
    """
```

## memory.py — 实现 get_assessment_context

```python
def get_assessment_context(checklist_code: str, top_k: int = 3) -> list:
    """从 Qdrant 企业本地库检索特殊情况说明。
    
    返回：
    [
        {"doc_id": 5, "doc_title": "...", "matched_text": "...", "similarity": 0.87}
    ]
    """
    # 1. 调用 get_embeddings() 将 checklist_code + 控制点名称向量化
    # 2. 查询 Qdrant "enterprise_local" collection
    # 3. 按 similarity 排序取 top_k
    # 4. 返回结果列表
```

### Qdrant — 初始化企业本地库 collection

在 `qdrant_client.py` 的 `init_collections()` 中确认 `enterprise_local` collection 已创建（step4 中已初始化，本轮确认可用）。

### qdrant_client.py — 新增企业本地库灌入

```python
def ingest_enterprise_doc(doc_id: int, file_path: str, doc_title: str):
    """将企业本地文档向量化灌入 Qdrant enterprise_local collection。"""
    # 1. 读取文件，提取文本
    # 2. 按 chunk_size=500, overlap=50 切分
    # 3. 调用 get_embeddings() 批量向量化
    # 4. 写入 Qdrant "enterprise_local"，payload 含 doc_id, doc_title, chunk_text
    # 5. 更新 kb_documents.chunk_count 和 status=1
```

## 数据库 — 新增接口

1. `POST /assessment/generate_checklist`：触发清单生成
   - body: `{ "session_id": ..., "system_level": 0|1|2, "system_name": "..." }`
   - 为每个控制点创建 `assessment_records` 记录（status=0）
   - 返回控制点列表

2. `POST /assessment/{record_id}/upload_screenshot`：上传测评截图
   - 上传截图文件（upload_purpose=3）
   - 更新 `assessment_records.screenshot_path`
   - 触发 `analyze_screenshot` + `compare_records`

3. `PUT /assessment/{record_id}/human_record`：提交人工记录
   - body: `{ "human_record": "密码策略未配置..." }`
   - 更新 `assessment_records.human_record`
   - 若已有 VLM 分析结果，自动触发比对

4. `GET /assessment_records?session_id=`：已在 ref-backend-arch.md 中定义，本轮实现
5. `GET /assessment_records/{record_id}`：已在 ref-backend-arch.md 中定义，本轮实现

## 前端 — AssessmentWorkbench.vue 实现

### 左侧：控制点列表

1. 清单生成后，左侧渲染控制点列表（`checklist_code` + `checklist_name`）；
2. 每个控制点显示：
   - `status` 图标：待测评(灰) → 待核查(黄) → 核查中(蓝) → 自动通过(绿) → 待人工复核(橙) → 已确认(深绿)
   - `confidence` 进度条（有值时显示）
   - 测评命令（点击展开复制）
3. 点击控制点 → 右侧弹窗展示详情。

### 中间：对话区

1. 流式渲染 AI 消息；
2. `tool_calls` 中 `generate_checklist` 的结果渲染为清单卡片（控制点表格）；
3. `analyze_screenshot` 的结果渲染为截图分析卡片（截图缩略图 + 识别文本 + 检测项列表）；
4. `compare_records` 的结果渲染为比对卡片（AI 结果 vs 人工结果，差异高亮）。

### 截图上传区

1. 选择控制点后，底部出现截图上传区（拖拽上传）；
2. 上传时传 `upload_purpose=3` + `record_id`；
3. 上传成功后自动触发 VLM 分析（若已有人工记录则同时触发比对）。

### 人工记录输入

1. 每个控制点详情弹窗中，有「人工记录」文本框；
2. 组员填写后点击「提交」→ `PUT /assessment/{record_id}/human_record`；
3. 若已有 VLM 分析结果，提交后自动触发比对。

## config.py — 新增配置

1. `CONFIDENCE_THRESHOLD`：自动通过置信度阈值，默认 0.80
2. `VLM_MODEL`：VLM 模型名，默认 `"qwen-vl-max"`
3. `ASSESSMENT_MAX_CHECKLIST`：单次生成最大控制点数，默认 50

## requirements.txt — 新增依赖

```
dashscope==1.*
```
（Qwen-VL 通过 DashScope SDK 接入，langchain-community 已有 ChatTongyi 集成）

## 验证标准

### 测评清单生成

1. 用户说"开始 XX 系统等保三级测评"，Agent 调用 `generate_checklist` 生成控制点清单；
2. 清单覆盖五大技术要求类别（物理/网络/主机/应用/数据安全），每类至少 2 个控制点；
3. 每个控制点有 `checklist_code` + `checklist_name` + `assessment_command`；
4. `assessment_records` 表为每个控制点创建记录（status=0 待测评）；
5. SSE 流推送 `type=task_created` 事件，`task_type=assessment`，前端渲染控制点列表。

### VLM 截图分析

6. 组员上传截图（`upload_purpose=3`），Agent 调用 `analyze_screenshot`；
7. VLM 识别结果包含 `recognized_text` + `detected_items`；
8. `assessment_records.vlm_analysis` 写入分析结果，`status` 更新为 2（核查中）；
9. 识别失败时返回友好提示，不崩溃。

### 比对与置信度

10. 组员提交人工记录后，Agent 调用 `compare_records` 比对；
11. 比对结果包含 `consistent` + `ai_result` + `human_result` + `diff_detail` + `confidence`；
12. `confidence >= 0.80` → `status=3`（自动通过）；
13. `confidence < 0.80` → `status=4`（待人工复核）；
14. 比对时从 Qdrant 企业本地库检索特殊情况说明，写入 `assessment_records.kb_references`；
15. 有特殊情况说明时，置信度有调整（如堡垒机场景，差异被解释，置信度提升）。

### 前端交互

16. 左侧控制点列表正确显示 status 图标和 confidence 进度条；
17. 点击控制点弹窗展示测评命令、VLM 分析、人工记录、比对结果；
18. 截图上传后自动触发分析，前端显示分析进度。

## 约束

- 本轮不做 HITL 中断（低置信度复核），只标记 `status=4`，下一步（step8）加 HITL；
- 本轮不做网络拓扑图生成，下一步（step8）加；
- `generate_checklist` 作为 LLM 可调用工具（`bind_tools`），由 Agent 自主决定何时生成；
- `analyze_screenshot` 和 `compare_records` 作为固定图节点（不绑定到 `bind_tools`），由截图上传和人工记录提交触发；
- 企业本地库灌入只实现 `ingest_enterprise_doc`，等保标准库灌入下一轮再加；
- VLM 图片输入使用本地文件路径，不走 MinIO URL（MinIO URL 方式下一轮优化）。



# 请在现有技术线基础上实现两个增强：（A）网络拓扑图生成——Agent 读取资产核查表，生成节点与边数据，前端 Vue Flow 渲染；（B）低置信度 HITL 复核——confidence < 0.80 的测评记录触发人工复核，审核结果回写并恢复流程。本步完成后技术线全流程闭环。

## 目标

**网络拓扑图**：
1. 用户上传资产核查表（Excel/CSV），说"生成网络拓扑图"
2. Agent 调用 `generate_topology` 工具，解析资产表，用 LLM 生成节点和边数据
3. 数据写入 `topology_records`，前端用 Vue Flow 渲染交互式拓扑图
4. Agent 同时生成拓扑结构文字分析（安全域划分、边界设备识别等）

**低置信度 HITL**：
1. `compare_records` 比对后 `confidence < 0.80`，`assessment_records.status=4`（待人工复核）
2. 自动创建 `review_tasks` 记录（task_type=1 低置信度复核）
3. SSE 推送 `type=hitl` 事件，前端弹出复核面板
4. 审核人查看 AI 结果 vs 人工记录差异 + KB 参考说明，做出判断
5. 审核结果回写 `assessment_records` 和 `review_tasks`，恢复流程

## A. generate_topology 工具

### tools.py — 新增 generate_topology

```python
@tool
def generate_topology(asset_file_path: str, system_level: str = "三级") -> str:
    """根据资产核查表生成网络拓扑图数据。解析资产表中的设备信息，生成节点和边。
    asset_file_path: 资产核查表文件路径（Excel/CSV）
    system_level: 等保级别，影响安全域划分建议
    返回结构化 JSON，含 nodes/edges/summary
    """
```

#### 实现要点

1. 解析资产核查表：
   - `.xlsx` / `.xls`：用 `openpyxl` 读取
   - `.csv`：用 `csv` 模块读取
   - 提取设备信息：设备名称、IP 地址、设备类型（交换机/路由器/防火墙/服务器/数据库等）、所属区域
2. 将设备列表交给 DeepSeek 生成拓扑结构：
   - 识别设备层级（核心层/汇聚层/接入层）
   - 根据 IP 网段推断连接关系
   - 识别安全边界（防火墙位置）
   - 生成安全域划分建议
3. 返回 JSON 字符串：

```json
{
    "nodes": [
        {"id": "node-1", "label": "核心交换机", "type": "switch", "ip": "192.168.1.1", "layer": "core"},
        {"id": "node-2", "label": "防火墙", "type": "firewall", "ip": "192.168.1.2", "layer": "boundary"},
        {"id": "node-3", "label": "Web服务器", "type": "server", "ip": "192.168.1.10", "layer": "access"},
        {"id": "node-4", "label": "数据库服务器", "type": "database", "ip": "192.168.1.20", "layer": "access"}
    ],
    "edges": [
        {"id": "edge-1", "source": "node-1", "target": "node-2", "label": "千兆"},
        {"id": "edge-2", "source": "node-2", "target": "node-3", "label": "千兆"},
        {"id": "edge-3", "source": "node-2", "target": "node-4", "label": "千兆"}
    ],
    "summary": "该网络采用单核心架构，通过防火墙隔离 DMZ 区和内网区。Web 服务器位于 DMZ 区，数据库位于内网区。建议增加汇聚层冗余设计。",
    "security_zones": [
        {"zone_name": "DMZ区", "nodes": ["node-3"], "description": "对外服务区域"},
        {"zone_name": "内网区", "nodes": ["node-4"], "description": "核心数据区域"}
    ]
}
```

4. 异常处理：文件格式不支持 / 解析失败 / LLM 生成失败返回 `{"error": "...", "detail": "..."}`；
5. 加日志：记录文件路径、设备数量、节点数、边数、耗时。

### prompt_layer.py — 新增拓扑生成 Prompt

```python
def get_topology_prompt() -> str:
    """网络拓扑图生成 Prompt。约束：
    - 根据 IP 网段推断连接关系
    - 识别设备层级（核心/汇聚/接入/边界）
    - 标注安全边界设备（防火墙）
    - 生成安全域划分建议
    - 输出 nodes + edges + summary + security_zones
    """
```

### graph.py — 新增拓扑节点

```python
def topology_node(state: TechnicalAgentState):
    """拓扑图生成节点。"""
    # 1. 从 state 获取资产核查表路径
    # 2. 调用 generate_topology 工具
    # 3. 将结果写入 topology_records 表
    # 4. 推送 topology_data 给前端
    return {
        "messages": [AIMessage(content="网络拓扑图已生成，请在左侧查看...")],
        "topology_data": result
    }
```

### 数据库 — topology_records 写入

```python
# 在 topology_node 中
topology_record = TopologyRecord(
    session_id=session_id,
    user_id=user_id,
    asset_file_path=asset_path,
    topology_data=result["nodes_edges"],  # nodes + edges
    topology_summary=result["summary"],
    status=1  # 已完成
)
db.add(topology_record)
```

### 前端 — Vue Flow 拓扑图渲染

#### AssessmentWorkbench.vue 新增拓扑图区域

1. 当 `topology_records` 有数据时，对话区上方出现「网络拓扑图」标签页；
2. 使用 Vue Flow 渲染：
   - 节点按 `type` 显示不同图标（switch/firewall/server/database）
   - 节点按 `layer` 分层布局（core 在顶部，access 在底部）
   - 边显示连接标签
   - 安全域用虚线框分组
3. 节点可拖拽、可点击查看详情（IP、设备类型、所属区域）；
4. 右上角「导出」按钮，导出为 PNG。

```vue
<template>
  <div class="topology-panel" v-if="topologyData">
    <VueFlow :nodes="topologyNodes" :edges="topologyEdges">
      <Background />
      <Controls />
      <MiniMap />
    </VueFlow>
  </div>
</template>
```

#### 节点类型映射

| type | 图标 | 颜色 |
|------|------|------|
| switch | 交换机图标 | 蓝色 |
| router | 路由器图标 | 蓝色 |
| firewall | 防火墙图标 | 红色 |
| server | 服务器图标 | 绿色 |
| database | 数据库图标 | 紫色 |

### 数据库 — 新增接口

1. `POST /assessment/topology`：触发拓扑图生成
   - body: `{ "session_id": ..., "asset_file_path": "..." }`
   - 调用 `generate_topology`，写入 `topology_records`
   - 返回 `topology_data` + `topology_summary`

2. `GET /topology/{topology_id}`：获取拓扑图数据
   - 返回 `topology_data` + `topology_summary` + `status`

3. `GET /topology?session_id=`：获取会话下所有拓扑记录

## B. 低置信度 HITL 复核

### graph.py — 更新技术线状态机

#### 1. TechnicalAgentState 新增字段

```python
class TechnicalAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    system_level: int
    system_name: str
    checklist_generated: bool
    current_record_id: int
    screenshot_analyzed: bool
    comparison_done: bool
    confidence: float
    need_human: bool
    human_reviewed: bool      # 新增：人工是否已复核
    review_result: int        # 新增：复核结果 0=通过 1=驳回
```

#### 2. 新增 review_node

```python
def review_node(state: TechnicalAgentState):
    """低置信度复核节点。中断点占位。"""
    return state
```

#### 3. 更新 compare_node

```python
def compare_node(state: TechnicalAgentState):
    # ... 比对逻辑 ...
    confidence = comparison["confidence"]
    
    if confidence >= settings.CONFIDENCE_THRESHOLD:
        # 自动通过
        update_assessment_record(record_id, status=3, confidence=confidence)
        return {"comparison_done": True, "confidence": confidence, "need_human": False}
    else:
        # 需要人工复核
        update_assessment_record(record_id, status=4, confidence=confidence)
        # 创建 review_tasks 记录
        create_review_task(
            session_id=session_id,
            user_id=user_id,
            task_type=1,  # 低置信度复核
            source_type=1,  # 测评核查记录
            source_id=record_id,
            review_data={
                "assessment_record_id": record_id,
                "checklist_code": checklist_code,
                "checklist_name": checklist_name,
                "ai_result": comparison["ai_result"],
                "human_result": comparison["human_result"],
                "confidence": confidence,
                "kb_references": comparison.get("kb_references", []),
                "reason": f"AI 与人工记录不一致，置信度 {confidence} 低于阈值 {settings.CONFIDENCE_THRESHOLD}"
            }
        )
        return {
            "comparison_done": True,
            "confidence": confidence,
            "need_human": True
        }
```

#### 4. 更新条件路由

```python
def should_continue(state: TechnicalAgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    # 比对完成后，检查是否需要人工复核
    if state.get("comparison_done") and state.get("need_human") and not state.get("human_reviewed"):
        return "review"  # 进入 HITL 中断
    return "__end__"

def should_continue_after_review(state: TechnicalAgentState) -> str:
    if state.get("human_reviewed"):
        return "__end__"
    return "compare"  # 驳回 → 重新比对（如人工修改了记录）
```

#### 5. 更新 build_assessment_graph()

```python
def build_assessment_graph():
    graph = StateGraph(TechnicalAgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("checklist", checklist_node)
    graph.add_node("screenshot", screenshot_node)
    graph.add_node("compare", compare_node)
    graph.add_node("review", review_node)          # 新增
    graph.add_node("topology", topology_node)      # 新增
    
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    graph.add_edge("compare", "review")            # 比对完进入审核
    graph.add_conditional_edges("review", should_continue_after_review)
    
    return graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["review"]  # 低置信度 HITL 中断点
    )
```

### routers — HITL 恢复接口

技术线复用 `POST /chat/{thread_id}/resume`，支持 `review_type=assessment_review`：

```python
@router.post("/chat/{thread_id}/resume")
async def resume_chat(thread_id: str, body: ResumeRequest):
    graph = build_assessment_graph()
    
    if body.review_type == "assessment_review":
        # 低置信度复核
        update = {
            "human_reviewed": True,
            "review_result": body.review_result  # 0=通过, 1=驳回
        }
        result = await graph.ainvoke(
            Command(resume=update),
            config={"configurable": {"thread_id": thread_id}}
        )
    # ... 其他 review_type ...
```

### SSE 推送 hitl 事件

```python
# compare_node 中 need_human=True 时推送
yield sse_event("hitl", {
    "task_type": "assessment_review",
    "thread_id": thread_id,
    "review_data": {
        "assessment_record_id": record_id,
        "checklist_code": checklist_code,
        "checklist_name": checklist_name,
        "ai_result": comparison["ai_result"],
        "human_result": comparison["human_result"],
        "confidence": confidence,
        "kb_references": comparison.get("kb_references", []),
        "diff_detail": comparison["diff_detail"],
        "reason": f"置信度 {confidence} 低于阈值"
    }
})
```

### 审核结果回写

```python
# POST /review/{review_task_id} 中
if task_type == 1:  # 低置信度复核
    record = get_assessment_record(source_id)
    
    if review_result == 0:  # 通过
        record.status = 5  # 已确认
    elif review_result == 1:  # 驳回
        record.status = 4  # 保持待复核，等组员修改记录
        # 驳回后组员修改人工记录，重新提交触发比对
    
    record.comparison_result["human_review"] = {
        "result": review_result,
        "comment": review_comment,
        "reviewer_id": reviewer_id
    }
```

### 前端 — AssessmentWorkbench.vue 复核面板

- `type=hitl` 且 `task_type=assessment_review` 时，右侧渲染复核面板：
  - 上半区：AI 结果 vs 人工记录差异对比（`comparison_result`），差异处高亮
  - 中间区：KB 参考说明（`kb_references`），展示企业本地库的特殊情况解释
  - 下方：置信度进度条，标注阈值线（0.80）
  - 底部按钮：「确认通过」「驳回（组员修改）」
- 「确认通过」→ POST `/review/{id}` `{ review_result: 0 }`，`assessment_records.status` 更新为 5
- 「驳回」→ POST `/review/{id}` `{ review_result: 1 }`，状态保持 4，通知组员修改记录

### ReviewWorkbench.vue — 低置信度复核列表

在审核工作台的待审核列表中，`task_type=1` 的项显示：
- 控制点编号 + 名称
- AI 结果摘要 vs 人工记录摘要
- 置信度（红色标注低于阈值）
- 点击进入复核面板

## C. 等保标准库灌入

### qdrant_client.py — 新增标准库灌入

```python
def ingest_standard_doc(doc_id: int, file_path: str, doc_title: str, doc_source: str):
    """将等保标准文档向量化灌入 Qdrant assessment_standard collection。"""
    # 1. 读取文件（GB/T 22239 等 PDF）
    # 2. 按 chunk_size=500, overlap=50 切分
    # 3. 调用 get_embeddings() 批量向量化
    # 4. 写入 Qdrant "assessment_standard"，payload 含 doc_id, doc_title, doc_source, chunk_text
    # 5. 更新 kb_documents.chunk_count 和 status=1
```

### memory.py — 更新 get_assessment_context

```python
def get_assessment_context(checklist_code: str, top_k: int = 5) -> dict:
    """双路 RAG 检索：等保标准库 + 企业本地库。"""
    # 1. 并行查询两个 collection
    standard_results = query_qdrant("assessment_standard", checklist_code, top_k=2)
    enterprise_results = query_qdrant("enterprise_local", checklist_code, top_k=3)
    
    # 2. 合并结果
    return {
        "standard": standard_results,    # 控制点标准要求
        "enterprise": enterprise_results  # 特殊情况说明
    }
```

### 数据库 — 知识库管理接口

1. `POST /kb/upload`：统一知识库上传接口（step4 中已定义，本轮扩展支持 kb_type=0 和 kb_type=1）
   - `kb_type=0`：等保标准库，调用 `ingest_standard_doc()`
   - `kb_type=1`：企业本地库，调用 `ingest_enterprise_doc()`
   - `kb_type=2`：历史标书库，调用 `ingest_bidding_doc()`（step4 已实现）

2. `GET /kb/documents?kb_type=`：查看知识库文档列表（step4 已定义）

## config.py — 新增配置

1. `TOPOLOGY_MAX_NODES`：拓扑图最大节点数，默认 50
2. `ASSET_SUPPORTED_FORMATS`：资产核查表支持格式，默认 `["xlsx", "xls", "csv"]`

## requirements.txt — 新增依赖

```
openpyxl==3.*
@vue-flow/core==1.*    # 前端 Vue Flow
```

## 验证标准

### 网络拓扑图

1. 用户上传资产核查表（Excel），说"生成网络拓扑图"，Agent 调用 `generate_topology`；
2. 生成的 `topology_data` 包含 nodes + edges + summary + security_zones；
3. `topology_records` 表写入记录，`status=1`（已完成）；
4. 前端 Vue Flow 正确渲染拓扑图，节点按类型显示不同图标，按层级布局；
5. 安全域用虚线框分组显示；
6. Agent 返回拓扑结构文字分析（安全域划分、边界设备识别、改进建议）；
7. 资产表格式不支持时返回友好提示。

### 低置信度 HITL

8. `compare_records` 比对后 `confidence < 0.80`，`assessment_records.status` 更新为 4；
9. 自动创建 `review_tasks` 记录（task_type=1, source_type=1）；
10. SSE 推送 `type=hitl` 事件，`task_type=assessment_review`；
11. 前端渲染复核面板，展示 AI vs 人工差异 + KB 参考 + 置信度；
12. 审核人点击「通过」→ `assessment_records.status` 更新为 5（已确认），`review_tasks.status` 更新为 1；
13. 审核人点击「驳回」→ `assessment_records.status` 保持 4，通知组员修改记录；
14. 驳回后组员修改人工记录重新提交，重新触发比对。

### 等保标准库

15. `POST /kb/upload` 上传 GB/T 22239 PDF（kb_type=0），`kb_documents` 创建记录，`status` 变为 1；
16. Qdrant `assessment_standard` collection 中可查到向量数据；
17. `get_assessment_context` 能同时检索标准库和企业本地库。

### 全流程闭环

18. 完整流程：用户说"开始测评" → 生成清单 → 组员按命令测评并截图 → VLM 分析 → 比对 → 置信度判断 → 自动通过或 HITL 复核 → 确认完成；
19. `assessment_records` 状态流转正确：0(待测评) → 1(待核查) → 2(核查中) → 3(自动通过) 或 4(待人工复核) → 5(已确认)；
20. 前端控制点列表实时更新 status 图标和 confidence 进度条。

## 约束

- 本轮完成后技术线全流程闭环，商务线 + 技术线均可用；
- 拓扑图只支持 Excel/CSV 格式资产表，不支持其他格式；
- Vue Flow 渲染在前端完成，后端只返回 nodes + edges JSON 数据；
- 低置信度 HITL 复核为技术线唯一的中断点，不做多个中断点；
- 驳回后重新比对只更新 `comparison_result` 和 `confidence`，不重新调用 VLM 分析（VLM 结果不变，只重新比对）；
- 等保标准库灌入是手动上传，不做自动爬取 GB/T 22239 文档。