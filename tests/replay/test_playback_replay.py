from __future__ import annotations

from copy import deepcopy

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.replay.state_digest import canonical_digest_payload


PLAYBACK_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "007-playback-progress.fixture.json"


def test_playback_fixture_replays_progress_commit_and_finish_state() -> None:
    result = run_replay_fixture(load_json_fixture(PLAYBACK_FIXTURE))

    assert [event["event_name"] for event in result.ordered_events[-4:]] == [
        "PLAYBACK_SPAN_STARTED",
        "PLAYBACK_PROGRESS",
        "PLAYBACK_COMMITTED",
        "PLAYBACK_FINISHED",
    ]
    assert result.playback_state.current_playback_span_id == "playback_slice7_001"
    assert result.playback_state.phase == "FINISHED"
    assert result.playback_state.latest_playback_offset_ms == 1000
    assert result.playback_state.latest_committed_offset_ms == 240
    assert result.playback_state.last_playback_event_id == "evt_mvp0_slice7_playback_finished"
    assert result.interaction_state.last_ingress_outcome == "COMMITTED"
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"
    assert result.state_digest["last_event_seq"] == 13
    assert result.state_digest["playback_state_hash"]


def test_playback_commit_is_delivery_marker_not_interaction_acknowledgement() -> None:
    result = run_replay_fixture(load_json_fixture(PLAYBACK_FIXTURE))

    assert result.interaction_state.current_playback_span_id is None
    assert result.interaction_state.playback_phase == "NOT_PLAYING"
    assert result.interaction_state.turn_phase == "TURN_COMMITTED"
    assert result.playback_state.latest_committed_offset_ms == 240


def test_post_finish_commit_replays_as_latest_committed_offset() -> None:
    fixture = load_json_fixture(PLAYBACK_FIXTURE)
    finish_event = fixture["events"][-1]
    post_finish_commit = deepcopy(finish_event)
    post_finish_commit.update(
        {
            "event_name": "PLAYBACK_COMMITTED",
            "event_id": "evt_mvp0_slice7_playback_committed_after_finish",
            "event_seq": 14,
            "created_monotonic_ms": 781,
            "created_wall_clock_ms": 1700000000781,
            "caused_by_event_id": finish_event["event_id"],
            "playback_offset_ms": 1000,
            "commit_basis": "mock_delivery_marker",
        }
    )
    post_finish_commit.pop("final_playback_offset_ms")
    post_finish_commit.pop("finish_reason")
    fixture["events"].append(post_finish_commit)

    result = run_replay_fixture(fixture)

    assert result.playback_state.phase == "FINISHED"
    assert result.playback_state.latest_playback_offset_ms == 1000
    assert result.playback_state.latest_committed_offset_ms == 1000
    assert result.playback_state.last_playback_event_id == "evt_mvp0_slice7_playback_committed_after_finish"


def test_playback_fixture_uses_only_mock_synthetic_refs_and_metadata() -> None:
    fixture = load_json_fixture(PLAYBACK_FIXTURE)
    playback_events = [
        event for event in fixture["events"] if event["event_name"].startswith("PLAYBACK_")
    ]

    assert {event["output_mode"] for event in playback_events} == {"mock"}
    assert playback_events[0]["audio_ref"] == "audio://synthetic/mvp0/mock-playback-slice7-001"
    assert all(event["playback_span_id"] == "playback_slice7_001" for event in playback_events)
    for event in playback_events:
        assert "raw_audio" not in event
        assert "raw_audio_ref" not in event
        assert "provider_response" not in event

    result_like_state = {"playback": playback_events}
    canonical = canonical_digest_payload(result_like_state)
    assert "raw_audio" not in repr(canonical)
    assert result_like_state["playback"][0]["audio_ref"].startswith("audio://synthetic/")
