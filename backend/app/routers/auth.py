"""路由层：认证相关接口（注册 / 登录 / 刷新令牌 / 当前用户）。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import User
from ..db.session import get_db
from ..schemas.auth import RefreshRequest, UserLogin
from ..schemas.common import ApiResponse
from ..schemas.user import UserCreate, UserOut
from ..security import create_access_token, create_refresh_token, decode_token, get_current_user
from ..services import user_service
from .common import ok, to_out

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED, summary="注册")
def register(data: UserCreate, db: Session = Depends(get_db)) -> ApiResponse:
    """注册用户：复用用户创建业务逻辑，密码经 bcrypt 加密入库，不保留明文。"""
    return ok(to_out(user_service.create_user(db, data)), "注册成功")


@router.post("/login", response_model=ApiResponse, summary="登录")
def login(data: UserLogin, db: Session = Depends(get_db)) -> ApiResponse:
    """用户名密码登录：签发访问令牌与刷新令牌。"""
    user = user_service.authenticate(db, data.username, data.password)
    return ok(_token_payload(user), "登录成功")


@router.post("/refresh", response_model=ApiResponse, summary="刷新访问令牌")
def refresh(data: RefreshRequest) -> ApiResponse:
    """访问令牌过期后，用刷新令牌换发新访问令牌，客户端可重试原请求。"""
    payload = decode_token(data.refresh_token, "refresh")
    user_id = int(payload["sub"])
    return ok(
        {
            "access_token": create_access_token(user_id),
            "refresh_token": data.refresh_token,
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,
        },
        "刷新成功",
    )


@router.get("/me", response_model=ApiResponse, summary="当前登录用户")
def me(current_user: User = Depends(get_current_user)) -> ApiResponse:
    """受保护接口示例：校验访问令牌并返回当前登录用户信息。"""
    return ok(to_out(current_user))


def _token_payload(user: User) -> dict:
    """组装登录响应：访问令牌 + 刷新令牌 + 用户信息。"""
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": UserOut.model_validate(user).model_dump(),
    }
