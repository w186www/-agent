"""业务层：旧版本地磁盘上传逻辑（教学保留，不运行）。

当前运行逻辑见 upload_service_minio.py（MinIO 对象存储）。
本文件仅作对比/教学参考，不再被任何路由引用。
"""

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import User

IMAGE_PREFIX = "image/"


def _md5_of_file(content: bytes) -> str:
    """计算文件内容的 MD5 哈希。"""
    return hashlib.md5(content).hexdigest()


def _ensure_user_dir(user_id: int) -> Path:
    """确保用户专属上传目录存在，返回目录路径。"""
    user_dir = Path(settings.upload_dir) / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def _detect_file_type(content_type: str | None) -> str:
    """根据 MIME 类型判断文件类别：image / document。"""
    if content_type and content_type.startswith(IMAGE_PREFIX):
        return "image"
    return "document"


def _get_extension(filename: str) -> str:
    """从文件名提取扩展名（含点），无扩展名返回空字符串。"""
    return Path(filename).suffix.lower()


def save_file_local(
    db: Session,
    user: User,
    content: bytes,
    filename: str,
    content_type: str | None,
) -> dict:
    """旧版：保存文件到本地磁盘（按用户分目录，MD5 文件名去重）。"""
    file_type = _detect_file_type(content_type)
    md5 = _md5_of_file(content)
    ext = _get_extension(filename or "file")
    stored_name = f"{md5}{ext}"

    user_dir = _ensure_user_dir(user.id)
    file_path = user_dir / stored_name
    if not file_path.exists():
        file_path.write_bytes(content)

    relative_path = f"{user.id}/{stored_name}"

    if file_type == "image":
        user.avatar = relative_path
        db.commit()

    return {
        "type": file_type,
        "path": relative_path,
        "filename": stored_name,
        "size": len(content),
        "original_name": filename,
    }
