"""RunRecord helpers for runtime audit logging and report generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from skymirror.tools.governance import policy_snapshot, policy_version

RunStatus = str
_VALID_STATUSES = frozenset({"blocked", "clean", "alerted", "failed"})


def new_run_id() -> str:
    return f"run_{uuid4().hex}"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_run_record(
    *,
    run_id: str,
    workflow_mode: str,
    camera_id: str,
    image_path: str,
    status: RunStatus,
    guardrail_result: dict[str, Any] | None = None,
    validated_text: str = "",
    validated_signals: dict[str, Any] | None = None,
    active_experts: list[str] | None = None,
    expert_results: dict[str, Any] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if status not in _VALID_STATUSES:
        raise ValueError(f"Unsupported run status: {status}")

    final_metadata = dict(metadata or {})
    final_metadata.setdefault("policies", {})
    final_metadata["policies"].setdefault("runtime", policy_snapshot())
    final_metadata["policies"].setdefault("policy_version", policy_version())

    record = {
        "run_id": run_id,
        "timestamp": timestamp or now_utc_iso(),
        "workflow_mode": workflow_mode,
        "camera_id": camera_id,
        "image_path": image_path,
        "guardrail_result": dict(guardrail_result or {}),
        "validated_text": str(validated_text or "").strip(),
        "validated_signals": dict(validated_signals or {}),
        "active_experts": list(active_experts or []),
        "expert_results": dict(expert_results or {}),
        "alerts": list(alerts or []),
        "metadata": final_metadata,
        "status": status,
    }
    validate_run_record(record)
    return record


def validate_run_record(record: dict[str, Any]) -> None:
    required_str = ("run_id", "timestamp", "workflow_mode", "camera_id", "image_path", "status")
    for field in required_str:
        if not isinstance(record.get(field), str):
            raise ValueError(f"RunRecord field '{field}' must be a string.")

    if record["status"] not in _VALID_STATUSES:
        raise ValueError(f"RunRecord status '{record['status']}' is invalid.")

    required_dict = (
        "guardrail_result",
        "validated_signals",
        "expert_results",
        "metadata",
    )
    for field in required_dict:
        if not isinstance(record.get(field), dict):
            raise ValueError(f"RunRecord field '{field}' must be a dict.")

    if not isinstance(record.get("active_experts"), list):
        raise ValueError("RunRecord field 'active_experts' must be a list.")
    if not isinstance(record.get("alerts"), list):
        raise ValueError("RunRecord field 'alerts' must be a list.")

    metadata = dict(record.get("metadata") or {})
    for key in ("models", "prompts", "policies", "retrieval", "external_calls"):
        if key not in metadata:
            metadata[key] = {}
        if not isinstance(metadata[key], dict):
            raise ValueError(f"RunRecord metadata '{key}' must be a dict.")


def write_run_record(oa_log_dir: Path | str, record: dict[str, Any]) -> Path:
    validate_run_record(record)
    output_dir = Path(oa_log_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_partition = record["timestamp"][:10]
    output_path = output_dir / f"{date_partition}.jsonl"
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return output_path

