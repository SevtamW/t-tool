from __future__ import annotations


DEFAULT_STYLE_HINTS = "informal, use Du for German"


def build_translation_prompt(
    *,
    source_text: str,
    protected_text: str,
    target_locale: str,
    style_hints: str | None = None,
) -> str:
    style = (style_hints or DEFAULT_STYLE_HINTS).strip()
    return (
        f"Translate the source to {target_locale}. Style hints: {style}.\n"
        "Do not modify placeholder tokens like ⟦PH_*⟧ and term tokens like ⟦TERM_*⟧.\n"
        "Keep actual newlines and escaped \\n unchanged.\n"
        "Output only the translated string.\n"
        f"SOURCE: {source_text}\n"
        f"PROTECTED: {protected_text}"
    )


def build_reviewer_prompt(
    *,
    source_text: str,
    draft_text: str,
    target_locale: str,
    style_hints: str | None = None,
) -> str:
    style = (style_hints or DEFAULT_STYLE_HINTS).strip()
    return (
        f"Review and improve this {target_locale} translation. Style hints: {style}.\n"
        "Keep placeholder tokens (⟦PH_*⟧) and glossary tokens (⟦TERM_*⟧) unchanged.\n"
        "Keep actual newlines and escaped \\n unchanged.\n"
        "Output only the revised translation string.\n"
        f"SOURCE: {source_text}\n"
        f"DRAFT: {draft_text}"
    )

