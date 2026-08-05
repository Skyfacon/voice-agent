from __future__ import annotations

import asyncio
from collections import deque

import pytest

from voice_agent.adapters.qwen_realtime.ephemeral_text_store import EphemeralTextStore
from voice_agent.adapters.qwen_realtime.protocol import QwenSessionConfiguration
from voice_agent.adapters.qwen_realtime.protocol import (
    ErrorServerEvent,
    InputAudioBufferAppendClientEvent,
    QwenClientEvent,
    QwenServerEvent,
    SessionCreatedServerEvent,
    SessionUpdatedServerEvent,
)
from voice_agent.adapters.qwen_realtime.projections import (
    ProviderContextProjectionV1,
    RebuildRequestedProjectionV1,
)
from voice_agent.adapters.qwen_realtime.quarantine import CandidateQuarantine
from voice_agent.adapters.qwen_realtime.scenarios import get_qwen_wire_script
from voice_agent.adapters.qwen_realtime.scripted_wire import ScriptedFakeQwenWire
from voice_agent.adapters.qwen_realtime.session_adapter import QwenRealtimeSessionAdapter


class CollectingSink:
    def __init__(self) -> None:
        self.frames: list[object] = []

    async def accept(self, frame: object) -> None:
        self.frames.append(frame)


class NoopTransport:
    async def open(self) -> None:
        return None

    async def send(self, event: object) -> None:
        return None

    async def recv(self) -> object:
        raise AssertionError("direct protocol tests do not receive")

    async def close(self) -> None:
        return None


class ConcurrentTransport:
    def __init__(self, events: list[QwenServerEvent]) -> None:
        self.events = deque(events)
        self.sent: list[QwenClientEvent] = []
        self.concurrent_recv = 0
        self.max_concurrent_recv = 0
        self.concurrent_send = 0
        self.max_concurrent_send = 0
        self.closed = False

    async def open(self) -> None:
        return None

    async def send(self, event: QwenClientEvent) -> None:
        self.concurrent_send += 1
        self.max_concurrent_send = max(
            self.max_concurrent_send,
            self.concurrent_send,
        )
        await asyncio.sleep(0)
        self.sent.append(event)
        self.concurrent_send -= 1

    async def recv(self) -> QwenServerEvent:
        self.concurrent_recv += 1
        self.max_concurrent_recv = max(
            self.max_concurrent_recv,
            self.concurrent_recv,
        )
        try:
            while not self.events:
                await asyncio.sleep(0)
            return self.events.popleft()
        finally:
            self.concurrent_recv -= 1

    async def close(self) -> None:
        self.closed = True


class ControlledReceiveTransport:
    def __init__(self, event: QwenServerEvent) -> None:
        self.event = event
        self.release = asyncio.Event()
        self.recv_started = asyncio.Event()

    async def open(self) -> None:
        return None

    async def send(self, event: QwenClientEvent) -> None:
        return None

    async def recv(self) -> QwenServerEvent:
        self.recv_started.set()
        await self.release.wait()
        return self.event

    async def close(self) -> None:
        self.release.set()


class ControlledFailureTransport:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.recv_started = asyncio.Event()

    async def open(self) -> None:
        return None

    async def send(self, event: QwenClientEvent) -> None:
        return None

    async def recv(self) -> QwenServerEvent:
        self.recv_started.set()
        await self.release.wait()
        raise RuntimeError("synthetic old-generation receive failure")

    async def close(self) -> None:
        self.release.set()


CONFIGURATION = QwenSessionConfiguration(
    turn_detection_type="smart_turn",
    modalities=("text", "audio"),
    voice="synthetic_voice",
    input_audio_transcription=(("model", "synthetic_asr"),),
    tools=(),
    fast_role_profile="fast-role://synthetic/v1",
)


def test_bootstrap_requires_created_update_exact_updated_before_clean() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        wire = ScriptedFakeQwenWire(
            get_qwen_wire_script("bootstrap_requires_session_update")
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        await wire.open()
        await adapter.attach_open_transport(wire)

        assert await adapter.append_audio(b"\x00\x00") is False
        wire.release_next_server_event()
        await asyncio.sleep(0)
        assert [entry["type"] for entry in wire.safe_timeline()] == ["session.created", "session.update"]
        assert adapter.provider_context_state == "REBUILDING"
        wire.release_next_server_event()
        await asyncio.sleep(0)

        assert adapter.provider_context_state == "CLEAN"
        await adapter.stop_pump()
        await wire.close()

    asyncio.run(scenario())


def test_updated_before_created_taints_and_requests_rebuild() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION, projection_sink=sink,
            quarantine=CandidateQuarantine(), text_store=EphemeralTextStore(),
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)

        await adapter._handle(SessionUpdatedServerEvent(
            event_id="evt_updated_before_created", session_id="sess_fake_001",
            configuration=CONFIGURATION,
        ))

        assert adapter.provider_context_state == "TAINTED"
        assert type(sink.frames[-1]).__name__ == "RebuildRequestedProjectionV1"

    asyncio.run(scenario())


def test_duplicate_created_and_configuration_mismatch_fail_closed() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION, projection_sink=sink,
            quarantine=CandidateQuarantine(), text_store=EphemeralTextStore(),
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        adapter._transport = NoopTransport()  # type: ignore[assignment]
        await adapter._handle(SessionCreatedServerEvent(
            event_id="evt_created_one", session_id="sess_fake_001"
        ))
        await adapter._handle(SessionCreatedServerEvent(
            event_id="evt_created_two", session_id="sess_fake_001"
        ))
        assert adapter.provider_context_state == "TAINTED"

        adapter.fence_for_generation(generation=2, playback_epoch=1)
        adapter._transport = NoopTransport()  # type: ignore[assignment]
        await adapter._handle(SessionCreatedServerEvent(
            event_id="evt_created_three", session_id="sess_fake_001"
        ))
        mismatch = QwenSessionConfiguration(
            turn_detection_type="smart_turn", modalities=("text", "audio"),
            voice="another_synthetic_voice",
            input_audio_transcription=(("model", "synthetic_asr"),), tools=(),
            fast_role_profile="fast-role://synthetic/v1",
        )
        await adapter._handle(SessionUpdatedServerEvent(
            event_id="evt_updated_mismatch", session_id="sess_fake_001",
            configuration=mismatch,
        ))
        assert adapter.provider_context_state == "TAINTED"

    asyncio.run(scenario())


def test_session_id_mismatch_and_handshake_error_fail_closed() -> None:
    async def scenario() -> None:
        for terminal in ("mismatch", "error"):
            sink = CollectingSink()
            adapter = QwenRealtimeSessionAdapter(
                configuration=CONFIGURATION,
                projection_sink=sink,
                quarantine=CandidateQuarantine(),
                text_store=EphemeralTextStore(),
            )
            adapter.fence_for_generation(generation=1, playback_epoch=0)
            adapter._transport = NoopTransport()  # type: ignore[assignment]
            await adapter._handle(
                SessionCreatedServerEvent(
                    event_id=f"event_created_{terminal}",
                    session_id="session_synthetic_1",
                ),
                generation=1,
            )
            if terminal == "mismatch":
                event: QwenServerEvent = SessionUpdatedServerEvent(
                    event_id="event_updated_wrong_session",
                    session_id="session_synthetic_2",
                    configuration=CONFIGURATION,
                )
            else:
                event = ErrorServerEvent(
                    event_id="event_handshake_error",
                    error_type="server_error",
                    error_code="synthetic_server_error",
                )
            await adapter._handle(event, generation=1)
            assert adapter.provider_context_state == "TAINTED"
            assert type(sink.frames[-1]).__name__ == (
                "RebuildRequestedProjectionV1"
            )

    asyncio.run(scenario())


def test_missing_and_duplicate_server_event_id_fail_closed() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        malformed = object.__new__(SessionCreatedServerEvent)
        object.__setattr__(malformed, "event_id", "")
        object.__setattr__(malformed, "session_id", "session_synthetic_1")
        await adapter._handle(malformed, generation=1)
        assert adapter.provider_context_state == "TAINTED"

        adapter.fence_for_generation(generation=2, playback_epoch=1)
        adapter._transport = NoopTransport()  # type: ignore[assignment]
        await adapter._handle(
            SessionCreatedServerEvent(
                event_id="event_duplicate",
                session_id="session_synthetic_1",
            ),
            generation=2,
        )
        await adapter._handle(
            SessionUpdatedServerEvent(
                event_id="event_duplicate",
                session_id="session_synthetic_1",
                configuration=CONFIGURATION,
            ),
            generation=2,
        )
        assert adapter.provider_context_state == "TAINTED"

    asyncio.run(scenario())


def test_exactly_one_pump_and_serialized_sender() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        transport = ConcurrentTransport(
            [
                SessionCreatedServerEvent(
                    event_id="event_created",
                    session_id="session_synthetic_1",
                ),
                SessionUpdatedServerEvent(
                    event_id="event_updated",
                    session_id="session_synthetic_1",
                    configuration=CONFIGURATION,
                ),
            ]
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        await adapter.attach_open_transport(transport)
        with pytest.raises(RuntimeError, match="second_pump"):
            await adapter.attach_open_transport(transport)
        for _ in range(20):
            if adapter.provider_context_state == "CLEAN":
                break
            await asyncio.sleep(0)
        assert adapter.provider_context_state == "CLEAN"

        results = await asyncio.gather(
            *(adapter.append_audio(b"\x00\x00") for _ in range(8))
        )
        assert all(results)
        assert transport.max_concurrent_recv == 1
        assert transport.max_concurrent_send == 1
        assert sum(
            isinstance(event, InputAudioBufferAppendClientEvent)
            for event in transport.sent
        ) == 8
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_non_clean_audio_is_dropped_and_never_replayed() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        transport = ConcurrentTransport([])
        adapter._transport = transport  # type: ignore[assignment]
        assert await adapter.append_audio(b"\x01\x02") is False
        assert transport.sent == []
        adapter.fence_for_generation(generation=2, playback_epoch=1)
        assert await adapter.append_audio(b"\x03\x04") is False
        assert transport.sent == []

    asyncio.run(scenario())


def test_old_generation_pump_event_drops_before_sequence_or_state_mutation() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        transport = ControlledReceiveTransport(
            SessionCreatedServerEvent(
                event_id="event_old_created",
                session_id="session_old",
            )
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        await adapter.attach_open_transport(transport)
        await transport.recv_started.wait()
        before_seq = adapter.provider_event_seq

        adapter.fence_for_generation(generation=2, playback_epoch=1)
        transport.release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert adapter.provider_event_seq == before_seq
        assert adapter.provider_context_state == "REBUILDING"
        assert not sink.frames
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_old_generation_pump_failure_cannot_taint_new_generation() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        transport = ControlledFailureTransport()
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        await adapter.attach_open_transport(transport)
        await transport.recv_started.wait()

        adapter.fence_for_generation(generation=2, playback_epoch=1)
        transport.release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert adapter.provider_context_state == "REBUILDING"
        assert not sink.frames
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_rebuild_projection_uses_opaque_provider_event_refs() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        adapter.fence_for_generation(generation=1, playback_epoch=0)
        raw_provider_event_id = "raw_provider_event_42"

        await adapter._handle(
            SessionUpdatedServerEvent(
                event_id=raw_provider_event_id,
                session_id="session_synthetic_1",
                configuration=CONFIGURATION,
            ),
            generation=1,
        )

        rebuild = next(
            frame
            for frame in sink.frames
            if isinstance(frame, RebuildRequestedProjectionV1)
        )
        assert raw_provider_event_id not in rebuild.source_event_id_refs
        assert all(
            ref.startswith("provider-event-ref://local/g1/")
            for ref in rebuild.source_event_id_refs
        )

    asyncio.run(scenario())


def test_provider_context_projection_binds_epoch_and_state_version_consistently() -> None:
    async def scenario() -> None:
        sink = CollectingSink()
        adapter = QwenRealtimeSessionAdapter(
            configuration=CONFIGURATION,
            projection_sink=sink,
            quarantine=CandidateQuarantine(),
            text_store=EphemeralTextStore(),
        )
        adapter.fence_for_generation(generation=1, playback_epoch=4)
        adapter._transport = NoopTransport()  # type: ignore[assignment]
        await adapter._handle(
            SessionCreatedServerEvent(
                event_id="event_created_epoch",
                session_id="session_epoch",
            ),
            generation=1,
        )
        await adapter._handle(
            SessionUpdatedServerEvent(
                event_id="event_updated_epoch",
                session_id="session_epoch",
                configuration=CONFIGURATION,
            ),
            generation=1,
        )
        context = [
            frame
            for frame in sink.frames
            if isinstance(frame, ProviderContextProjectionV1)
        ][-1]
        assert context.playback_epoch == 4
        assert context.interaction_state_version == 4

    asyncio.run(scenario())
