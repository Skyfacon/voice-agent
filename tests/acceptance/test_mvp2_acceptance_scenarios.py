from __future__ import annotations

from copy import deepcopy
import json
import re
import shutil

import pytest

from conftest import MVP2_REPLAY_FIXTURE_DIR, REPO_ROOT, load_json_fixture
from voice_agent.replay.scenario_assertions import (
    MVP2AcceptanceError,
    assert_fixture_has_no_forbidden_mvp2_scope,
    assert_mvp2_fixture_is_repo_safe,
    run_mvp2_acceptance_manifest,
)


MANIFEST_INDEX = MVP2_REPLAY_FIXTURE_DIR / "manifest.index.json"
SCENARIO_SPEC = REPO_ROOT / "docs" / "specs" / "mvp2-acceptance-scenarios.md"


def test_mvp2_acceptance_manifest_executes_required_scenarios_fixture_checks_and_scope_gates() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    expected_scenarios = _scenario_ids_from_spec()

    result = run_mvp2_acceptance_manifest(
        manifest,
        fixture_dir=MVP2_REPLAY_FIXTURE_DIR,
        required_scenario_ids=expected_scenarios,
    )

    assert [scenario.scenario_id for scenario in result.scenario_results] == expected_scenarios
    assert {scenario.result_status for scenario in result.scenario_results} == {"passed"}
    assert result.summary["suite_id"] == "MVP2-ACCEPTANCE"
    assert result.summary["result_status"] == "passed"
    assert result.summary["scenario_count"] == len(expected_scenarios)
    assert result.summary["fixture_count"] == 10
    assert result.summary["deterministic_replay_verified"] is True
    assert result.summary["runtime_execution_detected"] is False
    assert result.summary["adr_update_required"] is False
    assert result.summary["hidden_future_scope_detected"] is False
    assert result.summary["validated_fixture_names"] == [
        "000-empty-mvp2-session.fixture.json",
        "001-tool-execution-state.fixture.json",
        "002-tool-executor-skeleton.fixture.json",
        "003-tool-ui-state-patch.fixture.json",
        "004-demo-tools.fixture.json",
        "005-demo-destructive-confirmation.fixture.json",
        "006-thinker-as-composer.fixture.json",
        "007-composer-checks.fixture.json",
        "008-tool-manifest-only.fixture.json",
        "009-progressive-stale-tool-result.fixture.json",
    ]


def test_mvp2_acceptance_scenarios_report_scope_assertion_summaries() -> None:
    result = run_mvp2_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP2_REPLAY_FIXTURE_DIR,
        required_scenario_ids=_scenario_ids_from_spec(),
    )
    scenarios = {scenario.scenario_id: scenario for scenario in result.scenario_results}

    assert scenarios["MVP2-TOOL-MANIFEST-001"].assertion_summary["manifest_tool_names"] == [
        "alarm",
        "flashlight",
        "memo",
        "weather",
        "webSearch",
    ]
    assert scenarios["MVP2-UI-STATE-PATCHED-001"].assertion_summary == {
        "demo_ui_namespaces": ["memo"],
        "tool_ui_patch_count": 1,
        "non_patch_demo_mutation_count": 0,
    }
    assert scenarios["MVP2-WEBSEARCH-UNTRUSTED-EVIDENCE-001"].assertion_summary == {
        "tool_name": "webSearch",
        "trust_level": "UNTRUSTED_WEB_EVIDENCE",
        "source_type": "EXTERNAL_READ_UNTRUSTED",
        "ui_patch_count": 0,
        "evidence_reviewed": True,
    }
    assert scenarios["MVP2-DEMO-DESTRUCTIVE-CONFIRMATION-001"].assertion_summary == {
        "destructive_tool_calls": ["tool_call_mvp2_slice5_alarm_cancel", "tool_call_mvp2_slice5_memo_delete"],
        "accepted_confirmation_count": 2,
        "execution_started_count": 2,
        "demo_ui_namespaces": ["alarm", "memo"],
    }
    assert scenarios["MVP2-STALE-TOOL-RESULT-PROGRESSIVE-001"].assertion_summary == {
        "old_plan_tool_result_event_id": "evt_mvp2_slice8_stale_tool_result_received",
        "current_plan_version": 2,
        "stale_evidence_count": 1,
        "adopted_evidence_count": 0,
        "semantic_commitment_count": 0,
    }
    assert scenarios["MVP2-COMPOSER-SPOKEN-PLAN-001"].assertion_summary == {
        "spoken_plan_count": 2,
        "checked_plan_count": 0,
        "playback_count": 0,
        "output_modes": ["mock"],
    }
    assert scenarios["MVP2-COMMITMENT-COVERAGE-001"].assertion_summary["coverage_pass_event_id"] == (
        "evt_mvp2_slice7_coverage_passed"
    )
    assert scenarios["MVP2-PROGRESS-TRUTHFULNESS-001"].assertion_summary["truthfulness_pass_event_id"] == (
        "evt_mvp2_slice7_truthfulness_passed"
    )


def test_mvp2_acceptance_rejects_missing_required_scenario_mapping() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["scenarios"] = [
        scenario
        for scenario in manifest["scenarios"]
        if scenario["scenario_id"] != "MVP2-WEBSEARCH-UNTRUSTED-EVIDENCE-001"
    ]

    with pytest.raises(MVP2AcceptanceError, match="Missing scenario entries"):
        run_mvp2_acceptance_manifest(
            manifest,
            fixture_dir=MVP2_REPLAY_FIXTURE_DIR,
            required_scenario_ids=_scenario_ids_from_spec(),
        )


def test_mvp2_acceptance_rejects_scenario_fixture_that_skips_fixture_checks() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["fixture_checks"] = [
        check
        for check in manifest["fixture_checks"]
        if check["fixture"] != "004-demo-tools.fixture.json"
    ]

    with pytest.raises(MVP2AcceptanceError, match="fixture_checks"):
        run_mvp2_acceptance_manifest(
            manifest,
            fixture_dir=MVP2_REPLAY_FIXTURE_DIR,
            required_scenario_ids=_scenario_ids_from_spec(),
        )


@pytest.mark.parametrize("event_name", ["TOOL_EXECUTION_STARTED", "TOOL_RESULT_RECEIVED"])
def test_mvp2_acceptance_rejects_tool_lifecycle_events_not_owned_by_tool_executor(event_name: str) -> None:
    fixture = load_json_fixture(MVP2_REPLAY_FIXTURE_DIR / "004-demo-tools.fixture.json")
    events = deepcopy(fixture["events"])
    tool_event = next(event for event in events if event["event_name"] == event_name)
    tool_event["source_module"] = "slowtask_runtime"

    with pytest.raises(MVP2AcceptanceError, match="Tool Executor owned"):
        assert_fixture_has_no_forbidden_mvp2_scope(events)


def test_mvp2_acceptance_rejects_manifest_that_weakens_replay_scope_gates() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["required_replay_properties"] = [
        prop
        for prop in manifest["required_replay_properties"]
        if prop != "deterministic_replay_does_not_rerun_models_tools_network_clock_or_random"
    ]

    with pytest.raises(MVP2AcceptanceError, match="required_replay_properties"):
        run_mvp2_acceptance_manifest(
            manifest,
            fixture_dir=MVP2_REPLAY_FIXTURE_DIR,
            required_scenario_ids=_scenario_ids_from_spec(),
        )


def test_mvp2_acceptance_rejects_unsafe_declared_side_effect_class() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    memo = next(tool for tool in manifest["initial_tool_scope"] if tool["tool_name"] == "memo")
    memo["allowed_side_effect_classes"].append("EXTERNAL_WRITE")

    with pytest.raises(MVP2AcceptanceError, match="allowed_side_effect_classes"):
        run_mvp2_acceptance_manifest(
            manifest,
            fixture_dir=MVP2_REPLAY_FIXTURE_DIR,
            required_scenario_ids=_scenario_ids_from_spec(),
        )


def test_mvp2_acceptance_rejects_repo_unsafe_fixture_content() -> None:
    fixture = load_json_fixture(MVP2_REPLAY_FIXTURE_DIR / "004-demo-tools.fixture.json")
    fixture = deepcopy(fixture)
    fixture["events"][-1]["payload"] = {"raw_audio_ref": "audio/raw/session.wav"}

    with pytest.raises(MVP2AcceptanceError, match="repo-unsafe"):
        assert_mvp2_fixture_is_repo_safe(fixture)


def test_mvp2_acceptance_rejects_raw_artifact_markers_in_allowed_metadata_keys() -> None:
    fixture = load_json_fixture(MVP2_REPLAY_FIXTURE_DIR / "004-demo-tools.fixture.json")
    fixture = deepcopy(fixture)
    authorized = next(
        event
        for event in fixture["events"]
        if event["event_id"] == "evt_mvp2_slice4_weather_execution_authorized"
    )
    authorized["authorization_basis"] = "audio/raw/session.wav"

    with pytest.raises(MVP2AcceptanceError, match="repo-unsafe"):
        assert_mvp2_fixture_is_repo_safe(fixture)


def test_mvp2_acceptance_allows_optional_weather_display_ui_patch(tmp_path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    for fixture_path in MVP2_REPLAY_FIXTURE_DIR.glob("*.fixture.json"):
        shutil.copy(fixture_path, tmp_path / fixture_path.name)
    weather_fixture_path = tmp_path / "004-demo-tools.fixture.json"
    fixture = load_json_fixture(weather_fixture_path)
    _insert_weather_display_patch(fixture)
    weather_fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    result = run_mvp2_acceptance_manifest(
        manifest,
        fixture_dir=tmp_path,
        required_scenario_ids=_scenario_ids_from_spec(),
    )

    weather = next(
        scenario
        for scenario in result.scenario_results
        if scenario.scenario_id == "MVP2-WEATHER-READ-ONLY-001"
    )
    assert weather.assertion_summary["ui_patch_count"] == 1


def _scenario_ids_from_spec() -> list[str]:
    text = SCENARIO_SPEC.read_text(encoding="utf-8")
    scenario_ids = re.findall(r"^## Scenario (MVP2-[A-Z0-9-]+)$", text, flags=re.MULTILINE)
    assert scenario_ids, "MVP-2 acceptance scenario spec must declare required scenario ids"
    return scenario_ids


def _insert_weather_display_patch(fixture: dict[str, object]) -> None:
    events = fixture["events"]
    manifest = _event_by_id(events, "evt_mvp2_slice4_weather_manifest_loaded")
    progress = _event_by_id(events, "evt_mvp2_slice4_weather_progress_updated")
    result = _event_by_id(events, "evt_mvp2_slice4_weather_result_received")
    manifest["ui_patch_capable"] = True

    insert_index = events.index(result)
    insert_event_seq = int(result["event_seq"])
    insert_task_event_seq = int(result["task_event_seq"])
    for event in events[insert_index:]:
        event["event_seq"] = int(event["event_seq"]) + 1
        event["created_monotonic_ms"] = int(event["created_monotonic_ms"]) + 1
        event["created_wall_clock_ms"] = int(event["created_wall_clock_ms"]) + 1
        if event.get("task_id") == "task_mvp2_slice4" and "task_event_seq" in event:
            event["task_event_seq"] = int(event["task_event_seq"]) + 1

    weather_patch = {
        "event_name": "TOOL_UI_STATE_PATCHED",
        "event_id": "evt_mvp2_slice4_weather_ui_state_patched",
        "event_seq": insert_event_seq,
        "event_schema_version": "1.0",
        "session_id": progress["session_id"],
        "conversation_id": progress["conversation_id"],
        "source_module": "tool_executor",
        "created_monotonic_ms": int(progress["created_monotonic_ms"]) + 1,
        "created_wall_clock_ms": int(progress["created_wall_clock_ms"]) + 1,
        "caused_by_event_id": progress["event_id"],
        "trace_redaction_level": "metadata_only",
        "tool_call_id": "tool_call_mvp2_slice4_weather",
        "task_id": "task_mvp2_slice4",
        "plan_version": 1,
        "task_event_seq": insert_task_event_seq,
        "tool_name": "weather",
        "ui_patch_id": "ui_patch_mvp2_slice4_weather_display",
        "idempotency_key": "idem://synthetic/mvp2/slice4/weather",
        "patch_ref": "patch://synthetic/demo_backend/weather/display/ui_patch_mvp2_slice4_weather_display",
    }
    result["caused_by_event_id"] = weather_patch["event_id"]
    events.insert(insert_index, weather_patch)


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)
