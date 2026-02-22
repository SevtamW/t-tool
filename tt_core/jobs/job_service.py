from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from tt_core.db.schema import initialize_database
from tt_core.glossary.enforcer import enforce_must_use, reinject_term_tokens
from tt_core.glossary.glossary_store import load_must_use_terms
from tt_core.llm.policy import (
    DEFAULT_MODEL_BY_PROVIDER,
    ModelPolicy,
    TASK_REVIEWER,
    TASK_TRANSLATOR,
    TaskPolicy,
    get_secret,
    load_policy,
)
from tt_core.llm.prompts import DEFAULT_STYLE_HINTS, build_reviewer_prompt, build_translation_prompt
from tt_core.llm.provider_base import LLMProvider
from tt_core.llm.provider_local_stub import LocalProviderStub
from tt_core.llm.provider_mock import MockProvider
from tt_core.llm.provider_openai import OpenAIProvider
from tt_core.project.config import read_config
from tt_core.project.paths import project_config_path
from tt_core.qa.checks import (
    QAIssue,
    check_glossary_compliance,
    check_newlines_preserved,
    check_placeholders_unchanged,
)
from tt_core.qa.placeholder_firewall import Placeholder, protect_text, reinject
from tt_core.review.review_service import upsert_candidate
from tt_core.tm.tm_search import find_exact, search_fuzzy
from tt_core.tm.tm_store import record_tm_use

TM_FUZZY_THRESHOLD = 92.0
REVIEW_RISK_THRESHOLD = 5


@dataclass(slots=True)
class JobRunSummary:
    job_id: str
    project_id: str
    asset_id: str
    target_locale: str
    processed_segments: int
    status: str


@dataclass(slots=True)
class _ResolvedProvider:
    task: str
    provider_name: str
    model: str
    provider: LLMProvider
    fallback_from: str | None = None


class _LegacyTranslatorProvider(LLMProvider):
    def __init__(self, *, translator: Callable[[str, str], str], target_locale: str) -> None:
        self._translator = translator
        self._target_locale = target_locale

    def generate(
        self,
        *,
        task: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        del task
        del temperature
        del max_tokens
        return self._translator(prompt, self._target_locale)


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _latest_mapping_signature(*, db_path: Path, project_id: str) -> str | None:
    engine = initialize_database(Path(db_path))
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT signature
                    FROM schema_profiles
                    WHERE project_id = :project_id
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {"project_id": project_id},
            ).first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return str(row[0])


def _placeholder_payload(placeholders: list[Placeholder]) -> str:
    return json.dumps(
        [
            {
                "type": item.type,
                "value": item.value,
                "start": item.start,
                "end": item.end,
                "token": item.token,
            }
            for item in placeholders
        ],
        ensure_ascii=False,
    )


def _is_global_glossary_enabled(*, db_path: Path) -> bool:
    config_path = project_config_path(Path(db_path).parent)
    if not config_path.exists():
        return False

    try:
        return bool(read_config(config_path).global_game_glossary_enabled)
    except Exception:
        return False


def _load_style_hints(*, db_path: Path) -> str:
    config_path = project_config_path(Path(db_path).parent)
    if not config_path.exists():
        return DEFAULT_STYLE_HINTS

    try:
        style_hints = read_config(config_path).translation_style_hints
        normalized = str(style_hints or "").strip()
        return normalized if normalized else DEFAULT_STYLE_HINTS
    except Exception:
        return DEFAULT_STYLE_HINTS


def _replace_qa_flags(
    *,
    connection,
    segment_id: str,
    target_locale: str,
    issues: list[QAIssue],
) -> None:
    connection.execute(
        text(
            """
            DELETE FROM qa_flags
            WHERE segment_id = :segment_id
              AND target_locale = :target_locale
            """
        ),
        {
            "segment_id": segment_id,
            "target_locale": target_locale,
        },
    )

    if not issues:
        return

    created_at = _utc_now_iso()
    payloads = [
        {
            "id": str(uuid4()),
            "segment_id": segment_id,
            "target_locale": target_locale,
            "type": issue.issue_type,
            "severity": issue.severity,
            "message": issue.message,
            "span_json": json.dumps(issue.span),
            "created_at": created_at,
        }
        for issue in issues
    ]
    connection.execute(
        text(
            """
            INSERT INTO qa_flags(
                id, segment_id, target_locale, type, severity,
                message, span_json, created_at
            ) VALUES (
                :id, :segment_id, :target_locale, :type, :severity,
                :message, :span_json, :created_at
            )
            """
        ),
        payloads,
    )


def _collect_qa_issues(
    *,
    source_text: str,
    final_text: str,
    expected_enforcements,
    translated_with_tokens: str | None,
) -> list[QAIssue]:
    issues = check_placeholders_unchanged(source_text, final_text)
    issues.extend(check_newlines_preserved(source_text, final_text))
    issues.extend(
        check_glossary_compliance(
            expected_enforcements,
            final_text,
            translated_with_tokens=translated_with_tokens,
        )
    )
    return issues


def _compute_risk_score(
    *,
    source_text: str,
    char_limit: int | None,
    placeholders: list[Placeholder],
    glossary_hits: int,
) -> int:
    score = 0

    if char_limit is not None:
        score += 3
    if placeholders:
        score += 2
    if any(item.type == "angle_tag" for item in placeholders):
        score += 2
    if glossary_hits > 1:
        score += 1
    if len(source_text.strip()) < 12:
        score += 2

    return score


def _default_provider_factory(provider_name: str, model: str) -> LLMProvider:
    if provider_name == "mock":
        return MockProvider(model=model)
    if provider_name == "local":
        return LocalProviderStub(model=model)
    if provider_name == "openai":
        return OpenAIProvider(model=model)
    raise ValueError(f"Unsupported LLM provider '{provider_name}'")


def _resolve_provider(
    *,
    task: str,
    task_policy: TaskPolicy,
    provider_factory: Callable[[str, str], LLMProvider],
    strict_provider_selection: bool,
) -> _ResolvedProvider:
    provider_name = task_policy.provider
    model = task_policy.model
    fallback_from: str | None = None

    if provider_name == "openai" and not get_secret("openai_api_key"):
        if strict_provider_selection:
            raise RuntimeError(
                "OpenAI provider was selected, but openai_api_key is not configured in keyring."
            )
        provider_name = "mock"
        model = DEFAULT_MODEL_BY_PROVIDER[provider_name]
        fallback_from = "openai"

    provider = provider_factory(provider_name, model)
    return _ResolvedProvider(
        task=task,
        provider_name=provider_name,
        model=model,
        provider=provider,
        fallback_from=fallback_from,
    )


def _translator_prompt(
    *,
    provider_name: str,
    source_text: str,
    protected_text: str,
    target_locale: str,
    style_hints: str,
) -> str:
    if provider_name in {"mock", "legacy_callable"}:
        # Keep mock outputs backward-compatible with ticket 1-6 tests.
        return protected_text
    return build_translation_prompt(
        source_text=source_text,
        protected_text=protected_text,
        target_locale=target_locale,
        style_hints=style_hints,
    )


def _reviewer_prompt(
    *,
    provider_name: str,
    source_text: str,
    draft_text: str,
    target_locale: str,
    style_hints: str,
) -> str:
    if provider_name == "mock":
        return draft_text
    return build_reviewer_prompt(
        source_text=source_text,
        draft_text=draft_text,
        target_locale=target_locale,
        style_hints=style_hints,
    )


def _model_info(
    *,
    translator_provider: _ResolvedProvider,
    reviewer_provider: _ResolvedProvider | None,
    risk_score: int,
) -> dict[str, str]:
    if reviewer_provider is None:
        payload: dict[str, str] = {
            "provider": translator_provider.provider_name,
            "model": translator_provider.model,
            "risk_score": str(risk_score),
        }
        if translator_provider.fallback_from:
            payload["fallback_from"] = translator_provider.fallback_from
        return payload

    payload = {
        "provider": reviewer_provider.provider_name,
        "model": reviewer_provider.model,
        "translator_provider": translator_provider.provider_name,
        "translator_model": translator_provider.model,
        "risk_score": str(risk_score),
    }
    if translator_provider.fallback_from:
        payload["translator_fallback_from"] = translator_provider.fallback_from
    if reviewer_provider.fallback_from:
        payload["fallback_from"] = reviewer_provider.fallback_from
    return payload


def create_job(
    *,
    db_path: Path,
    project_id: str,
    asset_id: str,
    target_locale: str,
    decision_trace: dict[str, object] | None = None,
) -> str:
    job_id = str(uuid4())
    now = _utc_now_iso()
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO jobs(
                        id, project_id, asset_id, job_type, targets_json, status,
                        created_at, started_at, finished_at, summary, decision_trace_json
                    ) VALUES (
                        :id, :project_id, :asset_id, :job_type, :targets_json, :status,
                        :created_at, NULL, NULL, NULL, :decision_trace_json
                    )
                    """
                ),
                {
                    "id": job_id,
                    "project_id": project_id,
                    "asset_id": asset_id,
                    "job_type": "mock_translate",
                    "targets_json": json.dumps([target_locale]),
                    "status": "queued",
                    "created_at": now,
                    "decision_trace_json": json.dumps(decision_trace or {}),
                },
            )
    finally:
        engine.dispose()

    return job_id


def update_job_status(
    *,
    db_path: Path,
    job_id: str,
    status: str,
    summary: str | None = None,
    set_started_at: bool = False,
    set_finished_at: bool = False,
) -> None:
    now = _utc_now_iso()
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE jobs
                    SET
                        status = :status,
                        summary = :summary,
                        started_at = CASE
                            WHEN :set_started_at = 1 THEN COALESCE(started_at, :now)
                            ELSE started_at
                        END,
                        finished_at = CASE
                            WHEN :set_finished_at = 1 THEN :now
                            ELSE finished_at
                        END
                    WHERE id = :job_id
                    """
                ),
                {
                    "status": status,
                    "summary": summary,
                    "set_started_at": 1 if set_started_at else 0,
                    "set_finished_at": 1 if set_finished_at else 0,
                    "now": now,
                    "job_id": job_id,
                },
            )
    finally:
        engine.dispose()


def run_mock_translation_job(
    *,
    db_path: Path,
    project_id: str,
    asset_id: str,
    target_locale: str,
    decision_trace: dict[str, object] | None = None,
    translator: Callable[[str, str], str] | None = None,
    provider_factory: Callable[[str, str], LLMProvider] | None = None,
    strict_provider_selection: bool = False,
) -> JobRunSummary:
    mapping_signature = _latest_mapping_signature(db_path=db_path, project_id=project_id)
    merged_trace = dict(decision_trace or {})
    merged_trace.setdefault("selected_asset_id", asset_id)
    merged_trace.setdefault("mapping_signature", mapping_signature)

    job_id = create_job(
        db_path=db_path,
        project_id=project_id,
        asset_id=asset_id,
        target_locale=target_locale,
        decision_trace=merged_trace,
    )

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="running",
        summary="Job is running",
        set_started_at=True,
    )

    processed = 0
    include_global_glossary = _is_global_glossary_enabled(db_path=Path(db_path))
    style_hints = _load_style_hints(db_path=Path(db_path))
    policy: ModelPolicy = load_policy(Path(db_path).parent)
    provider_factory_fn = provider_factory or _default_provider_factory

    if translator is None:
        resolved_translator_provider = _resolve_provider(
            task=TASK_TRANSLATOR,
            task_policy=policy.translator,
            provider_factory=provider_factory_fn,
            strict_provider_selection=strict_provider_selection,
        )
    else:
        resolved_translator_provider = _ResolvedProvider(
            task=TASK_TRANSLATOR,
            provider_name="legacy_callable",
            model="callable",
            provider=_LegacyTranslatorProvider(translator=translator, target_locale=target_locale),
        )

    resolved_reviewer_provider = _resolve_provider(
        task=TASK_REVIEWER,
        task_policy=policy.reviewer,
        provider_factory=provider_factory_fn,
        strict_provider_selection=strict_provider_selection,
    )

    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            glossary_terms = load_must_use_terms(
                connection=connection,
                project_id=project_id,
                locale_code=target_locale,
                include_global=include_global_glossary,
            )
            segment_rows = connection.execute(
                text(
                    """
                    SELECT id, source_locale, source_text, char_limit
                    FROM segments
                    WHERE asset_id = :asset_id
                    ORDER BY row_index, id
                    """
                ),
                {"asset_id": asset_id},
            ).all()

            for row in segment_rows:
                segment_id = str(row[0])
                source_locale = str(row[1])
                source_text = str(row[2])
                char_limit = int(row[3]) if row[3] is not None else None
                protected_source = protect_text(source_text)

                connection.execute(
                    text(
                        """
                        UPDATE segments
                        SET placeholders_json = :placeholders_json
                        WHERE id = :segment_id
                        """
                    ),
                    {
                        "segment_id": segment_id,
                        "placeholders_json": _placeholder_payload(protected_source.placeholders),
                    },
                )

                if not source_text.strip():
                    _replace_qa_flags(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        issues=[],
                    )
                    continue

                enforced = enforce_must_use(
                    text=protected_source.protected,
                    terms=glossary_terms,
                )

                tm_candidate_text: str | None = None
                tm_candidate_type: str | None = None
                tm_candidate_score = 0.0
                tm_model_info: dict[str, str] | None = None

                exact_match = find_exact(
                    connection=connection,
                    project_id=project_id,
                    source_locale=source_locale,
                    target_locale=target_locale,
                    source_text=source_text,
                )
                if exact_match is not None:
                    tm_candidate_text = exact_match.target_text
                    tm_candidate_type = "tm_exact"
                    tm_candidate_score = 1.0
                    tm_model_info = {"provider": "tm", "version": "1", "match": "exact"}
                    record_tm_use(connection=connection, tm_id=exact_match.id)
                else:
                    fuzzy_hits = search_fuzzy(
                        connection=connection,
                        project_id=project_id,
                        source_locale=source_locale,
                        target_locale=target_locale,
                        source_text=source_text,
                        limit=5,
                    )
                    if fuzzy_hits and fuzzy_hits[0].score >= TM_FUZZY_THRESHOLD:
                        best_hit = fuzzy_hits[0]
                        tm_candidate_text = best_hit.target_text
                        tm_candidate_type = "tm_fuzzy"
                        tm_candidate_score = best_hit.score / 100.0
                        tm_model_info = {"provider": "tm", "version": "1", "match": "fuzzy"}
                        record_tm_use(connection=connection, tm_id=best_hit.tm_id)

                if tm_candidate_text is not None and tm_candidate_type is not None and tm_model_info is not None:
                    tm_issues = _collect_qa_issues(
                        source_text=source_text,
                        final_text=tm_candidate_text,
                        expected_enforcements=enforced.expected_enforcements,
                        translated_with_tokens=None,
                    )
                    _replace_qa_flags(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        issues=tm_issues,
                    )
                    upsert_candidate(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        candidate_text=tm_candidate_text,
                        candidate_type=tm_candidate_type,
                        score=tm_candidate_score,
                        model_info=tm_model_info,
                    )
                    processed += 1
                    continue

                translator_prompt = _translator_prompt(
                    provider_name=resolved_translator_provider.provider_name,
                    source_text=source_text,
                    protected_text=enforced.text_with_term_tokens,
                    target_locale=target_locale,
                    style_hints=style_hints,
                )
                translated_with_term_tokens = resolved_translator_provider.provider.generate(
                    task=target_locale
                    if resolved_translator_provider.provider_name == "mock"
                    else TASK_TRANSLATOR,
                    prompt=translator_prompt,
                    temperature=0.1,
                    max_tokens=512,
                )
                translated_with_terms = reinject_term_tokens(
                    translated_with_term_tokens,
                    enforced.term_map,
                )
                draft_text = reinject(protected_source, translated_with_terms)

                # Always run QA after translator.
                draft_issues = _collect_qa_issues(
                    source_text=source_text,
                    final_text=draft_text,
                    expected_enforcements=enforced.expected_enforcements,
                    translated_with_tokens=translated_with_term_tokens,
                )

                risk_score = _compute_risk_score(
                    source_text=source_text,
                    char_limit=char_limit,
                    placeholders=protected_source.placeholders,
                    glossary_hits=len(enforced.expected_enforcements),
                )

                final_text = draft_text
                final_issues = draft_issues
                final_candidate_type = "llm_draft"
                final_model_info = _model_info(
                    translator_provider=resolved_translator_provider,
                    reviewer_provider=None,
                    risk_score=risk_score,
                )

                if risk_score >= REVIEW_RISK_THRESHOLD:
                    reviewer_prompt = _reviewer_prompt(
                        provider_name=resolved_reviewer_provider.provider_name,
                        source_text=source_text,
                        draft_text=translated_with_term_tokens,
                        target_locale=target_locale,
                        style_hints=style_hints,
                    )
                    reviewed_with_term_tokens = resolved_reviewer_provider.provider.generate(
                        task=TASK_REVIEWER,
                        prompt=reviewer_prompt,
                        temperature=0.0,
                        max_tokens=512,
                    )
                    reviewed_with_terms = reinject_term_tokens(
                        reviewed_with_term_tokens,
                        enforced.term_map,
                    )
                    reviewed_text = reinject(protected_source, reviewed_with_terms)

                    # Always run QA after reviewer as well.
                    final_issues = _collect_qa_issues(
                        source_text=source_text,
                        final_text=reviewed_text,
                        expected_enforcements=enforced.expected_enforcements,
                        translated_with_tokens=reviewed_with_term_tokens,
                    )
                    final_text = reviewed_text
                    final_candidate_type = "llm_reviewed"
                    final_model_info = _model_info(
                        translator_provider=resolved_translator_provider,
                        reviewer_provider=resolved_reviewer_provider,
                        risk_score=risk_score,
                    )

                _replace_qa_flags(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    issues=final_issues,
                )

                upsert_candidate(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    candidate_text=final_text,
                    candidate_type=final_candidate_type,
                    score=1.0,
                    model_info=final_model_info,
                )
                processed += 1
    except Exception as exc:
        update_job_status(
            db_path=db_path,
            job_id=job_id,
            status="failed",
            summary=f"Job failed: {exc}",
            set_finished_at=True,
        )
        raise
    finally:
        engine.dispose()

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="done",
        summary=f"Processed {processed} segment(s) for {target_locale}",
        set_finished_at=True,
    )

    return JobRunSummary(
        job_id=job_id,
        project_id=project_id,
        asset_id=asset_id,
        target_locale=target_locale,
        processed_segments=processed,
        status="done",
    )
