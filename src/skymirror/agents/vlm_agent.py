"""
vlm_agent.py - Image guardrail and single-VLM scene extraction for SKYMIRROR.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from skymirror.agents.prompts import GUARDRAIL_SYSTEM_PROMPT, VLM_SYSTEM_PROMPT
from skymirror.agents.scene_schema import VlmSceneReport, coerce_model
from skymirror.graph.state import SkymirrorState
from skymirror.tools.llm_factory import build_openai_chat_model, get_openai_agent_model

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI_VLM_MODEL = "gpt-5.4"
_DEFAULT_OPENAI_GUARDRAIL_MODEL = "gpt-5.4-mini"
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_GUARDRAIL_MAX_TOKENS = 256
_IMAGE_FETCH_TIMEOUT_SECONDS = 10.0
_MIN_IMAGE_DIMENSION = 32
_MAX_IMAGE_DIMENSION = 8192
_SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

_VLM_USER_PROMPT = (
    "Return one JSON object with exactly these top-level fields:\n"
    "- summary: 1 to 3 sentences describing the traffic scene using only directly visible facts.\n"
    "- direct_observations: 4 to 10 short atomic observations.\n"
    "- road_features: visible roadway layout or markings such as intersection, junction, crosswalk, stop line, shoulder, lane arrows, bus lane, median, yellow box junction.\n"
    "- traffic_controls: visible signals or signs such as red traffic light, green traffic light, turn arrow, pedestrian signal, overhead sign.\n"
    "- notable_hazards: directly visible hazards or disruptions such as standing water, debris, blocked lane, collision damage, poor visibility.\n"
    "- signals: object with these exact fields and conservative values only:\n"
    "  vehicle_count, stopped_vehicle_count, pedestrian_present, blocked_lanes, queueing,\n"
    "  water_present, construction_present, obstacle_present, low_visibility,\n"
    "  lighting_abnormal, wrong_way_cue, collision_cue, dangerous_crossing_cue,\n"
    "  conflict_risk_cue.\n\n"
    "Signal guidance:\n"
    "- Count only clearly visible vehicles.\n"
    "- stopped_vehicle_count counts vehicles clearly stationary in the frame.\n"
    "- blocked_lanes is the number of lanes visibly obstructed right now.\n"
    "- Set *_cue booleans true only when the cue is directly observable.\n"
    "- If uncertain, use false or 0.\n"
    "- Return JSON only. No markdown, no prose outside the JSON object."
)

_GUARDRAIL_USER_PROMPT = (
    "Classify whether this traffic camera frame is safe for downstream traffic "
    "analysis. Return JSON with: allowed, status, reason, categories. "
    "Use status values only: allowed, blocked, indeterminate."
)


@dataclass(frozen=True)
class VisionConfig:
    api_key: str
    model: str
    max_tokens: int
    temperature: float


@dataclass(frozen=True)
class OpenAIGuardrailConfig:
    api_key: str
    model: str
    max_tokens: int
    temperature: float


@dataclass(frozen=True)
class ImagePayload:
    source: str
    media_type: str
    bytes_data: bytes
    base64_data: str
    byte_count: int
    width: int
    height: int

    @property
    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.base64_data}"


class GuardrailAssessment(BaseModel):
    allowed: bool
    status: Literal["allowed", "blocked", "indeterminate"]
    reason: str
    categories: list[str] = Field(default_factory=list)


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


def _read_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required.")
    return value


def _load_vlm_config() -> VisionConfig:
    return VisionConfig(
        api_key=_read_required_env("OPENAI_API_KEY"),
        model=os.getenv(
            "OPENAI_VLM_MODEL",
            os.getenv("OPENAI_AGENT_MODEL", _DEFAULT_OPENAI_VLM_MODEL),
        ).strip()
        or _DEFAULT_OPENAI_VLM_MODEL,
        max_tokens=_read_int_env("VLM_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
        temperature=_read_float_env("VLM_TEMPERATURE", _DEFAULT_TEMPERATURE),
    )


def _load_guardrail_config() -> OpenAIGuardrailConfig:
    return OpenAIGuardrailConfig(
        api_key=_read_required_env("OPENAI_API_KEY"),
        model=os.getenv(
            "OPENAI_GUARDRAIL_MODEL",
            os.getenv("OPENAI_AGENT_MODEL", _DEFAULT_OPENAI_GUARDRAIL_MODEL),
        ).strip()
        or get_openai_agent_model(),
        max_tokens=_read_int_env("GUARDRAIL_MAX_TOKENS", _DEFAULT_GUARDRAIL_MAX_TOKENS),
        temperature=_read_float_env("GUARDRAIL_TEMPERATURE", 0.0),
    )


def _is_remote_image(image_path: str) -> bool:
    parsed = urlparse(image_path)
    return parsed.scheme.lower() in {"http", "https"}


def _read_image_bytes(image_path: str) -> tuple[bytes, str]:
    if _is_remote_image(image_path):
        try:
            response = httpx.get(
                image_path,
                follow_redirects=True,
                timeout=_IMAGE_FETCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch remote image '{image_path}': {exc}") from exc

        if not response.content:
            raise ValueError(f"Remote image '{image_path}' returned an empty body.")

        return response.content, image_path

    image_file = Path(image_path).expanduser()
    if not image_file.is_file():
        raise FileNotFoundError(f"Image path does not exist: {image_file}")

    image_bytes = image_file.read_bytes()
    if not image_bytes:
        raise ValueError(f"Image file is empty: {image_file}")

    return image_bytes, str(image_file.resolve())


def build_image_payload(image_path: str) -> ImagePayload:
    image_bytes, source = _read_image_bytes(image_path)

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            media_type = Image.MIME.get(image.format or "", "").lower()
            width, height = image.size
    except UnidentifiedImageError as exc:
        raise ValueError(f"Unsupported or invalid image input: {image_path}") from exc

    if media_type not in _SUPPORTED_MEDIA_TYPES:
        supported = ", ".join(sorted(_SUPPORTED_MEDIA_TYPES))
        raise ValueError(
            f"Unsupported image media type '{media_type or 'unknown'}'. Supported: {supported}."
        )

    if width < _MIN_IMAGE_DIMENSION or height < _MIN_IMAGE_DIMENSION:
        raise ValueError(
            f"Image dimensions are too small: {width}x{height}. "
            f"Minimum is {_MIN_IMAGE_DIMENSION}x{_MIN_IMAGE_DIMENSION}."
        )

    if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
        raise ValueError(
            f"Image dimensions are too large: {width}x{height}. "
            f"Maximum is {_MAX_IMAGE_DIMENSION}x{_MAX_IMAGE_DIMENSION}."
        )

    return ImagePayload(
        source=source,
        media_type=media_type,
        bytes_data=image_bytes,
        base64_data=base64.b64encode(image_bytes).decode("ascii"),
        byte_count=len(image_bytes),
        width=width,
        height=height,
    )


def _normalize_guardrail_assessment(assessment: GuardrailAssessment) -> GuardrailAssessment:
    if assessment.status == "allowed":
        return assessment.model_copy(update={"allowed": True})

    return assessment.model_copy(update={"allowed": False})


def _coerce_scene_report(value: Any) -> VlmSceneReport:
    return coerce_model(value, VlmSceneReport)


def _classify_image_safety(image: ImagePayload, config: OpenAIGuardrailConfig) -> GuardrailAssessment:
    llm = build_openai_chat_model(
        temperature=config.temperature,
        model=config.model,
        api_key=config.api_key,
        max_tokens=config.max_tokens,
    )
    structured_llm = llm.with_structured_output(GuardrailAssessment)
    response = structured_llm.invoke(
        [
            SystemMessage(content=GUARDRAIL_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "text", "text": _GUARDRAIL_USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": image.data_url}},
                ]
            ),
        ]
    )

    if isinstance(response, GuardrailAssessment):
        return _normalize_guardrail_assessment(response)
    if isinstance(response, dict):
        return _normalize_guardrail_assessment(GuardrailAssessment.model_validate(response))
    raise RuntimeError("OpenAI guardrail returned no structured assessment.")


def _invoke_vlm(image: ImagePayload, config: VisionConfig) -> VlmSceneReport:
    llm = build_openai_chat_model(
        temperature=config.temperature,
        model=config.model,
        api_key=config.api_key,
        max_tokens=config.max_tokens,
    )
    structured_llm = llm.with_structured_output(VlmSceneReport)
    response = structured_llm.invoke(
        [
            SystemMessage(content=VLM_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "text", "text": _VLM_USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": image.data_url}},
                ]
            ),
        ]
    )
    return _coerce_scene_report(response)


def _build_blocked_guardrail_result(reason: str, *, category: str) -> dict[str, Any]:
    return {
        "allowed": False,
        "status": "blocked",
        "reason": reason,
        "categories": [category],
    }


def image_guardrail_node(state: SkymirrorState) -> dict[str, Any]:
    """Validate the image locally, then safety-classify it with OpenAI."""
    image_path = state.get("image_path")
    if not image_path:
        raise ValueError("image_guardrail_node requires state['image_path'].")

    try:
        image = build_image_payload(image_path)
    except Exception as exc:
        logger.warning("image_guardrail: Local preflight blocked frame - %s", exc)
        result = _build_blocked_guardrail_result(str(exc), category="invalid_image")
        return {
            "guardrail_result": result,
            "metadata": {
                "guardrail": {
                    "provider": "local_preflight",
                    "source": image_path,
                    "allowed": False,
                    "status": result["status"],
                    "reason": result["reason"],
                    "categories": result["categories"],
                }
            },
        }

    try:
        config = _load_guardrail_config()
        assessment = _classify_image_safety(image, config)
    except Exception as exc:
        logger.warning("image_guardrail: OpenAI guardrail blocked frame - %s", exc)
        result = _build_blocked_guardrail_result(
            f"Guardrail API failure: {exc}",
            category="guardrail_error",
        )
        return {
            "guardrail_result": result,
            "metadata": {
                "guardrail": {
                    "provider": "openai",
                    "model": config.model,
                    "source": image.source,
                    "media_type": image.media_type,
                    "width": image.width,
                    "height": image.height,
                    "byte_count": image.byte_count,
                    "allowed": False,
                    "status": result["status"],
                    "reason": result["reason"],
                    "categories": result["categories"],
                }
            },
        }

    result = assessment.model_dump()
    result["allowed"] = bool(result["allowed"] and result["status"] == "allowed")

    logger.info(
        "image_guardrail: status=%s allowed=%s categories=%s",
        result["status"],
        result["allowed"],
        result["categories"],
    )

    return {
        "guardrail_result": result,
        "metadata": {
            "guardrail": {
                "provider": "openai",
                "model": config.model,
                "source": image.source,
                "media_type": image.media_type,
                "width": image.width,
                "height": image.height,
                "byte_count": image.byte_count,
                "allowed": result["allowed"],
                "status": result["status"],
                "reason": result["reason"],
                "categories": result["categories"],
            }
        },
    }


def vlm_agent_node(state: SkymirrorState) -> dict[str, Any]:
    """Generate one structured traffic-scene report with OpenAI vision."""
    image_path = state.get("image_path")
    if not image_path:
        raise ValueError("vlm_agent_node requires state['image_path'].")

    image = build_image_payload(image_path)
    config = _load_vlm_config()
    report = _invoke_vlm(image, config)
    if not report.summary and not report.direct_observations:
        raise RuntimeError("OpenAI VLM returned an empty scene report.")

    logger.info(
        "vlm_agent: Generated scene report (%d observations).",
        len(report.direct_observations),
    )
    return {
        "vlm_output": report.model_dump(),
        "metadata": {
            "vlm": {
                "provider": "openai",
                "model": config.model,
                "source": image.source,
                "media_type": image.media_type,
                "width": image.width,
                "height": image.height,
                "byte_count": image.byte_count,
                "summary_chars": len(report.summary),
                "observation_count": len(report.direct_observations),
            }
        },
    }
