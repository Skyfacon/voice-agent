from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN, OUTPUT_MODES
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
    AdapterCallbackBoundaryError,
)


FAST_INTERACTION_SCHEMA_NAME = "voice_agent.fast_interaction.output.v1"
FOREGROUND_ACTS = frozenset({"ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY"})
RISK_CLASSES = frozenset({"LOW", "MEDIUM", "HIGH"})
ROUTE_DECISION_HINTS = frozenset(
    {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"}
)
TASK_FOCUS_HINTS = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "FOREGROUND_CHAT",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "NON_ASSISTANT",
        "AMBIGUOUS",
    }
)

FAST_INTERACTION_OUTPUT_EVENT_NAME = "FAST_INTERACTION_OUTPUT_EMITTED"
FOREGROUND_REPLY_CANDIDATE_EVENT_NAME = "FOREGROUND_REPLY_CANDIDATE_EMITTED"

FAST_INTERACTION_UNSAFE_REF_TERMS = (
    "audio/raw/",
    "audio/raw",
    "diagnostics/",
    "traces/",
    "replays/local/",
    "raw_audio",
    "raw_trace",
    "raw_prompt",
    "raw_transcript",
    "provider_body",
    "provider_payload",
    "provider_request",
    "provider_response",
    "provider_schema",
    "provider_text",
    "http://",
    "https://",
    "file://",
    "provider-url://",
    "provider://",
)

FAST_INTERACTION_TIMING_INT_OR_NONE_FIELDS = frozenset(
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
    }
)
FAST_INTERACTION_TIMING_BOOL_FIELDS = frozenset({"fast_interaction_ttft_available"})
FAST_INTERACTION_TIMING_STRING_VALUES = {
    "fast_interaction_timing_mode": frozenset({"streaming", "non_streaming"}),
    "fast_interaction_ttft_source": frozenset({"provider_stream_chunk", "not_available"}),
}
FAST_INTERACTION_TIMING_METADATA_FIELDS = frozenset(
    {
        *FAST_INTERACTION_TIMING_INT_OR_NONE_FIELDS,
        *FAST_INTERACTION_TIMING_BOOL_FIELDS,
        *FAST_INTERACTION_TIMING_STRING_VALUES,
    }
)


class FastInteractionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class FastInteractionBinding:
    turn_id: str
    utterance_id: str
    input_modality: str
    input_mode: str
    adapter_request_id: str
    source_event_ids: tuple[str, ...]
    audio_span_id: str | None = None
    audio_frame_ref: str | None = None
    audio_payload_ref: str | None = None
    asr_output_event_id: str | None = None
    asr_frame_ref: str | None = None
    text_ref: str | None = None

    @classmethod
    def from_turn_audio(
        cls,
        turn_committed_event: Mapping[str, Any],
        *,
        adapter_request_id: str,
        audio_frame_ref: str | None = None,
        audio_payload_ref: str | None = None,
    ) -> FastInteractionBinding:
        turn_event_id, turn_id, utterance_id, input_modality, audio_span_id = _committed_turn_context(
            turn_committed_event
        )
        if input_modality != "audio":
            raise FastInteractionValidationError(
                "Audio-native Fast Interaction binding requires input_modality='audio'"
            )
        safe_audio_frame_ref = _optional_safe_ref(audio_frame_ref, "audio_frame_ref")
        safe_audio_payload_ref = _optional_safe_ref(audio_payload_ref, "audio_payload_ref")
        if (safe_audio_frame_ref is None) == (safe_audio_payload_ref is None):
            raise FastInteractionValidationError(
                "Audio-native Fast Interaction binding requires exactly one safe audio ref"
            )

        return cls(
            turn_id=turn_id,
            utterance_id=utterance_id,
            input_modality=input_modality,
            input_mode="audio_native",
            audio_span_id=audio_span_id,
            adapter_request_id=_require_safe_token(adapter_request_id, "adapter_request_id"),
            audio_frame_ref=safe_audio_frame_ref,
            audio_payload_ref=safe_audio_payload_ref,
            source_event_ids=(turn_event_id,),
        )

    @classmethod
    def from_turn_and_asr(
        cls,
        turn_committed_event: Mapping[str, Any],
        *,
        asr_output_event: Mapping[str, Any] | None = None,
        adapter_request_id: str,
        **legacy_asr_refs: object,
    ) -> FastInteractionBinding:
        return cls.from_turn_and_asr_fallback(
            turn_committed_event,
            asr_output_event=asr_output_event,
            adapter_request_id=adapter_request_id,
            **legacy_asr_refs,
        )

    @classmethod
    def from_turn_and_asr_fallback(
        cls,
        turn_committed_event: Mapping[str, Any],
        *,
        asr_output_event: Mapping[str, Any] | None = None,
        adapter_request_id: str,
        **legacy_asr_refs: object,
    ) -> FastInteractionBinding:
        turn_event_id, turn_id, utterance_id, input_modality, audio_span_id = _committed_turn_context(
            turn_committed_event
        )
        if legacy_asr_refs or asr_output_event is None:
            raise FastInteractionValidationError(
                "ASR-text fallback Fast Interaction binding requires asr_output_event"
            )
        if asr_output_event.get("event_name") != "ASR_TRANSCRIPT_OUTPUT_EMITTED":
            raise FastInteractionValidationError(
                "ASR-text fallback Fast Interaction binding requires an ASR_TRANSCRIPT_OUTPUT_EMITTED event"
            )
        caused_by_event_id = _require_event_string(asr_output_event, "caused_by_event_id")
        if caused_by_event_id != turn_event_id:
            raise FastInteractionValidationError(
                "ASR output caused_by_event_id must match committed turn event_id"
            )
        asr_turn_id = _require_event_string(asr_output_event, "turn_id")
        asr_utterance_id = _require_event_string(asr_output_event, "utterance_id")
        asr_input_modality = _require_event_string(asr_output_event, "input_modality")
        if asr_turn_id != turn_id:
            raise FastInteractionValidationError("ASR output turn_id must match committed turn")
        if asr_utterance_id != utterance_id:
            raise FastInteractionValidationError(
                "ASR output utterance_id must match committed turn"
            )
        if asr_input_modality != input_modality:
            raise FastInteractionValidationError(
                "ASR output input_modality must match committed turn"
            )
        if input_modality == "audio":
            if audio_span_id is None:
                raise FastInteractionValidationError(
                    "Audio Fast Interaction binding requires committed turn audio_span_id"
                )
            asr_audio_span_id = _require_event_string(asr_output_event, "audio_span_id")
            if asr_audio_span_id != audio_span_id:
                raise FastInteractionValidationError(
                    "ASR output audio_span_id must match committed turn"
                )
        asr_output_event_id = _require_event_string(asr_output_event, "event_id")
        asr_frame_ref = _require_safe_ref(
            _require_event_string(asr_output_event, "asr_frame_ref"),
            "asr_frame_ref",
        )
        text_ref = _require_safe_ref(
            _require_event_string(asr_output_event, "text_ref"),
            "text_ref",
        )

        return cls(
            turn_id=turn_id,
            utterance_id=utterance_id,
            input_modality=input_modality,
            input_mode="asr_text_fallback",
            audio_span_id=audio_span_id,
            adapter_request_id=_require_safe_token(adapter_request_id, "adapter_request_id"),
            asr_output_event_id=asr_output_event_id,
            asr_frame_ref=asr_frame_ref,
            text_ref=text_ref,
            source_event_ids=(turn_event_id, asr_output_event_id),
        )


@dataclass(frozen=True)
class FastInteractionOutput:
    adapter_id: str
    route_hint_ref: str
    route_prelude_ref: str
    foreground_act: str
    final_fast_evidence_ref: str
    risk_tags: Sequence[str]
    risk_class: str
    confidence: float
    output_mode: str
    reply_candidate_ref: str | None = None
    candidate_id: str | None = None
    route_decision_hint: str | None = None
    task_focus_hint: str | None = None
    schema_name: str = FAST_INTERACTION_SCHEMA_NAME
    normalization_status: str = "normalized"

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", _require_safe_token(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self,
            "route_hint_ref",
            _require_safe_ref(self.route_hint_ref, "route_hint_ref"),
        )
        object.__setattr__(
            self,
            "route_prelude_ref",
            _require_safe_ref(self.route_prelude_ref, "route_prelude_ref"),
        )
        object.__setattr__(
            self,
            "final_fast_evidence_ref",
            _require_safe_ref(self.final_fast_evidence_ref, "final_fast_evidence_ref"),
        )
        if self.foreground_act not in FOREGROUND_ACTS:
            raise FastInteractionValidationError(
                f"foreground_act must be one of {sorted(FOREGROUND_ACTS)}"
            )
        if self.risk_class not in RISK_CLASSES:
            raise FastInteractionValidationError(f"risk_class must be one of {sorted(RISK_CLASSES)}")
        object.__setattr__(self, "confidence", _validate_confidence(self.confidence))
        if self.output_mode not in OUTPUT_MODES:
            raise FastInteractionValidationError(f"output_mode must be one of {sorted(OUTPUT_MODES)}")
        if self.schema_name != FAST_INTERACTION_SCHEMA_NAME:
            raise FastInteractionValidationError(f"schema_name must be {FAST_INTERACTION_SCHEMA_NAME}")
        if self.normalization_status != "normalized":
            raise FastInteractionValidationError("normalization_status must be normalized")
        object.__setattr__(self, "risk_tags", _validate_risk_tags(self.risk_tags))
        if self.route_decision_hint is not None:
            if self.route_decision_hint not in ROUTE_DECISION_HINTS:
                raise FastInteractionValidationError(
                    f"route_decision_hint must be one of {sorted(ROUTE_DECISION_HINTS)}"
                )
        if self.task_focus_hint is not None:
            if self.task_focus_hint not in TASK_FOCUS_HINTS:
                raise FastInteractionValidationError(
                    f"task_focus_hint must be one of {sorted(TASK_FOCUS_HINTS)}"
                )
        if self.reply_candidate_ref is not None:
            object.__setattr__(
                self,
                "reply_candidate_ref",
                _require_safe_ref(self.reply_candidate_ref, "reply_candidate_ref"),
            )
            object.__setattr__(
                self,
                "candidate_id",
                _require_safe_token(self.candidate_id, "candidate_id"),
            )
        elif self.candidate_id is not None:
            object.__setattr__(self, "candidate_id", _require_safe_token(self.candidate_id, "candidate_id"))


@dataclass(frozen=True)
class FastInteractionEmission:
    output_event: dict[str, Any]
    candidate_event: dict[str, Any] | None


def emit_fast_interaction_events(
    *,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    output: FastInteractionOutput,
    output_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    candidate_event_id: str | None = None,
    source_module: str = "fast_interaction_adapter",
    candidate_source_module: str = "foreground_buffer",
    trace_redaction_level: str = "metadata_only",
    timing_snapshot: Any | None = None,
) -> FastInteractionEmission:
    output_event_id = _require_safe_token(output_event_id, "output_event_id")
    source_module = _require_safe_token(source_module, "source_module")
    trace_redaction_level = _require_safe_token(trace_redaction_level, "trace_redaction_level")
    candidate_event_id_token: str | None = None
    if output.reply_candidate_ref is not None:
        if candidate_event_id is None:
            raise FastInteractionValidationError(
                "candidate_event_id is required when reply_candidate_ref is present"
            )
        if output.candidate_id is None:
            raise FastInteractionValidationError(
                "candidate_id is required when reply_candidate_ref is present"
            )
        candidate_event_id_token = _require_safe_token(candidate_event_id, "candidate_event_id")
        candidate_source_module = _require_safe_token(
            candidate_source_module,
            "candidate_source_module",
        )
    preflight_event_ids = (output_event_id,) if candidate_event_id_token is None else (
        output_event_id,
        candidate_event_id_token,
    )
    try:
        boundary.require_event_ids_available(*preflight_event_ids)
    except AdapterCallbackBoundaryError as exc:
        raise FastInteractionValidationError(str(exc)) from exc

    optional_output_fields: dict[str, Any] = {}
    if output.route_decision_hint is not None:
        optional_output_fields["route_decision_hint"] = output.route_decision_hint
    if output.task_focus_hint is not None:
        optional_output_fields["task_focus_hint"] = output.task_focus_hint
    if binding.audio_frame_ref is not None:
        optional_output_fields["audio_frame_ref"] = binding.audio_frame_ref
    if binding.audio_payload_ref is not None:
        optional_output_fields["audio_payload_ref"] = binding.audio_payload_ref
    if binding.asr_frame_ref is not None:
        optional_output_fields["asr_frame_ref"] = binding.asr_frame_ref
    if binding.text_ref is not None:
        optional_output_fields["text_ref"] = binding.text_ref
    if timing_snapshot is not None:
        optional_output_fields.update(_timing_metadata(timing_snapshot))

    caused_by_event_id = binding.asr_output_event_id or binding.source_event_ids[-1]

    output_event = boundary.append_adapter_event(
        event_name=FAST_INTERACTION_OUTPUT_EVENT_NAME,
        event_id=output_event_id,
        source_module=source_module,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level=trace_redaction_level,
        adapter_id=output.adapter_id,
        adapter_type="fast_interaction",
        adapter_request_id=binding.adapter_request_id,
        turn_id=binding.turn_id,
        utterance_id=binding.utterance_id,
        route_hint_ref=output.route_hint_ref,
        route_prelude_ref=output.route_prelude_ref,
        foreground_act=output.foreground_act,
        final_fast_evidence_ref=output.final_fast_evidence_ref,
        schema_name=output.schema_name,
        normalization_status=output.normalization_status,
        output_mode=output.output_mode,
        input_modality=binding.input_modality,
        input_mode=binding.input_mode,
        fast_interaction_input_mode=binding.input_mode,
        source_event_ids=binding.source_event_ids,
        risk_tags=output.risk_tags,
        risk_class=output.risk_class,
        confidence=output.confidence,
        **optional_output_fields,
    )
    if output.reply_candidate_ref is None:
        return FastInteractionEmission(output_event=output_event, candidate_event=None)

    candidate_event = boundary.append_adapter_event(
        event_name=FOREGROUND_REPLY_CANDIDATE_EVENT_NAME,
        event_id=str(candidate_event_id_token),
        source_module=candidate_source_module,
        caused_by_event_id=str(output_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 1,
        created_wall_clock_ms=created_wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        candidate_id=output.candidate_id,
        fast_interaction_output_event_id=str(output_event["event_id"]),
        turn_id=binding.turn_id,
        utterance_id=binding.utterance_id,
        candidate_ref=output.reply_candidate_ref,
        candidate_status="complete",
        input_mode=binding.input_mode,
        fast_interaction_input_mode=binding.input_mode,
        source_event_ids=binding.source_event_ids,
        risk_tags=output.risk_tags,
        confidence=output.confidence,
    )
    return FastInteractionEmission(output_event=output_event, candidate_event=candidate_event)


def _committed_turn_context(
    turn_committed_event: Mapping[str, Any],
) -> tuple[str, str, str, str, str | None]:
    if turn_committed_event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise FastInteractionValidationError(
            "Fast Interaction binding requires a TURN_INGRESS_COMMITTED event"
        )

    return (
        _require_event_string(turn_committed_event, "event_id"),
        _require_event_string(turn_committed_event, "turn_id"),
        _require_event_string(turn_committed_event, "utterance_id"),
        _require_event_string(turn_committed_event, "input_modality"),
        _optional_safe_token(turn_committed_event.get("audio_span_id"), "audio_span_id"),
    )


def _require_safe_ref(value: str | None, field: str) -> str:
    token = _require_safe_token(value, field)
    if "://" not in token:
        raise FastInteractionValidationError(f"{field} must be a safe ref")
    return token


def _optional_safe_ref(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _require_safe_ref(value, field)


def _timing_metadata(timing_snapshot: Any) -> dict[str, Any]:
    to_prefixed_metadata = getattr(timing_snapshot, "to_prefixed_metadata", None)
    if not callable(to_prefixed_metadata):
        raise FastInteractionValidationError("timing_snapshot must expose to_prefixed_metadata")
    try:
        raw_metadata = to_prefixed_metadata("fast_interaction")
    except (TypeError, ValueError) as exc:
        raise FastInteractionValidationError(str(exc)) from exc
    if not isinstance(raw_metadata, Mapping):
        raise FastInteractionValidationError("timing metadata must be a mapping")

    metadata: dict[str, Any] = {}
    for key, value in raw_metadata.items():
        if not isinstance(key, str) or key not in FAST_INTERACTION_TIMING_METADATA_FIELDS:
            raise FastInteractionValidationError("timing metadata contains unsupported field")
        if key in FAST_INTERACTION_TIMING_INT_OR_NONE_FIELDS:
            if value is None:
                metadata[key] = None
            elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                metadata[key] = value
            else:
                raise FastInteractionValidationError(f"{key} must be a non-negative integer or null")
        elif key in FAST_INTERACTION_TIMING_BOOL_FIELDS:
            if not isinstance(value, bool):
                raise FastInteractionValidationError(f"{key} must be a boolean")
            metadata[key] = value
        elif key in FAST_INTERACTION_TIMING_STRING_VALUES:
            if not isinstance(value, str):
                raise FastInteractionValidationError(f"{key} must be a string")
            _reject_unsafe_content(value, key)
            if value not in FAST_INTERACTION_TIMING_STRING_VALUES[key]:
                raise FastInteractionValidationError(f"{key} has unsupported value")
            metadata[key] = value
    return metadata


def _require_event_string(event: Mapping[str, Any], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or value == "":
        raise FastInteractionValidationError(f"{field} must be a non-empty string")
    return _require_safe_token(value, field)


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise FastInteractionValidationError(f"{field} must be a non-empty string")
    _reject_unsafe_content(value, field)
    return value


def _optional_safe_token(value: object, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _require_safe_token(value, field)


def _reject_unsafe_content(value: str, field: str) -> None:
    for view in _ref_safety_views(value):
        lowered = view.lower()
        normalized = lowered.replace("-", "_").replace(" ", "_")
        if (
            CREDENTIAL_LIKE_REF_PATTERN.search(view)
            or lowered.startswith(("/", "~", "\\"))
            or any(
                term in lowered or term in normalized
                for term in FAST_INTERACTION_UNSAFE_REF_TERMS
            )
        ):
            raise FastInteractionValidationError(f"{field} must not contain unsafe content")


def _validate_confidence(value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FastInteractionValidationError("confidence must be numeric")
    confidence = float(value)
    if confidence < 0.0 or confidence > 1.0:
        raise FastInteractionValidationError("confidence must be between 0 and 1")
    return confidence


def _validate_risk_tags(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise FastInteractionValidationError("risk_tags must be a string sequence")
    tags = tuple(_require_safe_token(tag, "risk_tags") for tag in value)
    return tags


def _ref_safety_views(value: str) -> tuple[str, ...]:
    views = [value]
    decoded = value
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        views.append(next_decoded)
        decoded = next_decoded
    return tuple(views)
