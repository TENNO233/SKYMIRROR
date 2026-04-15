"""
main.py — SKYMIRROR Application Entry Point
=============================================
Long-running daemon that polls a Singapore LTA traffic camera every
PROCESSING_INTERVAL_SECONDS, feeds each frame through the LangGraph pipeline,
and logs the resulting alerts.

Execution modes
---------------
    # Normal daemon (reads TARGET_CAMERA_ID from env, default "4798"):
    python -m skymirror.main

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
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env FIRST — before any module that reads os.environ
load_dotenv()

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Pipeline runner (single iteration)
# ---------------------------------------------------------------------------

def _run_pipeline(image_path: str, app: Any) -> None:
    """
    Invoke the LangGraph pipeline for one camera frame and log the results.

    Args:
        image_path: Absolute path to the saved camera frame.
        app:        Compiled LangGraph `CompiledGraph` (from `graph.graph`).
    """
    logger.info("Pipeline start — image: %s", image_path)

    initial_state = {
        "image_path": image_path,
        # Remaining fields start empty; each node populates its own slice
        "guardrail_result": {},
        "vlm_outputs": {},
        "validated_text": "",
        "active_experts": [],
        "expert_results": {},
        "alerts": [],
        "metadata": {},
    }

    try:
        final_state = app.invoke(initial_state)
    except Exception as exc:
        # Pipeline errors must NOT crash the daemon — log and continue
        logger.error("Pipeline raised an unhandled exception: %s", exc, exc_info=True)
        return

    guardrail_result: dict[str, Any] = final_state.get("guardrail_result", {})
    if guardrail_result and not guardrail_result.get("allowed", False):
        logger.info(
            "Pipeline complete - frame blocked by guardrail (%s): %s",
            guardrail_result.get("status", "blocked"),
            guardrail_result.get("reason", "no reason provided"),
        )
        return

    alerts: list[dict] = final_state.get("alerts", [])

    if alerts:
        logger.warning(
            "Pipeline complete — %d alert(s) generated:", len(alerts)
        )
        for i, alert in enumerate(alerts, start=1):
            severity = alert.get("severity", "unknown").upper()
            alert_type = alert.get("type", "unknown")
            message = alert.get("message", "(no message)")
            logger.warning("  [%d/%d] [%s] %s — %s", i, len(alerts), severity, alert_type, message)
    else:
        logger.info("Pipeline complete — no alerts generated for this frame.")


# ---------------------------------------------------------------------------
# Entry-point modes
# ---------------------------------------------------------------------------

def _run_daemon(
    app: Any,
    camera_id: str,
    frames_dir: Path,
    interval: int,
    keep_history: bool,
) -> None:
    """
    Main polling loop.  Runs until SIGINT / SIGTERM is received.

    Args:
        app:          Compiled LangGraph application.
        camera_id:    LTA camera ID to poll.
        frames_dir:   Directory where fetched frames are stored.
        interval:     Seconds to sleep between iterations.
        keep_history: Whether to retain timestamped historical frames.
    """
    # Import here (not at module level) so that the heavy LangGraph/model
    # initialisation only happens when the daemon actually starts.
    from skymirror.tools.camera_fetcher import fetch_latest_frame

    logger.info(
        "Daemon started — camera=%s | interval=%ds | frames_dir=%s",
        camera_id,
        interval,
        frames_dir,
    )

    iteration = 0

    while not _shutdown_requested:
        iteration += 1
        logger.info("─── Iteration %d ───────────────────────────────", iteration)

        # 1. Fetch the latest camera frame
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
        else:
            # 2. Run the LangGraph pipeline
            _run_pipeline(image_path, app)

        # 3. Sleep until next cycle, checking shutdown flag every second
        #    so we don't block a SIGTERM for up to `interval` seconds.
        for _ in range(interval):
            if _shutdown_requested:
                break
            time.sleep(1)

    logger.info("Daemon loop exited cleanly after %d iteration(s).", iteration)


def _run_single_shot(app: Any, image_path: str) -> None:
    """Run the pipeline once against a local image file and exit."""
    if not Path(image_path).is_file():
        logger.error("--image path does not exist: %s", image_path)
        sys.exit(1)
    _run_pipeline(image_path, app)


def _run_report() -> None:
    """Generate the daily report immediately and exit."""
    from skymirror.agents.report_generator import generate_daily_report
    logger.info("Generating daily report on demand.")
    generate_daily_report()
    logger.info("Daily report complete.")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="skymirror",
        description="SKYMIRROR — Multi-Agent Traffic Camera Analysis Daemon",
    )
    mode = parser.add_mutually_exclusive_group()
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
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Application entry point."""
    _configure_logging()
    args = _parse_args()

    # Register OS signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("=" * 60)
    logger.info("SKYMIRROR starting up (PID=%d)", os.getpid())
    logger.info("=" * 60)

    # --report mode: no pipeline needed
    if args.report:
        _run_report()
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
        _run_single_shot(app, args.image)
        return

    # --- Daemon mode: read configuration -------------------------------------
    camera_id: str = os.getenv("TARGET_CAMERA_ID", "4798")
    interval: int = int(os.getenv("PROCESSING_INTERVAL_SECONDS", "20"))
    frames_dir = Path(os.getenv("FRAMES_DIR", "data/frames")).resolve()
    keep_history: bool = os.getenv("KEEP_FRAME_HISTORY", "true").lower() != "false"

    logger.info("Configuration:")
    logger.info("  TARGET_CAMERA_ID           = %s", camera_id)
    logger.info("  PROCESSING_INTERVAL_SECONDS = %ds", interval)
    logger.info("  FRAMES_DIR                 = %s", frames_dir)
    logger.info("  KEEP_FRAME_HISTORY         = %s", keep_history)

    # --- Start APScheduler for daily reports (background thread) -------------
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

    # --- Enter the main polling loop -----------------------------------------
    try:
        _run_daemon(
            app=app,
            camera_id=camera_id,
            frames_dir=frames_dir,
            interval=interval,
            keep_history=keep_history,
        )
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler shut down.")
        logger.info("SKYMIRROR shut down. Goodbye.")


if __name__ == "__main__":
    main()
