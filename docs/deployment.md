# IC验证辅助代码生成平台 — 部署手册

**适用版本**：v1.0.0  
**更新日期**：2026-04-27  
**适用环境**：Linux（生产推荐）/ Windows（开发 / 测试）

---

## 目录

1. [环境要求](#1-环境要求)
2. [目录结构与配置文件说明](#2-目录结构与配置文件说明)
3. [环境变量配置](#3-环境变量配置)
4. [首次部署](#4-首次部署)
5. [启动场景选择](#5-启动场景选择)
6. [验证部署状态](#6-验证部署状态)
7. [模板库初始化](#7-模板库初始化)
8. [日常运维](#8-日常运维)
9. [备份与恢复](#9-备份与恢复)
10. [升级](#10-升级)
11. [故障排查](#11-故障排查)

---

## 1. 环境要求

### 1.1 必需依赖

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Docker Engine | 24.0+ | `docker --version` |
| Docker Compose | v2 插件（`docker compose`） | v1（`docker-compose`）不兼容 |
| 可用内存 | 8 GB | Embedding Service 模型加载约占 4-6 GB |
| 磁盘空间 | 20 GB | 含 Docker 镜像、HuggingFace 模型缓存、数据卷 |

### 1.2 GPU 加速（推荐生产环境）

| 依赖 | 说明 |
|------|------|
| NVIDIA GPU | VRAM ≥ 8 GB（bge-m3 + reranker 合计约 6 GB） |
| NVIDIA 驱动 | 525.85.12+ |
| CUDA | 12.1+ |
| NVIDIA Container Toolkit | `nvidia-container-toolkit`，安装后需重启 Docker daemon |

> **CPU 模式**：开发环境或无 GPU 时可使用 CPU 模式，Embedding Service 会自动降级为 `BAAI/bge-small-zh-v1.5`（精度略低），生成速度较慢（单次约 3-8s）。

### 1.3 验证 GPU 环境

```bash
# 验证驱动
nvidia-smi

# 验证 Container Toolkit
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

---

## 2. 目录结构与配置文件说明

```
DV_ACODE_GEN_PLATFORM/
├── docker-compose.yml              # 基础 Compose 文件（所有环境共用）
├── docker-compose.dev.yml          # 开发覆盖层（CPU 小模型 + 热重载）
├── docker-compose.gpu-linux.yml    # Linux GPU 覆盖层
├── docker-compose.gpu-windows.yml  # Windows GPU 覆盖层
├── .env.example                    # 环境变量模板（复制为 .env 后填写）
├── .env                            # 实际配置（不提交 Git）
├── nginx.conf                      # Nginx 反向代理配置
├── backend/
│   └── lib_manager.py              # 模板库管理 CLI
└── docs/
    └── deployment.md               # 本文档
```

### 服务组成

| 服务名 | 镜像 / 构建 | 对外端口 | 说明 |
|--------|------------|---------|------|
| `nginx` | nginx:alpine | **80** | 统一入口，反向代理前后端 |
| `frontend` | 构建自 `frontend/` | — | React + Ant Design，由 Nginx 代理 |
| `backend` | 构建自 `backend/` | — | FastAPI，由 Nginx 代理 |
| `celery_worker` | 同 backend | — | 批量生成任务队列 |
| `embedding_service` | 构建自 `embedding_service/` | 8001 | bge-m3 向量推理（需 GPU） |
| `postgres` | postgres:16-alpine | — | 主数据库 |
| `redis` | redis:7-alpine | — | 缓存 + Celery broker |
| `qdrant` | qdrant/qdrant:latest | — | 向量数据库 |
| `backup` | postgres:16-alpine | — | 定时 pg_dump 备份 |

---

## 3. 环境变量配置

### 3.1 复制模板

```bash
cp .env.example .env
```

### 3.2 必须修改的变量

以下三个变量**必须**在首次启动前修改，否则服务启动时会因安全校验失败而退出。

#### JWT_SECRET_KEY

用于 JWT 签名，长度不得少于 32 字符，建议使用随机字符串。

```bash
# 生成方式（Linux/Mac）
openssl rand -hex 32

# 生成方式（Python，跨平台）
python3 -c "import secrets; print(secrets.token_hex(32))"
```

填入 `.env`：
```
JWT_SECRET_KEY=<上面命令的输出>
```

#### LLM_KEY_ENCRYPTION_SECRET

用于加密数据库中存储的 LLM API Key，必须是 64 位十六进制字符串（256-bit AES 密钥）。

```bash
# 生成方式
openssl rand -hex 32

# 验证格式：64 个 0-9a-f 字符
python3 -c "import secrets; print(secrets.token_hex(32))"
```

填入 `.env`：
```
LLM_KEY_ENCRYPTION_SECRET=<64位十六进制字符串>
```

> **重要**：此密钥一旦设置且有数据写入后，**不可更换**。更换后数据库中已加密的 API Key 将无法解密，需要重新在 Admin UI 录入所有 LLM 配置。

#### SUPER_ADMIN_PASSWORD

首次启动时自动创建的超管账号密码，建议设为强密码（12 位以上，含大小写+数字+符号）。

```
SUPER_ADMIN_PASSWORD=YourStr0ngP@ssword
SUPER_ADMIN_USERNAME=admin         # 可自定义登录名
SUPER_ADMIN_EMAIL=admin@your.com   # 可自定义邮箱
```

> 超管账号仅在数据库中**不存在同名用户时**才会自动创建（幂等操作）。首次部署后建议立即登录修改密码。

### 3.3 可选调整的变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CONFIDENCE_THRESHOLD` | `0.85` | RAG 置信度阈值，低于此值提示用户确认 |
| `CELERY_CONCURRENCY` | `10` | Celery 批量任务并发数，根据服务器 CPU 核数调整 |
| `TEMPLATE_DEDUP_THRESHOLD` | `0.90` | 模板入库语义查重阈值（0-1），越高越严格 |
| `BACKUP_RETAIN_DAYS` | `7` | pg_dump 备份保留天数 |
| `QDRANT_SNAPSHOT_ENABLED` | `false` | 是否启用 Qdrant 每周快照（大规模部署建议开启） |
| `JWT_EXPIRE_MINUTES` | `10080` | JWT 有效期（分钟），默认 7 天 |
| `RAG_STAGE1_TOP_K` | `100` | RAG 第一阶段候选数，影响召回率，不建议低于 50 |

### 3.4 CORS 配置

`.env` 不直接设置 `ALLOWED_ORIGINS`，默认值为 `["http://localhost:3000"]`。

生产环境需修改 `backend/app/core/config.py` 中的默认值，或在容器启动命令中通过环境变量传入，以匹配实际域名：

```
ALLOWED_ORIGINS=["https://dv-acode.your-company.com"]
```

---

## 4. 首次部署

### 4.1 克隆仓库

```bash
git clone <repo-url> DV_ACODE_GEN_PLATFORM
cd DV_ACODE_GEN_PLATFORM
```

### 4.2 配置环境变量

参照 [第 3 节](#3-环境变量配置) 完成 `.env` 配置：

```bash
cp .env.example .env
# 编辑 .env，至少填写以下三项：
#   JWT_SECRET_KEY
#   LLM_KEY_ENCRYPTION_SECRET
#   SUPER_ADMIN_PASSWORD
```

### 4.3 选择启动场景并启动

根据环境选择对应命令（详见 [第 5 节](#5-启动场景选择)），例如 Linux GPU 生产环境：

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu-linux.yml up -d --build
```

首次启动时 Docker 会：
1. 构建 backend / frontend / embedding_service 镜像（约 5-15 分钟，取决于网速）
2. 下载 HuggingFace 模型到 `hf_cache` volume（bge-m3 约 2.5 GB，首次较慢）
3. backend 启动时自动建表（`Base.metadata.create_all`）
4. backend 启动时自动创建超管账号（若不存在）
5. backend 启动时自动创建 Qdrant collection（若不存在）

### 4.4 配置 LLM

平台需要至少一个 LLM 配置才能进行代码生成。首次部署完成后：

1. 访问 `http://<服务器IP>/`，用超管账号登录
2. 进入 **Admin → LLM 模型管理**
3. 点击「新增配置」，填写：
   - **名称**：任意显示名，如 `Claude Sonnet 4.6`
   - **Provider**：`anthropic`（原生 Claude）或 `openai_compatible`（兼容 OpenAI 接口的第三方）
   - **API Key**：对应平台的 API Key
   - **Model ID**：如 `claude-sonnet-4-6`、`deepseek-chat`
4. 点击「测试」验证连接
5. 点击「设为默认」

---

## 5. 启动场景选择

所有命令均在项目根目录执行。基础文件 `docker-compose.yml` 始终需要，覆盖层按需叠加。

### 场景 A：开发环境（CPU，无 GPU）

使用小模型（`bge-small-zh-v1.5`）降低内存占用，后端和 Celery Worker 启用热重载。

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

特点：
- Embedding 模型为 `BAAI/bge-small-zh-v1.5`（约 200 MB），CPU 推理
- 后端代码变更后自动热重载（`--reload`）
- backend / celery_worker 将本地 `./backend` 目录挂载进容器，便于调试

### 场景 B：生产环境 — Linux GPU

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu-linux.yml up -d --build
```

特点：
- 使用完整 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3` 模型
- 通过 `runtime: nvidia` 将 GPU 透传给 embedding_service
- `-d` 后台运行

### 场景 C：生产环境 — Windows GPU（Docker Desktop）

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu-windows.yml up -d --build
```

特点：
- 通过 `deploy.resources.reservations.devices` 声明 GPU 资源（WSL2 Backend 模式）
- 需要 Docker Desktop 4.26+ 并在设置中启用 GPU support

### 场景 D：纯 CPU 生产环境（无 GPU）

直接使用基础文件，但需手动覆盖 embedding_service 的模型和设备配置：

```bash
# 在 .env 中添加以下变量
EMBED_MODEL=BAAI/bge-small-zh-v1.5
DEVICE=cpu

docker compose up -d --build
```

> 生产环境强烈建议使用 GPU（场景 B/C），CPU 推理下批量生成任务耗时显著增加。

---

## 6. 验证部署状态

### 6.1 检查容器状态

```bash
docker compose ps
```

所有服务应处于 `healthy` 或 `running` 状态：

```
NAME                STATUS
...nginx-1          running
...frontend-1       running
...backend-1        healthy
...celery_worker-1  running
...embedding_service-1  healthy
...postgres-1       healthy
...redis-1          healthy
...qdrant-1         healthy
...backup-1         running
```

### 6.2 健康检查端点

```bash
# 平台总入口
curl http://localhost/

# 后端 API 健康检查
curl http://localhost/api/health
# 期望响应：{"status": "ok"}

# Embedding Service 健康检查（容器内网）
docker compose exec backend curl http://embedding_service:8001/health
# 期望响应：{"status": "ok"}

# Qdrant 健康检查（容器内网）
docker compose exec backend curl http://qdrant:6333/healthz
```

### 6.3 访问 API 文档

浏览器访问 `http://<服务器IP>/api/docs`，应显示 FastAPI Swagger UI。

### 6.4 查看启动日志

```bash
# 查看所有服务日志
docker compose logs --tail=50

# 只看 backend 启动日志（确认建表和超管创建成功）
docker compose logs backend --tail=100

# 实时跟踪
docker compose logs -f backend
```

正常启动时 backend 日志应包含：

```
INFO:     Started server process
INFO:     Application startup complete.
```

---

## 7. 模板库初始化

项目自带示例模板，首次部署后需导入数据库和 Qdrant。

### 7.1 预检（推荐先执行）

```bash
docker compose exec backend python lib_manager.py validate --dir template_library/
```

输出示例：
```
  [OK] SVA-HAND-001.yaml
  [OK] SVA-HAND-002.yaml
  ...
全部 10 个文件验证通过
```

### 7.2 导入模板库

```bash
docker compose exec backend python lib_manager.py import --dir template_library/
```

输出示例：
```
发现 10 个模板文件
  [导入] Valid-Ready数据稳定性断言
  [导入] Valid-Ready响应超时检测断言
  ...
完成: 导入=10 名称冲突=0 语义重复=0 失败=0
```

如需跳过语义查重强制导入（如重建环境时）：

```bash
docker compose exec backend python lib_manager.py import --force
```

### 7.3 验证导入结果

```bash
docker compose exec backend python lib_manager.py list
```

输出示例：
```
ID                               CODE_TYPE    MATURITY   NAME
────────────────────────────────────────────────────────────────
SVA-HAND-001                     assertion    production Valid-Ready数据稳定性断言
SVA-HAND-002                     assertion    production Valid-Ready响应超时检测断言
...
```

### 7.4 Qdrant 同步状态检查

如导入后遇到 `sync_status=pending` 未同步的模板，手动触发重建：

```bash
docker compose exec backend python lib_manager.py rebuild
```

---

## 8. 日常运维

### 8.1 启停服务

```bash
# 停止所有服务（保留数据卷）
docker compose down

# 重启单个服务
docker compose restart backend

# 重新构建并启动（代码更新后）
docker compose up -d --build backend celery_worker

# 查看资源占用
docker stats
```

### 8.2 查看日志

```bash
# 实时跟踪所有服务
docker compose logs -f

# 查看指定服务最近 200 行
docker compose logs --tail=200 embedding_service

# 查看 Celery 任务执行情况
docker compose logs -f celery_worker
```

### 8.3 lib_manager.py 常用命令

所有命令在容器内执行：`docker compose exec backend python lib_manager.py <子命令>`

| 子命令 | 说明 |
|--------|------|
| `validate [--dir DIR]` | 验证 YAML 模板文件语法，不写库 |
| `import [--dir DIR] [--force]` | 导入模板到 PG + Qdrant |
| `export [--dir DIR]` | 将数据库模板导出为 YAML 文件 |
| `rebuild [--collection NAME]` | 重建 Qdrant 向量索引 |
| `backup` | 手动触发 PostgreSQL pg_dump 备份 |
| `list [--code-type TYPE]` | 列出数据库中的模板 |

### 8.4 进入容器调试

```bash
# 进入 backend 容器
docker compose exec backend bash

# 执行数据库迁移（如有新迁移文件）
docker compose exec backend alembic upgrade head

# 查看当前迁移版本
docker compose exec backend alembic current

# 连接 PostgreSQL
docker compose exec postgres psql -U dvuser -d dv_platform

# 连接 Redis
docker compose exec redis redis-cli
```

---

## 9. 备份与恢复

### 9.1 自动备份

`backup` 容器每 24 小时自动执行一次 `pg_dump`，备份文件存储在 `backend_backups` volume 中，保留最近 `BACKUP_RETAIN_DAYS`（默认 7）天的备份。

查看备份文件列表：

```bash
docker compose exec backup ls -lh /backups/
```

### 9.2 手动备份

```bash
# 通过 lib_manager（在容器内执行，输出到 /app/backups/）
docker compose exec backend python lib_manager.py backup

# 直接执行 pg_dump（在宿主机，输出到当前目录）
docker compose exec -e PGPASSWORD=dvpassword postgres \
  pg_dump -U dvuser -d dv_platform -F c -f /tmp/manual_backup.dump
docker compose cp postgres:/tmp/manual_backup.dump ./manual_backup.dump
```

### 9.3 从备份恢复 PostgreSQL

> **警告**：恢复操作会覆盖当前数据库中的全部数据，请确认操作后果。

```bash
# 1. 停止后端服务（避免写入冲突）
docker compose stop backend celery_worker

# 2. 将备份文件复制进 postgres 容器
docker compose cp ./dv_platform_20260427_020000.dump postgres:/tmp/restore.dump

# 3. 执行恢复（pg_restore 会先清空再写入）
docker compose exec -e PGPASSWORD=dvpassword postgres \
  pg_restore -U dvuser -d dv_platform --clean --if-exists /tmp/restore.dump

# 4. 重建 Qdrant 向量索引（PG 恢复后 Qdrant 可能与 PG 不一致）
docker compose start backend
docker compose exec backend python lib_manager.py rebuild

# 5. 重启所有服务
docker compose restart
```

### 9.4 Qdrant 数据重建

如 Qdrant 数据损坏，可从 PostgreSQL 完整重建：

```bash
# 删除旧 collection（慎重）
curl -X DELETE http://localhost:6333/collections/templates

# 重新创建（backend 重启时自动创建）
docker compose restart backend

# 全量同步向量
docker compose exec backend python lib_manager.py rebuild
```

---

## 10. 升级

### 10.1 代码升级流程

```bash
# 1. 拉取新代码
git pull origin main

# 2. 查看 CHANGELOG.md，确认是否有破坏性变更或迁移说明

# 3. 重新构建镜像并重启
docker compose up -d --build

# 4. 执行数据库迁移（如有）
docker compose exec backend alembic upgrade head

# 5. 验证服务健康
docker compose ps
curl http://localhost/api/health
```

### 10.2 仅更新后端

```bash
docker compose up -d --build backend celery_worker
docker compose exec backend alembic upgrade head
```

### 10.3 Embedding 模型升级

更换 bge-m3 版本后，旧向量与新模型不兼容，需全量重建 Qdrant 索引：

```bash
# 1. 更新 docker-compose.yml 中 EMBED_MODEL 环境变量后重启
docker compose up -d --build embedding_service

# 2. 清空旧向量（backend 重启时会自动重建 collection）
curl -X DELETE http://localhost:6333/collections/templates
docker compose restart backend

# 3. 全量重建向量索引
docker compose exec backend python lib_manager.py rebuild
```

---

## 11. 故障排查

### 11.1 backend 启动失败

**现象**：`docker compose ps` 显示 backend 反复重启，或 `unhealthy`

**排查步骤**：

```bash
docker compose logs backend --tail=50
```

常见错误及处理：

| 错误信息 | 原因 | 处理 |
|---------|------|------|
| `jwt_secret_key must be a random string of at least 32 characters` | `.env` 中 `JWT_SECRET_KEY` 未修改或太短 | 生成并填入 32+ 位随机字符串 |
| `llm_key_encryption_secret must be a 64-char hex string` | `LLM_KEY_ENCRYPTION_SECRET` 格式错误 | 用 `openssl rand -hex 32` 生成 64 位 hex 字符串 |
| `could not connect to server: Connection refused` | PostgreSQL 尚未就绪 | 等待 postgres 容器 healthy 后 backend 会自动重试 |
| `connection refused` (qdrant) | Qdrant 尚未就绪 | 同上，等待即可 |

### 11.2 Embedding Service 启动慢

首次启动时需从 HuggingFace 下载模型（bge-m3 约 2.5 GB），在国内网络环境下可能很慢。

**加速方式**：

```bash
# 方式一：挂载预下载好的模型目录
# 在宿主机提前下载模型到 ~/hf_models/，然后在 docker-compose.yml 中挂载：
# volumes:
#   - ~/hf_models:/root/.cache/huggingface

# 方式二：设置 HuggingFace 镜像（在 .env 中添加）
HF_ENDPOINT=https://hf-mirror.com
```

### 11.3 RAG 返回置信度异常低

**可能原因**：
- 模板库尚未导入（执行 [第 7 节](#7-模板库初始化)）
- Qdrant 向量与 PG 不同步（执行 `lib_manager.py rebuild`）
- Embedding Service 使用了 CPU 小模型（检查 `EMBED_MODEL` 环境变量）

```bash
# 检查 Qdrant 中的向量数量
curl http://localhost:6333/collections/templates | python3 -m json.tool
# vectors_count 应与数据库模板数量一致
```

### 11.4 批量任务卡死 / 不执行

**排查**：

```bash
# 查看 Celery Worker 日志
docker compose logs -f celery_worker

# 检查 Redis 连接（在 celery_worker 容器内）
docker compose exec celery_worker redis-cli -u redis://redis:6379/1 ping
# 期望响应：PONG
```

常见原因：Redis 未就绪、并发数不足（调大 `CELERY_CONCURRENCY`）、任务超时（单条生成 > 60s 通常是 LLM 响应慢）。

### 11.5 前端无法访问 API

**排查**：

```bash
# 检查 Nginx 配置是否生效
docker compose exec nginx nginx -t

# 检查后端是否正常响应
docker compose exec nginx curl http://backend:8000/health

# 查看 Nginx 错误日志
docker compose logs nginx
```

如果 API 请求返回 413 错误，是文件上传超出 Nginx `client_max_body_size`（当前限制 50M），可修改 `nginx.conf` 后重启 Nginx。

### 11.6 数据卷清理（重置环境）

> **危险操作**，会删除所有数据，仅用于完全重置开发环境。

```bash
# 停止并删除容器和数据卷
docker compose down -v

# 重新启动（从零开始）
docker compose up -d --build
```
