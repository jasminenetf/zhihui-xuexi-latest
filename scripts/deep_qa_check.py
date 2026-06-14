"""Deep QA gate for the competition demo.

This script is intentionally local and lightweight:
- no real LLM call is required;
- it assumes the demo backend is already running on 127.0.0.1:8010;
- it checks the current high-value P0/P1 learning loop.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("DEEP_QA_BASE", "http://127.0.0.1:8010").rstrip("/")
QUESTION = "我不理解函数极限，讲清定义、常见误区，并给一个例题"
RESOURCE_TYPES = ["lecture_doc", "mindmap", "quiz", "ppt", "study_plan", "video_script"]
TEST_PREFIX = "QA_TEST_"


class QaFailure(RuntimeError):
    pass


def run_cmd(args: list[str], timeout: int = 90) -> str:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        shell=False,
    )
    if proc.returncode != 0:
        raise QaFailure(f"command failed: {' '.join(args)}\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


def request_json(path: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 180) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise QaFailure(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise QaFailure(f"{method} {path} failed: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QaFailure(f"{method} {path} returned non-json: {raw[:200]}") from exc


def request_text(path: str, timeout: int = 60) -> str:
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise QaFailure(f"download {path} failed: {exc}") from exc


def unwrap(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("ok") is True and isinstance(data.get("data"), dict):
        return data["data"]
    return data


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise QaFailure(message)


def text_of(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def check_syntax() -> None:
    run_cmd([sys.executable, "-m", "py_compile", "backend/app/demo_main.py"])
    run_cmd(["node", "--check", "frontend-demo/app.js"])
    print("[PASS] syntax checks")


def check_p0_smoke() -> None:
    env = os.environ.copy()
    env["P0_SMOKE_BASE"] = BASE
    proc = subprocess.run(
        [sys.executable, "scripts/verify_p0_smoke.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        env=env,
    )
    if proc.returncode != 0 or "ALL CHECKS PASSED" not in proc.stdout:
        raise QaFailure(f"P0 smoke failed\n{proc.stdout}\n{proc.stderr}")
    print("[PASS] P0 smoke")


def check_learning_loop() -> list[dict[str, Any]]:
    ask = unwrap(
        request_json(
            "/api/app/ask",
            "POST",
            {"course_id": 1, "question": QUESTION},
            timeout=180,
        )
    )
    items = (ask.get("resource_package") or {}).get("items") or []
    package_topic = (ask.get("resource_package") or {}).get("topic")
    assert_true(package_topic and QUESTION not in str(package_topic), "ask resource package topic still uses raw question")
    types = {item.get("type") for item in items}
    missing = [typ for typ in RESOURCE_TYPES if typ not in types]
    assert_true(not missing, f"ask resource package missing types: {missing}")
    assert_true((ask.get("student_profile") or {}).get("profile_version", 0) >= 1, "profile did not update after ask")
    assert_true(len(ask.get("agent_traces") or ask.get("agent_trace") or []) >= 4, "agent trace is too weak")
    risk = (ask.get("grounding") or {}).get("risk_level")
    provider = str(ask.get("provider") or "").lower()
    if provider == "mock":
        assert_true(risk in {"medium", "high"}, "mock answer must not be marked low risk")
    else:
        assert_true(risk in {"low", "medium"}, "online answer risk should be low/medium")

    generated: list[dict[str, Any]] = []
    for typ in RESOURCE_TYPES:
        res = unwrap(
            request_json(
                "/api/app/generate",
                "POST",
                {"course_id": 1, "resource_type": typ, "topic": QUESTION},
                timeout=180,
            )
        )
        assert_true(res.get("download_url"), f"{typ} missing download_url")
        assert_true((res.get("verifier") or {}).get("status") == "passed", f"{typ} verifier not passed")
        assert_true((res.get("context") or {}).get("chapter"), f"{typ} missing chapter context")
        assert_true(QUESTION not in text_of(res.get("title")), f"{typ} title contains raw question")
        if typ == "mindmap":
            assert_true(bool(res.get("tree")), "mindmap missing readable tree")
        if typ == "quiz":
            assert_true(len(res.get("items") or []) >= 3, "quiz should contain at least 3 items")
            assert_true(all(q.get("explanation") for q in res.get("items") or []), "quiz explanations missing")
            assert_true(all(QUESTION not in text_of(q.get("question")) for q in res.get("items") or []), "quiz question contains raw question")
        if typ == "study_plan":
            steps = ((res.get("study_plan") or {}).get("steps") or [])
            assert_true(len(steps) >= 4, "study plan should contain at least 4 steps")
            assert_true(all(step.get("check_standard") for step in steps), "study plan missing check standards")
        if typ == "ppt":
            assert_true((res.get("slide_count") or 0) >= 6, "ppt markdown deck should contain enough slides")
        if typ == "video_script":
            video_text = text_of(res.get("content")) + text_of(res.get("video_script")) + text_of(res.get("scenes"))
            assert_true("分镜" in video_text or "旁白" in video_text or "视频" in video_text, "video_script missing video script markers")
            assert_true(all(word in video_text for word in ["画面", "旁白", "板书", "易错"]), "video_script missing scene fields")
            assert_true(QUESTION not in video_text, "video_script content contains raw question")
        generated.append(res)

    listed = unwrap(request_json("/api/resources/generated", timeout=60))
    files = listed.get("files") or []
    listed_types = {f.get("resource_type") or f.get("type") for f in files}
    missing_listed = [typ for typ in RESOURCE_TYPES if typ not in listed_types]
    assert_true(not missing_listed, f"generated resource center missing types: {missing_listed}")

    wrong = request_json(
        "/api/app/quiz/submit",
        "POST",
        {
            "course_id": 1,
            "topic": f"{TEST_PREFIX}函数极限",
            "question_text": f"{TEST_PREFIX} 极限存在是否要求函数在该点有定义？",
            "selected_answer": "要求",
            "correct_answer": "不要求",
            "is_correct": False,
            "knowledge_point": f"{TEST_PREFIX}函数极限",
            "explanation": f"{TEST_PREFIX} 极限研究趋近过程，不要求该点函数值存在。",
        },
        timeout=60,
    )
    assert_true((wrong.get("mastery") or {}).get("mastery_score") == 0.48, "wrong answer mastery not updated")
    assert_true((wrong.get("detailed_feedback") or {}).get("correct_logic"), "wrong answer detailed feedback missing")
    print("[PASS] ask -> resources -> quiz feedback loop")
    return generated


def check_downloads(resources: list[dict[str, Any]]) -> None:
    for res in resources:
        text = request_text(str(res["download_url"]), timeout=60)
        typ = res.get("resource_type") or res.get("type")
        assert_true("Verifier" in text, f"{typ} download missing verifier section")
        assert_true("高数上.pdf" in text or "高等数学上册" in text, f"{typ} download missing course evidence")
        assert_true(QUESTION not in text.splitlines()[0], f"{typ} download title contains raw question")
        if typ == "ppt":
            assert_true("学生辅助学习版 PPT" in text, "ppt markdown download missing student deck marker")
        if typ == "mindmap":
            assert_true("可读知识结构" in text, "mindmap download missing readable structure")
        if typ == "video_script":
            assert_true("分镜脚本" in text and "旁白稿" in text, "video_script download missing script structure")
    print("[PASS] resource downloads")


def check_stage_3a5_definition_quality() -> None:
    sample = "定积分的定义"
    ask = unwrap(request_json("/api/app/ask", "POST", {"course_id": 1, "question": sample}, timeout=180))
    answer = text_of(ask.get("answer"))
    marker_groups = [
        ("一句话直答", "先懂一句话"),
        ("定义拆解",),
        ("符号翻译",),
        ("常见误区",),
        ("小例题", "例题"),
        ("下一步建议",),
    ]
    for group in marker_groups:
        assert_true(any(marker in answer for marker in group), f"definition answer missing marker: {'/'.join(group)}")
    assert_true("高数重要概念" not in answer[:80], "definition answer starts with generic importance")
    assert_true("$$" not in answer and "\\int" not in answer and "\\sum" not in answer, "definition answer exposes raw LaTeX")

    lecture = unwrap(request_json("/api/app/generate", "POST", {"course_id": 1, "resource_type": "lecture_doc", "topic": sample}, timeout=180))
    doc = lecture.get("lecture_doc") or {}
    for key in [
        "learning_problem",
        "one_sentence_answer",
        "intuition_explainer",
        "formal_definition",
        "symbol_translation_items",
        "key_distinctions",
        "worked_example",
        "common_mistakes",
        "quick_self_check",
        "next_step",
    ]:
        assert_true(bool(doc.get(key)), f"lecture_doc missing structured field: {key}")
    assert_true("讲义模块" not in text_of(lecture), "lecture_doc still contains weak module naming")
    lecture_text = text_of(doc)
    assert_true("定义里的关键符号或关键词" not in lecture_text, "lecture_doc symbol translation still uses generic template")
    for symbol in ["∫", "dx", "Σ", "lim"]:
        assert_true(symbol in lecture_text, f"integral lecture missing concrete symbol: {symbol}")

    limit_lecture = unwrap(request_json("/api/app/generate", "POST", {"course_id": 1, "resource_type": "lecture_doc", "topic": "函数极限的定义"}, timeout=180))
    limit_text = text_of(limit_lecture.get("lecture_doc") or {})
    for symbol in ["lim", "x→x0", "A", "左极限", "去心邻域", "0/0"]:
        assert_true(symbol in limit_text, f"limit lecture missing concrete symbol: {symbol}")
    assert_true("定义里的关键符号或关键词" not in limit_text, "limit lecture symbol translation still uses generic template")

    ppt = unwrap(request_json("/api/app/generate", "POST", {"course_id": 1, "resource_type": "ppt", "topic": sample}, timeout=180))
    slides = ppt.get("slides") or []
    assert_true(len(slides) >= 8, "student ppt should contain at least 8 slides")
    assert_true(all(s.get("slide_goal") and s.get("key_takeaway") for s in slides), "ppt slides missing slide_goal/key_takeaway")
    assert_true(any(s.get("self_check") for s in slides), "ppt missing self_check")
    assert_true(any(s.get("common_mistake") for s in slides), "ppt missing common_mistake")

    status = request_json("/api/settings/status", timeout=30)
    status_data = status.get("data") if status.get("ok") is True and isinstance(status.get("data"), dict) else status
    if ((status_data.get("model_status") or {}).get("label") == "Spark 真实生成"):
        fresh = unwrap(request_json("/api/app/generate", "POST", {"course_id": 1, "resource_type": "lecture_doc", "topic": sample}, timeout=180))
        assert_true(fresh.get("generated_by") == "spark", "spark active resource should be marked generated_by=spark")
        assert_true(fresh.get("fallback_used") is False, "spark active resource should not be fallback")
    print("[PASS] stage 3A.5 definition quality")


def check_secret_hygiene() -> None:
    allow_files = {
        "README.md",
        ".env.example",
        "backend/.env.example",
        "docs/final/模型与配置说明.md",
        "docs/final/朋友下载运行说明.md",
    }
    suspicious: list[str] = []
    patterns = [
        re.compile(r"(?i)(api[_-]?key|api[_-]?password|secret)\s*=\s*['\"]?([A-Za-z0-9_\-:]{16,})"),
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in allow_files:
            continue
        if any(part in {".git", ".venv", "venv", "__pycache__", "node_modules", "data", ".local"} for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".js", ".css", ".md", ".txt", ".bat", ".sh", ".yml", ".yaml", ".json", ".example"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                value = match.group(match.lastindex or 0)
                lower_value = value.lower()
                if (
                    "your" in lower_value
                    or "mock" in lower_value
                    or "example" in lower_value
                    or "normalize" in lower_value
                    or lower_value.startswith("_")
                ):
                    continue
                suspicious.append(f"{rel}: {match.group(0)[:80]}")
    assert_true(not suspicious, "possible secrets found:\n" + "\n".join(suspicious[:20]))
    print("[PASS] secret hygiene")


def main() -> int:
    print(f"=== Deep QA Check ({BASE}) ===")
    try:
        health = request_json("/health", timeout=5)
        assert_true(health.get("ok") is True, "backend health not ok")
        check_syntax()
        check_p0_smoke()
        resources = check_learning_loop()
        check_downloads(resources)
        check_stage_3a5_definition_quality()
        check_secret_hygiene()
    except QaFailure as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("=== DEEP QA PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
