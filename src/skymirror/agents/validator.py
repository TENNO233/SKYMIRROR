"""validator.py - OpenAI image cross-check for a single VLM scene report."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from skymirror.agents.prompts import VALIDATOR_SYSTEM_PROMPT
from skymirror.agents.scene_schema import ValidatedSceneReport, VlmSceneReport, coerce_model
from skymirror.agents.vlm_agent import ImagePayload, build_image_payload
from skymirror.graph.state import SkymirrorState
from skymirror.tools.llm_factory import build_openai_chat_model, get_openai_agent_model

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI_VALIDATOR_MODEL = "gpt-5.4"
_DEFAULT_MAX_TOKENS = 768
_DEFAULT_TEMPERATURE = 0.0
_SURVEILLANCE_SUMMARY_STANDARD = (
    "Surveillance summary standard:\n"
    "- The final brief must stay operations-facing rather than descriptive for its own sake.\n"
    "- Keep to two short sentences.\n"
    "- Sentence 1 must state the observable traffic operating condition using direct facts and routing-useful terms.\n"
    "- Sentence 2 must state the government relevance: enforcement concern, safety risk, traffic-flow issue, roadway/environment hazard, or that no immediate action is indicated.\n"
    "- Do not mention aesthetics, camera composition, or speculation about hidden causes or intent."
)
_TRAFFIC_VIOLATION_KEYWORDS = (
    "red light",
    "running light",
    "traffic violation",
    "illegal turn",
    "illegal parking",
    "double parked",
    "lane change",
    "overtaking",
    "no entry",
)
_TRAFFIC_FLOW_KEYWORDS = (
    "congestion",
    "traffic jam",
    "gridlock",
    "queue",
    "queueing",
    "blocked lane",
    "lane obstruction",
    "occupying lane",
    "stopped vehicle",
)
_SAFETY_KEYWORDS = (
    "collision",
    "accident",
    "crash",
    "rollover",
    "overturned",
    "wrong way",
    "against traffic",
    "dangerous crossing",
    "jaywalking",
    "near miss",
    "conflict risk",
    "swerving",
    "hard braking",
)
_ENVIRONMENT_KEYWORDS = (
    "standing water",
    "waterlogged",
    "flood",
    "flooding",
    "debris",
    "obstacle",
    "construction",
    "roadwork",
    "smoke",
    "fire",
    "low visibility",
    "poor visibility",
    "poor lighting",
    "glare",
    "road damage",
    "pothole",
)
_LEADING_LABEL_RE = re.compile(r"^(scene assessment|government relevance)\s*:\s*", re.IGNORECASE)
_SENTENCE_BREAK_RE = re.compile(r"\s*[.?!]+\s*")


@dataclass(frozen=True)
class ValidatorConfig:
    api_key: str
    model: str
    max_tokens: int
    temperature: float


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc


def _read_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if not raw_value:
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a float.") from exc


def _load_validator_config() -> ValidatorConfig:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Environment variable OPENAI_API_KEY is required.")

    return ValidatorConfig(
        api_key=api_key,
        model=os.getenv(
            "OPENAI_VALIDATOR_MODEL",
            os.getenv("OPENAI_AGENT_MODEL", _DEFAULT_OPENAI_VALIDATOR_MODEL),
        ).strip()
        or get_openai_agent_model(),
        max_tokens=_read_int_env("VALIDATOR_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
        temperature=_read_float_env("VALIDATOR_TEMPERATURE", _DEFAULT_TEMPERATURE),
    )


def _build_validator_prompt(candidate_report: VlmSceneReport) -> str:
    return (
        "Review this candidate traffic-scene JSON against the image.\n\n"
        "Validation rules:\n"
        "- Keep only claims clearly supported by the image.\n"
        "- If the candidate report overstates, speculates, or conflicts with the image, correct it conservatively.\n"
        "- normalized_description must be concise, factual, suitable for downstream routing, and written as an operations-facing surveillance brief.\n"
        "- consensus_observations should be short atomic facts that survived cross-checking.\n"
        "- signals must match the corrected description and stay conservative.\n"
        "- discarded_claims should list the candidate claims you removed or softened because they were unsupported, too strong, or inaccurate.\n\n"
        f"{_SURVEILLANCE_SUMMARY_STANDARD}\n\n"
        "Candidate VLM scene report:\n"
        f"{json.dumps(candidate_report.model_dump(), indent=2)}"
    )


def _invoke_openai_validator(
    config: ValidatorConfig,
    image: ImagePayload,
    candidate_report: VlmSceneReport,
) -> ValidatedSceneReport:
    llm = build_openai_chat_model(
        temperature=config.temperature,
        model=config.model,
        api_key=config.api_key,
        max_tokens=config.max_tokens,
    )
    structured_llm = llm.with_structured_output(ValidatedSceneReport)
    response = structured_llm.invoke(
        [
            SystemMessage(content=VALIDATOR_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "text", "text": _build_validator_prompt(candidate_report)},
                    {"type": "image_url", "image_url": {"url": image.data_url}},
                ]
            ),
        ]
    )
    return coerce_model(response, ValidatedSceneReport)


def _flatten_scene_text(report: ValidatedSceneReport) -> str:
    parts: list[str] = [
        report.normalized_description,
        *report.consensus_observations,
        *report.road_features,
        *report.traffic_controls,
        *report.notable_hazards,
    ]
    return " ".join(part.strip() for part in parts if str(part).strip()).lower()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _collapse_to_single_sentence(text: str) -> str:
    cleaned = _LEADING_LABEL_RE.sub("", str(text).strip())
    if not cleaned:
        return ""
    parts = [segment.strip(" ,;:") for segment in _SENTENCE_BREAK_RE.split(cleaned) if segment.strip(" ,;:")]
    if not parts:
        return ""
    return "; ".join(parts)


def _build_scene_assessment(report: ValidatedSceneReport) -> str:
    clause = _collapse_to_single_sentence(report.normalized_description)
    if not clause:
        clause = "; ".join(
            _collapse_to_single_sentence(item)
            for item in report.consensus_observations
            if _collapse_to_single_sentence(item)
        )

    signals = report.signals
    flattened = _flatten_scene_text(report)
    addenda: list[str] = []

    if signals.queueing and not _contains_any(flattened, ("queue", "queueing", "congestion", "traffic jam", "gridlock")):
        addenda.append("queueing is visible")
    if signals.blocked_lanes > 0 and not _contains_any(flattened, ("blocked lane", "lane obstruction", "occupying lane")):
        lane_label = "lane" if signals.blocked_lanes == 1 else "lanes"
        addenda.append(f"at least {signals.blocked_lanes} blocked {lane_label} are visible")
    if signals.water_present and not _contains_any(flattened, ("standing water", "flood", "flooding", "waterlogged")):
        addenda.append("standing water is visible")
    if signals.collision_cue and not _contains_any(flattened, ("collision", "accident", "crash", "rollover", "overturned")):
        addenda.append("collision indicators are visible")
    if signals.wrong_way_cue and not _contains_any(flattened, ("wrong way", "against traffic", "no entry")):
        addenda.append("possible wrong-way movement is visible")
    if signals.low_visibility and not _contains_any(flattened, ("low visibility", "poor visibility", "fog", "smoke", "glare", "poor lighting")):
        addenda.append("visibility is reduced")

    fragments = [fragment for fragment in (clause, *addenda) if fragment]
    if fragments:
        return "; ".join(fragments)
    return "no clearly verified abnormal traffic condition is visible"


def _build_government_relevance(report: ValidatedSceneReport) -> str:
    signals = report.signals
    flattened = _flatten_scene_text(report)
    concerns: list[str] = []

    def add(concern: str) -> None:
        if concern not in concerns:
            concerns.append(concern)

    if signals.collision_cue or signals.wrong_way_cue or signals.dangerous_crossing_cue or signals.conflict_risk_cue:
        add("immediate safety review is warranted")
    elif _contains_any(flattened, _SAFETY_KEYWORDS):
        add("safety review is warranted")

    if signals.blocked_lanes > 0 or _contains_any(flattened, ("blocked lane", "lane obstruction", "occupying lane")):
        add("traffic management attention is warranted because lane capacity appears reduced")

    if signals.water_present or signals.construction_present or signals.obstacle_present or signals.low_visibility or signals.lighting_abnormal:
        add("roadway hazard review is warranted")
    elif _contains_any(flattened, _ENVIRONMENT_KEYWORDS):
        add("roadway hazard review is warranted")

    if _contains_any(flattened, _TRAFFIC_VIOLATION_KEYWORDS):
        add("enforcement review is warranted for a possible traffic violation")

    if signals.queueing or _contains_any(flattened, _TRAFFIC_FLOW_KEYWORDS):
        add("continued traffic-flow monitoring is warranted")

    if not concerns:
        return "no immediate enforcement, safety, or maintenance action is indicated; routine monitoring is sufficient"
    if len(concerns) == 1:
        return concerns[0]
    return f"{concerns[0]}, and {concerns[1]}"


def _validated_text_from_report(report: ValidatedSceneReport) -> str:
    scene_assessment = _build_scene_assessment(report)
    government_relevance = _build_government_relevance(report)
    return f"Scene assessment: {scene_assessment}. Government relevance: {government_relevance}."


def validator_agent_node(state: SkymirrorState) -> dict[str, Any]:
    """Cross-check one VLM scene report against the frame image."""
    image_path = state.get("image_path")
    if not image_path:
        raise ValueError("validator_agent_node requires state['image_path'].")

    candidate_payload = state.get("vlm_output")
    if not candidate_payload:
        raise ValueError("validator_agent_node requires state['vlm_output'].")

    candidate_report = coerce_model(candidate_payload, VlmSceneReport)
    image = build_image_payload(image_path)
    config = _load_validator_config()
    validated_scene = _invoke_openai_validator(config, image, candidate_report)

    validated_text = _validated_text_from_report(validated_scene)
    if not validated_text:
        raise RuntimeError("OpenAI validator returned an empty normalized_description.")

    validated_signals = validated_scene.signals.to_state_dict()

    logger.info(
        "validator_agent: Cross-checked scene JSON with %d retained observations.",
        len(validated_scene.consensus_observations),
    )
    return {
        "validated_scene": validated_scene.model_dump(),
        "validated_text": validated_text,
        "validated_signals": validated_signals,
        "metadata": {
            "validator": {
                "provider": "openai",
                "model": config.model,
                "review_mode": "image_cross_check",
                "summary_standard": "surveillance_brief_v1",
                "input_sources": ["vlm_output"],
                "candidate_observation_count": len(candidate_report.direct_observations),
                "consensus_observation_count": len(validated_scene.consensus_observations),
                "discarded_claim_count": len(validated_scene.discarded_claims),
            }
        },
    }
