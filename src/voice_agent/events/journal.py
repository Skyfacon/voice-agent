from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from voice_agent.events.envelope import validate_event_envelope
from voice_agent.privacy.redaction import PayloadBlockedError, sanitize_event_payload


AUDIT_EVENT_SCHEMA_VERSION = "1.0"
_ATOMIC_REQUEST_OWNED_FIELDS = frozenset(
    {
        "event_name",
        "event_id",
        "event_seq",
        "event_schema_version",
        "session_id",
        "conversation_id",
        "source_module",
        "created_monotonic_ms",
        "created_wall_clock_ms",
        "trace_redaction_level",
        "caused_by_event_id",
        "supersedes_event_id",
    }
)


@dataclass(frozen=True, slots=True)
class JournalAppendRequest:
    event_name: str
    event_id: str
    source_module: str
    created_monotonic_ms: int
    created_wall_clock_ms: int
    trace_redaction_level: str
    caused_by_event_id: str | None = None
    supersedes_event_id: str | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)


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

        try:
            sanitized_event, redacted_fields = sanitize_event_payload(event)
        except PayloadBlockedError:
            self._append_trace_write_blocked_secret_detected(
                caused_by_event_id=caused_by_event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
            )
            raise
        if redacted_fields:
            sanitized_event["redaction_metadata"] = {
                "redacted_fields": redacted_fields,
                "redaction_reason": "secret-like payload field",
            }

        validated_event = self._append_validated_event(sanitized_event)
        if redacted_fields:
            self._append_trace_secret_redaction_applied(validated_event, redacted_fields)
        return deepcopy(validated_event)

    def events(self) -> list[dict[str, Any]]:
        return deepcopy(self._events)

    def has_event_id(self, event_id: str) -> bool:
        return event_id in self._event_ids

    def append_atomic_batch(
        self,
        requests: Sequence[JournalAppendRequest],
    ) -> tuple[dict[str, Any], ...]:
        request_batch = tuple(requests)
        request_event_ids: set[str] = set()
        for request in request_batch:
            if request.event_id in self._event_ids or request.event_id in request_event_ids:
                raise ValueError("Duplicate event_id in session journal")
            request_event_ids.add(request.event_id)

        next_event_seq = self._next_event_seq
        staged_event_ids = set(self._event_ids)
        reserved_event_ids = staged_event_ids | request_event_ids
        staged_playback_span_ids = [
            event.get("playback_span_id")
            for event in self._events
            if event.get("event_name") == "PLAYBACK_SPAN_STARTED"
        ]
        staged_events: list[dict[str, Any]] = []
        staged_main_events: list[dict[str, Any]] = []
        for request in request_batch:
            fields = dict(request.fields)
            owned_fields = _ATOMIC_REQUEST_OWNED_FIELDS.intersection(fields)
            if owned_fields:
                owned_field = min(owned_fields)
                raise ValueError(
                    f"{owned_field} is owned by the journal append request"
                )
            if (
                request.caused_by_event_id is not None
                and request.caused_by_event_id not in staged_event_ids
            ):
                raise ValueError(
                    "caused_by_event_id does not reference an appended event"
                )
            if (
                request.supersedes_event_id is not None
                and request.supersedes_event_id not in staged_event_ids
            ):
                raise ValueError(
                    "supersedes_event_id does not reference an appended event"
                )

            event: dict[str, Any] = {
                "event_name": request.event_name,
                "event_id": request.event_id,
                "event_seq": next_event_seq,
                "event_schema_version": "1.0",
                "session_id": self._session_id,
                "conversation_id": self._conversation_id,
                "source_module": request.source_module,
                "created_monotonic_ms": request.created_monotonic_ms,
                "created_wall_clock_ms": request.created_wall_clock_ms,
                "trace_redaction_level": request.trace_redaction_level,
                **fields,
            }
            if request.caused_by_event_id is not None:
                event["caused_by_event_id"] = request.caused_by_event_id
            if request.supersedes_event_id is not None:
                event["supersedes_event_id"] = request.supersedes_event_id

            try:
                sanitized_event, redacted_fields = sanitize_event_payload(event)
            except PayloadBlockedError:
                self._append_atomic_blocked_secret_audit(
                    caused_by_event_id=request.caused_by_event_id,
                    created_monotonic_ms=request.created_monotonic_ms,
                    created_wall_clock_ms=request.created_wall_clock_ms,
                    occupied_event_ids=reserved_event_ids,
                )
                raise
            if redacted_fields:
                sanitized_event["redaction_metadata"] = {
                    "redacted_fields": redacted_fields,
                    "redaction_reason": "secret-like payload field",
                }
            validated_event = validate_event_envelope(sanitized_event)
            if validated_event["event_name"] == "PLAYBACK_SPAN_STARTED":
                playback_span_id = validated_event["playback_span_id"]
                if any(
                    existing_span_id == playback_span_id
                    for existing_span_id in staged_playback_span_ids
                ):
                    raise ValueError(
                        "PLAYBACK_SPAN_STARTED requires a unique playback_span_id "
                        "per session journal"
                    )
                staged_playback_span_ids.append(deepcopy(playback_span_id))
            staged_events.append(validated_event)
            staged_main_events.append(validated_event)
            staged_event_ids.add(str(validated_event["event_id"]))
            next_event_seq += 1
            if redacted_fields:
                target_event_id = str(validated_event["event_id"])
                audit_event = {
                    "event_name": "TRACE_SECRET_REDACTION_APPLIED",
                    "event_id": self._generated_opaque_event_id_for_state(
                        "evt_trace_redaction_applied",
                        event_seq=next_event_seq,
                        occupied_event_ids=reserved_event_ids,
                    ),
                    "event_seq": next_event_seq,
                    "event_schema_version": validated_event["event_schema_version"],
                    "session_id": self._session_id,
                    "conversation_id": self._conversation_id,
                    "source_module": "trace_runtime",
                    "created_monotonic_ms": validated_event["created_monotonic_ms"],
                    "created_wall_clock_ms": validated_event["created_wall_clock_ms"],
                    "caused_by_event_id": target_event_id,
                    "trace_redaction_level": "metadata_only",
                    "payload_ref": f"payload://redacted/{target_event_id}",
                    "redaction_reason": "secret-like payload field",
                    "redacted_fields": list(redacted_fields),
                }
                reserved_event_ids.add(str(audit_event["event_id"]))
                sanitized_audit, audit_redacted_fields = sanitize_event_payload(audit_event)
                if audit_redacted_fields:
                    sanitized_audit["redaction_metadata"] = {
                        "redacted_fields": audit_redacted_fields,
                        "redaction_reason": "secret-like audit payload field",
                    }
                validated_audit = validate_event_envelope(sanitized_audit)
                staged_events.append(validated_audit)
                staged_event_ids.add(str(validated_audit["event_id"]))
                next_event_seq += 1

        stored_events = deepcopy(staged_events)
        returned_events = tuple(deepcopy(staged_main_events))
        next_events = [*self._events, *stored_events]
        self._events, self._event_ids, self._next_event_seq = (
            next_events,
            staged_event_ids,
            next_event_seq,
        )
        return returned_events

    def _append_atomic_blocked_secret_audit(
        self,
        *,
        caused_by_event_id: str | None,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        occupied_event_ids: set[str],
    ) -> None:
        event_seq = self._next_event_seq
        audit_event = {
            "event_name": "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
            "event_id": self._generated_opaque_event_id_for_state(
                "evt_trace_write_blocked",
                event_seq=event_seq,
                occupied_event_ids=occupied_event_ids,
            ),
            "event_seq": event_seq,
            "event_schema_version": AUDIT_EVENT_SCHEMA_VERSION,
            "session_id": self._session_id,
            "conversation_id": self._conversation_id,
            "source_module": "trace_runtime",
            "created_monotonic_ms": created_monotonic_ms,
            "created_wall_clock_ms": created_wall_clock_ms,
            "trace_redaction_level": "metadata_only",
            "blocked_payload_ref": f"payload://blocked/{event_seq:08d}",
            "secret_kind": "secret_like_payload",
            "blocking_reason": "blocked before journal append",
        }
        if caused_by_event_id in self._event_ids:
            audit_event["caused_by_event_id"] = caused_by_event_id

        sanitized_audit, redacted_fields = sanitize_event_payload(audit_event)
        if redacted_fields:
            sanitized_audit["redaction_metadata"] = {
                "redacted_fields": redacted_fields,
                "redaction_reason": "secret-like audit payload field",
            }
        validated_audit = validate_event_envelope(sanitized_audit)
        stored_audit = deepcopy(validated_audit)
        next_events = [*self._events, stored_audit]
        next_event_ids = self._event_ids | {str(validated_audit["event_id"])}
        self._events, self._event_ids, self._next_event_seq = (
            next_events,
            next_event_ids,
            event_seq + 1,
        )

    @staticmethod
    def _generated_opaque_event_id_for_state(
        prefix: str,
        *,
        event_seq: int,
        occupied_event_ids: set[str],
    ) -> str:
        base = f"{prefix}_{event_seq:08d}"
        candidate = base
        collision_index = 1
        while candidate in occupied_event_ids:
            candidate = f"{base}_{collision_index}"
            collision_index += 1
        return candidate

    def _validate_unique_playback_span_id(self, playback_span_id: object) -> None:
        for event in self._events:
            if (
                event.get("event_name") == "PLAYBACK_SPAN_STARTED"
                and event.get("playback_span_id") == playback_span_id
            ):
                raise ValueError("PLAYBACK_SPAN_STARTED requires a unique playback_span_id per session journal")

    def _append_validated_event(self, event: dict[str, Any]) -> dict[str, Any]:
        validated_event = validate_event_envelope(event)
        self._events.append(deepcopy(validated_event))
        self._event_ids.add(str(validated_event["event_id"]))
        self._next_event_seq += 1
        return validated_event

    def _append_trace_secret_redaction_applied(
        self,
        target_event: dict[str, Any],
        redacted_fields: list[str],
    ) -> None:
        target_event_id = str(target_event["event_id"])
        audit_event = {
            "event_name": "TRACE_SECRET_REDACTION_APPLIED",
            "event_id": self._generated_opaque_event_id("evt_trace_redaction_applied"),
            "event_seq": self._next_event_seq,
            "event_schema_version": target_event["event_schema_version"],
            "session_id": self._session_id,
            "conversation_id": self._conversation_id,
            "source_module": "trace_runtime",
            "created_monotonic_ms": target_event["created_monotonic_ms"],
            "created_wall_clock_ms": target_event["created_wall_clock_ms"],
            "caused_by_event_id": target_event_id,
            "trace_redaction_level": "metadata_only",
            "payload_ref": f"payload://redacted/{target_event_id}",
            "redaction_reason": "secret-like payload field",
            "redacted_fields": list(redacted_fields),
        }
        self._append_sanitized_audit_event(audit_event)

    def _append_trace_write_blocked_secret_detected(
        self,
        *,
        caused_by_event_id: str | None,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> None:
        audit_event = {
            "event_name": "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
            "event_id": self._generated_opaque_event_id("evt_trace_write_blocked"),
            "event_seq": self._next_event_seq,
            "event_schema_version": AUDIT_EVENT_SCHEMA_VERSION,
            "session_id": self._session_id,
            "conversation_id": self._conversation_id,
            "source_module": "trace_runtime",
            "created_monotonic_ms": created_monotonic_ms,
            "created_wall_clock_ms": created_wall_clock_ms,
            "trace_redaction_level": "metadata_only",
            "blocked_payload_ref": f"payload://blocked/{self._next_event_seq:08d}",
            "secret_kind": "secret_like_payload",
            "blocking_reason": "blocked before journal append",
        }
        if caused_by_event_id is not None:
            audit_event["caused_by_event_id"] = caused_by_event_id
        self._append_sanitized_audit_event(audit_event)

    def _append_sanitized_audit_event(self, audit_event: dict[str, Any]) -> None:
        sanitized_event, redacted_fields = sanitize_event_payload(audit_event)
        if redacted_fields:
            sanitized_event["redaction_metadata"] = {
                "redacted_fields": redacted_fields,
                "redaction_reason": "secret-like audit payload field",
        }
        self._append_validated_event(sanitized_event)

    def _generated_opaque_event_id(self, prefix: str) -> str:
        base = f"{prefix}_{self._next_event_seq:08d}"
        candidate = base
        collision_index = 1
        while candidate in self._event_ids:
            candidate = f"{base}_{collision_index}"
            collision_index += 1
        return candidate
