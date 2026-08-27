"""会话管理接口测试：列表分页、新建、改标题、删除级联、消息分页与 task_id 解析。"""

import time

from sqlalchemy import select

from app.db.models import (
    AssessmentRecord,
    BiddingTask,
    ChatMessage,
    ChatSession,
    KbChunk,
    KbDocument,
    Resource,
)


def _register(client, username: str = "session_user", password: str = "secret123"):
    resp = client.post("/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text


def _login(client, username: str = "session_user", password: str = "secret123") -> tuple[str, int]:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return data["access_token"], data["user"]["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_session(client, token: str, intent_type: int = 0, role_type: int = 0) -> dict:
    resp = client.post(
        "/sessions",
        headers=_auth(token),
        json={"role_type": role_type, "intent_type": intent_type},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_session_crud(client):
    """会话列表分页 / 新建 / 改标题 / 删除，按角色筛选与归属校验。"""
    _register(client)
    token, _ = _login(client)
    h = _auth(token)

    # 新建商务会话（intent=1 招投标，默认标题）
    data = _create_session(client, token, intent_type=1, role_type=0)
    sid = data["id"]
    assert data["title"] == "招投标任务"
    assert data["intent_type"] == 1

    # 列表按 role_type 筛选
    resp = client.get("/sessions", headers=h, params={"role_type": 0})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert any(s["id"] == sid for s in body["items"])
    assert body["total"] >= 1

    # 改标题
    resp = client.put(f"/sessions/{sid}", headers=h, json={"title": "改后的标题"})
    assert resp.json()["data"]["title"] == "改后的标题"

    # 删除后不可再查
    resp = client.delete(f"/sessions/{sid}", headers=h)
    assert resp.status_code == 200
    resp = client.get(f"/sessions/{sid}/messages", headers=h)
    assert resp.status_code == 404


def test_messages_pagination_and_task_payload(client, db_session):
    """消息游标/偏移两种分页 + intent_type/task_id 解析（intent_type=1 招投标）。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _create_session(client, token, intent_type=1)["id"]

    now = int(time.time())
    for i in range(25):
        db_session.add(ChatMessage(
            user_id=uid, session_id=sid, role=i % 2, request_id=f"r{i}",
            content=f"消息{i}", created_at=now + i,
            tool_calls=[{"name": "search_tender", "arguments": {"q": i}, "duration_ms": 123}] if i == 3 else None,
        ))
    task = BiddingTask(
        user_id=uid, session_id=sid, tender_title="XX项目", status=3,
        bidding_sections={"商务部分": "内容A"},
        compliance_result=[{"item": "资质", "type": "资格", "status": "danger", "detail": "缺证书"}],
        reference_doc_ids=[11, 22], created_at=now, updated_at=now,
    )
    db_session.add(task)
    db_session.commit()
    task_id = task.id

    # 游标分页：返回最近 limit 条且时间正序、翻页无重复
    resp = client.get(f"/sessions/{sid}/messages", headers=h, params={"limit": 10})
    body = resp.json()["data"]
    ids = [m["id"] for m in body["items"]]
    assert len(ids) == 10 and ids == sorted(ids)
    assert body["has_more"] is True
    resp2 = client.get(f"/sessions/{sid}/messages", headers=h, params={"limit": 10, "before_id": body["before_id"]})
    assert all(m["id"] < body["before_id"] for m in resp2.json()["data"]["items"])

    # 偏移分页：page/page_size + created_at 升序
    resp3 = client.get(f"/sessions/{sid}/messages", headers=h, params={"page": 2, "page_size": 10})
    body3 = resp3.json()["data"]
    assert body3["total"] == 25
    assert body3["page"] == 2 and len(body3["items"]) == 10
    assert body3["has_more"] is True

    # 每条消息附带 intent_type=1 与 task_id（bidding_tasks 的 id+status）
    for m in body["items"]:
        assert m["intent_type"] == 1
        assert m["task_id"] == {"id": task_id, "status": 3}

    # 全量拉取验证 tool_calls 透传
    resp4 = client.get(f"/sessions/{sid}/messages", headers=h, params={"limit": 50})
    tooled = [m for m in resp4.json()["data"]["items"] if m.get("tool_calls")]
    assert tooled and tooled[0]["tool_calls"][0]["name"] == "search_tender"


def test_messages_task_payload_assessment(client, db_session):
    """intent_type=2：task_id 为该会话下 assessment_records 摘要列表。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _create_session(client, token, intent_type=2)["id"]

    now = int(time.time())
    db_session.add(ChatMessage(user_id=uid, session_id=sid, role=0, request_id="r0", content="开始测评", created_at=now))
    db_session.add(AssessmentRecord(
        user_id=uid, session_id=sid, system_level=1, checklist_code="8.1.4.1",
        checklist_name="身份鉴别", status=3, confidence=0.92,
        vlm_analysis={"识别": "已配置"}, human_record="人工记录",
        comparison_result={"consistent": True}, kb_references=[{"title": "企业特殊说明"}],
        created_at=now, updated_at=now,
    ))
    db_session.add(AssessmentRecord(
        user_id=uid, session_id=sid, system_level=1, checklist_code="8.1.4.2",
        checklist_name="访问控制", status=4, confidence=0.55, created_at=now, updated_at=now,
    ))
    db_session.commit()

    resp = client.get(f"/sessions/{sid}/messages", headers=h)
    body = resp.json()["data"]
    item = body["items"][0]
    assert item["intent_type"] == 2
    task_id = item["task_id"]
    assert len(task_id) == 2
    first = next(r for r in task_id if r["checklist_code"] == "8.1.4.1")
    assert first == {"id": first["id"], "status": 3, "checklist_code": "8.1.4.1",
                     "checklist_name": "身份鉴别", "confidence": 0.92}

    # 记录详情返回 kb_references
    resp = client.get(f"/assessment_records/{first['id']}", headers=h)
    detail = resp.json()["data"]
    assert detail["kb_references"][0]["title"] == "企业特殊说明"
    assert detail["confidence"] == 0.92


def test_delete_session_cascades_resources(client, db_session):
    """删除会话：级联删除消息/任务，并清理 tool_calls 引用的 resources 元数据。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _create_session(client, token, intent_type=0)["id"]

    now = int(time.time())
    db_session.add(ChatMessage(
        user_id=uid, session_id=sid, role=1, request_id="r0", content="AI 回复",
        created_at=now,
        tool_calls=[{"name": "upload_file", "arguments": {"resource_id": 1001}},
                    {"name": "parse_doc", "result": {"resource_id": 1002}}],
    ))
    db_session.add(Resource(
        id=1001, resource_type=0, storage_scene=0, upload_purpose=0,
        file_name="a.docx", file_hash="h1", storage_path="minio://dengbao/users/1/h1.docx",
        user_id=uid, created_at=now,
    ))
    db_session.add(Resource(
        id=1002, resource_type=0, storage_scene=0, upload_purpose=0,
        file_name="b.pdf", file_hash="h2", storage_path="minio://dengbao/users/1/h2.pdf",
        user_id=uid, created_at=now,
    ))
    # 未被引用的资源应保留
    db_session.add(Resource(
        id=2001, resource_type=0, storage_scene=0, upload_purpose=0,
        file_name="keep.xlsx", file_hash="h3", storage_path="minio://dengbao/users/1/h3.xlsx",
        user_id=uid, created_at=now,
    ))
    db_session.commit()

    resp = client.delete(f"/sessions/{sid}", headers=h)
    assert resp.status_code == 200

    assert db_session.get(ChatSession, sid) is None
    assert db_session.scalar(select(ChatMessage).where(ChatMessage.session_id == sid)) is None
    # tool_calls 引用的资源元数据已被级联删除，未引用的保留
    assert db_session.get(Resource, 1001) is None
    assert db_session.get(Resource, 1002) is None
    assert db_session.get(Resource, 2001) is not None


def test_messages_reference_sources_enrich(client, db_session):
    """知识问答消息：历史接口按 reference_sources 回查重拼完整 sources；切片删除时给提示。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _create_session(client, token, intent_type=3)["id"]

    doc = KbDocument(kb_type=1, doc_title="企业制度", user_id=uid,
                     file_path="s3://u1/doc.docx", chunk_count=0)
    db_session.add(doc)
    db_session.commit()
    chunk = KbChunk(doc_id=doc.id, vector_id="v-1", chunk_index=0,
                    content="特殊情况说明内容", char_count=8)
    db_session.add(chunk)
    db_session.commit()

    now = int(time.time())
    db_session.add(ChatMessage(
        user_id=uid, session_id=sid, role=1, request_id="a1", content="回答",
        reference_sources=[
            {"chunk_id": chunk.id, "score": 0.85},
            {"chunk_id": 9999, "score": 0.4},  # 9999 对应切片已删除
        ],
        created_at=now,
    ))
    db_session.commit()

    resp = client.get(f"/sessions/{sid}/messages", headers=h)
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    msg = next(m for m in items if m["role"] == 1)
    assert len(msg["sources"]) == 2
    by_id = {s["chunk_id"]: s for s in msg["sources"]}
    assert by_id[chunk.id]["file_name"] == "doc.docx"
    assert by_id[chunk.id]["resource_id"] == doc.id
    assert by_id[chunk.id]["text"] == "特殊情况说明内容"
    assert by_id[chunk.id]["score"] == 0.85
    assert by_id[9999]["text"] == "该参考片段已被删除"
