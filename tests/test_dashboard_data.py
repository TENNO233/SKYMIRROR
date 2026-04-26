from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from skymirror.dashboard.data import (
    DashboardPaths,
    build_dashboard_payload,
    build_reports_payload,
    read_report_detail,
)
from skymirror.tools.dashboard_status import (
    load_runtime_status,
    set_runtime_active_cameras,
    write_camera_runtime_status,
)


def _build_paths(tmp_path: Path) -> DashboardPaths:
    data_root = tmp_path / "data"
    static_dir = tmp_path / "static"
    frames_dir = data_root / "frames"
    reports_dir = data_root / "reports"
    sources_dir = data_root / "sources"
    dashboard_dir = data_root / "dashboard"

    static_dir.mkdir(parents=True)
    frames_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)

    reference = [
        {
            "camera_id": "1703",
            "road_type": "Expressway",
            "location_description": "View from Yio Chu Kang Flyover",
            "area_or_key_landmark": "CTE (Near Ang Mo Kio/Yio Chu Kang)",
        },
        {
            "camera_id": "2701",
            "road_type": "Expressway",
            "location_description": "View from Woodlands Checkpoint (Towards BKE)",
            "area_or_key_landmark": "BKE (Woodlands Checkpoint Entrance)",
        },
    ]
    (sources_dir / "traffic_camera_reference.json").write_text(
        json.dumps(reference), encoding="utf-8"
    )

    return DashboardPaths(
        project_root=tmp_path,
        static_dir=static_dir,
        frames_dir=frames_dir,
        reports_dir=reports_dir,
        camera_reference_path=sources_dir / "traffic_camera_reference.json",
        runtime_status_path=dashboard_dir / "live_status.json",
    )


def _make_case_dir(case_name: str) -> Path:
    root = Path.cwd() / ".dashboard_test_workspace" / f"{case_name}_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_build_dashboard_payload_uses_only_guardrail_approved_frames() -> None:
    case_dir = _make_case_dir("payload")
    try:
        paths = _build_paths(case_dir)
        (paths.frames_dir / "cam1703_latest.jpg").write_bytes(b"jpg")

        write_camera_runtime_status(
            paths.runtime_status_path,
            camera_id="1703",
            backend_status="alerting",
            interval_seconds=20,
            image_path=str(paths.frames_dir / "cam1703_latest.jpg"),
            message="Collision response under dispatch",
            final_state={
                "guardrail_result": {"allowed": True, "status": "allowed"},
                "validated_text": "Vehicle collision with blockage.",
                "validated_signals": {
                    "vehicle_count": 4,
                    "stopped_vehicle_count": 2,
                    "blocked_lanes": 1,
                    "queueing": True,
                },
                "active_experts": ["safety_expert", "environment_expert"],
                "alerts": [
                    {
                        "message": "Collision response under dispatch",
                        "severity": "critical",
                        "emergency_type": "traffic_accident",
                        "dispatch_status": "success",
                        "dispatched_to": ["traffic_police", "ambulance"],
                    }
                ],
                "metadata": {
                    "langsmith": {
                        "trace_url": "https://smith.langchain.com/o/test/projects/p/test/r/abc123?poll=true",
                    }
                },
            },
        )
        set_runtime_active_cameras(paths.runtime_status_path, ["2701", "1703"])

        payload = build_dashboard_payload(
            paths,
            live_images={
                "1703": "https://example.test/1703.jpg",
                "2701": "https://example.test/2701.jpg",
            },
        )

        assert payload["default_monitor_ids"] == ["2701"]
        first = payload["cameras"][0]
        second = payload["cameras"][1]

        assert first["camera_id"] == "1703"
        assert first["image_source"] == "approved_frame"
        assert first["image_url"].startswith("/frames/cam1703_latest.jpg")
        assert first["image_candidates"][0].startswith("/frames/cam1703_latest.jpg")
        assert first["status_level"] == "alerting"
        assert first["status_summary_text"] == "Traffic accident detected"
        assert first["status_history"][-1]["message"] == "Collision response under dispatch"
        assert first["analysis_summary_text"] == "Vehicle collision with blockage."
        assert first["analysis_history"][-1]["summary"] == "Vehicle collision with blockage."
        assert first["dispatch_targets"] == ["traffic_police", "ambulance"]
        assert first["signal_snapshot"]["queueing"] is True
        assert first["active_experts"] == ["safety_expert", "environment_expert"]
        assert first["current_agents"] == []
        assert first["active_agents"] == [
            "image_guardrail",
            "vlm_agent",
            "validator_agent",
            "orchestrator_agent",
            "safety_expert",
            "environment_expert",
            "alert_manager",
        ]
        assert (
            first["langsmith_trace_url"]
            == "https://smith.langchain.com/o/test/projects/p/test/r/abc123?poll=true"
        )
        assert first["summary_text"] == "Vehicle collision with blockage."

        assert second["camera_id"] == "2701"
        assert second["image_source"] == "live_feed"
        assert second["image_candidates"] == ["https://example.test/2701.jpg"]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_build_dashboard_payload_holds_unapproved_frame_off_monitor() -> None:
    case_dir = _make_case_dir("guardrail_hold")
    try:
        paths = _build_paths(case_dir)
        (paths.frames_dir / "cam1703_latest.jpg").write_bytes(b"jpg")

        write_camera_runtime_status(
            paths.runtime_status_path,
            camera_id="1703",
            backend_status="processing",
            interval_seconds=20,
            image_path=str(paths.frames_dir / "cam1703_latest.jpg"),
            message="Frame fetched. Running guardrail and pipeline analysis.",
        )
        set_runtime_active_cameras(paths.runtime_status_path, ["1703"])

        payload = build_dashboard_payload(
            paths,
            live_images={"1703": "https://example.test/1703.jpg"},
        )

        camera = payload["cameras"][0]
        assert camera["camera_id"] == "1703"
        assert camera["image_url"] is None
        assert camera["image_source"] == "approved_frame_pending"
        assert camera["last_frame_at"] == "Awaiting approved frame"
        assert camera["status_label"] == "Processing"
        assert camera["status_summary_text"] == "Analyzing latest frame"
        assert (
            camera["analysis_summary_text"]
            == "No completed analysis has been published for this camera yet."
        )
        assert camera["analysis_history"] == []
        assert camera["current_agents"] == []
        assert camera["active_agents"] == []
        assert camera["langsmith_trace_url"] is None
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_write_camera_runtime_status_preserves_history_without_duplicates() -> None:
    case_dir = _make_case_dir("runtime_history")
    try:
        paths = _build_paths(case_dir)
        frame_path = paths.frames_dir / "cam1703_latest.jpg"
        frame_path.write_bytes(b"jpg")

        write_camera_runtime_status(
            paths.runtime_status_path,
            camera_id="1703",
            backend_status="starting",
            interval_seconds=20,
            message="Daemon online. Awaiting first camera fetch.",
        )
        write_camera_runtime_status(
            paths.runtime_status_path,
            camera_id="1703",
            backend_status="starting",
            interval_seconds=20,
            message="Daemon online. Awaiting first camera fetch.",
        )
        write_camera_runtime_status(
            paths.runtime_status_path,
            camera_id="1703",
            backend_status="processing",
            interval_seconds=20,
            image_path=str(frame_path),
            message="Frame fetched. Running guardrail and pipeline analysis.",
        )
        write_camera_runtime_status(
            paths.runtime_status_path,
            camera_id="1703",
            backend_status="monitoring",
            interval_seconds=20,
            image_path=str(frame_path),
            message="Frame processed successfully.",
            final_state={
                "guardrail_result": {"allowed": True, "status": "allowed"},
                "validated_text": "Traffic remains steady with no active incident.",
                "alerts": [],
            },
        )
        write_camera_runtime_status(
            paths.runtime_status_path,
            camera_id="1703",
            backend_status="monitoring",
            interval_seconds=20,
            image_path=str(frame_path),
            message="Frame processed successfully.",
            final_state={
                "guardrail_result": {"allowed": True, "status": "allowed"},
                "validated_text": "Traffic remains steady with no active incident.",
                "alerts": [],
            },
        )

        snapshot = load_runtime_status(paths.runtime_status_path)
        camera = snapshot["cameras"]["1703"]

        assert [entry["message"] for entry in camera["status_history"]] == [
            "Daemon online. Awaiting first camera fetch.",
            "Frame fetched. Running guardrail and pipeline analysis.",
            "Frame processed successfully.",
        ]
        assert [entry["summary"] for entry in camera["analysis_history"]] == [
            "Traffic remains steady with no active incident."
        ]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_build_reports_payload_and_report_detail() -> None:
    case_dir = _make_case_dir("reports")
    try:
        paths = _build_paths(case_dir)
        report_text = "\n".join(
            [
                "# SKYMIRROR Daily Report - 2026-04-15",
                "",
                "## 1. Daily Overview",
                "",
                "| Metric | Value |",
                "|---|---|",
                "| Frames | 12 |",
                "",
                "Daily operations remained stable.",
            ]
        )
        (paths.reports_dir / "2026-04-15.md").write_text(report_text, encoding="utf-8")

        payload = build_reports_payload(paths)
        assert len(payload["reports"]) == 1
        assert payload["reports"][0]["report_id"] == "2026-04-15"
        assert payload["reports"][0]["title"] == "SKYMIRROR Daily Report - 2026-04-15"

        detail = read_report_detail(paths.reports_dir, "2026-04-15")
        assert "Daily operations remained stable." in detail["content"]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
