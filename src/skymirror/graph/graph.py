"""
graph.py — LangGraph Pipeline Definition for SKYMIRROR
Builds the runnable LangGraph application.

Pipeline topology
-----------------

    START
      │
      ▼
  image_guardrail ──(blocked)──► END
      │ (allowed)
      ├──► gemini_vlm ──┐
      └──► qwen_vlm   ──┤
                        ▼
                  validator_agent
                        │
                        ▼
                 orchestrator_agent  ◄─────────────────────┐
                        │                                   │
              [route_from_orchestrator]                     │
                        │                                   │
           ┌────────────┼────────────┐                      │
           ▼            ▼            ▼                      │
     order_expert  safety_expert  environment_expert ───────┘
                                                    (fan-in back to orchestrator)

  orchestrator_agent (pass 2 — evaluate mode)
           │
    [route_from_orchestrator]
           │
     ┌─────┴──────┐
     ▼            ▼
  alert_manager  END
     │
     ▼
    END

Supervisor pattern
------------------
The orchestrator runs TWICE per frame:

  Pass 1 (dispatch):  expert_results is empty → LLM picks relevant experts →
                      route_from_orchestrator fans out via Send API.

  Pass 2 (evaluate):  expert_results populated → LLM evaluates findings →
                      routes to alert_manager or END directly.

Usage
-----
    from skymirror.graph import app

    result = app.invoke({"image_path": "/data/frames/cam01_20240412_093000.jpg"})
    print(result["alerts"])

    # Async streaming (recommended for production):
    async for event in app.astream(initial_state, stream_mode="updates"):
        print(event)
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from skymirror.agents.alert_manager import alert_manager_node
from skymirror.agents.experts import (
    environment_expert_node,
    order_expert_node,
    safety_expert_node,
)
from skymirror.agents.orchestrator import orchestrator_node
from skymirror.agents.validator import validator_agent_node
from skymirror.agents.vlm_agent import (
    gemini_vlm_node,
    image_guardrail_node,
    qwen_vlm_node,
)
from skymirror.graph.edges import route_after_guardrail, route_from_orchestrator
from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)


def _build_graph() -> StateGraph:
    """Construct and return a StateGraph for the SKYMIRROR supervisor pipeline."""
    graph = StateGraph(SkymirrorState)

    # --- Register nodes ------------------------------------------------------
    graph.add_node("image_guardrail", image_guardrail_node)
    graph.add_node("gemini_vlm", gemini_vlm_node)
    graph.add_node("qwen_vlm", qwen_vlm_node)
    graph.add_node("validator_agent", validator_agent_node)
    graph.add_node("orchestrator_agent", orchestrator_node)
    graph.add_node("order_expert", order_expert_node)
    graph.add_node("safety_expert", safety_expert_node)
    graph.add_node("environment_expert", environment_expert_node)
    graph.add_node("alert_manager", alert_manager_node)

    # --- Guardrail gate -------------------------------------------------------
    # Safe frames fan out to both VLMs in parallel; blocked frames go to END.
    graph.add_edge(START, "image_guardrail")
    graph.add_conditional_edges(
        source="image_guardrail",
        path=route_after_guardrail,
        path_map={"end_pipeline": END},
    )

    # --- Dual-VLM fan-in → validator -----------------------------------------
    graph.add_edge("gemini_vlm", "validator_agent")
    graph.add_edge("qwen_vlm", "validator_agent")

    # --- Validator → Orchestrator (fixed) ------------------------------------
    graph.add_edge("validator_agent", "orchestrator_agent")

    # --- Orchestrator → experts or terminal (conditional) --------------------
    # route_from_orchestrator returns:
    #   list[Send]      → parallel expert dispatch      (pass 1)
    #   "alert_manager" → alert synthesis node          (pass 2, anomaly found)
    #   END             → clean exit, no alert needed   (pass 2, no anomaly)
    graph.add_conditional_edges(
        source="orchestrator_agent",
        path=route_from_orchestrator,
        path_map={"alert_manager": "alert_manager"},
    )

    # --- Experts loop back to orchestrator (supervisor cycle) ----------------
    graph.add_edge("order_expert", "orchestrator_agent")
    graph.add_edge("safety_expert", "orchestrator_agent")
    graph.add_edge("environment_expert", "orchestrator_agent")

    # --- Terminal edge --------------------------------------------------------
    graph.add_edge("alert_manager", END)

    return graph


# ---------------------------------------------------------------------------
# Compiled Application (module-level singleton)
# ---------------------------------------------------------------------------

_graph = _build_graph()

#: Compiled LangGraph application.
#: Invoke synchronously:    app.invoke(state)
#: Stream asynchronously:   async for event in app.astream(state): ...
app = _graph.compile()

logger.info("SKYMIRROR LangGraph supervisor pipeline compiled successfully.")
