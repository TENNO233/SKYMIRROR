"""Helpers for optional LangSmith tracing."""

from __future__ import annotations

import logging
import os
from typing import Any

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


def get_current_run_trace_info() -> dict[str, Any]:
    """Return the current LangSmith run identifiers and UI URL when available."""
    if not langsmith_tracing_enabled():
        return {}

    try:
        from langsmith.run_helpers import get_current_run_tree

        run_tree = get_current_run_tree()
        if run_tree is None:
            return {}

        trace_url = run_tree.get_url()
        payload = {
            "trace_url": str(trace_url).strip(),
            "run_id": str(run_tree.id),
            "trace_id": str(run_tree.trace_id),
            "project_name": str(getattr(run_tree, "session_name", "")).strip(),
        }
        return {
            key: value
            for key, value in payload.items()
            if isinstance(value, str) and value.strip()
        }
    except Exception as exc:
        logger.warning("LangSmith trace URL lookup failed: %s", exc)
        return {}
