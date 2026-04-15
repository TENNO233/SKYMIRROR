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

from skymirror.tools.alert.lta_lookup import lookup_lta_events  # noqa: E402


def load_alerts(alert_dir: Path) -> list[dict[str, Any]]:
    """Load all alert JSON files from a directory (skip non-alert files)."""
    alerts: list[dict[str, Any]] = []
    for path in sorted(alert_dir.glob("*.json")):
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

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_alerts": len(alerts),
        "corroborated": corroborated,
        "partially_matched": partially_matched,
        "uncorroborated": uncorroborated,
        "api_unavailable": api_unavailable,
        "corroboration_rate": round(corroboration_rate, 3),
        "per_alert_details": per_alert_details,
    }


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
