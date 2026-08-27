"""复现浏览器行为：intent=0 对话助手流式链路。"""
import json

import httpx

BASE = "http://127.0.0.1:8000"

with httpx.Client(timeout=120) as client:
    login = client.post(f"{BASE}/auth/login", json={"username": "alice", "password": "secret123"}).json()
    token = login["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sid = client.post(f"{BASE}/sessions", headers=headers, json={"role_type": 0, "intent_type": 0}).json()["data"]["id"]
    print("session_id:", sid)

    with client.stream("POST", f"{BASE}/chat/stream", headers=headers, json={
        "session_id": sid, "content": "你好，介绍一下等保测评", "role": 0, "intent_type": 0,
    }) as resp:
        print("status:", resp.status_code)
        print("content-type:", resp.headers.get("content-type"))
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        types = [e["type"] for e in events]
        print("事件序列:", " -> ".join(types))
        toks = "".join(e.get("content", "") for e in events if e["type"] == "token")
        print("token总长度:", len(toks), "| 前60字:", toks[:60])
