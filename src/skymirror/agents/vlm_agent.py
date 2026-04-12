"""
vlm_agent.py — Vision-Language Model Agent
============================================
Responsibility: Accept a traffic camera image path and return a raw
natural-language description of what is visible in the frame.

Implementation notes (TODO)
---------------------------
- Load image from `state["image_path"]` (local path or remote URI).
- Encode the image as base64 or pass the URL directly to the VLM API.
- Recommended models: GPT-4o (`gpt-4o`), Claude 3.5 Sonnet
  (`claude-3-5-sonnet-20241022`), or a locally hosted LLaVA variant.
- The raw output is intentionally unfiltered — validator_agent handles cleanup.
- Consider prompt-caching (Anthropic) or seed params (OpenAI) for cost control.
"""

from __future__ import annotations

import logging
from typing import Any

from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)


def vlm_agent_node(state: SkymirrorState) -> dict[str, Any]:
    """
    LangGraph node function for the VLM Agent.

    Args:
        state: Current pipeline state.  `state["image_path"]` must be set.

    Returns:
        Partial state dict with `vlm_text` populated.
    """
    image_path: str = state["image_path"]
    logger.info("vlm_agent: Processing image — %s", image_path)

    # TODO: Implement vision-language model call.
    # Example skeleton:
    #
    # from langchain_openai import ChatOpenAI
    # from langchain_core.messages import HumanMessage
    # import base64, pathlib
    #
    # image_data = base64.b64encode(pathlib.Path(image_path).read_bytes()).decode()
    # llm = ChatOpenAI(model="gpt-4o", max_tokens=512)
    # message = HumanMessage(content=[
    #     {"type": "text", "text": "Describe all traffic-related events visible."},
    #     {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
    # ])
    # response = llm.invoke([message])
    # vlm_text = response.content

    raise NotImplementedError("vlm_agent_node is not yet implemented.")
