from __future__ import annotations

from typing import Any

import pytest

from voice_agent.runtime.session import start_mvp0_session
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.state.slowtask_state import SlowTaskState


def test_mock_runtime_interprets_irrelevant_user_patch_without_advancing_plan() -> None:
    journal, patch_event = _active_planning_task_with_patch(
        candidate_patch_types=("irrelevant_candidate",),
        patch_id="patch_mvp1_slice6_irrelevant",
        evidence_ref="evidence://synthetic/mvp1/slice6/irrelevant",
    )

    result = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=patch_event,
        event_id_prefix="evt_mvp1_slice6_irrelevant",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000006160,
    )

    assert result.plan_version == 1
    assert [event["event_name"] for event in result.produced_events] == ["USER_PATCH_INTERPRETED"]

    interpreted = result.produced_events[0]
    assert interpreted["source_module"] == "slowtask_runtime"
    assert interpreted["caused_by_event_id"] == "evt_mvp1_slice6_user_patch_received"
    assert interpreted["patch_id"] == "patch_mvp1_slice6_irrelevant"
    assert interpreted["task_id"] == "task_mvp1_slice6_active"
    assert interpreted["plan_version"] == 1
    assert interpreted["observed_plan_version"] == 1
    assert interpreted["interpreted_against_plan_version"] == 1
    assert interpreted["task_event_seq"] == 5
    assert interpreted["interpretation_type"] == "irrelevant"
    assert interpreted["materially_changes_task"] is False
    assert interpreted["interpretation_reason"] == "mock_irrelevant_candidate"
    assert interpreted["source_evidence_refs"] == [
        "evidence://synthetic/mvp1/slice6/irrelevant",
        "text://synthetic/mvp1/slice6/patch-redacted",
        "summary://synthetic/mvp1/slice6/patch",
    ]

    slowtask_state = SlowTaskState()
    for event in journal.events():
        slowtask_state.reduce_event(event)

    task = slowtask_state.tasks["task_mvp1_slice6_active"]
    assert task.current_plan_version == 1
    assert task.lifecycle_state == "PLANNING"
    assert task.user_patch_interpretations[0].interpretation_reason == "mock_irrelevant_candidate"
    assert task.user_patch_interpretations[0].source_evidence_refs == (
        "evidence://synthetic/mvp1/slice6/irrelevant",
        "text://synthetic/mvp1/slice6/patch-redacted",
        "summary://synthetic/mvp1/slice6/patch",
    )


def test_mock_runtime_interprets_constraint_patch_as_material_slowtask_decision() -> None:
    journal, patch_event = _active_planning_task_with_patch(
        candidate_patch_types=("constraint_update_candidate", "feedback_candidate"),
        patch_id="patch_mvp1_slice6_constraint",
        evidence_ref="evidence://synthetic/mvp1/slice6/constraint",
    )

    result = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=patch_event,
        event_id_prefix="evt_mvp1_slice6_constraint",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000006160,
    )

    interpreted = result.produced_events[0]
    assert interpreted["event_name"] == "USER_PATCH_INTERPRETED"
    assert interpreted["interpretation_type"] == "constraint_update"
    assert interpreted["materially_changes_task"] is True
    assert interpreted["interpretation_reason"] == "mock_constraint_update_candidate"
    assert interpreted["plan_version"] == 1
    assert interpreted["interpreted_against_plan_version"] == 1


@pytest.mark.parametrize(
    "candidate_patch_type",
    ["cancel_candidate", "confirmation_candidate", "switch_task_candidate"],
)
def test_slice6_runtime_rejects_control_patch_candidates_instead_of_recording_noop_interpretation(
    candidate_patch_type: str,
) -> None:
    journal, patch_event = _active_planning_task_with_patch(
        candidate_patch_types=(candidate_patch_type,),
        patch_id=f"patch_mvp1_slice6_{candidate_patch_type}",
        evidence_ref=f"evidence://synthetic/mvp1/slice6/{candidate_patch_type}",
    )
    event_count_before = len(journal.events())

    with pytest.raises(ValueError, match="control UserPatch candidate"):
        MockSlowTaskRuntime(journal).interpret_user_patch(
            user_patch_event=patch_event,
            event_id_prefix=f"evt_mvp1_slice6_{candidate_patch_type}",
            created_monotonic_ms=160,
            created_wall_clock_ms=1700000006160,
        )

    assert journal.events()[event_count_before:] == []


def _active_planning_task_with_patch(
    *,
    candidate_patch_types: tuple[str, ...],
    patch_id: str,
    evidence_ref: str,
) -> tuple[Any, dict[str, Any]]:
    startup = start_mvp0_session(
        session_id="sess_mvp1_slice6_runtime",
        conversation_id="conv_mvp1_slice6_runtime",
        runtime_config_ref="config://synthetic/mvp1/default",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000006100,
    )
    journal = startup.journal

    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp1_slice6_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=120,
        created_wall_clock_ms=1700000006120,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice6_active",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp1/slice6/initial",
        source_evidence_refs=["evidence://synthetic/mvp1/slice6/spawn"],
    )
    planning_started = journal.append(
        event_name="PLANNING_STARTED",
        event_id="evt_mvp1_slice6_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=122,
        created_wall_clock_ms=1700000006122,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice6_active",
        plan_version=1,
        task_event_seq=2,
        planning_reason="initial_goal_accepted",
    )
    state_planning = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp1_slice6_state_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning_started["event_id"]),
        created_monotonic_ms=123,
        created_wall_clock_ms=1700000006123,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice6_active",
        plan_version=1,
        task_event_seq=3,
        from_state="CREATED",
        to_state="PLANNING",
        reason="initial_planning_started",
    )
    router_event = journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id="evt_mvp1_slice6_patch_router",
        source_module="router",
        caused_by_event_id=str(state_planning["event_id"]),
        created_monotonic_ms=146,
        created_wall_clock_ms=1700000006146,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp1_slice6_patch",
        utterance_id="utt_mvp1_slice6_patch",
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="ACTIVE_TASK_PATCH",
        active_task_id="task_mvp1_slice6_active",
        confidence=0.82,
    )
    patch_event = journal.append(
        event_name="USER_PATCH_RECEIVED",
        event_id="evt_mvp1_slice6_user_patch_received",
        source_module="user_patch_pipeline",
        caused_by_event_id=str(router_event["event_id"]),
        created_monotonic_ms=150,
        created_wall_clock_ms=1700000006150,
        trace_redaction_level="redacted_fixture",
        patch_id=patch_id,
        task_id="task_mvp1_slice6_active",
        plan_version=1,
        observed_plan_version=1,
        task_event_seq=4,
        turn_id="turn_mvp1_slice6_patch",
        utterance_id="utt_mvp1_slice6_patch",
        evidence_ref=evidence_ref,
        authoritative_evidence_refs=["text://synthetic/mvp1/slice6/patch-redacted"],
        non_authoritative_hypothesis_refs=["summary://synthetic/mvp1/slice6/patch"],
        candidate_patch_types=list(candidate_patch_types),
    )
    return journal, patch_event
