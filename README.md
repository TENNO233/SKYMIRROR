## SKYMIRROR

SKYMIRROR is a LangGraph-based traffic-camera analysis pipeline for Singapore road-monitoring workflows.

### Model setup

The current runtime uses one OpenAI vision model and one OpenAI validator:

- `OPENAI_VLM_MODEL=gpt-5.4`
- `OPENAI_VALIDATOR_MODEL=gpt-5.4`
- `OPENAI_GUARDRAIL_MODEL=gpt-5.4-mini`
- `OPENAI_EXPERT_MODEL=gpt-5.4-mini`
- `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`

The validator no longer fuses outputs from multiple providers. It now cross-checks the single VLM report against the original image and returns a corrected, conservative scene summary for downstream routing.

### Environment

Copy `.env.example` to `.env`, fill in your real keys, and run the app with `python -m skymirror.main` or the dashboard with `python -m skymirror.dashboard.server`.
