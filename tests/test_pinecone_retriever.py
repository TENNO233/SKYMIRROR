from __future__ import annotations

from langchain_core.documents import Document

from skymirror.tools import pinecone_retriever


class _FakeEmbeddings:
    def embed_query(self, _text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _FakePinecone:
    def __init__(self, exists: bool) -> None:
        self.exists = exists
        self.created: list[dict[str, object]] = []
        self.describe_calls = 0

    def has_index(self, _name: str) -> bool:
        return self.exists

    def create_index(self, **kwargs: object) -> None:
        self.created.append(kwargs)
        self.exists = True

    def describe_index(self, _name: str | None = None, *, name: str | None = None) -> dict[str, object]:
        self.describe_calls += 1
        return {
            "host": "demo-index.svc.us-east-1.pinecone.io",
            "status": {"ready": True},
        }


class _FakeIntegratedIndex:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.upsert_calls: list[tuple[str, list[dict[str, object]]]] = []

    def search(self, namespace: str, query: dict[str, object], fields: list[str]):
        self.search_calls.append({"namespace": namespace, "query": query, "fields": fields})
        return {
            "result": {
                "hits": [
                    {
                        "_id": "rec-1",
                        "_score": 0.9,
                        "fields": {
                            "text": "Official guidance chunk",
                            "title": "TR 68",
                            "chunk_index": 3,
                        },
                    }
                ]
            }
        }

    def upsert_records(self, namespace: str, records: list[dict[str, object]]) -> None:
        self.upsert_calls.append((namespace, records))


def test_resolve_index_dimension_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PINECONE_INDEX_DIMENSION", "1536")
    assert pinecone_retriever._resolve_index_dimension() == 1536


def test_resolve_index_dimension_can_probe_embeddings(monkeypatch) -> None:
    monkeypatch.delenv("PINECONE_INDEX_DIMENSION", raising=False)
    monkeypatch.setattr(pinecone_retriever, "_get_embeddings", lambda model=None: _FakeEmbeddings())

    assert pinecone_retriever._resolve_index_dimension() == 3


def test_ensure_index_exists_creates_missing_serverless_index(monkeypatch) -> None:
    pc = _FakePinecone(exists=False)

    monkeypatch.setenv("PINECONE_INDEX_DIMENSION", "1024")
    monkeypatch.setenv("PINECONE_CLOUD", "aws")
    monkeypatch.setenv("PINECONE_REGION", "us-east-1")
    monkeypatch.setenv("PINECONE_INDEX_METRIC", "cosine")
    monkeypatch.setenv("PINECONE_DELETION_PROTECTION", "disabled")

    pinecone_retriever._ensure_index_exists(pc, "skymirror-rag")

    assert len(pc.created) == 1
    created = pc.created[0]
    assert created["name"] == "skymirror-rag"
    assert created["dimension"] == 1024
    assert created["metric"] == "cosine"
    assert getattr(created["spec"], "cloud") == "aws"
    assert getattr(created["spec"], "region") == "us-east-1"


def test_get_pinecone_retriever_uses_integrated_search(monkeypatch) -> None:
    fake_index = _FakeIntegratedIndex()
    monkeypatch.setattr(pinecone_retriever, "_get_index", lambda: fake_index)
    monkeypatch.setattr(
        pinecone_retriever,
        "_get_index_description",
        lambda: {"embed": {"field_map": {"text": "text"}}},
    )

    retriever = pinecone_retriever.get_pinecone_retriever(namespace="traffic-regulations", top_k=4)
    documents = retriever.invoke("find AV rules")

    assert len(documents) == 1
    assert documents[0].page_content == "Official guidance chunk"
    assert documents[0].metadata["record_id"] == "rec-1"
    assert fake_index.search_calls[0]["query"] == {"inputs": {"text": "find AV rules"}, "top_k": 4}


def test_upsert_documents_to_namespace_uses_integrated_upsert(monkeypatch) -> None:
    fake_index = _FakeIntegratedIndex()
    monkeypatch.setattr(pinecone_retriever, "_get_index", lambda: fake_index)
    monkeypatch.setattr(
        pinecone_retriever,
        "_get_index_description",
        lambda: {"embed": {"field_map": {"text": "text"}}},
    )

    inserted = pinecone_retriever.upsert_documents_to_namespace(
        "road-conditions",
        [
            Document(
                page_content="Chunk A",
                metadata={"title": "SDRE", "chunk_index": 0},
            )
        ],
        ids=["doc-1"],
    )

    assert inserted == ["doc-1"]
    assert fake_index.upsert_calls == [
        (
            "road-conditions",
            [
                {
                    "_id": "doc-1",
                    "text": "Chunk A",
                    "title": "SDRE",
                    "chunk_index": 0,
                }
            ],
        )
    ]
