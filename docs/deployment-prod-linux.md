# Linux 公司内网生产部署手册

**适用版本**：v1.0.0
**适用环境**：Ubuntu 22.04+ / Rocky Linux 9+ / CentOS Stream 9+，公司内网
**适用读者**：IT / 运维 / DevOps，负责把平台部署到生产服务器

> 网络假设：**受限外网** — 不可直连 docker.io / huggingface.co / api.anthropic.com，但可访问公司内部 Docker registry mirror、HuggingFace mirror 与 PyPI mirror。
> 完全离线场景请参照 §3「Mirror 替代方案」补充离线打包流程。
>
> 本机开发部署（Win11 + Docker Desktop）请看 [deployment-dev-windows.md](deployment-dev-windows.md)。

---

## 目录

1. [服务器规格要求](#1-服务器规格要求)
2. [系统级前置安装](#2-系统级前置安装)
3. [内网 Mirror 配置](#3-内网-mirror-配置)
4. [模型预下载与挂载](#4-模型预下载与挂载)
5. [首次部署流程](#5-首次部署流程)
6. [模板库初始化](#6-模板库初始化)
7. [验证与健康检查](#7-验证与健康检查)
8. [备份与恢复](#8-备份与恢复)
9. [升级流程](#9-升级流程)
10. [监控与故障排查](#10-监控与故障排查)
11. [安全加固清单](#11-安全加固清单)

---

## 1. 服务器规格要求

### 1.1 硬件最低 / 推荐

| 资源 | 最低 | 推荐 | 备注 |
|---|---|---|---|
| CPU | 8 核 | 16 核 | 影响 Celery 并发上限 |
| RAM | 16 GB | 32 GB | embedding_service 单独需 6-8 GB；预留 PG / Redis / 系统约 8 GB |
| 磁盘 | 100 GB SSD | 200 GB+ | Docker 镜像 ~10 GB、模型 ~3 GB、PG 数据增长、备份保留 7 天 |
| GPU（可选）| — | NVIDIA 显卡 ≥ 8 GB VRAM | BGE-M3 + Reranker 共 ~6 GB；RTX 3060 / Tesla T4 / A2 等都够 |
| 网络 | 千兆 | 万兆 | 内网到 mirror 的拉取速度直接影响首次部署 |

### 1.2 操作系统

| 发行版 | 验证状态 | 备注 |
|---|---|---|
| Ubuntu 22.04 LTS | ✅ 推荐 | 本平台主开发环境 |
| Ubuntu 24.04 LTS | ✅ | NVIDIA 驱动需 > 525 |
| Rocky Linux 9 | ✅ | RHEL 兼容 |
| CentOS Stream 9 | ✅ | 同上 |
| Debian 12 | 🟡 | 可用，nvidia-container-toolkit 安装步骤不同 |

### 1.3 GPU 软件栈版本

```
NVIDIA 驱动 ≥ 525.85.12
CUDA Runtime 12.1（容器内自带，主机上有兼容驱动即可）
nvidia-container-toolkit ≥ 1.14
```

---

## 2. 系统级前置安装

以下命令以 Ubuntu 22.04 为例。其他发行版请按 Docker / NVIDIA 官方文档调整。

### 2.1 Docker Engine + Compose plugin

```bash
# 卸载旧版本（如有）
sudo apt remove -y docker docker-engine docker.io containerd runc

# 添加 Docker 官方 GPG（若内网有 mirror，下面 URL 替换为 mirror 地址）
sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 让当前用户免 sudo 跑 docker
sudo usermod -aG docker $USER
newgrp docker

# 验证
docker --version            # 期望 ≥ 24.0
docker compose version      # 期望 ≥ v2.20
```

### 2.2 NVIDIA Container Toolkit（仅 GPU 部署）

```bash
# 添加 nvidia-container-toolkit 源
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update && sudo apt install -y nvidia-container-toolkit

# 配置 Docker 默认使用 nvidia runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# 验证
nvidia-smi                                                          # 主机看到 GPU
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi   # 容器看到 GPU
```

---

## 3. 内网 Mirror 配置

### 3.1 Docker Registry Mirror

把 docker.io 拉取代理到内部 harbor / nexus / 自建 registry mirror：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": [
    "https://harbor.company.internal",
    "https://docker-mirror.company.internal"
  ],
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  }
}
EOF
sudo systemctl restart docker
```

如果公司用的是**私有 registry**（带认证）：

```bash
docker login harbor.company.internal
# 登录信息持久化在 ~/.docker/config.json，docker compose 自动复用
```

### 3.2 HuggingFace Mirror（关键）

embedding_service 启动时会自动从 HuggingFace 下载 BGE-M3 + Reranker。如果走外网会失败。两种方案：

**方案 A：走内网 HF mirror**（推荐，省事）

在 `.env` 中加：

```ini
HF_ENDPOINT=https://hf-mirror.company.internal
```

并在 `docker-compose.yml` 的 `embedding_service` 服务里加进 `environment`：

```yaml
embedding_service:
  environment:
    - EMBED_MODEL=BAAI/bge-m3
    - RERANK_MODEL=BAAI/bge-reranker-v2-m3
    - DEVICE=cuda
    - HF_ENDPOINT=${HF_ENDPOINT}      # 新增
```

**方案 B：完全离线 + bind mount 模型**（最严内网用）

见 [§4 模型预下载与挂载](#4-模型预下载与挂载)。

### 3.3 PyPI Mirror

backend / embedding_service 镜像构建时跑 `pip install`。如果内网 PyPI 镜像（如 `https://pypi.company.internal/simple`）：

在 `backend/Dockerfile`、`embedding_service/Dockerfile.gpu` 的 `RUN pip install` 行前加：

```dockerfile
RUN pip config set global.index-url https://pypi.company.internal/simple && \
    pip config set global.trusted-host pypi.company.internal
```

或者在 build 时通过 `--build-arg`：

```bash
docker compose build --build-arg PIP_INDEX_URL=https://pypi.company.internal/simple
```

### 3.4 npm Mirror

frontend 镜像构建时跑 `npm install`。在 `frontend/Dockerfile` 的 `RUN npm install` 前加：

```dockerfile
RUN npm config set registry https://npm.company.internal/
```

---

## 4. 模型预下载与挂载

### 4.1 用 huggingface-cli 下载到本地（外网机器上）

如果有一台能访问外网的临时机器（或运维 Win 工位）：

```bash
pip install huggingface-hub
huggingface-cli download BAAI/bge-m3 --local-dir ./models/bge-m3
huggingface-cli download BAAI/bge-reranker-v2-m3 --local-dir ./models/bge-reranker-v2-m3
```

完成后 `./models/` 目录约 2.6 GB，包含两个子目录。**用 U 盘 / scp / 内网共享**搬到生产服务器。

### 4.2 在生产服务器上挂载

把 `./models/` 放到项目根目录（`DV_ACODE_GEN_PLATFORM/models/`），改 `docker-compose.yml` 的 `embedding_service` 服务：

```yaml
embedding_service:
  volumes:
    - ./models:/models:ro                 # 新增：bind mount 模型目录
    - hf_cache:/root/.cache/huggingface   # 保留：作为后备缓存
  environment:
    - EMBED_MODEL=/models/bge-m3                  # 改为本地路径
    - RERANK_MODEL=/models/bge-reranker-v2-m3
    - DEVICE=cuda
```

> FlagEmbedding 库支持把 `model_name` 直接传成本地目录路径。

### 4.3 模型升级流程

新版本 BGE-M3 发布后：

```bash
# 1. 在外网机器下新版到 ./models-new/bge-m3
# 2. scp 到生产服务器，覆盖 ./models/bge-m3
# 3. 重启 embedding_service
docker compose restart embedding_service

# 4. 旧向量与新模型不兼容，必须重建 Qdrant
docker compose exec backend python lib_manager.py rebuild
```

---

## 5. 首次部署流程

### 5.1 获取代码

如果内网有 git 服务器：

```bash
git clone https://git.company.internal/dv-team/DV_ACODE_GEN_PLATFORM.git
cd DV_ACODE_GEN_PLATFORM
```

如果没有，用打包文件：

```bash
# 在外网机：
git clone <repo-url> DV_ACODE_GEN_PLATFORM
cd DV_ACODE_GEN_PLATFORM
tar czf ../DV_ACODE_GEN_PLATFORM.tar.gz --exclude='.git' --exclude='node_modules' --exclude='dist' .

# 拷贝 tar.gz 到内网，解压
tar xzf DV_ACODE_GEN_PLATFORM.tar.gz
cd DV_ACODE_GEN_PLATFORM
```

### 5.2 配置 `.env`（生产强约束）

```bash
cp .env.example .env
chmod 600 .env       # 只允许文件所有者读写，防止 secret 泄漏
```

编辑 `.env`，**所有 secret 必须用强随机生成**：

```bash
# 在 shell 里生成强随机 secret
JWT=$(openssl rand -hex 32)
ENC=$(openssl rand -hex 32)
echo "JWT_SECRET_KEY=$JWT"
echo "LLM_KEY_ENCRYPTION_SECRET=$ENC"
```

填入 `.env`：

```ini
# 必填强 secret
JWT_SECRET_KEY=<openssl rand -hex 32 输出>
LLM_KEY_ENCRYPTION_SECRET=<openssl rand -hex 32 输出>

# 超管账号
SUPER_ADMIN_USERNAME=admin
SUPER_ADMIN_PASSWORD=<生产环境强密码，12+ 位含大小写 + 数字 + 符号>
SUPER_ADMIN_EMAIL=admin@your-company.com

# 数据库（如需改用外部 PG）
DATABASE_URL=postgresql+asyncpg://dvuser:<DB_PASSWORD>@postgres:5432/dv_platform

# RAG 阈值（按业务调）
CONFIDENCE_THRESHOLD=0.85
RAG_STAGE1_TOP_K=100
RAG_STAGE2_TOP_K=20
RAG_STAGE3_TOP_K=3

# 模板查重阈值
TEMPLATE_DEDUP_THRESHOLD=0.90

# Celery 并发（按 CPU 核数）
CELERY_CONCURRENCY=10

# 备份保留
BACKUP_RETAIN_DAYS=7
QDRANT_SNAPSHOT_ENABLED=false

# HF mirror（按 §3.2 配置）
HF_ENDPOINT=https://hf-mirror.company.internal

# CORS（生产域名）— 注意 backend/app/core/config.py 的默认值需同步改
ALLOWED_ORIGINS=["https://dv-acode.your-company.com"]
```

> ⚠️ `LLM_KEY_ENCRYPTION_SECRET` 一旦设置且有数据写入后**不可更换**。换了之后数据库中已加密的 LLM API Key 全部解密失败。

### 5.3 启动栈

**带 GPU**：

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu-linux.yml up -d --build
```

**纯 CPU**（小规模生产可接受，单次生成 30-60s）：

```bash
# 在 .env 添加
EMBED_MODEL=BAAI/bge-small-zh-v1.5
DEVICE=cpu

# 启动
docker compose up -d --build
```

首次启动 backend 自动：
1. 创建 PostgreSQL 表（`Base.metadata.create_all`）
2. 创建超管账号（若不存在）
3. 创建 Qdrant collection（若不存在）

---

## 6. 模板库初始化

```bash
# 1. 预检 YAML 语法（不写库）
docker compose exec backend python lib_manager.py validate

# 2. 导入到 PG + 同步 Qdrant
docker compose exec backend python lib_manager.py import

# 3. 验证
docker compose exec backend python lib_manager.py list
```

预期输出：

```
ID                               CODE_TYPE    MATURITY    NAME
─────────────────────────────────────────────────────────────────────
ast_data_integrity_v1            assertion    production  数据完整性断言
ast_fsm_state_transition_v1      assertion    production  状态机转换断言
...

共 10 个模板
```

如果 Qdrant 同步异常（`sync_status=pending`）：

```bash
docker compose exec backend python lib_manager.py rebuild
```

---

## 7. 验证与健康检查

### 7.1 容器状态

```bash
docker compose ps
```

期望全部 `Up`，关键服务带 `(healthy)`：postgres / redis / qdrant / embedding_service。

### 7.2 健康端点

```bash
curl http://localhost/                     # 前端 200
curl http://localhost/api/health           # {"status":"ok"}
```

容器内健康（用 backend 的 httpx 而非 curl，因为基础镜像不带 curl）：

```bash
docker compose exec backend python -c \
  "import httpx, asyncio; r = asyncio.run(httpx.AsyncClient().get('http://embedding_service:8001/health')); print(r.text)"

docker compose exec backend python -c \
  "import httpx, asyncio; r = asyncio.run(httpx.AsyncClient().get('http://qdrant:6333/healthz')); print(r.text)"
```

### 7.3 API 文档

浏览器访问 `https://<生产域名>/api/docs`，FastAPI Swagger UI 应正常显示。

> ⚠️ 生产环境**建议关闭** `/api/docs`、`/api/redoc` 暴露（修改 [backend/app/main.py](../backend/app/main.py) 把 `docs_url=None`）。详见 §11 安全加固。

### 7.4 LLM 配置

浏览器登录 → **Admin → LLM 配置** → 添加生产 LLM 配置（智谱 GLM、DeepSeek、内部 Ollama 等）→ 测试 → 设为默认。

---

## 8. 备份与恢复

### 8.1 自动备份

`backup` 服务每 24 小时自动 `pg_dump`，存到 `backend_backups` volume，保留 `BACKUP_RETAIN_DAYS` 天（默认 7）。

```bash
# 查看备份列表
docker compose exec backup ls -lh /backups/

# 备份默认存储位置（容器内）
/backups/dv_platform_<日期时间>.dump
```

> 想把备份文件输出到主机磁盘以便归档，改 `docker-compose.yml`：把 `backend_backups` named volume 改为 bind mount，例如 `./backups:/backups`。

### 8.2 手动备份

```bash
docker compose exec backend python lib_manager.py backup
# 备份输出在 /app/backups/ 容器内
```

或直接 `pg_dump`：

```bash
docker compose exec -e PGPASSWORD=dvpassword postgres \
  pg_dump -U dvuser -d dv_platform -F c -f /tmp/backup.dump
docker compose cp postgres:/tmp/backup.dump ./backup-$(date +%Y%m%d).dump
```

### 8.3 从备份恢复 PostgreSQL

> ⚠️ **覆盖当前数据库全部内容**，操作前再三确认

```bash
# 1. 停止后端写入
docker compose stop backend celery_worker

# 2. 备份文件入 PG 容器
docker compose cp ./backup-20260501.dump postgres:/tmp/restore.dump

# 3. 执行恢复（pg_restore 会先 DROP 再 CREATE）
docker compose exec -e PGPASSWORD=dvpassword postgres \
  pg_restore -U dvuser -d dv_platform --clean --if-exists /tmp/restore.dump

# 4. PG 恢复后 Qdrant 必然不一致，全量重建
docker compose start backend
docker compose exec backend python lib_manager.py rebuild

# 5. 重启所有服务
docker compose restart
```

### 8.4 Qdrant 重建（不依赖备份）

Qdrant 是**派生数据**，可由 PostgreSQL 模板表完整重建：

```bash
# 删除旧 collection
docker compose exec backend python -c \
  "import httpx, asyncio; asyncio.run(httpx.AsyncClient().delete('http://qdrant:6333/collections/templates'))"

# backend 重启时自动重建空 collection
docker compose restart backend

# 全量同步向量
docker compose exec backend python lib_manager.py rebuild
```

---

## 9. 升级流程

### 9.1 代码升级（普通版本）

```bash
# 1. 拉取最新代码
git pull origin master

# 2. 看 CHANGELOG.md 是否有破坏性变更或迁移说明
cat CHANGELOG.md | head -30

# 3. 重新构建 + 重启
docker compose -f docker-compose.yml -f docker-compose.gpu-linux.yml up -d --build

# 4. 数据库迁移（如有 alembic 文件更新）
docker compose exec backend alembic upgrade head

# 5. 验证
docker compose ps
curl http://localhost/api/health
```

### 9.2 仅更新 backend

```bash
docker compose up -d --build backend celery_worker
docker compose exec backend alembic upgrade head
```

### 9.3 仅更新前端

```bash
# 在能访问 npm 的机器上 build（或在生产机上配 npm mirror 后 build）
cd frontend
npm install
npm run build

# 把 dist/ 放到生产机
cd ..
# frontend 镜像里直接 COPY dist 进 nginx，需要重 build：
docker compose build frontend
docker compose up -d frontend
```

### 9.4 模型升级

见 [§4.3](#43-模型升级流程)。

---

## 10. 监控与故障排查

### 10.1 资源监控

```bash
# 容器实时资源
docker stats

# 单服务 CPU / 内存
docker compose top backend
```

可接 Prometheus / Grafana 监控 Docker daemon 指标（`/var/run/docker.sock`）。

### 10.2 GPU 不可用

**现象**：`embedding_service` 启动报 `CUDA initialization failed` 或推理回退到 CPU 慢。

**排查：**

```bash
# 1. 主机 GPU 是否正常
nvidia-smi

# 2. Docker 是否能用 GPU
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi

# 3. 容器内是否能看到 GPU
docker compose exec embedding_service nvidia-smi

# 4. 看 embedding_service 启动日志
docker compose logs embedding_service --tail=100 | grep -i "cuda\|gpu\|device"
```

**常见原因：**
- nvidia-container-toolkit 未装或未 `nvidia-ctk runtime configure`
- 主机驱动版本太低（< 525）
- `docker-compose.gpu-linux.yml` overlay 没加载（缺 `-f docker-compose.gpu-linux.yml`）

### 10.3 Embedding 启动慢

首次启动需下载模型（~3 GB）。如果走 mirror 仍慢：

```bash
# 看具体在等什么
docker compose logs -f embedding_service
```

如果反复看到 `Downloading...` 长时间没完，把模型预下载到 `./models/` 用 bind mount 替代（[§4](#4-模型预下载与挂载)）。

### 10.4 备份盘满

```bash
# 看 backup volume 大小
docker volume inspect dv_acode_gen_platform_backend_backups | grep Mountpoint
sudo du -sh <Mountpoint>

# 手动清理 7 天前备份（自动备份脚本已做这个，备份盘满说明 cron 没跑）
docker compose exec backup find /backups -name "*.dump" -mtime +7 -delete
```

### 10.5 backend 启动失败

```bash
docker compose logs backend --tail=80
```

常见错误对照：

| 错误信息 | 原因 | 处理 |
|---|---|---|
| `jwt_secret_key must be a random string of at least 32 characters` | `.env` 中 `JWT_SECRET_KEY` 太短 | 用 `openssl rand -hex 32` 重新生成 |
| `llm_key_encryption_secret must be a 64-char hex string` | 不是 64 位 hex | 用 `openssl rand -hex 32`，必须 64 个 0-9a-f 字符 |
| `could not connect to postgres` | PG 未就绪 | 等 postgres `(healthy)` 后 backend 自动重试 |
| `connection refused` (qdrant/redis) | 同上 | 等就绪 |

### 10.6 Celery 批量任务卡死

```bash
# 看 worker 日志
docker compose logs -f celery_worker

# 检查 Redis broker
docker compose exec celery_worker python -c \
  "import redis; r = redis.Redis.from_url('redis://redis:6379/1'); print(r.ping())"
# 期望 True

# 调大并发（改 .env 后重启）
CELERY_CONCURRENCY=20
docker compose up -d celery_worker
```

---

## 11. 安全加固清单

生产部署**必须**完成以下加固：

### 11.1 文件权限

```bash
chmod 600 .env                      # secret 文件只允许 owner 读
chown root:root .env                # 或部署账号
chmod 644 docker-compose.yml        # 普通 readable
```

### 11.2 强 Secret

| 变量 | 强度要求 |
|---|---|
| `JWT_SECRET_KEY` | ≥ 32 字符随机字符串（openssl rand -hex 32） |
| `LLM_KEY_ENCRYPTION_SECRET` | 必须是 64 位 hex（256-bit AES key） |
| `SUPER_ADMIN_PASSWORD` | ≥ 12 字符，含大小写 + 数字 + 符号 |
| 数据库密码 | ≥ 16 字符，与系统用户密码不同 |

### 11.3 关闭开发用接口

修改 `backend/app/main.py`，生产环境关闭 API 文档：

```python
app = FastAPI(
    ...,
    docs_url=None,           # 关闭 /api/docs
    redoc_url=None,          # 关闭 /api/redoc
    openapi_url=None,        # 关闭 OpenAPI JSON
)
```

或者通过环境变量条件开关：

```python
import os
DOCS_ENABLED = os.getenv("ENABLE_API_DOCS", "false").lower() == "true"
app = FastAPI(
    docs_url="/api/docs" if DOCS_ENABLED else None,
    ...
)
```

### 11.4 反向代理 HTTPS

生产环境**必须** HTTPS。在公司 Nginx / 负载均衡前置层做 TLS 终结，不暴露 80 端口直连：

```nginx
# 公司前置 Nginx
server {
    listen 443 ssl;
    server_name dv-acode.your-company.com;
    ssl_certificate     /etc/ssl/certs/dv-acode.crt;
    ssl_certificate_key /etc/ssl/private/dv-acode.key;

    location / {
        proxy_pass http://<本机 IP>:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

记得同步改 `.env` 的 `ALLOWED_ORIGINS` 为 HTTPS 域名。

### 11.5 防火墙

```bash
# 只开内网必要端口（举例：仅允许公司内网 10.x.x.x/8 访问）
sudo ufw allow from 10.0.0.0/8 to any port 80
sudo ufw allow from 10.0.0.0/8 to any port 443
sudo ufw allow ssh
sudo ufw enable
```

### 11.6 LLM API Key 安全

- 通过 Admin UI 录入，不要写在 `.env`（`ANTHROPIC_API_KEY` 在 `.env` 里只是初始化兼容字段，实际调用读 PG 加密存储）
- 数据库中所有 API Key 已用 AES-256-GCM 加密（密钥来自 `LLM_KEY_ENCRYPTION_SECRET`）
- 严禁日志中输出明文 Key（已通过 `mask_api_key()` 在所有 API 响应中掩码）

### 11.7 定期备份验证

每月做一次**恢复演练**：

```bash
# 1. 在测试环境跑一次 §8.3 的恢复流程
# 2. 验证恢复后服务可用、模板齐全
# 3. 记录恢复耗时（用于 RTO 评估）
```

---

## 索引

- 项目架构：[ARCHITECTURE.md](../ARCHITECTURE.md)
- 产品需求：[PRD.md](../PRD.md)
- Win11 本机开发部署：[deployment-dev-windows.md](deployment-dev-windows.md)
- 部署文档总入口：[deployment.md](deployment.md)
- 团队协作流程：[CONTRIBUTING.md](../CONTRIBUTING.md)
