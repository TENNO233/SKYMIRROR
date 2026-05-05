from __future__ import annotations

from pathlib import Path


def test_load_policy_and_thresholds() -> None:
    from skymirror.tools.governance import load_policy, load_release_thresholds

    policy = load_policy()
    thresholds = load_release_thresholds()

    assert policy["version"] == "2026-04-19.v1"
    assert "traffic-regulations" in policy["rag_controls"]["allowed_namespaces"]
    assert thresholds["version"] == "2026-04-19.v1"


def test_validate_run_record_accepts_standard_shape() -> None:
    from skymirror.tools.run_records import build_run_record

    record = build_run_record(
        run_id="run_test",
        workflow_mode="frame",
        camera_id="4798",
        image_path="frame.jpg",
        status="clean",
        metadata={
            "models": {},
            "prompts": {},
            "policies": {},
            "retrieval": {},
            "external_calls": {},
        },
    )

    assert record["run_id"] == "run_test"
    assert record["status"] == "clean"


def test_write_run_record_partitions_by_date(tmp_path: Path) -> None:
    from skymirror.tools.run_records import build_run_record, write_run_record

    record = build_run_record(
        run_id="run_test",
        workflow_mode="frame",
        camera_id="4798",
        image_path="frame.jpg",
        status="clean",
        timestamp="2026-04-12T00:00:00Z",
        metadata={
            "models": {},
            "prompts": {},
            "policies": {},
            "retrieval": {},
            "external_calls": {},
        },
    )
    output_path = write_run_record(tmp_path, record)

    assert output_path.name == "2026-04-12.jsonl"
    assert output_path.is_file()


def test_offline_runtime_eval_reports_metrics(fixtures_dir: Path) -> None:
    from scripts.evaluate_runtime import evaluate_runtime

    report = evaluate_runtime(fixtures_dir)

    assert "metrics" in report
    assert "schema_valid_rate" in report["metrics"]
    assert report["negative_checks"]["malformed_lines_detected"] >= 1
    assert isinstance(report["passed"], bool)
