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
- 学习讲义、思维导图、练习题、PPT、学习路径、视频脚本、动画预览、拓展阅读资源能力
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

- Base URL: `https://spark-api-open.xf-yun.com/x2`
- Model: `spark-x`
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
