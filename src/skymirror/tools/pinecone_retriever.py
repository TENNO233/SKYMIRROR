"""
pinecone_retriever.py - Pinecone retriever and writer utilities.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
_DEFAULT_RAG_TOP_K = 5
_DEFAULT_PINECONE_CLOUD = "aws"
_DEFAULT_PINECONE_REGION = "us-east-1"
_DEFAULT_PINECONE_METRIC = "cosine"
_DEFAULT_PINECONE_READY_TIMEOUT_SECONDS = 180
_INDEX_PROBE_TEXT = "skymirror pinecone dimension probe"

_lock = threading.Lock()
_pinecone_client: Optional[object] = None
_index: Optional[object] = None
_index_host: Optional[str] = None
_index_description: Optional[Any] = None


def _read_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required.")
    return value


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc


def _read_optional_env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _init_pinecone() -> None:
    """Initialise the Pinecone client and cache the target index handle."""
    global _pinecone_client, _index, _index_host, _index_description

    if _index is not None:
        return

    with _lock:
        if _index is not None:
            return

        from pinecone import Pinecone

        api_key = _read_required_env("PINECONE_API_KEY")
        index_name = _read_required_env("PINECONE_INDEX_NAME")

        pc = Pinecone(api_key=api_key)
        _ensure_index_exists(pc, index_name)
        description = pc.describe_index(name=index_name)

        host = os.getenv("PINECONE_INDEX_HOST", "").strip()
        if not host:
            host = _extract_index_host(description)

        _pinecone_client = pc
        _index_host = host
        _index_description = description
        _index = pc.Index(host=host)

        logger.info("pinecone_retriever: Initialised Pinecone index '%s'.", index_name)


def _get_index():
    _init_pinecone()
    if _index is None:
        raise RuntimeError("Pinecone index was not initialised.")
    return _index


def _get_index_description() -> Any:
    _init_pinecone()
    if _index_description is None:
        raise RuntimeError("Pinecone index description was not initialised.")
    return _index_description


def _get_embeddings(model: Optional[str] = None) -> Any:
    from langchain_openai import OpenAIEmbeddings

    resolved_model = (
        model
        or os.getenv("OPENAI_EMBEDDING_MODEL", _DEFAULT_OPENAI_EMBEDDING_MODEL).strip()
        or _DEFAULT_OPENAI_EMBEDDING_MODEL
    )
    return OpenAIEmbeddings(
        api_key=_read_required_env("OPENAI_API_KEY"),
        model=resolved_model,
    )


def _extract_index_host(description: Any) -> str:
    if isinstance(description, dict):
        host = description.get("host")
    else:
        host = getattr(description, "host", None)
        if host is None and hasattr(description, "to_dict"):
            host = description.to_dict().get("host")

    host_value = str(host or "").strip()
    if not host_value:
        raise RuntimeError("Pinecone describe_index response did not include a host.")
    return host_value


def _extract_embed_config(description: Any) -> dict[str, Any] | None:
    if isinstance(description, dict):
        embed = description.get("embed")
    else:
        embed = getattr(description, "embed", None)
        if embed is None and hasattr(description, "to_dict"):
            embed = description.to_dict().get("embed")

    if embed is None:
        return None
    if isinstance(embed, dict):
        return embed
    if hasattr(embed, "to_dict"):
        return embed.to_dict()
    return dict(embed)


def _get_integrated_text_field() -> str | None:
    embed = _extract_embed_config(_get_index_description())
    if not embed:
        return None

    field_map = embed.get("field_map") or {}
    if not field_map:
        return None

    first_target = next(iter(field_map.values()), None)
    if first_target is None:
        return None
    return str(first_target)


def _get_integrated_input_field() -> str | None:
    embed = _extract_embed_config(_get_index_description())
    if not embed:
        return None

    field_map = embed.get("field_map") or {}
    first_source = next(iter(field_map.keys()), None)
    if first_source is None:
        return None
    return str(first_source)


def _is_index_ready(description: Any) -> bool:
    status: Any
    if isinstance(description, dict):
        status = description.get("status", {})
    else:
        status = getattr(description, "status", None)
        if status is None and hasattr(description, "to_dict"):
            status = description.to_dict().get("status", {})

    if isinstance(status, dict):
        return bool(status.get("ready"))

    return bool(getattr(status, "ready", False))


def _resolve_index_dimension() -> int:
    explicit_dimension = os.getenv("PINECONE_INDEX_DIMENSION", "").strip()
    if explicit_dimension:
        try:
            return int(explicit_dimension)
        except ValueError as exc:
            raise ValueError("Environment variable PINECONE_INDEX_DIMENSION must be an integer.") from exc

    probe_vector = _get_embeddings().embed_query(_INDEX_PROBE_TEXT)
    dimension = len(probe_vector)
    if dimension <= 0:
        raise RuntimeError("Embedding probe returned an invalid vector dimension.")
    return dimension


def _wait_for_index_ready(pc: Any, index_name: str) -> Any:
    timeout_seconds = _read_int_env(
        "PINECONE_INDEX_READY_TIMEOUT_SECONDS",
        _DEFAULT_PINECONE_READY_TIMEOUT_SECONDS,
    )
    deadline = time.monotonic() + timeout_seconds
    latest_description: Any = None

    while time.monotonic() < deadline:
        latest_description = pc.describe_index(name=index_name)
        if _is_index_ready(latest_description):
            return latest_description
        time.sleep(2)

    raise TimeoutError(f"Pinecone index '{index_name}' was not ready within {timeout_seconds} seconds.")


def _ensure_index_exists(pc: Any, index_name: str) -> None:
    from pinecone import ServerlessSpec

    if pc.has_index(index_name):
        _wait_for_index_ready(pc, index_name)
        return

    dimension = _resolve_index_dimension()
    cloud = _read_optional_env("PINECONE_CLOUD", _DEFAULT_PINECONE_CLOUD)
    region = _read_optional_env("PINECONE_REGION", _DEFAULT_PINECONE_REGION)
    metric = _read_optional_env("PINECONE_INDEX_METRIC", _DEFAULT_PINECONE_METRIC)
    deletion_protection = _read_optional_env("PINECONE_DELETION_PROTECTION", "disabled")

    logger.info(
        "pinecone_retriever: Creating Pinecone index '%s' with dimension=%d cloud=%s region=%s metric=%s.",
        index_name,
        dimension,
        cloud,
        region,
        metric,
    )
    pc.create_index(
        name=index_name,
        dimension=dimension,
        metric=metric,
        spec=ServerlessSpec(cloud=cloud, region=region),
        deletion_protection=deletion_protection,
    )
    _wait_for_index_ready(pc, index_name)


def _iter_search_hits(response: Any) -> list[Any]:
    if isinstance(response, dict):
        result = response.get("result", {})
        hits = result.get("hits", [])
    else:
        result = getattr(response, "result", None)
        if result is None and hasattr(response, "to_dict"):
            result = response.to_dict().get("result", {})
        if isinstance(result, dict):
            hits = result.get("hits", [])
        else:
            hits = getattr(result, "hits", [])
    return list(hits or [])


def _hit_fields(hit: Any) -> dict[str, Any]:
    if isinstance(hit, dict):
        fields = hit.get("fields", {})
    else:
        fields = getattr(hit, "fields", None)
        if fields is None and hasattr(hit, "to_dict"):
            fields = hit.to_dict().get("fields", {})

    if isinstance(fields, dict):
        return fields
    if hasattr(fields, "to_dict"):
        return fields.to_dict()
    return dict(fields or {})


def _hit_value(hit: Any, key: str) -> Any:
    if isinstance(hit, dict):
        return hit.get(key)
    value = getattr(hit, key, None)
    if value is None and hasattr(hit, "to_dict"):
        return hit.to_dict().get(key)
    return value


def _sanitize_metadata_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_sanitize_metadata_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_metadata_value(item) for key, item in value.items()}
    return str(value)


class _IntegratedPineconeRetriever:
    def __init__(self, index: Any, namespace: str, top_k: int, input_field: str, text_field: str) -> None:
        self.index = index
        self.namespace = namespace
        self.top_k = top_k
        self.input_field = input_field
        self.text_field = text_field

    def invoke(self, query: str) -> list[Document]:
        response = self.index.search(
            namespace=self.namespace,
            query={
                "inputs": {self.input_field: query},
                "top_k": self.top_k,
            },
            fields=["*"],
        )
        documents: list[Document] = []
        for hit in _iter_search_hits(response):
            fields = _hit_fields(hit)
            page_content = str(fields.get(self.text_field, "")).strip()
            if not page_content:
                continue

            metadata = {key: value for key, value in fields.items() if key != self.text_field}
            record_id = _hit_value(hit, "_id")
            score = _hit_value(hit, "_score")
            if record_id is not None:
                metadata["record_id"] = str(record_id)
            if score is not None:
                metadata["score"] = float(score)

            documents.append(Document(page_content=page_content, metadata=metadata))
        return documents


def get_pinecone_vector_store(
    namespace: str,
    embedding_model: str | None = None,
):
    """Return a PineconeVectorStore for the requested namespace."""
    if _get_integrated_text_field():
        raise RuntimeError(
            "The configured Pinecone index uses integrated embeddings; vector-store access is not used."
        )

    from langchain_pinecone import PineconeVectorStore

    return PineconeVectorStore(
        index=_get_index(),
        embedding=_get_embeddings(embedding_model),
        namespace=namespace,
    )


def get_pinecone_retriever(
    namespace: str,
    top_k: int | None = None,
    embedding_model: str | None = None,
):
    """Return a LangChain retriever scoped to a Pinecone namespace."""
    k = top_k if top_k is not None else _read_int_env("RAG_TOP_K", _DEFAULT_RAG_TOP_K)
    text_field = _get_integrated_text_field()
    input_field = _get_integrated_input_field()
    if text_field and input_field:
        retriever = _IntegratedPineconeRetriever(
            index=_get_index(),
            namespace=namespace,
            top_k=k,
            input_field=input_field,
            text_field=text_field,
        )
        logger.debug(
            "get_pinecone_retriever: namespace=%s top_k=%d using integrated fields input=%s text=%s",
            namespace,
            k,
            input_field,
            text_field,
        )
        return retriever

    vector_store = get_pinecone_vector_store(namespace=namespace, embedding_model=embedding_model)
    retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )
    logger.debug("get_pinecone_retriever: namespace=%s top_k=%d", namespace, k)
    return retriever


def upsert_documents_to_namespace(
    namespace: str,
    documents: list[Document],
    *,
    ids: Optional[list[str]] = None,
    embedding_model: str | None = None,
) -> list[str]:
    """Upsert LangChain documents into a Pinecone namespace."""
    text_field = _get_integrated_text_field()
    if text_field:
        record_ids = ids or [str(index) for index in range(len(documents))]
        if len(record_ids) != len(documents):
            raise ValueError("Document ID count must match the number of documents.")

        index = _get_index()
        inserted_ids: list[str] = []
        batch_size = 96
        for batch_start in range(0, len(documents), batch_size):
            batch_docs = documents[batch_start : batch_start + batch_size]
            batch_ids = record_ids[batch_start : batch_start + batch_size]
            records: list[dict[str, Any]] = []
            for doc_id, document in zip(batch_ids, batch_docs, strict=True):
                record: dict[str, Any] = {
                    "_id": doc_id,
                    text_field: document.page_content,
                }
                for key, value in document.metadata.items():
                    if key == text_field:
                        continue
                    record[str(key)] = _sanitize_metadata_value(value)
                records.append(record)
            index.upsert_records(namespace=namespace, records=records)
            inserted_ids.extend(batch_ids)

        logger.info(
            "upsert_documents_to_namespace: Upserted %d document chunk(s) to namespace '%s' via integrated embeddings.",
            len(inserted_ids),
            namespace,
        )
        return inserted_ids

    vector_store = get_pinecone_vector_store(namespace=namespace, embedding_model=embedding_model)
    inserted_ids = vector_store.add_documents(documents=documents, ids=ids)
    logger.info(
        "upsert_documents_to_namespace: Upserted %d document chunk(s) to namespace '%s'.",
        len(inserted_ids),
        namespace,
    )
    return inserted_ids


def clear_namespace(namespace: str) -> None:
    """Delete all vectors from a Pinecone namespace."""
    index = _get_index()
    try:
        index.delete(delete_all=True, namespace=namespace)
    except Exception as exc:
        if exc.__class__.__name__ == "NotFoundException":
            logger.info("clear_namespace: Namespace '%s' does not exist yet; skipping clear.", namespace)
            return
        raise
    logger.info("clear_namespace: Cleared namespace '%s'.", namespace)
