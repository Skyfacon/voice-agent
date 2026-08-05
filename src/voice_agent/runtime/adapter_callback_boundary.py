from __future__ import annotations

from collections.abc import Mapping
from threading import Lock
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal


class AdapterCallbackBoundaryError(ValueError):
    pass


ADAPTER_CALLBACK_EVENT_NAMES = frozenset(
    {
        "ADAPTER_HEALTHCHECK_FAILED",
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED",
        "TTS_SYNTHESIS_OUTPUT_EMITTED",
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "ROUTE_EVIDENCE_OUTPUT_EMITTED",
        "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
    }
)


class AdapterCallbackAppendBoundary:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal
        self._lock = Lock()
        self._next_callback_seq = 1

    def require_event_ids_available(self, *event_ids: str) -> None:
        seen: set[str] = set()
        with self._lock:
            for event_id in event_ids:
                if event_id in seen or self._journal.has_event_id(event_id):
                    raise AdapterCallbackBoundaryError(
                        f"Duplicate event_id in session journal: {event_id}"
                    )
                seen.add(event_id)

    def require_recorded_event(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            raise AdapterCallbackBoundaryError(
                "recorded predecessor must be a mapping"
            )
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise AdapterCallbackBoundaryError(
                "recorded predecessor requires event_id"
            )
        expected = dict(event)
        with self._lock:
            for recorded in self._journal.events():
                if recorded.get("event_id") != event_id:
                    continue
                if recorded != expected:
                    raise AdapterCallbackBoundaryError(
                        "recorded predecessor fields do not match session journal"
                    )
                return recorded
        raise AdapterCallbackBoundaryError(
            "recorded predecessor is missing from session journal"
        )

    def append_adapter_event(self, **event_fields: Any) -> dict[str, Any]:
        event_name = event_fields.get("event_name")
        if event_name not in ADAPTER_CALLBACK_EVENT_NAMES:
            raise AdapterCallbackBoundaryError(f"Unsupported adapter callback event_name: {event_name!r}")
        if "adapter_callback_seq" in event_fields:
            raise AdapterCallbackBoundaryError("adapter_callback_seq is allocated by the adapter callback boundary")

        with self._lock:
            callback_seq = self._next_callback_seq
            self._next_callback_seq += 1
            return self._journal.append(**event_fields, adapter_callback_seq=callback_seq)
