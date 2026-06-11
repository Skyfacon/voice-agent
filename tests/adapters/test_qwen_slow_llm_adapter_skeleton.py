from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from voice_agent.adapters.capabilities import validate_capability_matrix
from voice_agent.adapters.qwen_slow_llm_skeleton import (
    QWEN_SLOW_LLM_MAX_REPAIR_ATTEMPTS,
    QWEN_SLOW_LLM_REQUIRED_LIVE_EVAL_APPROVAL_FIELDS,
    QwenSlowLLMCredentialHandle,
    QwenSlowLLMAdapterSkeletonError,
    QwenSlowLLMRequestBinding,
    build_qwen_slow_llm_capability,
    build_qwen_slow_llm_request_payload,
    classify_qwen_slow_llm_arrival,
    decide_qwen_slow_llm_repair,
    emit_qwen_slow_llm_output_degraded,
    emit_qwen_slow_llm_provider_text_result,
    emit_qwen_slow_llm_request_failed,
    emit_qwen_slow_llm_request_retrying,
    emit_qwen_slow_llm_structured_output,
    parse_qwen_slow_llm_evidence_json,
    request_qwen_slow_llm_provider_text,
    validate_qwen_slow_llm_credential_handle,
    validate_qwen_slow_llm_evidence,
    validate_qwen_slow_llm_live_eval_approval_packet,
)
from voice_agent.adapters.slow_llm_contract import SlowLLMStructuredOutputContract
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


def test_qwen_slow_llm_capability_is_real_metadata_without_provider_probe() -> None:
    capability = build_qwen_slow_llm_capability(model_alias="qwen3.6-plus")

    matrix = capability.to_dict()

    assert validate_capability_matrix(matrix) == matrix
    assert matrix["adapter_id"] == "slow_llm_qwen_mvp3_skeleton"
    assert matrix["adapter_type"] == "slow_llm"
    assert matrix["provider"] == "dashscope_qwen"
    assert matrix["model_name"] == "Qwen3.6 Plus"
    assert matrix["endpoint"] == "endpoint://dashscope/qwen/slow-llm"
    assert matrix["config_ref"] == "config://runtime/qwen-slow-llm"
    assert matrix["deployment_mode"] == "remote_api"
    assert matrix["output_mode"] == "real"
    assert matrix["supports_structured_json"] is True
    assert matrix["supports_tool_calling"] is True
    assert matrix["supports_streaming_output"] is False
    assert matrix["mocked"] is False
    assert matrix["mock_profile_ref"] == ""
    assert matrix["target_architecture_validation"] is True
    assert "supports_audio_input" in matrix["unsupported_capabilities"]


def test_request_payload_keeps_web_evidence_untrusted_and_provider_output_evidence_only() -> None:
    binding = _binding()

    payload = build_qwen_slow_llm_request_payload(
        binding=binding,
        task_evidence_ref="evidence://synthetic/qwen-slow-llm/001",
        untrusted_web_evidence_refs=("web://synthetic/qwen-slow-llm/001",),
    )

    assert payload["request_metadata"] == {
        "task_id": "task_qwen_001",
        "plan_version": 2,
        "observed_plan_version": 2,
        "interpreted_against_plan_version": 2,
        "task_event_seq": 7,
        "adapter_request_id": "adapter-request-qwen-001",
        "causal_refs": ["event:evidence-reviewed-qwen-001"],
    }
    assert payload["task_evidence"] == {
        "ref": "evidence://synthetic/qwen-slow-llm/001",
        "raw_content_included": False,
    }
    assert payload["untrusted_web_evidence"] == {
        "refs": ["web://synthetic/qwen-slow-llm/001"],
        "label": "UNTRUSTED_WEB_EVIDENCE",
        "instruction_authority": "none",
    }
    assert payload["instruction_boundary"]["provider_output_role"] == "evidence_candidate_only"
    assert payload["instruction_boundary"]["may_emit_event_journal_events"] is False
    assert "api_key" not in repr(payload).lower()
    assert "authorization" not in repr(payload).lower()
    assert "raw_provider_body" not in repr(payload).lower()


def test_parser_accepts_exactly_one_json_object_and_rejects_wrappers() -> None:
    parsed = parse_qwen_slow_llm_evidence_json(json.dumps(_valid_qwen_output()))

    assert parsed["schema_version"] == "slow_llm_qwen_evidence_v1"

    wrapped = f"```json\n{json.dumps(_valid_qwen_output())}\n```"
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="single JSON object"):
        parse_qwen_slow_llm_evidence_json(wrapped)

    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="single JSON object"):
        parse_qwen_slow_llm_evidence_json("{}{}")


def test_validator_accepts_evidence_only_output_and_rejects_ownership_claims() -> None:
    normalized = validate_qwen_slow_llm_evidence(
        _valid_qwen_output(),
        expected_binding=_binding(),
    )

    assert normalized["validation_status"] == "validated_evidence_candidate"
    assert normalized["may_advance_current_task"] is False
    assert normalized["tool_proposal"]["proposal_only"] is True
    assert normalized["tool_proposal"]["requires_slowtask_resolution"] is True

    invalid = _valid_qwen_output()
    invalid["boundary_assertions"]["no_tool_execution"] = False
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="boundary assertion"):
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())

    invalid = _valid_qwen_output()
    invalid["event_name"] = "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED"
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="forbidden ownership"):
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())

    invalid = _valid_qwen_output()
    invalid["task_binding"]["plan_version"] = 1
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="task binding"):
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())


def test_stale_comparator_classifies_arrivals_without_authorizing_progress() -> None:
    binding = _binding()

    assert (
        classify_qwen_slow_llm_arrival(
            binding,
            current_task_id="task_qwen_001",
            current_plan_version=2,
            task_is_terminal=False,
        )
        == "current_plan_reviewable_evidence"
    )
    assert (
        classify_qwen_slow_llm_arrival(
            binding,
            current_task_id="task_qwen_001",
            current_plan_version=3,
            task_is_terminal=False,
        )
        == "stale_old_plan_evidence"
    )
    assert (
        classify_qwen_slow_llm_arrival(
            binding,
            current_task_id="task_qwen_001",
            current_plan_version=2,
            task_is_terminal=True,
        )
        == "terminal_task_late_evidence"
    )
    assert (
        classify_qwen_slow_llm_arrival(
            binding,
            current_task_id="task-other",
            current_plan_version=2,
            task_is_terminal=False,
        )
        == "task_mismatch_ignored"
    )


def test_validation_failure_can_only_emit_existing_adapter_failure_event() -> None:
    invalid = _valid_qwen_output()
    del invalid["task_analysis"]

    with pytest.raises(QwenSlowLLMAdapterSkeletonError) as captured:
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())

    journal = _started_journal()
    slowtask_event = _append_slowtask_event(journal)
    event = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(journal),
        adapter_id="slow_llm_qwen_mvp3_skeleton",
        output_mode="real",
    ).emit_output_validation_failed(
        event_id="evt_qwen_slow_llm_validation_failed_001",
        caused_by_event_id=str(slowtask_event["event_id"]),
        created_monotonic_ms=200,
        created_wall_clock_ms=1700000000200,
        slowtask_event=slowtask_event,
        adapter_request_id="adapter-request-qwen-001",
        failure_reasons=captured.value.failure_reasons,
    )

    assert event["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    assert event["adapter_type"] == "slow_llm"
    assert event["schema_name"] == "voice_agent.slowtask.structured_output.v1"
    assert event["failure_reasons"] == ["missing required field: task_analysis"]
    assert "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED" not in [
        item["event_name"] for item in journal.events()
    ]


@pytest.mark.parametrize(
    "failure_category",
    ("parse_failure", "schema_failure", "boundary_assertion_failure"),
)
def test_repair_decision_allows_only_bounded_local_metadata_repairs(
    failure_category: str,
) -> None:
    decision = decide_qwen_slow_llm_repair(
        failure_category=failure_category,
        repair_attempt=1,
        failure_reasons=(f"{failure_category}: synthetic validation failure",),
    )

    metadata = decision.to_dict()

    assert QWEN_SLOW_LLM_MAX_REPAIR_ATTEMPTS == 2
    assert metadata == {
        "repairable": True,
        "repair_action": "attempt_local_bounded_repair",
        "failure_category": failure_category,
        "failure_reasons": [f"{failure_category}: synthetic validation failure"],
        "current_repair_attempt": 1,
        "next_repair_attempt": 2,
        "max_repair_attempts": 2,
        "raw_provider_body_included": False,
        "provider_call_allowed": False,
        "raw_prompt_constructed": False,
        "failure_terminal": False,
    }
    assert "provider_messages" not in repr(metadata).lower()
    assert "raw_prompt_text" not in repr(metadata).lower()
    assert metadata["raw_provider_body_included"] is False


def test_repair_decision_exhausts_at_two_attempts_without_provider_call() -> None:
    decision = decide_qwen_slow_llm_repair(
        failure_category="schema_failure",
        repair_attempt=2,
        failure_reasons=("schema_failure: missing required field",),
    )

    assert decision.to_dict() == {
        "repairable": False,
        "repair_action": "fail_closed",
        "failure_category": "schema_failure",
        "failure_reasons": ["schema_failure: missing required field"],
        "current_repair_attempt": 2,
        "next_repair_attempt": None,
        "max_repair_attempts": 2,
        "raw_provider_body_included": False,
        "provider_call_allowed": False,
        "raw_prompt_constructed": False,
        "failure_terminal": True,
    }


@pytest.mark.parametrize(
    "failure_category",
    (
        "unsafe_ref",
        "credential_like_content",
        "task_binding_mismatch",
        "old_plan_late_output",
        "terminal_task_late_output",
        "ownership_claim",
        "raw_artifact_retention",
    ),
)
def test_repair_decision_fails_closed_for_non_repairable_categories(
    failure_category: str,
) -> None:
    decision = decide_qwen_slow_llm_repair(
        failure_category=failure_category,
        repair_attempt=0,
        failure_reasons=(f"{failure_category}: synthetic failure",),
    )

    metadata = decision.to_dict()

    assert metadata["repairable"] is False
    assert metadata["repair_action"] == "fail_closed"
    assert metadata["next_repair_attempt"] is None
    assert metadata["provider_call_allowed"] is False
    assert metadata["raw_prompt_constructed"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["failure_reasons"] == [f"{failure_category}: synthetic failure"]


@pytest.mark.parametrize(
    "unsafe_value",
    (
        "raw_audio",
        "traces/session.jsonl",
        "diagnostics/piai-codex-trace.jsonl",
        "replays/local/session.fixture.json",
        "api_key=synthetic",
        "authorization=synthetic",
        "Bearer synthetic",
        "token=synthetic",
        "password=synthetic",
    ),
)
def test_validator_rejects_unsafe_payload_values_with_safe_failure_reasons(
    unsafe_value: str,
) -> None:
    invalid = _valid_qwen_output()
    invalid["task_analysis"]["summary"] = unsafe_value  # type: ignore[index]

    with pytest.raises(QwenSlowLLMAdapterSkeletonError) as captured:
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())

    failure_reasons = captured.value.failure_reasons
    assert failure_reasons
    assert all(isinstance(reason, str) and reason for reason in failure_reasons)
    assert "synthetic" not in " ".join(failure_reasons)


def test_validator_rejects_raw_provider_body_retention_key() -> None:
    invalid = _valid_qwen_output()
    invalid["validation_metadata"]["raw_provider_body"] = "redacted-but-forbidden"  # type: ignore[index]

    with pytest.raises(QwenSlowLLMAdapterSkeletonError) as captured:
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())

    assert captured.value.failure_reasons == ["payload must not retain raw provider artifacts"]


@pytest.mark.parametrize(
    "ownership_field",
    (
        "tool_result",
        "ui_patch",
        "semantic_commitment",
        "checker_verdict",
        "playback_action",
    ),
)
def test_validator_rejects_nested_forbidden_ownership_fields(
    ownership_field: str,
) -> None:
    invalid = _valid_qwen_output()
    invalid["proposed_resolved_arguments_evidence"] = {
        "nested": {
            ownership_field: {"status": "forbidden"},
        }
    }

    with pytest.raises(QwenSlowLLMAdapterSkeletonError) as captured:
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())

    assert captured.value.failure_reasons == [
        f"forbidden ownership field present: {ownership_field}"
    ]


def test_successful_qwen_evidence_helper_emits_structured_output_through_contract_only() -> None:
    journal = _started_journal()
    slowtask_event = _append_slowtask_event(journal)
    contract = SlowLLMStructuredOutputContract(
        boundary=AdapterCallbackAppendBoundary(journal),
        adapter_id="slow_llm_qwen_mvp3_skeleton",
        output_mode="real",
    )

    emission = emit_qwen_slow_llm_structured_output(
        contract=contract,
        output=_valid_qwen_output(),
        expected_binding=_binding(),
        event_id="evt_qwen_slow_llm_output_001",
        caused_by_event_id=str(slowtask_event["event_id"]),
        created_monotonic_ms=201,
        created_wall_clock_ms=1700000000201,
        slowtask_event=slowtask_event,
    )

    event = emission.structured_output_event
    metadata = emission.metadata.to_dict()

    assert event["event_name"] == "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED"
    assert event["adapter_callback_seq"] == 1
    assert event["adapter_request_id"] == "adapter-request-qwen-001"
    assert event["task_id"] == slowtask_event["task_id"]
    assert event["plan_version"] == slowtask_event["plan_version"]
    assert event["task_event_seq"] == slowtask_event["task_event_seq"]
    assert event["slow_llm_output_ref"] == metadata["slow_llm_output_ref"]
    assert event["structured_output_ref"] == metadata["structured_output_ref"]
    assert event["validation_result_ref"] == metadata["validation_result_ref"]
    assert metadata["raw_provider_body_included"] is False
    assert metadata["may_advance_current_task"] is False
    assert "raw_provider_body" not in event
    assert "provider_response" not in event
    assert "tool_result" not in repr(event)
    assert "ui_patch" not in repr(event)


def test_successful_emission_helper_does_not_emit_when_validation_fails() -> None:
    journal = _started_journal()
    slowtask_event = _append_slowtask_event(journal)
    invalid = _valid_qwen_output()
    del invalid["task_analysis"]

    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="missing required field"):
        emit_qwen_slow_llm_structured_output(
            contract=SlowLLMStructuredOutputContract(
                boundary=AdapterCallbackAppendBoundary(journal),
                adapter_id="slow_llm_qwen_mvp3_skeleton",
                output_mode="real",
            ),
            output=invalid,
            expected_binding=_binding(),
            event_id="evt_qwen_slow_llm_output_invalid_001",
            caused_by_event_id=str(slowtask_event["event_id"]),
            created_monotonic_ms=201,
            created_wall_clock_ms=1700000000201,
            slowtask_event=slowtask_event,
        )

    assert "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED" not in [
        event["event_name"] for event in journal.events()
    ]


def test_credential_handle_is_opaque_metadata_and_not_string_serializable() -> None:
    handle = QwenSlowLLMCredentialHandle(
        credential_ref="secret-ref://local/qwen-slow-llm/synthetic",
    )

    metadata = validate_qwen_slow_llm_credential_handle(handle).to_metadata()

    assert metadata == {
        "credential_ref": "secret-ref://local/qwen-slow-llm/synthetic",
        "credential_present": True,
        "secret_materialized": False,
    }
    assert "api_key" not in repr(handle).lower()
    assert "token" not in repr(handle).lower()
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="not string serializable"):
        str(handle)
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="opaque credential handle"):
        validate_qwen_slow_llm_credential_handle("api_key=synthetic")


def test_provider_client_boundary_uses_fake_transport_without_network_or_sdk_imports() -> None:
    source = Path("src/voice_agent/adapters/qwen_slow_llm_skeleton.py").read_text(
        encoding="utf-8",
    )
    imported_modules = _imported_modules(source)

    assert "dashscope" not in imported_modules
    assert "requests" not in imported_modules
    assert "urllib.request" not in imported_modules
    assert "http.client" not in imported_modules
    assert "socket" not in imported_modules
    assert "os" not in imported_modules

    transport = _FakeProviderTextTransport(json.dumps(_valid_qwen_output()))
    handle = QwenSlowLLMCredentialHandle(
        credential_ref="secret-ref://local/qwen-slow-llm/synthetic",
    )
    candidate = request_qwen_slow_llm_provider_text(
        transport=transport,
        credential_handle=handle,
        request_payload=build_qwen_slow_llm_request_payload(
            binding=_binding(),
            task_evidence_ref="evidence://synthetic/qwen-slow-llm/provider-boundary",
        ),
        adapter_request_id="adapter-request-qwen-001",
        timeout_ms=5000,
    )

    assert transport.calls == [
        {
            "adapter_request_id": "adapter-request-qwen-001",
            "credential_ref": "secret-ref://local/qwen-slow-llm/synthetic",
            "timeout_ms": 5000,
        }
    ]
    assert candidate.text.startswith("{")
    assert candidate.to_metadata() == {
        "adapter_request_id": "adapter-request-qwen-001",
        "output_mode": "real",
        "text_present": True,
        "raw_provider_body_included": False,
    }
    assert "synthetic redacted task summary" not in repr(candidate)


@pytest.mark.parametrize(
    "unsafe_field",
    (
        "raw_provider_request",
        "raw_provider_response",
        "raw_request_body",
        "raw_response_body",
        "headers",
        "authorization",
        "cookies",
        "provider_sdk_response",
    ),
)
def test_validator_rejects_provider_raw_body_and_header_retention_fields(
    unsafe_field: str,
) -> None:
    invalid = _valid_qwen_output()
    invalid["validation_metadata"][unsafe_field] = {"value": "redacted-but-forbidden"}  # type: ignore[index]

    with pytest.raises(QwenSlowLLMAdapterSkeletonError) as captured:
        validate_qwen_slow_llm_evidence(invalid, expected_binding=_binding())

    assert captured.value.failure_reasons == ["payload must not retain raw provider artifacts"]


def test_qwen_request_failure_paths_emit_existing_canonical_events_only() -> None:
    journal = _started_journal()
    slowtask_event = _append_slowtask_event(journal)
    boundary = AdapterCallbackAppendBoundary(journal)

    retrying = emit_qwen_slow_llm_request_retrying(
        boundary=boundary,
        event_id="evt_qwen_slow_llm_retrying_001",
        caused_by_event_id=str(slowtask_event["event_id"]),
        created_monotonic_ms=201,
        created_wall_clock_ms=1700000000201,
        adapter_request_id="adapter-request-qwen-001",
        retry_count=1,
        retry_reason="synthetic_retryable_timeout",
        timeout_ms=5000,
    )
    failed = emit_qwen_slow_llm_request_failed(
        boundary=boundary,
        event_id="evt_qwen_slow_llm_failed_001",
        caused_by_event_id=str(retrying["event_id"]),
        created_monotonic_ms=202,
        created_wall_clock_ms=1700000000202,
        adapter_request_id="adapter-request-qwen-001",
        failure_reason="synthetic_final_timeout",
        retryable=False,
        timeout_ms=5000,
    )
    degraded = emit_qwen_slow_llm_output_degraded(
        boundary=boundary,
        event_id="evt_qwen_slow_llm_degraded_001",
        caused_by_event_id=str(failed["event_id"]),
        created_monotonic_ms=203,
        created_wall_clock_ms=1700000000203,
        adapter_request_id="adapter-request-qwen-001",
        degraded_reason="synthetic_fallback_required",
        fallback_adapter_id="slow_llm_qwen_metadata_only_fallback",
    )

    assert [retrying["event_name"], failed["event_name"], degraded["event_name"]] == [
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
    ]
    assert [retrying["adapter_callback_seq"], failed["adapter_callback_seq"], degraded["adapter_callback_seq"]] == [
        1,
        2,
        3,
    ]
    assert all("raw_provider_body" not in event for event in (retrying, failed, degraded))


def test_provider_text_normalization_emits_success_only_after_validation() -> None:
    journal = _started_journal()
    slowtask_event = _append_slowtask_event(journal)
    result = emit_qwen_slow_llm_provider_text_result(
        contract=SlowLLMStructuredOutputContract(
            boundary=AdapterCallbackAppendBoundary(journal),
            adapter_id="slow_llm_qwen_mvp3_skeleton",
            output_mode="real",
        ),
        provider_text=json.dumps(_valid_qwen_output()),
        expected_binding=_binding(),
        success_event_id="evt_qwen_slow_llm_provider_text_output_001",
        validation_failed_event_id="evt_qwen_slow_llm_provider_text_failed_001",
        caused_by_event_id=str(slowtask_event["event_id"]),
        created_monotonic_ms=201,
        created_wall_clock_ms=1700000000201,
        slowtask_event=slowtask_event,
    )

    assert result.success is True
    assert result.structured_output_event is not None
    assert result.validation_failed_event is None
    assert result.structured_output_event["event_name"] == "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED"
    assert "provider_text" not in result.to_metadata()


def test_provider_text_normalization_emits_validation_failure_for_malformed_text() -> None:
    journal = _started_journal()
    slowtask_event = _append_slowtask_event(journal)
    result = emit_qwen_slow_llm_provider_text_result(
        contract=SlowLLMStructuredOutputContract(
            boundary=AdapterCallbackAppendBoundary(journal),
            adapter_id="slow_llm_qwen_mvp3_skeleton",
            output_mode="real",
        ),
        provider_text="not json",
        expected_binding=_binding(),
        success_event_id="evt_qwen_slow_llm_provider_text_output_invalid_001",
        validation_failed_event_id="evt_qwen_slow_llm_provider_text_failed_invalid_001",
        caused_by_event_id=str(slowtask_event["event_id"]),
        created_monotonic_ms=201,
        created_wall_clock_ms=1700000000201,
        slowtask_event=slowtask_event,
    )

    assert result.success is False
    assert result.structured_output_event is None
    assert result.validation_failed_event is not None
    assert result.validation_failed_event["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    assert "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED" not in [
        event["event_name"] for event in journal.events()
    ]


def test_live_eval_approval_packet_validation_is_provider_free_and_fail_closed() -> None:
    packet = _valid_live_eval_approval_packet()

    metadata = validate_qwen_slow_llm_live_eval_approval_packet(packet).to_dict()

    assert tuple(metadata["required_fields"]) == QWEN_SLOW_LLM_REQUIRED_LIVE_EVAL_APPROVAL_FIELDS
    assert metadata["approval_packet_complete"] is True
    assert metadata["provider_call_allowed"] is False
    assert metadata["secret_read_allowed"] is False
    assert metadata["output_storage_local_only"] is True

    missing = dict(packet)
    del missing["model_alias"]
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="missing approval field"):
        validate_qwen_slow_llm_live_eval_approval_packet(missing)

    unsafe = dict(packet)
    unsafe["credential_source"] = "api_key=synthetic"
    with pytest.raises(QwenSlowLLMAdapterSkeletonError, match="credential-like"):
        validate_qwen_slow_llm_live_eval_approval_packet(unsafe)


def _binding() -> QwenSlowLLMRequestBinding:
    return QwenSlowLLMRequestBinding(
        task_id="task_qwen_001",
        plan_version=2,
        observed_plan_version=2,
        interpreted_against_plan_version=2,
        task_event_seq=7,
        adapter_request_id="adapter-request-qwen-001",
        causal_refs=("event:evidence-reviewed-qwen-001",),
    )


def _valid_qwen_output() -> dict[str, object]:
    return {
        "schema_version": "slow_llm_qwen_evidence_v1",
        "task_binding": _binding().to_dict(),
        "task_analysis": {
            "summary": "synthetic redacted task summary",
            "intent": "find_candidate_solution",
            "confidence": "medium",
        },
        "missing_fields": [],
        "conflicting_fields": [],
        "proposed_resolved_arguments_evidence": {},
        "tool_proposal": {
            "proposal_only": True,
            "tool_name": None,
            "args_status": "none",
            "partial_args": {},
            "candidate_ready_args": {},
            "requires_slowtask_resolution": True,
        },
        "confirmation_risk_hints": [],
        "validation_metadata": {
            "output_mode": "real",
            "repair_attempt": 0,
            "web_evidence_treated_as_untrusted": True,
            "forbidden_instruction_sources_ignored": True,
        },
        "boundary_assertions": {
            "no_tool_authorization": True,
            "no_tool_execution": True,
            "no_ui_patch": True,
            "no_semantic_commitment_event": True,
            "no_checker_verdict": True,
            "no_playback_action": True,
        },
    }


def _started_journal() -> InMemoryEventJournal:
    journal = InMemoryEventJournal(
        session_id="sess_qwen_slow_llm_skeleton_synthetic",
        conversation_id="conv_qwen_slow_llm_skeleton_synthetic",
    )
    journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_qwen_slow_llm_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/qwen-slow-llm",
        capability_snapshot_ref="capability://synthetic/qwen-slow-llm",
    )
    return journal


def _append_slowtask_event(journal: InMemoryEventJournal) -> dict[str, object]:
    return journal.append(
        event_name="EVIDENCE_REVIEWED",
        event_id="evt_qwen_slow_llm_evidence_reviewed_001",
        source_module="slowtask_runtime",
        caused_by_event_id="evt_qwen_slow_llm_session_started",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        trace_redaction_level="metadata_only",
        task_id="task_qwen_001",
        plan_version=2,
        task_event_seq=7,
        evidence_refs=("evidence://synthetic/qwen-slow-llm/reviewed-001",),
        review_result="sufficient_for_slow_llm_skeleton_validation_failure",
    )


class _FakeProviderTextTransport:
    def __init__(self, provider_text: str) -> None:
        self._provider_text = provider_text
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        request_payload: dict[str, object],
        credential_handle: QwenSlowLLMCredentialHandle,
        adapter_request_id: str,
        timeout_ms: int,
    ) -> str:
        assert request_payload["task_evidence"]["raw_content_included"] is False  # type: ignore[index]
        self.calls.append(
            {
                "adapter_request_id": adapter_request_id,
                "credential_ref": credential_handle.credential_ref,
                "timeout_ms": timeout_ms,
            }
        )
        return self._provider_text


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def _valid_live_eval_approval_packet() -> dict[str, object]:
    return {
        "model_alias": "qwen-plus-synthetic-placeholder",
        "model_alias_repin_date": "2026-06-11",
        "provider_transport_allowance": "direct_http_or_sdk_requires_future_approval",
        "credential_source": "human_approved_runtime_env_script",
        "max_request_count": 3,
        "max_cost_quota": "human-approved bounded quota",
        "per_request_timeout_ms": 30000,
        "retry_budget": 1,
        "synthetic_input_set_path": "tests/fixtures/synthetic/qwen-slow-llm-inputs.jsonl",
        "output_storage_path": "diagnostics/qwen-slow-llm/live-eval",
        "redaction_policy": "metadata_only_no_raw_provider_body",
        "cleanup_policy": "delete_local_outputs_after_summary",
        "aggregate_metadata_commit_policy": "allowed_if_redacted_metadata_only",
        "forbidden_commit_artifacts_acknowledged": True,
    }
