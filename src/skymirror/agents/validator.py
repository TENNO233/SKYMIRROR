"""validator.py - OpenAI reconciliation node for dual-VLM output."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from skymirror.agents.prompts import VALIDATOR_SYSTEM_PROMPT
from skymirror.graph.state import SkymirrorState
from skymirror.tools.llm_factory import build_openai_chat_model, get_openai_agent_model

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI_VALIDATOR_MODEL = "gpt-5.4-mini"
_DEFAULT_MAX_TOKENS = 384
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


def _build_validator_prompt(gemini_text: str, qwen_text: str) -> str:
    return (
        "Reconcile these two traffic-scene descriptions into one concise factual summary.\n\n"
        "Rules:\n"
        "- Keep only directly observable traffic facts.\n"
        "- Remove speculation and stylistic language.\n"
        "- Drop conflicting claims unless both descriptions support them.\n"
        "- Prefer overlap between Gemini and Qwen.\n"
        "- Output plain text only.\n\n"
        f"Gemini description:\n{gemini_text}\n\n"
        f"Qwen description:\n{qwen_text}"
    )


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                if block.strip():
                    parts.append(block.strip())
                continue

            if isinstance(block, dict):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)

            if isinstance(text, str) and text.strip():
                parts.append(text.strip())

        return "\n".join(parts).strip()

    return str(content).strip()


def _invoke_openai_validator(config: ValidatorConfig, gemini_text: str, qwen_text: str) -> str:
    llm = build_openai_chat_model(
        temperature=config.temperature,
        model=config.model,
        api_key=config.api_key,
        max_tokens=config.max_tokens,
    )
    response = llm.invoke(
        [
            SystemMessage(content=VALIDATOR_SYSTEM_PROMPT),
            HumanMessage(content=_build_validator_prompt(gemini_text, qwen_text)),
        ]
    )
    return _extract_message_text(getattr(response, "content", response))


def validator_agent_node(state: SkymirrorState) -> dict[str, Any]:
    """Reconcile Gemini and Qwen outputs into one validated summary."""
    vlm_outputs = state.get("vlm_outputs", {})
    gemini_text = vlm_outputs.get("gemini", "").strip()
    qwen_text = vlm_outputs.get("qwen", "").strip()

    if not gemini_text or not qwen_text:
        raise ValueError("validator_agent_node requires both Gemini and Qwen outputs.")

    config = _load_validator_config()
    validated_text = _invoke_openai_validator(config, gemini_text, qwen_text)
    if not validated_text:
        raise RuntimeError("OpenAI validator returned an empty validated_text.")

    logger.info("validator_agent: Generated validated text (%d chars).", len(validated_text))
    return {
        "validated_text": validated_text,
        "metadata": {
            "validator": {
                "provider": "openai",
                "model": config.model,
                "input_sources": ["gemini", "qwen"],
                "gemini_chars": len(gemini_text),
                "qwen_chars": len(qwen_text),
            }
        },
    }
