from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import time
from typing import Any

from voice_agent.adapters.fast_interaction_contract import (
    FAST_INTERACTION_SCHEMA_NAME,
    ROUTE_DECISION_HINTS,
    TASK_FOCUS_HINTS,
    FastInteractionBinding,
    FastInteractionEmission,
    FastInteractionOutput,
    FastInteractionValidationError,
    emit_fast_interaction_events,
)
from voice_agent.adapters.fast_interaction_live_transport import (
    FastInteractionLiveTransportError,
)
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
    AdapterCallbackBoundaryError,
)


_REQUIRED_KEYS = frozenset(
    {
        "route_hint",
        "route_prelude",
        "foreground_act",
        "final_fast_evidence",
        "risk_tags",
        "risk_class",
        "confidence",
        "output_mode",
        "schema_name",
        "boundary_assertions",
    }
)
_BOUNDARY_ASSERTIONS = {
    "candidate_is_not_semantic_commitment": True,
    "may_authorize_tools": False,
    "may_execute_tools": False,
    "may_accept_confirmation": False,
    "may_mutate_slowtask_facts": False,
    "runtime_gate_owns_display": True,
}
_LOCAL_REPLY_CANDIDATE_BY_REF: dict[str, str] = {}
_FAST_INTERACTION_TIMING_INT_OR_NONE_FIELDS = frozenset(
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
_FAST_INTERACTION_TIMING_BOOL_FIELDS = frozenset({"fast_interaction_ttft_available"})
_FAST_INTERACTION_TIMING_STRING_VALUES = {
    "fast_interaction_timing_mode": frozenset({"streaming", "non_streaming"}),
    "fast_interaction_ttft_source": frozenset({"provider_stream_chunk", "not_available"}),
}
_FAST_INTERACTION_TIMING_FIELDS = frozenset(
    {
        *_FAST_INTERACTION_TIMING_INT_OR_NONE_FIELDS,
        *_FAST_INTERACTION_TIMING_BOOL_FIELDS,
        *_FAST_INTERACTION_TIMING_STRING_VALUES,
    }
)


def resolve_fast_interaction_reply_candidate_ref(candidate_ref: str) -> str | None:
    if not isinstance(candidate_ref, str) or candidate_ref == "":
        return None
    return _LOCAL_REPLY_CANDIDATE_BY_REF.get(candidate_ref)


@dataclass(frozen=True)
class FastInteractionProviderTextEmissionResult:
    success: bool
    emission: FastInteractionEmission | None = None
    validation_failed_event: dict[str, Any] | None = None


@dataclass(frozen=True)
class FastInteractionAdapterRequestResult:
    success: bool
    emission: FastInteractionEmission | None = None
    validation_failed_event: dict[str, Any] | None = None
    request_failed_event: dict[str, Any] | None = None
    failure_category: str | None = None
    failure_ref: str | None = None
    fast_interaction_latency_metadata: dict[str, int | bool | str | None] | None = None
    provider_http_ms: int | None = None
    parse_validate_emit_ms: int | None = None
    total_ms: int | None = None


@dataclass(frozen=True)
class FastInteractionProviderCallOutcome:
    completion: Any | None = None
    failure_category: str | None = None
    failure_ref: str | None = None
    provider_http_ms: int | None = None
    total_ms: int | None = None


@dataclass(frozen=True)
class _TransportCallSelection:
    call: Callable[..., Any]
    failure_category: str | None = None


@dataclass(frozen=True)
class _TimingMetadataView:
    timing_snapshot: Any
    parse_validate_emit_ms: int | None
    total_ms: int | None

    def to_prefixed_metadata(self, prefix: str) -> dict[str, int | bool | str | None]:
        raw_metadata = _safe_raw_timing_metadata(self.timing_snapshot, prefix)
        metadata = (
            {}
            if raw_metadata is None
            else _filter_timing_metadata(raw_metadata)
        )
        metadata[f"{prefix}_parse_validate_emit_ms"] = self.parse_validate_emit_ms
        metadata[f"{prefix}_total_ms"] = self.total_ms
        return metadata


@dataclass(frozen=True)
class _PreparedProviderTextEmission:
    success: bool
    output: FastInteractionOutput | None = None
    reply_candidate: str | None = None
    validation_failure_reasons: tuple[str, ...] = ()


def run_fast_interaction_adapter_request(
    *,
    transport: object,
    request_payload: Mapping[str, Any],
    audio_bytes: bytes | None = None,
    audio_format: str | None = None,
    turn_ingress_monotonic_ms: int,
    allow_asr_text_fallback: bool = False,
    credential_handle: object,
    credential_value: str,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    adapter_id: str,
    ref_prefix: str,
    output_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    timeout_ms: int,
    model_alias: str,
    candidate_event_id: str | None = None,
    validation_failed_event_id: str | None = None,
    request_failed_event_id: str | None = None,
) -> FastInteractionAdapterRequestResult:
    outcome = call_fast_interaction_provider(
        transport=transport,
        request_payload=request_payload,
        audio_bytes=audio_bytes,
        audio_format=audio_format,
        turn_ingress_monotonic_ms=turn_ingress_monotonic_ms,
        allow_asr_text_fallback=allow_asr_text_fallback,
        credential_handle=credential_handle,
        credential_value=credential_value,
        binding=binding,
        timeout_ms=timeout_ms,
        model_alias=model_alias,
    )
    return emit_fast_interaction_provider_outcome(
        outcome=outcome,
        boundary=boundary,
        binding=binding,
        adapter_id=adapter_id,
        ref_prefix=ref_prefix,
        output_event_id=output_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        timeout_ms=timeout_ms,
        candidate_event_id=candidate_event_id,
        validation_failed_event_id=validation_failed_event_id,
        request_failed_event_id=request_failed_event_id,
    )


def call_fast_interaction_provider(
    *,
    transport: object,
    request_payload: Mapping[str, Any],
    audio_bytes: bytes | None,
    audio_format: str | None,
    turn_ingress_monotonic_ms: int,
    allow_asr_text_fallback: bool,
    credential_handle: object,
    credential_value: str,
    binding: FastInteractionBinding,
    timeout_ms: int,
    model_alias: str,
) -> FastInteractionProviderCallOutcome:
    """Run provider I/O without parsing, emitting events, or touching a journal."""

    started = time.monotonic()
    selection = _select_transport_call(
        transport=transport,
        binding=binding,
        audio_bytes=audio_bytes,
        audio_format=audio_format,
        allow_asr_text_fallback=allow_asr_text_fallback,
    )
    if selection.failure_category is not None:
        failure_category = _safe_transport_failure_category(selection.failure_category)
        return FastInteractionProviderCallOutcome(
            failure_category=failure_category,
            failure_ref=_runtime_failure_ref(failure_category),
            total_ms=_elapsed_ms(started),
        )

    provider_started = time.monotonic()
    try:
        completion = selection.call(
            request_payload=request_payload,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            credential_handle=credential_handle,
            credential_value=credential_value,
            adapter_request_id=binding.adapter_request_id,
            timeout_ms=timeout_ms,
            model_alias=model_alias,
            turn_ingress_monotonic_ms=turn_ingress_monotonic_ms,
        )
    except FastInteractionLiveTransportError as exc:
        provider_http_ms = _elapsed_ms(provider_started)
        failure_category = _safe_transport_failure_category(exc.category)
        return FastInteractionProviderCallOutcome(
            failure_category=failure_category,
            failure_ref=_runtime_failure_ref(failure_category),
            provider_http_ms=provider_http_ms,
            total_ms=_elapsed_ms(started),
        )

    provider_http_ms = _elapsed_ms(provider_started)
    total_ms = _elapsed_ms(started)
    return FastInteractionProviderCallOutcome(
        completion=completion,
        provider_http_ms=provider_http_ms,
        total_ms=total_ms,
    )


def emit_fast_interaction_provider_outcome(
    *,
    outcome: FastInteractionProviderCallOutcome,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    adapter_id: str,
    ref_prefix: str,
    output_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    timeout_ms: int,
    candidate_event_id: str | None = None,
    validation_failed_event_id: str | None = None,
    request_failed_event_id: str | None = None,
) -> FastInteractionAdapterRequestResult:
    """Parse and emit one provider outcome on the coordinator/journal thread."""

    if outcome.failure_category is not None:
        coordinator_started = time.monotonic()
        failure_category = _safe_transport_failure_category(outcome.failure_category)
        event = _emit_request_failed(
            boundary=boundary,
            binding=binding,
            adapter_id=adapter_id,
            event_id=request_failed_event_id or f"{output_event_id}_request_failed",
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            failure_reason=failure_category,
            timeout_ms=timeout_ms,
        )
        parse_validate_emit_ms = _elapsed_ms(coordinator_started)
        total_ms = _sum_known_ms(outcome.total_ms, parse_validate_emit_ms)
        latency_metadata = _latency_metadata(
            binding=binding,
            timing_snapshot=None,
            timed_out=failure_category == "provider_timeout",
            failure_category=failure_category,
            parse_validate_emit_ms=parse_validate_emit_ms,
            total_ms=total_ms,
        )
        return FastInteractionAdapterRequestResult(
            success=False,
            request_failed_event=event,
            failure_category=failure_category,
            failure_ref=outcome.failure_ref or _runtime_failure_ref(failure_category),
            fast_interaction_latency_metadata=latency_metadata,
            provider_http_ms=outcome.provider_http_ms,
            parse_validate_emit_ms=parse_validate_emit_ms,
            total_ms=total_ms,
        )

    completion = outcome.completion
    if completion is None:
        raise FastInteractionValidationError("provider outcome completion is required")
    parse_started = time.monotonic()
    provider_text = getattr(completion, "provider_text", "")
    timing_snapshot = getattr(completion, "timing", None)
    prepared = _prepare_provider_text_emission(
        provider_text=provider_text,
        adapter_id=adapter_id,
        ref_prefix=ref_prefix,
    )
    event_timing_view = (
        _TimingMetadataView(
            timing_snapshot,
            parse_validate_emit_ms=None,
            total_ms=None,
        )
        if timing_snapshot is not None
        else None
    )
    result = _emit_prepared_provider_text_emission(
        prepared=prepared,
        boundary=boundary,
        binding=binding,
        adapter_id=adapter_id,
        ref_prefix=ref_prefix,
        output_event_id=output_event_id,
        candidate_event_id=candidate_event_id,
        validation_failed_event_id=validation_failed_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        timing_snapshot=event_timing_view,
    )
    parse_validate_emit_ms = _elapsed_ms(parse_started)
    total_ms = _sum_known_ms(outcome.total_ms, parse_validate_emit_ms)
    result_timing_view = (
        _TimingMetadataView(
            timing_snapshot,
            parse_validate_emit_ms=parse_validate_emit_ms,
            total_ms=total_ms,
        )
        if timing_snapshot is not None
        else None
    )
    latency_metadata = _latency_metadata(
        binding=binding,
        timing_snapshot=result_timing_view,
        timed_out=False,
        failure_category=None if result.success else "provider_output_validation_failed",
        parse_validate_emit_ms=parse_validate_emit_ms,
        total_ms=total_ms,
    )
    return FastInteractionAdapterRequestResult(
        success=result.success,
        emission=result.emission,
        validation_failed_event=result.validation_failed_event,
        failure_category=None if result.success else "provider_output_validation_failed",
        failure_ref=None if result.success else _runtime_failure_ref("provider_output_validation_failed"),
        fast_interaction_latency_metadata=latency_metadata,
        provider_http_ms=outcome.provider_http_ms,
        parse_validate_emit_ms=parse_validate_emit_ms,
        total_ms=total_ms,
    )


def _select_transport_call(
    *,
    transport: object,
    binding: FastInteractionBinding,
    audio_bytes: bytes | None,
    audio_format: str | None,
    allow_asr_text_fallback: bool,
) -> _TransportCallSelection:
    if binding.input_mode == "audio_native":
        if not isinstance(audio_bytes, bytes) or audio_bytes == b"":
            return _TransportCallSelection(_noop_transport_call, "audio_input_missing")
        if not isinstance(audio_format, str) or audio_format == "":
            return _TransportCallSelection(_noop_transport_call, "audio_format_missing")
        complete_audio_with_timing = getattr(transport, "complete_audio_with_timing", None)
        if not callable(complete_audio_with_timing):
            return _TransportCallSelection(_noop_transport_call, "transport_method_unavailable")

        def call(**kwargs: Any) -> Any:
            return complete_audio_with_timing(
                request_payload=kwargs["request_payload"],
                audio_bytes=kwargs["audio_bytes"],
                audio_format=kwargs["audio_format"],
                credential_handle=kwargs["credential_handle"],
                credential_value=kwargs["credential_value"],
                adapter_request_id=kwargs["adapter_request_id"],
                timeout_ms=kwargs["timeout_ms"],
                model_alias=kwargs["model_alias"],
                turn_ingress_monotonic_ms=kwargs["turn_ingress_monotonic_ms"],
            )

        return _TransportCallSelection(call)

    if binding.input_mode == "asr_text_fallback":
        if not allow_asr_text_fallback:
            return _TransportCallSelection(_noop_transport_call, "asr_text_fallback_not_enabled")
        complete_with_timing = getattr(transport, "complete_with_timing", None)
        if not callable(complete_with_timing):
            return _TransportCallSelection(_noop_transport_call, "transport_method_unavailable")

        def call(**kwargs: Any) -> Any:
            return complete_with_timing(
                request_payload=kwargs["request_payload"],
                credential_handle=kwargs["credential_handle"],
                credential_value=kwargs["credential_value"],
                adapter_request_id=kwargs["adapter_request_id"],
                timeout_ms=kwargs["timeout_ms"],
                model_alias=kwargs["model_alias"],
                turn_ingress_monotonic_ms=kwargs["turn_ingress_monotonic_ms"],
            )

        return _TransportCallSelection(call)

    return _TransportCallSelection(_noop_transport_call, "invalid_input_mode")


def _noop_transport_call(**_kwargs: Any) -> Any:
    raise AssertionError("unreachable transport selection failure call")


def _request_failed_result(
    *,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    adapter_id: str,
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    failure_category: str,
    timeout_ms: int,
    started: float,
) -> FastInteractionAdapterRequestResult:
    safe_category = _safe_transport_failure_category(failure_category)
    event = _emit_request_failed(
        boundary=boundary,
        binding=binding,
        adapter_id=adapter_id,
        event_id=event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        failure_reason=safe_category,
        timeout_ms=timeout_ms,
    )
    total_ms = _elapsed_ms(started)
    return FastInteractionAdapterRequestResult(
        success=False,
        request_failed_event=event,
        failure_category=safe_category,
        failure_ref=_runtime_failure_ref(safe_category),
        fast_interaction_latency_metadata=_latency_metadata(
            binding=binding,
            timing_snapshot=None,
            timed_out=safe_category == "provider_timeout",
            failure_category=safe_category,
            total_ms=total_ms,
        ),
        total_ms=total_ms,
    )


def emit_fast_interaction_from_provider_text(
    *,
    provider_text: str,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    adapter_id: str,
    ref_prefix: str,
    output_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    candidate_event_id: str | None = None,
    validation_failed_event_id: str | None = None,
    timing_snapshot: Any | None = None,
) -> FastInteractionProviderTextEmissionResult:
    prepared = _prepare_provider_text_emission(
        provider_text=provider_text,
        adapter_id=adapter_id,
        ref_prefix=ref_prefix,
    )
    return _emit_prepared_provider_text_emission(
        prepared=prepared,
        boundary=boundary,
        binding=binding,
        adapter_id=adapter_id,
        ref_prefix=ref_prefix,
        output_event_id=output_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        candidate_event_id=candidate_event_id,
        validation_failed_event_id=validation_failed_event_id,
        timing_snapshot=timing_snapshot,
    )


def _prepare_provider_text_emission(
    *,
    provider_text: str,
    adapter_id: str,
    ref_prefix: str,
) -> _PreparedProviderTextEmission:
    failure_reasons: list[str] = []
    payload: Mapping[str, Any] | None = None

    if _is_unsafe_ref_prefix(ref_prefix):
        failure_reasons.append("unsafe_ref_prefix")

    try:
        payload = _parse_strict_json_object(provider_text)
    except _ProviderTextValidationError as exc:
        failure_reasons.extend(exc.failure_reasons)

    if payload is not None:
        failure_reasons.extend(_validate_payload(payload))

    if failure_reasons:
        return _PreparedProviderTextEmission(
            success=False,
            validation_failure_reasons=tuple(_dedupe(failure_reasons)),
        )

    assert payload is not None
    reply_candidate = payload.get("reply_candidate")
    has_candidate = isinstance(reply_candidate, str) and reply_candidate.strip() != ""
    candidate_id = f"candidate_{_slug(ref_prefix)}" if has_candidate else None
    output = FastInteractionOutput(
        adapter_id=adapter_id,
        route_hint_ref=f"route-hint://synthetic/{ref_prefix}",
        route_prelude_ref=f"route-prelude://synthetic/{ref_prefix}",
        foreground_act=str(payload["foreground_act"]),
        final_fast_evidence_ref=f"fast-evidence://synthetic/{ref_prefix}",
        risk_tags=_risk_tags(payload["risk_tags"]),
        risk_class=str(payload["risk_class"]),
        confidence=_confidence(payload["confidence"]),
        output_mode=str(payload["output_mode"]),
        reply_candidate_ref=(
            f"foreground-candidate://synthetic/{ref_prefix}" if has_candidate else None
        ),
        candidate_id=candidate_id,
        route_decision_hint=_route_decision_hint(payload["route_hint"]),
        task_focus_hint=_task_focus_hint(payload["route_hint"]),
    )
    return _PreparedProviderTextEmission(
        success=True,
        output=output,
        reply_candidate=str(reply_candidate) if has_candidate else None,
    )


def _emit_prepared_provider_text_emission(
    *,
    prepared: _PreparedProviderTextEmission,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    adapter_id: str,
    ref_prefix: str,
    output_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    candidate_event_id: str | None = None,
    validation_failed_event_id: str | None = None,
    timing_snapshot: Any | None = None,
) -> FastInteractionProviderTextEmissionResult:
    validation_failed_event_id = validation_failed_event_id or f"{output_event_id}_validation_failed"
    if not prepared.success:
        event = _emit_validation_failed(
            boundary=boundary,
            binding=binding,
            adapter_id=adapter_id,
            event_id=validation_failed_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            failure_reasons=prepared.validation_failure_reasons,
        )
        return FastInteractionProviderTextEmissionResult(
            success=False,
            validation_failed_event=event,
        )

    assert prepared.output is not None
    emission = emit_fast_interaction_events(
        boundary=boundary,
        binding=binding,
        output=prepared.output,
        output_event_id=output_event_id,
        candidate_event_id=candidate_event_id if prepared.reply_candidate is not None else None,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        timing_snapshot=timing_snapshot,
    )
    if prepared.reply_candidate is not None and prepared.output.reply_candidate_ref is not None:
        _LOCAL_REPLY_CANDIDATE_BY_REF[prepared.output.reply_candidate_ref] = prepared.reply_candidate
    return FastInteractionProviderTextEmissionResult(success=True, emission=emission)


def _latency_metadata(
    *,
    binding: FastInteractionBinding,
    timing_snapshot: Any | None,
    timed_out: bool,
    failure_category: str | None,
    parse_validate_emit_ms: int | None = None,
    total_ms: int | None,
) -> dict[str, int | bool | str | None]:
    metadata: dict[str, int | bool | str | None] = {
        "fast_interaction_input_mode": binding.input_mode,
        "fast_interaction_timed_out": timed_out,
        "fast_interaction_adapter_start_offset_ms": None,
        "fast_interaction_provider_request_start_offset_ms": None,
        "fast_interaction_provider_first_chunk_offset_ms": None,
        "fast_interaction_provider_full_response_offset_ms": None,
        "fast_interaction_adapter_event_emit_offset_ms": None,
        "fast_interaction_provider_ttft_ms": None,
        "fast_interaction_provider_full_response_ms": None,
        "fast_interaction_provider_generation_ms": None,
        "fast_interaction_stream_decode_ms": None,
        "fast_interaction_parse_validate_emit_ms": parse_validate_emit_ms,
        "fast_interaction_total_ms": total_ms,
        "fast_interaction_timing_mode": "non_streaming",
        "fast_interaction_ttft_available": False,
        "fast_interaction_ttft_source": "not_available",
    }
    if timing_snapshot is not None:
        to_prefixed_metadata = getattr(timing_snapshot, "to_prefixed_metadata", None)
        if callable(to_prefixed_metadata):
            raw_timing_metadata = _safe_raw_timing_metadata(
                timing_snapshot,
                "fast_interaction",
            )
            if raw_timing_metadata is not None:
                metadata.update(_filter_timing_metadata(raw_timing_metadata))
    metadata["fast_interaction_parse_validate_emit_ms"] = parse_validate_emit_ms
    metadata["fast_interaction_total_ms"] = total_ms
    metadata["fast_interaction_timed_out"] = timed_out
    metadata["fast_interaction_input_mode"] = binding.input_mode
    if failure_category is not None:
        metadata["fast_interaction_failure_category"] = _safe_transport_failure_category(
            failure_category
        )
    return metadata


def _safe_raw_timing_metadata(timing_snapshot: Any, prefix: str) -> Mapping[str, object] | None:
    to_prefixed_metadata = getattr(timing_snapshot, "to_prefixed_metadata", None)
    if not callable(to_prefixed_metadata):
        return None
    try:
        raw_metadata = to_prefixed_metadata(prefix)
    except Exception:
        return None
    if not isinstance(raw_metadata, Mapping):
        return None
    return raw_metadata


def _filter_timing_metadata(
    raw_metadata: Mapping[str, object],
    *,
    parse_validate_emit_ms: int | None = None,
) -> dict[str, int | bool | str | None]:
    metadata: dict[str, int | bool | str | None] = {}
    for key in sorted(_FAST_INTERACTION_TIMING_FIELDS):
        if key not in raw_metadata:
            continue
        value = raw_metadata[key]
        if key in _FAST_INTERACTION_TIMING_INT_OR_NONE_FIELDS:
            if value is None:
                metadata[key] = None
            elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                metadata[key] = value
        elif key in _FAST_INTERACTION_TIMING_BOOL_FIELDS:
            if isinstance(value, bool):
                metadata[key] = value
        elif key in _FAST_INTERACTION_TIMING_STRING_VALUES:
            if (
                isinstance(value, str)
                and value in _FAST_INTERACTION_TIMING_STRING_VALUES[key]
                and not _contains_unsafe_string(value)
            ):
                metadata[key] = value
    if parse_validate_emit_ms is not None:
        metadata["fast_interaction_parse_validate_emit_ms"] = max(
            0,
            int(parse_validate_emit_ms),
        )
    return metadata


def _sum_known_ms(*values: int | None) -> int | None:
    if any(value is None for value in values):
        return None
    return sum(int(value) for value in values if value is not None)


class _ProviderTextValidationError(ValueError):
    def __init__(self, failure_reasons: Sequence[str]) -> None:
        self.failure_reasons = list(failure_reasons)
        super().__init__("fast_interaction_provider_text_validation_failed")


def _parse_strict_json_object(provider_text: str) -> Mapping[str, Any]:
    if not isinstance(provider_text, str) or provider_text.strip() == "":
        raise _ProviderTextValidationError(("provider_text_empty",))
    stripped = provider_text.strip()
    if stripped.startswith("```") or "```" in stripped:
        raise _ProviderTextValidationError(("fenced_markdown",))

    decoder = json.JSONDecoder()
    try:
        parsed, index = decoder.raw_decode(stripped)
    except json.JSONDecodeError:
        raise _ProviderTextValidationError(("provider_text_json_parse_failed",)) from None
    if stripped[index:].strip() != "":
        raise _ProviderTextValidationError(("provider_text_not_strict_json_object",))
    if not isinstance(parsed, Mapping):
        raise _ProviderTextValidationError(("provider_text_not_json_object",))
    return parsed


def _validate_payload(payload: Mapping[str, Any]) -> list[str]:
    failure_reasons: list[str] = []
    for key in sorted(_REQUIRED_KEYS):
        if key not in payload:
            failure_reasons.append("missing_required_key")
            break
    schema_name = payload.get("schema_name")
    if schema_name != FAST_INTERACTION_SCHEMA_NAME:
        failure_reasons.append("schema_name_mismatch")
    assertions = payload.get("boundary_assertions")
    if not isinstance(assertions, Mapping):
        failure_reasons.append("invalid_boundary_assertion")
    else:
        for key, expected in _BOUNDARY_ASSERTIONS.items():
            if assertions.get(key) is not expected:
                failure_reasons.append("invalid_boundary_assertion")
                break
    for field in ("route_hint", "route_prelude", "final_fast_evidence"):
        if field in payload:
            value = payload[field]
            if not isinstance(value, Mapping):
                failure_reasons.append("invalid_object_field")
            elif _contains_unsafe_provider_value(value):
                failure_reasons.append("unsafe_provider_field")
            elif field == "route_hint" and _invalid_route_hint(value):
                failure_reasons.append("invalid_route_hint")
    if "reply_candidate" in payload:
        reply_candidate = payload["reply_candidate"]
        if reply_candidate is not None and not isinstance(reply_candidate, str):
            failure_reasons.append("invalid_reply_candidate")
        elif isinstance(reply_candidate, str) and _contains_unsafe_string(reply_candidate):
            failure_reasons.append("unsafe_reply_candidate")
    try:
        if _REQUIRED_KEYS.issubset(payload.keys()):
            FastInteractionOutput(
                adapter_id="fast_interaction_validation_probe",
                route_hint_ref="route-hint://synthetic/fast-interaction/validation-probe",
                route_prelude_ref="route-prelude://synthetic/fast-interaction/validation-probe",
                foreground_act=str(payload["foreground_act"]),
                final_fast_evidence_ref=(
                    "fast-evidence://synthetic/fast-interaction/validation-probe"
                ),
                risk_tags=_risk_tags(payload["risk_tags"]),
                risk_class=str(payload["risk_class"]),
                confidence=_confidence(payload["confidence"]),
                output_mode=str(payload["output_mode"]),
            )
    except (FastInteractionValidationError, TypeError, ValueError):
        failure_reasons.append("schema_validation_failed")
    return _dedupe(failure_reasons)


def _emit_validation_failed(
    *,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    adapter_id: str,
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    failure_reasons: Sequence[str],
) -> dict[str, Any]:
    safe_reasons = _dedupe(_safe_failure_reason(reason) for reason in failure_reasons)
    try:
        boundary.require_event_ids_available(event_id)
    except AdapterCallbackBoundaryError as exc:
        raise FastInteractionValidationError(str(exc)) from exc
    return boundary.append_adapter_event(
        event_name="ADAPTER_OUTPUT_VALIDATION_FAILED",
        event_id=event_id,
        source_module="fast_interaction_adapter",
        caused_by_event_id=binding.asr_output_event_id or binding.source_event_ids[-1],
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        adapter_id=adapter_id,
        adapter_type="fast_interaction",
        adapter_request_id=binding.adapter_request_id,
        schema_name=FAST_INTERACTION_SCHEMA_NAME,
        failure_reasons=list(safe_reasons),
        output_mode="degraded",
    )


def _emit_request_failed(
    *,
    boundary: AdapterCallbackAppendBoundary,
    binding: FastInteractionBinding,
    adapter_id: str,
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    failure_reason: str,
    timeout_ms: int,
) -> dict[str, Any]:
    safe_reason = _safe_transport_failure_category(failure_reason)
    try:
        boundary.require_event_ids_available(event_id)
    except AdapterCallbackBoundaryError as exc:
        raise FastInteractionValidationError(str(exc)) from exc
    return boundary.append_adapter_event(
        event_name="ADAPTER_REQUEST_FAILED",
        event_id=event_id,
        source_module="fast_interaction_adapter",
        caused_by_event_id=binding.asr_output_event_id or binding.source_event_ids[-1],
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        adapter_id=adapter_id,
        adapter_type="fast_interaction",
        adapter_request_id=binding.adapter_request_id,
        failure_reason=safe_reason,
        retryable=False,
        timeout_ms=timeout_ms,
        output_mode="degraded",
    )


def _risk_tags(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise FastInteractionValidationError("risk_tags must be a sequence")
    return tuple(str(item) for item in value)


def _confidence(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FastInteractionValidationError("confidence must be numeric")
    return float(value)


def _is_unsafe_ref_prefix(value: object) -> bool:
    if not isinstance(value, str) or value == "":
        return True
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    return (
        "://" in value
        or value.startswith(("/", "~", "\\"))
        or any(
            marker in lowered
            for marker in (
                "audio/raw",
                "diagnostics",
                "traces",
                "replays/local",
                "raw_audio",
                "raw_prompt",
                "provider_body",
                "provider_payload",
                "provider_request",
                "provider_response",
                "provider_schema",
                "provider_text",
                "http",
                "file",
                "secret",
                "token",
                "password",
                "authorization",
            )
        )
    )


def _contains_unsafe_provider_value(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _contains_unsafe_string(str(key)) or _contains_unsafe_provider_value(child):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_unsafe_provider_value(item) for item in value)
    if isinstance(value, str):
        return _contains_unsafe_string(value)
    return False


def _contains_unsafe_string(value: str) -> bool:
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    return any(
        marker in lowered
        for marker in (
            "raw_audio",
            "raw_prompt",
            "raw_provider",
            "provider_body",
            "provider_payload",
            "provider_request",
            "provider_response",
            "provider_schema",
            "provider_text",
            "authorization",
            "api_key",
            "token",
            "password",
            "secret",
            "cookie",
            "bearer",
            "audio/raw",
            "diagnostics",
            "traces",
            "replays/local",
            "file://",
            "/users/",
            "\\users\\",
            "/private/",
            ".env",
            "http://",
            "https://",
        )
    )


def _invalid_route_hint(value: Mapping[str, Any]) -> bool:
    route_decision = value.get("router_decision_candidate")
    if route_decision not in (None, "") and route_decision not in ROUTE_DECISION_HINTS:
        return True
    task_focus = value.get("task_focus_hint")
    if task_focus not in (None, "") and task_focus not in TASK_FOCUS_HINTS:
        return True
    return False


def _route_decision_hint(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    route_decision = value.get("router_decision_candidate")
    if route_decision in ROUTE_DECISION_HINTS:
        return str(route_decision)
    return None


def _task_focus_hint(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    explicit = value.get("task_focus_hint")
    if explicit in TASK_FOCUS_HINTS:
        return str(explicit)
    route_decision = value.get("router_decision_candidate")
    if route_decision == "FAST_ONLY":
        return "FOREGROUND_CHAT"
    if route_decision == "SPAWN_SLOW_TASK":
        return "NEW_TASK_CANDIDATE"
    if route_decision == "PATCH_ACTIVE_SLOW_TASK":
        return "ACTIVE_TASK_PATCH"
    if route_decision == "IGNORE":
        return "NON_ASSISTANT"
    return None


def _safe_transport_failure_category(value: object) -> str:
    if not isinstance(value, str) or value == "":
        return "provider_request_failed"
    safe = _safe_failure_reason(value)
    if safe in {
        "credential_handle_invalid",
        "credential_handle_opaque",
        "credential_like_content",
        "credential_missing",
        "invalid_budget",
        "invalid_field",
        "local_only_artifact_ref",
        "provider_request_failed",
        "provider_response_parse_failed",
        "provider_response_text_missing",
        "provider_timeout",
        "request_payload_invalid",
        "transport_config_invalid",
        "asr_text_fallback_not_enabled",
        "audio_format_missing",
        "audio_format_unsupported",
        "audio_input_invalid",
        "audio_input_missing",
        "invalid_input_mode",
        "transport_method_unavailable",
        "unsafe_ref",
    }:
        return safe
    return "provider_request_failed"


def _runtime_failure_ref(category: str) -> str:
    return f"validation://synthetic/fast-interaction/runtime/{_slug(category)}"


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _safe_failure_reason(value: str) -> str:
    slug = _slug(value).replace("-", "_")
    return slug or "validation_failed"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in str(value)).strip("-") or "unknown"


def _dedupe(values: Sequence[str] | Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
