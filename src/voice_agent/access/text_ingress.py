from __future__ import annotations

from typing import Any

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.interaction.policy import ASSUMED_CLOSED, ASSUMED_DIRECTED, TEXT_INPUT_MODALITY


def receive_text_input(
    journal: InMemoryEventJournal,
    *,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    input_span_id: str,
    text_span_id: str,
    redacted_text: str | None = None,
    text_ref: str | None = None,
    language_hint: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "input_span_id": input_span_id,
        "text_span_id": text_span_id,
        "audio_span_id": None,
        "input_modality": TEXT_INPUT_MODALITY,
        "directedness": ASSUMED_DIRECTED,
        "semantic_close": ASSUMED_CLOSED,
    }
    if redacted_text is not None:
        fields["redacted_text"] = redacted_text
    if text_ref is not None:
        fields["text_ref"] = text_ref
    if language_hint is not None:
        fields["language_hint"] = language_hint

    return journal.append(
        event_name="TEXT_INPUT_RECEIVED",
        event_id=event_id,
        source_module="access_layer",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="redacted_fixture",
        **fields,
    )
