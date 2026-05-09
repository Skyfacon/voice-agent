from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from voice_agent.events.envelope import validate_event_envelope
from voice_agent.runtime.session import start_mvp0_session


def _slice4_symbol(module_name: str, symbol_name: str) -> Any:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Slice 4 module is not implemented: {module_name}")  # noqa: B011
        raise AssertionError from exc
    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        pytest.fail(f"Slice 4 symbol is not implemented: {module_name}.{symbol_name}")  # noqa: B011
        raise AssertionError from exc


def _startup_session():
    return start_mvp0_session(
        session_id="sess_mvp0_slice4_text",
        conversation_id="conv_mvp0_slice4_text",
        runtime_config_ref="config://synthetic/mvp0/default",
        created_monotonic_ms=400,
        created_wall_clock_ms=1700000000400,
    )


def test_access_layer_records_text_input_without_turn_or_router_events() -> None:
    receive_text_input = _slice4_symbol("voice_agent.access.text_ingress", "receive_text_input")
    startup = _startup_session()
    caused_by_event_id = str(startup.journal.events()[-1]["event_id"])

    text_event = receive_text_input(
        startup.journal,
        event_id="evt_mvp0_slice4_text_received",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=410,
        created_wall_clock_ms=1700000000410,
        input_span_id="input_slice4_text_001",
        text_span_id="text_slice4_001",
        redacted_text="[synthetic text: hello assistant]",
        language_hint="en",
    )

    events = startup.journal.events()
    assert text_event == validate_event_envelope(text_event)
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "TEXT_INPUT_RECEIVED",
    ]
    assert events[-1]["source_module"] == "access_layer"
    assert events[-1]["input_modality"] == "text"
    assert events[-1]["audio_span_id"] is None
    assert events[-1]["directedness"] == "ASSUMED_DIRECTED"
    assert events[-1]["semantic_close"] == "ASSUMED_CLOSED"
    assert "ROUTER_DECISION_EMITTED" not in {event["event_name"] for event in events}


def test_interaction_controller_commits_text_ingress_after_text_input() -> None:
    receive_text_input = _slice4_symbol("voice_agent.access.text_ingress", "receive_text_input")
    InteractionController = _slice4_symbol("voice_agent.interaction.controller", "InteractionController")
    startup = _startup_session()
    text_event = receive_text_input(
        startup.journal,
        event_id="evt_mvp0_slice4_text_received",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=410,
        created_wall_clock_ms=1700000000410,
        input_span_id="input_slice4_text_001",
        text_span_id="text_slice4_001",
        text_ref="text://synthetic/mvp0/slice4-redacted-text",
    )

    result = InteractionController(startup.journal).commit_text_ingress(
        text_event,
        turn_id="turn_slice4_text_001",
        utterance_id="utt_slice4_text_001",
        created_monotonic_ms=420,
        created_wall_clock_ms=1700000000420,
    )

    events = startup.journal.events()
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "TEXT_INPUT_RECEIVED",
        "TURN_OPENED",
        "TURN_INGRESS_ACCEPTED",
        "TURN_INGRESS_COMMITTED",
    ]
    assert [event["event_seq"] for event in events] == [1, 2, 3, 4, 5, 6]
    assert result.turn_opened["caused_by_event_id"] == text_event["event_id"]
    assert result.turn_accepted["caused_by_event_id"] == result.turn_opened["event_id"]
    assert result.turn_committed["caused_by_event_id"] == result.turn_accepted["event_id"]
    assert result.turn_opened["source_module"] == "interaction_controller"
    assert result.turn_accepted["source_module"] == "interaction_controller"
    assert result.turn_committed["source_module"] == "interaction_controller"
    assert result.turn_opened["turn_phase"] == "COLLECTING_INPUT"
    assert result.turn_accepted["ingress_outcome"] == "ACCEPTED"
    assert result.turn_committed["ingress_outcome"] == "COMMITTED"
    assert result.turn_committed["input_modality"] == "text"
    assert result.turn_committed["directedness"] == "ASSUMED_DIRECTED"
    assert result.turn_committed["semantic_close"] == "ASSUMED_CLOSED"
    assert all(event.get("audio_span_id") is None for event in events[2:])
    assert "ROUTER_DECISION_EMITTED" not in {event["event_name"] for event in events}


def test_controller_rejects_non_text_ingress_event() -> None:
    InteractionController = _slice4_symbol("voice_agent.interaction.controller", "InteractionController")
    startup = _startup_session()

    with pytest.raises(ValueError, match="TEXT_INPUT_RECEIVED"):
        InteractionController(startup.journal).commit_text_ingress(
            startup.journal.events()[0],
            turn_id="turn_slice4_text_001",
            utterance_id="utt_slice4_text_001",
            created_monotonic_ms=420,
            created_wall_clock_ms=1700000000420,
        )
