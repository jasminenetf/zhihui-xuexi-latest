"""
Application workspace API.

Prefix: /api/app

Provides bootstrap, dashboard, ask, generate and related
workspace endpoints for the learning product UI.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.auth import get_current_user, get_current_user_optional
from app.core.database import get_session
from app.models.user import User
from app.api.workspace import (
    ok as _ok,
    err as _err,
    dashboard_payload,
    bootstrap_payload,
    llm_configured,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/app", tags=["app"])

# ── Error codes ────────────────────────────────────────────────────────
ERR_NOT_CONFIGURED = "NOT_CONFIGURED"
ERR_NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
ERR_COURSE_NOT_FOUND = "COURSE_NOT_FOUND"
ERR_NO_KNOWLEDGE_BASE = "NO_KNOWLEDGE_BASE"
ERR_LLM_FAILED = "LLM_FAILED"
ERR_RESOURCE_FAILED = "RESOURCE_FAILED"

# Helpers and workspace routes moved to `app/api/workspace.py`.


# ═══════════════════════════════════════════════════════════════════════
# GET /api/app/bootstrap — app init payload (guest or authenticated)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/bootstrap")
def api_app_bootstrap(
    user: Optional[User] = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    return bootstrap_payload(user, session)


# ═══════════════════════════════════════════════════════════════════════
# GET /api/app/dashboard — course workspace summary
# ═══════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
def api_app_dashboard(
    course_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return dashboard_payload(course_id, user, session)


# ═══════════════════════════════════════════════════════════════════════
# POST /api/app/ask
# ═══════════════════════════════════════════════════════════════════════

from pydantic import BaseModel, Field

class AppAskRequest(BaseModel):
    course_id: int = Field(default=2)
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=8, ge=1, le=20)
    session_id: Optional[int] = Field(default=None, description="学习会话 ID，用于历史持久化")


@router.post("/ask")
def api_app_ask(
    body: AppAskRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Unified Q&A — multi-agent graph pipeline with agent traces."""
    from app.services.app_ask_service import answer_workspace_question

    return answer_workspace_question(body=body, user=user, session=session)


# ═══════════════════════════════════════════════════════════════════════
# POST /api/app/ask/stream — SSE streaming RAG answer
# ═══════════════════════════════════════════════════════════════════════

@router.post("/ask/stream")
async def api_app_ask_stream(
    body: AppAskRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Stream RAG answer via Server-Sent Events (commercial UX)."""
    from app.services.app_stream_service import stream_workspace_question

    return stream_workspace_question(body=body, user=user, session=session)


# ═══════════════════════════════════════════════════════════════════════
# POST /api/app/generate
# ═══════════════════════════════════════════════════════════════════════

class AppGenerateRequest(BaseModel):
    course_id: int = Field(default=2)
    resource_type: str = Field(..., description="lecture_doc, mindmap, quiz, ppt, study_plan, video_script, reading")
    topic: str = Field(default="导数与极限入门", min_length=1)


@router.post("/generate")
def api_app_generate(
    body: AppGenerateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Unified resource generation — wraps resource generator + study plan."""
    try:
        from app.services.app_resource_service import generate_workspace_resource

        return _ok(generate_workspace_resource(body=body, user=user, session=session))
    except HTTPException:
        raise
    except ValueError as e:
        msg = str(e)
        if "course not found" in msg:
            raise HTTPException(status_code=404, detail=ERR_COURSE_NOT_FOUND)
        if "no relevant" in msg:
            raise HTTPException(status_code=400, detail=ERR_NO_KNOWLEDGE_BASE)
        raise HTTPException(status_code=500, detail=f"{ERR_RESOURCE_FAILED}: {msg}")
    except Exception as e:
        logger.exception("Resource generation failed")
        raise HTTPException(status_code=500, detail=f"{ERR_RESOURCE_FAILED}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# POST /api/app/run-demo
# ═══════════════════════════════════════════════════════════════════════

@router.post("/run-demo")
def api_run_demo():
    """Deprecated demo pipeline endpoint."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "DEPRECATED",
            "message": "run_demo is deprecated. Use the standard workspace endpoints instead.",
        },
    )


# ═══════════════════════════════════════════════════════════════════════
# POST /api/app/quiz/submit
# ═══════════════════════════════════════════════════════════════════════

from pydantic import BaseModel as PydanticBaseModel


class QuizSubmitRequest(PydanticBaseModel):
    course_id: int = 0
    topic: str = ""
    question_text: str = ""
    selected_answer: str = ""
    correct_answer: str = ""
    is_correct: bool = False
    knowledge_point: str = ""
    explanation: str = ""


def _quiz_profile_payload(body: QuizSubmitRequest, result: dict[str, Any]) -> dict[str, Any]:
    """Expose the same structured profile fields after quiz actions."""
    topic = (body.knowledge_point or body.topic or "当前知识点").strip() or "当前知识点"
    if any(k in topic or k in body.question_text for k in ["极限", "函数极限"]):
        weak_points = ["函数极限", "极限定义理解"]
    elif any(k in topic or k in body.question_text for k in ["积分", "定积分"]):
        weak_points = ["积分概念", "定积分几何意义"]
    elif any(k in topic or k in body.question_text for k in ["导数", "微分"]):
        weak_points = ["导数定义", "变化率理解"]
    else:
        weak_points = [topic]

    wrong_types = [] if body.is_correct else ["概念辨析错误"]
    if not body.is_correct and any(k in body.question_text + body.explanation for k in ["条件", "适用", "范围"]):
        wrong_types.append("公式适用条件混淆")
    mastery_text = (
        f"{topic}本次练习答对，掌握度有提升，建议继续巩固。"
        if body.is_correct
        else f"{topic}本次练习答错，掌握度需要复测并回看概念条件。"
    )
    dimensions = {
        "知识基础": "基础概念掌握不稳定" if not body.is_correct else "基础概念正在巩固",
        "学习目标": "理解微积分核心概念并完成基础题",
        "薄弱知识点": weak_points,
        "认知风格": "偏好分步骤讲解和图解",
        "资源偏好": ["讲义", "思维导图", "练习题"],
        "错题类型": wrong_types or ["待积累"],
        "掌握度变化": mastery_text,
        "学习节奏": "适合先概念后练习的节奏",
    }
    updated_fields = ["薄弱知识点", "掌握度变化"]
    if wrong_types:
        updated_fields.append("错题类型")
    payload = {
        "profile_version": int(result.get("profile_version") or 1),
        "profile_dimensions": dimensions,
        "profile_updated_fields": updated_fields,
        "profile_summary": f"当前学生在{topic}相关练习中暴露出{'概念辨析问题' if wrong_types else '阶段性进步'}，需要围绕教材例题继续巩固。",
        "next_recommendation": f"建议先复习{weak_points[0]}，再完成 3 道同主题概念辨析题。",
    }
    payload["student_profile"] = dict(payload)
    return payload


@router.post("/quiz/submit")
def api_quiz_submit(
    body: QuizSubmitRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Record a quiz answer and update student profile weak_points."""
    from app.services.quiz_service import submit_quiz_attempt

    result = submit_quiz_attempt(body=body, user=user, session=session)
    result.update(_quiz_profile_payload(body, result))
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════════
# GET /api/app/learning-report
# ═══════════════════════════════════════════════════════════════════════

@router.get("/learning-report")
def api_learning_report(
    course_id: Optional[int] = None,
    topic: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Generate a learning evaluation report from quiz attempts."""
    from app.services.learning_report_service import build_learning_report
    from app.models.learning_analytics import ResourceBookmark

    report = build_learning_report(user=user, session=session, course_id=course_id, topic=topic)
    uid = int(user.id) if user.id else 0
    bookmark_count = len(session.exec(select(ResourceBookmark).where(ResourceBookmark.user_id == uid)).all())
    return _ok(_normalize_learning_report_payload(report, bookmark_count=bookmark_count))


def _normalize_learning_report_payload(report: dict[str, Any], bookmark_count: int = 0) -> dict[str, Any]:
    """Keep report counters and empty mastery display consistent for the UI."""
    report = dict(report or {})
    mastery_items = report.get("mastery_items") or []
    valid_scores: list[float] = []
    for item in mastery_items:
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("mastery_score"))
        except (TypeError, ValueError):
            continue
        valid_scores.append(max(0.0, min(1.0, score)))

    overview = dict(report.get("mastery_overview") or {})
    if valid_scores:
        avg = round(sum(valid_scores) / len(valid_scores), 2)
        overview.update(
            {
                "avg_mastery": avg,
                "average_score": avg,
                "average_label": f"{round(avg * 100)}%",
                "has_data": True,
                "weak_count": sum(1 for score in valid_scores if score < 0.5),
            }
        )
    else:
        overview.update(
            {
                "avg_mastery": None,
                "average_score": None,
                "average_label": "待测评",
                "has_data": False,
                "weak_count": 0,
            }
        )
    report["mastery_overview"] = overview

    stats = dict(report.get("stats") or {})
    wrong_count = max(0, int(report.get("total_attempts") or 0) - int(report.get("correct_count") or 0))
    if wrong_count == 0:
        wrong_count = sum(int(item.get("wrong_count") or 0) for item in mastery_items if isinstance(item, dict))
    stats.setdefault("wrong_count", wrong_count)
    stats.setdefault("bookmark_count", bookmark_count)
    stats.setdefault("mastery_count", len(valid_scores))
    stats.setdefault("study_plan_count", int(report.get("study_plan_count") or 0))
    report["stats"] = stats
    return report
