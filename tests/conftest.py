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

    Supports both direct `invoke()` (narrate pattern) and
    `with_structured_output()` (classification pattern).
    """
    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeClassificationResult:
        """Mimics a Pydantic model instance returned by with_structured_output."""
        def __init__(self):
            self.sub_type = "other"
            self.severity = "medium"
            self.message = "[MOCK] Alert classification result"

    class _FakeStructuredLLM:
        def invoke(self, messages):
            return _FakeClassificationResult()

    class _FakeLLM:
        def invoke(self, messages):
            if hasattr(messages, "__iter__") and not isinstance(messages, str):
                prompt = "\n".join(getattr(m, "content", str(m)) for m in messages)
            else:
                prompt = str(messages)
            head = prompt[:80].replace("\n", " ")
            return _FakeResponse(content=f"[MOCK LLM narration for: {head!r}]")

        def with_structured_output(self, schema):
            return _FakeStructuredLLM()

    monkeypatch.setattr(
        "skymirror.tools.llm_factory.get_llm",
        lambda **kwargs: _FakeLLM(),
    )
