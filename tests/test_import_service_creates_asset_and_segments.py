from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from tt_core.importers.import_service import ColumnMapping, import_asset
from tt_core.importers.signature import compute_schema_signature
from tt_core.importers.xlsx_reader import read_tabular_data
from tt_core.project.create_project import create_project, load_project_info


def test_import_service_creates_asset_and_segments(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    created = create_project("Import Service", root=projects_root)
    project = load_project_info(created.slug, root=projects_root)

    dataframe = pd.DataFrame(
        {
            "EN": ["Hello", "", None, "Bye"],
            "CN": ["hello_cn", "ignore", None, "bye_cn"],
            "Key": ["welcome", "skip-1", "skip-2", "goodbye"],
            "CharLimit": [20, 40, None, "bad"],
            "Filename": ["ui.json", "ui.json", "ui.json", "ui2.json"],
        }
    )

    xlsx_path = tmp_path / "sample.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Sheet1")

    file_bytes = xlsx_path.read_bytes()
    loaded = read_tabular_data(file_type="xlsx", file_bytes=file_bytes, sheet_name="Sheet1")

    signature_once = compute_schema_signature("xlsx", "Sheet1", list(loaded.columns))
    signature_twice = compute_schema_signature("xlsx", "Sheet1", list(loaded.columns))
    assert signature_once == signature_twice

    summary = import_asset(
        db_path=created.db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=loaded,
        file_type="xlsx",
        original_name=xlsx_path.name,
        column_mapping=ColumnMapping(
            source="EN",
            target=None,
            cn="CN",
            key="Key",
            char_limit="CharLimit",
            context=["Filename"],
        ),
        sheet_name="Sheet1",
        file_bytes=file_bytes,
        storage_path=None,
        size_bytes=len(file_bytes),
    )

    assert summary.imported_rows == 2
    assert summary.skipped_rows == 2
    assert summary.signature == signature_once

    conn = sqlite3.connect(created.db_path)
    try:
        asset_row = conn.execute(
            """
            SELECT project_id, asset_type, original_name, source_channel, content_hash, size_bytes
            FROM assets
            """
        ).fetchone()
        assert asset_row is not None
        assert asset_row[0] == project.project_id
        assert asset_row[1] == "xlsx"
        assert asset_row[2] == "sample.xlsx"
        assert asset_row[3] == "manual"
        assert asset_row[4] is not None
        assert asset_row[5] == len(file_bytes)

        segment_rows = conn.execute(
            """
            SELECT source_text, row_index, key, cn_text, char_limit, context_json
            FROM segments
            ORDER BY row_index
            """
        ).fetchall()
        assert len(segment_rows) == 2

        assert segment_rows[0][0] == "Hello"
        assert segment_rows[0][1] == 2
        assert segment_rows[0][2] == "welcome"
        assert segment_rows[0][3] == "hello_cn"
        assert segment_rows[0][4] == 20
        assert json.loads(segment_rows[0][5]) == {"Filename": "ui.json"}

        assert segment_rows[1][0] == "Bye"
        assert segment_rows[1][1] == 5
        assert segment_rows[1][2] == "goodbye"
        assert segment_rows[1][3] == "bye_cn"
        assert segment_rows[1][4] is None
        assert json.loads(segment_rows[1][5]) == {"Filename": "ui2.json"}

        schema_row = conn.execute(
            """
            SELECT signature, mapping_json, confidence, confirmed_by_user
            FROM schema_profiles
            """
        ).fetchone()
        assert schema_row is not None
        assert schema_row[0] == signature_once
        assert schema_row[2] == 1.0
        assert schema_row[3] == 1

        mapping_json = json.loads(schema_row[1])
        assert mapping_json["file_type"] == "xlsx"
        assert mapping_json["sheet_name"] == "Sheet1"
        assert mapping_json["mode"] == "lp"
        assert mapping_json["columns"]["source_new"] == "EN"
        assert mapping_json["columns"]["source_old"] is None
        assert mapping_json["columns"]["target_locale"] is None
        assert mapping_json["columns"]["cn"] == "CN"
        assert mapping_json["columns"]["context"] == ["Filename"]
    finally:
        conn.close()
