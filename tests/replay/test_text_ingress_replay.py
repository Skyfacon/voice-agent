from __future__ import annotations

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import run_replay_fixture


TEXT_INGRESS_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "004-text-ingress.fixture.json"


def test_text_ingress_fixture_validates_and_replays_to_committed_interaction_state() -> None:
    fixture = load_json_fixture(TEXT_INGRESS_FIXTURE)
    result = run_replay_fixture(fixture)

    assert [event["event_name"] for event in result.ordered_events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "TEXT_INPUT_RECEIVED",
        "TURN_OPENED",
        "TURN_INGRESS_ACCEPTED",
        "TURN_INGRESS_COMMITTED",
    ]
    assert result.interaction_state.turn_phase == "TURN_COMMITTED"
    assert result.interaction_state.last_ingress_outcome == "COMMITTED"
    assert result.interaction_state.current_input_span_id == "input_slice4_text_001"
    assert result.interaction_state.current_text_span_id == "text_slice4_001"
    assert result.interaction_state.current_audio_span_id is None
    assert result.interaction_state.directedness == "ASSUMED_DIRECTED"
    assert result.interaction_state.semantic_close == "ASSUMED_CLOSED"
    assert result.state_digest["last_event_seq"] == 6
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"


def test_text_ingress_fixture_has_no_router_or_model_events_before_slice6() -> None:
    fixture = load_json_fixture(TEXT_INGRESS_FIXTURE)
    event_names = [event["event_name"] for event in fixture["events"]]

    assert "ROUTER_DECISION_EMITTED" not in event_names
    assert "MOCK_ASR_FRAME_EMITTED" not in event_names
    assert "MOCK_THINKER_FRAME_EMITTED" not in event_names


def test_text_ingress_fixture_uses_redacted_text_and_no_audio_span() -> None:
    fixture = load_json_fixture(TEXT_INGRESS_FIXTURE)
    events = [validate_event_envelope(event) for event in fixture["events"]]
    text_event = next(event for event in events if event["event_name"] == "TEXT_INPUT_RECEIVED")

    assert text_event["redacted_text"] == "[synthetic text: hello assistant]"
    assert text_event["audio_span_id"] is None
    assert "text_ref" not in text_event
