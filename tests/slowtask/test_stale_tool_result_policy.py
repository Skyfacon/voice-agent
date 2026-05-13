from __future__ import annotations

from typing import Any

from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime

from tests.slowtask.test_evidence_review_mvp1 import _active_planning_journal, _event_names, _reduce


FORBIDDEN_NO_ADOPTION_ADVANCEMENT_EVENTS = {
    "STALE_EVIDENCE_ADOPTED",
    "ARGUMENTS_RESOLVED",
    "FINALIZING",
    "SEMANTIC_COMMITMENT_EMITTED",
}
FORBIDDEN_MVP2_TOOL_EVENTS = {
    "TOOL_EXECUTION_STARTED",
    "TOOL_PROGRESS_UPDATED",
    "TOOL_UI_STATE_PATCHED",
}


def test_old_plan_tool_result_is_recorded_stale_without_current_plan_advancement() -> None:
    journal, stale = _journal_with_recorded_stale_result("task_mvp1_slice8_no_adoption")

    event_names = _event_names(stale.produced_events)
    assert [event["event_name"] for event in stale.produced_events] == [
        "TOOL_RESULT_RECEIVED",
        "TOOL_RESULT_MARKED_STALE",
        "STALE_EVIDENCE_RECORDED",
    ]
    assert event_names.isdisjoint(FORBIDDEN_NO_ADOPTION_ADVANCEMENT_EVENTS)
    assert event_names.isdisjoint(FORBIDDEN_MVP2_TOOL_EVENTS)

    late_result, marked, recorded = stale.produced_events
    assert late_result["task_id"] == "task_mvp1_slice8_no_adoption"
    assert late_result["plan_version"] == 1
    assert late_result["task_event_seq"] == 11
    assert late_result["tool_call_id"] == "tool_call_task_mvp1_slice8_no_adoption"

    assert marked["caused_by_event_id"] == late_result["event_id"]
    assert marked["task_id"] == late_result["task_id"]
    assert marked["plan_version"] == 2
    assert marked["task_event_seq"] == 12
    assert marked["tool_call_id"] == late_result["tool_call_id"]
    assert marked["result_plan_version"] == 1
    assert marked["current_plan_version"] == 2
    assert marked["stale_reason"] == "old_plan_result_after_plan_advance"

    assert recorded["caused_by_event_id"] == marked["event_id"]
    assert recorded["task_id"] == late_result["task_id"]
    assert recorded["plan_version"] == 2
    assert recorded["task_event_seq"] == 13
    assert recorded["stale_evidence_ref"] == (
        "stale-evidence://synthetic/mvp1/slice8/task_mvp1_slice8_no_adoption/old-tool-result"
    )
    assert recorded["source_tool_result_event_id"] == late_result["event_id"]

    task = _reduce(journal.events()).tasks["task_mvp1_slice8_no_adoption"]
    assert task.current_plan_version == 2
    assert task.lifecycle_state == "PLANNING"
    assert task.current_task_event_seq == 13
    assert task.stale_evidence_refs == (
        "stale-evidence://synthetic/mvp1/slice8/task_mvp1_slice8_no_adoption/old-tool-result",
    )
    assert task.adopted_evidence == ()
    assert task.resolved_arguments_refs == ()
    assert task.semantic_commitments == ()
    assert task.tool_results[-1].is_current_plan is False


def test_adopted_stale_evidence_can_feed_current_plan_commitment_metadata() -> None:
    journal, stale = _journal_with_recorded_stale_result("task_mvp1_slice8_adopted")
    late_result, _, recorded = stale.produced_events

    adoption = MockSlowTaskRuntime(journal).adopt_stale_evidence_for_commitment(
        task_id="task_mvp1_slice8_adopted",
        plan_version=2,
        caused_by_event_id=str(recorded["event_id"]),
        event_id_prefix="evt_mvp1_slice8_adopted",
        created_monotonic_ms=190,
        created_wall_clock_ms=1700000008190,
        start_task_event_seq=14,
        stale_evidence_ref=str(recorded["stale_evidence_ref"]),
        source_tool_result_event_id=str(late_result["event_id"]),
        adopted_from_plan_version=1,
        adoption_reason="mock_current_plan_reuses_stale_result",
        adopted_scope=("destination", "availability_status"),
        adopted_by_event_id=str(recorded["event_id"]),
        resolved_arguments_ref="args://synthetic/mvp1/slice8/adopted",
        provenance_ref="provenance://synthetic/mvp1/slice8/adopted",
        field_provenance_refs=(
            "provenance://synthetic/mvp1/slice8/adopted/destination",
            "provenance://synthetic/mvp1/slice8/adopted/availability_status",
        ),
        commitment_id="commitment_mvp1_slice8_adopted",
        commitment_ref="commitment://synthetic/mvp1/slice8/adopted",
    )

    assert [event["event_name"] for event in adoption.produced_events] == [
        "STALE_EVIDENCE_ADOPTED",
        "EVIDENCE_REVIEWED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
        "FINALIZING",
        "SEMANTIC_COMMITMENT_EMITTED",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert _event_names(adoption.produced_events).isdisjoint(FORBIDDEN_MVP2_TOOL_EVENTS)

    adopted, reviewed, arguments, provenance, finalizing, commitment, completed = adoption.produced_events
    assert adopted["plan_version"] == 2
    assert adopted["stale_evidence_ref"] == recorded["stale_evidence_ref"]
    assert adopted["source_tool_result_event_id"] == late_result["event_id"]
    assert adopted["adopted_from_plan_version"] == 1
    assert adopted["adoption_mode"] == "adopt_or_rebase"
    assert adopted["adoption_reason"] == "mock_current_plan_reuses_stale_result"
    assert adopted["adopted_scope"] == ["destination", "availability_status"]
    assert adopted["adopted_by_event_id"] == recorded["event_id"]

    assert reviewed["caused_by_event_id"] == adopted["event_id"]
    assert reviewed["plan_version"] == 2
    assert reviewed["evidence_refs"] == [recorded["stale_evidence_ref"]]
    assert reviewed["review_result"] == "adopted_stale_evidence_sufficient"
    assert arguments["caused_by_event_id"] == reviewed["event_id"]
    assert provenance["caused_by_event_id"] == arguments["event_id"]
    assert finalizing["source_events"] == [adopted["event_id"], provenance["event_id"]]
    assert commitment["plan_version"] == 2
    assert adopted["event_id"] in commitment["source_events"]
    assert completed["caused_by_event_id"] == commitment["event_id"]
    assert completed["to_state"] == "COMPLETED"

    task = _reduce(journal.events()).tasks["task_mvp1_slice8_adopted"]
    assert task.current_plan_version == 2
    assert task.lifecycle_state == "COMPLETED"
    assert task.stale_evidence_refs == (recorded["stale_evidence_ref"],)
    assert task.adopted_evidence[-1].event_id == adopted["event_id"]
    assert task.adopted_evidence[-1].adopted_scope == ("destination", "availability_status")
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice8/adopted",)
    assert task.semantic_commitments[-1].commitment_id == "commitment_mvp1_slice8_adopted"
    assert adopted["event_id"] in task.semantic_commitments[-1].source_events


def _journal_with_recorded_stale_result(task_id: str) -> tuple[Any, Any]:
    journal, cause = _active_planning_journal(task_id)
    runtime = MockSlowTaskRuntime(journal)
    event_id_prefix = f"evt_{task_id}"

    tool_call = runtime.record_mock_tool_call(
        task_id=task_id,
        plan_version=1,
        caused_by_event_id=str(cause["event_id"]),
        event_id_prefix=event_id_prefix,
        created_monotonic_ms=150,
        created_wall_clock_ms=1700000008150,
        task_event_seq=4,
        tool_call_id=f"tool_call_{task_id}",
        tool_name="mock.synthetic.lookup",
        idempotency_key=f"idem://synthetic/mvp1/slice8/{task_id}/tool-call",
    )

    user_patch = journal.append(
        event_name="USER_PATCH_RECEIVED",
        event_id=f"{event_id_prefix}_user_patch_received",
        source_module="user_patch_pipeline",
        caused_by_event_id=str(tool_call.produced_events[0]["event_id"]),
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000008160,
        trace_redaction_level="metadata_only",
        patch_id=f"patch_{task_id}_material",
        task_id=task_id,
        plan_version=1,
        task_event_seq=5,
        observed_plan_version=1,
        evidence_ref=f"evidence://synthetic/mvp1/slice8/{task_id}/material-patch",
        candidate_patch_types=["constraint_update_candidate"],
        authoritative_evidence_refs=[f"text://synthetic/mvp1/slice8/{task_id}/patch-redacted"],
        non_authoritative_hypothesis_refs=[f"summary://synthetic/mvp1/slice8/{task_id}/patch"],
    )
    replan = runtime.interpret_user_patch(
        user_patch_event=user_patch,
        event_id_prefix=f"{event_id_prefix}_patch",
        created_monotonic_ms=161,
        created_wall_clock_ms=1700000008161,
        current_lifecycle_state="PLANNING",
        supersedes_event_id=str(tool_call.produced_events[0]["event_id"]),
    )
    assert replan.plan_version == 2

    stale = runtime.record_old_plan_tool_result(
        task_id=task_id,
        current_plan_version=2,
        result_plan_version=1,
        caused_by_event_id=str(replan.produced_events[-1]["event_id"]),
        event_id_prefix=event_id_prefix,
        created_monotonic_ms=180,
        created_wall_clock_ms=1700000008180,
        start_task_event_seq=11,
        tool_call_id=f"tool_call_{task_id}",
        result_status="succeeded",
        result_ref=f"tool-result://synthetic/mvp1/slice8/{task_id}/old-tool-result",
        stale_evidence_ref=f"stale-evidence://synthetic/mvp1/slice8/{task_id}/old-tool-result",
        stale_reason="old_plan_result_after_plan_advance",
    )
    return journal, stale
