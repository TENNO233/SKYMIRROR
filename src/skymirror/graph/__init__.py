"""
Graph package exports.

`app` is imported lazily so modules that only need state types do not require
LangGraph to be imported at package-import time.
"""

from __future__ import annotations

from typing import Any

from skymirror.graph.state import SkymirrorState

__all__ = ["app", "SkymirrorState"]


def __getattr__(name: str) -> Any:
    """Lazily expose the compiled LangGraph application."""
    if name == "app":
        from skymirror.graph.graph import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
