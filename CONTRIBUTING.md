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

---

## 1. 仓库结构

```
DV_ACODE_GEN_PLATFORM/
├── .github/
│   └── PULL_REQUEST_TEMPLATE.md   # PR 模板
├── backend/                        # FastAPI 后端
│   ├── app/
│   │   ├── api/                   # 路由层
│   │   ├── core/                  # 配置、安全
│   │   ├── engine/                # 算法匹配引擎（确定性核心）
│   │   ├── llm/                   # LLM 参数提取层
│   │   ├── models/                # SQLAlchemy ORM
│   │   ├── schemas/               # Pydantic Schema
│   │   └── templates_lib/         # Jinja2 模板渲染
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                       # React + TypeScript
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   ├── Dockerfile
│   └── package.json
├── templates/                      # YAML 模板库（受版本控制）
│   ├── sva/                       # SVA 断言模板
│   └── coverage/                  # 功能覆盖率模板
├── deploy/                         # 部署配置
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   └── nginx/
├── docs/                           # 补充文档
├── PRD.md                          # 产品需求文档
├── ARCHITECTURE.md                 # 架构设计文档
├── CONTRIBUTING.md                 # 本文件
├── CHANGELOG.md                    # 变更日志
└── README.md                       # 项目入口
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

# 启动基础设施（PostgreSQL + Redis + pgvector）
docker compose -f ../deploy/docker-compose.yml up -d db redis

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

### 3.4 一键启动（完整栈）

```bash
# 在项目根目录
docker compose -f deploy/docker-compose.yml up --build
# 前端: http://localhost:3000
# 后端: http://localhost:8000
# API文档: http://localhost:8000/docs
```

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

- 确定性核心（`engine/`）变更必须有单元测试覆盖
- LLM 调用不得出现在 `engine/` 层
- 模板变更需同步更新 `templates/` 目录的 YAML 文件
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

> 如有流程疑问，请在 GitHub Issues 中提出，或联系项目维护者。
