from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from skymirror.agents import vlm_agent
from skymirror.agents.scene_schema import TrafficSceneSignals, VlmSceneReport


def _make_case_dir(case_name: str) -> Path:
    root = Path.cwd() / ".dashboard_test_workspace" / f"{case_name}_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_load_vlm_config_uses_openai_env_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENAI_VLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_AGENT_MODEL", raising=False)

    config = vlm_agent._load_vlm_config()

    assert config.api_key == "openai-key"
    assert config.model == "gpt-5.4"


def test_load_guardrail_config_uses_openai_env_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENAI_GUARDRAIL_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_AGENT_MODEL", raising=False)

    config = vlm_agent._load_guardrail_config()

    assert config.api_key == "openai-key"
    assert config.model == "gpt-5.4-mini"
    assert config.max_tokens == 256
    assert config.temperature == 0.0


def test_image_guardrail_allows_valid_image(monkeypatch: pytest.MonkeyPatch) -> None:
    case_dir = _make_case_dir("guardrail_valid_image")
    try:
        image_path = case_dir / "frame.png"
        Image.new("RGB", (320, 240), color=(12, 34, 56)).save(image_path)

        monkeypatch.setattr(
            vlm_agent,
            "_load_guardrail_config",
            lambda: vlm_agent.OpenAIGuardrailConfig(
                api_key="openai-key",
                model="gpt-5.4-mini",
                max_tokens=64,
                temperature=0.0,
            ),
        )
        monkeypatch.setattr(
            vlm_agent,
            "_classify_image_safety",
            lambda *_: vlm_agent.GuardrailAssessment(
                allowed=True,
                status="allowed",
                reason="Safe public traffic scene.",
                categories=[],
            ),
        )

        result = vlm_agent.image_guardrail_node({"image_path": str(image_path), "metadata": {}})

        assert result["guardrail_result"]["allowed"] is True
        assert result["guardrail_result"]["status"] == "allowed"
        assert result["metadata"]["guardrail"]["provider"] == "openai"
        assert result["metadata"]["guardrail"]["width"] == 320
        assert result["metadata"]["guardrail"]["height"] == 240
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_image_guardrail_blocks_corrupt_image() -> None:
    case_dir = _make_case_dir("guardrail_corrupt_image")
    try:
        image_path = case_dir / "broken.jpg"
        image_path.write_text("not an image", encoding="utf-8")

        result = vlm_agent.image_guardrail_node({"image_path": str(image_path), "metadata": {}})

        assert result["guardrail_result"]["allowed"] is False
        assert result["guardrail_result"]["status"] == "blocked"
        assert result["guardrail_result"]["categories"] == ["invalid_image"]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_image_guardrail_blocks_on_guardrail_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    case_dir = _make_case_dir("guardrail_exception")
    try:
        image_path = case_dir / "frame.png"
        Image.new("RGB", (320, 240), color=(12, 34, 56)).save(image_path)

        monkeypatch.setattr(
            vlm_agent,
            "_load_guardrail_config",
            lambda: vlm_agent.OpenAIGuardrailConfig(
                api_key="openai-key",
                model="gpt-5.4-mini",
                max_tokens=64,
                temperature=0.0,
            ),
        )

        def _raise(*_: object) -> vlm_agent.GuardrailAssessment:
            raise RuntimeError("OpenAI unavailable")

        monkeypatch.setattr(vlm_agent, "_classify_image_safety", _raise)

        result = vlm_agent.image_guardrail_node({"image_path": str(image_path), "metadata": {}})

        assert result["guardrail_result"]["allowed"] is False
        assert result["guardrail_result"]["categories"] == ["guardrail_error"]
        assert "OpenAI unavailable" in result["guardrail_result"]["reason"]
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_vlm_agent_node_writes_single_output(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = vlm_agent.ImagePayload(
        source="local-file",
        media_type="image/jpeg",
        bytes_data=b"abcd",
        base64_data="YWJjZA==",
        byte_count=4,
        width=320,
        height=240,
    )

    monkeypatch.setattr(vlm_agent, "build_image_payload", lambda _: payload)
    monkeypatch.setattr(
        vlm_agent,
        "_load_vlm_config",
        lambda: vlm_agent.VisionConfig(
            api_key="openai-key",
            model="gpt-5.4",
            max_tokens=64,
            temperature=0.0,
        ),
    )
    monkeypatch.setattr(
        vlm_agent,
        "_invoke_vlm",
        lambda *_: VlmSceneReport(
            summary="Two cars are stopped at a junction.",
            direct_observations=["Two cars are stopped.", "Lane markings are visible."],
            signals=TrafficSceneSignals(vehicle_count=2, stopped_vehicle_count=2),
        ),
    )

    result = vlm_agent.vlm_agent_node({"image_path": "frame.jpg", "metadata": {}})

    assert result["vlm_output"]["summary"] == "Two cars are stopped at a junction."
    assert result["vlm_output"]["signals"]["vehicle_count"] == 2
    assert result["metadata"]["vlm"]["model"] == "gpt-5.4"


def test_invoke_vlm_uses_openai_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = vlm_agent.ImagePayload(
        source="local-file",
        media_type="image/jpeg",
        bytes_data=b"abcd",
        base64_data="YWJjZA==",
        byte_count=4,
        width=320,
        height=240,
    )
    config = vlm_agent.VisionConfig(
        api_key="openai-key",
        model="gpt-5.4",
        max_tokens=640,
        temperature=0.0,
    )
    recorded_messages: list[object] = []

    class _StructuredLLM:
        def invoke(self, messages):
            recorded_messages.extend(messages)
            return VlmSceneReport(
                summary="Cars move along a clear roadway.",
                direct_observations=["Cars move along the roadway."],
                signals=TrafficSceneSignals(vehicle_count=4),
            )

    class _LLM:
        def with_structured_output(self, _schema):
            return _StructuredLLM()

    monkeypatch.setattr(vlm_agent, "build_openai_chat_model", lambda **_: _LLM())

    report = vlm_agent._invoke_vlm(payload, config)

    assert len(recorded_messages) == 2
    assert report.summary == "Cars move along a clear roadway."
    assert report.signals.vehicle_count == 4
