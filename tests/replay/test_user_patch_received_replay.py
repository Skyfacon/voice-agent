from __future__ import annotations

from copy import deepcopy

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture

import pytest


ACTIVE_PATCH_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "005-active-patch-evidence.fixture.json"


def test_slice5_active_patch_fixture_replays_evidence_queue_without_task_mutation() -> None:
    result = run_replay_fixture(load_json_fixture(ACTIVE_PATCH_FIXTURE))

    event_names = [event["event_name"] for event in result.ordered_events]
    assert "USER_PATCH_RECEIVED" in event_names
    assert "USER_PATCH_INTERPRETED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names
    assert "TASK_REPLANNED" not in event_names
    assert "PLANNING_RESTARTED" not in event_names

    patch_event = next(event for event in result.ordered_events if event["event_name"] == "USER_PATCH_RECEIVED")
    assert patch_event["caused_by_event_id"] == "evt_mvp1_slice5_patch_router"
    assert patch_event["patch_id"] == "patch_mvp1_slice5_active"
    assert patch_event["task_id"] == "task_mvp1_slice5_active"
    assert patch_event["plan_version"] == 1
    assert patch_event["observed_plan_version"] == 1
    assert patch_event["task_event_seq"] == 5
    assert patch_event["turn_id"] == "turn_mvp1_slice5_patch"
    assert patch_event["utterance_id"] == "utt_mvp1_slice5_patch"
    assert patch_event["evidence_ref"] == "evidence://synthetic/mvp1/slice5/patch-pack"
    assert patch_event["candidate_patch_types"] == ["constraint_update_candidate"]
    assert patch_event["authoritative_evidence_refs"] == [
        "text://synthetic/mvp1/slice5/patch-redacted",
        "asr-frame://synthetic/mvp1/slice5/patch",
    ]
    assert patch_event["non_authoritative_hypothesis_refs"] == [
        "semantic-frame://synthetic/mvp1/slice5/patch",
        "summary://synthetic/mvp1/slice5/thinker/aisle-seat",
    ]

    task = result.slowtask_state.tasks["task_mvp1_slice5_active"]
    assert task.lifecycle_state == "PLANNING"
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == 5
    assert task.initial_goal_ref == "goal://synthetic/mvp1/slice5/initial"
    assert task.constraints_ref is None
    assert task.resolved_arguments_refs == ()
    assert task.confirmation_state.pending_confirmation_id is None
    assert [(patch.patch_id, patch.evidence_ref) for patch in task.user_patch_evidence] == [
        ("patch_mvp1_slice5_active", "evidence://synthetic/mvp1/slice5/patch-pack")
    ]
    assert result.task_focus_state.active_task_id == "task_mvp1_slice5_active"
    assert result.result_status == "passed"


def test_slice5_fixture_preserves_asr_and_thinker_disagreement_as_evidence_not_mutation() -> None:
    result = run_replay_fixture(load_json_fixture(ACTIVE_PATCH_FIXTURE))

    patch_event = next(event for event in result.ordered_events if event["event_name"] == "USER_PATCH_RECEIVED")
    evidence_pack = patch_event["evidence_pack"]

    assert evidence_pack["authoritative_evidence"]["asr_nbest"][0]["text_ref"].endswith("/window-seat")
    assert evidence_pack["non_authoritative_hypothesis"]["semantic_summary_ref"].endswith("/aisle-seat")
    assert evidence_pack["authoritative_evidence"]["provenance"]["asr_nbest"][0]["source"] == "asr"
    assert evidence_pack["non_authoritative_hypothesis"]["provenance"]["semantic_summary_ref"]["source"] == "thinker"
    assert evidence_pack["non_authoritative_hypothesis"]["candidate_patch_types"] == [
        "constraint_update_candidate"
    ]
    assert "goal_ref" not in patch_event
    assert "constraints_ref" not in patch_event
    assert "resolved_arguments_ref" not in patch_event


def test_replay_rejects_user_patch_evidence_sources_not_used_by_router_decision() -> None:
    fixture = load_json_fixture(ACTIVE_PATCH_FIXTURE)
    patch_event = deepcopy(next(event for event in fixture["events"] if event["event_name"] == "USER_PATCH_RECEIVED"))
    patch_event["event_id"] = "evt_mvp1_slice5_user_patch_mismatched_asr"
    patch_event["event_seq"] = 23
    patch_event["evidence_pack"]["authoritative_evidence"]["source_event_ids"] = [
        "evt_mvp1_slice5_patch_text",
        "evt_mvp1_slice5_patch_turn_committed",
        "evt_mvp1_slice5_unrelated_asr",
    ]
    fixture["events"] = [
        event for event in fixture["events"] if event["event_name"] != "USER_PATCH_RECEIVED"
    ] + [patch_event]

    with pytest.raises(ReplayValidationError, match="asr_frame_event_id"):
        run_replay_fixture(fixture)
