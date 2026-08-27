"""用 httpx 详细观察 SSE 响应：首字节时间、心跳、事件、结束方式。"""
import json
import time

import httpx

BASE = "http://127.0.0.1:8000"

with httpx.Client(timeout=120) as client:
    login = client.post(f"{BASE}/auth/login", json={"username": "alice", "password": "secret123"}).json()
    token = login["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sid = client.post(f"{BASE}/sessions", headers=headers, json={"role_type": 0, "intent_type": 0}).json()["data"]["id"]
    print("session_id:", sid)

    t0 = time.perf_counter()
    with client.stream("POST", f"{BASE}/chat/stream", headers=headers, json={
        "session_id": sid, "content": "你好", "role": 0, "intent_type": 0,
    }) as resp:
        t1 = time.perf_counter()
        print(f"响应头耗时: {t1 - t0:.2f}s | status={resp.status_code}")
        n = 0
        first_data = None
        for line in resp.iter_lines():
            n += 1
            if n <= 3:
                print(f"  第{n}行 ({time.perf_counter() - t0:.2f}s): {line[:80]!r}")
            if first_data is None and line.startswith("data: "):
                first_data = (time.perf_counter() - t0, line[:60])
        print(f"总行数: {n} | 首个data事件: {first_data[0]:.2f}s {first_data[1]!r}")
    t2 = time.perf_counter()
    print(f"流结束: 总耗时 {t2 - t0:.2f}s")
