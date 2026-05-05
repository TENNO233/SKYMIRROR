"""Shared pytest fixtures for SKYMIRROR agent tests."""

from __future__ import annotations

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


@pytest.fixture(autouse=True)
def _block_network_by_default(monkeypatch, request):
    """Block accidental network calls in tests.

    Tests that need httpx should mock it explicitly using `patch(...)`.
    """
    # Tests that explicitly patch httpx should not be affected
    from unittest.mock import MagicMock

    def _raise_blocked(*args, **kwargs):
        raise Exception("Network blocked in tests — mock httpx explicitly if needed")

    # Patch httpx.get in lta_lookup to raise; tests using patch() will override this
    import skymirror.tools.alert.lta_lookup as lta_mod

    fake_httpx = MagicMock()
    fake_httpx.get = MagicMock(side_effect=_raise_blocked)
    monkeypatch.setattr(lta_mod, "httpx", fake_httpx)
