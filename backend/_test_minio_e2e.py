"""MinIO 对象存储改造端到端验证脚本（临时，验证后删除）。

覆盖：
1. 上传普通文档 → MinIO 对象 + resources 元数据
2. 同用户重复上传同 MD5 → 去重（deduplicated=true，不新建对象）
3. upload_purpose=2 历史标书 → kb_documents + Qdrant 向量
4. upload_purpose=1 招标文件 → bidding_tasks.tender_file_path 联动
5. upload_purpose=3 测评截图 → assessment_records.screenshot_path 联动
6. upload_purpose=4 资产核查表 → storage_scene=2 只提取内容不落盘
7. 过期清理：模拟短过期数据，验证先删 MinIO 对象再删元数据
"""

import json
import time

import httpx
from minio import Minio
from qdrant_client import QdrantClient
from sqlalchemy import select, delete

from app.config import settings
from app.db.models import AssessmentRecord, BiddingTask, KbDocument, Resource, User
from app.db.session import SessionLocal

BASE = "http://127.0.0.1:8000"
PASS = "test1234"

client_http = httpx.Client(base_url=BASE, timeout=20)
minio = Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
              secret_key=settings.minio_secret_key, secure=False)
qdrant = QdrantClient(url=settings.qdrant_url)

results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def reg_and_login() -> tuple[int, str]:
    """注册临时用户并登录，返回 (user_id, access_token)。"""
    uname = f"e2e_{int(time.time())}"
    r = client_http.post("/auth/register", json={"username": uname, "password": PASS})
    if r.status_code != 200:
        # 已存在则直接登录
        pass
    r = client_http.post("/auth/login", json={"username": uname, "password": PASS})
    assert r.status_code == 200, f"login failed: {r.text}"
    data = r.json()["data"]
    return data["user"]["id"], data["access_token"]


def upload(token: str, filename: str, content: bytes, content_type: str,
           upload_purpose: int = 0, storage_scene: int = 0, session_id: int | None = None) -> dict:
    files = {"file": (filename, content, content_type)}
    data = {"upload_purpose": str(upload_purpose), "storage_scene": str(storage_scene)}
    if session_id is not None:
        data["session_id"] = str(session_id)
    r = client_http.post("/upload/file", headers={"Authorization": f"Bearer {token}"},
                         files=files, data=data)
    assert r.status_code == 200, f"upload failed: {r.status_code} {r.text}"
    return r.json()["data"]


def main():
    uid, token = reg_and_login()
    print(f"== 测试用户 id={uid} 已注册登录 ==")

    # ---------- 1. 普通文档上传 -> MinIO + 元数据 ----------
    doc_content = b"hello minio storage e2e test " * 20
    d1 = upload(token, "普通文档.txt", doc_content, "text/plain")
    check("1.1 普通文档上传返回 path", d1["path"].startswith("minio://"), d1["path"])
    check("1.2 上传返回 resource_id", d1.get("resource_id") is not None, str(d1))
    obj_key = d1["path"].replace(f"minio://{settings.minio_bucket}/", "")
    obj = minio.stat_object(settings.minio_bucket, obj_key)
    check("1.3 MinIO 对象已落盘", obj.size == len(doc_content), f"size={obj.size}")
    check("1.4 过期时间已计算(长场景30天)",
          d1["expire_time"] and d1["expire_time"] > time.time() + 29 * 86400, str(d1["expire_time"]))

    # ---------- 2. 重复上传同 MD5 -> 去重 ----------
    d2 = upload(token, "重复文档.txt", doc_content, "text/plain")
    check("2.1 重复上传 deduplicated=true", d2.get("deduplicated") is True, str(d2))
    check("2.2 去重后复用同一资源 id", d2["resource_id"] == d1["resource_id"], f"{d1['resource_id']} vs {d2['resource_id']}")

    # ---------- 3. 历史标书 -> kb_documents + Qdrant ----------
    tender_content = "某市政务云等保测评项目历史标书。本次测评范围包括主机安全、网络安全、数据安全等层面。评分细则详见评分表。" * 30
    d3 = upload(token, "历史标书.txt", tender_content.encode("utf-8"), "text/plain", upload_purpose=2)
    db = SessionLocal()
    doc = db.scalar(select(KbDocument).where(KbDocument.user_id == uid).order_by(KbDocument.id.desc()))
    check("3.1 kb_documents 已创建(kb_type=2)", doc is not None and doc.kb_type == 2,
          f"doc_id={doc.id if doc else None} status={doc.status if doc else None}")
    check("3.2 标书 file_path 指向 MinIO", doc is not None and doc.file_path.startswith("minio://"), doc.file_path if doc else "")
    check("3.3 标书向量化完成 status=1", doc is not None and doc.status == 1, str(doc.status if doc else None))
    check("3.4 Qdrant 集合已创建", qdrant.collection_exists(settings.qdrant_collection))
    coll = qdrant.get_collection(settings.qdrant_collection) if qdrant.collection_exists(settings.qdrant_collection) else None
    cnt = coll.points_count if coll else 0
    check("3.5 Qdrant 已灌入向量", coll is not None and cnt > 0, f"points={cnt}")

    # ---------- 4. 招标文件联动 -> bidding_tasks.tender_file_path ----------
    from app.db.models import ChatSession
    s1 = ChatSession(user_id=uid, role_type=1, intent_type=1, title="e2e 招标会话",
                     created_at=int(time.time()), updated_at=int(time.time()))
    s2 = ChatSession(user_id=uid, role_type=1, intent_type=2, title="e2e 测评会话",
                     created_at=int(time.time()), updated_at=int(time.time()))
    db.add_all([s1, s2])
    db.commit()
    db.refresh(s1)
    db.refresh(s2)
    task = BiddingTask(user_id=uid, session_id=s1.id, tender_title="e2e 招标任务",
                       status=0, reference_doc_ids=[], created_at=int(time.time()))
    db.add(task)
    db.commit()
    db.refresh(task)
    tender_f = upload(token, "招标文件.pdf", b"%PDF-1.4 fake tender content", "application/pdf",
                      upload_purpose=1, session_id=task.session_id)
    # 上传接口在独立连接中提交；本连接受 MySQL 快照隔离影响读不到新值，改用新连接读取
    db2 = SessionLocal()
    task2 = db2.scalar(select(BiddingTask).where(BiddingTask.id == task.id))
    check("4.1 bidding_tasks.tender_file_path 已联动", task2.tender_file_path == tender_f["path"],
          f"{task2.tender_file_path}")
    db2.close()

    # ---------- 5. 测评截图联动 -> assessment_records.screenshot_path ----------
    rec = AssessmentRecord(user_id=uid, session_id=s2.id, system_level=1, checklist_code="8.1.4.1",
                           checklist_name="身份鉴别", status=0, confidence=0.0,
                           created_at=int(time.time()))
    db.add(rec)
    db.commit()
    db.refresh(rec)
    png_content = b"\x89PNG\r\n\x1a\nfake-png-bytes-for-screenshot"
    shot = upload(token, "截图.png", png_content, "image/png", upload_purpose=3, session_id=rec.session_id)
    db3 = SessionLocal()
    rec2 = db3.scalar(select(AssessmentRecord).where(AssessmentRecord.id == rec.id))
    check("5.1 assessment_records.screenshot_path 已联动", rec2.screenshot_path == shot["path"], f"{rec2.screenshot_path}")
    db3.close()
    check("5.2 图片上传返回 type=image", shot["type"] == "image", str(shot["type"]))

    # ---------- 6. 资产核查表 -> storage_scene=2 只提取不落盘 ----------
    asset_content = "IP,主机名,系统类型,等保级别\n192.168.1.10,web01,Linux,三级\n192.168.1.11,db01,Linux,三级"
    d6 = upload(token, "资产核查表.csv", asset_content.encode("utf-8"), "text/csv", upload_purpose=4)
    check("6.1 资产核查表返回 extracted_text", d6.get("extracted_text") is not None and "192.168.1.10" in d6["extracted_text"], str(d6.get("extracted_text"))[:60])
    check("6.2 资产核查表 path=None(未落盘)", d6["path"] is None, str(d6["path"]))
    asset_res = db.scalar(select(Resource).where(Resource.user_id == uid, Resource.file_name == "资产核查表.csv"))
    check("6.3 场景2未创建元数据记录", asset_res is None)

    # ---------- 7. 过期清理（模拟短过期已到期的资源） ----------
    from app.services.cleanup_service import cleanup_expired_resources
    expired_obj_key = f"users/{uid}/expiredtest.txt"
    minio.put_object(settings.minio_bucket, expired_obj_key, __import__("io").BytesIO(b"expired"),
                     length=7, content_type="text/plain")
    res = Resource(user_id=uid, resource_type=0, storage_scene=1, upload_purpose=0,
                   file_name="过期附件.txt", file_hash="e" * 32,
                   storage_path=f"minio://{settings.minio_bucket}/{expired_obj_key}",
                   expire_time=int(time.time()) - 100, created_at=int(time.time()))
    db.add(res)
    db.commit()
    db.refresh(res)
    cleaned = cleanup_expired_resources(db)
    check("7.1 过期清理函数执行成功", cleaned >= 1, f"cleaned={cleaned}")
    obj_exists = minio.bucket_exists(settings.minio_bucket) and any(
        o.object_name == expired_obj_key for o in minio.list_objects(settings.minio_bucket, prefix=expired_obj_key))
    check("7.2 过期 MinIO 对象已删除", not obj_exists)
    res2 = db.scalar(select(Resource).where(Resource.id == res.id))
    check("7.3 过期元数据已删除", res2 is None)

    # ---------- 清理测试数据 ----------
    db.execute(delete(Resource).where(Resource.user_id == uid))
    db.execute(delete(KbDocument).where(KbDocument.user_id == uid))
    db.execute(delete(BiddingTask).where(BiddingTask.id == task.id))
    db.execute(delete(AssessmentRecord).where(AssessmentRecord.id == rec.id))
    db.execute(delete(ChatSession).where(ChatSession.id.in_([s1.id, s2.id])))
    db.execute(delete(User).where(User.id == uid))
    db.commit()
    # 删除 MinIO 中该用户对象
    for o in minio.list_objects(settings.minio_bucket, prefix=f"users/{uid}/"):
        minio.remove_object(settings.minio_bucket, o.object_name)
    # 删除 Qdrant 集合
    if qdrant.collection_exists(settings.qdrant_collection):
        qdrant.delete_collection(settings.qdrant_collection)
    db.close()
    print("== 测试数据已清理 ==")

    failed = [r for r in results if not r[1]]
    print(f"\n== 结果: {len(results) - len(failed)}/{len(results)} 通过 ==")
    if failed:
        for name, _, detail in failed:
            print(f"  FAILED: {name} {detail}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
