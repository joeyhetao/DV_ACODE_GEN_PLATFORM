"""SV 表达式语法校验（轻量手写状态机，无外部依赖）。

覆盖三种 SV 表达式语法的格式校验：
  - sv_boolean_expr   : `awvalid && ready`、`!busy || done`、`(a == b)`
  - sv_identifier_list: `IDLE, FETCH, DECODE`
  - sv_bins_expr      : `{0:255}`、`{1, 2, 4, 8}`、`{[10:100], 200}`

每个 validator 接口统一为 `validate(value: str) -> str | None`：
  - None  → 校验通过
  - 字符串 → 错误描述（可直接显示给用户）

设计原则：只校验"该字符串能否塞进 template_body 渲染成合法 SV 代码"，
不做语义校验（比如"signal 在 module port 里有没有声明"）。
"""
from __future__ import annotations
import re

# 单一 SV 标识符（与 identifier._SV_IDENT_RE 对齐）
_SV_IDENT = r'[A-Za-z_][A-Za-z0-9_]*'


def validate_sv_boolean_expr(value: str) -> str | None:
    """SV 布尔表达式：标识符 + 逻辑/比较/位算子 + 括号。

    允许字符集：字母、数字、下划线、`! & | ( ) = < > ~ + - *`、空白、`'` `.`（成员访问与字面量）。
    额外检查：括号配对、不出现重复算子（`&&&&` / `||||`）。
    """
    if not isinstance(value, str) or not value.strip():
        return "表达式不能为空"

    # 1. 字符集
    if not re.fullmatch(r"[A-Za-z0-9_!&|()=<>~+\-*\s'.]+", value):
        return "包含非法字符（仅允许 SV 标识符与逻辑/比较/位算子 ! && || == != < > ~ + - * 与括号）"

    # 2. 括号配对
    depth = 0
    for ch in value:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return "括号不配对（出现多余的右括号）"
    if depth != 0:
        return "括号不配对（左右括号数量不一致）"

    # 3. 重复算子（`&& &&` / `|| ||` / `&&&` / `|||` 等典型 LLM 错误）
    if re.search(r'&&\s*&&|\|\|\s*\|\||&&&|\|\|\|', value):
        return "包含重复的逻辑算子"

    # 4. 至少含一个标识符（不能是纯算子/括号）
    if not re.search(_SV_IDENT, value):
        return "表达式中未发现任何信号名"

    return None


def validate_sv_identifier_list(value: str) -> str | None:
    """逗号分隔的 SV 标识符列表（覆盖率模板的 state_list）。

    例：`IDLE, FETCH, DECODE, EXECUTE`
    """
    if not isinstance(value, str) or not value.strip():
        return "状态列表不能为空"

    parts = [p.strip() for p in value.split(',') if p.strip()]
    if not parts:
        return "至少需要一个枚举值"
    if len(parts) < 2:
        return "状态列表至少需要 2 个枚举值"

    for p in parts:
        if not re.fullmatch(_SV_IDENT, p):
            return f"枚举值 '{p}' 不是合法 SV 标识符（字母/下划线开头，仅字母/数字/下划线）"
    return None


def validate_sv_bins_expr(value: str) -> str | None:
    """SV bins 表达式：必须用 `{...}` 包裹，内部为数字/范围/十六进制/标识符 + 逗号。

    例：`{0:255}`、`{1, 2, 4, 8, 16}`、`{[10:100], 200}`、`{IDLE, ACTIVE}`
    """
    if not isinstance(value, str) or not value.strip():
        return "bins 表达式不能为空"

    s = value.strip()
    if not (s.startswith('{') and s.endswith('}')):
        return "必须用 {...} 包裹"

    inner = s[1:-1].strip()
    if not inner:
        return "{} 内部不能为空"

    # 内部允许：标识符、十进制、十六进制（`'h..` / `0x..`）、范围 N:M、`[N:M]`、逗号、空白
    # 注：单引号是 SV 进制字面量前缀（如 `8'hFF`）
    if not re.fullmatch(r"[A-Za-z0-9_'\s,:\[\]]+", inner):
        return "内部包含非法字符（仅允许标识符、数字、十六进制、范围 N:M、`[...]` 与逗号）"

    # 中括号配对
    if inner.count('[') != inner.count(']'):
        return "中括号 [ ] 不配对"

    return None


# expr_type → validator 函数的统一分发表
EXPR_TYPE_DISPATCH: dict[str, callable] = {
    "sv_boolean_expr": validate_sv_boolean_expr,
    "sv_identifier_list": validate_sv_identifier_list,
    "sv_bins_expr": validate_sv_bins_expr,
}
