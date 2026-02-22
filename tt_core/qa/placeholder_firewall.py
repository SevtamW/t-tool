from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re


@dataclass(slots=True, frozen=True)
class Placeholder:
    type: str
    value: str
    start: int | None = None
    end: int | None = None
    token: str = ""


@dataclass(slots=True, frozen=True)
class ProtectedText:
    original: str
    protected: str
    placeholders: list[Placeholder]
    token_map: dict[str, str]


_PLACEHOLDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("double_curly", re.compile(r"\{\{[^{}\r\n]+\}\}")),
    ("angle_tag", re.compile(r"</?(?:b|i|color|size)\b[^>]*>|<sprite\b[^>]*>", re.IGNORECASE)),
    ("curly", re.compile(r"\{(?:\d+|[A-Za-z_][A-Za-z0-9_]*)\}")),
    ("percent", re.compile(r"%(?:\d+\$)?[sd]")),
    ("escaped_newline", re.compile(r"\\n")),
    ("newline", re.compile(r"\n")),
)


def _overlaps(start: int, end: int, existing_spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in existing_spans)


def extract_placeholders(text: str) -> list[Placeholder]:
    if not text:
        return []

    collected: list[tuple[int, int, str, str]] = []
    occupied_spans: list[tuple[int, int]] = []

    for placeholder_type, pattern in _PLACEHOLDER_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if _overlaps(start, end, occupied_spans):
                continue
            occupied_spans.append((start, end))
            collected.append((start, end, placeholder_type, match.group(0)))

    collected.sort(key=lambda item: item[0])

    return [
        Placeholder(
            type=placeholder_type,
            value=value,
            start=start,
            end=end,
            token=f"⟦PH_{index}⟧",
        )
        for index, (start, end, placeholder_type, value) in enumerate(collected, start=1)
    ]


def protect_text(text: str) -> ProtectedText:
    placeholders = extract_placeholders(text)
    if not placeholders:
        return ProtectedText(
            original=text,
            protected=text,
            placeholders=[],
            token_map={},
        )

    chunks: list[str] = []
    cursor = 0
    for placeholder in placeholders:
        if placeholder.start is None or placeholder.end is None:
            continue
        chunks.append(text[cursor : placeholder.start])
        chunks.append(placeholder.token)
        cursor = placeholder.end
    chunks.append(text[cursor:])

    return ProtectedText(
        original=text,
        protected="".join(chunks),
        placeholders=placeholders,
        token_map={placeholder.token: placeholder.value for placeholder in placeholders},
    )


def reinject(protected_text: ProtectedText, translated_with_tokens: str) -> str:
    output = translated_with_tokens
    for placeholder in protected_text.placeholders:
        output = output.replace(placeholder.token, placeholder.value)
    return output


def validate_placeholders(original_text: str, final_text: str) -> list[str]:
    errors: list[str] = []

    original_values = [item.value for item in extract_placeholders(original_text)]
    final_values = [item.value for item in extract_placeholders(final_text)]
    original_counts = Counter(original_values)
    final_counts = Counter(final_values)

    for value in sorted(set(original_counts) | set(final_counts)):
        expected = original_counts.get(value, 0)
        found = final_counts.get(value, 0)
        if found < expected:
            errors.append(f"Missing placeholder '{value}' (expected {expected}, found {found})")
        elif found > expected:
            errors.append(f"Extra placeholder '{value}' (expected {expected}, found {found})")

    if not errors and original_values != final_values:
        errors.append("Placeholder order changed.")

    return errors
