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

  source .venv/bin/activate
  pip install -e ".[dev]"
  streamlit run tt_app/streamlit_app.py

## Notes

- Local-first only: each project has one SQLite DB file in its own folder.
- Schema migrations are versioned via `schema_meta.schema_version`.
- WAL mode is enabled for SQLite connections.
- `config.yml` stores non-secret settings only.
- Secrets (API keys, tokens) are intentionally not stored in SQLite or plaintext config.
- Planned future direction: OS keychain-backed secret handling (Ticket 6+).
