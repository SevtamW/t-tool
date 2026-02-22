from __future__ import annotations

from tt_core.llm.provider_base import LLMProvider


class LocalProviderStub(LLMProvider):
    def __init__(self, *, model: str = "local-stub-v1") -> None:
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
        return f"[local:{task}] {prompt[:200]}"

