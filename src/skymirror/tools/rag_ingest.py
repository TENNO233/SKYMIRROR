"""
rag_ingest.py - Ingest local corpus files into Pinecone namespaces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document

from skymirror.tools.pinecone_retriever import clear_namespace, upsert_documents_to_namespace

logger = logging.getLogger(__name__)

load_dotenv()

_DEFAULT_SOURCE_DIR = Path("data/rag")
_DEFAULT_CHUNK_SIZE = 1200
_DEFAULT_CHUNK_OVERLAP = 200
_DEFAULT_NAMESPACES = (
    "traffic-regulations",
    "safety-incidents",
    "road-conditions",
)
_SUPPORTED_SUFFIXES = {".txt", ".md", ".json"}


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError("chunk overlap must be smaller than chunk size")

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _load_file_text(path: Path) -> str:
    if path.suffix == ".json":
        return json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=True, indent=2)
    return path.read_text(encoding="utf-8")


def _build_documents_for_file(
    path: Path,
    namespace: str,
    *,
    chunk_size: int,
    overlap: int,
) -> tuple[list[Document], list[str]]:
    text = _load_file_text(path)
    chunks = _chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    documents: list[Document] = []
    ids: list[str] = []

    for index, chunk in enumerate(chunks):
        source_key = f"{namespace}:{path.as_posix()}:{index}"
        doc_id = hashlib.sha1(source_key.encode("utf-8")).hexdigest()
        documents.append(
            Document(
                page_content=chunk,
                metadata={
                    "source_path": str(path),
                    "filename": path.name,
                    "title": path.stem,
                    "namespace": namespace,
                    "chunk_index": index,
                },
            )
        )
        ids.append(doc_id)

    return documents, ids


def ingest_namespace(
    namespace: str,
    source_dir: Path,
    *,
    chunk_size: int,
    overlap: int,
    clear_first: bool = False,
) -> int:
    files = sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES
    )
    if not files:
        logger.warning("ingest_namespace: No supported files found in %s", source_dir)
        return 0

    if clear_first:
        clear_namespace(namespace)

    all_documents: list[Document] = []
    all_ids: list[str] = []
    for file_path in files:
        documents, ids = _build_documents_for_file(
            file_path,
            namespace,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        all_documents.extend(documents)
        all_ids.extend(ids)

    upsert_documents_to_namespace(namespace, all_documents, ids=all_ids)
    return len(all_documents)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="skymirror-rag-ingest",
        description="Ingest local RAG corpora into Pinecone namespaces.",
    )
    parser.add_argument(
        "--source-dir",
        default=str(_DEFAULT_SOURCE_DIR),
        help="Base source directory or a namespace-specific directory.",
    )
    parser.add_argument(
        "--namespace",
        choices=_DEFAULT_NAMESPACES,
        help="Namespace to ingest. If omitted, ingest all known namespace subdirectories.",
    )
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Delete all existing vectors in the target namespace(s) before ingesting.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    args = _parse_args()
    chunk_size = _read_int_env("RAG_CHUNK_SIZE", _DEFAULT_CHUNK_SIZE)
    overlap = _read_int_env("RAG_CHUNK_OVERLAP", _DEFAULT_CHUNK_OVERLAP)

    source_dir = Path(args.source_dir).resolve()
    if args.namespace:
        namespace_dir = source_dir / args.namespace
        target_dir = namespace_dir if namespace_dir.exists() else source_dir
        total = ingest_namespace(
            args.namespace,
            target_dir,
            chunk_size=chunk_size,
            overlap=overlap,
            clear_first=args.clear_first,
        )
        logger.info("Ingested %d chunk(s) into namespace '%s'.", total, args.namespace)
        return

    total = 0
    for namespace in _DEFAULT_NAMESPACES:
        namespace_dir = source_dir / namespace
        total += ingest_namespace(
            namespace,
            namespace_dir,
            chunk_size=chunk_size,
            overlap=overlap,
            clear_first=args.clear_first,
        )
    logger.info("Ingested %d total chunk(s) across default namespaces.", total)


if __name__ == "__main__":
    main()
