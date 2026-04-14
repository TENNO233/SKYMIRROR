"""Tests for Alert Generation Agent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def alert_fixtures(fixtures_dir: Path) -> dict:
    """Load alert test fixtures."""
    return json.loads((fixtures_dir / "alert_expert_results.json").read_text())


# ---------------------------------------------------------------------------
# Task 1: Constants
# ---------------------------------------------------------------------------

def test_domain_map_covers_all_experts():
    from skymirror.tools.alert.constants import DOMAIN_MAP
    assert DOMAIN_MAP["order_expert"] == "traffic"
    assert DOMAIN_MAP["safety_expert"] == "safety"
    assert DOMAIN_MAP["environment_expert"] == "environment"


def test_sub_type_map_has_other_for_each_domain():
    from skymirror.tools.alert.constants import SUB_TYPE_MAP
    for domain in ("traffic", "safety", "environment"):
        assert "other" in SUB_TYPE_MAP[domain]


def test_department_map_covers_all_domains():
    from skymirror.tools.alert.constants import DEPARTMENT_MAP
    assert "traffic" in DEPARTMENT_MAP
    assert "safety" in DEPARTMENT_MAP
    assert "environment" in DEPARTMENT_MAP
    # Values are non-empty strings
    for dept in DEPARTMENT_MAP.values():
        assert isinstance(dept, str) and len(dept) > 0
