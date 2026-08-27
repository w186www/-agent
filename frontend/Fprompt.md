# 实现前端登录功能：

1. 引入 axios 并二次封装 axios（请求头带 token，401 自动刷新并重试，失败清理 token 并跳登录）。
2. 统一错误提示：全局捕获 axios 错误信息；
3. 调用接口文档中的登录注册接口，处理登录和注册逻辑。
4. 路由前置守卫拦截未登录：在路由守卫中检查 token，未登录则跳转到登录页。
5. 登录成功后，保存 token 到 localStorage。
6. 头部按钮支持退出登录：添加退出登录按钮，点击后清理 token 并跳转到登录页。

# 实现聊天页面会话管理，对话数据回显：

- 会话管理：支持会话列表分页（`GET /sessions`，按 `role_type` 筛选商务/技术）、新建（`POST /sessions`，需传 `role_type` 和 `intent_type`）、编辑标题（`PUT /sessions/{session_id}`）、删除（`DELETE /sessions/{id}`，操作后刷新并切换会话）。
- 聊天信息：按会话ID分页获取消息（`GET /sessions/{session_id}/messages`），按 `role` 渲染（0=user 用户消息，1=assistant AI 消息），正文渲染 `content`，工具调用渲染 `tool_calls`（展开显示工具名、参数、结果、耗时），文件上下文渲染 `file_extracted_text`（折叠显示，点击展开）。
- 消息区：正文与工具调用分区显示，工具调用用独立组件（如 `MsgToolCalls.vue`），展示工具名、参数 JSON、返回结果摘要、耗时；`file_extracted_text` 非空时显示文件标识（如 `📎 资产核查表.xlsx`），点击展开提取的文本内容；AI 消息流式输出时显示打字动画。
- 消息加载：上拉分页（距离顶部100px触发），loading锁防重入，增量追加，按 `created_at` 排序。
- 任务卡片：根据会话 `intent_type` 显示不同卡片：
  - `intent_type=1`（招投标）：显示招投标进度卡片，展示 `bidding_tasks.status` 对应的流程阶段（搜索中→已解析→编写中→废标检查中→待人工审核→已完成），点击调用 `GET /bidding_tasks/{task_id}`，弹窗展示 `bidding_sections`（各部分投标内容）和 `compliance_result`（废标检查结果，pass/warning/danger 三色标注）。
  - `intent_type=2`（测评核查）：显示测评核查进度卡片，展示 `assessment_records` 列表中各控制点的 `status`（待测评→待核查→核查中→自动通过→待人工复核→已确认），点击某控制点调用 `GET /assessment_records/{record_id}`，弹窗展示 `vlm_analysis`（VLM 识别结果）、`human_record`（人工记录）、`comparison_result`（比对结果）和 `confidence`（置信度进度条）。
  - `intent_type=0` 或 `3`（对话/知识问答）：不显示任务卡片。

全部需对接接口如下：

- `GET /sessions`
- `POST /sessions`
- `PUT /sessions/{session_id}`
- `DELETE /sessions/{id}`
- `GET /sessions/{session_id}/messages`
- `GET /bidding_tasks/{task_id}`
- `GET /assessment_records?session_id={session_id}`
- `GET /assessment_records/{record_id}`



# 请按"API层 + 复用逻辑层 + 页面层"实现 Vue 流式聊天：

目标：

- 使用 fetch 发送请求
- 收到实时数据流拼接文本

架构要求：

1. API层（streamChat.ts）：只负责请求与SSE解析
2. 复用逻辑层（useSessionStreamSender.ts）
3. 页面层（BiddingWorkbench.vue、AssessmentWorkbench.vue）：只处理会话UI与占位消息

## API层（streamChat.ts）

- `streamChat(params, onMessage, onError, onClose)`：使用 fetch 发送 POST 请求到 `/api/chat/stream`，body 包含 `session_id`、`content`、`role`、`intent_type`；
- 手动解析 SSE 流（`ReadableStream` + `TextDecoder`），按 `data: ` 前缀逐行解析；
- 事件类型约定：
    - `type=token`：流式文本片段，`content` 字段为增量文本，调用 `onMessage(content)` 拼接；
    - `type=tool_call`：Agent 工具调用事件，`payload` 含 `tool_name`/`arguments`/`result`/`duration_ms`，前端渲染工具调用卡片；
    - `type=task_created`：任务创建事件，`payload` 含 `intent_type`（1=招投标/2=测评核查）和 `task_id`，前端据此渲染对应任务卡片；
    - `type=hitl`：Human-in-the-loop 触发事件，`payload` 含 `task_type`（0=报价审核/1=低置信度复核）、`source_type`、`source_id`、`review_data`，前端弹出审核工作台；
    - `type=done`：流结束，调用 `onClose()`；
    - `type=error`：错误事件，`payload.message` 为错误信息，调用 `onError(message)`；
- API 层不做任何 UI 状态管理，只解析流并回调。

## 复用逻辑层（useSessionStreamSender.ts）

- Composable，封装流式发送 + 消息状态管理的通用逻辑，供商务和技术页面复用；
- `messages`：响应式消息列表，每条消息结构为 `{ id, role, content, tool_calls, file_extracted_text, isStreaming, taskId, intentType }`；
- `sendMessage(content, session)`：创建占位 AI 消息（`isStreaming=true`，`content=''`），调用 `streamChat` 发送请求，在 `onMessage` 回调中追加 `content`，在 `onToolCall` 回调中更新 `tool_calls`，流结束后 `isStreaming=false`；
- `currentTask`：响应式，存当前会话的任务信息（`intentType` + `taskId`），由 `task_created` 事件写入，供页面层渲染任务卡片；
- `hitlQueue`：响应式数组，存触发的待审核任务列表，由 `hitl` 事件写入，供页面层渲染审核入口；
- `isSending`：响应式锁，防止用户连续发送；
- `abort()`：调用 `AbortController.abort()` 中断当前流式请求；
- 复用逻辑层不关心是招投标还是测评核查，通用逻辑与业务无关。

## 页面层

### BiddingWorkbench.vue（商务 - 招投标工作台）

- 引入 `useSessionStreamSender`，传入 `intent_type=1`；
- 左侧渲染招投标步骤进度条（7 步：搜索中→已解析→编写中→废标检查中→待人工审核→已完成→异常终止），步骤状态由 `currentTask` 中的 `bidding_tasks.status` 驱动；
- 中间为对话区，流式渲染 AI 消息，`tool_calls` 展示为工具调用卡片（工具名+参数+结果摘要+耗时）；
- `type=hitl` 且 `task_type=0`（报价审核）时，右侧渲染报价审核面板，展示 `review_data.pricing_section` 和 `ai_suggestion`，提供「通过」「驳回」「修改后通过」按钮，点击后 POST `/api/review/{review_task_id}` 恢复 Agent 流程；
- 占位消息：发送后立即显示用户消息 + AI 空消息占位（带打字动画），流式拼接 `content`。

### AssessmentWorkbench.vue（技术 - 测评核查工作台）

- 引入 `useSessionStreamSender`，传入 `intent_type=2`；
- 左侧渲染测评控制点列表（`checklist_code` + `checklist_name`），每个控制点显示 `status` 图标（待测评/核查中/自动通过/待人工复核/已确认）和 `confidence` 进度条；
- 中间为对话区，流式渲染 AI 消息，`tool_calls` 中 `analyze_screenshot` 的调用结果展示为截图分析卡片（识别文本 + 检测项列表）；
- `type=hitl` 且 `task_type=1`（低置信度复核）时，右侧渲染复核面板，展示 AI 结果与人工记录的差异对比（`comparison_result`）+ 置信度进度条 + KB 参考说明，提供「通过」「驳回」按钮，点击后 POST `/api/review/{review_task_id}` 恢复 Agent 流程；
- 截图上传区：拖拽上传截图，`upload_purpose=3`，上传成功后自动将 `screenshot_path` 关联到当前控制点的 `assessment_records`；
- 占位消息：发送后立即显示用户消息 + AI 空消息占位（带打字动画），流式拼接 `content`。