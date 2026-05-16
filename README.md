# DV_ACODE_GEN_PLATFORM

IC验证辅助代码生成平台 — 输入结构化需求表，确定性输出 SVA 断言 和 UVM 功能覆盖率代码。

---

## 核心特性

- **确定性生成**：相同输入必然产生相同输出（Redis缓存 → 算法匹配引擎 → Jinja2渲染三层保障），仅对域内 IC 验证输入承诺
- **LLM 仅做参数提取**：temperature=0 + JSON Schema，不参与代码生成
- **双表格输入**：SVA需求表 + 功能覆盖率需求表（Excel格式）
- **两步式确认面板**：preview 返回 RAG Top-3 候选 + 参数预填值（5 类来源徽标 + expr_type 校验/清洗结果），用户切换候选/编辑参数后再 render；意图缓存命中自动短路
- **无关意图拒绝**：RAG dense 余弦阈值闸（默认 0.44）在 LLM 调用前直接返回 HTTP 422，避免对诗歌/闲聊/通用代码请求生成全 placeholder 占位代码
- **Thinking 模型友好**：GLM-4.7 / DeepSeek-R1 等三步调用按用途独立调档；step2 thinking 开关在 Admin UI 可切（默认禁，实测从 12-249s 降至 ~3s）
- **三级权限**：普通用户 / 库管理员 / 超管
- **批量处理**：Excel 批量导入，打包下载生成结果

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI + PostgreSQL + Qdrant + Redis + Celery + Jinja2 |
| 嵌入服务 | BGE-M3（dense + sparse 混合）+ BGE Reranker v2-m3，独立 GPU 服务 |
| LLM | OpenAI 兼容接口（智谱 GLM、DeepSeek、Ollama 等）+ Anthropic Claude，多模型工厂可插拔 |
| 前端 | React + TypeScript + Vite + Ant Design + Zustand + Monaco Editor |
| 部署 | Docker + Docker Compose + Nginx（多 overlay：dev / hotreload / GPU） |

## 快速开始

```bash
git clone https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM.git
cd DV_ACODE_GEN_PLATFORM

# 一键启动完整栈（CPU 默认，需 GPU 加 -f docker-compose.gpu-linux.yml）
docker compose up --build
```

- 前端：http://localhost/
- API：http://localhost/api/
- API 文档：http://localhost/api/docs

详细搭建步骤见 [CONTRIBUTING.md](CONTRIBUTING.md#3-本地开发环境)，部署到生产/内网见 [docs/deployment.md](docs/deployment.md)。

## 文档索引

| 文档 | 说明 |
|------|------|
| [PRD.md](PRD.md) | 产品需求文档 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构设计 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 建仓、开发、文档维护指南 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更历史 |
| [docs/deployment.md](docs/deployment.md) | 部署索引（场景对比 + 跳转分册） |
| [docs/deployment-dev-windows.md](docs/deployment-dev-windows.md) | Win11 本机开发部署（hot reload + bind mount） |
| [docs/deployment-prod-linux.md](docs/deployment-prod-linux.md) | Linux 公司内网生产部署（受限外网 + GPU + 安全加固） |
| [docs/test-manual.md](docs/test-manual.md) | 平台功能测试手册（11 章 + 2 附录，含 10 模板触发用例 / 易混淆对照 / 低置信度兜底 / 贡献闭环 / 已知 gap） |

## 项目状态

当前阶段：**核心功能实现完成，待 Alpha 测试**

- [x] PRD 确认（v2.12，v3.0 起草中：IntentBuilder 多轮对话改造 + under_specified/code_type_mismatch 两道 422 闸 + 错误响应 `redirect_to` 跳转）
- [x] 架构设计（ARCHITECTURE v2.18，已同步 PRD v3.0 用户旅程重构：IntentBuilder 多轮对话 + 贡献机制 LLM 反推 + code_type_mismatch/under_specified 两道 422 闸 + 错误响应 `redirect_to`）
- [x] 后端骨架搭建
- [x] 确定性引擎核心实现（pipeline / renderer / dedup / cache + identifier 规范化 + expr_validator 校验）
- [x] 三阶段 RAG 检索流水线（混合检索 → ColBERT 精排 → Cross-Encoder 重排，含关键词补充召回兜底）
- [x] 无关意图 dense 余弦阈值闸（HTTP 422 + 前端专属 Modal + 校准脚本 + 回归语料）
- [x] 两步式 UI 确认面板（preview + render，5 类参数源徽标 + expr_type 清洗/校验提示，意图缓存短路）
- [x] 前端框架搭建（生成页、意图构建器、模板库、批量处理、管理控制台、登录/注册）
- [x] 模板库初始化（SVA 断言 6 个 + 功能覆盖率 4 个）
- [x] 批量处理 & Celery 任务队列
- [x] LLM 多模型配置管理（Anthropic / OpenAI 兼容 / GLM / DeepSeek / Ollama，per-call thinking/`max_tokens` 调档 + Admin UI step2 thinking 开关）
- [x] 独立嵌入服务（BGE-M3 + BGE Reranker，支持 GPU/CPU）
- [x] Docker Compose 完整栈（含开发热重载、GPU 部署 overlay）
- [x] 部署手册（[dev-windows](docs/deployment-dev-windows.md) / [prod-linux](docs/deployment-prod-linux.md) / [WSL 启动](docs/startup-wsl.md)）
- [x] 单元测试基础落地（pipeline preview/render + 正则参数提取 + off-topic mocked 回归套件）
- [ ] Alpha 测试

## License

Private — 内部使用，未授权不得分发。
