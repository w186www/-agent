"""对象存储层：MinIO 客户端封装（懒初始化单例）。

- 元数据与文件解耦：MySQL resources 表存元数据，MinIO 存原文件。
- 客户端在首次使用时创建（bucket 不存在则自动创建），避免启动即依赖 MinIO 可用。
"""

from functools import lru_cache

from minio import Minio

from ..config import settings
from ..log import get_logger

logger = get_logger("minio")


@lru_cache(maxsize=1)
def get_minio_client() -> Minio:
    """获取 MinIO 客户端单例，并确保 bucket 存在。"""
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
        logger.info("MinIO bucket 已创建: %s", settings.minio_bucket)
    return client


def storage_path_of(object_key: str) -> str:
    """拼接标准存储路径：minio://{bucket}/{object_key}。"""
    return f"minio://{settings.minio_bucket}/{object_key}"


def object_key_of(storage_path: str) -> str | None:
    """从存储路径解析 object_key，非法格式返回 None。"""
    prefix = f"minio://{settings.minio_bucket}/"
    if storage_path.startswith(prefix):
        return storage_path[len(prefix):]
    return None
