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


# ---------------------------------------------------------------------------
# Geo distance
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in metres between two (lat, lng) points."""
    rlat1, rlng1 = math.radians(lat1), math.radians(lng1)
    rlat2, rlng2 = math.radians(lat2), math.radians(lng2)
    dlat = rlat2 - rlat1
    dlng = rlng2 - rlng1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Event matching
# ---------------------------------------------------------------------------

def match_events(
    cam_lat: float,
    cam_lng: float,
    radius_m: float,
    domain: str,
    events: list[LtaEvent],
) -> list[LtaMatch]:
    """Match LTA events within radius, tagging by domain relevance.

    Events from endpoints in LTA_DOMAIN_MAP[domain] get "location_and_domain";
    all other events within radius get "location_only".
    Returns matches sorted by distance (nearest first).
    """
    domain_endpoints = set(LTA_DOMAIN_MAP.get(domain, []))
    matches: list[LtaMatch] = []

    for event in events:
        dist = _haversine_m(cam_lat, cam_lng, event.latitude, event.longitude)
        if dist <= radius_m:
            match_type = (
                "location_and_domain"
                if event.source_api in domain_endpoints
                else "location_only"
            )
            matches.append(LtaMatch(event=event, distance_m=round(dist, 1), match_type=match_type))

    matches.sort(key=lambda m: m.distance_m)
    return matches
