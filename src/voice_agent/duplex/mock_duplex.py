from __future__ import annotations

from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal


SPEECH_START_DETECTION_BASIS = "mock_rule:speech_start_on_audio_span_started"
SPEECH_END_DETECTION_BASIS = "mock_rule:speech_end_on_audio_span_ended"


class MockDuplexRuleGate:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def record_speech_start(
        self,
        audio_started_event: Mapping[str, Any],
        *,
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        audio_sample_offset: int,
        vad_confidence: float,
    ) -> dict[str, Any]:
        _validate_audio_event(audio_started_event, "AUDIO_SPAN_STARTED")
        return self._journal.append(
            event_name="SPEECH_START_DETECTED",
            event_id=event_id,
            source_module="duplex_mock",
            caused_by_event_id=str(audio_started_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            audio_span_id=str(audio_started_event["audio_span_id"]),
            audio_sample_offset=audio_sample_offset,
            vad_confidence=vad_confidence,
            detection_basis=SPEECH_START_DETECTION_BASIS,
        )

    def record_speech_end(
        self,
        audio_ended_event: Mapping[str, Any],
        *,
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        audio_sample_offset: int,
        vad_confidence: float,
        silence_duration_ms: int,
    ) -> dict[str, Any]:
        _validate_audio_event(audio_ended_event, "AUDIO_SPAN_ENDED")
        return self._journal.append(
            event_name="SPEECH_END_DETECTED",
            event_id=event_id,
            source_module="duplex_mock",
            caused_by_event_id=str(audio_ended_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            audio_span_id=str(audio_ended_event["audio_span_id"]),
            audio_sample_offset=audio_sample_offset,
            vad_confidence=vad_confidence,
            silence_duration_ms=silence_duration_ms,
            detection_basis=SPEECH_END_DETECTION_BASIS,
        )


def _validate_audio_event(event: Mapping[str, Any], expected_event_name: str) -> None:
    if event.get("event_name") != expected_event_name:
        raise ValueError(f"MockDuplexRuleGate requires a {expected_event_name} event")
