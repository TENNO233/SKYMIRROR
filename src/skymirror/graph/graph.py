"""
graph.py — LangGraph Pipeline Definition for SKYMIRROR
Builds the runnable LangGraph application.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from skymirror.agents.alert_manager import alert_manager_node
from skymirror.agents.experts import (
    environment_expert_node,
    order_expert_node,
    safety_expert_node,
)
from skymirror.agents.validator import validator_agent_node
from skymirror.agents.vlm_agent import (
    gemini_vlm_node,
    image_guardrail_node,
    qwen_vlm_node,
)
from skymirror.graph.edges import route_after_guardrail, route_to_experts
from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)


def _build_graph() -> StateGraph:
    """Construct and return a StateGraph for the SKYMIRROR pipeline."""
    graph = StateGraph(SkymirrorState)

    graph.add_node("image_guardrail", image_guardrail_node)
    graph.add_node("gemini_vlm", gemini_vlm_node)
    graph.add_node("qwen_vlm", qwen_vlm_node)
    graph.add_node("validator_agent", validator_agent_node)
    graph.add_node("order_expert", order_expert_node)
    graph.add_node("safety_expert", safety_expert_node)
    graph.add_node("environment_expert", environment_expert_node)
    graph.add_node("alert_manager", alert_manager_node)

    graph.add_edge(START, "image_guardrail")
    graph.add_conditional_edges(
        source="image_guardrail",
        path=route_after_guardrail,
        path_map={"end_pipeline": END},
    )

    graph.add_edge("gemini_vlm", "validator_agent")
    graph.add_edge("qwen_vlm", "validator_agent")

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