"""流式聊天（SSE）与人工审核接口测试。

- /chat/stream：按意图类型验证事件序列（token/tool_call/task_created/hitl/done/error）与消息落库；
- /review/{review_task_id}：审核结果提交、源任务状态联动、重复审核与归属校验。
"""

import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import routers
from app.db.models import (
    AssessmentRecord,
    BiddingTask,
    ChatMessage,
    ChatSession,
    ReviewTask,
)

cs = routers.chat_stream


class FakeChain:
    """替代 build_chain 返回值的假链路：stream 产出固定分片。"""

    def stream(self, variables: dict):
        for piece in ["这是", "流式回复"]:
            yield piece

    async def astream(self, variables: dict):
        for piece in ["这是", "流式回复"]:
            yield piece


# 未显式指定 next_pending 时保持 pending 不变（区别于"resume 后图结束"的 None）
_UNSET = object()


class FakeBiddingGraph:
    """替代 build_bidding_graph 返回值的假图：可编程产出 LangGraph v2 事件与中断点。

    - events：astream_events 依次产出的事件列表；
    - pending：get_state 返回的中断节点（next[0]），None 表示图已结束；
    - next_pending：resume 后切换到的新中断点；不传则保持 pending 不变，
      传 None 表示 resume 后图结束（pending 置空）；
    - values：get_state 返回的图状态字段。
    """

    def __init__(self, events: list[dict] | None = None, pending=None, next_pending=_UNSET, values: dict | None = None):
        self.events = events or []
        self.pending = pending
        self.next_pending = next_pending
        self.values = values or {}
        self.resumed_command = None

    async def astream_events(self, state, config=None, version="v2"):
        self.resumed_command = state
        for ev in self.events:
            yield ev
        if self.next_pending is not _UNSET:
            self.pending = self.next_pending

    def get_state(self, config):
        return SimpleNamespace(next=self.pending, values=self.values)


def _tool_events(name: str, args: dict, result: str) -> list[dict]:
    """构造一组 on_tool_start / on_tool_end 事件（对应一次工具调用）。"""
    run_id = f"run-{name}"
    return [
        {"event": "on_tool_start", "run_id": run_id, "name": name, "data": {"input": args}},
        {"event": "on_tool_end", "run_id": run_id, "name": name, "data": {"output": result}},
    ]


def _token_event(content: str) -> dict:
    return {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content=content)}}


# 招标解析结果 / 标书生成 / 自检结果样例（与 tools.py 输出结构对齐）
PARSE_RESULT = {
    "project_name": "XX市公安局等保测评项目",
    "budget": 800000,
    "deadline": "2026-09-01",
    "qualification_requirements": ["具备网络安全等级保护测评机构推荐证书"],
    "scoring_items": ["商务分30分，技术分50分，价格分20分"],
    "disqualification_items": ["投标保证金未到账", "投标文件未按时递交"],
}

BIDDING_SECTIONS = {
    "company_profile": "公司成立于2015年，专注网络安全等级保护测评服务。",
    "qualification": "具备网络安全等级保护测评机构推荐证书。",
    "project_team": "项目经理1名，持有CISP证书。",
    "pricing": "（待人工审核）",
}

COMPLIANCE_RESULT = {
    "overall_status": "pass",
    "disqualification_check": [
        {"item": "投标保证金比例", "type": "废标项", "status": "pass", "detail": "已包含保证金缴纳承诺"},
    ],
    "format_check": [{"item": "文件格式", "status": "pass", "detail": "符合招标文件要求"}],
    "typo_check": [],
    "summary": "共检查4项，通过4项，警告0项，危险0项",
}


def _register(client, username: str = "stream_user", password: str = "secret123"):
    resp = client.post("/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text


def _login(client, username: str = "stream_user", password: str = "secret123") -> tuple[str, int]:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return data["access_token"], data["user"]["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_session(client, token: str, intent_type: int = 0) -> int:
    resp = client.post("/sessions", headers=_auth(token), json={"role_type": 0, "intent_type": intent_type})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


def _patch_chain(monkeypatch, graph: FakeBiddingGraph | None = None):
    """mock 链路：不调用真实 DeepSeek / Tavily / Qdrant。"""
    monkeypatch.setattr(cs, "get_deepseek", lambda: object())
    monkeypatch.setattr(cs, "build_chain", lambda llm, prompt: FakeChain())
    monkeypatch.setattr(cs, "build_bidding_graph", lambda: graph or FakeBiddingGraph())
    monkeypatch.setattr(cs, "get_session_memory", lambda *a, **k: SimpleNamespace(
        load_memory_variables=lambda *a2, **k2: {"history": ""},
        buffer_as_messages=[],
        chat_memory=SimpleNamespace(messages=[]),
    ))
    monkeypatch.setattr(cs, "get_rag_context", lambda q, kt, top_k=None: [])


def _parse_sse(resp) -> list[dict]:
    events = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_stream_chat_dialog(client, db_session):
    """intent=0 对话链路：token 拼接 + done，用户/AI 消息落库。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _make_session(client, token, intent_type=0)
    _patch_chain(pytest.MonkeyPatch())

    resp = client.post("/chat/stream", headers=h, json={
        "session_id": sid, "content": "你好", "role": 0, "intent_type": 0,
    })
    assert resp.status_code == 200
    events = _parse_sse(resp)
    types = [e["type"] for e in events]
    assert types == ["token", "token", "done"]
    assert "".join(e["content"] for e in events if e["type"] == "token") == "这是流式回复"

    # 消息落库：用户 + AI
    messages = db_session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == sid).order_by(ChatMessage.id)
    ).all()
    assert [m.role for m in messages] == [0, 1]
    assert messages[0].content == "你好"
    assert messages[1].content == "这是流式回复"
    assert messages[1].tool_calls in (None, [])


def test_stream_bidding(client, db_session):
    """intent=1 招投标链路（搜索→解析）：tool_call -> task_created -> hitl(解析确认) -> done。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _make_session(client, token, intent_type=1)
    search_result = json.dumps([
        {"title": "XX市公安局等保测评采购公告", "url": "https://example.com/1",
         "published_date": "2026-08-05", "score": 0.95, "content": "项目预算80万元"},
    ], ensure_ascii=False)
    events = [
        *_tool_events("search_tender", {"keyword": "XX项目招标"}, search_result),
        *_tool_events("parse_tender", {"file_path": "tender.pdf"}, json.dumps(PARSE_RESULT, ensure_ascii=False)),
        _token_event("已解析招标文件，请确认解析结果"),
    ]
    _patch_chain(pytest.MonkeyPatch(), FakeBiddingGraph(events=events, pending=["review_parsed"], values={"tender_parsed": True}))

    resp = client.post("/chat/stream", headers=h, json={
        "session_id": sid, "content": "编写XX项目投标文件", "role": 0, "intent_type": 1,
    })
    events = _parse_sse(resp)
    types = [e["type"] for e in events]
    assert "tool_call" in types and "task_created" in types and "hitl" in types and "done" in types

    tool_event = next(e for e in events if e["type"] == "tool_call")
    assert tool_event["payload"]["tool_name"] == "search_tender"

    task_event = next(e for e in events if e["type"] == "task_created")
    task_payload = task_event["payload"]["task_id"]
    assert task_event["payload"]["intent_type"] == 1

    hitl_event = next(e for e in events if e["type"] == "hitl")
    assert hitl_event["payload"]["task_type"] == 2  # 解析结果确认
    assert hitl_event["payload"]["review_task_id"] is not None
    assert hitl_event["payload"]["review_data"]["project_name"] == "XX市公安局等保测评项目"

    # bidding_tasks 创建，标题取搜索结果首条，状态=1 已解析待确认
    task = db_session.scalar(select(BiddingTask).where(BiddingTask.session_id == sid))
    assert task is not None and task.status == 1
    assert task.tender_title == "XX市公安局等保测评采购公告"
    assert task.reference_doc_ids == []
    # review_tasks 创建
    review = db_session.scalar(select(ReviewTask).where(ReviewTask.session_id == sid))
    assert review is not None and review.task_type == 2 and review.status == 0
    # AI 消息带 tool_calls
    ai_msg = db_session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == sid, ChatMessage.role == 1)
    ).one()
    assert ai_msg.tool_calls[0]["name"] == "search_tender"


def test_stream_bidding_selfcheck(client, db_session):
    """intent=1 自检 HITL 链路：generate/self_check 节点事件 -> hitl(自检审核 task_type=3) -> done。

    覆盖规格验证标准 6-11：标书生成后自动触发自检，SSE 推送 generate_bidding/self_check
    工具事件，自检完成推送 task_type=selfcheck_review 的 hitl 事件。
    """
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _make_session(client, token, intent_type=1)
    events = [
        {"event": "on_chain_start", "name": "generate", "data": {}},
        {"event": "on_chain_end", "name": "generate", "data": {"output": {
            "messages": [SimpleNamespace(content="投标文件已生成，正在进行废标自检…")],
            "bidding_sections": BIDDING_SECTIONS,
        }}},
        {"event": "on_chain_start", "name": "selfcheck", "data": {}},
        {"event": "on_chain_end", "name": "selfcheck", "data": {"output": {
            "messages": [SimpleNamespace(content="废标自检完成，等待人工审核。")],
            "compliance_result": COMPLIANCE_RESULT,
        }}},
    ]
    _patch_chain(pytest.MonkeyPatch(), FakeBiddingGraph(
        events=events, pending=["review_selfcheck"],
        values={"bidding_sections": BIDDING_SECTIONS, "compliance_result": COMPLIANCE_RESULT},
    ))

    resp = client.post("/chat/stream", headers=h, json={
        "session_id": sid, "content": "开始编写投标文件", "role": 0, "intent_type": 1,
    })
    events = _parse_sse(resp)
    types = [e["type"] for e in events]
    assert "tool_call" in types and "task_created" in types and "hitl" in types and "done" in types

    tool_names = [e["payload"]["tool_name"] for e in events if e["type"] == "tool_call"]
    assert "generate_bidding" in tool_names and "self_check" in tool_names

    hitl_event = next(e for e in events if e["type"] == "hitl")
    assert hitl_event["payload"]["task_type"] == 3  # 自检审核
    assert hitl_event["payload"]["review_data"]["bidding_sections"] == BIDDING_SECTIONS
    assert hitl_event["payload"]["review_data"]["compliance_result"] == COMPLIANCE_RESULT

    # bidding_tasks 状态=4 待人工审核，写入生成内容与自检结果
    task = db_session.scalar(select(BiddingTask).where(BiddingTask.session_id == sid))
    assert task is not None and task.status == 4
    assert task.bidding_sections == BIDDING_SECTIONS
    assert task.compliance_result == COMPLIANCE_RESULT
    review = db_session.scalar(select(ReviewTask).where(ReviewTask.session_id == sid))
    assert review is not None and review.task_type == 3 and review.status == 0


def test_stream_assessment(client, db_session):
    """intent=2 测评核查链路：Agent 自主调用 generate_checklist -> task_created(控制点列表) -> done。

    本轮不做 HITL（低置信度仅标记 status=4）；清单写库由 checklist 节点执行，
    测试中以预置记录模拟（图节点内部走真实 SessionLocal，测试环境不触发）。
    """
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _make_session(client, token, intent_type=2)
    now = int(time.time())
    db_session.add_all([
        AssessmentRecord(user_id=uid, session_id=sid, system_level=1,
                         checklist_code="8.1.4.1", checklist_name="身份鉴别",
                         assessment_command="Windows: net accounts\nLinux: cat /etc/login.defs | grep PASS",
                         status=0, confidence=0.0, created_at=now, updated_at=now),
        AssessmentRecord(user_id=uid, session_id=sid, system_level=1,
                         checklist_code="8.1.4.2", checklist_name="访问控制",
                         assessment_command="Windows: icacls C:\\\nLinux: ls -la /etc/passwd",
                         status=0, confidence=0.0, created_at=now, updated_at=now),
    ])
    db_session.commit()

    events = [
        _token_event("好的，正在根据等保三级要求生成测评清单…"),
        *_tool_events("generate_checklist", {"system_level": "三级", "system_name": "XX业务系统"},
                      json.dumps({
                          "system_level": "三级", "system_name": "XX业务系统",
                          "checklist": [{"checklist_code": "8.1.4.1", "checklist_name": "身份鉴别"}],
                          "total_count": 1,
                      }, ensure_ascii=False)),
    ]
    _patch_chain(pytest.MonkeyPatch())
    pytest.MonkeyPatch().setattr(cs, "build_assessment_graph", lambda: FakeBiddingGraph(events=events))

    resp = client.post("/chat/stream", headers=h, json={
        "session_id": sid, "content": "开始XX业务系统等保三级测评", "role": 0, "intent_type": 2,
    })
    assert resp.status_code == 200
    resp_events = _parse_sse(resp)
    types = [e["type"] for e in resp_events]
    assert "token" in types and "tool_call" in types and "task_created" in types and "done" in types
    assert "hitl" not in types  # 本轮不做 HITL

    tool_event = next(e for e in resp_events if e["type"] == "tool_call")
    assert tool_event["payload"]["tool_name"] == "generate_checklist"

    task_event = next(e for e in resp_events if e["type"] == "task_created")
    assert task_event["payload"]["intent_type"] == 2
    records_payload = task_event["payload"]["task_id"]
    assert len(records_payload) == 2
    assert [r["checklist_code"] for r in records_payload] == ["8.1.4.1", "8.1.4.2"]

    # AI 消息落库：正文 + generate_checklist 工具调用记录
    ai_msg = db_session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == sid, ChatMessage.role == 1)
    ).one()
    assert ai_msg.tool_calls[0]["name"] == "generate_checklist"


def test_stream_session_not_found(client):
    """会话不存在：直接返回 404，而非 SSE 错误事件。"""
    _register(client)
    token, _ = _login(client)
    resp = client.post("/chat/stream", headers=_auth(token), json={
        "session_id": 99999, "content": "hi", "role": 0, "intent_type": 0,
    })
    assert resp.status_code == 404


def test_review_approve_updates_source(client, db_session):
    """审核通过：review_tasks 标记已审核，招投标任务推进到已完成。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _make_session(client, token, intent_type=1)
    now = int(time.time())
    task = BiddingTask(user_id=uid, session_id=sid, tender_title="项目", status=4, created_at=now, updated_at=now)
    db_session.add(task)
    db_session.commit()
    review = ReviewTask(
        user_id=uid, session_id=sid, task_type=0, source_type=0, source_id=task.id,
        review_data={"pricing_section": "xxx", "ai_suggestion": "yyy"}, status=0, created_at=now,
    )
    db_session.add(review)
    db_session.commit()
    review_id = review.id

    resp = client.post(f"/review/{review_id}", headers=h, json={"action": "approve", "comment": "同意"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["review_result"] == 0 and data["source_status"] == 5

    db_session.refresh(review)
    db_session.refresh(task)
    assert review.status == 1 and review.review_result == 0 and review.review_comment == "同意"
    assert task.status == 5


def test_review_reject_returns_to_pending(client, db_session):
    """审核驳回：测评核查记录退回待人工复核，重复审核被拒绝。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _make_session(client, token, intent_type=2)
    now = int(time.time())
    record = AssessmentRecord(
        user_id=uid, session_id=sid, system_level=1, checklist_code="8.1.4.1",
        checklist_name="身份鉴别", status=4, confidence=0.5, created_at=now, updated_at=now,
    )
    db_session.add(record)
    db_session.commit()
    review = ReviewTask(
        user_id=uid, session_id=sid, task_type=1, source_type=1, source_id=record.id,
        review_data={"confidence": 0.5}, status=0, created_at=now,
    )
    db_session.add(review)
    db_session.commit()
    review_id = review.id

    resp = client.post(f"/review/{review_id}", headers=h, json={"action": "reject", "comment": "证据不足"})
    assert resp.status_code == 200
    db_session.refresh(record)
    assert record.status == 4  # 驳回保持待人工复核

    # 重复审核 -> 业务错误
    resp = client.post(f"/review/{review_id}", headers=h, json={"action": "approve"})
    assert resp.status_code == 400


def test_review_not_found_and_ownership(client, db_session):
    """审核任务不存在或非本人 -> 404。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    resp = client.post("/review/99999", headers=h, json={"action": "approve"})
    assert resp.status_code == 404

    # 他人创建的审核任务
    _register(client, username="other_user")
    other_token, other_uid = _login(client, username="other_user")
    now = int(time.time())
    sid = _make_session(client, other_token, intent_type=0)
    review = ReviewTask(
        user_id=other_uid, session_id=sid, task_type=0, source_type=0, source_id=1,
        review_data={}, status=0, created_at=now,
    )
    db_session.add(review)
    db_session.commit()
    resp = client.post(f"/review/{review.id}", headers=h, json={"action": "approve"})
    assert resp.status_code == 404


def _setup_selfcheck_review(client, db_session, token, uid) -> tuple[int, int, dict]:
    """构造处于第二个 HITL（review_selfcheck）的会话：bidding_task(status=4) + review_task(task_type=3)。"""
    sid = _make_session(client, token, intent_type=1)
    now = int(time.time())
    task = BiddingTask(
        user_id=uid, session_id=sid, tender_title="项目", status=4,
        bidding_sections=BIDDING_SECTIONS, compliance_result=COMPLIANCE_RESULT,
        created_at=now, updated_at=now,
    )
    db_session.add(task)
    db_session.commit()
    review = ReviewTask(
        user_id=uid, session_id=sid, task_type=3, source_type=0, source_id=task.id,
        review_data={"bidding_sections": BIDDING_SECTIONS, "compliance_result": COMPLIANCE_RESULT},
        status=0, created_at=now,
    )
    db_session.add(review)
    db_session.commit()
    return sid, task.id, review.id


def test_resume_selfcheck_approve(client, db_session):
    """第二个 HITL 恢复：自检审核通过 -> bidding_tasks.status=5，审核任务标记已通过。

    覆盖规格验证标准 13：用户点击「通过」→ status 更新为 5（已完成），图结束。
    """
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid, task_id, review_id = _setup_selfcheck_review(client, db_session, token, uid)
    graph = FakeBiddingGraph(
        pending=["review_selfcheck"], next_pending=None,
        values={"selfcheck_approved": True, "bidding_sections": BIDDING_SECTIONS,
                "compliance_result": COMPLIANCE_RESULT},
    )
    _patch_chain(pytest.MonkeyPatch(), graph)

    resp = client.post(f"/chat/req-{sid}-1/resume", headers=h, json={
        "session_id": sid, "review_type": "selfcheck_review", "approved": True,
    })
    assert resp.status_code == 200
    events = _parse_sse(resp)
    assert events[-1]["type"] == "done"

    task = db_session.get(BiddingTask, task_id)
    review = db_session.get(ReviewTask, review_id)
    assert task.status == 5
    assert review.status == 1 and review.review_result == 0


def test_resume_selfcheck_modified(client, db_session):
    """第二个 HITL 恢复：修改后通过 -> modified_sections 覆盖 bidding_sections，status=5。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid, task_id, review_id = _setup_selfcheck_review(client, db_session, token, uid)
    modified = dict(BIDDING_SECTIONS, pricing="（待人工审核，预计50万元）")
    graph = FakeBiddingGraph(
        pending=["review_selfcheck"], next_pending=None,
        values={"selfcheck_approved": True, "bidding_sections": BIDDING_SECTIONS,
                "compliance_result": COMPLIANCE_RESULT},
    )
    _patch_chain(pytest.MonkeyPatch(), graph)

    resp = client.post(f"/chat/req-{sid}-1/resume", headers=h, json={
        "session_id": sid, "review_type": "selfcheck_review", "approved": True,
        "modified_sections": modified,
    })
    assert resp.status_code == 200
    events = _parse_sse(resp)
    assert events[-1]["type"] == "done"

    task = db_session.get(BiddingTask, task_id)
    review = db_session.get(ReviewTask, review_id)
    assert task.status == 5
    assert task.bidding_sections["pricing"] == "（待人工审核，预计50万元）"
    assert review.status == 1 and review.review_result == 2


def test_resume_selfcheck_reject_regenerates(client, db_session):
    """第二个 HITL 恢复：自检审核驳回 -> 图重新生成并再次中断，status=4，推送新一轮审核卡片。

    覆盖规格验证标准 14：用户点击「驳回」→ 图回到 generate 重新生成，status 回到 4 待人工审核。
    """
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid, task_id, review_id = _setup_selfcheck_review(client, db_session, token, uid)
    regenerated = dict(BIDDING_SECTIONS, qualification="具备网络安全等级保护测评机构推荐证书（补充）。")
    graph = FakeBiddingGraph(
        pending=["review_selfcheck"], next_pending=["review_selfcheck"],
        values={"bidding_sections": regenerated, "compliance_result": COMPLIANCE_RESULT},
    )
    _patch_chain(pytest.MonkeyPatch(), graph)

    resp = client.post(f"/chat/req-{sid}-1/resume", headers=h, json={
        "session_id": sid, "review_type": "selfcheck_review", "approved": False,
    })
    assert resp.status_code == 200
    events = _parse_sse(resp)
    assert events[-1]["type"] == "done"
    hitl_events = [e for e in events if e["type"] == "hitl"]
    assert len(hitl_events) == 1
    assert hitl_events[0]["payload"]["task_type"] == 3  # 新一轮自检审核

    task = db_session.get(BiddingTask, task_id)
    old_review = db_session.get(ReviewTask, review_id)
    assert task.status == 4
    assert task.bidding_sections == regenerated
    assert old_review.status == 1 and old_review.review_result == 1  # 旧审核任务标记驳回
    # 新一轮审核任务已创建
    new_reviews = db_session.scalars(
        select(ReviewTask).where(ReviewTask.session_id == sid).order_by(ReviewTask.id)
    ).all()
    assert len(new_reviews) == 2
    assert new_reviews[-1].status == 0 and new_reviews[-1].task_type == 3


def test_resume_type_mismatch(client, db_session):
    """resume 类型与当前中断点不匹配 -> 400 业务错误。"""
    _register(client)
    token, uid = _login(client)
    h = _auth(token)
    sid = _make_session(client, token, intent_type=1)
    _patch_chain(pytest.MonkeyPatch(), FakeBiddingGraph(pending=["review_parsed"], values={"tender_parsed": True}))

    resp = client.post(f"/chat/req-{sid}-1/resume", headers=h, json={
        "session_id": sid, "review_type": "selfcheck_review", "approved": True,
    })
    assert resp.status_code == 400
    assert "不匹配" in resp.json()["message"]
