"""
graph.py — LangGraph Pipeline Definition for SKYMIRROR
======================================================
Builds the runnable LangGraph application. V1 keeps a stub VLM node, while the
validator, expert agents, and alert manager are real rule-based implementations.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from skymirror.agents import (
    alert_manager_node,
    environment_expert_node,
    order_expert_node,
    safety_expert_node,
    validator_agent_node,
)
from skymirror.agents.prompts import VLM_SYSTEM_PROMPT
from skymirror.graph.edges import route_to_experts
from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)


def _stub_vlm_agent(state: SkymirrorState) -> dict[str, Any]:
    """
    Temporary VLM placeholder.

    Real image understanding is still pending, so V1 downstream development
    keeps using a stub here while the validator and expert stack are live.
    """
    messages = [
        {"role": "system", "content": VLM_SYSTEM_PROMPT},
        {"role": "user", "content": f"Image path: {state.get('image_path')}"},
    ]
    logger.debug("vlm_agent stub — image_path=%s | messages=%s", state.get("image_path"), messages)
    return {"vlm_text": state.get("vlm_text", "[stub] VLM description not yet implemented.")}


def _build_graph() -> StateGraph:
    """
    Construct and return a StateGraph for the SKYMIRROR pipeline.
    """
    graph = StateGraph(SkymirrorState)

    graph.add_node("vlm_agent", _stub_vlm_agent)
    graph.add_node("validator_agent", validator_agent_node)
    graph.add_node("order_expert", order_expert_node)
    graph.add_node("safety_expert", safety_expert_node)
    graph.add_node("environment_expert", environment_expert_node)
    graph.add_node("alert_manager", alert_manager_node)

    graph.add_edge(START, "vlm_agent")
    graph.add_edge("vlm_agent", "validator_agent")

    graph.add_conditional_edges(
        source="validator_agent",
        path=route_to_experts,
        path_map={"alert_manager": "alert_manager"},
    )

    graph.add_edge("order_expert", "alert_manager")
    graph.add_edge("safety_expert", "alert_manager")
    graph.add_edge("environment_expert", "alert_manager")
    graph.add_edge("alert_manager", END)

    return graph


_graph = _build_graph()
app = _graph.compile()

logger.info("SKYMIRROR LangGraph pipeline compiled successfully.")
