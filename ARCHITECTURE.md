# IC验证辅助代码生成平台 — 架构设计文档（ARCHITECTURE）

**版本**：v2.10  
**状态**：已确认  
**日期**：2026-04-22  
**变更**：
- v1.0 → v2.0：引入完整 RAG 方案，向量检索由 pgvector 替换为 bge-m3 + Qdrant 三阶段检索链路
- v2.0 → v2.1：新增 Windows / Linux 双系统支持说明
- v2.1 → v2.2：输入方式由"自然语言+Excel信号表"调整为"双表格结构化输入"，新增Excel解析层与信号角色直接参数填充机制
- v2.2 → v2.3：新增模板贡献与审核机制（§3.10），包含数据库变更（contributions/notifications表）、新增 API 端点、前端页面及目录结构更新
- v2.3 → v2.4：新增四层验证意图标准化机制（§3.11），包含 LLM 静默标准化、场景构建器、上传预检、历史意图知识库；更新 RAG 链路入口、数据库字段及 API 端点
- v2.4 → v2.5：新增 LLM 多模型支持（§3.12），支持第三方模型通过 URL+API Key 接入，新增模型测试功能；更新技术栈、数据库、API 端点及目录结构
- v2.5 → v2.6：可行性评审修订——§1.1/1.2 架构图 "Claude API" 改为通用 "LLM API"；预检去除 LLM 调用（§3.11.3）；llm_configs 加 DB 部分唯一索引（§4.1）；Redis maxmemory 策略 + 生成缓存 TTL 90天（§3.6）；Celery 默认并发数 10（§3.7）；dev 环境 Embedding Service 小模型降级方案（§8.2）
- v2.6 → v2.7：新增模板入库查重机制（§3.8）——名称精确匹配 + 语义相似度检查（阈值 0.90），覆盖 Admin UI 新建、YAML 批量导入、贡献审核三条路径；更新 API 端点（§5.1）、新增 TEMPLATE_DEDUP_THRESHOLD 环境变量（§8.4）
- v2.7 → v2.8：新增数据备份与误操作保护机制（§3.13）——三层防护（操作保护/自动备份/恢复路径）；新增 admin_audit_logs 表（§4.1）；Docker Compose 新增 backup 服务（§8.1）；新增审计日志 API 端点（§5.1）；新增 BACKUP_RETAIN_DAYS / QDRANT_SNAPSHOT_ENABLED 环境变量（§8.4）
- v2.8 → v2.9：架构分层解耦优化——新增代码类型注册表（§3.14，code_types/*.yaml 驱动，零 Python 代码扩展新类型）；新增生成流水线编排器（§3.15，8步 Pipeline 统一入口）；服务层重组为 core/rag/llm/intent/parser/platform 六子包（§7）；Excel 解析改为 schema 驱动（§3.9）；意图标准化 Prompt 改为 registry 驱动（§3.11.2）；templates 表 `category` 列重命名为 `code_type`（§4.1）；Qdrant payload 同步更名（§4.2）；新增 GET /api/v1/code-types 端点（§5.1）；模板 YAML `category` 字段改为 `code_type`（§6）；data/ 目录新增 code_types/、schemas/、scenarios/ 三个子目录（§7）
- v2.9 → v2.10：模板查重机制优化——步骤 B 从 Stage1 Hybrid RRF 检索改为 dense-only 余弦相似度检索（§3.8），解决 RRF 分数缺乏可解释单位的问题；补充说明框（关键词重叠 ≠ 语义重复，dense-only 与生成链路 hybrid 两套查询独立）；更新 TEMPLATE_DEDUP_THRESHOLD 环境变量注释（§8.4）

---

## 1. 架构总览

### 1.1 确定性策略（核心设计约束）

LLM 本质上是概率性的，但平台要求输出是确定性的。完整 RAG 方案下通过以下机制维持确定性：

```
┌──────────────────────────────────────────────────────────────────────┐
│         【RAG 检索链路】                  【确定性生成链路】            │
│                                                                      │
│  用户输入                                                            │
│     ↓                                                                │
│  bge-m3 编码（固定模型版本）                                          │
│     ↓                                                                │
│  Qdrant 三阶段检索（算法确定性）                                      │
│     ↓                                                                │
│  Top-3 模板内容注入 Prompt                                           │
│     ↓                                                                │
│  LLM API（by llm_configs）→   {template_id, params}（JSON Schema）  │
│  temperature=0                         ↓                             │
│  工具调用强制输出              Pydantic 验证 + 归一化                  │
│                                        ↓                             │
│                               Redis 缓存（绝对确定性兜底）             │
│                                        ↓                             │
│                               Jinja2 渲染（100% 确定性）              │
│                                        ↓                             │
│                               SVA / UVM 代码输出                     │
└──────────────────────────────────────────────────────────────────────┘
```

**LLM 在 RAG 中的职责边界**：接收检索到的模板作为上下文，输出"选择哪个模板 + 填入哪些参数"，**不生成任何代码**。代码生成完全由 Jinja2 完成。

**四层确定性保障**：

| 层次 | 机制 | 确定性强度 |
|------|------|-----------|
| 缓存层 | Redis：input_hash → output，相同输入直接命中，跳过所有环节 | 100% 绝对确定性 |
| 检索层 | bge-m3 固定模型版本 + Qdrant 算法确定性 + ColBERT MaxSim 纯数学计算 | 算法确定性 |
| 解析层 | temperature=0 + JSON Schema 工具调用 + Pydantic 归一化 | 强约束确定性 |
| 渲染层 | Jinja2 StrictUndefined，参数缺失报错不静默 | 100% 确定性 |

---

### 1.2 系统整体架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                          用户浏览器                                   │
│                Web 前端（React + TypeScript）                         │
│   ┌──────────────┐  ┌─────────────────────┐  ┌──────────────────┐   │
│   │ 自然语言输入  │  │   Excel 信号表上传    │  │   模板库浏览      │   │
│   └──────┬───────┘  └──────────┬──────────┘  └────────┬─────────┘   │
└──────────┼────────────────────┼──────────────────────┼──────────────┘
           │                    │   HTTPS / REST API   │
           └────────────────────┼──────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│                          Nginx 反向代理                               │
│                   静态资源服务 + API 路由转发                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│                       后端应用（FastAPI）                              │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                        API 路由层                             │    │
│  │   /api/v1/generate   /api/v1/batch   /api/v1/templates       │    │
│  │   /api/v1/admin      /api/v1/auth                            │    │
│  └────────────────────────────┬─────────────────────────────────┘    │
│                               │                                       │
│  ┌────────────────────────────▼─────────────────────────────────┐    │
│  │                    RAG 检索服务                                │    │
│  │                                                              │    │
│  │  用户输入                                                     │    │
│  │    ↓ 调用 Embedding Service /embed                           │    │
│  │  dense + sparse + colbert 向量                               │    │
│  │    ↓                                                         │    │
│  │  Qdrant 混合检索（dense+sparse RRF）→ Top-100               │    │
│  │    ↓ 取 Top-100 的 colbert 向量                              │    │
│  │  ColBERT MaxSim 精排 → Top-20                               │    │
│  │    ↓ 调用 Embedding Service /rerank                          │    │
│  │  bge-reranker-v2-m3 → Top-3                                 │    │
│  │    ↓ PostgreSQL 取完整模板内容                               │    │
│  │  构建 RAG Prompt → LLM API（temp=0，by llm_configs）         │    │
│  │    ↓ {template_id, params}（JSON Schema 约束）               │    │
│  │  Pydantic 验证 + 归一化                                      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │               生成 / 渲染 / 缓存 服务                          │    │
│  │   Redis 缓存查询 → Jinja2 渲染 → Redis 写入缓存               │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │            Excel 解析 / 库管理 / 批量任务 服务                  │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────┬──────────────────┬─────────────────┬──────────────────────────┘
       │                  │                 │
┌──────▼──────┐   ┌───────▼───────┐  ┌─────▼──────┐
│   Qdrant    │   │  PostgreSQL   │  │   Redis    │
│             │   │               │  │            │
│ dense 向量  │   │ 模板元数据     │  │ 生成缓存   │
│ sparse 向量 │   │ 用户 / 权限   │  │ Celery队列 │
│ colbert向量 │   │ 生成历史       │  │            │
│             │   │ 批量任务       │  │            │
└─────────────┘   └───────────────┘  └────────────┘

┌─────────────────────────────────────────────────────────────┐
│            Embedding Service（独立容器，挂载 GPU）            │
│                                                             │
│   bge-m3（~2.5GB 显存）                                     │
│   bge-reranker-v2-m3（~1.1GB 显存）         合计 ~3.6GB     │
│                                                             │
│   POST /embed    文本 → dense + sparse + colbert 向量       │
│   POST /rerank   (query, candidates[]) → 相关性分数列表      │
└─────────────────────────────────────────────────────────────┘

                    ┌────────────────────┐
                    │   LLM API          │
                    │ （由 llm_configs   │
                    │  配置决定，外部    │
                    │   HTTPS）          │
                    └────────────────────┘
```

---

## 2. 技术栈

### 2.1 后端

| 组件 | 技术选型 | 版本要求 | 选型理由 |
|------|---------|---------|---------|
| 运行时 | Python | 3.11+ | LLM/ML 生态最完善，Anthropic SDK 原生支持 |
| Web 框架 | FastAPI | 0.110+ | 原生异步，OpenAPI 文档自动生成，性能优异 |
| 数据验证 | Pydantic v2 | 2.x | JSON Schema 强制约束，LLM 输出验证 |
| ORM | SQLAlchemy | 2.x | 成熟稳定，异步支持 |
| 数据库驱动 | asyncpg | 最新 | PostgreSQL 异步驱动 |
| 模板引擎 | Jinja2 | 3.x | 工业级，StrictUndefined 保证参数不被静默忽略 |
| LLM SDK | Anthropic Python SDK + openai SDK | 最新 | Anthropic 原生 SDK（Tool Calling）+ openai SDK 的 `base_url` 参数覆盖所有 OpenAI 兼容第三方模型 |
| 向量库客户端 | qdrant-client | 最新 | Qdrant 官方异步 Python 客户端 |
| 缓存客户端 | redis-py (async) | 最新 | Redis 异步客户端 |
| Excel 解析 | openpyxl | 最新 | 稳定的 xlsx 读写库 |
| 任务队列 | Celery + Redis | 最新 | 批量生成异步任务处理 |
| 认证 | python-jose + passlib | 最新 | JWT Token 认证 |

### 2.2 Embedding 推理服务

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| Embedding 模型 | bge-m3（BAAI/bge-m3） | 多语言，同时产出 dense / sparse / colbert 三种向量 |
| Reranker 模型 | bge-reranker-v2-m3 | Cross-Encoder 精排，与 bge-m3 同系列，配合最优 |
| 推理框架 | FlagEmbedding | BAAI 官方库，原生支持 bge-m3 三模式输出和 ColBERT MaxSim |
| 服务框架 | FastAPI | 独立 HTTP 服务，与后端解耦 |
| 运行环境 | Python + CUDA | 挂载 GPU，fp16 推理 |

**bge-m3 输出向量规格**：

| 向量类型 | 维度 | 用途 |
|---------|------|------|
| dense | 1024 维实数向量 | 句子级语义相似度（余弦距离） |
| sparse | 词汇 ID → 权重字典 | 关键词精确匹配（类 BM25） |
| colbert | N × 1024（N = token 数） | Token 级细粒度交互，MaxSim 精排 |

### 2.3 数据库与存储

| 组件 | 技术选型 | 版本 | 用途 |
|------|---------|------|------|
| 向量数据库 | Qdrant | 最新 | 存储三种向量（dense/sparse/colbert），三阶段 RAG 检索 |
| 关系型数据库 | PostgreSQL | 16 | 模板元数据、用户/权限、生成历史、批量任务 |
| 缓存 | Redis | 7 | 生成结果缓存（确定性保障）、Celery 消息队列 |

> **注**：不再使用 pgvector 扩展，向量职责完全由 Qdrant 承担，PostgreSQL 仅存储结构化数据。

### 2.4 前端

| 组件 | 技术选型 | 版本要求 | 选型理由 |
|------|---------|---------|---------|
| 框架 | React | 18+ | 成熟生态，组件化开发 |
| 语言 | TypeScript | 5.x | 类型安全，减少运行时错误 |
| 构建工具 | Vite | 最新 | 极快的开发构建速度 |
| UI 组件库 | Ant Design | 5.x | 面向 B 端，组件齐全 |
| 代码编辑器 | Monaco Editor | 最新 | VS Code 同款，支持 SystemVerilog 语法高亮 |
| HTTP 客户端 | Axios | 最新 | 成熟稳定的 HTTP 库 |
| 状态管理 | Zustand | 最新 | 轻量，适合中等复杂度状态 |

### 2.5 部署与运维

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| 容器化 | Docker + Docker Compose | 服务编排和本地开发 |
| 反向代理 | Nginx | 静态资源服务、API 路由、SSL 终止 |
| 进程管理 | Uvicorn + Gunicorn | FastAPI 生产部署 |

---

## 3. 组件详细设计

### 3.1 Embedding 推理服务

独立 GPU 容器，对外暴露两个 HTTP 接口，后端通过内网调用。

**接口设计**：

```
POST /embed
  请求：{ "texts": ["文本1", "文本2", ...], "modes": ["dense", "sparse", "colbert"] }
  响应：{
    "dense":   [[1024个float], ...],
    "sparse":  [{"token_id": weight, ...}, ...],
    "colbert": [[[1024个float] × token数], ...]
  }

POST /rerank
  请求：{ "query": "用户输入文本", "candidates": ["模板文本1", "模板文本2", ...] }
  响应：{ "scores": [0.92, 0.71, 0.55, ...] }   # 与candidates顺序对应
```

**GPU 显存估算**：

| 模型 | 显存占用 |
|------|---------|
| bge-m3（fp16） | ~2.5 GB |
| bge-reranker-v2-m3（fp16） | ~1.1 GB |
| 推理缓冲 | ~0.5 GB |
| **合计** | **~4.1 GB** |

A10 / RTX 3090（24 GB）远超需求，两个模型可共用同一 GPU。

**确定性保障**：
- 推理时关闭 dropout（`model.eval()`）
- 固定模型版本（镜像中锁定 commit hash）
- 相同输入 → 相同向量输出（IEEE 754 浮点运算确定性）

---

### 3.2 三阶段 RAG 检索引擎

完整检索链路，三个阶段逐步提升精度，同时控制计算量：

```
Excel 表格行（验证意图 + 信号角色表）
      ↓
Excel解析层（§3.9）：提取验证意图文本 + 结构化信号角色表
      ↓
意图标准化层（§3.11）
  ① 查询历史意图库（Redis精确命中 → 直接返回缓存结果，跳过后续所有步骤）
  ② 历史未命中 → Claude LLM 静默标准化（temperature=0，fixed prompt）
     原文保留（original_intent），标准化文本（normalized_intent）用于检索
      ↓
标准化意图文本 → Embedding Service /embed（dense + sparse + colbert）
      ↓
┌─────────────────────────────────────────────────────┐
│  Stage 1：Qdrant 混合检索                            │
│  输入：dense_q + sparse_q                           │
│  方法：dense 余弦相似度 + sparse 词汇匹配            │
│         RRF（Reciprocal Rank Fusion）融合两路得分    │
│  优势：dense 捕捉语义，sparse 精确匹配技术术语        │
│  输出：Top-100 候选（含 qdrant_id + payload）        │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Stage 2：ColBERT MaxSim 精排                        │
│  输入：colbert_q + Top-100 的 colbert 向量           │
│        （从 Qdrant 批量取回）                        │
│  方法：MaxSim(q, d) = Σ max_j(qi · dj) / |q|       │
│        token 级细粒度交互，区分相似意图的细微差别    │
│  输出：Top-20 候选                                   │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Stage 3：bge-reranker-v2-m3 精排                    │
│  输入：(query文本, 模板描述文本) 对                  │
│        调用 Embedding Service /rerank               │
│  方法：Cross-Encoder，联合编码 query+doc，精度最高   │
│  输出：Top-3 最终候选（template_id + score）         │
└───────────────────────┬─────────────────────────────┘
                        ↓
              PostgreSQL 取 Top-3 完整模板内容
                        ↓
              构建 RAG Prompt（含信号角色表）→ Claude API
```

**各阶段候选数量与计算说明**：

| 阶段 | 候选数 | 计算复杂度 | 特点 |
|------|-------|-----------|------|
| Qdrant 混合检索 | Top-100 | O(log N)，ANN 近似 | 速度最快，召回率高 |
| ColBERT MaxSim | Top-20 | O(100 × L_q × L_d) | 精度高，在小集合上快 |
| bge-reranker | Top-3 | O(20) 次 Cross-Encoder | 精度最高，只在 20 个上跑 |

**Stage 2 ColBERT MaxSim 计算方式**：

```python
# colbert_q: shape (L_q, 1024)  query 的 token 向量矩阵
# colbert_d: shape (L_d, 1024)  模板的 token 向量矩阵
# MaxSim 分数
sim_matrix = colbert_q @ colbert_d.T          # (L_q, L_d)
max_sim_per_query_token = sim_matrix.max(-1)  # (L_q,)
score = max_sim_per_query_token.mean()         # 标量
```

---

### 3.3 RAG Prompt 构建与 LLM 调用

**Prompt 结构**（输入来自表格行解析结果）：

```
[System]
你是资深IC验证工程师。以下是从模板库中检索到的最相关模板，
以及工程师在需求表中填写的信号信息。
请从候选模板中选择最匹配的一个，并将信号角色与模板参数对应。
严格使用工具调用输出，不要输出任何其他内容。

[工程师填写的信号信息]
时钟: clk | 复位: rst_n（低有效）| 协议: AXI4
信号列表:
  awvalid  1bit  角色=valid
  awready  1bit  角色=ready
  awaddr   32bit 角色=data

[验证意图]
awvalid拉高后awready未到来期间，awaddr必须保持稳定不变

[Context - Top-3 候选模板]
模板1：SVA-HAND-001 - Valid-Ready握手数据稳定性断言
  描述：当valid信号拉高且ready信号未到来时，数据信号必须保持稳定
  参数需求：clk(signal), rst_n(signal), valid_sig(signal), ready_sig(signal), data_sig(signal,可选)

模板2：SVA-HAND-002 - Valid-Ready响应超时检测
  描述：valid拉高后，ready必须在指定周期数内到来，否则触发断言
  参数需求：clk(signal), rst_n(signal), valid_sig(signal), ready_sig(signal), max_cycles(integer)

模板3：SVA-TIME-003 - 最大延迟约束断言
  描述：起始事件发生后，结束事件必须在最大延迟周期内发生
  参数需求：clk(signal), rst_n(signal), start_sig(signal), end_sig(signal), max_delay(integer)

[Tool Call - 强制输出格式]
select_template(template_id: str, param_mapping: dict, confidence: float)
```

**工具调用输出**（被 Pydantic 验证）：

```json
{
  "template_id": "SVA-HAND-001",
  "param_mapping": {
    "clk":       "clk",
    "rst_n":     "rst_n",
    "valid_sig": "awvalid",
    "ready_sig": "awready",
    "data_sig":  "awaddr"
  },
  "confidence": 0.95
}
```

**信号角色直接填充机制**：工具调用输出的 `param_mapping` 中，信号名直接来自表格中工程师填写的实际信号名（已标注角色），LLM 只需确认角色与模板参数的对应关系，无需猜测信号名。Jinja2 渲染时直接使用 `param_mapping`，完全确定性。

---

### 3.4 Qdrant 集合设计

```python
# Collection 结构（支持三种向量类型）
client.create_collection(
    collection_name="templates",
    vectors_config={
        "dense": VectorParams(
            size=1024,
            distance=Distance.COSINE
        ),
        "colbert": VectorParams(
            size=1024,
            distance=Distance.COSINE,
            multivector_config=MultiVectorConfig(
                comparator=MultiVectorComparator.MAX_SIM
            )
        )
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(
            index=SparseIndexParams(on_disk=False)
        )
    }
)

# 每条模板的 Payload（轻量，仅存索引用字段）
# 完整模板内容存 PostgreSQL，通过 template_id 回查
payload = {
    "template_id": "SVA-HAND-001",
    "code_type":   "assertion",
    "subcategory": "handshake",
    "protocol":    ["AXI4", "AXI4-Lite"],
    "maturity":    "production"
}
```

**模板入库时的编码文本**（拼接多个字段，提升召回覆盖）：

```
{name}。{description}。
标签：{tags joined}。关键词：{keywords joined}。
参数：{parameter descriptions joined}。
```

---

### 3.5 渲染层（Jinja2）

- 使用 `StrictUndefined`：模板中引用了未提供的参数时抛出异常，而非静默渲染空字符串
- 渲染前做参数 Schema 验证（必填项、类型检查）
- 渲染后在代码头部追加标准注释：模板 ID、版本、匹配置信度、生成时间戳

---

### 3.6 缓存层（Redis）

**缓存键设计**：

```
cache_key = SHA256(
    template_id + "|" + template_version + "|" + canonical_json(sorted params)
)
```

**缓存策略**：
- 命中：直接返回，跳过检索+LLM+渲染全部环节，100% 确定性
- 未命中：走完整链路，结果写入 Redis（TTL 90天）
- 模板更新时：批量失效该模板 ID 下所有版本的缓存条目（通过 key pattern 扫描删除）

**Redis 内存配置**（写入 `docker-compose.yml` 的 Redis 服务 command）：
```
maxmemory 2gb
maxmemory-policy allkeys-lru
```
内存达上限时自动淘汰最久未访问的条目，防止无限增长。

---

### 3.7 批量生成（Celery 异步任务）

```
上传 Excel
  ↓
创建 BatchJob（PostgreSQL，status=pending）
  ↓
每行拆分为独立 CeleryTask，加入 Redis 队列
  ↓
Celery Worker 并行处理（默认并发数 10，I/O密集型任务，通过 CELERY_WORKER_CONCURRENCY 配置）
每行走完整 RAG 链路（共享 Embedding Service + Qdrant）
  ↓
每完成一行：更新 BatchJob.completed_rows + WebSocket 推送进度
  ↓
全部完成：打包 .sv 文件为 .zip，BatchJob.status=done
  ↓
前端下载
```

---

### 3.9 Excel 表格解析层

> **架构说明**：`excel_parser.py` 是**纯通用解释器**，不含任何代码类型特定的列定义。每种代码类型的 Excel 列结构由独立 Schema YAML 文件描述（`data/schemas/sva_schema.yaml`、`data/schemas/coverage_schema.yaml`），解析器在运行时动态读取对应 Schema 完成解析。新增代码类型时只需添加 Schema YAML，无需修改 Python 代码。

#### 3.9.1 两份输入表格规范

平台接受两种固定格式的 Excel 文件（`.xlsx`），分别对应 SVA 断言需求和功能覆盖率需求。列定义分别存储于 `data/schemas/sva_schema.yaml` 和 `data/schemas/coverage_schema.yaml`，以下为 v1.0 列规范参考。

**SVA断言需求表列定义**（sheet名：`SVA需求`）：

| 列索引 | 列名 | 数据类型 | 必填 | 枚举值 |
|--------|------|---------|------|-------|
| A | 编号 | 文本 | 是 | — |
| B | 所属模块 | 文本 | 是 | — |
| C | 时钟 | 文本 | 是 | — |
| D | 复位信号 | 文本 | 是 | — |
| E | 复位极性 | 枚举 | 是 | 高有效 / 低有效 |
| F | 协议 | 枚举 | 否 | AXI4 / AHB / APB / 通用 |
| G | 信号1名称 | 文本 | 是 | — |
| H | 信号1位宽 | 整数 | 是 | — |
| I | 信号1角色 | 枚举 | 是 | valid/ready/data/state/req/ack/start/end/enable/count/other |
| J | 信号2名称 | 文本 | 否 | — |
| K | 信号2位宽 | 整数 | 否 | — |
| L | 信号2角色 | 枚举 | 否 | 同上 |
| M | 信号3名称 | 文本 | 否 | — |
| N | 信号3位宽 | 整数 | 否 | — |
| O | 信号3角色 | 枚举 | 否 | 同上 |
| P | 信号4名称 | 文本 | 否 | — |
| Q | 信号4位宽 | 整数 | 否 | — |
| R | 信号4角色 | 枚举 | 否 | 同上 |
| S | 验证意图 | 长文本 | 是 | — |
| T | 严重级别 | 枚举 | 否 | error / warning / info |
| U | 备注 | 文本 | 否 | — |
| V | **[输出]匹配模板** | 文本 | — | 系统回填 |
| W | **[输出]置信度** | 数字 | — | 系统回填 |
| X | **[输出]生成状态** | 枚举 | — | 已生成 / 需确认 / 需修改 |

**功能覆盖率需求表列定义**（sheet名：`Coverage需求`）：

| 列索引 | 列名 | 数据类型 | 必填 | 枚举值 |
|--------|------|---------|------|-------|
| A | 编号 | 文本 | 是 | — |
| B | 所属模块 | 文本 | 是 | — |
| C | 采样时钟 | 文本 | 是 | — |
| D | 复位信号 | 文本 | 是 | — |
| E | 复位极性 | 枚举 | 是 | 高有效 / 低有效 |
| F | 覆盖类型 | 枚举 | 否 | 值覆盖 / 转移覆盖 / 交叉覆盖 |
| G | 主信号名称 | 文本 | 是 | — |
| H | 主信号位宽 | 整数 | 是 | — |
| I | 主信号数据类型 | 枚举 | 是 | logic / uint / enum |
| J | 交叉信号1名称 | 文本 | 否 | — |
| K | 交叉信号1位宽 | 整数 | 否 | — |
| L | 交叉信号1数据类型 | 枚举 | 否 | logic / uint / enum |
| M | 交叉信号2名称 | 文本 | 否 | — |
| N | 交叉信号2位宽 | 整数 | 否 | — |
| O | 交叉信号2数据类型 | 枚举 | 否 | logic / uint / enum |
| P | Bin提示 | 文本 | 否 | 如 `1,2,4,8,16` 或 `0-15,>15` |
| Q | 采样条件 | 文本 | 否 | 如 `awvalid && awready` |
| R | 覆盖意图 | 长文本 | 是 | — |
| S | 备注 | 文本 | 否 | — |
| T | **[输出]匹配模板** | 文本 | — | 系统回填 |
| U | **[输出]置信度** | 数字 | — | 系统回填 |
| V | **[输出]生成状态** | 枚举 | — | 已生成 / 需确认 / 需修改 |

#### 3.9.2 解析流程（完全确定性）

```python
# 每行解析产出结构化对象，供 RAG 引擎和渲染引擎使用
class ParsedSVARow:
    row_id: str               # 编号
    module: str               # 所属模块
    clk: str                  # 时钟信号名
    rst: str                  # 复位信号名
    rst_polarity: str         # high_active / low_active
    protocol: str | None      # 协议（可选）
    signals: list[SignalInfo] # [{name, width, role}, ...]
    intent: str               # 验证意图（驱动RAG）
    severity: str             # error / warning / info

class ParsedCoverageRow:
    row_id: str
    module: str
    clk: str
    rst: str
    rst_polarity: str
    cover_type: str | None         # 覆盖类型（辅助RAG过滤）
    main_signal: SignalInfo        # 主信号
    cross_signals: list[SignalInfo]# 交叉信号列表
    bin_hint: str | None           # Bin提示
    sample_condition: str | None   # 采样条件
    intent: str                    # 覆盖意图（驱动RAG）
```

#### 3.9.3 信号角色直接参数填充

RAG 检索并由 Claude 确认模板选择后，信号角色到模板参数的映射**直接由规则完成**，无需 LLM 二次推断：

```
ParsedRow.signals = [
    {name: "awvalid", width: 1,  role: "valid"},
    {name: "awready", width: 1,  role: "ready"},
    {name: "awaddr",  width: 32, role: "data"},
]

Template.parameters = [
    {name: "valid_sig", role_hint: "valid"},
    {name: "ready_sig", role_hint: "ready"},
    {name: "data_sig",  role_hint: "data"},
    {name: "clk",       from: "row.clk"},
    {name: "rst_n",     from: "row.rst"},
]

→ 参数映射（确定性规则）：
  valid_sig = awvalid   # 角色匹配 valid
  ready_sig = awready   # 角色匹配 ready
  data_sig  = awaddr    # 角色匹配 data
  clk       = clk       # 来自 row.clk
  rst_n     = rst_n     # 来自 row.rst
```

Claude 工具调用仅用于"选择模板"，参数填充由上述规则引擎完成，实现完全确定性。

---

### 3.8 模板向量化生命周期

模板向量是**预计算、持久存储**在 Qdrant 中的，查询时只对用户输入做实时向量化。向量化由以下四种事件触发：

```
┌─────────────────────────────────────────────────────────────────┐
│  触发事件                  处理动作                              │
├─────────────────────────────────────────────────────────────────┤
│  首次部署（批量导入）      lib_manager.py import                 │
│                            全量向量化所有 YAML 模板              │
├─────────────────────────────────────────────────────────────────┤
│  运行时：新增模板          Admin UI / YAML 导入                  │
│                            单条实时向量化                        │
├─────────────────────────────────────────────────────────────────┤
│  运行时：更新模板          Admin UI 编辑提交                     │
│                            单条重新向量化 + Redis 缓存失效        │
├─────────────────────────────────────────────────────────────────┤
│  Embedding 模型替换        lib_manager.py rebuild-index          │
│                            全量重新向量化，重建 Qdrant collection │
└─────────────────────────────────────────────────────────────────┘
```

#### 首次部署：`lib_manager.py import`

```
读取 template_library/ 下所有 YAML 文件
  ↓
逐条 Pydantic Schema 校验 + Jinja2 语法验证（失败则跳过并报错）
  ↓
批量调用 Embedding Service /embed（可配置 batch_size）
  → 每条模板的编码文本 = name + description + tags + keywords + parameter descriptions
  ↓
批量写入 Qdrant（获得 qdrant_point_id）
  ↓
批量写入 PostgreSQL（含 qdrant_point_id）
  ↓
输出导入报告：成功 N 条 / 跳过 M 条（含错误原因）
```

#### 运行时：新增模板（单条实时）

```
Admin 提交模板表单 / 上传 YAML
  ↓
【查重检查】（force=true 时跳过）
  A. 名称精确匹配：SELECT FROM templates WHERE name = ?（含 is_active=false）
     命中 → 返回 HTTP 409，告知已存在同名模板，阻止入库
  B. 语义相似度：调用 Embedding Service /embed → Qdrant dense-only 检索 Top-3
     （使用 dense 向量余弦相似度，而非 hybrid RRF；理由见下方说明）
     Top-1 余弦相似度 ≥ TEMPLATE_DEDUP_THRESHOLD（默认 0.90）
     → 返回 HTTP 200 + { "status": "duplicate_warning", "similar_templates": [...] }
     → 前端展示 Modal，管理员确认后附带 force=true 重新提交，跳过本步骤
  ↓
（通过查重 或 force=true）
① Jinja2 语法验证 + Pydantic 参数 Schema 校验
② 用 dummy 参数执行一次渲染（确保模板可正常渲染）
  ↓
③ 调用 Embedding Service /embed（单条，~50ms on GPU）
  ↓
④ 写入 Qdrant → 获得 qdrant_point_id
  ↓
⑤ 写入 PostgreSQL（含 qdrant_point_id，sync_status=ok）
```

**YAML 批量导入的查重行为**：`lib_manager.py import` 对每条模板逐一执行查重（步骤 A + B），命中则跳过并在导入报告中记录：
```
成功导入：42 条
跳过（同名已存在）：2 条 — SVA-HAND-003, COV-VAL-001
跳过（语义相似，相似度 ≥ 0.90）：1 条 — 与 SVA-HAND-001 相似度 0.93
失败（语法错误）：1 条 — SVA-FSM-005（第23行 Jinja2 语法错误）
```
可使用 `lib_manager.py import --force` 跳过语义相似检查（同名仍阻止）。

> **为何查重使用 Dense-only 而非 Hybrid RRF**：
> - Stage1 RAG 的 Hybrid RRF 融合了 dense（语义）+ sparse（关键词 BM25）两路分数，目的是提高检索召回率，但 RRF 分数没有固定的语义单位，不适合作为阈值比较。
> - 查重场景需要度量的是"两个模板是否在语义层面描述同一件事"，这正是 dense 向量余弦相似度所表达的含义（0–1，0.90 = 90% 语义相近），而关键词重叠（sparse）可能因共用相同信号名而虚高，导致误报重复。
> - 因此查重专用 Qdrant 查询使用 `using="dense"`，生成流水线的 Stage1 RAG 仍使用 hybrid RRF 以保证召回率，两者独立。

#### 运行时：更新模板（需保证两库一致性）

PostgreSQL 与 Qdrant 是两个独立写操作，需处理部分失败场景：

```
Admin 提交编辑
  ↓
① UPDATE PostgreSQL（新内容 + 版本号 +1，sync_status=syncing）
② 在 template_versions 插入旧版本快照
  ↓
③ DELETE Qdrant 旧 point（通过旧 qdrant_point_id）
④ INSERT Qdrant 新 point → 获得新 qdrant_point_id
  ↓
⑤ UPDATE PostgreSQL.qdrant_point_id = 新 point_id，sync_status=ok
  ↓
⑥ 删除 Redis 中该模板所有版本的缓存条目

任意步骤失败
  → sync_status = sync_error，记录失败步骤
  → 管理员在 Admin UI 可见"同步异常"标记
  → 执行 lib_manager.py repair --id SVA-HAND-001 修复
```

#### Embedding 模型替换：`lib_manager.py rebuild-index`

更换 bge-m3 版本后，旧向量与新模型不兼容，需全量重建：

```
① 创建新 Qdrant collection（临时命名，如 templates_new）
② 全量重新调用 /embed（新模型）→ 写入 templates_new
③ 原子切换：将 QDRANT_COLLECTION 环境变量指向 templates_new
④ 删除旧 collection（templates_old）
⑤ 更新 PostgreSQL 中所有 qdrant_point_id（指向新 collection 中的 point）
```

使用蓝绿切换而非原地更新，保证重建过程中服务不中断。

#### 查询时（用户发起生成请求）

```
用户输入文本
  ↓
实时调用 Embedding Service /embed（~50ms）
  ↓
用预存模板向量做三阶段检索
（模板向量静止在 Qdrant，不在查询时更新）
```

---

### 3.10 模板贡献服务

#### 3.10.1 贡献提交

```
POST /api/v1/contributions
  ↓
ContributionCreate Schema 验证（Pydantic）
  - demo_code：Jinja2 语法预检（只检查语法，不验证参数完整性）
  - description 非空校验（RAG 向量化依赖此字段）
  ↓
写入 template_contributions（status=pending_review）
  ↓
返回 contribution_id + status
```

#### 3.10.2 批准入库流水线

复用现有 `create_template()` 服务，保证入库逻辑与管理员直接新建模板完全一致：

```
PUT /api/v1/admin/contributions/{id}/approve
  ↓
① 读取 contribution 记录，验证 status 为 pending_review 或 under_review
② 管理员可在请求体中传入修改后的 demo_code / description / keywords
   （支持审核时直接补全）
  ↓
【查重结果提示】（非阻断，仅展示）
   查重在审核详情面板加载时已预计算（GET /api/v1/admin/contributions/{id} 时顺带执行）
   管理员点击「批准并入库」时，若 Top-1 相似度 ≥ TEMPLATE_DEDUP_THRESHOLD：
   - 按钮上方展示黄色提示："注意：库中已有相似模板 SVA-HAND-001（相似度 0.93）"
   - 管理员可点击跳转对比，或直接确认入库（操作日志记录"已知相似仍批准"）
  ↓
③ 组装 TemplateCreateRequest（复用现有 Schema）：
   id = 系统自动分配（category + 序号，如 SVA-HAND-047）
   template_body = contribution.demo_code（或审核时修改版）
   description = contribution.description（或修改版）
   …
  ↓
④ 调用 create_template()（含以下步骤）：
   a. Jinja2 语法验证
   b. Pydantic 参数 Schema 校验
   c. dummy 参数渲染测试（确保模板可正常渲染）
   d. 调用 Embedding Service /embed → 向量
   e. 写入 Qdrant
   f. 写入 PostgreSQL（sync_status=ok）
  ↓
⑤ UPDATE template_contributions：
   status = approved
   promoted_template_id = 新模板 ID
   reviewer_id = 审核者 ID
   updated_at = now()
  ↓
⑥ 写入 notifications（贡献者站内通知）
```

#### 3.10.3 退回 / 请求修改

```
PUT /api/v1/admin/contributions/{id}/reject
PUT /api/v1/admin/contributions/{id}/request-revision
  ↓
UPDATE template_contributions：
  status = rejected | needs_revision
  reviewer_comment = 必填意见
  reviewer_id = 审核者 ID
  ↓
写入 notifications（通知贡献者查看意见）
```

贡献者收到"需修改"通知后，可重新编辑并提交，status 回到 `pending_review`，进入新一轮审核。

#### 3.10.4 贡献服务文件位置

```
backend/app/
├── models/
│   ├── contribution.py          # TemplateContribution SQLAlchemy 模型
│   └── notification.py          # Notification 模型
├── schemas/
│   ├── contribution.py          # ContributionCreate / ContributionResponse / ContributionAdminView
│   └── notification.py          # NotificationResponse
├── api/v1/endpoints/
│   ├── contributions.py         # 贡献者端点（提交/查看/修改）
│   └── admin_contributions.py   # 管理员审核端点
├── services/
│   └── contribution_service.py  # 贡献入库流水线（调用 create_template()）
└── migrations/
    └── 003_add_contributions_and_notifications.sql
```

### 3.11 验证意图标准化服务

#### 3.11.1 四层协作流程

```
用户意图原文
     ↓
┌──────────────────────────────────────────────────────┐
│  Layer 4：历史意图精确匹配                             │
│  key = SHA256(normalized_intent)                     │
│  Redis HGET intent_cache:{hash} → 命中则直接返回      │
│                 template_id + params（跳过 RAG）      │
└──────────────────┬───────────────────────────────────┘
                   ↓ 未命中
┌──────────────────────────────────────────────────────┐
│  Layer 1：LLM 静默标准化                              │
│  调用 Claude（temperature=0）                         │
│  fixed system prompt（见下方）                        │
│  输出：normalized_intent（固定格式自然语言）           │
└──────────────────┬───────────────────────────────────┘
                   ↓
           三阶段 RAG 检索（§3.2）
                   ↓
       写入历史意图库（PostgreSQL + Redis）
```

#### 3.11.2 LLM 标准化 Prompt（注册表驱动，运行时动态组装）

> **架构说明**：System Prompt 中的标准句式规则**不再硬编码**于 Python 代码，而是由 `CodeTypeRegistry` 在启动时从 `data/code_types/*.yaml` 的 `normalization_pattern` 字段读取，动态组装注入 Prompt。新增代码类型时，其对应的标准化句式随 YAML 注册自动生效，无需修改 Python 代码。

```
[System - 运行时动态组装，句式规则来自 CodeTypeRegistry]
你是IC验证领域专家。将用户提供的验证意图改写为标准句式。

规则：
{registry_rules}   ← 由 CodeTypeRegistry 动态注入，例如：
  1. SVA断言意图（code_type=assertion）→ 格式："当 [触发条件] 时，[验证对象] 必须 [约束内容]"
  2. UVM功能覆盖率意图（code_type=coverage）→ 格式："覆盖 [信号名] 在 [场景/条件] 下的 [覆盖类型]"
{n}. 只改表达方式，不改变语义
{n+1}. 如果无法判断类型，输出原文
{n+2}. 输出一句话，不加任何解释

[User]
{original_intent}
```

确定性保证：
- `temperature=0`：相同输入 → 相同输出
- `max_tokens=128`：限制输出长度，避免发散
- 标准化结果写入 `generation_records.normalized_intent` 审计

#### 3.11.3 上传前置信度预检服务

预检是批量生成前的可选步骤，**完全不调用 LLM**，只跑 Stage1 Qdrant 混合检索，响应快（全表 5-10s）：

```
POST /api/v1/batch/preflight
  请求：{ "job_id": "xxx" }（Excel 已上传，解析完毕）
  ↓
  对每行意图（原始文本，不做 LLM 标准化）：
    ① 原始意图文本 → Embedding Service /embed（dense + sparse）
    ② 仅做 Stage1 Qdrant 混合检索 → Top-3
    ③ 取 Top-1 score 作为预估置信度
    ④ Top-1 模板名称作为改写建议参考
  ↓
  响应：[
    { "row_id": "SVA-001", "estimated_confidence": 0.83, "top_match": null },
    { "row_id": "SVA-003", "estimated_confidence": 0.42,
      "top_match": { "template_id": "SVA-DATA-002", "name": "FIFO写入读出数据匹配断言" } }
  ]
```

**说明**：
- 预检置信度基于原始意图文本（未经 LLM 标准化），是粗估值，与正式生成结果可能有偏差（正式生成经标准化后置信度通常更高）
- `top_match` 字段展示最近似的模板名称，引导工程师判断意图是否描述准确
- 正式生成时才执行 LLM 标准化，预检不涉及 LLM 调用

#### 3.11.4 历史意图知识库

**存储设计**：

`generation_records` 表新增字段（见 §4.1）：
- `original_intent`：用户原始意图文本
- `normalized_intent`：LLM 标准化后文本
- `intent_hash`：`SHA256(normalized_intent)`，用于精确匹配

**Redis 缓存层**（毫秒级历史命中）：
```
key:   intent_cache:{intent_hash}
value: {template_id, param_mapping, confidence, generated_code}
TTL:   无（历史知识库为知识积累，永久有效，由 allkeys-lru 策略兜底淘汰）
失效:  仅当模板被停用/更新时，批量删除相关 intent_cache 条目
```

**历史命中流程**：
```
新请求 intent → SHA256(normalized_intent) → Redis HGET
  命中 → 直接返回（cache_hit=true，跳过 RAG + LLM，100% 确定性）
  未命中 → 走完整 RAG 链路 → 成功后写入 Redis
```

#### 3.11.5 场景构建器 API

```
GET  /api/v1/intent-builder/scenarios
     响应：SVA 和 Coverage 的场景类型列表及各场景的参数字段定义

POST /api/v1/intent-builder/generate
     请求：{ "scenario_type": "handshake_stable",
             "params": { "valid": "awvalid", "ready": "awready", "data": "awaddr" } }
     响应：{ "intent_text": "当 awvalid 有效且 awready 未响应时，awaddr 必须保持稳定" }
```

场景构建器完全确定性（字符串模板填充），无 LLM 调用。

#### 3.11.6 文件位置（服务层重组后）

```
backend/app/
├── services/
│   ├── intent/                  # 意图相关服务聚合子包（新结构）
│   │   ├── normalizer.py        # LLM标准化服务（第1层，读 registry 获取句式）
│   │   ├── builder.py           # 场景构建器（第2层，纯字符串模板，读 registry 获取场景）
│   │   ├── preflight.py         # 上传预检服务（第3层）
│   │   └── history.py           # 历史意图库读写（第4层）
│   └── registry.py              # CodeTypeRegistry（启动时加载 data/code_types/*.yaml）
├── api/v1/endpoints/
│   ├── batch.py                 # /batch/preflight 端点
│   └── intent_builder.py        # 场景构建器端点
└── data/
    ├── code_types/              # 代码类型注册配置
    │   ├── assertion.yaml       # SVA断言类型定义
    │   └── coverage.yaml        # UVM覆盖率类型定义
    ├── schemas/                 # Excel 列定义（schema 驱动解析器）
    │   ├── sva_schema.yaml      # SVA断言 Excel 列规范
    │   └── coverage_schema.yaml # 覆盖率 Excel 列规范
    └── scenarios/               # 场景句式模板（各类型独立文件）
        ├── assertion_scenarios.yaml
        └── coverage_scenarios.yaml
```

### 3.12 LLM 多模型支持

#### 3.12.1 统一协议选择

所有第三方模型均以 **OpenAI-compatible API** 格式接入：`POST {base_url}/v1/chat/completions`。
使用 `openai` Python SDK，通过 `base_url` + `api_key` 参数即可覆盖 DeepSeek、Qwen、Ollama、vLLM 等所有兼容实现。
Anthropic Claude 保留原生 SDK 路径（Tool Calling 能力更强、更可靠）。

#### 3.12.2 客户端抽象层

```
services/llm/
├── base.py                   # LLMClient 抽象基类
│   ├── complete(system, user) → str       # 意图标准化调用
│   └── select_template(prompt) → dict    # 模板选择调用（返回 JSON）
├── anthropic_client.py       # Anthropic 原生 SDK 实现
├── openai_compat_client.py   # openai SDK + base_url 实现
└── factory.py                # 读 llm_configs 表，按 is_default 实例化
```

**factory.py 逻辑**：

```
读取 PostgreSQL llm_configs WHERE is_default=true AND is_active=true
  provider == "anthropic"        → AnthropicClient(config)
  provider == "openai_compatible" → OpenAICompatClient(config)
  无记录                          → 抛出 RuntimeError，提示管理员配置模型
```

#### 3.12.3 结构化输出降级策略

模板选择需要严格 JSON 输出。不同模型能力不同，按 `output_mode` 字段选择策略：

| output_mode | 适用模型 | 实现方式 |
|-------------|---------|---------|
| `tool_calling` | Claude、GPT-4o、DeepSeek-V3 | `tools` 参数，强制结构化输出，最可靠 |
| `json_mode` | 大多数主流模型 | `response_format: {"type": "json_object"}`，Pydantic 验证 |
| `prompt_json` | 能力较弱模型 | System prompt 注入 JSON 格式要求，Pydantic 验证，失败自动 retry 一次 |

#### 3.12.4 API Key 安全存储

- 存储时使用 **AES-256-GCM** 加密，密钥来自环境变量 `LLM_KEY_ENCRYPTION_SECRET`
- GET 接口只返回 `api_key_hint: "sk-...****"`（前4位 + 掩码），不返回明文
- PUT 接口中 `api_key` 字段为空字符串则不更新，保留原密文

#### 3.12.5 模型测试服务

```
POST /api/v1/admin/llm/configs/{id}/test
  test_type: "basic" | "normalization" | "template_selection"
           ↓
  basic:
    发送 {"role":"user","content":"Hello"}
    验证：HTTP 200 + 非空响应文本
    记录：latency_ms
           ↓
  normalization:
    固定测试意图："awvalid拉高后data不能变"
    调用 complete(system=固定标准化prompt, user=测试意图)
    验证：输出包含 "当" 或 "覆盖"（基础句式检查）
           ↓
  template_selection:
    固定 RAG Prompt（含2个虚拟模板）
    调用 select_template(固定prompt)
    验证：Pydantic TemplateSelectionResult 解析通过
           ↓
  响应：{
    success: bool,
    latency_ms: int,
    checks: {connectivity, format_valid, pydantic_valid},
    preview: "响应文本前100字",
    error: "错误信息 | null"
  }
```

#### 3.12.6 切换模型对确定性的影响

切换默认模型后，Redis 意图缓存（`intent_cache:*`）和生成结果缓存（`cache:*`）均**自动失效**：

```
PUT /api/v1/admin/llm/configs/{id}/set-default
  ↓
① UPDATE llm_configs SET is_default=false（旧默认）
② UPDATE llm_configs SET is_default=true（新默认）
③ Redis FLUSHDB_PATTERN "intent_cache:*"（意图标准化缓存，新模型可能产生不同归一化）
④ Redis FLUSHDB_PATTERN "cache:*"（生成结果缓存，依赖 LLM 选择结果）
⑤ 写入 admin 操作日志
```

新旧模型对同一输入可能选择不同模板，清空缓存确保切换后行为一致。

---

### 3.14 代码类型注册表（Code Type Registry）

#### 3.14.1 设计动机

SVA 断言和 UVM 覆盖率两种代码类型的专属逻辑（列定义、信号角色、意图标准化句式、场景模板）当前散落在多处 Python 代码中，增加新类型需要修改多个文件。

通过引入代码类型注册表，将所有类型专属逻辑迁移至纯配置文件：

**增加新代码类型 = 新增 3 个 YAML 文件，零 Python 代码变更**

#### 3.14.2 代码类型定义文件规范

```
backend/data/code_types/
├── assertion.yaml     # SVA 断言类型定义
└── coverage.yaml      # UVM 功能覆盖率类型定义
```

**code_types/assertion.yaml**（完整字段）：

```yaml
id: assertion
display_name: SVA断言
excel_sheet_name: SVA需求
excel_schema_file: schemas/sva_schema.yaml     # Excel 列定义文件
signal_roles:
  - valid
  - ready
  - data
  - state
  - req
  - ack
  - start
  - end
  - enable
  - count
  - other
normalization_pattern: "当 [触发条件] 时，[验证对象] 必须 [约束内容]"
scenario_templates_file: scenarios/assertion_scenarios.yaml
subcategories:
  - handshake
  - timing
  - fsm
  - data_integrity
  - bus_protocol
  - reset
  - counter
  - arbitration
```

**Excel Schema 文件规范**（`data/schemas/sva_schema.yaml`）：

```yaml
fields:
  - col: A
    field_key: row_id
    name: 编号
    type: text
    required: true
  - col: C
    field_key: clk
    name: 时钟
    type: text
    required: true
  - col: S
    field_key: intent
    name: 验证意图
    type: text
    required: true
  # ... 其余字段同理
signals:
  start_col: G       # 信号列起始列（G=信号1名称）
  max_count: 4       # 最多 4 组信号
  cols_per_signal: 3 # 每组 3 列：名称、位宽、角色
```

#### 3.14.3 registry.py 服务

`registry.py` 在应用启动时加载 `data/code_types/` 下所有 YAML 文件，运行时只读：

```python
class CodeTypeRegistry:
    def get(self, code_type_id: str) -> CodeTypeDefinition
    def list_all(self) -> list[CodeTypeDefinition]
    def get_signal_roles(self, code_type_id: str) -> list[str]
    def get_normalization_pattern(self, code_type_id: str) -> str
    def get_excel_schema(self, code_type_id: str) -> ExcelSchema
```

各服务通过依赖注入获取 `CodeTypeRegistry` 实例，不再硬编码类型判断：

- `excel_parser.py`：从 `registry.get_excel_schema(code_type)` 读取列定义
- `intent/normalizer.py`：从 `registry.get_normalization_pattern(code_type)` 读取句式
- `intent/builder.py`：从 `registry.get(code_type).scenario_templates_file` 加载场景

#### 3.14.4 新增 API 端点

```
GET /api/v1/code-types
  响应：[
    { "id": "assertion", "display_name": "SVA断言",
      "signal_roles": ["valid","ready","data",...],
      "subcategories": ["handshake","timing",...] },
    { "id": "coverage",  "display_name": "UVM功能覆盖率", ... }
  ]
```

前端通过此端点动态获取类型列表，单条生成页面的"代码类型"下拉和信号角色选项均由后端驱动，新增代码类型时前端**无需任何改动**。

---

### 3.15 生成流水线编排器（Generation Pipeline）

#### 3.15.1 设计动机

当前生成流程（7-8 步）的调用链路分散在端点层、多个 service 文件之间，没有明确的入口点和步骤边界。这导致：整体流程难以追踪、单步难以独立测试、插入新步骤需要修改多处代码。

引入 `services/core/pipeline.py` 作为唯一编排者，端点层只调用 `pipeline.run()`。

#### 3.15.2 统一请求/响应接口

```python
@dataclass
class GenerationRequest:
    code_type: str         # "assertion" | "coverage" | ...（registry 中注册的 id）
    intent: str            # 用户填写的验证意图原文
    clk: str               # 时钟信号
    rst: str               # 复位信号
    rst_polarity: str      # "high_active" | "low_active"
    protocol: str | None   # 可选协议过滤
    signals: list[SignalInfo]  # [{name, width, role}, ...]（最多4条）
    extra_fields: dict     # 代码类型专属字段（coverage的bin_hint等）

@dataclass
class GenerationResult:
    status: str            # "generated" | "needs_selection" | "low_confidence"
    code: str | None
    template_id: str | None
    template_version: str | None
    confidence: float
    rag_candidates: list
    params_used: dict
    cache_hit: bool
    intent_cache_hit: bool
    normalized_intent: str
```

#### 3.15.3 8 步流水线

```
GenerationPipeline.run(request: GenerationRequest) → GenerationResult

Step 1: CacheLookup
  输入：request → cache_key = SHA256(code_type + normalized_intent + signals_canonical)
  命中 → 直接返回，流水线结束
  未命中 → 进入 Step 2

Step 2: IntentNormalize
  读取 registry.get_normalization_pattern(request.code_type)
  调用 LLM.complete(system=固定prompt+句式, user=request.intent)
  输出：normalized_intent（temperature=0，确定性）

Step 3: Embed
  调用 Embedding Service /embed（dense + sparse + colbert）
  输出：三种向量

Step 4: RAGRetrieve
  Stage1 Qdrant 混合检索（code_type 作为主过滤条件，protocol 作为次过滤）
  Stage2 ColBERT MaxSim 精排
  Stage3 bge-reranker 精排
  输出：Top-3 候选模板（template_id + score）

Step 5: TemplateSelect
  从 PostgreSQL 取 Top-3 完整模板内容
  调用 LLM.select_template(rag_prompt)（工具调用，JSON Schema 约束）
  输出：{template_id, param_mapping, confidence}

Step 6: ParamMap
  从 template.parameters 中读取 role_hint
  通过角色规则引擎将 request.signals 映射至模板参数
  clk/rst 直接从 request 填充
  extra_fields 通过 field_key 直接填充
  输出：最终 params_used

Step 7: Render
  Jinja2 StrictUndefined 渲染
  输出：code（确定性字符串）

Step 8: CacheWrite
  写入 Redis（TTL 90天）
  写入 generation_records（PostgreSQL）
  写入 intent_cache（历史意图库，无 TTL）
```

#### 3.15.4 端点层变薄

端点层仅负责：HTTP 请求解析 → 构造 `GenerationRequest` → 调用 `pipeline.run()` → HTTP 响应序列化，不含任何业务逻辑。批量任务（Celery）的每行处理也调用同一个 `pipeline.run()`，与单条生成共享完全相同的代码路径。

---

### 3.13 数据备份与恢复机制

#### 3.13.1 数据分层与备份优先级

| 存储 | 性质 | 备份优先级 | 理由 |
|------|------|-----------|------|
| PostgreSQL | **主数据源** | 必须 | 模板内容、用户、生成历史等全部原始数据 |
| Qdrant | **派生数据** | 次要（可选） | 可由 PostgreSQL 完整重建，备份仅为加速恢复 |
| Redis | **临时数据** | 不需要 | 缓存可重新生成，Celery 队列允许丢失 |

#### 3.13.2 PostgreSQL 自动备份

由 Docker Compose 中独立的 `backup` 服务驱动，定时执行 `pg_dump`：

```
每天凌晨 02:00（自动）
  ↓
pg_dump --format=custom --compress=9
  输出：/backups/backup_YYYYMMDD.dump
  ↓
自动删除 BACKUP_RETAIN_DAYS（默认7）天前的备份文件
  保留最近 7 份，约占用空间：模板库 100 条时 ~10MB/份
```

备份文件存储于命名 Docker volume `postgres_backups`，挂载到宿主机持久化目录。

#### 3.13.3 Qdrant 快照（可选，加速恢复）

```
每周日凌晨 03:00（QDRANT_SNAPSHOT_ENABLED=true 时启用）
  ↓
POST http://qdrant:6333/collections/templates/snapshots
  ↓
保留最新 2 个快照，旧快照自动删除
  存储于命名 volume qdrant_snapshots
```

若 Qdrant 数据损坏，有快照时直接恢复（分钟级）；无快照时通过 `lib_manager.py rebuild-index` 从 PostgreSQL 重建（取决于模板数量，通常 < 30 分钟）。

#### 3.13.4 Template YAML 导出（人工可读快照）

```
lib_manager.py export-yaml --output ./backup/YYYY-MM-DD/
  ↓
  遍历 PostgreSQL 中所有 is_active=true 的模板
  按分类目录结构写出 YAML 文件
  ↓
  输出：
    已导出 42 条 → ./backup/2026-04-22/
    assertions/handshake/SVA-HAND-001.yaml
    assertions/timing/SVA-TIME-001.yaml
    ...
```

导出产物可提交 Git，形成人工可读的版本快照，也可作为 `lib_manager.py import` 的输入恢复模板。

#### 3.13.5 恢复场景与操作路径

| 场景 | 恢复操作 | 预估耗时 |
|------|---------|---------|
| 误停用少量模板 | Admin UI → 模板列表 → 重新启用（`is_active=false → true`） | 分钟级 |
| 误修改模板内容 | Admin UI → 模板版本历史 → 回滚至指定版本 | 分钟级 |
| 批量导入了错误数据 | `lib_manager.py restore-pg --date YYYY-MM-DD` 恢复到导入前的备份；或手动删除错误条目后重新导入正确 YAML | 分钟～小时 |
| PostgreSQL 数据损坏/误删表 | `lib_manager.py restore-pg --date YYYY-MM-DD`（全量恢复至最近备份点） | 小时级 |
| Qdrant 数据损坏 | 优先：Qdrant 快照恢复（若已启用）；否则：`lib_manager.py rebuild-index` | 分钟～小时 |

#### 3.13.6 lib_manager.py 完整命令列表

```
lib_manager.py import [--dry-run] [--force]
  # --dry-run：预检模式，输出变更预览，不写入数据库
  # --force：跳过语义相似查重（同名仍阻止）

lib_manager.py export-yaml [--output DIR]
  # 将所有活跃模板导出为 YAML 文件（新增）
  # 默认输出到 ./template_library/

lib_manager.py restore-pg --date YYYY-MM-DD
  # 从指定日期的 pg_dump 备份恢复 PostgreSQL（新增）
  # 执行前要求二次确认，因为会覆盖当前数据

lib_manager.py rebuild-index
  # 从 PostgreSQL 全量重建 Qdrant 向量索引（已有）

lib_manager.py repair --id TEMPLATE_ID
  # 修复指定模板的 PG↔Qdrant 同步异常（已有）
```

#### 3.13.7 操作保护措施

**批量导入 Dry-Run 流程**：
```
lib_manager.py import template_library/ --dry-run
  ↓
  执行校验 + 查重（不写入）
  输出预览报告：
    待新增：38 条
    待跳过（查重命中）：3 条
    校验失败（Jinja2语法错误）：1 条 — SVA-FSM-005（第23行）
  ↓
  操作建议：修复校验失败后，去掉 --dry-run 参数正式执行
```

**Admin UI 危险操作二次确认**：
- 停用模板：展示"该模板累计被使用 N 次，停用后新任务无法匹配，是否确认停用？"
- 批量导入：先展示 dry-run 预览报告，确认后才触发正式导入

**审计日志自动记录**：
所有管理员写操作（模板增删改、贡献审核、LLM配置变更、用户角色修改）自动写入 `admin_audit_logs` 表，超管可通过 `/api/v1/admin/audit-logs` 端点查询，支持按操作人、操作类型、时间范围过滤。

---

## 4. 数据库设计

### 4.1 PostgreSQL 表结构

**templates（模板表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(32) | 主键，格式如 `SVA-HAND-001` |
| version | VARCHAR(16) | 语义版本号，如 `1.0.0` |
| name | VARCHAR(128) | 模板名称 |
| code_type | ENUM | `assertion` / `coverage`（对应 CodeTypeRegistry 中已注册类型的 `id`） |
| subcategory | VARCHAR(64) | 子分类 |
| protocol | VARCHAR[] | 适用协议列表 |
| tags | VARCHAR[] | 标签列表 |
| keywords | VARCHAR[] | 中英文关键词 |
| description | TEXT | 详细描述 |
| parameters | JSONB | 参数定义列表 |
| template_body | TEXT | Jinja2 模板代码 |
| maturity | ENUM | `draft` / `validated` / `production` |
| is_active | BOOLEAN | 是否启用 |
| related_ids | VARCHAR[] | 关联模板 ID 列表 |
| qdrant_point_id | UUID | 对应 Qdrant 中的 point ID（用于向量更新/删除） |
| sync_status | ENUM | `ok` / `syncing` / `sync_error`，标识 PG 与 Qdrant 的同步状态 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 最后更新时间 |
| created_by | UUID | 创建者用户 ID |

> **注**：不再有 `embedding VECTOR` 字段，向量数据存于 Qdrant，通过 `qdrant_point_id` 关联。`sync_status` 用于检测 PostgreSQL 与 Qdrant 之间的数据一致性异常。

**template_versions（模板版本历史表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| template_id | VARCHAR(32) | 关联模板 ID |
| version | VARCHAR(16) | 版本号 |
| snapshot | JSONB | 该版本完整模板快照 |
| change_note | TEXT | 变更说明 |
| created_at | TIMESTAMP | 版本创建时间 |
| created_by | UUID | 操作用户 |

**generation_records（生成历史表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | UUID | 操作用户 |
| original_intent | TEXT | 用户填写的原始意图文本（审计用） |
| normalized_intent | TEXT | LLM 标准化后的意图文本（实际用于 RAG） |
| intent_hash | VARCHAR(64) | SHA256(normalized_intent)，用于历史知识库精确匹配 |
| rag_top3 | JSONB | RAG 检索的 Top-3 候选（template_id + score） |
| template_id | VARCHAR(32) | 最终选择的模板 ID |
| template_version | VARCHAR(16) | 所用模板版本 |
| params_used | JSONB | 实际填充的参数 |
| output_code | TEXT | 生成的代码 |
| confidence | FLOAT | 最终匹配置信度 |
| cache_hit | BOOLEAN | 是否命中 Redis 缓存（含历史意图库命中） |
| intent_cache_hit | BOOLEAN | 是否命中历史意图知识库（区分普通缓存） |
| created_at | TIMESTAMP | 生成时间 |

索引：`intent_hash`（历史意图库查询）、`user_id`（用户历史查询）

**users（用户表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| username | VARCHAR(64) | 登录名 |
| email | VARCHAR(256) | 邮箱 |
| hashed_password | VARCHAR | 密码哈希 |
| role | ENUM | `user` / `lib_admin` / `super_admin` |
| is_active | BOOLEAN | 账号状态 |
| created_at | TIMESTAMP | 注册时间 |

**batch_jobs（批量任务表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | UUID | 操作用户 |
| status | ENUM | `pending` / `running` / `done` / `failed` |
| total_rows | INT | 总行数 |
| completed_rows | INT | 已完成行数 |
| result_url | VARCHAR | 打包文件下载地址 |
| created_at | TIMESTAMP | 任务创建时间 |
| completed_at | TIMESTAMP | 任务完成时间 |

**llm_configs（LLM 模型配置表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | VARCHAR(64) | 显示名称，如 `DeepSeek-V3`、`本地Qwen2.5` |
| provider | VARCHAR(32) | `anthropic` / `openai_compatible` |
| base_url | VARCHAR(256) | API 地址；Anthropic 原生可为空（使用 SDK 默认） |
| api_key_encrypted | TEXT | AES-256-GCM 加密存储 |
| model_id | VARCHAR(128) | 模型标识，如 `deepseek-chat`、`claude-sonnet-4-6` |
| output_mode | VARCHAR(32) | `tool_calling` / `json_mode` / `prompt_json` |
| temperature | FLOAT | 默认 0.0 |
| max_tokens | INT | 默认 512 |
| is_active | BOOLEAN | 是否启用 |
| is_default | BOOLEAN | 是否为当前默认（同时只允许一条为 true） |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |

约束：`is_default=true` 的记录全表最多一条，由 PostgreSQL 部分唯一索引强制保证：
```sql
CREATE UNIQUE INDEX uq_llm_configs_one_default
ON llm_configs (is_default)
WHERE is_default = true;
```
`set-default` 操作在事务内执行：先将旧默认置为 `false`，再将新默认置为 `true`。

**template_contributions（模板贡献表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| contributor_id | UUID | 贡献者用户 ID（FK → users.id） |
| code_type | VARCHAR(16) | `assertion` / `coverage` |
| original_intent | TEXT | 来自 Excel 的验证意图原文 |
| original_row_json | JSONB | Excel 整行数据快照（供审核时参考背景） |
| template_name | VARCHAR(128) | 贡献者填写的模板名称 |
| category | VARCHAR(64) | 分类 |
| subcategory | VARCHAR(64) | 子分类 |
| protocol | VARCHAR(64) | 协议 |
| demo_code | TEXT | 贡献的 Jinja2 模板代码（含占位符） |
| description | TEXT | 自然语言描述（将用于 RAG 向量化） |
| keywords | TEXT[] | 关键词列表 |
| parameter_defs | JSONB | 参数定义列表：`[{role, param_name, required}, ...]` |
| status | VARCHAR(32) | `pending_review` / `under_review` / `needs_revision` / `approved` / `rejected` |
| reviewer_id | UUID | 审核者用户 ID（FK → users.id，可空） |
| reviewer_comment | TEXT | 审核意见（退回/请求修改时必填） |
| promoted_template_id | VARCHAR(32) | 批准后生成的模板 ID（如 `SVA-HAND-047`，可空） |
| created_at | TIMESTAMPTZ | 提交时间 |
| updated_at | TIMESTAMPTZ | 最后更新时间 |

索引：`status`（状态筛选）、`contributor_id`（我的贡献）

**notifications（站内通知表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | UUID | 接收者用户 ID（FK → users.id） |
| type | VARCHAR(32) | `contribution_approved` / `contribution_rejected` / `needs_revision` |
| payload | JSONB | `{contribution_id, template_id, comment}` |
| is_read | BOOLEAN | 是否已读（默认 false） |
| created_at | TIMESTAMPTZ | 创建时间 |

前端以 30s 轮询 `/api/v1/notifications` 获取未读数量，不引入 WebSocket，保持架构简单。

**admin_audit_logs（管理员操作审计日志表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| operator_id | UUID | 操作者用户 ID（FK → users.id） |
| action | VARCHAR(64) | 操作类型：`template_create` / `template_update` / `template_deactivate` / `template_import` / `contribution_approve` / `contribution_reject` / `llm_config_change` / `user_role_change` |
| target_type | VARCHAR(32) | 操作对象类型：`template` / `contribution` / `user` / `llm_config` |
| target_id | VARCHAR(64) | 操作对象 ID（如模板ID、用户ID） |
| detail | JSONB | 变更详情，含 `before` 和 `after` 快照（更新/停用操作时填充） |
| created_at | TIMESTAMPTZ | 操作时间 |

索引：`operator_id`、`action`、`created_at DESC`（运维查询和时间范围过滤）

> 审计日志只写不改，不支持删除，保证操作轨迹完整性。

### 4.2 Qdrant Collection 结构

| Collection | 用途 |
|-----------|------|
| `templates` | 存储所有启用模板的三种向量（dense / sparse / colbert） |

每个 Qdrant Point：
- **id**：UUID（与 PostgreSQL `templates.qdrant_point_id` 对应）
- **vectors**：dense（1024维）+ colbert（N×1024维）
- **sparse_vectors**：sparse（词汇权重字典）
- **payload**：template_id、code_type、subcategory、protocol、maturity（用于过滤；原 `category` 字段已重命名为 `code_type` 与 CodeTypeRegistry 对齐）

---

## 5. API 设计

### 5.1 核心端点列表

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/api/v1/code-types` | 获取已注册代码类型列表（前端动态读取，无需硬编码） | 普通用户+ |
| POST | `/api/v1/generate` | 单条代码生成（完整 RAG 链路） | 普通用户+ |
| POST | `/api/v1/generate/render` | 参数变更后重新渲染（不走 LLM/RAG） | 普通用户+ |
| POST | `/api/v1/batch/upload` | 上传 Excel 创建批量任务 | 普通用户+ |
| POST | `/api/v1/batch/preflight` | 上传后前置信度预检（轻量，仅Stage1） | 普通用户+ |
| GET | `/api/v1/batch/{job_id}` | 查询批量任务状态 | 普通用户+ |
| GET | `/api/v1/batch/{job_id}/download` | 下载批量生成结果 | 普通用户+ |
| GET | `/api/v1/intent-builder/scenarios` | 获取场景构建器场景类型列表 | 普通用户+ |
| POST | `/api/v1/intent-builder/generate` | 场景参数→生成标准化意图文本 | 普通用户+ |
| GET | `/api/v1/templates` | 模板列表（支持搜索/筛选/分页） | 普通用户+ |
| GET | `/api/v1/templates/{id}` | 模板详情 | 普通用户+ |
| POST | `/api/v1/admin/templates` | 新建模板（同步写 PG + Qdrant）；先执行查重，相似度 ≥ 阈值返回 `duplicate_warning`；附加 `?force=true` 跳过语义查重 | 库管理员+ |
| PUT | `/api/v1/admin/templates/{id}` | 更新模板（同步更新 PG + Qdrant） | 库管理员+ |
| DELETE | `/api/v1/admin/templates/{id}` | 停用模板（软删除，Qdrant 同步删除向量） | 库管理员+ |
| POST | `/api/v1/admin/templates/import` | 批量导入 YAML（批量写 PG + Qdrant） | 库管理员+ |
| GET | `/api/v1/admin/users` | 用户列表 | 超管 |
| PUT | `/api/v1/admin/users/{id}/role` | 修改用户角色 | 超管 |
| POST | `/api/v1/auth/login` | 登录获取 JWT | 公开 |
| POST | `/api/v1/auth/refresh` | 刷新 Token | 认证用户 |
| GET | `/api/v1/admin/llm/configs` | 获取所有模型配置（api_key 只返回掩码） | 超管 |
| POST | `/api/v1/admin/llm/configs` | 新增模型配置 | 超管 |
| PUT | `/api/v1/admin/llm/configs/{id}` | 更新配置（api_key 留空则不覆盖） | 超管 |
| DELETE | `/api/v1/admin/llm/configs/{id}` | 删除配置（默认模型不可删） | 超管 |
| PUT | `/api/v1/admin/llm/configs/{id}/set-default` | 设为默认（自动清空相关 Redis 缓存） | 超管 |
| POST | `/api/v1/admin/llm/configs/{id}/test` | 执行模型测试（basic/normalization/template_selection） | 超管 |
| POST | `/api/v1/contributions` | 提交模板贡献 | 登录用户+ |
| GET | `/api/v1/contributions/mine` | 查看我的贡献列表 | 登录用户+ |
| GET | `/api/v1/contributions/{id}` | 查看贡献详情 | 贡献者本人 |
| PUT | `/api/v1/contributions/{id}` | 修改贡献（仅 needs_revision 状态） | 贡献者本人 |
| GET | `/api/v1/admin/contributions` | 贡献列表（支持 status/type 过滤） | 库管理员+ |
| GET | `/api/v1/admin/contributions/{id}` | 贡献详情（含 Excel 行快照 + 查重结果 Top-3） | 库管理员+ |
| PUT | `/api/v1/admin/contributions/{id}/approve` | 批准并触发入库流水线 | 库管理员+ |
| PUT | `/api/v1/admin/contributions/{id}/reject` | 退回，body：`{comment}` | 库管理员+ |
| PUT | `/api/v1/admin/contributions/{id}/request-revision` | 请求修改，body：`{comment}` | 库管理员+ |
| GET | `/api/v1/notifications` | 获取当前用户通知列表 | 登录用户+ |
| PUT | `/api/v1/notifications/{id}/read` | 标记通知已读 | 登录用户+ |
| GET | `/api/v1/admin/audit-logs` | 查询管理员操作审计日志（按 action/operator/时间范围过滤，分页） | 超管 |

### 5.2 生成接口请求/响应示例

**POST `/api/v1/generate` 请求体**：

```json
{
  "text": "当axi_valid拉高后，在axi_ready到来之前，axi_data必须保持稳定",
  "code_type": "assertion",
  "protocol": "AXI4",
  "signals": {
    "clk": "clk",
    "valid": "axi_valid",
    "ready": "axi_ready",
    "data": "axi_data"
  }
}
```

**响应体（高置信度，直接生成）**：

```json
{
  "status": "generated",
  "confidence": 0.95,
  "template_id": "SVA-HAND-001",
  "template_version": "1.0.0",
  "cache_hit": false,
  "rag_candidates": [
    { "template_id": "SVA-HAND-001", "name": "Valid-Ready数据稳定性", "score": 0.95 },
    { "template_id": "SVA-HAND-002", "name": "Valid-Ready超时检测",   "score": 0.71 },
    { "template_id": "SVA-TIME-003", "name": "最大延迟约束",          "score": 0.55 }
  ],
  "params_used": {
    "clk": "clk",
    "rst_n": "rst_n",
    "valid_sig": "axi_valid",
    "ready_sig": "axi_ready",
    "data_sig": "axi_data",
    "prop_name": "p_valid_ready_stable"
  },
  "code": "// [SVA-HAND-001 v1.0.0] ...\nproperty p_valid_ready_stable;\n  ...\nendproperty\n..."
}
```

**响应体（低置信度，需用户选择）**：

```json
{
  "status": "needs_selection",
  "rag_candidates": [
    { "template_id": "SVA-HAND-001", "name": "Valid-Ready数据稳定性", "score": 0.72 },
    { "template_id": "SVA-HAND-002", "name": "Valid-Ready超时检测",   "score": 0.61 },
    { "template_id": "SVA-HAND-003", "name": "多周期握手完整性",      "score": 0.55 }
  ],
  "extracted_params": {
    "clk": "clk",
    "valid_sig": "axi_valid",
    "ready_sig": "axi_ready",
    "data_sig": "axi_data"
  }
}
```

---

## 6. 模板 YAML 文件规范

每个模板以独立 YAML 文件存储，文件名格式：`{ID}.yaml`。

```yaml
# 文件：SVA-HAND-001.yaml

id: SVA-HAND-001
version: "1.0.0"
name: "Valid-Ready握手数据稳定性断言"

# 分类
code_type: assertion       # 对应 CodeTypeRegistry 中已注册类型的 id（如 assertion / coverage）
subcategory: handshake

# 匹配信息（用于 bge-m3 编码入 Qdrant）
protocol:
  - AXI4
  - AXI4-Lite
  - custom
tags:
  - valid
  - ready
  - stable
  - handshake
  - backpressure
keywords:
  - 握手
  - 数据稳定
  - valid
  - ready
  - 保持

# 描述
description: "当valid信号拉高且ready信号未到来时，数据信号必须在整个等待期间保持稳定，防止握手期间数据被意外修改"
severity: error            # error | warning | info（仅断言使用）
maturity: production       # draft | validated | production

# 参数定义
parameters:
  - name: clk
    type: signal
    required: true
    description: "时钟信号名"

  - name: rst_n
    type: signal
    required: true
    description: "复位信号名（低有效）"

  - name: valid_sig
    type: signal
    required: true
    description: "有效信号名"

  - name: ready_sig
    type: signal
    required: true
    description: "就绪信号名"

  - name: data_sig
    type: signal
    required: false
    description: "数据信号名（可选）"

  - name: prop_name
    type: string
    required: false
    default: "p_valid_ready_stable"
    description: "SystemVerilog property 名称"

# Jinja2 代码模板
template_body: |
  // [{{ id }} v{{ version }}] {{ name }}
  // 描述: {{ description }}
  property {{ prop_name }};
    @(posedge {{ clk }}) disable iff (!{{ rst_n }})
    ({{ valid_sig }} && !{{ ready_sig }}) |=> $stable({{ data_sig }});
  endproperty
  assert property ({{ prop_name }})
    else $error("[ASSERT FAIL] %s: %s unstable during handshake at time %0t",
                "{{ prop_name }}", "{{ data_sig }}", $time);

# 关联模板
related_templates:
  - SVA-HAND-002    # Valid-Ready响应超时检测（常与本模板组合使用）
  - COV-HAND-001    # Valid-Ready握手事件覆盖率
```

---

## 7. 项目目录结构

```
DV_ACODE_GEN_PLATFORM/
│
├── embedding_service/                    # 独立 GPU 推理服务
│   ├── app/
│   │   ├── main.py                       # FastAPI 服务入口
│   │   ├── models.py                     # bge-m3 + reranker 模型加载
│   │   ├── schemas.py                    # 请求/响应 Pydantic Schema
│   │   └── routers/
│   │       ├── embed.py                  # POST /embed
│   │       └── rerank.py                 # POST /rerank
│   ├── Dockerfile.gpu                    # 基于 CUDA 镜像构建
│   └── requirements.txt                  # FlagEmbedding + FastAPI + torch
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── endpoints/
│   │   │           ├── generate.py              # 单条生成端点
│   │   │           ├── batch.py                 # 批量生成端点
│   │   │           ├── templates.py             # 模板库查询端点
│   │   │           ├── admin.py                 # 管理员端点（模板 CRUD）
│   │   │           ├── admin_llm.py             # LLM 模型配置 + 测试端点（新增）
│   │   │           ├── contributions.py         # 贡献者端点（提交/查看/修改）
│   │   │           ├── admin_contributions.py   # 管理员审核端点
│   │   │           ├── notifications.py         # 站内通知端点
│   │   │           └── auth.py                  # 认证端点
│   │   ├── core/
│   │   │   ├── config.py                 # 环境配置（从环境变量读取）
│   │   │   ├── database.py               # PostgreSQL 连接
│   │   │   ├── vector_store.py           # Qdrant 客户端连接
│   │   │   ├── cache.py                  # Redis 连接
│   │   │   └── security.py               # JWT 认证工具
│   │   ├── models/
│   │   │   ├── template.py               # SQLAlchemy 模板模型
│   │   │   ├── user.py                   # 用户模型
│   │   │   ├── generation_record.py      # 生成历史模型
│   │   │   ├── batch_job.py              # 批量任务模型
│   │   │   ├── llm_config.py             # LLM 配置模型（新增）
│   │   │   ├── contribution.py           # 模板贡献模型
│   │   │   └── notification.py           # 站内通知模型
│   │   ├── schemas/
│   │   │   ├── generate.py               # 生成请求/响应 Schema
│   │   │   ├── template.py               # 模板 Schema
│   │   │   ├── intent.py                 # LLM 工具调用输出 Schema
│   │   │   ├── user.py                   # 用户 Schema
│   │   │   ├── llm_config.py             # LLM 配置请求/响应 Schema（新增）
│   │   │   ├── contribution.py           # 贡献请求/响应 Schema
│   │   │   └── notification.py           # 通知响应 Schema
│   │   ├── services/
│   │   │   │                             # ── 三层服务子包结构 ──
│   │   │   ├── core/                     # 核心算法层（代码类型无感知，纯函数级）
│   │   │   │   ├── pipeline.py           # GenerationPipeline 8步编排器（新增）
│   │   │   │   ├── cache.py              # Redis 缓存读写（原 cache_service.py）
│   │   │   │   ├── renderer.py           # Jinja2 渲染 + StrictUndefined（原 renderer/jinja_renderer.py）
│   │   │   │   └── dedup.py              # 模板查重逻辑（精确名称 + 语义向量）
│   │   │   ├── rag/                      # RAG 检索层（结构不变）
│   │   │   │   ├── stage1_hybrid.py      # Qdrant 混合检索（dense+sparse RRF）
│   │   │   │   ├── stage2_colbert.py     # ColBERT MaxSim 精排
│   │   │   │   ├── stage3_reranker.py    # bge-reranker 精排
│   │   │   │   └── engine.py             # RAG 检索引擎主入口
│   │   │   ├── llm/                      # LLM 抽象层（结构不变）
│   │   │   │   ├── base.py               # LLMClient 抽象基类（complete / select_template）
│   │   │   │   ├── anthropic_client.py   # Anthropic 原生 SDK 实现
│   │   │   │   ├── openai_compat_client.py  # openai SDK + base_url 实现（覆盖所有兼容模型）
│   │   │   │   └── factory.py            # 读 llm_configs 表，按 is_default 实例化客户端
│   │   │   ├── intent/                   # 意图相关服务（聚合子包）
│   │   │   │   ├── normalizer.py         # LLM静默标准化（读 registry 获取句式）
│   │   │   │   ├── builder.py            # 场景构建器（读 registry 获取场景，纯字符串模板）
│   │   │   │   ├── preflight.py          # 上传前置信度预检服务（不调用 LLM）
│   │   │   │   └── history.py            # 历史意图知识库读写
│   │   │   ├── parser/                   # Excel 解析（schema 驱动，通用解释器）
│   │   │   │   └── excel_parser.py       # 读 data/schemas/*.yaml 动态解析任意代码类型
│   │   │   ├── platform/                 # 平台功能层（与生成核心完全解耦）
│   │   │   │   ├── contribution_service.py  # 贡献入库流水线（复用 create_template()）
│   │   │   │   ├── audit_service.py      # 审计日志写入服务（新增）
│   │   │   │   └── backup_service.py     # 备份管理服务（新增）
│   │   │   ├── registry.py               # CodeTypeRegistry（启动时加载 data/code_types/*.yaml，运行时只读）
│   │   │   └── embedding_client.py       # Embedding Service HTTP 客户端
│   │   ├── tasks/
│   │   │   └── batch_tasks.py            # Celery 批量任务
│   │   └── main.py                       # FastAPI 应用入口
│   │
│   ├── template_library/                 # YAML 模板文件（Git 管理）
│   │   ├── assertions/
│   │   │   ├── handshake/
│   │   │   │   ├── SVA-HAND-001.yaml
│   │   │   │   └── SVA-HAND-002.yaml
│   │   │   ├── timing/
│   │   │   ├── fsm/
│   │   │   ├── data_integrity/
│   │   │   ├── bus_protocol/
│   │   │   │   ├── axi4/
│   │   │   │   ├── ahb/
│   │   │   │   └── apb/
│   │   │   ├── reset/
│   │   │   ├── counter/
│   │   │   └── arbitration/
│   │   └── coverage/
│   │       ├── value/
│   │       ├── transition/
│   │       ├── cross/
│   │       ├── protocol/
│   │       └── exception/
│   │
│   ├── scripts/
│   │   └── lib_manager.py                # CLI：模板导入/验证/重建Qdrant索引
│   │
│   ├── data/
│   │   ├── code_types/                   # 代码类型注册配置（扩展新类型只需新增文件）
│   │   │   ├── assertion.yaml            # SVA断言类型定义（见 §3.14）
│   │   │   └── coverage.yaml             # UVM功能覆盖率类型定义（见 §3.14）
│   │   ├── schemas/                      # Excel 列定义（schema 驱动解析器）
│   │   │   ├── sva_schema.yaml           # SVA断言 Excel 列规范
│   │   │   └── coverage_schema.yaml      # 覆盖率 Excel 列规范
│   │   └── scenarios/                    # 场景句式模板（各类型独立文件）
│   │       ├── assertion_scenarios.yaml  # SVA 场景构建器句式
│   │       └── coverage_scenarios.yaml   # Coverage 场景构建器句式
│   ├── alembic/                          # 数据库迁移
│   │   # 003_add_contributions_and_notifications.sql
│   │   # 004_add_intent_fields_to_generation_records.sql
│   │   # 005_add_llm_configs.sql
│   │   # 006_rename_category_to_code_type.sql（新增）
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── CodeOutput/               # Monaco Editor 代码展示
│   │   │   ├── ParamPanel/               # 参数面板（实时编辑）
│   │   │   ├── TemplateSelector/         # 候选模板选择组件
│   │   │   ├── BatchProgress/            # 批量生成进度组件
│   │   │   ├── NotificationBell/         # 顶部通知角标（新增）
│   │   │   └── contribution/             # 贡献向导组件（新增）
│   │   │       ├── ContributionWizard.tsx  # 3步 Modal 入口
│   │   │       ├── Step1Intent.tsx         # Step1：意图澄清
│   │   │       ├── Step2DemoEditor.tsx     # Step2：Monaco 编写 Demo
│   │   │       └── Step3Metadata.tsx       # Step3：填写元数据
│   │   ├── pages/
│   │   │   ├── Generate/                 # 单条生成页面
│   │   │   ├── Batch/                    # 批量生成页面
│   │   │   ├── Library/                  # 模板库浏览页面
│   │   │   ├── MyContributions/          # 我的贡献页面
│   │   │   ├── IntentBuilder/            # 场景构建器页面（新增）
│   │   │   └── Admin/
│   │   │       ├── Templates/            # 管理员模板管理
│   │   │       ├── ContributionReview/   # 贡献审核队列
│   │   │       └── LLMConfig/            # LLM 模型配置管理（新增）
│   │   │           ├── index.tsx         # 模型列表（卡片形式）
│   │   │           └── TestPanel.tsx     # 三类模型测试面板
│   │   ├── api/
│   │   │   ├── client.ts                 # Axios API 调用封装
│   │   │   ├── contributionApi.ts        # 贡献 API 封装
│   │   │   ├── intentBuilderApi.ts       # 场景构建器 API 封装
│   │   │   └── llmConfigApi.ts           # LLM 配置管理 API 封装（新增）
│   │   ├── hooks/
│   │   ├── types/
│   │   └── App.tsx
│   ├── Dockerfile
│   └── package.json
│
├── docker-compose.yml                    # 主编排文件（Linux/Windows 通用）
├── docker-compose.dev.yml                # 开发环境覆盖（无 GPU 要求）
├── docker-compose.gpu-linux.yml          # Linux GPU 覆盖（NVIDIA Container Toolkit）
├── docker-compose.gpu-windows.yml        # Windows GPU 覆盖（Docker Desktop + WSL2）
├── nginx.conf
├── .gitattributes                        # 统一换行符（LF），防止 Windows CRLF 污染
├── PRD.md
├── ARCHITECTURE.md
└── .env.example
```

---

## 8. 部署架构

### 8.1 Docker Compose 服务组成

```
services:
  nginx              # 80/443，静态资源 + API 路由
  frontend           # React 构建产物（nginx 静态托管）
  backend            # FastAPI（Uvicorn 多 worker）
  celery_worker      # Celery Worker（批量任务）
  embedding_service  # bge-m3 + bge-reranker（GPU 容器）
  qdrant             # Qdrant 向量数据库
  postgres           # PostgreSQL 16（纯关系型，无 pgvector）
  redis              # Redis 7（缓存 + 任务队列）
  backup             # PostgreSQL 自动备份服务（每日 pg_dump，保留 7 天）
```

### 8.2 启动命令（按平台）

所有平台均使用相对路径，主 `docker-compose.yml` 不含平台特定配置，GPU 支持通过覆盖文件叠加：

```bash
# Linux（生产，含 GPU）
docker compose -f docker-compose.yml -f docker-compose.gpu-linux.yml up -d

# Windows（生产，含 GPU，需 Docker Desktop + WSL2）
docker compose -f docker-compose.yml -f docker-compose.gpu-windows.yml up -d

# 开发环境（Linux / Windows 均适用，不需要 GPU）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

**`docker-compose.gpu-linux.yml`**（NVIDIA Container Toolkit 运行时）：

```yaml
services:
  embedding_service:
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

**`docker-compose.gpu-windows.yml`**（Docker Desktop + WSL2，无需 runtime 字段）：

```yaml
services:
  embedding_service:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

> Windows 上 Docker Desktop 通过 WSL2 自动调用 NVIDIA GPU，无需显式指定 `runtime: nvidia`，语法与 Linux 仅差此一行。

**`docker-compose.dev.yml` — Embedding Service 降级配置**：

开发环境通常无 GPU，bge-m3 CPU 推理 ~5-30s/次，严重影响开发效率。dev 模式通过环境变量切换为 `bge-small-zh-v1.5`（~100MB，CPU ~200ms/次）：

```yaml
services:
  embedding_service:
    environment:
      - EMBED_MODEL=BAAI/bge-small-zh-v1.5   # 生产环境为 BAAI/bge-m3
      - RERANK_MODEL=BAAI/bge-reranker-v2-m3
      - DEVICE=cpu
```

> **注意**：`bge-small-zh-v1.5` 输出 512 维向量（bge-m3 为 1024 维），dev 环境的 Qdrant collection 需单独创建（`templates_dev`），与生产 collection 不兼容。dev 环境 RAG 匹配质量仅供流程验证，不代表生产效果。

### 8.3 服务间通信

```
用户 → Nginx (80/443)
         ├── /          → frontend 静态文件
         └── /api/      → backend:8000

backend → embedding_service:8001   (HTTP，内网)
backend → qdrant:6333              (HTTP，内网)
backend → postgres:5432
backend → redis:6379
backend → LLM API（HTTPS，外网）    (Anthropic / DeepSeek / Qwen / 本地 vLLM 等，由 llm_configs 配置决定)

celery_worker → embedding_service:8001
celery_worker → qdrant:6333
celery_worker → postgres:5432
celery_worker → redis:6379
```

### 8.4 环境变量配置项

| 变量名 | 说明 |
|--------|------|
| `DATABASE_URL` | PostgreSQL 连接字符串 |
| `REDIS_URL` | Redis 连接字符串 |
| `QDRANT_URL` | Qdrant 服务地址（如 `http://qdrant:6333`） |
| `QDRANT_COLLECTION` | Qdrant collection 名称（默认 `templates`） |
| `EMBEDDING_SERVICE_URL` | Embedding Service 地址（如 `http://embedding_service:8001`） |
| `ANTHROPIC_API_KEY` | Claude API 密钥（可选，初始化时写入 llm_configs 表的默认配置；之后通过 Admin UI 管理） |
| `LLM_KEY_ENCRYPTION_SECRET` | LLM API Key 在数据库中的 AES-256-GCM 加密密钥（必填，32字节） |
| `JWT_SECRET_KEY` | JWT 签名密钥 |
| `JWT_EXPIRE_MINUTES` | Token 过期时间（分钟） |
| `CONFIDENCE_THRESHOLD` | 自动生成置信度阈值（默认 `0.85`） |
| `RAG_STAGE1_TOP_K` | Stage1 粗筛候选数（默认 `100`） |
| `RAG_STAGE2_TOP_K` | Stage2 ColBERT 精排候选数（默认 `20`） |
| `RAG_STAGE3_TOP_K` | Stage3 Reranker 最终候选数（默认 `3`） |
| `CELERY_CONCURRENCY` | Celery Worker 并发数（默认 `10`） |
| `TEMPLATE_DEDUP_THRESHOLD` | 模板入库查重阈值（默认 `0.90`）；单位为 bge-m3 dense 向量余弦相似度（0.90 = 语义 90% 相似），超过此值触发 duplicate_warning |
| `BACKUP_RETAIN_DAYS` | `7` | PostgreSQL 备份文件保留天数，超期自动删除 |
| `QDRANT_SNAPSHOT_ENABLED` | `false` | 是否启用 Qdrant 每周快照（false 时只依赖 rebuild-index 恢复） |

---

## 9. 跨平台支持（Windows & Linux）

### 9.1 平台要求对比

| 组件 | Linux | Windows |
|------|-------|---------|
| 容器引擎 | Docker Engine 24+ | Docker Desktop 4.x（WSL2 backend） |
| GPU 驱动 | NVIDIA 驱动 + NVIDIA Container Toolkit | NVIDIA 驱动（≥ 527.x）+ WSL2 CUDA 支持（驱动自带） |
| CUDA | 宿主机安装 CUDA（或仅容器内） | 无需宿主机装 CUDA，WSL2 自动映射 |
| Python（开发用） | 3.11+，原生安装 | 3.11+，建议在 WSL2 内安装或使用原生 Python |
| 其他 | 无额外要求 | 启用 WSL2（`wsl --install`）、BIOS 开启虚拟化 |

### 9.2 Windows 环境准备步骤

```
1. 安装 WSL2
   wsl --install
   wsl --set-default-version 2

2. 安装 NVIDIA 驱动（Windows 侧，≥ 527.x）
   下载地址：https://www.nvidia.com/drivers
   安装后 WSL2 内自动可用 nvidia-smi

3. 安装 Docker Desktop
   启用 "Use WSL 2 based engine"（Settings → General）
   启用 "Enable integration with my default WSL distro"

4. 验证 GPU 在 Docker 中可用
   docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

### 9.3 Linux 环境准备步骤

```
1. 安装 Docker Engine
   curl -fsSL https://get.docker.com | sh

2. 安装 NVIDIA Container Toolkit
   distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list \
     | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo systemctl restart docker

3. 验证 GPU 在 Docker 中可用
   docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

### 9.4 代码层跨平台规范

所有代码必须遵守以下规范，保证在 Windows 和 Linux 上行为一致：

**文件路径**：全部使用 `pathlib.Path`，禁止字符串拼接路径

```python
# ✓ 正确（跨平台）
from pathlib import Path
template_dir = Path(__file__).parent / "template_library" / "assertions"

# ✗ 错误（Linux 专用）
template_dir = "/app/template_library/assertions"
```

**脚本**：所有自动化脚本使用 Python，不使用 `.sh`（Bash 在 Windows 需 WSL2）

```
scripts/
  lib_manager.py     # 模板导入/验证/重建索引（跨平台 Python CLI）
  # 不提供 .sh 脚本
```

**换行符**：项目根目录统一配置 `.gitattributes`，强制 LF，防止 Windows 将文件提交为 CRLF

```gitattributes
# .gitattributes
*           text=auto eol=lf
*.py        text eol=lf
*.yaml      text eol=lf
*.yml       text eol=lf
*.md        text eol=lf
*.sh        text eol=lf
*.ts        text eol=lf
*.tsx       text eol=lf
*.json      text eol=lf
Dockerfile* text eol=lf
*.bat       text eol=crlf   # Windows 批处理保留 CRLF
```

**Docker Compose Volume**：主 `docker-compose.yml` 只使用相对路径（`./data/postgres`），不使用绝对路径，保证两平台一致

```yaml
# ✓ 正确（相对路径，两平台均可）
volumes:
  - ./data/postgres:/var/lib/postgresql/data
  - ./data/qdrant:/qdrant/storage

# ✗ 错误（绝对路径，Linux 专用）
volumes:
  - /opt/app/data:/var/lib/postgresql/data
```

### 9.5 开发环境建议

| 场景 | Linux | Windows |
|------|-------|---------|
| 完整本地开发（含 GPU） | 直接运行所有服务 | 在 WSL2 内开发，Docker Desktop 管理容器 |
| 无 GPU 开发 | `docker-compose.dev.yml`（CPU fallback） | 同左，无需特殊配置 |
| IDE | VS Code / JetBrains | VS Code（推荐 WSL2 Remote 插件） |
| Python 虚拟环境 | venv / conda | WSL2 内 venv，或 Windows 原生 venv（不含 GPU 依赖） |

**开发环境 CPU Fallback**（`docker-compose.dev.yml` 中的 embedding_service）：

```yaml
# 开发环境：关闭 GPU，bge-m3 走 CPU（速度慢但可用）
services:
  embedding_service:
    environment:
      - USE_GPU=false
      - DEVICE=cpu
```

Embedding Service 内部通过 `USE_GPU` 环境变量决定加载设备，无需修改代码。

---

## 11. 扩展路径

| 扩展方向 | 实现路径 |
|---------|---------|
| 新增模板分类 | 添加 YAML 文件，`lib_manager.py import` 自动写 PG + Qdrant，无需改代码 |
| 支持新输出语言（如 e-language） | 模板 YAML 新增 `template_e` 字段，前端加语言选项，渲染层加分支 |
| 替换 Embedding 模型 | 替换 `embedding_service` 中的模型，重跑 `lib_manager.py rebuild-index` 重建 Qdrant 向量 |
| 调整检索阶段参数 | 修改环境变量 `RAG_STAGE*_TOP_K`，无需重新部署 |
| 企业 SSO/LDAP 登录 | 替换 `security.py` 认证后端，其余不变 |
| 切换 LLM 模型 | Admin UI 新增配置 → 设为默认 → 自动清空相关 Redis 缓存，无需重启服务 |
| 新增第三方模型支持 | 只要模型实现 OpenAI-compatible API，Admin UI 填入 URL+Key 即可接入，无需改代码 |
| 与 EDA 工具集成 | 新增 `/api/v1/export/{format}` 端点，输出对应格式文件 |
