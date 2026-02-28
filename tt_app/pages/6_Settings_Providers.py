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


def _provider_index(provider: str) -> int:
    if provider in PROVIDER_OPTIONS:
        return PROVIDER_OPTIONS.index(provider)
    return 0


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

st.subheader("OpenAI API Key")
openai_key_input = st.text_input("openai_api_key", type="password", value="")

save_col, delete_col, test_col = st.columns(3)
if save_col.button("Save key", disabled=not backend_available):
    if not openai_key_input.strip():
        st.error("Enter an API key before saving.")
    else:
        try:
            set_secret("openai_api_key", openai_key_input.strip())
            st.success("OpenAI API key saved to keychain.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to save key: {exc}")

if delete_col.button("Delete key", disabled=not backend_available):
    try:
        delete_secret("openai_api_key")
        st.success("OpenAI API key deleted from keychain.")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to delete key: {exc}")

if test_col.button("Test key", disabled=not backend_available):
    try:
        key_value = get_secret("openai_api_key")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Keychain check failed: {exc}")
    else:
        if key_value:
            st.success("OpenAI API key is present in keychain.")
        else:
            st.error("No OpenAI API key found in keychain.")

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
