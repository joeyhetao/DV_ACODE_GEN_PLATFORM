# 平台功能测试手册

**适用版本**：v1.0.0
**适用读者**：Alpha 测试者 / QA / 团队交接接收方

> 本手册不写自动化测试代码，全部是人工 QA 步骤。每个用例标注 **输入 → 操作 → 期望结果 → 后端验证**，照着跑能复现 100% 的链路。
>
> 部署相关请看 [deployment-dev-windows.md](deployment-dev-windows.md)。架构理解请看 [../ARCHITECTURE.md](../ARCHITECTURE.md)。

---

## 目录

0. [测试前置准备](#0-测试前置准备)
1. [代码生成 — 高置信度命中（10 模板逐一）](#1-代码生成--高置信度命中)
2. [代码生成 — 易混淆模板对照（4 对）](#2-代码生成--易混淆模板对照测试)
3. [代码生成 — 低置信度兜底场景（6 个）](#3-代码生成--低置信度兜底场景)
4. [缓存层行为验证](#4-缓存层行为验证)
5. [模板贡献机制（3 个完整流程）](#5-模板贡献机制)
6. [意图构建器](#6-意图构建器)
7. [批量生成](#7-批量生成)
8. [模板库浏览](#8-模板库浏览)
9. [用户管理](#9-用户管理)
10. [LLM 配置管理](#10-llm-配置管理)
11. [通知机制](#11-通知机制)
- [附录 A：故障排查 cheatsheet](#附录-a故障排查-cheatsheet)
- [附录 B：已知功能-UI gap 清单](#附录-b已知功能-ui-gap-清单)

---

## 0. 测试前置准备

### 0.1 启动栈

完整步骤见 [deployment-dev-windows.md §3](deployment-dev-windows.md#3-首次启动流程)。简版：

```powershell
docker compose `
  -f docker-compose.yml `
  -f docker-compose.dev.yml `
  -f docker-compose.hotreload.yml `
  up -d
```

测试前确认 9 个容器全 `Up` 且关键 4 项 `(healthy)`：

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### 0.2 测试账号

| 用户 | 密码 | 角色 | 用途 |
|---|---|---|---|
| `admin` | `YbZn@2021`（取自 `.env` `SUPER_ADMIN_PASSWORD`）| `super_admin` | 管理员所有操作 |
| `tester1` | 自定义 | `user`（默认） | 普通用户视角，需在 §9.1 创建 |
| `librarian1` | 自定义 | `lib_admin` | 模板审核员视角，需在 §9.1 创建 + 改角色 |

### 0.3 缓存清空命令（冷启动复测专用）

```powershell
# 清掉所有意图缓存 + 生成缓存
docker exec dv_acode_gen_platform-redis-1 redis-cli FLUSHDB

# 验证清空
docker exec dv_acode_gen_platform-redis-1 redis-cli DBSIZE
# 应返回 (integer) 0
```

> ⚠️ FLUSHDB 也会清掉 Celery 队列。**有批量任务在跑时不要执行**。

### 0.4 推荐 LLM 配置（避免单次 60-150s 等待）

测试期间默认 LLM 强烈建议**非 thinking 模型**：

| 推荐 | Provider | Model ID | 单次耗时 |
|---|---|---|---|
| ⭐ 智谱 GLM-4-Plus | OpenAI Compatible | `glm-4-plus` | ~5-10s |
| Claude via OpenRouter | OpenAI Compatible | `anthropic/claude-sonnet-4-6` | ~5-15s |
| ❌ GLM-4.7 | — | `glm-4.7` | 60-150s（thinking） |

切换方法：Admin → LLM 配置 → 编辑或新增 → 设为默认。**切换默认后建议 §0.3 清缓存**（背景见 §4.3）。

### 0.5 后端日志实时查看

```powershell
# 跟踪 backend 日志，过滤出 pipeline 关键步骤
docker logs -f dv_acode_gen_platform-backend-1 2>&1 | Select-String "Pipeline|GLM|RAG"
```

后续每个用例的"后端验证"步骤都依赖此日志窗口。

---

## 1. 代码生成 — 高置信度命中

10 个模板各 1 个用例。**期望全部 confidence ≥ 0.9**（LLM Step1 选中分数固定为 0.9，见 [openai_compat_client.py:78](../backend/app/services/llm/openai_compat_client.py#L78)）。

### 用例总表

| # | 模板 ID | 输入摘要（功能描述）| code_type |
|---|---|---|---|
| 1.1 | `sva_data_integrity_v1` | 数据寄存器在写使能无效期间保持稳定 | assertion |
| 1.2 | `sva_fsm_state_transition_v1` | FSM 从 IDLE 在条件触发下转到 ACTIVE | assertion |
| 1.3 | `sva_handshake_stable_v1` | AXI 握手 valid 拉高 ready 未响应时数据稳定 | assertion |
| 1.4 | `sva_handshake_timeout_v1` | valid 拉高后 ready 必须 16 周期内响应 | assertion |
| 1.5 | `sva_reset_behavior_v1` | 复位释放后计数器 1 周期内归 0 | assertion |
| 1.6 | `sva_timing_max_delay_v1` | 请求发送后应答 8 周期内返回 | assertion |
| 1.7 | `cov_cross_coverage_v1` | 数据宽度和控制信号的交叉覆盖率 | coverage |
| 1.8 | `cov_protocol_handshake_v1` | AXI valid-ready 四种握手场景覆盖率 | coverage |
| 1.9 | `cov_transition_coverage_v1` | FSM IDLE→FETCH→DECODE→EXECUTE 转换覆盖率 | coverage |
| 1.10 | `cov_value_coverage_v1` | 4 位状态信号 0-15 全部取值覆盖率 | coverage |

### 通用操作步骤（所有 §1.x 都按这个流程）

1. 浏览器访问 `http://localhost/`，用 `admin` 登录
2. 左菜单点 **生成代码** → 进入 generate 页
3. **功能描述** 框：copy 用例输入文本
4. **代码类型** 下拉：选用例对应的 code_type
5. 时钟 / 复位 / 信号列表保持默认（除非用例特别说明）
6. 点 **生成代码** 按钮 → 等 5-15 秒（GLM-4-Plus）或 60-150 秒（GLM-4.7）

### 通用期望结果（所有 §1.x 都该看到）

- 右侧面板出现：
  - **置信度**：≥ 90.0%（绿色）
  - **模板**：等于用例的期望 template_id
  - **缓存命中**：第一次跑显示「否」，相同输入再跑显示「是」
  - **生成代码** 区域：包含用例描述的 SystemVerilog 关键句
  - **RAG 候选模板 (Top 3)**：用例期望模板排第一

### 通用后端验证（每个用例都该在日志看到）

```
[Pipeline] keyword supplement: [...]            # 关键词补充召回，期望候选含本用例模板
[GLM Step1] selected='<期望 template_id>'        # LLM 选中
[GLM Step2] param_mapping={...}                  # 参数 JSON
[Pipeline] LLM selection: template_id='<期望 template_id>' confidence=0.9
[Pipeline] params={...}                          # 最终合并后参数
INFO: ... POST /api/v1/generate ... 200 OK       # 成功响应
```

---

### §1.1 数据完整性断言

- **template_id**：`sva_data_integrity_v1`
- **code_type**：`assertion`
- **输入文本**（**v2 — 强判别版**）：
  ```
  寄存器写保护场景的数据完整性断言：当写使能 wr_en 无效时受保护的数据信号 data_reg 不被意外修改，模块 reg_block
  ```
- **期望生成代码**包含：
  ```systemverilog
  // SVA: 数据完整性 — reg_block
  property p_reg_block_data_integrity;
    @(posedge clk) disable iff (!rst_n)
      !wr_en |-> $stable(data_reg);
  endproperty
  ```

> ⚠️ **此用例曾踩坑**：原版输入"数据寄存器在写使能 wr_en 无效期间保持稳定"实测被 BGE-reranker 排到 `sva_handshake_stable_v1`（confidence 100% 误导，实际 RAG[0] fallback）。原因：两个模板都含"数据"+"稳定"关键词，handshake_stable 描述"数据信号必须保持稳定"与原输入"保持稳定"逐字匹配。修正后的 v2 输入显式包含 data_integrity 独有关键词「数据完整性」「寄存器写保护」「不被意外修改」三处，将判别性大幅提升。**详见 §2.5 易混淆对照与附录 B.4。**

### §1.2 FSM 状态转换断言

- **template_id**：`sva_fsm_state_transition_v1`
- **code_type**：`assertion`
- **输入文本**：
  ```
  FSM 状态机从 IDLE 状态在 start_signal 触发下必须转换到 ACTIVE 状态，状态信号 cur_state，模块 ctrl_fsm
  ```
- **期望生成代码**包含：
  ```systemverilog
  cur_state == IDLE && start_signal |=> (cur_state == ACTIVE)
  ```

### §1.3 握手数据稳定断言

- **template_id**：`sva_handshake_stable_v1`
- **code_type**：`assertion`
- **输入文本**：
  ```
  AXI 握手过程中 awvalid 拉高但 awready 未响应时，awaddr 数据信号必须保持稳定，模块 axi_master
  ```
- **期望生成代码**包含：
  ```systemverilog
  (awvalid && !awready) |-> ##1 $stable(awaddr)
  ```

### §1.4 握手超时检测断言

- **template_id**：`sva_handshake_timeout_v1`
- **code_type**：`assertion`
- **输入文本**：
  ```
  awvalid 拉高后 awready 必须在 16 周期内响应防止握手死锁，模块 axi_slave
  ```
- **期望生成代码**包含：
  ```systemverilog
  $rose(awvalid) |-> ##[1:16] awready
  ```

### §1.5 复位行为断言

- **template_id**：`sva_reset_behavior_v1`
- **code_type**：`assertion`
- **输入文本**：
  ```
  复位 rst_n 释放后，计数器 cnt_reg 应在 1 周期内归 0，模块 counter_block
  ```
- **期望生成代码**包含：
  ```systemverilog
  $rose(rst_n) |-> ##[0:1] (cnt_reg == 0)
  ```

### §1.6 最大延迟时序约束断言

- **template_id**：`sva_timing_max_delay_v1`
- **code_type**：`assertion`
- **输入文本**：
  ```
  请求信号 req_sig 发送后，应答信号 ack_sig 必须在 8 周期内返回，模块 ack_engine
  ```
- **期望生成代码**包含：
  ```systemverilog
  $rose(req_sig) |-> ##[1:8] ack_sig
  ```

### §1.7 交叉覆盖率组

- **template_id**：`cov_cross_coverage_v1`
- **code_type**：`coverage`
- **输入文本**：
  ```
  收集数据宽度信号 data_w 和控制信号 ctrl_sig 的交叉覆盖率，发现信号组合的 corner case
  ```
- **期望生成代码**包含：
  ```systemverilog
  cross cp_data_w, cp_ctrl_sig
  ```

### §1.8 协议握手覆盖率组

- **template_id**：`cov_protocol_handshake_v1`
- **code_type**：`coverage`
- **输入文本**：
  ```
  收集 AXI valid-ready 四种握手场景覆盖率，包括握手成功、valid 等待、ready 预备、空闲，valid 信号 awvalid，ready 信号 awready
  ```
- **期望生成代码**包含：
  ```systemverilog
  cross cp_awvalid, cp_awready
  ```
  以及 `bins handshake_done` / `bins valid_wait` 等握手场景标签。

### §1.9 状态转换覆盖率组（用户已验证基线）

- **template_id**：`cov_transition_coverage_v1`
- **code_type**：`coverage`
- **输入文本**：
  ```
  生成一个FSM状态机的状态转换覆盖率组，时钟clk，复位rst_n，状态信号名为cur_state，位宽3位，状态包括IDLE、FETCH、DECODE、EXECUTE
  ```
- **期望生成代码**包含：
  ```systemverilog
  bins states[] = {IDLE,FETCH,DECODE,EXECUTE};
  bins trans[] = (IDLE,FETCH,DECODE,EXECUTE => IDLE,FETCH,DECODE,EXECUTE);
  ```
- **附加期望 params**：
  ```
  signal=cur_state, group_name=cur_state, signal_width=3,
  state_list="IDLE,FETCH,DECODE,EXECUTE"
  ```

### §1.10 信号值域覆盖率组

- **template_id**：`cov_value_coverage_v1`
- **code_type**：`coverage`
- **输入文本**：
  ```
  4 位状态信号 state_reg 的 0-15 全部取值覆盖率统计
  ```
- **期望生成代码**包含：
  ```systemverilog
  cp_state_reg: coverpoint state_reg {
    bins valid_values[] = {[0:15]};
  }
  ```

---

## 2. 代码生成 — 易混淆模板对照测试

下面 5 对模板因为关键词重叠/语义相近，容易让 RAG 选错。本章每对各设 2 个用例（A 倾向 / B 倾向），每跑 5 次至少 4 次该选对应的（80% 准确率底线）。

> **§2.5 是实测验证发现的真实陷阱**（在 §1.1 测试中暴露），不是凭空设想的混淆对。其他 4 对则基于模板 keywords/description 的潜在重叠分析。

### §2.1 握手 stable vs timeout

| 用例 | 输入文本 | 期望模板 | 区分关键词 |
|---|---|---|---|
| 2.1-A | "valid 期间 data 不能变" | `sva_handshake_stable_v1` | "稳定" / "不能变" |
| 2.1-B | "valid 拉高 ready 必须 10 周期内来" | `sva_handshake_timeout_v1` | "周期内" / "超时" |

如果 2.1-A 选成 timeout 或反之，看后端日志的 `[GLM Step1] candidates:` 列表，确认 LLM 到底选了哪个、为什么。

### §2.2 握手断言 vs 握手覆盖率

| 用例 | 输入文本 | 期望模板 | 区分 |
|---|---|---|---|
| 2.2-A | "断言 awvalid 拉高后 awready 必须在 8 周期内来" | `sva_handshake_timeout_v1`（assertion）| code_type=assertion + "断言" 关键词 |
| 2.2-B | "收集 valid-ready 四种握手场景的覆盖率" | `cov_protocol_handshake_v1`（coverage）| code_type=coverage + "覆盖率" |

**注意**：code_type 是硬过滤（Qdrant 只检索同 code_type 的模板）。选错 code_type 不会跨类别误判。

### §2.3 FSM 转换断言 vs 转换覆盖率

| 用例 | 输入文本 | 期望模板 |
|---|---|---|
| 2.3-A | "断言：状态机从 IDLE 在 enable 触发下必须转到 RUN" | `sva_fsm_state_transition_v1` |
| 2.3-B | "覆盖率：统计状态机 IDLE/RUN/DONE 的所有可能转换" | `cov_transition_coverage_v1` |

### §2.4 cross 覆盖 vs value 覆盖

| 用例 | 输入文本 | 期望模板 | 区分 |
|---|---|---|---|
| 2.4-A | "对 data 信号和 mode 信号做交叉覆盖" | `cov_cross_coverage_v1` | "交叉" / "两个信号" |
| 2.4-B | "对 state 信号 0-7 做值域覆盖" | `cov_value_coverage_v1` | "值域" / "单信号" |

### §2.5 数据完整性 vs 握手数据稳定（实测验证发现）⚠️

两份模板都有「数据」+「稳定/stable」类关键词，且 description 都谈"数据保持稳定"，是当前 RAG 最严重的混淆对。

| 用例 | 输入文本 | 期望模板 | 区分关键词 |
|---|---|---|---|
| 2.5-A | "**寄存器写保护**场景的**数据完整性**断言：当 wr_en 无效时数据 data_reg **不被意外修改**" | `sva_data_integrity_v1` | "数据完整性"（exact keyword）/ "寄存器写保护"（description verbatim）/ "不被意外修改"（description verbatim）|
| 2.5-B | "AXI 握手 awvalid 拉高 awready 未响应时 awaddr 必须保持稳定" | `sva_handshake_stable_v1` | "AXI"（tag）/ "valid"+"ready"（keyword）/ "握手"（keyword）|

**已知陷阱**：仅写"数据 ... 保持稳定"且不带 valid/ready/握手字眼时，BGE-reranker 仍倾向 `sva_handshake_stable_v1`（其 description "数据信号必须保持稳定" 与用户原话 "保持稳定" 字面匹配度更高），confidence 显示 **100%** 但实际是 fallback 路径取 RAG[0] 的分数（见附录 B.4 的 confidence 显示陷阱）。

**判别建议**：data_integrity 场景必须显式写「数据完整性」「写保护」「锁存」「不被修改」中至少一个独有关键词。

### §2.6（占位 — 关于 confidence 显示）

附录 B.4 描述的"confidence 100% 但选错模板"现象在 §2.5-A v1 输入中复现。测试时**不能只看 confidence 颜色，必须核对模板 ID + 后端日志的 `[GLM Step1] selected=...` 行**确认是 LLM 主动选中还是 RAG fallback。

---

## 3. 代码生成 — 低置信度兜底场景

PRD 期望系统对边界输入有合理 degradation，但**当前后端对 confidence 不做硬阻断**（[CONFIDENCE_THRESHOLD=0.85](../backend/app/core/config.py#L35) 仅 preflight 用，generate 主流程不查），所以下面用例**全部仍会出代码**，只是置信度低或参数兜底。

### §3.1 完全无关意图

- **输入**："帮我写一首七言律诗咏春"
- **code_type**：`coverage`
- **预期实际行为**：
  - RAG 仍返回 3 个 coverage 候选（向量距离都很大，但 RAG 不阈值过滤）
  - LLM Step1 可能选了某个或返回空
  - confidence 落在 **0.05–0.50** 之间
  - **仍出代码**（毫无意义但 Jinja2 不崩）
- **理想行为**（PRD 期望）：confidence 低于 0.5 时前端显示"无法理解，请补充信息"
- **gap**：见附录 B

### §3.2 极简意图（"覆盖率"）

- **输入**："覆盖率"
- **code_type**：`coverage`
- **预期实际行为**：
  - 关键词补充召回会命中 4 个 coverage 模板（"覆盖" 是它们的 keyword）
  - LLM Step1 在 4 个里挑一个（取决于 LLM 偏好）
  - confidence 0.9（LLM 选中固定值）
  - 由于参数完全缺失，最终 Jinja2 用 `signal=signal, group_name=cov_group, state_list="IDLE, ACTIVE, DONE"`（默认值）渲染
- **理想**：要求用户补完必填参数才能生成
- **测试目的**：验证 §pipeline.py 末尾的 "参数名占位符" 兜底真的不崩

### §3.3 英文意图

- **输入**：`FSM coverage for state machine with IDLE, RUN, STOP states`
- **code_type**：`coverage`
- **预期实际行为**：
  - BGE-M3 中英混合能力一般，向量召回可能不准
  - 关键词补充：`FSM` `状态机` `transition` 是 `cov_transition_coverage_v1` 的 keyword，**FSM 全大写匹配** → 命中
  - confidence 0.9
  - state_list 应自动提取出 `IDLE, RUN, STOP`（pipeline 正则 `\b[A-Z][A-Z0-9_]+\b` 会捕到）

### §3.4 code_type 与意图不符

- **输入**："统计 valid-ready 四种握手场景的覆盖率"
- **code_type**：**`assertion`**（故意选错）
- **预期实际行为**：
  - Qdrant 只检索 assertion 类模板，coverage 模板被过滤
  - 关键词"握手"→ 命中 `sva_handshake_*` 之一
  - LLM Step1 在 assertion 候选里硬选
  - 用户拿到的是断言代码，不是覆盖率代码
- **测试目的**：暴露 code_type 的硬过滤行为，提醒用户**先选对类型再写描述**

### §3.5 必填参数完全缺失

- **输入**："生成一个 FSM 转换覆盖率"
- **code_type**：`coverage`
- **预期实际行为**：
  - 命中 `cov_transition_coverage_v1`，confidence 0.9
  - LLM Step2 也填不出参数（描述里没信号名 / 状态列表）
  - 正则 `_extract_params_from_intent` 也提不到（无 `信号名为...`、无大写状态序列）
  - `_map_params` 末尾兜底：`required` 参数用参数名占位 → `signal=signal`, `state_list=state_list`
  - 生成代码包含字面量 `signal` `state_list`，**SystemVerilog 不可编译**但能渲染出来
- **预期日志**：
  ```
  [Pipeline] params={'group_name': 'cov_group', 'signal': 'signal',
                     'state_list': 'IDLE, ACTIVE, DONE', 'bins_expr': '{[0:7]}', ...}
  ```
- **理想行为**：required 参数缺失时返回 422 + 提示"请补充：状态信号名 / 状态列表"

### §3.6 RAG 召回 0 条（罕见）

- **复现条件**：模板库空（首次部署未跑 `lib_manager.py import`），或 code_type 名字打错
- **操作**：
  1. 临时清空模板库：`docker exec dv_acode_gen_platform-postgres-1 psql -U dvuser -d dv_platform -c "UPDATE templates SET is_active=false;"`
  2. 触发任意生成请求
- **预期实际行为**：
  - 后端抛 `ValueError("未能从模板库中检索到合适的模板...")`
  - HTTP 422 响应
  - 前端弹错误提示
- **测试后恢复**：`UPDATE templates SET is_active=true;`

---

## 4. 缓存层行为验证

### §4.1 intent_cache_hit（同意图二次请求）

- **操作**：
  1. §0.3 清缓存
  2. 跑 §1.9 的 FSM 用例 → 等待完成（5-150s）
  3. **不改任何输入**，再点一次"生成代码"
- **预期**：
  - 第二次响应 < 1 秒
  - 前端"缓存命中"显示「是」
  - 后端日志**直接跳到** `INFO: POST 200 OK`，**没有** `[GLM Step1]` `[GLM Step2]` 等步骤

### §4.2 cache_hit（不同意图但同模板+参数）

- **操作**：
  1. §0.3 清缓存
  2. 跑 §1.9 用例
  3. 把"功能描述"改成另一种说法（如"FSM 状态转换 cur_state 3bit IDLE FETCH DECODE EXECUTE"），保持参数预期相同
- **预期**：
  - normalize_intent 仍跑（不同原文 → 不同 hash）
  - RAG / LLM 仍跑
  - 但最终 `set_generation_cache(template+params)` 命中（同 template_id + 同 params）
  - 前端"缓存命中"显示「是」，"意图缓存命中"显示「否」

### §4.3 切换默认 LLM 后的缓存行为 ⚠️

> **重要**：本会话先前对话有过"切换 LLM 自动清缓存"的说法，**与代码实际不符**。本节验证真实行为。

- **操作**：
  1. 先跑 §1.9 用例让缓存写入
  2. Admin → LLM 配置 → 把默认从 GLM-4-Plus 切到 GLM-4.7（或 Claude）
  3. 不清 Redis，**直接再跑** §1.9 同输入
- **预期实际行为**（基于 [admin_llm.py set_default 端点](../backend/app/api/v1/admin_llm.py)代码）：
  - **缓存仍命中**，不会重新调新 LLM
  - 用户拿到的是**旧 LLM 选的模板和参数**，**新 LLM 没机会发挥**
- **结论**：切换 LLM 后**必须手动**执行 §0.3 清缓存才能让新 LLM 生效
- **gap**：见附录 B

---

## 5. 模板贡献机制

### §5.1 完整流程：提交 → 通过 → 入库 → 命中

- **角色**：tester1（普通用户）+ admin（审核员）
- **操作**：

| 步骤 | 角色 | 操作 |
|---|---|---|
| 1 | tester1 | 登录 → 左菜单 **我的贡献** → 点 **提交贡献** |
| 2 | tester1 | 填写：name=`自定义信号驱动断言`，code_type=`assertion`，description=`验证特定信号在 valid 拉高后必须立即变化`，提供 template_body（含 Jinja2 占位）和 parameters JSON |
| 3 | tester1 | 提交 → 后端 `POST /api/v1/contributions` → 返回 contribution_id，状态 `pending` |
| 4 | admin | 登录 → Admin → **贡献审核** 页 → 看到该 pending 条目 |
| 5 | admin | 点详情查看 → 点 **批准** → 后端 `POST /contributions/{id}/approve` → 自动入库（`promoted_template_id` 字段被填上）|
| 6 | tester1 | 进 **通知** 看是否收到 `contribution_approved` 通知 |
| 7 | admin | 进 **模板库** 页 → 应能看到刚批准的新模板 |
| 8 | admin | 进 **生成代码** → 用描述触发该新模板 → 期望命中（confidence 0.9）|

- **后端验证**：
  ```sql
  -- 在 PG 中确认入库
  docker exec dv_acode_gen_platform-postgres-1 psql -U dvuser -d dv_platform \
    -c "SELECT id, status, promoted_template_id FROM template_contributions ORDER BY created_at DESC LIMIT 1;"
  ```
  期望 `status=approved`，`promoted_template_id` 非空。

### §5.2 流程：要求修改 → 重提

- **操作**：
  1. tester1 同 §5.1 步骤 1-3 提交贡献
  2. admin 在贡献审核页点 **请求修改** → 填评论 "参数定义不完整，请补充 default 值"
  3. tester1 收到 `needs_revision` 通知，点进去看 reviewer_comment
  4. tester1 进 **我的贡献** → 编辑该贡献 → 修改 parameters → 重新提交
  5. 后端把状态从 `needs_revision` 重新置为 `pending`
  6. admin 再次审核 → 批准
- **后端验证**：贡献 `updated_at` 比 `created_at` 晚

### §5.3 提交语义重复模板（已知 gap）

> ⚠️ **已知**：贡献 API **不调用** `check_semantic_duplicate`（验证：[contributions.py 全文 grep 无此调用](../backend/app/api/v1/contributions.py)），只有 `/templates` 直建路径才检测。

- **操作**：
  1. tester1 提交一份描述与 `cov_transition_coverage_v1` 高度相似的贡献（如"FSM 状态机的转换覆盖率统计..."）
  2. 后端**不会**自动提示"语义重复"
  3. admin 应**手动**在审核界面对比现有模板
- **手动验证语义重复**：
  ```bash
  # 用 backend 容器调 /admin/templates/dedup-check（如果有此端点）
  # 或直接查 Qdrant：
  docker exec dv_acode_gen_platform-backend-1 python -c "
  import httpx, asyncio
  async def main():
      r = await httpx.AsyncClient().post(
          'http://qdrant:6333/collections/templates/points/search',
          json={'vector': {'name': 'dense', 'vector': [<查询向量>]}, 'limit': 3}
      )
      print(r.json())
  asyncio.run(main())
  "
  ```
- **gap 修复建议**：见附录 B

---

## 6. 意图构建器

### §6.1 完整流程：场景 → 参数 → 构建 → 复制

- **操作**：
  1. 登录 → 左菜单 **意图构建器**
  2. 选 **代码类型** = `assertion`
  3. 看到场景列表（来自 [registry scenarios](../backend/app/services/registry.py)）
  4. 选场景 `cov_fsm`（举例）→ 显示该场景需要的参数（state_var, initial_state, target_state）
  5. 填参数：state_var=`cur_state`，initial_state=`IDLE`，target_state=`RUN`
  6. 点 **构建意图** → 后端 `POST /api/v1/intent-builder/build` → 返回标准句式 intent_text
  7. 点 **复制** → 浏览器弹"已复制到剪贴板"
  8. 点 **跳转到生成** → 进 generate 页，**功能描述** 框已预填刚构建的文本
  9. 直接点 **生成代码** → 期望命中 `sva_fsm_state_transition_v1`

### §6.2 漏填必填参数

- **操作**：在 §6.1 第 5 步**只填** state_var，留空其他
- **预期**：前端校验阻止提交，弹提示"请补充：initial_state, target_state"

---

## 7. 批量生成

### §7.1 完整流程：5 行 Excel → 下载 ZIP

- **准备 Excel** `batch_test.xlsx`（5 行）：

| row_id | intent | code_type | protocol | clk | rst | rst_polarity | signals |
|---|---|---|---|---|---|---|---|
| 1 | "FSM 转换覆盖率，IDLE FETCH DECODE EXECUTE" | coverage | | clk | rst_n | 低有效 | `[]` |
| 2 | "AXI 握手 valid 拉高后 ready 必须 8 周期内响应" | assertion | axi | clk | rst_n | 低有效 | `[]` |
| 3 | "数据稳定，valid 拉高 ready 未来" | assertion | | clk | rst_n | 低有效 | `[]` |
| 4 | "信号 mode 0-3 值覆盖率" | coverage | | clk | rst_n | 低有效 | `[]` |
| 5 | "复位释放后计数器归 0" | assertion | | clk | rst_n | 低有效 | `[]` |

- **操作**：
  1. 登录 → 左菜单 **批量处理** → 进 batch 页
  2. 选 **代码类型** = `coverage`（或 `assertion`，由 Excel 第一行决定）
  3. 上传 `batch_test.xlsx` → 后端 `POST /api/v1/batch/upload` → 返回 job_id
  4. 前端先调 `GET /batch/{job_id}/preflight` 显示预估 confidence 列表
  5. 点 **开始生成** → 提交到 Celery 队列
  6. 前端轮询 `GET /batch/{job_id}/status` 显示进度
  7. status = `done` 后点 **下载结果** → 下载 ZIP
  8. 解压 ZIP，验证含 `results.json` + 5 个 `.sv` 文件

- **预期总耗时**：5 行 × 单条耗时（GLM-4-Plus 约 5-15s/条 × 并发 = 1-3 分钟）

### §7.2 任务卡死诊断

如果 `status` 长时间停在 `running`：

```powershell
# 1. 看 celery worker 日志
docker logs -f dv_acode_gen_platform-celery_worker-1

# 2. 检查 Celery 活跃任务
docker exec dv_acode_gen_platform-celery_worker-1 celery -A app.tasks.celery_app inspect active

# 3. 查 batch_jobs 表状态
docker exec dv_acode_gen_platform-postgres-1 psql -U dvuser -d dv_platform \
  -c "SELECT id, status, total_rows, completed_rows, error_message, updated_at FROM batch_jobs ORDER BY created_at DESC LIMIT 3;"

# 4. 查 Redis 队列长度
docker exec dv_acode_gen_platform-redis-1 redis-cli -n 1 LLEN celery
```

常见原因：worker 崩溃（重启 `docker compose restart celery_worker`）、LLM API 卡（看 backend 日志）、并发太低（调 `.env` `CELERY_CONCURRENCY`）。

---

## 8. 模板库浏览

### §8.1 过滤与搜索

- **操作**：
  1. 登录 → 左菜单 **模板库** → 看到 10 个模板列表
  2. 选 **代码类型** = `coverage` → 应该只显示 4 个
  3. 输入 keyword `握手` → 应该只显示 1 个（`cov_protocol_handshake_v1`）
  4. 清除筛选 → 列表恢复 10 个

### §8.2 管理员编辑模板

- **角色**：admin / lib_admin
- **操作**：
  1. 进入模板库 → 点某个模板 → 点 **编辑**
  2. 修改 description
  3. 填 `change_note` = "微调描述"
  4. 提交 → 后端 `PATCH /api/v1/templates/{id}`
- **后端验证**：
  ```sql
  docker exec dv_acode_gen_platform-postgres-1 psql -U dvuser -d dv_platform \
    -c "SELECT template_id, version, change_note, created_at FROM template_versions ORDER BY created_at DESC LIMIT 1;"
  ```
  期望新 row 的 `version` 比模板原 version +1，`change_note` 即填入内容。

---

## 9. 用户管理

### §9.1 创建测试用户 + 改角色

- **角色**：admin（super_admin）
- **操作**：
  1. 登出 admin → 在登录页 **注册** tab 创建 `tester1`（普通用户角色，默认）
  2. 用 admin 登录 → Admin → **用户管理** → 找到 tester1
  3. 点 **改角色** → 选 `lib_admin` → 提交
  4. 后端 `PATCH /api/v1/admin/users/{id}/role`
- **后端验证（审计日志）**：
  ```sql
  docker exec dv_acode_gen_platform-postgres-1 psql -U dvuser -d dv_platform \
    -c "SELECT actor_id, action, target_id, payload, created_at FROM admin_audit_logs ORDER BY created_at DESC LIMIT 1;"
  ```
  期望 action = `change_role`，payload 含 from / to 角色。

### §9.2 禁用用户 → token 失效验证

- **操作**：
  1. tester1 在另一浏览器登录，记下 token（DevTools → Local Storage → `access_token`）
  2. admin 把 tester1 切 `is_active=false`：Admin → 用户管理 → tester1 → **禁用**
  3. tester1 浏览器**不刷新 token**，直接访问 generate 页（前端会自动调 `GET /api/v1/auth/me`）
- **预期**：
  - `/auth/me` 返回 401（因 [security.py get_current_user](../backend/app/core/security.py) 的 SQL filter 含 `is_active=True`）
  - 前端 axios 拦截 401 → 清空 localStorage → 跳转 `/login`

---

## 10. LLM 配置管理

### §10.1 添加 + 三类测试

- **操作**：
  1. Admin → **LLM 配置** → 点 **添加配置**
  2. 填：name=`Claude Sonnet (test)`，provider=`OpenAI Compatible`，base_url=`https://openrouter.ai/api/v1`，api_key=`<你的 key>`，model_id=`anthropic/claude-sonnet-4-6`，max_tokens=2048
  3. 保存 → 后端 `POST /api/v1/admin/llm/configs`
  4. 在该配置行点 **测试** → 后端 `POST /admin/llm/configs/{id}/test` → 三类校验：
     - **基础连通**：发 "Hello" 验证 API 可达
     - **意图标准化**：发固定测试意图验证输出格式
     - **模板选择**：发 RAG Prompt 验证 JSON 解析
  5. 全通过 → 弹绿条；任何一项失败 → 弹红条 + 错误详情

### §10.2 切换默认 → 缓存联动验证

- 配合 [§4.3](#43-切换默认-llm-后的缓存行为-) 一起测。**关键**：切换后**手动清缓存**（§0.3），否则新 LLM 不会生效。

### §10.3 删除当前默认配置（已知 gap）

> ⚠️ **已知**：[admin_llm.py 的 DELETE 端点](../backend/app/api/v1/admin_llm.py) **不检查** `is_default` 标志，可以直接删掉当前默认配置 → 后续生成会因找不到默认配置而 RuntimeError。

- **复现**：
  1. 当前默认是 `智谱大模型`
  2. 在 LLM 配置页点该行的 **删除** → 直接删除成功
  3. 试图触发任意代码生成 → backend `factory.py` 抛 RuntimeError
- **gap**：见附录 B

---

## 11. 通知机制

### §11.1 贡献状态触发的通知

完整覆盖在 §5 测试中：

| 触发动作 | 通知类型 | 收信人 |
|---|---|---|
| admin 批准贡献 | `contribution_approved` | 提交者（tester1）|
| admin 请求修改 | `contribution_needs_revision` | 提交者 |
| admin 拒绝贡献 | `contribution_rejected` | 提交者 |

### §11.2 未读计数

- **操作**：
  1. tester1 登录 → 顶部菜单的 **通知** 图标看徽标数字
  2. 触发任意 §11.1 通知 → 徽标 +1
  3. 点通知图标 → 看通知列表 → 点某条 → 后端 `POST /api/v1/notifications/{id}/read` → 该条变灰，徽标 -1
- **观察**：前端是 polling（每 N 秒刷一次）还是 WebSocket 推送 → 看 DevTools Network 面板

---

## 附录 A：故障排查 cheatsheet

测试中遇到的"环境问题"统一查 [deployment-dev-windows.md §8](deployment-dev-windows.md#8-常见问题与故障排查)，特别是：

- Docker daemon 崩溃 → §8.1 完整重启
- 代码生成超时 / 失败 → §8.2 排查顺序
- 前端不显示新代码 → §8.4 验证 bundle 是否最新

测试专用补充：

```powershell
# 看完整的 pipeline 日志（加时间戳）
docker logs -t dv_acode_gen_platform-backend-1 --since 5m | Select-String "Pipeline|GLM|RAG"

# 看 Redis 当前所有缓存 key
docker exec dv_acode_gen_platform-redis-1 redis-cli KEYS "*"

# 看某个 generation_cache 的具体内容
docker exec dv_acode_gen_platform-redis-1 redis-cli GET "<完整 key>"

# 看 Qdrant 中模板向量数量
docker exec dv_acode_gen_platform-backend-1 python -c "
import httpx, asyncio
async def main():
    r = await httpx.AsyncClient().get('http://qdrant:6333/collections/templates')
    print(r.json()['result']['points_count'], 'points')
asyncio.run(main())
"
```

---

## 附录 B：已知功能-UI gap 清单

> 这里列的是**代码当前实际行为与 PRD 期望行为的差距**。QA 看到这些场景**不要当 bug 报**，团队后续根据优先级决定修不修。

### B.1 切换默认 LLM 不自动清空 Redis 缓存
- **位置**：[backend/app/api/v1/admin_llm.py](../backend/app/api/v1/admin_llm.py) `set_default` 端点
- **现状**：只更新 `llm_configs.is_default`，无 Redis 操作
- **影响**：用户期望"切了新模型就能让新模型干活"，但实际仍走旧缓存
- **临时绕过**：手动 §0.3 FLUSHDB
- **修复建议**：在 `set_default` 内添加 `await flush_intent_cache()` + `await flush_generation_cache()`

### B.2 删除当前默认 LLM 配置无防呆
- **位置**：[backend/app/api/v1/admin_llm.py](../backend/app/api/v1/admin_llm.py) DELETE 端点
- **现状**：直接 `db.delete(cfg)` 不检查 `is_default`
- **影响**：删完后所有代码生成 RuntimeError
- **临时绕过**：删除前先把另一个配置设为默认
- **修复建议**：在 DELETE 端点加 `if cfg.is_default: raise HTTPException(409, "不能删除当前默认配置...")`

### B.3 贡献 API 不调用语义去重检查
- **位置**：[backend/app/api/v1/contributions.py](../backend/app/api/v1/contributions.py) `POST /contributions`
- **现状**：直接创建 contribution 记录，不调用 `check_semantic_duplicate`
- **对比**：[backend/app/services/core/dedup.py](../backend/app/services/core/dedup.py) 中的去重逻辑只在 `/templates` 直建路径用
- **影响**：同一模板可能被多个贡献者重复提交，审核员需手动判断
- **临时绕过**：审核员人工核对
- **修复建议**：在贡献 POST 端点加去重检查，相似度 ≥ 0.90 时返回 200 + `duplicate_warning`，由前端弹"已存在相似模板，是否仍提交"

### B.4 后端不强制 confidence_threshold + confidence 显示语义混乱
- **位置**：`pipeline.py` 全文 grep 无 `confidence_threshold` 引用，[config.py:35](../backend/app/core/config.py#L35) 的常量只在 preflight 用
- **现状 1**：低置信度（如 0.1）仍正常返回 200 + 代码
- **现状 2（实测发现）**：前端显示的 "置信度" 数值在不同路径下含义不同：
  - LLM Step1 主动选中 → confidence = **0.9**（固定值，[openai_compat_client.py:78](../backend/app/services/llm/openai_compat_client.py#L78)）
  - LLM Step1 失败 fallback 到 RAG[0] → confidence = **rag_candidates[0]["score"]**（可达 1.0）
  - intent_cache_hit → confidence = 历史记录值（默认 1.0）
  - 即"100% 置信度"可能是 **RAG 排序分数** 而非 LLM 真实判断分数 → 选错模板时反而 confidence 更高（误导用户）
- **影响**：用户看到 100% 绿色高置信度，以为模板选对了，实际是 fallback 路径硬塞 RAG[0]
- **复现案例**：测试手册 §2.5-A v1 输入（"数据寄存器在写使能 wr_en 无效期间保持稳定"）→ confidence 100% 但选错为 sva_handshake_stable_v1
- **临时绕过**：除了看 confidence，还要核对前端显示的"模板"字段是否符合预期；后端日志的 `[GLM Step1] selected=...` 与 `LLM selected '...', fallback to: ...` 区分了主动选中 vs fallback
- **修复建议**：
  1. 区分前端显示：LLM 选中显示 confidence，fallback 路径显示 "RAG 推荐（无 LLM 信心）"
  2. confidence < 0.5 时前端弹 Modal 警告
  3. confidence < 0.3 时后端返回 422 + 提示文本

### B.5 ColBERT Stage2 当前实质退化
- **位置**：[backend/app/services/rag/stage1_hybrid.py](../backend/app/services/rag/stage1_hybrid.py) 不再请求 `with_vectors=["colbert"]`
- **现状**：Stage1 不返回 ColBERT 向量 → Stage2 拿不到向量做 MaxSim → 直接用 dense+sparse 排序结果
- **影响**：三阶段名义存在，实际只走两阶段
- **临时绕过**：无影响（命中率仍可接受）
- **修复建议**：要么恢复请求 colbert 向量，要么从架构文档中下调"三阶段"宣称为"两阶段 + reranker"

---

## 索引

- 部署本机环境：[deployment-dev-windows.md](deployment-dev-windows.md)
- 生产部署：[deployment-prod-linux.md](deployment-prod-linux.md)
- 架构理解：[../ARCHITECTURE.md](../ARCHITECTURE.md)
- 产品需求：[../PRD.md](../PRD.md)
- 团队协作：[../CONTRIBUTING.md](../CONTRIBUTING.md)
