"""
orchestrator.py - LLM-based Supervisor node for SKYMIRROR.

The Orchestrator is the central hub of the pipeline. It is called twice
per frame:

  Pass 1 — DISPATCH MODE (expert_results is empty)
      Reads validated_text and validated_signals.
      Uses an LLM to decide which experts are relevant.
      Writes next_nodes = [<expert names>].

  Pass 2 — EVALUATE MODE (expert_results is populated)
      Reads the accumulated expert findings.
      Uses an LLM to decide whether alerts are needed.
      Writes next_nodes = ["alert_manager"] or ["FINISH"].

Infinite-loop guard
-------------------
Both passes apply hard code-level filters on the LLM's output:
  • Dispatch pass strips any non-expert names; falls back to all experts.
  • Evaluate pass strips any expert names; falls back to "alert_manager".
This prevents mode-violating LLM responses from creating routing cycles.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from skymirror.agents.prompts import (
    ORCHESTRATOR_PROMPT_ID,
    ORCHESTRATOR_SYSTEM_PROMPT,
    PROMPT_VERSION,
)
from skymirror.graph.state import SkymirrorState
from skymirror.tools import llm_factory
from skymirror.tools.governance import model_allowed, policy_version

logger = logging.getLogger(__name__)

_EXPERT_NODES: frozenset[str] = frozenset({"order_expert", "safety_expert", "environment_expert"})
_ALL_EXPERTS: list[str] = sorted(_EXPERT_NODES)  # deterministic order


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------


class OrchestratorDecision(BaseModel):
    """LLM-structured routing decision from the Orchestrator."""

    next_nodes: list[
        Literal[
            "order_expert",
            "safety_expert",
            "environment_expert",
            "alert_manager",
            "FINISH",
        ]
    ] = Field(
        description=(
            "DISPATCH MODE: one or more expert node names. "
            "EVALUATE MODE: exactly one of 'alert_manager' or 'FINISH'."
        )
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of the routing decision (logged for observability).",
    )


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_dispatch_prompt(
    validated_scene: dict[str, Any],
    validated_text: str,
    validated_signals: dict[str, Any],
) -> str:
    scene_block = (
        json.dumps(validated_scene, indent=2)
        if validated_scene
        else "(no validated scene JSON available)"
    )
    signals_block = (
        json.dumps(validated_signals, indent=2)
        if validated_signals
        else "(no structured signals available)"
    )
    return (
        "## DISPATCH MODE\n\n"
        "expert_results: (empty - no experts have run yet)\n\n"
        "Validated scene JSON:\n"
        f"{scene_block}\n\n"
        "Validated traffic-scene description:\n"
        f"{validated_text or '(empty)'}\n\n"
        "Structured signals extracted by the validator:\n"
        f"{signals_block}\n\n"
        "Select which expert agents should analyze this scene. "
        "Return at least one expert node name."
    )


def _build_evaluate_prompt(expert_results: dict[str, Any]) -> str:
    results_block = json.dumps(expert_results, indent=2, default=str)
    return (
        "## EVALUATE MODE\n\n"
        "Expert agents have completed their analysis. "
        "Review their findings and decide whether alerts are needed.\n\n"
        f"expert_results:\n{results_block}\n\n"
        "Return ['alert_manager'] if any expert matched issues, "
        "or ['FINISH'] if the frame is clean."
    )


# ---------------------------------------------------------------------------
# LLM invocation
# ---------------------------------------------------------------------------


def _invoke_orchestrator_llm(state: SkymirrorState) -> OrchestratorDecision:
    from langchain_core.messages import HumanMessage, SystemMessage

    expert_results = state.get("expert_results", {})

    if not expert_results:
        user_content = _build_dispatch_prompt(
            validated_scene=dict(state.get("validated_scene") or {}),
            validated_text=state.get("validated_text", ""),
            validated_signals=dict(state.get("validated_signals") or {}),
        )
    else:
        user_content = _build_evaluate_prompt(expert_results)

    llm = llm_factory.get_llm(temperature=0.0)
    model_name = getattr(llm, "model_name", getattr(llm, "model", ""))
    if model_name and not model_allowed(str(model_name), capability="orchestrator"):
        raise RuntimeError(f"Model '{model_name}' is not allowed for orchestrator by policy.")
    structured_llm = llm.with_structured_output(OrchestratorDecision)
    return structured_llm.invoke(
        [
            SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]
    )


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


def orchestrator_node(state: SkymirrorState) -> dict[str, Any]:
    """
    LangGraph node: LLM-based supervisor that controls expert dispatch and
    alert triggering.

    Returns a state patch containing:
      • next_nodes      — routing decision for route_from_orchestrator
      • active_experts  — set only in dispatch pass (for observability)
      • metadata        — diagnostics under the "orchestrator" key
    """
    expert_results = state.get("expert_results", {})
    is_dispatch = not expert_results
    mode = "dispatch" if is_dispatch else "evaluate"

    logger.info(
        "orchestrator_agent [%s]: expert_results keys=%s",
        mode,
        list(expert_results.keys()),
    )

    # --- LLM call (with fallback) -------------------------------------------
    try:
        decision = _invoke_orchestrator_llm(state)
        raw_nodes: list[str] = list(decision.next_nodes)
        logger.info(
            "orchestrator_agent [%s]: LLM -> next_nodes=%s reasoning=%r",
            mode,
            raw_nodes,
            decision.reasoning,
        )
    except Exception as exc:
        logger.warning(
            "orchestrator_agent [%s]: LLM call failed (%s) - applying safety fallback.",
            mode,
            exc,
        )
        raw_nodes = _ALL_EXPERTS if is_dispatch else ["alert_manager"]

    # --- Hard safety filter: enforce mode constraints -----------------------
    # This prevents LLM hallucinations from causing infinite routing loops.
    if is_dispatch:
        next_nodes = [n for n in raw_nodes if n in _EXPERT_NODES]
        if not next_nodes:
            logger.warning(
                "orchestrator_agent [dispatch]: No valid experts in LLM output %s "
                "- falling back to all experts.",
                raw_nodes,
            )
            next_nodes = _ALL_EXPERTS
    else:
        valid_eval: frozenset[str] = frozenset({"alert_manager", "FINISH"})
        next_nodes = [n for n in raw_nodes if n in valid_eval]
        if not next_nodes:
            logger.warning(
                "orchestrator_agent [evaluate]: No valid terminal decision in LLM output %s "
                "- falling back to alert_manager.",
                raw_nodes,
            )
            next_nodes = ["alert_manager"]

    logger.info("orchestrator_agent [%s]: final next_nodes=%s", mode, next_nodes)

    patch: dict[str, Any] = {
        "next_nodes": next_nodes,
        "metadata": {
            "orchestrator": {
                "mode": mode,
                "next_nodes": next_nodes,
            },
            "models": {
                "orchestrator": {
                    "model_name": os.getenv("OPENAI_AGENT_MODEL", "gpt-5.4-mini"),
                    "provider": os.getenv("LLM_PROVIDER", "openai"),
                }
            },
            "prompts": {
                "orchestrator": {
                    "prompt_id": ORCHESTRATOR_PROMPT_ID,
                    "prompt_version": PROMPT_VERSION,
                }
            },
            "policies": {
                "orchestrator": {
                    "policy_version": policy_version(),
                }
            },
        },
    }

    # active_experts is only meaningful in dispatch pass
    if is_dispatch:
        patch["active_experts"] = next_nodes

    return patch
