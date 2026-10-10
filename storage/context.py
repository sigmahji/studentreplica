"""Per-request / per-session user identity. Never store student payloads here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True)
class UserContext:
    """Explicit user scope required for every student-data read/write.

    Attributes:
        user_id: Stable UUID string identifying one student twin.
        session_id: Optional UI/session identifier (not a data owner).
        created_at: When this context object was created.
    """

    user_id: str
    session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError("UserContext.user_id is required")
        try:
            normalized = str(UUID(self.user_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("UserContext.user_id must be a valid UUID") from None
        if normalized != self.user_id:
            raise ValueError("UserContext.user_id must use canonical UUID formatting")


def new_user_context(session_id: str | None = None) -> UserContext:
    """Create a fresh context with a new UUID user_id."""
    return UserContext(user_id=str(uuid4()), session_id=session_id)
