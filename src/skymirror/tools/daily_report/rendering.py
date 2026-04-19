"""Markdown renderers and prompt builders for RunRecord-based daily reports."""

from __future__ import annotations

from typing import Any


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_counts_inline(d: dict[str, int]) -> str:
    if not d:
        return "_(none)_"
    return " · ".join(f"{k} ({v})" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))


def render_overview_section(stats: dict[str, Any]) -> str:
    lines = [
        "## 1. Daily Overview",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Frames evaluated / Alerted runs / Total alerts / Trigger rate | "
        f"{stats['total_decisions']} / {stats['total_triggered']} / {stats['total_alerts']} / "
        f"{_fmt_pct(stats['trigger_rate'])} |",
        f"| Severity breakdown | {_fmt_counts_inline(stats['severity_counts'])} |",
        f"| Alert types | {_fmt_counts_inline(stats['type_counts'])} |",
        f"| Dispatch targets | {_fmt_counts_inline(stats['dispatch_counts'])} |",
        "",
    ]
    return "\n".join(lines)


def render_case(case: dict[str, Any], index: int) -> str:
    ts = case.get("timestamp", "unknown")
    alerts = case.get("alerts") or []
    primary_alert = alerts[0] if alerts else {}
    sev = str(primary_alert.get("severity", "unknown")).upper()
    alert_type = primary_alert.get("sub_type") or primary_alert.get("domain") or "unknown"
    scene = case.get("validated_text", "(no validated scene summary)")

    active_experts = case.get("active_experts") or []
    ex_str = ", ".join(str(expert) for expert in active_experts) if active_experts else "_(no expert activation)_"

    expert_lines: list[str] = []
    citation_lines: list[str] = []
    expert_results = case.get("expert_results") or {}
    for expert_name, payload in expert_results.items():
        if not isinstance(payload, dict):
            continue
        for scenario in payload.get("scenarios", []):
            if not isinstance(scenario, dict):
                continue
            expert_lines.append(
                f"- **{expert_name}**: {scenario.get('reason', '(no reason)')} "
                f"[{scenario.get('severity', 'unknown')}/{scenario.get('confidence', 'unknown')}]"
            )
        for citation in payload.get("citations", []):
            if not isinstance(citation, dict):
                continue
            title = citation.get("title") or citation.get("source_path") or "unknown source"
            score = citation.get("relevance_score", 0.0)
            citation_lines.append(f"> **{title}** (relevance {score})")

    if not expert_lines:
        expert_lines.append("- _(no expert scenarios recorded)_")
    if not citation_lines:
        citation_lines.append("> _(no citations recorded)_")

    departments = ", ".join(
        str(alert.get("department", "unknown")) for alert in alerts if isinstance(alert, dict)
    ) or "_(none)_"
    alert_messages = " | ".join(
        str(alert.get("message", "")).strip() for alert in alerts if isinstance(alert, dict)
    ) or "(no alert message)"

    return "\n".join([
        f"### Case {index} — {ts}, {alert_type} [{sev}]",
        "",
        "**Scene**",
        f"> {scene}",
        "",
        "**Routing Trace**",
        f"Activated experts: {ex_str}",
        "",
        "**Expert Findings & Citations**",
        *expert_lines,
        "",
        *citation_lines,
        "",
        "**Alert & Dispatch**",
        f"Run status: `{case.get('status', 'unknown')}`",
        f"Messages: {alert_messages}",
        f"Dispatched to: **{departments}**",
        "",
    ])


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


def render_system_profile_section(profile: dict[str, Any], narration: str) -> str:
    experts = _fmt_counts_inline(profile["expert_activation_counts"])
    status_counts = _fmt_counts_inline(profile["status_counts"])
    return "\n".join([
        "## 5. System Behaviour Profile",
        "",
        f"- **Expert activations**: {experts}",
        f"- **Routing fallback**: {profile['fallback_count']} frames "
        f"({_fmt_pct(profile['fallback_rate'])})",
        f"- **Average citation relevance**: {profile['avg_rag_relevance']:.3f}",
        f"- **Top cited source**: {profile.get('top_citation_source') or 'n/a'}",
        f"- **Run status distribution**: {status_counts}",
        "",
        narration,
        "",
    ])


def render_appendix_section(
    triggered: list[dict[str, Any]],
    featured_ids: set[str],
    jsonl_path: str,
) -> str:
    other = [record for record in triggered if record.get("run_id") not in featured_ids]
    by_type: dict[str, int] = {}
    for record in other:
        for alert in record.get("alerts", []):
            if not isinstance(alert, dict):
                continue
            alert_type = str(alert.get("sub_type") or alert.get("domain") or "unknown")
            by_type[alert_type] = by_type.get(alert_type, 0) + 1
    summary = _fmt_counts_inline(by_type) if by_type else "_(none)_"
    return "\n".join([
        "## 7. Appendix",
        "",
        f"**Other alerts**: {len(other)} runs ({summary}).",
        f"Full list available in: `{jsonl_path}`.",
        "",
    ])


def render_empty_day_report(target_date, case_label: str) -> str:
    case_intro = {
        "A": "RunRecord log file is missing entirely — the runtime may not have executed.",
        "B": "RunRecord log file exists but contains no records — the runtime started but processed nothing.",
        "C": "RunRecord log contains records but no alerted runs — this may indicate conservative routing, stale rules, or a genuinely quiet day.",
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
        "2. Silent failure in VLM or Validator stage",
        "3. Overly conservative routing or stale rule vocabulary",
        "4. RAG retrieval or external corroboration unavailable",
        "5. Genuinely incident-free monitoring period",
        "",
        "**Verification checklist:**",
        "- [ ] Check `data/frames/` for expected fresh frames",
        "- [ ] Review runtime logs for `failed` or `blocked` spikes",
        "- [ ] Verify `data/oa_log/` is being written continuously",
        "- [ ] Confirm camera feed and OpenAI/Pinecone/LTA dependencies are healthy",
        "",
    ])


_NO_HALLUCINATION_GUARD = (
    "Do NOT introduce any statistic, number, or claim that is not present "
    "in the facts above. If a field is missing, omit it rather than inventing a value."
)


def build_tldr_prompt(facts: dict[str, Any]) -> str:
    return (
        "Write a 3-5 sentence executive summary for a traffic monitoring report. "
        "Use only the provided RunRecord-derived facts.\n\n"
        f"Facts:\n{facts}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )


def build_temporal_prompt(facts: dict[str, Any]) -> str:
    return (
        "Write a 2-3 sentence analysis of the temporal alert distribution. "
        "Mention the peak hour and morning/evening dominant types when available.\n\n"
        f"Facts:\n{facts}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )


def build_system_profile_prompt(facts: dict[str, Any]) -> str:
    return (
        "Write 3-4 technical sentences about system behaviour based on expert activation, "
        "fallback rate, citation relevance, and run status distribution.\n\n"
        f"Facts:\n{facts}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )


def build_recommendations_prompt(overview: dict[str, Any], profile: dict[str, Any]) -> str:
    return (
        "Based on the overview and system profile below, write 3-5 concise operational "
        "and maintainer recommendations as a bullet list.\n\n"
        f"Overview:\n{overview}\n\nProfile:\n{profile}\n\n"
        f"{_NO_HALLUCINATION_GUARD}"
    )
