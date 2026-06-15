#!/usr/bin/env python3
"""Build a clean Windows portable release package.

The demo frontend is static, so this release does not require Node on the
target machine. It packages the FastAPI demo backend, frontend-demo files,
portable launch scripts, examples, and release metadata.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "release_build" / "智学工坊-Windows-便携版"
ZIP_PATH = DIST_DIR / "智学工坊-Windows-便携版.zip"

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".codex",
    ".cursor",
    ".local",
    "logs",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".zip", ".tar", ".gz", ".7z"}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|api[_-]?password|apisecret|secret|token)\s*=\s*['\"]?([A-Za-z0-9_\-:]{16,})"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]
ALLOW_SECRET_FILES = {".env.example", "backend/.env.example", "release/.env.example"}


def run(args: list[str], *, timeout: int = 60, allow_fail: bool = False) -> str:
    proc = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout, shell=False)
    if proc.returncode != 0 and not allow_fail:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{proc.stdout}\n{proc.stderr}")
    return (proc.stdout or "").strip()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def should_skip(path: Path) -> bool:
    parts = set(path.relative_to(ROOT).parts)
    if parts & EXCLUDE_DIRS:
        return True
    if path.name in {".env"} or path.name.startswith(".env."):
        return path.name != ".env.example"
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def scan_secrets(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = rel(path)
        if relative in ALLOW_SECRET_FILES or path.name == ".env.example":
            continue
        if path.suffix.lower() not in {".py", ".js", ".css", ".html", ".md", ".txt", ".bat", ".example", ".json", ".yml", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                lower = snippet.lower()
                if any(x in lower for x in [
                    "your", "example", "mock", "你的", "示例", "placeholder",
                    "body.api_key", "settings.", "os.environ", "demo_", "data[", "demo-pass",
                    "_normalize_spark_api_password", "token=\"demo-", "token='demo-",
                ]):
                    continue
                findings.append(relative)
                break
    return sorted(set(findings))


def copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        if should_skip(path):
            continue
        target = dst / path.relative_to(src)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def copy_project_files() -> None:
    for folder in ["backend", "frontend-demo", "scripts", "docs", "reports", "tests"]:
        src = ROOT / folder
        if src.exists():
            copy_tree(src, BUILD_DIR / folder)

    for file_name in [
        "README.md",
        "RUNBOOK.md",
        "PROJECT_BRIEF.md",
        "TASKS.md",
        "DECISIONS.md",
        "OSS_LICENSES.md",
        "SUBMISSION_CHECKLIST.md",
        ".env.example",
        "启动智能学习Agent.bat",
        "停止智能学习Agent.bat",
    ]:
        src = ROOT / file_name
        if src.exists() and not should_skip(src):
            target = BUILD_DIR / file_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)

    release_src = ROOT / "release"
    if release_src.exists():
        copy_tree(release_src, BUILD_DIR)

    (BUILD_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "data").mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "outputs").mkdir(parents=True, exist_ok=True)


def write_release_info(branch: str, commit: str) -> None:
    py_ver = sys.version.split()[0]
    node_ver = run(["node", "--version"], allow_fail=True) or "not required"
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info = f"""智学工坊 Windows 便携版
构建时间: {now}
分支: {branch}
Commit: {commit}
Python版本: {py_ver}
Node版本: {node_ver}（运行便携版不需要 Node）
是否包含真实 .env: 否
是否包含演示数据库: 否，启动后使用内置高数示例状态
前端入口: http://127.0.0.1:5173
后端入口: http://127.0.0.1:8010
启动方式: 双击 启动智学工坊.bat
"""
    (BUILD_DIR / "RELEASE_INFO.txt").write_text(info, encoding="utf-8")


def make_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD_DIR.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(BUILD_DIR.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 智学工坊 Windows portable release zip.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow packaging from a dirty working tree.")
    args = parser.parse_args()

    branch = run(["git", "branch", "--show-current"], allow_fail=True) or "unknown"
    commit = run(["git", "rev-parse", "--short", "HEAD"], allow_fail=True) or "unknown"
    status = run(["git", "status", "--short"], allow_fail=True)
    print(f"Branch: {branch}")
    print(f"Commit: {commit}")
    if status:
        print("Working tree: DIRTY")
        if not args.allow_dirty:
            print("Use --allow-dirty to package current local changes intentionally.")
            return 2
    else:
        print("Working tree: clean")

    scan_roots = [ROOT / "backend", ROOT / "frontend-demo", ROOT / "scripts", ROOT / "docs", ROOT / "reports", ROOT / "release"]
    scan_files = [p for root in scan_roots if root.exists() for p in root.rglob("*") if p.is_file() and not should_skip(p)]
    findings = scan_secrets(scan_files)
    if findings:
        print("Secret scan failed. Suspicious files:")
        for item in findings[:20]:
            print(f" - {item}")
        return 3
    print("Secret scan: PASS")

    shutil.rmtree(BUILD_DIR.parent, ignore_errors=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    copy_project_files()
    write_release_info(branch, commit)

    packaged_files = [p for p in BUILD_DIR.rglob("*") if p.is_file()]
    package_findings = scan_secrets(packaged_files)
    if package_findings:
        print("Packaged secret scan failed:")
        for item in package_findings[:20]:
            print(f" - {item}")
        return 4

    make_zip()
    print(f"Release zip: {ZIP_PATH}")
    print("BUILD RELEASE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
