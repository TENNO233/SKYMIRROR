from __future__ import annotations

import pytest

from skymirror.agents import validator
from skymirror.agents.scene_schema import TrafficSceneSignals, ValidatedSceneReport
from skymirror.agents.vlm_agent import ImagePayload


def test_validator_requires_single_vlm_output() -> None:
    with pytest.raises(ValueError):
        validator.validator_agent_node(
            {
                "image_path": "frame.jpg",
                "metadata": {},
            }
        )


def test_validator_agent_node_cross_checks_single_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        validator,
        "build_image_payload",
        lambda _: ImagePayload(
            source="frame.jpg",
            media_type="image/jpeg",
            bytes_data=b"abcd",
            base64_data="YWJjZA==",
            byte_count=4,
            width=320,
            height=240,
        ),
    )
    monkeypatch.setattr(
        validator,
        "_load_validator_config",
        lambda: validator.ValidatorConfig(
            api_key="openai-key",
            model="gpt-5.4",
            max_tokens=64,
            temperature=0.0,
        ),
    )
    monkeypatch.setattr(
        validator,
        "_invoke_openai_validator",
        lambda *_: ValidatedSceneReport(
            normalized_description="Two cars are stopped at a junction with clear lane markings.",
            consensus_observations=[
                "Two cars are stopped at the junction approach.",
                "Lane markings are clearly visible.",
            ],
            road_features=["junction", "lane markings"],
            signals=TrafficSceneSignals(
                vehicle_count=2,
                stopped_vehicle_count=2,
                blocked_lanes=0,
            ),
            discarded_claims=["No visible collision evidence."],
        ),
    )

    result = validator.validator_agent_node(
        {
            "image_path": "frame.jpg",
            "vlm_output": {
                "summary": "Two cars wait at a junction and may have collided.",
                "direct_observations": [
                    "Two cars wait at a junction.",
                    "Possible collision damage is visible.",
                ],
                "signals": {"vehicle_count": 2, "stopped_vehicle_count": 2, "collision_cue": True},
            },
            "metadata": {},
        }
    )

    assert result["validated_text"] == (
        "Scene assessment: Two cars are stopped at a junction with clear lane markings. "
        "Government relevance: no immediate enforcement, safety, or maintenance action is indicated; routine monitoring is sufficient."
    )
    assert result["validated_signals"]["vehicle_count"] == 2
    assert result["validated_scene"]["road_features"] == ["junction", "lane markings"]
    assert result["metadata"]["validator"]["provider"] == "openai"
    assert result["metadata"]["validator"]["review_mode"] == "image_cross_check"
    assert result["metadata"]["validator"]["summary_standard"] == "surveillance_brief_v1"
    assert result["metadata"]["validator"]["input_sources"] == ["vlm_output"]


def test_validated_text_from_report_uses_surveillance_brief_for_incident() -> None:
    summary = validator._validated_text_from_report(
        ValidatedSceneReport(
            normalized_description="Collision damage is visible across two lanes.",
            consensus_observations=[
                "Two damaged vehicles are stopped in the carriageway.",
            ],
            notable_hazards=["debris"],
            signals=TrafficSceneSignals(
                vehicle_count=4,
                stopped_vehicle_count=2,
                blocked_lanes=2,
                collision_cue=True,
            ),
        )
    )

    assert summary == (
        "Scene assessment: Collision damage is visible across two lanes; at least 2 blocked lanes are visible. "
        "Government relevance: immediate safety review is warranted, and traffic management attention is warranted because lane capacity appears reduced."
    )


def test_validated_text_from_report_uses_surveillance_brief_for_clear_scene() -> None:
    summary = validator._validated_text_from_report(
        ValidatedSceneReport(
            normalized_description="Traffic is moving steadily through the monitored junction.",
            consensus_observations=[
                "Vehicles are moving through the junction.",
            ],
            signals=TrafficSceneSignals(
                vehicle_count=5,
                stopped_vehicle_count=0,
                blocked_lanes=0,
            ),
        )
    )

    assert summary == (
        "Scene assessment: Traffic is moving steadily through the monitored junction. "
        "Government relevance: no immediate enforcement, safety, or maintenance action is indicated; routine monitoring is sufficient."
    )


def test_validated_text_from_report_uses_surveillance_brief_for_congestion() -> None:
    summary = validator._validated_text_from_report(
        ValidatedSceneReport(
            normalized_description="Heavy congestion is visible on the approach lanes.",
            consensus_observations=[
                "Multiple vehicles are queueing before the junction.",
            ],
            signals=TrafficSceneSignals(
                vehicle_count=18,
                stopped_vehicle_count=8,
                blocked_lanes=0,
                queueing=True,
            ),
        )
    )

    assert summary == (
        "Scene assessment: Heavy congestion is visible on the approach lanes. "
        "Government relevance: continued traffic-flow monitoring is warranted."
    )
