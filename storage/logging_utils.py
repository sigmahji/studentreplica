"""Safe logging helpers — never log raw personal student content."""

from __future__ import annotations

import logging

_logger = logging.getLogger("student_twin")


def log_event(user_id: str, event_type: str, **meta: object) -> None:
    """Log user_id and event type only; optional non-PII metadata allowed.

    Args:
        user_id: Owning student UUID.
        event_type: Short machine event name (e.g. twin_saved).
        **meta: Must not include names, skills, messages, or document text.
    """
    safe_meta = {k: v for k, v in meta.items() if k not in {"name", "content", "text"}}
    _logger.info("event=%s user_id=%s meta=%s", event_type, user_id, safe_meta)
