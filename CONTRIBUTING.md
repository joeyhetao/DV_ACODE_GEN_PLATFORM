# 贡献与维护指南

> 本文档面向项目所有参与者，覆盖：仓库初始化、本地开发环境搭建、分支规范、提交规范、文档维护流程。

---

## 目录

1. [仓库结构](#1-仓库结构)
2. [首次建仓流程](#2-首次建仓流程)
3. [本地开发环境](#3-本地开发环境)
4. [分支策略](#4-分支策略)
5. [提交规范](#5-提交规范)
6. [日常开发流程](#6-日常开发流程)
7. [推送与 PR 流程](#7-推送与-pr-流程)
8. [文档维护规范](#8-文档维护规范)
9. [版本发布流程](#9-版本发布流程)
10. [常用命令速查](#10-常用命令速查)
11. [无关意图回归语料维护](#11-无关意图回归语料维护)

---

## 1. 仓库结构

```
DV_ACODE_GEN_PLATFORM/
├── .github/
│   └── PULL_REQUEST_TEMPLATE.md        # PR 模板
├── backend/                             # FastAPI 后端
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/                     # 路由层（auth/generate/templates/batch/admin/admin_llm/
│   │   │                               #         intent_builder/contributions/notifications）
│   │   ├── core/                        # 配置、安全、数据库、Qdrant 连接
│   │   ├── models/                      # SQLAlchemy ORM 模型
│   │   ├── schemas/                     # Pydantic 请求/响应 Schema
│   │   ├── services/
│   │   │   ├── core/                   # 确定性生成引擎（pipeline/renderer/dedup/cache + identifier/expr_validator）
│   │   │   ├── intent/                 # 意图提取（normalizer/preflight/builder/history）
│   │   │   ├── llm/                    # LLM 适配层（Anthropic + OpenAI 兼容工厂）
│   │   │   ├── parser/                 # Excel 需求表解析（schema 驱动）
│   │   │   ├── platform/               # 审计日志、备份、贡献审核
│   │   │   ├── rag/                    # 三阶段 RAG（stage1_hybrid/stage2_colbert/stage3_reranker）
│   │   │   ├── registry.py             # CodeTypeRegistry（启动时加载 data/code_types/*.yaml）
│   │   │   └── embedding_client.py     # 嵌入服务 HTTP 客户端
│   │   ├── tasks/                       # Celery 异步任务（celery_app/batch_tasks）
│   │   └── main.py
│   ├── data/                            # 代码类型注册配置（扩展新类型只需改 YAML）
│   │   ├── code_types/                 # 类型定义（assertion / coverage 等）
│   │   ├── schemas/                    # Excel 列规范（schema 驱动解析器）
│   │   └── scenarios/                  # 场景构建器句式模板
│   ├── migrations/                      # Alembic 数据库迁移（001_initial_schema 起）
│   ├── tests/                           # 后端单元/集成测试（pytest）
│   ├── template_library/                # YAML 模板库（受版本控制）
│   │   ├── assertions/                 # SVA 断言模板
│   │   └── coverage/                   # 功能覆盖率模板
│   ├── lib_manager.py                   # 模板库管理 CLI（导入/校验/重建 Qdrant/导出 YAML）
│   ├── Dockerfile
│   └── requirements.txt
├── embedding_service/                   # 独立嵌入服务（BGE-M3 + Reranker，GPU/CPU 可选）
│   ├── app/                            # FastAPI 服务（main/models/routers/schemas）
│   ├── Dockerfile.gpu
│   └── requirements.txt
├── frontend/                            # React + TypeScript + Vite
│   ├── src/
│   │   ├── api/                        # API 请求层（client/auth/generate/admin 等）
│   │   ├── components/                 # 公共组件（MainLayout 等）
│   │   ├── hooks/                      # 自定义 React Hook
│   │   ├── pages/                      # 页面组件（Generate/Batch/Library/IntentBuilder/
│   │   │                               #           MyContributions/Admin/Login）
│   │   ├── store/                      # 状态管理（Zustand）
│   │   └── utils/                      # 工具函数
│   ├── nginx-frontend.conf             # 前端容器内 nginx 配置
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml                   # 主 compose（CPU 默认栈）
├── docker-compose.dev.yml               # 开发 overlay（端口透出等）
├── docker-compose.hotreload.yml         # 后端 --reload + 源码挂载
├── docker-compose.gpu-linux.yml         # Linux GPU overlay（CUDA passthrough）
├── docker-compose.gpu-windows.yml       # Windows GPU overlay（WSL2 GPU）
├── nginx.conf                           # 入口反向代理（前端 + /api 路由）
├── docs/                                # 补充文档（deployment-{dev-windows,prod-linux}.md / startup-wsl.md / test-manual.md / deployment.md 索引 / platform-bug.md / test-bug.md）
├── PRD.md                               # 产品需求文档
├── ARCHITECTURE.md                      # 架构设计文档
├── CONTRIBUTING.md                      # 本文件
├── CHANGELOG.md                         # 变更日志
├── CLAUDE.md                            # Claude Code 项目级指南（架构契约 + 速记 + house rules）
└── README.md                            # 项目入口
```

---

## 2. 首次建仓流程

### 2.1 在 GitHub 创建远程仓库

1. 登录 GitHub → New Repository
2. Repository name: `DV_ACODE_GEN_PLATFORM`
3. 选择 **Private**（企业内部项目）
4. **不勾选** Initialize with README（本地已有内容）
5. 点击 Create repository

### 2.2 本地初始化并推送

```bash
# 进入项目目录
cd /path/to/DV_ACODE_GEN_PLATFORM

# 初始化 git（如未初始化）
git init

# 添加 .gitignore（Python + Node + IDE）
curl -o .gitignore https://www.toptal.com/developers/gitignore/api/python,node,vscode,jetbrains

# 首次提交
git add .
git commit -m "chore: initial project structure"

# 关联远程仓库并推送
git remote add origin https://github.com/<your-org>/DV_ACODE_GEN_PLATFORM.git
git branch -M main
git push -u origin main

# 创建 develop 分支
git checkout -b develop
git push -u origin develop
```

### 2.3 推荐的 .gitignore 关键条目

```gitignore
# Python
__pycache__/
*.pyc
.venv/
*.egg-info/

# Node
node_modules/
dist/
.next/

# 环境变量（绝不提交）
.env
.env.local
.env.*.local
*.env

# 数据库 / 缓存
*.db
*.sqlite3

# IDE
.vscode/
.idea/
*.swp

# 构建产物
build/
*.log
```

---

## 3. 本地开发环境

### 3.1 前置依赖

| 工具 | 版本要求 | 用途 |
|------|----------|------|
| Python | ≥ 3.11 | 后端运行时 |
| Node.js | ≥ 20 LTS | 前端构建 |
| Docker Desktop | ≥ 24 | 本地基础设施（PG/Redis） |
| Git | ≥ 2.40 | 版本控制 |

### 3.2 后端环境搭建

```bash
cd backend

# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

# 安装依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 复制环境变量模板
cp .env.example .env
# 编辑 .env，填写本地 PostgreSQL / Redis / Anthropic Key

# 启动基础设施（PostgreSQL + Redis + Qdrant）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis qdrant

# 数据库迁移
alembic upgrade head

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

### 3.3 前端环境搭建

```bash
cd frontend

npm install

# 复制环境变量
cp .env.example .env.local
# 填写 VITE_API_BASE_URL=http://localhost:8000

npm run dev
# 访问 http://localhost:5173
```

### 3.4 一键启动（容器化完整栈）

如果不想在主机上装 Python / Node 直接跑后端、前端，而是把所有服务都放进 Docker 跑（hot reload + bind mount + 一致环境），完整指引见：

- **Win11 本机**：[docs/deployment-dev-windows.md](docs/deployment-dev-windows.md)（含 `.wslconfig` 优化、Docker Desktop 崩溃处置、bundle bind mount、HF 模型路径等本机特有的内容）
- **Linux/Mac 本机**：直接套用上面 Win11 那份的 §3-§4 流程，把 PowerShell 命令换成 bash 即可，路径用相对路径

简化版命令（适用所有平台）：

```bash
cd frontend && npm install && npm run build && cd ..
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.hotreload.yml up -d
# 前端 + 后端 + API 文档统一入口: http://localhost/
```

> §3.2、§3.3 描述的是「主机原生开发」路径（Python venv 跑 uvicorn + npm run dev 跑 vite），适合需要 IDE 断点调试或快速迭代的贡献者；本节是「容器化开发」路径，环境一致性最高。两种路径任选其一。

---

## 4. 分支策略

采用 **GitFlow 简化版**：

```
main          # 生产就绪代码，只接受来自 release/* 和 hotfix/* 的 PR
develop       # 集成分支，功能完成后合并到此
feature/*     # 新功能开发
fix/*         # Bug 修复
hotfix/*      # 生产紧急修复（从 main 切出，合并回 main + develop）
release/*     # 版本发布准备（从 develop 切出）
docs/*        # 仅文档变更
```

### 分支命名示例

```
feature/sva-template-axi4
feature/batch-generation-excel-import
fix/confidence-score-calculation
hotfix/redis-cache-key-collision
release/v1.2.0
docs/update-architecture-diagram
```

---

## 5. 提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

[可选 body]

[可选 footer]
```

### type 类型

| type | 含义 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 仅文档变更 |
| `refactor` | 代码重构（无功能变更） |
| `test` | 添加或修改测试 |
| `chore` | 构建流程、依赖更新等 |
| `perf` | 性能优化 |
| `ci` | CI/CD 配置变更 |

### scope 范围（本项目常用）

`engine` / `llm` / `template` / `api` / `frontend` / `db` / `deploy` / `auth`

### 示例

```bash
git commit -m "feat(engine): add AXI4 burst type matching rule"
git commit -m "fix(llm): handle JSON schema parse error for missing fields"
git commit -m "docs(template): add SVA assertion authoring guide"
git commit -m "refactor(db): migrate ORM queries to async SQLAlchemy 2.0"
git commit -m "chore(deps): upgrade anthropic-sdk to 0.40.0"
```

---

## 6. 日常开发流程

```bash
# 1. 从最新 develop 创建功能分支
git checkout develop
git pull origin develop
git checkout -b feature/your-feature-name

# 2. 开发、提交（小步多次提交）
git add <specific-files>
git commit -m "feat(scope): description"

# 3. 保持与 develop 同步（避免大偏差后合并地狱）
git fetch origin
git rebase origin/develop        # 推荐 rebase 保持线性历史

# 4. 推送并发起 PR
git push origin feature/your-feature-name
# 在 GitHub 上创建 PR → develop
```

---

## 7. 推送与 PR 流程

### PR 必填项

- [ ] 关联 Issue 编号（`Closes #<issue-number>`）
- [ ] 功能描述（做了什么、为什么这么做）
- [ ] 测试说明（如何验证）
- [ ] 对确定性的影响说明（核心约束检查）

### Review 标准

- 确定性核心（`services/core/`）变更必须有单元测试覆盖
- LLM 调用不得出现在 `services/core/` 层
- 模板变更需同步更新 `backend/template_library/` 目录的 YAML 文件
- 不得在代码中硬编码 API Key 或密码

### 合并策略

- `feature/*` → `develop`：**Squash Merge**（保持 develop 历史整洁）
- `release/*` → `main`：**Merge Commit**（保留发布节点）
- `hotfix/*` → `main` + `develop`：**Merge Commit**

---

## 8. 文档维护规范

### 8.1 文档分类与位置

| 文档 | 位置 | 更新时机 |
|------|------|----------|
| 产品需求（PRD） | `PRD.md` | 需求变更时，版本号递增 |
| 架构设计 | `ARCHITECTURE.md` | 架构调整时同步更新 |
| 变更日志 | `CHANGELOG.md` | 每次发布前更新 |
| API 文档 | FastAPI 自动生成 `/docs` | 接口变更自动同步 |
| 模板编写指南 | `docs/template-authoring.md` | 新增模板类型时 |
| 部署手册 | `docs/deployment.md` | 部署配置变更时 |
| 本指南 | `CONTRIBUTING.md` | 流程调整时 |

### 8.2 PRD.md 维护规则

- 每次需求变更必须递增版本号（`v2.7` → `v2.8`）
- 在文件头部 `变更` 区块追加变更摘要
- 保留历史版本描述，不删除旧内容
- 变更同时在 `CHANGELOG.md` 记录

### 8.3 ARCHITECTURE.md 维护规则

- 架构图使用 Mermaid 语法（GitHub 原生渲染）
- 新增服务/组件时同步更新数据流图
- 决策变更需记录 **决策原因**（ADR 风格）

### 8.4 CHANGELOG.md 格式

遵循 [Keep a Changelog](https://keepachangelog.com/) 规范：

```markdown
## [1.2.0] - 2026-05-01

### Added
- AXI4 协议 SVA 断言模板（burst/len/size 参数匹配）
- 批量生成支持最大 500 条并发处理

### Fixed
- 修复 Redis 缓存键在特殊字符信号名下的碰撞问题

### Changed
- 置信度阈值从 80% 调整为 85%

## [1.1.0] - 2026-04-15
...
```

---

## 9. 版本发布流程

```bash
# 1. 从 develop 创建 release 分支
git checkout develop
git pull origin develop
git checkout -b release/v1.2.0

# 2. 更新版本号和 CHANGELOG
# 编辑 CHANGELOG.md，将 [Unreleased] 改为 [1.2.0] - <date>
# 更新 backend/app/version.py 或 package.json 中的版本号

git commit -m "chore(release): bump version to v1.2.0"

# 3. 合并到 main 并打 tag
git checkout main
git merge --no-ff release/v1.2.0
git tag -a v1.2.0 -m "Release v1.2.0: AXI4 template support"
git push origin main --tags

# 4. 合并回 develop
git checkout develop
git merge --no-ff release/v1.2.0
git push origin develop

# 5. 删除 release 分支
git branch -d release/v1.2.0
git push origin --delete release/v1.2.0
```

---

## 10. 常用命令速查

```bash
# ---- 仓库状态 ----
git status                         # 工作区状态
git log --oneline --graph -20      # 图形化提交历史
git diff origin/develop            # 与 develop 的差异

# ---- 分支操作 ----
git checkout -b feature/xxx        # 创建并切换分支
git branch -d feature/xxx          # 删除本地分支
git push origin --delete feature/xxx  # 删除远程分支

# ---- 同步操作 ----
git fetch --all --prune            # 拉取所有远程变更并清理已删除分支
git rebase origin/develop          # 变基到最新 develop
git pull --rebase origin develop   # 拉取并变基

# ---- 撤销操作 ----
git restore <file>                 # 撤销未暂存的文件变更
git restore --staged <file>        # 从暂存区移除（不丢失修改）
git revert <commit-hash>           # 安全回滚（生成反向提交）

# ---- 暂存工作 ----
git stash push -m "wip: feature description"
git stash list
git stash pop

# ---- 查找问题 ----
git log --all --grep="keyword"     # 按关键词搜索提交记录
git blame <file>                   # 查看每行最后一次修改者
git bisect start                   # 二分法定位引入 bug 的提交
```

---

## 11. 无关意图回归语料维护

系统的"无关意图早返"（off-topic gate）依赖 RAG 之前的 dense 余弦阈值闸：原文 → bge-m3 dense embedding → Qdrant top1 余弦 < `OFFTOPIC_DENSE_THRESHOLD`（默认 0.44）→ HTTP 422。这条信号容易在以下情况静默回归：

- bge-m3 模型升级或更换 embedding 服务
- 模板库扩张（新增 code_type / 新模板使语料分布偏移）
- 阈值校准失效（语料样本不再典型）

`backend/tests/data/offtopic_corpus.yaml` 是兜底网——一份 checked-in 的"无关意图 vs marginal 真请求"样本集，由两套 pytest 守护：

- `tests/test_offtopic_corpus_mocked.py`：mock LLM，PR 必跑，守 pipeline 逻辑
- `tests/test_offtopic_corpus_real_llm.py`：调真 LLM，手动跑（`--real-llm` flag），守 prompt + 模型

### 11.1 新增样本的标准流程

**触发点 A：用户报告误判（最高频）**
1. 拿到原文：用户报"真请求被错拒"或"无关请求过了"
2. 复现并定位失效信号（通常是 sentinel 没触发 / 误触发）
3. 在 `offtopic_corpus.yaml` 对应段（`off_topic` 或 `marginal_ic`）加一条样本，必填 `id` / `input` / `code_type[s]` / `added` / `source: "user report YYYY-MM-DD"` / `reason`
4. **先跑 mock 测——预期当前 fail**（红灯证明语料抓到了真问题）
5. 改 prompt / 代码使 mock 测变绿 → 提 PR → 永守

**触发点 B：新增 code_type 或重大模板库变更（中频）**
PR 前 checklist：
- [ ] `offtopic_corpus.yaml` 是否需要新增样本？
  - 新 code_type 至少补 1 条 marginal_ic 边界样本
  - 新模板若引入了以前没法生成的场景，补一条对应输入

**触发点 C：bge-m3 或模板库重大变更（低频但风险高）**
1. PR 前先跑校准脚本看分布是否偏移：
   ```bash
   docker compose exec backend python scripts/calibrate_offtopic_threshold.py
   ```
2. 若 off_max 与 marg_min 出现重叠，**优先扩充模板库**让在域请求 embedding 更清晰，不要直接放宽阈值
3. 校准建议值与现有 `offtopic_dense_threshold` 偏差较大时，更新 `backend/app/core/config.py` 默认值并在 PR description 附校准输出
4. 真 LLM 端到端测试：`docker compose exec backend pytest tests/test_offtopic_corpus_real_llm.py --real-llm -v`
5. 个别样本不稳定可标 `flaky: true`——real-LLM 套件会 warn 而非 fail，保留历史

### 11.2 维护准则

- **append-only 优先**：除非彻底改设计契约，不要删除已有样本——它们是历史回归的疫苗
- **断言保持松散**：不绑具体 `template_id`（避免模板改名/合并破测）
- **`source` + `reason` 必填**：6 个月后能看懂"这条为什么在这里"
- **`added` 日期**：便于定期 review 时识别老化样本

### 11.3 跑法速查

```bash
# PR 必跑：mock 套件（快，纯本地）
docker compose exec backend pytest tests/test_offtopic_corpus_mocked.py -v

# 手动跑：真 LLM 套件（需 llm_configs 表已配 is_default=true 记录）
docker compose exec backend pytest tests/test_offtopic_corpus_real_llm.py --real-llm -v
```

### 11.4 周期性语料增量（建议运维节奏）

`触发点 A` 是被动的——只有用户报告才补。为防"沉默漂移"（用户误拒不上报，accuracy 在统计层面下降），建议每 4 周做一次主动 sampling：

1. 从最近 4 周 `generation_records` 表里筛 `confidence < 0.5` 或返 422 的 intent_hash
2. 拉对应原文（运维需提前确认日志合规：原文是否可保留 / 是否需要脱敏）
3. 每段抽 10 条人工评判 `off_topic` vs `marginal_ic`
4. 把"模型判错的"按 §11.1 流程加进 `offtopic_corpus.yaml`
5. 跑校准脚本看分布；偏移大就重新调阈值并跟一次真 LLM 套件

**不要在代码里硬编码这条流程的频率**。这是数据工程职责，进 ops runbook 即可——本节作为一份"未来想到再做"的备忘。

详细 schema 字段约定见 `backend/tests/data/offtopic_corpus.yaml` 文件头注释。

---

> 如有流程疑问，请在 GitHub Issues 中提出，或联系项目维护者。
