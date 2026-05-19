from __future__ import annotations

from typing import Any

import pytest

from voice_agent.access.text_ingress import receive_text_input
from voice_agent.interaction.controller import InteractionController
from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.state.slowtask_state import SlowTaskState
from voice_agent.understanding.mock_asr import emit_mock_asr_frame
from voice_agent.understanding.mock_thinker import emit_mock_thinker_frame
from voice_agent.user_patch.evidence_pack import (
    UserPatchEvidencePackRuntime,
    construct_user_patch_evidence_pack,
)


def test_construct_user_patch_evidence_pack_preserves_disagreeing_sources_as_provenance() -> None:
    _, events = _active_task_patch_decision()
    pack = construct_user_patch_evidence_pack(
        router_decision_event=events["patch_router"],
        turn_committed_event=events["patch_turn_committed"],
        text_input_event=events["patch_text_input"],
        asr_frame_event=events["patch_asr"],
        thinker_frame_event=events["patch_thinker"],
        evidence_ref="evidence://synthetic/mvp1/slice5/patch-pack",
        asr_nbest=[
            {
                "text_ref": "text://synthetic/mvp1/slice5/asr/window-seat",
                "confidence": 0.64,
                "source_event_id": "evt_mvp1_slice5_patch_asr",
            }
        ],
        transcript_hint_ref="text://synthetic/mvp1/slice5/asr/top-hint",
        semantic_summary_ref="summary://synthetic/mvp1/slice5/thinker/aisle-seat",
        audio_summary_ref="audio-summary://synthetic/mvp1/slice5/thinker/calm-correction",
        candidate_patch_types=["constraint_update_candidate", "feedback_candidate"],
        patch_hint="seat_preference_update_candidate",
    )

    assert pack.evidence_ref == "evidence://synthetic/mvp1/slice5/patch-pack"
    assert pack.authoritative_evidence["text_ref"] == "text://synthetic/mvp1/slice5/patch-redacted"
    assert pack.authoritative_evidence["redacted_text"] == "[synthetic mvp1 slice5 patch]"
    assert pack.authoritative_evidence["source_event_ids"] == [
        "evt_mvp1_slice5_patch_text",
        "evt_turn_mvp1_slice5_patch_ingress_committed",
        "evt_mvp1_slice5_patch_asr",
    ]
    assert pack.authoritative_evidence["asr_nbest"][0]["text_ref"].endswith("/window-seat")
    assert pack.authoritative_evidence["provenance"]["asr_nbest"][0] == {
        "source": "asr",
        "source_event_id": "evt_mvp1_slice5_patch_asr",
        "evidence_ref": "asr-frame://synthetic/mvp1/slice5/patch",
        "confidence": 0.64,
    }
    assert pack.non_authoritative_hypothesis["semantic_summary_ref"].endswith("/aisle-seat")
    assert pack.non_authoritative_hypothesis["candidate_patch_types"] == [
        "constraint_update_candidate",
        "feedback_candidate",
    ]
    assert pack.non_authoritative_hypothesis["provenance"]["semantic_summary_ref"] == {
        "source": "thinker",
        "source_event_id": "evt_mvp1_slice5_patch_thinker",
        "evidence_ref": "semantic-frame://synthetic/mvp1/slice5/patch",
    }
    assert "resolved_arguments_ref" not in pack.non_authoritative_hypothesis
    assert "constraints_ref" not in pack.non_authoritative_hypothesis
    assert "goal_ref" not in pack.non_authoritative_hypothesis


def test_user_patch_runtime_appends_received_event_with_pre_advance_bindings_only() -> None:
    journal, events = _active_task_patch_decision()
    slowtask_state = SlowTaskState()
    for event in journal.events():
        slowtask_state.reduce_event(event)

    task = slowtask_state.tasks["task_mvp1_slice5_active"]
    before_semantics = (
        task.current_plan_version,
        task.initial_goal_ref,
        task.constraints_ref,
        task.resolved_arguments_refs,
        task.confirmation_state,
        task.lifecycle_state,
    )

    result = UserPatchEvidencePackRuntime(journal).receive_patch_from_router_decision(
        router_decision_event=events["patch_router"],
        turn_committed_event=events["patch_turn_committed"],
        text_input_event=events["patch_text_input"],
        asr_frame_event=events["patch_asr"],
        thinker_frame_event=events["patch_thinker"],
        task_id="task_mvp1_slice5_active",
        current_plan_version=task.current_plan_version,
        next_task_event_seq=task.current_task_event_seq + 1,
        patch_id="patch_mvp1_slice5_active",
        event_id="evt_mvp1_slice5_user_patch_received",
        evidence_ref="evidence://synthetic/mvp1/slice5/patch-pack",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000005160,
        asr_nbest=[
            {
                "text_ref": "text://synthetic/mvp1/slice5/asr/window-seat",
                "confidence": 0.64,
                "source_event_id": "evt_mvp1_slice5_patch_asr",
            }
        ],
        semantic_summary_ref="summary://synthetic/mvp1/slice5/thinker/aisle-seat",
        candidate_patch_types=["constraint_update_candidate"],
    )

    event = result.user_patch_event
    assert event["event_name"] == "USER_PATCH_RECEIVED"
    assert event["source_module"] == "user_patch_pipeline"
    assert event["caused_by_event_id"] == "evt_mvp1_slice5_patch_router"
    assert event["patch_id"] == "patch_mvp1_slice5_active"
    assert event["task_id"] == "task_mvp1_slice5_active"
    assert event["plan_version"] == 1
    assert event["observed_plan_version"] == 1
    assert event["task_event_seq"] == 5
    assert event["turn_id"] == "turn_mvp1_slice5_patch"
    assert event["utterance_id"] == "utt_mvp1_slice5_patch"
    assert event["evidence_ref"] == "evidence://synthetic/mvp1/slice5/patch-pack"
    assert event["candidate_patch_types"] == ["constraint_update_candidate"]
    assert event["authoritative_evidence_refs"] == [
        "text://synthetic/mvp1/slice5/patch-redacted",
        "asr-frame://synthetic/mvp1/slice5/patch",
    ]
    assert event["non_authoritative_hypothesis_refs"] == [
        "semantic-frame://synthetic/mvp1/slice5/patch",
        "summary://synthetic/mvp1/slice5/thinker/aisle-seat",
    ]
    assert "resolved_arguments_ref" not in event
    assert "constraints_ref" not in event
    assert "goal_ref" not in event
    assert "confirmation_id" not in event

    slowtask_state.reduce_event(event)
    task = slowtask_state.tasks["task_mvp1_slice5_active"]
    assert (
        task.current_plan_version,
        task.initial_goal_ref,
        task.constraints_ref,
        task.resolved_arguments_refs,
        task.confirmation_state,
        task.lifecycle_state,
    ) == before_semantics
    assert [patch.patch_id for patch in task.user_patch_evidence] == ["patch_mvp1_slice5_active"]
    assert task.user_patch_evidence[0].evidence_ref == "evidence://synthetic/mvp1/slice5/patch-pack"


def test_user_patch_runtime_rejects_non_patch_router_decisions() -> None:
    journal, events = _active_task_patch_decision()
    non_patch_router = dict(events["patch_router"], router_decision="FAST_ONLY")

    with pytest.raises(ValueError, match="PATCH_ACTIVE_SLOW_TASK"):
        UserPatchEvidencePackRuntime(journal).receive_patch_from_router_decision(
            router_decision_event=non_patch_router,
            turn_committed_event=events["patch_turn_committed"],
            task_id="task_mvp1_slice5_active",
            current_plan_version=1,
            next_task_event_seq=5,
            patch_id="patch_mvp1_slice5_rejected",
            event_id="evt_mvp1_slice5_user_patch_rejected",
            evidence_ref="evidence://synthetic/mvp1/slice5/rejected",
            created_monotonic_ms=160,
            created_wall_clock_ms=1700000005160,
        )


@pytest.mark.parametrize(
    ("event_key", "changed_field", "expected_error"),
    [
        ("patch_turn_committed", "event_id", "turn_committed_event_id"),
        ("patch_asr", "event_id", "asr_frame_event_id"),
        ("patch_thinker", "event_id", "thinker_frame_event_id"),
    ],
)
def test_user_patch_runtime_rejects_evidence_sources_not_used_by_router_decision(
    event_key: str,
    changed_field: str,
    expected_error: str,
) -> None:
    journal, events = _active_task_patch_decision()
    mismatched_events = {name: dict(event) for name, event in events.items()}
    mismatched_events[event_key][changed_field] = f"evt_mvp1_slice5_other_{event_key}"

    with pytest.raises(ValueError, match=expected_error):
        UserPatchEvidencePackRuntime(journal).receive_patch_from_router_decision(
            router_decision_event=mismatched_events["patch_router"],
            turn_committed_event=mismatched_events["patch_turn_committed"],
            text_input_event=mismatched_events["patch_text_input"],
            asr_frame_event=mismatched_events["patch_asr"],
            thinker_frame_event=mismatched_events["patch_thinker"],
            task_id="task_mvp1_slice5_active",
            current_plan_version=1,
            next_task_event_seq=5,
            patch_id="patch_mvp1_slice5_mismatch",
            event_id="evt_mvp1_slice5_user_patch_mismatch",
            evidence_ref="evidence://synthetic/mvp1/slice5/mismatch",
            created_monotonic_ms=160,
            created_wall_clock_ms=1700000005160,
        )


def _active_task_patch_decision() -> tuple[Any, dict[str, dict[str, Any]]]:
    startup = start_mvp0_session(
        session_id="sess_mvp1_slice5_runtime",
        conversation_id="conv_mvp1_slice5_runtime",
        runtime_config_ref="config://synthetic/mvp1/default",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000005100,
    )
    journal = startup.journal

    spawn_text = receive_text_input(
        journal,
        event_id="evt_mvp1_slice5_spawn_text",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000005110,
        input_span_id="input_mvp1_slice5_spawn",
        text_span_id="text_mvp1_slice5_spawn",
        redacted_text="[synthetic mvp1 slice5 spawn]",
        text_ref="text://synthetic/mvp1/slice5/spawn-redacted",
    )
    spawn_turn = InteractionController(journal).commit_text_ingress(
        spawn_text,
        turn_id="turn_mvp1_slice5_spawn",
        utterance_id="utt_mvp1_slice5_spawn",
        created_monotonic_ms=111,
        created_wall_clock_ms=1700000005111,
    )
    spawn_asr = emit_mock_asr_frame(
        journal,
        spawn_turn.turn_committed,
        event_id="evt_mvp1_slice5_spawn_asr",
        created_monotonic_ms=114,
        created_wall_clock_ms=1700000005114,
        asr_frame_ref="asr-frame://synthetic/mvp1/slice5/spawn",
    )
    spawn_thinker = emit_mock_thinker_frame(
        journal,
        spawn_turn.turn_committed,
        event_id="evt_mvp1_slice5_spawn_thinker",
        created_monotonic_ms=115,
        created_wall_clock_ms=1700000005115,
        semantic_frame_ref="semantic-frame://synthetic/mvp1/slice5/spawn",
    )
    spawn_router = MVP1Router(journal).emit_decision(
        turn_committed_event=spawn_turn.turn_committed,
        asr_frame_event=spawn_asr,
        thinker_frame_event={
            **spawn_thinker,
            "task_focus_hint": "NEW_TASK_CANDIDATE",
            "task_like": True,
            "complexity_hint": "complex",
            "focus_confidence": 0.91,
        },
        router_context=RouterContext(),
        event_id="evt_mvp1_slice5_spawn_router",
        task_focus_state_event_id="evt_mvp1_slice5_spawn_focus",
        created_monotonic_ms=116,
        created_wall_clock_ms=1700000005116,
    ).router_decision_event

    created = MockSlowTaskRuntime(journal).create_from_router_spawn(
        router_decision_event=spawn_router,
        task_id="task_mvp1_slice5_active",
        initial_goal_ref="goal://synthetic/mvp1/slice5/initial",
        event_id_prefix="evt_mvp1_slice5_active",
        created_monotonic_ms=120,
        created_wall_clock_ms=1700000005120,
        source_evidence_refs=("evidence://synthetic/mvp1/slice5/spawn",),
    )
    planning_started = journal.append(
        event_name="PLANNING_STARTED",
        event_id="evt_mvp1_slice5_active_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created.produced_events[0]["event_id"]),
        created_monotonic_ms=122,
        created_wall_clock_ms=1700000005122,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice5_active",
        plan_version=1,
        task_event_seq=3,
        planning_reason="initial_goal_accepted",
    )
    journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp1_slice5_active_state_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning_started["event_id"]),
        created_monotonic_ms=123,
        created_wall_clock_ms=1700000005123,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice5_active",
        plan_version=1,
        task_event_seq=4,
        from_state="CREATED",
        to_state="PLANNING",
        reason="initial_planning_started",
    )

    patch_text = receive_text_input(
        journal,
        event_id="evt_mvp1_slice5_patch_text",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=140,
        created_wall_clock_ms=1700000005140,
        input_span_id="input_mvp1_slice5_patch",
        text_span_id="text_mvp1_slice5_patch",
        redacted_text="[synthetic mvp1 slice5 patch]",
        text_ref="text://synthetic/mvp1/slice5/patch-redacted",
    )
    patch_turn = InteractionController(journal).commit_text_ingress(
        patch_text,
        turn_id="turn_mvp1_slice5_patch",
        utterance_id="utt_mvp1_slice5_patch",
        created_monotonic_ms=141,
        created_wall_clock_ms=1700000005141,
    )
    patch_asr = emit_mock_asr_frame(
        journal,
        patch_turn.turn_committed,
        event_id="evt_mvp1_slice5_patch_asr",
        created_monotonic_ms=144,
        created_wall_clock_ms=1700000005144,
        asr_frame_ref="asr-frame://synthetic/mvp1/slice5/patch",
    )
    patch_thinker = emit_mock_thinker_frame(
        journal,
        patch_turn.turn_committed,
        event_id="evt_mvp1_slice5_patch_thinker",
        created_monotonic_ms=145,
        created_wall_clock_ms=1700000005145,
        semantic_frame_ref="semantic-frame://synthetic/mvp1/slice5/patch",
    )
    patch_router = MVP1Router(journal).emit_decision(
        turn_committed_event=patch_turn.turn_committed,
        asr_frame_event={
            **patch_asr,
            "focus_confidence": 0.68,
            "evidence_uncertainty": "medium",
        },
        thinker_frame_event={
            **patch_thinker,
            "task_focus_hint": "ACTIVE_TASK_PATCH",
            "focus_confidence": 0.82,
            "evidence_uncertainty": "medium",
        },
        router_context=RouterContext(
            task_focus_snapshot=TaskFocusSnapshot(
                active_task_id="task_mvp1_slice5_active",
                lifecycle_phase="PLANNING",
                current_plan_version=1,
            )
        ),
        event_id="evt_mvp1_slice5_patch_router",
        task_focus_state_event_id="evt_mvp1_slice5_patch_focus",
        created_monotonic_ms=146,
        created_wall_clock_ms=1700000005146,
    ).router_decision_event

    return journal, {
        "patch_text_input": patch_text,
        "patch_turn_committed": patch_turn.turn_committed,
        "patch_asr": patch_asr,
        "patch_thinker": patch_thinker,
        "patch_router": patch_router,
    }
