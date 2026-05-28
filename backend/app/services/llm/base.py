from __future__ import annotations
from abc import ABC, abstractmethod
from app.schemas.intent import TemplateSelectionOutput


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
