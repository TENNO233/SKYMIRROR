"""Enums, domain mappings, and department routing tables for the Alert Agent.

Used by: classification.py, rendering.py, dispatcher.py
"""
from __future__ import annotations

# Expert name -> alert domain
DOMAIN_MAP: dict[str, str] = {
    "order_expert": "traffic",
    "safety_expert": "safety",
    "environment_expert": "environment",
}

# Domain -> allowed sub-types (LLM picks from these; "other" is the fallback)
SUB_TYPE_MAP: dict[str, list[str]] = {
    "traffic": [
        "red_light",
        "wrong_way",
        "illegal_parking",
        "speeding",
        "illegal_lane_change",
        "other",
    ],
    "safety": [
        "collision",
        "pedestrian_intrusion",
        "dangerous_driving",
        "road_obstruction",
        "other",
    ],
    "environment": [
        "flooding",
        "low_visibility",
        "road_damage",
        "debris",
        "other",
    ],
}

# Domain -> receiving department (simulated)
DEPARTMENT_MAP: dict[str, str] = {
    "traffic": "Traffic Police",
    "safety": "Emergency Management Center",
    "environment": "Municipal & Meteorological Duty Office",
}

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
