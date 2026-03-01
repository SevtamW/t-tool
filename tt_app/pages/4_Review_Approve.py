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

from tt_core.project.create_project import load_project_info
from tt_core.review.review_service import (
    ReviewRow,
    get_latest_candidate,
    list_assets,
    list_review_rows,
    upsert_approved_translation,
    upsert_candidate,
)


def _asset_label(asset_id: str, original_name: str | None, received_at: str) -> str:
    return f"{original_name or '(unnamed)'} | {received_at} | {asset_id[:8]}"


def _edit_key(target_locale: str, segment_id: str) -> str:
    return f"review_edit_{target_locale}_{segment_id}"


def _bulk_key(target_locale: str, segment_id: str) -> str:
    return f"review_bulk_{target_locale}_{segment_id}"


def _row_qa_messages(row: ReviewRow) -> list[str]:
    raw_messages = getattr(row, "qa_messages", [])
    if isinstance(raw_messages, list):
        return [str(item) for item in raw_messages]
    if raw_messages is None:
        return []
    return [str(raw_messages)]


def _row_has_qa_flags(row: ReviewRow) -> bool:
    explicit_flag = getattr(row, "has_qa_flags", None)
    if explicit_flag is not None:
        return bool(explicit_flag)
    return bool(_row_qa_messages(row))


def _apply_filter(rows: list[ReviewRow], filter_option: str) -> list[ReviewRow]:
    if filter_option == "show only approved":
        return [row for row in rows if row.is_approved]
    if filter_option == "show only not approved":
        return [row for row in rows if not row.is_approved]
    if filter_option == "Only rows with QA flags":
        return [row for row in rows if _row_has_qa_flags(row)]
    if filter_option == "Only changed (stale)":
        return [row for row in rows if row.is_changed]
    return rows


def _has_candidate_text(row: ReviewRow) -> bool:
    value = row.proposed_text or row.candidate_text or row.baseline_text
    return isinstance(value, str) and bool(value.strip())


def _baseline_label(row: ReviewRow) -> str:
    if row.baseline_type == "approved":
        return "Current approved"
    if row.baseline_type == "existing_target":
        return "Existing baseline"
    return "Baseline"


def _proposed_label(row: ReviewRow) -> str:
    if row.proposed_type == "change_proposed":
        return "Proposed update"
    if row.proposed_type:
        return str(row.proposed_type)
    return "Proposed target"


def _init_row_state(rows: list[ReviewRow], target_locale: str) -> None:
    for row in rows:
        edit_key = _edit_key(target_locale, row.segment_id)
        bulk_key = _bulk_key(target_locale, row.segment_id)

        if edit_key not in st.session_state:
            st.session_state[edit_key] = (
                row.approved_text
                or row.proposed_text
                or row.baseline_text
                or row.candidate_text
                or ""
            )
        if bulk_key not in st.session_state:
            st.session_state[bulk_key] = row.is_approved


def _approve_row(
    *,
    db_path: Path,
    row: ReviewRow,
    target_locale: str,
    override_text: str | None = None,
) -> bool:
    edit_key = _edit_key(target_locale, row.segment_id)

    draft_text = override_text if override_text is not None else str(st.session_state.get(edit_key, ""))
    st.session_state[edit_key] = draft_text
    if not draft_text.strip():
        st.warning(f"Row {row.row_index}: approved text cannot be empty.")
        return False

    latest = get_latest_candidate(
        db_path=db_path,
        segment_id=row.segment_id,
        target_locale=target_locale,
    )
    if latest is None or latest.candidate_text != draft_text:
        upsert_candidate(
            db_path=db_path,
            segment_id=row.segment_id,
            target_locale=target_locale,
            candidate_text=draft_text,
            candidate_type="edited",
            score=1.0,
            model_info={"provider": "human", "version": "1"},
        )

    upsert_approved_translation(
        db_path=db_path,
        segment_id=row.segment_id,
        target_locale=target_locale,
        final_text=draft_text,
        approved_by="me",
    )
    return True


def _approve_rows(*, db_path: Path, rows: list[ReviewRow], target_locale: str) -> int:
    saved = 0
    for row in rows:
        if _approve_row(
            db_path=db_path,
            row=row,
            target_locale=target_locale,
        ):
            saved += 1
    return saved


st.title("Review & Approve")

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
    st.info("No assets found for this project. Import and run a job first.")
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

rows = list_review_rows(
    db_path=db_path,
    asset_id=selected_asset_id,
    target_locale=selected_target_locale,
)

if not rows:
    st.info("No segments in this asset.")
    st.stop()

filter_options = [
    "show all",
    "show only not approved",
    "show only approved",
    "Only rows with QA flags",
    "Only changed (stale)",
]
if "review_filter_option" not in st.session_state:
    st.session_state["review_filter_option"] = "show all"

filter_option = st.selectbox(
    "Filter",
    options=filter_options,
    key="review_filter_option",
)
filtered_rows = _apply_filter(rows, filter_option)
_init_row_state(filtered_rows, selected_target_locale)

approved_count = sum(1 for row in rows if row.is_approved)
qa_flag_count = sum(1 for row in rows if _row_has_qa_flags(row))
candidate_count = sum(1 for row in rows if _has_candidate_text(row))
st.write(
    "Rows: "
    f"{len(rows)} | "
    f"With candidate: {candidate_count} | "
    f"Approved: {approved_count} | "
    f"Pending: {len(rows) - approved_count} | "
    f"QA flagged: {qa_flag_count}"
)

if candidate_count == 0:
    st.warning(
        "No candidate translations were found for this asset/target locale yet. "
        "Import baseline translations or run a job for the same asset and target locale, then refresh."
    )

if not filtered_rows and rows:
    st.warning("No rows match the current filter.")
    if st.button("Reset filter to show all"):
        st.session_state["review_filter_option"] = "show all"
        st.rerun()

table_rows = [
    {
        "row_index": row.row_index,
        "key": row.key,
        "source_old": row.source_text_old,
        "source_new": row.source_text,
        "baseline_target": row.baseline_text,
        "proposed_target": row.proposed_text,
        "decision": row.change_decision,
        "approved_text": row.approved_text,
        "qa_flags": " | ".join(_row_qa_messages(row)),
    }
    for row in filtered_rows
]
st.dataframe(table_rows, use_container_width=True)

approve_selected_col, approve_all_col = st.columns(2)
approve_selected_clicked = approve_selected_col.button("Approve selected", type="primary")
approve_all_clicked = approve_all_col.button("Approve all")

if approve_selected_clicked or approve_all_clicked:
    if approve_all_clicked:
        rows_to_approve = filtered_rows
    else:
        rows_to_approve = [
            row
            for row in filtered_rows
            if st.session_state.get(_bulk_key(selected_target_locale, row.segment_id), False)
        ]

    if not rows_to_approve:
        if approve_all_clicked:
            st.info("No visible rows to approve.")
        else:
            st.info("No rows selected for bulk approval.")
    else:
        saved = _approve_rows(
            db_path=db_path,
            rows=rows_to_approve,
            target_locale=selected_target_locale,
        )
        if saved > 0:
            st.success(f"Approved {saved} row(s).")
            st.rerun()
        if approve_all_clicked and saved == 0:
            st.info("No visible rows could be approved.")

st.subheader("Edit and approve per row")
for row in filtered_rows:
    with st.container(border=True):
        st.write(
            f"Row {row.row_index} | Key: {row.key or '-'} | Sheet: {row.sheet_name or '-'} | Segment: {row.segment_id[:8]}"
        )
        if row.source_text_old is not None:
            st.write(f"Source OLD: {row.source_text_old}")
        st.write(f"Source NEW: {row.source_text}")
        st.write(f"{_baseline_label(row)}: {row.baseline_text or '(none)'}")
        st.write(f"{_proposed_label(row)}: {row.proposed_text or '(none)'}")
        if row.change_decision:
            confidence_label = (
                f" ({row.change_confidence}%)" if row.change_confidence is not None else ""
            )
            reason_label = f" | {row.change_reason}" if row.change_reason else ""
            st.write(f"Decision: {row.change_decision}{confidence_label}{reason_label}")
        st.write(f"Approved text: {row.approved_text or '(none)'}")
        row_qa_messages = _row_qa_messages(row)
        if row_qa_messages:
            for message in row_qa_messages:
                st.warning(f"QA: {message}")

        st.text_area(
            "Edit target text",
            key=_edit_key(selected_target_locale, row.segment_id),
            height=120,
        )

        action_proposed_col, action_keep_col, action_edit_col = st.columns(3)
        if action_proposed_col.button(
            "Approve proposed",
            key=f"approve_proposed_{selected_target_locale}_{row.segment_id}",
            disabled=not bool((row.proposed_text or "").strip()),
        ):
            if _approve_row(
                db_path=db_path,
                row=row,
                target_locale=selected_target_locale,
                override_text=row.proposed_text or "",
            ):
                st.success(f"Row {row.row_index} approved from proposed text.")
                st.rerun()
        if action_keep_col.button(
            "Keep baseline",
            key=f"keep_baseline_{selected_target_locale}_{row.segment_id}",
            disabled=not bool((row.baseline_text or "").strip()),
        ):
            if _approve_row(
                db_path=db_path,
                row=row,
                target_locale=selected_target_locale,
                override_text=row.baseline_text or "",
            ):
                st.success(f"Row {row.row_index} kept and approved.")
                st.rerun()
        if action_edit_col.button(
            "Edit + approve",
            key=f"approve_row_{selected_target_locale}_{row.segment_id}",
        ):
            if _approve_row(
                db_path=db_path,
                row=row,
                target_locale=selected_target_locale,
            ):
                st.success(f"Row {row.row_index} approved.")
                st.rerun()

        st.checkbox(
            "Select for bulk approve",
            key=_bulk_key(selected_target_locale, row.segment_id),
        )
