"""校验层：Pydantic v2 请求/响应模型，负责参数校验与响应字段过滤。

响应统一走 schemas.common.ApiResponse 包裹，data 部分使用 UserOut 过滤敏感字段。
"""

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """创建用户请求体。"""

    username: str = Field(min_length=1, max_length=32, description="用户名")
    # bcrypt 单次输入上限为 72 字节，故密码长度限制为 72
    password: str = Field(min_length=6, max_length=72, description="密码（最短 6 位）")


class UserUpdate(BaseModel):
    """更新用户请求体，所有字段可选。"""

    username: str | None = Field(default=None, min_length=1, max_length=32, description="新用户名")
    password: str | None = Field(default=None, min_length=6, max_length=72, description="新密码")


class UserOut(BaseModel):
    """用户响应模型：仅暴露 id 和 username，绝不含 password_hash。

    from_attributes=True 支持直接校验 ORM 模型对象。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
