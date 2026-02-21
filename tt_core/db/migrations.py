from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

Migration = Callable[[Connection], None]


def _table_exists(connection: Connection, table_name: str) -> bool:
    row = connection.execute(
        text(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name=:table_name LIMIT 1"
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def get_schema_version(connection: Connection) -> int:
    if not _table_exists(connection, "schema_meta"):
        return 0

    value = connection.execute(
        text("SELECT value FROM schema_meta WHERE key='schema_version' LIMIT 1")
    ).scalar_one_or_none()

    if value is None:
        return 0

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _set_schema_version(connection: Connection, version: int) -> None:
    connection.execute(
        text(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', :version) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        ),
        {"version": str(version)},
    )


def _migration_v1(connection: Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            default_source_locale TEXT NOT NULL,
            default_target_locale TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS project_locales (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            locale_code TEXT NOT NULL,
            is_enabled INTEGER NOT NULL,
            is_default INTEGER NOT NULL,
            rules_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_project_locales_project_locale
        ON project_locales(project_id, locale_code)
        """,
        """
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            original_name TEXT,
            source_channel TEXT NOT NULL DEFAULT 'manual',
            received_at TEXT NOT NULL,
            content_hash TEXT,
            storage_path TEXT,
            size_bytes INTEGER,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_assets_project_received_at
        ON assets(project_id, received_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_profiles (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            signature TEXT NOT NULL,
            mapping_json TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            confirmed_by_user INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_schema_profiles_project_signature
        ON schema_profiles(project_id, signature)
        """,
        """
        CREATE TABLE IF NOT EXISTS segments (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            sheet_name TEXT,
            row_index INTEGER,
            key TEXT,
            source_locale TEXT NOT NULL,
            source_text TEXT NOT NULL,
            cn_text TEXT,
            context_json TEXT NOT NULL DEFAULT '{}',
            char_limit INTEGER,
            placeholders_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_segments_asset_row_index
        ON segments(asset_id, row_index)
        """,
        """
        CREATE TABLE IF NOT EXISTS translation_candidates (
            id TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL,
            target_locale TEXT NOT NULL,
            candidate_text TEXT NOT NULL,
            candidate_type TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0.0,
            model_info_json TEXT NOT NULL DEFAULT '{}',
            generated_at TEXT NOT NULL,
            FOREIGN KEY(segment_id) REFERENCES segments(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_translation_candidates_segment_target
        ON translation_candidates(segment_id, target_locale)
        """,
        """
        CREATE TABLE IF NOT EXISTS approved_translations (
            id TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL,
            target_locale TEXT NOT NULL,
            final_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'approved',
            approved_by TEXT,
            approved_at TEXT NOT NULL,
            revision_of_id TEXT,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(segment_id) REFERENCES segments(id) ON DELETE CASCADE,
            FOREIGN KEY(revision_of_id) REFERENCES approved_translations(id)
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_approved_translations_segment_target
        ON approved_translations(segment_id, target_locale)
        """,
        """
        CREATE TABLE IF NOT EXISTS tm_entries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_locale TEXT NOT NULL,
            target_locale TEXT NOT NULL,
            source_text TEXT NOT NULL,
            target_text TEXT NOT NULL,
            normalized_source_hash TEXT NOT NULL,
            origin TEXT NOT NULL,
            origin_asset_id TEXT,
            origin_row_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT,
            use_count INTEGER NOT NULL DEFAULT 0,
            quality_tag TEXT NOT NULL DEFAULT 'trusted',
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(origin_asset_id) REFERENCES assets(id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tm_entries_lookup
        ON tm_entries(project_id, source_locale, target_locale, normalized_source_hash)
        """,
        """
        CREATE TABLE IF NOT EXISTS glossary_terms (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            locale_code TEXT NOT NULL,
            source_term TEXT NOT NULL,
            target_term TEXT NOT NULL,
            rule TEXT NOT NULL DEFAULT 'must_use',
            match_type TEXT NOT NULL DEFAULT 'whole_token',
            case_sensitive INTEGER NOT NULL DEFAULT 1,
            allow_compounds INTEGER NOT NULL DEFAULT 0,
            compound_strategy TEXT NOT NULL DEFAULT 'hyphenate',
            negative_patterns_json TEXT NOT NULL DEFAULT '[]',
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_glossary_terms_project_locale_source
        ON glossary_terms(project_id, locale_code, source_term)
        """,
        """
        CREATE TABLE IF NOT EXISTS qa_flags (
            id TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL,
            target_locale TEXT NOT NULL,
            type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            span_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT,
            resolution TEXT,
            FOREIGN KEY(segment_id) REFERENCES segments(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_qa_flags_segment_target
        ON qa_flags(segment_id, target_locale)
        """,
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            asset_id TEXT,
            job_type TEXT NOT NULL,
            targets_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            summary TEXT,
            decision_trace_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(asset_id) REFERENCES assets(id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_project_created_at
        ON jobs(project_id, created_at)
        """,
    )

    for statement in statements:
        connection.exec_driver_sql(statement)


MIGRATIONS: dict[int, Migration] = {
    1: _migration_v1,
}


def migrate_to_latest(engine: Engine) -> int:
    current_version = 0

    with engine.begin() as connection:
        current_version = get_schema_version(connection)

        for target_version in sorted(MIGRATIONS):
            if target_version <= current_version:
                continue
            MIGRATIONS[target_version](connection)
            _set_schema_version(connection, target_version)
            current_version = target_version

    return current_version
