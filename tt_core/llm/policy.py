from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from tt_core.project.config import read_config, write_config
from tt_core.project.paths import project_config_path

KEYRING_SERVICE_NAME = "t-tool"
SECRET_LABELS = {
    "openai_api_key": "OpenAI API Key",
}

TASK_TRANSLATOR = "translator"
TASK_REVIEWER = "reviewer"
TASK_SCHEMA_RESOLVER = "schema_resolver"
TASKS = (TASK_TRANSLATOR, TASK_REVIEWER, TASK_SCHEMA_RESOLVER)
PROVIDERS = ("mock", "openai", "local")

DEFAULT_MODEL_BY_PROVIDER = {
    "mock": "mock-v1",
    "openai": "gpt-4o-mini",
    "local": "local-stub-v1",
}

try:
    import keyring
    from keyring.errors import PasswordDeleteError
except Exception:  # noqa: BLE001
    keyring = None
    PasswordDeleteError = Exception


def _python_keyring_status() -> tuple[bool, str | None]:
    if keyring is None:
        return False, None

    if not hasattr(keyring, "get_keyring"):
        return True, keyring.__class__.__name__

    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001
        return False, "unavailable"

    if backend.__class__.__module__ == "keyring.backends.fail":
        return False, "fail-backend"

    return True, backend.__class__.__name__


def _has_macos_security_cli() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None


def _has_linux_secret_tool() -> bool:
    return sys.platform.startswith("linux") and shutil.which("secret-tool") is not None


def _macos_set_secret(name: str, value: str) -> None:
    completed = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            KEYRING_SERVICE_NAME,
            "-a",
            name,
            "-w",
            value,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"macOS keychain write failed: {details or 'unknown error'}")


def _macos_get_secret(name: str) -> str | None:
    completed = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            KEYRING_SERVICE_NAME,
            "-a",
            name,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value if value else None


def _macos_delete_secret(name: str) -> None:
    completed = subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-s",
            KEYRING_SERVICE_NAME,
            "-a",
            name,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").lower()
        if "could not be found" in stderr or "item not found" in stderr:
            return
        details = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"macOS keychain delete failed: {details or 'unknown error'}")


def _linux_secret_tool_attrs(name: str) -> list[str]:
    return ["service", KEYRING_SERVICE_NAME, "account", name]


def _linux_set_secret(name: str, value: str) -> None:
    completed = subprocess.run(
        [
            "secret-tool",
            "store",
            "--label",
            f"{KEYRING_SERVICE_NAME}: {name}",
            *_linux_secret_tool_attrs(name),
        ],
        input=value,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"Linux Secret Service write failed: {details or 'unknown error'}"
        )


def _linux_get_secret(name: str) -> str | None:
    completed = subprocess.run(
        ["secret-tool", "lookup", *_linux_secret_tool_attrs(name)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value if value else None


def _linux_delete_secret(name: str) -> None:
    completed = subprocess.run(
        ["secret-tool", "clear", *_linux_secret_tool_attrs(name)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        if not details or "not found" in details.lower():
            return
        raise RuntimeError(
            f"Linux Secret Service delete failed: {details or 'unknown error'}"
        )


@dataclass(slots=True, frozen=True)
class StoredSecretStatus:
    name: str
    label: str
    is_configured: bool
    preview: str | None


@dataclass(slots=True, frozen=True)
class TaskPolicy:
    provider: str
    model: str


@dataclass(slots=True, frozen=True)
class ModelPolicy:
    translator: TaskPolicy
    reviewer: TaskPolicy
    schema_resolver: TaskPolicy

    def for_task(self, task: str) -> TaskPolicy:
        if task == TASK_TRANSLATOR:
            return self.translator
        if task == TASK_REVIEWER:
            return self.reviewer
        if task == TASK_SCHEMA_RESOLVER:
            return self.schema_resolver
        raise ValueError(f"Unsupported model policy task: {task}")

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            TASK_TRANSLATOR: {
                "provider": self.translator.provider,
                "model": self.translator.model,
            },
            TASK_REVIEWER: {
                "provider": self.reviewer.provider,
                "model": self.reviewer.model,
            },
            TASK_SCHEMA_RESOLVER: {
                "provider": self.schema_resolver.provider,
                "model": self.schema_resolver.model,
            },
        }


def mask_secret_value(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if len(normalized) <= 4:
        return "*" * len(normalized)
    if len(normalized) <= 8:
        visible = 2
        hidden = len(normalized) - (visible * 2)
        return f"{normalized[:visible]}{'*' * hidden}{normalized[-visible:]}"
    hidden = len(normalized) - 8
    return f"{normalized[:4]}{'*' * hidden}{normalized[-4:]}"


def list_secret_statuses() -> list[StoredSecretStatus]:
    statuses: list[StoredSecretStatus] = []
    for name, label in SECRET_LABELS.items():
        value = get_secret(name)
        statuses.append(
            StoredSecretStatus(
                name=name,
                label=label,
                is_configured=bool(value),
                preview=mask_secret_value(value) if value else None,
            )
        )
    return statuses


def set_secret(name: str, value: str) -> None:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Secret value must not be empty.")

    keyring_available, _ = _python_keyring_status()
    keyring_error: Exception | None = None
    if keyring_available:
        try:
            keyring.set_password(KEYRING_SERVICE_NAME, name, normalized)
            return
        except Exception as exc:  # noqa: BLE001
            keyring_error = exc

    if _has_macos_security_cli():
        _macos_set_secret(name, normalized)
        return

    if _has_linux_secret_tool():
        _linux_set_secret(name, normalized)
        return

    if keyring_error is not None:
        raise RuntimeError(f"Secret storage failed: {keyring_error}") from keyring_error
    raise RuntimeError(
        "No secret backend available. Install a usable python keyring backend, "
        "use macOS Keychain, or install `secret-tool` for Linux Secret Service."
    )


def get_secret(name: str) -> str | None:
    value: str | None = None
    keyring_available, _ = _python_keyring_status()
    if keyring_available:
        try:
            value = keyring.get_password(KEYRING_SERVICE_NAME, name)
        except Exception:  # noqa: BLE001
            value = None

    if value is None and _has_macos_security_cli():
        try:
            value = _macos_get_secret(name)
        except Exception:  # noqa: BLE001
            value = None

    if value is None and _has_linux_secret_tool():
        try:
            value = _linux_get_secret(name)
        except Exception:  # noqa: BLE001
            value = None

    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def delete_secret(name: str) -> None:
    keyring_available, _ = _python_keyring_status()
    keyring_error: Exception | None = None

    if keyring_available:
        try:
            keyring.delete_password(KEYRING_SERVICE_NAME, name)
            return
        except PasswordDeleteError:
            return
        except Exception as exc:  # noqa: BLE001
            keyring_error = exc

    if _has_macos_security_cli():
        _macos_delete_secret(name)
        return

    if _has_linux_secret_tool():
        _linux_delete_secret(name)
        return

    if keyring_error is not None:
        raise RuntimeError(f"Secret deletion failed: {keyring_error}") from keyring_error


def has_secret_backend() -> bool:
    keyring_available, _ = _python_keyring_status()
    return keyring_available or _has_macos_security_cli() or _has_linux_secret_tool()


def describe_secret_backend() -> str:
    descriptions: list[str] = []
    _, keyring_description = _python_keyring_status()
    if keyring_description is not None:
        descriptions.append(f"python-keyring:{keyring_description}")
    if _has_macos_security_cli():
        descriptions.append("macOS-Keychain:security-cli")
    if _has_linux_secret_tool():
        descriptions.append("linux-secret-service:secret-tool")
    if not descriptions:
        return "none"
    return ", ".join(descriptions)


def _coerce_provider(value: Any, *, fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in PROVIDERS:
        return normalized
    return fallback


def _coerce_model(value: Any, *, provider: str) -> str:
    model = str(value or "").strip()
    if model:
        return model
    return DEFAULT_MODEL_BY_PROVIDER[provider]


def _default_policy() -> ModelPolicy:
    has_openai_key = bool(get_secret("openai_api_key"))
    translator_provider = "openai" if has_openai_key else "mock"
    return ModelPolicy(
        translator=TaskPolicy(
            provider=translator_provider,
            model=DEFAULT_MODEL_BY_PROVIDER[translator_provider],
        ),
        reviewer=TaskPolicy(
            provider="mock",
            model=DEFAULT_MODEL_BY_PROVIDER["mock"],
        ),
        schema_resolver=TaskPolicy(
            provider="mock",
            model=DEFAULT_MODEL_BY_PROVIDER["mock"],
        ),
    )


def _task_policy_from_raw(raw: Any, *, fallback: TaskPolicy) -> TaskPolicy:
    if not isinstance(raw, dict):
        return fallback
    provider = _coerce_provider(raw.get("provider"), fallback=fallback.provider)
    model = _coerce_model(raw.get("model"), provider=provider)
    return TaskPolicy(provider=provider, model=model)


def _from_legacy_policy(raw: dict[str, Any], *, defaults: ModelPolicy) -> ModelPolicy:
    translation_provider = _coerce_provider(raw.get("translation"), fallback=defaults.translator.provider)
    qa_provider = _coerce_provider(raw.get("qa"), fallback=defaults.reviewer.provider)
    schema_provider = _coerce_provider(
        raw.get("schema_mapping"),
        fallback=defaults.schema_resolver.provider,
    )
    return ModelPolicy(
        translator=TaskPolicy(
            provider=translation_provider,
            model=DEFAULT_MODEL_BY_PROVIDER[translation_provider],
        ),
        reviewer=TaskPolicy(
            provider=qa_provider,
            model=DEFAULT_MODEL_BY_PROVIDER[qa_provider],
        ),
        schema_resolver=TaskPolicy(
            provider=schema_provider,
            model=DEFAULT_MODEL_BY_PROVIDER[schema_provider],
        ),
    )


def _normalize_policy(raw_policy: Any) -> ModelPolicy:
    defaults = _default_policy()
    if not isinstance(raw_policy, dict) or not raw_policy:
        return defaults

    if any(task in raw_policy for task in TASKS):
        return ModelPolicy(
            translator=_task_policy_from_raw(
                raw_policy.get(TASK_TRANSLATOR),
                fallback=defaults.translator,
            ),
            reviewer=_task_policy_from_raw(
                raw_policy.get(TASK_REVIEWER),
                fallback=defaults.reviewer,
            ),
            schema_resolver=_task_policy_from_raw(
                raw_policy.get(TASK_SCHEMA_RESOLVER),
                fallback=defaults.schema_resolver,
            ),
        )

    # Backward compatibility for ticket 1-6 placeholder policy keys.
    return _from_legacy_policy(raw_policy, defaults=defaults)


def load_policy(project_path: Path) -> ModelPolicy:
    config = read_config(project_config_path(Path(project_path)))
    return _normalize_policy(config.model_policy)


def save_policy(project_path: Path, policy: ModelPolicy) -> None:
    config_path = project_config_path(Path(project_path))
    config = read_config(config_path)
    config.model_policy = policy.to_dict()
    write_config(config_path, config)
