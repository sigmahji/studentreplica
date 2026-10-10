"""SQLAlchemy models. Every student-owned table includes user_id."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for StudentReplica tables."""


class Account(Base):
    """Login identity mapped 1:1 to an isolated twin user_id."""

    __tablename__ = "accounts"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class TwinRecord(Base):
    """Current twin document for exactly one user."""

    __tablename__ = "twins"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    twin_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class TwinSnapshot(Base):
    """Versioned twin snapshot for progress history."""

    __tablename__ = "twin_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    twin_json: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class ChatMessage(Base):
    """Coach chat message belonging to one user only."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class AiCacheEntry(Base):
    """Cached AI responses; cache_key must already include user_id scope."""

    __tablename__ = "ai_cache"
    __table_args__ = (
        UniqueConstraint("user_id", "cache_key", name="uq_ai_cache_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class GeneratedArtifact(Base):
    """CV / insight / other generated artifacts scoped to one user."""

    __tablename__ = "generated_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
