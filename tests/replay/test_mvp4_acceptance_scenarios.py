from __future__ import annotations

from copy import deepcopy
import random
import socket
import time

import pytest

from conftest import REPO_ROOT, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


MVP4_REPLAY_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "replay" / "mvp4"
PROVIDER_FREE_FIXTURE = MVP4_REPLAY_FIXTURE_DIR / "000-provider-free-voice-e2e.fixture.json"
MANIFEST_INDEX = MVP4_REPLAY_FIXTURE_DIR / "manifest.index.json"


def test_mvp4_provider_free_fixture_replays_three_router_outcomes_without_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = load_json_fixture(PROVIDER_FREE_FIXTURE)
    mvp4.validate_provider_free_fixture_safety(fixture)

    monkeypatch.setattr(time, "time", lambda: pytest.fail("replay must not call wall clock"))
    monkeypatch.setattr(time, "monotonic", lambda: pytest.fail("replay must not call monotonic clock"))
    monkeypatch.setattr(random, "random", lambda: pytest.fail("replay must not call randomness"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("replay must not call network"),
    )

    result = run_replay_fixture(fixture)
    router_events = [
        event for event in result.ordered_events if event["event_name"] == "ROUTER_DECISION_EMITTED"
    ]
    events_by_id = {event["event_id"]: event for event in result.ordered_events}

    assert result.result_status == "passed"
    assert [event["router_decision"] for event in router_events] == [
        "FAST_ONLY",
        "SPAWN_SLOW_TASK",
        "PATCH_ACTIVE_SLOW_TASK",
    ]
    assert {
        event["event_name"]
        for event in result.ordered_events
        if event["event_name"].startswith(("ASR_", "THINKER_"))
    } == set()
    assert result.adapter_health_state.output_event_modes == {
        "evt_mvp4_voice_e2e_fast_mock_asr": "mock",
        "evt_mvp4_voice_e2e_fast_mock_thinker": "mock",
        "evt_mvp4_voice_e2e_spawn_mock_asr": "mock",
        "evt_mvp4_voice_e2e_spawn_mock_thinker": "mock",
        "evt_mvp4_voice_e2e_patch_mock_asr": "mock",
        "evt_mvp4_voice_e2e_patch_mock_thinker": "mock",
    }

    for router_event in router_events:
        asr_event = events_by_id[router_event["asr_frame_event_id"]]
        thinker_event = events_by_id[router_event["thinker_frame_event_id"]]
        turn_event = events_by_id[router_event["turn_committed_event_id"]]
        assert asr_event["event_seq"] < router_event["event_seq"]
        assert thinker_event["event_seq"] < router_event["event_seq"]
        assert asr_event["caused_by_event_id"] == turn_event["event_id"]
        assert thinker_event["caused_by_event_id"] == turn_event["event_id"]
        assert asr_event["turn_id"] == router_event["turn_id"]
        assert thinker_event["turn_id"] == router_event["turn_id"]
        assert "raw_transcript" not in repr(router_event)
        assert "provider_body" not in router_event
        assert "provider_response" not in router_event
        assert "provider_payload" not in router_event


def test_mvp4_manifest_index_is_metadata_only_and_maps_slice1_slice2_fixture() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)

    assert manifest["manifest_index_schema_version"] == "1.0"
    assert manifest["suite_id"] == "MVP4-PROVIDER-FREE-VOICE-SPINE"
    assert manifest["fixture_domain"] == "GITHUB_ALLOWED"
    assert manifest["replay_mode"] == "deterministic"
    assert manifest["required_scenarios"] == [
        "MVP4-VOICE-E2E-PROVIDER-FREE-001",
        "MVP4-VOICE-E2E-ROUTER-FAST-001",
        "MVP4-VOICE-E2E-ROUTER-SPAWN-SLOWTASK-001",
        "MVP4-VOICE-E2E-ROUTER-PATCH-SLOWTASK-001",
        "MVP4-VOICE-E2E-REPLAY-SAFETY-001",
        "MVP4-VOICE-E2E-RAW-ARTIFACT-BLOCK-001",
    ]
    assert manifest["fixture_checks"] == [
        {
            "fixture": "000-provider-free-voice-e2e.fixture.json",
            "purpose": "provider-free synthetic audio turn replay covering fake ASR, fake Thinker, and Router FAST/SPAWN/PATCH decisions",
        },
        {
            "fixture": "008-replay-safety.fixture.json",
            "purpose": "deterministic MVP-4 replay safety fixture proving recorded refs are replayed without provider or runtime reruns",
        }
    ]
    assert manifest["fixture_safety_flags"] == {
        "contains_raw_audio": False,
        "contains_raw_trace": False,
        "contains_real_user_input": False,
        "contains_secrets": False,
        "contains_unredacted_tool_result": False,
        "contains_large_raw_web_content": False,
    }
    assert manifest["safety_flags"] == {
        "contains_raw_audio": False,
        "contains_raw_trace": False,
        "contains_real_user_input": False,
        "contains_secrets": False,
        "contains_unredacted_tool_result": False,
        "contains_large_raw_web_content": False,
    }


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_value", "expected"),
    (
        ("raw_audio", "RIFF synthetic bytes", "raw_audio"),
        ("audio_payload", "UklGRg==", "audio_payload"),
        ("raw_transcript", "synthetic transcript text", "raw_transcript"),
        ("provider_response", {"body": "unsafe"}, "provider_response"),
        ("audio_format_ref", "audio/raw/private-input.wav", "audio/raw/"),
        ("semantic_frame_ref", "replays/local/mvp4/frame.json", "replays/local/"),
        ("asr_frame_ref", "diagnostics/mvp4/asr.jsonl", "diagnostics/"),
    ),
)
def test_mvp4_fixture_safety_rejects_unsafe_artifacts(
    unsafe_field: str,
    unsafe_value: object,
    expected: str,
) -> None:
    fixture = load_json_fixture(PROVIDER_FREE_FIXTURE)
    bad_fixture = deepcopy(fixture)
    if unsafe_field.endswith("_ref"):
        target_event = next(event for event in bad_fixture["events"] if unsafe_field in event)
    else:
        target_event = next(
            event for event in bad_fixture["events"] if event["event_name"] == "AUDIO_SPAN_STARTED"
        )
    target_event[unsafe_field] = unsafe_value

    with pytest.raises(mvp4.MVP4ArtifactSafetyError, match=expected):
        mvp4.validate_provider_free_fixture_safety(bad_fixture)
