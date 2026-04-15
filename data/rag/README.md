# RAG Corpus Layout

Place reference files under one namespace directory per expert:

- `data/rag/traffic-regulations/`
- `data/rag/safety-incidents/`
- `data/rag/road-conditions/`

Supported file types:

- `.txt`
- `.md`
- `.json`

Example ingest:

```powershell
uv run skymirror-rag-ingest --clear-first
```

Bootstrap the curated Singapore corpus first:

```powershell
uv run skymirror-rag-bootstrap-sg --ingest --clear-first
```
