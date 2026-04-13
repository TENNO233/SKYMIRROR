"""Tests for Daily Explication Report Agent."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Task 5: load_oa_log
# ---------------------------------------------------------------------------

def test_load_oa_log_reads_jsonl(fixtures_dir: Path):
    from skymirror.agents.report_helpers import load_oa_log
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    assert len(records) == 6
    assert records[0]["decision_id"] == "oa_20260412T083000_cam4798"


def test_load_oa_log_missing_file_returns_empty(tmp_path: Path):
    from skymirror.agents.report_helpers import load_oa_log
    records = load_oa_log(tmp_path, date(2026, 4, 12))
    assert records == []


def test_load_oa_log_skips_malformed_lines(fixtures_dir: Path):
    from skymirror.agents.report_helpers import load_oa_log
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="malformed_day")
    assert len(records) == 2
    assert records[0]["decision_id"] == "oa_good_001"
    assert records[1]["decision_id"] == "oa_good_002"


# ---------------------------------------------------------------------------
# Task 6: SGT date helpers
# ---------------------------------------------------------------------------

def test_yesterday_sgt_returns_previous_sgt_date(monkeypatch):
    from skymirror.agents import report_helpers
    fixed = datetime(2026, 4, 13, 2, 0, tzinfo=timezone.utc)  # = 10:00 SGT
    class _Clock:
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)
    monkeypatch.setattr(report_helpers, "datetime", _Clock)
    assert report_helpers.yesterday_sgt() == date(2026, 4, 12)


def test_yesterday_sgt_handles_late_utc_next_sgt_day(monkeypatch):
    """At 20:00 UTC on 2026-04-13, SGT time is 04:00 on 2026-04-14.
    So 'yesterday_sgt' should be 2026-04-13."""
    from skymirror.agents import report_helpers
    fixed = datetime(2026, 4, 13, 20, 0, tzinfo=timezone.utc)  # = 04:00 SGT on 04-14
    class _Clock:
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)
    monkeypatch.setattr(report_helpers, "datetime", _Clock)
    assert report_helpers.yesterday_sgt() == date(2026, 4, 13)


# ---------------------------------------------------------------------------
# Task 7: compute_overview_stats
# ---------------------------------------------------------------------------

def test_compute_overview_stats_on_normal_day(fixtures_dir: Path):
    from skymirror.agents.report_helpers import load_oa_log, compute_overview_stats
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    stats = compute_overview_stats(records)

    assert stats["total_decisions"] == 6
    assert stats["total_triggered"] == 4
    assert abs(stats["trigger_rate"] - 4/6) < 1e-9

    assert stats["severity_counts"] == {"critical": 1, "high": 2, "medium": 1}
    assert stats["type_counts"] == {
        "traffic_violation": 2,
        "traffic_accident": 1,
        "env_hazard": 1,
    }
    assert stats["dispatch_counts"]["traffic_police"] == 3
    assert stats["dispatch_counts"]["ambulance"] == 1
    assert stats["dispatch_counts"]["road_maintenance"] == 2


def test_compute_overview_stats_empty():
    from skymirror.agents.report_helpers import compute_overview_stats
    stats = compute_overview_stats([])
    assert stats["total_decisions"] == 0
    assert stats["total_triggered"] == 0
    assert stats["trigger_rate"] == 0.0
    assert stats["severity_counts"] == {}
    assert stats["type_counts"] == {}
    assert stats["dispatch_counts"] == {}


# ---------------------------------------------------------------------------
# Task 8: compute_temporal_stats
# ---------------------------------------------------------------------------

def test_compute_temporal_stats_on_normal_day(fixtures_dir: Path):
    from skymirror.agents.report_helpers import load_oa_log, compute_temporal_stats
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    stats = compute_temporal_stats(records)

    # 00:30Z = 08:30 SGT -> hour 8
    # 06:15Z = 14:15 SGT -> hour 14
    # 08:42Z = 16:42 SGT -> hour 16
    # 12:05Z = 20:05 SGT -> hour 20
    assert stats["hourly_triggered"][8] == 1
    assert stats["hourly_triggered"][14] == 1
    assert stats["hourly_triggered"][16] == 1
    assert stats["hourly_triggered"][20] == 1

    assert stats["peak_hour"] in {8, 14, 16, 20}


# ---------------------------------------------------------------------------
# Task 9: compute_system_profile_stats
# ---------------------------------------------------------------------------

def test_compute_system_profile_on_normal_day(fixtures_dir: Path):
    from skymirror.agents.report_helpers import load_oa_log, compute_system_profile_stats
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    profile = compute_system_profile_stats(records)

    assert profile["expert_activation_counts"]["order_expert"] == 3
    assert profile["expert_activation_counts"]["safety_expert"] == 1
    assert profile["expert_activation_counts"]["environment_expert"] == 2

    assert profile["fallback_count"] == 1
    assert abs(profile["fallback_rate"] - 1/6) < 1e-9

    # citations: records 0 (0.89), 1 (0.91), 2 (0.82), 5 (0.88) -> avg 0.875
    assert abs(profile["avg_rag_relevance"] - 0.875) < 1e-6

    assert profile["top_regulation_code"] == "RTA Section 120(3)"

    # triggered oa_confidence: 0.92, 0.96, 0.81, 0.89  -> 2 high, 2 mid, 0 low
    assert profile["oa_confidence_buckets"] == {"high_\u22650.9": 2, "mid_0.7\u20130.89": 2, "low_<0.7": 0}
