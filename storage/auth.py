"""Account create/login helpers. Passwords are hashed; never stored in plaintext."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from storage.logging_utils import log_event
from storage.models import Account, ExternalIdentity


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


def _ensure_outer_transaction(session: Session) -> None:
    """Keep SAVEPOINT inserts inside the caller's transaction on legacy sqlite3."""
    connection = session.connection()
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN")


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
    name = (display_name or uname).strip()
    if len(name) > 120:
        return AuthResult(False, None, None, "Display name must be at most 120 characters.")

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
        display_name=name,
        created_at=datetime.now(timezone.utc),
    )
    try:
        _ensure_outer_transaction(session)
        with session.begin_nested():
            session.add(account)
            session.flush()
    except IntegrityError:
        return AuthResult(False, None, None, "Username already taken.")
    log_event(user_id, "account_created")
    return AuthResult(True, user_id, uname, "Account created.")


def _google_subject_hash(claims: Mapping[str, object]) -> str:
    """Check Streamlit-verified Google claims; never accept browser form tokens."""
    subject = claims.get("sub")
    expires = claims.get("exp")
    if (
        claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com")
        or claims.get("email_verified") is not True
        or not isinstance(subject, str)
        or not 1 <= len(subject) <= 255
        or not subject.isascii()
        or subject != subject.strip()
        or not isinstance(expires, (int, float))
        or isinstance(expires, bool)
        or not math.isfinite(expires)
        or expires <= time.time()
    ):
        raise ValueError("Google identity could not be verified. Please sign in again.")
    return hashlib.sha256(subject.encode("ascii")).hexdigest()


def login_google_account(session: Session, claims: Mapping[str, object]) -> AuthResult:
    """Resolve ONLY claims verified by Streamlit OIDC, never email-match accounts.

    Streamlit/Authlib validates token signatures, audience, state and nonce. The
    caller must pass its server-side ``st.user``, not query parameters or uploads.
    No raw subject, email, access token or ID token is persisted here.
    """
    subject_hash = _google_subject_hash(claims)
    lookup = (
        select(Account)
        .join(ExternalIdentity, ExternalIdentity.user_id == Account.user_id)
        .where(
            ExternalIdentity.provider == "google",
            ExternalIdentity.subject_hash == subject_hash,
        )
    )
    account = session.scalars(lookup).first()
    if account is None:
        user_id = str(uuid4())
        supplied_name = claims.get("name")
        name = supplied_name.strip()[:120] if isinstance(supplied_name, str) else ""
        account = Account(
            user_id=user_id,
            username=f"google_{uuid4().hex}",
            # Not a password hash: no password can authenticate a Google-only account.
            password_hash="!google-only",
            salt=secrets.token_hex(16),
            display_name=name or "Student",
        )
        try:
            _ensure_outer_transaction(session)
            with session.begin_nested():
                session.add(account)
                session.flush()
                session.add(ExternalIdentity(
                    provider="google", subject_hash=subject_hash, user_id=user_id,
                ))
                session.flush()
        except IntegrityError:
            # A concurrent first sign-in may have created the same identity.
            account = session.scalars(lookup).first()
            if account is None:
                return AuthResult(
                    False, None, None, "Google sign-in could not finish. Please retry."
                )
        else:
            log_event(user_id, "google_account_created")
    log_event(account.user_id, "google_login_ok")
    return AuthResult(True, account.user_id, account.username, "Signed in with Google.")


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
