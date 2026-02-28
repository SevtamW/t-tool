from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


def _ensure_repo_root_on_path() -> None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "tt_core").is_dir():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return


_ensure_repo_root_on_path()

import tt_core.llm.policy as policy_module
from tt_core.llm.policy import (
    DEFAULT_MODEL_BY_PROVIDER,
    ModelPolicy,
    TASK_REVIEWER,
    TASK_SCHEMA_RESOLVER,
    TASK_TRANSLATOR,
    TaskPolicy,
    describe_secret_backend,
    delete_secret,
    get_secret,
    has_secret_backend,
    load_policy,
    save_policy,
    set_secret,
)
from tt_core.project.create_project import load_project_info

PROVIDER_OPTIONS = ["mock", "openai", "local"]
OPENAI_KEY_INPUT_STATE = "providers_openai_key_input"
OPENAI_KEY_SYNC_STATE = "providers_openai_key_synced"
OPENAI_KEY_FORCE_RELOAD_STATE = "providers_openai_key_force_reload"
OPENAI_KEY_SHOW_STATE = "providers_openai_key_show"
PROVIDERS_FLASH_STATE = "providers_flash"


def _provider_index(provider: str) -> int:
    if provider in PROVIDER_OPTIONS:
        return PROVIDER_OPTIONS.index(provider)
    return 0


def _set_flash(level: str, message: str) -> None:
    st.session_state[PROVIDERS_FLASH_STATE] = (level, message)


def _show_flash() -> None:
    flash = st.session_state.pop(PROVIDERS_FLASH_STATE, None)
    if flash is None:
        return
    level, message = flash
    if level == "success":
        st.success(message)
        return
    if level == "error":
        st.error(message)
        return
    st.info(message)


def _sync_secret_editor(
    secret_name: str,
    *,
    editor_key: str,
    synced_key: str,
    reload_key: str,
) -> str | None:
    current_value = get_secret(secret_name) or ""
    force_reload = bool(st.session_state.pop(reload_key, False))
    if force_reload or st.session_state.get(synced_key) != current_value:
        st.session_state[editor_key] = current_value
        st.session_state[synced_key] = current_value
    return current_value or None


def _mask_secret_value(value: str) -> str:
    helper = getattr(policy_module, "mask_secret_value", None)
    if callable(helper):
        return str(helper(value))

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


def _list_secret_statuses() -> list[dict[str, str | bool | None]]:
    helper = getattr(policy_module, "list_secret_statuses", None)
    if callable(helper):
        return [
            {
                "name": str(status.name),
                "label": str(status.label),
                "is_configured": bool(status.is_configured),
                "preview": str(status.preview) if status.preview else None,
            }
            for status in helper()
        ]

    openai_value = get_secret("openai_api_key")
    return [
        {
            "name": "openai_api_key",
            "label": "OpenAI API Key",
            "is_configured": bool(openai_value),
            "preview": _mask_secret_value(openai_value) if openai_value else None,
        }
    ]


st.title("Settings / Providers")

selected_slug = st.session_state.get("selected_project_slug")
projects_root = Path(st.session_state.get("projects_root", "./projects")).expanduser()

if not selected_slug:
    st.warning("No project selected. Open the 'Select Project' page first.")
    st.stop()

try:
    project = load_project_info(selected_slug, root=projects_root)
except Exception as exc:  # noqa: BLE001
    st.error(f"Unable to load selected project: {exc}")
    st.stop()

st.warning("API keys are stored in the OS keychain or secret service and are not written to disk.")
backend_description = describe_secret_backend()
backend_available = has_secret_backend()
st.caption(f"Detected secret backend: {backend_description}")
if not backend_available:
    st.error(
        "No usable secret backend detected. Install a working `keyring` backend, "
        "use macOS Keychain, or install `secret-tool` on Linux."
    )

_show_flash()

st.subheader("Stored API Keys")
for secret_status in _list_secret_statuses():
    if secret_status["is_configured"]:
        st.caption(f"{secret_status['label']}: {secret_status['preview']}")
    else:
        st.caption(f"{secret_status['label']}: not configured")

st.subheader("OpenAI API Key")
stored_openai_key = _sync_secret_editor(
    "openai_api_key",
    editor_key=OPENAI_KEY_INPUT_STATE,
    synced_key=OPENAI_KEY_SYNC_STATE,
    reload_key=OPENAI_KEY_FORCE_RELOAD_STATE,
)
editor_has_value = bool(str(st.session_state.get(OPENAI_KEY_INPUT_STATE, "")).strip())
if not editor_has_value:
    st.session_state[OPENAI_KEY_SHOW_STATE] = False

show_openai_key = st.checkbox(
    "Show current key in plain text",
    disabled=not editor_has_value,
    help="Reveal the stored key in the editor so you can review or replace it.",
    key=OPENAI_KEY_SHOW_STATE,
)
st.text_input(
    "openai_api_key",
    key=OPENAI_KEY_INPUT_STATE,
    type="password",
    placeholder="sk-...",
    help="Stored values are loaded from the OS keychain. Edit this field and save to replace the current key.",
)
if show_openai_key:
    visible_openai_key = str(st.session_state.get(OPENAI_KEY_INPUT_STATE, ""))
    if visible_openai_key.strip():
        st.code(visible_openai_key, language="text")
    else:
        st.caption("OpenAI API key editor is empty.")
elif stored_openai_key:
    st.caption(f"Stored key preview: {_mask_secret_value(stored_openai_key)}")
elif editor_has_value:
    st.caption("No OpenAI API key is stored yet. The editor contains an unsaved value.")
else:
    st.caption("No OpenAI API key stored.")

save_col, reload_col, delete_col = st.columns(3)
if save_col.button("Save changes", disabled=not backend_available):
    openai_key_input = str(st.session_state.get(OPENAI_KEY_INPUT_STATE, ""))
    if not openai_key_input.strip():
        st.error("Enter an API key before saving.")
    else:
        try:
            set_secret("openai_api_key", openai_key_input.strip())
            _set_flash("success", "OpenAI API key saved to keychain.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to save key: {exc}")

if reload_col.button("Reload stored key", disabled=not backend_available):
    st.session_state[OPENAI_KEY_FORCE_RELOAD_STATE] = True
    _set_flash("info", "Reloaded OpenAI API key from keychain.")
    st.rerun()

if delete_col.button("Delete key", disabled=not backend_available):
    try:
        delete_secret("openai_api_key")
        _set_flash("success", "OpenAI API key deleted from keychain.")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to delete key: {exc}")

policy = load_policy(project.project_path)

st.subheader("Model Policy")
translator_provider = st.selectbox(
    "Translator provider",
    options=PROVIDER_OPTIONS,
    index=_provider_index(policy.translator.provider),
)
translator_model = st.text_input(
    "Translator model",
    value=policy.translator.model or DEFAULT_MODEL_BY_PROVIDER[translator_provider],
)

reviewer_provider = st.selectbox(
    "Reviewer provider",
    options=PROVIDER_OPTIONS,
    index=_provider_index(policy.reviewer.provider),
)
reviewer_model = st.text_input(
    "Reviewer model",
    value=policy.reviewer.model or DEFAULT_MODEL_BY_PROVIDER[reviewer_provider],
)

schema_provider = st.selectbox(
    "Schema resolver provider",
    options=PROVIDER_OPTIONS,
    index=_provider_index(policy.schema_resolver.provider),
)
schema_model = st.text_input(
    "Schema resolver model",
    value=policy.schema_resolver.model or DEFAULT_MODEL_BY_PROVIDER[schema_provider],
)

if translator_provider == "openai" and not get_secret("openai_api_key"):
    st.info("Translator is set to OpenAI, but no key is configured. Jobs will fall back to mock.")

if st.button("Save policy", type="primary"):
    next_policy = ModelPolicy(
        translator=TaskPolicy(
            provider=translator_provider,
            model=translator_model.strip() or DEFAULT_MODEL_BY_PROVIDER[translator_provider],
        ),
        reviewer=TaskPolicy(
            provider=reviewer_provider,
            model=reviewer_model.strip() or DEFAULT_MODEL_BY_PROVIDER[reviewer_provider],
        ),
        schema_resolver=TaskPolicy(
            provider=schema_provider,
            model=schema_model.strip() or DEFAULT_MODEL_BY_PROVIDER[schema_provider],
        ),
    )
    try:
        save_policy(project.project_path, next_policy)
        st.success("Provider policy saved.")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to save policy: {exc}")

st.caption(
    f"Tasks: {TASK_TRANSLATOR}, {TASK_REVIEWER}, {TASK_SCHEMA_RESOLVER} "
    "(schema resolver is scaffolded for future tickets)."
)
