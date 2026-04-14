"""Simulated alert dispatch — writes JSON files and a dispatch log.

No real network calls. Each alert is written to its own JSON file;
a single dispatch_log.jsonl tracks all dispatches for the session.

Used by: skymirror.agents.alert_manager
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def dispatch(alert: dict[str, Any], output_dir: Path | str) -> None:
    """Write an alert to disk and append to the dispatch log.

    Idempotent: if the alert file already exists, skip writing and
    do not append a duplicate log entry.

    Args:
        alert: Complete alert dict (must contain "alert_id" and "department").
        output_dir: Directory to write files into (created if missing).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    alert_id = alert["alert_id"]
    alert_file = output_dir / f"{alert_id}.json"

    if alert_file.exists():
        logger.info(
            "alert_dispatch: SKIP duplicate alert_id=%s (already dispatched)",
            alert_id,
        )
        return

    alert_file.write_text(json.dumps(alert, indent=2, ensure_ascii=False), encoding="utf-8")

    log_entry = {
        "alert_id": alert_id,
        "department": alert.get("department", "unknown"),
        "dispatched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "simulated",
    }

    log_file = output_dir / "dispatch_log.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    logger.info(
        "alert_dispatch: SENT alert_id=%s domain=%s severity=%s -> %s",
        alert_id,
        alert.get("domain", "?"),
        alert.get("severity", "?"),
        alert.get("department", "?"),
    )
