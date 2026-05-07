# 平台功能测试 — 场景 Bug 与优化点记录

**起始日期**：2026-05-07
**适用版本**：v1.0.0（迁移到 WSL Ubuntu-22.04 后首轮 alpha 测试）
**职责范围**：仅记录"测试用户可见功能"时发现的场景类问题——模板选错、参数抽取错、生成代码错、UI 交互错等。
**不收录**：平台架构、部署、运维、环境层面的问题 —— 见 [platform-bug.md](platform-bug.md)。

**用法**：测试期间发现一条记一条，**全部测完后再统一按优先级处理**。每条遵循"现象 / 根因 / 解决方案 / 优先级 / 状态"四段式，可直接作为修复任务清单使用。

---

## 优先级定义

| 标记 | 含义 | 处理时机 |
|---|---|---|
| 🔴 P0 | 阻断核心功能（生成不出代码 / 选错模板）| 测试结束后立即 |
| 🟠 P1 | 影响用户体验或检索准确性 | 第一轮优化 |
| 🟡 P2 | 边角问题或已知技术债 | 第二轮优化 |
| 🟢 P3 | 极少触发或可文档绕过 | 仅记录 |

---

## #001 — 自然语言参数提取失败，4 个必填参数全占位符

- **发现日期**：2026-05-07
- **测试场景**：握手数据稳定性断言
- **测试输入**：`AXI 握手过程中 awvalid 拉高但 awready 未响应时，awaddr 数据信号必须保持稳定，模块 axi_master`
- **优先级**：🟠 P1（影响"纯自然语言生成"路径的可用性）
- **状态**：已知短板，有架构层 + 模板层两条优化路径

### 现象

- ✅ RAG 选对模板：`sva_handshake_stable_v1`，score 1.00
- ❌ 4 个必填参数全部 🔴 占位符：`module_name` / `valid` / `ready` / `data`
- 平台正确拒绝生成（StrictUndefined 设计），用户必须手填后才能点"确认并生成代码"

### 根因

`backend/app/services/core/pipeline.py` 中 `_extract_params_from_intent()` 的正则 patterns 期望**"角色 [为/是/：/:] 信号名"**强分隔符模式：

```python
_ASSERTION_SIGNAL_PATTERNS = [
    (r'valid(?:\s*信号)?\s*[为是：:]\s*([A-Za-z_]\w*)', ['valid']),
    (r'ready(?:\s*信号)?\s*[为是：:]\s*([A-Za-z_]\w*)', ['ready']),
    (r'数据(?:信号)?名?\s*[为是：:]\s*([A-Za-z_]\w*)', ['data']),
    ...
]
m = re.search(r'模块名?\s*[为是：:]\s*([A-Za-z_]\w*)', intent)
```

而用户输入用的是**"信号名 + 动词/角色"**口语化表达：

| 用户写法 | 正则期望 | 命中？ |
|---|---|---|
| `awvalid 拉高` | `valid 为 awvalid` | ❌ |
| `awready 未响应` | `ready 信号为 awready` | ❌ |
| `awaddr 数据信号` | `数据信号为 awaddr` | ❌（"数据"在信号名之后）|
| `模块 axi_master` | `模块名为 axi_master` | ❌（无 `:/为/是` 分隔符）|

LLM Step2（`openai_compat_client._step2_fill_params`）对该输入也没补上参数——可能是当前默认 LLM 在"动词式描述"上抽参能力弱。

### 解决方案

**方案 A — 扩展正则（成本低，覆盖 80% 场景）**：

在 `_ASSERTION_SIGNAL_PATTERNS` 增加"信号名前置"的 patterns：

```python
# 新增"信号名 + 动词"模式
(r'([A-Za-z_]\w*)\s*(?:拉高|有效|valid)',                 ['valid']),
(r'([A-Za-z_]\w*)\s*(?:未响应|未到来|应答|响应|ready)',     ['ready']),
(r'([A-Za-z_]\w*)\s*(?:数据信号|地址信号|payload)',         ['data']),
(r'([A-Za-z_]\w*)\s*(?:使能信号|enable)',                  ['enable']),
```

放宽 `module_name` 正则的分隔符要求（兼容空格）：

```python
m = re.search(r'模块(?:名)?\s*[为是：:\s]\s*([A-Za-z_]\w*)', intent)
```

**方案 B — 改 LLM Step2 Prompt（成本中，根治）**：

在 `_step2_fill_params` 的 system prompt 加 few-shot examples，明确"动词式描述如何抽参"：

```
示例：
输入：awvalid 拉高但 awready 未响应时，awaddr 必须稳定，模块 axi_master
输出：{"valid": "awvalid", "ready": "awready", "data": "awaddr", "module_name": "axi_master"}
```

**方案 C — 用户引导（成本零，覆盖 95% 场景）**：

`docs/test-manual.md` 强调"信号列表 + role-hint" 是 assertion 模板的**主推工作流**，自然语言只作为"意图描述"。前端"添加信号"按钮上加一行 placeholder："assertion 模板强烈推荐填信号列表"——前端代码已经有这句提示，但用户测试时跳过了。

### 推荐执行顺序

1. 先做方案 A（改 `pipeline.py:_ASSERTION_SIGNAL_PATTERNS`，加单元测试），覆盖最常见的"动词式"输入
2. 同时做方案 C（文档侧，引导用户用信号列表）
3. 方案 B 留作 LLM 升级后的优化项

---

## #002 — RAG 模板检索误判，timing_max_delay 被 reset_behavior 抢

- **发现日期**：2026-05-07
- **测试场景**：最大延迟时序约束断言
- **测试输入**：`请求信号 req_sig 发送后，应答信号 ack_sig 必须在 8 周期内返回，模块 ack_engine`
- **优先级**：🔴 P0（核心检索功能失准，影响一类常见场景）
- **状态**：已定位根因，方案明确

### 现象

- ❌ 系统选了 `sva_reset_behavior_v1`（**复位释放后初始值断言**），score 1.00，置信度来源标"RAG 兜底"
- ✅ 期望的 `sva_timing_max_delay_v1` 在候选下拉里只排第 3，score 0.50
- LLM Step1 选不出来（候选里 reset_behavior 的描述和用户输入太像），系统退回 RAG top-1

用户必须手动从下拉切换到正确模板才能继续。

### 根因

两个模板的 `description` 字段是 RAG 编码的主要文本。对比：

```yaml
# sva_reset_behavior_v1
description: 验证复位信号释放后目标信号必须在指定周期内达到初始值

# sva_timing_max_delay_v1
description: 约束起始事件发生后结束事件必须在指定最大延迟周期内发生
```

用户输入的句式骨架是 "**信号** X 后，**信号** Y 必须在 N **周期内**…"。`reset_behavior` 用了"**信号**"+"释放后"，结构上更近；`max_delay` 用了"**事件**"+"发生后"这种 SVA 教科书抽象术语，反而距离远。

bge-m3 是通用中文 embedding，对"信号"和"事件"明显视为不同词。

`pipeline.py:_keyword_supplement` 的关键词兜底也救不了——`max_delay` 当前 keywords 是 `延迟 / 时序 / latency / max_delay / 响应时间`，**用户输入里一个都没出现**（用户写的是"返回"不是"延迟/响应/latency"）。

更广的问题：**任何描述里"信号 ... 必须在 ... 周期内 ..."的模板都会被 reset_behavior 偷流量**——这是当前模板库的"通吃陷阱"。

### 解决方案

**方案 A — 扩 `timing_max_delay.yaml` 的 description / keywords（必做）**：

```yaml
description: |
  约束起始事件发生后结束事件必须在指定最大延迟周期内发生，用于验证时序SLA。
  适用场景：请求-应答延迟约束（req-ack）、信号响应时间限制、返回延迟、超时前必须完成的时序约束。
keywords:
  - 延迟
  - 时序
  - latency
  - max_delay
  - 响应时间
  - 请求       # 新增
  - 应答       # 新增
  - 返回       # 新增
  - req        # 新增
  - ack        # 新增
  - 响应       # 新增
```

加 6 个 keywords 后，`pipeline.py:_keyword_supplement` 会因为用户输入命中"请求/应答/返回"3 个关键词，主动把 max_delay 加分插队到候选头部，绕开 dense embedding 的偏差。

**方案 B — 改 `reset_behavior.yaml` 收窄适用范围（建议做）**：

```yaml
description: |
  验证**复位信号释放**后目标信号必须在指定周期内达到初始值，确保正确的复位行为。
  仅用于复位/上电场景，不适用于一般的请求-应答时序约束。
```

加"不适用于…"虽不影响 dense 距离，但对 LLM Step1 看候选时是强引导，让它在用户输入不含"复位/reset"时主动跳过。

**方案 C — 全模板库审计 keywords（中期）**：

设计一份关键词覆盖度审查清单：每个模板的 keywords 必须涵盖"工程师口语术语 + 教科书术语 + 协议名"三类。当前模板库里 6 个 assertion + 4 个 coverage 模板都该过一遍。

**方案 D — 改进 `_keyword_supplement` 算法（长期）**：

当前实现是"小写子串匹配 + 命中次数"。可以加：
- 同义词扩展（"返回" → "响应"、"应答"）
- 反义关键词降权（用户输入有"复位"才让 reset_behavior 加分；没有则保持原 RAG 排序）

### 验证方式

修复后用同样输入再测一次 `请求信号 req_sig 发送后，应答信号 ack_sig 必须在 8 周期内返回`，预期：
- 推荐模板变为 `sva_timing_max_delay_v1`，score ≥ 0.85
- 置信度来源标"LLM" 或正常 RAG（不再是 "RAG 兜底"）

### 推荐执行顺序

1. 先做方案 A（仅 1 份 YAML 改动 + `lib_manager.py import --force` 重灌），最快验证假设
2. 改完用同 input 回归测试
3. 通过后做方案 B（同样的 import）
4. 方案 C 作为下一轮全库审计任务
5. 方案 D 留作 RAG 引擎层迭代

---

## #003 — Coverage 模板 group_name 被 LLM 填成中文话题描述，前端 SV 标识符校验拒绝生成

- **发现日期**：2026-05-07
- **修复日期**：2026-05-07（同日修复）
- **测试场景**：协议握手覆盖率组（`cov_protocol_handshake_v1`）
- **测试输入**：`收集 AXI valid-ready 四种握手场景覆盖率，包括握手成功、valid 等待、ready 预备、空闲，valid 信号 awvalid，ready 信号 awready`
- **优先级**：🔴 P0（影响所有 4 个 coverage 模板的可生成性）
- **状态**：✅ **已修复**（方案 B + B 内嵌 D 轻量版）

### 现象

- ✅ RAG / LLM Step1 选对模板：`cov_protocol_handshake_v1`，置信度来源"LLM 主动选中"
- ✅ `valid` = `awvalid`、`ready` = `awready` 被 LLM 正确抽取
- ❌ `group_name` 被 LLM 填成 `"AXI valid-ready握手场景覆盖率"` —— 含中文、空格、连字符
- ❌ 前端校验"必须是合法 SystemVerilog 标识符（字母/下划线开头，仅字母/数字/下划线）"失败 → 整体生成被拒

### 根因（三层叠加）

**层 1 — LLM Step2 的 prompt 没说格式约束**（`backend/app/services/llm/openai_compat_client.py:138-148`）：

```python
system = "你是IC验证工程师。根据用户描述，为指定模板填写参数的真实值。\n要求：只返回 JSON 对象，不要其他说明；参数值必须来自描述中的实际内容，不要使用占位符。"
```

prompt 没告诉 LLM "`group_name` 必须是合法 SV 标识符"。LLM 看到 description 是"覆盖率组名"，就把用户描述里的话题"AXI valid-ready握手场景覆盖率"当 group_name 返回。

**层 2 — 模板 YAML 的 description 太弱**（`backend/template_library/coverage/protocol_handshake_coverage.yaml`）：

```yaml
- name: group_name
  type: string
  required: true
  description: 覆盖率组名      # 没有任何关于格式约束的说明
```

`group_name` 直接拼进 `template_body` 的 SV 标识符位置：`covergroup cg_{{ group_name }}_handshake`、`cg_{{ group_name }}_handshake cg_{{ group_name }}_handshake_inst = new();` —— 必须是合法 identifier，但这条约束没写在 description 里。

**层 3 — 正则前置兜底覆盖率太低**（`backend/app/services/core/pipeline.py:_extract_params_from_intent`）：

```python
m = re.search(r'(?:状态)?信号名?[为是：:]\s*(\w+)', intent)
if m:
    params["signal"] = m.group(1)
    params["group_name"] = m.group(1)
```

只在"信号名为 X"强分隔符模式下命中。用户没用这种模式时，group_name 完全压给 LLM 决定。

**层 4 — 后端缺少 sanitize 步骤**：LLM 或正则给的非法 identifier 直接进 params 透传给前端，后端没做格式清洗 / 自动转换。

### 解决方案

**方案 A — LLM Step2 prompt 加格式约束（必做，成本最低）**：

`openai_compat_client.py:138-142` 改写 system prompt：

```python
system = (
    "你是IC验证工程师。根据用户描述，为指定模板填写参数的真实值。\n"
    "要求：\n"
    "1. 只返回 JSON 对象，不要其他说明；\n"
    "2. 参数值必须来自描述中的实际内容，不要使用占位符；\n"
    "3. 名为 group_name / module_name / signal / valid / ready / data / start_event / end_event / target / state_sig 的参数必须是合法 SystemVerilog 标识符——只能包含 ASCII 字母、数字、下划线，且首字符为字母或下划线；\n"
    "4. 若用户描述里没有合法 identifier 可用，请构造形如 cov_<场景> / <module>_<role>_sig 的英文标识符，不要使用中文。"
)
```

**方案 B — 后端加 sanitize 兜底（强烈推荐，根治）**：

在 `pipeline.py` 的 `_map_params_with_source` 收尾处加一步"identifier 清洗"：

```python
def _sanitize_identifier(value: str, fallback_prefix: str) -> str:
    """把任意字符串清洗成合法 SystemVerilog 标识符。"""
    import re
    # 中文/标点/空格统一转 _，再保留字母数字下划线
    cleaned = re.sub(r'[^A-Za-z0-9_]', '_', value)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    if not cleaned or not re.match(r'[A-Za-z_]', cleaned):
        cleaned = f"{fallback_prefix}_{cleaned}" if cleaned else fallback_prefix
    return cleaned[:64]  # SV 标识符长度上限保守取 64

# 标记哪些参数名需要 SV 标识符
_IDENTIFIER_PARAMS = {"group_name", "module_name", "signal", "valid", "ready", 
                      "data", "start_event", "end_event", "target", "state_sig"}

# 在 _map_params_with_source 末尾收尾时：
for name, meta in result.items():
    if name in _IDENTIFIER_PARAMS and isinstance(meta["value"], str):
        cleaned = _sanitize_identifier(meta["value"], fallback_prefix=name)
        if cleaned != meta["value"]:
            meta["value"] = cleaned
            meta.setdefault("sanitized", True)  # 前端可据此提示"已自动清洗"
```

这样不管 LLM、正则、用户手填出现什么奇葩值，后端都能保证渲染拿到的 group_name 是合法 SV identifier。

**方案 C — 模板 YAML description 加格式提示（建议做）**：

每个使用 group_name / module_name / signal 等参数的模板，在 YAML description 加一行明确格式：

```yaml
- name: group_name
  type: string
  required: true
  description: 覆盖率组名（必须是合法 SystemVerilog 标识符，仅含字母/数字/下划线，首字符为字母或下划线）
  default: cov_handshake     # 给一个保守的默认值
```

LLM 看到 description 里就有这条约束，会比方案 A 的 system prompt 更"近"地引导它。

**方案 D — 改正则前置生成 group_name（建议做）**：

`pipeline.py:_extract_params_from_intent` 增加构造逻辑：

```python
# 优先用模块名构造 group_name
m_module = re.search(r'模块(?:名)?\s*[为是：:\s]\s*([A-Za-z_]\w*)', intent)
if m_module:
    params.setdefault("group_name", f"{m_module.group(1)}_cov")

# 否则用 valid/ready 构造
elif "valid" in params and "ready" in params:
    params.setdefault("group_name", f"{params['valid']}_{params['ready']}_cov")
```

### 验证方式

修复后用同样输入再测一次。预期：
- `group_name` 自动填为 `cov_handshake` 或 `awvalid_awready_cov` 之类合法 identifier
- 前端校验通过，"确认并生成代码"按钮可点
- 渲染出的 `cg_<group_name>_handshake` 在 SV 编译器下合法

### 推荐执行顺序

1. **方案 B（sanitize 兜底）必做**——这是结构性防御，覆盖所有渠道（LLM / 正则 / 用户手填）。一次实现，全模板受益
2. **方案 A（prompt 加约束）和方案 C（YAML 加格式提示）配套做**——降低 sanitize 真正被触发的频率
3. **方案 D（正则前置构造）选做**——锦上添花，让方案 B 在更多情况下不需要兜底
4. 修完用本文件 #003 input + 其余 3 个 coverage 模板各跑一次，确认全部通过

### 实际修复过程（2026-05-07）

**最终方案**：B（后端 sanitize）+ B 内嵌 D 轻量版（智能 group_name 构造），舍弃 A 和 C。

**理由**：B 已守住正确性，A 是依赖 LLM 听话的软约束、C 对结果无影响——两者都是浪费。D 完整版（独立正则 pass）太重，作为 sanitize 内嵌的智能 fallback 实现即可。

**改动清单**：

| 文件 | 改动 |
|---|---|
| `backend/app/services/core/identifier.py` | 新增（约 80 行）：`IDENTIFIER_PARAMS` 常量（与前端 `validateParam.ts` 严格对齐）+ `is_sv_identifier()` + `sanitize_sv_identifier()` + `construct_group_name()` |
| `backend/app/services/core/pipeline.py` | 顶部加 import；`_map_params_with_source` 末尾插入 sanitize pass（智能 group_name 修复 + 全 IDENTIFIER_PARAMS 兜底清洗），加 sanitized=True flag |
| `backend/app/schemas/generate.py` | `ParamWithSource` 加可选 `sanitized: bool = False` 字段，确保 flag 能透传到前端 |
| `backend/tests/test_extract_params.py` | 追加 13 个测试（6 个 sanitize 单元 + 5 个 construct_group_name + 1 个 IDENTIFIER_PARAMS 与前端契约对齐 + 1 个 _map_params 集成）|

**不动的部分**：前端 `validateParam.ts`、所有 10 个模板 YAML、LLM 客户端 prompt、`_extract_params_from_intent` 正则——按"最小范围修复"原则。

**清洗规则**：`sanitize_sv_identifier()`：
1. 已合法 → 原样返回
2. 非 `[A-Za-z0-9_]` 字符 → `_`
3. 连续 `_` 合并为单个 `_`
4. 去首尾 `_`
5. 首字符不是字母/下划线 → 加 `fallback_prefix` 前缀
6. 长度截断到 64

**智能 group_name 构造优先级**：`module_name + _cov` > `valid + _ + ready + _cov` > `signal + _cov` > 无（退到纯 sanitize）。每个候选自身必须是合法 identifier 才参与构造，避免用非法值再拼出非法值。

**回归验证**：

```bash
docker compose exec backend python -m pytest tests/test_extract_params.py -v
# 35 passed in 1.45s（22 既有 + 13 新增）
```

端到端用 #003 原始 input 调 `/api/v1/generate/preview`：
- ✅ `group_name = "awvalid_awready_cov"`（智能构造命中 valid+ready 分支，合法 SV 标识符）
- ✅ `source = "default"`（智能构造改源）
- ✅ `sanitized = true`（标记已清洗）
- ✅ confidence_source: `llm_step1`（LLM 选对模板，不再 RAG 兜底）
- ✅ 其他 4 个参数 LLM 抽取正确无修改

### 补全（2026-05-07）：`from_state` / `to_state` 同步纳入 IDENTIFIER_PARAMS

**触发**：代码审查 #003 修复后系统性检查"还有哪些参数实际是 SV 标识符但未被前后端契约收录"，发现 `sva_fsm_state_transition_v1` 模板的 `from_state` / `to_state` 在 template_body 中：

```jinja
property p_fsm_{{ from_state }}_to_{{ to_state }};   ← property 名（必须 SV identifier）
({{ state_sig }} == {{ from_state }}) ...            ← 状态值比较（必须 SV 标识符/枚举值名）
```

它们事实上就是 SV 标识符，但前端 `validateParam.ts:11-15` 的 `SIGNAL_PARAM_NAMES` 没收录、后端 `IDENTIFIER_PARAMS` 也没收录——属"已知漏洞"，FSM 模板下次有人测就可能踩。

**改动**：
- `backend/app/services/core/identifier.py`：`IDENTIFIER_PARAMS` 增加 `from_state` / `to_state`
- `frontend/src/utils/validateParam.ts`：`SIGNAL_PARAM_NAMES` 同步增加；行 49 注释从"自由文本参数（state_list / bins_expr / from_state / condition 等）"改为"自由文本参数（state_list / bins_expr / condition 等 SV 表达式语法）"——把 `from_state` 从自由文本组移除
- `backend/tests/test_extract_params.py`：`test_identifier_params_match_frontend` 期望集合扩到 16 个；新增 `test_sanitize_from_state_chinese` 测试中文输入降级行为

**回归**：
- 单元测试 `pytest tests/test_extract_params.py` → 36 passed
- 端到端 FSM 模板用"FSM 状态机断言：当 启动信号 ena 拉高时，FSM 必须从 空闲状态 转换到 运行状态，状态信号是 cur_state，模块 fsm_ctrl"：LLM 给 `from_state="空闲状态"` / `to_state="运行状态"`，sanitize 降级为合法 `from_state` / `to_state`，标记 `sanitized=true`，平台未崩、能继续渲染合法 SV

**遗留**（不在本次范围）：FSM 模板的 `condition` 是 SV 布尔表达式语法、`state_list` / `bins_expr` 是 SV bins 语法——这三个不是单一 identifier，需要不同的语法 lint 而非 sanitize，属架构级技术债，记入 `platform-bug.md` 待长期修。

---

## 待补充测试场景

按 `docs/test-manual.md` 的测试章节顺序，下面这些还没测，测到再往本文件追加 #003 / #004 / …：

- [ ] FSM 状态转移断言（`sva_fsm_state_transition_v1`）
- [ ] 数据完整性断言（`sva_data_integrity_v1`）
- [ ] 复位行为断言独立测试（确认 reset_behavior 在合理输入下能被选中）
- [ ] 4 个 coverage 模板：值覆盖、转移覆盖、交叉覆盖、状态覆盖
- [ ] 批量处理流程：上传 Excel → preflight → 批量生成 → 打包下载
- [ ] 意图构建器（场景化结构化输入）
- [ ] 模板贡献流程：用户提交 → 管理员审核 → 入库
- [ ] LLM 多模型切换：测试不同 LLM 对参数提取能力的影响
- [ ] 三级权限：普通用户 / 库管理员 / 超管
- [ ] 模板查重机制（dense-only 阈值 0.90）
- [ ] 历史意图缓存命中（重复输入秒返回）

---

## 优先级总览（持续刷新）

| ID | 标题 | 优先级 | 状态 |
|---|---|---|---|
| #001 | 自然语言参数提取失败 | 🟠 P1 | 待修 |
| #002 | RAG 模板检索误判（timing_max_delay 被抢）| 🔴 P0 | 待修 |
| #003 | Coverage group_name 被填成中文话题，SV 标识符校验拒绝 | 🔴 P0 | ✅ 已修复 (2026-05-07) |

---

## 修复后的回归测试基线

每条 bug 修完后，至少要让以下输入"原状"通过（不需要切下拉、不需要手填）：

```
# 对应 #001 修复
握手数据稳定：AXI 握手过程中 awvalid 拉高但 awready 未响应时，awaddr 数据信号必须保持稳定，模块 axi_master

# 对应 #002 修复
最大延迟时序：请求信号 req_sig 发送后，应答信号 ack_sig 必须在 8 周期内返回，模块 ack_engine

# 对应 #003 修复
协议握手覆盖率：收集 AXI valid-ready 四种握手场景覆盖率，包括握手成功、valid 等待、ready 预备、空闲，valid 信号 awvalid，ready 信号 awready
```

把这两条加进 `docs/test-manual.md` 的"易混淆对照"或新建"自然语言鲁棒性"小节，作为长期回归用例。
