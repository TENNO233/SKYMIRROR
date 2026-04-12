"""
Graph module.

Public surface:
    - `app`   : compiled LangGraph `CompiledGraph` ready for `.invoke()` / `.astream()`
    - `SkymirrorState` : the shared TypedDict used across all nodes
"""

from skymirror.graph.state import SkymirrorState
from skymirror.graph.graph import app

__all__ = ["app", "SkymirrorState"]
