"""RAG Q&A service: search → build prompt → LLM generate → citations."""

from sqlmodel import Session

from app.models.course import Course
from app.models.user import User
from app.services.agent_graph import verify_answer_quality
from app.services.llm_provider import get_llm_provider, model_status_from_response
from app.services.prompt_builder import build_rag_prompt
from app.services.rag_service import search_course

MAX_ASK_TOP_K = 10


def answer_course_question(
    course_id: int,
    question: str,
    top_k: int,
    session: Session,
    user: User,
) -> dict:
    """Full RAG Q&A pipeline: search → prompt → LLM → citations."""

    # Clamp top_k
    top_k = min(top_k, MAX_ASK_TOP_K)

    # Verify course exists
    course = session.get(Course, course_id)
    if not course:
        return {"error": "course not found", "course_id": course_id}

    # Retrieve chunks
    search_result = search_course(course_id, question, top_k, session)
    if "error" in search_result:
        return search_result

    chunks = search_result.get("results", [])
    if not chunks:
        return {"error": "no relevant course materials found", "course_id": course_id}

    # Build prompt
    messages = build_rag_prompt(
        question=question,
        chunks=chunks,
        course_name=course.name,
    )

    # Generate answer
    provider = get_llm_provider()
    resp = provider.generate(messages)

    # Build citations
    citations = []
    for c in chunks:
        citations.append({
            "chunk_id": c.get("chunk_id"),
            "source": c.get("source"),
            "page_number": c.get("page_number"),
            "score": c.get("score"),
        })

    verification = verify_answer_quality(resp.content, citations, chunks)
    return {
        "course_id": course_id,
        "course_name": course.name,
        "question": question,
        "answer": resp.content,
        "provider": resp.provider,
        "model": resp.model,
        "model_status": model_status_from_response(resp),
        "citations": citations,
        "retrieved_chunks": chunks,
        "verification": verification.get("verification", {}),
        "verifier_score": verification.get("verifier_score", 0.0),
        "rag_status": search_result.get("rag_status", {}),
    }


def prepare_stream_answer(
    course_id: int,
    question: str,
    top_k: int,
    session: Session,
) -> dict:
    """RAG retrieval + prompt build for streaming generation."""
    top_k = min(top_k, MAX_ASK_TOP_K)
    course = session.get(Course, course_id)
    if not course:
        return {"error": "course not found", "course_id": course_id}

    search_result = search_course(course_id, question, top_k, session)
    if "error" in search_result:
        return search_result

    chunks = search_result.get("results", [])
    if not chunks:
        return {"error": "no relevant course materials found", "course_id": course_id}

    messages = build_rag_prompt(
        question=question,
        chunks=chunks,
        course_name=course.name,
    )
    citations = [
        {
            "chunk_id": c.get("chunk_id"),
            "source": c.get("source"),
            "page_number": c.get("page_number"),
            "score": c.get("score"),
        }
        for c in chunks
    ]
    return {
        "course_id": course_id,
        "course_name": course.name,
        "question": question,
        "messages": messages,
        "citations": citations,
        "retrieved_chunks": chunks,
        "rag_status": search_result.get("rag_status", {}),
    }
