"""Tests for Daily Explication Report Agent."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Task 5: load_oa_log
# ---------------------------------------------------------------------------

def test_load_oa_log_reads_jsonl(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    assert len(records) == 6
    assert records[0]["decision_id"] == "oa_20260412T083000_cam4798"


def test_load_oa_log_missing_file_returns_empty(tmp_path: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    records = load_oa_log(tmp_path, date(2026, 4, 12))
    assert records == []


def test_load_oa_log_skips_malformed_lines(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="malformed_day")
    assert len(records) == 2
    assert records[0]["decision_id"] == "oa_good_001"
    assert records[1]["decision_id"] == "oa_good_002"


# ---------------------------------------------------------------------------
# Task 6: SGT date helpers
# ---------------------------------------------------------------------------

def test_yesterday_sgt_returns_previous_sgt_date(monkeypatch):
    from skymirror.tools.daily_report import loader as report_helpers
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
    from skymirror.tools.daily_report import loader as report_helpers
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
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.analysis import compute_overview_stats
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
    from skymirror.tools.daily_report.analysis import compute_overview_stats
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
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.analysis import compute_temporal_stats
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


def test_compute_temporal_stats_empty():
    from skymirror.tools.daily_report.analysis import compute_temporal_stats
    stats = compute_temporal_stats([])
    assert stats["hourly_triggered"] == {}
    assert stats["hourly_total"] == {}
    assert stats["peak_hour"] is None
    assert stats["morning_dominant_type"] is None
    assert stats["evening_dominant_type"] is None


# ---------------------------------------------------------------------------
# Task 9: compute_system_profile_stats
# ---------------------------------------------------------------------------

def test_compute_system_profile_on_normal_day(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.analysis import compute_system_profile_stats
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


def test_compute_system_profile_empty():
    from skymirror.tools.daily_report.analysis import compute_system_profile_stats
    profile = compute_system_profile_stats([])
    assert profile["expert_activation_counts"] == {}
    assert profile["fallback_count"] == 0
    assert profile["fallback_rate"] == 0.0
    assert profile["avg_rag_relevance"] == 0.0
    assert profile["top_regulation_code"] is None
    assert profile["oa_confidence_buckets"] == {"high_\u22650.9": 0, "mid_0.7\u20130.89": 0, "low_<0.7": 0}


# ---------------------------------------------------------------------------
# Task 10: select_representative_cases
# ---------------------------------------------------------------------------

def test_select_cases_prefers_diversity(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.analysis import select_representative_cases
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    triggered = [r for r in records if r.get("is_emergency")]
    cases = select_representative_cases(triggered, n=3)

    types = {c["alert"]["emergency_type"] for c in cases}
    assert types == {"traffic_accident", "traffic_violation", "env_hazard"}
    assert any(c["alert"]["severity"] == "critical" for c in cases)


def test_select_cases_returns_fewer_than_n_if_data_insufficient():
    from skymirror.tools.daily_report.analysis import select_representative_cases
    assert select_representative_cases([], n=3) == []


def test_select_cases_single_type_returns_top_severity(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.analysis import select_representative_cases
    records = load_oa_log(
        fixtures_dir, date(2026, 4, 12), filename_stem_override="single_type_day"
    )
    triggered = [r for r in records if r.get("is_emergency")]
    cases = select_representative_cases(triggered, n=3)
    assert len(cases) == 3
    severities = [c["alert"]["severity"] for c in cases]
    assert severities[0] == "critical"
    assert severities[1] == "high"
    assert severities[2] == "medium"


# ---------------------------------------------------------------------------
# Task 11: LLM factory
# ---------------------------------------------------------------------------

def test_get_llm_default_is_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from skymirror.tools.llm_factory import get_llm
    llm = get_llm()
    assert type(llm).__name__ == "ChatAnthropic"


def test_get_llm_respects_openai_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-key")
    from skymirror.tools.llm_factory import get_llm
    llm = get_llm()
    assert type(llm).__name__ == "ChatOpenAI"


def test_get_llm_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    from skymirror.tools.llm_factory import get_llm
    with pytest.raises(ValueError):
        get_llm()


def test_narrate_uses_fallback_when_llm_fails(monkeypatch):
    """If the provided LLM object's invoke raises, narrate() returns fallback."""
    from skymirror.tools.llm_factory import narrate

    class _Broken:
        def invoke(self, *_a, **_kw):
            raise RuntimeError("API down")

    out = narrate("prompt", fallback="FALLBACK_TEXT", llm=_Broken())
    assert "FALLBACK_TEXT" in out
    assert "LLM narration unavailable" in out


# ---------------------------------------------------------------------------
# Task 12: Template renderers
# ---------------------------------------------------------------------------

def test_render_overview_section():
    from skymirror.tools.daily_report.rendering import render_overview_section
    stats = {
        "total_decisions": 6, "total_triggered": 4, "trigger_rate": 0.667,
        "severity_counts": {"critical": 1, "high": 2, "medium": 1},
        "type_counts": {"traffic_violation": 2, "traffic_accident": 1, "env_hazard": 1},
        "dispatch_counts": {"traffic_police": 3, "ambulance": 1, "road_maintenance": 2},
    }
    md = render_overview_section(stats)
    assert "## 1. Daily Overview" in md
    assert "6" in md and "4" in md and "66.7%" in md
    assert "critical" in md and "traffic_violation" in md
    assert "traffic_police" in md


def test_render_case_section_has_three_layers(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.rendering import render_case
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    case = records[1]  # the critical collision
    md = render_case(case, index=1)

    assert "Scene" in md
    assert "Expert Finding" in md or "Legal Citation" in md
    assert "OA Decision" in md or "Dispatch" in md
    assert "collision" in md.lower()
    assert "ERP-3.2" in md
    assert "ambulance" in md


# ---------------------------------------------------------------------------
# Task 13: Remaining template renderers
# ---------------------------------------------------------------------------

def test_render_empty_day_report_contains_self_diagnostic():
    from skymirror.tools.daily_report.rendering import render_empty_day_report
    md = render_empty_day_report(date(2026, 4, 12), case_label="A")
    assert "NOT necessarily normal" in md
    assert "Verification checklist" in md
    assert "2026-04-12" in md


def test_render_appendix_compact_list(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.rendering import render_appendix_section
    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    triggered = [r for r in records if r.get("is_emergency")]
    featured_ids = {triggered[0]["decision_id"]}
    md = render_appendix_section(triggered, featured_ids, jsonl_path="data/oa_log/2026-04-12.jsonl")
    assert "## 7. Appendix" in md
    assert "other" in md.lower()


def test_render_system_profile_section_has_metrics():
    from skymirror.tools.daily_report.rendering import render_system_profile_section
    profile = {
        "expert_activation_counts": {"order_expert": 3, "safety_expert": 1, "environment_expert": 2},
        "fallback_count": 1, "fallback_rate": 0.1667,
        "avg_rag_relevance": 0.875, "top_regulation_code": "RTA Section 120(3)",
        "oa_confidence_buckets": {"high_≥0.9": 2, "mid_0.7–0.89": 2, "low_<0.7": 0},
    }
    md = render_system_profile_section(profile, narration="MOCK_NARRATION")
    assert "## 5. System Behaviour Profile" in md
    assert "order_expert" in md
    assert "0.875" in md or "0.88" in md
    assert "RTA Section 120(3)" in md
    assert "MOCK_NARRATION" in md


# ---------------------------------------------------------------------------
# Task 14: Prompt builders
# ---------------------------------------------------------------------------

def test_build_tldr_prompt_embeds_facts_without_raw_records():
    from skymirror.tools.daily_report.rendering import build_tldr_prompt
    facts = {
        "total_triggered": 127, "peak_hour": 18,
        "dominant_type": "traffic_violation", "dominant_type_ratio": 0.70,
    }
    prompt = build_tldr_prompt(facts)
    assert "127" in prompt
    assert "traffic_violation" in prompt
    assert "Do NOT" in prompt or "do not" in prompt


# ---------------------------------------------------------------------------
# Task 15: Orchestrator end-to-end
# ---------------------------------------------------------------------------

def test_generate_report_end_to_end_normal_day(tmp_path, fixtures_dir, mock_llm):
    """End-to-end: normal_day fixture produces a 7-section Markdown report."""
    from skymirror.agents.report_generator import generate_report

    oa_log_dir = tmp_path / "oa_log"
    oa_log_dir.mkdir()
    src = (fixtures_dir / "normal_day.jsonl").read_bytes()
    (oa_log_dir / "2026-04-12.jsonl").write_bytes(src)

    output_dir = tmp_path / "reports"
    report_path = generate_report(
        target_date=date(2026, 4, 12),
        oa_log_dir=oa_log_dir,
        output_dir=output_dir,
    )

    assert report_path.exists()
    text = report_path.read_text()
    for heading in [
        "## 1. Daily Overview",
        "## 2. Executive Summary",
        "## 3. Temporal Pattern Analysis",
        "## 4. Representative Case Explications",
        "## 5. System Behaviour Profile",
        "## 6. Recommendations",
        "## 7. Appendix",
    ]:
        assert heading in text, f"missing: {heading}"

    assert "collision" in text.lower() or "red light" in text.lower()


def test_generate_report_empty_day_produces_self_diagnostic(tmp_path, mock_llm):
    from skymirror.agents.report_generator import generate_report
    oa_log_dir = tmp_path / "oa_log"
    oa_log_dir.mkdir()
    output_dir = tmp_path / "reports"
    report_path = generate_report(
        target_date=date(2026, 4, 12),
        oa_log_dir=oa_log_dir,
        output_dir=output_dir,
    )
    text = report_path.read_text()
    assert "NOT necessarily normal" in text
    assert "Verification checklist" in text


def test_generate_daily_report_legacy_wrapper_exists():
    """main.py's APScheduler imports `generate_daily_report` — must remain callable."""
    from skymirror.agents.report_generator import generate_daily_report
    assert callable(generate_daily_report)
