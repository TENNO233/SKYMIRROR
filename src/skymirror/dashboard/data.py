"""Data loaders for the SKYMIRROR dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from skymirror.tools.dashboard_status import load_runtime_status

logger = logging.getLogger(__name__)

SGT = timezone(timedelta(hours=8), name="SGT")
_LATEST_FRAME_RE = re.compile(
    r"^cam(?P<camera_id>\d+)_latest\.(?:jpg|jpeg|png|webp)$",
    re.IGNORECASE,
)
_TIMESTAMPED_FRAME_RE = re.compile(
    r"^cam(?P<camera_id>\d+)_(?P<stamp>\d{8}_\d{6})\.(?:jpg|jpeg|png|webp)$",
    re.IGNORECASE,
)
_REPORT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRAFFIC_IMAGES_API_URL = "https://api.data.gov.sg/v1/transport/traffic-images"
_LIVE_CACHE_TTL_SECONDS = 20.0


@dataclass(frozen=True)
class DashboardPaths:
    project_root: Path
    static_dir: Path
    frames_dir: Path
    reports_dir: Path
    camera_reference_path: Path
    runtime_status_path: Path


@dataclass
class LiveCameraCache:
    images: dict[str, str] = field(default_factory=dict)
    expires_at: float = 0.0


def default_dashboard_paths(project_root: Path | None = None) -> DashboardPaths:
    root = (project_root or Path(__file__).resolve().parents[3]).resolve()
    return DashboardPaths(
        project_root=root,
        static_dir=root / "src" / "skymirror" / "dashboard" / "static",
        frames_dir=root / "data" / "frames",
        reports_dir=root / "data" / "reports",
        camera_reference_path=root / "data" / "sources" / "traffic_camera_reference.json",
        runtime_status_path=root / "data" / "dashboard" / "live_status.json",
    )


def load_camera_reference(reference_path: Path) -> list[dict[str, str]]:
    rows = json.loads(reference_path.read_text(encoding="utf-8"))
    return [
        {
            "camera_id": str(row.get("camera_id", "")).strip(),
            "road_type": str(row.get("road_type", "")).strip(),
            "location_description": str(row.get("location_description", "")).strip(),
            "area_or_key_landmark": str(row.get("area_or_key_landmark", "")).strip(),
        }
        for row in rows
    ]


def fetch_live_camera_images(
    *,
    timeout_seconds: float = 3.0,
    cache: LiveCameraCache | None = None,
) -> dict[str, str]:
    now = monotonic()
    if cache is not None and cache.images and now < cache.expires_at:
        return dict(cache.images)

    request = Request(
        _TRAFFIC_IMAGES_API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "SkyMirrorDashboard/1.0",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        logger.warning("dashboard: live camera lookup unavailable: %s", exc)
        if cache is not None and cache.images:
            return dict(cache.images)
        return {}

    items = payload.get("items", [])
    cameras = items[0].get("cameras", []) if items else []
    images = {
        str(camera.get("camera_id", "")).strip(): str(camera.get("image", "")).strip()
        for camera in cameras
        if str(camera.get("camera_id", "")).strip() and str(camera.get("image", "")).strip()
    }

    if cache is not None:
        cache.images = dict(images)
        cache.expires_at = now + _LIVE_CACHE_TTL_SECONDS

    return images


def discover_local_frames(frames_dir: Path) -> dict[str, dict[str, Any]]:
    if not frames_dir.exists():
        return {}

    discovered: dict[str, dict[str, Any]] = {}
    for path in frames_dir.iterdir():
        if not path.is_file():
            continue

        match = _LATEST_FRAME_RE.match(path.name)
        priority = 2
        if not match:
            match = _TIMESTAMPED_FRAME_RE.match(path.name)
            priority = 1
        if not match:
            continue

        camera_id = match.group("camera_id")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        current = discovered.get(camera_id)
        if current is None or priority > current["priority"] or mtime > current["timestamp"]:
            discovered[camera_id] = {
                "url": f"/frames/{quote(path.name)}?v={int(path.stat().st_mtime)}",
                "timestamp": mtime,
                "priority": priority,
            }

    return discovered


def build_dashboard_payload(
    paths: DashboardPaths,
    *,
    live_images: dict[str, str] | None = None,
    live_cache: LiveCameraCache | None = None,
) -> dict[str, Any]:
    cameras = load_camera_reference(paths.camera_reference_path)
    local_frames = discover_local_frames(paths.frames_dir)
    runtime_snapshot = load_runtime_status(paths.runtime_status_path)
    runtime_lookup = runtime_snapshot.get("cameras", {})
    active_camera_ids = runtime_snapshot.get("active_camera_ids", [])
    live_lookup = live_images if live_images is not None else fetch_live_camera_images(cache=live_cache)

    camera_states = [
        _build_camera_state(
            camera=camera,
            local_frame=local_frames.get(camera["camera_id"]),
            runtime_state=runtime_lookup.get(camera["camera_id"], {}),
            approved_frame=_resolve_runtime_frame(
                paths.frames_dir,
                runtime_lookup.get(camera["camera_id"], {}).get("approved_image_path")
                if isinstance(runtime_lookup.get(camera["camera_id"], {}), dict)
                else "",
            ),
            live_lookup=live_lookup,
        )
        for camera in cameras
    ]

    default_monitor_ids = [
        camera_id
        for camera_id in active_camera_ids
        if any(camera["camera_id"] == camera_id for camera in camera_states)
    ][:1]
    if not default_monitor_ids:
        default_monitor_ids = [camera["camera_id"] for camera in camera_states[:1]]

    return {
        "generated_at": _now_iso(),
        "default_monitor_ids": default_monitor_ids,
        "active_camera_ids": active_camera_ids,
        "cameras": camera_states,
    }


def list_report_history(reports_dir: Path) -> list[dict[str, Any]]:
    if not reports_dir.exists():
        return []

    history: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("*.md"), reverse=True):
        text = path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        history.append(
            {
                "report_id": path.stem,
                "title": _extract_report_title(text, path.stem),
                "excerpt": _extract_report_excerpt(text),
                "updated_at": _format_datetime(mtime),
                "updated_at_iso": mtime.isoformat(),
                "word_count": len(text.split()),
                "section_count": sum(1 for line in text.splitlines() if line.startswith("## ")),
            }
        )
    return history


def build_reports_payload(paths: DashboardPaths) -> dict[str, Any]:
    return {
        "generated_at": _now_iso(),
        "reports": list_report_history(paths.reports_dir),
    }


def read_report_detail(reports_dir: Path, report_id: str) -> dict[str, Any]:
    if not _REPORT_ID_RE.fullmatch(report_id):
        raise FileNotFoundError(report_id)

    report_path = reports_dir / f"{report_id}.md"
    if not report_path.is_file():
        raise FileNotFoundError(report_id)

    text = report_path.read_text(encoding="utf-8")
    mtime = datetime.fromtimestamp(report_path.stat().st_mtime, tz=timezone.utc)
    return {
        "report_id": report_id,
        "title": _extract_report_title(text, report_id),
        "excerpt": _extract_report_excerpt(text),
        "updated_at": _format_datetime(mtime),
        "updated_at_iso": mtime.isoformat(),
        "word_count": len(text.split()),
        "content": text,
    }


def _build_camera_state(
    *,
    camera: dict[str, str],
    local_frame: dict[str, Any] | None,
    runtime_state: dict[str, Any],
    approved_frame: dict[str, Any] | None,
    live_lookup: dict[str, str],
) -> dict[str, Any]:
    camera_id = camera["camera_id"]
    image_url = None
    image_source = "unavailable"
    frame_timestamp: datetime | None = None
    image_candidates: list[str] = []

    resolved_candidates = _build_image_candidates(
        camera_id=camera_id,
        approved_frame=approved_frame,
        local_frame=local_frame,
        live_lookup=live_lookup,
        runtime_controlled=_is_runtime_controlled(runtime_state),
    )
    if resolved_candidates:
        primary = resolved_candidates[0]
        image_url = str(primary["url"])
        image_source = str(primary["source"])
        frame_timestamp = primary.get("timestamp")
        image_candidates = [str(candidate["url"]) for candidate in resolved_candidates]
    elif _is_runtime_controlled(runtime_state):
        image_source = "approved_frame_pending"

    runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
    metadata = runtime_state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    alerts = runtime_state.get("alerts") if isinstance(runtime_state.get("alerts"), list) else []
    first_alert = alerts[0] if alerts and isinstance(alerts[0], dict) else {}
    signals = runtime_state.get("validated_signals")
    signals = signals if isinstance(signals, dict) else {}
    active_experts = [
        str(expert).strip()
        for expert in runtime_state.get("active_experts", [])
        if str(expert).strip()
    ] if isinstance(runtime_state.get("active_experts"), list) else []
    current_agents = [
        str(agent).strip()
        for agent in runtime_state.get("current_agents", [])
        if str(agent).strip()
    ] if isinstance(runtime_state.get("current_agents"), list) else []
    last_frame_at = _parse_timestamp(runtime_state.get("last_frame_at")) or frame_timestamp
    last_analysis_at = _parse_timestamp(runtime_state.get("last_analysis_at"))

    status_level, status_label, status_detail = _derive_runtime_status(runtime_state, bool(image_url))
    status_log_fallback = (
        str(runtime_state.get("status_message", "")).strip()
        or str(first_alert.get("message", "")).strip()
        or status_detail
        or "No backend status has been published for this camera yet."
    )
    status_summary_text = _derive_status_summary_text(
        runtime_state,
        status_label=status_label,
        first_alert=first_alert,
        image_available=bool(image_url),
    )
    analysis_summary_text = (
        str(runtime_state.get("validated_text", "")).strip()
        or str(first_alert.get("message", "")).strip()
        or (
            "No completed analysis has been published for this camera yet."
            if last_analysis_at is None
            else "The latest completed analysis did not include a summary."
        )
    )
    status_history = _build_status_history(runtime_state, fallback_message=status_log_fallback)
    analysis_history = _build_analysis_history(
        runtime_state,
        fallback_summary=analysis_summary_text,
        fallback_timestamp=last_analysis_at,
    )

    return {
        "camera_id": camera_id,
        "road_type": camera["road_type"],
        "location_description": camera["location_description"],
        "area_or_key_landmark": camera["area_or_key_landmark"],
        "image_url": image_url,
        "image_source": image_source,
        "image_candidates": image_candidates,
        "status_level": status_level,
        "status_label": status_label,
        "status_detail": status_detail,
        "status_summary_text": status_summary_text,
        "status_history": status_history,
        "analysis_summary_text": analysis_summary_text,
        "analysis_history": analysis_history,
        "summary_text": analysis_summary_text,
        "severity": str(first_alert.get("severity", "")).lower() or None,
        "emergency_type": first_alert.get("emergency_type") or first_alert.get("type"),
        "dispatch_status": first_alert.get("dispatch_status"),
        "dispatch_targets": first_alert.get("dispatched_to") or [],
        "active_experts": active_experts,
        "active_agents": _derive_active_agents(
            runtime_state,
            active_experts=active_experts,
            alerts=alerts,
            validated_signals=signals,
        ),
        "current_agents": current_agents,
        "langsmith_trace_url": _extract_langsmith_trace_url(metadata),
        "signal_snapshot": {
            "vehicle_count": _coerce_int(signals.get("vehicle_count")),
            "stopped_vehicle_count": _coerce_int(signals.get("stopped_vehicle_count")),
            "blocked_lanes": _coerce_int(signals.get("blocked_lanes")),
            "queueing": bool(signals.get("queueing", False)),
            "low_visibility": bool(signals.get("low_visibility", False)),
            "water_present": bool(signals.get("water_present", False)),
        },
        "last_analysis_at": _format_datetime(last_analysis_at) if last_analysis_at else "No analysis yet",
        "last_frame_at": _format_datetime(last_frame_at) if last_frame_at else _frame_status_label(image_source),
        "frame_available": bool(image_url),
        "backend_status": str(runtime_state.get("backend_status", "")).strip(),
    }


def _derive_active_agents(
    runtime_state: dict[str, Any],
    *,
    active_experts: list[str],
    alerts: list[dict[str, Any]],
    validated_signals: dict[str, Any],
) -> list[str]:
    metadata = runtime_state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    guardrail_result = runtime_state.get("guardrail_result")
    guardrail_result = guardrail_result if isinstance(guardrail_result, dict) else {}
    validated_text = str(runtime_state.get("validated_text", "")).strip()

    agents: list[str] = []
    seen: set[str] = set()

    def add(agent_name: str, *, enabled: bool = True) -> None:
        normalized = str(agent_name).strip()
        if not enabled or not normalized or normalized in seen:
            return
        seen.add(normalized)
        agents.append(normalized)

    guardrail_ran = bool(guardrail_result or metadata.get("guardrail"))
    pipeline_progressed = bool(
        validated_text
        or validated_signals
        or active_experts
        or alerts
        or metadata.get("vlm")
        or metadata.get("validator")
        or metadata.get("orchestrator")
        or metadata.get("alert_manager")
    )
    orchestrator_ran = bool(active_experts or alerts or metadata.get("orchestrator") or metadata.get("alert_manager"))

    add("image_guardrail", enabled=guardrail_ran)
    add("vlm_agent", enabled=pipeline_progressed)
    add("validator_agent", enabled=pipeline_progressed)
    add("orchestrator_agent", enabled=orchestrator_ran)
    for expert in active_experts:
        add(expert)
    add("alert_manager", enabled=bool(alerts or metadata.get("alert_manager")))

    return agents


def _extract_langsmith_trace_url(metadata: dict[str, Any]) -> str | None:
    langsmith_metadata = metadata.get("langsmith")
    if not isinstance(langsmith_metadata, dict):
        return None

    trace_url = str(langsmith_metadata.get("trace_url", "")).strip()
    return trace_url or None


def _build_image_candidates(
    *,
    camera_id: str,
    approved_frame: dict[str, Any] | None,
    local_frame: dict[str, Any] | None,
    live_lookup: dict[str, str],
    runtime_controlled: bool,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def add_candidate(
        *,
        url: str,
        source: str,
        timestamp: datetime | None = None,
    ) -> None:
        normalized = str(url).strip()
        if not normalized or normalized in seen_urls:
            return
        seen_urls.add(normalized)
        candidates.append(
            {
                "url": normalized,
                "source": source,
                "timestamp": timestamp,
            }
        )

    if approved_frame is not None:
        add_candidate(
            url=str(approved_frame["url"]),
            source="approved_frame",
            timestamp=approved_frame.get("timestamp"),
        )
    if approved_frame is None and runtime_controlled:
        return candidates

    if local_frame is not None:
        add_candidate(
            url=str(local_frame["url"]),
            source="local_frame",
            timestamp=local_frame.get("timestamp"),
        )

    live_url = str(live_lookup.get(camera_id, "")).strip()
    if live_url:
        add_candidate(url=live_url, source="live_feed")

    return candidates


def _derive_runtime_status(runtime_state: dict[str, Any], image_available: bool) -> tuple[str, str, str]:
    raw_status = str(runtime_state.get("backend_status", "")).strip().lower()
    message = str(runtime_state.get("status_message", "")).strip()

    if _is_stale(runtime_state):
        return ("offline", "Offline", "Backend heartbeat is stale for this camera.")
    if raw_status == "starting":
        return ("monitoring", "Starting", message or "Backend is online and waiting for the first frame.")
    if raw_status in {"fetching", "processing"}:
        return ("monitoring", "Processing", message or "Backend is processing the current frame.")
    if raw_status == "fetch_error":
        return ("offline", "Feed Fault", message or "The camera feed could not be refreshed.")
    if raw_status == "alerting":
        return ("alerting", "Alerting", message or "An active incident is being tracked.")
    if raw_status == "blocked":
        return ("blocked", "Blocked", message or "The frame was blocked before analysis.")
    if raw_status == "error":
        return ("blocked", "Fault", message or "The backend raised an error.")
    if raw_status == "offline":
        return ("offline", "Offline", message or "Backend is offline for this camera.")
    if raw_status == "monitoring":
        return ("monitoring", "Monitoring", message or "Backend is monitoring this feed.")
    if image_available:
        return ("monitoring", "Standby", "Feed available. No backend status has been published yet.")
    return ("offline", "Standby", "No backend status or live feed is currently available.")


def _derive_status_summary_text(
    runtime_state: dict[str, Any],
    *,
    status_label: str,
    first_alert: dict[str, Any],
    image_available: bool,
) -> str:
    raw_status = str(runtime_state.get("backend_status", "")).strip().lower()
    emergency_type = _humanize_phrase(first_alert.get("emergency_type") or first_alert.get("type"))
    severity = _humanize_phrase(first_alert.get("severity"))

    if raw_status == "starting":
        return "Initializing monitor"
    if raw_status == "fetching":
        return "Fetching latest frame"
    if raw_status == "processing":
        return "Analyzing latest frame"
    if raw_status == "fetch_error":
        return "Camera feed unavailable"
    if raw_status == "alerting":
        if emergency_type:
            return f"{emergency_type} detected"
        if severity:
            return f"{severity} incident detected"
        return "Active incident detected"
    if raw_status == "blocked":
        return "Frame blocked by guardrail"
    if raw_status == "error":
        return "Backend attention required"
    if raw_status == "offline":
        return "Backend offline"
    if raw_status == "monitoring":
        return "Monitoring live traffic conditions"
    if image_available:
        return "Feed ready for monitoring"
    return status_label or "Status unavailable"


def _humanize_phrase(value: Any) -> str:
    normalized = str(value or "").strip().replace("_", " ")
    if not normalized:
        return ""
    return normalized[0].upper() + normalized[1:]


def _build_status_history(
    runtime_state: dict[str, Any],
    *,
    fallback_message: str,
) -> list[dict[str, Any]]:
    history = _format_history_entries(
        runtime_state.get("status_history"),
        value_key="message",
        fallback_value=fallback_message,
        fallback_timestamp=_parse_timestamp(runtime_state.get("heartbeat_at")),
        runtime_state=runtime_state,
    )
    return _mark_current_entry(history)


def _build_analysis_history(
    runtime_state: dict[str, Any],
    *,
    fallback_summary: str,
    fallback_timestamp: datetime | None,
) -> list[dict[str, Any]]:
    validated_text = str(runtime_state.get("validated_text", "")).strip()
    history = _format_history_entries(
        runtime_state.get("analysis_history"),
        value_key="summary",
        fallback_value=fallback_summary if validated_text or fallback_timestamp is not None else "",
        fallback_timestamp=fallback_timestamp,
        runtime_state=runtime_state,
    )
    return _mark_current_entry(history)


def _format_history_entries(
    raw_history: Any,
    *,
    value_key: str,
    fallback_value: str,
    fallback_timestamp: datetime | None,
    runtime_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if isinstance(raw_history, list):
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            value = str(item.get(value_key, "")).strip()
            if not value:
                continue
            timestamp = _parse_timestamp(item.get("timestamp"))
            backend_status = str(item.get("backend_status", "")).strip().lower()
            entry: dict[str, Any] = {
                "timestamp": _format_datetime(timestamp) if timestamp else "Recent",
                "timestamp_iso": timestamp.isoformat() if timestamp else "",
                "backend_status": backend_status,
                value_key: value,
            }
            if backend_status:
                entry["label"] = _status_label_for_log(backend_status)
            severity = str(item.get("severity", "")).strip().lower()
            emergency_type = str(item.get("emergency_type", "")).strip()
            if severity:
                entry["severity"] = severity
            if emergency_type:
                entry["emergency_type"] = emergency_type
            entries.append(entry)

    if entries or not fallback_value.strip():
        return entries

    fallback_status = str(runtime_state.get("backend_status", "")).strip().lower() if runtime_state else ""
    fallback_entry: dict[str, Any] = {
        "timestamp": _format_datetime(fallback_timestamp) if fallback_timestamp else "Recent",
        "timestamp_iso": fallback_timestamp.isoformat() if fallback_timestamp else "",
        "backend_status": fallback_status,
        value_key: fallback_value.strip(),
    }
    if fallback_status:
        fallback_entry["label"] = _status_label_for_log(fallback_status)
    return [fallback_entry]


def _mark_current_entry(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return []

    marked: list[dict[str, Any]] = []
    last_index = len(entries) - 1
    for index, entry in enumerate(entries):
        marked.append({**entry, "is_current": index == last_index})
    return marked


def _status_label_for_log(raw_status: str) -> str:
    normalized = str(raw_status).strip().lower()
    labels = {
        "starting": "Starting",
        "fetching": "Fetching",
        "processing": "Processing",
        "fetch_error": "Feed Fault",
        "alerting": "Alerting",
        "blocked": "Blocked",
        "error": "Fault",
        "offline": "Offline",
        "monitoring": "Monitoring",
    }
    return labels.get(normalized, normalized.replace("_", " ").title() or "Update")


def _is_stale(runtime_state: dict[str, Any]) -> bool:
    heartbeat = _parse_timestamp(runtime_state.get("heartbeat_at"))
    if heartbeat is None:
        return False

    interval = _coerce_int(runtime_state.get("interval_seconds"))
    stale_after_seconds = max(45, interval * 3 if interval > 0 else 45)
    age = datetime.now(tz=timezone.utc) - heartbeat
    return age.total_seconds() > stale_after_seconds


def _extract_report_title(text: str, fallback: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _extract_report_excerpt(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("|"):
            continue
        if line.startswith(">"):
            return line.removeprefix(">").strip()
        return line
    return "No summary preview available."


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Unavailable"
    return value.astimezone(SGT).strftime("%d %b %Y %H:%M SGT")


def _frame_status_label(image_source: str) -> str:
    if image_source == "approved_frame_pending":
        return "Awaiting approved frame"
    if image_source == "live_feed":
        return "Live feed linked"
    if image_source == "local_frame":
        return "Local frame ready"
    if image_source == "approved_frame":
        return "Approved frame ready"
    return "No frame available"


def _resolve_runtime_frame(frames_dir: Path, image_path: Any) -> dict[str, Any] | None:
    if not isinstance(image_path, str) or not image_path.strip():
        return None

    candidate = Path(image_path).expanduser()
    try:
        resolved = candidate.resolve()
        frames_root = frames_dir.resolve()
        resolved.relative_to(frames_root)
    except (OSError, ValueError):
        return None

    if not resolved.is_file():
        return None

    stat = resolved.stat()
    return {
        "url": f"/frames/{quote(resolved.name)}?v={int(stat.st_mtime)}",
        "timestamp": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    }


def _is_runtime_controlled(runtime_state: dict[str, Any]) -> bool:
    if not isinstance(runtime_state, dict) or not runtime_state:
        return False

    for key in ("backend_status", "heartbeat_at", "image_path", "approved_image_path"):
        value = runtime_state.get(key)
        if isinstance(value, str) and value.strip():
            return True

    return False


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
