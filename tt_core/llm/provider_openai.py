from __future__ import annotations

from dataclasses import dataclass

from tt_core.llm.policy import get_secret
from tt_core.llm.provider_base import LLMProvider


class OpenAIProviderError(RuntimeError):
    """Base exception for OpenAI provider failures."""


class OpenAIKeyMissingError(OpenAIProviderError):
    """Raised when no OpenAI API key is available in keyring."""


@dataclass(slots=True)
class OpenAIProvider(LLMProvider):
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1/chat/completions"
    timeout_seconds: float = 20.0

    def _api_key(self) -> str:
        api_key = get_secret("openai_api_key")
        if not api_key:
            raise OpenAIKeyMissingError(
                "OpenAI API key is not configured. Save it in Settings / Providers."
            )
        return api_key

    def generate(
        self,
        *,
        task: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency failure path
            raise OpenAIProviderError(
                "httpx is required for OpenAIProvider but is not installed."
            ) from exc

        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a localization model. Follow task constraints strictly. "
                        f"Task: {task}."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise OpenAIProviderError(f"OpenAI request failed: {exc}") from exc

        if response.status_code >= 400:
            body = response.text.strip()
            detail = body[:300] if body else "no response body"
            raise OpenAIProviderError(
                f"OpenAI request failed with HTTP {response.status_code}: {detail}"
            )

        try:
            payload_json = response.json()
            choices = payload_json.get("choices", [])
            first = choices[0]
            message = first.get("message", {})
            content = message.get("content", "")
        except Exception as exc:  # noqa: BLE001
            raise OpenAIProviderError("OpenAI response parsing failed.") from exc

        if not isinstance(content, str) or not content.strip():
            raise OpenAIProviderError("OpenAI response did not include text content.")
        return content.strip()

