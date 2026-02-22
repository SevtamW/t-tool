from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re

from tt_core.glossary.glossary_store import GlossaryTerm
from tt_core.glossary.matcher import find_must_use_matches

_TERM_TOKEN_PATTERN = re.compile(r"⟦TERM_(\d+)⟧")


@dataclass(slots=True, frozen=True)
class GlossaryExpectedEnforcement:
    token: str
    source_term: str
    target_term: str
    enforced_text: str
    start: int
    end: int
    is_compound: bool = False


@dataclass(slots=True, frozen=True)
class GlossaryEnforcementResult:
    original_text: str
    text_with_term_tokens: str
    term_map: dict[str, str]
    expected_enforcements: list[GlossaryExpectedEnforcement]


def enforce_must_use(*, text: str, terms: Sequence[GlossaryTerm]) -> GlossaryEnforcementResult:
    matches = find_must_use_matches(text=text, terms=list(terms))
    if not matches:
        return GlossaryEnforcementResult(
            original_text=text,
            text_with_term_tokens=text,
            term_map={},
            expected_enforcements=[],
        )

    chunks: list[str] = []
    term_map: dict[str, str] = {}
    expected: list[GlossaryExpectedEnforcement] = []

    cursor = 0
    for index, match in enumerate(matches, start=1):
        token = f"⟦TERM_{index}⟧"
        chunks.append(text[cursor : match.start])
        chunks.append(token)
        cursor = match.end

        term_map[token] = match.enforced_text
        expected.append(
            GlossaryExpectedEnforcement(
                token=token,
                source_term=match.term.source_term,
                target_term=match.term.target_term,
                enforced_text=match.enforced_text,
                start=match.start,
                end=match.end,
                is_compound=match.is_compound,
            )
        )

    chunks.append(text[cursor:])

    return GlossaryEnforcementResult(
        original_text=text,
        text_with_term_tokens="".join(chunks),
        term_map=term_map,
        expected_enforcements=expected,
    )


def _term_token_sort_key(token: str) -> tuple[int, str]:
    matched = _TERM_TOKEN_PATTERN.fullmatch(token)
    if matched is None:
        return (10**9, token)
    return (int(matched.group(1)), token)


def reinject_term_tokens(text: str, term_map: Mapping[str, str]) -> str:
    if not term_map:
        return text

    output = text
    for token in sorted(term_map.keys(), key=_term_token_sort_key):
        output = output.replace(token, term_map[token])
    return output
