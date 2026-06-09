from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
)


class AdapterEventHarnessError(ValueError):
    pass


ADAPTER_EVENT_HARNESS_EVENT_NAMES = frozenset(
    {
        "ADAPTER_HEALTHCHECK_FAILED",
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
    }
)
ADAPTER_EVENT_HARNESS_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})


class FakeRealAdapterEventHarness:
    """Deterministic MVP-3 Slice 2 event harness; it never probes providers."""

    def __init__(
        self,
        *,
        boundary: AdapterCallbackAppendBoundary,
        adapter_id: str,
        adapter_type: str,
        output_mode: str,
        source_module: str = "adapter_runtime",
        trace_redaction_level: str = "metadata_only",
    ) -> None:
        self._boundary = boundary
        self._adapter_id = _require_non_empty_string(adapter_id, "adapter_id")
        self._adapter_type = _require_non_empty_string(adapter_type, "adapter_type")
        self._output_mode = _validate_output_mode(output_mode)
        self._source_module = _require_non_empty_string(source_module, "source_module")
        self._trace_redaction_level = _require_non_empty_string(
            trace_redaction_level,
            "trace_redaction_level",
        )

    def emit_healthcheck_failed(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        failure_reason: str,
        health_status: str = "unhealthy",
        adapter_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._append(
            event_name="ADAPTER_HEALTHCHECK_FAILED",
            event_id=event_id,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_metadata=adapter_metadata,
            health_status=health_status,
            failure_reason=failure_reason,
        )

    def emit_request_retrying(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        adapter_request_id: str,
        retry_count: int,
        retry_reason: str,
        timeout_ms: int | None = None,
        adapter_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "adapter_request_id": adapter_request_id,
            "retry_count": retry_count,
            "retry_reason": retry_reason,
        }
        if timeout_ms is not None:
            fields["timeout_ms"] = timeout_ms
        return self._append(
            event_name="ADAPTER_REQUEST_RETRYING",
            event_id=event_id,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_metadata=adapter_metadata,
            **fields,
        )

    def emit_request_failed(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        adapter_request_id: str,
        failure_reason: str,
        retryable: bool,
        timeout_ms: int | None = None,
        adapter_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "adapter_request_id": adapter_request_id,
            "failure_reason": failure_reason,
            "retryable": retryable,
        }
        if timeout_ms is not None:
            fields["timeout_ms"] = timeout_ms
        return self._append(
            event_name="ADAPTER_REQUEST_FAILED",
            event_id=event_id,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_metadata=adapter_metadata,
            **fields,
        )

    def emit_output_validation_failed(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        adapter_request_id: str,
        schema_name: str,
        failure_reasons: Sequence[str],
        adapter_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(failure_reasons, (str, bytes)):
            raise AdapterEventHarnessError("failure_reasons must be a sequence of strings")
        return self._append(
            event_name="ADAPTER_OUTPUT_VALIDATION_FAILED",
            event_id=event_id,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_metadata=adapter_metadata,
            adapter_request_id=adapter_request_id,
            schema_name=schema_name,
            failure_reasons=list(failure_reasons),
        )

    def emit_output_degraded(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        degraded_reason: str,
        adapter_request_id: str | None = None,
        missing_capability: str | None = None,
        fallback_adapter_id: str | None = None,
        adapter_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {"degraded_reason": degraded_reason}
        if adapter_request_id is not None:
            fields["adapter_request_id"] = adapter_request_id
        if missing_capability is not None:
            fields["missing_capability"] = missing_capability
        if fallback_adapter_id is not None:
            fields["fallback_adapter_id"] = fallback_adapter_id
        return self._append(
            event_name="ADAPTER_OUTPUT_DEGRADED",
            event_id=event_id,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_metadata=adapter_metadata,
            **fields,
        )

    def _append(
        self,
        *,
        event_name: str,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        adapter_metadata: Mapping[str, Any] | None,
        **fields: Any,
    ) -> dict[str, Any]:
        event_fields: dict[str, Any] = {
            "event_name": event_name,
            "event_id": event_id,
            "source_module": self._source_module,
            "caused_by_event_id": caused_by_event_id,
            "created_monotonic_ms": created_monotonic_ms,
            "created_wall_clock_ms": created_wall_clock_ms,
            "trace_redaction_level": self._trace_redaction_level,
            "adapter_id": self._adapter_id,
            "adapter_type": self._adapter_type,
            "output_mode": self._output_mode,
            **fields,
        }
        if adapter_metadata is not None:
            event_fields["adapter_metadata"] = dict(adapter_metadata)
        return self._boundary.append_adapter_event(**event_fields)


def _require_non_empty_string(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise AdapterEventHarnessError(f"{field} must be a non-empty string")
    return value


def _validate_output_mode(output_mode: str) -> str:
    if output_mode not in ADAPTER_EVENT_HARNESS_OUTPUT_MODES:
        raise AdapterEventHarnessError(
            f"fake-real adapter event harness output_mode must be one of {sorted(ADAPTER_EVENT_HARNESS_OUTPUT_MODES)}"
        )
    return output_mode
