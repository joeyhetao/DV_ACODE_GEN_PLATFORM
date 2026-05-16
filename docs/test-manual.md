# 平台功能测试手册

> 面向：QA、产品验证、上线前回归。每个用例 = 操作步骤 + 期望效果。
> 平台版本：PRD v3.0。后端基于 4 道闸契约（off-topic / code_type_mismatch / under_specified / empty_retrieval）。

---

## 目录

- [0. 测试前置](#0-测试前置)
- [1. 单条生成 — 高置信路径](#1-单条生成--高置信路径)
- [2. 单条生成 — 4 道闸触发](#2-单条生成--4-道闸触发)
- [3. 缓存层验证](#3-缓存层验证)
- [4. 意图构建器（IntentBuilder）](#4-意图构建器intentbuilder)
- [5. 模板贡献机制](#5-模板贡献机制)
- [6. 批量生成](#6-批量生成)
- [7. 模板库浏览与管理](#7-模板库浏览与管理)
- [8. 用户与权限](#8-用户与权限)
- [9. LLM 配置管理](#9-llm-配置管理)
- [10. 通知机制](#10-通知机制)
- [附录 A：日志/缓存排查速查](#附录-a日志缓存排查速查)
- [附录 B：4 道闸错误响应结构对照](#附录-b4-道闸错误响应结构对照)

---

## 0. 测试前置

### 0.1 启动栈

```bash
# 前端 dist 准备（首次或源码改动后）
cd frontend && npm install && npm run build && cd ..

# CPU 完整栈 + 后端 hot-reload + 前端 dist bind-mount
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.hotreload.yml up -d

# 入口
# 前端：http://localhost/
# API 文档：http://localhost/api/docs
```

### 0.2 测试账号

| 角色 | 用户名 | 密码 |
|---|---|---|
| 平台管理员 | `admin` | 环境变量 `SUPER_ADMIN_PASSWORD`，默认见 `.env.example` |
| 库管理员 | （需 super_admin 在用户管理页升级现有用户） | — |
| 普通用户 | 登录页"注册"自助创建 | — |

### 0.3 缓存清空（冷启动复测）

```bash
# 清两层 LLM 缓存（gen + intent_cache）
docker compose exec redis redis-cli --scan --pattern 'gen:*' | xargs -r docker compose exec -T redis redis-cli DEL
docker compose exec redis redis-cli --scan --pattern 'intent_cache:*' | xargs -r docker compose exec -T redis redis-cli DEL

# 清 IntentBuilder session（也可用 FLUSHDB 一并清干净）
docker compose exec redis redis-cli --scan --pattern 'intent_builder_session:*' | xargs -r docker compose exec -T redis redis-cli DEL
```

### 0.4 推荐 LLM 配置

进入 Admin → LLM 配置，选择 `step2_disable_thinking=true`（默认即开）。GLM-4.7 / DeepSeek-R1 等 thinking 类模型在此设置下单次推理 ~3s；关闭则 60-150s 方差。

### 0.5 后端日志实时查看

```bash
# 跟踪 backend 日志，过滤 pipeline 关键步骤
docker compose logs -f backend | grep -E "\[Pipeline\]|\[Timing\]|\[GLM Step|\[WARN\]"
```

### 0.6 测试 JWT 获取

```bash
# API 测试时用
TOKEN=$(curl -s -X POST http://localhost/api/v1/auth/login \
  --data-urlencode "username=admin" \
  --data-urlencode "password=<your_password>" | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
echo $TOKEN
```

---

## 1. 单条生成 — 高置信路径

### §1.0 通用工作流（所有 §1.x 都按这个流程）

1. 进入「代码生成」页
2. 选择代码类型（assertion / coverage）
3. 在「功能描述」TextArea 填验证意图
4. 必要时填 协议 / 时钟 / 复位 / 信号列表
5. 点「分析意图」（preview 阶段，3-7s）
6. 检查 ConfirmationPanel：模板名 + 置信度来源 + 6 类参数源徽标
7. 编辑参数（如需要）→ 点「确认并生成代码」（render 阶段，<1s）
8. 看生成的 SystemVerilog 代码

### §1.0 通用期望

- preview 后展示 RAG Top-3 候选 + 推荐模板
- 参数徽标颜色对应：🟢 信号列表 / 🟡 正则 / 🟠 LLM / ⚪ 默认 / 🔴 占位（主路径下不出现，出现即被拦截）
- confidence_source = `llm_step1`（LLM 主动选中）或 `rag_fallback`（RAG 兜底，置信度低）
- 后端日志含 `[Pipeline] source=direct code_type=<type>` + `[Timing] llm=...` 三段

### §1.1 数据完整性断言

| | |
|---|---|
| 输入 | `寄存器写保护场景：当写使能 wr_en 无效时，data_in 不会被意外修改` |
| code_type | SVA 断言 |
| 期望模板 | `sva_data_integrity_v1` 数据完整性无损坏断言 |
| 关键参数 | enable=wr_en（信号列表）/ data=data_in（LLM） |

### §1.2 FSM 状态转换断言

| | |
|---|---|
| 输入 | `检测状态信号 cur_state 不允许直接从 IDLE 跳到 DONE，必须经过 RUN 中间态` |
| code_type | SVA 断言 |
| 期望模板 | `sva_fsm_state_transition_v1` FSM 状态转换合法性断言 |

### §1.3 握手数据稳定断言

| | |
|---|---|
| 输入 | `AXI 写通道 awvalid 拉高后 awaddr 必须保持稳定到 awready` |
| code_type | SVA 断言 |
| 信号列表 | awvalid(role=valid)、awready(role=ready)、awaddr(role=data) |
| 期望模板 | `sva_handshake_stable_v1` AXI Valid-Ready 握手数据稳定性断言 |

### §1.4 握手超时检测断言

| | |
|---|---|
| 输入 | `AXI valid-ready 握手超时检测：awvalid 拉高后 16 周期内 awready 必须响应` |
| code_type | SVA 断言 |
| 期望模板 | `sva_handshake_timeout_v1` Valid-Ready 握手超时检测断言 |

### §1.5 复位行为断言

| | |
|---|---|
| 输入 | `复位释放后 cur_state 必须等于 IDLE` |
| code_type | SVA 断言 |
| 期望模板 | `sva_reset_behavior_v1` 复位释放后初始值断言 |

### §1.6 最大延迟时序约束断言

| | |
|---|---|
| 输入 | `从 req 拉高到 ack 拉高的最大延迟不超过 8 个时钟周期` |
| code_type | SVA 断言 |
| 期望模板 | `sva_timing_max_delay_v1` 最大延迟时序约束断言 |

### §1.7 交叉覆盖率组

| | |
|---|---|
| 输入 | `交叉覆盖 awsize 与 awburst 的所有合法组合` |
| code_type | UVM 覆盖率 |
| 期望模板 | `cov_cross_coverage_v1` 交叉覆盖率组 |

### §1.8 协议握手覆盖率组

| | |
|---|---|
| 输入 | `统计 valid-ready 握手成功、valid 等待、ready 预备三种场景的覆盖率` |
| code_type | UVM 覆盖率 |
| 期望模板 | `cov_protocol_handshake_v1` 协议握手覆盖率组 |

### §1.9 状态转换覆盖率组

| | |
|---|---|
| 输入 | `对状态信号 cur_state 做 FSM 转换覆盖率，状态包括 IDLE,ACTIVE,DONE，信号位宽 2` |
| code_type | UVM 覆盖率 |
| 期望模板 | `cov_transition_coverage_v1` 状态转换覆盖率组 |
| 参数 | signal=cur_state / state_list="IDLE, ACTIVE, DONE" / signal_width=2 |

### §1.10 信号值域覆盖率组

| | |
|---|---|
| 输入 | `覆盖 awlen 信号的所有典型枚举值：1、4、8、16` |
| code_type | UVM 覆盖率 |
| 期望模板 | `cov_value_coverage_v1` 信号值域覆盖率组 |

---

## 2. 单条生成 — 4 道闸触发

按 pipeline 顺序触发：off-topic → code_type_mismatch → empty_retrieval → under_specified。

### §2.1 off-topic（HTTP 422，弹"非验证请求"Modal）

| | |
|---|---|
| 输入 | `推荐上海好吃的小笼包` |
| code_type | 任选 |
| 期望 | 后端返 422，前端弹"检测到非验证请求"Modal，文案含 dense top1 分数 + 阈值 0.44 |
| detail.type | `off_topic` |
| detail.redirect_to | `null`（停留生成页） |

### §2.2 code_type_mismatch（HTTP 422，弹"切换 code_type"Modal）

| | |
|---|---|
| 输入 | `统计 valid-ready 四种握手场景的覆盖率` |
| code_type | **错选** SVA 断言 |
| 期望 | 后端返 422，前端弹"代码类型选错了"Modal，建议改为 coverage |
| detail.suggested_code_type | `coverage` |
| detail.redirect_to | `null`（用户在原页面切换 code_type 重试） |

### §2.3 under_specified（HTTP 422，跳转 IntentBuilder）

| | |
|---|---|
| 输入 | `生成一个 FSM 转换覆盖率`（描述里没说信号名/状态列表） |
| code_type | UVM 覆盖率 |
| 期望 | 后端返 422 含 `redirect_to`；前端 `handleApiError` 读到 `redirect_to` 自动 `router.push` 跳 IntentBuilder |
| detail.missing_params | 含 `signal` / `state_list` / `signal_width` / `group_name` 等参数名 |
| detail.redirect_to | `/intent-builder?prefill=...&template_id=cov_transition_coverage_v1&code_type=coverage&missing=...` |

### §2.4 empty_retrieval（HTTP 503，弹"系统不可用"Modal）

需故意制造基础设施异常才能复现（停掉 Qdrant 或清空 templates 表）。日常回归靠单测 `test_pipeline_preview_rag_empty_and_no_supplement_raises_empty_retrieval`，**不要**在生产复测此场景。

### §2.5 4 道闸响应结构验证（API 层）

```bash
# under_specified detail 必含 redirect_to 字符串
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/generate/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"生成一个 FSM 转换覆盖率","code_type":"coverage","clk":"clk","rst":"rst_n","rst_polarity":"低有效","signals":[]}' \
  | python3 -m json.tool
```

期望响应：`detail.type="under_specified"` + `detail.redirect_to` 是非空字符串以 `/intent-builder?` 开头。

---

## 3. 缓存层验证

### §3.1 intent_cache 命中

1. 清缓存（§0.3）
2. 第一次 preview 某意图（如 §1.9）→ render → 看到 SV 代码
3. 不改任何输入，第二次 preview 同意图
4. 期望：
   - 第二次响应 `confidence_source: "intent_cache"`
   - 前端跳过 ConfirmationPanel 直接进 render 视图（quick_render）
   - 后端日志 `[Timing] stage=normalize` 之后无 `[GLM Step` 调用

### §3.2 gen cache 命中（同模板 + 同参数）

1. 不同意图但选同一模板和相同参数确认值
2. 第二次 render 期望 `cache_hit: true`
3. 后端日志在 render 阶段无 Jinja2 渲染时间

### §3.3 切换默认 LLM 后两层缓存自动 flush

1. 进 Admin → LLM 配置
2. 当前默认 = glm-4.7，先确认有缓存：
   ```bash
   docker compose exec redis redis-cli KEYS 'gen:*' | head
   docker compose exec redis redis-cli KEYS 'intent_cache:*' | head
   ```
3. 点击其他 config 的"设为默认"
4. 立即查 Redis：
   ```bash
   docker compose exec redis redis-cli KEYS 'gen:*'          # 应空
   docker compose exec redis redis-cli KEYS 'intent_cache:*' # 应空
   docker compose exec redis redis-cli KEYS 'intent_builder_session:*'  # 应保留
   ```
5. 期望：`gen:*` 和 `intent_cache:*` 全清，但 IntentBuilder session 不受影响

### §3.4 模板 schema 漂移时 intent_cache bypass

1. 提交意图 → render → intent_cache 写入（含 `params_fingerprint`）
2. 库管理员在「模板库」编辑该模板，新增一个 required 参数
3. 同意图再 preview
4. 期望：后端日志含 `[Pipeline] intent_cache schema drift: ... bypass cache`；走完整 RAG+LLM 链路重新算

---

## 4. 意图构建器（IntentBuilder）

### §4.1 通过 422 under_specified 跳转进入

1. 在 GeneratePage 触发 §2.3 under_specified
2. 期望：自动跳到 `/intent-builder?prefill=...&template_id=...&missing=...&code_type=...`
3. 进入 IntentBuilder 首屏：
   - 顶部 Tag：当前 code_type / 已识别模板 ID / 缺失参数名
   - TextArea 已被 prefill 填入"生成一个 FSM 转换覆盖率（系统提示：以下必填参数我还没明确：signal,state_list,...）"

### §4.2 多轮对话补足参数

1. 点击「发送」（首轮）
2. 期望：
   - 左侧出现 user 气泡（蓝色） + assistant 气泡（灰色）
   - 右侧 Card 列表显示 RAG top-3 候选模板（含 score 百分比）
   - 上方 Alert 显示「当前累计意图」（accumulated_intent）
3. 用户回复："信号名 cur_state，状态包括 IDLE / RUN / DONE"
4. 期望：第二轮 turn_count=2，accumulated_intent 已包含具体信号名

### §4.3 用累计意图回 GeneratePage

1. 点底部「用这条意图回去生成」
2. 期望：跳 `/generate?prefill=<accumulated_intent>&code_type=<...>&source=intent_builder`
3. GeneratePage 自动填入意图
4. 点「分析意图」→ 期望本次 4 道闸全过，到 ConfirmationPanel

### §4.4 用户输入超长拒（DoS 防护）

```bash
# user_message 超过 8192 字符
TOKEN=<jwt>
docker compose exec backend python -c "
import json
print(json.dumps({'session_id':'', 'user_message':'x'*9000, 'code_type':'coverage'}))
" > /tmp/long.json
curl -s -o /tmp/long_r.json -w "HTTP %{http_code}\n" \
  -X POST http://localhost/api/v1/intent-builder/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  --data-binary @/tmp/long.json
head -c 200 /tmp/long_r.json
```

期望：HTTP 422 含 `string_too_long` Pydantic 错误。

### §4.5 session 24h TTL

```bash
docker compose exec redis redis-cli KEYS 'intent_builder_session:*' | head -1
docker compose exec redis redis-cli TTL <key>
```

期望：TTL 接近 86400（24h）。

### §4.6 N 轮后建议贡献

构造库里完全没有的需求（如非常规、罕见的描述），连续 5 轮对话后期望响应含 `suggest_contribute: true`，前端展示「贡献新模板」入口按钮。

### §4.7 v2 退役端点返 410

```bash
curl -s -w "HTTP %{http_code}\n" \
  "http://localhost/api/v1/intent-builder/scenarios?code_type=assertion" \
  -H "Authorization: Bearer $TOKEN"
```

期望：HTTP **410 Gone** + `detail.type="endpoint_deprecated"`。

---

## 5. 模板贡献机制

### §5.1 完整流程（4 字段提交 → LLM 反推 → 审核 → 入库）

#### 步骤

1. 普通用户在 GeneratePage 触发低置信度场景，或通过「我的贡献」页 +「+ 新贡献」入口
2. 弹出提交 Modal（v3.0 简化为 4 字段）：
   - 模板名称
   - 代码类型（assertion / coverage）
   - 验证场景描述（自然语言，用于 RAG 匹配）
   - 代码示例（粘贴含真实信号名的可运行 SV 代码）
3. 点「提交，由 AI 协助参数化」
4. 后端同步跑（5-15s）：
   - LLM 反推 parameter_defs / Jinja body / keywords / subcategory / protocol
   - 3 道自动校验：参数名合法 / Jinja2 沙箱渲染通过 / keywords 格式
   - 语义查重把 top-3 相似模板塞 `original_row_json.similar_templates`
5. 期望成功响应：HTTP 201 + `status: "pending_review"` + 自动反推的 `parameter_defs / keywords / subcategory / protocol`

#### 进入审核

6. 切换到 lib_admin 账号（或 super_admin）
7. 进 Admin → 贡献审核
8. 看到刚提交的贡献，点击展开审核 Drawer（90% 宽三栏布局）：
   - 左栏（只读）：用户提交 — 模板名、code_type、场景描述、原始代码示例
   - 中栏（可编辑）：LLM 反推的 Jinja2 模板（Monaco 高亮）
   - 右栏（可编辑）：parameter_defs JSON / keywords / subcategory / protocol
9. 验证 `similar_templates`（如果有）：贡献提交时把库内相似 top-3 塞了 `original_row_json`，审核员可在这里看到
10. 审核员可任意修改中/右栏；改完点「保存编辑」
11. 改 demo_code / parameter_defs 后保存时**自动重跑** jinja 二次校验，失败拒提交

#### 批准入库

12. 点「批准并入库」
13. 期望：HTTP 200 + 自动分配 `promoted_template_id`（形如 `contrib_<8hex>`）
14. 进「模板库」页，能看到新入库模板（maturity=draft）
15. 此后用相关意图 preview，可命中该模板

### §5.2 关键拦截路径

#### §5.2.1 重复模板名 → 422

提交时 `template_name` 与已入库 Template 重名 → HTTP 422 `contribution_name_duplicate`。

#### §5.2.2 demo_code 太烂 → LLM 反推失败 → 422

```bash
# 故意提交 garbage demo_code
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/contributions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"code_type":"assertion","template_name":"L_garbage","description":"测试","demo_code":"!!!! garbage @@@@"}'
```

期望：HTTP 422 + `detail.type="contribution_parse_failed"` + `detail.stage="param_defs_empty"`（或类似）。

#### §5.2.3 SSTI payload 提交时被拦

提交 demo_code 含 `{{ self.__class__.__bases__ }}` 这类 dunder 访问 → Sandbox 渲染失败 → 422 stage=`jinja_sandbox`。

#### §5.2.4 审核员 PATCH 后二次校验

审核员把 demo_code 改成含 SSTI 的 Jinja2 → PATCH 端点二次跑 sandbox 渲染 → 422 拒 commit，原数据不变。

#### §5.2.5 demo_code / description 超长拒

`demo_code > 32KB` 或 `description > 4KB` → Pydantic 拒 422 `string_too_long`。

#### §5.2.6 SV / Python 关键字作参数名拒

若 LLM 反推产出 `always` / `class` / `module` 等关键字作 parameter name → 拒，stage=`param_defs_name`。

### §5.3 我的贡献页

1. 普通用户进「我的贡献」
2. 看自己提交记录的状态列：`pending_review` / `under_review` / `needs_revision` / `approved` / `rejected`
3. needs_revision 状态可点「编辑」修改后重提，状态归回 `pending_review`

---

## 6. 批量生成

### §6.1 完整流程（Excel → ZIP）

1. 「批量生成」页下载 Excel 模板（按 code_type 区分 sheet）
2. 填 5 行测试数据（混合 assertion + coverage）
3. 上传 Excel
4. 看解析预览：行数、列识别
5. 点「开始批量生成」
6. 期望：实时进度条（已完成/总数）；每行调 `run_pipeline`，遇 4 道闸结构化记录该行状态
7. 完成后展示结果列表：每行 `status` ∈ `success` / `under_specified` / `off_topic` / `code_type_mismatch` / `failed`
8. 下载结果 ZIP

### §6.2 每行结果状态对应

| 行状态 | 含义 | 用户行动 |
|---|---|---|
| `success` | 4 道闸全过 + 模板渲染成功 | 直接用代码 |
| `under_specified` | 该行描述里缺必填参数（响应含 `missing_params`） | 修改该行意图后单独重跑 |
| `off_topic` | 描述非 IC 验证 | 重写该行 |
| `code_type_mismatch` | 该行 code_type 与意图不符（响应含 `suggested_code_type`） | 切换该行 code_type |
| `failed` | 兜底未知异常 | 联系管理员 |

### §6.3 任务卡死诊断

```bash
# Celery worker 日志
docker compose logs celery_worker | tail -50

# 当前 Celery 活跃任务
docker compose exec celery_worker celery -A app.tasks.celery_app inspect active

# batch_jobs 表状态
docker compose exec postgres psql -U dvuser -d dv_platform -c "SELECT id, status, started_at, completed_rows, total_rows FROM batch_jobs ORDER BY created_at DESC LIMIT 5;"
```

---

## 7. 模板库浏览与管理

### §7.1 浏览与过滤

1. 「模板库」页能看到所有 `is_active=true` 模板
2. 按 code_type / subcategory / protocol 过滤
3. 按名称模糊搜索
4. 点击模板看详情：description / parameters / template_body / keywords

### §7.2 库管理员编辑模板

1. lib_admin 进入「模板库」点某模板「编辑」
2. 改 description / template_body / parameters
3. 保存后期望：
   - 模板 version 自动递增
   - 写入 `template_versions` 历史快照
   - `templates.{template_id}.{old_version}` 的 gen cache **不**自动失效（设计：旧版本代码继续可命中缓存，新生成走新版本）
   - 关联 intent_cache 因 `params_fingerprint` 差异自动 bypass

### §7.3 lib_manager CLI 模板库管理

```bash
# 列出所有模板
docker compose exec backend python lib_manager.py list

# 按 code_type 过滤
docker compose exec backend python lib_manager.py list --code-type coverage

# 语义查重扫描（按指定阈值）
docker compose exec backend python lib_manager.py dedup-check --threshold 0.85

# 重建 Qdrant 索引（sync_status=syncing 的行）
docker compose exec backend python lib_manager.py rebuild
```

---

## 8. 用户与权限

### §8.1 自助注册

1. 登录页切换"注册"Tab
2. 填用户名 / 邮箱 / 密码
3. 注册成功 → 自动登录 → 跳生成页
4. 默认角色 `user`（普通用户）

### §8.2 super_admin 升级权限

1. admin 登录 → 「用户管理」
2. 找到用户，点「修改角色」
3. 选 `lib_admin` 或 `super_admin`
4. 期望：被改用户的下一次请求生效新权限

### §8.3 禁用用户 token 立即失效

1. admin 把某用户 `is_active=false`
2. 该用户的现有 JWT 下一次请求期望 401 + `detail: "账号已被禁用"`
3. 前端 401 拦截器自动清 localStorage token → 跳 `/login`

---

## 9. LLM 配置管理

### §9.1 添加 + 测试新配置

1. admin 进「LLM 配置」
2. 点「新增配置」填：name / provider（anthropic / openai_compatible）/ base_url / api_key / model_id / temperature / max_tokens
3. 对 OpenAI 兼容类型可勾选 `step2_disable_thinking`（默认勾选）
4. 提交后期望：
   - api_key 在 list 视图显示为 mask 形式（如 `sk-a***EwAA`）—— **真 key 头尾**，不是密文头尾
   - 三道测试按钮：连通性测试 / Anthropic 工具调用测试 / OpenAI 文本测试

### §9.2 设为默认 → 两层缓存联动 flush

见 §3.3。同时验证 `is_default` 表上的 partial unique index 防止多行同时 default=true。

### §9.3 删除当前默认配置

1. 删除当前 `is_default=true` 配置
2. 期望：删除后下一次 `/preview` 请求 500 `没有可用的 LLM 配置`，提示用户去 Admin 新建并设默认

---

## 10. 通知机制

### §10.1 贡献状态通知

1. 普通用户提交贡献
2. 切到 lib_admin 批准 / 退回 / 请求修改
3. 切回原用户「通知」页或顶部 Bell 图标
4. 期望：收到对应通知（轮询更新，无需实时推送）

### §10.2 未读计数

1. 顶部导航栏 Bell 图标显示未读数字
2. 点开通知列表后未读归 0
3. 后端只在状态变更时插入 `notifications` 行；轮询接口返回新增条目

---

## 附录 A：日志/缓存排查速查

```bash
# 完整 pipeline 日志（含时间戳）
docker compose logs --timestamps backend | grep -E "\[Pipeline\]|\[Timing\]" | tail -40

# Redis 所有缓存 key 概览
docker compose exec redis redis-cli --scan | head -20

# 某 gen cache 的具体内容
docker compose exec redis redis-cli GET 'gen:<llm_config_id>:<template_id>:<version>:<params_hash>'

# Qdrant 模板点数 / 维度
docker compose exec backend python -c "
import asyncio
from app.core.vector_store import get_qdrant
from app.core.config import get_settings
async def m():
    q = get_qdrant(); s = get_settings()
    info = await q.get_collection(s.qdrant_collection)
    count = await q.count(s.qdrant_collection)
    print(f'points={count.count} dim={s.embedding_dim}')
asyncio.run(m())
"

# 当前 IntentBuilder 活跃 session 数
docker compose exec redis redis-cli --scan --pattern 'intent_builder_session:*' | wc -l

# alembic 当前版本
docker compose exec backend alembic current

# 跑全部单测
docker compose exec backend pytest tests/ --ignore=tests/test_offtopic_corpus_real_llm.py -q
```

---

## 附录 B：4 道闸错误响应结构对照

所有 4 道闸响应共享 `detail.redirect_to` 字段；前端 `handleApiError` 优先读这一字段决定是否跳路由。

| 闸 | HTTP | `detail.type` | `detail.redirect_to` | 前端行为 |
|---|---|---|---|---|
| off-topic | 422 | `off_topic` | `null` | 弹"检测到非验证请求"Modal，停留生成页 |
| code_type_mismatch | 422 | `code_type_mismatch` | `null` | 弹"代码类型选错了"Modal，含 `suggested_code_type` |
| under_specified | 422 | `under_specified` | `/intent-builder?prefill=...&template_id=...&code_type=...&missing=...` | 自动 `router.push` 进 IntentBuilder |
| empty_retrieval | 503 | `empty_retrieval` | `null` | 弹"系统暂不可用"Modal（基础设施异常） |
| contribution_parse_failed | 422 | `contribution_parse_failed` | — | 提交贡献 Modal 内 Alert 显示 `stage` + `reason` |

每个 detail 还携带专属字段（如 off_topic 的 `top_dense_score` / `threshold`，code_type_mismatch 的 `selected_score` / `suggested_score`，under_specified 的 `missing_params` 列表）。完整结构见 `backend/app/api/v1/generate.py` 各 `_*_detail()` 函数。
