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
