# 平台功能测试手册

> 面向：QA、产品验证、上线前回归。每个用例 = 操作步骤 + 期望效果。
> 平台版本：PRD v3.5。后端基于 5 道闸契约（off-topic / code_type_mismatch / no_matching_template / under_specified / empty_retrieval）+ FEAT-11 Stage 2 双模生成（`generation_mode ∈ {rag, llm_direct}`，详 §2.9 高置信自动渲染、§4.8 LLM 直接生成兜底）+ FEAT-12 用户对比报告系统（§4.9 用户提交 + §14 管理员审阅，独立于 §12 L3 差评通道，详 ARCHITECTURE §3.18 / §4.1.4）+ **FEAT-13 模板成熟度门控**（§7.4 admin 升降级 / §7.5 experimental 不召回 / §7.6 migration 009 backfill，RAG 三阶段默认仅消费 `maturity_level='production'`，贡献流入库默认 `experimental` 须 super_admin 显式提升，详 ARCHITECTURE §3.2/§4.1）。双模诊断说明：result 阶段 `generation_mode==='llm_direct' && parent_record_id!=null` 时同时出现两个独立按钮——FeedbackBar（§12 L3 评分）与「提交对比报告」按钮（§4.9 / §14 对比报告），分别走两条数据通道，互不阻塞、可同时使用。

---

## 目录

- [0. 测试前置](#0-测试前置)
- [1. 单条生成 — 高置信路径](#1-单条生成--高置信路径)
- [2. 单条生成 — 5 道闸触发](#2-单条生成--5-道闸触发)
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
  - [§7.4 admin 端模板成熟度切换（FEAT-13）](#74-admin-端模板成熟度切换feat-13--v35)
  - [§7.5 experimental 模板不参与 RAG 召回手测（FEAT-13）](#75-experimental-模板不参与-rag-召回手测feat-13--v35)
  - [§7.6 migration 009 backfill 验证手测（FEAT-13）](#76-migration-009-backfill-验证手测feat-13--v35)
- [8. 用户与权限](#8-用户与权限)
- [9. LLM 配置管理](#9-llm-配置管理)
- [10. 通知机制](#10-通知机制)
- [11. Step1 模板选择质量回归（混淆对语料 + reranker 阈值标定）](#11-step1-模板选择质量回归混淆对语料--reranker-阈值标定)
- [12. L3 用户反馈机制验证](#12-l3-用户反馈机制验证)
- [13. 管理员分析仪表盘使用说明](#13-管理员分析仪表盘使用说明)
- [14. 管理员对比报告审阅（FEAT-12 / v3.4）](#14-管理员对比报告审阅feat-12--v34)
- [附录 A：日志/缓存排查速查](#附录-a日志缓存排查速查)
- [附录 B：5 道闸错误响应结构对照](#附录-b5-道闸错误响应结构对照)

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
| `[Gate] offtopic selected_dense=... best_other_id=... best_other_score=... best_overall=... threshold=...` | §2.1 闸命中（v2.27 / FEAT-15 起 5 字段：selected_dense=所选 code_type 子集 top-1；best_other_id/score=非选中 code_type 中的最高分及其 id，单 code_type 时为 `None / -1.0000` 哨兵；best_overall=全库最高=`max(selected, best_other)`，与 threshold 比较） |
| `[Pipeline] code_type mismatch: selected=<ct>(<f>) vs suggested=<ct>(<f>) margin=...` | §2.2 闸命中（v2.27 / FEAT-15 起共用 §2.1 的 cross_scores 字典，需 `gap >= margin` 且 `best_other_score >= threshold` 两前提同时成立） |
| `[Gate] empty_retrieval: code_type=...` | §2.4 闸命中（基础设施异常） |
| `[Gate] no_matching_template: top_score=...` | §2.5 第五道闸命中（LLM step1 返回 none 即触发），库内无此场景模板，直跳贡献页；top_score 仅作监控参考 |
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

### §1.11 背压流控交叉覆盖率组

| | |
|---|---|
| 输入 | `统计背压信号 bp_n 拉低时 tx_valid 是否真的暂停，覆盖四种组合场景` |
| code_type | UVM 覆盖率 |
| 期望模板 | `cov_cross_coverage_v1` 交叉覆盖率组 |
| 参数 | signal_a=`bp_n`（LLM）/ signal_b=`tx_valid`（LLM）/ group_name=`cross`（默认）/ bins_a=`{0, 1}`（LLM）/ bins_b=`{0, 1}`（LLM）|
| confidence_source | `llm_step1`（LLM 主动选中，置信度 ≥ 85%）|
| 备注 | 背压流控语义与交叉覆盖率模板高度匹配；**不触发**第五道闸，直接进 ConfirmationPanel |

---

## 2. 单条生成 — 5 道闸触发

按 pipeline 顺序触发：off-topic → code_type_mismatch → no_matching_template → under_specified → empty_retrieval。

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

#### §2.2.1 错选 code_type 不应误判为 off_topic（v2.27 / FEAT-15）

**背景**：FEAT-15 前 gate 1 仅对所选 code_type 子集算 `dense_top1_score`。当用户合法 IC 意图错选了 code_type、且所选 code_type 子集刚好低于阈值时（典型 0.41 < 0.44），gate 1 直接抛 `OffTopicIntentError` 误导用户"提问非 IC 验证"——gate 2 根本拿不到执行机会。修复将 gate 1 / gate 2 判定基准统一升级为"全 code_type 库视角"（`best_overall = max(selected_dense, max(cross_code_type_scores))`），并给 gate 2 追加 `best_other_score >= threshold` 前置条件。本子节验证错选 code_type 路径正确路由到 `CodeTypeMismatchError`。

**前置准备**：

1. 库内必须已 import `cov_cross_coverage_v1` 或同语义覆盖率模板（默认种子库已含，`docker compose exec backend python lib_manager.py list --code-type coverage` 确认）
2. 相关模板 `maturity_level='production'`（默认 backfill）
3. 清意图缓存（避免 cache hit 跳过 gate）：

   ```bash
   docker compose exec redis redis-cli --raw EVAL "local keys = redis.call('KEYS', ARGV[1]); for i=1,#keys do redis.call('DEL', keys[i]); end; return #keys" 0 'intent_cache:*'
   ```

**手测步骤**：

1. 打开 `/generate`，code_type **错选**「SVA 断言」
2. 输入意图：`交叉覆盖 awsize 与 awburst 的所有合法组合`
3. 提交 preview

**期望前端**：弹"代码类型选错了"Modal，建议改为 `coverage`，停留生成页让用户切换 code_type 后重试。**不**弹"检测到非验证请求"Modal、**不**直接跳贡献页 / IntentBuilder。

**期望后端响应**：

| 字段 | 期望值 |
|---|---|
| HTTP status | `422` |
| `detail.type` | `code_type_mismatch` |
| `detail.suggested_code_type` | `coverage` |
| `detail.selected_score` | 约 0.41（assertion 子集 dense top-1） |
| `detail.suggested_score` | 约 0.76（coverage 子集 dense top-1，≥ 阈值 0.44） |
| `detail.redirect_to` | `null` |

**期望后端日志**（按顺序两行）：

```
[Timing] stage=offtopic_gate ms=<n>
[Pipeline] code_type mismatch: selected=assertion(0.4xxx) vs suggested=coverage(0.7xxx) margin=0.10
```

`[Gate] offtopic ...` 不应出现——`best_overall = max(0.41, 0.76) = 0.76 ≥ 0.44` 通过 gate 1。

**反例（旧 bug 现象，验证修复生效后不再发生）**：若 `detail.type='off_topic'`、前端弹"检测到非验证请求"Modal、后端日志出现 `[Gate] offtopic selected_dense=0.4xxx ... best_overall=0.4xxx`（best_overall 仍只看 selected）→ 说明 FEAT-15 未落地或被回滚（检查 `_compute_cross_code_type_scores` helper 是否存在 + gate 1 判定式是否用 `best_overall`）。

**API 层验证**：

```bash
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/generate/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"交叉覆盖 awsize 与 awburst 的所有合法组合","code_type":"assertion","clk":"clk","rst":"rst_n","rst_polarity":"低有效","signals":[]}' \
  | python3 -m json.tool
```

期望：`detail.type="code_type_mismatch"` + `detail.suggested_code_type="coverage"`。

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

### §2.5 no_matching_template（HTTP 422，toast + 直跳贡献页）

| | |
|---|---|
| 输入 | `统计背压信号 bp_n 拉低时 tx_valid 是否暂停，覆盖四种组合场景` |
| code_type | UVM 覆盖率 |
| 触发条件 | LLM step1 返回 none 即触发（`confidence_source=rag_fallback`）；top-1 score 不再参与触发判定，仅记入日志供监控 |
| 期望 | 前端 toast「库内暂无匹配模板，跳转至贡献页面帮助完善模板库」→ 自动 navigate，**不弹 Modal，不进 IntentBuilder** |
| detail.type | `no_matching_template` |
| detail.redirect_to | `/contribute/new?description=<url-encoded-intent>&code_type=coverage`（非 null） |
| detail.top_score | 数值（可为 ≥ 0.60，cross-encoder 词汇重叠可给满分；不再作为触发依据） |
| 后端日志 | `[Gate] no_matching_template: top_score=<n>` |

**对比验证（确保正常场景不受影响）**：输入 §1.9 意图 `对状态信号 cur_state 做 FSM 转换覆盖率`（库内有 `cov_transition_coverage_v1`）→ 应进 under_specified → IntentBuilder，**不触发**此闸。

**API 层验证**：

```bash
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/generate/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"统计背压信号 bp_n 拉低时 tx_valid 是否暂停，覆盖四种组合场景","code_type":"coverage","clk":"clk","rst":"rst_n","rst_polarity":"低有效","signals":[]}' \
  | python3 -m json.tool
```

期望：`detail.type="no_matching_template"` + `detail.redirect_to` 以 `/contribute/new?` 开头。

#### §2.5.1 手测验证 step1 数字解析修复（v2.26 / FEAT-14）

**背景**：`_step1_select_id`（`openai_compat_client.py`）偶发把候选序号字符串（如 `'3'`）当 `template_id` 返回，原解析层只做精确 id 匹配，导致 `selected=""` → `confidence_source=rag_fallback` → `no_matching_template` 闸误触发，正确候选被丢弃。v2.26 / FEAT-14 双管齐下修复：(A) 解析层数字兜底——raw 是纯数字 N（`1 ≤ N ≤ len(candidates)`，允许前后空白 / 尾部句号 / 引号包裹）时映射到 `candidates[N-1]['template_id']`；(B) `_render_step1_candidate` 候选块从 Markdown `### {N}.` 改为 XML `<candidate id="...">`，从视觉上消除序号心智。本子节验证两条都生效。

**前置准备**：

1. 库内必须已 import `sva_handshake_timeout_v1` 模板（默认种子库已含；可通过 `docker compose exec backend python lib_manager.py list --code-type assertion` 确认）
2. 该模板 `maturity_level='production'`（默认 backfill；非 production 会被 RAG 三阶段过滤掉）
3. 清意图缓存（避免 cache hit 跳过 step1）：

   ```bash
   docker compose exec redis redis-cli --raw EVAL "local keys = redis.call('KEYS', ARGV[1]); for i=1,#keys do redis.call('DEL', keys[i]); end; return #keys" 0 'intent_cache:*'
   ```

   期望输出：被删除的 key 数（≥ 0 均可）

**手测步骤**：

1. 打开 `/generate`，code_type 选「SVA 断言」
2. 输入意图：`AXI valid-ready 握手超时检测：awvalid 拉高后 16 周期内 awready 必须响应`
3. 提交 preview
4. **期望前端**：进入 ConfirmationPanel 或 quick_render（视 high-confidence-rag 条件而定），`template_id` 显示为 `sva_handshake_timeout_v1`，**不**跳转 `/contribute/new`
5. **期望后端日志**（任选一种均算修复生效）：

   - **理想态（B 完全消除编号心智）**：

     ```
     [GLM Step1] raw='sva_handshake_timeout_v1'
     ```

     表明 XML 化后 LLM 直接返完整 template_id，根本没机会返编号

   - **次优态（A 兜底生效）**：

     ```
     [GLM Step1] raw='3'   (或 raw='3.' / raw=' 3 ' / raw='"3"' 等变体)
     [GLM Step1] raw was integer 3 → resolved to 'sva_handshake_timeout_v1'
     ```

     表明 LLM 仍偶发返编号但兜底成功 resolve，`confidence_source` 保持 `llm_step1`

6. 若后端日志出现 `[Gate] no_matching_template: top_score=<n>` 且前端跳转 `/contribute/new`，说明修复**未生效**——核对 `_step1_select_id` 解析逻辑（数字兜底块是否在精确匹配失败后、`return ""` 之前）以及 `_render_step1_candidate` 输出是否含 `<candidate id="` / 不含 `### `

**API 层独立验证**：

```bash
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/generate/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"AXI valid-ready 握手超时检测：awvalid 拉高后 16 周期内 awready 必须响应","code_type":"assertion","clk":"clk","rst":"rst_n","rst_polarity":"低有效","signals":[]}' \
  | python3 -m json.tool
```

期望：返回正常 preview 响应（含 `template_id="sva_handshake_timeout_v1"` + `confidence_source="llm_step1"`），**不**是 422 `no_matching_template`。

**自动化回归**：本场景已固化到 `backend/tests/test_step1_numeric_fallback.py`（数字兜底全路径）+ `backend/tests/test_step1_prompt_xml.py`（prompt XML 格式断言），CI 必跑。手测仅用于真 LLM 模型变更 / prompt 大改时的 sanity check。

### §2.6 5 道闸响应结构验证（API 层）

```bash
# under_specified detail 必含 redirect_to 字符串
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/generate/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"生成一个 FSM 转换覆盖率","code_type":"coverage","clk":"clk","rst":"rst_n","rst_polarity":"低有效","signals":[]}' \
  | python3 -m json.tool
```

期望响应：`detail.type="under_specified"` + `detail.redirect_to` 是非空字符串以 `/intent-builder?` 开头。

### §2.7 step1 二次验证开关（A8，pipeline 内置 LLM 自审）

**背景**：当 LLM step1 选中模板且 `confidence_source == "llm_step1"` 时，pipeline 调用 `llm.verify_step1_selection(normalized_intent, selected_id, candidates)` 发一条 yes/no 二次问询确认核心验证语义是否一致；LLM 答 `no` → `confidence_source` 降级为 `rag_fallback`，让第五道闸 `NoMatchingTemplateError`（若开启）接管引导贡献。**默认 `STEP1_VERIFY_ENABLED=false`**（开启前需先用 §11 confusion corpus 的 real-llm 套件评估误拒率）。fail-open：LLM 调用失败/解析失败一律视为 yes。

**关掉时（默认行为）验证**：

```bash
# 在 backend 容器内（确保 settings 未设环境变量）
docker compose exec backend python -c "from app.core.config import get_settings; print(f'STEP1_VERIFY_ENABLED={get_settings().step1_verify_enabled}')"
```

期望输出：`STEP1_VERIFY_ENABLED=False`。任何 §1.x 用例通过后，后端日志**不应**出现 `[Timing] stage=step1_verify` 行。

**开启后（实验性）验证**：

1. 修改 `.env` 或导出 `STEP1_VERIFY_ENABLED=true`，重启 backend：
   ```bash
   docker compose restart backend
   ```
2. 跑一条已知能命中模板的高置信意图（例如 §1.3 握手数据稳定断言）
3. 后端日志期望：
   ```
   [Timing] stage=step1_verify ms=<n> ok=True
   ```
   `ok=True` 表示 LLM 答 yes，确认与 step1 选择一致，`confidence_source` 保持 `llm_step1`
4. 跑一条易混淆意图（从 `backend/tests/data/template_confusion_corpus.yaml` 取一条，注入 RAG 把 `confusion_template` 顶到 top-1）
5. 后端日志期望两段连续输出（仅当 LLM 决策反转时才出现）：
   ```
   [GLM Step1Verify] id=<confusion_id> raw='no'
   [Pipeline] step1 verify=no: id=<confusion_id> → confidence_source 降级为 rag_fallback
   ```
   后续走 RAG fallback / 第五道闸路径

**关闸单测**：`backend/tests/test_pipeline_preview_render.py` 中以 `step1_verify_enabled=False`、`return_value=True`、`return_value=False` 三组用例覆盖三档行为。

### §2.8 reranker score gate（A9，pipeline 层独立 gate）

**背景**：A8 验证通过后，pipeline 查 LLM 选中的 `template_id` 在 `rag_candidates` 中的 `score` 字段（即 stage3 reranker score，由 `services/rag/engine.py` enriched 写入）。若 `score < RERANKER_MIN_SCORE_THRESHOLD`（默认 0.30 经验占位）且 `STEP1_RERANKER_GATE_ENABLED=true` → 抛 `NoMatchingTemplateError(top_score=selected_score)` 直跳贡献页。**默认 `STEP1_RERANKER_GATE_ENABLED=false`**（开启前必须先跑标定脚本，未标定就上生产会误拒 marginal 真请求）。

**与 FIX-9 移除的 `no_match_score_threshold` 的区分**：FIX-9 拦 RAG **top-1** score（已移除）；A9 拦 **LLM 选中** 的那个 id 的 reranker score。`no_match_score_threshold` 字段保留供日志/监控参考，**不**参与触发判定。

**量化验证流程（A9 阈值标定）**：

1. **前置**：确认 `llm_configs` 表已配 `is_default=true` 记录；Qdrant 已 import 全部模板（`docker compose exec backend python lib_manager.py import`）；embedding_service 健康
2. 运行标定脚本：
   ```bash
   docker compose exec backend python scripts/calibrate_reranker_threshold.py
   ```
3. **阶段 1（selection corpus）期望输出**：每条 intent 列 `normalized` + top-N 模板列表 + `correct` 模板分数（若 correct 不在 top-N 则记 `MISS`）
4. **阶段 2（confusion corpus）期望输出**：每条 case 列 `correct_template` 与 `confusion_template` 的 reranker score 对照
5. **阶段 3（汇总）期望输出**：
   ```
   [correct]   N=<n> p10=<x> p50=<y> p90=<z>
   [confusion] N=<n> p10=<x> p50=<y> p90=<z>
   [suggest]   reranker_min_score_threshold = max(correct_p10 - ε, confusion_p50 + ε)
   ```
6. **解读规则**：
   - `correct_p10 > confusion_p50` 且分隔明显 → 取中点写入 `backend/app/core/config.py::reranker_min_score_threshold` 默认值，然后 `STEP1_RERANKER_GATE_ENABLED=true` 可开启
   - `correct_p10 < confusion_p50` 两段分布重叠 → **标定无解**，不要直接放宽阈值；优先在 §11 confusion corpus 加样本 / 模板 `differentiators` 补强 / 重训 reranker / 换 embedding model 后再标定
7. 标定结果是给人工拍板用的，**脚本本身不进 CI**（依赖 live embedding service 与 Qdrant）

**开启后（实验性）验证**：

1. `.env` 设 `STEP1_RERANKER_GATE_ENABLED=true` 与标定建议的 `RERANKER_MIN_SCORE_THRESHOLD=<x>`，重启 backend
2. 跑一条已知 reranker score 偏低（< 阈值）但 LLM 选中的意图
3. 后端日志期望：
   ```
   [Gate] step1_reranker_gate: id=<tid> selected_score=<x.xxxx> < threshold=<y> → NoMatchingTemplate
   ```
4. 前端期望：toast「库内暂无匹配模板，跳转至贡献页面帮助完善模板库」→ 自动 navigate `/contribute/new?...`

**关闸单测**：`backend/tests/test_pipeline_preview_render.py` 中以 `step1_reranker_gate_enabled` 开关 + `selected_score < threshold` / `selected_score > threshold` 三组用例覆盖三档行为。

### §2.9 高置信 RAG 自动渲染（FEAT-11 A，正向路径）

> 本节是 §2 中**唯一的非闸场景**——它不是错误路径，而是 FEAT-11 Stage 2 A 子项落地的"高置信免确认"短路。把它放在 §2 是因为触发条件与 A8 / A9 强相关；走的不是闸路径，而是 `quick_render=True` 旗标。

**背景**：当 `pipeline_preview` 同时满足以下四条件时，`PreviewResult.quick_render=True`，前端 `GeneratePage` 跳过 ConfirmationPanel 直接调 `/render` 一步出代码。任一条件不达标即保留默认 ConfirmationPanel 流程（无回归）。

| # | 条件 | 来源 / 控制 |
|---|---|---|
| 1 | `confidence_source == "llm_step1"` | pipeline.py Step 5a，LLM 主动选中（未走 rag_fallback/keyword_supplement/intent_cache） |
| 2 | `step1_verify_enabled == True` AND A8 二次验证 `verify_ok=True` | `STEP1_VERIFY_ENABLED` env，A8 disabled 时不达标 |
| 3 | `selected_score >= reranker_min_score_threshold`（默认 0.30） | A9 共用同一份 selected_score |
| 4 | 所有 required param sources ∈ `{llm, regex, signal_list, default}` | `_map_params_with_source` 输出，不含 `semantic_fallback` / `placeholder` |

**正向验证步骤**：

1. **前置**：开启 A8（`STEP1_VERIFY_ENABLED=true`），重启 backend：
   ```bash
   docker compose restart backend
   ```
2. 跑一条已知能高置信命中模板的意图，例如 §1.3 **握手数据稳定断言**：
   - 输入：`AXI 写通道 awvalid 拉高后 awaddr 必须保持稳定到 awready`
   - 信号表：awvalid(role=valid)、awready(role=ready)、awaddr(role=data)
   - code_type：SVA 断言
3. 点「分析意图」 → **预期前端不显示 ConfirmationPanel**，直接跳到 result 阶段展示代码
4. 后端日志期望（§0.5）连续两段：
   ```
   [Timing] stage=step1_verify ms=<n> ok=True
   [Pipeline] high_confidence_rag: tid=sva_handshake_stable_v1 score=<x.xxxx> → quick_render=True
   ```
5. SQL 验证写入：
   ```sql
   SELECT generation_mode, cache_hit, template_id, confidence
     FROM generation_records ORDER BY created_at DESC LIMIT 1;
   ```
   期望：`generation_mode='rag'`, `template_id='sva_handshake_stable_v1'`, `confidence` ≥ 阈值

**反向验证（任一条件失败应回到 ConfirmationPanel）**：

| 故意失败的条件 | 复测方法 | 期望 |
|---|---|---|
| 条件 1（confidence_source != llm_step1） | 让 LLM step1 返 `none`（用一条无库内匹配的"边界场景"意图） | 走 rag_fallback，前端展示 ConfirmationPanel + 顶部低置信提示条 |
| 条件 2（A8 verify 失败） | 用 §11 confusion corpus 任一条样本（注入 confusion_template 到 RAG top-1，A8 应答 no） | `confidence_source` 降级 rag_fallback，前端展示 ConfirmationPanel；日志含 `[Pipeline] step1 verify=no` |
| 条件 3（selected_score < 阈值） | 把 `RERANKER_MIN_SCORE_THRESHOLD` 临时调高（如 0.95），重启 backend，跑同一条意图 | 日志 `[Pipeline] high_confidence_rag: ... → quick_render=False`，前端展示 ConfirmationPanel |
| 条件 4（含 semantic_fallback / placeholder 源） | 跑一条少填一个 required 参数的意图（如 §1.9 转换覆盖率不填 state_list） | 通常 under_specified 闸已先触发；若 gate 关闭则保留 ConfirmationPanel + 红色占位徽标 |

**关闸单测**：`backend/tests/test_pipeline_preview_render.py` 中以"四条件齐绿 → quick_render=True"以及四条件各自单独 disqualify（保持其余三条件齐绿、单独翻转一条）的回归用例覆盖。

**与 §3.1 intent_cache 命中的区别**：两者都让 `quick_render=True`，前端代码路径完全一致；差异仅在 `confidence_source` 字段（`intent_cache` vs `llm_step1`）与对应的置信徽标颜色。intent_cache 命中是"历史已生成过"的二次复用，A 子项是"首次但高置信"的免确认。

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
4. 点「分析意图」→ 期望本次 5 道闸全过，到 ConfirmationPanel

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

### §4.8 LLM 直接生成兜底（FEAT-11 Stage 2 B 子项）

> 本节是 §4 中**唯一与 IntentBuilder 无关**的子节——它放在 §4 是因为同属"用户对 RAG 结果不满意时的自助救济"主题（IntentBuilder 走 RAG 精修，LLM 直接生成走非确定性 bypass）。详 ARCHITECTURE §3.17。

`POST /api/v1/generate/llm-fallback` 接收 `{generation_record_id}`，载入源记录的 `original_intent + code_type + signals + clk + rst`，调 `LLMClient.generate_code_freeform` 自由生成 SystemVerilog 代码（**不经 Jinja2 模板渲染**），写新 `GenerationRecord(generation_mode='llm_direct', parent_record_id=source.id)` 返回。

#### §4.8.1 Happy path（前端按钮触发）

**前置**：跑一次 §1 任意成功生成 → 停在 result 阶段；后端日志（§0.5）已显示 `generation_mode="rag"` 写入。

1. 代码卡片下方应出现 secondary Button「对生成结果不满意？尝试 LLM 直接生成」（紧邻 FeedbackBar）
2. 点击按钮 → 按钮进入 loading 状态（spinner），上方文案"RAG 结果不符合预期？可以让 LLM 直接生成（结果是非确定性的，每次可能不同）。"
3. 期望（5-30s 取决于 LLM 配置）：
   - 代码区被替换为新代码（可能与原 `rag` 结果不同）
   - 代码卡片头部出现橙色标签 `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>`
   - **fallback 按钮消失**（因为 `state.result.generation_mode === 'llm_direct'` 不再展示按钮）
   - FeedbackBar 重新激活（`feedbackSubmitted` 归零）允许独立评分 `llm_direct` 结果
   - 顶部 `message.success('已切换为 LLM 直接生成')`
4. 后端日志期望：
   ```
   POST /api/v1/generate/llm-fallback HTTP/1.1" 200
   [Timing] llm=<name> ms=<n> reasoning_tokens=0 thinking=off  (generate_code_freeform)
   ```
5. SQL 验证：
   ```sql
   SELECT id, generation_mode, parent_record_id, template_id, output_code IS NULL AS empty_code
     FROM generation_records ORDER BY created_at DESC LIMIT 2;
   ```
   期望：最新一行 `generation_mode='llm_direct'`, `parent_record_id` = 上一条 `rag` 记录的 id, `template_id IS NULL`, `empty_code = false`

#### §4.8.2 cache hit（同一输入二次触发）

1. 完成 §4.8.1 后停在 result 页（已是 `llm_direct`）
2. 重新跑一次 §1 同一意图（必须**清 intent_cache** 让 preview 跑完整流程，避免短路）：
   ```bash
   docker compose exec redis redis-cli --scan --pattern 'intent_cache:*' \
     | xargs -r docker compose exec -T redis redis-cli DEL
   ```
3. 到 result 阶段（新的 `rag` 记录）→ 点 fallback 按钮
4. 期望（< 200ms）：响应中 `cache_hit: true`，代码与第一次完全一致（gen_llm 缓存命中）
5. 后端日志期望：**不**出现 `[Timing] llm=...` 段（因为 cache hit 跳过 LLM 调用）
6. Redis 验证 cache key 存在：
   ```bash
   docker compose exec redis redis-cli --scan --pattern 'gen_llm:*' | head -5
   docker compose exec redis redis-cli TTL <key>
   ```
   期望：TTL 接近 604800（7d）

#### §4.8.3 错误场景（API 直接验证）

```bash
TOKEN=<jwt>
# 1) record 不存在 → 404
curl -s -X POST http://localhost/api/v1/generate/llm-fallback \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"generation_record_id":"00000000-0000-0000-0000-000000000000"}' -w "\nHTTP %{http_code}\n"
# 期望：HTTP 404，detail 是纯字符串 "源生成记录不存在"（不带 type 字段；
#       这是 FastAPI 默认 HTTPException(detail=str) 形态，与 422/500 的结构化
#       detail dict 不同——前端只看 HTTP 状态码即可识别 404）

# 2) 源 record 已是 llm_direct → 422 chained_not_allowed
LLM_DIRECT_ID=$(docker compose exec -T postgres psql -U postgres -d ic_codegen -t -c \
  "SELECT id FROM generation_records WHERE generation_mode='llm_direct' ORDER BY created_at DESC LIMIT 1" | tr -d ' ')
curl -s -X POST http://localhost/api/v1/generate/llm-fallback \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"generation_record_id\":\"$LLM_DIRECT_ID\"}" -w "\nHTTP %{http_code}\n"
# 期望：HTTP 422，detail.type="llm_direct_chained_not_allowed"，
#       message 含"已是 LLM 直接生成结果，不支持链式兜底"

# 3) llm_direct_no_code（HTTP 422）+ llm_direct_internal_error（HTTP 422 或 500）
#    无法在生产环境稳定复现（依赖 LLM 输出形态 / 基础设施故障），由
#    backend/tests/test_llm_direct_generation.py 与 test_llm_freeform_client.py
#    的 mock 单测覆盖：
#    - test_llm_freeform_client.py::test_prose_only_raises_no_sv_code_block
#    - test_llm_direct_generation.py::test_endpoint_llm_no_code_returns_422
#      （ValueError("no_sv_code_block") → 422 llm_direct_no_code）
#    - test_llm_direct_generation.py::test_endpoint_llm_value_error_returns_422
#      （非 no_sv_code_block 的 ValueError → 422 llm_direct_internal_error，
#       前端可建议用户重试）
#    - test_llm_direct_generation.py::test_endpoint_llm_exception_returns_500
#      （非 ValueError 的 Exception → 500 llm_direct_internal_error，前端
#       toast 含 HTTP 500，需 SRE 排查；同 type 但 HTTP 状态不同）
#    本地跑：docker compose exec backend pytest tests/test_llm_direct_generation.py tests/test_llm_freeform_client.py -v
```

#### §4.8.4 analytics filter 手测

`/admin/analytics/*` 4 个端点全部新增 optional `generation_mode` 参数。完成 §4.8.1 + §12（提交 L3 反馈给两个 record）后：

```bash
ADMIN_TOKEN=$(curl -s -X POST http://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<pw>"}' | jq -r .access_token)

# 1) 仅 rag 桶
curl -s "http://localhost/api/v1/admin/analytics/feedback-summary?days=7&generation_mode=rag" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq

# 2) 仅 llm_direct 桶
curl -s "http://localhost/api/v1/admin/analytics/feedback-summary?days=7&generation_mode=llm_direct" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
# 期望：total_generations / total_feedbacks 都 ≥ 1，仅包含 llm_direct 路径

# 3) llm_direct 桶 + template-issues（template_id 全为 NULL，归入 __llm_direct__ 桶）
curl -s "http://localhost/api/v1/admin/analytics/template-issues?days=7&generation_mode=llm_direct&limit=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
# 期望：返回数组每行 template_id == "__llm_direct__"（FEAT-11 约定的桶 key）

# 4) llm_direct 桶 + no-match-rate（恒返 no_match_rate=0 行）
curl -s "http://localhost/api/v1/admin/analytics/no-match-rate?days=7&generation_mode=llm_direct" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
# 期望：每行 no_match_count=0, no_match_rate=0.0；这是设计内行为
# （llm_direct 路径绕过五闸，gate_error_type 恒 NULL）

# 5) omit 参数 → 全量（rag + llm_direct 都进桶）
curl -s "http://localhost/api/v1/admin/analytics/feedback-summary?days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
# 期望：total_generations 是 rag + llm_direct 之和
```

**非法参数验证**：
```bash
curl -s -w "\nHTTP %{http_code}\n" \
  "http://localhost/api/v1/admin/analytics/feedback-summary?days=7&generation_mode=invalid" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# 期望：HTTP 422，detail 含 "literal_error"（Pydantic Literal['rag','llm_direct'] 校验）
```

### §4.9 用户提交对比报告（FEAT-12 / v3.4）

> 本节与 §4.8 同源（用户对 LLM 直接生成结果的后续动作），但目标不同：§4.8 是兜底救济（生成代码），本节是质量信号采集（让 admin 关注成对差异）。详 PRD §6.2 / ARCHITECTURE §3.18。

`POST /api/v1/improvement-reports` 接收 `{rag_record_id, llm_direct_record_id, report_categories?, reporter_note?}`，后两个字段**均可全空**仍 201 成功。前端按钮在 result 阶段独立于 FeedbackBar 渲染，仅当 `generation_mode==='llm_direct' && parent_record_id != null` 时出现。

#### §4.9.1 Happy path — RAG 高置信生成 → LLM 直接生成 → 提交对比报告

**前置**：清三层缓存（§0.3 `gen:*` + `intent_cache:*` + `gen_llm:*`），让流程从冷启动跑完整路径。

1. 跑 §1 任意成功生成，停在 result 阶段，确认代码卡片头部无橙色 Tag、按钮区只有 FeedbackBar（**不**应出现「提交对比报告」按钮，因为 `generation_mode==='rag'`）
2. 点击代码卡片下方「对生成结果不满意？尝试 LLM 直接生成」（§4.8.1），等待替换为 `llm_direct` 代码
3. 期望（FEAT-12 标识三处同步）：
   - 代码卡片头部出现 `<Tag color="orange">LLM 直接生成 · 非确定性</Tag>`（§4.8.1 既有）
   - **新增**：FeedbackBar 旁出现独立 secondary Button「提交对比报告」，按钮 **enabled**（mount 时调 `GET /improvement-reports/check?rag_record_id=&llm_direct_record_id=` 返 `{exists: false}`）
   - 后端日志：`GET /api/v1/improvement-reports/check?rag_record_id=...&llm_direct_record_id=... HTTP/1.1" 200`
4. 点击「提交对比报告」→ 弹出 Modal：
   - 标题"提交对比报告"
   - `Checkbox.Group` 4 项（无必填星号）：模板选错 / 参数映射错 / 代码风格差 / 其他
   - `Input.TextArea` rows=4，placeholder "可描述 RAG 与 LLM 直接生成的差异（选填）"
   - 「提交」按钮**始终 enabled**（与 §12 差评 Modal 不同——后者不选 reason_tags 拒绝提交）
   - 「取消」按钮
5. **不勾任何分类、不写任何 note**，直接点「提交」
6. 期望：
   - HTTP 201 响应体 `{id: <uuid>, status: 'pending', created_at: ..., report_categories: [] or null, reporter_note: null, ...}`
   - Modal 自动关闭
   - 「提交对比报告」按钮置灰、文案改为「已提交」
   - 顶部 `message.success('已提交对比报告，admin 处理中')`
7. 后端日志期望：
   ```
   POST /api/v1/improvement-reports HTTP/1.1" 201
   ```
8. SQL 验证：
   ```bash
   docker compose exec postgres psql -U dvuser -d dv_platform -c \
     "SELECT id, status, report_categories, reporter_note IS NULL AS note_null, created_at \
      FROM improvement_reports ORDER BY created_at DESC LIMIT 1;"
   ```
   期望：`status='pending'`, `report_categories` 为 `null` 或 `[]`, `note_null=t`

#### §4.9.2 重复提交按钮 disabled（409 拦截）

**前置**：完成 §4.9.1。

1. 不刷新页面，**手动改 `state.reported = false`**（DevTools React 改 state）或刷新页面让前端 mount 重新调 `check` 端点
2. 期望刷新后：
   - `GET /improvement-reports/check?rag_record_id=&llm_direct_record_id=` 返 `200 {exists: true, report_id: <uuid>}`
   - 「提交对比报告」按钮初始即 disabled、文案"已有人提交对比报告，admin 处理中"
3. **直接调 API 验证 409 兜底**（前端守门失效时的最后防线）：
   ```bash
   TOKEN=<jwt>
   RAG_ID=<上一步的 rag_record_id>
   LLM_ID=<上一步的 llm_direct_record_id>
   curl -s -X POST http://localhost/api/v1/improvement-reports \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d "{\"rag_record_id\":\"$RAG_ID\",\"llm_direct_record_id\":\"$LLM_ID\"}" \
     -w "\nHTTP %{http_code}\n"
   ```
   期望：HTTP 409，`detail.type="duplicate_report"`，`detail.existing_report_id` 为 §4.9.1 创建的 UUID

#### §4.9.3 FK 缺失场景（422 invalid_record_ref）

```bash
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/improvement-reports \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"rag_record_id":"00000000-0000-0000-0000-000000000000","llm_direct_record_id":"00000000-0000-0000-0000-000000000001"}' \
  -w "\nHTTP %{http_code}\n"
```

期望：HTTP 422，`detail.type="invalid_record_ref"`。

#### §4.9.4 未登录 401

```bash
curl -s -X POST http://localhost/api/v1/improvement-reports \
  -H "Content-Type: application/json" \
  -d '{"rag_record_id":"<any>","llm_direct_record_id":"<any>"}' \
  -w "\nHTTP %{http_code}\n"
```

期望：HTTP 401（无 Authorization header）。

#### §4.9.5 按钮不渲染场景（`generation_mode === 'rag'`）

**前置**：完成 §1 任意成功生成，停在 result 阶段（`generation_mode==='rag'`）。

1. 检查代码卡片下方
2. 期望：**仅** FeedbackBar 出现，不应出现「提交对比报告」按钮——前端守门 `state.result.generation_mode === 'llm_direct' && parent_record_id != null` 不满足

---

## 5. 模板贡献机制

### §5.0 两种贡献入口

| 入口 | 触发时机 | 表单预填 |
|---|---|---|
| **A：GeneratePage → 第五道闸直跳（首选路径）** | LLM step1 返回 none 即触发（`confidence_source=rag_fallback`）；preview 阶段即判定库内无此场景，top-1 score 不参与触发判定（仅记入日志供监控） | `description` 由 original_intent URL 编码预填；`code_type` 由 URL 参数携带 |
| **A（边界降级）：GeneratePage → IntentBuilder → 建议贡献** | LLM step1 选中了某个 RAG 候选但下游 `under_specified` 闸命中（描述模糊参数缺失），走 IntentBuilder 5 轮后 `suggest_contribute=true` | `description` 由 accumulated_intent 预填；`code_type` 由会话携带 |
| **B：「我的贡献」→「+ 新贡献」** | 用户主动发起 | 全部手填 |

三个路径最终进入相同的 v3.1 两步 Modal：**Step 0 仅 2 字段必填** `original_intent + code_type`，点「生成预览」调 `POST /api/v1/contributions/preview` 不入库地让 LLM 同时产出 `template_name / description / demo_code / parameter_defs / keywords`；**Step 1** 用户对 LLM 输出做语义级校对（编辑或接受 3 字段）后点「提交审核」或「立即使用」，调 `POST /api/v1/contributions` 入审核队列。两端点都跑同样 4 道校验闸（`template_name` 命名规范 + parameter_defs 命名 + Jinja2 沙箱渲染 + keywords 形态），任一失败返 422 `contribution_parse_failed`（含 `detail.stage` / `detail.reason`）；submit 端点额外做 name 精确查重（422 `contribution_name_duplicate` 阻塞）+ 语义查重（top-3 写入 `original_row_json["similar_templates"]` 非阻塞）。原 4 字段提交路径（caller 显式传 `template_name + description + demo_code`）作为分支 3 完全向后兼容。详见 §5.7。

---

### §5.1 入口 A：GeneratePage 低置信度场景 → 贡献

#### 前置：必须清 intent_cache

```bash
docker compose exec redis redis-cli --scan --pattern 'intent_cache:*' \
  | xargs -r docker compose exec -T redis redis-cli DEL
```

intent_cache 命中时流水线直接短路返回缓存结果，第五道闸永远不会触发。**每次测试本节前必须先清缓存。**

#### 用例：总线仲裁互斥约束断言（库内暂无匹配模板）

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | GeneratePage 输入 `断言 cpu_req 和 dma_req 不能在同一时钟周期同时有效，验证总线仲裁互斥约束`，code_type 选 **SVA 断言**，点「分析意图」 | 不弹 Modal，不跳 IntentBuilder；前端弹蓝色 toast「库内暂无匹配模板，跳转至贡献页面帮助完善模板库」，随即自动 navigate 到贡献提交页 |
| 2 | 检查跳转后页面 URL 应含 `description=` 和 `code_type=assertion` | 表单 description 字段已预填总线仲裁互斥意图原文，code_type 预选 SVA 断言 |
| 3 | 填写模板名称（如 `总线仲裁互斥约束断言`），粘贴下方 demo_code，点「提交，由 AI 协助参数化」 | HTTP 201 + `status: pending_review` + LLM 反推的 `parameter_defs` 含 `clk / rst_n / req_a / req_b`（或等价的两路请求信号名） |

**为什么这个场景能触发第五道闸**：库内 6 个 assertion 模板分别覆盖数据稳定 / 最大延迟 / 握手超时 / 复位值 / FSM 转换 / 握手数据稳定，没有任何一个涉及"两信号互斥 / one-hot / 竞争检测"语义。FIX-8 后，LLM step1 在系统提示中被明确禁止"通过信号名重命名（如把 `cpu_req` / `dma_req` 重映射为握手模板的 `valid` / `ready`）强行适配语义不符的模板"，因此对互斥场景必返 `"none"`，`pipeline.py` 取 RAG 顶点候选并写入 `confidence_source="rag_fallback"`；FIX-9 后闸只依赖 `confidence_source=rag_fallback`（LLM step1 返 none）即触发 `NoMatchingTemplateError`——即使 cross-encoder reranker 因 `req` 词汇重叠对 `sva_timing_max_delay_v1` 给 1.0 满分，也不再阻拦闸生效。

> **回归对照（应继续命中正常路径，不被新规则误拒）**：意图 `awvalid 拉高后 awready 未到来期间 awaddr 必须保持稳定` 选 SVA 断言 → LLM step1 仍应选中 `sva_handshake_stable_v1`，走 ConfirmationPanel；意图 `检测 cur_state 从 IDLE 到 ACTIVE 的转换` 选 UVM 覆盖率 → 仍应选中 `cov_transition_coverage_v1`。

#### 提交 demo_code 示例（入口 A）

```systemverilog
// 总线仲裁互斥约束：cpu_req 与 dma_req 不能在同一拍同时拉高
property p_bus_grant_mutex;
  @(posedge clk) disable iff (!rst_n)
  !(cpu_req && dma_req);
endproperty

a_bus_grant_mutex: assert property(p_bus_grant_mutex)
  else $error("[ARB] 总线仲裁冲突：cpu_req=%0b dma_req=%0b 同拍同时有效",
              cpu_req, dma_req);
```

---

### §5.2 入口 B：「我的贡献」→「+ 新贡献」直接提交

#### 用例：寄存器写后读一致性断言（用户主动贡献，v3.1 两步流）

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 左侧导航进「我的贡献」，点右上角「+ 新贡献」 | 弹出两步 Modal，停在 Step 0 |
| 2 | **Step 0** — **`original_intent`**：`写使能有效后，下一拍读同地址返回的数据必须与写入值相同，检测 RTL 写穿或旁路逻辑错误`；**`code_type`**：SVA 断言 → 点「生成预览」（5-15s） | LLM 同时产出 `template_name`（按 `sva_*_v1` 规范）、`description`、`demo_code` 三字段，进入 Step 1 |
| 3 | **Step 1** — 检查/微调三字段（如把 LLM 起的名换成 `sva_reg_wr_rd_consistency_v1`），点「提交审核」 | HTTP 201 + `status: pending_review` + `use_immediately_available: true`；后端 `parameter_defs` 含 `clk / rst_n / wr_en / wr_addr / rd_addr / wr_data / rd_data`；`keywords` 含"写后读"、"一致性"；`subcategory` ≈ `data_integrity` |

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

### §5.7 贡献预览端点 smoke test（FEAT-10）

> 本节覆盖 FEAT-10 新增的 `POST /api/v1/contributions/preview`——前端两步 Modal Step 0 → Step 1 跳转的后端入口。**不入库**，仅返回 LLM 生成预览供用户在 Step 1 编辑/确认；解析失败统一 422 `contribution_parse_failed`，name 命中已有模板时携 `name_conflict: true` 非阻塞标记。

#### §5.7.1 正常生成

**前置**：`llm_configs` 默认行可用、`embedding_service` 在线。

```bash
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/contributions/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"original_intent":"检测AXI写通道在awvalid拉高到awready到来期间地址保持稳定","code_type":"assertion"}' | jq .
```

**期望**：HTTP 200，响应体形如：

```json
{
  "template_name": "sva_axi_aw_addr_stable_v1",
  "description": "在 AXI 写通道 awvalid 拉高到 awready 之间，awaddr 必须保持稳定",
  "demo_code": "property p_axi_aw_addr_stable;\n  @(posedge clk) ...",
  "parameter_defs": [
    {"name": "clk", "type": "string", "required": true, "description": "时钟信号", "expr_type": "sv_identifier"},
    {"name": "awvalid", "type": "string", "required": true, "description": "...", "expr_type": "sv_identifier"},
    ...
  ],
  "keywords": ["AXI", "写通道", "地址稳定", ...],
  "name_conflict": false
}
```

**验证要点**：

- `template_name` 匹配 `^(sva|cov)_[a-z][a-z0-9_]*_v\d+$`（assertion 应以 `sva_` 开头，coverage 应以 `cov_` 开头）
- `parameter_defs` 每项含 `name / type / required / description / expr_type` 五字段
- `demo_code` 是**原始 SV 代码**（含真实信号名 / 字面量），**不是** Jinja2 模板体——这一点用于前端"立即使用"路径直接展示给用户复制
- `name_conflict` 为 `false`（库内无重名模板）

#### §5.7.2 LLM 解析失败 → 422

**触发条件**：`original_intent` 描述模糊到 LLM 无法生成合规 JSON / 命名 / Jinja2 / keywords 任一字段。

```bash
TOKEN=<jwt>
curl -i -X POST http://localhost/api/v1/contributions/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"original_intent":"做点验证的东西","code_type":"assertion"}'
```

**期望**：HTTP 422，响应体：

```json
{
  "detail": {
    "type": "contribution_parse_failed",
    "stage": "<见下方速查表>",
    "reason": "<具体失败描述>"
  }
}
```

**stage 取值速查**（与 `backend/app/services/platform/parameter_extractor.py` 实际 `ContributionParseError(stage=...)` 字符串一一对应）：

| stage | 触发位 | 说明 |
|---|---|---|
| `llm_response` | `generate_from_intent` | LLM 返空响应 |
| `json_locate` / `json_parse` | `_extract_json_block` | LLM 输出未含 JSON 对象 / JSON 解析失败 |
| `template_name` | `_validate_template_name` | LLM 产出的名称不匹配 `^(sva|cov)_[a-z][a-z0-9_]*_v\d+$` |
| `param_defs_shape` / `param_defs_empty` / `param_defs_name` / `param_defs_expr_type` | `_validate_parameter_defs` | LLM 产出的参数定义不是 list、为空、name 非法 SV 标识符、`expr_type` 不在白名单等 |
| `jinja_empty` | `_validate_jinja_rendering` | LLM 产出的 `jinja_body` 为空字符串 |
| `jinja_syntax` | `_validate_jinja_rendering` | Jinja2 模板体语法错误（`TemplateSyntaxError`） |
| `jinja_sandbox` | `_validate_jinja_rendering` | 模板体含 SSTI / `__class__` 等不安全访问被 `SandboxedEnvironment` 拦截（`SecurityError`） |
| `jinja_render` | `_validate_jinja_rendering` | 用占位值跑 `StrictUndefined` 渲染失败（引用未声明变量 / 其他运行时错误） |
| `keywords_shape` | `_validate_keywords` | keywords 不是 list（None 容忍为空 list；非 str 元素与空串静默过滤；当前**无**长度/数量上限） |
| `description` / `demo_code` | `generate_from_intent` | LLM 未返回 `description` 或 `demo_code` 字段或为空 |
| `input` | `generate_from_intent` | `original_intent` 入参为空 |

**前端预期行为**：Step 0 表单底部展示红色错误条「LLM 生成失败：<stage> - <reason>」，用户改 `original_intent` 后再点「生成预览」重试。

#### §5.7.3 `name_conflict` 非阻塞提示

**前置**：库中已存在 `sva_handshake_stable_v1` 模板。

**触发**：意图描述与已有模板高度相似，LLM 倾向生成同名 `template_name`。

```bash
TOKEN=<jwt>
curl -s -X POST http://localhost/api/v1/contributions/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"original_intent":"valid 拉高到 ready 到来之间 data 必须稳定","code_type":"assertion"}' | jq '.template_name, .name_conflict'
```

**期望**：HTTP 200，响应体含：

```json
{
  "template_name": "sva_handshake_stable_v1",
  "name_conflict": true,
  ...
}
```

**前端预期行为**：Step 1 顶部展示黄色 Warning Alert「此名称与现有模板重名，请修改 `template_name` 后再提交」；submit 端点若用户不改名直接提交，会返 422 `contribution_name_duplicate` 阻塞（与 §5.4.1 既有行为一致）。

#### §5.7.4 `original_intent` 为空 → 422

**前置**：Pydantic schema `ContributionPreviewRequest.original_intent` 声明 `min_length=1`。

```bash
TOKEN=<jwt>
curl -i -X POST http://localhost/api/v1/contributions/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"original_intent":"","code_type":"assertion"}'
```

**期望**：HTTP 422，Pydantic 标准 validation error（`detail[0].loc=["body","original_intent"]` + `msg` 含 `min_length`）。

#### §5.7.5 「立即使用」端到端验证

**前置**：跑通 §5.7.1 拿到一个合法 preview 响应。

```bash
TOKEN=<jwt>
PREVIEW=$(curl -s -X POST http://localhost/api/v1/contributions/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"original_intent":"<新场景>","code_type":"assertion"}')

# 模拟前端 Step 1「立即使用」：携带 preview 5 字段调 submit
curl -s -X POST http://localhost/api/v1/contributions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "$(echo $PREVIEW | jq -c '{original_intent:"<新场景>",code_type:"assertion",template_name,description,demo_code}')" | jq .
```

**期望**：HTTP 201，响应体含：

```json
{
  "id": "<uuid>",
  "status": "pending_review",
  "use_immediately_available": true,
  ...
}
```

**前端预期行为**：Step 1 内不关闭 Modal，渲染 `<pre>` monospace 代码块（内容 = Step 1 表单里用户最终确认的 `demo_code`）+ 「复制代码」按钮 + 提示文案"代码已就绪，可直接复制使用。模板已提交审核，审核通过后将加入模板库。"——**不**跳转 `/generate`，因为 `pending_review` 贡献不在 Qdrant 中，跳过去只会触发第五道闸 `no_matching_template` 进入死循环。

---

## 6. 批量生成

### §6.1 完整流程（Excel → ZIP）

1. 「批量生成」页下载 Excel 模板（按 code_type 区分 sheet）
2. 填 5 行测试数据（混合 assertion + coverage）
3. 上传 Excel
4. 看解析预览：行数、列识别
5. 点「开始批量生成」
6. 期望：实时进度条（已完成/总数）；每行调 `run_pipeline`，遇 5 道闸结构化记录该行状态
7. 完成后展示结果列表：每行 `status` ∈ `success` / `under_specified` / `off_topic` / `code_type_mismatch` / `failed`
8. 下载结果 ZIP

### §6.2 每行结果状态对应

| 行状态 | 含义 | 用户行动 |
|---|---|---|
| `success` | 5 道闸全过 + 模板渲染成功 | 直接用代码 |
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

### §7.4 admin 端模板成熟度切换（FEAT-13 / v3.5）

> 「升级到 production」/「降级到 experimental」按钮仅 `super_admin` 可见可点。lib_admin 即使在 DOM 中手工渲染、绕过前端权限校验直接点击，后端 PATCH 也会返 HTTP 403。本节按"前端 UI 可视手测 + API 直调防御性测试"两个层级覆盖。

**前置**：

- 已跑 `alembic upgrade head` 升到 migration 009，`maturity_level` 列存在
- 已跑 `docker compose exec backend python lib_manager.py rebuild` 让 Qdrant payload 含 `maturity_level` 字段（否则 §7.5 会失败）
- 准备三类账号：`super_user`（role=super_admin）、`lib_admin_user`（role=lib_admin）、`normal_user`（role=user）

#### §7.4.1 super_admin 升级 / 降级（happy path）

1. 用 `super_user` 登录 → 进入「模板库管理」（`/admin/templates`）
2. 表格期望可见**新列 `maturity_level`**，每行带颜色 Tag：
   - `production` → 绿色
   - `experimental` → 橙色
   - `draft` → 蓝色
3. 找到任一 `maturity_level='experimental'` 行（如 backfill 后的 `L6_E2E_1778770719`，若不存在可任选一行先降级再升级）→ 操作区可见**两个新按钮**「升级到 production」「降级到 experimental」
4. 点「升级到 production」→ Popconfirm 确认 → 期望：
   - 表格内该行 `maturity_level` Tag 实时变 `production`（绿色）
   - 后端日志（`docker compose logs backend --tail 30`）应出现 `PATCH /api/v1/admin/templates/<id>` `200 OK`
   - DB 验证：`docker compose exec postgres psql -U postgres -d dvacode -c "SELECT id, maturity, maturity_level FROM templates WHERE id='<id>'"` → 期望 `maturity_level=production`，`maturity` 列**保持原值不变**（两列独立）
5. 点同行「降级到 experimental」→ Popconfirm 确认 → 期望 Tag 实时变橙色，DB 中 `maturity_level=experimental`

#### §7.4.2 lib_admin 看不到升降级按钮（前端守门）

1. 用 `lib_admin_user` 登录 → 进入「模板库管理」
2. 期望：
   - `maturity_level` 列仍可见（lib_admin 可查看）
   - 操作区**不渲染**「升级到 production」「降级到 experimental」两个按钮（仅 super_admin 可见）
   - 现有「编辑」「停用」等既有按钮不受影响

#### §7.4.3 lib_admin API 直调 PATCH maturity_level → 403（后端兜底）

```bash
# 取 lib_admin token
LIB_ADMIN_TOKEN=$(curl -s -X POST http://localhost/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"lib_admin_user","password":"<password>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 尝试 PATCH 一个真实模板的 maturity_level
curl -s -i -X PATCH http://localhost/api/v1/admin/templates/sva_handshake_stable_v1 \
  -H "Authorization: Bearer $LIB_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"maturity_level": "experimental"}'
```

期望响应：

- HTTP `403 Forbidden`
- 响应体 `detail` 字段为字符串 `"仅 super_admin 可修改 maturity_level"`
- DB 中该模板 `maturity_level` 列**未改动**（验证：`SELECT maturity_level FROM templates WHERE id='sva_handshake_stable_v1'` 仍为 `production`）

#### §7.4.4 super_admin 传入非法 enum 值 → 422

```bash
SUPER_TOKEN=$(curl -s -X POST http://localhost/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"super_user","password":"<password>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 传一个不在 enum 范围的值
curl -s -i -X PATCH http://localhost/api/v1/admin/templates/sva_handshake_stable_v1 \
  -H "Authorization: Bearer $SUPER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"maturity_level": "released"}'
```

期望响应：

- HTTP `422 Unprocessable Entity`
- `detail` 是 Pydantic 标准错误数组，含 `"loc": ["body", "maturity_level"]` 与提示非法 enum 值
- DB 中该模板 `maturity_level` 列**未改动**

### §7.5 experimental 模板不参与 RAG 召回手测（FEAT-13 / v3.5）

> 验证 RAG stage1 Qdrant Filter + engine.py DB 二次过滤双层防御生效，experimental / draft 模板不会出现在 `rag_candidates`。

**前置**：

- 至少有一条 `maturity_level='experimental'` 的模板（backfill 后 `L6_E2E_1778770719` 即是；若数据集不含该 ID，用 §7.4.1 把任一已知模板临时降级为 experimental 后再回升）
- 选一条意图能命中该 experimental 模板的查询（可参考 spec / `L6_E2E_*` 的原始用例）

#### §7.5.1 通过 /preview 端点验证 rag_candidates 不含 experimental 模板

```bash
TOKEN=<jwt of normal_user>
curl -s -X POST http://localhost/api/v1/generate/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "text": "<选定的能命中 experimental 模板的意图>",
    "code_type": "assertion",
    "clk": "clk",
    "rst": "rst_n",
    "rst_polarity": "低有效",
    "signals": []
  }' | python3 -m json.tool > /tmp/preview.json
```

期望响应中：

- `rag_candidates` 数组的每一项 `template_id` 都**应是 `maturity_level='production'`** 的模板 ID（运行 `SELECT id, maturity_level FROM templates WHERE id = ANY(ARRAY[<rag_top3 ids>]::varchar[])` 逐一比对）
- 即被定向降级的 experimental 模板 ID **不**出现在 `rag_candidates` 中
- 即使该 experimental 模板在语义上更贴近用户意图，召回流水线也会走 RAG fallback / 关键词补充召回 / no_matching_template 闸而不是命中它

#### §7.5.2 实时降级一个 production 模板 → 立即从召回中消失

1. 用 super_admin 在 Admin UI 把当前能命中某意图的 production 模板降级为 experimental
2. **不**手动 invalidate 缓存（验证 Filter 即时生效，不依赖缓存清理）
3. 用一个**新**意图（防 intent_cache 命中）触发 `/preview`，意图措辞替换 1-2 个词避免 hash 重叠
4. 期望：原 production 模板**不出现**在 `rag_candidates`；若库内有近邻 production 模板，命中它（fallback）；若无 → no_matching_template 闸 → 422
5. 再用 super_admin 把模板升回 production，跑同一新意图 → 期望该模板**重新出现**在 `rag_candidates`

#### §7.5.3 后端日志辅助（Qdrant 查询 Filter 结构）

排查 RAG 召回为空时，可在 backend 日志确认 Qdrant 查询确实带了 maturity Filter：

```bash
docker compose logs backend --tail 100 | grep -E 'stage1_hybrid|maturity_level|query_filter'
```

期望日志含类似 `Filter(must=[FieldCondition(key='code_type', ...), FieldCondition(key='maturity_level', match=MatchValue(value='production'))])` 结构。

### §7.6 migration 009 backfill 验证手测（FEAT-13 / v3.5）

> 验证 `alembic upgrade head` 之后 `templates.maturity_level` 列被正确 backfill：官方种子模板 → `production`，其余（含 `is_active=false`、含历史 `L6_E2E_*`）→ `experimental`。

**前置**：

- 已在测试栈跑过 migration 001-008（无 maturity_level 列状态）
- 数据集含至少 1 条 `sva_*_v*` 行 + 1 条 `cov_*_v*` 行 + 1 条 `L6_E2E_*` 行
- 若是全新环境，先 `docker compose exec backend python lib_manager.py import` 让模板入库再升

**步骤**：

1. 跑迁移：
   ```bash
   docker compose exec backend alembic upgrade head
   ```
   期望日志末尾出现 `[WARN]` 字样的提示 "必须紧接 `lib_manager rebuild` 同步 Qdrant payload"（migration 009 `upgrade()` 末尾打印）

2. 三类模板的 maturity_level 分别确认（SVA 官方种子）：
   ```bash
   docker compose exec postgres psql -U postgres -d dvacode -c \
     "SELECT id, maturity_level FROM templates WHERE id ~ '^sva_.+_v[0-9]+$' ORDER BY id LIMIT 10"
   ```
   期望：所有行 `maturity_level=production`

3. 覆盖率官方种子：
   ```bash
   docker compose exec postgres psql -U postgres -d dvacode -c \
     "SELECT id, maturity_level FROM templates WHERE id ~ '^cov_.+_v[0-9]+$' ORDER BY id LIMIT 10"
   ```
   期望：所有行 `maturity_level=production`

4. 历史 / 测试模板：
   ```bash
   docker compose exec postgres psql -U postgres -d dvacode -c \
     "SELECT id, maturity_level, is_active FROM templates WHERE id !~ '^(sva|cov)_.+_v[0-9]+$' ORDER BY id LIMIT 20"
   ```
   期望：所有行 `maturity_level=experimental`（包括 `is_active=false` 的行；`L6_E2E_1778770719` 必须 `experimental`）

5. enum 完整性验证：
   ```bash
   docker compose exec postgres psql -U postgres -d dvacode -c \
     "SELECT enum_range(NULL::template_maturity_enum)"
   ```
   期望返回 `{production,experimental,draft}`（顺序不重要，三档必须齐）

6. **回滚验证（可选）**：
   ```bash
   docker compose exec backend alembic downgrade -1
   docker compose exec postgres psql -U postgres -d dvacode -c \
     "\d templates"
   ```
   期望 `maturity_level` 列消失、`template_maturity_enum` 类型也被 DROP；再 `alembic upgrade head` 应可重新 backfill 至相同结果（幂等）

7. **Qdrant payload 同步**（与 §7.5 联动）：
   ```bash
   docker compose exec backend python lib_manager.py rebuild
   ```
   完成后跑 §7.5.1 验证 RAG 召回正常（若漏跑 rebuild，**所有** `/preview` 请求会因 Qdrant Filter 找不到 `maturity_level=production` 的 points 而返 503 `empty_retrieval`——这是上线最容易踩的坑，必须明确告诉运维"先 upgrade 再 rebuild"）

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

## 11. Step1 模板选择质量回归（混淆对语料 + reranker 阈值标定）

LLM step1 在两个语义接近的模板间选错（如 `handshake_stable` ↔ `handshake_timeout`）是隐蔽失效——不触发任何 gate，用户拿到"看起来合理但语义错位的代码"。`backend/tests/data/template_confusion_corpus.yaml` 是这条防线的回归语料；与 A8 二次验证（§2.7）和 A9 reranker score gate（§2.8）三者联动构成"近邻混淆对路由契约"。

### §11.1 confusion corpus 字段与添加流程

字段约定（与 `template_selection_corpus.yaml` 类似，新增 `confusion_template`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✓ | 蛇形命名，唯一 |
| `input` | ✓ | 用户原始意图文本 |
| `code_type` | ✓ | `"assertion"` \| `"coverage"` |
| `signals` | ✗ | 信号列表 `[{name, width, role}]`，用于避免触发 under_specified 闸 |
| `correct_template` | ✓ | 应命中的 `template_id` |
| `confusion_template` | ✓ | 最容易混淆的竞争 `template_id`（mock 测注入为 RAG top-1） |
| `added` | ✓ | `"YYYY-MM-DD"` |
| `source` | ✓ | `"initial seed"` / `"user report 2026-XX-XX"` / `"PR fix-X"` |
| `reason` | ✓ | 6 个月后能看懂"这对为啥容易混" |
| `flaky` | ✗ | `true` 时 real-llm 套件 warn 但不 fail |

**添加流程**：
1. 收到用户报错或 real-llm 套件 fail 的混淆对
2. 加一条 case 到 yaml，**先跑 mock 测预期 fail**（红灯证明问题真实存在）：
   ```bash
   docker compose exec backend pytest tests/test_template_confusion_corpus_mocked.py -v
   ```
3. 修：补对应模板 YAML 的 `differentiators` / `non_use_cases`（让 LLM step1 看到时能区分）、或调 `_render_step1_candidate` 截断阈值、或调 A8 `verify_step1_selection` prompt
4. `lib_manager.py import --force`（导入更新过的模板）→ 重跑 mock 测变绿
5. 真 LLM 套件复测（手动跑，看 prompt 改动是否在真模型上仍有效）：
   ```bash
   docker compose exec backend pytest tests/test_template_confusion_corpus_real_llm.py --real-llm -v
   ```
6. PR → CI 永守

完整字段约定与触发点 A/B/C 详见 `backend/tests/data/template_confusion_corpus.yaml` 文件头注释（与 `CONTRIBUTING.md §12` 同源，避免双份维护）。

### §11.2 跑套件速查

**mock 套件**（CI 默认必跑，纯本地，~3s）：
```bash
docker compose exec backend pytest tests/test_template_confusion_corpus_mocked.py -v
```
内部逻辑：每条 case 把 `confusion_template` mock 成 RAG top-1，LLM step1 选 `correct`，断言 pipeline 最终落地 `correct_template`（不被 rag_fallback 拖走）；临时关 `under_specified` 闸隔离测试目标。

**real-llm 套件**（手动，需 default LLM + Qdrant + bge-m3 在线，~分钟级）：
```bash
docker compose exec backend pytest tests/test_template_confusion_corpus_real_llm.py --real-llm -v
```
每条 case 调真 pipeline，断言 `template_id == correct`；`under_specified` 算路由对了（参数 corpus 未给全）、`NoMatchingTemplate` 算 step1 误拒、其他异常或选错均 fail（`flaky: true` 的 case 容差）。

### §11.3 解读结果

| 现象 | 解读 | 下一步 |
|---|---|---|
| mock 测全绿 | pipeline 路由逻辑健康（A4 渲染 + A8 verify + A10 描述字段联动正常） | — |
| mock 测某条 fail | 该混淆对在 mock 路径下 pipeline 仍选错，多半是 `differentiators` 信息不够 | 补 template YAML 的 `differentiators` / `non_use_cases`，重导库，重跑 |
| real-llm 测某条 fail | 真模型在新 RAG 排序下仍选错，prompt 或描述字段在真分布下不够 | 调 A8 verify prompt / 扩 description 三要素，重导库，重跑 real-llm |
| real-llm 测 flaky 频繁告警 | 模型温度抖动 / 边界 case | 加 `flaky: true` 接受，或加更明确的样本提高 prompt 强度 |
| A9 阈值标定脚本两段分布重叠 | `correct_p10 < confusion_p50`，无法画分界线 | **不要直接放宽阈值**——先扩 confusion corpus / 优化 differentiators / 重训 reranker，再标定 |

### §11.4 与 A8 / A9 开关的联动测试矩阵

| `STEP1_VERIFY_ENABLED` | `STEP1_RERANKER_GATE_ENABLED` | 适用场景 |
|---|---|---|
| `false`（默认） | `false`（默认） | 当前生产配置；A4 + A10 已起作用，A8/A9 暂未启用 |
| `true` | `false` | 实验阶段：用 confusion corpus real-llm 套件评估 A8 verify 的 false-negative 率 |
| `false` | `true` | 阈值已标定但 verify 尚未上线：纯量化拦截 |
| `true` | `true` | 双重保险，两层均经过对应验证后开启 |

任意配置变化都应：(1) 重启 backend；(2) 跑 §11.2 mock 套件确保 pipeline 仍正确；(3) `docker compose exec backend python -c "from app.core.config import get_settings; s=get_settings(); print(s.step1_verify_enabled, s.step1_reranker_gate_enabled, s.reranker_min_score_threshold)"` 确认 settings 落对。

---

## 附录 B：5 道闸错误响应结构对照

所有 5 道闸响应共享 `detail.redirect_to` 字段；前端 `handleApiError` 优先读这一字段决定是否跳路由。

| 闸 | HTTP | `detail.type` | `detail.redirect_to` | 前端行为 |
|---|---|---|---|---|
| off-topic | 422 | `off_topic` | `null` | 弹"检测到非验证请求"Modal，停留生成页 |
| code_type_mismatch | 422 | `code_type_mismatch` | `null` | 弹"代码类型选错了"Modal，含 `suggested_code_type` |
| under_specified | 422 | `under_specified` | `/intent-builder?prefill=...&template_id=...&code_type=...&missing=...` | 自动 `router.push` 进 IntentBuilder |
| no_matching_template | 422 | `no_matching_template` | `/contribute/new?description=...&code_type=...` | toast + 自动 navigate，跳过 IntentBuilder |
| empty_retrieval | 503 | `empty_retrieval` | `null` | 弹"系统暂不可用"Modal（基础设施异常） |
| contribution_parse_failed | 422 | `contribution_parse_failed` | — | 提交贡献 Modal 内 Alert 显示 `stage` + `reason` |

每个 detail 还携带专属字段（如 off_topic 的 `top_dense_score` / `threshold`，code_type_mismatch 的 `selected_score` / `suggested_score`，under_specified 的 `missing_params` 列表）。完整结构见 `backend/app/api/v1/generate.py` 各 `_*_detail()` 函数。

### 兜底 fallback 错误（非闸异常）

当后端抛非结构化异常（如 LLM vendor 错、Pydantic 校验失败、httpx 超时）时，5 道闸都不命中，FastAPI 端点统一返回 `HTTP 500 detail="<ExceptionName>: <msg>"`（preview / render / 旧 `/generate` 都做了 `logger.exception` 记 traceback），前端 `handleApiError` 走 fallback 分支：

```
message.error(`${fallbackMsg}（HTTP <status>: <detail 200 字符摘要>）`)
```

即任意 generic 失败都会显示 HTTP 状态码 + detail 摘要，方便回归测试时直接看 toast 定位是 500 / 503 / 422 异常路径。后端则可用 §0.5 的 `ERROR` 过滤抓 traceback。

---

## 12. L3 用户反馈机制验证

### §12.1 提交三档评分

**前置**：登录普通用户，跑一次成功生成（任意 §1.x 路径都行），停留在 result 阶段（看到代码卡片）。

**步骤**：
1. 代码卡片下方应出现一行 3 个按钮：👍 好评 / 😐 一般 / 👎 差评
2. **点 👍 好评**：按钮立即变 loading → 转灰 → 右侧出现「已提交反馈」文字。预期：无 Modal，单击即提交，rating=1
3. 后端日志（§0.5）应出现 `POST /api/v1/feedback/<record_id> HTTP/1.1" 204`
4. SQL 验证（`docker compose exec postgres psql -U postgres -d ic_codegen -c`）：
   ```sql
   SELECT id, feedback_rating, feedback_reason_tags, feedback_comment, feedback_at, generation_mode
     FROM generation_records ORDER BY created_at DESC LIMIT 1;
   ```
   期望：`feedback_rating=1`, `feedback_reason_tags=NULL`, `feedback_comment=NULL`, `feedback_at` 是当前 UTC 时间戳，`generation_mode='rag'`

**重复提交防护**：
5. 再点其他档（😐 一般 / 👎 差评）应**无反应**——按钮已 disabled。预期：DB 该行 `feedback_rating` 仍为 1，不被覆盖
6. 触发一次新生成（编辑参数后 Render，或重新 Preview），按钮组应**重新激活**（`feedbackSubmitted` 按 `generation_record_id` 独立 lock，新 record 归零）

### §12.2 差评 Modal + reason_tags 必填

**步骤**：
1. 跑一次新生成进入 result 阶段
2. 点 **👎 差评** → 弹出「差评反馈」Modal，含：
   - 7 个 Checkbox 选项（模板选错 / 幻觉信号名 / 语法错误 / 语义错误 / 风格不佳 / 缺少 disable iff / 其他）
   - 一个 TextArea comment 输入框
   - 「取消」「确定」按钮
3. **不选任何 reason_tag 直接点「确定」**：前端 toast `请至少选择一个差评原因`，**不发请求**（后端日志无 POST），Modal 不关闭。这是关键拦截
4. 勾选 `模板选错` + `语义错误`，填 `comment = "这条用了 handshake 模板但我要的是 timing 约束"`，点「确定」
5. 期望：按钮组转灰、Modal 关闭、`已提交反馈` 出现
6. SQL 验证：
   ```sql
   SELECT feedback_rating, feedback_reason_tags, feedback_comment
     FROM generation_records ORDER BY created_at DESC LIMIT 1;
   ```
   期望：`feedback_rating=3`, `feedback_reason_tags=["wrong_template", "semantic_error"]`（JSONB 数组），`feedback_comment='这条用了 handshake 模板但我要的是 timing 约束'`

### §12.3 后端校验闸（前端绕过场景）

通过 cURL 直接测后端 schema 校验（前端的拦截只是 UX，后端必须有强制约束）：

```bash
# 取 JWT（§0.6）
TOKEN=$(curl -s ... | jq -r .access_token)

# 取一条自己的 record id
RECORD_ID=$(docker compose exec -T postgres psql -U postgres -d ic_codegen -t -c \
  "SELECT id FROM generation_records WHERE user_id='<your_uuid>' ORDER BY created_at DESC LIMIT 1" | tr -d ' ')

# 1) rating=3 但 reason_tags 为空 → 422 reason_tags_required
curl -s -X POST http://localhost/api/v1/feedback/$RECORD_ID \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"rating": 3}' | jq
# 期望：HTTP 422，detail[0].type="reason_tags_required"，msg 含 "reason_tags 字段必填"

# 2) rating=5（非 {1,2,3}）→ 422 校验错误
curl -s -X POST http://localhost/api/v1/feedback/$RECORD_ID \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"rating": 5}' | jq
# 期望：HTTP 422，detail[0].type="literal_error"（Pydantic Literal[1,2,3] 标准错误）

# 3) 别人的 record → 403
SOMEONE_ELSE_ID=$(docker compose exec -T postgres psql -U postgres -d ic_codegen -t -c \
  "SELECT id FROM generation_records WHERE user_id!='<your_uuid>' LIMIT 1" | tr -d ' ')
curl -s -X POST http://localhost/api/v1/feedback/$SOMEONE_ELSE_ID \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"rating": 1}' | jq
# 期望：HTTP 403，detail="无权对他人的生成记录评分"
# 注：用 lib_admin / super_admin 账号同请求应该 204
```

### §12.4 闸触发路径的 record 持久化（L4 数据基础设施）

L4 `/no-match-rate` 端点依赖"5 道闸触发时也有 GenerationRecord 行"。手动验证：

1. 触发 `no_matching_template`（§2.5 总线仲裁互斥约束意图） → 收到 422 + 直跳贡献页
2. SQL：
   ```sql
   SELECT id, user_id, template_id, output_code, gate_error_type, generation_mode
     FROM generation_records
     WHERE gate_error_type IS NOT NULL ORDER BY created_at DESC LIMIT 3;
   ```
   期望：最新一行 `gate_error_type='no_matching_template'`, `template_id IS NULL`, `output_code IS NULL`, `generation_mode='rag'`, `user_id` 是当前登录用户
3. 同理触发 off-topic（§2.1 诗歌意图）→ 应写一行 `gate_error_type='off_topic'`
4. 触发 under_specified（§2.3 缺信号名意图）→ 应写一行 `gate_error_type='under_specified'`

**若 gate_error_type 行**不**出现**：说明 `api/v1/generate.py` `_record_gate_event` 调用链漏掉了某个闸，分析仪表盘 KPI 会失真。日志应有 `failed to persist gate event for analytics; ignoring` 表示写失败被吞——这种应改 ERROR 等级排查。

---

## 13. 管理员分析仪表盘使用说明

**前置**：登录 `lib_admin` 或 `super_admin` 账号，访问 `/admin/analytics`（顶部导航「数据分析」入口）。

### §13.1 4 个端点 curl 示例

```bash
TOKEN=$(curl -s -X POST http://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<pw>"}' | jq -r .access_token)

# 1) feedback-summary
curl -s "http://localhost/api/v1/admin/analytics/feedback-summary?days=7" \
  -H "Authorization: Bearer $TOKEN" | jq
# 期望响应字段：
# {
#   "days": 7,
#   "total_generations": <int>,
#   "total_feedbacks": <int>,
#   "feedback_rate": <0..1, 4 位小数>,
#   "bad_rate": <0..1, 4 位小数>,
#   "no_match_rate": <0..1, 4 位小数>
# }
# 空数据时各 rate=0.0，不报 500

# 2) template-issues
curl -s "http://localhost/api/v1/admin/analytics/template-issues?days=7&limit=10" \
  -H "Authorization: Bearer $TOKEN" | jq
# 期望：数组每行 {template_id, total_count, bad_count, bad_rate}，按 bad_rate DESC 排序

# 3) intent-confusion
curl -s "http://localhost/api/v1/admin/analytics/intent-confusion?days=7&limit=10" \
  -H "Authorization: Bearer $TOKEN" | jq
# 期望：数组每行 {intent (≤200 字符), expected_template, actual_template, code_type, count}
# 数据源仅 feedback_rating=3 且 template_id != rag_top3[0].template_id

# 4) no-match-rate
curl -s "http://localhost/api/v1/admin/analytics/no-match-rate?days=7" \
  -H "Authorization: Bearer $TOKEN" | jq
# 期望：数组每行 {date (ISO date), total, no_match_count, no_match_rate}
# 不补零行——只返实际有数据的天数

# 权限校验：普通用户访问 → 403
curl -s "http://localhost/api/v1/admin/analytics/feedback-summary" \
  -H "Authorization: Bearer $REGULAR_USER_TOKEN" -w "%{http_code}\n" -o /dev/null
# 期望：403
```

### §13.2 仪表盘 KPI 卡片含义

| 卡片 | 数据源 | 解读 |
|---|---|---|
| 总生成数 | `total_generations` | 时间窗内所有 `generation_records` 行数（含 gate 触发记录） |
| 反馈率 | `feedback_rate = total_feedbacks / total_generations` | 多少比例的生成被用户评了分。低于 5% 说明 UI 引导不够，用户根本不点反馈按钮 |
| 差评率 | `bad_rate = bad_feedbacks / total_feedbacks` | **分母是反馈数不是生成数**——表达"在愿意反馈的用户里，差评占比"。> 30% 说明库或 LLM 有系统性问题 |
| NoMatch 率 | `no_match_rate = no_match_count / total_generations` | 触发 `no_matching_template` 闸的比例。> 10% 说明库覆盖度不够，需要主动扩 templates |

### §13.3 仪表盘视觉验收

打开 `/admin/analytics` 页面后逐项核查：

1. 顶部 KPI 卡片行（4 个 `Statistic`）数字与上面 curl 响应一致
2. 7 天趋势折线图（`@ant-design/charts` Line）：X 轴日期（ISO date 倒序或顺序）、Y 轴 `no_match_rate`；hover 时 tooltip 显示当日 `total` / `no_match_count`
3. 差评模板 top-10 表：
   - 列：template_id / total_count / bad_count / bad_rate（百分比展示）
   - 默认按 bad_rate 降序，可点表头排序
4. intent confusion 表：
   - 列：intent（截断显示） / expected_template / actual_template / code_type / count / 操作（含「复制为 corpus 条目」按钮）
   - 点「复制为 corpus 条目」→ toast `已复制为 corpus 条目，可粘贴到 template_selection_corpus.yaml`
   - 在终端 `pbpaste`（mac）或粘到任意编辑器，应得到完整 YAML 块：
     ```yaml
       - id: confusion_<timestamp>_<expected>_vs_<actual>
         intent: "<原始意图 ≤200 字符>"
         code_type: <actual_template 的 code_type>
         expected_template: <rag_top3[0].template_id>
         note: "From production confusion log: intent classified as ... but expected ... (count=N)"
     ```
   - 若 `code_type` 为空（actual_template 已被删）→ 出现 `code_type: ""  # template not found — please fill manually`
5. 空数据兜底：DB 无任何反馈数据时，4 个 KPI 卡片显示 0.00% 而非 NaN/NaN，表格显示「暂无数据」占位

### §13.4 intent_confusion → corpus 闭环（手动 append）

发现 confusion 表里的混淆样本想加入回归测试时，标准流程：

1. 仪表盘点「复制为 corpus 条目」
2. 编辑 `backend/tests/data/template_selection_corpus.yaml`，把剪贴板 YAML 块 append 到末尾（按 `code_type` 分组就近放）
3. 跑 `docker compose exec backend pytest tests/test_template_selection_corpus_mocked.py -v` 确认新条目通过 mock 套件
4. PR 提交时附上「源于 production confusion 第 N 条」的说明，便于后续追溯

**不**做自动写回：corpus 是版本控制的契约，需要 human-in-the-loop 审 audit；自动化只在贡献入库时由 `corpus_service.py` 写 `template_corpus_cases` DB 表（参见 CONTRIBUTING.md §12 近邻模板混淆对回归语料维护流程）。

### §13.5 Stage 2/3 启动条件参考

参考产品路线图的"观察期决策门"判定何时进入 L4 增强阶段：

- **`bad_rate > 30%` 且持续 2 周** → 触发"模板系统性优化"工单（追查 top-10 表的 bad rate 集中模板）
- **`no_match_rate > 15%` 且持续 2 周** → 触发"模板库扩容"工单（看 intent-confusion 表的高频未覆盖意图）
- **`feedback_rate < 5%` 且持续 4 周** → 触发"反馈 UX 重设计"工单（用户根本不点反馈按钮，数据信号失效）

阈值未硬编码到代码里——观察期决策由库管理员根据仪表盘手动判定，本表仅作参考起步值。

---

## 14. 管理员对比报告审阅（FEAT-12 / v3.4）

> §4.9 用户提交对比报告后流入 `improvement_reports` 表（status='pending'）。本节验证管理员侧列表过滤、详情自动状态流转、admin_note 编辑、标记 resolved 与状态机非法跳转拦截。前置：完成 §4.9.1 至少一次成功提交。
>
> 路由：仅 `lib_admin` / `super_admin` 可见，侧边栏「管理」→「对比报告」（`/admin/improvement-reports`）。普通用户访问任一 admin 端点返 HTTP 403。

### §14.1 列表页过滤（status / category）

1. 登录 admin（§0.2），点侧边栏「管理」→「对比报告」
2. 期望进入 `/admin/improvement-reports`：
   - 顶部 Filter Bar：`status` 单选下拉（`全部` / `pending` / `in_review` / `resolved`）+ `categories` 多选下拉（4 项中文 label）
   - Table 列：ID（uuid 缩写） / 状态 Tag（三色：橙=pending / 蓝=in_review / 绿=resolved） / 提交用户名 / RAG 模板名 / 分类 Tag 组 / 提交时间 / 操作"查看"
   - 默认 `created_at DESC`
3. 选 `status=pending`：期望只看到 §4.9.1 创建的那条
4. 选 `categories=[模板选错]`：期望 §4.9.1（categories 为空）行**不**显示——空 categories 不匹配任何 category filter
5. 清 filter → 仍能看到 §4.9.1 行

### §14.2 详情页 mount 自动 PATCH `pending → in_review`

1. 列表里点 §4.9.1 行的"查看" → 跳 `/admin/improvement-reports/<id>`
2. 期望页面 mount 期间立即调 `PATCH /api/v1/admin/improvement-reports/{id} {status: 'in_review'}`，无需 admin 主动点击
3. 后端日志期望：
   ```
   PATCH /api/v1/admin/improvement-reports/<id> HTTP/1.1" 200
   ```
4. 详情页 UI 期望：
   - 顶部状态 Tag 由橙色 `pending` 变蓝色 `in_review`
   - 三列 Card 横向布局：
     - **左列（RAG 记录）**：`original_intent` / `template_id` + `template_name` / `params_used` JSON / `output_code`（Monaco 只读 SystemVerilog 高亮） / `generation_mode='rag'` / `cache_hit`
     - **中列（LLM Direct 记录）**：同字段；`template_id` 为空 / `generation_mode='llm_direct'` / 头部橙色 Tag「非确定性」
     - **右列（用户提交内容）**：`report_categories` 中文 label Tag 组 / `reporter_note`（若空显"用户未填写"）
   - 右列下方："管理员处理"区：`admin_note` TextArea（无字数上限） + 「标记已处理」按钮（始终 enabled）
5. SQL 验证：
   ```bash
   docker compose exec postgres psql -U dvuser -d dv_platform -c \
     "SELECT status, reviewed_by, reviewed_at IS NOT NULL AS reviewed FROM improvement_reports WHERE id='<id>';"
   ```
   期望：`status=in_review`, `reviewed_by=<current admin id>`, `reviewed=t`

### §14.3 admin 写 note 并标记 resolved

1. 在 §14.2 详情页 admin_note TextArea 输入"已确认是模板选错，已加入 FEAT-13 语料回流队列"
2. 点「标记已处理」
3. 期望：
   - 调 `PATCH /api/v1/admin/improvement-reports/{id} {status: 'resolved', admin_note: '<上述文本>'}`
   - HTTP 200 响应
   - 顶部状态 Tag 变绿色 `resolved`
   - 「标记已处理」按钮变 disabled（终止态不允许再 PATCH）
   - 顶部 `message.success('已标记为已处理')`
4. 返回列表页 → §4.9.1 行状态 Tag 应同步刷新为绿色 `resolved`

### §14.4 状态机非法跳转手测（API 直调）

详情页 UI 已守门"标记已处理"按钮只在 `in_review` 时 enabled，但仍需 API 直调验证后端兜底拦截。

```bash
ADMIN_TOKEN=<jwt>
REPORT_ID=<已 resolved 的 §14.3 报告 ID>

# 1) resolved → pending（倒退）
curl -s -X PATCH "http://localhost/api/v1/admin/improvement-reports/$REPORT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"pending"}' -w "\nHTTP %{http_code}\n"
# 期望：HTTP 422，detail.type="illegal_status_transition"，message 含"resolved → pending"

# 2) resolved → in_review（倒退）
curl -s -X PATCH "http://localhost/api/v1/admin/improvement-reports/$REPORT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"in_review"}' -w "\nHTTP %{http_code}\n"
# 期望：HTTP 422 illegal_status_transition

# 3) 新建一份 pending 报告（§4.9.1 重新跑），然后直接 pending → resolved 跳过 in_review
NEW_REPORT_ID=<新 pending 报告 ID>
curl -s -X PATCH "http://localhost/api/v1/admin/improvement-reports/$NEW_REPORT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"resolved","admin_note":"试跳"}' -w "\nHTTP %{http_code}\n"
# 期望：HTTP 422 illegal_status_transition，message 含"pending → resolved"（跳过 in_review）

# 4) in_review → pending（倒退）—— 把 NEW_REPORT_ID 通过 §14.2 流程先 PATCH 到 in_review
curl -s -X PATCH "http://localhost/api/v1/admin/improvement-reports/$NEW_REPORT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"pending"}' -w "\nHTTP %{http_code}\n"
# 期望：HTTP 422 illegal_status_transition

# 5) 对照组：pending → in_review（合法），in_review → resolved（合法）
# 期望：HTTP 200，对应状态正常推进；reviewed_by / reviewed_at 同步刷新
```

### §14.5 普通用户访问 admin 端点返 403

```bash
USER_TOKEN=<非 admin 用户 jwt>
curl -s -w "\nHTTP %{http_code}\n" \
  "http://localhost/api/v1/admin/improvement-reports?status=pending" \
  -H "Authorization: Bearer $USER_TOKEN"
# 期望：HTTP 403

curl -s -w "\nHTTP %{http_code}\n" \
  "http://localhost/api/v1/admin/improvement-reports/$REPORT_ID" \
  -H "Authorization: Bearer $USER_TOKEN"
# 期望：HTTP 403

curl -s -X PATCH -w "\nHTTP %{http_code}\n" \
  "http://localhost/api/v1/admin/improvement-reports/$REPORT_ID" \
  -H "Authorization: Bearer $USER_TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"resolved"}'
# 期望：HTTP 403
```

### §14.6 与 §12 L3 差评 / §13 L4 仪表盘的边界

- **§12 L3 差评 vs §4.9 + §14 对比报告**：同一对 `(RAG record, llm_direct child record)` 可同时存在 L3 差评和对比报告。验证：完成 §4.9.1 提交报告后，对 `llm_direct` 子记录额外打一次 §12.1 三档评分（如 3 分差评） + 填 reason_tags + 提交 — 期望 `generation_records.feedback_rating=3` 与 `improvement_reports.status='pending'` 双写成功，两条数据通道互不影响
- **§13 L4 仪表盘**：FEAT-12 **不修改** 4 个 KPI 端点；本次 PR 不在仪表盘看到 `improvement_reports` 数据（留 FEAT-13）。验证：进入 `/admin/analytics`，确认页面无变化，4 个 KPI 卡片含义与 §13.2 完全一致
