from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import bindparam, text

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
from tt_core.qa.placeholder_firewall import (
    Placeholder,
    extract_placeholders,
    protect_text,
    reinject,
)
from tt_core.review.review_service import upsert_candidate, upsert_change_proposal
from tt_core.tm.tm_search import find_exact, search_fuzzy
from tt_core.tm.tm_store import record_tm_use

TM_FUZZY_THRESHOLD = 92.0
REVIEW_RISK_THRESHOLD = 5
CHANGE_PROPOSED_CANDIDATE_TYPES = ("change_proposed", "change_flagged_proposed")
CHANGE_QA_FLAG_TYPES = ("stale_source_change", "impact_flagged")
_CHANGE_PUNCTUATION_PATTERN = re.compile(r"[.!?:;,'\"“”‘’()\[\]{}]+")


@dataclass(slots=True)
class JobRunSummary:
    job_id: str
    project_id: str
    asset_id: str
    target_locale: str
    processed_segments: int
    status: str
    job_type: str = "mock_translate"
    changed_segments: int = 0
    keep_count: int = 0
    update_count: int = 0
    flag_count: int = 0
    proposals_created: int = 0


@dataclass(slots=True)
class _ResolvedProvider:
    task: str
    provider_name: str
    model: str
    provider: LLMProvider
    fallback_from: str | None = None


@dataclass(slots=True, frozen=True)
class _GeneratedCandidate:
    candidate_text: str
    candidate_type: str
    score: float
    model_info: dict[str, str]
    qa_issues: list[QAIssue]


@dataclass(slots=True, frozen=True)
class ChangeClassification:
    decision: str
    confidence: int
    reason: str


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


def _normalize_change_text(value: str) -> str:
    return " ".join(str(value).split())


def _strip_change_punctuation(value: str) -> str:
    without_punctuation = _CHANGE_PUNCTUATION_PATTERN.sub(" ", value)
    return _normalize_change_text(without_punctuation)


def _relative_delta(*, old_value: int, new_value: int) -> float:
    if old_value <= 0:
        return 1.0 if new_value > 0 else 0.0
    return abs(new_value - old_value) / old_value


def _change_placeholder_signature(value: str) -> list[tuple[str, str]]:
    return [(item.type, item.value) for item in extract_placeholders(value)]


def classify_change(old: str, new: str) -> ChangeClassification:
    normalized_old = _normalize_change_text(old)
    normalized_new = _normalize_change_text(new)

    if normalized_old == normalized_new:
        return ChangeClassification(
            decision="KEEP",
            confidence=98,
            reason="Whitespace-only source change.",
        )

    if _change_placeholder_signature(old) != _change_placeholder_signature(new):
        return ChangeClassification(
            decision="FLAG",
            confidence=25,
            reason="Placeholder or tag pattern changed.",
        )

    if _strip_change_punctuation(normalized_old) == _strip_change_punctuation(normalized_new):
        return ChangeClassification(
            decision="KEEP",
            confidence=92,
            reason="Only punctuation changed.",
        )

    old_length = len(normalized_old)
    new_length = len(normalized_new)
    old_words = len(normalized_old.split())
    new_words = len(normalized_new.split())

    if _relative_delta(old_value=old_length, new_value=new_length) > 0.30:
        return ChangeClassification(
            decision="UPDATE",
            confidence=78,
            reason="Source length changed significantly.",
        )

    if _relative_delta(old_value=old_words, new_value=new_words) > 0.20:
        return ChangeClassification(
            decision="UPDATE",
            confidence=78,
            reason="Source word count changed significantly.",
        )

    return ChangeClassification(
        decision="FLAG",
        confidence=45,
        reason="Source change needs manual review.",
    )


def _change_variant_a_issue() -> QAIssue:
    return QAIssue(
        issue_type="stale_source_change",
        severity="warn",
        message="Source changed from OLD to NEW. Proposed updated target for review.",
        span={
            "decision": "UPDATE",
            "confidence": 50,
            "reason": "Source changed from OLD to NEW.",
        },
    )


def _change_proposal_score(generated: _GeneratedCandidate) -> float:
    if generated.candidate_type == "tm_exact":
        return 1.0
    if generated.candidate_type == "tm_fuzzy":
        return generated.score
    return 0.5


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


def _delete_candidate_types(
    *,
    connection,
    segment_id: str,
    target_locale: str,
    candidate_types: tuple[str, ...],
) -> None:
    if not candidate_types:
        return

    connection.execute(
        text(
            """
            DELETE FROM translation_candidates
            WHERE segment_id = :segment_id
              AND target_locale = :target_locale
              AND candidate_type IN :candidate_types
            """
        ).bindparams(bindparam("candidate_types", expanding=True)),
        {
            "segment_id": segment_id,
            "target_locale": target_locale,
            "candidate_types": list(candidate_types),
        },
    )


def _delete_qa_flag_types(
    *,
    connection,
    segment_id: str,
    target_locale: str,
    flag_types: tuple[str, ...],
) -> None:
    if not flag_types:
        return

    connection.execute(
        text(
            """
            DELETE FROM qa_flags
            WHERE segment_id = :segment_id
              AND target_locale = :target_locale
              AND type IN :flag_types
            """
        ).bindparams(bindparam("flag_types", expanding=True)),
        {
            "segment_id": segment_id,
            "target_locale": target_locale,
            "flag_types": list(flag_types),
        },
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


def _generate_translation_candidate(
    *,
    connection,
    project_id: str,
    source_locale: str,
    source_text: str,
    target_locale: str,
    char_limit: int | None,
    glossary_terms,
    translator_provider: _ResolvedProvider,
    reviewer_provider: _ResolvedProvider,
    style_hints: str,
) -> _GeneratedCandidate:
    protected_source = protect_text(source_text)
    enforced = enforce_must_use(
        text=protected_source.protected,
        terms=glossary_terms,
    )

    exact_match = find_exact(
        connection=connection,
        project_id=project_id,
        source_locale=source_locale,
        target_locale=target_locale,
        source_text=source_text,
    )
    if exact_match is not None:
        record_tm_use(connection=connection, tm_id=exact_match.id)
        return _GeneratedCandidate(
            candidate_text=exact_match.target_text,
            candidate_type="tm_exact",
            score=1.0,
            model_info={"provider": "tm", "version": "1", "match": "exact"},
            qa_issues=_collect_qa_issues(
                source_text=source_text,
                final_text=exact_match.target_text,
                expected_enforcements=enforced.expected_enforcements,
                translated_with_tokens=None,
            ),
        )

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
        record_tm_use(connection=connection, tm_id=best_hit.tm_id)
        return _GeneratedCandidate(
            candidate_text=best_hit.target_text,
            candidate_type="tm_fuzzy",
            score=best_hit.score / 100.0,
            model_info={"provider": "tm", "version": "1", "match": "fuzzy"},
            qa_issues=_collect_qa_issues(
                source_text=source_text,
                final_text=best_hit.target_text,
                expected_enforcements=enforced.expected_enforcements,
                translated_with_tokens=None,
            ),
        )

    translator_prompt = _translator_prompt(
        provider_name=translator_provider.provider_name,
        source_text=source_text,
        protected_text=enforced.text_with_term_tokens,
        target_locale=target_locale,
        style_hints=style_hints,
    )
    translated_with_term_tokens = translator_provider.provider.generate(
        task=target_locale if translator_provider.provider_name == "mock" else TASK_TRANSLATOR,
        prompt=translator_prompt,
        temperature=0.1,
        max_tokens=512,
    )
    translated_with_terms = reinject_term_tokens(
        translated_with_term_tokens,
        enforced.term_map,
    )
    draft_text = reinject(protected_source, translated_with_terms)

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
        translator_provider=translator_provider,
        reviewer_provider=None,
        risk_score=risk_score,
    )

    if risk_score >= REVIEW_RISK_THRESHOLD:
        reviewer_prompt = _reviewer_prompt(
            provider_name=reviewer_provider.provider_name,
            source_text=source_text,
            draft_text=translated_with_term_tokens,
            target_locale=target_locale,
            style_hints=style_hints,
        )
        reviewed_with_term_tokens = reviewer_provider.provider.generate(
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
        final_text = reviewed_text
        final_candidate_type = "llm_reviewed"
        final_model_info = _model_info(
            translator_provider=translator_provider,
            reviewer_provider=reviewer_provider,
            risk_score=risk_score,
        )
        final_issues = _collect_qa_issues(
            source_text=source_text,
            final_text=reviewed_text,
            expected_enforcements=enforced.expected_enforcements,
            translated_with_tokens=reviewed_with_term_tokens,
        )

    return _GeneratedCandidate(
        candidate_text=final_text,
        candidate_type=final_candidate_type,
        score=1.0,
        model_info=final_model_info,
        qa_issues=final_issues,
    )


def _update_job_decision_trace(
    *,
    db_path: Path,
    job_id: str,
    decision_trace: dict[str, object],
) -> None:
    engine = initialize_database(Path(db_path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE jobs
                    SET decision_trace_json = :decision_trace_json
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "decision_trace_json": json.dumps(decision_trace),
                },
            )
    finally:
        engine.dispose()


def create_job(
    *,
    db_path: Path,
    project_id: str,
    asset_id: str,
    target_locale: str | None = None,
    target_locales: list[str] | None = None,
    job_type: str = "mock_translate",
    decision_trace: dict[str, object] | None = None,
) -> str:
    resolved_targets = target_locales
    if resolved_targets is None:
        if target_locale is None:
            raise ValueError("target_locale is required when target_locales is not provided")
        resolved_targets = [target_locale]

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
                    "job_type": job_type,
                    "targets_json": json.dumps(resolved_targets),
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
        job_type="mock_translate",
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

                generated = _generate_translation_candidate(
                    connection=connection,
                    project_id=project_id,
                    source_locale=source_locale,
                    source_text=source_text,
                    target_locale=target_locale,
                    char_limit=char_limit,
                    glossary_terms=glossary_terms,
                    translator_provider=resolved_translator_provider,
                    reviewer_provider=resolved_reviewer_provider,
                    style_hints=style_hints,
                )
                _replace_qa_flags(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    issues=generated.qa_issues,
                )

                upsert_candidate(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    candidate_text=generated.candidate_text,
                    candidate_type=generated.candidate_type,
                    score=generated.score,
                    model_info=generated.model_info,
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


def run_change_variant_a_job(
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
        job_type="change_variant_a",
        decision_trace=merged_trace,
    )

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="running",
        summary="Change fill job is running",
        set_started_at=True,
    )

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

    changed_segments = 0
    proposals_created = 0

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
                    SELECT id, source_locale, source_text, source_text_old, char_limit
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
                source_text_old = str(row[3]) if row[3] is not None else None
                char_limit = int(row[4]) if row[4] is not None else None

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

                if source_text_old is None or source_text_old.strip() == source_text.strip():
                    continue

                changed_segments += 1
                generated = _generate_translation_candidate(
                    connection=connection,
                    project_id=project_id,
                    source_locale=source_locale,
                    source_text=source_text,
                    target_locale=target_locale,
                    char_limit=char_limit,
                    glossary_terms=glossary_terms,
                    translator_provider=resolved_translator_provider,
                    reviewer_provider=resolved_reviewer_provider,
                    style_hints=style_hints,
                )
                _replace_qa_flags(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    issues=[_change_variant_a_issue(), *generated.qa_issues],
                )
                upsert_change_proposal(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    text=generated.candidate_text,
                    score=_change_proposal_score(generated),
                    model_info={
                        **generated.model_info,
                        "source_candidate_type": generated.candidate_type,
                        "workflow": "change_variant_a",
                    },
                )
                proposals_created += 1
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

    final_trace = {
        **merged_trace,
        "summary_counts": {
            "changed_rows": changed_segments,
            "proposals_created": proposals_created,
        },
    }
    _update_job_decision_trace(
        db_path=db_path,
        job_id=job_id,
        decision_trace=final_trace,
    )

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="done",
        summary=(
            f"Processed {changed_segments} changed segment(s) for {target_locale} "
            f"(proposals={proposals_created})"
        ),
        set_finished_at=True,
    )

    return JobRunSummary(
        job_id=job_id,
        project_id=project_id,
        asset_id=asset_id,
        target_locale=target_locale,
        processed_segments=proposals_created,
        status="done",
        job_type="change_variant_a",
        changed_segments=changed_segments,
        update_count=proposals_created,
        proposals_created=proposals_created,
    )


def run_change_variant_b_job(
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
    rules_used = [
        "trimmed text equality => KEEP",
        "punctuation-only change => KEEP",
        "placeholder/tag pattern change => FLAG",
        "length delta >30% => UPDATE",
        "word-count delta >20% => UPDATE",
        "fallback => FLAG",
    ]
    merged_trace = dict(decision_trace or {})
    merged_trace.setdefault("selected_asset_id", asset_id)
    merged_trace.setdefault("mapping_signature", mapping_signature)
    merged_trace.setdefault("rules_used", rules_used)

    job_id = create_job(
        db_path=db_path,
        project_id=project_id,
        asset_id=asset_id,
        target_locale=target_locale,
        job_type="change_variant_b",
        decision_trace=merged_trace,
    )

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="running",
        summary="Change review job is running",
        set_started_at=True,
    )

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

    changed_segments = 0
    keep_count = 0
    update_count = 0
    flag_count = 0

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
                    SELECT id, source_locale, source_text, source_text_old, char_limit
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
                source_text_old = str(row[3]) if row[3] is not None else None
                char_limit = int(row[4]) if row[4] is not None else None

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

                is_changed = (
                    source_text_old is not None
                    and source_text_old.strip() != source_text.strip()
                )
                if not is_changed:
                    _delete_candidate_types(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        candidate_types=CHANGE_PROPOSED_CANDIDATE_TYPES,
                    )
                    _delete_qa_flag_types(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        flag_types=CHANGE_QA_FLAG_TYPES,
                    )
                    continue

                changed_segments += 1
                if source_text_old is None:
                    classification = ChangeClassification(
                        decision="FLAG",
                        confidence=25,
                        reason="Missing previous source text.",
                    )
                else:
                    classification = classify_change(source_text_old, source_text)

                base_issue = QAIssue(
                    issue_type="stale_source_change",
                    severity="warn",
                    message=(
                        "Source changed from OLD to NEW. "
                        f"Decision: {classification.decision}. {classification.reason}"
                    ),
                    span={
                        "decision": classification.decision,
                        "confidence": classification.confidence,
                        "reason": classification.reason,
                    },
                )

                if classification.decision == "KEEP":
                    _delete_candidate_types(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        candidate_types=CHANGE_PROPOSED_CANDIDATE_TYPES,
                    )
                    _replace_qa_flags(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        issues=[base_issue],
                    )
                    keep_count += 1
                    continue

                if classification.decision == "FLAG":
                    _delete_candidate_types(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        candidate_types=CHANGE_PROPOSED_CANDIDATE_TYPES,
                    )
                    _replace_qa_flags(
                        connection=connection,
                        segment_id=segment_id,
                        target_locale=target_locale,
                        issues=[
                            base_issue,
                            QAIssue(
                                issue_type="impact_flagged",
                                severity="warn",
                                message=classification.reason,
                                span={
                                    "decision": classification.decision,
                                    "confidence": classification.confidence,
                                    "reason": classification.reason,
                                },
                            ),
                        ],
                    )
                    flag_count += 1
                    continue

                generated = _generate_translation_candidate(
                    connection=connection,
                    project_id=project_id,
                    source_locale=source_locale,
                    source_text=source_text,
                    target_locale=target_locale,
                    char_limit=char_limit,
                    glossary_terms=glossary_terms,
                    translator_provider=resolved_translator_provider,
                    reviewer_provider=resolved_reviewer_provider,
                    style_hints=style_hints,
                )
                _replace_qa_flags(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    issues=[base_issue, *generated.qa_issues],
                )
                upsert_candidate(
                    connection=connection,
                    segment_id=segment_id,
                    target_locale=target_locale,
                    candidate_text=generated.candidate_text,
                    candidate_type="change_proposed",
                    score=1.0
                    if generated.candidate_type == "tm_exact"
                    else classification.confidence / 100.0,
                    model_info={
                        **generated.model_info,
                        "change_decision": classification.decision,
                        "change_confidence": str(classification.confidence),
                        "change_reason": classification.reason,
                        "source_candidate_type": generated.candidate_type,
                    },
                )
                update_count += 1
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

    final_trace = {
        **merged_trace,
        "summary_counts": {
            "changed_rows": changed_segments,
            "keep": keep_count,
            "update": update_count,
            "flag": flag_count,
        },
    }
    _update_job_decision_trace(
        db_path=db_path,
        job_id=job_id,
        decision_trace=final_trace,
    )

    update_job_status(
        db_path=db_path,
        job_id=job_id,
        status="done",
        summary=(
            f"Reviewed {changed_segments} changed segment(s) for {target_locale} "
            f"(keep={keep_count}, update={update_count}, flag={flag_count})"
        ),
        set_finished_at=True,
    )

    return JobRunSummary(
        job_id=job_id,
        project_id=project_id,
        asset_id=asset_id,
        target_locale=target_locale,
        processed_segments=changed_segments,
        status="done",
        job_type="change_variant_b",
        changed_segments=changed_segments,
        keep_count=keep_count,
        update_count=update_count,
        flag_count=flag_count,
    )
