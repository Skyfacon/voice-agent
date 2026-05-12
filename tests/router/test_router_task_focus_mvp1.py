from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest

from voice_agent.access.text_ingress import receive_text_input
from voice_agent.interaction.controller import InteractionController
from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.understanding.mock_asr import emit_mock_asr_frame


def _committed_turn_with_mock_frames(
    *,
    suffix: str,
    task_focus_hint: str | None = None,
    task_like: bool = False,
    complexity_hint: str = "simple",
    focus_confidence: float = 0.9,
    evidence_uncertainty: str = "low",
) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    startup = start_mvp0_session(
        session_id=f"sess_mvp1_slice2_{suffix}",
        conversation_id=f"conv_mvp1_slice2_{suffix}",
        runtime_config_ref="config://synthetic/mvp1/default",
        created_monotonic_ms=1000,
        created_wall_clock_ms=1700000001000,
    )
    text_event = receive_text_input(
        startup.journal,
        event_id=f"evt_mvp1_slice2_{suffix}_text_received",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=1010,
        created_wall_clock_ms=1700000001010,
        input_span_id=f"input_mvp1_slice2_{suffix}",
        text_span_id=f"text_mvp1_slice2_{suffix}",
        redacted_text=f"[synthetic mvp1 slice2 {suffix}]",
    )
    commit_result = InteractionController(startup.journal).commit_text_ingress(
        text_event,
        turn_id=f"turn_mvp1_slice2_{suffix}",
        utterance_id=f"utt_mvp1_slice2_{suffix}",
        created_monotonic_ms=1020,
        created_wall_clock_ms=1700000001020,
    )
    asr_event = emit_mock_asr_frame(
        startup.journal,
        commit_result.turn_committed,
        event_id=f"evt_mvp1_slice2_{suffix}_mock_asr",
        created_monotonic_ms=1030,
        created_wall_clock_ms=1700000001030,
        asr_frame_ref=f"asr-frame://synthetic/mvp1/slice2/{suffix}",
    )
    thinker_event = startup.journal.append(
        event_name="MOCK_THINKER_FRAME_EMITTED",
        event_id=f"evt_mvp1_slice2_{suffix}_mock_thinker",
        source_module="mock_thinker_adapter",
        caused_by_event_id=str(commit_result.turn_committed["event_id"]),
        created_monotonic_ms=1031,
        created_wall_clock_ms=1700000001031,
        trace_redaction_level="metadata_only",
        turn_id=str(commit_result.turn_committed["turn_id"]),
        utterance_id=str(commit_result.turn_committed["utterance_id"]),
        input_modality=str(commit_result.turn_committed["input_modality"]),
        semantic_frame_ref=f"semantic-frame://synthetic/mvp1/slice2/{suffix}",
        output_mode="mock",
        task_focus_hint=task_focus_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
        focus_confidence=focus_confidence,
        evidence_uncertainty=evidence_uncertainty,
    )
    return startup, commit_result.turn_committed, asr_event, thinker_event


def _active_snapshot() -> TaskFocusSnapshot:
    return TaskFocusSnapshot(
        active_task_id="task_mvp1_slice2_active_001",
        lifecycle_phase="PLANNING",
        terminal_status=None,
        current_plan_version=3,
        pending_confirmation_scope=None,
    )


def test_task_focus_snapshot_contract_exposes_only_router_public_fields() -> None:
    assert {field.name for field in fields(TaskFocusSnapshot)} == {
        "active_task_id",
        "lifecycle_phase",
        "terminal_status",
        "current_plan_version",
        "pending_confirmation_scope",
    }
    assert _active_snapshot().has_active_non_terminal_task is True

    forbidden_internal_fields = {
        "goal",
        "constraints",
        "resolved_arguments",
        "stale_evidence",
        "authorization_details",
    }
    assert forbidden_internal_fields.isdisjoint({field.name for field in fields(TaskFocusSnapshot)})


def test_no_active_complex_input_spawns_slowtask_decision_without_creating_task() -> None:
    startup, turn_committed, asr_event, thinker_event = _committed_turn_with_mock_frames(
        suffix="spawn",
        task_like=True,
        complexity_hint="complex",
        task_focus_hint="NEW_TASK_CANDIDATE",
        focus_confidence=0.87,
    )

    result = MVP1Router(startup.journal).emit_decision(
        turn_committed_event=turn_committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        event_id="evt_mvp1_slice2_spawn_router_decision",
        task_focus_state_event_id="evt_mvp1_slice2_spawn_focus_state",
        created_monotonic_ms=1040,
        created_wall_clock_ms=1700000001040,
    )

    assert result.router_decision_event["router_decision"] == "SPAWN_SLOW_TASK"
    assert result.router_decision_event["task_focus"] == "NEW_TASK_CANDIDATE"
    assert result.task_focus_state_event["active_task_id"] is None
    assert result.task_focus_state_event["default_patch_policy"] == "NO_ACTIVE_TASK"
    assert result.task_focus_state_event["router_decision_event_id"] == result.router_decision_event["event_id"]
    assert result.task_focus_state_event["last_focus_event_id"] == result.router_decision_event["event_id"]
    assert "task_id" not in result.router_decision_event
    assert "plan_version" not in result.router_decision_event
    assert "SLOWTASK_CREATED" not in {event["event_name"] for event in startup.journal.events()}


@pytest.mark.parametrize(
    "hint,expected_decision,expected_focus",
    [
        ("ACTIVE_TASK_PATCH", "PATCH_ACTIVE_SLOW_TASK", "ACTIVE_TASK_PATCH"),
        ("FOREGROUND_CHAT", "FAST_ONLY", "FOREGROUND_CHAT"),
        ("AMBIGUOUS", "FAST_ONLY", "AMBIGUOUS"),
        ("NEW_TASK_CANDIDATE", "PATCH_ACTIVE_SLOW_TASK", "NEW_TASK_CANDIDATE"),
        ("CANCEL_OR_PAUSE_CANDIDATE", "PATCH_ACTIVE_SLOW_TASK", "CANCEL_OR_PAUSE_CANDIDATE"),
        ("NON_ASSISTANT", "IGNORE", "NON_ASSISTANT"),
    ],
)
def test_active_slowtask_focus_decisions_never_emit_slice3_events(
    hint: str,
    expected_decision: str,
    expected_focus: str,
) -> None:
    startup, turn_committed, asr_event, thinker_event = _committed_turn_with_mock_frames(
        suffix=hint.lower(),
        task_focus_hint=hint,
        focus_confidence=0.76,
        evidence_uncertainty="high" if hint == "AMBIGUOUS" else "low",
    )

    result = MVP1Router(startup.journal).emit_decision(
        turn_committed_event=turn_committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=RouterContext(task_focus_snapshot=_active_snapshot()),
        event_id=f"evt_mvp1_slice2_{hint.lower()}_router_decision",
        task_focus_state_event_id=f"evt_mvp1_slice2_{hint.lower()}_focus_state",
        created_monotonic_ms=1040,
        created_wall_clock_ms=1700000001040,
    )

    assert result.router_decision_event["router_decision"] == expected_decision
    assert result.router_decision_event["task_focus"] == expected_focus
    assert result.task_focus_state_event["active_task_id"] == "task_mvp1_slice2_active_001"
    assert result.task_focus_state_event["last_focus_decision"] == expected_focus
    assert result.task_focus_state_event["last_focus_confidence"] == 0.76

    event_names = {event["event_name"] for event in startup.journal.events()}
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "USER_PATCH_INTERPRETED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names
    assert "SLOWTASK_CANCEL_REQUESTED" not in event_names
    assert "SLOWTASK_CANCELLED" not in event_names
    assert "SLOWTASK_CREATED" not in event_names


def test_unknown_mvp1_focus_hint_is_rejected_instead_of_extending_router_scope() -> None:
    startup, turn_committed, asr_event, thinker_event = _committed_turn_with_mock_frames(
        suffix="unknown_focus",
        task_focus_hint="REWRITE_GOAL",
    )

    with pytest.raises(ValueError, match="task_focus"):
        MVP1Router(startup.journal).emit_decision(
            turn_committed_event=turn_committed,
            asr_frame_event=asr_event,
            thinker_frame_event=thinker_event,
            router_context=RouterContext(task_focus_snapshot=_active_snapshot()),
            event_id="evt_mvp1_slice2_unknown_focus_router_decision",
            task_focus_state_event_id="evt_mvp1_slice2_unknown_focus_focus_state",
            created_monotonic_ms=1040,
            created_wall_clock_ms=1700000001040,
        )


@pytest.mark.parametrize(
    "snapshot",
    [
        TaskFocusSnapshot(),
        TaskFocusSnapshot(
            active_task_id="task_mvp1_slice2_terminal_001",
            lifecycle_phase="COMPLETED",
            terminal_status="COMPLETED",
            current_plan_version=3,
        ),
    ],
)
def test_active_task_patch_hint_is_rejected_without_active_non_terminal_task(
    snapshot: TaskFocusSnapshot,
) -> None:
    startup, turn_committed, asr_event, thinker_event = _committed_turn_with_mock_frames(
        suffix=f"impossible_patch_{snapshot.lifecycle_phase or 'none'}",
        task_focus_hint="ACTIVE_TASK_PATCH",
        focus_confidence=0.9,
    )

    with pytest.raises(ValueError, match="active non-terminal SlowTask"):
        MVP1Router(startup.journal).emit_decision(
            turn_committed_event=turn_committed,
            asr_frame_event=asr_event,
            thinker_frame_event=thinker_event,
            router_context=RouterContext(task_focus_snapshot=snapshot),
            event_id=f"evt_mvp1_slice2_impossible_patch_{snapshot.lifecycle_phase or 'none'}",
            task_focus_state_event_id=f"evt_mvp1_slice2_impossible_patch_focus_{snapshot.lifecycle_phase or 'none'}",
            created_monotonic_ms=1040,
            created_wall_clock_ms=1700000001040,
        )


def test_not_directed_turn_is_ignored_even_when_model_frame_has_task_focus_hint() -> None:
    startup, turn_committed, asr_event, thinker_event = _committed_turn_with_mock_frames(
        suffix="not_directed_with_hint",
        task_focus_hint="ACTIVE_TASK_PATCH",
        focus_confidence=0.94,
    )
    not_directed_turn = dict(turn_committed, directedness="NOT_DIRECTED")

    result = MVP1Router(startup.journal).emit_decision(
        turn_committed_event=not_directed_turn,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=RouterContext(task_focus_snapshot=_active_snapshot()),
        event_id="evt_mvp1_slice2_not_directed_router_decision",
        task_focus_state_event_id="evt_mvp1_slice2_not_directed_focus_state",
        created_monotonic_ms=1040,
        created_wall_clock_ms=1700000001040,
    )

    assert result.router_decision_event["router_decision"] == "IGNORE"
    assert result.router_decision_event["task_focus"] == "NON_ASSISTANT"
    assert "USER_PATCH_RECEIVED" not in {event["event_name"] for event in startup.journal.events()}
