from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def generate(
        self,
        *,
        task: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate plain-text output for an LLM task."""

