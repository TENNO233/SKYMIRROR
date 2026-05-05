# SKYMIRROR

SKYMIRROR is a multi-agent traffic image analysis system designed for Singapore road-monitoring scenarios. It is not just a traffic-camera image recognition script. It is an end-to-end operational analysis pipeline that turns live camera frames into structured scene understanding, expert review, alerts, audit logs, dashboard state, and daily reports.

The project is built with `LangGraph + OpenAI + Pinecone + Python runtime`, and is suitable for:

- intelligent event detection in urban road-monitoring workflows
- multi-agent orchestration and explainable AI pipeline design
- operational traffic monitoring and incident triage prototypes
- AI agent systems with governance, auditability, and reporting built in

## Why SKYMIRROR

Traditional vision projects usually stop at answering "what is in the image." SKYMIRROR focuses on a harder operational question: "does this frame justify action, and why?"

Its goal is to turn a traffic camera image into a traceable, explainable, archived, and reviewable event pipeline:

1. Fetch a live traffic camera frame
2. Apply an image guardrail before analysis
3. Use a vision model to produce structured scene understanding
4. Run a validator that re-checks the first-pass output against the original image
5. Let an orchestrator decide which domain experts should engage
6. Use experts with rules and RAG context to assess order, safety, and environmental issues
7. Merge expert outputs into alerts and persist them
8. Publish runtime state to the dashboard
9. Aggregate `RunRecord` logs into a daily Markdown report

## Core Features

- `LangGraph` dual-workflow orchestration
  One unified graph supports both the live `frame` workflow and the offline `report` workflow.
- Image guardrail
  Frames go through local preflight checks and model-level safety classification before entering the main analysis path.
- Single-VLM plus validator architecture
  A single OpenAI vision model produces structured output, and a validator cross-checks it conservatively against the source image.
- Expert routing and parallel analysis
  The orchestrator activates `order`, `safety`, and `environment` experts based on scene signals.
- Pinecone-backed RAG
  Experts can retrieve traffic regulations, road-condition references, and safety-incident context.
- Auditable runtime records
  Every processed frame produces a `RunRecord` JSONL entry for replay, reporting, and evaluation.
- Operations dashboard
  A lightweight web dashboard shows runtime status, latest frames, alerts, and report history.
- Daily reporting
  Historical runtime logs are summarized into Markdown daily reports.
- Governance and AI safety controls
  The repository includes runtime policy files, release thresholds, and an AI risk register.

## System Architecture

At a high level, SKYMIRROR has five layers:

1. Input layer
   Fetches live frames from Singapore traffic camera APIs or reads local test images.
2. Orchestration layer
   LangGraph manages state, branching, expert fan-out, and convergence.
3. Retrieval layer
   Pinecone and local corpora provide domain references to expert agents.
4. Output and presentation layer
   Produces alerts, logs, reports, and dashboard payloads.
5. Governance and evaluation layer
   Enforces runtime policy, release thresholds, and offline checks.

The main graph is structured roughly like this:

```text
START
  -> workflow_router
     -> frame
        -> image_guardrail
        -> vlm_agent
        -> validator_agent
        -> orchestrator_agent
           -> order_expert
           -> safety_expert
           -> environment_expert
        -> orchestrator_agent
        -> alert_manager
        -> END

     -> report
        -> report_generator
        -> END
```

## Project Workflows

### 1. `frame` workflow

Processes one live traffic frame and outputs:

- structured scene understanding
- expert analysis results
- alert objects
- `RunRecord` audit entries
- latest dashboard runtime state

### 2. `report` workflow

Processes one day of historical `RunRecord` data and outputs:

- a daily Markdown report
- timeline-style operational summaries for review

## Repository Layout

```text
SKYMIRROR/
├── src/skymirror/
│   ├── agents/                 # guardrail, VLM, validator, experts, alert manager
│   ├── graph/                  # LangGraph graph, state, routing edges
│   ├── tools/                  # camera fetcher, Pinecone, governance, reports, alerts
│   ├── dashboard/              # HTTP dashboard backend + static frontend
│   └── main.py                 # daemon entrypoint
├── data/
│   ├── rag/                    # local RAG corpora
│   ├── sources/                # camera reference data and official source cache
│   ├── frames/                 # fetched runtime frames
│   ├── oa_log/                 # RunRecord JSONL audit logs
│   ├── alerts/                 # alert outputs
│   └── reports/                # daily report outputs
├── governance/                 # policies, release thresholds, AI risk register
├── scripts/                    # offline evaluation scripts
├── tests/                      # unit and regression tests
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── langgraph.json
```

## Tech Stack

- Python `3.11+`
- LangGraph / LangChain
- OpenAI models
- Pinecone
- APScheduler
- built-in Python HTTP server for the dashboard backend
- Docker / Docker Compose

## Model Setup

The current default model setup is:

- `OPENAI_VLM_MODEL=gpt-5.4`
- `OPENAI_VALIDATOR_MODEL=gpt-5.4`
- `OPENAI_GUARDRAIL_MODEL=gpt-5.4-mini`
- `OPENAI_EXPERT_MODEL=gpt-5.4-mini`
- `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`

The current validator design uses a single-VLM output followed by a direct image re-check. It no longer fuses results from multiple providers, which keeps the pipeline easier to govern, trace, and debug.

## Quick Start

### 1. Install dependencies

Using `uv` is recommended:

```bash
uv sync --dev
```

If you prefer `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment variables

Copy the template:

```bash
cp .env.example .env
```

At minimum, fill in:

```dotenv
OPENAI_API_KEY=...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=skymirror-rag
PINECONE_INDEX_HOST=...
```

### 3. Initialize the RAG corpus

Before the first full deployment, ingest the built-in Singapore transport corpus into Pinecone:

```bash
uv run skymirror-rag-bootstrap-sg --ingest --clear-first
```

If your local `data/rag/` directory is already prepared and you only want to ingest it:

```bash
uv run skymirror-rag-ingest --clear-first
```

### 4. Run a single smoke test cycle

```bash
uv run python -m skymirror.main --once
```

To test with a local image:

```bash
uv run python -m skymirror.main --image /absolute/path/to/frame.jpg
```

### 5. Start the dashboard

```bash
uv run python -m skymirror.dashboard.server --host 0.0.0.0 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

## Runtime Modes

`src/skymirror/main.py` supports four entry modes:

```bash
python -m skymirror.main
python -m skymirror.main --once
python -m skymirror.main --image /path/to/file.jpg
python -m skymirror.main --report
```

Behavior:

- `python -m skymirror.main`
  Runs the long-lived daemon and continuously polls cameras
- `--once`
  Fetches and processes one live cycle, then exits
- `--image`
  Runs the `frame` workflow on a local image
- `--report`
  Generates a daily report from `data/oa_log/`

In daemon mode, APScheduler is started and triggers daily report generation at `00:05 UTC`.

## Key Environment Variables

See the full template in [`.env.example`](.env.example).

The most important variables are:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API credential |
| `OPENAI_VLM_MODEL` | vision model |
| `OPENAI_GUARDRAIL_MODEL` | image guardrail model |
| `OPENAI_VALIDATOR_MODEL` | validator model |
| `OPENAI_EXPERT_MODEL` | expert model |
| `OPENAI_EMBEDDING_MODEL` | embedding model |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_INDEX_NAME` | Pinecone index name |
| `PINECONE_INDEX_HOST` | Pinecone index host |
| `PROCESSING_INTERVAL_SECONDS` | polling interval, default `20` |
| `TARGET_CAMERA_IDS` | comma-separated multi-camera list |
| `TARGET_CAMERA_ID` | single camera ID |
| `FRAMES_DIR` | frame output directory |
| `OA_LOG_DIR` | audit log directory |
| `KEEP_FRAME_HISTORY` | whether to retain historical frames |
| `LANGSMITH_TRACING` | enable tracing |
| `LTA_API_KEY` | LTA DataMall corroboration key |

Camera resolution priority is:

1. `TARGET_CAMERA_IDS`
2. the first two cameras in `data/sources/traffic_camera_reference.json`
3. `TARGET_CAMERA_ID`
4. default `4798`

## Running with Docker

### Build

```bash
docker build -t skymirror:latest .
```

### Run daemon only

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data/oa_log:/app/data/oa_log" \
  -v "$(pwd)/data/reports:/app/data/reports" \
  -v "$(pwd)/data/alerts:/app/data/alerts" \
  -v "$(pwd)/data/frames:/app/data/frames" \
  skymirror:latest
```

### Run the full stack with Docker Compose

The repository already includes [`docker-compose.yml`](docker-compose.yml):

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f daemon
docker compose logs -f dashboard
```

The Compose dashboard is exposed at:

```text
http://127.0.0.1:8000
```

Notes:

- the local dashboard default port is `8787`
- the Compose dashboard port is `8000`
- `docker compose up` does not automatically ingest the RAG corpus into Pinecone, so initial ingest must still be done first

## Data Outputs

The most important runtime output directories are:

- `data/frames/`
  fetched traffic camera frames
- `data/oa_log/`
  `RunRecord` JSONL entries for each run
- `data/alerts/`
  alert payloads and dispatch records
- `data/reports/`
  daily report outputs
- `data/dashboard/`
  dashboard runtime state files

`data/oa_log/` is especially important because it is the source of truth for:

- dashboard status and history views
- daily report generation
- offline runtime governance evaluation

## Governance, Evaluation, and Safety

SKYMIRROR is designed not only to run, but to be reviewable, governable, and testable.

The repository includes:

- [`governance/policy.yaml`](governance/policy.yaml)
  runtime policy configuration
- [`governance/release_thresholds.yaml`](governance/release_thresholds.yaml)
  offline release thresholds
- [`governance/AI_SECURITY_RISK_REGISTER.md`](governance/AI_SECURITY_RISK_REGISTER.md)
  AI risk register

Offline evaluation script:

```bash
uv run python -m scripts.evaluate_runtime
```

It validates:

- RunRecord schema validity rate
- guardrail regression rate
- validator regression rate
- expert routing regression rate
- alert evidence completeness rate
- report generation success rate

To evaluate generated alerts separately, you can also run:

```bash
uv run python -m scripts.evaluate_alerts
```

## Testing

Run the full test suite:

```bash
uv run pytest
```

Coverage areas include:

- graph routing and state convergence
- VLM, validator, and expert behavior
- alert manager outputs
- dashboard payload aggregation
- RAG ingest and Pinecone retrieval
- prompt injection and policy enforcement
- runtime governance and report generation

## LangGraph Studio

If you want to inspect the unified graph in Studio, use [`langgraph.json`](langgraph.json).

Graph entrypoint:

```text
src/skymirror/graph/graph.py:app
```

Because the repository uses a `src/` layout, it is recommended to keep:

```dotenv
PYTHONPATH=src
```

## Deployment Notes

For longer-running deployments, the recommended baseline is:

1. inject secrets through `.env` or a secret manager, never bake them into images
2. persist `data/oa_log`, `data/reports`, `data/alerts`, and `data/frames`
3. configure log collection and rotation
4. place the dashboard behind a reverse proxy and access control
5. start with a conservative `PROCESSING_INTERVAL_SECONDS` such as `20`
6. keep LangSmith tracing enabled for debugging and incident review

## Common Issues

### The dashboard opens but shows no useful data

Check:

- whether the daemon is actually running
- whether OpenAI and Pinecone variables are correctly configured in `.env`
- whether `data/oa_log/` is receiving new records
- whether the dashboard is reading the same mounted data directories that the daemon writes to

### Expert stages fail with Pinecone-related errors

Usually this means one of the following:

- `PINECONE_API_KEY` is missing
- `PINECONE_INDEX_NAME` is missing
- `PINECONE_INDEX_HOST` is missing
- the target namespace has not been ingested yet

### Why does starting the dashboard also start a backend process locally

The local dashboard includes a runtime manager that can automatically start a backend daemon for single-machine demos and development. In Compose mode, the dashboard and daemon run as separate services.

## Documentation Map

If you want more detail, continue with:

- [`docs/DEPLOYMENT_README.md`](docs/DEPLOYMENT_README.md)
  detailed deployment guide
- [`docs/SKYMIRROR_PROJECT_LOGIC.md`](docs/SKYMIRROR_PROJECT_LOGIC.md)
  project logic and code responsibility walkthrough
- [`data/rag/README.md`](data/rag/README.md)
  RAG corpus layout and ingest notes

## License

MIT
