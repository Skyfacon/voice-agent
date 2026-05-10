from __future__ import annotations

from copy import deepcopy

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture


BARGE_IN_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "008-barge-in-truncate.fixture.json"


def test_barge_in_truncate_fixture_replays_truncated_playback_state() -> None:
    result = run_replay_fixture(load_json_fixture(BARGE_IN_FIXTURE))

    assert [event["event_name"] for event in result.ordered_events[-4:]] == [
        "BARGE_IN_CANDIDATE",
        "INTERRUPT_CANDIDATE",
        "TTS_TRUNCATE_REQUESTED",
        "TTS_TRUNCATED",
    ]
    assert result.playback_state.current_playback_span_id == "playback_slice8_001"
    assert result.playback_state.phase == "TRUNCATED"
    assert result.playback_state.latest_playback_offset_ms == 900
    assert result.playback_state.latest_committed_offset_ms == 850
    assert result.playback_state.cutoff_playback_offset_ms == 920
    assert result.playback_state.actual_stop_offset_ms == 930
    assert result.playback_state.truncate_request_event_id == "evt_mvp0_slice8_truncate_requested"
    assert result.interaction_state.current_audio_span_id == "audio_slice8_barge_001"
    assert result.interaction_state.current_playback_span_id == "playback_slice8_001"
    assert result.interaction_state.turn_phase == "INTERRUPTING"
    assert result.interaction_state.playback_phase == "TRUNCATED"
    assert result.state_digest["last_event_seq"] == 18
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"


def test_barge_in_truncate_fixture_preserves_distinct_offsets_and_causal_refs() -> None:
    fixture = load_json_fixture(BARGE_IN_FIXTURE)
    events = {event["event_id"]: event for event in fixture["events"]}
    candidate = events["evt_mvp0_slice8_barge_candidate"]
    interrupt = events["evt_mvp0_slice8_interrupt_candidate"]
    request = events["evt_mvp0_slice8_truncate_requested"]
    truncated = events["evt_mvp0_slice8_tts_truncated"]

    assert candidate["playback_offset_ms"] == 910
    assert interrupt["playback_offset_ms"] == 910
    assert request["cutoff_playback_offset_ms"] == 920
    assert truncated["actual_stop_offset_ms"] == 930
    assert len({candidate["playback_offset_ms"], request["cutoff_playback_offset_ms"], truncated["actual_stop_offset_ms"]}) == 3
    assert interrupt["caused_by_event_id"] == candidate["event_id"]
    assert request["caused_by_event_id"] == interrupt["event_id"]
    assert request["interrupt_candidate_event_id"] == interrupt["event_id"]
    assert truncated["caused_by_event_id"] == request["event_id"]
    assert truncated["truncate_request_event_id"] == request["event_id"]


def test_stale_truncate_request_after_terminal_span_does_not_regress_replay_state() -> None:
    fixture = load_json_fixture(BARGE_IN_FIXTURE)
    request = next(event for event in fixture["events"] if event["event_id"] == "evt_mvp0_slice8_truncate_requested")
    stale_request = deepcopy(request)
    stale_request.update(
        {
            "event_id": "evt_mvp0_slice8_stale_truncate_requested",
            "event_seq": 19,
            "created_monotonic_ms": 970,
            "created_wall_clock_ms": 1700000000970,
            "cutoff_playback_offset_ms": 940,
        }
    )
    fixture["events"].append(stale_request)

    result = run_replay_fixture(fixture)

    assert result.playback_state.phase == "TRUNCATED"
    assert result.playback_state.cutoff_playback_offset_ms == 920
    assert result.playback_state.actual_stop_offset_ms == 930
    assert result.playback_state.truncate_request_event_id == "evt_mvp0_slice8_truncate_requested"


def test_barge_in_truncate_fixture_contains_only_mock_metadata_and_no_slice9_events() -> None:
    fixture = load_json_fixture(BARGE_IN_FIXTURE)
    event_names = {event["event_name"] for event in fixture["events"]}

    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "TOOL_CALL_STARTED" not in event_names
    for event in fixture["events"]:
        assert "plan_version" not in event
        assert "task_id" not in event
        assert "raw_audio" not in event
        assert "raw_audio_ref" not in event
        assert "provider_response" not in event
    assert {event["output_mode"] for event in fixture["events"] if event["event_name"] == "BARGE_IN_CANDIDATE"} == {
        "mock"
    }
    assert {event["output_mode"] for event in fixture["events"] if event["event_name"] == "TTS_TRUNCATED"} == {
        "mock"
    }
