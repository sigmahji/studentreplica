"""Database connection settings shared by local and hosted backends."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import StaticPool


def normalize_database_url(value: str) -> URL:
    """Select Psycopg 3 and default remote PostgreSQL connections to TLS."""
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        raise ValueError("DATABASE_URL must be a valid SQLAlchemy connection URL.") from None
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() == "postgresql":
        if url.get_driver_name() != "psycopg":
            raise ValueError("Use postgresql+psycopg for the PostgreSQL backend.")
        local = url.host in (None, "localhost", "127.0.0.1", "::1")
        if not local and "sslmode" not in url.query:
            url = url.update_query_dict({"sslmode": "require"})
    return url


def connection_options(url: URL) -> dict[str, Any]:
    """Return fresh options; never retain a student's session or query results."""
    options: dict[str, Any] = {
        "future": True, "pool_pre_ping": True, "hide_parameters": True,
    }
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
    elif url.get_backend_name() == "postgresql":
        options.update(
            pool_size=5, max_overflow=5, pool_timeout=30, pool_recycle=300,
            # Compatible with hosted transaction poolers as well as direct connections.
            connect_args={"connect_timeout": 10, "prepare_threshold": None},
        )
    return options
