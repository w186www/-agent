"""路由层：技术线（测评核查）操作接口（需认证）。

- POST /assessment/generate_checklist：触发测评清单生成（generate_checklist 工具），
  为每个控制点创建 assessment_records 记录（status=0 待测评），返回控制点列表；
- POST /assessment/{record_id}/upload_screenshot：上传测评截图并触发 VLM 分析
  （analyze_screenshot），更新 vlm_analysis + status=2（核查中）；若已有人工记录则自动触发比对；
- PUT /assessment/{record_id}/human_record：提交人工记录；若已有 VLM 分析结果，
  自动触发比对（compare_records），按置信度阈值更新 status（>=0.80 自动通过，<0.80 待人工复核）。

截图 VLM 分析走本地文件路径（MinIO URL 方式下一轮优化），分析后写入记录。
"""

import json
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.tools import analyze_screenshot, generate_checklist
from ..config import settings
from ..db.models import AssessmentRecord, User
from ..db.session import get_db
from ..exceptions import BusinessError, ErrorCode
from ..log import get_logger
from ..schemas.chat import AssessmentRecordOut
from ..schemas.common import ApiResponse
from ..security import get_current_user
from ..services.assessment_service import (
    compare_and_update_record,
    sync_assessment_session_title,
    write_report_message,
)
from ..services.upload_service_minio import save_file_minio

router = APIRouter(prefix="/assessment", tags=["测评核查操作"])
logger = get_logger("assessment")

# 等保级别 int -> 工具入参中文字符串（0=二级，1=三级，2=四级）
_LEVEL_NAMES = {0: "二级", 1: "三级", 2: "四级"}


class GenerateChecklistRequest(BaseModel):
    """触发清单生成请求体。"""

    session_id: int = Field(description="会话 ID")
    system_level: int = Field(default=1, ge=0, le=2, description="等保级别：0=二级，1=三级，2=四级")
    system_name: str = Field(default="", max_length=128, description="被测系统名称（可选）")


class HumanRecordRequest(BaseModel):
    """提交人工记录请求体。"""

    human_record: str = Field(min_length=1, max_length=4000, description="组员人工填写的结果记录")


def _get_owned_record(db: Session, user: User, record_id: int) -> AssessmentRecord:
    """按归属校验获取核查记录，不存在或不属于当前用户时抛 404。"""
    record = db.get(AssessmentRecord, record_id)
    if record is None or record.user_id != user.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "核查记录不存在", status_code=404)
    return record


def _resolve_screenshot_local(path: str) -> str | None:
    """把截图路径解析为本地文件：minio:// 路径从 MinIO 拉取到临时文件，本地路径直接返回。"""
    if path.startswith("minio://"):
        try:
            from ..services.minio_client import get_minio_client, object_key_of

            object_key = object_key_of(path)
            if not object_key:
                logger.warning("截图 MinIO 路径无法解析: %s", path)
                return None
            client = get_minio_client()
            response = client.get_object(settings.minio_bucket, object_key)
            try:
                content = response.read()
            finally:
                response.close()
                response.release_conn()
            suffix = Path(object_key).suffix or ".png"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                return tmp.name
        except Exception as exc:
            logger.warning("截图从 MinIO 拉取失败 path=%s: %s", path, exc)
            return None
    return path if Path(path).exists() else None


@router.post("/generate_checklist", response_model=ApiResponse, summary="触发测评清单生成")
def generate_checklist_api(
    body: GenerateChecklistRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """调用 generate_checklist 工具生成控制点清单，写入 assessment_records（status=0）。

    校验会话归属后清空该会话旧清单再写入新控制点（避免重复堆积）。
    """
    from ..db.models import ChatSession

    chat_session = db.get(ChatSession, body.session_id)
    if chat_session is None or chat_session.user_id != current_user.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在", status_code=404)

    level_name = _LEVEL_NAMES.get(body.system_level, "三级")
    raw = generate_checklist.invoke({"system_level": level_name, "system_name": body.system_name})
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    if isinstance(parsed, dict) and parsed.get("error"):
        raise BusinessError(ErrorCode.LLM_ERROR, parsed.get("detail") or "测评清单生成失败", status_code=502)
    checklist = parsed.get("checklist") if isinstance(parsed, dict) else None
    if not isinstance(checklist, list) or not checklist:
        raise BusinessError(ErrorCode.LLM_ERROR, "模型未返回有效控制点列表", status_code=502)

    now = int(__import__("time").time())
    for old in db.scalars(
        select(AssessmentRecord).where(AssessmentRecord.session_id == body.session_id)
    ).all():
        db.delete(old)
    records: list[AssessmentRecord] = []
    for item in checklist[: settings.assessment_max_checklist]:
        if not isinstance(item, dict):
            continue
        records.append(AssessmentRecord(
            user_id=current_user.id,
            session_id=body.session_id,
            system_level=body.system_level,
            checklist_code=str(item.get("checklist_code") or "")[:32],
            checklist_name=str(item.get("checklist_name") or "")[:128],
            assessment_command=(str(item.get("assessment_command") or "") or None)[:512],
            status=0,
            confidence=0.0,
            created_at=now,
            updated_at=now,
        ))
    db.add_all(records)
    # 会话标题同步为"被测系统名 等保X级测评"（工作台清单标题与会话同名，优先取请求体系统名）
    sync_assessment_session_title(
        db, body.session_id, body.system_name or parsed.get("system_name") or "", body.system_level
    )
    db.commit()
    logger.info("清单生成完成 session=%s 控制点=%d", body.session_id, len(records))
    return ApiResponse(code=0, message="清单生成成功", data={
        "items": [AssessmentRecordOut.model_validate(r).model_dump() for r in records],
        "total_count": len(records),
    })


@router.post("/{record_id}/upload_screenshot", response_model=ApiResponse, summary="上传测评截图并触发 VLM 分析")
async def upload_screenshot(
    record_id: int,
    file: UploadFile = File(..., description="测评截图（图片文件）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """上传截图到 MinIO，写入 screenshot_path，触发 analyze_screenshot。

    分析结果写入 vlm_analysis，status 更新为 2（核查中）；
    若该控制点已有人工记录，自动触发 compare_records 比对。
    """
    record = _get_owned_record(db, current_user, record_id)
    content = await file.read()
    if not content:
        raise BusinessError(ErrorCode.VALIDATION, "截图文件为空", status_code=400)

    data = save_file_minio(
        db=db,
        user=current_user,
        content=content,
        filename=file.filename or "screenshot.png",
        content_type=file.content_type,
        upload_purpose=3,
        storage_scene=0,
        session_id=record.session_id,
    )
    # 关联到当前控制点记录（save_file_minio 的 _link_assessment_record 只挂最新一条，这里精确指定）
    record.screenshot_path = data.get("path") or record.screenshot_path

    # VLM 分析（本地文件路径，MinIO URL 下一轮优化）
    local = _resolve_screenshot_local(record.screenshot_path)
    if local is None:
        db.commit()
        raise BusinessError(ErrorCode.VALIDATION, "截图文件无法访问", status_code=400)
    analysis = analyze_screenshot(local, record.checklist_code, record.checklist_name)
    record.vlm_analysis = analysis
    record.status = 2  # 核查中
    record.updated_at = int(__import__("time").time())

    compared = False
    review_task_id = None
    if record.human_record:
        review_task_id = compare_and_update_record(db, record)
        compared = True
    # 汇报消息写入对话：截图识别结果（有人工记录则附比对结论）
    recognized = (analysis.get("recognized_text") or "")[:80]
    if compared:
        if record.status == 3:
            result_note = f"与人工记录比对置信度 {record.confidence:.0%}，自动通过"
        elif record.status == 4:
            result_note = f"与人工记录比对置信度 {record.confidence:.0%}，待人工复核"
        else:
            result_note = "比对完成"
    else:
        result_note = "请组员提交人工记录后自动比对"
    write_report_message(
        db, current_user.id, record.session_id,
        f"【测评核查】第 {record.checklist_code} 项（{record.checklist_name}）截图已识别：{recognized or '（无识别文本）'}。{result_note}。",
    )
    db.commit()

    return ApiResponse(code=0, message="截图已上传并完成分析", data={
        "record_id": record.id,
        "status": record.status,
        "vlm_analysis": analysis,
        "comparison_done": compared,
        "confidence": record.confidence,
        "review_task_id": review_task_id,
    })


@router.put("/{record_id}/human_record", response_model=ApiResponse, summary="提交人工记录并触发比对")
def submit_human_record(
    record_id: int,
    body: HumanRecordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """更新 human_record；若已有 VLM 分析结果，自动触发 compare_records 比对。"""
    record = _get_owned_record(db, current_user, record_id)
    record.human_record = body.human_record

    compared = False
    review_task_id = None
    if record.vlm_analysis:
        review_task_id = compare_and_update_record(db, record)
        compared = True
    record.updated_at = int(__import__("time").time())
    # 汇报消息写入对话：人工记录提交结果（有比对则附置信度结论）
    if compared:
        if record.status == 3:
            result_note = f"比对置信度 {record.confidence:.0%}，自动通过"
        elif record.status == 4:
            result_note = f"比对置信度 {record.confidence:.0%}，待人工复核"
        else:
            result_note = "比对完成"
    else:
        result_note = "尚未上传截图，待上传后自动比对"
    write_report_message(
        db, current_user.id, record.session_id,
        f"【测评核查】第 {record.checklist_code} 项（{record.checklist_name}）人工记录已提交，{result_note}。",
    )
    db.commit()

    return ApiResponse(code=0, message="人工记录已提交", data={
        "record_id": record.id,
        "status": record.status,
        "confidence": record.confidence,
        "comparison_done": compared,
        "comparison_result": record.comparison_result,
        "review_task_id": review_task_id,
    })
