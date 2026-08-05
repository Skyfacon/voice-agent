from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass

import pytest

from experiments.qwen_realtime_fast_slow_web.shadow_router_evaluator import (
    ShadowRouterEvaluator,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.router.router import TaskFocusSnapshot
from voice_agent.state.slowtask_state import SlowTaskState
from voice_agent.state.task_focus_state import TaskFocusState


@dataclass(frozen=True)
class Proposal:
    route_decision_hint: str = "FAST_ONLY"
    task_focus_hint: str = "FOREGROUND_CHAT"
    foreground_act: str = "ANSWER"
    risk_class: str = "LOW"
    risk_tags: tuple[str, ...] = ("none",)
    confidence: float = 0.95
    task_like: bool = False
    complexity_hint: str = "LOW"
    evidence_uncertainty: str = "LOW"
    reply_candidate_text: str | None = None


def evaluate(
    proposal: Proposal,
    *,
    task_focus_snapshot: TaskFocusSnapshot | None = None,
):
    return ShadowRouterEvaluator(session_ref="session-safe").evaluate(
        proposal=proposal,
        turn_id="turn-safe-1",
        utterance_id="utterance-safe-1",
        audio_span_id="audio-span-safe-1",
        asr_frame_ref="asr-safe-1",
        task_focus_snapshot=task_focus_snapshot or TaskFocusSnapshot(),
    )


def test_isolated_router_reports_route_focus_and_foreground_agreement() -> None:
    result = evaluate(Proposal())

    assert result.local_router_decision == "FAST_ONLY"
    assert result.local_task_focus == "FOREGROUND_CHAT"
    assert result.local_foreground_act == "ANSWER"
    assert result.route_agreement is True
    assert result.task_focus_agreement is True
    assert result.foreground_act_agreement is True
    assert result.agreement == "yes"
    assert result.evaluation_latency_ms >= 0
    assert result.isolated_event_count >= 6


def test_isolated_router_preserves_qwen_hint_as_proposal_and_reports_mismatch() -> None:
    result = evaluate(
        Proposal(
            route_decision_hint="FAST_ONLY",
            task_focus_hint="NEW_TASK_CANDIDATE",
            foreground_act="ANSWER",
            task_like=True,
            complexity_hint="HIGH",
        )
    )

    assert result.local_router_decision == "SPAWN_SLOW_TASK"
    assert result.local_task_focus == "NEW_TASK_CANDIDATE"
    assert result.local_foreground_act == "ACK_SLOW"
    assert result.route_agreement is False
    assert result.task_focus_agreement is True
    assert result.foreground_act_agreement is False
    assert result.agreement == "no"


def test_overall_agreement_includes_foreground_act() -> None:
    result = evaluate(
        Proposal(
            route_decision_hint="SPAWN_SLOW_TASK",
            task_focus_hint="NEW_TASK_CANDIDATE",
            foreground_act="CLARIFY",
            task_like=True,
            complexity_hint="MEDIUM",
        )
    )

    assert result.route_agreement is True
    assert result.task_focus_agreement is True
    assert result.foreground_act_agreement is False
    assert result.local_foreground_act == "ACK_SLOW"
    assert result.agreement == "no"


def test_active_task_snapshot_can_yield_patch_without_mutating_snapshot() -> None:
    snapshot = TaskFocusSnapshot(
        active_task_id="task_qfs_1",
        lifecycle_phase="PLANNING",
        current_plan_version=3,
        pending_confirmation_scope="TASK_CANCEL",
    )

    result = evaluate(
        Proposal(
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            task_focus_hint="CANCEL_OR_PAUSE_CANDIDATE",
            foreground_act="ACK_PATCH",
            task_like=True,
            complexity_hint="MEDIUM",
        ),
        task_focus_snapshot=snapshot,
    )

    assert result.local_router_decision == "PATCH_ACTIVE_SLOW_TASK"
    assert result.local_task_focus == "CANCEL_OR_PAUSE_CANDIDATE"
    assert result.local_foreground_act == "ACK_PATCH"
    assert result.agreement == "yes"
    assert snapshot == TaskFocusSnapshot(
        active_task_id="task_qfs_1",
        lifecycle_phase="PLANNING",
        current_plan_version=3,
        pending_confirmation_scope="TASK_CANCEL",
    )


def test_impossible_active_task_focus_fails_closed_instead_of_forging_context() -> None:
    with pytest.raises(
        ValueError,
        match="ACTIVE_TASK_PATCH requires active non-terminal SlowTask",
    ):
        evaluate(
            Proposal(
                route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
                task_focus_hint="ACTIVE_TASK_PATCH",
                foreground_act="ACK_PATCH",
                task_like=True,
            )
        )


def test_evaluation_does_not_append_to_authoritative_journal_or_states() -> None:
    authoritative_journal = InMemoryEventJournal(
        session_id="authoritative-session",
        conversation_id="authoritative-conversation",
    )
    authoritative_journal.append(
        event_name="SESSION_STARTED",
        event_id="event-authoritative-session-started",
        source_module="test",
        created_monotonic_ms=1,
        created_wall_clock_ms=1,
        trace_redaction_level="metadata_only",
        runtime_config_ref="runtime-config://synthetic/authoritative",
        capability_snapshot_ref="capability://synthetic/authoritative",
    )
    task_focus_state = TaskFocusState(
        active_task_id="task-authoritative",
        foreground_mode="SLOWTASK_ACTIVE",
        default_patch_policy="ACTIVE_TASK_PATCH_ONLY",
        last_focus_decision="ACTIVE_TASK_PATCH",
    )
    slowtask_state = SlowTaskState()
    before_events = authoritative_journal.events()
    before_focus = deepcopy(task_focus_state.to_digest_dict())
    before_slowtask = deepcopy(slowtask_state.to_digest_dict())
    playback_epoch = 7
    gate_invocations = 0

    result = evaluate(Proposal(reply_candidate_text="transient candidate"))

    assert result.local_router_decision == "FAST_ONLY"
    assert authoritative_journal.events() == before_events
    assert task_focus_state.to_digest_dict() == before_focus
    assert slowtask_state.to_digest_dict() == before_slowtask
    assert playback_epoch == 7
    assert gate_invocations == 0


def test_evaluation_metadata_is_bounded_and_excludes_candidate_or_transcript() -> None:
    candidate = "PRIVATE_TRANSIENT_REPLY_CANDIDATE"
    result = evaluate(Proposal(reply_candidate_text=candidate))
    metadata = result.to_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert set(metadata) == {
        "local_router_decision",
        "local_task_focus",
        "local_foreground_act",
        "route_agreement",
        "task_focus_agreement",
        "foreground_act_agreement",
        "agreement",
        "function_done_to_local_router_ms",
        "isolated_event_count",
    }
    assert candidate not in serialized
    for forbidden in (
        "transcript",
        "reply_candidate",
        "function_arguments",
        "provider_payload",
        "raw_audio",
        "authorization",
    ):
        assert forbidden not in serialized.lower()
