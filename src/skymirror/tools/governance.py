"""Lightweight governance helpers for SKYMIRROR runtime controls."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_POLICY_PATH = Path("governance/policy.yaml")
DEFAULT_RELEASE_THRESHOLDS_PATH = Path("governance/release_thresholds.yaml")
DEFAULT_POLICY_VERSION = "2026-04-19.v1"
DEFAULT_RELEASE_THRESHOLDS_VERSION = "2026-04-19.v1"
_TRUTHY = {"1", "true", "yes", "on"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_config_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (_project_root() / path).resolve()


def _parse_yaml_like_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - fallback only
        raise RuntimeError(
            "Governance config must be JSON-compatible YAML when PyYAML is unavailable."
        ) from exc

    parsed = yaml.safe_load(stripped)
    return dict(parsed or {})


def _load_config(path: Path, *, default_version: str) -> dict[str, Any]:
    if not path.is_file():
        return {"version": default_version}

    payload = _parse_yaml_like_text(path.read_text(encoding="utf-8"))
    payload.setdefault("version", default_version)
    return payload


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    raw_path = os.getenv("SKYMIRROR_POLICY_PATH", str(DEFAULT_POLICY_PATH))
    return _load_config(_resolve_config_path(raw_path), default_version=DEFAULT_POLICY_VERSION)


@lru_cache(maxsize=1)
def load_release_thresholds() -> dict[str, Any]:
    raw_path = os.getenv(
        "SKYMIRROR_RELEASE_THRESHOLDS_PATH",
        str(DEFAULT_RELEASE_THRESHOLDS_PATH),
    )
    return _load_config(
        _resolve_config_path(raw_path),
        default_version=DEFAULT_RELEASE_THRESHOLDS_VERSION,
    )


def policy_version(policy: dict[str, Any] | None = None) -> str:
    active = policy or load_policy()
    return str(active.get("version", DEFAULT_POLICY_VERSION))


def policy_snapshot(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active = dict(policy or load_policy())
    return {
        "version": policy_version(active),
        "input_controls": dict(active.get("input_controls") or {}),
        "rag_controls": dict(active.get("rag_controls") or {}),
        "runtime_controls": dict(active.get("runtime_controls") or {}),
        "telemetry": dict(active.get("telemetry") or {}),
    }


def tracing_enabled_by_policy(policy: dict[str, Any] | None = None) -> bool:
    active = policy or load_policy()
    telemetry = dict(active.get("telemetry") or {})
    value = str(telemetry.get("enable_tracing", "")).strip().lower()
    return value in _TRUTHY if value else True


def allowed_image_domains(policy: dict[str, Any] | None = None) -> set[str]:
    active = policy or load_policy()
    controls = dict(active.get("input_controls") or {})
    domains = controls.get("allowed_remote_image_domains") or []
    return {str(domain).strip().lower() for domain in domains if str(domain).strip()}


def validate_image_source(image_path: str, policy: dict[str, Any] | None = None) -> None:
    parsed = urlparse(image_path)
    if parsed.scheme.lower() not in {"http", "https"}:
        return

    host = parsed.hostname or ""
    allowed = allowed_image_domains(policy)
    if host.lower() not in allowed:
        raise ValueError(f"Remote image host '{host}' is not allowed by policy.")


def allowed_rag_namespaces(policy: dict[str, Any] | None = None) -> set[str]:
    active = policy or load_policy()
    controls = dict(active.get("rag_controls") or {})
    namespaces = controls.get("allowed_namespaces") or []
    return {str(namespace).strip() for namespace in namespaces if str(namespace).strip()}


def validate_rag_namespace(namespace: str, policy: dict[str, Any] | None = None) -> None:
    allowed = allowed_rag_namespaces(policy)
    if namespace not in allowed:
        raise ValueError(f"RAG namespace '{namespace}' is not allowed by policy.")


def lta_enabled(policy: dict[str, Any] | None = None) -> bool:
    active = policy or load_policy()
    controls = dict(active.get("runtime_controls") or {})
    value = str(controls.get("enable_lta_lookup", "true")).strip().lower()
    return value in _TRUTHY


def model_allowed(model_name: str, *, capability: str, policy: dict[str, Any] | None = None) -> bool:
    active = policy or load_policy()
    models = dict(active.get("allowed_models") or {})
    allowed_models = models.get(capability) or []
    return str(model_name).strip() in {
        str(item).strip() for item in allowed_models if str(item).strip()
    }


# ---------------------------------------------------------------------------
# Prompt Security – input length enforcement (LLMSecOps defence-in-depth)
# ---------------------------------------------------------------------------

_PROMPT_SECURITY_FIELD_KEYS = {
    "validated_text": "max_validated_text_chars",
    "expert_input": "max_expert_input_chars",
    "alert_message": "max_alert_message_chars",
    "history_context": "max_history_context_chars",
}

_PROMPT_SECURITY_DEFAULTS: dict[str, int] = {
    "max_validated_text_chars": 4000,
    "max_expert_input_chars": 6000,
    "max_alert_message_chars": 1000,
    "max_history_context_chars": 8000,
}


def prompt_security_limit(field: str, policy: dict[str, Any] | None = None) -> int:
    """Return the character limit for *field* from the active policy."""
    active = policy or load_policy()
    prompt_sec = dict(active.get("prompt_security") or {})
    policy_key = _PROMPT_SECURITY_FIELD_KEYS.get(field)
    if policy_key is None:
        return 0  # unknown field → no limit enforced
    default = _PROMPT_SECURITY_DEFAULTS.get(policy_key, 0)
    raw = prompt_sec.get(policy_key, default)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def validate_input_length(text: str, *, field: str, policy: dict[str, Any] | None = None) -> None:
    """Raise *ValueError* if *text* exceeds the policy-configured length for *field*.

    This is a lightweight structural guard against context-overflow prompt
    injection attacks.  Call it before passing user-derived text into any LLM
    prompt.
    """
    limit = prompt_security_limit(field, policy)
    if limit and len(text) > limit:
        raise ValueError(
            f"Input field '{field}' exceeds policy limit "
            f"({len(text)} chars > {limit} chars allowed)."
        )

