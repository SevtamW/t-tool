from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlmodel import Session

from tt_core.db.engine import create_sqlite_engine


@contextmanager
def session_for_db(db_path: Path) -> Iterator[Session]:
    """Yield a SQLModel session for a project SQLite database."""

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()
