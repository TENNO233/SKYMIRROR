"""LLM provider factory and safe narration helper.

Shared between Alert Agent and Daily Explication Report. Select provider
via the `LLM_PROVIDER` environment variable (default: anthropic).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def get_llm(temperature: float = 0.3) -> Any:
    """Return an instantiated LangChain chat model based on LLM_PROVIDER."""
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", temperature=temperature)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model_name="claude-sonnet-4-6", temperature=temperature
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")


def narrate(prompt: str, fallback: str, *, llm: Any | None = None) -> str:
    """Invoke an LLM to narrate facts, returning `fallback` on failure.

    The Hybrid principle: callers must pre-compute all statistics and pass
    them as text in `prompt`. This function does not compute anything — it
    only transforms facts into prose.

    Args:
        prompt: Natural-language request containing pre-computed facts.
        fallback: Template-rendered text to return if the LLM errors.
        llm: Pre-constructed LLM (for tests). If None, calls `get_llm()`.
    """
    if llm is None:
        try:
            llm = get_llm()
        except Exception as exc:
            logger.warning("get_llm failed: %s — using fallback.", exc)
            return f"{fallback}\n\n⚠️ LLM narration unavailable: {exc}"
    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=prompt)])
        content = getattr(response, "content", None)
        return content if isinstance(content, str) and content.strip() else fallback
    except Exception as exc:
        logger.warning("LLM narration failed: %s — using fallback.", exc)
        return f"{fallback}\n\n⚠️ LLM narration unavailable: {exc}"
