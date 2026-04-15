"""
Graph module.

Public surface:
    - `app`   : compiled LangGraph `CompiledGraph` ready for `.invoke()` / `.astream()`
    - `SkymirrorState` : the shared TypedDict used across all nodes
"""

from skymirror.graph.state import SkymirrorState

__all__ = ["app", "SkymirrorState"]


def __getattr__(name: str):
    if name == "app":
        from skymirror.graph.graph import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
