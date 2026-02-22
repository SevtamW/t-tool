from __future__ import annotations

"""Glossary term loading, matching, and enforcement helpers."""

from tt_core.glossary.enforcer import (
    GlossaryEnforcementResult,
    GlossaryExpectedEnforcement,
    enforce_must_use,
    reinject_term_tokens,
)
from tt_core.glossary.glossary_store import GlossaryTerm, load_must_use_terms
from tt_core.glossary.matcher import TermMatch, find_must_use_matches

__all__ = [
    "GlossaryEnforcementResult",
    "GlossaryExpectedEnforcement",
    "GlossaryTerm",
    "TermMatch",
    "enforce_must_use",
    "find_must_use_matches",
    "load_must_use_terms",
    "reinject_term_tokens",
]
