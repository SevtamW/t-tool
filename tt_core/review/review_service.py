from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from tt_core.db.schema import initialize_database
from tt_core.tm.tm_store import upsert_tm_entry


@dataclass(slots=True)
class AssetListItem:
    id: str
    original_name: str | None
    received_at: str
    asset_type: str
    storage_path: str | None


@dataclass(slots=True)
class SegmentRow:
    id: str
    asset_id: str
    row_index: int | None
    key: str | None
    source_text: str
    cn_text: str | None
    sheet_name: str | None


@dataclass(slots=True)
class CandidateRow:
    id: str
    segment_id: str
    target_locale: str
    candidate_text: str
    candidate_type: str
    generated_at: str


@dataclass(slots=True)
class ReviewRow:
    segment_id: str
    row_index: int | None
    key: str | None
    source_text: str
    cn_text: str | None
    sheet_name: str | None
    candidate_text: str | None
    candidate_type: str | None
    approved_text: str | None
    is_approved: bool
    qa_messages: list[str] = field(default_factory=list)
    has_qa_flags: bool = False


@dataclass(slots=True)
class ApprovedPatchRow:
    segment_id: str
    row_index: int | None
    key: str | None
    source_text: str
    approved_target_text: str
    cn_text: str | None
    sheet_name: str | None


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def list_assets(*, db_path: Path, project_id: str) -> list[AssetListItem]:
    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id, original_name, received_at, asset_type, storage_path
                    FROM assets
                    WHERE project_id = :project_id
                    ORDER BY received_at DESC
                    """
                ),
                {"project_id": project_id},
            ).all()
    finally:
        engine.dispose()

    return [
        AssetListItem(
            id=str(row[0]),
            original_name=row[1],
            received_at=str(row[2]),
            asset_type=str(row[3]),
            storage_path=row[4],
        )
        for row in rows
    ]


def list_segments(*, db_path: Path, asset_id: str) -> list[SegmentRow]:
    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id, asset_id, row_index, key, source_text, cn_text, sheet_name
                    FROM segments
                    WHERE asset_id = :asset_id
                    ORDER BY row_index, id
                    """
                ),
                {"asset_id": asset_id},
            ).all()
    finally:
        engine.dispose()

    return [
        SegmentRow(
            id=str(row[0]),
            asset_id=str(row[1]),
            row_index=row[2],
            key=row[3],
            source_text=str(row[4]),
            cn_text=row[5],
            sheet_name=row[6],
        )
        for row in rows
    ]


def _upsert_candidate_on_connection(
    connection: Connection,
    *,
    segment_id: str,
    target_locale: str,
    candidate_text: str,
    candidate_type: str,
    score: float,
    model_info_json: str,
    generated_at: str,
) -> str:
    existing = connection.execute(
        text(
            """
            SELECT id
            FROM translation_candidates
            WHERE segment_id = :segment_id
              AND target_locale = :target_locale
              AND candidate_type = :candidate_type
            ORDER BY generated_at DESC, id DESC
            LIMIT 1
            """
        ),
        {
            "segment_id": segment_id,
            "target_locale": target_locale,
            "candidate_type": candidate_type,
        },
    ).first()

    if existing is None:
        candidate_id = str(uuid4())
        connection.execute(
            text(
                """
                INSERT INTO translation_candidates(
                    id, segment_id, target_locale, candidate_text,
                    candidate_type, score, model_info_json, generated_at
                ) VALUES (
                    :id, :segment_id, :target_locale, :candidate_text,
                    :candidate_type, :score, :model_info_json, :generated_at
                )
                """
            ),
            {
                "id": candidate_id,
                "segment_id": segment_id,
                "target_locale": target_locale,
                "candidate_text": candidate_text,
                "candidate_type": candidate_type,
                "score": score,
                "model_info_json": model_info_json,
                "generated_at": generated_at,
            },
        )
        return candidate_id

    candidate_id = str(existing[0])
    connection.execute(
        text(
            """
            UPDATE translation_candidates
            SET candidate_text = :candidate_text,
                score = :score,
                model_info_json = :model_info_json,
                generated_at = :generated_at
            WHERE id = :id
            """
        ),
        {
            "id": candidate_id,
            "candidate_text": candidate_text,
            "score": score,
            "model_info_json": model_info_json,
            "generated_at": generated_at,
        },
    )
    return candidate_id


def upsert_candidate(
    *,
    db_path: Path | None = None,
    connection: Connection | None = None,
    segment_id: str,
    target_locale: str,
    candidate_text: str,
    candidate_type: str,
    score: float = 1.0,
    model_info: dict[str, str] | None = None,
    generated_at: str | None = None,
) -> str:
    generated = generated_at or _utc_now_iso()
    model_payload = json.dumps(model_info or {})

    if connection is not None:
        return _upsert_candidate_on_connection(
            connection,
            segment_id=segment_id,
            target_locale=target_locale,
            candidate_text=candidate_text,
            candidate_type=candidate_type,
            score=score,
            model_info_json=model_payload,
            generated_at=generated,
        )

    if db_path is None:
        raise ValueError("db_path is required when connection is not provided")

    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as local_connection:
            return _upsert_candidate_on_connection(
                local_connection,
                segment_id=segment_id,
                target_locale=target_locale,
                candidate_text=candidate_text,
                candidate_type=candidate_type,
                score=score,
                model_info_json=model_payload,
                generated_at=generated,
            )
    finally:
        engine.dispose()


def get_latest_candidate(*, db_path: Path, segment_id: str, target_locale: str) -> CandidateRow | None:
    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, segment_id, target_locale, candidate_text, candidate_type, generated_at
                    FROM translation_candidates
                    WHERE segment_id = :segment_id AND target_locale = :target_locale
                    ORDER BY generated_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"segment_id": segment_id, "target_locale": target_locale},
            ).first()
    finally:
        engine.dispose()

    if row is None:
        return None

    return CandidateRow(
        id=str(row[0]),
        segment_id=str(row[1]),
        target_locale=str(row[2]),
        candidate_text=str(row[3]),
        candidate_type=str(row[4]),
        generated_at=str(row[5]),
    )


def upsert_approved_translation(
    *,
    db_path: Path,
    segment_id: str,
    target_locale: str,
    final_text: str,
    approved_by: str = "me",
) -> str:
    now = _utc_now_iso()
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            inserted_id = str(uuid4())
            connection.execute(
                text(
                    """
                    INSERT INTO approved_translations(
                        id, segment_id, target_locale, final_text, status,
                        approved_by, approved_at, revision_of_id, is_pinned
                    ) VALUES (
                        :id, :segment_id, :target_locale, :final_text, :status,
                        :approved_by, :approved_at, NULL, 0
                    )
                    ON CONFLICT(segment_id, target_locale) DO UPDATE SET
                        final_text = excluded.final_text,
                        status = excluded.status,
                        approved_by = excluded.approved_by,
                        approved_at = excluded.approved_at
                    """
                ),
                {
                    "id": inserted_id,
                    "segment_id": segment_id,
                    "target_locale": target_locale,
                    "final_text": final_text,
                    "status": "approved",
                    "approved_by": approved_by,
                    "approved_at": now,
                },
            )

            segment_row = connection.execute(
                text(
                    """
                    SELECT
                        a.project_id,
                        s.source_locale,
                        s.source_text,
                        s.asset_id,
                        s.sheet_name,
                        s.row_index
                    FROM segments AS s
                    INNER JOIN assets AS a
                        ON a.id = s.asset_id
                    WHERE s.id = :segment_id
                    LIMIT 1
                    """
                ),
                {"segment_id": segment_id},
            ).first()
            if segment_row is None:
                raise RuntimeError(f"Segment not found for approval: {segment_id}")

            sheet_name = segment_row[4]
            row_index = segment_row[5]
            origin_row_ref = f"{sheet_name}:{row_index}"
            upsert_tm_entry(
                connection=connection,
                project_id=str(segment_row[0]),
                source_locale=str(segment_row[1]),
                target_locale=target_locale,
                source_text=str(segment_row[2]),
                target_text=final_text,
                origin="approved",
                origin_asset_id=str(segment_row[3]) if segment_row[3] is not None else None,
                origin_row_ref=origin_row_ref,
                quality_tag="trusted",
            )

            id_row = connection.execute(
                text(
                    """
                    SELECT id
                    FROM approved_translations
                    WHERE segment_id = :segment_id AND target_locale = :target_locale
                    LIMIT 1
                    """
                ),
                {
                    "segment_id": segment_id,
                    "target_locale": target_locale,
                },
            ).first()
    finally:
        engine.dispose()

    if id_row is None:
        raise RuntimeError("Failed to persist approved translation")
    return str(id_row[0])


def list_review_rows(*, db_path: Path, asset_id: str, target_locale: str) -> list[ReviewRow]:
    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        s.id AS segment_id,
                        s.row_index,
                        s.key,
                        s.source_text,
                        s.cn_text,
                        s.sheet_name,
                        tc.candidate_text,
                        tc.candidate_type,
                        at.final_text
                    FROM segments AS s
                    LEFT JOIN translation_candidates AS tc
                        ON tc.id = (
                            SELECT t2.id
                            FROM translation_candidates AS t2
                            WHERE t2.segment_id = s.id
                              AND t2.target_locale = :target_locale
                            ORDER BY t2.generated_at DESC, t2.id DESC
                            LIMIT 1
                        )
                    LEFT JOIN approved_translations AS at
                        ON at.segment_id = s.id
                       AND at.target_locale = :target_locale
                    WHERE s.asset_id = :asset_id
                    ORDER BY s.row_index, s.id
                    """
                ),
                {"asset_id": asset_id, "target_locale": target_locale},
            ).all()
            qa_rows = connection.execute(
                text(
                    """
                    SELECT q.segment_id, q.message
                    FROM qa_flags AS q
                    INNER JOIN segments AS s
                        ON s.id = q.segment_id
                    WHERE s.asset_id = :asset_id
                      AND q.target_locale = :target_locale
                      AND q.resolved_at IS NULL
                    ORDER BY q.created_at, q.id
                    """
                ),
                {"asset_id": asset_id, "target_locale": target_locale},
            ).all()
    finally:
        engine.dispose()

    qa_by_segment: dict[str, list[str]] = defaultdict(list)
    for qa_row in qa_rows:
        qa_by_segment[str(qa_row[0])].append(str(qa_row[1]))

    return [
        ReviewRow(
            segment_id=str(row[0]),
            row_index=row[1],
            key=row[2],
            source_text=str(row[3]),
            cn_text=row[4],
            sheet_name=row[5],
            candidate_text=row[6],
            candidate_type=row[7],
            approved_text=row[8],
            is_approved=row[8] is not None,
            qa_messages=qa_by_segment.get(str(row[0]), []),
            has_qa_flags=bool(qa_by_segment.get(str(row[0]), [])),
        )
        for row in rows
    ]


def list_approved_for_asset(*, db_path: Path, asset_id: str, target_locale: str) -> list[ApprovedPatchRow]:
    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        s.id AS segment_id,
                        s.row_index,
                        s.key,
                        s.source_text,
                        a.final_text AS approved_target_text,
                        s.cn_text,
                        s.sheet_name
                    FROM approved_translations AS a
                    INNER JOIN segments AS s
                        ON s.id = a.segment_id
                    WHERE s.asset_id = :asset_id
                      AND a.target_locale = :target_locale
                    ORDER BY s.row_index, s.id
                    """
                ),
                {"asset_id": asset_id, "target_locale": target_locale},
            ).all()
    finally:
        engine.dispose()

    return [
        ApprovedPatchRow(
            segment_id=str(row[0]),
            row_index=row[1],
            key=row[2],
            source_text=str(row[3]),
            approved_target_text=str(row[4]),
            cn_text=row[5],
            sheet_name=row[6],
        )
        for row in rows
    ]
