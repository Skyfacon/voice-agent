from __future__ import annotations

from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal


MOCK_TALKER_PROFILE_REF = "mock-profile://synthetic/mvp0/talker-playback-v1"
MOCK_TALKER_OUTPUT_MODE = "mock"
PLAYBACK_SOURCE_MODULE = "mock_talker"
SYNTHETIC_AUDIO_REF_PREFIX = "audio://synthetic/"
SYNTHETIC_TTS_STREAM_REF_PREFIX = "tts-stream://synthetic/"
RAW_AUDIO_EXTENSIONS = (".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".weba")
LOCAL_ONLY_PATH_MARKERS = ("audio/raw/", "traces/", "diagnostics/", "replays/local/")


class MockTalker:
    """Deterministic MVP-0 mock/rule Talker that emits playback metadata only."""

    def __init__(
        self,
        journal: InMemoryEventJournal,
        *,
        mock_profile_ref: str = MOCK_TALKER_PROFILE_REF,
    ) -> None:
        self._journal = journal
        self._mock_profile_ref = mock_profile_ref
        self._started_playback_span_ids: set[str] = set()

    def start_playback_after_fast_only(
        self,
        *,
        router_decision_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        playback_span_id: str,
        audio_ref: str | None = None,
        tts_stream_ref: str | None = None,
    ) -> dict[str, Any]:
        _validate_fast_only_router_decision(router_decision_event)
        ref_fields = _synthetic_playback_ref_fields(audio_ref=audio_ref, tts_stream_ref=tts_stream_ref)
        self._validate_unique_span(playback_span_id)

        started = self._journal.append(
            event_name="PLAYBACK_SPAN_STARTED",
            event_id=event_id,
            source_module=PLAYBACK_SOURCE_MODULE,
            caused_by_event_id=str(router_decision_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            playback_span_id=playback_span_id,
            output_mode=MOCK_TALKER_OUTPUT_MODE,
            mock_profile_ref=self._mock_profile_ref,
            **ref_fields,
        )
        self._started_playback_span_ids.add(playback_span_id)
        return started

    def record_progress(
        self,
        *,
        playback_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        playback_offset_ms: int,
        progress_basis: str = "mock_rule_offset",
    ) -> dict[str, Any]:
        span_id = _playback_span_id_from_event(
            playback_event,
            allowed_event_names=("PLAYBACK_SPAN_STARTED", "PLAYBACK_PROGRESS", "PLAYBACK_COMMITTED"),
        )
        _validate_non_negative_offset(playback_offset_ms, field_name="playback_offset_ms")
        return self._journal.append(
            event_name="PLAYBACK_PROGRESS",
            event_id=event_id,
            source_module=PLAYBACK_SOURCE_MODULE,
            caused_by_event_id=str(playback_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            playback_span_id=span_id,
            playback_offset_ms=playback_offset_ms,
            progress_basis=progress_basis,
            output_mode=MOCK_TALKER_OUTPUT_MODE,
            mock_profile_ref=self._mock_profile_ref,
        )

    def record_committed(
        self,
        *,
        playback_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        playback_offset_ms: int,
        commit_basis: str = "mock_delivery_marker",
    ) -> dict[str, Any]:
        span_id = _playback_span_id_from_event(
            playback_event,
            allowed_event_names=("PLAYBACK_PROGRESS", "PLAYBACK_FINISHED"),
        )
        _validate_non_negative_offset(playback_offset_ms, field_name="playback_offset_ms")
        return self._journal.append(
            event_name="PLAYBACK_COMMITTED",
            event_id=event_id,
            source_module=PLAYBACK_SOURCE_MODULE,
            caused_by_event_id=str(playback_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            playback_span_id=span_id,
            playback_offset_ms=playback_offset_ms,
            commit_basis=commit_basis,
            output_mode=MOCK_TALKER_OUTPUT_MODE,
            mock_profile_ref=self._mock_profile_ref,
        )

    def record_finished(
        self,
        *,
        playback_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        final_playback_offset_ms: int,
        finish_reason: str = "mock_span_completed",
    ) -> dict[str, Any]:
        span_id = _playback_span_id_from_event(
            playback_event,
            allowed_event_names=("PLAYBACK_PROGRESS", "PLAYBACK_COMMITTED"),
        )
        _validate_non_negative_offset(final_playback_offset_ms, field_name="final_playback_offset_ms")
        return self._journal.append(
            event_name="PLAYBACK_FINISHED",
            event_id=event_id,
            source_module=PLAYBACK_SOURCE_MODULE,
            caused_by_event_id=str(playback_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            playback_span_id=span_id,
            final_playback_offset_ms=final_playback_offset_ms,
            finish_reason=finish_reason,
            output_mode=MOCK_TALKER_OUTPUT_MODE,
            mock_profile_ref=self._mock_profile_ref,
        )

    def record_truncated(
        self,
        truncate_request_event: Mapping[str, Any],
        *,
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        actual_stop_offset_ms: int,
        final_playback_offset_ms: int | None = None,
    ) -> dict[str, Any]:
        span_id = _playback_span_id_from_truncate_request(truncate_request_event)
        _validate_non_negative_offset(actual_stop_offset_ms, field_name="actual_stop_offset_ms")

        fields: dict[str, Any] = {}
        if final_playback_offset_ms is not None:
            _validate_non_negative_offset(final_playback_offset_ms, field_name="final_playback_offset_ms")
            fields["final_playback_offset_ms"] = final_playback_offset_ms

        return self._journal.append(
            event_name="TTS_TRUNCATED",
            event_id=event_id,
            source_module=PLAYBACK_SOURCE_MODULE,
            caused_by_event_id=str(truncate_request_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            playback_span_id=span_id,
            actual_stop_offset_ms=actual_stop_offset_ms,
            truncate_request_event_id=str(truncate_request_event["event_id"]),
            output_mode=MOCK_TALKER_OUTPUT_MODE,
            mock_profile_ref=self._mock_profile_ref,
            **fields,
        )

    def _validate_unique_span(self, playback_span_id: str) -> None:
        if playback_span_id in self._started_playback_span_ids:
            raise ValueError("Mock playback requires a unique playback_span_id")
        for event in self._journal.events():
            if (
                event.get("event_name") == "PLAYBACK_SPAN_STARTED"
                and event.get("playback_span_id") == playback_span_id
            ):
                raise ValueError("Mock playback requires a unique playback_span_id")


def _validate_fast_only_router_decision(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "ROUTER_DECISION_EMITTED":
        raise ValueError("MockTalker requires a ROUTER_DECISION_EMITTED event")
    if event.get("router_decision") != "FAST_ONLY":
        raise ValueError("MockTalker playback starts only after a FAST_ONLY router decision")


def _synthetic_playback_ref_fields(*, audio_ref: str | None, tts_stream_ref: str | None) -> dict[str, str]:
    refs = {"audio_ref": audio_ref, "tts_stream_ref": tts_stream_ref}
    present_refs = {field: value for field, value in refs.items() if value is not None}
    if len(present_refs) != 1:
        raise ValueError("Mock playback requires exactly one synthetic playback ref")
    field, value = next(iter(present_refs.items()))
    _validate_synthetic_playback_ref(field=field, value=value)
    return {field: value}


def _validate_synthetic_playback_ref(*, field: str, value: str) -> None:
    expected_prefix = SYNTHETIC_AUDIO_REF_PREFIX if field == "audio_ref" else SYNTHETIC_TTS_STREAM_REF_PREFIX
    lower_value = value.lower()
    if not value.startswith(expected_prefix):
        raise ValueError("Mock playback requires a synthetic playback ref")
    if any(marker in lower_value for marker in LOCAL_ONLY_PATH_MARKERS):
        raise ValueError("Mock playback requires a synthetic playback ref")
    if lower_value.endswith(RAW_AUDIO_EXTENSIONS):
        raise ValueError("Mock playback requires a synthetic playback ref")


def _playback_span_id_from_event(
    event: Mapping[str, Any],
    *,
    allowed_event_names: tuple[str, ...],
) -> str:
    if event.get("event_name") not in allowed_event_names:
        expected = ", ".join(allowed_event_names)
        raise ValueError(f"MockTalker playback event must be one of: {expected}")
    if event.get("output_mode") != MOCK_TALKER_OUTPUT_MODE:
        raise ValueError("MockTalker only chains mock playback events")
    playback_span_id = event.get("playback_span_id")
    if not playback_span_id:
        raise ValueError("MockTalker playback event must include playback_span_id")
    return str(playback_span_id)


def _playback_span_id_from_truncate_request(event: Mapping[str, Any]) -> str:
    if event.get("event_name") != "TTS_TRUNCATE_REQUESTED":
        raise ValueError("MockTalker truncate confirmation requires a TTS_TRUNCATE_REQUESTED event")
    playback_span_id = event.get("playback_span_id")
    if not playback_span_id:
        raise ValueError("TTS_TRUNCATE_REQUESTED must include playback_span_id")
    if not event.get("interrupt_candidate_event_id"):
        raise ValueError("TTS_TRUNCATE_REQUESTED must include interrupt_candidate_event_id")
    return str(playback_span_id)


def _validate_non_negative_offset(value: int, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
