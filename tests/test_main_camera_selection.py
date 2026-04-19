from __future__ import annotations

import json
from pathlib import Path
import shutil
from uuid import uuid4


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
