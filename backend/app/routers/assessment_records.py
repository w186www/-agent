"""路由层：测评核查记录查询（需认证）。

- GET /assessment_records?session_id=：查询会话下全部核查记录（任务卡片按控制点展示）
- GET /assessment_records/{record_id}：记录详情（弹窗展示 VLM 分析/人工记录/比对结果/置信度）
- 所有操作校验记录归属当前用户
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AssessmentRecord, User
from ..db.session import get_db
from ..exceptions import BusinessError, ErrorCode
from ..schemas.chat import AssessmentRecordOut
from ..schemas.common import ApiResponse
from ..security import get_current_user

router = APIRouter(tags=["测评核查记录"])


@router.get("/assessment_records", response_model=ApiResponse, summary="按会话查询核查记录列表")
def list_assessment_records(
    session_id: int = Query(..., description="会话 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """返回该会话下全部核查记录，按控制点编号排序（任务卡片渲染用）。"""
    records = db.scalars(
        select(AssessmentRecord)
        .where(AssessmentRecord.session_id == session_id, AssessmentRecord.user_id == current_user.id)
        .order_by(AssessmentRecord.checklist_code)
    ).all()
    return ApiResponse(code=0, message="success", data={
        "items": [AssessmentRecordOut.model_validate(r).model_dump() for r in records],
    })


@router.get("/assessment_records/{record_id}", response_model=ApiResponse, summary="测评核查记录详情")
def get_assessment_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """查询核查记录详情。"""
    record = db.get(AssessmentRecord, record_id)
    if record is None or record.user_id != current_user.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "记录不存在", status_code=404)
    return ApiResponse(code=0, message="success", data=AssessmentRecordOut.model_validate(record).model_dump())
