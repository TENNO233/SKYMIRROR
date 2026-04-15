"""
edges.py - Conditional routing logic for SKYMIRROR.
"""

from __future__ import annotations

import logging
from typing import Union

from langgraph.types import Send

from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)

ORDER_KEYWORDS: frozenset[str] = frozenset(
    {
        "wrong way",
        "illegal turn",
        "red light",
        "traffic violation",
        "running light",
        "lane change",
        "overtaking",
        "no entry",
        "congestion",
        "gridlock",
        "queue",
        "blocked intersection",
        "jaywalking",
        "pedestrian violation",
        "double parking",
        "illegal parking",
    }
)

SAFETY_KEYWORDS: frozenset[str] = frozenset(
    {
        "accident",
        "collision",
        "crash",
        "impact",
        "injured",
        "injury",
        "casualty",
        "emergency",
        "ambulance",
        "fire truck",
        "police",
        "overturned",
        "rollover",
        "debris",
        "hazard",
        "danger",
        "speeding",
        "excessive speed",
        "reckless",
        "near miss",
    }
)

ENVIRONMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "smoke",
        "fire",
        "flood",
        "waterlogged",
        "ice",
        "fog",
        "dust",
        "visibility",
        "low visibility",
        "pothole",
        "road damage",
        "oil spill",
        "construction",
        "roadwork",
        "barrier",
        "fallen tree",
        "debris on road",
        "pollution",
    }
)

_EXPERT_ROUTING: list[tuple[frozenset[str], str]] = [
    (ORDER_KEYWORDS, "order_expert"),
    (SAFETY_KEYWORDS, "safety_expert"),
    (ENVIRONMENT_KEYWORDS, "environment_expert"),
]
_FALLBACK_NODE = "alert_manager"
_GUARDRAIL_BLOCKED_NODE = "end_pipeline"


def route_after_guardrail(state: SkymirrorState) -> Union[list[Send], str]:
    """Route safe frames to both VLMs, and fail closed otherwise."""
    guardrail_result = state.get("guardrail_result", {})
    allowed = bool(guardrail_result.get("allowed", False))

    if not allowed:
        logger.info(
            "route_after_guardrail: Blocking frame before VLMs - status=%s reason=%s",
            guardrail_result.get("status", "missing"),
            guardrail_result.get("reason", "missing guardrail result"),
        )
        return _GUARDRAIL_BLOCKED_NODE

    logger.info("route_after_guardrail: Guardrail passed; fan-out to Gemini and Qwen.")
    return [
        Send("gemini_vlm", state),
        Send("qwen_vlm", state),
    ]


def route_to_experts(state: SkymirrorState) -> Union[list[Send], str]:
    """Inspect `validated_text` and route to zero or more expert nodes."""
    validated_text = state.get("validated_text", "")

    if not validated_text:
        logger.warning(
            "route_to_experts: validated_text is empty; routing directly to %s.",
            _FALLBACK_NODE,
        )
        return _FALLBACK_NODE

    text_lower = validated_text.lower()
    active_experts = [
        expert_node
        for keywords, expert_node in _EXPERT_ROUTING
        if any(keyword in text_lower for keyword in keywords)
    ]

    if not active_experts:
        logger.info(
            "route_to_experts: No expert keywords matched; routing to %s.",
            _FALLBACK_NODE,
        )
        return _FALLBACK_NODE

    logger.info("route_to_experts: Activated experts -> %s", active_experts)
    state_with_experts: SkymirrorState = {**state, "active_experts": active_experts}
    return [Send(expert, state_with_experts) for expert in active_experts]
