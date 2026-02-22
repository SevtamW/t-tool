"""QA helpers for placeholder protection and baseline checks."""

from tt_core.qa.checks import QAIssue, check_newlines_preserved, check_placeholders_unchanged
from tt_core.qa.placeholder_firewall import (
    Placeholder,
    ProtectedText,
    extract_placeholders,
    protect_text,
    reinject,
    validate_placeholders,
)

__all__ = [
    "Placeholder",
    "ProtectedText",
    "QAIssue",
    "check_newlines_preserved",
    "check_placeholders_unchanged",
    "extract_placeholders",
    "protect_text",
    "reinject",
    "validate_placeholders",
]
