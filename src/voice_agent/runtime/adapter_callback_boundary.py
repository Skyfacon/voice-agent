from __future__ import annotations

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
    }
)


class AdapterCallbackAppendBoundary:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal
        self._lock = Lock()
        self._next_callback_seq = 1

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
