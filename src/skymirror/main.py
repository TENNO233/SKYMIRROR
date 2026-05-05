"""
main.py — SKYMIRROR Application Entry Point
=============================================
Long-running daemon that polls one or more Singapore LTA traffic cameras every
PROCESSING_INTERVAL_SECONDS, feeds each frame through the LangGraph pipeline,
and logs the resulting alerts.

Execution modes
---------------
    # Normal daemon (reads TARGET_CAMERA_IDS, or falls back to the first two
    # cameras in the dashboard reference file):
    python -m skymirror.main

    # Single live-camera cycle (fetch, process, exit):
    python -m skymirror.main --once

    # Single-shot with a local image (skips camera fetch, useful for testing):
    python -m skymirror.main --image /path/to/frame.jpg

    # Fire the daily report generator immediately and exit:
    python -m skymirror.main --report

Architecture
------------
                  ┌─────────────────────────────────────────┐
    every 20 s    │                                         │
    ─────────────►│  camera_fetcher.fetch_latest_frame()    │
                  │           │ image_path                  │
                  │           ▼                             │
                  │  app.invoke({"image_path": ...})        │  ← LangGraph
                  │           │ SkymirrorState              │
                  │           ▼                             │
                  │  log state["alerts"]                    │
                  └─────────────────────────────────────────┘
                  APScheduler: generate_daily_report @ 00:05 UTC (background)

Graceful shutdown
-----------------
SIGINT (Ctrl-C) and SIGTERM both trigger a clean exit:
  - The current pipeline invocation is allowed to finish.
  - APScheduler is shut down (jobs are not interrupted mid-run).
  - A final log line is emitted before the process exits.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from threading import Thread
from typing import Any

from dotenv import load_dotenv
from langsmith import traceable

from skymirror.tools.dashboard_status import (
    clear_runtime_active_cameras,
    set_runtime_active_cameras,
    write_camera_runtime_status,
)
from skymirror.tools.governance import policy_snapshot
from skymirror.tools.langsmith_utils import flush_langsmith_traces
from skymirror.tools.run_records import build_run_record, new_run_id, write_run_record

# Load .env FIRST — before any module that reads os.environ
load_dotenv()

logger = logging.getLogger(__name__)
_HISTORY_WINDOW_SIZE: int = 5
_DEFAULT_DASHBOARD_STATUS_PATH = "data/dashboard/live_status.json"
_DEFAULT_CAMERA_REFERENCE_PATH = "data/sources/traffic_camera_reference.json"
_DEFAULT_OA_LOG_DIR = "data/oa_log"
_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_DASHBOARD_AGENT_ORDER = (
    "image_guardrail",
    "vlm_agent",
    "validator_agent",
    "orchestrator_agent",
    "order_expert",
    "safety_expert",
    "environment_expert",
    "alert_manager",
)
_DASHBOARD_AGENT_NAMES = frozenset(_DASHBOARD_AGENT_ORDER)

# ---------------------------------------------------------------------------
# Shutdown flag — set by signal handlers, checked in the main loop
# ---------------------------------------------------------------------------
_shutdown_requested: bool = False


def _handle_signal(signum: int, _frame: Any) -> None:
    """Signal handler: request graceful shutdown."""
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — finishing current iteration then shutting down.", sig_name)
    _shutdown_requested = True


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    """
    Configure the root logger.

    In production (LOG_LEVEL=INFO or above) emits one-line records.
    Set LOG_LEVEL=DEBUG for verbose per-request tracing.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )
    # Quieten noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def _publish_dashboard_status(
    *,
    status_path: Path,
    camera_id: str,
    backend_status: str,
    interval_seconds: int,
    image_path: str = "",
    final_state: dict[str, Any] | None = None,
    message: str = "",
) -> None:
    try:
        write_camera_runtime_status(
            status_path=status_path,
            camera_id=camera_id,
            backend_status=backend_status,
            interval_seconds=interval_seconds,
            image_path=image_path,
            final_state=final_state,
            message=message,
        )
    except Exception as exc:
        logger.warning("Dashboard status update failed for camera %s: %s", camera_id, exc)


def _load_default_camera_ids(limit: int = 2) -> list[str]:
    reference_path = Path(_DEFAULT_CAMERA_REFERENCE_PATH)
    if not reference_path.is_file():
        return []

    try:
        rows = json.loads(reference_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read camera reference file %s: %s", reference_path, exc)
        return []

    camera_ids: list[str] = []
    for row in rows:
        camera_id = str(row.get("camera_id", "")).strip()
        if camera_id and camera_id not in camera_ids:
            camera_ids.append(camera_id)
        if len(camera_ids) >= limit:
            break
    return camera_ids


def _parse_camera_ids(raw_value: str) -> list[str]:
    camera_ids: list[str] = []
    for part in raw_value.split(","):
        camera_id = part.strip()
        if camera_id and camera_id not in camera_ids:
            camera_ids.append(camera_id)
    return camera_ids


def _resolve_target_camera_ids() -> list[str]:
    raw_ids = os.getenv("TARGET_CAMERA_IDS", "").strip()
    if raw_ids:
        return _parse_camera_ids(raw_ids)

    default_ids = _load_default_camera_ids(limit=2)
    if default_ids:
        return default_ids

    explicit_single = os.getenv("TARGET_CAMERA_ID", "").strip()
    if explicit_single:
        return [explicit_single]

    return ["4798"]


def _resolve_oa_log_dir() -> Path:
    return Path(os.getenv("OA_LOG_DIR", _DEFAULT_OA_LOG_DIR)).resolve()


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE_ENV_VALUES


def _ensure_record_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(metadata or {})
    for key in ("models", "prompts", "policies", "retrieval", "external_calls"):
        nested = payload.get(key)
        payload[key] = dict(nested) if isinstance(nested, dict) else {}
    return payload


def _write_run_record_safe(
    *,
    run_id: str,
    workflow_mode: str,
    camera_id: str,
    image_path: str,
    status: str,
    guardrail_result: dict[str, Any] | None = None,
    validated_text: str = "",
    validated_signals: dict[str, Any] | None = None,
    active_experts: list[str] | None = None,
    expert_results: dict[str, Any] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        record = build_run_record(
            run_id=run_id,
            workflow_mode=workflow_mode,
            camera_id=camera_id,
            image_path=image_path,
            status=status,
            guardrail_result=guardrail_result,
            validated_text=validated_text,
            validated_signals=validated_signals,
            active_experts=active_experts,
            expert_results=expert_results,
            alerts=alerts,
            metadata=_ensure_record_metadata(metadata),
        )
        write_run_record(_resolve_oa_log_dir(), record)
    except Exception as exc:
        logger.warning("Failed to write RunRecord for %s/%s: %s", camera_id, status, exc)


def _sleep_until_next_cycle(*, cycle_started_at: float, interval_seconds: int) -> None:
    """Maintain a fixed cycle cadence measured from the iteration start."""
    deadline = cycle_started_at + max(interval_seconds, 0)
    while not _shutdown_requested:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def _apply_task_stream_part(part: dict[str, Any], running_agents: set[str]) -> bool:
    if part.get("type") != "tasks":
        return False

    payload = part.get("data")
    if not isinstance(payload, dict):
        return False

    agent_name = str(payload.get("name", "")).strip()
    if agent_name not in _DASHBOARD_AGENT_NAMES:
        return False

    before = set(running_agents)
    if "input" in payload:
        running_agents.add(agent_name)
    else:
        running_agents.discard(agent_name)
    return running_agents != before


# ---------------------------------------------------------------------------
# Pipeline runner (single iteration)
# ---------------------------------------------------------------------------


def _build_history_entry(final_state: dict[str, Any]) -> dict[str, Any]:
    """Persist only the fields needed by downstream temporal reasoning."""
    return {
        "image_path": final_state.get("image_path", ""),
        "validated_scene": final_state.get("validated_scene", {}),
        "validated_text": final_state.get("validated_text", ""),
        "validated_signals": final_state.get("validated_signals", {}),
        "expert_results": final_state.get("expert_results", {}),
    }


def _trace_run_pipeline_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    history_context = inputs.get("history_context") or []
    return {
        "workflow_mode": str(inputs.get("workflow_mode", "frame")),
        "image_path": str(inputs.get("image_path", "")),
        "history_count": len(history_context),
    }


def _trace_run_pipeline_output(output: dict[str, Any] | None) -> dict[str, Any]:
    if output is None:
        return {"status": "failed"}

    guardrail_result = output.get("guardrail_result", {})
    blocked = bool(guardrail_result and not guardrail_result.get("allowed", False))
    return {
        "status": "blocked" if blocked else "completed",
        "alerts_count": len(output.get("alerts", [])),
        "active_experts": list(output.get("active_experts", [])),
        "has_validated_text": bool(output.get("validated_text", "").strip()),
    }


@traceable(
    name="run_pipeline",
    run_type="chain",
    process_inputs=_trace_run_pipeline_inputs,
    process_outputs=_trace_run_pipeline_output,
)
def _run_pipeline(
    image_path: str,
    app: Any,
    history_context: list[dict[str, Any]] | None = None,
    *,
    camera_id: str,
    status_path: Path,
    interval_seconds: int,
) -> dict[str, Any] | None:
    """
    Invoke the LangGraph pipeline for one camera frame and log the results.

    Args:
        image_path: Absolute path to the saved camera frame.
        app:             Compiled LangGraph `CompiledGraph` (from `graph.graph`).
        history_context: Recent same-camera frame summaries for temporal cues.
    """
    logger.info("Pipeline start — image: %s", image_path)

    run_id = new_run_id()
    initial_state = {
        "workflow_mode": "frame",
        "run_id": run_id,
        "camera_id": camera_id,
        "image_path": image_path,
        "target_date": "",
        "oa_log_dir": str(_resolve_oa_log_dir()),
        "output_dir": "",
        "report_path": "",
        "policy_snapshot": policy_snapshot(),
        # Remaining fields start empty; each node populates its own slice
        "guardrail_result": {},
        "vlm_output": {},
        "validated_scene": {},
        "validated_text": "",
        "validated_signals": {},
        "history_context": history_context or [],
        "active_experts": [],
        "next_nodes": [],
        "expert_results": {},
        "alerts": [],
        "metadata": {},
    }

    try:
        final_state = app.invoke(initial_state)
    except Exception as exc:
        # Pipeline errors must NOT crash the daemon — log and continue
        logger.error("Pipeline raised an unhandled exception: %s", exc, exc_info=True)
        error_metadata = _ensure_record_metadata(initial_state.get("metadata"))
        error_metadata["external_calls"]["pipeline"] = {
            "status": "failed",
            "reason": str(exc),
        }
        _write_run_record_safe(
            run_id=run_id,
            workflow_mode="frame",
            camera_id=camera_id,
            image_path=image_path,
            status="failed",
            metadata=error_metadata,
        )
        _publish_dashboard_status(
            status_path=status_path,
            camera_id=camera_id,
            backend_status="error",
            interval_seconds=interval_seconds,
            image_path=image_path,
            message=f"Pipeline error: {exc}",
        )
        return None

    guardrail_result: dict[str, Any] = final_state.get("guardrail_result", {})
    if guardrail_result and not guardrail_result.get("allowed", False):
        reason = guardrail_result.get("reason", "no reason provided")
        logger.info(
            "Pipeline complete - frame blocked by guardrail (%s): %s",
            guardrail_result.get("status", "blocked"),
            reason,
        )
        _publish_dashboard_status(
            status_path=status_path,
            camera_id=camera_id,
            backend_status="blocked",
            interval_seconds=interval_seconds,
            image_path=image_path,
            final_state=final_state,
            message=str(reason),
        )
        _write_run_record_safe(
            run_id=str(final_state.get("run_id", run_id)),
            workflow_mode=str(final_state.get("workflow_mode", "frame")),
            camera_id=camera_id,
            image_path=image_path,
            status="blocked",
            guardrail_result=guardrail_result,
            validated_text=str(final_state.get("validated_text", "")),
            validated_signals=dict(final_state.get("validated_signals", {})),
            active_experts=list(final_state.get("active_experts", [])),
            expert_results=dict(final_state.get("expert_results", {})),
            alerts=list(final_state.get("alerts", [])),
            metadata=dict(final_state.get("metadata", {})),
        )
        return

    alerts: list[dict] = final_state.get("alerts", [])

    if alerts:
        logger.warning("Pipeline complete — %d alert(s) generated:", len(alerts))
        for i, alert in enumerate(alerts, start=1):
            severity = alert.get("severity", "unknown").upper()
            alert_type = alert.get("sub_type") or alert.get("domain", "unknown")
            message = alert.get("message", "(no message)")
            logger.warning("  [%d/%d] [%s] %s — %s", i, len(alerts), severity, alert_type, message)
    else:
        logger.info("Pipeline complete — no alerts generated for this frame.")

    _publish_dashboard_status(
        status_path=status_path,
        camera_id=camera_id,
        backend_status="alerting" if alerts else "monitoring",
        interval_seconds=interval_seconds,
        image_path=image_path,
        final_state=final_state,
        message=(
            str(alerts[0].get("message", "")).strip() if alerts else "Frame processed successfully."
        ),
    )

    _write_run_record_safe(
        run_id=str(final_state.get("run_id", run_id)),
        workflow_mode=str(final_state.get("workflow_mode", "frame")),
        camera_id=camera_id,
        image_path=image_path,
        status="alerted" if alerts else "clean",
        guardrail_result=guardrail_result,
        validated_text=str(final_state.get("validated_text", "")),
        validated_signals=dict(final_state.get("validated_signals", {})),
        active_experts=list(final_state.get("active_experts", [])),
        expert_results=dict(final_state.get("expert_results", {})),
        alerts=list(alerts),
        metadata=dict(final_state.get("metadata", {})),
    )

    return final_state


# ---------------------------------------------------------------------------
# Entry-point modes
# ---------------------------------------------------------------------------


def _run_daemon(
    app: Any,
    camera_id: str,
    frames_dir: Path,
    interval: int,
    keep_history: bool,
    status_path: Path,
    *,
    run_once: bool = False,
) -> None:
    """
    Main polling loop.  Runs until SIGINT / SIGTERM is received.

    Args:
        app:          Compiled LangGraph application.
        camera_id:    LTA camera ID to poll.
        frames_dir:   Directory where fetched frames are stored.
        interval:     Target total seconds per iteration.
        keep_history: Whether to retain timestamped historical frames.
        status_path:  JSON snapshot file consumed by the dashboard backend.
    """
    # Import here (not at module level) so that the heavy LangGraph/model
    # initialisation only happens when the daemon actually starts.
    from skymirror.tools.camera_fetcher import fetch_latest_frame, publish_latest_frame

    logger.info(
        "Daemon started — camera=%s | interval=%ds | frames_dir=%s | run_once=%s",
        camera_id,
        interval,
        frames_dir,
        run_once,
    )

    iteration = 0
    camera_history: deque[dict[str, Any]] = deque(maxlen=_HISTORY_WINDOW_SIZE)
    _publish_dashboard_status(
        status_path=status_path,
        camera_id=camera_id,
        backend_status="starting",
        interval_seconds=interval,
        message="Daemon online. Awaiting first camera fetch.",
    )

    while not _shutdown_requested:
        cycle_started_at = time.monotonic()
        iteration += 1
        logger.info("─── Iteration %d ───────────────────────────────", iteration)

        # 1. Fetch the latest camera frame
        _publish_dashboard_status(
            status_path=status_path,
            camera_id=camera_id,
            backend_status="fetching",
            interval_seconds=interval,
            message="Polling camera feed for the latest frame.",
        )
        image_path = fetch_latest_frame(
            camera_id=camera_id,
            save_dir=frames_dir,
            keep_history=keep_history,
        )

        if image_path is None:
            logger.warning(
                "Camera fetch failed for camera %s — skipping pipeline this cycle.",
                camera_id,
            )
            _write_run_record_safe(
                run_id=new_run_id(),
                workflow_mode="frame",
                camera_id=camera_id,
                image_path="",
                status="failed",
                metadata={
                    "external_calls": {
                        "camera_feed": {
                            "status": "failed",
                            "reason": "fetch_latest_frame returned no image",
                        }
                    }
                },
            )
            _publish_dashboard_status(
                status_path=status_path,
                camera_id=camera_id,
                backend_status="fetch_error",
                interval_seconds=interval,
                message="Latest frame could not be fetched from the camera feed.",
            )
        else:
            # 2. Run the LangGraph pipeline
            _publish_dashboard_status(
                status_path=status_path,
                camera_id=camera_id,
                backend_status="processing",
                interval_seconds=interval,
                image_path=image_path,
                message="Frame fetched. Running guardrail and pipeline analysis.",
            )
            final_state = _run_pipeline(
                image_path,
                app,
                history_context=list(camera_history),
                camera_id=camera_id,
                status_path=status_path,
                interval_seconds=interval,
            )
            if final_state is not None:
                publish_latest_frame(camera_id, frames_dir, image_path)
                camera_history.append(_build_history_entry(final_state))

        if run_once:
            logger.info("Run-once mode enabled — completed one iteration for camera %s.", camera_id)
            break

        _sleep_until_next_cycle(
            cycle_started_at=cycle_started_at,
            interval_seconds=interval,
        )

    _publish_dashboard_status(
        status_path=status_path,
        camera_id=camera_id,
        backend_status="offline",
        interval_seconds=interval,
        message="Daemon stopped.",
    )
    logger.info("Daemon loop exited cleanly after %d iteration(s).", iteration)


def _run_multi_camera_daemon(
    *,
    app: Any,
    camera_ids: list[str],
    frames_dir: Path,
    interval: int,
    keep_history: bool,
    status_path: Path,
    run_once: bool = False,
) -> None:
    global _shutdown_requested

    set_runtime_active_cameras(status_path, camera_ids)

    threads: list[Thread] = []
    for camera_id in camera_ids:
        thread = Thread(
            target=_run_daemon,
            name=f"camera-{camera_id}",
            kwargs={
                "app": app,
                "camera_id": camera_id,
                "frames_dir": frames_dir,
                "interval": interval,
                "keep_history": keep_history,
                "status_path": status_path,
                "run_once": run_once,
            },
            daemon=True,
        )
        thread.start()
        threads.append(thread)
        logger.info("Started camera worker thread for %s", camera_id)

    try:
        while not _shutdown_requested:
            failed_threads = [thread.name for thread in threads if not thread.is_alive()]
            if failed_threads:
                if run_once and len(failed_threads) == len(threads):
                    logger.info("Run-once mode complete for all camera worker threads.")
                    break
                logger.error(
                    "Camera worker thread exited unexpectedly: %s", ", ".join(failed_threads)
                )
                _shutdown_requested = True
                break
            time.sleep(1)
    finally:
        for thread in threads:
            thread.join(timeout=max(interval + 5, 10))


def _run_single_shot(app: Any, image_path: str, *, camera_id: str, status_path: Path) -> None:
    """Run the pipeline once against a local image file and exit."""
    if not Path(image_path).is_file():
        logger.error("--image path does not exist: %s", image_path)
        sys.exit(1)
    _run_pipeline(
        image_path,
        app,
        history_context=[],
        camera_id=camera_id,
        status_path=status_path,
        interval_seconds=0,
    )


def _run_report() -> None:
    """Generate the daily report immediately and exit."""
    from skymirror.graph.graph import app

    logger.info("Generating daily report on demand.")
    final_state = app.invoke(
        {
            "workflow_mode": "report",
            "target_date": "",
            "oa_log_dir": "data/oa_log",
            "output_dir": "data/reports",
            "report_path": "",
            "metadata": {},
        }
    )
    logger.info("Daily report complete: %s", final_state.get("report_path", "(unknown)"))


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="skymirror",
        description="SKYMIRROR — Multi-Agent Traffic Camera Analysis Daemon",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Fetch and process one live camera cycle, then exit.",
    )
    mode.add_argument(
        "--image",
        metavar="PATH",
        help="Run pipeline once against a local image file, then exit.",
    )
    mode.add_argument(
        "--report",
        action="store_true",
        help="Generate the daily summary report immediately, then exit.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Application entry point."""
    _configure_logging()
    args = _parse_args()
    scheduler: Any = None

    # Register OS signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("=" * 60)
    logger.info("SKYMIRROR starting up (PID=%d)", os.getpid())
    logger.info("=" * 60)

    # --report mode: no pipeline needed
    if args.report:
        _run_report()
        flush_langsmith_traces()
        return

    # --- Import the compiled LangGraph app -----------------------------------
    # Done here (not at module top) so import errors surface with a clear
    # message rather than a cryptic startup crash.
    try:
        from skymirror.graph.graph import app
    except Exception as exc:
        logger.critical("Failed to import LangGraph pipeline: %s", exc, exc_info=True)
        sys.exit(1)

    # --image mode: single-shot, no scheduler needed
    if args.image:
        status_path = Path(
            os.getenv("DASHBOARD_STATUS_PATH", _DEFAULT_DASHBOARD_STATUS_PATH)
        ).resolve()
        camera_id = os.getenv("TARGET_CAMERA_ID", "local")
        _run_single_shot(app, args.image, camera_id=camera_id, status_path=status_path)
        flush_langsmith_traces()
        return

    # --- Daemon mode: read configuration -------------------------------------
    camera_ids = _resolve_target_camera_ids()
    interval: int = int(os.getenv("PROCESSING_INTERVAL_SECONDS", "20"))
    frames_dir = Path(os.getenv("FRAMES_DIR", "data/frames")).resolve()
    status_path = Path(os.getenv("DASHBOARD_STATUS_PATH", _DEFAULT_DASHBOARD_STATUS_PATH)).resolve()
    keep_history: bool = os.getenv("KEEP_FRAME_HISTORY", "true").lower() != "false"
    run_once = args.once or _env_flag_enabled("SKYMIRROR_RUN_ONCE")

    logger.info("Configuration:")
    logger.info("  TARGET_CAMERA_IDS          = %s", ", ".join(camera_ids))
    logger.info("  PROCESSING_INTERVAL_SECONDS = %ds", interval)
    logger.info("  FRAMES_DIR                 = %s", frames_dir)
    logger.info("  DASHBOARD_STATUS_PATH      = %s", status_path)
    logger.info("  KEEP_FRAME_HISTORY         = %s", keep_history)
    logger.info("  SKYMIRROR_RUN_ONCE         = %s", run_once)

    # --- Start APScheduler for daily reports (background thread) -------------
    if not run_once:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            from skymirror.agents.report_generator import generate_daily_report

            scheduler = BackgroundScheduler(timezone="UTC")
            scheduler.add_job(
                generate_daily_report,
                trigger="cron",
                hour=0,
                minute=5,
                id="daily_report",
                replace_existing=True,
            )
            scheduler.start()
            logger.info("APScheduler started — daily report job scheduled at 00:05 UTC.")
        except ImportError:
            logger.warning(
                "apscheduler not installed — daily report scheduling disabled. "
                "Install with: pip install apscheduler"
            )
            scheduler = None  # type: ignore[assignment]
    else:
        logger.info("Run-once mode enabled — skipping APScheduler startup.")

    # --- Enter the main polling loop -----------------------------------------
    try:
        _run_multi_camera_daemon(
            app=app,
            camera_ids=camera_ids,
            frames_dir=frames_dir,
            interval=interval,
            keep_history=keep_history,
            status_path=status_path,
            run_once=run_once,
        )
    finally:
        clear_runtime_active_cameras(status_path)
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler shut down.")
        flush_langsmith_traces()
        logger.info("SKYMIRROR shut down. Goodbye.")


if __name__ == "__main__":
    main()
