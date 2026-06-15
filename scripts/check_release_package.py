#!/usr/bin/env python3
"""Validate the Windows portable release zip without extracting secrets."""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / "dist" / "智学工坊-Windows-便携版.zip"
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|api[_-]?password|apisecret|secret|token)\s*=\s*['\"]?([A-Za-z0-9_\-:]{16,})"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]
INTERNAL_AUDIT_FRAGMENTS = [
    "/reports/",
    "reports/",
    "final_full_audit_after_3b.md",
    "final_qa_audit.md",
    "local_pending_static_qa_fix.diff",
]


def fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def has(names: list[str], suffix: str) -> bool:
    return any(name.endswith(suffix) for name in names)


def main() -> int:
    print("=== Release Package Check ===")
    if not ZIP_PATH.exists():
        return fail(f"zip not found: {ZIP_PATH}")
    print(f"zip: {ZIP_PATH}")

    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = zf.namelist()
        lower_names = [n.lower().replace("\\", "/") for n in names]

        checks = {
            "启动脚本": has(names, "启动智学工坊.bat"),
            "停止脚本": has(names, "停止智学工坊.bat"),
            "README_先看我": has(names, "README_先看我.txt"),
            ".env.example": has(names, ".env.example"),
            "RELEASE_INFO": has(names, "RELEASE_INFO.txt"),
            "后端入口": any(n.endswith("backend/app/demo_main.py") for n in names),
            "前端入口": any(n.endswith("frontend-demo/index.html") for n in names),
        }
        for label, ok in checks.items():
            print(f"{label}: {'OK' if ok else 'MISSING'}")
            if not ok:
                return 1

        forbidden = [n for n in lower_names if "/.git/" in n or "/node_modules/" in n or "/__pycache__/" in n or n.endswith("/.env") or "/.env." in n and not n.endswith(".env.example")]
        forbidden += [n for n in lower_names if "/venv/" in n or "/.venv/" in n or n.endswith(".log")]
        forbidden += [n for n in lower_names if any(fragment in n for fragment in INTERNAL_AUDIT_FRAGMENTS)]
        if forbidden:
            print("Forbidden files:")
            for item in forbidden[:30]:
                print(f" - {item}")
            return 1
        print("forbidden files: OK")

        suspicious: list[str] = []
        for name in names:
            lower = name.lower()
            if not lower.endswith((".py", ".js", ".css", ".html", ".md", ".txt", ".bat", ".example", ".json", ".yml", ".yaml")):
                continue
            if lower.endswith(".env.example") or lower.endswith("readme_先看我.txt"):
                continue
            try:
                text = zf.read(name).decode("utf-8", errors="ignore")
            except Exception:
                continue
            for pattern in SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    snippet = match.group(0).lower()
                    if any(x in snippet for x in [
                        "your", "example", "mock", "你的", "示例", "placeholder",
                        "body.api_key", "settings.", "os.environ", "demo_", "data[", "demo-pass",
                        "_normalize_spark_api_password", "token=\"demo-", "token='demo-",
                    ]):
                        continue
                    suspicious.append(name)
                    break
        if suspicious:
            print("Suspicious secret-like strings:")
            for item in sorted(set(suspicious))[:30]:
                print(f" - {item}")
            return 1
        print("secret scan: OK")

    print("=== RELEASE PACKAGE PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
