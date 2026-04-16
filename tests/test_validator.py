from __future__ import annotations

import pytest

from skymirror.agents import validator
from skymirror.agents.scene_schema import TrafficSceneSignals, ValidatedSceneReport


def test_validator_requires_both_provider_outputs() -> None:
    with pytest.raises(ValueError):
        validator.validator_agent_node(
            {
                "vlm_outputs": {"gemini": {"summary": "Only Gemini is present."}},
                "metadata": {},
            }
        )


def test_validator_agent_node_reconciles_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        validator,
        "_load_validator_config",
        lambda: validator.ValidatorConfig(
            api_key="openai-key",
            model="gpt-5.4-mini",
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
        ),
    )

    result = validator.validator_agent_node(
        {
            "vlm_outputs": {
                "gemini": {
                    "summary": "Two cars wait at a junction.",
                    "direct_observations": ["Two cars wait at a junction."],
                    "signals": {"vehicle_count": 2, "stopped_vehicle_count": 2},
                },
                "qwen": {
                    "summary": "Two vehicles are stopped before the intersection.",
                    "direct_observations": ["Two vehicles are stopped before the intersection."],
                    "signals": {"vehicle_count": 2, "stopped_vehicle_count": 2},
                },
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
    assert result["metadata"]["validator"]["input_sources"] == ["gemini", "qwen"]
