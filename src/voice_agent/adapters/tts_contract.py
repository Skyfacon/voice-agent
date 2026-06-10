from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.capabilities import (
    CREDENTIAL_LIKE_REF_PATTERN,
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


class TtsSynthesisAdapterContractError(ValueError):
    pass


TTS_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
TTS_SYNTHESIS_OUTPUT_EVENT_NAME = "TTS_SYNTHESIS_OUTPUT_EMITTED"
TTS_UNSAFE_REF_TERMS = frozenset(
    {
        "raw_audio",
        "audio/raw",
        "data:",
        "traces/",
        "diagnostics/",
        "replays/local",
    }
)
TTS_APPROVED_CHECK_EVENT_NAMES = frozenset(
    {
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
    }
)


@dataclass(frozen=True)
class TtsSynthesisEmission:
    synthesis_event: dict[str, Any]
    degraded_events: tuple[dict[str, Any], ...]


class TtsSynthesisAdapterContract:
    """Provider-agnostic MVP-3 TTS synthesis ref contract."""

    def __init__(
        self,
        *,
        boundary: AdapterCallbackAppendBoundary,
        adapter_id: str,
        capability_matrix: Mapping[str, Any],
        output_mode: str,
        source_module: str = "tts_adapter",
        trace_redaction_level: str = "metadata_only",
    ) -> None:
        self._boundary = boundary
        self._adapter_id = _require_non_empty_string(adapter_id, "adapter_id")
        self._declared_supports_tts_truncate = _validate_tts_capability_matrix(
            capability_matrix,
            adapter_id=self._adapter_id,
        )
        self._output_mode = _validate_output_mode(output_mode)
        self._source_module = _require_non_empty_string(source_module, "source_module")
        self._trace_redaction_level = _require_non_empty_string(
            trace_redaction_level,
            "trace_redaction_level",
        )

    def emit_synthesis_output(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        approved_check_event: Mapping[str, Any],
        adapter_request_id: str,
        audio_ref: str | None,
        tts_stream_ref: str | None,
        audio_format_ref: str,
        synthesis_result_ref: str,
        truncate_supported: bool,
    ) -> TtsSynthesisEmission:
        _validate_approved_check_event(approved_check_event)
        if caused_by_event_id != str(approved_check_event["event_id"]):
            raise TtsSynthesisAdapterContractError(
                "TTS synthesis output must be caused by the approved SpokenPlan check event"
            )
        if not isinstance(truncate_supported, bool):
            raise TtsSynthesisAdapterContractError("truncate_supported must be a boolean")

        adapter_request_id = _require_safe_ref(adapter_request_id, "adapter_request_id")
        audio_ref = _optional_safe_ref(audio_ref, "audio_ref")
        tts_stream_ref = _optional_safe_ref(tts_stream_ref, "tts_stream_ref")
        if audio_ref is None and tts_stream_ref is None:
            raise TtsSynthesisAdapterContractError("TTS synthesis output requires audio_ref or tts_stream_ref")
        audio_format_ref = _require_safe_ref(audio_format_ref, "audio_format_ref")
        synthesis_result_ref = _require_safe_ref(synthesis_result_ref, "synthesis_result_ref")

        if truncate_supported and not self._declared_supports_tts_truncate:
            raise TtsSynthesisAdapterContractError(
                "TTS truncate_supported cannot exceed declared supports_tts_truncate capability"
            )
        if not truncate_supported and self._output_mode != "degraded":
            raise TtsSynthesisAdapterContractError(
                "TTS output_mode must be degraded when truncate capability is unavailable"
            )

        degraded_events = ()
        if not truncate_supported:
            degraded_events = (
                self._emit_degraded(
                    event_id=f"{event_id}_missing_tts_truncate",
                    caused_by_event_id=caused_by_event_id,
                    created_monotonic_ms=created_monotonic_ms,
                    created_wall_clock_ms=created_wall_clock_ms,
                    adapter_request_id=adapter_request_id,
                    missing_capability="supports_tts_truncate",
                ),
            )

        fields: dict[str, Any] = {
            "event_name": TTS_SYNTHESIS_OUTPUT_EVENT_NAME,
            "event_id": event_id,
            "source_module": self._source_module,
            "caused_by_event_id": caused_by_event_id,
            "created_monotonic_ms": created_monotonic_ms + len(degraded_events),
            "created_wall_clock_ms": created_wall_clock_ms + len(degraded_events),
            "trace_redaction_level": self._trace_redaction_level,
            "adapter_id": self._adapter_id,
            "adapter_type": "tts",
            "adapter_request_id": adapter_request_id,
            "spoken_plan_id": str(approved_check_event["spoken_plan_id"]),
            "approved_check_event_id": str(approved_check_event["event_id"]),
            "normalization_status": "normalized",
            "audio_format_ref": audio_format_ref,
            "synthesis_result_ref": synthesis_result_ref,
            "truncate_status": "supported" if truncate_supported else "unsupported_blocked",
            "output_mode": self._output_mode,
        }
        if audio_ref is not None:
            fields["audio_ref"] = audio_ref
        if tts_stream_ref is not None:
            fields["tts_stream_ref"] = tts_stream_ref
        for optional_field in ("task_id", "plan_version"):
            if approved_check_event.get(optional_field) not in (None, ""):
                fields[optional_field] = approved_check_event[optional_field]

        synthesis_event = self._boundary.append_adapter_event(**fields)
        return TtsSynthesisEmission(
            synthesis_event=synthesis_event,
            degraded_events=degraded_events,
        )

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
            adapter_type="tts",
            adapter_request_id=adapter_request_id,
            degraded_reason=missing_capability,
            missing_capability=missing_capability,
            output_mode=self._output_mode,
        )


def _validate_approved_check_event(event: Mapping[str, Any]) -> None:
    event_name = event.get("event_name")
    if event_name not in TTS_APPROVED_CHECK_EVENT_NAMES:
        raise TtsSynthesisAdapterContractError(
            "approved_check_event must be a passed SpokenPlan check event"
        )
    for field in ("event_id", "spoken_plan_id"):
        if field not in event or event[field] in (None, ""):
            raise TtsSynthesisAdapterContractError(f"approved_check_event requires {field}")


def _validate_output_mode(output_mode: str) -> str:
    if output_mode not in TTS_OUTPUT_MODES:
        raise TtsSynthesisAdapterContractError(
            f"TTS output_mode must be one of {sorted(TTS_OUTPUT_MODES)}"
        )
    return output_mode


def _validate_tts_capability_matrix(capability_matrix: Mapping[str, Any], *, adapter_id: str) -> bool:
    try:
        matrix = validate_capability_matrix(capability_matrix)
    except CapabilityValidationError as exc:
        raise TtsSynthesisAdapterContractError(str(exc)) from exc
    if matrix.get("adapter_id") != adapter_id:
        raise TtsSynthesisAdapterContractError("capability_matrix adapter_id must match contract adapter_id")
    if matrix.get("adapter_type") != "tts":
        raise TtsSynthesisAdapterContractError("capability_matrix must declare adapter_type=tts")
    if matrix.get("supports_tts") is not True:
        raise TtsSynthesisAdapterContractError("capability_matrix must declare supports_tts=true")
    if matrix.get("supports_audio_output") is not True:
        raise TtsSynthesisAdapterContractError("capability_matrix must declare supports_audio_output=true")
    return bool(matrix["supports_tts_truncate"])


def _require_non_empty_string(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise TtsSynthesisAdapterContractError(f"{field} must be a non-empty string")
    return value


def _require_safe_ref(value: str, field: str) -> str:
    value = _require_non_empty_string(value, field)
    if any(_contains_unsafe_ref_content(view) for view in _ref_safety_views(value)):
        raise TtsSynthesisAdapterContractError(f"{field} must be a safe ref")
    return value


def _optional_safe_ref(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _require_safe_ref(value, field)


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


def _contains_unsafe_ref_content(value: str) -> bool:
    lowered = value.lower()
    return CREDENTIAL_LIKE_REF_PATTERN.search(value) is not None or any(
        term in lowered for term in TTS_UNSAFE_REF_TERMS
    )
