from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from tt_core.db.schema import initialize_database
from tt_core.tm.normalize import normalized_source_hash


@dataclass(slots=True, frozen=True)
class TMEntry:
    id: str
    project_id: str
    source_locale: str
    target_locale: str
    source_text: str
    target_text: str
    normalized_source_hash: str
    origin: str
    origin_asset_id: str | None
    origin_row_ref: str | None
    created_at: str
    updated_at: str
    last_used_at: str | None
    use_count: int
    quality_tag: str


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _upsert_tm_entry_on_connection(
    connection: Connection,
    *,
    project_id: str,
    source_locale: str,
    target_locale: str,
    source_text: str,
    target_text: str,
    origin: str,
    origin_asset_id: str | None = None,
    origin_row_ref: str | None = None,
    quality_tag: str = "trusted",
) -> str:
    now = _utc_now_iso()
    normalized_hash = normalized_source_hash(source_text)
    existing = connection.execute(
        text(
            """
            SELECT id
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

    if existing is None:
        tm_id = str(uuid4())
        connection.execute(
            text(
                """
                INSERT INTO tm_entries(
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
                ) VALUES (
                    :id,
                    :project_id,
                    :source_locale,
                    :target_locale,
                    :source_text,
                    :target_text,
                    :normalized_source_hash,
                    :origin,
                    :origin_asset_id,
                    :origin_row_ref,
                    :created_at,
                    :updated_at,
                    NULL,
                    0,
                    :quality_tag
                )
                """
            ),
            {
                "id": tm_id,
                "project_id": project_id,
                "source_locale": source_locale,
                "target_locale": target_locale,
                "source_text": source_text,
                "target_text": target_text,
                "normalized_source_hash": normalized_hash,
                "origin": origin,
                "origin_asset_id": origin_asset_id,
                "origin_row_ref": origin_row_ref,
                "created_at": now,
                "updated_at": now,
                "quality_tag": quality_tag,
            },
        )
    else:
        tm_id = str(existing[0])
        connection.execute(
            text(
                """
                UPDATE tm_entries
                SET
                    source_text = :source_text,
                    target_text = :target_text,
                    origin = :origin,
                    origin_asset_id = :origin_asset_id,
                    origin_row_ref = :origin_row_ref,
                    quality_tag = :quality_tag,
                    updated_at = :updated_at
                WHERE id = :id
                """
            ),
            {
                "id": tm_id,
                "source_text": source_text,
                "target_text": target_text,
                "origin": origin,
                "origin_asset_id": origin_asset_id,
                "origin_row_ref": origin_row_ref,
                "quality_tag": quality_tag,
                "updated_at": now,
            },
        )

    connection.execute(
        text(
            """
            DELETE FROM tm_fts
            WHERE tm_id = :tm_id
            """
        ),
        {"tm_id": tm_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO tm_fts(
                project_id, source_locale, target_locale, source_text, target_text, tm_id
            ) VALUES (
                :project_id, :source_locale, :target_locale, :source_text, :target_text, :tm_id
            )
            """
        ),
        {
            "project_id": project_id,
            "source_locale": source_locale,
            "target_locale": target_locale,
            "source_text": source_text,
            "target_text": target_text,
            "tm_id": tm_id,
        },
    )
    return tm_id


def upsert_tm_entry(
    *,
    db_path: Path | None = None,
    connection: Connection | None = None,
    project_id: str,
    source_locale: str,
    target_locale: str,
    source_text: str,
    target_text: str,
    origin: str,
    origin_asset_id: str | None = None,
    origin_row_ref: str | None = None,
    quality_tag: str = "trusted",
) -> str:
    if connection is not None:
        return _upsert_tm_entry_on_connection(
            connection=connection,
            project_id=project_id,
            source_locale=source_locale,
            target_locale=target_locale,
            source_text=source_text,
            target_text=target_text,
            origin=origin,
            origin_asset_id=origin_asset_id,
            origin_row_ref=origin_row_ref,
            quality_tag=quality_tag,
        )

    if db_path is None:
        raise ValueError("db_path is required when connection is not provided")

    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as local_connection:
            return _upsert_tm_entry_on_connection(
                local_connection,
                project_id=project_id,
                source_locale=source_locale,
                target_locale=target_locale,
                source_text=source_text,
                target_text=target_text,
                origin=origin,
                origin_asset_id=origin_asset_id,
                origin_row_ref=origin_row_ref,
                quality_tag=quality_tag,
            )
    finally:
        engine.dispose()


def record_tm_use(
    *,
    db_path: Path | None = None,
    connection: Connection | None = None,
    tm_id: str,
) -> None:
    now = _utc_now_iso()

    if connection is not None:
        connection.execute(
            text(
                """
                UPDATE tm_entries
                SET
                    use_count = use_count + 1,
                    last_used_at = :last_used_at
                WHERE id = :tm_id
                """
            ),
            {"tm_id": tm_id, "last_used_at": now},
        )
        return

    if db_path is None:
        raise ValueError("db_path is required when connection is not provided")

    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as local_connection:
            local_connection.execute(
                text(
                    """
                    UPDATE tm_entries
                    SET
                        use_count = use_count + 1,
                        last_used_at = :last_used_at
                    WHERE id = :tm_id
                    """
                ),
                {"tm_id": tm_id, "last_used_at": now},
            )
    finally:
        engine.dispose()
