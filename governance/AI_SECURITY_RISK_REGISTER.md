# AI Security Risk Register

Repository assessed: `SKYMIRROR`  
Assessment basis: repository contents in the local workspace as of 2026-04-20

## Scope

This register focuses on AI-specific and AI-adjacent security risks in the
current SKYMIRROR pipeline:

- traffic-camera image ingestion
- OpenAI vision / validation / expert reasoning
- RAG-backed expert context retrieval
- alert generation and external notification hooks
- runtime logging, tracing, and governance controls

## Table of Identified Risks

| ID | Risk | Where it appears in this project | Potential impact | Current controls in repo | Residual risk | Recommended mitigation strategies and security controls |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Prompt injection through camera frames or model-derived text | Image input enters `vlm_agent`, then model output is passed into `validator` and expert prompts. | Manipulated reasoning, false alerts, suppressed alerts, unsafe downstream actions. | Remote image domain allowlist in `governance/policy.yaml`; source validation in `src/skymirror/tools/governance.py`; conservative system prompts in `src/skymirror/agents/prompts.py`; validator cross-check in `src/skymirror/agents/validator.py`; prompt length caps and prompt-injection tests in `tests/test_prompt_injection.py`. | Medium | Add explicit injection-pattern detection on `validated_text` and `history_context`; quarantine suspicious frames; strip imperative phrases before expert prompting; require higher confidence or human review for high-severity alerts triggered by weak evidence. |
| R2 | SSRF / remote content pivot through image fetching | `build_image_payload()` validates the original URL, then fetches with redirects enabled. | Fetching attacker-controlled content, bypassing source policy, exposure to untrusted payloads. | Exact hostname allowlist; local image validation; media type and dimension checks in `src/skymirror/agents/vlm_agent.py`; network timeouts. | Medium | Re-validate the final redirected URL and resolved host after redirects; disable cross-domain redirects; enforce maximum response size and content-length checks before full download; log redirect chains in audit metadata. |
| R3 | Retrieval poisoning or namespace escape in RAG | Expert agents depend on Pinecone namespaces and retrieved documents. | Experts cite malicious or irrelevant content, leading to incorrect legal/safety conclusions. | Namespace allowlist in `governance/policy.yaml`; runtime namespace validation in `src/skymirror/tools/governance.py`; expert prompts require citations only from retrieved context. | Medium | Add a controlled ingestion pipeline for RAG documents with checksum/signature verification, source provenance metadata, document approval workflow, freshness policy, and periodic index integrity review. |
| R4 | Unauthorized model substitution or backdoored model configuration | Runtime model names are loaded from environment variables. | Silent downgrade, backdoored model behavior, policy bypass, inconsistent outputs. | Capability-specific allowlists in `governance/policy.yaml`; `model_allowed()` enforcement across VLM, validator, experts, and orchestrator; unit tests for allowlists. | Low to Medium | Lock deployment env vars in CI/CD; fail closed on unexpected provider/model combinations at startup; record exact provider/model/version per run; require change approval for model policy updates. |
| R5 | Sensitive data leakage through logs, traces, alerts, or report generation | Run records, LangSmith tracing, alerts, and daily reports contain model outputs and image references. | Exposure of operational details, alert content, URLs, file paths, or incident context to unauthorized staff or third parties. | `.env` is ignored in `.gitignore`; Dockerfile avoids baking secrets and runs as non-root; structured run records in `src/skymirror/tools/run_records.py`; telemetry governed by policy. | Medium | Add redaction before tracing and persistence; minimize logged image paths and external URLs; disable tracing for sensitive production environments by default; enforce retention limits and access controls for `data/oa_log`, `data/reports`, and alert outputs. |
| R6 | Over-permissive local file input | Policy currently allows local files, and `validate_image_source()` skips non-HTTP paths. | A local operator or compromised process could submit unintended files for model processing. | PIL validation rejects non-image content; file existence and image-format checks in `src/skymirror/agents/vlm_agent.py`. | Medium | Restrict production inputs to an approved frame directory; disable arbitrary local file mode outside development; validate canonical paths; separate developer CLI testing from production runtime policy. |
| R7 | Output injection or unsafe downstream notification content | Alert generation uses model-derived findings and an external `ALERT_WEBHOOK_URL`. | Downstream dashboards, chat tools, or ticketing systems may receive misleading, overlong, or unescaped content. | Structured intermediate schemas in expert and alert stages; alert message length limit is defined in policy. | Medium | Enforce output escaping/sanitization before dispatch; apply strict webhook allowlists and authentication; sign outbound alerts; cap payload size at dispatch time; add replay protection and delivery audit logs. |
| R8 | Resource exhaustion / denial of service against AI pipeline | Repeated frame ingestion, remote downloads, image parsing, LLM calls, and tracing can be expensive. | Increased cost, degraded availability, delayed incident handling, failed processing loops. | Request timeouts in governance and fetchers; image dimension bounds; prompt length limits; healthcheck in Dockerfile. | Medium | Add per-camera rate limiting, retry budgets, maximum image byte size, queue backpressure, circuit breakers for repeated model/API failures, and alerting on abnormal token or request volume. |
| R9 | Hallucinated or overconfident AI decisions causing unsafe operations | LLMs decide scene summaries, expert findings, and alert classification. | False positives, false negatives, operator distrust, or missed real incidents. | Conservative prompts; validator cross-check; hard routing filters in `src/skymirror/agents/orchestrator.py`; audit logs and daily reports for review. | Medium | Introduce confidence thresholds, human-in-the-loop review for high-severity alerts, regression evaluation on known scenarios, and periodic red-team tests for adversarial traffic scenes. |
| R10 | Dependency / supply-chain exposure in AI stack | Project relies on external model SDKs, LangChain components, and Pinecone-related packages. | Compromised dependency could alter prompts, leak data, or change retrieval/runtime behavior. | Version ranges are declared in `pyproject.toml`; Docker runs with a reduced runtime surface and non-root user. | Medium | Pin and review dependency versions for production, run dependency scanning in CI, generate SBOMs, monitor security advisories, and separate development-only packages from runtime images. |

## Mitigation Strategies and Security Controls

### Existing controls already present in the repository

1. Input source validation
   Remote image hosts are restricted by policy, and prompt-injection tests verify
   that unauthorized domains and namespace manipulation are rejected.

2. Model governance
   Each capability is tied to an allowlisted model set, reducing the risk of
   silent model substitution.

3. Defense in depth for model outputs
   The pipeline uses conservative prompts, a validator cross-check stage, and
   structured outputs instead of trusting raw free-form model text.

4. Prompt-surface reduction
   Character limits exist for validated text, expert inputs, alert messages, and
   history context to reduce context-overflow attacks.

5. Auditability
   Run records capture model, prompt, policy, and external-call metadata, which
   supports forensic review and post-incident analysis.

6. Runtime hardening
   The container runs as a non-root user and avoids baking secrets into the
   image, which lowers blast radius if the service is compromised.

### Priority controls to add next

1. Redirect-safe remote fetching
   Re-check the final destination host after redirects and reject any redirect
   chain that leaves the approved domain set.

2. Production path restrictions
   Disable arbitrary local file ingestion in production and only allow frames
   from the controlled capture directory.

3. Trace and log redaction
   Redact image paths, URLs, alert payload fields, and sensitive operator data
   before sending traces to external observability platforms.

4. RAG ingestion governance
   Treat the vector index as a controlled content supply chain: approve sources,
   verify checksums, record provenance, and review updates before indexing.

5. Human review for high-impact actions
   Require analyst confirmation for high-severity or low-confidence alerts before
   they trigger operational escalation.

6. AI security testing
   Expand the current tests with adversarial image cases, poisoned-retrieval
   fixtures, long-context abuse tests, and alert-output injection tests.

## Security Control Summary

| Control family | Current status | Notes |
| --- | --- | --- |
| Image source allowlisting | Implemented | Good baseline, but redirect validation should be strengthened. |
| RAG namespace isolation | Implemented | Prevents obvious cross-namespace access; does not yet assure document integrity. |
| Model allowlisting | Implemented | Strong control against accidental or malicious model swaps. |
| Prompt length limits | Implemented | Reduces overflow-style prompt injection but does not detect semantic attacks. |
| Structured output validation | Implemented | Lowers downstream parsing and free-form output risk. |
| Audit logging | Implemented | Useful for governance, forensics, and report generation. |
| Secret handling | Partially implemented | `.env` is ignored and Docker avoids baked secrets, but production secret rotation is not defined. |
| Trace redaction | Not evident in repo | Should be added before production use with third-party telemetry. |
| Webhook authentication and signing | Not evident in repo | Needed for trustworthy external alert delivery. |
| RAG content approval workflow | Not evident in repo | Needed to reduce poisoning risk. |
| Human-in-the-loop escalation | Partially implemented | Audit exists, but explicit approval gates are not shown in code. |

## Overall Assessment

SKYMIRROR already includes several meaningful AI security controls for a student
or prototype multi-agent system, especially around allowlisting, prompt-surface
reduction, structured outputs, and auditability. The main remaining gaps are in
production hardening around redirect-safe fetching, log/trace redaction, RAG
content governance, local file restrictions, and downstream alert-delivery
security.
