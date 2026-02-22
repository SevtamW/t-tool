from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from tt_core.export.export_patch import export_patch_file
from tt_core.importers.import_service import ColumnMapping, import_asset
from tt_core.jobs.job_service import run_mock_translation_job
from tt_core.project.create_project import create_project, load_project_info
from tt_core.review.review_service import (
    list_segments,
    upsert_approved_translation,
    upsert_candidate,
)


def _setup_project_with_asset(tmp_path: Path) -> tuple[Path, object, str]:
    projects_root = tmp_path / "projects"
    created = create_project("Ticket 3 Workflow", root=projects_root)
    project = load_project_info(created.slug, root=projects_root)

    dataframe = pd.DataFrame(
        {
            "EN": ["Hello", "Goodbye"],
            "CN": ["Ni Hao", "Zai Jian"],
            "Key": ["greeting", "farewell"],
        }
    )

    summary = import_asset(
        db_path=created.db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=dataframe,
        file_type="csv",
        original_name="sample.csv",
        column_mapping=ColumnMapping(
            source="EN",
            target=None,
            cn="CN",
            key="Key",
            char_limit=None,
            context=[],
        ),
        sheet_name=None,
        file_bytes=b"EN,CN,Key\nHello,Ni Hao,greeting\nGoodbye,Zai Jian,farewell\n",
        storage_path=None,
        size_bytes=None,
    )

    return created.db_path, project, summary.asset_id


def test_run_mock_job_persists_job_and_candidates(tmp_path: Path) -> None:
    db_path, project, asset_id = _setup_project_with_asset(tmp_path)

    result = run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
    )

    assert result.status == "done"
    assert result.processed_segments == 2

    conn = sqlite3.connect(db_path)
    try:
        job_row = conn.execute(
            """
            SELECT project_id, asset_id, job_type, targets_json, status
            FROM jobs
            WHERE id = ?
            """,
            (result.job_id,),
        ).fetchone()
        assert job_row is not None
        assert job_row[0] == project.project_id
        assert job_row[1] == asset_id
        assert job_row[2] == "mock_translate"
        assert job_row[3] == f'["{project.target_locale}"]'
        assert job_row[4] == "done"

        candidate_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM translation_candidates
            WHERE target_locale = ?
            """,
            (project.target_locale,),
        ).fetchone()
        assert candidate_count is not None
        assert candidate_count[0] == 2
    finally:
        conn.close()


@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
def test_approve_upsert_and_export_patch(tmp_path: Path, file_format: str) -> None:
    db_path, project, asset_id = _setup_project_with_asset(tmp_path)

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
    )

    first_segment = list_segments(db_path=db_path, asset_id=asset_id)[0]
    edited_text = "Hallo (edited)"

    upsert_candidate(
        db_path=db_path,
        segment_id=first_segment.id,
        target_locale=project.target_locale,
        candidate_text=edited_text,
        candidate_type="edited",
        score=1.0,
        model_info={"provider": "human", "version": "1"},
    )

    first_id = upsert_approved_translation(
        db_path=db_path,
        segment_id=first_segment.id,
        target_locale=project.target_locale,
        final_text=edited_text,
        approved_by="me",
    )
    second_id = upsert_approved_translation(
        db_path=db_path,
        segment_id=first_segment.id,
        target_locale=project.target_locale,
        final_text="Hallo (edited v2)",
        approved_by="me",
    )
    assert first_id == second_id

    conn = sqlite3.connect(db_path)
    try:
        approved_rows = conn.execute(
            """
            SELECT final_text
            FROM approved_translations
            WHERE segment_id = ? AND target_locale = ?
            """,
            (first_segment.id, project.target_locale),
        ).fetchall()
        assert len(approved_rows) == 1
        assert approved_rows[0][0] == "Hallo (edited v2)"
    finally:
        conn.close()

    result = export_patch_file(
        db_path=db_path,
        project_slug=project.slug,
        project_path=project.project_path,
        asset_id=asset_id,
        target_locale=project.target_locale,
        file_format=file_format,
        filename_prefix="patch",
    )

    assert result.path.exists()
    assert result.file_format == file_format
    assert result.row_count == 1
    assert result.path.parent == project.project_path / "exports"

    if file_format == "csv":
        exported = pd.read_csv(result.path)
    else:
        exported = pd.read_excel(result.path)

    expected_columns = {
        "key",
        "source_text",
        "approved_target_text",
        "row_index",
        "sheet_name",
    }
    assert expected_columns.issubset(set(exported.columns))
    assert "cn_text" in exported.columns

    row = exported.iloc[0].to_dict()
    assert row["key"] == "greeting"
    assert row["source_text"] == "Hello"
    assert row["approved_target_text"] == "Hallo (edited v2)"

