"""路由层：用户 CRUD 接口定义，统一返回标准化响应结构 ApiResponse。

响应 data 经 UserOut 过滤，确保密码哈希等敏感字段绝不外泄。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..schemas.common import ApiResponse
from ..schemas.user import UserCreate, UserUpdate
from ..services import user_service
from .common import ok, to_out

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED, summary="创建用户")
def create_user(data: UserCreate, db: Session = Depends(get_db)) -> ApiResponse:
    """创建用户，密码经 bcrypt 加密后存储，不保留明文。"""
    return ok(to_out(user_service.create_user(db, data)), "创建成功")


@router.get("", response_model=ApiResponse, summary="查询用户列表")
def list_users(db: Session = Depends(get_db)) -> ApiResponse:
    """返回全部用户（不含密码信息）。"""
    users = [to_out(u) for u in user_service.list_users(db)]
    return ok(users)


@router.get("/{user_id}", response_model=ApiResponse, summary="查询用户详情")
def get_user(user_id: int, db: Session = Depends(get_db)) -> ApiResponse:
    """按 id 查询单个用户。"""
    return ok(to_out(user_service.get_user(db, user_id)))


@router.put("/{user_id}", response_model=ApiResponse, summary="更新用户")
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)) -> ApiResponse:
    """更新用户名/密码，密码变更时重新哈希。"""
    return ok(to_out(user_service.update_user(db, user_id, data)), "更新成功")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除用户")
def delete_user(user_id: int, db: Session = Depends(get_db)) -> None:
    """删除指定用户，成功返回 204 无响应体。"""
    user_service.delete_user(db, user_id)
