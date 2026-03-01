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

from tt_core.jobs.job_service import (
    run_change_variant_a_job,
    run_change_variant_b_job,
    run_mock_translation_job,
)
from tt_core.project.create_project import load_project_info
from tt_core.review.review_service import list_assets, list_changed_segments, list_segments


def _asset_label(asset_id: str, original_name: str | None, received_at: str) -> str:
    return f"{original_name or '(unnamed)'} | {received_at} | {asset_id[:8]}"


LAST_JOB_SUMMARY_KEY = "run_job_last_summary"
LAST_CHANGE_VARIANT_A_JOB_SUMMARY_KEY = "run_change_variant_a_job_last_summary"
LAST_CHANGE_JOB_SUMMARY_KEY = "run_change_job_last_summary"


st.title("Run Job")

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
    st.info("No assets found for this project. Import an XLSX/CSV on page 2 first.")
    st.stop()

asset_labels = {
    _asset_label(item.id, item.original_name, item.received_at): item.id for item in assets
}
selected_asset_label = st.selectbox("Asset", options=list(asset_labels.keys()))
selected_asset_id = asset_labels[selected_asset_label]

target_locales = [locale for locale in project.enabled_locales if locale != project.source_locale]
if not target_locales:
    st.error("No enabled target locales found. Add at least one non-source locale.")
    st.stop()

default_target = project.target_locale if project.target_locale in target_locales else target_locales[0]
selected_target_locale = st.selectbox(
    "Target locale",
    options=target_locales,
    index=target_locales.index(default_target),
)

segments = list_segments(db_path=db_path, asset_id=selected_asset_id)
segment_count = len(segments)
changed_count = len(list_changed_segments(db_path=db_path, asset_id=selected_asset_id))
st.write(f"Segments in selected asset: {segment_count} | Changed rows: {changed_count}")

translation_col, change_a_col, change_b_col = st.columns(3)
run_translation_clicked = translation_col.button("Run translation", type="primary")
run_change_variant_a_clicked = change_a_col.button("Run Change Job (Variant A)")
run_change_clicked = change_b_col.button("Run Change Review (Variant B)")

if run_translation_clicked:
    try:
        with st.spinner("Running translation job..."):
            result = run_mock_translation_job(
                db_path=db_path,
                project_id=project.project_id,
                asset_id=selected_asset_id,
                target_locale=selected_target_locale,
                decision_trace={"page": "3_Run_Job"},
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to run job: {exc}")
        st.stop()

    st.session_state["selected_asset_id"] = selected_asset_id
    st.session_state["selected_target_locale"] = selected_target_locale
    st.session_state[LAST_JOB_SUMMARY_KEY] = {
        "project_slug": project.slug,
        "asset_id": selected_asset_id,
        "target_locale": result.target_locale,
        "job_id": result.job_id,
        "processed_segments": result.processed_segments,
        "status": result.status,
    }

if run_change_variant_a_clicked:
    try:
        with st.spinner("Running change fill job..."):
            result = run_change_variant_a_job(
                db_path=db_path,
                project_id=project.project_id,
                asset_id=selected_asset_id,
                target_locale=selected_target_locale,
                decision_trace={"page": "3_Run_Job", "mode": "change_variant_a"},
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to run change fill job: {exc}")
        st.stop()

    st.session_state["selected_asset_id"] = selected_asset_id
    st.session_state["selected_target_locale"] = selected_target_locale
    st.session_state[LAST_CHANGE_VARIANT_A_JOB_SUMMARY_KEY] = {
        "project_slug": project.slug,
        "asset_id": selected_asset_id,
        "target_locale": result.target_locale,
        "job_id": result.job_id,
        "changed_segments": result.changed_segments,
        "proposals_created": result.proposals_created,
        "status": result.status,
    }

if run_change_clicked:
    try:
        with st.spinner("Running change review job..."):
            result = run_change_variant_b_job(
                db_path=db_path,
                project_id=project.project_id,
                asset_id=selected_asset_id,
                target_locale=selected_target_locale,
                decision_trace={"page": "3_Run_Job", "mode": "change_variant_b"},
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to run change review job: {exc}")
        st.stop()

    st.session_state["selected_asset_id"] = selected_asset_id
    st.session_state["selected_target_locale"] = selected_target_locale
    st.session_state[LAST_CHANGE_JOB_SUMMARY_KEY] = {
        "project_slug": project.slug,
        "asset_id": selected_asset_id,
        "target_locale": result.target_locale,
        "job_id": result.job_id,
        "changed_segments": result.changed_segments,
        "keep_count": result.keep_count,
        "update_count": result.update_count,
        "flag_count": result.flag_count,
        "status": result.status,
    }

last_job_summary = st.session_state.get(LAST_JOB_SUMMARY_KEY)
if (
    isinstance(last_job_summary, dict)
    and last_job_summary.get("project_slug") == project.slug
    and last_job_summary.get("asset_id") == selected_asset_id
    and last_job_summary.get("target_locale") == selected_target_locale
):
    st.success("Translation job completed")
    st.caption("Last completed job")
    st.write(f"Job ID: {last_job_summary['job_id']}")
    st.write(f"Target locale: {last_job_summary['target_locale']}")
    st.write(f"Segments processed: {last_job_summary['processed_segments']}")
    st.write(f"Status: {last_job_summary['status']}")

last_change_variant_a_job_summary = st.session_state.get(LAST_CHANGE_VARIANT_A_JOB_SUMMARY_KEY)
if (
    isinstance(last_change_variant_a_job_summary, dict)
    and last_change_variant_a_job_summary.get("project_slug") == project.slug
    and last_change_variant_a_job_summary.get("asset_id") == selected_asset_id
    and last_change_variant_a_job_summary.get("target_locale") == selected_target_locale
):
    st.success("Change fill job completed")
    st.caption("Last completed change fill")
    st.write(f"Job ID: {last_change_variant_a_job_summary['job_id']}")
    st.write(f"Changed rows: {last_change_variant_a_job_summary['changed_segments']}")
    st.write(f"Proposals created: {last_change_variant_a_job_summary['proposals_created']}")
    st.write(f"Status: {last_change_variant_a_job_summary['status']}")

last_change_job_summary = st.session_state.get(LAST_CHANGE_JOB_SUMMARY_KEY)
if (
    isinstance(last_change_job_summary, dict)
    and last_change_job_summary.get("project_slug") == project.slug
    and last_change_job_summary.get("asset_id") == selected_asset_id
    and last_change_job_summary.get("target_locale") == selected_target_locale
):
    st.success("Change review job completed")
    st.caption("Last completed change review")
    st.write(f"Job ID: {last_change_job_summary['job_id']}")
    st.write(f"Changed rows: {last_change_job_summary['changed_segments']}")
    st.write(f"KEEP: {last_change_job_summary['keep_count']}")
    st.write(f"UPDATE: {last_change_job_summary['update_count']}")
    st.write(f"FLAG: {last_change_job_summary['flag_count']}")
    st.write(f"Status: {last_change_job_summary['status']}")
