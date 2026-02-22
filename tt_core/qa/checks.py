from __future__ import annotations

from dataclasses import dataclass, field
import re

from tt_core.qa.placeholder_firewall import validate_placeholders


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
