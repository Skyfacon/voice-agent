from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from voice_agent.adapters.asr_contract import (
    ASR_OUTPUT_MODES,
    AsrAdapterContract,
    AsrTranscriptEmission,
)
from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN


class AsrNormalizationError(ValueError):
    pass


ASR_NORMALIZED_TRANSCRIPT_SCHEMA = "voice_agent.asr.normalized_transcript_candidate.v1"
ASR_LANGUAGE_STATUSES = frozenset({"available", "unavailable", "unknown"})
ASR_CONFIDENCE_STATUSES = frozenset({"available", "unavailable", "low_confidence"})
ASR_NBEST_STATUSES = frozenset({"available", "unavailable"})
ASR_TIMESTAMP_STATUSES = frozenset({"available", "unavailable"})
ASR_STREAMING_STATUSES = frozenset({"supported", "unsupported_final_only"})
ASR_QUALITY_FLAGS = frozenset(
    {
        "non_speech",
        "silence",
        "low_confidence",
        "clipped_start",
        "malformed_timing",
        "late_result_stale",
    }
)
FORBIDDEN_ASR_CANDIDATE_FIELDS = frozenset(
    {
        "raw_transcript",
        "transcript_text",
        "raw_text",
        "text",
        "provider_request",
        "provider_response",
        "provider_payload",
        "provider_schema",
        "request_body",
        "response_body",
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "prompt",
        "prompt_dump",
        "headers",
        "authorization",
        "api_key",
        "token",
        "credential",
        "password",
        "local_path",
        "resolved_arguments_ref",
        "semantic_commitment_ref",
        "confirmation_state",
        "tool_authorization",
        "tool_call",
        "ui_patch",
        "playback_span_id",
    }
)


@dataclass(frozen=True)
class AsrRequestBinding:
    adapter_request_id: str
    turn_id: str
    utterance_id: str
    audio_span_id: str
    input_modality: str
    turn_committed_event_id: str

    @classmethod
    def from_turn_committed_event(
        cls,
        turn_committed_event: Mapping[str, Any],
        *,
        adapter_request_id: str,
    ) -> AsrRequestBinding:
        if turn_committed_event.get("event_name") != "TURN_INGRESS_COMMITTED":
            raise AsrNormalizationError(
                "ASR request binding requires TURN_INGRESS_COMMITTED"
            )
        if turn_committed_event.get("input_modality") != "audio":
            raise AsrNormalizationError("ASR request binding requires input_modality=audio")
        for field in ("event_id", "turn_id", "utterance_id", "audio_span_id"):
            _require_non_empty_string(turn_committed_event.get(field), field)
        return cls(
            adapter_request_id=_require_safe_ref(adapter_request_id, "adapter_request_id"),
            turn_id=str(turn_committed_event["turn_id"]),
            utterance_id=str(turn_committed_event["utterance_id"]),
            audio_span_id=str(turn_committed_event["audio_span_id"]),
            input_modality="audio",
            turn_committed_event_id=str(turn_committed_event["event_id"]),
        )


@dataclass(frozen=True)
class NormalizedAsrTranscriptCandidate:
    adapter_request_id: str
    turn_id: str
    utterance_id: str
    audio_span_id: str
    input_modality: str
    turn_committed_event_id: str
    transcript_finality: str
    text_ref: str
    asr_frame_ref: str
    audio_timestamps_ref: str | None
    language_status: str
    language_ref: str | None
    confidence_status: str
    confidence_score: float | None
    confidence_ref: str | None
    nbest_status: str
    nbest_ref: str | None
    timestamp_status: str
    streaming_status: str
    normalization_status: str
    output_mode: str
    quality_flags: tuple[str, ...]


def normalize_asr_candidate(
    *,
    binding: AsrRequestBinding,
    asr_frame_ref: str,
    text_ref: str,
    audio_timestamps_ref: str | None = None,
    language_status: str = "unavailable",
    language_ref: str | None = None,
    confidence_status: str = "unavailable",
    confidence_score: float | None = None,
    confidence_ref: str | None = None,
    nbest_status: str = "unavailable",
    nbest_ref: str | None = None,
    timestamp_status: str | None = None,
    streaming_status: str = "supported",
    output_mode: str = "real",
    quality_flags: Sequence[str] = (),
) -> NormalizedAsrTranscriptCandidate:
    candidate = NormalizedAsrTranscriptCandidate(
        adapter_request_id=binding.adapter_request_id,
        turn_id=binding.turn_id,
        utterance_id=binding.utterance_id,
        audio_span_id=binding.audio_span_id,
        input_modality=binding.input_modality,
        turn_committed_event_id=binding.turn_committed_event_id,
        transcript_finality="final",
        text_ref=_require_safe_ref(text_ref, "text_ref"),
        asr_frame_ref=_require_safe_ref(asr_frame_ref, "asr_frame_ref"),
        audio_timestamps_ref=_optional_safe_ref(audio_timestamps_ref, "audio_timestamps_ref"),
        language_status=language_status,
        language_ref=_optional_safe_ref(language_ref, "language_ref"),
        confidence_status=confidence_status,
        confidence_score=confidence_score,
        confidence_ref=_optional_safe_ref(confidence_ref, "confidence_ref"),
        nbest_status=nbest_status,
        nbest_ref=_optional_safe_ref(nbest_ref, "nbest_ref"),
        timestamp_status=timestamp_status
        or ("available" if audio_timestamps_ref is not None else "unavailable"),
        streaming_status=streaming_status,
        normalization_status="normalized",
        output_mode=output_mode,
        quality_flags=_normalize_quality_flags(quality_flags),
    )
    return validate_normalized_asr_candidate(candidate)


def validate_normalized_asr_candidate(
    candidate: NormalizedAsrTranscriptCandidate | Mapping[str, Any],
) -> NormalizedAsrTranscriptCandidate:
    if isinstance(candidate, NormalizedAsrTranscriptCandidate):
        normalized = candidate
        mapping = asdict(candidate)
    else:
        mapping = dict(candidate)
        forbidden = sorted(set(mapping) & FORBIDDEN_ASR_CANDIDATE_FIELDS)
        if forbidden:
            raise AsrNormalizationError(f"forbidden ASR candidate fields: {forbidden}")
        allowed = set(NormalizedAsrTranscriptCandidate.__dataclass_fields__)
        unknown = sorted(set(mapping) - allowed)
        if unknown:
            raise AsrNormalizationError(f"unknown ASR candidate fields: {unknown}")
        normalized = NormalizedAsrTranscriptCandidate(**mapping)

    _validate_binding_values(normalized)
    _validate_status("language_status", normalized.language_status, ASR_LANGUAGE_STATUSES)
    _validate_status("confidence_status", normalized.confidence_status, ASR_CONFIDENCE_STATUSES)
    _validate_status("nbest_status", normalized.nbest_status, ASR_NBEST_STATUSES)
    _validate_status("timestamp_status", normalized.timestamp_status, ASR_TIMESTAMP_STATUSES)
    _validate_status("streaming_status", normalized.streaming_status, ASR_STREAMING_STATUSES)
    _validate_status("output_mode", normalized.output_mode, ASR_OUTPUT_MODES)
    if normalized.transcript_finality != "final":
        raise AsrNormalizationError("ASR transcript_finality must be final")
    if normalized.normalization_status != "normalized":
        raise AsrNormalizationError("ASR normalization_status must be normalized")
    if normalized.audio_timestamps_ref is None and normalized.timestamp_status != "unavailable":
        raise AsrNormalizationError("timestamp_status must be unavailable without audio_timestamps_ref")
    if normalized.audio_timestamps_ref is not None and normalized.timestamp_status != "available":
        raise AsrNormalizationError("timestamp_status must be available with audio_timestamps_ref")
    if normalized.timestamp_status == "unavailable" and normalized.output_mode != "degraded":
        raise AsrNormalizationError("timestamp unavailable ASR candidate must be degraded")
    if normalized.streaming_status == "unsupported_final_only" and normalized.output_mode != "degraded":
        raise AsrNormalizationError("final-only ASR candidate must be degraded")
    if normalized.confidence_score is not None:
        _validate_confidence_score(normalized.confidence_score)
    _normalize_quality_flags(normalized.quality_flags)
    for field, value in mapping.items():
        if field.endswith("_ref") or field in {"adapter_request_id"}:
            _optional_safe_ref(value, field)
    return normalized


def emit_normalized_asr_candidate(
    *,
    contract: AsrAdapterContract,
    candidate: NormalizedAsrTranscriptCandidate | Mapping[str, Any],
    turn_committed_event: Mapping[str, Any],
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> AsrTranscriptEmission:
    normalized = validate_normalized_asr_candidate(candidate)
    _validate_candidate_matches_turn(normalized, turn_committed_event)
    return contract.emit_final_transcript(
        event_id=event_id,
        caused_by_event_id=normalized.turn_committed_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        turn_committed_event=turn_committed_event,
        adapter_request_id=normalized.adapter_request_id,
        asr_frame_ref=normalized.asr_frame_ref,
        text_ref=normalized.text_ref,
        audio_timestamps_ref=normalized.audio_timestamps_ref,
        streaming_output_supported=normalized.streaming_status == "supported",
    )


def _validate_candidate_matches_turn(
    candidate: NormalizedAsrTranscriptCandidate,
    turn_committed_event: Mapping[str, Any],
) -> None:
    if turn_committed_event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise AsrNormalizationError("candidate emission requires TURN_INGRESS_COMMITTED")
    expected = {
        "event_id": candidate.turn_committed_event_id,
        "turn_id": candidate.turn_id,
        "utterance_id": candidate.utterance_id,
        "audio_span_id": candidate.audio_span_id,
        "input_modality": candidate.input_modality,
    }
    for field, expected_value in expected.items():
        if turn_committed_event.get(field) != expected_value:
            raise AsrNormalizationError(f"ASR candidate {field} does not match committed turn")


def _validate_binding_values(candidate: NormalizedAsrTranscriptCandidate) -> None:
    for field in (
        "adapter_request_id",
        "turn_id",
        "utterance_id",
        "audio_span_id",
        "turn_committed_event_id",
    ):
        _require_non_empty_string(getattr(candidate, field), field)
    if candidate.input_modality != "audio":
        raise AsrNormalizationError("ASR candidate input_modality must be audio")


def _validate_status(field: str, value: str, allowed: frozenset[str]) -> None:
    if value not in allowed:
        raise AsrNormalizationError(f"{field} must be one of {sorted(allowed)}")


def _validate_confidence_score(value: float) -> None:
    if not isinstance(value, (float, int)) or isinstance(value, bool) or value < 0 or value > 1:
        raise AsrNormalizationError("confidence_score must be between 0 and 1")


def _normalize_quality_flags(flags: Sequence[str]) -> tuple[str, ...]:
    if isinstance(flags, (str, bytes)):
        raise AsrNormalizationError("quality_flags must be a sequence of strings")
    normalized = tuple(flags)
    if not all(isinstance(flag, str) for flag in normalized):
        raise AsrNormalizationError("quality_flags must be a sequence of strings")
    unknown = sorted(set(normalized) - ASR_QUALITY_FLAGS)
    if unknown:
        raise AsrNormalizationError(f"unknown ASR quality_flags: {unknown}")
    return normalized


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise AsrNormalizationError(f"{field} must be a non-empty string")
    return value


def _optional_safe_ref(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_safe_ref(value, field)


def _require_safe_ref(value: Any, field: str) -> str:
    value = _require_non_empty_string(value, field)
    if CREDENTIAL_LIKE_REF_PATTERN.search(value) or _looks_like_local_path(value):
        raise AsrNormalizationError(f"{field} must be a safe ref")
    return value


def _looks_like_local_path(value: str) -> bool:
    return (
        value.startswith("/")
        or value.startswith("~/")
        or value.startswith("file://")
        or "\\Users\\" in value
        or "/Users/" in value
    )
