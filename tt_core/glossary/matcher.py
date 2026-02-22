from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

from tt_core.glossary.glossary_store import GlossaryTerm

_LOCKED_TOKEN_PATTERN = re.compile(r"⟦(?:PH|TERM)_\d+⟧")


@dataclass(slots=True, frozen=True)
class TermMatch:
    term: GlossaryTerm
    start: int
    end: int
    source_text: str
    enforced_text: str
    is_compound: bool = False
    priority: int = 0


def _span_overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _iter_alnum_tokens(
    text: str,
    *,
    blocked_spans: list[tuple[int, int]],
) -> list[tuple[int, int, str]]:
    tokens: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(text):
        if not text[cursor].isalnum():
            cursor += 1
            continue

        start = cursor
        while cursor < len(text) and text[cursor].isalnum():
            cursor += 1
        end = cursor

        if _span_overlaps(start, end, blocked_spans):
            continue
        tokens.append((start, end, text[start:end]))

    return tokens


def _equals(left: str, right: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return left == right
    return left.casefold() == right.casefold()


def _starts_with(value: str, prefix: str, *, case_sensitive: bool) -> bool:
    if len(value) < len(prefix):
        return False
    return _equals(value[: len(prefix)], prefix, case_sensitive=case_sensitive)


def _compound_split_points(token: str) -> set[int]:
    points: set[int] = set()
    for index in range(1, len(token)):
        previous = token[index - 1]
        current = token[index]

        if previous.isalpha() and current.isdigit():
            points.add(index)
            continue

        if previous.isdigit() and current.isalpha():
            points.add(index)
            continue

        if previous.islower() and current.isupper():
            points.add(index)
            continue

        if previous.isupper() and current.islower() and index >= 2 and token[index - 2].isupper():
            points.add(index)
            continue

        if (
            previous.isupper()
            and current.isupper()
            and index + 1 < len(token)
            and token[index + 1].islower()
        ):
            points.add(index)

    return points


def _apply_compound_strategy(
    *,
    full_token: str,
    rest: str,
    target_term: str,
    strategy: str,
) -> str:
    normalized_strategy = strategy.strip().lower()
    if normalized_strategy == "keep_source":
        return full_token
    if normalized_strategy == "replace_prefix":
        return f"{target_term}{rest}"
    return f"{target_term}-{rest}"


@lru_cache(maxsize=256)
def _compile_regex(pattern: str, case_sensitive: bool) -> re.Pattern[str] | None:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def _is_negative_pattern_blocked(
    *,
    term: GlossaryTerm,
    text: str,
    start: int,
    end: int,
) -> bool:
    if not term.negative_patterns:
        return False

    context_start = max(0, start - 48)
    context_end = min(len(text), end + 48)
    context = text[context_start:context_end]

    for raw_pattern in term.negative_patterns:
        pattern = _compile_regex(raw_pattern, term.case_sensitive)
        if pattern is None:
            continue
        if pattern.search(text) or pattern.search(context):
            return True

    return False


def _find_token_matches(
    *,
    text: str,
    term: GlossaryTerm,
    tokens: list[tuple[int, int, str]],
    priority: int,
) -> list[TermMatch]:
    matches: list[TermMatch] = []
    source = term.source_term
    if not source:
        return matches

    for start, end, token in tokens:
        if _equals(token, source, case_sensitive=term.case_sensitive):
            if _is_negative_pattern_blocked(term=term, text=text, start=start, end=end):
                continue
            matches.append(
                TermMatch(
                    term=term,
                    start=start,
                    end=end,
                    source_text=token,
                    enforced_text=term.target_term,
                    is_compound=False,
                    priority=priority,
                )
            )
            continue

        if not term.allow_compounds:
            continue

        if not _starts_with(token, source, case_sensitive=term.case_sensitive):
            continue

        split_index = len(source)
        if split_index >= len(token):
            continue

        if split_index not in _compound_split_points(token):
            continue

        rest = token[split_index:]
        if not rest:
            continue

        if _is_negative_pattern_blocked(term=term, text=text, start=start, end=end):
            continue

        matches.append(
            TermMatch(
                term=term,
                start=start,
                end=end,
                source_text=token,
                enforced_text=_apply_compound_strategy(
                    full_token=token,
                    rest=rest,
                    target_term=term.target_term,
                    strategy=term.compound_strategy,
                ),
                is_compound=True,
                priority=priority,
            )
        )

    return matches


def _find_exact_matches(
    *,
    text: str,
    term: GlossaryTerm,
    blocked_spans: list[tuple[int, int]],
    priority: int,
) -> list[TermMatch]:
    if not term.source_term:
        return []

    pattern = _compile_regex(re.escape(term.source_term), term.case_sensitive)
    if pattern is None:
        return []

    output: list[TermMatch] = []
    for match in pattern.finditer(text):
        start, end = match.span()
        if _span_overlaps(start, end, blocked_spans):
            continue

        if _is_negative_pattern_blocked(term=term, text=text, start=start, end=end):
            continue

        output.append(
            TermMatch(
                term=term,
                start=start,
                end=end,
                source_text=match.group(0),
                enforced_text=term.target_term,
                is_compound=False,
                priority=priority,
            )
        )

    return output


def _select_non_overlapping(matches: list[TermMatch]) -> list[TermMatch]:
    sorted_matches = sorted(
        matches,
        key=lambda item: (
            item.start,
            -(item.end - item.start),
            item.priority,
            -len(item.term.source_term),
            item.term.source_term.casefold(),
        ),
    )

    selected: list[TermMatch] = []
    for candidate in sorted_matches:
        if any(candidate.start < item.end and item.start < candidate.end for item in selected):
            continue
        selected.append(candidate)

    return sorted(selected, key=lambda item: (item.start, item.end))


def find_must_use_matches(*, text: str, terms: list[GlossaryTerm]) -> list[TermMatch]:
    if not text or not terms:
        return []

    blocked_spans = [(match.start(), match.end()) for match in _LOCKED_TOKEN_PATTERN.finditer(text)]
    tokens = _iter_alnum_tokens(text, blocked_spans=blocked_spans)

    matches: list[TermMatch] = []
    for priority, term in enumerate(terms):
        match_type = term.match_type.strip().lower()
        if match_type in {"whole_token", "word_boundary"}:
            matches.extend(
                _find_token_matches(
                    text=text,
                    term=term,
                    tokens=tokens,
                    priority=priority,
                )
            )
        elif match_type == "exact":
            matches.extend(
                _find_exact_matches(
                    text=text,
                    term=term,
                    blocked_spans=blocked_spans,
                    priority=priority,
                )
            )

    if not matches:
        return []

    return _select_non_overlapping(matches)
