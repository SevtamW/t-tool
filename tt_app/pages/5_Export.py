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

from tt_core.export.export_lp_copy import export_lp_copy_with_new_column
from tt_core.export.export_patch import export_patch_file
from tt_core.project.create_project import load_project_info
from tt_core.review.review_service import list_assets


def _asset_label(asset_id: str, original_name: str | None, received_at: str) -> str:
    return f"{original_name or '(unnamed)'} | {received_at} | {asset_id[:8]}"


def _import_copy_candidate_path(
    *,
    project_path: Path,
    asset_id: str,
    original_name: str | None,
) -> Path:
    safe_name = Path(original_name or f"{asset_id}.xlsx").name
    return project_path / "imports" / f"{asset_id}_{safe_name}"


st.title("Export")

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

db_path = project.project_path / "project.db"
assets = list_assets(db_path=db_path, project_id=project.project_id)
if not assets:
    st.info("No assets found for this project.")
    st.stop()

asset_labels = {
    _asset_label(item.id, item.original_name, item.received_at): item for item in assets
}
default_asset_id = st.session_state.get("selected_asset_id")
label_options = list(asset_labels.keys())
default_asset_index = 0
if default_asset_id:
    for idx, label in enumerate(label_options):
        if asset_labels[label].id == default_asset_id:
            default_asset_index = idx
            break

selected_asset_label = st.selectbox("Asset", options=label_options, index=default_asset_index)
selected_asset = asset_labels[selected_asset_label]
selected_asset_id = selected_asset.id

target_locales = [locale for locale in project.enabled_locales if locale != project.source_locale]
if not target_locales:
    st.error("No enabled target locales found. Add at least one non-source locale.")
    st.stop()

default_target = st.session_state.get("selected_target_locale", project.target_locale)
target_index = target_locales.index(default_target) if default_target in target_locales else 0
selected_target_locale = st.selectbox("Target locale", options=target_locales, index=target_index)

export_mode = st.selectbox(
    "Export mode",
    options=["Patch table", "LP copy with NEW column"],
)

can_export_lp = True
persist_uploaded_copy = False
uploaded_xlsx_bytes: bytes | None = None
lp_source_hint: str | None = None

if export_mode == "Patch table":
    file_format = st.selectbox("Format", options=["XLSX", "CSV"], index=0)
    filename_prefix = st.text_input("Filename prefix", value="patch")
else:
    st.info("Creates a copy of the original XLSX and writes approved rows into a NEW <LANG> column.")
    file_format = "XLSX"
    filename_prefix = "lp"

    if selected_asset.asset_type.lower() != "xlsx":
        st.error("LP copy with NEW column supports only XLSX assets.")
        can_export_lp = False

    asset_has_storage_path = bool((selected_asset.storage_path or "").strip())
    storage_available = False
    if selected_asset.storage_path:
        storage_candidate = Path(selected_asset.storage_path).expanduser()
        if storage_candidate.is_file():
            storage_available = True
            lp_source_hint = f"Using storage_path source: {storage_candidate}"
        else:
            st.warning(f"storage_path not found on disk: {storage_candidate}")

    imports_candidate = _import_copy_candidate_path(
        project_path=project.project_path,
        asset_id=selected_asset.id,
        original_name=selected_asset.original_name,
    )
    imports_copy_available = imports_candidate.is_file()
    if not storage_available and imports_copy_available:
        lp_source_hint = f"Using stored imports copy: {imports_candidate}"

    uploaded_map = st.session_state.get("uploaded_xlsx_bytes_by_asset", {})
    if isinstance(uploaded_map, dict):
        maybe_bytes = uploaded_map.get(selected_asset.id)
        if isinstance(maybe_bytes, bytes):
            uploaded_xlsx_bytes = maybe_bytes

    if not asset_has_storage_path:
        if uploaded_xlsx_bytes is not None:
            persist_uploaded_copy = st.checkbox(
                "Store a copy of uploaded XLSX inside project imports/",
                value=False,
            )
        else:
            st.checkbox(
                "Store a copy of uploaded XLSX inside project imports/",
                value=False,
                disabled=True,
            )
            st.caption("Uploaded XLSX bytes are not available in this session.")

    if persist_uploaded_copy and uploaded_xlsx_bytes is None:
        st.error("Cannot store uploaded copy because uploaded XLSX bytes are not available.")
        can_export_lp = False

    has_on_disk_source = storage_available or imports_copy_available
    if not has_on_disk_source and not (persist_uploaded_copy and uploaded_xlsx_bytes is not None):
        st.error("Original XLSX not available; use Patch Export instead.")
        can_export_lp = False
        if uploaded_xlsx_bytes is not None and not asset_has_storage_path:
            st.caption("Enable copy storage to proceed with LP export.")
    elif not has_on_disk_source and persist_uploaded_copy and uploaded_xlsx_bytes is not None:
        st.caption("Export will persist uploaded XLSX bytes into project imports/ and use that copy.")

    if lp_source_hint:
        st.caption(lp_source_hint)

if st.button("Export", type="primary"):
    try:
        if export_mode == "Patch table":
            result = export_patch_file(
                db_path=db_path,
                project_slug=project.slug,
                project_path=project.project_path,
                asset_id=selected_asset_id,
                target_locale=selected_target_locale,
                file_format=file_format.lower(),
                filename_prefix=filename_prefix.strip() or "patch",
            )
            st.session_state["last_export_path"] = str(result.path)
            st.session_state["last_export_format"] = result.file_format
            st.success(f"Exported {result.row_count} row(s)")
        else:
            if not can_export_lp:
                st.error("LP copy export cannot run for the current asset state.")
                st.stop()

            lp_result = export_lp_copy_with_new_column(
                db_path=db_path,
                project_slug=project.slug,
                project_path=project.project_path,
                asset_id=selected_asset_id,
                target_locale=selected_target_locale,
                uploaded_xlsx_bytes=uploaded_xlsx_bytes,
                store_uploaded_copy=persist_uploaded_copy,
            )
            st.session_state["last_export_path"] = str(lp_result.path)
            st.session_state["last_export_format"] = "xlsx"
            st.success(
                f"Exported {lp_result.row_count} approved row(s) into column '{lp_result.new_column_name}'."
            )
            st.write(f"Source file used: {lp_result.source_path}")
            for warning in lp_result.warnings:
                st.warning(warning)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Export failed: {exc}")
        st.stop()

last_export_path = st.session_state.get("last_export_path")
last_export_format = st.session_state.get("last_export_format")

if last_export_path:
    export_path = Path(last_export_path)
    if export_path.is_file():
        mime_type = (
            "text/csv"
            if last_export_format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.download_button(
            "Download exported file",
            data=export_path.read_bytes(),
            file_name=export_path.name,
            mime=mime_type,
        )
        st.write(f"Saved path: {export_path}")
