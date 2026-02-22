from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from tt_core.glossary.enforcer import enforce_must_use, reinject_term_tokens
from tt_core.glossary.glossary_store import GlossaryTerm, load_must_use_terms
from tt_core.importers.import_service import ColumnMapping, import_asset
from tt_core.jobs.job_service import run_mock_translation_job
from tt_core.project.create_project import create_project, load_project_info


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _term(
    *,
    source: str,
    target: str,
    match_type: str = "whole_token",
    case_sensitive: bool = True,
    allow_compounds: bool = False,
    compound_strategy: str = "hyphenate",
    negative_patterns: tuple[str, ...] = (),
) -> GlossaryTerm:
    return GlossaryTerm(
        id="term-id",
        project_id="project-id",
        locale_code="de-DE",
        source_term=source,
        target_term=target,
        rule="must_use",
        match_type=match_type,
        case_sensitive=case_sensitive,
        allow_compounds=allow_compounds,
        compound_strategy=compound_strategy,
        negative_patterns=negative_patterns,
        notes=None,
    )


def _setup_project(tmp_path: Path, project_name: str) -> tuple[Path, object]:
    projects_root = tmp_path / "projects"
    created = create_project(project_name, root=projects_root)
    project = load_project_info(created.slug, root=projects_root)
    return created.db_path, project


def _import_asset(*, db_path: Path, project: object, source_texts: list[str]) -> str:
    dataframe = pd.DataFrame(
        {
            "EN": source_texts,
            "Key": [f"line_{index}" for index in range(1, len(source_texts) + 1)],
        }
    )
    csv_lines = ["EN,Key"]
    for index, text in enumerate(source_texts, start=1):
        csv_lines.append(f"{text},line_{index}")
    file_bytes = ("\n".join(csv_lines) + "\n").encode("utf-8")

    summary = import_asset(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=dataframe,
        file_type="csv",
        original_name="ticket5.csv",
        column_mapping=ColumnMapping(
            source="EN",
            target=None,
            cn=None,
            key="Key",
            char_limit=None,
            context=[],
        ),
        sheet_name=None,
        file_bytes=file_bytes,
        storage_path=None,
        size_bytes=len(file_bytes),
    )
    return summary.asset_id


def _insert_glossary_term(
    *,
    db_path: Path,
    project_id: str,
    locale_code: str,
    source_term: str,
    target_term: str,
    match_type: str = "whole_token",
    case_sensitive: int = 1,
    allow_compounds: int = 0,
    compound_strategy: str = "hyphenate",
    negative_patterns: tuple[str, ...] = (),
) -> None:
    now = _utc_now_iso()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO glossary_terms(
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
                notes,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                project_id,
                locale_code,
                source_term,
                target_term,
                "must_use",
                match_type,
                case_sensitive,
                allow_compounds,
                compound_strategy,
                json.dumps(list(negative_patterns)),
                None,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _drop_term_tokens(text: str, _target_locale: str) -> str:
    return re.sub(r"⟦TERM_\d+⟧", "", text)


def test_whole_token_matching_avoids_substrings() -> None:
    term = _term(source="DMG", target="SCH", case_sensitive=True)
    source = "Deal DMG and dmg. ADMGX randomg"

    enforced = enforce_must_use(text=source, terms=[term])
    restored = reinject_term_tokens(enforced.text_with_term_tokens, enforced.term_map)

    assert restored == "Deal SCH and dmg. ADMGX randomg"
    assert len(enforced.expected_enforcements) == 1
    assert enforced.expected_enforcements[0].source_term == "DMG"


def test_compound_hyphenate_and_allow_compounds_flag() -> None:
    hyphenate_term = _term(
        source="DMG",
        target="SCH",
        case_sensitive=True,
        allow_compounds=True,
        compound_strategy="hyphenate",
    )
    with_compound = enforce_must_use(text="DMGBoost", terms=[hyphenate_term])
    assert reinject_term_tokens(with_compound.text_with_term_tokens, with_compound.term_map) == "SCH-Boost"

    strict_term = _term(
        source="DMG",
        target="SCH",
        case_sensitive=True,
        allow_compounds=False,
    )
    without_compound = enforce_must_use(text="DMGBoost", terms=[strict_term])
    assert reinject_term_tokens(without_compound.text_with_term_tokens, without_compound.term_map) == "DMGBoost"
    assert without_compound.expected_enforcements == []


def test_negative_pattern_blocks_match() -> None:
    term = _term(
        source="DMG",
        target="SCH",
        negative_patterns=(".*IGNORE.*",),
    )
    source = "Deal DMG IGNORE"

    enforced = enforce_must_use(text=source, terms=[term])

    assert enforced.expected_enforcements == []
    assert reinject_term_tokens(enforced.text_with_term_tokens, enforced.term_map) == source


def test_global_glossary_is_loaded_and_project_overrides(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 5 Global Glossary")

    _insert_glossary_term(
        db_path=db_path,
        project_id="global",
        locale_code=project.target_locale,
        source_term="DMG",
        target_term="GLOBAL",
    )
    _insert_glossary_term(
        db_path=db_path,
        project_id=project.project_id,
        locale_code=project.target_locale,
        source_term="DMG",
        target_term="SCH",
    )

    loaded = load_must_use_terms(
        db_path=db_path,
        project_id=project.project_id,
        locale_code=project.target_locale,
        include_global=True,
    )

    assert len(loaded) == 1
    assert loaded[0].source_term == "DMG"
    assert loaded[0].target_term == "SCH"


def test_job_pipeline_enforces_glossary_and_has_no_glossary_qa_flags(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 5 Integration")
    asset_id = _import_asset(db_path=db_path, project=project, source_texts=["Deal DMG", "DMGBoost"])

    _insert_glossary_term(
        db_path=db_path,
        project_id=project.project_id,
        locale_code=project.target_locale,
        source_term="DMG",
        target_term="SCH",
        match_type="whole_token",
        case_sensitive=1,
        allow_compounds=1,
        compound_strategy="hyphenate",
    )

    result = run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
    )
    assert result.status == "done"

    conn = sqlite3.connect(db_path)
    try:
        candidate_rows = conn.execute(
            """
            SELECT tc.candidate_text
            FROM translation_candidates AS tc
            INNER JOIN segments AS s
                ON s.id = tc.segment_id
            WHERE s.asset_id = ?
              AND tc.target_locale = ?
            ORDER BY s.row_index, s.id
            """,
            (asset_id, project.target_locale),
        ).fetchall()
        assert [row[0] for row in candidate_rows] == [
            f"[{project.target_locale}] Deal SCH",
            f"[{project.target_locale}] SCH-Boost",
        ]

        glossary_qa_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM qa_flags
            WHERE target_locale = ?
              AND type = 'glossary_violation'
            """,
            (project.target_locale,),
        ).fetchone()
    finally:
        conn.close()

    assert glossary_qa_count is not None
    assert glossary_qa_count[0] == 0


def test_job_pipeline_flags_glossary_violation_when_term_token_removed(tmp_path: Path) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 5 Broken Translator")
    asset_id = _import_asset(db_path=db_path, project=project, source_texts=["Deal DMG", "DMGBoost"])

    _insert_glossary_term(
        db_path=db_path,
        project_id=project.project_id,
        locale_code=project.target_locale,
        source_term="DMG",
        target_term="SCH",
        match_type="whole_token",
        case_sensitive=1,
        allow_compounds=1,
        compound_strategy="hyphenate",
    )

    result = run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
        translator=_drop_term_tokens,
    )
    assert result.status == "done"

    conn = sqlite3.connect(db_path)
    try:
        violation_rows = conn.execute(
            """
            SELECT type, message
            FROM qa_flags
            WHERE target_locale = ?
            ORDER BY created_at, id
            """,
            (project.target_locale,),
        ).fetchall()
    finally:
        conn.close()

    assert violation_rows
    assert any(row[0] == "glossary_violation" for row in violation_rows)
    assert any("Glossary lock token" in row[1] for row in violation_rows)
