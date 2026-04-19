"""validator.py - OpenAI image cross-check for a single VLM scene report."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from skymirror.agents.prompts import PROMPT_VERSION, VALIDATOR_PROMPT_ID, VALIDATOR_SYSTEM_PROMPT
from skymirror.agents.scene_schema import ValidatedSceneReport, VlmSceneReport, coerce_model
from skymirror.agents.vlm_agent import ImagePayload, build_image_payload
from skymirror.graph.state import SkymirrorState
from skymirror.tools.governance import model_allowed, policy_version
from skymirror.tools.llm_factory import build_openai_chat_model, get_openai_agent_model

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI_VALIDATOR_MODEL = "gpt-5.4"
_DEFAULT_MAX_TOKENS = 768
_DEFAULT_TEMPERATURE = 0.0


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

    config = ValidatorConfig(
        api_key=api_key,
        model=os.getenv(
            "OPENAI_VALIDATOR_MODEL",
            os.getenv("OPENAI_AGENT_MODEL", _DEFAULT_OPENAI_VALIDATOR_MODEL),
        ).strip()
        or get_openai_agent_model(),
        max_tokens=_read_int_env("VALIDATOR_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
        temperature=_read_float_env("VALIDATOR_TEMPERATURE", _DEFAULT_TEMPERATURE),
    )
    if not model_allowed(config.model, capability="validator"):
        raise RuntimeError(f"Model '{config.model}' is not allowed for validator by policy.")
    return config


def _build_validator_prompt(candidate_report: VlmSceneReport) -> str:
    return (
        "Review this candidate traffic-scene JSON against the image.\n\n"
        "Validation rules:\n"
        "- Keep only claims clearly supported by the image.\n"
        "- If the candidate report overstates, speculates, or conflicts with the image, correct it conservatively.\n"
        "- normalized_description must be concise, factual, and suitable for downstream routing.\n"
        "- consensus_observations should be short atomic facts that survived cross-checking.\n"
        "- signals must match the corrected description and stay conservative.\n"
        "- discarded_claims should list the candidate claims you removed or softened because they were unsupported, too strong, or inaccurate.\n\n"
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


def _validated_text_from_report(report: ValidatedSceneReport) -> str:
    normalized_description = report.normalized_description.strip()
    if normalized_description:
        return normalized_description
    fallback = "; ".join(report.consensus_observations).strip()
    return fallback


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
                "input_sources": ["vlm_output"],
                "candidate_observation_count": len(candidate_report.direct_observations),
                "consensus_observation_count": len(validated_scene.consensus_observations),
                "discarded_claim_count": len(validated_scene.discarded_claims),
            },
            "models": {
                "validator": {
                    "model_name": config.model,
                    "provider": "openai",
                }
            },
            "prompts": {
                "validator": {
                    "prompt_id": VALIDATOR_PROMPT_ID,
                    "prompt_version": PROMPT_VERSION,
                }
            },
            "policies": {
                "validator": {
                    "policy_version": policy_version(),
                }
            },
            "external_calls": {
                "validator_api": {
                    "provider": "openai",
                    "status": "success",
                    "model_name": config.model,
                }
            },
        },
    }
