from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


INTERACTION_EVENT_NAMES = frozenset(
    {
        "TEXT_INPUT_RECEIVED",
        "AUDIO_SPAN_STARTED",
        "AUDIO_SPAN_ENDED",
        "SPEECH_START_DETECTED",
        "SPEECH_END_DETECTED",
        "DIRECTEDNESS_CANDIDATE",
        "SEMANTIC_CLOSE_CANDIDATE",
        "NON_ASSISTANT_CANDIDATE",
        "LOW_CONFIDENCE_INGRESS",
        "TURN_OPENED",
        "TURN_HELD",
        "TURN_INGRESS_ACCEPTED",
        "TURN_INGRESS_REJECTED",
        "TURN_INGRESS_COMMITTED",
        "BARGE_IN_CANDIDATE",
        "INTERRUPT_CANDIDATE",
        "TTS_TRUNCATE_REQUESTED",
        "TTS_TRUNCATED",
        "WAITING_USER",
    }
)


@dataclass
class InteractionState:
    turn_phase: str = "IDLE"
    playback_phase: str = "NOT_PLAYING"
    directedness: str | None = None
    semantic_close: str | None = None
    current_turn_id: str | None = None
    current_input_span_id: str | None = None
    current_audio_span_id: str | None = None
    current_text_span_id: str | None = None
    current_playback_span_id: str | None = None
    last_ingress_outcome: str | None = None
    last_interaction_event_id: str | None = None

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        event_name = str(event["event_name"])
        if event_name not in INTERACTION_EVENT_NAMES:
            return False

        if "input_span_id" in event:
            self.current_input_span_id = _optional_str(event.get("input_span_id"))
        if "audio_span_id" in event:
            self.current_audio_span_id = _optional_str(event.get("audio_span_id"))
        if "text_span_id" in event:
            self.current_text_span_id = _optional_str(event.get("text_span_id"))
        if "playback_span_id" in event:
            self.current_playback_span_id = _optional_str(event.get("playback_span_id"))
        if "directedness" in event:
            self.directedness = _optional_str(event.get("directedness"))
        if "semantic_close" in event:
            self.semantic_close = _optional_str(event.get("semantic_close"))

        if event_name == "TEXT_INPUT_RECEIVED":
            self.current_audio_span_id = None
        elif event_name == "SPEECH_START_DETECTED":
            self.turn_phase = "COLLECTING_INPUT"
        elif event_name == "TURN_OPENED":
            self.current_turn_id = str(event["turn_id"])
            self.turn_phase = str(event["turn_phase"])
        elif event_name == "TURN_HELD":
            self.current_turn_id = str(event["turn_id"])
            self.turn_phase = "HOLDING_INPUT"
            self.last_ingress_outcome = str(event["ingress_outcome"])
        elif event_name == "TURN_INGRESS_ACCEPTED":
            self.current_turn_id = str(event["turn_id"])
            self.last_ingress_outcome = str(event["ingress_outcome"])
        elif event_name == "TURN_INGRESS_REJECTED":
            self.current_turn_id = str(event["turn_id"])
            self.turn_phase = "WAITING_USER"
            self.last_ingress_outcome = str(event["ingress_outcome"])
        elif event_name == "TURN_INGRESS_COMMITTED":
            self.current_turn_id = str(event["turn_id"])
            self.turn_phase = "TURN_COMMITTED"
            self.last_ingress_outcome = str(event["ingress_outcome"])
        elif event_name == "BARGE_IN_CANDIDATE":
            self.playback_phase = "PLAYING"
        elif event_name == "INTERRUPT_CANDIDATE":
            self.turn_phase = "INTERRUPTING"
            self.playback_phase = "TRUNCATE_REQUESTED"
        elif event_name == "TTS_TRUNCATE_REQUESTED":
            self.playback_phase = "TRUNCATE_REQUESTED"
        elif event_name == "TTS_TRUNCATED":
            self.playback_phase = "TRUNCATED"
        elif event_name == "WAITING_USER":
            self.turn_phase = "WAITING_USER"

        self.last_interaction_event_id = str(event["event_id"])
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
