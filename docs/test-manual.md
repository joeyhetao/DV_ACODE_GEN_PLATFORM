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
  - [§5.0 两种贡献入口](#50-两种贡献入口)
  - [§5.1 入口 A：GeneratePage 低置信度场景](#51-入口-a-generatepage-低置信度场景--贡献)
  - [§5.2 入口 B：「我的贡献」直接提交](#52-入口-b我的贡献--新贡献直接提交)
  - [§5.3 管理员审核流程](#53-管理员审核流程)
  - [§5.4 关键拦截路径](#54-关键拦截路径)
  - [§5.5 我的贡献页状态追踪](#55-我的贡献页状态追踪)
  - [§5.6 管理员三层防冲突面板](#56-管理员三层防冲突分析面板feat-4)
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
docker compose logs -f backend | grep -E "\[Pipeline\]|\[Gate\]|\[Timing\]|\[GLM Step|\[WARN\]|ERROR"
```

关键日志行（用于排查 §2 闸触发与 §1 参数解析）：

| 标记 | 含义 |
|---|---|
| `[Pipeline] source=... code_type=...` | preview 入口 |
| `[Pipeline] extracted from intent: {...}` | regex 提取结果 |
| `[Pipeline] params_resolved: [(name, source, value), ...]` | 每参数最终源标识，是判断 §1 高置信路径 / §2.3 under_specified 的关键 |
| `[Pipeline] under_specified gate: missing=[...]` | §2.3 闸命中 |
| `[Gate] off_topic: dense_top1=... threshold=...` | §2.1 闸命中 |
| `[Pipeline] code_type mismatch: selected=... vs suggested=...` | §2.2 闸命中 |
| `[Gate] empty_retrieval: code_type=...` | §2.4 闸命中（基础设施异常） |
| `[Timing] llm=... ms=... reasoning_tokens=...` | LLM 单次调用耗时 + 是否真关 thinking |
| `[Timing] stage=... ms=...` | preview 各阶段耗时（normalize / rag / llm_select / preview_total） |
| `ERROR ... pipeline_preview unexpected failure: user=... code_type=...` | 后端崩了，附 full traceback；前端会收 500 |

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
- 后端日志含 `[Pipeline] source=direct code_type=<type>` + `[Pipeline] params_resolved: [(name, source, value), ...]` + `[Timing] llm=...` 等段（完整对照见 §0.5）

### §1.1 数据完整性断言

| | |
|---|---|
| 输入 | `寄存器写保护场景：当写使能 wr_en 无效时，data_in 不会被意外修改` |
| code_type | SVA 断言 |
| signals 表 | **可留空**（叙述式 regex + 模板 default 兜底） |
| 期望模板 | `sva_data_integrity_v1` 数据完整性无损坏断言 |
| 关键参数 | enable=`wr_en`（regex 叙述式）/ data=`data_in`（regex 或 LLM）/ module_name=`dut`（template default）/ clk=`clk`、rst_n=`rst_n`（template default） |
| 备注 | 模板 `module_name` 自 2026-05 加了 `default: dut`；regex `_ASSERTION_SIGNAL_PATTERNS` 同步引入叙述式中文模式，让"使能 X 拉高/无效"、"被保护的数据 X" 这类未带「为/是/:」强分隔符的句子也能命中 |

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

### §5.0 两种贡献入口

| 入口 | 触发时机 | 表单预填 |
|---|---|---|
| **A：GeneratePage → IntentBuilder → 建议贡献** | IntentBuilder 连续 5 轮 RAG top-1 < 0.5，平台判断库内无匹配 | `description` 由 accumulated_intent 预填；`code_type` 由会话携带 |
| **B：「我的贡献」→「+ 新贡献」** | 用户主动发起 | 全部手填 |

两个入口最终进入相同的 4 字段提交表单：`template_name / code_type / description / demo_code`。提交后后端同步跑（5-15s）LLM 反推 + 3 道自动校验，成功返 HTTP 201，失败返 422。

---

### §5.1 入口 A：GeneratePage 低置信度场景 → 贡献

#### 用例：背压流控覆盖率（库内暂无匹配模板）

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | GeneratePage 输入 `统计背压信号 bp_n 拉低时 tx_valid 是否真的暂停，覆盖四种组合场景`，code_type 选 UVM 覆盖率，点「分析意图」 | pipeline 返回 under_specified 或 empty_retrieval → 自动跳 IntentBuilder |
| 2 | IntentBuilder 内连续对话，描述场景细节 | 右侧 RAG 候选 card 相似度持续 < 50%（橙/红色百分比标签） |
| 3 | 连续 5 轮后底部出现橙色「贡献新模板」按钮 | `suggest_contribute: true` |
| 4 | 点「贡献新模板」 | 跳转提交表单，`description` 预填 accumulated_intent，`code_type=coverage` |
| 5 | 填写模板名称（如 `背压流控覆盖率`），粘贴下方 demo_code，点提交 | HTTP 201 + `status: pending_review` + LLM 反推的 `parameter_defs` 含 `clk / bp_n / tx_valid / group_name` |

#### 提交 demo_code 示例（入口 A）

```systemverilog
// 背压流控覆盖率：统计 bp_n 拉低（施压）时 tx_valid 的四种组合场景
covergroup cg_backpressure @(posedge clk);
  option.per_instance = 1;
  option.comment = "背压流控场景覆盖";

  cp_bp: coverpoint bp_n {
    bins asserted   = {0};   // downstream 施压
    bins deasserted = {1};   // 正常传输
  }

  cp_tx: coverpoint tx_valid {
    bins sending = {1};
    bins idle    = {0};
  }

  cx_bp_x_tx: cross cp_bp, cp_tx {
    bins normal_tx   = binsof(cp_bp.deasserted) && binsof(cp_tx.sending);   // 正常发送
    bins bp_paused   = binsof(cp_bp.asserted)   && binsof(cp_tx.idle);      // 背压暂停（期望行为）
    bins bp_violated = binsof(cp_bp.asserted)   && binsof(cp_tx.sending);   // 背压违例（bug 场景）
    bins both_idle   = binsof(cp_bp.deasserted) && binsof(cp_tx.idle);      // 双方空闲
  }

endgroup

cg_backpressure cg_bp_inst = new();
```

---

### §5.2 入口 B：「我的贡献」→「+ 新贡献」直接提交

#### 用例：寄存器写后读一致性断言（用户主动贡献）

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 左侧导航进「我的贡献」，点右上角「+ 新贡献」 | 弹出 4 字段提交 Modal |
| 2 | **模板名称**：`寄存器写后读一致性断言`<br>**代码类型**：SVA 断言<br>**场景描述**：`写使能有效后，下一拍读同地址返回的数据必须与写入值相同，检测 RTL 写穿或旁路逻辑错误`<br>**代码示例**：粘贴下方 demo_code | — |
| 3 | 点「提交，由 AI 协助参数化」（5-15s） | HTTP 201 + `parameter_defs` 含 `clk / rst_n / wr_en / wr_addr / rd_addr / wr_data / rd_data`；`keywords` 含"写后读"、"一致性"；`subcategory` ≈ `data_integrity` |

#### 提交 demo_code 示例（入口 B）

```systemverilog
// 写后读一致性：wr_en 有效且地址相同时，下一拍 rd_data 必须等于写入值
property p_reg_wr_rd_consistency;
  @(posedge clk) disable iff (!rst_n)
  (wr_en && (wr_addr == rd_addr)) |=> (rd_data == $past(wr_data));
endproperty

a_reg_wr_rd_consistency: assert property(p_reg_wr_rd_consistency)
  else $error("[WR_RD] 一致性违例：rd_data=%0h expected=%0h addr=%0h",
              rd_data, $past(wr_data), rd_addr);
```

**验证后端日志**：

```bash
docker compose logs backend | grep -E "\[contribution\]|\[param_extract\]" | tail -20
```

---

### §5.3 管理员审核流程

> 角色：`lib_admin` 或 `super_admin`，入口：Admin → 贡献审核 → 点击记录展开 Drawer（三列布局）。

#### Drawer 三列说明

| 列 | 内容 | 可编辑 |
|---|---|---|
| 左列 | 用户提交原文：模板名、code_type、场景描述、原始 demo_code | 只读 |
| 中列 | LLM 反推的 Jinja2 模板体（Monaco 高亮） | ✅ 可直接编辑 |
| 右列 | parameter_defs JSON / keywords / subcategory / protocol | ✅ 可直接编辑 |

#### 审核决策树

```
打开 Drawer
│
├─ [左列] 用户意图是否属于 IC 验证范围？
│    └─ 否（FPGA 烧写 / Python 脚本等） → 「拒绝」并填 reason，流程结束
│
├─ [中列] Jinja2 模板体检查
│    ├─ {{ 变量 }} 占位符是否覆盖所有应参数化的信号名？
│    ├─ SV 语法结构是否正确（covergroup/property/endgroup 匹配）？
│    └─ 若有问题 → 在 Monaco 编辑器修改后点「保存编辑」（自动触发沙箱二次校验）
│
├─ [右列] parameter_defs / keywords 检查
│    ├─ 参数名是否 snake_case，无 SV/Python 保留字（module/always/class…）？
│    ├─ required/default/description/role_hint 是否准确？
│    ├─ 中间列 {{ var }} 与右列 parameter_defs 的 name 是否一一对应？
│    └─ 若有问题 → 在 JSON 编辑器内修改
│
├─ 点「批准并入库」→ 触发 pre-approve-analysis（详见 §5.6）
│    ├─ 无冲突 → 绿色面板 → 1s 后自动入库
│    └─ 有冲突 → 橙色面板 → 三选一：一键应用建议 / 忽略冲突 / 取消
│
└─ 整体质量差（demo 过于模糊，LLM 参数化错误率高）
     └─ 「请求修改」→ 填具体反馈 → 状态改为 needs_revision
          └─ 用户在「我的贡献」页修改 demo_code 后重提
```

#### 审核要点速查

| 检查项 | 绿灯（可批准）| 红灯（需修改 / 拒绝）|
|---|---|---|
| Jinja2 渲染 | 沙箱渲染通过，无 StrictUndefined | 含未定义变量 / dunder 访问 / 语法错误 |
| 参数名合法性 | 全 snake_case，无保留字 | 出现 `module` / `always` / `class` 等 |
| 占位符完整性 | 模板中所有 `{{ var }}` 在 parameter_defs 中有对应 `name` | `{{ signal }}` 在右列叫 `sig`（名称不一致）|
| 信号名参数化 | 原 demo 中的具体信号名（如 `bp_n`）已替换为 `{{ bp_signal }}` | 硬编码信号名残留模板体中 |
| 语义重叠 | pre-approve-analysis 无冲突，或建议修改后降至可接受 | 与已有模板 embedding 相似度 > 0.85 且描述无差异化 |

#### 请求修改时的反馈建议

反馈应指向具体问题，例如：

> "LLM 把 wr_addr 和 rd_addr 合并成一个 addr 参数，请在 demo_code 里用不同名称区分，并在描述中说明地址必须相等的条件。"

> "模板体中 tx_valid 被硬编码，请在场景描述里明确写出该信号名，让 LLM 能识别为参数。"

---

### §5.4 关键拦截路径

#### §5.4.1 重复模板名 → 422

提交时 `template_name` 与已入库 Template 重名 → HTTP 422 `contribution_name_duplicate`。

#### §5.4.2 demo_code 太烂 → LLM 反推失败 → 422

```bash
# 故意提交 garbage demo_code
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/contributions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"code_type":"assertion","template_name":"L_garbage","description":"测试","demo_code":"!!!! garbage @@@@"}'
```

期望：HTTP 422 + `detail.type="contribution_parse_failed"` + `detail.stage="param_defs_empty"`（或类似）。

#### §5.4.3 SSTI payload 提交时被拦

提交 demo_code 含 `{{ self.__class__.__bases__ }}` 这类 dunder 访问 → Sandbox 渲染失败 → 422 stage=`jinja_sandbox`。

#### §5.4.4 审核员 PATCH 后二次校验

审核员把 demo_code 改成含 SSTI 的 Jinja2 → PATCH 端点二次跑 sandbox 渲染 → 422 拒 commit，原数据不变。

#### §5.4.5 demo_code / description 超长拒

`demo_code > 32KB` 或 `description > 4KB` → Pydantic 拒 422 `string_too_long`。

#### §5.4.6 SV / Python 关键字作参数名拒

若 LLM 反推产出 `always` / `class` / `module` 等关键字作 parameter name → 拒，stage=`param_defs_name`。

### §5.5 我的贡献页状态追踪

1. 普通用户进「我的贡献」
2. 看自己提交记录的状态列：`pending_review` / `under_review` / `needs_revision` / `approved` / `rejected`
3. needs_revision 状态可点「编辑」修改后重提，状态归回 `pending_review`

### §5.6 管理员三层防冲突分析面板（FEAT-4）

> 本节覆盖 FEAT-4 新增的 pre-approve-analysis 流程。普通用户提交贡献的流程不变（§5.1）。

#### §5.4.1 无冲突场景

**前置**：库中已有若干模板；待审核贡献的语义与所有已有模板意图无显著重叠。

**步骤**：

1. lib_admin 账号，进 Admin → 贡献审核，打开待审核贡献的 Drawer
2. 点「批准并入库」
3. 按钮变灰，出现 spinner "正在分析…"（预期耗时 3-15s，取决于 LLM 速度）
4. spinner 消失后，Drawer 底部出现**绿色折叠面板**，显示：
   - "✅ 无冲突，已生成 N 条回归语料"
5. 1 秒倒计时后自动确认，可在倒计时期间点「取消」中止

**预期后端日志**（`docker compose logs -f backend | grep corpus`）：
```
[corpus] generate_corpus_cases: contribution=<id> template=<name> cases=3
[corpus] detect_conflicts: checked=<n> conflicts=0
[corpus] corpus_cases saved: contribution=<id> count=3
```

**验证 DB**：
```sql
SELECT COUNT(*) FROM template_corpus_cases
WHERE auto_generated_from = '<contribution_id>' AND is_active = true;
-- 期望：≥ 1
```

#### §5.4.2 有冲突场景

**前置**：待审核贡献与现有某模板的语义高度相近（如两者都覆盖"复位后寄存器初始值"场景）。

**步骤**：

1. 同上，点「批准并入库」→ spinner
2. spinner 消失后，Drawer 底部出现**橙色折叠面板**，显示：
   - "⚠️ 发现 N 条已有意图可能被新模板抢走"
   - 受影响意图列表（业务描述语言，不含 embedding 分数）
   - 大模型根因分析（中文，无技术术语）
   - 建议修改的字段（`description` 或 `keywords`）及建议文本
3. 操作选项 A：点「**一键应用建议修改**」
   - 中间列 description / keywords 字段自动填入建议内容
   - 面板自动重新触发 pre-approve-analysis
   - 若第二次无冲突，进入 §5.4.1 的绿色面板流程
4. 操作选项 B：点「**忽略冲突**」
   - 直接调 approve 端点，忽略冲突继续入库
   - 审计日志记录"管理员知情忽略冲突"（可在 Admin → 审计日志查到）
5. 操作选项 C：点「**取消**」
   - 回到待审核状态，不改变 contribution 状态

**预期后端日志**（`docker compose logs -f backend | grep corpus`）：
```
[corpus] generate_corpus_cases: contribution=<id> cases=3
[corpus] detect_conflicts: checked=<n> conflicts=1
[corpus] generate_llm_analysis: conflicts=1 recommendation_field=description confidence=0.87
```

#### §5.4.3 API 直接验证

```bash
TOKEN=<lib_admin_jwt>
CID=<contribution_id>

# 触发分析（非破坏性，可重复调用）
curl -s -X POST http://localhost/api/v1/admin/contributions/$CID/pre-approve-analysis \
  -H "Authorization: Bearer $TOKEN" | jq .

# 期望响应结构
# {
#   "has_conflicts": false,
#   "conflicts": [],
#   "new_corpus_preview": ["意图1", "意图2", "意图3"],
#   "llm_analysis": null,
#   "recommendation_field": null,
#   "recommendation_text": null,
#   "confidence": null,
#   "analysis_id": "<uuid>"
# }

# approve 时传 analysis_id（触发语料入库）
curl -s -X PUT http://localhost/api/v1/admin/contributions/$CID/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"analysis_id\": \"<analysis_id>\"}" | jq .
```

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
# 完整 pipeline 日志（含时间戳）—— Gate / params_resolved / ERROR 三类信号最关键
docker compose logs --timestamps backend | grep -E "\[Pipeline\]|\[Gate\]|\[Timing\]|ERROR" | tail -40

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

### 兜底 fallback 错误（非闸异常）

当后端抛非结构化异常（如 LLM vendor 错、Pydantic 校验失败、httpx 超时）时，4 道闸都不命中，FastAPI 端点统一返回 `HTTP 500 detail="<ExceptionName>: <msg>"`（preview / render / 旧 `/generate` 都做了 `logger.exception` 记 traceback），前端 `handleApiError` 走 fallback 分支：

```
message.error(`${fallbackMsg}（HTTP <status>: <detail 200 字符摘要>）`)
```

即任意 generic 失败都会显示 HTTP 状态码 + detail 摘要，方便回归测试时直接看 toast 定位是 500 / 503 / 422 异常路径。后端则可用 §0.5 的 `ERROR` 过滤抓 traceback。
