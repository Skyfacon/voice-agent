from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


class ThinkerAdapterContractError(ValueError):
    pass


THINKER_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
THINKER_SEMANTIC_FRAME_OUTPUT_EVENT_NAME = "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"
THINKER_SEMANTIC_FRAME_SCHEMA = "voice_agent.semantic_frame.v1"

OPTIONAL_SEMANTIC_REF_FIELDS = (
    (
        "semantic_close_ref",
        "semantic_close_status",
        "supports_semantic_close",
        "missing_semantic_close",
    ),
    (
        "assistant_directedness_ref",
        "assistant_directedness_status",
        "supports_assistant_directedness",
        "missing_assistant_directedness",
    ),
    (
        "emotion_ref",
        "emotion_status",
        "supports_emotion",
        "missing_emotion",
    ),
    (
        "audio_caption_ref",
        "audio_caption_status",
        "supports_audio_caption",
        "missing_audio_caption",
    ),
)


@dataclass(frozen=True)
class ThinkerSemanticFrameEmission:
    thinker_event: dict[str, Any]
    degraded_events: tuple[dict[str, Any], ...]


class ThinkerAdapterContract:
    """Provider-agnostic MVP-3 Thinker SemanticFrame output contract."""

    def __init__(
        self,
        *,
        boundary: AdapterCallbackAppendBoundary,
        adapter_id: str,
        output_mode: str,
        source_module: str = "thinker_adapter",
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

    def emit_semantic_frame(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        turn_committed_event: Mapping[str, Any],
        adapter_request_id: str,
        semantic_frame_ref: str,
        semantic_summary_ref: str,
        semantic_close_ref: str | None,
        assistant_directedness_ref: str | None,
        emotion_ref: str | None,
        audio_caption_ref: str | None,
        task_focus_hint: str | None = None,
        task_like: bool | None = None,
        complexity_hint: str | None = None,
        focus_confidence: float | None = None,
        evidence_uncertainty: str | None = None,
    ) -> ThinkerSemanticFrameEmission:
        _validate_turn_committed_event(turn_committed_event)
        if caused_by_event_id != str(turn_committed_event["event_id"]):
            raise ThinkerAdapterContractError(
                "Thinker semantic frame output must be caused by TURN_INGRESS_COMMITTED"
            )

        adapter_request_id = _require_safe_ref(adapter_request_id, "adapter_request_id")
        semantic_frame_ref = _require_safe_ref(semantic_frame_ref, "semantic_frame_ref")
        semantic_summary_ref = _require_safe_ref(semantic_summary_ref, "semantic_summary_ref")
        optional_refs = {
            "semantic_close_ref": _optional_safe_ref(semantic_close_ref, "semantic_close_ref"),
            "assistant_directedness_ref": _optional_safe_ref(
                assistant_directedness_ref,
                "assistant_directedness_ref",
            ),
            "emotion_ref": _optional_safe_ref(emotion_ref, "emotion_ref"),
            "audio_caption_ref": _optional_safe_ref(audio_caption_ref, "audio_caption_ref"),
        }

        missing_capabilities = _missing_optional_capabilities(optional_refs)
        if missing_capabilities and self._output_mode != "degraded":
            missing = ", ".join(missing_capability for _, missing_capability in missing_capabilities)
            raise ThinkerAdapterContractError(
                "Thinker output_mode must be degraded when optional semantic fields are unavailable: "
                f"{missing}"
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
            "event_name": THINKER_SEMANTIC_FRAME_OUTPUT_EVENT_NAME,
            "event_id": event_id,
            "source_module": self._source_module,
            "caused_by_event_id": caused_by_event_id,
            "created_monotonic_ms": created_monotonic_ms + len(degraded_events),
            "created_wall_clock_ms": created_wall_clock_ms + len(degraded_events),
            "trace_redaction_level": self._trace_redaction_level,
            "adapter_id": self._adapter_id,
            "adapter_type": "thinker",
            "adapter_request_id": adapter_request_id,
            "turn_id": str(turn_committed_event["turn_id"]),
            "utterance_id": str(turn_committed_event["utterance_id"]),
            "input_modality": str(turn_committed_event["input_modality"]),
            "semantic_frame_schema": THINKER_SEMANTIC_FRAME_SCHEMA,
            "normalization_status": "normalized",
            "semantic_frame_ref": semantic_frame_ref,
            "semantic_summary_ref": semantic_summary_ref,
            "output_mode": self._output_mode,
        }
        for ref_field, status_field, _, _ in OPTIONAL_SEMANTIC_REF_FIELDS:
            ref_value = optional_refs[ref_field]
            fields[status_field] = "available" if ref_value is not None else "unavailable"
            if ref_value is not None:
                fields[ref_field] = ref_value

        if turn_committed_event.get("audio_span_id") not in (None, ""):
            fields["audio_span_id"] = str(turn_committed_event["audio_span_id"])
        if turn_committed_event.get("text_span_id") not in (None, ""):
            fields["text_span_id"] = str(turn_committed_event["text_span_id"])
        if task_focus_hint is not None:
            fields["task_focus_hint"] = _require_non_empty_string(task_focus_hint, "task_focus_hint")
        if task_like is not None:
            if not isinstance(task_like, bool):
                raise ThinkerAdapterContractError("task_like must be a boolean when present")
            fields["task_like"] = task_like
        if complexity_hint is not None:
            fields["complexity_hint"] = _require_non_empty_string(complexity_hint, "complexity_hint")
        if focus_confidence is not None:
            fields["focus_confidence"] = _validate_confidence(focus_confidence, "focus_confidence")
        if evidence_uncertainty is not None:
            fields["evidence_uncertainty"] = _require_non_empty_string(
                evidence_uncertainty,
                "evidence_uncertainty",
            )

        thinker_event = self._boundary.append_adapter_event(**fields)
        return ThinkerSemanticFrameEmission(
            thinker_event=thinker_event,
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
            adapter_type="thinker",
            adapter_request_id=adapter_request_id,
            degraded_reason=missing_capability,
            missing_capability=missing_capability,
            output_mode=self._output_mode,
        )


def _missing_optional_capabilities(optional_refs: Mapping[str, str | None]) -> tuple[tuple[str, str], ...]:
    missing: list[tuple[str, str]] = []
    for ref_field, _, missing_capability, suffix in OPTIONAL_SEMANTIC_REF_FIELDS:
        if optional_refs[ref_field] is None:
            missing.append((suffix, missing_capability))
    return tuple(missing)


def _validate_turn_committed_event(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise ThinkerAdapterContractError("emit_semantic_frame requires a TURN_INGRESS_COMMITTED event")


def _validate_output_mode(output_mode: str) -> str:
    if output_mode not in THINKER_OUTPUT_MODES:
        raise ThinkerAdapterContractError(
            f"Thinker output_mode must be one of {sorted(THINKER_OUTPUT_MODES)}"
        )
    return output_mode


def _require_non_empty_string(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ThinkerAdapterContractError(f"{field} must be a non-empty string")
    return value


def _require_safe_ref(value: str, field: str) -> str:
    value = _require_non_empty_string(value, field)
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        raise ThinkerAdapterContractError(f"{field} must not contain credential-like content")
    return value


def _optional_safe_ref(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _require_safe_ref(value, field)


def _validate_confidence(value: float, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ThinkerAdapterContractError(f"{field} must be numeric")
    confidence = float(value)
    if confidence < 0.0 or confidence > 1.0:
        raise ThinkerAdapterContractError(f"{field} must be between 0 and 1")
    return confidence
