# LTA DataMall Integration for Alert Agent

**Date**: 2026-04-15
**Author**: JK
**Status**: Approved
**Scope**: Alert Agent real-time corroboration + evaluation script

---

## Motivation

The Alert Agent currently relies solely on OA (Orchestrator Agent) expert analysis of camera frames to generate alerts. By integrating LTA DataMall real-time APIs, the Alert Agent gains an independent data source to cross-reference OA's judgments against official records. This serves two purposes:

1. **Real-time corroboration (Priority 1)**: Enrich each alert's evidence chain with matching LTA official events, giving the Alert Agent independent judgment beyond what OA provides.
2. **Evaluation (Priority 2)**: Use LTA official data as ground truth to measure the Alert Agent's detection accuracy.

Both purposes enhance the system's explainability (XAI) — a core requirement of the course project.

---

## Architecture: Post-classification Enrichment (Approach A)

LTA lookup happens **after** classification, **before** rendering. This ensures:
- Classification is independent of external API availability
- LTA data enriches evidence without influencing severity/type decisions
- Graceful degradation is natural — skip LTA step if unavailable

### Alert Agent Flow (updated)

```
OA expert_results
  → classify()                   # existing, unchanged
  → lookup_lta_events()          # NEW: query LTA DataMall
  → render_alert()               # MODIFIED: accepts corroboration
  → dispatch()                   # existing, unchanged
```

---

## Component 1: LTA Lookup Tool

**File**: `src/skymirror/tools/alert/lta_lookup.py`

### Public Interface

```python
def lookup_lta_events(
    camera_id: str,
    domain: str,
    radius_m: float = 500.0,
) -> LtaCorroboration:
    """Query LTA DataMall for official events near a camera, return matches."""
```

### Internal Flow

```
camera_id
  → resolve_camera_location(camera_id)   # data.gov.sg traffic-images API → lat/lng
  → fetch_lta_events(domain)             # LTA DataMall endpoints per domain
  → match_events(lat, lng, radius_m, domain, events)  # geo + type matching
  → LtaCorroboration(...)
```

### Data Structures

```python
@dataclass
class LtaEvent:
    event_type: str        # LTA raw type, e.g. "Accident", "Road Work"
    description: str       # LTA raw description
    latitude: float
    longitude: float
    source_api: str        # "TrafficIncidents" | "FaultyTrafficLights" | "FloodAlerts" | "RoadWorks"

@dataclass
class LtaMatch:
    event: LtaEvent
    distance_m: float
    match_type: str        # "location_and_domain" | "location_only"

@dataclass
class LtaCorroboration:
    camera_id: str
    camera_lat: float
    camera_lng: float
    matches: list[LtaMatch]
    queried_at: str        # ISO 8601 UTC
    api_available: bool    # False if API key missing or request failed
```

### LTA API Endpoints per Domain

Added to `constants.py`:

```python
LTA_DOMAIN_MAP = {
    "traffic": ["TrafficIncidents", "FaultyTrafficLights"],
    "safety": ["TrafficIncidents"],
    "environment": ["PUB_Flood", "RoadWorks"],
}

# All endpoints to query (superset)
LTA_ALL_ENDPOINTS = ["TrafficIncidents", "FaultyTrafficLights", "RoadWorks", "PUB_Flood"]
```

All LTA endpoints are queried regardless of domain. Events from endpoints listed in the domain's `LTA_DOMAIN_MAP` entry are tagged `location_and_domain`; events from other endpoints are tagged `location_only`. This implements the two-layer matching (option C) agreed during design.

### Camera Location Resolution

Uses the same `api.data.gov.sg/v1/transport/traffic-images` API the team already uses in `get_traffic.py`. Response contains `camera_id`, `latitude`, `longitude` per camera. Camera list is fetched once per `lookup_lta_events` call (could be cached in future).

### LTA DataMall API Access

- API key read from `LTA_API_KEY` environment variable
- Auth header: `{"AccountKey": LTA_API_KEY}`
- Base URL: `http://datamall2.mytransport.sg/ltaodataservice/`
- Queried endpoints:
  - `TrafficIncidents` — accidents, vehicle breakdowns, road blocks, diversions
  - `FaultyTrafficLights` — faulty or under-maintenance traffic lights
  - `RoadWorks` — approved road construction/maintenance
  - `PUB_Flood` — flood alerts from PUB (Public Utilities Board)

### Graceful Degradation

All three failure modes return `LtaCorroboration(api_available=False, matches=[])`:
- `LTA_API_KEY` environment variable not set
- LTA API request fails (timeout, 4xx, 5xx)
- data.gov.sg camera resolution fails (camera_id not found)

No exceptions propagated. Warning logged via `structlog`.

### Geo Distance Calculation

Haversine formula for distance between two lat/lng points. Simple, no external dependency needed. Events beyond `radius_m` are filtered out.

---

## Component 2: Alert Manager Changes

**File**: `src/skymirror/agents/alert_manager.py`

### Changes

In `generate_alerts()`, for each expert with findings:

```python
# existing
classification = classify(domain, findings, severity, llm)

# NEW: extract camera_id, query LTA
camera_id = _extract_camera_id(image_path)
corroboration = lookup_lta_events(camera_id, domain) if camera_id else None

# MODIFIED: pass corroboration to render
alert = render_alert(expert, domain, classification, image_path, rag_citations, corroboration)

# existing
dispatch(alert, output_dir)
```

### Camera ID Extraction

```python
def _extract_camera_id(image_path: str) -> str | None:
    """Extract camera ID from image path. e.g. 'cam4798_20260412.jpg' → '4798'."""
```

Regex-based. Returns None on parse failure → LTA lookup skipped.

### Impact

- No change to function signature or return type
- No change to existing behavior when LTA is unavailable
- ~5 lines of new logic

---

## Component 3: Rendering Changes

**File**: `src/skymirror/tools/alert/rendering.py`

### Changes

`render_alert()` gains optional parameter:

```python
def render_alert(
    expert_name, domain, classification, image_path, rag_citations,
    corroboration: LtaCorroboration | None = None,  # NEW
) -> dict:
```

### New Field in Alert Dict

```python
{
    # ... existing 11 fields unchanged ...
    "lta_corroboration": {
        "camera_location": {"lat": 1.3456, "lng": 103.8765},
        "queried_at": "2026-04-15T08:30:00Z",
        "api_available": true,
        "matches": [
            {
                "event_type": "Accident",
                "description": "Accident on PIE towards Tuas after Bt Batok Rd Exit",
                "distance_m": 230.5,
                "match_type": "location_and_domain",
                "source_api": "TrafficIncidents"
            }
        ],
        "match_summary": {
            "total": 3,
            "location_and_domain": 1,
            "location_only": 2
        }
    }
}
```

- `corroboration` is None or `api_available=False` → `"lta_corroboration": null`
- `match_summary` is computed from matches list (pure calculation)
- LTA data stays in its own field, separate from `evidence` (OA observations) and `regulations` (RAG citations) — three distinct evidence sources with clear provenance for XAI audit trail

---

## Component 4: Constants Changes

**File**: `src/skymirror/tools/alert/constants.py`

### Additions

```python
# LTA DataMall endpoint → Alert Agent domain mapping
LTA_DOMAIN_MAP: dict[str, list[str]] = {
    "traffic": ["TrafficIncidents", "FaultyTrafficLights"],
    "safety": ["TrafficIncidents"],
    "environment": ["PUB_Flood", "RoadWorks"],
}

# All endpoints to query (superset of all domain-specific endpoints)
LTA_ALL_ENDPOINTS: list[str] = ["TrafficIncidents", "FaultyTrafficLights", "RoadWorks", "PUB_Flood"]

# LTA DataMall base URL
LTA_BASE_URL = "http://datamall2.mytransport.sg/ltaodataservice/"

# data.gov.sg camera API
CAMERA_API_URL = "https://api.data.gov.sg/v1/transport/traffic-images"
```

---

## Component 5: Evaluation Script

**File**: `scripts/evaluate_alerts.py`

### Usage

```bash
python scripts/evaluate_alerts.py --alert-dir output/ --radius 500 --output eval_report.json
```

### Flow

1. Read all `*.json` alert files from `--alert-dir`
2. For each alert:
   - If `lta_corroboration` field exists and `api_available=True` → use it
   - Otherwise → extract camera_id from `image_path`, call `lookup_lta_events` to backfill
3. Compute statistics
4. Detect undetected events: query all LTA events, find those within radius of any camera but not matched by any alert
5. Output report

### Report Structure

```python
{
    "generated_at": "2026-04-15T10:00:00Z",
    "total_alerts": 15,
    "corroborated": 8,          # has location_and_domain match
    "partially_matched": 3,     # location_only match only
    "uncorroborated": 2,        # no LTA events nearby
    "api_unavailable": 2,       # query failed
    "corroboration_rate": 0.615,  # corroborated / (total - api_unavailable)
    "lta_undetected": [
        {
            "event_type": "Road Work",
            "description": "...",
            "location": {"lat": 1.345, "lng": 103.876},
            "nearest_camera": "4798",
            "distance_m": 150.0
        }
    ],
    "per_alert_details": [...]
}
```

### Reuse

Imports `lookup_lta_events` and related functions from `tools/alert/lta_lookup.py`. No duplicate API/matching logic.

---

## Testing Strategy

### New Tests (in `tests/test_alert_manager.py`)

**lta_lookup tests (~8-10):**
- `resolve_camera_location`: correct camera_id → lat/lng
- `resolve_camera_location`: unknown camera_id → None
- `fetch_lta_events`: correct endpoint selection per domain
- `match_events`: distance calculation accuracy (known coordinate pairs)
- `match_events`: type matching — domain events → `location_and_domain`, others → `location_only`
- `match_events`: beyond-radius events filtered out
- Graceful degradation: missing `LTA_API_KEY` → `api_available=False`
- Graceful degradation: API request failure → `api_available=False`
- Graceful degradation: camera resolution failure → `api_available=False`

**rendering tests (~3):**
- Corroboration with matches → full `lta_corroboration` field in alert dict
- Corroboration is None → `"lta_corroboration": null`
- `match_summary` counts correct

**alert_manager integration tests (~2):**
- `_extract_camera_id`: `cam4798_20260412T083000.jpg` → `"4798"`
- End-to-end with mocked LTA: alert output includes corroboration

**evaluation script tests (~3):**
- Alert files + mocked LTA → correct report statistics
- Alerts with existing corroboration → no redundant API calls
- Empty alert dir → empty report, no errors

### Mock Strategy

- LTA DataMall and data.gov.sg: mock via `pytest-mock` patching `httpx.get`
- Add LTA response sample JSONs to `tests/fixtures/`
- Reuse existing `conftest.py` mock_llm fixture (classification unchanged)

---

## Files Changed Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `tools/alert/lta_lookup.py` | NEW | LTA API calls + geo/type matching |
| `tools/alert/constants.py` | MODIFY | Add `LTA_DOMAIN_MAP`, `LTA_BASE_URL`, `CAMERA_API_URL` |
| `agents/alert_manager.py` | MODIFY | Add lta_lookup call + camera_id extraction (~5 lines) |
| `tools/alert/rendering.py` | MODIFY | Accept corroboration, add `lta_corroboration` field |
| `scripts/evaluate_alerts.py` | NEW | Batch evaluation script |
| `tests/test_alert_manager.py` | MODIFY | Add ~16-18 new tests |
| `tests/fixtures/lta_responses.json` | NEW | Mock LTA API response samples |
| `.env.example` | MODIFY | Add `LTA_API_KEY` |

### Not Changed

- `tools/alert/classification.py` — classification logic untouched
- `tools/alert/dispatcher.py` — dispatch logic untouched
- `tools/llm_factory.py` — no new LLM calls
- Any files outside JK's responsibility (graph/*, experts, vlm_agent, etc.)

---

## Dependencies

No new packages required:
- `httpx` already in `pyproject.toml` (used by camera_fetcher.py)
- `math` stdlib for haversine
- `dataclasses` stdlib for LTA data structures
- `re` stdlib for camera_id extraction
