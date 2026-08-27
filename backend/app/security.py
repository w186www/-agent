"""JWT 令牌工具与鉴权依赖。

- 登录时签发访问令牌（Access Token）与刷新令牌（Refresh Token）
- 受保护接口通过 get_current_user 依赖校验 Bearer Token
- 访问令牌过期时，可用刷新令牌调用 /auth/refresh 换发新令牌后重试原请求
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db.models import User
from .db.session import get_db
from .exceptions import BusinessError, ErrorCode

# Bearer Token 提取器：auto_error=False 以便统一返回标准化 401 响应
_bearer = HTTPBearer(auto_error=False)


def _create_token(subject: str, token_type: str, expires: timedelta) -> str:
    """按指定类型与有效期签发 JWT（含 iat/exp/type 声明）。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int) -> str:
    """签发访问令牌，有效期默认 15 分钟。"""
    return _create_token(str(user_id), "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: int) -> str:
    """签发刷新令牌，有效期默认 7 天。"""
    return _create_token(str(user_id), "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str) -> dict:
    """解码并校验 JWT：过期抛 2003，无效/类型不符抛 2002。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise BusinessError(ErrorCode.TOKEN_EXPIRED, "令牌已过期", detail="令牌已过期，请刷新后重试", status_code=401) from exc
    except jwt.InvalidTokenError as exc:
        raise BusinessError(ErrorCode.UNAUTHORIZED, "无效令牌", detail="令牌格式或签名不正确", status_code=401) from exc
    if payload.get("type") != expected_type:
        raise BusinessError(ErrorCode.UNAUTHORIZED, "令牌类型错误", detail="请使用正确的令牌类型", status_code=401)
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """鉴权依赖：校验访问令牌并返回当前登录用户，失败抛 401。"""
    if credentials is None:
        raise BusinessError(ErrorCode.UNAUTHORIZED, "未提供认证凭证", detail="请求头缺少 Bearer Token", status_code=401)
    payload = decode_token(credentials.credentials, "access")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise BusinessError(ErrorCode.UNAUTHORIZED, "用户不存在或已注销", status_code=401)
    return user
