from __future__ import annotations

from pathlib import Path

from skymirror.tools import singapore_corpus


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, payloads: dict[str, bytes] | None = None) -> None:
        self.payloads = payloads or {}

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        return _FakeResponse(self.payloads[url])


def test_materialize_html_source_writes_raw_and_namespace_markdown(tmp_path: Path) -> None:
    source = singapore_corpus.CuratedSource(
        slug="sample-html",
        title="Sample HTML",
        kind="html",
        url="https://example.com/sample",
        namespaces=("traffic-regulations",),
        notes="html test",
    )
    client = _FakeClient(
        {
            "https://example.com/sample": (
                b"<html><body><main><h1>Title</h1><p>Important guidance.</p></main></body></html>"
            )
        }
    )

    result = singapore_corpus._materialize_source(
        source,
        client=client,
        raw_dir=tmp_path / "raw",
        rag_dir=tmp_path / "rag",
        force=True,
    )

    assert result["status"] == "downloaded"
    markdown_path = tmp_path / "rag" / "traffic-regulations" / "sample-html.md"
    assert markdown_path.exists()
    assert "Important guidance." in markdown_path.read_text(encoding="utf-8")


def test_materialize_note_source_writes_namespace_markdown(tmp_path: Path) -> None:
    source = singapore_corpus.CuratedSource(
        slug="note-source",
        title="Note Source",
        kind="note",
        namespaces=("road-conditions",),
        note_body="This is a generated note.",
    )

    result = singapore_corpus._materialize_source(
        source,
        client=None,
        raw_dir=tmp_path / "raw",
        rag_dir=tmp_path / "rag",
        force=False,
    )

    assert result["status"] == "rendered_note"
    markdown_path = tmp_path / "rag" / "road-conditions" / "note-source.md"
    assert markdown_path.exists()
    assert "This is a generated note." in markdown_path.read_text(encoding="utf-8")


def test_bootstrap_ingests_touched_namespaces(tmp_path: Path, monkeypatch) -> None:
    source = singapore_corpus.CuratedSource(
        slug="note-source",
        title="Note Source",
        kind="note",
        namespaces=("safety-incidents",),
        note_body="This is a generated note.",
    )
    calls: list[tuple[str, Path, bool]] = []

    def _fake_ingest(namespace: str, source_dir: Path, *, chunk_size: int, overlap: int, clear_first: bool) -> int:
        assert chunk_size == 1200
        assert overlap == 200
        calls.append((namespace, source_dir, clear_first))
        return 7

    monkeypatch.setattr(singapore_corpus, "_CURATED_SOURCES", (source,))
    monkeypatch.setattr(singapore_corpus, "ingest_namespace", _fake_ingest)
    monkeypatch.setattr(singapore_corpus.httpx, "Client", lambda **_: _FakeClient())

    manifest = singapore_corpus.bootstrap_singapore_corpus(
        download_root=tmp_path / "downloads",
        rag_root=tmp_path / "rag",
        ingest=True,
        clear_first=True,
    )

    assert manifest["ingested_chunks"] == {"safety-incidents": 7}
    assert calls == [("safety-incidents", tmp_path / "rag" / "safety-incidents", True)]
