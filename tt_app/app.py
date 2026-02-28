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

st.set_page_config(page_title="t-tool Importer", layout="wide")

if "projects_root" not in st.session_state:
    st.session_state["projects_root"] = "./projects"

st.title("t-tool Importer MVP")
st.write("Use the left sidebar to select a project and import an XLSX/CSV file.")

selected_slug = st.session_state.get("selected_project_slug")
selected_root = st.session_state.get("projects_root", "./projects")

if selected_slug:
    st.success(f"Selected project: {selected_slug} (root: {selected_root})")
else:
    st.info("No project selected yet. Open the 'Select Project' page.")
