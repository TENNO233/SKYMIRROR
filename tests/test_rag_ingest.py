from __future__ import annotations

from pathlib import Path

from skymirror.tools import rag_ingest


def test_chunk_text_uses_overlap() -> None:
    chunks = rag_ingest._chunk_text("abcdefghij", chunk_size=6, overlap=2)
    assert chunks == ["abcdef", "efghij"]


def test_build_documents_for_file(tmp_path: Path) -> None:
    file_path = tmp_path / "rules.md"
    file_path.write_text("Rule one.\n\nRule two.", encoding="utf-8")

    documents, ids = rag_ingest._build_documents_for_file(
        file_path,
        "traffic-regulations",
        chunk_size=20,
        overlap=5,
    )

    assert len(documents) >= 1
    assert len(documents) == len(ids)
    assert documents[0].metadata["namespace"] == "traffic-regulations"
    assert documents[0].metadata["filename"] == "rules.md"
