from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


class AsrAdapterContractError(ValueError):
    pass


ASR_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
ASR_TRANSCRIPT_OUTPUT_EVENT_NAME = "ASR_TRANSCRIPT_OUTPUT_EMITTED"


@dataclass(frozen=True)
class AsrTranscriptEmission:
    transcript_event: dict[str, Any]
    degraded_events: tuple[dict[str, Any], ...]


class AsrAdapterContract:
    """Provider-agnostic MVP-3 ASR final transcript/text projection contract."""

    def __init__(
        self,
        *,
        boundary: AdapterCallbackAppendBoundary,
        adapter_id: str,
        output_mode: str,
        source_module: str = "asr_adapter",
        trace_redaction_level: str = "metadata_only",
    ) -> None:
        self._boundary = boundary
        self._adapter_id = _require_non_empty_string(adapter_id, "adapter_id")
        self._output_mode = _validate_output_mode(output_mode)
        self._source_module = _require_non_empty_string(source_module, "source_module")
        self._trace_redaction_level = _require_non_empty_string(
            trace_redaction_level,
            "trace_redaction_level",
        )

    def emit_final_transcript(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        turn_committed_event: Mapping[str, Any],
        adapter_request_id: str,
        asr_frame_ref: str,
        text_ref: str,
        audio_timestamps_ref: str | None,
        streaming_output_supported: bool,
    ) -> AsrTranscriptEmission:
        _validate_turn_committed_event(turn_committed_event)
        if caused_by_event_id != str(turn_committed_event["event_id"]):
            raise AsrAdapterContractError(
                "ASR transcript output must be caused by TURN_INGRESS_COMMITTED"
            )

        adapter_request_id = _require_safe_ref(adapter_request_id, "adapter_request_id")
        asr_frame_ref = _require_safe_ref(asr_frame_ref, "asr_frame_ref")
        text_ref = _require_safe_ref(text_ref, "text_ref")
        if audio_timestamps_ref is not None:
            audio_timestamps_ref = _require_safe_ref(audio_timestamps_ref, "audio_timestamps_ref")
        if not isinstance(streaming_output_supported, bool):
            raise AsrAdapterContractError("streaming_output_supported must be a boolean")

        missing_capabilities = _missing_asr_capabilities(
            audio_timestamps_ref=audio_timestamps_ref,
            streaming_output_supported=streaming_output_supported,
        )
        if missing_capabilities and self._output_mode != "degraded":
            raise AsrAdapterContractError(
                "ASR output_mode must be degraded when timestamp or streaming capability is unavailable"
            )

        degraded_events = tuple(
            self._emit_degraded(
                event_id=f"{event_id}_{suffix}",
                caused_by_event_id=caused_by_event_id,
                created_monotonic_ms=created_monotonic_ms + index,
                created_wall_clock_ms=created_wall_clock_ms + index,
                adapter_request_id=adapter_request_id,
                missing_capability=missing_capability,
            )
            for index, (suffix, missing_capability) in enumerate(missing_capabilities, start=0)
        )

        fields: dict[str, Any] = {
            "event_name": ASR_TRANSCRIPT_OUTPUT_EVENT_NAME,
            "event_id": event_id,
            "source_module": self._source_module,
            "caused_by_event_id": caused_by_event_id,
            "created_monotonic_ms": created_monotonic_ms + len(degraded_events),
            "created_wall_clock_ms": created_wall_clock_ms + len(degraded_events),
            "trace_redaction_level": self._trace_redaction_level,
            "adapter_id": self._adapter_id,
            "adapter_type": "asr",
            "adapter_request_id": adapter_request_id,
            "turn_id": str(turn_committed_event["turn_id"]),
            "utterance_id": str(turn_committed_event["utterance_id"]),
            "input_modality": str(turn_committed_event["input_modality"]),
            "asr_frame_ref": asr_frame_ref,
            "text_ref": text_ref,
            "transcript_finality": "final",
            "timestamp_status": "available" if audio_timestamps_ref else "unavailable",
            "streaming_status": "supported" if streaming_output_supported else "unsupported_final_only",
            "output_mode": self._output_mode,
        }
        if turn_committed_event.get("audio_span_id") not in (None, ""):
            fields["audio_span_id"] = str(turn_committed_event["audio_span_id"])
        if turn_committed_event.get("text_span_id") not in (None, ""):
            fields["text_span_id"] = str(turn_committed_event["text_span_id"])
        if audio_timestamps_ref is not None:
            fields["audio_timestamps_ref"] = audio_timestamps_ref

        transcript_event = self._boundary.append_adapter_event(**fields)
        return AsrTranscriptEmission(transcript_event=transcript_event, degraded_events=degraded_events)

    def _emit_degraded(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        adapter_request_id: str,
        missing_capability: str,
    ) -> dict[str, Any]:
        return self._boundary.append_adapter_event(
            event_name="ADAPTER_OUTPUT_DEGRADED",
            event_id=event_id,
            source_module=self._source_module,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level=self._trace_redaction_level,
            adapter_id=self._adapter_id,
            adapter_type="asr",
            adapter_request_id=adapter_request_id,
            degraded_reason=missing_capability,
            missing_capability=missing_capability,
            output_mode=self._output_mode,
        )


def _missing_asr_capabilities(
    *,
    audio_timestamps_ref: str | None,
    streaming_output_supported: bool,
) -> tuple[tuple[str, str], ...]:
    missing: list[tuple[str, str]] = []
    if audio_timestamps_ref is None:
        missing.append(("missing_timestamps", "supports_audio_timestamps"))
    if not streaming_output_supported:
        missing.append(("missing_streaming_output", "supports_streaming_output"))
    return tuple(missing)


def _validate_turn_committed_event(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise AsrAdapterContractError("emit_final_transcript requires a TURN_INGRESS_COMMITTED event")
    if event.get("input_modality") != "audio":
        raise AsrAdapterContractError("ASR transcript output requires committed audio turn metadata")
    if event.get("audio_span_id") in (None, ""):
        raise AsrAdapterContractError("ASR transcript output requires audio_span_id")


def _validate_output_mode(output_mode: str) -> str:
    if output_mode not in ASR_OUTPUT_MODES:
        raise AsrAdapterContractError(
            f"ASR output_mode must be one of {sorted(ASR_OUTPUT_MODES)}"
        )
    return output_mode


def _require_non_empty_string(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise AsrAdapterContractError(f"{field} must be a non-empty string")
    return value


def _require_safe_ref(value: str, field: str) -> str:
    value = _require_non_empty_string(value, field)
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        raise AsrAdapterContractError(f"{field} must not contain credential-like content")
    return value
