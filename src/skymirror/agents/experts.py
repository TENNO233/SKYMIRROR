"""
experts.py - RAG-backed expert agents.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from skymirror.agents.prompts import (
    ENVIRONMENT_EXPERT_PROMPT,
    ORDER_EXPERT_PROMPT,
    SAFETY_EXPERT_PROMPT,
)
from skymirror.graph.state import SkymirrorState
from skymirror.tools.pinecone_retriever import get_pinecone_retriever

logger = logging.getLogger(__name__)

_DEFAULT_GEMINI_EXPERT_MODEL = "gemini-3.1-pro-preview"
_DEFAULT_RAG_TOP_K = 5
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_TOKENS = 512


@dataclass(frozen=True)
class ExpertSpec:
    name: str
    namespace: str
    system_prompt: str
    focus: str


class ExpertCitation(BaseModel):
    source_path: str = ""
    title: str = ""
    chunk_index: int = 0


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
    ),
    "safety_expert": ExpertSpec(
        name="safety_expert",
        namespace="safety-incidents",
        system_prompt=SAFETY_EXPERT_PROMPT,
        focus="Classify safety risks, incidents, and operational severity.",
    ),
    "environment_expert": ExpertSpec(
        name="environment_expert",
        namespace="road-conditions",
        system_prompt=ENVIRONMENT_EXPERT_PROMPT,
        focus="Identify road-condition and environmental hazards affecting traffic.",
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
    return {
        "api_key": _read_required_env("GEMINI_API_KEY"),
        "model": os.getenv("GEMINI_EXPERT_MODEL", _DEFAULT_GEMINI_EXPERT_MODEL).strip()
        or _DEFAULT_GEMINI_EXPERT_MODEL,
        "temperature": _read_float_env("EXPERT_TEMPERATURE", _DEFAULT_TEMPERATURE),
        "max_tokens": _read_int_env("EXPERT_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
        "top_k": _read_int_env("RAG_TOP_K", _DEFAULT_RAG_TOP_K),
    }


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
    from google import genai
    from google.genai import types

    config = _load_expert_model_config()
    client = genai.Client(api_key=config["api_key"])
    response = client.models.generate_content(
        model=config["model"],
        contents=_build_expert_prompt(spec, validated_text, documents),
        config=types.GenerateContentConfig(
            system_instruction=spec.system_prompt,
            temperature=config["temperature"],
            max_output_tokens=config["max_tokens"],
            response_mime_type="application/json",
            response_schema=ExpertAssessment,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, ExpertAssessment):
        return parsed

    if getattr(response, "text", None):
        return ExpertAssessment.model_validate_json(response.text)

    raise RuntimeError(f"{spec.name}: Gemini expert model returned no structured assessment.")


def _build_empty_assessment(spec: ExpertSpec) -> ExpertAssessment:
    return ExpertAssessment(
        summary=f"No supporting RAG context was retrieved for namespace '{spec.namespace}'.",
        findings=[],
        severity="low",
        recommended_action="Ingest reference documents into Pinecone before relying on this expert.",
        citations=[],
    )


def _run_expert(spec: ExpertSpec, state: SkymirrorState) -> dict[str, Any]:
    validated_text = state.get("validated_text", "").strip()
    if not validated_text:
        raise ValueError(f"{spec.name} requires state['validated_text'].")

    config = _load_expert_model_config()
    retriever = get_pinecone_retriever(namespace=spec.namespace, top_k=config["top_k"])
    documents = retriever.invoke(validated_text)

    logger.info(
        "%s: Retrieved %d context document(s) from namespace '%s'.",
        spec.name,
        len(documents),
        spec.namespace,
    )

    assessment = _build_empty_assessment(spec) if not documents else _invoke_expert_llm(spec, validated_text, documents)
    result = assessment.model_dump()
    result["retrieved_context_count"] = len(documents)
    result["namespace"] = spec.namespace

    return {
        "expert_results": {
            spec.name: result,
        },
        "metadata": {
            "experts": {
                spec.name: {
                    "namespace": spec.namespace,
                    "retrieved_context_count": len(documents),
                }
            }
        },
    }


def order_expert_node(state: SkymirrorState) -> dict[str, Any]:
    return _run_expert(_EXPERT_SPECS["order_expert"], state)


def safety_expert_node(state: SkymirrorState) -> dict[str, Any]:
    return _run_expert(_EXPERT_SPECS["safety_expert"], state)


def environment_expert_node(state: SkymirrorState) -> dict[str, Any]:
    return _run_expert(_EXPERT_SPECS["environment_expert"], state)
