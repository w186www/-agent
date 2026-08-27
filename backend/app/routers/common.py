"""路由层公共工具：统一成功响应与响应字段过滤。"""

from ..schemas.common import ApiResponse
from ..schemas.user import UserOut


def ok(data=None, message: str = "success") -> ApiResponse:
    """构造成功响应：code 固定为 0。"""
    return ApiResponse(code=0, message=message, data=data)


def to_out(user) -> dict:
    """将 ORM 记录转换为对外响应，仅保留 UserOut 声明字段。"""
    return UserOut.model_validate(user).model_dump()
