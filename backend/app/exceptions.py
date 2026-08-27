"""统一异常定义：业务异常与系统异常两类，供全局异常处理器识别。

- BusinessError：预期内的业务规则错误，message 面向用户中文可读；
- SystemError：未预期的内部错误，message 通用化，真实原因记录在 detail 供后端定位。
"""


class ErrorCode:
    """业务错误码：0 表示成功，非 0 按类别递增分配。"""

    OK = 0
    NOT_FOUND = 1001   # 资源不存在
    DUPLICATE = 1002   # 资源冲突（如用户名重复）
    VALIDATION = 1003  # 请求参数校验失败
    WEAK_PASSWORD = 1004  # 弱密码校验不通过
    HEALTH_DB_ERROR = 3001  # 健康检查：数据库连接异常
    INTERNAL = 2001    # 系统内部错误
    UNAUTHORIZED = 2002  # 未认证/无效凭证/无效令牌
    TOKEN_EXPIRED = 2003  # 令牌已过期
    LLM_ERROR = 2004     # LLM 调用失败或返回内容不符合预期


class BusinessError(Exception):
    """业务异常：预期内的业务规则错误。"""

    def __init__(
        self,
        code: int,
        message: str,
        *,
        detail: str | None = None,
        status_code: int = 400,
    ):
        self.code = code
        self.message = message
        self.detail = detail or message
        self.status_code = status_code
        super().__init__(message)


class SystemError(Exception):
    """系统异常：未预期的内部错误，返回通用提示，原始信息进日志。"""

    def __init__(self, message: str = "系统内部错误，请稍后重试", *, detail: str | None = None):
        self.code = ErrorCode.INTERNAL
        self.message = message
        self.detail = detail or message
        self.status_code = 500
        super().__init__(message)
