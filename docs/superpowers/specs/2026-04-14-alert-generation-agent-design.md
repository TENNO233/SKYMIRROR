# Alert Generation Agent — Design Spec

**Date**: 2026-04-14
**Author**: JK
**Status**: Draft

---

## 1. Overview

The Alert Generation Agent is an independent agent invoked on-demand by the
Orchestrator Agent (OA). When OA determines that expert analysis results
warrant an alert, it calls the Alert Agent with the relevant context. The
Alert Agent classifies the event, generates a structured alert with
explainable evidence, and simulates dispatch to the appropriate department.

### Key Principles

- **OA-driven**: Alert Agent has one upstream caller — OA. It does not
  participate in a fixed pipeline. OA decides when to invoke it.
- **Tool-based architecture**: The agent file (`alert_manager.py`) contains
  only orchestration logic (tool calls + logging). All business logic lives
  in `tools/alert/` modules.
- **Hybrid principle**: Structured fields are computed by rules/templates;
  only the human-readable `message` field is LLM-generated. Consistent with
  the Daily Explication Report Agent pattern.
- **XAI compliance**: Every alert carries `evidence` (expert findings) and
  `regulations` (RAG-retrieved references from experts) for full process
  transparency and source attribution.

---

## 2. Invocation Model

```
OA (Orchestrator Agent)
  |
  |  Determines alert is needed
  |  Calls Alert Agent with:
  |    - expert_results: dict[str, Any]
  |    - image_path: str
  |    - metadata: dict (optional)
  |
  v
Alert Agent (orchestration layer)
  |  Calls tools to classify, render, dispatch
  |  Returns: list of alert dicts to OA
  v
OA receives alerts, continues processing
```

The Alert Agent does **not** read from LangGraph shared state. Its inputs
are explicitly passed by OA.

---

## 3. Classification System

### 3.1 Two-Layer Taxonomy

**Layer 1 — Domain** (rule-based, derived from source expert name):

| Expert Name            | Domain        |
|------------------------|---------------|
| `order_expert`         | `traffic`     |
| `safety_expert`        | `safety`      |
| `environment_expert`   | `environment` |

**Layer 2 — Sub-type** (LLM-selected from predefined enum per domain):

| Domain        | Sub-types                                                                          |
|---------------|------------------------------------------------------------------------------------|
| `traffic`     | `red_light`, `wrong_way`, `illegal_parking`, `speeding`, `illegal_lane_change`, `other` |
| `safety`      | `collision`, `pedestrian_intrusion`, `dangerous_driving`, `road_obstruction`, `other`   |
| `environment` | `flooding`, `low_visibility`, `road_damage`, `debris`, `other`                          |

**Severity levels**: `low`, `medium`, `high`, `critical` — determined by LLM
with the expert's own severity assessment as reference input.

### 3.2 Department Mapping

| Domain        | Department (simulated)                              |
|---------------|-----------------------------------------------------|
| `traffic`     | Traffic Police (交通警察大队)                         |
| `safety`      | Emergency Management Center (应急管理中心)            |
| `environment` | Municipal & Meteorological Duty Office (市政与气象联合值班室) |

---

## 4. Alert Schema

```python
{
    "alert_id":       str,         # Deterministic hash of (image_path + source_expert)
    "domain":         str,         # "traffic" | "safety" | "environment"
    "sub_type":       str,         # Enum value or "other"
    "severity":       str,         # "low" | "medium" | "high" | "critical"
    "message":        str,         # LLM-generated readable summary
    "source_expert":  str,         # Expert name that produced the findings
    "evidence":       list[str],   # Expert findings verbatim (process transparency)
    "regulations":    list[dict],  # RAG references from expert (source attribution)
    "department":     str,         # Target department name
    "timestamp":      str,         # ISO-8601 UTC
    "image_path":     str,         # Source frame path
}
```

- `evidence` and `regulations` are extracted directly from expert_results
  without modification — preserving the XAI audit trail.
- `alert_id` is a deterministic hash (not random UUID) to support idempotent
  re-processing of the same frame.

---

## 5. Generation Flow

Per invocation, the Alert Agent processes each expert's results independently.
One frame may produce 1-3 alerts (one per activated expert).

```
For each expert in expert_results:
  1. [Rule]  domain = DOMAIN_MAP[expert_name]
  2. [Rule]  Extract evidence + regulations from expert findings
  3. [Tool]  classify(domain, findings) -> { sub_type, severity, message }
             Uses LLM with_structured_output(AlertClassification)
  4. [Tool]  render_alert(classification, evidence, regulations, context)
             -> complete alert dict
  5. [Tool]  dispatch(alert) -> write file + log

Return all alerts to OA
```

---

## 6. LLM Integration

### 6.1 Classification Prompt

```
You are SKYMIRROR's Alert Classification Agent.

Given the following expert analysis findings, classify this event.

Domain: {domain}
Expert findings: {findings_json}

Choose sub_type from: {sub_type_enum_for_domain}
Choose severity from: low, medium, high, critical
The expert's own severity assessment was: {expert_severity}

Write a concise alert message (1-2 sentences) in English summarizing
the event for the receiving department. Include what happened, the
image reference, and recommended urgency.
```

### 6.2 Structured Output Schema

```python
class AlertClassification(BaseModel):
    sub_type: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str
```

Enforced via `llm.with_structured_output(AlertClassification)`.

### 6.3 Fallback Strategy

| Failure Scenario                  | Fallback Behavior                                              |
|-----------------------------------|----------------------------------------------------------------|
| LLM call fails                    | sub_type=`"other"`, severity=expert's original, message=template `"{domain} alert from {expert}: {first_finding}"` |
| LLM returns sub_type not in enum  | Force to `"other"`                                             |
| Expert findings list is empty     | Skip this expert, do not generate alert                        |

Principle: LLM failure must never block alert generation. Degrade to
template output — an alert always gets dispatched.

---

## 7. Simulated Dispatch

### 7.1 File Output

- Each alert: `data/alerts/{date}/{alert_id}.json`
- Dispatch log: `data/alerts/{date}/dispatch_log.jsonl`

Dispatch log entry format:
```json
{
    "alert_id": "...",
    "department": "Traffic Police",
    "dispatched_at": "2026-04-14T08:30:00Z",
    "status": "simulated"
}
```

### 7.2 Idempotency

`alert_id` = deterministic hash of `image_path + source_expert`. Repeated
calls for the same frame and expert produce the same ID. The dispatcher
checks for existing files before writing — skip if already dispatched.

### 7.3 Structured Logging

`logger.info` for each dispatch with key fields (alert_id, domain,
severity, department) for demo terminal visibility.

---

## 8. Code Structure

```
src/skymirror/
  agents/
    alert_manager.py              # Agent entry: orchestration only (tool calls + logging)
  tools/
    alert/
      __init__.py
      constants.py                # Enums, DOMAIN_MAP, DEPARTMENT_MAP, SUB_TYPE_MAP
      classification.py           # LLM classification (with_structured_output)
      rendering.py                # Template assembly of alert dict
      dispatcher.py               # File write + dispatch_log + logging
```

### Module Responsibilities

| Module               | Does                                              | Calls LLM? |
|----------------------|---------------------------------------------------|-------------|
| `constants.py`       | Enum definitions, mapping tables                  | No          |
| `classification.py`  | Build prompt, call LLM, parse + validate result   | Yes         |
| `rendering.py`       | Assemble complete alert dict from parts            | No          |
| `dispatcher.py`      | Write JSON files, dispatch_log.jsonl, logging      | No          |
| `alert_manager.py`   | Orchestrate tool calls, return alerts to OA        | No (indirect) |

**Zero business logic in `alert_manager.py`** — it only sequences tool
calls and handles the OA interface contract.

---

## 9. Testing Strategy

Uses existing `mock_llm` fixture pattern from conftest.py.

| Test Area          | What                                                          | Fixture      |
|--------------------|---------------------------------------------------------------|--------------|
| `classification`   | Prompt construction, structured output parsing, fallback on LLM failure | `mock_llm`   |
| `rendering`        | Pure function: given inputs, verify all alert fields correct  | None         |
| `dispatcher`       | File creation, idempotent skip, dispatch_log format           | `tmp_path`   |
| `alert_manager`    | End-to-end: expert_results in -> alerts list + files out      | `mock_llm` + `tmp_path` |
| Edge cases         | Empty expert_results, empty findings, invalid LLM sub_type   | Various      |

---

## 10. Out of Scope

- Modifying `graph.py` topology (other team member's responsibility)
- Real network dispatch (webhook, Kafka, SNS)
- Additional RAG retrieval (experts already provide references)
- Modifying `SkymirrorState` schema
