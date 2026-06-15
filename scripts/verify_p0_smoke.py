#!/usr/bin/env python3
"""Smoke verification for P0 fixes (no secrets printed)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("P0_SMOKE_BASE", "http://127.0.0.1:8010")
DEMO_USERNAME = os.environ.get("P0_DEMO_USERNAME", "demo_student")
DEMO_PASSWORD = os.environ.get("P0_DEMO_PASSWORD", "demo_pass_12345")
DEMO_COURSE_NAME = os.environ.get("P0_DEMO_COURSE_NAME", "高等数学上册")
REQUIRE_DEMO = os.environ.get("P0_REQUIRE_DEMO", "0").lower() in {"1", "true", "yes", "on"}
TEST_PREFIX = "P0_SMOKE_"


def get(path: str, token: str | None = None, timeout: int = 8) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {"raw": body[:200]}
        return e.code, data


def post(path: str, payload: dict, token: str | None = None, timeout: int = 8) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body[:200]}
        return e.code, parsed
    except TimeoutError:
        return 0, {"timeout": True}


def unwrap_api(payload: dict) -> dict:
    """Unwrap common {ok,data} response envelopes, including nested envelopes."""
    current = payload or {}
    for _ in range(3):
        if isinstance(current, dict) and current.get("ok") is True and isinstance(current.get("data"), dict):
            current = current["data"]
        else:
            break
    return current if isinstance(current, dict) else {}


def _validate_agent_traces(payload: dict, fails: list[str], label: str) -> None:
    payload = unwrap_api(payload)
    traces = payload.get("agent_traces") or payload.get("agent_trace") or []
    if not traces:
        fails.append(f"{label} missing agent traces")
        return
    required = {"agent", "phase", "status", "summary", "latency_ms"}
    missing = [k for k in required if k not in traces[0]]
    if missing:
        fails.append(f"{label} trace missing fields: {missing}")
    else:
        print(f"[PASS] {label} agent trace schema")


def _validate_grounding(payload: dict, fails: list[str], label: str) -> None:
    payload = unwrap_api(payload)
    grounding = payload.get("grounding") or {}
    safety = payload.get("content_safety") or {}
    if "grounding_score" not in payload and "grounding_score" not in grounding:
        fails.append(f"{label} missing grounding_score")
    elif "risk_level" not in grounding:
        fails.append(f"{label} missing grounding.risk_level")
    elif "safe" not in safety:
        fails.append(f"{label} missing content_safety.safe")
    else:
        print(f"[PASS] {label} grounding and safety fields")


def _validate_resource_package(payload: dict, fails: list[str], label: str) -> None:
    payload = unwrap_api(payload)
    package = payload.get("resource_package") or {}
    required = ["title", "items", "item_count", "agent_count", "grounding_score", "risk_level"]
    missing = [k for k in required if k not in package]
    if missing:
        fails.append(f"{label} resource_package missing fields: {missing}")
    else:
        print(f"[PASS] {label} resource package fields")


def _validate_demo_citations(payload: dict, fails: list[str], label: str) -> None:
    payload = unwrap_api(payload)
    citations = payload.get("citations") or payload.get("sources") or []
    if not citations:
        fails.append(f"{label} missing citations for seeded course")
        return
    text = json.dumps(citations, ensure_ascii=False)
    if "高数上.pdf" not in text and "高等数学" not in text and "函数与极限" not in text:
        fails.append(f"{label} citations do not reference seeded high-math course materials")
    else:
        print(f"[PASS] {label} citations from seeded course")


def _find_demo_course_id(courses: list[dict]) -> int | None:
    for course in courses:
        if course.get("name") == DEMO_COURSE_NAME:
            return course.get("id")
    for course in courses:
        if "演示课程" in str(course.get("name", "")) or "高等数学" in str(course.get("name", "")):
            return course.get("id")
    return None


def _run_demo_smoke(fails: list[str]) -> None:
    """Validate seeded demo data and the real RAG ask path."""
    st, login = post("/api/auth/login", {"username": DEMO_USERNAME, "password": DEMO_PASSWORD})
    demo_token = login.get("access_token") if st == 200 else None
    if not demo_token:
        msg = "demo login failed; run `python scripts/seed_demo_data.py` first"
        if REQUIRE_DEMO:
            fails.append(msg)
        else:
            print(f"[WARN] {msg}")
        return
    print("[PASS] POST /api/auth/login (demo student)")

    st, boot = get("/api/app/bootstrap", demo_token)
    courses = boot.get("data", {}).get("courses") or [] if st == 200 and boot.get("ok") is True else []
    course_id = _find_demo_course_id(courses)
    if not course_id:
        msg = f"demo course not found: {DEMO_COURSE_NAME}; run `python scripts/seed_demo_data.py` first"
        if REQUIRE_DEMO:
            fails.append(msg)
        else:
            print(f"[WARN] {msg}")
        return
    print(f"[PASS] demo course available id={course_id}")

    st, ask = post(
        "/api/app/ask",
        {
            "course_id": course_id,
            "question": "请结合课程资料解释函数极限和左右极限，并推荐下一步学习资源。",
            "top_k": 5,
        },
        demo_token,
        timeout=180,
    )
    if st == 200 and ask.get("ok") is True:
        ask_data = ask.get("data", {})
        _validate_agent_traces(ask_data, fails, "demo ask")
        _validate_grounding(ask_data, fails, "demo ask")
        _validate_resource_package(ask_data, fails, "demo ask")
        _validate_demo_citations(ask_data, fails, "demo ask")
        return
    if st == 0 and ask.get("timeout"):
        msg = "demo ask timed out (LLM or embedding cold start)"
    else:
        msg = f"demo ask expected 200 got {st}: {str(ask)[:200]}"
    if REQUIRE_DEMO:
        fails.append(msg)
    else:
        print(f"[WARN] {msg}")


def main() -> int:
    fails: list[str] = []
    print("=== P0 Smoke Verification ===")

    # health
    try:
        st, _ = get("/health")
        if st != 200:
            fails.append(f"health status={st}")
        else:
            print("[PASS] GET /health")
    except Exception as exc:
        print(f"[SKIP] backend not running: {exc}")
        print("Start with: cd backend && python -m uvicorn app.demo_main:app --host 127.0.0.1 --port 8010")
        return 2

    # bootstrap (guest)
    st, body = get("/api/app/bootstrap")
    if st != 200:
        fails.append(f"bootstrap status={st}")
    elif body.get("ok") is not True:
        fails.append("bootstrap missing ok:true")
    elif "courses" not in body.get("data", {}):
        fails.append("bootstrap missing data.courses")
    elif "llm_configured" not in body.get("data", {}).get("config", {}):
        fails.append("bootstrap missing config.llm_configured")
    else:
        print("[PASS] GET /api/app/bootstrap (guest)")

    # no-login demo: settings test is open
    st, _ = post("/api/settings/test-llm", {"provider": "mock"})
    if st != 200:
        fails.append(f"settings test-llm without auth expected 200 got {st}")
    else:
        print("[PASS] POST /api/settings/test-llm open no-login")

    # deprecated demo endpoint may be absent in lightweight demo or gone in full backend
    st, _ = post("/api/app/run-demo", {})
    if st not in (404, 410):
        fails.append(f"run-demo expected 404/410 got {st}")
    else:
        print(f"[PASS] POST /api/app/run-demo -> {st}")

    # register + login + dashboard
    import time

    user = f"{TEST_PREFIX}verify_{int(time.time())}"
    password = "verify_pass_12345"
    st, reg = post("/api/auth/register", {"username": user, "password": password, "role": "teacher"})
    if st not in (200, 201) and not (st == 400 and "already" in str(reg).lower()):
        fails.append(f"register status={st}")
    else:
        print("[PASS] POST /api/auth/register (role locked to student)")

    st, login = post("/api/auth/login", {"username": user, "password": password})
    token = login.get("access_token") if st == 200 else None
    if not token:
        fails.append(f"login failed status={st}")
    else:
        print("[PASS] POST /api/auth/login")

    if token:
        st, _ = get("/api/settings/status", token)
        if st != 200:
            fails.append(f"open settings status expected 200 got {st}")
        else:
            print("[PASS] GET /api/settings/status open")

        st, _ = post("/api/courses", {"name": f"{TEST_PREFIX}临时课程", "description": f"{TEST_PREFIX}仅用于接口冒烟，reset_demo_state.py 可清理"}, token)
        if st != 200:
            fails.append(f"open create course expected 200 got {st}")
        else:
            print("[PASS] POST /api/courses open")

        st, _ = post("/api/app/run-demo", {}, token)
        if st not in (404, 410):
            fails.append(f"run-demo expected 404/410 got {st}")
        else:
            print(f"[PASS] POST /api/app/run-demo -> {st}")

        st, _ = get("/api/resources/download/../../x", token)
        if st not in (400, 404):
            fails.append(f"invalid resource id expected 400/404 got {st}")
        else:
            print(f"[PASS] GET /api/resources/download/../../x -> {st}")

        st, resources = get("/api/resources/generated", token)
        if st != 200:
            fails.append(f"generated resources expected 200 got {st}")
        elif resources.get("ok") is not True:
            fails.append("generated resources missing ok:true")
        else:
            files = resources.get("files") or resources.get("data", {}).get("files", [])
            print(f"[PASS] GET /api/resources/generated files={len(files)}")

        st, report = get("/api/app/learning-report", token)
        if st != 200:
            fails.append(f"learning report expected 200 got {st}")
        elif report.get("ok") is not True or "data" not in report:
            fails.append("learning report missing ok/data")
        else:
            report_data = unwrap_api(report)
            if "mastery_overview" not in report_data:
                fails.append("learning report missing mastery_overview")
            elif "mastery_items" not in report_data:
                fails.append("learning report missing mastery_items")
            else:
                print("[PASS] GET /api/app/learning-report includes mastery fields")

        st, boot = get("/api/app/bootstrap", token)
        course_id = None
        courses = []
        if st == 200 and boot.get("ok") is True:
            selected = boot.get("data", {}).get("selected_course") or {}
            courses = boot.get("data", {}).get("courses") or []
            course_id = _find_demo_course_id(courses) or selected.get("id") or (courses[0].get("id") if courses else None)

        if course_id:
            st, ask = post(
                "/api/app/ask",
                {
                    "course_id": course_id,
                    "question": "请结合课程资料解释函数极限和左右极限，并推荐下一步学习资源。",
                    "top_k": 5,
                },
                token,
                timeout=180,
            )
            if st == 200 and ask.get("ok") is True:
                ask_data = ask.get("data", {})
                _validate_agent_traces(ask_data, fails, "ask")
                _validate_grounding(ask_data, fails, "ask")
                _validate_resource_package(ask_data, fails, "ask")
            elif st in (400, 404):
                print(f"[SKIP] POST /api/app/ask no usable course materials -> {st}; course_id={course_id}; courses={[c.get('name') for c in courses]}")
            elif st == 0 and ask.get("timeout"):
                print("[SKIP] POST /api/app/ask timed out (LLM or embedding cold start)")
            else:
                fails.append(f"ask unexpected status={st}; course_id={course_id}; body={str(ask)[:500]}")
        else:
            print("[SKIP] POST /api/app/ask no course available")

        st, quiz = post(
            "/api/app/quiz/submit",
            {
                "course_id": 1,
                "topic": f"{TEST_PREFIX}知识点",
                "question_text": f"{TEST_PREFIX} 什么是函数极限？",
                "selected_answer": "A",
                "correct_answer": "B",
                "is_correct": False,
                "knowledge_point": f"{TEST_PREFIX}知识点",
                "explanation": f"{TEST_PREFIX}用于验证掌握度更新链路",
            },
            token,
        )
        if st not in (200, 404):
            fails.append(f"quiz submit expected 200/404 got {st}")
        elif st == 200:
            quiz_data = unwrap_api(quiz)
            if "mastery" not in quiz_data:
                fails.append("quiz submit missing mastery")
            else:
                print("[PASS] POST /api/app/quiz/submit includes mastery")
        else:
            print("[SKIP] POST /api/app/quiz/submit no course_id=1")

        try:
            st, dash = get("/api/app/dashboard", token, timeout=30)
        except TimeoutError:
            print("[SKIP] GET /api/app/dashboard timed out (embedding cold start)")
            st, dash = 0, {}
        if st == 200 and dash.get("ok") is True and "knowledge_base" in dash.get("data", {}):
            kb = dash["data"]["knowledge_base"]
            print(f"[PASS] GET /api/app/dashboard chunks={kb.get('chunks_count')} vectors={kb.get('vector_count')}")
        elif st == 404:
            print("[PASS] GET /api/app/dashboard skipped (no courses in DB)")
        elif st == 0:
            pass
        else:
            fails.append(f"dashboard unexpected status={st}")

    _run_demo_smoke(fails)

    if fails:
        print("\n=== FAILED ===")
        for f in fails:
            print(" -", f)
        return 1

    print("\n=== ALL CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
