# 平台架构 / 部署 / 环境 — Bug 与优化点记录

**起始日期**：2026-05-07
**适用版本**：v1.0.0（迁移到 WSL Ubuntu-22.04 后首轮 alpha 测试）
**职责范围**：仅记录平台代码、架构、部署流程、运维 / 环境层面的问题。
**不收录**：测试用户可见功能时发现的场景类 bug（模板选错、参数抽取错、生成代码错等）—— 见 [test-bug.md](test-bug.md)。

**用法**：发现一条记一条，**全部测完后再统一按优先级处理**。每条遵循"现象 / 根因 / 解决方案 / 优先级 / 状态"四段式。

---

## 优先级定义

| 标记 | 含义 | 处理时机 |
|---|---|---|
| 🔴 P0 | 阻断核心功能或部署，必须修 | 立即 |
| 🟠 P1 | 影响开发体验或可维护性，应修 | 第一轮优化 |
| 🟡 P2 | 边角问题或已知技术债，可优化 | 第二轮优化 |
| 🟢 P3 | 非平台问题（环境/浏览器等），仅文档说明 | 仅记录 |

---

## #001 — 后端 bind mount 在 Docker Desktop 硬重启后损坏

- **发现日期**：2026-05-07
- **触发场景**：电脑重启 / Docker Desktop 自己崩了之后，重新打开 http://localhost/ 报 502 Bad Gateway
- **优先级**：🟡 P2（运维流程问题，非代码 bug）
- **状态**：已找到稳定恢复路径

### 现象

浏览器访问 `http://localhost/` 502；nginx 日志显示 `connect() failed (111: Connection refused) ... upstream: "http://172.18.0.3:8000/..."`；backend 容器虽然 `Up`，但 uvicorn 子进程持续报：

```
ModuleNotFoundError: No module named 'app'
```

进容器 `docker exec backend ls /app` 只看到 `backups` 和 `uploads` 两个目录（来自 named volume），bind mount 进来的 `app/`、`alembic.ini`、`requirements.txt` 全部消失。

### 根因

`docker-compose.hotreload.yml` 中 `./backend:/app` 的 bind mount 源解析路径在 Docker Desktop 内部是 `/run/desktop/mnt/host/wsl/docker-desktop-bind-mounts/Ubuntu-22.04/<hash>`，**WSL2 后端硬重启后 hash 改变**，旧容器的 mount 指向已不存在的内部路径 → 容器看到的是空目录。

### 解决方案

**临时（用户侧）**：硬重启 Docker Desktop / WSL 后，**不要复用旧容器**，必须 `down` 后再 `up`：

```powershell
cd "Microsoft.PowerShell.Core\FileSystem::\\wsl.localhost\Ubuntu-22.04\home\Administrator\DV_ACODE_GEN_PLATFORM"
docker compose -f docker-compose.yml -f docker-compose.gpu-windows.yml -f docker-compose.hotreload.yml down
docker compose -f docker-compose.yml -f docker-compose.gpu-windows.yml -f docker-compose.hotreload.yml up -d
```

**长期（文档侧）**：在 `docs/startup-wsl.md` §6 常见坑表格里加一行：

| 现象 | 原因 | 解决 |
|---|---|---|
| `localhost` 502 / backend 报 ModuleNotFoundError | Docker Desktop 重启后 bind mount 源失效 | `compose down && compose up -d` 重建容器 |

**根治（架构侧）**：考虑迁移到 docker-in-WSL（dockerd 直接装 Ubuntu-22.04 内），顺便解决许可证 + dev/prod 同源问题。具体取舍见之前讨论的 "Docker Desktop vs Docker-in-WSL" 对照表。

---

## #002 — 浏览器自动翻译把英文参数名误译成中文

- **发现日期**：2026-05-07
- **触发场景**：测试 `sva_handshake_timeout_v1` 模板时，参数面板显示 `clk * 咔嚓 *`、`valid * 有效 *`、`ready * 准备好 了*`、`string * 弦 *`
- **优先级**：🟢 P3（环境问题，不修代码）
- **状态**：用户侧关闭翻译即可解决

### 现象

参数标签显示成机翻味十足的中文：
- `clk` → "咔嚓"（click 的中文拟声词）
- `valid` → "有效"
- `ready` → "准备好"，红星 `*` 被吞进去拆成 "了*"
- `string` → "弦"（小提琴弦的弦）
- `integer` → "整数"（巧合译对了）

### 根因

`grep` 前端代码、模板 YAML 全部 0 命中——**字符串不来自平台**。是浏览器自带翻译（Edge / Chrome）或浏览器扩展（沉浸式翻译 / 彩云小译）逐 DOM 节点把英文 `clk` / `valid` / `ready` 当英文单词翻译成中文。

### 解决方案

**用户侧**：浏览器关闭对 `localhost` 的自动翻译。

- Edge：地址栏 🌐 图标 → 永远不翻译此网站
- Chrome：右键页面 → 翻译 → 三个点 → 始终不翻译该网站
- 沉浸式翻译扩展：图标 → 暂停 / 加 localhost 到不翻译白名单

**文档侧**：在 `docs/startup-wsl.md` 或 `docs/test-manual.md` 加一句"建议浏览器对 localhost 关闭自动翻译"——避免后续测试者再踩同一个坑。

---

## #003 — SV 表达式语法层缺失：`condition` / `state_list` / `bins_expr` 等参数无任何语法校验

- **发现日期**：2026-05-07（test-bug #003 修复时系统性审计发现）
- **修复日期**：2026-05-07（同日落地 metadata-driven expr_type 系统）
- **优先级**：🟡 P2（架构级技术债，目前没有真实测试场景触发崩溃）
- **状态**：✅ **已修复**（手写 validator + 模板 YAML expr_type 字段驱动）

### 现象

平台对参数有三层校验保护：
- 整数类型（`max_cycles` 等）→ 前端正则 + Pydantic int
- SV 单标识符（`module_name` / `valid` / `from_state` 等 16 个）→ 前端校验 + 后端 sanitize（test-bug #003 已落地）
- **SV 表达式语法（多 token 组合）→ 完全没有校验**

涉及参数：

| 参数名 | 用途 | 期望语法 | 当前校验 |
|---|---|---|---|
| `condition`（FSM 模板）| SV 布尔表达式 | `awvalid && awready`、`!busy \|\| done` 之类 | 仅"不含换行/制表" |
| `state_list`（覆盖率模板）| 逗号分隔的 SV 标识符列表 | `IDLE, FETCH, DECODE, EXECUTE` | 仅"不含换行/制表" |
| `bins_expr`（覆盖率模板）| SV bins 语法 | `{0:255}`、`{1, 2, 4, 8, 16}`、`{[10:100], 200}` | 仅"不含换行/制表" |

LLM 或用户给这些参数输入畸形值时，前端不会阻断，后端不会清洗，渲染出来的 SV 代码会编译失败。

### 根因

`frontend/src/utils/validateParam.ts:50-53` 把这三个参数归为"其他自由文本参数"，仅校验"不含换行/制表"——这是 token-level 的最低保护，远不足以保证 SV 语法合法性。

后端无对应 sanitize 层——sanitize 只对单一 identifier 有效，套用到 SV 表达式上反而会破坏 `&&` / `==` / `{` / `:` 等合法语法。

### 解决方案

需要的是**轻量的 SV 表达式 lint**（不是完整 SV parser），有几种实现路径：

**路径 A — 手写状态机式 lint（中等成本）**：
- 为每类参数写一个专门的语法校验器
- `condition`：检查仅含 `[A-Za-z0-9_!&|()=<>!~+\-*\s]`，且括号配对
- `state_list`：split by `,`，每段单独跑 sanitize_sv_identifier，重组
- `bins_expr`：检查整体被 `{}` 包裹，内部允许 `[A-Za-z0-9_,\s:\[\]]`

**路径 B — 引入轻量 SV 解析库（高成本）**：
- 用 sly / lark / antlr4-python 之类工具写局部 SV 表达式语法
- 解析失败时报详细行列错误
- 优点：精确，能给用户更好的错误信息
- 缺点：增加依赖、维护这个 mini-parser

**路径 C — 渲染后整体 SV lint（最重）**：
- 集成 verilator 容器（`verilator --lint-only`），渲染后跑一遍真实 SV lint
- 这是端到端验证，能查跨参数语义问题（如"port 列表里没声明的信号被 property 引用"）
- 缺点：docker 镜像变大、runtime 加 1-2 秒、需要把 verilator 集成进 backend 容器或单独服务

### 推荐执行顺序

1. **触发再修**：等真有用户测试时给 `condition` 填了畸形语法导致代码生成失败，再启动这个 P2 修复——避免提前优化
2. 触发后优先选**路径 A**（手写状态机），覆盖 80% 场景，无新依赖
3. 路径 B / C 留作长期演进——B 是中期，C 是质量门禁的终极形态

### 实际修复（2026-05-07）

**触发**：在和用户讨论 #003 修复（test-bug 的 group_name 修复）时延伸出"未来加新模板新参数怎么办"的可扩展性问题，决定提前实施而非等触发。

**最终方案**：路径 A（手写 validator）+ **metadata-driven 体系**（模板 YAML 自描述参数语法类型，前后端按声明动态 dispatch）。

**核心设计**：

- 模板 YAML `parameters` 节点新增可选 `expr_type` 字段，6 类预设：`sv_identifier / sv_identifier_list / sv_boolean_expr / sv_bins_expr / integer / free_text`
- 后端 `expr_validator.py` + `pipeline.py:_map_params_with_source` 收尾按 `expr_type` 分发：identifier 类自动 sanitize，表达式类校验后打 `validation_error` flag
- `IDENTIFIER_PARAMS` 静态白名单降级为**未声明 expr_type 时的 fallback**——所有现有 10 个模板照常工作
- 前端 `exprValidators.ts` 同样的 dispatch 逻辑（TS 重写一份），`ParametersForm` 优先看 `meta.validation_error`，否则按 `expr_type` 校验
- `lib_manager.py import` 时对未声明 expr_type 的参数输出 lint warn，督促团队声明

**改动清单**：

| 文件 | 改动 |
|---|---|
| `backend/app/services/core/expr_validator.py` | 新增（~95 行）：3 个 SV 表达式 validator + EXPR_TYPE_DISPATCH |
| `backend/app/services/core/identifier.py` | 加注释明确 IDENTIFIER_PARAMS 为 fallback 角色 |
| `backend/app/services/core/pipeline.py` | sanitize pass 重写为 expr_type-driven，覆盖 sv_identifier / sv_identifier_list / sv_boolean_expr / sv_bins_expr 4 路 |
| `backend/app/schemas/generate.py` | `ParamWithSource` 加 `expr_type` 和 `validation_error` 两个可选字段透传 |
| `frontend/src/api/generate.ts` | `ParamWithSource` interface 同步 |
| `frontend/src/utils/exprValidators.ts` | 新增（~85 行）：3 个 TS validator + `validateByExprType()` dispatcher |
| `frontend/src/utils/validateParam.ts` | `validateParamValue` 加 `exprType?` 参数，优先 dispatch |
| `frontend/src/components/ParametersForm.tsx` | 调用时传入 `meta.expr_type`；优先显示 `meta.validation_error` |
| `backend/lib_manager.py` | import 加未声明 expr_type 的 lint warn |
| `backend/template_library/assertions/fsm_state_transition.yaml` | dogfooding：7 个参数都补 `expr_type` 字段，`condition` 标 `sv_boolean_expr` |
| `backend/tests/test_extract_params.py` | 追加 17 个测试（10 个 expr_validator 单测 + 5 个 pipeline dispatch 集成测试 + 2 个边界）|

**验证**：单元测试 52 passed（22 既有 + 13 上次 #003 + 17 本次）。端到端 FSM 模板调 `/api/v1/generate/preview` 返回 7 个参数都带 `expr_type` 透传，`condition` 标 `sv_boolean_expr`。

**遗留**（不在本次范围）：

- 渲染前 Pydantic field_validator 重跑校验（防 frontend bypass）—— 视作防御深度，本次跳过
- 把另外 9 个模板的 `expr_type` 字段也补全（当前仅 fsm_state_transition 做了 dogfooding）—— 留 Phase 2，IDENTIFIER_PARAMS fallback 让旧模板不破
- 升级到 lark / pyslang 解析器 —— 当前手写够用，未来 expr_type 词典超 5-6 个或出现嵌套结构再迁移

---

## 待补充观察项

平台层面后续可能浮现的问题（未确认，先列着）：

- [ ] Celery worker 在 backend 重启后是否会丢失任务（持久化由 Redis 兜底，但需实测验证）
- [ ] `embedding_service` 在 GPU 显存不足时的降级路径（当前 fp16，BGE-M3 + Reranker 占 ~3.6GB）
- [ ] PostgreSQL volume 长期增长后 `backend_backups` 备份机制（凌晨 2 点 `pg_dump` + `BACKUP_RETAIN_DAYS=7`）的可恢复性
- [ ] 切换默认 LLM 时 `intent_cache:*` + `cache:*` 两层缓存清空是否真做到（架构 §3.12.6）
- [ ] 模板增删改触发的 PG ↔ Qdrant 双写一致性，sync_status `sync_error` 状态下 `lib_manager.py repair` 实测路径

---

## 优先级总览（持续刷新）

| ID | 标题 | 优先级 | 状态 |
|---|---|---|---|
| #001 | bind mount 在硬重启后失效 | 🟡 P2 | 已找到恢复路径 |
| #002 | 浏览器自动翻译干扰 | 🟢 P3 | 用户侧规避 |
| #003 | SV 表达式语法层缺失（condition / state_list / bins_expr）| 🟡 P2 | ✅ 已修复 (2026-05-07，metadata-driven expr_type 系统)|
