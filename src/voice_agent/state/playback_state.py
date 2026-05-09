from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


PLAYBACK_EVENT_NAMES = frozenset(
    {
        "PLAYBACK_SPAN_STARTED",
        "PLAYBACK_PROGRESS",
        "PLAYBACK_COMMITTED",
        "PLAYBACK_FINISHED",
        "TTS_TRUNCATE_REQUESTED",
        "TTS_TRUNCATED",
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
    }
)
TERMINAL_PHASES = frozenset({"TRUNCATED", "FINISHED"})


@dataclass
class PlaybackState:
    current_playback_span_id: str | None = None
    phase: str = "NOT_PLAYING"
    latest_playback_offset_ms: int | None = None
    latest_committed_offset_ms: int | None = None
    approved_check_event_id: str | None = None
    cutoff_playback_offset_ms: int | None = None
    actual_stop_offset_ms: int | None = None
    truncate_request_event_id: str | None = None
    last_playback_event_id: str | None = None

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        event_name = str(event["event_name"])
        if event_name not in PLAYBACK_EVENT_NAMES:
            return False

        if event_name == "PLAYBACK_SPAN_STARTED":
            self.current_playback_span_id = str(event["playback_span_id"])
            self.phase = "PLAYING"
            self.latest_playback_offset_ms = None
            self.latest_committed_offset_ms = None
            self.approved_check_event_id = _optional_str(event.get("approved_check_event_id"))
            self.cutoff_playback_offset_ms = None
            self.actual_stop_offset_ms = None
            self.truncate_request_event_id = None
        elif event_name == "PLAYBACK_PROGRESS":
            if self._is_current_nonterminal_span(event):
                self.latest_playback_offset_ms = int(event["playback_offset_ms"])
        elif event_name == "PLAYBACK_COMMITTED":
            if self._is_current_nonterminal_span(event):
                self.latest_committed_offset_ms = int(event["playback_offset_ms"])
        elif event_name == "TTS_TRUNCATE_REQUESTED":
            if self._is_current_or_unset_span(event):
                self.current_playback_span_id = str(event["playback_span_id"])
                self.phase = "TRUNCATE_REQUESTED"
                self.cutoff_playback_offset_ms = int(event["cutoff_playback_offset_ms"])
        elif event_name == "TTS_TRUNCATED":
            if self._is_current_or_unset_span(event):
                self.current_playback_span_id = str(event["playback_span_id"])
                self.phase = "TRUNCATED"
                self.actual_stop_offset_ms = int(event["actual_stop_offset_ms"])
                self.truncate_request_event_id = str(event["truncate_request_event_id"])
        elif event_name == "PLAYBACK_FINISHED":
            if self._is_current_or_unset_span(event):
                self.current_playback_span_id = str(event["playback_span_id"])
                self.phase = "FINISHED"
                self.latest_playback_offset_ms = int(event["final_playback_offset_ms"])

        self.last_playback_event_id = str(event["event_id"])
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        return asdict(self)

    def _is_current_nonterminal_span(self, event: Mapping[str, Any]) -> bool:
        return self.phase not in TERMINAL_PHASES and self._is_current_or_unset_span(event)

    def _is_current_or_unset_span(self, event: Mapping[str, Any]) -> bool:
        event_span = str(event["playback_span_id"])
        return self.current_playback_span_id in (None, event_span)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
