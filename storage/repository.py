"""Repository layer: every query is filtered by user_id from UserContext."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.context import UserContext
from storage.logging_utils import log_event
from storage.models import (
    AiCacheEntry,
    ChatMessage,
    GeneratedArtifact,
    TwinRecord,
    TwinSnapshot,
)
from storage.twin_schema import clone_twin, empty_twin


class TwinRepository:
    """User-scoped persistence for twins, chat, cache, and artifacts.

    No method accepts raw user data without an explicit ``UserContext``.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _require_user_cache_key(self, ctx: UserContext, cache_key: str) -> None:
        """Ensure cache keys cannot be reused across user scopes."""
        expected_prefix = f"{ctx.user_id}:"
        if not cache_key.startswith(expected_prefix):
            raise ValueError("AI cache keys must start with '<user_id>:'")

    # ------------------------------------------------------------------ twin
    def get_twin(self, ctx: UserContext) -> dict[str, Any] | None:
        """Load the current twin for ``ctx.user_id``, or None if missing."""
        row = self._session.get(TwinRecord, ctx.user_id)
        if row is None:
            return None
        return clone_twin(json.loads(row.twin_json))

    def get_or_create_twin(self, ctx: UserContext) -> dict[str, Any]:
        """Return the twin, creating an empty document if needed."""
        twin = self.get_twin(ctx)
        if twin is not None:
            return twin
        twin = empty_twin()
        self.save_twin(ctx, twin, label="initial")
        return twin

    def save_twin(
        self,
        ctx: UserContext,
        twin: dict[str, Any],
        *,
        label: str | None = None,
        snapshot: bool = True,
    ) -> dict[str, Any]:
        """Persist twin for this user only; optionally write a version snapshot."""
        existing = self._session.get(TwinRecord, ctx.user_id)
        now = datetime.now(timezone.utc)
        if existing is None:
            version = 1
            twin = clone_twin(twin)
            twin.setdefault("meta", {})
            twin["meta"]["twin_version"] = version
            twin["meta"]["updated_at"] = now.isoformat()
            self._session.add(
                TwinRecord(
                    user_id=ctx.user_id,
                    twin_json=json.dumps(twin),
                    version=version,
                    updated_at=now,
                )
            )
        else:
            version = int(existing.version) + 1
            twin = clone_twin(twin)
            twin.setdefault("meta", {})
            twin["meta"]["twin_version"] = version
            twin["meta"]["updated_at"] = now.isoformat()
            existing.twin_json = json.dumps(twin)
            existing.version = version
            existing.updated_at = now

        if snapshot:
            self._session.add(
                TwinSnapshot(
                    user_id=ctx.user_id,
                    version=version,
                    twin_json=json.dumps(twin),
                    label=label,
                    created_at=now,
                )
            )

        self._session.flush()
        log_event(ctx.user_id, "twin_saved", version=version)
        return twin

    def list_snapshots(self, ctx: UserContext) -> list[dict[str, Any]]:
        """List twin snapshots for this user only (newest first)."""
        stmt = (
            select(TwinSnapshot)
            .where(TwinSnapshot.user_id == ctx.user_id)
            .order_by(TwinSnapshot.version.desc())
        )
        rows = self._session.scalars(stmt).all()
        return [
            {
                "version": row.version,
                "label": row.label,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "twin": json.loads(row.twin_json),
            }
            for row in rows
        ]

    def get_twin_version(self, ctx: UserContext) -> int:
        """Return the current twin version number (0 if none)."""
        row = self._session.get(TwinRecord, ctx.user_id)
        return int(row.version) if row else 0

    # ------------------------------------------------------------------ chat
    def add_chat_message(self, ctx: UserContext, role: str, content: str) -> None:
        """Append a chat message for this user only."""
        self._session.add(
            ChatMessage(
                user_id=ctx.user_id,
                role=role,
                content=content,
                created_at=datetime.now(timezone.utc),
            )
        )
        self._session.flush()
        log_event(ctx.user_id, "chat_message_added", role=role)

    def get_chat_history(
        self, ctx: UserContext, *, limit: int = 12
    ) -> list[dict[str, str]]:
        """Load the latest chat messages for this user only."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.user_id == ctx.user_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        rows = list(reversed(self._session.scalars(stmt).all()))
        return [{"role": r.role, "content": r.content} for r in rows]

    def clear_chat_history(self, ctx: UserContext) -> None:
        """Delete chat history for this user only."""
        stmt = select(ChatMessage).where(ChatMessage.user_id == ctx.user_id)
        for row in self._session.scalars(stmt).all():
            self._session.delete(row)
        self._session.flush()
        log_event(ctx.user_id, "chat_cleared")

    # ------------------------------------------------------------------ cache
    def get_ai_cache(self, ctx: UserContext, cache_key: str) -> dict[str, Any] | None:
        """Fetch a cached AI response; key must be unique per user."""
        self._require_user_cache_key(ctx, cache_key)
        stmt = select(AiCacheEntry).where(
            AiCacheEntry.user_id == ctx.user_id,
            AiCacheEntry.cache_key == cache_key,
        )
        row = self._session.scalars(stmt).first()
        if row is None:
            return None
        return json.loads(row.response_json)

    def set_ai_cache(
        self, ctx: UserContext, cache_key: str, response: dict[str, Any]
    ) -> None:
        """Store an AI response under (user_id, cache_key)."""
        self._require_user_cache_key(ctx, cache_key)
        stmt = select(AiCacheEntry).where(
            AiCacheEntry.user_id == ctx.user_id,
            AiCacheEntry.cache_key == cache_key,
        )
        row = self._session.scalars(stmt).first()
        payload = json.dumps(response)
        if row is None:
            self._session.add(
                AiCacheEntry(
                    user_id=ctx.user_id,
                    cache_key=cache_key,
                    response_json=payload,
                    created_at=datetime.now(timezone.utc),
                )
            )
        else:
            row.response_json = payload
        self._session.flush()
        log_event(ctx.user_id, "ai_cache_set")

    def list_ai_cache_keys(self, ctx: UserContext) -> list[str]:
        """Return cache keys for this user (for isolation tests)."""
        stmt = select(AiCacheEntry.cache_key).where(AiCacheEntry.user_id == ctx.user_id)
        return list(self._session.scalars(stmt).all())

    def list_ai_cache_payloads(self, ctx: UserContext) -> list[dict[str, Any]]:
        """Return all cached payloads for this user (for isolation tests)."""
        stmt = select(AiCacheEntry).where(AiCacheEntry.user_id == ctx.user_id)
        return [json.loads(r.response_json) for r in self._session.scalars(stmt).all()]

    # -------------------------------------------------------------- artifacts
    def save_artifact(
        self,
        ctx: UserContext,
        kind: str,
        payload: dict[str, Any],
        *,
        prompt_text: str | None = None,
    ) -> int:
        """Persist a generated artifact for this user only."""
        row = GeneratedArtifact(
            user_id=ctx.user_id,
            kind=kind,
            payload_json=json.dumps(payload),
            prompt_text=prompt_text,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        self._session.flush()
        log_event(ctx.user_id, "artifact_saved", kind=kind)
        return int(row.id)

    def list_artifacts(
        self, ctx: UserContext, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """List artifacts for this user, optionally filtered by kind."""
        stmt = select(GeneratedArtifact).where(GeneratedArtifact.user_id == ctx.user_id)
        if kind is not None:
            stmt = stmt.where(GeneratedArtifact.kind == kind)
        stmt = stmt.order_by(GeneratedArtifact.id.desc())
        results: list[dict[str, Any]] = []
        for row in self._session.scalars(stmt).all():
            results.append(
                {
                    "id": row.id,
                    "kind": row.kind,
                    "payload": json.loads(row.payload_json),
                    "prompt_text": row.prompt_text,
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                }
            )
        return results

    def dump_user_strings(self, ctx: UserContext) -> list[str]:
        """Collect all stored string blobs for this user (isolation tests)."""
        blobs: list[str] = []
        twin = self.get_twin(ctx)
        if twin:
            blobs.append(json.dumps(twin))
        for snap in self.list_snapshots(ctx):
            blobs.append(json.dumps(snap))
        for msg in self.get_chat_history(ctx, limit=10_000):
            blobs.append(msg["content"])
        for payload in self.list_ai_cache_payloads(ctx):
            blobs.append(json.dumps(payload))
        for art in self.list_artifacts(ctx):
            blobs.append(json.dumps(art["payload"]))
            if art.get("prompt_text"):
                blobs.append(str(art["prompt_text"]))
        return blobs

    def delete_artifacts(self, ctx: UserContext, *, kind: str) -> None:
        """Remove only this user's artifacts of the selected kind (e.g. a photo)."""
        from sqlalchemy import delete

        self._session.execute(
            delete(GeneratedArtifact).where(
                GeneratedArtifact.user_id == ctx.user_id, GeneratedArtifact.kind == kind
            )
        )
        self._session.flush()
        log_event(ctx.user_id, "artifacts_deleted", kind=kind)
