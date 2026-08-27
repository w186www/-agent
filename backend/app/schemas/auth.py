"""校验层：认证相关请求/响应模型。"""

from pydantic import BaseModel, Field

from .user import UserOut


class UserLogin(BaseModel):
    """登录请求体。"""

    username: str = Field(min_length=1, max_length=32, description="用户名")
    password: str = Field(min_length=1, max_length=72, description="密码")


class RefreshRequest(BaseModel):
    """刷新令牌请求体。"""

    refresh_token: str = Field(min_length=1, description="刷新令牌")


class TokenResponse(BaseModel):
    """登录/刷新成功后的令牌响应。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="访问令牌有效期（秒）")
    user: UserOut | None = None
