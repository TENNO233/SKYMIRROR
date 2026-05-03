"""Template-based alert dict assembly for the Alert Agent.

Pure functions — no LLM calls, no I/O. Takes classification results and
expert data, returns a complete alert dict ready for dispatch.

Used by: skymirror.agents.alert_manager
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from skymirror.tools.alert.constants import DEPARTMENT_MAP, DOMAIN_MAP

if TYPE_CHECKING:
    from skymirror.tools.alert.lta_lookup import LtaCorroboration


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
    corroboration: LtaCorroboration | None = None,
) -> dict[str, Any]:
    """Assemble a complete alert dict from classification + expert data.

    All structured fields are rule-based; only `message` comes from LLM
    (via the classification dict).
    """
    domain = DOMAIN_MAP.get(expert_name, "unknown")
    department = DEPARTMENT_MAP.get(domain, "General Operations")

    evidence = [f.get("description", "") for f in findings if f.get("description")]

    lta_corroboration = None
    if corroboration is not None and corroboration.api_available:
        lta_corroboration = {
            "camera_location": {"lat": corroboration.camera_lat, "lng": corroboration.camera_lng},
            "queried_at": corroboration.queried_at,
            "api_available": True,
            "matches": [
                {
                    "event_type": m.event.event_type,
                    "description": m.event.description,
                    "distance_m": m.distance_m,
                    "match_type": m.match_type,
                    "source_api": m.event.source_api,
                }
                for m in corroboration.matches
            ],
            "match_summary": {
                "total": len(corroboration.matches),
                "location_and_domain": sum(
                    1 for m in corroboration.matches if m.match_type == "location_and_domain"
                ),
                "location_only": sum(
                    1 for m in corroboration.matches if m.match_type == "location_only"
                ),
            },
        }

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
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "image_path": image_path,
        "lta_corroboration": lta_corroboration,
    }
