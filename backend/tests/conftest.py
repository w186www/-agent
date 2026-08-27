"""pytest 公共配置：用 SQLite 内存库替换 MySQL，保证测试隔离、不污染真实数据。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app

# 测试专用 SQLite 内存引擎（StaticPool 保证多会话共享同一连接）
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    """覆盖 FastAPI 依赖：测试使用内存库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client():
    """每个测试用例独立重建表结构，保证用例之间互不影响。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session():
    """直接访问测试库的会话（与 API 同库，用于造数据与断言）。"""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
