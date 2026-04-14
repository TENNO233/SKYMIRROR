# Alert Generation Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Alert Generation Agent that classifies expert findings, generates structured alerts with XAI-compliant evidence, and simulates dispatch to departments.

**Architecture:** OA calls `generate_alerts(expert_results, image_path, metadata)` which orchestrates tools in `tools/alert/` — classification (LLM), rendering (template), dispatch (file write). Agent file contains zero business logic, only tool call sequencing.

**Tech Stack:** Python 3.11+, LangChain (`with_structured_output`), Pydantic v2, pytest

---

## File Structure

```
src/skymirror/
  agents/
    alert_manager.py              # Rewrite: orchestration entry point
  tools/
    alert/
      __init__.py                 # Create: package init
      constants.py                # Create: enums, mappings
      classification.py           # Create: LLM structured output
      rendering.py                # Create: alert dict assembly
      dispatcher.py               # Create: file write + dispatch log
tests/
  test_alert_manager.py           # Create: all alert agent tests
  fixtures/
    alert_expert_results.json     # Create: test fixture
```

---

### Task 1: Constants Module

**Files:**
- Create: `src/skymirror/tools/alert/__init__.py`
- Create: `src/skymirror/tools/alert/constants.py`
- Create: `tests/test_alert_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_alert_manager.py`:

```python
"""Tests for Alert Generation Agent."""
from __future__ import annotations


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py::test_domain_map_covers_all_experts tests/test_alert_manager.py::test_sub_type_map_has_other_for_each_domain tests/test_alert_manager.py::test_department_map_covers_all_domains -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Create package init and constants module**

Create `src/skymirror/tools/alert/__init__.py`:

```python
```

Create `src/skymirror/tools/alert/constants.py`:

```python
"""Enums, domain mappings, and department routing tables for the Alert Agent.

Used by: classification.py, rendering.py, dispatcher.py
"""
from __future__ import annotations

# Expert name -> alert domain
DOMAIN_MAP: dict[str, str] = {
    "order_expert": "traffic",
    "safety_expert": "safety",
    "environment_expert": "environment",
}

# Domain -> allowed sub-types (LLM picks from these; "other" is the fallback)
SUB_TYPE_MAP: dict[str, list[str]] = {
    "traffic": [
        "red_light",
        "wrong_way",
        "illegal_parking",
        "speeding",
        "illegal_lane_change",
        "other",
    ],
    "safety": [
        "collision",
        "pedestrian_intrusion",
        "dangerous_driving",
        "road_obstruction",
        "other",
    ],
    "environment": [
        "flooding",
        "low_visibility",
        "road_damage",
        "debris",
        "other",
    ],
}

# Domain -> receiving department (simulated)
DEPARTMENT_MAP: dict[str, str] = {
    "traffic": "Traffic Police",
    "safety": "Emergency Management Center",
    "environment": "Municipal & Meteorological Duty Office",
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py::test_domain_map_covers_all_experts tests/test_alert_manager.py::test_sub_type_map_has_other_for_each_domain tests/test_alert_manager.py::test_department_map_covers_all_domains -v`

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/skymirror/tools/alert/__init__.py src/skymirror/tools/alert/constants.py tests/test_alert_manager.py
git commit -m "feat(alert): add constants module with domain/sub-type/department mappings"
```

---

### Task 2: Test Fixture

**Files:**
- Create: `tests/fixtures/alert_expert_results.json`

- [ ] **Step 1: Create test fixture**

Create `tests/fixtures/alert_expert_results.json` based on the existing `normal_day.jsonl` expert_results format:

```json
{
  "single_expert": {
    "expert_results": {
      "order_expert": {
        "findings": [
          {"description": "Running red light at intersection A", "confidence": 0.87}
        ],
        "severity": "high",
        "confidence": 0.87
      }
    },
    "image_path": "data/frames/cam4798_20260412T083000.jpg",
    "rag_citations": [
      {
        "source": "Singapore Road Traffic Act",
        "regulation_code": "RTA Section 120(3)",
        "excerpt": "Any person who fails to conform to a red traffic light signal shall be guilty of an offence.",
        "relevance_score": 0.89
      }
    ]
  },
  "multi_expert": {
    "expert_results": {
      "safety_expert": {
        "findings": [
          {"description": "Multi-vehicle collision with rollover", "confidence": 0.94}
        ],
        "severity": "critical",
        "confidence": 0.94
      },
      "environment_expert": {
        "findings": [
          {"description": "Debris on roadway", "confidence": 0.71}
        ],
        "severity": "medium",
        "confidence": 0.71
      }
    },
    "image_path": "data/frames/cam4798_20260412T061530.jpg",
    "rag_citations": [
      {
        "source": "Singapore Emergency Response Protocol",
        "regulation_code": "ERP-3.2",
        "excerpt": "Multi-vehicle collision with overturn requires immediate dispatch.",
        "relevance_score": 0.91
      }
    ]
  },
  "empty_findings": {
    "expert_results": {
      "order_expert": {
        "findings": [],
        "severity": "low",
        "confidence": 0.0
      }
    },
    "image_path": "data/frames/cam4798_20260412T031212.jpg",
    "rag_citations": []
  }
}
```

- [ ] **Step 2: Add fixture loader to test file**

Append to `tests/test_alert_manager.py`:

```python
import json
from pathlib import Path

import pytest


@pytest.fixture
def alert_fixtures(fixtures_dir: Path) -> dict:
    """Load alert test fixtures."""
    return json.loads((fixtures_dir / "alert_expert_results.json").read_text())
```

Move this fixture and the existing imports to the top of the file (below the module docstring, above the Task 1 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/alert_expert_results.json tests/test_alert_manager.py
git commit -m "feat(alert): add test fixtures for alert agent"
```

---

### Task 3: Classification Module

**Files:**
- Create: `src/skymirror/tools/alert/classification.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_alert_manager.py`:

```python
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
```

Note: import `classify` from the module — the function-level imports in the existing tests above already show the pattern.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "classify" -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement classification module**

Create `src/skymirror/tools/alert/classification.py`:

```python
"""LLM-based event classification for the Alert Agent.

Uses with_structured_output to constrain LLM responses to a valid
AlertClassification schema. Falls back to template-based defaults
on any LLM failure.

Used by: skymirror.agents.alert_manager
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel

from skymirror.tools.alert.constants import SUB_TYPE_MAP
from skymirror.tools import llm_factory

logger = logging.getLogger(__name__)


class AlertClassification(BaseModel):
    """Structured output schema for LLM classification."""
    sub_type: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


def _get_classification_llm() -> Any:
    """Return an LLM instance for classification. Separated for test mocking."""
    return llm_factory.get_llm(temperature=0.1)


def build_classification_prompt(
    domain: str,
    findings: list[dict[str, Any]],
    expert_severity: str,
) -> str:
    """Build the classification prompt with domain-specific enum constraints."""
    sub_types = SUB_TYPE_MAP.get(domain, ["other"])
    return (
        "You are SKYMIRROR's Alert Classification Agent.\n\n"
        "Given the following expert analysis findings, classify this event.\n\n"
        f"Domain: {domain}\n"
        f"Expert findings: {json.dumps(findings, indent=2)}\n\n"
        f"Choose sub_type from: {sub_types}\n"
        "Choose severity from: low, medium, high, critical\n"
        f"The expert's own severity assessment was: {expert_severity}\n\n"
        "Write a concise alert message (1-2 sentences) in English summarizing "
        "the event for the receiving department. Include what happened, the "
        "image reference, and recommended urgency."
    )


def classify(
    domain: str,
    findings: list[dict[str, Any]],
    expert_severity: str,
) -> dict[str, str]:
    """Classify an event using LLM with structured output.

    Returns a dict with keys: sub_type, severity, message.
    Falls back to safe defaults on any LLM failure.
    """
    prompt = build_classification_prompt(domain, findings, expert_severity)

    try:
        llm = _get_classification_llm()
        structured_llm = llm.with_structured_output(AlertClassification)
        from langchain_core.messages import HumanMessage
        result = structured_llm.invoke([HumanMessage(content=prompt)])

        sub_type = result.sub_type
        valid_types = SUB_TYPE_MAP.get(domain, ["other"])
        if sub_type not in valid_types:
            logger.warning(
                "LLM returned invalid sub_type %r for domain %r; forcing 'other'.",
                sub_type, domain,
            )
            sub_type = "other"

        return {
            "sub_type": sub_type,
            "severity": result.severity,
            "message": result.message,
        }

    except Exception as exc:
        logger.warning("Classification LLM failed: %s — using fallback.", exc)
        first_desc = findings[0].get("description", "Unknown event") if findings else "Unknown event"
        return {
            "sub_type": "other",
            "severity": expert_severity if expert_severity in ("low", "medium", "high", "critical") else "medium",
            "message": f"{domain} alert: {first_desc}",
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "classify" -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/skymirror/tools/alert/classification.py tests/test_alert_manager.py
git commit -m "feat(alert): add LLM classification with structured output and fallback"
```

---

### Task 4: Rendering Module

**Files:**
- Create: `src/skymirror/tools/alert/rendering.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_alert_manager.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "render_alert" -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement rendering module**

Create `src/skymirror/tools/alert/rendering.py`:

```python
"""Template-based alert dict assembly for the Alert Agent.

Pure functions — no LLM calls, no I/O. Takes classification results and
expert data, returns a complete alert dict ready for dispatch.

Used by: skymirror.agents.alert_manager
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from skymirror.tools.alert.constants import DEPARTMENT_MAP, DOMAIN_MAP


def _deterministic_id(image_path: str, expert_name: str) -> str:
    """Generate a deterministic alert ID from image_path + expert_name.

    Supports idempotent re-processing: same inputs always produce same ID.
    """
    key = f"{image_path}::{expert_name}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def render_alert(
    expert_name: str,
    classification: dict[str, str],
    findings: list[dict[str, Any]],
    regulations: list[dict[str, Any]],
    image_path: str,
) -> dict[str, Any]:
    """Assemble a complete alert dict from classification + expert data.

    All structured fields are rule-based; only `message` comes from LLM
    (via the classification dict).
    """
    domain = DOMAIN_MAP.get(expert_name, "unknown")
    department = DEPARTMENT_MAP.get(domain, "General Operations")

    evidence = [f.get("description", "") for f in findings if f.get("description")]

    return {
        "alert_id": _deterministic_id(image_path, expert_name),
        "domain": domain,
        "sub_type": classification["sub_type"],
        "severity": classification["severity"],
        "message": classification["message"],
        "source_expert": expert_name,
        "evidence": evidence,
        "regulations": regulations,
        "department": department,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "image_path": image_path,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "render_alert" -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/skymirror/tools/alert/rendering.py tests/test_alert_manager.py
git commit -m "feat(alert): add rendering module for alert dict assembly"
```

---

### Task 5: Dispatcher Module

**Files:**
- Create: `src/skymirror/tools/alert/dispatcher.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_alert_manager.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "dispatch" -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement dispatcher module**

Create `src/skymirror/tools/alert/dispatcher.py`:

```python
"""Simulated alert dispatch — writes JSON files and a dispatch log.

No real network calls. Each alert is written to its own JSON file;
a single dispatch_log.jsonl tracks all dispatches for the session.

Used by: skymirror.agents.alert_manager
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def dispatch(alert: dict[str, Any], output_dir: Path | str) -> None:
    """Write an alert to disk and append to the dispatch log.

    Idempotent: if the alert file already exists, skip writing and
    do not append a duplicate log entry.

    Args:
        alert: Complete alert dict (must contain "alert_id" and "department").
        output_dir: Directory to write files into (created if missing).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    alert_id = alert["alert_id"]
    alert_file = output_dir / f"{alert_id}.json"

    if alert_file.exists():
        logger.info(
            "alert_dispatch: SKIP duplicate alert_id=%s (already dispatched)",
            alert_id,
        )
        return

    alert_file.write_text(json.dumps(alert, indent=2, ensure_ascii=False), encoding="utf-8")

    log_entry = {
        "alert_id": alert_id,
        "department": alert.get("department", "unknown"),
        "dispatched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "simulated",
    }

    log_file = output_dir / "dispatch_log.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    logger.info(
        "alert_dispatch: SENT alert_id=%s domain=%s severity=%s -> %s",
        alert_id,
        alert.get("domain", "?"),
        alert.get("severity", "?"),
        alert.get("department", "?"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "dispatch" -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/skymirror/tools/alert/dispatcher.py tests/test_alert_manager.py
git commit -m "feat(alert): add dispatcher with file output and idempotent writes"
```

---

### Task 6: Alert Manager Agent (Orchestration)

**Files:**
- Modify: `src/skymirror/agents/alert_manager.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_alert_manager.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "generate_alerts" -v`

Expected: FAIL (ImportError — generate_alerts does not exist yet)

- [ ] **Step 3: Rewrite alert_manager.py**

Replace the entire contents of `src/skymirror/agents/alert_manager.py`:

```python
"""Alert Generation Agent — Orchestration Entry Point
=====================================================

Identity
--------
I am SKYMIRROR's alert generation surface. When OA determines that expert
analysis results warrant an alert, it calls me with expert_results,
image_path, and optional context. I orchestrate tools to classify, render,
and dispatch structured alerts.

I am NOT a fixed pipeline node. I am an independent agent invoked on-demand
by OA (Orchestrator Agent).

Tasks
-----
1. For each expert in expert_results: skip if findings are empty.
2. Call classification tool to determine sub_type, severity, and message.
3. Call rendering tool to assemble the complete alert dict with evidence
   and regulation citations (XAI: process transparency + source attribution).
4. Call dispatcher tool to write alert files and dispatch log.
5. Return the list of generated alerts to OA.

Tools
-----
- ``skymirror.tools.alert.classification`` : LLM-based event classification
- ``skymirror.tools.alert.rendering``      : template-based alert dict assembly
- ``skymirror.tools.alert.dispatcher``     : simulated file-based dispatch
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from skymirror.tools.alert.classification import classify
from skymirror.tools.alert.constants import DOMAIN_MAP
from skymirror.tools.alert.dispatcher import dispatch
from skymirror.tools.alert.rendering import render_alert

logger = logging.getLogger(__name__)


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

        # Tool 2: Render
        alert = render_alert(
            expert_name=expert_name,
            classification=classification,
            findings=findings,
            regulations=rag_citations,
            image_path=image_path,
        )

        # Tool 3: Dispatch
        dispatch(alert, output_dir=output_dir)

        alerts.append(alert)

    logger.info("alert_manager: Generated %d alert(s).", len(alerts))
    return alerts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "generate_alerts" -v`

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/skymirror/agents/alert_manager.py tests/test_alert_manager.py
git commit -m "feat(alert): implement alert manager agent with tool orchestration"
```

---

### Task 7: Update mock_llm Fixture for Structured Output

**Files:**
- Modify: `tests/conftest.py`

The existing `mock_llm` fixture only mocks `invoke()`. The classification module uses `with_structured_output()` which needs a different mock path. We need to update conftest to handle both patterns.

- [ ] **Step 1: Write a failing test that exposes the issue**

If the Task 6 tests above pass with the current mock, this task may be unnecessary. Run all tests first:

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -v`

If `test_generate_alerts_single_expert` or similar fail because mock_llm doesn't support `with_structured_output`, proceed to Step 2. If all pass, skip to Step 5 (commit is a no-op, move on).

- [ ] **Step 2: Update conftest.py mock_llm fixture**

Add structured output support to the existing `_FakeLLM` class in `tests/conftest.py`:

```python
@pytest.fixture
def mock_llm(monkeypatch):
    """Replace `get_llm()` with a deterministic echo LLM for offline tests.

    Supports both direct `invoke()` (narrate pattern) and
    `with_structured_output()` (classification pattern).
    """
    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeClassificationResult:
        """Mimics a Pydantic model instance returned by with_structured_output."""
        def __init__(self):
            self.sub_type = "other"
            self.severity = "medium"
            self.message = "[MOCK] Alert classification result"

    class _FakeStructuredLLM:
        def invoke(self, messages):
            return _FakeClassificationResult()

    class _FakeLLM:
        def invoke(self, messages):
            if hasattr(messages, "__iter__") and not isinstance(messages, str):
                prompt = "\n".join(getattr(m, "content", str(m)) for m in messages)
            else:
                prompt = str(messages)
            head = prompt[:80].replace("\n", " ")
            return _FakeResponse(content=f"[MOCK LLM narration for: {head!r}]")

        def with_structured_output(self, schema):
            return _FakeStructuredLLM()

    monkeypatch.setattr(
        "skymirror.tools.llm_factory.get_llm",
        lambda **kwargs: _FakeLLM(),
    )
```

- [ ] **Step 3: Run all tests to verify everything passes**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/ -v`

Expected: All tests pass (existing report tests + new alert tests)

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "feat(test): extend mock_llm to support with_structured_output"
```

---

### Task 8: Full Integration Test with Fixture Data

**Files:**
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write integration test using fixture file**

Append to `tests/test_alert_manager.py`:

```python
# ---------------------------------------------------------------------------
# Task 8: Integration test with fixture data
# ---------------------------------------------------------------------------

def test_end_to_end_single_expert_fixture(tmp_path, alert_fixtures, mock_llm):
    """End-to-end: single expert fixture produces one alert with all fields."""
    from skymirror.agents.alert_manager import generate_alerts
    fixture = alert_fixtures["single_expert"]
    alerts = generate_alerts(
        expert_results=fixture["expert_results"],
        image_path=fixture["image_path"],
        rag_citations=fixture["rag_citations"],
        output_dir=tmp_path,
    )
    assert len(alerts) == 1
    alert = alerts[0]
    # Schema completeness
    for key in ("alert_id", "domain", "sub_type", "severity", "message",
                "source_expert", "evidence", "regulations", "department",
                "timestamp", "image_path"):
        assert key in alert, f"Missing key: {key}"
    assert alert["domain"] == "traffic"
    assert alert["department"] == "Traffic Police"
    assert len(alert["regulations"]) == 1
    assert alert["regulations"][0]["regulation_code"] == "RTA Section 120(3)"

    # Dispatch files exist
    assert (tmp_path / f"{alert['alert_id']}.json").exists()
    assert (tmp_path / "dispatch_log.jsonl").exists()


def test_end_to_end_multi_expert_fixture(tmp_path, alert_fixtures, mock_llm):
    """End-to-end: multi-expert fixture produces two alerts to different departments."""
    from skymirror.agents.alert_manager import generate_alerts
    fixture = alert_fixtures["multi_expert"]
    alerts = generate_alerts(
        expert_results=fixture["expert_results"],
        image_path=fixture["image_path"],
        rag_citations=fixture["rag_citations"],
        output_dir=tmp_path,
    )
    assert len(alerts) == 2
    departments = {a["department"] for a in alerts}
    assert "Emergency Management Center" in departments
    assert "Municipal & Meteorological Duty Office" in departments

    # Two alert files + one dispatch log
    import json
    log_file = tmp_path / "dispatch_log.jsonl"
    lines = [l for l in log_file.read_text().strip().split("\n") if l]
    assert len(lines) == 2


def test_end_to_end_empty_findings_fixture(tmp_path, alert_fixtures, mock_llm):
    """End-to-end: empty findings fixture produces no alerts."""
    from skymirror.agents.alert_manager import generate_alerts
    fixture = alert_fixtures["empty_findings"]
    alerts = generate_alerts(
        expert_results=fixture["expert_results"],
        image_path=fixture["image_path"],
        rag_citations=fixture["rag_citations"],
        output_dir=tmp_path,
    )
    assert alerts == []
    assert not (tmp_path / "dispatch_log.jsonl").exists()
```

- [ ] **Step 2: Run integration tests**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/test_alert_manager.py -k "end_to_end" -v`

Expected: 3 passed

- [ ] **Step 3: Run ALL tests (alert + report) to confirm no regressions**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/ -v`

Expected: All tests pass (27 existing + new alert tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_alert_manager.py
git commit -m "feat(alert): add end-to-end integration tests with fixture data"
```

---

### Task 9: Final Cleanup and Full Test Run

**Files:**
- All files from Tasks 1-8

- [ ] **Step 1: Run full test suite**

Run: `cd "/Users/shangjiakun/Desktop/Explainable and Responsible AI/Group Project/SKYMIRROR" && python -m pytest tests/ -v --tb=short`

Expected: ALL tests pass, zero failures

- [ ] **Step 2: Verify file structure matches spec**

Run: `find src/skymirror/tools/alert -type f -name "*.py" | sort && echo "---" && find src/skymirror/agents -name "alert*" -type f`

Expected output:
```
src/skymirror/tools/alert/__init__.py
src/skymirror/tools/alert/classification.py
src/skymirror/tools/alert/constants.py
src/skymirror/tools/alert/dispatcher.py
src/skymirror/tools/alert/rendering.py
---
src/skymirror/agents/alert_manager.py
```

- [ ] **Step 3: Verify alert_manager.py contains zero business logic**

Read `src/skymirror/agents/alert_manager.py` and confirm it only imports + calls tools. No string manipulation, no dict construction, no file I/O — only `classify()`, `render_alert()`, `dispatch()`, and logging.

- [ ] **Step 4: Final commit if any cleanup was needed**

```bash
git add -A
git commit -m "chore(alert): final cleanup after full test pass"
```
