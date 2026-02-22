from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from tt_core.importers.import_service import ColumnMapping, import_asset
from tt_core.importers.xlsx_reader import read_tabular_data
from tt_core.jobs.job_service import run_mock_translation_job
from tt_core.project.create_project import create_project, load_project_info
from tt_core.qa.placeholder_firewall import (
    extract_placeholders,
    protect_text,
    reinject,
    validate_placeholders,
)


def _drop_placeholder_tokens(text: str, _target_locale: str) -> str:
    return re.sub(r"⟦PH_\d+⟧", "", text)


def _setup_project(tmp_path: Path, project_name: str) -> tuple[Path, object]:
    projects_root = tmp_path / "projects"
    created = create_project(project_name, root=projects_root)
    project = load_project_info(created.slug, root=projects_root)
    return created.db_path, project


def _import_csv_asset_with_placeholders(*, db_path: Path, project: object) -> str:
    dataframe = pd.DataFrame(
        {
            "EN": ["Hello {0}", "Damage %1$s dealt"],
            "Key": ["hello", "damage"],
        }
    )
    file_bytes = b"EN,Key\nHello {0},hello\nDamage %1$s dealt,damage\n"
    summary = import_asset(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=dataframe,
        file_type="csv",
        original_name="sample.csv",
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


def _import_xlsx_asset_with_placeholders(*, tmp_path: Path, db_path: Path, project: object) -> str:
    dataframe = pd.DataFrame(
        {
            "EN": [
                r"Deal {0} DMG\n<color=#fff>Now</color>",
                "Use <b>{playerName}</b> and %s",
            ],
            "Key": ["line_1", "line_2"],
        }
    )

    xlsx_path = tmp_path / "ticket4_fixture.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Sheet1")

    file_bytes = xlsx_path.read_bytes()
    loaded = read_tabular_data(file_type="xlsx", file_bytes=file_bytes, sheet_name="Sheet1")
    summary = import_asset(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=loaded,
        file_type="xlsx",
        original_name=xlsx_path.name,
        column_mapping=ColumnMapping(
            source="EN",
            target=None,
            cn=None,
            key="Key",
            char_limit=None,
            context=[],
        ),
        sheet_name="Sheet1",
        file_bytes=file_bytes,
        storage_path=None,
        size_bytes=len(file_bytes),
    )
    return summary.asset_id


def test_placeholder_extract_protect_reinject_round_trip() -> None:
    source = r"Deal {0} DMG\n<color=#fff>Now</color>"

    placeholders = extract_placeholders(source)
    assert [item.value for item in placeholders] == ["{0}", r"\n", "<color=#fff>", "</color>"]

    protected = protect_text(source)
    translated = f"[de-DE] {protected.protected}"
    final_text = reinject(protected, translated)

    assert final_text == f"[de-DE] {source}"
    assert validate_placeholders(source, final_text) == []


def test_missing_placeholder_creates_qa_flag(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 4 QA Flags")
    asset_id = _import_csv_asset_with_placeholders(db_path=db_path, project=project)

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
        translator=_drop_placeholder_tokens,
    )

    conn = sqlite3.connect(db_path)
    try:
        qa_rows = conn.execute(
            """
            SELECT type, message
            FROM qa_flags
            WHERE target_locale = ?
            ORDER BY created_at, id
            """,
            (project.target_locale,),
        ).fetchall()
    finally:
        conn.close()

    assert qa_rows
    assert any(row[0] == "placeholder_mismatch" for row in qa_rows)
    assert any("Missing placeholder '{0}'" in row[1] for row in qa_rows)


def test_job_pipeline_preserves_placeholders_and_stores_flags_on_broken_translation(
    tmp_path: Path,
) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 4 Job Integration")
    asset_id = _import_xlsx_asset_with_placeholders(
        tmp_path=tmp_path,
        db_path=db_path,
        project=project,
    )

    result = run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
    )
    assert result.status == "done"

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT s.source_text, s.placeholders_json, tc.candidate_text
            FROM segments AS s
            INNER JOIN translation_candidates AS tc
                ON tc.segment_id = s.id
               AND tc.target_locale = ?
            WHERE s.asset_id = ?
            ORDER BY s.row_index, s.id
            """,
            (project.target_locale, asset_id),
        ).fetchall()
        assert len(rows) == 2

        for source_text, placeholders_json, candidate_text in rows:
            assert validate_placeholders(str(source_text), str(candidate_text)) == []
            stored_placeholders = json.loads(str(placeholders_json))
            extracted_values = [item.value for item in extract_placeholders(str(source_text))]
            assert [item["value"] for item in stored_placeholders] == extracted_values

        qa_count_before = conn.execute(
            """
            SELECT COUNT(*)
            FROM qa_flags
            WHERE target_locale = ?
            """,
            (project.target_locale,),
        ).fetchone()
        assert qa_count_before is not None
        assert qa_count_before[0] == 0
    finally:
        conn.close()

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
        translator=_drop_placeholder_tokens,
    )

    conn = sqlite3.connect(db_path)
    try:
        qa_count_after = conn.execute(
            """
            SELECT COUNT(*)
            FROM qa_flags
            WHERE target_locale = ?
            """,
            (project.target_locale,),
        ).fetchone()
    finally:
        conn.close()

    assert qa_count_after is not None
    assert qa_count_after[0] > 0
