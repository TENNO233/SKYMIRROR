"""Pure-function helpers for Daily Explication Report.

This module contains ONLY pure functions — no I/O side effects beyond
reading files and no global state. This makes the agent trivially unit-testable.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SGT = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_oa_log(
    oa_log_dir: Path,
    target_date: date,
    *,
    filename_stem_override: str | None = None,
) -> list[dict[str, Any]]:
    """Load all OA decision records for `target_date` (SGT day).

    Args:
        oa_log_dir: Directory holding `YYYY-MM-DD.jsonl` files.
        target_date: The SGT date whose log should be loaded.
        filename_stem_override: For tests — use a different filename
            (without `.jsonl`) instead of the date-derived one.

    Returns:
        List of parsed decision records. Empty list if the file is
        missing or empty. Malformed JSON lines are skipped with a warning.
    """
    oa_log_dir = Path(oa_log_dir)
    stem = filename_stem_override or target_date.isoformat()
    path = oa_log_dir / f"{stem}.jsonl"

    if not path.exists():
        logger.warning("OA log file not found: %s", path)
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Skipping malformed line %d in %s: %s", lineno, path, exc
                )
    return records


# ---------------------------------------------------------------------------
# Date / timezone helpers
# ---------------------------------------------------------------------------

def yesterday_sgt() -> date:
    """Return the SGT date one day before the current SGT day.

    Uses Singapore Time (UTC+8). At 07:59 UTC on 2026-04-13 (= 15:59 SGT on
    2026-04-13), returns 2026-04-12.
    """
    now_sgt = datetime.now(SGT)
    return (now_sgt - timedelta(days=1)).date()


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_overview_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute top-level counts used in Section 1 (Daily Overview).

    Returns a dict with:
        total_decisions, total_triggered, trigger_rate,
        severity_counts, type_counts, dispatch_counts
    """
    triggered = [r for r in records if r.get("is_emergency") and r.get("alert")]
    severity = Counter(r["alert"]["severity"] for r in triggered)
    etype = Counter(r["alert"]["emergency_type"] for r in triggered)
    dispatch = Counter(
        dept
        for r in triggered
        for dept in r["alert"].get("dispatched_to", [])
    )
    total = len(records)
    return {
        "total_decisions": total,
        "total_triggered": len(triggered),
        "trigger_rate": (len(triggered) / total) if total else 0.0,
        "severity_counts": dict(severity),
        "type_counts": dict(etype),
        "dispatch_counts": dict(dispatch),
    }


def compute_temporal_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute time-of-day distributions used in Section 3 (Temporal Pattern).

    All times are converted to SGT before bucketing into hours.

    Returns a dict with:
        hourly_triggered:  dict[int, int] — SGT hour (0-23) -> triggered count
        hourly_total:      dict[int, int] — SGT hour -> all-decisions count
        peak_hour:         int | None    — SGT hour with the most triggers (None if no triggers)
        morning_dominant_type:  str | None  — most common emergency_type during 07-09 SGT, if any
        evening_dominant_type:  str | None  — most common emergency_type during 17-20 SGT, if any
    """
    hourly_triggered: Counter[int] = Counter()
    hourly_total: Counter[int] = Counter()
    morning_types: Counter[str] = Counter()
    evening_types: Counter[str] = Counter()

    for r in records:
        ts = r.get("timestamp")
        if not ts:
            continue
        try:
            dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        dt_sgt = dt_utc.astimezone(SGT)
        hour = dt_sgt.hour
        hourly_total[hour] += 1
        if r.get("is_emergency") and r.get("alert"):
            hourly_triggered[hour] += 1
            etype = r["alert"].get("emergency_type", "unknown")
            if 7 <= hour <= 9:
                morning_types[etype] += 1
            elif 17 <= hour <= 20:
                evening_types[etype] += 1

    peak_hour = max(hourly_triggered, key=hourly_triggered.get) if hourly_triggered else None

    def _top(c: Counter[str]) -> str | None:
        return c.most_common(1)[0][0] if c else None

    return {
        "hourly_triggered": dict(hourly_triggered),
        "hourly_total": dict(hourly_total),
        "peak_hour": peak_hour,
        "morning_dominant_type": _top(morning_types),
        "evening_dominant_type": _top(evening_types),
    }


def compute_system_profile_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute XAI self-reflection stats used in Section 5 (System Profile).

    Returns a dict with:
        expert_activation_counts: dict[str, int] across ALL records
        fallback_count, fallback_rate: number and fraction of records with
            empty activated_experts
        avg_rag_relevance: float across every citation in every record
        top_regulation_code: str | None — most frequently cited code
        oa_confidence_buckets: three-bucket histogram of triggered oa_confidence
    """
    activation_counts: Counter[str] = Counter()
    fallback_count = 0
    rag_scores: list[float] = []
    reg_codes: Counter[str] = Counter()
    buckets = {"high_\u22650.9": 0, "mid_0.7\u20130.89": 0, "low_<0.7": 0}

    for r in records:
        experts = (r.get("routing_trace") or {}).get("activated_experts") or []
        if experts:
            for e in experts:
                activation_counts[e] += 1
        else:
            fallback_count += 1
        for cite in (r.get("rag_citations") or []):
            try:
                rag_scores.append(float(cite.get("relevance_score", 0.0)))
            except (TypeError, ValueError):
                pass
            code = cite.get("regulation_code")
            if code:
                reg_codes[code] += 1

        if r.get("is_emergency"):
            conf = float(r.get("oa_confidence", 0.0))
            if conf >= 0.9:
                buckets["high_\u22650.9"] += 1
            elif conf >= 0.7:
                buckets["mid_0.7\u20130.89"] += 1
            else:
                buckets["low_<0.7"] += 1

    total = len(records)
    return {
        "expert_activation_counts": dict(activation_counts),
        "fallback_count": fallback_count,
        "fallback_rate": (fallback_count / total) if total else 0.0,
        "avg_rag_relevance": (sum(rag_scores) / len(rag_scores)) if rag_scores else 0.0,
        "top_regulation_code": reg_codes.most_common(1)[0][0] if reg_codes else None,
        "oa_confidence_buckets": buckets,
    }
