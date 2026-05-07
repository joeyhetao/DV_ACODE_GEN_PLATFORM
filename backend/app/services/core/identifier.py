"""SystemVerilog 标识符规范化兜底层。

防御性清洗：无论参数从 LLM Step2 / 正则 / signal_list / default / placeholder 哪一层来，
最后统一过一遍，确保 IDENTIFIER_PARAMS 中的参数永远是合法 SV 标识符。

与前端 frontend/src/utils/validateParam.ts 的 SIGNAL_PARAM_NAMES 严格对齐。
"""
from __future__ import annotations
import re

_SV_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

# IDENTIFIER_PARAMS：旧模板未声明 expr_type 时的 fallback 白名单。
#
# Metadata-driven 体系下首选是模板 YAML 的 parameters[].expr_type 字段——
# 当前路径见 pipeline._map_params_with_source 末尾的 sanitize pass。本集合
# 仅作为"模板没声明 expr_type"的兜底：若参数名在此集合内，按 sv_identifier 处理；
# 否则跳过（保持 #003 修复前的行为，不破坏后向兼容）。
#
# 严格对齐 frontend/src/utils/validateParam.ts 的 SIGNAL_PARAM_NAMES。
# 团队加新模板时建议直接在 YAML 声明 expr_type，避免再扩这个集合。
IDENTIFIER_PARAMS: frozenset[str] = frozenset({
    "enable", "data", "valid", "ready", "signal", "state_sig",
    "target", "start_event", "end_event", "module_name", "group_name",
    "clk", "rst", "rst_n",
    # FSM 状态枚举值，在 template_body 里既参与 property 名拼接又参与状态值比较，
    # 实际就是 SV 标识符——和 SIGNAL_PARAM_NAMES 前后端契约保持一致
    "from_state", "to_state",
})

_MAX_LEN = 64  # 保守上限；SV LRM 允许 1024，但太长在工具链里到处翻车


def is_sv_identifier(value) -> bool:
    """检查给定值是否已经是合法 SV 标识符（不修改，仅判断）。"""
    if not isinstance(value, str):
        return False
    return bool(_SV_IDENT_RE.match(value)) and len(value) <= _MAX_LEN


def sanitize_sv_identifier(value: str, fallback_prefix: str = "id") -> tuple[str, bool]:
    """把任意字符串规范化为合法 SystemVerilog 标识符。

    返回 (cleaned, changed)：
      - cleaned：合法 identifier
      - changed：True 表示进行了清洗（前端可据此显示"已自动规范化"）

    清洗规则：
      1. 已合法 → 原样返回
      2. 非 [A-Za-z0-9_] 字符 → '_'
      3. 连续 '_' 合并为单个 '_'
      4. 去首尾 '_'
      5. 首字符不是字母/下划线 → 加 fallback_prefix 前缀
      6. 长度截断到 _MAX_LEN
    """
    if not isinstance(value, str):
        value = str(value)

    if _SV_IDENT_RE.match(value) and len(value) <= _MAX_LEN:
        return value, False

    cleaned = re.sub(r'[^A-Za-z0-9_]', '_', value)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')

    if not cleaned or not re.match(r'[A-Za-z_]', cleaned):
        cleaned = f"{fallback_prefix}_{cleaned}".rstrip('_') if cleaned else fallback_prefix

    cleaned = cleaned[:_MAX_LEN]
    return cleaned, True


def construct_group_name(result: dict[str, dict]) -> str | None:
    """从已填好的其他参数构造一个有意义的 group_name。

    优先级：
      1. f"{module_name}_cov"
      2. f"{valid}_{ready}_cov"
      3. f"{signal}_cov"
      4. None（让调用方退到纯 sanitize）

    每个候选都必须自己也是合法 identifier，否则跳过。
    """
    def _legal(name: str) -> str | None:
        meta = result.get(name)
        if not meta:
            return None
        v = str(meta.get("value", ""))
        return v if _SV_IDENT_RE.match(v) else None

    module_name = _legal("module_name")
    if module_name:
        return f"{module_name}_cov"[:_MAX_LEN]

    valid = _legal("valid")
    ready = _legal("ready")
    if valid and ready:
        return f"{valid}_{ready}_cov"[:_MAX_LEN]

    signal = _legal("signal")
    if signal:
        return f"{signal}_cov"[:_MAX_LEN]

    return None
