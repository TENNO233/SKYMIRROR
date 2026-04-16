"""validator.py - OpenAI fusion node for dual-VLM structured scene reports."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from skymirror.agents.prompts import VALIDATOR_SYSTEM_PROMPT
from skymirror.agents.scene_schema import (
    ValidatedSceneReport,
    VlmSceneReport,
    coerce_model,
)
from skymirror.graph.state import SkymirrorState
from skymirror.tools.llm_factory import build_openai_chat_model, get_openai_agent_model

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI_VALIDATOR_MODEL = "gpt-5.4-mini"
_DEFAULT_MAX_TOKENS = 640
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


def _build_validator_prompt(gemini_report: VlmSceneReport, qwen_report: VlmSceneReport) -> str:
    return (
        "Fuse these two provider scene reports into one canonical traffic-scene JSON.\n\n"
        "Fusion rules:\n"
        "- Keep only directly visible facts.\n"
        "- Prefer overlap between Gemini and Qwen.\n"
        "- If counts or hazard claims conflict, keep the more conservative supported value.\n"
        "- normalized_description must be concise, factual, and suitable for downstream routing.\n"
        "- consensus_observations should be short atomic facts.\n"
        "- signals must align with the fused description.\n"
        "- discarded_claims should list claims you dropped because they were unsupported, speculative, or conflicting.\n\n"
        f"Gemini scene report:\n{json.dumps(gemini_report.model_dump(), indent=2)}\n\n"
        f"Qwen scene report:\n{json.dumps(qwen_report.model_dump(), indent=2)}"
    )


def _invoke_openai_validator(
    config: ValidatorConfig,
    gemini_report: VlmSceneReport,
    qwen_report: VlmSceneReport,
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
            HumanMessage(content=_build_validator_prompt(gemini_report, qwen_report)),
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
    """Fuse Gemini and Qwen scene JSON into one canonical scene answer."""
    vlm_outputs = state.get("vlm_outputs", {})
    gemini_payload = vlm_outputs.get("gemini")
    qwen_payload = vlm_outputs.get("qwen")

    if not gemini_payload or not qwen_payload:
        raise ValueError("validator_agent_node requires both Gemini and Qwen outputs.")

    gemini_report = coerce_model(gemini_payload, VlmSceneReport)
    qwen_report = coerce_model(qwen_payload, VlmSceneReport)

    config = _load_validator_config()
    validated_scene = _invoke_openai_validator(config, gemini_report, qwen_report)
    validated_text = _validated_text_from_report(validated_scene)
    if not validated_text:
        raise RuntimeError("OpenAI validator returned an empty normalized_description.")

    validated_signals = validated_scene.signals.to_state_dict()

    logger.info(
        "validator_agent: Fused scene JSON with %d consensus facts.",
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
                "input_sources": ["gemini", "qwen"],
                "consensus_observation_count": len(validated_scene.consensus_observations),
                "discarded_claim_count": len(validated_scene.discarded_claims),
            }
        },
    }
