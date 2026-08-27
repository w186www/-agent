"""路由层：招投标任务查询（需认证）。

- GET /bidding_tasks?session_id=：查询某会话下最新一条任务（任务卡片用）
- GET /bidding_tasks/{task_id}：任务详情（弹窗展示投标内容与废标检查结果）
- 所有操作校验任务归属当前用户
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import BiddingTask, User
from ..db.session import get_db
from ..exceptions import BusinessError, ErrorCode
from ..schemas.chat import BiddingTaskOut
from ..schemas.common import ApiResponse
from ..security import get_current_user

router = APIRouter(tags=["招投标任务"])


@router.get("/bidding_tasks", response_model=ApiResponse, summary="查询会话下最新招投标任务")
def list_bidding_tasks(
    session_id: int = Query(..., description="会话 ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """返回该会话下最新一条招投标任务，无则 data=None（任务卡片可静默隐藏）。"""
    task = db.scalar(
        select(BiddingTask)
        .where(BiddingTask.session_id == session_id, BiddingTask.user_id == current_user.id)
        .order_by(BiddingTask.id.desc())
        .limit(1)
    )
    data = BiddingTaskOut.model_validate(task).model_dump() if task else None
    return ApiResponse(code=0, message="success", data=data)


@router.get("/bidding_tasks/{task_id}", response_model=ApiResponse, summary="招投标任务详情")
def get_bidding_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    """查询任务详情（含投标文件各部分与废标检查结果）。"""
    task = db.get(BiddingTask, task_id)
    if task is None or task.user_id != current_user.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
    return ApiResponse(code=0, message="success", data=BiddingTaskOut.model_validate(task).model_dump())
