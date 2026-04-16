"""
validator.py — Lightweight Validator / Signal Extractor
======================================================
V1 does not call an LLM here. Instead, the validator normalizes the raw VLM
text and extracts lightweight structured hints that downstream expert agents
can combine with rule-based logic.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from skymirror.graph.state import SkymirrorState, ValidatedSignals

logger = logging.getLogger(__name__)

_WORD_TO_INT: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_VEHICLE_TERMS = r"(?:vehicles?|cars?|buses?|trucks?|motorcycles?)"
_LANE_TERMS = r"lanes?"

_QUEUEING_PATTERNS = (
    "queue",
    "queued",
    "queueing",
    "traffic jam",
    "heavy traffic",
    "congestion",
    "gridlock",
    "bumper-to-bumper",
    "slow-moving traffic",
    "standstill traffic",
    "backed up traffic",
)
_WATER_PATTERNS = (
    "flood",
    "flooding",
    "waterlogged",
    "standing water",
    "pooled water",
    "water covering",
)
_CONSTRUCTION_PATTERNS = (
    "construction",
    "roadwork",
    "road work",
    "maintenance",
    "work zone",
    "work crew",
    "traffic cones",
    "barricade",
)
_OBSTACLE_PATTERNS = (
    "obstacle",
    "debris",
    "fallen tree",
    "object on road",
    "barrier",
    "cargo spill",
    "road blocked by object",
)
_LOW_VISIBILITY_PATTERNS = (
    "low visibility",
    "poor visibility",
    "fog",
    "smoke",
    "haze",
    "mist",
)
_LIGHTING_PATTERNS = (
    "glare",
    "backlit",
    "overexposed",
    "underexposed",
    "dark roadway",
    "poor lighting",
    "low light",
    "dim lighting",
)
_WRONG_WAY_PATTERNS = (
    "wrong way",
    "against traffic",
    "opposite direction",
    "wrong direction",
    "oncoming lane",
    "reverse direction",
)
_COLLISION_PATTERNS = (
    "collision",
    "crash",
    "impact",
    "accident",
    "rear-end",
    "rear end",
    "hit another vehicle",
    "vehicle contact",
)
_DANGEROUS_CROSSING_PATTERNS = (
    "jaywalking",
    "pedestrian crossing between vehicles",
    "pedestrian darting across",
    "dangerous crossing",
    "crossing active traffic",
    "pedestrian in roadway",
)
_CONFLICT_PATTERNS = (
    "near miss",
    "close call",
    "hard brake",
    "hard braking",
    "sudden brake",
    "swerving",
    "evasive action",
    "conflict risk",
)
_PEDESTRIAN_PATTERNS = (
    "pedestrian",
    "pedestrians",
    "person crossing",
    "people crossing",
    "person on roadway",
)


def _normalize_text(raw_text: str) -> str:
    """Return lowercase text with compact whitespace."""
    lowered = raw_text.strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    """Check whether any phrase is present in text."""
    return any(pattern in text for pattern in patterns)


def _parse_token_to_int(token: str) -> int | None:
    """Convert digits or basic number words into integers."""
    normalized = token.lower()
    if normalized.isdigit():
        return int(normalized)
    return _WORD_TO_INT.get(normalized)


def _extract_max_count(text: str, patterns: Iterable[str]) -> int:
    """Extract the maximum numeric value matched by the supplied regexes."""
    values: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw_value = match.group("count")
            parsed = _parse_token_to_int(raw_value)
            if parsed is not None:
                values.append(parsed)
    return max(values, default=0)


def _extract_vehicle_count(text: str) -> int:
    """Best-effort extraction of vehicle count from free-form text."""
    patterns = (
        rf"(?P<count>\d+|{'|'.join(_WORD_TO_INT)})\s+{_VEHICLE_TERMS}",
        rf"{_VEHICLE_TERMS}\s+count(?:ed)?\s+at\s+(?P<count>\d+|{'|'.join(_WORD_TO_INT)})",
    )
    return _extract_max_count(text, patterns)


def _extract_stopped_vehicle_count(text: str) -> int:
    """Extract an approximate count of stopped or parked vehicles."""
    patterns = (
        rf"(?P<count>\d+|{'|'.join(_WORD_TO_INT)})\s+(?:stopped|parked|stationary)\s+{_VEHICLE_TERMS}",
        rf"(?:stopped|parked|stationary)\s+{_VEHICLE_TERMS}\s+(?:count\s+)?(?:of\s+)?(?P<count>\d+|{'|'.join(_WORD_TO_INT)})",
    )
    return _extract_max_count(text, patterns)


def _extract_blocked_lanes(text: str) -> int:
    """Extract the number of blocked or occupied lanes, if stated."""
    patterns = (
        rf"(?P<count>\d+|{'|'.join(_WORD_TO_INT)})\s+{_LANE_TERMS}\s+(?:blocked|occupied|closed|obstructed)",
        rf"(?:blocked|occupying|closing|obstructing)\s+(?P<count>\d+|{'|'.join(_WORD_TO_INT)})\s+{_LANE_TERMS}",
    )
    blocked_lanes = _extract_max_count(text, patterns)
    if blocked_lanes:
        return blocked_lanes
    if "multi-lane" in text or "multiple lanes" in text:
        return 2
    if "single lane" in text or "one lane" in text:
        return 1
    return 0


def _build_validated_signals(text: str) -> ValidatedSignals:
    """Extract lightweight structured hints used by downstream experts."""
    signals: ValidatedSignals = {
        "vehicle_count": _extract_vehicle_count(text),
        "stopped_vehicle_count": _extract_stopped_vehicle_count(text),
        "pedestrian_present": _contains_any(text, _PEDESTRIAN_PATTERNS),
        "blocked_lanes": _extract_blocked_lanes(text),
        "queueing": _contains_any(text, _QUEUEING_PATTERNS),
        "water_present": _contains_any(text, _WATER_PATTERNS),
        "construction_present": _contains_any(text, _CONSTRUCTION_PATTERNS),
        "obstacle_present": _contains_any(text, _OBSTACLE_PATTERNS),
        "low_visibility": _contains_any(text, _LOW_VISIBILITY_PATTERNS),
        "lighting_abnormal": _contains_any(text, _LIGHTING_PATTERNS),
        "wrong_way_cue": _contains_any(text, _WRONG_WAY_PATTERNS),
        "collision_cue": _contains_any(text, _COLLISION_PATTERNS),
        "dangerous_crossing_cue": _contains_any(text, _DANGEROUS_CROSSING_PATTERNS),
        "conflict_risk_cue": _contains_any(text, _CONFLICT_PATTERNS),
    }

    # Promote strong textual cues into counts when the wording is explicit.
    if signals["queueing"] and signals["vehicle_count"] == 0:
        signals["vehicle_count"] = 6
    if "double parked" in text and signals["stopped_vehicle_count"] == 0:
        signals["stopped_vehicle_count"] = 1
    if "pedestrian" in text and not signals["pedestrian_present"]:
        signals["pedestrian_present"] = True

    return signals


def validator_agent_node(state: SkymirrorState) -> dict[str, Any]:
    """
    Normalize VLM output and extract structured signals for expert agents.

    Args:
        state: Current pipeline state. Uses `vlm_text` when available and falls
            back to `validated_text` for direct unit-test usage.

    Returns:
        Partial state dict with normalized `validated_text` and `validated_signals`.
    """
    source_text = state.get("vlm_text") or state.get("validated_text", "")
    logger.info("validator_agent: Validating input text (%d chars).", len(source_text))

    normalized_text = _normalize_text(source_text)
    signals = _build_validated_signals(normalized_text)

    logger.debug(
        "validator_agent: Extracted signals vehicle_count=%s blocked_lanes=%s queueing=%s",
        signals.get("vehicle_count"),
        signals.get("blocked_lanes"),
        signals.get("queueing"),
    )

    return {
        "validated_text": normalized_text,
        "validated_signals": signals,
    }
