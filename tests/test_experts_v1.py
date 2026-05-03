from __future__ import annotations

from typing import Any

import pytest

from skymirror.agents.experts import (
    environment_expert_node,
    order_expert_node,
    safety_expert_node,
)


def _make_state(
    *,
    validated_text: str,
    validated_signals: dict[str, Any] | None = None,
    history_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "image_path": "frame.jpg",
        "validated_text": validated_text,
        "validated_signals": validated_signals or {},
        "history_context": history_context or [],
        "expert_results": {},
        "alerts": [],
    }


def _scenario_names(result: dict[str, Any]) -> set[str]:
    return {scenario["name"] for scenario in result["scenarios"]}


def test_order_detects_illegal_parking_without_obstruction() -> None:
    result = order_expert_node(
        _make_state(
            validated_text="a double parked sedan is stopped at the curb beside active traffic",
            validated_signals={
                "stopped_vehicle_count": 1,
                "blocked_lanes": 0,
            },
        )
    )["expert_results"]["order_expert"]

    assert result["matched"] is True
    assert _scenario_names(result) == {"illegal_parking"}
    assert result["urgent"] is False


def test_order_detects_obstruction_and_congestion() -> None:
    result = order_expert_node(
        _make_state(
            validated_text=(
                "a double parked truck is blocking lane one and causing heavy traffic "
                "congestion with a long queue"
            ),
            validated_signals={
                "stopped_vehicle_count": 1,
                "blocked_lanes": 1,
                "queueing": True,
                "vehicle_count": 12,
            },
        )
    )["expert_results"]["order_expert"]

    assert {"illegal_parking", "lane_obstruction", "congestion"} <= _scenario_names(result)


def test_order_detects_abnormal_queue_from_history() -> None:
    history_context = [
        {
            "validated_signals": {"queueing": True, "vehicle_count": 10},
            "expert_results": {},
        },
        {
            "validated_signals": {"queueing": True, "vehicle_count": 11},
            "expert_results": {},
        },
    ]
    result = order_expert_node(
        _make_state(
            validated_text="traffic remains in a long queue with heavy congestion",
            validated_signals={
                "queueing": True,
                "vehicle_count": 13,
                "blocked_lanes": 1,
            },
            history_context=history_context,
        )
    )["expert_results"]["order_expert"]

    abnormal_queue = next(
        scenario for scenario in result["scenarios"] if scenario["name"] == "abnormal_queue"
    )
    assert abnormal_queue["persistence"] in {"persistent", "worsening"}


def test_order_detects_vehicle_loitering_from_history() -> None:
    history_context = [
        {"validated_signals": {"stopped_vehicle_count": 1}, "expert_results": {}},
        {"validated_signals": {"stopped_vehicle_count": 1}, "expert_results": {}},
    ]
    result = order_expert_node(
        _make_state(
            validated_text="a vehicle remained stopped in the same roadside position",
            validated_signals={
                "stopped_vehicle_count": 1,
                "blocked_lanes": 0,
            },
            history_context=history_context,
        )
    )["expert_results"]["order_expert"]

    assert "vehicle_loitering" in _scenario_names(result)


def test_safety_detects_collision_and_sets_urgent() -> None:
    result = safety_expert_node(
        _make_state(
            validated_text=(
                "a suspected collision is visible with an ambulance arriving and vehicles "
                "blocking one lane"
            ),
            validated_signals={
                "collision_cue": True,
                "blocked_lanes": 1,
            },
        )
    )["expert_results"]["safety_expert"]

    collision = next(
        scenario
        for scenario in result["scenarios"]
        if scenario["name"] == "collision_or_suspected_collision"
    )
    assert collision["severity"] == "critical"
    assert result["urgent"] is True


def test_safety_detects_wrong_way_crossing_and_conflict_risk() -> None:
    result = safety_expert_node(
        _make_state(
            validated_text=(
                "a car is moving the wrong way while a pedestrian is crossing active traffic "
                "and nearby vehicles are swerving to avoid a near miss"
            ),
            validated_signals={
                "wrong_way_cue": True,
                "pedestrian_present": True,
                "dangerous_crossing_cue": True,
                "conflict_risk_cue": True,
            },
        )
    )["expert_results"]["safety_expert"]

    assert {
        "wrong_way",
        "dangerous_pedestrian_crossing",
        "vehicle_or_pedestrian_conflict_risk",
    } <= _scenario_names(result)
    assert result["urgent"] is True


def test_environment_detects_flooding_and_visibility_issues() -> None:
    result = environment_expert_node(
        _make_state(
            validated_text=(
                "standing water covers two lanes while fog creates low visibility across "
                "the intersection"
            ),
            validated_signals={
                "water_present": True,
                "low_visibility": True,
                "blocked_lanes": 2,
                "vehicle_count": 8,
            },
        )
    )["expert_results"]["environment_expert"]

    assert {
        "flooding",
        "low_visibility_or_abnormal_lighting",
    } <= _scenario_names(result)


def test_environment_detects_construction_and_road_obstacle() -> None:
    result = environment_expert_node(
        _make_state(
            validated_text=(
                "a construction zone with barricades is occupying one lane and debris is "
                "present on the roadway"
            ),
            validated_signals={
                "construction_present": True,
                "obstacle_present": True,
                "blocked_lanes": 1,
            },
        )
    )["expert_results"]["environment_expert"]

    assert {"construction_zone", "road_obstacle"} <= _scenario_names(result)


def test_expert_returns_explicit_no_issue_payload() -> None:
    result = order_expert_node(
        _make_state(
            validated_text="traffic appears normal and vehicles are moving steadily",
            validated_signals={"vehicle_count": 4},
        )
    )["expert_results"]["order_expert"]

    assert result["matched"] is False
    assert result["scenarios"] == []


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_graph_routes_multiple_experts_and_generates_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("langgraph")
    import skymirror.graph.graph as graph_module

    def fake_vlm_agent(_state: dict[str, Any]) -> dict[str, Any]:
        return {
            "vlm_text": (
                "a double parked truck is blocking one lane and causing heavy congestion. "
                "another vehicle is moving the wrong way near active traffic. "
                "standing water covers the intersection."
            )
        }

    monkeypatch.setattr(graph_module, "_stub_vlm_agent", fake_vlm_agent)
    app = graph_module._build_graph().compile()

    result = app.invoke(
        {
            "image_path": "frame.jpg",
            "history_context": [],
            "expert_results": {},
            "alerts": [],
        }
    )

    assert set(result["expert_results"]) == {
        "order_expert",
        "safety_expert",
        "environment_expert",
    }
    assert result["expert_results"]["safety_expert"]["urgent"] is True
    assert len(result["alerts"]) >= 3
    assert any(alert["urgent"] for alert in result["alerts"])
