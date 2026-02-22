from __future__ import annotations

from tt_core.llm.provider_base import LLMProvider


class MockProvider(LLMProvider):
    def __init__(self, *, model: str = "mock-v1") -> None:
        self.model = model

    def generate(
        self,
        *,
        task: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        del temperature
        del max_tokens
        return f"[{task}] {prompt[:200]}"

