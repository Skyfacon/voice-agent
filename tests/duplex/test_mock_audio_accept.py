from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from voice_agent.state.interaction_state import InteractionState
from voice_agent.runtime.session import start_mvp0_session


def _slice5_symbol(module_name: str, symbol_name: str) -> Any:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Slice 5 module is not implemented: {module_name}")  # noqa: B011
        raise AssertionError from exc
    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        pytest.fail(f"Slice 5 symbol is not implemented: {module_name}.{symbol_name}")  # noqa: B011
        raise AssertionError from exc


def _startup_session():
    return start_mvp0_session(
        session_id="sess_mvp0_slice5_audio",
        conversation_id="conv_mvp0_slice5_audio",
        runtime_config_ref="config://synthetic/mvp0/default",
        created_monotonic_ms=500,
        created_wall_clock_ms=1700000000500,
    )


def _full_audio_path() -> tuple[Any, dict[str, Any]]:
    receive_audio_span_start = _slice5_symbol("voice_agent.access.audio_ingress", "receive_audio_span_start")
    receive_audio_span_end = _slice5_symbol("voice_agent.access.audio_ingress", "receive_audio_span_end")
    MockDuplexRuleGate = _slice5_symbol("voice_agent.duplex.mock_duplex", "MockDuplexRuleGate")
    InteractionController = _slice5_symbol("voice_agent.interaction.controller", "InteractionController")

    startup = _startup_session()
    audio_started = receive_audio_span_start(
        startup.journal,
        event_id="evt_mvp0_slice5_audio_started",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=510,
        created_wall_clock_ms=1700000000510,
        audio_span_id="audio_slice5_001",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/mvp0/pcm16-16khz-mono",
    )
    duplex = MockDuplexRuleGate(startup.journal)
    speech_start = duplex.record_speech_start(
        audio_started,
        event_id="evt_mvp0_slice5_speech_start",
        created_monotonic_ms=512,
        created_wall_clock_ms=1700000000512,
        audio_sample_offset=160,
        vad_confidence=0.97,
    )
    controller = InteractionController(startup.journal)
    turn_opened = controller.open_audio_turn(
        speech_start,
        turn_id="turn_slice5_audio_001",
        created_monotonic_ms=513,
        created_wall_clock_ms=1700000000513,
    )
    audio_ended = receive_audio_span_end(
        startup.journal,
        event_id="evt_mvp0_slice5_audio_ended",
        caused_by_event_id=str(speech_start["event_id"]),
        created_monotonic_ms=540,
        created_wall_clock_ms=1700000000540,
        audio_span_id="audio_slice5_001",
        audio_sample_offset=16000,
        duration_ms=1000,
        end_reason="mock_speech_end",
    )
    speech_end = duplex.record_speech_end(
        audio_ended,
        event_id="evt_mvp0_slice5_speech_end",
        created_monotonic_ms=542,
        created_wall_clock_ms=1700000000542,
        audio_sample_offset=16000,
        vad_confidence=0.95,
        silence_duration_ms=240,
    )
    commit_result = controller.commit_audio_ingress(
        speech_end,
        turn_id="turn_slice5_audio_001",
        utterance_id="utt_slice5_audio_001",
        created_monotonic_ms=543,
        created_wall_clock_ms=1700000000543,
    )

    return startup, {
        "audio_started": audio_started,
        "speech_start": speech_start,
        "turn_opened": turn_opened,
        "audio_ended": audio_ended,
        "speech_end": speech_end,
        "commit_result": commit_result,
    }


def test_audio_span_start_and_mock_speech_start_open_collecting_turn() -> None:
    receive_audio_span_start = _slice5_symbol("voice_agent.access.audio_ingress", "receive_audio_span_start")
    MockDuplexRuleGate = _slice5_symbol("voice_agent.duplex.mock_duplex", "MockDuplexRuleGate")
    InteractionController = _slice5_symbol("voice_agent.interaction.controller", "InteractionController")
    startup = _startup_session()

    audio_started = receive_audio_span_start(
        startup.journal,
        event_id="evt_mvp0_slice5_audio_started",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=510,
        created_wall_clock_ms=1700000000510,
        audio_span_id="audio_slice5_001",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/mvp0/pcm16-16khz-mono",
    )
    speech_start = MockDuplexRuleGate(startup.journal).record_speech_start(
        audio_started,
        event_id="evt_mvp0_slice5_speech_start",
        created_monotonic_ms=512,
        created_wall_clock_ms=1700000000512,
        audio_sample_offset=160,
        vad_confidence=0.97,
    )
    turn_opened = InteractionController(startup.journal).open_audio_turn(
        speech_start,
        turn_id="turn_slice5_audio_001",
        created_monotonic_ms=513,
        created_wall_clock_ms=1700000000513,
    )

    events = startup.journal.events()
    state = InteractionState()
    for event in events:
        state.reduce_event(event)

    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "AUDIO_SPAN_STARTED",
        "SPEECH_START_DETECTED",
        "TURN_OPENED",
    ]
    assert state.turn_phase == "COLLECTING_INPUT"
    assert state.current_audio_span_id == "audio_slice5_001"
    assert audio_started["input_modality"] == "audio"
    assert audio_started["audio_sample_offset"] == 0
    assert audio_started["audio_format_ref"] == "audio-format://synthetic/mvp0/pcm16-16khz-mono"
    assert speech_start["source_module"] == "duplex_mock"
    assert speech_start["detection_basis"] == "mock_rule:speech_start_on_audio_span_started"
    assert turn_opened["caused_by_event_id"] == speech_start["event_id"]
    assert turn_opened["input_modality"] == "audio"
    assert turn_opened["audio_span_id"] == "audio_slice5_001"
    for event in events:
        assert "raw_audio" not in event
        assert "audio_bytes" not in event
        assert "audio_payload" not in event


def test_mock_speech_end_accepts_and_commits_audio_turn_without_router_or_model_frames() -> None:
    startup, emitted = _full_audio_path()
    events = startup.journal.events()
    commit_result = emitted["commit_result"]

    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "AUDIO_SPAN_STARTED",
        "SPEECH_START_DETECTED",
        "TURN_OPENED",
        "AUDIO_SPAN_ENDED",
        "SPEECH_END_DETECTED",
        "TURN_INGRESS_ACCEPTED",
        "TURN_INGRESS_COMMITTED",
    ]
    assert [event["event_seq"] for event in events] == list(range(1, 10))
    assert emitted["audio_ended"]["audio_sample_offset"] == 16000
    assert emitted["audio_ended"]["duration_ms"] == 1000
    assert emitted["speech_end"]["detection_basis"] == "mock_rule:speech_end_on_audio_span_ended"
    assert commit_result.turn_accepted["caused_by_event_id"] == emitted["speech_end"]["event_id"]
    assert commit_result.turn_committed["caused_by_event_id"] == commit_result.turn_accepted["event_id"]
    assert commit_result.turn_accepted["acceptance_basis"] == "mock_rule:assumed_directed_and_closed"
    assert commit_result.turn_committed["input_modality"] == "audio"
    assert commit_result.turn_committed["audio_span_id"] == "audio_slice5_001"
    assert commit_result.turn_committed["directedness"] == "ASSUMED_DIRECTED"
    assert commit_result.turn_committed["semantic_close"] == "ASSUMED_CLOSED"
    assert "ROUTER_DECISION_EMITTED" not in {event["event_name"] for event in events}
    assert "MOCK_ASR_FRAME_EMITTED" not in {event["event_name"] for event in events}
    assert "MOCK_THINKER_FRAME_EMITTED" not in {event["event_name"] for event in events}


def test_controller_rejects_non_audio_duplex_events_for_audio_path() -> None:
    InteractionController = _slice5_symbol("voice_agent.interaction.controller", "InteractionController")
    startup = _startup_session()

    with pytest.raises(ValueError, match="SPEECH_START_DETECTED"):
        InteractionController(startup.journal).open_audio_turn(
            startup.journal.events()[0],
            turn_id="turn_slice5_audio_001",
            created_monotonic_ms=513,
            created_wall_clock_ms=1700000000513,
        )


def test_controller_rejects_audio_commit_without_prior_matching_turn_opened() -> None:
    InteractionController = _slice5_symbol("voice_agent.interaction.controller", "InteractionController")
    startup, emitted = _full_audio_path()

    isolated_startup = _startup_session()
    with pytest.raises(ValueError, match="TURN_OPENED"):
        InteractionController(isolated_startup.journal).commit_audio_ingress(
            emitted["speech_end"],
            turn_id="turn_slice5_audio_001",
            utterance_id="utt_slice5_audio_001",
            created_monotonic_ms=543,
            created_wall_clock_ms=1700000000543,
        )
