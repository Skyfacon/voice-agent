from __future__ import annotations

import pytest

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.events.envelope import EventValidationError, validate_event_envelope
from voice_agent.events.registry import MVP0_EVENT_NAMES, get_event_definition


def session_started_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": "SESSION_STARTED",
        "event_id": "evt_mvp0_session_started_001",
        "event_seq": 1,
        "event_schema_version": "1.0",
        "session_id": "sess_mvp0_synthetic_001",
        "conversation_id": "conv_mvp0_synthetic_001",
        "source_module": "session_runtime",
        "created_monotonic_ms": 0,
        "created_wall_clock_ms": 1700000000000,
        "trace_redaction_level": "metadata_only",
        "runtime_config_ref": "config://synthetic/mvp0/default",
        "capability_snapshot_ref": "capability://synthetic/mvp0/not-recorded-yet",
    }
    event.update(overrides)
    return event


def text_input_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": "TEXT_INPUT_RECEIVED",
        "event_id": "evt_mvp0_text_input_001",
        "event_seq": 2,
        "event_schema_version": "1.0",
        "session_id": "sess_mvp0_synthetic_001",
        "conversation_id": "conv_mvp0_synthetic_001",
        "source_module": "access_layer",
        "created_monotonic_ms": 12,
        "created_wall_clock_ms": 1700000000012,
        "caused_by_event_id": "evt_mvp0_session_started_001",
        "trace_redaction_level": "redacted_fixture",
        "input_span_id": "input_synthetic_001",
        "text_span_id": "text_synthetic_001",
        "input_modality": "text",
        "redacted_text": "[synthetic user text]",
        "directedness": "ASSUMED_DIRECTED",
        "semantic_close": "ASSUMED_CLOSED",
    }
    event.update(overrides)
    return event


def test_session_started_root_event_can_omit_cause() -> None:
    validated = validate_event_envelope(session_started_event())

    assert validated["event_name"] == "SESSION_STARTED"
    assert "caused_by_event_id" not in validated


def test_root_event_rejects_non_empty_cause() -> None:
    with pytest.raises(EventValidationError, match="root event"):
        validate_event_envelope(session_started_event(caused_by_event_id="evt_other"))


def test_non_root_event_requires_caused_by_event_id() -> None:
    event = text_input_event()
    event.pop("caused_by_event_id")

    with pytest.raises(EventValidationError, match="caused_by_event_id"):
        validate_event_envelope(event)


@pytest.mark.parametrize(
    "missing_field",
    [
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
    ],
)
def test_common_envelope_fields_are_required(missing_field: str) -> None:
    event = session_started_event()
    event.pop(missing_field)

    with pytest.raises(EventValidationError, match=missing_field):
        validate_event_envelope(event)


def test_unknown_mvp_event_name_is_rejected() -> None:
    event = session_started_event(event_name="SESSION_BOOTED")

    with pytest.raises(EventValidationError, match="Unknown event_name"):
        validate_event_envelope(event)


def test_registry_exposes_only_canonical_mvp0_event_names_for_slice_1() -> None:
    assert "SESSION_STARTED" in MVP0_EVENT_NAMES
    assert "TURN_INGRESS_COMMITTED" in MVP0_EVENT_NAMES
    assert "TRACE_WRITE_BLOCKED_SECRET_DETECTED" in MVP0_EVENT_NAMES
    assert "SESSION_BOOTED" not in MVP0_EVENT_NAMES


def test_event_specific_required_fields_are_enforced() -> None:
    event = text_input_event()
    event.pop("text_span_id")

    with pytest.raises(EventValidationError, match="text_span_id"):
        validate_event_envelope(event)


def test_event_specific_or_fields_are_enforced() -> None:
    event = text_input_event()
    event.pop("redacted_text")
    event["text_ref"] = "text://synthetic/mvp0/001"

    assert validate_event_envelope(event)["text_ref"] == "text://synthetic/mvp0/001"

    event.pop("text_ref")
    with pytest.raises(EventValidationError, match="redacted_text or text_ref"):
        validate_event_envelope(event)


def test_event_specific_literal_fields_are_enforced() -> None:
    event = text_input_event(input_modality="audio")

    with pytest.raises(EventValidationError, match="input_modality=text"):
        validate_event_envelope(event)


def test_mvp0_session_start_fixture_validates_through_event_validator() -> None:
    fixture = load_json_fixture(MVP0_REPLAY_FIXTURE_DIR / "001-event-envelope-session-start.fixture.json")

    validated_events = [validate_event_envelope(event) for event in fixture["events"]]

    assert [event["event_seq"] for event in validated_events] == [1, 2]
    assert get_event_definition(validated_events[0]["event_name"]).is_root is True
    assert validated_events[1]["caused_by_event_id"] == validated_events[0]["event_id"]
