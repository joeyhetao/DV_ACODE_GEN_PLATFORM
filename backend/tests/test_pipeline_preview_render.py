"""Unit tests for pipeline_preview / pipeline_render split (方案 3)。

跑法（容器内）:
    docker compose exec backend pytest tests/test_pipeline_preview_render.py -v

测试不依赖真实 LLM API / Qdrant / PostgreSQL，全部用 unittest.mock 桩。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.core.pipeline import (
    OffTopicIntentError,
    PipelineInput,
    PreviewResult,
    RenderInput,
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


def _make_inp(signals=None, clk="clk", rst="rst_n", rst_polarity="低有效"):
    return PipelineInput(
        original_intent="dummy",
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
               new=AsyncMock(return_value="// cached code")):
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


def _make_preview_inp():
    return PipelineInput(
        original_intent="some user input",
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
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=db_get_return_value)
    return stack, fake_db


@pytest.mark.asyncio
async def test_pipeline_preview_off_topic_dense_threshold_early_returns():
    """dense_top1_score < threshold → 在 normalize/RAG/LLM 之前就早返 OffTopicIntentError。

    校准结果决定 threshold=0.44；mock dense=0.30 < 0.44，应当抛 OffTopicIntentError。
    detector="rag_dense_threshold"，携带 top_dense_score 和 threshold 给前端。
    """
    rag = [_make_rag_candidate("any_id", score=0.9)]
    llm_sel = TemplateSelectionOutput(template_id="any_id", param_mapping={}, confidence=0.9)
    stack, fake_db = _patch_preview_deps(rag, llm_sel, dense_score=0.30)
    with stack, pytest.raises(OffTopicIntentError) as excinfo:
        await pipeline_preview(_make_preview_inp(), fake_db)

    assert excinfo.value.detector == "rag_dense_threshold"
    assert excinfo.value.top_dense_score == 0.30
    assert excinfo.value.threshold == 0.44  # 跟 config.py 默认一致


@pytest.mark.asyncio
async def test_pipeline_preview_marginal_intent_falls_back_with_llm_confidence():
    """LLM step1 没选出 template（marginal 真请求）→ 走 rag_fallback；
    且 confidence 保留 LLM 上报的 0.0，不再被 RAG cross-encoder 分数覆盖。

    这是真 IC 请求但表述简略的常见路径。即便 RAG top1 分数较低（如 0.7），
    也不应当被拒——这是 normalize_intent 信任路径（sentinel 没触发）。
    """
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
    with stack:
        result = await pipeline_preview(_make_preview_inp(), fake_db)

    assert result.template_id == "sva_handshake_timeout_v1"
    assert result.confidence_source == "rag_fallback"
    # 关键断言：confidence 是 LLM 上报的 0.0，不再被 RAG 0.95 覆盖
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_pipeline_preview_off_topic_gate_disabled_skips_check():
    """offtopic_gate_enabled=False → 即使 dense 分数低于阈值，也跳过闸继续走老路径。
    紧急逃生通道：若阈值校准误调或语料缺失导致大面积误拒，可立即关闸。"""
    fake_db_template = MagicMock()
    fake_db_template.parameters = []
    fake_db_template.id = "sva_data_integrity_v1"
    fake_db_template.name = "Template sva_data_integrity_v1"
    fake_db_template.version = "1.0.0"
    rag = [_make_rag_candidate("sva_data_integrity_v1", score=0.5)]
    llm_refused = TemplateSelectionOutput(template_id="", param_mapping={}, confidence=0.0)

    from app.core.config import get_settings
    settings = get_settings()
    original = settings.offtopic_gate_enabled
    settings.offtopic_gate_enabled = False
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
        settings.offtopic_gate_enabled = original
