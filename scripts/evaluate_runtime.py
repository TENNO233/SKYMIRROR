"""Offline evaluation for RunRecord contracts and runtime governance."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from skymirror.agents.report_generator import generate_report  # noqa: E402
from skymirror.tools.daily_report.loader import load_oa_log  # noqa: E402
from skymirror.tools.governance import load_release_thresholds  # noqa: E402
from skymirror.tools.run_records import validate_run_record  # noqa: E402


def _raw_line_counts(path: Path) -> tuple[int, int]:
    total = 0
    valid = 0
    if not path.is_file():
        return total, valid
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        total += 1
        try:
            record = json.loads(line)
            validate_run_record(record)
            valid += 1
        except Exception:
            continue
    return total, valid


def _all_records(fixtures_dir: Path, stems: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for stem in stems:
        records.extend(
            load_oa_log(
                fixtures_dir,
                target_date=date(2026, 4, 12),
                filename_stem_override=stem,
            )
        )
    return records


def _alerted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if str(record.get("status", "")).strip().lower() == "alerted"
        and isinstance(record.get("alerts"), list)
        and bool(record.get("alerts"))
    ]


def evaluate_runtime(fixtures_dir: Path) -> dict[str, Any]:
    thresholds = load_release_thresholds()
    stems = ["normal_day", "no_trigger_day", "single_type_day"]

    total_lines = 0
    valid_lines = 0
    for stem in stems:
        count_total, count_valid = _raw_line_counts(fixtures_dir / f"{stem}.jsonl")
        total_lines += count_total
        valid_lines += count_valid
    malformed_total, malformed_valid = _raw_line_counts(fixtures_dir / "malformed_day.jsonl")

    records = _all_records(fixtures_dir, ["normal_day", "no_trigger_day", "single_type_day"])
    alerted = _alerted_records(records)

    blocked = [record for record in records if record.get("status") == "blocked"]
    blocked_failures = sum(
        1
        for record in blocked
        if record.get("alerts") or record.get("guardrail_result", {}).get("allowed") is not False
    )
    guardrail_regression_rate = (blocked_failures / len(blocked)) if blocked else 0.0

    validator_candidates = [
        record for record in records if record.get("status") in {"clean", "alerted"}
    ]
    validator_failures = sum(
        1 for record in validator_candidates if not str(record.get("validated_text", "")).strip()
    )
    validator_regression_rate = (
        validator_failures / len(validator_candidates) if validator_candidates else 0.0
    )

    routing_failures = sum(
        1
        for record in alerted
        if not record.get("active_experts") or not record.get("expert_results")
    )
    expert_routing_regression_rate = (routing_failures / len(alerted)) if alerted else 0.0

    total_alerts = 0
    evidence_complete = 0
    for record in alerted:
        for alert in record.get("alerts", []):
            if not isinstance(alert, dict):
                continue
            total_alerts += 1
            if alert.get("evidence") is not None and alert.get("regulations") is not None:
                evidence_complete += 1
    alert_evidence_completeness_rate = evidence_complete / total_alerts if total_alerts else 1.0

    with tempfile.TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        report_success = 0
        for stem in ("normal_day", "no_trigger_day"):
            oa_log_dir = tmp_root / stem / "oa_log"
            oa_log_dir.mkdir(parents=True, exist_ok=True)
            date_str = "2026-04-12"
            (oa_log_dir / f"{date_str}.jsonl").write_text(
                (fixtures_dir / f"{stem}.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            try:
                report_path = generate_report(
                    target_date=date.fromisoformat(date_str),
                    oa_log_dir=oa_log_dir,
                    output_dir=tmp_root / stem / "reports",
                )
                if report_path.is_file():
                    report_success += 1
            except Exception:
                continue
    report_generation_success_rate = report_success / 2

    schema_valid_rate = (valid_lines / total_lines) if total_lines else 1.0
    metrics = {
        "schema_valid_rate": round(schema_valid_rate, 3),
        "guardrail_regression_rate": round(guardrail_regression_rate, 3),
        "validator_regression_rate": round(validator_regression_rate, 3),
        "expert_routing_regression_rate": round(expert_routing_regression_rate, 3),
        "alert_evidence_completeness_rate": round(alert_evidence_completeness_rate, 3),
        "report_generation_success_rate": round(report_generation_success_rate, 3),
    }

    threshold_values = dict(thresholds.get("thresholds") or {})
    failures = [
        name
        for name, value in metrics.items()
        if float(value) < float(threshold_values.get(name, value))
        and name.endswith("_rate")
        and name
        in {
            "schema_valid_rate",
            "alert_evidence_completeness_rate",
            "report_generation_success_rate",
        }
    ]
    failures.extend(
        name
        for name, value in metrics.items()
        if float(value) > float(threshold_values.get(name, value))
        and name
        in {
            "guardrail_regression_rate",
            "validator_regression_rate",
            "expert_routing_regression_rate",
        }
    )

    return {
        "fixtures_dir": str(fixtures_dir),
        "metrics": metrics,
        "negative_checks": {
            "malformed_lines_detected": malformed_total - malformed_valid,
        },
        "thresholds_version": thresholds.get("version", ""),
        "passed": not failures,
        "failures": sorted(set(failures)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate RunRecord governance and reporting.")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=Path("tests/fixtures"),
        help="Directory containing RunRecord fixture jsonl files.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args(argv)

    report = evaluate_runtime(args.fixtures_dir.resolve())
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
