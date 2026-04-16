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
        "Two cars are stopped at a junction with clear lane markings."
    )
    assert result["validated_signals"]["vehicle_count"] == 2
    assert result["validated_scene"]["road_features"] == ["junction", "lane markings"]
    assert result["metadata"]["validator"]["provider"] == "openai"
    assert result["metadata"]["validator"]["review_mode"] == "image_cross_check"
    assert result["metadata"]["validator"]["input_sources"] == ["vlm_output"]
