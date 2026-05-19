from __future__ import annotations

import pytest

from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.state.slowtask_state import SlowTaskState, SlowTaskStateError

from tests.slowtask.test_user_patch_interpretation import _active_planning_task_with_patch


def test_material_user_patch_advances_plan_and_restarts_planning_sequence() -> None:
    journal, patch_event = _active_planning_task_with_patch(
        candidate_patch_types=("constraint_update_candidate",),
        patch_id="patch_mvp1_slice6_material",
        evidence_ref="evidence://synthetic/mvp1/slice6/material",
    )

    result = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=patch_event,
        event_id_prefix="evt_mvp1_slice6_material",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000006160,
    )

    assert result.plan_version == 2
    assert [event["event_name"] for event in result.produced_events] == [
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "PLANNING_RESTARTED",
        "TASK_REPLANNED",
        "SLOWTASK_STATE_CHANGED",
    ]

    interpreted, advanced, restarted, replanned, state_changed = result.produced_events
    assert interpreted["task_event_seq"] == 5
    assert interpreted["plan_version"] == 1

    assert advanced["plan_version"] == 2
    assert advanced["task_event_seq"] == 6
    assert advanced["from_plan_version"] == 1
    assert advanced["to_plan_version"] == 2
    assert advanced["planning_reason"] == "material_user_patch:constraint_update"
    assert advanced["caused_by_event_id"] == interpreted["event_id"]
    assert advanced["caused_by_user_patch_event_id"] == patch_event["event_id"]

    assert restarted["plan_version"] == 2
    assert restarted["task_event_seq"] == 7
    assert restarted["restart_reason"] == "material_user_patch:constraint_update"
    assert restarted["caused_by_event_id"] == advanced["event_id"]

    assert replanned["plan_version"] == 2
    assert replanned["task_event_seq"] == 8
    assert replanned["planning_reason"] == "material_user_patch:constraint_update"
    assert replanned["superseded_plan_version"] == 1
    assert replanned["caused_by_event_id"] == advanced["event_id"]

    assert state_changed["plan_version"] == 2
    assert state_changed["task_event_seq"] == 9
    assert state_changed["from_state"] == "PLANNING"
    assert state_changed["to_state"] == "PLANNING"
    assert state_changed["reason"] == "material_user_patch_replanning"
    assert state_changed["caused_by_event_id"] == replanned["event_id"]

    slowtask_state = SlowTaskState()
    for event in journal.events():
        slowtask_state.reduce_event(event)

    task = slowtask_state.tasks["task_mvp1_slice6_active"]
    assert task.current_plan_version == 2
    assert task.current_task_event_seq == 9
    assert task.lifecycle_state == "PLANNING"
    assert task.plan_advances[0].caused_by_user_patch_event_id == patch_event["event_id"]
    assert task.progress_events[-1].event_name == "TASK_REPLANNED"
    assert task.state_transitions[-1].to_state == "PLANNING"


def test_plan_advance_with_user_patch_cause_requires_material_interpretation() -> None:
    state = _planning_state_with_non_material_interpretation()

    with pytest.raises(SlowTaskStateError, match="material USER_PATCH_INTERPRETED"):
        state.reduce_event(
            _slowtask_event(
                "PLAN_VERSION_ADVANCED",
                event_id="evt_mvp1_slice6_bad_plan_advanced",
                task_event_seq=5,
                plan_version=2,
                from_plan_version=1,
                to_plan_version=2,
                planning_reason="material_user_patch:irrelevant",
                caused_by_user_patch_event_id="evt_mvp1_slice6_non_material_patch_received",
            )
        )

    task = state.tasks["task_mvp1_slice6_non_material"]
    assert task.current_plan_version == 1


def test_material_user_patch_plan_advance_requires_user_patch_cause_id() -> None:
    state = _planning_state_with_non_material_interpretation()

    with pytest.raises(SlowTaskStateError, match="caused_by_user_patch_event_id"):
        state.reduce_event(
            _slowtask_event(
                "PLAN_VERSION_ADVANCED",
                event_id="evt_mvp1_slice6_missing_user_patch_cause",
                task_event_seq=5,
                plan_version=2,
                from_plan_version=1,
                to_plan_version=2,
                planning_reason="material_user_patch:constraint_update",
            )
        )

    task = state.tasks["task_mvp1_slice6_non_material"]
    assert task.current_plan_version == 1


def test_plan_advance_user_patch_cause_must_match_specific_material_interpretation_event() -> None:
    state = _planning_state_with_duplicate_patch_id_interpretations()

    with pytest.raises(SlowTaskStateError, match="material USER_PATCH_INTERPRETED"):
        state.reduce_event(
            _slowtask_event(
                "PLAN_VERSION_ADVANCED",
                event_id="evt_mvp1_slice6_misassociated_plan_advance",
                task_id="task_mvp1_slice6_duplicate_patch",
                task_event_seq=7,
                plan_version=2,
                from_plan_version=1,
                to_plan_version=2,
                planning_reason="material_user_patch:constraint_update",
                caused_by_user_patch_event_id="evt_mvp1_slice6_duplicate_patch_received_second",
            )
        )

    task = state.tasks["task_mvp1_slice6_duplicate_patch"]
    assert task.current_plan_version == 1


def _planning_state_with_non_material_interpretation() -> SlowTaskState:
    state = SlowTaskState()
    state.reduce_event(
        _slowtask_event(
            "SLOWTASK_CREATED",
            event_id="evt_mvp1_slice6_non_material_created",
            task_id="task_mvp1_slice6_non_material",
            task_event_seq=1,
            initial_goal_ref="goal://synthetic/mvp1/slice6/non-material",
        )
    )
    state.reduce_event(
        _slowtask_event(
            "SLOWTASK_STATE_CHANGED",
            event_id="evt_mvp1_slice6_non_material_planning",
            task_id="task_mvp1_slice6_non_material",
            task_event_seq=2,
            from_state="CREATED",
            to_state="PLANNING",
            reason="initial_planning_started",
        )
    )
    state.reduce_event(
        _slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_mvp1_slice6_non_material_patch_received",
            task_id="task_mvp1_slice6_non_material",
            task_event_seq=3,
            patch_id="patch_mvp1_slice6_non_material",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice6/non-material",
        )
    )
    state.reduce_event(
        _slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_mvp1_slice6_non_material_patch_interpreted",
            task_id="task_mvp1_slice6_non_material",
            task_event_seq=4,
            caused_by_event_id="evt_mvp1_slice6_non_material_patch_received",
            patch_id="patch_mvp1_slice6_non_material",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="irrelevant",
            materially_changes_task=False,
            interpretation_reason="mock_irrelevant_candidate",
            source_evidence_refs=["evidence://synthetic/mvp1/slice6/non-material"],
        )
    )
    return state


def _planning_state_with_duplicate_patch_id_interpretations() -> SlowTaskState:
    state = SlowTaskState()
    state.reduce_event(
        _slowtask_event(
            "SLOWTASK_CREATED",
            event_id="evt_mvp1_slice6_duplicate_patch_created",
            task_id="task_mvp1_slice6_duplicate_patch",
            task_event_seq=1,
            initial_goal_ref="goal://synthetic/mvp1/slice6/duplicate-patch",
        )
    )
    state.reduce_event(
        _slowtask_event(
            "SLOWTASK_STATE_CHANGED",
            event_id="evt_mvp1_slice6_duplicate_patch_planning",
            task_id="task_mvp1_slice6_duplicate_patch",
            task_event_seq=2,
            from_state="CREATED",
            to_state="PLANNING",
            reason="initial_planning_started",
        )
    )
    state.reduce_event(
        _slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_mvp1_slice6_duplicate_patch_received_first",
            task_id="task_mvp1_slice6_duplicate_patch",
            task_event_seq=3,
            patch_id="patch_mvp1_slice6_duplicate",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice6/duplicate-first",
        )
    )
    state.reduce_event(
        _slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_mvp1_slice6_duplicate_patch_interpreted_first",
            task_id="task_mvp1_slice6_duplicate_patch",
            task_event_seq=4,
            caused_by_event_id="evt_mvp1_slice6_duplicate_patch_received_first",
            patch_id="patch_mvp1_slice6_duplicate",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="constraint_update",
            materially_changes_task=True,
            interpretation_reason="mock_constraint_update_candidate",
            source_evidence_refs=["evidence://synthetic/mvp1/slice6/duplicate-first"],
        )
    )
    state.reduce_event(
        _slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_mvp1_slice6_duplicate_patch_received_second",
            task_id="task_mvp1_slice6_duplicate_patch",
            task_event_seq=5,
            patch_id="patch_mvp1_slice6_duplicate",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice6/duplicate-second",
        )
    )
    state.reduce_event(
        _slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_mvp1_slice6_duplicate_patch_interpreted_second",
            task_id="task_mvp1_slice6_duplicate_patch",
            task_event_seq=6,
            caused_by_event_id="evt_mvp1_slice6_duplicate_patch_received_second",
            patch_id="patch_mvp1_slice6_duplicate",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="irrelevant",
            materially_changes_task=False,
            interpretation_reason="mock_irrelevant_candidate",
            source_evidence_refs=["evidence://synthetic/mvp1/slice6/duplicate-second"],
        )
    )
    return state


def _slowtask_event(event_name: str, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": event_name,
        "event_id": f"evt_{event_name.lower()}_{overrides.get('task_event_seq', 1)}",
        "task_id": "task_mvp1_slice6_non_material",
        "plan_version": 1,
        "task_event_seq": 1,
    }
    event.update(overrides)
    return event
