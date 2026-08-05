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

    for enum_field, allowed_values in definition.enum_fields.items():
        if enum_field not in normalized:
            continue
        actual = normalized[enum_field]
        if not any(actual == allowed for allowed in allowed_values):
            raise EventValidationError(f"{enum_field} has an unsupported value")

    for conditional in definition.conditional_required_fields:
        if (
            normalized.get(conditional.when_field) == conditional.when_value
            and all(
                normalized.get(field) == expected
                for field, expected in conditional.and_conditions
            )
        ):
            for field in conditional.required_fields:
                _require_present(normalized, field)

    for all_or_none in definition.all_or_none_fields:
        present_fields = [
            field for field in all_or_none.fields if _has_value(normalized, field)
        ]
        if present_fields and len(present_fields) != len(all_or_none.fields):
            for field in all_or_none.fields:
                _require_present(normalized, field)

    if (
        normalized["event_name"] == "PLAYBACK_SPAN_STARTED"
        and _has_value(normalized, "release_token_ref")
    ):
        for field in (
            "provider_session_generation",
            "qwen_response_id",
            "qwen_output_item_id",
            "qwen_output_index",
            "qwen_content_index",
            "playback_epoch",
        ):
            _require_present(normalized, field)

    for alternatives in definition.one_of_fields:
        if not any(_has_value(normalized, field) for field in alternatives):
            raise EventValidationError(f"One of {' or '.join(alternatives)} is required")

    for alternative_field_set in definition.any_of_field_sets:
        if all(_has_value(normalized, field) for field in alternative_field_set):
            break
    else:
        if definition.any_of_field_sets:
            alternatives = [
                " and ".join(alternative_field_set) for alternative_field_set in definition.any_of_field_sets
            ]
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
