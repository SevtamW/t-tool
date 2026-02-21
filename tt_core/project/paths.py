from __future__ import annotations

import re
from pathlib import Path

from tt_core.constants import (
    DEFAULT_PROJECTS_DIRNAME,
    PROJECT_CONFIG_FILENAME,
    PROJECT_DB_FILENAME,
    PROJECT_README_FILENAME,
    PROJECT_SUBDIRS,
)

_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
_MULTI_DASH_PATTERN = re.compile(r"-{2,}")


def slugify(name: str) -> str:
    slug = _NON_ALNUM_PATTERN.sub("-", name.strip().lower()).strip("-")
    slug = _MULTI_DASH_PATTERN.sub("-", slug)
    if not slug:
        raise ValueError("Unable to generate a valid slug from project name.")
    return slug


def resolve_projects_root(root: Path | None = None) -> Path:
    if root is None:
        return Path.cwd() / DEFAULT_PROJECTS_DIRNAME
    return Path(root).expanduser()


def project_path_for_slug(slug: str, root: Path | None = None) -> Path:
    return resolve_projects_root(root) / slug


def project_db_path(project_path: Path) -> Path:
    return project_path / PROJECT_DB_FILENAME


def project_config_path(project_path: Path) -> Path:
    return project_path / PROJECT_CONFIG_FILENAME


def project_readme_path(project_path: Path) -> Path:
    return project_path / PROJECT_README_FILENAME


def ensure_project_layout(project_path: Path) -> None:
    for dirname in PROJECT_SUBDIRS:
        (project_path / dirname).mkdir(parents=True, exist_ok=True)
