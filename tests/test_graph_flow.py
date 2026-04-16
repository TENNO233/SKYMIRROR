from __future__ import annotations

from skymirror.graph import graph as graph_module


def _initial_state() -> dict[str, object]:
    return {
        "workflow_mode": "frame",
        "image_path": "frame.jpg",
        "target_date": "",
        "oa_log_dir": "",
        "output_dir": "",
        "report_path": "",
        "guardrail_result": {},
        "vlm_outputs": {},
        "validated_scene": {},
        "validated_text": "",
        "validated_signals": {},
        "active_experts": [],
        "next_nodes": [],
        "expert_results": {},
        "alerts": [],
        "metadata": {},
    }


def test_safe_graph_path_reaches_both_vlms_and_validator(monkeypatch) -> None:
    calls: list[str] = []

    def _guardrail(_state):
        calls.append("guardrail")
        return {
            "guardrail_result": {
                "allowed": True,
                "status": "allowed",
                "reason": "safe",
                "categories": [],
            },
            "metadata": {},
        }

    def _gemini(_state):
        calls.append("gemini")
        return {
            "vlm_outputs": {
                "gemini": {
                    "summary": "Cars are stopped at a junction.",
                    "direct_observations": ["Cars are stopped."],
                    "signals": {"vehicle_count": 2, "stopped_vehicle_count": 2},
                }
            }
        }

    def _qwen(_state):
        calls.append("qwen")
        return {
            "vlm_outputs": {
                "qwen": {
                    "summary": "Vehicles wait at an intersection.",
                    "direct_observations": ["Vehicles wait before the intersection."],
                    "signals": {"vehicle_count": 2, "stopped_vehicle_count": 2},
                }
            }
        }

    def _validator(_state):
        calls.append("validator")
        return {
            "validated_scene": {
                "normalized_description": "Cars are stopped at a junction.",
                "consensus_observations": ["Cars are stopped at the junction approach."],
                "signals": {"vehicle_count": 2, "stopped_vehicle_count": 2},
            },
            "validated_text": "Cars are stopped at a junction.",
            "validated_signals": {"vehicle_count": 2, "stopped_vehicle_count": 2},
        }

    def _orchestrator(_state):
        calls.append("orchestrator")
        return {"next_nodes": ["FINISH"], "metadata": {}}

    monkeypatch.setattr(graph_module, "image_guardrail_node", _guardrail)
    monkeypatch.setattr(graph_module, "gemini_vlm_node", _gemini)
    monkeypatch.setattr(graph_module, "qwen_vlm_node", _qwen)
    monkeypatch.setattr(graph_module, "validator_agent_node", _validator)
    monkeypatch.setattr(graph_module, "orchestrator_node", _orchestrator)

    app = graph_module._build_graph().compile()
    final_state = app.invoke(_initial_state())

    assert "guardrail" in calls
    assert "gemini" in calls
    assert "qwen" in calls
    assert calls.count("validator") == 1
    assert calls.count("orchestrator") == 1
    assert final_state["vlm_outputs"]["gemini"]["summary"] == "Cars are stopped at a junction."
    assert final_state["vlm_outputs"]["qwen"]["summary"] == "Vehicles wait at an intersection."
    assert final_state["validated_text"] == "Cars are stopped at a junction."
    assert final_state["validated_signals"]["vehicle_count"] == 2


def test_blocked_graph_path_skips_vlms_and_validator(monkeypatch) -> None:
    calls: list[str] = []

    def _guardrail(_state):
        calls.append("guardrail")
        return {
            "guardrail_result": {
                "allowed": False,
                "status": "blocked",
                "reason": "unsafe image",
                "categories": ["guardrail_error"],
            }
        }

    def _gemini(_state):
        calls.append("gemini")
        return {"vlm_outputs": {"gemini": {"summary": "should not run"}}}

    def _qwen(_state):
        calls.append("qwen")
        return {"vlm_outputs": {"qwen": {"summary": "should not run"}}}

    def _validator(_state):
        calls.append("validator")
        return {"validated_text": "should not run"}

    monkeypatch.setattr(graph_module, "image_guardrail_node", _guardrail)
    monkeypatch.setattr(graph_module, "gemini_vlm_node", _gemini)
    monkeypatch.setattr(graph_module, "qwen_vlm_node", _qwen)
    monkeypatch.setattr(graph_module, "validator_agent_node", _validator)

    app = graph_module._build_graph().compile()
    final_state = app.invoke(_initial_state())

    assert calls == ["guardrail"]
    assert final_state["guardrail_result"]["status"] == "blocked"
    assert final_state["vlm_outputs"] == {}
    assert final_state["validated_text"] == ""


def test_report_mode_routes_to_report_generator_and_skips_frame_nodes(monkeypatch) -> None:
    calls: list[str] = []

    def _router(_state):
        calls.append("report_generator")
        return {
            "report_path": "data/reports/2026-04-15.md",
            "metadata": {"report_generator": {"target_date": "2026-04-15"}},
        }

    def _guardrail(_state):
        calls.append("guardrail")
        return {}

    def _gemini(_state):
        calls.append("gemini")
        return {}

    def _qwen(_state):
        calls.append("qwen")
        return {}

    def _validator(_state):
        calls.append("validator")
        return {}

    monkeypatch.setattr(graph_module, "report_generator_node", _router)
    monkeypatch.setattr(graph_module, "image_guardrail_node", _guardrail)
    monkeypatch.setattr(graph_module, "gemini_vlm_node", _gemini)
    monkeypatch.setattr(graph_module, "qwen_vlm_node", _qwen)
    monkeypatch.setattr(graph_module, "validator_agent_node", _validator)

    app = graph_module._build_graph().compile()
    final_state = app.invoke(
        {
            **_initial_state(),
            "workflow_mode": "report",
            "target_date": "2026-04-15",
            "oa_log_dir": "data/oa_log",
            "output_dir": "data/reports",
        }
    )

    assert calls == ["report_generator"]
    assert final_state["report_path"].endswith("2026-04-15.md")
    assert final_state["metadata"]["report_generator"]["target_date"] == "2026-04-15"
