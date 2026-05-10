from __future__ import annotations

from typing import Any

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.interaction.policy import AUDIO_INPUT_MODALITY


def receive_audio_span_start(
    journal: InMemoryEventJournal,
    *,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    audio_span_id: str,
    audio_sample_offset: int,
    audio_format_ref: str,
    input_span_id: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "audio_span_id": audio_span_id,
        "input_modality": AUDIO_INPUT_MODALITY,
        "audio_sample_offset": audio_sample_offset,
        "audio_format_ref": audio_format_ref,
    }
    if input_span_id is not None:
        fields["input_span_id"] = input_span_id

    return journal.append(
        event_name="AUDIO_SPAN_STARTED",
        event_id=event_id,
        source_module="access_layer",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        **fields,
    )


def receive_audio_span_end(
    journal: InMemoryEventJournal,
    *,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    audio_span_id: str,
    audio_sample_offset: int,
    duration_ms: int,
    end_reason: str,
) -> dict[str, Any]:
    return journal.append(
        event_name="AUDIO_SPAN_ENDED",
        event_id=event_id,
        source_module="access_layer",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=audio_sample_offset,
        duration_ms=duration_ms,
        end_reason=end_reason,
    )
