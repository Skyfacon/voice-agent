from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


class SlowLLMStructuredOutputContractError(ValueError):
    pass


SLOW_LLM_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
SLOW_LLM_STRUCTURED_OUTPUT_EVENT_NAME = "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED"
SLOW_LLM_STRUCTURED_OUTPUT_SCHEMA = "voice_agent.slowtask.structured_output.v1"
SLOW_LLM_ALLOWED_SLOWTASK_BINDING_EVENTS = frozenset(
    {
        "PLANNING_STARTED",
        "PLANNING_RESTARTED",
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_RESOLVED",
    }
)


@dataclass(frozen=True)
class SlowLLMStructuredOutputEmission:
    structured_output_event: dict[str, Any]


class SlowLLMStructuredOutputContract:
    """Provider-agnostic MVP-3 Slow LLM structured output contract."""

    def __init__(
        self,
        *,
        boundary: AdapterCallbackAppendBoundary,
        adapter_id: str,
        output_mode: str,
        source_module: str = "slow_llm_adapter",
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

    def emit_structured_output(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        slowtask_event: Mapping[str, Any],
        adapter_request_id: str,
        slow_llm_output_ref: str,
        structured_output_ref: str,
        validation_result_ref: str,
        resolved_arguments_ref: str | None = None,
        provenance_ref: str | None = None,
    ) -> SlowLLMStructuredOutputEmission:
        _validate_slowtask_binding_event(slowtask_event)
        if caused_by_event_id != str(slowtask_event["event_id"]):
            raise SlowLLMStructuredOutputContractError(
                "Slow LLM structured output must be caused by the bound SlowTask event"
            )

        adapter_request_id = _require_safe_ref(adapter_request_id, "adapter_request_id")
        slow_llm_output_ref = _require_safe_ref(slow_llm_output_ref, "slow_llm_output_ref")
        structured_output_ref = _require_safe_ref(structured_output_ref, "structured_output_ref")
        validation_result_ref = _require_safe_ref(validation_result_ref, "validation_result_ref")
        optional_refs = {
            "resolved_arguments_ref": _optional_safe_ref(
                resolved_arguments_ref,
                "resolved_arguments_ref",
            ),
            "provenance_ref": _optional_safe_ref(provenance_ref, "provenance_ref"),
        }
        if (optional_refs["resolved_arguments_ref"] is None) != (optional_refs["provenance_ref"] is None):
            raise SlowLLMStructuredOutputContractError(
                "resolved_arguments_ref and provenance_ref must be emitted together"
            )

        fields: dict[str, Any] = {
            "event_name": SLOW_LLM_STRUCTURED_OUTPUT_EVENT_NAME,
            "event_id": event_id,
            "source_module": self._source_module,
            "caused_by_event_id": caused_by_event_id,
            "created_monotonic_ms": created_monotonic_ms,
            "created_wall_clock_ms": created_wall_clock_ms,
            "trace_redaction_level": self._trace_redaction_level,
            "adapter_id": self._adapter_id,
            "adapter_type": "slow_llm",
            "adapter_request_id": adapter_request_id,
            "task_id": str(slowtask_event["task_id"]),
            "plan_version": int(slowtask_event["plan_version"]),
            "task_event_seq": int(slowtask_event["task_event_seq"]),
            "schema_name": SLOW_LLM_STRUCTURED_OUTPUT_SCHEMA,
            "normalization_status": "normalized",
            "slow_llm_output_ref": slow_llm_output_ref,
            "structured_output_ref": structured_output_ref,
            "validation_result_ref": validation_result_ref,
            "output_mode": self._output_mode,
        }
        for field, value in optional_refs.items():
            if value is not None:
                fields[field] = value

        structured_output_event = self._boundary.append_adapter_event(**fields)
        return SlowLLMStructuredOutputEmission(
            structured_output_event=structured_output_event,
        )

    def emit_output_validation_failed(
        self,
        *,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        slowtask_event: Mapping[str, Any],
        adapter_request_id: str,
        failure_reasons: Sequence[str],
    ) -> dict[str, Any]:
        _validate_slowtask_binding_event(slowtask_event)
        if caused_by_event_id != str(slowtask_event["event_id"]):
            raise SlowLLMStructuredOutputContractError(
                "Slow LLM validation failure must be caused by the bound SlowTask event"
            )
        failure_reasons = _validate_failure_reasons(failure_reasons)

        return self._boundary.append_adapter_event(
            event_name="ADAPTER_OUTPUT_VALIDATION_FAILED",
            event_id=event_id,
            source_module=self._source_module,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level=self._trace_redaction_level,
            adapter_id=self._adapter_id,
            adapter_type="slow_llm",
            adapter_request_id=_require_safe_ref(adapter_request_id, "adapter_request_id"),
            task_id=str(slowtask_event["task_id"]),
            plan_version=int(slowtask_event["plan_version"]),
            task_event_seq=int(slowtask_event["task_event_seq"]),
            schema_name=SLOW_LLM_STRUCTURED_OUTPUT_SCHEMA,
            failure_reasons=failure_reasons,
            output_mode=self._output_mode,
        )


def _validate_slowtask_binding_event(event: Mapping[str, Any]) -> None:
    event_name = event.get("event_name")
    if not isinstance(event_name, str):
        raise SlowLLMStructuredOutputContractError("slowtask_event requires event_name")
    if event_name not in SLOW_LLM_ALLOWED_SLOWTASK_BINDING_EVENTS:
        raise SlowLLMStructuredOutputContractError(
            "slowtask_event must use an allowed SlowTask event_name"
        )
    for field in ("event_id", "task_id", "plan_version", "task_event_seq"):
        if field not in event or event[field] in (None, ""):
            raise SlowLLMStructuredOutputContractError(f"slowtask_event requires {field}")
    for numeric_field in ("plan_version", "task_event_seq"):
        value = event[numeric_field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SlowLLMStructuredOutputContractError(
                f"slowtask_event {numeric_field} must be a positive integer"
            )


def _validate_output_mode(output_mode: str) -> str:
    if output_mode not in SLOW_LLM_OUTPUT_MODES:
        raise SlowLLMStructuredOutputContractError(
            f"Slow LLM output_mode must be one of {sorted(SLOW_LLM_OUTPUT_MODES)}"
        )
    return output_mode


def _require_non_empty_string(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise SlowLLMStructuredOutputContractError(f"{field} must be a non-empty string")
    return value


def _require_safe_ref(value: str, field: str) -> str:
    value = _require_non_empty_string(value, field)
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        raise SlowLLMStructuredOutputContractError(f"{field} must not contain credential-like content")
    return value


def _optional_safe_ref(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _require_safe_ref(value, field)


def _validate_failure_reasons(failure_reasons: Sequence[str]) -> list[str]:
    invalid_failure_reasons = (
        not failure_reasons
        or isinstance(failure_reasons, (str, bytes))
        or not all(isinstance(reason, str) and reason for reason in failure_reasons)
    )
    if invalid_failure_reasons:
        raise SlowLLMStructuredOutputContractError(
            "failure_reasons must be a non-empty sequence of strings"
        )
    normalized = list(failure_reasons)
    if any(CREDENTIAL_LIKE_REF_PATTERN.search(reason) for reason in normalized):
        raise SlowLLMStructuredOutputContractError(
            "failure_reasons must not contain credential-like content"
        )
    return normalized
