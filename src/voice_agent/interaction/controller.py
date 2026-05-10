from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.interaction.policy import (
    AUDIO_INPUT_MODALITY,
    ASSUMED_CLOSED,
    ASSUMED_DIRECTED,
    INGRESS_ACCEPTED,
    INGRESS_COMMITTED,
    MOCK_AUDIO_ACCEPTANCE_BASIS,
    TEXT_INPUT_MODALITY,
    TURN_PHASE_COLLECTING_INPUT,
)
from voice_agent.state.playback_state import PlaybackState


@dataclass(frozen=True)
class TextIngressCommitResult:
    turn_opened: dict[str, Any]
    turn_accepted: dict[str, Any]
    turn_committed: dict[str, Any]


@dataclass(frozen=True)
class AudioIngressCommitResult:
    turn_accepted: dict[str, Any]
    turn_committed: dict[str, Any]


@dataclass(frozen=True)
class BargeInTruncateRequestResult:
    interrupt_candidate: dict[str, Any]
    truncate_requested: dict[str, Any]


MOCK_BARGE_IN_POLICY_REASON = "mock_barge_in_confidence_allows_truncate"


class InteractionController:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def commit_text_ingress(
        self,
        text_event: Mapping[str, Any],
        *,
        turn_id: str,
        utterance_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> TextIngressCommitResult:
        _validate_text_event(text_event)
        input_span_id = str(text_event["input_span_id"])
        text_span_id = str(text_event["text_span_id"])

        turn_opened = self._journal.append(
            event_name="TURN_OPENED",
            event_id=f"evt_{turn_id}_opened",
            source_module="interaction_controller",
            caused_by_event_id=str(text_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            turn_id=turn_id,
            input_span_id=input_span_id,
            text_span_id=text_span_id,
            audio_span_id=None,
            turn_phase=TURN_PHASE_COLLECTING_INPUT,
            input_modality=TEXT_INPUT_MODALITY,
        )
        turn_accepted = self._journal.append(
            event_name="TURN_INGRESS_ACCEPTED",
            event_id=f"evt_{turn_id}_ingress_accepted",
            source_module="interaction_controller",
            caused_by_event_id=str(turn_opened["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 1,
            created_wall_clock_ms=created_wall_clock_ms + 1,
            trace_redaction_level="metadata_only",
            turn_id=turn_id,
            input_span_id=input_span_id,
            text_span_id=text_span_id,
            audio_span_id=None,
            ingress_outcome=INGRESS_ACCEPTED,
        )
        turn_committed = self._journal.append(
            event_name="TURN_INGRESS_COMMITTED",
            event_id=f"evt_{turn_id}_ingress_committed",
            source_module="interaction_controller",
            caused_by_event_id=str(turn_accepted["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 2,
            created_wall_clock_ms=created_wall_clock_ms + 2,
            trace_redaction_level="metadata_only",
            turn_id=turn_id,
            utterance_id=utterance_id,
            input_span_id=input_span_id,
            text_span_id=text_span_id,
            audio_span_id=None,
            input_modality=TEXT_INPUT_MODALITY,
            directedness=ASSUMED_DIRECTED,
            semantic_close=ASSUMED_CLOSED,
            ingress_outcome=INGRESS_COMMITTED,
        )

        return TextIngressCommitResult(
            turn_opened=turn_opened,
            turn_accepted=turn_accepted,
            turn_committed=turn_committed,
        )

    def open_audio_turn(
        self,
        speech_start_event: Mapping[str, Any],
        *,
        turn_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> dict[str, Any]:
        _validate_speech_start_event(speech_start_event)
        audio_span_id = str(speech_start_event["audio_span_id"])
        fields: dict[str, Any] = {
            "turn_id": turn_id,
            "audio_span_id": audio_span_id,
            "turn_phase": TURN_PHASE_COLLECTING_INPUT,
            "input_modality": AUDIO_INPUT_MODALITY,
        }
        input_span_id = speech_start_event.get("input_span_id")
        if input_span_id is not None:
            fields["input_span_id"] = str(input_span_id)

        return self._journal.append(
            event_name="TURN_OPENED",
            event_id=f"evt_{turn_id}_opened",
            source_module="interaction_controller",
            caused_by_event_id=str(speech_start_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            **fields,
        )

    def commit_audio_ingress(
        self,
        speech_end_event: Mapping[str, Any],
        *,
        turn_id: str,
        utterance_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> AudioIngressCommitResult:
        _validate_speech_end_event(speech_end_event)
        audio_span_id = str(speech_end_event["audio_span_id"])
        fields: dict[str, Any] = {
            "turn_id": turn_id,
            "audio_span_id": audio_span_id,
            "acceptance_basis": MOCK_AUDIO_ACCEPTANCE_BASIS,
        }
        input_span_id = speech_end_event.get("input_span_id")
        if input_span_id is not None:
            fields["input_span_id"] = str(input_span_id)

        turn_accepted = self._journal.append(
            event_name="TURN_INGRESS_ACCEPTED",
            event_id=f"evt_{turn_id}_ingress_accepted",
            source_module="interaction_controller",
            caused_by_event_id=str(speech_end_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            ingress_outcome=INGRESS_ACCEPTED,
            **fields,
        )
        turn_committed = self._journal.append(
            event_name="TURN_INGRESS_COMMITTED",
            event_id=f"evt_{turn_id}_ingress_committed",
            source_module="interaction_controller",
            caused_by_event_id=str(turn_accepted["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 1,
            created_wall_clock_ms=created_wall_clock_ms + 1,
            trace_redaction_level="metadata_only",
            utterance_id=utterance_id,
            input_modality=AUDIO_INPUT_MODALITY,
            directedness=ASSUMED_DIRECTED,
            semantic_close=ASSUMED_CLOSED,
            ingress_outcome=INGRESS_COMMITTED,
            **fields,
        )

        return AudioIngressCommitResult(
            turn_accepted=turn_accepted,
            turn_committed=turn_committed,
        )

    def request_truncate_for_barge_in(
        self,
        barge_in_candidate_event: Mapping[str, Any],
        *,
        interrupt_event_id: str,
        truncate_request_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        cutoff_playback_offset_ms: int,
    ) -> BargeInTruncateRequestResult:
        _validate_barge_in_candidate_event(barge_in_candidate_event)
        _validate_non_negative_offset(cutoff_playback_offset_ms, field_name="cutoff_playback_offset_ms")

        audio_span_id = str(barge_in_candidate_event["audio_span_id"])
        playback_span_id = str(barge_in_candidate_event["playback_span_id"])
        candidate_playback_offset_ms = int(barge_in_candidate_event["playback_offset_ms"])
        _validate_active_playback_span(self._journal.events(), playback_span_id)

        confidence_summary = {
            "echo_likelihood": barge_in_candidate_event["echo_likelihood"],
            "vad_confidence": barge_in_candidate_event["vad_confidence"],
            "barge_in_confidence": barge_in_candidate_event["barge_in_confidence"],
        }
        interrupt_candidate = self._journal.append(
            event_name="INTERRUPT_CANDIDATE",
            event_id=interrupt_event_id,
            source_module="interaction_controller",
            caused_by_event_id=str(barge_in_candidate_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            audio_span_id=audio_span_id,
            playback_span_id=playback_span_id,
            playback_offset_ms=candidate_playback_offset_ms,
            policy_reason=MOCK_BARGE_IN_POLICY_REASON,
            confidence_summary=confidence_summary,
        )
        truncate_requested = self._journal.append(
            event_name="TTS_TRUNCATE_REQUESTED",
            event_id=truncate_request_event_id,
            source_module="interaction_controller",
            caused_by_event_id=str(interrupt_candidate["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            audio_span_id=audio_span_id,
            playback_span_id=playback_span_id,
            cutoff_playback_offset_ms=cutoff_playback_offset_ms,
            interrupt_candidate_event_id=str(interrupt_candidate["event_id"]),
        )

        return BargeInTruncateRequestResult(
            interrupt_candidate=interrupt_candidate,
            truncate_requested=truncate_requested,
        )


def _validate_text_event(text_event: Mapping[str, Any]) -> None:
    if text_event.get("event_name") != "TEXT_INPUT_RECEIVED":
        raise ValueError("commit_text_ingress requires a TEXT_INPUT_RECEIVED event")
    if text_event.get("input_modality") != TEXT_INPUT_MODALITY:
        raise ValueError("commit_text_ingress only accepts input_modality=text")
    if text_event.get("audio_span_id") is not None:
        raise ValueError("text ingress must not have an audio_span_id")


def _validate_speech_start_event(speech_start_event: Mapping[str, Any]) -> None:
    if speech_start_event.get("event_name") != "SPEECH_START_DETECTED":
        raise ValueError("open_audio_turn requires a SPEECH_START_DETECTED event")
    if not speech_start_event.get("audio_span_id"):
        raise ValueError("SPEECH_START_DETECTED must include audio_span_id")


def _validate_speech_end_event(speech_end_event: Mapping[str, Any]) -> None:
    if speech_end_event.get("event_name") != "SPEECH_END_DETECTED":
        raise ValueError("commit_audio_ingress requires a SPEECH_END_DETECTED event")
    if not speech_end_event.get("audio_span_id"):
        raise ValueError("SPEECH_END_DETECTED must include audio_span_id")


def _validate_barge_in_candidate_event(barge_in_candidate_event: Mapping[str, Any]) -> None:
    if barge_in_candidate_event.get("event_name") != "BARGE_IN_CANDIDATE":
        raise ValueError("request_truncate_for_barge_in requires a BARGE_IN_CANDIDATE event")
    for field in (
        "event_id",
        "audio_span_id",
        "playback_span_id",
        "playback_offset_ms",
        "echo_likelihood",
        "vad_confidence",
        "barge_in_confidence",
    ):
        if barge_in_candidate_event.get(field) in (None, ""):
            raise ValueError(f"BARGE_IN_CANDIDATE must include {field}")
    _validate_non_negative_offset(barge_in_candidate_event["playback_offset_ms"], field_name="playback_offset_ms")


def _validate_active_playback_span(events: list[dict[str, Any]], playback_span_id: str) -> None:
    playback_state = PlaybackState()
    for event in events:
        playback_state.reduce_event(event)
    if playback_state.current_playback_span_id != playback_span_id or playback_state.phase != "PLAYING":
        raise ValueError("BARGE_IN_CANDIDATE requires active playback before requesting truncate")


def _validate_non_negative_offset(value: object, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
