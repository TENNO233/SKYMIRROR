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
from skymirror.agents.validator import validator_agent_node
from skymirror.agents.vlm_agent import image_guardrail_node, vlm_agent_node
from skymirror.agents.report_generator import generate_report
from skymirror.graph.edges import route_after_guardrail, route_from_orchestrator
from skymirror.graph.state import SkymirrorState
from skymirror.tools.daily_report.loader import yesterday_sgt

logger = logging.getLogger(__name__)

_FRAME_PIPELINE = "frame_pipeline"
_REPORT_PIPELINE = "report_pipeline"


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
    graph.add_node(
        "image_guardrail",
        image_guardrail_node,
        destinations={
            "vlm_agent": "allowed",
            END: "blocked",
        },
    )
    graph.add_node("vlm_agent", vlm_agent_node)
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
        },
    )

    graph.add_edge("report_generator", END)

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
