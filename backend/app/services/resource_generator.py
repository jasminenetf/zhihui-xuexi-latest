"""Resource generator: RAG retrieval → structured JSON → resource pack.

Unified pipeline for mindmap, lecture_doc, and quiz generation.
Reuses existing rag_service and llm_provider.
Mock mode generates deterministic structured resources from chunks.
"""

import json
import logging
import re
from typing import Any, Optional

from sqlmodel import Session

from app.models.course import Course
from app.models.user import User
from app.schemas.resource import (
    Citation,
    LectureDocJSON,
    LectureSection,
    MindMapJSON,
    MindMapNode,
    QuizItem,
    QuizJSON,
    ResourceItem,
    ResourcePackResponse,
    ResourceType,
)
from app.services.llm_provider import get_llm_provider
from app.services.rag_service import search_course
from app.services.resource_renderer import (
    render_lecture_to_markdown,
    render_mindmap_to_mermaid,
    render_quiz,
)

logger = logging.getLogger(__name__)

MAX_RESOURCE_TOP_K = 8


def _analysis_for_topic(topic: str, profile: dict | None = None) -> dict[str, Any]:
    text = str(topic or "")
    if "连续" in text:
        key = "连续"
    elif "微积分" in text:
        key = "微积分"
    elif "定积分" in text or "积分" in text:
        key = "积分"
    elif "导数" in text or "微分" in text:
        key = "导数"
    elif "极限" in text:
        key = "极限"
    else:
        key = "微积分"
    data = {
        "极限": {
            "label": "函数极限", "chapter": "第一章 函数与极限",
            "intuition": "极限看自变量趋近过程中的函数值趋势，不等于某一点函数值。",
            "definition": "x 趋近 x0 时 f(x) 任意接近 A，则 A 是极限。",
            "conditions": ["判断趋近方向", "比较左右极限", "0/0 型先化简"],
            "steps": ["代入判断未定式", "化简表达式", "看左右趋势", "写结论"],
            "mistakes": ["函数值等于极限", "忽略左右极限", "把 0/0 当答案"],
            "example": "求 lim(x->1)(x^2-1)/(x-1)",
            "solution": ["代入得 0/0", "分解 x^2-1", "约去 x-1", "得到极限 2"],
        },
        "导数": {
            "label": "导数定义", "chapter": "第二章 导数与微分",
            "intuition": "导数是割线逼近切线后的瞬时变化率。",
            "definition": "f'(x0)=lim(Δx->0)[f(x0+Δx)-f(x0)]/Δx。",
            "conditions": ["写出差商", "让 Δx 趋近 0", "差商极限存在"],
            "steps": ["建立平均变化率", "化简差商", "取极限", "解释切线斜率"],
            "mistakes": ["忘记取极限", "把导数当普通除法", "混淆可导与连续"],
            "example": "用定义求 f(x)=x^2 在 x=3 处导数",
            "solution": ["写差商", "展开化简", "取 Δx->0", "得到 6"],
        },
        "积分": {
            "label": "定积分的几何意义", "chapter": "第四、五章 不定积分与定积分",
            "intuition": "定积分把区间切成小段，把小矩形面积累加后取极限。",
            "definition": "定积分是分割、取样、求和、取极限的区间累积量。",
            "conditions": ["区分定积分和不定积分", "看清上下限", "解释面积或累积意义"],
            "steps": ["确定累积对象", "画区间图像", "选择公式", "代入上下限"],
            "mistakes": ["定积分写 +C", "漏看上下限", "换元后上下限不同步"],
            "example": "解释并计算 ∫_0^2 x dx",
            "solution": ["画 y=x", "识别三角形面积", "1/2*2*2", "结果为 2"],
        },
        "连续": {
            "label": "函数连续", "chapter": "第一章 函数与极限",
            "intuition": "连续要求点上的函数值和靠近该点的趋势对得上。",
            "definition": "f(x0) 有定义、极限存在且等于 f(x0)，则连续。",
            "conditions": ["函数值存在", "极限存在", "二者相等"],
            "steps": ["算函数值", "算左右极限", "比较三者", "判断间断点"],
            "mistakes": ["只看函数值", "不比较极限与函数值", "混淆连续和可导"],
            "example": "判断 f(x)=x^2 在 x=1 处连续",
            "solution": ["f(1)=1", "极限为 1", "二者相等", "连续"],
        },
        "微积分": {
            "label": "微积分整体理解", "chapter": "第一至第五章 微积分核心工具",
            "intuition": "微分研究局部变化，积分研究整体累积。",
            "definition": "导数刻画局部变化率，积分刻画区间总量，二者由基本公式联系。",
            "conditions": ["判断局部还是整体", "选择导数或积分", "解释实际含义"],
            "steps": ["识别对象", "判断变化或累积", "选择工具", "解释结果"],
            "mistakes": ["割裂导数和积分", "只背公式", "不问研究对象"],
            "example": "速度函数如何解释加速度和路程",
            "solution": ["速度导数是加速度", "速度积分是路程", "局部与整体联系", "形成建模工具"],
        },
    }[key]
    weak = (profile or {}).get("weak_points") or "待识别"
    data["profile_hint"] = f"画像薄弱点：{weak}"
    return data

# ── Topic-specific Mock templates ──────────────────────────────────────────────

# Known topic patterns → mock resource templates
_MOCK_TOPICS = {
    "导数": {
        "mindmap": MindMapJSON(
            title="导数",
            nodes=[
                MindMapNode(id="def", label="导数定义", children=[
                    MindMapNode(id="rate", label="瞬时变化率"),
                    MindMapNode(id="limit", label="差商极限"),
                ]),
                MindMapNode(id="geo", label="几何意义", children=[
                    MindMapNode(id="tangent", label="切线斜率"),
                    MindMapNode(id="monotonic", label="单调性判断"),
                ]),
                MindMapNode(id="rules", label="求导法则", children=[
                    MindMapNode(id="basic", label="基本初等函数"),
                    MindMapNode(id="chain", label="链式法则"),
                    MindMapNode(id="product", label="积商法则"),
                ]),
                MindMapNode(id="app", label="应用", children=[
                    MindMapNode(id="extreme", label="极值与最值"),
                    MindMapNode(id="shape", label="函数图像分析"),
                ]),
            ],
        ),
        "lecture": LectureDocJSON(
            title="导数入门讲解",
            difficulty="beginner",
            sections=[
                LectureSection(
                    heading="什么是导数",
                    content=(
                        "导数是微积分学中最核心的概念之一，用于描述函数在某一点处的瞬时变化率。"
                        "从直观上说，导数就是曲线在一点的切线斜率，它告诉我们函数在该点的变化趋势。"
                        "导数本质上来源于差商的极限：当自变量的增量趋近于零时，函数值的增量与自变量的增量之比的极限。"
                    ),
                ),
                LectureSection(
                    heading="导数的几何意义",
                    content=(
                        "在几何上，函数 y=f(x) 在点 x0 处的导数 f'(x0) 等于曲线在该点处切线的斜率。"
                        "切线是割线在两点无限趋近时的极限位置。导数的正负可以判断函数的单调性："
                        "导数为正表示函数在该点附近递增，导数为负表示函数递减。"
                    ),
                ),
                LectureSection(
                    heading="常见求导法则",
                    content=(
                        "1. 常数求导：(C)' = 0\n"
                        "2. 幂函数求导：(xⁿ)' = n·xⁿ⁻¹\n"
                        "3. 指数函数求导：(eˣ)' = eˣ\n"
                        "4. 对数函数求导：(ln x)' = 1/x\n"
                        "5. 和差法则：(u±v)' = u' ± v'\n"
                        "6. 积法则：(uv)' = u'v + uv'\n"
                        "7. 商法则：(u/v)' = (u'v - uv')/v²\n"
                        "8. 链式法则：(f(g(x)))' = f'(g(x))·g'(x)"
                    ),
                ),
                LectureSection(
                    heading="学习建议",
                    content=(
                        "建议初学者先从导数的直观理解入手，通过画切线来感受导数的几何意义。"
                        "然后通过大量练习掌握基本求导公式和法则。不建议死记硬背，而是理解每个法则的来源。"
                        "最后通过极值问题和函数作图来巩固对导数的整体理解。"
                    ),
                ),
            ],
        ),
        "quiz": QuizJSON(
            title="导数概念自测",
            items=[
                QuizItem(
                    question="导数本质上来源于什么？",
                    options=["积分", "差商的极限", "微分方程", "泰勒展开"],
                    answer=1,
                    explanation="导数定义为函数增量与自变量增量之比的极限，即差商的极限。",
                ),
                QuizItem(
                    question="导数在几何上表示什么？",
                    options=["曲线与 x 轴围成的面积", "曲线在某点的切线斜率", "函数的最大值", "函数的平均值"],
                    answer=1,
                    explanation="导数的几何意义就是曲线在对应点处的切线斜率。",
                ),
                QuizItem(
                    question="(x³)' 等于多少？",
                    options=["3x³", "3x²", "x²", "3x"],
                    answer=1,
                    explanation="根据幂函数求导法则：(xⁿ)' = n·xⁿ⁻¹，所以 (x³)' = 3x²。",
                ),
                QuizItem(
                    question="下列哪个是链式法则的正确表达式？",
                    options=[
                        "(uv)' = u'v + uv'",
                        "(u/v)' = (u'v - uv')/v²",
                        "(f(g(x)))' = f'(g(x))·g'(x)",
                        "(C)' = 0",
                    ],
                    answer=2,
                    explanation="(f(g(x)))' = f'(g(x))·g'(x) 就是链式法则，用于复合函数求导。",
                ),
            ],
        ),
    },
    "极限": {
        "mindmap": MindMapJSON(
            title="极限",
            nodes=[
                MindMapNode(id="def", label="极限定义", children=[
                    MindMapNode(id="eps_delta", label="ε-δ 语言"),
                    MindMapNode(id="intuitive", label="直观理解"),
                ]),
                MindMapNode(id="prop", label="极限性质", children=[
                    MindMapNode(id="unique", label="唯一性"),
                    MindMapNode(id="bounded", label="有界性"),
                    MindMapNode(id="preserve", label="保号性"),
                ]),
                MindMapNode(id="ops", label="极限运算法则", children=[
                    MindMapNode(id="four_op", label="四则运算法则"),
                    MindMapNode(id="squeeze", label="夹逼准则"),
                    MindMapNode(id="monotone", label="单调有界准则"),
                ]),
                MindMapNode(id="important", label="重要极限", children=[
                    MindMapNode(id="sin", label="sin x / x → 1"),
                    MindMapNode(id="e", label="(1+1/x)ˣ → e"),
                ]),
            ],
        ),
        "lecture": LectureDocJSON(
            title="极限入门讲解",
            difficulty="beginner",
            sections=[
                LectureSection(
                    heading="什么是极限",
                    content=(
                        "极限是微积分学的基础概念，描述当自变量无限趋近某个值时函数值的变化趋势。"
                        "直观理解：当 x 越来越接近 x0（但不等于 x0）时，f(x) 是否越来越接近某个确定的值 A。"
                        "如果能，就说 f(x) 在 x→x0 时的极限是 A。"
                    ),
                ),
                LectureSection(
                    heading="极限的性质",
                    content=(
                        "1. 唯一性：如果极限存在，则极限值唯一。\n"
                        "2. 有界性：如果极限存在，则函数在 x0 附近有界。\n"
                        "3. 保号性：如果极限为正，则函数在 x0 附近也为正。\n"
                        "4. 夹逼准则：如果 g(x) ≤ f(x) ≤ h(x) 且 g(x) 和 h(x) 趋于相同极限 L，则 f(x) 也趋于 L。"
                    ),
                ),
                LectureSection(
                    heading="两个重要极限",
                    content=(
                        "第一个重要极限：lim(x→0) sin x / x = 1\n"
                        "这个极限在处理三角函数极限时经常用到。\n\n"
                        "第二个重要极限：lim(x→∞) (1 + 1/x)ˣ = e\n"
                        "这个极限定义了自然常数 e ≈ 2.71828。"
                    ),
                ),
                LectureSection(
                    heading="学习建议",
                    content=(
                        "先通过图像和数值表建立直观理解，再学习 ε-δ 的严格定义。"
                        "多做极限计算练习，特别是两个重要极限的变形应用。"
                    ),
                ),
            ],
        ),
        "quiz": QuizJSON(
            title="极限概念自测",
            items=[
                QuizItem(
                    question="lim(x→0) sin x / x 的值是多少？",
                    options=["0", "1", "∞", "不存在"],
                    answer=1,
                    explanation="第一个重要极限：lim(x→0) sin x / x = 1。",
                ),
                QuizItem(
                    question="函数极限存在的必要条件是什么？",
                    options=["函数可导", "左右极限存在且相等", "函数连续", "函数有定义"],
                    answer=1,
                    explanation="函数在 x0 处极限存在的充要条件是左右极限存在且相等。",
                ),
                QuizItem(
                    question="如果 lim f(x) = L > 0，则根据保号性可以推出什么？",
                    options=["f(x) 恒大于 L", "在 x0 附近 f(x) > 0", "f(x) 是增函数", "L 是最大值"],
                    answer=1,
                    explanation="保号性：如果极限为正，则函数在该点附近也为正。",
                ),
            ],
        ),
    },
    "连续": {
        "mindmap": MindMapJSON(
            title="连续函数",
            nodes=[
                MindMapNode(id="def", label="连续定义", children=[
                    MindMapNode(id="three", label="三个条件"),
                    MindMapNode(id="left_right", label="左右连续"),
                ]),
                MindMapNode(id="types", label="间断点类型", children=[
                    MindMapNode(id="removable", label="可去间断点"),
                    MindMapNode(id="jump", label="跳跃间断点"),
                    MindMapNode(id="infinite", label="无穷间断点"),
                ]),
                MindMapNode(id="prop", label="连续函数性质", children=[
                    MindMapNode(id="ivt", label="介值定理"),
                    MindMapNode(id="maxmin", label="最值定理"),
                    MindMapNode(id="zeros", label="零点定理"),
                ]),
                MindMapNode(id="relation", label="与导数关系", children=[
                    MindMapNode(id="diff", label="可导必连续"),
                    MindMapNode(id="converse", label="连续不一定可导"),
                ]),
            ],
        ),
        "lecture": LectureDocJSON(
            title="函数的连续性讲解",
            difficulty="intermediate",
            sections=[
                LectureSection(
                    heading="连续的定义",
                    content=(
                        "函数 f(x) 在点 x0 处连续，需要满足三个条件：\n"
                        "1. f(x0) 有定义\n"
                        "2. lim(x→x0) f(x) 存在\n"
                        "3. lim(x→x0) f(x) = f(x0)\n\n"
                        "直观理解：函数的图像在该点不间断，可以一笔画出来。"
                    ),
                ),
                LectureSection(
                    heading="间断点的分类",
                    content=(
                        "1. 可去间断点：极限存在但不等于函数值或函数在该点无定义\n"
                        "2. 跳跃间断点：左右极限存在但不相等\n"
                        "3. 无穷间断点：极限为无穷大\n"
                        "4. 振荡间断点：函数在该点附近无限振荡"
                    ),
                ),
                LectureSection(
                    heading="连续函数的重要性",
                    content=(
                        "闭区间上的连续函数具有三个关键性质：\n"
                        "1. 最值定理：必能达到最大值和最小值\n"
                        "2. 介值定理：必能取到两端点之间的所有值\n"
                        "3. 零点定理：如果两端点函数值异号，则必存在零点\n\n"
                        "重要的是：可导必连续，但连续不一定可导（如 y=|x| 在 x=0）。"
                    ),
                ),
            ],
        ),
        "quiz": QuizJSON(
            title="连续函数自测",
            items=[
                QuizItem(
                    question="函数在一点连续需要满足几个条件？",
                    options=["1个", "2个", "3个", "4个"],
                    answer=2,
                    explanation="函数连续需要同时满足：有定义、极限存在、极限值等于函数值，共三个条件。",
                ),
                QuizItem(
                    question="y = |x| 在 x=0 处的情况是？",
                    options=["可导且连续", "连续但不可导", "可导但不连续", "既不连续也不可导"],
                    answer=1,
                    explanation="|x| 在 x=0 处连续但不可导，是'连续不一定可导'的典型例子。",
                ),
                QuizItem(
                    question="如果 f(a)·f(b) < 0 且 f 在 [a,b] 连续，则根据什么定理可以断定存在 c∈(a,b) 使 f(c)=0？",
                    options=["最值定理", "介值定理", "零点定理", "罗尔定理"],
                    answer=2,
                    explanation="闭区间连续且两端异号时，零点定理保证存在至少一个零点。",
                ),
            ],
        ),
    },
    "不定积分": {
        "mindmap": MindMapJSON(
            title="不定积分",
            nodes=[
                MindMapNode(id="def", label="定义", children=[
                    MindMapNode(id="antiderivative", label="原函数"),
                    MindMapNode(id="family", label="原函数族"),
                ]),
                MindMapNode(id="basic", label="基本积分公式", children=[
                    MindMapNode(id="power", label="幂函数"),
                    MindMapNode(id="trig", label="三角函数"),
                    MindMapNode(id="exp_log", label="指数与对数"),
                ]),
                MindMapNode(id="methods", label="积分方法", children=[
                    MindMapNode(id="sub", label="换元积分法"),
                    MindMapNode(id="parts", label="分部积分法"),
                    MindMapNode(id="rational", label="有理函数积分"),
                ]),
            ],
        ),
        "lecture": LectureDocJSON(
            title="不定积分入门",
            difficulty="intermediate",
            sections=[
                LectureSection(
                    heading="不定积分的概念",
                    content=(
                        "不定积分是微积分学中的基本运算之一，是导数的逆运算。"
                        "如果 F'(x) = f(x)，则称 F(x) 是 f(x) 的一个原函数，"
                        "而 f(x) 的所有原函数 F(x) + C 称为 f(x) 的不定积分，"
                        "记作 ∫ f(x) dx = F(x) + C。常数 C 称为积分常数，"
                        "体现了原函数族的概念。"
                    ),
                ),
                LectureSection(
                    heading="基本积分公式",
                    content=(
                        "1. ∫ xⁿ dx = xⁿ⁺¹/(n+1) + C  (n ≠ -1)\n"
                        "2. ∫ 1/x dx = ln|x| + C\n"
                        "3. ∫ eˣ dx = eˣ + C\n"
                        "4. ∫ sin x dx = -cos x + C\n"
                        "5. ∫ cos x dx = sin x + C\n"
                        "6. ∫ sec²x dx = tan x + C"
                    ),
                ),
                LectureSection(
                    heading="常用积分方法",
                    content=(
                        "1. 第一换元法（凑微分法）：将被积函数凑成某个函数的导数形式\n"
                        "2. 第二换元法：通过变量代换简化被积函数\n"
                        "3. 分部积分法：∫ u dv = uv - ∫ v du\n"
                        "4. 有理函数积分：通过部分分式分解后逐项积分\n\n"
                        "学习建议：先熟练掌握基本积分公式，再学习各种方法的适用场景。"
                        "多做题是掌握积分技巧的关键。"
                    ),
                ),
            ],
        ),
        "quiz": QuizJSON(
            title="不定积分自测",
            items=[
                QuizItem(
                    question="∫ x² dx 等于什么？",
                    options=["x³/2 + C", "x³/3 + C", "2x + C", "x² + C"],
                    answer=1,
                    explanation="∫ x² dx = x³/3 + C，这是幂函数积分公式的应用。",
                ),
                QuizItem(
                    question="分部积分法 ∫ u dv 的结果是？",
                    options=["uv + ∫ v du", "uv - ∫ v du", "u'v + uv'", "uv + C"],
                    answer=1,
                    explanation="分部积分公式：∫ u dv = uv - ∫ v du。",
                ),
                QuizItem(
                    question="∫ 1/x dx 的结果是什么？",
                    options=["ln x + C", "1/x² + C", "x + C", "ln|x| + C"],
                    answer=3,
                    explanation="∫ 1/x dx = ln|x| + C，注意绝对值符号。",
                ),
            ],
        ),
    },
}


def _extract_topic_key(topic: str) -> Optional[str]:
    """Match user topic to a known mock topic key."""
    topic_lower = topic.strip().lower()
    for key in _MOCK_TOPICS:
        if key in topic or key in topic_lower:
            return key
    return None


def _chunks_to_summary(chunks: list[dict], max_len: int = 200) -> str:
    """Extract a short text summary from retrieved chunks."""
    parts = []
    total = 0
    for c in chunks:
        content = (c.get("content", "") or "").strip()
        if not content:
            continue
        if total + len(content) > max_len:
            remaining = max_len - total
            parts.append(content[:remaining] + "...")
            break
        parts.append(content)
        total += len(content)
    return " ".join(parts).strip()


def _extract_keywords(text: str, max_words: int = 10) -> list[str]:
    """Extract key terms from text for generic resource generation."""
    # Simple heuristic: find capitalized/longer Chinese or English terms
    words = re.findall(r"[\u4e00-\u9fff]{2,6}|\b[A-Za-z]{3,}\b", text)
    seen = set()
    result = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)
            if len(result) >= max_words:
                break
    return result


# ── Prompt builders for LLM-based generation ──────────────────────────────────

_MINDSET_PROMPT = """你是一位知识可视化专家。请根据课程内容和学生画像，生成概念思维导图。
输出纯JSON（不要markdown标记），格式：
{{
  "title": "主题标题",
  "nodes": [
    {{
      "id": "唯一英文ID",
      "label": "节点标签(中文≤20字)",
      "children": [
        {{"id": "子ID", "label": "子标签", "children": []}}
      ]
    }}
  ]
}}
主题：{topic}
课程资料：
{context}
学生画像：
{profile}
要求：节点层级≤3，root节点用title代替nodes，每个分支节点至少2个子节点。内容基于课程资料，体现学生画像特点。只输出JSON。"""

_LECTURE_PROMPT = """你是一位大学教师。请根据课程内容和学生画像，编写个性化讲解文档。
输出纯JSON（不要markdown标记），格式：
{{
  "title": "讲解标题",
  "difficulty": "beginner",
  "sections": [
    {{"heading": "小节标题", "content": "小节内容(Markdown格式)"}}
  ]
}}
主题：{topic}
课程资料：
{context}
学生画像：
{profile}
要求：至少4个小节，涵盖学习目标、核心概念、例题讲解、常见误区、小结与建议。内容基于课程资料。体现学生画像（节奏、短板、资源偏好）。只输出JSON。"""

_QUIZ_PROMPT = """你是一位命题专家。请根据课程内容和学生画像，生成测验题。
输出纯JSON（不要markdown标记），格式：
{{
  "title": "测验标题",
  "items": [
    {{
      "question": "题目",
      "options": ["A.选项", "B.选项", "C.选项", "D.选项"],
      "answer": 0,
      "explanation": "解析说明",
      "difficulty": "basic"
    }}
  ]
}}
主题：{topic}
课程资料：
{context}
学生画像：
{profile}
要求：至少5道题，包含基础题(basic)、理解题(intermediate)、应用题(advanced)。answer是0-based索引。选项不带ABCD前缀，系统会自动添加。题目基于课程资料。体现学生短板知识点。只输出JSON。"""


def _clean_json(text: str) -> str:
    """Strip markdown fences and extract first JSON object."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    # Find first { and last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        text = text[start:end+1]
    # Fix trailing commas before } or ]
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    return text


def _try_llm_generate(llm_provider, prompt: str) -> str | None:
    """Try LLM generation, return content or None on failure."""
    try:
        if llm_provider.provider == "mock":
            return None
        resp = llm_provider.generate(
            [{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return resp.content.strip()
    except Exception as e:
        logger.warning("LLM generation failed for prompt: %s", str(e)[:100])
        return None


def _build_profile_text(profile: dict) -> str:
    """Build human-readable profile summary for prompts."""
    parts = []
    if profile.get("major"):
        parts.append(f"专业：{profile['major']}")
    parts.append(f"知识水平：{profile.get('knowledge_level', 'intermediate')}")
    parts.append(f"认知风格：{profile.get('cognitive_style', 'conceptual')}")
    parts.append(f"学习节奏：{profile.get('pace_preference', 'moderate')}")
    wps = profile.get("weak_points")
    if wps:
        if isinstance(wps, str):
            try: wps = json.loads(wps)
            except: pass
        if isinstance(wps, list) and wps:
            parts.append(f"知识薄弱点：{', '.join(wps)}")
    rps = profile.get("resource_preference")
    if rps:
        if isinstance(rps, str):
            try: rps = json.loads(rps)
            except: pass
        if isinstance(rps, list) and rps:
            parts.append(f"资源偏好：{', '.join(rps)}")
    return "\n".join(parts)


def _chunks_to_context(chunks: list[dict], max_len: int = 1500) -> str:
    """Merge chunks into a prompt-ready context string."""
    parts = []
    total = 0
    for i, c in enumerate(chunks):
        content = (c.get("content", "") or "").strip()
        if not content:
            continue
        src = c.get("source", "unknown")
        part = f"[{i+1}:{src}] {content}"
        if total + len(part) > max_len:
            remaining = max_len - total
            parts.append(part[:remaining])
            break
        parts.append(part)
        total += len(part)
    return "\n\n".join(parts) if parts else "（暂无课程资料）"

# ── MindMap generation ─────────────────────────────────────────────────────────

def _generate_mindmap_json(
    topic: str, chunks: list[dict], llm_provider, profile: dict | None = None
) -> MindMapJSON:
    """Generate a MindMapJSON from topic and retrieved chunks.

    Uses DeepSeek LLM when available, falls back to Mock templates.
    """
    # Try LLM
    context = _chunks_to_context(chunks)
    profile_text = _build_profile_text(profile or {})
    prompt = _MINDSET_PROMPT.format(topic=topic, context=context, profile=profile_text)
    raw = _try_llm_generate(llm_provider, prompt)

    if raw:
        try:
            cleaned = _clean_json(raw)
            data = json.loads(cleaned)
            # Validate nodes structure
            nodes = data.get("nodes", [])
            if nodes and isinstance(nodes, list):
                node_objs = []
                for n in nodes:
                    if isinstance(n, dict) and n.get("label"):
                        children = n.get("children", [])
                        child_objs = [
                            MindMapNode(id=c.get("id", f"c_{i}"), label=c.get("label", "?"))
                            for i, c in enumerate(children)
                            if isinstance(c, dict) and c.get("label")
                        ]
                        node_objs.append(
                            MindMapNode(id=n.get("id", f"n_{len(node_objs)}"),
                                       label=n["label"][:40],
                                       children=child_objs)
                        )
                if node_objs:
                    return MindMapJSON(title=data.get("title", topic)[:80], nodes=node_objs)
        except Exception as e:
            logger.warning("LLM mindmap JSON parse failed: %s", str(e)[:80])

    analysis = _analysis_for_topic(topic, profile)
    branch_map = [
        ("教材位置", [analysis["chapter"], *analysis["conditions"][:2]]),
        ("核心问题", [analysis["intuition"], analysis["definition"]]),
        ("概念直觉", [analysis["intuition"], analysis["profile_hint"]]),
        ("正式定义", [analysis["definition"], *analysis["conditions"][:2]]),
        ("条件判定", analysis["conditions"]),
        ("方法路径", analysis["steps"]),
        ("易错点", analysis["mistakes"]),
        ("例题入口", [analysis["example"], *analysis["solution"][:2]]),
        ("复习建议", ["先看讲义", "再看导图", "完成三道诊断题"]),
    ]
    nodes = [
        MindMapNode(id=f"node_{i}", label=title[:40], children=[
            MindMapNode(id=f"node_{i}_{j}", label=str(child)[:40])
            for j, child in enumerate(children[:4])
        ])
        for i, (title, children) in enumerate(branch_map)
    ]
    return MindMapJSON(title=analysis["label"], nodes=nodes)


# ── Reading / video script generation ──────────────────────────────────────────

def _generate_reading_content(topic: str, chunks: list[dict], profile: dict | None = None) -> str:
    """Generate extended reading material from course chunks."""
    summary = _chunks_to_summary(chunks, max_len=900)
    goal = (profile or {}).get("learning_goal") or "课程掌握"
    weak = (profile or {}).get("weak_points") or "[]"
    keywords = _extract_keywords(summary or topic, max_words=8) or [topic, "核心概念", "典型方法"]
    source_lines = []
    for chunk in chunks[:5]:
        src = chunk.get("source") or chunk.get("metadata", {}).get("source") or "课程资料"
        page = chunk.get("page_number") or chunk.get("metadata", {}).get("page_number")
        source_lines.append(f"- {src}" + (f"，第 {page} 页" if page else ""))
    sections = [
        f"# {topic} · 拓展阅读材料",
        "",
        "## 1. 阅读目标",
        f"- 围绕「{topic}」建立概念框架，服务学习目标：{goal}。",
        "- 能用自己的话解释核心定义、适用条件和常见误区。",
        "- 阅读后能够完成 3-5 道基础题或错题复盘任务。",
        "",
        "## 2. 关键词导航",
        "、".join(keywords),
        "",
        "## 3. 课程依据摘要",
        summary or "（暂无课程片段，以下为通用拓展框架）",
        "",
        "## 4. 推荐阅读路径",
        "1. 先读定义与符号说明，圈出不理解的术语。",
        "2. 再读典型例题，关注每一步使用的条件。",
        "3. 最后对照错题本，找出自己出错的概念或公式。",
        "",
        "## 5. 资料来源",
        "\n".join(source_lines) if source_lines else "- 暂无可引用课程资料",
        "",
        "## 6. 思考问题",
        f"1. 「{topic}」主要解决什么问题？",
        "2. 这个知识点最容易和哪些概念混淆？",
        "3. 如果题目条件发生变化，解题方法是否仍然适用？",
        "",
        "## 7. 读后自测",
        "- 用 3 句话总结本知识点。",
        "- 写出一个典型例题的解题步骤。",
        "- 标记一个仍不确定的问题，回到问答页继续追问。",
        "",
        "## 8. 推荐学习动作",
        "- 先阅读讲义建立概念框架。",
        "- 再通过练习题检验理解。",
        "- 最后回看错题本中的相关知识点。",
    ]
    if weak and weak != "[]":
        sections.append(f"\n## 9. 结合薄弱点\n建议重点阅读与 `{weak}` 相关的章节与例题，并优先生成讲义、导图和巩固练习。")
    return "\n".join(sections)


def _generate_video_script_content(topic: str, chunks: list[dict], profile: dict | None = None) -> str:
    """Generate a multi-scene teaching video script."""
    summary = _chunks_to_summary(chunks, max_len=500)
    style = (profile or {}).get("cognitive_style") or "conceptual"
    lines = [
        f"# {topic} · 教学视频脚本",
        "",
        f"**讲解风格**：{'图解示意为主' if style == 'conceptual' else '逻辑推导为主' if style == 'logical' else '例题实操为主'}",
        "",
        "## 场景 1 · 引入（0:00-0:45）",
        f"**画面**：课程标题 + {topic} 关键词卡片",
        f"**旁白**：这节课我们来理解「{topic}」。先明确它解决什么问题，以及和已学知识的联系。",
        "",
        "## 场景 2 · 核心讲解（0:45-2:30）",
        "**画面**：知识点结构图 + 课程资料片段高亮",
        f"**旁白**：{summary[:200] or '结合课程资料，从定义、原理和典型应用三个层面展开讲解。'}",
        "",
        "## 场景 3 · 例题演示（2:30-3:30）",
        "**画面**：例题步骤动画",
        "**旁白**：通过一个典型例题，演示如何应用本节知识解决问题。",
        "",
        "## 场景 4 · 总结与练习（3:30-4:00）",
        "**画面**：总结卡片 + 练习入口",
        f"**旁白**：总结「{topic}」的关键要点，并引导完成配套练习巩固理解。",
    ]
    return "\n".join(lines)


# ── Lecture generation ─────────────────────────────────────────────────────────

def _generate_lecture_doc_json(
    topic: str, chunks: list[dict], llm_provider, profile: dict | None = None
) -> LectureDocJSON:
    """Generate a LectureDocJSON from topic, chunks, and student profile.

    Uses DeepSeek LLM when available, falls back to Mock templates.
    """
    # Try LLM
    context = _chunks_to_context(chunks)
    profile_text = _build_profile_text(profile or {})
    prompt = _LECTURE_PROMPT.format(topic=topic, context=context, profile=profile_text)
    raw = _try_llm_generate(llm_provider, prompt)

    if raw:
        try:
            cleaned = _clean_json(raw)
            data = json.loads(cleaned)
            sections_data = data.get("sections", [])
            if sections_data and isinstance(sections_data, list):
                sections = []
                for s in sections_data:
                    if isinstance(s, dict) and s.get("heading") and s.get("content"):
                        sections.append(LectureSection(
                            heading=s["heading"],
                            content=s["content"]
                        ))
                if sections:
                    return LectureDocJSON(
                        title=data.get("title", f"{topic}讲解")[:80],
                        difficulty=data.get("difficulty", "intermediate"),
                        sections=sections
                    )
        except Exception as e:
            logger.warning("LLM lecture JSON parse failed: %s", str(e)[:80])

    analysis = _analysis_for_topic(topic, profile)
    difficulty = profile.get("knowledge_level", "intermediate") if profile else "intermediate"
    sections = [
        LectureSection(heading="教材定位", content=f"{analysis['chapter']}。核心问题：{analysis['intuition']}"),
        LectureSection(heading="为什么难", content=f"容易混淆：{'；'.join(analysis['mistakes'])}。{analysis['profile_hint']}"),
        LectureSection(heading="人话解释", content=analysis["intuition"]),
        LectureSection(heading="正式定义拆解", content=f"{analysis['definition']}\n符号重点和条件：{'；'.join(analysis['conditions'])}"),
        LectureSection(heading="条件检查清单", content="\n".join(f"- {x}" for x in analysis["conditions"])),
        LectureSection(heading="典型例题完整拆解", content=f"题目：{analysis['example']}\n" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(analysis["solution"]))),
        LectureSection(heading="常见错误与纠正", content="\n".join(f"- 错误：{x}\n  纠正：回到定义条件，写出这一步的依据。" for x in analysis["mistakes"])),
        LectureSection(heading="课后 15 分钟复习安排", content="3 分钟复述概念；5 分钟重做例题；5 分钟完成诊断题；2 分钟标记错因和下一步资源。"),
        LectureSection(heading="自测清单", content="能说清研究对象；能列出条件；能解释例题步骤；能辨析相近概念；能归因错题。"),
    ]
    return LectureDocJSON(title=f"{analysis['label']}老师讲课式讲义", difficulty=difficulty, sections=sections)


# ── Quiz generation ────────────────────────────────────────────────────────────

def _generate_quiz_json(
    topic: str, chunks: list[dict], llm_provider, profile: dict | None = None
) -> QuizJSON:
    """Generate a QuizJSON from topic and chunks.

    Uses DeepSeek LLM when available, falls back to Mock templates.
    """
    # Try LLM
    context = _chunks_to_context(chunks)
    profile_text = _build_profile_text(profile or {})
    prompt = _QUIZ_PROMPT.format(topic=topic, context=context, profile=profile_text)
    raw = _try_llm_generate(llm_provider, prompt)

    if raw:
        try:
            cleaned = _clean_json(raw)
            data = json.loads(cleaned)
            items_data = data.get("items", [])
            if items_data and isinstance(items_data, list):
                items = []
                for it in items_data:
                    if not isinstance(it, dict):
                        continue
                    q = it.get("question", "")
                    opts = it.get("options", [])
                    ans = it.get("answer", 0)
                    exp = it.get("explanation", "")
                    if not q or len(opts) < 2 or not exp:
                        continue
                    # Strip A/B/C/D prefix if present
                    opts_clean = [re.sub(r'^[A-D][.、．:：\s]+', '', o).strip() for o in opts]
                    # Ensure answer is within range
                    ans = max(0, min(int(ans), len(opts_clean) - 1))
                    items.append(QuizItem(
                        question=q, options=opts_clean, answer=ans, explanation=exp
                    ))
                if len(items) >= 3:
                    return QuizJSON(title=data.get("title", f"{topic}自测")[:80], items=items)
        except Exception as e:
            logger.warning("LLM quiz JSON parse failed: %s", str(e)[:80])

    analysis = _analysis_for_topic(topic, profile)
    items = [
        QuizItem(
            question=f"【概念辨析】关于{analysis['label']}，哪项说法正确？",
            options=[analysis["intuition"], analysis["mistakes"][0], "只需背公式不看条件", "只看最终答案即可"],
            answer=0,
            explanation=f"该题考察核心直觉：{analysis['intuition']}。错因通常是{analysis['mistakes'][0]}。",
        ),
        QuizItem(
            question=f"【条件判断】处理{analysis['label']}题目前应先检查什么？",
            options=[analysis["conditions"][0], analysis["mistakes"][1] if len(analysis["mistakes"]) > 1 else "直接套公式", "先写答案", "忽略题干限制"],
            answer=0,
            explanation=f"方法是否可用取决于条件。先检查：{analysis['conditions'][0]}。",
        ),
        QuizItem(
            question=f"【基础应用】{analysis['example']} 的第一步是什么？",
            options=[analysis["solution"][0], analysis["mistakes"][2] if len(analysis["mistakes"]) > 2 else "跳过条件", "只写结论", "不解释依据"],
            answer=0,
            explanation=f"基础题先从第一步依据开始：{analysis['solution'][0]}。",
        ),
    ]
    return QuizJSON(title=f"{analysis['label']}诊断练习", items=items)


# ── Main pipeline ──────────────────────────────────────────────────────────────

def generate_resource_pack(
    course_id: int,
    topic: str,
    resource_types: list[ResourceType],
    student_profile: dict,
    top_k: int,
    session: Session,
    user: User,
) -> ResourcePackResponse:
    """Generate a pack of educational resources from course knowledge base.

    Pipeline: verify course → RAG search → JSON generation → rendering → pack.

    Args:
        course_id: Course to search in.
        topic: Topic/question to generate resources for.
        resource_types: Types of resources to generate.
        student_profile: Profile dict with knowledge_level and cognitive_style.
        top_k: Number of chunks to retrieve (capped at MAX_RESOURCE_TOP_K).
        session: Database session.
        user: Authenticated user.

    Returns:
        ResourcePackResponse with generated resources and citations.
    """
    top_k = min(top_k, MAX_RESOURCE_TOP_K)

    # Verify course
    course = session.get(Course, course_id)
    if not course:
        raise ValueError(f"course not found: {course_id}")

    # Retrieve chunks
    search_result = search_course(course_id, topic, top_k, session)
    if "error" in search_result:
        raise ValueError(search_result["error"])

    chunks = search_result.get("results", [])
    if not chunks:
        raise ValueError("no relevant course materials found for this topic")

    # Build citations
    citations = [
        Citation(
            chunk_id=c.get("chunk_id"),
            source=c.get("source"),
            page_number=c.get("page_number"),
            score=c.get("score"),
        )
        for c in chunks
    ]

    # Get LLM provider + full student profile
    llm_provider = get_llm_provider()
    full_profile = {}
    try:
        from app.services.profile_service import get_or_create_profile
        uid = int(user.id) if user.id else 0
        sp = get_or_create_profile(uid, session)
        full_profile = {
            "major": sp.major,
            "learning_goal": sp.learning_goal,
            "knowledge_level": sp.knowledge_level,
            "cognitive_style": sp.cognitive_style,
            "weak_points": sp.weak_points,
            "pace_preference": sp.pace_preference,
            "resource_preference": sp.resource_preference,
            "motivation": sp.motivation,
            "meta_learning_level": sp.meta_learning_level,
        }
    except Exception:
        full_profile = student_profile

    # Generate resources
    resources: list[ResourceItem] = []
    num_chunks = len(chunks)

    for rt in resource_types:
        try:
            item = _generate_single_resource(
                rt, topic, chunks, full_profile, llm_provider,
                num_chunks, course_id, session, user
            )
            resources.append(item)
        except Exception as e:
            logger.warning("Failed to generate resource type=%s: %s", rt.value, e)
            resources.append(
                ResourceItem(
                    type=rt,
                    title=topic,
                    content=f"生成失败：{str(e)}",
                    generated_by="error",
                    fallback_used=True,
                )
            )

    return ResourcePackResponse(
        course_id=course_id,
        course_name=course.name or "",
        topic=topic,
        resources=resources,
        citations=citations,
        provider=llm_provider.provider,
        model=llm_provider.model,
    )


def _generate_single_resource(
    rt: ResourceType,
    topic: str,
    chunks: list[dict],
    student_profile: dict,
    llm_provider,
    num_chunks: int = 0,
    course_id: int = 0,
    session = None,
    user = None,
) -> ResourceItem:
    """Generate a single resource item of the given type."""
    is_mock = llm_provider.provider == "mock"
    used_llm = False

    if rt == ResourceType.MINDMAP:
        mm_json = _generate_mindmap_json(topic, chunks, llm_provider, student_profile)
        mermaid = render_mindmap_to_mermaid(mm_json)
        # Detect if LLM was used: compare against known mock templates
        topic_key = _extract_topic_key(topic)
        used_llm = not is_mock and (
            topic_key is None
            or topic_key not in _MOCK_TOPICS
            or mm_json.model_dump() != _MOCK_TOPICS[topic_key]["mindmap"].model_dump()
        )
        return ResourceItem(
            type=ResourceType.MINDMAP,
            title=mm_json.title,
            mermaid=mermaid,
            raw_json=mm_json.model_dump(),
            generated_by="deepseek" if used_llm else "fallback_template",
            used_rag=(num_chunks > 0),
            used_profile=True,
            fallback_used=not used_llm,
            context_chunks=num_chunks,
        )

    elif rt == ResourceType.LECTURE_DOC:
        lec_json = _generate_lecture_doc_json(topic, chunks, llm_provider, student_profile)
        md_content = render_lecture_to_markdown(lec_json)
        topic_key = _extract_topic_key(topic)
        used_llm = not is_mock and (
            topic_key is None
            or topic_key not in _MOCK_TOPICS
            or lec_json.model_dump() != _MOCK_TOPICS[topic_key]["lecture"].model_dump()
        )
        return ResourceItem(
            type=ResourceType.LECTURE_DOC,
            title=lec_json.title,
            content=md_content,
            generated_by="deepseek" if used_llm else "fallback_template",
            used_rag=(num_chunks > 0),
            used_profile=True,
            fallback_used=not used_llm,
            context_chunks=num_chunks,
        )

    elif rt == ResourceType.QUIZ:
        quiz_json = _generate_quiz_json(topic, chunks, llm_provider, student_profile)
        quiz_dict = render_quiz(quiz_json)
        topic_key = _extract_topic_key(topic)
        used_llm = not is_mock and (
            topic_key is None
            or topic_key not in _MOCK_TOPICS
            or quiz_json.model_dump() != _MOCK_TOPICS[topic_key]["quiz"].model_dump()
        )
        return ResourceItem(
            type=ResourceType.QUIZ,
            title=quiz_json.title,
            items=quiz_dict.get("items", []),
            generated_by="deepseek" if used_llm else "fallback_template",
            used_rag=(num_chunks > 0),
            used_profile=True,
            fallback_used=not used_llm,
            context_chunks=num_chunks,
        )

    elif rt == ResourceType.PPT:
        from app.services.ppt_service import build_slide_deck, render_pptx
        from app.services.generated_file_storage import save_generated_file

        slide_deck = build_slide_deck(topic, chunks, student_profile, llm_provider)
        pptx_bytes = render_pptx(slide_deck)
        file_info = save_generated_file(
            content=pptx_bytes,
            filename=f"{topic}_课件.pptx",
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        # Detect if LLM content was used
        ppt_used_llm = slide_deck.get("generated_by") == "deepseek"
        return ResourceItem(
            type=ResourceType.PPT,
            title=slide_deck.get("title", topic),
            resource_id=file_info["resource_id"],
            filename=file_info["filename"],
            download_url=file_info["download_url"],
            slide_count=len(slide_deck.get("slides", [])),
            generated_by="deepseek" if ppt_used_llm else "fallback_template",
            used_rag=(num_chunks > 0),
            used_profile=True,
            fallback_used=not ppt_used_llm,
            context_chunks=num_chunks,
        )

    elif rt == ResourceType.READING:
        content = _generate_reading_content(topic, chunks, student_profile)
        return ResourceItem(
            type=ResourceType.READING,
            title=f"{topic}拓展阅读",
            content=content,
            generated_by="template" if is_mock else "deepseek",
            used_rag=(num_chunks > 0),
            used_profile=True,
            fallback_used=is_mock,
            context_chunks=num_chunks,
        )

    elif rt == ResourceType.VIDEO_SCRIPT:
        content = _generate_video_script_content(topic, chunks, student_profile)
        return ResourceItem(
            type=ResourceType.VIDEO_SCRIPT,
            title=f"{topic}教学视频脚本",
            content=content,
            generated_by="template" if is_mock else "deepseek",
            used_rag=(num_chunks > 0),
            used_profile=True,
            fallback_used=is_mock,
            context_chunks=num_chunks,
        )

    elif rt == ResourceType.STUDY_PLAN:
        from app.services.study_plan_service import generate_study_plan, render_study_plan_markdown
        from app.services.resource_renderer import render_study_plan
        from app.services.profile_service import get_or_create_profile

        profile = None
        if user and session:
            try:
                profile = get_or_create_profile(int(user.id) if user.id else 0, session)
            except Exception:
                pass

        plan = generate_study_plan(
            course_id=course_id,
            topic=topic,
            profile=profile,
            session=session,
            top_k=5,
        )
        plan_validated = render_study_plan(plan)
        plan_used_llm = plan.get("provider") != "rule"
        return ResourceItem(
            type=ResourceType.STUDY_PLAN,
            title=plan.get("title", topic),
            study_plan=plan_validated,
            content=render_study_plan_markdown(plan),
            generated_by=plan.get("provider", "deepseek") if plan_used_llm else "fallback_template",
            used_rag=(num_chunks > 0),
            used_profile=True,
            fallback_used=not plan_used_llm,
            context_chunks=num_chunks,
        )

    else:
        raise ValueError(f"unsupported resource type: {rt.value}")
