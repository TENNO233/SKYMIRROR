"""
vlm_agent.py - Guardrail and dual-VLM nodes for SKYMIRROR.
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
from skymirror.graph.state import SkymirrorState
from skymirror.tools.llm_factory import build_openai_chat_model, get_openai_agent_model

logger = logging.getLogger(__name__)

_DEFAULT_GEMINI_VLM_MODEL = "gemini-3-flash-preview"
_DEFAULT_OPENAI_GUARDRAIL_MODEL = "gpt-5.4-mini"
_DEFAULT_QWEN_VLM_MODEL = "qwen3.6-plus"
_DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
_DEFAULT_MAX_TOKENS = 384
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_GUARDRAIL_MAX_TOKENS = 256
_IMAGE_FETCH_TIMEOUT_SECONDS = 10.0
_MIN_IMAGE_DIMENSION = 32
_MAX_IMAGE_DIMENSION = 8192
_SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

_VLM_USER_PROMPT = (
    "Describe this traffic camera frame in concise factual language. Include "
    "only directly visible traffic details: vehicle positions, pedestrian "
    "presence, signals, lane usage, road markings, obstructions, hazards, and "
    "visibility conditions."
)

_QWEN_VLM_PROMPT = f"{VLM_SYSTEM_PROMPT}\n\n{_VLM_USER_PROMPT}"

_GUARDRAIL_USER_PROMPT = (
    "Classify whether this traffic camera frame is safe for downstream traffic "
    "analysis. Return JSON with: allowed, status, reason, categories. "
    "Use status values only: allowed, blocked, indeterminate."
)


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    vlm_model: str
    max_tokens: int
    temperature: float


@dataclass(frozen=True)
class OpenAIGuardrailConfig:
    api_key: str
    model: str
    max_tokens: int
    temperature: float


@dataclass(frozen=True)
class QwenConfig:
    api_key: str
    model: str
    base_url: str


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


def _load_gemini_config() -> GeminiConfig:
    return GeminiConfig(
        api_key=_read_required_env("GEMINI_API_KEY"),
        vlm_model=os.getenv("GEMINI_VLM_MODEL", _DEFAULT_GEMINI_VLM_MODEL).strip()
        or _DEFAULT_GEMINI_VLM_MODEL,
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


def _load_qwen_config() -> QwenConfig:
    return QwenConfig(
        api_key=_read_required_env("DASHSCOPE_API_KEY"),
        model=os.getenv("QWEN_VLM_MODEL", _DEFAULT_QWEN_VLM_MODEL).strip()
        or _DEFAULT_QWEN_VLM_MODEL,
        base_url=os.getenv("DASHSCOPE_BASE_URL", _DEFAULT_DASHSCOPE_BASE_URL).strip()
        or _DEFAULT_DASHSCOPE_BASE_URL,
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


def _build_image_payload(image_path: str) -> ImagePayload:
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


def _extract_text_content(content: Any) -> str:
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


def _normalize_guardrail_assessment(assessment: GuardrailAssessment) -> GuardrailAssessment:
    if assessment.status == "allowed":
        return assessment.model_copy(update={"allowed": True})

    return assessment.model_copy(update={"allowed": False})


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


def _invoke_gemini_vlm(image: ImagePayload, config: GeminiConfig) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.api_key)
    response = client.models.generate_content(
        model=config.vlm_model,
        contents=[
            types.Part.from_bytes(data=image.bytes_data, mime_type=image.media_type),
            _VLM_USER_PROMPT,
        ],
        config=types.GenerateContentConfig(
            system_instruction=VLM_SYSTEM_PROMPT,
            temperature=config.temperature,
            max_output_tokens=config.max_tokens,
        ),
    )
    return (response.text or "").strip()


def _invoke_qwen_vlm(image: ImagePayload, config: QwenConfig) -> str:
    import dashscope
    from dashscope import MultiModalConversation

    dashscope.base_http_api_url = config.base_url
    response = MultiModalConversation.call(
        api_key=config.api_key,
        model=config.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": image.data_url},
                    {"text": _QWEN_VLM_PROMPT},
                ],
            }
        ],
    )

    try:
        content = response.output.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Qwen returned an unexpected response shape: {response!r}") from exc

    return _extract_text_content(content)


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
        image = _build_image_payload(image_path)
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


def gemini_vlm_node(state: SkymirrorState) -> dict[str, Any]:
    """Generate a traffic-scene description with Gemini."""
    image_path = state.get("image_path")
    if not image_path:
        raise ValueError("gemini_vlm_node requires state['image_path'].")

    image = _build_image_payload(image_path)
    config = _load_gemini_config()
    text = _invoke_gemini_vlm(image, config)
    if not text:
        raise RuntimeError("Gemini VLM returned an empty description.")

    logger.info("gemini_vlm: Generated description (%d chars).", len(text))
    return {
        "vlm_outputs": {"gemini": text},
        "metadata": {
            "vlm": {
                "gemini": {
                    "provider": "gemini",
                    "model": config.vlm_model,
                    "source": image.source,
                    "media_type": image.media_type,
                    "width": image.width,
                    "height": image.height,
                    "byte_count": image.byte_count,
                }
            }
        },
    }


def qwen_vlm_node(state: SkymirrorState) -> dict[str, Any]:
    """Generate a traffic-scene description with Qwen 3.6 Plus."""
    image_path = state.get("image_path")
    if not image_path:
        raise ValueError("qwen_vlm_node requires state['image_path'].")

    image = _build_image_payload(image_path)
    config = _load_qwen_config()
    text = _invoke_qwen_vlm(image, config)
    if not text:
        raise RuntimeError("Qwen VLM returned an empty description.")

    logger.info("qwen_vlm: Generated description (%d chars).", len(text))
    return {
        "vlm_outputs": {"qwen": text},
        "metadata": {
            "vlm": {
                "qwen": {
                    "provider": "qwen",
                    "model": config.model,
                    "base_url": config.base_url,
                    "source": image.source,
                    "media_type": image.media_type,
                    "width": image.width,
                    "height": image.height,
                    "byte_count": image.byte_count,
                }
            }
        },
    }
