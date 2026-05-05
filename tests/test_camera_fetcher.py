from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from skymirror.tools.camera_fetcher import fetch_latest_frame, publish_latest_frame


def _make_case_dir(case_name: str) -> Path:
    root = Path.cwd() / ".dashboard_test_workspace" / f"{case_name}_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


class _FakeResponse:
    def __init__(self, *, payload=None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_fetch_latest_frame_does_not_publish_latest_before_approval(monkeypatch) -> None:
    case_dir = _make_case_dir("camera_fetcher_hold")
    try:
        frames_dir = case_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        responses = iter(
            [
                _FakeResponse(
                    payload={
                        "items": [
                            {
                                "cameras": [
                                    {
                                        "camera_id": "1703",
                                        "image": "https://example.test/cam1703.jpg",
                                    }
                                ]
                            }
                        ]
                    }
                ),
                _FakeResponse(content=b"jpeg-bytes"),
            ]
        )

        monkeypatch.setattr(
            "skymirror.tools.camera_fetcher.requests.get",
            lambda *args, **kwargs: next(responses),
        )

        image_path = fetch_latest_frame("1703", frames_dir, keep_history=True)

        assert image_path is not None
        assert Path(image_path).name.startswith("cam1703_")
        assert Path(image_path).name != "cam1703_latest.jpg"
        assert not (frames_dir / "cam1703_latest.jpg").exists()
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_publish_latest_frame_promotes_approved_frame() -> None:
    case_dir = _make_case_dir("camera_fetcher_promote")
    try:
        frames_dir = case_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        source = frames_dir / "cam1703_20260417_010000.jpg"
        source.write_bytes(b"approved-jpeg")

        latest_path = publish_latest_frame("1703", frames_dir, source)

        assert latest_path is not None
        assert Path(latest_path).name == "cam1703_latest.jpg"
        assert (frames_dir / "cam1703_latest.jpg").read_bytes() == b"approved-jpeg"
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
