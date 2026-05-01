# DV_ACODE_GEN_PLATFORM

IC验证辅助代码生成平台 — 输入结构化需求表，确定性输出 SVA 断言 和 UVM 功能覆盖率代码。

---

## 核心特性

- **确定性生成**：相同输入必然产生相同输出（Redis缓存 → 算法匹配引擎 → Jinja2渲染三层保障）
- **LLM 仅做参数提取**：temperature=0 + JSON Schema，不参与代码生成
- **双表格输入**：SVA需求表 + 功能覆盖率需求表（Excel格式）
- **智能置信度**：>85% 自动生成，≤85% 展示 Top-3 候选供确认
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
| [PRD.md](PRD.md) | 产品需求文档（v2.7） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构设计 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 建仓、开发、文档维护指南 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更历史 |

## 项目状态

当前阶段：**核心功能实现完成，待 Alpha 测试**

- [x] PRD 确认（v2.7）
- [x] 架构设计
- [x] 后端骨架搭建
- [x] 确定性引擎核心实现（pipeline / renderer / dedup / cache）
- [x] 三阶段 RAG 检索流水线（混合检索 → ColBERT 精排 → Cross-Encoder 重排）
- [x] 前端框架搭建（生成页、意图构建器、模板库、批量处理、管理控制台）
- [x] 模板库初始化（SVA 断言 6 个 + 功能覆盖率 4 个）
- [x] 批量处理 & Celery 任务队列
- [x] LLM 多模型配置管理（Anthropic / OpenAI 兼容 / GLM / DeepSeek / Ollama）
- [x] 独立嵌入服务（BGE-M3 + BGE Reranker，支持 GPU/CPU）
- [x] Docker Compose 完整栈（含开发热重载、GPU 部署 overlay）
- [x] 部署手册（[docs/deployment.md](docs/deployment.md)）
- [ ] 单元测试与集成测试
- [ ] Alpha 测试

## License

Private — 内部使用，未授权不得分发。
