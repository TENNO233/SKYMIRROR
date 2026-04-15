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


# ---------------------------------------------------------------------------
# LTA DataMall API fetching
# ---------------------------------------------------------------------------

def _parse_lta_events(data: dict[str, Any], source_api: str) -> list[LtaEvent]:
    """Parse LTA DataMall JSON response into LtaEvent list."""
    events: list[LtaEvent] = []
    for item in data.get("value", []):
        try:
            events.append(LtaEvent(
                event_type=item.get("Type", item.get("AlarmID", source_api)),
                description=item.get("Message", ""),
                latitude=float(item["Latitude"]),
                longitude=float(item["Longitude"]),
                source_api=source_api,
            ))
        except (KeyError, ValueError) as exc:
            logger.debug("Skipping malformed LTA event: %s", exc)
    return events


def fetch_lta_events(endpoint: str) -> list[LtaEvent]:
    """Fetch events from a single LTA DataMall endpoint.

    Returns empty list if API key is missing or request fails.
    """
    api_key = os.environ.get("LTA_API_KEY")
    if not api_key:
        logger.warning("LTA_API_KEY not set; skipping %s.", endpoint)
        return []

    try:
        url = f"{LTA_BASE_URL}{endpoint}"
        resp = httpx.get(url, headers={"AccountKey": api_key}, timeout=10.0)
        resp.raise_for_status()
        return _parse_lta_events(resp.json(), source_api=endpoint)
    except Exception as exc:
        logger.warning("LTA fetch failed for %s: %s", endpoint, exc)
        return []


# ---------------------------------------------------------------------------
# Main lookup function
# ---------------------------------------------------------------------------

def _unavailable(camera_id: str) -> LtaCorroboration:
    """Return a corroboration result indicating API was unavailable."""
    return LtaCorroboration(
        camera_id=camera_id,
        camera_lat=0.0,
        camera_lng=0.0,
        matches=[],
        queried_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        api_available=False,
    )


def lookup_lta_events(
    camera_id: str,
    domain: str,
    radius_m: float = 500.0,
) -> LtaCorroboration:
    """Query LTA DataMall for official events near a camera.

    Orchestrates: camera resolution -> fetch all endpoints -> match events.
    Returns LtaCorroboration with api_available=False on any failure.
    """
    # Step 1: Resolve camera location
    location = resolve_camera_location(camera_id)
    if location is None:
        return _unavailable(camera_id)

    cam_lat, cam_lng = location

    # Step 2: Check API key before fetching
    if not os.environ.get("LTA_API_KEY"):
        logger.warning("LTA_API_KEY not set; returning unavailable.")
        return _unavailable(camera_id)

    # Step 3: Fetch events from all endpoints
    all_events: list[LtaEvent] = []
    for endpoint in LTA_ALL_ENDPOINTS:
        all_events.extend(fetch_lta_events(endpoint))

    # Step 4: Match events by distance and domain
    matches = match_events(cam_lat, cam_lng, radius_m, domain, all_events)

    return LtaCorroboration(
        camera_id=camera_id,
        camera_lat=cam_lat,
        camera_lng=cam_lng,
        matches=matches,
        queried_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        api_available=True,
    )
