from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from tt_core.db.migrations import get_schema_version
from tt_core.db.schema import initialize_database
from tt_core.project.config import ProjectConfig, read_config, write_config
from tt_core.project.paths import (
    ensure_project_layout,
    project_config_path,
    project_db_path,
    project_path_for_slug,
    project_readme_path,
    resolve_projects_root,
    slugify,
)


@dataclass(slots=True)
class CreatedProject:
    name: str
    slug: str
    root: Path
    project_path: Path
    db_path: Path
    config_path: Path


@dataclass(slots=True)
class ProjectInfo:
    name: str
    slug: str
    project_id: str
    source_locale: str
    target_locale: str
    enabled_locales: list[str]
    schema_version: int
    project_path: Path


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _normalize_target_locales(default_target_locale: str, targets: list[str] | None) -> list[str]:
    return _unique_ordered([default_target_locale, *(targets or [])])


def _write_project_readme(project_path: Path) -> None:
    readme_path = project_readme_path(project_path)
    note = (
        "This project is local-first.\n"
        "Do not store API keys in config.yml or project.db.\n"
        "Future tickets will add OS keychain-backed secret handling.\n"
    )
    readme_path.write_text(note, encoding="utf-8")


def create_project(
    name: str,
    *,
    slug: str | None = None,
    default_source_locale: str = "en-US",
    default_target_locale: str = "de-DE",
    targets: list[str] | None = None,
    root: Path | None = None,
) -> CreatedProject:
    project_slug = slugify(slug if slug is not None else name)
    projects_root = resolve_projects_root(root)
    project_path = project_path_for_slug(project_slug, projects_root)

    if project_path.exists():
        raise FileExistsError(f"Project path already exists: {project_path}")

    projects_root.mkdir(parents=True, exist_ok=True)
    project_path.mkdir(parents=False, exist_ok=False)
    ensure_project_layout(project_path)

    enabled_targets = _normalize_target_locales(default_target_locale, targets)
    config = ProjectConfig(
        project_name=name,
        slug=project_slug,
        default_source_locale=default_source_locale,
        default_target_locale=default_target_locale,
        enabled_locales=enabled_targets,
    )

    config_path = project_config_path(project_path)
    write_config(config_path, config)
    _write_project_readme(project_path)

    db_path = project_db_path(project_path)
    engine = initialize_database(db_path)

    now = _utc_now_iso()
    project_id = str(uuid4())
    project_locales = _unique_ordered([default_source_locale, *enabled_targets])

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO projects(
                    id, name, slug, default_source_locale, default_target_locale, created_at, updated_at
                ) VALUES (
                    :id, :name, :slug, :default_source_locale, :default_target_locale, :created_at, :updated_at
                )
                """
            ),
            {
                "id": project_id,
                "name": name,
                "slug": project_slug,
                "default_source_locale": default_source_locale,
                "default_target_locale": default_target_locale,
                "created_at": now,
                "updated_at": now,
            },
        )

        for locale_code in project_locales:
            connection.execute(
                text(
                    """
                    INSERT INTO project_locales(
                        id, project_id, locale_code, is_enabled, is_default, rules_json
                    ) VALUES (
                        :id, :project_id, :locale_code, :is_enabled, :is_default, :rules_json
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "project_id": project_id,
                    "locale_code": locale_code,
                    "is_enabled": 1,
                    "is_default": 1 if locale_code == default_source_locale else 0,
                    "rules_json": "{}",
                },
            )

    engine.dispose()

    return CreatedProject(
        name=name,
        slug=project_slug,
        root=projects_root,
        project_path=project_path,
        db_path=db_path,
        config_path=config_path,
    )


def load_project_info(slug: str, *, root: Path | None = None) -> ProjectInfo:
    project_slug = slugify(slug)
    projects_root = resolve_projects_root(root)
    project_path = project_path_for_slug(project_slug, projects_root)

    if not project_path.exists():
        raise FileNotFoundError(f"Project does not exist: {project_path}")

    config = read_config(project_config_path(project_path))
    db_path = project_db_path(project_path)
    engine = initialize_database(db_path)

    with engine.connect() as connection:
        schema_version = get_schema_version(connection)
        project_row = connection.execute(
            text(
                """
                SELECT id, name, slug, default_source_locale, default_target_locale
                FROM projects
                WHERE slug = :slug
                LIMIT 1
                """
            ),
            {"slug": project_slug},
        ).mappings().first()

        if project_row is None:
            raise RuntimeError(
                f"No project row found in DB for slug '{project_slug}' at {project_path / 'project.db'}"
            )

        locale_rows = connection.execute(
            text(
                """
                SELECT locale_code
                FROM project_locales
                WHERE project_id = :project_id AND is_enabled = 1
                ORDER BY locale_code
                """
            ),
            {"project_id": project_row["id"]},
        ).all()

    engine.dispose()

    enabled_locales = [row[0] for row in locale_rows]

    return ProjectInfo(
        name=project_row["name"] or config.project_name,
        slug=project_row["slug"] or config.slug,
        project_id=project_row["id"],
        source_locale=project_row["default_source_locale"],
        target_locale=project_row["default_target_locale"],
        enabled_locales=enabled_locales,
        schema_version=schema_version,
        project_path=project_path,
    )
