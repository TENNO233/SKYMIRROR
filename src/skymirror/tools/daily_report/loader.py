"""Loader utilities for the Daily Explication Report Agent.

Responsible for:
- Reading the OA decision log file for a given SGT date.
- Determining "yesterday (SGT)" for default-date behaviour.

Used by: `skymirror.agents.report_generator`.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SGT = timezone(timedelta(hours=8))


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


def yesterday_sgt() -> date:
    """Return the SGT date one day before the current SGT day.

    Uses Singapore Time (UTC+8). At 07:59 UTC on 2026-04-13 (= 15:59 SGT on
    2026-04-13), returns 2026-04-12.
    """
    now_sgt = datetime.now(SGT)
    return (now_sgt - timedelta(days=1)).date()
