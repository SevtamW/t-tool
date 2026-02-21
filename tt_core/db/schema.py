from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

from tt_core.db.engine import create_sqlite_engine
from tt_core.db.migrations import migrate_to_latest


def initialize_database(db_path: Path) -> Engine:
    engine = create_sqlite_engine(db_path)
    migrate_to_latest(engine)
    return engine


def create_fts5_tables_placeholder(_engine: Engine) -> None:
    """Placeholder for future FTS5 migration work.

    TODO: Add an FTS5 virtual table in a dedicated migration (v2+)
    when full-text search features are introduced.
    """
    return None
