"""Engine and session factory. No student data is cached at module level."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from sqlite3 import Connection as SQLiteConnection
from threading import RLock
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from config import DATABASE_URL
from storage.models import Base
from storage.sqlite_files import database_path, prepare_database_file

_engines: dict[str, Engine] = {}
_engine_lock = RLock()


def _configure_sqlite(
    connection: SQLiteConnection, _connection_record: ConnectionPoolEntry
) -> None:
    """Configure each built-in sqlite3 connection before its first transaction."""
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
    finally:
        cursor.close()


def get_engine(database_url: str | None = None) -> Engine:
    """Reuse connection pools by URL; overrides never change the default database."""
    url = database_url or DATABASE_URL
    path = database_path(url)
    if path is not None:
        url = (
            make_url(url)
            .set(database=path.as_posix())
            .render_as_string(hide_password=False)
        )
    with _engine_lock:
        if url not in _engines:
            prepare_database_file(url)
            options: dict[str, Any] = {"future": True, "pool_pre_ping": True}
            if url.startswith("sqlite"):
                options["connect_args"] = {"check_same_thread": False, "timeout": 30}
                if path is None:
                    options["poolclass"] = StaticPool
            engine = create_engine(url, **options)
            if engine.dialect.name == "sqlite":
                event.listen(engine, "connect", _configure_sqlite)
            _engines[url] = engine
        return _engines[url]


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Return the configured sessionmaker, initializing the engine if needed."""
    return sessionmaker(
        bind=get_engine(database_url), autoflush=False, autocommit=False, future=True
    )


def init_db(database_url: str | None = None) -> Engine:
    """Create all tables and return the engine."""
    with _engine_lock:
        engine = get_engine(database_url)
        Base.metadata.create_all(bind=engine)
        return engine


@contextmanager
def session_scope(database_url: str | None = None) -> Generator[Session, None, None]:
    """Yield a transactional session and always close it."""
    factory = get_session_factory(database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Drop the process engine (for isolated tests). Does not hold student data."""
    with _engine_lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
