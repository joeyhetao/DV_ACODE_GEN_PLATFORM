"""v3.0 贡献机制 LLM 反推 parameters。

输入：用户提交的 demo_code（含真实信号名/字面量）+ description + code_type
输出：parameter_defs JSON / jinja_body / keywords / subcategory / protocol

流程：
1. LLM 一次性结构化输出（要求 LLM 返合法 JSON）
2. 自动校验（3 道）：
   a. Jinja2 用占位值能 render（不报 StrictUndefined）
   b. parameter_defs 字段命名合法（无中文 / 无特殊字符 / expr_type 都声明）
   c. keywords 合法（list[str]，非空字符串）
3. 任一失败抛 ContributionParseError，端点返 422

参考已有 `app/services/core/identifier.py` 的合法 SV ident 判定。
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment, SecurityError

from app.services.core.identifier import is_sv_identifier
from app.services.llm.base import LLMClient


_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_VALID_EXPR_TYPES = {
    "sv_identifier", "sv_identifier_list",
    "sv_boolean_expr", "sv_bins_expr",
    "integer", "free_text",
}

# P1-5：LLM 可能反推出 `always` / `module` 等参数名 → 通过格式检查但生成的 SV 代码非法。
# Python 关键字（如 `class` / `for`）作参数名也可能让 Jinja2 渲染时撞 Python 内置类型导致诡异错误。
# 黑名单合并 SV 常见关键字 + 完整 Python 关键字。
_SV_RESERVED = {
    # 行为语句
    "always", "always_comb", "always_ff", "always_latch",
    "assign", "begin", "end", "case", "casex", "casez", "default",
    "endcase", "if", "else", "for", "while", "do", "break", "continue",
    "return", "function", "endfunction", "task", "endtask",
    # 模块/接口
    "module", "endmodule", "interface", "endinterface", "package", "endpackage",
    "import", "export", "extern", "automatic", "static",
    # 数据类型 / 修饰符
    "logic", "wire", "reg", "bit", "byte", "int", "integer", "longint", "shortint",
    "real", "shortreal", "string", "void", "input", "output", "inout",
    "signed", "unsigned", "const", "ref", "var", "type", "typedef",
    "struct", "union", "enum", "class", "endclass", "virtual", "pure",
    # SVA 关键字
    "assert", "assume", "cover", "expect", "property", "endproperty",
    "sequence", "endsequence", "disable", "iff", "throughout", "within", "intersect",
    "first_match", "and", "or", "not", "implies",
    # 覆盖率
    "covergroup", "endgroup", "coverpoint", "cross", "bins", "illegal_bins",
    "ignore_bins", "wildcard",
    # 系统/编译指令前缀片段（保守）
    "posedge", "negedge", "edge", "wait", "fork", "join",
    "initial", "final", "generate", "endgenerate", "genvar",
    "parameter", "localparam", "specify", "endspecify",
    "force", "release", "deassign",
}


def _is_reserved_keyword(name: str) -> bool:
    """name 是否撞 SV 或 Python 关键字。"""
    import keyword as _py_keyword
    return name in _SV_RESERVED or _py_keyword.iskeyword(name)


class ContributionParseError(ValueError):
    """LLM 反推 parameters 失败——三道校验之一不过。端点应转 422。"""
    def __init__(self, reason: str, stage: str = "unknown"):
        self.reason = reason
        self.stage = stage
        super().__init__(f"[{stage}] {reason}")


@dataclass
class ExtractedParameters:
    """LLM 反推产出，端点拿去填 Contribution 入库。"""
    parameter_defs: list[dict]      # [{name, type, required, description, expr_type, default?}, ...]
    jinja_body: str                 # 用 {{ param }} 占位真实信号的 Jinja2 模板
    keywords: list[str]
    subcategory: str | None
    protocol: str | None


def _build_extraction_prompt(demo_code: str, description: str, code_type: str) -> str:
    """LLM 反推 prompt——结构化输出 JSON。让 LLM 把 demo_code 里的字面信号名换成 {{ placeholder }}。"""
    return (
        "你是 IC 验证模板库管理员。下面有一份用户贡献的 SystemVerilog 代码示例与场景描述，"
        "请把代码里的具体信号名 / 字面量改写成 Jinja2 占位符 {{ param }}，并整理出参数列表。\n\n"
        f"### 代码类型\n{code_type}\n\n"
        f"### 场景描述\n{description}\n\n"
        f"### 代码示例\n```systemverilog\n{demo_code}\n```\n\n"
        "### 任务\n"
        "1. 找出代码里所有应该参数化的位置（信号名、状态枚举值、位宽常量、超时周期数等）\n"
        "2. 用 {{ snake_case_name }} 占位符替换它们，生成 jinja_body\n"
        "3. 给每个参数填元数据：name / type / required / description / expr_type / default\n"
        "4. 推测 keywords（中英文混合，2-5 个）/ subcategory / protocol\n\n"
        "### 严格约束\n"
        "- 参数 name 必须是小写蛇形（[a-z][a-z0-9_]*），不允许中文 / 大写 / 特殊字符\n"
        "- expr_type 只能是：sv_identifier / sv_identifier_list / sv_boolean_expr / sv_bins_expr / integer / free_text\n"
        "- 时钟参数命名 clk，复位参数命名 rst_n，都设 default=参数名本身\n"
        "- 不要发明用户代码里没有的参数；不要漏掉用户代码里的字面信号名\n\n"
        "### 输出格式（必须严格遵守）\n"
        "返回一段 JSON（**只返 JSON，不要任何解释文字**），结构如下：\n"
        "```json\n"
        "{\n"
        '  "parameter_defs": [\n'
        '    {"name": "clk", "type": "string", "required": true, "description": "时钟", '
        '"expr_type": "sv_identifier", "default": "clk"},\n'
        '    {"name": "signal", "type": "string", "required": true, "description": "被检查信号", '
        '"expr_type": "sv_identifier"}\n'
        "  ],\n"
        '  "jinja_body": "module {{ module_name }};\\n  ...\\nendmodule",\n'
        '  "keywords": ["握手", "handshake", "AXI"],\n'
        '  "subcategory": "handshake",\n'
        '  "protocol": "AXI4"\n'
        "}\n"
        "```\n"
    )


def _extract_json_block(text: str) -> dict:
    """从 LLM 回复抽 JSON（容忍前后散文 / 容忍 ```json 包裹）。失败抛 ContributionParseError。"""
    if not text.strip():
        raise ContributionParseError("LLM 返空", stage="llm_response")
    # 优先匹配 ```json ... ``` 代码块
    block_re = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    m = block_re.search(text)
    raw = m.group(1) if m else text
    # 再尝试找第一个 { 到最后一个 }
    if not m:
        first = raw.find("{")
        last = raw.rfind("}")
        if first == -1 or last == -1 or last < first:
            raise ContributionParseError(f"LLM 输出未含 JSON 对象：{text[:200]}", stage="json_locate")
        raw = raw[first:last + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ContributionParseError(f"JSON 解析失败: {e}", stage="json_parse") from e


def _validate_parameter_defs(parameter_defs) -> None:
    """校验 parameter_defs 字段命名合法 / expr_type 在白名单。失败抛 ContributionParseError。"""
    if not isinstance(parameter_defs, list):
        raise ContributionParseError(
            f"parameter_defs 必须是 list，实际 {type(parameter_defs).__name__}",
            stage="param_defs_shape",
        )
    if not parameter_defs:
        raise ContributionParseError(
            "parameter_defs 为空——LLM 没识别出任何可参数化的位置",
            stage="param_defs_empty",
        )
    seen_names = set()
    for i, p in enumerate(parameter_defs):
        if not isinstance(p, dict):
            raise ContributionParseError(
                f"parameter_defs[{i}] 不是 dict",
                stage="param_defs_shape",
            )
        name = p.get("name")
        if not name or not isinstance(name, str):
            raise ContributionParseError(
                f"parameter_defs[{i}] name 缺失或非字符串",
                stage="param_defs_name",
            )
        if not _VALID_NAME_RE.match(name):
            raise ContributionParseError(
                f"参数名 {name!r} 非法（必须小写蛇形 [a-z][a-z0-9_]*）",
                stage="param_defs_name",
            )
        if not is_sv_identifier(name):
            raise ContributionParseError(
                f"参数名 {name!r} 不是合法 SV 标识符",
                stage="param_defs_name",
            )
        if _is_reserved_keyword(name):
            # P1-5：拦 SV / Python 关键字——避免 Jinja2 渲染产出 `module module;` 这种非法 SV
            raise ContributionParseError(
                f"参数名 {name!r} 撞 SystemVerilog 或 Python 关键字，请换个名字",
                stage="param_defs_name",
            )
        if name in seen_names:
            raise ContributionParseError(
                f"参数名 {name!r} 重复",
                stage="param_defs_name",
            )
        seen_names.add(name)
        # expr_type 校验
        expr_type = p.get("expr_type")
        if expr_type and expr_type not in _VALID_EXPR_TYPES:
            raise ContributionParseError(
                f"参数 {name} 的 expr_type={expr_type!r} 不在白名单 {sorted(_VALID_EXPR_TYPES)}",
                stage="param_defs_expr_type",
            )


def _validate_jinja_rendering(jinja_body: str, parameter_defs: list[dict]) -> None:
    """用占位值跑一次 Jinja2 渲染，确认：
    1. 没有 StrictUndefined 报错（即 jinja_body 引用的所有 {{ var }} 都在 parameter_defs 里有定义）
    2. 不含 SSTI payload（用 SandboxedEnvironment 阻断 __class__ / __bases__ / 危险 builtin）

    v3.0 P0-2：LLM 反推的 jinja_body 直接来自外部输入，必须沙箱化。
    失败抛 ContributionParseError。
    """
    if not jinja_body.strip():
        raise ContributionParseError("jinja_body 为空", stage="jinja_empty")
    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
    try:
        tmpl = env.from_string(jinja_body)
    except TemplateError as e:
        raise ContributionParseError(f"Jinja2 语法错误：{e}", stage="jinja_syntax") from e
    # 用每个 parameter 填 "x" 跑一次渲染；
    # - jinja_body 引用了未声明的 var → UndefinedError
    # - jinja_body 含 SSTI payload → SecurityError (sandbox 阻断)
    placeholder_values = {p["name"]: "x" for p in parameter_defs}
    try:
        tmpl.render(**placeholder_values)
    except SecurityError as e:
        raise ContributionParseError(
            f"模板含禁止的不安全操作（可能是 SSTI payload）：{e}",
            stage="jinja_sandbox",
        ) from e
    except TemplateError as e:
        raise ContributionParseError(
            f"Jinja2 渲染失败（可能引用了未声明的参数）：{e}",
            stage="jinja_render",
        ) from e


def _validate_keywords(keywords) -> list[str]:
    """keywords 必须是 list[str]，去重 / 过滤空字符串。失败抛 ContributionParseError。"""
    if keywords is None:
        return []
    if not isinstance(keywords, list):
        raise ContributionParseError(
            f"keywords 必须是 list，实际 {type(keywords).__name__}",
            stage="keywords_shape",
        )
    cleaned = []
    for k in keywords:
        if isinstance(k, str) and k.strip():
            cleaned.append(k.strip())
    # 去重保序
    seen = set()
    out = []
    for k in cleaned:
        if k not in seen:
            out.append(k)
            seen.add(k)
    return out


async def derive_parameters_from_demo(
    demo_code: str,
    description: str,
    code_type: str,
    llm: LLMClient,
) -> ExtractedParameters:
    """主入口：LLM 反推 + 3 道校验。失败抛 ContributionParseError 让端点返 422。

    成功返回 ExtractedParameters，端点直接拿来填 Contribution 入库。
    """
    if not demo_code.strip():
        raise ContributionParseError("demo_code 为空", stage="input")
    if not description.strip():
        raise ContributionParseError("description 为空", stage="input")

    prompt = _build_extraction_prompt(demo_code, description, code_type)
    messages = [
        {"role": "system", "content": "你是 IC 验证模板库管理员，专门把贡献者的代码示例规范化为模板。"},
        {"role": "user", "content": prompt},
    ]
    raw = await llm.chat(messages, max_tokens=2048)
    parsed = _extract_json_block(raw)

    # 取字段（缺失给默认）
    parameter_defs = parsed.get("parameter_defs", [])
    jinja_body = parsed.get("jinja_body", "")
    keywords = parsed.get("keywords", [])
    subcategory = parsed.get("subcategory") or None
    protocol = parsed.get("protocol") or None

    # 3 道校验（任一失败抛）
    _validate_parameter_defs(parameter_defs)
    _validate_jinja_rendering(jinja_body, parameter_defs)
    cleaned_keywords = _validate_keywords(keywords)

    return ExtractedParameters(
        parameter_defs=parameter_defs,
        jinja_body=jinja_body,
        keywords=cleaned_keywords,
        subcategory=subcategory if isinstance(subcategory, str) else None,
        protocol=protocol if isinstance(protocol, str) else None,
    )
