from __future__ import annotations

from dataclasses import dataclass, field


class EventRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class EventDefinition:
    event_name: str
    required_fields: tuple[str, ...]
    one_of_fields: tuple[tuple[str, ...], ...] = ()
    literal_fields: dict[str, object] = field(default_factory=dict)
    is_root: bool = False


def _definition(
    event_name: str,
    *,
    required_fields: tuple[str, ...] = (),
    one_of_fields: tuple[tuple[str, ...], ...] = (),
    literal_fields: dict[str, object] | None = None,
    is_root: bool = False,
) -> EventDefinition:
    return EventDefinition(
        event_name=event_name,
        required_fields=required_fields,
        one_of_fields=one_of_fields,
        literal_fields=literal_fields or {},
        is_root=is_root,
    )


MVP0_EVENT_DEFINITIONS: dict[str, EventDefinition] = {
    "SESSION_STARTED": _definition(
        "SESSION_STARTED",
        required_fields=("session_id", "conversation_id", "runtime_config_ref", "capability_snapshot_ref"),
        is_root=True,
    ),
    "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED": _definition(
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        required_fields=(
            "capability_snapshot_ref",
            "adapter_ids",
            "adapter_types",
            "deployment_modes",
            "output_modes",
        ),
    ),
    "TEXT_INPUT_RECEIVED": _definition(
        "TEXT_INPUT_RECEIVED",
        required_fields=(
            "input_span_id",
            "text_span_id",
            "directedness",
            "semantic_close",
        ),
        one_of_fields=(("redacted_text", "text_ref"),),
        literal_fields={
            "input_modality": "text",
            "directedness": "ASSUMED_DIRECTED",
            "semantic_close": "ASSUMED_CLOSED",
        },
    ),
    "LOW_CONFIDENCE_INGRESS": _definition(
        "LOW_CONFIDENCE_INGRESS",
        required_fields=("confidence_fields", "ingress_reason"),
        one_of_fields=(("input_span_id", "audio_span_id"),),
    ),
    "AUDIO_SPAN_STARTED": _definition(
        "AUDIO_SPAN_STARTED",
        required_fields=("audio_span_id", "audio_sample_offset", "audio_format_ref"),
        literal_fields={"input_modality": "audio"},
    ),
    "AUDIO_SPAN_ENDED": _definition(
        "AUDIO_SPAN_ENDED",
        required_fields=("audio_span_id", "audio_sample_offset", "duration_ms", "end_reason"),
    ),
    "SPEECH_START_DETECTED": _definition(
        "SPEECH_START_DETECTED",
        required_fields=("audio_span_id", "audio_sample_offset", "vad_confidence"),
    ),
    "SPEECH_END_DETECTED": _definition(
        "SPEECH_END_DETECTED",
        required_fields=("audio_span_id", "audio_sample_offset", "vad_confidence", "silence_duration_ms"),
    ),
    "BARGE_IN_CANDIDATE": _definition(
        "BARGE_IN_CANDIDATE",
        required_fields=(
            "audio_span_id",
            "playback_span_id",
            "playback_offset_ms",
            "echo_likelihood",
            "vad_confidence",
            "barge_in_confidence",
        ),
    ),
    "DIRECTEDNESS_CANDIDATE": _definition(
        "DIRECTEDNESS_CANDIDATE",
        required_fields=("audio_span_id", "directedness", "directedness_confidence"),
    ),
    "SEMANTIC_CLOSE_CANDIDATE": _definition(
        "SEMANTIC_CLOSE_CANDIDATE",
        required_fields=("audio_span_id", "semantic_close", "semantic_close_confidence"),
    ),
    "NON_ASSISTANT_CANDIDATE": _definition(
        "NON_ASSISTANT_CANDIDATE",
        required_fields=("audio_span_id", "directedness_confidence"),
        literal_fields={"directedness": "NOT_DIRECTED"},
    ),
    "TURN_OPENED": _definition(
        "TURN_OPENED",
        required_fields=("turn_id", "turn_phase", "input_modality"),
        one_of_fields=(("input_span_id", "audio_span_id"),),
        literal_fields={"turn_phase": "COLLECTING_INPUT"},
    ),
    "TURN_HELD": _definition(
        "TURN_HELD",
        required_fields=("turn_id", "semantic_close", "directedness"),
        literal_fields={"ingress_outcome": "HELD"},
    ),
    "TURN_INGRESS_ACCEPTED": _definition(
        "TURN_INGRESS_ACCEPTED",
        required_fields=("turn_id", "ingress_outcome"),
        one_of_fields=(("input_span_id", "audio_span_id"),),
        literal_fields={"ingress_outcome": "ACCEPTED"},
    ),
    "TURN_INGRESS_REJECTED": _definition(
        "TURN_INGRESS_REJECTED",
        required_fields=("turn_id", "reject_reason"),
        one_of_fields=(("input_span_id", "audio_span_id"),),
        literal_fields={"ingress_outcome": "REJECTED"},
    ),
    "TURN_INGRESS_COMMITTED": _definition(
        "TURN_INGRESS_COMMITTED",
        required_fields=(
            "turn_id",
            "utterance_id",
            "input_modality",
            "directedness",
            "semantic_close",
            "ingress_outcome",
        ),
        one_of_fields=(("input_span_id", "text_span_id", "audio_span_id"),),
        literal_fields={"ingress_outcome": "COMMITTED"},
    ),
    "INTERRUPT_CANDIDATE": _definition(
        "INTERRUPT_CANDIDATE",
        required_fields=("playback_span_id", "playback_offset_ms", "policy_reason", "confidence_summary"),
    ),
    "ROUTER_DECISION_EMITTED": _definition(
        "ROUTER_DECISION_EMITTED",
        required_fields=("turn_id", "utterance_id", "router_decision"),
    ),
    "PLAYBACK_SPAN_STARTED": _definition(
        "PLAYBACK_SPAN_STARTED",
        required_fields=("playback_span_id",),
        one_of_fields=(("audio_ref", "tts_stream_ref"),),
    ),
    "PLAYBACK_PROGRESS": _definition(
        "PLAYBACK_PROGRESS",
        required_fields=("playback_span_id", "playback_offset_ms"),
    ),
    "PLAYBACK_COMMITTED": _definition(
        "PLAYBACK_COMMITTED",
        required_fields=("playback_span_id", "playback_offset_ms", "commit_basis"),
    ),
    "PLAYBACK_FINISHED": _definition(
        "PLAYBACK_FINISHED",
        required_fields=("playback_span_id", "final_playback_offset_ms"),
    ),
    "TTS_TRUNCATE_REQUESTED": _definition(
        "TTS_TRUNCATE_REQUESTED",
        required_fields=("playback_span_id", "cutoff_playback_offset_ms", "interrupt_candidate_event_id"),
    ),
    "TTS_TRUNCATED": _definition(
        "TTS_TRUNCATED",
        required_fields=("playback_span_id", "actual_stop_offset_ms", "truncate_request_event_id"),
    ),
    "MOCK_ASR_FRAME_EMITTED": _definition(
        "MOCK_ASR_FRAME_EMITTED",
        required_fields=("turn_id", "utterance_id", "input_modality", "asr_frame_ref"),
        literal_fields={"output_mode": "mock"},
    ),
    "MOCK_THINKER_FRAME_EMITTED": _definition(
        "MOCK_THINKER_FRAME_EMITTED",
        required_fields=("turn_id", "utterance_id", "semantic_frame_ref"),
        literal_fields={"output_mode": "mock"},
    ),
    "REPLAY_STARTED": _definition(
        "REPLAY_STARTED",
        required_fields=("replay_id", "source_trace_ref", "replay_mode"),
    ),
    "REPLAY_COMPLETED": _definition(
        "REPLAY_COMPLETED",
        required_fields=("replay_id", "result_status", "state_digest"),
    ),
    "TRACE_WRITE_DEGRADED": _definition(
        "TRACE_WRITE_DEGRADED",
        required_fields=("storage_target", "degraded_reason"),
    ),
    "TRACE_SECRET_REDACTION_APPLIED": _definition(
        "TRACE_SECRET_REDACTION_APPLIED",
        required_fields=("redaction_reason", "redacted_fields"),
        one_of_fields=(("event_id", "payload_ref"),),
    ),
    "TRACE_WRITE_BLOCKED_SECRET_DETECTED": _definition(
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
        required_fields=("source_module", "blocked_payload_ref", "secret_kind", "blocking_reason"),
    ),
}

MVP0_EVENT_NAMES = frozenset(MVP0_EVENT_DEFINITIONS)


def get_event_definition(event_name: str) -> EventDefinition:
    try:
        return MVP0_EVENT_DEFINITIONS[event_name]
    except KeyError as exc:
        raise EventRegistryError(f"Unknown event_name: {event_name}") from exc
