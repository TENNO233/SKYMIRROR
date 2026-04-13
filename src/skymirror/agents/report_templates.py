"""Markdown renderers and LLM prompt builders for the Daily Report.

All facts must be pre-computed by `report_helpers`; these functions only
lay out the result. Keeping this file pure-template makes visual changes
(heading levels, emoji, wording) easy to diff without touching logic.
"""
from __future__ import annotations

from typing import Any


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_counts_inline(d: dict[str, int]) -> str:
    if not d:
        return "_(none)_"
    return " · ".join(f"{k} ({v})" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------------------
# Section 1 — Daily Overview
# ---------------------------------------------------------------------------

def render_overview_section(stats: dict[str, Any]) -> str:
    lines = [
        "## 1. Daily Overview",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Frames evaluated / Alerts triggered / Trigger rate | "
        f"{stats['total_decisions']} / {stats['total_triggered']} / "
        f"{_fmt_pct(stats['trigger_rate'])} |",
        f"| Severity breakdown | {_fmt_counts_inline(stats['severity_counts'])} |",
        f"| Emergency types | {_fmt_counts_inline(stats['type_counts'])} |",
        f"| Dispatch targets | {_fmt_counts_inline(stats['dispatch_counts'])} |",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 4 — Case Explication (3 layers)
# ---------------------------------------------------------------------------

def render_case(case: dict[str, Any], index: int) -> str:
    ts = case.get("timestamp", "unknown")
    alert = case.get("alert") or {}
    sev = (alert.get("severity") or "unknown").upper()
    etype = alert.get("emergency_type", "unknown")
    vlm = case.get("vlm_output_excerpt", "(no VLM excerpt)")

    # Collect expert finding summaries + citation block
    ef_lines: list[str] = []
    for expert_name, payload in (case.get("expert_findings") or {}).items():
        for finding in payload.get("findings", []):
            desc = finding.get("description", "(no description)")
            conf = finding.get("confidence", "n/a")
            ef_lines.append(f"- **{expert_name}**: {desc} (conf {conf})")
    if not ef_lines:
        ef_lines.append("- _(no expert findings recorded)_")

    rag_lines: list[str] = []
    for cite in (case.get("rag_citations") or []):
        src = cite.get("source", "unknown source")
        code = cite.get("regulation_code", "n/a")
        excerpt = cite.get("excerpt", "")
        rel = cite.get("relevance_score", "n/a")
        rag_lines.append(
            f"> **{src} — {code}** (relevance {rel})\n> \"{excerpt}\""
        )
    if not rag_lines:
        rag_lines.append("> _(no RAG citations recorded)_")

    oa_reasoning = case.get("oa_reasoning", "(no reasoning recorded)")
    oa_conf = case.get("oa_confidence", "n/a")
    dispatched = ", ".join(alert.get("dispatched_to", [])) or "_(none)_"
    status = alert.get("dispatch_status", "n/a")

    return "\n".join([
        f"### Case {index} — {ts}, {etype} [{sev}]",
        "",
        f"**📸 Scene** (VLM)",
        f"> {vlm}",
        "",
        f"**📚 Expert Finding & Legal Citation** (Expert + RAG)",
        *ef_lines,
        "",
        *rag_lines,
        "",
        f"**⚖️ OA Decision & Dispatch**",
        f"OA confidence {oa_conf}: {oa_reasoning}",
        f"Dispatched to: **{dispatched}** (status: {status})",
        "",
    ])


# ---------------------------------------------------------------------------
# Section 3 — Temporal Pattern (narration only; facts passed in)
# ---------------------------------------------------------------------------

def render_temporal_section(stats: dict[str, Any], narration: str) -> str:
    peak = stats.get("peak_hour")
    morn = stats.get("morning_dominant_type") or "n/a"
    eve = stats.get("evening_dominant_type") or "n/a"
    facts_line = (
        f"_Peak hour (SGT): {peak if peak is not None else 'n/a'} · "
        f"Morning dominant type: {morn} · Evening dominant type: {eve}_"
    )
    return "\n".join([
        "## 3. Temporal Pattern Analysis",
        "",
        facts_line,
        "",
        narration,
        "",
    ])


# ---------------------------------------------------------------------------
# Section 5 — System Behaviour Profile
# ---------------------------------------------------------------------------

def render_system_profile_section(profile: dict[str, Any], narration: str) -> str:
    experts = _fmt_counts_inline(profile["expert_activation_counts"])
    buckets = _fmt_counts_inline(profile["oa_confidence_buckets"])
    return "\n".join([
        "## 5. System Behaviour Profile",
        "",
        f"- **Expert activations**: {experts}",
        f"- **Routing fallback**: {profile['fallback_count']} frames "
        f"({_fmt_pct(profile['fallback_rate'])})",
        f"- **Average RAG relevance**: {profile['avg_rag_relevance']:.3f}",
        f"- **Top cited regulation**: {profile.get('top_regulation_code') or 'n/a'}",
        f"- **OA confidence distribution (triggered alerts)**: {buckets}",
        "",
        narration,
        "",
    ])


# ---------------------------------------------------------------------------
# Section 7 — Appendix
# ---------------------------------------------------------------------------

def render_appendix_section(
    triggered: list[dict[str, Any]],
    featured_ids: set[str],
    jsonl_path: str,
) -> str:
    other = [t for t in triggered if t.get("decision_id") not in featured_ids]
    by_type: dict[str, int] = {}
    for t in other:
        et = (t.get("alert") or {}).get("emergency_type", "unknown")
        by_type[et] = by_type.get(et, 0) + 1
    summary = _fmt_counts_inline(by_type) if by_type else "_(none)_"
    return "\n".join([
        "## 7. Appendix",
        "",
        f"**Other alerts**: {len(other)} records ({summary}).",
        f"Full list available in: `{jsonl_path}` (filter `is_emergency = true`).",
        "",
    ])


# ---------------------------------------------------------------------------
# Empty-Day Self-Diagnostic Report
# ---------------------------------------------------------------------------

def render_empty_day_report(target_date, case_label: str) -> str:
    """Render the self-diagnostic report for an empty day.

    `case_label` is "A", "B", or "C" per Section 5.1 of the spec — used to
    tune the diagnostic framing.
    """
    case_intro = {
        "A": "OA log file is missing entirely — OA may not have run today.",
        "B": "OA log file exists but contains no records — OA started but "
             "processed no frames.",
        "C": "OA evaluated frames all day but triggered no alerts — this may "
             "indicate stale keyword vocabulary, overly strict thresholds, or "
             "a genuinely incident-free day.",
    }.get(case_label, "Unknown empty-day case.")

    return "\n".join([
        f"# SKYMIRROR Daily Report — {target_date.isoformat()}",
        "",
        "## ⚠️ No alerts detected today — this is NOT necessarily normal.",
        "",
        f"**Diagnostic framing**: {case_intro}",
        "",
        "**Possible causes (ranked by likelihood):**",
        "1. Camera offline or image stream interrupted",
        "2. Silent failure in VLM or Validator stage (no exceptions but empty output)",
        "3. Routing fallback rate unusually high (keyword vocabulary may be stale)",
        "4. Expert RAG retrieval failures",
        "5. (Rare) Genuinely incident-free monitoring period",
        "",
        "**Verification checklist:**",
        "- [ ] Check `data/frames/` for today's new frames (~4,300 expected at 20s intervals)",
        "- [ ] Review pipeline logs for ERROR/WARNING",
        "- [ ] Verify cam4798 is not under maintenance",
        "- [ ] Compare total-decision count against 7-day baseline",
        "- [ ] Confirm OA process was running throughout the day",
        "",
    ])


# ---------------------------------------------------------------------------
# LLM prompt builders (Hybrid principle — facts-only)
# ---------------------------------------------------------------------------

_NO_HALLUCINATION_GUARD = (
    "Do NOT introduce any statistic, number, or claim that is not present "
    "in the facts dict above. If a field is missing or null, omit it rather "
    "than inventing a value."
)


def build_tldr_prompt(facts: dict[str, Any]) -> str:
    return (
        "You are drafting the Executive Summary (TL;DR) of a daily traffic "
        "monitoring report. Write 3-5 English sentences for an operations "
        "audience. Summarise today's activity based ONLY on the following "
        "pre-computed facts.\n\n"
        f"Facts:\n{facts}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )


def build_temporal_prompt(facts: dict[str, Any]) -> str:
    return (
        "Write a 2-3 sentence analysis of today's temporal alert distribution "
        "in English. Mention the peak hour and the morning/evening dominant "
        "types if present.\n\n"
        f"Facts:\n{facts}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )


def build_system_profile_prompt(facts: dict[str, Any]) -> str:
    return (
        "Write 3-4 English sentences interpreting today's system behaviour "
        "metrics (expert activation balance, RAG citation quality, routing "
        "fallback rate, OA confidence distribution). Keep the tone technical "
        "and self-reflective.\n\n"
        f"Facts:\n{facts}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )


def build_recommendations_prompt(overview: dict[str, Any], profile: dict[str, Any]) -> str:
    return (
        "Based on the following daily facts, write 3-5 concise, actionable "
        "recommendations in English as a bulleted list. Split between "
        "operational (field-level) and system (maintainer-level) advice.\n\n"
        f"Overview:\n{overview}\n\nProfile:\n{profile}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )
