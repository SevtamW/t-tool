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


CONFIG_FILENAME = "config.yml"
DB_FILENAME = "project.db"


def _discover_project_slugs(projects_root: Path) -> list[str]:
    if not projects_root.exists() or not projects_root.is_dir():
        return []

    slugs: list[str] = []
    for child in sorted(projects_root.iterdir()):
        if not child.is_dir():
            continue
        if (child / CONFIG_FILENAME).is_file() and (child / DB_FILENAME).is_file():
            slugs.append(child.name)

    return slugs


st.title("Select Project")

current_root = st.session_state.get("projects_root", "./projects")
root_input = st.text_input("Projects root folder", value=current_root)
projects_root = Path(root_input).expanduser()

st.session_state["projects_root"] = str(projects_root)

if not projects_root.exists():
    st.warning(f"Folder does not exist: {projects_root}")

project_slugs = _discover_project_slugs(projects_root)

if not project_slugs:
    st.info("No projects found. A valid project directory must contain config.yml and project.db.")
    st.stop()

previous_selection = st.session_state.get("selected_project_slug")
default_index = 0
if previous_selection in project_slugs:
    default_index = project_slugs.index(previous_selection)

selected_slug = st.selectbox("Project slug", options=project_slugs, index=default_index)

try:
    project = load_project_info(selected_slug, root=projects_root)
except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load project info: {exc}")
    st.stop()

st.session_state["selected_project_slug"] = selected_slug
st.session_state["selected_project_id"] = project.project_id
st.session_state["selected_project_source_locale"] = project.source_locale
st.session_state["selected_project_path"] = str(project.project_path)
st.session_state["selected_project_db_path"] = str(project.project_path / DB_FILENAME)

st.success(f"Selected project: {project.name} ({project.slug})")
st.write(f"Path: {project.project_path}")
st.write(f"Source locale: {project.source_locale}")
st.write(f"Default target locale: {project.target_locale}")
