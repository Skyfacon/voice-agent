from __future__ import annotations

from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal


SPEECH_START_DETECTION_BASIS = "mock_rule:speech_start_on_audio_span_started"
SPEECH_END_DETECTION_BASIS = "mock_rule:speech_end_on_audio_span_ended"
BARGE_IN_DETECTION_BASIS = "mock_rule:barge_in_on_speech_playback_overlap"
MOCK_DUPLEX_BARGE_IN_PROFILE_REF = "mock-profile://synthetic/mvp0/duplex-barge-in-v1"
MOCK_DUPLEX_OUTPUT_MODE = "mock"
SYNTHETIC_PLAYBACK_REFERENCE_REF_PREFIX = "playback-ref://synthetic/"
RAW_PLAYBACK_REFERENCE_EXTENSIONS = (".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".weba")
LOCAL_ONLY_REFERENCE_MARKERS = ("audio/raw/", "traces/", "diagnostics/", "replays/local/")


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

    def record_barge_in_candidate(
        self,
        speech_start_event: Mapping[str, Any],
        *,
        playback_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        playback_offset_ms: int,
        echo_likelihood: str,
        vad_confidence: float,
        barge_in_confidence: float,
        playback_reference_ref: str | None = None,
    ) -> dict[str, Any]:
        _validate_audio_event(speech_start_event, "SPEECH_START_DETECTED")
        playback_span_id = _playback_span_id_from_event(playback_event)
        _validate_non_negative_offset(playback_offset_ms, field_name="playback_offset_ms")
        _validate_confidence(vad_confidence, field_name="vad_confidence")
        _validate_confidence(barge_in_confidence, field_name="barge_in_confidence")
        _validate_echo_likelihood(echo_likelihood)

        ref_fields: dict[str, str] = {}
        if playback_reference_ref is not None:
            _validate_synthetic_playback_reference(playback_reference_ref)
            ref_fields["playback_reference_ref"] = playback_reference_ref

        return self._journal.append(
            event_name="BARGE_IN_CANDIDATE",
            event_id=event_id,
            source_module="duplex_mock",
            caused_by_event_id=str(speech_start_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            audio_span_id=str(speech_start_event["audio_span_id"]),
            playback_span_id=playback_span_id,
            playback_offset_ms=playback_offset_ms,
            echo_likelihood=echo_likelihood,
            vad_confidence=vad_confidence,
            barge_in_confidence=barge_in_confidence,
            detection_basis=BARGE_IN_DETECTION_BASIS,
            output_mode=MOCK_DUPLEX_OUTPUT_MODE,
            mock_profile_ref=MOCK_DUPLEX_BARGE_IN_PROFILE_REF,
            **ref_fields,
        )


def _validate_audio_event(event: Mapping[str, Any], expected_event_name: str) -> None:
    if event.get("event_name") != expected_event_name:
        raise ValueError(f"MockDuplexRuleGate requires a {expected_event_name} event")


def _playback_span_id_from_event(event: Mapping[str, Any]) -> str:
    if event.get("event_name") not in ("PLAYBACK_SPAN_STARTED", "PLAYBACK_PROGRESS", "PLAYBACK_COMMITTED"):
        raise ValueError("MockDuplexRuleGate barge-in requires an active mock playback event")
    if event.get("output_mode") != MOCK_DUPLEX_OUTPUT_MODE:
        raise ValueError("MockDuplexRuleGate barge-in only chains mock playback events")
    playback_span_id = event.get("playback_span_id")
    if not playback_span_id:
        raise ValueError("MockDuplexRuleGate playback event must include playback_span_id")
    return str(playback_span_id)


def _validate_non_negative_offset(value: int, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_confidence(value: float, *, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
        raise ValueError(f"{field_name} must be a number between 0 and 1")


def _validate_echo_likelihood(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("echo_likelihood must be a non-empty string")


def _validate_synthetic_playback_reference(value: str) -> None:
    lower_value = value.lower()
    if not value.startswith(SYNTHETIC_PLAYBACK_REFERENCE_REF_PREFIX):
        raise ValueError("Mock barge-in requires a synthetic playback reference")
    if any(marker in lower_value for marker in LOCAL_ONLY_REFERENCE_MARKERS):
        raise ValueError("Mock barge-in requires a synthetic playback reference")
    if lower_value.endswith(RAW_PLAYBACK_REFERENCE_EXTENSIONS):
        raise ValueError("Mock barge-in requires a synthetic playback reference")
