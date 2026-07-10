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
        "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED",
        "TTS_SYNTHESIS_OUTPUT_EMITTED",
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
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
