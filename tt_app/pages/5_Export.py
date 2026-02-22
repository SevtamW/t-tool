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

from tt_core.export.export_patch import export_patch_file
from tt_core.project.create_project import load_project_info
from tt_core.review.review_service import list_assets


def _asset_label(asset_id: str, original_name: str | None, received_at: str) -> str:
    return f"{original_name or '(unnamed)'} | {received_at} | {asset_id[:8]}"


st.title("Export Patch")

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
    _asset_label(item.id, item.original_name, item.received_at): item.id for item in assets
}
default_asset_id = st.session_state.get("selected_asset_id")
label_options = list(asset_labels.keys())
default_asset_index = 0
if default_asset_id:
    for idx, label in enumerate(label_options):
        if asset_labels[label] == default_asset_id:
            default_asset_index = idx
            break

selected_asset_label = st.selectbox("Asset", options=label_options, index=default_asset_index)
selected_asset_id = asset_labels[selected_asset_label]

target_locales = [locale for locale in project.enabled_locales if locale != project.source_locale]
if not target_locales:
    st.error("No enabled target locales found. Add at least one non-source locale.")
    st.stop()

default_target = st.session_state.get("selected_target_locale", project.target_locale)
target_index = target_locales.index(default_target) if default_target in target_locales else 0
selected_target_locale = st.selectbox("Target locale", options=target_locales, index=target_index)

file_format = st.selectbox("Format", options=["XLSX", "CSV"], index=0)
filename_prefix = st.text_input("Filename prefix", value="patch")

if st.button("Export", type="primary"):
    try:
        result = export_patch_file(
            db_path=db_path,
            project_slug=project.slug,
            project_path=project.project_path,
            asset_id=selected_asset_id,
            target_locale=selected_target_locale,
            file_format=file_format.lower(),
            filename_prefix=filename_prefix.strip() or "patch",
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Export failed: {exc}")
        st.stop()

    st.session_state["last_export_path"] = str(result.path)
    st.session_state["last_export_format"] = result.file_format
    st.success(f"Exported {result.row_count} row(s)")

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
            "Download patch file",
            data=export_path.read_bytes(),
            file_name=export_path.name,
            mime=mime_type,
        )
        st.write(f"Saved path: {export_path}")

