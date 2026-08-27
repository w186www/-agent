"""校验层：会话 / 消息 / 招投标任务 / 测评核查记录的请求与响应模型。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    """新建会话请求体。"""

    role_type: int = Field(ge=0, le=1, description="角色类型：0=商务，1=技术")
    intent_type: int = Field(ge=0, le=3, description="意图类型：0=对话助手，1=招投标，2=测评核查，3=知识问答")
    title: str | None = Field(default=None, max_length=255, description="会话标题，缺省自动生成")


class SessionUpdate(BaseModel):
    """更新会话请求体（当前仅支持改标题）。"""

    title: str = Field(min_length=1, max_length=255, description="新会话标题")


class SessionOut(BaseModel):
    """会话响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role_type: int
    intent_type: int
    title: str
    created_at: int
    updated_at: int
    attachment_name: str | None = None


class ChatMessageOut(BaseModel):
    """消息响应模型：正文 / 工具调用 / 文件上下文三部分，按 role 区分渲染。

    intent_type / task_id 非表字段，由消息接口按会话动态补齐，供前端任务卡片逻辑使用：
    - intent_type=1：task_id 为 {"id", "status"}，指向最近一条 bidding_tasks；
    - intent_type=2：task_id 为该会话下 assessment_records 摘要列表；
    - intent_type=0/3：无任务卡片，task_id 为 None。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: int  # 0=user，1=assistant
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    file_name: str | None = None
    file_extracted_text: str | None = None
    created_at: int
    intent_type: int = 0  # 会话意图类型：0=对话助手，1=招投标，2=测评核查，3=知识问答
    task_id: Any | None = None  # 任务卡片数据，见类注释


class BiddingTaskOut(BaseModel):
    """招投标任务响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    tender_title: str | None = None
    tender_url: str | None = None
    tender_file_path: str | None = None
    bidding_sections: dict[str, Any] | None = None
    compliance_result: list[dict[str, Any]] | None = None
    reference_doc_ids: list[int] | None = None
    status: int
    created_at: int
    updated_at: int


class AssessmentRecordOut(BaseModel):
    """测评核查记录响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    system_level: int
    checklist_code: str
    checklist_name: str
    assessment_command: str | None = None
    screenshot_path: str | None = None
    vlm_analysis: dict[str, Any] | None = None
    human_record: str | None = None
    comparison_result: dict[str, Any] | None = None
    kb_references: list[Any] | None = None
    confidence: float
    status: int
    created_at: int


class StreamChatRequest(BaseModel):
    """流式聊天请求体（SSE /chat/stream）。"""

    session_id: int = Field(description="会话 ID")
    content: str = Field(min_length=1, max_length=8000, description="用户输入内容")
    role: int = Field(default=0, ge=0, le=1, description="消息角色：0=user")
    intent_type: int = Field(default=0, ge=0, le=3, description="意图类型：0=对话助手，1=招投标，2=测评核查，3=知识问答")
    # 文件附件场景（用户上传招标/投标文件后发送消息，intent_type=1 时生效）
    upload_purpose: int | None = Field(default=None, ge=0, le=5, description="上传用途：1=招标文件，5=投标文件")
    file_path: str | None = Field(default=None, max_length=512, description="上传文件存储路径（minio://...）")
    file_extracted_text: str | None = Field(default=None, max_length=50000, description="上传文件提取的文本（供对话上下文）")


class ReviewRequest(BaseModel):
    """人工审核请求体（POST /review/{review_task_id}）。

    action 为审核动作；modified_sections 仅在 action=modified 时携带（修改后通过的投标内容），
    后端用其更新 bidding_tasks.bidding_sections。
    """

    action: str = Field(pattern="^(approve|reject|modified)$", description="审核动作：approve=通过，reject=驳回，modified=修改后通过")
    comment: str | None = Field(default=None, max_length=1000, description="审核意见")
    modified_sections: dict[str, Any] | None = Field(default=None, description="修改后的投标文件各部分内容（action=modified 时携带）")


class ResumeRequest(BaseModel):
    """恢复 HITL 中断对话请求体（POST /chat/{thread_id}/resume）。

    支持两种恢复场景：
    - parsed_review：第一个 HITL（解析结果确认），confirmed 决定是否继续；
    - selfcheck_review：第二个 HITL（自检结果审核），approved 决定通过/驳回，
      modified_sections 在"修改后通过"时携带并更新投标内容。
    """

    session_id: int = Field(description="会话 ID（归属校验与任务状态联动用）")
    review_type: str = Field(default="parsed_review", pattern="^(parsed_review|selfcheck_review)$", description="恢复场景：parsed_review=解析确认，selfcheck_review=自检审核")
    confirmed: bool = Field(default=True, description="解析结果是否确认继续；False 表示不确认（直接结束）")
    approved: bool = Field(default=False, description="自检审核是否通过；False=驳回重新生成")
    modified_sections: dict[str, Any] | None = Field(default=None, description="修改后通过的投标内容（approved=True 时可携带）")
