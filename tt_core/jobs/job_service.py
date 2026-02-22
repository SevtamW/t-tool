from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from tt_core.db.schema import initialize_database
from tt_core.jobs.mock_translator import mock_translate
from tt_core.review.review_service import upsert_candidate


@dataclass(slots=True)
class JobRunSummary:
    job_id: str
    project_id: str
    asset_id: str
    target_locale: str
    processed_segments: int
    status: str


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _latest_mapping_signature(*, db_path: Path, project_id: str) -> str | None:
    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT signature
                    FROM schema_profiles
                    WHERE project_id = :project_id
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {"project_id": project_id},
            ).first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return str(row[0])


def create_job(
    *,
    db_path: Path,
    project_id: str,
    asset_id: str,
    target_locale: str,
    decision_trace: dict[str, object] | None = None,
) -> str:
    job_id = str(uuid4())
    now = _utc_now_iso()
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO jobs(
                        id, project_id, asset_id, job_type, targets_json, status,
                        created_at, started_at, finished_at, summary, decision_trace_json
                    ) VALUES (
                        :id, :project_id, :asset_id, :job_type, :targets_json, :status,
                        :created_at, NULL, NULL, NULL, :decision_trace_json
                    )
                    """
                ),
                {
                    "id": job_id,
                    "project_id": project_id,
                    "asset_id": asset_id,
                    "job_type": "mock_translate",
                    "targets_json": json.dumps([target_locale]),
                    "status": "queued",
                    "created_at": now,
                    "decision_trace_json": json.dumps(decision_trace or {}),
                },
            )
    finally:
        engine.dispose()

    return job_id


def update_job_status(
    *,
    db_path: Path,
    job_id: str,
    status: str,
    summary: str | None = None,
    set_started_at: bool = False,
    set_finished_at: bool = False,
) -> None:
    now = _utc_now_iso()
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE jobs
                    SET
                        status = :status,
                        summary = :summary,
                        started_at = CASE
                            WHEN :set_started_at = 1 THEN COALESCE(started_at, :now)
                            ELSE started_at
                        END,
                        finished_at = CASE
                            WHEN :set_finished_at = 1 THEN :now
                            ELSE finished_at
                        END
                    WHERE id = :job_id
                    """
                ),
                {
                    "status": status,
                    "summary": summary,
                    "set_started_at": 1 if set_started_at else 0,
                    "set_finished_at": 1 if set_finished_at else 0,
                    "now": now,
                    "job_id": job_id,
                },
            )
    finally:
        engine.dispose()


def run_mock_translation_job(
    *,
    db_path: Path,
    project_id: str,
    asset_id: str,
    target_locale: str,
    decision_trace: dict[str, object] | None = None,
) -> JobRunSummary:
    mapping_signature = _latest_mapping_signature(db_path=db_path, project_id=project_id)
    merged_trace = dict(decision_trace or {})
    merged_trace.setdefault("selected_asset_id", asset_id)
    merged_trace.setdefault("mapping_signature", mapping_signature)

    job_id = create_job(
        db_path=db_path,
        project_id=project_id,
        asset_id=asset_id,
        target_locale=target_locale,
        decision_trace=merged_trace,
    )

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="running",
        summary="Job is running",
        set_started_at=True,
    )

    processed = 0
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            segment_rows = connection.execute(
                text(
                    """
                    SELECT id, source_text
                    FROM segments
                    WHERE asset_id = :asset_id
                    ORDER BY row_index, id
                    """
                ),
                {"asset_id": asset_id},
            ).all()

            for row in segment_rows:
                segment_id = str(row[0])
                source_text = str(row[1]).strip()
                if not source_text:
                    continue

                upsert_candidate(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    candidate_text=mock_translate(source_text, target_locale),
                    candidate_type="mock",
                    score=1.0,
                    model_info={"provider": "mock", "version": "1"},
                )
                processed += 1
    except Exception as exc:
        update_job_status(
            db_path=db_path,
            job_id=job_id,
            status="failed",
            summary=f"Job failed: {exc}",
            set_finished_at=True,
        )
        raise
    finally:
        engine.dispose()

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="done",
        summary=f"Processed {processed} segment(s) for {target_locale}",
        set_finished_at=True,
    )

    return JobRunSummary(
        job_id=job_id,
        project_id=project_id,
        asset_id=asset_id,
        target_locale=target_locale,
        processed_segments=processed,
        status="done",
    )

