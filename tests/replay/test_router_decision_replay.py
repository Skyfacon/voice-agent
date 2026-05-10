from __future__ import annotations

import pytest

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


ROUTER_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "006-mock-understanding-router.fixture.json"


def test_router_fixture_replays_mock_understanding_and_task_focus_state() -> None:
    fixture = load_json_fixture(ROUTER_FIXTURE)
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
        "MOCK_ASR_FRAME_EMITTED",
        "MOCK_THINKER_FRAME_EMITTED",
        "ROUTER_DECISION_EMITTED",
    ]
    assert result.interaction_state.turn_phase == "TURN_COMMITTED"
    assert result.interaction_state.current_audio_span_id == "audio_slice6_001"
    assert result.adapter_health_state.output_event_modes == {
        "evt_mvp0_slice6_mock_asr": "mock",
        "evt_mvp0_slice6_mock_thinker": "mock",
    }
    assert result.task_focus_state.active_task_id is None
    assert result.task_focus_state.foreground_mode == "FAST_RESPONSE"
    assert result.task_focus_state.side_conversation_allowed is True
    assert result.task_focus_state.default_patch_policy == "NO_ACTIVE_TASK"
    assert result.task_focus_state.ambiguous_input_policy == "CLARIFY"
    assert result.task_focus_state.last_focus_decision == "FOREGROUND_CHAT"
    assert result.task_focus_state.last_focus_confidence == 1.0
    assert result.task_focus_state.last_focus_event_id == "evt_mvp0_slice6_router_decision"
    assert result.state_digest["last_event_seq"] == 12
    assert result.state_digest["task_focus_state_hash"]
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"


def test_replay_rejects_mock_frames_before_turn_commit() -> None:
    fixture = load_json_fixture(ROUTER_FIXTURE)
    events = [dict(event) for event in fixture["events"]]
    asr_index = next(index for index, event in enumerate(events) if event["event_name"] == "MOCK_ASR_FRAME_EMITTED")
    early_asr = dict(events.pop(asr_index))
    early_asr["event_seq"] = 3
    early_asr["caused_by_event_id"] = "evt_mvp0_slice6_capability_snapshot"
    shifted_events = [
        *events[:2],
        early_asr,
        *[dict(event, event_seq=int(event["event_seq"]) + 1) for event in events[2:]],
    ]
    fixture["events"] = shifted_events

    with pytest.raises(ReplayValidationError, match="MOCK_ASR_FRAME_EMITTED.*TURN_INGRESS_COMMITTED"):
        run_replay_fixture(fixture)


def test_replay_rejects_router_decision_before_mock_frames() -> None:
    fixture = load_json_fixture(ROUTER_FIXTURE)
    events = [dict(event) for event in fixture["events"]]
    router_index = next(index for index, event in enumerate(events) if event["event_name"] == "ROUTER_DECISION_EMITTED")
    router_event = dict(events.pop(router_index))
    router_event["event_seq"] = 10
    router_event["caused_by_event_id"] = "evt_turn_slice6_audio_001_ingress_committed"
    reordered_events = [
        *events[:9],
        router_event,
        *[dict(event, event_seq=int(event["event_seq"]) + 1) for event in events[9:]],
    ]
    fixture["events"] = reordered_events

    with pytest.raises(
        ReplayValidationError,
        match="ROUTER_DECISION_EMITTED.*MOCK_ASR_FRAME_EMITTED or MOCK_THINKER_FRAME_EMITTED",
    ):
        run_replay_fixture(fixture)


def test_replay_accepts_router_decision_with_only_prior_thinker_frame() -> None:
    fixture = load_json_fixture(ROUTER_FIXTURE)
    events = [dict(event) for event in fixture["events"] if event["event_name"] != "MOCK_ASR_FRAME_EMITTED"]
    router_event = next(event for event in events if event["event_name"] == "ROUTER_DECISION_EMITTED")
    router_event.pop("asr_frame_event_id")
    fixture["events"] = events

    result = run_replay_fixture(fixture)

    assert "MOCK_ASR_FRAME_EMITTED" not in {event["event_name"] for event in result.ordered_events}
    assert result.adapter_health_state.output_event_modes == {
        "evt_mvp0_slice6_mock_thinker": "mock",
    }
    assert result.task_focus_state.foreground_mode == "FAST_RESPONSE"
    assert result.task_focus_state.last_focus_event_id == "evt_mvp0_slice6_router_decision"


def test_replay_rejects_router_reference_to_unavailable_mock_asr_frame() -> None:
    fixture = load_json_fixture(ROUTER_FIXTURE)
    fixture["events"] = [
        dict(event) for event in fixture["events"] if event["event_name"] != "MOCK_ASR_FRAME_EMITTED"
    ]

    with pytest.raises(ReplayValidationError, match="asr_frame_event_id requires prior mock ASR"):
        run_replay_fixture(fixture)


def test_router_fixture_contains_only_synthetic_refs_and_no_slice7_plus_events() -> None:
    fixture = load_json_fixture(ROUTER_FIXTURE)
    event_names = {event["event_name"] for event in fixture["events"]}

    assert "PLAYBACK_SPAN_STARTED" not in event_names
    assert "PLAYBACK_PROGRESS" not in event_names
    assert "PLAYBACK_COMMITTED" not in event_names
    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names
    for event in fixture["events"]:
        assert "plan_version" not in event
        assert "task_id" not in event
        assert "raw_transcript" not in event
        assert "prompt" not in event
        assert "provider_response" not in event
