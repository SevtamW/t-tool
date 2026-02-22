from __future__ import annotations

from hashlib import sha256
import re

_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_source_text(text: str) -> str:
    collapsed = _WHITESPACE_PATTERN.sub(" ", text.strip())
    return collapsed.lower()


def normalized_source_hash(text: str) -> str:
    normalized = normalize_source_text(text)
    return sha256(normalized.encode("utf-8")).hexdigest()
