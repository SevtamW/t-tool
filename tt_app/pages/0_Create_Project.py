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

from tt_core.project.create_project import create_project, load_project_info
from tt_core.project.paths import slugify


IMPORT_PAGE_PATH = "pages/2_Import_File.py"


def _normalize_projects_root(raw_value: str, fallback_value: str) -> Path:
    candidate = raw_value.strip() or fallback_value
    return Path(candidate).expanduser().resolve()


def _parse_additional_target_locales(raw_value: str) -> list[str]:
    stripped = raw_value.strip()
    if not stripped:
        return []

    locales: list[str] = []
    for chunk in stripped.split(","):
        locale = chunk.strip()
        if not locale:
            raise ValueError(
                "Additional target locales must be a comma-separated list of non-empty locale codes."
            )
        locales.append(locale)

    return locales


def _validate_slug_override(raw_value: str) -> str | None:
    stripped = raw_value.strip()
    if not stripped:
        return None

    normalized = slugify(stripped)
    if normalized != stripped:
        raise ValueError("Slug override must use lowercase letters, numbers, and hyphens only.")

    return stripped


def _show_success_state() -> None:
    result = st.session_state.get("create_project_result")
    if not isinstance(result, dict):
        return

    st.success(f"Project created: {result['name']} ({result['slug']})")
    st.write(f"Project path: {result['project_path']}")
    st.write(f"Database: {result['db_path']}")
    st.write(f"Config: {result['config_path']}")

    if hasattr(st, "switch_page"):
        if st.button("Go to Import", type="primary"):
            st.switch_page(IMPORT_PAGE_PATH)
    else:
        st.info("Open the 'Import File' page from the sidebar to continue.")


st.title("Create Project")
st.write("Create a local-first project and select it for the current session.")

_show_success_state()

current_root = st.session_state.get("projects_root", "./projects")

with st.form("create_project_form"):
    project_name = st.text_input("Project name", value="")
    slug_override = st.text_input("Optional slug override", value="")
    projects_root_input = st.text_input("Projects root folder", value=current_root)
    source_locale = st.text_input("Source locale", value="en-US")
    default_target_locale = st.text_input("Default target locale", value="de-DE")
    additional_targets = st.text_input("Additional target locales (comma-separated; optional)", value="")
    enable_global_game_glossary = st.checkbox("Enable global game glossary", value=True)

    slug_preview_source = slug_override.strip() or project_name.strip()
    if slug_preview_source:
        try:
            st.caption(f"Resolved project slug: {slugify(slug_preview_source)}")
        except ValueError:
            st.caption("Resolved project slug: invalid")

    submitted = st.form_submit_button("Create Project", type="primary")

if submitted:
    st.session_state.pop("create_project_result", None)

    try:
        normalized_name = project_name.strip()
        if not normalized_name:
            raise ValueError("Project name is required.")

        normalized_source_locale = source_locale.strip()
        if not normalized_source_locale:
            raise ValueError("Source locale is required.")

        normalized_default_target_locale = default_target_locale.strip()
        if not normalized_default_target_locale:
            raise ValueError("Default target locale is required.")

        validated_slug = _validate_slug_override(slug_override)
        parsed_additional_targets = _parse_additional_target_locales(additional_targets)
        normalized_projects_root = _normalize_projects_root(projects_root_input, str(current_root))

        created = create_project(
            normalized_name,
            slug=validated_slug,
            default_source_locale=normalized_source_locale,
            default_target_locale=normalized_default_target_locale,
            targets=parsed_additional_targets,
            root=normalized_projects_root,
            global_game_glossary_enabled=enable_global_game_glossary,
        )
        project = load_project_info(created.slug, root=created.root)
    except (FileExistsError, ValueError) as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Project creation failed: {exc}")
    else:
        normalized_root = str(created.root.resolve())
        st.session_state["selected_project_slug"] = project.slug
        st.session_state["selected_project_id"] = project.project_id
        st.session_state["selected_project_source_locale"] = project.source_locale
        st.session_state["selected_project_path"] = str(project.project_path)
        st.session_state["selected_project_db_path"] = str(created.db_path)
        st.session_state["projects_root"] = normalized_root
        st.session_state["create_project_result"] = {
            "name": project.name,
            "slug": project.slug,
            "project_path": str(project.project_path),
            "db_path": str(created.db_path),
            "config_path": str(created.config_path),
        }
        st.rerun()
