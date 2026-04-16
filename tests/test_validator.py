from __future__ import annotations

import pytest

from skymirror.agents import validator


def test_validator_requires_both_provider_outputs() -> None:
    with pytest.raises(ValueError):
        validator.validator_agent_node(
            {
                "vlm_outputs": {"gemini": "Only Gemini is present."},
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
        lambda *_: "Two cars are stopped at a junction with clear lane markings.",
    )

    result = validator.validator_agent_node(
        {
            "vlm_outputs": {
                "gemini": "Two cars wait at a junction.",
                "qwen": "Two vehicles are stopped before the intersection.",
            },
            "metadata": {},
        }
    )

    assert result["validated_text"] == (
        "Two cars are stopped at a junction with clear lane markings."
    )
    assert result["metadata"]["validator"]["provider"] == "openai"
    assert result["metadata"]["validator"]["input_sources"] == ["gemini", "qwen"]
