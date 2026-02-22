from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from tt_core.db.schema import initialize_database
from tt_core.glossary.enforcer import enforce_must_use, reinject_term_tokens
from tt_core.glossary.glossary_store import load_must_use_terms
from tt_core.jobs.mock_translator import mock_translate
from tt_core.project.config import read_config
from tt_core.project.paths import project_config_path
from tt_core.qa.checks import (
    QAIssue,
    check_glossary_compliance,
    check_newlines_preserved,
    check_placeholders_unchanged,
)
from tt_core.qa.placeholder_firewall import Placeholder, protect_text, reinject
from tt_core.review.review_service import upsert_candidate
from tt_core.tm.tm_search import find_exact, search_fuzzy
from tt_core.tm.tm_store import record_tm_use

TM_FUZZY_THRESHOLD = 92.0


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


def _placeholder_payload(placeholders: list[Placeholder]) -> str:
    return json.dumps(
        [
            {
                "type": item.type,
                "value": item.value,
                "start": item.start,
                "end": item.end,
                "token": item.token,
            }
            for item in placeholders
        ],
        ensure_ascii=False,
    )


def _is_global_glossary_enabled(*, db_path: Path) -> bool:
    config_path = project_config_path(Path(db_path).parent)
    if not config_path.exists():
        return False

    try:
        return bool(read_config(config_path).global_game_glossary_enabled)
    except Exception:
        return False


def _replace_qa_flags(
    *,
    connection,
    segment_id: str,
    target_locale: str,
    issues: list[QAIssue],
) -> None:
    connection.execute(
        text(
            """
            DELETE FROM qa_flags
            WHERE segment_id = :segment_id
              AND target_locale = :target_locale
            """
        ),
        {
            "segment_id": segment_id,
            "target_locale": target_locale,
        },
    )

    if not issues:
        return

    created_at = _utc_now_iso()
    payloads = [
        {
            "id": str(uuid4()),
            "segment_id": segment_id,
            "target_locale": target_locale,
            "type": issue.issue_type,
            "severity": issue.severity,
            "message": issue.message,
            "span_json": json.dumps(issue.span),
            "created_at": created_at,
        }
        for issue in issues
    ]
    connection.execute(
        text(
            """
            INSERT INTO qa_flags(
                id, segment_id, target_locale, type, severity,
                message, span_json, created_at
            ) VALUES (
                :id, :segment_id, :target_locale, :type, :severity,
                :message, :span_json, :created_at
            )
            """
        ),
        payloads,
    )


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
    translator: Callable[[str, str], str] | None = None,
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
    translator_fn = translator or mock_translate
    include_global_glossary = _is_global_glossary_enabled(db_path=Path(db_path))
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            glossary_terms = load_must_use_terms(
                connection=connection,
                project_id=project_id,
                locale_code=target_locale,
                include_global=include_global_glossary,
            )
            segment_rows = connection.execute(
                text(
                    """
                    SELECT id, source_locale, source_text
                    FROM segments
                    WHERE asset_id = :asset_id
                    ORDER BY row_index, id
                    """
                ),
                {"asset_id": asset_id},
            ).all()

            for row in segment_rows:
                segment_id = str(row[0])
                source_locale = str(row[1])
                source_text = str(row[2])
                protected_source = protect_text(source_text)

                connection.execute(
                    text(
                        """
                        UPDATE segments
                        SET placeholders_json = :placeholders_json
                        WHERE id = :segment_id
                        """
                    ),
                    {
                        "segment_id": segment_id,
                        "placeholders_json": _placeholder_payload(protected_source.placeholders),
                    },
                )

                if not source_text.strip():
                    _replace_qa_flags(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        issues=[],
                    )
                    continue

                enforced = enforce_must_use(
                    text=protected_source.protected,
                    terms=glossary_terms,
                )

                tm_candidate_text: str | None = None
                tm_candidate_type: str | None = None
                tm_candidate_score = 0.0
                tm_model_info: dict[str, str] | None = None

                exact_match = find_exact(
                    connection=connection,
                    project_id=project_id,
                    source_locale=source_locale,
                    target_locale=target_locale,
                    source_text=source_text,
                )
                if exact_match is not None:
                    tm_candidate_text = exact_match.target_text
                    tm_candidate_type = "tm_exact"
                    tm_candidate_score = 1.0
                    tm_model_info = {"provider": "tm", "version": "1", "match": "exact"}
                    record_tm_use(connection=connection, tm_id=exact_match.id)
                else:
                    fuzzy_hits = search_fuzzy(
                        connection=connection,
                        project_id=project_id,
                        source_locale=source_locale,
                        target_locale=target_locale,
                        source_text=source_text,
                        limit=5,
                    )
                    if fuzzy_hits and fuzzy_hits[0].score >= TM_FUZZY_THRESHOLD:
                        best_hit = fuzzy_hits[0]
                        tm_candidate_text = best_hit.target_text
                        tm_candidate_type = "tm_fuzzy"
                        tm_candidate_score = best_hit.score / 100.0
                        tm_model_info = {"provider": "tm", "version": "1", "match": "fuzzy"}
                        record_tm_use(connection=connection, tm_id=best_hit.tm_id)

                if tm_candidate_text is not None and tm_candidate_type is not None and tm_model_info is not None:
                    issues = check_placeholders_unchanged(source_text, tm_candidate_text)
                    issues.extend(check_newlines_preserved(source_text, tm_candidate_text))
                    issues.extend(
                        check_glossary_compliance(
                            enforced.expected_enforcements,
                            tm_candidate_text,
                        )
                    )
                    _replace_qa_flags(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        issues=issues,
                    )
                    upsert_candidate(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        candidate_text=tm_candidate_text,
                        candidate_type=tm_candidate_type,
                        score=tm_candidate_score,
                        model_info=tm_model_info,
                    )
                    processed += 1
                    continue

                translated_with_term_tokens = translator_fn(
                    enforced.text_with_term_tokens,
                    target_locale,
                )
                translated_with_terms = reinject_term_tokens(
                    translated_with_term_tokens,
                    enforced.term_map,
                )
                final_text = reinject(protected_source, translated_with_terms)
                issues = check_placeholders_unchanged(source_text, final_text)
                issues.extend(check_newlines_preserved(source_text, final_text))
                issues.extend(
                    check_glossary_compliance(
                        enforced.expected_enforcements,
                        final_text,
                        translated_with_tokens=translated_with_term_tokens,
                    )
                )
                _replace_qa_flags(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    issues=issues,
                )

                upsert_candidate(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    candidate_text=final_text,
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
