from __future__ import annotations

import json

import pytest

from voice_agent.adapters import fast_interaction_runtime_adapter as runtime_adapter
from voice_agent.adapters.adapter_timing import AdapterTimingSnapshot
from voice_agent.adapters.fast_interaction_contract import (
    FAST_INTERACTION_SCHEMA_NAME,
    FastInteractionBinding,
    FastInteractionValidationError,
)
from voice_agent.adapters.fast_interaction_live_transport import (
    FastInteractionProviderCompletion,
    FastInteractionLiveTransportError,
)
from voice_agent.adapters.fast_interaction_runtime_adapter import (
    emit_fast_interaction_from_provider_text,
    resolve_fast_interaction_reply_candidate_ref,
    run_fast_interaction_adapter_request,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


_ALLOWED_TIMING_FIELD_NAMES = frozenset(
    {
        "fast_interaction_adapter_start_offset_ms",
        "fast_interaction_provider_request_start_offset_ms",
        "fast_interaction_provider_first_chunk_offset_ms",
        "fast_interaction_provider_full_response_offset_ms",
        "fast_interaction_adapter_event_emit_offset_ms",
        "fast_interaction_provider_ttft_ms",
        "fast_interaction_provider_full_response_ms",
        "fast_interaction_provider_generation_ms",
        "fast_interaction_stream_decode_ms",
        "fast_interaction_parse_validate_emit_ms",
        "fast_interaction_total_ms",
        "fast_interaction_timing_mode",
        "fast_interaction_ttft_available",
        "fast_interaction_ttft_source",
    }
)


def test_valid_provider_text_emits_normalized_fast_output_and_candidate_events() -> None:
    journal, turn, asr_output = _journal_with_asr_output("valid_live_payload")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_valid_live_payload",
    )
    provider_text = json.dumps(_provider_output(reply_candidate="A tiny safe story."))

    result = emit_fast_interaction_from_provider_text(
        provider_text=provider_text,
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/valid-live-payload",
        output_event_id="evt_fast_interaction_runtime_valid_output",
        candidate_event_id="evt_fast_interaction_runtime_valid_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert result.success is True
    assert result.validation_failed_event is None
    assert result.emission is not None
    output_event = result.emission.output_event
    candidate_event = result.emission.candidate_event
    assert output_event["event_name"] == "FAST_INTERACTION_OUTPUT_EMITTED"
    assert output_event["adapter_id"] == "fast_interaction_runtime_test"
    assert output_event["adapter_type"] == "fast_interaction"
    assert output_event["adapter_request_id"] == binding.adapter_request_id
    assert output_event["turn_id"] == turn["turn_id"]
    assert output_event["utterance_id"] == turn["utterance_id"]
    assert output_event["route_hint_ref"] == "route-hint://synthetic/runtime/valid-live-payload"
    assert output_event["route_prelude_ref"] == "route-prelude://synthetic/runtime/valid-live-payload"
    assert output_event["route_decision_hint"] == "FAST_ONLY"
    assert output_event["task_focus_hint"] == "FOREGROUND_CHAT"
    assert output_event["foreground_act"] == "ANSWER"
    assert output_event["final_fast_evidence_ref"] == (
        "fast-evidence://synthetic/runtime/valid-live-payload"
    )
    assert output_event["schema_name"] == FAST_INTERACTION_SCHEMA_NAME
    assert output_event["normalization_status"] == "normalized"
    assert output_event["output_mode"] == "real"
    assert output_event["risk_tags"] == ("low_risk", "no_side_effects")
    assert output_event["risk_class"] == "LOW"
    assert output_event["confidence"] == 0.91
    assert output_event["source_event_ids"] == (turn["event_id"], asr_output["event_id"])
    assert candidate_event is not None
    assert candidate_event["event_name"] == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
    assert candidate_event["candidate_id"] == "candidate_runtime-valid-live-payload"
    assert candidate_event["candidate_ref"] == (
        "foreground-candidate://synthetic/runtime/valid-live-payload"
    )
    assert (
        resolve_fast_interaction_reply_candidate_ref(str(candidate_event["candidate_ref"]))
        == "A tiny safe story."
    )
    rendered_events = repr(journal.events())
    assert "A tiny safe story." not in rendered_events
    assert provider_text not in rendered_events
    assert "runtime-secret-value-for-test-only" not in rendered_events
    assert "Bearer " not in rendered_events


@pytest.mark.parametrize("reply_candidate", ("", None))
def test_valid_provider_text_omits_candidate_event_when_reply_candidate_missing_or_empty(
    reply_candidate: str | None,
) -> None:
    journal, turn, asr_output = _journal_with_asr_output(f"no_candidate_{reply_candidate!r}")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id=f"adapter_request_fast_interaction_no_candidate_{reply_candidate!r}",
    )

    result = emit_fast_interaction_from_provider_text(
        provider_text=json.dumps(_provider_output(reply_candidate=reply_candidate)),
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix=f"runtime/no-candidate-{reply_candidate!r}",
        output_event_id=f"evt_fast_interaction_runtime_no_candidate_{reply_candidate!r}",
        candidate_event_id=f"evt_fast_interaction_runtime_no_candidate_unused_{reply_candidate!r}",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert result.success is True
    assert result.emission is not None
    assert result.emission.candidate_event is None
    assert [event["event_name"] for event in journal.events()].count(
        "FOREGROUND_REPLY_CANDIDATE_EMITTED"
    ) == 0


@pytest.mark.parametrize(
    ("provider_text", "expected_reason"),
    (
        ("```json\n{}\n```", "fenced_markdown"),
        (json.dumps({"route_hint": {}}), "missing_required_key"),
        (
            json.dumps(
                {
                    "schema_name": FAST_INTERACTION_SCHEMA_NAME,
                    "route_hint": {"router_decision_candidate": "FAST_ONLY"},
                    "route_prelude": {"summary": "low risk story request"},
                    "foreground_act": "ANSWER",
                    "reply_candidate": "Unsafe boundary.",
                    "final_fast_evidence": {"summary": "safe foreground answer"},
                    "risk_tags": ["low_risk", "no_side_effects"],
                    "risk_class": "LOW",
                    "confidence": 0.91,
                    "output_mode": "real",
                    "boundary_assertions": {
                        "candidate_is_not_semantic_commitment": True,
                        "may_authorize_tools": True,
                        "may_execute_tools": False,
                        "may_accept_confirmation": False,
                        "may_mutate_slowtask_facts": False,
                        "runtime_gate_owns_display": True,
                    },
                }
            ),
            "invalid_boundary_assertion",
        ),
    ),
)
def test_invalid_provider_text_emits_validation_failure_without_fast_events(
    provider_text: str,
    expected_reason: str,
) -> None:
    journal, turn, asr_output = _journal_with_asr_output(expected_reason)
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id=f"adapter_request_fast_interaction_{expected_reason}",
    )
    event_count_before = len(journal.events())

    result = emit_fast_interaction_from_provider_text(
        provider_text=provider_text,
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix=f"runtime/{expected_reason}",
        output_event_id=f"evt_fast_interaction_runtime_{expected_reason}_output",
        candidate_event_id=f"evt_fast_interaction_runtime_{expected_reason}_candidate",
        validation_failed_event_id=f"evt_fast_interaction_runtime_{expected_reason}_validation_failed",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert result.success is False
    assert result.emission is None
    assert result.validation_failed_event is not None
    assert result.validation_failed_event["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    assert result.validation_failed_event["adapter_type"] == "fast_interaction"
    assert result.validation_failed_event["schema_name"] == FAST_INTERACTION_SCHEMA_NAME
    assert expected_reason in result.validation_failed_event["failure_reasons"]
    assert result.validation_failed_event["output_mode"] == "degraded"
    assert len(journal.events()) == event_count_before + 1
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()[event_count_before:]
    )
    rendered_events = repr(journal.events())
    assert "```json" not in rendered_events
    assert provider_text not in rendered_events
    assert "Unsafe boundary." not in rendered_events


def test_unsafe_ref_prefix_emits_validation_failure_without_fast_events() -> None:
    journal, turn, asr_output = _journal_with_asr_output("unsafe_ref_prefix")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_unsafe_ref_prefix",
    )

    result = emit_fast_interaction_from_provider_text(
        provider_text=json.dumps(_provider_output(reply_candidate="Hidden text")),
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/provider-text/raw",
        output_event_id="evt_fast_interaction_runtime_unsafe_prefix_output",
        candidate_event_id="evt_fast_interaction_runtime_unsafe_prefix_candidate",
        validation_failed_event_id="evt_fast_interaction_runtime_unsafe_prefix_validation_failed",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert result.success is False
    assert result.validation_failed_event is not None
    assert "unsafe_ref_prefix" in result.validation_failed_event["failure_reasons"]
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )
    assert "Hidden text" not in repr(journal.events())


@pytest.mark.parametrize(
    ("field", "expected_reason"),
    (
        ("schema_name", "missing_required_key"),
        ("boundary_assertions", "missing_required_key"),
    ),
)
def test_provider_text_requires_schema_name_and_boundary_assertions(
    field: str,
    expected_reason: str,
) -> None:
    journal, turn, asr_output = _journal_with_asr_output(f"missing_{field}")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id=f"adapter_request_fast_interaction_missing_{field}",
    )
    payload = _provider_output(reply_candidate="Hidden text")
    del payload[field]

    result = emit_fast_interaction_from_provider_text(
        provider_text=json.dumps(payload),
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix=f"runtime/missing-{field}",
        output_event_id=f"evt_fast_interaction_runtime_missing_{field}_output",
        candidate_event_id=f"evt_fast_interaction_runtime_missing_{field}_candidate",
        validation_failed_event_id=f"evt_fast_interaction_runtime_missing_{field}_validation_failed",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert result.success is False
    assert result.validation_failed_event is not None
    assert expected_reason in result.validation_failed_event["failure_reasons"]
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )
    assert "Hidden text" not in repr(journal.events())


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    (
        ("route_hint", "FAST_ONLY", "invalid_object_field"),
        ("route_prelude", ["summary"], "invalid_object_field"),
        ("final_fast_evidence", "safe foreground answer", "invalid_object_field"),
        (
            "route_hint",
            {"raw": "provider_response://internal/body"},
            "unsafe_provider_field",
        ),
        (
            "route_prelude",
            {"nested": {"token": "SECRET"}},
            "unsafe_provider_field",
        ),
        (
            "final_fast_evidence",
            {"summary": "raw_prompt leaked"},
            "unsafe_provider_field",
        ),
    ),
)
def test_provider_text_requires_safe_object_route_and_evidence_fields(
    field: str,
    value: object,
    expected_reason: str,
) -> None:
    journal, turn, asr_output = _journal_with_asr_output(f"invalid_{field}_{expected_reason}")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id=f"adapter_request_fast_interaction_invalid_{field}_{expected_reason}",
    )
    payload = _provider_output(reply_candidate="Hidden text")
    payload[field] = value

    result = emit_fast_interaction_from_provider_text(
        provider_text=json.dumps(payload),
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix=f"runtime/invalid-{field}-{expected_reason}",
        output_event_id=f"evt_fast_interaction_runtime_invalid_{field}_{expected_reason}_output",
        candidate_event_id=f"evt_fast_interaction_runtime_invalid_{field}_{expected_reason}_candidate",
        validation_failed_event_id=(
            f"evt_fast_interaction_runtime_invalid_{field}_{expected_reason}_validation_failed"
        ),
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert result.success is False
    assert result.validation_failed_event is not None
    assert expected_reason in result.validation_failed_event["failure_reasons"]
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )
    rendered = repr(journal.events())
    assert "Hidden text" not in rendered
    assert "SECRET" not in rendered
    assert "provider_response" not in rendered
    assert "raw_prompt" not in rendered


@pytest.mark.parametrize(
    "reply_candidate",
    (
        "Bearer SECRET_BEARER",
        "token: SECRET_TOKEN",
        "provider-body://internal/raw",
        "provider-text://internal/raw",
        "file://Users/a123/.env",
        "/Users/a123/voice-agent/.env",
        "/private/tmp/trace.jsonl",
    ),
)
def test_provider_text_rejects_unsafe_reply_candidate_before_candidate_event(
    reply_candidate: str,
) -> None:
    journal, turn, asr_output = _journal_with_asr_output("unsafe_reply_candidate")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_unsafe_reply_candidate",
    )
    payload = _provider_output(reply_candidate=reply_candidate)

    result = emit_fast_interaction_from_provider_text(
        provider_text=json.dumps(payload),
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/unsafe-reply-candidate",
        output_event_id="evt_fast_interaction_runtime_unsafe_reply_candidate_output",
        candidate_event_id="evt_fast_interaction_runtime_unsafe_reply_candidate_candidate",
        validation_failed_event_id=(
            "evt_fast_interaction_runtime_unsafe_reply_candidate_validation_failed"
        ),
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert result.success is False
    assert result.validation_failed_event is not None
    assert "unsafe_reply_candidate" in result.validation_failed_event["failure_reasons"]
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )
    rendered = repr(journal.events())
    assert "SECRET" not in rendered
    assert "provider-body" not in rendered
    assert "provider-text" not in rendered
    assert "file://Users" not in rendered
    assert "/Users/a123" not in rendered
    assert "/private/tmp" not in rendered


def test_transport_error_emits_request_failed_event_without_fast_events() -> None:
    journal, turn, _asr_output = _journal_with_asr_output("transport_timeout")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_transport_timeout",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/transport-timeout",
    )
    transport = _RaisingTransport(
        FastInteractionLiveTransportError(
            "raw provider body runtime-secret-value-for-test-only",
            category="provider_timeout",
            failure_reasons=("provider_timeout",),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"turn_ref": "turn://synthetic/mvp63/runtime-timeout"},
        audio_bytes=b"RIFF0000WAVE",
        audio_format="wav",
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/transport-timeout",
        output_event_id="evt_fast_interaction_runtime_transport_timeout_output",
        request_failed_event_id="evt_fast_interaction_runtime_transport_timeout_failed",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=1500,
        model_alias="qwen3.5-omni-flash",
    )

    assert result.success is False
    assert result.failure_category == "provider_timeout"
    assert result.emission is None
    assert result.validation_failed_event is None
    assert result.request_failed_event is not None
    assert result.fast_interaction_latency_metadata["fast_interaction_input_mode"] == "audio_native"
    assert result.fast_interaction_latency_metadata["fast_interaction_timed_out"] is True
    failed_event = result.request_failed_event
    assert failed_event["event_name"] == "ADAPTER_REQUEST_FAILED"
    assert failed_event["adapter_type"] == "fast_interaction"
    assert failed_event["adapter_request_id"] == binding.adapter_request_id
    assert failed_event["failure_reason"] == "provider_timeout"
    assert failed_event["retryable"] is False
    assert failed_event["timeout_ms"] == 1500
    assert failed_event["output_mode"] == "degraded"
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )
    rendered = repr(journal.events())
    assert "runtime-secret-value-for-test-only" not in rendered
    assert "raw provider body" not in rendered
    assert "Bearer " not in rendered


def test_audio_native_adapter_request_emits_output_with_latency_waterfall_metadata() -> None:
    journal, turn, _asr_output = _journal_with_asr_output("audio_native_runtime")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_audio_native_runtime",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/audio-native-runtime",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="A safe tiny answer.")),
            timing=AdapterTimingSnapshot(
                adapter_start_offset_ms=0,
                provider_request_start_offset_ms=5,
                provider_first_chunk_offset_ms=25,
                provider_full_response_offset_ms=65,
                adapter_event_emit_offset_ms=70,
                provider_ttft_ms=20,
                provider_full_response_ms=60,
                provider_generation_ms=40,
                stream_decode_ms=0,
                parse_validate_emit_ms=0,
                total_ms=70,
                timing_mode="streaming",
                ttft_available=True,
                ttft_source="provider_stream_chunk",
            ),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"turn_ref": "turn://synthetic/mvp63/runtime"},
        audio_bytes=b"RIFF0000WAVE",
        audio_format="wav",
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/audio-native-runtime",
        output_event_id="evt_fast_interaction_runtime_audio_native_output",
        candidate_event_id="evt_fast_interaction_runtime_audio_native_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
    )

    assert result.success is True
    assert result.fast_interaction_latency_metadata["fast_interaction_input_mode"] == "audio_native"
    assert result.fast_interaction_latency_metadata["fast_interaction_provider_ttft_ms"] == 20
    assert result.emission is not None
    assert result.emission.output_event["input_mode"] == "audio_native"
    assert transport.audio_call_count == 1
    assert transport.text_call_count == 0


def test_audio_native_latency_metadata_drops_unsupported_timing_keys() -> None:
    journal, turn, _asr_output = _journal_with_asr_output("malicious_timing_runtime")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_malicious_timing_runtime",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/malicious-timing-runtime",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="A safe tiny answer.")),
            timing=_MaliciousTimingSnapshot(),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"turn_ref": "turn://synthetic/mvp63/malicious-timing"},
        audio_bytes=b"RIFF0000WAVE",
        audio_format="wav",
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/malicious-timing-runtime",
        output_event_id="evt_fast_interaction_runtime_malicious_timing_output",
        candidate_event_id="evt_fast_interaction_runtime_malicious_timing_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
    )

    assert result.success is True
    assert result.fast_interaction_latency_metadata is not None
    assert "fast_interaction_provider_text" not in result.fast_interaction_latency_metadata
    assert "fast_interaction_audio_raw" not in result.fast_interaction_latency_metadata
    assert "SECRET" not in repr(result.fast_interaction_latency_metadata)
    assert "RIFF" not in repr(result.fast_interaction_latency_metadata)
    assert result.emission is not None
    rendered_events = repr(journal.events())
    assert "fast_interaction_provider_text" not in rendered_events
    assert "fast_interaction_audio_raw" not in rendered_events
    assert "SECRET" not in rendered_events
    assert "RIFF" not in rendered_events


def test_timing_snapshot_exception_fails_closed_without_raw_content() -> None:
    journal, turn, _asr_output = _journal_with_asr_output("raising_timing_runtime")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_raising_timing_runtime",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/raising-timing-runtime",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="A safe tiny answer.")),
            timing=_RaisingTimingSnapshot(),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"turn_ref": "turn://synthetic/mvp63/raising-timing"},
        audio_bytes=b"RIFF0000WAVE",
        audio_format="wav",
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/raising-timing-runtime",
        output_event_id="evt_fast_interaction_runtime_raising_timing_output",
        candidate_event_id="evt_fast_interaction_runtime_raising_timing_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
    )

    assert result.success is True
    assert result.fast_interaction_latency_metadata is not None
    rendered_result = repr(result.fast_interaction_latency_metadata)
    rendered_events = repr(journal.events())
    assert "provider_response" not in rendered_result
    assert "raw_audio" not in rendered_result
    assert "SECRET" not in rendered_result
    assert "provider_response" not in rendered_events
    assert "raw_audio" not in rendered_events
    assert "SECRET" not in rendered_events


def test_audio_native_output_event_uses_measured_parse_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    journal, turn, _asr_output = _journal_with_asr_output("measured_parse_runtime")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_measured_parse_runtime",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/measured-parse-runtime",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="A safe tiny answer.")),
            timing=AdapterTimingSnapshot(
                adapter_start_offset_ms=0,
                provider_request_start_offset_ms=5,
                provider_first_chunk_offset_ms=25,
                provider_full_response_offset_ms=65,
                adapter_event_emit_offset_ms=70,
                provider_ttft_ms=20,
                provider_full_response_ms=60,
                provider_generation_ms=40,
                stream_decode_ms=0,
                parse_validate_emit_ms=0,
                total_ms=70,
                timing_mode="streaming",
                ttft_available=True,
                ttft_source="provider_stream_chunk",
            ),
        )
    )
    monotonic = _MutableMonotonic(1.0)
    original_complete = transport.complete_audio_with_timing
    original_emit = runtime_adapter._emit_prepared_provider_text_emission

    def complete_with_measured_provider_time(**kwargs: object) -> object:
        monotonic.advance(0.25)
        return original_complete(**kwargs)

    def emit_with_measured_journal_append(**kwargs: object) -> object:
        emission = original_emit(**kwargs)
        monotonic.advance(0.125)
        return emission

    monkeypatch.setattr(runtime_adapter.time, "monotonic", monotonic)
    monkeypatch.setattr(
        transport,
        "complete_audio_with_timing",
        complete_with_measured_provider_time,
    )
    monkeypatch.setattr(
        runtime_adapter,
        "_emit_prepared_provider_text_emission",
        emit_with_measured_journal_append,
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"turn_ref": "turn://synthetic/mvp63/measured-parse"},
        audio_bytes=b"RIFF0000WAVE",
        audio_format="wav",
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/measured-parse-runtime",
        output_event_id="evt_fast_interaction_runtime_measured_parse_output",
        candidate_event_id="evt_fast_interaction_runtime_measured_parse_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
    )

    assert result.success is True
    assert result.fast_interaction_latency_metadata is not None
    assert result.provider_http_ms == 250
    assert result.parse_validate_emit_ms == 125
    assert result.total_ms == 375
    assert result.fast_interaction_latency_metadata["fast_interaction_parse_validate_emit_ms"] == 125
    assert result.fast_interaction_latency_metadata["fast_interaction_total_ms"] == 375
    assert result.emission is not None
    assert result.emission.output_event["fast_interaction_parse_validate_emit_ms"] is None
    assert result.emission.output_event["fast_interaction_total_ms"] is None
    stored_output_event = next(
        event
        for event in journal.events()
        if event["event_id"] == "evt_fast_interaction_runtime_measured_parse_output"
    )
    assert stored_output_event["fast_interaction_parse_validate_emit_ms"] is None
    assert stored_output_event["fast_interaction_total_ms"] is None


def test_unknown_provider_latency_remains_null_after_failure_event_emission() -> None:
    journal, turn, _asr_output = _journal_with_asr_output("unknown_provider_latency")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_unknown_provider_latency",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/unknown-provider-latency",
    )

    result = runtime_adapter.emit_fast_interaction_provider_outcome(
        outcome=runtime_adapter.FastInteractionProviderCallOutcome(
            failure_category="provider_transport_error",
            failure_ref="failure://fast-interaction/provider-transport-error",
        ),
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/unknown-provider-latency",
        output_event_id="evt_fast_interaction_runtime_unknown_provider_latency_output",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
    )

    assert result.success is False
    assert result.provider_http_ms is None
    assert result.parse_validate_emit_ms is not None
    assert result.total_ms is None
    assert result.fast_interaction_latency_metadata is not None
    assert result.fast_interaction_latency_metadata["fast_interaction_stream_decode_ms"] is None
    assert result.fast_interaction_latency_metadata["fast_interaction_total_ms"] is None


def test_successful_output_event_waterfall_matches_result_metadata() -> None:
    journal, turn, _asr_output = _journal_with_asr_output("waterfall_match_runtime")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_waterfall_match_runtime",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/waterfall-match-runtime",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="A safe tiny answer.")),
            timing=AdapterTimingSnapshot(
                adapter_start_offset_ms=3,
                provider_request_start_offset_ms=8,
                provider_first_chunk_offset_ms=28,
                provider_full_response_offset_ms=68,
                adapter_event_emit_offset_ms=74,
                provider_ttft_ms=20,
                provider_full_response_ms=60,
                provider_generation_ms=40,
                stream_decode_ms=2,
                parse_validate_emit_ms=0,
                total_ms=71,
                timing_mode="streaming",
                ttft_available=True,
                ttft_source="provider_stream_chunk",
            ),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"turn_ref": "turn://synthetic/mvp63/waterfall-match"},
        audio_bytes=b"RIFF0000WAVE",
        audio_format="wav",
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/waterfall-match-runtime",
        output_event_id="evt_fast_interaction_runtime_waterfall_match_output",
        candidate_event_id="evt_fast_interaction_runtime_waterfall_match_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
    )

    assert result.success is True
    assert result.emission is not None
    assert result.fast_interaction_latency_metadata is not None
    event_timing_fields = {
        key: value
        for key, value in result.emission.output_event.items()
        if key in _ALLOWED_TIMING_FIELD_NAMES
        and key
        not in {
            "fast_interaction_parse_validate_emit_ms",
            "fast_interaction_total_ms",
        }
    }
    assert event_timing_fields
    for key, value in event_timing_fields.items():
        assert result.fast_interaction_latency_metadata[key] == value
    assert result.emission.output_event["fast_interaction_parse_validate_emit_ms"] is None
    assert result.emission.output_event["fast_interaction_total_ms"] is None


def test_asr_text_fallback_without_approval_fails_without_transport_call() -> None:
    journal, turn, asr_output = _journal_with_asr_output("fallback_not_enabled")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_fallback_not_enabled",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="Should not be called.")),
            timing=AdapterTimingSnapshot(
                adapter_start_offset_ms=0,
                provider_request_start_offset_ms=1,
                provider_first_chunk_offset_ms=2,
                provider_full_response_offset_ms=3,
                adapter_event_emit_offset_ms=4,
                provider_ttft_ms=1,
                provider_full_response_ms=2,
                provider_generation_ms=1,
                stream_decode_ms=0,
                parse_validate_emit_ms=0,
                total_ms=4,
                timing_mode="streaming",
                ttft_available=True,
                ttft_source="provider_stream_chunk",
            ),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"text_ref": "text://synthetic/fast-interaction/fallback-not-enabled"},
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/fallback-not-enabled",
        output_event_id="evt_fast_interaction_runtime_fallback_not_enabled_output",
        request_failed_event_id="evt_fast_interaction_runtime_fallback_not_enabled_failed",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
    )

    assert result.success is False
    assert result.failure_category == "asr_text_fallback_not_enabled"
    assert result.request_failed_event is not None
    assert result.request_failed_event["failure_reason"] == "asr_text_fallback_not_enabled"
    assert transport.audio_call_count == 0
    assert transport.text_call_count == 0


def test_asr_text_fallback_with_approval_uses_text_timing_transport() -> None:
    journal, turn, asr_output = _journal_with_asr_output("fallback_enabled")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_fallback_enabled",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="Fallback safe answer.")),
            timing=AdapterTimingSnapshot(
                adapter_start_offset_ms=0,
                provider_request_start_offset_ms=4,
                provider_first_chunk_offset_ms=24,
                provider_full_response_offset_ms=54,
                adapter_event_emit_offset_ms=60,
                provider_ttft_ms=20,
                provider_full_response_ms=50,
                provider_generation_ms=30,
                stream_decode_ms=0,
                parse_validate_emit_ms=0,
                total_ms=60,
                timing_mode="streaming",
                ttft_available=True,
                ttft_source="provider_stream_chunk",
            ),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"text_ref": "text://synthetic/fast-interaction/fallback-enabled"},
        turn_ingress_monotonic_ms=0,
        allow_asr_text_fallback=True,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/fallback-enabled",
        output_event_id="evt_fast_interaction_runtime_fallback_enabled_output",
        candidate_event_id="evt_fast_interaction_runtime_fallback_enabled_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-text-fast-interaction",
    )

    assert result.success is True
    assert result.fast_interaction_latency_metadata is not None
    assert (
        result.fast_interaction_latency_metadata["fast_interaction_input_mode"]
        == "asr_text_fallback"
    )
    assert result.emission is not None
    assert result.emission.output_event["input_mode"] == "asr_text_fallback"
    assert transport.audio_call_count == 0
    assert transport.text_call_count == 1


def test_audio_native_missing_audio_bytes_fails_without_transport_call() -> None:
    journal, turn, _asr_output = _journal_with_asr_output("audio_missing")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_audio_missing",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/audio-missing",
    )
    transport = _AudioCompletionTransport(
        FastInteractionProviderCompletion(
            provider_text=json.dumps(_provider_output(reply_candidate="Should not be called.")),
            timing=AdapterTimingSnapshot(
                adapter_start_offset_ms=0,
                provider_request_start_offset_ms=1,
                provider_first_chunk_offset_ms=2,
                provider_full_response_offset_ms=3,
                adapter_event_emit_offset_ms=4,
                provider_ttft_ms=1,
                provider_full_response_ms=2,
                provider_generation_ms=1,
                stream_decode_ms=0,
                parse_validate_emit_ms=0,
                total_ms=4,
                timing_mode="streaming",
                ttft_available=True,
                ttft_source="provider_stream_chunk",
            ),
        )
    )

    result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"turn_ref": "turn://synthetic/mvp63/audio-missing"},
        audio_format="wav",
        turn_ingress_monotonic_ms=0,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/audio-missing",
        output_event_id="evt_fast_interaction_runtime_audio_missing_output",
        request_failed_event_id="evt_fast_interaction_runtime_audio_missing_failed",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
    )

    assert result.success is False
    assert result.failure_category == "audio_input_missing"
    assert result.request_failed_event is not None
    assert result.request_failed_event["failure_reason"] == "audio_input_missing"
    assert transport.audio_call_count == 0
    assert transport.text_call_count == 0


def test_duplicate_validation_failed_event_id_is_preflighted_before_callback_seq_advances() -> None:
    journal, turn, asr_output = _journal_with_asr_output("duplicate_validation_id")
    duplicate_event_id = str(journal.events()[0]["event_id"])
    boundary = AdapterCallbackAppendBoundary(journal)
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_duplicate_validation_id",
    )
    event_count_before = len(journal.events())

    with pytest.raises(FastInteractionValidationError):
        emit_fast_interaction_from_provider_text(
            provider_text="```json\n{}\n```",
            boundary=boundary,
            binding=binding,
            adapter_id="fast_interaction_runtime_test",
            ref_prefix="runtime/duplicate-validation-id",
            output_event_id="evt_fast_interaction_runtime_duplicate_validation_output",
            validation_failed_event_id=duplicate_event_id,
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
        )

    assert len(journal.events()) == event_count_before
    valid_result = emit_fast_interaction_from_provider_text(
        provider_text="```json\n{}\n```",
        boundary=boundary,
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/duplicate-validation-id-second",
        output_event_id="evt_fast_interaction_runtime_duplicate_validation_second_output",
        validation_failed_event_id="evt_fast_interaction_runtime_duplicate_validation_second_failed",
        created_monotonic_ms=31,
        created_wall_clock_ms=1700000000031,
    )
    assert valid_result.validation_failed_event is not None
    assert valid_result.validation_failed_event["adapter_callback_seq"] == 1


def test_duplicate_request_failed_event_id_is_preflighted_before_callback_seq_advances() -> None:
    journal, turn, asr_output = _journal_with_asr_output("duplicate_request_failed_id")
    duplicate_event_id = str(journal.events()[0]["event_id"])
    boundary = AdapterCallbackAppendBoundary(journal)
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_duplicate_request_failed_id",
    )
    transport = _RaisingTransport(
        FastInteractionLiveTransportError(
            "provider timeout",
            category="provider_timeout",
            failure_reasons=("provider_timeout",),
        )
    )
    event_count_before = len(journal.events())

    with pytest.raises(FastInteractionValidationError):
        run_fast_interaction_adapter_request(
            transport=transport,
            request_payload={"text_ref": "text://synthetic/fast-interaction/duplicate-failed"},
            turn_ingress_monotonic_ms=0,
            allow_asr_text_fallback=True,
            credential_handle=object(),
            credential_value="runtime-secret-value-for-test-only",
            boundary=boundary,
            binding=binding,
            adapter_id="fast_interaction_runtime_test",
            ref_prefix="runtime/duplicate-request-failed-id",
            output_event_id="evt_fast_interaction_runtime_duplicate_request_failed_output",
            request_failed_event_id=duplicate_event_id,
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
            timeout_ms=1500,
            model_alias="qwen3.5-omni-flash",
        )

    assert len(journal.events()) == event_count_before
    valid_result = run_fast_interaction_adapter_request(
        transport=transport,
        request_payload={"text_ref": "text://synthetic/fast-interaction/duplicate-failed-second"},
        turn_ingress_monotonic_ms=0,
        allow_asr_text_fallback=True,
        credential_handle=object(),
        credential_value="runtime-secret-value-for-test-only",
        boundary=boundary,
        binding=binding,
        adapter_id="fast_interaction_runtime_test",
        ref_prefix="runtime/duplicate-request-failed-id-second",
        output_event_id="evt_fast_interaction_runtime_duplicate_request_failed_second_output",
        request_failed_event_id="evt_fast_interaction_runtime_duplicate_request_failed_second_failed",
        created_monotonic_ms=31,
        created_wall_clock_ms=1700000000031,
        timeout_ms=1500,
        model_alias="qwen3.5-omni-flash",
    )
    assert valid_result.request_failed_event is not None
    assert valid_result.request_failed_event["adapter_callback_seq"] == 1


class _RaisingTransport:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.call_count = 0

    def complete(self, **_kwargs: object) -> str:
        self.call_count += 1
        raise self._exc

    def complete_with_timing(self, **_kwargs: object) -> FastInteractionProviderCompletion:
        self.call_count += 1
        raise self._exc

    def complete_audio_with_timing(self, **_kwargs: object) -> FastInteractionProviderCompletion:
        self.call_count += 1
        raise self._exc


class _AudioCompletionTransport:
    def __init__(self, completion: FastInteractionProviderCompletion) -> None:
        self._completion = completion
        self.audio_call_count = 0
        self.text_call_count = 0

    def complete_audio_with_timing(self, **_kwargs: object) -> FastInteractionProviderCompletion:
        self.audio_call_count += 1
        return self._completion

    def complete_with_timing(self, **_kwargs: object) -> FastInteractionProviderCompletion:
        self.text_call_count += 1
        return self._completion


class _SequenceMonotonic:
    def __init__(self, values: tuple[float, ...]) -> None:
        self._values = list(values)
        self._last = values[-1]

    def __call__(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last


class _MutableMonotonic:
    def __init__(self, value: float) -> None:
        self._value = value

    def __call__(self) -> float:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += seconds


class _MaliciousTimingSnapshot:
    def to_prefixed_metadata(self, prefix: str) -> dict[str, object]:
        return {
            f"{prefix}_adapter_start_offset_ms": 0,
            f"{prefix}_provider_request_start_offset_ms": 5,
            f"{prefix}_provider_first_chunk_offset_ms": 25,
            f"{prefix}_provider_full_response_offset_ms": 65,
            f"{prefix}_adapter_event_emit_offset_ms": 70,
            f"{prefix}_provider_ttft_ms": 20,
            f"{prefix}_provider_full_response_ms": 60,
            f"{prefix}_provider_generation_ms": 40,
            f"{prefix}_stream_decode_ms": 0,
            f"{prefix}_parse_validate_emit_ms": 0,
            f"{prefix}_total_ms": 70,
            f"{prefix}_timing_mode": "streaming",
            f"{prefix}_ttft_available": True,
            f"{prefix}_ttft_source": "provider_stream_chunk",
            f"{prefix}_provider_text": "SECRET",
            f"{prefix}_audio_raw": "RIFF0000WAVE",
        }


class _RaisingTimingSnapshot:
    def to_prefixed_metadata(self, _prefix: str) -> dict[str, object]:
        raise ValueError("provider_response SECRET raw_audio should not leak")


def _provider_output(*, reply_candidate: str | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": FAST_INTERACTION_SCHEMA_NAME,
        "route_hint": {"router_decision_candidate": "FAST_ONLY"},
        "route_prelude": {"summary": "low risk story request"},
        "foreground_act": "ANSWER",
        "final_fast_evidence": {"summary": "safe foreground answer"},
        "risk_tags": ["low_risk", "no_side_effects"],
        "risk_class": "LOW",
        "confidence": 0.91,
        "output_mode": "real",
        "boundary_assertions": {
            "candidate_is_not_semantic_commitment": True,
            "may_authorize_tools": False,
            "may_execute_tools": False,
            "may_accept_confirmation": False,
            "may_mutate_slowtask_facts": False,
            "runtime_gate_owns_display": True,
        },
    }
    if reply_candidate is not None:
        payload["reply_candidate"] = reply_candidate
    return payload


def _journal_with_asr_output(suffix: str) -> tuple[InMemoryEventJournal, dict[str, object], dict[str, object]]:
    safe_suffix = "".join(char.lower() if char.isalnum() else "_" for char in suffix).strip("_")
    journal = InMemoryEventJournal(
        session_id=f"sess_fast_interaction_runtime_{safe_suffix}",
        conversation_id=f"conv_fast_interaction_runtime_{safe_suffix}",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id=f"evt_{safe_suffix}_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/fast-interaction/runtime",
        capability_snapshot_ref="capability://synthetic/fast-interaction/runtime",
    )
    turn = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_{safe_suffix}_turn_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000000010,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_fast_interaction_{safe_suffix}",
        utterance_id=f"utt_fast_interaction_{safe_suffix}",
        input_modality="audio",
        audio_span_id=f"audio_span_fast_interaction_{safe_suffix}",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    asr_output = journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id=f"evt_{safe_suffix}_asr_output",
        source_module="asr_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000000020,
        trace_redaction_level="metadata_only",
        adapter_id="asr_runtime_test",
        adapter_type="asr",
        adapter_request_id=f"adapter_request_asr_{safe_suffix}",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        audio_span_id=str(turn["audio_span_id"]),
        asr_frame_ref=f"asr-frame://synthetic/fast-interaction/{safe_suffix}",
        text_ref=f"text://synthetic/fast-interaction/{safe_suffix}",
        transcript_finality="final",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="real",
    )
    return journal, turn, asr_output
