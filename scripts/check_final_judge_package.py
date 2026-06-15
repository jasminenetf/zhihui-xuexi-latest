#!/usr/bin/env python3
"""Validate final judge and private prep packages."""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JUDGE_ZIP = ROOT / "dist" / "智学工坊_评委提交包.zip"
PRIVATE_ZIP = ROOT / "dist" / "智学工坊_个人备稿包_不提交.zip"

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|api[_-]?password|apisecret|api[_-]?secret|secret|token)\s*=\s*['\"]?([A-Za-z0-9_\-:]{16,})"),
    re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-.]{20,})"),
    re.compile(r"(sk-[A-Za-z0-9]{20,})"),
]


def fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def is_false_positive(value: str, context: str) -> bool:
    lower = value.lower()
    context_lower = context.lower()
    if any(x in lower for x in ["your", "mock", "example", "placeholder", "changeme", "demo", "你的", "示例"]):
        return True
    if lower.startswith("_normalize_") or "normalize" in lower:
        return True
    if "settings." in context_lower or "os.getenv" in context_lower or "os.environ" in context_lower:
        return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) and "_" in value:
        return True
    return False


def secret_hits(zf: zipfile.ZipFile, names: list[str]) -> list[str]:
    hits: list[str] = []
    for name in names:
        lower = name.lower()
        if lower.endswith(".env.example"):
            continue
        if not lower.endswith((".py", ".js", ".css", ".html", ".md", ".txt", ".bat", ".sh", ".json", ".yml", ".yaml", ".example")):
            continue
        text = zf.read(name).decode("utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(2) if (match.lastindex or 0) >= 2 else match.group(1)
                if is_false_positive(value, match.group(0)):
                    continue
                hits.append(f"{name}: {match.group(0)[:80]}")
    return hits


def contains(names: list[str], fragment: str) -> bool:
    return any(fragment in name for name in names)


def validate_judge() -> int:
    if not JUDGE_ZIP.exists():
        return fail(f"judge package not found: {JUDGE_ZIP}")
    with zipfile.ZipFile(JUDGE_ZIP) as zf:
        names = zf.namelist()
        lower = [n.lower().replace("\\", "/") for n in names]
        required = {
            "Windows 便携版 zip": "03_可运行系统/智学工坊-Windows-便携版.zip",
            "源码与数据 zip": "04_源码与数据/智学工坊_源码与数据.zip",
            "提交文件清单": "07_提交清单/提交文件清单.md",
            "系统文档目录": "05_系统文档/智学工坊_系统开发说明书.md",
            "AI Coding 工具说明": "06_AI_Coding说明/智学工坊_AI_Coding工具使用说明.md",
            "待补文件清单": "03_待补文件/缺失文件清单.md",
            "不要提交说明": "99_不要提交_临时文件说明/不要提交说明.md",
        }
        for label, fragment in required.items():
            ok = contains(names, fragment)
            print(f"{label}: {'OK' if ok else 'MISSING'}")
            if not ok:
                return 1

        forbidden_fragments = [
            "/.git/",
            "/node_modules/",
            "/venv/",
            "/.venv/",
            "/__pycache__/",
            "/.pytest_cache/",
            "/logs/",
            "02_个人备稿_不提交给评委",
            "codex提示词",
            "06_codex",
            "final_full_audit_after_3b.md",
            "final_qa_audit.md",
            "local_pending_static_qa_fix.diff",
        ]
        forbidden = [n for n in lower if any(f.lower() in n for f in forbidden_fragments)]
        forbidden += [n for n in lower if n.endswith("/.env") or ("/.env." in n and not n.endswith(".env.example"))]
        if forbidden:
            print("Forbidden judge package entries:")
            for item in forbidden[:40]:
                print(f" - {item}")
            return 1
        print("forbidden judge entries: OK")

        hits = secret_hits(zf, names)
        if hits:
            print("Suspicious secrets in judge package:")
            for hit in hits[:40]:
                print(f" - {hit}")
            return 1
        print("judge secret scan: OK")
    return 0


def validate_private() -> int:
    if not PRIVATE_ZIP.exists():
        return fail(f"private package not found: {PRIVATE_ZIP}")
    with zipfile.ZipFile(PRIVATE_ZIP) as zf:
        names = zf.namelist()
        required = [
            "01_答辩讲稿",
            "02_演示视频稿",
            "06_Codex提示词",
            "04_复现清单",
        ]
        for fragment in required:
            ok = contains(names, fragment)
            print(f"private {fragment}: {'OK' if ok else 'MISSING'}")
            if not ok:
                return 1
        forbidden = [n for n in names if "03_待补文件" in n or "99_不要提交_临时文件说明" in n or "01_提交给评委" in n]
        if forbidden:
            print("Unexpected entries in private package:")
            for item in forbidden[:30]:
                print(f" - {item}")
            return 1
    return 0


def main() -> int:
    print("=== Final Judge Package Check ===")
    if validate_judge() != 0:
        return 1
    if validate_private() != 0:
        return 1
    print("JUDGE PACKAGE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
