"""Tests for Alert Generation Agent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def alert_fixtures(fixtures_dir: Path) -> dict:
    """Load alert test fixtures."""
    return json.loads((fixtures_dir / "alert_expert_results.json").read_text())


# ---------------------------------------------------------------------------
# Task 1: Constants
# ---------------------------------------------------------------------------

def test_domain_map_covers_all_experts():
    from skymirror.tools.alert.constants import DOMAIN_MAP
    assert DOMAIN_MAP["order_expert"] == "traffic"
    assert DOMAIN_MAP["safety_expert"] == "safety"
    assert DOMAIN_MAP["environment_expert"] == "environment"


def test_sub_type_map_has_other_for_each_domain():
    from skymirror.tools.alert.constants import SUB_TYPE_MAP
    for domain in ("traffic", "safety", "environment"):
        assert "other" in SUB_TYPE_MAP[domain]


def test_department_map_covers_all_domains():
    from skymirror.tools.alert.constants import DEPARTMENT_MAP
    assert "traffic" in DEPARTMENT_MAP
    assert "safety" in DEPARTMENT_MAP
    assert "environment" in DEPARTMENT_MAP
    # Values are non-empty strings
    for dept in DEPARTMENT_MAP.values():
        assert isinstance(dept, str) and len(dept) > 0


# ---------------------------------------------------------------------------
# Task 3: Classification
# ---------------------------------------------------------------------------

def test_classify_returns_valid_structure(mock_llm):
    from skymirror.tools.alert.classification import classify
    result = classify(
        domain="traffic",
        findings=[{"description": "Running red light", "confidence": 0.87}],
        expert_severity="high",
    )
    assert "sub_type" in result
    assert "severity" in result
    assert "message" in result
    assert result["severity"] in ("low", "medium", "high", "critical")


def test_classify_falls_back_on_llm_failure(monkeypatch):
    from skymirror.tools.alert import classification as cls_mod

    class _Broken:
        def with_structured_output(self, schema):
            return self
        def invoke(self, *_a, **_kw):
            raise RuntimeError("API down")

    monkeypatch.setattr(cls_mod, "_get_classification_llm", lambda: _Broken())

    result = cls_mod.classify(
        domain="traffic",
        findings=[{"description": "Running red light", "confidence": 0.87}],
        expert_severity="high",
    )
    assert result["sub_type"] == "other"
    assert result["severity"] == "high"  # falls back to expert_severity
    assert "Running red light" in result["message"]


def test_classify_forces_other_on_invalid_sub_type(monkeypatch):
    from skymirror.tools.alert import classification as cls_mod

    class _FakeClassification:
        sub_type: str = "INVALID_TYPE"
        severity: str = "medium"
        message: str = "Some message"

    class _FakeLLM:
        def with_structured_output(self, schema):
            return self
        def invoke(self, messages):
            return _FakeClassification()

    monkeypatch.setattr(cls_mod, "_get_classification_llm", lambda: _FakeLLM())

    result = cls_mod.classify(
        domain="traffic",
        findings=[{"description": "Something", "confidence": 0.5}],
        expert_severity="medium",
    )
    assert result["sub_type"] == "other"


def test_build_classification_prompt_includes_domain_and_findings():
    from skymirror.tools.alert.classification import build_classification_prompt
    prompt = build_classification_prompt(
        domain="safety",
        findings=[{"description": "Collision", "confidence": 0.9}],
        expert_severity="critical",
    )
    assert "safety" in prompt
    assert "Collision" in prompt
    assert "critical" in prompt
    assert "collision" in prompt or "pedestrian_intrusion" in prompt  # enum values present


# ---------------------------------------------------------------------------
# Task 4: Rendering
# ---------------------------------------------------------------------------

def test_render_alert_produces_complete_dict():
    from skymirror.tools.alert.rendering import render_alert
    alert = render_alert(
        expert_name="order_expert",
        classification={"sub_type": "red_light", "severity": "high", "message": "Red light violation"},
        findings=[{"description": "Running red light", "confidence": 0.87}],
        regulations=[{"source": "RTA", "regulation_code": "S120", "excerpt": "...", "relevance_score": 0.89}],
        image_path="data/frames/cam4798_20260412T083000.jpg",
    )
    assert alert["domain"] == "traffic"
    assert alert["sub_type"] == "red_light"
    assert alert["severity"] == "high"
    assert alert["message"] == "Red light violation"
    assert alert["source_expert"] == "order_expert"
    assert alert["department"] == "Traffic Police"
    assert alert["image_path"] == "data/frames/cam4798_20260412T083000.jpg"
    assert len(alert["evidence"]) == 1
    assert alert["evidence"][0] == "Running red light"
    assert len(alert["regulations"]) == 1
    assert "alert_id" in alert
    assert "timestamp" in alert


def test_render_alert_deterministic_id():
    from skymirror.tools.alert.rendering import render_alert
    kwargs = dict(
        expert_name="safety_expert",
        classification={"sub_type": "collision", "severity": "critical", "message": "Crash"},
        findings=[{"description": "Collision", "confidence": 0.94}],
        regulations=[],
        image_path="data/frames/cam4798_20260412T061530.jpg",
    )
    a1 = render_alert(**kwargs)
    a2 = render_alert(**kwargs)
    assert a1["alert_id"] == a2["alert_id"]


def test_render_alert_different_inputs_different_ids():
    from skymirror.tools.alert.rendering import render_alert
    a1 = render_alert(
        expert_name="order_expert",
        classification={"sub_type": "red_light", "severity": "high", "message": "msg"},
        findings=[], regulations=[],
        image_path="frame_A.jpg",
    )
    a2 = render_alert(
        expert_name="safety_expert",
        classification={"sub_type": "collision", "severity": "high", "message": "msg"},
        findings=[], regulations=[],
        image_path="frame_A.jpg",
    )
    assert a1["alert_id"] != a2["alert_id"]


def test_render_alert_unknown_expert_uses_unknown_domain():
    from skymirror.tools.alert.rendering import render_alert
    alert = render_alert(
        expert_name="unknown_expert",
        classification={"sub_type": "other", "severity": "low", "message": "msg"},
        findings=[], regulations=[],
        image_path="frame.jpg",
    )
    assert alert["domain"] == "unknown"
    assert alert["department"] == "General Operations"


# ---------------------------------------------------------------------------
# Task 5: Dispatcher
# ---------------------------------------------------------------------------

def test_dispatch_writes_alert_json(tmp_path):
    from skymirror.tools.alert.dispatcher import dispatch
    alert = {
        "alert_id": "abc123",
        "domain": "traffic",
        "severity": "high",
        "department": "Traffic Police",
    }
    dispatch(alert, output_dir=tmp_path)

    alert_file = tmp_path / "abc123.json"
    assert alert_file.exists()
    import json
    data = json.loads(alert_file.read_text())
    assert data["alert_id"] == "abc123"


def test_dispatch_writes_dispatch_log(tmp_path):
    from skymirror.tools.alert.dispatcher import dispatch
    alert = {
        "alert_id": "abc123",
        "domain": "traffic",
        "severity": "high",
        "department": "Traffic Police",
    }
    dispatch(alert, output_dir=tmp_path)

    log_file = tmp_path / "dispatch_log.jsonl"
    assert log_file.exists()
    import json
    entry = json.loads(log_file.read_text().strip())
    assert entry["alert_id"] == "abc123"
    assert entry["department"] == "Traffic Police"
    assert entry["status"] == "simulated"
    assert "dispatched_at" in entry


def test_dispatch_is_idempotent(tmp_path):
    from skymirror.tools.alert.dispatcher import dispatch
    alert = {
        "alert_id": "abc123",
        "domain": "traffic",
        "severity": "high",
        "department": "Traffic Police",
    }
    dispatch(alert, output_dir=tmp_path)
    dispatch(alert, output_dir=tmp_path)  # second call

    # Alert file written once
    import json
    alert_file = tmp_path / "abc123.json"
    assert alert_file.exists()

    # Dispatch log has only one entry
    log_file = tmp_path / "dispatch_log.jsonl"
    lines = [l for l in log_file.read_text().strip().split("\n") if l]
    assert len(lines) == 1


def test_dispatch_multiple_alerts_appends_log(tmp_path):
    from skymirror.tools.alert.dispatcher import dispatch
    for i, dept in enumerate(["Traffic Police", "Emergency Management Center"]):
        dispatch(
            {"alert_id": f"id_{i}", "domain": "traffic", "severity": "high", "department": dept},
            output_dir=tmp_path,
        )

    import json
    log_file = tmp_path / "dispatch_log.jsonl"
    lines = [l for l in log_file.read_text().strip().split("\n") if l]
    assert len(lines) == 2
    entries = [json.loads(l) for l in lines]
    assert entries[0]["department"] == "Traffic Police"
    assert entries[1]["department"] == "Emergency Management Center"


# ---------------------------------------------------------------------------
# Task 6: Alert Manager (agent orchestration)
# ---------------------------------------------------------------------------

def test_generate_alerts_single_expert(tmp_path, mock_llm):
    from skymirror.agents.alert_manager import generate_alerts
    expert_results = {
        "order_expert": {
            "findings": [{"description": "Running red light", "confidence": 0.87}],
            "severity": "high",
            "confidence": 0.87,
        }
    }
    rag_citations = [
        {"source": "RTA", "regulation_code": "S120", "excerpt": "...", "relevance_score": 0.89}
    ]
    alerts = generate_alerts(
        expert_results=expert_results,
        image_path="data/frames/cam4798.jpg",
        rag_citations=rag_citations,
        output_dir=tmp_path,
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["domain"] == "traffic"
    assert alert["source_expert"] == "order_expert"
    assert alert["department"] == "Traffic Police"
    assert len(alert["evidence"]) == 1
    assert len(alert["regulations"]) == 1
    # File was dispatched
    assert (tmp_path / f"{alert['alert_id']}.json").exists()


def test_generate_alerts_multi_expert(tmp_path, mock_llm):
    from skymirror.agents.alert_manager import generate_alerts
    expert_results = {
        "safety_expert": {
            "findings": [{"description": "Collision", "confidence": 0.94}],
            "severity": "critical",
            "confidence": 0.94,
        },
        "environment_expert": {
            "findings": [{"description": "Debris on road", "confidence": 0.71}],
            "severity": "medium",
            "confidence": 0.71,
        },
    }
    alerts = generate_alerts(
        expert_results=expert_results,
        image_path="data/frames/cam4798.jpg",
        rag_citations=[],
        output_dir=tmp_path,
    )
    assert len(alerts) == 2
    domains = {a["domain"] for a in alerts}
    assert domains == {"safety", "environment"}


def test_generate_alerts_skips_empty_findings(tmp_path, mock_llm):
    from skymirror.agents.alert_manager import generate_alerts
    expert_results = {
        "order_expert": {
            "findings": [],
            "severity": "low",
            "confidence": 0.0,
        }
    }
    alerts = generate_alerts(
        expert_results=expert_results,
        image_path="data/frames/cam4798.jpg",
        rag_citations=[],
        output_dir=tmp_path,
    )
    assert len(alerts) == 0


def test_generate_alerts_empty_expert_results(tmp_path, mock_llm):
    from skymirror.agents.alert_manager import generate_alerts
    alerts = generate_alerts(
        expert_results={},
        image_path="data/frames/cam4798.jpg",
        rag_citations=[],
        output_dir=tmp_path,
    )
    assert alerts == []


def test_generate_alerts_returns_list_to_oa(tmp_path, mock_llm):
    """Verify the contract: generate_alerts returns a plain list of dicts."""
    from skymirror.agents.alert_manager import generate_alerts
    expert_results = {
        "order_expert": {
            "findings": [{"description": "Speeding", "confidence": 0.8}],
            "severity": "medium",
            "confidence": 0.8,
        }
    }
    result = generate_alerts(
        expert_results=expert_results,
        image_path="frame.jpg",
        rag_citations=[],
        output_dir=tmp_path,
    )
    assert isinstance(result, list)
    assert all(isinstance(a, dict) for a in result)
    assert all("alert_id" in a for a in result)
