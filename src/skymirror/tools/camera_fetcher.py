"""
camera_fetcher.py — Singapore Traffic Camera Image Fetcher
===========================================================
Fetches the latest snapshot from a specific camera via the Singapore
Land Transport Authority (LTA) open-data API and saves it to disk.

API endpoint
------------
    GET https://api.data.gov.sg/v1/transport/traffic-images
    Response schema (simplified):
    {
        "items": [{
            "timestamp": "2024-04-12T14:30:00+08:00",
            "cameras": [{
                "camera_id": "4798",
                "image":     "https://images.data.gov.sg/api/traffic-images/...",
                "location":  {"latitude": 1.29, "longitude": 103.87},
                "image_metadata": {"height": 240, "width": 320, "md5": "..."}
            }]
        }]
    }

Disk layout
-----------
    data/frames/
        cam4798_20240412_143000.jpg     ← timestamped frame (kept ≤24 h)
        cam4798_latest.jpg              ← always-current symlink / overwrite

Cleanup policy
--------------
`purge_old_frames(save_dir, max_age_hours=24)` is called automatically after
every successful save.  Files matching `cam<id>_*.jpg` that are older than
`max_age_hours` are deleted, preventing unbounded disk growth.

Usage
-----
    from pathlib import Path
    from skymirror.tools.camera_fetcher import fetch_latest_frame

    image_path = fetch_latest_frame("4798", Path("data/frames"))
    if image_path:
        print(f"Saved to: {image_path}")
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: LTA Traffic Images API endpoint (Singapore government open data)
_API_URL: str = "https://api.data.gov.sg/v1/transport/traffic-images"

#: Connection + read timeout for all outbound HTTP requests (seconds)
_HTTP_TIMEOUT: int = 10

#: Frames older than this many hours are deleted by the purge step
_DEFAULT_MAX_AGE_HOURS: int = 24

#: Filename suffix for the always-current copy (no timestamp)
_LATEST_SUFFIX: str = "latest"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_frame_filename(camera_id: str, ts: Optional[datetime] = None) -> str:
    """
    Build a deterministic filename for a camera frame.

    Args:
        camera_id: LTA camera identifier string, e.g. ``"4798"``.
        ts:        Frame timestamp.  Defaults to the current UTC time.

    Returns:
        Filename string, e.g. ``"cam4798_20240412_143000.jpg"``.
    """
    if ts is None:
        ts = datetime.now(tz=timezone.utc)
    return f"cam{camera_id}_{ts.strftime('%Y%m%d_%H%M%S')}.jpg"


def _build_latest_filename(camera_id: str) -> str:
    """Return the fixed 'latest' filename for a given camera."""
    return f"cam{camera_id}_{_LATEST_SUFFIX}.jpg"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def purge_old_frames(save_dir: Path, camera_id: str, max_age_hours: int = _DEFAULT_MAX_AGE_HOURS) -> int:
    """
    Delete timestamped frame files older than `max_age_hours`.

    Only deletes files matching the pattern ``cam<camera_id>_YYYYMMDD_HHMMSS.jpg``
    — the ``*_latest.jpg`` file is always preserved.

    Args:
        save_dir:      Directory containing the frame files.
        camera_id:     Camera ID string used in the filename prefix.
        max_age_hours: Files older than this many hours are removed.

    Returns:
        Number of files deleted.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
    deleted = 0

    for frame_file in save_dir.glob(f"cam{camera_id}_[0-9]*.jpg"):
        try:
            mtime = datetime.fromtimestamp(frame_file.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                frame_file.unlink()
                deleted += 1
                logger.debug("purge_old_frames: Deleted stale frame — %s", frame_file.name)
        except OSError as exc:
            # Non-fatal: log and continue
            logger.warning("purge_old_frames: Could not remove %s — %s", frame_file, exc)

    if deleted:
        logger.info("purge_old_frames: Removed %d stale frame(s) from %s", deleted, save_dir)

    return deleted


def fetch_latest_frame(
    camera_id: str,
    save_dir: Path,
    *,
    keep_history: bool = True,
    max_age_hours: int = _DEFAULT_MAX_AGE_HOURS,
) -> Optional[str]:
    """
    Fetch the latest snapshot for `camera_id` from the LTA API and save it.

    Behaviour
    ---------
    1. GET the traffic-images API with a 10-second timeout.
    2. Parse the JSON and locate the camera matching `camera_id`.
    3. Download the image binary with a separate 10-second timeout.
    4. Write the image to `save_dir` using a timestamp-based filename.
    5. Also overwrite `cam<id>_latest.jpg` for the pipeline to use as a
       stable reference (avoids race conditions with in-progress writes).
    6. Purge frames older than `max_age_hours` from `save_dir`.

    Args:
        camera_id:    LTA camera ID (e.g. ``"4798"``).
        save_dir:     Directory where images are saved (created if absent).
        keep_history: If ``True`` (default), timestamped files are retained
                      for up to `max_age_hours`.  If ``False``, only the
                      ``*_latest.jpg`` file is kept — useful when historical
                      frames are not needed downstream.
        max_age_hours: Age threshold for the purge step (ignored when
                      ``keep_history=False``).

    Returns:
        Absolute path string of the saved ``*_latest.jpg`` file on success,
        or ``None`` if the camera was not found or any network error occurred.

    Raises:
        Nothing — all exceptions are caught, logged, and ``None`` is returned
        so the caller's main loop can continue without crashing.
    """
    save_dir = save_dir.resolve()
    save_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: Fetch camera listing ----------------------------------------
    try:
        logger.debug("fetch_latest_frame: Querying API for camera %s", camera_id)
        api_response = requests.get(_API_URL, timeout=_HTTP_TIMEOUT)
        api_response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.error(
            "fetch_latest_frame: API request timed out after %ds (camera=%s)",
            _HTTP_TIMEOUT,
            camera_id,
        )
        return None
    except requests.exceptions.ConnectionError as exc:
        logger.error("fetch_latest_frame: Network error reaching API — %s", exc)
        return None
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "fetch_latest_frame: API returned HTTP %d — %s",
            exc.response.status_code,
            exc,
        )
        return None
    except requests.exceptions.RequestException as exc:
        logger.error("fetch_latest_frame: Unexpected requests error — %s", exc)
        return None

    # --- Step 2: Locate the target camera ------------------------------------
    try:
        data = api_response.json()
        items = data.get("items", [])
        if not items:
            logger.warning("fetch_latest_frame: API returned empty 'items' list.")
            return None

        all_cameras: list[dict] = items[0].get("cameras", [])
        camera_match = next(
            (c for c in all_cameras if str(c.get("camera_id", "")) == str(camera_id)),
            None,
        )
    except (ValueError, KeyError, IndexError) as exc:
        logger.error("fetch_latest_frame: Unexpected API response schema — %s", exc)
        return None

    if camera_match is None:
        logger.warning(
            "fetch_latest_frame: Camera ID '%s' not found in API response "
            "(available IDs sampled: %s).",
            camera_id,
            [c.get("camera_id") for c in all_cameras[:5]],
        )
        return None

    image_url: str = camera_match.get("image", "")
    if not image_url:
        logger.error("fetch_latest_frame: Camera %s has no 'image' URL in response.", camera_id)
        return None

    # --- Step 3: Download the image binary -----------------------------------
    try:
        logger.debug("fetch_latest_frame: Downloading image from %s", image_url)
        img_response = requests.get(image_url, timeout=_HTTP_TIMEOUT, stream=True)
        img_response.raise_for_status()
        image_bytes = img_response.content
    except requests.exceptions.Timeout:
        logger.error(
            "fetch_latest_frame: Image download timed out after %ds (camera=%s)",
            _HTTP_TIMEOUT,
            camera_id,
        )
        return None
    except requests.exceptions.RequestException as exc:
        logger.error("fetch_latest_frame: Failed to download image — %s", exc)
        return None

    if not image_bytes:
        logger.error("fetch_latest_frame: Downloaded image is empty (camera=%s).", camera_id)
        return None

    # --- Step 4: Persist to disk ---------------------------------------------
    now_utc = datetime.now(tz=timezone.utc)

    # Timestamped copy (retained for history / debugging)
    if keep_history:
        timestamped_path = save_dir / _build_frame_filename(camera_id, ts=now_utc)
        try:
            timestamped_path.write_bytes(image_bytes)
            logger.debug("fetch_latest_frame: Saved timestamped frame — %s", timestamped_path.name)
        except OSError as exc:
            logger.error("fetch_latest_frame: Could not write %s — %s", timestamped_path, exc)
            return None

    # Stable 'latest' copy — pipeline always reads from this path
    latest_path = save_dir / _build_latest_filename(camera_id)
    try:
        latest_path.write_bytes(image_bytes)
    except OSError as exc:
        logger.error("fetch_latest_frame: Could not write latest frame %s — %s", latest_path, exc)
        return None

    logger.info(
        "fetch_latest_frame: Saved frame for camera %s → %s (%d bytes)",
        camera_id,
        latest_path.name,
        len(image_bytes),
    )

    # --- Step 5: Purge stale frames ------------------------------------------
    if keep_history:
        purge_old_frames(save_dir, camera_id=camera_id, max_age_hours=max_age_hours)

    return str(latest_path)
