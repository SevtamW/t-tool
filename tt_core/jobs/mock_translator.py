from __future__ import annotations


def mock_translate(source_text: str, target_locale: str) -> str:
    return f"[{target_locale}] {source_text}"

