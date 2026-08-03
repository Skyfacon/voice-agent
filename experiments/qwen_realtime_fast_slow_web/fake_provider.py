"""Deterministic provider-free Qwen-style Duplex/ASR/FastInteraction fake.

PCM is inspected transiently for a bounded energy check and is never retained.
All generated text, identifiers, and audio are synthetic fixtures.
"""

from __future__ import annotations

import asyncio
import math
import sys
from array import array
from dataclasses import dataclass, field
from typing import Any

from .browser_protocol import FAKE_SCENARIOS, OUTPUT_SAMPLE_RATE
from .capability_profile import CapabilityProfile, fake_capability_profile


class FakeProviderDisconnected(RuntimeError):
    def __init__(self, code: str = "fake_provider_disconnected") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class FakeProviderConfig:
    output_queue_events: int = 64
    auto_stop_after_voiced_frames: int = 6
    silence_frames_to_stop: int = 2
    transcript_delta_every_frames: int = 2
    response_audio_chunks: int = 6
    response_audio_chunk_ms: int = 40
    event_delay_seconds: float = 0.001
    voice_threshold: int = 350
    late_audio_after_cancel: bool = True

    def __post_init__(self) -> None:
        if self.output_queue_events < 4:
            raise ValueError("output_queue_events must be at least four")
        if min(
            self.auto_stop_after_voiced_frames,
            self.silence_frames_to_stop,
            self.transcript_delta_every_frames,
            self.response_audio_chunks,
            self.response_audio_chunk_ms,
        ) < 1:
            raise ValueError("fake frame and chunk values must be positive")
        if self.event_delay_seconds < 0:
            raise ValueError("event_delay_seconds must not be negative")
        if not 0 <= self.voice_threshold <= 32_767:
            raise ValueError("voice_threshold is outside PCM16 range")


@dataclass(frozen=True, slots=True)
class FakeProviderEvent:
    type: str
    output_mode: str = "mock"
    scenario: str | None = None
    turn_ref: str | None = None
    response_id: str | None = None
    provider_item_id: str | None = None
    text: str | None = None
    audio: bytes | None = field(default=None, repr=False)
    route_hint: str | None = None
    task_focus_hint: str | None = None
    foreground_act: str | None = None
    risk_class: str | None = None
    confidence: float | None = None
    status: str | None = None
    error_code: str | None = None
    terminal: bool = False
    interrupt_only: bool = False

    def to_safe_metadata(self) -> dict[str, Any]:
        """Return bounded metadata; audio and transcript content are omitted."""

        fields = {
            "type": self.type,
            "output_mode": self.output_mode,
            "scenario": self.scenario,
            "turn_ref": self.turn_ref,
            "response_id": self.response_id,
            "provider_item_id": self.provider_item_id,
            "route_hint": self.route_hint,
            "task_focus_hint": self.task_focus_hint,
            "foreground_act": self.foreground_act,
            "risk_class": self.risk_class,
            "confidence": self.confidence,
            "status": self.status,
            "error_code": self.error_code,
            "terminal": self.terminal,
            "interrupt_only": self.interrupt_only,
            "audio_bytes": len(self.audio) if self.audio is not None else 0,
        }
        return {key: value for key, value in fields.items() if value is not None}


_SCENARIO_PROPOSALS: dict[str, tuple[str, str, str, str, float]] = {
    "fast": ("FAST_ONLY", "FOREGROUND_CHAT", "ANSWER", "LOW", 0.96),
    "spawn": ("SPAWN_SLOW_TASK", "NEW_TASK_CANDIDATE", "ANSWER", "LOW", 0.96),
    "patch": (
        "PATCH_ACTIVE_SLOW_TASK",
        "ACTIVE_TASK_PATCH",
        "ANSWER",
        "LOW",
        0.96,
    ),
    "ignore": ("IGNORE", "NON_ASSISTANT", "SILENCE", "LOW", 0.99),
    "ambiguous": ("FAST_ONLY", "AMBIGUOUS", "ANSWER", "LOW", 0.55),
    "cancel": (
        "PATCH_ACTIVE_SLOW_TASK",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "CLARIFY",
        "MEDIUM",
        0.94,
    ),
    "confirm": (
        "PATCH_ACTIVE_SLOW_TASK",
        "ACTIVE_TASK_PATCH",
        "ACK_PATCH",
        "LOW",
        0.99,
    ),
    "reject_confirmation": (
        "PATCH_ACTIVE_SLOW_TASK",
        "ACTIVE_TASK_PATCH",
        "ACK_PATCH",
        "LOW",
        0.99,
    ),
    "late_audio": ("FAST_ONLY", "FOREGROUND_CHAT", "ANSWER", "LOW", 0.96),
}

_SYNTHETIC_USER_TEXT = {
    "fast": "[synthetic] hello assistant",
    "spawn": "[synthetic] prepare a multi-step plan",
    "patch": "[synthetic] add the red constraint",
    "ignore": "[synthetic] background speech not addressed to assistant",
    "ambiguous": "[synthetic] maybe continue that",
    "cancel": "[synthetic] cancel the active task",
    "confirm": "[synthetic] yes confirm",
    "reject_confirmation": "[synthetic] no keep the task",
    "late_audio": "[synthetic] late audio epoch check",
}

_SYNTHETIC_ASSISTANT_TEXT = {
    "fast": "Synthetic fast reply.",
    "spawn": "Uncommitted provider slow-task answer.",
    "patch": "Uncommitted provider patch answer.",
    "ignore": "Uncommitted provider background answer.",
    "ambiguous": "Uncommitted provider ambiguous answer.",
    "cancel": "Uncommitted provider cancel answer.",
    "confirm": "Uncommitted provider confirmation answer.",
    "reject_confirmation": "Uncommitted provider rejection answer.",
    "late_audio": "Synthetic response interrupted before late audio.",
}


class FakeRealtimeProvider:
    """One bounded synthetic provider session.

    The coordinator is the lifecycle owner.  This fake only emits normalized
    provider evidence and honors response cancellation.
    """

    def __init__(self, config: FakeProviderConfig | None = None) -> None:
        self.config = config or FakeProviderConfig()
        self._events: asyncio.Queue[FakeProviderEvent] = asyncio.Queue(
            maxsize=self.config.output_queue_events
        )
        self._profile = fake_capability_profile()
        self._connected = False
        self._closed = False
        self._in_speech = False
        self._awaiting_silence_reset = False
        self._voiced_frames = 0
        self._silence_frames = 0
        self._turn_index = 0
        self._response_index = 0
        self._response_task: asyncio.Task[None] | None = None
        self._active_response_id: str | None = None
        self._response_cancel = asyncio.Event()
        self.default_scenario = "fast"

        self.sent_audio_frames = 0
        self.sent_audio_bytes = 0
        self.cancel_count = 0
        self.dropped_provider_events = 0

    @property
    def profile(self) -> CapabilityProfile:
        return self._profile

    @property
    def response_active(self) -> bool:
        return self._active_response_id is not None

    @property
    def active_response_id(self) -> str | None:
        return self._active_response_id

    @property
    def pending_event_count(self) -> int:
        return self._events.qsize()

    async def connect(self) -> None:
        if self._closed:
            raise FakeProviderDisconnected("fake_provider_closed")
        if self._connected:
            return
        self._connected = True
        await self._emit(FakeProviderEvent(type="session.created"))
        await self._emit(FakeProviderEvent(type="session.updated"))

    def configure(self, *, default_scenario: str | None = None) -> None:
        if default_scenario is not None:
            self.default_scenario = _scenario(default_scenario)

    async def send_audio(self, pcm16le: bytes) -> None:
        self._require_connected()
        if not isinstance(pcm16le, bytes) or not pcm16le or len(pcm16le) % 2:
            raise ValueError("invalid_pcm_frame")
        self.sent_audio_frames += 1
        self.sent_audio_bytes += len(pcm16le)

        voiced = _pcm_has_voice(pcm16le, self.config.voice_threshold)
        if self._awaiting_silence_reset:
            if not voiced:
                self._awaiting_silence_reset = False
            return
        if voiced:
            self._silence_frames = 0
            if not self._in_speech:
                self._in_speech = True
                self._voiced_frames = 0
                self._turn_index += 1
                await self._emit(
                    FakeProviderEvent(
                        type="speech.started",
                        scenario=self.default_scenario,
                        turn_ref=f"provider-turn-{self._turn_index:04d}",
                    )
                )
            self._voiced_frames += 1
            if self._voiced_frames % self.config.transcript_delta_every_frames == 0:
                await self._emit(
                    FakeProviderEvent(
                        type="user.transcript.delta",
                        scenario=self.default_scenario,
                        turn_ref=f"provider-turn-{self._turn_index:04d}",
                        text="[synthetic] partial utterance",
                    )
                )
            if self._voiced_frames >= self.config.auto_stop_after_voiced_frames:
                await self.finish_turn()
            return

        if self._in_speech:
            self._silence_frames += 1
            if self._silence_frames >= self.config.silence_frames_to_stop:
                await self.finish_turn()

    async def finish_turn(self, scenario: str | None = None) -> bool:
        self._require_connected()
        if not self._in_speech:
            return False
        selected = _scenario(scenario or self.default_scenario)
        self._in_speech = False
        self._awaiting_silence_reset = True
        self._voiced_frames = 0
        self._silence_frames = 0
        turn_ref = f"provider-turn-{self._turn_index:04d}"
        await self._emit(
            FakeProviderEvent(type="speech.stopped", scenario=selected, turn_ref=turn_ref)
        )
        await self._emit(
            FakeProviderEvent(
                type="user.transcript.final",
                scenario=selected,
                turn_ref=turn_ref,
                text=_SYNTHETIC_USER_TEXT[selected],
            )
        )
        await self._start_response(selected, turn_ref=turn_ref)
        return True

    async def trigger_scenario(
        self,
        scenario: str,
        *,
        confidence: float | None = None,
        risk_class: str | None = None,
        foreground_act: str | None = None,
    ) -> None:
        """Start one complete synthetic turn without microphone PCM."""

        self._require_connected()
        selected = _scenario(scenario)
        if selected == "provider_error":
            await self.trigger_error()
            return
        if selected == "provider_disconnect":
            await self.trigger_disconnect()
            return
        await self._finish_existing_response()
        self._turn_index += 1
        turn_ref = f"provider-turn-{self._turn_index:04d}"
        await self._emit(
            FakeProviderEvent(type="speech.started", scenario=selected, turn_ref=turn_ref)
        )
        await self._emit(
            FakeProviderEvent(
                type="user.transcript.delta",
                scenario=selected,
                turn_ref=turn_ref,
                text="[synthetic] partial utterance",
            )
        )
        await self._emit(
            FakeProviderEvent(type="speech.stopped", scenario=selected, turn_ref=turn_ref)
        )
        await self._emit(
            FakeProviderEvent(
                type="user.transcript.final",
                scenario=selected,
                turn_ref=turn_ref,
                text=_SYNTHETIC_USER_TEXT[selected],
            )
        )
        await self._start_response(
            selected,
            turn_ref=turn_ref,
            confidence=confidence,
            risk_class=risk_class,
            foreground_act=foreground_act,
        )

    async def recv_event(self) -> FakeProviderEvent:
        if self._closed and self._events.empty():
            raise FakeProviderDisconnected("fake_provider_closed")
        return await self._events.get()

    def event_processed(self) -> None:
        self._events.task_done()

    async def wait_response_complete(self) -> None:
        task = self._response_task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def wait_events_drained(self) -> None:
        await self._events.join()

    async def cancel_response(self) -> bool:
        if not self.response_active or self._response_cancel.is_set():
            return False
        self.cancel_count += 1
        self._response_cancel.set()
        return True

    async def inject_event(self, event: FakeProviderEvent) -> None:
        self._require_connected()
        await self._emit(event)

    async def trigger_error(
        self, code: str = "synthetic_provider_error", *, terminal: bool = False
    ) -> None:
        self._require_connected()
        await self._emit(
            FakeProviderEvent(
                type="provider.error",
                output_mode="degraded",
                error_code=_safe_provider_error_code(code),
                terminal=terminal,
            )
        )

    async def trigger_disconnect(self) -> None:
        if not self._connected or self._closed:
            return
        self._connected = False
        self._profile = self._profile.with_health("disconnected")
        await self._emit(
            FakeProviderEvent(
                type="provider.disconnected",
                output_mode="degraded",
                error_code="synthetic_provider_disconnect",
                terminal=True,
            )
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connected = False
        self._response_cancel.set()
        task, self._response_task = self._response_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._active_response_id = None
        while True:
            try:
                self._events.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._events.task_done()
        self._profile = self._profile.with_health("closed")

    async def _start_response(
        self,
        scenario: str,
        *,
        turn_ref: str,
        confidence: float | None = None,
        risk_class: str | None = None,
        foreground_act: str | None = None,
    ) -> None:
        await self._finish_existing_response()
        self._response_cancel = asyncio.Event()
        self._response_task = asyncio.create_task(
            self._stream_response(
                scenario,
                turn_ref=turn_ref,
                confidence=confidence,
                risk_class=risk_class,
                foreground_act=foreground_act,
            ),
            name="qwen-fast-slow-fake-response",
        )
        await asyncio.sleep(0)

    async def _finish_existing_response(self) -> None:
        task = self._response_task
        if task is None or task.done():
            return
        await self.cancel_response()
        await asyncio.gather(task, return_exceptions=True)

    async def _stream_response(
        self,
        scenario: str,
        *,
        turn_ref: str,
        confidence: float | None,
        risk_class: str | None,
        foreground_act: str | None,
    ) -> None:
        self._response_index += 1
        response_id = f"provider-response-{self._response_index:04d}"
        provider_item_id = f"provider-item-{self._response_index:04d}"
        self._active_response_id = response_id
        try:
            await self._emit(
                FakeProviderEvent(
                    type="response.created",
                    scenario=scenario,
                    turn_ref=turn_ref,
                    response_id=response_id,
                    provider_item_id=provider_item_id,
                )
            )
            assistant_text = _SYNTHETIC_ASSISTANT_TEXT[scenario]
            text_chunks = _text_chunks(assistant_text)
            for index in range(self.config.response_audio_chunks):
                await self._delay()
                if index < len(text_chunks):
                    await self._emit(
                        FakeProviderEvent(
                            type="assistant.transcript.delta",
                            scenario=scenario,
                            response_id=response_id,
                            provider_item_id=provider_item_id,
                            text=text_chunks[index],
                        )
                    )
                await self._emit(
                    FakeProviderEvent(
                        type="response.audio.delta",
                        scenario=scenario,
                        response_id=response_id,
                        provider_item_id=provider_item_id,
                        audio=_sine_pcm_chunk(
                            index=index,
                            duration_ms=self.config.response_audio_chunk_ms,
                        ),
                    )
                )
            await self._emit(
                FakeProviderEvent(
                    type="assistant.transcript.done",
                    scenario=scenario,
                    response_id=response_id,
                    provider_item_id=provider_item_id,
                    text=assistant_text,
                )
            )

            route_hint, focus_hint, act, risk, default_confidence = _SCENARIO_PROPOSALS[
                scenario
            ]
            await self._emit(
                FakeProviderEvent(
                    type="route.proposed",
                    scenario=scenario,
                    response_id=response_id,
                    provider_item_id=provider_item_id,
                    route_hint=route_hint,
                    task_focus_hint=focus_hint,
                    foreground_act=foreground_act or act,
                    risk_class=risk_class or risk,
                    confidence=default_confidence if confidence is None else confidence,
                )
            )
            await self._delay()

            if scenario == "late_audio":
                await self._emit(
                    FakeProviderEvent(
                        type="speech.started",
                        scenario=scenario,
                        turn_ref=f"{turn_ref}-interrupt",
                        interrupt_only=True,
                    )
                )
                await self._delay()

            if self._response_cancel.is_set() or scenario == "late_audio":
                if self.config.late_audio_after_cancel:
                    await self._emit(
                        FakeProviderEvent(
                            type="response.audio.delta",
                            scenario=scenario,
                            response_id=response_id,
                            provider_item_id=provider_item_id,
                            audio=_sine_pcm_chunk(
                                index=self.config.response_audio_chunks,
                                duration_ms=self.config.response_audio_chunk_ms,
                            ),
                        )
                    )
                await self._emit(
                    FakeProviderEvent(
                        type="response.done",
                        scenario=scenario,
                        response_id=response_id,
                        provider_item_id=provider_item_id,
                        status="cancelled",
                    )
                )
                return

            await self._emit(
                FakeProviderEvent(
                    type="response.done",
                    scenario=scenario,
                    response_id=response_id,
                    provider_item_id=provider_item_id,
                    status="completed",
                )
            )
        finally:
            if self._active_response_id == response_id:
                self._active_response_id = None

    async def _delay(self) -> None:
        if self.config.event_delay_seconds:
            await asyncio.sleep(self.config.event_delay_seconds)
        else:
            await asyncio.sleep(0)

    async def _emit(self, event: FakeProviderEvent) -> None:
        if self._closed:
            return
        # Bounded backpressure is intentional.  Provider events are never
        # copied into an unbounded staging list.
        await self._events.put(event)

    def _require_connected(self) -> None:
        if not self._connected or self._closed:
            raise FakeProviderDisconnected("fake_provider_not_connected")


def _scenario(value: str) -> str:
    if value not in FAKE_SCENARIOS:
        raise ValueError("unsupported_fake_scenario")
    return value


def _pcm_has_voice(pcm16le: bytes, threshold: int) -> bool:
    for offset in range(0, len(pcm16le), 2):
        sample = int.from_bytes(pcm16le[offset : offset + 2], "little", signed=True)
        if abs(sample) > threshold:
            return True
    return False


def _sine_pcm_chunk(*, index: int, duration_ms: int) -> bytes:
    sample_count = OUTPUT_SAMPLE_RATE * duration_ms // 1_000
    start_sample = index * sample_count
    samples = array(
        "h",
        (
            int(4_000 * math.sin(2.0 * math.pi * 440.0 * sample / OUTPUT_SAMPLE_RATE))
            for sample in range(start_sample, start_sample + sample_count)
        ),
    )
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _text_chunks(text: str) -> tuple[str, ...]:
    words = text.split(" ")
    return tuple(f"{word} " if index < len(words) - 1 else word for index, word in enumerate(words))


def _safe_provider_error_code(value: object) -> str:
    allowed = {
        "synthetic_provider_error",
        "synthetic_provider_timeout",
        "synthetic_rate_limit",
    }
    return value if isinstance(value, str) and value in allowed else "synthetic_provider_error"


__all__ = [
    "FakeProviderConfig",
    "FakeProviderDisconnected",
    "FakeProviderEvent",
    "FakeRealtimeProvider",
]
