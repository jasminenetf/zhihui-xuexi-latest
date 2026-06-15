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
RESOURCE_TYPES = ["lecture_doc", "mindmap", "quiz", "ppt", "study_plan", "video_script", "animation_preview", "reading"]
ANIMATION_TOPICS = [
    ("函数极限", ["x→x0", "f(x)", "A", "趋近"]),
    ("导数定义", ["割线", "切线", "h→0", "f'(x)"]),
    ("定积分", ["小矩形", "累加", "∫", "面积"]),
    ("不定积分", ["原函数", "+C", "反向求导", "F(x)+C"]),
    ("微分方程", ["dy/dx", "初值", "通解", "特解"]),
    ("洛必达法则", ["0/0", "未定式", "求导", "适用条件"]),
]
TEST_PREFIX = "QA_TEST_"
EXPECTED_AGENTS = {
    "ProfileAgent",
    "RetrievalAgent",
    "TutorAgent",
    "ResourceAgent",
    "AssessmentAgent",
    "PlannerAgent",
    "VerifierAgent",
}
PROGRESS_LABELS = [
    "读取学习画像",
    "检索课程知识库",
    "规划资源结构",
    "生成个性化内容",
    "执行 Verifier 检查",
    "保存资源并展示结果",
]


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


def check_knowledge_base_evidence() -> None:
    kb = ROOT / "knowledge_base" / "高等数学上册"
    required = [
        "course_manifest.json",
        "chapter_outline.md",
        "knowledge_points.json",
        "rag_sample_queries.md",
        "resource_grounding_examples.md",
        "README.md",
    ]
    missing = [name for name in required if not (kb / name).exists()]
    assert_true(not missing, f"knowledge base evidence missing files: {missing}")
    manifest = json.loads((kb / "course_manifest.json").read_text(encoding="utf-8"))
    assert_true(manifest.get("course_name") == "高等数学上册", "manifest course_name should be 高等数学上册")
    assert_true(len(manifest.get("chapters") or []) >= 7, "manifest should cover 7 chapters")
    expected_labels = {"学习讲义", "思维导图", "练习题", "PPT 课件", "学习路径", "视频脚本", "动画预览", "拓展阅读"}
    manifest_labels = set(manifest.get("resource_types") or manifest.get("resource_types_supported") or [])
    assert_true(expected_labels.issubset(manifest_labels), f"manifest missing 8 resource labels: {expected_labels - manifest_labels}")
    grounding = manifest.get("grounding_strategy") or {}
    for key in ["chapter_mapping", "knowledge_point_mapping", "rag_retrieval", "verifier_check"]:
        assert_true(grounding.get(key), f"manifest grounding_strategy missing: {key}")
    data = json.loads((kb / "knowledge_points.json").read_text(encoding="utf-8"))
    points = data.get("knowledge_points") or []
    assert_true(len(points) >= 30, "knowledge_points.json should contain at least 30 points")
    assert_true(manifest.get("knowledge_point_count") == len(points), "manifest knowledge_point_count mismatch")
    chapters = {p.get("chapter") for p in points}
    for chapter in ["函数与极限", "导数与微分", "微分中值定理与导数应用", "不定积分", "定积分", "定积分应用", "微分方程"]:
        assert_true(chapter in chapters, f"knowledge base missing chapter points: {chapter}")
    required_point_fields = {"id", "chapter", "name", "prerequisite", "explanation_goal", "common_mistakes", "recommended_resources", "suitable_animation", "suitable_quiz_type"}
    for idx, point in enumerate(points, 1):
        missing_fields = [field for field in required_point_fields if field not in point]
        assert_true(not missing_fields, f"knowledge point {idx} missing fields: {missing_fields}")
        assert_true(point.get("common_mistakes"), f"knowledge point {idx} missing common_mistakes")
        assert_true(point.get("recommended_resources"), f"knowledge point {idx} missing recommended_resources")
    outline = (kb / "chapter_outline.md").read_text(encoding="utf-8")
    for token in ["章节目标", "核心知识点", "常见误区", "推荐资源类型", "前置关系或后续建议"]:
        assert_true(outline.count(token) >= 7, f"chapter outline missing repeated section: {token}")
    rag = (kb / "rag_sample_queries.md").read_text(encoding="utf-8")
    for token in ["函数极限", "导数定义", "洛必达法则", "不定积分", "定积分", "微分方程", "连续", "中值定理"]:
        assert_true(token in rag, f"rag samples missing topic: {token}")
    grounding_examples = (kb / "resource_grounding_examples.md").read_text(encoding="utf-8")
    for token in ["函数极限", "导数定义", "洛必达法则", "定积分定义", "一阶线性微分方程"]:
        assert_true(token in grounding_examples, f"grounding examples missing: {token}")
    print("[PASS] knowledge base evidence")


def check_frontend_static_evidence() -> None:
    js = (ROOT / "frontend-demo" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend-demo" / "app.css").read_text(encoding="utf-8")
    for token in ["多智能体协作轨迹", "学习诊断闭环", "资源生成进度追踪", "不定积分", "微分方程", "洛必达"]:
        assert_true(token in js or token in css, f"frontend missing visible evidence token: {token}")
    for label in PROGRESS_LABELS:
        assert_true(label in js, f"frontend missing generation progress label: {label}")
    for agent in EXPECTED_AGENTS:
        assert_true(agent in js, f"frontend missing agent trace name: {agent}")
    print("[PASS] frontend static evidence")


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
    traces = ask.get("agent_traces") or ask.get("agent_trace") or []
    assert_true(len(traces) >= 7, "agent trace is too weak")
    trace_agents = {str(t.get("agent") or "") for t in traces}
    assert_true(EXPECTED_AGENTS.issubset(trace_agents), f"agent trace missing expected agents: {EXPECTED_AGENTS - trace_agents}")
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
        resource_traces = res.get("agent_traces") or res.get("agent_trace") or []
        assert_true(len(resource_traces) >= 7, f"{typ} missing full agent trace")
        steps = res.get("progress_steps") or res.get("generation_steps") or []
        step_text = text_of(steps)
        assert_true(all(label in step_text for label in PROGRESS_LABELS), f"{typ} missing generation progress steps")
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
        if typ == "animation_preview":
            html_text = text_of(res.get("html") or res.get("content") or (res.get("animation_preview") or {}).get("html"))
            assert_true("<svg" in html_text and "</html>" in html_text, "animation_preview missing standalone HTML/SVG")
        if typ == "reading":
            assert_true(text_of(res.get("content")), "reading content missing")
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
    report = unwrap(request_json("/api/app/learning-report?course_id=1", timeout=60))
    loop = report.get("diagnostic_loop") or report.get("learning_diagnosis_loop") or {}
    for key in ["本次学习主题", "暴露问题", "错因分析", "对应知识点", "推荐复习资源", "下一步学习路径", "掌握度变化", "推荐练习类型"]:
        assert_true(loop.get(key), f"learning report diagnostic loop missing: {key}")
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


def check_animation_preview_resources() -> None:
    for topic, markers in ANIMATION_TOPICS:
        res = unwrap(
            request_json(
                "/api/app/generate",
                "POST",
                {"course_id": 1, "resource_type": "animation_preview", "topic": topic},
                timeout=60,
            )
        )
        assert_true(res.get("resource_type") == "animation_preview", f"{topic} animation has wrong resource_type")
        assert_true(res.get("download_url"), f"{topic} animation missing download_url")
        assert_true(res.get("title") and topic in str(res.get("title")), f"{topic} animation title is not topic-based")
        html_text = text_of(res.get("html") or res.get("content") or (res.get("animation_preview") or {}).get("html"))
        assert_true("<svg" in html_text and "</html>" in html_text, f"{topic} animation is not standalone HTML/SVG")
        assert_true("mp4" not in html_text.lower(), f"{topic} animation should not reference mp4")
        assert_true(any(marker in html_text for marker in markers), f"{topic} animation missing topic markers")
        assert_true("高等数学上册" in html_text, f"{topic} animation missing course basis")
        assert_true("Verifier" in html_text, f"{topic} animation missing verifier marker")
        downloaded = request_text(str(res["download_url"]), timeout=60)
        assert_true("<!doctype html>" in downloaded.lower(), f"{topic} animation download is not HTML")
        assert_true("<svg" in downloaded, f"{topic} animation download missing SVG")

    video = unwrap(
        request_json(
            "/api/app/generate",
            "POST",
            {"course_id": 1, "resource_type": "video_script", "topic": "函数极限"},
            timeout=60,
        )
    )
    preview = video.get("animation_preview") or {}
    assert_true(preview.get("html") and "<svg" in preview.get("html"), "video_script missing embedded animation preview")
    print("[PASS] animation preview resources")


def check_static_policy_and_forbidden_terms() -> None:
    checked_roots = [
        ROOT / "README.md",
        ROOT / "docs" / "final",
        ROOT / "knowledge_base",
        ROOT / "release",
        ROOT / "scripts" / "build_final_judge_package.py",
        ROOT / "backend" / ".env.example",
        ROOT / "backend" / "app" / "core" / "config.py",
    ]
    old_terms = [
        "https://spark-api-open.xf-yun.com/v1",
        "generalv3.5",
        "/chat/completions 作为推荐 Base URL",
        "只有 5 类资源",
        "只有 6 类资源",
        "不支持动画",
        "完整教材 PDF 已公开提交",
        "视频已完成",
    ]
    hits: list[str] = []
    for root in checked_roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".txt", ".py", ".js", ".json", ".example"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for term in old_terms:
                if term in text:
                    hits.append(f"{path.relative_to(ROOT).as_posix()}: {term}")
    assert_true(not hits, "old public wording found:\n" + "\n".join(hits[:20]))
    print("[PASS] static wording policy")


def check_package_forbidden_hits_if_present() -> None:
    import io
    import zipfile

    forbidden_substrings = [
        ".git/",
        "node_modules/",
        "venv/",
        ".venv/",
        "__pycache__/",
        ".pytest_cache/",
        "logs/",
        "reports/",
        "final_full_audit_after_3b.md",
        "final_qa_audit.md",
        "local_pending_static_qa_fix.diff",
        "Codex提示词",
        "个人备稿",
        "Actions 失败日志",
    ]
    forbidden_exact_names = {".env"}
    zip_paths = [
        ROOT / "dist" / "智学工坊-Windows-便携版.zip",
        ROOT / "dist" / "智学工坊_评委提交包.zip",
        ROOT / "final_delivery" / "01_提交给评委" / "04_源码与数据" / "智学工坊_源码与数据.zip",
    ]
    hits: list[str] = []

    def scan_zip(src: Path | io.BytesIO, label: str) -> None:
        with zipfile.ZipFile(src) as zf:
            for name in zf.namelist():
                normalized = name.replace("\\", "/")
                lower = normalized.lower()
                base_name = normalized.rsplit("/", 1)[-1]
                if base_name in forbidden_exact_names or any(item.lower() in lower for item in forbidden_substrings):
                    hits.append(f"{label}:{normalized}")
                if lower.endswith(".zip"):
                    scan_zip(io.BytesIO(zf.read(name)), f"{label}!{normalized}")

    for path in zip_paths:
        if path.exists():
            scan_zip(path, path.relative_to(ROOT).as_posix())
    assert_true(not hits, "forbidden package hits:\n" + "\n".join(hits[:20]))
    print("[PASS] package forbidden hits")


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
        if any(part in {".git", ".venv", "venv", "__pycache__", "node_modules", "data", ".local", "release_build", "final_delivery", "dist"} for part in path.parts):
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
        check_knowledge_base_evidence()
        check_frontend_static_evidence()
        check_p0_smoke()
        resources = check_learning_loop()
        check_downloads(resources)
        check_animation_preview_resources()
        check_stage_3a5_definition_quality()
        check_static_policy_and_forbidden_terms()
        check_package_forbidden_hits_if_present()
        check_secret_hygiene()
    except QaFailure as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("=== DEEP QA PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
