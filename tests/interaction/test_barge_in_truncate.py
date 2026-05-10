from __future__ import annotations

from typing import Any

import pytest

from voice_agent.access.audio_ingress import receive_audio_span_start
from voice_agent.access.text_ingress import receive_text_input
from voice_agent.duplex.mock_duplex import MockDuplexRuleGate
from voice_agent.interaction.controller import InteractionController
from voice_agent.router.router import MVP0Router
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.talker.mock_talker import MockTalker
from voice_agent.understanding.mock_asr import emit_mock_asr_frame
from voice_agent.understanding.mock_thinker import emit_mock_thinker_frame


def _start_playback_with_progress() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    startup = start_mvp0_session(
        session_id="sess_mvp0_slice8_barge_in",
        conversation_id="conv_mvp0_slice8_barge_in",
        runtime_config_ref="config://synthetic/mvp0/default",
        created_monotonic_ms=800,
        created_wall_clock_ms=1700000000800,
    )
    text_event = receive_text_input(
        startup.journal,
        event_id="evt_mvp0_slice8_text_received",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=810,
        created_wall_clock_ms=1700000000810,
        input_span_id="input_slice8_text_001",
        text_span_id="text_slice8_001",
        text_ref="text://synthetic/mvp0/slice8-redacted-text",
    )
    turn_committed = InteractionController(startup.journal).commit_text_ingress(
        text_event,
        turn_id="turn_slice8_text_001",
        utterance_id="utt_slice8_text_001",
        created_monotonic_ms=820,
        created_wall_clock_ms=1700000000820,
    ).turn_committed
    asr_event = emit_mock_asr_frame(
        startup.journal,
        turn_committed,
        event_id="evt_mvp0_slice8_mock_asr",
        created_monotonic_ms=830,
        created_wall_clock_ms=1700000000830,
        asr_frame_ref="asr-frame://synthetic/mvp0/slice8-text",
    )
    thinker_event = emit_mock_thinker_frame(
        startup.journal,
        turn_committed,
        event_id="evt_mvp0_slice8_mock_thinker",
        created_monotonic_ms=831,
        created_wall_clock_ms=1700000000831,
        semantic_frame_ref="semantic-frame://synthetic/mvp0/slice8-text",
    )
    router_event = MVP0Router(startup.journal).emit_decision(
        turn_committed_event=turn_committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        event_id="evt_mvp0_slice8_router_decision",
        created_monotonic_ms=840,
        created_wall_clock_ms=1700000000840,
        router_decision="FAST_ONLY",
    )

    talker = MockTalker(startup.journal)
    playback_started = talker.start_playback_after_fast_only(
        router_decision_event=router_event,
        event_id="evt_mvp0_slice8_playback_started",
        created_monotonic_ms=850,
        created_wall_clock_ms=1700000000850,
        playback_span_id="playback_slice8_001",
        audio_ref="audio://synthetic/mvp0/mock-playback-slice8-001",
    )
    playback_progress = talker.record_progress(
        playback_event=playback_started,
        event_id="evt_mvp0_slice8_playback_progress_900",
        created_monotonic_ms=900,
        created_wall_clock_ms=1700000000900,
        playback_offset_ms=900,
    )
    playback_committed = talker.record_committed(
        playback_event=playback_progress,
        event_id="evt_mvp0_slice8_playback_committed_850",
        created_monotonic_ms=901,
        created_wall_clock_ms=1700000000901,
        playback_offset_ms=850,
    )
    return startup, playback_progress, playback_committed


def _speech_start_during_playback(startup: Any) -> dict[str, Any]:
    audio_started = receive_audio_span_start(
        startup.journal,
        event_id="evt_mvp0_slice8_audio_started",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=910,
        created_wall_clock_ms=1700000000910,
        audio_span_id="audio_slice8_barge_001",
        audio_sample_offset=14400,
        audio_format_ref="audio-format://synthetic/mvp0/pcm16-16khz-mono",
    )
    return MockDuplexRuleGate(startup.journal).record_speech_start(
        audio_started,
        event_id="evt_mvp0_slice8_speech_start",
        created_monotonic_ms=912,
        created_wall_clock_ms=1700000000912,
        audio_sample_offset=14560,
        vad_confidence=0.96,
    )


def test_mock_duplex_emits_barge_in_candidate_with_playback_reference_metadata() -> None:
    startup, playback_progress, _playback_committed = _start_playback_with_progress()
    speech_start = _speech_start_during_playback(startup)

    candidate = MockDuplexRuleGate(startup.journal).record_barge_in_candidate(
        speech_start,
        playback_event=playback_progress,
        event_id="evt_mvp0_slice8_barge_candidate",
        created_monotonic_ms=913,
        created_wall_clock_ms=1700000000913,
        playback_offset_ms=910,
        echo_likelihood="low",
        vad_confidence=0.96,
        barge_in_confidence=0.94,
        playback_reference_ref="playback-ref://synthetic/mvp0/slice8-reference",
    )

    assert candidate["event_name"] == "BARGE_IN_CANDIDATE"
    assert candidate["caused_by_event_id"] == speech_start["event_id"]
    assert candidate["audio_span_id"] == "audio_slice8_barge_001"
    assert candidate["playback_span_id"] == "playback_slice8_001"
    assert candidate["playback_offset_ms"] == 910
    assert candidate["echo_likelihood"] == "low"
    assert candidate["vad_confidence"] == 0.96
    assert candidate["barge_in_confidence"] == 0.94
    assert candidate["output_mode"] == "mock"
    assert candidate["mock_profile_ref"] == "mock-profile://synthetic/mvp0/duplex-barge-in-v1"
    assert "raw_audio" not in candidate
    assert "raw_audio_ref" not in candidate


def test_mock_duplex_rejects_barge_in_without_synthetic_playback_reference() -> None:
    startup, playback_progress, _playback_committed = _start_playback_with_progress()
    speech_start = _speech_start_during_playback(startup)

    with pytest.raises(ValueError, match="synthetic playback reference"):
        MockDuplexRuleGate(startup.journal).record_barge_in_candidate(
            speech_start,
            playback_event=playback_progress,
            event_id="evt_mvp0_slice8_barge_candidate_bad_ref",
            created_monotonic_ms=913,
            created_wall_clock_ms=1700000000913,
            playback_offset_ms=910,
            echo_likelihood="low",
            vad_confidence=0.96,
            barge_in_confidence=0.94,
            playback_reference_ref="audio/raw/reference.wav",
        )


def test_interaction_controller_emits_interrupt_and_truncate_request_from_barge_in_candidate() -> None:
    startup, playback_progress, _playback_committed = _start_playback_with_progress()
    speech_start = _speech_start_during_playback(startup)
    candidate = MockDuplexRuleGate(startup.journal).record_barge_in_candidate(
        speech_start,
        playback_event=playback_progress,
        event_id="evt_mvp0_slice8_barge_candidate",
        created_monotonic_ms=913,
        created_wall_clock_ms=1700000000913,
        playback_offset_ms=910,
        echo_likelihood="low",
        vad_confidence=0.96,
        barge_in_confidence=0.94,
        playback_reference_ref="playback-ref://synthetic/mvp0/slice8-reference",
    )

    result = InteractionController(startup.journal).request_truncate_for_barge_in(
        candidate,
        interrupt_event_id="evt_mvp0_slice8_interrupt_candidate",
        truncate_request_event_id="evt_mvp0_slice8_truncate_requested",
        created_monotonic_ms=930,
        created_wall_clock_ms=1700000000930,
        cutoff_playback_offset_ms=920,
    )

    assert result.interrupt_candidate["event_name"] == "INTERRUPT_CANDIDATE"
    assert result.interrupt_candidate["caused_by_event_id"] == candidate["event_id"]
    assert result.interrupt_candidate["playback_span_id"] == "playback_slice8_001"
    assert result.interrupt_candidate["playback_offset_ms"] == 910
    assert result.interrupt_candidate["audio_span_id"] == "audio_slice8_barge_001"
    assert result.interrupt_candidate["policy_reason"] == "mock_barge_in_confidence_allows_truncate"
    assert result.interrupt_candidate["confidence_summary"]["barge_in_confidence"] == 0.94
    assert result.truncate_requested["event_name"] == "TTS_TRUNCATE_REQUESTED"
    assert result.truncate_requested["caused_by_event_id"] == result.interrupt_candidate["event_id"]
    assert result.truncate_requested["playback_span_id"] == "playback_slice8_001"
    assert result.truncate_requested["cutoff_playback_offset_ms"] == 920
    assert result.truncate_requested["interrupt_candidate_event_id"] == result.interrupt_candidate["event_id"]
    assert result.truncate_requested["audio_span_id"] == "audio_slice8_barge_001"


def test_interaction_controller_rejects_barge_in_after_playback_finished() -> None:
    startup, playback_progress, playback_committed = _start_playback_with_progress()
    speech_start = _speech_start_during_playback(startup)
    candidate = MockDuplexRuleGate(startup.journal).record_barge_in_candidate(
        speech_start,
        playback_event=playback_progress,
        event_id="evt_mvp0_slice8_barge_candidate",
        created_monotonic_ms=913,
        created_wall_clock_ms=1700000000913,
        playback_offset_ms=910,
        echo_likelihood="low",
        vad_confidence=0.96,
        barge_in_confidence=0.94,
        playback_reference_ref="playback-ref://synthetic/mvp0/slice8-reference",
    )
    MockTalker(startup.journal).record_finished(
        playback_event=playback_committed,
        event_id="evt_mvp0_slice8_playback_finished",
        created_monotonic_ms=920,
        created_wall_clock_ms=1700000000920,
        final_playback_offset_ms=1000,
    )
    event_ids_before = {event["event_id"] for event in startup.journal.events()}

    with pytest.raises(ValueError, match="active playback"):
        InteractionController(startup.journal).request_truncate_for_barge_in(
            candidate,
            interrupt_event_id="evt_mvp0_slice8_stale_interrupt_candidate",
            truncate_request_event_id="evt_mvp0_slice8_stale_truncate_requested",
            created_monotonic_ms=930,
            created_wall_clock_ms=1700000000930,
            cutoff_playback_offset_ms=920,
        )

    assert {event["event_id"] for event in startup.journal.events()} == event_ids_before


def test_interaction_controller_rejects_duplicate_barge_in_after_tts_truncated() -> None:
    startup, playback_progress, _playback_committed = _start_playback_with_progress()
    speech_start = _speech_start_during_playback(startup)
    candidate = MockDuplexRuleGate(startup.journal).record_barge_in_candidate(
        speech_start,
        playback_event=playback_progress,
        event_id="evt_mvp0_slice8_barge_candidate",
        created_monotonic_ms=913,
        created_wall_clock_ms=1700000000913,
        playback_offset_ms=910,
        echo_likelihood="low",
        vad_confidence=0.96,
        barge_in_confidence=0.94,
        playback_reference_ref="playback-ref://synthetic/mvp0/slice8-reference",
    )
    truncate = InteractionController(startup.journal).request_truncate_for_barge_in(
        candidate,
        interrupt_event_id="evt_mvp0_slice8_interrupt_candidate",
        truncate_request_event_id="evt_mvp0_slice8_truncate_requested",
        created_monotonic_ms=930,
        created_wall_clock_ms=1700000000930,
        cutoff_playback_offset_ms=920,
    )
    MockTalker(startup.journal).record_truncated(
        truncate.truncate_requested,
        event_id="evt_mvp0_slice8_tts_truncated",
        created_monotonic_ms=960,
        created_wall_clock_ms=1700000000960,
        actual_stop_offset_ms=930,
    )
    event_ids_before = {event["event_id"] for event in startup.journal.events()}

    with pytest.raises(ValueError, match="active playback"):
        InteractionController(startup.journal).request_truncate_for_barge_in(
            candidate,
            interrupt_event_id="evt_mvp0_slice8_duplicate_interrupt_candidate",
            truncate_request_event_id="evt_mvp0_slice8_duplicate_truncate_requested",
            created_monotonic_ms=970,
            created_wall_clock_ms=1700000000970,
            cutoff_playback_offset_ms=940,
        )

    assert {event["event_id"] for event in startup.journal.events()} == event_ids_before


def test_mock_talker_confirms_truncate_with_actual_stop_offset() -> None:
    startup, playback_progress, _playback_committed = _start_playback_with_progress()
    speech_start = _speech_start_during_playback(startup)
    candidate = MockDuplexRuleGate(startup.journal).record_barge_in_candidate(
        speech_start,
        playback_event=playback_progress,
        event_id="evt_mvp0_slice8_barge_candidate",
        created_monotonic_ms=913,
        created_wall_clock_ms=1700000000913,
        playback_offset_ms=910,
        echo_likelihood="low",
        vad_confidence=0.96,
        barge_in_confidence=0.94,
        playback_reference_ref="playback-ref://synthetic/mvp0/slice8-reference",
    )
    truncate = InteractionController(startup.journal).request_truncate_for_barge_in(
        candidate,
        interrupt_event_id="evt_mvp0_slice8_interrupt_candidate",
        truncate_request_event_id="evt_mvp0_slice8_truncate_requested",
        created_monotonic_ms=930,
        created_wall_clock_ms=1700000000930,
        cutoff_playback_offset_ms=920,
    )

    truncated = MockTalker(startup.journal).record_truncated(
        truncate.truncate_requested,
        event_id="evt_mvp0_slice8_tts_truncated",
        created_monotonic_ms=960,
        created_wall_clock_ms=1700000000960,
        actual_stop_offset_ms=930,
    )

    assert truncated["event_name"] == "TTS_TRUNCATED"
    assert truncated["caused_by_event_id"] == truncate.truncate_requested["event_id"]
    assert truncated["playback_span_id"] == "playback_slice8_001"
    assert truncated["actual_stop_offset_ms"] == 930
    assert truncated["truncate_request_event_id"] == truncate.truncate_requested["event_id"]
    assert truncated["output_mode"] == "mock"
    assert truncated["mock_profile_ref"] == "mock-profile://synthetic/mvp0/talker-playback-v1"
