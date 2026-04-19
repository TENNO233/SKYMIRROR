"""
Agent module exports.

The package avoids eager imports so individual agent modules can be imported
without pulling in optional runtime dependencies from unrelated modules.
"""
from typing import Any

from skymirror.agents.alert_manager import alert_manager_node
from skymirror.agents.experts import (
    environment_expert_node,
    order_expert_node,
    safety_expert_node,
)
from skymirror.agents.validator import validator_agent_node
from skymirror.agents.alert_manager import generate_alerts
from skymirror.agents.vlm_agent import image_guardrail_node, vlm_agent_node

__all__ = [
    "image_guardrail_node",
    "vlm_agent_node",
    "validator_agent_node",
    "order_expert_node",
    "safety_expert_node",
    "environment_expert_node",
    "generate_alerts",
]


def __getattr__(name: str) -> Any:
    """Lazily import agent entry points on demand."""
    if name == "vlm_agent_node":
        from skymirror.agents.vlm_agent import vlm_agent_node

        return vlm_agent_node
    if name == "validator_agent_node":
        from skymirror.agents.validator import validator_agent_node

        return validator_agent_node
    if name == "order_expert_node":
        from skymirror.agents.experts import order_expert_node

        return order_expert_node
    if name == "safety_expert_node":
        from skymirror.agents.experts import safety_expert_node

        return safety_expert_node
    if name == "environment_expert_node":
        from skymirror.agents.experts import environment_expert_node

        return environment_expert_node
    if name == "alert_manager_node":
        from skymirror.agents.alert_manager import alert_manager_node

        return alert_manager_node
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
