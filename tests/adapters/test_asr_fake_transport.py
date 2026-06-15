from __future__ import annotations

from voice_agent.adapters.asr_fake_transport import (
    FakeAsrProviderResponse,
    FakeAsrTransport,
)
from voice_agent.adapters.asr_normalization import AsrRequestBinding


def test_fake_transport_normalizes_success_response_to_final_candidate() -> None:
    result = FakeAsrTransport(
        [
            FakeAsrProviderResponse.success(
                asr_frame_ref="asr-frame://synthetic/asr/success",
                text_ref="text://synthetic/asr/success",
                audio_timestamps_ref="timestamps://synthetic/asr/success",
                streaming_status="supported",
            )
        ]
    ).transcribe(valid_binding())

    assert result.candidate is not None
    assert result.candidate.transcript_finality == "final"
    assert result.candidate.timestamp_status == "available"
    assert result.candidate.streaming_status == "supported"
    assert result.candidate.output_mode == "real"
    assert result.validation_failure_metadata is None
    assert result.request_failure_metadata is None


def test_fake_transport_malformed_output_returns_validation_failure_metadata() -> None:
    result = FakeAsrTransport([FakeAsrProviderResponse.malformed("missing_text_ref")]).transcribe(
        valid_binding()
    )

    assert result.candidate is None
    assert result.validation_failure_metadata == {
        "adapter_request_id": "adapter_request_asr_fake_001",
        "schema_name": "voice_agent.asr.normalized_transcript_candidate.v1",
        "failure_reasons": ("missing_text_ref",),
        "output_mode": "degraded",
    }
    assert result.request_failure_metadata is None


def test_fake_transport_timeout_returns_safe_request_failure_metadata() -> None:
    result = FakeAsrTransport([FakeAsrProviderResponse.timeout(timeout_ms=750)]).transcribe(
        valid_binding()
    )

    assert result.candidate is None
    assert result.request_failure_metadata == {
        "adapter_request_id": "adapter_request_asr_fake_001",
        "failure_reason": "timeout",
        "retryable": True,
        "timeout_ms": 750,
        "output_mode": "degraded",
    }
    assert result.validation_failure_metadata is None


def test_fake_transport_request_failure_returns_bounded_failure_metadata() -> None:
    result = FakeAsrTransport([FakeAsrProviderResponse.request_failure("provider_unavailable")]).transcribe(
        valid_binding()
    )

    assert result.candidate is None
    assert result.request_failure_metadata == {
        "adapter_request_id": "adapter_request_asr_fake_001",
        "failure_reason": "provider_unavailable",
        "retryable": False,
        "timeout_ms": None,
        "output_mode": "degraded",
    }


def test_fake_transport_missing_timestamps_marks_candidate_degraded() -> None:
    result = FakeAsrTransport(
        [
            FakeAsrProviderResponse.success(
                asr_frame_ref="asr-frame://synthetic/asr/no-timestamps",
                text_ref="text://synthetic/asr/no-timestamps",
                audio_timestamps_ref=None,
                streaming_status="supported",
            )
        ]
    ).transcribe(valid_binding())

    assert result.candidate is not None
    assert result.candidate.timestamp_status == "unavailable"
    assert result.candidate.output_mode == "degraded"


def test_fake_transport_final_only_streaming_marks_candidate_degraded() -> None:
    result = FakeAsrTransport(
        [
            FakeAsrProviderResponse.success(
                asr_frame_ref="asr-frame://synthetic/asr/final-only",
                text_ref="text://synthetic/asr/final-only",
                audio_timestamps_ref="timestamps://synthetic/asr/final-only",
                streaming_status="unsupported_final_only",
            )
        ]
    ).transcribe(valid_binding())

    assert result.candidate is not None
    assert result.candidate.streaming_status == "unsupported_final_only"
    assert result.candidate.output_mode == "degraded"


def test_fake_transport_non_speech_and_low_confidence_are_quality_flags() -> None:
    result = FakeAsrTransport(
        [
            FakeAsrProviderResponse.success(
                asr_frame_ref="asr-frame://synthetic/asr/quality",
                text_ref="text://synthetic/asr/quality",
                audio_timestamps_ref="timestamps://synthetic/asr/quality",
                streaming_status="supported",
                quality_flags=("non_speech", "low_confidence"),
                confidence_score=0.21,
            )
        ]
    ).transcribe(valid_binding())

    assert result.candidate is not None
    assert result.candidate.quality_flags == ("non_speech", "low_confidence")
    assert result.candidate.confidence_status == "available"
    assert result.candidate.confidence_score == 0.21


def test_fake_transport_late_result_returns_stale_ignored_metadata_without_candidate() -> None:
    result = FakeAsrTransport(
        [
            FakeAsrProviderResponse.late_result(
                asr_frame_ref="asr-frame://synthetic/asr/late",
                text_ref="text://synthetic/asr/late",
            )
        ]
    ).transcribe(valid_binding())

    assert result.candidate is None
    assert result.late_result_metadata == {
        "adapter_request_id": "adapter_request_asr_fake_001",
        "turn_id": "turn_asr_fake_001",
        "utterance_id": "utt_asr_fake_001",
        "audio_span_id": "audio_asr_fake_001",
        "late_result_status": "stale_ignored",
        "stale_reason": "result_returned_after_current_request_window",
        "asr_frame_ref": "asr-frame://synthetic/asr/late",
        "text_ref": "text://synthetic/asr/late",
    }


def valid_binding() -> AsrRequestBinding:
    return AsrRequestBinding.from_turn_committed_event(
        {
            "event_name": "TURN_INGRESS_COMMITTED",
            "event_id": "evt_turn_committed_asr_fake_001",
            "turn_id": "turn_asr_fake_001",
            "utterance_id": "utt_asr_fake_001",
            "audio_span_id": "audio_asr_fake_001",
            "input_modality": "audio",
        },
        adapter_request_id="adapter_request_asr_fake_001",
    )
