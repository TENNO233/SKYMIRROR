from __future__ import annotations

from langchain_core.documents import Document

from skymirror.agents import experts


def test_order_expert_node_uses_retriever_and_model(monkeypatch) -> None:
    documents = [
        Document(
            page_content="Vehicles must not stop across a yellow box junction.",
            metadata={"source_path": "rules.md", "title": "Road Traffic Rules", "chunk_index": 0},
        )
    ]

    class _Retriever:
        def invoke(self, query: str):
            assert "junction" in query
            return documents

    monkeypatch.setattr(
        experts,
        "_load_expert_model_config",
        lambda: {
            "api_key": "openai-key",
            "model": "gpt-5.4-mini",
            "temperature": 0.0,
            "max_tokens": 256,
            "top_k": 5,
        },
    )
    monkeypatch.setattr(experts, "get_pinecone_retriever", lambda **_: _Retriever())
    monkeypatch.setattr(
        experts,
        "_invoke_expert_llm",
        lambda spec, validated_text, docs: experts.ExpertAssessment(
            summary="Possible box junction violation.",
            findings=["A vehicle appears stopped within the box junction."],
            severity="medium",
            recommended_action="Review against the retrieved traffic rule.",
            citations=[
                experts.ExpertCitation(
                    source_path="rules.md",
                    title="Road Traffic Rules",
                    chunk_index=0,
                )
            ],
        ),
    )

    result = experts.order_expert_node(
        {"validated_text": "A car is stopped in a yellow box junction."}
    )

    assert result["expert_results"]["order_expert"]["matched"] is True
    assert result["expert_results"]["order_expert"]["summary"] == (
        "Detected 1 order-related issue(s): llm_inferred_order_issue."
    )
    assert result["expert_results"]["order_expert"]["llm_raw_assessment"]["summary"] == (
        "Possible box junction violation."
    )
    assert result["metadata"]["experts"]["order_expert"]["retrieved_context_count"] == 1
    assert result["metadata"]["experts"]["order_expert"]["rag_triggered"] is True
    assert result["metadata"]["experts"]["order_expert"]["namespace"] == "traffic-regulations"


def test_environment_expert_returns_empty_assessment_when_no_context(monkeypatch) -> None:
    class _Retriever:
        def invoke(self, query: str):
            assert query
            return []

    monkeypatch.setattr(
        experts,
        "_load_expert_model_config",
        lambda: {
            "api_key": "openai-key",
            "model": "gpt-5.4-mini",
            "temperature": 0.0,
            "max_tokens": 256,
            "top_k": 5,
        },
    )
    monkeypatch.setattr(experts, "get_pinecone_retriever", lambda **_: _Retriever())

    result = experts.environment_expert_node(
        {"validated_text": "Roadway appears ordinary with no confirmed environmental hazard."}
    )

    assert result["expert_results"]["environment_expert"]["matched"] is False
    assert result["expert_results"]["environment_expert"]["summary"] == (
        "No environment-related issues detected."
    )
    assert result["metadata"]["experts"]["environment_expert"]["retrieved_context_count"] == 0
    assert result["metadata"]["experts"]["environment_expert"]["rag_triggered"] is False


def test_expert_gracefully_handles_rag_fallback_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        experts,
        "_load_expert_model_config",
        lambda: {
            "api_key": "openai-key",
            "model": "gpt-5.4-mini",
            "temperature": 0.0,
            "max_tokens": 256,
            "top_k": 5,
        },
    )
    monkeypatch.setattr(
        experts,
        "get_pinecone_retriever",
        lambda **_: (_ for _ in ()).throw(
            RuntimeError("Environment variable PINECONE_API_KEY is required.")
        ),
    )

    result = experts.environment_expert_node(
        {"validated_text": "Roadway appears ordinary with no confirmed environmental hazard."}
    )

    assert result["expert_results"]["environment_expert"]["matched"] is False
    assert result["expert_results"]["environment_expert"]["summary"] == (
        "No environment-related issues detected."
    )
    assert result["metadata"]["experts"]["environment_expert"]["rag_triggered"] is False
    assert result["metadata"]["experts"]["environment_expert"]["rag_error"] == (
        "Environment variable PINECONE_API_KEY is required."
    )
