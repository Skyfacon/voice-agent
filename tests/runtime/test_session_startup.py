from __future__ import annotations

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.runtime.session import start_mvp0_session


def test_start_mvp0_session_records_start_then_capability_snapshot() -> None:
    startup = start_mvp0_session(
        session_id="sess_mvp0_slice2_synthetic",
        conversation_id="conv_mvp0_slice2_synthetic",
        runtime_config_ref="config://synthetic/mvp0/default",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
    )

    events = startup.journal.events()

    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
    ]
    assert [event["event_seq"] for event in events] == [1, 2]
    assert "caused_by_event_id" not in events[0]
    assert events[1]["caused_by_event_id"] == events[0]["event_id"]
    assert events[0]["capability_snapshot_ref"] == events[1]["capability_snapshot_ref"]
    assert events[1]["adapter_ids"] == ["mock_asr", "mock_thinker", "mock_talker"]
    assert events[1]["adapter_types"] == ["asr", "thinker", "tts"]
    assert events[1]["deployment_modes"] == ["mock", "mock", "mock"]
    assert events[1]["output_modes"] == ["mock", "mock", "mock"]

    for event in events:
        assert validate_event_envelope(event) == event


def test_mvp0_capability_snapshot_fixture_validates_through_event_validator() -> None:
    fixture = load_json_fixture(
        MVP0_REPLAY_FIXTURE_DIR / "002-mock-capability-snapshot.fixture.json"
    )

    events = [validate_event_envelope(event) for event in fixture["events"]]

    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
    ]
    assert events[1]["caused_by_event_id"] == events[0]["event_id"]
    assert events[1]["output_modes"] == ["mock", "mock", "mock"]
