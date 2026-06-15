"""Workspace streaming Q&A service."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.api.learning_sessions import add_message, get_or_create_session
from app.models.student_profile import StudentProfile
from app.models.user import User
from app.services.llm_provider import get_llm_provider
from app.services.llm_provider import model_status
from app.services.content_safety_service import evaluate_content_safety
from app.services.grounding_service import evaluate_grounding
from app.services.qa_service import prepare_stream_answer
from app.services.recommendation_service import suggest_resources_from_question
from app.services.resource_package_service import build_resource_package

logger = logging.getLogger(__name__)


def stream_workspace_question(*, body: Any, user: User, session: Session) -> StreamingResponse:
    """Build a Server-Sent Events response for streaming RAG answers."""
    prep = prepare_stream_answer(body.course_id, body.question, body.top_k, session)
    if "error" in prep:
        raise HTTPException(status_code=400, detail=prep["error"])

    learning_session = get_or_create_session(
        session,
        int(user.id),
        body.course_id,
        session_id=body.session_id,
        question=body.question,
    )
    add_message(session, learning_session, "user", body.question)

    provider = get_llm_provider()
    citation_count = len(prep.get("citations", []))
    from app.services.agent_graph import build_stream_agent_traces

    agent_traces = build_stream_agent_traces(
        body.question,
        citation_count,
        provider.provider,
        phase="streaming",
    )
    meta = {
        "session_id": learning_session.id,
        "course_name": prep.get("course_name", ""),
        "citations": prep.get("citations", []),
        "provider": provider.provider,
        "model": provider.model,
        "model_status": model_status(provider=provider.provider, model=provider.model),
        "rag_status": prep.get("rag_status", {}),
        "agent_traces": agent_traces,
    }

    return StreamingResponse(
        _event_generator(
            body=body,
            user=user,
            session=session,
            prep=prep,
            provider=provider,
            learning_session=learning_session,
            meta=meta,
            citation_count=citation_count,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_generator(
    *,
    body: Any,
    user: User,
    session: Session,
    prep: dict[str, Any],
    provider: Any,
    learning_session: Any,
    meta: dict[str, Any],
    citation_count: int,
):
    yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
    full_parts: list[str] = []
    try:
        for token in provider.stream_generate(prep["messages"]):
            full_parts.append(token)
            payload = json.dumps({"token": token}, ensure_ascii=False)
            yield f"event: token\ndata: {payload}\n\n"
            await asyncio.sleep(0)
    except Exception as exc:
        payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
        yield f"event: error\ndata: {payload}\n\n"
        return

    done = _finalize_stream_answer(
        body=body,
        user=user,
        session=session,
        prep=prep,
        provider=provider,
        learning_session=learning_session,
        full_answer="".join(full_parts),
        citation_count=citation_count,
    )
    yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"


def _finalize_stream_answer(
    *,
    body: Any,
    user: User,
    session: Session,
    prep: dict[str, Any],
    provider: Any,
    learning_session: Any,
    full_answer: str,
    citation_count: int,
) -> dict[str, Any]:
    from app.services.agent_graph import build_stream_agent_traces, verify_answer_quality

    verify_result = verify_answer_quality(
        full_answer,
        prep.get("citations", []),
        prep.get("retrieved_chunks", []),
    )
    profile_row = session.exec(
        select(StudentProfile).where(StudentProfile.user_id == int(user.id) if user.id else 0)
    ).first()
    resource_suggestions = suggest_resources_from_question(body.question, profile_row)
    final_traces = build_stream_agent_traces(
        body.question,
        citation_count,
        provider.provider,
        phase="done",
        verifier_trace=verify_result.get("trace"),
    )
    student_profile = _update_profile_after_stream(body=body, user=user, session=session)
    _persist_streamed_answer(
        session=session,
        learning_session=learning_session,
        full_answer=full_answer,
        prep=prep,
        provider=provider,
    )
    _store_stream_audit(body=body, user=user, session=session, prep=prep, provider=provider)
    grounding = evaluate_grounding(
        answer=full_answer,
        citations=prep.get("citations", []),
        retrieved_chunks=prep.get("retrieved_chunks", []),
    )
    safety = evaluate_content_safety(
        question=body.question,
        answer=full_answer,
        citations=prep.get("citations", []),
    )
    resource_package = build_resource_package(
        topic=body.question,
        resource_suggestions=resource_suggestions,
        agent_traces=final_traces,
        grounding=grounding,
        safety=safety,
        mastery=student_profile,
    )
    return {
        "answer": full_answer,
        "session_id": learning_session.id,
        "citations": prep.get("citations", []),
        "resource_suggestions": resource_suggestions,
        "resource_package": resource_package,
        "course_name": prep.get("course_name", ""),
        "provider": provider.provider,
        "model": provider.model,
        "model_status": model_status(provider=provider.provider, model=provider.model),
        "agent_traces": final_traces,
        "verifier_score": verify_result["verifier_score"],
        "verification": verify_result.get("verification", {}),
        "grounding_score": grounding.get("grounding_score", 0.0),
        "grounding": grounding,
        "rag_status": prep.get("rag_status", {}),
        "content_safety": safety,
        "student_profile": student_profile,
        "generated_artifacts": {
            "ready_for_generation": bool(full_answer),
            "suggestions": resource_suggestions[:5],
        },
    }


def _update_profile_after_stream(*, body: Any, user: User, session: Session) -> dict[str, Any]:
    student_profile: dict[str, Any] = {}
    try:
        from app.services.profile_service import update_profile_from_behavior, update_profile_from_extraction

        update_profile_from_behavior(
            user,
            session,
            source="ask",
            text=body.question[:200],
            learning_stage="practice",
            confidence=0.05,
        )
        if len(body.question.strip()) >= 15:
            extracted = update_profile_from_extraction(user, body.question, session, source="ask")
            student_profile = {
                "knowledge_level": extracted.get("knowledge_level"),
                "learning_goal": extracted.get("learning_goal"),
                "weak_points": extracted.get("weak_points"),
            }
    except Exception:
        logger.exception("Failed to update profile after streamed ask")
    return student_profile


def _persist_streamed_answer(*, session: Session, learning_session: Any, full_answer: str, prep: dict[str, Any], provider: Any) -> None:
    try:
        add_message(
            session,
            learning_session,
            "assistant",
            full_answer,
            metadata={
                "citations": prep.get("citations", []),
                "provider": provider.provider,
                "model": provider.model,
                "streamed": True,
            },
        )
    except Exception:
        logger.exception("Failed to persist streamed answer")


def _store_stream_audit(*, body: Any, user: User, session: Session, prep: dict[str, Any], provider: Any) -> None:
    try:
        from app.api.analytics import AuditLog

        session.add(AuditLog(
            user_id=int(user.id),
            action="question_answered_stream",
            target_type="course",
            target_id=str(body.course_id),
            detail=f"citations={len(prep.get('citations', []))} provider={provider.provider}",
        ))
        session.commit()
    except Exception:
        logger.exception("Failed to store stream ask audit log")
