"""数据库层：SQLAlchemy 2.0 ORM 模型定义。

共 8 张表：users / sessions / chat_messages / bidding_tasks /
assessment_records / topology_records / review_tasks / kb_documents。

约定：
- 时间戳统一为 Unix 秒（BigInteger），MySQL 侧由 UNIX_TIMESTAMP() 提供 server 默认值；
  Python 端 default 兜底，保证测试（SQLite 内存库）环境下插入可用。
- JSON 字段使用 sqlalchemy.JSON，MySQL 下为 JSON 类型，SQLite 下为文本存储。
"""

import time

from sqlalchemy import (
    JSON,
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> int:
    """当前 Unix 秒时间戳（Python 端默认值，兼容 SQLite 测试库）。"""
    return int(time.time())


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class User(Base):
    """用户表。

    - role: 0=商务，1=技术
    - status: 0=禁用，1=正常
    - avatar: 头像路径（文件上传接口使用）
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="登录用户名")
    password_hash: Mapped[str] = mapped_column(String(255), comment="密码 bcrypt 哈希")
    role: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), index=True, comment="角色：0=商务，1=技术")
    display_name: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"), comment="显示名称")
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="手机号")
    status: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), comment="状态：0=禁用，1=正常")
    avatar: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="头像路径")
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), onupdate=_now, comment="更新时间（Unix 秒）"
    )


class ChatSession(Base):
    """会话表。

    - role_type: 0=商务，1=技术
    - intent_type: 0=对话助手，1=招投标，2=测评核查，3=知识问答
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, comment="所属用户")
    role_type: Mapped[int] = mapped_column(Integer, comment="角色类型：0=商务，1=技术")
    intent_type: Mapped[int] = mapped_column(Integer, comment="意图类型：0=对话助手，1=招投标，2=测评核查，3=知识问答")
    title: Mapped[str] = mapped_column(String(255), comment="会话标题")
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="会话创建时间（Unix 秒）"
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), onupdate=_now, comment="会话更新时间（Unix 秒）"
    )
    attachment_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="会话绑定附件文件名（对话附件，storage_scene=2 提取文本后绑定）"
    )
    attachment_text: Mapped[str | None] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True, comment="会话绑定附件提取文本"
    )


class ChatMessage(Base):
    """消息表。

    - role: 0=user，1=assistant
    - tool_calls: Agent 工具调用记录（JSON）
    - file_extracted_text: 从文件中提取的完整文本（对话上下文用）
    """

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_created", "session_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), comment="所属用户")
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), comment="所属会话")
    role: Mapped[int] = mapped_column(Integer, comment="消息角色：0=user，1=assistant")
    request_id: Mapped[str] = mapped_column(String(64), index=True, comment="请求 ID")
    content: Mapped[str] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"), comment="消息内容"
    )
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="Agent 工具调用记录")
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="附件原始文件名")
    file_extracted_text: Mapped[str | None] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True, comment="从文件中提取的完整文本"
    )
    reference_sources: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="知识问答引用来源（[{chunk_id, score}]，供历史消息回显重拼）"
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )


class BiddingTask(Base):
    """招投标任务表。

    - bidding_sections: 生成的投标文件各部分内容（JSON）
    - compliance_result: 废标项与评分表检查结果（JSON）
    - reference_doc_ids: 引用的历史标书文档 ID 列表（JSON）
    - status: 0=搜索中，1=已解析，2=编写中，3=废标检查中，4=待人工审核，5=已完成，6=异常终止
    """

    __tablename__ = "bidding_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), comment="所属会话")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, comment="所属用户")
    tender_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="招标项目名称")
    tender_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="招标公告 URL")
    tender_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="解析后的招标文件路径")
    bidding_sections: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="投标文件各部分内容")
    compliance_result: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="废标项与评分表检查结果")
    reference_doc_ids: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="引用的历史标书文档 ID 列表")
    status: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), index=True,
        comment="状态：0=搜索中，1=已解析，2=编写中，3=废标检查中，4=待人工审核，5=已完成，6=异常终止",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), onupdate=_now, comment="更新时间（Unix 秒）"
    )


class AssessmentRecord(Base):
    """测评核查记录表。

    - system_level: 0=二级，1=三级，2=四级
    - vlm_analysis: VLM 截图分析结果（JSON）
    - comparison_result: AI 与人工记录比对结果（JSON）
    - kb_references: 企业本地知识库检索结果（JSON）
    - status: 0=待测评，1=待核查，2=核查中，3=自动通过，4=待人工复核，5=已确认，6=异常
    """

    __tablename__ = "assessment_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, comment="所属会话")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, comment="所属用户")
    system_level: Mapped[int] = mapped_column(Integer, comment="等保级别：0=二级，1=三级，2=四级")
    checklist_code: Mapped[str] = mapped_column(String(32), comment="等保控制点编号，如 8.1.4.1")
    checklist_name: Mapped[str] = mapped_column(String(128), comment="控制点名称，如 身份鉴别")
    assessment_command: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="测评命令")
    screenshot_path: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="测评截图文件路径")
    vlm_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="VLM 截图分析结果")
    human_record: Mapped[str | None] = mapped_column(Text, nullable=True, comment="组员人工填写的结果记录")
    comparison_result: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="AI 与人工记录比对结果")
    kb_references: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="核查时检索到的企业本地知识库特殊情况说明")
    confidence: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0.0"), comment="置信度 0.0~1.0"
    )
    status: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), index=True,
        comment="状态：0=待测评，1=待核查，2=核查中，3=自动通过，4=待人工复核，5=已确认，6=异常",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), onupdate=_now, comment="更新时间（Unix 秒）"
    )


class TopologyRecord(Base):
    """网络拓扑记录表。

    - topology_data: 网络拓扑图数据（节点与边），供前端 Vue Flow 渲染（JSON）
    - status: 0=生成中，1=已完成，2=生成失败
    """

    __tablename__ = "topology_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, comment="所属会话")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), comment="所属用户")
    asset_file_path: Mapped[str] = mapped_column(String(512), comment="资产核查表文件路径")
    topology_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="网络拓扑图数据")
    topology_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="拓扑结构文字描述")
    status: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), index=True,
        comment="状态：0=生成中，1=已完成，2=生成失败",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), onupdate=_now, comment="更新时间（Unix 秒）"
    )


class ReviewTask(Base):
    """审核任务表。

    - task_type: 0=审核（报价/自检/投标文件），1=低置信度复核，2=解析结果确认，3=自检审核
    - source_type: 0=招投标任务，1=测评核查记录
    - review_data: 待审核数据快照（JSON）
    - review_result: 0=通过，1=驳回，2=修改后通过
    - status: 0=待审核，1=已审核，2=已取消
    """

    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), comment="所属会话")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), comment="提交审核的用户")
    task_type: Mapped[int] = mapped_column(Integer, index=True, comment="任务类型：0=审核（报价/自检/投标文件），1=低置信度复核，2=解析结果确认，3=自检审核")
    source_type: Mapped[int] = mapped_column(Integer, comment="来源类型：0=招投标任务，1=测评核查记录")
    source_id: Mapped[int] = mapped_column(Integer, comment="关联 bidding_tasks.id 或 assessment_records.id")
    review_data: Mapped[dict] = mapped_column(JSON, comment="待审核数据快照")
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="实际审核人")
    review_result: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="审核结果：0=通过，1=驳回，2=修改后通过")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    status: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), index=True,
        comment="状态：0=待审核，1=已审核，2=已取消",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )
    reviewed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="审核完成时间（Unix 秒）")


class KbDocument(Base):
    """知识库文档表。

    - kb_type: 0=等保标准库，1=企业本地库，2=历史标书库
    - status: 0=待处理，1=已向量化，2=处理失败
    """

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="上传者（系统导入则为空）")
    kb_type: Mapped[int] = mapped_column(Integer, index=True, comment="知识库类型：0=等保标准库，1=企业本地库，2=历史标书库")
    doc_title: Mapped[str] = mapped_column(String(255), comment="文档标题")
    doc_source: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="来源，如 GB/T 22239-2019")
    file_path: Mapped[str] = mapped_column(String(512), comment="原始文件路径")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="切分后的向量块数")
    status: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), comment="状态：0=待处理，1=已向量化，2=处理失败"
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )


class KbChunk(Base):
    """知识库切片表：向量化切分后的原文，与 Qdrant point 通过 vector_id 关联。

    用途：切片原文溯源（知识库内容审计）、同文档重传时覆盖删除的 MySQL 侧依据。
    """

    __tablename__ = "kb_chunks"
    __table_args__ = (Index("ix_kb_chunks_doc_index", "doc_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    doc_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"), index=True, comment="所属文档")
    vector_id: Mapped[str] = mapped_column(String(64), comment="Qdrant Point id（{doc_id}-{chunk_index}，与向量关联）")
    chunk_index: Mapped[int] = mapped_column(Integer, comment="块序号")
    content: Mapped[str] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"), comment="切片原文"
    )
    char_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="字符数")
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )


class Resource(Base):
    """资源元数据表：统一管理文档和图片，file_hash + user_id 联合去重。

    - resource_type: 0=文档（PDF/Word/Excel），1=图片（测评截图）
    - storage_scene: 0=长过期（1个月），1=短过期（2小时），2=只提取内容不存原文件
    - upload_purpose: 0=普通资源，1=招标文件，2=历史标书，3=测评截图，4=资产核查表，5=投标文件
    - file_hash: 文件 MD5，去重核心字段
    - storage_path: MinIO 对象存储路径
    - expire_time: 资源过期时间（Unix 秒时间戳）
    """

    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("file_hash", "user_id", name="uk_file_hash_user_id", comment="用户+MD5联合去重"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="资源主键ID")
    resource_type: Mapped[int] = mapped_column(
        Integer().with_variant(TINYINT(), "mysql"), comment="资源类型：0=文档（PDF/Word/Excel），1=图片（测评截图）"
    )
    storage_scene: Mapped[int] = mapped_column(
        Integer().with_variant(TINYINT(), "mysql"), default=0, server_default=text("0"),
        comment="存储场景：0=长过期（1个月），1=短过期（2小时），2=只提取内容不存原文件",
    )
    upload_purpose: Mapped[int] = mapped_column(
        Integer().with_variant(TINYINT(), "mysql"), default=0, server_default=text("0"),
        comment="上传用途：0=普通资源，1=招标文件，2=历史标书，3=测评截图，4=资产核查表，5=投标文件",
    )
    file_name: Mapped[str] = mapped_column(String(255), comment="用户上传原始文件名")
    file_hash: Mapped[str] = mapped_column(String(64), comment="文件MD5，去重核心字段")
    storage_path: Mapped[str] = mapped_column(String(512), comment="MinIO对象存储路径")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="上传用户ID")
    expire_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="资源过期时间（Unix秒时间戳）")
    created_at: Mapped[int] = mapped_column(
        BigInteger, default=_now, server_default=text("(unix_timestamp())"), comment="创建时间（Unix 秒）"
    )
