"""Simulated alert dispatch — writes JSON files and a dispatch log.

No real network calls. Each alert is written to its own JSON file;
a single dispatch_log.jsonl tracks all dispatches for the session.

Used by: skymirror.agents.alert_manager
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _extract_date_partition(alert: dict[str, Any]) -> str:
    """Derive the YYYY-MM-DD date partition for an alert.

    Prefers the alert's own `timestamp` field (ISO 8601). Falls back to
    today's UTC date if timestamp is missing or malformed — this keeps
    dispatch robust even for partially-formed alerts.
    """
    ts = alert.get("timestamp", "")
    if isinstance(ts, str) and len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
        return ts[:10]
    return datetime.now(UTC).date().isoformat()


def dispatch(alert: dict[str, Any], output_dir: Path | str) -> None:
    """Write an alert to disk and append to the dispatch log.

    Writes to `output_dir/{YYYY-MM-DD}/...` where the date is derived from
    the alert's timestamp. This prevents file pile-up over multi-day runs
    and matches the design spec.

    Idempotent: if the alert file already exists, skip writing and
    do not append a duplicate log entry.

    Args:
        alert: Complete alert dict (must contain "alert_id"; uses "timestamp"
            and "department" if present).
        output_dir: Root directory to write files into (date subdirs created
            as needed).
    """
    output_dir = Path(output_dir)
    date_dir = output_dir / _extract_date_partition(alert)
    date_dir.mkdir(parents=True, exist_ok=True)

    alert_id = alert["alert_id"]
    alert_file = date_dir / f"{alert_id}.json"

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
        "dispatched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "simulated",
    }

    log_file = date_dir / "dispatch_log.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    logger.info(
        "alert_dispatch: SENT alert_id=%s domain=%s severity=%s -> %s",
        alert_id,
        alert.get("domain", "?"),
        alert.get("severity", "?"),
        alert.get("department", "?"),
    )
