from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence
import re

from tt_core.glossary.enforcer import GlossaryExpectedEnforcement
from tt_core.qa.placeholder_firewall import validate_placeholders

_GLOSSARY_TOKEN_PATTERN = re.compile(r"⟦TERM_\d+⟧")


@dataclass(slots=True, frozen=True)
class QAIssue:
    issue_type: str
    severity: str
    message: str
    span: dict[str, object] = field(default_factory=dict)


def check_placeholders_unchanged(source: str, target: str) -> list[QAIssue]:
    return [
        QAIssue(
            issue_type="placeholder_mismatch",
            severity="error",
            message=message,
        )
        for message in validate_placeholders(source, target)
    ]


def check_newlines_preserved(source: str, target: str) -> list[QAIssue]:
    issues: list[QAIssue] = []

    source_newline_count = source.count("\n")
    target_newline_count = target.count("\n")
    if source_newline_count != target_newline_count:
        issues.append(
            QAIssue(
                issue_type="newline_mismatch",
                severity="error",
                message=(
                    "Actual newline count changed "
                    f"(expected {source_newline_count}, found {target_newline_count})."
                ),
                span={"kind": "newline"},
            )
        )

    escaped_newline_pattern = re.compile(r"\\n")
    source_escaped_newline_count = len(escaped_newline_pattern.findall(source))
    target_escaped_newline_count = len(escaped_newline_pattern.findall(target))
    if source_escaped_newline_count != target_escaped_newline_count:
        issues.append(
            QAIssue(
                issue_type="newline_mismatch",
                severity="error",
                message=(
                    "Escaped newline count changed "
                    f"(expected {source_escaped_newline_count}, found {target_escaped_newline_count})."
                ),
                span={"kind": "escaped_newline"},
            )
        )

    return issues


def _count_non_overlapping_occurrences(text: str, needle: str) -> int:
    if not needle:
        return 0
    return len(re.findall(re.escape(needle), text))


def check_glossary_compliance(
    expected_enforcements: Sequence[GlossaryExpectedEnforcement],
    final_text: str,
    translated_with_tokens: str | None = None,
) -> list[QAIssue]:
    if not expected_enforcements:
        return []

    issues: list[QAIssue] = []

    if translated_with_tokens is not None:
        for expected in expected_enforcements:
            if expected.token in translated_with_tokens:
                continue
            issues.append(
                QAIssue(
                    issue_type="glossary_violation",
                    severity="error",
                    message=(
                        f"Glossary lock token '{expected.token}' was modified or removed before reinjection."
                    ),
                    span={"token": expected.token, "source_term": expected.source_term},
                )
            )

    unresolved_tokens = sorted(set(_GLOSSARY_TOKEN_PATTERN.findall(final_text)))
    for token in unresolved_tokens:
        issues.append(
            QAIssue(
                issue_type="glossary_violation",
                severity="error",
                message=f"Glossary lock token '{token}' was not reinjected in final output.",
                span={"token": token},
            )
        )

    expected_counts = Counter(item.enforced_text for item in expected_enforcements if item.enforced_text)
    for enforced_text, expected_count in expected_counts.items():
        found_count = _count_non_overlapping_occurrences(final_text, enforced_text)
        if found_count >= expected_count:
            continue
        issues.append(
            QAIssue(
                issue_type="glossary_violation",
                severity="error",
                message=(
                    f"Missing enforced glossary term '{enforced_text}' "
                    f"(expected at least {expected_count}, found {found_count})."
                ),
                span={"enforced_text": enforced_text, "expected_count": expected_count},
            )
        )

    return issues
