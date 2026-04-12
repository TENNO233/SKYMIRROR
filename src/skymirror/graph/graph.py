"""
graph.py — LangGraph Pipeline Definition for SKYMIRROR
========================================================
Assembles the full directed graph and compiles it into a runnable `app`.

Pipeline topology
-----------------

    START
      │
      ▼
  vlm_agent          ← converts camera frame → raw text
      │
      ▼
  validator_agent    ← cleans / validates vlm_text → validated_text
      │
      ▼  (conditional — route_to_experts)
      ├──► order_expert        ┐
      ├──► safety_expert       ├─► alert_manager → END
      ├──► environment_expert  ┘
      │
      └──► alert_manager       (fallback: no keywords matched)


Fan-out / Fan-in
----------------
When multiple experts are activated the Send API dispatches them in parallel.
Each expert writes its findings into `state["expert_results"]` under its own
key.  The `_merge_dicts` reducer on `expert_results` (defined in state.py)
merges all partial dicts before `alert_manager` runs.

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
from typing import Any

from langgraph.graph import END, START, StateGraph

from skymirror.agents.prompts import (
    VLM_SYSTEM_PROMPT,
    VALIDATOR_SYSTEM_PROMPT,
    ORDER_EXPERT_PROMPT,
)
from skymirror.graph.edges import route_to_experts
from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Placeholder / Dummy Node Functions
# ---------------------------------------------------------------------------
# These are *structural stubs* — they pass state through unchanged so the
# graph topology can be built, tested, and visualised before each agent's
# internal logic is implemented.
#
# Replace each function body with the real import once implemented:
#
#   from skymirror.agents import vlm_agent_node
#   graph.add_node("vlm_agent", vlm_agent_node)
# ---------------------------------------------------------------------------

def _stub_vlm_agent(state: SkymirrorState) -> dict[str, Any]:
    """
    VLM Agent stub.
    Real implementation: call a vision-language model (e.g. GPT-4o, Claude 3)
    with `state["image_path"]` and return `{"vlm_text": "<description>"}`.
    """
    messages = [
        {"role": "system", "content": VLM_SYSTEM_PROMPT},
        {"role": "user", "content": f"Image path: {state.get('image_path')}"},
    ]
    logger.debug("vlm_agent stub — image_path=%s | messages=%s", state.get("image_path"), messages)
    print(f"[DEBUG] vlm_agent loaded prompt: {VLM_SYSTEM_PROMPT[:50]}...")
    return {"vlm_text": "[stub] VLM description not yet implemented."}


def _stub_validator_agent(state: SkymirrorState) -> dict[str, Any]:
    """
    Validator Agent stub.
    Real implementation: use an LLM to clean, structure, and fact-check
    `state["vlm_text"]`, returning `{"validated_text": "<refined>"}`.
    """
    messages = [
        {"role": "system", "content": VALIDATOR_SYSTEM_PROMPT},
        {"role": "user", "content": state.get("vlm_text", "")},
    ]
    logger.debug("validator_agent stub — vlm_text=%s | messages=%s", state.get("vlm_text"), messages)
    print(f"[DEBUG] validator_agent loaded prompt: {VALIDATOR_SYSTEM_PROMPT[:50]}...")
    return {"validated_text": state.get("vlm_text", "")}


def _stub_order_expert(state: SkymirrorState) -> dict[str, Any]:
    """
    Order Expert stub.
    Real implementation: RAG retrieval from Pinecone (traffic-regulation corpus)
    + LLM reasoning → return `{"expert_results": {"order_expert": {...}}}`.
    """
    messages = [
        {"role": "system", "content": ORDER_EXPERT_PROMPT},
        {"role": "user", "content": state.get("validated_text", "")},
    ]
    logger.debug("order_expert stub | messages=%s", messages)
    print(f"[DEBUG] order_expert loaded prompt: {ORDER_EXPERT_PROMPT[:50]}...")
    return {
        "expert_results": {
            "order_expert": {
                "findings": [],
                "severity": "unknown",
                "stub": True,
            }
        }
    }


def _stub_safety_expert(state: SkymirrorState) -> dict[str, Any]:
    """
    Safety Expert stub.
    Real implementation: RAG retrieval from Pinecone (safety-incident corpus)
    + LLM reasoning → return `{"expert_results": {"safety_expert": {...}}}`.
    """
    logger.debug("safety_expert stub")
    return {
        "expert_results": {
            "safety_expert": {
                "findings": [],
                "severity": "unknown",
                "stub": True,
            }
        }
    }


def _stub_environment_expert(state: SkymirrorState) -> dict[str, Any]:
    """
    Environment Expert stub.
    Real implementation: RAG retrieval from Pinecone (weather/road-condition corpus)
    + LLM reasoning → return `{"expert_results": {"environment_expert": {...}}}`.
    """
    logger.debug("environment_expert stub")
    return {
        "expert_results": {
            "environment_expert": {
                "findings": [],
                "severity": "unknown",
                "stub": True,
            }
        }
    }


def _stub_alert_manager(state: SkymirrorState) -> dict[str, Any]:
    """
    Alert Manager stub.
    Real implementation: iterate `state["expert_results"]`, synthesise alerts,
    and optionally dispatch them via webhook / message queue.
    Returns `{"alerts": [<alert_dict>, ...]}`.
    """
    logger.debug(
        "alert_manager stub — expert_results keys=%s",
        list(state.get("expert_results", {}).keys()),
    )
    return {"alerts": []}


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    """
    Construct and return a compiled StateGraph for the SKYMIRROR pipeline.

    Separated into its own function so tests can call `_build_graph()` to get
    a fresh graph instance without running the module-level compilation side
    effect more than once.
    """
    graph = StateGraph(SkymirrorState)

    # --- Register nodes ------------------------------------------------------
    graph.add_node("vlm_agent", _stub_vlm_agent)
    graph.add_node("validator_agent", _stub_validator_agent)
    graph.add_node("order_expert", _stub_order_expert)
    graph.add_node("safety_expert", _stub_safety_expert)
    graph.add_node("environment_expert", _stub_environment_expert)
    graph.add_node("alert_manager", _stub_alert_manager)

    # --- Linear edges (deterministic) ----------------------------------------
    graph.add_edge(START, "vlm_agent")
    graph.add_edge("vlm_agent", "validator_agent")

    # --- Conditional edge (orchestrator) -------------------------------------
    # `route_to_experts` returns either:
    #   • list[Send]  → fan-out to N expert nodes in parallel
    #   • "alert_manager"  → skip experts, go straight to alerting
    graph.add_conditional_edges(
        source="validator_agent",
        path=route_to_experts,
        # path_map tells LangGraph which *string* returns map to which nodes.
        # Send-based returns are resolved automatically and don't need entries.
        path_map={"alert_manager": "alert_manager"},
    )

    # --- Fan-in: experts → alert_manager -------------------------------------
    # All three expert nodes converge on alert_manager.
    # LangGraph waits for ALL activated Send branches to complete before
    # alert_manager runs (automatic synchronisation barrier).
    graph.add_edge("order_expert", "alert_manager")
    graph.add_edge("safety_expert", "alert_manager")
    graph.add_edge("environment_expert", "alert_manager")

    # --- Terminal edge -------------------------------------------------------
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

logger.info("SKYMIRROR LangGraph pipeline compiled successfully.")
