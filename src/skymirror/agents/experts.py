"""
experts.py — Domain Expert Agents (Order / Safety / Environment)
=================================================================
Each expert agent is a specialised LangGraph node that:
  1. Retrieves relevant regulations / precedents from Pinecone (RAG).
  2. Constructs a prompt combining the retrieved context + validated_text.
  3. Calls an LLM to produce structured findings.
  4. Returns a partial state update under `expert_results["<expert_name>"]`.

Shared utilities
----------------
- `get_pinecone_retriever(namespace)` from `tools.pinecone_retriever` provides
  the LangChain `VectorStoreRetriever` for each expert's Pinecone namespace.
- Each expert uses a *separate namespace* in Pinecone so knowledge bases don't
  cross-contaminate.

Implementation notes (TODO per expert)
---------------------------------------
order_expert
    - Pinecone namespace: "traffic-regulations"
    - LLM task: identify specific violated regulation codes.

safety_expert
    - Pinecone namespace: "safety-incidents"
    - LLM task: classify incident type, estimate severity (low/med/high/critical).

environment_expert
    - Pinecone namespace: "road-conditions"
    - LLM task: identify environmental hazards and affected road segments.
"""

from __future__ import annotations

import logging
from typing import Any

from skymirror.graph.state import SkymirrorState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order Expert
# ---------------------------------------------------------------------------

def order_expert_node(state: SkymirrorState) -> dict[str, Any]:
    """
    LangGraph node: analyses traffic-order violations via RAG.

    Returns:
        Partial state with `expert_results["order_expert"]` populated.
    """
    validated_text: str = state.get("validated_text", "")
    logger.info("order_expert: Analysing traffic-order violations.")

    # TODO: Implement RAG + LLM chain.
    # retriever = get_pinecone_retriever(namespace="traffic-regulations")
    # rag_chain = RetrievalQA.from_chain_type(llm=..., retriever=retriever)
    # findings = rag_chain.invoke(validated_text)
    # return {"expert_results": {"order_expert": findings}}

    raise NotImplementedError("order_expert_node is not yet implemented.")


# ---------------------------------------------------------------------------
# Safety Expert
# ---------------------------------------------------------------------------

def safety_expert_node(state: SkymirrorState) -> dict[str, Any]:
    """
    LangGraph node: analyses accident / hazard situations via RAG.

    Returns:
        Partial state with `expert_results["safety_expert"]` populated.
    """
    validated_text: str = state.get("validated_text", "")
    logger.info("safety_expert: Analysing safety incidents.")

    # TODO: Implement RAG + LLM chain.
    # retriever = get_pinecone_retriever(namespace="safety-incidents")
    # ...

    raise NotImplementedError("safety_expert_node is not yet implemented.")


# ---------------------------------------------------------------------------
# Environment Expert
# ---------------------------------------------------------------------------

def environment_expert_node(state: SkymirrorState) -> dict[str, Any]:
    """
    LangGraph node: analyses environmental / road-condition issues via RAG.

    Returns:
        Partial state with `expert_results["environment_expert"]` populated.
    """
    validated_text: str = state.get("validated_text", "")
    logger.info("environment_expert: Analysing environmental conditions.")

    # TODO: Implement RAG + LLM chain.
    # retriever = get_pinecone_retriever(namespace="road-conditions")
    # ...

    raise NotImplementedError("environment_expert_node is not yet implemented.")
