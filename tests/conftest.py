"""Shared pytest fixtures for Daily Explication Report tests."""
from __future__ import annotations

import types
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Absolute path to tests/fixtures/."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_llm(monkeypatch):
    """Replace `get_llm()` with a deterministic echo LLM for offline tests.

    The mock's `invoke()` returns a synthetic narration that embeds the
    first 80 chars of the prompt, so tests can assert the prompt made it
    through without hitting a real API.
    """
    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeLLM:
        def invoke(self, messages):
            # messages is a list[HumanMessage] in real code; for tests we
            # accept either list[Message] or str.
            if hasattr(messages, "__iter__") and not isinstance(messages, str):
                prompt = "\n".join(getattr(m, "content", str(m)) for m in messages)
            else:
                prompt = str(messages)
            head = prompt[:80].replace("\n", " ")
            return _FakeResponse(content=f"[MOCK LLM narration for: {head!r}]")

    monkeypatch.setattr(
        "skymirror.agents._llm.get_llm",
        lambda **kwargs: _FakeLLM(),
    )
