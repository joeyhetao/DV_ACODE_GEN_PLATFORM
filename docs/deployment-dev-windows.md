# Win11 本机开发部署手册

**适用版本**：v1.0.0
**适用环境**：Windows 11 + Docker Desktop（WSL2 后端）
**适用读者**：本机日常开发、单人测试、给项目改代码的人

> 生产环境（Linux 服务器）部署请看 [deployment-prod-linux.md](deployment-prod-linux.md)。
> 团队协作流程（分支、commit 规范）看 [CONTRIBUTING.md](../CONTRIBUTING.md)。

---

## 目录

1. [环境要求](#1-环境要求)
2. [一次性环境优化](#2-一次性环境优化)
3. [首次启动流程](#3-首次启动流程)
4. [日常开发工作流](#4-日常开发工作流)
5. [LLM 配置](#5-llm-配置)
6. [验证服务状态](#6-验证服务状态)
7. [模板库导入](#7-模板库导入)
8. [常见问题与故障排查](#8-常见问题与故障排查)

---

## 1. 环境要求

### 1.1 必需

| 工具 | 最低版本 | 备注 |
|---|---|---|
| Windows 11 Pro / Home | 21H2+ | 需启用 WSL2 |
| Docker Desktop | 4.26+ | 内含 Compose v2 插件 |
| WSL2 | — | Docker Desktop 安装时自动启用 |
| Node.js | 20 LTS | 前端 build；命令行 `node --version` 验证 |
| Python | 3.11 | 仅在主机上跑 `lib_manager.py` 时需要；容器内已自带 |
| Git | 2.40+ | 克隆仓库 |
| 物理内存 | **16 GB**（最低 12 GB）| WSL2 + 9 个容器最少需 8 GB，留给 Windows 桌面 |
| 磁盘 | 30 GB 空闲 | Docker 镜像 + WSL VHDX + HuggingFace 模型 |

### 1.2 GPU 可选

GPU 不是必须的：

- **没 GPU**：embedding_service 自动用 CPU 推理 BGE-M3 + BGE-reranker-v2-m3（两个模型分别用于向量化和 RAG 三阶段重排），单次生成 ~30s（dev overlay 下用小模型 `bge-small-zh-v1.5` 约 ~5s）
- **有 NVIDIA GPU**：BGE-M3 + Reranker 加载到 GPU 显存（共 ~6 GB），单次推理 ~50ms。Docker Desktop 4.26+ 在 WSL2 下自动支持 GPU passthrough，无需额外配置

GPU 验证：

```powershell
# 主机看到 GPU
nvidia-smi

# 容器看到 GPU
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

---

## 2. 一次性环境优化

> 本节配置只需做一次，之后所有项目都受益。

### 2.1 `.wslconfig` — 限制 WSL2 资源

WSL2 默认会贪占主机内存，频繁导致 Docker daemon 在内存压力下崩溃。在 `C:\Users\<你的用户名>\.wslconfig`（不存在就新建）写入：

```ini
[wsl2]
memory=10GB                    # WSL 内存上限（建议主机 RAM 的 60-65%）
processors=8                   # WSL 可用 CPU 核数（主机的 40-50%）
swap=4GB                       # 交换分区
localhostForwarding=true

[experimental]
autoMemoryReclaim=disabled     # 关闭 Windows 主动回收 WSL 内存，避免 CUDA 抖动
```

修改后必须 `wsl --shutdown` 让设置生效。Docker Desktop 会自动重启 WSL2 后端。

### 2.2 Docker Desktop 设置

**Settings → Resources**：把 Memory 上限设为略低于 `.wslconfig` 的 `memory` 值（例如 9 GB），给 Linux 内核留点缓冲。

**Settings → Resources → File Sharing**（如果用 bind mount）：
- Windows 项目目录所在盘（一般是 D:）勾选共享

### 2.3 验证 WSL 配置生效

```powershell
docker run --rm alpine sh -c "cat /proc/meminfo | head -1"
# MemTotal 应接近 10 GB（10184924 KB 左右）
```

---

## 3. 首次启动流程

### 3.1 克隆仓库

```powershell
cd D:\tools\github
git clone <repo-url> DV_ACODE_GEN_PLATFORM
cd DV_ACODE_GEN_PLATFORM
```

### 3.2 配置 `.env`

```powershell
copy .env.example .env
```

编辑 `.env`，**开发环境只需修改 3 个变量**（强度要求低于生产）：

```ini
# 32 字符以上随机字符串即可，dev 用占位也能跑
JWT_SECRET_KEY=dev-jwt-secret-pad-this-to-at-least-32-chars

# 64 个 hex 字符（即 32 字节 = 256-bit AES key，注意"64 位"指字符数不是 bit 数）
# PowerShell 生成方式：
# -join ((48..57 + 97..102) | Get-Random -Count 64 | %{[char]$_})
LLM_KEY_ENCRYPTION_SECRET=00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff

# dev 用简单密码即可（注意不要在生产复用）
SUPER_ADMIN_PASSWORD=YourDevPassword
```

其他变量保持默认。

### 3.3 前端首次构建

前端用 bind mount 把 `frontend/dist/` 挂进容器，**必须先 build 才能启动**：

> 本节命令在 **PowerShell** 中运行（不是 WSL bash）。`npm` 由你装的 Node.js 提供，是 Windows 全局可执行命令。如果用了反引号续行（` `` `），那是 PowerShell 风格；用 bash 则换成反斜杠 `\`。

```powershell
cd frontend
npm install
npm run build
cd ..
```

完成后 `frontend/dist/` 应有 `index.html` 和 `assets/index-*.js`。

### 3.4 启动完整栈

```powershell
docker compose `
  -f docker-compose.yml `
  -f docker-compose.dev.yml `
  -f docker-compose.hotreload.yml `
  up -d
```

三个 overlay 的作用：

- `docker-compose.yml`：基础栈（9 个服务）+ `restart: unless-stopped`
- `docker-compose.dev.yml`：embedding 用 CPU 小模型 `bge-small-zh-v1.5`（200 MB）替代 BGE-M3（2 GB），加速首次启动
- `docker-compose.hotreload.yml`：后端 `--reload`、源码挂载、前端 dist bind mount

首次启动 5-10 分钟（拉镜像 + build + 下载小模型）。

### 3.5 等待服务就绪

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
```

9 个容器全 `Up` 且关键三项 `(healthy)`：postgres / redis / qdrant / embedding_service。

---

## 4. 日常开发工作流

### 4.1 改后端代码（`backend/app/**.py`）

后端走 hot reload，**无需任何 docker 操作**。改完保存，等 1-2 秒看 backend 日志：

```powershell
docker logs dv_acode_gen_platform-backend-1 --tail 5
# 应看到 "WatchFiles detected changes" → "Started server process"
```

### 4.2 改前端代码（`frontend/src/**.tsx`）

```powershell
cd frontend
npm run build           # 重建 dist/，bind mount 自动反映到容器
cd ..
```

浏览器 **Ctrl + F5** 强制刷新（或开无痕窗口）拉取新 bundle。

> 前端容器的 nginx 已配 `index.html` 不缓存（[frontend/nginx-frontend.conf](../frontend/nginx-frontend.conf)），HTML 每次重取，但浏览器会缓存 hash 化的 JS 文件，因此换新 bundle 时仍需 Ctrl+F5。

### 4.3 改模板库（`backend/template_library/*.yaml`）

```powershell
docker compose exec backend python lib_manager.py import
```

冲突说明：
- 名称重复 → 跳过
- 语义高度相似（>0.90 余弦相似度）→ 跳过；加 `--force` 覆盖

### 4.4 重启某个服务

```powershell
docker compose restart backend                       # 单服务
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.hotreload.yml up -d --force-recreate backend  # 重建
```

### 4.5 完全停止 / 完全启动

```powershell
docker compose down                                  # 保留 volume 数据
docker compose `
  -f docker-compose.yml `
  -f docker-compose.dev.yml `
  -f docker-compose.hotreload.yml `
  up -d
```

---

## 5. LLM 配置

平台需要至少一个 LLM 配置才能生成代码。

1. 浏览器访问 **http://localhost/**，用 admin / `<SUPER_ADMIN_PASSWORD>` 登录
2. 进 **Admin → LLM 配置**
3. 点「添加配置」

### 5.1 推荐配置（按优先级）

| 优先级 | 名称 | Provider | Base URL | Model ID | 速度 | 成本 |
|---|---|---|---|---|---|---|
| ⭐ 首选 | 智谱 GLM-4-Plus | OpenAI Compatible | `https://open.bigmodel.cn/api/paas/v4/` | `glm-4-plus` | **5-15s** | 国内可达 + 免费额度 |
| 备选 | 智谱 GLM-4.7 | OpenAI Compatible | 同上 | `glm-4.7` | 60-150s（thinking 模型）| 同上，质量更高 |
| 备选 | DeepSeek-V3 | OpenAI Compatible | `https://api.deepseek.com/v1` | `deepseek-chat` | 5-10s | 国内可达，¥10 起充 |
| 备选 | Claude via OpenRouter | OpenAI Compatible | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4-6` | 5-15s | 需信用卡，~$0.005/次 |
| 备选 | 本地 Ollama | OpenAI Compatible | `http://host.docker.internal:11434/v1` | 自定义 | 视模型 | 完全免费但要本地资源 |

### 5.2 通用字段

- **Temperature**：`0.0`（确定性约束）
- **Max Tokens**：非 thinking 模型 `2048` 即可；thinking 模型（GLM-4.7、DeepSeek-R1）建议 `4096`
- **输出模式**：`Tool Calling`（OpenAI 兼容路径当前其实固定走两步纯文本，此字段为预留）

### 5.3 测试与切换

- 创建后点「**测试**」→ 三项检查通过即正常
- 点「**设为默认**」→ 整个平台切换到该 LLM
- 切换默认时 Redis `cache:*` 与 `intent_cache:*` 自动清空（避免不同模型对同一意图选不同模板的污染）

> ⚠️ 切换 LLM 之后**第一次代码生成必然冷启动**（重新跑 normalize_intent + Step1 + Step2），耗时取决于模型；之后相同意图命中缓存 < 1 秒。

---

## 6. 验证服务状态

```powershell
# 容器状态
docker ps --format "table {{.Names}}\t{{.Status}}"

# API 健康
curl http://localhost/api/health
# {"status":"ok"}

# 前端
curl -I http://localhost/
# HTTP/1.1 200 OK
```

API 文档：浏览器开 **http://localhost/api/docs** 看 FastAPI Swagger UI。

---

## 7. 模板库导入

项目自带 10 个示例模板。**首次部署后**导入：

```powershell
# 预检（不写库）
docker compose exec backend python lib_manager.py validate

# 导入（写库 + 同步 Qdrant）
docker compose exec backend python lib_manager.py import

# 列出当前模板
docker compose exec backend python lib_manager.py list
```

后续修改 `template_library/*.yaml` 后只需再跑 `import`。

> 标志说明：`import` 默认会跳过名称冲突 + 跳过语义高度相似（余弦 ≥ `TEMPLATE_DEDUP_THRESHOLD`，默认 0.90）的模板。开发期反复迭代同一模板时常用 `python lib_manager.py import --force` **跳过语义查重**强制覆盖（名称冲突仍阻止）。

---

## 8. 常见问题与故障排查

### 8.1 Docker Desktop daemon 突然不响应

**现象**：CLI 跑 `docker ps` 报 `pipe 文件不存在`，但 Docker Desktop 鲸鱼图标还在。

**原因**：WSL2 内核或 Docker daemon 在 WSL2 内部死了，但 Docker Desktop 前端壳还活着。

**修复**（PowerShell）：

```powershell
# 杀掉所有 Docker 相关进程
Get-Process "*docker*" -ErrorAction SilentlyContinue | Stop-Process -Force

# 把 WSL 后端整个关掉
wsl --shutdown

# 等 5 秒后从开始菜单重启 Docker Desktop
Start-Sleep -Seconds 5
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

容器有 `restart: unless-stopped` 策略，daemon 起来后会自动跟着拉起。

### 8.2 代码生成报"生成失败，请重试"

**排查顺序：**

1. **后端跑通了吗**：`docker logs dv_acode_gen_platform-backend-1 --tail 30`
   - 看是否有 `[Pipeline] params=...` 这一行
   - 有 → pipeline 完成，问题在前端 / 网络
   - 无 → LLM 调用还在跑或报错
2. **nginx 状态码**：`docker logs dv_acode_gen_platform-nginx-1 --tail 5 | grep generate`
   - `499` = 客户端断开（浏览器超时 / 用户刷新）
   - `502` = nginx 找不到 backend（容器重启 IP 变了，新版 nginx 配置已自动重解析）
   - `200` = 正常返回，前端没正确处理
3. **前端 bundle 是不是最新**：浏览器 DevTools → Network → 看 `index-*.js` 的 hash 和 `frontend/dist/assets/` 比对
4. **LLM 是否慢**：thinking 类模型（GLM-4.7、DeepSeek-R1）单次 60-150s，前端 axios 默认 200s，但 thinking 模型 + 网络抖动可能踩边界 → 换非 thinking 模型（GLM-4-Plus）

### 8.3 BGE 模型在哪里？

模型存在 Docker 命名 volume `dv_acode_gen_platform_hf_cache` 里，物理上封装在 WSL2 的 VHDX 文件中：

```
C:\Users\<你的用户名>\AppData\Local\Docker\wsl\disk\docker_data.vhdx   (统一 vhdx)
```

**通过 Windows 资源管理器查看具体内容**：地址栏输入

```
\\wsl.localhost\docker-desktop\mnt\docker-desktop-disk\data\docker\volumes\dv_acode_gen_platform_hf_cache\_data\hub\
```

可以看到：
- `models--BAAI--bge-m3\` (~2 GB)
- `models--BAAI--bge-reranker-v2-m3\` (~600 MB)

> 想把模型搬到 D 盘可见目录（便于打包带到内网部署），改 `docker-compose.yml` 用 bind mount 替代 named volume；详见 [deployment-prod-linux.md §4](deployment-prod-linux.md#4-模型预下载与挂载)。

### 8.4 前端改了没生效

```powershell
# 1. 确认本地 build 了新版本
ls frontend/dist/assets/

# 2. 确认 bind mount 是否生效
docker inspect dv_acode_gen_platform-frontend-1 --format "{{range .Mounts}}{{.Source}} → {{.Destination}}{{`\n`}}{{end}}"
# 应显示 D:\tools\github\DV_ACODE_GEN_PLATFORM\frontend\dist → /usr/share/nginx/html

# 3. 浏览器 Ctrl+F5 / 无痕窗口
```

如果不是 bind mount（显示 `volume` 类型），说明启动时漏带了 `-f docker-compose.hotreload.yml`，重启容器：

```powershell
docker compose `
  -f docker-compose.yml `
  -f docker-compose.dev.yml `
  -f docker-compose.hotreload.yml `
  up -d --force-recreate frontend
```

### 8.5 完全重置（仅开发环境用）

> ⚠️ **会删除所有数据库 / 模板 / LLM 配置 / 缓存**

```powershell
docker compose down -v          # -v 删除 volume
# 接下来重做 §3 首次启动流程
```

### 8.6 资源占用过高

```powershell
docker stats
```

- `embedding_service` 占 RAM 大（5+ GB）：正常，BGE 模型在内存
- 整体超过 `.wslconfig` 的 `memory=10GB`：调整 `.wslconfig` 加大或减少其他容器（如 `docker compose stop backup`）

---

## 索引

- 项目架构：[ARCHITECTURE.md](../ARCHITECTURE.md)
- 团队协作流程：[CONTRIBUTING.md](../CONTRIBUTING.md)
- 生产部署（Linux 公司内网）：[deployment-prod-linux.md](deployment-prod-linux.md)
- 部署文档总入口：[deployment.md](deployment.md)
