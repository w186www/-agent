"""应用配置：环境变量分层管理（开发/生产）。

规则：
- APP_ENV=dev（默认）→ 加载项目根目录 .env
- APP_ENV=prod        → 加载项目根目录 .env.production
- 敏感信息（数据库连接串等）只从环境变量/环境文件读取，代码中不写死任何带密码的默认值；
  缺失必填项时启动即报错，避免带错误配置运行。

启动示例（PowerShell）：
    $env:APP_ENV="prod"; python -m uvicorn app.main:app --port 8000
"""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 当前环境（dev/prod），决定加载哪个环境文件
APP_ENV = os.getenv("APP_ENV", "dev")
_ENV_FILE = ".env" if APP_ENV == "dev" else ".env.production"


class Settings(BaseSettings):
    """全局配置项。"""

    # 基础
    app_env: str = "dev"             # 运行环境
    app_name: str = "等保测评全流程助手"    # 服务名称
    app_version: str = "0.1.0"       # 服务版本

    # 敏感配置：必填，由环境文件提供，代码不设默认值
    mysql_url: str = Field(..., description="MySQL 连接串（必填，仅从环境配置读取）")
    jwt_secret: str = Field(..., description="JWT 签名密钥（必填，仅从环境配置读取）")

    # JWT
    jwt_algorithm: str = "HS256"                 # 签名算法
    access_token_expire_minutes: int = 15        # 访问令牌有效期（分钟）
    refresh_token_expire_days: int = 7           # 刷新令牌有效期（天）

    # 日志
    log_level: str = "INFO"          # 日志级别：dev 建议 INFO，prod 可调 WARNING 减少噪音
    log_dir: str = "logs"            # 日志文件目录

    # 文件上传
    upload_dir: str = "./data/uploads"   # 文件上传根目录（download_tender 下载的招标文件也存于此）
    max_upload_size: int = 10 * 1024 * 1024  # 最大上传 10MB
    tender_dir: str = "./data/uploads/tenders"  # 招标文件存储子目录（download_tender 落盘目录，启动时自动创建）
    parse_max_text_length: int = 50000   # parse_tender 传给 LLM 解析的最大文本长度，超出截断

    # MinIO 对象存储（元数据与文件解耦：MySQL 存元数据，MinIO 存原文件）
    minio_endpoint: str = "127.0.0.1:19000"   # 独立端口，避免与其它项目冲突
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "dengbao"             # 独立 bucket
    minio_secure: bool = False                # 本机 HTTP，生产改 HTTPS

    # Qdrant 向量库（等保标准库 / 企业本地库 / 历史标书库，按 kb_type 分 collection）
    qdrant_url: str = "http://127.0.0.1:16333"
    qdrant_collection: str = "dengbao_kb"     # 集合前缀，实际集合名 = {前缀}_{kb_type}

    # 大模型（AI 三层：模型层 / 提示词层 / 记忆层）
    # 缺失时启动不报错，调用对应 get_xxx() 时抛出业务异常提示补配置
    deepseek_api_key: str = ""                # DeepSeek（DEEPSEEK_API_KEY）
    dashscope_api_key: str = ""               # 阿里云百炼 DashScope（DASHSCOPE_API_KEY）

    # 火山引擎 OCR（扫描版 PDF 兜底：kb_ingest 提取到空文本时自动识别）
    volc_access_key: str = ""                 # 火山引擎 Access Key（VOLC_ACCESS_KEY）
    volc_secret_key: str = ""                 # 火山引擎 Secret Key（VOLC_SECRET_KEY）
    volc_region: str = "cn-north-1"           # 火山引擎区域（VOLC_REGION）
    volc_host: str = "visual.volcengineapi.com"  # 视觉服务域名（VOLC_HOST）

    # Tavily 联网搜索（招投标 Agent 工具 search_tender）
    tavily_api_key: str = ""                  # Tavily（TAVILY_API_KEY），缺失时工具返回友好错误
    tender_sites: list[str] = Field(default_factory=lambda: ["cebpub.com", "ccgp.gov.cn", "bidcenter.com.cn"])  # 招标网站域名白名单
    tavily_max_results: int = 10              # 单次搜索最大结果数

    # LangGraph 状态机（招投标 Agent 图，替换 AgentExecutor）
    graph_max_iterations: int = 10            # 图最大工具调用轮次，防止死循环
    graph_recursion_limit: int = 25           # LangGraph 递归限制（compile 时传入）

    # 标书生成与自检（商务线全流程闭环）
    bidding_max_retries: int = 3              # 标书生成最大重试次数（自检驳回后重新生成），超过后提示人工处理
    selfcheck_model: str = ""                 # 自检使用模型名（留空用 get_deepseek()，可配置为更强模型）

    # 投标文件审核（review_bidding 工具）
    review_confidence_threshold: float = 0.75  # 人工确认置信度阈值，低于此值的审核项 need_human=true
    bidding_review_max_items: int = 20        # 投标文件审核最大检查项数

    # 知识库灌入（kb_ingest：历史标书切分向量化，写入 Qdrant）
    chunk_size: int = 500                     # 文本切分块大小（字符）
    chunk_overlap: int = 50                   # 切分块重叠（字符）

    # 模型与检索参数集中配置
    llm_temperature: float = 0.3              # 文本生成温度（DeepSeek）
    llm_max_tokens: int = 2048                # 单次生成最大 token 数
    vlm_model: str = "qwen-vl-plus"           # Qwen-VL 多模态模型
    embedding_model: str = "text-embedding-v3"  # DashScope 文本向量化模型
    rag_top_k: int = 5                        # RAG 检索返回 top-k 片段数
    memory_window_k: int = 20                 # 会话历史窗口保留轮数

    # 测评核查（技术线：清单生成 / VLM 分析 / 比对置信度）
    confidence_threshold: float = 0.80        # 自动通过置信度阈值：>= 阈值 status=3 自动通过，< 阈值 status=4 待人工复核
    assessment_max_checklist: int = 50        # 单次生成最大控制点数（generate_checklist 截断上限）

    # CORS 允许来源（逗号分隔，CORS_ORIGINS 环境变量覆盖；生产必须配置为前端实际域名）
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")


settings = Settings()
