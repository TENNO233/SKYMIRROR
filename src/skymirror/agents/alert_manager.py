"""
alert_manager.py — Alert Generation & Optional Dispatch
=======================================================
Consumes structured expert results and turns matched scenarios into alert
records. Dispatch is optional and only attempted when `ALERT_WEBHOOK_URL`
is configured.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from skymirror.graph.state import ExpertResult, ExpertScenario, SkymirrorState

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_alert(
    *,
    expert_name: str,
    result: ExpertResult,
    scenario: ExpertScenario,
    image_path: str,
) -> dict[str, Any]:
    """Convert one scenario into an alert record."""
    return {
        "severity": scenario["severity"],
        "type": scenario["name"],
        "category": result["category"],
        "message": scenario["reason"],
        "source_expert": expert_name,
        "timestamp": _iso_now(),
        "image_path": image_path,
        "urgent": result["urgent"],
        "summary": result["summary"],
        "recommended_actions": scenario["recommended_actions"],
        "evidence": scenario["evidence"],
        "impact_scope": scenario["impact_scope"],
        "persistence": scenario["persistence"],
        "confidence": scenario["confidence"],
    }


def _dispatch_alerts(alerts: list[dict[str, Any]]) -> None:
    """Send alerts to an optional webhook destination."""
    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if not webhook_url or not alerts:
        return

    try:
        import httpx

        response = httpx.post(webhook_url, json=alerts, timeout=5.0)
        response.raise_for_status()
        logger.info("alert_manager: Dispatched %d alert(s) to webhook.", len(alerts))
    except Exception as exc:
        logger.warning("alert_manager: Failed to dispatch alerts — %s", exc)


def alert_manager_node(state: SkymirrorState) -> dict[str, Any]:
    """
    Transform expert results into alert records and optionally dispatch them.

    Args:
        state: Pipeline state containing merged `expert_results`.

    Returns:
        Partial state dict with `alerts` populated.
    """
    expert_results: dict[str, ExpertResult] = state.get("expert_results", {})
    image_path = state.get("image_path", "")
    logger.info(
        "alert_manager: Processing results from %d expert(s): %s",
        len(expert_results),
        list(expert_results.keys()),
    )

    alerts: list[dict[str, Any]] = []
    for expert_name, result in expert_results.items():
        if not result.get("matched"):
            continue
        for scenario in result.get("scenarios", []):
            alerts.append(
                _build_alert(
                    expert_name=expert_name,
                    result=result,
                    scenario=scenario,
                    image_path=image_path,
                )
            )

    _dispatch_alerts(alerts)
    return {"alerts": alerts}
