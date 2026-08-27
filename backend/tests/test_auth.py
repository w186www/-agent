"""JWT 鉴权冒烟测试：登录、受保护接口、刷新令牌与过期自动重试流程。"""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.exceptions import ErrorCode


def _register(client, username: str = "alice", password: str = "secret123"):
    """注册一个测试用户。"""
    resp = client.post("/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _login(client, username: str = "alice", password: str = "secret123"):
    """登录并返回令牌响应体。"""
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _expired_access_token(user_id: int) -> str:
    """构造一个已过期的访问令牌，用于模拟过期场景。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_login_success(client):
    """登录成功：返回访问令牌与刷新令牌及用户信息。"""
    _register(client)
    data = _login(client)
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "alice"
    assert "password" not in str(data["user"])


def test_login_wrong_password(client):
    """登录：密码错误返回 401。"""
    _register(client)
    resp = client.post("/auth/login", json={"username": "alice", "password": "wrong123"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_login_user_not_found(client):
    """登录：用户不存在返回 401，且提示与密码错误一致（防用户枚举）。"""
    resp = client.post("/auth/login", json={"username": "nobody", "password": "whatever"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_without_token(client):
    """受保护接口：缺少令牌返回 401。"""
    resp = client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_with_valid_token(client):
    """受保护接口：携带有效访问令牌返回当前用户。"""
    user = _register(client)
    data = _login(client)
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == user["id"]
    assert resp.json()["data"]["username"] == "alice"


def test_me_with_invalid_token(client):
    """受保护接口：伪造令牌返回 401。"""
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_with_refresh_token_rejected(client):
    """受保护接口：用刷新令牌冒充访问令牌被拒。"""
    _register(client)
    data = _login(client)
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {data['refresh_token']}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_refresh_token_retry_flow(client):
    """过期自动续期闭环：过期令牌被拒 → 刷新换新 → 重试原请求成功。"""
    user = _register(client)
    data = _login(client)
    user_id = user["id"]

    # 1. 访问令牌已过期，原请求返回 401 TOKEN_EXPIRED
    expired = _expired_access_token(user_id)
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.TOKEN_EXPIRED

    # 2. 客户端自动用刷新令牌换取新访问令牌
    resp = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 200
    new_access = resp.json()["data"]["access_token"]
    assert new_access

    # 3. 携带新访问令牌重试原请求，成功
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "alice"


def test_refresh_with_access_token_rejected(client):
    """刷新接口：用访问令牌冒充刷新令牌被拒。"""
    _register(client)
    data = _login(client)
    resp = client.post("/auth/refresh", json={"refresh_token": data["access_token"]})
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED
