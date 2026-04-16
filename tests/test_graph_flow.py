from __future__ import annotations

from skymirror.graph import graph as graph_module


def _initial_state() -> dict[str, object]:
    return {
        "image_path": "frame.jpg",
        "guardrail_result": {},
        "vlm_outputs": {},
        "validated_text": "",
        "active_experts": [],
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
        return {"vlm_outputs": {"gemini": "Cars are stopped at a junction."}}

    def _qwen(_state):
        calls.append("qwen")
        return {"vlm_outputs": {"qwen": "Vehicles wait at an intersection."}}

    def _validator(_state):
        calls.append("validator")
        return {"validated_text": "Cars are stopped at a junction."}

    monkeypatch.setattr(graph_module, "image_guardrail_node", _guardrail)
    monkeypatch.setattr(graph_module, "gemini_vlm_node", _gemini)
    monkeypatch.setattr(graph_module, "qwen_vlm_node", _qwen)
    monkeypatch.setattr(graph_module, "validator_agent_node", _validator)

    app = graph_module._build_graph().compile()
    final_state = app.invoke(_initial_state())

    assert "guardrail" in calls
    assert "gemini" in calls
    assert "qwen" in calls
    assert calls.count("validator") == 1
    assert final_state["vlm_outputs"]["gemini"] == "Cars are stopped at a junction."
    assert final_state["vlm_outputs"]["qwen"] == "Vehicles wait at an intersection."
    assert final_state["validated_text"] == "Cars are stopped at a junction."


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
        return {"vlm_outputs": {"gemini": "should not run"}}

    def _qwen(_state):
        calls.append("qwen")
        return {"vlm_outputs": {"qwen": "should not run"}}

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
