# IC验证辅助代码生成平台 — 产品需求文档（PRD）

**版本**：v3.6  
**状态**：起草中  
**日期**：2026-06-17  
**变更**：
- v1.0 → v2.0：输入方式由"自然语言+Excel信号表"调整为"双表格结构化输入"（SVA需求表 + 功能覆盖率需求表）
- v2.0 → v2.1：新增模板贡献与审核机制，处理 RAG 置信度 < 50% 时模板缺口的知识沉淀闭环
- v2.1 → v2.2：新增四层验证意图标准化机制，解决不同工程师表达差异导致 RAG 匹配率低的问题
- v2.2 → v2.3：新增 LLM 多模型支持（第三方模型通过 URL+API Key 接入）及模型测试功能
- v2.3 → v2.4：可行性评审修订——修正 §3.7 子节编号；单条生成改为结构化信号输入；预检去除 LLM 调用改为纯 Stage1 检索；更新 §8 待确定项；补充相关术语修正
- v2.4 → v2.5：新增模板入库查重机制（名称精确匹配 + 语义相似度检查），覆盖 Admin UI 新建、YAML 批量导入、贡献审核三条入库路径
- v2.5 → v2.6：新增数据备份与误操作保护机制——§4.6 数据安全与可恢复性非功能需求；§3.4 新增 Dry-Run 预检和操作审计日志功能
- v2.6 → v2.7：架构分层解耦优化——§1.2 产品定位补充代码类型可扩展性说明；§4.2 扩展性需求覆盖新代码类型场景；§5 模板分类体系注册制说明；§7 Out of Scope 区分永久约束与可扩展项
- v2.7 → v2.8：§4.3 性能指标按所选 LLM 是否为 thinking 模型分档（非 thinking 模型保持 <10s，thinking 模型如 GLM-4.7 / DeepSeek-R1 调整为 60-150s）；§3.5.1 LLM 模型清单补充 GLM 系列与 Ollama 本地部署说明
- v2.8 → v2.9：§3.6 新增"自助注册账号"能力——登录页提供注册标签页，新账号默认 role=普通用户，库管理员/平台管理员仍由超管在用户管理页升级；§6.1 单条生成主流程改为统一两步式确认面板（preview → 用户确认 → render），意图缓存命中时通过 `quick_render` 短路跳过确认面板
- v2.9 → v2.10：**核心契约修订**——"系统对任何输入必定产出代码"契约**收窄为仅对域内 IC 验证输入**；无关意图（诗歌/闲聊/数学题/通用代码请求等）经 RAG 之前的 dense 余弦阈值闸（默认 0.44）直接返 HTTP 422 拒绝，前端弹"检测到非验证请求"专属 Modal，不再退化生成全 placeholder 代码（详见 ARCHITECTURE.md §1.1）；阈值由 `backend/scripts/calibrate_offtopic_threshold.py` 经验校准，紧急情况通过 `OFFTOPIC_GATE_ENABLED=false` 一键关闸退回老行为
- v2.10 → v2.11：§3.5.1 LLM 模型配置新增"Step2 禁用 thinking"开关（仅 OpenAI 兼容 Provider 可见，默认开启）——对 GLM-4.7/DeepSeek-R1 等 thinking 模型，关闭后单次推理可由 12-249s 降至 ~3s；管理员可在 FSM 复杂参数填充能力验证场景临时关闭以保留推理；§4.3 性能指标按 thinking 开关分档刷新（thinking 默认禁用后非缓存路径回到 < 10s 量级），前端 `/generate` 客户端超时从 180s 提升至 300s 以兼容 thinking ON 模式
- v2.11 → v2.12：§6.1 单条生成主流程新增"系统侧异常"错误模式——RAG 检索为空且关键词补充召回也命中不到模板时返 HTTP 503（基础设施异常），前端弹"暂时无法生成，请稍后重试或联系管理员"提示，与 off-topic 422（用户问题，提示用户改提问）分流；用户无需也无法自助处理 503，提示文案直接引导联系管理员/SRE
- v2.12 → v2.13：**核心契约第二次反转**——"系统总能产出代码（兜底用参数名占位）"契约**彻底退役**。意图在域但**必填参数缺少高置信源**时返 HTTP 422 `under_specified`，detail 含 `missing_params` 列表（带 description / expr_type / role_hint），前端 Modal 引导用户补描述。判定规则：参数源落在 `semantic_fallback` / `placeholder` / 或 LLM 返"trivial 值"（空串/0/字面参数名）→ 低置信 → 拒。新增第 6 类参数源 `semantic_fallback` 与 `default` 区分（"系统按经验猜"vs"用户/模板设计"）。code-type 一致性闸同期上线（v2.13）：意图语义匹配另一类时 422 `code_type_mismatch` 提示切换。两道新闸均有 `UNDER_SPECIFIED_GATE_ENABLED` / `CODE_TYPE_MISMATCH_GATE_ENABLED` env 关闸通道。本次的设计原则是"承认无能"——LLM 不允许编参数兜底，让用户知道具体缺什么再补
- v2.13 → v3.0：**用户旅程根本性重构**——从"NL 单端点生成"切换为"NL → 意图标准化（IntentBuilder）→ 生成 / 贡献"二级流。
  - §3.7 模板贡献向导大幅简化：用户只填 `name + code_type + description + 代码示例`，后端 LLM 自动反推 `parameters JSON` 与 Jinja2 化的 `template_body`，审核员可三栏（原始代码 / 反推模板 / 反推参数）任意修改后批准。Demo 编辑器里手填占位符 / 参数定义表单的旧 Step 2/3 退役。
  - §3.8 重命名为"**意图构建器（IntentBuilder）**"，由四层标准化机制改为**RAG-grounded 多轮对话**：LLM 每轮自动跑一次 RAG 检索把库内 top-3 模板的 `description` 喂回 prompt，引导用户往已存在模板靠拢；若 N 轮后所有候选都明显不匹配，引导用户跳转到 §3.7 贡献新模板。会话历史存 Redis（key=`intent_builder_session:{user_id}:{session_id}`，TTL 24h），LLM 沿用 `llm_configs.is_default`。
  - §6.1 单条生成错误模式新增 `detail.redirect_to` 字段：`under_specified` / `code_type_mismatch` 等"用户问题"返 422 时附带前端应跳转的路由（如 `/intent-builder?prefill=<intent>&missing=<params>`），前端 `handleApiError` 读到该字段无脑 `router.push`，不再在 Generate 页弹 dead-end Modal。`off_topic` / `empty_retrieval` 不带 `redirect_to`（前者用户问题但去 IntentBuilder 也救不了，后者是基础设施问题）。
  - `normalize_intent` 角色降级为"**弃权信号载体**"：sentinel "无法判断类型，输出原文"保留，但下游不再用它做兜底——sentinel 之后参数仍是低置信源时 under_specified 闸照常拦。同义改写本身仍跑（保 cache key 稳定），但**不**承担"我替你猜你想说什么"的职责。
  - PipelineInput 新增可选字段 `source: "intent_builder" | "direct" = "direct"`，仅供日志/统计区分入口（不影响路由逻辑）。
  - **不**加新的低 confidence 硬闸——v2.13 的 4 道闸（off-topic / code_type_mismatch / under_specified / empty_retrieval）已覆盖所有"用户问题"场景，置信度保留为信息性元数据，由前端 ConfirmationPanel 软提示「贡献新模板」入口决定后续动作
- v3.0 → v3.1：**§3.7 模板贡献向导从 4 字段再次简化为 2 字段**（FEAT-10）——用户只填 `original_intent + code_type` 两件，`template_name / description / demo_code` 由后端 LLM 一次性生成；前端提交 Modal 改为两步 Steps：Step 1 输入意图调 `POST /api/v1/contributions/preview` 取预览；Step 2 展示并允许编辑 `template_name / description / demo_code`，提供「提交审核」与「立即使用」两个按钮。新增**双层审核**机制：第一层是用户在 Step 2 对 LLM 输出做语义级验证（编辑或接受），第二层是管理员三栏审核（不变）。「立即使用」直接在 Step 2 页面内展示可复制代码框（`<pre>` 块 + 复制按钮），**不再跳转 `/generate`**——避免 `pending_review` 贡献因不在 Qdrant 中触发 `no_matching_template` 闸进入循环。LLM 生成的 `template_name` 走 `^(sva|cov)_[a-z][a-z0-9_]*_v\d+$` 命名规范校验 + `check_name_duplicate`，重名时预览响应携带 `name_conflict: true` 非阻塞提示（前端 Warning Alert 引导改名后重提）。`ContributionOut` 新增 `use_immediately_available: bool` 恒 true 字段供前端条件渲染。原 4 字段提交路径（`template_name + description + demo_code` 全传）作为分支 3 完全向后兼容；`parameter_defs` 显式传入仍走 v2 批量路径不调 LLM。
- v3.1 → v3.2：**新增 §3.9 L3 用户反馈机制 + §3.10 L4 管理员分析仪表盘**——
  - §3.9 GeneratePage `result` 阶段插入 3 档评分按钮（1=好/2=一般/3=差）；差评点击弹出 reason_tags 多选 Modal（7 项固定枚举：`wrong_template` / `hallucinated_signal` / `syntax_error` / `semantic_error` / `style_bad` / `missing_disable_iff` / `other`）+ 可选 `comment` 文本框（≤ 2048 字符）；任一档提交成功后整组按钮置灰
  - §3.9 `POST /api/v1/feedback/{generation_record_id}`：rating ∈ {1,2,3}（其他 422）、rating=3 必填 reason_tags（否则 422 `reason_tags_required`）；权限 owner-or-admin（普通用户只能评自己的记录，库管理员+ 可补评他人）；成功返 204；写入 `generation_records` 的 4 个 feedback 列 + 回填 `generation_mode='rag'`（若原 NULL）
  - §3.10 新增 4 个 KPI 端点（`/admin/analytics/{feedback-summary, template-issues, intent-confusion, no-match-rate}`），全部要求 `lib_admin` / `super_admin`，`days` 窗 ∈ [1, 90] 默认 7；`intent-confusion` 仅从 `feedback_rating=3 AND template_id != rag_top3[0].template_id` 聚合（视 RAG top-1 为期望模板），`no-match-rate` 按 UTC 日界统计 `gate_error_type='no_matching_template'`
  - §3.10 新建 `AdminAnalyticsPage`（`/admin/analytics`）：KPI 卡片行 + 7 天 NoMatch 趋势折线图（`@ant-design/charts` Line） + 差评模板 top-10 表 + intent confusion 表（每行含「复制为 corpus 条目」按钮，生成 `template_selection_corpus.yaml` 兼容 YAML 块写入剪贴板，闭环回归测试语料）
  - Stage 范围（明确不做）：不发送邮件/Webhook 推送、不实现批量任务行级反馈、不允许用户修改已提交反馈、不实现 CSV 导出、不做 Redis 缓存、不做差评率突增告警（留待 L5）
- v3.2 → v3.3：**FEAT-11 Stage 2 双模生成（rag 默认 + llm_direct 兜底）落地为 in-scope 功能**——
  - §6.1 单条生成主流程新增 **A 子项：高置信 RAG 自动渲染**——当 preview 同时满足 `confidence_source==llm_step1` + `step1_verify_enabled` 且 verify 通过 + `selected_score >= reranker_min_score_threshold` + 所有 required 参数源 ∈ `{llm, regex, signal_list, default}` 四条件时，`pipeline_preview` 把 `quick_render=True` 与 intent_cache 命中路径走同一旗标，前端 `GeneratePage` 跳过 ConfirmationPanel 直接调 `/render` 并展示代码。任一条件未达标仍走原确认面板（无回归）
  - §6.1 result 阶段新增 **B 子项：LLM 直接生成兜底按钮**——`generation_mode === 'rag'` 时显示「对生成结果不满意？尝试 LLM 直接生成」按钮（已为 `llm_direct` 的记录不再展示，禁止链式 fallback）。点击 → `POST /api/v1/generate/llm-fallback {generation_record_id}` → 后端载入源记录的 intent / code_type / signals / clk / rst → 调 `LLMClient.generate_code_freeform` → 返回 `{code, generation_record_id, generation_mode: "llm_direct"}` → 前端替换代码区 + `feedbackSubmitted` 归零，让用户对 `llm_direct` 结果独立评分
  - §6.1 新增 **非确定性标签契约**：`llm_direct` 记录的代码卡片头部强制渲染 `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>`；同一输入再次触发 `llm-fallback` 可能产出不同代码——这是设计内行为，与 `rag` 路径的"字节级确定性"形成对照。原"系统决定产出代码时必为确定"契约（§4.1）**收窄为仅对 `rag` 路径**；`llm_direct` 路径仅在 `gen_llm:*` Redis 7d TTL 缓存命中时呈现"伪确定性"，TTL 过期或切换 LLM 默认配置后即重新生成
  - §6.1 错误模式表新增 `llm_direct_*` 三类错误：`llm_direct_chained_not_allowed`（源记录已是 `llm_direct`→422）/ `llm_direct_no_code`（LLM 返回无围栏代码→422）/ `llm_direct_internal_error`（LLM 调用 / DB 写入失败→422，detail 不泄漏内部 repr）。三类均不带 `redirect_to`——前端显示 `message.error` 文案后停留在 result 页让用户重试或换 LLM
  - §3.9 用户反馈机制扩展：FeedbackBar 现在对 `rag` 与 `llm_direct` 两种 record 都可用，后端写 4 个 feedback 列不再回填 `generation_mode`（因为 `llm_direct` 子记录在写入时已经显式标 `'llm_direct'`，回填只发生在 v3.2 前的老 `'rag' or NULL` 行为，本版本保留 NULL→`'rag'` 防穿透但不再触碰显式值）
  - §3.10 管理员分析仪表盘 4 个 KPI 端点全部新增 optional `generation_mode` query 参数（值 `rag` / `llm_direct`，omit = 全量）：`feedback-summary` 按模式分桶；`template-issues` 在 `generation_mode=llm_direct` 时把 `template_id IS NULL` 行归入 `__llm_direct__` 桶不再被默认 `IS NOT NULL` filter 排除；`intent-confusion` 与 `no-match-rate` 同样支持 filter
  - 数据库：migration 007 `generation_records` 新增 `parent_record_id VARCHAR(36) NULLABLE FK→generation_records.id ondelete=SET NULL` 列，让 `llm_direct` 子记录回链触发本次 fallback 的源 RAG 记录；源记录被删除（admin 操作）仅清空 FK，保留 `llm_direct` 子记录与其反馈数据
  - Stage 范围（明确不做，留待 Stage 3）：批量任务（Celery）不支持 `llm_direct` 模式；L4 仪表盘除 `generation_mode` 过滤参数外暂不做"按模式拆分的图表/趋势"；用户不可在没有源 RAG 记录前提下"冷启动"直接 `llm_direct`；管理员不可从 Admin UI 重触发 `llm_direct`；贡献向导不支持 `llm_direct` 路径；不为 `llm_direct` 结果发邮件/Webhook 推送；不做 `llm_direct` analytics 的 CSV 导出
- v3.3 → v3.4：**FEAT-12 用户对比报告系统**——新增 §6.2「用户对比报告（FEAT-12）」小节（原 §6.2 批量生成顺延为 §6.3），描述用户在 GeneratePage result 阶段对 LLM 直接生成记录一键提交对比报告的完整链路：独立按钮（仅 `generation_mode==='llm_direct' && parent_record_id!=null` 渲染，与 §3.9 L3 差评按钮互相独立）→ Modal（4 项分类 Checkbox.Group + 自由文本 TextArea，**全选填均允许空提交**）→ `POST /api/v1/improvement-reports` → 后端写入新建 `improvement_reports` 表（独立于 `generation_records.feedback_*` 列）。引入分类枚举 `ReportCategoryEnum`（4 项 slug ↔ 中文 label：`wrong_template`/模板选错、`wrong_params`/参数映射错、`poor_style`/代码风格差、`other`/其他），并定义 admin 三态状态机 `pending → in_review → resolved`（详见 ARCH §3.18 / §4.1.4）；已有报告时按钮 disabled 文案"已有人提交对比报告，admin 处理中"。§6.1 错误模式表新增 3 行 `duplicate_report` (409) / `invalid_record_ref` (422) / `illegal_status_transition` (422)，前两条用于 `POST /improvement-reports`，第三条用于 `PATCH /admin/improvement-reports/{id}` 非法状态跳转（如 pending→resolved 跳过 in_review、resolved→pending 倒退），三者均不带 `redirect_to`。§3.9 L3 差评机制与本对比报告系统在 result 阶段并存——前者按记录评质量分（写 `generation_records.feedback_*`），后者按 RAG/LLM 直接生成对比（写 `improvement_reports`），用户可同时使用。**Out of scope（留 FEAT-13）**：resolved 报告语料回流到 `template_corpus_cases`（半自动或自动）、admin CSV 导出、报告邮件/Webhook 推送、admin↔用户对话、跨 admin 认领锁、用户撤回、批量任务行级对比报告
- v3.5 → v3.6：**FEAT-18 批量页删 code_type 下拉 + sheet 自动检测多 code_type**——§3.1.1 两份输入表格描述补"前端不再要求用户在上传前选择 code_type，系统按 Excel 各 sheet 名（`SVA需求` / `Coverage需求`）自动识别每行对应的 code_type"；§3.1.2 处理流程框图"上传表格"步骤追加"系统检视 workbook.sheetnames → CodeTypeRegistry 反查 → 每个匹配 sheet 独立解析；未注册 sheet 名静默跳过；所有已知 sheet 均无有效数据行时返 HTTP 400 detail.type=no_valid_rows"注解；同一份 Excel 中两个 sheet 均填了数据时，系统在一次上传里混合生成两类代码。本版本**不**修改 §6 用户交互流程详述的单条生成 / IntentBuilder / 贡献向导任何文案——code_type 选择动作仅在批量生成页移除，单条生成页仍保留 code_type 选择控件。详细实现层影响（端点签名 / 解析函数 / 前端组件 / 测试覆盖）见 ARCHITECTURE v2.28→v2.29 与 CHANGELOG。
- v3.4 → v3.5：**FEAT-13 模板成熟度门控（maturity_level 三档 + RAG 默认仅召回 production + admin 提升降级 UI）**——
  - §4 数据模型新增：`templates` 表追加 `maturity_level` 列（PostgreSQL ENUM `template_maturity_enum`，值 `production / experimental / draft`，NOT NULL，server_default `'experimental'`），由 Alembic migration 009 加列并 backfill：`id ~ '^(sva|cov)_.+_v[0-9]+$'` 命名规范的官方种子模板升为 `production`，其余行（含 `is_active=false`、含历史 `L6_E2E_*` 测试模板）落 `experimental`。三档语义如下：
    - `production`：经人工核验、**进入 RAG 召回主库**的官方模板；`stage1_hybrid_search` Qdrant Filter + `engine.py` DB 二次过滤 + `dense_top1_score`（off-topic gate / code_type_mismatch gate）三处均**仅**消费此档
    - `experimental`：贡献流通过 admin review 后**默认落到这一档**；模板已可读、可由库管理员维护，但**不参与 RAG 召回**，避免污染主库
    - `draft`：内部测试 / 早期实验位，亦**不参与 RAG 召回**
  - 与既有 `maturity` 列（值 `draft / validated / production`）的区分：`maturity` 描述"开发成熟度"（模板设计者标注的迭代位），`maturity_level` 描述"生产门控"（是否进入 RAG 召回主库）；两列并存、语义独立，**不得混用**——前端 Admin UI、ORM、迁移三处分别引用，不在同一 Form.Item 中编辑
  - §3.6（贡献流权限矩阵）+ §3.7（模板贡献与审核机制）生命周期更新：贡献流 `_create_template_from_contribution` 新建模板时 `maturity_level` 固定为 `'experimental'`（不依赖 contribution 的 `maturity` 字段取值），admin 通过 review 后该模板**仍保持 `experimental`，须 super_admin 显式 PATCH 才能升为 `production` 并进入 RAG 召回主库**。完整生命周期：提交贡献 → admin review 通过 → 默认 `experimental` → super_admin 显式提升 `production` → RAG 召回生效
  - §3.4（模板库管理）Admin UI 扩展：模板表格新增 `maturity_level` 列（带颜色 Tag：`production=green` / `experimental=orange` / `draft=blue`）；行内操作区新增「升级到 production」「降级到 experimental」两个按钮，**仅 `role=='super_admin'` 用户可见可点**（`lib_admin` 隐藏）。后端 `PATCH /api/v1/admin/templates/{id}` 校验：当 payload 含 `maturity_level` 且 `current_user.role != 'super_admin'` 时返 HTTP 403 `detail="仅 super_admin 可修改 maturity_level"`；非法 enum 值返 HTTP 422
  - §3.7.2 / §3.7.3 贡献流明确：用户在 Step 2 编辑 / admin 在三栏审核界面修改的内容**均不影响 `maturity_level`**——批准入库的模板恒以 `experimental` 落库
  - **不在范围内**：自动语料质量评分（`draft → experimental` 自动升级）由 FEAT-14 承接；`production → 退役` 流程留待后续票；前端 Library 页 / Generate 页不展示 `maturity_level`（用户视角对 production-only 召回无感）
  - **风险记录**：`dense_top1_score` 加 maturity Filter 后，off-topic gate 与 code_type_mismatch gate 的阈值可能需重新校准（`OFFTOPIC_DENSE_THRESHOLD` / `CODE_TYPE_MISMATCH_MARGIN`），由 SRE 在上线后跑 `calibrate_offtopic_threshold.py` 验证；Qdrant payload 冷启动须先 `alembic upgrade head` 再 `lib_manager rebuild`，否则现有 points 因缺 `maturity_level` payload 字段会被 stage1 Filter 全部过滤掉 → RAG 召回为空 → 全量 503

---

## 1. 产品概述

### 1.1 背景与动机

IC验证工程师在日常工作中需要大量编写SystemVerilog断言（SVA）和UVM功能覆盖率代码。这类代码具有高度结构化的特点——模式固定，但参数因设计而异。手工编写存在以下问题：

- **效率低下**：重复性工作耗费大量工时
- **风格不统一**：不同工程师编写的断言/覆盖率代码格式差异大，不利于团队协作和代码审查
- **易遗漏**：依赖个人经验，容易遗漏重要的验证点
- **维护困难**：缺乏统一的断言/覆盖率模式库，知识难以沉淀和复用

### 1.2 产品定位

一个面向IC验证工程师团队的**Web端辅助代码生成平台**，通过维护结构化的断言/覆盖率模板库，将工程师填写的结构化需求表格（含信号信息和验证意图）批量转化为统一风格的SVA和UVM功能覆盖率代码。

**输入形式**：两份标准Excel表格——SVA断言需求表和功能覆盖率需求表，分别承载信号信息（信号名、位宽、角色）和验证意图（自然语言描述）。验证意图经RAG检索匹配模板，信号信息直接填充模板参数。

平台采用**代码类型注册表**设计，v1.0 支持 SVA 断言和 UVM 功能覆盖率两种类型；架构允许通过添加配置文件扩展至其他辅助代码类型（如 UVM 激励序列、形式验证属性、约束文件等），无需修改核心系统代码。

### 1.3 核心价值

- **统一风格**：所有生成代码来自同一模板库，团队代码风格一致
- **确定性输出**：相同输入必然产生相同输出，结果可预期、可审计
- **知识沉淀**：模板库是团队验证经验的结构化积累，随时间持续完善
- **效率提升**：大幅减少重复性代码编写工作

---

## 2. 目标用户

| 角色 | 描述 | 主要诉求 |
|------|------|---------|
| **IC验证工程师（普通用户）** | 日常使用平台生成SVA和UVM覆盖率代码 | 快速生成、风格统一、参数准确 |
| **库管理员（高级工程师）** | 维护和扩充模板库，审核模板质量 | 方便地添加/修改模板，保证库的准确性 |
| **平台管理员** | 管理用户账号和权限 | 用户管理、系统配置 |

---

## 3. 功能需求

### 3.1 核心功能：表格驱动的批量代码生成

**描述**：工程师填写标准Excel表格（SVA需求表 或 功能覆盖率需求表），上传后系统逐行解析、RAG匹配模板、批量生成代码。

#### 3.1.1 两份输入表格

平台提供两份固定格式的Excel模板供下载，工程师按需填写：**前端不再要求用户在上传前选择 code_type，系统按 Excel 各 sheet 名（`SVA需求` / `Coverage需求`）自动识别每行对应的 code_type**，详见 §3.1.2 处理流程与 ARCHITECTURE §3.9 解析层；同一份 Excel 中两个 sheet 均填了数据时，系统会在一次上传里混合生成两类代码。

**SVA断言需求表**（每行 = 一条断言需求）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| 编号 | 文本 | 是 | SVA-001，用于结果追踪 |
| 所属模块 | 文本 | 是 | 断言挂载的模块/接口名 |
| 时钟 | 文本 | 是 | 时钟信号名 |
| 复位信号 | 文本 | 是 | 复位信号名 |
| 复位极性 | 枚举 | 是 | 高有效 / 低有效 |
| 协议 | 枚举 | 否 | AXI4 / AHB / APB / 通用，辅助RAG过滤 |
| 信号1名称 | 文本 | 是 | — |
| 信号1位宽 | 整数 | 是 | bit |
| 信号1角色 | 枚举 | 是 | valid / ready / data / state / req / ack / start / end / enable / count / other |
| 信号2名称 | 文本 | 否 | — |
| 信号2位宽 | 整数 | 否 | — |
| 信号2角色 | 枚举 | 否 | 同上 |
| 信号3名称 | 文本 | 否 | — |
| 信号3位宽 | 整数 | 否 | — |
| 信号3角色 | 枚举 | 否 | 同上 |
| 信号4名称 | 文本 | 否 | — |
| 信号4位宽 | 整数 | 否 | — |
| 信号4角色 | 枚举 | 否 | 同上 |
| 验证意图 | 长文本 | 是 | 自然语言描述，驱动RAG检索匹配模板 |
| 严重级别 | 枚举 | 否 | error / warning / info（默认error） |
| 备注 | 文本 | 否 | 可选补充说明 |
| **[输出]匹配模板** | 文本 | — | 系统回填，如 SVA-HAND-001 |
| **[输出]置信度** | 数字 | — | 系统回填，如 0.95 |
| **[输出]生成状态** | 枚举 | — | 系统回填：已生成 / 需确认 / 需修改 |

**功能覆盖率需求表**（每行 = 一个covergroup需求）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| 编号 | 文本 | 是 | COV-001，用于结果追踪 |
| 所属模块 | 文本 | 是 | covergroup挂载的模块/接口名 |
| 采样时钟 | 文本 | 是 | 采样时钟信号名 |
| 复位信号 | 文本 | 是 | 复位信号名 |
| 复位极性 | 枚举 | 是 | 高有效 / 低有效 |
| 覆盖类型 | 枚举 | 否 | 值覆盖 / 转移覆盖 / 交叉覆盖，辅助RAG过滤 |
| 主信号名称 | 文本 | 是 | 主要覆盖信号名 |
| 主信号位宽 | 整数 | 是 | bit |
| 主信号数据类型 | 枚举 | 是 | logic / uint / enum |
| 交叉信号1名称 | 文本 | 否 | 交叉覆盖时填写 |
| 交叉信号1位宽 | 整数 | 否 | — |
| 交叉信号1数据类型 | 枚举 | 否 | logic / uint / enum |
| 交叉信号2名称 | 文本 | 否 | 三维交叉时填写 |
| 交叉信号2位宽 | 整数 | 否 | — |
| 交叉信号2数据类型 | 枚举 | 否 | logic / uint / enum |
| Bin提示 | 文本 | 否 | 期望分段，如 `1,2,4,8,16` 或 `0-15,16-255` |
| 采样条件 | 文本 | 否 | 采样触发条件，留空则时钟沿采样 |
| 覆盖意图 | 长文本 | 是 | 自然语言描述，驱动RAG检索匹配模板 |
| 备注 | 文本 | 否 | 可选补充说明 |
| **[输出]匹配模板** | 文本 | — | 系统回填，如 COV-VAL-001 |
| **[输出]置信度** | 数字 | — | 系统回填，如 0.92 |
| **[输出]生成状态** | 枚举 | — | 系统回填：已生成 / 需确认 / 需修改 |

#### 3.1.2 处理流程

```
工程师下载标准Excel模板 → 填写需求行（可选：使用场景构建器辅助填写）
  ↓
上传表格（系统检视 workbook.sheetnames → CodeTypeRegistry 反查 → 每个匹配 sheet 独立解析为 code_type 已知的行；
         未注册的 sheet 名静默跳过；所有已知 sheet 均无有效数据行时返 HTTP 400 detail.type=no_valid_rows）
  ↓
【前置信度预检】（见 §3.8 第三层）
  系统快速扫描所有行，展示逐行预估置信度
  低置信度行高亮，提供 AI 改写建议
  工程师确认/修改后继续
  ↓
系统逐行解析（Celery并行）
  ↓
每行：验证意图 →【LLM标准化】（见 §3.8 第一层）→ bge-m3向量化
      → Qdrant RAG检索（含协议/类型过滤）
      → Top-3候选 → reranker精排 → LLM选模板（工具调用）
      → 信号角色表直接填充模板参数 → Jinja2渲染
  ↓
结果回填到Excel原表（输出列）+ Web端展示进度与结果列表
  ↓
[置信度 > 85%]  自动完成，结果标绿
[置信度 50-85%] 标黄，工程师在Web端逐条确认模板选择
[置信度 < 50%]  标红，展示最近似模板，标注需人工修改处；同时展示「贡献新模板」入口
  ↓
下载生成结果
```

#### 3.1.3 信号角色的作用

表格中每个信号明确标注"角色"（valid/ready/data/state等），在RAG匹配到模板后，系统直接将信号名填入模板对应参数位置，**无需LLM猜测信号角色**，参数填充完全确定性。

Claude（LLM）在此流程中仅做一件事：从Top-3候选模板中选择最匹配的一个，并确认角色与模板参数的对应关系。

#### 3.1.4 结果查看与操作

- Web端展示完整结果列表（含每行状态、置信度、匹配模板ID）
- 点击任意行可展开查看生成代码，支持参数面板实时编辑重渲染
- 下载选项：全部下载 / 仅下载高置信度项 / 下载含结果的Excel表格

---

### 3.2 模板库下载

工程师可从平台下载两份标准Excel模板文件：
- `sva_requirements_template.xlsx`：SVA断言需求表（含示范行）
- `coverage_requirements_template.xlsx`：功能覆盖率需求表（含示范行）

模板文件包含枚举字段的下拉约束，输出列灰色只读，工程师直接在模板上填写需求行后上传。

---

### 3.3 模板库浏览与查询

**描述**：用户可浏览和搜索平台维护的断言/覆盖率模板库，了解库中现有的模板。

**功能点**：
- 按分类树浏览（断言/覆盖率 → 子类型 → 协议）
- 关键词搜索（支持中英文）
- 按协议筛选（AXI4、AHB、APB等）
- 查看模板详情（描述、参数列表、代码预览、相关模板）
- 直接从模板详情页进入生成流程（预填参数）

---

### 3.4 模板库管理（库管理员）

**描述**：库管理员通过Admin界面维护模板库内容。

**功能点**：

| 操作 | 描述 |
|------|------|
| 新建模板 | 填写模板元数据（名称、分类、标签、协议）和参数定义，编写Jinja2代码模板 |
| 编辑模板 | 修改现有模板的任意字段 |
| 版本管理 | 每次修改自动记录版本历史，支持回滚 |
| 模板验证 | 保存时自动做语法检查和参数渲染测试 |
| 停用/启用 | 下线不再适用的模板（不删除，保留历史） |
| 关联模板 | 设置模板间的关联关系（互补模板、推荐组合） |
| 批量导入 | 通过YAML文件批量导入模板；支持 `--dry-run` 预检模式，正式写入前完整预览变更 |
| **查重检测** | 新建/导入模板时自动执行名称精确匹配 + 语义相似度检查；发现相似模板（≥ 90%）时展示告警，管理员可查看相似模板后决定是否继续入库 |
| **导入预检（Dry-Run）** | 批量导入 YAML 前可先执行 `--dry-run` 预检，展示待新增/待跳过/校验失败的条目明细，不执行任何写入，确认无误后再正式导入 |
| **操作审计日志** | Admin UI 提供管理员操作历史查看页面，展示模板变更、贡献审核、导入操作的完整审计轨迹（操作人、时间、变更前后内容） |
| **审核贡献** | 审核工程师提交的模板贡献，可编辑后批准入库或退回（见 §3.7） |

**模板元数据字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| ID | 字符串 | 唯一标识，格式如 `SVA-HAND-001` |
| 名称 | 字符串 | 简短描述性名称 |
| 类别 | 枚举 | `断言` / `覆盖率` |
| 子类别 | 枚举 | 见分类体系 |
| 适用协议 | 多选 | AXI4、AHB、APB、通用等 |
| 标签/关键词 | 标签列表 | 中英文均可，用于搜索匹配 |
| 描述 | 文本 | 详细说明模板的用途和适用场景 |
| 参数定义 | 结构化列表 | 每个参数的名称、类型、是否必填、默认值 |
| 代码模板 | Jinja2文本 | 实际代码模板 |
| 成熟度 | 枚举 | `草稿` / `已验证` / `生产` |
| 关联模板 | ID列表 | 相关/推荐组合的模板ID |

---

### 3.5 LLM 模型配置管理（平台管理员）

**描述**：平台管理员可在 Admin 界面配置多个 LLM 模型，支持通过 URL + API Key 接入第三方模型（DeepSeek、Qwen、本地 vLLM 部署等），并可对每个模型执行连通性和能力测试。

#### 3.5.1 模型配置管理

| 操作 | 说明 |
|------|------|
| 新增模型配置 | 填写名称、Provider 类型、Base URL、API Key、Model ID、输出模式 |
| 编辑配置 | 可修改所有字段；API Key 留空则保留原值（不覆盖） |
| 删除配置 | 不能删除当前默认模型 |
| 设为默认 | 将指定模型设为系统默认，全平台 LLM 调用切换至该模型 |
| 启用/禁用 | 禁用后不影响其他配置，不会被 factory 选中 |

**模型配置字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| 名称 | 文本 | 显示名称，如 `智谱大模型`、`DeepSeek-V3`、`本地Qwen2.5` |
| Provider | 枚举 | `Anthropic 原生` / `OpenAI 兼容` |
| Base URL | URL | API 地址；Anthropic 原生可留空使用默认；OpenAI 兼容常用：智谱 `https://open.bigmodel.cn/api/paas/v4/`、DeepSeek `https://api.deepseek.com/v1`、Ollama `http://host.docker.internal:11434/v1` |
| API Key | 密码框 | 加密存储，界面只展示前4位掩码 |
| Model ID | 文本 | 模型标识，如 `glm-4.7`、`deepseek-chat`、`claude-sonnet-4-6` |
| 输出模式 | 枚举 | `工具调用（Tool Calling）` / `JSON Mode` / `Prompt JSON`，决定结构化输出策略；OpenAI 兼容路径当前固定走两步纯文本以兼容 thinking 模型 |
| Temperature | 数字 | 默认 0.0（确定性约束） |
| Max Tokens | 整数 | 仅作为该模型默认 `max_tokens` 透出；实际 OpenAI 兼容路径按调用分档（normalize=512、step1=64、step2=2048/1024，详见 ARCHITECTURE §3.12.2） |
| Step2 禁用 thinking | 开关 | 仅 OpenAI 兼容 Provider 显示，默认开启。开启时 `_step2_fill_params` 调用注入 `extra_body={"thinking":{"type":"disabled"}}`，GLM-4.7 实测从 12-249s 降至 ~3s。关闭后保留模型推理能力，用于 FSM `state_list` / `bins_expr` 等复杂参数填充能力对照（详见 ARCHITECTURE §3.12.2） |

**Provider 说明**：

- **Anthropic 原生**：使用 Anthropic Python SDK，支持原生 Tool Calling，结构化输出最可靠
- **OpenAI 兼容**：使用 `openai` SDK 的 `base_url` 参数，覆盖 智谱 GLM、DeepSeek、Qwen、Ollama、vLLM 等所有兼容实现；本地部署的 Ollama 在 Docker 网络中通过 `host.docker.internal` 访问宿主机端口

#### 3.5.2 模型测试功能

**描述**：配置完成后，管理员可对任意模型执行三类测试，在正式切换前验证模型可用性。

| 测试类型 | 测试内容 | 通过条件 |
|---------|---------|---------|
| 基础连通 | 发送 `"Hello"` 消息，验证 API 可达性和鉴权 | 收到任意非错误响应 |
| 意图标准化 | 发送固定测试意图，验证输出格式 | 返回文本符合 `"当...时，...必须..."` 句式 |
| 模板选择 | 发送含 2 个虚拟模板的 RAG Prompt，验证 JSON 结构 | 输出可被 Pydantic Schema 解析 |

**测试结果展示**：

```
[基础连通]  ✓ 连通正常   耗时 1240ms
[意图标准化] ✓ 格式正常   输出预览："当 awvalid 有效且..."
[模板选择]  ✓ JSON有效   解析结果：{ template_id: "SVA-HAND-001", confidence: 0.95 }
```

失败时展示具体错误信息（HTTP 状态码、超时、JSON 解析失败原因等），方便排查配置错误。

---

### 3.6 用户与权限管理（平台管理员）

**账号开通方式**：登录页提供"注册"标签页，任何访客都可填写用户名 + 邮箱 + 密码自助注册。新账号默认角色为**普通用户**，可立即登录使用单条/批量生成、模板浏览、模板贡献等普通用户功能；如需库管理员或平台管理员权限，由平台管理员在用户管理页面手动升级。

**角色与权限矩阵**：

| 操作 | 普通用户 | 库管理员 | 平台管理员 |
|------|---------|---------|-----------|
| 生成代码（单条/批量） | ✓ | ✓ | ✓ |
| 浏览模板库 | ✓ | ✓ | ✓ |
| 提交模板贡献 | ✓ | ✓ | ✓ |
| 查看我的贡献列表 | ✓ | ✓ | ✓ |
| 新建/编辑模板 | ✗ | ✓ | ✓ |
| 停用模板 | ✗ | ✓ | ✓ |
| 批量导入模板 | ✗ | ✓ | ✓ |
| 审核/批准/退回贡献 | ✗ | ✓ | ✓ |
| 管理 LLM 模型配置 | ✗ | ✗ | ✓ |
| 执行模型测试 | ✗ | ✗ | ✓ |
| 管理用户账号 | ✗ | ✗ | ✓ |
| 分配/修改角色 | ✗ | ✗ | ✓ |
| 查看系统使用统计 | ✗ | ✗ | ✓ |

---

### 3.7 模板贡献与审核机制

**背景**：平台初期模板库规模有限，库里没有的验证场景会频繁出现。工程师手动改完代码后，知识无法沉淀回库。本功能为此类场景建立从"未匹配"到"入库"的完整闭环。

**v3.0 设计原则**：普通工程师对模板数据库格式（YAML schema、Jinja2 占位符、`expr_type` 字段）不熟悉，强制他们手填这些字段会造成贡献门槛过高、退回率高、知识沉淀低。v3.0 把"格式化模板"的脏活全部移到后端 LLM + 审核员手里，工程师只负责描述**问题本身**与**真实的代码示例**。

---

#### 3.7.1 贡献触发入口

入口有三个：

1. **批量生成结果列表**：低置信度（< 50%）行旁的「贡献新模板」按钮（沿用 v1）
2. **IntentBuilder N 轮对话仍无匹配**（v3.0 新增）：意图构建器（§3.8）在 N=5 轮后仍无 RAG 候选能对齐时，自动展示「我们的库里似乎还没这个，要不要贡献？」入口，prefill 已经标准化的 description
3. **顶部导航 → 我的贡献页 → 「+ 新贡献」按钮**（直接入口）

---

#### 3.7.2 贡献向导（v3.1 两步式 Modal，2 字段必填）

点击「贡献新模板」打开两步 Modal（Ant Design Steps），用户**只需必填 2 个字段**：

**Step 1 — 输入验证意图**

| 字段 | 说明 | 必填 |
|------|------|------|
| `original_intent` | 自然语言描述你要验证的场景（4 行 TextArea），如"检测 AXI 写通道在 awvalid 拉高到 awready 到来期间地址保持稳定" | ✓ |
| `code_type` | 单选：SVA 断言 / UVM 覆盖率 | ✓ |

点「生成预览」→ 前端调 `POST /api/v1/contributions/preview`（不入库，仅返回 LLM 生成结果），后端同步跑 LLM + 3 道校验（5-15s），成功进入 Step 2。

**Step 2 — 预览编辑与提交**

LLM 生成的 5 字段在 Step 2 中展示为**可编辑表单**：

| 字段 | 控件 | 来源 | 用户能改？ |
|------|------|------|----------|
| `template_name` | Input | LLM 按 `^(sva|cov)_[a-z][a-z0-9_]*_v\d+$` 规范生成 | ✅ |
| `description` | TextArea（3 行） | LLM 按标准 IC 验证措辞生成 | ✅ |
| `demo_code` | TextArea（12 行 monospace） | LLM 生成的完整 SVA/UVM 代码（含真实信号名） | ✅ |
| `parameter_defs` | （隐藏） | LLM 反推参数定义；用户不直接看 | — |
| `keywords` | （隐藏） | LLM 推测；用户不直接看 | — |

若预览响应中 `name_conflict: true`，Step 2 顶部显示黄色 Warning Alert："此名称与现有模板重名，请修改 `template_name` 后再提交"。

底部两个动作按钮：

- **提交审核**：调 `POST /api/v1/contributions`（携带 Step 2 中用户最终确认/编辑后的 5 字段），状态入 `pending_review` 进审核队列；Modal 关闭，刷新列表
- **立即使用**：同样调 `POST /api/v1/contributions` 入审核队列，但**不关闭 Modal**——Step 2 页面内展示可复制代码框（`<pre>` monospace 块 + 「复制代码」按钮 + 提示文案"代码已就绪，可直接复制使用。模板已提交审核，审核通过后将加入模板库。"）。**不跳转 `/generate`** —— 该贡献处于 `pending_review` 不在 Qdrant 中，跳过去只会触发第五道闸 `no_matching_template` 进入循环

**不需要填**：~~参数定义表单~~ / ~~占位符映射~~ / ~~分类下拉~~ / ~~协议下拉~~ / ~~关键词~~ / ~~模板名称~~ / ~~场景描述~~ / ~~代码示例~~——全部由后端 LLM 一次性生成；用户负责语义级校对。

**向后兼容**：原 4 字段提交路径（caller 同时显式传 `template_name + description + demo_code`）仍受支持——`POST /api/v1/contributions` 按 3 个分支选择路径：(1) 缺关键字段触发 intent-only 生成；(2) 显式传 `parameter_defs` 走 v2 批量路径不调 LLM；(3) 4 字段齐全走原 demo 反推路径。

---

#### 3.7.3 后端 LLM 生成流程（preview / submit 两端共用）

`generate_from_intent(original_intent, code_type, llm)` 同步完成（耗时预估 5-15s），preview 与 submit（分支 1）端点共用：

1. **LLM 一次性生成 5 字段**（沿用 `llm_configs.is_default`）：
   - System prompt 喂模板库已有 schema 风格 + 命名规范（`sva_<scenario>_v<N>` / `cov_<scenario>_v<N>`）作为约束
   - User prompt = `original_intent + code_type`
   - 输出：(a) `template_name`、(b) `description`、(c) `demo_code`（含真实信号名 / 字面量的完整 SV 代码），(d) `parameters` JSON（含 name / type / required / description / expr_type / role_hint / default），(e) `jinja_body`（用 `{{ param }}` 占位真实信号的 Jinja2 模板），(f) `keywords` / `subcategory` / `protocol`
2. **自动校验**（4 道，任一失败回 422 `contribution_parse_failed`，`detail` 含 `stage` + `reason`）：
   - `_validate_template_name`：必须匹配 `^(sva|cov)_[a-z][a-z0-9_]*_v\d+$`（`stage="template_name"`）
   - `_validate_parameter_defs`：每项含 `name/type/required/description/expr_type`，name 是合法 SV 标识符，`expr_type ∈ {sv_identifier, sv_identifier_list, sv_boolean_expr, sv_bins_expr, integer, free_text}`（`stage ∈ {param_defs_shape, param_defs_empty, param_defs_name, param_defs_expr_type}`）
   - `_validate_jinja_rendering`：Jinja2 用占位值跑 `SandboxedEnvironment` + `StrictUndefined` 渲染通过（`stage ∈ {jinja_empty, jinja_syntax, jinja_sandbox (SSTI/不安全操作), jinja_render (StrictUndefined / 参数引用失败)}`）
   - `_validate_keywords`：必须是 `list[str]`，自动去重 / 过滤空串；非 list 即拒（`stage="keywords_shape"`）
3. **`name_conflict` 检测**（preview 端点专属，非阻塞）：跑 `check_name_duplicate`，命中已入库模板时响应携带 `name_conflict: true`；submit 端点遇重名仍 422 `contribution_name_duplicate` 阻塞
4. **dedup 预扫**（submit 端点）：用 description 跑一次语义查重（沿用 `check_semantic_duplicate`，阈值 0.90），命中已有模板时把"相似模板列表"塞 `original_row_json["similar_templates"]` 供审核员对比；查重失败（Qdrant 暂时不可达等）非阻塞
5. submit 全部通过 → 状态 `pending_review`，进入审核队列

错误情况下用户**不会**看到中间产物——只看到"你的描述太模糊 / LLM 生成的代码无法参数化"的友好提示，用户可改 Step 1 的 `original_intent` 重新生成预览。

**双层审核机制**：

- **第一层（用户验证 LLM 输出）**：Step 2 预览页就是用户对 LLM 生成质量的把关——任何不准确的命名、措辞或代码细节，用户可在 Step 2 直接改后再提交；这是 v3.1 把"参数化脏活推给 LLM"后增加的关键反馈环
- **第二层（管理员审批入库）**：与 §3.7.5 既有三栏审核完全一致，审核员对左/中/右栏任意修改后批准触发 §3.10.2 入库流水线

#### 3.7.4 我的贡献（普通用户）

入口：顶部导航栏 →「我的贡献」页面

列表展示所有本人提交的贡献记录：

| 列 | 说明 |
|----|------|
| 模板名称 | 提交的名称 |
| 类型 | SVA / Coverage |
| 提交时间 | — |
| 状态 | 待审核 / 审核中 / 需修改 / 已入库 / 已退回 |
| 操作 | 待审核→可撤回；需修改→可编辑重提；已入库→查看模板详情 |

- **已退回 / 需修改**：展示审核意见，工程师修改后可重新提交
- **已入库**：显示系统分配的模板 ID（如 `SVA-HAND-047`），可点击跳转模板详情页

#### 3.7.5 贡献审核（库管理员，v3.0 三栏对比布局）

入口：Admin 后台 →「贡献审核」页面（顶部导航栏显示待审核数量角标）

**审核队列**：

- 默认展示状态为"待审核"的贡献，支持按状态/类型/时间筛选
- 列表显示：模板名称、贡献者、提交时间、代码类型、状态

**审核详情面板**（v3.0 三栏对比布局）：

| 区域 | 内容 | 可编辑？ |
|------|------|---------|
| 左栏：用户提交 | 用户原始代码示例（含真实信号名），description，name，code_type | 否（只读，便于审核员看懂原始意图） |
| 中栏：LLM 反推模板 | `template_body`（Jinja2 占位过的版本）+ Monaco Editor SV 高亮 | **是**，审核员可直接改 Jinja2 模板 |
| 右栏：LLM 反推元数据 | `parameters` JSON / `keywords` / `subcategory` / `protocol`，每个 parameters 项展开为表单 | **是**，逐项可改 |
| 顶部横栏：查重结果 | 提交时 dedup 扫的语义相似度 Top-3；相似度 ≥ 90% 黄色警告，点击跳转对比；无重复绿色"无相似模板" | — |
| 底部操作栏 | 「批准并入库」「请求修改」「退回」 | — |

**操作说明**：

| 操作 | 说明 |
|------|------|
| 批准并入库 | 取中栏 + 右栏当前内容（含审核员的修改）触发模板创建流水线（再跑一次 Jinja2 验证→向量化→写 Qdrant + PostgreSQL），系统自动分配模板 ID。**v3.5 / FEAT-13 起**：入库时 `maturity_level` 固定为 `'experimental'`（即使审核员在中/右栏改过 `maturity` 字段亦不影响 `maturity_level`），模板**暂不进入 RAG 召回主库**，须 super_admin 在「模板库管理」页显式点「升级到 production」后方生效 |
| 请求修改 | 必填审核意见，贡献者收到通知后可重新编辑提交（v3.1：贡献者只能在两步 Modal 中改 `original_intent + code_type` 后重新走预览/编辑流程，重提会重新跑 LLM 生成；审核员对中右栏的旧手改在重提后丢弃，避免新旧产物错配） |
| 退回 | 必填退回原因，记录归档，状态标为已退回 |

**v3.0 不做**：审核员与 LLM 的多轮对话（"AI 这个 parameters 拆得不对，再来一遍"）—— 后续议题。当前若 LLM 反推质量不好，审核员直接手改中/右栏即可。

**v3.5 / FEAT-13 — 模板成熟度门控生命周期补充**：贡献流通过 review 不再意味着"立即上 RAG 召回主库"。完整生命周期：

```
用户提交贡献 → admin review → 通过 → 模板入库（maturity_level='experimental'）
                                     ↓
                              super_admin 在「模板库管理」页显式
                              点「升级到 production」 → maturity_level='production'
                                     ↓
                              进入 RAG stage1 召回主库（Qdrant Filter 通过）
                                     ↓
                              后续生成请求开始命中本模板
```

设计原则："通过 admin review" 是"质量门"（模板写法合规、Jinja2 可渲染、参数定义合理），"super_admin 提升 production" 是"召回门"（确认本模板适合作为团队级官方模板纳入主库）。两道门解耦后，库管理员可以放心批准"看起来对但还需观察"的贡献，不必担心未经充分核验的模板立即影响所有用户的生成结果。`maturity_level='experimental'` 的模板仍可在「模板库」页被浏览、被库管理员维护，仅**不参与 RAG 召回**。

#### 3.7.6 通知机制

- 批准入库后：贡献者收到站内通知「您贡献的模板 SVA-HAND-047 已入库，可在模板库中查看」
- 被退回/请求修改后：贡献者收到通知及审核意见
- 顶部导航栏显示未读通知数量，点击展开通知列表（轮询更新，无需实时推送）

---

### 3.8 意图构建器（IntentBuilder）—— v3.0 重写

**背景**：v2 之前，验证意图标准化由四层机制承担——服务端 LLM 静默改写 + 可选场景构建器 + 上传预检 + 历史知识库。v3.0 的契约反转使前三层的"我替你猜你想说什么"角色不再合时宜：**平台不再为开放性自然语言兜底**。当意图不够明确（off-topic / code_type_mismatch 之外的所有歧义情况）时，统一引导用户进入意图构建器（IntentBuilder）做**RAG-grounded 多轮对话**，最终输出与库内已有模板对齐的标准化句子；若 N 轮后仍无候选能对齐，引导跳转贡献机制（§3.7）。

**用户旅程**：

```
用户输入 NL → POST /preview
        ↓
  [闸 1]  off-topic        → 422，弹"非验证请求"Modal，停留生成页
  [闸 2]  code_type 错配   → 422，弹"切换 code_type"Modal，停留生成页
  [闸 3]  RAG 空 (基础设施)→ 503，弹"系统暂不可用"，停留生成页
  [闸 4]  必填参数缺高置信 → 422 with detail.redirect_to=/intent-builder?...
                          → 前端无脑 router.push，进入 IntentBuilder
        ↓ 全部通过
  RAG 三阶段 + LLM step1/2 → 渲染代码（与 v2.13 同）
```

进入 IntentBuilder 后，目标只有一个：**让用户的描述与库内某个模板对齐**。

---

#### 3.8.1 多轮 RAG-grounded 对话

入口：通过 §6.1 错误模式 `redirect_to` 跳转 / 顶部导航栏「意图构建器」直接入口 / §3.7 贡献页"先在意图构建器看看现有模板"按钮。

**对话引擎逻辑**（沿用 `llm_configs.is_default` LLM）：

1. **会话初始化**：用户的 prefill intent + missing_params（从 redirect URL 获取）作为首轮 user message。
2. **每轮 LLM 调用前**，后端自动跑一次 RAG 检索（用最新累积意图做 query），把 top-3 模板的 `{name, description, parameters[name+description]}` 注入 system prompt 作为"当前可对齐候选"。
3. LLM **system prompt 核心约束**：
   - 你只能从下面给出的候选模板里选一个引导用户对齐，**不要发明新场景**
   - 如果候选都不像，明确说"我们的库里似乎没有匹配的"，并问用户是否要贡献新模板
   - 引导用户**逐个补足**候选模板的必填参数，一次问一个，问完确认
   - 输出格式：人话引导 + 末尾固定段 `<<intent>>...<<end>>` 包裹当前累积的标准化意图（前端解析这段做"试运行"按钮的 prefill）
4. 用户回复 → 添加到 history → 跑下一轮（含新 RAG 检索）
5. **退出条件**（任一）：
   - 用户点击「用这条意图回去生成」→ 跳转 GeneratePage with prefill
   - 用户点击「这些都不对，我要贡献新模板」→ 跳转 §3.7 贡献页，prefill 已积累的 description
   - 达到 **5 轮对话上限** 仍无候选高置信→ 弹"我们的库似乎不覆盖这个场景"提示 + 贡献入口
   - 用户主动关闭会话

#### 3.8.2 会话状态存储

| 维度 | 选择 | 理由 |
|---|---|---|
| 存储 | Redis | 多轮对话本质 ephemeral，写 PG 会污染表 |
| Key | `intent_builder_session:{user_id}:{session_id}` | 按用户隔离 |
| Value | JSON 序列化的 `messages: [{role, content, rag_candidates_snapshot?}]` 列表 | role ∈ `system` / `user` / `assistant` |
| TTL | 24 小时 | 超时即删；用户回头开新会话不复用 |
| 鉴权 | 必须 JWT，未登录禁用 | 与 GeneratePage 同标准 |

**不写 PG**——若未来产品需要"恢复 N 天前的会话"再补，目前 24h 内的 Redis 足够。

#### 3.8.3 normalize_intent 的新角色（v3.0 降级）

LLM 静默标准化（旧 §3.8 第一层）**保留但角色降级**：

- **旧角色（兜底翻译）**：把 NL 改写成规范句式，弥补用户描述差异 → v3.0 否定。
- **新角色（缓存键一致性 + 弃权信号）**：
  - 同一意图的不同写法经 normalize 后产出同一份 hash，是 intent_cache 命中的基础——这条不可去
  - normalize 的 sentinel "如果无法判断类型，输出原文" **保留**，但不再代表"兜底完成"，仅作为"LLM 弃权"的载体；下游 under_specified 闸照常拦
- **关键约束**：normalize 的 system prompt 明文写死"**不允许**填空、扩写、推断信号名/状态"——只做同义改写，不做创造性补全
- 实现位置：`backend/app/services/intent/normalizer.py`，与 v2 同；prompt 改写

#### 3.8.4 退役的旧机制

以下旧 §3.8 子层在 v3.0 退役（功能由 IntentBuilder 接管）：

| 旧机制 | 命运 |
|---|---|
| 第二层"场景构建器（结构化句子组装表单）" | **退役**。IntentBuilder 的对话式引导覆盖此场景，且对话方式比"选场景下拉 + 填空"更灵活；v3.0 直接删除场景构建器 UI 与 `/intent-builder` 旧端点的表单逻辑（若有），改为对话式 |
| 第三层"上传前置信度预检"（批量生成专用） | **保留但缩水**：仅显示低置信度行的"最近似模板"，**不再**引导逐行修改；批量场景下"低质量行"由 v3.0 的 under_specified 闸在逐行 `run_pipeline` 时 422，前端把这些行标红展示，用户选择"逐行跳转 IntentBuilder 改进"或"整批跳过" |
| 第四层"历史意图知识库（intent_cache）" | **保留**。这是缓存层，与 v3.0 契约无冲突；继续以 `intent_cache:{cfg_id}:{intent_hash}` 形式存 30d TTL（已在 v2.13 落地） |

---

#### 3.8.5 RAG 注入 prompt 优先级

回应"大模型辅助生成的表达式是否要优先参考数据库"的设计原则：

**强制 RAG 优先**——IntentBuilder 的 LLM 不被允许凭空想象任何场景，每轮都必须先看库内候选。原因：
1. 否则 LLM 会引导用户产出"看起来标准但库里没有任何模板能渲染"的句子——用户走出 IntentBuilder 又被 RAG empty / under_specified 打回来
2. 让 IntentBuilder 既是"意图标准化器"也是"模板发现器"——对库里有的需求几乎不会走到贡献路径
3. 对库里**没有**的需求自然显式化（LLM 会明说"候选都不像"），引导用户去 §3.7 贡献

---

### 3.9 用户反馈机制（L3）

**背景**：v3.0 之前，平台只在管理员侧收集"贡献被采纳"这一种正向信号；普通用户对每次生成结果的质量判断（"这条对/这条错"）没有结构化采集渠道，模板库优化只能靠管理员主观采样。L3 把"质量信号"沉淀到 `generation_records` 表，**为 §3.10 分析仪表盘提供原始数据**。

#### 3.9.1 3 档评分按钮

GeneratePage 在 `result` 阶段（生成代码渲染完成后）于代码卡片下方插入反馈条，3 个按钮一字排开：

| 按钮 | rating 值 | 交互 |
|---|---|---|
| 👍 好评 | 1 | 单击即提交，无 Modal |
| 😐 一般 | 2 | 单击即提交，无 Modal |
| 👎 差评 | 3 | 单击弹差评 Modal（见 §3.9.2），Modal 内 Submit 才提交 |

提交成功后整组按钮置灰（`feedbackSubmitted=true`），右侧显示"已提交反馈"文字；同一 `generation_record_id` 只允许评一次。重新发起一次新生成后 `feedbackSubmitted` 归零。

#### 3.9.2 差评 Modal（reason_tags + comment）

差评必须至少选 1 个 `reason_tag`（前端 `Checkbox.Group` + 不选则 Submit 按钮触发 `message.warning('请至少选择一个差评原因')`，不发请求）。固定 7 项枚举（Stage 1 不允许用户自定义，新增需走 §CONTRIBUTING.md 流程）：

| 枚举值 | 中文标签 |
|---|---|
| `wrong_template` | 模板选错 |
| `hallucinated_signal` | 幻觉信号名 |
| `syntax_error` | 语法错误 |
| `semantic_error` | 语义错误 |
| `style_bad` | 风格不佳 |
| `missing_disable_iff` | 缺少 disable iff |
| `other` | 其他 |

Modal 内还有可选 `comment` 文本框（≤ 2048 字符），允许用户描述具体问题。`comment` 在所有评分档位都可填（不限于差评）。

#### 3.9.3 提交契约

| 维度 | 值 |
|---|---|
| 端点 | `POST /api/v1/feedback/{generation_record_id}` |
| 权限 | JWT 登录用户；普通用户只能给**自己**的 `generation_record` 评分；`lib_admin` / `super_admin` 可补评他人记录（兜底审核场景） |
| 成功响应 | HTTP 204 No Content |
| 失败响应 | 422（rating 非 1/2/3、rating=3 但 reason_tags 空）/ 403（user_id 不匹配且非 admin）/ 404（generation_record 不存在） |
| 写入字段 | `generation_records.feedback_rating` / `feedback_reason_tags`（JSONB 数组）/ `feedback_comment` / `feedback_at`（UTC 时间）；若原记录 `generation_mode` 为 NULL 则回填 `'rag'`（防 batch 老记录穿透）；显式 `'rag'` / `'llm_direct'` 值**不**回写。**适用范围（v3.3 / FEAT-11 起）**：FeedbackBar 对 `rag` 与 `llm_direct` 两种 record 都可用——前端按 `generation_record_id` 独立 lock，触发一次 `llm-fallback` 后产生新 record，`feedbackSubmitted` 归零让用户重新评分 `llm_direct` 结果 |

**Stage 范围（明确不做）**：
- 不做反馈数据的邮件 / Webhook 推送（仅入库）
- 不做好评/一般评分触发任何自动流程（仅存储）
- 不实现批量任务行级反馈（仅单条生成路径）
- 不允许用户修改已提交的反馈（如需修改让 admin 走 PATCH）

**与 §6.2 用户对比报告的边界（v3.4 / FEAT-12）**：L3 差评针对单条记录的质量打分，写入 `generation_records.feedback_*` 4 列；§6.2 用户对比报告针对成对（RAG 源 + LLM 直接生成子记录）的差异提交，写入独立的 `improvement_reports` 表（详见 §6.2 与 ARCH §4.1.4）。两者在 result 阶段并存（FeedbackBar + 「提交对比报告」按钮各自独立锁定），允许同一对记录同时存在差评与对比报告。L4 仪表盘（§3.10）暂不消费 `improvement_reports` 数据，仅依赖 L3 反馈。

---

### 3.10 管理员分析仪表盘（L4）

**背景**：库管理员需要从"高频差评模板 / NoMatchingTemplate 趋势 / 意图-模板混淆热点"三个维度发现要修复的模板，**让模板库改进有数据驱动**。L4 把 §3.9 用户反馈、`generate.py` 5 道闸触发事件、`rag_top3` 候选日志聚合为 4 个 KPI 端点，前端 `/admin/analytics` 一站式呈现。

#### 3.10.1 4 个 KPI 端点

全部要求 `lib_admin` / `super_admin`；时间窗 `days` 默认 7、上限 90（防全表扫）。

**v3.3 / FEAT-11 起**：4 个端点全部新增 optional `generation_mode` query 参数（值 `rag` / `llm_direct`，omit = 全量），用于在双模架构下隔离统计两条路径的质量信号。`template-issues` 端点在 `generation_mode=llm_direct` 时把 `template_id IS NULL` 行归入 `__llm_direct__` 桶不再被默认 `IS NOT NULL` filter 排除——LLM 直接生成的代码没有对应 template_id，这是设计内行为。

| 端点 | 返回字段 | 数据源 / 聚合逻辑 |
|---|---|---|
| `GET /api/v1/admin/analytics/feedback-summary` | `{days, total_generations, total_feedbacks, feedback_rate, bad_rate, no_match_rate}` | `total_*` = `count(generation_records)` 按时间窗；`bad_rate` = 差评数 / **反馈总数**（防 0/0 NaN）；`no_match_rate` = `gate_error_type='no_matching_template'` 记录数 / 总生成数 |
| `GET /api/v1/admin/analytics/template-issues` | `[{template_id, total_count, bad_count, bad_rate}]` top-N（默认 10） | 仅取 `template_id IS NOT NULL AND feedback_rating IS NOT NULL` 记录，按 `template_id` group by；排序 by `bad_rate DESC, bad_count DESC` |
| `GET /api/v1/admin/analytics/intent-confusion` | `[{intent, expected_template, actual_template, code_type, count}]` top-N | **仅** `feedback_rating=3 AND template_id != rag_top3[0].template_id`；`expected_template = rag_top3[0].template_id`（视 RAG top-1 为期望），`actual_template = template_id`；按 `(expected, actual)` 二元组聚合（不用用户原文做 key，脱敏 + 防基数爆炸），`intent` 字段返代表性截断样本（200 字符）；`code_type` 从 `templates` 表 join 出 actual 的 code_type，为前端复制 corpus 条目准备 |
| `GET /api/v1/admin/analytics/no-match-rate` | `[{date, total, no_match_count, no_match_rate}]` | 按 UTC 日界 group by；`no_match_count` = 当日 `gate_error_type='no_matching_template'` 记录数；`total` = 当日所有 `generation_records`（含 gate 触发记录）；**不补零行**——不足 days 天时只返实际有数据的天数 |

无数据情况下所有率值返 `0.0`、列表返 `[]`，**不报 500**。

#### 3.10.2 仪表盘页面（`/admin/analytics`）

`AdminAnalyticsPage.tsx` 挂载于 `/admin/analytics`，`RequireAdmin` 包裹。布局：

1. **KPI 卡片行**（Ant Design `Statistic`）：4 个数字 / 百分比展示总生成数、反馈率、差评率、NoMatch 率
2. **7 天趋势折线图**（`@ant-design/charts` Line）：消费 `/no-match-rate` 数据，X 轴日期、Y 轴 `no_match_rate`
3. **差评模板 top-10 表**（Ant Design `Table`）：消费 `/template-issues`，列含 template_id / total_count / bad_count / bad_rate
4. **intent confusion 表**（Ant Design `Table`）：消费 `/intent-confusion`，每行末尾有「复制为 corpus 条目」按钮——点击后将该行格式化为 `template_selection_corpus.yaml` 兼容的 YAML 块（含 id / intent / code_type / expected_template / note）写入剪贴板

#### 3.10.3 intent-confusion → corpus 闭环

混淆样本是回归测试语料的天然来源（CONTRIBUTING.md §12 近邻模板混淆对回归语料维护流程）。「复制为 corpus 条目」按钮生成的 YAML 格式直接兼容 `backend/tests/data/template_selection_corpus.yaml`：

```yaml
  - id: confusion_<timestamp>_<expected>_vs_<actual>
    intent: "<原始意图前 200 字符>"
    code_type: <actual_template 的 code_type，由后端 join 自动填好>
    expected_template: <rag_top3[0].template_id>
    note: "From production confusion log: intent classified as <actual> but expected <expected> (count=N)"
```

管理员复制后人工 append 到 yaml（**不**自动写回—— Stage 1 不做），下次 PR 上 CI 时回归套件自动守护这条规则。

**Stage 范围（明确不做）**：
- 不实现 CSV 导出（仅前端单条复制）
- 不做仪表盘数据的 Redis 缓存（量级 < 1 周生成数，PG 直查足够）
- 不实现 L4 自动告警（差评率突增邮件等，留待 L5）

---

## 4. 非功能需求

### 4.1 确定性（最高优先级）

- **当系统决定产出代码时**，相同的用户输入（含参数）必须产生字节级别完全相同的代码输出（v3.0 起，4 道闸有任一触发即不产出代码，详见 §6.1 错误模式）
- 系统必须对历史生成记录可追溯（输入→模板ID+版本→输出）
- 模板修改必须版本化，旧版本行为可复现
- **错误响应也必须确定**：同一输入触发同一闸，返回同一 `detail.type` 与同一 `redirect_to`（4 道闸的判定阈值都由 env 控制，固定阈值 = 固定结果）

### 4.2 模板库与代码类型可扩展性

- 模板库设计必须支持持续扩充，不影响现有模板的正常工作
- **新增模板**无需修改系统代码，仅维护 YAML 文件即可生效
- **新增代码类型**（如 UVM 激励序列）同样无需修改系统代码，仅需添加代码类型定义 YAML（含列定义、信号角色、意图标准化句式、场景模板），系统自动识别并适配
- 模板分类体系与代码类型绑定，每种代码类型独立维护自己的子分类体系，支持新增，不需要重构

### 4.3 性能

- 单条生成（缓存命中）：响应时间 < 500ms
- 单条生成（缓存未命中，含 LLM 调用）：
  - 非 thinking 类模型（Claude、DeepSeek-V3、GPT-4o、Qwen-Plus 等）：< 10s
  - Thinking 类模型（GLM-4.7、DeepSeek-R1 等）默认配置（`step2_disable_thinking=true`）：< 10s，与非 thinking 模型同档
  - Thinking 类模型显式关闭"Step2 禁用 thinking"开关时：60-150s，方差较大，建议仅在 FSM 等复杂参数填充能力验证场景使用
- 前端 `/generate` 与 `/generate/preview` 客户端默认超时 300s，覆盖 thinking ON 模式最坏情况
- 批量生成：支持单次上传不少于 100 行 Excel，整体生成时间 < 5 分钟（默认 thinking 禁用配置下达成；显式启用 thinking 时需相应放宽）
- 系统支持至少 50 个并发用户

### 4.4 可用性

- Web界面支持主流浏览器（Chrome、Firefox、Edge最新版）
- 响应式布局，支持1080p及以上分辨率
- 代码输出区域支持SystemVerilog语法高亮
- 参数面板支持实时编辑、实时重渲染（无需重新提交）

### 4.5 可维护性

- 模板库以YAML文件形式存储，可通过Git进行版本管理
- 系统提供Admin Web界面，支持无代码维护模板
- 模板保存时自动做语法和渲染校验，防止无效模板入库

### 4.6 数据安全与可恢复性

- PostgreSQL 每日自动备份（`pg_dump`），保留最近 7 份，支持按日期一键恢复
- Qdrant 向量索引属于派生数据，可由 PostgreSQL 完整重建，无需单独依赖向量备份
- 模板库支持随时通过 `lib_manager.py export-yaml` 导出为 YAML 文件，形成人工可读快照并可提交 Git
- 所有管理员敏感操作（模板变更、贡献审核、LLM配置修改等）自动写入审计日志，记录操作人、时间和变更前后内容
- 危险操作（停用模板、批量导入）在 Admin UI 执行前展示影响范围并要求二次确认
- 批量导入支持 `--dry-run` 预检模式，正式写入前可完整预览变更内容

---

## 5. 模板分类体系

> v1.0 初始注册 **SVA 断言** 和 **UVM 功能覆盖率** 两种代码类型，后续可通过添加代码类型配置文件扩展新类型（如 UVM 激励序列、约束文件等），无需修改系统代码。每种代码类型独立维护自己的子分类体系。

### 断言库（SVA）

```
断言库
├── 握手协议 (handshake)
│   ├── valid-ready 数据稳定性
│   ├── req-ack 响应时间约束
│   └── 多周期握手完整性
├── 时序约束 (timing)
│   ├── 最大延迟断言
│   ├── 最小延迟断言
│   └── 建立/保持时间
├── 有限状态机 (fsm)
│   ├── 非法状态跳转检测
│   ├── 状态可达性
│   └── 死锁检测
├── 数据完整性 (data_integrity)
│   ├── FIFO写入读出数据匹配
│   ├── 流水线数据一致性
│   └── 写后读验证
├── 总线协议 (bus_protocol)
│   ├── AXI4 专用
│   ├── AHB 专用
│   └── APB 专用
├── 复位行为 (reset)
├── 计数器 (counter)
└── 互斥与仲裁 (arbitration)
```

### 覆盖率库（UVM Coverage）

```
覆盖率库
├── 信号值覆盖 (value)
│   ├── 枚举值全覆盖
│   ├── 边界值覆盖
│   └── 范围分段覆盖
├── 状态转移覆盖 (transition)
│   ├── 单信号跳变覆盖
│   └── FSM 状态转移覆盖
├── 交叉覆盖 (cross)
│   ├── 双维度交叉覆盖
│   └── 三维度交叉覆盖
├── 协议事务覆盖 (protocol)
│   ├── AXI 事务类型覆盖
│   └── 突发传输长度覆盖
└── 异常场景覆盖 (exception)
```

---

## 6. 用户交互流程详述

### 6.1 单条生成主流程

1. 用户填写自然语言验证意图（文本框）
2. 选择代码类型（断言 / 覆盖率）
3. 填写结构化信号表（与批量 Excel 格式一致）：时钟、复位、协议，以及最多 4 个信号（每个信号填写名称、位宽、角色）
4. 点击「生成代码」 → 触发两步式流程

**Step A · 预览（preview）**：系统返回 RAG Top-3 候选模板 + 每参数的预填值与来源标识（6 类：LLM / 正则 / 信号表 / 模板默认 / 语义猜测 / 占位）。前 4 类为高置信源，后 2 类（`semantic_fallback` / `placeholder`）是系统按经验猜的——任一 required 参数落在低置信源，preview 直接走错误模式 **HTTP 422 under_specified** 并附 `redirect_to` 跳转 IntentBuilder（详见错误模式段）。

**Step B · 确认面板**：
- 默认套用置信度最高的候选；用户可一键切换其他候选，参数随之换为该候选的预填值
- 参数表单按 6 类源用不同颜色徽标提示来源；后端对 SV 标识符做了规范化清洗的字段显示"已规范化"角标，鼠标悬停可查看原始值；布尔/bins 表达式校验失败时实时显示红色错误提示
- 用户编辑参数 → 点击「确认生成」（参数源切回 `llm` 视为用户确认）
- 切换候选模板时若产生新的 `placeholder` / `semantic_fallback` 源参数，前端 `ConfirmationPanel` 实时拦截「确认生成」按钮，不允许带低置信源参数进入 render

**Step C · 渲染（render）**：系统按确认后的参数渲染最终代码，存入生成历史。

**短路路径 1（意图缓存命中）**：
- 历史上相同意图已生成过同一模板与同一参数 → 系统直接返回缓存代码，跳过确认面板，对用户呈现为一步式

**短路路径 2（高置信 RAG 自动渲染，v3.3 / FEAT-11 起）**：
- 当 preview 同时满足以下四条件时，`pipeline_preview` 同样把 `quick_render=True` 设为 True，前端跳过确认面板直接调 `/render`：
  1. `confidence_source == "llm_step1"`（LLM 主动选中模板，未走 rag_fallback）
  2. `STEP1_VERIFY_ENABLED=true` 且 A8 二次验证通过（LLM 自审 yes）
  3. 选中模板的 stage3 reranker score ≥ `RERANKER_MIN_SCORE_THRESHOLD`（默认 0.30）
  4. 所有 required 参数的源都属于高置信源集合 `{llm, regex, signal_list, default}`（不含 `semantic_fallback` / `placeholder`）
- 任一条件不满足即保留原 ConfirmationPanel 流程，用户可手工编辑参数后再 render（无回归）
- 前端 `handlePreviewSuccess` 的 `quick_render` 旗标处理对"意图缓存命中"与"高置信 RAG"两种来源完全一致——前者 `confidence_source==intent_cache`、后者 `confidence_source==llm_step1`，差异仅在置信徽标颜色

**LLM 直接生成兜底（result 阶段，v3.3 / FEAT-11 起）**：
- result 阶段在代码卡片下方展示「对生成结果不满意？尝试 LLM 直接生成」secondary 按钮，**仅在 `state.result.generation_mode === 'rag'` 时显示**——已经是 `llm_direct` 的记录不再展示该按钮，禁止链式 fallback
- 点击 → spinner → `POST /api/v1/generate/llm-fallback {generation_record_id}` → 后端载入源记录的 intent / code_type / signals / clk / rst → 调 `LLMClient.generate_code_freeform`（围栏接受 `systemverilog` / `sv` / `verilog` 三种 lang 或裸 ` ``` `）→ 返回 `{code, generation_record_id, generation_mode: "llm_direct", cache_hit}` → 前端替换代码区 + 反馈状态归零
- 代码卡片头部强制渲染 `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>` 提示用户当前结果不在确定性契约保护范围内
- 同一输入命中 `gen_llm:{llm_config_id}:{sha256(canonical(intent+code_type+signals+clk+rst))}` 7d TTL Redis 缓存时返缓存代码（cache_hit=True）；切换默认 LLM 配置即 flush 该前缀（与 `gen:*` / `intent_cache:*` 同步清空）

**软提示路径（低置信度，**非硬闸**）**：
- 当 `confidence_source == "rag_fallback"`（LLM Step1 没主动选中、由 RAG top-1 兜底）时，确认面板顶部展示提示条与「去意图构建器精修」「贡献新模板」两个入口
- 这条路径**不**拦截用户继续生成——只要 required 参数都有高置信源（under_specified 已经放过），用户可以继续 Step B + C 强行渲染最接近的候选作为草稿
- 设计原则：v2.13 已经收敛了所有"用户问题"硬闸（off-topic / code_type_mismatch / under_specified / empty_retrieval），低置信度不构成"系统拒绝服务"的理由，只是"系统不确定，需要用户判断"

**错误模式（用户可见，按 pipeline 顺序；v3.0 引入 `redirect_to` 字段）**：

错误响应统一结构（HTTP 4xx/5xx）：
```json
{
  "detail": {
    "type": "<off_topic | code_type_mismatch | under_specified | empty_retrieval>",
    "message": "<人话描述>",
    "redirect_to": "<前端应跳转的路由 URL，可选>",
    // 各错误专属字段…
  }
}
```

前端 `handleApiError` 读到 `detail.redirect_to` 时**优先做 router.push**，不读时按 detail.type 弹对应 Modal。

| 错误模式 | HTTP | `detail.type` | `redirect_to` | 前端表现 |
|---|---|---|---|---|
| **off-topic** | 422 | `off_topic` | 无 | 弹"检测到非验证请求"专属 Modal，停留生成页（IntentBuilder 也救不了真离题） |
| **code_type 错配** | 422 | `code_type_mismatch` | 无 | 弹"代码类型选错了"Modal 引导切换，停留生成页 |
| **under_specified** | 422 | `under_specified` | `/intent-builder?prefill=<intent>&missing=<param_names>&template_id=<id>` | 前端读 `redirect_to` 自动 `router.push`，进入 IntentBuilder 多轮对话补足信息 |
| **empty_retrieval** | 503 | `empty_retrieval` | 无 | 弹"系统暂不可用，请稍后或联系管理员"，停留生成页（基础设施问题，跳哪里都救不了） |
| **llm_direct_chained_not_allowed**（v3.3） | 422 | `llm_direct_chained_not_allowed` | 无 | 用户对已是 `llm_direct` 的记录再次点 fallback 按钮（理论上前端按 `generation_mode==='rag'` 守门已阻止；保留作 API 直调防线）；前端 `message.error` 文案"已是 LLM 直接生成结果，不支持链式兜底"，停留 result 页 |
| **llm_direct_no_code**（v3.3） | 422 | `llm_direct_no_code` | 无 | `LLMClient.generate_code_freeform` 解析失败（LLM 返纯文字无 ` ```systemverilog/sv/verilog``` ` 围栏）；前端 `message.error` "LLM 未生成可用 SV 代码块，请稍后重试或换 LLM 配置"，停留 result 页 |
| **llm_direct_internal_error · 422 分支**（v3.3） | 422 | `llm_direct_internal_error` | 无 | 非 `no_sv_code_block` 类 `ValueError`（LLM 输出可解析但内容异常 / Pydantic 校验失败等）；`detail.message` 是固定文案不泄漏内部 repr；前端 `message.error` "LLM 直接生成失败，请稍后重试"，停留 result 页 |
| **llm_direct_internal_error · 500 分支**（v3.3） | 500 | `llm_direct_internal_error` | 无 | `except Exception` 兜底（DB 写入失败 / 网络超时 / LLM SDK 内部错误等基础设施失败）；与 422 同名 `type`，靠 HTTP 状态区分——422 用户重试可能解决，500 需 SRE 介入；前端 `message.error` 同 422 分支，但状态码会出现在 toast 文案的"HTTP 500"段 |
| **duplicate_report**（v3.4 / FEAT-12） | 409 | `duplicate_report` | 无 | 同一 `(rag_record_id, llm_direct_record_id)` 对已存在 `improvement_reports` 行；`detail.existing_report_id` 为已有记录的 UUID。前端 `handleApiError` 将"提交对比报告"按钮置 disabled、文案改为"已有人提交对比报告，admin 处理中"，停留 result 页 |
| **invalid_record_ref**（v3.4 / FEAT-12） | 422 | `invalid_record_ref` | 无 | `POST /improvement-reports` 中 `rag_record_id` 或 `llm_direct_record_id` 在 `generation_records` 中不存在（被 admin 删除 / ID 拼错）；前端 `message.error` "记录不存在，可能已被删除，请刷新页面"，停留 result 页 |
| **illegal_status_transition**（v3.4 / FEAT-12） | 422 | `illegal_status_transition` | 无 | `PATCH /admin/improvement-reports/{id}` 试图非法跳转 admin 三态状态机（如 `pending → resolved` 跳过 `in_review`、`resolved → pending` 倒退、`resolved → in_review` 倒退）；`detail.message` 描述合法跳转链。前端 `message.error` 提示 admin"非法状态跳转"，停留 admin 详情页 |

后端 except 链顺序固定（OffTopic → CodeTypeMismatch → UnderSpecified → EmptyRetrieval → 兜底 ValueError），不要泛化为 `except ValueError`。`llm_direct_*` 错误由 `POST /generate/llm-fallback` 端点独立返回，与上述 5 道闸的 except 链路无关。`llm_direct_internal_error` 同名 `type` 同时出现在 422 和 500，前端 `handleApiError` 据 HTTP 状态分流即可（不依赖 detail.type 区分）。`duplicate_report` / `invalid_record_ref` / `illegal_status_transition`（FEAT-12）由 `improvement_reports` 路由独立返回，亦与上述 except 链无关，三者均不带 `redirect_to`。

**IntentBuilder 处理后的回流**：用户在 IntentBuilder 中通过多轮对话产出标准化 intent 后，点击「用这条意图回去生成」，前端 `router.push("/generate?prefill=<refined_intent>")` 跳回生成页，自动填入 TextArea 并触发新一轮 /preview——若仍触发 under_specified，循环（用户可继续 IntentBuilder 精修或退到贡献流）。

### 6.2 用户对比报告（FEAT-12 / v3.4）

**用户旅程**：result 阶段当且仅当 `state.result.generation_mode === 'llm_direct' && state.result.parent_record_id != null` 时，FeedbackBar 旁渲染独立 secondary 按钮「提交对比报告」（与 §3.9 L3 差评按钮并存，两个交互互相独立）。`rag` 路径记录与"冷启动 llm_direct"（parent_record_id 为空，本期实际不可达）均不渲染该按钮。

**触发位置与既有差异**：
- L3 差评（§3.9）：每条记录单独打分（1/2/3），回写 `generation_records.feedback_*` 4 列，关心"这条结果质量怎样"
- 对比报告（§6.2 本节）：成对（RAG 源 + LLM 直接生成子记录）一次性提交，写入新表 `improvement_reports`，关心"RAG vs LLM 直接生成的差异是否值得 admin 关注、问题在哪类"
- 二者可同时使用——用户既可对 LLM 直接生成结果打 3 分差评，也可同一对再提交对比报告，互不抑制

**提交 Modal（4 项分类 + 自由文本）**：

| 字段 | 控件 | 必填 | 说明 |
|---|---|---|---|
| `report_categories` | `Checkbox.Group`（4 选项可多选） | 否（可全不勾） | 见下方枚举表 |
| `reporter_note` | `TextArea`（rows=4，无字数上限校验） | 否（可空） | 用户自由描述差异点 |

`report_categories` 枚举（`ReportCategoryEnum`，slug ↔ 中文 label）：

| slug | 中文 label | 含义 |
|---|---|---|
| `wrong_template` | 模板选错 | RAG 选中的模板与意图不符（语义错配） |
| `wrong_params` | 参数映射错 | 模板正确但参数填充错误（信号名/状态列表/表达式映射错） |
| `poor_style` | 代码风格差 | 模板正确、参数正确，但生成风格不符合团队规范（命名、缩进、注释） |
| `other` | 其他 | 上述 3 类无法归纳的差异 |

**"全选填均为空也允许提交"是显式契约**：用户可不勾任何分类、不写任何 note 直接点「提交」，HTTP 201 成功 → 后端写入 `status='pending'` + `report_categories=[]` + `reporter_note=NULL` 记录。设计原则：降低提交摩擦——用户观察到差异即可一键留痕，分类与详述可由 admin 在审阅时反向补充。

**按钮 disabled 状态**：

| 触发条件 | 按钮文案 | 触发机制 |
|---|---|---|
| 本次会话内已提交成功 | 「已提交」（gray） | 前端 state.reported 旗标 |
| 同一对 `(rag_record_id, llm_direct_record_id)` 已有他人/历史报告 | 「已有人提交对比报告，admin 处理中」（gray） | `GET /api/v1/improvement-reports/check?rag_record_id=&llm_direct_record_id=` mount 时查询；或 `POST` 时捕获 409 `duplicate_report` 兜底刷新按钮态 |

**admin 三态审阅工作流**：

```
pending ──admin 打开详情页（mount 自动 PATCH）──► in_review ──admin 写 note + 「标记已处理」──► resolved
```

合法跳转：`pending → in_review`、`in_review → resolved`。**所有其他跳转一律 422 `illegal_status_transition`**，包括但不限于 `pending → resolved`（跳过 in_review）、`resolved → pending`（倒退）、`resolved → in_review`（倒退）、`in_review → pending`（倒退）。多 admin 并发进入 `in_review` 不做认领锁（last-write-wins），FEAT-12 不解决该并发问题。

admin 端入口：侧边栏「管理」分组新增「对比报告」菜单项 `/admin/improvement-reports`，仅 `lib_admin` / `super_admin` 可见。

- **列表页**：分页 Table，含 ID / 状态 Tag（pending/in_review/resolved 三色）/ 提交用户名 / RAG 模板名 / 分类 Tag 组 / 提交时间 / 操作"查看"。Filter Bar 支持 `status` 单选 + `categories` 多选，默认 `created_at DESC`
- **详情页**（`/admin/improvement-reports/:id`）：三列 Card 横向布局——左 RAG 记录（output_code / template_name / params_used / original_intent / generation_mode）/ 中 LLM Direct 记录（同字段）/ 右用户提交内容（categories / note）+ admin_note 编辑区 + 「标记已处理」按钮。mount 时若 `status === 'pending'`，前端**自动**调 `PATCH /api/v1/admin/improvement-reports/{id} { status: 'in_review' }`，无需 admin 主动点击

**Out of scope（明确不做，留 FEAT-13 或后续票）**：
- **语料回流**：resolved 报告自动 / 半自动写入 `template_corpus_cases` 闭环（留 FEAT-13）
- admin 端报告 CSV 导出
- 邮件 / Webhook 推送通知（admin 有新报告待审）
- 报告评论 / 互相回复（admin ↔ 用户对话）；`admin_note` 为单向字段
- 跨 admin 的认领锁（多 admin 同时进入 `in_review` 均允许，last-write-wins）
- 删除 improvement_report
- 用户撤回已提交的报告
- 报告字段长度上限校验（`reporter_note` / `admin_note` 均不设 DB 层 CHECK 约束）
- 批量任务（Celery）路径生成记录的对比报告（`parent_record_id` 在 batch 路径中不写入，故无源记录可对比）
- 贡献向导路径生成记录的对比报告

### 6.3 批量生成主流程

1. 用户下载Excel模板
2. 填写Excel（描述列 + 信号列）
3. 上传Excel，选择默认代码类型
4. 系统显示解析预览（行数、识别到的列）
5. 确认开始批量生成
6. 显示实时进度（已完成/总数）
7. 生成完成，展示结果列表（含每行状态）
8. 用户可逐项审查、修改参数重新生成
9. 选择下载范围，下载打包文件

---

## 7. 不在范围内（Out of Scope）

以下内容在当前版本（v1.0）**不包含**，后续版本可扩展：

- 自动化仿真运行和断言检查结果回收
- 与EDA工具（Cadence、Synopsys）的直接集成
- 多语言UI界面（v1.0仅支持中文界面）
- 移动端适配

以下内容**不是永久性约束**，通过代码类型注册表可在后续版本无代码扩展：

- 形式验证属性（Formal Property）辅助代码生成
- UVM 激励序列（Sequence）代码生成
- SV 约束文件（Constraint）生成
- 其他结构化辅助验证代码类型

> 注：以上扩展类型均无需修改核心系统代码，仅需为新类型编写代码类型定义 YAML 和对应模板库。

---

## 8. 待后续确定

- 初始模板库规模：v1.0 上线最少 10 条种子模板，后续通过贡献审核机制逐步扩充；优先级：通用握手（SVA）→ 通用时序（SVA）→ UVM基础覆盖率 → AXI4专用 → FSM
- 用户登录方式：v1.0 采用本地账号 + JWT，企业 LDAP/SSO 集成留待后续版本
