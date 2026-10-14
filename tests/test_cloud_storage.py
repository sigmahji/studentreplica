"""Hosted storage configuration, privacy, startup and connection protections."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import DDL
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from storage.connections import connection_options, normalize_database_url
from storage.database import get_engine, init_db, reset_engine
from storage.models import Account, Base


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_postgres_urls_use_psycopg_and_tls_without_losing_passwords(scheme) -> None:
    url = normalize_database_url(f"{scheme}://student:p%40ss@db.example.com/students")
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss"
    assert url.query["sslmode"] == "require"


def test_explicit_tls_settings_are_preserved_and_local_postgres_is_supported() -> None:
    url = normalize_database_url(
        "postgresql://student:synthetic@db.example.com/students?sslmode=verify-full"
    )
    assert url.query["sslmode"] == "verify-full"
    local = normalize_database_url("postgresql://student@127.0.0.1/students")
    assert "sslmode" not in local.query


def test_pooling_and_error_parameters_are_safe_for_hosted_postgres() -> None:
    options = connection_options(normalize_database_url("postgresql://localhost/students"))
    assert options["hide_parameters"] is True
    assert options["pool_pre_ping"] is True
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 5
    assert options["pool_recycle"] == 300
    assert options["connect_args"] == {"connect_timeout": 10, "prepare_threshold": None}
    sqlite = connection_options(normalize_database_url("sqlite:///:memory:"))
    assert sqlite["poolclass"] is StaticPool
    assert sqlite["connect_args"]["check_same_thread"] is False


def test_invalid_connection_url_does_not_echo_the_credential() -> None:
    with pytest.raises(ValueError) as result:
        normalize_database_url("INVALID_PRIVATE_DATABASE_PASSWORD")
    assert "INVALID_PRIVATE_DATABASE_PASSWORD" not in str(result.value)


def test_postgres_driver_loads_without_contacting_a_database() -> None:
    engine = get_engine("postgres://synthetic:synthetic@127.0.0.1:1/test_only")
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    assert engine.hide_parameters is True


def test_initialization_runs_once_per_engine_and_resets_cleanly(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{(tmp_path / 'initialized_once.db').as_posix()}"
    original = Base.metadata.create_all
    calls = []

    def create(**kwargs):
        calls.append(True)
        return original(**kwargs)

    monkeypatch.setattr(Base.metadata, "create_all", create)
    init_db(url)
    init_db(url)
    assert len(calls) == 1
    reset_engine()
    init_db(url)
    assert len(calls) == 2


def test_database_errors_do_not_expose_student_parameters(db, ctx_a, ctx_b) -> None:
    engine = get_engine(db)
    private = "PRIVATE_STUDENT_USERNAME_NO_LOGGING"
    with engine.begin() as connection:
        connection.execute(Account.__table__.insert(), {
            "user_id": ctx_a.user_id, "username": private,
            "password_hash": "synthetic-hash", "salt": "synthetic-salt",
            "display_name": "Synthetic Student",
        })
    with pytest.raises(IntegrityError) as error:
        with engine.begin() as connection:
            connection.execute(Account.__table__.insert(), {
                "user_id": ctx_b.user_id, "username": private,
                "password_hash": "synthetic-hash", "salt": "synthetic-salt",
                "display_name": "Synthetic Student",
            })
    assert private not in str(error.value)


def test_row_security_ddl_quotes_metadata_identifiers() -> None:
    for table in Base.metadata.sorted_tables:
        sql = str(DDL("ALTER TABLE %(fullname)s ENABLE ROW LEVEL SECURITY").against(
            table
        ).compile(dialect=postgresql.dialect()))
        assert table.name in sql
        assert sql.endswith(" ENABLE ROW LEVEL SECURITY")


def test_startup_failure_is_private_and_retry_does_not_change_backends(
    db, monkeypatch, caplog,
) -> None:
    attempts = []

    def initialize():
        attempts.append(True)
        if len(attempts) == 1:
            raise OperationalError("PRIVATE_SQL", {}, RuntimeError("PRIVATE_DATABASE_PASSWORD"))
        return init_db(db)

    monkeypatch.setattr("storage.database.init_db", initialize)
    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.session_state["ai_force_mock"] = True
    app.run()
    assert not app.exception
    assert any("Storage is unavailable" in item.value for item in app.error)
    assert not any(item.label == "Continue" for item in app.button)
    assert "PRIVATE_DATABASE_PASSWORD" not in caplog.text
    assert "PRIVATE_SQL" not in caplog.text
    next(item for item in app.button if item.label == "Retry database").click().run()
    assert not app.exception
    assert len(attempts) == 2
    assert any(item.label == "Continue" for item in app.button)


def test_compose_keeps_administrator_credentials_out_of_the_app() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    app = compose["services"]["app"]
    database = compose["services"]["database"]
    assert "env_file" not in app
    assert "POSTGRES_PASSWORD" not in app["environment"]
    assert "POSTGRES_APP_PASSWORD" in app["environment"]["PGPASSWORD"]
    assert "studentreplica_app@database" in app["environment"]["DATABASE_URL"]
    assert database["environment"]["POSTGRES_USER"] == "postgres"
    assert any("postgres_data:" in volume for volume in database["volumes"])
    assert any("init-postgres.sql:" in volume for volume in database["volumes"])
    assert app["ports"] == ["127.0.0.1:8502:8501"]


def test_database_initialization_script_does_not_embed_passwords() -> None:
    root = Path(__file__).resolve().parents[1]
    sql = (root / "database/init-postgres.sql").read_text(encoding="utf-8")
    assert "\\getenv application_password POSTGRES_APP_PASSWORD" in sql
    assert "NOSUPERUSER" in sql and "NOBYPASSRLS" in sql
    assert "PASSWORD :'application_password'" in sql


def test_backend_ci_runs_real_postgres_isolation_tests() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load(
        (root / ".github/workflows/backend-tests.yml").read_text(encoding="utf-8")
    )
    assert set(workflow["on"]) == {"push", "pull_request"}
    job = workflow["jobs"]["storage"]
    assert job["env"]["AI_PROVIDER"] == "mock"
    assert job["env"]["TEST_POSTGRES_URL"].startswith("postgresql+psycopg://")
    assert job["services"]["postgres"]["image"] == "postgres:17-bookworm"
    assert any(step.get("run") == "python -m pytest -q" for step in job["steps"])
