"""
edges.py — Conditional Routing Logic for SKYMIRROR
====================================================
This module implements the *orchestrator* layer: a pure routing function that
inspects `validated_text` and decides which expert nodes should run next.

Routing strategy
----------------
Keywords found in `validated_text` are matched against three domain-specific
keyword sets.  Matching is case-insensitive.  Multiple experts can be activated
simultaneously; they will run in *parallel* via LangGraph's `Send` API.

Fallback
--------
If no keyword matches are found the frame is considered low-risk and the
pipeline skips directly to `alert_manager` (which may then emit a "no issues"
alert or simply produce an empty alert list).

LangGraph integration
---------------------
`route_to_experts` is registered as the routing function for a
`add_conditional_edges` call in `graph.py`.  It must return either:
  - A `list[Send]`  → fan-out to one or more expert nodes in parallel.
  - A `str`         → go directly to that node (used for the fallback path).
"""

from __future__ import annotations

import logging
from typing import Union

from langgraph.types import Send

from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword Taxonomy
# ---------------------------------------------------------------------------
# Each set covers the vocabulary a VLM is likely to produce for its domain.
# Extend these sets as your VLM vocabulary is refined.

ORDER_KEYWORDS: frozenset[str] = frozenset(
    {
        # Traffic-flow violations
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
        # Accident / hazard vocabulary
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
        # Environmental / road-condition vocabulary
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

# Mapping from keyword-set → expert node name (kept separate for clarity)
_EXPERT_ROUTING: list[tuple[frozenset[str], str]] = [
    (ORDER_KEYWORDS, "order_expert"),
    (SAFETY_KEYWORDS, "safety_expert"),
    (ENVIRONMENT_KEYWORDS, "environment_expert"),
]

# Fallback target when no keywords match
_FALLBACK_NODE: str = "alert_manager"


# ---------------------------------------------------------------------------
# Public Routing Function
# ---------------------------------------------------------------------------

def route_to_experts(
    state: SkymirrorState,
) -> Union[list[Send], str]:
    """
    Conditional edge function: orchestrates which expert nodes run next.

    Called by LangGraph immediately after `validator_agent` completes.

    Algorithm
    ---------
    1. Lower-case `validated_text` once (O(n) string operation).
    2. For each expert domain, check whether *any* keyword is present in the
       text (short-circuits on first match for efficiency).
    3. Build a list of `Send(node_name, state)` objects for all matched experts.
    4. If the list is empty → return the fallback node name as a plain string.

    Args:
        state: Current pipeline state.  `validated_text` must be populated.

    Returns:
        A list of `Send` objects for parallel fan-out to matched expert nodes,
        OR the string `"alert_manager"` when no experts are required.
    """
    validated_text: str = state.get("validated_text", "")  # type: ignore[assignment]

    if not validated_text:
        logger.warning(
            "route_to_experts: `validated_text` is empty — skipping to %s",
            _FALLBACK_NODE,
        )
        return _FALLBACK_NODE

    text_lower = validated_text.lower()

    # Determine which experts to activate
    active_experts: list[str] = [
        expert_node
        for keywords, expert_node in _EXPERT_ROUTING
        if any(kw in text_lower for kw in keywords)
    ]

    if not active_experts:
        logger.info(
            "route_to_experts: No domain keywords matched in validated text — "
            "routing directly to %s (fallback).",
            _FALLBACK_NODE,
        )
        return _FALLBACK_NODE

    logger.info(
        "route_to_experts: Activated experts → %s",
        active_experts,
    )

    # Inject the resolved list into state so nodes can introspect it if needed
    # (LangGraph merges this partial update before calling each Send target)
    state_with_experts: SkymirrorState = {**state, "active_experts": active_experts}  # type: ignore[misc]

    # Fan-out: each Send dispatches one expert node with an independent state copy
    return [Send(expert, state_with_experts) for expert in active_experts]
