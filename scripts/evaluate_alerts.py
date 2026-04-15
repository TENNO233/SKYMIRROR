"""Batch evaluation: compare Alert Agent output vs LTA DataMall ground truth.

Usage:
    python scripts/evaluate_alerts.py --alert-dir output/ --radius 500 --output eval_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as script from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from skymirror.tools.alert.lta_lookup import (  # noqa: E402
    _haversine_m,
    fetch_lta_events,
    lookup_lta_events,
    resolve_camera_location,
)
from skymirror.tools.alert.constants import LTA_ALL_ENDPOINTS  # noqa: E402


def load_alerts(alert_dir: Path) -> list[dict[str, Any]]:
    """Load all alert JSON files from a directory tree (skip non-alert files).

    Recurses into subdirectories — supports both flat (legacy) and
    date-partitioned (`{date}/{alert_id}.json`) layouts transparently.
    """
    alerts: list[dict[str, Any]] = []
    for path in sorted(alert_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "alert_id" in data:
                alerts.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return alerts


def _extract_camera_id(image_path: str) -> str | None:
    """Extract camera ID from image path."""
    import re
    m = re.search(r"cam(\d+)", image_path)
    return m.group(1) if m else None


def evaluate_alerts(
    alert_dir: Path,
    radius_m: float = 500.0,
) -> dict[str, Any]:
    """Run evaluation on all alerts in a directory.

    For alerts without existing lta_corroboration, queries LTA API to backfill.
    Returns a summary report dict.
    """
    alerts = load_alerts(alert_dir)

    corroborated = 0
    partially_matched = 0
    uncorroborated = 0
    api_unavailable = 0
    per_alert_details: list[dict[str, Any]] = []

    for alert in alerts:
        lta = alert.get("lta_corroboration")

        # Backfill if needed
        if lta is None:
            camera_id = _extract_camera_id(alert.get("image_path", ""))
            if camera_id:
                result = lookup_lta_events(camera_id, alert.get("domain", "unknown"), radius_m)
                if result.api_available:
                    lta = {
                        "api_available": True,
                        "matches": [
                            {
                                "event_type": m.event.event_type,
                                "description": m.event.description,
                                "distance_m": m.distance_m,
                                "match_type": m.match_type,
                                "source_api": m.event.source_api,
                            }
                            for m in result.matches
                        ],
                        "match_summary": {
                            "total": len(result.matches),
                            "location_and_domain": sum(
                                1 for m in result.matches if m.match_type == "location_and_domain"
                            ),
                            "location_only": sum(
                                1 for m in result.matches if m.match_type == "location_only"
                            ),
                        },
                    }

        # Classify result
        if lta is None or not lta.get("api_available", False):
            api_unavailable += 1
            status = "api_unavailable"
        elif any(m.get("match_type") == "location_and_domain" for m in lta.get("matches", [])):
            corroborated += 1
            status = "corroborated"
        elif lta.get("matches"):
            partially_matched += 1
            status = "partially_matched"
        else:
            uncorroborated += 1
            status = "uncorroborated"

        per_alert_details.append({
            "alert_id": alert.get("alert_id"),
            "domain": alert.get("domain"),
            "status": status,
            "match_count": len(lta.get("matches", [])) if lta else 0,
        })

    evaluable = len(alerts) - api_unavailable
    corroboration_rate = (corroborated / evaluable) if evaluable > 0 else 0.0

    # Reverse lookup: LTA events within radius of any covered camera that
    # were NOT captured by any alert. Signals potentially missed events.
    undetected = _find_undetected_events(alerts, radius_m)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_alerts": len(alerts),
        "corroborated": corroborated,
        "partially_matched": partially_matched,
        "uncorroborated": uncorroborated,
        "api_unavailable": api_unavailable,
        "corroboration_rate": round(corroboration_rate, 3),
        "lta_undetected": undetected,
        "per_alert_details": per_alert_details,
    }


def _find_undetected_events(
    alerts: list[dict[str, Any]],
    radius_m: float,
) -> list[dict[str, Any]]:
    """Find LTA events within radius of any covered camera that no alert matched.

    Uses (source_api, description) as event identity — two events from the same
    endpoint with the same message describe the same incident.

    Returns empty list if LTA API unavailable (graceful degradation).
    """
    # Collect unique camera_ids from the alert set
    camera_ids: set[str] = set()
    for alert in alerts:
        cid = _extract_camera_id(alert.get("image_path", ""))
        if cid:
            camera_ids.add(cid)

    if not camera_ids:
        return []

    # Resolve each camera to (lat, lng)
    camera_locations: dict[str, tuple[float, float]] = {}
    for cid in camera_ids:
        loc = resolve_camera_location(cid)
        if loc is not None:
            camera_locations[cid] = loc

    if not camera_locations:
        return []

    # Collect all LTA events across all endpoints (single pass)
    all_events = []
    for endpoint in LTA_ALL_ENDPOINTS:
        all_events.extend(fetch_lta_events(endpoint))

    if not all_events:
        return []

    # Build the set of events already matched by any alert
    matched_keys: set[tuple[str, str]] = set()
    for alert in alerts:
        lta = alert.get("lta_corroboration")
        if not lta:
            continue
        for m in lta.get("matches", []):
            key = (m.get("source_api", ""), m.get("description", ""))
            matched_keys.add(key)

    # Find events near any camera but not matched
    undetected: list[dict[str, Any]] = []
    for event in all_events:
        # Find nearest camera within radius (if any)
        nearest_cid = None
        nearest_dist = float("inf")
        for cid, (cam_lat, cam_lng) in camera_locations.items():
            dist = _haversine_m(cam_lat, cam_lng, event.latitude, event.longitude)
            if dist <= radius_m and dist < nearest_dist:
                nearest_cid = cid
                nearest_dist = dist

        if nearest_cid is None:
            continue  # event not near any covered camera

        key = (event.source_api, event.description)
        if key in matched_keys:
            continue  # already captured by some alert

        undetected.append({
            "event_type": event.event_type,
            "description": event.description,
            "source_api": event.source_api,
            "location": {"lat": event.latitude, "lng": event.longitude},
            "nearest_camera": nearest_cid,
            "distance_m": round(nearest_dist, 1),
        })

    return undetected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Alert Agent output vs LTA ground truth.")
    parser.add_argument("--alert-dir", type=Path, required=True, help="Directory with alert JSON files")
    parser.add_argument("--radius", type=float, default=500.0, help="Match radius in metres (default: 500)")
    parser.add_argument("--output", type=Path, default=None, help="Output file for report JSON")
    args = parser.parse_args(argv)

    if not args.alert_dir.is_dir():
        print(f"ERROR: {args.alert_dir} is not a directory.", file=sys.stderr)
        return 1

    report = evaluate_alerts(args.alert_dir, radius_m=args.radius)

    report_json = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(report_json, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(report_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
