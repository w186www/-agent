"""业务层：用户增删改查业务逻辑与密码加密。

- 业务规则错误统一抛 BusinessError，由全局异常处理器转换为标准化响应；
- 数据库会话由路由层通过依赖注入传入，业务层只负责规则与编排。
"""

from sqlalchemy.orm import Session

from ..db import user_db
from ..exceptions import BusinessError, ErrorCode
from ..schemas.user import UserCreate, UserUpdate

# bcrypt 密码哈希上下文
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 常见弱密码黑名单
_WEAK_PASSWORDS = frozenset({
    "password", "password1", "password123", "123456", "1234567", "12345678",
    "123456789", "1234567890", "123123", "123321", "111111", "222222",
    "333333", "666666", "888888", "000000", "abc123", "qwerty", "qwerty123",
    "letmein", "admin", "admin123", "root", "welcome", "iloveyou",
    "1qaz2wsx", "123qwe", "a123456", "654321", "1234", "12345", "qwe123",
})


def hash_password(plain: str) -> str:
    """对明文密码做 bcrypt 哈希，存储时不保留明文。"""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    return pwd_context.verify(plain, hashed)


def _validate_password_strength(username: str, password: str) -> None:
    """弱密码校验：黑名单 / 必须同时包含字母与数字 / 禁止包含用户名。"""
    lowered = password.lower()
    if lowered in _WEAK_PASSWORDS:
        raise BusinessError(ErrorCode.WEAK_PASSWORD, "密码强度过弱，请更换", status_code=400)
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise BusinessError(ErrorCode.WEAK_PASSWORD, "密码必须同时包含字母和数字", status_code=400)
    if username.lower() in lowered:
        raise BusinessError(ErrorCode.WEAK_PASSWORD, "密码不能包含用户名", status_code=400)


def _ensure_username_free(db: Session, username: str, exclude_id: int | None = None) -> None:
    """校验用户名唯一性（更新时可排除自身），冲突抛业务异常。"""
    exist = user_db.get_by_username(db, username)
    if exist and exist.id != exclude_id:
        raise BusinessError(ErrorCode.DUPLICATE, "用户名已存在", status_code=409)


def create_user(db: Session, data: UserCreate):
    """创建用户：唯一性校验 + 弱密码校验 + 密码哈希后入库。"""
    _ensure_username_free(db, data.username)
    _validate_password_strength(data.username, data.password)
    return user_db.create(db, username=data.username, password_hash=hash_password(data.password))


def get_user(db: Session, user_id: int):
    """查询单个用户，不存在抛业务异常。"""
    user = user_db.get_by_id(db, user_id)
    if user is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "用户不存在", status_code=404)
    return user


def list_users(db: Session) -> list:
    """查询全部用户。"""
    return user_db.list_all(db)


def update_user(db: Session, user_id: int, data: UserUpdate):
    """更新用户：先确认存在，再处理字段变更（密码变更时重新哈希）。"""
    user = get_user(db, user_id)  # 不存在则抛 404
    fields: dict = {}
    if data.username is not None:
        _ensure_username_free(db, data.username, exclude_id=user_id)
        fields["username"] = data.username
    if data.password is not None:
        # 与注册保持一致的弱密码校验，防止通过更新接口绕过规则
        _validate_password_strength(data.username or user.username, data.password)
        fields["password_hash"] = hash_password(data.password)
    return user_db.update(db, user, **fields)


def delete_user(db: Session, user_id: int) -> None:
    """删除用户，不存在抛业务异常。"""
    user = get_user(db, user_id)
    user_db.delete(db, user)


def authenticate(db: Session, username: str, password: str):
    """登录校验：用户名与密码都正确才返回用户，否则统一抛 401（避免用户枚举）。"""
    user = user_db.get_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        raise BusinessError(ErrorCode.UNAUTHORIZED, "用户名或密码错误", status_code=401)
    return user
