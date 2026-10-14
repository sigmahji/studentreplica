"""Engine and session factory. No student data is cached at module level."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from sqlite3 import Connection as SQLiteConnection
from threading import RLock

from sqlalchemy import DDL, create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from config import DATABASE_URL
from storage.connections import connection_options, normalize_database_url
from storage.models import Base
from storage.sqlite_files import database_path, prepare_database_file

_engines: dict[str, Engine] = {}
_initialized_engines: set[Engine] = set()
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
    parsed = normalize_database_url(database_url or DATABASE_URL)
    path = database_path(parsed.render_as_string(hide_password=False))
    if path is not None:
        parsed = parsed.set(database=path.as_posix())
    url = parsed.render_as_string(hide_password=False)
    with _engine_lock:
        if url not in _engines:
            prepare_database_file(url)
            options = connection_options(parsed)
            if parsed.get_backend_name() == "sqlite" and path is None:
                options["poolclass"] = StaticPool
            engine = create_engine(parsed, **options)
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
    """Initialize once per engine; hosted student tables are backend-only."""
    with _engine_lock:
        engine = get_engine(database_url)
        if engine not in _initialized_engines:
            with engine.begin() as connection:
                if engine.dialect.name == "postgresql":
                    # Serialize first startup across app processes on the same server.
                    connection.execute(select(func.pg_advisory_xact_lock(84161373)))
                Base.metadata.create_all(bind=connection)
                if engine.dialect.name == "postgresql":
                    for table in Base.metadata.sorted_tables:
                        connection.execute(
                            DDL("ALTER TABLE %(fullname)s ENABLE ROW LEVEL SECURITY")
                            .against(table)
                        )
            _initialized_engines.add(engine)
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
        _initialized_engines.clear()
