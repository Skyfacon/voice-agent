from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from voice_agent.events.registry import EventRegistryError, get_event_definition


class EventValidationError(ValueError):
    pass


COMMON_ENVELOPE_FIELDS = (
    "event_name",
    "event_id",
    "event_seq",
    "event_schema_version",
    "session_id",
    "conversation_id",
    "source_module",
    "created_monotonic_ms",
    "created_wall_clock_ms",
    "trace_redaction_level",
)


def validate_event_envelope(event: Mapping[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(dict(event))

    for field in COMMON_ENVELOPE_FIELDS:
        _require_present(normalized, field)

    try:
        definition = get_event_definition(str(normalized["event_name"]))
    except EventRegistryError as exc:
        raise EventValidationError(str(exc)) from exc

    _validate_event_seq(normalized["event_seq"])

    if definition.is_root:
        if normalized.get("caused_by_event_id") not in ("", None):
            raise EventValidationError("root event must not include caused_by_event_id")
        normalized.pop("caused_by_event_id", None)
    elif definition.caused_by_event_required:
        _require_present(normalized, "caused_by_event_id")
    elif normalized.get("caused_by_event_id") in ("", None):
        normalized.pop("caused_by_event_id", None)

    for field in definition.required_fields:
        _require_present(normalized, field)

    for literal_field, expected in definition.literal_fields.items():
        _require_present(normalized, literal_field)
        actual = normalized[literal_field]
        if actual != expected:
            raise EventValidationError(f"{literal_field}={expected} required, got {actual!r}")

    for alternatives in definition.one_of_fields:
        if not any(_has_value(normalized, field) for field in alternatives):
            raise EventValidationError(f"One of {' or '.join(alternatives)} is required")

    return normalized


def _require_present(event: Mapping[str, Any], field: str) -> None:
    if not _has_value(event, field):
        raise EventValidationError(f"Missing required field: {field}")


def _has_value(event: Mapping[str, Any], field: str) -> bool:
    return field in event and event[field] is not None and event[field] != ""


def _validate_event_seq(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EventValidationError("event_seq must be a positive integer")
