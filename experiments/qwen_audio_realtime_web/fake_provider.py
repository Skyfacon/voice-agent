"""Deterministic provider-free Qwen realtime simulation.

The fake retains counters and small control state only.  Incoming PCM is
inspected transiently for an energy threshold and is never stored.
"""

from __future__ import annotations

import asyncio
import math
import sys
from array import array
from dataclasses import dataclass

from .capability_profile import CapabilityProfile, fake_capability_profile
from .provider_adapter import (
    NormalizedProviderEvent,
    ProviderDisconnected,
    SafeProviderError,
)


@dataclass(frozen=True, slots=True)
class FakeProviderConfig:
    auto_stop_after_voiced_frames: int = 6
    silence_frames_to_stop: int = 2
    transcript_delta_every_frames: int = 2
    event_delay_seconds: float = 0.02
    response_audio_chunks: int = 10
    response_audio_chunk_ms: int = 40
    output_queue_events: int = 64
    voice_threshold: int = 350
    late_audio_after_cancel: bool = True

    def __post_init__(self) -> None:
        positive = (
            self.auto_stop_after_voiced_frames,
            self.silence_frames_to_stop,
            self.transcript_delta_every_frames,
            self.response_audio_chunks,
            self.response_audio_chunk_ms,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("fake provider frame/chunk values must be positive")
        if self.event_delay_seconds < 0:
            raise ValueError("event_delay_seconds must not be negative")
        if self.output_queue_events < 4:
            raise ValueError("output_queue_events must be at least four")
        if self.voice_threshold < 0 or self.voice_threshold > 32_767:
            raise ValueError("voice_threshold is outside PCM16 range")


class FakeRealtimeProvider:
    """One bounded, synthetic realtime session implementing provider contract."""

    def __init__(self, config: FakeProviderConfig | None = None) -> None:
        self.config = config or FakeProviderConfig()
        self._events: asyncio.Queue[NormalizedProviderEvent] = asyncio.Queue(
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
        self._active_response_ref: str | None = None
        self._response_task: asyncio.Task[None] | None = None
        self._response_cancel = asyncio.Event()
        self.sent_audio_frames = 0
        self.sent_audio_bytes = 0
        self.cancel_count = 0

    @property
    def profile(self) -> CapabilityProfile:
        return self._profile

    @property
    def response_active(self) -> bool:
        return self._active_response_ref is not None

    async def connect(self) -> None:
        if self._closed:
            raise ProviderDisconnected("fake_provider_closed")
        if self._connected:
            return
        self._connected = True
        await self._emit(
            NormalizedProviderEvent(
                type="session.created",
                output_mode="mock",
                session_ref="session-synthetic",
            )
        )
        await self._emit(
            NormalizedProviderEvent(
                type="session.updated",
                output_mode="mock",
                session_ref="session-synthetic",
            )
        )

    async def send_audio(self, pcm16le: bytes) -> None:
        self._require_connected()
        if not pcm16le or len(pcm16le) % 2:
            raise SafeProviderError("invalid_pcm_frame")
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
                    NormalizedProviderEvent(
                        type="speech.started", output_mode="mock"
                    )
                )
            self._voiced_frames += 1
            if (
                self._voiced_frames % self.config.transcript_delta_every_frames
                == 0
            ):
                # Match Qwen's ASR projection: ``text`` is the cumulative
                # confirmed prefix and ``stash`` is the replaceable draft
                # suffix.  The browser must not treat these as append-only
                # token deltas.
                partial_index = min(
                    self._voiced_frames
                    // self.config.transcript_delta_every_frames,
                    3,
                )
                confirmed_tokens = ("[synthetic]", "redacted", "utterance")
                await self._emit(
                    NormalizedProviderEvent(
                        type="user.transcript.delta",
                        output_mode="mock",
                        text=" ".join(confirmed_tokens[:partial_index]) + " ",
                        stash=(
                            "[synthetic draft]"
                            if partial_index < len(confirmed_tokens)
                            else ""
                        ),
                    )
                )
            if self._voiced_frames >= self.config.auto_stop_after_voiced_frames:
                await self.finish_turn()
            return

        if self._in_speech:
            self._silence_frames += 1
            if self._silence_frames >= self.config.silence_frames_to_stop:
                await self.finish_turn()

    async def finish_turn(self) -> bool:
        """Finish a synthetic user turn and start one streaming response."""

        if not self._in_speech:
            return False
        self._in_speech = False
        self._awaiting_silence_reset = True
        self._silence_frames = 0
        self._voiced_frames = 0
        await self._emit(
            NormalizedProviderEvent(type="speech.stopped", output_mode="mock")
        )
        await self._emit(
            NormalizedProviderEvent(
                type="user.transcript.final",
                output_mode="mock",
                text="[synthetic redacted user utterance]",
            )
        )
        if self._response_task is not None and not self._response_task.done():
            # A fake session should normally be interrupted before another
            # response starts.  Finish safely rather than creating two writers.
            await self.cancel_response()
            await asyncio.gather(self._response_task, return_exceptions=True)
        self._response_cancel = asyncio.Event()
        self._response_task = asyncio.create_task(
            self._stream_response(), name="qwen-spike-fake-response"
        )
        return True

    async def recv_event(self) -> NormalizedProviderEvent:
        if self._closed and self._events.empty():
            raise ProviderDisconnected("fake_provider_closed")
        return await self._events.get()

    async def cancel_response(self) -> bool:
        if not self.response_active or self._response_cancel.is_set():
            return False
        self.cancel_count += 1
        self._response_cancel.set()
        return True

    async def inject_event(self, event: NormalizedProviderEvent) -> None:
        """Inject a synthetic normalized event for deterministic tests."""

        self._require_connected()
        await self._emit(event)

    async def trigger_error(
        self, code: str = "synthetic_provider_error", *, terminal: bool = False
    ) -> None:
        await self._emit(
            NormalizedProviderEvent(
                type="provider.error",
                output_mode="degraded",
                error_code=_synthetic_error_code(code),
                terminal=terminal,
            )
        )

    async def trigger_disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        await self._emit(
            NormalizedProviderEvent(
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
        self._active_response_ref = None
        self._profile = self._profile.with_health("closed")

    async def _stream_response(self) -> None:
        self._response_index += 1
        response_ref = f"response-synthetic-{self._response_index:04d}"
        self._active_response_ref = response_ref
        try:
            await self._emit(
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="mock",
                    response_ref=response_ref,
                )
            )
            transcript_chunks = ("Synthetic ", "streaming ", "reply.")
            for index in range(self.config.response_audio_chunks):
                await asyncio.sleep(self.config.event_delay_seconds)
                if self._response_cancel.is_set():
                    if self.config.late_audio_after_cancel:
                        # Deliberately model one in-flight late frame.  The
                        # bridge must drop it using response->epoch binding.
                        await self._emit(
                            NormalizedProviderEvent(
                                type="response.audio.delta",
                                output_mode="mock",
                                response_ref=response_ref,
                                audio=_sine_pcm_chunk(
                                    index=index,
                                    duration_ms=self.config.response_audio_chunk_ms,
                                ),
                            )
                        )
                    await self._emit(
                        NormalizedProviderEvent(
                            type="response.done",
                            output_mode="mock",
                            response_ref=response_ref,
                            status="cancelled",
                            reason="client_cancelled",
                        )
                    )
                    return
                if index < len(transcript_chunks):
                    await self._emit(
                        NormalizedProviderEvent(
                            type="assistant.transcript.delta",
                            output_mode="mock",
                            response_ref=response_ref,
                            text=transcript_chunks[index],
                        )
                    )
                await self._emit(
                    NormalizedProviderEvent(
                        type="response.audio.delta",
                        output_mode="mock",
                        response_ref=response_ref,
                        audio=_sine_pcm_chunk(
                            index=index,
                            duration_ms=self.config.response_audio_chunk_ms,
                        ),
                    )
                )
            await self._emit(
                NormalizedProviderEvent(
                    type="assistant.transcript.done",
                    output_mode="mock",
                    response_ref=response_ref,
                    text="Synthetic streaming reply.",
                )
            )
            await self._emit(
                NormalizedProviderEvent(
                    type="response.audio.done",
                    output_mode="mock",
                    response_ref=response_ref,
                )
            )
            await self._emit(
                NormalizedProviderEvent(
                    type="response.done",
                    output_mode="mock",
                    response_ref=response_ref,
                    status="completed",
                )
            )
        finally:
            if self._active_response_ref == response_ref:
                self._active_response_ref = None

    async def _emit(self, event: NormalizedProviderEvent) -> None:
        if self._closed:
            return
        await self._events.put(event)

    def _require_connected(self) -> None:
        if not self._connected or self._closed:
            raise ProviderDisconnected("fake_provider_not_connected")


def _pcm_has_voice(pcm16le: bytes, threshold: int) -> bool:
    for offset in range(0, len(pcm16le), 2):
        value = int.from_bytes(pcm16le[offset : offset + 2], "little", signed=True)
        if abs(value) > threshold:
            return True
    return False


def _sine_pcm_chunk(*, index: int, duration_ms: int) -> bytes:
    sample_rate = 24_000
    sample_count = sample_rate * duration_ms // 1_000
    start_sample = index * sample_count
    samples = array(
        "h",
        (
            int(5_000 * math.sin(2.0 * math.pi * 440.0 * sample / sample_rate))
            for sample in range(start_sample, start_sample + sample_count)
        ),
    )
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _synthetic_error_code(value: str) -> str:
    allowed = {
        "synthetic provider error": "synthetic_provider_error",
        "synthetic provider timeout": "synthetic_provider_timeout",
        "synthetic rate limit": "synthetic_rate_limit",
        "synthetic_provider_error": "synthetic_provider_error",
        "synthetic_provider_timeout": "synthetic_provider_timeout",
        "synthetic_rate_limit": "synthetic_rate_limit",
        "synthetic_rate_limited": "synthetic_rate_limit",
    }
    return allowed.get(value, "synthetic_provider_error")


__all__ = ["FakeProviderConfig", "FakeRealtimeProvider"]
