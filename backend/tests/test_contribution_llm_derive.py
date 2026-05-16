"""v3.0 贡献机制 LLM 反推 parameters 单测。

锁定：
- LLM 输出合法 JSON + 通过 3 道校验 → ExtractedParameters
- LLM 输出非法 JSON → ContributionParseError(stage=json_parse)
- LLM 输出 parameters name 含中文 → ContributionParseError(stage=param_defs_name)
- LLM 输出 expr_type 不在白名单 → ContributionParseError(stage=param_defs_expr_type)
- Jinja2 模板引用未声明参数 → ContributionParseError(stage=jinja_render)
- Jinja2 语法错误 → ContributionParseError(stage=jinja_syntax)
- parameter_defs 空 → ContributionParseError(stage=param_defs_empty)
- demo_code 空 → ContributionParseError(stage=input)

跑法：docker compose exec backend pytest tests/test_contribution_llm_derive.py -v
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.platform.parameter_extractor import (
    ContributionParseError,
    _extract_json_block,
    _validate_jinja_rendering,
    _validate_keywords,
    _validate_parameter_defs,
    derive_parameters_from_demo,
)


# ── _extract_json_block 纯函数单测 ────────────────────────────────────────

def test_extract_json_block_from_code_fence():
    """LLM 用 ```json ... ``` 包裹的 JSON 能抽出。"""
    raw = '随便聊两句。\n```json\n{"a": 1, "b": [2, 3]}\n```\n收尾废话。'
    out = _extract_json_block(raw)
    assert out == {"a": 1, "b": [2, 3]}


def test_extract_json_block_from_bare_text():
    """没有 fence 但有 { } 的 JSON 也能抽。"""
    raw = '响应：{"name": "x", "value": 42}'
    out = _extract_json_block(raw)
    assert out == {"name": "x", "value": 42}


def test_extract_json_block_empty_raises():
    with pytest.raises(ContributionParseError) as exc:
        _extract_json_block("")
    assert exc.value.stage == "llm_response"


def test_extract_json_block_no_json_raises():
    """LLM 返纯文本无 JSON → 抛 json_locate。"""
    with pytest.raises(ContributionParseError) as exc:
        _extract_json_block("这是一段没有任何 JSON 的纯文本")
    assert exc.value.stage == "json_locate"


def test_extract_json_block_malformed_json_raises():
    """有 { } 但 JSON 语法错 → 抛 json_parse。"""
    with pytest.raises(ContributionParseError) as exc:
        _extract_json_block('```json\n{"x": 1,,, }\n```')
    assert exc.value.stage == "json_parse"


# ── _validate_parameter_defs 单测 ─────────────────────────────────────────

def test_validate_parameter_defs_happy_path():
    """合法 list[dict]，每个 name 合法 / expr_type 在白名单 → 不抛。"""
    _validate_parameter_defs([
        {"name": "clk", "expr_type": "sv_identifier"},
        {"name": "valid", "expr_type": "sv_identifier"},
        {"name": "state_list", "expr_type": "sv_identifier_list"},
    ])


def test_validate_parameter_defs_empty_raises():
    with pytest.raises(ContributionParseError) as exc:
        _validate_parameter_defs([])
    assert exc.value.stage == "param_defs_empty"


def test_validate_parameter_defs_not_list_raises():
    with pytest.raises(ContributionParseError) as exc:
        _validate_parameter_defs({"oops": "dict"})
    assert exc.value.stage == "param_defs_shape"


def test_validate_parameter_defs_chinese_name_raises():
    """中文参数名 → 抛 param_defs_name。"""
    with pytest.raises(ContributionParseError) as exc:
        _validate_parameter_defs([{"name": "信号", "expr_type": "sv_identifier"}])
    assert exc.value.stage == "param_defs_name"


def test_validate_parameter_defs_uppercase_name_raises():
    with pytest.raises(ContributionParseError) as exc:
        _validate_parameter_defs([{"name": "MyParam", "expr_type": "sv_identifier"}])
    assert exc.value.stage == "param_defs_name"


def test_validate_parameter_defs_duplicate_name_raises():
    with pytest.raises(ContributionParseError) as exc:
        _validate_parameter_defs([
            {"name": "clk", "expr_type": "sv_identifier"},
            {"name": "clk", "expr_type": "sv_identifier"},
        ])
    assert exc.value.stage == "param_defs_name"


def test_validate_parameter_defs_bad_expr_type_raises():
    with pytest.raises(ContributionParseError) as exc:
        _validate_parameter_defs([{"name": "x", "expr_type": "not_a_real_type"}])
    assert exc.value.stage == "param_defs_expr_type"


@pytest.mark.parametrize("keyword", [
    "always", "module", "assign", "class", "for", "if", "begin", "end",
    "logic", "wire", "covergroup", "assert", "property", "import",
])
def test_validate_parameter_defs_rejects_sv_python_keywords(keyword):
    """P1-5：SV/Python 关键字作参数名应被拒——这些都过 _VALID_NAME_RE 但生成代码会炸。"""
    with pytest.raises(ContributionParseError) as exc:
        _validate_parameter_defs([{"name": keyword, "expr_type": "sv_identifier"}])
    assert exc.value.stage == "param_defs_name"
    assert "关键字" in exc.value.reason


# ── _validate_jinja_rendering 单测 ────────────────────────────────────────

def test_validate_jinja_rendering_happy_path():
    """所有 {{ var }} 都在 parameter_defs 里声明 → 不抛。"""
    _validate_jinja_rendering(
        "module {{ name }};\n  logic {{ signal }};\nendmodule",
        [{"name": "name"}, {"name": "signal"}],
    )


def test_validate_jinja_rendering_undefined_var_raises():
    """{{ undeclared }} 没在 parameter_defs 里声明 → 抛 jinja_render。"""
    with pytest.raises(ContributionParseError) as exc:
        _validate_jinja_rendering(
            "module {{ name }};\n  logic {{ undeclared }};\nendmodule",
            [{"name": "name"}],
        )
    assert exc.value.stage == "jinja_render"


def test_validate_jinja_rendering_syntax_error_raises():
    """Jinja2 语法错（如未关闭的标签）→ 抛 jinja_syntax。"""
    with pytest.raises(ContributionParseError) as exc:
        _validate_jinja_rendering(
            "module {{ name ;",  # 没 }} 关闭
            [{"name": "name"}],
        )
    assert exc.value.stage == "jinja_syntax"


def test_validate_jinja_rendering_empty_raises():
    with pytest.raises(ContributionParseError) as exc:
        _validate_jinja_rendering("", [{"name": "x"}])
    assert exc.value.stage == "jinja_empty"


# ── P0-2 SSTI 沙箱阻断单测 ───────────────────────────────────────────────

@pytest.mark.parametrize("ssti_payload", [
    "{{ self.__class__ }}",
    "{{ ''.__class__.__mro__ }}",
    "{{ self.__class__.__bases__ }}",
    "{{ self.__init__.__globals__ }}",
    "{{ ''.__class__.__mro__[-1].__subclasses__() }}",
    "{% set x = ''.__class__ %}{{ x }}",
])
def test_validate_jinja_rendering_blocks_ssti_payloads(ssti_payload):
    """LLM 反推的 jinja_body 若含 SSTI payload（dunder 访问 / __class__ 链 / __init__ 等），
    必须被 SandboxedEnvironment 阻断为 SecurityError，转 ContributionParseError(stage=jinja_sandbox)。

    P0-2 安全回归：v3.0 之前用普通 Environment，这类 payload 渲染时可执行任意代码。
    """
    full_body = f"module test;\n  // {ssti_payload}\nendmodule"
    with pytest.raises(ContributionParseError) as exc:
        _validate_jinja_rendering(full_body, [{"name": "module_name"}])
    # SecurityError 或 jinja_render 都接受——只要不放过去
    assert exc.value.stage in ("jinja_sandbox", "jinja_render"), \
        f"SSTI payload {ssti_payload!r} 应被沙箱拦截，实际 stage={exc.value.stage}"


def test_validate_jinja_rendering_blocks_attr_set_chain():
    """{% set x = obj.attr.attr %} 这种用 set 链式访问 dunder，沙箱也要拦。"""
    body = "module x;\n  {% set bad = ''.__class__.__mro__ %}{{ bad }}\nendmodule"
    with pytest.raises(ContributionParseError) as exc:
        _validate_jinja_rendering(body, [])
    assert exc.value.stage in ("jinja_sandbox", "jinja_render", "param_defs_empty")


# ── _validate_keywords 单测 ──────────────────────────────────────────────

def test_validate_keywords_dedupe_and_strip():
    out = _validate_keywords(["AXI", " AXI ", "握手", "", "  ", "握手"])
    assert out == ["AXI", "握手"]


def test_validate_keywords_none_returns_empty():
    assert _validate_keywords(None) == []


def test_validate_keywords_non_list_raises():
    with pytest.raises(ContributionParseError) as exc:
        _validate_keywords("AXI,握手")
    assert exc.value.stage == "keywords_shape"


# ── derive_parameters_from_demo 集成单测 ─────────────────────────────────

@pytest.mark.asyncio
async def test_derive_parameters_happy_path():
    """LLM 返合法 JSON，3 道校验全过 → ExtractedParameters。"""
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="""```json
{
  "parameter_defs": [
    {"name": "clk", "type": "string", "required": true, "description": "时钟", "expr_type": "sv_identifier", "default": "clk"},
    {"name": "signal", "type": "string", "required": true, "description": "信号", "expr_type": "sv_identifier"}
  ],
  "jinja_body": "module test;\\n  assign x = {{ signal }};\\n  always @({{ clk }}) begin end\\nendmodule",
  "keywords": ["AXI", "test"],
  "subcategory": "handshake",
  "protocol": "AXI4"
}
```""")
    out = await derive_parameters_from_demo(
        demo_code="module test; assign x = sig; always @(clk) begin end endmodule",
        description="测试场景",
        code_type="assertion",
        llm=fake_llm,
    )
    assert len(out.parameter_defs) == 2
    assert {p["name"] for p in out.parameter_defs} == {"clk", "signal"}
    assert out.keywords == ["AXI", "test"]
    assert out.subcategory == "handshake"
    assert out.protocol == "AXI4"


@pytest.mark.asyncio
async def test_derive_parameters_empty_demo_raises():
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="{}")
    with pytest.raises(ContributionParseError) as exc:
        await derive_parameters_from_demo(
            demo_code="   ", description="x", code_type="assertion", llm=fake_llm,
        )
    assert exc.value.stage == "input"


@pytest.mark.asyncio
async def test_derive_parameters_llm_bad_json_raises():
    """LLM 返非法 JSON → derive 应抛 ContributionParseError。"""
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="（LLM 偷懒没返 JSON）")
    with pytest.raises(ContributionParseError) as exc:
        await derive_parameters_from_demo(
            demo_code="module x; endmodule",
            description="x",
            code_type="assertion",
            llm=fake_llm,
        )
    assert exc.value.stage in ("json_locate", "json_parse")


@pytest.mark.asyncio
async def test_derive_parameters_jinja_undefined_var_raises():
    """LLM 反推产出的 jinja_body 引用了 parameter_defs 里没声明的变量 → 抛 jinja_render。"""
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="""```json
{
  "parameter_defs": [{"name": "clk", "expr_type": "sv_identifier"}],
  "jinja_body": "logic {{ orphan_var }};",
  "keywords": []
}
```""")
    with pytest.raises(ContributionParseError) as exc:
        await derive_parameters_from_demo(
            demo_code="logic sig;", description="x", code_type="assertion", llm=fake_llm,
        )
    assert exc.value.stage == "jinja_render"
