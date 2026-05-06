# 开机登录手册（WSL 路径版）

**适用版本**：v1.0.0
**适用场景**：项目位于 D 盘 WSL Ubuntu-22.04 发行版内部
**项目位置**：
- WSL 内部：`/home/Administrator/DV_ACODE_GEN_PLATFORM`
- Windows UNC：`\\wsl.localhost\Ubuntu-22.04\home\Administrator\DV_ACODE_GEN_PLATFORM`

> 本手册只覆盖"开机 → 进入开发环境"。环境初装看 [deployment-dev-windows.md](deployment-dev-windows.md)，开发协作流程看 [CONTRIBUTING.md](../CONTRIBUTING.md)。

---

## 0. 一图看懂今天要怎么走

```
开 Windows
   ↓
启动 Docker Desktop（自动拉起 WSL2 + Ubuntu-22.04）
   ↓
选一条入口：
   A. VS Code (Remote-WSL)        ← 推荐，最顺滑
   B. Windows Terminal → wsl      ← 纯命令行习惯
   C. 文件资源管理器 \\wsl.localhost\... ← 只看/拷贝文件
   ↓
进入 /home/Administrator/DV_ACODE_GEN_PLATFORM
   ↓
docker compose ... up -d
   ↓
浏览器打开 http://localhost/
```

---

## 1. 开机后必做的两件事

### 1.1 启动 Docker Desktop

- 点击桌面 / 开始菜单的 **Docker Desktop** 图标
- 等右下角托盘鲸鱼图标变绿（约 30-60 秒）
- Docker Desktop 启动会**自动拉起 WSL2 后端**和 `Ubuntu-22.04` 发行版，无需手动 `wsl` 命令

### 1.2 验证 WSL 已就绪（可选）

打开 PowerShell：

```powershell
wsl --list --verbose
```

应看到：

```
  NAME              STATE     VERSION
* Ubuntu-22.04      Running   2
  docker-desktop    Running   2
```

如果 `Ubuntu-22.04` 是 `Stopped`，手动拉起：

```powershell
wsl -d Ubuntu-22.04
exit   # 拉起后退出，让它在后台保持 Running
```

---

## 2. 进入项目目录的三种方式

### 方式 A — VS Code + Remote-WSL（**推荐**）

这是开发体验最好的方式，编辑器、终端、Git、Docker CLI 全部跑在 Linux 端，磁盘 I/O 最快，inotify hot reload 可靠，git 也不会出现 Windows 侧的 "dubious ownership" 问题。

**前置一次性安装**（Windows 侧 VS Code）：

- 扩展 `Remote - WSL`（ID `ms-vscode-remote.remote-wsl`，Microsoft 官方）

**每次开机后的进入流程**：

1. 打开 PowerShell 进 WSL：

   ```powershell
   wsl -d Ubuntu-22.04
   ```

2. 进项目并拉起 VS Code：

   ```bash
   cd /home/Administrator/DV_ACODE_GEN_PLATFORM
   code .
   ```

   首次会自动下载 VS Code Server 到 WSL 端（约 30 秒，仅一次）。

3. VS Code 左下角出现 **`WSL: Ubuntu-22.04`** 绿色徽标 = 已处于 Remote-WSL 模式。

**进入 VS Code 后怎么开发**：

- **打开集成终端**（Ctrl + 反引号 `` ` ``）→ 默认就是 WSL bash，已在项目根目录。所有 `docker compose`、`git push`、`pytest`、`npm run build` 都在这个终端里跑，不要切回 PowerShell。
- **编辑文件** → 直接 Ctrl+S 保存即可，后端 `--reload` + 前端 `dist` bind mount 会自动反映变化。
- **Git push** → 第一次会提示输入凭据，参考下面 [方式 B 的"首次 git push"](#方式-b--windows-terminal--wsl-bash) 配置一次即可；之后所有 WSL 终端（含 VS Code 集成终端）共用同一份凭据。
- **推荐在 WSL 端装的扩展**（侧栏 Extensions → 搜到扩展后选 "Install in WSL: Ubuntu-22.04"）：`Python`、`Pylance`、`ESLint`、`Prettier`、`Docker`。Windows 端装的扩展默认不会同步到 WSL 端，必须手动勾。
- **关闭窗口下次打开** → VS Code 会记住最近的 Remote-WSL 工作区，File → Open Recent 直接选回项目，不用每次跑 `code .`。

> 也可以直接在 PowerShell 里跑 `code "\\wsl.localhost\Ubuntu-22.04\home\Administrator\DV_ACODE_GEN_PLATFORM"`，VS Code 会自动检测到 UNC 路径并提示切换到 Remote-WSL 模式。

### 方式 B — Windows Terminal + WSL bash

适合"只想跑命令"的场景：git 操作、docker compose、跑测试、看日志。落到 WSL bash 后是 Linux 用户视角，git 不会再报 dubious ownership。

**方案 A — 在当前 PowerShell 直接进 WSL bash**：

```powershell
wsl -d Ubuntu-22.04 --cd /home/Administrator/DV_ACODE_GEN_PLATFORM
```

落到 bash 后已在项目根，可以直接 `git status` / `git push` / `docker compose ...`。

**方案 B — 在 Windows Terminal 新开独立标签**：

```powershell
wt -w 0 new-tab --title "DV_ACODE_GEN" wsl -d Ubuntu-22.04 --cd /home/Administrator/DV_ACODE_GEN_PLATFORM
```

`-w 0` 表示在已有 Windows Terminal 窗口里新开标签；不带就开新窗口。

> **入口固化**：Windows Terminal → Settings → Add new profile → Command line 粘 `wsl.exe -d Ubuntu-22.04 --cd /home/Administrator/DV_ACODE_GEN_PLATFORM`，命名为 `DV_ACODE_GEN`，下次下拉一键进入。

**首次 git push 必做：配置 GitHub 凭据**

WSL 里 remote 是 HTTPS（`https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM.git`），第一次 push 会被问账号密码。GitHub 已经不接受密码，必须用 **Personal Access Token (PAT)**。二选一：

```bash
# 方案 1（推荐）：GitHub CLI 自动配凭据
sudo apt update && sudo apt install -y gh
gh auth login
# 选 GitHub.com → HTTPS → Login with a web browser
# 按提示在浏览器粘 one-time code，授权后自动写入 git credential helper
# 此后 git push 静默通过，所有 WSL 终端共享

# 方案 2：手动 PAT
# 在 https://github.com/settings/tokens 生成 classic PAT（勾 repo 权限）
git config --global credential.helper store
git push     # username 填 GitHub 账号；password 粘 PAT（不是 GitHub 密码）
             # 之后 ~/.git-credentials 明文存盘，后续不再问
```

> 不要在 PowerShell（即 Windows 侧 Git for Windows）里对 UNC 路径 `\\wsl.localhost\...` 跑 git——会触发 dubious ownership 报错；即使加 `safe.directory` 例外，9P 协议也会比 WSL 内部慢 10×。统一在 WSL bash 里操作。

### 方式 C — 文件资源管理器（只看文件）

地址栏粘贴：

```
\\wsl.localhost\Ubuntu-22.04\home\Administrator\DV_ACODE_GEN_PLATFORM
```

适合查看日志、拷贝 Excel 模板等。**不要在这里跑构建命令**——经过 Windows ↔ WSL 的 9P 协议，I/O 慢 10-50 倍，且 `npm install` 之类操作会触发权限问题。

---

## 3. 启动开发栈

进入项目根（无论用上面哪种方式），执行：

```bash
# 有 NVIDIA GPU（推荐）
docker compose \
  -f docker-compose.yml \
  -f docker-compose.hotreload.yml \
  up -d

# 无 GPU（CPU 小模型 overlay）
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  -f docker-compose.hotreload.yml \
  up -d
```

> ⚠️ 第一次切换 overlay 路径要保持一致，dev.yml（512 维）和 base（1024 维）混用会触发 Qdrant 维度错误。详见 [deployment-dev-windows.md §3.4](deployment-dev-windows.md#34-启动完整栈)。

等服务就绪：

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

9 个容器都 `Up`，其中 `postgres` / `redis` / `qdrant` / `embedding_service` 应为 `(healthy)`。

打开浏览器：

- 前端 → http://localhost/
- API 文档 → http://localhost/api/docs

---

## 4. 日常工作流速查

| 操作 | 命令（在 `/home/Administrator/DV_ACODE_GEN_PLATFORM` 下） |
|---|---|
| 改后端 Python | 直接保存，hot reload 自动生效 |
| 改前端 TSX | `cd frontend && npm run build`（dist bind mount） |
| 看后端日志 | `docker logs -f dv_acode_gen_platform-backend-1` |
| 看所有容器状态 | `docker ps` |
| 重启某个服务 | `docker compose restart backend` |
| 进后端容器调试 | `docker compose exec backend bash` |
| 拉最新代码 | `git pull` |
| 提交代码 | `git add -p && git commit && git push` |

详细命令见 [deployment-dev-windows.md §4](deployment-dev-windows.md#4-日常开发工作流)。

---

## 5. 收工与下次开机

### 5.1 收工选项

**只关 Docker Desktop**（推荐）：容器会保留状态，下次开机直接 `up -d` 续上。
```powershell
# 不需要任何命令，直接关 Docker Desktop GUI 即可
```

**完全停掉栈**：
```bash
docker compose down
```

**关 WSL 释放内存**：
```powershell
wsl --shutdown
```

### 5.2 下次开机

回到 [§1.1](#11-启动-docker-desktop) → [§2](#2-进入项目目录的三种方式) 选一种入口 → `docker compose ... up -d`。

如果上次没跑 `docker compose down`，因为 `restart: unless-stopped` 策略，**Docker Desktop 启动后容器会自动拉起**，可以跳过启动栈那一步，直接打开浏览器。

---

## 6. 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| `code .` 提示 `command not found` | WSL 里没装 VS Code Server | 在 Windows 端打开 VS Code，装 `Remote - WSL` 扩展，再回 WSL `code .` |
| `docker: command not found`（在 WSL 内） | Docker Desktop 没勾选 WSL 集成 | Docker Desktop → Settings → Resources → WSL Integration → 勾上 `Ubuntu-22.04`，Apply & Restart |
| `\\wsl.localhost\...` 在资源管理器打不开 | WSL 没启动 | `wsl -d Ubuntu-22.04 -- echo ok` 拉起一次 |
| 文件保存但 hot reload 没触发 | 用 Windows IDE 编辑 UNC 路径文件，inotify 跨 9P 不可靠 | 换成 VS Code Remote-WSL 编辑（方式 A） |
| `git status` 显示一堆权限/换行变更 | 跨 Windows ↔ WSL 复制过文件 | 在 WSL 内 `git config --global core.autocrlf input` 后重新 clone，或 `git checkout .` 复位 |
| `npm install` 在 UNC 路径跑超慢 | 走 9P 协议 | 必须在 WSL bash 内（`/home/Administrator/...` 路径）执行，不能在 PowerShell 里对 UNC 路径执行 |

---

## 7. 备份提示

项目现在物理位于 WSL2 的 VHDX（一个虚拟磁盘文件）：

```
%LOCALAPPDATA%\Packages\CanonicalGroupLimited.Ubuntu22.04LTS_*\LocalState\ext4.vhdx
```

**这个文件不在 Windows 备份/同步的常规路径里**，且坏盘后整个 WSL 数据会全丢。建议至少保证：

- 代码已 `git push` 到远端仓库
- `.env`、自定义模板、用户上传的 Excel 等**不在 git 里**的资产，定期手动拷出来到 D 盘或网盘

---

**最后修改**：2026-05-06
