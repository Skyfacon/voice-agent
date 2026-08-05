from __future__ import annotations

import asyncio
import json
from typing import Callable

from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeProviderEvent,
    FakeRealtimeProvider,
)


def run(coro):
    return asyncio.run(coro)


def voiced_frame(samples: int = 1_600, amplitude: int = 1_000) -> bytes:
    return amplitude.to_bytes(2, "little", signed=True) * samples


async def receive_event(provider: FakeRealtimeProvider) -> FakeProviderEvent:
    event = await asyncio.wait_for(provider.recv_event(), timeout=1)
    provider.event_processed()
    return event


async def drain_until(
    provider: FakeRealtimeProvider,
    predicate: Callable[[FakeProviderEvent], bool],
    *,
    maximum: int = 100,
) -> list[FakeProviderEvent]:
    events: list[FakeProviderEvent] = []
    for _ in range(maximum):
        event = await receive_event(provider)
        events.append(event)
        if predicate(event):
            return events
    raise AssertionError("fake provider did not emit expected terminal event")


async def connect_and_drain(provider: FakeRealtimeProvider) -> list[FakeProviderEvent]:
    await provider.connect()
    return [await receive_event(provider), await receive_event(provider)]


def test_fake_provider_connects_with_mock_capability_projection() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))
        try:
            events = await connect_and_drain(provider)

            assert [event.type for event in events] == [
                "session.created",
                "session.updated",
            ]
            assert provider.profile.output_mode == "mock"
            assert provider.profile.supports_real_provider is False
            assert provider.profile.tools_enabled is False
        finally:
            await provider.close()

    run(scenario())


def test_continuous_audio_is_forwarded_and_emits_asr_route_candidate_and_pcm() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(
            FakeProviderConfig(
                auto_stop_after_voiced_frames=3,
                transcript_delta_every_frames=1,
                response_audio_chunks=2,
                event_delay_seconds=0,
            )
        )
        try:
            await connect_and_drain(provider)
            frame = voiced_frame()
            for _ in range(3):
                await provider.send_audio(frame)

            events = await drain_until(provider, lambda event: event.type == "response.done")
            await provider.wait_response_complete()
            types = [event.type for event in events]

            assert provider.sent_audio_frames == 3
            assert provider.sent_audio_bytes == 3 * len(frame)
            assert "speech.started" in types
            assert "speech.stopped" in types
            assert types.count("user.transcript.delta") == 3
            assert "user.transcript.final" in types
            assert "assistant.transcript.delta" in types
            assert types.count("response.audio.delta") == 2
            assert "assistant.transcript.done" in types
            assert "route.proposed" in types
            assert events[-1].status == "completed"

            proposal = next(event for event in events if event.type == "route.proposed")
            assert (
                proposal.route_hint,
                proposal.task_focus_hint,
                proposal.foreground_act,
                proposal.risk_class,
            ) == ("FAST_ONLY", "FOREGROUND_CHAT", "ANSWER", "LOW")
            audio = [event.audio for event in events if event.type == "response.audio.delta"]
            assert all(chunk and len(chunk) % 2 == 0 for chunk in audio)
        finally:
            await provider.close()

    run(scenario())


def test_response_cancel_emits_cancelled_done_and_optional_late_audio() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(
            FakeProviderConfig(
                response_audio_chunks=8,
                event_delay_seconds=0.01,
                late_audio_after_cancel=True,
            )
        )
        try:
            await connect_and_drain(provider)
            await provider.trigger_scenario("fast")
            prefix = await drain_until(provider, lambda event: event.type == "response.created")
            response_id = prefix[-1].response_id

            assert await provider.cancel_response() is True
            assert await provider.cancel_response() is False
            suffix = await drain_until(
                provider,
                lambda event: event.type == "response.done" and event.response_id == response_id,
            )
            await provider.wait_response_complete()

            assert provider.cancel_count == 1
            assert suffix[-1].status == "cancelled"
            assert any(event.type == "response.audio.delta" for event in suffix)
        finally:
            await provider.close()

    run(scenario())


def test_late_audio_scenario_emits_interrupt_then_old_response_audio() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(
            FakeProviderConfig(
                response_audio_chunks=1,
                event_delay_seconds=0,
                late_audio_after_cancel=True,
            )
        )
        try:
            await connect_and_drain(provider)
            await provider.trigger_scenario("late_audio")
            events = await drain_until(provider, lambda event: event.type == "response.done")
            await provider.wait_response_complete()
            interrupt_index = next(
                index
                for index, event in enumerate(events)
                if event.type == "speech.started" and event.interrupt_only
            )
            late_index = next(
                index
                for index, event in enumerate(events)
                if index > interrupt_index and event.type == "response.audio.delta"
            )

            assert late_index > interrupt_index
            assert events[-1].status == "cancelled"
        finally:
            await provider.close()

    run(scenario())


def test_fake_event_queue_applies_bounded_backpressure() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(
            FakeProviderConfig(
                output_queue_events=4,
                response_audio_chunks=12,
                event_delay_seconds=0,
            )
        )
        try:
            await provider.connect()
            # Do not consume: connect already occupies two slots and the
            # producer must block at the configured hard limit.
            producer = asyncio.create_task(provider.trigger_scenario("fast"))
            for _ in range(100):
                if provider.pending_event_count == 4:
                    break
                await asyncio.sleep(0)

            assert provider.pending_event_count == 4
            assert provider.pending_event_count <= provider.config.output_queue_events
            assert provider.dropped_provider_events == 0
            assert not producer.done()
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
        finally:
            await provider.close()

    run(scenario())


def test_provider_error_is_allowlisted_and_degraded_without_detail_leak() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))
        try:
            await connect_and_drain(provider)
            secret = "Bearer secret-token from provider body"
            await provider.trigger_error(secret, terminal=False)
            event = await receive_event(provider)
            metadata = event.to_safe_metadata()
            serialized = json.dumps(metadata, sort_keys=True)

            assert event.type == "provider.error"
            assert event.output_mode == "degraded"
            assert event.error_code == "synthetic_provider_error"
            assert event.terminal is False
            assert secret not in serialized
            assert "bearer" not in serialized.lower()
            assert "token" not in serialized.lower()
        finally:
            await provider.close()

    run(scenario())


def test_provider_disconnect_is_terminal_degraded_and_close_is_idempotent() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))
        await connect_and_drain(provider)

        await provider.trigger_disconnect()
        event = await receive_event(provider)
        assert event.type == "provider.disconnected"
        assert event.output_mode == "degraded"
        assert event.terminal is True
        assert provider.profile.health_status == "disconnected"

        await provider.close()
        await provider.close()
        assert provider.profile.health_status == "closed"

    run(scenario())


def test_safe_provider_event_metadata_omits_transcript_and_pcm_content() -> None:
    event = FakeProviderEvent(
        type="response.audio.delta",
        response_id="response-safe",
        provider_item_id="item-safe",
        text="unredacted synthetic transcript",
        audio=b"\x01\x00\x02\x00",
    )

    metadata = event.to_safe_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert metadata["audio_bytes"] == 4
    assert "text" not in metadata
    assert "audio" not in metadata
    assert "unredacted" not in serialized
    assert "01000200" not in serialized
