"""Workspace Q&A service.

Keeps `/api/app/ask` thin by encapsulating agent orchestration,
fallback answering, profile update, recommendations, audit logs and
learning-session persistence.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session, select

from app.api.learning_sessions import add_message, get_or_create_session
from app.api.workspace import err, ok
from app.models.student_profile import StudentProfile
from app.models.user import User
from app.services.content_safety_service import evaluate_content_safety
from app.services.grounding_service import evaluate_grounding
from app.services.qa_service import answer_course_question
from app.services.recommendation_service import suggest_resources_from_question
from app.services.resource_package_service import build_resource_package

logger = logging.getLogger(__name__)

ERR_LLM_FAILED = "LLM_FAILED"

PROFILE_DIMENSION_DEFAULTS = {
    "知识基础": "待识别",
    "学习目标": "理解核心概念并完成基础练习",
    "薄弱知识点": ["待识别"],
    "认知风格": "偏好分步骤讲解",
    "资源偏好": ["讲义", "思维导图", "练习题"],
    "错题类型": ["待积累"],
    "掌握度变化": "暂无足够数据",
    "学习节奏": "正常",
}


def answer_workspace_question(*, body: Any, user: User, session: Session) -> dict[str, Any]:
    """Run multi-agent Q&A with fallback and side effects."""
    result, course_name = _run_agent_or_fallback(body=body, user=user, session=session)
    if result.get("error"):
        err(ERR_LLM_FAILED, result["error"], status_code=400)

    citations = result.get("citations", [])
    answer_text = result.get("answer", "")
    profile_row = session.exec(
        select(StudentProfile).where(StudentProfile.user_id == int(user.id) if user.id else 0)
    ).first()
    resource_suggestions = suggest_resources_from_question(body.question, profile_row)

    grounding = evaluate_grounding(
        answer=answer_text,
        citations=citations,
        retrieved_chunks=result.get("retrieved_chunks", []),
    )
    safety = evaluate_content_safety(
        question=body.question,
        answer=answer_text,
        citations=citations,
    )

    resource_package = build_resource_package(
        topic=body.question,
        resource_suggestions=resource_suggestions,
        agent_traces=result.get("agent_traces", []),
        grounding=grounding,
        safety=safety,
        mastery=result.get("student_profile", {}),
    )

    profile_public = _public_profile_payload(result.get("student_profile", {}), result.get("profile_delta", {}))

    response_payload = ok({
        "answer": answer_text,
        "course_name": course_name or result.get("course_name", ""),
        "provider": result.get("provider", "unknown"),
        "model": result.get("model", "unknown"),
        "model_status": result.get("model_status", {}),
        "citations": citations,
        "agent_traces": result.get("agent_traces", []),
        "profile_delta": result.get("profile_delta", {}),
        "student_profile": profile_public,
        "profile_version": profile_public.get("profile_version"),
        "profile_dimensions": profile_public.get("profile_dimensions"),
        "profile_updated_fields": profile_public.get("profile_updated_fields"),
        "profile_summary": profile_public.get("profile_summary"),
        "next_recommendation": profile_public.get("next_recommendation"),
        "verifier_score": result.get("verifier_score", 0.0),
        "verification": result.get("verification", {}),
        "grounding_score": grounding.get("grounding_score", 0.0),
        "grounding": grounding,
        "rag_status": result.get("rag_status", {}),
        "content_safety": safety,
        "generated_artifacts": result.get("generated_artifacts", {}),
        "resource_suggestions": resource_suggestions,
        "resource_package": resource_package,
        "retrieved_chunks": result.get("retrieved_chunks", []),
        "used_rag": bool(citations),
        "status": result.get("status", "ok"),
    })

    _update_profile_from_question(body=body, user=user, session=session, response_payload=response_payload)
    _store_ask_audit(body=body, user=user, session=session, citations=citations, response_payload=response_payload)
    _persist_ask_messages(body=body, user=user, session=session, answer_text=answer_text, result=result, response_payload=response_payload)
    return response_payload


def _run_agent_or_fallback(*, body: Any, user: User, session: Session) -> tuple[dict[str, Any], str]:
    course_name = ""
    try:
        from app.models.course import Course
        from app.services.agent_graph import run_tutor_graph

        course = session.get(Course, body.course_id)
        course_name = course.name if course else ""
        result = run_tutor_graph(
            body.course_id,
            course_name,
            body.question,
            body.top_k,
            session,
            user,
        )
        if not result:
            err(ERR_LLM_FAILED, "no result produced", status_code=500)
        return result, course_name
    except Exception:
        logger.exception("Agent graph failed, falling back to qa_service")
        try:
            result = answer_course_question(
                body.course_id,
                body.question,
                body.top_k,
                session,
                user,
            )
            if result.get("error"):
                err(ERR_LLM_FAILED, result["error"], status_code=400)
            result.setdefault("agent_traces", [])
            result.setdefault("status", "ok")
            return result, result.get("course_name", course_name)
        except Exception as exc:
            err(ERR_LLM_FAILED, str(exc), status_code=500)
    return {}, course_name


def _update_profile_from_question(*, body: Any, user: User, session: Session, response_payload: dict[str, Any]) -> None:
    if len(body.question.strip()) < 15:
        return
    try:
        from app.services.profile_service import update_profile_from_extraction

        extracted = update_profile_from_extraction(
            user,
            body.question,
            session,
            source="ask",
        )
        enriched = _public_profile_payload(extracted, response_payload["data"].get("profile_delta", {}), question=body.question)
        response_payload["data"]["student_profile"] = enriched
        response_payload["data"]["profile_version"] = enriched.get("profile_version")
        response_payload["data"]["profile_dimensions"] = enriched.get("profile_dimensions")
        response_payload["data"]["profile_updated_fields"] = enriched.get("profile_updated_fields")
        response_payload["data"]["profile_summary"] = enriched.get("profile_summary")
        response_payload["data"]["next_recommendation"] = enriched.get("next_recommendation")
    except Exception:
        logger.exception("Failed to update profile from ask")


def _public_profile_payload(profile: dict[str, Any] | None, delta: dict[str, Any] | None = None, question: str = "") -> dict[str, Any]:
    profile = dict(profile or {})
    delta = dict(delta or {})
    weak_points = _profile_weak_points(question or profile.get("last_topic") or delta.get("last_topic") or "", profile, delta)
    resource_pref = _listify(profile.get("resource_preference") or delta.get("resource_preference")) or ["讲义", "思维导图", "练习题"]
    wrong_types = _listify(profile.get("wrong_question_types") or delta.get("wrong_question_types")) or ["待积累"]
    dimensions = dict(PROFILE_DIMENSION_DEFAULTS)
    dimensions.update({
        "知识基础": profile.get("knowledge_level") or delta.get("knowledge_level") or "待识别",
        "学习目标": profile.get("learning_goal") or "理解核心概念并完成基础练习",
        "薄弱知识点": weak_points or ["待识别"],
        "认知风格": profile.get("cognitive_style") or delta.get("cognitive_style") or "偏好分步骤讲解",
        "资源偏好": [str(x) for x in resource_pref],
        "错题类型": wrong_types,
        "掌握度变化": profile.get("mastery_trend") or "暂无足够数据",
        "学习节奏": profile.get("pace_preference") or "正常",
    })
    updated = ["薄弱知识点", "资源偏好"] if weak_points and weak_points != ["待识别"] else []
    if delta.get("cognitive_style"):
        updated.append("认知风格")
    profile.update({
        "profile_version": int(profile.get("profile_version") or delta.get("interaction_count") or 1),
        "profile_dimensions": dimensions,
        "profile_updated_fields": list(dict.fromkeys(updated or ["学习目标"])),
        "profile_summary": f"当前学生对《高等数学上册》的{dimensions['薄弱知识点'][0] if isinstance(dimensions['薄弱知识点'], list) else dimensions['薄弱知识点']}仍需巩固，适合先概念后练习。",
        "next_recommendation": f"建议先复习{dimensions['薄弱知识点'][0] if isinstance(dimensions['薄弱知识点'], list) else '当前知识点'}，再完成 3 道概念辨析题。",
    })
    return profile


def _listify(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return [str(value)] if str(value).strip() else []


def _profile_weak_points(text: str, profile: dict[str, Any], delta: dict[str, Any]) -> list[str]:
    existing = _listify(profile.get("weak_points") or delta.get("weak_points") or delta.get("weakness_triggered"))
    if "极限" in text:
        return ["函数极限", "极限定义理解"]
    if "积分" in text:
        return ["积分概念", "定积分几何意义"]
    if "导数" in text or "微分" in text:
        return ["导数定义", "变化率理解"]
    return existing or ["待识别"]


def _store_ask_audit(*, body: Any, user: User, session: Session, citations: list[Any], response_payload: dict[str, Any]) -> None:
    try:
        from app.api.analytics import AuditLog

        session.add(AuditLog(
            user_id=int(user.id),
            action="question_asked",
            target_type="course",
            target_id=str(body.course_id),
            detail=body.question[:200],
        ))
        session.add(AuditLog(
            user_id=int(user.id),
            action=("question_answered_with_citations" if citations else "question_answered_without_citations"),
            target_type="course",
            target_id=str(body.course_id),
            detail=f"citations={len(citations)} verifier={response_payload.get('data', {}).get('verifier_score', 0.0)}",
        ))
        session.commit()
    except Exception:
        logger.exception("Failed to store ask audit log")


def _persist_ask_messages(*, body: Any, user: User, session: Session, answer_text: str, result: dict[str, Any], response_payload: dict[str, Any]) -> None:
    try:
        learning_session = get_or_create_session(
            session,
            int(user.id),
            body.course_id,
            session_id=body.session_id,
            question=body.question,
        )
        add_message(session, learning_session, "user", body.question)
        add_message(
            session,
            learning_session,
            "assistant",
            answer_text,
            metadata={
                "citations": result.get("citations", []),
                "agent_traces": result.get("agent_traces", []),
                "verifier_score": result.get("verifier_score", 0.0),
            },
        )
        response_payload["session_id"] = learning_session.id
    except Exception:
        logger.exception("Failed to persist learning session messages")
