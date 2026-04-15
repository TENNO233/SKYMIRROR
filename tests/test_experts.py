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
            "api_key": "gemini-key",
            "model": "gemini-3.1-pro-preview",
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

    result = experts.order_expert_node({"validated_text": "A car is stopped in a yellow box junction."})

    assert result["expert_results"]["order_expert"]["summary"] == "Possible box junction violation."
    assert result["expert_results"]["order_expert"]["retrieved_context_count"] == 1
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
            "api_key": "gemini-key",
            "model": "gemini-3.1-pro-preview",
            "temperature": 0.0,
            "max_tokens": 256,
            "top_k": 5,
        },
    )
    monkeypatch.setattr(experts, "get_pinecone_retriever", lambda **_: _Retriever())

    result = experts.environment_expert_node({"validated_text": "Standing water is visible on the road shoulder."})

    assert result["expert_results"]["environment_expert"]["retrieved_context_count"] == 0
    assert "No supporting RAG context" in result["expert_results"]["environment_expert"]["summary"]
