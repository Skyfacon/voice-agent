"""Experiment-local realtime evidence and correlation contracts.

These dataclasses bind provider-local identifiers to canonical turn metadata.
They are not canonical events and never carry PCM or raw provider payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping


ROUTE_HINTS = frozenset(
    {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"}
)
TASK_FOCUS_HINTS = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "FOREGROUND_CHAT",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "NON_ASSISTANT",
        "AMBIGUOUS",
    }
)
FOREGROUND_ACTS = frozenset({"ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY"})
RISK_CLASSES = frozenset({"LOW", "MEDIUM", "HIGH"})


@dataclass(frozen=True, slots=True)
class ProviderRouteProposal:
    scenario: str
    response_id: str
    provider_item_id: str
    route_hint: str
    task_focus_hint: str
    foreground_act: str
    risk_class: str
    confidence: float
    output_mode: str = "mock"
    task_like: bool = False
    complexity_hint: str = "LOW"
    evidence_uncertainty: str = "LOW"
    risk_tags: tuple[str, ...] = ()
    reply_candidate_text: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for field_name in ("scenario", "response_id", "provider_item_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} is required")
        if self.route_hint not in ROUTE_HINTS:
            raise ValueError("route_hint is not an existing Router decision")
        if self.task_focus_hint not in TASK_FOCUS_HINTS:
            raise ValueError("task_focus_hint is not an ADR-006 focus value")
        if self.foreground_act not in FOREGROUND_ACTS:
            raise ValueError("foreground_act is invalid")
        if self.risk_class not in RISK_CLASSES:
            raise ValueError("risk_class is invalid")
        if (
            not isinstance(self.confidence, (int, float))
            or isinstance(self.confidence, bool)
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("confidence must be in [0, 1]")
        if self.output_mode not in {"real", "mock", "fallback", "degraded"}:
            raise ValueError("output_mode must be real, mock, fallback, or degraded")
        if not isinstance(self.task_like, bool):
            raise ValueError("task_like must be boolean")
        if self.complexity_hint not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("complexity_hint is invalid")
        if self.evidence_uncertainty not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("evidence_uncertainty is invalid")
        if (
            not isinstance(self.risk_tags, tuple)
            or len(self.risk_tags) > 12
            or any(not isinstance(tag, str) or not tag for tag in self.risk_tags)
        ):
            raise ValueError("risk_tags are invalid")
        if self.reply_candidate_text is not None and (
            not isinstance(self.reply_candidate_text, str)
            or not self.reply_candidate_text.strip()
            or len(self.reply_candidate_text) > 512
        ):
            raise ValueError("reply_candidate_text is invalid")

    def with_local_focus_override(
        self, *, route_hint: str, task_focus_hint: str
    ) -> "ProviderRouteProposal":
        """Return contextual evidence for Router without mutating task state."""

        return replace(self, route_hint=route_hint, task_focus_hint=task_focus_hint)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "response_id": self.response_id,
            "provider_item_id": self.provider_item_id,
            "route_hint": self.route_hint,
            "task_focus_hint": self.task_focus_hint,
            "foreground_act": self.foreground_act,
            "risk_class": self.risk_class,
            "confidence": float(self.confidence),
            "output_mode": self.output_mode,
            "task_like": self.task_like,
            "complexity_hint": self.complexity_hint,
            "evidence_uncertainty": self.evidence_uncertainty,
            "risk_tags": list(self.risk_tags),
            "reply_candidate_present": self.reply_candidate_text is not None,
            "reply_candidate_chars": (
                len(self.reply_candidate_text)
                if self.reply_candidate_text is not None
                else 0
            ),
        }


@dataclass(frozen=True, slots=True)
class RealtimeTurnEvidenceBundle:
    """One post-commit binding passed into Router/Gate integration."""

    turn_id: str
    utterance_id: str
    audio_span_id: str
    provider_item_id: str
    response_id: str
    playback_epoch: int
    turn_committed_event: Mapping[str, Any]
    asr_frame_event: Mapping[str, Any]
    proposal: ProviderRouteProposal

    def __post_init__(self) -> None:
        for field_name in (
            "turn_id",
            "utterance_id",
            "audio_span_id",
            "provider_item_id",
            "response_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} is required")
        if (
            not isinstance(self.playback_epoch, int)
            or isinstance(self.playback_epoch, bool)
            or self.playback_epoch < 0
        ):
            raise ValueError("playback_epoch must be a non-negative integer")
        if self.turn_committed_event.get("event_name") != "TURN_INGRESS_COMMITTED":
            raise ValueError("turn_committed_event binding is invalid")
        if self.asr_frame_event.get("event_name") not in {
            "MOCK_ASR_FRAME_EMITTED",
            "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        }:
            raise ValueError("asr_frame_event binding is invalid")
        for event in (self.turn_committed_event, self.asr_frame_event):
            if event.get("turn_id") != self.turn_id:
                raise ValueError("evidence turn_id mismatch")
            if event.get("utterance_id") != self.utterance_id:
                raise ValueError("evidence utterance_id mismatch")
            if event.get("audio_span_id") not in (None, self.audio_span_id):
                raise ValueError("evidence audio_span_id mismatch")
        if self.proposal.provider_item_id != self.provider_item_id:
            raise ValueError("proposal provider_item_id mismatch")
        if self.proposal.response_id != self.response_id:
            raise ValueError("proposal response_id mismatch")

    def to_metadata(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "utterance_id": self.utterance_id,
            "audio_span_id": self.audio_span_id,
            "provider_item_id": self.provider_item_id,
            "response_id": self.response_id,
            "playback_epoch": self.playback_epoch,
            "scenario": self.proposal.scenario,
            "route_hint": self.proposal.route_hint,
            "task_focus_hint": self.proposal.task_focus_hint,
        }


__all__ = [
    "FOREGROUND_ACTS",
    "ProviderRouteProposal",
    "RealtimeTurnEvidenceBundle",
    "RISK_CLASSES",
    "ROUTE_HINTS",
    "TASK_FOCUS_HINTS",
]
