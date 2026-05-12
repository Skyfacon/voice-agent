from __future__ import annotations

import importlib
import importlib.util
from typing import Any

import pytest

from voice_agent.runtime.session import start_mvp0_session
from voice_agent.state.slowtask_state import SlowTaskState
from voice_agent.state.task_focus_state import TaskFocusState


def _runtime_class() -> type[Any]:
    assert importlib.util.find_spec("voice_agent.slowtask.mock_runtime") is not None
    module = importlib.import_module("voice_agent.slowtask.mock_runtime")
    return module.MockSlowTaskRuntime


def _orchestrator_class() -> type[Any]:
    assert importlib.util.find_spec("voice_agent.runtime.slowtask_orchestrator") is not None
    module = importlib.import_module("voice_agent.runtime.slowtask_orchestrator")
    return module.MVP1SlowTaskHappyPathOrchestrator


def _spawn_router_decision(journal, *, event_id: str = "evt_slice4_router_spawn") -> dict[str, Any]:
    return journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id=event_id,
        source_module="router",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=1020,
        created_wall_clock_ms=1700000004020,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp1_slice4_spawn",
        utterance_id="utt_mvp1_slice4_spawn",
        router_decision="SPAWN_SLOW_TASK",
        task_focus="NEW_TASK_CANDIDATE",
        confidence=0.91,
        evidence_uncertainty="low",
        turn_committed_event_id="evt_mvp1_slice4_turn_committed",
        thinker_frame_event_id="evt_mvp1_slice4_thinker_spawn",
    )


def _started_journal():
    startup = start_mvp0_session(
        session_id="sess_mvp1_slice4_runtime",
        conversation_id="conv_mvp1_slice4_runtime",
        runtime_config_ref="config://synthetic/mvp1/default",
        created_monotonic_ms=1000,
        created_wall_clock_ms=1700000004000,
    )
    return startup.journal


def _run_happy_path() -> tuple[list[dict[str, Any]], Any]:
    journal = _started_journal()
    router_event = _spawn_router_decision(journal)

    result = _orchestrator_class()(journal).run_spawn_planning_completed(
        router_decision_event=router_event,
        task_id="task_mvp1_slice4_happy",
        initial_goal_ref="goal://synthetic/mvp1/slice4/happy",
        source_evidence_refs=("evidence://synthetic/mvp1/slice4/router-spawn",),
        evidence_refs=("evidence://synthetic/mvp1/slice4/router-spawn",),
        resolved_arguments_ref="args://synthetic/mvp1/slice4/resolved",
        provenance_ref="provenance://synthetic/mvp1/slice4/arguments",
        field_provenance_refs=("provenance://synthetic/mvp1/slice4/field/goal",),
        commitment_id="commitment_mvp1_slice4_happy",
        commitment_ref="commitment://synthetic/mvp1/slice4/happy",
        event_id_prefix="evt_mvp1_slice4_runtime",
        created_monotonic_ms=1030,
        created_wall_clock_ms=1700000004030,
    )
    return journal.events(), result


def test_mock_slowtask_runtime_does_not_emit_router_owned_focus_updates() -> None:
    journal = _started_journal()
    router_event = _spawn_router_decision(journal)

    result = _runtime_class()(journal).run_spawn_planning_completed(
        router_decision_event=router_event,
        task_id="task_mvp1_slice4_runtime_only",
        initial_goal_ref="goal://synthetic/mvp1/slice4/runtime-only",
        source_evidence_refs=("evidence://synthetic/mvp1/slice4/router-spawn",),
        evidence_refs=("evidence://synthetic/mvp1/slice4/router-spawn",),
        resolved_arguments_ref="args://synthetic/mvp1/slice4/runtime-only",
        provenance_ref="provenance://synthetic/mvp1/slice4/runtime-only",
        field_provenance_refs=("provenance://synthetic/mvp1/slice4/field/runtime-only",),
        commitment_id="commitment_mvp1_slice4_runtime_only",
        commitment_ref="commitment://synthetic/mvp1/slice4/runtime-only",
        event_id_prefix="evt_mvp1_slice4_runtime_only",
        created_monotonic_ms=1030,
        created_wall_clock_ms=1700000004030,
    )

    produced_event_names = [event["event_name"] for event in result.produced_events]
    assert "TASK_FOCUS_STATE_UPDATED" not in produced_event_names
    assert {event["source_module"] for event in result.produced_events} == {"slowtask_runtime"}


def test_mock_slowtask_runtime_emits_slice4_happy_path_event_sequence() -> None:
    events, result = _run_happy_path()
    produced = events[2:]

    assert [event["event_name"] for event in produced] == [
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
    assert result.task_id == "task_mvp1_slice4_happy"
    assert result.plan_version == 1

    active_focus = produced[3]
    cleanup_focus = produced[-1]
    assert active_focus["source_module"] == "router"
    assert active_focus["active_task_id"] == "task_mvp1_slice4_happy"
    assert cleanup_focus["source_module"] == "router"
    assert cleanup_focus["active_task_id"] is None


def test_mock_slowtask_runtime_binds_current_plan_semantic_commitment_and_reduces_state() -> None:
    events, _ = _run_happy_path()
    slowtask_state = SlowTaskState()
    task_focus_state = TaskFocusState()

    for event in events:
        slowtask_state.reduce_event(event)
        task_focus_state.reduce_event(event)

    task = slowtask_state.tasks["task_mvp1_slice4_happy"]
    assert task.lifecycle_state == "COMPLETED"
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == 10
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice4/resolved",)
    assert task.argument_provenance_refs == (
        "provenance://synthetic/mvp1/slice4/arguments",
        "provenance://synthetic/mvp1/slice4/field/goal",
    )
    assert [commitment.commitment_id for commitment in task.semantic_commitments] == [
        "commitment_mvp1_slice4_happy"
    ]

    commitment_event = next(
        event for event in events if event["event_name"] == "SEMANTIC_COMMITMENT_EMITTED"
    )
    assert commitment_event["task_id"] == "task_mvp1_slice4_happy"
    assert commitment_event["plan_version"] == task.current_plan_version
    assert commitment_event["task_event_seq"] == 9
    assert commitment_event["commitment_ref"] == "commitment://synthetic/mvp1/slice4/happy"
    assert task_focus_state.active_task_id is None


def test_mock_slowtask_runtime_rejects_non_spawn_router_decision() -> None:
    journal = _started_journal()
    router_event = _spawn_router_decision(journal, event_id="evt_slice4_router_fast_only")
    router_event["router_decision"] = "FAST_ONLY"

    with pytest.raises(ValueError, match="SPAWN_SLOW_TASK"):
        _runtime_class()(journal).run_spawn_planning_completed(
            router_decision_event=router_event,
            task_id="task_mvp1_slice4_rejected",
            initial_goal_ref="goal://synthetic/mvp1/slice4/rejected",
            source_evidence_refs=("evidence://synthetic/mvp1/slice4/rejected",),
            evidence_refs=("evidence://synthetic/mvp1/slice4/rejected",),
            commitment_id="commitment_mvp1_slice4_rejected",
            event_id_prefix="evt_mvp1_slice4_rejected",
            created_monotonic_ms=1030,
            created_wall_clock_ms=1700000004030,
        )
