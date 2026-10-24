"""Cryptographically signed session tokens for persistent device logins."""

from __future__ import annotations

import hashlib
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import DATABASE_URL


def _get_signing_secret() -> str:
    """Derive a stable server-side signing secret from environment or database config."""
    raw = (
        os.getenv("SESSION_SECRET")
        or os.getenv("POSTGRES_APP_PASSWORD")
        or os.getenv("POSTGRES_PASSWORD")
        or DATABASE_URL
        or "studentreplica-session-signing-key"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_session_token(user_id: str) -> str:
    """Generate a tamper-proof timestamped token for 30-day persistent logins."""
    serializer = URLSafeTimedSerializer(_get_signing_secret(), salt="studentreplica-session")
    return serializer.dumps({"user_id": str(user_id)})


def validate_session_token(token: str, max_age: int = 30 * 86400) -> str | None:
    """Verify cryptographic signature and expiration; return user_id on success."""
    if not token or not isinstance(token, str):
        return None
    serializer = URLSafeTimedSerializer(_get_signing_secret(), salt="studentreplica-session")
    try:
        data = serializer.loads(token.strip(), max_age=max_age)
        if isinstance(data, dict) and "user_id" in data:
            return str(data["user_id"])
    except (BadSignature, SignatureExpired, Exception):
        return None
    return None
