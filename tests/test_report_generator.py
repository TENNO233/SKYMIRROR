"""Tests for RunRecord-based Daily Explication Report Agent."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest


def test_load_oa_log_reads_run_records(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log

    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")

    assert len(records) == 6
    assert records[0]["run_id"] == "run_001"
    assert records[0]["status"] == "alerted"


def test_load_oa_log_missing_file_returns_empty(tmp_path: Path):
    from skymirror.tools.daily_report.loader import load_oa_log

    assert load_oa_log(tmp_path, date(2026, 4, 12)) == []


def test_load_oa_log_skips_malformed_lines(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log

    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="malformed_day")

    assert len(records) == 2
    assert records[0]["run_id"] == "run_good_001"
    assert records[1]["run_id"] == "run_good_002"


def test_yesterday_sgt_returns_previous_sgt_date(monkeypatch):
    from skymirror.tools.daily_report import loader as report_helpers

    fixed = datetime(2026, 4, 13, 2, 0, tzinfo=timezone.utc)

    class _Clock:
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr(report_helpers, "datetime", _Clock)
    assert report_helpers.yesterday_sgt() == date(2026, 4, 12)


def test_compute_overview_stats_on_normal_day(fixtures_dir: Path):
    from skymirror.tools.daily_report.analysis import compute_overview_stats
    from skymirror.tools.daily_report.loader import load_oa_log

    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    stats = compute_overview_stats(records)

    assert stats["total_decisions"] == 6
    assert stats["total_triggered"] == 3
    assert stats["total_alerts"] == 4
    assert abs(stats["trigger_rate"] - 0.5) < 1e-9
    assert stats["severity_counts"] == {"high": 2, "critical": 1, "medium": 1}
    assert stats["type_counts"]["red_light"] == 1
    assert stats["dispatch_counts"]["Traffic Police"] == 1


def test_compute_temporal_stats_on_normal_day(fixtures_dir: Path):
    from skymirror.tools.daily_report.analysis import compute_temporal_stats
    from skymirror.tools.daily_report.loader import load_oa_log

    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    stats = compute_temporal_stats(records)

    assert stats["hourly_triggered"][8] == 1
    assert stats["hourly_triggered"][14] == 1
    assert stats["hourly_triggered"][16] == 1
    assert stats["peak_hour"] in {8, 14, 16}


def test_compute_system_profile_on_normal_day(fixtures_dir: Path):
    from skymirror.tools.daily_report.analysis import compute_system_profile_stats
    from skymirror.tools.daily_report.loader import load_oa_log

    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    profile = compute_system_profile_stats(records)

    assert profile["expert_activation_counts"]["order_expert"] == 2
    assert profile["expert_activation_counts"]["environment_expert"] == 2
    assert profile["fallback_count"] == 2
    assert abs(profile["avg_rag_relevance"] - (0.89 + 0.91 + 0.82) / 3) < 1e-6
    assert profile["top_citation_source"] in {
        "Road Traffic Act",
        "Emergency Response Protocol",
        "Drainage Operations Guide",
    }
    assert profile["status_counts"]["alerted"] == 3


def test_select_cases_prefers_diversity(fixtures_dir: Path):
    from skymirror.tools.daily_report.analysis import select_representative_cases
    from skymirror.tools.daily_report.loader import load_oa_log

    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    triggered = [record for record in records if record["status"] == "alerted"]
    cases = select_representative_cases(triggered, n=3)

    assert len(cases) == 3
    types = {case["alerts"][0]["sub_type"] for case in cases}
    assert {"red_light", "collision", "flooding"} <= types


def test_select_cases_single_type_returns_top_severity(fixtures_dir: Path):
    from skymirror.tools.daily_report.analysis import select_representative_cases
    from skymirror.tools.daily_report.loader import load_oa_log

    records = load_oa_log(
        fixtures_dir,
        date(2026, 4, 12),
        filename_stem_override="single_type_day",
    )
    triggered = [record for record in records if record["status"] == "alerted"]
    cases = select_representative_cases(triggered, n=3)

    assert len(cases) == 3
    severities = [case["alerts"][0]["severity"] for case in cases]
    assert severities == ["critical", "high", "medium"]


def test_get_llm_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    from skymirror.tools.llm_factory import get_llm

    with pytest.raises(ValueError):
        get_llm()


def test_narrate_uses_fallback_when_llm_fails():
    from skymirror.tools.llm_factory import narrate

    class _Broken:
        def invoke(self, *_a, **_kw):
            raise RuntimeError("API down")

    out = narrate("prompt", fallback="FALLBACK_TEXT", llm=_Broken())
    assert "FALLBACK_TEXT" in out


def test_render_overview_section():
    from skymirror.tools.daily_report.rendering import render_overview_section

    stats = {
        "total_decisions": 6,
        "total_triggered": 3,
        "total_alerts": 4,
        "trigger_rate": 0.5,
        "severity_counts": {"critical": 1, "high": 2, "medium": 1},
        "type_counts": {"red_light": 1, "collision": 1, "debris": 1, "flooding": 1},
        "dispatch_counts": {"Traffic Police": 1},
    }
    md = render_overview_section(stats)
    assert "## 1. Daily Overview" in md
    assert "50.0%" in md
    assert "Total alerts" in md


def test_render_case_section_uses_runrecord_fields(fixtures_dir: Path):
    from skymirror.tools.daily_report.loader import load_oa_log
    from skymirror.tools.daily_report.rendering import render_case

    records = load_oa_log(fixtures_dir, date(2026, 4, 12), filename_stem_override="normal_day")
    md = render_case(records[1], index=1)

    assert "Scene" in md
    assert "Routing Trace" in md
    assert "Expert Findings" in md
    assert "Alert & Dispatch" in md
    assert "collision" in md.lower()
    assert "Emergency Response Protocol" in md


def test_render_empty_day_report_contains_self_diagnostic():
    from skymirror.tools.daily_report.rendering import render_empty_day_report

    md = render_empty_day_report(date(2026, 4, 12), case_label="A")
    assert "NOT necessarily normal" in md
    assert "Verification checklist" in md


def test_render_system_profile_section_has_metrics():
    from skymirror.tools.daily_report.rendering import render_system_profile_section

    profile = {
        "expert_activation_counts": {"order_expert": 2},
        "fallback_count": 2,
        "fallback_rate": 2 / 6,
        "avg_rag_relevance": 0.875,
        "top_citation_source": "Road Traffic Act",
        "status_counts": {"alerted": 3, "clean": 1, "blocked": 1, "failed": 1},
    }
    md = render_system_profile_section(profile, narration="MOCK_NARRATION")
    assert "Run status distribution" in md
    assert "Road Traffic Act" in md
    assert "MOCK_NARRATION" in md


def test_build_tldr_prompt_embeds_facts():
    from skymirror.tools.daily_report.rendering import build_tldr_prompt

    prompt = build_tldr_prompt({"total_alerts": 4, "peak_hour": 14})
    assert "4" in prompt
    assert "Do NOT" in prompt


def test_generate_report_end_to_end_normal_day(tmp_path, fixtures_dir, mock_llm):
    from skymirror.agents.report_generator import generate_report

    oa_log_dir = tmp_path / "oa_log"
    oa_log_dir.mkdir()
    (oa_log_dir / "2026-04-12.jsonl").write_bytes(
        (fixtures_dir / "normal_day.jsonl").read_bytes()
    )

    report_path = generate_report(
        target_date=date(2026, 4, 12),
        oa_log_dir=oa_log_dir,
        output_dir=tmp_path / "reports",
    )

    text = report_path.read_text()
    assert "## 1. Daily Overview" in text
    assert "## 7. Appendix" in text
    assert "red light" in text.lower() or "collision" in text.lower()


def test_generate_report_empty_day_produces_self_diagnostic(tmp_path, mock_llm):
    from skymirror.agents.report_generator import generate_report

    oa_log_dir = tmp_path / "oa_log"
    oa_log_dir.mkdir()
    report_path = generate_report(
        target_date=date(2026, 4, 12),
        oa_log_dir=oa_log_dir,
        output_dir=tmp_path / "reports",
    )

    text = report_path.read_text()
    assert "NOT necessarily normal" in text
    assert "Verification checklist" in text


def test_generate_report_case_c_has_self_diagnostic_and_profile(
    tmp_path,
    fixtures_dir: Path,
    mock_llm,
):
    from skymirror.agents.report_generator import generate_report

    oa_log_dir = tmp_path / "oa_log"
    oa_log_dir.mkdir()
    (oa_log_dir / "2026-04-12.jsonl").write_text(
        (fixtures_dir / "no_trigger_day.jsonl").read_text()
    )

    report_path = generate_report(
        target_date=date(2026, 4, 12),
        oa_log_dir=oa_log_dir,
        output_dir=tmp_path / "reports",
    )

    text = report_path.read_text()
    assert "NOT necessarily normal" in text
    assert "System Behaviour Profile" in text


def test_generate_daily_report_legacy_wrapper_exists():
    from skymirror.agents.report_generator import generate_daily_report

    assert callable(generate_daily_report)
