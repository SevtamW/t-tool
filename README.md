# t-tool (Ticket 1 Walking Skeleton)

This repository provides a local-first foundation for per-project translation tooling.

## Setup

```bash
python -m pip install -e .
```

For tests:

```bash
python -m pip install -e .[dev]
pytest
```

## CLI Usage

Create a project:

```bash
tt create-project "My Game" --source en-US --target de-DE --targets de-DE,fr-FR
```

Show project info:

```bash
tt project-info my-game
```

Optional projects root override:

```bash
tt create-project "Another Game" --root /path/to/projects
```

## Project Folder Structure

```text
projects/<slug>/
  project.db
  imports/
  exports/
  cache/
  config.yml
  README.txt
```

## Run project locally

```bash
  source .venv/bin/activate
  pip install -e ".[dev]"
  streamlit run tt_app/streamlit_app.py
```

## Notes

- Local-first only: each project has one SQLite DB file in its own folder.
- Schema migrations are versioned via `schema_meta.schema_version`.
- WAL mode is enabled for SQLite connections.
- `config.yml` stores non-secret settings only.
- Secrets (API keys, tokens) are intentionally not stored in SQLite or plaintext config.
- Planned future direction: OS keychain-backed secret handling (Ticket 6+).



## Delete all projects

```bash
rm -rf ./projects
```

```bash
SQLite:
PRAGMA foreign_keys = OFF;
DELETE FROM qa_flags;
DELETE FROM approved_translations;
DELETE FROM translation_candidates;
DELETE FROM jobs;
DELETE FROM segments;
DELETE FROM schema_profiles;
DELETE FROM assets;
DELETE FROM tm_fts;
DELETE FROM tm_entries;
DELETE FROM glossary_terms;
DELETE FROM project_locales;
DELETE FROM projects;
PRAGMA foreign_keys = ON;
VACUUM;
```