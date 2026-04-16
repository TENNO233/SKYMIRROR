"""Alert Generation Agent — Orchestration Entry Point

Tools
-----
- ``skymirror.tools.alert.classification`` : LLM-based event classification
- ``skymirror.tools.alert.rendering``      : template-based alert dict assembly
- ``skymirror.tools.alert.dispatcher``     : simulated file-based dispatch
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from skymirror.tools.alert.classification import classify
from skymirror.tools.alert.constants import DOMAIN_MAP
from skymirror.tools.alert.dispatcher import dispatch
from skymirror.tools.alert.lta_lookup import lookup_lta_events
from skymirror.tools.alert.rendering import render_alert

logger = logging.getLogger(__name__)

_CAMERA_ID_RE = re.compile(r"cam(\d+)")


def _extract_camera_id(image_path: str) -> str | None:
    """Extract camera ID from image path, e.g. 'cam4798_...' -> '4798'."""
    m = _CAMERA_ID_RE.search(image_path)
    return m.group(1) if m else None


def generate_alerts(
    expert_results: dict[str, Any],
    image_path: str,
    rag_citations: list[dict[str, Any]],
    output_dir: Path | str = "data/alerts",
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate and dispatch alerts from expert analysis results.

    Called by OA when it determines alerting is needed. This function
    contains zero business logic — it only sequences tool calls.

    Args:
        expert_results: Merged dict from activated experts.
            ``{"order_expert": {"findings": [...], "severity": "high", ...}, ...}``
        image_path: Source camera frame path.
        rag_citations: RAG references from expert analysis (passed through
            to alert for XAI source attribution).
        output_dir: Directory for alert JSON files and dispatch log.
        metadata: Optional diagnostic context from OA (not processed).

    Returns:
        List of generated alert dicts (empty list if no actionable findings).
    """
    if not expert_results:
        logger.info("alert_manager: No expert results provided; returning empty.")
        return []

    logger.info(
        "alert_manager: Processing results from %d expert(s): %s",
        len(expert_results),
        list(expert_results.keys()),
    )

    alerts: list[dict[str, Any]] = []

    for expert_name, expert_data in expert_results.items():
        findings = expert_data.get("findings", [])
        if not findings:
            logger.info("alert_manager: Skipping %s (no findings).", expert_name)
            continue

        domain = DOMAIN_MAP.get(expert_name, "unknown")
        expert_severity = expert_data.get("severity", "medium")

        # Tool 1: Classify
        classification = classify(
            domain=domain,
            findings=findings,
            expert_severity=expert_severity,
        )

        # Tool 2: LTA corroboration (independent official data)
        camera_id = _extract_camera_id(image_path)
        corroboration = lookup_lta_events(camera_id, domain) if camera_id else None

        # Tool 3: Render
        alert = render_alert(
            expert_name=expert_name,
            classification=classification,
            findings=findings,
            regulations=rag_citations,
            image_path=image_path,
            corroboration=corroboration,
        )

        # Tool 4: Dispatch
        dispatch(alert, output_dir=output_dir)

        alerts.append(alert)

    logger.info("alert_manager: Generated %d alert(s).", len(alerts))
    return alerts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "alert_expert_results.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="skymirror.agents.alert_manager",
        description="Run the SKYMIRROR Alert Generation Agent on sample data.",
    )
    parser.add_argument(
        "--fixture",
        choices=["single_expert", "multi_expert", "empty_findings"],
        default="single_expert",
        help="Which test fixture scenario to run (default: single_expert).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to a custom JSON file with expert_results, image_path, rag_citations.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/alerts"),
        help="Directory for alert output files (default: data/alerts).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)

    if args.input:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        if not _FIXTURES_PATH.exists():
            print(f"ERROR: Fixture file not found: {_FIXTURES_PATH}", file=sys.stderr)
            return 1
        all_fixtures = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
        data = all_fixtures[args.fixture]

    alerts = generate_alerts(
        expert_results=data["expert_results"],
        image_path=data["image_path"],
        rag_citations=data.get("rag_citations", []),
        output_dir=args.output_dir,
    )

    print(f"\n{'=' * 60}")
    print(f"Alert Generation Agent — {len(alerts)} alert(s) generated")
    print(f"{'=' * 60}")
    for i, alert in enumerate(alerts, 1):
        print(f"\n--- Alert {i} ---")
        print(json.dumps(alert, indent=2, ensure_ascii=False))

    if alerts:
        print(f"\nFiles written to: {args.output_dir}/")
    else:
        print("\nNo alerts generated (no actionable findings).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
