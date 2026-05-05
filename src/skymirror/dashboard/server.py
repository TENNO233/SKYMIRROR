"""Small HTTP server for the SKYMIRROR dashboard."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any, BinaryIO
from urllib.parse import unquote, urlparse

from skymirror.dashboard.data import (
    DashboardPaths,
    LiveCameraCache,
    build_dashboard_payload,
    build_reports_payload,
    default_dashboard_paths,
    load_camera_reference,
    read_report_detail,
)
from skymirror.tools.dashboard_status import (
    set_runtime_active_cameras,
    write_camera_runtime_status,
)

logger = logging.getLogger(__name__)


class DashboardRuntimeManager:
    """Manage one backend camera daemon at a time for the dashboard."""

    def __init__(
        self,
        dashboard_paths: DashboardPaths,
        *,
        python_executable: str | None = None,
    ) -> None:
        self.dashboard_paths = dashboard_paths
        self.python_executable = python_executable or sys.executable
        self._lock = RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_handle: BinaryIO | None = None
        self._stderr_handle: BinaryIO | None = None
        self._control_dir = self.dashboard_paths.runtime_status_path.parent
        self._control_dir.mkdir(parents=True, exist_ok=True)
        self._selected_camera_path = self._control_dir / "selected_camera.json"
        self._backend_stdout_path = self._control_dir / "backend_daemon.out.log"
        self._backend_stderr_path = self._control_dir / "backend_daemon.err.log"

    def ensure_backend_running(self) -> str:
        with self._lock:
            camera_id = self._load_selected_camera_id_unlocked()
            if self._process_is_running_unlocked():
                return camera_id
            self._start_backend_unlocked(camera_id)
            return camera_id

    def switch_camera(self, camera_id: str) -> str:
        selected_camera_id = self._validate_camera_id(camera_id)
        with self._lock:
            current_camera_id = self._load_selected_camera_id_unlocked()
            if selected_camera_id == current_camera_id and self._process_is_running_unlocked():
                return selected_camera_id

            self._stop_backend_unlocked()
            self._start_backend_unlocked(selected_camera_id)
            return selected_camera_id

    def shutdown(self) -> None:
        with self._lock:
            self._stop_backend_unlocked()

    def _process_is_running_unlocked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _list_camera_ids(self) -> list[str]:
        return [
            row["camera_id"]
            for row in load_camera_reference(self.dashboard_paths.camera_reference_path)
            if row.get("camera_id")
        ]

    def _validate_camera_id(self, camera_id: str) -> str:
        selected_camera_id = str(camera_id).strip()
        if not selected_camera_id:
            raise ValueError("camera_id is required.")

        available_camera_ids = self._list_camera_ids()
        if selected_camera_id not in available_camera_ids:
            raise ValueError(f"Unknown camera_id: {selected_camera_id}")
        return selected_camera_id

    def _load_selected_camera_id_unlocked(self) -> str:
        if self._selected_camera_path.is_file():
            try:
                payload = json.loads(self._selected_camera_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("dashboard: could not read selected camera state: %s", exc)
            else:
                selected_camera_id = str(payload.get("camera_id", "")).strip()
                if selected_camera_id:
                    return self._validate_camera_id(selected_camera_id)

        available_camera_ids = self._list_camera_ids()
        if not available_camera_ids:
            raise RuntimeError("No camera reference entries are available for the dashboard.")
        return available_camera_ids[0]

    def _write_selected_camera_id_unlocked(self, camera_id: str) -> None:
        payload = {"camera_id": camera_id}
        self._selected_camera_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _start_backend_unlocked(self, camera_id: str) -> None:
        interval_seconds = int(os.getenv("PROCESSING_INTERVAL_SECONDS", "20"))
        self._write_selected_camera_id_unlocked(camera_id)
        set_runtime_active_cameras(self.dashboard_paths.runtime_status_path, [camera_id])
        write_camera_runtime_status(
            self.dashboard_paths.runtime_status_path,
            camera_id=camera_id,
            backend_status="starting",
            interval_seconds=interval_seconds,
            message="Switching backend to the selected camera.",
        )

        env = os.environ.copy()
        src_path = str(self.dashboard_paths.project_root / "src")
        current_python_path = env.get("PYTHONPATH", "").strip()
        env["PYTHONPATH"] = (
            src_path
            if not current_python_path
            else os.pathsep.join([src_path, current_python_path])
        )
        env["TARGET_CAMERA_IDS"] = camera_id
        env["TARGET_CAMERA_ID"] = camera_id

        self._stdout_handle = self._backend_stdout_path.open("ab")
        self._stderr_handle = self._backend_stderr_path.open("ab")
        self._process = subprocess.Popen(
            [self.python_executable, "-m", "skymirror.main"],
            cwd=str(self.dashboard_paths.project_root),
            env=env,
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
        )
        logger.info(
            "dashboard: started backend daemon for camera %s (pid=%s)", camera_id, self._process.pid
        )

    def _stop_backend_unlocked(self) -> None:
        process = self._process
        if process is None:
            self._close_log_handles_unlocked()
            return

        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            self._process = None
            self._close_log_handles_unlocked()

    def _close_log_handles_unlocked(self) -> None:
        if self._stdout_handle is not None:
            self._stdout_handle.close()
            self._stdout_handle = None
        if self._stderr_handle is not None:
            self._stderr_handle.close()
            self._stderr_handle = None


class DashboardHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying repo paths, caches, and runtime control."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        dashboard_paths: DashboardPaths,
        runtime_manager: DashboardRuntimeManager,
    ) -> None:
        self.dashboard_paths = dashboard_paths
        self.live_cache = LiveCameraCache()
        self.runtime_manager = runtime_manager
        super().__init__(server_address, handler_class)

    def server_close(self) -> None:
        runtime_manager = getattr(self, "runtime_manager", None)
        if runtime_manager is not None:
            runtime_manager.shutdown()
        super().server_close()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route_path = parsed.path

        try:
            if route_path in {"/", "/index.html"}:
                self._serve_static("index.html", content_type="text/html; charset=utf-8")
                return
            if route_path == "/styles.css":
                self._serve_static("styles.css", content_type="text/css; charset=utf-8")
                return
            if route_path == "/app.js":
                self._serve_static("app.js", content_type="application/javascript; charset=utf-8")
                return
            if route_path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            if route_path == "/health":
                self._serve_json({"status": "ok"})
                return
            if route_path == "/api/dashboard":
                payload = build_dashboard_payload(
                    self.server.dashboard_paths,
                    live_cache=self.server.live_cache,
                )
                self._serve_json(payload)
                return
            if route_path == "/api/reports":
                self._serve_json(build_reports_payload(self.server.dashboard_paths))
                return
            if route_path.startswith("/api/reports/"):
                report_id = route_path.removeprefix("/api/reports/")
                payload = read_report_detail(self.server.dashboard_paths.reports_dir, report_id)
                self._serve_json(payload)
                return
            if route_path.startswith("/frames/"):
                frame_name = Path(unquote(route_path.removeprefix("/frames/"))).name
                self._serve_file(self.server.dashboard_paths.frames_dir / frame_name)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Route not found.")
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND, "Resource not found.")
        except Exception as exc:  # pragma: no cover - defensive server guard
            logger.exception("dashboard request failed: %s", exc)
            self._serve_json(
                {"error": "Internal server error."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route_path = parsed.path

        try:
            if route_path == "/api/runtime/select-camera":
                payload = self._read_json_body()
                camera_id = str(payload.get("camera_id", "")).strip()
                self.server.runtime_manager.switch_camera(camera_id)
                dashboard_payload = build_dashboard_payload(
                    self.server.dashboard_paths,
                    live_cache=self.server.live_cache,
                )
                self._serve_json(dashboard_payload)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Route not found.")
        except ValueError as exc:
            self._serve_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - defensive server guard
            logger.exception("dashboard POST failed: %s", exc)
            self._serve_json(
                {"error": "Internal server error."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("dashboard: " + format, *args)

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0").strip() or "0"
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc

        body = self.rfile.read(content_length) if content_length > 0 else b""
        if not body:
            return {}

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc

        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _serve_static(self, filename: str, *, content_type: str) -> None:
        self._serve_file(
            self.server.dashboard_paths.static_dir / filename, content_type=content_type
        )

    def _serve_file(self, path: Path, *, content_type: str | None = None) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)

        body = path.read_bytes()
        resolved_type = content_type or _guess_content_type(path)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", resolved_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript; charset=utf-8"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def serve_dashboard(host: str = "127.0.0.1", port: int = 8787) -> None:
    paths = default_dashboard_paths()
    runtime_manager = DashboardRuntimeManager(paths)
    try:
        runtime_manager.ensure_backend_running()
    except Exception as exc:
        logger.warning("dashboard: backend manager startup failed: %s", exc)

    httpd = DashboardHTTPServer(
        (host, port),
        DashboardRequestHandler,
        dashboard_paths=paths,
        runtime_manager=runtime_manager,
    )

    logger.info("SKYMIRROR dashboard serving on http://%s:%d", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("dashboard: shutdown requested by keyboard interrupt")
    finally:
        httpd.server_close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="skymirror-dashboard",
        description="Serve the SKYMIRROR operations dashboard.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    serve_dashboard(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
