from __future__ import annotations

from dataclasses import asdict

import pytest

from voice_agent.adapters.asr_normalization import (
    AsrNormalizationError,
    AsrRequestBinding,
    normalize_asr_candidate,
    validate_normalized_asr_candidate,
)


def test_request_binding_copies_committed_audio_turn_metadata() -> None:
    binding = AsrRequestBinding.from_turn_committed_event(
        committed_audio_turn(),
        adapter_request_id="adapter_request_asr_binding_001",
    )

    assert binding.adapter_request_id == "adapter_request_asr_binding_001"
    assert binding.turn_id == "turn_asr_001"
    assert binding.utterance_id == "utt_asr_001"
    assert binding.audio_span_id == "audio_asr_001"
    assert binding.input_modality == "audio"
    assert binding.turn_committed_event_id == "evt_turn_committed_asr_001"


@pytest.mark.parametrize(
    "bad_turn",
    (
        {"event_name": "TURN_INGRESS_COMMITTED", "input_modality": "text", "audio_span_id": "audio_asr_001"},
        {"event_name": "TEXT_INPUT_RECEIVED", "input_modality": "audio", "audio_span_id": "audio_asr_001"},
        {"event_name": "TURN_INGRESS_COMMITTED", "input_modality": "audio", "audio_span_id": ""},
    ),
)
def test_request_binding_rejects_missing_or_mismatched_committed_turn_metadata(
    bad_turn: dict[str, object],
) -> None:
    turn = committed_audio_turn()
    turn.update(bad_turn)

    with pytest.raises(AsrNormalizationError):
        AsrRequestBinding.from_turn_committed_event(
            turn,
            adapter_request_id="adapter_request_asr_binding_bad",
        )


def test_normalized_candidate_contains_safe_refs_and_metadata_only() -> None:
    candidate = normalize_asr_candidate(
        binding=valid_binding(),
        asr_frame_ref="asr-frame://synthetic/asr/final-001",
        text_ref="text://synthetic/asr/final-001",
        audio_timestamps_ref="timestamps://synthetic/asr/final-001",
        language_status="available",
        language_ref="language://synthetic/asr/en-us",
        confidence_status="available",
        confidence_score=0.91,
        nbest_status="unavailable",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="real",
    )

    assert candidate.normalization_status == "normalized"
    assert candidate.transcript_finality == "final"
    assert candidate.input_modality == "audio"
    assert candidate.quality_flags == ()
    assert "raw_transcript" not in asdict(candidate)
    assert validate_normalized_asr_candidate(candidate) == candidate


@pytest.mark.parametrize(
    ("field", "unsafe_ref"),
    (
        ("text_ref", "text://synthetic/asr/final?token=synthetic"),
        ("asr_frame_ref", "asr-frame://synthetic/asr/final?api_key=sk-synthetic"),
        ("audio_timestamps_ref", "file:///Users/a123/private/timestamps.json"),
    ),
)
def test_normalized_candidate_rejects_unsafe_refs(field: str, unsafe_ref: str) -> None:
    kwargs = {
        "binding": valid_binding(),
        "asr_frame_ref": "asr-frame://synthetic/asr/final-safe",
        "text_ref": "text://synthetic/asr/final-safe",
        "audio_timestamps_ref": "timestamps://synthetic/asr/final-safe",
        "timestamp_status": "available",
        "streaming_status": "supported",
        "output_mode": "real",
    }
    kwargs[field] = unsafe_ref

    with pytest.raises(AsrNormalizationError, match="safe ref"):
        normalize_asr_candidate(**kwargs)


@pytest.mark.parametrize(
    "forbidden_field",
    (
        "raw_transcript",
        "provider_response",
        "raw_audio",
        "prompt_dump",
        "resolved_arguments_ref",
        "confirmation_state",
        "tool_authorization",
    ),
)
def test_normalized_candidate_rejects_raw_payload_and_ownership_fields(
    forbidden_field: str,
) -> None:
    candidate = asdict(
        normalize_asr_candidate(
            binding=valid_binding(),
            asr_frame_ref="asr-frame://synthetic/asr/final-safe",
            text_ref="text://synthetic/asr/final-safe",
            audio_timestamps_ref="timestamps://synthetic/asr/final-safe",
            timestamp_status="available",
            streaming_status="supported",
            output_mode="real",
        )
    )
    candidate[forbidden_field] = "ref://synthetic/forbidden"

    with pytest.raises(AsrNormalizationError, match="forbidden"):
        validate_normalized_asr_candidate(candidate)


def test_timestamp_unavailable_and_final_only_streaming_are_degraded_metadata() -> None:
    candidate = normalize_asr_candidate(
        binding=valid_binding(),
        asr_frame_ref="asr-frame://synthetic/asr/degraded-final",
        text_ref="text://synthetic/asr/degraded-final",
        audio_timestamps_ref=None,
        timestamp_status="unavailable",
        streaming_status="unsupported_final_only",
        output_mode="degraded",
        quality_flags=("non_speech", "low_confidence"),
    )

    assert candidate.timestamp_status == "unavailable"
    assert candidate.streaming_status == "unsupported_final_only"
    assert candidate.output_mode == "degraded"
    assert candidate.quality_flags == ("non_speech", "low_confidence")


def test_degraded_timestamp_or_streaming_status_cannot_be_labeled_real() -> None:
    with pytest.raises(AsrNormalizationError, match="degraded"):
        normalize_asr_candidate(
            binding=valid_binding(),
            asr_frame_ref="asr-frame://synthetic/asr/bad-mode",
            text_ref="text://synthetic/asr/bad-mode",
            audio_timestamps_ref=None,
            timestamp_status="unavailable",
            streaming_status="supported",
            output_mode="real",
        )


def valid_binding() -> AsrRequestBinding:
    return AsrRequestBinding.from_turn_committed_event(
        committed_audio_turn(),
        adapter_request_id="adapter_request_asr_001",
    )


def committed_audio_turn() -> dict[str, object]:
    return {
        "event_name": "TURN_INGRESS_COMMITTED",
        "event_id": "evt_turn_committed_asr_001",
        "turn_id": "turn_asr_001",
        "utterance_id": "utt_asr_001",
        "audio_span_id": "audio_asr_001",
        "input_modality": "audio",
    }
