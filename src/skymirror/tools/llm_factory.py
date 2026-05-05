"""LLM provider factory and safe narration helper.

Shared between SKYMIRROR's non-VLM agents. By default these agents use
OpenAI GPT-5.4 Mini unless an explicit provider override is set.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LLM_PROVIDER = "openai"
_DEFAULT_OPENAI_AGENT_MODEL = "gpt-5.4-mini"


def get_openai_agent_model() -> str:
    """Return the shared OpenAI model name for non-VLM agents."""
    model = os.getenv("OPENAI_AGENT_MODEL", _DEFAULT_OPENAI_AGENT_MODEL).strip()
    return model or _DEFAULT_OPENAI_AGENT_MODEL


def build_openai_chat_model(
    *,
    temperature: float,
    model: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
) -> Any:
    """Construct a ChatOpenAI instance with shared defaults."""
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": (model or get_openai_agent_model()),
        "temperature": temperature,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


def get_llm(temperature: float = 0.3) -> Any:
    """Return an instantiated LangChain chat model based on LLM_PROVIDER."""
    provider = os.getenv("LLM_PROVIDER", _DEFAULT_LLM_PROVIDER).lower()
    if provider == "openai":
        return build_openai_chat_model(temperature=temperature)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model_name="claude-sonnet-4-6", temperature=temperature)
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
