"""Unit tests for app.services.core.pipeline._extract_params_from_intent.

跑法（容器内）:
    docker compose exec backend pytest backend/tests/test_extract_params.py -v
"""
from app.services.core.pipeline import _extract_params_from_intent


# ── coverage 模板用例（既有功能，回归保护）────────────────────────────────

def test_signal_name_extraction():
    """状态信号名为 cur_state → signal=cur_state, group_name=cur_state"""
    p = _extract_params_from_intent("状态信号名为 cur_state")
    assert p["signal"] == "cur_state"
    assert p["group_name"] == "cur_state"


def test_signal_width_extraction():
    """位宽 3 位 → signal_width=3"""
    p = _extract_params_from_intent("位宽3位")
    assert p["signal_width"] == 3


def test_state_list_extraction_with_anchor():
    """状态包括 IDLE、FETCH、DECODE、EXECUTE → state_list 4 项"""
    p = _extract_params_from_intent("状态包括IDLE、FETCH、DECODE、EXECUTE")
    assert "IDLE" in p["state_list"]
    assert "FETCH" in p["state_list"]
    assert "DECODE" in p["state_list"]
    assert "EXECUTE" in p["state_list"]


# ── assertion 模板用例（本次新增功能）─────────────────────────────────────

def test_module_name_extraction():
    """模块名为 reg_block → module_name=reg_block（§1.1 v3 关键场景）"""
    p = _extract_params_from_intent(
        "寄存器写保护场景的数据完整性断言：模块名为 reg_block，当写使能无效时数据信号不被意外修改"
    )
    assert p["module_name"] == "reg_block"


def test_module_name_with_colon():
    """模块: ctrl_fsm → module_name=ctrl_fsm"""
    p = _extract_params_from_intent("FSM 状态机断言，模块: ctrl_fsm")
    assert p["module_name"] == "ctrl_fsm"


def test_max_cycles_extraction():
    """N 周期内 → 同时填 max_cycles 与 max_delay（§1.4 / §1.6 共用）"""
    p = _extract_params_from_intent(
        "valid 拉高后 ready 必须在 16 周期内响应防止握手死锁"
    )
    assert p["max_cycles"] == 16
    assert p["max_delay"] == 16


def test_max_cycles_with_ge():
    """N 个周期 → 同 max_cycles"""
    p = _extract_params_from_intent("8 个周期内必须返回")
    assert p["max_cycles"] == 8


def test_init_value_decimal():
    """复位值为 0 → init_value='0'"""
    p = _extract_params_from_intent("复位释放后计数器初始值为 0")
    assert p["init_value"] == "0"


def test_init_value_hex():
    """初始值: 0xFF → init_value='0xFF'"""
    p = _extract_params_from_intent("初始值: 0xFF")
    assert p["init_value"] == "0xFF"


def test_enable_signal_with_strong_delimiter():
    """使能信号为 wr_en → enable=wr_en"""
    p = _extract_params_from_intent("使能信号为 wr_en，数据信号为 data_reg")
    assert p["enable"] == "wr_en"
    assert p["data"] == "data_reg"


def test_valid_ready_extraction():
    """valid 信号为 awvalid，ready 信号为 awready"""
    p = _extract_params_from_intent("valid 信号为 awvalid，ready 信号为 awready")
    assert p["valid"] == "awvalid"
    assert p["ready"] == "awready"


def test_valid_ready_case_insensitive():
    """VALID 信号 / Ready 信号 → 大小写无关"""
    p = _extract_params_from_intent("Valid 信号为 v_sig，READY 信号为 r_sig")
    assert p["valid"] == "v_sig"
    assert p["ready"] == "r_sig"


def test_state_sig_extraction():
    """状态信号为 cur_state → state_sig=cur_state（fsm_state_transition 模板）"""
    p = _extract_params_from_intent("状态信号为 cur_state，从 IDLE 到 ACTIVE")
    assert p["state_sig"] == "cur_state"


def test_start_end_event_extraction():
    """起始/应答信号为 X → start_event / end_event"""
    p = _extract_params_from_intent("起始信号为 req_sig，应答信号为 ack_sig")
    assert p["start_event"] == "req_sig"
    assert p["end_event"] == "ack_sig"


def test_target_extraction():
    """目标信号为 cnt_reg → target=cnt_reg（reset_behavior 模板）"""
    p = _extract_params_from_intent("复位释放后目标信号为 cnt_reg 应在 1 周期内归 0")
    assert p["target"] == "cnt_reg"


# ── 反例：避免误提取 ──────────────────────────────────────────────────────

def test_no_module_extraction_when_no_strong_pattern():
    """文本无"模块名为/是/:" → 不提取 module_name"""
    p = _extract_params_from_intent("做一个 FSM 状态转换覆盖率")
    assert "module_name" not in p


def test_enable_signal_narrative_extraction():
    """叙述式"使能 X 拉高/无效..."也提取 enable（v3.0 放宽：让 regex 接住更多
    narrative-Chinese case，不再独占 LLM step2 的负担）。"""
    p = _extract_params_from_intent("使能 wr_en 拉高时数据稳定")
    assert p["enable"] == "wr_en"


def test_enable_signal_narrative_with_invalid():
    """用户实际场景：当写使能 wr_en 无效时 → enable=wr_en"""
    p = _extract_params_from_intent("当写使能 wr_en 无效时，data_in 不会被意外修改")
    assert p["enable"] == "wr_en"


def test_no_max_cycles_when_no_unit():
    """N 没跟"周期"单位 → 不提取 max_cycles"""
    p = _extract_params_from_intent("发送 16 字节数据")
    assert "max_cycles" not in p


def test_empty_intent():
    """空字符串 → 返回空 dict"""
    p = _extract_params_from_intent("")
    assert p == {}


# ── 集成场景：完整 §1.x 用例输入 ──────────────────────────────────────────

def test_section_1_1_v3_full():
    """§1.1 v3 完整输入应正确提取 module_name；enable/data 因无 ASCII 标识符紧邻
    角色词（"使能"后是中文"无效"，"数据"后是中文"信号"），仍保持不提取，
    保留 LLM Step2 + signal-list role-hint 兜底机会。"""
    p = _extract_params_from_intent(
        "寄存器写保护场景的数据完整性断言：模块名为 reg_block，"
        "当写使能无效时数据信号不被意外修改"
    )
    assert p["module_name"] == "reg_block"
    # "写使能无效" / "数据信号不被" 后面紧邻的都是中文，叙述式 regex 需要 ASCII 标识符
    # 紧邻角色词才匹配，所以此处不会误提取
    assert "enable" not in p
    assert "data" not in p


def test_section_1_4_handshake_timeout_full():
    """§1.4 风格输入：完整提取 valid/ready/max_cycles/module_name"""
    p = _extract_params_from_intent(
        "模块: axi_slave，valid 信号为 awvalid，ready 信号为 awready，"
        "valid 拉高后 ready 必须在 16 周期内响应"
    )
    assert p["module_name"] == "axi_slave"
    assert p["valid"] == "awvalid"
    assert p["ready"] == "awready"
    assert p["max_cycles"] == 16


def test_section_1_6_timing_max_delay_full():
    """§1.6 风格输入：完整提取 start_event/end_event/max_delay"""
    p = _extract_params_from_intent(
        "模块名为 ack_engine，起始信号为 req_sig，应答信号为 ack_sig，"
        "请求发送后应答必须在 8 周期内返回"
    )
    assert p["module_name"] == "ack_engine"
    assert p["start_event"] == "req_sig"
    assert p["end_event"] == "ack_sig"
    assert p["max_delay"] == 8


# ── identifier sanitize 单元测试（test-bug #003 修复）────────────────────

from app.services.core.identifier import (
    IDENTIFIER_PARAMS,
    construct_group_name,
    is_sv_identifier,
    sanitize_sv_identifier,
)


def test_sanitize_legal_passthrough():
    """合法 identifier 直通，不改、不标 changed"""
    cleaned, changed = sanitize_sv_identifier("awvalid_awready_cov")
    assert cleaned == "awvalid_awready_cov"
    assert changed is False


def test_sanitize_chinese_only():
    """全中文 → 全部转 _ 后被去掉，加 fallback_prefix 前缀"""
    cleaned, changed = sanitize_sv_identifier("覆盖率组", fallback_prefix="group_name")
    assert changed is True
    assert is_sv_identifier(cleaned)
    assert cleaned == "group_name"   # 全非法时回退到纯前缀


def test_sanitize_mixed_chinese_and_ascii():
    """实战场景：'AXI valid-ready握手场景覆盖率' → 'AXI_valid_ready_cov' 风格"""
    cleaned, changed = sanitize_sv_identifier(
        "AXI valid-ready握手场景覆盖率", fallback_prefix="group_name"
    )
    assert changed is True
    assert is_sv_identifier(cleaned)
    # 中文/空格/连字符应统一变 _，多 _ 合并，去首尾 _
    assert cleaned == "AXI_valid_ready"


def test_sanitize_digits_first():
    """数字开头 → 加 fallback_prefix 前缀"""
    cleaned, changed = sanitize_sv_identifier("123abc", fallback_prefix="signal")
    assert changed is True
    assert is_sv_identifier(cleaned)
    assert cleaned == "signal_123abc"


def test_sanitize_empty_string():
    """空串 → 退化为 fallback_prefix 本身"""
    cleaned, changed = sanitize_sv_identifier("", fallback_prefix="module_name")
    assert changed is True
    assert cleaned == "module_name"


def test_sanitize_pure_punctuation():
    """纯标点 → 全部转 _ 被剥光 → 退化为 fallback_prefix"""
    cleaned, changed = sanitize_sv_identifier("---!!!", fallback_prefix="group_name")
    assert changed is True
    assert cleaned == "group_name"


def test_construct_group_name_from_module():
    """有合法 module_name → 优先 module_name + _cov"""
    result = {
        "module_name": {"value": "axi_master", "source": "regex"},
        "valid": {"value": "awvalid", "source": "llm"},
        "ready": {"value": "awready", "source": "llm"},
    }
    assert construct_group_name(result) == "axi_master_cov"


def test_construct_group_name_from_valid_ready():
    """无 module_name，有 valid+ready → valid_ready_cov"""
    result = {
        "valid": {"value": "awvalid", "source": "llm"},
        "ready": {"value": "awready", "source": "llm"},
    }
    assert construct_group_name(result) == "awvalid_awready_cov"


def test_construct_group_name_from_signal():
    """只有 signal → signal_cov"""
    result = {"signal": {"value": "cur_state", "source": "regex"}}
    assert construct_group_name(result) == "cur_state_cov"


def test_construct_group_name_skips_illegal_candidates():
    """候选自身不合法时跳过，不会用非法值拼接"""
    result = {
        "module_name": {"value": "中文模块", "source": "llm"},  # 非法，跳过
        "valid": {"value": "awvalid", "source": "llm"},
        "ready": {"value": "awready", "source": "llm"},
    }
    assert construct_group_name(result) == "awvalid_awready_cov"


def test_construct_group_name_returns_none_when_empty():
    """全无可用候选 → None，让调用方退到纯 sanitize"""
    assert construct_group_name({}) is None
    assert construct_group_name({"max_cycles": {"value": 8, "source": "regex"}}) is None


def test_identifier_params_match_frontend():
    """与 frontend/src/utils/validateParam.ts 的 SIGNAL_PARAM_NAMES 完全一致"""
    expected = {
        "enable", "data", "valid", "ready", "signal", "state_sig",
        "target", "start_event", "end_event", "module_name", "group_name",
        "clk", "rst", "rst_n",
        "from_state", "to_state",
    }
    assert set(IDENTIFIER_PARAMS) == expected


def test_sanitize_from_state_chinese():
    """from_state/to_state 也属于 IDENTIFIER_PARAMS，中文输入会被清洗。

    验证场景：FSM 模板 template_body 把 from_state/to_state 拼进 property 名，
    若用户/LLM 给中文枚举值，渲染会产生非法 SV，必须先 sanitize。
    """
    assert "from_state" in IDENTIFIER_PARAMS
    assert "to_state" in IDENTIFIER_PARAMS

    cleaned, changed = sanitize_sv_identifier("空闲状态", fallback_prefix="from_state")
    assert changed is True
    assert is_sv_identifier(cleaned)
    assert cleaned == "from_state"   # 全中文 → 退化为 fallback_prefix

    cleaned, changed = sanitize_sv_identifier("IDLE 状态", fallback_prefix="from_state")
    assert changed is True
    assert is_sv_identifier(cleaned)
    assert cleaned == "IDLE"          # 中英混排，保留 ASCII 部分


# ── _map_params_with_source sanitize 集成测试 ────────────────────────────

from app.services.core.pipeline import PipelineInput, _map_params_with_source


class _FakeTemplate:
    def __init__(self, parameters):
        self.parameters = parameters


# ── expr_validator 单元测试（metadata-driven 系统）─────────────────────

from app.services.core.expr_validator import (
    EXPR_TYPE_DISPATCH,
    validate_sv_bins_expr,
    validate_sv_boolean_expr,
    validate_sv_identifier_list,
)


def test_validate_sv_boolean_expr_legal():
    assert validate_sv_boolean_expr("awvalid && awready") is None
    assert validate_sv_boolean_expr("!busy || done") is None
    assert validate_sv_boolean_expr("(a == b) && (c < d)") is None


def test_validate_sv_boolean_expr_double_op():
    err = validate_sv_boolean_expr("awvalid && && ready")
    assert err is not None and "重复" in err


def test_validate_sv_boolean_expr_unbalanced_paren():
    err = validate_sv_boolean_expr("(a && b")
    assert err is not None and "括号" in err


def test_validate_sv_boolean_expr_chinese():
    err = validate_sv_boolean_expr("awvalid 且 awready")
    assert err is not None and "非法字符" in err


def test_validate_sv_identifier_list_legal():
    assert validate_sv_identifier_list("IDLE, FETCH, DECODE, EXECUTE") is None


def test_validate_sv_identifier_list_invalid_member():
    err = validate_sv_identifier_list("IDLE, 123BAD, EXECUTE")
    assert err is not None and "123BAD" in err


def test_validate_sv_identifier_list_too_short():
    err = validate_sv_identifier_list("IDLE")
    assert err is not None and "至少需要 2" in err


def test_validate_sv_bins_expr_legal():
    assert validate_sv_bins_expr("{0:255}") is None
    assert validate_sv_bins_expr("{1, 2, 4, 8, 16}") is None
    assert validate_sv_bins_expr("{[10:100], 200}") is None


def test_validate_sv_bins_expr_no_braces():
    err = validate_sv_bins_expr("0:255")
    assert err is not None and "{...}" in err


def test_validate_sv_bins_expr_illegal_char():
    err = validate_sv_bins_expr("{0:255, 中文}")
    assert err is not None and "非法字符" in err


def test_expr_type_dispatch_completeness():
    """EXPR_TYPE_DISPATCH 必须覆盖三个表达式类型"""
    assert "sv_boolean_expr" in EXPR_TYPE_DISPATCH
    assert "sv_identifier_list" in EXPR_TYPE_DISPATCH
    assert "sv_bins_expr" in EXPR_TYPE_DISPATCH


# ── pipeline dispatch 集成测试（expr_type vs fallback）───────────────────

def test_pipeline_dispatches_by_explicit_expr_type():
    """模板 parameters 声明 expr_type 时按 dispatch 走，不依赖参数名"""
    # 用一个不在 IDENTIFIER_PARAMS 白名单的参数名 'addr_bus' 配 expr_type=sv_identifier
    template = _FakeTemplate(parameters=[
        {"name": "addr_bus", "type": "string", "required": True,
         "expr_type": "sv_identifier"},  # ← 非白名单，但显式声明
    ])
    inp = PipelineInput(original_intent="dummy", code_type="assertion", signals=[])
    llm_mapping = {"addr_bus": "AXI 地址总线"}  # ← 中文非法值

    result = _map_params_with_source(template, inp, regex_mapping={}, llm_mapping=llm_mapping)

    # expr_type 透传到前端
    assert result["addr_bus"]["expr_type"] == "sv_identifier"
    # sanitize 命中（即使参数名不在 IDENTIFIER_PARAMS）
    assert is_sv_identifier(result["addr_bus"]["value"])
    assert result["addr_bus"]["sanitized"] is True


def test_pipeline_falls_back_to_identifier_params_for_legacy_templates():
    """旧模板没声明 expr_type，按 IDENTIFIER_PARAMS 白名单 fallback"""
    template = _FakeTemplate(parameters=[
        {"name": "valid", "type": "string", "required": True},  # 无 expr_type，但 valid ∈ IDENTIFIER_PARAMS
    ])
    inp = PipelineInput(original_intent="dummy", code_type="assertion", signals=[])
    llm_mapping = {"valid": "中文信号名"}

    result = _map_params_with_source(template, inp, regex_mapping={}, llm_mapping=llm_mapping)

    # 没声明 expr_type → meta 不带 expr_type 字段
    assert "expr_type" not in result["valid"]
    # 但因为名字在 IDENTIFIER_PARAMS，仍然 sanitize
    assert is_sv_identifier(result["valid"]["value"])
    assert result["valid"]["sanitized"] is True


def test_pipeline_skips_unknown_params_without_expr_type():
    """新参数名 + 无 expr_type → 不校验（保持后向兼容）"""
    template = _FakeTemplate(parameters=[
        {"name": "addr_bus", "type": "string", "required": True},  # 无 expr_type 且不在白名单
    ])
    inp = PipelineInput(original_intent="dummy", code_type="assertion", signals=[])
    llm_mapping = {"addr_bus": "AXI 地址总线"}

    result = _map_params_with_source(template, inp, regex_mapping={}, llm_mapping=llm_mapping)

    # 完全不动：没 sanitize、没 validation_error、没 expr_type
    assert result["addr_bus"]["value"] == "AXI 地址总线"
    assert "sanitized" not in result["addr_bus"]
    assert "validation_error" not in result["addr_bus"]
    assert "expr_type" not in result["addr_bus"]


def test_pipeline_validates_sv_boolean_expr():
    """expr_type=sv_boolean_expr 时 validator 触发，invalid 时打 validation_error 不修改值"""
    template = _FakeTemplate(parameters=[
        {"name": "condition", "type": "string", "required": True,
         "expr_type": "sv_boolean_expr"},
    ])
    inp = PipelineInput(original_intent="dummy", code_type="assertion", signals=[])
    llm_mapping = {"condition": "awvalid && && ready"}  # 双 &&

    result = _map_params_with_source(template, inp, regex_mapping={}, llm_mapping=llm_mapping)

    # 值不变（validator 不修改）
    assert result["condition"]["value"] == "awvalid && && ready"
    # 但带 validation_error
    assert "validation_error" in result["condition"]
    assert "重复" in result["condition"]["validation_error"]


def test_pipeline_sanitizes_sv_identifier_list():
    """expr_type=sv_identifier_list 时逐项 sanitize"""
    template = _FakeTemplate(parameters=[
        {"name": "state_list", "type": "string", "required": True,
         "expr_type": "sv_identifier_list"},
    ])
    inp = PipelineInput(original_intent="dummy", code_type="coverage", signals=[])
    llm_mapping = {"state_list": "IDLE, 中文状态, EXECUTE"}

    result = _map_params_with_source(template, inp, regex_mapping={}, llm_mapping=llm_mapping)

    # 中文项被 sanitize
    assert result["state_list"]["sanitized"] is True
    assert "中文" not in result["state_list"]["value"]
    # 其他合法项保留
    assert "IDLE" in result["state_list"]["value"]
    assert "EXECUTE" in result["state_list"]["value"]


def test_map_params_sanitizes_llm_chinese_group_name():
    """重现 test-bug #003：LLM 返回中文 group_name → 智能构造为 awvalid_awready_cov"""
    template = _FakeTemplate(parameters=[
        {"name": "group_name", "type": "string", "required": True, "description": "覆盖率组名"},
        {"name": "clk", "type": "string", "required": True, "default": "clk"},
        {"name": "rst_n", "type": "string", "required": True, "default": "rst_n"},
        {"name": "valid", "type": "string", "required": True, "role_hint": "valid"},
        {"name": "ready", "type": "string", "required": True, "role_hint": "ready"},
    ])
    inp = PipelineInput(
        original_intent="dummy",
        code_type="coverage",
        signals=[],
    )
    llm_mapping = {
        "group_name": "AXI valid-ready握手场景覆盖率",  # ← LLM 给的非法值
        "valid": "awvalid",
        "ready": "awready",
        "clk": "clk",
        "rst_n": "rst_n",
    }

    result = _map_params_with_source(template, inp, regex_mapping={}, llm_mapping=llm_mapping)

    # group_name 应该被智能构造为 awvalid_awready_cov（valid+ready 命中分支）
    assert is_sv_identifier(result["group_name"]["value"])
    assert result["group_name"]["value"] == "awvalid_awready_cov"
    assert result["group_name"]["sanitized"] is True
    # v2.11 契约反转后：系统经验式构造统一标 semantic_fallback（与"用户给"分开），
    # under_specified 闸据此判定为低置信源。
    assert result["group_name"]["source"] == "semantic_fallback"

    # 其他参数没动
    assert result["valid"]["value"] == "awvalid"
    assert result["ready"]["value"] == "awready"
    assert "sanitized" not in result["valid"]
    assert "sanitized" not in result["ready"]


def test_map_params_group_name_falls_back_to_sanitize_when_construct_fails():
    """group_name 中文 + 同伴信号也都非合法 ident → construct_group_name 返 None →
    回落到 sanitize_sv_identifier 兜底，仍生成合法 SV 名（不允许把"中文"原样落进
    covergroup 名让 simulator 报错）。"""
    template = _FakeTemplate(parameters=[
        {"name": "group_name", "type": "string", "required": True},
        {"name": "signal", "type": "string", "required": True, "role_hint": "data"},
    ])
    inp = PipelineInput(original_intent="dummy", code_type="coverage", signals=[])
    llm_mapping = {
        "group_name": "AXI握手覆盖",         # ← 非法
        "signal": "数据信号",                # ← 同伴信号也非合法 ident
    }

    result = _map_params_with_source(template, inp, regex_mapping={}, llm_mapping=llm_mapping)

    # 关键：value 必须是合法 SV identifier，不能是中文字面量。
    assert is_sv_identifier(result["group_name"]["value"]), \
        f"got non-legal SV id: {result['group_name']['value']!r}"
    assert result["group_name"]["sanitized"] is True
