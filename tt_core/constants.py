from __future__ import annotations

from pathlib import Path

CURRENT_SCHEMA_VERSION = 2
DEFAULT_PROJECTS_DIRNAME = "projects"
PROJECT_DB_FILENAME = "project.db"
PROJECT_CONFIG_FILENAME = "config.yml"
PROJECT_README_FILENAME = "README.txt"
PROJECT_SUBDIRS = ("imports", "exports", "cache")


def default_projects_root(cwd: Path | None = None) -> Path:
    base = cwd or Path.cwd()
    return base / DEFAULT_PROJECTS_DIRNAME
