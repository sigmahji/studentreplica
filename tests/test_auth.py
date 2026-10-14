"""Account create/login isolation tests."""

from __future__ import annotations

from uuid import uuid4

from storage.auth import create_account, get_account_by_user_id, login_account
from storage.context import UserContext
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def test_create_and_login(open_session) -> None:
    with open_session() as session:
        created = create_account(
            session, username="alice_student", password="secret12", display_name="Alice"
        )
        assert created.ok and created.user_id
        bad = login_account(session, username="alice_student", password="wrong")
        assert not bad.ok
        good = login_account(session, username="alice_student", password="secret12")
        assert good.ok and good.user_id == created.user_id


def test_duplicate_username_rejected(open_session) -> None:
    with open_session() as session:
        a = create_account(session, username="bob", password="secret12")
        assert a.ok
        b = create_account(session, username="bob", password="secret99")
        assert not b.ok


def test_display_name_limit_is_checked_before_database_insert(open_session) -> None:
    with open_session() as session:
        invalid = create_account(
            session, username="long_display", password="secret12", display_name="a" * 121
        )
        assert not invalid.ok
        assert "120" in invalid.message
        valid = create_account(
            session, username="long_display", password="secret12", display_name="a" * 120
        )
        assert valid.ok
    with open_session() as session:
        account = get_account_by_user_id(session, valid.user_id)
    assert account is not None and len(account.display_name) == 120


def test_account_metadata_usable_after_sign_in_session_closes(open_session) -> None:
    with open_session() as session:
        created = create_account(
            session, username="alice_student", password="secret12", display_name="Alice"
        )
    assert created.ok and created.user_id

    with open_session() as session:
        signed_in = login_account(
            session, username="alice_student", password="secret12"
        )
    assert signed_in.ok and signed_in.user_id

    with open_session() as session:
        account = get_account_by_user_id(session, signed_in.user_id)

    # The sidebar reads these fields only after the lookup session commits/closes.
    assert account is not None
    assert account.user_id == created.user_id
    assert account.username == "alice_student"
    assert account.display_name == "Alice"
    assert not hasattr(account, "password_hash")
    assert not hasattr(account, "salt")


def test_unknown_account_returns_none(open_session) -> None:
    with open_session() as session:
        created = create_account(session, username="alice_student", password="secret12")
    assert created.ok

    with open_session() as session:
        account = get_account_by_user_id(session, str(uuid4()))
    assert account is None


def test_accounts_have_isolated_twins(open_session) -> None:
    with open_session() as session:
        a = create_account(session, username="acc_a", password="secret12")
        b = create_account(session, username="acc_b", password="secret12")
        assert a.user_id != b.user_id
        ctx_a = UserContext(user_id=a.user_id)
        ctx_b = UserContext(user_id=b.user_id)
        repo = TwinRepository(session)
        twin_a = empty_twin("AccountA_ONLY")
        twin_b = empty_twin("AccountB_ONLY")
        repo.save_twin(ctx_a, twin_a)
        repo.save_twin(ctx_b, twin_b)
        assert "AccountA_ONLY" in str(repo.get_twin(ctx_a))
        assert "AccountA_ONLY" not in str(repo.get_twin(ctx_b))
