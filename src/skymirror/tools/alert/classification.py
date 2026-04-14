"""LLM-based event classification for the Alert Agent.

Uses with_structured_output to constrain LLM responses to a valid
AlertClassification schema. Falls back to template-based defaults
on any LLM failure.

Used by: skymirror.agents.alert_manager
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel

from skymirror.tools.alert.constants import SUB_TYPE_MAP
from skymirror.tools import llm_factory

logger = logging.getLogger(__name__)


class AlertClassification(BaseModel):
    """Structured output schema for LLM classification."""
    sub_type: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


def _get_classification_llm() -> Any:
    """Return an LLM instance for classification. Separated for test mocking."""
    return llm_factory.get_llm(temperature=0.1)


def build_classification_prompt(
    domain: str,
    findings: list[dict[str, Any]],
    expert_severity: str,
) -> str:
    """Build the classification prompt with domain-specific enum constraints."""
    sub_types = SUB_TYPE_MAP.get(domain, ["other"])
    return (
        "You are SKYMIRROR's Alert Classification Agent.\n\n"
        "Given the following expert analysis findings, classify this event.\n\n"
        f"Domain: {domain}\n"
        f"Expert findings: {json.dumps(findings, indent=2)}\n\n"
        f"Choose sub_type from: {sub_types}\n"
        "Choose severity from: low, medium, high, critical\n"
        f"The expert's own severity assessment was: {expert_severity}\n\n"
        "Write a concise alert message (1-2 sentences) in English summarizing "
        "the event for the receiving department. Include what happened, the "
        "image reference, and recommended urgency."
    )


def classify(
    domain: str,
    findings: list[dict[str, Any]],
    expert_severity: str,
) -> dict[str, str]:
    """Classify an event using LLM with structured output.

    Returns a dict with keys: sub_type, severity, message.
    Falls back to safe defaults on any LLM failure.
    """
    prompt = build_classification_prompt(domain, findings, expert_severity)

    try:
        llm = _get_classification_llm()
        structured_llm = llm.with_structured_output(AlertClassification)
        from langchain_core.messages import HumanMessage
        result = structured_llm.invoke([HumanMessage(content=prompt)])

        sub_type = result.sub_type
        valid_types = SUB_TYPE_MAP.get(domain, ["other"])
        if sub_type not in valid_types:
            logger.warning(
                "LLM returned invalid sub_type %r for domain %r; forcing 'other'.",
                sub_type, domain,
            )
            sub_type = "other"

        return {
            "sub_type": sub_type,
            "severity": result.severity,
            "message": result.message,
        }

    except Exception as exc:
        logger.warning("Classification LLM failed: %s — using fallback.", exc)
        first_desc = findings[0].get("description", "Unknown event") if findings else "Unknown event"
        return {
            "sub_type": "other",
            "severity": expert_severity if expert_severity in ("low", "medium", "high", "critical") else "medium",
            "message": f"{domain} alert: {first_desc}",
        }
