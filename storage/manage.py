"""Local administrator commands; only health metadata is printed, never records."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from config import DATABASE_URL
from storage.database import init_db
from storage.models import Base
from storage.sqlite_files import copy_database, database_path


def check_database(database_url: str = DATABASE_URL) -> dict[str, Any]:
    """Check an existing SQLite file read-only without exposing student data."""
    path = database_path(database_url)
    if path is None or not path.is_file():
        raise FileNotFoundError("Initialize the SQLite database first.")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_key_errors = len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        )
        available = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = set(Base.metadata.tables)
        missing = sorted(required - available)
        # Table names come exclusively from application metadata, never user input.
        counts = {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in sorted(required & available)
        }
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
    return {
        "status": (
            "ok"
            if integrity == ["ok"] and not foreign_key_errors and not missing
            else "error"
        ),
        "database": str(path),
        "engine": "Python built-in sqlite3",
        "sqlite_version": sqlite3.sqlite_version,
        "integrity_check": integrity,
        "foreign_key_errors": foreign_key_errors,
        "missing_tables": missing,
        "journal_mode": journal,
        "row_counts": counts,
    }


def backup_database(database_url: str = DATABASE_URL) -> Path:
    """Save a consistent private backup, including committed write-ahead log data."""
    source = database_path(database_url)
    if source is None or not source.is_file():
        raise FileNotFoundError("Initialize the SQLite database first.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-UTC")
    destination = (
        source.parent / "backups" / f"{source.stem}-{stamp}-{uuid4().hex[:8]}.db"
    )
    copy_database(source, destination)
    return destination


def main() -> int:
    """Run database setup, validation or backup from the project directory."""
    parser = argparse.ArgumentParser(description="StudentReplica SQLite maintenance")
    parser.add_argument("command", choices=["init", "check", "backup"])
    args = parser.parse_args()
    try:
        if args.command == "init":
            init_db()
        if args.command == "backup":
            print(json.dumps({"status": "ok", "backup": str(backup_database())}))
            return 0
        report = check_database()
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "ok" else 1
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        print(
            f"Database operation failed ({type(error).__name__}). Existing files were not deleted."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
