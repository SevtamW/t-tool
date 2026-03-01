# Prompt Archive

This archive keeps the original build prompts in one place, organized for faster scanning and reuse.

## Quick Navigation

- [Full MVP Prompt](#full-mvp-prompt)
- [Ticket Prompts](#ticket-prompts)
- [Ticket 1: Walking Skeleton Foundation](#ticket-1)
- [Ticket 2: Import XLSX/CSV + Manual Column Mapping + Store Segments](#ticket-2)
- [Ticket 3: Run Job (Mock) -> Review/Approve -> Export Patch](#ticket-3)
- [Ticket 3b: Export LP Copy With "NEW <LANG>" Column](#ticket-3b)
- [Ticket 4: Placeholder Firewall + QA Flags](#ticket-4)
- [Ticket 5: Glossary Must-Use](#ticket-5)
- [Ticket 6: TM Store + Search (FTS5)](#ticket-6)
- [Ticket 7: LLM Provider Layer + Keyring Settings](#ticket-7)
- [Ticket 8: Import v2](#ticket-8)
- [Ticket 8b: Create Project in Streamlit UI](#ticket-8b)
- [Ticket 9: Change-File Variant B](#ticket-9)
- [Ticket 10: Change-File Variant A](#ticket-10)

<a id="full-mvp-prompt"></a>
## Full MVP Prompt

You are Codex, an expert product + software architect and senior full-stack engineer. Build a working MVP of a “Translation Tool” for game localization automation.

You are starting in an EMPTY directory. Create the entire repository: code, tests, docs, and a runnable app.

### PRODUCT GOAL

Build a local-first, cross-platform-friendly MVP for translators that:

- Imports game “Language Pack” spreadsheets (XLSX/CSV) with varying column names/order and multiple languages.
- Supports EN -> any target language (DE/FR/ES/PT/IT etc.). Target language(s) are selectable per job.
- Enforces consistency via:
  - Project-specific Translation Memory (TM) (approved translations)
  - Project-specific Glossary (must-use terms)
  - Optional small Global Game Glossary (ATK/HP/DMG etc.) shared across projects
- Handles change-file variants (source OLD/NEW, targets either NEW columns or existing target columns).
- Provides QA gates (placeholders/tags/numbers/length limits/terminology) and a review UI to approve per-row.
- Learns safely: only approved outputs go into TM automatically; glossary/pattern rules are suggested and require explicit approval.
- Includes an “agentic” layer ONLY for ambiguity resolution (schema mapping, routing, disambiguation), not for blind writing.

MVP UI language: English only.

### KEY AGREEMENTS / CONSTRAINTS

- **Local-first storage**
  - Use SQLite as the single source of truth per project (one DB per project folder).
  - Do NOT store photos/videos inside the DB. Store only paths/hashes + derived findings (OCR text snippets, timestamps, etc.).
  - Provide export of “ALL” as XLSX/TMX-style export (simple MVP export acceptable). “ALL.xlsx” becomes an export artifact, not the working store.
- **Security**
  - Do NOT store API keys in SQLite or plaintext config files.
  - Store API keys in OS credential storage via Python `keyring`.
  - Support “BYOK” (Bring Your Own Key): user supplies their own OpenAI/other API keys.
  - Provide option to use local LLMs (later), but implement the abstraction now.
- **LLM usage**
  - LLM calls are used for:
    1. Translation draft (when not filled by TM/glossary)
    2. Optional post-edit/review pass, but ONLY when risk score warrants it
    3. Schema/column mapping resolution when heuristics are uncertain
    4. Optional small routing/disambiguation tasks
  - Do NOT run a second “review LLM” for every segment by default. Use risk scoring + gates.
- **Determinism + intelligence**
  - Deterministic rules always run (placeholder firewall, QA checks, must-use terminology).
  - “Agent” is a resolver: it decides what to do only when the situation is unclear; all write actions are controlled, validated, and auditable.
- **Approval & locking**
  - User can approve individual rows (and leave others unapproved).
  - User can edit within a row (change a word).
  - Approved outputs are not overwritten by default.
  - If source changes, mark translations as “STALE” and queue for review.
  - Optional “Pin/Lock” exists but must NOT require manual row-by-row locking. Provide row-level pin and bulk pin rules (by key prefix, manual-edited, glossary-derived, etc.).
- **Terminology nuance**
  - Avoid false positives like matching “DMG” inside unrelated substrings.
  - Glossary terms must support match policies: whole-token, case-sensitive, allow_compounds, compound_strategy, negative patterns.
  - Compounds like “DMGBoost” should be handled via rules + intelligent transformation when needed.
- **Scalability**
  - Must handle large spreadsheets (e.g., LP 120,000 rows; glossary 4,000; TM 30,000+) smoothly.
  - Use bulk imports, proper indices, WAL mode, and FTS5 for fast text search in TM.

### DELIVERABLES

Create:

1. A Python package for the core engine (`tt_core/`) and a Streamlit MVP UI (`tt_app/`).
2. A CLI (`tt_cli`) for basic operations (create project, import, run job, export).
3. A clean data model in SQLite with migrations or create-on-first-run.
4. Unit tests (pytest) for core logic (placeholder firewall, glossary match, QA, schema mapping decisions, TM insert/retrieval).
5. A README with setup and usage instructions.
6. Implement a future-ready “Messaging/Connectors” abstraction (stubs only) to support channels like WhatsApp, Email, Feishu later.
   - Must be job-centric (Translation Ops Bot), not a general-purpose assistant.
   - In MVP: provide a `LocalConsoleConnector` and a `FileDropConnector` only.

### TECH STACK (MVP)

Python 3.11+

- streamlit (UI)
- pandas + openpyxl (xlsx import/export)
- SQLModel or SQLAlchemy (ORM) + SQLite
- sqlite FTS5 (for TM search)
- rapidfuzz (fuzzy match)
- pydantic (schemas)
- keyring (secure key storage)
- typer (CLI)

Optional but helpful:
- python-dotenv (optional env var support for power users)
- opencv-python / pytesseract is NOT required in MVP tests; implement media scan structure and simple image OCR integration as optional plugin (stub + interface). If OCR libs are unavailable, degrade gracefully.

### REPO STRUCTURE (create this)

/README.md

/pyproject.toml (or requirements.txt + setup.cfg; choose one clean approach)

/tt_core/

__init__.py

db/

models.py

migrations.py (or schema_init.py)

queries.py

project/

create_project.py

config.py

importers/

xlsx_import.py

csv_import.py

schema_detect.py

schema_resolver_llm.py

tm/

tm_store.py

tm_search.py

glossary/

glossary_store.py

matcher.py

rules.py

qa/

placeholder_firewall.py

checks.py

risk_score.py

jobs/

router.py

job_types.py

pipeline_translate.py

pipeline_changefile.py

pipeline_media_scan.py (phase-1 assist; store findings only)

llm/

provider_base.py

provider_openai.py (BYOK; minimal implementation)

provider_local_stub.py

policy.py

export/

export_xlsx.py

export_all.py

/tt_app/

streamlit_app.py

pages/

1_Project_Setup.py

2_Import_File.py

3_Run_Job.py

4_Review_Approve.py

5_Export.py

6_Settings_Providers.py

/tt_cli/

__init__.py

main.py

/tests/

test_placeholder_firewall.py

test_glossary_matching.py

test_tm_search.py

test_schema_detect.py

test_qa_checks.py

test_jobs_routing.py

/examples/ (optional placeholder folder)

/docs/ (optional)

Make sure imports and packaging work.

/tt_core/connectors/

connector_base.py

connector_local_console.py

connector_filedrop.py

message_router.py

message_intents.py


### CORE WORKFLOWS TO IMPLEMENT

A) New Project creation

- User creates a project with:

- Project name

- source locale (default en-US)

- enabled target locales, default target locale

- style profile per target (e.g., DE uses “Du” by default)

- toggle global game glossary (small default set)

- Create local project folder:

projects/<slug>/

project.db

imports/

exports/

cache/

config.yml (NO secrets)

- Initialize SQLite schema; set WAL mode.

B) Import file (XLSX/CSV)

- Read workbook/sheet, headers, and sample rows.

- Perform heuristic schema detection:

- Identify candidate source columns (EN; also optional CN context)

- Identify candidate targets (DE/FR/ES/… based on header + language detection from samples)

- Identify special columns: key/id, filename, type/category, comments, char limit, old/new markers.

- Confidence scoring. If uncertain, call Schema Resolver LLM (optional).

- Save schema profile (signature hash of headers + sheet name + column count) for future 1-click mapping.

- Store Asset record and Segments:

- Segment includes row refs, sheet, key/context, source text, cn text optional, char_limit optional.

- Do NOT overwrite approved translations from previous imports automatically.

C) Job router (agentic but controlled)

Given an Asset import, router decides job type:

- translate_file (LP)

- change_file_fill_variant_a: OLD EN/NEW EN + OLD target/NEW target columns (NEW target empty)

- change_file_update_variant_b: OLD EN/NEW EN + existing target columns (targets may already exist; needs impact analysis)

- string_translate / shorten_to_limit (stub; for future)

- media_scan (phase-1 assist; from folder/zip)

Router is deterministic first; if ambiguous, optional LLM call to classify.

D) Translation pipeline

For each segment and each chosen target locale:

1) Protect placeholders/tags:

- detect and replace placeholders with tokens ⟦PH_1⟧, preserve both “\n” and “\\n” forms

2) Terminology scan and apply deterministic safe replacements:

- Glossary must-use with match policies (whole-token/case-sensitive/etc.)

- Global glossary if enabled

- Must avoid substring false positives

- For compound hits (e.g., DMGBoost), use compound_strategy; if unclear, call resolver LLM (optional) to propose transformation.

3) TM retrieval:

- exact match via normalized hash

- FTS5 search for top candidates + rapidfuzz rerank

4) Draft creation:

- If TM exact or high-confidence TM fuzzy and passes QA, use it as candidate.

- Else call LLM translator to produce draft under constraints (must keep placeholders/tags, follow must-use terms, style “Du” etc.).

5) QA checks:

- placeholder unchanged

- tags unchanged

- numbers match (basic)

- glossary compliance

- length limit if present (hard error if exceeded)

6) Risk score:

- Use defined heuristic scoring. Only if risk_score >= threshold, run optional post-edit LLM.

7) Re-run QA after post-edit.

8) Save Draft candidates and final approval state:

- default status: draft

- user can edit and approve per row

- only approved outputs go into TM automatically.

E) Change-file pipelines

Variant A (OLD/NEW columns):

- Identify OLD EN, NEW EN; and NEW target columns are empty.

- Fill NEW targets using pipeline_translate with NEW EN as source.

- Output: write NEW target columns without preserving “red formatting”; formatting is not essential in MVP, but output must not intentionally color cells red. (Ok to write plain values.)

Variant B (OLD/NEW EN, existing targets):

- For rows where EN changed, mark target as STALE.

- Run “impact analysis”:

- Deterministic: if change is punctuation/whitespace only -> suggest KEEP.

- If key terms changed -> suggest UPDATE.

- If uncertain -> optional LLM decides KEEP/UPDATE/FLAG with confidence.

- If UPDATE -> propose updated target draft in a separate “proposed” field (do not overwrite existing target until approved).

- Export as patch (e.g., new sheet or new columns “NEW <locale>”) or allow “apply to existing target column” only for approved.

F) Review UI

Streamlit screens must allow:

- Filtering segments: all / only flagged QA / only stale / only draft / only edited / only approved

- Row-level view: source, current target, proposed target, QA flags, glossary hits, placeholders, char limit, context (key/filename/type)

- Edit target text inline

- Approve row (per target locale)

- Optional Pin row (rare); provide bulk pin tools (by key prefix, manual edited, etc.)

- Approve should commit ApprovedTranslation + update TMEntry.

G) “Learning” / Suggestions

- TM auto-learns from ApprovedTranslation.

- Glossary/pattern rules do NOT auto-learn; they become “Suggestions” when triggers hit:

- Glossary suggestion: same term correction appears >=5 times OR appears in approved outputs >=10 times; term is safe (token-boundary).

- Pattern suggestion: >=3 distinct compound tokens corrected with same prefix strategy.

- Provide a UI list “Suggestions” where user can Approve/Reject rule creation.

- After approving a rule, it is used in future translations.

H) Media QA Phase 1 (assist, no media storage)

- Support importing a folder/zip reference (do not copy large media by default; store path/hash).

- Create a job that:

- samples images, and for videos samples frames (stub ok in MVP)

- optional OCR integration behind an interface; if OCR unavailable, store “not processed” and still allow manual findings entry.

- Stores Findings: issue_type, suspected_owner (loc/dev/unknown), confidence, evidence snippet, recommended_action.

- DOES NOT upload to Feishu in MVP; just generates structured findings + optional patch suggestions.

I) Messaging / Ops Commands (MVP: local only)

- Implement an intent parser for commands like:

- "new jobs", "latest job", "job <id>", "start <id> --targets ...",

"status <id>", "approve <id>", "export <id>"

- The message router must translate messages into calls to the existing job router/pipelines.

- Store all messages and actions in an audit log table.

- DO NOT implement WhatsApp/WeChat integration in MVP; only stubs and local connectors.

### LLM PROVIDER ABSTRACTION & MODEL POLICY

Implement:

- `LLMProvider` interface with `generate()` returning structured output when needed.

- `OpenAIProvider` (BYOK) with API key stored in keyring. If no key is present, app should show a clear error and allow mock mode.

- `LocalProviderStub` that returns deterministic dummy outputs for tests.

Model selection:

- Provide a “Model Policy” config (no secrets) that maps each task to a provider:

- schema_resolver: local by default

- translator: cloud by default

- reviewer: local by default (risk gated)

- impact_analyzer: local by default

Allow user to override per task in Settings UI.

All LLM outputs that must be machine-consumed must be JSON and validated.

### NON-GOALS (MVP)

- Do NOT implement real WhatsApp/WeChat connectivity in MVP.

- Do NOT implement stealth/human-mimic browser automation.

- Provide only the connector abstraction + local stubs.

### ACCEPTANCE CRITERIA

- `streamlit run tt_app/streamlit_app.py` launches and supports:

- Create project

- Import XLSX

- Detect/match schema with confidence; save schema profile

- Run translation job for selected target locales using mock provider (works without external keys)

- Review and approve individual rows

- Export updated XLSX / patch file

- CLI supports:

- create-project

- import

- run-job

- export

- SQLite contains:

- project metadata, assets, schema profiles, segments, candidates, approvals, TM entries, glossary terms, QA flags, jobs.

- API key storage uses `keyring` (no plaintext keys).

- Tests run: `pytest -q` passes.

- Performance basics: bulk inserts in transactions; FTS5 used for TM search; WAL enabled.

### IMPLEMENTATION PLAN OUTPUT

Before coding, print a brief plan and then implement step-by-step:

- Create project scaffolding + pyproject dependencies

- Implement DB models + initialization (WAL, indices, FTS5)

- Implement importers + schema detection + schema profile saving

- Implement glossary matcher + placeholder firewall + QA checks

- Implement TM store/search (exact + FTS + fuzzy rerank)

- Implement pipelines (translate + changefile variants)

- Implement Streamlit UI pages

- Implement CLI

- Add tests + sample fixtures generated in tests

- Update README with instructions

Now implement the repository accordingly.


You are Codex, an expert software architect and senior Python engineer. Implement **Ticket 1** only.


You are starting in an EMPTY directory. Create a runnable repository skeleton with:

- A local-first, per-project SQLite database (one DB file per project folder).

- A migration/versioning mechanism (simple but real).

- A CLI command to create a new project (folder + DB + config).

- NO UI yet (Streamlit comes in Ticket 2/3).

- Keep the codebase extensible for future features (TM, glossary, QA, jobs, schema profiles, etc.).

<a id="ticket-prompts"></a>
## Ticket Prompts

<a id="ticket-1"></a>
### TICKET 1: WALKING SKELETON FOUNDATION (NO FEATURES)


GOAL

Create the base repository + core library that:

1) Creates a project folder structure.

2) Initializes an SQLite DB with an extensible core schema (tables + indexes).

3) Enables WAL mode.

4) Stores a schema version and can run migrations.

5) Provides a CLI to create a project and show basic project info.


IMPORTANT CONSTRAINTS

- Local-first only. No cloud, no accounts.

- DO NOT store any API keys in SQLite or in plaintext config files.

- Provide a placeholder Settings structure but no secrets.

- Must run on Windows/Mac/Linux.

- Keep UI language English (for later). In this ticket, only CLI messages.


TECH STACK (Ticket 1)

Python 3.11+

- sqlmodel (preferred) or SQLAlchemy

- typer (CLI)

- pydantic

- pyyaml (for config.yml)

- pytest (tests)

You may use a pyproject.toml with hatch/poetry/pdm; choose ONE clean approach.


#### REPO STRUCTURE TO CREATE

/README.md

/pyproject.toml

/tt_core/

  __init__.py

  constants.py

  project/

    __init__.py

    create_project.py

    config.py

    paths.py

  db/

    __init__.py

    engine.py

    schema.py

    migrations.py

    models.py

/tt_cli/

  __init__.py

  main.py

/tests/

  test_create_project.py


#### PROJECT FOLDER LAYOUT (created by CLI)

projects/<slug>/

  project.db

  imports/

  exports/

  cache/

  config.yml    # NO secrets

  README.txt    # short project-local note


#### CORE DATA MODEL (DB SCHEMA)

Implement these tables minimally now (fields can be minimal but must exist). Keep names stable.


1) schema_meta

- key TEXT PRIMARY KEY

- value TEXT NOT NULL

Store:

- schema_version (int as string)


2) projects

- id TEXT PRIMARY KEY (UUID)

- name TEXT NOT NULL

- slug TEXT NOT NULL UNIQUE

- default_source_locale TEXT NOT NULL (e.g. "en-US")

- default_target_locale TEXT NOT NULL (e.g. "de-DE")

- created_at TEXT NOT NULL (ISO)

- updated_at TEXT NOT NULL (ISO)


3) project_locales

- id TEXT PRIMARY KEY (UUID)

- project_id TEXT NOT NULL (FK projects.id)

- locale_code TEXT NOT NULL (BCP-47)

- is_enabled INTEGER NOT NULL (0/1)

- is_default INTEGER NOT NULL (0/1)

- rules_json TEXT NOT NULL DEFAULT "{}"

Indexes:

- (project_id, locale_code) unique


4) assets

- id TEXT PRIMARY KEY (UUID)

- project_id TEXT NOT NULL

- asset_type TEXT NOT NULL (xlsx/csv/folder_media/zip_media/text_request/etc.)

- original_name TEXT

- source_channel TEXT NOT NULL DEFAULT "manual"

- received_at TEXT NOT NULL

- content_hash TEXT

- storage_path TEXT

- size_bytes INTEGER

Indexes:

- (project_id, received_at)


5) schema_profiles

- id TEXT PRIMARY KEY (UUID)

- project_id TEXT NOT NULL

- signature TEXT NOT NULL  # hash of headers/sheet/colcount

- mapping_json TEXT NOT NULL

- confidence REAL NOT NULL DEFAULT 0.0

- confirmed_by_user INTEGER NOT NULL DEFAULT 0

- created_at TEXT NOT NULL

- updated_at TEXT NOT NULL

Indexes:

- (project_id, signature) unique


6) segments

- id TEXT PRIMARY KEY (UUID)

- asset_id TEXT NOT NULL

- sheet_name TEXT

- row_index INTEGER

- key TEXT

- source_locale TEXT NOT NULL

- source_text TEXT NOT NULL

- cn_text TEXT

- context_json TEXT NOT NULL DEFAULT "{}"

- char_limit INTEGER

- placeholders_json TEXT NOT NULL DEFAULT "[]"

Indexes:

- (asset_id, row_index)


7) translation_candidates

- id TEXT PRIMARY KEY (UUID)

- segment_id TEXT NOT NULL

- target_locale TEXT NOT NULL

- candidate_text TEXT NOT NULL

- candidate_type TEXT NOT NULL

- score REAL NOT NULL DEFAULT 0.0

- model_info_json TEXT NOT NULL DEFAULT "{}"

- generated_at TEXT NOT NULL

Indexes:

- (segment_id, target_locale)


8) approved_translations

- id TEXT PRIMARY KEY (UUID)

- segment_id TEXT NOT NULL

- target_locale TEXT NOT NULL

- final_text TEXT NOT NULL

- status TEXT NOT NULL DEFAULT "approved"

- approved_by TEXT

- approved_at TEXT NOT NULL

- revision_of_id TEXT

- is_pinned INTEGER NOT NULL DEFAULT 0

Indexes:

- (segment_id, target_locale) unique


9) tm_entries

- id TEXT PRIMARY KEY (UUID)

- project_id TEXT NOT NULL

- source_locale TEXT NOT NULL

- target_locale TEXT NOT NULL

- source_text TEXT NOT NULL

- target_text TEXT NOT NULL

- normalized_source_hash TEXT NOT NULL

- origin TEXT NOT NULL

- origin_asset_id TEXT

- origin_row_ref TEXT

- created_at TEXT NOT NULL

- updated_at TEXT NOT NULL

- last_used_at TEXT

- use_count INTEGER NOT NULL DEFAULT 0

- quality_tag TEXT NOT NULL DEFAULT "trusted"

Indexes:

- (project_id, source_locale, target_locale, normalized_source_hash)


10) glossary_terms

- id TEXT PRIMARY KEY (UUID)

- project_id TEXT NOT NULL  # use "global" for global glossary later

- locale_code TEXT NOT NULL

- source_term TEXT NOT NULL

- target_term TEXT NOT NULL

- rule TEXT NOT NULL DEFAULT "must_use"

- match_type TEXT NOT NULL DEFAULT "whole_token"

- case_sensitive INTEGER NOT NULL DEFAULT 1

- allow_compounds INTEGER NOT NULL DEFAULT 0

- compound_strategy TEXT NOT NULL DEFAULT "hyphenate"

- negative_patterns_json TEXT NOT NULL DEFAULT "[]"

- notes TEXT

- created_at TEXT NOT NULL

- updated_at TEXT NOT NULL

Indexes:

- (project_id, locale_code, source_term) unique


11) qa_flags

- id TEXT PRIMARY KEY (UUID)

- segment_id TEXT NOT NULL

- target_locale TEXT NOT NULL

- type TEXT NOT NULL

- severity TEXT NOT NULL

- message TEXT NOT NULL

- span_json TEXT NOT NULL DEFAULT "{}"

- created_at TEXT NOT NULL

- resolved_at TEXT

- resolved_by TEXT

- resolution TEXT

Indexes:

- (segment_id, target_locale)


12) jobs

- id TEXT PRIMARY KEY (UUID)

- project_id TEXT NOT NULL

- asset_id TEXT

- job_type TEXT NOT NULL

- targets_json TEXT NOT NULL DEFAULT "[]"

- status TEXT NOT NULL

- created_at TEXT NOT NULL

- started_at TEXT

- finished_at TEXT

- summary TEXT

- decision_trace_json TEXT NOT NULL DEFAULT "{}"

Indexes:

- (project_id, created_at)


FTS5:

- For Ticket 1 you may skip creating the FTS5 virtual table, but include a TODO and a placeholder function in schema.py to add it in a future migration.


#### MIGRATION MECHANISM

Implement a simple migration runner:

- schema_version is stored in schema_meta.

- On DB open, run `migrate_to_latest(db)` which applies sequential migrations.

- For Ticket 1, implement version 1 schema creation and set schema_version=1.

- Structure must allow later migrations (v2, v3, ...).


#### CONFIG FILE (projects/<slug>/config.yml)

YAML with NO secrets:

- project_name

- slug

- default_source_locale

- default_target_locale

- enabled_locales: list of locale codes (include default target)

- global_game_glossary_enabled: true/false (default true)

- model_policy: placeholder mapping of tasks to provider names (no keys)


#### CLI COMMANDS

Implement `tt` CLI with Typer.


Commands:

1) `tt create-project <name> --slug <optional> --source en-US --target de-DE --targets de-DE,fr-FR,...`

- Creates folder + subfolders + config.yml + project README.txt

- Initializes project.db schema

- Inserts project row and project_locales rows

- Prints project path and next steps


2) `tt project-info <slug>`

- Reads config + DB project row and prints summary (locales enabled, DB schema version)


Default projects root: ./projects (relative to current working directory). Also accept `--root` to change.


#### TESTS

Write pytest tests:

- Creating a project creates correct directories and files.

- project.db exists and has schema_meta schema_version=1.

- project row exists with correct name/slug/locales.

- No API keys stored in config.yml (assert no keys like "api_key" fields present).

Use temporary directories (tmp_path fixture).


#### README

Document:

- Setup (pip install -e .)

- Create project example

- Project folder structure

- Notes: secrets stored via OS keychain later (Ticket 6+), not in config.


#### IMPLEMENTATION RULES

- Keep code clear and minimal. No premature abstractions beyond what’s needed for extendability.

- Use ISO timestamps (UTC).

- Use UUIDs for IDs.

- Use pathlib everywhere.

- Ensure Windows path compatibility.

- Print a short plan before implementing, then implement.


Now implement Ticket 1 ONLY.


Ticket 2:

You are Codex, an expert Python engineer. Implement **Ticket 2** only.


You already have Ticket 1: local-first project creation (project folder + SQLite schema + CLI).

Now add an MVP importer for XLSX/CSV with a minimal Streamlit UI to do **manual column mapping** and persist segments.


<a id="ticket-2"></a>
### TICKET 2: IMPORT XLSX/CSV + MANUAL COLUMN MAPPING + STORE SEGMENTS


GOAL

Add the ability to:

1) Select an existing project (by slug) under a projects root folder.

2) Import an XLSX or CSV file.

3) Choose sheet (for XLSX).

4) Manually map columns to roles:

   - Source column (required) (e.g. EN)

   - Target column (optional for now; still capture it in mapping)

   - Optional CN column

   - Optional Key/ID column

   - Optional CharLimit column

   - Optional additional context columns (multi-select)

5) Persist:

   - An Asset row

   - Segment rows (one per row with a non-empty source cell)

   - A SchemaProfile row (signature + mapping_json, confirmed_by_user=1, confidence=1.0)

6) Show a preview table in the UI and a post-import summary:

   - number of rows imported

   - number skipped (empty source)

   - which columns were mapped


No LLM usage in Ticket 2.


#### CONSTRAINTS

- Do not modify Ticket 1 schema in this ticket.

- Keep it cross-platform.

- No secrets storage.

- Bulk insert segments in a transaction for performance.

- UI language: English only.


#### DEPENDENCIES

Update pyproject.toml to add:

- streamlit

- pandas

- openpyxl (for XLSX)

- python-dateutil (optional, but ok)

If you add CSV support, pandas handles it; no extra deps needed.


#### REPO STRUCTURE CHANGES

Create:

/tt_app/

  streamlit_app.py

  pages/

    1_Select_Project.py

    2_Import_File.py


Create or extend core modules:

/tt_core/importers/

  __init__.py

  xlsx_reader.py         # load sheets, headers, dataframe preview

  import_service.py      # create Asset + Segments + SchemaProfile

  signature.py           # compute schema profile signature hash

/tt_core/db/

  session.py             # helper to open Session(engine) if you don't already have it


You may add minimal SQLModel models if useful, but do not refactor Ticket 1 extensively.


#### MAPPING JSON FORMAT (store into schema_profiles.mapping_json)

Store a JSON object like:

{

  "file_type": "xlsx"|"csv",

  "sheet_name": "Sheet1",

  "columns": {

    "source": "<column name>",

    "target": "<column name or null>",

    "cn": "<column name or null>",

    "key": "<column name or null>",

    "char_limit": "<column name or null>",

    "context": ["<colA>", "<colB>", ...]

  }

}


#### SIGNATURE (schema_profiles.signature)

Compute a stable signature as SHA256 of:

- file_type

- sheet_name (empty string for csv)

- column names in order

- column count

Example string to hash:

"XLSX|Sheet1|colcount=12|cols=中文,英语-NEW,德语,..."


#### ASSET RECORD

When importing, create an assets row:

- project_id: from project table

- asset_type: "xlsx" or "csv"

- original_name: file name

- source_channel: "manual"

- received_at: now (UTC iso)

- content_hash: sha256 of file bytes (for uploaded file) if available; else empty/null

- storage_path: if user provided a local path, store it; if uploaded file, store null and keep in-memory only (MVP)

- size_bytes: size if known


#### SEGMENT CREATION RULES

For each row:

- Read source_text from mapped source column.

- If source_text is empty/NaN -> skip.

- source_locale is project's default_source_locale.

- sheet_name set for xlsx.

- row_index should match the original row index in the sheet (use dataframe index + header offset).

- key from key column if mapped.

- cn_text from cn column if mapped.

- char_limit from char_limit column if mapped and numeric; else null.

- context_json should include mapped context columns with their cell values, e.g.:

  {"filename": "...", "type": "..."}.

- placeholders_json: default "[]" (placeholder extraction comes later in Ticket 4).

Insert in a single transaction.


#### STREAMLIT UI

Implement a minimal Streamlit app:


Page 1: Select Project

- Input: projects root folder (default "./projects")

- List slugs (subdirectories with config.yml + project.db)

- Select a project, store selection in st.session_state


Page 2: Import File

- Option A: Upload file (st.file_uploader) for .xlsx/.csv

- Option B: Local path input (text) for power users (optional)

- If XLSX: choose sheet name from workbook

- Show dataframe preview (first 20 rows)

- Column mapping widgets:

  - source column (required)

  - target column (optional)

  - cn column (optional)

  - key column (optional)

  - char_limit column (optional)

  - context columns (multiselect)

- "Import" button:

  - Runs import_service.import_asset(...)

  - Shows summary + writes schema_profile


#### CLI (Optional in Ticket 2, nice-to-have)

If time permits, add:

`tt import-xlsx <slug> <path> --sheet <name> --source-col <col> [--cn-col ...] ...`

But do not block ticket completion if you skip this.


#### TESTS

Add tests in /tests:

- test_import_service_creates_asset_and_segments.py

Use a generated in-memory dataframe written to a temp .xlsx via pandas+openpyxl (or a small fixture file).

Validate:

- assets row inserted

- segments count correct (skips empty source)

- schema_profiles row inserted with confirmed_by_user=1

- signature stable (same inputs -> same signature)


#### ACCEPTANCE CRITERIA

- `streamlit run tt_app/streamlit_app.py` launches.

- You can select a project created by Ticket 1.

- You can import an XLSX, map columns manually, click Import.

- DB contains assets, segments, schema_profiles.

- `pytest -q` passes.


Now implement Ticket 2 only. Print a brief plan, then code.


Ticket 3:

You are Codex, an expert Python engineer. Implement **Ticket 3** only.


Ticket 1 and Ticket 2 already exist:

- Ticket 1: local-first projects + SQLite schema + CLI create-project/project-info

- Ticket 2: Streamlit importer with manual column mapping + Asset/Segments/SchemaProfile persisted


Now implement a minimal end-to-end workflow:

- Create a “translation job” that produces mock translations for segments

- Review/edit/approve per row

- Export a patch file (XLSX/CSV) with approved translations


NO Glossary, NO TM, NO QA, NO LLM calls in this ticket.

Use a mock translator only.


<a id="ticket-3"></a>
### TICKET 3: RUN JOB (MOCK) -> REVIEW/APPROVE -> EXPORT PATCH


GOAL

Add:

1) A Streamlit page to run a mock translation job for an imported asset.

2) A Streamlit review page to edit and approve translations per row.

3) An export page to create a patch XLSX/CSV with approved translations.


Data must be persisted in SQLite:

- jobs

- translation_candidates

- approved_translations


#### SCOPE / SIMPLICITY

- Support exactly ONE target locale per job in Ticket 3:

  - default: project.default_target_locale

  - allow user to select another enabled target locale (single select)

- The job should operate on a selected Asset (choose from assets table).

- Do not attempt to write back into the original file (formatting etc.). Export a patch file only.


Patch file content (minimal but useful):

- key (if present)

- source_text

- approved_target_text

- row_index

- sheet_name

Optionally include cn_text if present.


#### REPO STRUCTURE CHANGES

Add Streamlit pages:

/tt_app/pages/

  3_Run_Job.py

  4_Review_Approve.py

  5_Export.py


Add core modules:

/tt_core/jobs/

  __init__.py

  job_service.py          # create job, run job, update status

  mock_translator.py      # deterministic mock translation

/tt_core/review/

  __init__.py

  review_service.py       # fetch candidates, save edits, approve

/tt_core/export/

  __init__.py

  export_patch.py         # write patch xlsx/csv into project exports/

Optionally add:

/tt_core/db/session.py    # helper to create SQLAlchemy/SQLModel sessions


#### JOB MODEL USAGE (existing schema)

- Insert into jobs:

  - id uuid

  - project_id

  - asset_id

  - job_type = "mock_translate"

  - targets_json = ["<locale>"]

  - status transitions: queued -> running -> done (or failed)

  - decision_trace_json: store basic info (selected asset id, mapping signature if known)


- Insert into translation_candidates:

  - segment_id

  - target_locale

  - candidate_text = mock translation

  - candidate_type = "mock"

  - score = 1.0

  - model_info_json = {"provider":"mock","version":"1"}

  - generated_at = now


- Approvals:

  - Store into approved_translations with upsert on (segment_id, target_locale)

  - If user edits before approving:

    - Save edited draft back into translation_candidates as candidate_type="edited"

    - Or store edits in session_state and write only on approve (choose one approach; simplest: store as new candidate row and keep latest)


#### MOCK TRANSLATOR

Deterministic function:

mock_translate(source_text, target_locale) -> str

Suggested output:

- f"[{target_locale}] {source_text}"

No placeholder handling needed in Ticket 3.


#### STREAMLIT PAGES (English UI)


Page 3: Run Job

- Requires selected project in session_state (from Select Project page)

- Loads assets list for the project (order by received_at desc)

- User selects an asset (display original_name + received_at + id short)

- User selects target locale (single select) from enabled locales in project config/DB (exclude source locale)

- Button "Run mock translation"

  - Creates a job record

  - Generates translation_candidates for all segments in that asset (skip empty source_text; already skipped in import)

  - Marks job done

- Show summary: segments processed count, target locale, job id


Page 4: Review & Approve

- Select asset and target locale (same selection style)

- Show a table-like UI:

  - row_index, key, source_text, candidate_text (latest), approved_text (if exists)

- For each row, allow:

  - Edit text (text_input/text_area)

  - Approve checkbox/button

- Provide filters:

  - show all

  - show only not approved

  - show only approved

- On approve:

  - upsert approved_translations

- Provide "Approve selected" bulk action


Page 5: Export Patch

- Select asset + target locale

- Export options:

  - format: XLSX or CSV

  - filename prefix

- Button "Export"

  - Loads approved_translations for that asset+locale (join segments)

  - Writes patch file to projects/<slug>/exports/

  - File name example: patch_<slug>_<assetidshort>_<locale>_<timestamp>.xlsx

- Provide download link in Streamlit (st.download_button) AND show saved path.


#### DB QUERIES

Implement reusable query functions:

- list_assets(project_id)

- list_segments(asset_id)

- upsert_candidate(...)

- get_latest_candidate(segment_id, target_locale)

- upsert_approved_translation(segment_id, target_locale, final_text, approved_by="me")

- list_approved_for_asset(asset_id, target_locale)


Make sure to use transactions for bulk candidate inserts.


#### TESTS

Add tests:

- Create a temp project + import a small dataframe via import_asset (from Ticket 2)

- Run mock job in code (not Streamlit) and assert:

  - job row inserted

  - translation_candidates count equals segments count

- Approve one row and assert approved_translations upsert works

- Export patch and assert file is created and contains expected rows/columns


Use pytest tmp_path and pandas to read back exported XLSX/CSV.


#### ACCEPTANCE CRITERIA

- Streamlit app has pages 3/4/5 and they work end-to-end:

  Import -> Run Job -> Review/Edit/Approve -> Export Patch

- Data persists in SQLite

- pytest passes


Now implement Ticket 3 only. Print a brief plan, then code.


Ticket 3b:

You are Codex, an expert Python engineer. Implement **Ticket 3b** only.


Context:

- Ticket 1: project folder + SQLite schema + CLI create-project

- Ticket 2: Streamlit importer that stores assets/segments/schema_profiles; import stores `assets.storage_path` when user chose Local path; for uploads storage_path may be null.

- Ticket 3: mock job + review/approve + patch export exists (or is being implemented).


Now add an additional export mode specifically for LP workflows:

Export a COPY of the original XLSX with a NEW target column (e.g. "NEW DE") filled for approved rows.


<a id="ticket-3b"></a>
### TICKET 3b: EXPORT LP COPY WITH "NEW <LANG>" COLUMN


GOAL

Add an export option that creates an XLSX file in:

  projects/<slug>/exports/

based on the original imported XLSX, with an added column:

  "NEW <LANG>"

(e.g., "NEW DE", "NEW FR")

and writes the approved translations into that new column aligned to the correct rows.


This MUST NOT overwrite or modify the original file in-place.


#### ASSUMPTIONS / REQUIRED DATA

- We can locate the original file either by:

  A) `assets.storage_path` (local path imports), OR

  B) if the import was via upload, store a copy of the uploaded bytes under

     projects/<slug>/imports/<asset_id>_<original_name>

     (only for XLSX, and only if user consent checkbox is enabled).

If neither is available, the UI must show a clear error: "Original XLSX not available; use Patch Export instead."


- Column mapping is stored in schema_profiles.mapping_json (Ticket 2), including the original target column name.

- We will create the new column name as:

  "NEW " + <locale_short>

where locale_short is:

  - For "de-DE" -> "DE"

  - For "fr-FR" -> "FR"

  - Otherwise use the part before "-" uppercased.


#### FUNCTIONAL REQUIREMENTS


1) Determine original XLSX source to copy:

- Prefer assets.storage_path if it exists and file is present.

- Otherwise look for a stored copy in project imports folder:

  projects/<slug>/imports/<asset_id>_<original_name>

- Only XLSX supported in Ticket 3b. If asset_type != "xlsx", show error.


2) Find the correct sheet and row alignment:

- Use schema_profiles.mapping_json for this asset (match by signature if available) to know:

  - sheet_name (for XLSX)

  - mapped target column name (existing target col; may be null)

  - mapped key/source columns etc. (not strictly required here)

- If multiple schema_profiles exist, choose the newest (latest updated_at) for that project+signature used at import.

If you did not store signature on asset, then:

  - use the most recent schema_profile for the project whose mapping_json.sheet_name matches the selected sheet_name, OR

  - add a simple query UI where user selects the schema_profile to use (acceptable fallback).


Row alignment rule:

- segments.row_index is stored as Excel 1-based row index (header=1, first data row=2).

- When writing approved translations, use segments.row_index to locate the row.

- Do NOT rely on pandas re-exporting the entire sheet; preserve existing workbook structure as much as possible.


3) Add the NEW column:

- Add a new header cell in the header row (row 1) with value "NEW XX" (e.g., "NEW DE").

- If a column with that name already exists:

  - DO NOT create another. Reuse it (overwrite only those rows that are approved; leave others untouched).


4) Fill approved values:

- For the selected asset_id and target_locale:

  - Load all approved translations joined with segments:

    - segments.row_index, segments.sheet_name, approved_translations.final_text

- Write final_text into the NEW column at the matching row_index.

- Only write for rows with approved translations.

- Do not clear cells for unapproved rows.


5) Output file naming:

- Save to exports folder as:

  lp_<slug>_<assetidshort>_<NEWCOL>_<timestamp>.xlsx

Example:

  lp_open-dragon_a1b2c3_NEWDE_2026-02-22T12-30-00Z.xlsx


6) Streamlit UI integration:

- In Export page:

  - Add a selector "Export mode": ["Patch table", "LP copy with NEW column"]

  - If "LP copy with NEW column":

    - require asset_type == xlsx

    - show checkbox "Store a copy of uploaded XLSX inside project imports/" if asset has no storage_path (default OFF)

      - if checked and original bytes are available (from upload), persist them now

    - run export and show:

      - saved path

      - download button


#### IMPLEMENTATION NOTES

- Use openpyxl to load and modify the workbook, not pandas.

- Locate the sheet by name from mapping_json; if missing, default to the active sheet but show a warning.

- Find header row = 1. Find last column. Insert new column at the end (append), unless a "NEW XX" header already exists.

- Writing:

  - worksheet.cell(row=row_index, column=new_col_idx).value = final_text


- Make sure to close workbook properly and handle file I/O errors gracefully.


#### TESTS

Add tests:

- Create temp project.

- Generate a tiny XLSX with headers ["EN","DE"] and 3 data rows.

- Import it via Ticket 2 import_service (use local path so assets.storage_path is set).

- Insert approved_translations for 2 of the rows in DB.

- Run new export function:

  - Assert output file exists.

  - Load with openpyxl and verify:

    - header includes "NEW DE"

    - approved rows have correct values

    - unapproved row cell under NEW DE is unchanged/empty

- Also test idempotency:

  - If "NEW DE" already exists, function reuses it and does not add another column.


#### ACCEPTANCE CRITERIA

- From Streamlit Export page, user can export an XLSX copy with "NEW <LANG>" column.

- Column is created or reused; approved translations are written aligned by segments.row_index.

- Original XLSX is not modified.

- pytest passes.


Now implement Ticket 3b only. Print a brief plan, then code.


Ticket 4:

You are Codex, an expert Python engineer. Implement **Ticket 4** only.


Context:

- Ticket 1–3b are done (project+db, importer, mock job, review/approve, export patch + LP copy with NEW <LANG> column).


Now implement the **Placeholder Firewall + basic QA flags**, and integrate it into the mock translation job pipeline.

This ticket must not add TM/Glossary or real LLM calls.


<a id="ticket-4"></a>
### TICKET 4: PLACEHOLDER FIREWALL + QA FLAGS (FOUNDATION)


GOAL

1) Implement a placeholder/tag detection + protection system:

   - Extract placeholders/tags from source text

   - Replace them with stable tokens (e.g. ⟦PH_1⟧)

   - After translation, reinject the original placeholders exactly

2) Add basic QA checks that create qa_flags rows when something is wrong.

3) Integrate into the job pipeline so every candidate/approved output is protected + validated.


#### PLACEHOLDER TYPES TO SUPPORT (MVP)

Detect and protect at least these patterns:

- Curly placeholders: {0}, {1}, {playerName}

- Percent placeholders: %s, %d, %1$s

- Escapes/newlines: "\n" and "\\n" (treat both as placeholders; preserve exact form)

- Angle tags: <color=#FFFFFF>, </color>, <b>, </b>, <i>, </i>, <size=...>, <sprite=...>

- Double curly: {{var}} (optional but nice)


Rules:

- Placeholders MUST remain identical in the final output (same strings, same count).

- Reinject must be 1:1. No reformatting.


#### NEW MODULES

Create:

tt_core/qa/placeholder_firewall.py

tt_core/qa/checks.py


placeholder_firewall.py should expose:

- extract_placeholders(text) -> list[Placeholder]

- protect_text(text) -> ProtectedText (original, protected, placeholders, token_map)

- reinject(protected_text, translated_with_tokens) -> final_text

- validate_placeholders(original_text, final_text) -> list[str] (errors)


Represent placeholders with a small dataclass:

- type (enum string)

- value (exact substring)

- start/end (optional)

- token (e.g. ⟦PH_1⟧)


checks.py should include:

- check_placeholders_unchanged(source, target) -> QA issues

- check_newlines_preserved(source, target) -> QA issues (ensure \n vs \\n preserved)

(Keep it minimal; numbers/terminology later.)


#### DB INTEGRATION

- Store extracted placeholders into segments.placeholders_json (update on job run is OK)

- When generating translation_candidates:

  - run protect_text() on source_text

  - send protected text to translator (mock translator)

  - reinject tokens after translation

  - run QA checks

  - if issues found, insert qa_flags rows for that segment+locale

- Ensure QA flags are wiped/replaced for a new run (optional: delete old flags for that segment+locale before inserting new ones)


#### STREAMLIT REVIEW UI INTEGRATION

Update Review page:

- Add a filter "Only rows with QA flags"

- Show QA flag messages inline per row when present


#### TESTS

Add tests:

1) Placeholder extraction/protect/reinject round-trip:

   - "Deal {0} DMG\\n<color=#fff>Now</color>" must reinject exactly

2) QA detection:

   - If target is missing a placeholder, a qa_flag is created

3) Job integration test:

   - Import small XLSX fixture

   - Run mock job

   - Verify candidates exist AND placeholders are preserved

   - Verify qa_flags created for an intentionally broken candidate (you may simulate by providing a mock translator that drops tokens in a test)


#### ACCEPTANCE CRITERIA

- Running mock job preserves placeholders/tags/newlines exactly.

- QA flags are written to DB and visible in Review UI filter.

- pytest -q passes.

- No TM/Glossary/LLM work in this ticket.

============================================================


Now implement Ticket 4 only. Print a brief plan, then code.


Ticket 5:

You are Codex, an expert Python engineer. Implement **Ticket 5** only.


Context:

- Ticket 1–3b done: project/db, import, mock job, review/approve, export patch + LP copy with NEW <LANG> column.

- Ticket 4 done: Placeholder firewall + QA flags + review UI filter for QA flags.

Now implement the **Glossary must-use engine** with robust matching to avoid substring false positives and handle common game compounds.


No TM work in this ticket. No real LLM calls. Keep it deterministic.


<a id="ticket-5"></a>
### TICKET 5: GLOSSARY MUST-USE (MATCHING + ENFORCEMENT)


GOAL

1) Implement a glossary store + matcher that can find and enforce must-use terms in text.

2) Avoid false positives (e.g., "DMG" inside an unrelated word).

3) Handle simple compounds (e.g., "DMGBoost" -> "SCH-Boost") when allowed by rules.

4) Integrate enforcement into the translation pipeline BEFORE the mock translation and reinjection.

5) Create QA flags when glossary compliance is violated.


#### DATA MODEL (already exists)

Use existing table glossary_terms with columns:

- project_id (string; later "global" for global glossary)

- locale_code (target locale)

- source_term, target_term

- rule ("must_use" default)

- match_type ("whole_token" default)

- case_sensitive (int 0/1)

- allow_compounds (int 0/1)

- compound_strategy (string; default "hyphenate")

- negative_patterns_json (JSON list of regex strings)

- notes


We will treat only rule == "must_use" in Ticket 5.


#### MATCH TYPES (MVP)

Support at least:

- whole_token: match only when source_term is a standalone token (word boundary)

- exact: exact substring match (use sparingly; keep safe)

- (optional) word_boundary: like whole_token but for alphabetic words


Default for abbreviations like DMG/ATK should be whole_token + case_sensitive=1.


Implement:

- case_sensitive: if 0, match case-insensitively.

- negative_patterns_json: if any pattern matches the candidate context or full text, ignore the match.


Tokenization guidance:

- Treat boundaries between letters/numbers and non-alphanumerics as token boundaries.

- Also treat transitions like lower->upper (camel case) and digit boundaries as potential split points for compound detection.


#### COMPOUND HANDLING (MVP)

When allow_compounds=1 and match_type=whole_token:

- Detect tokens that start with source_term followed by additional letters/digits, e.g. "DMGBoost", "ATKUp", "HP100"

- Apply compound_strategy:

  - "hyphenate": target_term + "-" + rest (rest preserved as-is for MVP)

    Example: DMGBoost -> SCH-Boost if source_term=DMG, target_term=SCH

  - "keep_source": leave token unchanged (for projects that want DMGBoost unchanged)

  - "replace_prefix": target_term + rest (no hyphen)


IMPORTANT:

- Do NOT apply a substring replacement inside an unrelated word if allow_compounds=0.

- Do NOT apply compounds if the token contains the source_term not at the start (e.g., "MegaDMGBoost" should not match prefix unless you explicitly decide; MVP: only prefix match).


#### ENFORCEMENT STRATEGY

We want must-use constraints. In Ticket 5, implement enforcement as follows:


Pipeline order for each segment (per target locale):

1) Placeholder firewall: protect source_text -> protected_source

2) Glossary enforcement on protected_source:

   - Replace matched terms/tokens in protected_source with their enforced target forms BUT as special "locked tokens"

     Example: "Deal DMG" -> "Deal ⟦TERM_1⟧" where TERM_1 maps to "SCH"

     Example: "DMGBoost" -> "⟦TERM_2⟧" mapping to "SCH-Boost"

   - Keep a term_map of TERM tokens -> enforced strings

3) Mock translation runs on the string containing TERM tokens.

4) After mock translation, reinject TERM tokens first (replace ⟦TERM_n⟧ with enforced strings),

   then reinject placeholders via placeholder firewall (or vice versa, but must be consistent).

5) Run QA checks:

   - If any must-use term that should have been enforced is missing in final output, create qa_flag type="glossary_violation".

   - Also flag if an enforced term token was modified or not reinjected.


Note: Since mock translation is deterministic and does not remove tokens, the QA should normally pass, but this architecture is needed for real LLM later.


#### GLOBAL GLOSSARY (OPTIONAL IN TICKET 5)

If project config has global_game_glossary_enabled=true:

- Load additional glossary_terms where project_id == "global" (if any exist).

- If none exist yet, seed a very small set on project creation is OUT OF SCOPE here.

In Ticket 5, just implement the ability to query and combine (project + global).


Priority:

- project glossary overrides global if same source_term exists.


#### MODULES TO CREATE / UPDATE

Create:

tt_core/glossary/__init__.py

tt_core/glossary/glossary_store.py

tt_core/glossary/matcher.py

tt_core/glossary/enforcer.py


Update job pipeline code to call enforcer before translation:

- likely in tt_core/jobs/job_service.py or mock translator wrapper


Update QA:

- add in tt_core/qa/checks.py:

  - check_glossary_compliance(expected_enforcements, final_text) -> issues


Update Streamlit UI:

- In Review page, show glossary violations like other QA flags (already supported).


Add minimal CLI command (optional):

- `tt glossary-import <slug> <csv/xlsx>` is OUT OF SCOPE.

In Ticket 5 just implement DB operations programmatically; UI import can come later.


#### TESTS

Add tests for:

1) whole_token match avoids substrings:

   - term DMG->SCH whole_token must NOT match "ADMGX" or "randomg"

2) compound handling:

   - allow_compounds=1, strategy=hyphenate: "DMGBoost" -> "SCH-Boost"

   - allow_compounds=0: "DMGBoost" unchanged (no enforcement)

3) negative pattern:

   - if negative_patterns contains ".*IGNORE.*" and text includes IGNORE, do not match.

4) integration:

   - create temp project db

   - insert glossary_terms for project and locale

   - import a small asset with segments including "Deal DMG" and "DMGBoost"

   - run mock job for target locale

   - verify candidate_text contains enforced forms after reinjection

   - verify no glossary_violation flags for correct enforcement

   - simulate a broken translator in test that removes TERM tokens -> should produce glossary_violation qa_flags


#### ACCEPTANCE CRITERIA

- Glossary must-use enforcement works deterministically.

- Substring false positives avoided for whole_token.

- Basic compound prefix handling works for DMGBoost-style tokens.

- QA flags are created for glossary violations.

- Integrated into job pipeline before translation.

- pytest -q passes.


Now implement Ticket 5 only. Print a brief plan, then code.


Ticket 6:

You are Codex, an expert Python engineer. Implement **Ticket 6** only.


Context:

- Ticket 1–3b done: project/db, import, mock job, review/approve, export patch + LP copy with NEW <LANG>.

- Ticket 4 done: placeholder firewall + QA flags integration.

- Ticket 5 done: glossary must-use enforcement + glossary QA flags.


Now implement **Translation Memory (TM)** with:

- exact match retrieval via normalized hash

- full-text search (FTS5) for candidate retrieval

- fuzzy reranking (rapidfuzz) on top FTS hits

- safe auto-learning: ONLY approved translations are written into TM


No real LLM calls in this ticket.


<a id="ticket-6"></a>
### TICKET 6: TM STORE + SEARCH (FTS5) + AUTO-LEARN FROM APPROVALS


GOAL

1) Add a DB migration (schema_version 2) that creates an FTS5 table for TM search.

2) Implement TM store APIs:

   - upsert TM entries

   - exact lookup by normalized_source_hash

   - FTS search + fuzzy rerank

3) Integrate TM retrieval into the job pipeline:

   - Prefer TM exact for segments if available

   - Optionally use high-confidence fuzzy match (threshold-based) before mock translation

4) Integrate “learning”:

   - On approve (approved_translations upsert), also upsert into tm_entries (and tm_fts)

   - TM learns ONLY from approved outputs (never from drafts)


#### DB MIGRATION (v2)


Add MIGRATION v2 in tt_core/db/migrations.py:

- Create FTS5 virtual table `tm_fts` with columns:

  - project_id UNINDEXED

  - source_locale UNINDEXED

  - target_locale UNINDEXED

  - source_text

  - target_text

  - tm_id UNINDEXED (TEXT uuid from tm_entries.id)

Example:

  CREATE VIRTUAL TABLE IF NOT EXISTS tm_fts USING fts5(

    project_id UNINDEXED,

    source_locale UNINDEXED,

    target_locale UNINDEXED,

    source_text,

    target_text,

    tm_id UNINDEXED

  );


- Set schema_version=2.


NOTE:

- Do not change existing tables in this ticket (only add FTS table).

- Ensure migrate_to_latest upgrades existing DBs from v1 to v2.


#### TM NORMALIZATION / HASH

Implement a stable normalization for hashing:

- trim whitespace

- collapse internal whitespace to single spaces

- keep case as-is OR lower-case; choose one and be consistent

Recommended:

- lower-case for matching stability

- do NOT remove punctuation (yet)

Compute:

  normalized_source_hash = sha256(normalized_source_text.encode("utf-8")).hexdigest()


Add helper in:

tt_core/tm/normalize.py or inside tm_store.py


#### TM STORE API

Create:

tt_core/tm/__init__.py

tt_core/tm/tm_store.py

tt_core/tm/tm_search.py


tm_store.py functions:

- upsert_tm_entry(

    db_path, project_id, source_locale, target_locale,

    source_text, target_text,

    origin, origin_asset_id=None, origin_row_ref=None,

    quality_tag="trusted"

  ) -> tm_id

Behavior:

- Compute normalized_source_hash

- Check if a tm_entries row exists for:

  (project_id, source_locale, target_locale, normalized_source_hash)

  If exists: update target_text, updated_at; else insert new id.

- Also upsert into tm_fts:

  - Remove any tm_fts rows for that tm_id then insert the current row (simplest)

  - Or implement "INSERT ...; DELETE ..." carefully

- Keep use_count/last_used_at unchanged on upsert.


- record_tm_use(db_path, tm_id): increment use_count and set last_used_at=now.


tm_search.py functions:

- find_exact(db_path, project_id, source_locale, target_locale, source_text) -> TMEntry|None

  - uses normalized hash lookup in tm_entries

- search_fts(db_path, project_id, source_locale, target_locale, query_text, limit=50) -> list[TMHit]

  - Query tm_fts with MATCH and filters:

    WHERE tm_fts MATCH :q AND project_id=:pid AND source_locale=:sl AND target_locale=:tl

  - Return tm_id, source_text, target_text

- search_fuzzy(db_path, ..., source_text, limit=5) -> list[TMHitWithScore]

  - Use search_fts to get candidates

  - Re-rank with rapidfuzz (e.g. fuzz.ratio or fuzz.token_set_ratio) comparing normalized source_text

  - Return top N with score


FTS query safety:

- Implement a simple sanitizer that:

  - strips quotes

  - extracts alnum tokens

  - joins with " OR " for recall

  - fallback to exact-like search if token list empty


#### PIPELINE INTEGRATION (JOB RUN)


Update the translation pipeline order per segment (per target locale):


1) Placeholder firewall protect source_text -> protected_source

2) Glossary enforcement tokens -> glossary_protected_source (from Ticket 5)

3) TM lookup should be done based on the ORIGINAL source_text (not the tokenized one), because TM stores real strings.

   - exact_match = find_exact(...)

   - If exact_match found:

       candidate_text = exact_match.target_text

       candidate_type = "tm_exact"

       score = 1.0

       record_tm_use()

       Still run placeholder + glossary QA checks against source/target:

         - placeholder unchanged

         - glossary compliance (if violates, create qa_flag but keep candidate)

       Insert translation_candidate row and continue (skip mock translate)

   - Else:

       fuzzy_hits = search_fuzzy(...)

       If best score >= FUZZY_THRESHOLD (e.g. 92):

          use it as candidate_type="tm_fuzzy", score=best_score/100

          record_tm_use()

          still run QA checks

          insert candidate and skip mock translate

       Else:

          proceed with mock translation path (existing logic)


Keep the job deterministic and fast.

No LLM calls.


#### AUTO-LEARN FROM APPROVALS


Wherever approvals are written (review_service / approval upsert):

- After writing approved_translations (status approved), also call:

  upsert_tm_entry(

    project_id=project_id,

    source_locale=segment.source_locale,

    target_locale=target_locale,

    source_text=segment.source_text,

    target_text=final_text,

    origin="approved",

    origin_asset_id=segment.asset_id,

    origin_row_ref=f"{segment.sheet_name}:{segment.row_index}"

  )

This implements the “system learns only from approved” rule.


Do NOT write drafts/edited-but-not-approved into TM.


#### STREAMLIT UI (MINIMAL)

Optional but helpful:

- In Review page, display candidate_type and score (tm_exact/tm_fuzzy/mock).

- Add filter: show only tm-based suggestions (optional).


Do not overbuild.


#### TESTS


Add tests:

1) Migration test:

   - Create project DB (v1), then call initialize_database again and ensure schema_version becomes 2.

   - Assert tm_fts exists:

     SELECT name FROM sqlite_master WHERE type='table' AND name='tm_fts' (FTS tables appear as 'table')

2) TM upsert + exact lookup:

   - Insert tm entry, then find_exact returns it.

3) FTS + fuzzy:

   - Insert multiple tm entries, search_fuzzy returns most similar.

4) Pipeline uses TM:

   - Import small XLSX, approve one translation (auto-learns TM)

   - Re-run mock job (or run job on another asset with identical source_text)

   - Assert candidate_type becomes tm_exact and candidate_text equals approved target.

5) Ensure TM is NOT updated when translation is not approved:

   - Create a candidate but do not approve; tm_entries count unchanged.


All tests must pass: `pytest -q`.


#### ACCEPTANCE CRITERIA

- DB migrates to schema_version=2 and includes tm_fts.

- Exact TM lookup works and is used by job pipeline.

- FTS + fuzzy rerank works for near matches.

- Approving a row auto-learns into TM (and tm_fts).

- No drafts are added to TM.

- pytest passes.


Implement Ticket 6 only. Print a brief plan, then code.


Ticket 7:

You are Codex, an expert Python engineer. Implement **Ticket 7** only.


Context:

- Ticket 1–6 are done:

  - local-first projects + SQLite

  - importer + schema profiles

  - job run + review/approve + export patch + LP copy with NEW <LANG> column

  - placeholder firewall + QA flags

  - glossary must-use enforcement

  - TM + FTS5 + auto-learn from approvals


Now add the ability to use real LLM providers (BYOK) securely, with a policy layer that lets the user choose which provider/model to use per task.


<a id="ticket-7"></a>
### TICKET 7: LLM PROVIDER LAYER + KEYRING SETTINGS + TRANSLATION VIA LLM


GOAL

1) Add an LLM provider abstraction with at least:

   - MockProvider (always available, used in tests)

   - OpenAIProvider (BYOK; uses API key stored via keyring)

   - LocalProviderStub (no real local model calls yet; just scaffolding)

2) Add a model/policy config (no secrets) allowing per-task provider+model selection:

   - tasks: "translator", "reviewer", "schema_resolver" (schema resolver can remain unused for now)

3) Add Streamlit Settings page to enter/test API keys and choose policy.

4) Update the job pipeline so it can run either:

   - TM exact / TM fuzzy (already exists)

   - else LLM translator for draft

   - optional LLM reviewer only when risk score >= threshold

5) Ensure strict constraints:

   - Never store API keys in SQLite or config.yml

   - Preserve placeholders/tags/newlines and glossary terms (via your existing firewall+enforcer)

   - Always run QA after translator/reviewer; create qa_flags on failures

6) Tests must not call the network.


#### DEPENDENCIES

Add dependencies:

- keyring

- httpx (recommended) OR requests

Optionally:

- openai python sdk (ONLY if you prefer; otherwise do raw HTTP)


No new heavy frameworks.


#### REPO STRUCTURE

Add:

/tt_core/llm/

  __init__.py

  provider_base.py

  provider_mock.py

  provider_openai.py

  provider_local_stub.py

  policy.py

  prompts.py

/tt_app/pages/

  6_Settings_Providers.py    # new page


You may update existing job pipeline modules to call the provider.


#### KEY STORAGE (SECURE)

Use keyring for secrets:

- service name: "t-tool"

- key names:

  - "openai_api_key"

  - (optional future) "anthropic_api_key"


Implement helpers:

- set_secret(name, value)

- get_secret(name) -> str|None

- delete_secret(name)


Do NOT write these into config.yml or SQLite.


#### MODEL POLICY (NO SECRETS)

Store policy in project config.yml (safe):

model_policy:

  translator:

    provider: "openai" | "mock" | "local"

    model: "<string>"

  reviewer:

    provider: "openai" | "mock" | "local"

    model: "<string>"

  schema_resolver:

    provider: "mock" | "openai" | "local"

    model: "<string>"


Default:

- translator: openai (if key exists) else mock

- reviewer: mock (or openai) but only used when risk gated

- schema_resolver: mock


Implement:

- load_policy(project_path)

- save_policy(project_path, policy)


#### PROVIDER INTERFACE

Define an interface:


class LLMProvider:

  def generate(self, *, task: str, prompt: str, temperature: float, max_tokens: int) -> str


For now, plain text output is OK (no JSON requirement yet).


MockProvider:

- returns deterministic output:

  f"[{task}] {prompt[:200]}"


LocalProviderStub:

- deterministic placeholder behavior


OpenAIProvider:

- uses keyring to read openai_api_key

- makes a single chat/completions-style request (choose the API shape you prefer)

- must fail gracefully with a clear exception if no key is configured


IMPORTANT:

- Tests must not call OpenAI. Use dependency injection to swap providers.


#### PROMPTS (MVP)

Create prompt builders in tt_core/llm/prompts.py that take:

- source_text (original)

- protected_text (after placeholder protection + glossary enforcement tokens)

- target_locale

- style hints (from project config; default "informal, use Du for German")

Return a compact prompt instructing:

- translate from source to target

- DO NOT change placeholder tokens (⟦PH_*⟧) and term tokens (⟦TERM_*⟧)

- keep \n and \\n as-is

- output ONLY the translated string (no commentary)


Reviewer prompt:

- only run if risk_score >= threshold (see below)

- task: "reviewer"

- input: source + draft + constraints

- instructions: improve fluency but do not break tokens


#### RISK GATING FOR REVIEWER

Implement a simple risk score function (if you don’t already):

- +3 if char_limit is set

- +2 if placeholders present

- +2 if tags present

- +1 if multiple glossary hits

- +2 if very short source (< 12 chars)

If score >= 5: run reviewer, else skip.


Always run QA after reviewer.


#### PIPELINE INTEGRATION

Update the job run flow per segment (per target locale):

1) TM exact/fuzzy attempt (existing; keep as highest priority)

2) If no TM chosen:

   a) placeholder protect

   b) glossary enforce -> TERM tokens

   c) LLM translator on protected+TERM-tokenized text

   d) reinject TERM tokens

   e) reinject placeholders

   f) QA checks (placeholders + glossary)

   g) risk score gating -> optional reviewer:

      - run reviewer on the same tokenized representation OR on final text but preserving tokens

      - re-run QA

3) Save translation_candidates with candidate_type:

   - "llm_draft" or "llm_reviewed"

   Include model_info_json in candidates with provider+model.


If provider missing (no key), fall back to MockProvider automatically unless user explicitly forces openai.


#### STREAMLIT SETTINGS PAGE

Add page "Settings / Providers":

- Input for OpenAI API key (password field)

- Buttons: Save, Delete, Test

- Test: performs a tiny provider call (or just validates key present; avoid network if you want)

- Policy dropdowns:

  - translator provider + model string

  - reviewer provider + model string

Save policy to config.yml


Also show a warning:

- “API keys are stored in OS Keychain via keyring and are not written to disk.”


#### TESTS

Add tests that:

1) Ensure key is not written into config.yml or SQLite.

2) Provider selection works:

   - with no key, translator falls back to mock

3) Pipeline produces llm_draft candidate using MockProvider injection (no network).

4) Reviewer gating:

   - create a segment with char_limit -> reviewer should run (using mock provider) and candidate_type becomes llm_reviewed

5) QA flags still work (placeholders preserved).


Use dependency injection so providers are swappable in tests.


#### ACCEPTANCE CRITERIA

- Streamlit has a Settings page to set provider policy + store key via keyring.

- Running a job can use LLM provider (mock by default; OpenAI if configured).

- Placeholders/tags/glossary enforcement still preserved; QA flags created on violations.

- No secrets stored in files/DB.

- pytest -q passes.


Implement Ticket 7 only. Print a brief plan, then code.

Ticket 8:

You are Codex, an expert Python engineer. Implement **Ticket 8** only.


Context:

- Ticket 1–7 are done:

  - local-first projects + SQLite migrations

  - importer with manual mapping that stores assets + segments + schema_profiles

  - job run + review/approve + exports (patch + LP copy with NEW <LANG>)

  - placeholder firewall + QA flags

  - glossary must-use enforcement

  - TM + FTS5 + auto-learn from approvals

  - LLM provider layer + settings (optional use)


Now we must upgrade the importer so the system can correctly handle:

- LP files that already contain existing target translations (e.g., existing DE)

- Change-file type spreadsheets with OLD/NEW source columns and existing target columns


<a id="ticket-8"></a>
### TICKET 8: IMPORT v2 (EXISTING TARGET BASELINE + SOURCE OLD/NEW SUPPORT)


GOAL

1) Extend the importer to optionally capture **existing target text** from a mapped target column and store it as a baseline candidate:

   - translation_candidates.candidate_type = "existing_target"

   - This baseline must NOT auto-approve.

2) Add support for change-files by allowing mapping of **source_old** and **source_new** columns.

   - Store NEW source in segments.source_text (existing behavior)

   - Store OLD source in a new column segments.source_text_old (requires migration v3)

3) Update schema_profiles.mapping_json format to include these roles.


No change-file pipeline / no keep-update logic yet. This ticket is importer only.


#### DB MIGRATION (v3)

Add a migration v3 that:

- Adds column to segments:

  ALTER TABLE segments ADD COLUMN source_text_old TEXT;

- Sets schema_version=3.


Notes:

- Keep existing data intact.

- migrate_to_latest must upgrade v2 -> v3 correctly.


#### UPDATED MAPPING MODEL

Update ColumnMapping (and mapping_json) to include:


For LP (single source):

- source_new (required)  -> map to segments.source_text

- source_old (optional)  -> usually None


For Change-file (source update):

- source_new (required)

- source_old (required for this mode)


Also keep existing optional mappings:

- cn, key, char_limit, context (multi)


Target baseline capture:

- target column name (optional)

- target locale for that target column (required if target column is set)


Store mapping_json like:

{

  "file_type": "xlsx|csv",

  "sheet_name": "Sheet1",

  "columns": {

    "source_new": "EN-NEW",

    "source_old": "EN-OLD",

    "target": "DE",

    "target_locale": "de-DE",

    "cn": "...",

    "key": "...",

    "char_limit": "...",

    "context": ["..."]

  },

  "mode": "lp" | "change_source_update"

}


Keep backwards compatibility:

- If mapping_json has "source" from older imports, treat it as source_new.


#### STREAMLIT IMPORT UI CHANGES

Update Import page:

- Add a selector "Import mode": ["LP (single source)", "Change file (OLD/NEW source)"]

- If LP:

  - show "Source column" (maps to source_new)

  - hide source_old (or optional)

- If Change:

  - show both "Source NEW" and "Source OLD"


Target baseline:

- If user selects a target column (existing translations):

  - show a dropdown "Target locale for this column" (single select from enabled target locales; exclude source locale)

  - explain: "This imports existing translations as baseline candidates (not approved)."


Everything else stays: CN/key/char_limit/context columns.


#### IMPORT SERVICE CHANGES

Update import_asset() logic:


1) Build segments:

- source_text = value from source_new

- source_text_old = value from source_old (if mapped; else null)

- row_index logic stays as-is

- cn_text, key, char_limit, context_json unchanged


2) Insert baseline candidates (if target column mapped):

- For each segment row:

  - read target_text from mapped target column

  - if target_text is empty -> skip

  - insert into translation_candidates:

    - id uuid

    - segment_id

    - target_locale = mapped target_locale

    - candidate_text = target_text

    - candidate_type = "existing_target"

    - score = 1.0

    - model_info_json = {"provider":"import","kind":"baseline"}

    - generated_at = now


Important:

- Do not overwrite an existing approved_translation.

- If an approved_translation exists for (segment_id, target_locale), do NOT insert baseline candidate for that segment (avoid confusion).

- If a baseline candidate already exists for that segment+locale (candidate_type existing_target), you may either:

  - insert another row (history), or

  - skip; choose simplest consistent approach and document it.


3) Schema profile upsert remains (confirmed_by_user=1, confidence=1.0).


4) Performance:

- bulk insert segments and candidates in transactions.

- candidates insertion can be a separate bulk execute.


#### REVIEW UI (SMALL IMPROVEMENT)

Update Review page to show:

- If there is a baseline candidate and also a job-generated candidate:

  - show both (e.g., "Existing" and "Proposed")

- Provide a button "Use Existing" or "Use Proposed" per row (optional).

If too much for Ticket 8, just display "existing_target" as the current candidate when no other candidate exists.


#### TESTS

Add tests:

1) Migration v3:

- Create db at v2 then run initialize_database; schema_version becomes 3 and segments has source_text_old column.


2) Import baseline candidates:

- Create small XLSX with columns EN, DE, EN-OLD, EN-NEW (or just EN+DE for LP mode)

- Import in LP mode with target column DE and target_locale de-DE

- Assert:

  - segments inserted

  - translation_candidates inserted with candidate_type="existing_target" for non-empty DE rows

  - approved_translations remains empty


3) Import change mode old/new:

- Import with source_old + source_new mapping

- Assert segments.source_text_old and segments.source_text set correctly.


All tests must pass: pytest -q


#### ACCEPTANCE CRITERIA

- Streamlit Import page supports LP and Change-file mapping (OLD/NEW).

- Existing target translations can be imported as baseline candidates for a chosen target locale.

- DB schema version is 3 and segments includes source_text_old.

- pytest passes.

- No change-file pipeline/impact analysis yet (that is Ticket 9).


Now implement Ticket 8 only. Print a brief plan, then code.


You are Codex, an expert Python engineer. Implement **Ticket 8b** only.

Context:
- Ticket 1+: create_project exists in tt_core.project.create_project and CLI uses it.
- Streamlit UI exists with pages:
  1_Select_Project.py and 2_Import_File.py etc.

Now add a Streamlit UI flow to create a new project from within the app.

<a id="ticket-8b"></a>
### TICKET 8b: CREATE PROJECT IN STREAMLIT UI

GOAL
1) Add a Streamlit page "Create Project" that lets the user create a project without using the CLI.
2) Reuse the existing core function create_project() from tt_core.project.create_project.
3) After creating, automatically select the new project in session_state and navigate to Import page (or show a button).

#### UI REQUIREMENTS (English only)

Add page:
tt_app/pages/0_Create_Project.py  (so it appears first)

Form fields:
- Project name (required)
- Optional slug override
- Projects root folder (default from session_state["projects_root"] or "./projects")
- Source locale (default "en-US")
- Default target locale (default "de-DE")
- Additional target locales (comma-separated; optional)
- Checkbox: "Enable global game glossary" (default true)

Validation:
- Project name required
- Locales should be non-empty strings (basic validation)
- If slug provided, must be filesystem safe (reuse your slugify/validation logic already in core; otherwise show error)
- If folder already exists, show error (surface FileExistsError)

On submit:
- Call tt_core.project.create_project.create_project(...)
- On success:
  - st.success + show paths
  - set session_state:
    - selected_project_slug
    - selected_project_id
    - selected_project_source_locale
    - selected_project_path
    - selected_project_db_path
    - projects_root (normalized)
- Provide a button "Go to Import" (navigate to 2_Import_File) or show instructions.

#### CORE INTEGRATION
- Do NOT duplicate project creation logic in Streamlit.
- Ensure config.yml has model_policy placeholder and no secrets (existing behavior).
- Ensure project_locales include:
  - source locale enabled
  - default target locale enabled
  - additional targets enabled

If user leaves additional targets empty, still create with default target.

#### SELECT PROJECT PAGE UPDATE
Update 1_Select_Project.py:
- Add a link/notice at the top: “Create a new project in ‘Create Project’ page”.

#### TESTS
No new tests required for Ticket 8b (UI-only), but make sure:
- mypy not required
- pytest still passes

#### ACCEPTANCE CRITERIA
- Streamlit app shows a "Create Project" page.
- Creating a project from UI produces the same folder structure and DB schema as CLI create-project.
- After creation, project is selected and visible on the main page and Import page works.

Implement Ticket 8b only. Print a brief plan, then code.


<a id="ticket-9"></a>
### TICKET 9: CHANGE-FILE VARIANT B (OLD/NEW SOURCE + EXISTING TARGETS)
(Change-Management: Sorgt dafür, dass eine Change-Datei nicht blind komplett neu übersetzt wird, sondern dass das Tool gezielt entscheidet, was wirklich geändert werden muss. Erkennt Zeilen, wo EN-OLD ≠ EN-NEW -->klassifiziert pro Zeile: KEEP / UPDATE / FLAG (unklar/riskant → landet in Review))

You are Codex, an expert Python engineer. Implement **Ticket 9** only.

Context:
- Tickets 1–8 (+ 8b UI create project) are implemented.
- Import supports change mode with source_old/source_new into segments.source_text_old/source_text.
- Baseline targets can be imported as translation_candidates (existing_target).
- There is a job pipeline, review/approve UI, exports including LP copy with "NEW <LANG>" column.
- Placeholder firewall + glossary enforcement + TM + LLM provider are available.

============================================================
TICKET 9: CHANGE-FILE VARIANT B (OLD/NEW SOURCE + EXISTING TARGETS)
============================================================

GOAL
Implement a workflow for "Change file variant B":
- We have source_old and source_new (stored in segments.source_text_old and segments.source_text).
- Targets already exist (baseline candidates imported as existing_target).
- We must decide for each changed row whether to KEEP existing target, UPDATE with a proposed new translation, or FLAG for review.

No file-format-specific red coloring handling needed.

============================================================
DEFINITIONS
============================================================
- A segment is "changed" if source_text_old is not null AND source_text_old != source_text (string compare after trim).
- For a given target locale, baseline text is:
  - latest existing_target candidate if present
  - OR approved_translations if present (show it as current final)
- Proposed update is a new translation candidate, NOT auto-approved.

============================================================
IMPACT ANALYSIS (DETERMINISTIC FIRST)
============================================================
Implement a function classify_change(old, new) -> ("KEEP"|"UPDATE"|"FLAG", confidence, reason)

Rules (MVP):
- If normalize(old) == normalize(new) (whitespace-only): KEEP (confidence high)
- If only punctuation changed (.,!?:; quotes) and token content same: KEEP
- If placeholder/tag patterns changed: FLAG (risk)
- If length delta > 30% or word count delta > 20%: UPDATE
- Else: FLAG (or UPDATE depending on your preference; choose FLAG to be safe)

Optionally (risk-gated) you may call an LLM "impact_analyzer" when result is FLAG to decide KEEP vs UPDATE, returning JSON:
{ decision, confidence, reason }

============================================================
PROPOSAL GENERATION
============================================================
If decision == UPDATE:
- Generate a proposed translation candidate for target locale:
  - Use existing pipeline order:
    TM exact/fuzzy -> else LLM translator -> optional reviewer (risk-gated)
  - Must preserve placeholders/tags and enforce glossary as usual.
- Save candidate_type = "change_proposed"
- Score = confidence/100 or 1.0 if TM exact

If decision == KEEP:
- Do NOT generate a new candidate; keep baseline.
- But store the decision in a job decision trace and/or a lightweight per-segment record (can be JSON in job decision_trace_json).

If decision == FLAG:
- Do not overwrite anything; optionally generate a proposed candidate but mark it clearly as low-confidence (candidate_type="change_flagged_proposed") OR skip.
- Always create a QA flag type="stale_source_change" for visibility.

============================================================
DB / JOBS
============================================================
Add a new job_type: "change_variant_b"
- job targets_json includes the selected target locale(s) (for Ticket 9 support single locale only).
- decision_trace_json should store summary counts and rules used.

QA flags:
- Create qa_flags for:
  - "stale_source_change" (warn) when old!=new
  - "impact_flagged" (warn) when decision == FLAG
  - existing placeholder/glossary QA still applies to proposed candidates

============================================================
STREAMLIT UI
============================================================
Add a page (or extend Run Job page):
- "Run Change Review (Variant B)"
  - Choose asset
  - Choose target locale (single select)
  - Button: Run
  - Show summary counts: changed rows, keep/update/flag counts

Update Review page for this mode:
- Add a filter: "Only changed (stale)".
- For each row show:
  - source_old, source_new
  - baseline target (existing_target or approved)
  - proposed target (if any)
  - decision (keep/update/flag)
- Provide actions per row:
  - "Approve proposed" (writes approved_translations)
  - "Keep baseline" (optional: explicitly mark as reviewed/kept)
  - "Edit + approve" (manual edit)

EXPORT:
- Reuse "LP copy with NEW <LANG>" export.
- For this workflow, export should fill NEW <LANG> only for approved rows.

============================================================
TESTS
============================================================
Add tests:
1) Import a change-file style xlsx/dataframe with old/new source.
2) Import baseline existing target.
3) Run change_variant_b job:
   - ensure changed rows get qa_flag stale_source_change
   - ensure proposed candidates created only for UPDATE
4) Approve a proposed row -> TM learns (existing behavior)
5) Export LP copy with NEW <LANG> includes only approved rows.

pytest -q must pass.

============================================================
ACCEPTANCE CRITERIA
============================================================
- You can import change-file with old/new columns.
- Running change job produces keep/update/flag decisions.
- Proposed translations are generated only for UPDATE (or flagged proposals if you choose).
- Review UI shows old vs new and baseline vs proposed.
- Export produces a copy with NEW <LANG> column containing only approved changes.

<a id="ticket-10"></a>
### TICKET 10: CHANGE-FILE VARIANT A (FILL NEW TARGETS)
(Variant B = “Quelle geändert, aber Ziel existiert schon → entscheiden ob Update nötig ist”. 
Variant A = “Quelle geändert → NEW DE muss befüllt werden”)

You are Codex, an expert Python engineer. Implement **Ticket 10** only.

Context:
- Tickets 1–9 are done:
  - Import supports LP + Change mode and stores source_text_old/source_text.
  - Existing targets can be imported as baseline candidates (existing_target).
  - Placeholder firewall + QA flags, glossary must-use enforcement.
  - TM (exact + fuzzy) + auto-learn from approvals.
  - LLM provider layer works.
  - Ticket 9 implements Change Variant B (KEEP/UPDATE/FLAG) with review + export to NEW <LANG>.

Now implement **Change-file Variant A**:
- OLD/NEW source columns exist.
- “NEW <LANG>” is expected to be produced (often empty in input).
- We want to generate proposed translations for NEW source for changed rows, with optional baseline context.

============================================================
TICKET 10: CHANGE-FILE VARIANT A (FILL NEW TARGETS)
============================================================

GOAL
1) Add a new job type: "change_variant_a".
2) For each segment where source_text_old is not null and old!=new:
   - create a proposed translation candidate for the selected target locale:
     candidate_type="change_proposed"
3) For unchanged rows (old==new): do nothing by default.
4) Review UI shows:
   - source_old, source_new
   - baseline target (if any existing_target/approved)
   - proposed target
5) Export:
   - reuse existing "LP copy with NEW <LANG> column" export
   - fill NEW <LANG> only for APPROVED rows

This workflow differs from variant B:
- No KEEP/FLAG decision required in MVP; simply propose updates for changed rows.
- Still use QA and allow manual edits + approve.

============================================================
PROPOSAL GENERATION (use existing pipeline)
============================================================
For each changed segment:
- Use current pipeline order per target locale:
  TM exact/fuzzy -> else LLM translator -> risk-gated reviewer
- Must preserve placeholders/tags/newlines and enforce glossary as usual.
- Save translation_candidates:
  - candidate_type="change_proposed"
  - score: 1.0 for tm_exact; fuzzy score normalized; else based on provider or 0.5
  - model_info_json filled

QA:
- Run placeholder + glossary QA checks.
- Create qa_flags on violations as usual.
- Additionally create qa_flag type="stale_source_change" severity="warn" for changed segments (same as variant B).

============================================================
UI CHANGES
============================================================
Add a run option (either new page or extend Run Job page):
- "Run Change Job (Variant A)"
  - Select asset
  - Select target locale (single locale, enabled in project; exclude source locale)
  - Button: Run -> creates job, generates proposals for changed rows
  - Show summary counts: changed rows, proposals created

Review page:
- Add filter “Only change proposals (Variant A)”
- For each row show:
  - old/new source + proposed target
  - baseline target if exists (existing_target or approved)
- Actions:
  - Edit proposed
  - Approve (writes approved_translations)
  - Optional: “Skip” (no DB change)

Export page:
- No major changes required: user selects asset + locale and exports LP copy with "NEW <LANG>".
- Ensure export writes only approved translations (existing behavior).

============================================================
DB / QUERIES
============================================================
- Add helper queries:
  - list_changed_segments(asset_id)  (source_text_old not null and differs)
  - upsert_change_proposal(segment_id, target_locale, text, model_info, score)
  - list_proposals_for_asset(asset_id, target_locale) (candidate_type change_proposed)

Note: Keep approved_translations unique constraint behavior.

============================================================
TESTS
============================================================
Add tests:
1) Import a change-file-like dataset with old/new source for 3 rows (2 changed, 1 unchanged).
2) Run change_variant_a job for de-DE:
   - assert job exists
   - assert change_proposed candidates exist only for changed rows
   - assert stale_source_change qa_flags exist for changed rows
3) Approve 1 proposed row.
4) Export LP copy with NEW DE:
   - verify NEW DE column exists and only the approved row is filled.

pytest -q must pass.

============================================================
ACCEPTANCE CRITERIA
============================================================
- User can run "Change Variant A" on an imported change file.
- Proposed translations generated for changed rows only.
- Review/edit/approve works.
- Export produces a copy with NEW <LANG> filled only for approved changes.
- Tests pass.

Implement Ticket 10 only. Print a brief plan, then code.
