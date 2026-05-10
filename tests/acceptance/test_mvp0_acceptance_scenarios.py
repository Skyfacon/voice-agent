from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import MVP0_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.scenario_assertions import (
    MVP0AcceptanceError,
    assert_fixture_has_no_forbidden_mvp0_scope,
    run_mvp0_acceptance_manifest,
)


MANIFEST_INDEX = MVP0_REPLAY_FIXTURE_DIR / "manifest.index.json"
REQUIRED_SCENARIOS = [
    "MVP0-TEXT-INGRESS-001",
    "MVP0-AUDIO-INGRESS-001",
    "MVP0-BARGE-IN-TRUNCATE-001",
    "MVP0-MOCK-ADAPTER-CAPABILITY-001",
    "MVP0-LOCAL-TRACE-SAFETY-001",
]


def test_mvp0_acceptance_manifest_executes_required_scenarios_and_fixture_checks() -> None:
    result = run_mvp0_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP0_REPLAY_FIXTURE_DIR,
    )

    assert [scenario.scenario_id for scenario in result.scenario_results] == REQUIRED_SCENARIOS
    assert {scenario.result_status for scenario in result.scenario_results} == {"passed"}
    assert result.summary["result_status"] == "passed"
    assert result.summary["scenario_count"] == 5
    assert result.summary["validated_fixture_names"] == [
        "002-mock-capability-snapshot.fixture.json",
        "004-text-ingress.fixture.json",
        "005-audio-ingress-accepted.fixture.json",
        "006-mock-understanding-router.fixture.json",
        "007-playback-progress.fixture.json",
        "008-barge-in-truncate.fixture.json",
        "009-local-trace-safety.fixture.json",
    ]


def test_mvp0_acceptance_runner_reports_mock_slo_measurement_labels() -> None:
    result = run_mvp0_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP0_REPLAY_FIXTURE_DIR,
    )
    barge_in = next(
        scenario
        for scenario in result.scenario_results
        if scenario.scenario_id == "MVP0-BARGE-IN-TRUNCATE-001"
    )

    assert barge_in.slo_measurements == (
        {
            "name": "barge_in_to_truncate_command_latency",
            "latency_ms": 17,
            "max_latency_ms": 250,
            "output_mode": "mock",
            "result_status": "passed",
        },
    )


def test_mvp0_acceptance_fails_when_scenario_fixture_skips_fixture_checks() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["fixture_checks"] = [
        check
        for check in manifest["fixture_checks"]
        if check["fixture"] != "008-barge-in-truncate.fixture.json"
    ]

    with pytest.raises(MVP0AcceptanceError, match="fixture_checks"):
        run_mvp0_acceptance_manifest(
            manifest,
            fixture_dir=MVP0_REPLAY_FIXTURE_DIR,
        )


def test_mvp0_acceptance_rejects_negative_slo_latency() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    barge_in = next(
        scenario
        for scenario in manifest["scenarios"]
        if scenario["scenario_id"] == "MVP0-BARGE-IN-TRUNCATE-001"
    )
    measurement = barge_in["slo_measurements"][0]
    measurement["start_event_id"], measurement["end_event_id"] = (
        measurement["end_event_id"],
        measurement["start_event_id"],
    )

    with pytest.raises(MVP0AcceptanceError, match="negative latency"):
        run_mvp0_acceptance_manifest(
            manifest,
            fixture_dir=MVP0_REPLAY_FIXTURE_DIR,
        )


def test_text_ingress_acceptance_requires_mock_thinker_router_handoff() -> None:
    result = run_mvp0_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP0_REPLAY_FIXTURE_DIR,
    )
    text = next(
        scenario
        for scenario in result.scenario_results
        if scenario.scenario_id == "MVP0-TEXT-INGRESS-001"
    )

    assert text.fixture_name == "007-playback-progress.fixture.json"
    assert text.assertion_summary["mock_thinker_event_id"] == "evt_mvp0_slice7_mock_thinker"
    assert text.assertion_summary["router_event_id"] == "evt_mvp0_slice7_router_decision"
    assert text.assertion_summary["router_decision"] == "FAST_ONLY"


def test_local_trace_safety_scenario_replays_trace_privacy_counters() -> None:
    result = run_mvp0_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP0_REPLAY_FIXTURE_DIR,
    )
    trace_safety = next(
        scenario
        for scenario in result.scenario_results
        if scenario.scenario_id == "MVP0-LOCAL-TRACE-SAFETY-001"
    )

    assert trace_safety.assertion_summary["fixture_domain"] == "GITHUB_ALLOWED"
    assert trace_safety.assertion_summary["contains_raw_audio"] is False
    assert trace_safety.assertion_summary["redaction_count"] == 1
    assert trace_safety.assertion_summary["blocked_write_count"] == 1
    assert trace_safety.assertion_summary["trace_write_degraded_count"] == 1
    assert trace_safety.assertion_summary["replay_result_status"] == "passed"


def test_mvp0_acceptance_fails_for_forbidden_scope_event_names() -> None:
    fixture = load_json_fixture(MVP0_REPLAY_FIXTURE_DIR / "004-text-ingress.fixture.json")
    events = deepcopy(fixture["events"])
    events[-1]["event_name"] = "SLOWTASK_CREATED"

    with pytest.raises(MVP0AcceptanceError, match="forbidden MVP0 event_name"):
        assert_fixture_has_no_forbidden_mvp0_scope(events)


def test_mvp0_acceptance_fails_for_forbidden_scope_source_modules() -> None:
    fixture = load_json_fixture(MVP0_REPLAY_FIXTURE_DIR / "004-text-ingress.fixture.json")
    events = deepcopy(fixture["events"])
    events[-1]["source_module"] = "tool_executor"

    with pytest.raises(MVP0AcceptanceError, match="forbidden MVP0 source_module"):
        assert_fixture_has_no_forbidden_mvp0_scope(events)
