"""用户接口冒烟测试：覆盖健康检查与用户增删改查主流程。"""

from app.db.session import get_db
from app.exceptions import ErrorCode
from app.main import app
from tests.conftest import override_get_db


class _BrokenSession:
    """模拟数据库不可用的会话，用于验证 /health 的 503 逻辑。"""

    def execute(self, *args, **kwargs):
        raise RuntimeError("database connection refused")

    def close(self):
        pass


def _broken_db():
    yield _BrokenSession()


def test_health_ok(client):
    """健康检查：服务与数据库均正常。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "healthy"
    assert body["data"]["database"] == "ok"


def test_health_db_down(client):
    """健康检查：数据库不可用时返回 503。"""
    app.dependency_overrides[get_db] = _broken_db
    try:
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json()["code"] == ErrorCode.HEALTH_DB_ERROR
    finally:
        app.dependency_overrides[get_db] = override_get_db


def test_create_user(client):
    """创建用户：成功返回 201，响应不含任何密码字段。"""
    resp = client.post("/users", json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "alice"
    assert "password" not in str(body["data"])


def test_create_user_duplicate(client):
    """创建用户：用户名重复返回 409。"""
    client.post("/users", json={"username": "alice", "password": "secret123"})
    resp = client.post("/users", json={"username": "alice", "password": "other123"})
    assert resp.status_code == 409
    assert resp.json()["code"] == ErrorCode.DUPLICATE


def test_create_user_invalid_password(client):
    """创建用户：密码过短被参数校验拦截，返回 422。"""
    resp = client.post("/users", json={"username": "bob", "password": "123"})
    assert resp.status_code == 422
    assert resp.json()["code"] == ErrorCode.VALIDATION


def test_list_users(client):
    """查询列表：返回全部用户。"""
    client.post("/users", json={"username": "alice", "password": "secret123"})
    resp = client.get("/users")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


def test_get_user_not_found(client):
    """查询详情：用户不存在返回 404。"""
    resp = client.get("/users/999")
    assert resp.status_code == 404
    assert resp.json()["code"] == ErrorCode.NOT_FOUND


def test_update_user(client):
    """更新用户：修改密码成功。"""
    created = client.post("/users", json={"username": "alice", "password": "secret123"}).json()["data"]
    resp = client.put(f"/users/{created['id']}", json={"password": "newpass888"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["username"] == "alice"


def test_delete_user(client):
    """删除用户：删除成功返回 204，列表清空。"""
    created = client.post("/users", json={"username": "alice", "password": "secret123"}).json()["data"]
    resp = client.delete(f"/users/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/users").json()["data"] == []


def test_register(client):
    """注册：成功返回 201，响应不含任何密码字段。"""
    resp = client.post("/auth/register", json={"username": "carol", "password": "sunny2468"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "carol"
    assert "password" not in str(body["data"])


def test_register_duplicate(client):
    """注册：用户名重复返回 409。"""
    client.post("/auth/register", json={"username": "carol", "password": "sunny2468"})
    resp = client.post("/auth/register", json={"username": "carol", "password": "another88"})
    assert resp.status_code == 409
    assert resp.json()["code"] == ErrorCode.DUPLICATE


def test_register_weak_blacklist(client):
    """注册：命中弱密码黑名单返回 400。"""
    resp = client.post("/auth/register", json={"username": "dave", "password": "123456"})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.WEAK_PASSWORD


def test_register_requires_letter_and_digit(client):
    """注册：纯字母密码被拦截。"""
    resp = client.post("/auth/register", json={"username": "eve", "password": "abcdef"})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.WEAK_PASSWORD


def test_register_password_contains_username(client):
    """注册：密码包含用户名被拦截。"""
    resp = client.post("/auth/register", json={"username": "frank", "password": "frank123"})
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.WEAK_PASSWORD
