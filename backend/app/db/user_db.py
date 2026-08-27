"""数据库层：基于 SQLAlchemy 会话的用户表增删改查。

所有函数显式接收 Session 参数，由上层（路由依赖）统一管理会话生命周期。
返回值为 ORM 模型对象，供业务层/路由层使用。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


def create(db: Session, username: str, password_hash: str) -> User:
    """插入一条用户记录并提交。"""
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_by_id(db: Session, user_id: int) -> Optional[User]:
    """按 id 查询用户，不存在返回 None。"""
    return db.get(User, user_id)


def get_by_username(db: Session, username: str) -> Optional[User]:
    """按用户名查询用户，用于唯一性校验。"""
    stmt = select(User).where(User.username == username)
    return db.scalar(stmt)


def list_all(db: Session) -> list[User]:
    """返回全部用户。"""
    stmt = select(User).order_by(User.id)
    return list(db.scalars(stmt))


def update(db: Session, user: User, **fields) -> User:
    """按字段更新指定用户并提交。"""
    for key, value in fields.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


def delete(db: Session, user: User) -> None:
    """删除指定用户并提交。"""
    db.delete(user)
    db.commit()
