"""Synthetic case definitions for the TTS playback eval harness."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    observation_kind: str
    expected_label: str
    output_mode: str = "mock"
    voice_id: str = "longanyang"
    format_requested: str = "mp3"
    sample_rate_requested_hz: int = 22050
    format_observed: str = "mp3"
    sample_rate_observed_hz: int = 22050
    first_audio_latency_ms: int | None = None
    total_synthesis_latency_ms: int | None = None
    audio_duration_ms_estimated: int | None = None
    chunk_count: int = 0
    audio_byte_count: int = 0
    word_timestamp_events_observed: bool = False
    provider_cancel_confirmed: str = "unknown"
    stream_end_reason: str = "not_applicable"
    playback_started: bool = False
    progress_offsets_ms: tuple[int, ...] = ()
    committed_offset_ms: int | None = None
    commit_basis: str | None = None
    truncate_requested: bool = False
    cutoff_playback_offset_ms: int | None = None
    actual_stop_offset_ms: int | None = None
    final_playback_offset_ms: int | None = None
    local_playback_stop_observed: bool = False
    client_close_observed: bool = False
    timeout_observed: bool = False
    retry_count: int = 0
    retry_reason: str | None = None
    late_audio_chunk_count: int = 0
    late_audio_policy: str = "not_applicable"
    partial_audio: bool = False
    mismatch_category: str | None = None
    spoken_plan_approved: bool = False
    risk_warning_preserved: bool = False
    event_observations: tuple[str, ...] = field(default_factory=tuple)
    degradation_reason: str | None = None


SMOKE_CASES = (
    "basic_short_synthesis",
    "streaming_audio_probe",
    "playback_progress_probe",
    "truncate_mid_utterance_probe",
    "client_close_during_stream_probe",
)

FULL_SYNTHETIC_CASES = (
    "basic_short_synthesis",
    "longer_sentence_synthesis",
    "voice_id_probe",
    "format_probe",
    "sample_rate_probe",
    "streaming_audio_probe",
    "first_audio_latency_probe",
    "playback_progress_probe",
    "playback_committed_not_ack_probe",
    "truncate_mid_utterance_probe",
    "client_close_during_stream_probe",
    "local_playback_stop_probe",
    "provider_cancellation_probe",
    "timeout_probe",
    "retryable_failure_probe",
    "late_audio_after_truncate_probe",
    "partial_audio_replay_probe",
    "composer_approved_spoken_plan_probe",
    "risk_warning_spoken_plan_probe",
    "format_mismatch_probe",
)


def _case(case_id: str, observation_kind: str, expected_label: str, **kwargs: object) -> CaseDefinition:
    return CaseDefinition(
        case_id=case_id,
        observation_kind=observation_kind,
        expected_label=expected_label,
        **kwargs,
    )


CASES: dict[str, CaseDefinition] = {
    "basic_short_synthesis": _case(
        "basic_short_synthesis",
        "adapter_synthesis_observation",
        "prior_observed_real_basic_synthesis",
        first_audio_latency_ms=556,
        total_synthesis_latency_ms=1103,
        audio_duration_ms_estimated=1100,
        chunk_count=15,
        audio_byte_count=36453,
        word_timestamp_events_observed=True,
        stream_end_reason="task_finished",
    ),
    "longer_sentence_synthesis": _case(
        "longer_sentence_synthesis",
        "adapter_synthesis_observation",
        "prior_observed_real_longer_synthesis",
        first_audio_latency_ms=705,
        total_synthesis_latency_ms=5778,
        audio_duration_ms_estimated=5700,
        chunk_count=61,
        audio_byte_count=148466,
        word_timestamp_events_observed=True,
        stream_end_reason="task_finished",
    ),
    "voice_id_probe": _case(
        "voice_id_probe",
        "adapter_synthesis_observation",
        "prior_observed_real_voice_id_longanyang",
        first_audio_latency_ms=553,
        total_synthesis_latency_ms=1326,
        audio_duration_ms_estimated=1300,
        chunk_count=17,
        audio_byte_count=43976,
        word_timestamp_events_observed=True,
        stream_end_reason="task_finished",
    ),
    "format_probe": _case(
        "format_probe",
        "adapter_synthesis_observation",
        "prior_observed_real_format_mp3",
        first_audio_latency_ms=556,
        total_synthesis_latency_ms=1103,
        audio_duration_ms_estimated=1100,
        chunk_count=15,
        audio_byte_count=36453,
        stream_end_reason="task_finished",
    ),
    "sample_rate_probe": _case(
        "sample_rate_probe",
        "adapter_synthesis_observation",
        "prior_observed_real_sample_rate_22050",
        first_audio_latency_ms=556,
        total_synthesis_latency_ms=1103,
        audio_duration_ms_estimated=1100,
        chunk_count=15,
        audio_byte_count=36453,
        stream_end_reason="task_finished",
    ),
    "streaming_audio_probe": _case(
        "streaming_audio_probe",
        "stream_chunk_summary",
        "prior_observed_real_streaming_audio",
        first_audio_latency_ms=493,
        total_synthesis_latency_ms=1728,
        audio_duration_ms_estimated=1700,
        chunk_count=23,
        audio_byte_count=55679,
        word_timestamp_events_observed=True,
        stream_end_reason="task_finished",
    ),
    "first_audio_latency_probe": _case(
        "first_audio_latency_probe",
        "adapter_synthesis_observation",
        "prior_observed_real_first_audio_bucket",
        first_audio_latency_ms=493,
        total_synthesis_latency_ms=1728,
        chunk_count=23,
        audio_byte_count=55679,
        stream_end_reason="task_finished",
    ),
    "playback_progress_probe": _case(
        "playback_progress_probe",
        "playback_event_observation",
        "synthetic_playback_progress_shape",
        playback_started=True,
        progress_offsets_ms=(0, 250, 500, 750, 1000),
        final_playback_offset_ms=1000,
        event_observations=("PLAYBACK_SPAN_STARTED", "PLAYBACK_PROGRESS"),
    ),
    "playback_committed_not_ack_probe": _case(
        "playback_committed_not_ack_probe",
        "playback_event_observation",
        "synthetic_playback_committed_not_ack",
        playback_started=True,
        progress_offsets_ms=(0, 400, 800, 1200),
        committed_offset_ms=1200,
        commit_basis="audio_delivered_to_output_device",
        final_playback_offset_ms=1200,
        event_observations=("PLAYBACK_SPAN_STARTED", "PLAYBACK_PROGRESS", "PLAYBACK_COMMITTED"),
    ),
    "truncate_mid_utterance_probe": _case(
        "truncate_mid_utterance_probe",
        "truncate_event_observation",
        "synthetic_truncate_chain_shape",
        playback_started=True,
        progress_offsets_ms=(0, 400, 800, 1200),
        truncate_requested=True,
        cutoff_playback_offset_ms=1180,
        actual_stop_offset_ms=1240,
        final_playback_offset_ms=1240,
        local_playback_stop_observed=True,
        event_observations=("TTS_TRUNCATE_REQUESTED", "TTS_TRUNCATED"),
    ),
    "client_close_during_stream_probe": _case(
        "client_close_during_stream_probe",
        "adapter_failure_observation",
        "prior_observed_degraded_client_close",
        output_mode="degraded",
        first_audio_latency_ms=663,
        total_synthesis_latency_ms=679,
        chunk_count=3,
        audio_byte_count=6778,
        word_timestamp_events_observed=True,
        provider_cancel_confirmed="unknown",
        stream_end_reason="client_closed",
        client_close_observed=True,
        partial_audio=True,
        degradation_reason="client close is not provider-confirmed cancellation",
    ),
    "local_playback_stop_probe": _case(
        "local_playback_stop_probe",
        "playback_event_observation",
        "synthetic_local_playback_stop_shape",
        output_mode="degraded",
        playback_started=True,
        progress_offsets_ms=(0, 300, 600, 900),
        actual_stop_offset_ms=960,
        final_playback_offset_ms=960,
        local_playback_stop_observed=True,
        stream_end_reason="local_stop_without_provider_cancel",
    ),
    "provider_cancellation_probe": _case(
        "provider_cancellation_probe",
        "adapter_failure_observation",
        "unknown_provider_cancellation",
        output_mode="degraded",
        provider_cancel_confirmed="unknown",
        stream_end_reason="provider_cancel_unconfirmed",
        degradation_reason="provider-confirmed cancellation not observed",
    ),
    "timeout_probe": _case(
        "timeout_probe",
        "adapter_failure_observation",
        "synthetic_timeout_shape",
        output_mode="degraded",
        timeout_observed=True,
        stream_end_reason="timeout",
        degradation_reason="timeout must not synthesize playback events",
    ),
    "retryable_failure_probe": _case(
        "retryable_failure_probe",
        "adapter_failure_observation",
        "synthetic_retry_shape",
        output_mode="degraded",
        retry_count=1,
        retry_reason="retryable_connection_failure",
        stream_end_reason="retry_exhausted_or_degraded",
    ),
    "late_audio_after_truncate_probe": _case(
        "late_audio_after_truncate_probe",
        "truncate_event_observation",
        "synthetic_late_audio_ignored_shape",
        output_mode="degraded",
        playback_started=True,
        truncate_requested=True,
        cutoff_playback_offset_ms=1180,
        actual_stop_offset_ms=1240,
        final_playback_offset_ms=1240,
        late_audio_chunk_count=2,
        late_audio_policy="ignored_after_terminal_playback",
        event_observations=("TTS_TRUNCATE_REQUESTED", "TTS_TRUNCATED"),
    ),
    "partial_audio_replay_probe": _case(
        "partial_audio_replay_probe",
        "privacy_review",
        "synthetic_partial_audio_replay_shape",
        output_mode="degraded",
        chunk_count=4,
        audio_byte_count=12000,
        partial_audio=True,
        stream_end_reason="partial_audio_fixture",
    ),
    "composer_approved_spoken_plan_probe": _case(
        "composer_approved_spoken_plan_probe",
        "playback_event_observation",
        "synthetic_spoken_plan_approval_shape",
        playback_started=True,
        spoken_plan_approved=True,
        progress_offsets_ms=(0, 500, 1000),
        final_playback_offset_ms=1000,
        event_observations=("PLAYBACK_SPAN_STARTED",),
    ),
    "risk_warning_spoken_plan_probe": _case(
        "risk_warning_spoken_plan_probe",
        "playback_event_observation",
        "synthetic_risk_warning_preservation_shape",
        playback_started=True,
        spoken_plan_approved=True,
        risk_warning_preserved=True,
        progress_offsets_ms=(0, 500, 1000),
        final_playback_offset_ms=1000,
        event_observations=("PLAYBACK_SPAN_STARTED",),
    ),
    "format_mismatch_probe": _case(
        "format_mismatch_probe",
        "adapter_failure_observation",
        "synthetic_format_mismatch_shape",
        output_mode="degraded",
        format_requested="mp3",
        format_observed="unknown_or_mismatch",
        mismatch_category="format_mismatch",
        stream_end_reason="adapter_output_degraded",
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
