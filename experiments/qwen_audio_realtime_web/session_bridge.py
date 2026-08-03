"""Async browser/provider bridge for the isolated Qwen realtime web spike.

The bridge owns ephemeral session state only.  Its metadata timeline is not an
ADR-002 Event Journal and none of its event names are canonical runtime events.
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Generic, TypeVar

from aiohttp import WSMsgType

from .provider_adapter import (
    NormalizedProviderEvent,
    ProviderDisconnected,
    RealtimeProviderSession,
    SafeProviderError,
)


HEADSET_FULL_DUPLEX = "headset_full_duplex"
SPEAKER_SAFE = "speaker_safe"
VALID_MODES = frozenset({HEADSET_FULL_DUPLEX, SPEAKER_SAFE})
AUDIO_FRAME_MAGIC = b"QAR1"
_AUDIO_FRAME_HEADER = struct.Struct(">4sI")

T = TypeVar("T")


class QueueClosed(RuntimeError):
    pass


class DropOldestQueue(Generic[T]):
    """Small event-loop-local bounded queue with deterministic drop-oldest.

    It intentionally has no thread synchronization.  All callers live on the
    one asyncio loop that owns a spike session.
    """

    def __init__(self, maxsize: int) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        self.maxsize = maxsize
        self._items: Deque[T] = deque()
        self._available = asyncio.Event()
        self._closed = False
        self.dropped = 0

    def put_nowait(self, item: T, *, front: bool = False) -> T | None:
        if self._closed:
            raise QueueClosed("queue is closed")
        dropped_item: T | None = None
        if len(self._items) >= self.maxsize:
            dropped_item = self._items.popleft()
            self.dropped += 1
        if front:
            self._items.appendleft(item)
        else:
            self._items.append(item)
        self._available.set()
        return dropped_item

    async def get(self) -> T:
        while not self._items:
            if self._closed:
                raise QueueClosed("queue is closed")
            self._available.clear()
            if self._items:
                continue
            await self._available.wait()
        item = self._items.popleft()
        if not self._items:
            self._available.clear()
        return item

    def discard_where(self, predicate: Callable[[T], bool]) -> int:
        retained: Deque[T] = deque()
        removed = 0
        while self._items:
            item = self._items.popleft()
            if predicate(item):
                removed += 1
            else:
                retained.append(item)
        self._items = retained
        if self._items:
            self._available.set()
        else:
            self._available.clear()
        return removed

    def discard_one(
        self, predicate: Callable[[T], bool], *, count_as_drop: bool = False
    ) -> T | None:
        retained: Deque[T] = deque()
        removed: T | None = None
        while self._items:
            item = self._items.popleft()
            if removed is None and predicate(item):
                removed = item
                continue
            retained.append(item)
        self._items = retained
        if removed is not None and count_as_drop:
            self.dropped += 1
        if self._items:
            self._available.set()
        else:
            self._available.clear()
        return removed

    def clear(self) -> int:
        removed = len(self._items)
        self._items.clear()
        self._available.clear()
        return removed

    def close(self) -> None:
        self._closed = True
        self._available.set()

    def qsize(self) -> int:
        return len(self._items)

    def empty(self) -> bool:
        return not self._items

    def full(self) -> bool:
        return len(self._items) >= self.maxsize


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    input_queue_frames: int = 5
    output_queue_messages: int = 32
    expected_input_frame_bytes: int = 3_200
    max_input_frame_bytes: int = 6_400
    max_control_frame_bytes: int = 8_192
    max_response_epoch_bindings: int = 128

    def __post_init__(self) -> None:
        if self.input_queue_frames <= 0 or self.output_queue_messages <= 0:
            raise ValueError("bridge queue sizes must be positive")
        if self.expected_input_frame_bytes <= 0:
            raise ValueError("expected_input_frame_bytes must be positive")
        if self.max_input_frame_bytes < self.expected_input_frame_bytes:
            raise ValueError("max input frame must cover expected frame")
        if self.max_input_frame_bytes % 2:
            raise ValueError("max PCM frame size must be even")
        if self.max_control_frame_bytes < 256:
            raise ValueError("max_control_frame_bytes is too small")
        if self.max_response_epoch_bindings <= 0:
            raise ValueError("max_response_epoch_bindings must be positive")


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    kind: str
    value: dict[str, Any] | bytes
    playback_epoch: int
    priority: bool = False


class SessionBridge:
    """Lifecycle and cancellation owner for one browser/provider pair."""

    def __init__(
        self,
        browser_websocket: Any,
        provider: RealtimeProviderSession,
        *,
        mode: str = HEADSET_FULL_DUPLEX,
        config: BridgeConfig | None = None,
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError("invalid bridge mode")
        self.browser_websocket = browser_websocket
        self.provider = provider
        self.mode = mode
        self.config = config or BridgeConfig()
        self.input_queue: DropOldestQueue[bytes] = DropOldestQueue(
            self.config.input_queue_frames
        )
        self.output_queue: DropOldestQueue[OutboundMessage] = DropOldestQueue(
            self.config.output_queue_messages
        )
        self.playback_epoch = 0
        self.responding = False
        self.microphone_active = False
        self.dropped_input_frames = 0
        self.dropped_output_messages = 0
        self.dropped_output_audio_messages = 0
        self.dropped_output_control_messages = 0
        self.output_queue_high_water = 0
        self.speaker_safe_suppressed_frames = 0
        self.stale_audio_frames = 0
        self.invalid_input_frames = 0
        # Queue-pressure notices bypass the already-congested bounded queue but
        # still use the single browser writer.  The counters coalesce any burst
        # into constant-size metadata and never retain PCM or provider payloads.
        self._pending_gateway_drop_messages = 0
        self._pending_gateway_drop_audio_messages = 0
        self._pending_gateway_drop_control_messages = 0
        self._response_epochs: OrderedDict[str, int] = OrderedDict()
        self._active_response_ref: str | None = None
        self._last_bound_epoch: int | None = None
        self._closed = False
        self._running = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._started_ms = _monotonic_ms()
        self._speech_started_ms: float | None = None
        self._speech_stopped_ms: float | None = None
        self._first_user_transcript_seen = False
        self._first_assistant_transcript_seen = False
        self._first_audio_seen = False

    async def run(self) -> None:
        """Connect and run until either browser or provider terminates."""

        if self._running:
            raise RuntimeError("session bridge already running")
        self._running = True
        try:
            await self.provider.connect()
        except SafeProviderError as error:
            await self._send_direct_json(
                self._event_payload(
                    "session.error",
                    code=error.code,
                    retryable=error.retryable,
                    terminal=True,
                    turn_failed=False,
                    provider_mode=self.provider.profile.output_mode,
                )
            )
            await self.close()
            return
        except Exception:
            await self._send_direct_json(
                self._event_payload(
                    "session.error",
                    code="provider_connect_failed",
                    retryable=False,
                    terminal=True,
                    turn_failed=False,
                    provider_mode=self.provider.profile.output_mode,
                )
            )
            await self.close()
            return

        writer = asyncio.create_task(
            self._browser_writer(), name="qwen-spike-browser-writer"
        )
        browser_reader = asyncio.create_task(
            self._browser_reader(), name="qwen-spike-browser-reader"
        )
        input_forwarder = asyncio.create_task(
            self._browser_to_provider(), name="qwen-spike-browser-to-provider"
        )
        provider_reader = asyncio.create_task(
            self._provider_to_browser(), name="qwen-spike-provider-to-browser"
        )
        self._tasks = {writer, browser_reader, input_forwarder, provider_reader}
        await self._queue_json(
            "session.ready",
            mode=self.mode,
            state="connected",
            capabilities=self.provider.profile.to_metadata(),
        )
        await self._timeline(
            "spike.session.ready", output_mode=self.provider.profile.output_mode
        )

        try:
            _done, _pending = await asyncio.wait(
                self._tasks, return_when=asyncio.FIRST_COMPLETED
            )
            # Stop all producers first, then close the egress queue and let the
            # writer drain terminal status/error messages before teardown.
            producer_tasks = self._tasks - {writer}
            for task in producer_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*producer_tasks, return_exceptions=True)
            self.input_queue.close()
            self.output_queue.close()
            if not writer.done():
                try:
                    await asyncio.wait_for(writer, timeout=0.5)
                except asyncio.TimeoutError:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)
        finally:
            self._tasks.clear()
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.input_queue.clear()
        self.input_queue.close()
        self.output_queue.close()
        try:
            await self.provider.close()
        except Exception:
            pass
        websocket = self.browser_websocket
        if not getattr(websocket, "closed", False):
            try:
                await websocket.close()
            except Exception:
                pass

    async def enqueue_browser_audio(self, pcm16le: bytes) -> bool:
        """Validate and enqueue one transient browser PCM frame."""

        if (
            not pcm16le
            or len(pcm16le) % 2
            or len(pcm16le) > self.config.max_input_frame_bytes
        ):
            self.invalid_input_frames += 1
            await self._queue_json(
                "session.error",
                code="invalid_browser_audio_frame",
                retryable=True,
                terminal=False,
                turn_failed=False,
            )
            return False
        if self.mode == SPEAKER_SAFE and self.responding:
            self.speaker_safe_suppressed_frames += 1
            await self._emit_drop_status("speaker_safe_suppressed")
            return False
        dropped = self.input_queue.put_nowait(bytes(pcm16le))
        if dropped is not None:
            # The discarded bytes immediately become unreachable; no replay.
            self.dropped_input_frames += 1
            await self._emit_drop_status("input_backlog_drop_oldest")
        return True

    async def handle_provider_event(self, event: NormalizedProviderEvent) -> bool:
        """Handle one normalized event; return False for terminal events."""

        latency_ms: float | None = None
        if event.type == "speech.started":
            self._speech_started_ms = _monotonic_ms()
            self._speech_stopped_ms = None
            self._first_user_transcript_seen = False
            self._first_assistant_transcript_seen = False
            self._first_audio_seen = False
            await self.interrupt(reason="provider_speech_started")
            await self._queue_json(
                "speech.started",
                state="listening",
                output_mode=event.output_mode,
            )
        elif event.type == "speech.stopped":
            self._speech_stopped_ms = _monotonic_ms()
            await self._queue_json(
                "speech.stopped",
                state="processing",
                reason=event.reason,
                output_mode=event.output_mode,
            )
        elif event.type == "user.transcript.delta":
            if not self._first_user_transcript_seen:
                self._first_user_transcript_seen = True
                latency_ms = _elapsed(self._speech_started_ms)
            await self._queue_json(
                "user.transcript.delta",
                delta=event.text or "",
                stash=event.stash or "",
                latency_ms=latency_ms,
                output_mode=event.output_mode,
            )
        elif event.type == "user.transcript.final":
            if not self._first_user_transcript_seen:
                self._first_user_transcript_seen = True
                latency_ms = _elapsed(self._speech_started_ms)
            await self._queue_json(
                "user.transcript.final",
                transcript=event.text or "",
                latency_ms=latency_ms,
                output_mode=event.output_mode,
            )
        elif event.type == "response.created":
            response_ref = event.response_ref or "response-missing-safe-ref"
            existing_epoch = self._response_epochs.get(response_ref)
            if existing_epoch is not None and existing_epoch != self.playback_epoch:
                # A stale duplicate response.created must not reclaim the
                # current epoch or make its late audio playable.
                await self._emit_drop_status("stale_response_created")
                await self._timeline_event(event, latency_ms=latency_ms)
                return True
            if existing_epoch is None and self._last_bound_epoch == self.playback_epoch:
                # Every assistant response owns a unique epoch even when the
                # provider starts a new response without a speech_started.
                # Do not send response.cancel here: the adapter already regards
                # this newly-created response as active.
                await self._advance_playback_epoch(
                    reason="new_assistant_response", request_provider_cancel=False
                )
            self._bind_response_epoch(response_ref, self.playback_epoch)
            self._active_response_ref = response_ref
            self.responding = True
            if self.mode == SPEAKER_SAFE:
                removed = self.input_queue.clear()
                self.speaker_safe_suppressed_frames += removed
            await self._queue_json(
                "playback.started",
                response_ref=response_ref,
                state="responding",
                output_mode=event.output_mode,
            )
        elif event.type == "assistant.transcript.delta":
            if not self._response_is_current(event.response_ref):
                await self._emit_drop_status("stale_response_transcript")
                await self._timeline_event(event, latency_ms=latency_ms)
                return True
            if not self._first_assistant_transcript_seen:
                self._first_assistant_transcript_seen = True
                latency_ms = _elapsed(self._speech_stopped_ms)
            await self._queue_json(
                "assistant.transcript.delta",
                response_ref=event.response_ref,
                delta=event.text or "",
                latency_ms=latency_ms,
                output_mode=event.output_mode,
            )
        elif event.type == "assistant.transcript.done":
            if not self._response_is_current(event.response_ref):
                await self._emit_drop_status("stale_response_transcript")
                await self._timeline_event(event, latency_ms=latency_ms)
                return True
            await self._queue_json(
                "assistant.transcript.done",
                response_ref=event.response_ref,
                transcript=event.text or "",
                output_mode=event.output_mode,
            )
        elif event.type == "response.audio.delta":
            accepted = await self._handle_audio_delta(event)
            if accepted and not self._first_audio_seen:
                self._first_audio_seen = True
                latency_ms = _elapsed(self._speech_stopped_ms)
        elif event.type == "response.done":
            response_ref = event.response_ref or self._active_response_ref
            response_epoch = (
                self._response_epochs.get(response_ref)
                if response_ref is not None
                else None
            )
            response_is_from_old_epoch = (
                response_epoch is not None and response_epoch != self.playback_epoch
            )
            current_epoch_has_response = self._last_bound_epoch == self.playback_epoch
            if (
                response_is_from_old_epoch
                and current_epoch_has_response
            ) or (
                self._active_response_ref is not None
                and response_ref != self._active_response_ref
            ):
                # A late completion from an older response is useful timeline
                # metadata, but must not push the browser out of the current
                # response's Responding state.
                await self._emit_drop_status("stale_response_done")
                await self._timeline_event(event, latency_ms=latency_ms)
                return True
            completion_only = response_is_from_old_epoch
            if response_ref == self._active_response_ref:
                self._active_response_ref = None
                self.responding = False
            await self._queue_json(
                "response.done",
                response_ref=response_ref,
                response_epoch=response_epoch,
                status=event.status or "unknown",
                reason=event.reason,
                completion_only=completion_only,
                state=None if completion_only else (
                    "interrupted"
                    if event.status == "cancelled"
                    else "listening"
                    if event.status == "completed"
                else "error"
                ),
                output_mode=event.output_mode,
            )
            if event.status not in {"completed", "cancelled"}:
                await self._queue_json(
                    "session.error",
                    code="provider_response_failed",
                    retryable=False,
                    terminal=False,
                    turn_failed=True,
                    output_mode="degraded",
                )
        elif event.type in {"session.created", "session.updated"}:
            await self._queue_json(
                event.type,
                session_ref=event.session_ref,
                state="connected",
                output_mode=event.output_mode,
            )
        elif event.type == "provider.error":
            await self._queue_json(
                "session.error",
                code=event.error_code or "provider_error",
                retryable=not event.terminal,
                terminal=event.terminal,
                turn_failed=self.responding,
                output_mode="degraded",
            )
        elif event.type in {"provider.disconnected", "provider.timeout"}:
            await self._queue_json(
                "session.error",
                code=event.error_code or event.type.replace(".", "_"),
                retryable=False,
                terminal=True,
                turn_failed=self.responding,
                output_mode="degraded",
            )
            await self._timeline_event(event, latency_ms=latency_ms)
            return False

        await self._timeline_event(event, latency_ms=latency_ms)
        return not event.terminal

    async def interrupt(self, *, reason: str = "client_cancel") -> bool:
        """Advance epoch, clear queued audio, and conditionally cancel provider."""

        return await self._advance_playback_epoch(
            reason=reason, request_provider_cancel=True
        )

    async def _advance_playback_epoch(
        self, *, reason: str, request_provider_cancel: bool
    ) -> bool:
        """Advance epoch and enqueue a protected, immediate playback clear."""

        self.playback_epoch = (self.playback_epoch + 1) & 0xFFFFFFFF
        cleared = self.output_queue.discard_where(
            lambda item: item.kind == "audio"
        )
        was_responding = self.responding
        self.responding = False
        self._active_response_ref = None
        cancel_requested = False
        if request_provider_cancel and self.provider.response_active:
            try:
                cancel_requested = await self.provider.cancel_response()
            except SafeProviderError as error:
                await self._queue_json(
                    "session.error",
                    code=error.code,
                    retryable=error.retryable,
                    terminal=False,
                    turn_failed=was_responding,
                )
        await self._queue_json(
            "playback.clear",
            priority=True,
            reason=reason,
            cleared_frames=cleared,
            cancel_requested=cancel_requested,
            state="interrupted" if was_responding else "listening",
        )
        return cancel_requested

    async def _browser_reader(self) -> None:
        async for message in self.browser_websocket:
            if message.type == WSMsgType.BINARY:
                await self.enqueue_browser_audio(message.data)
            elif message.type == WSMsgType.TEXT:
                await self._handle_browser_control(message.data)
            elif message.type in (
                WSMsgType.CLOSE,
                WSMsgType.CLOSED,
                WSMsgType.ERROR,
            ):
                return

    async def _handle_browser_control(self, raw_message: str) -> None:
        if len(raw_message.encode("utf-8", "replace")) > self.config.max_control_frame_bytes:
            await self._queue_json(
                "session.error",
                code="browser_control_frame_too_large",
                retryable=True,
                terminal=False,
                turn_failed=False,
            )
            return
        try:
            message = json.loads(raw_message)
        except (TypeError, ValueError):
            message = None
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            await self._queue_json(
                "session.error",
                code="invalid_browser_control",
                retryable=True,
                terminal=False,
                turn_failed=False,
            )
            return

        message_type = message["type"]
        if message_type == "client.configure":
            mode = message.get("mode")
            if mode not in VALID_MODES:
                await self._queue_json(
                    "session.error",
                    code="invalid_audio_mode",
                    retryable=True,
                    terminal=False,
                    turn_failed=False,
                )
                return
            self.mode = mode
            removed = 0
            if mode == SPEAKER_SAFE and self.responding:
                removed = self.input_queue.clear()
                self.speaker_safe_suppressed_frames += removed
            await self._queue_json(
                "session.status",
                state="responding" if self.responding else "connected",
                mode=self.mode,
                speaker_safe_cleared_frames=removed,
            )
        elif message_type == "client.cancel":
            await self.interrupt(reason="client_cancel")
        elif message_type == "client.microphone":
            active = message.get("active")
            if not isinstance(active, bool):
                await self._queue_json(
                    "session.error",
                    code="invalid_microphone_state",
                    retryable=True,
                    terminal=False,
                    turn_failed=False,
                )
                return
            self.microphone_active = active
            if not self.microphone_active:
                self.input_queue.clear()
            await self._queue_json(
                "session.status",
                state="listening" if self.microphone_active else "connected",
                microphone_active=self.microphone_active,
            )
        elif message_type == "client.ping":
            await self._queue_json("client.pong")
        else:
            await self._queue_json(
                "session.error",
                code="unsupported_browser_control",
                retryable=True,
                terminal=False,
                turn_failed=False,
            )

    async def _browser_to_provider(self) -> None:
        try:
            while True:
                pcm = await self.input_queue.get()
                if self.mode == SPEAKER_SAFE and self.responding:
                    self.speaker_safe_suppressed_frames += 1
                    await self._emit_drop_status("speaker_safe_suppressed")
                    continue
                await self.provider.send_audio(pcm)
        except QueueClosed:
            return
        except SafeProviderError as error:
            await self._queue_json(
                "session.error",
                code=error.code,
                retryable=error.retryable,
                terminal=True,
                turn_failed=self.responding,
            )

    async def _provider_to_browser(self) -> None:
        try:
            while True:
                event = await self.provider.recv_event()
                if not await self.handle_provider_event(event):
                    return
        except ProviderDisconnected as error:
            await self._queue_json(
                "session.error",
                code=error.code,
                retryable=False,
                terminal=True,
                turn_failed=self.responding,
            )
        except SafeProviderError as error:
            await self._queue_json(
                "session.error",
                code=error.code,
                retryable=error.retryable,
                terminal=True,
                turn_failed=self.responding,
            )
        except Exception:
            await self._queue_json(
                "session.error",
                code="provider_receive_failed",
                retryable=False,
                terminal=True,
                turn_failed=self.responding,
            )

    async def _browser_writer(self) -> None:
        try:
            while True:
                message = await self.output_queue.get()
                if message.kind == "json":
                    if isinstance(message.value, dict):
                        self._refresh_output_flow_metadata(message.value)
                    await self.browser_websocket.send_json(message.value)
                else:
                    await self.browser_websocket.send_bytes(message.value)
                await self._flush_gateway_drop_notice()
        except (QueueClosed, asyncio.CancelledError):
            return
        except Exception:
            return

    async def _handle_audio_delta(self, event: NormalizedProviderEvent) -> bool:
        response_ref = event.response_ref or self._active_response_ref
        event_epoch = (
            self._response_epochs.get(response_ref)
            if response_ref is not None
            else None
        )
        if event_epoch is None or event_epoch != self.playback_epoch:
            self.stale_audio_frames += 1
            await self._emit_drop_status("stale_response_audio")
            return False
        if not event.audio:
            return False
        await self._queue_audio(event.audio, event_epoch)
        return True

    def _response_is_current(self, response_ref: str | None) -> bool:
        resolved = response_ref or self._active_response_ref
        if resolved is None:
            return False
        return self._response_epochs.get(resolved) == self.playback_epoch

    def _bind_response_epoch(self, response_ref: str, epoch: int) -> None:
        self._response_epochs[response_ref] = epoch
        self._last_bound_epoch = epoch
        self._response_epochs.move_to_end(response_ref)
        while len(self._response_epochs) > self.config.max_response_epoch_bindings:
            self._response_epochs.popitem(last=False)

    async def _queue_audio(self, pcm16le: bytes, epoch: int) -> None:
        frame = pack_output_audio(epoch, pcm16le)
        message = OutboundMessage(
            kind="audio", value=frame, playback_epoch=epoch, priority=False
        )
        self._put_output(message)

    async def _queue_json(
        self, event_type: str, *, priority: bool = False, **fields: Any
    ) -> None:
        payload = self._event_payload(event_type, **fields)
        message = OutboundMessage(
            kind="json",
            value=payload,
            playback_epoch=self.playback_epoch,
            priority=priority,
        )
        self._put_output(message, front=priority)

    def _put_output(
        self, message: OutboundMessage, *, front: bool = False
    ) -> bool:
        """Queue output while preserving an enqueued playback.clear.

        Ordinary bursts first evict ordinary audio/control messages.  If every
        queued item is priority, an ordinary incoming item is dropped instead.
        A newer priority clear may replace the oldest priority item.
        """

        try:
            if self.output_queue.full():
                dropped = self.output_queue.discard_one(
                    lambda item: not item.priority and item.kind == "audio",
                    count_as_drop=True,
                )
                if dropped is None:
                    dropped = self.output_queue.discard_one(
                        lambda item: not item.priority,
                        count_as_drop=True,
                    )
                if dropped is None:
                    if not message.priority:
                        self.output_queue.dropped += 1
                        self._record_output_drop(message)
                        return False
                    dropped = self.output_queue.discard_one(
                        lambda _item: True, count_as_drop=True
                    )
                if dropped is not None:
                    self._record_output_drop(dropped)
            dropped_by_queue = self.output_queue.put_nowait(message, front=front)
        except QueueClosed:
            return False
        if dropped_by_queue is not None:
            self._record_output_drop(dropped_by_queue)
        self.output_queue_high_water = max(
            self.output_queue_high_water, self.output_queue.qsize()
        )
        return True

    def _record_output_drop(self, message: OutboundMessage) -> None:
        """Record one queue-pressure drop without retaining message content."""

        self.dropped_output_messages += 1
        self._pending_gateway_drop_messages += 1
        if message.kind == "audio":
            self.dropped_output_audio_messages += 1
            self._pending_gateway_drop_audio_messages += 1
        else:
            self.dropped_output_control_messages += 1
            self._pending_gateway_drop_control_messages += 1

    async def _flush_gateway_drop_notice(self) -> None:
        """Send one coalesced, metadata-only gateway queue-pressure notice.

        Sending from the sole browser writer avoids recursion through the full
        output queue.  New drops that occur while ``send_json`` yields remain
        pending because only the snapshotted deltas are subtracted afterward.
        """

        dropped = self._pending_gateway_drop_messages
        if dropped <= 0:
            return
        dropped_audio = self._pending_gateway_drop_audio_messages
        dropped_control = self._pending_gateway_drop_control_messages
        payload = self._event_payload(
            "flow.gateway_output_dropped",
            output_mode="degraded",
            state="degraded",
            layer="gateway_output_queue",
            reason="output_queue_full",
            count=dropped,
            dropped_audio_messages_delta=dropped_audio,
            dropped_control_messages_delta=dropped_control,
        )
        # The existing page timeline treats ``dropped_input_frames`` as the
        # preferred generic drop count.  This new event omits that unrelated
        # field so it renders its own output-drop ``count`` instead.
        payload.pop("dropped_input_frames", None)
        await self.browser_websocket.send_json(payload)
        self._pending_gateway_drop_messages -= dropped
        self._pending_gateway_drop_audio_messages -= dropped_audio
        self._pending_gateway_drop_control_messages -= dropped_control

    def _refresh_output_flow_metadata(self, payload: dict[str, Any]) -> None:
        """Attach current, bounded and content-free gateway flow metrics."""

        payload.update(
            {
                "dropped_output_messages": self.dropped_output_messages,
                "dropped_output_audio_messages": self.dropped_output_audio_messages,
                "dropped_output_control_messages": self.dropped_output_control_messages,
                "output_queue_depth": self.output_queue.qsize(),
                "output_queue_high_water": self.output_queue_high_water,
                "output_queue_capacity": self.output_queue.maxsize,
            }
        )

    async def _emit_drop_status(self, reason: str) -> None:
        await self._queue_json(
            "flow.dropped",
            reason=reason,
            state="degraded",
            output_mode="degraded",
        )

    async def _timeline_event(
        self, event: NormalizedProviderEvent, *, latency_ms: float | None
    ) -> None:
        await self._timeline(
            f"spike.provider.{event.type}",
            byte_length=event.byte_length,
            response_ref=event.response_ref,
            session_ref=event.session_ref,
            latency_ms=latency_ms,
            output_mode=event.output_mode,
            status=event.status,
            reason=event.reason,
            error_code=event.error_code,
        )

    async def _timeline(self, event_name: str, **metadata: Any) -> None:
        safe_metadata = {
            key: value for key, value in metadata.items() if value is not None
        }
        await self._queue_json(
            "timeline.event",
            event=event_name,
            **safe_metadata,
        )

    def _event_payload(self, event_type: str, **fields: Any) -> dict[str, Any]:
        default_output_mode = (
            "degraded"
            if event_type in {"session.error", "flow.dropped"}
            else self.provider.profile.output_mode
        )
        output_mode = fields.pop("output_mode", default_output_mode)
        payload: dict[str, Any] = {
            "type": event_type,
            "timestamp_ms": round(_monotonic_ms(), 3),
            "playback_epoch": self.playback_epoch,
            "output_mode": output_mode,
            "mode": self.mode,
            "dropped_input_frames": self.dropped_input_frames,
            "speaker_safe_suppressed_frames": self.speaker_safe_suppressed_frames,
            "stale_audio_frames": self.stale_audio_frames,
        }
        self._refresh_output_flow_metadata(payload)
        payload.update({key: value for key, value in fields.items() if value is not None})
        return payload

    async def _send_direct_json(self, payload: dict[str, Any]) -> None:
        try:
            await self.browser_websocket.send_json(payload)
        except Exception:
            pass


def pack_output_audio(playback_epoch: int, pcm16le: bytes) -> bytes:
    """Pack local downlink frame: ``QAR1`` + uint32 BE epoch + PCM16LE."""

    if not 0 <= playback_epoch <= 0xFFFFFFFF:
        raise ValueError("playback_epoch outside uint32 range")
    if not pcm16le or len(pcm16le) % 2:
        raise ValueError("output PCM must be non-empty PCM16LE")
    return _AUDIO_FRAME_HEADER.pack(AUDIO_FRAME_MAGIC, playback_epoch) + pcm16le


def unpack_output_audio(frame: bytes) -> tuple[int, bytes]:
    if len(frame) <= _AUDIO_FRAME_HEADER.size:
        raise ValueError("audio frame is too short")
    magic, epoch = _AUDIO_FRAME_HEADER.unpack_from(frame)
    if magic != AUDIO_FRAME_MAGIC:
        raise ValueError("invalid audio frame magic")
    pcm = frame[_AUDIO_FRAME_HEADER.size :]
    if len(pcm) % 2:
        raise ValueError("output audio frame has odd PCM byte length")
    return epoch, pcm


def _monotonic_ms() -> float:
    return asyncio.get_running_loop().time() * 1_000.0


def _elapsed(start_ms: float | None) -> float | None:
    if start_ms is None:
        return None
    return round(max(0.0, _monotonic_ms() - start_ms), 3)


__all__ = [
    "AUDIO_FRAME_MAGIC",
    "BridgeConfig",
    "DropOldestQueue",
    "HEADSET_FULL_DUPLEX",
    "OutboundMessage",
    "QueueClosed",
    "SPEAKER_SAFE",
    "SessionBridge",
    "VALID_MODES",
    "pack_output_audio",
    "unpack_output_audio",
]
