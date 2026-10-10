"""Account create/login helpers. Passwords are hashed; never stored in plaintext."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from storage.logging_utils import log_event
from storage.models import Account


@dataclass(frozen=True)
class AuthResult:
    """Outcome of create/login without exposing secrets."""

    ok: bool
    user_id: str | None
    username: str | None
    message: str


@dataclass(frozen=True)
class AccountMetadata:
    """Public account details that remain usable after a session closes."""

    user_id: str
    username: str
    display_name: str


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    )
    return digest.hex()


def create_account(
    session: Session,
    *,
    username: str,
    password: str,
    display_name: str = "",
) -> AuthResult:
    """Register a new isolated student account with a fresh user_id."""
    uname = username.strip().lower()
    if len(uname) < 3:
        return AuthResult(False, None, None, "Username must be at least 3 characters.")
    if len(uname) > 64:
        return AuthResult(False, None, None, "Username must be at most 64 characters.")
    if len(password) < 6:
        return AuthResult(False, None, None, "Password must be at least 6 characters.")

    existing = session.scalars(select(Account).where(Account.username == uname)).first()
    if existing is not None:
        return AuthResult(False, None, None, "Username already taken.")

    user_id = str(uuid4())
    salt = secrets.token_hex(16)
    account = Account(
        user_id=user_id,
        username=uname,
        password_hash=_hash_password(password, salt),
        salt=salt,
        display_name=(display_name or uname).strip(),
        created_at=datetime.now(timezone.utc),
    )
    try:
        connection = session.connection()
        if (
            connection.dialect.name == "sqlite"
            and not connection.connection.driver_connection.in_transaction
        ):
            # sqlite3 legacy mode needs an outer transaction before a SAVEPOINT.
            connection.exec_driver_sql("BEGIN")
        with session.begin_nested():
            session.add(account)
            session.flush()
    except IntegrityError:
        return AuthResult(False, None, None, "Username already taken.")
    log_event(user_id, "account_created")
    return AuthResult(True, user_id, uname, "Account created.")


def login_account(session: Session, *, username: str, password: str) -> AuthResult:
    """Authenticate and return the account's user_id on success."""
    uname = username.strip().lower()
    account = session.scalars(select(Account).where(Account.username == uname)).first()
    if account is None:
        return AuthResult(False, None, None, "Invalid username or password.")

    candidate = _hash_password(password, account.salt)
    if not hmac.compare_digest(candidate, account.password_hash):
        log_event(account.user_id, "login_failed")
        return AuthResult(False, None, None, "Invalid username or password.")

    log_event(account.user_id, "login_ok")
    return AuthResult(True, account.user_id, account.username, "Logged in.")


def get_account_by_user_id(session: Session, user_id: str) -> AccountMetadata | None:
    """Return session-independent account metadata without password fields."""
    account = session.execute(
        select(Account.user_id, Account.username, Account.display_name).where(
            Account.user_id == user_id
        )
    ).one_or_none()
    if account is None:
        return None
    return AccountMetadata(
        user_id=account.user_id,
        username=account.username,
        display_name=account.display_name,
    )
