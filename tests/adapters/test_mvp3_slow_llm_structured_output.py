from __future__ import annotations

import http.client
from pathlib import Path
import random
import socket
import time
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.event_harness import FakeRealAdapterEventHarness
from voice_agent.adapters.slow_llm_contract import SlowLLMStructuredOutputContract
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


SPEC_PATH = Path("docs/specs/mvp3-acceptance-scenarios.md")
SLOW_LLM_OUTPUT_EVENT_NAME = "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED"


def test_mvp3_slow_llm_structured_output_spec_names_slice6_contract() -> None:
    slow_llm_section = SPEC_PATH.read_text(encoding="utf-8").split(
        "## Scenario MVP3-SLOW-LLM-STRUCTURED-001",
        maxsplit=1,
    )[1].split("## Scenario", maxsplit=1)[0]

    for required_text in (
        "Slow LLM structured output and validation failure handling",
        "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED",
        "validated normalized output/ref metadata",
        "output_mode=real|fallback|degraded",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "Invalid output does not silently pass downstream",
        "Retry/failure/degraded path is event-visible",
        "Replay uses recorded refs only",
        "No provider-specific schema leakage into SlowTask",
    ):
        assert required_text in slow_llm_section


def test_slow_llm_contract_emits_validated_normalized_refs_for_slowtask_without_provider_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = _start_mvp3_slow_llm_contract_session()
    evidence_reviewed = _append_planning_slowtask_chain(startup.journal)
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    blocked_calls = _block_provider_runtime(monkeypatch)

    contract = SlowLLMStructuredOutputContract(
        boundary=boundary,
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    )

    emission = contract.emit_structured_output(
        event_id="evt_mvp3_slice6_slow_llm_output",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_slice6_001",
        slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/output-001",
        structured_output_ref="structured-output://synthetic/mvp3/slice6/output-001",
        validation_result_ref="validation://synthetic/mvp3/slice6/output-001",
        resolved_arguments_ref="resolved-arguments://synthetic/mvp3/slice6/output-001",
        provenance_ref="provenance://synthetic/mvp3/slice6/output-001",
    )
    arguments_resolved = startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp3_slice6_slow_llm_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(emission.structured_output_event["event_id"]),
        created_monotonic_ms=211,
        created_wall_clock_ms=1700000000211,
        trace_redaction_level="metadata_only",
        task_id=str(evidence_reviewed["task_id"]),
        plan_version=int(evidence_reviewed["plan_version"]),
        task_event_seq=int(evidence_reviewed["task_event_seq"]) + 1,
        resolved_arguments_ref="resolved-arguments://synthetic/mvp3/slice6/output-001",
        provenance_ref="provenance://synthetic/mvp3/slice6/output-001",
    )

    events = startup.journal.events()
    emitted = events[-2:]
    slow_llm = emission.structured_output_event

    assert [event["event_name"] for event in emitted] == [
        SLOW_LLM_OUTPUT_EVENT_NAME,
        "ARGUMENTS_RESOLVED",
    ]
    assert slow_llm == emitted[0]
    assert arguments_resolved == emitted[1]
    assert [event["event_seq"] for event in emitted] == [8, 9]
    assert slow_llm["adapter_callback_seq"] == 1
    assert slow_llm["adapter_id"] == "mvp3_slow_llm"
    assert slow_llm["adapter_type"] == "slow_llm"
    assert slow_llm["adapter_request_id"] == "adapter_request_mvp3_slow_llm_slice6_001"
    assert slow_llm["task_id"] == evidence_reviewed["task_id"]
    assert slow_llm["plan_version"] == evidence_reviewed["plan_version"]
    assert slow_llm["task_event_seq"] == evidence_reviewed["task_event_seq"]
    assert slow_llm["schema_name"] == "voice_agent.slowtask.structured_output.v1"
    assert slow_llm["normalization_status"] == "normalized"
    assert slow_llm["slow_llm_output_ref"] == "slow-llm-output://synthetic/mvp3/slice6/output-001"
    assert slow_llm["structured_output_ref"] == "structured-output://synthetic/mvp3/slice6/output-001"
    assert slow_llm["validation_result_ref"] == "validation://synthetic/mvp3/slice6/output-001"
    assert slow_llm["resolved_arguments_ref"] == arguments_resolved["resolved_arguments_ref"]
    assert slow_llm["provenance_ref"] == arguments_resolved["provenance_ref"]
    assert slow_llm["output_mode"] == "real"
    assert "provider_response" not in slow_llm
    assert "provider_schema" not in slow_llm
    assert "raw_structured_output" not in slow_llm

    assert all(validate_event_envelope(event) == event for event in emitted)
    assert _forbidden_payload_terms_are_absent(events)

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": events,
        }
    )

    assert replay_result.result_status == "passed"
    assert replay_result.adapter_health_state.output_event_modes[slow_llm["event_id"]] == "real"
    assert replay_result.slowtask_state.tasks["task_mvp3_slice6"].resolved_arguments_refs == (
        "resolved-arguments://synthetic/mvp3/slice6/output-001",
    )
    assert {
        "event_id": slow_llm["event_id"],
        "field": "structured_output_ref",
        "ref": "structured-output://synthetic/mvp3/slice6/output-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert {
        "event_id": slow_llm["event_id"],
        "field": "validation_result_ref",
        "ref": "validation://synthetic/mvp3/slice6/output-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert blocked_calls == []


def test_invalid_slow_llm_structured_output_emits_validation_failed_and_cannot_feed_slowtask() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_invalid_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_invalid",
    )
    contract = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    )

    validation_failed = contract.emit_output_validation_failed(
        event_id="evt_mvp3_slice6_slow_llm_validation_failed",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_invalid_001",
        failure_reasons=("missing_required_field: resolved_arguments_ref",),
    )
    startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp3_slice6_slow_llm_invalid_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(validation_failed["event_id"]),
        created_monotonic_ms=211,
        created_wall_clock_ms=1700000000211,
        trace_redaction_level="metadata_only",
        task_id=str(evidence_reviewed["task_id"]),
        plan_version=int(evidence_reviewed["plan_version"]),
        task_event_seq=int(evidence_reviewed["task_event_seq"]) + 1,
        resolved_arguments_ref="resolved-arguments://synthetic/mvp3/slice6/invalid-output",
        provenance_ref="provenance://synthetic/mvp3/slice6/invalid-output",
    )

    events = startup.journal.events()

    assert validation_failed["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    assert validation_failed["adapter_type"] == "slow_llm"
    assert validation_failed["schema_name"] == "voice_agent.slowtask.structured_output.v1"
    assert validation_failed["failure_reasons"] == ["missing_required_field: resolved_arguments_ref"]
    assert SLOW_LLM_OUTPUT_EVENT_NAME not in [event["event_name"] for event in events]

    with pytest.raises(ReplayValidationError, match="validation failed output"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


def test_replay_rejects_indirect_arguments_resolved_after_slow_llm_validation_failure() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_indirect_invalid_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_indirect_invalid",
    )
    SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    ).emit_output_validation_failed(
        event_id="evt_mvp3_slice6_slow_llm_indirect_validation_failed",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_indirect_invalid_001",
        failure_reasons=("missing_required_field: resolved_arguments_ref",),
    )
    startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp3_slice6_slow_llm_indirect_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=211,
        created_wall_clock_ms=1700000000211,
        trace_redaction_level="metadata_only",
        task_id=str(evidence_reviewed["task_id"]),
        plan_version=int(evidence_reviewed["plan_version"]),
        task_event_seq=int(evidence_reviewed["task_event_seq"]) + 1,
        resolved_arguments_ref="resolved-arguments://synthetic/mvp3/slice6/indirect-invalid",
        provenance_ref="provenance://synthetic/mvp3/slice6/indirect-invalid",
    )

    with pytest.raises(ReplayValidationError, match="validated Slow LLM structured output"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": startup.journal.events(),
            }
        )


def test_slow_llm_retry_failure_and_degraded_paths_are_replay_visible() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_failure_paths_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_failure_paths",
    )
    harness = FakeRealAdapterEventHarness(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        adapter_type="slow_llm",
        output_mode="degraded",
    )

    retrying = harness.emit_request_retrying(
        event_id="evt_mvp3_slice6_slow_llm_retrying",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        adapter_request_id="adapter_request_mvp3_slow_llm_retry_001",
        retry_count=1,
        retry_reason="synthetic_retryable_timeout",
        timeout_ms=500,
    )
    failed = harness.emit_request_failed(
        event_id="evt_mvp3_slice6_slow_llm_failed",
        caused_by_event_id=str(retrying["event_id"]),
        created_monotonic_ms=211,
        created_wall_clock_ms=1700000000211,
        adapter_request_id="adapter_request_mvp3_slow_llm_retry_001",
        failure_reason="synthetic_final_failure",
        retryable=False,
        timeout_ms=500,
    )
    degraded = harness.emit_output_degraded(
        event_id="evt_mvp3_slice6_slow_llm_degraded",
        caused_by_event_id=str(failed["event_id"]),
        created_monotonic_ms=212,
        created_wall_clock_ms=1700000000212,
        adapter_request_id="adapter_request_mvp3_slow_llm_retry_001",
        degraded_reason="fallback_after_final_failure",
        fallback_adapter_id="mvp3_slow_llm_fallback",
    )

    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    adapter = result.adapter_health_state.adapters["mvp3_slow_llm"]
    assert adapter.retry_count == 1
    assert adapter.failure_count == 1
    assert adapter.latest_degradation_reason == "fallback_after_final_failure"
    assert [event["event_name"] for event in (retrying, failed, degraded)] == [
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
    ]


def test_replay_accepts_delayed_slow_llm_callback_bound_to_prior_slowtask_event() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_delayed_callback_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_delayed_callback",
    )
    waiting = _append_waiting_for_slot_after_evidence(
        startup.journal,
        evidence_reviewed=evidence_reviewed,
        event_id="evt_mvp3_slice6_slow_llm_delayed_callback_waiting",
    )
    emission = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    ).emit_structured_output(
        event_id="evt_mvp3_slice6_slow_llm_delayed_callback_output",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_delayed_callback_001",
        slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/delayed-callback",
        structured_output_ref="structured-output://synthetic/mvp3/slice6/delayed-callback",
        validation_result_ref="validation://synthetic/mvp3/slice6/delayed-callback",
    )

    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert result.result_status == "passed"
    assert waiting["task_event_seq"] > emission.structured_output_event["task_event_seq"]
    assert result.adapter_health_state.output_event_modes[emission.structured_output_event["event_id"]] == "real"


def test_replay_rejects_provider_specific_slow_llm_payload_leaking_downstream() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_provider_payload_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_provider_payload",
    )
    emission = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    ).emit_structured_output(
        event_id="evt_mvp3_slice6_slow_llm_provider_payload_output",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_provider_payload_001",
        slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/provider-payload",
        structured_output_ref="structured-output://synthetic/mvp3/slice6/provider-payload",
        validation_result_ref="validation://synthetic/mvp3/slice6/provider-payload",
    )
    events = startup.journal.events()
    slow_llm = next(event for event in events if event["event_id"] == emission.structured_output_event["event_id"])
    slow_llm["provider_response"] = {"choices": [{"message": "provider-specific"}]}

    with pytest.raises(ReplayValidationError, match="provider-specific"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


def test_slow_llm_contract_rejects_non_request_slowtask_binding_event() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_non_request_binding_contract_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_non_request_binding_contract",
    )
    arguments_resolved = startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp3_slice6_slow_llm_non_request_binding_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        trace_redaction_level="metadata_only",
        task_id=str(evidence_reviewed["task_id"]),
        plan_version=int(evidence_reviewed["plan_version"]),
        task_event_seq=int(evidence_reviewed["task_event_seq"]) + 1,
        resolved_arguments_ref="resolved-arguments://synthetic/mvp3/slice6/non-request-binding",
        provenance_ref="provenance://synthetic/mvp3/slice6/non-request-binding",
    )
    contract = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    )

    with pytest.raises(ValueError, match="allowed SlowTask event"):
        contract.emit_structured_output(
            event_id="evt_mvp3_slice6_slow_llm_non_request_binding_output",
            caused_by_event_id=str(arguments_resolved["event_id"]),
            created_monotonic_ms=211,
            created_wall_clock_ms=1700000000211,
            slowtask_event=arguments_resolved,
            adapter_request_id="adapter_request_mvp3_slow_llm_non_request_binding_001",
            slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/non-request-binding",
            structured_output_ref="structured-output://synthetic/mvp3/slice6/non-request-binding",
            validation_result_ref="validation://synthetic/mvp3/slice6/non-request-binding",
        )


def test_slow_llm_contract_rejects_adapter_event_as_binding_event() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_adapter_bound_contract_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_adapter_bound_contract",
    )
    contract = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    )
    first_output = contract.emit_structured_output(
        event_id="evt_mvp3_slice6_slow_llm_adapter_bound_contract_first",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_adapter_bound_contract_001",
        slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/adapter-bound-contract-first",
        structured_output_ref="structured-output://synthetic/mvp3/slice6/adapter-bound-contract-first",
        validation_result_ref="validation://synthetic/mvp3/slice6/adapter-bound-contract-first",
    ).structured_output_event

    with pytest.raises(ValueError, match="allowed SlowTask event"):
        contract.emit_structured_output(
            event_id="evt_mvp3_slice6_slow_llm_adapter_bound_contract_second",
            caused_by_event_id=str(first_output["event_id"]),
            created_monotonic_ms=211,
            created_wall_clock_ms=1700000000211,
            slowtask_event=first_output,
            adapter_request_id="adapter_request_mvp3_slow_llm_adapter_bound_contract_002",
            slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/adapter-bound-contract-second",
            structured_output_ref="structured-output://synthetic/mvp3/slice6/adapter-bound-contract-second",
            validation_result_ref="validation://synthetic/mvp3/slice6/adapter-bound-contract-second",
        )


def test_slow_llm_contract_rejects_credential_like_validation_failure_reasons() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_credential_failure_reason_contract_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_credential_failure_reason_contract",
    )
    contract = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    )

    with pytest.raises(ValueError, match="credential-like"):
        contract.emit_output_validation_failed(
            event_id="evt_mvp3_slice6_slow_llm_credential_failure_reason_contract_failed",
            caused_by_event_id=str(evidence_reviewed["event_id"]),
            created_monotonic_ms=210,
            created_wall_clock_ms=1700000000210,
            slowtask_event=evidence_reviewed,
            adapter_request_id="adapter_request_mvp3_slow_llm_credential_failure_reason_contract_001",
            failure_reasons=("provider echoed api_key=synthetic",),
        )


def test_replay_rejects_credential_like_imported_slow_llm_validation_failure_reasons() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_credential_failure_reason_replay_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_credential_failure_reason_replay",
    )
    failed = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    ).emit_output_validation_failed(
        event_id="evt_mvp3_slice6_slow_llm_credential_failure_reason_replay_failed",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_credential_failure_reason_replay_001",
        failure_reasons=("missing_required_field: resolved_arguments_ref",),
    )
    events = startup.journal.events()
    imported_failed = next(event for event in events if event["event_id"] == failed["event_id"])
    imported_failed["failure_reasons"] = ["provider echoed api_key=synthetic"]

    with pytest.raises(ReplayValidationError, match="credential-like"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


def test_replay_rejects_adapter_caused_slow_llm_output_chain() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_adapter_bound_replay_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_adapter_bound_replay",
    )
    first_output = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    ).emit_structured_output(
        event_id="evt_mvp3_slice6_slow_llm_adapter_bound_replay_first",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_adapter_bound_replay_001",
        slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/adapter-bound-replay-first",
        structured_output_ref="structured-output://synthetic/mvp3/slice6/adapter-bound-replay-first",
        validation_result_ref="validation://synthetic/mvp3/slice6/adapter-bound-replay-first",
    ).structured_output_event
    startup.journal.append(
        event_name=SLOW_LLM_OUTPUT_EVENT_NAME,
        event_id="evt_mvp3_slice6_slow_llm_adapter_bound_replay_second",
        source_module="slow_llm_adapter",
        caused_by_event_id=str(first_output["event_id"]),
        created_monotonic_ms=211,
        created_wall_clock_ms=1700000000211,
        trace_redaction_level="metadata_only",
        adapter_id="mvp3_slow_llm",
        adapter_type="slow_llm",
        adapter_request_id="adapter_request_mvp3_slow_llm_adapter_bound_replay_002",
        task_id=str(first_output["task_id"]),
        plan_version=int(first_output["plan_version"]),
        task_event_seq=int(first_output["task_event_seq"]),
        schema_name="voice_agent.slowtask.structured_output.v1",
        normalization_status="normalized",
        slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/adapter-bound-replay-second",
        structured_output_ref="structured-output://synthetic/mvp3/slice6/adapter-bound-replay-second",
        validation_result_ref="validation://synthetic/mvp3/slice6/adapter-bound-replay-second",
        output_mode="real",
    )

    with pytest.raises(ReplayValidationError, match="task_event_seq|prior allowed SlowTask event"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": startup.journal.events(),
            }
        )


def test_replay_rejects_nested_provider_specific_slow_llm_payload() -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id="sess_mvp3_slice6_slow_llm_nested_provider_payload_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice6_slow_llm_nested_provider_payload",
    )
    emission = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode="real",
    ).emit_structured_output(
        event_id="evt_mvp3_slice6_slow_llm_nested_provider_payload_output",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id="adapter_request_mvp3_slow_llm_nested_provider_payload_001",
        slow_llm_output_ref="slow-llm-output://synthetic/mvp3/slice6/nested-provider-payload",
        structured_output_ref="structured-output://synthetic/mvp3/slice6/nested-provider-payload",
        validation_result_ref="validation://synthetic/mvp3/slice6/nested-provider-payload",
    )
    events = startup.journal.events()
    slow_llm = next(event for event in events if event["event_id"] == emission.structured_output_event["event_id"])
    slow_llm["adapter_metadata"] = {
        "provider_response": {"choices": [{"message": "provider-specific"}]},
    }

    with pytest.raises(ReplayValidationError, match="provider-specific"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


@pytest.mark.parametrize("output_mode", ("real", "fallback", "degraded"))
def test_slow_llm_contract_accepts_explicit_real_fallback_or_degraded_output_modes(
    output_mode: str,
) -> None:
    startup = _start_mvp3_slow_llm_contract_session(
        session_id=f"sess_mvp3_slice6_slow_llm_{output_mode}_synthetic"
    )
    evidence_reviewed = _append_planning_slowtask_chain(
        startup.journal,
        event_id_prefix=f"evt_mvp3_slice6_slow_llm_{output_mode}",
    )
    contract = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_slow_llm",
        output_mode=output_mode,
    )

    emission = contract.emit_structured_output(
        event_id=f"evt_mvp3_slice6_slow_llm_output_{output_mode}",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        slowtask_event=evidence_reviewed,
        adapter_request_id=f"adapter_request_mvp3_slow_llm_{output_mode}_001",
        slow_llm_output_ref=f"slow-llm-output://synthetic/mvp3/slice6/{output_mode}",
        structured_output_ref=f"structured-output://synthetic/mvp3/slice6/{output_mode}",
        validation_result_ref=f"validation://synthetic/mvp3/slice6/{output_mode}",
    )

    assert emission.structured_output_event["event_name"] == SLOW_LLM_OUTPUT_EVENT_NAME
    assert emission.structured_output_event["output_mode"] == output_mode
    assert emission.structured_output_event["normalization_status"] == "normalized"


def _start_mvp3_slow_llm_contract_session(
    *,
    session_id: str = "sess_mvp3_slice6_slow_llm_synthetic",
) -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_mvp3_slice6_slow_llm_synthetic",
        runtime_config_ref="config://synthetic/mvp3/slice6-slow-llm-contract",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/slice6-slow-llm-contract",
            capability_version="mvp3.contract.v1",
        ),
        capabilities=valid_mvp3_real_profiles(),
    )


def _append_planning_slowtask_chain(
    journal: object,
    *,
    event_id_prefix: str = "evt_mvp3_slice6_slow_llm",
) -> dict[str, object]:
    snapshot_event_id = str(journal.events()[1]["event_id"])
    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id=f"{event_id_prefix}_created",
        source_module="slowtask_runtime",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=120,
        created_wall_clock_ms=1700000000120,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice6",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp3/slice6/slow-llm",
        source_evidence_refs=["evidence://synthetic/mvp3/slice6/initial"],
    )
    state_created = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"{event_id_prefix}_state_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=121,
        created_wall_clock_ms=1700000000121,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice6",
        plan_version=1,
        task_event_seq=2,
        from_state="CREATED",
        to_state="CREATED",
        reason="created_snapshot",
    )
    planning_started = journal.append(
        event_name="PLANNING_STARTED",
        event_id=f"{event_id_prefix}_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=str(state_created["event_id"]),
        created_monotonic_ms=122,
        created_wall_clock_ms=1700000000122,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice6",
        plan_version=1,
        task_event_seq=3,
        planning_reason="initial_goal_accepted",
    )
    state_planning = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"{event_id_prefix}_state_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning_started["event_id"]),
        created_monotonic_ms=123,
        created_wall_clock_ms=1700000000123,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice6",
        plan_version=1,
        task_event_seq=4,
        from_state="CREATED",
        to_state="PLANNING",
        reason="initial_planning_started",
    )
    return journal.append(
        event_name="EVIDENCE_REVIEWED",
        event_id=f"{event_id_prefix}_evidence_reviewed",
        source_module="slowtask_runtime",
        caused_by_event_id=str(state_planning["event_id"]),
        created_monotonic_ms=124,
        created_wall_clock_ms=1700000000124,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice6",
        plan_version=1,
        task_event_seq=5,
        evidence_refs=["evidence://synthetic/mvp3/slice6/initial"],
        review_result="requires_slow_llm_structured_output",
    )


def _append_waiting_for_slot_after_evidence(
    journal: object,
    *,
    evidence_reviewed: dict[str, object],
    event_id: str,
) -> dict[str, object]:
    return journal.append(
        event_name="WAITING_FOR_SLOT",
        event_id=event_id,
        source_module="slowtask_runtime",
        caused_by_event_id=str(evidence_reviewed["event_id"]),
        created_monotonic_ms=125,
        created_wall_clock_ms=1700000000125,
        trace_redaction_level="metadata_only",
        task_id=str(evidence_reviewed["task_id"]),
        plan_version=int(evidence_reviewed["plan_version"]),
        task_event_seq=int(evidence_reviewed["task_event_seq"]) + 1,
        missing_fields=["destination"],
    )


def _github_allowed_replay_manifest() -> dict[str, object]:
    return {
        "manifest_schema_version": "1.0",
        "replay_id": "replay_mvp3_slice6_slow_llm_contract_synthetic",
        "source_trace_ref": "fixture://mvp3/slice6-slow-llm-contract",
        "replay_mode": "deterministic",
        "event_schema_version_range": ["1.0"],
        "fixture_domain": "GITHUB_ALLOWED",
        "generated_from": "hand_written_minimal",
        "contains_raw_audio": False,
        "contains_raw_trace": False,
        "contains_real_user_input": False,
        "contains_secrets": False,
        "contains_unredacted_tool_result": False,
        "contains_large_raw_web_content": False,
        "allowed_re_eval_components": [],
    }


def _block_provider_runtime(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    blocked_calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        blocked_calls.append((args, kwargs))
        raise AssertionError("Slow LLM contract and replay must not call provider runtime")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_called)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    monkeypatch.setattr(time, "time", fail_if_called)
    monkeypatch.setattr(time, "monotonic", fail_if_called)
    monkeypatch.setattr(random, "random", fail_if_called)
    return blocked_calls


def _forbidden_payload_terms_are_absent(events: list[dict[str, object]]) -> bool:
    rendered = repr(events)
    forbidden_terms = (
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_structured_output",
        "provider_response",
        "provider_schema",
        "authorization",
        "credential",
        "api_key",
        "token",
    )
    return all(term not in rendered.lower() for term in forbidden_terms)
