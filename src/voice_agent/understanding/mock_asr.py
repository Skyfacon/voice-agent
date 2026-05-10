from __future__ import annotations

from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal


def emit_mock_asr_frame(
    journal: InMemoryEventJournal,
    turn_committed_event: Mapping[str, Any],
    *,
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    asr_frame_ref: str,
) -> dict[str, Any]:
    _validate_turn_committed_event(turn_committed_event)
    fields: dict[str, Any] = {
        "turn_id": str(turn_committed_event["turn_id"]),
        "utterance_id": str(turn_committed_event["utterance_id"]),
        "input_modality": str(turn_committed_event["input_modality"]),
        "asr_frame_ref": asr_frame_ref,
        "output_mode": "mock",
    }
    for span_field in ("audio_span_id", "text_span_id"):
        if turn_committed_event.get(span_field) is not None:
            fields[span_field] = str(turn_committed_event[span_field])

    return journal.append(
        event_name="MOCK_ASR_FRAME_EMITTED",
        event_id=event_id,
        source_module="mock_asr_adapter",
        caused_by_event_id=str(turn_committed_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        **fields,
    )


def _validate_turn_committed_event(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise ValueError("emit_mock_asr_frame requires a TURN_INGRESS_COMMITTED event")
