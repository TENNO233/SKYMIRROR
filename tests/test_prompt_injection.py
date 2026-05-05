"""
test_prompt_injection.py – LLMSecOps compliance: structural prompt-injection defenses.

These tests verify the defense-in-depth layers that protect the SKYMIRROR pipeline
WITHOUT requiring live LLM API calls.  They cover:

  1. Input source validation  – blocks unauthorized image origins (SSRF vectors)
  2. RAG namespace isolation  – prevents cross-namespace data leakage
  3. Model allowlisting       – prevents unauthorized model substitution
  4. Input length limits      – prevents context-overflow injection
  5. Audit log schema         – prevents tampered / injected run records
  6. Policy integrity         – verifies governance config cannot be silently bypassed
"""

from __future__ import annotations

import pytest

from skymirror.tools.governance import (
    allowed_image_domains,
    allowed_rag_namespaces,
    load_policy,
    model_allowed,
    validate_image_source,
    validate_input_length,
    validate_rag_namespace,
)
from skymirror.tools.run_records import build_run_record, validate_run_record

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLEAN_METADATA = {
    "models": {},
    "prompts": {},
    "policies": {},
    "retrieval": {},
    "external_calls": {},
}


# ===========================================================================
# 1. Input Source Validation
#    Threat: attacker crafts a URL pointing to an image that contains embedded
#    instructions ("Ignore previous instructions…"), causing the VLM to
#    exfiltrate data or alter its output.
# ===========================================================================


class TestImageSourceValidation:
    def test_gov_sg_api_domain_passes(self):
        validate_image_source("https://api.data.gov.sg/v1/transport/traffic-images")

    def test_lta_datamall_domain_passes(self):
        validate_image_source("https://datamall2.mytransport.sg/ltaodataservice/Traffic-Imagesv2")

    def test_onemap_domain_passes(self):
        validate_image_source("https://www.onemap.gov.sg/map.png")

    def test_unauthorized_arbitrary_domain_blocked(self):
        with pytest.raises(ValueError, match="not allowed by policy"):
            validate_image_source("https://attacker.com/evil_frame.jpg")

    def test_lookalike_suffix_attack_blocked(self):
        """api.data.gov.sg.evil.com must NOT pass (hostname suffix hijack)."""
        with pytest.raises(ValueError, match="not allowed by policy"):
            validate_image_source("https://api.data.gov.sg.evil.com/frame.jpg")

    def test_subdomain_of_unknown_domain_blocked(self):
        """traffic-cam.evil.com should not pass even with gov.sg in the path."""
        with pytest.raises(ValueError, match="not allowed by policy"):
            validate_image_source("https://evil.com/gov.sg/frame.jpg")

    def test_local_file_bypasses_remote_check(self):
        """Local paths are allowed (allow_local_files=true); no exception raised."""
        validate_image_source("/data/frames/4798_latest.jpg")

    def test_allowlist_is_non_empty(self):
        """An empty allowlist would allow any domain — must never happen."""
        domains = allowed_image_domains()
        assert len(domains) >= 3, "Allowlist must contain at least the LTA domains"


# ===========================================================================
# 2. RAG Namespace Isolation
#    Threat: attacker poisons a query to retrieve documents from a different
#    namespace (e.g. internal-prompts, system-config) via namespace injection.
# ===========================================================================


class TestRagNamespaceIsolation:
    @pytest.mark.parametrize(
        "ns",
        [
            "traffic-regulations",
            "safety-incidents",
            "road-conditions",
        ],
    )
    def test_allowed_namespaces_pass(self, ns: str):
        validate_rag_namespace(ns)

    @pytest.mark.parametrize(
        "ns",
        [
            "internal-secrets",
            "system-prompts",
            "admin",
            "",
            "   ",
            "traffic-regulations; DROP TABLE vectors--",
        ],
    )
    def test_disallowed_namespaces_blocked(self, ns: str):
        with pytest.raises(ValueError, match="not allowed by policy"):
            validate_rag_namespace(ns)

    def test_namespace_list_is_exactly_three(self):
        ns = allowed_rag_namespaces()
        assert ns == {"traffic-regulations", "safety-incidents", "road-conditions"}


# ===========================================================================
# 3. Model Allowlisting
#    Threat: supply-chain attack replaces the model name in env vars with a
#    fine-tuned or backdoored variant (ft:gpt-5.4:org:malicious:…).
# ===========================================================================


class TestModelAllowlisting:
    @pytest.mark.parametrize(
        "model,capability",
        [
            ("gpt-5.4", "vlm"),
            ("gpt-5.4", "validator"),
            ("gpt-5.4-mini", "guardrail"),
            ("gpt-5.4-mini", "expert"),
            ("gpt-5.4-mini", "orchestrator"),
            ("gpt-5.4", "orchestrator"),
        ],
    )
    def test_allowlisted_models_pass(self, model: str, capability: str):
        assert model_allowed(model, capability=capability) is True

    @pytest.mark.parametrize(
        "model,capability",
        [
            ("gpt-3.5-turbo", "vlm"),
            ("gpt-4o", "guardrail"),
            ("claude-3-haiku", "expert"),
            ("ft:gpt-5.4:org:backdoor:abc123", "vlm"),  # fine-tuned backdoor
            ("gpt-5.4-mini", "vlm"),  # wrong capability tier
            ("", "vlm"),
        ],
    )
    def test_disallowed_models_blocked(self, model: str, capability: str):
        assert model_allowed(model, capability=capability) is False

    def test_allowlist_non_empty_per_capability(self):
        policy = load_policy()
        for cap, models in policy.get("allowed_models", {}).items():
            assert models, f"Model allowlist for '{cap}' must not be empty"


# ===========================================================================
# 4. Input Length Limits
#    Threat: attacker embeds thousands of "ignore previous instructions" tokens
#    in an image caption or history context to overflow the LLM context window
#    and hijack downstream reasoning.
# ===========================================================================


class TestInputLengthLimits:
    def test_short_validated_text_passes(self):
        validate_input_length("Normal intersection, moderate traffic.", field="validated_text")

    def test_validated_text_at_limit_passes(self):
        validate_input_length("A" * 4000, field="validated_text")

    def test_validated_text_over_limit_blocked(self):
        with pytest.raises(ValueError, match="exceeds policy limit"):
            validate_input_length("A" * 4001, field="validated_text")

    def test_expert_input_over_limit_blocked(self):
        with pytest.raises(ValueError, match="exceeds policy limit"):
            validate_input_length("X" * 6001, field="expert_input")

    def test_alert_message_over_limit_blocked(self):
        with pytest.raises(ValueError, match="exceeds policy limit"):
            validate_input_length("M" * 1001, field="alert_message")

    def test_history_context_over_limit_blocked(self):
        with pytest.raises(ValueError, match="exceeds policy limit"):
            validate_input_length("H" * 8001, field="history_context")

    def test_unknown_field_does_not_raise(self):
        """Unknown fields have no limit — must not cause a crash."""
        validate_input_length("A" * 99999, field="unknown_field")


# ===========================================================================
# 5. Audit Log Schema Integrity
#    Threat: compromised pipeline stage injects a malformed or extra-field
#    RunRecord to silently suppress audit evidence or spoof a clean status.
# ===========================================================================


class TestRunRecordSchemaIntegrity:
    def test_valid_clean_record_accepted(self):
        record = build_run_record(
            run_id="run_safe_001",
            workflow_mode="frame",
            camera_id="4798",
            image_path="frame.jpg",
            status="clean",
            metadata=_CLEAN_METADATA,
        )
        assert record["status"] == "clean"

    @pytest.mark.parametrize(
        "bad_status",
        [
            "pwned",
            "ok",
            "pass",
            "TRUE",
            "1",
            "",
            "clean\x00",
        ],
    )
    def test_invalid_status_blocked(self, bad_status: str):
        with pytest.raises(ValueError):
            build_run_record(
                run_id="run_inject",
                workflow_mode="frame",
                camera_id="4798",
                image_path="frame.jpg",
                status=bad_status,
                metadata=_CLEAN_METADATA,
            )

    def test_missing_run_id_blocked(self):
        record = {
            "timestamp": "2026-04-19T00:00:00Z",
            "workflow_mode": "frame",
            "camera_id": "4798",
            "image_path": "frame.jpg",
            "status": "clean",
            "guardrail_result": {},
            "validated_signals": {},
            "expert_results": {},
            "metadata": _CLEAN_METADATA,
            "active_experts": [],
            "alerts": [],
        }
        with pytest.raises(ValueError, match="run_id"):
            validate_run_record(record)

    def test_non_dict_metadata_blocked(self):
        record = {
            "run_id": "run_bad_meta",
            "timestamp": "2026-04-19T00:00:00Z",
            "workflow_mode": "frame",
            "camera_id": "4798",
            "image_path": "frame.jpg",
            "status": "clean",
            "guardrail_result": {},
            "validated_signals": {},
            "expert_results": {},
            "metadata": "injected_string",  # must be dict
            "active_experts": [],
            "alerts": [],
        }
        with pytest.raises(ValueError, match="metadata"):
            validate_run_record(record)

    def test_alerted_status_accepted(self):
        record = build_run_record(
            run_id="run_alerted_001",
            workflow_mode="frame",
            camera_id="4798",
            image_path="frame.jpg",
            status="alerted",
            alerts=[{"alert_id": "a1", "domain": "traffic"}],
            metadata=_CLEAN_METADATA,
        )
        assert record["status"] == "alerted"

    def test_blocked_status_accepted(self):
        record = build_run_record(
            run_id="run_blocked_001",
            workflow_mode="frame",
            camera_id="4798",
            image_path="frame.jpg",
            status="blocked",
            guardrail_result={"allowed": False, "reason": "unsafe content"},
            metadata=_CLEAN_METADATA,
        )
        assert record["guardrail_result"]["allowed"] is False


# ===========================================================================
# 6. Policy Integrity
#    Threat: misconfiguration (empty allowlist, wrong version, missing section)
#    silently disables a security control.
# ===========================================================================


class TestPolicyIntegrity:
    def test_policy_version_is_pinned_string(self):
        policy = load_policy()
        version = policy.get("version", "")
        assert isinstance(version, str) and version, "Policy version must be a non-empty string"

    def test_policy_version_matches_expected(self):
        policy = load_policy()
        assert policy["version"] == "2026-04-19.v1"

    def test_prompt_security_section_present(self):
        policy = load_policy()
        ps = policy.get("prompt_security")
        assert isinstance(ps, dict) and ps, "prompt_security section must exist and be non-empty"

    def test_prompt_security_limits_are_positive(self):
        policy = load_policy()
        for key, value in (policy.get("prompt_security") or {}).items():
            assert isinstance(value, int) and value > 0, (
                f"prompt_security.{key} must be a positive integer, got {value!r}"
            )

    def test_telemetry_tracing_enabled_by_default(self):
        policy = load_policy()
        telemetry = policy.get("telemetry", {})
        assert telemetry.get("enable_tracing") is True, (
            "Tracing must be enabled by default for audit compliance"
        )

    def test_all_runtime_timeouts_are_set(self):
        policy = load_policy()
        rt = policy.get("runtime_controls", {})
        for key in (
            "openai_timeout_seconds",
            "pinecone_timeout_seconds",
            "camera_fetch_timeout_seconds",
        ):
            assert key in rt and rt[key] > 0, f"runtime_controls.{key} must be a positive number"
