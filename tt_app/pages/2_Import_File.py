from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


def _ensure_repo_root_on_path() -> None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "tt_core").is_dir():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return


_ensure_repo_root_on_path()

from tt_core.importers import (
    ColumnMapping,
    import_asset,
    infer_file_type,
    list_xlsx_sheets,
    preview_dataframe,
    read_tabular_data,
)
from tt_core.project.create_project import load_project_info

NONE_OPTION = "(None)"


def _optional_selection(value: str) -> str | None:
    if value == NONE_OPTION:
        return None
    return value


st.title("Import XLSX/CSV")

selected_slug = st.session_state.get("selected_project_slug")
projects_root = Path(st.session_state.get("projects_root", "./projects")).expanduser()

if not selected_slug:
    st.warning("No project selected. Open the 'Select Project' page first.")
    st.stop()

try:
    project = load_project_info(selected_slug, root=projects_root)
except Exception as exc:  # noqa: BLE001
    st.error(f"Unable to load selected project: {exc}")
    st.stop()

st.write(f"Project: {project.name} ({project.slug})")
st.write(f"Source locale for segments: {project.source_locale}")

source_mode = st.radio("Input source", ["Upload file", "Local path"], horizontal=True)

file_bytes: bytes | None = None
storage_path: str | None = None
original_name: str | None = None

if source_mode == "Upload file":
    uploaded_file = st.file_uploader("Upload .xlsx or .csv", type=["xlsx", "csv"])
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        original_name = uploaded_file.name
else:
    local_path_input = st.text_input("Local file path")
    if local_path_input.strip():
        local_path = Path(local_path_input).expanduser()
        if local_path.is_file():
            file_bytes = local_path.read_bytes()
            original_name = local_path.name
            storage_path = str(local_path)
        else:
            st.error(f"File not found: {local_path}")

if file_bytes is None or original_name is None:
    st.info("Choose a file to continue.")
    st.stop()

try:
    file_type = infer_file_type(original_name)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

sheet_name: str | None = None
if file_type == "xlsx":
    try:
        sheet_options = list_xlsx_sheets(file_bytes=file_bytes)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Unable to read workbook sheets: {exc}")
        st.stop()

    if not sheet_options:
        st.error("Workbook has no sheets.")
        st.stop()

    sheet_name = st.selectbox("Sheet", options=sheet_options)

try:
    dataframe = read_tabular_data(
        file_type=file_type,
        file_bytes=file_bytes,
        sheet_name=sheet_name,
    )
except Exception as exc:  # noqa: BLE001
    st.error(f"Unable to parse file: {exc}")
    st.stop()

columns = list(dataframe.columns)
if not columns:
    st.error("No columns found in the selected sheet/file.")
    st.stop()

st.subheader("Preview")
st.dataframe(preview_dataframe(dataframe, limit=20), use_container_width=True)

st.subheader("Column Mapping")
source_column = st.selectbox("Source column (required)", options=columns)
target_column = _optional_selection(
    st.selectbox("Target column (optional)", options=[NONE_OPTION, *columns], index=0)
)
cn_column = _optional_selection(
    st.selectbox("CN column (optional)", options=[NONE_OPTION, *columns], index=0)
)
key_column = _optional_selection(
    st.selectbox("Key/ID column (optional)", options=[NONE_OPTION, *columns], index=0)
)
char_limit_column = _optional_selection(
    st.selectbox("CharLimit column (optional)", options=[NONE_OPTION, *columns], index=0)
)
context_columns = st.multiselect("Additional context columns (optional)", options=columns)

if st.button("Import", type="primary"):
    mapping = ColumnMapping(
        source=source_column,
        target=target_column,
        cn=cn_column,
        key=key_column,
        char_limit=char_limit_column,
        context=context_columns,
    )

    db_path = project.project_path / "project.db"

    try:
        summary = import_asset(
            db_path=db_path,
            project_id=project.project_id,
            source_locale=project.source_locale,
            dataframe=dataframe,
            file_type=file_type,
            original_name=original_name,
            column_mapping=mapping,
            sheet_name=sheet_name,
            file_bytes=file_bytes,
            storage_path=storage_path,
            size_bytes=len(file_bytes),
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Import failed: {exc}")
        st.stop()

    st.success("Import completed")
    st.write(f"Rows imported: {summary.imported_rows}")
    st.write(f"Rows skipped (empty source): {summary.skipped_rows}")
    st.write("Mapped columns:")
    st.json(summary.mapped_columns)

    st.session_state["selected_asset_id"] = summary.asset_id

    if source_mode == "Upload file" and file_type == "xlsx":
        uploaded_map = st.session_state.get("uploaded_xlsx_bytes_by_asset", {})
        if not isinstance(uploaded_map, dict):
            uploaded_map = {}
        uploaded_map[summary.asset_id] = file_bytes
        st.session_state["uploaded_xlsx_bytes_by_asset"] = uploaded_map
