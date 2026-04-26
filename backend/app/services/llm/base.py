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
    ) -> TemplateSelectionOutput:
        ...

    @abstractmethod
    async def test_basic(self) -> str:
        ...
