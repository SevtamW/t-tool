from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str
    slug: str
    default_source_locale: str
    default_target_locale: str
    enabled_locales: list[str] = Field(default_factory=list)
    global_game_glossary_enabled: bool = True
    model_policy: dict[str, str] = Field(
        default_factory=lambda: {
            "translation": "provider_placeholder",
            "qa": "provider_placeholder",
            "schema_mapping": "provider_placeholder",
        }
    )


def write_config(config_path: Path, config: ProjectConfig) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config.model_dump(mode="python"), handle, sort_keys=False)


def read_config(config_path: Path) -> ProjectConfig:
    with config_path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    return ProjectConfig.model_validate(content)
