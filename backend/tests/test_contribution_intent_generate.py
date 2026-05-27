"""FEAT-10：intent-only 生成单测——锁定 generate_from_intent 行为。

覆盖 4 个场景：
1. 正常路径：LLM 返合法 JSON，5 字段齐全 → ExtractedFull
2. LLM 返回非法参数名（中文 / 撞 SV 关键字） → ContributionParseError(stage=param_defs_name)
3. original_intent 为空 → ContributionParseError(stage=input)
4. template_name 命名格式非法（不匹配 ^(sva|cov)_..._v\\d+$） → ContributionParseError(stage=template_name)

跑法：docker compose exec backend pytest tests/test_contribution_intent_generate.py -v
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.platform.parameter_extractor import (
    ContributionParseError,
    ExtractedFull,
    generate_from_intent,
)


_HAPPY_JSON = """```json
{
  "template_name": "sva_axi_handshake_data_stable_v1",
  "description": "检测 AXI valid-ready 握手期间数据信号必须保持稳定。",
  "demo_code": "module sva_axi_handshake_data_stable (input logic clk, input logic valid, input logic ready, input logic [31:0] data);\\n  property p;\\n    @(posedge clk) (valid && !ready) |-> $stable(data);\\n  endproperty\\n  assert property (p);\\nendmodule",
  "parameter_defs": [
    {"name": "clk", "type": "string", "required": true, "description": "时钟", "expr_type": "sv_identifier", "default": "clk"},
    {"name": "valid_sig", "type": "string", "required": true, "description": "valid 信号", "expr_type": "sv_identifier"},
    {"name": "ready_sig", "type": "string", "required": true, "description": "ready 信号", "expr_type": "sv_identifier"},
    {"name": "data_sig", "type": "string", "required": true, "description": "数据信号", "expr_type": "sv_identifier"}
  ],
  "jinja_body": "module mod (input logic {{ clk }}, input logic {{ valid_sig }}, input logic {{ ready_sig }}, input logic [31:0] {{ data_sig }});\\n  property p;\\n    @(posedge {{ clk }}) ({{ valid_sig }} && !{{ ready_sig }}) |-> $stable({{ data_sig }});\\n  endproperty\\n  assert property (p);\\nendmodule",
  "keywords": ["AXI", "握手", "handshake"],
  "subcategory": "handshake",
  "protocol": "AXI4"
}
```"""


@pytest.mark.asyncio
async def test_generate_from_intent_happy_path():
    """LLM 返合法 JSON，5 个字段齐全且 4 道校验全过 → ExtractedFull。"""
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value=_HAPPY_JSON)

    out = await generate_from_intent(
        original_intent="检测 AXI valid-ready 握手期间数据信号必须保持稳定",
        code_type="assertion",
        llm=fake_llm,
    )
    assert isinstance(out, ExtractedFull)
    assert out.template_name == "sva_axi_handshake_data_stable_v1"
    assert out.description.startswith("检测 AXI")
    # demo_code 是 LLM 产出的**原始 SystemVerilog 代码**（含真实信号名），不带 {{ }} 占位符
    assert "module sva_axi_handshake_data_stable" in out.demo_code
    assert "{{" not in out.demo_code
    # jinja_body 是参数化后的模板体，含 {{ clk }} 等占位符
    assert "{{ clk }}" in out.jinja_body
    assert {p["name"] for p in out.parameter_defs} == {"clk", "valid_sig", "ready_sig", "data_sig"}
    assert out.keywords == ["AXI", "握手", "handshake"]
    assert out.subcategory == "handshake"
    assert out.protocol == "AXI4"


@pytest.mark.asyncio
async def test_generate_from_intent_invalid_param_name_raises():
    """LLM 把参数命名为中文或撞 SV 关键字 → ContributionParseError(stage=param_defs_name)。"""
    bad_json = """```json
{
  "template_name": "sva_demo_v1",
  "description": "示例场景",
  "demo_code": "module x; endmodule",
  "parameter_defs": [
    {"name": "信号", "expr_type": "sv_identifier"}
  ],
  "jinja_body": "logic x;",
  "keywords": ["x"]
}
```"""
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value=bad_json)

    with pytest.raises(ContributionParseError) as exc:
        await generate_from_intent(
            original_intent="任意意图",
            code_type="assertion",
            llm=fake_llm,
        )
    assert exc.value.stage == "param_defs_name"


@pytest.mark.asyncio
async def test_generate_from_intent_empty_intent_raises():
    """original_intent 为空（仅空格也算） → ContributionParseError(stage=input)。
    LLM 不应被调用。
    """
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="{}")

    with pytest.raises(ContributionParseError) as exc:
        await generate_from_intent(
            original_intent="   ",
            code_type="assertion",
            llm=fake_llm,
        )
    assert exc.value.stage == "input"
    # LLM 不应该被调用——空输入直接拒
    fake_llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_generate_from_intent_illegal_template_name_raises():
    """LLM 返的 template_name 不符合命名规范 → ContributionParseError(stage=template_name)。

    错误格式举例：
    - 缺前缀（"axi_handshake_v1"）
    - 缺版本后缀（"sva_axi_handshake"）
    - 含大写（"SVA_axi_v1"）
    """
    bad_json = """```json
{
  "template_name": "AXI_check",
  "description": "任意",
  "demo_code": "module x; endmodule",
  "parameter_defs": [{"name": "clk", "expr_type": "sv_identifier"}],
  "jinja_body": "logic {{ clk }};",
  "keywords": []
}
```"""
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value=bad_json)

    with pytest.raises(ContributionParseError) as exc:
        await generate_from_intent(
            original_intent="检测 AXI",
            code_type="assertion",
            llm=fake_llm,
        )
    assert exc.value.stage == "template_name"
