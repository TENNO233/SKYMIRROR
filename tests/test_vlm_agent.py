from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from skymirror.agents import vlm_agent
from skymirror.graph.state import _merge_dicts


def test_load_gemini_config_uses_new_env_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("GEMINI_VLM_MODEL", raising=False)

    config = vlm_agent._load_gemini_config()

    assert config.api_key == "gemini-key"
    assert config.vlm_model == "gemini-3-flash-preview"


def test_load_guardrail_config_uses_openai_env_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENAI_GUARDRAIL_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_AGENT_MODEL", raising=False)

    config = vlm_agent._load_guardrail_config()

    assert config.api_key == "openai-key"
    assert config.model == "gpt-5.4-mini"
    assert config.max_tokens == 256
    assert config.temperature == 0.0


def test_load_qwen_config_uses_singapore_default_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    monkeypatch.delenv("QWEN_VLM_MODEL", raising=False)

    config = vlm_agent._load_qwen_config()

    assert config.api_key == "dashscope-key"
    assert config.model == "qwen3.6-plus"
    assert config.base_url == "https://dashscope-intl.aliyuncs.com/api/v1"


def test_image_guardrail_allows_valid_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "frame.png"
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


def test_image_guardrail_blocks_corrupt_image(tmp_path: Path) -> None:
    image_path = tmp_path / "broken.jpg"
    image_path.write_text("not an image", encoding="utf-8")

    result = vlm_agent.image_guardrail_node({"image_path": str(image_path), "metadata": {}})

    assert result["guardrail_result"]["allowed"] is False
    assert result["guardrail_result"]["status"] == "blocked"
    assert result["guardrail_result"]["categories"] == ["invalid_image"]


def test_image_guardrail_blocks_on_guardrail_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "frame.png"
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


def test_dual_vlm_nodes_write_separate_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = vlm_agent.ImagePayload(
        source="local-file",
        media_type="image/jpeg",
        bytes_data=b"abcd",
        base64_data="YWJjZA==",
        byte_count=4,
        width=320,
        height=240,
    )

    monkeypatch.setattr(vlm_agent, "_build_image_payload", lambda _: payload)
    monkeypatch.setattr(
        vlm_agent,
        "_load_gemini_config",
        lambda: vlm_agent.GeminiConfig(
            api_key="gemini-key",
            vlm_model="gemini-3-flash-preview",
            max_tokens=64,
            temperature=0.0,
        ),
    )
    monkeypatch.setattr(
        vlm_agent,
        "_load_qwen_config",
        lambda: vlm_agent.QwenConfig(
            api_key="dashscope-key",
            model="qwen3.6-plus",
            base_url="https://dashscope-intl.aliyuncs.com/api/v1",
        ),
    )
    monkeypatch.setattr(vlm_agent, "_invoke_gemini_vlm", lambda *_: "Gemini scene text.")
    monkeypatch.setattr(vlm_agent, "_invoke_qwen_vlm", lambda *_: "Qwen scene text.")

    gemini_result = vlm_agent.gemini_vlm_node({"image_path": "frame.jpg", "metadata": {}})
    qwen_result = vlm_agent.qwen_vlm_node({"image_path": "frame.jpg", "metadata": {}})
    merged = _merge_dicts(gemini_result["vlm_outputs"], qwen_result["vlm_outputs"])

    assert merged == {
        "gemini": "Gemini scene text.",
        "qwen": "Qwen scene text.",
    }
