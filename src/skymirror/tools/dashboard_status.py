"""Runtime status persistence for the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from threading import RLock
import time
from typing import Any

logger = logging.getLogger(__name__)
_STATUS_WRITE_LOCK = RLock()
_HISTORY_LIMIT = 40


def load_runtime_status(status_path: Path | str) -> dict[str, Any]:
    path = Path(status_path)
    with _STATUS_WRITE_LOCK:
        return _read_runtime_status_unlocked(path)


def set_runtime_active_cameras(
    status_path: Path | str,
    camera_ids: list[str],
) -> None:
    path = Path(status_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    active_camera_ids = [camera_id for camera_id in camera_ids if camera_id]
    with _STATUS_WRITE_LOCK:
        snapshot = _read_runtime_status_unlocked(path)
        cameras = snapshot.get("cameras")
        if not isinstance(cameras, dict):
            cameras = {}
        snapshot["cameras"] = {
            camera_id: payload
            for camera_id, payload in cameras.items()
            if camera_id in active_camera_ids
        }
        snapshot["active_camera_ids"] = active_camera_ids
        snapshot["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        _write_runtime_status_unlocked(path, snapshot)


def clear_runtime_active_cameras(status_path: Path | str) -> None:
    set_runtime_active_cameras(status_path, [])


def _read_runtime_status_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"updated_at": "", "active_camera_ids": [], "cameras": {}}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("dashboard_status: could not read %s: %s", path, exc)
        return {"updated_at": "", "active_camera_ids": [], "cameras": {}}

    cameras = payload.get("cameras")
    if not isinstance(cameras, dict):
        cameras = {}
    active_camera_ids = payload.get("active_camera_ids")
    if not isinstance(active_camera_ids, list):
        active_camera_ids = []
    updated_at = payload.get("updated_at")
    return {
        "updated_at": updated_at if isinstance(updated_at, str) else "",
        "active_camera_ids": [str(camera_id).strip() for camera_id in active_camera_ids if str(camera_id).strip()],
        "cameras": cameras,
    }


def write_camera_runtime_status(
    status_path: Path | str,
    *,
    camera_id: str,
    backend_status: str,
    interval_seconds: int,
    image_path: str = "",
    final_state: dict[str, Any] | None = None,
    message: str = "",
    current_agents: list[str] | None = None,
    record_history: bool = True,
) -> None:
    path = Path(status_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with _STATUS_WRITE_LOCK:
        snapshot = _read_runtime_status_unlocked(path)
        cameras = snapshot.setdefault("cameras", {})
        existing = cameras.get(camera_id, {})
        existing = existing if isinstance(existing, dict) else {}

        now = datetime.now(tz=timezone.utc)
        status_message = _resolve_status_message(
            existing=existing,
            backend_status=backend_status,
            message=message,
            record_history=record_history,
        )
        status_history = (
            _append_history_entry(
                _coerce_history(existing.get("status_history")),
                {
                    "timestamp": now.isoformat(),
                    "backend_status": str(backend_status).strip(),
                    "message": status_message,
                },
                compare_keys=("backend_status", "message"),
            )
            if record_history
            else _coerce_history(existing.get("status_history"))
        )
        analysis_history = _coerce_history(existing.get("analysis_history"))
        payload: dict[str, Any] = {
            **existing,
            "camera_id": camera_id,
            "backend_status": backend_status,
            "interval_seconds": int(interval_seconds),
            "heartbeat_at": now.isoformat(),
            "status_message": status_message,
            "status_history": status_history,
            "analysis_history": analysis_history,
            "current_agents": _coerce_agent_names(
                current_agents if current_agents is not None else existing.get("current_agents")
            ),
        }

        if image_path:
            payload["image_path"] = image_path
            image_timestamp = _resolve_image_timestamp(image_path)
            if image_timestamp:
                payload["latest_frame_at"] = image_timestamp
        else:
            image_timestamp = ""

        if final_state is not None:
            payload["last_analysis_at"] = now.isoformat()
            guardrail_result = _coerce_dict(final_state.get("guardrail_result"))
            payload["guardrail_result"] = guardrail_result
            validated_text = str(final_state.get("validated_text", "")).strip()
            payload["validated_text"] = validated_text
            payload["validated_signals"] = _coerce_dict(final_state.get("validated_signals"))
            payload["active_experts"] = _coerce_list(final_state.get("active_experts"))
            alerts = _coerce_list(final_state.get("alerts"))
            payload["alerts"] = alerts
            payload["metadata"] = _compact_metadata(final_state.get("metadata"))

            first_alert = alerts[0] if alerts and isinstance(alerts[0], dict) else {}
            if validated_text:
                payload["analysis_history"] = _append_history_entry(
                    analysis_history,
                    {
                        "timestamp": now.isoformat(),
                        "backend_status": str(backend_status).strip(),
                        "summary": validated_text,
                        "severity": str(first_alert.get("severity", "")).strip().lower(),
                        "emergency_type": str(
                            first_alert.get("emergency_type") or first_alert.get("type") or ""
                        ).strip(),
                    },
                    compare_keys=("backend_status", "summary", "severity", "emergency_type"),
                )

            if image_path and _guardrail_allows_display(guardrail_result, backend_status):
                payload["approved_image_path"] = image_path
                if image_timestamp:
                    payload["last_frame_at"] = image_timestamp

        cameras[camera_id] = payload
        snapshot["updated_at"] = now.isoformat()

        active_camera_ids = snapshot.get("active_camera_ids")
        if not isinstance(active_camera_ids, list):
            snapshot["active_camera_ids"] = []

        _write_runtime_status_unlocked(path, snapshot)


def _write_runtime_status_unlocked(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    last_error: OSError | None = None
    for _ in range(5):
        try:
            temp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.1)

    if last_error is not None:
        raise last_error


def _resolve_image_timestamp(image_path: str) -> str:
    try:
        path = Path(image_path)
        if not path.is_file():
            return ""
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return mtime.isoformat()
    except OSError:
        return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _coerce_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append({str(key): item_value for key, item_value in item.items() if str(key).strip()})
    return normalized[-_HISTORY_LIMIT:]


def _coerce_agent_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _append_history_entry(
    history: list[dict[str, Any]],
    entry: dict[str, Any],
    *,
    compare_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    normalized = {
        str(key): value
        for key, value in entry.items()
        if str(key).strip() and value not in (None, "", [], {})
    }
    if not normalized:
        return history[-_HISTORY_LIMIT:]

    entries = list(history[-_HISTORY_LIMIT:])
    if entries:
        last = entries[-1]
        if all(last.get(key) == normalized.get(key) for key in compare_keys):
            entries[-1] = {**last, **normalized}
            return entries[-_HISTORY_LIMIT:]

    entries.append(normalized)
    return entries[-_HISTORY_LIMIT:]


def _default_status_message(backend_status: str) -> str:
    normalized = str(backend_status).strip().replace("_", " ")
    return normalized.title() if normalized else "Status update received."


def _resolve_status_message(
    *,
    existing: dict[str, Any],
    backend_status: str,
    message: str,
    record_history: bool,
) -> str:
    explicit_message = str(message).strip()
    if explicit_message:
        return explicit_message
    if not record_history:
        existing_message = str(existing.get("status_message", "")).strip()
        if existing_message:
            return existing_message
    return _default_status_message(backend_status)


def _compact_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for key in ("guardrail", "validator", "orchestrator", "alert_manager", "langsmith"):
        nested = value.get(key)
        if isinstance(nested, dict):
            compact[key] = nested
    return compact


def _guardrail_allows_display(guardrail_result: dict[str, Any], backend_status: str) -> bool:
    allowed = guardrail_result.get("allowed")
    if isinstance(allowed, bool):
        return allowed

    return str(backend_status).strip().lower() not in {"blocked", "error", "fetch_error"}
