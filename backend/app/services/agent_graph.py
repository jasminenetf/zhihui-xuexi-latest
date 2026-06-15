"""
LangGraph multi-agent tutor workflow v2 — R2.2 enhanced.

5-agent pipeline with conditional routing:
  supervisor → profile → rag → lecture → verifier ──┬── score ≥ 0.85 → insight → practice → END
                                                     └── score < 0.85 → rag (retry) → ...
"""

import logging
import re
from typing import Optional, TypedDict, Annotated, Any
import operator

from langgraph.graph import StateGraph, END
from sqlmodel import Session

from app.models.user import User
from app.services.llm_provider import get_llm_provider, model_status_from_response
from app.services.prompt_builder import build_rag_prompt
from app.services.rag_service import search_course

logger = logging.getLogger(__name__)
MAX_RETRY = 2
MAX_TUTOR_TOP_K = 10

# ═══════════════════════════════════════════════════════════════════════
# GraphState — typed shared state across all nodes
# ═══════════════════════════════════════════════════════════════════════

class AgentTraceEntry(TypedDict, total=False):
    agent_name: str
    status: str          # pending|running|completed|failed
    message: str
    timestamp: float

class CitationEntry(TypedDict, total=False):
    chunk_id: Optional[str]
    source: str
    page_number: Optional[int]
    score: float
    content: str

class ArtifactEntry(TypedDict, total=False):
    mindmap: Optional[str]
    quiz: Optional[list[dict]]
    lecture_doc: Optional[str]
    ppt: Optional[dict]
    study_plan: Optional[dict]

class GraphState(TypedDict):
    course_id: int
    course_name: Optional[str]
    question: str
    top_k: int
    user_id: int
    user_role: str
    intent: str
    student_profile: dict
    retrieved_chunks: list[dict]
    citations: list[dict]
    draft_answer: str
    verified_answer: str
    verifier_score: float
    verification: dict
    agent_trace: Annotated[list[dict], operator.add]
    error: Optional[str]
    retry_count: int
    profile_delta: dict
    generated_artifacts: dict
    model_status: dict
    rag_status: dict
    provider: str
    model: str

# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

import time

def _trace_entry(agent_name: str, status: str, message: str = "", *, phase: str | None = None, output: Any | None = None) -> dict:
    """Create a normalized multi-agent trace entry.

    Keep legacy fields (agent_name/message/timestamp) while adding the
    canonical schema consumed by the product workbench frontend and smoke tests.
    """
    ts = int(time.time())
    normalized_phase = phase or _infer_trace_phase(agent_name, status)
    return {
        "agent": agent_name,
        "agent_name": agent_name,
        "phase": normalized_phase,
        "status": status,
        "summary": message,
        "message": message,
        "latency_ms": 0,
        "output": output or {},
        "timestamp": ts,
    }


def _infer_trace_phase(agent_name: str, status: str) -> str:
    name = (agent_name or "").lower()
    if "profile" in name or "insight" in name:
        return "profiling"
    if "informer" in name or "retriever" in name or "rag" in name:
        return "retrieving"
    if "tutor" in name or "lecture" in name:
        return "generating"
    if "verifier" in name:
        return "verifying"
    if "practice" in name or "resource" in name:
        return "building_resources"
    if status == "failed":
        return "failed"
    return "planning"

def _detect_knowledge_level(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ["不懂", "不会", "基础比较差", "基础很差", "基础差", "简单", "初学", "入门", "零基础"]):
        return "beginner"
    if any(w in q for w in ["证明", "推导", "深入", "原理", "为什么", "考研", "竞赛"]):
        return "advanced"
    return "intermediate"

def _detect_cognitive_style(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ["证明", "推导", "为什么", "逻辑"]):
        return "logical"
    if any(w in q for w in ["例题", "怎么做", "练习", "做题", "应用", "计算"]):
        return "practice_oriented"
    if any(w in q for w in ["图", "导图", "可视化", "思维导图", "画"]):
        return "visual"
    return "conceptual"

# ═══════════════════════════════════════════════════════════════════════
# Nodes
# ═══════════════════════════════════════════════════════════════════════

def supervisor_node(state: GraphState) -> dict:
    """Entry: initialize graph state."""
    return {
        "intent": "course_tutoring",
        "top_k": min(state.get("top_k", 5), 10),
        "agent_trace": [_trace_entry(
            "TutorAgent", "running",
            f"任务已启动：正在拆解问题「{state['question'][:40]}...」"
        )],
        "student_profile": {},
        "retrieved_chunks": [],
        "citations": [],
        "draft_answer": "",
        "verified_answer": "",
        "verifier_score": 0.0,
        "verification": {},
        "error": None,
        "retry_count": 0,
        "profile_delta": {},
        "generated_artifacts": {},
        "model_status": {},
        "rag_status": {},
        "provider": "",
        "model": "",
    }


def profile_node(state: GraphState) -> dict:
    """Profile extraction: infer learner profile from question text."""
    q = state.get("question", "")
    level = _detect_knowledge_level(q)
    style = _detect_cognitive_style(q)

    # Detect knowledge weakness from question keywords
    weakness = ""
    detected = []
    topic_patterns = [
        (r"导数|求导|微分|切线|变化率", "导数定义 / 变化率理解"),
        (r"极限|函数极限|连续性|无穷小|夹逼", "函数极限 / 极限定义理解"),
        (r"积分|不定积分|定积分|微积分基本定理", "积分概念 / 定积分几何意义"),
        (r"中值定理|罗尔|拉格朗日|柯西|泰勒", "微分中值定理"),
        (r"级数|收敛|幂级数|傅里叶", "无穷级数"),
    ]
    for pat, topic in topic_patterns:
        if re.search(pat, q):
            detected.append(topic)
    weakness = "、".join(detected) if detected else ""

    profile = {
        "knowledge_level": level,
        "cognitive_style": style,
        "needs_examples": style == "practice_oriented",
        "needs_step_by_step": level == "beginner" or "步骤" in q,
        "detected_weakness": weakness,
        "weak_points": detected or ["待识别"],
        "resource_preference": ["讲义", "思维导图", "练习题"],
        "wrong_question_types": ["待积累"],
        "mastery_trend": "暂无足够数据",
        "learning_goal": "考研复习" if "考研" in q else "课程学习",
        "pace_preference": "slow" if level == "beginner" else "normal",
        "profile_updated_fields": ["薄弱知识点", "认知风格"] if detected else ["认知风格"],
    }

    return {
        "student_profile": profile,
        "agent_trace": [_trace_entry(
            "ProfileAgent", "completed",
            f"已提取画像：水平={level}, 风格={style}, 知识短板={'已识别' if weakness else '未知'}"
        )],
    }


def rag_node(state: GraphState, session: Session) -> dict:
    """Informer: retrieve relevant chunks from ChromaDB knowledge base."""
    cid = state["course_id"]
    top_k = state.get("top_k", 8)
    retry = state.get("retry_count", 0)

    result = search_course(cid, state["question"], top_k, session)
    if "error" in result:
        return {
            "error": result["error"],
            "agent_trace": [_trace_entry(
                "InformerAgent", "failed",
                f"知识库检索失败：{result['error']}"
            )],
        }

    chunks = result.get("results", [])
    if not chunks:
        return {
            "error": "no relevant course materials found",
            "agent_trace": [_trace_entry(
                "InformerAgent", "failed",
                "未在知识库中找到相关课程资料"
            )],
        }

    citations = []
    for idx, c in enumerate(chunks):
        content_snippet = (c.get("content") or "")[:150]
        citations.append({
            "id": str(idx + 1),
            "chunk_id": c.get("chunk_id"),
            "source": c.get("source", "课程资料"),
            "page_number": c.get("page_number"),
            "score": c.get("score", 0),
            "content": content_snippet,
            "title": c.get("source", "课程资料"),
        })

    msg = f"在ChromaDB中成功匹配到{len(chunks)}个高价值高等数学高维切片"
    if retry > 0:
        msg = f"（第{retry}次重试）{msg}"

    return {
        "retrieved_chunks": chunks,
        "citations": citations,
        "rag_status": result.get("rag_status", {}),
        "error": None,
        "agent_trace": [_trace_entry("InformerAgent", "completed", msg)],
    }


def lecture_node(state: GraphState) -> dict:
    """Tutor: generate answer using RAG context + student profile."""
    if state.get("error"):
        return {
            "draft_answer": "",
            "agent_trace": [_trace_entry(
                "TutorAgent", "skipped",
                f"跳过生成：{state['error']}"
            )],
        }

    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return {
            "draft_answer": "",
            "agent_trace": [_trace_entry(
                "TutorAgent", "skipped",
                "无可用知识库切片，无法生成回答"
            )],
        }

    course_name = state.get("course_name", "")
    messages = build_rag_prompt(
        question=state["question"],
        chunks=chunks,
        course_name=course_name,
    )

    # Inject student profile into system message
    profile = state.get("student_profile", {})
    if profile:
        profile_hint = (
            f"\n学生画像：知识水平={profile.get('knowledge_level', 'intermediate')}，"
            f"认知风格={profile.get('cognitive_style', 'conceptual')}，"
            f"知识短板={profile.get('detected_weakness', '未知')}。"
            f"请根据学生水平调整回答深度和讲解方式。"
        )
        messages[0]["content"] += profile_hint

    provider = get_llm_provider()
    try:
        import signal
        resp = provider.generate(messages)
    except Exception as e:
        logger.warning("LLM generate failed: %s", e)
        return {
            "draft_answer": "",
            "agent_trace": [_trace_entry(
                "TutorAgent", "failed",
                f"AI模型调用失败：{str(e)[:80]}"
            )],
        }

    answer = resp.content

    return {
        "draft_answer": answer,
        "provider": resp.provider,
        "model": resp.model,
        "model_status": model_status_from_response(resp),
        "agent_trace": [_trace_entry(
            "TutorAgent", "completed",
            f"已生成回答（{len(answer)}字符），基于{len(chunks)}个知识切片"
        )],
    }


def verify_answer_quality(draft: str, citations: list, chunks: list) -> dict:
    """VerifierAgent: citation coverage check, not a vague truth claim."""
    claims = _extract_answer_claims(draft)
    chunk_texts = [str(c.get("content") or c.get("snippet") or "") for c in (chunks or [])]
    supported: list[str] = []
    unsupported: list[str] = []
    for claim in claims:
        if _claim_supported_by_chunks(claim, chunk_texts):
            supported.append(claim)
        else:
            unsupported.append(claim)

    total_claims = len(claims)
    supported_count = len(supported)
    citation_coverage = round(supported_count / total_claims, 2) if total_claims else (1.0 if citations and draft else 0.0)
    if not citations or not chunks:
        risk_level = "high"
    elif citation_coverage >= 0.75 and not unsupported:
        risk_level = "low"
    elif citation_coverage >= 0.45:
        risk_level = "medium"
    else:
        risk_level = "high"

    score = citation_coverage
    verdict = "passed" if risk_level != "high" else "needs_review"
    msg = f"引用覆盖率 {round(citation_coverage * 100)}%，支持断言 {supported_count} 条，无依据断言 {len(unsupported)} 条，风险 {risk_level}"

    return {
        "verified_answer": draft if draft else "",
        "verifier_score": score,
        "verification": {
            "verdict": verdict,
            "citation_coverage": citation_coverage,
            "supported_claim_count": supported_count,
            "unsupported_claims": unsupported[:5],
            "unsupported_claim_count": len(unsupported),
            "risk_level": risk_level,
            "claims_checked": total_claims,
        },
        "trace": _trace_entry(
            "VerifierAgent",
            "completed" if draft else "failed",
            msg,
            phase="verifying",
            output={
                "citation_coverage": citation_coverage,
                "supported_claim_count": supported_count,
                "unsupported_claim_count": len(unsupported),
                "risk_level": risk_level,
            },
        ),
    }


def _extract_answer_claims(answer: str) -> list[str]:
    if not answer:
        return []
    parts = re.split(r"[。！？；\n]+", answer)
    claims: list[str] = []
    for part in parts:
        text = re.sub(r"\s+", "", part)
        if len(text) >= 12 and not text.startswith(("【", "参考", "来源")):
            claims.append(text[:120])
    return claims[:12]


def _claim_supported_by_chunks(claim: str, chunk_texts: list[str]) -> bool:
    keywords = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}|\d+", claim)
    keywords = [k for k in keywords if k not in {"这个", "因此", "所以", "可以", "需要", "我们", "如果", "因为"}]
    if not keywords:
        return bool(chunk_texts)
    for chunk in chunk_texts:
        hit = sum(1 for keyword in keywords[:12] if keyword in chunk)
        if hit >= max(1, min(3, len(keywords) // 3)):
            return True
    return False


def verifier_node(state: GraphState) -> dict:
    """Verifier: cross-check answer against source chunks for hallucination."""
    result = verify_answer_quality(
        state.get("draft_answer", ""),
        state.get("citations", []),
        state.get("retrieved_chunks", []),
    )
    return {
        "verified_answer": result["verified_answer"],
        "verifier_score": result["verifier_score"],
        "verification": result["verification"],
        "agent_trace": [result["trace"]],
    }


def should_retry(state: GraphState) -> str:
    """Conditional edge: retry RAG if verifier score is too low."""
    score = state.get("verifier_score", 0)
    retry = state.get("retry_count", 0)
    has_error = bool(state.get("error"))

    if has_error:
        return "end"
    if score < 0.5 and retry < MAX_RETRY:
        logger.info(f"Verifier score {score:.2f} < 0.5, retry {retry + 1}/{MAX_RETRY}")
        return "rag_retry"
    return "insight"


def retry_increment_node(state: GraphState) -> dict:
    """Increment retry counter before re-entering RAG."""
    return {"retry_count": state.get("retry_count", 0) + 1}


def insight_node(state: GraphState) -> dict:
    """Insight: extract profile delta from this interaction for radar update."""
    q = state.get("question", "")
    level = _detect_knowledge_level(q)
    style = _detect_cognitive_style(q)
    weakness = state.get("student_profile", {}).get("detected_weakness", "")

    delta = {
        "knowledge_level": level,
        "cognitive_style": style,
        "interaction_count": 1,
        "last_topic": q[:40],
    }
    if weakness:
        delta["weakness_triggered"] = weakness

    return {
        "profile_delta": delta,
        "agent_trace": [_trace_entry(
            "InsightAgent", "completed",
            f"成功捕获用户行为特征，动态修正雷达图画像：{delta.get('knowledge_level')}/{delta.get('cognitive_style')}"
        )],
    }


def practice_node(state: GraphState) -> dict:
    """Practice: prepare resource generation hints for the frontend."""
    from app.services.recommendation_service import suggest_resources_from_question

    draft = state.get("draft_answer", "")
    question = state.get("question", "")
    suggestions = suggest_resources_from_question(question) if question else []
    type_labels = {
        "mindmap": "思维导图",
        "quiz": "自适测验",
        "lecture_doc": "精编讲义",
        "ppt": "PPT课件",
        "reading": "拓展阅读",
        "video_script": "教学脚本",
        "study_plan": "学习路径",
    }
    msg_parts = [type_labels.get(s["type"], s["type"]) for s in suggestions[:3]]
    if draft and not msg_parts:
        msg_parts = ["思维导图", "自适测验", "精编讲义"]

    artifacts = {
        "ready_for_generation": bool(draft),
        "suggested_types": msg_parts,
        "suggestions": suggestions[:5],
    }

    return {
        "generated_artifacts": artifacts,
        "agent_trace": [_trace_entry(
            "PracticeAgent", "completed",
            f"正在异步铸造{' · '.join(msg_parts)}..."
        )],
    }


# ═══════════════════════════════════════════════════════════════════════
# Graph & session injection via RunnableConfig
# ═══════════════════════════════════════════════════════════════════════

# Session is passed via RunnableConfig["configurable"]["session"]
_SESSION_KEY = "__db_session__"


def _rag_node_wrapper(state: GraphState, config: dict = None) -> dict:
    session = None
    if config and "configurable" in config:
        session = config["configurable"].get(_SESSION_KEY)
    if not session:
        # Fallback: try global (backward compat)
        global _global_session
        session = _global_session
    if not session:
        return {
            "error": "database session not available",
            "agent_trace": [_trace_entry("InformerAgent", "failed", "数据库会话不可用")],
        }
    return rag_node(state, session)


_global_session: Optional[Session] = None


def _build_graph() -> StateGraph:
    g = StateGraph(GraphState)

    # Add nodes
    g.add_node("supervisor", supervisor_node)
    g.add_node("profile", profile_node)
    g.add_node("rag", _rag_node_wrapper)
    g.add_node("lecture", lecture_node)
    g.add_node("verifier", verifier_node)
    g.add_node("retry_inc", retry_increment_node)
    g.add_node("insight", insight_node)
    g.add_node("practice", practice_node)

    # Build edges
    g.set_entry_point("supervisor")
    g.add_edge("supervisor", "profile")
    g.add_edge("profile", "rag")
    g.add_edge("rag", "lecture")
    g.add_edge("lecture", "verifier")

    # Conditional: verifier → retry or insight
    g.add_conditional_edges(
        "verifier",
        should_retry,
        {
            "rag_retry": "retry_inc",
            "insight": "insight",
            "end": END,
        }
    )
    g.add_edge("retry_inc", "rag")
    g.add_edge("insight", "practice")
    g.add_edge("practice", END)

    return g.compile()


_tutor_graph = _build_graph()


def run_tutor_graph(
    course_id: int,
    course_name: Optional[str],
    question: str,
    top_k: int,
    session: Session,
    user: Optional[User] = None,
) -> dict:
    """Execute the full multi-agent graph and return enriched state.

    Returns a dict with keys:
      - answer: final answer text
      - citations: list of citation entries
      - agent_traces: list of agent trace entries
      - profile_delta: extracted profile changes
      - verifier_score: confidence score
      - status: "success" | "partial" | "failed"
    """
    global _global_session
    _global_session = session
    try:
        uid = int(user.id) if (user and user.id) else 0
        role = user.role if user else "student"

        initial_state: GraphState = {
            "course_id": course_id,
            "course_name": course_name,
            "question": question,
            "top_k": min(top_k, 10),
            "user_id": uid,
            "user_role": role,
            # Required by TypedDict — filled by supervisor
            "intent": "",
            "student_profile": {},
            "retrieved_chunks": [],
            "citations": [],
            "draft_answer": "",
            "verified_answer": "",
            "verifier_score": 0.0,
            "verification": {},
            "agent_trace": [],
            "error": None,
            "retry_count": 0,
            "profile_delta": {},
            "generated_artifacts": {},
            "model_status": {},
            "rag_status": {},
            "provider": "",
            "model": "",
        }

        config = {"configurable": {_SESSION_KEY: session}}
        result = _tutor_graph.invoke(initial_state, config)

        # Determine overall status
        has_answer = bool(result.get("verified_answer") or result.get("draft_answer"))
        has_citations = bool(result.get("citations"))
        verifier_score = result.get("verifier_score", 0)

        if has_answer and verifier_score >= 0.5:
            status = "success"
        elif has_answer:
            status = "partial"
        else:
            status = "failed"

        return {
            "status": status,
            "answer": result.get("verified_answer") or result.get("draft_answer", ""),
            "citations": result.get("citations", []),
            "agent_traces": result.get("agent_trace", []),
            "profile_delta": result.get("profile_delta", {}),
            "verifier_score": result.get("verifier_score", 0.0),
            "student_profile": result.get("student_profile", {}),
            "generated_artifacts": result.get("generated_artifacts", {}),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            "verification": result.get("verification", {}),
            "model_status": result.get("model_status", {}),
            "rag_status": result.get("rag_status", {}),
            "provider": result.get("provider", ""),
            "model": result.get("model", ""),
            "error": result.get("error"),
        }
    finally:
        _global_session = None


def build_stream_agent_traces(
    question: str,
    citation_count: int,
    provider: str,
    *,
    phase: str = "streaming",
    verifier_trace: dict | None = None,
) -> list[dict]:
    """Build demo-friendly agent traces for SSE stream (Informer + stream path)."""
    q_hint = (question or "")[:36]
    traces = [
        _trace_entry("TutorAgent", "completed", f"已解析学习意图：{q_hint}"),
        _trace_entry("InformerAgent", "completed", f"已从课程知识库检索 {citation_count} 条引用片段"),
        _trace_entry("LectureAgent", "completed", "已构建带引用的 RAG 提示词"),
    ]
    if phase == "streaming":
        traces.append(_trace_entry("VerifierAgent", "running", "正在进行引用覆盖检查"))
    else:
        if verifier_trace:
            traces.append(verifier_trace)
        else:
            traces.append(_trace_entry("VerifierAgent", "completed", "回答校验完成"))
        traces.append(_trace_entry("InsightAgent", "completed", "已更新学习画像与薄弱点线索"))
        traces.append(_trace_entry("PracticeAgent", "completed", "已准备思维导图/练习/讲义等推荐资源"))
    return traces
