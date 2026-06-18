"""Unit tests for pipeline_preview / pipeline_render split (方案 3)。

跑法（容器内）:
    docker compose exec backend pytest tests/test_pipeline_preview_render.py -v

测试不依赖真实 LLM API / Qdrant / PostgreSQL，全部用 unittest.mock 桩。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.core.pipeline import (
    CodeTypeMismatchError,
    OffTopicIntentError,
    PipelineInput,
    PreviewResult,
    RenderInput,
    UnderSpecifiedIntentError,
    _detect_under_specified,
    _map_params_with_source,
    _values_only,
    pipeline_preview,
    pipeline_render,
)
from app.schemas.intent import TemplateSelectionOutput


# ── _map_params_with_source 单测（纯函数，最易测）───────────────────────

class _FakeTemplate:
    """最小 Template 桩，只暴露 parameters 字段。"""
    def __init__(self, parameters):
        self.parameters = parameters


def _make_inp(signals=None, clk="clk", rst="rst_n", rst_polarity="低有效",
              original_intent="dummy"):
    return PipelineInput(
        original_intent=original_intent,
        code_type="assertion",
        clk=clk,
        rst=rst,
        rst_polarity=rst_polarity,
        signals=signals or [],
    )


def test_map_params_priority_llm_wins_over_regex():
    """LLM mapping 应覆盖 regex 提取（与 legacy {**extracted, **llm} 行为一致）。"""
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "type": "string", "description": "模块名"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(),
        regex_mapping={"module_name": "from_regex"},
        llm_mapping={"module_name": "from_llm"},
    )
    assert result["module_name"]["value"] == "from_llm"
    assert result["module_name"]["source"] == "llm"


def test_map_params_regex_when_no_llm():
    """LLM 没给该参数 → 用 regex 值，source 标 regex。"""
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(),
        regex_mapping={"module_name": "reg_block"},
        llm_mapping={},
    )
    assert result["module_name"]["value"] == "reg_block"
    assert result["module_name"]["source"] == "regex"


def test_map_params_signal_list_role_hint():
    """LLM/regex 都没给 → 走 signal-list role-hint 自动映射。"""
    template = _FakeTemplate([
        {"name": "enable", "required": True, "role_hint": "enable", "type": "string"},
        {"name": "data", "required": True, "role_hint": "data", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(signals=[
            {"name": "wr_en", "width": 1, "role": "enable"},
            {"name": "data_reg", "width": 32, "role": "data"},
        ]),
        regex_mapping={},
        llm_mapping={},
    )
    assert result["enable"]["value"] == "wr_en"
    assert result["enable"]["source"] == "signal_list"
    assert result["data"]["value"] == "data_reg"
    assert result["data"]["source"] == "signal_list"


def test_map_params_default_clk_rst():
    """clk / rst_n 走 PipelineInput 默认值，source=default。"""
    template = _FakeTemplate([
        {"name": "clk", "required": True, "default": "clk", "type": "string"},
        {"name": "rst_n", "required": True, "default": "rst_n", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(clk="my_clk", rst="my_rst"),
        regex_mapping={},
        llm_mapping={},
    )
    assert result["clk"]["value"] == "my_clk"
    assert result["clk"]["source"] == "default"
    assert result["rst_n"]["value"] == "my_rst"
    assert result["rst_n"]["source"] == "default"


def test_map_params_placeholder_for_required_missing():
    """required 参数所有兜底都没命中 → 用参数名占位，source=placeholder。

    这是 §1.1 v2 实测发现的 bug 场景：用户没在信号列表填 enable，
    LLM Step2 也没把"使能 wr_en"映射出来 → enable 字段拿到字面量 "enable"。
    新方案 3 的前端会用红色徽标显示，禁用「生成代码」按钮逼用户改。
    """
    template = _FakeTemplate([
        {"name": "enable", "required": True, "role_hint": "enable", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(signals=[]),  # 信号列表为空，role-hint 无源可映射
        regex_mapping={},
        llm_mapping={},
    )
    assert result["enable"]["value"] == "enable"  # 字面量参数名
    assert result["enable"]["source"] == "placeholder"
    assert result["enable"]["required"] is True


def test_map_params_template_default():
    """template.default 字段用于非 required 的兜底（如 max_cycles=16）。"""
    template = _FakeTemplate([
        {"name": "max_cycles", "required": True, "default": 16, "type": "integer"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(),
        regex_mapping={},
        llm_mapping={},
    )
    assert result["max_cycles"]["value"] == 16
    assert result["max_cycles"]["source"] == "default"


def test_map_params_meta_fields_populated():
    """每个 entry 应含 required / description / type 字段（前端用）。"""
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "type": "string", "description": "模块名"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(),
        regex_mapping={"module_name": "reg_block"},
        llm_mapping={},
    )
    entry = result["module_name"]
    assert entry["required"] is True
    assert entry["description"] == "模块名"
    assert entry["type"] == "string"


def test_map_params_trivial_llm_value_falls_through_to_default():
    """LLM 给 trivial 值 ("unknown") 时跳过槽位，让模板 default 接管。

    回归 FIX-1：寄存器写保护场景 LLM 把 module_name 填成 "unknown"，原实现把它
    标 source=llm 锁死槽位，under_specified 闸再把它拦下 → 用户被赶到 IntentBuilder。
    修复后 trivial LLM 值跳过，default="dut" 接管，pipeline 直接出码。
    """
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "default": "dut", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(),
        regex_mapping={},
        llm_mapping={"module_name": "unknown"},
    )
    assert result["module_name"]["value"] == "dut"
    assert result["module_name"]["source"] == "default"


def test_map_params_nontrivial_llm_value_is_kept():
    """非 trivial 的 LLM 值（且 grounded 在原文中）仍保留 source=llm，不被 default 吞掉。

    双重回归保护：
      - FIX-1：trivial 守卫只跳过 _TRIVIAL_LLM_VALUES 里的值，不能误伤合法 LLM 输出。
      - FIX-2：grounding 守卫只在 LLM 值 **未** grounded 时介入；本例 intent 含 'my_dut'
        让 LLM 值通过 grounding check，确认 FIX-2 守卫不会把合法 grounded 值也丢掉。

    与新增的 test_map_params_grounded_llm_value_kept_even_with_default 测同一个不变量
    （grounded+has default → source=llm），保留作为 FIX-1 trivial 路径的命名回归锚点；
    若后续合并两条测试，请同步保留对 _TRIVIAL_LLM_VALUES 不误伤的覆盖。
    """
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "default": "dut", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(original_intent="my_dut 模块的握手稳定性断言"),
        regex_mapping={},
        llm_mapping={"module_name": "my_dut"},
    )
    assert result["module_name"]["value"] == "my_dut"
    assert result["module_name"]["source"] == "llm"


def test_map_params_trivial_llm_value_whitespace_and_case_normalized():
    """LLM 返 '  UNKNOWN  '（大写 + 前后空格）也应被识别为 trivial，走 default。

    覆盖 .strip().lower() 归一化路径——LLM 真实输出常带多余空白/大小写，
    若守卫只匹配字面 'unknown' 会漏掉这类变体。
    """
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "default": "dut", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(),
        regex_mapping={},
        llm_mapping={"module_name": "  UNKNOWN  "},
    )
    assert result["module_name"]["value"] == "dut"
    assert result["module_name"]["source"] == "default"


# ── FIX-2: ungrounded-LLM-value + has-default → defer to default ───────
#
# step 1 第二道守卫的判定矩阵：
#   trivial?     yes → 跳过（FIX-1 已覆盖）
#   non-trivial:
#     has default? │ grounded?  →  expected behavior
#         no      │    n/a      →  保留 source=llm（让 _detect_under_specified 兜底）
#         yes     │   no        →  跳过 _set，让 step 4 default 接管
#         yes     │   yes (intent) → 保留 source=llm
#         yes     │   yes (form)   → 保留 source=llm（form_values grounding 等同）


def test_map_params_ungrounded_llm_value_with_default_falls_through():
    """非 trivial 但 ungrounded 的 LLM 值 + 模板有 default → 守卫跳过 → default 接管。

    复现真实 case：FSM 断言场景 LLM step2 给 module_name='top'，原文里没有 'top'、
    form 字段（clk/rst/rst_polarity + signals）里也没有。原实现把 'top' 锁死
    source=llm，下游 _detect_under_specified grounding check 再把它打成低置信源 →
    422 把用户赶进 IntentBuilder（即使模板已经给了 default='dut'）。
    本守卫识别这种 "LLM 善意编造" → 跳过 _set，让 default 接管。
    """
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "default": "dut", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(original_intent="FSM 状态转换断言：从 IDLE 到 ACTIVE"),
        regex_mapping={},
        llm_mapping={"module_name": "top"},
    )
    assert result["module_name"]["value"] == "dut"
    assert result["module_name"]["source"] == "default"


def test_map_params_ungrounded_llm_value_without_default_kept_for_under_specified_gate():
    """非 trivial 但 ungrounded 的 LLM 值 + 模板**无** default → 保留 source=llm。

    没有 default 兜底时，让 LLM 值占位是有意为之：
      - 前端能在 ConfirmationPanel 显示具体出错值（"模型猜的 'fabricated_sig'"）
      - _detect_under_specified 用 grounding check 把它判低置信源 → 422 → IntentBuilder
    本守卫只在 "has default" 时才介入，避免吞掉用户必须填的参数的诊断信息。
    """
    template = _FakeTemplate([
        # 注意：没有 default 字段
        {"name": "signal", "required": True, "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(original_intent="覆盖率统计四个状态"),
        regex_mapping={},
        llm_mapping={"signal": "fabricated_sig"},
    )
    assert result["signal"]["value"] == "fabricated_sig"
    assert result["signal"]["source"] == "llm"


def test_map_params_grounded_llm_value_kept_even_with_default():
    """LLM 值在原文里出现 + 模板有 default → 守卫不跳过，LLM 值优先于 default。

    防止 FIX-2 守卫过度激进：用户在原文里明说了 "my_dut 模块"，LLM 正确抽出
    module_name='my_dut'，此时应保留 LLM 值，不能被 default='dut' 覆盖。
    grounding 判定复用 _llm_value_grounded_in_intent。
    """
    template = _FakeTemplate([
        {"name": "module_name", "required": True, "default": "dut", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(original_intent="my_dut 模块的 FSM 状态转换断言"),
        regex_mapping={},
        llm_mapping={"module_name": "my_dut"},
    )
    assert result["module_name"]["value"] == "my_dut"
    assert result["module_name"]["source"] == "llm"


def test_map_params_llm_value_grounded_in_form_values_kept():
    """LLM 值在 form 字段里出现（clk/rst/rst_polarity + signals.name）+ 模板有 default
    → 守卫不跳过，LLM 值优先于 default。

    form_values 是用户通过 GenerateForm 显式提供的结构化值，被注入到 LLM system prompt
    作 signal_context，LLM 引用它们是合法 grounding。grounding 检查复用
    _llm_value_in_form_values，与 _detect_under_specified 同一标准（避免两层判定漂移）。

    本例：原文不含 'aclk'，但用户在表单填了 clk='aclk' → LLM 给 valid='aclk' 合法。
    """
    template = _FakeTemplate([
        {"name": "valid", "required": True, "default": "valid", "type": "string"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(
            clk="aclk",
            original_intent="握手稳定性断言",  # 原文不含 'aclk'
        ),
        regex_mapping={},
        llm_mapping={"valid": "aclk"},  # 命中 form_values 里的 clk='aclk'
    )
    assert result["valid"]["value"] == "aclk"
    assert result["valid"]["source"] == "llm"


def test_map_params_group_name_ungrounded_llm_value_falls_to_yaml_default():
    """coverage 模板：LLM 给 group_name='cov_group'（原文/form 都没这词）+ 模板有 default
    → 守卫跳过，YAML default 接管。

    与 _module_name_ 路径对称的 group_name 路径单测——确保 4 个 coverage 模板
    （value/cross/transition/protocol_handshake）的 default 在生产路径都能被 step 4 拿到。
    本测试同时模拟"LLM 编造 group_name"和"用户没提供 group_name"两种情况的合流。
    """
    template = _FakeTemplate([
        {"name": "group_name", "required": True, "default": "value",
         "type": "string", "description": "覆盖率组名"},
    ])
    result = _map_params_with_source(
        template,
        _make_inp(original_intent="对状态信号 cur_state 做值覆盖率统计"),
        regex_mapping={},
        llm_mapping={"group_name": "cov_group"},  # 原文/form 都没这词
    )
    assert result["group_name"]["value"] == "value"
    assert result["group_name"]["source"] == "default"


@pytest.mark.parametrize("fname,expected_default,expected_covergroup,extra_params", [
    # 每行：(YAML 文件名, group_name 期望 default, 渲染后期望出现的完整 covergroup 声明字串, body 引用的额外参数)
    # extra_params 须包含 body 实际引用的所有变量，但 group_name 除外（已由
    # actual_default 单独注入）。Jinja2 不读 YAML parameter defaults——所有 body
    # 引用的变量（含 YAML default 的）都必须显式在 params 里出现，否则
    # StrictUndefined 会 raise。
    (
        "value_coverage.yaml", "value", "covergroup cg_value_value",
        {"clk": "clk", "signal": "sig", "bins_expr": "{[0:15]}"},
    ),
    (
        "cross_coverage.yaml", "cross", "covergroup cg_cross_cross",
        {"clk": "clk", "signal_a": "sa", "signal_b": "sb",
         "bins_a": "{[0:3]}", "bins_b": "{0, 1}"},
    ),
    (
        "transition_coverage.yaml", "transition", "covergroup cg_transition_transition",
        {"clk": "clk", "signal": "state_sig", "state_list": "IDLE, ACTIVE, DONE"},
    ),
    (
        "protocol_handshake_coverage.yaml", "protocol_handshake",
        "covergroup cg_protocol_handshake_handshake",
        {"clk": "clk", "valid": "v", "ready": "r"},
    ),
])
def test_coverage_template_renders_default_without_double_prefix(
    fname, expected_default, expected_covergroup, extra_params,
):
    """端到端契约：4 个 coverage 模板用 YAML default 渲染时，产出的 SV covergroup
    名字**只带一个 `cg_` 前缀**，不出现 `cg_cg_*_value` 这种重复前缀。

    回归保护：模板 body 都是 `covergroup cg_{{ group_name }}_<suffix> ...` 结构，
    若 YAML 把 default 写成 `cg_<x>`（前缀重复），渲染结果会变成
    `cg_cg_<x>_<suffix>`——能编译但语义冗余。本测试读真实 YAML default 并 Jinja
    渲染，断言：(1) 渲染输出**不**含 `cg_cg_`，(2) 完整的 `covergroup cg_<default>_<suffix>`
    声明字串确实出现。

    assertion (2) 同时锁住 default 与 body 后缀这对契约——任一侧改动而不同步另一侧
    （例如把 body 改成 `cg_{{ group_name }}` 去掉 `_value` 后缀）也会被本测试挡住。
    """
    import yaml
    from pathlib import Path
    from app.services.core.renderer import render_template

    yaml_path = Path(__file__).resolve().parent.parent / "template_library/coverage" / fname
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    group_name_param = next(p for p in data["parameters"] if p["name"] == "group_name")
    actual_default = group_name_param["default"]
    # 锁住 YAML default 本身——防 default 被改 cg_ 前缀重新引入但 parametrize 漏改
    assert actual_default == expected_default, \
        f"{fname}: YAML default={actual_default!r} 与测试参数 {expected_default!r} 不一致"

    params = {"group_name": actual_default, **extra_params}
    rendered = render_template(data["template_body"], params, data["id"], data["version"])

    # 关键断言 (1)：标识符**不**包含双重 cg_ 前缀
    assert "cg_cg_" not in rendered, \
        f"{fname}: 双重 cg_ 前缀（YAML default 多了 cg_）：渲染片段=\n{rendered[:600]}"
    # 关键断言 (2)：完整 covergroup 声明字串出现——锁 default + body 后缀的契约
    assert expected_covergroup in rendered, \
        f"{fname}: 期望渲染含 {expected_covergroup!r}，渲染片段=\n{rendered[:600]}"


# ── _values_only 单测 ──────────────────────────────────────────────────

def test_values_only_strips_metadata():
    """_values_only 应把 {name: {value, source, ...}} 转成 {name: value}。"""
    params = {
        "module_name": {"value": "reg_block", "source": "regex", "required": True, "description": "", "type": "string"},
        "enable": {"value": "wr_en", "source": "signal_list", "required": True, "description": "", "type": "string"},
    }
    assert _values_only(params) == {"module_name": "reg_block", "enable": "wr_en"}


# ── pipeline_render 集成测试（mock cache + render）─────────────────────

@pytest.mark.asyncio
async def test_pipeline_render_cache_hit():
    """generation_cache 命中 → 直接返回 (cached_code, True)，不调 Jinja2。"""
    fake_template = MagicMock()
    fake_template.template_body = "// stub"
    fake_template.id = "tmpl_x"
    fake_template.version = "1.0.0"

    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_template)

    with patch("app.services.core.pipeline.get_generation_cache",
               new=AsyncMock(return_value="// cached code")), \
         patch("app.services.core.pipeline.get_default_llm_config_id",
               new=AsyncMock(return_value="cfg_test")):
        req = RenderInput(
            template_id="tmpl_x",
            template_version="1.0.0",
            params={"x": "y"},
        )
        code, cache_hit = await pipeline_render(req, fake_db)

    assert code == "// cached code"
    assert cache_hit is True


@pytest.mark.asyncio
async def test_pipeline_render_cache_miss_renders_and_writes():
    """缓存未命中 → 调 render_template + set_generation_cache + save_history（若有 intent_hash）。"""
    fake_template = MagicMock()
    fake_template.template_body = "module {{ name }}; endmodule"
    fake_template.id = "tmpl_x"
    fake_template.version = "1.0.0"

    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_template)

    set_cache_mock = AsyncMock()
    save_hist_mock = AsyncMock()

    with patch("app.services.core.pipeline.get_generation_cache", new=AsyncMock(return_value=None)), \
         patch("app.services.core.pipeline.set_generation_cache", new=set_cache_mock), \
         patch("app.services.core.pipeline.save_history", new=save_hist_mock), \
         patch("app.services.core.pipeline.get_default_llm_config_id",
               new=AsyncMock(return_value="cfg_test")), \
         patch("app.services.core.pipeline.render_template", return_value="module foo; endmodule"):
        req = RenderInput(
            template_id="tmpl_x",
            template_version="1.0.0",
            params={"name": "foo"},
            intent_hash="abc123",
            confidence=0.9,
            normalized_intent="some normalized text",
        )
        code, cache_hit = await pipeline_render(req, fake_db)

    assert code == "module foo; endmodule"
    assert cache_hit is False
    set_cache_mock.assert_awaited_once()
    save_hist_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_render_no_intent_hash_skips_save_history():
    """intent_hash=None（legacy 重渲染路径）→ 不调 save_history。"""
    fake_template = MagicMock()
    fake_template.template_body = "// stub"
    fake_template.id = "tmpl_x"
    fake_template.version = "1.0.0"

    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_template)

    save_hist_mock = AsyncMock()

    with patch("app.services.core.pipeline.get_generation_cache", new=AsyncMock(return_value=None)), \
         patch("app.services.core.pipeline.set_generation_cache", new=AsyncMock()), \
         patch("app.services.core.pipeline.save_history", new=save_hist_mock), \
         patch("app.services.core.pipeline.get_default_llm_config_id",
               new=AsyncMock(return_value="cfg_test")), \
         patch("app.services.core.pipeline.render_template", return_value="// rendered"):
        req = RenderInput(
            template_id="tmpl_x",
            template_version="1.0.0",
            params={"x": "y"},
            intent_hash=None,
        )
        code, cache_hit = await pipeline_render(req, fake_db)

    assert code == "// rendered"
    save_hist_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_render_template_not_found_raises():
    """template_id 不存在 → ValueError。"""
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=None)

    req = RenderInput(template_id="nonexistent", template_version="1.0.0", params={})
    with pytest.raises(ValueError, match="模板不存在"):
        await pipeline_render(req, fake_db)


# ── pipeline_preview 双信号合议闸单测 ────────────────────────────────

def _make_rag_candidate(template_id: str, score: float, parameters=None):
    """构造 rag_retrieve 返回结构：每条 candidate 含 template_id/name/description/score/template。"""
    fake_template = MagicMock()
    fake_template.parameters = parameters or []
    fake_template.id = template_id
    fake_template.name = f"Template {template_id}"
    fake_template.version = "1.0.0"
    return {
        "template_id": template_id,
        "name": f"Template {template_id}",
        "description": f"desc-{template_id}",
        "score": score,
        "template": fake_template,
    }


def _make_preview_inp(text: str = "some user input"):
    """默认 intent='some user input'。需要 grounding check 通过的测试传具体原文，
    确保 LLM mock 返回的 value 能在原文中 substring/token 命中。"""
    return PipelineInput(
        original_intent=text,
        code_type="assertion",
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=[],
    )


def _patch_preview_deps(rag_candidates, llm_selection, db_get_return_value=None, dense_score=0.9):
    """统一 patch pipeline_preview 上游。

    dense_score 默认 0.9（高于阈值），off-topic 闸不触发；
    需要测 off-topic 行为时传低值（< 0.44）。
    """
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score",
        new=AsyncMock(return_value=dense_score),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized text", "hash_abc")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history",
        new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve",
        new=AsyncMock(return_value=rag_candidates),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement",
        new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_selection)
    # A8：pipeline 会在 step1 选中后调 await llm.verify_step1_selection；
    # 默认返 True（"通过验证"），由测试按需 override 这一字段成 AsyncMock(return_value=False)
    # 来覆盖 A8 否定分支。否则 MagicMock 默认子属性不是 awaitable，会 TypeError。
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=db_get_return_value)
    return stack, fake_db


@pytest.mark.asyncio
async def test_pipeline_preview_off_topic_dense_threshold_early_returns():
    """全库 best_overall < threshold → 在 normalize/RAG/LLM 之前就早返 OffTopicIntentError。

    校准结果决定 threshold=0.44；mock dense=0.30 < 0.44，应当抛 OffTopicIntentError。
    FEAT-15：`top_dense_score` 现在传 `best_overall = max(selected, max(other))`，
    本测试用 `_patch_preview_deps` 的均匀 mock，每个 code_type 都返 0.30 → best_overall
    退化为 0.30，断言仍成立。若改用非均匀 mock（如 `_patch_dense_per_code_type`），
    `top_dense_score` 会变成所有 code_type 中的最大值。
    detector="rag_dense_threshold"，携带 top_dense_score 和 threshold 给前端 Modal。
    """
    rag = [_make_rag_candidate("any_id", score=0.9)]
    llm_sel = TemplateSelectionOutput(template_id="any_id", param_mapping={}, confidence=0.9)
    stack, fake_db = _patch_preview_deps(rag, llm_sel, dense_score=0.30)
    with stack, pytest.raises(OffTopicIntentError) as excinfo:
        await pipeline_preview(_make_preview_inp(), fake_db)

    assert excinfo.value.detector == "rag_dense_threshold"
    # uniform mock 下 best_overall == selected_dense == 0.30
    assert excinfo.value.top_dense_score == 0.30
    assert excinfo.value.threshold == 0.44  # 跟 config.py 默认一致


@pytest.mark.asyncio
async def test_pipeline_preview_marginal_intent_falls_back_with_llm_confidence():
    """LLM step1 没选出 template（marginal 真请求）→ 走 rag_fallback；
    且 confidence 保留 LLM 上报的 0.0，不再被 RAG cross-encoder 分数覆盖。

    这是真 IC 请求但表述简略的常见路径。即便 RAG top1 分数较低（如 0.7），
    也不应当被拒——这是 normalize_intent 信任路径（sentinel 没触发）。
    FIX-9 后第五道闸默认会拦截 rag_fallback；本测试关注 confidence 透传逻辑，
    需临时关闸 no_match_gate_enabled 以隔离测试目标。
    """
    from app.core.config import get_settings

    rag = [
        _make_rag_candidate("sva_handshake_timeout_v1", score=0.7),
        _make_rag_candidate("sva_data_integrity_v1", score=0.3),
    ]
    llm_refused = TemplateSelectionOutput(template_id="", param_mapping={}, confidence=0.0)

    fake_db_template = MagicMock()
    fake_db_template.parameters = []
    fake_db_template.id = "sva_handshake_timeout_v1"
    fake_db_template.name = "Template sva_handshake_timeout_v1"
    fake_db_template.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_refused, db_get_return_value=fake_db_template)
    settings = get_settings()
    original = settings.no_match_gate_enabled
    settings.no_match_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(_make_preview_inp(), fake_db)

        assert result.template_id == "sva_handshake_timeout_v1"
        assert result.confidence_source == "rag_fallback"
        # 关键断言：confidence 是 LLM 上报的 0.0，不再被 RAG 0.95 覆盖
        assert result.confidence == 0.0
    finally:
        settings.no_match_gate_enabled = original


@pytest.mark.asyncio
async def test_pipeline_preview_off_topic_gate_disabled_skips_check():
    """offtopic_gate_enabled=False → 即使 dense 分数低于阈值，也跳过闸继续走老路径。
    紧急逃生通道：若阈值校准误调或语料缺失导致大面积误拒，可立即关闸。
    FIX-9 后第五道闸只看 confidence_source==rag_fallback，本测试构造的 llm_refused
    会触发它；测试目标是 off-topic 闸开关，故同步临时关闭 no_match 闸隔离测试目标。
    """
    fake_db_template = MagicMock()
    fake_db_template.parameters = []
    fake_db_template.id = "sva_data_integrity_v1"
    fake_db_template.name = "Template sva_data_integrity_v1"
    fake_db_template.version = "1.0.0"
    rag = [_make_rag_candidate("sva_data_integrity_v1", score=0.70)]
    llm_refused = TemplateSelectionOutput(template_id="", param_mapping={}, confidence=0.0)

    from app.core.config import get_settings
    settings = get_settings()
    original_offtopic = settings.offtopic_gate_enabled
    original_no_match = settings.no_match_gate_enabled
    settings.offtopic_gate_enabled = False
    settings.no_match_gate_enabled = False
    try:
        # dense=0.10 远低于阈值，但闸关掉 → 不应抛异常
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch(
            "app.services.core.pipeline.dense_top1_score",
            new=AsyncMock(return_value=0.10),
        ))
        stack.enter_context(patch(
            "app.services.core.pipeline.normalize_intent",
            new=AsyncMock(return_value=("normalized text", "hash_abc")),
        ))
        stack.enter_context(patch(
            "app.services.core.pipeline.lookup_history",
            new=AsyncMock(return_value=None),
        ))
        stack.enter_context(patch(
            "app.services.core.pipeline.rag_retrieve",
            new=AsyncMock(return_value=rag),
        ))
        stack.enter_context(patch(
            "app.services.core.pipeline._keyword_supplement",
            new=AsyncMock(return_value=[]),
        ))
        fake_llm = MagicMock()
        fake_llm.select_template = AsyncMock(return_value=llm_refused)
        fake_llm.verify_step1_selection = AsyncMock(return_value=True)
        stack.enter_context(patch(
            "app.services.core.pipeline.get_default_llm_client",
            new=AsyncMock(return_value=fake_llm),
        ))
        fake_db = MagicMock()
        fake_db.get = AsyncMock(return_value=fake_db_template)
        with stack:
            result = await pipeline_preview(_make_preview_inp(), fake_db)
        assert result.template_id == "sva_data_integrity_v1"
        assert result.confidence_source == "rag_fallback"
    finally:
        settings.offtopic_gate_enabled = original_offtopic
        settings.no_match_gate_enabled = original_no_match


@pytest.mark.asyncio
async def test_pipeline_preview_offtopic_short_circuits_normalize_and_rag():
    """跑题闸触发时必须早返：normalize / rag / llm 都不能被调到。

    防止后续重构无意中把 dense gate 移到 normalize 之后，浪费 GLM-4.7 thinking 20s。
    """
    from contextlib import ExitStack
    stack = ExitStack()
    dense_mock = AsyncMock(return_value=0.10)
    normalize_mock = AsyncMock(return_value=("should not reach here", "hash"))
    rag_mock = AsyncMock(return_value=[])
    llm_factory_mock = AsyncMock()

    stack.enter_context(patch("app.services.core.pipeline.dense_top1_score", new=dense_mock))
    stack.enter_context(patch("app.services.core.pipeline.normalize_intent", new=normalize_mock))
    stack.enter_context(patch("app.services.core.pipeline.rag_retrieve", new=rag_mock))
    stack.enter_context(patch("app.services.core.pipeline.get_default_llm_client", new=llm_factory_mock))

    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=None)

    with stack, pytest.raises(OffTopicIntentError):
        await pipeline_preview(_make_preview_inp(), fake_db)

    # FEAT-15：off-topic 闸现在同时算 selected + 每个非选中 code_type 的 dense top1
    # （共享给 code_type_mismatch 闸）。调用次数 = registered code_type 数。
    # 关键不变量：normalize / rag / llm 仍然零调用——闸触发前的早返契约。
    assert dense_mock.await_count >= 1
    normalize_mock.assert_not_awaited()
    rag_mock.assert_not_awaited()
    llm_factory_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_preview_is_deterministic_for_same_input():
    """两次调用相同输入必须得到相同 template_id 和 params（确定性契约）。

    禁掉 step1 thinking 后理论上仍 deterministic（temperature=0），本测试用 mock
    LLM 锁死契约：相同 input → 相同 select_template 返回 → 相同 PreviewResult。
    """
    rag = [_make_rag_candidate("sva_handshake_timeout_v1", score=0.85)]
    selection = TemplateSelectionOutput(
        template_id="sva_handshake_timeout_v1",
        param_mapping={"signal": "valid"},
        confidence=0.9,
    )

    fake_db_template = MagicMock()
    fake_db_template.parameters = []
    fake_db_template.id = "sva_handshake_timeout_v1"
    fake_db_template.name = "Template sva_handshake_timeout_v1"
    fake_db_template.version = "1.0.0"

    inp = _make_preview_inp()

    results = []
    for _ in range(2):
        stack, fake_db = _patch_preview_deps(rag, selection, db_get_return_value=fake_db_template)
        with stack:
            results.append(await pipeline_preview(inp, fake_db))

    assert results[0].template_id == results[1].template_id
    assert results[0].template_version == results[1].template_version
    assert results[0].confidence_source == results[1].confidence_source
    assert _values_only_from_preview(results[0]) == _values_only_from_preview(results[1])


def _values_only_from_preview(result) -> dict:
    """提取 params dict 的 value-only 视图，便于比较确定性契约。"""
    return {name: meta["value"] for name, meta in result.params.items()}


# ── keyword_supplement fallback 路径（RAG 返空时由 DB keywords 兜底）────────

@pytest.mark.asyncio
async def test_pipeline_preview_keyword_supplement_fills_when_rag_empty():
    """RAG 三阶段返空 → _keyword_supplement 命中 → 候选注入 LLM step1。

    若不命中、不补充，pipeline 会 raise EmptyRetrievalError。这里 mock 补充返回
    一条候选，验证 LLM 拿到了非空候选列表并被选中。
    """
    from contextlib import ExitStack
    stack = ExitStack()
    supplement_hit = _make_rag_candidate("sva_handshake_keyword_supplement_v1", score=0.6)
    llm_pick = TemplateSelectionOutput(
        template_id="sva_handshake_keyword_supplement_v1",
        param_mapping={"signal": "valid"},
        confidence=0.85,
    )

    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score", new=AsyncMock(return_value=0.9),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "hash_supp")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    # 关键：RAG 三阶段返空
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=[]),
    ))
    # 关键：keyword 补充非空
    supplement_mock = AsyncMock(return_value=[supplement_hit])
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=supplement_mock,
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_pick)
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "sva_handshake_keyword_supplement_v1"
    fake_tmpl.name = "Template sva_handshake_keyword_supplement_v1"
    fake_tmpl.version = "1.0.0"
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    with stack:
        result = await pipeline_preview(_make_preview_inp(), fake_db)

    supplement_mock.assert_awaited_once()
    assert result.template_id == "sva_handshake_keyword_supplement_v1"
    # LLM 选中的是 keyword 补充注入的候选（RAG 三阶段未召回）→ confidence_source
    # 应标为 keyword_supplement，让前端 / 日志区分这条 fallback 路径。
    assert result.confidence_source == "keyword_supplement"
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_pipeline_preview_rag_empty_and_no_supplement_raises_empty_retrieval():
    """RAG 返空且 keyword 补充也返空 → EmptyRetrievalError（不是 OffTopicIntentError，
    也不是 ValueError）。前端应当能区分这两种 422 / 503 路径。"""
    from app.services.core.pipeline import EmptyRetrievalError
    from contextlib import ExitStack
    stack = ExitStack()

    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score", new=AsyncMock(return_value=0.9),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "hash_e")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=[]),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock()
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))

    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=None)

    with stack, pytest.raises(EmptyRetrievalError) as excinfo:
        await pipeline_preview(_make_preview_inp(), fake_db)

    assert excinfo.value.code_type == "assertion"
    # LLM 不应被调到（连候选列表都凑不齐）
    fake_llm.select_template.assert_not_awaited()


# ── intent_cache 命中路径 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_preview_intent_cache_hit_returns_quick_render():
    """intent_hash 命中、fingerprint 匹配 → 直接 quick_render=True，
    跳过 RAG / keyword / LLM 全链路。"""
    from contextlib import ExitStack
    from app.services.intent.history import template_params_fingerprint

    template_params = [
        {"name": "signal", "required": True, "expr_type": "sv_identifier"},
    ]
    fp = template_params_fingerprint(template_params)

    stack = ExitStack()
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score", new=AsyncMock(return_value=0.9),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized cache hit", "hash_cache")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history",
        new=AsyncMock(return_value={
            "template_id": "sva_handshake_v1",
            "version": "1.0.0",
            "param_mapping": {"signal": "valid"},
            "confidence": 0.92,
            "params_fingerprint": fp,
        }),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.get_generation_cache",
        new=AsyncMock(return_value="// cached SV code"),
    ))
    rag_mock = AsyncMock(return_value=[])
    stack.enter_context(patch("app.services.core.pipeline.rag_retrieve", new=rag_mock))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock()
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = template_params
    fake_tmpl.id = "sva_handshake_v1"
    fake_tmpl.name = "SVA Handshake"
    fake_tmpl.version = "1.0.0"
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    with stack:
        result = await pipeline_preview(_make_preview_inp(), fake_db)

    assert result.quick_render is True
    assert result.confidence_source == "intent_cache"
    assert result.template_id == "sva_handshake_v1"
    # 关键：RAG / LLM 都没被调用
    rag_mock.assert_not_awaited()
    fake_llm.select_template.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_preview_intent_cache_schema_drift_bypasses_cache():
    """intent_hash 命中但 params_fingerprint 不匹配（模板被编辑过）→
    bypass 缓存，走 RAG / LLM 完整路径。防止用旧 mapping 渲染编辑过的模板。"""
    from contextlib import ExitStack

    # 缓存写入时模板只有 signal 一个参数；现在模板新增了 required state_list。
    cached_fingerprint = "stale_fp_does_not_match_current_schema_1234"

    stack = ExitStack()
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score", new=AsyncMock(return_value=0.9),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized drift", "hash_drift")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history",
        new=AsyncMock(return_value={
            "template_id": "sva_fsm_v1",
            "version": "1.0.0",
            "param_mapping": {"signal": "valid"},  # 缺 state_list
            "confidence": 0.9,
            "params_fingerprint": cached_fingerprint,
        }),
    ))
    rag_mock = AsyncMock(return_value=[_make_rag_candidate("sva_fsm_v1", score=0.85)])
    stack.enter_context(patch("app.services.core.pipeline.rag_retrieve", new=rag_mock))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=TemplateSelectionOutput(
        template_id="sva_fsm_v1",
        param_mapping={"signal": "valid", "state_list": "IDLE,RUN"},
        confidence=0.9,
    ))
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))

    # 当前模板含两个 required 参数 → fingerprint 与 cached_fingerprint 必不等
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "signal", "required": True, "expr_type": "sv_identifier"},
        {"name": "state_list", "required": True, "expr_type": "free_text"},
    ]
    fake_tmpl.id = "sva_fsm_v1"
    fake_tmpl.name = "FSM template"
    fake_tmpl.version = "1.0.0"
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    with stack:
        result = await pipeline_preview(
            _make_preview_inp("信号 valid 状态 IDLE RUN"), fake_db,
        )

    # 关键：走了 RAG / LLM 完整路径——既未命中 intent_cache，RAG/LLM 都被实际调用。
    # 注：FEAT-11 之后高置信 RAG 也可能令 quick_render=True，那是正确行为
    # （与 intent_cache 短路不同源）。
    assert result.confidence_source != "intent_cache"
    rag_mock.assert_awaited_once()
    fake_llm.select_template.assert_awaited_once()


# ── validation_error 端到端透传 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_preview_propagates_validation_error_to_params_meta():
    """LLM 返回非法 sv_boolean_expr（含双 &&）→ pipeline_preview 在每个 param 的 meta
    上挂 validation_error，PreviewResponse 通过 ParamWithSource 透传到 JSON。

    保护契约：前端从 `params[name].validation_error` 读取错误描述渲染红色提示。
    若 pipeline 重构把这个字段丢了，本测试立刻报警。
    """
    rag = [_make_rag_candidate("sva_property_v1", score=0.85,
                                parameters=[
                                    {"name": "condition", "type": "string",
                                     "required": True, "expr_type": "sv_boolean_expr"},
                                ])]
    llm_pick = TemplateSelectionOutput(
        template_id="sva_property_v1",
        param_mapping={"condition": "awvalid && && ready"},  # 非法：双 &&
        confidence=0.9,
    )

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "condition", "type": "string", "required": True,
         "expr_type": "sv_boolean_expr"},
    ]
    fake_tmpl.id = "sva_property_v1"
    fake_tmpl.name = "SVA Property"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_pick, db_get_return_value=fake_tmpl)
    with stack:
        # intent 含 awvalid + ready 让 grounding check 放过这两个 token；
        # validation_error 是 expr_validator 的功能，本测试只关心错误是否被透传。
        result = await pipeline_preview(
            _make_preview_inp("awvalid && && ready 表达式校验测试"), fake_db,
        )

    cond_meta = result.params["condition"]
    # 值不动（validator 不修改值）
    assert cond_meta["value"] == "awvalid && && ready"
    # 关键：validation_error 字段被填充
    assert cond_meta.get("validation_error"), \
        f"expected validation_error to be set, got meta={cond_meta}"
    # 字段会以 ParamWithSource(**meta) 形式序列化进 /preview JSON 响应。

    # 验证 Pydantic schema 能接受 meta dict
    from app.schemas.generate import ParamWithSource
    pwa = ParamWithSource(**cond_meta)
    assert pwa.validation_error == cond_meta["validation_error"]


# ── code_type 一致性闸 ───────────────────────────────────────────────────

def _patch_dense_per_code_type(stack, scores: dict[str, float]):
    """让 dense_top1_score 按 code_type 返不同分数，测试跨类比较逻辑。

    scores: {"assertion": 0.62, "coverage": 0.76} → 调用时按 code_type kwarg 查表，
    未列出的类型默认 0.0。
    """
    async def fake(query_text, code_type=None):
        return scores.get(code_type, 0.0)
    stack.enter_context(patch("app.services.core.pipeline.dense_top1_score", new=fake))


@pytest.mark.asyncio
async def test_pipeline_preview_code_type_mismatch_raises_with_suggestion():
    """选 assertion 但 coverage 库 dense 显著更高（≥margin=0.10）→ CodeTypeMismatchError。

    复现 case："统计 valid-ready 四种握手场景的覆盖率" + code_type=assertion，
    coverage 库 0.76 vs assertion 库 0.62，gap=0.14 > 0.10。
    """
    from contextlib import ExitStack
    stack = ExitStack()
    _patch_dense_per_code_type(stack, {"assertion": 0.62, "coverage": 0.76})

    with stack, pytest.raises(CodeTypeMismatchError) as excinfo:
        await pipeline_preview(_make_preview_inp(), MagicMock())

    e = excinfo.value
    assert e.selected_code_type == "assertion"
    assert e.suggested_code_type == "coverage"
    assert abs(e.selected_score - 0.62) < 1e-6
    assert abs(e.suggested_score - 0.76) < 1e-6
    assert e.detector == "rag_dense_cross_code_type"


@pytest.mark.asyncio
async def test_pipeline_preview_code_type_match_passes():
    """选 assertion 且 assertion 库 dense 高于 coverage（或差距 < margin）→ 不抛，正常走流水线。

    防止误伤："用 SVA 断言 valid-ready 握手稳定性"这种 assertion 正例不应触发 mismatch。
    """
    from contextlib import ExitStack
    stack = ExitStack()
    _patch_dense_per_code_type(stack, {"assertion": 0.85, "coverage": 0.50})
    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.85)]
    llm_pick = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={"valid": "v"}, confidence=0.9,
    )
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "h_match")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=rag),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_pick)
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "sva_handshake_stable_v1"
    fake_tmpl.name = "stable"
    fake_tmpl.version = "1.0.0"
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    with stack:
        result = await pipeline_preview(_make_preview_inp(), fake_db)
    assert result.template_id == "sva_handshake_stable_v1"


@pytest.mark.asyncio
async def test_pipeline_preview_code_type_borderline_under_margin_passes():
    """coverage 比 assertion 高，但差距 < margin（0.10）→ 不抛。margin 防误伤的边界。"""
    from contextlib import ExitStack
    stack = ExitStack()
    # gap = 0.06 < 0.10
    _patch_dense_per_code_type(stack, {"assertion": 0.70, "coverage": 0.76})
    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.7)]
    llm_pick = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={"valid": "v"}, confidence=0.8,
    )
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "h_border")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=rag),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_pick)
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "sva_handshake_stable_v1"
    fake_tmpl.name = "stable"
    fake_tmpl.version = "1.0.0"
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    with stack:
        result = await pipeline_preview(_make_preview_inp(), fake_db)
    # 没抛 mismatch、正常返
    assert result.template_id == "sva_handshake_stable_v1"


@pytest.mark.asyncio
async def test_pipeline_preview_code_type_gate_disabled_skips_check():
    """code_type_mismatch_gate_enabled=False → 即使分数差距巨大也不抛。逃生通道。"""
    from contextlib import ExitStack
    from app.core.config import get_settings
    stack = ExitStack()
    _patch_dense_per_code_type(stack, {"assertion": 0.62, "coverage": 0.76})
    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.62)]
    llm_pick = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={}, confidence=0.6,
    )
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "h_off")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=rag),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_pick)
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "sva_handshake_stable_v1"
    fake_tmpl.name = "stable"
    fake_tmpl.version = "1.0.0"
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    settings = get_settings()
    original = settings.code_type_mismatch_gate_enabled
    settings.code_type_mismatch_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(_make_preview_inp(), fake_db)
        assert result.template_id == "sva_handshake_stable_v1"
    finally:
        settings.code_type_mismatch_gate_enabled = original


# ── under_specified 闸（契约反转 v2.11）───────────────────────────────────

# _detect_under_specified 纯函数单测——不经过 pipeline，直接测判定规则

def test_detect_under_specified_placeholder_required():
    """required + source=placeholder → 必拦"""
    params = {"signal": {"value": "signal", "source": "placeholder", "required": True}}
    defs = [{"name": "signal", "required": True, "description": "信号名"}]
    missing = _detect_under_specified(params, defs)
    assert [m["name"] for m in missing] == ["signal"]


def test_detect_under_specified_semantic_fallback_required():
    """required + source=semantic_fallback → 必拦（系统瞎猜）"""
    params = {"state_list": {"value": "IDLE, ACTIVE, DONE", "source": "semantic_fallback", "required": True}}
    defs = [{"name": "state_list", "required": True, "description": "状态列表"}]
    missing = _detect_under_specified(params, defs)
    assert [m["name"] for m in missing] == ["state_list"]
    assert missing[0]["description"] == "状态列表"


def test_detect_under_specified_llm_trivial_empty_string():
    """LLM 返空串 → 视为弃权 → 拦"""
    params = {"state_list": {"value": "", "source": "llm", "required": True}}
    defs = [{"name": "state_list", "required": True}]
    assert [m["name"] for m in _detect_under_specified(params, defs)] == ["state_list"]


def test_detect_under_specified_llm_trivial_zero():
    """LLM 返 0（int 或 '0'）→ 视为弃权 → 拦。修复 FSM signal_width=0 真实 bug"""
    for val in (0, "0"):
        params = {"signal_width": {"value": val, "source": "llm", "required": True}}
        defs = [{"name": "signal_width", "required": True}]
        assert [m["name"] for m in _detect_under_specified(params, defs)] == ["signal_width"]


def test_detect_under_specified_llm_returns_param_name_literal():
    """LLM 偷懒返字面参数名且原文中不含该词 → 视为弃权 → 拦（前提：模板默认不是该名字）。

    反例见 test_detect_under_specified_llm_returns_param_name_grounded_in_intent。
    """
    params = {"signal": {"value": "signal", "source": "llm", "required": True}}
    defs = [{"name": "signal", "required": True}]  # default 缺省 None
    # intent_text 里不含 "signal" 词 → 视为弃权 → 拦
    assert [m["name"] for m in _detect_under_specified(
        params, defs, intent_text="FSM 状态信号在 IDLE 时必须等待"
    )] == ["signal"]


def test_detect_under_specified_llm_returns_param_name_grounded_in_intent():
    """LLM 返字面参数名但该名字出现在用户原文里 → 合法信号名与参数名恰好相同 → 放过。

    真实场景：AXI 协议的 valid/ready 信号名与 cov_protocol_handshake_v1 模板参数名
    相同。用户输入"统计 valid-ready 握手成功、valid 等待、ready 预备三种场景的覆盖率"，
    LLM 正确把 valid='valid' / ready='ready'，不应触发 under_specified gate。
    """
    params = {
        "valid": {"value": "valid", "source": "llm", "required": True},
        "ready": {"value": "ready", "source": "llm", "required": True},
    }
    defs = [
        {"name": "valid", "required": True},   # no default
        {"name": "ready", "required": True},   # no default
    ]
    intent = "统计 valid-ready 握手成功、valid 等待、ready 预备三种场景的覆盖率"
    assert _detect_under_specified(params, defs, intent_text=intent) == []


def test_detect_under_specified_llm_returns_default_aware_name():
    """LLM 返字面参数名但等于模板 default → 是合法选用默认，不拦。

    防御误拦真实案例：clk/rst_n 这种约定名既是参数名也是默认值，LLM 返 'clk' 不该被视为弃权。
    """
    params = {"clk": {"value": "clk", "source": "llm", "required": True}}
    defs = [{"name": "clk", "required": True, "default": "clk"}]
    assert _detect_under_specified(params, defs) == []


def test_detect_under_specified_high_conf_sources_pass():
    """regex / signal_list / default / llm-with-real-value 全放过"""
    params = {
        "valid":  {"value": "awvalid", "source": "regex", "required": True},
        "ready":  {"value": "awready", "source": "signal_list", "required": True},
        "clk":    {"value": "aclk", "source": "default", "required": True},
        "module": {"value": "axi_dma", "source": "llm", "required": True},
    }
    defs = [
        {"name": "valid", "required": True}, {"name": "ready", "required": True},
        {"name": "clk", "required": True},   {"name": "module", "required": True},
    ]
    assert _detect_under_specified(params, defs) == []


def test_detect_under_specified_optional_param_not_blocked():
    """optional 参数 source=placeholder 也放过——只拦 required"""
    params = {"opt": {"value": "opt", "source": "placeholder", "required": False}}
    defs = [{"name": "opt", "required": False}]
    assert _detect_under_specified(params, defs) == []


def test_detect_under_specified_returns_missing_metadata():
    """missing 列表带 description / expr_type / role_hint metadata 供前端做提示语"""
    params = {
        "signal": {"value": "signal", "source": "placeholder", "required": True},
        "valid":  {"value": "awvalid", "source": "regex", "required": True},
    }
    defs = [
        {"name": "signal", "required": True, "description": "状态信号名",
         "expr_type": "sv_identifier", "role_hint": "state"},
        {"name": "valid", "required": True},
    ]
    missing = _detect_under_specified(params, defs)
    assert len(missing) == 1
    m = missing[0]
    assert m == {"name": "signal", "description": "状态信号名",
                 "expr_type": "sv_identifier", "role_hint": "state"}


# pipeline_preview 集成层测试

@pytest.mark.asyncio
async def test_pipeline_preview_under_specified_raises_with_missing_list():
    """FSM 覆盖率场景：选中 cov_transition_coverage_v1，LLM step2 返空 mapping →
    state_list / signal 等必填参数无高置信源 → 抛 UnderSpecifiedIntentError，
    detail 含完整 missing 列表。复现今日真实 FSM bug 场景。"""
    rag = [_make_rag_candidate("cov_transition_coverage_v1", score=1.0,
                                parameters=[
                                    {"name": "group_name", "required": True, "description": "覆盖率组名"},
                                    {"name": "signal", "required": True, "description": "状态信号名"},
                                    {"name": "state_list", "required": True, "description": "状态列表"},
                                ])]
    llm_empty = TemplateSelectionOutput(
        template_id="cov_transition_coverage_v1",
        param_mapping={},  # LLM 啥都没填出来
        confidence=0.9,
    )

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "group_name", "required": True, "description": "覆盖率组名"},
        {"name": "signal", "required": True, "description": "状态信号名"},
        {"name": "state_list", "required": True, "description": "状态列表"},
    ]
    fake_tmpl.id = "cov_transition_coverage_v1"
    fake_tmpl.name = "状态转换覆盖率组"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_empty, db_get_return_value=fake_tmpl)
    with stack, pytest.raises(UnderSpecifiedIntentError) as excinfo:
        await pipeline_preview(_make_preview_inp(), fake_db)

    e = excinfo.value
    assert e.template_id == "cov_transition_coverage_v1"
    assert e.template_name == "状态转换覆盖率组"
    names = {m["name"] for m in e.missing_params}
    # signal 走 semantic_fallback (inp.signals=[] 时不填) / state_list 走 semantic_fallback / group_name 走 semantic_fallback
    assert "state_list" in names
    assert "group_name" in names


@pytest.mark.asyncio
async def test_pipeline_preview_under_specified_gate_disabled_allows_placeholder():
    """UNDER_SPECIFIED_GATE_ENABLED=false → 退回旧"始终返代码"行为，让 placeholder 进入 PreviewResult。
    紧急逃生通道——线上误拦时一键关闸。"""
    from app.core.config import get_settings
    rag = [_make_rag_candidate("cov_transition_coverage_v1", score=1.0)]
    llm_empty = TemplateSelectionOutput(
        template_id="cov_transition_coverage_v1", param_mapping={}, confidence=0.9,
    )
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "signal", "required": True, "description": "信号"},
    ]
    fake_tmpl.id = "cov_transition_coverage_v1"
    fake_tmpl.name = "状态转换覆盖率组"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_empty, db_get_return_value=fake_tmpl)
    settings = get_settings()
    original = settings.under_specified_gate_enabled
    settings.under_specified_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(_make_preview_inp(), fake_db)
        assert result.template_id == "cov_transition_coverage_v1"
        # 闸关时 placeholder 进入 params 不抛异常
        assert result.params["signal"]["source"] == "placeholder"
    finally:
        settings.under_specified_gate_enabled = original


@pytest.mark.asyncio
async def test_pipeline_preview_under_specified_passes_when_all_params_high_conf():
    """所有 required 参数都有高置信源 → 闸开着也放行。回归保护。"""
    rag = [_make_rag_candidate("sva_handshake_timeout_v1", score=0.9)]
    llm_full = TemplateSelectionOutput(
        template_id="sva_handshake_timeout_v1",
        param_mapping={"module_name": "axi_dma", "valid": "awvalid", "ready": "awready"},
        confidence=0.9,
    )
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "module_name", "required": True},
        {"name": "valid", "required": True, "role_hint": "valid"},
        {"name": "ready", "required": True, "role_hint": "ready"},
        {"name": "clk", "required": True, "default": "clk"},
        {"name": "rst_n", "required": True, "default": "rst_n"},
    ]
    fake_tmpl.id = "sva_handshake_timeout_v1"
    fake_tmpl.name = "Valid-Ready握手超时检测断言"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_full, db_get_return_value=fake_tmpl)
    with stack:
        # intent 含 axi_dma / awvalid / awready 让 grounding check 放过
        result = await pipeline_preview(
            _make_preview_inp("axi_dma 模块 valid=awvalid ready=awready 握手超时断言"),
            fake_db,
        )
    assert result.template_id == "sva_handshake_timeout_v1"


@pytest.mark.asyncio
async def test_pipeline_preview_under_specified_llm_trivial_value_caught():
    """LLM 返 signal_width=0 / state_list='' 这种 trivial 值 → 仍被识别拦截。
    防止 LLM 假填充冒充高置信源。"""
    rag = [_make_rag_candidate("cov_transition_coverage_v1", score=1.0)]
    llm_trivial = TemplateSelectionOutput(
        template_id="cov_transition_coverage_v1",
        param_mapping={"signal_width": 0, "state_list": ""},
        confidence=0.9,
    )
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "signal_width", "required": True, "type": "integer"},
        {"name": "state_list", "required": True, "type": "string"},
    ]
    fake_tmpl.id = "cov_transition_coverage_v1"
    fake_tmpl.name = "状态转换覆盖率组"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_trivial, db_get_return_value=fake_tmpl)
    with stack, pytest.raises(UnderSpecifiedIntentError) as excinfo:
        await pipeline_preview(_make_preview_inp(), fake_db)
    names = {m["name"] for m in excinfo.value.missing_params}
    assert "signal_width" in names
    assert "state_list" in names


# ── FIX-1 §2 Acceptance Criteria（端到端 pipeline_preview mock 集成测试）──────
#
# 这两个测试逐字对应 .claude/plans/FIX-1.spec.md §2 AC1 / AC2：
#   AC1: 寄存器写保护 intent → PreviewResult.template_id == "sva_data_integrity_v1"，
#        不抛 UnderSpecifiedIntentError、不重定向 IntentBuilder
#   AC2: 同 intent 下 module_name → value="dut", source="default"
# 单元测试 (test_map_params_trivial_llm_value_falls_through_to_default 等) 已覆盖
# 内部函数行为；这两个把"happy path 端到端走通"锁进回归套。

def _make_data_integrity_template_mock():
    """构造 sva_data_integrity_v1 的 fake template，参数布局对齐生产 YAML。"""
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "module_name", "type": "string", "required": True,
         "description": "模块名", "default": "dut"},
        {"name": "clk", "type": "string", "required": True,
         "description": "时钟信号", "default": "clk"},
        {"name": "rst_n", "type": "string", "required": True,
         "description": "复位信号", "default": "rst_n"},
        {"name": "enable", "type": "string", "required": True,
         "description": "写使能信号名（高有效）", "role_hint": "enable"},
        {"name": "data", "type": "string", "required": True,
         "description": "被保护的数据信号名", "role_hint": "data"},
    ]
    fake_tmpl.id = "sva_data_integrity_v1"
    fake_tmpl.name = "数据完整性无损坏断言"
    fake_tmpl.version = "1.0.0"
    return fake_tmpl


@pytest.mark.asyncio
async def test_ac1_register_write_protect_intent_returns_data_integrity_template():
    """AC1：寄存器写保护 intent + module_name='unknown' 不应再触发 UnderSpecifiedIntentError。

    pre-FIX-1：step1 把 'unknown' 写成 source=llm 锁死 module_name 槽位，下游
    under_specified 闸把它拦下，PreviewResult 永远不返回。
    post-FIX-1：'unknown' 被 step1 守卫识别为 trivial 跳过，default='dut' 接管，
    流水线正常返回 PreviewResult(template_id='sva_data_integrity_v1')。
    """
    rag = [_make_rag_candidate("sva_data_integrity_v1", score=0.85)]
    # LLM step2 用 'unknown' 弃权 module_name；enable / data 由信号列表 grounding 通过
    llm_pick = TemplateSelectionOutput(
        template_id="sva_data_integrity_v1",
        param_mapping={"module_name": "unknown", "enable": "wr_en", "data": "data_in"},
        confidence=0.9,
    )
    fake_tmpl = _make_data_integrity_template_mock()

    inp = PipelineInput(
        original_intent="寄存器写保护场景：当写使能 wr_en 无效时，data_in 不会被意外修改",
        code_type="assertion",
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=[
            {"name": "wr_en", "width": 1, "role": "enable"},
            {"name": "data_in", "width": 32, "role": "data"},
        ],
    )

    stack, fake_db = _patch_preview_deps(rag, llm_pick, db_get_return_value=fake_tmpl)
    with stack:
        result = await pipeline_preview(inp, fake_db)

    assert result.template_id == "sva_data_integrity_v1"
    # 没抛 UnderSpecifiedIntentError —— 走到这里就意味着 redirect_to/IntentBuilder
    # 那条路没被触发。


@pytest.mark.asyncio
async def test_ac2_module_name_resolved_to_default_dut():
    """AC2：同 AC1 场景下，module_name 在 params_with_source 里应是 value='dut'、source='default'。

    这是 FIX-1 的核心契约：trivial LLM 值不堵塞 default 链路。
    """
    rag = [_make_rag_candidate("sva_data_integrity_v1", score=0.85)]
    llm_pick = TemplateSelectionOutput(
        template_id="sva_data_integrity_v1",
        param_mapping={"module_name": "unknown", "enable": "wr_en", "data": "data_in"},
        confidence=0.9,
    )
    fake_tmpl = _make_data_integrity_template_mock()

    inp = PipelineInput(
        original_intent="寄存器写保护场景：当写使能 wr_en 无效时，data_in 不会被意外修改",
        code_type="assertion",
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=[
            {"name": "wr_en", "width": 1, "role": "enable"},
            {"name": "data_in", "width": 32, "role": "data"},
        ],
    )

    stack, fake_db = _patch_preview_deps(rag, llm_pick, db_get_return_value=fake_tmpl)
    with stack:
        result = await pipeline_preview(inp, fake_db)

    module_meta = result.params["module_name"]
    assert module_meta["value"] == "dut"
    assert module_meta["source"] == "default"


# ── FIX-2 §2 Acceptance Criteria（端到端 pipeline_preview mock 集成测试）──────
#
# 锁定 FIX-2 §1.2 happy path 端到端契约：FSM 状态转换 intent，原文里没有 module_name，
# LLM step2 偏要返一个"看起来合理"的 ungrounded 值（'top'），原实现把它锁死 → 422 →
# IntentBuilder。FIX-2 守卫让模板 YAML default='dut' 接管 → PreviewResult 正常返回。
#
# 与 FIX-1 AC1/AC2 互补：FIX-1 拦的是 trivial LLM 值（"unknown"），FIX-2 拦的是
# non-trivial-but-fabricated LLM 值（"top"）。两类都不让前端误以为系统"懂用户意图"
# 而提示填错的代码。


@pytest.mark.asyncio
async def test_fix2_fsm_intent_ungrounded_module_name_falls_to_default():
    """FIX-2 端到端：FSM 状态转换 intent + LLM 返 module_name='top'（原文/form 都没这词）
    → pipeline_preview 正常返回 PreviewResult，module_name 走模板 default='dut'。

    前置：sva_fsm_state_transition_v1 已加 default: dut（Part B YAML 改动）。
    本测试用 mock template 直接注入 default 字段，独立验证守卫语义，
    不依赖 lib_manager.py 把 YAML 导入 PG（那是 post-merge deploy 步骤）。
    """
    rag = [_make_rag_candidate(
        "sva_fsm_state_transition_v1", score=0.92,
        parameters=[
            {"name": "module_name", "type": "string", "required": True,
             "description": "模块名", "default": "dut",
             "expr_type": "sv_identifier"},
            {"name": "clk", "type": "string", "required": True,
             "default": "clk", "expr_type": "sv_identifier"},
            {"name": "rst_n", "type": "string", "required": True,
             "default": "rst_n", "expr_type": "sv_identifier"},
            {"name": "state_sig", "type": "string", "required": True,
             "role_hint": "state", "expr_type": "sv_identifier"},
            {"name": "from_state", "type": "string", "required": True,
             "default": "IDLE", "expr_type": "sv_identifier"},
            {"name": "condition", "type": "string", "required": True,
             "expr_type": "sv_boolean_expr"},
            {"name": "to_state", "type": "string", "required": True,
             "default": "ACTIVE", "expr_type": "sv_identifier"},
        ],
    )]
    # LLM step2 给 module_name='top'（原文/form 都没这词）+ 其余 grounded 参数。
    # condition/state_sig 必须有高置信源否则 under_specified 闸会拦 —— 给它们
    # 原文里出现过的值，让本测试只暴露 module_name 这一根维度。
    llm_pick = TemplateSelectionOutput(
        template_id="sva_fsm_state_transition_v1",
        param_mapping={
            "module_name": "top",  # FIX-2 守卫的目标：ungrounded + has default
            "state_sig": "cur_state",
            "condition": "trigger == 1",
            "from_state": "IDLE",
            "to_state": "ACTIVE",
        },
        confidence=0.9,
    )

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = rag[0]["template"].parameters
    fake_tmpl.id = "sva_fsm_state_transition_v1"
    fake_tmpl.name = "FSM状态转换合法性断言"
    fake_tmpl.version = "1.0.0"

    inp = PipelineInput(
        # 原文含 cur_state / trigger / IDLE / ACTIVE 让其他参数 grounding 通过；
        # 关键：原文里**不出现** 'top' / 'dut'，让 module_name 守在测试条件上。
        original_intent="FSM 从 IDLE 转到 ACTIVE 的断言，状态信号 cur_state，触发条件 trigger == 1",
        code_type="assertion",
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=[
            {"name": "cur_state", "width": 4, "role": "state"},
        ],
    )

    stack, fake_db = _patch_preview_deps(rag, llm_pick, db_get_return_value=fake_tmpl)
    with stack:
        result = await pipeline_preview(inp, fake_db)

    # 关键断言 1：pipeline 正常返回（未抛 UnderSpecifiedIntentError 走到 IntentBuilder）
    assert result.template_id == "sva_fsm_state_transition_v1"
    # 关键断言 2：module_name 落在模板 default
    module_meta = result.params["module_name"]
    assert module_meta["value"] == "dut", \
        f"expected module_name=dut from template default, got {module_meta}"
    assert module_meta["source"] == "default", \
        f"expected source=default, got source={module_meta['source']}"


# ── 第五道闸：no_matching_template gate ─────────────────────────────────────

@pytest.mark.asyncio
async def test_no_matching_template_gate_fires_on_rag_fallback():
    """confidence_source=rag_fallback → NoMatchingTemplateError（FIX-9：score 不再参与触发判断）。

    场景：LLM step1 返回 "none"（db.get 找不到对应模板），rag_fallback 生效 →
    库内无此场景，直接引导贡献。score 仅供日志，不影响触发。
    redirect_to 应以 /contribute/new? 开头，携带 description 和 code_type。
    """
    from app.services.core.pipeline import NoMatchingTemplateError

    rag = [_make_rag_candidate("some_template", score=0.45)]
    # LLM 选 "none" → db.get("none") 返 None → rag_fallback
    llm_sel = TemplateSelectionOutput(template_id="none", param_mapping={}, confidence=0.3)

    fake_rag_tmpl = MagicMock()
    fake_rag_tmpl.parameters = []
    fake_rag_tmpl.id = "some_template"
    fake_rag_tmpl.name = "Some Template"
    fake_rag_tmpl.version = "1.0.0"

    # db.get("none") → None；db.get("some_template") → fake_rag_tmpl
    def _db_get_side_effect(model, id_):
        if id_ == "some_template":
            return fake_rag_tmpl
        return None

    stack, fake_db = _patch_preview_deps(rag, llm_sel)
    fake_db.get = AsyncMock(side_effect=_db_get_side_effect)

    with stack, pytest.raises(NoMatchingTemplateError) as excinfo:
        await pipeline_preview(_make_preview_inp("统计背压信号 bp_n 拉低时 tx_valid 是否暂停"), fake_db)

    err = excinfo.value
    assert err.detector == "no_matching_template"
    assert err.top_score == pytest.approx(0.45)
    assert err.redirect_to.startswith("/contribute/new?")
    assert "description=" in err.redirect_to
    assert "code_type=" in err.redirect_to


@pytest.mark.asyncio
async def test_no_matching_template_mutex_scenario():
    """FIX-9：互斥约束场景下 LLM step1 应返回空字符串 → rag_fallback → 第五道闸触发。

    场景：用户提交"断言 cpu_req 和 dma_req 不能在同一时钟周期同时有效，验证总线仲裁互斥约束"，
    库内只有握手类候选（sva_handshake_stable_v1）。真实生产现场 cross-encoder 因
    req 词汇重叠给该模板 score=1.0；新增的负向选择规则迫使 LLM step1 返回空字符串
    而非把 cpu_req/dma_req 重映射为 valid/ready。rag_fallback 接管后，FIX-9 闸条件
    已不再依赖 score，故 score=1.0 也能触发 NoMatchingTemplateError。
    """
    from app.services.core.pipeline import NoMatchingTemplateError

    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=1.0)]
    # 新负向规则下，LLM 对互斥场景应返回空字符串（而非强行映射到握手模板）
    llm_sel = TemplateSelectionOutput(template_id="", param_mapping={}, confidence=0.0)

    fake_rag_tmpl = MagicMock()
    fake_rag_tmpl.parameters = []
    fake_rag_tmpl.id = "sva_handshake_stable_v1"
    fake_rag_tmpl.name = "握手稳定性"
    fake_rag_tmpl.version = "1.0.0"

    def _db_get_side_effect(model, id_):
        if id_ == "sva_handshake_stable_v1":
            return fake_rag_tmpl
        return None

    stack, fake_db = _patch_preview_deps(rag, llm_sel)
    fake_db.get = AsyncMock(side_effect=_db_get_side_effect)

    mutex_intent = "断言 cpu_req 和 dma_req 不能在同一时钟周期同时有效，验证总线仲裁互斥约束"
    with stack, pytest.raises(NoMatchingTemplateError) as excinfo:
        await pipeline_preview(_make_preview_inp(mutex_intent), fake_db)

    err = excinfo.value
    assert err.detector == "no_matching_template"
    assert err.top_score == pytest.approx(1.0)
    assert err.code_type == "assertion"
    assert err.redirect_to.startswith("/contribute/new?")
    assert "description=" in err.redirect_to
    assert "code_type=" in err.redirect_to


@pytest.mark.asyncio
async def test_no_matching_template_gate_disabled_skips():
    """NO_MATCH_GATE_ENABLED=false → 即便 rag_fallback + score=1.0，闸不触发，
    退回旧 rag_fallback → 正常流程。紧急关闸通道回归保护。
    """
    from app.core.config import get_settings

    rag = [_make_rag_candidate("cov_transition_coverage_v1", score=1.0)]
    llm_sel = TemplateSelectionOutput(template_id="none", param_mapping={}, confidence=0.4)

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "cov_transition_coverage_v1"
    fake_tmpl.name = "状态转换覆盖率组"
    fake_tmpl.version = "1.0.0"

    def _db_get_side_effect(model, id_):
        if id_ == "cov_transition_coverage_v1":
            return fake_tmpl
        return None

    stack, fake_db = _patch_preview_deps(rag, llm_sel)
    fake_db.get = AsyncMock(side_effect=_db_get_side_effect)

    settings = get_settings()
    original = settings.no_match_gate_enabled
    settings.no_match_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(_make_preview_inp("生成一个 FSM 转换覆盖率"), fake_db)
        assert result.template_id == "cov_transition_coverage_v1"
        assert result.confidence_source == "rag_fallback"
    finally:
        settings.no_match_gate_enabled = original


# ── A8 step1 二次验证 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step1_verify_yes_keeps_llm_selection():
    """LLM step1 选中 + verify=yes → 正常返回 PreviewResult，confidence_source=llm_step1。

    显式开 STEP1_VERIFY_ENABLED——它在 config.py 中默认 False（标定后才开），但本测试
    锁的契约就是"verify 开启时回 yes 不影响 step1 决策"，所以必须显式开启。
    """
    from app.core.config import get_settings

    rag = [_make_rag_candidate("sva_handshake_timeout_v1", score=0.85)]
    llm_sel = TemplateSelectionOutput(
        template_id="sva_handshake_timeout_v1",
        param_mapping={"module_name": "axi_dma", "valid": "awvalid", "ready": "awready"},
        confidence=0.9,
    )

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "module_name", "required": True},
        {"name": "valid", "required": True, "role_hint": "valid"},
        {"name": "ready", "required": True, "role_hint": "ready"},
    ]
    fake_tmpl.id = "sva_handshake_timeout_v1"
    fake_tmpl.name = "Valid-Ready握手超时检测断言"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_sel, db_get_return_value=fake_tmpl)
    settings = get_settings()
    original = settings.step1_verify_enabled
    settings.step1_verify_enabled = True
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("axi_dma 模块 valid=awvalid ready=awready 握手超时断言"),
                fake_db,
            )
    finally:
        settings.step1_verify_enabled = original

    assert result.template_id == "sva_handshake_timeout_v1"
    assert result.confidence_source == "llm_step1"


@pytest.mark.asyncio
async def test_step1_verify_no_demotes_to_rag_fallback_and_triggers_no_match():
    """LLM step1 选中但 verify=no → confidence_source 降级 rag_fallback → 第五道闸触发
    NoMatchingTemplateError。即"二次验证识破 LLM 误选"路径。
    """
    from app.services.core.pipeline import NoMatchingTemplateError
    from contextlib import ExitStack

    rag = [_make_rag_candidate("sva_handshake_timeout_v1", score=0.75)]
    # LLM step1 给出选择，但 verify_step1_selection 会返 False 模拟"LLM 自审发现选错了"
    llm_sel = TemplateSelectionOutput(
        template_id="sva_handshake_timeout_v1",
        param_mapping={},
        confidence=0.9,
    )

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "sva_handshake_timeout_v1"
    fake_tmpl.name = "Valid-Ready握手超时检测断言"
    fake_tmpl.version = "1.0.0"

    stack = ExitStack()
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score", new=AsyncMock(return_value=0.9),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "hash_verify_no")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=rag),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_sel)
    # 关键：verify 返 False 模拟二次验证否定
    fake_llm.verify_step1_selection = AsyncMock(return_value=False)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    from app.core.config import get_settings
    settings = get_settings()
    original = settings.step1_verify_enabled
    settings.step1_verify_enabled = True  # 显式开（config.py 默认 False）
    try:
        with stack, pytest.raises(NoMatchingTemplateError) as excinfo:
            await pipeline_preview(_make_preview_inp("verify-no 触发降级测试"), fake_db)
    finally:
        settings.step1_verify_enabled = original

    # 二次验证否定 → 降级 rag_fallback → no_matching_template 闸（默认开启）拦下
    assert excinfo.value.detector == "no_matching_template"
    # verify_step1_selection 确实被 await 调用了（confirm pipeline 真走了 A8 路径）
    fake_llm.verify_step1_selection.assert_awaited_once()


@pytest.mark.asyncio
async def test_step1_verify_disabled_skips_verification():
    """STEP1_VERIFY_ENABLED=false → 不调 verify_step1_selection；LLM step1 选择直接生效。"""
    from contextlib import ExitStack

    rag = [_make_rag_candidate("sva_handshake_timeout_v1", score=0.85)]
    llm_sel = TemplateSelectionOutput(
        template_id="sva_handshake_timeout_v1",
        param_mapping={"module_name": "axi_dma", "valid": "awvalid", "ready": "awready"},
        confidence=0.9,
    )

    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "module_name", "required": True},
        {"name": "valid", "required": True, "role_hint": "valid"},
        {"name": "ready", "required": True, "role_hint": "ready"},
    ]
    fake_tmpl.id = "sva_handshake_timeout_v1"
    fake_tmpl.name = "Valid-Ready握手超时检测断言"
    fake_tmpl.version = "1.0.0"

    stack = ExitStack()
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score", new=AsyncMock(return_value=0.9),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "hash_verify_off")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=rag),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_sel)
    # 即便 verify mock 配成 False，禁用开关后也不应被调用
    fake_llm.verify_step1_selection = AsyncMock(return_value=False)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)

    from app.core.config import get_settings
    settings = get_settings()
    original = settings.step1_verify_enabled
    settings.step1_verify_enabled = False
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("axi_dma 模块 valid=awvalid ready=awready 握手超时"),
                fake_db,
            )
        # 关键：verify 没被调用
        fake_llm.verify_step1_selection.assert_not_awaited()
        # 关键：step1 选择按原样生效（即便 verify mock 返 False 也不影响）
        assert result.template_id == "sva_handshake_timeout_v1"
        assert result.confidence_source == "llm_step1"
    finally:
        settings.step1_verify_enabled = original


# ── A9 reranker score gate ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step1_reranker_gate_fires_when_selected_score_below_threshold():
    """LLM step1 选中 id 的 reranker score 低于阈值 → NoMatchingTemplateError，
    redirect_to 走贡献页路径。"""
    from app.services.core.pipeline import NoMatchingTemplateError
    from app.core.config import get_settings

    settings = get_settings()
    # 构造 selected_score (0.10) 显著低于阈值 (0.30) 的场景
    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.10)]
    llm_sel = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={},
        confidence=0.9,
    )
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "sva_handshake_stable_v1"
    fake_tmpl.name = "Stable"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_sel, db_get_return_value=fake_tmpl)

    original_gate = settings.step1_reranker_gate_enabled
    original_thresh = settings.reranker_min_score_threshold
    settings.step1_reranker_gate_enabled = True
    settings.reranker_min_score_threshold = 0.30
    try:
        with stack, pytest.raises(NoMatchingTemplateError) as excinfo:
            await pipeline_preview(_make_preview_inp("reranker gate 触发测试"), fake_db)
    finally:
        settings.step1_reranker_gate_enabled = original_gate
        settings.reranker_min_score_threshold = original_thresh

    e = excinfo.value
    assert e.detector == "no_matching_template"
    assert e.top_score == pytest.approx(0.10)
    assert e.redirect_to.startswith("/contribute/new?")


@pytest.mark.asyncio
async def test_step1_reranker_gate_disabled_skips():
    """STEP1_RERANKER_GATE_ENABLED=false → 即便 selected_score 远低于阈值也不拦，
    PreviewResult 正常返回。逃生通道。"""
    from app.core.config import get_settings

    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.05)]
    llm_sel = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={"module_name": "dut", "valid": "v", "ready": "r", "data": "d"},
        confidence=0.9,
    )
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "module_name", "required": True, "default": "dut"},
        {"name": "valid", "required": True, "role_hint": "valid"},
        {"name": "ready", "required": True, "role_hint": "ready"},
        {"name": "data", "required": True, "role_hint": "data"},
    ]
    fake_tmpl.id = "sva_handshake_stable_v1"
    fake_tmpl.name = "Stable"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_sel, db_get_return_value=fake_tmpl)

    settings = get_settings()
    original_gate = settings.step1_reranker_gate_enabled
    original_us = settings.under_specified_gate_enabled
    settings.step1_reranker_gate_enabled = False
    # 关 under_specified 闸：本测试只关心 reranker gate 是否被跳过，参数完整性不在范围
    settings.under_specified_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("dut 模块 valid=v ready=r data=d 握手稳定性"),
                fake_db,
            )
        assert result.template_id == "sva_handshake_stable_v1"
    finally:
        settings.step1_reranker_gate_enabled = original_gate
        settings.under_specified_gate_enabled = original_us


@pytest.mark.asyncio
async def test_step1_reranker_gate_passes_when_score_above_threshold():
    """selected_score 高于阈值 → 不抛，正常走流水线。回归保护，防 A9 误拦边缘真请求。"""
    from app.core.config import get_settings

    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.55)]  # 0.55 > 0.30
    llm_sel = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={"module_name": "dut", "valid": "v", "ready": "r", "data": "d"},
        confidence=0.9,
    )
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "module_name", "required": True, "default": "dut"},
        {"name": "valid", "required": True, "role_hint": "valid"},
        {"name": "ready", "required": True, "role_hint": "ready"},
        {"name": "data", "required": True, "role_hint": "data"},
    ]
    fake_tmpl.id = "sva_handshake_stable_v1"
    fake_tmpl.name = "Stable"
    fake_tmpl.version = "1.0.0"

    stack, fake_db = _patch_preview_deps(rag, llm_sel, db_get_return_value=fake_tmpl)

    settings = get_settings()
    original_gate = settings.step1_reranker_gate_enabled
    original_thresh = settings.reranker_min_score_threshold
    original_us = settings.under_specified_gate_enabled
    settings.step1_reranker_gate_enabled = True
    settings.reranker_min_score_threshold = 0.30
    settings.under_specified_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("dut 模块 valid=v ready=r data=d 握手稳定性"),
                fake_db,
            )
        assert result.template_id == "sva_handshake_stable_v1"
        assert result.confidence_source == "llm_step1"
    finally:
        settings.step1_reranker_gate_enabled = original_gate
        settings.reranker_min_score_threshold = original_thresh
        settings.under_specified_gate_enabled = original_us


# ── FEAT-11 A：高置信 RAG 自动 quick_render（跳过 ConfirmationPanel）─────────

def _make_high_conf_template_mock():
    """构造一个让所有 required 参数都能落到 llm/regex/signal_list/default 的 fake template。

    所有四个 required 参数：module_name（LLM 给 grounded 值）/ valid / ready / clk（default）。
    """
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "module_name", "required": True, "default": "dut"},
        {"name": "valid", "required": True, "role_hint": "valid"},
        {"name": "ready", "required": True, "role_hint": "ready"},
        {"name": "clk", "required": True, "default": "clk"},
    ]
    fake_tmpl.id = "sva_handshake_stable_v1"
    fake_tmpl.name = "Stable"
    fake_tmpl.version = "1.0.0"
    return fake_tmpl


@pytest.mark.asyncio
async def test_feat11_high_conf_all_green_sets_quick_render_true():
    """四条件齐绿：confidence_source=llm_step1 + verify_ok + score≥阈值 + 全高置信源
    → PreviewResult.quick_render=True，让前端跳过 ConfirmationPanel 直渲。"""
    from app.core.config import get_settings

    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.85)]
    llm_full = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={"module_name": "axi_dma", "valid": "awvalid", "ready": "awready"},
        confidence=0.95,
    )
    fake_tmpl = _make_high_conf_template_mock()
    stack, fake_db = _patch_preview_deps(rag, llm_full, db_get_return_value=fake_tmpl)

    settings = get_settings()
    original_verify = settings.step1_verify_enabled
    original_thresh = settings.reranker_min_score_threshold
    settings.step1_verify_enabled = True
    settings.reranker_min_score_threshold = 0.30
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("axi_dma 模块 valid=awvalid ready=awready 握手稳定性断言"),
                fake_db,
            )
        assert result.quick_render is True
        assert result.confidence_source == "llm_step1"
    finally:
        settings.step1_verify_enabled = original_verify
        settings.reranker_min_score_threshold = original_thresh


@pytest.mark.asyncio
async def test_feat11_quick_render_false_when_verify_disabled():
    """step1_verify_enabled=False → 即便其他三条件齐绿，也禁高置信直渲（缺一个独立信号）。"""
    from app.core.config import get_settings

    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.85)]
    llm_full = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={"module_name": "axi_dma", "valid": "awvalid", "ready": "awready"},
        confidence=0.95,
    )
    fake_tmpl = _make_high_conf_template_mock()
    stack, fake_db = _patch_preview_deps(rag, llm_full, db_get_return_value=fake_tmpl)

    settings = get_settings()
    original_verify = settings.step1_verify_enabled
    original_thresh = settings.reranker_min_score_threshold
    settings.step1_verify_enabled = False
    settings.reranker_min_score_threshold = 0.30
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("axi_dma 模块 valid=awvalid ready=awready 握手稳定性断言"),
                fake_db,
            )
        assert result.quick_render is False
    finally:
        settings.step1_verify_enabled = original_verify
        settings.reranker_min_score_threshold = original_thresh


@pytest.mark.asyncio
async def test_feat11_quick_render_false_when_score_below_threshold():
    """selected_score < reranker_min_score_threshold → 即便其他三条件齐绿，禁直渲。"""
    from app.core.config import get_settings

    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.20)]
    llm_full = TemplateSelectionOutput(
        template_id="sva_handshake_stable_v1",
        param_mapping={"module_name": "axi_dma", "valid": "awvalid", "ready": "awready"},
        confidence=0.95,
    )
    fake_tmpl = _make_high_conf_template_mock()
    stack, fake_db = _patch_preview_deps(rag, llm_full, db_get_return_value=fake_tmpl)

    settings = get_settings()
    original_verify = settings.step1_verify_enabled
    original_thresh = settings.reranker_min_score_threshold
    original_gate = settings.step1_reranker_gate_enabled
    settings.step1_verify_enabled = True
    settings.reranker_min_score_threshold = 0.30
    # A9 gate 关 —— 避免 0.20<0.30 直接抛 NoMatchingTemplateError 掩盖测试目标
    settings.step1_reranker_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("axi_dma 模块 valid=awvalid ready=awready 握手稳定性断言"),
                fake_db,
            )
        assert result.quick_render is False
    finally:
        settings.step1_verify_enabled = original_verify
        settings.reranker_min_score_threshold = original_thresh
        settings.step1_reranker_gate_enabled = original_gate


@pytest.mark.asyncio
async def test_feat11_quick_render_false_when_rag_fallback():
    """confidence_source=rag_fallback（LLM 拒所有候选）→ 禁直渲，必须走 ConfirmationPanel。"""
    from app.core.config import get_settings

    rag = [_make_rag_candidate("sva_handshake_stable_v1", score=0.85)]
    llm_refused = TemplateSelectionOutput(
        template_id="",
        param_mapping={},
        confidence=0.0,
    )
    fake_tmpl = _make_high_conf_template_mock()
    stack, fake_db = _patch_preview_deps(rag, llm_refused, db_get_return_value=fake_tmpl)

    settings = get_settings()
    original_verify = settings.step1_verify_enabled
    original_thresh = settings.reranker_min_score_threshold
    original_no_match = settings.no_match_gate_enabled
    original_us = settings.under_specified_gate_enabled
    settings.step1_verify_enabled = True
    settings.reranker_min_score_threshold = 0.30
    # 关掉 no_match + under_specified 闸，让 rag_fallback 路径走到结尾产 PreviewResult
    settings.no_match_gate_enabled = False
    settings.under_specified_gate_enabled = False
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("axi_dma 模块 valid=awvalid ready=awready 握手稳定性"),
                fake_db,
            )
        assert result.confidence_source == "rag_fallback"
        assert result.quick_render is False
    finally:
        settings.step1_verify_enabled = original_verify
        settings.reranker_min_score_threshold = original_thresh
        settings.no_match_gate_enabled = original_no_match
        settings.under_specified_gate_enabled = original_us


@pytest.mark.asyncio
async def test_feat11_quick_render_false_when_param_has_semantic_fallback():
    """所有四条件齐绿但有 required 参数落在 semantic_fallback → 禁直渲。

    placeholder / semantic_fallback 都不是用户/LLM 给的，强制走 ConfirmationPanel
    让用户先确认再渲染。本测试关闭 under_specified 闸，否则会先于本判定拦下。
    """
    from app.core.config import get_settings

    rag = [_make_rag_candidate("cov_transition_coverage_v1", score=0.85)]
    # state_list 既无 LLM 给值也无 regex 提取 → 落到 semantic_fallback="IDLE, ACTIVE, DONE"
    llm_partial = TemplateSelectionOutput(
        template_id="cov_transition_coverage_v1",
        param_mapping={"signal": "cur_state", "group_name": "fsm_cg"},
        confidence=0.95,
    )
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = [
        {"name": "signal", "required": True},
        {"name": "group_name", "required": True, "default": "fsm_cg"},
        {"name": "state_list", "required": True},
        {"name": "clk", "required": True, "default": "clk"},
    ]
    fake_tmpl.id = "cov_transition_coverage_v1"
    fake_tmpl.name = "transition cov"
    fake_tmpl.version = "1.0.0"
    stack, fake_db = _patch_preview_deps(rag, llm_partial, db_get_return_value=fake_tmpl)

    settings = get_settings()
    original_verify = settings.step1_verify_enabled
    original_thresh = settings.reranker_min_score_threshold
    original_us = settings.under_specified_gate_enabled
    settings.step1_verify_enabled = True
    settings.reranker_min_score_threshold = 0.30
    settings.under_specified_gate_enabled = False  # 否则会先拦 state_list 缺失
    try:
        with stack:
            result = await pipeline_preview(
                _make_preview_inp("cur_state 状态转换覆盖率 fsm_cg"),
                fake_db,
            )
        # 至少有一个参数落 semantic_fallback / placeholder → 必须 False
        assert result.quick_render is False
    finally:
        settings.step1_verify_enabled = original_verify
        settings.reranker_min_score_threshold = original_thresh
        settings.under_specified_gate_enabled = original_us
