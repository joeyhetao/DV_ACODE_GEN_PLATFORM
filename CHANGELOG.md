# Changelog

All notable changes to DV_ACODE_GEN_PLATFORM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

> 正在按 PRD v3.0 起草稿实现：意图构建器（IntentBuilder）改为 RAG-grounded 多轮对话；模板贡献向导简化为"name+description+代码示例"由后端 LLM 反推 `parameters` 与 `template_body`；新增 `under_specified` / `code_type_mismatch` 两道 422 闸（详 v2.13 草稿），错误响应附 `redirect_to` 让前端无脑跳转。代码进行中，落地后归集到 [0.7.0]。

### Added
- **模板选择质量保障三层系统**（FEAT-4，#13 + #14）：① **Layer 1 — IntentBuilder RAG 分数注入**：`services/intent/conversation.py` 候选列表格式扩展为"候选 N（相似度 X.XX）：xxx"，把 stage-3 RAG score 显式喂进 LLM 系统提示，让模糊意图在 top-3 间做选择时不再只靠 description 抽签；② **Layer 2 — 静态选择语料库 + 双套件回归测试**：`backend/tests/data/template_selection_corpus.yaml`（220 行，覆盖现有所有模板含 FIX-3 case）固化"哪条意图应命中哪个模板"，`tests/test_template_selection_corpus_mocked.py`（CI 常态，mock RAG/LLM 仅校验流水线路由）+ `tests/test_template_selection_corpus_real.py --real-embedding`（手动回归，真实 RAG top-1 断言）双套件防止模板改动悄悄抢走已有意图的正确映射；③ **Layer 3 — 上线前冲突预检 + LLM 业务层分析 + 自动语料入库**：新增 `services/platform/corpus_service.py`（3 个 async 函数：生成 3 条新模板正例 + per-邻居 1 条负例 / 嵌入相似度冲突检测 / LLM 修改建议）、`models/template_corpus_case.py` SQLAlchemy 模型、`migrations/versions/005_template_corpus_cases.py` Alembic 迁移、`POST /api/v1/contributions/{id}/pre-approve-analysis` 端点 + `ConflictItem` / `PreApproveAnalysisResult` schema；管理员点"批准并入库"后端先跑冲突检测，无冲突 1 秒自动确认，有冲突弹分析面板支持"一键应用建议修改"重跑分析；approve 成功后自动向 `template_corpus_cases` 写入 3 条 LLM 生成语料形成正反馈闭环。前端 `AdminContributionsPage.tsx` 两步审核 UI + Drawer 分析面板 + `frontend/src/api/contributions.ts analyzeConflicts()`；普通用户提交贡献流程零变化。Review pass-1 cleanup（#14）：静态语料 YAML 模块级缓存（不再每次请求重读，失败打 `[WARN]` 不静默）、新模板 + N 条 intent 一次性批量 embed（替代 N+1 次串行 HTTP，rag_retrieve 因共享 AsyncSession 保持串行）、`for_neighbors` prompt 空邻居路径（移除硬编码兜底 `sva_data_integrity_v1`，模板被改名/删掉时不再生成幻邻居语料引发 FK 违反）、`detect_conflicts` 同时 join `Template` 表把动态语料里的裸 `expected_template_id` 翻译为真实模板名，避免管理员看到一堆 UUID；LLM JSON 输出统一两段式 fence 解析（兼容偶发 ```json 包裹）、`AdminContributionsPage` `detail=null` 后自动批准倒计时不再 fire（避免 `doApprove(null!.id)` runtime error）、`needs_revision` 状态下"批准并入库"按钮 disabled + Tooltip 解释、"一键应用建议"在 `saveEdits` 失败时不再静默重跑分析、conftest 共享语料 fixture 改为下划线开头的私有命名约定

### Changed
- **4-agent scaffold 5 项人工触点优化**（WORKFLOW-1, #10）：① `branch-scope-guard.py` 放宽 `DOC_REGEX`——`feature/*` / `fix/*` 分支现可直接编辑 `CHANGELOG.md`，每次 allow/block 决策写 stderr 审计日志；② `worktree-init.sh` 解析 spec §8 `docs_targets`——`[]` 时仅建 feat worktree（`--add-docs` 可事后补建 docs worktree）；③ `/commit` 在 `feature/*` 分支 commit 后自动从 `git diff origin/develop..HEAD` 派生 Handoff JSON 的 `affected_paths`、`changelog`、`needs_migration`（`docs_targets` 仍手动填写）；④ `/review-pre-pr` 在转发 subagent 原文后，主 session 追加 MUST / SHOULD / NIT 三档分诊段；⑤ `/open-pr` 开 PR 成功后自动排队 `gh pr merge --auto --squash`，`--no-auto-merge` 提供 opt-out
- ARCHITECTURE v2.17 → v2.18：先行落地 PRD v3.0 实现细节文档（§3.10 LLM 反推贡献流、§3.11 `normalize_intent` 角色降级 + IntentBuilder `/chat` 多轮对话端点、§3.12 `LLMClient.chat()` 抽象、§3.15.3 `code_type_mismatch` + `under_specified` 闸 + `redirect_to` 字段约定、§5.1 端点表 + §8.4 六个新环境变量）。代码实现仍未提交。

### Fixed
- **`no_matching_template` 闸去掉 RAG score 阈值，只信 LLM 判断**（FIX-9）：第五道闸原触发条件为 `confidence_source=rag_fallback AND rag_candidates[0]["score"] < NO_MATCH_SCORE_THRESHOLD（默认 0.60）`。但 cross-encoder reranker 对含公共关键词（如 `req`）的语义不相关意图仍会给满分——典型案例：意图"断言 cpu_req 和 dma_req 不能在同一时钟周期同时有效，验证总线仲裁互斥约束"命中 `sva_timing_max_delay_v1` 拿 1.0 分，score 条件（1.0 < 0.60 为假）使闸无法触发，LLM 正确返回的 `none` 判断被 reranker 词汇重叠分数否决，本应直跳贡献页的场景错误地继续走 rag_fallback 后陷入 under_specified。修复将触发条件简化为 `confidence_source=rag_fallback`（即完全信任 LLM step1 的 none 判断），`pipeline.py` 闸判断块移除 `rag_candidates[0]["score"] < settings.no_match_score_threshold`，日志格式简化为 `[Gate] no_matching_template: top_score=<n>`（去掉 `< threshold=0.60`），score 值仍写入日志供监控。`no_match_score_threshold` 配置项保留但不再参与触发判定。`NO_MATCH_GATE_ENABLED=false` 紧急关闸通道保持有效。ARCHITECTURE.md §3.15.3 Step 5a + docs/test-manual.md §2.5 / §5.0 入口 A / 后端日志参考表同步更新
- **LLM step1 收紧系统提示，禁止信号重命名强行匹配语义不符模板**（FIX-8）：原 `_step1_select_id`（`openai_compat_client.py`）和 `select_template`（`anthropic_client.py`）的系统提示只声明"从候选中选最匹配的一个"，未禁止"通过信号名重映射强行适配"，导致互斥约束类意图（如"断言 cpu_req 和 dma_req 不能同拍同时有效"）被 LLM 把用户信号 `cpu_req` / `dma_req` 重命名为 `sva_handshake_stable_v1` 的 `valid` / `ready` 参数槽位，绕过第五道闸（`NoMatchingTemplateError`）而错误地走 ConfirmationPanel 或 IntentBuilder。修复在两个客户端的 step1 系统提示中追加显式负向准则：候选模板核心验证语义与意图不匹配时（互斥 / one-hot / 竞争检测 vs 候选均为握手 / 稳定性 / 延迟 / FSM / 值域），必须返回 `"none"`（Anthropic 在 `tool_choice` 强制下于 `template_id` 字段填 `"none"`），交由 `pipeline.py` 的 `confidence_source="rag_fallback"` + `rag_candidates[0]["score"] < NO_MATCH_SCORE_THRESHOLD`（默认 0.60）链路触发 HTTP 422 `no_matching_template`，前端直跳贡献页（注：FIX-9 后此 score 阈值条件已移除，仅保留 `confidence_source=rag_fallback` 条件即触发）。`docs/test-manual.md` §5.1 测试用例由"DMA 地址越界检测"替换为"总线仲裁互斥约束"（更贴合 FIX-8 修复路径），并补"正常握手/FSM 场景应继续命中"的回归对照；`ARCHITECTURE.md` §3.12 step1 表格 + §3.15.3 Step 5a 段落同步补"何时返回 none"负向准则
- **`sva_reset_behavior_v1` 模板 RAG 误判为 `sva_fsm_state_transition_v1`**（#12, FIX-3）：`reset_behavior.yaml` 的 description / keywords 未覆盖"状态寄存器复位后初始状态"语义，stage-3 reranker 因 FSM 模板含 `state` / `IDLE` 关键词而排名反转，导致"复位释放后 cur_state 必须等于 IDLE"被误判为 `sva_fsm_state_transition_v1` 并触发 UnderSpecifiedIntentError 跳转 IntentBuilder。修复扩充 description（明确覆盖 FSM 复位初始状态场景）、keywords（新增 初始状态 / 状态寄存器 / FSM复位 / cur_state / IDLE 等）、tags（fsm_reset / state_initialization）以及 target / init_value 参数 description（说明可接受枚举值）；重新 embed 后 `sva_reset_behavior_v1` 对此类查询排名回归首位
- **`_map_params_with_source` step 1 漏掉 trivial LLM 弃权值守卫**（#6, FIX-1）：LLM step2 返回 `""` / `"unknown"` / `"null"` / `0` 等 trivial 占位时被无条件写入槽位并标 `source=llm`，槽位写入卫语句（`if name in result: return`）立即生效封死 regex → signal_list → default 兜底链路；下游 `_detect_under_specified` 把这条 `source=llm` 低置信值判失败抛 `UnderSpecifiedIntentError`，即便模板已配置合法 `default` 也被误导向 IntentBuilder。修复在 step 1 顶部加 2 条 context-free 守卫（`None`/`0` 跳过 + `isinstance(value, str) and value.strip().lower() in _TRIVIAL_LLM_VALUES` 跳过），与 `_detect_under_specified` 低置信判定保持镜像；典型现象是寄存器写保护意图（`sva_data_integrity_v1`，`module_name` 应回落 `default="dut"`）不再被错误拦截。`value == name`（字面参数名弃权）依赖 `param_def` 上下文（`clk default="clk"` 是合法值），有意不在此复刻，仍由 `_detect_under_specified` 统一裁决
- **`_map_params_with_source` step 1 漏掉 ungrounded 非 trivial LLM 值守卫 + 9 个模板缺 `default`**（#8, FIX-2）：FIX-1 之后仍存在对称漏洞——LLM step2 返回的并非 trivial 占位（不被既有守卫拦截）但语义上完全无依据的"幻觉值"（如 `module_name='top'`，意图文本与 form signals 均未出现），照样会被写入槽位标 `source=llm` 封死 step 4 default 兜底；下游 `_detect_under_specified` 通过 `_llm_value_grounded_in_intent` 判其低置信 → 422 → 用户被错误导向 IntentBuilder，即便模板配了合法 default 也救不回来。修复在 step 1 既有 trivial 守卫之后追加第 3 条 context-aware 守卫：当参数 `param_def` 含 `default` 且 LLM 值既不能溯源到 `intent_text` 也不在 `form_values` 中时跳过该槽位，让 step 4 用模板 default 接管；`if intent_text:` 包裹保持与 `_detect_under_specified` 一致的 mock 测试豁免。配套补齐 9 个模板的 `default`：5 个 assertion 模板（`fsm_state_transition` / `handshake_stable` / `handshake_timeout` / `timing_max_delay` / `reset_behavior`）的 `module_name="dut"`，4 个 coverage 模板（`value_coverage` / `transition_coverage` / `protocol_handshake_coverage` / `cross_coverage`）的 `group_name="cg_<subcategory>"`——这是新守卫真正生效的前提（无 default 时守卫 no-op）。新增 4 个单测：ungrounded `module_name` 让位 default、ungrounded `group_name` 让位 default、grounded 非 trivial 值保留、`signal` 类无 default 参数仍被 `_detect_under_specified` 拦截。部署已在主 session 完成：`lib_manager.py import --force` + Qdrant `rebuild` + `invalidate_all_llm_caches()`（intent_cache schema fingerprint 漂移本可自动 bypass，主动失效是保险），DB 已通过 `SELECT parameters FROM templates` 验证 9 个新 default 落库

---

## [0.6.0] - 2026-05-14

### Added
- **缓存 key 按 LLM 配置分桶**：`cache:{sha256(...)}` → `gen:{llm_config_id}:{template_id}:{version}:{sha256(sorted_params)}`；`intent_cache:{intent_hash}` → `intent_cache:{llm_config_id}:{intent_hash}`，TTL 30d。`template_id` 与 `version` 从单一复合 hash 中拆出，使 `invalidate_template_cache(tid)` 能用 `gen:*:{tid}:*` 通配跨所有配置桶精准失效单模板（旧 schema 只能整库 FLUSH）。Admin LLM CRUD / set-default 时仍调用 `invalidate_all_llm_caches()` 全清两个前缀——分桶不是为了"切换后保留旧缓存"，而是支撑单模板维度的精准失效。空 `llm_config_id` 用 `_` 占位（保留测试 mock 路径）
- **intent_cache schema-drift 兜底**：`services/intent/history.py::template_params_fingerprint()` 对 `parameters[].name / required / expr_type` 三字段稳定 hash 写入缓存条目；命中时 pipeline 用当前 `template.parameters` 重算指纹比对，**漂移即 bypass 缓存走完整流水线**，避免模板参数改名/增删后旧 mapping 被短路返回
- **`EmptyRetrievalError` 独立错误路径 → HTTP 503**：通过 off-topic dense 闸但 RAG 三阶段返空时抛出，端点结构化 detail（`type=empty_retrieval` / `code_type` / `hint`）映射 503 让 SRE 排查 Qdrant/embedding service，**不与 off-topic 422 共用错误流**；该异常继承 `RuntimeError` 而非 `ValueError`，避免被泛化 `except ValueError` 兜底降级
- **DB 端 `llm_configs.is_default` 部分唯一索引**（迁移 `004_unique_default_llm.py`）：`CREATE UNIQUE INDEX ... WHERE is_default=true`，并发 set-default 或事务回滚遗留多行 True 时由 DB 拦截，防止 `factory.get_default_llm_client.scalar_one_or_none()` 抛 `MultipleResultsFound` → 500
- **`EMBEDDING_DIM` 设置 + Qdrant 维度告警**：换 embedding 模型（bge-m3=1024 ↔ Qwen3-Embedding-4B=2560）时硬编码 1024 不再生效；`main.py:_init_qdrant_collection` 在 collection 已存在时读取实际 `dense.size` 与 `settings.embedding_dim` 比对，错配打 WARN 提示跑 `lib_manager.py rebuild`；`.env.example` 补 `OFFTOPIC_GATE_ENABLED` / `OFFTOPIC_DENSE_THRESHOLD` 两个之前没文档化的环境变量
- **lib_manager `dedup-check` 子命令**：按当前 `TEMPLATE_DEDUP_THRESHOLD`（可 `--threshold` 临时覆盖）扫一遍 active 模板列出潜在重复对——dedup 在 import 时只对"新模板 vs 历史"判定一次，阈值改了不会回溯，本命令补一份事后审计能力；仅打印不删除。Import 完成后自动调 `invalidate_all_intent_cache()`：批量导入可能整体替换模板库，30 天 TTL 内的旧 intent → (template_id, params) 映射可能指向已不存在/schema 已改的模板
- **Anthropic 客户端 `[Timing]` 打点对齐 OpenAI-compat**：`_anthropic_thinking_tokens(msg)` 兼容不同 SDK 版本的 `thinking_tokens` / `reasoning_tokens` 字段名；`normalize_intent` / `select_template` 调用前后包夹 `time.perf_counter()`，与 OpenAI-compat 日志格式一致便于跨 provider 对比
- **`calibrate_offtopic_threshold.py` 输出推荐 `.env` 行**：跑完分布表后直接根据 off-topic 最大值与 marginal-ic 最小值的中点推荐一行 `OFFTOPIC_DENSE_THRESHOLD=<value>` 配置，能直接粘贴生效；gap ≤ 0 时回退 `marg_min - 0.02` 保守值

### Fixed
- **`sync_status_enum` 值与 ORM 错位**（迁移 `003_align_sync_status_enum.py`）：migration 001 旧声明 `('pending','synced','error')` 与 ORM/`lib_manager.py` 长期写入的 `('ok','syncing','sync_error')` 错位，导致纯 alembic 路径升级的 DB 首次 import 模板报 `invalid input value for enum`。迁移**幂等**实现：兼容三种状态（旧值 / 新值 / 混合）；同步把 `templates.py` 三处 `create/update` 路径 `sync_status="pending"` 改成 `"syncing"`
- **registry YAML 加载单文件错误容忍**：之前 `registry._load` 单文件失败（YAML 损坏 / 必填字段缺失）直接抛异常让整个 backend 起不来；新增 code_type 时一次手抖就把生产打挂。改为 try/except 捕获 `yaml.YAMLError / KeyError / TypeError`，命中即跳过该文件并打 `[WARN]` 日志，已加载的 code_types 仍生效

### Changed
- CLAUDE.md：补齐 cache key 结构与 schema-drift 契约 §（"Four-layer determinism guard" 第 1 条）、`EmptyRetrievalError` vs `OffTopicIntentError` 的 422/503 分流说明、Stage2 ColBERT 实际 bypass 的代码位点（`stage1_hybrid.py:62` / `stage2_colbert.py:25-27`，main.py 只 provisions dense+sparse 命名向量）——后者是已存在行为的文档化，不是代码变更
- ARCHITECTURE v2.16 → v2.17 / PRD v2.11 → v2.12：补齐 cache key 新结构、`EmptyRetrievalError` 503 路径与 off-topic 422 在 §6.1 的错误模式分流
- `.claude/commands/commit.md`：`/commit` skill 改为"默认全自主模式"——0a/0b/Phase 2 等"等用户确认"门改为自动分档/执行前公告，保留绝对禁止 + 硬阻止四类硬停红线；`.claude/settings.json` 新增项目级 Bash/MCP 工具 allowlist
- CONTRIBUTING §11.4：增加"周期性语料增量"运维节奏建议（每 4 周从 `generation_records` 抽 `confidence<0.5`/422 样本人工评判补语料防沉默漂移）

---

## [0.5.0] - 2026-05-14

### Added
- **无关意图 RAG dense 余弦闸**（核心契约修订）：`pipeline_preview` 头部插入 dense 阈值闸，对 `original_intent`（非 normalized，避免 LLM 改写抬高 off-topic 分数）做 Qdrant dense 通道 top-1 比对，低于 `OFFTOPIC_DENSE_THRESHOLD`（默认 0.44）抛 `OffTopicIntentError` → HTTP 422 + 结构化 detail（`type=off_topic` / `detector` / `top_dense_score` / `threshold`）；前端弹"检测到非验证请求"专属 Modal，不再退化生成全 placeholder；`OFFTOPIC_GATE_ENABLED=false` 紧急 kill-switch；新增 `services/rag/engine.py::dense_top1_score` helper 复用 Qdrant dense 通道
- **off-topic 校准与回归基础设施**：`backend/scripts/calibrate_offtopic_threshold.py` 经验校准脚本（输出阈值候选 + 召回/拒绝率曲线）；`backend/tests/data/offtopic_corpus.yaml` 双标签语料；`tests/test_offtopic_corpus_mocked.py`（CI 默认，always-on 路由回归）+ `tests/test_offtopic_corpus_real_llm.py --real-llm`（活模型精度探针）双套件
- **per-config thinking-disable 开关**：`llm_configs` 表新增 `step2_disable_thinking` BOOLEAN 列（NOT NULL DEFAULT true，迁移 `002_step2_disable_thinking.py`），Admin UI 加 Switch；`normalize_intent` 与 `_step1_select_id` 硬编码禁 thinking 收紧 `max_tokens`（512 / 64），`_step2_fill_params` 由配置切换（true → `max_tokens=2048` 禁 thinking，false → `max_tokens=1024` 保留 thinking）；GLM-4.7 实测单次推理由 12-249s 降至 ~3s
- **LLM 调用 per-stage 延迟与 thinking 状态打点**：每次 OpenAI-compat 调用打点 `[Timing] llm=<name> ms=<n> reasoning_tokens=<n> thinking=<on/off>`，便于运行时验证 `extra_body={"thinking":{"type":"disabled"}}` 是否真正被模型识别（`reasoning_tokens=0` 确认生效）
- **expr_type 驱动的标识符规范化 + 表达式校验**：模板 YAML 的 `parameters[].expr_type` 字段声明语法类型（`sv_identifier` / `sv_identifier_list` / `sv_boolean_expr` / `sv_bins_expr`）；新增 `services/core/identifier.py`（SV 标识符 sanitize + IDENTIFIER_PARAMS 兜底白名单 + `construct_group_name`）和 `services/core/expr_validator.py`（轻量手写状态机校验布尔/列表/bins 表达式）；`_map_params_with_source` 末尾追加 expr_type-driven Step 7，覆盖所有 5 类源（sv_identifier 类静默清洗并标 `sanitized=True`，布尔/bins 类校验失败仅附 `validation_error`）；`PreviewResponse.params` schema 新增 `sanitized` / `expr_type` / `validation_error` 三字段供前端徽标提示，前端镜像 `frontend/src/utils/exprValidators.ts` 做同款实时校验
- **客户端 / SDK 超时延长至 300s**：前端 `/generate` 与 `/generate/preview` 客户端超时 180s → 300s；后端 `OpenAICompatClient` 显式设 read=300s，避免默认 60s 在 thinking ON 模式下被前端 abort
- **平台与测试 bug 跟踪日志**：`docs/platform-bug.md` + `docs/test-bug.md`，配合 v1.0.0 alpha 阶段缺陷追踪闭环

### Changed
- ARCHITECTURE v2.14 → v2.16、PRD v2.9 → v2.11：补齐 §1.1 "always produce code" 契约**收窄为仅对域内 IC 输入**、§3.12.2 per-call thinking/`max_tokens` 矩阵、§4.1 `llm_configs.step2_disable_thinking` 列；PRD §3.5.1 新增"Step2 禁用 thinking"开关、§4.3 性能分档刷新（默认配置回到 < 10s）
- CLAUDE.md：新增 GLM-4.7 thinking-disable 策略章节 + step2 thinking ablation 矩阵 + off-topic 闸契约说明
- normalize_intent 提示词回退为纯句式改写（撤掉前一轮临时的 sentinel 注入式 off-topic 检测方案）

### Fixed
- dev overlay (`docker-compose.dev.yml`) 之前误用小尺寸 embedding model 与 Qdrant 1024-dim collection 维度冲突导致生成全链路失败，统一回 bge-m3
- Admin LLM 配置 GET 接口在新增 `step2_disable_thinking` 列后未在 `_to_config_out` 透出该字段，导致 Pydantic schema 校验失败返 500

---

## [0.4.0] - 2026-05-07

### Added
- **方案 3 两步式 UI 确认面板**（核心 UX 重构）：
  - 后端：`run_pipeline` 拆为 `pipeline_preview` + `pipeline_render` 两段；新增 `/api/v1/generate/preview` 端点（返回模板推荐 + 参数预填充含来源标识）；增强 `/api/v1/generate/render` 端点（用户确认参数后渲染 + 写 GenerationRecord + 写缓存）
  - `_map_params_with_source` 替代 `_map_params`，每参数标 5 类源（`signal_list` / `regex` / `llm` / `default` / `placeholder`）
  - 新增 `confidence_source` 字段（`llm_step1` / `rag_fallback` / `intent_cache`），解决附录 B.4 的 confidence 显示陷阱
  - 前端：新增 `ConfirmationPanel` + `ParametersForm` + `SourceBadge` 组件，意图缓存命中（`quick_render=true`）时自动跳过确认面板；红色占位符徽标禁用「生成代码」按钮强制用户填值；切换 RAG 候选模板自动重映射参数
  - 既有 `/generate` 端点保留兼容（内部调 preview+render），batch_tasks 零变更
  - 新增 4 个 pipeline_render 集成测试 + 8 个 `_map_params_with_source` 单测，共 12 测全过
- **LLM thinking-model 支持**：OpenAI 兼容客户端拆为"选模板 + 填参数"两步纯文本调用（`_step1_select_id` + `_step2_fill_params`，`max_tokens=4096`），规避 GLM-4.7 / DeepSeek-R1 reasoning_tokens 截断问题；切换默认模型时自动清空 `intent_cache:*` 与 `cache:*`
- **Pipeline 兜底链**：RAG 召回不足时基于 `template.keywords` 与意图原文做小写子串匹配补充召回；LLM 选不出模板时退化为 RAG 第一候选（`confidence_source=rag_fallback`）；LLM 填不出参数时退化为正则提取 + signal-list role-hint + 模板 default + 参数名占位
- **正则参数提取扩展**（pipeline.py `_extract_params_from_intent`）：从只覆盖 5 个 coverage 字段扩展到额外覆盖 11 个 assertion 参数（module_name / max_cycles / max_delay / init_value / enable / data / valid / ready / target / start_event / end_event / state_sig），让"模块名为 X，使能信号为 Y"这类半结构化句式不再依赖 LLM Step2 语义映射
- **首份单元测试** `backend/tests/test_extract_params.py` + `tests/test_pipeline_preview_render.py`：22 + 12 个测试覆盖既有 coverage 提取（回归保护）+ 新增 assertion 提取 + 反例（避免误提取）+ §1.1/§1.4/§1.6 完整集成场景。容器内跑 `docker compose exec backend pytest tests/ -v`
- **用户自助注册**：登录页注册标签页 + 公开 `POST /api/v1/auth/register` 端点（默认 role=普通用户），库管理员/平台管理员仍由超管在用户管理页升级
- **CLAUDE.md 项目级 Claude Code 指南**：确定性契约、生成管线两步流、code-type 注册机制、LLM 客户端抽象、PG/Qdrant/Redis 数据分工、house rules（Conventional Commits + scope 列表 + core 单测要求）
- **WSL2 启动手册** `docs/startup-wsl.md`：VS Code Remote-WSL 工作流、`gh auth login` / 手动 PAT 两种凭据方案、Windows Terminal `-w 0` 新标签命令与 profile 固化、9P 协议性能与 dubious ownership 注意事项
- 部署文档拆分为两份独立分册：
  - `docs/deployment-dev-windows.md`：Win11 本机开发部署（含 .wslconfig 优化、hot reload、bind mount、Docker daemon 崩溃处置、HF 模型 VHDX 路径等）
  - `docs/deployment-prod-linux.md`：Linux 公司内网生产部署（含受限外网 mirror 配置、模型预下载与 bind mount、备份与恢复演练、安全加固清单 11 项）
- 平台功能测试手册 `docs/test-manual.md`（11 章 + 2 附录）：
  - 10 个模板逐一的高置信度命中用例（含输入文本 / 期望模板 / 期望代码片段 / 后端验证）
  - 4 对易混淆模板对照测试（握手 stable vs timeout、断言 vs 覆盖率等）
  - 6 个低置信度兜底场景（无关意图 / 极简输入 / 英文 / code_type 不匹配 / 必填参数缺失 / RAG 召回 0）
  - 缓存层 3 个用例 + 模板贡献 3 个完整流程 + 批量生成 + 意图构建器 + 用户/LLM/通知管理
  - **附录 B：5 项已知功能-UI gap 清单**（贡献无去重、切换 LLM 不清缓存、删默认 LLM 无防呆、后端不强制 confidence_threshold、ColBERT Stage2 实质退化）

### Changed
- ARCHITECTURE v2.13→v2.14、PRD v2.8→v2.9：补齐 §3.15 拆 `pipeline_preview` / `pipeline_render`、新增 §3.15.5 expr_type 校验/规范化层占位与 §3.16 两步式确认面板、§5.1 端点表对齐 `/preview` `/auth/register` `/auth/me` `/health`；PRD §3.6 新增自助注册说明、§6.1 主流程改为统一两步式（preview → 确认面板 → render，含 quick_render 短路）
- 项目工作目录从 `D:\dev\DV_ACODE_GEN_PLATFORM` 迁移到 WSL2 内部 `/home/Administrator/DV_ACODE_GEN_PLATFORM/`，`docs/deployment-dev-windows.md` 与 `docs/startup-wsl.md` 同步路径
- `docs/deployment.md` 由 680 行重写为 ~50 行索引文档，仅承载场景对比表与跳转
- README.md 文档索引表新增 4 条文档链接（3 份 deployment + test-manual）
- docker-compose.yml：9 个服务启用 `restart: unless-stopped`；qdrant healthcheck 改为 TCP 探测；hotreload override 增加 `frontend/dist` bind mount 让前端改动免重建容器即时生效
- nginx 入口启用 Docker 内置 resolver `127.0.0.11 valid=10s` + 变量化 `proxy_pass`，解决 backend 容器重启后 nginx 缓存旧 IP 导致 502；前端容器对 `index.html` 强制 `no-cache` 响应头，确保 hash 化 bundle 升级后浏览器立即拉新
- 前端 axios 超时延长至 thinking-model 容许范围（避免请求被前端提前 abort）
- FastAPI docs/redoc/openapi.json 与 health 端点统一挂到 `/api/` 前缀（与反代路径一致）

### Fixed
- RAG Stage3 graceful degradation：reranker 异常时回落到 Stage2 排序，不再让整条流水线 502；同时兼容 qdrant-client 1.12 的 `query_points` API 变更
- `lib_manager rebuild` 用 `uuid.uuid5(NAMESPACE_DNS, template.id)` 派生确定性 Qdrant point ID，修复重复 rebuild 累积重复 point 污染检索的 bug

---

## [0.3.0] - 2026-04-27

### Added
- 部署手册 `docs/deployment.md`，覆盖 Docker Compose 完整栈启动、环境变量配置、嵌入服务 GPU/CPU 选择、首次初始化流程
- `/update-docs` 与 `/update-specs` 两个 slash command 工具骨架，支持按真实项目状态自动同步 README/CHANGELOG/CONTRIBUTING 与 PRD/ARCHITECTURE

### Changed
- ARCHITECTURE.md 与首版平台实现对齐：补全 Qdrant 三阶段 RAG、独立嵌入服务、LLM 多模型工厂、Celery 任务队列等模块
- CONTRIBUTING.md 中的 docker-compose 路径修正为根目录形式（取消废弃的 `deploy/` 路径）
- README/CHANGELOG/CONTRIBUTING 整体与项目当前实现状态同步

---

## [0.2.0] - 2026-04-26

### Added
- 完整后端实现：FastAPI 路由层（auth / generate / templates / batch / admin / intent_builder / notifications / contributions）
- 三阶段 RAG 检索流水线：混合检索（stage1_hybrid）→ ColBERT 精排（stage2_colbert）→ Cross-Encoder 重排（stage3_reranker）
- 确定性代码生成引擎：Redis 缓存命中 → 算法匹配（pipeline）→ Jinja2 渲染（renderer），含去重（dedup）
- 结构化意图提取服务：normalizer / preflight / builder / history
- LLM 多模型适配层：Anthropic Claude 原生客户端 + OpenAI 兼容接口，工厂模式统一管理
- 批量生成任务系统：Celery + Redis 任务队列，支持 Excel 批量导入
- 模板库初始化（SVA 断言 5 个模板：data_integrity / fsm_state_transition / handshake_stable / handshake_timeout / reset_behavior）
- 前端完整界面：生成页、意图构建器、模板库、批量处理、我的贡献、管理控制台（用户/模板/贡献审核/LLM 配置）
- Excel 需求表解析服务（excel_parser）
- 平台管理服务：审计日志、备份、贡献审核
- Docker Compose 完整栈配置

### Changed
- 向量数据库由 pgvector 调整为 Qdrant（独立服务，更优的 ANN 检索性能）
- LLM 层设计从单一 Anthropic 扩展为可插拔多模型工厂

---

## [0.1.0] - 2026-04-22

### Added
- 初始仓库建立
- PRD v2.7：确认双表格结构化输入、三层确定性架构、三级权限体系
- ARCHITECTURE.md：完整系统架构设计文档

---

[Unreleased]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/releases/tag/v0.1.0
