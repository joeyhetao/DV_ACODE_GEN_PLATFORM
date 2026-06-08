from __future__ import annotations
import html
import re
from abc import ABC, abstractmethod
from app.schemas.intent import TemplateSelectionOutput


# FEAT-11 Stage 2：llm_direct 兜底接受 ```systemverilog / ```sv / ```verilog 三种围栏。
# 模型有时漏写 lang，也兼容裸 ```。DOTALL 让 `.` 跨行；非贪婪 `.*?` 截到首个闭合 ```。
# 放在 base.py 让两实现共用，避免 prompt / 解析逻辑漂移。
_SV_FENCE_RE = re.compile(
    r"```(?:systemverilog|sv|verilog)?\s*\n?(.*?)\n?```",
    re.DOTALL | re.IGNORECASE,
)


def extract_sv_code_block(text: str) -> str:
    """从 LLM 自由文本中提取**单个**SystemVerilog 代码块；找不到则抛 ValueError("no_sv_code_block")。

    提取规则：第一个 ```systemverilog / ```sv / ```verilog（lang 可省略）开头、
    最近的 ``` 闭合。围栏外的 prose 一律丢弃。空内容也算无效。

    上游 (endpoint) 捕 ValueError 翻译为 HTTP 422 detail.type='llm_direct_no_code'。
    """
    match = _SV_FENCE_RE.search(text or "")
    if not match:
        raise ValueError("no_sv_code_block")
    body = match.group(1).strip()
    if not body:
        raise ValueError("no_sv_code_block")
    return body


def build_freeform_prompt(
    intent: str,
    code_type: str,
    signals: list[dict] | None,
    clk: str,
    rst: str,
) -> tuple[str, str]:
    """FEAT-11 Stage 2：构造 freeform 生成的 (system, user) 提示。

    硬约束：单个 systemverilog 围栏，前后零 prose。模型不遵守 → 提取层 422 兜底。
    两 LLM 实现（Anthropic / OpenAI-compat）共用此函数避免 prompt 漂移。
    """
    signal_lines = (
        "\n".join(
            f"  - {s.get('name', '?')} [width={s.get('width', 1)}] role={s.get('role', 'other')}"
            for s in (signals or [])
        )
        or "  （用户未提供信号列表）"
    )
    system = (
        "你是资深 IC 验证工程师。根据用户描述直接生成 SystemVerilog 验证代码。\n"
        "硬性输出约束：\n"
        "1. 只输出一个 ```systemverilog ... ``` 代码块，**前后不得有任何说明性文字**。\n"
        "2. 代码必须语法可编译；不要使用 // TODO 或留空函数体。\n"
        "3. 时钟与复位信号严格使用用户给定的名称。\n"
        "4. 若用户描述信息不足以确定细节，按合理默认补全，不要中断输出。"
    )
    user = (
        f"[代码类型]\n{code_type}\n\n"
        f"[时钟] {clk}\n[复位] {rst}\n\n"
        f"[信号列表]\n{signal_lines}\n\n"
        f"[用户描述]\n{intent}\n\n"
        f"只输出一个 ```systemverilog 围栏的代码块。"
    )
    return system, user


# lib_manager.py import 时把 differentiators / non_use_cases 拼到 description 末尾
# （"区别要点：..."、"不适用场景：..."），实测最长 812 char（protocol_handshake_coverage）。
# 截断设到 1000 留余量避免 non_use_cases 末项被切；若 lib_manager 拼接逻辑变动可在此调。
_CANDIDATE_DESC_MAX_LEN = 1000


def render_step1_candidate_xml(
    c: dict,
    extra_lines: list[str] | None = None,
) -> str:
    """Step1 候选 XML 块渲染（OpenAI-compat / Anthropic 共用，FEAT-14）。

    输出形如：
        <candidate id="sva_handshake_timeout_v1" name="Handshake Timeout">
        描述：xxx
        参数：a, b, c     ← 可选 extra_lines
        </candidate>

    安全：id / name 属性值与正文一律走 html.escape——template 字段（尤其 name 是
    String(128) 自由文本）若含 `"` / `</candidate>` / `>` 等字符会破坏 XML 结构
    并诱发 prompt 注入（review SEC-1）。description 截断到 _CANDIDATE_DESC_MAX_LEN。

    extra_lines 用于 Anthropic 路径追加"参数：xxx"等附加信息行；OpenAI-compat 不传。
    本函数对每条 extra line 做正文级 escape（quote=False，只转 `<>&`，保留中文 / 标点
    可读），并把内嵌 `\\n` 替换为空格做防御性清洗——caller（如 Anthropic 的 _format_params）
    通常来自 DB dict，不强类型，存在低概率参数名含 `\\n` 的情况；若不清洗，`\\n".join()`
    会把违规行拆成额外正文行、破坏"描述 → 参数 → </candidate>"的顺序契约（review M-1）。
    """
    safe_id = html.escape(c["template_id"], quote=True)
    safe_name = html.escape(c.get("name") or "", quote=True)
    desc = html.escape((c.get("description") or "")[:_CANDIDATE_DESC_MAX_LEN], quote=False)
    body_lines = [f"描述：{desc}"]
    for line in extra_lines or []:
        # 防御 caller 违约：把内嵌换行替换为空格，避免破坏 XML 块结构
        body_lines.append(html.escape(line.replace("\n", " "), quote=False))
    body = "\n".join(body_lines)
    return f'<candidate id="{safe_id}" name="{safe_name}">\n{body}\n</candidate>'


def resolve_numeric_fallback(
    raw: str,
    candidates: list[dict],
    log_prefix: str,
) -> str | None:
    """LLM step1 数字兜底（FEAT-14）：把 '3' / '3.' / '"3"' / ' 3 ' 等序号字符串
    映射回 candidates[N-1].template_id。

    剥离链：strip → 去配对的 ASCII 引号 → 去尾部句号 → 再 strip。N 取值
    1..len(candidates)；N=0 或 N>len 视为越界，返回 None 让 caller 走原 fallback。
    非数字字符串（含中文"三"、'3 (我选的)' 这类带噪声形式）一律 None。日志前缀
    与历史 [GLM Step1] / [Anthropic Step1] 对齐，便于线上日志排障。
    """
    stripped = (raw or "").strip().strip('"\'').rstrip('.').strip()
    if stripped.isdigit():
        n = int(stripped)
        if 1 <= n <= len(candidates):
            resolved = candidates[n - 1]["template_id"]
            print(
                f"[{log_prefix}] raw was integer {n} → resolved to {resolved!r}",
                flush=True,
            )
            return resolved
    return None


class LLMClient(ABC):
    @abstractmethod
    async def normalize_intent(self, original_intent: str, rules: str) -> str:
        ...

    @abstractmethod
    async def select_template(
        self,
        normalized_intent: str,
        signal_context: str,
        candidates: list[dict],
        original_intent: str = "",
    ) -> TemplateSelectionOutput:
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        """通用多轮对话接口（v3.0 IntentBuilder + 贡献机制 LLM 反推 parameters 用）。

        messages 格式与 OpenAI / Anthropic SDK 一致：[{role: "system"|"user"|"assistant", content: str}, ...]
        实现要求：
        - temperature 默认沿用 client 自身配置（temperature=0 一致性）
        - 不打 thinking 开关（caller 可自行决定，但默认关——多轮对话不需要 reasoning_tokens）
        - 返回 assistant 文本内容
        """
        ...

    @abstractmethod
    async def test_basic(self) -> str:
        ...

    @abstractmethod
    async def generate_code_freeform(
        self,
        intent: str,
        code_type: str,
        signals: list[dict],
        clk: str,
        rst: str,
    ) -> str:
        """FEAT-11 Stage 2 llm_direct 兜底：让 LLM 完全自由生成 SystemVerilog 代码。

        与 select_template + Jinja2 渲染的确定性路径不同——本方法**显式接受非确定性**：
        同一 intent 多次调用允许返回不同代码，作为"用户对 RAG 输出不满意"的逃生通道。

        实现约束（子类必须遵守）：
        - temperature=0（控制变量；非确定性来自模型本身的采样，不来自调用层）
        - prompt 必须明确要求输出**单个**且**唯一**的 fenced 代码块（systemverilog / sv / verilog 任一）；
          实现层负责正则提取 fenced 内容
        - 提取失败（无 fenced block / 多个不连续 block / prose 主导）→ raise ValueError("no_sv_code_block")
        - 返回 str 必须是裸代码（已去掉 ``` 围栏）

        参数：
        - intent: 用户原始描述（不用 normalize 后的版本——原文信号名更稳）
        - code_type: 'assertion' / 'coverage' / ... ; 用于 prompt 提示生成何种代码
        - signals: 来自 PipelineInput.signals 的 list[dict]，每项 {name, width, role}；
          可空（user 没填）
        - clk / rst: 时钟与复位信号名
        """
        ...

    async def verify_step1_selection(
        self,
        normalized_intent: str,
        selected_template_id: str,
        candidates: list[dict],
    ) -> bool:
        """A8：对 step1 已选模板做一次 yes/no 二次验证。

        默认实现返 True（即"接受 step1 选择"），适用于 anthropic_client 等还未实现
        本逻辑的客户端 —— 让 pipeline 的二次验证调用安全无副作用。仅 openai_compat
        重写为真实 LLM 调用。

        约束（子类实现需要遵守）：
          - max_tokens 极小（如 16），输出限制为 "yes" / "no" 单词
          - thinking 必须 disabled（一致性 + 延迟 < 1s 才有意义）
          - 任何解析失败 / 异常都应当 return True（fail-open）：A8 是辅助闸，
            不能把 LLM 二次验证自身的脆弱性变成新的误拒来源。
        """
        return True
