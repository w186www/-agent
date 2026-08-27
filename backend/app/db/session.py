"""数据库层：SQLAlchemy 引擎与会话管理。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings

# 数据库引擎：pool_pre_ping 检测失效连接，pool_recycle 防止 MySQL 超时断连
engine = create_engine(settings.mysql_url, pool_pre_ping=True, pool_recycle=3600)

# 会话工厂：expire_on_commit=False 使提交后仍可访问模型属性
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI 依赖：提供请求级数据库会话，请求结束后自动关闭。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
