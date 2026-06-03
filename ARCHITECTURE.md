# IC验证辅助代码生成平台 — 架构设计文档（ARCHITECTURE）

**版本**：v2.25  
**状态**：已确认  
**日期**：2026-06-03  
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
- v2.8 → v2.9：架构分层解耦优化——新增代码类型注册表（§3.14，code_types/*.yaml 驱动，零 Python 代码扩展新类型）；新增生成流水线编排器（§3.15，8步 Pipeline 统一入口）；服务层重组为 core/rag/llm/intent/parser/platform 六子包（§7）；Excel 解析改为 schema 驱动（§3.9）；意图标准化 Prompt 改为 registry 驱动（§3.11.2）；templates 表 `category` 列重命名为 `code_type`（§4.1）；Qdrant payload 同步更名（§4.2）；新增 GET /api/v1/generate/code-types 端点（§5.1）；模板 YAML `category` 字段改为 `code_type`（§6）；data/ 目录新增 code_types/、schemas/、scenarios/ 三个子目录（§7）
- v2.9 → v2.10：模板查重机制优化——步骤 B 从 Stage1 Hybrid RRF 检索改为 dense-only 余弦相似度检索（§3.8），解决 RRF 分数缺乏可解释单位的问题；补充说明框（关键词重叠 ≠ 语义重复，dense-only 与生成链路 hybrid 两套查询独立）；更新 TEMPLATE_DEDUP_THRESHOLD 环境变量注释（§8.4）
- v2.10 → v2.11：初始实现对齐——API v1 端点平铺于 api/v1/（删除 endpoints/ 子目录），贡献者与管理员审核端点合并为单文件（§3.10.4）；code-types 端点路径更正为 /api/v1/generate/code-types（§3.14.4、§5.1）；流水线接口类更名为 PipelineInput/PipelineResult，Step 1 改为 IntentNormalize（§3.15.2、§3.15.3）；备份 volume 更正为 backend_backups（§3.13.2）；迁移文件合并为 001_initial_schema.py（§7）
- v2.11 → v2.12：流水线鲁棒性与 thinking 模型支持——OpenAI 兼容客户端拆为"选模板 + 填参数"两步纯文本调用，规避 GLM-4.7 等 thinking 模型 reasoning_tokens 截断问题，max_tokens 提升至 4096（§3.12.2、§3.12.3）；Pipeline 在 RAG 后增加关键词补充召回、意图正则参数提取、LLM 失败 fallback 三层兜底（§3.15.3）；lib_manager 用 `uuid.uuid5(NAMESPACE_DNS, template.id)` 派生确定性 Qdrant point ID，修复 rebuild 重复 point bug（§3.8）；新增 docker-compose.hotreload.yml 开发 overlay（§8.2）；nginx 入口启用 Docker 内置 resolver `127.0.0.11 valid=10s` + 变量化 proxy_pass，解决 backend 容器重启后 nginx 缓存旧 IP 导致 502 的问题（§8.3）；前端容器 nginx 对 index.html 强制 `no-cache` 响应头，确保 hash 化 bundle 升级后浏览器立即拉新（§8.3）
- v2.12 → v2.13：方案 3 两步式 UI 落地——`run_pipeline` 拆为 `pipeline_preview` + `pipeline_render`（§3.15.3），新增 `/api/v1/generate/preview` 端点 + 增强 `/api/v1/generate/render` 端点（§5.1）；`_map_params` 重写为 `_map_params_with_source`，每参数标注 5 类来源（signal_list / regex / llm / default / placeholder）（§3.15.4）；新增 `confidence_source` 字段区分 LLM 主动选中 vs RAG fallback vs 意图缓存命中（§3.15.5）；前端引入 ConfirmationPanel + ParametersForm 两步式确认面板（§3.16），意图缓存命中走 `quick_render=true` 路径自动跳过确认；既有 `/generate` 端点改为内部调 preview+render，对 batch_tasks 调用方零变更
- v2.13 → v2.14：参数 expr_type 元数据 + 标识符规范化层落地——模板 YAML 的 `parameters[].expr_type` 字段声明参数语法类型（`sv_identifier` / `sv_identifier_list` / `sv_boolean_expr` / `sv_bins_expr`）；新增 `services/core/identifier.py`（SV 标识符 sanitize + IDENTIFIER_PARAMS 兜底白名单 + `construct_group_name`）和 `services/core/expr_validator.py`（轻量手写状态机校验布尔/列表/bins 表达式）；`_map_params_with_source` 末尾追加 expr_type-driven Step 7（覆盖所有 5 类源，sv_identifier 类参数被静默清洗、布尔/bins 类校验失败仅打 `validation_error`）（§3.15.5 新增）；`PreviewResponse.params` schema 新增 `sanitized` / `expr_type` / `validation_error` 三字段供前端徽标提示；前端镜像 `frontend/src/utils/exprValidators.ts`（§7）；§5.1 端点表补齐 `/api/v1/generate/preview`、`/api/v1/auth/register`、`/api/v1/auth/me`、`/api/health`，移除不存在的 `/api/v1/auth/refresh`；`lib_manager.py import` 在参数缺 `expr_type` 时输出 WARN 提示
- v2.14 → v2.15：契约修订 + RAG 原生 off-topic 闸——"always produce code" 契约**收窄为仅对域内 IC 输入**（§1.1）；新增 `services/rag/engine.py::dense_top1_score` helper 复用 Qdrant dense 通道；`pipeline_preview` 头部插入 dense 阈值闸（用 `original_intent` 而非 `normalized`——后者会被 LLM 改写成"无法判断类型"等元说明意外抬高 off-topic 分数），低于 `OFFTOPIC_DENSE_THRESHOLD`（校准默认 0.44）抛 `OffTopicIntentError` 返 HTTP 422；`generate.py` 端点结构化 detail（`type=off_topic` + `detector` + `top_dense_score` + `threshold`）让前端弹专属 Modal；`OFFTOPIC_GATE_ENABLED=false` 紧急 kill-switch；删除前一轮的 normalizer sentinel 注入式临时方案（恢复 `normalize_intent` 提示词为纯改写）；新增 `backend/scripts/calibrate_offtopic_threshold.py` 经验校准脚本；回归语料 `backend/tests/data/offtopic_corpus.yaml` + mock/real-LLM 双套件保留
- v2.15 → v2.16：thinking 控制由全局硬编码改为**按 LLM 调用分档 + 按配置可调**（§3.12.2、§3.12.3）——`llm_configs` 表新增 `step2_disable_thinking` BOOLEAN 列（NOT NULL，默认 true；迁移 `002_step2_disable_thinking.py`）（§4.1）；`normalize_intent` 与 `_step1_select_id` 硬编码禁 thinking 且收紧 `max_tokens`（512 / 64），`_step2_fill_params` 由 `llm_configs.step2_disable_thinking` 运行时切换（true→`max_tokens=2048` 禁 thinking，false→`max_tokens=1024` 保留 thinking）；所有 OpenAI-compat 调用打点 `[Timing] llm=<name> ms=<n> reasoning_tokens=<n> thinking=<on/off>` 便于验证 `extra_body` 是否被模型实际识别；`LLMConfigCreate/Update/Out` 三个 Schema 透出新字段，Admin UI 加 Switch（§5.1）；前端 `/generate` 与 `/generate/preview` 客户端超时由 180s 提升至 300s（thinking ON 模式下三步累加可达 ~4min）
- v2.16 → v2.17：缓存结构按 LLM 配置分桶 + intent_cache schema-drift 兜底 + RAG 空召回独立错误路径——`gen:{llm_config_id}:{template_id}:{version}:{params_hash}` 替换旧 `cache:{sha256(...)}` 复合 hash；`intent_cache:{llm_config_id}:{intent_hash}` 同样按配置分桶，TTL 30d（§3.6）；`services/intent/history.py::template_params_fingerprint()` 对 `parameters[].name/required/expr_type` 三字段取稳定指纹随 intent_cache 条目写入，命中时与当前模板指纹比对，漂移即 bypass 走完整流水线（§3.15.3 Step 2）；新增 `EmptyRetrievalError`（继承 `RuntimeError` 而非 `ValueError`，避免被泛化 `except ValueError` 兜底）—— off-topic 闸通过但关键词补充召回后仍返空时抛出，端点结构化 detail（`type=empty_retrieval` / `code_type` / `hint`）映射 **HTTP 503**，与 off-topic 422 分流（§3.15.3 Step 4 / §5.1）；缓存失效原语拆为 `invalidate_template_cache(tid)`（用 `gen:*:{tid}:*` 通配跨所有配置桶删除单模板）+ `invalidate_all_intent_cache()`（lib_manager 批量重导 hook）+ `invalidate_all_llm_caches()`（admin LLM CRUD/set-default 时仍全清两个前缀，分桶不是为了切换后保留旧缓存，而是为了 update 单模板时能跨配置精准失效）；迁移 `003_align_sync_status_enum.py` 幂等修正 `sync_status_enum` 旧值 `('pending','synced','error')` 到 ORM 值 `('ok','syncing','sync_error')`（兼容 `app/main.py:_init_db` 的 `create_all` 先于 alembic 跑、dev DB 已是 ORM 值的情况）；迁移 `004_unique_default_llm.py` 把 §4.1 已声明的部分唯一索引 `WHERE is_default=true` 落到 alembic 树上（兜底并发 set-default 留多行 True 导致 `MultipleResultsFound` → 500）
- v2.17 → v2.18：**对齐 PRD v3.0 用户旅程重构**——新增两道 422 闸 + IntentBuilder 多轮对话 + 贡献机制 LLM 反推 + 错误响应 `redirect_to` 字段：
  - **`CodeTypeMismatchError`（HTTP 422 `code_type_mismatch`）**（§3.15.3）：通过 off-topic 闸后插入 `_detect_code_type_mismatch`，对所有注册 code_type 逐一算 dense top-1 score，若某非当前 code_type 的得分高于当前 ≥ `CODE_TYPE_MISMATCH_MARGIN`（默认 0.10）则抛错，结构化 detail 含 `current_code_type` / `suggested_code_type` / `current_score` / `suggested_score`，前端原页面 Modal 引导切换类型；可关闸 `CODE_TYPE_MISMATCH_GATE_ENABLED=false`（off-topic 关时本闸也自动跳）
  - **`UnderSpecifiedIntentError`（HTTP 422 `under_specified`）**（§3.15.3、§3.15.5）：Step 6 参数映射后插入 `_detect_under_specified`，识别"必填但只有低置信源"参数（source ∈ {placeholder, semantic_fallback}，或 LLM 返"trivial 值"如空串/0/字面参数名），抛错带 `missing_params: [{name, description, expr_type, role_hint}]` 列表 + `redirect_to: /intent-builder?prefill=...&missing=...`，前端 `handleApiError` 读到 `redirect_to` 直接 `router.push` 跳 IntentBuilder 精修；可关闸 `UNDER_SPECIFIED_GATE_ENABLED=false`
  - **第 6 类参数源 `semantic_fallback`**（§3.15.5）：原 `default` 拆分为两类——`default`（模板设计者声明的默认 / 用户在前端编辑过的值）vs `semantic_fallback`（系统按语义规则猜的值：`group_name` 用 `construct_group_name` 合成、`state_list="IDLE, ACTIVE, DONE"`、`bins_expr=f"{{[0:{2**width-1}]}}"`）。同时 group_name 被 sanitize/construct 改写后 source 自动升级到 `semantic_fallback`，避免"系统猜的值被规范化后伪装成 user 给的"
  - **`/api/v1/intent-builder/chat` 多轮对话端点**（§3.11、§5.1）：替换原 `/scenarios` + `/build`（两者改返 HTTP 410 Gone + 提示语）；新增 `services/intent/conversation.py::run_one_turn`（每轮跑一次 RAG 把 top-3 模板 description 喂回 prompt 引导用户往已存在模板靠拢）+ `services/intent/session.py`（Redis key `intent_builder_session:{user_id}:{session_id}`，TTL 24h，未登录禁用，按用户隔离）；LLM 沿用 `llm_configs.is_default`
  - **`LLMClient.chat(messages, max_tokens, temperature)` 通用多轮接口**（§3.12）：在 `base.py` 抽象方法添加，Anthropic / OpenAICompat 两条实现都补齐；供 IntentBuilder 与贡献机制 LLM 反推共用，默认不打 thinking 开关
  - **模板贡献机制 LLM 反推**（§3.10）：新增 `services/platform/parameter_extractor.py::derive_parameters_from_demo`——用户只填 `name + code_type + description + demo_code` 时，后端 LLM 反推 `parameter_defs` + Jinja2 化的 `template_body` + `keywords` + `subcategory` + `protocol`；用户也可手动传 `parameter_defs` 走旧路径（contributions.py 内部分支）。审核员在 AdminContributionsPage 三栏（原始代码 / 反推模板 / 反推参数）任意修改后批准
  - **PipelineInput `source: "intent_builder" | "direct" = "direct"`**（§3.15.2）：仅供日志/统计区分入口，不影响路由逻辑
  - **`normalize_intent` 角色降级**（§3.11）：从"四层标准化机制核心"降为"弃权信号载体 + cache key 稳定器"，sentinel "无法判断类型，输出原文"保留但下游不再用它做兜底——sentinel 之后参数仍是低置信源时 `under_specified` 闸照常拦
  - **`redirect_to` 字段约定**（§5.1）：仅 `under_specified` 返 `/intent-builder?prefill=...&missing=...`；`off_topic` / `empty_retrieval` / `code_type_mismatch` 返 `None`（前者 IntentBuilder 救不了真离题；中间是基础设施问题；后者前端在原页面 Modal 切换类型）
  - **环境变量**（§8.4）：新增 `CODE_TYPE_MISMATCH_GATE_ENABLED` / `CODE_TYPE_MISMATCH_MARGIN` / `UNDER_SPECIFIED_GATE_ENABLED`
- v2.18 → v2.19：v3.0 实现细节补全——
  - §3.10.1 贡献提交流补齐 v3.0 LLM 反推路径的三道**校验闸**（`_validate_parameter_defs` 参数命名合法 / `_validate_jinja_rendering` 占位值能渲染 / `_validate_keywords` 形态）与**dedup 预扫**（提交时调 `check_semantic_duplicate` 把 top-3 相似已入库模板塞 `original_row_json["similar_templates"]`，失败非阻塞仅 WARN），任一校验失败抛 `ContributionParseError → 422 contribution_parse_failed`；同步列出三个入口点（批量低置信行 / IntentBuilder 5 轮无候选 / 我的贡献页"+ 新贡献"）
  - §3.11.5 IntentBuilder 补齐**5 轮对话上限**与 `suggest_contribute` 信号：每轮把 top-1 RAG score 记入 session；5 轮全 < 0.5 → 响应携 `suggest_contribute=True`，前端展示"我们的库似乎不覆盖这个场景"+ §3.10 贡献入口；LLM system prompt 强制约束输出末尾用 `<<intent>>...<<end>>` 包裹累积标准化意图供前端 prefill；并强制 RAG-priority（每轮 LLM 调用前必先跑 RAG 注入 top-3 候选 description，不允许 LLM 凭空想象新场景）
  - §3.11.3 上传预检在 v3.0 **缩水**：仅展示低置信行的"最近似模板"，不再引导逐行修改；批量场景下"低质量行"由 v3.0 `under_specified` 闸在逐行 `run_pipeline` 时 422，前端标红展示
- v2.19 → v2.20：**FEAT-10 贡献流程二次简化为 2 字段必填 + intent-only LLM 生成**——
  - §3.10.1 新增 `generate_from_intent(original_intent, code_type, llm) → ExtractedFull` 函数（`services/platform/parameter_extractor.py`），LLM 一次性生成 `template_name + description + demo_code + parameter_defs + jinja_body + keywords + subcategory + protocol`；在原 3 道校验闸（参数命名 / Jinja2 沙箱 / keywords 形态）之外新增 `_validate_template_name` 第 4 道校验，强制 `^(sva|cov)_[a-z][a-z0-9_]*_v\d+$` 命名规范，违规抛 `ContributionParseError(stage="template_name")`
  - §3.10.1 `POST /api/v1/contributions` 重构为 3 分支并存（按顺序判断）：(1) 缺关键字段（`template_name` 或 `demo_code`）→ 触发 `generate_from_intent`；(2) 显式传 `parameter_defs` → v2 批量路径不调 LLM；(3) 4 字段齐全 → 原 `derive_parameters_from_demo` demo 反推路径；分支 1 同样跑 dedup 预扫与 name 精确查重
  - §5.1 端点表新增 `POST /api/v1/contributions/preview`（仅基于 `original_intent + code_type` 让 LLM 生成完整模板预览，**不入库**），返回 `{template_name, description, demo_code, parameter_defs, keywords, name_conflict}`；`name_conflict` 由 `check_name_duplicate` 计算，**非阻塞**——前端展示 Warning Alert 让用户改名后再调 submit；解析失败统一走 `422 contribution_parse_failed`（与现 submit 端点同结构 `detail.type / detail.stage / detail.reason`）
  - §5.1 `POST /api/v1/contributions` 响应 schema `ContributionOut` 新增 `use_immediately_available: bool = True` 字段（前端用于条件渲染"立即使用"按钮）
  - §3.10.1 「立即使用」路径定型为**在 Step 2 Modal 内展示可复制代码框**（`<pre>` monospace + 「复制代码」按钮 + 提示文案"代码已就绪，可直接复制使用。模板已提交审核，审核通过后将加入模板库。"），**不跳转 `/generate`**——`pending_review` 贡献不在 Qdrant 中，跳过去只会触发第五道闸 `no_matching_template` 进入循环；该贡献仍以 `status=pending_review` 进审核队列
  - 双层审核机制成型：第一层是 Step 2 用户对 LLM 输出的语义级校对（编辑或接受 `template_name / description / demo_code`），第二层是管理员三栏审核（不变）
  - schema 变更：`ContributionCreate.original_intent` 升必填（去掉 `Optional`），`template_name / description / demo_code` 改为 `Optional`；新增 `ContributionPreviewRequest / ContributionPreviewResponse`；`ContributionOut` 增 `use_immediately_available`
  - 前端：`MyContributionsPage` 提交 Modal 改为 Ant Design 两步 Steps；`contributions.ts` 新增 `contributionsApi.preview()` 方法与 `ContributionPreview` 接口
- v2.20 → v2.21：**Step1 模板选择精度提升 — 候选渲染扩容 + description audit + 混淆语料 + 二次验证 + reranker score gate**——
  - §3.15.3 Step 5a：`_step1_select_id` 候选渲染由单行字符串改为 Markdown 多行块（`### {i}. {template_id}  {name}\n描述：...`）；description 截断阈值由 60 char 扩到 **1000 char**（spec 中先记的 300 在 review NEW-1 后改为 1000，原因是 `lib_manager.py import` 在描述末尾追加合成的"区别要点："/"不适用场景："两段，合成总长实测最长达 812 char，需余量避免末项被切）；`_step1_select_id` 的 `max_tokens` **保持 64 不变**（仅输入侧扩容，输出仍是 `template_id` 或 `"none"`）；GLM-4.7 实测 step1 延迟增幅 < 1s
  - §3.15.3 Step 5a：新增 **A8 step1 二次验证**——`pipeline.py` 在 step1 选中且 `confidence_source == "llm_step1"` 时，调用 `llm.verify_step1_selection(normalized_intent, selected_id, candidates)` 发一条 yes/no 问询；LLM 答 `no` → 把 `confidence_source` 降级为 `"rag_fallback"` 并把 `template` 置空，让后续 fallback 链按 `rag_fallback` 走 RAG top-1，可被第五道闸 `NoMatchingTemplateError` 接管；fail-open（LLM 调用/解析失败一律视为通过）；`STEP1_VERIFY_ENABLED` 开关，**默认 `False`**（开启前需先用 `tests/test_template_confusion_corpus_real_llm.py --real-llm` 评估 false-negative 率）；`max_tokens=16` / `thinking=disabled`
  - §3.15.3 Step 5a：新增 **A9 reranker score gate**（pipeline 层独立 gate）——A8 验证通过后查 `rag_candidates` 中 `template_id == selection.template_id` 那一条的 `score` 字段（即 stage3 reranker score，由 `services/rag/engine.py` enriched 写入），低于 `RERANKER_MIN_SCORE_THRESHOLD`（默认 0.30，未标定的经验占位值）→ 抛 `NoMatchingTemplateError(top_score=selected_score)`；`STEP1_RERANKER_GATE_ENABLED` 开关，**默认 `False`**（开启前需跑 `scripts/calibrate_reranker_threshold.py` 在 `template_selection_corpus.yaml + template_confusion_corpus.yaml` 上标定 `correct_p10 / wrong_p50` 中点后写回 `reranker_min_score_threshold`）
  - §3.15.3 Step 5a：**A9 与 FIX-9 移除的 `no_match_score_threshold` 的语义区分**——FIX-9 拦的是 RAG **top-1** score（"top-1 分数低就整体否决 LLM"），cross-encoder 词汇重叠会让无关握手模板拿 1.0 分把 LLM 正确的 `none` 判断否决，已经移除；A9 拦的是 **LLM 选中的那个 template_id** 的 reranker score（"LLM 信心十足选了某 id，但该 id 客观重排得分仍偏低"），是 LLM 决策 + reranker 复核的双信号互证，触发更稀少且方向更精确。`no_match_score_threshold` 仍保留供日志/监控参考，**不参与触发判定**
  - §6 模板 YAML 文件规范：新增 `differentiators`（list[str]，列出与最近邻模板的 2–3 条区别）与 `non_use_cases`（list[str]，列出 2–3 条不适用场景）两个可选字段；`description` 字段约定升级为"做什么 / 典型场景 / 边界（请勿用于 X 请用 Y）"三要素。`lib_manager.py import` 通过新增的 `_compose_description(base, differentiators, non_use_cases)` helper **在 import 时把两个字段拼到 `description` 列末尾**（"区别要点："/"不适用场景："标题段，每段 list 前缀 `- `），由现有列流转到 Qdrant payload + reranker text + pipeline.candidate_dicts + LLM prompt，**避免 DB schema 变更**；`lib_manager.py validate` 同步新增校验：`description` 缺失或 < 30 字节 WARN（鼓励补齐三要素），`differentiators` / `non_use_cases` 若存在必须是非空 list 否则 ERROR
  - §8.4 环境变量新增三项：`STEP1_VERIFY_ENABLED`（默认 false）、`STEP1_RERANKER_GATE_ENABLED`（默认 false）、`RERANKER_MIN_SCORE_THRESHOLD`（默认 0.30）
  - 新增配套测试基础设施：`backend/tests/data/template_confusion_corpus.yaml`（近邻混淆对回归语料 ≥10 条种子，涵盖 pair-A `handshake_stable` ↔ `handshake_timeout` × 4 / pair-B `timing_max_delay` ↔ `handshake_timeout` × 4 / FSM × 1 / coverage × 1）+ `test_template_confusion_corpus_mocked.py`（CI 必跑，mock RAG 把 `confusion_template` 注入为 top-1，断言 pipeline 最终选中 `correct_template`）+ `test_template_confusion_corpus_real_llm.py --real-llm`（手动套件）+ `scripts/calibrate_reranker_threshold.py`（A9 阈值标定）
- v2.21 → v2.22：**L3 用户反馈 + L4 管理员分析仪表盘数据基础设施**——
  - §4.1 `generation_records` 表新增 6 列（migration 006）：`feedback_rating SMALLINT`（1=好/2=一般/3=差）、`feedback_reason_tags JSONB`（7 项 `ReasonTagEnum` 枚举数组）、`feedback_comment TEXT(≤2048)`、`feedback_at TIMESTAMPTZ`、`generation_mode VARCHAR(16) DEFAULT 'rag'`（`'rag'` / `'llm_direct'` 为 L2 预留）、`gate_error_type VARCHAR(32)`（5 道闸触发标记）；全部 nullable，正常生成路径与 batch 老记录不受影响
  - §4.1.1 新增 "feedback API 数据流" 子节：`POST /api/v1/feedback/{generation_record_id}` 写 4 个 feedback 列；权限 owner-or-admin（`record.user_id == current_user.id OR current_user.role in {lib_admin, super_admin}`），`rating=3` 必填 `reason_tags`（Pydantic `model_validator` 抛 `PydanticCustomError(type='reason_tags_required')`），成功返 204
  - §4.1.2 新增 "admin analytics 模块" 子节：4 个 KPI 端点（`/admin/analytics/{feedback-summary, template-issues, intent-confusion, no-match-rate}`）的 SQL 聚合关键策略 + 数据源约定（`intent-confusion` 用 `rag_top3[0]` 作为 `expected_template`、`no-match-rate` 用 `gate_error_type='no_matching_template'`），全部要求 `lib_admin` / `super_admin`，`days` 窗 ∈ [1, 90] 默认 7
  - §4.1.3 新增 "generate endpoint 422 catch 路径写 record" 子节：`api/v1/generate.py` 在 5 道闸 catch 块通过 `_record_gate_event` 写 `GenerationRecord(template_id=None, gate_error_type=<type>)`，`gate_error_type` 取值与异常一一对应（off_topic / code_type_mismatch / under_specified / no_matching_template / empty_retrieval）；**不修改 `services/core/pipeline.py` 闸判断逻辑**，仅在端点层补持久化，对确定性契约（§1.1）无影响
  - §5.1 端点表追加 5 条：`POST /feedback/{id}`（普通用户/库管理员+） + 4 个 `/admin/analytics/*`（库管理员+）
- v2.22 → v2.23：**FEAT-11 Stage 2 双模生成（rag + llm_direct）落地**——
  - §1.1 确定性契约修订（v2.15 之后第二次修订）：原"LLM 在 RAG 中的职责边界 ... 不生成任何代码"约束**收窄为仅对 `generation_mode='rag'` 路径**；新增 `generation_mode='llm_direct'` 路径，明确声明为**非确定性 by design**。`llm_direct` 路径只对 `gen_llm:*` Redis 7d TTL 缓存命中呈现"伪确定性"，TTL 过期或切换 LLM 默认配置后即重新生成。`rag`/`llm_direct` 标签必须在 record / 响应 / UI 三处同时打——后端 `GenerationRecord.generation_mode` 列、`POST /generate/llm-fallback` 响应 `generation_mode: "llm_direct"` 字段、前端 result 阶段 `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>` 三处同步
  - 新增 §3.17 `llm_direct` 生成路径完整文档：`POST /api/v1/generate/llm-fallback` 端点契约、`LLMClient.generate_code_freeform` 抽象方法 + 两实现（Anthropic native messages / OpenAI-compat chat + regex 提取 `systemverilog`/`sv`/`verilog` 围栏）、`gen_llm:{llm_config_id}:{sha256(canonical(intent+code_type+signals+clk+rst))}` 7d TTL 缓存（signals 按 name 排序保证顺序无关）、`parent_record_id` FK 回链契约（`ondelete=SET NULL`）、非确定性标签三处同步约定、三类 422 错误（`llm_direct_chained_not_allowed` / `llm_direct_no_code` / `llm_direct_internal_error`）的 detail 结构
  - §3.15.3 / §3.16 扩展 **A 子项：高置信 RAG 自动 quick_render**——`pipeline_preview` 在 `_detect_under_specified` 之后新增 `_is_high_confidence_rag(result, settings, verify_ok, selected_score, params_with_source) -> bool` 判定，四条件齐绿（`confidence_source==llm_step1` + `step1_verify_enabled` 且 `verify_ok=True` + `selected_score >= reranker_min_score_threshold` + 所有 param sources ∈ `{llm, regex, signal_list, default}`）→ `quick_render=True`，与 intent_cache 命中共用同一旗标让前端跳过 ConfirmationPanel。`selected_score` 从 A9 gate 专用计算上移到 `confidence_source==llm_step1` 通用计算，A9 与高置信判定共用同一份值
  - §3.12.2 `LLMClient` 抽象表新增第 4 条方法 `generate_code_freeform(intent, code_type, signals, clk, rst) -> str`；OpenAI-compat 实现硬编码 `extra_body={"thinking":{"type":"disabled"}}` + `max_tokens=2048`（与 normalize_intent / step1 一致禁 thinking），Anthropic 实现走 native messages API；prose-only 响应（无 ` ```systemverilog/sv/verilog``` ` 围栏）抛 `ValueError("no_sv_code_block")` 由端点翻译为 HTTP 422 `llm_direct_no_code`
  - §3.6 缓存键设计扩为三类（增加 `gen_llm:*`）：`gen_llm:{llm_config_id}:{sha256(canonical(intent+code_type+signals+clk+rst))}` 7d TTL 用于 `llm_direct` 兜底缓存；`invalidate_all_llm_caches()` 同步 scan-delete 三个前缀（`gen:*` / `intent_cache:*` / `gen_llm:*`），切换默认 LLM 配置后 `llm_direct` 缓存与 RAG 两层缓存一起失效
  - §3.15.2 `/render` 端点响应 `RenderResponse` 新增 `generation_mode: Literal["rag", "llm_direct"] = "rag"` 字段（枚举值仅这两项，Pydantic 在响应序列化时拦非法值），前端据此初始化 `state.result.generation_mode` 决定是否显示 `llm_direct` fallback 按钮；正常 RAG 路径恒返 `"rag"`
  - §4.1 `generation_records` 表 `generation_mode` 列含义升级：从"L2 预留"变为"代码来源的真实标签"，新增 `parent_record_id VARCHAR(36) NULLABLE FK→generation_records.id ondelete=SET NULL` 列（migration 007），让 `llm_direct` 子记录回链触发本次 fallback 的源 RAG 记录；源记录被 admin 删除仅清空 FK，保留 `llm_direct` 子记录与其反馈数据
  - §4.1.2 4 个 KPI 端点 SQL 聚合策略表新增 optional `generation_mode` query 参数：`feedback-summary` / `template-issues` / `intent-confusion` / `no-match-rate` 全部支持。`template-issues` 在 `generation_mode=llm_direct` 时把 `template_id IS NULL` 行归入 `__llm_direct__` 桶不再被默认 `IS NOT NULL` filter 排除
  - §7 项目目录结构：`migrations/versions/` 列举更新为 001 / 002 / 003 / 004 / 005 / 006 / 007 七个迁移文件（含简要功能注释），不再仅列 001
  - §5.1 端点表追加 1 条：`POST /generate/llm-fallback`（普通用户）
- v2.23 → v2.24：**FEAT-12 用户对比报告系统落地**——
  - 新增 §3.18 `improvement_reports` 路径完整文档：从 GeneratePage 「提交对比报告」按钮 → `GET /improvement-reports/check` 预查（驱动按钮 disabled 态）→ `POST /improvement-reports`（用户端，写 `status='pending'`）→ admin 列表 / 详情自动 PATCH `pending → in_review` → admin 写 `admin_note` + 「标记已处理」PATCH `in_review → resolved` 的完整链路；引用 §4.1.4 表结构、§5.1 端点表
  - §4.1 `generation_records` 表追加备注：`parent_record_id`（v2.23 引入的 `llm_direct` 子记录 → RAG 源记录 FK）同时是 `improvement_reports.rag_record_id` / `improvement_reports.llm_direct_record_id` 配对的"语义锚点"——`POST /improvement-reports` 要求 `rag_record_id == llm_direct_record.parent_record_id`（端点层显式校验或前端守门，后端容忍 user 自行构造的合法对）；删除源 RAG 记录不级联删除 `improvement_reports`（FEAT-12 不解决该清理路径）
  - §4.1.4 新增 `improvement_reports` 表结构（migration 008）：字段 / 类型 / 约束 / UNIQUE(rag_record_id, llm_direct_record_id) / 状态 ENUM `report_status_enum('pending','in_review','resolved')` 取值 / `report_categories JSONB` 列存 4 项 `ReportCategoryEnum` slug（`wrong_template` / `wrong_params` / `poor_style` / `other`）与中文 label 双向对照表
  - §5.1 端点表追加 5 行：`POST /improvement-reports`（登录用户+）、`GET /improvement-reports/check`（登录用户+，鉴权与 POST 同级，不限 admin）、`GET /admin/improvement-reports`（库管理员+，支持 `status`/`categories` 过滤）、`GET /admin/improvement-reports/{id}`（库管理员+，返两条 generation_record 完整对比字段）、`PATCH /admin/improvement-reports/{id}`（库管理员+，三态状态机非法跳转返 422 `illegal_status_transition`）；3 类错误 `duplicate_report`(409) / `invalid_record_ref`(422) / `illegal_status_transition`(422) 详见 PRD §6.1 错误模式表
  - §7 目录结构追加：`backend/app/api/v1/improvement_reports.py`（4+1 路由） / `backend/app/models/improvement_report.py`（ORM）/ `backend/app/schemas/improvement_report.py`（4 个 Pydantic）/ 前端 `frontend/src/api/improvementReports.ts` / `frontend/src/pages/Admin/AdminImprovementReportsPage.tsx` / `frontend/src/pages/Admin/AdminImprovementReportDetailPage.tsx`，外加 `frontend/src/pages/Generate/GeneratePage.tsx` 与 `frontend/src/components/MainLayout.tsx` / `frontend/src/App.tsx` 增量改动
  - §7 migrations 列表追加 `008_improvement_reports.py`（建表 + `report_status_enum` 创建 + UNIQUE 约束 + FK → generation_records.id ondelete=RESTRICT）
  - 与 §3.17 / §1.1 确定性契约的边界：`improvement_reports` 路径是**纯 DB 写入**，不调用 LLM、不参与 RAG 检索、不影响 `generation_records.output_code`；它消费 `generation_records` 现有 FK（`parent_record_id`）作为配对锚点。对 §1.1 确定性契约（`rag` / `llm_direct` 路径）**无影响**
- v2.24 → v2.25：**FEAT-13 模板成熟度门控（maturity_level 三档 + RAG 默认仅召回 production + admin 提升降级 UI）**——
  - §4.1 `templates` 表新增 `maturity_level` 列（PostgreSQL ENUM `template_maturity_enum`，值 `production / experimental / draft`，NOT NULL，server_default `'experimental'`），与既有 `maturity` 列（值 `draft / validated / production`，"开发成熟度"）**并存且语义独立**——`maturity_level` 专责"生产门控"（是否进入 RAG 召回主库），`maturity` 描述"开发成熟度"（模板设计者标注的迭代位）；两列共用部分 enum 值（`draft` / `production`）纯属语义重合无关联，**不得混用**
  - 新增 §3.2 RAG 三阶段 maturity 过滤说明：stage1 `stage1_hybrid_search` Qdrant `Filter.must` 在 `code_type` 之外追加 `FieldCondition(key='maturity_level', match=MatchValue(value='production'))`；`engine.py::rag_retrieve` 的 DB 查询 `select Template where id in template_ids and is_active==True` 追加 `and Template.maturity_level=='production'` 作为**双重防御**（应对 Qdrant payload 缺失字段的边角场景）；`dense_top1_score` 同样追加 `maturity_level='production'` Filter，影响 off-topic gate 与 code_type mismatch gate 两处调用点（两个 gate 的阈值校准基线随之变化，**spec §5 风险记录**：上线后可能需重跑 `calibrate_offtopic_threshold.py` 验证 `OFFTOPIC_DENSE_THRESHOLD` 仍合理）
  - §3.15.3 Step 5a LLM step1 候选生成路径说明：由于 RAG 三阶段（stage1 Qdrant Filter + engine.py DB Filter）已保证返回候选列表**仅含 production 模板**，`pipeline_preview` 组装 `candidate_dicts` 之前**无需**在 pipeline 层再单独过滤 `maturity_level`，依赖链 = Qdrant payload → stage1 Filter → engine.py DB Filter → `rag_candidates` → `candidate_dicts`
  - §3.4 Qdrant Collection payload 字段表新增 `maturity_level`（用于 stage1 Filter）；`lib_manager.py::_sync_to_qdrant` 在 `PointStruct.payload` 中加 `"maturity_level": template.maturity_level`（兼容性 `getattr(template, 'maturity_level', 'experimental')`）；**Qdrant payload 冷启动注意事项**：现有 Qdrant collection 中的 points 没有 `maturity_level` payload 字段，stage1 Filter 会把它们全部过滤掉。上线流程**必须先 `alembic upgrade head` 再 `lib_manager.py rebuild`**（或 `lib_manager.py import --force`）让所有 points 带上正确 `maturity_level` payload，否则 RAG 召回为空 → `EmptyRetrievalError` → 全量 HTTP 503
  - §3.10 贡献流：`_create_template_from_contribution`（`templates.py`）新建模板时 `maturity_level` 固定写 `'experimental'`（无论 contribution 的 `maturity` 字段取值），admin 通过 review 后该模板仍保持 `experimental`；须 super_admin 在「模板库管理」页（`AdminTemplatesPage.tsx`）显式点「升级到 production」走 `PATCH /api/v1/admin/templates/{id} {maturity_level: 'production'}` 才进入 RAG 召回主库
  - §3.4 Admin 模板管理页 UI：表格新增 `maturity_level` 列（带颜色 Tag：`production=green` / `experimental=orange` / `draft=blue`）；行内操作区追加「升级到 production」「降级到 experimental」两个按钮，**仅 `current_user.role=='super_admin'` 时渲染**（`lib_admin` 隐藏，不可见亦不可点）；编辑 Modal 中保留原 `maturity` 字段不变，**不得**将 `maturity_level` 与 `maturity` 合并到同一 Form.Item（避免审核员误改）
  - §5.1 端点契约：`PATCH /api/v1/admin/templates/{id}` 在 payload 含 `maturity_level` 时新增权限校验——`current_user.role != 'super_admin'` 返 HTTP 403 `detail="仅 super_admin 可修改 maturity_level"`；非法 enum 值（非 `production/experimental/draft`）由 Pydantic schema 返 HTTP 422
  - §7 项目目录结构 + migrations 列表追加 `009_template_maturity_level.py`（创建 `template_maturity_enum` PG ENUM + `templates.maturity_level` 列 + 全表 backfill：`id ~ '^(sva|cov)_.+_v[0-9]+$'` 命名规范的官方种子模板 UPDATE 为 `production`，其余行（含 `is_active=false`、含历史 `L6_E2E_*` 测试模板）由 `server_default='experimental'` 自动得到 `experimental` 或显式 UPDATE 兜底）；migration 009 `upgrade()` 末尾打印 `[WARN]` 提示部署方"必须紧接 `lib_manager.py rebuild` 同步 Qdrant payload"
  - §7 新增测试文件 `backend/tests/test_template_maturity_gating.py`（mock Qdrant / PG，覆盖 4 场景：stage1 Filter 包含 `maturity_level='production'` 条件；engine.py DB 二次过滤正确拦截非 production 模板；PATCH maturity_level 的 super_admin 200 / lib_admin 403 / 非法值 422；migration 009 backfill 条件函数单元测试）
  - **不在范围内**：FEAT-14 范畴的自动语料质量评分（`draft → experimental` 自动升级）、跨语料库 maturity 同步、`production → 退役` 流程、batch / contribution / IntentBuilder 路径的 maturity 显式 override 参数（RAG 默认生效，不开 explicit override API）、stage2 ColBERT 独立 maturity Filter（stage1 已保证输入是 production，stage2 透传即可）、修改既有 `maturity` 列 enum 值或列名（两列并存）、前端 Library 页 / Generate 页的 `maturity_level` 展示

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
│                               Redis 缓存（同输入命中即返）             │
│                                        ↓                             │
│                               Jinja2 渲染（100% 确定性）              │
│                                        ↓                             │
│                               SVA / UVM 代码输出                     │
└──────────────────────────────────────────────────────────────────────┘
```

**LLM 在 RAG 中的职责边界**：接收检索到的模板作为上下文，输出"选择哪个模板 + 填入哪些参数"，**不生成任何代码**。代码生成完全由 Jinja2 完成。**该约束的适用范围**：仅对 `generation_mode='rag'` 路径生效；v2.23 / FEAT-11 引入的 `generation_mode='llm_direct'` 兜底路径是 explicit 例外（详见 §3.17），明确声明为**非确定性 by design**。

**契约修订（v2.15）**：原"always produce code"契约范围收窄为**仅对域内（IC 验证）输入**。无关意图（诗歌/闲聊/数学题/通用代码请求等）经 RAG 之前的 dense 余弦阈值闸（threshold=0.44，原文 embedding × Qdrant top1 < 阈值）直接 HTTP 422 拒绝，不进入 LLM 调用链。阈值由 `backend/scripts/calibrate_offtopic_threshold.py` 在 `backend/tests/data/offtopic_corpus.yaml` 上经验校准；emergency kill-switch `OFFTOPIC_GATE_ENABLED=false`。

**契约修订（v2.23 / FEAT-11，双模架构）**：原"系统决定产出代码时必为字节级确定"约束**仅对 `rag` 路径成立**。`llm_direct` 路径由 `POST /generate/llm-fallback` 端点暴露，调用 `LLMClient.generate_code_freeform(intent, code_type, signals, clk, rst)`，LLM 自由生成 SystemVerilog 代码，**不经过 Jinja2 渲染层**。同一输入再次调用可能产出不同代码——这是设计内行为。`llm_direct` 路径只在 `gen_llm:{llm_config_id}:{sha256(canonical(intent+code_type+signals+clk+rst))}` 7d TTL Redis 缓存命中时呈现"伪确定性"，TTL 过期或切换 LLM 默认配置后即重新生成。非确定性标签必须在三处同时打：
- **后端记录层**：`GenerationRecord.generation_mode='llm_direct'` + `parent_record_id` FK 回链源 RAG 记录
- **API 响应层**：`POST /generate/llm-fallback` 响应体含 `generation_mode: "llm_direct"` 字段；`POST /generate/render`（RAG 路径）响应体含 `generation_mode: "rag"` 字段
- **前端 UI 层**：`llm_direct` 结果代码卡片头部强制渲染 `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>` 提示用户当前结果不在确定性契约保护范围内

链式禁止：源记录已是 `llm_direct` 时端点返 HTTP 422 `llm_direct_chained_not_allowed`——不允许 `llm_direct → llm_direct` 累积"漂得越来越远"的代码。

**四层确定性保障**：

| 层次 | 机制 | 确定性强度 |
|------|------|-----------|
| 缓存层 | Redis：input_hash → output，相同输入直接命中，跳过所有环节 | 100% 绝对确定性 |
| 检索层 | bge-m3 固定模型版本 + Qdrant 算法确定性 + ColBERT MaxSim 纯数学计算 | 算法确定性 |
| 解析层 | temperature=0 + JSON Schema 工具调用 + Pydantic 归一化 | 强约束确定性 |
| 渲染层 | Jinja2 StrictUndefined，参数缺失报错不静默 | 100% 确定性 |
| 域过滤 | dense 余弦阈值闸，无关意图早返 422，不进入下游 | 拒绝路径确定性 |

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
    "template_id":     "SVA-HAND-001",
    "code_type":       "assertion",
    "subcategory":     "handshake",
    "protocol":        ["AXI4", "AXI4-Lite"],
    "maturity":        "production",      # 开发成熟度，纯元数据
    "maturity_level":  "production"       # 生产门控（FEAT-13 / v2.25，stage1 Filter 必读）
}
```

**stage1 Qdrant Filter（v2.25 / FEAT-13）**：`stage1_hybrid_search` 构造 `Filter.must` 时在 `code_type` 条件之外追加 `FieldCondition(key='maturity_level', match=MatchValue(value='production'))`，stage1 召回**仅返回 production 模板**；`engine.py::dense_top1_score` 同样追加此 Filter，使 off-topic / code_type_mismatch gate 的 top-1 计算也只在 production 子集上进行。`lib_manager.py::_sync_to_qdrant` 在 `payload` dict 中加 `"maturity_level": getattr(template, 'maturity_level', 'experimental')`；**冷启动**必须先 `alembic upgrade head` 再 `lib_manager.py rebuild` 让所有 points 带上 payload 字段，否则 stage1 Filter 会把缺字段的旧 points 全部过滤掉。

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

**缓存键设计**（三类缓存，均按 LLM 配置分桶；`gen_llm:*` 由 v2.23 / FEAT-11 引入）：

```
# 生成结果缓存（pipeline_render 写入，TTL 90天）
gen:{llm_config_id}:{template_id}:{template_version}:{sha256(canonical_json(sorted params))}

# 意图归一化缓存（pipeline_preview Step 2 写入，TTL 30天）
intent_cache:{llm_config_id}:{intent_hash}
  value = JSON({template_id, params, confidence, params_fingerprint})

# llm_direct 兜底缓存（POST /generate/llm-fallback 写入，TTL 7天，v2.23 / FEAT-11）
gen_llm:{llm_config_id}:{sha256(canonical(intent + code_type + signals_sorted_by_name + clk + rst))}
  value = LLM 生成的 SystemVerilog 代码字符串
```

空 `llm_config_id` 用 `_` 占位（测试 mock / 早期未配置场景）。`params_hash` 拆出 `template_id` / `version` 单独是为了支持 `invalidate_template_cache(template_id)` 用 `gen:*:{template_id}:*` 通配跨所有配置桶精准失效。

`gen_llm:*` 的 canonical 序列化由 `services/core/cache.py::_canonical_llm_direct_signature(intent, code_type, signals, clk, rst)` 实现，`signals` 列表按 `name` 字段排序后 JSON dumps（`ensure_ascii=False, separators=(',', ':')`），保证同一逻辑输入在 signal 列表顺序不同时仍命中同一键。TTL 短于 `gen:*` 的 90d 是因为 `llm_direct` 路径本身非确定性，缓存只是给"同一用户连续点几次 fallback 按钮"加速，长时间复用会让用户误以为得到了确定性输出。

**缓存策略**：
- 命中：直接返回，跳过检索+LLM+渲染全部环节，100% 确定性
- 未命中：走完整链路，结果写入 Redis
- **intent_cache schema-drift 兜底**：命中条目里取出的 `params_fingerprint` 与当前模板 `template_params_fingerprint(template.parameters)` 比对（hash `name/required/expr_type` 三字段）；漂移即 bypass 缓存走完整 pipeline，避免模板参数改名/增删后旧 mapping 被短路返回
- 失效原语：
  - `invalidate_template_cache(tid)` —— 单模板 Admin 改/停用后调用，跨所有配置桶
  - `invalidate_all_intent_cache()` —— `lib_manager.py import` 批量重导后调用（模板可能整体被替换）
  - `invalidate_all_llm_caches()` —— Admin LLM 配置 CRUD / set-default 时**全清三个前缀**（`gen:*` / `intent_cache:*` / `gen_llm:*`，v2.23 / FEAT-11 起含 `gen_llm:*`）；不同 LLM 对同一意图可能返不同 `(template_id, params)` 或不同 `llm_direct` 代码，复用旧缓存会让切换形同没切；分桶不是为了切换后保留旧缓存，而是支撑单模板/单意图维度的精准失效

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
批量写入 Qdrant（point_id = uuid.uuid5(NAMESPACE_DNS, template.id)）
  → 派生确定性 UUID 而非 uuid4()，确保后续 rebuild 真正 upsert 旧 point
    （旧实现用 uuid4 会在每次 rebuild 累积同一模板的多个 point，污染检索结果）
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

#### 3.10.1 贡献提交（v3.1 双入口 + 3 分支并存）

v3.1 在 v3.0 LLM 反推路径基础上**进一步把必填字段从 4 件压到 2 件**（`original_intent + code_type`），新增预览端点供前端两步 Modal 使用；原 4 字段路径作为分支 3 完全向后兼容。

**入口点**（v3.1）：(1) 批量生成结果列表低置信度（< 50%）行旁的「贡献新模板」按钮；(2) GeneratePage 第五道闸 `no_matching_template` 直跳贡献页（`redirect_to=/contribute/new?description=...&code_type=...`）；(3) IntentBuilder 5 轮对话仍无候选高置信时自动展示的「贡献新模板」入口（详 §3.11.5）；(4) 顶部导航「我的贡献」页「+ 新贡献」直接入口。所有入口最终都进同一两步 Modal。

**预览端点（FEAT-10 新增，不入库）**：

```
POST /api/v1/contributions/preview
  ↓
ContributionPreviewRequest Schema（Pydantic）
  - 必填：original_intent (str, 1-4096), code_type (str)
  ↓
调 generate_from_intent(original_intent, code_type, llm)：
  LLMClient.chat([{system: "你是 SV 模板生成专家 + 命名规范"},
                  {user: <intent + code_type + contract>}])
  → _extract_json_block：兼容 ```json``` 围栏抓首个 JSON 对象
  → 4 道校验闸（任一失败抛 ContributionParseError → 422 contribution_parse_failed）：
    ① _validate_template_name：匹配 ^(sva|cov)_[a-z][a-z0-9_]*_v\d+$
      失败 → stage="template_name"
    ② _validate_parameter_defs：name/type/required/description/expr_type 齐全；
      name 是合法 SV 标识符；expr_type ∈ {sv_identifier, sv_identifier_list,
      sv_boolean_expr, sv_bins_expr, integer, free_text}
      失败 → stage ∈ {param_defs_shape, param_defs_empty, param_defs_name,
      param_defs_expr_type}
    ③ _validate_jinja_rendering：用占位值跑一次 SandboxedEnvironment +
      StrictUndefined 渲染
      失败 → stage ∈ {jinja_empty, jinja_syntax, jinja_sandbox (SSTI/不安全
      操作), jinja_render (StrictUndefined / 参数引用失败)}
    ④ _validate_keywords：必须是 list[str]，自动去重 / 过滤空串；非 list 即拒
      失败 → stage="keywords_shape"
  返回 ExtractedFull(template_name, description, demo_code, parameter_defs,
                     jinja_body, keywords, subcategory, protocol)
  ↓
check_name_duplicate(extracted.template_name) → name_conflict: bool（非阻塞）
  ↓
返回 ContributionPreviewResponse(template_name, description, demo_code,
                                  parameter_defs, keywords, name_conflict)
```

`demo_code` 回传 LLM 产出的**原始 SystemVerilog 代码**（含真实信号名 / 字面量），不暴露 `jinja_body`——`jinja_body` 在 submit 时由 `derive_parameters_from_demo` 用用户最终编辑过的 `demo_code` 重新生成，保证用户对代码的修改会被传递到模板体。

**提交端点（3 分支并存，按顺序判断）**：

```
POST /api/v1/contributions
  ↓
ContributionCreate Schema（Pydantic）
  - 必填：original_intent (str, 1-4096), code_type
  - 可选：template_name, description, demo_code, parameter_defs（v3.1 全部可选）
  ↓
分支判定：need_llm_generate = not (template_name and demo_code)

【分支 1 — intent-only 生成】（need_llm_generate=true）
  调 generate_from_intent(original_intent, code_type, llm)，跑同样 4 道校验闸
  final_template_name = payload.template_name or generated.template_name
  final_description   = payload.description   or generated.description
  final_user_demo     = payload.demo_code     or generated.demo_code
  derived_param_defs  = generated.parameter_defs
  derived_jinja_body  = generated.jinja_body  ← LLM 同时产出的 Jinja2 体
  derived_keywords    = generated.keywords

【分支 2 — v2 批量兼容】（need_llm_generate=false AND payload.parameter_defs 显式给出）
  derived_param_defs = payload.parameter_defs（caller 已是结构化）
  derived_jinja_body = payload.demo_code（caller 已是 Jinja2 体）
  不调 LLM

【分支 3 — v3.0 demo 反推】（need_llm_generate=false AND payload.parameter_defs 未给）
  调 derive_parameters_from_demo(demo_code, description, code_type)
  跑 3 道校验闸（参数命名 / Jinja2 沙箱 / keywords 形态）
  ↓
_validate_template_name(final_template_name)
  分支 1 内 generate_from_intent 已校验，但分支 2/3 + 分支 1 中 payload.template_name 覆盖路径需补校验
  失败 → 422 contribution_parse_failed(stage="template_name")
  ↓
check_name_duplicate(final_template_name) 命中 → 422 contribution_name_duplicate（阻塞）
  ↓
dedup 预扫：check_semantic_duplicate(description, name) dense-only 取 top-3
  命中即写入 contribution.original_row_json["similar_templates"]；
  失败（Qdrant 暂时不可达等）非阻塞，仅打 WARN
  ↓
写入 template_contributions（status=pending_review）
  - demo_code 字段填 derived_jinja_body（用户编辑过的 SV 代码经过 jinja 化）
  - original_row_json["user_demo"] = final_user_demo（保留原始 SV 代码供审核员对比）
  - original_row_json["similar_templates"] = dedup 预扫结果
  ↓
返回 ContributionOut（含 use_immediately_available: bool = True）
```

整段同步耗时 5-15s（LLM 占主要）。审核员在 AdminContributionsPage 看到**三栏对照**：左栏用户原始 `original_row_json["user_demo"]`（只读）/ 中栏 `demo_code`（已 Jinja2 化，Monaco 可改）/ 右栏 `parameter_defs + keywords + subcategory + protocol`（表单可改）+ 顶部横栏展示 dedup 预扫的 top-3 相似模板（≥ 0.90 黄色警告）；任意修改后批准走 §3.10.2 入库流水线。

**双层审核机制**：

- **第一层（用户验证 LLM 输出）**：前端两步 Modal 的 Step 2 就是用户对 LLM 生成质量的把关——预览返回的 `template_name / description / demo_code` 三字段全部可在 Step 2 编辑后再提交；这是把"参数化脏活推给 LLM"后必须建立的反馈环
- **第二层（管理员审批入库）**：与 §3.7.5 三栏审核完全一致，审核员独立判定质量并对中右栏改写后批准

**「立即使用」路径（FEAT-10）**：Step 2 内点「立即使用」按钮 → 与「提交审核」走完全相同的 `POST /api/v1/contributions`（贡献仍以 `pending_review` 入审核队列），区别在前端**不关闭 Modal**，而是在 Step 2 页面内展示可复制代码框（`<pre>` monospace 块 + 「复制代码」按钮 + 提示文案"代码已就绪，可直接复制使用。模板已提交审核，审核通过后将加入模板库。"），用户可一键复制 LLM 生成的 SV 代码直接粘进设计。

**不跳转 `/generate`**——刚提交的贡献处于 `pending_review` 不在 Qdrant 中，若跳过去走 pipeline 仍会触发第五道闸 `no_matching_template` 进入死循环；在 Step 2 内展示代码框是 FEAT-10 spec §5（"立即使用"方案 A）确定的方案，最简单且无副作用。

重提流程：被请求修改的贡献，普通用户在两步 Modal 中改 `original_intent + code_type` 重新走预览/编辑流程，重提会**重新跑一次 LLM 生成 + 4 闸 + dedup 预扫**——审核员对中右栏的旧手改在重提后丢弃，避免新旧产物错配。

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
├── api/v1/
│   └── contributions.py         # 贡献者端点（提交/查看/修改）及管理员审核端点（合并单文件）
└── services/platform/
    ├── contribution_service.py  # 贡献入库流水线（调用 create_template()）
    ├── parameter_extractor.py   # v3.0 LLM 反推 parameter_defs + Jinja2 template_body（调 LLMClient.chat）
    └── corpus_service.py        # FEAT-4 三层模板选择质量保障（语料生成 / 冲突检测 / LLM 根因分析）
```

> **注**：贡献者端点与管理员审核端点合并在同一 `contributions.py` 文件中，通过 `require_role` 依赖注入区分权限。所有表结构均在 `migrations/versions/001_initial_schema.py` 初始迁移中统一建立。

### 3.11 验证意图标准化服务 + IntentBuilder 多轮对话（v3.0）

#### 3.11.0 v3.0 角色重定位

`normalize_intent`（原"四层标准化机制"核心）在 v3.0 **角色降级为"弃权信号载体 + cache key 稳定器"**：sentinel "无法判断类型，输出原文"保留，但**下游不再用它做兜底**——sentinel 之后参数仍是低置信源时，§3.15.3 的 `under_specified` 闸照常拦。同义改写仍跑（保 `intent_hash` 稳定让 `intent_cache:*` 命中率不退化），但**不再承担"我替你猜你想说什么"的职责**。

"猜用户意图"的职责改由新增的 **IntentBuilder 多轮对话（§3.11.5）** 承担：用户被 `under_specified_required_param` 拦下后通过 `redirect_to` 跳到 `/intent-builder`，与 LLM 多轮交互逐步明确意图，最后再回 Generate 页提交（`PipelineInput.source="intent_builder"`）。

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

**v3.0 缩水**：预检仅展示低置信行的"最近似模板"参考，**不再**引导用户逐行修改原表。批量场景下真正的"低质量行"由 v3.0 的 `under_specified` 闸在逐行 `run_pipeline` 时 422，前端把这些行标红展示，用户可选择"逐行跳转 IntentBuilder 改进"或"整批跳过"。预检与 under_specified 闸定位互补：前者是上传后**快速概览**（无 LLM、5-10s），后者是逐行生成时**强校验**（带 LLM、含 detail.missing_params）。

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

#### 3.11.5 IntentBuilder 多轮对话端点（v3.0，替换原场景构建器）

v3.0 用 RAG-grounded 多轮 LLM 对话取代原"场景模板填空"——后者要求用户预知场景类型，对模板库已覆盖但用户语言风格不同的场景无能为力。多轮对话每轮跑一次 RAG 把库内 top-3 模板 `description` 喂回 prompt 引导用户往已存在模板靠拢；N 轮后所有候选都明显不匹配 → 引导用户跳转到 §3.10 贡献新模板。

```
POST /api/v1/intent-builder/chat
     请求：{ "session_id": "<uuid4>" or "",   # 空 → 后端 mint 新 session_id
             "user_message": "<用户本轮输入>",
             "code_type": "assertion" | "coverage" }
     响应：{ "session_id": "<始终回填>",
             "assistant_message": "<LLM 回复>",
             "rag_candidates": [{template_id, name, description, score}, ...top-3],
             "should_contribute": bool }  # 多轮后仍无 close match → true 提示用户贡献新模板

GET  /api/v1/intent-builder/scenarios   # v2 残留，v3.0 退役 → HTTP 410 Gone
POST /api/v1/intent-builder/build       # v2 残留，v3.0 退役 → HTTP 410 Gone
```

**Session 存储**（`services/intent/session.py`）：
- Key: `intent_builder_session:{user_id}:{session_id}`，按用户隔离，未登录用户禁用
- TTL: 24h（多轮对话本质 ephemeral）；每轮写都刷新 TTL；用户点"关闭对话"可手动 delete，常规依赖 TTL 兜底
- Value: 完整 message 列表 + `code_type` + `last_rag_candidates`

**对话编排**（`services/intent/conversation.py::run_one_turn`）：每轮先用本轮 user_message 跑一次 RAG → 把 top-3 模板 `{name, description, parameters[name+description]}` 注入 system prompt → 调 `LLMClient.chat(messages)` → 返回 assistant 回复 + 同一批 RAG 结果。LLM 沿用 `llm_configs.is_default`（不分独立配置）。

**强制 RAG-priority 约束**：system prompt 写死"你只能从下面给出的候选里选一个引导对齐，不允许凭空想象新场景；如候选都不像，明确告诉用户'我们的库里似乎没有匹配的'并问是否贡献"。目的：避免 LLM 引导用户产出"看起来标准但库里没模板能渲染"的句子，导致用户走出 IntentBuilder 又被 RAG empty / under_specified 打回来。

**LLM 输出契约**：assistant 回复末尾固定段 `<<intent>>...<<end>>` 包裹当前累积的标准化意图，前端解析这段做"用这条意图回去生成"按钮的 prefill；正文部分自由组织的人话引导（"请告诉我 valid/ready 信号名"等）。

**5 轮上限 + `suggest_contribute` 信号**：session 中每轮存 top-1 RAG score。响应 `IntentBuilderChatResponse.suggest_contribute=True` 触发条件——本轮 + 历史所有轮的 top-1 RAG score 都 < 0.5（共积累 5 轮仍无候选）。前端见 `suggest_contribute=True` 展示"我们的库似乎不覆盖这个场景"提示 + §3.10 贡献入口（prefill 已积累的 description）。

场景构建器（v2 的 §3.11.5 内容）**已退役**——`/scenarios` `/build` 端点改返 HTTP 410 Gone + 提示语指向 `/chat`；`services/intent/builder.py` 保留代码但不再被路由层引用。

#### 3.11.6 文件位置（服务层重组后）

```
backend/app/
├── services/
│   ├── intent/                  # 意图相关服务聚合子包（新结构）
│   │   ├── normalizer.py        # LLM 标准化服务（v3.0 角色降级为弃权信号载体 + cache key 稳定器）
│   │   ├── builder.py           # v2 场景构建器（v3.0 退役保留，端点改 410 Gone）
│   │   ├── preflight.py         # 上传预检服务（第3层）
│   │   ├── history.py           # 历史意图库读写（v3.0 含 template_params_fingerprint helper）
│   │   ├── conversation.py      # v3.0 多轮对话编排（run_one_turn：每轮跑 RAG + LLMClient.chat）
│   │   └── session.py           # v3.0 Redis-backed session（key=intent_builder_session:{uid}:{sid}, TTL 24h）
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
│   ├── normalize_intent(original_intent, rules) → str
│   ├── select_template(normalized_intent, signal_context, candidates,
│   │                   original_intent="") → TemplateSelectionOutput
│   ├── chat(messages, max_tokens=1024, temperature=None) → str    # v3.0 通用多轮接口
│   │   供 IntentBuilder 与贡献机制 LLM 反推共用；messages 与 OpenAI/Anthropic SDK
│   │   原生格式一致（role: system/user/assistant），默认不打 thinking 开关
│   ├── generate_code_freeform(intent, code_type, signals, clk, rst)
│   │   → str  # v2.23 / FEAT-11 Stage 2：llm_direct 兜底自由生成 SystemVerilog
│   │   prompt 强制单 ```systemverilog/sv/verilog``` 围栏；prose-only 响应抛
│   │   ValueError("no_sv_code_block") 让端点翻译为 HTTP 422 llm_direct_no_code
│   └── test_basic() → str                   # 连通性自检
├── anthropic_client.py       # Anthropic 原生 SDK 实现（tool_calling 单步返回）
├── openai_compat_client.py   # openai SDK + base_url 实现（两步纯文本，见下）
└── factory.py                # 读 llm_configs 表，按 is_default 实例化
```

**OpenAI 兼容路径——两步调用模式**：

为兼容 GLM-4.7、DeepSeek-R1 等 thinking 类模型（reasoning_tokens 实测 ~650/次），`select_template` 内部拆为两次纯文本调用，避免单次 prompt 输出过长触发 `finish_reason='length'`。每次调用的 thinking 开关与 `max_tokens` 按用途独立调档：

| 调用 | `extra_body` | `max_tokens` | 说明 |
|------|--------------|--------------|------|
| `normalize_intent` | `{"thinking":{"type":"disabled"}}`（硬编码） | 512 | 句式改写，无需 chain-of-thought |
| `_step1_select_id` | `{"thinking":{"type":"disabled"}}`（硬编码） | 64 | 仅返回候选列表中的 template_id 或字符串 `"none"`；系统提示含负向选择准则（FIX-8）——核心验证语义不匹配时禁止信号名重映射强行适配，必须返 `"none"` 让 pipeline 走 rag_fallback → 第五道闸（详见 §3.15.3 Step 5a） |
| `_step2_fill_params` | 由 `llm_configs.step2_disable_thinking` 运行时切换 | 2048（off）/ 1024（on） | 仅针对所选模板的 required 参数生成 JSON；prompt 注入示例输出，正则提取响应中第一个 JSON 对象（兼容 ` ```json``` ` 围栏） |
| `generate_code_freeform`（v2.23 / FEAT-11） | `{"thinking":{"type":"disabled"}}`（硬编码） | 2048 | `llm_direct` 兜底完整代码生成；prompt 注入 `intent + code_type + signals + clk + rst` 并强制单 ` ```systemverilog/sv/verilog``` ` 围栏，正则提取首块。**理由**：自由生成已经够大不再额外开 thinking，且与 normalize / step1 一致禁 thinking 保稳定延迟；输出 token 较多（一段完整 SVA / coverage 代码），`max_tokens=2048` 与 step2 off-thinking 同档 |
| `test_basic` | `{"thinking":{"type":"disabled"}}`（硬编码） | 64 | 连通性自检 |

`_step2_fill_params` 的两档配置：

- **`step2_disable_thinking=true`（默认）**：禁 thinking，`max_tokens=2048`。实测 GLM-4.7 单次 ~3s 稳定，无 `finish=length`。适合生产路径。
- **`step2_disable_thinking=false`**：保留 thinking，`max_tokens=1024`（reasoning ≤ 600 + JSON ~150）。实测方差 12-249s，偶发 `finish=length` 返空。仅在需要复杂推理填参数（FSM `state_list` / `bins_expr` 等边界场景）时由超管在 Admin UI 临时切换以做能力对照。

`extra_body={"thinking":{"type":"disabled"}}` 是 Zhipu OpenAI-compatible 原生参数（`openai` SDK 透传），非 thinking 模型会静默忽略，无副作用。每次调用打点 `[Timing] llm=<name> ms=<n> reasoning_tokens=<n> thinking=<on/off>`，`reasoning_tokens=0` 确认 `extra_body` 真正生效。

返回 `TemplateSelectionOutput(template_id, param_mapping, confidence)`，其中 `param_mapping` schema 类型为 `dict`（不限定 value 类型，因 LLM 可能返回 `signal_width: 3` 等数字）。

**factory.py 逻辑**：

```
读取 PostgreSQL llm_configs WHERE is_default=true AND is_active=true
  provider == "anthropic"        → AnthropicClient(config)
  provider == "openai_compatible" → OpenAICompatClient(config)
  无记录                          → 抛出 RuntimeError，提示管理员配置模型
```

#### 3.12.3 结构化输出降级策略

模板选择需要严格的字段化输出。当前实现按 provider 区分两条路径：

| 路径 | 适用模型 | 实现方式 |
|------|---------|---------|
| Anthropic 原生 | Claude | `tools` 参数强制单次结构化输出，结果直接绑定到 `TemplateSelectionOutput` |
| OpenAI 兼容（两步纯文本） | GLM-4.7、DeepSeek、Qwen、Ollama 等 | Step1 仅输出 template_id，Step2 仅输出 params JSON；后端用正则提取第一个 JSON 对象（含 ` ```json``` ` 围栏兼容）+ Pydantic 验证 |

> `llm_configs.output_mode` 字段（`tool_calling` / `json_mode` / `prompt_json`）作为预留扩展字段保留在表结构中，OpenAI-compat 路径当前**固定使用两步纯文本**，原因是兼容 thinking 模型时 tool_calling 路径会因 reasoning_tokens 占用 max_tokens 导致空输出。Anthropic 路径仍走 tool_calling。

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
③ invalidate_all_llm_caches() —— scan-delete `intent_cache:*` + `gen:*`（覆盖所有配置桶）
④ 写入 admin 操作日志
```

新旧模型对同一输入可能选择不同模板/参数，全清两个前缀确保切换后行为一致。§3.6 的 `llm_config_id` 分桶不是为了"切换后保留旧缓存"——既然要切换语义，旧条目必须失效——而是为了支持 `invalidate_template_cache(tid)` 用 `gen:*:{tid}:*` 跨所有配置桶精准失效单模板（Admin 改/停用模板时只动该模板对应键，不动其他模板的缓存）。

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
GET /api/v1/generate/code-types
  响应：[
    { "id": "assertion", "display_name": "SVA断言" },
    { "id": "coverage",  "display_name": "UVM功能覆盖率" }
  ]
```

前端通过此端点动态获取类型列表，单条生成页面的"代码类型"下拉均由后端驱动，新增代码类型时前端**无需任何改动**。该端点挂载在 `/generate` 路由组下（`router = APIRouter(prefix="/generate")`）。

---

### 3.15 生成流水线编排器（Generation Pipeline）

#### 3.15.1 设计动机

当前生成流程（7-8 步）的调用链路分散在端点层、多个 service 文件之间，没有明确的入口点和步骤边界。这导致：整体流程难以追踪、单步难以独立测试、插入新步骤需要修改多处代码。

引入 `services/core/pipeline.py` 作为唯一编排者，端点层只调用 `pipeline.run()`。

#### 3.15.2 统一请求/响应接口

```python
@dataclass
class PipelineInput:
    original_intent: str   # 用户填写的验证意图原文
    code_type: str         # "assertion" | "coverage" | ...（registry 中注册的 id）
    protocol: str | None   # 可选协议过滤
    clk: str               # 时钟信号（默认 "clk"）
    rst: str               # 复位信号（默认 "rst_n"）
    rst_polarity: str      # 复位极性（默认 "低有效"）
    signals: list[dict]    # [{name, width, role}, ...]
    source: str = "direct" # "intent_builder" | "direct"；v3.0 仅供日志/统计区分入口，不影响路由

@dataclass
class PipelineResult:
    """legacy 一步式返回（run_pipeline / batch_tasks 用）。"""
    status: str            # "success"
    code: str
    template_id: str
    template_name: str
    version: str
    confidence: float
    normalized_intent: str
    intent_hash: str
    rag_candidates: list[dict]
    params_used: dict
    cache_hit: bool
    intent_cache_hit: bool

@dataclass
class PreviewResult:
    """两步式第一步：仅返回模板候选 + 参数预填，不渲染、不写代码缓存。"""
    template_id: str
    template_name: str
    template_version: str
    confidence: float
    confidence_source: str         # "llm_step1" | "rag_fallback" | "intent_cache"
    rag_candidates: list[dict]     # 含每候选的 parameters 供前端切换
    params: dict[str, dict]        # {name: {value, source, required, description, type,
                                   #          sanitized?, expr_type?, validation_error?}}
    intent_hash: str
    normalized_intent: str
    quick_render: bool = False     # intent_cache 命中 → True，前端跳确认面板

@dataclass
class RenderInput:
    """两步式第二步：用户在确认面板编辑后回传的最终参数。"""
    template_id: str
    template_version: str
    params: dict                   # value-only dict
    intent_hash: str | None = None # 透传以关联意图历史
    confidence: float = 0.0
    normalized_intent: str = ""
```

**入口对照**：

| 入口 | 调用方 | 行为 |
|---|---|---|
| `pipeline_preview(PipelineInput, db) → PreviewResult` | `/api/v1/generate/preview` | 跑 Step 1–6（含参数 5 源标注）；不渲染、不写缓存 |
| `pipeline_render(RenderInput, db) → (code, cache_hit)` | `/api/v1/generate/render` | 跑 Step 7–8；写代码缓存与意图历史（`intent_hash` 非空时） |
| `run_pipeline(PipelineInput, db) → PipelineResult` | `/api/v1/generate`（legacy）+ Celery batch | 内部串行调上面两步，对调用方零变更 |

#### 3.15.3 流水线步骤（含兜底链）

```
run_pipeline(inp: PipelineInput, db: AsyncSession) → PipelineResult

Step 1: IntentNormalize
  调用 normalize_intent(inp.original_intent, db)
  输出：normalized_intent + intent_hash（SHA256，temperature=0，确定性）

Step 2: IntentCacheLookup
  lookup_history(intent_hash, llm_config_id) → 若命中，取历史 template_id + params + params_fingerprint
  schema-drift 守门：current_fp = template_params_fingerprint(tmpl.parameters)
    cached_fp != current_fp → bypass 缓存（模板 schema 已改，旧 mapping 不再合法）→ 进入 Step 3
    cached_fp == current_fp → 再尝试 get_generation_cache(tmpl_id, version, params, llm_config_id)
      双重命中 → 直接返回（intent_cache_hit=True, cache_hit=True），流水线结束
  未命中 → 进入 Step 3

Step 0a (preview 前置)：off-topic dense 闸（详见 §1.1）
  dense_top1_score(original_intent, code_type) < OFFTOPIC_DENSE_THRESHOLD
    → 抛 OffTopicIntentError → 端点映射 HTTP 422（redirect_to=None）
  注（v2.25 / FEAT-13）：dense_top1_score 内部 Qdrant 查询 Filter 已带上
    maturity_level='production'，top-1 只在 production 子集计算；过滤后子集
    与全量分布若有显著差异，OFFTOPIC_DENSE_THRESHOLD 可能需重新校准
    （`backend/scripts/calibrate_offtopic_threshold.py`）。

Step 0b (preview 前置, off-topic 通过后)：code_type_mismatch 闸
  当 OFFTOPIC_GATE_ENABLED && CODE_TYPE_MISMATCH_GATE_ENABLED 时启用。
  _detect_code_type_mismatch(original_intent, current_code_type, current_score,
                              margin=CODE_TYPE_MISMATCH_MARGIN)：
    对所有 registry 注册的 code_type 逐一算 dense top-1（同样仅在 production
    模板上计算，v2.25 / FEAT-13），若某非当前 code_type 的得分 - 当前得分
    ≥ margin（默认 0.10）→ 抛 CodeTypeMismatchError → 端点映射 HTTP 422
    （redirect_to=None，前端在原页面 Modal 引导切换 code_type）
  无显著更优 code_type → 进入 Step 3

Step 3+4: Embed + RAGRetrieve
  rag_retrieve(normalized_intent, db, code_type)
  Stage1 Qdrant 混合检索（dense+sparse RRF，code_type 过滤 + maturity_level='production' 过滤，v2.25 / FEAT-13）
  Stage2 ColBERT MaxSim 精排（注：当前实际 bypass——main.py:_init_qdrant_collection 只 provisions
    dense+sparse 命名向量，stage1 读 r.vector.get("colbert") 永远为 None，stage2 见 None 透传 RRF 分数；
    v2.25 / FEAT-13 起 stage1 已保证输入仅含 production 模板，stage2 无需独立 maturity Filter）
  Stage3 bge-reranker 精排
  engine.py DB 二次过滤：select Template where id in template_ids and is_active==True
    AND Template.maturity_level=='production'（v2.25 / FEAT-13，双重防御）
  对返回结果按 template_id 去重（Qdrant 可能返回同一模板的多个 point）
  进入 Step 4b（关键词补充召回）

Step 4b: KeywordSupplement（向量召回兜底）
  从 PostgreSQL 查询同 code_type 的 active 模板
  按 template.keywords 与 (normalized_intent + original_intent) 做小写子串匹配
  对每个模板计算命中关键词数作为分数，取 top-2 加入 rag_candidates 头部
  动机：bge-m3 对中文 IC 验证术语区分度有限，关键词命中作为 RAG 召回的兜底

  rag_candidates 仍为空（向量+关键词双兜底后） → 抛 EmptyRetrievalError → 端点映射 HTTP 503
    这是基础设施层问题（Qdrant 不可达 / collection 空 / embedding service 挂），不是用户问题；
    与 off-topic 422 分流，让 SRE 排查而不是让用户改提问。该异常继承 RuntimeError 而非
    ValueError，避免端点旧的 except ValueError 把它泛化兜底成 422。

Step 5a: TemplateSelect（LLM Step1）
  llm.select_template(normalized, signal_context, candidates, original_intent)
  → 内部依次调用 _step1_select_id（选模板 ID）+ _step2_fill_params（填参数）
  返回 TemplateSelectionOutput(template_id, param_mapping, confidence)
  若 template_id 为空 / "none" / 不在候选 → 退化为 rag_candidates[0]
    （此时 confidence 重写为该候选的 RAG 分数，confidence_source = "rag_fallback"）

  【候选渲染（v2.21，A4）】_step1_select_id 的 candidates_text 由单行串接改为
  Markdown 多行块（`### {i}. {template_id}  {name}\n描述：...`），description 截断
  60 → 1000 char（lib_manager.py import 时已把 differentiators / non_use_cases 拼到
  description 末尾形成"区别要点："/"不适用场景："两段，合成总长实测最长 812 char，
  截断设到 1000 留余量避免 non_use_cases 末项被切；review NEW-1 后由 spec 中的 300
  改为当前值）。`max_tokens=64` **保持不变**（输出仅 ~10 token 的 template_id，仅
  input 侧扩容；GLM-4.7 实测 step1 延迟增幅 < 1s）。系统提示新增提示语
  "候选描述末尾可能附『区别要点』/『不适用场景』段，请优先用于区分判断"。
  此项仅影响 openai_compat_client；anthropic_client 的 select_template 候选渲染保持不变。

  【负向选择准则（FIX-8）】_step1_select_id 与 anthropic_client.select_template 的系统提示
  显式约束：当候选模板的**核心验证语义**与用户意图不匹配（例如意图是"两信号互斥 /
  one-hot / 竞争检测"，但候选均为握手 / 稳定性 / 延迟 / FSM / 值域），
  禁止通过将用户信号名重命名为模板参数名（如 cpu_req/dma_req → valid/ready）
  来强行匹配；此类场景必须返回字符串 "none"（Anthropic 路径在 tool_choice 强制调用下
  于 template_id 字段填 "none"），交由本层 rag_fallback 路径继续走第五道闸
  （pipeline.py NoMatchingTemplateError，post-Step 5a 闸：LLM step1 返回 none
  即触发，score 值记入日志供监控 → HTTP 422
  no_matching_template + detail.redirect_to=/contribute/new?...）。
  即：模板覆盖空白由"贡献页"修复，不由 LLM 在 step1 强行掩盖。

  【A8 step1 二次验证（v2.21）】当 confidence_source == "llm_step1" 且
  settings.step1_verify_enabled == True 时，pipeline 调用
  llm.verify_step1_selection(normalized_intent, selected_template_id, candidates)
  发一条 yes/no 问询确认核心验证语义是否一致。LLM 答 "no" → 把 confidence_source
  降级为 "rag_fallback" 并把 template 置空，让后续 fallback 链按 rag_fallback 走
  RAG top-1，可被第五道闸 NoMatchingTemplateError 接管。fail-open 原则：LLM 调用
  失败 / 解析失败 / first-token 非 "no" 一律视为通过——避免新加这条验证反成误拒来源。
  STEP1_VERIFY_ENABLED **默认 False**：开启前需用 confusion corpus 的 real-llm 套件
  评估 false-negative 率。keyword_supplement 路径不验（已经是补救路径，不再加压）。
  LLM 调用参数：max_tokens=16 / temperature=0 / thinking=disabled。

  【A9 reranker score gate（v2.21，pipeline 层独立 gate）】A8 验证通过后再查
  selection.template_id 在 rag_candidates 中的 score 字段（即 stage3 reranker score，
  由 services/rag/engine.py enriched 写入）：若 selected_score < settings.
  reranker_min_score_threshold（默认 0.30 经验占位值）且 settings.
  step1_reranker_gate_enabled == True → 抛 NoMatchingTemplateError(top_score=
  selected_score)，直跳贡献页。STEP1_RERANKER_GATE_ENABLED **默认 False**：开启前需
  跑 scripts/calibrate_reranker_threshold.py 在 selection + confusion corpus 上标定
  correct_p10 / wrong_p50 中点写入 reranker_min_score_threshold；未标定就上生产会
  误拒 marginal 真请求。

  【A9 与 FIX-9 移除的 no_match_score_threshold 的语义区分】FIX-9 拦的是 RAG **top-1**
  score（"top-1 分数低就整体否决 LLM 决策"），cross-encoder 词汇重叠会让无关握手模板
  拿 1.0 分把 LLM 正确的 none 判断否决，已经移除；A9 拦的是"LLM **选中** 的那个
  template_id"的 reranker score，是 LLM 决策 + reranker 复核的双信号互证，触发条件
  更稀少且方向更精确。no_match_score_threshold 字段保留供日志/监控，**不参与**触发判定。

Step 5b: GenerationCacheLookup
  从意图正则提取 + LLM param_mapping 合并后查 get_generation_cache
  命中 → 直接返回（cache_hit=True），流水线结束

Step 6: ParamMap（多源合并）
  ① _extract_params_from_intent(original_intent)：正则提取 signal/group_name/
     signal_width/state_list/bins_expr 等字段（CJK 字符兼容）
  ② merged = {**extracted, **selection.param_mapping}（LLM 优先覆盖正则）
  ③ _map_params(template, inp, merged)：
       - 角色规则引擎按 role_hint 从 inp.signals 映射
       - clk/rst/rst_polarity 直接填充
       - 已知字段语义兜底（signal、group_name、state_list、bins_expr）
       - required 参数仍缺失 → 用参数名本身占位，保证 Jinja2 不崩

Step 7: Render
  render_template(template_body, params)（Jinja2 StrictUndefined）
  输出：code（确定性字符串）

Step 8: CacheWrite
  set_generation_cache(template_id, version, params, code)（Redis TTL 90天）
  save_history(intent_hash, template_id, params, confidence, code)（历史意图库）
```

**Recovery 链总览（v2.13 反转后）**：RAG 召回失败 → 关键词补充召回 → LLM 选不出 → 取 RAG 第一候选 → LLM 填不出参数 → 取意图正则提取 → 仍缺失 → 用模板 default → 仍缺失 → 系统经验式 semantic_fallback（仅给可观察值供闸判定，不再当作"完成"）。

**契约反转关键点**：步骤 6 末尾的 `placeholder`（参数名字面量）和步骤 5 的 `semantic_fallback`（"IDLE, ACTIVE, DONE"等系统瞎猜值）**不再视为合法终态**。`pipeline_preview` 在 `_map_params_with_source` 返回后调用 `_detect_under_specified`，任一 required 参数源落在 `{placeholder, semantic_fallback}` 或 LLM 返 trivial 值（空串/0/字面参数名）→ 抛 `UnderSpecifiedIntentError` → HTTP 422 `under_specified`，detail 含：
- `missing_params: [{name, description, expr_type, role_hint}, ...]` —— 每个缺失参数的语义信息，供前端组织提示语
- `redirect_to: "/intent-builder?prefill=<urlencoded original_intent>&missing=<csv param names>"` —— 前端 `handleApiError` 读到 `redirect_to` 直接 `router.push` 跳 IntentBuilder 精修，不在 Generate 页弹 dead-end Modal

**LLM 不允许编参数兜底**——这是 v2.13 契约相对 v2.12 之前最大的策略转向，目的是让用户看到"系统不知道你要什么"而不是"系统给了一堆生造的默认"。

**错误响应 `redirect_to` 约定**（v3.0，§5.1 端点错误响应规范）：仅 `under_specified` 带 `redirect_to` 指向 IntentBuilder；`off_topic`（IntentBuilder 救不了真离题）、`empty_retrieval`（基础设施问题）、`code_type_mismatch`（前端原页面 Modal 切换类型即可）均返 `redirect_to=None`。

**置信度记录**：合并 LLM/RAG 结果时按来源分别记录真实分数 (`confidence_source ∈ {llm_step1, rag_fallback, keyword_supplement, intent_cache}`)。

**Env 关闸**：`UNDER_SPECIFIED_GATE_ENABLED=false` 临时退回到 v2.12 之前的"始终产出"行为，仅用于线上误拦应急。

**Step 8a：高置信 RAG 自动 quick_render（v2.23 / FEAT-11 A 子项）**：

`pipeline_preview` 在 `_detect_under_specified` 通过后、构造 `PreviewResult` 之前，调用 `_is_high_confidence_rag(confidence_source: str, verify_ok: bool | None, selected_score: float | None, params_with_source: dict[str, dict], settings) -> bool` 判定是否四条件齐绿：

1. `result.confidence_source == "llm_step1"`（LLM 主动选中模板，未走 `rag_fallback`/`keyword_supplement`/`intent_cache`）
2. `settings.step1_verify_enabled == True` AND `verify_ok == True`（A8 二次验证通过；A8 disabled 时 `verify_ok=None` 视为不达标，保守不自动 render）
3. `selected_score >= settings.reranker_min_score_threshold`（默认 0.30；`selected_score` 已在 Step 5a A9 gate 阶段无条件计算并向下游透传，与 A9 共用同一份值）
4. `all(p["source"] in {"llm", "regex", "signal_list", "default"} for p in params_with_source.values())`（不含 `semantic_fallback` / `placeholder`，与 under_specified 闸的低置信源集合互补）

四条件齐绿 → `PreviewResult.quick_render=True`，与 intent_cache 命中走的 `quick_render=True` 用同一面板旗标，前端 `GeneratePage.handlePreviewSuccess` 透明承接（已有逻辑：`if (res.quick_render) → callRender()`）。任一条件不达标即保留默认 `quick_render=False`（ConfirmationPanel 流程，无回归）。日志格式：`[Pipeline] high_confidence_rag: tid=<id> score=<x.xxxx> → quick_render=True`。本判定不引入新 env 关闸——直接受 `STEP1_VERIFY_ENABLED` 与 `STEP1_RERANKER_GATE_ENABLED` 控制（两者关闭时条件 2/3 自然不成立，行为退回 ConfirmationPanel）。

#### 3.15.4 端点层变薄

端点层仅负责：HTTP 请求解析 → 构造 `PipelineInput` / `RenderInput` → 调用 `pipeline_preview` / `pipeline_render`（或 legacy `run_pipeline`）→ HTTP 响应序列化，不含任何业务逻辑。批量任务（Celery）每行处理仍走 `run_pipeline`，与单条生成共享完全相同的代码路径。

#### 3.15.5 expr_type 驱动的校验与规范化层

`_map_params_with_source` 末尾追加一道独立 pass，对前面 6 类源（llm / regex / signal_list / default / semantic_fallback / placeholder）产出的参数值统一做语法兜底，确保任何来源的"脏值"都不会污染 Jinja2 渲染。注意 sanitize 是为 Jinja2 渲染做的最后清洗，**不**改变源标签——例如 group_name 经 `construct_group_name` 改写后仍保留 `semantic_fallback` 标签，以便 under_specified 闸正确拒绝。

**模板侧契约**：YAML 的每个 `parameters[]` 元素声明 `expr_type`：

| expr_type | 语义 | Pass 行为 |
|---|---|---|
| `sv_identifier` | 单个 SV 标识符（信号名 / 模块名 / 状态枚举值等） | 过 `sanitize_sv_identifier`：剥离非法字符、首字符必须是字母或下划线、空值回退为 `<参数名>_default`；修改后置 `meta["sanitized"] = true` |
| `sv_identifier_list` | 逗号分隔的标识符列表（如 `IDLE, FETCH, DECODE`） | 逐项 sanitize 后重组；任一项被改动则置 `sanitized = true` |
| `sv_boolean_expr` | SV 布尔表达式（如 `awvalid && ready`） | 过 `validate_sv_boolean_expr`：检查字符集、括号配对、不出现重复算子；不修改值，仅在失败时置 `meta["validation_error"]` |
| `sv_bins_expr` | covergroup bins 表达式（如 `{0:255}`、`{[10:100], 200}`） | 过 `validate_sv_bins_expr`：花括号配对、范围语法、整数字面量；不修改值，仅在失败时置 `validation_error` |
| `integer` / `free_text` / 未声明 / 未知 | 按 Pydantic / 前端 / 模板默认行为 | 跳过 |

**后向兼容**：旧模板未声明 `expr_type` 时，pass 按参数名落入 `IDENTIFIER_PARAMS` 白名单（`enable / data / valid / ready / signal / state_sig / target / start_event / end_event / module_name / group_name / clk / rst / rst_n / from_state / to_state`），按 `sv_identifier` 处理；不在白名单的参数跳过校验，行为与历史一致。`lib_manager.py import` 在导入时对每个未声明 `expr_type` 的参数输出 `WARN` 行，引导团队补齐元数据。

**模块拆分**：

```
backend/app/services/core/
├── identifier.py        # sanitize_sv_identifier / construct_group_name / IDENTIFIER_PARAMS
└── expr_validator.py    # validate_sv_boolean_expr / validate_sv_identifier_list /
                         # validate_sv_bins_expr / EXPR_TYPE_DISPATCH 路由表
```

`_map_params_with_source` 内部从 `EXPR_TYPE_DISPATCH[expr_type]` 取出对应 validator；新增 expr_type 时只需在 dispatch 表加一行，pipeline 主流程零变更。

**前端镜像**：`frontend/src/utils/exprValidators.ts` 实现同名函数，用于 ConfirmationPanel 在用户编辑参数时即时反馈，避免空跑后端 `/render`。后端 pass 是确定性最终防线——前端校验仅作 UX 优化。

**与确定性契约的关系**：本 pass 不改变"LLM 不写代码"的根本约束，只把"模板渲染前的输入空间"从"任意字符串"收紧为"模板声明允许的语法形式"。Jinja2 `StrictUndefined` 仍是兜底，但许多 LLM 失误（在标识符位置塞入空格、注释、CJK 字符等）现在会在此 pass 静默修正或被 `validation_error` 拦截，前端 ConfirmationPanel 据此呈现提示徽标（见 §3.16）。

#### 3.16 两步式确认面板（前端方案 3）

`/api/v1/generate/preview` 返回的 `params` 字典每项含 `value` + `source` + 可选的 `sanitized` / `expr_type` / `validation_error`，前端 `ConfirmationPanel` + `ParametersForm` 组件据此呈现：

- **5 色徽标**对应 5 类源：`llm`（蓝） / `regex`（绿） / `signal_list`（青） / `default`（灰） / `placeholder`（红警示）
- **sanitized 标记** → 灰色"已规范化"角标，鼠标悬停展示原始值
- **validation_error** → 红色错误条 + 错误原文（来自 expr_validator）
- **候选模板切换**：`rag_candidates[]` 每项含 `parameters` 子段，用户切换候选时前端直接套用对应模板的参数预填，无需再调后端

**quick_render 短路**（两条来源）：
1. **意图缓存命中**（v2.13 起）：preview 返回 `quick_render=true`，前端跳过确认面板直接调 `/render` 输出代码
2. **高置信 RAG 自动渲染**（v2.23 / FEAT-11 A）：preview 满足四条件齐绿（详 §3.15.3 Step 8a）时同样 `quick_render=true`；前端逻辑透明承接——`handlePreviewSuccess` 不区分来源，只看旗标。两种来源的差异仅在 `confidence_source` 字段（`intent_cache` vs `llm_step1`）与对应的置信徽标颜色

其余情况一律展示确认面板，用户编辑后再调 `/render`。

**LLM 直接生成兜底按钮（v2.23 / FEAT-11 B）**：result 阶段在代码卡片下方展示「对生成结果不满意？尝试 LLM 直接生成」secondary 按钮，**仅在 `state.result.generation_mode === 'rag'` 时显示**——已经是 `llm_direct` 的记录不再展示按钮（前端守门，禁止链式 fallback；后端再次防御于 §3.17）。点击 → 调 `generateApi.llmFallback(recordId)` → spinner → 收到新 record 后替换代码区 + `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>` + 反馈状态归零。详 §3.17。

---

### 3.17 LLM 直接生成兜底路径（FEAT-11 Stage 2）

#### 3.17.1 设计动机

§1.1 确定性契约把"系统总能产出代码"约束到 `rag` 路径——库内有可用模板时按确定性流水线产出 SVA / coverage 代码。但库覆盖度不可能 100%：意图通过五道闸（off-topic / code_type_mismatch / no_matching_template / under_specified / empty_retrieval）后仍可能因 RAG top-1 与意图实际语义偏差而产出"看似合理但用户不满意"的代码。v2.22 之前用户除了"重写意图 + 重新走流水线"没有自助路径，体验断裂。

FEAT-11 Stage 2 引入 `llm_direct` 兜底路径：用户对 `rag` 结果不满意时一键触发 LLM 自由生成。该路径放弃确定性、放弃模板复用、放弃 Jinja2 渲染，**用 LLM 的语义理解能力换更贴合意图的代码**，代价是 (1) 同一输入可能产出不同代码 (2) 不参与模板库知识沉淀 (3) 无法做严格的语法 / 结构 校验。该取舍由用户在 result 阶段显式触发，前端 UI 与后端 record 双重打标提醒。

#### 3.17.2 端点契约

```
POST /api/v1/generate/llm-fallback
Authorization: Bearer <jwt>
Content-Type: application/json
{
  "generation_record_id": "<source RAG record uuid>"
}

→ HTTP 200
{
  "code": "<完整 SystemVerilog 代码>",
  "generation_record_id": "<新建的 llm_direct child record uuid>",
  "generation_mode": "llm_direct",
  "cache_hit": false | true
}
```

**5 类错误响应**（由端点独立返回，不参与五道闸 except 链）：

| HTTP | `detail.type` | 触发条件 |
|---|---|---|
| 404 | —（详 §3.17.2 注 1） | `generation_record_id` 在 DB 中不存在或不属于当前用户；`detail` 是纯字符串 `"源生成记录不存在"`，不带结构化 `type` 字段 |
| 422 | `llm_direct_chained_not_allowed` | 源记录 `generation_mode == 'llm_direct'`——禁止 `llm_direct → llm_direct` 累积漂移 |
| 422 | `llm_direct_no_code` | `LLMClient.generate_code_freeform` 抛 `ValueError("no_sv_code_block")`（LLM 返纯文字无 ` ```systemverilog/sv/verilog``` ` 围栏） |
| 422 | `llm_direct_internal_error` | 非 `no_sv_code_block` 类 `ValueError`（LLM 返回结构异常 / Pydantic 校验失败等）；`detail.message` 是固定文案，**不**回写 `str(e)` / `type(e).__name__`，避免泄漏内部 repr |
| 500 | `llm_direct_internal_error` | `except Exception` 兜底（非 ValueError：DB 写入失败 / 网络超时 / LLM SDK 内部错误等）；与 422 同名 `type`，靠 HTTP 状态区分语义——422 = LLM 输出可解析但内容异常（用户重试可能解决），500 = 平台基础设施失败（用户重试可能仍败，需 SRE 介入） |

#### 3.17.3 端点流程

```
1. db.get(GenerationRecord, generation_record_id) → 不存在 → 404
2. record.generation_mode == 'llm_direct' → 422 chained_not_allowed（前端已守门，本步是 API 直调防线）
3. signature = canonical(record.original_intent + code_type + record.params_used.signals + clk + rst)
4. cached_code = await get_llm_direct_cache(signature, llm_config_id)
   命中 → 跳到 step 6 with cache_hit=True
5. miss → code = await llm.generate_code_freeform(intent, code_type, signals, clk, rst)
   ValueError("no_sv_code_block") → 422 llm_direct_no_code
   其他 ValueError → 422 llm_direct_internal_error（结构化 detail，不泄漏 repr）
   await set_llm_direct_cache(signature, llm_config_id, code, ttl=7d)
6. 新建 GenerationRecord:
     user_id = current_user.id
     original_intent = source.original_intent
     code_type = source.code_type
     template_id = None
     output_code = code
     confidence = None
     cache_hit = cache_hit_from_step4
     intent_cache_hit = False
     generation_mode = 'llm_direct'
     parent_record_id = source.id
     created_at = now()
7. db.commit() → 返 200 {code, generation_record_id=new.id, generation_mode, cache_hit}
```

源 record 的 `clk` / `rst` 通过 `params_used` JSONB 字段反序列化获得（pipeline_render 写入时已固化，缺则回落到 `"clk"` / `"rst_n"` 默认值）。`signals` 不在 `GenerationRecord` 落盘——`generate_code_freeform` 不强依赖结构化信号列表，prompt 会从 intent 文本直接提取，所以端点向 LLM 调用恒传 `signals=[]`（让 `build_freeform_prompt` 走"未提供信号列表"分支）。`code_type` 唯一可信来源是 `source.template_id` → `templates.code_type`；模板缺失（理论上 RAG 路径不应发生）回落 `"assertion"` 并打 WARN 日志。

#### 3.17.4 缓存与 invalidation

- 键结构：`gen_llm:{llm_config_id}:{sha256(canonical(intent + code_type + signals_sorted_by_name + clk + rst))}`
- TTL：7 天（详 §3.6 缓存层；理由：`llm_direct` 路径本身非确定性，缓存只是给"同一用户连续点几次 fallback 按钮"加速，长时间复用会让用户误以为得到了确定性输出）
- canonical：`services/core/cache.py::_canonical_llm_direct_signature` 把 `signals` 列表按 `name` 字段排序后做 JSON dumps（`ensure_ascii=False, separators=(',', ':')`），保证 signal 顺序无关
- invalidation：`invalidate_all_llm_caches()` 在 admin LLM 配置 CRUD / set-default 时 scan-delete `gen_llm:*` 与 `gen:*` / `intent_cache:*` 同步清空（详 §3.12.6）

#### 3.17.5 DB schema 与回链契约

`generation_records` 表（v2.22 起含 `generation_mode` 列）在 migration 007 追加 `parent_record_id` FK：

| 字段 | 类型 | 说明 |
|---|---|---|
| parent_record_id | VARCHAR(36) NULLABLE FK → generation_records.id | `ondelete=SET NULL`；仅 `generation_mode='llm_direct'` 的记录会有非 None 值，`'rag'` 默认 NULL |

`ondelete=SET NULL` 而非 `CASCADE` / `RESTRICT` 的设计：源 RAG 记录被 admin 删除时（如批量清理误测数据）保留 `llm_direct` 子记录与其反馈数据——子记录的 `feedback_rating` / `output_code` 仍是有意义的质量信号，不应级联消失；FK 清空后子记录 `parent_record_id IS NULL` 仅意味着"无法追溯触发源"，不影响 analytics 聚合（`feedback-summary` / `template-issues` 不依赖 FK）。

#### 3.17.6 非确定性标签三处同步契约

| 位置 | 写入 | 读出 |
|---|---|---|
| 后端记录层 | `GenerationRecord.generation_mode='llm_direct'` + `parent_record_id` FK | admin analytics 4 个端点的 `generation_mode` query filter |
| API 响应层 | `POST /generate/llm-fallback` 响应 `generation_mode: "llm_direct"` 字段；`POST /generate/render`（RAG）响应 `generation_mode: "rag"` 字段 | 前端 `state.result.generation_mode` 初始化与切换 |
| 前端 UI 层 | result 阶段代码卡片头部 `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>` | 用户视觉感知；同时按 `generation_mode === 'rag'` 决定是否显示 LLM fallback 按钮 |

三处任何一处缺打标签都是 bug——回归测试 `tests/test_llm_direct_generation.py` 与 `tests/test_pipeline_preview_render.py` 同时守护"`generation_mode` 字段在响应体存在 + 值正确"两条不变量。

#### 3.17.7 服务层实现位置

```
backend/app/api/v1/generate.py                 # POST /generate/llm-fallback 端点 +
                                                 5 道闸 catch 链（独立路径，不与五闸合并）
backend/app/services/llm/base.py               # LLMClient.generate_code_freeform 抽象方法 +
                                                 build_freeform_prompt / extract_sv_code_block helper
backend/app/services/llm/anthropic_client.py   # native messages API 实现
backend/app/services/llm/openai_compat_client.py # chat.completions + 围栏正则提取，
                                                 硬编码 thinking=disabled / max_tokens=2048
backend/app/services/core/cache.py             # get_llm_direct_cache / set_llm_direct_cache /
                                                 _canonical_llm_direct_signature 三函数
backend/app/models/generation_record.py        # parent_record_id Mapped 列声明
backend/migrations/versions/007_llm_direct_parent_fk.py  # ALTER TABLE ADD COLUMN + FK
backend/tests/test_llm_direct_generation.py    # 端点级集成测试（mock LLM/DB/Redis）
backend/tests/test_llm_freeform_client.py      # 围栏 lang 兼容 + prose 拒绝单测（mock LLM 不依赖活基础设施）
frontend/src/api/generate.ts                   # llmFallback API + GenerationMode 类型
frontend/src/pages/Generate/GeneratePage.tsx   # result 阶段 fallback 按钮 + Tag 渲染
```

#### 3.17.8 与 5 道闸的关系

5 道闸（OffTopic / CodeTypeMismatch / UnderSpecified / NoMatchingTemplate / EmptyRetrieval）仅守 `pipeline_preview` 路径（即 RAG 链路）。`POST /generate/llm-fallback` **绕过五闸**：它的输入是已经通过五闸的 `rag` record 的 `original_intent` / `code_type` / `signals` / `clk` / `rst`，意图本身一定是域内（否则源 record 不会存在）。这是 v2.15 引入 off-topic 闸时的隐含前提，本路径继续遵循。

`llm_direct` 路径自身的失败（无围栏 / LLM 调不通 / DB 写不进）由 §3.17.2 的三类 422 错误处理，不复用五闸的 detail.type。

---

### 3.18 用户对比报告路径（FEAT-12）

#### 3.18.1 设计动机

§3.17 引入 `llm_direct` 兜底后，用户能在 `rag` 不满意时一键拿到 LLM 自由生成的代码。但平台缺少一条**结构化采集"哪些 RAG vs LLM 直接生成的差异值得 admin 关注"**的通道：§3.9 L3 差评（`generation_records.feedback_*`）按记录评质量分，颗粒度是单条结果；模板库改进需要的颗粒度是"成对（RAG 源 + LLM 直接生成子记录）"。FEAT-12 新建独立的 `improvement_reports` 表（§4.1.4）+ 用户一键提交按钮 + admin 三态审阅工作流，作为质量信号采集链路的新一环（上游：用户观察成对差异；下游：FEAT-13 把 resolved 报告语料回流到 `template_corpus_cases`，**本票不做**）。

设计原则：
- **不与 §3.9 L3 差评互斥**：FeedbackBar 与「提交对比报告」按钮在 result 阶段并存（互相独立锁定），允许同一对记录同时存在差评 + 对比报告
- **不接入 §1.1 确定性契约**：`improvement_reports` 是纯 DB 写入，不调用 LLM、不读 Qdrant、不影响 `generation_records.output_code`
- **不接入 §3.10 L4 仪表盘**：FEAT-12 不修改 4 个 KPI 端点，`improvement_reports` 数据消费留 FEAT-13

#### 3.18.2 完整链路

```
GeneratePage result 阶段（generation_mode === 'llm_direct' && parent_record_id != null）
  ├─ FeedbackBar（§3.9 L3 差评，独立通道）
  └─ [提交对比报告] 按钮（§3.18 本路径）
       │
       │ mount/聚焦时：GET /api/v1/improvement-reports/check?rag_record_id=&llm_direct_record_id=
       │   ↓ 200 {exists:true, report_id} → 按钮 disabled「已有人提交对比报告，admin 处理中」
       │   ↓ 200 {exists:false} 或 404      → 按钮 enabled
       │
       │ 用户点击 → Modal（Checkbox.Group + TextArea，全选填均允许空）
       │
       ↓ POST /api/v1/improvement-reports
          body: {rag_record_id, llm_direct_record_id, report_categories?, reporter_note?}
       │
       ├─ rag_record_id / llm_direct_record_id 不在 generation_records → 422 invalid_record_ref
       ├─ UNIQUE(rag_record_id, llm_direct_record_id) 冲突 → 409 duplicate_report
       │   detail.existing_report_id = <已存在记录 UUID>
       └─ 成功 → 201 {id, status: 'pending', created_at, ...}
          按钮置灰文案改「已提交」

admin 侧边栏「管理」→「对比报告」（仅 lib_admin / super_admin 可见）
  ├─ /admin/improvement-reports（列表页）
  │   ↓ GET /api/v1/admin/improvement-reports?status=&categories=&page=&page_size=
  │   ↓ 返回分页 + status Tag + 提交用户名 + RAG 模板名 + 分类 Tag 组 + 提交时间
  │
  └─ /admin/improvement-reports/:id（详情页）
      ↓ mount: GET /api/v1/admin/improvement-reports/{id}
      ↓        → 三列对比字段：[RAG record / LLM Direct record / 用户提交]
      ↓ if status === 'pending'
      ↓    自动 PATCH /api/v1/admin/improvement-reports/{id} {status: 'in_review'}
      ↓ admin 填 admin_note + 点「标记已处理」
      ↓    PATCH /api/v1/admin/improvement-reports/{id} {status: 'resolved', admin_note}
      ↓ 非法跳转（pending→resolved 跳过 in_review、resolved→pending 倒退等）
      ↓    → 422 illegal_status_transition
```

#### 3.18.3 端点契约总览

| 方法 | 路径 | 鉴权 | 关键行为 |
|---|---|---|---|
| `POST` | `/api/v1/improvement-reports` | 登录用户+ | 写 `status='pending'`；categories/note 全空合法；FK 缺失 422 `invalid_record_ref`；UNIQUE 冲突 409 `duplicate_report` |
| `GET` | `/api/v1/improvement-reports/check` | 登录用户+（与 POST 同级，不限 admin） | 查询 `(rag_record_id, llm_direct_record_id)` 对是否已有报告；契约 200 `{exists, report_id?}` 单形态（前端只需判 `exists` bool；详 §5.1） |
| `GET` | `/api/v1/admin/improvement-reports` | 库管理员+ | 分页列表，支持 `status` 单选 + `categories` 多选过滤，默认 `created_at DESC`；普通用户 403 |
| `GET` | `/api/v1/admin/improvement-reports/{id}` | 库管理员+ | 详情，返两条 `generation_record` 完整对比字段（`output_code` / `template_id` / `template_name`（join templates 取 name）/ `params_used` / `original_intent` / `generation_mode` / `cache_hit`） + 用户提交字段；普通用户 403 |
| `PATCH` | `/api/v1/admin/improvement-reports/{id}` | 库管理员+ | 更新 `status` 与 `admin_note`；三态状态机校验在端点层做（不依赖 DB CHECK）；非法跳转 422 `illegal_status_transition` |

`check` 端点契约选 **200 `{exists, report_id?}` 单形态**（spec §5 Open Question 中的方案 B）：前端只看 `exists` bool 即可分支按钮 disabled 态，不依赖 HTTP 状态码做控制流（404 会污染浏览器 devtools 红条）。

#### 3.18.4 三态状态机（合法跳转表）

```
pending ──admin 打开详情页（mount 自动 PATCH）──► in_review ──admin 「标记已处理」──► resolved
```

| from / to | pending | in_review | resolved |
|---|---|---|---|
| **pending** | ✗（no-op）| ✓ | **✗（跳过 in_review）→ 422 `illegal_status_transition`** |
| **in_review** | ✗ 倒退 → 422 | ✗（no-op）| ✓ |
| **resolved** | **✗ 倒退 → 422** | **✗ 倒退 → 422** | ✗（no-op）|

`detail.message` 在非法跳转时返"非法状态跳转：{current} → {target}；合法跳转链：pending → in_review → resolved"，前端 `message.error` 透传文案。

**并发**：多 admin 并发进入 `in_review` 不做认领锁（last-write-wins），FEAT-12 不解决该并发问题。

#### 3.18.5 服务层实现位置

```
backend/app/api/v1/improvement_reports.py    # 4+1 路由（POST 用户端 + check + GET 列表/详情 + PATCH admin）
                                              # router.py 注册 prefix /improvement-reports + /admin/improvement-reports
backend/app/models/improvement_report.py     # ImprovementReport ORM（含 report_categories JSONB + status PG ENUM）
backend/app/schemas/improvement_report.py    # ImprovementReportCreate / ImprovementReportAdminListItem /
                                              # ImprovementReportDetail / ImprovementReportPatch / ReportCategoryEnum
backend/migrations/versions/008_improvement_reports.py
                                              # report_status_enum 创建 + improvement_reports 表 +
                                              # UNIQUE(rag_record_id, llm_direct_record_id) + FK → generation_records.id
backend/tests/test_improvement_reports.py    # 端点级集成测试（mock DB；POST happy / 409 / 422 / 403 / 状态机非法跳转 / 分页过滤）
frontend/src/api/improvementReports.ts       # 4 条 axios 封装 + 类型定义
frontend/src/pages/Generate/GeneratePage.tsx  # result 阶段「提交对比报告」按钮 + Modal +
                                              # check 端点 mount 调用驱动按钮态
frontend/src/pages/Admin/AdminImprovementReportsPage.tsx        # 列表页（Table + Filter Bar）
frontend/src/pages/Admin/AdminImprovementReportDetailPage.tsx   # 详情页（三列 Card + mount 自动 PATCH in_review）
frontend/src/components/MainLayout.tsx        # 侧边栏 admin children 新增「对比报告」菜单项
frontend/src/App.tsx                          # 新增两条 RequireAdmin 路由（列表 + 详情）
```

#### 3.18.6 与 §3.17 / §3.9 / §3.10 的关系

- **§3.17（`llm_direct`）**：`improvement_reports` 路径**依赖** `parent_record_id` FK（v2.23 / FEAT-11 引入）作为成对锚点；本路径不修改 §3.17 任何端点
- **§3.9（L3 差评）**：两条独立通道，写入互不耦合（一条写 `generation_records.feedback_*` 4 列，一条写 `improvement_reports` 新表）
- **§3.10（L4 仪表盘）**：FEAT-12 不修改 4 个 KPI 端点；`improvement_reports` 数据消费 / 趋势图 / CSV 导出留 FEAT-13

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

备份文件存储于命名 Docker volume `backend_backups`，挂载到宿主机持久化目录。

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
| maturity | ENUM | `draft` / `validated` / `production`（**开发成熟度**——模板设计者标注的迭代位，纯元数据，不参与 RAG 召回判定。与 `maturity_level` 列独立） |
| **maturity_level** | ENUM `template_maturity_enum` | `production` / `experimental` / `draft`；**NOT NULL，server_default `'experimental'`**（migration 009 / FEAT-13 / v2.25）；**生产门控**——RAG stage1 Qdrant Filter + engine.py DB 二次过滤 + `dense_top1_score` 三处均**仅消费 `production`** 档；贡献流入库默认 `experimental`，须 super_admin 显式 PATCH 升至 `production` 才进入 RAG 召回主库；与 `maturity` 列**语义独立、不得混用**（详 §3.2 / §3.4 / §3.10 / §5.1） |
| is_active | BOOLEAN | 是否启用 |
| related_ids | VARCHAR[] | 关联模板 ID 列表 |
| qdrant_point_id | UUID | 对应 Qdrant 中的 point ID（用于向量更新/删除） |
| sync_status | ENUM | `ok` / `syncing` / `sync_error`，标识 PG 与 Qdrant 的同步状态 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 最后更新时间 |
| created_by | UUID | 创建者用户 ID |

> **注**：不再有 `embedding VECTOR` 字段，向量数据存于 Qdrant，通过 `qdrant_point_id` 关联。`sync_status` 用于检测 PostgreSQL 与 Qdrant 之间的数据一致性异常。`maturity` 与 `maturity_level` 两列并存且语义独立——前者描述"开发成熟度"，后者承担"生产门控"职责；migration 009 backfill 仅写 `maturity_level`，不触碰 `maturity`。

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
| **feedback_rating** | SMALLINT NULL | L3 用户反馈评分：`1=好` / `2=一般` / `3=差`；NULL=未反馈（migration 006） |
| **feedback_reason_tags** | JSONB NULL | 差评原因标签数组，元素来自 `ReasonTagEnum` 7 项枚举（`wrong_template` / `hallucinated_signal` / `syntax_error` / `semantic_error` / `style_bad` / `missing_disable_iff` / `other`）；rating=3 必填 |
| **feedback_comment** | TEXT NULL | 反馈自由文本（≤ 2048 字符），所有评分档均可选填 |
| **feedback_at** | TIMESTAMPTZ NULL | 反馈提交时间（UTC） |
| **generation_mode** | VARCHAR(16) NULL DEFAULT 'rag' | 代码来源：`'rag'`（默认，走 RAG + 模板渲染）/ `'llm_direct'`（v2.23 / FEAT-11 启用，由 `POST /generate/llm-fallback` 端点写入，详 §3.17）；`cache_hit` 路径仍标 `'rag'`——含义为"代码来源"，与 `cache_hit` 的"是否命中"语义正交 |
| **gate_error_type** | VARCHAR(32) NULL | 5 道闸触发记录标记：`'no_matching_template'` / `'off_topic'` / `'under_specified'` / `'code_type_mismatch'` / `'empty_retrieval'`；正常生成路径为 NULL；analytics `/no-match-rate` 端点的核心数据源 |
| **parent_record_id** | VARCHAR(36) NULL FK → generation_records.id | `ondelete=SET NULL`（migration 007）；仅 `generation_mode='llm_direct'` 的记录有非 NULL 值，回链触发本次 fallback 的源 RAG 记录。源记录被 admin 删除时仅清空 FK，保留 `llm_direct` 子记录及其反馈数据，详 §3.17.5。**FEAT-12 / v2.24 起，本列同时是 `improvement_reports` 的配对锚点**——`POST /improvement-reports` 要求 `rag_record_id == llm_direct_record.parent_record_id`（端点层校验，DB 不加 CHECK）；详 §3.18.2 / §4.1.4。注意：`improvement_reports` 表对 `generation_records.id` 的两个 FK 是 `ondelete=RESTRICT`，与本列 `SET NULL` 行为相反——存在 `improvement_reports` 引用时禁止删除 source / child record |

索引：`intent_hash`（历史意图库查询）、`user_id`（用户历史查询）

> **L3/L4 数据基础设施说明（migration 006）**：以上 6 列由 L3 用户反馈 + L4 分析仪表盘特性引入。`feedback_*` 4 列由 `POST /feedback/{id}` 写入（见下文"feedback API 数据流"）；`generation_mode` 默认 `'rag'`，正常生成与闸触发路径都写；`gate_error_type` 仅在 `api/v1/generate.py` 的 5 道闸 catch 块由 `_record_gate_event` 写入（见下文"generate endpoint 422 catch 路径写 record"）。**本 PR 不修改 `services/core/pipeline.py` 闸判断逻辑**，仅在端点层补持久化。

#### 4.1.1 feedback API 数据流

`POST /api/v1/feedback/{generation_record_id}` 唯一职责：把用户对单条 `generation_record` 的反馈写到上表 4 个 feedback 列。流程：

```
前端 GeneratePage result 阶段（FeedbackBar）
  ↓ POST /api/v1/feedback/{record_id}  body: {rating, reason_tags?, comment?}
api/v1/feedback.py::submit_feedback
  ↓ 1. db.get(GenerationRecord, id) → 不存在则 404
  ↓ 2. 权限校验：record.user_id == current_user.id OR current_user.role in {lib_admin, super_admin}
  ↓    不满足 → 403
  ↓ 3. Pydantic FeedbackCreate 已在端点入参校验：rating ∈ {1,2,3}（其他值 422），
  ↓    rating=3 且 reason_tags 空 → 422 PydanticCustomError(type='reason_tags_required')
  ↓ 4. 写 4 列：feedback_rating / feedback_reason_tags（[t.value for t in tags]）/
  ↓    feedback_comment / feedback_at（datetime.now(timezone.utc)）
  ↓ 5. 若原 record.generation_mode 为 NULL → 回填 'rag'（防 batch 老记录穿透）；
  ↓    显式 'rag' / 'llm_direct' 值**不**回写（FEAT-11 起 llm_direct 子记录由
  ↓    /generate/llm-fallback 端点显式写入，feedback 端点无需也不应覆盖）
  ↓ 6. db.commit()
返 HTTP 204 No Content
```

**幂等性**：未做去重——同一 `record_id` 重复 POST 会覆盖先前值（前端按钮已置灰防误操作）。如需历史保留改 L4 议题。

**适用范围**：自 v2.23 / FEAT-11 起，FeedbackBar 对 `rag` 与 `llm_direct` 两种 record 同等可用——前端按 `generation_record_id` 独立 lock，触发一次 `llm-fallback` 后产生新 record 即 `feedbackSubmitted` 归零，让用户分别为 `rag` 与 `llm_direct` 两条产出独立打分，分别进入 L4 analytics 桶。

**测试位置**：`backend/tests/test_feedback_api.py` 覆盖 422（rating=3 无 reason_tags）/ 403（user_id 不匹配） / 204（合法）三分支，全部 mock DB。

#### 4.1.2 admin analytics 模块

4 个端点全部在 `backend/app/api/v1/admin.py` 的 `# ── L4 analytics` 区块；时间窗 `days` 参数 `Query(7, ge=1, le=90)` 强制上限防全表扫；`require_role("lib_admin", "super_admin")` 守门。

**关键 SQL 聚合**：

| 端点 | 关键 SQL / 聚合策略 |
|---|---|
| `/feedback-summary` | 4 个并行 `count(*)`：`total_generations` / `total_feedbacks`（`feedback_rating IS NOT NULL`） / `bad_feedbacks`（`feedback_rating=3`） / `no_match_count`（`gate_error_type='no_matching_template'`）；`bad_rate` 分母用 `total_feedbacks` 避免 NaN |
| `/template-issues` | 单 `group_by(template_id)`，`case((feedback_rating==3, 1), else_=0)` 累加 `bad_count`；Python 侧按 `(bad_rate, bad_count) DESC` 排序后切片，避免 SQL 方言差异 |
| `/intent-confusion` | SQL 拉 `(original_intent, template_id, rag_top3)` where `feedback_rating=3 AND rag_top3 IS NOT NULL`；**Python 侧**对 `rag_top3[0]` 做 JSONB 路径访问、过滤 `expected != actual`、按 `(expected, actual)` 二元组聚合（不用用户原文做 key，脱敏 + 防基数爆炸）；末尾对桶内 `template_id` 集合做单次 `templates` 表反查拿 `code_type`（避免 N+1） |
| `/no-match-rate` | `GenerationRecord.created_at.cast(Date)` 作为分桶 key（UTC 日界）；`func.sum(case((gate_error_type=='no_matching_template', 1), else_=0))` 算当日 `no_match_count`；不补零行——只返实际有数据的天数 |

**数据源约定**：
- `intent-confusion` 的 `expected_template` = `rag_top3[0].template_id`——视 RAG top-1 为"用户期望"的近似。语义弱于"用户补填期望模板"方案，但用户零负担、全自动，ROI 更高
- `no-match-rate` 依赖 `gate_error_type` 列，**前提是 generate endpoint 422 catch 路径写 record**（见 §4.1.3）；否则该端点恒返 0
- `rag_top3` 为空数组的边界（empty_retrieval 触发时）：Python 聚合 `if not isinstance(rag, list) or not rag: continue` 兜底

**`generation_mode` filter（v2.23 / FEAT-11 起）**：4 个端点全部新增 optional `generation_mode: str | None = Query(None)` 参数，值域 `{"rag", "llm_direct"}`，omit = 全量。filter 作用 = 在 SQL where 子句追加 `GenerationRecord.generation_mode == :mode`。三类边界处理：

| 端点 | filter 行为 |
|---|---|
| `/feedback-summary` | 直接 where 过滤；`total_*` 与 `*_rate` 按所选模式重新聚合 |
| `/template-issues` | `generation_mode='llm_direct'` 时**移除默认的 `template_id IS NOT NULL` filter**，把 NULL 行归入 `__llm_direct__` 桶——LLM 直接生成的代码没有对应 template_id，这是设计内行为 |
| `/intent-confusion` | `generation_mode='llm_direct'` 时 `expected_template = rag_top3[0]` 仍指向源 RAG 记录的 top-1（语义：用户期望 vs LLM 实际给的代码差距），桶 key 仍按 `(expected, actual_or_llm_direct_marker)` 聚合 |
| `/no-match-rate` | 直接 where 过滤；`llm_direct` 模式下因 `gate_error_type` 恒为 NULL，端点恒返 `no_match_rate=0` 行——正常行为（`llm_direct` 路径绕过五闸） |

**测试位置**：`backend/tests/test_admin_analytics.py` 覆盖 4 端点的空数据 + 有数据两分支，mock DB。

#### 4.1.3 generate endpoint 422 catch 路径写 record（gate persistence）

L4 `/no-match-rate` 与 `/feedback-summary` 的 `no_match_rate` 字段都依赖"闸触发时也有 `generation_records` 行"这条不变量。本 PR 在 `api/v1/generate.py` 的 5 道闸 catch 块补写：

```python
async def _record_gate_event(db, user_id, original_intent, gate_error_type):
    # 1. 先 db.rollback()——pipeline 抛闸异常前可能往 session add 过中间对象
    #    （intent_cache 之类），不清洁就直接 commit 会把脏对象一并持久化
    # 2. db.add(GenerationRecord(user_id, original_intent,
    #          template_id=None, output_code=None, confidence=None,
    #          cache_hit=False, intent_cache_hit=False,
    #          generation_mode='rag', gate_error_type=<type>))
    # 3. db.commit()
    # 失败兜底：logger.exception + rollback（不抛，闸响应优先于 analytics 持久化）
```

`gate_error_type` 取值与 pipeline 抛出的异常一一对应：

| pipeline 异常 | `gate_error_type` 字面值 | HTTP 状态 |
|---|---|---|
| `OffTopicIntentError` | `off_topic` | 422 |
| `CodeTypeMismatchError` | `code_type_mismatch` | 422 |
| `UnderSpecifiedIntentError` | `under_specified` | 422 |
| `NoMatchingTemplateError` | `no_matching_template` | 422 |
| `EmptyRetrievalError` | `empty_retrieval` | 503 |

**只在 `/generate` 与 `/generate/preview` 端点做**，`/generate/render` 不参与（renderer 自身不抛闸异常，且 record 在 preview 阶段已写）。**不改 pipeline 闸判断本身**——本 PR 是闸事件持久化的基础设施扩展，对确定性契约（§1.1）无影响。

**与正常路径 record 的区分**：`gate_error_type IS NOT NULL` 即闸触发记录；`template_id` / `output_code` / `confidence` 均 NULL。`/template-issues` 端点 SQL where 加 `template_id IS NOT NULL` 自然排除这些行。

#### 4.1.4 improvement_reports（用户对比报告表，FEAT-12 / v2.24）

migration 008 新建独立表 + `report_status_enum` PG ENUM 类型；与 `generation_records.feedback_*` 4 列**互相独立**——L3 差评和对比报告是两条不同颗粒度的质量信号采集通道（详 §3.18.6）。

**报告分类枚举（`ReportCategoryEnum`，slug ↔ 中文 label 双向对照）**：

| slug | 中文 label | 含义 |
|---|---|---|
| `wrong_template` | 模板选错 | RAG 选中的模板与意图不符（语义错配） |
| `wrong_params` | 参数映射错 | 模板正确但参数填充错误（信号名 / 状态列表 / 表达式映射错） |
| `poor_style` | 代码风格差 | 模板正确、参数正确，但生成风格不符合团队规范（命名 / 缩进 / 注释） |
| `other` | 其他 | 上述 3 类无法归纳的差异 |

**状态枚举（PG ENUM `report_status_enum`，与 `ReportStatusEnum` Python 枚举一一对应）**：

| 值 | 含义 | 合法跳转（详 §3.18.4） |
|---|---|---|
| `pending` | 用户提交后默认状态，等待 admin 处理 | → `in_review`（admin 打开详情页时前端自动 PATCH） |
| `in_review` | admin 已查阅，处理中 | → `resolved`（admin 写完 admin_note 后「标记已处理」） |
| `resolved` | admin 已处理完毕（无论是否产生模板库改进） | 终止态（不允许倒退） |

**`improvement_reports` 表结构**：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | 报告主键 |
| reporter_id | UUID | NOT NULL, FK → users.id ondelete=RESTRICT | 提交用户 ID（提交后用户被删除时禁止级联——保留报告作为审计） |
| rag_record_id | VARCHAR(36) | NOT NULL, FK → generation_records.id ondelete=RESTRICT | RAG 源记录 ID；与 `llm_direct_record.parent_record_id` 配对 |
| llm_direct_record_id | VARCHAR(36) | NOT NULL, FK → generation_records.id ondelete=RESTRICT | LLM 直接生成子记录 ID（该记录 `generation_mode='llm_direct'`） |
| report_categories | JSONB | NULL | 用户勾选的 `ReportCategoryEnum` slug 数组；全空合法（前端可不勾任何分类） |
| reporter_note | TEXT | NULL | 用户自由文本描述差异；全空合法；无 DB 层长度 CHECK |
| status | report_status_enum | NOT NULL DEFAULT 'pending' | 三态状态机；非法跳转校验在端点层（详 §3.18.4） |
| admin_note | TEXT | NULL | admin 审阅时填写的处理说明；状态变 `resolved` 时建议填写但不强制 |
| reviewed_by | UUID | NULL, FK → users.id ondelete=SET NULL | 最后一次 PATCH 该报告的 admin id（多 admin 进入 in_review 时按 last-write-wins 覆盖） |
| reviewed_at | TIMESTAMPTZ | NULL | 最后一次 PATCH 时间（UTC） |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 提交时间 |

**约束**：
- `UNIQUE(rag_record_id, llm_direct_record_id)`：同一对生成记录只允许一份报告；冲突时 `POST` 端点返 409 `duplicate_report` + `detail.existing_report_id`
- **不**强制要求 `llm_direct_record.parent_record_id == rag_record_id`（端点层校验，DB 层不加 CHECK）；理由：DB CHECK 跨行依赖性能差且部署期 migration 风险高

**索引**：
- `idx_improvement_reports_status_created`（status, created_at DESC）：列表页过滤 + 默认排序
- `idx_improvement_reports_reporter_created`（reporter_id, created_at DESC）：用户视角"我提交的报告"（FEAT-12 不实现该端点，但索引提前布好留 FEAT-13）

**与 `generation_records` 的关系**：
- 上游：消费 `parent_record_id`（v2.23 / FEAT-11 引入）作为成对锚点；如 RAG 源记录被 admin 删除，由于 FK `ondelete=RESTRICT`，DB 层拒绝删除并报错——admin 需先删除对应 `improvement_reports` 才能删 source record（FEAT-12 不在 UI 暴露该清理路径，admin 走 SQL 直执）。`llm_direct` 子记录侧同样 RESTRICT
- 与 `feedback_*` 4 列正交：同一对 (RAG, llm_direct) 既可有 L3 差评（写 `generation_records.feedback_*`）也可有对比报告（写 `improvement_reports`），两条数据互不影响

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
| step2_disable_thinking | BOOLEAN | NOT NULL DEFAULT true；仅 `provider=openai_compatible` 生效，控制 `_step2_fill_params` 是否禁用模型 thinking（详见 §3.12.2）。Anthropic provider 走 `extended_thinking` 不受此字段控制 |
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

**template_corpus_cases（模板选择质量语料表，FEAT-4）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| intent | TEXT | 意图文本（用于 RAG 检索验证） |
| code_type | VARCHAR(16) | `assertion` / `coverage` |
| expected_template_id | VARCHAR(32) | 期望命中的模板 ID（FK → templates.id） |
| source | VARCHAR(32) | `auto_generated`（管理员审核时 LLM 生成）/ `manual`（人工添加）/ `user_report`（用户报告误判） |
| auto_generated_from | VARCHAR(64) | 来源 contribution_id（仅 `auto_generated` 时填充） |
| note | TEXT | 备注（可空，说明该用例的添加原因） |
| is_active | BOOLEAN | 是否参与 CI 回归（默认 true） |
| created_at | TIMESTAMPTZ | 创建时间 |

与 `backend/tests/data/template_selection_corpus.yaml`（静态语料库）共同构成回归测试基线：
- 静态 YAML：版本控制，FIX-3 等已知 bug 的种子用例
- DB 动态表：每次管理员审核新模板时自动生成，持续积累

`corpus_service.py` 三个核心函数：
- `generate_corpus_cases(contribution, llm, existing_templates)`：LLM 为新模板生成 3 条正例意图 + 每个语义近邻各 1 条反例意图
- `detect_conflicts(new_template_text, corpus_cases, embedding_client, rag_fn)`：对每条现有语料，比较新模板 embedding 与当前 RAG top-1 分数；若新模板得分更高则标记冲突
- `generate_llm_analysis(new_template, conflicts, llm)`：生成业务友好的根因分析 + 字段修改建议（不向管理员暴露 embedding 分数）

### 4.2 Qdrant Collection 结构

| Collection | 用途 |
|-----------|------|
| `templates` | 存储所有启用模板的三种向量（dense / sparse / colbert） |

每个 Qdrant Point：
- **id**：UUID（与 PostgreSQL `templates.qdrant_point_id` 对应）
- **vectors**：dense（1024维）+ colbert（N×1024维）
- **sparse_vectors**：sparse（词汇权重字典）
- **payload**：template_id、code_type、subcategory、protocol、maturity（开发成熟度，纯元数据）、**maturity_level（生产门控，v2.25 / FEAT-13，stage1 Filter 必读字段）**；原 `category` 字段已重命名为 `code_type` 与 CodeTypeRegistry 对齐

---

## 5. API 设计

### 5.1 核心端点列表

| 方法 | 路径 | 描述 | 权限 |
|------|------|------|------|
| GET | `/api/v1/generate/code-types` | 获取已注册代码类型列表（前端动态读取，无需硬编码） | 普通用户+ |
| POST | `/api/v1/generate` | 单条代码生成（legacy 一步式，内部串行调 preview+render） | 普通用户+ |
| POST | `/api/v1/generate/preview` | 两步式第一步：返回模板候选 + 参数预填（含 5 类源标识与 sanitized/validation_error） | 普通用户+ |
| POST | `/api/v1/generate/render` | 两步式第二步：用户确认参数后渲染 + 写代码缓存（`intent_hash` 非空时也写 GenerationRecord）；响应体含 `generation_mode: "rag"` 字段（v2.23 / FEAT-11） | 普通用户+ |
| POST | `/api/v1/generate/llm-fallback` | **v2.23 / FEAT-11 Stage 2**：用户对 `rag` 结果不满意时触发 LLM 自由生成兜底；入参 `{generation_record_id}`，写新 `GenerationRecord(generation_mode='llm_direct', parent_record_id=source.id)`；响应 `{code, generation_record_id, generation_mode: "llm_direct", cache_hit}`；5 类错误：404（detail 为纯字符串）/ 422 `llm_direct_chained_not_allowed` / 422 `llm_direct_no_code` / 422 `llm_direct_internal_error`（ValueError 分支）/ 500 `llm_direct_internal_error`（Exception 分支）（详 §3.17） | 普通用户+ |
| POST | `/api/v1/batch/upload` | 上传 Excel 创建批量任务 | 普通用户+ |
| POST | `/api/v1/batch/preflight` | 上传后前置信度预检（轻量，仅Stage1） | 普通用户+ |
| GET | `/api/v1/batch/{job_id}` | 查询批量任务状态 | 普通用户+ |
| GET | `/api/v1/batch/{job_id}/download` | 下载批量生成结果 | 普通用户+ |
| POST | `/api/v1/intent-builder/chat` | v3.0 多轮 RAG-grounded 对话；首轮 `session_id=""` 由后端 mint，TTL 24h | 登录用户+ |
| GET | `/api/v1/intent-builder/scenarios` | **v3.0 退役**：返 HTTP 410 Gone，提示改用 `/chat` | — |
| POST | `/api/v1/intent-builder/build` | **v3.0 退役**：返 HTTP 410 Gone，提示改用 `/chat` | — |
| GET | `/api/v1/templates` | 模板列表（支持搜索/筛选/分页） | 普通用户+ |
| GET | `/api/v1/templates/{id}` | 模板详情 | 普通用户+ |
| POST | `/api/v1/admin/templates` | 新建模板（同步写 PG + Qdrant）；先执行查重，相似度 ≥ 阈值返回 `duplicate_warning`；附加 `?force=true` 跳过语义查重 | 库管理员+ |
| PATCH | `/api/v1/admin/templates/{id}` | 更新模板（同步更新 PG + Qdrant）；**v2.25 / FEAT-13** 起 payload 含 `maturity_level` 时新增权限闸：`current_user.role != 'super_admin'` 返 HTTP 403 `detail="仅 super_admin 可修改 maturity_level"`；非法 enum 值（非 `production`/`experimental`/`draft`）由 Pydantic schema 返 HTTP 422 | 库管理员+（修改 `maturity_level` 字段仅 super_admin） |
| DELETE | `/api/v1/admin/templates/{id}` | 停用模板（软删除，Qdrant 同步删除向量） | 库管理员+ |
| POST | `/api/v1/admin/templates/import` | 批量导入 YAML（批量写 PG + Qdrant） | 库管理员+ |
| GET | `/api/v1/admin/users` | 用户列表 | 超管 |
| PUT | `/api/v1/admin/users/{id}/role` | 修改用户角色 | 超管 |
| POST | `/api/v1/auth/login` | 登录获取 JWT | 公开 |
| POST | `/api/v1/auth/register` | 自助注册账号（默认 role=user） | 公开 |
| GET | `/api/v1/auth/me` | 获取当前登录用户信息 | 登录用户+ |
| GET | `/health`、`/api/health` | 健康检查（容器探针 + 反代探活） | 公开 |
| GET | `/api/v1/admin/llm/configs` | 获取所有模型配置（api_key 只返回掩码） | 超管 |
| POST | `/api/v1/admin/llm/configs` | 新增模型配置 | 超管 |
| PUT | `/api/v1/admin/llm/configs/{id}` | 更新配置（api_key 留空则不覆盖） | 超管 |
| DELETE | `/api/v1/admin/llm/configs/{id}` | 删除配置（默认模型不可删） | 超管 |
| PUT | `/api/v1/admin/llm/configs/{id}/set-default` | 设为默认（自动清空相关 Redis 缓存） | 超管 |
| POST | `/api/v1/admin/llm/configs/{id}/test` | 执行模型测试（basic/normalization/template_selection） | 超管 |
| POST | `/api/v1/contributions/preview` | **FEAT-10**：仅基于 `original_intent + code_type` 让 LLM 生成完整模板预览（**不入库**）；返回 `{template_name, description, demo_code, parameter_defs, keywords, name_conflict}`；`name_conflict` 由 `check_name_duplicate` 计算非阻塞；解析失败统一 422 `contribution_parse_failed`（含 `detail.stage` / `detail.reason`） | 登录用户+ |
| POST | `/api/v1/contributions` | 提交模板贡献；v3.1 必填降至 `original_intent + code_type`，`template_name / description / demo_code` 全部可选；按顺序 3 分支判定（intent-only LLM 生成 / 显式 parameter_defs 走 v2 批量路径 / 4 字段齐全走 demo 反推）；响应 `ContributionOut` 新增 `use_immediately_available: bool = True` | 登录用户+ |
| GET | `/api/v1/contributions/mine` | 查看我的贡献列表 | 登录用户+ |
| GET | `/api/v1/contributions/{id}` | 查看贡献详情 | 贡献者本人 |
| PUT | `/api/v1/contributions/{id}` | 修改贡献（仅 needs_revision 状态） | 贡献者本人 |
| GET | `/api/v1/admin/contributions` | 贡献列表（支持 status/type 过滤） | 库管理员+ |
| GET | `/api/v1/admin/contributions/{id}` | 贡献详情（含 Excel 行快照 + 查重结果 Top-3） | 库管理员+ |
| POST | `/api/v1/admin/contributions/{id}/pre-approve-analysis` | 批准前分析（非破坏性）：冲突检测 + 语料生成 + LLM 根因分析 | 库管理员+ |
| PUT | `/api/v1/admin/contributions/{id}/approve` | 批准并触发入库流水线（同时激活 pre-approve 阶段生成的语料） | 库管理员+ |
| PUT | `/api/v1/admin/contributions/{id}/reject` | 退回，body：`{comment}` | 库管理员+ |
| PUT | `/api/v1/admin/contributions/{id}/request-revision` | 请求修改，body：`{comment}` | 库管理员+ |
| GET | `/api/v1/notifications` | 获取当前用户通知列表 | 登录用户+ |
| PUT | `/api/v1/notifications/{id}/read` | 标记通知已读 | 登录用户+ |
| GET | `/api/v1/admin/audit-logs` | 查询管理员操作审计日志（按 action/operator/时间范围过滤，分页） | 超管 |
| POST | `/api/v1/feedback/{generation_record_id}` | L3 用户反馈：写 `generation_records` 的 4 个 feedback 列；rating ∈ {1,2,3}（其他 422）；rating=3 必填 `reason_tags`（否则 422 `reason_tags_required`）；非 owner 且非 admin 返 403；成功 204 | 登录用户+（自己记录）/ 库管理员+（任意记录） |
| GET | `/api/v1/admin/analytics/feedback-summary` | L4 KPI：`{days, total_generations, total_feedbacks, feedback_rate, bad_rate, no_match_rate}`；空数据各率返 0.0；`days` ∈ [1, 90] 默认 7 | 库管理员+ |
| GET | `/api/v1/admin/analytics/template-issues` | L4 差评模板 top-N：`[{template_id, total_count, bad_count, bad_rate}]`，按 `bad_rate DESC, bad_count DESC` 排序；`limit` ∈ [1, 100] 默认 10 | 库管理员+ |
| GET | `/api/v1/admin/analytics/intent-confusion` | L4 意图-模板混淆：`[{intent, expected_template, actual_template, code_type, count}]`；数据源仅 `feedback_rating=3 AND template_id != rag_top3[0].template_id`；`code_type` 由后端 join `templates` 表填好供前端复制 corpus 条目 | 库管理员+ |
| GET | `/api/v1/admin/analytics/no-match-rate` | L4 按 UTC 日界聚合：`[{date, total, no_match_count, no_match_rate}]`；不补零行；依赖 `gate_error_type='no_matching_template'` 数据源 | 库管理员+ |
| POST | `/api/v1/improvement-reports` | **FEAT-12 / v2.24** 用户对比报告提交：入参 `{rag_record_id, llm_direct_record_id, report_categories?, reporter_note?}`；categories/note 全空合法；写 `improvement_reports.status='pending'`；FK 缺失 422 `invalid_record_ref`；UNIQUE 冲突 409 `duplicate_report` + `detail.existing_report_id`；未登录 401（详 §3.18） | 登录用户+ |
| GET | `/api/v1/improvement-reports/check` | **FEAT-12** 轻查询端点：查询 `(rag_record_id, llm_direct_record_id)` 对是否已有报告；契约 200 `{exists: bool, report_id?: UUID}` 单形态（前端按 `exists` bool 分支按钮 disabled 态）；鉴权与 POST 同级，不限 admin | 登录用户+ |
| GET | `/api/v1/admin/improvement-reports` | **FEAT-12** admin 列表：分页 + 支持 `status`（单选）+ `categories`（多选）过滤，默认 `created_at DESC`；返回 join 摘要（reporter username / RAG template_name / categories Tag / created_at）；非 admin 403 | 库管理员+ |
| GET | `/api/v1/admin/improvement-reports/{id}` | **FEAT-12** admin 详情：返两条 `generation_record` 完整对比字段（`output_code` / `template_id` / `template_name`（join templates 取 name）/ `params_used` / `original_intent` / `generation_mode` / `cache_hit`）+ 用户提交字段（categories / reporter_note）+ 当前 status / admin_note / reviewed_by / reviewed_at；非 admin 403 | 库管理员+ |
| PATCH | `/api/v1/admin/improvement-reports/{id}` | **FEAT-12** admin 状态机更新：可单独或同时更新 `status` 与 `admin_note`；三态状态机（pending → in_review → resolved）校验在端点层；非法跳转返 422 `illegal_status_transition`（`pending → resolved` 跳过 in_review、`resolved → pending` / `resolved → in_review` / `in_review → pending` 倒退均拒绝）；同时写 `reviewed_by = current_user.id` + `reviewed_at = now()`；非 admin 403 | 库管理员+ |

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

# 描述（三要素：做什么 / 典型场景 / 边界）
# 约定（v2.21 / A10）：`description` 应同时覆盖"本模板做什么"+"典型场景"+
# "边界：请勿用于 X 请用 Y"三要素；< 30 字节会被 lib_manager validate 标 WARN。
description: |
  做什么：当 valid 拉高且 ready 尚未响应（握手等待期间），断言数据/payload 信号必须保持稳定（$stable），关注的是"等待期间数据不变"。
  典型场景：wvalid=1 但 wready=0 期间 wdata 不能改变；arvalid 期间 araddr 必须保持稳定。
  边界：请勿用于"ready 必须在 N 周期内响应"（超时检测）—— 那是 sva_handshake_timeout_v1；也不要用于"req → ack 响应时间上限"（通用两事件时序）—— 那是 sva_timing_max_delay_v1。

# 与最近邻模板的区别要点（v2.21 / A10，可选）
# lib_manager.py import 时通过 _compose_description 拼到 description 列末尾形成
# "区别要点：" 段（每项 `- ` 前缀），由现有列流转到 Qdrant payload / reranker text /
# pipeline.candidate_dicts / LLM step1 prompt。声明此键即必须是非空 list（validate ERROR）。
differentiators:
  - 关注的是 valid 等待期间 data/payload 的 $stable 稳定性，不数等待周期、不抛超时
  - 触发条件是 `valid && !ready`（握手未完成态），不关心首次 valid 上升沿后等多久 ready 才到

# 不适用场景（v2.21 / A10，可选）
# 同上：lib_manager.py import 时拼成 "不适用场景：" 段；声明此键即必须是非空 list。
non_use_cases:
  - 验证 ready 必须在 N 周期内响应（应用 sva_handshake_timeout_v1）
  - 验证 FSM 状态转换或复位行为

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
│   │   │       ├── router.py                    # APIRouter 汇总注册
│   │   │       ├── generate.py                  # 单条生成端点 + /code-types
│   │   │       ├── batch.py                     # 批量生成端点
│   │   │       ├── templates.py                 # 模板库查询端点
│   │   │       ├── admin.py                     # 管理员端点（模板 CRUD + 用户管理 + 审计日志）
│   │   │       ├── admin_llm.py                 # LLM 模型配置 + 测试端点
│   │   │       ├── contributions.py             # 贡献者端点 + 管理员审核端点（合并单文件）
│   │   │       ├── notifications.py             # 站内通知端点
│   │   │       ├── intent_builder.py            # 场景构建器端点
│   │   │       ├── improvement_reports.py      # FEAT-12 用户对比报告 4+1 路由（POST + check + GET 列表/详情 + PATCH）
│   │   │       └── auth.py                      # 认证端点
│   │   ├── core/
│   │   │   ├── config.py                 # 环境配置（从环境变量读取）
│   │   │   ├── database.py               # PostgreSQL 连接
│   │   │   ├── vector_store.py           # Qdrant 客户端连接
│   │   │   ├── cache.py                  # Redis 连接
│   │   │   └── security.py               # JWT 认证工具
│   │   ├── models/
│   │   │   ├── template.py               # SQLAlchemy 模板模型（Template + TemplateVersion）
│   │   │   ├── user.py                   # 用户模型
│   │   │   ├── generation_record.py      # 生成历史模型
│   │   │   ├── batch_job.py              # 批量任务模型
│   │   │   ├── llm_config.py             # LLM 配置模型
│   │   │   ├── contribution.py           # 模板贡献模型
│   │   │   ├── notification.py           # 站内通知模型
│   │   │   ├── improvement_report.py     # FEAT-12 用户对比报告 ORM（report_categories JSONB + status PG ENUM）
│   │   │   └── audit_log.py              # 管理员操作审计日志模型
│   │   ├── schemas/
│   │   │   ├── generate.py               # 生成请求/响应 Schema
│   │   │   ├── template.py               # 模板 Schema
│   │   │   ├── intent.py                 # LLM 工具调用输出 Schema
│   │   │   ├── user.py                   # 用户 Schema
│   │   │   ├── llm_config.py             # LLM 配置请求/响应 Schema（新增）
│   │   │   ├── contribution.py           # 贡献请求/响应 Schema
│   │   │   ├── improvement_report.py     # FEAT-12 ImprovementReportCreate / AdminListItem / Detail / Patch + ReportCategoryEnum
│   │   │   └── notification.py           # 通知响应 Schema
│   │   ├── services/
│   │   │   │                             # ── 三层服务子包结构 ──
│   │   │   ├── core/                     # 核心算法层（代码类型无感知，纯函数级，禁调 LLM）
│   │   │   │   ├── pipeline.py           # 流水线编排器（pipeline_preview / pipeline_render / run_pipeline）
│   │   │   │   ├── cache.py              # Redis 缓存读写（原 cache_service.py）
│   │   │   │   ├── renderer.py           # Jinja2 渲染 + StrictUndefined（原 renderer/jinja_renderer.py）
│   │   │   │   ├── dedup.py              # 模板查重逻辑（精确名称 + 语义向量）
│   │   │   │   ├── identifier.py         # SV 标识符 sanitize + IDENTIFIER_PARAMS 兜底白名单（§3.15.5）
│   │   │   │   └── expr_validator.py     # sv_boolean_expr / sv_identifier_list / sv_bins_expr 校验 + EXPR_TYPE_DISPATCH（§3.15.5）
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
│   │   │   │   ├── backup_service.py     # 备份管理服务（新增）
│   │   │   │   └── corpus_service.py     # FEAT-4：语料自动生成 + 冲突检测 + LLM 根因分析
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
│   ├── lib_manager.py                    # CLI：模板导入/验证/重建Qdrant索引（位于 backend/ 根目录）
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
│   ├── migrations/                       # Alembic 数据库迁移
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 001_initial_schema.py     # 初始全量建表（含所有表结构）
│   │       ├── 002_step2_disable_thinking.py  # llm_configs.step2_disable_thinking BOOL 列
│   │       ├── 003_align_sync_status_enum.py  # sync_status enum 值与 ORM 对齐（幂等）
│   │       ├── 004_unique_default_llm.py      # llm_configs.is_default 部分唯一索引
│   │       ├── 005_template_corpus_cases.py   # template_corpus_cases 表（FEAT-4 回归语料）
│   │       ├── 006_feedback_columns.py        # generation_records 加 6 列（L3 反馈 / generation_mode / gate_error_type）
│   │       ├── 007_llm_direct_parent_fk.py    # generation_records.parent_record_id FK（FEAT-11 Stage 2）
│   │       ├── 008_improvement_reports.py     # FEAT-12：report_status_enum 创建 + improvement_reports 表 + UNIQUE(rag_record_id, llm_direct_record_id) + FK → generation_records.id ondelete=RESTRICT
│   │       └── 009_template_maturity_level.py # FEAT-13：template_maturity_enum 创建 + templates.maturity_level 列（NOT NULL，server_default 'experimental'） + 全表 backfill（sva_*_v* / cov_*_v* → production，其余 → experimental）；upgrade() 末尾打印 WARN 提示部署方紧接 lib_manager rebuild 同步 Qdrant payload
│   ├── tests/
│   │   ├── test_template_maturity_gating.py   # FEAT-13：stage1 Filter 包含 maturity_level='production' / engine.py DB 二次过滤拦截非 production / PATCH maturity_level 的 super_admin 200·lib_admin 403·非法值 422 / migration 009 backfill 条件函数单测（全程 mock Qdrant + PG，无活基础设施依赖）
│   │   └── ...                                  # 其他既有测试文件（test_pipeline_preview_render / test_offtopic_corpus_mocked / test_feedback_api / test_admin_analytics / test_llm_direct_generation / test_llm_freeform_client / test_improvement_reports 等）
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
│   │   │       ├── AdminImprovementReportsPage.tsx       # FEAT-12 admin 列表页（Table + Filter Bar）
│   │   │       ├── AdminImprovementReportDetailPage.tsx  # FEAT-12 admin 详情页（三列 Card + mount 自动 PATCH in_review）
│   │   │       └── LLMConfig/            # LLM 模型配置管理（新增）
│   │   │           ├── index.tsx         # 模型列表（卡片形式）
│   │   │           └── TestPanel.tsx     # 三类模型测试面板
│   │   ├── api/
│   │   │   ├── client.ts                 # Axios API 调用封装
│   │   │   ├── contributionApi.ts        # 贡献 API 封装
│   │   │   ├── intentBuilderApi.ts       # 场景构建器 API 封装
│   │   │   ├── improvementReports.ts     # FEAT-12 对比报告 4 条 axios 封装（user POST + check + admin 列表/详情/PATCH）
│   │   │   └── llmConfigApi.ts           # LLM 配置管理 API 封装（新增）
│   │   ├── utils/
│   │   │   ├── validateParam.ts          # 参数表单基础校验（前端）
│   │   │   └── exprValidators.ts         # 后端 expr_validator 的前端镜像（§3.15.5）
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

所有平台均使用相对路径，主 `docker-compose.yml` 不含平台特定配置，GPU/开发/热重载通过覆盖文件叠加：

```bash
# Linux（生产，含 GPU）
docker compose -f docker-compose.yml -f docker-compose.gpu-linux.yml up -d

# Windows（生产，含 GPU，需 Docker Desktop + WSL2）
docker compose -f docker-compose.yml -f docker-compose.gpu-windows.yml up -d

# 开发环境（Linux / Windows 均适用，不需要 GPU）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 后端代码热重载（在 dev 基础上挂载 backend/ 源码目录 + uvicorn --reload）
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.hotreload.yml up -d
```

`docker-compose.hotreload.yml` 仅覆盖 backend / celery_worker 的 `volumes` 与 `command`，将本地 `./backend` 挂到容器 `/app`，并把 backend 启动命令改为 `uvicorn --reload`，源码改动 1 秒内自动生效，无需 rebuild。

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
backend → LLM API（HTTPS，外网）    (Anthropic / GLM-4.7 / DeepSeek / Qwen / 本地 vLLM / Ollama 等，由 llm_configs 配置决定)

celery_worker → embedding_service:8001
celery_worker → qdrant:6333
celery_worker → postgres:5432
celery_worker → redis:6379
```

**入口 nginx DNS 解析配置**（关键）：

```nginx
server {
  listen 80;
  resolver 127.0.0.11 valid=10s ipv6=off;     # Docker 内置 DNS

  location /api/ {
    set $upstream_backend http://backend:8000;  # 用变量触发每次请求重解析
    proxy_pass $upstream_backend;
    proxy_read_timeout 300s;                    # GLM thinking 模型可能需要 60-150s
    ...
  }
}
```

不能用 `upstream backend { server backend:8000; }`，因为 nginx 在启动时一次性解析并缓存上游 IP；当 backend 容器重启（dev 模式下 hot-reload 频繁触发）IP 变化后，nginx 仍指向旧 IP，导致 `502 Bad Gateway` 直到下次 nginx reload。改用 `resolver` + 变量化 `proxy_pass` 后，nginx 按 `valid=10s` 周期重解析。

**前端容器 nginx 缓存策略**：

```nginx
# index.html 必须每次重取，否则 hash 化资源更新后浏览器仍引用旧 bundle
location = /index.html {
  add_header Cache-Control "no-cache, no-store, must-revalidate";
}
# hash 化的静态资源永久可缓存（文件名变化时 HTML 自然引导浏览器拉新文件）
location ~* \.(js|css|png|jpg|ico|svg|woff2?)$ {
  expires 30d;
  add_header Cache-Control "public, immutable";
}
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
| `EMBEDDING_DIM` | embedding 模型输出维度（默认 `1024`，bge-m3）；启动时与 Qdrant collection 现有维度比对，错配打 WARN（详 §3.6 / `main.py:_init_qdrant_collection`） |
| `OFFTOPIC_GATE_ENABLED` | off-topic dense 闸总开关（默认 `true`）；设 `false` 时退回 v2.9 之前"始终生成代码"行为 |
| `OFFTOPIC_DENSE_THRESHOLD` | off-topic dense top-1 阈值（默认 `0.44`，由 `backend/scripts/calibrate_offtopic_threshold.py` 校准；换 embedding 模型 / 模板库大改后必须重跑） |
| `CODE_TYPE_MISMATCH_GATE_ENABLED` | code_type 一致性闸总开关（默认 `true`）；`OFFTOPIC_GATE_ENABLED=false` 时本闸自动跳 |
| `CODE_TYPE_MISMATCH_MARGIN` | 别类 code_type dense 得分超过当前类多少时判定 mismatch（默认 `0.10`） |
| `UNDER_SPECIFIED_GATE_ENABLED` | under_specified 闸总开关（默认 `true`）；设 `false` 时退回 v2.12 之前"系统编参数兜底总能产出代码"行为 |
| `STEP1_VERIFY_ENABLED` | A8 step1 二次验证开关（默认 `false`）；开启前需用 confusion corpus 的 real-llm 套件评估 false-negative 率（详 §3.15.3 Step 5a / docs/test-manual.md §2.7） |
| `STEP1_RERANKER_GATE_ENABLED` | A9 reranker score gate 开关（默认 `false`）；开启前必须先跑 `backend/scripts/calibrate_reranker_threshold.py` 在 selection + confusion corpus 上标定阈值（详 docs/test-manual.md §2.8） |
| `RERANKER_MIN_SCORE_THRESHOLD` | A9 step1 选中模板的 stage3 reranker score 下限（默认 `0.30`，经验占位值；标定后写入 `backend/app/core/config.py` 默认值） |
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
