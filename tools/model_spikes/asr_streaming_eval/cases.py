"""Synthetic case definitions for the ASR streaming eval harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    fixture_kind: str
    audio_duration_ms: int
    sample_rate_hz: int
    channels: int
    audio_format: str
    transcript_present: bool
    transcript_length_chars: int
    expected_label: str
    degradation_reason: str | None = None
    expected_non_speech: bool = False
    non_speech_transcript_risk: bool = False
    clipped_start_case: bool = False
    playback_echo_context: bool = False
    low_volume_case: bool = False
    response_streaming_output_observed: bool = False
    delta_chunk_count: int = 0
    first_delta_ms: int | None = None
    final_delta_ms: int | None = None
    true_realtime_microphone_streaming_input_observed: bool = False
    input_chunk_duration_ms: int | None = None
    input_cadence_ms: int | None = None
    timestamp_source: str = "unavailable"
    timestamp_units: str = "unknown"
    audio_offset_basis: str = "unknown"
    segment_count: int = 0
    word_count: int = 0
    timestamp_normalized: bool = False
    timestamp_status: str = "unavailable"
    failure_category: str | None = None
    retryable: bool | None = None
    provider_confirmed_cancellation: str = "unknown"
    client_close_observed: bool = False
    late_output_policy: str = "not_applicable"


SMOKE_CASES = (
    "short_command_nonstream_baseline",
    "streaming_output_delta_probe",
    "filetrans_timestamp_probe",
    "silence_non_speech_probe",
    "client_timeout_probe",
)

FULL_SYNTHETIC_CASES = (
    "short_command_nonstream_baseline",
    "mixed_language_nonstream_baseline",
    "clipped_start_probe",
    "low_volume_speech_probe",
    "longer_utterance_probe",
    "silence_non_speech_probe",
    "tone_non_speech_probe",
    "white_noise_non_speech_probe",
    "background_speech_not_directed_probe",
    "playback_only_echo_probe",
    "user_speech_over_playback_probe",
    "streaming_output_delta_probe",
    "true_realtime_mic_streaming_input_probe",
    "filetrans_timestamp_probe",
    "word_timestamp_granularity_probe",
    "timestamp_normalization_probe",
    "partial_transcript_replay_probe",
    "client_timeout_probe",
    "client_abort_stream_probe",
    "provider_cancellation_probe",
    "retryable_failure_probe",
    "late_transcript_after_superseded_turn_probe",
    "asr_not_semantic_truth_probe",
)


def _case(
    case_id: str,
    *,
    transcript_present: bool = True,
    transcript_length_chars: int = 7,
    audio_duration_ms: int = 1200,
    expected_label: str = "synthetic_reference",
    **kwargs: object,
) -> CaseDefinition:
    return CaseDefinition(
        case_id=case_id,
        fixture_kind="synthetic_audio_metadata",
        audio_duration_ms=audio_duration_ms,
        sample_rate_hz=16000,
        channels=1,
        audio_format="wav",
        transcript_present=transcript_present,
        transcript_length_chars=transcript_length_chars,
        expected_label=expected_label,
        **kwargs,
    )


CASES: dict[str, CaseDefinition] = {
    "short_command_nonstream_baseline": _case(
        "short_command_nonstream_baseline",
        expected_label="prior_observed_real_final_transcript",
        timestamp_source="chat_annotations",
        timestamp_status="degraded",
        degradation_reason="chat annotation timing not normalized",
    ),
    "mixed_language_nonstream_baseline": _case(
        "mixed_language_nonstream_baseline",
        transcript_length_chars=22,
        expected_label="prior_observed_real_final_transcript",
    ),
    "clipped_start_probe": _case(
        "clipped_start_probe",
        transcript_length_chars=6,
        expected_label="prior_observed_real_final_transcript",
        clipped_start_case=True,
        degradation_reason="clipped-start quality requires eval",
    ),
    "low_volume_speech_probe": _case(
        "low_volume_speech_probe",
        expected_label="unknown_quality_until_eval",
        low_volume_case=True,
        degradation_reason="low-volume robustness not yet observed",
    ),
    "longer_utterance_probe": _case(
        "longer_utterance_probe",
        transcript_length_chars=64,
        audio_duration_ms=18000,
        expected_label="unknown_quality_until_eval",
        degradation_reason="longer utterance behavior not yet observed",
    ),
    "silence_non_speech_probe": _case(
        "silence_non_speech_probe",
        transcript_length_chars=2,
        expected_label="prior_observed_degraded_non_speech_risk",
        expected_non_speech=True,
        non_speech_transcript_risk=True,
        degradation_reason="non-speech produced transcript-like text",
    ),
    "tone_non_speech_probe": _case(
        "tone_non_speech_probe",
        transcript_present=False,
        transcript_length_chars=0,
        expected_label="unknown_until_eval",
        expected_non_speech=True,
    ),
    "white_noise_non_speech_probe": _case(
        "white_noise_non_speech_probe",
        transcript_present=False,
        transcript_length_chars=0,
        expected_label="unknown_until_eval",
        expected_non_speech=True,
    ),
    "background_speech_not_directed_probe": _case(
        "background_speech_not_directed_probe",
        expected_label="unknown_directedness_boundary",
        degradation_reason="directedness owner remains interaction_or_duplex",
    ),
    "playback_only_echo_probe": _case(
        "playback_only_echo_probe",
        expected_label="unknown_echo_rejection",
        playback_echo_context=True,
        degradation_reason="playback-only echo may not be user input",
    ),
    "user_speech_over_playback_probe": _case(
        "user_speech_over_playback_probe",
        expected_label="unknown_overlap_quality",
        playback_echo_context=True,
    ),
    "streaming_output_delta_probe": _case(
        "streaming_output_delta_probe",
        expected_label="prior_observed_real_response_streaming_output",
        response_streaming_output_observed=True,
        delta_chunk_count=4,
        first_delta_ms=1306,
        final_delta_ms=1322,
    ),
    "true_realtime_mic_streaming_input_probe": _case(
        "true_realtime_mic_streaming_input_probe",
        transcript_present=False,
        transcript_length_chars=0,
        expected_label="unknown_realtime_input",
        degradation_reason="true realtime microphone streaming input not observed",
    ),
    "filetrans_timestamp_probe": _case(
        "filetrans_timestamp_probe",
        expected_label="prior_observed_real_filetrans_timestamps",
        timestamp_source="filetrans_words",
        timestamp_units="ms",
        audio_offset_basis="audio_span_start",
        segment_count=1,
        word_count=3,
        timestamp_normalized=True,
        timestamp_status="normalized",
    ),
    "word_timestamp_granularity_probe": _case(
        "word_timestamp_granularity_probe",
        expected_label="unknown_alignment_quality",
        timestamp_source="filetrans_words",
        timestamp_units="ms",
        audio_offset_basis="audio_span_start",
        segment_count=1,
        word_count=5,
        timestamp_normalized=True,
        timestamp_status="normalized",
    ),
    "timestamp_normalization_probe": _case(
        "timestamp_normalization_probe",
        expected_label="synthetic_normalization_shape",
        timestamp_source="mixed_chat_filetrans",
        timestamp_units="ms",
        audio_offset_basis="audio_span_start",
        segment_count=2,
        word_count=6,
        timestamp_normalized=True,
        timestamp_status="normalized",
    ),
    "partial_transcript_replay_probe": _case(
        "partial_transcript_replay_probe",
        expected_label="synthetic_replay_shape",
        response_streaming_output_observed=True,
        delta_chunk_count=3,
        first_delta_ms=400,
        final_delta_ms=900,
    ),
    "client_timeout_probe": _case(
        "client_timeout_probe",
        transcript_present=False,
        transcript_length_chars=0,
        expected_label="prior_observed_degraded_client_timeout",
        failure_category="client_timeout",
        retryable=True,
        degradation_reason="timeout is not provider-confirmed cancellation",
    ),
    "client_abort_stream_probe": _case(
        "client_abort_stream_probe",
        transcript_present=False,
        transcript_length_chars=0,
        expected_label="unknown_client_close_boundary",
        failure_category="client_stream_close",
        retryable=True,
        client_close_observed=True,
        degradation_reason="client close is degraded local control metadata",
    ),
    "provider_cancellation_probe": _case(
        "provider_cancellation_probe",
        transcript_present=False,
        transcript_length_chars=0,
        expected_label="unknown_provider_cancellation",
        failure_category="provider_cancellation_unconfirmed",
        retryable=None,
        provider_confirmed_cancellation="unknown",
    ),
    "retryable_failure_probe": _case(
        "retryable_failure_probe",
        transcript_present=False,
        transcript_length_chars=0,
        expected_label="unknown_retry_behavior",
        failure_category="retryable_provider_failure_fixture",
        retryable=True,
    ),
    "late_transcript_after_superseded_turn_probe": _case(
        "late_transcript_after_superseded_turn_probe",
        expected_label="unknown_late_output_policy",
        late_output_policy="stale_or_ignored",
        degradation_reason="late output must keep original request binding",
    ),
    "asr_not_semantic_truth_probe": _case(
        "asr_not_semantic_truth_probe",
        expected_label="synthetic_adr_008_boundary",
        degradation_reason="ASR and Thinker refs remain separate; no field winner",
    ),
}


CASE_SETS: dict[str, tuple[str, ...]] = {
    "smoke": SMOKE_CASES,
    "full_synthetic": FULL_SYNTHETIC_CASES,
}


def select_cases(case_set: str) -> list[CaseDefinition]:
    if case_set == "provider_probe":
        raise ValueError("provider_probe is unavailable by default")
    try:
        case_ids = CASE_SETS[case_set]
    except KeyError as exc:
        raise ValueError(f"unknown case set: {case_set}") from exc
    return [CASES[case_id] for case_id in case_ids]
