from __future__ import annotations

import json
from pathlib import Path
import shutil
from uuid import uuid4

from skymirror.dashboard.data import DashboardPaths
from skymirror.dashboard.server import DashboardRuntimeManager
from skymirror.tools.dashboard_status import load_runtime_status


def _make_case_dir(case_name: str) -> Path:
    root = Path.cwd() / ".dashboard_test_workspace" / f"{case_name}_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


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
    (sources_dir / "traffic_camera_reference.json").write_text(json.dumps(reference), encoding="utf-8")

    return DashboardPaths(
        project_root=tmp_path,
        static_dir=static_dir,
        frames_dir=frames_dir,
        reports_dir=reports_dir,
        camera_reference_path=sources_dir / "traffic_camera_reference.json",
        runtime_status_path=dashboard_dir / "live_status.json",
    )


class _FakeProcess:
    _next_pid = 4000

    def __init__(self, command, **kwargs) -> None:
        self.command = command
        self.cwd = kwargs.get("cwd")
        self.env = kwargs.get("env", {})
        self.stdout = kwargs.get("stdout")
        self.stderr = kwargs.get("stderr")
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.pid = _FakeProcess._next_pid
        _FakeProcess._next_pid += 1

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_runtime_manager_switches_single_backend_process(monkeypatch) -> None:
    case_dir = _make_case_dir("dashboard_runtime")
    try:
        paths = _build_paths(case_dir)
        spawned_processes: list[_FakeProcess] = []

        def _popen(command, **kwargs):
            process = _FakeProcess(command, **kwargs)
            spawned_processes.append(process)
            return process

        monkeypatch.setattr("skymirror.dashboard.server.subprocess.Popen", _popen)

        manager = DashboardRuntimeManager(paths, python_executable="python.exe")
        first_camera = manager.switch_camera("1703")
        assert first_camera == "1703"
        assert len(spawned_processes) == 1
        assert spawned_processes[0].env["TARGET_CAMERA_IDS"] == "1703"

        snapshot = load_runtime_status(paths.runtime_status_path)
        assert snapshot["active_camera_ids"] == ["1703"]

        second_camera = manager.switch_camera("2701")
        assert second_camera == "2701"
        assert len(spawned_processes) == 2
        assert spawned_processes[0].terminated is True
        assert spawned_processes[1].env["TARGET_CAMERA_IDS"] == "2701"

        snapshot = load_runtime_status(paths.runtime_status_path)
        assert snapshot["active_camera_ids"] == ["2701"]

        manager.shutdown()
        assert spawned_processes[1].terminated is True
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
