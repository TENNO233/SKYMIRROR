"""
alert_manager.py - Alert synthesis node and standalone CLI for SKYMIRROR.

LangGraph node
--------------
``alert_manager_node(state)`` is the terminal node in the pipeline.
It reads ``state["expert_results"]``, calls ``generate_alerts``, and writes
the resulting list back to ``state["alerts"]``.

Standalone CLI
--------------
Run directly for smoke-testing against fixture JSON:

    python -m skymirror.agents.alert_manager --fixture single_expert
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from skymirror.agents.prompts import ALERT_CLASSIFICATION_PROMPT_ID, PROMPT_VERSION
from skymirror.graph.state import SkymirrorState
from skymirror.tools.governance import lta_enabled, policy_version
from skymirror.tools.alert.classification import classify
from skymirror.tools.alert.constants import DOMAIN_MAP
from skymirror.tools.alert.dispatcher import dispatch
from skymirror.tools.alert.lta_lookup import lookup_lta_events
from skymirror.tools.alert.rendering import render_alert

logger = logging.getLogger(__name__)

_SEVERITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_CAMERA_ID_RE = re.compile(r"cam(\d+)")


def _extract_camera_id(image_path: str) -> str | None:
    """Extract camera ID from image path, e.g. 'cam4798_...' -> '4798'."""
    m = _CAMERA_ID_RE.search(image_path)
    return m.group(1) if m else None


def _expert_severity(scenarios: list[dict[str, Any]]) -> str:
    """Return the highest severity level across all scenarios in a result."""
    if not scenarios:
        return "low"
    return max(
        (s.get("severity", "low") for s in scenarios),
        key=lambda s: _SEVERITY_RANK.get(s, 0),
    )


def _normalize_scenarios(result: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = result.get("scenarios")
    if isinstance(scenarios, list):
        return [dict(item) for item in scenarios if isinstance(item, dict)]

    findings = result.get("findings")
    if not isinstance(findings, list):
        return []

    severity = str(result.get("severity", "medium"))
    confidence = result.get("confidence", "medium")
    normalized: list[dict[str, Any]] = []
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            continue
        normalized.append(
            {
                "name": f"legacy_finding_{index}",
                "reason": str(finding.get("description", "")).strip(),
                "confidence": confidence,
                "severity": severity,
                "evidence": list(finding.get("evidence", []))
                if isinstance(finding.get("evidence"), list)
                else [],
            }
        )
    return normalized


def _citations_from_result(
    result: dict[str, Any],
    fallback_citations: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    citations = result.get("citations")
    if isinstance(citations, list) and citations:
        return [dict(item) for item in citations if isinstance(item, dict)]
    return [dict(item) for item in (fallback_citations or []) if isinstance(item, dict)]


def generate_alerts(
    expert_results: dict[str, Any],
    image_path: str,
    rag_citations: list[dict[str, Any]] | None = None,
    output_dir: Path | str = "data/alerts",
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate and dispatch alerts from expert analysis results.

    Iterates over each activated expert's ``ExpertResult``, reads its
    ``scenarios`` list, builds a findings payload compatible with the
    classify / render / dispatch tool chain, and returns the complete list
    of generated alert dicts.

    Args:
        expert_results: Merged dict from activated experts.
            ``{"order_expert": ExpertResult, "safety_expert": ExpertResult, ...}``
        image_path: Source camera frame path.
        rag_citations: RAG references from expert analysis (passed through
            to alert for XAI source attribution).
        output_dir: Directory for alert JSON files and dispatch log.
        metadata: Optional diagnostic context (not processed, reserved for
            future observability use).

    Returns:
        List of generated alert dicts (empty list if no actionable findings).
    """
    if not expert_results:
        logger.info("alert_manager: No expert results provided; returning empty.")
        return []
    _ = metadata

    logger.info(
        "alert_manager: Processing results from %d expert(s): %s",
        len(expert_results),
        list(expert_results.keys()),
    )

    alerts: list[dict[str, Any]] = []

    for expert_name, result in expert_results.items():
        # ExpertResult stores detected issues under "scenarios"
        scenarios = _normalize_scenarios(result if isinstance(result, dict) else {})

        if not scenarios:
            logger.info("alert_manager: Skipping %s (no scenarios).", expert_name)
            continue

        domain = DOMAIN_MAP.get(expert_name, "unknown")
        expert_severity = _expert_severity(scenarios)

        # Build findings list in the shape expected by classify() and render_alert():
        # each entry needs at least a "description" key.
        findings: list[dict[str, Any]] = [
            {
                "description": s.get("reason", s.get("name", "")),
                "name": s.get("name", ""),
                "confidence": s.get("confidence", "medium"),
                "evidence": s.get("evidence", []),
            }
            for s in scenarios
        ]

        # Tool 1: LLM-based event classification
        classification = classify(
            domain=domain,
            findings=findings,
            expert_severity=expert_severity,
        )

        # Tool 2: LTA corroboration (independent official data feed)
        camera_id = _extract_camera_id(image_path)
        corroboration = None
        if camera_id and lta_enabled():
            corroboration = lookup_lta_events(camera_id, domain)

        # Tool 3: Template-based alert assembly
        alert = render_alert(
            expert_name=expert_name,
            classification=classification,
            findings=findings,
            regulations=_citations_from_result(
                result if isinstance(result, dict) else {},
                rag_citations,
            ),
            image_path=image_path,
            corroboration=corroboration,
        )

        # Tool 4: Write to disk and append to dispatch log
        dispatch(alert, output_dir=output_dir)

        alerts.append(alert)

    logger.info("alert_manager: Generated %d alert(s).", len(alerts))
    return alerts


def alert_manager_node(state: SkymirrorState) -> dict[str, Any]:
    """LangGraph node: synthesize expert results into structured alerts.

    Reads ``state["expert_results"]`` and ``state["image_path"]``, delegates
    to ``generate_alerts``, and returns ``{"alerts": [...]}`` for the state
    reducer to merge.

    When no experts were activated (clean frame), ``expert_results`` is empty
    and an empty alerts list is returned — no anomaly logged.
    """
    expert_results: dict[str, Any] = state.get("expert_results", {})
    image_path: str = state.get("image_path", "")

    if not expert_results:
        logger.info(
            "alert_manager_node: No expert results in state — no anomaly detected for %s.",
            image_path,
        )
        return {"alerts": []}

    alerts = generate_alerts(
        expert_results=expert_results,
        image_path=image_path,
        rag_citations=[],
        metadata=state.get("metadata", {}),
    )

    logger.info("alert_manager_node: Emitting %d alert(s) to state.", len(alerts))
    return {
        "alerts": alerts,
        "metadata": {
            "alert_manager": {
                "alerts_generated": len(alerts),
                "lta_lookup_enabled": lta_enabled(),
            },
            "models": {
                "alert_manager": {
                    "model_name": os.getenv("OPENAI_AGENT_MODEL", "gpt-5.4-mini"),
                    "provider": os.getenv("LLM_PROVIDER", "openai"),
                }
            },
            "prompts": {
                "alert_manager": {
                    "prompt_id": ALERT_CLASSIFICATION_PROMPT_ID,
                    "prompt_version": PROMPT_VERSION,
                }
            },
            "policies": {
                "alert_manager": {
                    "policy_version": policy_version(),
                }
            },
            "external_calls": {
                "lta_lookup": {
                    "status": "enabled" if lta_enabled() else "disabled",
                }
            },
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_FIXTURES_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "alert_expert_results.json"
)


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
