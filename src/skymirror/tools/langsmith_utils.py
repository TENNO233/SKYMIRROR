"""Helpers for optional LangSmith tracing."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def langsmith_tracing_enabled() -> bool:
    """Return True when LangSmith tracing is enabled via env vars."""
    for name in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2"):
        value = os.getenv(name, "").strip().lower()
        if value in _TRUTHY_VALUES:
            return True
    return False


def flush_langsmith_traces() -> None:
    """Block until queued LangSmith traces have been sent."""
    if not langsmith_tracing_enabled():
        return

    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers

        wait_for_all_tracers()
    except Exception as exc:
        logger.warning("LangSmith trace flush failed: %s", exc)
