"""路由层：通用文件上传接口（需认证）。

- 底层存储走 MinIO（upload_service_minio.py），旧本地逻辑见 upload_service.py（教学保留）。
- 支持 upload_purpose / storage_scene / session_id 参数触发业务联动（见服务模块文档）。
- storage_path 格式：minio://{bucket}/{object_key}。
"""

from fastapi import APIRouter, Depends, Form, UploadFile
from sqlalchemy.orm import Session

from ..db.models import User
from ..db.session import get_db
from ..schemas.common import ApiResponse
from ..security import get_current_user
from ..services.upload_service_minio import save_file_minio

router = APIRouter(prefix="/upload", tags=["文件上传"])


@router.post("/file", response_model=ApiResponse, summary="上传文件（需认证）")
async def upload_file(
    file: UploadFile,
    upload_purpose: int = Form(default=0, ge=0, le=5, description="上传用途：0=普通资源，1=招标文件，2=历史标书，3=测评截图，4=资产核查表，5=投标文件"),
    storage_scene: int = Form(default=0, ge=0, le=2, description="存储场景：0=长过期，1=短过期，2=只提取内容不存文件"),
    session_id: int | None = Form(default=None, description="业务联动目标会话 ID（招投标/测评核查）"),
    message_id: int | None = Form(default=None, description="对话消息 ID（storage_scene=2 对话附件时，提取文本写入该消息的 file_extracted_text）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """通用文件上传：MinIO 对象存储 + 元数据记录 + MD5 用户级去重。"""
    content = await file.read()
    data = save_file_minio(
        db=db,
        user=current_user,
        content=content,
        filename=file.filename or "",
        content_type=file.content_type,
        upload_purpose=upload_purpose,
        storage_scene=storage_scene,
        session_id=session_id,
        message_id=message_id,
    )
    return ApiResponse(code=0, message="上传成功", data=data, detail=None)
