from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest


def _make_case_dir(case_name: str) -> Path:
    root = Path.cwd() / ".dashboard_test_workspace" / f"{case_name}_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_resolve_target_camera_ids_prefers_multi_camera_env(monkeypatch) -> None:
    from skymirror import main as skymirror_main

    case_dir = _make_case_dir("camera_ids_env")
    try:
        reference_path = case_dir / "traffic_camera_reference.json"
        reference_path.write_text(
            json.dumps(
                [
                    {"camera_id": "1703"},
                    {"camera_id": "2701"},
                ]
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(skymirror_main, "_DEFAULT_CAMERA_REFERENCE_PATH", str(reference_path))
        monkeypatch.setenv("TARGET_CAMERA_IDS", "1502, 1703")
        monkeypatch.setenv("TARGET_CAMERA_ID", "4798")

        assert skymirror_main._resolve_target_camera_ids() == ["1502", "1703"]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_resolve_target_camera_ids_defaults_to_reference(monkeypatch) -> None:
    from skymirror import main as skymirror_main

    case_dir = _make_case_dir("camera_ids_default")
    try:
        reference_path = case_dir / "traffic_camera_reference.json"
        reference_path.write_text(
            json.dumps(
                [
                    {"camera_id": "1703"},
                    {"camera_id": "2701"},
                    {"camera_id": "1502"},
                ]
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(skymirror_main, "_DEFAULT_CAMERA_REFERENCE_PATH", str(reference_path))
        monkeypatch.delenv("TARGET_CAMERA_IDS", raising=False)
        monkeypatch.delenv("TARGET_CAMERA_ID", raising=False)

        assert skymirror_main._resolve_target_camera_ids() == ["1703", "2701"]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_parse_args_accepts_once_mode() -> None:
    from skymirror import main as skymirror_main

    args = skymirror_main._parse_args(["--once"])

    assert args.once is True
    assert args.image is None
    assert args.report is False


def test_env_flag_enabled_recognises_true_values(monkeypatch) -> None:
    from skymirror import main as skymirror_main

    monkeypatch.setenv("SKYMIRROR_RUN_ONCE", "true")
    assert skymirror_main._env_flag_enabled("SKYMIRROR_RUN_ONCE") is True

    monkeypatch.setenv("SKYMIRROR_RUN_ONCE", "0")
    assert skymirror_main._env_flag_enabled("SKYMIRROR_RUN_ONCE") is False


def test_run_multi_camera_daemon_exits_cleanly_in_once_mode(monkeypatch) -> None:
    from skymirror import main as skymirror_main

    calls: list[dict[str, object]] = []
    skymirror_main._shutdown_requested = False

    def fake_run_daemon(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(skymirror_main, "_run_daemon", fake_run_daemon)
    monkeypatch.setattr(
        skymirror_main, "set_runtime_active_cameras", lambda *_args, **_kwargs: None
    )

    skymirror_main._run_multi_camera_daemon(
        app=object(),
        camera_ids=["1703", "2701"],
        frames_dir=Path("data/frames"),
        interval=20,
        keep_history=True,
        status_path=Path("data/dashboard/live_status.json"),
        run_once=True,
    )

    assert len(calls) == 2
    assert {str(call["camera_id"]) for call in calls} == {"1703", "2701"}
    assert all(call["run_once"] is True for call in calls)


def test_sleep_until_next_cycle_waits_remaining_time(monkeypatch) -> None:
    from skymirror import main as skymirror_main

    clock = {"now": 12.0}
    sleeps: list[float] = []
    skymirror_main._shutdown_requested = False

    monkeypatch.setattr(skymirror_main.time, "monotonic", lambda: clock["now"])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(skymirror_main.time, "sleep", fake_sleep)

    skymirror_main._sleep_until_next_cycle(cycle_started_at=0.0, interval_seconds=30)

    assert sum(sleeps) == pytest.approx(18.0)
    assert clock["now"] == pytest.approx(30.0)


def test_sleep_until_next_cycle_does_not_wait_when_cycle_exceeds_interval(monkeypatch) -> None:
    from skymirror import main as skymirror_main

    sleeps: list[float] = []
    skymirror_main._shutdown_requested = False

    monkeypatch.setattr(skymirror_main.time, "monotonic", lambda: 35.0)
    monkeypatch.setattr(skymirror_main.time, "sleep", lambda seconds: sleeps.append(seconds))

    skymirror_main._sleep_until_next_cycle(cycle_started_at=0.0, interval_seconds=30)

    assert sleeps == []


def test_apply_task_stream_part_tracks_running_dashboard_agents() -> None:
    from skymirror import main as skymirror_main

    running_agents: set[str] = set()

    started = skymirror_main._apply_task_stream_part(
        {
            "type": "tasks",
            "data": {
                "id": "task-1",
                "name": "image_guardrail",
                "input": {},
                "triggers": ["workflow_router"],
            },
        },
        running_agents,
    )
    assert started is True
    assert running_agents == {"image_guardrail"}

    ignored = skymirror_main._apply_task_stream_part(
        {
            "type": "tasks",
            "data": {
                "id": "task-2",
                "name": "workflow_router",
                "input": {},
                "triggers": ["__start__"],
            },
        },
        running_agents,
    )
    assert ignored is False
    assert running_agents == {"image_guardrail"}

    finished = skymirror_main._apply_task_stream_part(
        {
            "type": "tasks",
            "data": {
                "id": "task-1",
                "name": "image_guardrail",
                "result": {"guardrail_result": {"allowed": True}},
                "interrupts": [],
                "error": None,
            },
        },
        running_agents,
    )
    assert finished is True
    assert running_agents == set()
