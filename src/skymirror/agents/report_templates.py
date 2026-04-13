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
