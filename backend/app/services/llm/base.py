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
