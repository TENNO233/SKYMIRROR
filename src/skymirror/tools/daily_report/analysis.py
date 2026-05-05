"""Aggregate statistics and case selection based on RunRecord logs."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from skymirror.tools.daily_report.loader import SGT

_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _record_alerts(record: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = record.get("alerts")
    if not isinstance(alerts, list):
        return []
    return [dict(alert) for alert in alerts if isinstance(alert, dict)]


def _is_alerted(record: dict[str, Any]) -> bool:
    status = str(record.get("status", "")).strip().lower()
    return status == "alerted" and bool(_record_alerts(record))


def _primary_alert_type(alert: dict[str, Any]) -> str:
    sub_type = str(alert.get("sub_type", "")).strip()
    domain = str(alert.get("domain", "")).strip()
    if sub_type:
        return sub_type
    if domain:
        return domain
    return "unknown"


def compute_overview_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    alerted_runs = [record for record in records if _is_alerted(record)]
    alerts = [alert for record in alerted_runs for alert in _record_alerts(record)]
    severity_counts = Counter(str(alert.get("severity", "unknown")) for alert in alerts)
    type_counts = Counter(_primary_alert_type(alert) for alert in alerts)
    dispatch_counts = Counter(str(alert.get("department", "unknown")) for alert in alerts)

    total = len(records)
    triggered = len(alerted_runs)
    return {
        "total_decisions": total,
        "total_triggered": triggered,
        "total_alerts": len(alerts),
        "trigger_rate": (triggered / total) if total else 0.0,
        "severity_counts": dict(severity_counts),
        "type_counts": dict(type_counts),
        "dispatch_counts": dict(dispatch_counts),
    }


def compute_temporal_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    hourly_triggered: Counter[int] = Counter()
    hourly_total: Counter[int] = Counter()
    morning_types: Counter[str] = Counter()
    evening_types: Counter[str] = Counter()

    for record in records:
        ts = str(record.get("timestamp", "")).strip()
        if not ts:
            continue
        try:
            dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=UTC)
        dt_sgt = dt_utc.astimezone(SGT)
        hour = dt_sgt.hour
        hourly_total[hour] += 1
        if _is_alerted(record):
            hourly_triggered[hour] += 1
            for alert in _record_alerts(record):
                alert_type = _primary_alert_type(alert)
                if 7 <= hour <= 9:
                    morning_types[alert_type] += 1
                elif 17 <= hour <= 20:
                    evening_types[alert_type] += 1

    peak_hour = max(hourly_triggered, key=hourly_triggered.get) if hourly_triggered else None

    def _top(counter: Counter[str]) -> str | None:
        return counter.most_common(1)[0][0] if counter else None

    return {
        "hourly_triggered": dict(hourly_triggered),
        "hourly_total": dict(hourly_total),
        "peak_hour": peak_hour,
        "morning_dominant_type": _top(morning_types),
        "evening_dominant_type": _top(evening_types),
    }


def compute_system_profile_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    activation_counts: Counter[str] = Counter()
    fallback_count = 0
    rag_scores: list[float] = []
    citation_sources: Counter[str] = Counter()
    alert_status_counts: Counter[str] = Counter()

    for record in records:
        experts = record.get("active_experts")
        if isinstance(experts, list) and experts:
            for expert in experts:
                activation_counts[str(expert)] += 1
        else:
            fallback_count += 1

        expert_results = record.get("expert_results")
        if isinstance(expert_results, dict):
            for result in expert_results.values():
                if not isinstance(result, dict):
                    continue
                citations = result.get("citations")
                if not isinstance(citations, list):
                    continue
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    source = str(citation.get("title") or citation.get("source_path") or "unknown")
                    citation_sources[source] += 1
                    try:
                        rag_scores.append(float(citation.get("relevance_score", 0.0)))
                    except (TypeError, ValueError):
                        pass

        alert_status_counts[str(record.get("status", "unknown"))] += 1

    total = len(records)
    return {
        "expert_activation_counts": dict(activation_counts),
        "fallback_count": fallback_count,
        "fallback_rate": (fallback_count / total) if total else 0.0,
        "avg_rag_relevance": (sum(rag_scores) / len(rag_scores)) if rag_scores else 0.0,
        "top_citation_source": citation_sources.most_common(1)[0][0] if citation_sources else None,
        "status_counts": dict(alert_status_counts),
    }


def _record_severity_rank(record: dict[str, Any]) -> int:
    alerts = _record_alerts(record)
    if not alerts:
        return 0
    return max(_SEVERITY_ORDER.get(str(alert.get("severity", "low")), 0) for alert in alerts)


def select_representative_cases(
    triggered: list[dict[str, Any]], n: int = 3
) -> list[dict[str, Any]]:
    if not triggered:
        return []

    sorted_pool = sorted(
        triggered,
        key=lambda record: (_record_severity_rank(record), len(_record_alerts(record))),
        reverse=True,
    )[:10]

    picked: list[dict[str, Any]] = []
    seen_types: set[str] = set()

    for record in sorted_pool:
        if len(picked) >= n:
            break
        alert_types = {_primary_alert_type(alert) for alert in _record_alerts(record)}
        if not alert_types or alert_types.isdisjoint(seen_types):
            picked.append(record)
            seen_types.update(alert_types)

    if len(picked) < n:
        picked_ids = {id(record) for record in picked}
        remaining = [record for record in sorted_pool if id(record) not in picked_ids]
        picked.extend(remaining[: n - len(picked)])

    return picked
