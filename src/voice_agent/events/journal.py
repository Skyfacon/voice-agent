from __future__ import annotations

from copy import deepcopy
from typing import Any

from voice_agent.events.envelope import validate_event_envelope
from voice_agent.privacy.redaction import sanitize_event_payload


class InMemoryEventJournal:
    def __init__(self, *, session_id: str, conversation_id: str) -> None:
        self._session_id = session_id
        self._conversation_id = conversation_id
        self._next_event_seq = 1
        self._events: list[dict[str, Any]] = []
        self._event_ids: set[str] = set()

    def append(
        self,
        *,
        event_name: str,
        event_id: str,
        source_module: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        trace_redaction_level: str,
        event_schema_version: str = "1.0",
        caused_by_event_id: str | None = None,
        supersedes_event_id: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        if "event_seq" in fields:
            raise ValueError("event_seq is allocated by the journal")
        if "session_id" in fields or "conversation_id" in fields:
            raise ValueError("session_id and conversation_id are owned by the journal")
        if event_id in self._event_ids:
            raise ValueError(f"Duplicate event_id in session journal: {event_id}")
        if caused_by_event_id is not None and caused_by_event_id not in self._event_ids:
            raise ValueError(f"caused_by_event_id does not reference an appended event: {caused_by_event_id}")
        if event_name == "PLAYBACK_SPAN_STARTED" and "playback_span_id" in fields:
            self._validate_unique_playback_span_id(fields["playback_span_id"])

        event: dict[str, Any] = {
            "event_name": event_name,
            "event_id": event_id,
            "event_seq": self._next_event_seq,
            "event_schema_version": event_schema_version,
            "session_id": self._session_id,
            "conversation_id": self._conversation_id,
            "source_module": source_module,
            "created_monotonic_ms": created_monotonic_ms,
            "created_wall_clock_ms": created_wall_clock_ms,
            "trace_redaction_level": trace_redaction_level,
            **fields,
        }
        if caused_by_event_id is not None:
            event["caused_by_event_id"] = caused_by_event_id
        if supersedes_event_id is not None:
            event["supersedes_event_id"] = supersedes_event_id

        sanitized_event, redacted_fields = sanitize_event_payload(event)
        if redacted_fields:
            sanitized_event["redaction_metadata"] = {
                "redacted_fields": redacted_fields,
                "redaction_reason": "secret-like payload field",
            }

        validated_event = validate_event_envelope(sanitized_event)
        self._events.append(deepcopy(validated_event))
        self._event_ids.add(str(validated_event["event_id"]))
        self._next_event_seq += 1
        return deepcopy(validated_event)

    def events(self) -> list[dict[str, Any]]:
        return deepcopy(self._events)

    def _validate_unique_playback_span_id(self, playback_span_id: object) -> None:
        for event in self._events:
            if (
                event.get("event_name") == "PLAYBACK_SPAN_STARTED"
                and event.get("playback_span_id") == playback_span_id
            ):
                raise ValueError("PLAYBACK_SPAN_STARTED requires a unique playback_span_id per session journal")
