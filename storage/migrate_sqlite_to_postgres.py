"""Migrate local SQLite data into hosted PostgreSQL / Supabase."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from config import DEFAULT_DATABASE_PATH
from storage.connections import connection_options, normalize_database_url
from storage.database import init_db
from storage.models import (
    Account,
    AiCacheEntry,
    ChatMessage,
    ExternalIdentity,
    GeneratedArtifact,
    TwinRecord,
    TwinSnapshot,
)


def migrate(sqlite_path: str, postgres_url: str) -> None:
    """Copy all records from SQLite to PostgreSQL while preserving UUIDs and hashes."""
    norm_url = normalize_database_url(postgres_url)
    if norm_url.get_backend_name() != "postgresql":
        raise ValueError("Destination URL must be a PostgreSQL connection URL.")

    # Initialize destination tables & RLS
    dest_engine = init_db(norm_url.render_as_string(hide_password=False))

    src_url = f"sqlite:///{Path(sqlite_path).as_posix()}"
    src_engine = create_engine(src_url, **connection_options(normalize_database_url(src_url)))

    models = [
        Account,
        ExternalIdentity,
        TwinRecord,
        TwinSnapshot,
        ChatMessage,
        AiCacheEntry,
        GeneratedArtifact,
    ]

    print("Beginning migration from local SQLite to Supabase...")
    with Session(src_engine) as src_session, Session(dest_engine) as dest_session:
        for model in models:
            records = src_session.scalars(select(model)).all()
            print(f"  Found {len(records)} records in {model.__tablename__}")
            for record in records:
                dest_session.merge(record)
        dest_session.commit()
    print("Migration complete! All records merged into Supabase.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local SQLite to Supabase PostgreSQL")
    parser.add_argument(
        "--dest",
        required=True,
        help="Supabase connection string (e.g. postgresql+psycopg://postgres:PASSWORD@db.ixoxcwaharigczkhpexv.supabase.co:5432/postgres?sslmode=require)",
    )
    parser.add_argument(
        "--src",
        default=str(DEFAULT_DATABASE_PATH),
        help="Path to source SQLite database (defaults to database/studentreplica.db)",
    )
    args = parser.parse_args()

    try:
        migrate(args.src, args.dest)
    except Exception as exc:
        print(f"Migration error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
