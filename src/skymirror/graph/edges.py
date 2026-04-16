"""
edges.py — Conditional Routing Logic for SKYMIRROR
==================================================
The router performs coarse expert selection using normalized `validated_text`
plus lightweight `validated_signals`. Fine-grained classification happens
inside each expert node.
"""

from __future__ import annotations

import logging
from typing import Union

from langgraph.types import Send

from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)

ORDER_KEYWORDS: frozenset[str] = frozenset(
    {
        "illegal parking",
        "double parked",
        "lane obstruction",
        "blocked lane",
        "occupying lane",
        "congestion",
        "traffic jam",
        "gridlock",
        "queue",
        "queueing",
        "vehicle loitering",
        "stationary for long",
    }
)

SAFETY_KEYWORDS: frozenset[str] = frozenset(
    {
        "collision",
        "suspected collision",
        "crash",
        "accident",
        "wrong way",
        "against traffic",
        "dangerous crossing",
        "jaywalking",
        "near miss",
        "conflict risk",
        "hard braking",
        "swerving",
    }
)

ENVIRONMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "flooding",
        "standing water",
        "construction",
        "roadwork",
        "obstacle",
        "debris",
        "fallen tree",
        "low visibility",
        "poor visibility",
        "glare",
        "poor lighting",
        "smoke",
        "fog",
    }
)

_EXPERT_ROUTING: list[tuple[frozenset[str], str]] = [
    (ORDER_KEYWORDS, "order_expert"),
    (SAFETY_KEYWORDS, "safety_expert"),
    (ENVIRONMENT_KEYWORDS, "environment_expert"),
]

_EXPERT_SIGNAL_FIELDS: dict[str, tuple[str, ...]] = {
    "order_expert": ("queueing", "blocked_lanes", "stopped_vehicle_count"),
    "safety_expert": (
        "wrong_way_cue",
        "collision_cue",
        "dangerous_crossing_cue",
        "conflict_risk_cue",
    ),
    "environment_expert": (
        "water_present",
        "construction_present",
        "obstacle_present",
        "low_visibility",
        "lighting_abnormal",
    ),
}

_FALLBACK_NODE: str = "alert_manager"


def _signal_activates_expert(expert_node: str, signals: dict[str, object]) -> bool:
    """Check whether structured validator signals are enough to route to an expert."""
    if expert_node == "order_expert":
        return (
            bool(signals.get("queueing"))
            or int(signals.get("blocked_lanes", 0) or 0) > 0
            or int(signals.get("stopped_vehicle_count", 0) or 0) > 0
        )
    return any(bool(signals.get(field)) for field in _EXPERT_SIGNAL_FIELDS[expert_node])


def route_to_experts(
    state: SkymirrorState,
) -> Union[list[Send], str]:
    """
    Resolve which expert nodes should process the current frame.

    Args:
        state: Current pipeline state after validator execution.

    Returns:
        A list of `Send` objects for parallel expert execution or the fallback
        alert manager node when nothing matches.
    """
    validated_text = state.get("validated_text", "")
    validated_signals = state.get("validated_signals", {})

    if not validated_text and not validated_signals:
        logger.warning(
            "route_to_experts: validator output is empty — skipping to %s",
            _FALLBACK_NODE,
        )
        return _FALLBACK_NODE

    text_lower = validated_text.lower()
    active_experts: list[str] = []
    for keywords, expert_node in _EXPERT_ROUTING:
        if any(keyword in text_lower for keyword in keywords) or _signal_activates_expert(
            expert_node,
            validated_signals,
        ):
            active_experts.append(expert_node)

    if not active_experts:
        logger.info(
            "route_to_experts: No expert matches found — routing directly to %s.",
            _FALLBACK_NODE,
        )
        return _FALLBACK_NODE

    logger.info("route_to_experts: Activated experts → %s", active_experts)
    state_with_experts: SkymirrorState = {**state, "active_experts": active_experts}  # type: ignore[misc]
    return [Send(expert, state_with_experts) for expert in active_experts]
