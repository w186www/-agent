# 根据{{FastAPI}}初始化项目代码，要求如下：

1. 需要创建虚拟环境并激活，安装相关依赖；
2. 按路由层、校验层、业务层、数据库层四层组织代码；
3. 数据库层仅用内存字典模拟，不连接真实数据库；
4. 实现用户信息增删改查接口，用户包含{{id}}、{{username}}、{{password}}字段；
5. 密码使用{{passlib[bcrypt]}}做哈希加密，存储时不保留明文；
6. 复用{{Pydantic（v2）}}做请求/响应参数校验；
7. 代码简洁高效,并合理添加注释；




## 生成{{FastAPI}}统一错误处理代码

### 核心目标

报错前端中文可读、后端可定位

### 关键要求

1. 自定义业务/系统两类异常类
2. 标准化响应模型（含code/message/detail）
3. 注册全局异常处理器
4. 在用户信息接口中加上错误处理功能

### 实现步骤

自定义异常→响应模型→日志配置→全局处理器→业务示例






# 用FastAPI + SQLAlchemy 2.0 + MySQL 实现用户信息数据建模：

1. 定义 User 表（id 自增主键、username 添加唯一索引、password、create_time 自动填充当前时间）
2. 配置 MySQL 连接串 {{mysql_url}};
3. 集成 Alembic 管理表结构变更，支持修改表结构后一键同步到数据库



# 实现环境变量分层管理和日志体系

1. 环境变量分层：支持开发/生产。
2. 敏感信息只走环境变量/配置层，不写死在业务代码。
3. 建立日志体系：日志文件用于留痕与排障，避免多余日志。
4. 最后补齐忽略规则




# 在项目里完善稳定性保障：实现健康检查接口，并补齐基础冒烟测试。

要求：

1.  健康检查：实现 `/health` 接口，校验服务存活及数据库连通性，异常返回503。
2.  冒烟测试：用 `pytest` + `httpx` 编写用户接口测试用例。
3.  交付：说明改动文件及运行测试命令（`pytest tests/test_smoke.py -v`）。


# 安全实现注册接口，保持代码简洁：

1. 注册接口：新增 /auth/register，复用 UserService.create_user
2. 密码加密：bcrypt 哈希，禁止明文入库
3. 弱密码校验：黑名单 + 必须字母+数字 + 禁止包含用户名
4. 接口限流：固定窗口 + IP 维度，注册 5/min


## 实现登录接口：

- JWT鉴权全流程，包括：
    - 登录时使用PyJWT生成访问令牌（Access Token）和刷新令牌（Refresh Token）。
    - 使用鉴权保护接口，验证请求的合法性。
    - 当访问令牌过期时，自动使用刷新令牌获取新的访问令牌，并重试原请求，无需用户手动操作。
- token 密钥必须通过环境变量进行安全存储。

# 创建一个 需认证 的通用文件上传接口。该接口需 自动判断 文件类型：

- 如果是图片 ，则保存文件并 更新 用户数据库中的 avatar 字段。
- 如果是文档 ，则 只保存 文件。
- 存储逻辑 ：文件保存在按用户 ID 划分的目录中，并使用文件内容的 MD5 哈希值作为文件名以实现去重。
- 文件上传依赖: python-multipart==0.0.9

# 请使用 SQLAlchemy 2.0 语法，根据以下信息创建八个 ORM 模型：

1. 用户表 (users)

- id：主键，自增
- username：字符串(64)，非空，唯一；登录用户名
- password_hash：字符串(255)，非空；bcrypt 哈希密码
- role：整数，非空，默认 0，索引（0=商务，1=技术）
- display_name：字符串(64)，非空；显示名称
- email：字符串(128)，可空；邮箱
- phone：字符串(20)，可空；手机号
- status：整数，非空，默认 1（0=禁用，1=正常）
- created_at：Unix 秒时间戳，非空，默认 `UNIX_TIMESTAMP()`
- updated_at：Unix 秒时间戳，非空，默认 `UNIX_TIMESTAMP()`

2. 会话表 (sessions)

- id：主键，自增
- user_id：外键（关联 users.id），索引
- role_type：整数，非空（注释：0=商务，1=技术）
- intent_type：整数，非空（注释：0=对话助手，1=招投标，2=测评核查，3=知识问答）
- title：字符串(255)，非空
- created_at：Unix 秒时间戳，非空，默认 `UNIX_TIMESTAMP()`（会话创建时间）
- updated_at：Unix 秒时间戳，非空，默认 `UNIX_TIMESTAMP()`（会话更新时间）

3. 消息表 (chat_messages)

- id：主键，自增
- user_id：外键（关联 users.id）
- session_id：外键（关联 sessions.id）
- role：整数，非空（注释：0=user，1=assistant）
- request_id：字符串(64)，非空，索引
- content：MEDIUMTEXT，非空
- tool_calls：JSON，可空；Agent 工具调用记录，字段约定见下方示例
- file_extracted_text：MEDIUMTEXT，可空；从文件中提取的完整文本(对话上下文用)
- created_at：Unix 秒时间戳，非空
- 要求：在 session_id 与 created_at 上创建复合索引

`tool_calls` 示例：

```json
[
    {
        "tool_name": "search_tender",
        "arguments": {"keyword": "等保三级 招标"},
        "result": "搜索结果摘要...",
        "duration_ms": 1200
    },
    {
        "tool_name": "analyze_screenshot",
        "arguments": {"image_path": "/uploads/screenshot_001.png", "checklist_item": "身份鉴别"},
        "result": "识别到密码策略已启用...",
        "duration_ms": 3500
    }
]
```

4. 招投标任务表 (bidding_tasks)

- id：主键，自增
- session_id：外键（关联 sessions.id）
- user_id：外键（关联 users.id），索引
- tender_title：字符串(255)，可空；招标项目名称
- tender_url：字符串(512)，可空；招标公告 URL
- tender_file_path：字符串(512)，可空；解析后的招标文件路径
- bidding_sections：JSON，可空；生成的投标文件各部分内容，字段约定见下方示例
- compliance_result：JSON，可空；废标项与评分表检查结果，字段约定见下方示例
- reference_doc_ids：JSON，可空；本次编写引用的历史标书文档 ID 列表，用于审计溯源
- status：整数，非空，默认 0，索引（0=搜索中，1=已解析，2=编写中，3=废标检查中，4=待人工审核，5=已完成，6=异常终止）
- created_at：Unix 秒时间戳，非空
- updated_at：Unix 秒时间戳，非空

`bidding_sections` 示例：

```json
{
    "company_profile": "公司成立于...",
    "qualification": "具备...",
    "project_team": "项目经理1名...",
    "pricing": "（待人工审核）"
}
```

`compliance_result` 示例：

```json
[
    {
        "item": "投标保证金比例",
        "type": "废标项",
        "status": "pass",
        "detail": "符合要求"
    }
]
```

`reference_doc_ids` 示例：

```json
[3, 7, 12]
```

5. 测评核查记录表 (assessment_records)

- id：主键，自增
- session_id：外键（关联 sessions.id），索引
- user_id：外键（关联 users.id），索引
- system_level：整数，非空（注释：0=二级，1=三级，2=四级）
- checklist_code：字符串(32)，非空；等保控制点编号，如 `8.1.4.1`
- checklist_name：字符串(128)，非空；控制点名称，如 `身份鉴别`
- assessment_command：字符串(512)，可空；测评命令，如 `net accounts` 或 `cat /etc/login.defs`
- screenshot_path：字符串(512)，可空；测评截图文件路径
- vlm_analysis：JSON，可空；VLM 截图分析结果，字段约定见下方示例
- human_record：TEXT，可空；组员人工填写的结果记录
- comparison_result：JSON，可空；AI 与人工记录比对结果，字段约定见下方示例
- kb_references：JSON，可空；核查时检索到的企业本地知识库特殊情况说明，字段约定见下方示例
- confidence：Float，非空，默认 0.0；置信度 0.0~1.0
- status：整数，非空，默认 0，索引（0=待测评，1=待核查，2=核查中，3=自动通过，4=待人工复核，5=已确认，6=异常）
- created_at：Unix 秒时间戳，非空
- updated_at：Unix 秒时间戳，非空

`vlm_analysis` 示例：

```json
{
    "recognized_text": "Password minimum length: 8",
    "detected_items": ["密码策略已启用", "最小长度8位", "复杂度要求开启"],
    "raw_response": "VLM 原始返回内容..."
}
```

`comparison_result` 示例：

```json
{
    "consistent": false,
    "ai_result": "密码策略已配置",
    "human_result": "密码策略未配置",
    "diff_detail": "截图显示已启用密码策略，人工记录为未配置"
}
```

`kb_references` 示例：

```json
[
    {
        "doc_id": 5,
        "doc_title": "XX系统特殊配置说明",
        "matched_text": "该系统使用堡垒机统一管理密码策略，本地不显示...",
        "similarity": 0.87
    }
]
```

6. 网络拓扑记录表 (topology_records)

- id：主键，自增
- session_id：外键（关联 sessions.id），索引
- user_id：外键（关联 users.id）
- asset_file_path：字符串(512)，非空；资产核查表文件路径
- topology_data：JSON，可空；生成的网络拓扑图数据（节点与边），供前端 Vue Flow 渲染，字段约定见下方示例
- topology_summary：TEXT，可空；拓扑结构文字描述（Agent 生成的分析说明）
- status：整数，非空，默认 0，索引（0=生成中，1=已完成，2=生成失败）
- created_at：Unix 秒时间戳，非空
- updated_at：Unix 秒时间戳，非空

`topology_data` 示例：

```json
{
    "nodes": [
        {"id": "node-1", "label": "核心交换机", "type": "switch", "ip": "192.168.1.1"},
        {"id": "node-2", "label": "Web服务器", "type": "server", "ip": "192.168.1.10"},
        {"id": "node-3", "label": "数据库服务器", "type": "database", "ip": "192.168.1.20"}
    ],
    "edges": [
        {"id": "edge-1", "source": "node-1", "target": "node-2", "label": "千兆"},
        {"id": "edge-2", "source": "node-1", "target": "node-3", "label": "千兆"}
    ]
}
```

7. 审核任务表 (review_tasks)

- id：主键，自增
- session_id：外键（关联 sessions.id）
- user_id：外键（关联 users.id）；提交审核的用户
- task_type：整数，非空，索引（注释：0=报价审核，1=低置信度复核）
- source_type：整数，非空（注释：0=招投标任务，1=测评核查记录）
- source_id：整数，非空；关联 bidding_tasks.id 或 assessment_records.id
- review_data：JSON，非空；待审核数据快照，字段约定见下方示例
- reviewer_id：外键（关联 users.id），可空；实际审核人
- review_result：整数，可空（0=通过，1=驳回，2=修改后通过）
- review_comment：TEXT，可空；审核意见
- status：整数，非空，默认 0，索引（0=待审核，1=已审核，2=已取消）
- created_at：Unix 秒时间戳，非空
- reviewed_at：Unix 秒时间戳，可空；审核完成时间

报价审核 `review_data` 示例（task_type=0）：

```json
{
    "bidding_task_id": 3,
    "pricing_section": "报价总金额：￥280,000",
    "tender_budget": "￥300,000",
    "ai_suggestion": "报价在预算范围内，建议通过"
}
```

低置信度复核 `review_data` 示例（task_type=1）：

```json
{
    "assessment_record_id": 12,
    "checklist_code": "8.1.4.1",
    "checklist_name": "身份鉴别",
    "ai_result": "密码策略已配置",
    "human_result": "密码策略未配置",
    "confidence": 0.62,
    "kb_references": "该系统使用堡垒机统一管理密码策略，本地不显示...",
    "reason": "AI 与人工记录不一致，置信度 0.62 低于阈值 0.80"
}
```

8. 知识库文档表 (kb_documents)

- id：主键，自增
- user_id：外键（关联 users.id），可空；上传者（系统导入则为空）
- kb_type：整数，非空，索引（注释：0=等保标准库，1=企业本地库，2=历史标书库）
- doc_title：字符串(255)，非空；文档标题
- doc_source：字符串(255)，可空；来源，如 `GB/T 22239-2019` 或 `XX项目中标标书`
- file_path：字符串(512)，非空；原始文件路径
- chunk_count：整数，非空，默认 0；切分后的向量块数
- status：整数，非空，默认 0（0=待处理，1=已向量化，2=处理失败）
- created_at：Unix 秒时间戳，非空

> 全局说明：
>
> **商务线**：`sessions.intent_type=1` → `bidding_tasks` 全流程（搜索→解析→编写→废标检查→报价审核）。编写时从 `kb_documents`（kb_type=2 历史标书库）检索相似段落参考风格，引用记录写入 `bidding_tasks.reference_doc_ids`。报价部分由 `review_tasks`（task_type=0）触发人工审核。
>
> **技术线**：`sessions.intent_type=2` → `assessment_records` 全流程（生成清单+命令→截图上传→VLM分析→比对记录→置信度判断）。核查时从 `kb_documents`（kb_type=1 企业本地库）检索特殊情况说明，写入 `assessment_records.kb_references`。置信度低于 0.80 时由 `review_tasks`（task_type=1）触发人工复核。网络层面测评时，Agent 读取资产核查表生成拓扑数据存入 `topology_records`，前端 Vue Flow 渲染。
>
> **共享表**：`users`、`sessions`、`chat_messages`、`review_tasks`、`kb_documents` 商务与技术两条线共享。


# 创建 资源元数据表：统一管理文档和图片，MD5实现用户级去重

CREATE TABLE `resources` (
`id` bigint NOT NULL AUTO_INCREMENT COMMENT '资源主键ID',
`resource_type` tinyint NOT NULL COMMENT '资源类型：0=文档（PDF/Word/Excel），1=图片（测评截图）',
`storage_scene` tinyint NOT NULL DEFAULT '0' COMMENT '存储场景：0=长过期（1个月，招标文件/历史标书/测评截图），1=短过期（2小时，对话临时附件），2=只提取内容不存原文件（资产核查表/对话附件提取后丢弃）',
`upload_purpose` tinyint NOT NULL DEFAULT '0' COMMENT '上传用途：0=普通资源，1=招标文件，2=历史标书，3=测评截图，4=资产核查表',
`file_name` varchar(255) NOT NULL COMMENT '用户上传原始文件名',
`file_hash` varchar(64) NOT NULL COMMENT '文件MD5，去重核心字段',
`storage_path` varchar(512) NOT NULL COMMENT 'MinIO对象存储路径',
`user_id` bigint NOT NULL COMMENT '上传用户ID',
`expire_time` bigint DEFAULT NULL COMMENT '资源过期时间（Unix秒时间戳）',
`created_at` bigint NOT NULL DEFAULT UNIX_TIMESTAMP() COMMENT '创建时间',
PRIMARY KEY (`id`),
UNIQUE KEY `uk_file_hash_user_id` (`file_hash`,`user_id`) COMMENT '用户+MD5联合去重'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='资源元数据表';

# 请按"元数据与文件解耦"架构，完成 MinIO 对象存储改造。

目标：

- MySQL resources 存元数据；
- MinIO 存原文件；
- /upload/file 接口路径不变。

要求：

1. 保留去重规则：UNIQUE(file_hash, user_id)（代码层可预查，数据库兜底）。
2. 上传改为 MinIO put_object；storage_path 格式：minio://{bucket}/{object_key}。
3. storage_scene=2：只提取文件内容，不上传原文件。资产核查表提取后供 Agent 生成拓扑图，对话附件提取后写入 chat_messages.file_extracted_text。
4. upload_purpose 业务联动：
    - upload_purpose=1（招标文件）：上传后解析投标格式，更新 bidding_tasks.tender_file_path；
    - upload_purpose=2（历史标书）：上传后同步创建 kb_documents 记录（kb_type=2），并向 Qdrant 灌入向量；
    - upload_purpose=3（测评截图）：上传后更新 assessment_records.screenshot_path；
    - upload_purpose=4（资产核查表）：storage_scene=2，只提取内容供 Agent 生成拓扑数据写入 topology_records。
5. 创建 MinIO 客户端，并在环境变量中配置连接变量。
6. 教学/运行分离：
    - upload_service.py 保留旧本地逻辑（不运行）；
    - 新建 upload_service_minio.py 作为运行逻辑；
    - /upload/file 路由切到 upload_service_minio.py。
7. 新增过期清理：每天03:00扫描 expire_time，先删 MinIO 对象，再删元数据。
8. 更新 requirements（minio 依赖）。
9. 代码简洁：职责单一、注释清晰、无冗余代码。




# 请在现有 FastAPI 项目中实现并完善会话与聊天接口，严格遵守以下语义与约束：

## 核心语义

1. `ChatMessage.role`（0=user，1=assistant）+ `content` 是聊天正文主字段，按角色分行存储，一行一条；
2. `tool_calls`（JSON）存 Agent 工具调用记录（工具名、参数、结果、耗时），`file_extracted_text` 存从文件中提取的完整文本（对话上下文用）；
3. 用户提问可带附件（`file_extracted_text` 非空）；AI 回复可带文本正文（`content`）和工具调用记录（`tool_calls`）；
4. 聊天消息返回需包含 `intent_type`（0=对话助手，1=招投标，2=测评核查，3=知识问答）与 `task_id`，用于前端任务卡片逻辑：
    - `intent_type=1`：`task_id` 指向 `bidding_tasks.id`，前端渲染招投标进度卡片；
    - `intent_type=2`：`task_id` 指向 `assessment_records` 列表（一个会话可含多个控制点），前端渲染测评核查进度卡片；
    - `intent_type=0` 或 `3`：不返回 `task_id`，前端不渲染任务卡片；
5. `bidding_tasks` 和 `assessment_records` 均包含 `user_id`，获取详情时需根据 `task_id` + `user_id` 查询。

## 需要实现/确认的接口

1. `GET /sessions?page=&page_size=&role_type=`：会话列表分页（按当前用户，按 `role_type` 筛选商务/技术）
2. `POST /sessions`：创建会话（需传 `title` + `role_type` + `intent_type`）
3. `PUT /sessions/{session_id}`：编辑会话标题
4. `DELETE /sessions/{session_id}`：删除会话（级联删除）
    - 删除 session
    - 删除该 session 下 `chat_messages`
    - 删除关联 `bidding_tasks`（若 `intent_type=1`）
    - 删除关联 `assessment_records`（若 `intent_type=2`）
    - 删除关联 `topology_records`（若 `intent_type=2` 且有拓扑记录）
    - 删除关联 `review_tasks`（该 session 下所有待审核/已审核任务）
    - 解析 `chat_messages.tool_calls` 收集引用的 `resources.id`
    - 删除 `resources` 中文件元信息与 MinIO 对象存储文件
5. `GET /sessions/{session_id}/messages?page=&page_size=`：分页获取聊天消息
    - 返回：`role`/`content` + `tool_calls`/`file_extracted_text` + `intent_type`/`task_id`/`created_at`
    - 按 `created_at` 升序排列
    - `task_id` 解析逻辑：`intent_type=1` 时查 `bidding_tasks` 获取 `id`+`status`；`intent_type=2` 时查 `assessment_records` 获取该 session 下所有记录的 `id`+`status`+`checklist_code`+`checklist_name`+`confidence`
6. `GET /bidding_tasks/{task_id}`：按 `task_id` + `user_id` 获取招投标详情
    - 返回：`status` + `tender_title`/`tender_url` + `bidding_sections`（各部分投标内容）+ `compliance_result`（废标检查结果，含 item/type/status/detail）+ `reference_doc_ids`（引用的历史标书 ID）
7. `GET /assessment_records?session_id={session_id}`：按 `session_id` 获取该会话下所有测评核查记录列表
    - 返回：列表，每条含 `id`/`checklist_code`/`checklist_name`/`status`/`confidence`/`system_level`
8. `GET /assessment_records/{record_id}`：按 `record_id` + `user_id` 获取单条测评核查详情
    - 返回：`status` + `checklist_code`/`checklist_name` + `assessment_command` + `vlm_analysis`（VLM 识别结果）+ `human_record`（人工记录）+ `comparison_result`（比对结果，含 consistent/ai_result/human_result/diff_detail）+ `confidence` + `kb_references`（知识库参考）




## 通过 langchain 实现下面三层功能：
1. 模型层（llm.py）：只负责 provider -> 模型实例
2. 提示词层（prompt_layer.py）：只负责 Prompt + 链路组装
3. 记忆层（memory.py）：只负责历史记忆构建，并包含搜索增强

### 模型层（llm.py）

- `get_deepseek()`：返回 DeepSeek-V3 文本模型实例，通过 `ChatOpenAI(base_url="https://api.deepseek.com")` 接入，兼容 function calling，用于文本对话、招投标编写、废标检查、测评清单生成、知识问答等纯文本任务；
- `get_qwen_vl()`：返回 Qwen-VL 多模态模型实例，通过 DashScope SDK 接入，用于测评截图分析任务（识别截图内容、提取关键信息）；
- `get_embeddings()`：返回 Embedding 模型实例，用于向量化等保标准文档和历史标书，写入 Qdrant；
- 模型层只做实例化，不组装 Prompt、不调用链路、不碰记忆；
- API Key 从环境变量读取（`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`），temperature 等参数集中配置。

### 提示词层（prompt_layer.py）

- `get_router_prompt()`：路由 Agent 的 system prompt，根据用户角色（商务/技术）和输入意图，输出分发到 `bidding`/`assessment`/`knowledge` 三条链路；
- `get_bidding_prompt()`：招投标 Agent 的 system prompt，定义角色为等保测评商务助手，约束输出投标文件格式，参考检索到的历史标书风格，明确报价部分不生成（标注待人工审核）；
- `get_assessment_prompt()`：测评核查 Agent 的 system prompt，定义角色为等保测评技术核查助手，给定测评控制点和 VLM 分析结果，要求比对人工记录并输出置信度判断；
- `get_vlm_prompt(checklist_item)`：VLM 截图分析的 prompt 模板，传入测评控制点名称，要求识别截图中与该控制点相关的配置信息；
- `get_knowledge_prompt()`：知识库 Agent 的 system prompt，基于双路 RAG 检索结果（等保标准库 + 企业本地库）生成回答，要求引用来源；
- `get_compliance_prompt()`：废标检查 prompt，输入投标内容和招标文件废标项/评分表，逐条比对输出 pass/warning/danger；
- `build_chain(llm, prompt, memory)`：通用链路组装函数，接收模型实例、Prompt 模板、记忆实例，返回一个可执行的 Chain；招投标和测评核查需绑定各自 Tool 列表（search_tender/parse_tender/analyze_screenshot 等）。
- 提示词层只做 Prompt 定义和 Chain 组装，不做模型实例化、不碰数据库、不直接调 Qdrant。

### 记忆层（memory.py）

- `get_session_memory(session_id)`：从数据库 `chat_messages` 表按 `session_id` 查询历史消息，按 `created_at` 排序，构造 LangChain `ConversationBufferWindowMemory`，`role=0` 为 HumanMessage，`role=1` 为 AIMessage；
- `get_rag_context(query, kb_types)`：搜索增强，接收查询文本和知识库类型列表，并行查询 Qdrant 多个 collection（`kb_type=0` 等保标准库 / `kb_type=1` 企业本地库 / `kb_type=2` 历史标书库），合并结果按 similarity 排序，返回 top-k 检索片段；
- `get_bidding_context(tender_title)`：招投标专用搜索增强，查 `kb_type=2` 历史标书库，返回相似段落供 Agent 参考风格和结构，同时返回引用的 `doc_id` 列表供写入 `bidding_tasks.reference_doc_ids`；
- `get_assessment_context(checklist_code)`：测评核查专用搜索增强，查 `kb_type=0` 等保标准库（获取控制点标准要求）和 `kb_type=1` 企业本地库（获取特殊情况说明），合并后返回，同时返回 `kb_references` 结构供写入 `assessment_records.kb_references`；
- `build_memory_prompt(memory, rag_context)`：将历史记忆和 RAG 检索结果组装为上下文，注入 Prompt 的变量中；
- 记忆层只做历史构建和检索增强，不做模型调用、不组装 Chain、不定义 Prompt；
- 历史消息窗口默认保留最近 20 轮，超出时截断早期消息，避免 token 溢出。

### 三层协作关系

```
请求进来
  │
  ├── 记忆层 memory.py
  │     ├── get_session_memory() → 历史对话
  │     └── get_rag_context()    → RAG 检索片段
  │
  ├── 提示词层 prompt_layer.py
  │     ├── get_xxx_prompt()     → 选择对应 Prompt
  │     └── build_chain(llm, prompt, memory) → 组装 Chain
  │
  └── 模型层 llm.py
        └── get_deepseek() / get_qwen_vl() → 提供模型实例
              │
              └── Chain.invoke() → 输出结果
```

# 实现 RAG 文件向量化入库
新建 app/rag/core.py，对外只暴露 ingest_file。

流水线：解析 → 清洗 → 分类 → 分块 → 向量化 → 写 Qdrant

要求
1. 解析：PDF(PyPDF2) / DOCX(python-docx) / TXT，字典分派；不支持类型抛异常。
2. 清洗：去零宽字符、合并空白、压缩多换行、删独立页码行。
3. 分类：resume / study_material / general，按关键字计分，显式值优先。
4. 分块：滑动窗口 size=500、overlap=50，回退到句子终止符（。！？\n）切分，MD5 去重。
5. 向量化：DashScope text-embedding-v4，维度 1024，每批 10 条，按 text_index 对齐顺序。
6. 写库：Qdrant collection=knowledge_chunks，余弦距离，不存在自动建；point.id=uuid4，payload 包含 text/user_id/doc_category/file_name/chunk_index。

约束
- 配置走 settings（dashscope_api_key、qdrant_host、qdrant_port）
- 单文件聚合，不过度抽象

请升级 PDF 解析链路：
1. 解析器替换：PyPDF2 → pypdfium2
   requirements.txt 同步增删，并添加 volcengine SDK、pillow

2. 扫描版判定：在 _parse_pdf 里先用 pypdfium2 抽取文字，平均每页字符数低于 20 视为扫描件，走 OCR 兜底；否则直接返回，电子版不消耗 OCR 成本。

3. OCR 单独成文件 app/rag/ocr.py，对外只暴露 ocr_pdf(path)。内部三步：
pypdfium2 按 150 DPI 渲染每页为 PNG → base64 上送 VisualService 的 OCRNormal → 取 data.line_texts 按行拼接为全文。

4. 凭证：settings.py 新增 volc_access_key / secret_key / region。



#  文档切片升级需求
目标：把现有文本切片升级为递归智能切片，并增强 Word 文档结构识别，代码做最小改造，只修改 core.py

具体要求：
1. 引入 RecursiveCharacterTextSplitter。
3. DOCX 提取时识别 Heading 1 / Heading 2 / Heading 3，并分别注入 # / ## / ### 标题标记。
5. 新的切片分隔符按以下优先级：
`\n###`、`\n##`、`\n#`、`\n\n`、`。`、`！`、`？`、`；`、`，`、空格、字符兜底。
6. 其余的业务逻辑都保留。


### 优化切片数据的存储方式：

**核心功能：切片数据分两份存储**
- Qdrant：只存向量 + 检索过滤字段（user_id、doc_category 等），不存原文
- MySQL knowledge_chunks：存切片原文（text、chunk_index、char_count），关联已有的 resources 表

两边通过同一个 UUID 关联：入库时生成 UUID 同时写入 Qdrant Point id 和 MySQL vector_id 字段。

**实现要点**
- 创建一个 chunk_store.py 需实现: save_chunks
- RagService 增加 db 和 resource_id 入参，写完 Qdrant 后调用 save_chunks 再 commit
请结合我的项目现有代码实现。


# 实现 RAG 检索模块：用户提问 → 找到最相关的知识库片段

核心思路：
检索时把问题也变成向量，
在 Qdrant 里找距离最近的 N 个片段（向量空间找近邻）。

原文回查创建函数：fetch_chunks_by_vector_ids，用它回查 MySQL

新建 app/rag/retriever.py，对外只暴露一个函数 search_similar_chunks，
检索必须带 user_id 过滤（多用户共用同一个 collection，不过滤会串数据）。
- 分数阈值过滤（低于0.4丢弃）
- 单条text截断（超过500字截断）



# 请实现 RAG 对话链路：意图判断、资料注入、来源展示。

目标：
用户提问时按需检索知识库，把命中的知识片段注入本轮上下文；前端能看到回答来源，刷新历史后仍能回显，但数据库不重复保存知识块全文。

实现要点：
1. 用 should_retrieve(request_text) 做轻量意图判断，跳过空输入、极短输入、确认语、礼貌语和推进语。
2. 需要检索时调用 search_similar_chunks(query, user_id, db, top_k=3)，按 user_id 隔离资料，得到 retrieved_chunks。
3. 用 format_retrieved_chunks(retrieved_chunks) 生成 retrieved_text，并作为 rag_context 拼到本轮用户问题前，结构为“【参考资料】+【用户问题】”。
4. build_rag_system_prompt 只补充 RAG 回答规则，不处理 sources 展示和落库。
5. SSE done 返回完整 sources：chunk_id、resource_id、chunk_index、file_name、score、text。
6. 在 ChatMessage 表中新增 reference_sources 字段，用来存储：chunk_id、score
7. 历史消息接口根据 reference_sources 回查 knowledge_chunks 和 resources，重新拼出 sources；知识块已删除时返回“该参考片段已被删除”。
