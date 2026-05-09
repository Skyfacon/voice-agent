from __future__ import annotations

import random
import socket
import time

import pytest

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.manifest import ReplayManifestError, validate_replay_manifest
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


SLICE3_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "003-replay-empty-and-startup.fixture.json"


def test_replay_manifest_rejects_github_fixture_with_unsafe_safety_flags() -> None:
    fixture = load_json_fixture(SLICE3_FIXTURE)
    manifest = dict(fixture["replay_manifest"])
    manifest["contains_raw_audio"] = True

    with pytest.raises(ReplayManifestError, match="contains_raw_audio"):
        validate_replay_manifest(manifest)


def test_deterministic_replay_sorts_by_event_seq_not_wall_clock() -> None:
    fixture = load_json_fixture(SLICE3_FIXTURE)

    result = run_replay_fixture(fixture)

    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"
    assert [event["event_id"] for event in result.ordered_events] == [
        "evt_mvp0_slice3_session_started",
        "evt_mvp0_slice3_capability_snapshot",
    ]
    assert [event["created_wall_clock_ms"] for event in result.ordered_events] == [
        1700000000300,
        1700000000200,
    ]


def test_deterministic_replay_rebuilds_startup_adapter_health_and_trace_privacy() -> None:
    result = run_replay_fixture(load_json_fixture(SLICE3_FIXTURE))

    assert result.adapter_health_state.capability_snapshot_ref == (
        "capability://synthetic/mvp0/mock-adapters-v1"
    )
    assert result.adapter_health_state.adapters["mock_asr"].adapter_type == "asr"
    assert result.adapter_health_state.adapters["mock_thinker"].deployment_mode == "mock"
    assert result.adapter_health_state.adapters["mock_talker"].output_mode == "mock"
    assert result.trace_privacy_state.fixture_domain == "GITHUB_ALLOWED"
    assert result.trace_privacy_state.replay_mode == "deterministic"
    assert result.trace_privacy_state.contains_raw_audio is False
    assert result.trace_privacy_state.contains_secrets is False
    assert result.state_digest["source_session_id"] == "sess_mvp0_slice3_synthetic"
    assert result.state_digest["last_event_seq"] == 2
    assert result.state_digest["overall_digest"]


def test_replay_preserves_missing_data_plane_refs_as_unavailable_metadata() -> None:
    fixture = load_json_fixture(SLICE3_FIXTURE)
    events = list(fixture["events"])
    events.append(
        {
            "event_name": "PLAYBACK_SPAN_STARTED",
            "event_id": "evt_mvp0_slice3_playback_started",
            "event_seq": 3,
            "event_schema_version": "1.0",
            "session_id": "sess_mvp0_slice3_synthetic",
            "conversation_id": "conv_mvp0_slice3_synthetic",
            "source_module": "talker",
            "created_monotonic_ms": 310,
            "created_wall_clock_ms": 1700000000310,
            "caused_by_event_id": "evt_mvp0_slice3_capability_snapshot",
            "trace_redaction_level": "metadata_only",
            "playback_span_id": "playback_synthetic_001",
            "audio_ref": "audio://synthetic/mvp0/generated-playback-001",
        }
    )
    fixture["events"] = events

    result = run_replay_fixture(fixture)

    assert {
        "event_id": "evt_mvp0_slice3_playback_started",
        "field": "audio_ref",
        "ref": "audio://synthetic/mvp0/generated-playback-001",
        "status": "unavailable",
    } in result.diagnostics["data_plane_refs"]


def test_replay_does_not_call_network_clock_random_or_missing_ref_fetchers(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = load_json_fixture(SLICE3_FIXTURE)

    monkeypatch.setattr(time, "time", lambda: pytest.fail("replay must not call wall clock"))
    monkeypatch.setattr(time, "monotonic", lambda: pytest.fail("replay must not call monotonic clock"))
    monkeypatch.setattr(random, "random", lambda: pytest.fail("replay must not call randomness"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("replay must not call network"),
    )

    result = run_replay_fixture(fixture)

    assert result.state_digest["overall_digest"]


def test_replay_rejects_duplicate_event_seq_before_reducing() -> None:
    fixture = load_json_fixture(SLICE3_FIXTURE)
    fixture["events"] = [dict(event, event_seq=1) for event in fixture["events"]]

    with pytest.raises(ReplayValidationError, match="Duplicate event_seq"):
        run_replay_fixture(fixture)


def test_slice3_fixture_exists_in_expected_repo_safe_location() -> None:
    assert SLICE3_FIXTURE.parent == MVP0_REPLAY_FIXTURE_DIR
    assert SLICE3_FIXTURE.name == "003-replay-empty-and-startup.fixture.json"
    assert "replays/local" not in SLICE3_FIXTURE.as_posix()
