"""Translation memory storage and retrieval helpers."""

from tt_core.tm.normalize import normalize_source_text, normalized_source_hash
from tt_core.tm.tm_search import TMHit, TMHitWithScore, find_exact, search_fts, search_fuzzy
from tt_core.tm.tm_store import TMEntry, record_tm_use, upsert_tm_entry

__all__ = [
    "TMEntry",
    "TMHit",
    "TMHitWithScore",
    "find_exact",
    "normalize_source_text",
    "normalized_source_hash",
    "record_tm_use",
    "search_fts",
    "search_fuzzy",
    "upsert_tm_entry",
]
