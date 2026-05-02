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


def test_no_signal_extraction_when_no_strong_delimiter():
    """文本无"使能信号为 X" 强分隔，仅有"使能 X" → 不提取 enable（避免误伤）"""
    p = _extract_params_from_intent("使能 wr_en 拉高时数据稳定")
    # 弱模式不应触发：保留 LLM Step2 + signal-list role-hint 的机会
    # 仅当用户写"使能信号为 X"或"使能为 X"时才提取
    assert "enable" not in p


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
    """§1.1 v3 完整输入应正确提取 module_name"""
    p = _extract_params_from_intent(
        "寄存器写保护场景的数据完整性断言：模块名为 reg_block，"
        "当写使能无效时数据信号不被意外修改"
    )
    assert p["module_name"] == "reg_block"
    # enable / data 不在文本里强结构，依赖 signal-list role-hint，符合 §1 章首约定
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
