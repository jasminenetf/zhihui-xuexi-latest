<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platform">
</p>

<h1 align="center">智学工坊</h1>
<h3 align="center">面向高校工科基础课的多智能体个性化学习资源生成系统</h3>
<p align="center">课程级 AI 学习工作台：资料理解、问答辅导、资源生成、错题复盘与学习路径推荐</p>

---

## 产品定位

智学工坊当前答辩版以《高等数学上册》为样例课程，面向高校工科基础课学习场景。系统围绕“提问诊断 → 课程检索 → 可信回答 → 多资源生成 → 练习反馈 → 错题复盘 → 学习画像更新 → 个性化学习路径调整”的闭环，帮助学生把一个不会的问题拆成可学、可练、可复盘的学习过程。项目仓库名为 `123444`，但对外展示项目名称统一为“智学工坊——面向高校工科基础课的多智能体个性化学习资源生成系统”。

### 核心能力

| 能力 | 说明 |
|------|------|
| 课程与资料管理 | 创建课程、上传资料、自动解析、构建知识库 |
| 对话式画像构建 | 通过自然语言对话提取学习特征，动态更新学习画像 |
| 多智能体资源生成 | 提问后自动生成学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览和拓展阅读 |
| 个性化学习路径 | 基于当前问题、画像、错题和教材章节，自动生成学习顺序、资源、原因、时间和检验标准 |
| 学习闭环 | 提问、练习、复盘、报告、资源推送形成完整链路 |

### 技术栈

`FastAPI` `SQLModel` `ChromaDB` `LangGraph` `Spark / DeepSeek / Mock fallback` `sentence-transformers` `Markdown PPT` `sqladmin`

### 比赛交付亮点

| 亮点 | 说明 |
|------|------|
| 多智能体协作 | ProfileAgent / RetrievalAgent / TutorAgent / ResourceAgent / AssessmentAgent / PlannerAgent / VerifierAgent 形成可追踪链路 |
| RAG 防幻觉 | 回答返回引用、grounding 分数、风险等级、无依据提示和内容安全状态 |
| 个性化资源包 | 围绕当前问题自动聚合学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览和拓展阅读 |
| 学习效果评价 | 测验结果写入知识点掌握度，学习报告展示掌握度、强弱项与推荐动作 |
| 学习闭环工作台 | 首页串联画像、问答、资源生成、测验、错题复盘、学习路径和报告 |
| QA 回归 | `scripts/verify_p0_smoke.py` + `scripts/deep_qa_check.py` 覆盖启动、问答、自动资源包、下载、错题反馈和敏感信息 |

### 推荐升级方向

- 后端主干：`FastAPI` + `PostgreSQL` + `pgvector`
- 异步任务：`Redis` + `Celery/RQ`
- 检索增强：混合检索 + rerank
- 前端工作台：`Next.js` + `React` + `TypeScript` + `shadcn/ui`
- 存储与文件：`MinIO` / `S3`
- 观测与评测：`OpenTelemetry` + tracing / eval

---

## 快速开始

### 1. 安装依赖

#### Windows
双击 `install.bat`

#### macOS / Linux / WSL

```bash
bash install.sh
```

### 2. 配置环境变量

复制 `backend/.env.example` 为 `backend/.env`，并配置模型与数据库相关参数。

```ini
# 答辩推荐：科大讯飞 Spark 为主引擎
LLM_PROVIDER=spark
SPARK_ENABLED=true
SPARK_API_PASSWORD=你的APIPassword

# 或开发备用 DeepSeek
DEEPSEEK_API_KEY=sk-你的APIKey
DEEPSEEK_MODEL=deepseek-v4-pro
```

### 3 分钟答辩演示脚本

1. **设置页**：配置 Spark → 测试连接成功（顶部栏显示 `Spark`）
2. **课程资料库**：免登录上传 PDF/Word → 确认知识片段数量 > 0
3. **会话中心**：提问“我不懂函数极限，讲清定义、常见误区，并给一个例题” → 观察可信回答、课程引用和模型状态
4. **右侧预览**：提问后自动推荐学习讲义、思维导图、练习题、PPT 课件、学习路径、视频脚本、动画预览和拓展阅读
5. **练习题**：故意选错一题 → 原地查看详细解析、错因和下一步练习建议
6. **学习画像/路径**：展示 6 维画像和动态学习路径如何随对话、错题更新

### 3. 启动服务

#### Windows
双击 `启动智学工坊.bat`

#### macOS / Linux

```bash
bash scripts/start_app.sh
```

前端默认访问地址：`http://127.0.0.1:5173`
后端默认访问地址：`http://127.0.0.1:8010`

如需手动启动当前免登录 Demo 后端：

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.demo_main:app --host 127.0.0.1 --port 8010 --reload
```

正式后端开发入口仍保留为 `app.main:app`，建议仅在调试数据库、RAG 和完整 FastAPI 路由时使用。

### 4. 可选基础设施（PostgreSQL / Redis / MinIO）

项目默认使用 SQLite 快速运行模式。若需要演示或验证 P1 架构增强，可以启动基础设施：

```bash
docker compose up -d postgres redis minio
```

服务默认地址：

- PostgreSQL：`127.0.0.1:5432`
- Redis：`127.0.0.1:6379`
- MinIO API：`http://127.0.0.1:9000`
- MinIO Console：`http://127.0.0.1:9001`

如需切换 PostgreSQL，请参考 `backend/.env.example` 中的 `DATABASE_URL` 示例。当前比赛演示仍建议使用 SQLite 快速模式，降低环境复杂度。

### 5. 演示数据初始化

当前比赛候选版本默认收口到《高等数学上册》样例课程。轻量 Demo 后端启动后会内置函数极限、左右极限、无穷小、连续、导数、积分、微分方程等课程知识结构，适合直接演示“提问 → 引用 → 资源 → 测验 → 画像 → 路径 → 报告”闭环。

#### 5.1 高等数学上册真实教材导入

如果 PDF 有可复制文本层，可以直接导入：

```powershell
$env:GAOSHU_PDF_PATH='C:\Users\zhang\Desktop\高数上.pdf'  # 原始本地文件名，系统对外统一显示“高等数学上册”
python scripts/seed_gaoshu_pdf.py
```

如果 PDF 是扫描版，需要启用 OCR。先确保已安装 Tesseract OCR，并准备中文简体语言包 `chi_sim.traineddata`。项目支持把语言包放在本地目录：

```text
.local/tessdata/chi_sim.traineddata
```

全量 OCR 导入命令：

```powershell
$env:GAOSHU_OCR='1'
$env:GAOSHU_MAX_PAGES='0'
$env:TESSDATA_PREFIX='C:\Users\zhang\Desktop\智能学习\.local\tessdata'
python scripts/seed_gaoshu_pdf.py
```

在本机演示环境中，可选导入扫描版《高等数学上册》：

- PDF 页数：442
- 知识片段：668
- 课程 ID：2
- 课程名称：`高等数学上册 - 真实教材演示课程`

推荐演示问题：

```text
请根据教材解释函数极限的定义，并举一个简单例子。
```

```text
请结合教材说明导数的几何意义和物理意义。
```

```text
我对洛必达法则不熟，请根据教材给我生成讲义、思维导图和巩固练习。
```

### 6. P0 Smoke 与 Deep QA 回归验证

启动后端并初始化演示数据后运行：

```bash
python scripts/verify_p0_smoke.py
```

如果后端运行在临时端口，例如 `8010`：

```bash
# Windows PowerShell
$env:P0_SMOKE_BASE='http://127.0.0.1:8010'
python scripts/verify_p0_smoke.py

# macOS / Linux
P0_SMOKE_BASE=http://127.0.0.1:8010 python scripts/verify_p0_smoke.py
```

当前 P0 smoke 覆盖：

- 健康检查与 bootstrap
- 登录注册与权限限制
- demo endpoint 禁用
- 资源中心接口
- 学习报告 mastery 字段
- quiz submit 掌握度写入
- dashboard
- ask 的 agent trace / grounding / safety / resource package 校验（有可用课程资料时）

答辩前建议继续运行深度 QA：

```bash
python scripts/deep_qa_check.py
```

`deep_qa_check.py` 默认使用本地 Mock/fallback，不消耗真实 Spark 额度，覆盖：

- 后端与前端语法检查
- P0 smoke
- 固定《高等数学上册》问题的问答和八类学习资源
- 思维导图可读树、练习题、讲义、学习路径、Markdown PPT 结构
- 资源下载文件可打开且包含教材依据、Verifier 和生成来源
- 测验选错后的原地详细解析
- 常见敏感信息扫描

### Playwright 浏览器验收

如需复跑前端 E2E：

```powershell
cd tests/e2e
npm install
npx playwright install chromium
npx playwright test
```

E2E 默认访问 `http://127.0.0.1:5173` 和 `http://127.0.0.1:8010`，测试问题固定为函数极限，不再使用旧 AI 导论/过拟合主题。

### 5. 停止服务

#### Windows
双击 `停止智学工坊.bat`

#### macOS / Linux

```bash
bash scripts/stop_app.sh
```

---

## 使用流程

```text
打开页面 → 配置 API Key → 创建课程 → 上传资料 → 构建知识库 → 对话提问 → 生成资源 → 做题复盘 → 查看报告
```

### 主要页面

| 页面 | 功能 |
|------|------|
| 工作台 | 课程状态、学习进度、任务与推荐 |
| 会话中心 | 课程问答、上下文会话、自动学习资源包 |
| 课程中心 | 创建课程、切换课程、课程上下文管理 |
| 资料库 | 课程文件、知识块、解析状态 |
| 资源中心 | 讲义、导图、题库、Markdown PPT、学习路径等资产管理与下载 |
| 错题本 | 错题记录、详细讲解、复习计划、薄弱点追踪 |
| 学习报告 | 学习进度、行为记录、推荐建议 |
| 账户与设置 | 免登录状态、API Key 配置与系统状态 |

---

## API 概览

当前免登录 Demo 后端启动在 `http://127.0.0.1:8010`

| 端点 | 说明 |
|------|------|
| `GET /api/app/bootstrap` | 启动自检与课程概览 |
| `POST /api/auth/login` | 用户登录 |
| `POST /api/auth/register` | 用户注册 |
| `GET /api/courses` | 课程列表 |
| `POST /api/courses` | 创建课程 |
| `POST /api/courses/{course_id}/files` | 上传课程资料 |
| `GET /api/courses/{course_id}/files` | 查询课程文件 |
| `GET /api/courses/{course_id}/chunks` | 查询课程知识块 |
| `POST /api/app/ask` | 课程问答（RAG） |
| `POST /api/app/generate` | 资源生成 |
| `GET /api/sessions` | 学习会话列表 |
| `GET /api/analytics/progress` | 学习进度 |
| `GET /api/analytics/wrong-book` | 错题本 |
| `GET /api/analytics/bookmarks` | 收藏资源 |
| `GET /api/settings/status` | 系统状态 |

完整 API 文档：`http://127.0.0.1:8010/docs`

---

## 部署说明

### 本地开发
- 后端：FastAPI
- 前端：静态页面 + 前端脚本
- 数据库：SQLite / SQLModel（按当前配置）

### 生产建议
- 使用 Docker 容器化部署
- 使用独立数据库与对象存储
- 通过环境变量管理模型、数据库、日志与密钥
- 开启健康检查、日志收集与监控告警

---

## 项目结构

```text
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── api/              # API 路由
│   │   ├── core/             # 配置、数据库、安全
│   │   ├── models/           # 数据模型
│   │   ├── schemas/          # 请求与响应结构
│   │   └── services/         # 业务服务与多智能体编排
│   ├── .env.example          # 环境变量模板
│   └── requirements.txt      # Python 依赖
├── frontend-demo/            # 前端工作台
├── seed/                     # 种子数据
├── scripts/                  # 启停与初始化脚本
├── install.sh                # Linux/macOS/WSL 安装脚本
├── install.bat               # Windows 安装脚本
├── release/启动智学工坊.bat    # Windows 启动器
└── release/停止智学工坊.bat    # Windows 停止器
```

---

## 常见问题

**Q: 启动后浏览器显示“未连接”？**  
A: 检查后端是否启动、端口是否占用、`.env` 配置是否正确。

**Q: 问答或资源生成返回错误？**  
A: 先看设置页的 provider/model/fallback/Chroma/vector_count 状态。Spark 未配置或失败时，系统会标注失败原因并进入“本地演示兜底 Mock”，该模式只用于流程演示，不应被当作真实模型效果。

**Q: 为什么 GitHub 上没有 API Key？**  
A: 这是正常的。密钥保存在本机 `backend/.env` 中，不应提交到仓库。

**Q: 知识库为空？**  
A: 请先创建课程并上传资料，系统会自动解析并生成知识块。

---

## 许可证

MIT License

## 作者

jasminenetf

---

<p align="center"><sub>Built with FastAPI + LangGraph + Spark / DeepSeek / Mock fallback</sub></p>
