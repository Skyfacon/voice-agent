from __future__ import annotations

from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal


MVP0_ROUTER_DECISIONS = frozenset({"FAST_ONLY", "IGNORE"})
MVP0_TASK_FOCUS_BY_DECISION = {
    "FAST_ONLY": "FOREGROUND_CHAT",
    "IGNORE": "NON_ASSISTANT",
}


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
