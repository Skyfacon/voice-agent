from __future__ import annotations

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture


BARGE_IN_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "008-barge-in-truncate.fixture.json"


def test_barge_in_to_truncate_command_latency_is_computable_and_within_mvp0_slo() -> None:
    fixture = load_json_fixture(BARGE_IN_FIXTURE)
    events = {event["event_id"]: event for event in fixture["events"]}
    candidate = events["evt_mvp0_slice8_barge_candidate"]
    request = events["evt_mvp0_slice8_truncate_requested"]

    latency_ms = int(request["created_monotonic_ms"]) - int(candidate["created_monotonic_ms"])

    assert request["caused_by_event_id"] == "evt_mvp0_slice8_interrupt_candidate"
    assert request["interrupt_candidate_event_id"] == "evt_mvp0_slice8_interrupt_candidate"
    assert candidate["output_mode"] == "mock"
    assert latency_ms == 17
    assert latency_ms <= 250
