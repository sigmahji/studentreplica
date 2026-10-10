"""Persistent SQLite storage, safe migration, credentials and connection isolation."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import select

from config import DEFAULT_DATABASE_PATH
from storage.auth import create_account, login_account
from storage.context import UserContext
from storage.database import get_engine, init_db, reset_engine, session_scope
from storage.manage import backup_database, check_database
from storage.models import Account
from storage.repository import TwinRepository
from storage.sqlite_files import copy_database, migrate_legacy_database
from storage.twin_schema import empty_twin


def sqlite_url(path: Path) -> str:
    """Create an absolute URL for a test-owned database."""
    return f"sqlite:///{path.as_posix()}"


def database_dump(path: Path) -> list[str]:
    """Compare synthetic database contents without printing private records."""
    with closing(sqlite3.connect(path)) as connection:
        return list(connection.iterdump())


def test_default_path_and_sqlite_connection_protections(db, tmp_path) -> None:
    assert DEFAULT_DATABASE_PATH.parent.name == "database"
    assert DEFAULT_DATABASE_PATH.name == "studentreplica.db"
    nested = tmp_path / "separate_database" / "nested" / "students.db"
    engine = init_db(sqlite_url(nested))
    assert nested.is_file()
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 2


def test_accounts_and_all_private_records_survive_restart_without_mixing(db) -> None:
    users = []
    with session_scope(db) as session:
        for suffix in ("a", "b"):
            result = create_account(
                session, username=f"persistent_{suffix}", password=f"password-{suffix}"
            )
            assert result.ok
            ctx = UserContext(user_id=result.user_id)
            users.append(ctx)
            marker = f"PRIVATE_STUDENT_{suffix.upper()}_ONLY"
            twin = empty_twin(marker)
            twin["academic"]["semesters"] = [{"semester": 1, "notes": marker}]
            twin["achievements"] = [{"title": marker}]
            repo = TwinRepository(session)
            repo.save_twin(ctx, twin)
            repo.add_chat_message(ctx, "user", marker)
            repo.set_ai_cache(ctx, f"{ctx.user_id}:persistence", {"text": marker})
            repo.save_artifact(ctx, "cv", {"text": marker})
    reset_engine()
    init_db(db)
    with session_scope(db) as session:
        repo = TwinRepository(session)
        for index, suffix in enumerate(("a", "b")):
            result = login_account(
                session,
                username=f"PERSISTENT_{suffix.upper()}",
                password=f"password-{suffix}",
            )
            assert result.ok and result.user_id == users[index].user_id
            assert not login_account(
                session, username=f"persistent_{suffix}", password="wrong-password"
            ).ok
            blob = "\n".join(repo.dump_user_strings(users[index]))
            assert f"PRIVATE_STUDENT_{suffix.upper()}_ONLY" in blob
            other = "B" if suffix == "a" else "A"
            assert f"PRIVATE_STUDENT_{other}_ONLY" not in blob
            assert len(repo.list_snapshots(users[index])) == 1
            assert len(repo.get_chat_history(users[index])) == 1
            assert len(repo.list_artifacts(users[index])) == 1


def test_database_override_cannot_redirect_later_default_sessions(
    db, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    with session_scope() as session:
        assert create_account(session, username="default_only", password="secret123").ok
    other = sqlite_url(tmp_path / "other_database.db")
    init_db(other)
    with session_scope(other) as session:
        assert create_account(
            session, username="override_only", password="secret456"
        ).ok
    with session_scope() as session:
        assert login_account(session, username="default_only", password="secret123").ok
        assert not login_account(
            session, username="override_only", password="secret456"
        ).ok
    with session_scope(other) as session:
        assert login_account(session, username="override_only", password="secret456").ok
        assert not login_account(
            session, username="default_only", password="secret123"
        ).ok
    assert get_engine() is get_engine(db)
    assert get_engine() is not get_engine(other)


def test_migration_preserves_wal_records_credentials_and_original(db, tmp_path) -> None:
    source = Path(get_engine(db).url.database)
    with session_scope(db) as session:
        result = create_account(
            session, username="migrated_login", password="saved-password"
        )
        TwinRepository(session).save_twin(
            UserContext(user_id=result.user_id), empty_twin("Migration Student")
        )
    before = database_dump(source)
    destination = tmp_path / "database" / "studentreplica.db"
    assert source.with_name(source.name + "-wal").exists()
    assert migrate_legacy_database(source, destination)
    assert source.is_file()
    assert database_dump(source) == before
    assert database_dump(destination) == before
    assert not migrate_legacy_database(source, destination)
    with session_scope(sqlite_url(destination)) as session:
        restored = login_account(
            session, username="migrated_login", password="saved-password"
        )
        assert restored.ok and restored.user_id == result.user_id


def test_migration_and_backup_never_overwrite_or_merge_existing_databases(
    db, tmp_path
) -> None:
    source = Path(get_engine(db).url.database)
    destination = tmp_path / "already_used.db"
    other = sqlite_url(destination)
    init_db(other)
    with session_scope(other) as session:
        create_account(session, username="keep_existing", password="existing-password")
    before = database_dump(destination)
    assert not migrate_legacy_database(source, destination)
    with pytest.raises(FileExistsError):
        copy_database(source, destination)
    assert database_dump(destination) == before


def test_first_startup_automatically_imports_the_former_default(
    db, tmp_path, monkeypatch
) -> None:
    source = Path(get_engine(db).url.database)
    destination = tmp_path / "database" / "studentreplica.db"
    monkeypatch.setattr("storage.sqlite_files.DEFAULT_DATABASE_PATH", destination)
    monkeypatch.setattr("storage.sqlite_files.LEGACY_DATABASE_PATH", source)
    with session_scope(db) as session:
        created = create_account(
            session, username="previous_account", password="previous-password"
        )
    url = sqlite_url(destination)
    init_db(url)
    with session_scope(url) as session:
        restored = login_account(
            session, username="previous_account", password="previous-password"
        )
        assert restored.ok and restored.user_id == created.user_id
    assert source.is_file()


def test_database_health_and_consistent_backup_do_not_expose_records(db) -> None:
    with session_scope(db) as session:
        create_account(
            session, username="private_health_name", password="never-print-password"
        )
    report = check_database(db)
    assert report["status"] == "ok"
    assert report["integrity_check"] == ["ok"]
    assert report["row_counts"]["accounts"] == 1
    assert report["foreign_key_errors"] == 0
    assert "private_health_name" not in str(report)
    assert "never-print-password" not in str(report)
    backup = backup_database(db)
    assert backup.parent.name == "backups"
    assert database_dump(backup) == database_dump(Path(get_engine(db).url.database))


def test_failed_transaction_rolls_back_registration_and_student_data(db) -> None:
    with pytest.raises(RuntimeError, match="cancel transaction"):
        with session_scope(db) as session:
            result = create_account(
                session, username="must_rollback", password="secret123"
            )
            TwinRepository(session).save_twin(
                UserContext(user_id=result.user_id), empty_twin("Cancelled Student")
            )
            raise RuntimeError("cancel transaction")
    report = check_database(db)
    assert report["row_counts"]["accounts"] == 0
    assert report["row_counts"]["twins"] == 0
    assert report["row_counts"]["twin_snapshots"] == 0


def test_passwords_are_salted_hashes_and_case_insensitive_usernames_are_unique(
    db,
) -> None:
    password = "shared-test-password"
    with session_scope(db) as session:
        first = create_account(
            session, username="  Hash_Student_A  ", password=password
        )
        second = create_account(session, username="hash_student_b", password=password)
        assert first.ok and second.ok
        assert not create_account(
            session, username="HASH_STUDENT_A", password="different"
        ).ok
        hashes = session.execute(select(Account.password_hash, Account.salt)).all()
        assert len(hashes) == 2
        assert hashes[0].salt != hashes[1].salt
        assert hashes[0].password_hash != hashes[1].password_hash
        assert all(
            row.password_hash != password and len(row.password_hash) == 64
            for row in hashes
        )


def test_simultaneous_duplicate_registrations_return_a_friendly_result(db) -> None:
    def register() -> bool:
        with session_scope(db) as session:
            return create_account(
                session, username="same_student", password="secret123"
            ).ok

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: register(), range(2)))
    assert sorted(outcomes) == [False, True]
    assert check_database(db)["row_counts"]["accounts"] == 1


@pytest.mark.parametrize("user_id", ["not-a-uuid", "../other-student", " "])
def test_non_uuid_student_contexts_are_rejected(user_id: str) -> None:
    with pytest.raises(ValueError):
        UserContext(user_id=user_id)
