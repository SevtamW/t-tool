from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tt_core.db.engine import create_sqlite_engine
from tt_core.db.migrations import _migration_v1, _set_schema_version
from tt_core.db.schema import initialize_database
from tt_core.importers.import_service import ColumnMapping, import_asset
from tt_core.jobs.job_service import run_mock_translation_job
from tt_core.project.create_project import create_project, load_project_info
from tt_core.review.review_service import list_segments, upsert_candidate, upsert_approved_translation
from tt_core.tm.tm_search import find_exact, search_fuzzy
from tt_core.tm.tm_store import upsert_tm_entry

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")


def _setup_project(tmp_path: Path, name: str) -> tuple[Path, object]:
    projects_root = tmp_path / "projects"
    created = create_project(name, root=projects_root)
    project = load_project_info(created.slug, root=projects_root)
    return created.db_path, project


def _import_csv_asset(*, db_path: Path, project: object, source_texts: list[str]) -> str:
    dataframe = pd.DataFrame(
        {
            "EN": source_texts,
            "Key": [f"line_{index}" for index in range(1, len(source_texts) + 1)],
        }
    )
    csv_lines = ["EN,Key"]
    for index, text in enumerate(source_texts, start=1):
        csv_lines.append(f"{text},line_{index}")
    file_bytes = ("\n".join(csv_lines) + "\n").encode("utf-8")

    summary = import_asset(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=dataframe,
        file_type="csv",
        original_name="ticket6.csv",
        column_mapping=ColumnMapping(
            source="EN",
            target=None,
            cn=None,
            key="Key",
            char_limit=None,
            context=[],
        ),
        sheet_name=None,
        file_bytes=file_bytes,
        storage_path=None,
        size_bytes=len(file_bytes),
    )
    return summary.asset_id


def test_migration_v2_creates_tm_fts_and_updates_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "v1_project.db"
    engine = create_sqlite_engine(db_path)
    try:
        with engine.begin() as connection:
            _migration_v1(connection)
            _set_schema_version(connection, 1)
    finally:
        engine.dispose()

    migrated_engine = initialize_database(db_path)
    migrated_engine.dispose()

    conn = sqlite3.connect(db_path)
    try:
        schema_version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert schema_version is not None
        assert schema_version[0] == "2"

        tm_fts_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tm_fts'"
        ).fetchone()
        assert tm_fts_row is not None
        assert tm_fts_row[0] == "tm_fts"
    finally:
        conn.close()


def test_tm_upsert_and_find_exact(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 6 Exact")

    tm_id = upsert_tm_entry(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        target_locale=project.target_locale,
        source_text="  Hello   WORLD  ",
        target_text="Hallo Welt",
        origin="approved",
    )
    match = find_exact(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        target_locale=project.target_locale,
        source_text="hello world",
    )

    assert match is not None
    assert match.id == tm_id
    assert match.target_text == "Hallo Welt"


def test_tm_search_fuzzy_reranks_top_result(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 6 Fuzzy")

    save_tm_id = upsert_tm_entry(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        target_locale=project.target_locale,
        source_text="Save game now",
        target_text="Spiel jetzt speichern",
        origin="approved",
    )
    upsert_tm_entry(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        target_locale=project.target_locale,
        source_text="Load saved game",
        target_text="Spielstand laden",
        origin="approved",
    )
    upsert_tm_entry(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        target_locale=project.target_locale,
        source_text="Open settings menu",
        target_text="Einstellungsmenü öffnen",
        origin="approved",
    )

    hits = search_fuzzy(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        target_locale=project.target_locale,
        source_text="save the game",
        limit=3,
    )
    assert hits
    assert hits[0].tm_id == save_tm_id
    assert hits[0].score >= hits[-1].score


def test_pipeline_prefers_tm_exact_after_approval_learning(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 6 Pipeline")
    first_asset_id = _import_csv_asset(db_path=db_path, project=project, source_texts=["Hello there"])
    first_segment = list_segments(db_path=db_path, asset_id=first_asset_id)[0]

    approved_text = "Hallo vom TM"
    upsert_approved_translation(
        db_path=db_path,
        segment_id=first_segment.id,
        target_locale=project.target_locale,
        final_text=approved_text,
        approved_by="me",
    )

    second_asset_id = _import_csv_asset(db_path=db_path, project=project, source_texts=["Hello there"])
    result = run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=second_asset_id,
        target_locale=project.target_locale,
    )
    assert result.status == "done"

    conn = sqlite3.connect(db_path)
    try:
        candidate_row = conn.execute(
            """
            SELECT tc.candidate_type, tc.candidate_text
            FROM translation_candidates AS tc
            INNER JOIN segments AS s
                ON s.id = tc.segment_id
            WHERE s.asset_id = ?
              AND tc.target_locale = ?
            ORDER BY tc.generated_at DESC, tc.id DESC
            LIMIT 1
            """,
            (second_asset_id, project.target_locale),
        ).fetchone()
    finally:
        conn.close()

    assert candidate_row is not None
    assert candidate_row[0] == "tm_exact"
    assert candidate_row[1] == approved_text


def test_tm_not_updated_without_approval(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 6 No Draft Learning")
    asset_id = _import_csv_asset(db_path=db_path, project=project, source_texts=["Do not learn me"])

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
    )
    segment = list_segments(db_path=db_path, asset_id=asset_id)[0]
    upsert_candidate(
        db_path=db_path,
        segment_id=segment.id,
        target_locale=project.target_locale,
        candidate_text="Entwurf ohne Freigabe",
        candidate_type="edited",
        score=1.0,
        model_info={"provider": "human", "version": "1"},
    )

    conn = sqlite3.connect(db_path)
    try:
        count_row = conn.execute("SELECT COUNT(*) FROM tm_entries").fetchone()
    finally:
        conn.close()

    assert count_row is not None
    assert count_row[0] == 0
