from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from tt_core.db.schema import initialize_database


@dataclass(slots=True, frozen=True)
class GlossaryTerm:
    id: str
    project_id: str
    locale_code: str
    source_term: str
    target_term: str
    rule: str
    match_type: str
    case_sensitive: bool
    allow_compounds: bool
    compound_strategy: str
    negative_patterns: tuple[str, ...]
    notes: str | None = None


def _parse_negative_patterns(raw_value: object) -> tuple[str, ...]:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return ()

    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return ()

    if not isinstance(parsed, list):
        return ()

    patterns: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        pattern = item.strip()
        if pattern:
            patterns.append(pattern)

    return tuple(patterns)


def _row_to_term(row: dict[str, object]) -> GlossaryTerm:
    return GlossaryTerm(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        locale_code=str(row["locale_code"]),
        source_term=str(row["source_term"]),
        target_term=str(row["target_term"]),
        rule=str(row.get("rule") or "must_use").strip().lower(),
        match_type=str(row.get("match_type") or "whole_token").strip().lower(),
        case_sensitive=bool(int(row.get("case_sensitive") or 0)),
        allow_compounds=bool(int(row.get("allow_compounds") or 0)),
        compound_strategy=str(row.get("compound_strategy") or "hyphenate").strip().lower(),
        negative_patterns=_parse_negative_patterns(row.get("negative_patterns_json")),
        notes=(str(row["notes"]) if row.get("notes") is not None else None),
    )


def _load_must_use_for_project(
    *,
    connection: Connection,
    project_id: str,
    locale_code: str,
) -> dict[str, GlossaryTerm]:
    rows = connection.execute(
        text(
            """
            SELECT
                id,
                project_id,
                locale_code,
                source_term,
                target_term,
                rule,
                match_type,
                case_sensitive,
                allow_compounds,
                compound_strategy,
                negative_patterns_json,
                notes
            FROM glossary_terms
            WHERE project_id = :project_id
              AND locale_code = :locale_code
              AND rule = 'must_use'
            ORDER BY source_term, id
            """
        ),
        {"project_id": project_id, "locale_code": locale_code},
    ).mappings().all()

    output: dict[str, GlossaryTerm] = {}
    for row in rows:
        term = _row_to_term(dict(row))
        output[term.source_term] = term
    return output


def _load_must_use_terms_on_connection(
    *,
    connection: Connection,
    project_id: str,
    locale_code: str,
    include_global: bool,
) -> list[GlossaryTerm]:
    merged: dict[str, GlossaryTerm] = {}

    if include_global:
        merged.update(
            _load_must_use_for_project(
                connection=connection,
                project_id="global",
                locale_code=locale_code,
            )
        )

    merged.update(
        _load_must_use_for_project(
            connection=connection,
            project_id=project_id,
            locale_code=locale_code,
        )
    )

    return sorted(
        merged.values(),
        key=lambda item: (-len(item.source_term), item.source_term.casefold(), item.id),
    )


def load_must_use_terms(
    *,
    project_id: str,
    locale_code: str,
    include_global: bool = False,
    db_path: Path | None = None,
    connection: Connection | None = None,
) -> list[GlossaryTerm]:
    if connection is not None:
        return _load_must_use_terms_on_connection(
            connection=connection,
            project_id=project_id,
            locale_code=locale_code,
            include_global=include_global,
        )

    if db_path is None:
        raise ValueError("db_path is required when connection is not provided")

    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as local_connection:
            return _load_must_use_terms_on_connection(
                connection=local_connection,
                project_id=project_id,
                locale_code=locale_code,
                include_global=include_global,
            )
    finally:
        engine.dispose()
