"""路由层：健康检查接口，用于探活与数据库连通性校验。"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..exceptions import BusinessError, ErrorCode
from ..log import get_logger
from ..schemas.common import ApiResponse

logger = get_logger("app.health")

router = APIRouter(tags=["健康检查"])


@router.get("/health", response_model=ApiResponse, summary="健康检查")
def health_check(db: Session = Depends(get_db)) -> ApiResponse:
    """校验服务存活与数据库连通性，数据库异常时返回 503。"""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("健康检查：数据库连接异常 -> %r", exc)
        raise BusinessError(
            ErrorCode.HEALTH_DB_ERROR,
            "数据库连接异常",
            detail=f"{type(exc).__name__}: {exc}",
            status_code=503,
        )
    return ApiResponse(code=0, message="服务正常", data={"status": "healthy", "database": "ok"})
