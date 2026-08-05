from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import WSMsgType

from experiments.qwen_audio_realtime_web.capability_profile import (
    CapabilityProfile,
    fake_capability_profile,
)
from experiments.qwen_audio_realtime_web.provider_adapter import (
    NormalizedProviderEvent,
)
from experiments.qwen_audio_realtime_web.session_bridge import (
    AUDIO_FRAME_MAGIC,
    BridgeConfig,
    DropOldestQueue,
    HEADSET_FULL_DUPLEX,
    OutboundMessage,
    QueueClosed,
    SPEAKER_SAFE,
    SessionBridge,
    pack_output_audio,
    unpack_output_audio,
)


def run(coro):
    return asyncio.run(coro)


def pcm_frame(amplitude: int, samples: int = 1_600) -> bytes:
    return amplitude.to_bytes(2, "little", signed=True) * samples


class StubProvider:
    def __init__(self) -> None:
        self._profile = fake_capability_profile()
        self.events: asyncio.Queue[NormalizedProviderEvent] = asyncio.Queue()
        self.sent_audio: list[bytes] = []
        self.connected = False
        self.closed = False
        self.active = False
        self.cancel_calls = 0

    @property
    def profile(self) -> CapabilityProfile:
        return self._profile

    @property
    def response_active(self) -> bool:
        return self.active

    async def connect(self) -> None:
        self.connected = True

    async def send_audio(self, pcm16le: bytes) -> None:
        self.sent_audio.append(pcm16le)

    async def recv_event(self) -> NormalizedProviderEvent:
        return await self.events.get()

    async def cancel_response(self) -> bool:
        if not self.active:
            return False
        self.cancel_calls += 1
        self.active = False
        return True

    async def close(self) -> None:
        self.closed = True
        self.active = False
        self._profile = self._profile.with_health("closed")


_STOP = object()


class MemoryBrowser:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[Any] = asyncio.Queue()
        self.sent_json: list[dict[str, Any]] = []
        self.sent_bytes: list[bytes] = []
        self.closed = False

    def __aiter__(self) -> "MemoryBrowser":
        return self

    async def __anext__(self) -> Any:
        item = await self.incoming.get()
        if item is _STOP:
            raise StopAsyncIteration
        return item

    async def send_json(self, value: dict[str, Any]) -> None:
        self.sent_json.append(value)

    async def send_bytes(self, value: bytes) -> None:
        self.sent_bytes.append(value)

    async def close(self) -> None:
        self.closed = True


async def drain_output(bridge: SessionBridge) -> list[OutboundMessage]:
    messages: list[OutboundMessage] = []
    while not bridge.output_queue.empty():
        messages.append(await bridge.output_queue.get())
    return messages


async def wait_until(predicate, *, timeout: float = 1.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=timeout)


def test_drop_oldest_queue_is_bounded_and_counts_drops() -> None:
    async def scenario() -> None:
        queue: DropOldestQueue[str] = DropOldestQueue(maxsize=2)
        assert queue.put_nowait("one") is None
        assert queue.put_nowait("two") is None
        assert queue.put_nowait("three") == "one"
        assert queue.qsize() == 2
        assert queue.dropped == 1
        assert await queue.get() == "two"
        assert await queue.get() == "three"
        queue.close()
        with pytest.raises(QueueClosed):
            await queue.get()

    run(scenario())


@pytest.mark.parametrize(
    ("frame", "message"),
    (
        (b"", "output PCM must be non-empty"),
        (b"\x00", "output PCM must be non-empty PCM16LE"),
    ),
)
def test_output_pcm_envelope_rejects_invalid_pcm(frame: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        pack_output_audio(0, frame)


def test_output_pcm_envelope_is_qar1_plus_uint32_epoch() -> None:
    pcm = b"\x01\x00\x02\x00"
    frame = pack_output_audio(0x01020304, pcm)

    assert frame[:4] == AUDIO_FRAME_MAGIC == b"QAR1"
    assert frame[4:8] == b"\x01\x02\x03\x04"
    assert unpack_output_audio(frame) == (0x01020304, pcm)
    with pytest.raises(ValueError, match="magic"):
        unpack_output_audio(b"NOPE" + frame[4:])
    with pytest.raises(ValueError, match="odd PCM"):
        unpack_output_audio(frame + b"\x00")


def test_input_backlog_drops_oldest_frame_and_surfaces_degraded_counter() -> None:
    async def scenario() -> None:
        bridge = SessionBridge(
            MemoryBrowser(),
            StubProvider(),
            config=BridgeConfig(input_queue_frames=2),
        )
        first, second, third = (pcm_frame(value) for value in (1, 2, 3))

        assert await bridge.enqueue_browser_audio(first) is True
        assert await bridge.enqueue_browser_audio(second) is True
        assert await bridge.enqueue_browser_audio(third) is True

        assert bridge.input_queue.qsize() == 2
        assert bridge.input_queue.dropped == 1
        assert bridge.dropped_input_frames == 1
        assert await bridge.input_queue.get() == second
        assert await bridge.input_queue.get() == third
        messages = await drain_output(bridge)
        drop = [
            message.value
            for message in messages
            if message.kind == "json" and message.value["type"] == "flow.dropped"
        ]
        assert drop[0]["reason"] == "input_backlog_drop_oldest"
        assert drop[0]["output_mode"] == "degraded"

    run(scenario())


@pytest.mark.parametrize(
    "frame",
    (b"", b"\x01", b"\x00\x00" * 3_201),
)
def test_invalid_browser_audio_is_rejected_with_safe_error(frame: bytes) -> None:
    async def scenario() -> None:
        bridge = SessionBridge(MemoryBrowser(), StubProvider())

        assert await bridge.enqueue_browser_audio(frame) is False
        assert bridge.invalid_input_frames == 1
        assert bridge.input_queue.empty()
        messages = await drain_output(bridge)
        error = messages[0].value
        assert error["type"] == "session.error"
        assert error["code"] == "invalid_browser_audio_frame"
        assert "frame" not in error

    run(scenario())


def test_speaker_safe_suppresses_upload_while_responding() -> None:
    async def scenario() -> None:
        speaker_bridge = SessionBridge(
            MemoryBrowser(), StubProvider(), mode=SPEAKER_SAFE
        )
        speaker_bridge.responding = True
        assert await speaker_bridge.enqueue_browser_audio(pcm_frame(1)) is False
        assert speaker_bridge.input_queue.empty()
        assert speaker_bridge.speaker_safe_suppressed_frames == 1

        headset_bridge = SessionBridge(
            MemoryBrowser(), StubProvider(), mode=HEADSET_FULL_DUPLEX
        )
        headset_bridge.responding = True
        assert await headset_bridge.enqueue_browser_audio(pcm_frame(1)) is True
        assert headset_bridge.input_queue.qsize() == 1

    run(scenario())


def test_speech_started_advances_epoch_cancels_and_clears_playback() -> None:
    async def scenario() -> None:
        provider = StubProvider()
        provider.active = True
        bridge = SessionBridge(MemoryBrowser(), provider)
        bridge.responding = True
        bridge._active_response_ref = "response-current"
        await bridge._queue_audio(b"\x01\x00", epoch=0)

        keep_running = await bridge.handle_provider_event(
            NormalizedProviderEvent(type="speech.started", output_mode="mock")
        )

        assert keep_running is True
        assert bridge.playback_epoch == 1
        assert bridge.responding is False
        assert provider.cancel_calls == 1
        messages = await drain_output(bridge)
        assert all(message.kind != "audio" for message in messages)
        assert messages[0].value["type"] == "playback.clear"
        assert messages[0].value["playback_epoch"] == 1
        assert messages[0].value["cleared_frames"] == 1
        assert messages[0].value["cancel_requested"] is True
        assert any(
            message.kind == "json" and message.value["type"] == "speech.started"
            for message in messages
        )

    run(scenario())


def test_explicit_cancel_advances_epoch_even_without_active_provider_response() -> None:
    async def scenario() -> None:
        bridge = SessionBridge(MemoryBrowser(), StubProvider())

        assert await bridge.interrupt(reason="client_cancel") is False
        assert bridge.playback_epoch == 1
        messages = await drain_output(bridge)
        assert messages[0].value["type"] == "playback.clear"
        assert messages[0].value["reason"] == "client_cancel"
        assert messages[0].value["cancel_requested"] is False

    run(scenario())


def test_response_transcripts_and_pcm_are_bound_to_current_epoch() -> None:
    async def scenario() -> None:
        bridge = SessionBridge(MemoryBrowser(), StubProvider())
        response_ref = "response-safe-1"
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.created",
                output_mode="mock",
                response_ref=response_ref,
            )
        )
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="assistant.transcript.delta",
                output_mode="mock",
                response_ref=response_ref,
                text="Synthetic ",
            )
        )
        pcm = b"\x01\x00\x02\x00"
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.audio.delta",
                output_mode="mock",
                response_ref=response_ref,
                audio=pcm,
            )
        )
        messages = await drain_output(bridge)

        transcript = [
            message.value
            for message in messages
            if message.kind == "json"
            and message.value["type"] == "assistant.transcript.delta"
        ]
        assert transcript[0]["delta"] == "Synthetic "
        assert transcript[0]["output_mode"] == "mock"
        audio = [message for message in messages if message.kind == "audio"]
        assert len(audio) == 1
        assert audio[0].playback_epoch == 0
        assert unpack_output_audio(audio[0].value) == (0, pcm)

    run(scenario())


def test_two_sequential_responses_receive_unique_epochs_and_old_audio_is_dropped() -> None:
    async def scenario() -> None:
        bridge = SessionBridge(MemoryBrowser(), StubProvider())
        first = "response-safe-first"
        second = "response-safe-second"

        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.created", output_mode="mock", response_ref=first
            )
        )
        first_epoch = bridge.playback_epoch
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.created", output_mode="mock", response_ref=second
            )
        )
        second_epoch = bridge.playback_epoch
        assert second_epoch == first_epoch + 1

        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.audio.delta",
                output_mode="mock",
                response_ref=first,
                audio=b"\x01\x00",
            )
        )
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.audio.delta",
                output_mode="mock",
                response_ref=second,
                audio=b"\x02\x00",
            )
        )
        messages = await drain_output(bridge)
        audio = [message for message in messages if message.kind == "audio"]

        assert bridge.stale_audio_frames == 1
        assert len(audio) == 1
        assert unpack_output_audio(audio[0].value) == (second_epoch, b"\x02\x00")
        assert any(
            message.kind == "json"
            and message.value["type"] == "flow.dropped"
            and message.value["reason"] == "stale_response_audio"
            for message in messages
        )

    run(scenario())


def test_old_response_done_cannot_end_new_active_response() -> None:
    async def scenario() -> None:
        bridge = SessionBridge(MemoryBrowser(), StubProvider())
        first = "response-safe-first"
        second = "response-safe-second"
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.created", output_mode="mock", response_ref=first
            )
        )
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.created", output_mode="mock", response_ref=second
            )
        )
        await drain_output(bridge)

        assert bridge.responding is True
        assert bridge._active_response_ref == second
        await bridge.handle_provider_event(
            NormalizedProviderEvent(
                type="response.done",
                output_mode="degraded",
                response_ref=first,
                status="cancelled",
                reason="client_cancelled",
            )
        )
        messages = await drain_output(bridge)

        assert bridge.responding is True
        assert bridge._active_response_ref == second
        assert not any(
            message.kind == "json" and message.value["type"] == "response.done"
            for message in messages
        )
        stale = [
            message.value
            for message in messages
            if message.kind == "json"
            and message.value["type"] == "flow.dropped"
        ]
        assert [item["reason"] for item in stale] == ["stale_response_done"]

    run(scenario())


def test_playback_clear_is_not_evicted_by_later_output_burst() -> None:
    async def scenario() -> None:
        bridge = SessionBridge(
            MemoryBrowser(),
            StubProvider(),
            config=BridgeConfig(output_queue_messages=3),
        )
        await bridge.interrupt(reason="client_cancel")
        for index in range(20):
            await bridge._queue_json("timeline.event", event=f"synthetic.{index}")

        messages = await drain_output(bridge)
        assert messages[0].priority is True
        assert messages[0].value["type"] == "playback.clear"
        assert len(messages) == 3
        assert bridge.dropped_output_messages == 18
        assert bridge.dropped_output_audio_messages == 0
        assert bridge.dropped_output_control_messages == 18
        assert bridge.output_queue_high_water == 3

    run(scenario())


def test_gateway_audio_drop_emits_coalesced_metadata_only_notice() -> None:
    async def scenario() -> None:
        browser = MemoryBrowser()
        bridge = SessionBridge(
            browser,
            StubProvider(),
            config=BridgeConfig(output_queue_messages=2),
        )
        await bridge._queue_audio(b"\x01\x00", epoch=0)
        await bridge._queue_audio(b"\x02\x00", epoch=0)

        # A control message entering the full queue preferentially evicts the
        # oldest audio message.  The writer then emits one direct, coalesced
        # notice without trying to enqueue diagnostics into that same queue.
        await bridge._queue_json("timeline.event", event="synthetic.safe")
        bridge.output_queue.close()
        await bridge._browser_writer()

        notices = [
            item
            for item in browser.sent_json
            if item["type"] == "flow.gateway_output_dropped"
        ]
        assert len(notices) == 1
        notice = notices[0]
        assert notice["layer"] == "gateway_output_queue"
        assert notice["reason"] == "output_queue_full"
        assert notice["output_mode"] == "degraded"
        assert notice["count"] == 1
        assert notice["dropped_audio_messages_delta"] == 1
        assert notice["dropped_control_messages_delta"] == 0
        assert notice["dropped_output_messages"] == 1
        assert notice["dropped_output_audio_messages"] == 1
        assert notice["dropped_output_control_messages"] == 0
        assert notice["output_queue_high_water"] == 2
        assert notice["output_queue_capacity"] == 2
        assert "dropped_input_frames" not in notice
        assert "audio" not in notice
        assert "pcm" not in notice

    run(scenario())


def test_browser_controls_validate_mode_size_and_boolean_microphone_state() -> None:
    async def scenario() -> None:
        bridge = SessionBridge(
            MemoryBrowser(),
            StubProvider(),
            config=BridgeConfig(max_control_frame_bytes=256),
        )

        await bridge._handle_browser_control("not json")
        await bridge._handle_browser_control(
            json.dumps({"type": "client.configure", "mode": "unsafe_mode"})
        )
        await bridge._handle_browser_control(
            json.dumps({"type": "client.microphone", "active": "yes"})
        )
        await bridge._handle_browser_control("x" * 257)
        messages = await drain_output(bridge)
        codes = [message.value["code"] for message in messages]

        assert codes == [
            "invalid_browser_control",
            "invalid_audio_mode",
            "invalid_microphone_state",
            "browser_control_frame_too_large",
        ]
        assert bridge.microphone_active is False

    run(scenario())


def test_bridge_continuously_forwards_browser_binary_frames_and_closes_on_disconnect() -> None:
    async def scenario() -> None:
        browser = MemoryBrowser()
        provider = StubProvider()
        bridge = SessionBridge(browser, provider)
        task = asyncio.create_task(bridge.run())
        await wait_until(
            lambda: any(item["type"] == "session.ready" for item in browser.sent_json)
        )

        frames = [pcm_frame(value) for value in (1, 2, 3)]
        for frame in frames:
            await browser.incoming.put(
                SimpleNamespace(type=WSMsgType.BINARY, data=frame)
            )
        await wait_until(lambda: len(provider.sent_audio) == len(frames))
        await browser.incoming.put(
            SimpleNamespace(type=WSMsgType.CLOSE, data=None)
        )
        await asyncio.wait_for(task, timeout=1)

        assert provider.sent_audio == frames
        assert provider.closed is True
        assert browser.closed is True
        assert bridge.input_queue.empty()

    run(scenario())


@pytest.mark.parametrize(
    "terminal_event",
    (
        NormalizedProviderEvent(
            type="provider.disconnected",
            output_mode="degraded",
            error_code="provider_disconnected",
            terminal=True,
        ),
        NormalizedProviderEvent(
            type="provider.timeout",
            output_mode="degraded",
            error_code="provider_receive_timeout",
            terminal=True,
        ),
    ),
)
def test_provider_terminal_status_reaches_browser_before_bridge_teardown(
    terminal_event: NormalizedProviderEvent,
) -> None:
    async def scenario() -> None:
        browser = MemoryBrowser()
        provider = StubProvider()
        bridge = SessionBridge(browser, provider)
        task = asyncio.create_task(bridge.run())
        await wait_until(
            lambda: any(item["type"] == "session.ready" for item in browser.sent_json)
        )

        await provider.events.put(terminal_event)
        await asyncio.wait_for(task, timeout=1)

        terminal_errors = [
            item
            for item in browser.sent_json
            if item["type"] == "session.error" and item.get("terminal") is True
        ]
        assert terminal_errors
        assert terminal_errors[-1]["code"] == terminal_event.error_code
        assert terminal_errors[-1]["output_mode"] == "degraded"
        assert provider.closed is True
        assert browser.closed is True

    run(scenario())
