"""业务层：过期资源清理（每天 03:00 扫描，先删 MinIO 对象，再删元数据）。

- 清理依据：resources.expire_time 非空且已过期；
- 顺序：先删 MinIO 中的原文件，再删 MySQL 元数据，避免遗留孤儿对象；
- 调度：FastAPI 启动时挂载后台守护线程，每小时检查一次，到 03:00 执行。
"""

import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Resource
from ..db.session import SessionLocal
from ..log import get_logger
from .minio_client import get_minio_client, object_key_of

logger = get_logger("cleanup")


def cleanup_expired_resources(db: Session | None = None) -> int:
    """清理已过期资源，返回删除的元数据条数。

    db 为空时自建会话；由调用方传入时复用（便于测试）。
    """
    own_session = db is None
    if db is None:
        db = SessionLocal()

    removed = 0
    try:
        expired = db.scalars(
            select(Resource).where(
                Resource.expire_time.is_not(None),
                Resource.expire_time <= int(time.time()),
            )
        ).all()

        client = get_minio_client()
        for resource in expired:
            object_key = object_key_of(resource.storage_path)
            if object_key:
                try:
                    client.remove_object(settings.minio_bucket, object_key)
                except Exception:
                    # MinIO 对象删除失败不阻塞元数据清理，记录日志由人工核查
                    logger.warning("MinIO 对象删除失败 storage_path=%s", resource.storage_path)
            db.delete(resource)
            removed += 1
        db.commit()
        if removed:
            logger.info("过期资源清理完成，共删除 %d 条", removed)
    finally:
        if own_session:
            db.close()
    return removed


def _cleanup_job_loop() -> None:
    """后台守护线程：每小时检查一次，每日 03:00 执行清理。"""
    last_run_day: str | None = None
    while True:
        now = datetime.now()
        if now.hour == 3 and last_run_day != now.strftime("%Y-%m-%d"):
            last_run_day = now.strftime("%Y-%m-%d")
            try:
                cleanup_expired_resources()
            except Exception:
                logger.exception("过期资源清理任务异常")
        time.sleep(3600)


def start_cleanup_scheduler() -> None:
    """启动过期清理调度线程（守护线程，随主进程退出）。"""
    import threading

    thread = threading.Thread(target=_cleanup_job_loop, name="expired-resource-cleanup", daemon=True)
    thread.start()
    logger.info("过期资源清理调度已启动（每日 03:00）")
