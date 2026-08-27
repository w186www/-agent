"""全局异常处理器：将各类异常统一转换为标准化响应结构，并记录日志。

覆盖：业务异常、系统异常、HTTPException、参数校验失败、未预期兜底异常。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .exceptions import BusinessError, ErrorCode, SystemError
from .log import get_logger
from .schemas.common import ApiResponse

logger = get_logger("app.error")

# pydantic v2 常见校验错误类型 -> 中文提示
_VALIDATION_MSG = {
    "missing": "缺少必填字段",
    "string_too_short": "长度不足",
    "string_too_long": "长度超限",
    "string_type": "必须为字符串",
    "int_parsing": "必须为整数",
    "int_type": "必须为整数",
}


def _error_response(status_code: int, code: int, message: str, detail: str | None) -> JSONResponse:
    """构造统一错误响应体。"""
    body = ApiResponse(code=code, message=message, data=None, detail=detail).model_dump()
    return JSONResponse(status_code=status_code, content=body)


def _exc_info(exc: Exception) -> tuple:
    """构造日志 exc_info，确保异常堆栈完整记录。"""
    return (type(exc), exc, exc.__traceback__)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全部全局异常处理器。"""

    @app.exception_handler(BusinessError)
    async def business_error_handler(request: Request, exc: BusinessError):
        logger.warning("业务异常 %s -> %s | %s", request.url.path, exc.message, exc.detail)
        return _error_response(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(SystemError)
    async def system_error_handler(request: Request, exc: SystemError):
        logger.error("系统异常 %s -> %s", request.url.path, exc.detail, exc_info=_exc_info(exc))
        return _error_response(500, exc.code, exc.message, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "请求错误"
        logger.warning("HTTP 异常 %s -> %s %s", request.url.path, exc.status_code, message)
        return _error_response(exc.status_code, exc.status_code, message, message)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # 提取首条校验错误，转成中文可读提示
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        msg = _VALIDATION_MSG.get(first.get("type", ""), first.get("msg", "参数校验失败"))
        detail = f"字段[{loc}] {msg}" if loc else msg
        logger.warning("参数校验失败 %s -> %s", request.url.path, detail)
        return _error_response(422, ErrorCode.VALIDATION, "请求参数校验失败", detail)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # 兜底：任何未预期异常统一转 500，完整堆栈写入日志供后端定位
        logger.error("未捕获异常 %s -> %r", request.url.path, exc, exc_info=_exc_info(exc))
        return _error_response(500, ErrorCode.INTERNAL, "系统内部错误，请稍后重试", repr(exc))
