# LTA DataMall Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate LTA DataMall real-time APIs into the Alert Agent for cross-referencing OA judgments with official event data, plus an evaluation script to measure detection accuracy.

**Architecture:** Post-classification enrichment — LTA lookup happens after classify(), before render_alert(). All LTA endpoints are queried; matches are tagged `location_and_domain` or `location_only` based on domain relevance. Graceful degradation when API key is missing or requests fail.

**Tech Stack:** httpx (existing dep), dataclasses (stdlib), math (stdlib for haversine), re (stdlib), argparse (stdlib)

**Spec:** `docs/superpowers/specs/2026-04-15-lta-datamall-integration-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/skymirror/tools/alert/constants.py` | MODIFY | Add LTA_DOMAIN_MAP, LTA_ALL_ENDPOINTS, LTA_BASE_URL, CAMERA_API_URL |
| `src/skymirror/tools/alert/lta_lookup.py` | CREATE | LTA API calls, camera resolution, geo matching, main lookup function |
| `src/skymirror/tools/alert/rendering.py` | MODIFY | Add optional corroboration param, lta_corroboration field in alert dict |
| `src/skymirror/agents/alert_manager.py` | MODIFY | Add _extract_camera_id, insert LTA lookup between classify and render |
| `scripts/evaluate_alerts.py` | CREATE | Batch evaluation: compare alerts vs LTA ground truth |
| `tests/test_alert_manager.py` | MODIFY | Add ~18 new tests across all new/modified components |
| `tests/fixtures/lta_responses.json` | CREATE | Mock LTA API + data.gov.sg response samples |
| `.env.example` | MODIFY | Add LTA_API_KEY |

---

### Task 1: Constants and LTA Fixture Data

**Files:**
- Modify: `src/skymirror/tools/alert/constants.py`
- Create: `tests/fixtures/lta_responses.json`

- [ ] **Step 1: Add LTA constants to constants.py**

Append after `DEPARTMENT_MAP` at the end of `src/skymirror/tools/alert/constants.py`:

```python
# ---------------------------------------------------------------------------
# LTA DataMall integration
# ---------------------------------------------------------------------------

# Domain -> relevant LTA endpoints (events from these are "location_and_domain")
LTA_DOMAIN_MAP: dict[str, list[str]] = {
    "traffic": ["TrafficIncidents", "FaultyTrafficLights"],
    "safety": ["TrafficIncidents"],
    "environment": ["PUB_Flood", "RoadWorks"],
}

# All LTA endpoints to query (superset)
LTA_ALL_ENDPOINTS: list[str] = [
    "TrafficIncidents",
    "FaultyTrafficLights",
    "RoadWorks",
    "PUB_Flood",
]

# LTA DataMall base URL
LTA_BASE_URL = "http://datamall2.mytransport.sg/ltaodataservice/"

# data.gov.sg camera API (no auth needed)
CAMERA_API_URL = "https://api.data.gov.sg/v1/transport/traffic-images"
```

- [ ] **Step 2: Create LTA fixture data**

Create `tests/fixtures/lta_responses.json`:

```json
{
  "camera_api": {
    "items": [
      {
        "timestamp": "2026-04-15T08:30:00+08:00",
        "cameras": [
          {
            "camera_id": "4798",
            "latitude": 1.29531,
            "longitude": 103.871,
            "image": "https://images.data.gov.sg/api/traffic-images/2026/04/cam4798.jpg"
          },
          {
            "camera_id": "1701",
            "latitude": 1.44565,
            "longitude": 103.77055,
            "image": "https://images.data.gov.sg/api/traffic-images/2026/04/cam1701.jpg"
          }
        ]
      }
    ]
  },
  "traffic_incidents": {
    "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#IncidentSet",
    "value": [
      {
        "Type": "Accident",
        "Latitude": 1.29550,
        "Longitude": 103.87120,
        "Message": "(15/4)08:25 Accident on Ayer Rajah Expressway (AYE) towards Tuas after Clementi Ave 6 Exit."
      },
      {
        "Type": "Vehicle Breakdown",
        "Latitude": 1.44600,
        "Longitude": 103.77100,
        "Message": "(15/4)07:50 Vehicle breakdown on BKE towards Woodlands after Dairy Farm Exit."
      },
      {
        "Type": "Road Block",
        "Latitude": 1.35000,
        "Longitude": 103.90000,
        "Message": "(15/4)09:00 Road block on Geylang Road."
      }
    ]
  },
  "faulty_traffic_lights": {
    "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#FaultyTrafficLightSet",
    "value": [
      {
        "AlarmID": "FTL-2026-0415-001",
        "NodeID": "N1234",
        "Type": "Amber Fault",
        "StartDate": "2026-04-15 07:00:00",
        "EndDate": "",
        "Message": "Faulty traffic light at junction of Ayer Rajah Expressway / Clementi Ave 6.",
        "Latitude": 1.29500,
        "Longitude": 103.87080
      }
    ]
  },
  "road_works": {
    "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#RoadWorkSet",
    "value": [
      {
        "EventID": "RW-2026-0089",
        "StartDate": "2026-04-10 22:00:00",
        "EndDate": "2026-04-20 05:00:00",
        "SvcDept": "LTA",
        "Message": "Road works on Clementi Road between Clementi Ave 2 and West Coast Road.",
        "Latitude": 1.29800,
        "Longitude": 103.87300
      }
    ]
  },
  "pub_flood": {
    "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#FloodAlertSet",
    "value": []
  }
}
```

- [ ] **Step 3: Run existing tests to confirm no regression**

Run: `cd ~/Desktop/Explainable\ and\ Responsible\ AI/Group\ Project/SKYMIRROR && python -m pytest tests/test_alert_manager.py -v`
Expected: All existing tests PASS (new constants don't break anything)

- [ ] **Step 4: Commit**

```bash
git add src/skymirror/tools/alert/constants.py tests/fixtures/lta_responses.json
git commit -m "feat(alert): add LTA DataMall constants and test fixture data"
```

---

### Task 2: LTA Data Structures and Camera Resolution

**Files:**
- Create: `src/skymirror/tools/alert/lta_lookup.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests for data structures and camera resolution**

Append to `tests/test_alert_manager.py`:

```python
# =============================================================================
# Task: LTA Lookup — Data Structures & Camera Resolution
# =============================================================================

import math
from unittest.mock import patch, MagicMock
from skymirror.tools.alert.lta_lookup import (
    LtaEvent,
    LtaMatch,
    LtaCorroboration,
    resolve_camera_location,
)


class TestResolveCamera:
    """Tests for camera_id -> (lat, lng) resolution via data.gov.sg."""

    def test_known_camera_returns_coords(self, fixtures_dir):
        sample = json.loads((fixtures_dir / "lta_responses.json").read_text())
        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = sample["camera_api"]
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_resp

            result = resolve_camera_location("4798")

        assert result is not None
        lat, lng = result
        assert abs(lat - 1.29531) < 1e-5
        assert abs(lng - 103.871) < 1e-5

    def test_unknown_camera_returns_none(self, fixtures_dir):
        sample = json.loads((fixtures_dir / "lta_responses.json").read_text())
        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = sample["camera_api"]
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_resp

            result = resolve_camera_location("9999")

        assert result is None

    def test_api_failure_returns_none(self):
        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection timeout")

            result = resolve_camera_location("4798")

        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alert_manager.py::TestResolveCamera -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skymirror.tools.alert.lta_lookup'`

- [ ] **Step 3: Implement data structures and camera resolution**

Create `src/skymirror/tools/alert/lta_lookup.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alert_manager.py::TestResolveCamera -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/skymirror/tools/alert/lta_lookup.py tests/test_alert_manager.py
git commit -m "feat(alert): add LTA data structures and camera resolution"
```

---

### Task 3: Haversine Distance and Event Matching

**Files:**
- Modify: `src/skymirror/tools/alert/lta_lookup.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests for haversine and match_events**

Append to `tests/test_alert_manager.py`:

```python
from skymirror.tools.alert.lta_lookup import _haversine_m, match_events


class TestHaversine:
    """Tests for haversine distance calculation."""

    def test_same_point_is_zero(self):
        assert _haversine_m(1.3, 103.8, 1.3, 103.8) == 0.0

    def test_known_distance(self):
        # NUS to Changi Airport: ~17.6 km
        dist = _haversine_m(1.2966, 103.7764, 1.3644, 103.9915)
        assert 17000 < dist < 18500


class TestMatchEvents:
    """Tests for geo + domain matching logic."""

    def test_within_radius_and_domain(self):
        events = [
            LtaEvent("Accident", "Crash on AYE", 1.29550, 103.87120, "TrafficIncidents"),
        ]
        matches = match_events(1.29531, 103.871, 500.0, "traffic", events)
        assert len(matches) == 1
        assert matches[0].match_type == "location_and_domain"
        assert matches[0].distance_m < 500.0

    def test_within_radius_but_different_domain(self):
        events = [
            LtaEvent("Accident", "Crash on AYE", 1.29550, 103.87120, "TrafficIncidents"),
        ]
        matches = match_events(1.29531, 103.871, 500.0, "environment", events)
        assert len(matches) == 1
        assert matches[0].match_type == "location_only"

    def test_beyond_radius_filtered_out(self):
        events = [
            LtaEvent("Road Block", "Block on Geylang", 1.35000, 103.90000, "TrafficIncidents"),
        ]
        # cam4798 is at ~1.295, 103.871 — Geylang is ~7km away
        matches = match_events(1.29531, 103.871, 500.0, "traffic", events)
        assert len(matches) == 0

    def test_mixed_results_sorted_by_distance(self):
        events = [
            LtaEvent("Accident", "Far", 1.29600, 103.87200, "TrafficIncidents"),
            LtaEvent("Amber Fault", "Near", 1.29535, 103.87105, "FaultyTrafficLights"),
        ]
        matches = match_events(1.29531, 103.871, 500.0, "traffic", events)
        assert len(matches) == 2
        assert matches[0].distance_m <= matches[1].distance_m
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alert_manager.py::TestHaversine tests/test_alert_manager.py::TestMatchEvents -v`
Expected: FAIL with `ImportError: cannot import name '_haversine_m'`

- [ ] **Step 3: Implement haversine and match_events**

Add to `src/skymirror/tools/alert/lta_lookup.py` after the camera resolution section:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alert_manager.py::TestHaversine tests/test_alert_manager.py::TestMatchEvents -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/skymirror/tools/alert/lta_lookup.py tests/test_alert_manager.py
git commit -m "feat(alert): add haversine distance and LTA event matching"
```

---

### Task 4: LTA API Fetching and Main Lookup Function

**Files:**
- Modify: `src/skymirror/tools/alert/lta_lookup.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests for fetch_lta_events and lookup_lta_events**

Append to `tests/test_alert_manager.py`:

```python
from skymirror.tools.alert.lta_lookup import fetch_lta_events, lookup_lta_events


class TestFetchLtaEvents:
    """Tests for fetching events from LTA DataMall endpoints."""

    def test_parses_traffic_incidents(self, fixtures_dir):
        sample = json.loads((fixtures_dir / "lta_responses.json").read_text())
        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = sample["traffic_incidents"]
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_resp

            with patch.dict(os.environ, {"LTA_API_KEY": "test-key"}):
                events = fetch_lta_events("TrafficIncidents")

        assert len(events) == 3
        assert events[0].event_type == "Accident"
        assert events[0].source_api == "TrafficIncidents"
        assert isinstance(events[0].latitude, float)

    def test_missing_api_key_returns_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure LTA_API_KEY is not set
            os.environ.pop("LTA_API_KEY", None)
            events = fetch_lta_events("TrafficIncidents")

        assert events == []

    def test_api_failure_returns_empty(self):
        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_httpx.get.side_effect = Exception("503 Service Unavailable")
            with patch.dict(os.environ, {"LTA_API_KEY": "test-key"}):
                events = fetch_lta_events("TrafficIncidents")

        assert events == []


class TestLookupLtaEvents:
    """Tests for the main lookup_lta_events orchestrator."""

    def test_full_lookup_with_matches(self, fixtures_dir):
        sample = json.loads((fixtures_dir / "lta_responses.json").read_text())

        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            if "data.gov.sg" in url:
                mock_resp.json.return_value = sample["camera_api"]
            elif "TrafficIncidents" in url:
                mock_resp.json.return_value = sample["traffic_incidents"]
            elif "FaultyTrafficLights" in url:
                mock_resp.json.return_value = sample["faulty_traffic_lights"]
            elif "RoadWorks" in url:
                mock_resp.json.return_value = sample["road_works"]
            elif "Flood" in url:
                mock_resp.json.return_value = sample["pub_flood"]
            else:
                mock_resp.json.return_value = {"value": []}
            return mock_resp

        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_httpx.get.side_effect = mock_get
            with patch.dict(os.environ, {"LTA_API_KEY": "test-key"}):
                result = lookup_lta_events("4798", "traffic", radius_m=500.0)

        assert result.api_available is True
        assert result.camera_id == "4798"
        assert abs(result.camera_lat - 1.29531) < 1e-5
        assert len(result.matches) > 0
        # Accident near cam4798 should be location_and_domain for traffic
        domain_matches = [m for m in result.matches if m.match_type == "location_and_domain"]
        assert len(domain_matches) >= 1

    def test_missing_api_key_graceful(self):
        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"items": [{"cameras": []}]}
            mock_httpx.get.return_value = mock_resp

            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("LTA_API_KEY", None)
                result = lookup_lta_events("4798", "traffic")

        assert result.api_available is False
        assert result.matches == []

    def test_camera_not_found_graceful(self, fixtures_dir):
        sample = json.loads((fixtures_dir / "lta_responses.json").read_text())
        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = sample["camera_api"]
            mock_resp.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_resp

            with patch.dict(os.environ, {"LTA_API_KEY": "test-key"}):
                result = lookup_lta_events("9999", "traffic")

        assert result.api_available is False
        assert result.matches == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alert_manager.py::TestFetchLtaEvents tests/test_alert_manager.py::TestLookupLtaEvents -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_lta_events'`

- [ ] **Step 3: Implement fetch_lta_events and lookup_lta_events**

Add to `src/skymirror/tools/alert/lta_lookup.py` after the `match_events` function:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alert_manager.py::TestFetchLtaEvents tests/test_alert_manager.py::TestLookupLtaEvents -v`
Expected: 6 PASSED

- [ ] **Step 5: Run all tests to check no regression**

Run: `python -m pytest tests/test_alert_manager.py -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
git add src/skymirror/tools/alert/lta_lookup.py tests/test_alert_manager.py
git commit -m "feat(alert): add LTA API fetching and main lookup function"
```

---

### Task 5: Rendering Changes

**Files:**
- Modify: `src/skymirror/tools/alert/rendering.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests for corroboration in render_alert**

Append to `tests/test_alert_manager.py`:

```python
from skymirror.tools.alert.lta_lookup import LtaCorroboration, LtaMatch, LtaEvent


class TestRenderAlertCorroboration:
    """Tests for lta_corroboration field in rendered alert dict."""

    def _base_args(self):
        return dict(
            expert_name="order_expert",
            classification={"sub_type": "red_light", "severity": "high", "message": "Test alert"},
            findings=[{"description": "Running red light", "confidence": 0.87}],
            regulations=[],
            image_path="data/frames/cam4798_20260412T083000.jpg",
        )

    def test_corroboration_none_gives_null_field(self):
        alert = render_alert(**self._base_args(), corroboration=None)
        assert alert["lta_corroboration"] is None

    def test_corroboration_unavailable_gives_null_field(self):
        corr = LtaCorroboration(
            camera_id="4798", camera_lat=0.0, camera_lng=0.0,
            matches=[], queried_at="2026-04-15T08:30:00Z", api_available=False,
        )
        alert = render_alert(**self._base_args(), corroboration=corr)
        assert alert["lta_corroboration"] is None

    def test_corroboration_with_matches(self):
        event = LtaEvent("Accident", "Crash on AYE", 1.295, 103.871, "TrafficIncidents")
        match = LtaMatch(event=event, distance_m=23.5, match_type="location_and_domain")
        corr = LtaCorroboration(
            camera_id="4798", camera_lat=1.29531, camera_lng=103.871,
            matches=[match], queried_at="2026-04-15T08:30:00Z", api_available=True,
        )
        alert = render_alert(**self._base_args(), corroboration=corr)

        lta = alert["lta_corroboration"]
        assert lta is not None
        assert lta["camera_location"] == {"lat": 1.29531, "lng": 103.871}
        assert lta["api_available"] is True
        assert len(lta["matches"]) == 1
        assert lta["matches"][0]["event_type"] == "Accident"
        assert lta["matches"][0]["match_type"] == "location_and_domain"
        assert lta["match_summary"]["total"] == 1
        assert lta["match_summary"]["location_and_domain"] == 1
        assert lta["match_summary"]["location_only"] == 0

    def test_existing_fields_unchanged_with_corroboration(self):
        event = LtaEvent("Accident", "Crash", 1.295, 103.871, "TrafficIncidents")
        match = LtaMatch(event=event, distance_m=50.0, match_type="location_and_domain")
        corr = LtaCorroboration(
            camera_id="4798", camera_lat=1.29531, camera_lng=103.871,
            matches=[match], queried_at="2026-04-15T08:30:00Z", api_available=True,
        )
        alert = render_alert(**self._base_args(), corroboration=corr)

        # All 11 original fields still present
        for key in [
            "alert_id", "domain", "sub_type", "severity", "message",
            "source_expert", "evidence", "regulations", "department",
            "timestamp", "image_path",
        ]:
            assert key in alert
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alert_manager.py::TestRenderAlertCorroboration -v`
Expected: FAIL with `TypeError: render_alert() got an unexpected keyword argument 'corroboration'`

- [ ] **Step 3: Modify render_alert to accept corroboration**

Edit `src/skymirror/tools/alert/rendering.py`. Update the import and function:

Edit the existing imports in `rendering.py`:
- Change `from typing import Any` to `from typing import Any, TYPE_CHECKING`
- Add after the existing imports block:
```python
if TYPE_CHECKING:
    from skymirror.tools.alert.lta_lookup import LtaCorroboration
```

(Do NOT duplicate `from __future__ import annotations` — it's already present.)

Replace the `render_alert` function signature and body:

```python
def render_alert(
    expert_name: str,
    classification: dict[str, str],
    findings: list[dict[str, Any]],
    regulations: list[dict[str, Any]],
    image_path: str,
    corroboration: LtaCorroboration | None = None,
) -> dict[str, Any]:
    """Assemble a complete alert dict from classification + expert data.

    All structured fields are rule-based; only `message` comes from LLM
    (via the classification dict).
    """
    domain = DOMAIN_MAP.get(expert_name, "unknown")
    department = DEPARTMENT_MAP.get(domain, "General Operations")

    evidence = [f.get("description", "") for f in findings if f.get("description")]

    lta_corroboration = None
    if corroboration is not None and corroboration.api_available:
        lta_corroboration = {
            "camera_location": {"lat": corroboration.camera_lat, "lng": corroboration.camera_lng},
            "queried_at": corroboration.queried_at,
            "api_available": True,
            "matches": [
                {
                    "event_type": m.event.event_type,
                    "description": m.event.description,
                    "distance_m": m.distance_m,
                    "match_type": m.match_type,
                    "source_api": m.event.source_api,
                }
                for m in corroboration.matches
            ],
            "match_summary": {
                "total": len(corroboration.matches),
                "location_and_domain": sum(
                    1 for m in corroboration.matches if m.match_type == "location_and_domain"
                ),
                "location_only": sum(
                    1 for m in corroboration.matches if m.match_type == "location_only"
                ),
            },
        }

    return {
        "alert_id": _deterministic_id(image_path, expert_name),
        "domain": domain,
        "sub_type": classification["sub_type"],
        "severity": classification["severity"],
        "message": classification["message"],
        "source_expert": expert_name,
        "evidence": evidence,
        "regulations": regulations,
        "department": department,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "image_path": image_path,
        "lta_corroboration": lta_corroboration,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alert_manager.py::TestRenderAlertCorroboration -v`
Expected: 4 PASSED

- [ ] **Step 5: Run all tests to check no regression**

Run: `python -m pytest tests/test_alert_manager.py -v`
Expected: All tests PASS. Existing render tests still pass because `corroboration` defaults to None.

- [ ] **Step 6: Commit**

```bash
git add src/skymirror/tools/alert/rendering.py tests/test_alert_manager.py
git commit -m "feat(alert): add lta_corroboration field to rendered alert dict"
```

---

### Task 6: Alert Manager Changes

**Files:**
- Modify: `src/skymirror/agents/alert_manager.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests for camera ID extraction and LTA integration**

Append to `tests/test_alert_manager.py`:

```python
from skymirror.agents.alert_manager import _extract_camera_id


class TestExtractCameraId:
    """Tests for _extract_camera_id helper."""

    def test_standard_format(self):
        assert _extract_camera_id("data/frames/cam4798_20260412T083000.jpg") == "4798"

    def test_just_filename(self):
        assert _extract_camera_id("cam1701_20260412.jpg") == "1701"

    def test_no_match_returns_none(self):
        assert _extract_camera_id("random_image.jpg") is None

    def test_empty_string_returns_none(self):
        assert _extract_camera_id("") is None


class TestAlertManagerLtaIntegration:
    """Tests for LTA lookup integration in generate_alerts."""

    def test_alert_includes_corroboration(self, mock_llm, tmp_path, fixtures_dir):
        """When LTA lookup succeeds, alert dict has lta_corroboration."""
        fixture_data = json.loads((fixtures_dir / "alert_expert_results.json").read_text())
        scenario = fixture_data["single_expert"]
        lta_sample = json.loads((fixtures_dir / "lta_responses.json").read_text())

        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            if "data.gov.sg" in url:
                mock_resp.json.return_value = lta_sample["camera_api"]
            elif "TrafficIncidents" in url:
                mock_resp.json.return_value = lta_sample["traffic_incidents"]
            elif "FaultyTrafficLights" in url:
                mock_resp.json.return_value = lta_sample["faulty_traffic_lights"]
            elif "RoadWorks" in url:
                mock_resp.json.return_value = lta_sample["road_works"]
            else:
                mock_resp.json.return_value = {"value": []}
            return mock_resp

        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_httpx.get.side_effect = mock_get
            with patch.dict(os.environ, {"LTA_API_KEY": "test-key"}):
                alerts = generate_alerts(
                    expert_results=scenario["expert_results"],
                    image_path=scenario["image_path"],
                    rag_citations=scenario.get("rag_citations", []),
                    output_dir=tmp_path,
                )

        assert len(alerts) == 1
        assert "lta_corroboration" in alerts[0]

    def test_alert_without_lta_key(self, mock_llm, tmp_path, fixtures_dir):
        """When LTA_API_KEY is missing, alert still generated with null corroboration."""
        fixture_data = json.loads((fixtures_dir / "alert_expert_results.json").read_text())
        scenario = fixture_data["single_expert"]

        with patch("skymirror.tools.alert.lta_lookup.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"items": [{"cameras": []}]}
            mock_httpx.get.return_value = mock_resp

            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("LTA_API_KEY", None)
                alerts = generate_alerts(
                    expert_results=scenario["expert_results"],
                    image_path=scenario["image_path"],
                    rag_citations=scenario.get("rag_citations", []),
                    output_dir=tmp_path,
                )

        assert len(alerts) == 1
        assert alerts[0]["lta_corroboration"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alert_manager.py::TestExtractCameraId tests/test_alert_manager.py::TestAlertManagerLtaIntegration -v`
Expected: FAIL with `ImportError: cannot import name '_extract_camera_id'`

- [ ] **Step 3: Modify alert_manager.py**

Edit `src/skymirror/agents/alert_manager.py`.

Add import at the top (after existing imports):
```python
import re

from skymirror.tools.alert.lta_lookup import lookup_lta_events
```

Add helper function before `generate_alerts`:
```python
_CAMERA_ID_RE = re.compile(r"cam(\d+)")


def _extract_camera_id(image_path: str) -> str | None:
    """Extract camera ID from image path, e.g. 'cam4798_...' -> '4798'."""
    m = _CAMERA_ID_RE.search(image_path)
    return m.group(1) if m else None
```

In `generate_alerts`, replace the tool sequence inside the for loop. Change:
```python
        # Tool 1: Classify
        classification = classify(
            domain=domain,
            findings=findings,
            expert_severity=expert_severity,
        )

        # Tool 2: Render
        alert = render_alert(
            expert_name=expert_name,
            classification=classification,
            findings=findings,
            regulations=rag_citations,
            image_path=image_path,
        )

        # Tool 3: Dispatch
        dispatch(alert, output_dir=output_dir)
```

To:
```python
        # Tool 1: Classify
        classification = classify(
            domain=domain,
            findings=findings,
            expert_severity=expert_severity,
        )

        # Tool 2: LTA corroboration
        camera_id = _extract_camera_id(image_path)
        corroboration = lookup_lta_events(camera_id, domain) if camera_id else None

        # Tool 3: Render
        alert = render_alert(
            expert_name=expert_name,
            classification=classification,
            findings=findings,
            regulations=rag_citations,
            image_path=image_path,
            corroboration=corroboration,
        )

        # Tool 4: Dispatch
        dispatch(alert, output_dir=output_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alert_manager.py::TestExtractCameraId tests/test_alert_manager.py::TestAlertManagerLtaIntegration -v`
Expected: 6 PASSED

- [ ] **Step 5: Run all tests to check no regression**

Run: `python -m pytest tests/test_alert_manager.py -v`
Expected: All tests PASS. Existing integration tests still pass because LTA lookup returns None/unavailable when httpx is not mocked (the mock_llm fixture doesn't mock httpx).

Note: If existing integration tests fail because `lookup_lta_events` makes real HTTP calls, add this to `conftest.py`:

```python
@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Prevent accidental network calls in tests."""
    import skymirror.tools.alert.lta_lookup as lta_mod
    monkeypatch.setattr(lta_mod, "httpx", MagicMock(get=MagicMock(side_effect=Exception("blocked"))))
```

This ensures `lookup_lta_events` returns `api_available=False` in all tests that don't explicitly mock httpx.

- [ ] **Step 6: Commit**

```bash
git add src/skymirror/agents/alert_manager.py tests/test_alert_manager.py tests/conftest.py
git commit -m "feat(alert): integrate LTA lookup into alert generation flow"
```

---

### Task 7: Evaluation Script

**Files:**
- Create: `scripts/evaluate_alerts.py`
- Modify: `tests/test_alert_manager.py`

- [ ] **Step 1: Write failing tests for evaluation script**

Append to `tests/test_alert_manager.py`:

```python
from scripts.evaluate_alerts import evaluate_alerts, load_alerts


class TestEvaluateAlerts:
    """Tests for the evaluation script logic."""

    def test_load_alerts_from_dir(self, tmp_path):
        alert = {
            "alert_id": "abc123",
            "domain": "traffic",
            "image_path": "data/frames/cam4798_20260412T083000.jpg",
            "lta_corroboration": None,
        }
        (tmp_path / "abc123.json").write_text(json.dumps(alert))
        (tmp_path / "dispatch_log.jsonl").write_text("")  # should be skipped

        alerts = load_alerts(tmp_path)
        assert len(alerts) == 1
        assert alerts[0]["alert_id"] == "abc123"

    def test_evaluate_with_existing_corroboration(self, tmp_path):
        alert = {
            "alert_id": "abc123",
            "domain": "traffic",
            "image_path": "data/frames/cam4798_20260412T083000.jpg",
            "lta_corroboration": {
                "api_available": True,
                "matches": [
                    {"match_type": "location_and_domain", "event_type": "Accident",
                     "description": "Crash", "distance_m": 50.0, "source_api": "TrafficIncidents"}
                ],
                "match_summary": {"total": 1, "location_and_domain": 1, "location_only": 0},
            },
        }
        (tmp_path / "abc123.json").write_text(json.dumps(alert))

        report = evaluate_alerts(tmp_path, radius_m=500.0)

        assert report["total_alerts"] == 1
        assert report["corroborated"] == 1
        assert report["uncorroborated"] == 0

    def test_evaluate_empty_dir(self, tmp_path):
        report = evaluate_alerts(tmp_path, radius_m=500.0)
        assert report["total_alerts"] == 0
        assert report["corroborated"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_alert_manager.py::TestEvaluateAlerts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`

- [ ] **Step 3: Create the evaluation script**

Create `scripts/__init__.py` (empty file) and `scripts/evaluate_alerts.py`:

`scripts/__init__.py`:
```python
```

`scripts/evaluate_alerts.py`:
```python
"""Batch evaluation: compare Alert Agent output vs LTA DataMall ground truth.

Usage:
    python scripts/evaluate_alerts.py --alert-dir output/ --radius 500 --output eval_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as script from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from skymirror.tools.alert.lta_lookup import lookup_lta_events  # noqa: E402


def load_alerts(alert_dir: Path) -> list[dict[str, Any]]:
    """Load all alert JSON files from a directory (skip non-alert files)."""
    alerts: list[dict[str, Any]] = []
    for path in sorted(alert_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "alert_id" in data:
                alerts.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return alerts


def _extract_camera_id(image_path: str) -> str | None:
    """Extract camera ID from image path."""
    import re
    m = re.search(r"cam(\d+)", image_path)
    return m.group(1) if m else None


def evaluate_alerts(
    alert_dir: Path,
    radius_m: float = 500.0,
) -> dict[str, Any]:
    """Run evaluation on all alerts in a directory.

    For alerts without existing lta_corroboration, queries LTA API to backfill.
    Returns a summary report dict.
    """
    alerts = load_alerts(alert_dir)

    corroborated = 0
    partially_matched = 0
    uncorroborated = 0
    api_unavailable = 0
    per_alert_details: list[dict[str, Any]] = []

    for alert in alerts:
        lta = alert.get("lta_corroboration")

        # Backfill if needed
        if lta is None:
            camera_id = _extract_camera_id(alert.get("image_path", ""))
            if camera_id:
                result = lookup_lta_events(camera_id, alert.get("domain", "unknown"), radius_m)
                if result.api_available:
                    lta = {
                        "api_available": True,
                        "matches": [
                            {
                                "event_type": m.event.event_type,
                                "description": m.event.description,
                                "distance_m": m.distance_m,
                                "match_type": m.match_type,
                                "source_api": m.event.source_api,
                            }
                            for m in result.matches
                        ],
                        "match_summary": {
                            "total": len(result.matches),
                            "location_and_domain": sum(
                                1 for m in result.matches if m.match_type == "location_and_domain"
                            ),
                            "location_only": sum(
                                1 for m in result.matches if m.match_type == "location_only"
                            ),
                        },
                    }

        # Classify result
        if lta is None or not lta.get("api_available", False):
            api_unavailable += 1
            status = "api_unavailable"
        elif any(m.get("match_type") == "location_and_domain" for m in lta.get("matches", [])):
            corroborated += 1
            status = "corroborated"
        elif lta.get("matches"):
            partially_matched += 1
            status = "partially_matched"
        else:
            uncorroborated += 1
            status = "uncorroborated"

        per_alert_details.append({
            "alert_id": alert.get("alert_id"),
            "domain": alert.get("domain"),
            "status": status,
            "match_count": len(lta.get("matches", [])) if lta else 0,
        })

    evaluable = len(alerts) - api_unavailable
    corroboration_rate = (corroborated / evaluable) if evaluable > 0 else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_alerts": len(alerts),
        "corroborated": corroborated,
        "partially_matched": partially_matched,
        "uncorroborated": uncorroborated,
        "api_unavailable": api_unavailable,
        "corroboration_rate": round(corroboration_rate, 3),
        "per_alert_details": per_alert_details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Alert Agent output vs LTA ground truth.")
    parser.add_argument("--alert-dir", type=Path, required=True, help="Directory with alert JSON files")
    parser.add_argument("--radius", type=float, default=500.0, help="Match radius in metres (default: 500)")
    parser.add_argument("--output", type=Path, default=None, help="Output file for report JSON")
    args = parser.parse_args(argv)

    if not args.alert_dir.is_dir():
        print(f"ERROR: {args.alert_dir} is not a directory.", file=sys.stderr)
        return 1

    report = evaluate_alerts(args.alert_dir, radius_m=args.radius)

    report_json = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(report_json, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(report_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alert_manager.py::TestEvaluateAlerts -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/evaluate_alerts.py tests/test_alert_manager.py
git commit -m "feat(alert): add evaluation script for LTA ground truth comparison"
```

---

### Task 8: .env.example Update and Final Verification

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add LTA_API_KEY to .env.example**

Add after the `# --- Alerting ----------------------------------------------------------------` section in `.env.example`:

```
# --- LTA DataMall (Real-Time Corroboration) -----------------------------------
LTA_API_KEY=                            # Request at https://datamall.lta.gov.sg/content/datamall/en/request-for-api.html
```

- [ ] **Step 2: Run full test suite**

Run: `cd ~/Desktop/Explainable\ and\ Responsible\ AI/Group\ Project/SKYMIRROR && python -m pytest tests/ -v`
Expected: All tests PASS (existing + ~18 new tests)

- [ ] **Step 3: Run CLI demo to verify no import errors**

Run: `cd ~/Desktop/Explainable\ and\ Responsible\ AI/Group\ Project/SKYMIRROR && python -m skymirror.agents.alert_manager --fixture single_expert --output-dir /tmp/skymirror-test-alerts`
Expected: 1 alert generated, output includes `lta_corroboration: null` (since no LTA_API_KEY set)

- [ ] **Step 4: Commit**

```bash
git add .env.example
git commit -m "docs: add LTA_API_KEY to .env.example"
```

- [ ] **Step 5: Verify git log**

Run: `git log --oneline -8`
Expected: 7 new commits for this feature on top of existing alert agent work.
