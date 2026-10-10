"""Safe SQLite file creation and online backups using Python's built-in sqlite3."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from config import DEFAULT_DATABASE_PATH, LEGACY_DATABASE_PATH


def database_path(database_url: str) -> Path | None:
    """Resolve a file-backed SQLite URL without interpreting other database URLs."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return None
    if url.query.get("uri") == "true":
        return None
    return Path(url.database).expanduser().resolve()


def copy_database(source: Path, destination: Path) -> None:
    """Publish a consistent, integrity-checked backup without overwriting a file.

    SQLite's backup API includes committed WAL data. An exclusive lock serializes
    publishers; only a complete checked staging database becomes the destination.
    """
    source, destination = source.resolve(), destination.resolve()
    if not source.is_file():
        raise FileNotFoundError("The source SQLite database does not exist.")
    if source == destination:
        raise ValueError("The backup must use a different database file.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name(destination.name + ".copy.lock")
    deadline = time.monotonic() + 30
    while True:
        try:
            lock_handle = lock.open("x")
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError("Another database copy is still running.") from None
            time.sleep(0.1)
    try:
        if destination.exists():
            raise FileExistsError("The destination database already exists.")
        with tempfile.TemporaryDirectory(
            prefix=".sqlite-copy-", dir=destination.parent
        ) as tmp:
            staged = Path(tmp) / "copy.db"
            with closing(
                sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
            ) as src:
                with closing(sqlite3.connect(staged)) as dst:
                    src.backup(dst)
                    if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise RuntimeError(
                            "The database backup failed its integrity check."
                        )
            os.replace(staged, destination)
    finally:
        lock_handle.close()
        lock.unlink(missing_ok=True)


def migrate_legacy_database(source: Path, destination: Path) -> bool:
    """Copy the old database once; never merge into or replace an existing one."""
    if destination.exists() or not source.is_file():
        return False
    try:
        copy_database(source, destination)
    except FileExistsError:
        # A different process may have completed the same first-run migration.
        return False
    return True


def prepare_database_file(database_url: str) -> None:
    """Create SQLite's parent directory and preserve the former default database."""
    path = database_path(database_url)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path == DEFAULT_DATABASE_PATH.resolve():
        migrate_legacy_database(LEGACY_DATABASE_PATH, path)
