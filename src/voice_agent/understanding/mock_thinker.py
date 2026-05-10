from __future__ import annotations

from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal


def emit_mock_thinker_frame(
    journal: InMemoryEventJournal,
    turn_committed_event: Mapping[str, Any],
    *,
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    semantic_frame_ref: str,
) -> dict[str, Any]:
    _validate_turn_committed_event(turn_committed_event)
    return journal.append(
        event_name="MOCK_THINKER_FRAME_EMITTED",
        event_id=event_id,
        source_module="mock_thinker_adapter",
        caused_by_event_id=str(turn_committed_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        turn_id=str(turn_committed_event["turn_id"]),
        utterance_id=str(turn_committed_event["utterance_id"]),
        input_modality=str(turn_committed_event["input_modality"]),
        semantic_frame_ref=semantic_frame_ref,
        output_mode="mock",
    )


def _validate_turn_committed_event(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise ValueError("emit_mock_thinker_frame requires a TURN_INGRESS_COMMITTED event")
