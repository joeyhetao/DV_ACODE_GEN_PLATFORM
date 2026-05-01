# 部署手册（索引）

**适用版本**：v1.0.0

平台支持两套部署场景，对应不同的读者与使用方式。**请先选择你的场景，然后跳转到对应的分册文档。**

---

## 场景对比

| 维度 | Win11 本机开发 | Linux 公司内网生产 |
|---|---|---|
| **适用读者** | 给项目改代码的开发者 / 单人测试 | IT / 运维 / DevOps |
| **OS** | Windows 11 + Docker Desktop（WSL2 后端） | Ubuntu 22.04+ / Rocky 9+ |
| **GPU** | 可选；无 GPU 时自动 CPU 小模型 | 推荐 NVIDIA GPU（不含也能跑 CPU 模式） |
| **网络** | 直连外网 | **受限外网**（用公司内部 Docker / HuggingFace / PyPI mirror） |
| **关键 compose overlay** | `docker-compose.dev.yml` + `docker-compose.hotreload.yml` | `docker-compose.gpu-linux.yml` |
| **特色能力** | hot reload 后端 + bind mount 前端 + 单条意图调试 | 模型 bind mount + 自动备份 + GPU passthrough + 反向代理 HTTPS |
| **首次部署耗时** | 5-10 分钟 | 30-60 分钟（含 mirror 配置 + 模型搬运） |
| **跳转文档** | 👉 [deployment-dev-windows.md](deployment-dev-windows.md) | 👉 [deployment-prod-linux.md](deployment-prod-linux.md) |

---

## 我应该看哪份？

- **"我在自己的 Win11 笔记本上跑这个项目改代码"** → [deployment-dev-windows.md](deployment-dev-windows.md)
- **"我把项目部署到公司服务器供团队使用"** → [deployment-prod-linux.md](deployment-prod-linux.md)
- **"我想了解整体架构 / 三阶段 RAG / LLM 流水线设计"** → [../ARCHITECTURE.md](../ARCHITECTURE.md)
- **"我要给项目贡献代码 / 提交 PR"** → [../CONTRIBUTING.md](../CONTRIBUTING.md)

---

## 两份文档的共同前提

无论哪个场景，平台的核心组件不变：

```
┌─ Frontend (React + nginx) ──────────────────────────────┐
│                                                          │
│   ↓ HTTP /api/                                           │
│                                                          │
│ ┌─ Backend (FastAPI) ─────────────────────────────────┐ │
│ │  Pipeline: normalize → RAG → LLM Step1+Step2 →     │ │
│ │            param map → Jinja2 render               │ │
│ └─────────────────────────────────────────────────────┘ │
│   │            │              │              │          │
│   ↓            ↓              ↓              ↓          │
│ PostgreSQL   Redis        Qdrant      Embedding Service │
│ (主数据)    (缓存+队列)   (向量)      (BGE-M3 + Reranker)│
│                                              │          │
│                                              ↓          │
│                                          外部 LLM API   │
│                                          (智谱/DS/Claude)│
└──────────────────────────────────────────────────────────┘
```

具体每个组件的作用、路径、数据流见 [ARCHITECTURE.md](../ARCHITECTURE.md)。
