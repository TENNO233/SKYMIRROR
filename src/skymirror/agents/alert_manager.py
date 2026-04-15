"""
alert_manager.py - Minimal alert synthesis for expert results.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)

_EXPERT_TO_TYPE = {
    "order_expert": "traffic_violation",
    "safety_expert": "safety_incident",
    "environment_expert": "env_hazard",
}


def alert_manager_node(state: SkymirrorState) -> dict[str, Any]:
    """Convert expert results into structured alerts."""
    expert_results: dict[str, Any] = state.get("expert_results", {})
    logger.info(
        "alert_manager: Processing results from %d expert(s): %s",
        len(expert_results),
        list(expert_results.keys()),
    )

    alerts: list[dict[str, Any]] = []
    timestamp = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    image_path = state.get("image_path", "")

    for expert_name, result in expert_results.items():
        findings = result.get("findings") or []
        severity = str(result.get("severity", "low"))
        alert_type = _EXPERT_TO_TYPE.get(expert_name, "unknown")

        if findings:
            for finding in findings:
                alerts.append(
                    {
                        "severity": severity,
                        "type": alert_type,
                        "message": str(finding),
                        "source_expert": expert_name,
                        "timestamp": timestamp,
                        "image_path": image_path,
                    }
                )
            continue

        if int(result.get("retrieved_context_count", 0)) == 0:
            continue

        summary = str(result.get("summary", "")).strip()
        if summary:
            alerts.append(
                {
                    "severity": severity,
                    "type": alert_type,
                    "message": summary,
                    "source_expert": expert_name,
                    "timestamp": timestamp,
                    "image_path": image_path,
                }
            )

    return {"alerts": alerts}
