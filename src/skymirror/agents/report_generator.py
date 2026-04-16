"""
Daily Explication Report Agent
==============================

Identity
--------
I am SKYMIRROR's human-facing output surface. I turn a day's worth of
Orchestrator Agent (OA) decisions into a readable English Markdown report
grounded in XAI principles (process transparency + source attribution).

I am NOT a per-frame LangGraph node. I am invoked once per day by OA
(at a scheduled time), or manually via CLI for testing and demos.

Tasks
-----
1. Load all OA decision records for the target SGT day from
   `data/oa_log/YYYY-MM-DD.jsonl`.
2. Compute aggregate statistics (overview totals, temporal patterns,
   system-behaviour profile).
3. Select 3 representative cases via Top-Severity + Diversity Dedup.
4. Render 7 Markdown sections. Four narrative sections go through an LLM
   (Hybrid principle: template computes facts, LLM only narrates prose).
5. Handle empty-day scenarios with a self-diagnostic report that resists
   the "all systems nominal" false positive.
6. Write the final Markdown to `data/reports/YYYY-MM-DD.md`.

Tools
-----
- `skymirror.tools.daily_report.loader`     : load_oa_log, yesterday_sgt
- `skymirror.tools.daily_report.analysis`   : stats + case selection
- `skymirror.tools.daily_report.rendering`  : Markdown templates + LLM prompts
- `skymirror.tools.llm_factory`             : LLM provider + narrate() with fallback

Entry points
------------
- `generate_report(target_date, oa_log_dir, output_dir) -> Path`
    Primary entry. OA or CLI calls this.
- `generate_daily_report()` : zero-arg legacy wrapper for `main.py`'s
    existing APScheduler integration. DO NOT rename; upstream imports it.
- `python -m skymirror.agents.report_generator [--date ...]`
    CLI for demos and manual runs.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

from langsmith import traceable

from skymirror.tools.llm_factory import narrate
from skymirror.tools.daily_report.loader import load_oa_log, yesterday_sgt
from skymirror.tools.daily_report.analysis import (
    compute_overview_stats,
    compute_system_profile_stats,
    compute_temporal_stats,
    select_representative_cases,
)
from skymirror.tools.daily_report.rendering import (
    build_recommendations_prompt,
    build_system_profile_prompt,
    build_temporal_prompt,
    build_tldr_prompt,
    render_appendix_section,
    render_case,
    render_empty_day_report,
    render_overview_section,
    render_system_profile_section,
    render_temporal_section,
)
from skymirror.tools.langsmith_utils import flush_langsmith_traces

logger = logging.getLogger(__name__)


def _trace_generate_report_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    target_date = inputs.get("target_date")
    return {
        "target_date": target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date),
        "oa_log_dir": str(inputs.get("oa_log_dir", "")),
        "output_dir": str(inputs.get("output_dir", "")),
    }


def _trace_generate_report_output(output: Path) -> dict[str, str]:
    return {"report_path": str(output)}


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------

@traceable(
    name="generate_report",
    run_type="chain",
    process_inputs=_trace_generate_report_inputs,
    process_outputs=_trace_generate_report_output,
)
def generate_report(
    target_date: date,
    oa_log_dir: Path | str,
    output_dir: Path | str,
) -> Path:
    """Generate the Daily Explication Report for `target_date` (SGT).

    Returns the absolute path of the written Markdown file.
    """
    oa_log_dir = Path(oa_log_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_oa_log(oa_log_dir, target_date)
    triggered = [r for r in records if r.get("is_emergency") and r.get("alert")]

    if not records:
        # Case A or B: no log file or empty log file.
        stem = (oa_log_dir / f"{target_date.isoformat()}.jsonl")
        label = "A" if not stem.exists() else "B"
        md = render_empty_day_report(target_date, case_label=label)
    elif not triggered:
        # Case C: records exist but no triggers. Still render a self-diagnostic
        # up top, but optionally append the system profile so maintainers can
        # see what OA *did* see.
        md_parts = [render_empty_day_report(target_date, case_label="C")]
        profile = compute_system_profile_stats(records)
        md_parts.append(render_system_profile_section(profile, narration=""))
        md = "\n".join(md_parts)
    else:
        md = _render_full_report(target_date, records, triggered)

    out_path = output_dir / f"{target_date.isoformat()}.md"
    out_path.write_text(md, encoding="utf-8")
    logger.info("Report written to %s", out_path)
    return out_path


def _render_full_report(
    target_date: date,
    records: list[dict[str, Any]],
    triggered: list[dict[str, Any]],
) -> str:
    overview = compute_overview_stats(records)
    temporal = compute_temporal_stats(records)
    profile = compute_system_profile_stats(records)

    # Hybrid narration (template-computed facts → LLM prose).
    tldr_fallback = (
        f"Today {overview['total_triggered']} alerts were triggered out of "
        f"{overview['total_decisions']} OA evaluations "
        f"({overview['trigger_rate'] * 100:.1f}% trigger rate)."
    )
    tldr = narrate(build_tldr_prompt(overview), fallback=tldr_fallback)
    temporal_narration = narrate(
        build_temporal_prompt(temporal),
        fallback="Temporal narration unavailable.",
    )
    profile_narration = narrate(
        build_system_profile_prompt(profile),
        fallback="System profile narration unavailable.",
    )
    recs_narration = narrate(
        build_recommendations_prompt(overview, profile),
        fallback="- Review any high-severity alerts manually.",
    )

    cases = select_representative_cases(triggered, n=3)
    # Use .get() — some records may lack decision_id; filter out None to keep set consistent
    featured_ids = {c.get("decision_id") for c in cases if c.get("decision_id")}
    case_md = "\n".join(render_case(c, index=i + 1) for i, c in enumerate(cases))

    jsonl_rel = f"data/oa_log/{target_date.isoformat()}.jsonl"

    return "\n".join([
        f"# SKYMIRROR Daily Report — {target_date.isoformat()}",
        "",
        render_overview_section(overview),
        "## 2. Executive Summary",
        "",
        tldr,
        "",
        render_temporal_section(temporal, narration=temporal_narration),
        "## 4. Representative Case Explications",
        "",
        case_md,
        render_system_profile_section(profile, narration=profile_narration),
        "## 6. Recommendations",
        "",
        recs_narration,
        "",
        render_appendix_section(triggered, featured_ids, jsonl_path=jsonl_rel),
    ])


# ---------------------------------------------------------------------------
# Legacy wrapper — preserves main.py's existing APScheduler import
# ---------------------------------------------------------------------------

def generate_daily_report(
    oa_log_dir: Path | str = "data/oa_log",
    output_dir: Path | str = "data/reports",
) -> Path:
    """Zero/low-arg wrapper: generate report for yesterday (SGT)."""
    return generate_report(
        target_date=yesterday_sgt(),
        oa_log_dir=oa_log_dir,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="skymirror.agents.report_generator",
        description="Generate the SKYMIRROR Daily Explication Report.",
    )
    parser.add_argument(
        "--date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Target SGT date YYYY-MM-DD (default: yesterday SGT).",
    )
    parser.add_argument("--oa-log-dir", type=Path, default=Path("data/oa_log"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        args = _parse_args(argv)
        target = args.date or yesterday_sgt()
        path = generate_report(
            target_date=target,
            oa_log_dir=args.oa_log_dir,
            output_dir=args.output_dir,
        )
        print(str(path))
        return 0
    finally:
        flush_langsmith_traces()


if __name__ == "__main__":
    sys.exit(main())
