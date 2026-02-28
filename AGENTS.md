# agents.md — AI Agent Working Agreement (t-tool)

This document is **the single source of truth** for how contributors (human + AI) should understand, extend, and modify this repository.

It aims to keep development **safe, predictable, and extensible** while the product evolves.

---

## Product Overview

**t-tool** is a **local-first** translation automation tool for game localization workflows.

Primary use cases:
- Import game **LP spreadsheets** (XLSX/CSV) with varying schemas
- Support **EN → any target locale** (DE/FR/ES/PT/IT…)
- Maintain consistency via:
  - **Glossary (must-use)** with robust matching rules (avoid substring false positives)
  - **Translation Memory (TM)** that learns **only from approved translations**
- Provide a **review-first** workflow:
  - generate proposals (TM/LLM)
  - user edits + approves per row
  - export results to a new column **NEW <LANG>** (e.g., **NEW DE**) without touching the original file

Non-goals for now:
- Cloud / accounts / SaaS sync
- WeChat/WhatsApp automation and any “stealth bot” behavior
- Feishu live-writing or browser automation
- Full media OCR pipeline (only findings + structure; no media storage in DB)

---

## Current Capability Snapshot (Tickets 1–8)

### Implemented
- **Local projects**: `projects/<slug>/` with `project.db`, `imports/`, `exports/`, `cache/`, `config.yml`
- **SQLite schema + migrations** (schema versioning via `schema_meta`)
- **Streamlit UI** for:
  - Select Project
  - Import XLSX/CSV (manual mapping)
  - Run jobs
  - Review/edit/approve
  - Export:
    - patch table export
    - XLSX copy export with **NEW <LANG>** column (e.g. NEW DE)
  - Settings: keyring-backed API key + model policy (BYOK)
- **Importer v2**:
  - LP vs Change-file modes
  - stores `source_text_old` for change files
  - imports existing target column as baseline candidate `existing_target` (not approved)
- **Placeholder firewall** + QA flags
- **Glossary must-use enforcement** (whole-token + compound support)
- **TM**: exact + FTS5 + fuzzy rerank (Top-N), auto-learn only from approvals
- **LLM provider layer** (BYOK + keyring), policy-driven per task, risk-gated reviewer

### Not implemented yet (planned)
- Automatic file-type detection / schema inference (heuristics + optional LLM resolver)
- Change-file processing pipelines (KEEP/UPDATE/FLAG logic)
- Glossary import UX (xlsx/csv → glossary_terms)
- Advanced QA (numbers, punctuation, length strategies, MQM-style categorization)
- Media QA automation beyond basic structured findings

---

## Core Principles (Hard Rules)

### Local-first & Privacy
- Everything is per-project on disk in `projects/<slug>/`.
- **Do not store secrets** in `config.yml`, SQLite, fixtures, logs, or commit history.
- API keys are stored via **OS keychain** using `keyring`.

### Approval-driven learning
- **Only `approved_translations`** are allowed to feed the TM (`tm_entries` + `tm_fts`).
- Drafts and baseline `existing_target` are **not** written into TM automatically.

### Exports never overwrite the original file
- For LP workflows, output must be a **copy** with new column **`NEW <LANG>`** (default naming: `NEW DE`, `NEW FR`, …).
- Only approved rows are written to NEW columns. Unapproved rows must remain blank/untouched.

### Deterministic safety layer first
- Placeholder/tag safety and glossary enforcement must remain robust:
  - Preserve `{0}`, `%s`, `<color=...>`, `\n` and `
` exactly
  - Avoid substring false positives in glossary matching (e.g., “DMG” inside unrelated words)

### Agent/LLM usage is controlled
- LLMs generate *proposals*, never uncontrolled writes.
- Reviewer pass is **risk-gated**, not automatic for all segments.
- All machine-consumed outputs must be validated; failures create QA flags or require review.

---

## File Types & How the Tool Treats Them (Current)

**Right now** the importer is user-directed:
- UI “Import mode” selects:
  - `lp` (single source)
  - `change_source_update` (OLD/NEW source)

Importer stores mapping in `schema_profiles.mapping_json` including:
- mode
- source_new/source_old column names
- target column name (optional) + `target_locale`
- cn/key/char_limit/context columns

Baseline behavior:
- If a target column is mapped, non-empty target values become `translation_candidates` with `candidate_type="existing_target"` (not approved).

Generation behavior (job run):
1. TM exact/fuzzy has priority
2. else glossary + placeholder safety
3. else LLM draft (per model policy)

---

## Data Model Invariants (High-Level)

Tables exist for:
- Projects + locales: `projects`, `project_locales`
- Imports: `assets`, `schema_profiles`, `segments`
- Proposals + approvals: `translation_candidates`, `approved_translations`
- Knowledge: `glossary_terms`, `tm_entries` (+ `tm_fts`)
- Quality + orchestration: `qa_flags`, `jobs`

Key invariants:
- `approved_translations` is the “truth” for what is final.
- TM entries are derived from approvals only.
- `schema_profiles.signature` must be stable; mapping must be upserted safely.
- Bulk inserts must be done in transactions for performance.

---

## LLM / Provider Policy (BYOK)

Policy lives in project `config.yml` (no secrets), e.g.:
- translator provider + model
- reviewer provider + model
- schema_resolver provider + model (future)

Secrets live in keychain:
- keyring service: `t-tool`
- secret names: `openai_api_key` (and future provider keys)

When no key is configured:
- the app must fail gracefully or fall back to MockProvider (depending on UI choice).

---

## Build, Test, and Development Commands

Use Python 3.11+.

```bash
python -m pip install -e .
python -m pip install -e ".[dev]"
pytest
streamlit run tt_app/app.py
tt create-project "My Game" --source en-US --target de-DE --targets de-DE,fr-FR
```

Additional contributor rule:
- If a change adds or requires new dependencies, install them before validation.
- After completing changes, always run the app locally (`streamlit run tt_app/app.py`) to verify it starts.

---

## Coding Style & Naming Conventions

- Keep changes small and testable.
- 4-space indentation, type hints on public APIs.
- `snake_case` for modules/functions/vars, `PascalCase` for classes.
- Keep Streamlit pages prefixed with numbers (sidebar order stability).
- Do not introduce style-only refactors unless necessary.

---

## Testing Guidelines

- `pytest` tests live in `tests/` as `test_*.py`.
- Prefer regression tests around touched subsystems.
- Use `tmp_path` for filesystem and temp DBs.
- Tests must be **offline** (no network calls). Use MockProvider in tests.

Recommended “golden fixtures” (not committed with private data):
- Small LP with placeholders/tags/newlines
- Small change file (OLD/NEW)
- A glossary sample (DMG/ATK/HP + compound tokens)

---

## Migration & Backwards Compatibility Rules

- All schema changes must be done via migrations in `tt_core/db/migrations.py`.
- Always increment `schema_version`.
- Maintain compatibility:
  - If older `mapping_json` uses `"source"` key, treat as `source_new`.

---

## Security & Configuration Tips

- Never write API keys into:
  - SQLite
  - config.yml
  - test fixtures
  - logs
- Runtime project data is stored under `projects/` and must not be treated as source code.

---

## How to Add New Features Safely

Preferred approach: **thin vertical slices** on top of stable core.

Before adding a feature:
1. Define acceptance criteria (what must work end-to-end)
2. Add/extend tests (regression + edge cases)
3. Implement minimal UI + service logic
4. Validate with golden files
5. Only then iterate on “smarter” agent behavior (LLM resolvers)

Priority roadmap (suggested):
1) File type detection (heuristics + optional LLM resolver)
2) Change-file pipeline (Variant B first: KEEP/UPDATE/FLAG)
3) Glossary import UX
4) Advanced QA (numbers, length strategies, MQM-style reporting)
5) Media QA enhancements (optional OCR plugin)

---
