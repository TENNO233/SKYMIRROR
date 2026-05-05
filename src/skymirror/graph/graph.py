"""
graph.py - Unified LangGraph entrypoint for SKYMIRROR.

Studio should show both workflow families on one canvas:

    START
      |
      v
  workflow_router
      | frame
      +--> image_guardrail --(blocked)--> END
      |       | (allowed)
      |       +--> vlm_agent --> validator_agent --> orchestrator_agent
      |                                             | dispatch / evaluate
      |                                             v
      |                                 order_expert / safety_expert /
      |                                 environment_expert / alert_manager / END
      |
      | report
      +--> report_generator --> END

The report generator remains logically distinct from the per-frame path, but it
is registered in the same top-level graph so LangGraph Studio renders it on the
same canvas.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from skymirror.agents.alert_manager import alert_manager_node
from skymirror.agents.experts import (
    environment_expert_node,
    order_expert_node,
    safety_expert_node,
)
from skymirror.agents.orchestrator import orchestrator_node
from skymirror.agents.report_generator import generate_report
from skymirror.agents.validator import validator_agent_node
from skymirror.agents.vlm_agent import image_guardrail_node, vlm_agent_node
from skymirror.graph.edges import route_after_guardrail, route_from_orchestrator
from skymirror.graph.state import SkymirrorState
from skymirror.tools.daily_report.loader import yesterday_sgt

logger = logging.getLogger(__name__)

_FRAME_PIPELINE = "frame_pipeline"
_REPORT_PIPELINE = "report_pipeline"
_LEGACY_FRAME_PIPELINE = "legacy_frame_pipeline"


def _stub_vlm_agent(state: SkymirrorState) -> dict[str, Any]:
    """Compatibility wrapper retained for older graph tests."""
    return vlm_agent_node(state)


def legacy_text_adapter_node(state: SkymirrorState) -> dict[str, Any]:
    """Adapt legacy `vlm_text` outputs into the validated-text field."""
    text = str(state.get("vlm_text", "")).strip()
    return {
        "validated_text": text,
        "validated_signals": {},
        "validated_scene": {},
    }


def legacy_frame_compat_node(state: SkymirrorState) -> dict[str, Any]:
    """Execute the old text-first expert flow used by legacy graph tests."""

    def _mark_legacy_alert_urgent(alert: Any, *, has_urgent_expert: bool) -> dict[str, Any]:
        base_alert = dict(alert) if isinstance(alert, dict) else {"value": alert}
        base_alert["urgent"] = bool(base_alert.get("urgent", False)) or has_urgent_expert
        return base_alert

    working_state: dict[str, Any] = dict(state)
    working_state.setdefault("metadata", {})
    working_state.setdefault("expert_results", {})
    working_state.setdefault("alerts", [])

    vlm_patch = _stub_vlm_agent(working_state)
    if isinstance(vlm_patch, dict):
        working_state.update(vlm_patch)

    validated_text = (
        str(working_state.get("validated_text", "")).strip()
        or str(working_state.get("vlm_text", "")).strip()
    )
    working_state["validated_text"] = validated_text
    working_state.setdefault("validated_signals", {})
    working_state.setdefault("validated_scene", {})

    for expert_node in (order_expert_node, safety_expert_node, environment_expert_node):
        patch = expert_node(working_state)
        if isinstance(patch.get("expert_results"), dict):
            working_state["expert_results"] = {
                **dict(working_state.get("expert_results") or {}),
                **dict(patch["expert_results"]),
            }
        if isinstance(patch.get("metadata"), dict):
            merged_metadata = dict(working_state.get("metadata") or {})
            for key, value in dict(patch["metadata"]).items():
                if isinstance(value, dict) and isinstance(merged_metadata.get(key), dict):
                    merged_metadata[key] = {**dict(merged_metadata[key]), **value}
                else:
                    merged_metadata[key] = value
            working_state["metadata"] = merged_metadata

    alert_patch = alert_manager_node(working_state)
    if isinstance(alert_patch.get("alerts"), list):
        has_urgent_expert = any(
            bool(result.get("urgent"))
            for result in dict(working_state.get("expert_results") or {}).values()
            if isinstance(result, dict)
        )
        working_state["alerts"] = [
            _mark_legacy_alert_urgent(alert, has_urgent_expert=has_urgent_expert)
            for alert in list(alert_patch["alerts"])
        ]
    if isinstance(alert_patch.get("metadata"), dict):
        merged_metadata = dict(working_state.get("metadata") or {})
        for key, value in dict(alert_patch["metadata"]).items():
            if isinstance(value, dict) and isinstance(merged_metadata.get(key), dict):
                merged_metadata[key] = {**dict(merged_metadata[key]), **value}
            else:
                merged_metadata[key] = value
        working_state["metadata"] = merged_metadata

    return working_state


def _resolve_target_date(raw_value: object) -> date:
    if isinstance(raw_value, date):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        return date.fromisoformat(raw_value)
    return yesterday_sgt()


def report_generator_node(state: SkymirrorState) -> dict[str, Any]:
    """Run the daily report generator and write the output path into state."""
    target_date = _resolve_target_date(state.get("target_date"))
    oa_log_dir = Path(str(state.get("oa_log_dir", "data/oa_log")))
    output_dir = Path(str(state.get("output_dir", "data/reports")))

    report_path = generate_report(
        target_date=target_date,
        oa_log_dir=oa_log_dir,
        output_dir=output_dir,
    )

    logger.info(
        "report_generator_node: Generated daily report for %s -> %s",
        target_date.isoformat(),
        report_path,
    )
    return {
        "report_path": str(report_path),
        "metadata": {
            "report_generator": {
                "target_date": target_date.isoformat(),
                "oa_log_dir": str(oa_log_dir),
                "output_dir": str(output_dir),
            }
        },
    }


def workflow_router_node(state: SkymirrorState) -> dict[str, Any]:
    """Record which top-level workflow is about to run."""
    workflow_mode = str(state.get("workflow_mode", "frame")).strip().lower() or "frame"
    return {
        "metadata": {
            "workflow_router": {
                "workflow_mode": workflow_mode,
            }
        }
    }


def route_from_workflow_mode(state: SkymirrorState) -> str:
    """Choose the frame-analysis path or the report-generation path."""
    if "workflow_mode" not in state:
        return _LEGACY_FRAME_PIPELINE
    workflow_mode = str(state.get("workflow_mode", "frame")).strip().lower()
    if workflow_mode == "report":
        return _REPORT_PIPELINE
    return _FRAME_PIPELINE


def _build_graph() -> StateGraph:
    """Construct the unified SKYMIRROR graph for Studio and runtime use."""
    graph = StateGraph(SkymirrorState)

    graph.add_node(
        "workflow_router",
        workflow_router_node,
        destinations={
            "image_guardrail": "frame",
            "report_generator": "report",
        },
    )
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("legacy_frame_compat", legacy_frame_compat_node)
    graph.add_node(
        "image_guardrail",
        image_guardrail_node,
        destinations={
            "vlm_agent": "allowed",
            END: "blocked",
        },
    )
    graph.add_node("vlm_agent", _stub_vlm_agent)
    graph.add_node("validator_agent", validator_agent_node)
    graph.add_node(
        "orchestrator_agent",
        orchestrator_node,
        destinations={
            "order_expert": "dispatch",
            "safety_expert": "dispatch",
            "environment_expert": "dispatch",
            "alert_manager": "alert",
            END: "finish",
        },
    )
    graph.add_node("order_expert", order_expert_node)
    graph.add_node("safety_expert", safety_expert_node)
    graph.add_node("environment_expert", environment_expert_node)
    graph.add_node("alert_manager", alert_manager_node)

    graph.add_edge(START, "workflow_router")
    graph.add_conditional_edges(
        source="workflow_router",
        path=route_from_workflow_mode,
        path_map={
            _FRAME_PIPELINE: "image_guardrail",
            _REPORT_PIPELINE: "report_generator",
            _LEGACY_FRAME_PIPELINE: "legacy_frame_compat",
        },
    )

    graph.add_edge("report_generator", END)
    graph.add_edge("legacy_frame_compat", END)

    graph.add_conditional_edges(
        source="image_guardrail",
        path=route_after_guardrail,
        path_map={"vlm_agent": "vlm_agent", "end_pipeline": END},
    )

    graph.add_edge("vlm_agent", "validator_agent")
    graph.add_edge("validator_agent", "orchestrator_agent")

    graph.add_conditional_edges(
        source="orchestrator_agent",
        path=route_from_orchestrator,
        path_map={"alert_manager": "alert_manager", "finish": END},
    )

    graph.add_edge("order_expert", "orchestrator_agent")
    graph.add_edge("safety_expert", "orchestrator_agent")
    graph.add_edge("environment_expert", "orchestrator_agent")
    graph.add_edge("alert_manager", END)

    return graph


_graph = _build_graph()

# Unified compiled application.
app = _graph.compile()

logger.info("SKYMIRROR unified graph compiled successfully.")
