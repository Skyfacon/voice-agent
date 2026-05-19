from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


HAPPY_PATH_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "004-spawn-planning-completed.fixture.json"


def _happy_fixture() -> dict[str, Any]:
    assert HAPPY_PATH_FIXTURE.is_file()
    return load_json_fixture(HAPPY_PATH_FIXTURE)


def test_slice4_happy_path_fixture_replays_runtime_produced_state() -> None:
    result = run_replay_fixture(_happy_fixture())

    event_names = [event["event_name"] for event in result.ordered_events]
    router_index = event_names.index("ROUTER_DECISION_EMITTED")
    assert event_names[router_index:] == [
        "ROUTER_DECISION_EMITTED",
        "SLOWTASK_CREATED",
        "SLOWTASK_STATE_CHANGED",
        "TASK_FOCUS_STATE_UPDATED",
        "PLANNING_STARTED",
        "SLOWTASK_STATE_CHANGED",
        "EVIDENCE_REVIEWED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
        "FINALIZING",
        "SEMANTIC_COMMITMENT_EMITTED",
        "SLOWTASK_STATE_CHANGED",
        "TASK_FOCUS_STATE_UPDATED",
    ]

    task = result.slowtask_state.tasks["task_mvp1_slice4_happy"]
    assert task.lifecycle_state == "COMPLETED"
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == 10
    assert task.terminal_outcome == "COMPLETED"
    assert task.semantic_commitments[-1].commitment_id == "commitment_mvp1_slice4_happy"
    assert task.semantic_commitments[-1].plan_version == task.current_plan_version
    assert task.semantic_commitments[-1].task_event_seq == 9
    assert result.task_focus_state.active_task_id is None
    assert result.result_status == "passed"


def test_replay_rejects_active_focus_before_corresponding_slowtask_created() -> None:
    fixture = _happy_fixture()
    router_event = next(event for event in fixture["events"] if event["event_name"] == "ROUTER_DECISION_EMITTED")
    active_focus_event = deepcopy(
        next(
            event
            for event in fixture["events"]
            if event["event_name"] == "TASK_FOCUS_STATE_UPDATED" and event["active_task_id"] is not None
        )
    )
    created_event = deepcopy(next(event for event in fixture["events"] if event["event_name"] == "SLOWTASK_CREATED"))

    active_focus_event["event_seq"] = int(router_event["event_seq"]) + 1
    active_focus_event["created_monotonic_ms"] = int(router_event["created_monotonic_ms"]) + 1
    active_focus_event["created_wall_clock_ms"] = int(router_event["created_wall_clock_ms"]) + 1
    created_event["event_seq"] = int(router_event["event_seq"]) + 2
    created_event["created_monotonic_ms"] = int(router_event["created_monotonic_ms"]) + 2
    created_event["created_wall_clock_ms"] = int(router_event["created_wall_clock_ms"]) + 2

    fixture["events"] = [
        deepcopy(event)
        for event in fixture["events"]
        if int(event["event_seq"]) <= int(router_event["event_seq"])
    ] + [active_focus_event, created_event]

    with pytest.raises(ReplayValidationError, match="active_task_id.*SLOWTASK_CREATED"):
        run_replay_fixture(fixture)


def test_replay_rejects_router_active_task_before_corresponding_slowtask_created() -> None:
    fixture = _happy_fixture()
    router_event = next(event for event in fixture["events"] if event["event_name"] == "ROUTER_DECISION_EMITTED")
    router_event["active_task_id"] = "task_mvp1_slice4_happy"

    with pytest.raises(ReplayValidationError, match="ROUTER_DECISION_EMITTED active_task_id.*SLOWTASK_CREATED"):
        run_replay_fixture(fixture)


def test_slice4_happy_path_fixture_has_no_tool_or_composer_events() -> None:
    emitted = {event["event_name"] for event in _happy_fixture()["events"]}

    assert emitted.isdisjoint(
        {
            "TOOL_CALL_STARTED",
            "TOOL_EXECUTION_STARTED",
            "TOOL_RESULT_RECEIVED",
            "TOOL_UI_STATE_PATCHED",
            "SPOKEN_PLAN_EMITTED",
            "COMMITMENT_COVERAGE_CHECK_PASSED",
            "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
        }
    )
