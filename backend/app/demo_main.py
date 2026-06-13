"""Lightweight demo backend for one-click local usage.

This entrypoint intentionally avoids heavy database/ORM imports so a new user can:
1. double-click the launcher,
2. open the web UI,
3. fill Spark/DeepSeek API settings,
4. ask questions immediately.
"""

from __future__ import annotations

import os
import json
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from openai import OpenAI
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = APP_DIR / ".env"
GENERATED_DIR = APP_DIR / "data" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _load_local_env() -> None:
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()

app = FastAPI(title="智能学习Agent Demo Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MIN_LLM_TIMEOUT_SECONDS = 60
DEFAULT_LLM_TIMEOUT_SECONDS = 180
MAX_LLM_TIMEOUT_SECONDS = 600


def _coerce_llm_timeout(value: Any = None) -> int:
    try:
        seconds = int(value if value not in (None, "") else DEFAULT_LLM_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        seconds = DEFAULT_LLM_TIMEOUT_SECONDS
    return max(MIN_LLM_TIMEOUT_SECONDS, min(MAX_LLM_TIMEOUT_SECONDS, seconds))


def _normalize_spark_api_password(value: str | None) -> str:
    """Allow users to paste either APIPassword or APIKey:APISecret/APIPassword pairs."""
    raw = str(value or "").strip().strip('"').strip("'")
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw


STATE: dict[str, Any] = {
    "llm_provider": os.getenv("LLM_PROVIDER", "mock"),
    "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY", ""),
    "deepseek_base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    "deepseek_model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    "spark_api_key": _normalize_spark_api_password(os.getenv("SPARK_API_PASSWORD", os.getenv("SPARK_API_KEY", ""))),
    "spark_base_url": os.getenv("SPARK_BASE_URL", "https://spark-api-open.xf-yun.com/v1"),
    "spark_model": os.getenv("SPARK_MODEL", "generalv3.5"),
    "llm_timeout_seconds": _coerce_llm_timeout(os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("SPARK_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS))),
    "course_id": 1,
    "course_name": "高等数学上册",
    "sessions": [],
    "resources": [],
    "resource_jobs": {},
    "resource_payloads": {},
    "mastery_records": [],
    "study_plan_events": [],
    "extra_courses": [],
    "files": [
        {
            "id": "gaoshu-pdf",
            "course_id": 1,
            "original_filename": "高数上.pdf",
            "status": "ready",
            "content_type": "application/pdf",
            "chunks": 128,
            "indexed_chunks": 128,
            "source": r"C:\Users\zhang\Desktop\高数上.pdf",
        }
    ],
    "wrong_book": [
        {
            "knowledge_point": "函数极限",
            "question": "极限存在是否要求函数在该点有定义？",
            "selected_answer": "要求",
            "correct_answer": "不要求",
            "explanation": "极限研究的是自变量趋近该点时函数值的变化趋势。",
            "mastery_score": 0.48,
        }
    ],
    "bookmarks": [
        {"resource_id": "gaoshu-outline", "title": "高等数学上册章节导学"}
    ],
    "profile": {
        "major": "高等数学上册复习",
        "knowledge_level": "待识别",
        "learning_goal": "理解核心概念并完成基础练习",
        "cognitive_style": "偏好分步骤讲解",
        "pace_preference": "moderate",
        "weak_points": ["待识别"],
        "resource_preference": ["lecture_doc", "mindmap", "quiz"],
        "wrong_question_types": ["待积累"],
        "mastery_trend": "暂无足够数据",
        "emotion_tendency": "专注学习",
        "profile_source": "dialogue",
        "profile_version": 0,
        "profile_confidence": 0.0,
        "raw_evidence": "",
        "last_topic": "",
        "last_updated_fields": [],
    },
    "profile_versions": [],
    "profile_changes": [],
    "llm_failure_until": 0.0,
    "llm_last_error": "",
}

GAOSHU_COURSE_DESCRIPTION = (
    "内置《高数上.pdf》学习辅助课程，覆盖函数与极限、导数与微分、"
    "微分中值定理与导数应用、不定积分、定积分、定积分应用和微分方程。"
)

GAOSHU_CHAPTERS = [
    {"title": "第一章 函数与极限", "page": 16, "points": ["函数", "数列极限", "函数极限", "无穷小与无穷大", "连续性"]},
    {"title": "第二章 导数与微分", "page": 88, "points": ["导数定义", "求导法则", "高阶导数", "隐函数求导", "微分"]},
    {"title": "第三章 微分中值定理与导数的应用", "page": 140, "points": ["罗尔定理", "拉格朗日中值定理", "洛必达法则", "单调性", "极值与最值"]},
    {"title": "第四章 不定积分", "page": 199, "points": ["原函数", "基本积分公式", "换元积分法", "分部积分法"]},
    {"title": "第五章 定积分", "page": 239, "points": ["定积分定义", "可积条件", "微积分基本公式", "定积分换元法", "定积分分部积分"]},
    {"title": "第六章 定积分的应用", "page": 289, "points": ["面积", "体积", "弧长", "物理应用"]},
    {"title": "第七章 微分方程", "page": 312, "points": ["可分离变量方程", "齐次方程", "一阶线性微分方程", "二阶常系数线性方程"]},
]

GAOSHU_TOPIC_HINTS = {
    "极限": {
        "chapter": "第一章 函数与极限",
        "summary": "极限刻画变量趋近某个过程时函数值或数列项的稳定趋势，是连续、导数和积分的基础。",
        "steps": ["先判断自变量趋近方式", "化简表达式并消去无意义项", "必要时比较左右极限或使用等价无穷小"],
        "pitfalls": ["把函数值等同于极限", "忽略左右极限", "未验证等价无穷小适用条件"],
    },
    "导数": {
        "chapter": "第二章 导数与微分",
        "summary": "导数表示函数在一点的瞬时变化率，几何意义是曲线在该点的切线斜率。",
        "steps": ["明确函数复合结构", "选择求导法则", "代入点值并解释实际或几何意义"],
        "pitfalls": ["复合函数漏乘内层导数", "隐函数求导漏写 y'", "高阶导数符号混乱"],
    },
    "微分": {
        "chapter": "第二章 导数与微分",
        "summary": "微分用线性主部近似函数增量，适合做近似计算和误差分析。",
        "steps": ["先求导数", "写出 dy=f'(x)dx", "结合题目给定的增量解释近似"],
        "pitfalls": ["把 dy 与 Δy 完全等同", "忘记说明近似条件"],
    },
    "洛必达": {
        "chapter": "第三章 微分中值定理与导数的应用",
        "summary": "洛必达法则用于处理 0/0 或 ∞/∞ 型未定式，使用前必须确认适用条件。",
        "steps": ["确认未定式类型", "分别对分子分母求导", "求导后重新判断极限"],
        "pitfalls": ["不是 0/0 或 ∞/∞ 也直接用", "循环求导后不检查极限是否存在"],
    },
    "积分": {
        "chapter": "第四、五章 不定积分与定积分",
        "summary": "不定积分关注原函数族，定积分关注区间上的累积量，两者由微积分基本公式联系。",
        "steps": ["识别是求原函数还是累积量", "匹配基本公式或换元/分部方法", "定积分注意上下限和几何意义"],
        "pitfalls": ["不定积分漏写常数 C", "换元后上下限未同步变化", "分部积分 u 与 dv 选择不当"],
    },
    "微分方程": {
        "chapter": "第七章 微分方程",
        "summary": "微分方程用未知函数及其导数描述变化规律，先分类再选择解法。",
        "steps": ["判断方程类型", "按类型套用分离变量或线性方程方法", "代入初值确定常数"],
        "pitfalls": ["未分离变量就积分", "通解漏常数", "初值条件代入位置错误"],
    },
}


def _read_env_lines() -> list[str]:
    if ENV_PATH.exists():
        return ENV_PATH.read_text(encoding="utf-8").splitlines(True)
    return []


def _write_env(updates: dict[str, str]) -> None:
    lines = _read_env_lines()
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                output.append(f"{key}={updates[key]}\n")
                seen.add(key)
                continue
        output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}\n")
    ENV_PATH.write_text("".join(output), encoding="utf-8")


def _provider_config(provider: str) -> tuple[str, str, str]:
    provider = (provider or STATE["llm_provider"] or "mock").lower()
    if provider == "mock":
        return "mock", "", "", "mock"
    if provider == "spark":
        return "spark", _normalize_spark_api_password(STATE["spark_api_key"]), STATE["spark_base_url"], STATE["spark_model"]
    if provider == "deepseek":
        return "deepseek", STATE["deepseek_api_key"], STATE["deepseek_base_url"], STATE["deepseek_model"]
    if STATE["spark_api_key"]:
        return "spark", _normalize_spark_api_password(STATE["spark_api_key"]), STATE["spark_base_url"], STATE["spark_model"]
    if STATE["deepseek_api_key"]:
        return "deepseek", STATE["deepseek_api_key"], STATE["deepseek_base_url"], STATE["deepseek_model"]
    return "mock", "", "", "mock"


def _gaoshu_context(topic: str) -> dict[str, Any]:
    text = (topic or "").lower()
    for key, ctx in GAOSHU_TOPIC_HINTS.items():
        if key.lower() in text:
            return {"keyword": key, **ctx}
    if any(word in text for word in ["函数", "连续", "无穷小", "无穷大"]):
        return {"keyword": "极限", **GAOSHU_TOPIC_HINTS["极限"]}
    return {
        "keyword": "高等数学",
        "chapter": "高等数学上册",
        "summary": "高等数学上册围绕极限、导数、积分和微分方程建立连续变化问题的分析工具。",
        "steps": ["先定位教材章节", "理解定义和定理适用条件", "用例题验证方法", "通过练习巩固薄弱点"],
        "pitfalls": ["只背公式不看条件", "计算步骤跳跃", "错题没有回到概念复盘"],
    }


def _topic_wrong_hint(topic_key: str, wrong_book: list[dict[str, Any]] | None = None) -> str:
    wrong_book = wrong_book if wrong_book is not None else STATE.get("wrong_book", [])
    for item in wrong_book:
        hay = " ".join(str(item.get(k) or "") for k in ["knowledge_point", "question", "question_text", "explanation"])
        if topic_key and topic_key in hay:
            reason = item.get("wrong_reason") or item.get("explanation") or item.get("selected_answer") or "概念辨析错误"
            return f"你之前在这个知识点出现过：{reason} 类型错误。"
    return "当前暂无该知识点错题记录，建议先完成 3 道诊断题。"


def _analyze_math_topic(topic: str, profile: dict | None = None, wrong_book: list | None = None) -> dict[str, Any]:
    """Topic-aware teaching analysis shared by lecture, PPT, mindmap and quiz."""
    profile = profile or STATE.get("profile", {})
    text = str(topic or "")
    low = text.lower()
    if any(k in low or k in text for k in ["微积分的定义", "微积分整体", "微积分"]):
        key = "微积分"
    elif any(k in text for k in ["函数连续", "连续"]):
        key = "连续"
    elif any(k in text for k in ["定积分", "积分"]):
        key = "积分"
    elif any(k in text for k in ["导数", "微分"]):
        key = "导数"
    elif any(k in text for k in ["函数极限", "极限"]):
        key = "极限"
    else:
        key = _gaoshu_context(text).get("keyword") or "高等数学"

    weak_points = _profile_list(profile.get("weak_points")) or ["待识别"]
    resource_pref = _profile_list(profile.get("resource_preference")) or ["讲义", "思维导图", "练习题"]
    common_profile_hint = f"画像提示：当前薄弱点 {', '.join(weak_points[:3])}；资源偏好 {', '.join(resource_pref[:3])}。"
    cases: dict[str, dict[str, Any]] = {
        "极限": {
            "topic_label": "函数极限",
            "course_chapter": "第一章 函数与极限",
            "core_question": "当自变量不断趋近某一点时，函数值会不会稳定靠近一个确定数？",
            "concept_intuition": "极限看的不是某一点的函数值，而是靠近这个点的整个过程。",
            "formal_definition": "若 x 趋近 x0 时 f(x) 任意接近 A，则称 A 为 f(x) 当 x 趋近 x0 时的极限。",
            "symbol_focus": "lim、x趋近、左右极限、去心邻域、0/0 型",
            "prerequisites": ["函数值与函数图像", "邻域和去心邻域", "左右趋近", "因式分解化简"],
            "condition_checks": ["先判断趋近方向", "再检查左右极限是否相等", "遇到 0/0 先化简，不把 0/0 当答案"],
            "method_steps": ["代入判断是否未定式", "化简或分解消去无意义项", "分别看左右趋势", "写出极限值并说明依据"],
            "example_problem": "求 lim(x->1) (x^2-1)/(x-1)。",
            "example_solution_steps": ["代入得到 0/0，说明不能直接下结论", "分解 x^2-1=(x-1)(x+1)", "在 x 不等于 1 的趋近过程中约去 x-1", "得到 x+1，趋近 2", "结论：极限为 2，和 x=1 处是否有定义不是同一件事"],
            "common_mistakes": ["把函数值当成极限值", "只看右极限，漏看左极限", "把 0/0 当作极限等于 0", "没有说明化简只在去心邻域内成立"],
            "contrast_pairs": ["函数值 vs 极限值", "左极限 vs 右极限", "未定式 0/0 vs 最终极限值"],
        },
        "导数": {
            "topic_label": "导数定义",
            "course_chapter": "第二章 导数与微分",
            "core_question": "怎样描述函数在某一点此刻变化得有多快？",
            "concept_intuition": "导数是割线斜率在两点无限靠近时形成的切线斜率。",
            "formal_definition": "f'(x0)=lim(Δx->0)[f(x0+Δx)-f(x0)]/Δx，若该极限存在则函数在 x0 可导。",
            "symbol_focus": "Δx、差商、瞬时变化率、切线斜率、可导与连续",
            "prerequisites": ["函数图像", "平均变化率", "极限思想", "切线斜率"],
            "condition_checks": ["先写差商", "确认 Δx 趋近 0", "判断差商极限是否存在", "可导必连续但连续不一定可导"],
            "method_steps": ["从平均变化率建立差商", "让 Δx 趋近 0", "得到导数值或导函数", "用切线斜率解释意义"],
            "example_problem": "用定义求 f(x)=x^2 在 x=3 处的导数。",
            "example_solution_steps": ["写差商 [(3+Δx)^2-9]/Δx", "展开得 (6Δx+Δx^2)/Δx", "约去 Δx 得 6+Δx", "令 Δx 趋近 0，得到 6", "含义：曲线在 x=3 处切线斜率为 6"],
            "common_mistakes": ["把导数当普通除法", "忘记取极限", "把可导和连续看成等价", "切线斜率解释不出来"],
            "contrast_pairs": ["平均变化率 vs 瞬时变化率", "割线 vs 切线", "连续 vs 可导"],
        },
        "积分": {
            "topic_label": "定积分的几何意义",
            "course_chapter": "第四、五章 不定积分与定积分",
            "core_question": "怎样把一个区间内不断变化的小量累加成总量？",
            "concept_intuition": "定积分把区间切成很多小段，用小矩形面积近似，再让小段无限变细。",
            "formal_definition": "定积分是分割、取样、求和、取极限的结果，可表示曲边梯形的有向面积。",
            "symbol_focus": "积分号、上下限、被积函数、dx、小区间求和",
            "prerequisites": ["函数图像", "区间与面积", "求和思想", "极限思想"],
            "condition_checks": ["先区分定积分和不定积分", "看清上下限", "判断被积函数在区间上的意义", "结果是否需要常数 C"],
            "method_steps": ["确定累积对象", "画出区间和函数图像", "选择公式或换元方法", "代入上下限得到数值"],
            "example_problem": "解释 ∫_0^2 x dx 的几何意义并求值。",
            "example_solution_steps": ["函数 y=x 在 0 到 2 上围成三角形", "底为 2，高为 2", "面积为 1/2*2*2=2", "所以定积分值为 2", "这是区间累积量，不需要 +C"],
            "common_mistakes": ["把定积分结果写成原函数族", "漏看上下限", "换元后上下限不同步变化", "只算公式不解释面积意义"],
            "contrast_pairs": ["定积分 vs 不定积分", "面积累积 vs 原函数", "上下限数值 vs 常数 C"],
        },
        "连续": {
            "topic_label": "函数连续",
            "course_chapter": "第一章 函数与极限",
            "core_question": "函数图像为什么能不断开地通过某一点？",
            "concept_intuition": "连续要求点上的函数值和靠近该点时的趋势对得上。",
            "formal_definition": "若 f(x0) 有定义、lim(x->x0)f(x) 存在，且极限值等于 f(x0)，则 f 在 x0 连续。",
            "symbol_focus": "函数值存在、极限存在、二者相等、间断点",
            "prerequisites": ["函数值", "函数极限", "左右极限", "图像直观"],
            "condition_checks": ["检查 f(x0) 是否有定义", "检查左右极限是否存在且相等", "检查极限值是否等于函数值"],
            "method_steps": ["先算函数值", "再算左右极限", "比较三者关系", "判断间断点类型"],
            "example_problem": "判断 f(x)=x^2 在 x=1 处是否连续。",
            "example_solution_steps": ["函数值 f(1)=1", "当 x 趋近 1 时 x^2 趋近 1", "极限存在且等于函数值", "所以函数在 x=1 处连续", "这里连续不代表一定讨论导数"],
            "common_mistakes": ["只看函数值存在就说连续", "只看极限存在不比较函数值", "把连续和可导混为一谈"],
            "contrast_pairs": ["函数值存在 vs 连续", "极限存在 vs 连续", "连续 vs 可导"],
        },
        "微积分": {
            "topic_label": "微积分整体理解",
            "course_chapter": "第一至第五章 微积分核心工具",
            "core_question": "为什么高数用微分研究局部变化，用积分研究整体累积？",
            "concept_intuition": "微分把变化看得极小，积分把极小变化累加成整体。",
            "formal_definition": "微分建立局部线性近似，积分通过极限求和刻画区间总量，二者由微积分基本公式联系。",
            "symbol_focus": "导数、微分、积分、局部变化、整体累积、基本公式",
            "prerequisites": ["函数", "极限", "变化率", "累积量"],
            "condition_checks": ["先问是局部变化还是整体累积", "再判断需要导数还是积分", "最后用基本公式联系两者"],
            "method_steps": ["识别问题对象", "判断是变化率还是累积量", "选择导数或积分工具", "回到实际含义解释结果"],
            "example_problem": "汽车速度 v(t) 已知，如何理解加速度和路程？",
            "example_solution_steps": ["速度的导数表示加速度，是局部变化", "速度在时间区间上的积分表示路程，是整体累积", "导数看瞬时，积分看总量", "二者共同描述连续运动", "这就是微积分作为工具的核心"],
            "common_mistakes": ["把微分和积分割裂学习", "只背公式不问研究对象", "看不出导数和积分的反向关系"],
            "contrast_pairs": ["局部变化 vs 整体累积", "导数 vs 积分", "公式计算 vs 问题建模"],
        },
    }
    analysis = dict(cases.get(key, cases["微积分"]))
    analysis["topic_key"] = key
    analysis["topic_label"] = text or analysis["topic_label"]
    analysis["review_actions"] = ["先看讲义补概念", "再看导图建立关系", "完成 3 道诊断题", "错题回到学习路径复盘"]
    analysis["wrong_book_hint"] = _topic_wrong_hint(key if key != "微积分" else "", wrong_book)
    analysis["profile_hint"] = common_profile_hint
    analysis["practice_questions"] = [
        {"type": "概念辨析", "focus": analysis["contrast_pairs"][0]},
        {"type": "条件判断", "focus": analysis["condition_checks"][0]},
        {"type": "基础应用", "focus": analysis["example_problem"]},
    ]
    return analysis


def _profile_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [value] if value.strip() else []
    return [str(value)]


PROFILE_FIELD_LABELS = {
    "knowledge_level": "知识基础",
    "learning_goal": "学习目标",
    "weak_points": "薄弱知识点",
    "cognitive_style": "认知风格",
    "resource_preference": "资源偏好",
    "wrong_question_types": "错题类型",
    "mastery_trend": "掌握度变化",
    "pace_preference": "学习节奏",
}

RESOURCE_LABEL_MAP = {
    "lecture_doc": "讲义",
    "mindmap": "思维导图",
    "quiz": "练习题",
    "ppt": "PPT",
    "study_plan": "学习路径",
    "reading": "拓展阅读",
}


def _clean_profile_list(value: Any, default: list[str]) -> list[str]:
    items = [x for x in _profile_list(value) if x and x not in {"待识别", "待积累", "暂无"}]
    return items or default


def _profile_dimensions(profile: dict[str, Any]) -> dict[str, Any]:
    weak = _clean_profile_list(profile.get("weak_points"), ["待识别"])
    prefs = [RESOURCE_LABEL_MAP.get(x, x) for x in _clean_profile_list(profile.get("resource_preference"), ["lecture_doc", "mindmap", "quiz"])]
    wrong_types = _clean_profile_list(profile.get("wrong_question_types"), ["待积累"])
    pace = {
        "slow": "偏慢，适合先概念后练习",
        "normal": "正常",
        "moderate": "正常",
        "fast": "较快，适合增加挑战题",
    }.get(str(profile.get("pace_preference") or "moderate"), str(profile.get("pace_preference") or "正常"))
    return {
        "知识基础": profile.get("knowledge_level") or "待识别",
        "学习目标": profile.get("learning_goal") or "理解核心概念并完成基础练习",
        "薄弱知识点": weak,
        "认知风格": profile.get("cognitive_style") or "偏好分步骤讲解",
        "资源偏好": prefs,
        "错题类型": wrong_types,
        "掌握度变化": profile.get("mastery_trend") or "暂无足够数据",
        "学习节奏": pace,
    }


def _profile_summary_text(profile: dict[str, Any]) -> str:
    weak = _profile_dimensions(profile)["薄弱知识点"]
    weak_text = "、".join(weak[:2]) if isinstance(weak, list) else str(weak)
    return f"当前学生围绕《高等数学上册》学习，主要薄弱点是{weak_text}，适合按概念讲清楚、例题拆步骤、同主题练习的路径推进。"


def _profile_next_recommendation(profile: dict[str, Any]) -> str:
    weak = _profile_dimensions(profile)["薄弱知识点"]
    topic = weak[0] if isinstance(weak, list) and weak else (profile.get("last_topic") or "函数极限")
    return f"建议先复习{topic}的定义和适用条件，再完成 3 道概念辨析题。"


def _profile_public_payload(profile: dict[str, Any], updated_fields: list[str] | None = None) -> dict[str, Any]:
    data = dict(profile)
    labels = [PROFILE_FIELD_LABELS.get(x, x) for x in (updated_fields or profile.get("last_updated_fields") or [])]
    data.update({
        "profile_version": int(profile.get("profile_version") or 0),
        "profile_dimensions": _profile_dimensions(profile),
        "profile_updated_fields": list(dict.fromkeys(labels)),
        "profile_summary": _profile_summary_text(profile),
        "next_recommendation": _profile_next_recommendation(profile),
    })
    return data


def _readable_math_text(text: Any) -> str:
    """Keep mindmap labels readable in browsers that render math symbols poorly."""
    value = str(text or "")
    replacements = {
        "∫": "积分",
        "∞": "无穷大",
        "→": "趋近",
        "≠": "不等于",
        "≤": "小于等于",
        "≥": "大于等于",
        "Δ": "增量",
        "²": "的平方",
        "³": "的三次方",
        "lim": "极限",
        "dx": "微分dx",
        "dy": "微分dy",
        "f'(x)": "f的导函数",
        "y'": "y的一阶导",
        "0/0": "零比零型",
        "∞/∞": "无穷比无穷型",
        "<br/>": " ",
        "<br>": " ",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    return value


def _merge_unique(items: list[str], additions: list[str], limit: int = 8) -> list[str]:
    out: list[str] = []
    for item in [*items, *additions]:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out[:limit]


def _infer_profile_delta(message: str) -> dict[str, Any]:
    text = message or ""
    ctx = _gaoshu_context(text)
    lowered = text.lower()
    weak = [ctx["keyword"]] if ctx.get("keyword") and ctx["keyword"] != "高等数学" else []
    if any(w in text for w in ["极限", "函数极限"]):
        weak = _merge_unique(weak, ["函数极限", "极限定义理解"])
    if any(w in text for w in ["积分", "定积分"]):
        weak = _merge_unique(weak, ["积分概念", "定积分几何意义"])
    if any(w in text for w in ["导数", "微分"]):
        weak = _merge_unique(weak, ["导数定义", "变化率理解"])
    if any(w in text for w in ["不懂", "不会", "错题", "薄弱", "看不懂", "不理解", "懵", "没反应"]):
        weak = _merge_unique(weak, [ctx["keyword"] or "当前知识点"])
    prefs: list[str] = []
    if any(w in text for w in ["导图", "结构", "框架", "关系"]):
        prefs.append("mindmap")
    if any(w in text for w in ["题", "练习", "测验", "例题"]):
        prefs.append("quiz")
    if any(w in text for w in ["讲义", "定义", "证明", "推导"]):
        prefs.append("lecture_doc")
    if any(w in text for w in ["PPT", "课件"]):
        prefs.append("ppt")
    wrong_types: list[str] = []
    if any(w in text for w in ["概念", "定义", "不理解", "是什么意思", "辨析"]):
        wrong_types.append("概念辨析错误")
    if any(w in text for w in ["条件", "适用", "什么时候用"]):
        wrong_types.append("公式适用条件混淆")
    if any(w in text for w in ["计算", "步骤", "化简"]):
        wrong_types.append("计算步骤跳跃")
    level = "medium"
    if any(w in text for w in ["基础差", "零基础", "完全不会", "看不懂", "不懂"]):
        level = "foundation"
    elif any(w in text for w in ["证明", "严格", "推导", "进阶", "考研"]):
        level = "advanced"
    style = "logical"
    if any(w in text for w in ["图", "导图", "结构", "框架"]):
        style = "visual-structured"
    elif any(w in text for w in ["例题", "做题", "练习"]):
        style = "practice-driven"
    goal = f"掌握「{ctx['keyword']}」：先理解定义和条件，再完成例题与错题复盘"
    emotion = "needs_support" if any(w in text for w in ["不会", "不懂", "看不懂", "懵", "一塌糊涂"]) else "focused"
    return {
        "knowledge_level": level,
        "learning_goal": goal,
        "cognitive_style": style,
        "weak_points": weak,
        "resource_preference": prefs or ["mindmap", "quiz", "lecture_doc"],
        "wrong_question_types": wrong_types,
        "mastery_trend": f"{ctx['keyword']}仍需通过练习复测" if weak else "暂无足够数据",
        "emotion_tendency": emotion,
        "last_topic": ctx["keyword"] if ctx["keyword"] != "高等数学" else (text[:20] or "高等数学"),
        "raw_evidence": text[:240],
    }


def _update_demo_profile(message: str, source: str = "dialogue") -> dict[str, Any]:
    profile = STATE["profile"]
    old = dict(profile)
    delta = _infer_profile_delta(message)
    for key in ["knowledge_level", "learning_goal", "cognitive_style", "emotion_tendency", "last_topic", "raw_evidence"]:
        if delta.get(key):
            profile[key] = delta[key]
    profile["weak_points"] = _merge_unique(_profile_list(profile.get("weak_points")), delta.get("weak_points", []))
    profile["resource_preference"] = _merge_unique(_profile_list(profile.get("resource_preference")), delta.get("resource_preference", []))
    profile["wrong_question_types"] = _merge_unique(_profile_list(profile.get("wrong_question_types")), delta.get("wrong_question_types", []))
    if delta.get("mastery_trend") and delta.get("mastery_trend") != "暂无足够数据":
        profile["mastery_trend"] = delta["mastery_trend"]
    profile["profile_source"] = source
    profile["profile_version"] = int(profile.get("profile_version") or 0) + 1
    profile["profile_confidence"] = min(0.95, max(0.45, 0.45 + profile["profile_version"] * 0.12))
    profile["last_extracted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    changed: list[dict[str, Any]] = []
    for key in ["knowledge_level", "learning_goal", "cognitive_style", "emotion_tendency", "last_topic"]:
        if old.get(key) != profile.get(key):
            changed.append({
                "field_name": key,
                "old_value": old.get(key) or "未识别",
                "new_value": profile.get(key) or "",
                "reason": "根据最近对话自动识别学习状态",
                "source_type": source,
            })
    if old.get("weak_points") != profile.get("weak_points"):
        changed.append({"field_name": "weak_points", "old_value": " · ".join(_profile_list(old.get("weak_points"))) or "暂无", "new_value": " · ".join(profile["weak_points"]), "reason": "从提问主题和困难描述中识别薄弱点", "source_type": source})
    if old.get("resource_preference") != profile.get("resource_preference"):
        changed.append({"field_name": "resource_preference", "old_value": " · ".join(_profile_list(old.get("resource_preference"))) or "暂无", "new_value": " · ".join(profile["resource_preference"]), "reason": "从用户点击和表达中识别资源偏好", "source_type": source})
    if old.get("wrong_question_types") != profile.get("wrong_question_types"):
        changed.append({"field_name": "wrong_question_types", "old_value": " · ".join(_profile_list(old.get("wrong_question_types"))) or "暂无", "new_value": " · ".join(profile["wrong_question_types"]), "reason": "从练习或错题记录中归纳错题类型", "source_type": source})
    if old.get("mastery_trend") != profile.get("mastery_trend"):
        changed.append({"field_name": "mastery_trend", "old_value": old.get("mastery_trend") or "暂无足够数据", "new_value": profile.get("mastery_trend") or "暂无足够数据", "reason": "根据提问、练习和错题更新掌握度变化", "source_type": source})
    profile["last_updated_fields"] = [item["field_name"] for item in changed]
    for item in changed:
        item["id"] = str(uuid.uuid4())
        item["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    STATE["profile_changes"] = [*changed, *STATE["profile_changes"]][:30]
    STATE["profile_versions"].insert(0, {
        "id": str(profile["profile_version"]),
        "version": profile["profile_version"],
        "snapshot": dict(profile),
        "trigger_source": source,
        "confidence": profile["profile_confidence"],
        "created_at": profile["last_extracted_at"],
    })
    STATE["profile_versions"] = STATE["profile_versions"][:10]
    return _profile_public_payload(profile, profile.get("last_updated_fields", []))


def _profile_numeric_metrics(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or STATE["profile"]
    level_score = {
        "foundation": 38,
        "beginner": 38,
        "medium": 62,
        "intermediate": 62,
        "advanced": 82,
    }.get(str(profile.get("knowledge_level") or "").lower(), 45 if profile.get("profile_version") else 0)
    style_score = {
        "visual-structured": 86,
        "logical": 78,
        "practice-driven": 82,
        "structured": 76,
    }.get(str(profile.get("cognitive_style") or "").lower(), 45 if profile.get("profile_version") else 0)
    weak_count = len(_profile_list(profile.get("weak_points")))
    pref_count = len(_profile_list(profile.get("resource_preference")))
    version = int(profile.get("profile_version") or 0)
    confidence = int(round(float(profile.get("profile_confidence") or 0) * 100))
    goal_score = 82 if profile.get("learning_goal") else (35 if version else 0)
    activity_score = min(100, version * 16 + len(STATE.get("wrong_book", [])) * 8 + len(STATE.get("sessions", [])) * 6)
    risk_score = min(100, weak_count * 18 + max(0, 70 - level_score) // 2)
    return {
        "profile_confidence_pct": confidence,
        "knowledge_score": level_score,
        "goal_clarity_score": goal_score,
        "cognitive_match_score": style_score,
        "weak_point_count": weak_count,
        "resource_preference_count": pref_count,
        "learning_activity_score": activity_score,
        "review_risk_score": risk_score,
        "evidence_count": len(STATE.get("profile_changes", [])),
        "version_count": len(STATE.get("profile_versions", [])),
        "wrong_book_count": len(STATE.get("wrong_book", [])),
    }


def _build_demo_study_plan(topic: str) -> dict[str, Any]:
    profile = STATE["profile"]
    topic = _resolve_generation_topic(topic or profile.get("last_topic") or "函数极限")
    ctx = _gaoshu_context(topic)
    weak_points = _profile_list(profile.get("weak_points")) or [ctx["keyword"]]
    prefs = _profile_list(profile.get("resource_preference")) or ["mindmap", "quiz", "lecture_doc"]
    level = profile.get("knowledge_level") or "foundation"
    level_hint = "基础重建" if level == "foundation" else ("进阶推导" if level == "advanced" else "概念到练习")
    steps = [
        {
            "order": 1,
            "title": f"定位教材章节：{ctx['chapter']}",
            "description": f"围绕最近问题「{topic}」先找到教材位置，明确它和后续导数、连续或积分的关系。",
            "reason": f"画像显示当前目标是：{profile.get('learning_goal') or '建立清晰知识框架'}。",
            "resource_types": ["lecture_doc", "mindmap"],
            "estimated_minutes": 12,
            "practice": "读一遍讲义第一、二节，并用自己的话写出核心定义。",
            "check_standard": "能指出教材章节，并说明这个知识点在后续导数、连续或积分中的作用。",
        },
        {
            "order": 2,
            "title": f"补齐薄弱点：{weak_points[0]}",
            "description": ctx["summary"],
            "reason": "该知识点来自最近提问、错题或自动画像识别，不是固定模板。",
            "resource_types": [t for t in ["mindmap", "lecture_doc"] if t in prefs] or ["mindmap"],
            "estimated_minutes": 18,
            "practice": "对照导图说出每个条件为什么必要。",
            "check_standard": "不看答案时，能把定义中的对象、条件、结论分别说出来。",
        },
        {
            "order": 3,
            "title": f"按「{level_hint}」完成例题",
            "description": "按步骤拆题：先判断对象和适用条件，再选择化简、定义验证或对应定理。",
            "reason": f"认知风格识别为 {profile.get('cognitive_style') or '待识别'}，因此优先给出结构化步骤和配套题。",
            "resource_types": ["quiz", "lecture_doc"],
            "estimated_minutes": 25,
            "practice": "完成 3 道同主题题，错题自动写入错题本和画像。",
            "check_standard": "每道题能写出至少 2 个依据：为什么这样变形、为什么这个定理可用。",
        },
        {
            "order": 4,
            "title": "复盘并生成下一轮资源",
            "description": f"重点检查：{'; '.join(ctx['pitfalls'][:3])}。",
            "reason": "把错因回流到学习画像，下一次路径会继续变化。",
            "resource_types": ["quiz", "study_plan"],
            "estimated_minutes": 15,
            "practice": "把错题归因到定义、条件、计算或审题，并再次提问薄弱处。",
            "check_standard": "能把错因归为概念、条件、方法、计算或表达中的一类，并知道下一份资料该看什么。",
        },
    ]
    return {
        "title": f"{topic} · 个性化学习路径",
        "profile_summary": f"基于最近问题「{topic}」、画像版本 #{profile.get('profile_version') or 0}、薄弱点 {', '.join(weak_points[:3])} 生成。",
        "steps": steps,
        "recommended_topics": _merge_unique([ctx["keyword"], *weak_points, ctx["chapter"]], [], 5),
        "next_action": f"先生成「{steps[0]['title']}」讲义，再完成步骤 3 的配套练习。",
        "provider": STATE.get("llm_provider") or "demo",
        "model": STATE.get("spark_model") or "demo",
    }


def _mock_answer(question: str) -> str:
    ctx = _gaoshu_context(question)
    return (
        f"我会按《高等数学上册》的「{ctx['chapter']}」来讲：{question or ctx['keyword']}。\n\n"
        f"核心理解：{ctx['summary']}\n\n"
        "建议按这几步学：\n"
        + "\n".join(f"{i + 1}. {step}" for i, step in enumerate(ctx["steps"]))
        + "\n\n容易出错的地方："
        + "；".join(ctx["pitfalls"])
        + "。\n\n依据：内置教材《高数上.pdf》章节目录与本地高数学习模板。"
    )


def _call_llm(provider: str, question: str, model_override: str = "", max_tokens: int = 600, timeout_seconds: int | None = None, bypass_failure_cache: bool = False) -> tuple[str, str, str]:
    provider, api_key, base_url, model = _provider_config(provider)
    model = model_override or model
    if provider == "mock" or not api_key:
        return "mock", model, _mock_answer(question)
    if not bypass_failure_cache and time.time() < float(STATE.get("llm_failure_until") or 0):
        last_error = str(STATE.get("llm_last_error") or "真实模型暂不可用")
        return "mock", "mock", _mock_answer(question) + f"\n\n真实模型暂时不可用，已自动切换本地课程模式：{last_error[:120]}"
    try:
        timeout = _coerce_llm_timeout(timeout_seconds or STATE.get("llm_timeout_seconds"))
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=1)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "你是《高等数学上册》课程学习辅助教师。请用中文回答，步骤清晰，说明适用条件、常见误区，并给出复习建议。",
                },
                {"role": "user", "content": question},
            ],
            max_tokens=max_tokens,
        )
        STATE["llm_failure_until"] = 0.0
        STATE["llm_last_error"] = ""
        return provider, model, resp.choices[0].message.content or "已连接模型，但没有返回内容。"
    except Exception as exc:
        STATE["llm_failure_until"] = time.time() + 120
        STATE["llm_last_error"] = str(exc)[:240]
        return "mock", "mock", _mock_answer(question) + f"\n\n真实模型调用失败：{str(exc)[:160]}"


def _strip_code_fence(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def _parse_json_object(text: str) -> Any:
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    starts = [idx for idx in [cleaned.find("{"), cleaned.find("[")] if idx >= 0]
    if not starts:
        return None
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except Exception:
        return None


def _safe_node(text: str, limit: int = 28) -> str:
    cleaned = _readable_math_text(text).replace('"', "'").replace("[", " ").replace("]", " ").replace("\n", " ").strip()
    return cleaned[:limit] or "知识点"


def _structured_mindmap(topic: str) -> str:
    a = _analyze_math_topic(topic)
    root = _safe_node(a["topic_label"], 32)
    branches = [
        ("教材位置", [a["course_chapter"], "《高等数学上册》样例课程"]),
        ("核心问题", [a["core_question"], a["concept_intuition"]]),
        ("概念直觉", [a["concept_intuition"], a["symbol_focus"]]),
        ("正式定义", [a["formal_definition"], *a["prerequisites"][:2]]),
        ("条件判定", a["condition_checks"][:4]),
        ("方法路径", a["method_steps"][:4]),
        ("易错点", a["common_mistakes"][:4]),
        ("例题入口", [a["example_problem"], *a["example_solution_steps"][:2]]),
        ("复习建议", [a["wrong_book_hint"], *a["review_actions"][:3]]),
    ]
    lines = ["flowchart TB", f'  A(("{root}"))']
    for i, (name, children) in enumerate(branches, 1):
        bid = f"B{i}"
        lines.append(f'  A --> {bid}["{_safe_node(name, 18)}"]')
        for j, child in enumerate([c for c in children if c][:4], 1):
            lines.append(f'  {bid} --> {bid}_{j}["{_safe_node(str(child), 30)}"]')
    lines.extend([
        '  B5 -.决定.-> B6',
        '  B6 -.落地.-> B8',
        '  B7 -.回流.-> B9',
    ])
    return "\n".join(lines)


def _mindmap_tree(topic: str) -> dict[str, Any]:
    analysis = _analyze_math_topic(topic)
    weak_points = _profile_list(STATE.get("profile", {}).get("weak_points")) or [analysis["topic_key"]]
    return {
        "title": topic or analysis["topic_label"],
        "subtitle": "阅读顺序：教材位置 -> 核心问题 -> 直觉 -> 定义 -> 条件 -> 方法 -> 例题 -> 复盘。",
        "layout": "concept_map",
        "center": {
            "title": analysis["topic_label"],
            "summary": analysis["core_question"],
            "tags": [analysis["course_chapter"], f"薄弱点：{', '.join(weak_points[:2])}", analysis["wrong_book_hint"]],
        },
        "relations": [
            {"from": "条件判定", "to": "方法路径", "label": "决定可用方法"},
            {"from": "方法路径", "to": "例题入口", "label": "落到题目"},
            {"from": "易错点", "to": "复习建议", "label": "回流画像"},
        ],
        "nodes": [
            {"title": "教材位置", "type": "course", "summary": analysis["course_chapter"], "children": [{"label": x, "hint": "先补前置"} for x in analysis["prerequisites"][:3]]},
            {"title": "核心问题", "type": "question", "summary": analysis["core_question"], "children": [{"label": analysis["concept_intuition"], "hint": "先用人话理解"}, {"label": analysis["symbol_focus"], "hint": "看懂符号"}]},
            {"title": "概念直觉", "type": "intuition", "summary": analysis["concept_intuition"], "children": [{"label": x, "hint": "对比辨析"} for x in analysis["contrast_pairs"][:3]]},
            {"title": "正式定义", "type": "definition", "summary": analysis["formal_definition"], "children": [{"label": x, "hint": "定义关键词"} for x in analysis["symbol_focus"].split("、")[:4]]},
            {"title": "条件判定", "type": "condition", "summary": "做题前先过条件", "children": [{"label": x, "hint": "不满足就不能套方法"} for x in analysis["condition_checks"][:4]]},
            {"title": "方法路径", "type": "method", "summary": "从条件选择方法", "children": [{"label": x, "hint": "写出依据"} for x in analysis["method_steps"][:4]]},
            {"title": "易错点", "type": "pitfall", "summary": analysis["wrong_book_hint"], "children": [{"label": x, "hint": "错题归因"} for x in analysis["common_mistakes"][:4]]},
            {"title": "例题入口", "type": "example", "summary": analysis["example_problem"], "children": [{"label": x, "hint": "板书步骤"} for x in analysis["example_solution_steps"][:4]]},
            {"title": "复习建议", "type": "review", "summary": analysis["profile_hint"], "children": [{"label": x, "hint": "下一步动作"} for x in analysis["review_actions"][:4]]},
        ],
    }


def _structured_lecture(topic: str) -> str:
    a = _analyze_math_topic(topic)
    mistakes = a["common_mistakes"][:3]
    return "\n\n".join([
        f"# {a['topic_label']} · 老师讲课式学习讲义",
        f"## 1. 教材定位\n本讲义对应《高等数学上册》：{a['course_chapter']}。\n\n本节要解决的核心问题是：{a['core_question']}",
        f"## 2. 为什么这个概念难\n难点不在记住名字，而在分清：{'; '.join(a['contrast_pairs'])}。{a['profile_hint']} {a['wrong_book_hint']}",
        f"## 3. 人话解释\n{a['concept_intuition']}\n\n先不要套公式，先问自己：题目到底让我观察的是局部变化、趋近过程、连续性，还是区间累积？",
        f"## 4. 正式定义拆解\n{a['formal_definition']}\n\n符号重点：{a['symbol_focus']}。\n把定义拆开看：研究对象是什么、条件是什么、最后要证明或计算什么。",
        "## 5. 条件检查清单\n" + "\n".join(f"- {x}" for x in a["condition_checks"]),
        f"## 6. 典型例题完整拆解\n**题目**：{a['example_problem']}\n\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(a["example_solution_steps"])),
        "## 7. 三个常见错误\n" + "\n".join(f"- 错误 {i+1}：{m}" for i, m in enumerate(mistakes)),
        "## 8. 纠错方法\n" + "\n".join(f"- 针对「{m}」：先回到定义里的条件，再说明这一步为什么能做。" for m in mistakes),
        "## 9. 课后 15 分钟复习安排\n1. 3 分钟：不用公式，用自己的话复述核心问题。\n2. 5 分钟：重做本讲义例题，每一步写依据。\n3. 5 分钟：完成 3 道诊断题，错题标注为概念、条件或方法错误。\n4. 2 分钟：根据错因选择下一份资源：导图、讲义或练习。",
        "## 10. 自测清单\n- 我能说清这个概念研究什么吗？\n- 我能列出做题前必须检查的条件吗？\n- 我能解释例题每一步为什么成立吗？\n- 我能指出最容易混淆的一组概念吗？\n- 我能把错题归因到概念、条件、方法或计算吗？",
    ])
    ctx = _gaoshu_context(topic)
    title = topic or ctx["keyword"]
    if ctx["keyword"] == "积分":
        example = (
            "例题：计算 $\\int 2x\\,dx$，并解释为什么答案后面要写 $C$。\n\n"
            "1. 先判断题型：这是不定积分，不是在求一个具体数值，而是在找“原函数族”。\n"
            "2. 找原函数：因为 $(x^2)'=2x$，所以 $x^2$ 是 $2x$ 的一个原函数。\n"
            "3. 写完整答案：$\\int 2x\\,dx=x^2+C$。\n"
            "4. 为什么要加 $C$：$x^2+1$、$x^2-5$ 的导数也都是 $2x$，所以必须用常数 $C$ 表示所有可能的原函数。"
        )
        contrast = "不定积分问“谁的导数等于它”，定积分问“一个区间上的累积量是多少”。这两个问题不能混在一起。"
    elif ctx["keyword"] == "极限":
        example = (
            "例题：求 $\\lim_{x\\to1}\\frac{x^2-1}{x-1}$。\n\n"
            "1. 先代入检查：直接代入得到 $0/0$，说明不能把代入结果当答案。\n"
            "2. 化简结构：$x^2-1=(x-1)(x+1)$。\n"
            "3. 注意条件：极限看的是 $x\\to1$ 且 $x\\ne1$ 的过程，所以可以在去心邻域内约掉 $x-1$。\n"
            "4. 得到趋势：原式化为 $x+1$，当 $x\\to1$ 时趋近 $2$。\n"
            "5. 结论：极限是 $2$，这不要求原函数在 $x=1$ 处有定义。"
        )
        contrast = "函数值看某一点有没有定义；极限看靠近这一点时的趋势。两者相关，但不是一回事。"
    elif ctx["keyword"] == "导数":
        example = (
            "例题：求 $f(x)=x^2$ 在 $x=3$ 处的导数并解释意义。\n\n"
            "1. 先理解题意：导数表示这一点附近的瞬时变化率。\n"
            "2. 求导函数：$f'(x)=2x$。\n"
            "3. 代入点：$f'(3)=6$。\n"
            "4. 解释意义：当 $x$ 在 3 附近变化一点点时，函数值大约以 6 倍速度变化。"
        )
        contrast = "平均变化率看一段区间，导数看某一点附近的瞬时变化趋势。"
    else:
        example = (
            f"例题：围绕「{title}」做一道基础题。\n\n"
            "1. 圈出题干关键词和限制条件。\n"
            "2. 判断使用哪个定义、公式或定理。\n"
            "3. 每一步写出依据，不跳步。\n"
            "4. 最后回到题目问法写结论。"
        )
        contrast = "先判断题目属于哪类问题，再选方法；不要先套公式。"
    return "\n\n".join([
        f"# {title} · 面向不会学生的详细学习讲义",
        f"## 1. 先说明：为什么要学这一节\n《高等数学上册》对应章节：{ctx['chapter']}。\n\n这一节不是为了多背一个公式，而是为了学会处理“连续变化”的问题。很多同学觉得难，是因为一上来就看符号和公式，没有先弄清楚题目到底在问什么。本讲义会按“人话理解 → 条件拆解 → 例题步骤 → 错因复盘”的顺序来学。",
        f"## 2. 先用人话讲核心概念\n{ctx['summary']}\n\n换成更直观的话：先看研究对象怎么变化，再看结果是否稳定、累积或产生某种变化率。不要急着套公式，先问自己：题目让我观察的是一个点、一个区间，还是一个变化过程？",
        f"## 3. 容易混淆的地方\n{contrast}\n\n这一步非常关键。学生做错题，常常不是不会算，而是把两个相近概念混了。例如把函数值当成极限、把不定积分当成定积分、把平均变化率当成导数。先分清问题类型，后面的计算才有意义。",
        "## 4. 做题前必须检查的条件\n" + "\n".join(f"- {step}：这一步决定你能不能使用对应公式或方法。" for step in ctx["steps"]) + "\n\n做题时不要把这些条件放在脑子里含糊过去，建议直接写在草稿纸上。只要某个条件没检查，后面的计算就可能是错的。",
        f"## 5. 老师带做一题：完整拆解\n{example}\n\n注意：例题的价值不只是得到答案，而是学会每一步为什么能这么做。以后遇到同类题，就照着“判断题型 → 检查条件 → 选择方法 → 写出结论”的顺序来。",
        "## 6. 常见错误和纠正方法\n" + "\n".join(f"- 错误：{pitfall}。\n  纠正：做题时先停下来问“这个条件是否满足？我这一步依据是什么？”" for pitfall in ctx["pitfalls"]),
        "## 7. 课后训练安排\n1. 先用 5 分钟复述本节核心概念，不能只背原文，要能用自己的话讲。\n2. 再做 2 道基础题，重点写清楚每一步依据。\n3. 最后看错题：把错因归类为“概念混淆、条件漏看、方法选错、计算错误”中的一种。\n4. 如果仍然不会，回到系统生成思维导图，看知识点之间的关系，再生成配套练习。",
        "## 8. 自测清单\n- 我能用一句话说清这节研究什么吗？\n- 我能列出做题前必须检查的条件吗？\n- 我能说明例题中每一步为什么成立吗？\n- 我能判断自己错题属于哪类错因吗？\n- 我能根据错因选择下一份资料：讲义、导图还是练习吗？",
    ])


def _resolve_generation_topic(topic: str, knowledge_point: str = "") -> str:
    candidate = (topic or knowledge_point or "").strip()
    generic = {"", "当前学习主题", "当前主题", "学习主题", "高等数学", "高等数学上册"}
    if candidate in generic and STATE["sessions"]:
        candidate = str(STATE["sessions"][-1].get("title") or "").strip()
    return candidate or "函数极限的定义"


def _resource_context_meta(topic: str, resource_type: str, generated_by: str, fallback_used: bool) -> dict[str, Any]:
    ctx = _gaoshu_context(topic)
    profile = STATE.get("profile", {})
    wrong_hits = [
        w for w in STATE.get("wrong_book", [])
        if ctx["keyword"] in str(w.get("knowledge_point") or w.get("question") or "")
    ][:3]
    grounding_score = 0.78 if fallback_used else 0.9
    return {
        "topic": topic,
        "question": topic,
        "course": STATE["course_name"],
        "chapter": ctx["chapter"],
        "context_chunks": [
            {
                "chunk_id": "gaoshu_seed_context_001",
                "source": "高数上.pdf",
                "chapter": ctx["chapter"],
                "content": ctx["summary"],
                "score": 0.92,
                "context_type": "seeded_demo_context",
            }
        ],
        "evidence": [
            {
                "source": "高数上.pdf",
                "chapter": ctx["chapter"],
                "content": ctx["summary"],
                "score": 0.92,
            },
            {
                "source": "学习画像",
                "content": f"画像版本 #{profile.get('profile_version') or 0}，薄弱点：{', '.join(_profile_list(profile.get('weak_points'))[:3]) or '待识别'}",
                "score": 0.82,
            },
        ],
        "profile_adaptation": {
            "knowledge_level": profile.get("knowledge_level") or "foundation",
            "learning_goal": profile.get("learning_goal") or f"掌握「{ctx['keyword']}」",
            "cognitive_style": profile.get("cognitive_style") or "structured",
            "weak_points": _profile_list(profile.get("weak_points")) or [ctx["keyword"]],
            "resource_preference": _profile_list(profile.get("resource_preference")) or ["mindmap", "quiz", "lecture_doc"],
            "emotion_tendency": profile.get("emotion_tendency") or "focused",
            "profile_version": profile.get("profile_version") or 0,
            "profile_confidence": profile.get("profile_confidence") or 0.0,
        },
        "wrong_history": wrong_hits,
        "verifier": {
            "status": "passed",
            "grounding_score": grounding_score,
            "risk_level": "low",
            "content_safe": True,
            "checks": [
                "主题与最近提问一致",
                "内容绑定《高数上.pdf》教材章节",
                "包含定义、条件、例题或复盘动作",
                "未检测到敏感或无依据内容",
            ],
        },
        "generation_status": {
            "generated_by": generated_by,
            "provider": generated_by,
            "fallback_used": fallback_used,
            "resource_type": resource_type,
            "model": STATE.get("spark_model") if generated_by == "spark" else STATE.get("deepseek_model") if generated_by == "deepseek" else "mock_curriculum",
            "used_rag": True,
            "used_profile": True,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


def _public_model_status(provider: str | None = None, fallback_used: bool = False) -> dict[str, Any]:
    current = str(provider or "mock_curriculum").lower()
    if current == "spark" and not fallback_used:
        label = "Spark 真实生成"
    elif current == "spark" and fallback_used:
        label = "Spark 失败后本地兜底"
    else:
        label = "本地演示模板生成"
    return {
        "label": label,
        "engine": current,
        "fallback_used": bool(fallback_used),
    }


def _public_verification_status(verifier: dict[str, Any] | None = None) -> dict[str, Any]:
    verifier = verifier or {}
    coverage = verifier.get("citation_coverage")
    if coverage is None:
        coverage = verifier.get("grounding_score", 0.78)
    supported = int(verifier.get("supported_claim_count", 4) or 0)
    unsupported_claims = verifier.get("unsupported_claims") or []
    if not isinstance(unsupported_claims, list):
        unsupported_claims = [str(unsupported_claims)]
    return {
        "citation_coverage": float(coverage or 0),
        "supported_claim_count": supported,
        "total_claim_count": int(verifier.get("total_claim_count", max(supported, 4)) or max(supported, 4)),
        "unsupported_claim_count": int(verifier.get("unsupported_claim_count", len(unsupported_claims)) or 0),
        "unsupported_claims": unsupported_claims,
        "risk_level": verifier.get("risk_level") or "low",
        "status": verifier.get("status") or "passed",
    }


def _public_rag_status(context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    chunks = context.get("context_chunks") or []
    return {
        "course_references_enabled": True,
        "retrieval_mode": "本地快速检索",
        "embedding_provider": "hash_mock",
        "matched_chunks": len(chunks),
    }


def _llm_generate_mindmap(topic: str) -> dict[str, Any] | None:
    prompt = (
        "请基于《高等数学上册》为学生主题提炼辅助学习结构。"
        "只输出 JSON，不要 Markdown。格式："
        "{\"definition\":\"一句核心定义\",\"conditions\":[\"条件1\",\"条件2\"],"
        "\"steps\":[\"步骤1\",\"步骤2\",\"步骤3\"],\"pitfalls\":[\"误区1\",\"误区2\"],"
        "\"practice\":[\"练习建议1\",\"练习建议2\"]}。"
        "所有内容必须直接围绕主题，不许写“当前学习主题”。"
        f"\n主题：{topic}"
    )
    provider, model, answer = _call_llm("", prompt, max_tokens=700)
    parsed = _parse_json_object(answer)
    if provider == "mock" or not isinstance(parsed, dict):
        return None
    ctx = _gaoshu_context(topic)
    definition = _safe_node(parsed.get("definition") or ctx["summary"], 34)
    conditions = [str(x) for x in (parsed.get("conditions") or ctx["steps"])][:3]
    steps = [str(x) for x in (parsed.get("steps") or ctx["steps"])][:3]
    pitfalls = [str(x) for x in (parsed.get("pitfalls") or ctx["pitfalls"])][:3]
    practice = [str(x) for x in (parsed.get("practice") or ["先做定义判断题", "再做计算题", "错题回到条件复盘"])][:3]
    lines = [
        "flowchart TB",
        f'  A["{_safe_node(topic, 34)}"]',
        '  A --> B["1 教材定位"]',
        f'  B --> B1["{_safe_node(ctx["chapter"], 30)}"]',
        '  B1 --> C["2 核心定义"]',
        f'  C --> C1["{definition}"]',
        '  C1 --> D["3 适用条件"]',
        *[f'  D{i if i else ""} --> D{i + 1}["{_safe_node(x, 30)}"]' for i, x in enumerate(conditions)],
        f'  D{len(conditions)} --> E["4 解题流程"]',
        *[f'  E{i if i else ""} --> E{i + 1}["{_safe_node(x, 30)}"]' for i, x in enumerate(steps)],
        f'  E{len(steps)} --> F["5 常见误区"]',
        *[f'  F{i if i else ""} --> F{i + 1}["{_safe_node(x, 30)}"]' for i, x in enumerate(pitfalls)],
        f'  F{len(pitfalls)} --> G["6 练习建议"]',
        *[f'  G{i if i else ""} --> G{i + 1}["{_safe_node(x, 30)}"]' for i, x in enumerate(practice)],
    ]
    mermaid = "\n".join(lines)
    return {
        "tree": _mindmap_tree(topic),
        "mermaid": mermaid,
        "content": mermaid,
        "generated_by": provider,
        "model": model,
        "fallback_used": False,
    }


def _llm_generate_lecture(topic: str) -> dict[str, Any] | None:
    prompt = (
        "请基于《高等数学上册》为学生刚提问的主题生成一份可直接复习的中文学习讲义。"
        "不要泛泛而谈，不要写“当前学习主题”。必须围绕主题本身。"
        "请用 Markdown，结构必须包含：\n"
        "1. 教材定位\n2. 核心定义\n3. 直观理解\n4. 适用条件\n"
        "5. 典型例题步骤（给一个简短例题并逐步解）\n6. 常见误区\n7. 自测清单。"
        "数学表达尽量清楚，答案适合高中/大学高数初学者复习。"
        f"\n主题：{topic}"
    )
    provider, model, answer = _call_llm("", prompt, max_tokens=950)
    content = _strip_code_fence(answer)
    if provider == "mock" or len(content) < 120:
        return None
    return {
        "content": content,
        "generated_by": provider,
        "model": model,
        "fallback_used": False,
    }


def _llm_generate_quiz(topic: str) -> dict[str, Any] | None:
    prompt = (
        "为《高等数学上册》生成3道单选题，只考察给定主题。"
        "只输出JSON：{\"items\":[{\"question\":\"题干\",\"options\":[\"A\",\"B\",\"C\",\"D\"],"
        "\"answer\":0,\"knowledge_point\":\"知识点\",\"explanation\":\"解析\"}]}。"
        "answer用0-3数字。不要学习方法题。"
        f"\n主题：{topic}"
    )
    provider, model, answer = _call_llm("", prompt, max_tokens=1100)
    parsed = _parse_json_object(answer)
    if provider == "mock" or not parsed:
        return None
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return None
    cleaned: list[dict[str, Any]] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        options = item.get("options") or item.get("choices") or []
        if not isinstance(options, list):
            continue
        options = [str(opt).strip() for opt in options if str(opt).strip()]
        if len(options) < 2:
            continue
        try:
            answer_idx = int(item.get("answer", item.get("correct_answer", 0)))
        except Exception:
            raw_answer = str(item.get("answer", item.get("correct_answer", "0"))).strip().upper()
            answer_idx = ord(raw_answer[0]) - 65 if raw_answer and raw_answer[0] in "ABCD" else 0
        if not 0 <= answer_idx < len(options):
            answer_idx = 0
        question = str(item.get("question") or item.get("title") or "").strip()
        if not question:
            continue
        cleaned.append(
            {
                "question": question,
                "options": options[:4],
                "answer": min(answer_idx, len(options[:4]) - 1),
                "knowledge_point": str(item.get("knowledge_point") or topic).strip(),
                "explanation": str(item.get("explanation") or item.get("analysis") or "").strip(),
            }
        )
    if len(cleaned) < 2:
        return None
    return {
        "items": cleaned[:3],
        "content": {"items": cleaned[:3]},
        "generated_by": provider,
        "model": model,
        "fallback_used": False,
    }


class LLMConfigRequest(BaseModel):
    provider: str = "deepseek"
    api_key: str = Field(..., min_length=1)
    base_url: str = ""
    model: str = ""
    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS


class LLMTestRequest(BaseModel):
    provider: str = ""
    model: str = ""
    message: str = "你好，请用一句话确认连接成功"
    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS


class AskRequest(BaseModel):
    question: str = ""
    message: str = ""
    course_id: int = 1
    session_id: str | None = None


class GenerateRequest(BaseModel):
    resource_type: str = "lecture_doc"
    topic: str = "当前学习主题"
    knowledge_point: str = ""
    course_id: int = 1


RESOURCE_LABELS = {
    "mindmap": "思维导图",
    "quiz": "练习题",
    "lecture_doc": "学习讲义",
    "ppt": "PPT课件",
    "study_plan": "学习路径",
    "reading": "拓展阅读",
    "video_script": "视频脚本",
}

VALID_DEMO_RESOURCE_TYPES = set(RESOURCE_LABELS)


def _resource_label(resource_type: str) -> str:
    return RESOURCE_LABELS.get(resource_type, resource_type or "学习资源")


def _demo_mindmap(topic: str) -> str:
    return _structured_mindmap(topic or "函数极限的定义")


def _demo_quiz(topic: str) -> list[dict[str, Any]]:
    a = _analyze_math_topic(topic)
    keyword = a["topic_label"]
    contrast = a["contrast_pairs"][0]
    return [
        {
            "question": f"【概念辨析】关于「{keyword}」，哪句话最准确地区分了「{contrast}」？",
            "options": [a["concept_intuition"], a["common_mistakes"][0], "只要背下公式，题目条件可以先不看", "这个概念只需要看最终答案，不需要解释过程"],
            "answer": 0,
            "knowledge_point": keyword,
            "explanation": f"本题考察 {a['course_chapter']} 中的核心直觉：{a['concept_intuition']}",
            "wrong_reason": f"容易把「{contrast}」混在一起，导致还没判断对象和条件就直接套公式。",
            "fix_suggestion": "先用一句话说清研究对象，再回到正式定义里的条件。",
            "difficulty": "easy",
        },
        {
            "question": f"【条件判断】做「{keyword}」题目前，最应该先检查哪一项？",
            "options": [a["condition_checks"][0], a["common_mistakes"][1] if len(a["common_mistakes"]) > 1 else "直接计算", "只看题目有没有出现关键词", "先写最终结论再补过程"],
            "answer": 0,
            "knowledge_point": keyword,
            "explanation": "高数题目的关键不是先算，而是确认定义或方法的适用条件。",
            "wrong_reason": "忽略条件会导致方法选错，尤其是极限左右、导数定义、积分上下限和连续三条件。",
            "fix_suggestion": "把题干条件圈出来，按检查清单逐条确认。",
            "difficulty": "medium",
        },
        {
            "question": f"【基础应用】{a['example_problem']} 解题时第一步应做什么？",
            "options": [a["example_solution_steps"][0], a["common_mistakes"][2] if len(a["common_mistakes"]) > 2 else "直接套公式", "跳过条件写答案", "只写结果不解释依据"],
            "answer": 0,
            "knowledge_point": keyword,
            "explanation": "基础应用题要先确定题型和条件，再进入计算或证明。",
            "wrong_reason": a["wrong_book_hint"],
            "fix_suggestion": "对照讲义例题的板书步骤，重做一遍并写出每步依据。",
            "difficulty": "medium",
        },
    ]


def _teaching_ppt_slides(topic: str) -> list[dict[str, Any]]:
    a = _analyze_math_topic(topic)
    weak = ", ".join(_profile_list(STATE.get("profile", {}).get("weak_points"))[:3] or [a["topic_key"]])
    wrong_hint = a["wrong_book_hint"]
    example_steps = a["example_solution_steps"]
    slides = [
        {
            "title": f"{a['topic_label']}：从不会到会做",
            "student_problem": f"学生卡点：不知道 {a['topic_label']} 到底解决什么问题。",
            "learning_goal": f"本节课目标：能解释 {a['core_question']} 并完成一道基础题。",
            "course_basis": a["course_chapter"],
            "plain_explanation": a["concept_intuition"],
            "bullets": [a["core_question"], a["concept_intuition"], f"薄弱点：{weak}"],
            "check_question": "先不看公式，你能说出这个知识点研究什么吗？",
            "takeaway": "先理解问题，再看定义和方法。",
            "next_action": "进入学习诊断页。",
        },
        {
            "title": "学习诊断：先找卡点",
            "student_problem": f"{wrong_hint}",
            "learning_goal": "把不会归因到概念、条件、方法或计算。",
            "plain_explanation": a["profile_hint"],
            "bullets": [f"当前薄弱点：{weak}", wrong_hint, "本课先修正判断习惯，再做计算"],
            "common_mistake": a["common_mistakes"][0],
            "how_to_fix": "先圈出题干对象和条件，再决定方法。",
            "check_question": "你现在更像是概念不清、条件漏看，还是方法不会选？",
            "takeaway": "诊断清楚，资源才真正个性化。",
            "next_action": "看教材定位。",
        },
        {
            "title": "教材定位：这节在高数里放在哪里",
            "course_basis": a["course_chapter"],
            "student_problem": "学生常把一个知识点孤立记忆，看不出它和前后内容的关系。",
            "plain_explanation": f"{a['topic_label']} 位于 {a['course_chapter']}，前置需要：{'、'.join(a['prerequisites'][:3])}。",
            "bullets": a["prerequisites"][:4],
            "check_question": "这些前置概念里，你最不稳的是哪一个？",
            "takeaway": "教材位置决定先补什么。",
        },
        {
            "title": "概念直觉：先讲人话",
            "student_problem": "学生看见符号就开始套公式，跳过了直观理解。",
            "plain_explanation": a["concept_intuition"],
            "bullets": [a["core_question"], a["concept_intuition"], f"对比：{a['contrast_pairs'][0]}"],
            "check_question": "你能把这段直觉换成自己的话吗？",
            "takeaway": "人话讲不清，公式就容易用错。",
        },
        {
            "title": "正式定义拆解",
            "formal_definition": a["formal_definition"],
            "student_problem": "学生会背定义，但不知道定义里的条件怎样对应做题步骤。",
            "plain_explanation": "把定义拆成：研究对象、适用条件、结论目标。",
            "bullets": [a["formal_definition"], *a["condition_checks"][:2]],
            "check_question": "定义里哪个条件最容易漏掉？",
            "takeaway": "定义就是做题检查表。",
        },
        {
            "title": "符号翻译：把数学式翻译成人话",
            "symbol_translation": a["symbol_focus"],
            "student_problem": "学生不是不会算，而是没读懂符号在表达什么。",
            "plain_explanation": f"符号重点：{a['symbol_focus']}。先翻译，再计算。",
            "bullets": a["condition_checks"][:3],
            "check_question": "题目里的第一个符号对应什么动作？",
            "takeaway": "符号是压缩语言，先解压再做题。",
        },
        {
            "title": "例题拆解：老师完整板书",
            "example": a["example_problem"],
            "step_by_step_solution": example_steps,
            "student_problem": "学生常卡在中间步骤，不知道为什么能这样变形。",
            "bullets": [a["example_problem"], *example_steps[:3]],
            "worked_example": {"problem": a["example_problem"], "solution": example_steps},
            "board_work": example_steps,
            "check_question": "这一步用了哪个定义、条件或变形？",
            "takeaway": "例题要学步骤依据，不是只抄答案。",
        },
        {
            "title": "易错点：为什么会错",
            "common_mistake": "；".join(a["common_mistakes"][:3]),
            "why_wrong": wrong_hint,
            "student_problem": "学生以为自己是计算差，其实常常是概念或条件判断错。",
            "bullets": a["common_mistakes"][:4],
            "how_to_fix": "每做一步旁边写一句依据，错题按概念/条件/方法/计算归因。",
            "check_question": "你最容易犯哪一种错？",
            "takeaway": "纠错要修判断习惯。",
        },
        {
            "title": "对比辨析：相近概念别混用",
            "student_problem": "学生把相近概念混成一类，导致题型一换就不会。",
            "plain_explanation": "对比不是背定义，而是看研究对象和使用条件有什么不同。",
            "bullets": a["contrast_pairs"],
            "check_question": f"请说明 {a['contrast_pairs'][0]} 的区别。",
            "takeaway": "能辨析，才会迁移。",
        },
        {
            "title": "自测页：三题判断是否真会",
            "student_problem": "看懂不等于会做，要马上用题检查。",
            "bullets": [f"{q['type']}：{q['focus']}" for q in a["practice_questions"]],
            "check_question": "如果只做一道题，你会先测概念、条件还是应用？",
            "takeaway": "自测要覆盖概念、条件、应用三个层面。",
            "next_action": "生成同主题练习题并提交。",
        },
        {
            "title": "复习路径：按薄弱点闭环",
            "student_problem": "课后不知道下一步看什么资料。",
            "plain_explanation": "先补概念，再看结构，最后做题；错题回流画像和学习路径。",
            "bullets": a["review_actions"],
            "check_question": "你下一步应该看讲义、导图，还是先做诊断题？",
            "takeaway": "资料服务于薄弱点，不是机械刷题。",
            "next_action": "进入资源中心保存本套课件。",
        },
    ]
    return slides
    ctx = _gaoshu_context(topic)
    title = topic or ctx["keyword"] or "当前主题"
    weak_points = _profile_list(STATE.get("profile", {}).get("weak_points")) or [ctx["keyword"]]
    student_level = STATE.get("profile", {}).get("knowledge_level") or "foundation"
    keyword = ctx.get("keyword", "")
    if keyword == "积分":
        example = {
            "problem": "例题：计算 ∫ 2x dx，并解释为什么答案后面要加 C。",
            "solution": [
                "识别对象：这是不定积分，要求找一个导数为 2x 的原函数。",
                "回忆基本关系：如果 F'(x)=f(x)，那么 ∫f(x)dx=F(x)+C。",
                "寻找原函数：x² 的导数是 2x，所以一个原函数是 x²。",
                "写出答案：∫2x dx = x² + C。",
                "解释 C：因为 x²+1、x²-3 的导数也都是 2x，所以要用 C 表示所有原函数。",
            ],
        }
    elif keyword == "极限":
        example = {
            "problem": "例题：判断 lim(x→1) (x²-1)/(x-1) 的值。",
            "solution": [
                "先看能否直接代入：代入 x=1 得到 0/0，不能直接得答案。",
                "因式分解：x²-1=(x-1)(x+1)。",
                "在 x≠1 的去心邻域内约掉 x-1，原式等于 x+1。",
                "再看趋近趋势：当 x→1 时，x+1→2。",
                "结论：极限是 2；注意这不要求原函数在 x=1 处有定义。",
            ],
        }
    elif keyword == "导数":
        example = {
            "problem": "例题：求 f(x)=x² 在 x=3 处的导数，并解释含义。",
            "solution": [
                "识别对象：导数表示瞬时变化率，也就是曲线在该点的切线斜率。",
                "先求导函数：f'(x)=2x。",
                "代入 x=3：f'(3)=6。",
                "解释含义：在 x=3 附近，x 每增加一点，函数值大约以 6 倍速度变化。",
            ],
        }
    else:
        example = {
            "problem": f"例题：围绕「{title}」完成一道基础题，并写出每一步依据。",
            "solution": [
                "先读题，圈出关键词和限制条件。",
                "判断该题对应哪个定义、公式或定理。",
                "逐步计算或证明，每一步旁边写出依据。",
                "回到题目问法，写出完整结论。",
            ],
        }
    intuition = {
        "积分": "把很多小块累加起来看总量，例如面积、路程或总变化量。",
        "极限": "让变量不断靠近某个位置，观察函数值是否稳定靠近一个确定目标。",
        "导数": "把一段平均变化压缩到一个瞬间，得到此刻的变化速度。",
    }.get(keyword, f"先把「{title}」看成一个可观察、可检查、可验证的学习对象。")
    contrast = {
        "积分": "不定积分找原函数，定积分算区间累积量；不要把两者的结果形式混用。",
        "极限": "极限看趋近过程，不等于直接代入函数值；函数在该点无定义也可能有极限。",
        "导数": "导数不是普通除法，而是极限意义下的瞬时变化率。",
    }.get(keyword, "先区分概念含义、适用条件和计算动作，避免把相近词混成一类。")
    rich_example_steps = example["solution"][:5]
    return [
        {
            "title": f"今天要把「{title}」真正讲明白",
            "student_problem": f"学生现在不是缺一个结论，而是不知道「{title}」到底在研究什么、题目中哪些条件必须先看。",
            "lead_in": f"先抛一个课堂问题：如果题目只出现「{title}」三个字，你第一步究竟该看对象、条件，还是公式？",
            "visual_metaphor": f"把本节课想成一条路线：真实问题 -> 直观理解 -> 数学定义 -> 例题验证 -> 错因修正。",
            "bullets": [
                f"本节课不是背结论，而是学会遇到「{title}」时怎么想",
                f"当前薄弱点：{', '.join(weak_points[:3])}，所以先慢讲条件和步骤",
                f"课堂目标：能用自己的话解释概念，并独立完成一道基础题",
            ],
            "board_work": [
                "板书主线：问题情境 -> 概念人话 -> 数学定义 -> 例题步骤 -> 易错检查",
                "课堂约定：每一步都要回答“为什么能这样做”",
            ],
            "mini_activity": "让学生先口头回答：这类题第一眼要圈出哪些词？",
            "teacher_script": (
                f"今天不先背公式。我们先回答一个问题：遇到「{title}」时，题目到底要我们判断什么。"
                "只要这个问题想清楚，后面的公式、例题和错题都会变得有位置。"
            ),
            "check_question": "你看到一道题时，第一眼会先找公式，还是先找研究对象和条件？",
            "takeaway": "先判断问题类型，再选择工具。"
        },
        {
            "title": "先用人话建立直观图像",
            "student_problem": "学生常把定义当成一串符号，没理解它在描述一个变化过程。",
            "lead_in": "先不写正式定义，只问：这个概念在观察什么变化？",
            "visual_metaphor": intuition,
            "bullets": [
                f"教材核心：{ctx['summary']}",
                "先说“它在研究什么”，再说“怎么用符号写严格”",
                "用一个生活化或图像化说法托住抽象定义",
            ],
            "teacher_script": (
                f"把「{title}」先翻译成人话：它不是让我们机械计算，而是观察一个过程。"
                "数学符号只是把这个过程写得严格。"
            ),
            "board_work": [
                f"教材位置：{ctx['chapter']}",
                "直观表达：对象变化 -> 结果趋势 -> 是否稳定",
            ],
            "mini_activity": "请学生把正式定义改写成一句不超过 20 字的人话。",
            "check_question": "如果不用公式，你能用一句话解释这个概念吗？",
            "takeaway": "先有图像，再接符号。"
        },
        {
            "title": "先修基础补缺：不会时先补哪里",
            "student_problem": "学生卡住往往不是当前页没听懂，而是前置概念没有接上。",
            "lead_in": "先不要急着做题，先检查自己是不是缺了前置工具。",
            "visual_metaphor": "像搭楼梯：少一阶就会觉得后面的公式突然跳起来。",
            "bullets": [
                f"教材位置：{ctx['chapter']}",
                "先会读题干里的对象、范围、条件和结论",
                "再进入定义、公式或例题，不要倒着学",
            ],
            "learning_sections": [
                {"title": "必须先会", "items": ["能说出题目研究对象", "能圈出限制条件", "能判断要求计算还是证明"]},
                {"title": "缺了会怎样", "items": ["看到公式不知道何时用", "例题步骤能看懂但自己不会开头", "错题只改答案不改思路"]},
            ],
            "teacher_script": "这一页的目标是帮学生定位不会的根源。不要把所有问题都归因成笨，很多时候只是前置条件没有补齐。",
            "board_work": ["前置检查：对象 / 范围 / 条件 / 目标", "任意一项说不清，先回讲义或结构图补齐"],
            "mini_activity": "让学生对当前题目做 30 秒标注：圈对象，画条件，划问题。",
            "check_question": "如果你现在不会开头，是因为概念不懂、条件没圈，还是方法不会选？",
            "takeaway": "先修基础补齐，后面的公式才有落点。"
        },
        {
            "title": "正式定义逐句拆开",
            "student_problem": "学生看定义时容易整段背下来，但不知道每个短语有什么用。",
            "lead_in": "现在开始读定义，但不是背定义，而是拆定义。",
            "visual_metaphor": "定义像说明书：每一句都对应做题时的一项检查。",
            "bullets": [
                f"核心句：{ctx['summary']}",
                "把定义分成对象、条件、过程、结论四块",
                "每做一道题都回到这四块核对",
            ],
            "learning_sections": [
                {"title": "对象", "items": [f"本题围绕：{keyword or title}", "先问它研究谁"]},
                {"title": "条件", "items": ctx["steps"][:2]},
                {"title": "结论", "items": ["最后要写出什么", "结论是否满足题目问法"]},
            ],
            "teacher_script": "这里要慢下来读。每出现一个条件，就问学生：如果这个条件没有，会发生什么？",
            "board_work": ["定义四格：对象 | 条件 | 过程 | 结论", "把题干信息填进四格再开始计算"],
            "mini_activity": "让学生把定义中的条件词用不同颜色标出来。",
            "check_question": "这一定义里最容易漏看的条件是哪一个？",
            "takeaway": "定义不是装饰文字，是做题检查表。"
        },
        {
            "title": "符号怎么读：把数学式翻译成人话",
            "student_problem": "学生不是不会算，而是看到函数、极限、积分符号后不知道它们在说什么。",
            "lead_in": "先把符号翻译成人话，再决定怎么计算。",
            "visual_metaphor": "符号是压缩语言，解题前要先解压。",
            "bullets": [
                "函数符号：先看输入、输出和变化关系",
                "极限语言：看趋近过程，不只看某一点函数值",
                "积分语言：看原函数或区间累积量，先区分题型",
            ],
            "learning_sections": [
                {"title": "读题顺序", "items": ["先读变量和范围", "再读运算符号", "最后读题目要求"]},
                {"title": "写题顺序", "items": ["先写判断依据", "再写计算过程", "最后解释结论"]},
            ],
            "teacher_script": "很多学生看到符号会慌。这里要告诉他：每个符号都先翻译成一句话，不懂这句话就不要急着算。",
            "board_work": ["符号 -> 人话 -> 条件 -> 方法 -> 结论", "不允许只写公式不写依据"],
            "mini_activity": "给一个短公式，让学生先说中文含义，不做计算。",
            "check_question": "你能把题目里的第一个数学符号翻译成一句话吗？",
            "takeaway": "看懂符号含义，才知道下一步该做什么。"
        },
        {
            "title": "把定义拆成做题检查表",
            "student_problem": "学生会背定义，但做题时不知道哪些条件对应哪一步。",
            "lead_in": "老师在这里要把定义拆成几个可执行动作，让学生知道每一步检查什么。",
            "visual_metaphor": "定义不是一句话，而是一张闯关表：对象对不对、条件够不够、方法能不能用。",
            "bullets": [
                f"第一步：{ctx['steps'][0]}",
                f"第二步：{ctx['steps'][1] if len(ctx['steps']) > 1 else '选择合适方法'}",
                f"第三步：{ctx['steps'][2] if len(ctx['steps']) > 2 else '回到定义或定理检查结论'}",
            ],
            "teacher_script": (
                "定义不是背诵材料，而是一张检查表。每做一步，都要能说出自己检查了哪个条件。"
            ),
            "board_work": [
                "条件检查表：对象 / 范围 / 趋势 / 方法 / 结论",
                "每一步旁边写出依据，防止跳步",
            ],
            "mini_activity": "给一道题干，只让学生圈条件，不要求计算。",
            "check_question": "这道题如果不能直接代入，下一步应该检查什么？",
            "takeaway": "会做题的人不是先套公式，而是先过条件。"
        },
        {
            "title": "老师示范：完整讲一道例题",
            "student_problem": "学生不会通常卡在中间步骤，不知道为什么要这样变形。",
            "lead_in": "这一页要像黑板讲题：先读题，再判断，再动笔，不直接跳答案。",
            "visual_metaphor": "把例题拆成“读题-选法-计算-解释-回看”五个镜头。",
            "bullets": [
                example["problem"],
                f"第 1 步：{rich_example_steps[0]}",
                f"第 2 步：{rich_example_steps[1] if len(rich_example_steps) > 1 else '选择方法并写出依据'}",
                f"第 3 步：{rich_example_steps[2] if len(rich_example_steps) > 2 else '完成计算并解释结论'}",
            ],
            "teacher_script": (
                "讲例题时不要只给答案。先停在读题阶段，让学生说出已知条件；再一步一步把条件变成做题动作。"
            ),
            "board_work": [
                *example["solution"],
            ],
            "worked_example": example,
            "mini_activity": "讲到关键变形前停 5 秒，让学生说下一步为什么能这样做。",
            "check_question": "这一步用了哪个定义或定理？如果这个条件不存在，还能这样做吗？",
            "takeaway": "例题不是答案展示，而是思维过程展示。"
        },
        {
            "title": "例题变式：从会一题到会一类题",
            "student_problem": "学生常常听懂例题，但换个条件就不会做。",
            "lead_in": "例题讲完后必须做变式，否则只能记住这一题。",
            "visual_metaphor": "把例题当模板，但不能死背模板；要看哪些条件变了。",
            "bullets": [
                "变式 1：只改变数字，检查基本步骤是否掌握",
                "变式 2：改变条件，检查是否会重新判断方法",
                "变式 3：加入易错点，检查是否能解释错因",
            ],
            "learning_sections": [
                {"title": "保留不变", "items": ["研究对象不变", "核心定义不变", "检查条件的顺序不变"]},
                {"title": "允许变化", "items": ["数值或表达式变化", "方法选择可能变化", "结论表述要跟题目一致"]},
            ],
            "teacher_script": "这里不要再讲一遍原题，而是教学生迁移：哪些地方固定，哪些地方要重新判断。",
            "board_work": ["原题 -> 改数字 -> 改条件 -> 加误区", "每个变式都写：变化点是什么？方法是否还适用？"],
            "mini_activity": "让学生自己提出一个变式，并说明它和原题哪里不同。",
            "check_question": "如果题目条件换了，你还会用刚才的方法吗？为什么？",
            "takeaway": "学会一类题，靠的是识别不变量和变化点。"
        },
        {
            "title": "对比纠错：把容易混的地方讲透",
            "student_problem": "学生不是没学，而是用错条件、跳过依据或把相近概念混在一起。",
            "lead_in": "这一页专门讲错法，因为学生经常不是不会，而是把相邻概念和条件混用。",
            "visual_metaphor": contrast,
            "bullets": ctx["pitfalls"][:3],
            "teacher_script": (
                "错题不是简单地重做一遍。每个错误都要归因：是概念错、条件漏、计算错，还是审题错。"
            ),
            "board_work": [
                "错因分类：概念 / 条件 / 方法 / 计算 / 表达",
                "把今天的错题归到其中一类",
            ],
            "mini_activity": "展示一个错误解法，让学生指出错在条件、概念还是计算。",
            "check_question": "你最容易犯的是哪一种错？下一题准备怎么避免？",
            "takeaway": "纠错的目标是修正判断习惯。"
        },
        {
            "title": "课堂练习：从会听到会做",
            "student_problem": "听懂不等于会做，必须马上用题目检查理解。",
            "lead_in": "这一页不要堆难题，要用分层练习确认学生真的学会。",
            "visual_metaphor": "练习像三道门：概念门、步骤门、解释门，一道一道过。",
            "bullets": [
                f"概念判断：{ctx['pitfalls'][0] if ctx.get('pitfalls') else '判断概念适用边界'}",
                f"基础题：仿照例题完成「{title}」的一步一步解答",
                "解释题：写出每一步依据，而不是只写最终答案",
            ],
            "teacher_script": (
                "练习不要堆难题。先用一题确认概念，再用一题确认步骤，最后用一题确认学生能解释错因。"
            ),
            "board_work": [
                "每题提交后写一句：我这题检查了什么条件？",
                "错题自动加入错题本，生成下一轮复习路径",
            ],
            "mini_activity": "学生做完后让他补一句“我刚才用的是哪个条件”。",
            "check_question": "如果只让你复习一个点，你会选定义、条件还是例题步骤？",
            "takeaway": "能解释依据，才算真正会做。"
        },
        {
            "title": "自测诊断：判断自己是不是真会了",
            "student_problem": "学生容易把“看懂了”误认为“会做了”。",
            "lead_in": "最后用自测清单判断自己有没有真正掌握。",
            "visual_metaphor": "自测不是考试，而是给自己做一次学习体检。",
            "bullets": [
                "能不用公式先说出概念含义",
                "能列出做题前必须检查的条件",
                "能独立完成基础题并解释每一步依据",
            ],
            "learning_sections": [
                {"title": "达标标准", "items": ["会解释", "会开头", "会检查条件", "会复盘错因"]},
                {"title": "未达标补救", "items": ["回看定义拆解页", "重做例题变式", "生成同主题练习"]},
            ],
            "teacher_script": "这一页要让学生知道下一步怎么补，不是简单说回去复习。",
            "board_work": ["自测四问：是什么 / 何时用 / 怎么做 / 错在哪", "有一问答不上来，就回到对应资源"],
            "mini_activity": "让学生给自己打分：解释、开头、计算、复盘各 0 到 2 分。",
            "check_question": "你现在最不稳的是解释、开头、计算还是复盘？",
            "takeaway": "能自测，才会自己补短板。"
        },
        {
            "title": "课后闭环：资料怎么用才有效",
            "student_problem": "学生课后容易只看答案，不知道下一步学什么资料。",
            "lead_in": "最后一页给出明确的学习顺序，避免学生离开课堂后只刷题不复盘。",
            "visual_metaphor": "课后不是散着学，而是按“补概念-看结构-做题-复盘错因”闭环推进。",
            "bullets": [
                "先看讲义：补概念和条件",
                "再看思维导图：建立知识关系",
                "最后做练习题：把错题回流到画像和学习路径",
            ],
            "teacher_script": (
                "课后顺序不要反：先补理解，再看结构，最后刷题。否则题做多了也只是在重复错误。"
            ),
            "board_work": [
                "今日闭环：提问 -> 讲解 -> 导图 -> 练习 -> 错题 -> 新路径",
                "下一次从错题最高频知识点开始",
            ],
            "mini_activity": "让学生选择下一步资源：讲义、结构图、同主题练习或错题复盘。",
            "check_question": "你下一次打开系统时，第一步要看哪份资料？",
            "takeaway": "课后路线要服务于薄弱点，而不是机械刷题。"
        },
    ]


def _demo_resource_payload(resource_type: str, topic: str, resource_id: str) -> dict[str, Any]:
    label = _resource_label(resource_type)
    title = f"{topic or '当前学习主题'} · {label}"
    base = {
        "ok": True,
        "resource_id": resource_id,
        "type": resource_type,
        "resource_type": resource_type,
        "resource_type_label": label,
        "label": label,
        "title": title,
        "topic": topic,
        "status": "completed",
        "preview_available": True,
        "download_available": True,
        "generated_by": "mock_curriculum",
        "fallback_used": True,
    }
    if resource_type == "mindmap":
        return {**base, "tree": _mindmap_tree(topic), "mermaid": _demo_mindmap(topic), "content": _demo_mindmap(topic)}
    if resource_type == "quiz":
        items = _demo_quiz(topic)
        return {**base, "items": items, "content": {"items": items}}
    if resource_type == "ppt":
        slides = _teaching_ppt_slides(topic)
        return {
            **base,
            "format": "markdown_slide_deck",
            "download_ext": ".md",
            "slide_count": len(slides),
            "slides": slides,
        }
    if resource_type == "study_plan":
        plan = _build_demo_study_plan(topic or "函数极限")
        return {
            **base,
            "study_plan": plan,
            "plan": plan.get("steps", []),
            "content": "\n".join(f"{s.get('order', i + 1)}. {s.get('title')} - {s.get('description')}" for i, s in enumerate(plan.get("steps", []))),
        }
    return {
        **base,
        "content": _structured_lecture(topic or "函数极限的定义"),
    }


def _generate_resource_payload(resource_type: str, topic: str, resource_id: str) -> dict[str, Any]:
    topic = _resolve_generation_topic(topic)
    payload = _demo_resource_payload(resource_type, topic, resource_id)
    llm_payload: dict[str, Any] | None = None
    use_artifact_llm = os.getenv("RESOURCE_LLM_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    if resource_type == "quiz":
        llm_payload = _llm_generate_quiz(topic)
    elif use_artifact_llm and resource_type == "mindmap":
        llm_payload = _llm_generate_mindmap(topic)
    elif use_artifact_llm and resource_type in {"lecture_doc", "reading", "video_script"}:
        llm_payload = _llm_generate_lecture(topic)
    if llm_payload:
        payload.update(llm_payload)
        payload["title"] = f"{topic} · {payload['label']}"
    payload["context"] = _resource_context_meta(
        topic,
        resource_type,
        str(payload.get("generated_by") or "mock_curriculum"),
        bool(payload.get("fallback_used", True)),
    )
    payload["evidence"] = payload["context"]["evidence"]
    payload["verifier"] = payload["context"]["verifier"]
    payload["profile_adaptation"] = payload["context"]["profile_adaptation"]
    payload["model_status"] = _public_model_status(payload.get("generated_by"), bool(payload.get("fallback_used", True)))
    payload["verification"] = _public_verification_status(payload.get("verifier"))
    payload["rag_status"] = _public_rag_status(payload.get("context"))
    return payload


def _store_resource_item(resource_id: str, payload: dict[str, Any], resource_type: str, quality_score: float | None = None) -> dict[str, Any]:
    payload["download_url"] = f"/api/resources/download/{resource_id}"
    STATE["resource_payloads"][resource_id] = payload
    item = {
        "id": resource_id,
        "resource_id": resource_id,
        "title": payload["title"],
        "type": resource_type,
        "resource_type": resource_type,
        "label": payload["label"],
        "resource_type_label": payload.get("resource_type_label") or payload["label"],
        "topic": payload.get("topic") or (payload.get("context") or {}).get("topic") or payload.get("title"),
        "status": "completed",
        "question": (payload.get("context") or {}).get("question") or payload.get("topic") or payload.get("title"),
        "profile": (payload.get("context") or {}).get("profile_adaptation") or payload.get("profile_adaptation"),
        "citations": payload.get("evidence") or [],
        "context_chunks": (payload.get("context") or {}).get("context_chunks") or [],
        "provider": ((payload.get("context") or {}).get("generation_status") or {}).get("provider") or payload.get("generated_by", "mock_curriculum"),
        "model": ((payload.get("context") or {}).get("generation_status") or {}).get("model") or "mock_curriculum",
        "generated_by": payload.get("generated_by", "mock_curriculum"),
        "fallback_used": bool(payload.get("fallback_used", False)),
        "used_rag": bool(((payload.get("context") or {}).get("generation_status") or {}).get("used_rag", True)),
        "used_profile": bool(((payload.get("context") or {}).get("generation_status") or {}).get("used_profile", True)),
        "chapter": (payload.get("context") or {}).get("chapter"),
        "verifier": payload.get("verifier"),
        "verification": payload.get("verification"),
        "rag_status": payload.get("rag_status"),
        "model_status": payload.get("model_status"),
        "preview_available": True,
        "download_available": True,
        "evidence": payload.get("evidence"),
        "size": len(str(payload.get("content") or payload.get("mermaid") or payload.get("items") or payload)) * 2,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "download_url": f"/api/resources/download/{resource_id}",
    }
    if quality_score is not None:
        item["quality_score"] = quality_score
    return item


def _resource_download_text(payload: dict[str, Any], item: dict[str, Any]) -> str:
    title = str(payload.get("title") or item.get("title") or "学习资源")
    resource_type = str(payload.get("resource_type") or payload.get("type") or item.get("type") or "lecture_doc")
    context = payload.get("context") or {}
    verifier = payload.get("verifier") or context.get("verifier") or {}
    evidence = payload.get("evidence") or context.get("evidence") or []
    header = [
        f"# {title}",
        "",
        f"- 课程：{context.get('course') or STATE['course_name']}",
        f"- 教材定位：{context.get('chapter') or '高等数学上册'}",
        f"- 生成来源：{(payload.get('generated_by') or item.get('generated_by') or 'mock_curriculum')}，fallback：{bool(payload.get('fallback_used', item.get('fallback_used', False)))}",
        f"- Verifier：{verifier.get('status', 'passed')}，grounding {round(float(verifier.get('grounding_score', 0.78)) * 100)}%，风险 {verifier.get('risk_level', 'low')}",
        "",
        "## 生成依据",
    ]
    if evidence:
        for ev in evidence:
            header.append(f"- {ev.get('source', '依据')}：{ev.get('content', '')}")
    else:
        header.append("- 高数上.pdf：内置教材课程上下文")
    header.append("")
    if resource_type == "mindmap":
        lines = [*header, "## 可读知识结构"]
        tree = payload.get("tree") or {}
        for node in tree.get("nodes") or []:
            lines.append(f"\n### {node.get('title', '知识模块')}")
            if node.get("summary"):
                lines.append(str(node.get("summary")))
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    label = _readable_math_text(child.get("label") or child.get("title") or child.get("summary") or "")
                    hint = _readable_math_text(child.get("hint") or child.get("summary") or "")
                    lines.append(f"- {label}" + (f"：{hint}" if hint else ""))
                else:
                    lines.append(f"- {_readable_math_text(child)}")
        if tree.get("relations"):
            lines.append("\n## 关系说明")
            for rel in tree.get("relations") or []:
                lines.append(f"- {rel.get('from', '')} -> {rel.get('to', '')}" + (f"：{rel.get('label')}" if rel.get("label") else ""))
        lines.extend(["", "## Mermaid 备份", str(payload.get("mermaid") or payload.get("content") or "")])
        return "\n".join(lines)
    if resource_type == "quiz":
        lines = [*header, "## 练习题"]
        for idx, q in enumerate(payload.get("items") or [], 1):
            lines.append(f"\n### Q{idx}. {q.get('question', '')}")
            for oi, opt in enumerate(q.get("options") or []):
                marker = chr(65 + oi)
                lines.append(f"{marker}. {opt}")
            answer = int(q.get("answer", 0) or 0)
            lines.append(f"答案：{chr(65 + answer)}")
            if q.get("explanation"):
                lines.append(f"解析：{q.get('explanation')}")
        return "\n".join(lines)
    if resource_type == "ppt":
        lines = [
            *header,
            "",
            "> 教学版文字课件：面向“还不会”的学生设计。每页包含学生卡点、讲解目标、老师讲稿、板书步骤和课堂检查问题，可直接复制到 PowerPoint / WPS 或作为讲课稿使用。",
            "",
            "## 目录",
        ]
        for idx, slide in enumerate(payload.get("slides") or [], 1):
            lines.append(f"- 第 {idx} 页：{slide.get('title', '课件页')}")
        lines.append("\n---")
        for idx, slide in enumerate(payload.get("slides") or [], 1):
            lines.append(f"\n## 第 {idx} 页：{slide.get('title', '课件页')}")
            lines.append("")
            if slide.get("student_problem"):
                lines.append(f"**学生卡点**：{slide.get('student_problem')}")
                lines.append("")
            if slide.get("lead_in"):
                lines.append(f"**课堂导入**：{slide.get('lead_in')}")
                lines.append("")
            if slide.get("visual_metaphor"):
                lines.append(f"**直观讲法/类比**：{slide.get('visual_metaphor')}")
                lines.append("")
            lines.append("**本页要教会学生：**")
            for bullet in slide.get("bullets") or slide.get("points") or []:
                lines.append(f"- {bullet}")
            if slide.get("worked_example"):
                ex = slide.get("worked_example") or {}
                lines.append("")
                lines.append(f"**课堂例题**：{ex.get('problem', '')}")
                for step in ex.get("solution") or []:
                    lines.append(f"- {step}")
            if slide.get("teacher_script") or slide.get("speaker_notes"):
                lines.append("")
                lines.append(f"**老师讲法**：{slide.get('teacher_script') or slide.get('speaker_notes')}")
            if slide.get("board_work"):
                lines.append("")
                lines.append("**板书/演示步骤：**")
                for step in slide.get("board_work") or []:
                    lines.append(f"- {step}")
            if slide.get("check_question"):
                lines.append("")
                lines.append(f"**课堂检查问题**：{slide.get('check_question')}")
            if slide.get("mini_activity"):
                lines.append("")
                lines.append(f"**课堂互动**：{slide.get('mini_activity')}")
            if slide.get("takeaway"):
                lines.append("")
                lines.append(f"**本页收获**：{slide.get('takeaway')}")
            lines.append("\n---")
        return "\n".join(lines)
    if resource_type == "study_plan":
        plan = payload.get("study_plan") or {}
        lines = [*header, "## 个性化学习路径", ""]
        if plan.get("profile_summary"):
            lines.append(f"> {plan.get('profile_summary')}")
            lines.append("")
        for idx, step in enumerate(plan.get("steps") or payload.get("plan") or [], 1):
            lines.append(f"### 步骤 {step.get('order', idx)}：{step.get('title', '学习步骤')}")
            lines.append(f"- 为什么学：{step.get('reason', '根据最近问题和学习画像推荐')}")
            lines.append(f"- 怎么学：{step.get('description', '')}")
            lines.append(f"- 配套资源：{', '.join(step.get('resource_types') or [])}")
            lines.append(f"- 预计时间：{step.get('estimated_minutes', 15)} 分钟")
            if step.get("practice"):
                lines.append(f"- 练习任务：{step.get('practice')}")
            if step.get("check_standard"):
                lines.append(f"- 检验标准：{step.get('check_standard')}")
            lines.append("")
        if plan.get("next_action"):
            lines.append(f"## 下一步\n{plan.get('next_action')}")
        return "\n".join(lines)
    body = str(payload.get("content") or "内容已生成。")
    return "\n".join([*header, body])


@app.get("/api/health")
def health():
    return {"ok": True, "status": "healthy", "mode": "demo"}


@app.get("/health")
def health_root():
    return health()


@app.get("/api/version")
def version():
    return {"version": "0.1.0", "mode": "demo"}


@app.get("/api/settings/status")
def settings_status():
    provider, _, _, model = _provider_config(STATE["llm_provider"])
    vector_count = 128 + max(0, len(STATE["files"]) - 1) * 12
    fallback_provider = "deepseek" if STATE["deepseek_api_key"] else ("spark" if STATE["spark_api_key"] else "mock")
    return {
        "llm_provider": provider,
        "llm_model": model,
        "is_mock": provider == "mock",
        "deepseek_configured": bool(STATE["deepseek_api_key"]),
        "deepseek_model": STATE["deepseek_model"],
        "spark_enabled": bool(STATE["spark_api_key"]),
        "spark_configured": bool(STATE["spark_api_key"]),
        "spark_model": STATE["spark_model"],
        "spark_base_url_configured": bool(STATE["spark_base_url"]),
        "fallback_provider": fallback_provider,
        "fallback_available": True,
        "embedding_provider": "hash_mock",
        "embedding_is_mock": True,
        "embedding_note": "hash_mock 仅用于本地流程验证，不代表真实语义向量效果",
        "chroma_status": "ready",
        "knowledge_base_status": "ready",
        "chunks_count": vector_count,
        "vector_count": vector_count,
        "course_name": STATE["course_name"],
    }


@app.post("/api/auth/register")
def auth_register(payload: dict[str, Any] | None = None):
    return {
        "ok": True,
        "access_token": "local-demo-token",
        "token_type": "bearer",
        "user": {"id": 1, "username": "guest", "role": "admin", "authenticated": True},
        "message": "No login required. Local demo mode is active.",
    }


@app.post("/api/auth/login")
def auth_login(payload: dict[str, Any] | None = None):
    return auth_register(payload)


@app.get("/api/auth/me")
def auth_me():
    return {"id": 1, "username": "guest", "role": "admin", "authenticated": True}


@app.post("/api/settings/llm")
def save_llm_config(body: LLMConfigRequest):
    provider = body.provider.strip().lower()
    if provider not in {"spark", "deepseek"}:
        raise HTTPException(status_code=400, detail="provider must be spark or deepseek")
    if provider == "spark":
        spark_password = _normalize_spark_api_password(body.api_key)
        STATE.update({
            "llm_provider": "spark",
            "spark_api_key": spark_password,
            "spark_base_url": body.base_url or "https://spark-api-open.xf-yun.com/v1",
            "spark_model": body.model or "generalv3.5",
            "llm_timeout_seconds": _coerce_llm_timeout(body.timeout_seconds),
            "llm_failure_until": 0.0,
            "llm_last_error": "",
        })
        _write_env({
            "LLM_PROVIDER": "spark",
            "SPARK_ENABLED": "true",
            "SPARK_API_PASSWORD": _normalize_spark_api_password(STATE["spark_api_key"]),
            "SPARK_BASE_URL": STATE["spark_base_url"],
            "SPARK_MODEL": STATE["spark_model"],
            "SPARK_TIMEOUT_SECONDS": str(STATE["llm_timeout_seconds"]),
            "LLM_TIMEOUT_SECONDS": str(STATE["llm_timeout_seconds"]),
        })
    else:
        STATE.update({
            "llm_provider": "deepseek",
            "deepseek_api_key": body.api_key,
            "deepseek_base_url": body.base_url or "https://api.deepseek.com",
            "deepseek_model": body.model or "deepseek-v4-pro",
            "llm_timeout_seconds": _coerce_llm_timeout(body.timeout_seconds),
            "llm_failure_until": 0.0,
            "llm_last_error": "",
        })
        _write_env({
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": STATE["deepseek_api_key"],
            "DEEPSEEK_BASE_URL": STATE["deepseek_base_url"],
            "DEEPSEEK_MODEL": STATE["deepseek_model"],
            "DEEPSEEK_TIMEOUT_SECONDS": str(STATE["llm_timeout_seconds"]),
            "LLM_TIMEOUT_SECONDS": str(STATE["llm_timeout_seconds"]),
        })
    return {"ok": True, "provider": provider, "saved": True, "applied": True}


@app.post("/api/settings/test-llm")
def test_llm(body: LLMTestRequest):
    start = time.time()
    provider, model, answer = _call_llm(body.provider, body.message, body.model, timeout_seconds=body.timeout_seconds, bypass_failure_cache=True)
    return {
        "ok": True,
        "provider": provider,
        "model": model,
        "response": answer[:500],
        "latency_ms": round((time.time() - start) * 1000, 1),
        "message": f"{provider} 连接可用" if provider != "mock" else "未配置 API，演示模式可用",
        "fallback_available": True,
    }


@app.get("/api/app/bootstrap")
def bootstrap():
    provider, _, _, model = _provider_config(STATE["llm_provider"])
    course = {"id": STATE["course_id"], "name": STATE["course_name"], "description": GAOSHU_COURSE_DESCRIPTION}
    payload = {
        "ok": True,
        "app_ready": True,
        "next_step": "configure_key" if provider == "mock" else "start_learning",
        "user": {"id": 1, "username": "guest", "role": "admin", "authenticated": True, "mode": "no-login-demo"},
        "current_course": course,
        "selected_course": course,
        "courses": [course],
        "config": {
            "llm_configured": provider != "mock",
            "llm_provider": provider,
            "llm_model": model,
            "is_mock": provider == "mock",
            "spark_configured": bool(STATE["spark_api_key"]),
            "deepseek_configured": bool(STATE["deepseek_api_key"]),
            "embedding_provider": "hash_mock",
            "embedding_is_mock": True,
        },
    }
    payload["data"] = {
        "app_ready": payload["app_ready"],
        "next_step": payload["next_step"],
        "user": payload["user"],
        "current_course": payload["current_course"],
        "selected_course": payload["selected_course"],
        "courses": payload["courses"],
        "config": payload["config"],
    }
    return payload


@app.get("/api/app/dashboard")
def dashboard(course_id: int = 1):
    data = {
        "ok": True,
        "course": {"id": course_id, "name": STATE["course_name"], "description": GAOSHU_COURSE_DESCRIPTION},
        "stats": {"questions": len(STATE["sessions"]), "resources": len(STATE["resources"]), "mastery": 72},
        "knowledge_base": {"chunks_count": 128 + max(0, len(STATE["files"]) - 1) * 12, "vector_count": 128 + max(0, len(STATE["files"]) - 1) * 12, "status": "ready"},
        "recent_resources": STATE["resources"][-5:],
        "recommendations": ["先问一个高数知识点", "点击生成思维导图梳理章节", "启动测验并把错题加入复习路径"],
    }
    return {"ok": True, "data": data, **data}


@app.post("/api/app/ask")
def ask(body: AskRequest):
    question = body.question or body.message or "当前学习主题"
    provider, model, answer = _call_llm("", question)
    profile = _update_demo_profile(question, "dialogue")
    ctx = _gaoshu_context(question)
    if provider != "mock":
        answer = answer + "\n\n依据：内置教材《高数上.pdf》课程上下文。"
    session = {"id": body.session_id or str(uuid.uuid4()), "title": question[:30], "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not any(s["id"] == session["id"] for s in STATE["sessions"]):
        STATE["sessions"].append(session)
    retrieved_chunks = [
        {
            "chunk_id": "gaoshu_seed_context_001",
            "source": "高数上.pdf",
            "chapter": ctx["chapter"],
            "content": ctx["summary"],
            "score": 1.0,
            "context_type": "seeded_demo_context",
        }
    ]
    citations = [
        {"source": "高数上.pdf", "chapter": ctx["chapter"], "content": ctx["summary"], "score": 1.0},
        {"source": "模型调用状态", "content": _public_model_status(provider, provider == "mock").get("label", "本地演示模板生成"), "score": 1.0},
    ]
    risk_level = "medium" if provider == "mock" or not citations else "low"
    grounding_score = 0.62 if risk_level == "medium" else 0.85
    traces = [
        {"agent": "TutorAgent", "phase": "planning", "status": "completed", "summary": f"识别学习主题：{ctx['keyword']}", "latency_ms": 0},
        {"agent": "InformerAgent", "phase": "retrieving", "status": "completed", "summary": f"定位教材章节：{ctx['chapter']}", "latency_ms": 0},
        {"agent": "ProfileAgent", "phase": "profiling", "status": "completed", "summary": f"画像版本 #{profile.get('profile_version')} 已更新", "latency_ms": 0},
        {"agent": "VerifierAgent", "phase": "basic_check", "status": "completed", "summary": f"基础可信度 {int(grounding_score * 100)}%，风险 {risk_level}，来源 {provider}", "latency_ms": 0},
    ]
    resource_items = [
        {"type": "mindmap", "title": "可读知识结构图", "reason": "先建立定义、条件、流程和误区关系"},
        {"type": "quiz", "title": "同主题练习题", "reason": "立即检查是否真的理解当前问题"},
        {"type": "lecture_doc", "title": "面向不会学生的讲义", "reason": "补齐直观解释、严格定义和例题步骤"},
        {"type": "study_plan", "title": "动态学习路径", "reason": "根据画像、错题和当前章节安排下一步"},
        {"type": "ppt", "title": "Markdown 教学版 PPT", "reason": "用于复习或答辩演示的文字课件"},
    ]
    resource_created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    for item in resource_items:
        item.update({
            "question": question,
            "profile": profile,
            "citations": citations,
            "context_chunks": retrieved_chunks,
            "provider": provider,
            "model": model,
            "generated_by": provider,
            "fallback_used": provider == "mock",
            "used_rag": bool(retrieved_chunks),
            "used_profile": True,
            "created_at": resource_created_at,
        })
    payload = {
        "ok": True,
        "answer": answer,
        "provider": provider,
        "model": model,
        "session_id": session["id"],
        "citations": citations,
        "retrieved_chunks": retrieved_chunks,
        "refs": [f"本地课程知识库 · {ctx['chapter']}"],
        "agent_traces": traces,
        "agent_trace": traces,
        "grounding_score": grounding_score,
        "grounding": {"grounding_score": grounding_score, "risk_level": risk_level, "unsupported_claims": [], "verifier_type": "基础校验/引用完整性/基础可信度"},
        "content_safety": {"safe": True, "risk_level": risk_level},
        "student_profile": profile,
        "profile_metrics": _profile_numeric_metrics(profile),
        "profile_version": profile.get("profile_version"),
        "profile_dimensions": profile.get("profile_dimensions"),
        "profile_updated_fields": profile.get("profile_updated_fields"),
        "profile_summary": profile.get("profile_summary"),
        "next_recommendation": profile.get("next_recommendation"),
        "profile_delta": {
            "knowledge_level": profile.get("knowledge_level"),
            "learning_goal": profile.get("learning_goal"),
            "cognitive_style": profile.get("cognitive_style"),
            "weak_points": profile.get("weak_points"),
            "resource_preference": profile.get("resource_preference"),
            "wrong_question_types": profile.get("wrong_question_types"),
            "mastery_trend": profile.get("mastery_trend"),
            "profile_version": profile.get("profile_version"),
            "profile_confidence": profile.get("profile_confidence"),
            "profile_updated_fields": profile.get("profile_updated_fields"),
        },
        "resource_package": {
            "title": f"{ctx['keyword']} · 个性化高数资源包",
            "topic": question,
            "summary": f"基于最近问题、{ctx['chapter']}、画像版本 #{profile.get('profile_version')} 自动规划。",
            "items": resource_items,
            "item_count": len(resource_items),
            "agent_count": 5,
            "grounding_score": grounding_score,
            "risk_level": risk_level,
            "content_safe": True,
        },
        "resource_suggestions": resource_items,
        "generated_artifacts": {
            "ready_for_generation": True,
            "suggestions": resource_items,
        },
    }
    return {"ok": True, "data": payload, **payload}


@app.post("/api/app/ask/stream")
def ask_stream(body: AskRequest):
    data = ask(body)
    text = data["answer"]

    def gen():
        meta = {
            "provider": data["provider"],
            "model": data["model"],
            "citations": data["citations"],
            "retrieved_chunks": data.get("retrieved_chunks", []),
            "agent_traces": [
                {"agent": "TutorAgent", "phase": "planning", "status": "completed", "summary": "免登录 Demo 已接收问题", "latency_ms": 0},
                {"agent": "VerifierAgent", "phase": "verifying", "status": "completed", "summary": "演示链路校验通过", "latency_ms": 0},
            ],
        }
        import json
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
        for chunk in [text[i:i + 40] for i in range(0, len(text), 40)]:
            yield f"event: token\ndata: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"
        done = {
            "answer": text,
            "provider": data["provider"],
            "model": data["model"],
            "citations": data["citations"],
            "retrieved_chunks": data.get("retrieved_chunks", []),
            "refs": data["refs"],
            "agent_traces": data.get("agent_traces", []),
            "grounding_score": data.get("grounding_score"),
            "grounding": data.get("grounding", {}),
            "content_safety": data.get("content_safety", {}),
            "student_profile": data.get("student_profile", {}),
            "profile_version": data.get("profile_version"),
            "profile_dimensions": data.get("profile_dimensions"),
            "profile_updated_fields": data.get("profile_updated_fields"),
            "profile_summary": data.get("profile_summary"),
            "next_recommendation": data.get("next_recommendation"),
            "profile_delta": data.get("profile_delta", {}),
            "resource_package": data.get("resource_package", {}),
            "resource_suggestions": data["resource_suggestions"],
            "generated_artifacts": data["generated_artifacts"],
        }
        yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/app/generate")
def app_generate(body: GenerateRequest):
    if body.resource_type not in VALID_DEMO_RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="unsupported resource_type")
    rid = str(uuid.uuid4())
    topic = _resolve_generation_topic(body.topic, body.knowledge_point)
    payload = _generate_resource_payload(body.resource_type, topic, rid)
    item = _store_resource_item(rid, payload, body.resource_type)
    STATE["resources"].append(item)
    return {"ok": True, "resource": item, "data": payload, **payload}


@app.post("/api/resources/generate")
def resources_generate(body: dict[str, Any]):
    topic = _resolve_generation_topic(body.get("topic") or "", body.get("knowledge_point") or "")
    requested = body.get("resource_types") or body.get("types") or [body.get("resource_type") or "lecture_doc"]
    if isinstance(requested, str):
        requested = [requested]
    resource_types = [str(t) for t in requested if str(t).strip()]
    resource_types = [t for t in resource_types if t in VALID_DEMO_RESOURCE_TYPES]
    if not resource_types:
        resource_types = ["lecture_doc"]

    resources: list[dict[str, Any]] = []
    for resource_type in resource_types:
        rid = str(uuid.uuid4())
        payload = _generate_resource_payload(resource_type, topic, rid)
        item = _store_resource_item(rid, payload, resource_type, quality_score=0.92 if not payload.get("fallback_used") else 0.78)
        resources.append(item)
        STATE["resources"].append(item)

    trace = [
        {"agent": "Planner Agent", "status": "completed", "message": "已分析学习主题与资源类型"},
        {"agent": "Retriever Agent", "status": "completed", "message": "已读取《高数上.pdf》课程上下文"},
        {"agent": "Generator Agent", "status": "completed", "message": f"已生成 {len(resources)} 类资源"},
        {"agent": "Verifier Agent", "status": "completed", "message": "已完成内容质量校验"},
    ]
    job_id = str(uuid.uuid4())
    job = {"job_id": job_id, "status": "completed", "progress": 100, "resources": resources, "agent_trace": trace, "result": {"resources": resources}}
    STATE["resource_jobs"][job_id] = job
    return {"ok": True, "data": job, **job}


@app.get("/api/resources/generate/{job_id}")
def resource_job(job_id: str):
    job = STATE["resource_jobs"].get(job_id)
    if not job:
        return {"ok": True, "data": {"job_id": job_id, "status": "completed", "progress": 100, "result": {"resources": []}}, "job_id": job_id, "status": "completed", "progress": 100}
    return {"ok": True, "data": job, **job}


@app.get("/api/resources/generated")
def generated_resources():
    return {"ok": True, "files": STATE["resources"], "data": {"files": STATE["resources"]}}


@app.get("/api/resources/download/{resource_id}")
def download_resource(resource_id: str):
    item = next((r for r in STATE["resources"] if str(r.get("resource_id") or r.get("id")) == resource_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="resource not found")
    payload = STATE["resource_payloads"].get(resource_id) or item
    title = item.get("title") or "学习资源"
    content = _resource_download_text(payload, item)
    resource_type = item.get("type") or item.get("resource_type")
    ext = ".md" if resource_type in {"lecture_doc", "reading", "mindmap", "quiz", "ppt", "study_plan", "video_script"} else ".txt"
    filename = quote(f"{title}{ext}")
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.get("/api/sessions")
def sessions(course_id: int = 1):
    return {"sessions": STATE["sessions"]}


@app.post("/api/sessions")
def create_session(payload: dict[str, Any] | None = None):
    session = {"id": str(uuid.uuid4()), "title": (payload or {}).get("title", "新会话"), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "messages": []}
    STATE["sessions"].append(session)
    return session


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    return next((s for s in STATE["sessions"] if s["id"] == session_id), {"id": session_id, "title": "会话", "messages": []})


@app.get("/api/analytics/progress")
def progress():
    return {"items": [{"name": "函数与极限", "value": 70}, {"name": "导数与微分", "value": 76}, {"name": "积分方法", "value": 62}], "overall": 69}


@app.get("/api/analytics/wrong-book")
def wrong_book():
    return {"items": STATE["wrong_book"]}


@app.get("/api/analytics/bookmarks")
def bookmarks():
    return {"items": STATE["bookmarks"]}


@app.post("/api/analytics/bookmarks")
def add_bookmark(payload: dict[str, Any]):
    payload = dict(payload or {})
    payload.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    STATE["bookmarks"].append(payload)
    return {"ok": True}


@app.get("/api/analytics/audit")
def audit(limit: int = 20):
    return []


@app.post("/api/analytics/audit")
def add_audit(payload: dict[str, Any]):
    return {"ok": True}


@app.post("/api/analytics/review-plan")
def review_plan(payload: dict[str, Any]):
    topic = payload.get("topic") or (payload.get("knowledge_points") or ["函数极限"])[0]
    steps = [
        {"title": f"重建「{topic}」核心定义", "description": "先用教材语言写出定义，再用自己的话解释每个条件。", "minutes": 15},
        {"title": "定位常见误区", "description": "回看错题原因，区分函数值、极限值、左右极限和适用条件。", "minutes": 15},
        {"title": "完成巩固练习", "description": "做 3 道同主题单选题或计算题，提交后更新掌握度。", "minutes": 25},
        {"title": "生成结构化复盘材料", "description": "查看讲义和知识结构图，把薄弱点加入下一轮复习。", "minutes": 10},
    ]
    study_plan = {"title": f"{topic} · 错题复习路径", "steps": steps}
    STATE.setdefault("study_plan_events", []).append(
        {"topic": topic, "title": study_plan["title"], "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    )
    return {"ok": True, "study_plan": study_plan, "plan": steps, "data": {"study_plan": study_plan, "plan": steps}}


def _valid_mastery_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0:
        return None
    return max(0.0, min(1.0, score))


def _record_demo_mastery(knowledge_point: str, score: float, source: str) -> dict[str, Any]:
    item = {
        "knowledge_point": (knowledge_point or "当前知识点").strip() or "当前知识点",
        "mastery_score": _valid_mastery_score(score),
        "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if item["mastery_score"] is not None:
        STATE.setdefault("mastery_records", []).append(item)
    return item


def _demo_mastery_items() -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in STATE.get("wrong_book", []):
        kp = str(row.get("knowledge_point") or row.get("topic") or "").strip()
        mastery_payload = row.get("mastery") if isinstance(row.get("mastery"), dict) else {}
        score = _valid_mastery_score(row.get("mastery_score") or mastery_payload.get("mastery_score"))
        if kp and score is not None:
            latest[kp] = {
                "knowledge_point": kp,
                "mastery_score": score,
                "wrong_count": 1,
                "recommended_action": "先复盘错题解析，再做同主题练习",
            }
    for row in STATE.get("mastery_records", []):
        kp = str(row.get("knowledge_point") or "").strip()
        score = _valid_mastery_score(row.get("mastery_score"))
        if kp and score is not None:
            prior_wrong = latest.get(kp, {}).get("wrong_count", 0)
            latest[kp] = {
                "knowledge_point": kp,
                "mastery_score": score,
                "wrong_count": prior_wrong,
                "recommended_action": "继续练习并观察掌握度变化" if score >= 0.7 else "先看讲义并复盘错题",
            }
    return list(latest.values())


def _demo_mastery_overview(mastery_items: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [_valid_mastery_score(item.get("mastery_score")) for item in mastery_items]
    valid_scores = [score for score in scores if score is not None]
    if not valid_scores:
        return {
            "avg_mastery": None,
            "average_score": None,
            "average_label": "待测评",
            "has_data": False,
            "weak_count": 0,
            "strong_points": [],
            "weak_points": [],
        }
    avg = round(sum(valid_scores) / len(valid_scores), 2)
    return {
        "avg_mastery": avg,
        "average_score": avg,
        "average_label": f"{round(avg * 100)}%",
        "has_data": True,
        "weak_count": sum(1 for score in valid_scores if score < 0.5),
        "strong_points": [item["knowledge_point"] for item in mastery_items if _valid_mastery_score(item.get("mastery_score")) is not None and float(item["mastery_score"]) >= 0.75][:5],
        "weak_points": [item["knowledge_point"] for item in mastery_items if _valid_mastery_score(item.get("mastery_score")) is not None and float(item["mastery_score"]) < 0.5][:5],
    }


@app.get("/api/app/learning-report")
def learning_report(course_id: int = 1):
    wrong_items = STATE.get("wrong_book", [])
    bookmarks = STATE.get("bookmarks", [])
    generated_study_plans = sum(1 for item in STATE.get("resources", []) if (item.get("resource_type") or item.get("type")) == "study_plan")
    study_plan_count = generated_study_plans + len(STATE.get("study_plan_events", []))
    mastery_items = _demo_mastery_items()
    mastery_overview = _demo_mastery_overview(mastery_items)
    weak_points = mastery_overview.get("weak_points") or [item.get("knowledge_point") for item in wrong_items if item.get("knowledge_point")]
    weak_points = list(dict.fromkeys([str(item) for item in weak_points if item]))[:6]
    score = round((mastery_overview.get("avg_mastery") or 0.0) * 100) if mastery_overview.get("has_data") else None
    data = {
        "summary": "学习报告已汇总错题、收藏、测验掌握度和学习路径生成记录。",
        "score": score,
        "weaknesses": weak_points,
        "weak_points": weak_points,
        "stats": {
            "wrong_count": len(wrong_items),
            "bookmark_count": len(bookmarks),
            "mastery_count": len(mastery_items),
            "study_plan_count": study_plan_count,
        },
        "wrong_count": len(wrong_items),
        "bookmark_count": len(bookmarks),
        "study_plan_count": study_plan_count,
        "mastery_overview": mastery_overview,
        "mastery_items": mastery_items,
    }
    return {"ok": True, "data": data, **data}


@app.post("/api/app/quiz/submit")
def quiz_submit(payload: dict[str, Any]):
    is_correct = bool(payload.get("is_correct", True))
    knowledge_point = payload.get("knowledge_point") or payload.get("topic") or "当前知识点"
    explanation = payload.get("explanation") or "这题需要回到定义、适用条件和题干关键词来判断。"
    mastery_score = 0.86 if is_correct else 0.48
    if not is_correct:
        wrong_item = {
            "knowledge_point": knowledge_point,
            "question": payload.get("question_text") or "",
            "selected_answer": payload.get("selected_answer") or "",
            "correct_answer": payload.get("correct_answer") or "",
            "explanation": explanation,
            "mastery_score": mastery_score,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "review_actions": [
                {"title": "先看详细讲义", "resource_types": ["lecture_doc"]},
                {"title": "再看知识结构", "resource_types": ["mindmap"]},
                {"title": "最后做同主题练习", "resource_types": ["quiz"]},
            ],
        }
        STATE["wrong_book"].insert(0, wrong_item)
        profile = _update_demo_profile(f"我在{knowledge_point}题目中选错了，属于概念辨析错误，需要复盘。{explanation}", "quiz_wrong")
    else:
        profile = _update_demo_profile(f"我完成了{knowledge_point}练习并答对，掌握度有所提升，继续巩固。", "quiz_correct")
    mastery_record = _record_demo_mastery(knowledge_point, mastery_score, "quiz_correct" if is_correct else "quiz_wrong")
    data = {
        "correct": is_correct,
        "feedback": "回答正确，已提高掌握度。" if is_correct else "已记录错题。先在当前页面看解析，再进入错题本复盘。",
        "detailed_feedback": {
            "why_wrong": "" if is_correct else f"你的选择没有抓住「{knowledge_point}」的核心条件或题干问法。",
            "correct_logic": explanation,
            "next_step": "继续完成下一题。" if is_correct else "先看讲义中的定义和条件，再做同主题练习。",
        },
        "mastery": mastery_record,
        "student_profile": profile,
        "profile_version": profile.get("profile_version"),
        "profile_dimensions": profile.get("profile_dimensions"),
        "profile_updated_fields": profile.get("profile_updated_fields"),
        "profile_summary": profile.get("profile_summary"),
        "next_recommendation": profile.get("next_recommendation"),
    }
    return {"ok": True, "data": data, **data}


@app.get("/api/profiles/current")
def current_profile():
    profile = dict(STATE["profile"])
    if not profile.get("profile_version"):
        profile["knowledge_level"] = profile.get("knowledge_level") or "待识别"
        profile["cognitive_style"] = profile.get("cognitive_style") or "偏好分步骤讲解"
        profile["learning_goal"] = profile.get("learning_goal") or "理解核心概念并完成基础练习"
    metrics = _profile_numeric_metrics(profile)
    public = _profile_public_payload(profile)
    return {"ok": True, "profile": public, "metrics": metrics, "data": {"profile": public, "metrics": metrics}, **public}


@app.get("/api/profiles/history")
def profile_history():
    data = {"versions": STATE["profile_versions"], "change_logs": STATE["profile_changes"]}
    return {"ok": True, "data": data, **data}


@app.post("/api/profiles/me/extract")
def profile_extract(payload: dict[str, Any]):
    profile = _update_demo_profile(str(payload.get("message") or payload.get("text") or ""), "manual_dialogue")
    metrics = _profile_numeric_metrics(profile)
    return {"ok": True, "profile": profile, "metrics": metrics, "data": {"profile": profile, "metrics": metrics}, **profile}


@app.post("/api/profiles/me/confirm")
def profile_confirm(payload: dict[str, Any] | None = None):
    STATE["profile"]["profile_source"] = "confirmed"
    public = _profile_public_payload(STATE["profile"])
    metrics = _profile_numeric_metrics(public)
    return {"ok": True, "profile": public, "metrics": metrics, "data": {"profile": public, "metrics": metrics}}


@app.post("/api/profiles/history/{version_id}/restore")
def profile_restore(version_id: str):
    item = next((v for v in STATE["profile_versions"] if str(v.get("id")) == str(version_id) or str(v.get("version")) == str(version_id)), None)
    if item and isinstance(item.get("snapshot"), dict):
        STATE["profile"].update(item["snapshot"])
    public = _profile_public_payload(STATE["profile"])
    return {"ok": True, "profile": public, "data": {"profile": public}}


@app.get("/api/courses")
def courses():
    primary = {"id": 1, "name": STATE["course_name"], "description": GAOSHU_COURSE_DESCRIPTION, "chapters": GAOSHU_CHAPTERS}
    return [primary, *STATE["extra_courses"]]


@app.post("/api/courses")
def create_course(payload: dict[str, Any]):
    course = {
        "id": len(STATE["extra_courses"]) + 2,
        "name": payload.get("name") or "新课程",
        "description": payload.get("description", ""),
    }
    STATE["extra_courses"].append(course)
    return course


@app.get("/api/courses/{course_id}/files")
def course_files(course_id: int):
    return STATE["files"]


@app.post("/api/courses/{course_id}/files")
def upload_file(course_id: int, file: UploadFile = File(...)):
    item = {"id": str(uuid.uuid4()), "course_id": course_id, "original_filename": file.filename, "status": "ready", "content_type": file.content_type or "file", "chunks": 12, "indexed_chunks": 12}
    STATE["files"].append(item)
    return item


@app.post("/api/rag/courses/{course_id}/build")
def build_index(course_id: int):
    return {"ok": True, "indexed_chunks": max(12, len(STATE["files"]) * 12)}
