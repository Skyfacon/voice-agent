from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


PLAN_ADVANCE_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "006-plan-advance-replanning.fixture.json"


def test_slice6_plan_advance_fixture_replays_interpretation_and_replanning_state() -> None:
    result = run_replay_fixture(load_json_fixture(PLAN_ADVANCE_FIXTURE))

    event_names = [event["event_name"] for event in result.ordered_events]
    assert event_names[-5:] == [
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "PLANNING_RESTARTED",
        "TASK_REPLANNED",
        "SLOWTASK_STATE_CHANGED",
    ]

    patch = next(event for event in result.ordered_events if event["event_name"] == "USER_PATCH_RECEIVED")
    interpreted = next(event for event in result.ordered_events if event["event_name"] == "USER_PATCH_INTERPRETED")
    advanced = next(event for event in result.ordered_events if event["event_name"] == "PLAN_VERSION_ADVANCED")

    assert interpreted["caused_by_event_id"] == patch["event_id"]
    assert interpreted["patch_id"] == patch["patch_id"]
    assert interpreted["plan_version"] == 1
    assert interpreted["observed_plan_version"] == 1
    assert interpreted["interpreted_against_plan_version"] == 1
    assert interpreted["interpretation_type"] == "constraint_update"
    assert interpreted["materially_changes_task"] is True
    assert interpreted["interpretation_reason"] == "mock_constraint_update_candidate"
    assert interpreted["source_evidence_refs"] == [
        "evidence://synthetic/mvp1/slice6/patch-pack",
        "text://synthetic/mvp1/slice6/patch-redacted",
        "summary://synthetic/mvp1/slice6/thinker/seat-preference",
    ]

    assert advanced["plan_version"] == 2
    assert advanced["from_plan_version"] == 1
    assert advanced["to_plan_version"] == 2
    assert advanced["planning_reason"] == "material_user_patch:constraint_update"
    assert advanced["caused_by_user_patch_event_id"] == patch["event_id"]

    task = result.slowtask_state.tasks["task_mvp1_slice6_active"]
    assert task.current_plan_version == 2
    assert task.lifecycle_state == "PLANNING"
    assert task.current_task_event_seq == 9
    assert task.user_patch_interpretations[0].interpretation_reason == "mock_constraint_update_candidate"
    assert task.plan_advances[0].caused_by_user_patch_event_id == patch["event_id"]
    assert task.progress_events[-1].event_name == "TASK_REPLANNED"
    assert result.result_status == "passed"


def test_replay_rejects_plan_advance_from_non_material_user_patch_interpretation() -> None:
    fixture = load_json_fixture(PLAN_ADVANCE_FIXTURE)
    interpreted = next(event for event in fixture["events"] if event["event_name"] == "USER_PATCH_INTERPRETED")
    interpreted["materially_changes_task"] = False
    interpreted["interpretation_type"] = "irrelevant"
    interpreted["interpretation_reason"] = "mock_irrelevant_candidate"

    with pytest.raises(ReplayValidationError, match="material USER_PATCH_INTERPRETED"):
        run_replay_fixture(deepcopy(fixture))
