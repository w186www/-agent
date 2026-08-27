"""后端会话/消息/任务接口冒烟验证脚本（临时）。"""
import time
import httpx
from sqlalchemy import delete, select
from app.db.models import AssessmentRecord, BiddingTask, ChatMessage, ChatSession, User
from app.db.session import SessionLocal

BASE = "http://127.0.0.1:8001"
client = httpx.Client(base_url=BASE, timeout=20)
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


# 1. 注册登录
uname = f"smoke_{int(time.time())}"
r = client.post("/auth/register", json={"username": uname, "password": "test1234"})
if r.status_code == 201 or r.status_code == 200:
    pass
r = client.post("/auth/login", json={"username": uname, "password": "test1234"})
assert r.status_code == 200, r.text
uid = r.json()["data"]["user"]["id"]
token = r.json()["data"]["access_token"]
H = {"Authorization": f"Bearer {token}"}
print(f"== 用户 {uid} 登录 ==")

# 2. 新建会话
r = client.post("/sessions", headers=H, json={"role_type": 0, "intent_type": 1})
check("POST /sessions", r.status_code == 200 and r.json()["data"]["id"], r.text[:120])
sid = r.json()["data"]["id"]
check("默认标题生成", r.json()["data"]["title"] == "招投标任务", r.json()["data"]["title"])

# 3. 列表分页 + role_type 筛选
r = client.get("/sessions", headers=H, params={"role_type": 0})
check("GET /sessions 筛选商务", r.status_code == 200 and any(s["id"] == sid for s in r.json()["data"]["items"]))
r = client.get("/sessions", headers=H, params={"role_type": 1})
check("GET /sessions 筛选技术为空", all(s["role_type"] == 1 for s in r.json()["data"]["items"]))

# 4. 改标题
r = client.put(f"/sessions/{sid}", headers=H, json={"title": "改后的标题"})
check("PUT /sessions 改标题", r.json()["data"]["title"] == "改后的标题")

# 5. 造消息 + 分页
db = SessionLocal()
now = int(time.time())
for i in range(25):
    db.add(ChatMessage(user_id=uid, session_id=sid, role=i % 2, request_id=f"r{i}",
                       content=f"消息{i}", tool_calls=[{"name": "search_tender", "arguments": {"q": i}, "duration_ms": 123}] if i % 5 == 0 else None,
                       file_name="资产核查表.xlsx" if i == 3 else None,
                       file_extracted_text="IP,主机名\n192.168.1.1,web01" if i == 3 else None,
                       created_at=now + i))
db.commit()
r = client.get(f"/sessions/{sid}/messages", headers=H, params={"limit": 10})
d = r.json()["data"]
check("GET messages 首页10条", len(d["items"]) == 10 and d["items"][0]["id"] < d["items"][-1]["id"])
check("has_more 为真", d["has_more"] is True)
first_prev_id = d["before_id"]
r2 = client.get(f"/sessions/{sid}/messages", headers=H, params={"limit": 10, "before_id": first_prev_id})
check("上拉翻页无重复", all(m["id"] < first_prev_id for m in r2.json()["data"]["items"]))
msg3 = db.scalar(select(ChatMessage).where(ChatMessage.session_id == sid, ChatMessage.file_name.is_not(None)))
r3 = client.get(f"/sessions/{sid}/messages", headers=H, params={"limit": 50})
m3 = next(m for m in r3.json()["data"]["items"] if m["id"] == msg3.id)
check("消息含 file_name/file_extracted_text", m3["file_name"] == "资产核查表.xlsx" and "192.168.1.1" in (m3["file_extracted_text"] or ""))
check("消息含 tool_calls", any(m.get("tool_calls") for m in r3.json()["data"]["items"]))

# 6. 招投标任务
task = BiddingTask(user_id=uid, session_id=sid, tender_title="XX项目", status=3,
                   bidding_sections={"商务部分": "内容A", "技术部分": "内容B"},
                   compliance_result=[{"item": "资质", "type": "资格条件", "status": "danger", "detail": "缺证书"},
                                      {"item": "保证金", "type": "评分项", "status": "pass", "detail": "符合"}],
                   reference_doc_ids=[11, 22], created_at=now, updated_at=now)
db.add(task)
db.commit()
db.refresh(task)
r = client.get(f"/bidding_tasks?session_id={sid}", headers=H)
check("GET /bidding_tasks?session_id 最新任务", r.json()["data"]["id"] == task.id)
r = client.get(f"/bidding_tasks/{task.id}", headers=H)
check("GET /bidding_tasks/{id} 详情", r.json()["data"]["status"] == 3 and "商务部分" in r.json()["data"]["bidding_sections"])
r = client.get(f"/bidding_tasks/{task.id}", headers=H)
check("compliance_result 含 pass/danger", {i["status"] for i in r.json()["data"]["compliance_result"]} == {"pass", "danger"})
check("reference_doc_ids 透传", r.json()["data"]["reference_doc_ids"] == [11, 22])

# 7. 测评核查记录
rec = AssessmentRecord(user_id=uid, session_id=sid, system_level=1, checklist_code="8.1.4.1",
                       checklist_name="身份鉴别", status=3, confidence=0.92,
                       vlm_analysis={"识别": "已配置密码策略"}, human_record="人工记录内容",
                       comparison_result={"一致": True}, kb_references=[{"title": "企业特殊说明"}],
                       created_at=now)
db.add(rec)
db.commit()
db.refresh(rec)
r = client.get(f"/assessment_records?session_id={sid}", headers=H)
check("GET /assessment_records 列表", any(x["id"] == rec.id for x in r.json()["data"]["items"]))
r = client.get(f"/assessment_records/{rec.id}", headers=H)
check("GET /assessment_records/{id} 详情", r.json()["data"]["confidence"] == 0.92 and r.json()["data"]["status"] == 3)
check("kb_references 透传", r.json()["data"]["kb_references"][0]["title"] == "企业特殊说明")

# 8. 消息附带 intent_type/task_id 解析
r = client.get(f"/sessions/{sid}/messages", headers=H, params={"limit": 5})
d = r.json()["data"]
check("消息含 intent_type=1", all(m["intent_type"] == 1 for m in d["items"]))
check("消息 task_id 指向招投标任务", all(m["task_id"] == {"id": task.id, "status": task.status} for m in d["items"]))
r = client.get(f"/sessions/{sid}/messages", headers=H, params={"page": 1, "page_size": 5})
d = r.json()["data"]
check("偏移分页 page/page_size", d["page"] == 1 and len(d["items"]) == 5 and d["total"] >= 25)

# 9. 权限隔离：他人访问 -> 404
r = client.get(f"/bidding_tasks/{task.id}", headers=H)
check("归属校验通过", r.status_code == 200)
r = client.delete(f"/sessions/{sid}", headers=H)
check("DELETE /sessions", r.status_code == 200)
r = client.get(f"/sessions/{sid}/messages", headers=H)
check("删除后消息不可查", r.status_code == 404)

# 清理
for model in (ChatMessage, BiddingTask, AssessmentRecord):
    db.execute(delete(model).where(model.session_id == sid))
db.execute(delete(ChatSession).where(ChatSession.id == sid))
db.execute(delete(User).where(User.id == uid))
db.commit()
db.close()

print(f"\n== 结果: {sum(results)}/{len(results)} 通过 ==")
raise SystemExit(0 if all(results) else 1)
