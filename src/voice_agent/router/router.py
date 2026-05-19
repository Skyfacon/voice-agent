from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal


MVP0_ROUTER_DECISIONS = frozenset({"FAST_ONLY", "IGNORE"})
MVP1_ROUTER_DECISIONS = frozenset(
    {
        "FAST_ONLY",
        "SPAWN_SLOW_TASK",
        "PATCH_ACTIVE_SLOW_TASK",
        "IGNORE",
    }
)
MVP0_TASK_FOCUS_BY_DECISION = {
    "FAST_ONLY": "FOREGROUND_CHAT",
    "IGNORE": "NON_ASSISTANT",
}
MVP1_TASK_FOCUS_VALUES = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "FOREGROUND_CHAT",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "NON_ASSISTANT",
        "AMBIGUOUS",
    }
)
MVP1_PATCH_FOCUS_VALUES = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
    }
)
MVP1_ACTIVE_TASK_REQUIRED_FOCUS_VALUES = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "CANCEL_OR_PAUSE_CANDIDATE",
    }
)
TERMINAL_SLOWTASK_PHASES = frozenset({"COMPLETED", "CANCELLED", "FAILED"})


@dataclass(frozen=True)
class TaskFocusSnapshot:
    active_task_id: str | None = None
    lifecycle_phase: str | None = None
    terminal_status: str | None = None
    current_plan_version: int | None = None
    pending_confirmation_scope: str | None = None

    @property
    def has_active_non_terminal_task(self) -> bool:
        if self.active_task_id is None:
            return False
        if self.terminal_status is not None:
            return False
        return self.lifecycle_phase not in TERMINAL_SLOWTASK_PHASES


@dataclass(frozen=True)
class RouterContext:
    task_focus_snapshot: TaskFocusSnapshot = field(default_factory=TaskFocusSnapshot)
    side_conversation_allowed: bool = True
    default_patch_policy: str | None = None
    ambiguous_input_policy: str = "CLARIFY"


@dataclass(frozen=True)
class MVP1RouterDecisionResult:
    router_decision_event: dict[str, Any]
    task_focus_state_event: dict[str, Any]


class MVP1TaskFocusUpdateEmitter:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def emit_update(
        self,
        *,
        router_decision_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        active_task_id: str | None,
        foreground_mode: str,
        default_patch_policy: str,
        side_conversation_allowed: bool = True,
        ambiguous_input_policy: str = "CLARIFY",
    ) -> dict[str, Any]:
        if router_decision_event.get("event_name") != "ROUTER_DECISION_EMITTED":
            raise ValueError("TaskFocus update requires a ROUTER_DECISION_EMITTED event")

        return self._journal.append(
            event_name="TASK_FOCUS_STATE_UPDATED",
            event_id=event_id,
            source_module="router",
            caused_by_event_id=str(router_decision_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            active_task_id=active_task_id,
            foreground_mode=foreground_mode,
            side_conversation_allowed=side_conversation_allowed,
            default_patch_policy=default_patch_policy,
            ambiguous_input_policy=ambiguous_input_policy,
            last_focus_decision=str(router_decision_event.get("task_focus", "NEW_TASK_CANDIDATE")),
            last_focus_confidence=float(router_decision_event.get("confidence", 1.0)),
            router_decision_event_id=str(router_decision_event["event_id"]),
            last_focus_event_id=str(router_decision_event["event_id"]),
        )


class MVP0Router:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def emit_decision(
        self,
        *,
        turn_committed_event: Mapping[str, Any],
        asr_frame_event: Mapping[str, Any],
        thinker_frame_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        router_decision: str = "FAST_ONLY",
        task_focus: str | None = None,
        confidence: float = 1.0,
        evidence_uncertainty: str = "low",
    ) -> dict[str, Any]:
        _validate_turn_committed_event(turn_committed_event)
        _validate_mock_frame(
            asr_frame_event,
            expected_event_name="MOCK_ASR_FRAME_EMITTED",
            turn_committed_event=turn_committed_event,
        )
        _validate_mock_frame(
            thinker_frame_event,
            expected_event_name="MOCK_THINKER_FRAME_EMITTED",
            turn_committed_event=turn_committed_event,
        )
        if router_decision not in MVP0_ROUTER_DECISIONS:
            raise ValueError("MVP0 router_decision must be FAST_ONLY or IGNORE")

        expected_task_focus = MVP0_TASK_FOCUS_BY_DECISION[router_decision]
        resolved_task_focus = task_focus or expected_task_focus
        if resolved_task_focus != expected_task_focus:
            raise ValueError("MVP0 task_focus must match FAST_ONLY/IGNORE skeleton labels")

        return self._journal.append(
            event_name="ROUTER_DECISION_EMITTED",
            event_id=event_id,
            source_module="router",
            caused_by_event_id=str(thinker_frame_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            turn_id=str(turn_committed_event["turn_id"]),
            utterance_id=str(turn_committed_event["utterance_id"]),
            router_decision=router_decision,
            task_focus=resolved_task_focus,
            confidence=confidence,
            evidence_uncertainty=evidence_uncertainty,
            turn_committed_event_id=str(turn_committed_event["event_id"]),
            asr_frame_event_id=str(asr_frame_event["event_id"]),
            thinker_frame_event_id=str(thinker_frame_event["event_id"]),
        )


class MVP1Router:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def emit_decision(
        self,
        *,
        turn_committed_event: Mapping[str, Any],
        asr_frame_event: Mapping[str, Any],
        thinker_frame_event: Mapping[str, Any],
        router_context: RouterContext,
        event_id: str,
        task_focus_state_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> MVP1RouterDecisionResult:
        _validate_turn_committed_event(turn_committed_event)
        _validate_mock_frame(
            asr_frame_event,
            expected_event_name="MOCK_ASR_FRAME_EMITTED",
            turn_committed_event=turn_committed_event,
        )
        _validate_mock_frame(
            thinker_frame_event,
            expected_event_name="MOCK_THINKER_FRAME_EMITTED",
            turn_committed_event=turn_committed_event,
        )

        task_focus = _infer_mvp1_task_focus(
            turn_committed_event=turn_committed_event,
            asr_frame_event=asr_frame_event,
            thinker_frame_event=thinker_frame_event,
            router_context=router_context,
        )
        router_decision = _router_decision_for_focus(
            task_focus=task_focus,
            router_context=router_context,
        )
        confidence = _focus_confidence(asr_frame_event, thinker_frame_event)
        evidence_uncertainty = _evidence_uncertainty(asr_frame_event, thinker_frame_event)
        active_task_id = _active_task_id(router_context.task_focus_snapshot)

        router_fields: dict[str, Any] = {
            "turn_id": str(turn_committed_event["turn_id"]),
            "utterance_id": str(turn_committed_event["utterance_id"]),
            "router_decision": router_decision,
            "task_focus": task_focus,
            "confidence": confidence,
            "evidence_uncertainty": evidence_uncertainty,
            "turn_committed_event_id": str(turn_committed_event["event_id"]),
            "asr_frame_event_id": str(asr_frame_event["event_id"]),
            "thinker_frame_event_id": str(thinker_frame_event["event_id"]),
        }
        if active_task_id is not None:
            router_fields["active_task_id"] = active_task_id

        router_decision_event = self._journal.append(
            event_name="ROUTER_DECISION_EMITTED",
            event_id=event_id,
            source_module="router",
            caused_by_event_id=str(thinker_frame_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            **router_fields,
        )

        task_focus_state_event = self._journal.append(
            event_name="TASK_FOCUS_STATE_UPDATED",
            event_id=task_focus_state_event_id,
            source_module="router",
            caused_by_event_id=str(router_decision_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 1,
            created_wall_clock_ms=created_wall_clock_ms + 1,
            trace_redaction_level="metadata_only",
            active_task_id=active_task_id,
            foreground_mode=_foreground_mode(
                router_decision=router_decision,
                snapshot=router_context.task_focus_snapshot,
            ),
            side_conversation_allowed=router_context.side_conversation_allowed,
            default_patch_policy=_default_patch_policy(router_context, active_task_id),
            ambiguous_input_policy=router_context.ambiguous_input_policy,
            last_focus_decision=task_focus,
            last_focus_confidence=confidence,
            router_decision_event_id=str(router_decision_event["event_id"]),
            last_focus_event_id=str(router_decision_event["event_id"]),
        )

        return MVP1RouterDecisionResult(
            router_decision_event=router_decision_event,
            task_focus_state_event=task_focus_state_event,
        )


def _validate_turn_committed_event(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise ValueError("MVP0Router requires a TURN_INGRESS_COMMITTED event")


def _validate_mock_frame(
    event: Mapping[str, Any],
    *,
    expected_event_name: str,
    turn_committed_event: Mapping[str, Any],
) -> None:
    if event.get("event_name") != expected_event_name:
        raise ValueError(f"MVP0Router requires a {expected_event_name} event")
    if event.get("output_mode") != "mock":
        raise ValueError(f"{expected_event_name} must use output_mode=mock")
    for field in ("turn_id", "utterance_id"):
        if event.get(field) != turn_committed_event.get(field):
            raise ValueError(f"{expected_event_name} must match committed turn {field}")
    if event.get("caused_by_event_id") != turn_committed_event.get("event_id"):
        raise ValueError(f"{expected_event_name} must be caused by TURN_INGRESS_COMMITTED")


def _infer_mvp1_task_focus(
    *,
    turn_committed_event: Mapping[str, Any],
    asr_frame_event: Mapping[str, Any],
    thinker_frame_event: Mapping[str, Any],
    router_context: RouterContext,
) -> str:
    if turn_committed_event.get("directedness") == "NOT_DIRECTED":
        return "NON_ASSISTANT"

    explicit_focus = _task_focus_hint(asr_frame_event, thinker_frame_event)
    if explicit_focus is not None:
        if explicit_focus not in MVP1_TASK_FOCUS_VALUES:
            raise ValueError("MVP-1 task_focus must be an ADR-006 focus value")
        if (
            explicit_focus in MVP1_ACTIVE_TASK_REQUIRED_FOCUS_VALUES
            and not router_context.task_focus_snapshot.has_active_non_terminal_task
        ):
            raise ValueError(f"MVP-1 task_focus {explicit_focus} requires active non-terminal SlowTask")
        return explicit_focus

    has_active_task = router_context.task_focus_snapshot.has_active_non_terminal_task
    task_like = _task_like(asr_frame_event, thinker_frame_event)
    if not has_active_task:
        return "NEW_TASK_CANDIDATE" if task_like else "FOREGROUND_CHAT"
    if task_like:
        return "NEW_TASK_CANDIDATE"
    if _evidence_uncertainty(asr_frame_event, thinker_frame_event) == "high":
        return "AMBIGUOUS"
    return "FOREGROUND_CHAT"


def _router_decision_for_focus(
    *,
    task_focus: str,
    router_context: RouterContext,
) -> str:
    if task_focus == "NON_ASSISTANT":
        return "IGNORE"
    if router_context.task_focus_snapshot.has_active_non_terminal_task:
        if task_focus in MVP1_PATCH_FOCUS_VALUES:
            return "PATCH_ACTIVE_SLOW_TASK"
        return "FAST_ONLY"
    if task_focus == "NEW_TASK_CANDIDATE":
        return "SPAWN_SLOW_TASK"
    return "FAST_ONLY"


def _task_focus_hint(*events: Mapping[str, Any]) -> str | None:
    for event in reversed(events):
        value = event.get("task_focus_hint")
        if value not in (None, ""):
            return str(value)
    return None


def _task_like(*events: Mapping[str, Any]) -> bool:
    for event in events:
        if event.get("task_like") is True:
            return True
        complexity_hint = event.get("complexity_hint")
        if isinstance(complexity_hint, str) and complexity_hint.lower() in {"complex", "task", "slow_task"}:
            return True
    return False


def _focus_confidence(*events: Mapping[str, Any]) -> float:
    for event in reversed(events):
        value = event.get("focus_confidence", event.get("confidence"))
        if value not in (None, ""):
            return float(value)
    return 1.0


def _evidence_uncertainty(*events: Mapping[str, Any]) -> str:
    for event in reversed(events):
        value = event.get("evidence_uncertainty")
        if value not in (None, ""):
            return str(value)
    return "low"


def _active_task_id(snapshot: TaskFocusSnapshot) -> str | None:
    if not snapshot.has_active_non_terminal_task:
        return None
    return snapshot.active_task_id


def _foreground_mode(
    *,
    router_decision: str,
    snapshot: TaskFocusSnapshot,
) -> str:
    if router_decision == "FAST_ONLY":
        return "FAST_RESPONSE"
    if snapshot.pending_confirmation_scope is not None:
        return "WAITING_CONFIRMATION"
    if snapshot.has_active_non_terminal_task:
        return "SLOWTASK_ACTIVE"
    return "IDLE"


def _default_patch_policy(router_context: RouterContext, active_task_id: str | None) -> str:
    if router_context.default_patch_policy is not None:
        return router_context.default_patch_policy
    if active_task_id is None:
        return "NO_ACTIVE_TASK"
    return "ACTIVE_TASK_PATCH_ONLY"
