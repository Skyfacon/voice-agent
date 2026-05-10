from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from voice_agent.access.text_ingress import receive_text_input
from voice_agent.interaction.controller import InteractionController
from voice_agent.router.router import MVP0Router
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.understanding.mock_asr import emit_mock_asr_frame
from voice_agent.understanding.mock_thinker import emit_mock_thinker_frame


def _slice7_symbol(module_name: str, symbol_name: str) -> Any:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Slice 7 module is not implemented: {module_name}")  # noqa: B011
        raise AssertionError from exc
    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        pytest.fail(f"Slice 7 symbol is not implemented: {module_name}.{symbol_name}")  # noqa: B011
        raise AssertionError from exc


def _fast_only_router_decision():
    startup = start_mvp0_session(
        session_id="sess_mvp0_slice7_playback",
        conversation_id="conv_mvp0_slice7_playback",
        runtime_config_ref="config://synthetic/mvp0/default",
        created_monotonic_ms=700,
        created_wall_clock_ms=1700000000700,
    )
    text_event = receive_text_input(
        startup.journal,
        event_id="evt_mvp0_slice7_text_received",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=710,
        created_wall_clock_ms=1700000000710,
        input_span_id="input_slice7_text_001",
        text_span_id="text_slice7_001",
        text_ref="text://synthetic/mvp0/slice7-redacted-text",
    )
    turn_committed = InteractionController(startup.journal).commit_text_ingress(
        text_event,
        turn_id="turn_slice7_text_001",
        utterance_id="utt_slice7_text_001",
        created_monotonic_ms=720,
        created_wall_clock_ms=1700000000720,
    ).turn_committed
    asr_event = emit_mock_asr_frame(
        startup.journal,
        turn_committed,
        event_id="evt_mvp0_slice7_mock_asr",
        created_monotonic_ms=730,
        created_wall_clock_ms=1700000000730,
        asr_frame_ref="asr-frame://synthetic/mvp0/slice7-text",
    )
    thinker_event = emit_mock_thinker_frame(
        startup.journal,
        turn_committed,
        event_id="evt_mvp0_slice7_mock_thinker",
        created_monotonic_ms=731,
        created_wall_clock_ms=1700000000731,
        semantic_frame_ref="semantic-frame://synthetic/mvp0/slice7-text",
    )
    router_event = MVP0Router(startup.journal).emit_decision(
        turn_committed_event=turn_committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        event_id="evt_mvp0_slice7_router_decision",
        created_monotonic_ms=740,
        created_wall_clock_ms=1700000000740,
        router_decision="FAST_ONLY",
    )
    return startup, router_event


def test_mock_talker_emits_mock_playback_lifecycle_after_fast_only_router_decision() -> None:
    MockTalker = _slice7_symbol("voice_agent.talker.mock_talker", "MockTalker")
    startup, router_event = _fast_only_router_decision()

    talker = MockTalker(startup.journal)
    started = talker.start_playback_after_fast_only(
        router_decision_event=router_event,
        event_id="evt_mvp0_slice7_playback_started",
        created_monotonic_ms=750,
        created_wall_clock_ms=1700000000750,
        playback_span_id="playback_slice7_001",
        audio_ref="audio://synthetic/mvp0/mock-playback-slice7-001",
    )
    progress = talker.record_progress(
        playback_event=started,
        event_id="evt_mvp0_slice7_playback_progress_250",
        created_monotonic_ms=760,
        created_wall_clock_ms=1700000000760,
        playback_offset_ms=250,
    )
    committed = talker.record_committed(
        playback_event=progress,
        event_id="evt_mvp0_slice7_playback_committed_240",
        created_monotonic_ms=761,
        created_wall_clock_ms=1700000000761,
        playback_offset_ms=240,
    )
    finished = talker.record_finished(
        playback_event=committed,
        event_id="evt_mvp0_slice7_playback_finished",
        created_monotonic_ms=780,
        created_wall_clock_ms=1700000000780,
        final_playback_offset_ms=1000,
    )

    assert [event["event_name"] for event in (started, progress, committed, finished)] == [
        "PLAYBACK_SPAN_STARTED",
        "PLAYBACK_PROGRESS",
        "PLAYBACK_COMMITTED",
        "PLAYBACK_FINISHED",
    ]
    assert started["caused_by_event_id"] == router_event["event_id"]
    assert progress["caused_by_event_id"] == started["event_id"]
    assert committed["caused_by_event_id"] == progress["event_id"]
    assert finished["caused_by_event_id"] == committed["event_id"]
    assert progress["playback_offset_ms"] == 250
    assert committed["playback_offset_ms"] == 240
    assert committed["commit_basis"] == "mock_delivery_marker"
    assert finished["final_playback_offset_ms"] == 1000

    for event in (started, progress, committed, finished):
        assert event["output_mode"] == "mock"
        assert event["mock_profile_ref"] == "mock-profile://synthetic/mvp0/talker-playback-v1"
        assert event["playback_span_id"] == "playback_slice7_001"
        assert "raw_audio" not in event
        assert "raw_audio_ref" not in event
        assert "provider_response" not in event


def test_mock_talker_requires_unique_playback_span_ids_and_synthetic_refs() -> None:
    MockTalker = _slice7_symbol("voice_agent.talker.mock_talker", "MockTalker")
    startup, router_event = _fast_only_router_decision()
    talker = MockTalker(startup.journal)

    talker.start_playback_after_fast_only(
        router_decision_event=router_event,
        event_id="evt_mvp0_slice7_playback_started",
        created_monotonic_ms=750,
        created_wall_clock_ms=1700000000750,
        playback_span_id="playback_slice7_001",
        tts_stream_ref="tts-stream://synthetic/mvp0/mock-playback-slice7-001",
    )

    with pytest.raises(ValueError, match="unique playback_span_id"):
        talker.start_playback_after_fast_only(
            router_decision_event=router_event,
            event_id="evt_mvp0_slice7_playback_started_duplicate",
            created_monotonic_ms=751,
            created_wall_clock_ms=1700000000751,
            playback_span_id="playback_slice7_001",
            tts_stream_ref="tts-stream://synthetic/mvp0/mock-playback-slice7-duplicate",
        )

    with pytest.raises(ValueError, match="unique playback_span_id"):
        MockTalker(startup.journal).start_playback_after_fast_only(
            router_decision_event=router_event,
            event_id="evt_mvp0_slice7_playback_started_duplicate_new_talker",
            created_monotonic_ms=752,
            created_wall_clock_ms=1700000000752,
            playback_span_id="playback_slice7_001",
            tts_stream_ref="tts-stream://synthetic/mvp0/mock-playback-slice7-duplicate-new-talker",
        )

    with pytest.raises(ValueError, match="synthetic playback ref"):
        talker.start_playback_after_fast_only(
            router_decision_event=router_event,
            event_id="evt_mvp0_slice7_playback_started_raw_ref",
            created_monotonic_ms=753,
            created_wall_clock_ms=1700000000753,
            playback_span_id="playback_slice7_002",
            audio_ref="audio/raw/session.wav",
        )


def test_mock_talker_rejects_non_fast_only_router_decision() -> None:
    MockTalker = _slice7_symbol("voice_agent.talker.mock_talker", "MockTalker")
    startup, router_event = _fast_only_router_decision()
    ignore_event = dict(router_event, router_decision="IGNORE")

    with pytest.raises(ValueError, match="FAST_ONLY"):
        MockTalker(startup.journal).start_playback_after_fast_only(
            router_decision_event=ignore_event,
            event_id="evt_mvp0_slice7_playback_started_ignore",
            created_monotonic_ms=750,
            created_wall_clock_ms=1700000000750,
            playback_span_id="playback_slice7_ignore",
            audio_ref="audio://synthetic/mvp0/mock-playback-ignore",
        )
