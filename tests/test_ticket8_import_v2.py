from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from tt_core.db.engine import create_sqlite_engine
from tt_core.db.migrations import _migration_v1, _migration_v2, _set_schema_version
from tt_core.db.schema import initialize_database
from tt_core.importers.import_service import ColumnMapping, import_asset
from tt_core.importers.xlsx_reader import read_tabular_data
from tt_core.project.create_project import create_project, load_project_info


def test_migration_v3_adds_source_text_old_column(tmp_path: Path) -> None:
    db_path = tmp_path / "v2_project.db"
    engine = create_sqlite_engine(db_path)
    try:
        with engine.begin() as connection:
            _migration_v1(connection)
            _migration_v2(connection)
            _set_schema_version(connection, 2)
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
        assert schema_version[0] == "3"

        segment_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(segments)").fetchall()
        }
        assert "source_text_old" in segment_columns
    finally:
        conn.close()


def test_import_lp_mode_creates_existing_target_baseline_candidates(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    created = create_project("Ticket 8 LP", root=projects_root)
    project = load_project_info(created.slug, root=projects_root)

    dataframe = pd.DataFrame(
        {
            "EN": ["Hello", "Goodbye", ""],
            "DE": ["Hallo", "", "Ignorieren"],
            "Key": ["welcome", "bye", "skip"],
        }
    )

    xlsx_path = tmp_path / "lp_import.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Sheet1")

    file_bytes = xlsx_path.read_bytes()
    loaded = read_tabular_data(file_type="xlsx", file_bytes=file_bytes, sheet_name="Sheet1")

    summary = import_asset(
        db_path=created.db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=loaded,
        file_type="xlsx",
        original_name=xlsx_path.name,
        column_mapping=ColumnMapping(
            mode="lp",
            source_new="EN",
            target="DE",
            target_locale="de-DE",
            key="Key",
        ),
        sheet_name="Sheet1",
        file_bytes=file_bytes,
        size_bytes=len(file_bytes),
    )

    assert summary.imported_rows == 2
    assert summary.skipped_rows == 1

    conn = sqlite3.connect(created.db_path)
    try:
        segment_rows = conn.execute(
            """
            SELECT source_text, source_text_old
            FROM segments
            ORDER BY row_index
            """
        ).fetchall()
        assert segment_rows == [("Hello", None), ("Goodbye", None)]

        candidate_rows = conn.execute(
            """
            SELECT target_locale, candidate_text, candidate_type, score, model_info_json
            FROM translation_candidates
            ORDER BY generated_at, id
            """
        ).fetchall()
        assert len(candidate_rows) == 1
        assert candidate_rows[0][0] == "de-DE"
        assert candidate_rows[0][1] == "Hallo"
        assert candidate_rows[0][2] == "existing_target"
        assert candidate_rows[0][3] == 1.0
        assert json.loads(candidate_rows[0][4]) == {"provider": "import", "kind": "baseline"}

        approved_count = conn.execute(
            "SELECT COUNT(*) FROM approved_translations"
        ).fetchone()
        assert approved_count is not None
        assert approved_count[0] == 0
    finally:
        conn.close()


def test_import_change_mode_stores_source_old_and_source_new(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    created = create_project("Ticket 8 Change", root=projects_root)
    project = load_project_info(created.slug, root=projects_root)

    dataframe = pd.DataFrame(
        {
            "EN-OLD": ["Attack", "Defend"],
            "EN-NEW": ["Attack now", "Defend now"],
            "DE": ["Angriff", "Verteidigen"],
        }
    )

    summary = import_asset(
        db_path=created.db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=dataframe,
        file_type="csv",
        original_name="change.csv",
        column_mapping=ColumnMapping(
            mode="change_source_update",
            source_new="EN-NEW",
            source_old="EN-OLD",
            target="DE",
            target_locale="de-DE",
        ),
        file_bytes=b"EN-OLD,EN-NEW,DE\nAttack,Attack now,Angriff\nDefend,Defend now,Verteidigen\n",
        size_bytes=75,
    )

    assert summary.imported_rows == 2
    assert summary.skipped_rows == 0

    conn = sqlite3.connect(created.db_path)
    try:
        rows = conn.execute(
            """
            SELECT source_text_old, source_text
            FROM segments
            ORDER BY row_index
            """
        ).fetchall()
        assert rows == [("Attack", "Attack now"), ("Defend", "Defend now")]

        schema_row = conn.execute(
            "SELECT mapping_json FROM schema_profiles LIMIT 1"
        ).fetchone()
        assert schema_row is not None

        mapping_json = json.loads(schema_row[0])
        assert mapping_json["mode"] == "change_source_update"
        assert mapping_json["columns"]["source_new"] == "EN-NEW"
        assert mapping_json["columns"]["source_old"] == "EN-OLD"
        assert mapping_json["columns"]["target"] == "DE"
        assert mapping_json["columns"]["target_locale"] == "de-DE"
    finally:
        conn.close()
