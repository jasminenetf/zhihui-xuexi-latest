#!/usr/bin/env python3
"""Build final judge-facing and private prep packages.

Only this script may recreate final_delivery. It keeps judge-facing materials
clean and puts audit notes, prompts, and private rehearsal notes into a
separate package.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "final_delivery"
JUDGE = FINAL / "01_提交给评委"
PRIVATE = FINAL / "02_个人备稿_不提交给评委"
MISSING = FINAL / "03_待补文件"
DO_NOT_SUBMIT = FINAL / "99_不要提交_临时文件说明"
DIST = ROOT / "dist"
WINDOWS_ZIP = DIST / "智学工坊-Windows-便携版.zip"
JUDGE_ZIP = DIST / "智学工坊_评委提交包.zip"
PRIVATE_ZIP = DIST / "智学工坊_个人备稿包_不提交.zip"
SOURCE_ZIP = JUDGE / "04_源码与数据" / "智学工坊_源码与数据.zip"

PROJECT_NAME = "智学工坊——面向高校工科基础课的多智能体个性化学习资源生成系统"
SPARK_BASE = "https://spark-api-open.xf-yun.com/x2"
SPARK_MODEL = "spark-x"
RESOURCE_TYPES = "学习讲义、思维导图、练习题、PPT、学习路径、视频脚本、动画预览、拓展阅读"

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "logs",
    "dist",
    "final_delivery",
    "release_build",
    "reports",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".zip", ".7z", ".tar", ".gz"}
INTERNAL_AUDIT_NAMES = {
    "final_full_audit_after_3b.md",
    "final_qa_audit.md",
    "local_pending_static_qa_fix.diff",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|api[_-]?password|apisecret|api[_-]?secret|secret|token)\s*=\s*['\"]?([A-Za-z0-9_\-:]{16,})"),
    re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-.]{20,})"),
    re.compile(r"(sk-[A-Za-z0-9]{20,})"),
]


def run(args: list[str], *, timeout: int = 120, allow_fail: bool = False) -> str:
    proc = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    if proc.returncode != 0 and not allow_fail:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{proc.stdout}\n{proc.stderr}")
    return (proc.stdout or "").strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts if path.is_absolute() else path.parts
    if any(part in EXCLUDE_DIRS for part in rel_parts):
        return True
    if path.name in INTERNAL_AUDIT_NAMES:
        return True
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


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


def scan_text_for_secrets(text: str, label: str) -> list[str]:
    hits: list[str] = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(2) if (match.lastindex or 0) >= 2 else match.group(1)
            if is_false_positive(value, match.group(0)):
                continue
            hits.append(f"{label}: {match.group(0)[:80]}")
    return hits


def scan_paths(paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        if path.name == ".env.example":
            continue
        if path.suffix.lower() not in {".py", ".js", ".css", ".html", ".md", ".txt", ".bat", ".sh", ".json", ".yml", ".yaml", ".example"}:
            continue
        hits.extend(scan_text_for_secrets(path.read_text(encoding="utf-8", errors="ignore"), path.as_posix()))
    return hits


def make_zip(src: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src.parent))


def find_first(patterns: list[str], exclude_dirs: set[str] | None = None) -> Path | None:
    exclude_dirs = exclude_dirs or set()
    for pattern in patterns:
        for path in ROOT.rglob(pattern):
            if any(part in exclude_dirs for part in path.parts):
                continue
            if path.is_file():
                return path
    return None


def ensure_dirs() -> None:
    if FINAL.exists():
        shutil.rmtree(FINAL)
    dirs = [
        JUDGE / "01_演示PPT",
        JUDGE / "02_演示视频",
        JUDGE / "03_可运行系统",
        JUDGE / "04_源码与数据",
        JUDGE / "05_系统文档",
        JUDGE / "06_AI_Coding说明",
        JUDGE / "07_提交清单",
        PRIVATE / "01_答辩讲稿",
        PRIVATE / "02_演示视频稿",
        PRIVATE / "03_答辩PPT大纲",
        PRIVATE / "04_复现清单",
        PRIVATE / "05_审计报告",
        PRIVATE / "06_Codex提示词",
        PRIVATE / "07_开发过程记录",
        PRIVATE / "08_问题修复记录",
        MISSING,
        DO_NOT_SUBMIT,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def doc_system_development() -> str:
    return f"""
# 智学工坊_系统开发说明书

## 1. 项目背景

{PROJECT_NAME} 面向高等教育工科基础课学习场景。学生在学习高等数学等课程时，常见问题是教材内容抽象、学习资源分散、练习反馈滞后，教师难以及时掌握每个学生的薄弱点。

## 2. 赛题理解

赛题方向是高等教育个性化学习资源智能体系统。项目重点不是单次问答，而是把“提问诊断、课程依据检索、资源生成、练习反馈、错题复盘、学习报告和路径更新”串成闭环。

## 3. 需求分析

- 学生可以用自然语言描述不会的问题。
- 系统结合课程知识库给出有依据的解释。
- 系统自动生成学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览和拓展阅读。
- 系统记录练习和错题，动态更新学习画像。
- 系统给出下一步学习路径和复习建议。

## 4. 总体架构

系统采用静态前端工作台 + FastAPI 后端 + 多智能体编排 + 本地课程知识库。答辩主入口为 `frontend-demo/` 和 `backend/app/demo_main.py`，便于本地稳定演示。

## 5. 多智能体协同设计

- 画像智能体 ProfileAgent：读取画像、薄弱点和学习偏好。
- 检索智能体 RetrievalAgent：检索课程知识库和章节依据。
- 讲解智能体 TutorAgent：组织结构化讲解和问题诊断。
- 资源智能体 ResourceAgent：生成学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览和拓展阅读。
- 评估智能体 AssessmentAgent：根据练习、错题和掌握度形成复测建议。
- 路径智能体 PlannerAgent：生成下一步学习路径。
- 校验智能体 VerifierAgent：进行引用覆盖检查和可信检查。

## 6. 学习画像设计

画像至少展示知识基础、学习目标、薄弱知识点、认知风格、资源偏好、错题类型、掌握度变化和学习节奏。画像来自提问、练习、错题和资源使用行为。

## 7. 课程知识库与 RAG

样例课程为《高等数学上册》。系统将教材内容组织为可检索片段，在回答和资源生成时显示课程依据、检索模式和引用覆盖检查，降低幻觉风险。

## 8. 资源生成流程

资源类型包括：{RESOURCE_TYPES}。资源生成后进入资源中心，可预览、下载、收藏、继续练习或加入学习路径。

## 9. 错题反馈与学习报告

练习提交后，系统原地解释正误。错题进入错题本，并影响学习报告中的掌握度、薄弱点和下一步建议。

## 10. 动画预览与多模态设计

当前版本提供函数极限、导数定义、定积分、不定积分、微分方程、洛必达法则 6 类轻量 HTML/SVG/CSS 动画预览，不生成 mp4。动画用于辅助理解抽象概念，并与视频脚本和资源中心打通。

## 11. 防幻觉与内容安全

系统展示课程引用、引用覆盖率、支持断言数、无依据断言和风险等级。没有 API 时使用本地演示模式，不把 fallback 伪装成真实模型输出。

## 12. 前后端实现

前端为 `frontend-demo` 静态工作台，后端为 FastAPI。Spark 推荐配置为 Base URL `{SPARK_BASE}`、Model `{SPARK_MODEL}`、APIPassword 使用用户自己的科大讯飞 APIPassword。

## 13. 课程知识库证据层

项目包含 `knowledge_base/高等数学上册`，用于展示 7 章、40+ 知识点、RAG 样例查询和资源 grounding 示例。该证据层不公开完整版权教材原文，不包含真实密钥。

## 14. 数据库与文件结构

项目使用 SQLite / 本地文件保存演示数据和资源输出；课程知识库、资源结果、画像和报告围绕答辩 Demo 做轻量持久化。

## 15. 部署方式

Windows 便携包提供启动脚本。另一台电脑仍需 Python 3.10+ 和后端 requirements。没有 API 时可使用本地演示模式完成学习闭环。

## 16. 创新点

- 对话式画像，不依赖繁琐表单。
- 多智能体协同生成学习资源。
- 课程依据与 Verifier 结合，强调可信。
- 从问答到练习、错题、报告、路径的完整闭环。
- 轻量动画预览让抽象高数概念更直观。

## 17. 交付与验证

交付物包含 Windows 便携包、源码与数据包、系统文档、AI Coding 工具说明和 QA 检查脚本。评委包递归 forbidden hits 检查目标为 0，不包含 reports、个人备稿、Codex 提示词、真实密钥或 Actions 失败日志。当前正式 7 分钟演示视频仍待录制。

## 18. 局限与后续优化

当前动画不生成 mp4；正式账号权限、完整生产部署和更多课程适配仍需后续增强。
"""


def doc_test() -> str:
    return """
# 智学工坊_测试说明书

## 测试目标

验证系统能完成从对话诊断到资源生成、练习反馈、错题复盘、学习报告和路径更新的完整学习闭环。

## 测试环境

- Windows 10 / Windows 11
- Python 3.10+
- 浏览器：Chrome 或 Edge
- 后端端口：8010
- 前端端口：5173

## 测试范围

覆盖 AI 会话、资源生成、资源中心、练习提交、错题本、学习画像、学习报告、学习路径、动画预览、下载和便携启动。

## 功能测试

- 打开学习工作台。
- 输入“我不理解函数极限，讲清定义、常见误区，并给一个例题”。
- 查看结构化回答、课程依据、可信检查和画像更新。

## 接口测试

通过 smoke 和 deep QA 脚本检查 `/health`、`/api/app/*` 等核心接口。

## 资源生成测试

检查学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览、拓展阅读是否可生成、预览和下载。

## 学习闭环测试

完成练习并故意答错，确认错因解释、错题本、学习报告和学习路径更新。

## 跨电脑启动测试

在另一台 Windows 电脑完整解压便携包，安装 Python 3.10+ 和 requirements 后运行启动脚本。

## 安全与密钥检查

发行包不包含真实 `.env`，不包含真实 APIPassword、APIKey、APISecret。自动脚本进行密钥扫描。

## 自动化测试命令

```bash
python scripts/qa_startup_check.py
python scripts/verify_p0_smoke.py
python scripts/deep_qa_check.py
python scripts/check_release_package.py
```

## 测试结果说明

通过标准：

- `STARTUP QA PASSED`
- `ALL CHECKS PASSED`
- `DEEP QA PASSED`
- `RELEASE PACKAGE PASSED`

## 已知限制

Spark 真实生成受网络和 APIPassword 状态影响；没有 API 时可使用本地演示模式。
"""


def doc_deploy() -> str:
    return f"""
# 智学工坊_部署与运行说明

## Windows 便携包运行方式

1. 完整解压 `智学工坊-Windows-便携版.zip`。
2. 双击 `启动智学工坊.bat`。
3. 浏览器打开 `http://127.0.0.1:5173`。

## Python 3.10+ 要求

另一台电脑需要安装 Python 3.10+，安装时勾选 Add Python to PATH。

## requirements 安装

首次运行如提示依赖缺失，进入 `backend` 目录执行：

```bash
python -m pip install -r requirements.txt
```

## 启动脚本

启动脚本会启动后端 `127.0.0.1:8010` 和前端 `127.0.0.1:5173`。

## 端口说明

- 前端：5173
- 后端：8010
- 健康检查：`http://127.0.0.1:8010/health`

## Spark API 配置

- Base URL: `{SPARK_BASE}`
- Model: `{SPARK_MODEL}`
- APIPassword: 用户自己的科大讯飞 APIPassword

不要公开 APIPassword。

## fallback 演示模式

没有 API 或网络失败时，系统可使用本地演示模式完成学习闭环。

## 常见错误处理

- Python 未安装：安装 Python 3.10+。
- requirements 未安装：执行 pip install。
- 端口被占用：关闭占用 8010 或 5173 的程序。
- 页面打不开：检查启动窗口和防火墙。
- Spark 连接失败：检查 Base URL、Model 和 APIPassword。
- 杀毒软件拦截 bat：允许本地脚本运行。

## QA 验收命令

```bash
python scripts/qa_startup_check.py
python scripts/verify_p0_smoke.py
python scripts/deep_qa_check.py
```
"""


def doc_course() -> str:
    return """
# 智学工坊_课程知识库说明

## 样例课程

当前样例课程为《高等数学上册》。

## 知识库组织方式

系统将课程材料拆分为可检索片段，围绕章节、知识点和学习主题组织。

项目新增 `knowledge_base/高等数学上册` 证据层，包含 `course_manifest.json`、`chapter_outline.md`、`knowledge_points.json`、`rag_sample_queries.md`、`resource_grounding_examples.md` 和 `README.md`，用于展示学生问题如何映射到课程章节、知识点、RAG 检索和资源生成依据。

## 覆盖主题

重点覆盖函数极限、导数定义、定积分、不定积分、微分方程、连续、微分等高等数学基础主题。

## 资源依据

AI 回答和学习资源会展示课程依据，帮助学生知道内容来自哪个课程片段。

## RAG 检索流程

用户提问后，系统提取学习主题，再检索课程知识库，最后将课程依据交给回答和资源生成模块。

## 课程依据展示

前端会显示课程引用状态、检索模式、embedding provider 和引用覆盖检查。

## 局限说明

当前知识库以样例课程为主。若切换其他课程，需要重新上传材料并构建索引。
"""


def doc_open_source() -> str:
    return f"""
# 智学工坊_开源与工具使用说明

## 主要开源技术

- Python
- FastAPI
- SQLite
- 静态前端页面 HTML/CSS/JavaScript
- 本地脚本和 zip 打包工具

具体许可证以各项目官方协议为准。

## OpenAI SDK 兼容调用方式

系统采用 OpenAI-compatible 调用方式封装模型 Provider，便于切换 Spark 和本地演示模式。

## 科大讯飞 Spark X2

推荐配置：

- Base URL: `{SPARK_BASE}`
- Model: `{SPARK_MODEL}`
- APIPassword: 用户自己的科大讯飞 APIPassword

## 相关工具用途

- Python/FastAPI：后端服务。
- SQLite：轻量数据存储。
- 前端静态页面：学习工作台。
- GitHub Actions：静态 QA 和密钥扫描。
- Codex / AI Coding 工具：辅助代码、测试、文档和打包脚本编写。

## 安全说明

提交包不包含真实 `.env`，不包含真实 API 密钥，不公开 APIPassword。

## 开源协议说明

项目依赖的第三方开源组件应遵循其官方许可证；不确定具体许可证时，以对应项目官方协议为准。
"""


def doc_ai_coding() -> str:
    return """
# 智学工坊_AI_Coding工具使用说明

## 使用了哪些 AI Coding 工具

项目开发过程中使用了 Codex 等 AI Coding 辅助工具，用于提高工程整理、测试补充和文档初稿效率。

## 使用场景

- 需求拆解：把赛题要求拆成可执行阶段任务。
- 代码辅助生成：辅助实现脚本、接口兼容和前端交互细节。
- 测试脚本补充：补充 smoke、deep QA、包检查和密钥扫描。
- UI/UX 优化：辅助梳理学习闭环页面和学生操作路径。
- 文档初稿：生成开发说明、测试说明、部署说明等初稿。
- 打包脚本：生成 Windows 便携包和最终评委提交包脚本。
- 问题排查：定位 Actions 密钥扫描误报、资源下载、状态展示等问题。

## 人工审核方式

- 人工确认赛题要求和项目边界。
- 人工运行测试命令。
- 人工检查生成内容是否符合教学目标。
- 人工控制提交范围。
- 人工确认不把内部审计报告和原始提示词放入评委提交包。

## 安全措施

- 不提交真实 `.env`。
- 不公开 APIPassword。
- 使用密钥扫描检查提交包。
- 使用自动化 QA 验证核心功能。

## 说明

AI Coding 工具只作为辅助。最终功能、文档和提交内容经过人工审核。Codex 原始提示词不放入评委提交包。
"""


def release_notes() -> str:
    return f"""
# GitHub Release 发布说明

## 智学工坊 Windows 便携演示版 v0.1.0-demo

建议 tag：`v0.1.0-demo`

## 项目简介

智学工坊是面向高校工科基础课的多智能体个性化学习资源生成系统，以《高等数学上册》为样例课程，支持对话式学习画像、课程知识库检索、多智能体资源生成、练习反馈、错题复盘、学习报告、学习路径和轻量动画预览。

## 本版本包含

- Windows 便携启动脚本
- 后端服务
- 前端静态服务
- 高等数学上册演示数据
- {RESOURCE_TYPES}资源能力
- QA 验收脚本
- 便携版使用说明
- `.env.example`

## 使用方式

1. 下载 `智学工坊-Windows-便携版.zip`。
2. 完整解压。
3. 双击 `启动智学工坊.bat`。
4. 浏览器打开 `http://127.0.0.1:5173`。
5. 进入模型与设置填写 Spark API。
6. 没有 API 也可使用本地演示模式。

## 环境要求

- Windows 10 / Windows 11
- Python 3.10+
- 首次运行需要安装 backend requirements

## Spark 推荐配置

- Base URL: `{SPARK_BASE}`
- Model: `{SPARK_MODEL}`
- APIPassword: 用户自己的科大讯飞 APIPassword

## 验收命令

```bash
python scripts/qa_startup_check.py
python scripts/verify_p0_smoke.py
python scripts/deep_qa_check.py
```

## 安全说明

- 发行包不包含真实 `.env`
- 不包含真实 API 密钥
- 不公开 APIPassword
- 只包含 `.env.example`

## 已知限制

- 不是完全免安装版，另一台电脑仍需 Python 3.10+ 和后端依赖。
- 动画预览为 HTML/SVG/CSS 轻量动画，不生成 mp4。
- Spark 真实生成受网络和 API 状态影响，本地 fallback 可保证演示闭环。
"""


def reproduce_checklist() -> str:
    return f"""
# 跨电脑复现验收清单

## 1. 目标电脑准备

- Windows 10/11
- Python 3.10+
- 安装时勾选 Add Python to PATH
- 浏览器 Chrome/Edge

## 2. 解压

- 下载 zip
- 完整解压
- 不要只解压 bat

## 3. 首次依赖

进入 backend：

```bash
python -m pip install -r requirements.txt
```

## 4. 启动

双击 `启动智学工坊.bat`。

## 5. 检查地址

- `http://127.0.0.1:5173`
- `http://127.0.0.1:8010/health`

## 6. Spark 配置

- Base URL: `{SPARK_BASE}`
- Model: `{SPARK_MODEL}`
- APIPassword: 用户自己的 APIPassword

## 7. 验收命令

```bash
python scripts/qa_startup_check.py
python scripts/verify_p0_smoke.py
python scripts/deep_qa_check.py
```

## 8. 通过标准

出现：

- `STARTUP QA PASSED`
- `ALL CHECKS PASSED`
- `DEEP QA PASSED`

## 9. 失败处理

- Python 未安装：安装 Python 3.10+。
- requirements 未安装：执行 pip install。
- 端口被占用：关闭占用端口。
- 页面打不开：检查启动窗口、防火墙和浏览器地址。
- Spark 连接失败：检查 Base URL、Model、APIPassword。
- API 填错：重新填写用户自己的 APIPassword。
- 杀毒软件拦截 bat：允许本地脚本运行。
"""


def video_script() -> str:
    return """
# 7分钟演示视频脚本

## 0:00-0:30 项目背景与痛点

高等教育学习资源多、杂、难匹配。学生经常不知道自己到底哪里不会，也不知道下一步该学什么。传统表单画像麻烦，老师也很难实时跟踪每个学生的薄弱点。

## 0:30-1:00 项目定位

本项目叫智学工坊，面向高校工科基础课，是一个多智能体个性化学习资源生成系统。当前样例课程是《高等数学上册》。

## 1:00-2:00 对话式学习诊断

在 AI 会话中输入：“我不理解函数极限，讲清定义、常见误区，并给一个例题”。展示结构化回答、课程依据、可信检查和画像更新。

## 2:00-3:20 多资源生成

依次展示学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览和拓展阅读。强调资源围绕同一个薄弱点生成，并进入资源中心保存。

## 3:20-4:10 动画预览亮点

打开 video_script 中的动画预览，展示函数极限、不定积分或微分方程动画，再进入资源中心查看 animation_preview。说明这是轻量 HTML/SVG/CSS 动画预览，不生成 mp4。

## 4:10-5:10 练习反馈与错题闭环

做一道题，故意答错。展示原地错因分析、正确思路和错题本记录。

## 5:10-6:00 学习报告与画像

展示掌握度、薄弱点、学习节奏和下一步学习路径，说明画像会根据提问、练习和错题动态更新。

## 6:00-6:40 工程与交付

展示 Spark X2 配置、RAG、Verifier、QA 脚本和 Windows 便携包。说明提交包不含真实密钥。

## 6:40-7:00 总结

智学工坊把“问问题”变成“生成资源、练习、复盘、路径更新”的闭环，体现因材施教和多智能体协同。
"""


def ppt_outline() -> str:
    pages = [
        ("封面", "项目名称、赛题方向、团队信息", "系统首页或学习工作台", "介绍智学工坊的定位和样例课程。"),
        ("赛题理解与痛点", "资源多、画像难、反馈慢、路径不清", "学生学习流程示意", "说明为什么需要智能体系统。"),
        ("项目定位", "面向高校工科基础课的个性化学习资源系统", "项目工作台截图", "强调高等数学上册样例课程。"),
        ("总体架构", "前端、后端、RAG、多智能体、资源中心", "架构图", "讲清系统模块关系。"),
        ("多智能体协同流程", "ProfileAgent、RetrievalAgent、TutorAgent、ResourceAgent、AssessmentAgent、PlannerAgent、VerifierAgent", "Agent trace 截图", "突出多智能体不是口号，而是实际流程。"),
        ("对话式学习画像", "不填表，通过提问和练习更新画像", "画像页截图", "说明画像维度和动态更新。"),
        ("多资源生成能力", RESOURCE_TYPES, "资源中心截图", "展示围绕一个问题生成多类资源。"),
        ("动画预览与多模态亮点", "函数极限、导数、定积分、不定积分、微分方程、洛必达法则轻量动画", "动画预览截图", "说明不生成 mp4，但可预览可下载 HTML。"),
        ("错题反馈、学习报告、学习路径闭环", "答错讲解、错题本、掌握度、路径", "错题本和报告截图", "说明从练习到复盘的闭环。"),
        ("安全、可信检查与防幻觉", "课程依据、引用覆盖、风险等级", "可信检查截图", "强调 RAG 和 Verifier。"),
        ("测试与便携交付", "QA 脚本、Windows 便携包、跨电脑清单", "终端测试通过截图", "说明可复现和可交付。"),
        ("总结与创新价值", "对话式画像、多智能体资源生成、学习闭环", "完整闭环流程图", "收束项目价值和后续方向。"),
    ]
    body = ["# 答辩PPT大纲"]
    for i, (title, focus, shot, speech) in enumerate(pages, 1):
        body.append(f"## {i}. {title}\n\n- 标题：{title}\n- 页面重点：{focus}\n- 建议截图：{shot}\n- 讲解话术：{speech}")
    return "\n\n".join(body)


def ppt_final_update_checklist() -> str:
    return f"""
# 答辩PPT最终更新清单

由于本轮目标是录视频前终检，不直接重写或伪造 PPTX。正式 PPTX 如需最后编辑，请按下列清单核对：

1. 项目名称统一为：{PROJECT_NAME}
2. 赛题方向统一为：高等教育个性化学习资源智能体系统。
3. 样例课程统一为：高等数学上册。
4. 总体架构按五层表达：前端学习工作台、后端智能体服务、课程知识库/RAG、Spark 大模型、资源生成/评估/路径更新。
5. 多智能体图展示 7 个智能体：ProfileAgent、RetrievalAgent、TutorAgent、ResourceAgent、AssessmentAgent、PlannerAgent、VerifierAgent。
6. 知识库证据层展示：7 章、40+ 知识点、RAG 样例、grounding 示例，并说明不公开完整版权教材原文。
7. 功能闭环展示：对话诊断 → 学习画像 → 课程检索 → 多资源生成 → 练习反馈 → 错因分析 → 学习报告 → 路径更新。
8. 多模态资源展示 8 类：{RESOURCE_TYPES}。
9. 动画模板展示 6 类：函数极限、导数定义、定积分、不定积分、微分方程、洛必达法则。
10. 工程交付展示：Windows 便携包、源码与数据包、系统文档、AI Coding 说明、QA passed、forbidden hits 0。
11. 最后一页明确：当前待补为 7 分钟演示视频录制；系统已具备完整演示条件。
"""


def write_formal_docs() -> None:
    docs_final = ROOT / "docs" / "final"
    docs = {
        "智学工坊_系统开发说明书.md": doc_system_development(),
        "智学工坊_测试说明书.md": doc_test(),
        "智学工坊_部署与运行说明.md": doc_deploy(),
        "智学工坊_课程知识库说明.md": doc_course(),
        "智学工坊_开源与工具使用说明.md": doc_open_source(),
    }
    for name, text in docs.items():
        write(JUDGE / "05_系统文档" / name, text)
        write(docs_final / name, text)
    write(JUDGE / "06_AI_Coding说明" / "智学工坊_AI_Coding工具使用说明.md", doc_ai_coding())
    write(docs_final / "智学工坊_AI_Coding工具使用说明.md", doc_ai_coding())


def write_private_docs() -> None:
    write(PRIVATE / "01_答辩讲稿" / "7分钟答辩讲稿.md", video_script())
    write(PRIVATE / "01_答辩讲稿" / "评委可能追问与回答.md", f"""
# 评委可能追问与回答

## 是否真的调用 Spark？

推荐配置为 Base URL `{SPARK_BASE}`、Model `{SPARK_MODEL}`、APIPassword 使用用户自己的科大讯飞 APIPassword。没有 API 时系统会明确使用本地演示模式。

## 为什么动画不是 mp4？

当前阶段选择轻量 HTML/SVG/CSS 动画预览，优先保证可运行和可解释，不生成 mp4。

## 如何防幻觉？

系统展示课程依据、引用覆盖检查、支持断言和风险等级，并保留 Verifier。

## 项目创新点是什么？

对话式画像、多智能体资源生成、错题反馈和学习路径闭环。
""")
    write(PRIVATE / "01_答辩讲稿" / "项目亮点总结.md", """
# 项目亮点总结

1. 对话式学习画像。
2. 多智能体协同生成学习资源。
3. RAG + Verifier 可信检查。
4. 资源中心沉淀学习资料。
5. 错题、报告、路径闭环。
6. 轻量动画预览辅助高数理解。
7. Windows 便携交付。
""")
    write(PRIVATE / "02_演示视频稿" / "7分钟演示视频脚本.md", video_script())
    write(PRIVATE / "02_演示视频稿" / "录屏操作路线.md", """
# 录屏操作路线

1. 打开学习工作台。
2. 进入 AI 会话。
3. 提问函数极限。
4. 展示回答、依据、画像。
5. 展示多资源生成。
6. 打开动画预览。
7. 做题并故意答错。
8. 打开错题本、学习报告、学习路径。
9. 展示便携包和 QA 脚本。
""")
    write(PRIVATE / "02_演示视频稿" / "录屏检查清单.md", """
# 录屏检查清单

- 浏览器缩放合适。
- 不显示真实 APIPassword。
- 关闭无关窗口。
- 预生成资源可用。
- Spark 等待时间可控。
- 便携包和 QA 结果截图准备好。
""")
    write(PRIVATE / "02_演示视频稿" / "录屏口播稿.md", video_script())
    write(PRIVATE / "03_答辩PPT大纲" / "答辩PPT大纲.md", ppt_outline())
    write(PRIVATE / "03_答辩PPT大纲" / "每页讲解词.md", ppt_outline())
    write(PRIVATE / "03_答辩PPT大纲" / "答辩PPT最终更新清单.md", ppt_final_update_checklist())
    write(ROOT / "docs" / "final" / "答辩PPT最终更新清单.md", ppt_final_update_checklist())
    write(PRIVATE / "03_答辩PPT大纲" / "建议截图清单.md", """
# 建议截图清单

- 学习工作台首页
- AI 会话结构化回答
- 课程依据和可信检查
- 学习画像页面
- 资源中心
- 思维导图
- PPT 预览
- 视频脚本与动画预览
- 错题本
- 学习报告
- QA 脚本通过结果
""")
    write(PRIVATE / "04_复现清单" / "跨电脑复现验收清单.md", reproduce_checklist())
    existing_portable = ROOT / "docs" / "final" / "便携版使用说明.md"
    if existing_portable.exists():
        copy_if_exists(existing_portable, PRIVATE / "04_复现清单" / "便携版使用说明.md")
    else:
        write(PRIVATE / "04_复现清单" / "便携版使用说明.md", doc_deploy())
    write(PRIVATE / "04_复现清单" / "GitHub Release 发布说明.md", release_notes())
    for src_name in ["final_full_audit_after_3b.md", "final_qa_audit.md", "local_pending_static_qa_fix.diff"]:
        copy_if_exists(ROOT / "reports" / src_name, PRIVATE / "05_审计报告" / src_name)
    write(PRIVATE / "05_审计报告" / "QA摘要.md", """
# QA摘要

主学习闭环、资源生成闭环、动画预览、便携打包和提交包检查已纳入自动化验证。内部审计报告只供个人备稿使用，不进入评委包。
""")
    write(PRIVATE / "05_审计报告" / "P0_P1_P2问题记录.md", """
# P0_P1_P2问题记录

## P0

当前整理阶段未发现阻断提交的 P0。

## P1

- 正式 PPTX 和 MP4 如不存在，需要赛前补齐。
- 跨电脑运行仍需 Python 3.10+ 和 requirements。

## P2

- 动画预览不生成 mp4。
- 更多课程适配仍需后续扩展。
""")
    write(PRIVATE / "06_Codex提示词" / "阶段整理提示词汇总.md", """
# 阶段整理提示词汇总

本文件只供个人复盘，不提交给评委。内容概括为：围绕比赛交付，要求整理评委提交包、个人备稿包、复现清单和 AI Coding 工具说明。
""")
    write(PRIVATE / "06_Codex提示词" / "关键修复提示词汇总.md", """
# 关键修复提示词汇总

本文件只供个人复盘，不提交给评委。关键修复包括：资源质量、Spark 配置、密钥扫描误报、便携包、动画预览、数学公式可读化。
""")
    write(PRIVATE / "07_开发过程记录" / "功能阶段记录.md", """
# 功能阶段记录

1. 学习报告和错题本数据一致性。
2. 模型状态、Verifier、RAG 展示统一。
3. 学习画像动态更新。
4. 资源闭环和 video_script。
5. Spark 配置和教学内容质量优化。
6. 轻量动画预览。
7. 便携打包和最终提交包整理。
""")
    write(PRIVATE / "07_开发过程记录" / "commit摘要.md", run(["git", "log", "--oneline", "-12"], allow_fail=True))
    write(PRIVATE / "07_开发过程记录" / "架构演进记录.md", """
# 架构演进记录

项目从基础问答扩展为静态前端工作台 + FastAPI Demo 后端 + 多智能体资源生成 + RAG/Verifier + 学习画像和报告闭环。
""")
    fixes = {
        "Spark配置修复.md": f"Spark 推荐配置统一为 Base URL `{SPARK_BASE}`、Model `{SPARK_MODEL}`、APIPassword 使用用户自己的科大讯飞 APIPassword。",
        "secret_scan误报修复.md": "修复 GitHub Actions 将 `_normalize_spark_api_password` 误判为密钥的问题，保留真实 token 检测能力。",
        "便携包修复.md": "新增 Windows 便携包构建和检查脚本，确保不包含真实 .env、.git、node_modules 和密钥。",
        "动画预览修复.md": "新增函数极限、导数定义、定积分、不定积分、微分方程、洛必达法则 6 类轻量 HTML/SVG/CSS 动画预览。",
        "数学公式可读化修复.md": "将讲义和回答中的公式表达改为更适合学生理解的文本和结构。",
        "学习资源质量重构.md": "提升学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览和拓展阅读的教学针对性。",
    }
    for name, text in fixes.items():
        write(PRIVATE / "08_问题修复记录" / name, f"# {name.removesuffix('.md')}\n\n{text}")


def copy_judge_runtime() -> None:
    if not WINDOWS_ZIP.exists():
        run(["python", "scripts/build_windows_release.py", "--allow-dirty"], timeout=180)
        run(["python", "scripts/check_release_package.py"], timeout=120)
    copy_if_exists(WINDOWS_ZIP, JUDGE / "03_可运行系统" / WINDOWS_ZIP.name)
    write(JUDGE / "03_可运行系统" / "README_运行说明.txt", f"""
1. 完整解压 "智学工坊-Windows-便携版.zip"。
2. 安装 Python 3.10+，并勾选 Add Python to PATH。
3. 首次运行如提示依赖缺失，进入 backend 目录执行：
   python -m pip install -r requirements.txt
4. 双击 "启动智学工坊.bat"。
5. 浏览器打开 "http://127.0.0.1:5173"。
6. 进入“模型与设置”填写 Spark API。
7. 推荐配置：
   Base URL: {SPARK_BASE}
   Model: {SPARK_MODEL}
   APIPassword: 用户自己的科大讯飞 APIPassword
8. 没有 API 也可使用本地演示模式完成学习闭环。
9. 不要公开 APIPassword。
""")


def copy_ppt_video_and_missing() -> list[dict[str, str]]:
    missing_rows: list[dict[str, str]] = []
    ppt = find_first([
        "docs/presentation/*.pptx",
        "docs/final/*.pptx",
        "*.pptx",
    ], {".git", "node_modules", "final_delivery", "dist", "release_build", "data", "outputs"})
    if ppt:
        copy_if_exists(ppt, JUDGE / "01_演示PPT" / "智学工坊_演示PPT.pptx")
        ppt_status = ("是", str(ppt.relative_to(ROOT)), "是", "已复制并统一命名")
    else:
        ppt_status = ("否", "未找到", "否", "缺少正式 PPTX；当前大纲在个人备稿包")
    video = find_first([
        "docs/presentation/*.mp4",
        "docs/final/*.mp4",
        "*.mp4",
    ], {".git", "node_modules", "final_delivery", "dist", "release_build", "data", "outputs"})
    if video:
        copy_if_exists(video, JUDGE / "02_演示视频" / "智学工坊_7分钟演示视频.mp4")
        video_status = ("是", str(video.relative_to(ROOT)), "是", "已复制并统一命名")
    else:
        video_status = ("否", "未找到", "否", "缺少正式 MP4；当前脚本在个人备稿包")

    required = [
        ("智学工坊_演示PPT.pptx", *ppt_status),
        ("智学工坊_7分钟演示视频.mp4", *video_status),
        ("智学工坊_系统开发说明书.md", "是", "final_delivery/01_提交给评委/05_系统文档", "是", "已生成"),
        ("智学工坊_测试说明书.md", "是", "final_delivery/01_提交给评委/05_系统文档", "是", "已生成"),
        ("智学工坊_部署与运行说明.md", "是", "final_delivery/01_提交给评委/05_系统文档", "是", "已生成"),
        ("智学工坊_课程知识库说明.md", "是", "final_delivery/01_提交给评委/05_系统文档", "是", "已生成"),
        ("智学工坊_开源与工具使用说明.md", "是", "final_delivery/01_提交给评委/05_系统文档", "是", "已生成"),
        ("智学工坊_AI_Coding工具使用说明.md", "是", "final_delivery/01_提交给评委/06_AI_Coding说明", "是", "已生成"),
        ("智学工坊-Windows-便携版.zip", "是" if WINDOWS_ZIP.exists() else "否", "dist/智学工坊-Windows-便携版.zip", "是", "便携系统包"),
        ("智学工坊_源码与数据.zip", "是", "final_delivery/01_提交给评委/04_源码与数据", "是", "构建时生成"),
    ]
    lines = ["# 缺失文件清单", "", "| 文件 | 是否存在 | 当前路径 | 是否提交评委 | 备注 |", "| --- | --- | --- | --- | --- |"]
    for row in required:
        lines.append("| " + " | ".join(row) + " |")
    write(MISSING / "缺失文件清单.md", "\n".join(lines))
    return [{"name": row[0], "exists": row[1], "path": row[2], "submit": row[3], "note": row[4]} for row in required]


def create_source_zip() -> None:
    temp = FINAL / "_source_build"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    include_dirs = ["backend", "frontend-demo", "scripts", "release", "knowledge_base", "data", "outputs"]
    for folder in include_dirs:
        src = ROOT / folder
        if not src.exists():
            continue
        for path in src.rglob("*"):
            if should_skip(path):
                continue
            target = temp / path.relative_to(ROOT)
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    final_docs_target = temp / "docs" / "final"
    for doc in (JUDGE / "05_系统文档").glob("*.md"):
        copy_if_exists(doc, final_docs_target / doc.name)
    for doc in (JUDGE / "06_AI_Coding说明").glob("*.md"):
        copy_if_exists(doc, final_docs_target / doc.name)
    for file_name in ["README.md", "LICENSE", "backend/requirements.txt", "requirements.txt", ".env.example"]:
        src = ROOT / file_name
        if src.exists() and not should_skip(src):
            copy_if_exists(src, temp / file_name)
    findings = scan_paths([p for p in temp.rglob("*") if p.is_file()])
    if findings:
        raise RuntimeError("source secret scan failed:\n" + "\n".join(findings[:20]))
    make_zip(temp, SOURCE_ZIP)
    shutil.rmtree(temp)


def submission_checklist(rows: list[dict[str, str]]) -> None:
    status_map = {row["name"]: row for row in rows}
    items = [
        ("演示 PPT", "智学工坊_演示PPT.pptx", status_map["智学工坊_演示PPT.pptx"]["exists"]),
        ("演示视频", "智学工坊_7分钟演示视频.mp4", status_map["智学工坊_7分钟演示视频.mp4"]["exists"]),
        ("Windows 便携版 zip", "智学工坊-Windows-便携版.zip", "是"),
        ("源码与数据 zip", "智学工坊_源码与数据.zip", "是"),
        ("系统开发说明书", "智学工坊_系统开发说明书.md", "是"),
        ("测试说明书", "智学工坊_测试说明书.md", "是"),
        ("部署与运行说明", "智学工坊_部署与运行说明.md", "是"),
        ("课程知识库说明", "智学工坊_课程知识库说明.md", "是"),
        ("开源与工具使用说明", "智学工坊_开源与工具使用说明.md", "是"),
        ("AI Coding 工具使用说明", "智学工坊_AI_Coding工具使用说明.md", "是"),
    ]
    lines = ["# 提交文件清单", "", "| 文件类别 | 文件名 | 是否已放入评委包 | 说明 | 状态 |", "| --- | --- | --- | --- | --- |"]
    for category, name, exists in items:
        status = "已放入" if exists == "是" else "待补"
        note = "正式提交材料" if exists == "是" else "当前不存在，已记录到待补文件清单"
        lines.append(f"| {category} | {name} | {exists} | {note} | {status} |")
    write(JUDGE / "07_提交清单" / "提交文件清单.md", "\n".join(lines))


def do_not_submit_doc() -> None:
    write(DO_NOT_SUBMIT / "不要提交说明.md", """
# 不要提交说明

以下内容不提交给评委：

- `.git/`
- `.env`
- `backend/.env`
- `node_modules/`
- `venv/`
- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `logs/`
- `dist` 中旧 zip
- `reports` 内部审计报告
- Codex 原始提示词
- 个人备稿
- 临时截图
- 临时测试数据库
- 真实 API 密钥
- Actions 失败日志截图
- 开发流水账
""")


def scan_judge_materials() -> None:
    findings = scan_paths([p for p in JUDGE.rglob("*") if p.is_file() and p.suffix.lower() != ".zip"])
    if findings:
        raise RuntimeError("judge material secret scan failed:\n" + "\n".join(findings[:20]))


def main() -> int:
    print("Building final judge package...")
    ensure_dirs()
    copy_judge_runtime()
    rows = copy_ppt_video_and_missing()
    write_formal_docs()
    write_private_docs()
    create_source_zip()
    submission_checklist(rows)
    do_not_submit_doc()
    scan_judge_materials()
    judge_root = FINAL / "_judge_package"
    if judge_root.exists():
        shutil.rmtree(judge_root)
    judge_root.mkdir(parents=True)
    shutil.copytree(JUDGE, judge_root / JUDGE.name)
    shutil.copytree(MISSING, judge_root / MISSING.name)
    shutil.copytree(DO_NOT_SUBMIT, judge_root / DO_NOT_SUBMIT.name)
    make_zip(judge_root, JUDGE_ZIP)
    shutil.rmtree(judge_root)
    make_zip(PRIVATE, PRIVATE_ZIP)
    print(f"final_delivery: {FINAL}")
    print(f"judge zip: {JUDGE_ZIP}")
    print(f"private zip: {PRIVATE_ZIP}")
    print("BUILD FINAL JUDGE PACKAGE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
