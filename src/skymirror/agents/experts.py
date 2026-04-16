"""
experts.py — Rule-Based Domain Expert Agents
============================================
V1 expert agents operate on normalized `validated_text`, lightweight
`validated_signals`, and short-term `history_context`. They do not depend on
Pinecone or additional LLM calls.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from skymirror.graph.state import (
    ConfidenceLevel,
    ExpertResult,
    ExpertScenario,
    HistoryFrame,
    ImpactScope,
    PersistenceLevel,
    SeverityLevel,
    SkymirrorState,
    ValidatedSignals,
)

logger = logging.getLogger(__name__)

_SEVERITY_RANK: dict[SeverityLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}
_CONFIDENCE_RANK: dict[ConfidenceLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
}

_ORDER_PARKING_PATTERNS = (
    "illegal parking",
    "illegally parked",
    "double parked",
    "double parking",
    "parked in lane",
    "parked on roadway",
    "stopped at the curb",
    "stopped on shoulder",
    "roadside parking",
)
_ORDER_OBSTRUCTION_PATTERNS = (
    "blocking lane",
    "blocked lane",
    "lane obstruction",
    "occupying lane",
    "obstructing traffic",
    "occupying roadway",
    "blocking traffic",
    "lane blocked",
)
_ORDER_CONGESTION_PATTERNS = (
    "congestion",
    "traffic jam",
    "gridlock",
    "heavy traffic",
    "long queue",
    "traffic build-up",
    "backed up",
    "bumper-to-bumper",
    "standstill traffic",
    "slow-moving traffic",
)
_ORDER_LOITERING_PATTERNS = (
    "lingering vehicle",
    "remained stopped",
    "still stationary",
    "stationary for long",
    "vehicle loitering",
)

_SAFETY_COLLISION_PATTERNS = (
    "collision",
    "suspected collision",
    "possible collision",
    "crash",
    "impact",
    "accident",
    "rear-end",
    "hit another vehicle",
    "vehicle contact",
)
_SAFETY_SEVERE_INCIDENT_PATTERNS = (
    "injured",
    "injury",
    "casualty",
    "ambulance",
    "fire truck",
    "police",
    "emergency crew",
)
_SAFETY_WRONG_WAY_PATTERNS = (
    "wrong way",
    "against traffic",
    "opposite direction",
    "wrong direction",
    "oncoming lane",
    "reverse direction",
)
_SAFETY_CROSSING_PATTERNS = (
    "jaywalking",
    "pedestrian crossing between vehicles",
    "pedestrian darting across",
    "dangerous crossing",
    "crossing active traffic",
    "pedestrian in roadway",
)
_SAFETY_CONFLICT_PATTERNS = (
    "near miss",
    "close call",
    "hard brake",
    "hard braking",
    "sudden brake",
    "swerving",
    "evasive action",
    "conflict risk",
    "conflict between vehicles",
)

_ENV_FLOODING_PATTERNS = (
    "flood",
    "flooding",
    "waterlogged",
    "standing water",
    "pooled water",
    "water covering",
    "submerged lane",
)
_ENV_CONSTRUCTION_PATTERNS = (
    "construction",
    "roadwork",
    "road work",
    "maintenance zone",
    "work zone",
    "work crew",
    "traffic cones",
    "barricade",
)
_ENV_OBSTACLE_PATTERNS = (
    "obstacle",
    "debris",
    "fallen tree",
    "object on road",
    "barrier",
    "cargo spill",
    "road blocked by object",
)
_ENV_VISIBILITY_PATTERNS = (
    "low visibility",
    "poor visibility",
    "fog",
    "smoke",
    "haze",
    "mist",
    "glare",
    "backlit",
    "overexposed",
    "underexposed",
    "poor lighting",
    "low light",
    "dim lighting",
)

_RECOMMENDED_ACTIONS: dict[str, list[str]] = {
    "illegal_parking": [
        "Verify whether the vehicle is unattended or improperly stopped.",
        "Notify traffic operations if the vehicle remains stationary.",
        "Dispatch a field check if the obstruction escalates.",
    ],
    "lane_obstruction": [
        "Verify the blocked lane in the live feed immediately.",
        "Coordinate traffic control or lane management if required.",
        "Escalate to field responders if the blockage persists.",
    ],
    "congestion": [
        "Verify live traffic density in the affected area.",
        "Notify traffic operations about the queue build-up.",
        "Assess whether lane control or diversion is needed.",
    ],
    "abnormal_queue": [
        "Monitor the queue across the next few frames.",
        "Notify traffic operations of the persistent queueing pattern.",
        "Prepare lane management or diversion if conditions worsen.",
    ],
    "vehicle_loitering": [
        "Verify whether the stationary vehicle is disabled or unattended.",
        "Notify traffic operations if the vehicle remains in place.",
        "Dispatch a field unit if the same vehicle continues to linger.",
    ],
    "collision_or_suspected_collision": [
        "Verify the scene immediately in the live feed.",
        "Notify incident response and traffic operations.",
        "Prepare emergency coordination if injuries are visible.",
    ],
    "wrong_way": [
        "Escalate immediately to traffic operations.",
        "Issue an urgent warning to nearby control teams.",
        "Coordinate direct intervention if the vehicle remains oncoming.",
    ],
    "dangerous_pedestrian_crossing": [
        "Verify pedestrian exposure in the live feed immediately.",
        "Notify traffic operations or on-site staff.",
        "Assess whether temporary control measures are needed.",
    ],
    "vehicle_or_pedestrian_conflict_risk": [
        "Monitor the conflict area in real time.",
        "Notify traffic operations of the elevated safety risk.",
        "Prepare immediate response if the risk escalates into contact.",
    ],
    "flooding": [
        "Verify water coverage and lane impact in the live feed.",
        "Notify road operations about possible flooding.",
        "Consider lane closure or diversion if water spreads.",
    ],
    "construction_zone": [
        "Verify whether the work zone is properly contained.",
        "Notify operations if construction is reducing capacity.",
        "Confirm whether lane control or signage adjustments are needed.",
    ],
    "road_obstacle": [
        "Verify the obstacle location and lane impact.",
        "Notify road operations for obstacle removal.",
        "Consider temporary lane control if the obstacle remains.",
    ],
    "low_visibility_or_abnormal_lighting": [
        "Verify visibility conditions in the live feed.",
        "Notify operations if visibility is affecting safe travel.",
        "Consider traffic control measures if the condition persists.",
    ],
}


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    """Return True when any phrase appears in the normalized text."""
    return any(pattern in text for pattern in patterns)


def _dedupe(items: Iterable[str]) -> list[str]:
    """Preserve order while removing duplicate evidence strings."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _history_hits(
    history_context: list[HistoryFrame],
    predicate: Callable[[HistoryFrame], bool],
) -> int:
    """Count historical frames satisfying a predicate."""
    return sum(1 for frame in history_context if predicate(frame))


def _history_metric_max(history_context: list[HistoryFrame], metric_field: str) -> int:
    """Return the maximum historical metric value for a signal field."""
    values = [
        int(frame.get("validated_signals", {}).get(metric_field, 0))
        for frame in history_context
    ]
    return max(values, default=0)


def _impact_scope(text: str, signals: ValidatedSignals) -> ImpactScope:
    """Infer the impact scope from text and blocked-lane cues."""
    if "intersection" in text or "junction" in text:
        return "intersection"
    blocked_lanes = int(signals.get("blocked_lanes", 0))
    if blocked_lanes >= 2:
        return "multi_lane"
    if blocked_lanes == 1:
        return "single_lane"
    return "local"


def _persistence(
    history_context: list[HistoryFrame],
    history_hits: int,
    metric_field: str | None = None,
    current_metric: int = 0,
) -> PersistenceLevel:
    """Classify persistence based on recent history and optional metric growth."""
    if not history_context:
        return "unknown"
    if history_hits == 0:
        return "new"
    if metric_field and current_metric > _history_metric_max(history_context, metric_field):
        return "worsening"
    return "persistent"


def _sort_scenarios(scenarios: list[ExpertScenario]) -> list[ExpertScenario]:
    """Sort scenarios by severity, then confidence, then name."""
    return sorted(
        scenarios,
        key=lambda item: (
            _SEVERITY_RANK[item["severity"]],
            _CONFIDENCE_RANK[item["confidence"]],
            item["name"],
        ),
        reverse=True,
    )


def _build_summary(category: str, scenarios: list[ExpertScenario]) -> str:
    """Generate a concise expert summary line."""
    if not scenarios:
        return f"No {category}-related issues detected."
    names = ", ".join(scenario["name"] for scenario in scenarios)
    return f"Detected {len(scenarios)} {category}-related issue(s): {names}."


def _build_scenario(
    *,
    name: str,
    severity: SeverityLevel,
    confidence: ConfidenceLevel,
    reason: str,
    evidence: Iterable[str],
    impact_scope: ImpactScope,
    persistence: PersistenceLevel,
) -> ExpertScenario:
    """Construct a scenario payload with standardized fields."""
    return {
        "name": name,
        "severity": severity,
        "confidence": confidence,
        "reason": reason,
        "evidence": _dedupe(evidence),
        "impact_scope": impact_scope,
        "persistence": persistence,
        "recommended_actions": list(_RECOMMENDED_ACTIONS[name]),
    }


def _build_result(category: str, scenarios: list[ExpertScenario]) -> ExpertResult:
    """Construct the final expert result payload."""
    sorted_scenarios = _sort_scenarios(scenarios)
    urgent = category == "safety" and any(
        scenario["severity"] in {"high", "critical"} for scenario in sorted_scenarios
    )
    return {
        "matched": bool(sorted_scenarios),
        "category": category,
        "summary": _build_summary(category, sorted_scenarios),
        "urgent": urgent,
        "scenarios": sorted_scenarios,
    }


def _order_scenarios(
    text: str,
    signals: ValidatedSignals,
    history_context: list[HistoryFrame],
) -> list[ExpertScenario]:
    """Detect order-related issues from text, signals, and short-term history."""
    scenarios: list[ExpertScenario] = []
    blocked_lanes = int(signals.get("blocked_lanes", 0))
    vehicle_count = int(signals.get("vehicle_count", 0))
    stopped_vehicle_count = int(signals.get("stopped_vehicle_count", 0))
    queueing = bool(signals.get("queueing"))
    scope = _impact_scope(text, signals)

    if _contains_any(text, _ORDER_PARKING_PATTERNS):
        parking_history_hits = _history_hits(
            history_context,
            lambda frame: int(frame.get("validated_signals", {}).get("stopped_vehicle_count", 0)) > 0,
        )
        severity: SeverityLevel = "medium" if blocked_lanes > 0 else "low"
        confidence: ConfidenceLevel = "high" if "illegal parking" in text or "double parked" in text else "medium"
        scenarios.append(
            _build_scenario(
                name="illegal_parking",
                severity=severity,
                confidence=confidence,
                reason=(
                    "A stationary vehicle appears to be improperly parked near active traffic."
                ),
                evidence=[
                    "validated_text contains parking-related wording",
                    f"stopped_vehicle_count={stopped_vehicle_count}",
                    f"blocked_lanes={blocked_lanes}",
                    f"parking seen in {parking_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    parking_history_hits,
                    metric_field="stopped_vehicle_count",
                    current_metric=stopped_vehicle_count,
                ),
            )
        )

    if blocked_lanes > 0 or _contains_any(text, _ORDER_OBSTRUCTION_PATTERNS):
        obstruction_history_hits = _history_hits(
            history_context,
            lambda frame: int(frame.get("validated_signals", {}).get("blocked_lanes", 0)) > 0,
        )
        severity = "high" if blocked_lanes >= 2 or queueing else "medium"
        confidence = "high" if blocked_lanes > 0 else "medium"
        scenarios.append(
            _build_scenario(
                name="lane_obstruction",
                severity=severity,
                confidence=confidence,
                reason="Lane occupation is likely disrupting normal traffic movement.",
                evidence=[
                    "validated_text indicates lane blockage or occupation",
                    f"blocked_lanes={blocked_lanes}",
                    f"queueing={queueing}",
                    f"lane obstruction seen in {obstruction_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    obstruction_history_hits,
                    metric_field="blocked_lanes",
                    current_metric=blocked_lanes,
                ),
            )
        )

    if queueing or vehicle_count >= 8 or _contains_any(text, _ORDER_CONGESTION_PATTERNS):
        congestion_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("queueing")),
        )
        severity = "high" if blocked_lanes > 0 or vehicle_count >= 12 else "medium"
        confidence = "high" if queueing or _contains_any(text, _ORDER_CONGESTION_PATTERNS) else "medium"
        scenarios.append(
            _build_scenario(
                name="congestion",
                severity=severity,
                confidence=confidence,
                reason="Traffic density and queueing suggest active congestion.",
                evidence=[
                    "validated_text mentions congestion or queueing",
                    f"vehicle_count={vehicle_count}",
                    f"queueing={queueing}",
                    f"blocked_lanes={blocked_lanes}",
                    f"queue-like conditions seen in {congestion_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    congestion_history_hits,
                    metric_field="vehicle_count",
                    current_metric=vehicle_count,
                ),
            )
        )

    abnormal_queue_history_hits = _history_hits(
        history_context,
        lambda frame: bool(frame.get("validated_signals", {}).get("queueing"))
        or any(
            scenario.get("name") in {"congestion", "abnormal_queue"}
            for result in frame.get("expert_results", {}).values()
            for scenario in result.get("scenarios", [])
        ),
    )
    if queueing and abnormal_queue_history_hits >= 2:
        scenarios.append(
            _build_scenario(
                name="abnormal_queue",
                severity="high" if blocked_lanes > 0 or vehicle_count >= 10 else "medium",
                confidence="high",
                reason="Queueing has repeated across recent frames and appears abnormal.",
                evidence=[
                    "current frame indicates queueing",
                    f"vehicle_count={vehicle_count}",
                    f"blocked_lanes={blocked_lanes}",
                    f"same queue pattern seen in {abnormal_queue_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    abnormal_queue_history_hits,
                    metric_field="vehicle_count",
                    current_metric=vehicle_count,
                ),
            )
        )

    loitering_history_hits = _history_hits(
        history_context,
        lambda frame: int(frame.get("validated_signals", {}).get("stopped_vehicle_count", 0)) > 0,
    )
    if (
        stopped_vehicle_count > 0 and loitering_history_hits >= 2
    ) or _contains_any(text, _ORDER_LOITERING_PATTERNS):
        confidence: ConfidenceLevel = "high" if loitering_history_hits >= 2 else "medium"
        scenarios.append(
            _build_scenario(
                name="vehicle_loitering",
                severity="medium",
                confidence=confidence,
                reason="A stationary vehicle pattern appears to be persisting across recent frames.",
                evidence=[
                    f"stopped_vehicle_count={stopped_vehicle_count}",
                    f"vehicle loitering cues seen in {loitering_history_hits} recent frame(s)",
                    "validated_text suggests prolonged stationary presence",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    loitering_history_hits,
                    metric_field="stopped_vehicle_count",
                    current_metric=stopped_vehicle_count,
                ),
            )
        )

    return scenarios


def _safety_scenarios(
    text: str,
    signals: ValidatedSignals,
    history_context: list[HistoryFrame],
) -> list[ExpertScenario]:
    """Detect safety-related issues from text, signals, and short-term history."""
    scenarios: list[ExpertScenario] = []
    blocked_lanes = int(signals.get("blocked_lanes", 0))
    scope = _impact_scope(text, signals)
    collision_cue = bool(signals.get("collision_cue"))
    wrong_way_cue = bool(signals.get("wrong_way_cue"))
    dangerous_crossing_cue = bool(signals.get("dangerous_crossing_cue"))
    conflict_risk_cue = bool(signals.get("conflict_risk_cue"))
    pedestrian_present = bool(signals.get("pedestrian_present"))

    if collision_cue or _contains_any(text, _SAFETY_COLLISION_PATTERNS):
        collision_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("collision_cue")),
        )
        severe_incident = _contains_any(text, _SAFETY_SEVERE_INCIDENT_PATTERNS)
        severity: SeverityLevel = "critical" if severe_incident else "high"
        confidence: ConfidenceLevel = "high" if collision_cue or "collision" in text or "crash" in text else "medium"
        scenarios.append(
            _build_scenario(
                name="collision_or_suspected_collision",
                severity=severity,
                confidence=confidence,
                reason="The scene includes signs of a collision or likely vehicle contact.",
                evidence=[
                    "validated_text includes collision-related wording",
                    f"collision_cue={collision_cue}",
                    f"blocked_lanes={blocked_lanes}",
                    f"collision signs seen in {collision_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(history_context, collision_history_hits),
            )
        )

    if wrong_way_cue or _contains_any(text, _SAFETY_WRONG_WAY_PATTERNS):
        wrong_way_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("wrong_way_cue")),
        )
        severity = "critical" if "oncoming" in text or conflict_risk_cue else "high"
        scenarios.append(
            _build_scenario(
                name="wrong_way",
                severity=severity,
                confidence="high",
                reason="A vehicle appears to be moving in the wrong direction of travel.",
                evidence=[
                    "validated_text includes wrong-way wording",
                    f"wrong_way_cue={wrong_way_cue}",
                    f"wrong-way seen in {wrong_way_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(history_context, wrong_way_history_hits),
            )
        )

    if dangerous_crossing_cue or (
        pedestrian_present and _contains_any(text, _SAFETY_CROSSING_PATTERNS)
    ):
        crossing_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("dangerous_crossing_cue")),
        )
        severity = "critical" if conflict_risk_cue else "high"
        confidence = "high" if dangerous_crossing_cue else "medium"
        scenarios.append(
            _build_scenario(
                name="dangerous_pedestrian_crossing",
                severity=severity,
                confidence=confidence,
                reason="A pedestrian appears to be crossing in a way that exposes them to traffic risk.",
                evidence=[
                    "validated_text includes dangerous crossing wording",
                    f"pedestrian_present={pedestrian_present}",
                    f"dangerous_crossing_cue={dangerous_crossing_cue}",
                    f"crossing risk seen in {crossing_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(history_context, crossing_history_hits),
            )
        )

    if conflict_risk_cue or _contains_any(text, _SAFETY_CONFLICT_PATTERNS):
        conflict_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("conflict_risk_cue")),
        )
        severity = "high" if pedestrian_present or wrong_way_cue else "medium"
        confidence = "high" if conflict_risk_cue else "medium"
        scenarios.append(
            _build_scenario(
                name="vehicle_or_pedestrian_conflict_risk",
                severity=severity,
                confidence=confidence,
                reason="The current frame suggests an elevated risk of vehicle or pedestrian conflict.",
                evidence=[
                    "validated_text includes near-conflict wording",
                    f"conflict_risk_cue={conflict_risk_cue}",
                    f"pedestrian_present={pedestrian_present}",
                    f"conflict pattern seen in {conflict_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(history_context, conflict_history_hits),
            )
        )

    return scenarios


def _environment_scenarios(
    text: str,
    signals: ValidatedSignals,
    history_context: list[HistoryFrame],
) -> list[ExpertScenario]:
    """Detect environment-related issues from text, signals, and short-term history."""
    scenarios: list[ExpertScenario] = []
    blocked_lanes = int(signals.get("blocked_lanes", 0))
    vehicle_count = int(signals.get("vehicle_count", 0))
    scope = _impact_scope(text, signals)
    water_present = bool(signals.get("water_present"))
    construction_present = bool(signals.get("construction_present"))
    obstacle_present = bool(signals.get("obstacle_present"))
    low_visibility = bool(signals.get("low_visibility"))
    lighting_abnormal = bool(signals.get("lighting_abnormal"))

    if water_present or _contains_any(text, _ENV_FLOODING_PATTERNS):
        flooding_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("water_present")),
        )
        severity: SeverityLevel = "critical" if blocked_lanes >= 2 or scope == "intersection" else "high"
        scenarios.append(
            _build_scenario(
                name="flooding",
                severity=severity,
                confidence="high" if water_present else "medium",
                reason="Water accumulation appears to be affecting road usability and safety.",
                evidence=[
                    "validated_text includes flooding-related wording",
                    f"water_present={water_present}",
                    f"blocked_lanes={blocked_lanes}",
                    f"flooding signs seen in {flooding_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    flooding_history_hits,
                    metric_field="blocked_lanes",
                    current_metric=blocked_lanes,
                ),
            )
        )

    if construction_present or _contains_any(text, _ENV_CONSTRUCTION_PATTERNS):
        construction_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("construction_present")),
        )
        if blocked_lanes > 0:
            severity = "high"
        elif vehicle_count >= 6:
            severity = "medium"
        else:
            severity = "low"
        scenarios.append(
            _build_scenario(
                name="construction_zone",
                severity=severity,
                confidence="high" if construction_present else "medium",
                reason="Road construction activity appears to be affecting roadway capacity.",
                evidence=[
                    "validated_text includes construction-related wording",
                    f"construction_present={construction_present}",
                    f"blocked_lanes={blocked_lanes}",
                    f"construction signs seen in {construction_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    construction_history_hits,
                    metric_field="blocked_lanes",
                    current_metric=blocked_lanes,
                ),
            )
        )

    if obstacle_present or _contains_any(text, _ENV_OBSTACLE_PATTERNS):
        obstacle_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("obstacle_present")),
        )
        severity = "high" if blocked_lanes > 0 else "medium"
        scenarios.append(
            _build_scenario(
                name="road_obstacle",
                severity=severity,
                confidence="high" if obstacle_present else "medium",
                reason="An obstacle appears to be present on or near the roadway.",
                evidence=[
                    "validated_text includes obstacle-related wording",
                    f"obstacle_present={obstacle_present}",
                    f"blocked_lanes={blocked_lanes}",
                    f"obstacle signs seen in {obstacle_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    obstacle_history_hits,
                    metric_field="blocked_lanes",
                    current_metric=blocked_lanes,
                ),
            )
        )

    if low_visibility or lighting_abnormal or _contains_any(text, _ENV_VISIBILITY_PATTERNS):
        visibility_history_hits = _history_hits(
            history_context,
            lambda frame: bool(frame.get("validated_signals", {}).get("low_visibility"))
            or bool(frame.get("validated_signals", {}).get("lighting_abnormal")),
        )
        severity = "high" if blocked_lanes > 0 or vehicle_count >= 8 else "medium"
        confidence = "high" if low_visibility or lighting_abnormal else "medium"
        scenarios.append(
            _build_scenario(
                name="low_visibility_or_abnormal_lighting",
                severity=severity,
                confidence=confidence,
                reason="Visibility or lighting conditions appear to be reducing safe travel conditions.",
                evidence=[
                    "validated_text includes visibility or lighting wording",
                    f"low_visibility={low_visibility}",
                    f"lighting_abnormal={lighting_abnormal}",
                    f"visibility issue seen in {visibility_history_hits} recent frame(s)",
                ],
                impact_scope=scope,
                persistence=_persistence(history_context, visibility_history_hits),
            )
        )

    return scenarios


def order_expert_node(state: SkymirrorState) -> dict[str, Any]:
    """
    Analyse order-related events such as illegal parking, obstruction, and queueing.
    """
    text = state.get("validated_text", "")
    signals = state.get("validated_signals", {})
    history_context = state.get("history_context", [])
    logger.info("order_expert: Analysing order-related conditions.")
    result = _build_result("order", _order_scenarios(text, signals, history_context))
    return {"expert_results": {"order_expert": result}}


def safety_expert_node(state: SkymirrorState) -> dict[str, Any]:
    """
    Analyse safety-related events such as collisions, wrong-way movement, and conflict risk.
    """
    text = state.get("validated_text", "")
    signals = state.get("validated_signals", {})
    history_context = state.get("history_context", [])
    logger.info("safety_expert: Analysing safety-related conditions.")
    result = _build_result("safety", _safety_scenarios(text, signals, history_context))
    return {"expert_results": {"safety_expert": result}}


def environment_expert_node(state: SkymirrorState) -> dict[str, Any]:
    """
    Analyse environment-related issues such as flooding, obstacles, and visibility.
    """
    text = state.get("validated_text", "")
    signals = state.get("validated_signals", {})
    history_context = state.get("history_context", [])
    logger.info("environment_expert: Analysing environment-related conditions.")
    result = _build_result("environment", _environment_scenarios(text, signals, history_context))
    return {"expert_results": {"environment_expert": result}}
