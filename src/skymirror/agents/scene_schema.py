from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any, TypeVar

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T", bound=BaseModel)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _clean_text(value: str) -> str:
    return " ".join(str(value).split()).strip()


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_value in values:
        value = _clean_text(raw_value)
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(value)
    return result


class TrafficSceneSignals(BaseModel):
    """Downstream-friendly signal set used by validator, experts, and orchestrator."""

    vehicle_count: int = Field(default=0, ge=0)
    stopped_vehicle_count: int = Field(default=0, ge=0)
    pedestrian_present: bool = False
    blocked_lanes: int = Field(default=0, ge=0)
    queueing: bool = False
    water_present: bool = False
    construction_present: bool = False
    obstacle_present: bool = False
    low_visibility: bool = False
    lighting_abnormal: bool = False
    wrong_way_cue: bool = False
    collision_cue: bool = False
    dangerous_crossing_cue: bool = False
    conflict_risk_cue: bool = False

    def to_state_dict(self) -> dict[str, Any]:
        return self.model_dump()


class VlmSceneReport(BaseModel):
    """Structured provider output for one traffic camera frame."""

    summary: str = ""
    direct_observations: list[str] = Field(default_factory=list)
    road_features: list[str] = Field(default_factory=list)
    traffic_controls: list[str] = Field(default_factory=list)
    notable_hazards: list[str] = Field(default_factory=list)
    signals: TrafficSceneSignals = Field(default_factory=TrafficSceneSignals)

    @field_validator(
        "direct_observations",
        "road_features",
        "traffic_controls",
        "notable_hazards",
        mode="before",
    )
    @classmethod
    def _normalize_string_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _dedupe_strings([value])
        if isinstance(value, list):
            return _dedupe_strings(str(item) for item in value)
        return []

    @field_validator("summary", mode="before")
    @classmethod
    def _normalize_summary(cls, value: Any) -> str:
        return _clean_text(str(value or ""))


class ValidatedSceneReport(BaseModel):
    """Fused canonical scene description emitted by the validator."""

    normalized_description: str = ""
    consensus_observations: list[str] = Field(default_factory=list)
    road_features: list[str] = Field(default_factory=list)
    traffic_controls: list[str] = Field(default_factory=list)
    notable_hazards: list[str] = Field(default_factory=list)
    signals: TrafficSceneSignals = Field(default_factory=TrafficSceneSignals)
    discarded_claims: list[str] = Field(default_factory=list)

    @field_validator(
        "consensus_observations",
        "road_features",
        "traffic_controls",
        "notable_hazards",
        "discarded_claims",
        mode="before",
    )
    @classmethod
    def _normalize_string_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _dedupe_strings([value])
        if isinstance(value, list):
            return _dedupe_strings(str(item) for item in value)
        return []

    @field_validator("normalized_description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> str:
        return _clean_text(str(value or ""))


def extract_json_object_text(text: str) -> str:
    candidate = text.strip()
    if not candidate:
        raise ValueError("Expected JSON output but received an empty string.")

    candidate = _CODE_FENCE_RE.sub("", candidate).strip()
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        trimmed = candidate[start : end + 1]
        json.loads(trimmed)
        return trimmed


def coerce_model(value: Any, model_type: type[T]) -> T:
    if isinstance(value, model_type):
        return value
    if isinstance(value, dict):
        return model_type.model_validate(value)
    if isinstance(value, str):
        return model_type.model_validate_json(extract_json_object_text(value))
    raise TypeError(f"Cannot coerce {type(value)!r} into {model_type.__name__}.")
