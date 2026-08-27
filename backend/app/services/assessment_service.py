"""测评核查服务层：比对落库、复核任务、对话汇报消息（router 与 tools 共用，避免循环导入）。

- ensure_review_task：低置信度（status=4）创建/更新复核任务，自动通过（status=3）取消残留待审任务；
- compare_and_update_record：调 compare_records 工具比对 VLM 结果 vs 人工记录，按置信度阈值更新 status；
- write_report_message：把核查动作（截图识别/比对/确认）写成对话消息，让"测评核查"与"对话助手"在同一会话内互通。

工具层（app/ai/tools.py）与路由层（app/routers/assessment.py）都调用本服务，保证规则一致。
"""

import json
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import AssessmentRecord, ChatMessage, ChatSession, ReviewTask
from ..log import get_logger

logger = get_logger("assessment_service")

# 等保级别 int -> 中文字符串（清单标题与比对口径共用）
_LEVEL_NAMES = {0: "二级", 1: "三级", 2: "四级"}


def sync_assessment_session_title(db: Session, session_id: int, system_name: str, system_level: int) -> None:
    """清单生成后把会话标题同步为"被测系统名 等保X级测评"。

    对话助手确认测评系统（generate_checklist 拿到 system_name）后，会话标题成为
    测评核查工作台的清单标题，保证"核查进度清单与会话同名"。system_name 为空时保持默认标题。
    """
    name = (system_name or "").strip()
    if not name:
        return
    session = db.get(ChatSession, session_id)
    if session is None:
        return
    session.title = f"{name} 等保{_LEVEL_NAMES.get(system_level, '三级')}测评"
    logger.info("会话标题同步为测评清单: session=%s title=%s", session_id, session.title)


def ensure_review_task(db: Session, record: AssessmentRecord, now: int) -> int | None:
    """低置信度（status=4）时创建/更新复核任务；自动通过（status=3）时取消残留待审任务。

    同一核查记录只保留一条待审复核任务（task_type=1 低置信度复核 / source_type=1 测评核查记录），
    重复比对时覆盖快照，避免堆积假待办。返回 review_task_id（无待审任务时为 None）。
    """
    existing = db.scalar(
        select(ReviewTask)
        .where(
            ReviewTask.source_type == 1,
            ReviewTask.source_id == record.id,
            ReviewTask.task_type == 1,
            ReviewTask.status == 0,
        )
        .order_by(ReviewTask.id.desc())
        .limit(1)
    )
    if record.status == 3:
        # 自动通过：取消该记录残留的待审复核任务
        if existing is not None:
            existing.status = 2
        return None
    snapshot = {
        "record_id": record.id,
        "checklist_code": record.checklist_code,
        "checklist_name": record.checklist_name,
        "confidence": record.confidence,
        "comparison_result": record.comparison_result,
        "kb_references": record.kb_references,
    }
    if existing is not None:
        existing.review_data = snapshot
        return existing.id
    task = ReviewTask(
        session_id=record.session_id,
        user_id=record.user_id,
        task_type=1,
        source_type=1,
        source_id=record.id,
        review_data=snapshot,
        created_at=now,
    )
    db.add(task)
    db.flush()
    return task.id


def compare_and_update_record(db: Session, record: AssessmentRecord) -> int | None:
    """执行 VLM 结果 vs 人工记录比对：调 compare_records 工具，按阈值更新 status。

    confidence >= CONFIDENCE_THRESHOLD -> status=3（自动通过，取消残留复核任务）；
    confidence <  CONFIDENCE_THRESHOLD -> status=4（待人工复核，创建复核任务）。
    返回复核任务 id（无待审任务时为 None）。
    """
    # 惰性导入：tools 顶部依赖 service（避免循环导入）
    from ..ai.tools import compare_records

    vlm_result = json.dumps(record.vlm_analysis or {}, ensure_ascii=False)
    result = compare_records.invoke({
        "vlm_result": vlm_result,
        "human_record": record.human_record or "",
        "checklist_code": record.checklist_code,
    })
    try:
        comparison = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        comparison = {}
    if comparison.get("error"):
        logger.warning(
            "compare_records 返回错误 code=%s: %s",
            record.checklist_code, comparison.get("detail"),
        )
        return None

    confidence = float(comparison.get("confidence") or 0.0)
    record.comparison_result = comparison
    record.confidence = round(min(max(confidence, 0.0), 1.0), 2)
    record.kb_references = comparison.get("kb_references") or record.kb_references
    record.status = 3 if record.confidence >= settings.confidence_threshold else 4
    now = int(time.time())
    record.updated_at = now
    logger.info(
        "比对完成 code=%s confidence=%s status=%s",
        record.checklist_code, record.confidence, record.status,
    )
    return ensure_review_task(db, record, now)


def write_report_message(db: Session, user_id: int, session_id: int, content: str) -> None:
    """把核查动作结果写入会话，作为一条 assistant 消息（对话助手与测评核查互通的关键）。

    content 使用【测评核查】前缀，供前端与模型识别为核查汇报。
    """
    now = int(time.time())
    db.add(ChatMessage(
        user_id=user_id,
        session_id=session_id,
        role=1,
        request_id=f"report-{uuid.uuid4().hex[:12]}",
        content=content,
        created_at=now,
    ))
    logger.info("写入测评核查汇报消息 session=%s", session_id)
