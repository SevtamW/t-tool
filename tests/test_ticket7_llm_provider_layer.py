from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

import tt_core.llm.policy as policy_module
from tt_core.importers.import_service import ColumnMapping, import_asset
from tt_core.jobs.job_service import run_mock_translation_job
from tt_core.llm.policy import ModelPolicy, TaskPolicy, save_policy, set_secret
from tt_core.llm.provider_base import LLMProvider
from tt_core.llm.provider_mock import MockProvider
from tt_core.project.create_project import create_project, load_project_info


class _FakeKeyring:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, name: str, value: str) -> None:
        self._store[(service, name)] = value

    def get_password(self, service: str, name: str) -> str | None:
        return self._store.get((service, name))

    def delete_password(self, service: str, name: str) -> None:
        self._store.pop((service, name), None)


class _FailBackend:
    __module__ = "keyring.backends.fail"


class _FailKeyring:
    def get_keyring(self) -> _FailBackend:
        return _FailBackend()

    def set_password(self, service: str, name: str, value: str) -> None:
        raise AssertionError("fail backend should not be used for writes")

    def get_password(self, service: str, name: str) -> str | None:
        raise AssertionError("fail backend should not be used for reads")

    def delete_password(self, service: str, name: str) -> None:
        raise AssertionError("fail backend should not be used for deletes")


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> _FakeKeyring:
    fake = _FakeKeyring()
    monkeypatch.setattr(policy_module, "keyring", fake)
    return fake


def test_mask_secret_value_only_exposes_edges() -> None:
    assert policy_module.mask_secret_value("abcd") == "****"
    assert policy_module.mask_secret_value("abcdef") == "ab**ef"
    assert policy_module.mask_secret_value("abcdefghij") == "abcd**ghij"


def test_list_secret_statuses_reports_known_stored_keys(
    fake_keyring: _FakeKeyring,
) -> None:
    policy_module.set_secret("openai_api_key", "sk-test-1234")

    statuses = {status.name: status for status in policy_module.list_secret_statuses()}

    assert "openai_api_key" in statuses
    assert statuses["openai_api_key"].label == "OpenAI API Key"
    assert statuses["openai_api_key"].is_configured is True
    assert statuses["openai_api_key"].preview == "sk-t****1234"


def test_fail_keyring_backend_is_not_treated_as_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy_module, "keyring", _FailKeyring())
    monkeypatch.setattr(policy_module.sys, "platform", "linux")
    monkeypatch.setattr(policy_module.shutil, "which", lambda name: None)

    assert policy_module.has_secret_backend() is False
    assert policy_module.describe_secret_backend() == "python-keyring:fail-backend"


def test_linux_secret_tool_fallback_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy_module, "keyring", _FailKeyring())
    monkeypatch.setattr(policy_module.sys, "platform", "linux")
    monkeypatch.setattr(
        policy_module.shutil,
        "which",
        lambda name: "/usr/bin/secret-tool" if name == "secret-tool" else None,
    )

    store: dict[tuple[tuple[str, str], ...], str] = {}

    def _attrs(parts: list[str]) -> tuple[tuple[str, str], ...]:
        return tuple((parts[index], parts[index + 1]) for index in range(0, len(parts), 2))

    def fake_run(
        args: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check

        if args[:2] == ["secret-tool", "store"]:
            attrs = _attrs(args[4:])
            store[attrs] = input or ""
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["secret-tool", "lookup"]:
            attrs = _attrs(args[2:])
            value = store.get(attrs)
            if value is None:
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, 0, value, "")
        if args[:2] == ["secret-tool", "clear"]:
            attrs = _attrs(args[2:])
            store.pop(attrs, None)
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr(policy_module.subprocess, "run", fake_run)

    assert policy_module.has_secret_backend() is True
    assert (
        policy_module.describe_secret_backend()
        == "python-keyring:fail-backend, linux-secret-service:secret-tool"
    )

    policy_module.set_secret("openai_api_key", "sk-test-ubuntu")
    assert policy_module.get_secret("openai_api_key") == "sk-test-ubuntu"

    policy_module.delete_secret("openai_api_key")
    assert policy_module.get_secret("openai_api_key") is None


def _setup_project(tmp_path: Path, name: str) -> tuple[Path, object]:
    projects_root = tmp_path / "projects"
    created = create_project(name, root=projects_root)
    project = load_project_info(created.slug, root=projects_root)
    return created.db_path, project


def _import_asset_single_segment(
    *,
    db_path: Path,
    project: object,
    source_text: str,
    char_limit: int | None = None,
) -> str:
    payload: dict[str, list[object]] = {
        "EN": [source_text],
        "Key": ["line_1"],
    }
    char_limit_column = None
    if char_limit is not None:
        payload["CharLimit"] = [char_limit]
        char_limit_column = "CharLimit"

    dataframe = pd.DataFrame(payload)
    file_bytes = dataframe.to_csv(index=False).encode("utf-8")
    summary = import_asset(
        db_path=db_path,
        project_id=project.project_id,
        source_locale=project.source_locale,
        dataframe=dataframe,
        file_type="csv",
        original_name="ticket7.csv",
        column_mapping=ColumnMapping(
            source="EN",
            target=None,
            cn=None,
            key="Key",
            char_limit=char_limit_column,
            context=[],
        ),
        sheet_name=None,
        file_bytes=file_bytes,
        storage_path=None,
        size_bytes=len(file_bytes),
    )
    return summary.asset_id


def _set_policy(
    *,
    project_path: Path,
    translator_provider: str,
    translator_model: str,
    reviewer_provider: str = "mock",
    reviewer_model: str = "mock-v1",
) -> None:
    save_policy(
        project_path,
        ModelPolicy(
            translator=TaskPolicy(provider=translator_provider, model=translator_model),
            reviewer=TaskPolicy(provider=reviewer_provider, model=reviewer_model),
            schema_resolver=TaskPolicy(provider="mock", model="mock-v1"),
        ),
    )


def test_key_not_written_to_config_or_sqlite(tmp_path: Path, fake_keyring: _FakeKeyring) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 7 Secrets")
    secret_value = "sk-test-super-secret"

    set_secret("openai_api_key", secret_value)
    _set_policy(
        project_path=project.project_path,
        translator_provider="openai",
        translator_model="gpt-4o-mini",
    )

    config_text = (project.project_path / "config.yml").read_text(encoding="utf-8")
    assert secret_value not in config_text
    assert "openai_api_key" not in config_text

    conn = sqlite3.connect(db_path)
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()

    assert secret_value not in dump
    assert "openai_api_key" not in dump


def test_provider_falls_back_to_mock_without_openai_key(tmp_path: Path, fake_keyring: _FakeKeyring) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 7 Fallback")
    asset_id = _import_asset_single_segment(
        db_path=db_path,
        project=project,
        source_text="This source sentence is long enough for low risk.",
    )
    _set_policy(
        project_path=project.project_path,
        translator_provider="openai",
        translator_model="gpt-4o-mini",
    )

    selected: list[tuple[str, str]] = []

    def provider_factory(provider_name: str, model: str) -> LLMProvider:
        selected.append((provider_name, model))
        return MockProvider(model=model)

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
        provider_factory=provider_factory,
    )

    assert selected
    assert selected[0][0] == "mock"


def test_pipeline_creates_llm_draft_with_mock_provider_injection(
    tmp_path: Path,
    fake_keyring: _FakeKeyring,
) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 7 Draft")
    asset_id = _import_asset_single_segment(
        db_path=db_path,
        project=project,
        source_text="This source sentence is long enough for low risk.",
    )
    _set_policy(
        project_path=project.project_path,
        translator_provider="mock",
        translator_model="mock-v1",
    )

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
        provider_factory=lambda provider, model: MockProvider(model=model),
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT candidate_type, model_info_json
            FROM translation_candidates
            ORDER BY generated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "llm_draft"
    model_info = json.loads(str(row[1]))
    assert model_info["provider"] == "mock"
    assert model_info["model"] == "mock-v1"


def test_reviewer_gating_runs_when_risk_threshold_met(tmp_path: Path, fake_keyring: _FakeKeyring) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 7 Reviewer")
    asset_id = _import_asset_single_segment(
        db_path=db_path,
        project=project,
        source_text="Hello",
        char_limit=8,
    )
    _set_policy(
        project_path=project.project_path,
        translator_provider="mock",
        translator_model="mock-v1",
        reviewer_provider="mock",
        reviewer_model="mock-v1",
    )

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
        provider_factory=lambda provider, model: MockProvider(model=model),
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT candidate_type
            FROM translation_candidates
            ORDER BY generated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "llm_reviewed"


def test_placeholder_qa_flags_still_work_with_llm_pipeline(
    tmp_path: Path,
    fake_keyring: _FakeKeyring,
) -> None:
    db_path, project = _setup_project(tmp_path, "Ticket 7 QA")
    asset_id = _import_asset_single_segment(
        db_path=db_path,
        project=project,
        source_text="Damage %1$s dealt now",
    )
    _set_policy(
        project_path=project.project_path,
        translator_provider="mock",
        translator_model="mock-v1",
    )

    class _BrokenProvider(LLMProvider):
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
            return prompt.replace("⟦PH_1⟧", "")

    run_mock_translation_job(
        db_path=db_path,
        project_id=project.project_id,
        asset_id=asset_id,
        target_locale=project.target_locale,
        provider_factory=lambda provider, model: _BrokenProvider(),
    )

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
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

    assert rows
    assert any(row[0] == "placeholder_mismatch" for row in rows)
    assert any("Missing placeholder" in row[1] for row in rows)
