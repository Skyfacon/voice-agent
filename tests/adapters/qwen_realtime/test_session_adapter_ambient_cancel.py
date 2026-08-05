from __future__ import annotations

import asyncio

from voice_agent.adapters.qwen_realtime.ephemeral_text_store import EphemeralTextStore
from voice_agent.adapters.qwen_realtime.projections import (
    AmbientTerminalProjectionV1,
    CandidateObservationProjectionV1,
    FinalASRReadyProjectionV1,
    ProviderContextProjectionV1,
    RebuildRequestedProjectionV1,
    SpeechBoundaryProjectionV1,
)
from voice_agent.adapters.qwen_realtime.protocol import (
    AmbientTranscriptionCompletedServerEvent,
    AmbientTranscriptionDeltaServerEvent,
    ConversationItemCreatedServerEvent,
    ConversationItemDeletedServerEvent,
    ErrorServerEvent,
    InputTranscriptionCompletedServerEvent,
    QwenSessionConfiguration,
    ResponseAudioDeltaServerEvent,
    ResponseCancelClientEvent,
    ResponseCreatedServerEvent,
    ResponseDoneServerEvent,
    ResponseOutputItemAddedServerEvent,
    SessionCreatedServerEvent,
    SessionUpdatedServerEvent,
    SpeechStartedServerEvent,
    SpeechStoppedServerEvent,
)
from voice_agent.adapters.qwen_realtime.quarantine import (
    CandidateQuarantine,
    CommittedCandidateBinding,
)
from voice_agent.adapters.qwen_realtime.session_adapter import QwenRealtimeSessionAdapter
from voice_agent.adapters.qwen_realtime.transport import QwenTransportClosedError


CONFIGURATION = QwenSessionConfiguration(
    turn_detection_type="smart_turn",
    modalities=("text", "audio"),
    voice="synthetic_voice",
    input_audio_transcription=(("model", "synthetic_asr"),),
    tools=(),
    fast_role_profile="fast-role://synthetic/v1",
)


class CollectingSink:
    def __init__(self) -> None:
        self.frames: list[object] = []

    async def accept(self, frame: object) -> None:
        self.frames.append(frame)


class BlockingCleanupSink(CollectingSink):
    """Holds only the CLEANUP_PENDING projection, between state mutation and wire send."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def accept(self, frame: object) -> None:
        if (
            isinstance(frame, ProviderContextProjectionV1)
            and frame.to_state == "CLEANUP_PENDING"
        ):
            self.entered.set()
            await self.release.wait()
        self.frames.append(frame)


class BlockingStoppedSink(CollectingSink):
    """Holds a gen-1 STOPPED projection before turn-invalid continuation."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def accept(self, frame: object) -> None:
        if (
            isinstance(frame, SpeechBoundaryProjectionV1)
            and frame.boundary == "STOPPED"
        ):
            self.entered.set()
            await self.release.wait()
        self.frames.append(frame)


class PermitQueueTransport:
    """Pump-only driver: tests may release one provider frame, never call adapter internals."""

    _CLOSE = object()

    def __init__(self) -> None:
        self.sent: list[object] = []
        self._incoming: asyncio.Queue[object] = asyncio.Queue()
        self.recv_count = 0
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def send(self, event: object) -> None:
        self.sent.append(event)

    async def recv(self) -> object:
        item = await self._incoming.get()
        self.recv_count += 1
        if item is self._CLOSE:
            raise QwenTransportClosedError()
        return item

    async def close(self) -> None:
        self.closed = True
        self._incoming.put_nowait(self._CLOSE)

    def release(self, event: object) -> None:
        assert self.opened and not self.closed
        self._incoming.put_nowait(event)


class BlockingSendPermitQueueTransport(PermitQueueTransport):
    def __init__(self) -> None:
        super().__init__()
        self.hold_sends = False
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()
        self.release_send.set()

    async def send(self, event: object) -> None:
        if self.hold_sends:
            self.send_started.set()
            await self.release_send.wait()
        await super().send(event)

    def hold_next_send(self) -> None:
        self.hold_sends = True
        self.send_started.clear()
        self.release_send.clear()


async def _settle() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


async def _deliver(transport: PermitQueueTransport, event: object) -> None:
    before = transport.recv_count
    transport.release(event)
    for _ in range(20):
        await asyncio.sleep(0)
        if transport.recv_count == before + 1:
            break
    assert transport.recv_count == before + 1
    await _settle()


async def ready_adapter(
    transport: PermitQueueTransport | None = None,
    *,
    sink: CollectingSink | None = None,
) -> tuple[QwenRealtimeSessionAdapter, CollectingSink, PermitQueueTransport]:
    sink = sink or CollectingSink()
    store = EphemeralTextStore()
    adapter = QwenRealtimeSessionAdapter(
        configuration=CONFIGURATION,
        projection_sink=sink,
        quarantine=CandidateQuarantine(text_store=store),
        text_store=store,
    )
    wire = transport or PermitQueueTransport()
    adapter.fence_for_generation(generation=1, playback_epoch=7)
    await wire.open()
    await adapter.attach_open_transport(wire)
    await _deliver(wire, SessionCreatedServerEvent(
        event_id="event_session_created", session_id="session_synthetic_1"
    ))
    await _deliver(wire, SessionUpdatedServerEvent(
        event_id="event_session_updated", session_id="session_synthetic_1", configuration=CONFIGURATION
    ))
    assert adapter.provider_context_state == "CLEAN"
    return adapter, sink, wire


async def open_response(transport: PermitQueueTransport) -> None:
    await _deliver(transport, SpeechStartedServerEvent(
        event_id="event_speech_started", item_id="input_synthetic_1", audio_start_ms=0
    ))
    await _deliver(transport, ResponseCreatedServerEvent(
        event_id="event_response_created", response_id="response_synthetic_1", response_status="in_progress"
    ))


def test_ambient_transcription_uses_temporary_item_only_and_unique_terminal_is_tombstoned() -> None:
    async def scenario() -> None:
        adapter, sink, transport = await ready_adapter()
        await _deliver(transport, AmbientTranscriptionDeltaServerEvent(
            event_id="event_ambient_delta", item_id="temporary_ambient_1", content_index=0, text="ambient", stash=""
        ))
        await _deliver(transport, AmbientTranscriptionCompletedServerEvent(
            event_id="event_ambient_completed", item_id="temporary_ambient_1", content_index=0, transcript="ambient"
        ))
        ambient = [f for f in sink.frames if isinstance(f, AmbientTerminalProjectionV1)]
        assert len(ambient) == 1
        assert ambient[0].temporary_item_ref == "temporary_ambient_1"
        assert not any(isinstance(f, FinalASRReadyProjectionV1) for f in sink.frames)
        await _deliver(transport, AmbientTranscriptionCompletedServerEvent(
            event_id="event_ambient_completed_again_unique", item_id="temporary_ambient_1", content_index=0, transcript="ambient"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_turn_invalid_output_first_cancels_and_deletes_known_speculation_without_authority() -> None:
    async def scenario() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        # Output-first is a legal wire order. It already reveals the item that
        # must be removed if local ingress is later rejected.
        await _deliver(transport, ResponseOutputItemAddedServerEvent(
            event_id="event_output_first", response_id="response_synthetic_1", output_index=0,
            item_id="assistant_synthetic_1", item_type="message", item_status="in_progress", role="assistant"
        ))
        await _deliver(transport, SpeechStoppedServerEvent(
            event_id="event_turn_invalid", item_id="input_synthetic_1", audio_end_ms=30, stop_reason="turn_invalid"
        ))
        assert [event.type for event in transport.sent[-2:]] == ["response.cancel", "conversation.item.delete"]
        assert not any(isinstance(f, FinalASRReadyProjectionV1) for f in sink.frames)
        cancelled = [f for f in sink.frames if isinstance(f, CandidateObservationProjectionV1) and f.observation == "CANCELLED"]
        assert len(cancelled) == 1
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_explicit_and_auto_cancel_race_emits_one_terminal_and_no_epoch_change() -> None:
    async def scenario() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        epoch = adapter.playback_epoch
        assert await adapter.cancel_active_response() is True
        assert isinstance(transport.sent[-1], ResponseCancelClientEvent)
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_response_cancelled", response_id="response_synthetic_1",
            terminal_status="cancelled", response_terminal_reason="client_cancelled"
        ))
        await _deliver(transport, ErrorServerEvent(
            event_id="event_late_invalid_cancel", error_type="invalid_request_error", error_code="response_already_cancelled"
        ))
        assert adapter.provider_context_state == "CLEAN"
        assert adapter.playback_epoch == epoch
        terminals = [f for f in sink.frames if isinstance(f, CandidateObservationProjectionV1) and f.observation == "CANCELLED"]
        assert len(terminals) == 1
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_benign_late_cancel_error_requires_a_cancelled_terminal() -> None:
    async def scenario() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_response_failed",
            response_id="response_synthetic_1",
            terminal_status="failed",
        ))
        await _deliver(transport, ErrorServerEvent(
            event_id="event_spurious_late_cancel_error",
            error_type="invalid_request_error",
            error_code="response_already_cancelled",
        ))

        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_late_pcm_after_cancel_and_old_generation_pcm_are_wiped_and_dropped() -> None:
    async def scenario() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        assert await adapter.cancel_active_response()
        late = ResponseAudioDeltaServerEvent(
            event_id="event_late_pcm", response_id="response_synthetic_1", item_id="assistant_synthetic_1",
            output_index=0, content_index=0, pcm=bytearray(b"\x01\x02" * 8)
        )
        await _deliver(transport, late)
        assert late.pcm == bytearray(len(late.pcm))
        adapter.fence_for_generation(generation=2, playback_epoch=8)
        # This item was queued before the old Pump was fenced. Releasing it can
        # only exercise the old generation path; no fresh adapter call is made.
        old = ResponseAudioDeltaServerEvent(
            event_id="event_old_pcm", response_id="response_synthetic_1", item_id="assistant_synthetic_1",
            output_index=0, content_index=0, pcm=bytearray(b"\x03\x04" * 8)
        )
        transport.release(old)
        await _settle()
        assert old.pcm == bytearray(len(old.pcm))
        assert not any(isinstance(f, RebuildRequestedProjectionV1) and f.provider_session_generation == 2 for f in sink.frames)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_missing_cancel_terminal_and_delete_ack_timeout_taint_and_rebuild() -> None:
    async def scenario() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        assert await adapter.cancel_active_response()
        assert await adapter.expire_pending_cancel() is True
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

        adapter, sink, transport = await ready_adapter()
        assert await adapter.delete_assistant_item("assistant_synthetic_1")
        await _deliver(transport, ConversationItemDeletedServerEvent(
            event_id="event_wrong_delete_ack", item_id="assistant_synthetic_2"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

        adapter, sink, transport = await ready_adapter()
        assert await adapter.delete_assistant_item("assistant_synthetic_1")
        assert await adapter.expire_pending_delete() is True
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_matching_delete_ack_returns_cleanup_to_clean() -> None:
    async def scenario() -> None:
        adapter, _, transport = await ready_adapter()
        assert await adapter.delete_assistant_item("assistant_synthetic_1")
        assert adapter.provider_context_state == "CLEANUP_PENDING"
        await _deliver(transport, ConversationItemDeletedServerEvent(
            event_id="event_delete_ack", item_id="assistant_synthetic_1"
        ))
        assert adapter.provider_context_state == "CLEAN"
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_blocked_cancel_and_delete_sends_accept_later_ack_or_terminal_without_race() -> None:
    async def scenario() -> None:
        wire = BlockingSendPermitQueueTransport()
        adapter, sink, transport = await ready_adapter(wire)
        await open_response(transport)
        wire.hold_next_send()
        cancelling = asyncio.create_task(adapter.cancel_active_response())
        await wire.send_started.wait()
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_cancel_terminal_while_blocked", response_id="response_synthetic_1",
            terminal_status="cancelled", response_terminal_reason="client_cancelled"
        ))
        wire.release_send.set()
        assert await cancelling is True
        await _settle()
        assert adapter.provider_context_state == "CLEAN"
        assert sum(isinstance(f, CandidateObservationProjectionV1) and f.observation == "CANCELLED" for f in sink.frames) == 1
        await adapter.stop_pump()

        wire = BlockingSendPermitQueueTransport()
        adapter, _, transport = await ready_adapter(wire)
        wire.hold_next_send()
        deleting = asyncio.create_task(adapter.delete_assistant_item("assistant_synthetic_1"))
        await wire.send_started.wait()
        await _deliver(transport, ConversationItemDeletedServerEvent(
            event_id="event_delete_ack_while_blocked", item_id="assistant_synthetic_1"
        ))
        wire.release_send.set()
        assert await deleting is True
        await _settle()
        assert adapter.provider_context_state == "CLEAN"
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_auto_cancel_cannot_claim_client_cancelled_reason_and_completed_after_invalid_fails_closed() -> None:
    async def scenario() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_invalid_auto_cancel_reason", response_id="response_synthetic_1",
            terminal_status="cancelled", response_terminal_reason="client_cancelled"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        await _deliver(transport, SpeechStoppedServerEvent(
            event_id="event_turn_invalid_before_completed", item_id="input_synthetic_1", audio_end_ms=30, stop_reason="turn_invalid"
        ))
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_completed_after_cancel", response_id="response_synthetic_1", terminal_status="completed"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_fence_during_cleanup_projection_prevents_old_delete_send_and_wire_sequence_increment() -> None:
    async def scenario() -> None:
        sink = BlockingCleanupSink()
        adapter, _, transport = await ready_adapter(sink=sink)
        before_sequence = adapter.wire_send_seq
        deleting = asyncio.create_task(
            adapter.delete_assistant_item("assistant_synthetic_1")
        )
        await sink.entered.wait()
        adapter.fence_for_generation(generation=2, playback_epoch=8)
        sink.release.set()
        assert await deleting is False
        assert adapter.wire_send_seq == before_sequence
        assert not any(
            getattr(event, "type", None) == "conversation.item.delete"
            for event in transport.sent
        )
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_fence_during_blocked_turn_invalid_stopped_projection_cannot_reject_or_terminalize_generation_two() -> None:
    async def scenario() -> None:
        sink = BlockingStoppedSink()
        adapter, _, old_transport = await ready_adapter(sink=sink)
        await _deliver(old_transport, SpeechStartedServerEvent(
            event_id="event_gen1_speech", item_id="input_gen1", audio_start_ms=0
        ))
        old_transport.release(SpeechStoppedServerEvent(
            event_id="event_gen1_turn_invalid", item_id="input_gen1",
            audio_end_ms=20, stop_reason="turn_invalid",
        ))
        await sink.entered.wait()

        adapter.fence_for_generation(generation=2, playback_epoch=8)
        sink.release.set()
        await _settle()

        assert not any(
            isinstance(frame, SpeechBoundaryProjectionV1)
            and frame.provider_session_generation == 1
            and frame.boundary == "STOPPED"
            for frame in sink.frames
        )
        # Public join state exposes cross-generation contamination without
        # requiring the provider to reuse an item identifier in generation 2.
        assert adapter.asr_join_disposition("input_gen1").status == (
            "WAITING_PROVIDER_FINAL"
        )
        await adapter.stop_pump()

        current_transport = PermitQueueTransport()
        await current_transport.open()
        await adapter.attach_open_transport(current_transport)
        await _deliver(current_transport, SessionCreatedServerEvent(
            event_id="event_gen2_created", session_id="session_gen2"
        ))
        await _deliver(current_transport, SessionUpdatedServerEvent(
            event_id="event_gen2_updated", session_id="session_gen2",
            configuration=CONFIGURATION,
        ))
        await _deliver(current_transport, SpeechStartedServerEvent(
            event_id="event_gen2_speech", item_id="input_gen2", audio_start_ms=30
        ))
        binding = CommittedCandidateBinding(
            "turn_gen2", "utterance_gen2", "context_gen2"
        )
        assert adapter.bind_committed_turn(
            input_item_ref="input_gen2", binding=binding
        ).status == "WAITING_PROVIDER_FINAL"
        await _deliver(current_transport, InputTranscriptionCompletedServerEvent(
            event_id="event_gen2_asr", item_id="input_gen2",
            content_index=0, transcript="generation two request",
        ))
        await _deliver(current_transport, ResponseCreatedServerEvent(
            event_id="event_gen2_response", response_id="response_gen2",
            response_status="in_progress",
        ))

        assert adapter.provider_context_state == "CLEAN"
        assert any(
            isinstance(frame, FinalASRReadyProjectionV1)
            and frame.provider_session_generation == 2
            and frame.qwen_input_item_ref == "input_gen2"
            for frame in sink.frames
        )
        assert not any(
            isinstance(frame, CandidateObservationProjectionV1)
            and frame.provider_session_generation == 2
            and frame.observation in {"CANCELLED", "DISCARDED"}
            for frame in sink.frames
        )
        assert not any(
            getattr(event, "type", None)
            in {"response.cancel", "conversation.item.delete"}
            for event in current_transport.sent
        )
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_fence_during_reject_continuation_cannot_cancel_or_mutate_new_owner() -> None:
    async def scenario() -> None:
        wire = BlockingSendPermitQueueTransport()
        adapter, _, transport = await ready_adapter(wire)
        await open_response(transport)
        wire.hold_next_send()
        rejecting = asyncio.create_task(adapter.reject_or_hold_ingress(
            input_item_ref="input_synthetic_1", disposition="rejected"
        ))
        await wire.send_started.wait()
        adapter.fence_for_generation(generation=2, playback_epoch=8)
        wire.release_send.set()
        # A send that was already inside the transport is not retractable. The
        # post-await continuation, however, must not discard or terminalize the
        # generation-2 owner.
        assert await rejecting is True
        await adapter.stop_pump()

        wire.hold_sends = False
        current_transport = PermitQueueTransport()
        await current_transport.open()
        await adapter.attach_open_transport(current_transport)
        await _deliver(current_transport, SessionCreatedServerEvent(
            event_id="event_new_owner_created", session_id="session_new_owner"
        ))
        await _deliver(current_transport, SessionUpdatedServerEvent(
            event_id="event_new_owner_updated", session_id="session_new_owner", configuration=CONFIGURATION
        ))
        await _deliver(current_transport, SpeechStartedServerEvent(
            event_id="event_new_owner_speech", item_id="input_new_owner", audio_start_ms=10
        ))
        await _deliver(current_transport, ResponseCreatedServerEvent(
            event_id="event_new_owner_response", response_id="response_new_owner", response_status="in_progress"
        ))
        assert adapter.provider_context_state == "CLEAN"
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_auto_cancel_late_pcm_drops_but_benign_error_requires_actual_explicit_cancel_race() -> None:
    async def auto_only_case() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_auto_cancelled", response_id="response_synthetic_1",
            terminal_status="cancelled", response_terminal_reason="turn_detected"
        ))
        late = ResponseAudioDeltaServerEvent(
            event_id="event_auto_late_pcm", response_id="response_synthetic_1", item_id="assistant_synthetic_1",
            output_index=0, content_index=0, pcm=bytearray(b"\x01\x02" * 4)
        )
        await _deliver(transport, late)
        assert late.pcm == bytearray(len(late.pcm))
        assert adapter.provider_context_state == "CLEAN"
        await _deliver(transport, ErrorServerEvent(
            event_id="event_auto_benign_error", error_type="invalid_request_error", error_code="response_already_cancelled"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    async def actual_race_case() -> None:
        adapter, sink, transport = await ready_adapter()
        await open_response(transport)
        assert await adapter.cancel_active_response() is True
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_explicit_auto_race", response_id="response_synthetic_1",
            terminal_status="cancelled", response_terminal_reason="turn_detected"
        ))
        await _deliver(transport, ErrorServerEvent(
            event_id="event_race_benign_error_once", error_type="invalid_request_error", error_code="response_already_cancelled"
        ))
        assert adapter.provider_context_state == "CLEAN"
        await adapter.stop_pump()

    async def scenario() -> None:
        await auto_only_case()
        await actual_race_case()

    asyncio.run(scenario())
