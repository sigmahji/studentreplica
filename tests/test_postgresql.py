"""Optional real PostgreSQL tests, confined to a fresh test-owned schema."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.schema import CreateSchema, DropSchema

from ai.client import MockClient
from ai.service import AIService
from storage.auth import create_account, login_account
from storage.connections import normalize_database_url
from storage.context import UserContext
from storage.database import get_engine, init_db, reset_engine, session_scope
from storage.manage import check_database
from storage.models import Base
from storage.pipeline import run_full_pipeline
from storage.repository import TwinRepository


@pytest.fixture()
def postgres_database():
    """Never use production tables: create and clean up only our own random schema."""
    value = os.getenv("TEST_POSTGRES_URL")
    if not value:
        pytest.skip("TEST_POSTGRES_URL is not configured; PostgreSQL integration runs in CI.")
    url = normalize_database_url(value)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_POSTGRES_URL must select a dedicated PostgreSQL test database.")
    schema = "studentreplica_test_" + uuid4().hex
    admin = get_engine(url.render_as_string(hide_password=False))
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        scoped = url.update_query_dict({"options": f"-csearch_path={schema}"})
        target = scoped.render_as_string(hide_password=False)
        init_db(target)
        yield target
    finally:
        try:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        finally:
            admin.dispose()
            reset_engine()


def test_postgresql_full_pipeline_persists_accounts_and_never_mixes_students(
    postgres_database,
) -> None:
    database = postgres_database
    client = MockClient()
    ai = AIService(client=client, offline_mode=True)
    students = []
    with session_scope(database) as session:
        for suffix in ("a", "b"):
            account = create_account(
                session, username=f"synthetic_pg_{suffix}", password=f"synthetic-password-{suffix}"
            )
            assert account.ok
            ctx = UserContext(user_id=account.user_id)
            marker = f"POSTGRES_PRIVATE_STUDENT_{suffix.upper()}_ONLY"
            result = run_full_pipeline(session, ctx, {
                "name": marker, "degree": f"Synthetic Degree {suffix}",
                "verified_skills": [f"SyntheticSkill{suffix}"],
                "core_courses": [f"SyntheticCourse{suffix}"],
            }, ai)
            assert marker in json.dumps(result)
            students.append(ctx)
    reset_engine()
    init_db(database)
    with session_scope(database) as session:
        repo = TwinRepository(session)
        for index, suffix in enumerate(("a", "b")):
            account = login_account(
                session, username=f"synthetic_pg_{suffix}", password=f"synthetic-password-{suffix}"
            )
            assert account.ok and account.user_id == students[index].user_id
            records = "\n".join(repo.dump_user_strings(students[index]))
            other = "B" if suffix == "a" else "A"
            assert f"POSTGRES_PRIVATE_STUDENT_{other}_ONLY" not in records
            assert f"POSTGRES_PRIVATE_STUDENT_{suffix.upper()}_ONLY" in records
        security = session.execute(text(
            "SELECT relname, relrowsecurity FROM pg_class "
            "JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace "
            "WHERE nspname = current_schema() AND relkind = 'r'"
        )).all()
        assert {row.relname for row in security} == set(Base.metadata.tables)
        assert all(row.relrowsecurity for row in security)
    for prompt in client.prompts_for(students[1].user_id):
        assert "POSTGRES_PRIVATE_STUDENT_A_ONLY" not in json.dumps(prompt)
    report = check_database(database)
    assert report["status"] == "ok"
    assert report["row_counts"]["accounts"] == 2
    assert "synthetic-password" not in str(report)
    assert "POSTGRES_PRIVATE_STUDENT" not in str(report)
