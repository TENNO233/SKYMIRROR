"""
experts.py - RAG-backed Rule-Dased expert agents.

V1 expert agents operate on normalized `validated_text`, lightweight
`validated_signals`, and short-term `history_context`. They do not depend on
Pinecone or additional LLM calls.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from skymirror.agents.prompts import (
    ENVIRONMENT_EXPERT_PROMPT_ID,
    ENVIRONMENT_EXPERT_PROMPT,
    ORDER_EXPERT_PROMPT_ID,
    ORDER_EXPERT_PROMPT,
    PROMPT_VERSION,
    SAFETY_EXPERT_PROMPT_ID,
    SAFETY_EXPERT_PROMPT,
)
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
from skymirror.tools.governance import (
    model_allowed,
    policy_version,
    validate_rag_namespace,
)
from skymirror.tools.llm_factory import build_openai_chat_model, get_openai_agent_model
from skymirror.tools.pinecone_retriever import get_pinecone_retriever

logger = logging.getLogger(__name__)

# ============================================================================
# 1. CONFIG & RAG MODELS (From Savion's Branch)
# ============================================================================
_DEFAULT_OPENAI_EXPERT_MODEL = "gpt-5.4-mini"
_DEFAULT_RAG_TOP_K = 5
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_TOKENS = 512

@dataclass(frozen=True)
class ExpertSpec:
    name: str
    namespace: str
    system_prompt: str
    focus: str
    prompt_id: str

class ExpertCitation(BaseModel):
    source_path: str = ""
    title: str = ""
    chunk_index: int = 0
    relevance_score: float = 0.0

class ExpertAssessment(BaseModel):
    summary: str
    findings: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"] = "low"
    recommended_action: str = ""
    citations: list[ExpertCitation] = Field(default_factory=list)

_EXPERT_SPECS: dict[str, ExpertSpec] = {
    "order_expert": ExpertSpec(
        name="order_expert",
        namespace="traffic-regulations",
        system_prompt=ORDER_EXPERT_PROMPT,
        focus="Determine possible traffic-order or parking violations in Singapore.",
        prompt_id=ORDER_EXPERT_PROMPT_ID,
    ),
    "safety_expert": ExpertSpec(
        name="safety_expert",
        namespace="safety-incidents",
        system_prompt=SAFETY_EXPERT_PROMPT,
        focus="Classify safety risks, incidents, and operational severity.",
        prompt_id=SAFETY_EXPERT_PROMPT_ID,
    ),
    "environment_expert": ExpertSpec(
        name="environment_expert",
        namespace="road-conditions",
        system_prompt=ENVIRONMENT_EXPERT_PROMPT,
        focus="Identify road-condition and environmental hazards affecting traffic.",
        prompt_id=ENVIRONMENT_EXPERT_PROMPT_ID,
    ),
}

def _read_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required.")
    return value

def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc

def _read_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a float.") from exc

def _load_expert_model_config() -> dict[str, Any]:
    config = {
        "api_key": _read_required_env("OPENAI_API_KEY"),
        "model": os.getenv(
            "OPENAI_EXPERT_MODEL",
            os.getenv("OPENAI_AGENT_MODEL", _DEFAULT_OPENAI_EXPERT_MODEL),
        ).strip()
        or get_openai_agent_model(),
        "temperature": _read_float_env("EXPERT_TEMPERATURE", _DEFAULT_TEMPERATURE),
        "max_tokens": _read_int_env("EXPERT_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
        "top_k": _read_int_env("RAG_TOP_K", _DEFAULT_RAG_TOP_K),
    }
    if not model_allowed(str(config["model"]), capability="expert"):
        raise RuntimeError(f"Model '{config['model']}' is not allowed for experts by policy.")
    return config

def _format_context(documents: list[Document]) -> str:
    if not documents:
        return "No supporting documents were retrieved."
    sections: list[str] = []
    for index, document in enumerate(documents, start=1):
        source_path = str(document.metadata.get("source_path", ""))
        title = str(document.metadata.get("title", ""))
        chunk_index = int(document.metadata.get("chunk_index", 0))
        sections.append(
            f"[{index}] title={title!r} source={source_path!r} chunk={chunk_index}\n"
            f"{document.page_content}"
        )
    return "\n\n".join(sections)

def _build_expert_prompt(spec: ExpertSpec, validated_text: str, documents: list[Document]) -> str:
    return (
        f"Focus: {spec.focus}\n\n"
        "Validated traffic-scene description:\n"
        f"{validated_text}\n\n"
        "Retrieved supporting context:\n"
        f"{_format_context(documents)}\n\n"
        "Return JSON with fields: summary, findings, severity, recommended_action, citations.\n"
        "Only cite retrieved documents. If the retrieved context does not support a claim, do not make it."
    )

def _invoke_expert_llm(spec: ExpertSpec, validated_text: str, documents: list[Document]) -> ExpertAssessment:
    config = _load_expert_model_config()
    llm = build_openai_chat_model(
        temperature=config["temperature"],
        model=config["model"],
        api_key=config["api_key"],
        max_tokens=config["max_tokens"],
    )
    structured_llm = llm.with_structured_output(ExpertAssessment)
    response = structured_llm.invoke(
        [
            SystemMessage(content=spec.system_prompt),
            HumanMessage(content=_build_expert_prompt(spec, validated_text, documents)),
        ]
    )
    if isinstance(response, ExpertAssessment):
        return response
    if isinstance(response, dict):
        return ExpertAssessment.model_validate(response)
    raise RuntimeError(f"{spec.name}: OpenAI expert model returned no structured assessment.")

# ============================================================================
# 2. RULE-BASED PATTERNS & LOGIC (From Main Branch)
# ============================================================================
_SEVERITY_RANK: dict[SeverityLevel, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_CONFIDENCE_RANK: dict[ConfidenceLevel, int] = {"low": 0, "medium": 1, "high": 2}

_ORDER_PARKING_PATTERNS = ("illegal parking", "illegally parked", "double parked", "double parking", "parked in lane", "parked on roadway", "stopped at the curb", "stopped on shoulder", "roadside parking")
_ORDER_OBSTRUCTION_PATTERNS = ("blocking lane", "blocked lane", "lane obstruction", "occupying lane", "obstructing traffic", "occupying roadway", "blocking traffic", "lane blocked")
_ORDER_CONGESTION_PATTERNS = ("congestion", "traffic jam", "gridlock", "heavy traffic", "long queue", "traffic build-up", "backed up", "bumper-to-bumper", "standstill traffic", "slow-moving traffic")
_ORDER_LOITERING_PATTERNS = ("lingering vehicle", "remained stopped", "still stationary", "stationary for long", "vehicle loitering")
_SAFETY_COLLISION_PATTERNS = ("collision", "suspected collision", "possible collision", "crash", "impact", "accident", "rear-end", "hit another vehicle", "vehicle contact")
_SAFETY_SEVERE_INCIDENT_PATTERNS = ("injured", "injury", "casualty", "ambulance", "fire truck", "police", "emergency crew")
_SAFETY_WRONG_WAY_PATTERNS = ("wrong way", "against traffic", "opposite direction", "wrong direction", "oncoming lane", "reverse direction")
_SAFETY_CROSSING_PATTERNS = ("jaywalking", "pedestrian crossing between vehicles", "pedestrian darting across", "dangerous crossing", "crossing active traffic", "pedestrian in roadway")
_SAFETY_CONFLICT_PATTERNS = ("near miss", "close call", "hard brake", "hard braking", "sudden brake", "swerving", "evasive action", "conflict risk", "conflict between vehicles")
_ENV_FLOODING_PATTERNS = ("flood", "flooding", "waterlogged", "standing water", "pooled water", "water covering", "submerged lane")
_ENV_CONSTRUCTION_PATTERNS = ("construction", "roadwork", "road work", "maintenance zone", "work zone", "work crew", "traffic cones", "barricade")
_ENV_OBSTACLE_PATTERNS = ("obstacle", "debris", "fallen tree", "object on road", "barrier", "cargo spill", "road blocked by object")
_ENV_VISIBILITY_PATTERNS = ("low visibility", "poor visibility", "fog", "smoke", "haze", "mist", "glare", "backlit", "overexposed", "underexposed", "poor lighting", "low light", "dim lighting")

_RECOMMENDED_ACTIONS: dict[str, list[str]] = {
    "illegal_parking": ["Verify whether the vehicle is unattended or improperly stopped.", "Notify traffic operations if the vehicle remains stationary.", "Dispatch a field check if the obstruction escalates."],
    "lane_obstruction": ["Verify the blocked lane in the live feed immediately.", "Coordinate traffic control or lane management if required.", "Escalate to field responders if the blockage persists."],
    "congestion": ["Verify live traffic density in the affected area.", "Notify traffic operations about the queue build-up.", "Assess whether lane control or diversion is needed."],
    "abnormal_queue": ["Monitor the queue across the next few frames.", "Notify traffic operations of the persistent queueing pattern.", "Prepare lane management or diversion if conditions worsen."],
    "vehicle_loitering": ["Verify whether the stationary vehicle is disabled or unattended.", "Notify traffic operations if the vehicle remains in place.", "Dispatch a field unit if the same vehicle continues to linger."],
    "collision_or_suspected_collision": ["Verify the scene immediately in the live feed.", "Notify incident response and traffic operations.", "Prepare emergency coordination if injuries are visible."],
    "wrong_way": ["Escalate immediately to traffic operations.", "Issue an urgent warning to nearby control teams.", "Coordinate direct intervention if the vehicle remains oncoming."],
    "dangerous_pedestrian_crossing": ["Verify pedestrian exposure in the live feed immediately.", "Notify traffic operations or on-site staff.", "Assess whether temporary control measures are needed."],
    "vehicle_or_pedestrian_conflict_risk": ["Monitor the conflict area in real time.", "Notify traffic operations of the elevated safety risk.", "Prepare immediate response if the risk escalates into contact."],
    "flooding": ["Verify water coverage and lane impact in the live feed.", "Notify road operations about possible flooding.", "Consider lane closure or diversion if water spreads."],
    "construction_zone": ["Verify whether the work zone is properly contained.", "Notify operations if construction is reducing capacity.", "Confirm whether lane control or signage adjustments are needed."],
    "road_obstacle": ["Verify the obstacle location and lane impact.", "Notify road operations for obstacle removal.", "Consider temporary lane control if the obstacle remains."],
    "low_visibility_or_abnormal_lighting": ["Verify visibility conditions in the live feed.", "Notify operations if visibility is affecting safe travel.", "Consider traffic control measures if the condition persists."],
}

def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    return any(pattern in text for pattern in patterns)

def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

def _history_hits(history_context: list[HistoryFrame], predicate: Callable[[HistoryFrame], bool]) -> int:
    return sum(1 for frame in history_context if predicate(frame))

def _history_metric_max(history_context: list[HistoryFrame], metric_field: str) -> int:
    values = [int(frame.get("validated_signals", {}).get(metric_field, 0)) for frame in history_context]
    return max(values, default=0)

def _impact_scope(text: str, signals: ValidatedSignals) -> ImpactScope:
    if "intersection" in text or "junction" in text:
        return "intersection"
    blocked_lanes = int(signals.get("blocked_lanes", 0))
    if blocked_lanes >= 2: return "multi_lane"
    if blocked_lanes == 1: return "single_lane"
    return "local"

def _persistence(history_context: list[HistoryFrame], history_hits: int, metric_field: str | None = None, current_metric: int = 0) -> PersistenceLevel:
    if not history_context: return "unknown"
    if history_hits == 0: return "new"
    if metric_field and current_metric > _history_metric_max(history_context, metric_field): return "worsening"
    return "persistent"

def _sort_scenarios(scenarios: list[ExpertScenario]) -> list[ExpertScenario]:
    return sorted(scenarios, key=lambda item: (_SEVERITY_RANK[item["severity"]], _CONFIDENCE_RANK[item["confidence"]], item["name"]), reverse=True)

def _build_summary(category: str, scenarios: list[ExpertScenario]) -> str:
    if not scenarios: return f"No {category}-related issues detected."
    names = ", ".join(scenario["name"] for scenario in scenarios)
    return f"Detected {len(scenarios)} {category}-related issue(s): {names}."

def _build_scenario(*, name: str, severity: SeverityLevel, confidence: ConfidenceLevel, reason: str, evidence: Iterable[str], impact_scope: ImpactScope, persistence: PersistenceLevel) -> ExpertScenario:
    return {
        "name": name,
        "severity": severity,
        "confidence": confidence,
        "reason": reason,
        "evidence": _dedupe(evidence),
        "impact_scope": impact_scope,
        "persistence": persistence,
        "recommended_actions": list(_RECOMMENDED_ACTIONS.get(name, [])),
    }

def _build_result(
    category: str,
    scenarios: list[ExpertScenario],
    citations: list[dict[str, Any]] | None = None,
) -> ExpertResult:
    sorted_scenarios = _sort_scenarios(scenarios)
    urgent = category == "safety" and any(scenario["severity"] in {"high", "critical"} for scenario in sorted_scenarios)
    return {
        "matched": bool(sorted_scenarios),
        "category": category,
        "summary": _build_summary(category, sorted_scenarios),
        "urgent": urgent,
        "scenarios": sorted_scenarios,
        "citations": list(citations or []),
    }

# Rule Evaluators (Condensed versions of the original logic)
def _order_scenarios(text: str, signals: ValidatedSignals, history_context: list[HistoryFrame]) -> list[ExpertScenario]:
    scenarios: list[ExpertScenario] = []
    blocked_lanes = int(signals.get("blocked_lanes", 0))
    vehicle_count = int(signals.get("vehicle_count", 0))
    stopped_vehicle_count = int(signals.get("stopped_vehicle_count", 0))
    queueing = bool(signals.get("queueing"))
    scope = _impact_scope(text, signals)

    if _contains_any(text, _ORDER_PARKING_PATTERNS):
        scenarios.append(_build_scenario(name="illegal_parking", severity="medium" if blocked_lanes > 0 else "low", confidence="high" if "illegal parking" in text else "medium", reason="Stationary vehicle improperly parked.", evidence=[f"stopped_vehicle_count={stopped_vehicle_count}"], impact_scope=scope, persistence="new"))
    
    if blocked_lanes > 0 or _contains_any(text, _ORDER_OBSTRUCTION_PATTERNS):
        scenarios.append(_build_scenario(name="lane_obstruction", severity="high" if blocked_lanes >= 2 else "medium", confidence="high" if blocked_lanes > 0 else "medium", reason="Lane occupation disrupting traffic.", evidence=[f"blocked_lanes={blocked_lanes}"], impact_scope=scope, persistence="new"))

    if queueing or vehicle_count >= 8 or _contains_any(text, _ORDER_CONGESTION_PATTERNS):
        scenarios.append(_build_scenario(name="congestion", severity="high" if vehicle_count >= 12 else "medium", confidence="high" if queueing else "medium", reason="Active congestion detected.", evidence=[f"vehicle_count={vehicle_count}", f"queueing={queueing}"], impact_scope=scope, persistence="new"))

    queue_history_hits = _history_hits(
        history_context,
        lambda frame: bool(frame.get("validated_signals", {}).get("queueing")),
    )
    if queueing and queue_history_hits >= 2:
        scenarios.append(
            _build_scenario(
                name="abnormal_queue",
                severity="medium",
                confidence="medium",
                reason="Queueing persisted across recent frames.",
                evidence=[f"queue_history_hits={queue_history_hits}", f"vehicle_count={vehicle_count}"],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    queue_history_hits,
                    metric_field="vehicle_count",
                    current_metric=vehicle_count,
                ),
            )
        )

    loitering_hits = _history_hits(
        history_context,
        lambda frame: int(frame.get("validated_signals", {}).get("stopped_vehicle_count", 0)) > 0,
    )
    if stopped_vehicle_count > 0 and (
        _contains_any(text, _ORDER_LOITERING_PATTERNS) or loitering_hits >= 2
    ):
        scenarios.append(
            _build_scenario(
                name="vehicle_loitering",
                severity="medium" if blocked_lanes > 0 else "low",
                confidence="medium",
                reason="A vehicle appears to remain stationary across multiple frames.",
                evidence=[f"stopped_vehicle_count={stopped_vehicle_count}", f"loitering_hits={loitering_hits}"],
                impact_scope=scope,
                persistence=_persistence(
                    history_context,
                    loitering_hits,
                    metric_field="stopped_vehicle_count",
                    current_metric=stopped_vehicle_count,
                ),
            )
        )

    return scenarios

def _safety_scenarios(text: str, signals: ValidatedSignals, history_context: list[HistoryFrame]) -> list[ExpertScenario]:
    scenarios: list[ExpertScenario] = []
    scope = _impact_scope(text, signals)
    collision_cue = bool(signals.get("collision_cue"))
    wrong_way_cue = bool(signals.get("wrong_way_cue"))
    conflict_risk_cue = bool(signals.get("conflict_risk_cue"))
    
    if collision_cue or _contains_any(text, _SAFETY_COLLISION_PATTERNS):
        scenarios.append(_build_scenario(name="collision_or_suspected_collision", severity="critical" if _contains_any(text, _SAFETY_SEVERE_INCIDENT_PATTERNS) else "high", confidence="high" if collision_cue else "medium", reason="Signs of vehicle collision.", evidence=[f"collision_cue={collision_cue}"], impact_scope=scope, persistence="new"))
    
    if wrong_way_cue or _contains_any(text, _SAFETY_WRONG_WAY_PATTERNS):
        scenarios.append(_build_scenario(name="wrong_way", severity="high", confidence="high", reason="Vehicle moving in wrong direction.", evidence=[f"wrong_way_cue={wrong_way_cue}"], impact_scope=scope, persistence="new"))

    dangerous_crossing_cue = bool(signals.get("dangerous_crossing_cue"))
    if dangerous_crossing_cue or _contains_any(text, _SAFETY_CROSSING_PATTERNS):
        scenarios.append(
            _build_scenario(
                name="dangerous_pedestrian_crossing",
                severity="high" if dangerous_crossing_cue else "medium",
                confidence="high" if dangerous_crossing_cue else "medium",
                reason="Pedestrian exposure is visible in active traffic.",
                evidence=[f"dangerous_crossing_cue={dangerous_crossing_cue}"],
                impact_scope=scope,
                persistence="new",
            )
        )

    if conflict_risk_cue or _contains_any(text, _SAFETY_CONFLICT_PATTERNS):
        scenarios.append(_build_scenario(name="vehicle_or_pedestrian_conflict_risk", severity="medium", confidence="high" if conflict_risk_cue else "medium", reason="Elevated risk of conflict.", evidence=[f"conflict_risk_cue={conflict_risk_cue}"], impact_scope=scope, persistence="new"))

    return scenarios

def _environment_scenarios(text: str, signals: ValidatedSignals, history_context: list[HistoryFrame]) -> list[ExpertScenario]:
    scenarios: list[ExpertScenario] = []
    scope = _impact_scope(text, signals)
    water_present = bool(signals.get("water_present"))
    construction_present = bool(signals.get("construction_present"))
    
    if water_present or _contains_any(text, _ENV_FLOODING_PATTERNS):
        scenarios.append(_build_scenario(name="flooding", severity="high", confidence="high" if water_present else "medium", reason="Water affecting road usability.", evidence=[f"water_present={water_present}"], impact_scope=scope, persistence="new"))
    
    if construction_present or _contains_any(text, _ENV_CONSTRUCTION_PATTERNS):
        scenarios.append(_build_scenario(name="construction_zone", severity="medium", confidence="high" if construction_present else "medium", reason="Construction activity affecting capacity.", evidence=[f"construction_present={construction_present}"], impact_scope=scope, persistence="new"))

    obstacle_present = bool(signals.get("obstacle_present"))
    if obstacle_present or _contains_any(text, _ENV_OBSTACLE_PATTERNS):
        scenarios.append(
            _build_scenario(
                name="road_obstacle",
                severity="medium",
                confidence="high" if obstacle_present else "medium",
                reason="A road obstacle or debris is affecting the roadway.",
                evidence=[f"obstacle_present={obstacle_present}"],
                impact_scope=scope,
                persistence="new",
            )
        )

    low_visibility = bool(signals.get("low_visibility")) or bool(signals.get("lighting_abnormal"))
    if low_visibility or _contains_any(text, _ENV_VISIBILITY_PATTERNS):
        scenarios.append(
            _build_scenario(
                name="low_visibility_or_abnormal_lighting",
                severity="medium",
                confidence="high" if low_visibility else "medium",
                reason="Visibility or lighting conditions may affect safe travel.",
                evidence=[
                    f"low_visibility={bool(signals.get('low_visibility'))}",
                    f"lighting_abnormal={bool(signals.get('lighting_abnormal'))}",
                ],
                impact_scope=scope,
                persistence="new",
            )
        )

    return scenarios


def _citations_from_assessment(
    assessment: ExpertAssessment,
    documents: list[Document],
) -> list[dict[str, Any]]:
    document_lookup: dict[tuple[str, str, int], dict[str, Any]] = {}
    for document in documents:
        metadata = dict(document.metadata)
        key = (
            str(metadata.get("source_path", "")),
            str(metadata.get("title", "")),
            int(metadata.get("chunk_index", 0)),
        )
        document_lookup[key] = metadata

    citations: list[dict[str, Any]] = []
    for citation in assessment.citations:
        key = (citation.source_path, citation.title, citation.chunk_index)
        metadata = document_lookup.get(key, {})
        citations.append(
            {
                "source_path": citation.source_path,
                "title": citation.title,
                "chunk_index": citation.chunk_index,
                "relevance_score": float(metadata.get("score", citation.relevance_score or 0.0) or 0.0),
            }
        )
    return citations


# ============================================================================
# 3. HYBRID NODE EXECUTION (The Merge: Rule-Based with RAG Fallback)
# ============================================================================
def _run_hybrid_expert(category: str, spec: ExpertSpec, state: SkymirrorState, rule_evaluator: Callable) -> dict[str, Any]:
    text = state.get("validated_text", "").strip()
    signals = state.get("validated_signals", {})
    history_context = state.get("history_context", [])

    if not text:
        raise ValueError(f"{spec.name} requires state['validated_text'].")

    # Step 1: Run fast rule-based evaluation
    scenarios = rule_evaluator(text, signals, history_context)
    rule_result = _build_result(category, scenarios, citations=[])

    metadata = {
        "namespace": spec.namespace,
        "rag_triggered": False,
        "retrieved_context_count": 0,
    }
    external_call = {
        "provider": "pinecone",
        "status": "skipped",
        "namespace": spec.namespace,
    }
    validate_rag_namespace(spec.namespace)

    # Step 2: Determine if RAG fallback is necessary
    # Trigger RAG if rule engine found nothing, OR if all findings are low confidence
    needs_fallback = False
    if not rule_result["matched"]:
        needs_fallback = True
    elif all(s["confidence"] == "low" for s in scenarios):
        needs_fallback = True

    if needs_fallback:
        logger.info("%s: Rule-based confidence low/empty. Triggering RAG fallback.", spec.name)
        try:
            config = _load_expert_model_config()
            retriever = get_pinecone_retriever(namespace=spec.namespace, top_k=config["top_k"])
            documents = retriever.invoke(text)
            metadata["retrieved_context_count"] = len(documents)
            citations: list[dict[str, Any]] = []
            external_call["status"] = "success"

            if documents:
                assessment = _invoke_expert_llm(spec, text, documents)
                metadata["rag_triggered"] = True
                citations = _citations_from_assessment(assessment, documents)

                if assessment.findings and assessment.severity != "low":
                    llm_scenario: ExpertScenario = {
                        "name": f"llm_inferred_{category}_issue",
                        "severity": assessment.severity,
                        "confidence": "medium",
                        "reason": assessment.summary,
                        "evidence": assessment.findings + [f"RAG Citations: {len(assessment.citations)}"],
                        "impact_scope": "local",
                        "persistence": "new",
                        "recommended_actions": [assessment.recommended_action] if assessment.recommended_action else [],
                    }
                    scenarios.append(llm_scenario)
                    rule_result = _build_result(category, scenarios, citations=citations)
                    rule_result["llm_raw_assessment"] = assessment.model_dump()
                else:
                    rule_result = _build_result(category, scenarios, citations=citations)
        except Exception as exc:
            external_call["status"] = "failed"
            external_call["reason"] = str(exc)
            logger.warning("%s: RAG fallback failed - %s", spec.name, exc)

    return {
        "expert_results": {
            spec.name: rule_result
        },
        "metadata": {
            "models": {
                spec.name: {
                    "model_name": os.getenv("OPENAI_EXPERT_MODEL", os.getenv("OPENAI_AGENT_MODEL", _DEFAULT_OPENAI_EXPERT_MODEL)),
                    "provider": "openai",
                }
            },
            "prompts": {
                spec.name: {
                    "prompt_id": spec.prompt_id,
                    "prompt_version": PROMPT_VERSION,
                }
            },
            "policies": {
                spec.name: {
                    "policy_version": policy_version(),
                }
            },
            "retrieval": {
                spec.name: {
                    "namespace": spec.namespace,
                    "rag_triggered": bool(metadata["rag_triggered"]),
                    "retrieved_context_count": int(metadata["retrieved_context_count"]),
                }
            },
            "external_calls": {
                f"{spec.name}_retriever": external_call
            },
            "experts": {
                spec.name: metadata
            }
        }
    }

def order_expert_node(state: SkymirrorState) -> dict[str, Any]:
    return _run_hybrid_expert("order", _EXPERT_SPECS["order_expert"], state, _order_scenarios)

def safety_expert_node(state: SkymirrorState) -> dict[str, Any]:
    return _run_hybrid_expert("safety", _EXPERT_SPECS["safety_expert"], state, _safety_scenarios)

def environment_expert_node(state: SkymirrorState) -> dict[str, Any]:
    return _run_hybrid_expert("environment", _EXPERT_SPECS["environment_expert"], state, _environment_scenarios)
