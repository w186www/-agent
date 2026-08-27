"""通用响应模型。"""

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一响应模型：所有接口（成功与失败）均返回该结构，前端按此解析。

    - code: 业务码，0 成功，非 0 见 exceptions.ErrorCode
    - message: 中文可读提示
    - data: 业务数据（失败时为 None）
    - detail: 错误定位信息，成功时为 None
    """

    code: int = 0
    message: str = "success"
    data: Any = None
    detail: str | None = None
