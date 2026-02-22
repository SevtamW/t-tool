from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml
from typer.testing import CliRunner

from tt_cli.main import app

runner = CliRunner()


def _collect_keys(value: object) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_collect_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_collect_keys(item))
    return keys


def test_create_project_creates_expected_files_and_directories(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"

    result = runner.invoke(
        app,
        [
            "create-project",
            "My Project",
            "--source",
            "en-US",
            "--target",
            "de-DE",
            "--targets",
            "de-DE,fr-FR",
            "--root",
            str(projects_root),
        ],
    )

    assert result.exit_code == 0, result.output

    project_dir = projects_root / "my-project"
    assert project_dir.is_dir()
    assert (project_dir / "imports").is_dir()
    assert (project_dir / "exports").is_dir()
    assert (project_dir / "cache").is_dir()
    assert (project_dir / "config.yml").is_file()
    assert (project_dir / "README.txt").is_file()
    assert (project_dir / "project.db").is_file()



def test_project_db_and_config_are_initialized(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"

    create_result = runner.invoke(
        app,
        [
            "create-project",
            "Localization Base",
            "--source",
            "en-US",
            "--target",
            "de-DE",
            "--targets",
            "de-DE,fr-FR",
            "--root",
            str(projects_root),
        ],
    )
    assert create_result.exit_code == 0, create_result.output

    project_dir = projects_root / "localization-base"
    db_path = project_dir / "project.db"

    conn = sqlite3.connect(db_path)
    try:
        schema_version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert schema_version is not None
        assert schema_version[0] == "2"

        project_row = conn.execute(
            """
            SELECT name, slug, default_source_locale, default_target_locale
            FROM projects
            LIMIT 1
            """
        ).fetchone()
        assert project_row == (
            "Localization Base",
            "localization-base",
            "en-US",
            "de-DE",
        )

        locales = {
            row[0]
            for row in conn.execute(
                "SELECT locale_code FROM project_locales WHERE is_enabled = 1"
            ).fetchall()
        }
        assert locales == {"en-US", "de-DE", "fr-FR"}
    finally:
        conn.close()

    config = yaml.safe_load((project_dir / "config.yml").read_text(encoding="utf-8"))

    assert config["project_name"] == "Localization Base"
    assert config["slug"] == "localization-base"
    assert config["enabled_locales"] == ["de-DE", "fr-FR"]

    forbidden_key_names = {"api_key", "apikey", "openai_api_key", "anthropic_api_key"}
    config_keys = {key.lower() for key in _collect_keys(config)}
    assert forbidden_key_names.isdisjoint(config_keys)

    info_result = runner.invoke(
        app,
        ["project-info", "localization-base", "--root", str(projects_root)],
    )
    assert info_result.exit_code == 0, info_result.output
    assert "Schema version: 2" in info_result.output
