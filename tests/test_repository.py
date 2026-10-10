"""Unit tests for UserContext and TwinRepository basics."""

from __future__ import annotations

import pytest

from storage.context import UserContext, new_user_context
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def test_user_context_requires_user_id() -> None:
    with pytest.raises(ValueError):
        UserContext(user_id="")


def test_new_user_context_unique() -> None:
    a = new_user_context()
    b = new_user_context()
    assert a.user_id != b.user_id


def test_save_and_snapshot(open_session, ctx_a: UserContext) -> None:
    with open_session() as session:
        repo = TwinRepository(session)
        twin = empty_twin(name="Test Student")
        twin["skills"] = [
            {"name": "Python", "proficiency": 80, "evidence": "course", "last_updated": ""}
        ]
        saved = repo.save_twin(ctx_a, twin, label="v1")
        assert saved["meta"]["twin_version"] == 1
        saved2 = repo.save_twin(ctx_a, saved, label="v2")
        assert saved2["meta"]["twin_version"] == 2
        snaps = repo.list_snapshots(ctx_a)
        assert len(snaps) == 2
        assert snaps[0]["version"] == 2


def test_ai_cache_scoped(open_session, ctx_a: UserContext, ctx_b: UserContext) -> None:
    with open_session() as session:
        repo = TwinRepository(session)
        key = f"{ctx_a.user_id}:insight:v1:abc"
        repo.set_ai_cache(ctx_a, key, {"hello": "a"})
        assert repo.get_ai_cache(ctx_a, key) == {"hello": "a"}
        with pytest.raises(ValueError):
            repo.get_ai_cache(ctx_b, key)
        with pytest.raises(ValueError):
            repo.set_ai_cache(ctx_b, key, {"hello": "b"})


def test_ai_cache_key_must_include_user_id(open_session, ctx_a: UserContext) -> None:
    with open_session() as session:
        repo = TwinRepository(session)
        with pytest.raises(ValueError):
            repo.set_ai_cache(ctx_a, "insight:v1:abc", {"hello": "a"})
