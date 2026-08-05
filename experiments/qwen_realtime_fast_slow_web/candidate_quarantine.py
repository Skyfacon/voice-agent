"""Bounded, response-scoped quarantine for provider reply text and PCM."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class QuarantineLimits:
    max_responses: int = 2
    max_text_deltas: int = 32
    max_text_characters: int = 8_192
    max_audio_chunks: int = 96
    max_audio_bytes: int = 768_000

    def __post_init__(self) -> None:
        if min(
            self.max_responses,
            self.max_text_deltas,
            self.max_text_characters,
            self.max_audio_chunks,
            self.max_audio_bytes,
        ) < 1:
            raise ValueError("quarantine limits must be positive")


@dataclass(frozen=True, slots=True)
class QuarantinedCandidate:
    response_id: str
    provider_item_id: str
    turn_id: str
    utterance_id: str
    playback_epoch: int
    text_deltas: tuple[str, ...]
    audio_chunks: tuple[bytes, ...] = field(repr=False)
    text_characters: int = 0
    audio_bytes: int = 0
    overflowed: bool = False

    @property
    def text(self) -> str:
        return "".join(self.text_deltas)


@dataclass(slots=True)
class _Entry:
    response_id: str
    provider_item_id: str
    turn_id: str
    utterance_id: str
    playback_epoch: int
    text_deltas: list[str] = field(default_factory=list)
    audio_chunks: list[bytes] = field(default_factory=list, repr=False)
    text_characters: int = 0
    audio_bytes: int = 0
    overflowed: bool = False

    def snapshot(self) -> QuarantinedCandidate:
        return QuarantinedCandidate(
            response_id=self.response_id,
            provider_item_id=self.provider_item_id,
            turn_id=self.turn_id,
            utterance_id=self.utterance_id,
            playback_epoch=self.playback_epoch,
            text_deltas=tuple(self.text_deltas),
            audio_chunks=tuple(self.audio_chunks),
            text_characters=self.text_characters,
            audio_bytes=self.audio_bytes,
            overflowed=self.overflowed,
        )


class CandidateQuarantine:
    """In-memory candidate buffer that fails closed on every bound."""

    def __init__(self, limits: QuarantineLimits | None = None) -> None:
        self.limits = limits or QuarantineLimits()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self.discarded_responses = 0
        self.dropped_text_deltas = 0
        self.dropped_audio_chunks = 0
        self.dropped_audio_bytes = 0
        self.overflow_count = 0

    @property
    def active_response_ids(self) -> tuple[str, ...]:
        return tuple(self._entries)

    @property
    def total_audio_bytes(self) -> int:
        return sum(entry.audio_bytes for entry in self._entries.values())

    @property
    def total_text_characters(self) -> int:
        return sum(entry.text_characters for entry in self._entries.values())

    def start(
        self,
        *,
        response_id: str,
        provider_item_id: str,
        turn_id: str,
        utterance_id: str,
        playback_epoch: int,
    ) -> None:
        if not response_id or not provider_item_id or not turn_id or not utterance_id:
            raise ValueError("quarantine correlation identifiers are required")
        if (
            not isinstance(playback_epoch, int)
            or isinstance(playback_epoch, bool)
            or playback_epoch < 0
        ):
            raise ValueError("playback_epoch must be a non-negative integer")
        if response_id in self._entries:
            raise ValueError("response already exists in candidate quarantine")
        while len(self._entries) >= self.limits.max_responses:
            _, evicted = self._entries.popitem(last=False)
            self._record_discard(evicted)
        self._entries[response_id] = _Entry(
            response_id=response_id,
            provider_item_id=provider_item_id,
            turn_id=turn_id,
            utterance_id=utterance_id,
            playback_epoch=playback_epoch,
        )

    def append_text(self, response_id: str, delta: str) -> bool:
        entry = self._entries.get(response_id)
        if entry is None or not isinstance(delta, str) or not delta:
            self.dropped_text_deltas += 1
            return False
        if entry.overflowed:
            self.dropped_text_deltas += 1
            return False
        if (
            len(entry.text_deltas) >= self.limits.max_text_deltas
            or entry.text_characters + len(delta) > self.limits.max_text_characters
        ):
            self.dropped_text_deltas += 1
            self._overflow(entry)
            return False
        entry.text_deltas.append(delta)
        entry.text_characters += len(delta)
        return True

    def append_audio(self, response_id: str, pcm16le: bytes) -> bool:
        entry = self._entries.get(response_id)
        if (
            entry is None
            or not isinstance(pcm16le, bytes)
            or not pcm16le
            or len(pcm16le) % 2
        ):
            self.dropped_audio_chunks += 1
            if isinstance(pcm16le, bytes):
                self.dropped_audio_bytes += len(pcm16le)
            return False
        if entry.overflowed:
            self.dropped_audio_chunks += 1
            self.dropped_audio_bytes += len(pcm16le)
            return False
        if (
            len(entry.audio_chunks) >= self.limits.max_audio_chunks
            or entry.audio_bytes + len(pcm16le) > self.limits.max_audio_bytes
        ):
            self.dropped_audio_chunks += 1
            self.dropped_audio_bytes += len(pcm16le)
            self._overflow(entry)
            return False
        entry.audio_chunks.append(pcm16le)
        entry.audio_bytes += len(pcm16le)
        return True

    def snapshot(self, response_id: str) -> QuarantinedCandidate | None:
        entry = self._entries.get(response_id)
        return entry.snapshot() if entry is not None else None

    def release(
        self, response_id: str, *, expected_playback_epoch: int
    ) -> QuarantinedCandidate | None:
        if (
            not isinstance(expected_playback_epoch, int)
            or isinstance(expected_playback_epoch, bool)
            or expected_playback_epoch < 0
        ):
            raise ValueError("expected_playback_epoch must be a non-negative integer")
        entry = self._entries.pop(response_id, None)
        if entry is None:
            return None
        if entry.playback_epoch != expected_playback_epoch or entry.overflowed:
            self._record_discard(entry)
            return None
        return entry.snapshot()

    def discard(self, response_id: str, *, reason: str = "discarded") -> QuarantinedCandidate | None:
        del reason  # The reason belongs in bounded metadata, never in stored PCM.
        entry = self._entries.pop(response_id, None)
        if entry is None:
            return None
        self._record_discard(entry)
        return entry.snapshot()

    def clear(self, *, reason: str = "cleared") -> tuple[QuarantinedCandidate, ...]:
        del reason
        snapshots = tuple(entry.snapshot() for entry in self._entries.values())
        for entry in self._entries.values():
            self._record_discard(entry)
        self._entries.clear()
        return snapshots

    def counters(self) -> dict[str, int]:
        return {
            "active_responses": len(self._entries),
            "discarded_responses": self.discarded_responses,
            "dropped_text_deltas": self.dropped_text_deltas,
            "dropped_audio_chunks": self.dropped_audio_chunks,
            "dropped_audio_bytes": self.dropped_audio_bytes,
            "overflow_count": self.overflow_count,
            "quarantined_text_characters": self.total_text_characters,
            "quarantined_audio_bytes": self.total_audio_bytes,
        }

    def _overflow(self, entry: _Entry) -> None:
        self.overflow_count += 1
        self.dropped_text_deltas += len(entry.text_deltas)
        self.dropped_audio_chunks += len(entry.audio_chunks)
        self.dropped_audio_bytes += entry.audio_bytes
        entry.text_deltas.clear()
        entry.audio_chunks.clear()
        entry.text_characters = 0
        entry.audio_bytes = 0
        entry.overflowed = True

    def _record_discard(self, entry: _Entry) -> None:
        self.discarded_responses += 1
        self.dropped_text_deltas += len(entry.text_deltas)
        self.dropped_audio_chunks += len(entry.audio_chunks)
        self.dropped_audio_bytes += entry.audio_bytes


__all__ = [
    "CandidateQuarantine",
    "QuarantinedCandidate",
    "QuarantineLimits",
]
