"""Template-based alert dict assembly for the Alert Agent.

Pure functions — no LLM calls, no I/O. Takes classification results and
expert data, returns a complete alert dict ready for dispatch.

Used by: skymirror.agents.alert_manager
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from skymirror.tools.alert.constants import DEPARTMENT_MAP, DOMAIN_MAP


def _deterministic_id(image_path: str, expert_name: str) -> str:
    """Generate a deterministic alert ID from image_path + expert_name.

    Supports idempotent re-processing: same inputs always produce same ID.
    """
    key = f"{image_path}::{expert_name}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def render_alert(
    expert_name: str,
    classification: dict[str, str],
    findings: list[dict[str, Any]],
    regulations: list[dict[str, Any]],
    image_path: str,
) -> dict[str, Any]:
    """Assemble a complete alert dict from classification + expert data.

    All structured fields are rule-based; only `message` comes from LLM
    (via the classification dict).
    """
    domain = DOMAIN_MAP.get(expert_name, "unknown")
    department = DEPARTMENT_MAP.get(domain, "General Operations")

    evidence = [f.get("description", "") for f in findings if f.get("description")]

    return {
        "alert_id": _deterministic_id(image_path, expert_name),
        "domain": domain,
        "sub_type": classification["sub_type"],
        "severity": classification["severity"],
        "message": classification["message"],
        "source_expert": expert_name,
        "evidence": evidence,
        "regulations": regulations,
        "department": department,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "image_path": image_path,
    }
