from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from voice_agent.access.audio_ingress import receive_audio_span_end, receive_audio_span_start
from voice_agent.access.text_ingress import receive_text_input
from voice_agent.duplex.mock_duplex import MockDuplexRuleGate
from voice_agent.interaction.controller import InteractionController
from voice_agent.runtime.session import start_mvp0_session


def _slice6_symbol(module_name: str, symbol_name: str) -> Any:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Slice 6 module is not implemented: {module_name}")  # noqa: B011
        raise AssertionError from exc
    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        pytest.fail(f"Slice 6 symbol is not implemented: {module_name}.{symbol_name}")  # noqa: B011
        raise AssertionError from exc


def _startup_session(session_suffix: str = "understanding"):
    return start_mvp0_session(
        session_id=f"sess_mvp0_slice6_{session_suffix}",
        conversation_id=f"conv_mvp0_slice6_{session_suffix}",
        runtime_config_ref="config://synthetic/mvp0/default",
        created_monotonic_ms=600,
        created_wall_clock_ms=1700000000600,
    )


def _commit_text_turn():
    startup = _startup_session("text_understanding")
    text_event = receive_text_input(
        startup.journal,
        event_id="evt_mvp0_slice6_text_received",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=610,
        created_wall_clock_ms=1700000000610,
        input_span_id="input_slice6_text_001",
        text_span_id="text_slice6_001",
        text_ref="text://synthetic/mvp0/slice6-redacted-text",
    )
    result = InteractionController(startup.journal).commit_text_ingress(
        text_event,
        turn_id="turn_slice6_text_001",
        utterance_id="utt_slice6_text_001",
        created_monotonic_ms=620,
        created_wall_clock_ms=1700000000620,
    )
    return startup, result.turn_opened, result.turn_committed


def _commit_audio_turn():
    startup = _startup_session("audio_understanding")
    audio_started = receive_audio_span_start(
        startup.journal,
        event_id="evt_mvp0_slice6_audio_started",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=610,
        created_wall_clock_ms=1700000000610,
        audio_span_id="audio_slice6_001",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/mvp0/pcm16-16khz-mono",
    )
    duplex = MockDuplexRuleGate(startup.journal)
    speech_start = duplex.record_speech_start(
        audio_started,
        event_id="evt_mvp0_slice6_speech_start",
        created_monotonic_ms=612,
        created_wall_clock_ms=1700000000612,
        audio_sample_offset=160,
        vad_confidence=0.97,
    )
    controller = InteractionController(startup.journal)
    controller.open_audio_turn(
        speech_start,
        turn_id="turn_slice6_audio_001",
        created_monotonic_ms=613,
        created_wall_clock_ms=1700000000613,
    )
    audio_ended = receive_audio_span_end(
        startup.journal,
        event_id="evt_mvp0_slice6_audio_ended",
        caused_by_event_id=str(speech_start["event_id"]),
        created_monotonic_ms=640,
        created_wall_clock_ms=1700000000640,
        audio_span_id="audio_slice6_001",
        audio_sample_offset=16000,
        duration_ms=1000,
        end_reason="mock_speech_end",
    )
    speech_end = duplex.record_speech_end(
        audio_ended,
        event_id="evt_mvp0_slice6_speech_end",
        created_monotonic_ms=642,
        created_wall_clock_ms=1700000000642,
        audio_sample_offset=16000,
        vad_confidence=0.95,
        silence_duration_ms=240,
    )
    result = controller.commit_audio_ingress(
        speech_end,
        turn_id="turn_slice6_audio_001",
        utterance_id="utt_slice6_audio_001",
        created_monotonic_ms=643,
        created_wall_clock_ms=1700000000643,
    )
    return startup, result.turn_committed


def test_mock_understanding_rejects_events_before_turn_commit() -> None:
    emit_mock_asr_frame = _slice6_symbol("voice_agent.understanding.mock_asr", "emit_mock_asr_frame")
    emit_mock_thinker_frame = _slice6_symbol(
        "voice_agent.understanding.mock_thinker",
        "emit_mock_thinker_frame",
    )
    startup, turn_opened, _turn_committed = _commit_text_turn()

    with pytest.raises(ValueError, match="TURN_INGRESS_COMMITTED"):
        emit_mock_asr_frame(
            startup.journal,
            turn_opened,
            event_id="evt_mvp0_slice6_mock_asr_too_early",
            created_monotonic_ms=630,
            created_wall_clock_ms=1700000000630,
            asr_frame_ref="asr-frame://synthetic/mvp0/slice6-too-early",
        )

    with pytest.raises(ValueError, match="TURN_INGRESS_COMMITTED"):
        emit_mock_thinker_frame(
            startup.journal,
            turn_opened,
            event_id="evt_mvp0_slice6_mock_thinker_too_early",
            created_monotonic_ms=631,
            created_wall_clock_ms=1700000000631,
            semantic_frame_ref="semantic-frame://synthetic/mvp0/slice6-too-early",
        )


@pytest.mark.parametrize(
    ("commit_factory", "span_field", "span_value"),
    [
        (_commit_text_turn, "text_span_id", "text_slice6_001"),
        (_commit_audio_turn, "audio_span_id", "audio_slice6_001"),
    ],
)
def test_mock_understanding_frames_emit_after_text_and_audio_commits(
    commit_factory: Any,
    span_field: str,
    span_value: str,
) -> None:
    emit_mock_asr_frame = _slice6_symbol("voice_agent.understanding.mock_asr", "emit_mock_asr_frame")
    emit_mock_thinker_frame = _slice6_symbol(
        "voice_agent.understanding.mock_thinker",
        "emit_mock_thinker_frame",
    )
    result = commit_factory()
    startup = result[0]
    turn_committed = result[-1]

    asr_event = emit_mock_asr_frame(
        startup.journal,
        turn_committed,
        event_id=f"evt_{turn_committed['turn_id']}_mock_asr",
        created_monotonic_ms=650,
        created_wall_clock_ms=1700000000650,
        asr_frame_ref=f"asr-frame://synthetic/mvp0/{turn_committed['utterance_id']}",
    )
    thinker_event = emit_mock_thinker_frame(
        startup.journal,
        turn_committed,
        event_id=f"evt_{turn_committed['turn_id']}_mock_thinker",
        created_monotonic_ms=651,
        created_wall_clock_ms=1700000000651,
        semantic_frame_ref=f"semantic-frame://synthetic/mvp0/{turn_committed['utterance_id']}",
    )

    assert asr_event["event_name"] == "MOCK_ASR_FRAME_EMITTED"
    assert thinker_event["event_name"] == "MOCK_THINKER_FRAME_EMITTED"
    assert asr_event["caused_by_event_id"] == turn_committed["event_id"]
    assert thinker_event["caused_by_event_id"] == turn_committed["event_id"]
    assert asr_event["output_mode"] == "mock"
    assert thinker_event["output_mode"] == "mock"
    assert asr_event["turn_id"] == turn_committed["turn_id"]
    assert thinker_event["turn_id"] == turn_committed["turn_id"]
    assert asr_event["utterance_id"] == turn_committed["utterance_id"]
    assert thinker_event["utterance_id"] == turn_committed["utterance_id"]
    assert asr_event["input_modality"] == turn_committed["input_modality"]
    assert thinker_event["input_modality"] == turn_committed["input_modality"]
    assert asr_event[span_field] == span_value
    assert asr_event["asr_frame_ref"].startswith("asr-frame://synthetic/mvp0/")
    assert thinker_event["semantic_frame_ref"].startswith("semantic-frame://synthetic/mvp0/")

    for event in (asr_event, thinker_event):
        assert "raw_transcript" not in event
        assert "prompt" not in event
        assert "provider_response" not in event
        assert "api_key" not in event
        assert "token" not in event
