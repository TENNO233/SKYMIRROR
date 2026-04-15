"""LTA DataMall real-time event lookup for the Alert Agent.

Queries LTA DataMall APIs and data.gov.sg camera API to find official
events near a camera location, providing independent corroboration of
OA expert judgments.

Used by: skymirror.agents.alert_manager, scripts/evaluate_alerts.py
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from skymirror.tools.alert.constants import (
    CAMERA_API_URL,
    LTA_ALL_ENDPOINTS,
    LTA_BASE_URL,
    LTA_DOMAIN_MAP,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LtaEvent:
    """A single event from an LTA DataMall endpoint."""
    event_type: str
    description: str
    latitude: float
    longitude: float
    source_api: str


@dataclass
class LtaMatch:
    """An LTA event that matched within the search radius."""
    event: LtaEvent
    distance_m: float
    match_type: str  # "location_and_domain" | "location_only"


@dataclass
class LtaCorroboration:
    """Result of querying LTA for events near a camera."""
    camera_id: str
    camera_lat: float
    camera_lng: float
    matches: list[LtaMatch] = field(default_factory=list)
    queried_at: str = ""
    api_available: bool = True


# ---------------------------------------------------------------------------
# Camera resolution
# ---------------------------------------------------------------------------

def resolve_camera_location(camera_id: str) -> tuple[float, float] | None:
    """Resolve a camera ID to (latitude, longitude) via data.gov.sg.

    Returns None if the camera is not found or the API fails.
    """
    try:
        resp = httpx.get(CAMERA_API_URL, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        cameras = data.get("items", [{}])[0].get("cameras", [])
        for cam in cameras:
            if str(cam.get("camera_id")) == str(camera_id):
                return (cam["latitude"], cam["longitude"])

        logger.warning("Camera %s not found in data.gov.sg response.", camera_id)
        return None

    except Exception as exc:
        logger.warning("Camera resolution failed for %s: %s", camera_id, exc)
        return None
