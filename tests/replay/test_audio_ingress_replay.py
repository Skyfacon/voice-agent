from __future__ import annotations

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import run_replay_fixture


AUDIO_INGRESS_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "005-audio-ingress-accepted.fixture.json"


def test_audio_ingress_fixture_replays_to_committed_interaction_state() -> None:
    fixture = load_json_fixture(AUDIO_INGRESS_FIXTURE)
    result = run_replay_fixture(fixture)

    assert [event["event_name"] for event in result.ordered_events] == [
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
    assert result.interaction_state.turn_phase == "TURN_COMMITTED"
    assert result.interaction_state.last_ingress_outcome == "COMMITTED"
    assert result.interaction_state.current_audio_span_id == "audio_slice5_001"
    assert result.interaction_state.current_text_span_id is None
    assert result.interaction_state.directedness == "ASSUMED_DIRECTED"
    assert result.interaction_state.semantic_close == "ASSUMED_CLOSED"
    assert result.state_digest["last_event_seq"] == 9
    assert result.state_digest["overall_digest"]
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"


def test_audio_ingress_fixture_has_no_router_or_model_events_before_slice6() -> None:
    fixture = load_json_fixture(AUDIO_INGRESS_FIXTURE)
    event_names = [event["event_name"] for event in fixture["events"]]

    assert "ROUTER_DECISION_EMITTED" not in event_names
    assert "MOCK_ASR_FRAME_EMITTED" not in event_names
    assert "MOCK_THINKER_FRAME_EMITTED" not in event_names


def test_audio_ingress_fixture_uses_metadata_refs_and_no_raw_audio() -> None:
    fixture = load_json_fixture(AUDIO_INGRESS_FIXTURE)
    events = [validate_event_envelope(event) for event in fixture["events"]]
    audio_events = [
        event
        for event in events
        if event["event_name"] in {"AUDIO_SPAN_STARTED", "AUDIO_SPAN_ENDED"}
    ]
    duplex_events = [
        event
        for event in events
        if event["event_name"] in {"SPEECH_START_DETECTED", "SPEECH_END_DETECTED"}
    ]

    assert audio_events[0]["audio_format_ref"] == "audio-format://synthetic/mvp0/pcm16-16khz-mono"
    assert audio_events[0]["audio_sample_offset"] == 0
    assert audio_events[1]["audio_sample_offset"] == 16000
    assert audio_events[1]["duration_ms"] == 1000
    assert [event["detection_basis"] for event in duplex_events] == [
        "mock_rule:speech_start_on_audio_span_started",
        "mock_rule:speech_end_on_audio_span_ended",
    ]
    for event in events:
        assert "raw_audio" not in event
        assert "audio_bytes" not in event
        assert "audio_payload" not in event
        assert "audio_chunk_ref" not in event
