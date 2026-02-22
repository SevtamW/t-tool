from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from difflib import SequenceMatcher

from sqlalchemy import text
from sqlalchemy.engine import Connection

from tt_core.db.schema import initialize_database
from tt_core.tm.normalize import normalize_source_text, normalized_source_hash
from tt_core.tm.tm_store import TMEntry

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - fallback for environments without rapidfuzz
    fuzz = None

_QUOTE_PATTERN = re.compile(r"""["']""")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


@dataclass(slots=True, frozen=True)
class TMHit:
    tm_id: str
    source_text: str
    target_text: str


@dataclass(slots=True, frozen=True)
class TMHitWithScore(TMHit):
    score: float


def _sanitize_fts_query(query_text: str) -> str:
    stripped = _QUOTE_PATTERN.sub(" ", query_text)
    tokens = _TOKEN_PATTERN.findall(stripped)
    if not tokens:
        return ""

    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(lowered)
    return " OR ".join(f'"{token}"' for token in deduped)


def _similarity_score(left: str, right: str) -> float:
    if fuzz is not None:
        return float(fuzz.token_set_ratio(left, right))
    return SequenceMatcher(None, left, right).ratio() * 100.0


def find_exact(
    *,
    db_path: Path | None = None,
    connection: Connection | None = None,
    project_id: str,
    source_locale: str,
    target_locale: str,
    source_text: str,
) -> TMEntry | None:
    normalized_hash = normalized_source_hash(source_text)
    row = None
    if connection is not None:
        row = connection.execute(
            text(
                """
                SELECT
                    id,
                    project_id,
                    source_locale,
                    target_locale,
                    source_text,
                    target_text,
                    normalized_source_hash,
                    origin,
                    origin_asset_id,
                    origin_row_ref,
                    created_at,
                    updated_at,
                    last_used_at,
                    use_count,
                    quality_tag
                FROM tm_entries
                WHERE project_id = :project_id
                  AND source_locale = :source_locale
                  AND target_locale = :target_locale
                  AND normalized_source_hash = :normalized_source_hash
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            ),
            {
                "project_id": project_id,
                "source_locale": source_locale,
                "target_locale": target_locale,
                "normalized_source_hash": normalized_hash,
            },
        ).first()
    else:
        if db_path is None:
            raise ValueError("db_path is required when connection is not provided")
        engine = initialize_database(Path(db_path))
        try:
            with engine.connect() as local_connection:
                row = local_connection.execute(
                    text(
                        """
                        SELECT
                            id,
                            project_id,
                            source_locale,
                            target_locale,
                            source_text,
                            target_text,
                            normalized_source_hash,
                            origin,
                            origin_asset_id,
                            origin_row_ref,
                            created_at,
                            updated_at,
                            last_used_at,
                            use_count,
                            quality_tag
                        FROM tm_entries
                        WHERE project_id = :project_id
                          AND source_locale = :source_locale
                          AND target_locale = :target_locale
                          AND normalized_source_hash = :normalized_source_hash
                        ORDER BY updated_at DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "project_id": project_id,
                        "source_locale": source_locale,
                        "target_locale": target_locale,
                        "normalized_source_hash": normalized_hash,
                    },
                ).first()
        finally:
            engine.dispose()

    if row is None:
        return None

    return TMEntry(
        id=str(row[0]),
        project_id=str(row[1]),
        source_locale=str(row[2]),
        target_locale=str(row[3]),
        source_text=str(row[4]),
        target_text=str(row[5]),
        normalized_source_hash=str(row[6]),
        origin=str(row[7]),
        origin_asset_id=row[8],
        origin_row_ref=row[9],
        created_at=str(row[10]),
        updated_at=str(row[11]),
        last_used_at=row[12],
        use_count=int(row[13]),
        quality_tag=str(row[14]),
    )


def search_fts(
    *,
    db_path: Path | None = None,
    connection: Connection | None = None,
    project_id: str,
    source_locale: str,
    target_locale: str,
    query_text: str,
    limit: int = 50,
) -> list[TMHit]:
    sanitized = _sanitize_fts_query(query_text)
    normalized_limit = max(1, int(limit))
    if connection is not None:
        if sanitized:
            rows = connection.execute(
                text(
                    """
                    SELECT tm_id, source_text, target_text
                    FROM tm_fts
                    WHERE tm_fts MATCH :query
                      AND project_id = :project_id
                      AND source_locale = :source_locale
                      AND target_locale = :target_locale
                    ORDER BY bm25(tm_fts)
                    LIMIT :limit
                    """
                ),
                {
                    "query": sanitized,
                    "project_id": project_id,
                    "source_locale": source_locale,
                    "target_locale": target_locale,
                    "limit": normalized_limit,
                },
            ).all()
        else:
            rows = connection.execute(
                text(
                    """
                    SELECT tm_id, source_text, target_text
                    FROM tm_fts
                    WHERE project_id = :project_id
                      AND source_locale = :source_locale
                      AND target_locale = :target_locale
                    ORDER BY
                        CASE WHEN source_text = :query_text THEN 0 ELSE 1 END,
                        rowid DESC
                    LIMIT :limit
                    """
                ),
                {
                    "project_id": project_id,
                    "source_locale": source_locale,
                    "target_locale": target_locale,
                    "query_text": query_text,
                    "limit": normalized_limit,
                },
            ).all()
    else:
        if db_path is None:
            raise ValueError("db_path is required when connection is not provided")
        engine = initialize_database(Path(db_path))
        try:
            with engine.connect() as local_connection:
                rows = search_fts(
                    connection=local_connection,
                    project_id=project_id,
                    source_locale=source_locale,
                    target_locale=target_locale,
                    query_text=query_text,
                    limit=normalized_limit,
                )
        finally:
            engine.dispose()
        return rows

    return [
        TMHit(tm_id=str(row[0]), source_text=str(row[1]), target_text=str(row[2]))
        for row in rows
    ]


def search_fuzzy(
    *,
    db_path: Path | None = None,
    connection: Connection | None = None,
    project_id: str,
    source_locale: str,
    target_locale: str,
    source_text: str,
    limit: int = 5,
) -> list[TMHitWithScore]:
    normalized_limit = max(1, int(limit))
    candidates = search_fts(
        db_path=db_path,
        connection=connection,
        project_id=project_id,
        source_locale=source_locale,
        target_locale=target_locale,
        query_text=source_text,
        limit=max(50, normalized_limit * 10),
    )
    normalized_source = normalize_source_text(source_text)

    scored = [
        TMHitWithScore(
            tm_id=item.tm_id,
            source_text=item.source_text,
            target_text=item.target_text,
            score=_similarity_score(normalized_source, normalize_source_text(item.source_text)),
        )
        for item in candidates
    ]
    scored.sort(key=lambda item: (-item.score, item.tm_id))
    return scored[:normalized_limit]
