from __future__ import annotations

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture


EVIDENCE_REVIEW_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "007-evidence-review-waiting-slot.fixture.json"


def test_slice7_evidence_review_fixture_replays_resolved_arguments_and_waiting_slot() -> None:
    assert EVIDENCE_REVIEW_FIXTURE.is_file()
    result = run_replay_fixture(load_json_fixture(EVIDENCE_REVIEW_FIXTURE))

    event_names = [event["event_name"] for event in result.ordered_events]
    assert event_names[2:6] == [
        "SLOWTASK_CREATED",
        "SLOWTASK_STATE_CHANGED",
        "PLANNING_STARTED",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert result.ordered_events[3]["to_state"] == "CREATED"
    assert result.ordered_events[3]["reason"] == "created_snapshot"
    assert event_names[-10:] == [
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_DETECTED",
        "AMBIGUITY_RESOLVED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
        "EVIDENCE_REVIEWED",
        "INSUFFICIENT_EVIDENCE_FOR_ACTION",
        "CLARIFICATION_REQUESTED",
        "WAITING_FOR_SLOT",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert set(event_names).isdisjoint(
        {
            "TOOL_CALL_STARTED",
            "TOOL_RESULT_RECEIVED",
            "FINALIZING",
            "SEMANTIC_COMMITMENT_EMITTED",
        }
    )

    first_review = next(event for event in result.ordered_events if event["event_id"] == "evt_mvp1_slice7_review_context")
    ambiguity = next(event for event in result.ordered_events if event["event_name"] == "AMBIGUITY_DETECTED")
    resolved = next(event for event in result.ordered_events if event["event_name"] == "AMBIGUITY_RESOLVED")
    arguments = next(event for event in result.ordered_events if event["event_name"] == "ARGUMENTS_RESOLVED")
    provenance = next(event for event in result.ordered_events if event["event_name"] == "ARGUMENT_RESOLUTION_PROVENANCE")
    insufficient = next(event for event in result.ordered_events if event["event_name"] == "INSUFFICIENT_EVIDENCE_FOR_ACTION")
    clarification = next(event for event in result.ordered_events if event["event_name"] == "CLARIFICATION_REQUESTED")
    waiting = next(event for event in result.ordered_events if event["event_name"] == "WAITING_FOR_SLOT")

    assert first_review["review_result"] == "context_resolvable_ambiguity"
    assert ambiguity["caused_by_event_id"] == first_review["event_id"]
    assert resolved["caused_by_event_id"] == ambiguity["event_id"]
    assert arguments["caused_by_event_id"] == resolved["event_id"]
    assert provenance["caused_by_event_id"] == arguments["event_id"]
    assert insufficient["blocking_fields"] == ["date"]
    assert clarification["caused_by_event_id"] == insufficient["event_id"]
    assert waiting["caused_by_event_id"] == clarification["event_id"]

    task = result.slowtask_state.tasks["task_mvp1_slice7_review"]
    assert task.lifecycle_state == "WAITING_FOR_SLOT"
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == 14
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice7/context",)
    assert task.argument_provenance_refs == (
        "provenance://synthetic/mvp1/slice7/context",
        "provenance://synthetic/mvp1/slice7/field/destination",
    )
    assert task.progress_events[-1].event_name == "WAITING_FOR_SLOT"
    assert task.progress_events[-1].refs == ("date",)
    assert result.result_status == "passed"
