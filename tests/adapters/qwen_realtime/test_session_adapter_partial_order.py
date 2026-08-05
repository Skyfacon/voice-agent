from __future__ import annotations

import asyncio

import pytest

from voice_agent.adapters.qwen_realtime.ephemeral_text_store import EphemeralTextStore
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateCompletionV1,
    CandidateObservationProjectionV1,
    CandidateTranscriptCompleteV1,
    FinalASRReadyProjectionV1,
    RebuildRequestedProjectionV1,
    SpeechBoundaryProjectionV1,
)
from voice_agent.adapters.qwen_realtime.protocol import (
    ConversationItemCreatedServerEvent,
    InputTranscriptionCompletedServerEvent,
    InputTranscriptionDeltaServerEvent,
    InputTranscriptionFailedServerEvent,
    QwenOutputItemSnapshot,
    QwenSessionConfiguration,
    ResponseAudioDeltaServerEvent,
    ResponseAudioDoneServerEvent,
    ResponseAudioTranscriptDeltaServerEvent,
    ResponseAudioTranscriptDoneServerEvent,
    ResponseContentPartAddedServerEvent,
    ResponseContentPartDoneServerEvent,
    ResponseCreatedServerEvent,
    ResponseDoneServerEvent,
    ResponseOutputItemAddedServerEvent,
    ResponseOutputItemDoneServerEvent,
    SessionCreatedServerEvent,
    SessionUpdatedServerEvent,
    SpeechStartedServerEvent,
    SpeechStoppedServerEvent,
)
from voice_agent.adapters.qwen_realtime.quarantine import (
    CandidateLimitsV1,
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
BINDING = CommittedCandidateBinding(
    turn_id="turn_synthetic_1",
    utterance_id="utterance_synthetic_1",
    context_snapshot_id="context_synthetic_1",
)
BINDING_2 = CommittedCandidateBinding(
    turn_id="turn_synthetic_2",
    utterance_id="utterance_synthetic_2",
    context_snapshot_id="context_synthetic_2",
)


class CollectingSink:
    def __init__(self) -> None:
        self.frames: list[object] = []

    async def accept(self, frame: object) -> None:
        self.frames.append(frame)


class BlockingSink(CollectingSink):
    """Test-only projection sink to hold a handler after it has reached sink I/O."""

    def __init__(self, block_type: type[object]) -> None:
        super().__init__()
        self._block_type = block_type
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def accept(self, frame: object) -> None:
        if isinstance(frame, self._block_type):
            self.entered.set()
            await self.release.wait()
        self.frames.append(frame)


class PermitQueueTransport:
    """A test-local transport which releases exactly one server frame at a time."""

    _CLOSE = object()

    def __init__(self) -> None:
        self.sent: list[object] = []
        self._incoming: asyncio.Queue[object] = asyncio.Queue()
        self.opened = False
        self.closed = False
        self.recv_count = 0

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
        self.release_close()

    def release(self, event: object) -> None:
        assert self.opened and not self.closed
        self._incoming.put_nowait(event)

    def release_close(self) -> None:
        self._incoming.put_nowait(self._CLOSE)


async def _settle() -> None:
    # Pump processing has no public acknowledgement by design. Yielding here is
    # deliberately bounded and each test releases only one server event first.
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
    *, sink: CollectingSink | None = None,
) -> tuple[QwenRealtimeSessionAdapter, CollectingSink, PermitQueueTransport, EphemeralTextStore]:
    sink = sink or CollectingSink()
    text_store = EphemeralTextStore()
    adapter = QwenRealtimeSessionAdapter(
        configuration=CONFIGURATION,
        projection_sink=sink,
        quarantine=CandidateQuarantine(
            limits=CandidateLimitsV1(
                max_transcript_unicode_scalars=80,
                max_pcm_bytes=4096,
                max_pcm_chunks=8,
                max_audio_duration_ms=2000,
            ),
            text_store=text_store,
        ),
        text_store=text_store,
    )
    transport = PermitQueueTransport()
    adapter.fence_for_generation(generation=1, playback_epoch=4)
    await transport.open()
    await adapter.attach_open_transport(transport)
    await _deliver(transport, SessionCreatedServerEvent(
        event_id="event_session_created", session_id="session_synthetic_1"
    ))
    await _deliver(transport, SessionUpdatedServerEvent(
        event_id="event_session_updated",
        session_id="session_synthetic_1",
        configuration=CONFIGURATION,
    ))
    assert adapter.provider_context_state == "CLEAN"
    return adapter, sink, transport, text_store


async def start_response(
    transport: PermitQueueTransport,
    *,
    response_id: str = "response_synthetic_1",
    input_id: str = "input_synthetic_1",
    prefix: str = "event",
) -> None:
    await _deliver(transport, SpeechStartedServerEvent(
        event_id=f"{prefix}_speech_started", item_id=input_id, audio_start_ms=0
    ))
    await _deliver(transport, ResponseCreatedServerEvent(
        event_id=f"{prefix}_response_created",
        response_id=response_id,
        response_status="in_progress",
    ))


async def add_output(
    transport: PermitQueueTransport,
    *,
    response_id: str = "response_synthetic_1",
    item_id: str = "assistant_synthetic_1",
    output_first: bool,
    prefix: str = "event",
) -> None:
    assistant = ConversationItemCreatedServerEvent(
        event_id=f"{prefix}_assistant_item", item_id=item_id,
        item_type="message", item_status="in_progress", role="assistant",
    )
    output = ResponseOutputItemAddedServerEvent(
        event_id=f"{prefix}_output_item", response_id=response_id,
        output_index=0, item_id=item_id, item_type="message",
        item_status="in_progress", role="assistant",
    )
    for event in ((output, assistant) if output_first else (assistant, output)):
        await _deliver(transport, event)
    await _deliver(transport, ResponseContentPartAddedServerEvent(
        event_id=f"{prefix}_content_added", response_id=response_id,
        item_id=item_id, output_index=0, content_index=0, content_type="audio",
    ))


async def finish_response(
    transport: PermitQueueTransport,
    *,
    response_id: str = "response_synthetic_1",
    item_id: str = "assistant_synthetic_1",
    pcm_first: bool,
    prefix: str = "event",
) -> None:
    transcript = ResponseAudioTranscriptDeltaServerEvent(
        event_id=f"{prefix}_transcript_delta", response_id=response_id,
        item_id=item_id, output_index=0, content_index=0, delta="synthetic answer",
    )
    pcm = ResponseAudioDeltaServerEvent(
        event_id=f"{prefix}_audio_delta", response_id=response_id, item_id=item_id,
        output_index=0, content_index=0, pcm=bytearray(b"\x01\x02" * 48),
    )
    for event in ((pcm, transcript) if pcm_first else (transcript, pcm)):
        await _deliver(transport, event)
    await _deliver(transport, ResponseAudioTranscriptDoneServerEvent(
        event_id=f"{prefix}_transcript_done", response_id=response_id, item_id=item_id,
        output_index=0, content_index=0, transcript="synthetic answer",
    ))
    await _deliver(transport, ResponseAudioDoneServerEvent(
        event_id=f"{prefix}_audio_done", response_id=response_id, item_id=item_id,
        output_index=0, content_index=0,
    ))
    await _deliver(transport, ResponseContentPartDoneServerEvent(
        event_id=f"{prefix}_content_done", response_id=response_id, item_id=item_id,
        output_index=0, content_index=0, content_type="audio",
    ))
    await _deliver(transport, ResponseOutputItemDoneServerEvent(
        event_id=f"{prefix}_output_done", response_id=response_id, output_index=0,
        item_id=item_id, item_type="message", item_status="completed", role="assistant",
    ))
    await _deliver(transport, ResponseDoneServerEvent(
        event_id=f"{prefix}_response_done", response_id=response_id,
        terminal_status="completed",
        output_items=(QwenOutputItemSnapshot(
            item_id=item_id, item_type="message", item_status="completed", role="assistant",
        ),),
    ))


@pytest.mark.parametrize("provider_final_first", (False, True))
def test_asr_final_and_local_commit_join_exactly_once(provider_final_first: bool) -> None:
    async def scenario() -> None:
        adapter, sink, transport, text_store = await ready_adapter()
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_asr_speech_started",
            item_id="input_synthetic_1",
            audio_start_ms=0,
        ))
        final = InputTranscriptionCompletedServerEvent(
            event_id="event_asr_final", item_id="input_synthetic_1", content_index=0,
            transcript="A" * 2000,
        )
        if provider_final_first:
            await _deliver(transport, final)
            disposition = adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        else:
            disposition = adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
            assert disposition.status == "WAITING_PROVIDER_FINAL"
            await _deliver(transport, final)
            disposition = adapter.asr_join_disposition("input_synthetic_1")
        assert disposition.status == "READY"
        projection = disposition.final_asr_projection
        assert isinstance(projection, FinalASRReadyProjectionV1)
        assert projection.transcript_unicode_scalar_count == 2000
        with text_store.resolve(projection.transcript_ref, expected_kind="asr", expected_digest=projection.transcript_digest, max_unicode_scalars=2000) as lease:
            assert lease.text == "A" * 2000
        await _settle()
        assert sum(isinstance(frame, FinalASRReadyProjectionV1) for frame in sink.frames) == 1
        with pytest.raises(RuntimeError, match="already_bound"):
            adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        await adapter.stop_pump()

    asyncio.run(scenario())


@pytest.mark.parametrize("output_first", (False, True))
@pytest.mark.parametrize("pcm_first", (False, True))
def test_candidate_legal_partial_orders_emit_safe_completions_once(output_first: bool, pcm_first: bool) -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING).status == "WAITING_PROVIDER_FINAL"
        await add_output(transport, output_first=output_first)
        await finish_response(transport, pcm_first=pcm_first)
        opened = [f for f in sink.frames if isinstance(f, CandidateObservationProjectionV1) and f.observation == "OPENED"]
        transcripts = [f for f in sink.frames if isinstance(f, CandidateTranscriptCompleteV1)]
        completions = [f for f in sink.frames if isinstance(f, CandidateCompletionV1)]
        assert len(opened) == len(transcripts) == len(completions) == 1
        transcript, completion = transcripts[0], completions[0]
        assert opened[0].candidate_ref == transcript.candidate_ref == completion.candidate_ref
        facts = completion.eligibility_facts
        assert transcript.provider_session_generation == 1
        assert transcript.qwen_response_id == "response_synthetic_1"
        assert facts.qwen_output_item_id == "assistant_synthetic_1"
        assert facts.qwen_output_index == facts.qwen_content_index == 0
        assert (facts.turn_id, facts.utterance_id, facts.context_snapshot_id) == (BINDING.turn_id, BINDING.utterance_id, BINDING.context_snapshot_id)
        assert facts.bound_playback_epoch == 4
        assert facts.candidate_audio_duration_ms == 2
        assert facts.candidate_transcript_digest == transcript.candidate_transcript_digest
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_response_terminals_before_late_binding_emit_transcript_then_full_completion_in_order() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        await add_output(transport, output_first=True)
        await finish_response(transport, pcm_first=False)
        assert not any(isinstance(f, CandidateTranscriptCompleteV1) for f in sink.frames)
        assert not any(isinstance(f, CandidateCompletionV1) for f in sink.frames)
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING).status == "WAITING_PROVIDER_FINAL"
        await adapter.flush_deferred_projections()
        terminal_indexes = [
            index for index, frame in enumerate(sink.frames)
            if isinstance(frame, (CandidateTranscriptCompleteV1, CandidateCompletionV1))
        ]
        assert [type(sink.frames[index]) for index in terminal_indexes] == [CandidateTranscriptCompleteV1, CandidateCompletionV1]
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_second_sequential_response_has_its_own_turn_and_completes_before_simultaneous_second_response_fails_closed() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        await add_output(transport, output_first=False)
        adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        await finish_response(transport, pcm_first=False)
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_second_speech_started", item_id="input_synthetic_2", audio_start_ms=100
        ))
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_2", binding=BINDING_2).status == "WAITING_PROVIDER_FINAL"
        await _deliver(transport, ResponseCreatedServerEvent(
            event_id="event_response_created_second", response_id="response_synthetic_2", response_status="in_progress"
        ))
        await add_output(
            transport, response_id="response_synthetic_2", item_id="assistant_synthetic_2",
            output_first=True, prefix="event_second",
        )
        await finish_response(
            transport, response_id="response_synthetic_2", item_id="assistant_synthetic_2",
            pcm_first=True, prefix="event_second",
        )
        assert adapter.provider_context_state == "CLEAN"
        completions = [f for f in sink.frames if isinstance(f, CandidateCompletionV1)]
        assert len(completions) == 2
        assert [f.eligibility_facts.turn_id for f in completions] == [BINDING.turn_id, BINDING_2.turn_id]
        await adapter.stop_pump()

        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        await _deliver(transport, ResponseCreatedServerEvent(
            event_id="event_response_created_simultaneous", response_id="response_synthetic_2", response_status="in_progress"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_failed_asr_cannot_be_resurrected_by_later_completed_terminal() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await _deliver(transport, SpeechStartedServerEvent(event_id="event_speech", item_id="input_synthetic_1", audio_start_ms=0))
        await _deliver(transport, InputTranscriptionFailedServerEvent(
            event_id="event_asr_failed", item_id="input_synthetic_1", content_index=0,
            error_type="server_error", error_code="synthetic_failure", error_message="synthetic"
        ))
        await _deliver(transport, InputTranscriptionCompletedServerEvent(
            event_id="event_asr_late_completed", item_id="input_synthetic_1", content_index=0, transcript="resurrected"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert not any(isinstance(f, FinalASRReadyProjectionV1) for f in sink.frames)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_late_generation_binding_and_reused_input_id_fail_closed() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await _deliver(transport, SpeechStartedServerEvent(event_id="event_input_one", item_id="input_synthetic_1", audio_start_ms=0))
        adapter.fence_for_generation(generation=2, playback_epoch=5)
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING).status == "REJECTED"
        await adapter.stop_pump()
        # A second use of a current input item identifier must not silently adopt
        # the first turn's local authority.
        adapter, sink, transport, _ = await ready_adapter()
        await _deliver(transport, SpeechStartedServerEvent(event_id="event_input_first", item_id="input_synthetic_1", audio_start_ms=0))
        adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        await _deliver(transport, SpeechStartedServerEvent(event_id="event_input_reused", item_id="input_synthetic_1", audio_start_ms=10))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_unique_id_duplicate_response_done_taints_and_spontaneous_close_requests_rebuild() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        await add_output(transport, output_first=False)
        await finish_response(transport, pcm_first=False)
        await _deliver(transport, ResponseDoneServerEvent(
            event_id="event_response_done_duplicate_unique", response_id="response_synthetic_1", terminal_status="completed"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

        adapter, sink, transport, _ = await ready_adapter()
        transport.release_close()
        await _settle()
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_generation_fence_while_old_handler_is_blocked_never_delivers_old_frame_or_adopts_old_input() -> None:
    async def scenario() -> None:
        sink = BlockingSink(SpeechBoundaryProjectionV1)
        adapter, _, old_transport, _ = await ready_adapter(sink=sink)
        old_transport.release(SpeechStartedServerEvent(
            event_id="event_old_speech", item_id="input_old", audio_start_ms=0
        ))
        await sink.entered.wait()
        adapter.fence_for_generation(generation=2, playback_epoch=5)
        sink.release.set()
        await _settle()
        assert not any(
            isinstance(frame, SpeechBoundaryProjectionV1)
            and frame.provider_session_generation == 1
            for frame in sink.frames
        )
        # A fresh generation may become CLEAN, but it must not inherit the old
        # Pump's ingress identity after that handler is released.
        await adapter.stop_pump()
        current_transport = PermitQueueTransport()
        await current_transport.open()
        await adapter.attach_open_transport(current_transport)
        await _deliver(current_transport, SessionCreatedServerEvent(
            event_id="event_current_created", session_id="session_current"
        ))
        await _deliver(current_transport, SessionUpdatedServerEvent(
            event_id="event_current_updated", session_id="session_current", configuration=CONFIGURATION
        ))
        assert adapter.bind_committed_turn(input_item_ref="input_old", binding=BINDING).status == "REJECTED"
        await adapter.stop_pump()

    asyncio.run(scenario())


@pytest.mark.parametrize("disposition", ("rejected", "held"))
def test_final_asr_waiting_on_projection_lock_is_never_sunk_after_public_ingress_retraction(disposition: str) -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_asr_lock_speech", item_id="input_synthetic_1", audio_start_ms=0
        ))
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING).status == "WAITING_PROVIDER_FINAL"
        # This is scheduler control only: another ordered projection owns the
        # lock while the Pump has already captured the provider final.
        async with adapter._projection_lock:
            transport.release(InputTranscriptionCompletedServerEvent(
                event_id="event_asr_waiting", item_id="input_synthetic_1", content_index=0, transcript="request"
            ))
            await _settle()
            assert await adapter.reject_or_hold_ingress(
                input_item_ref="input_synthetic_1", disposition=disposition  # type: ignore[arg-type]
            ) is True
        await _settle()
        assert not any(isinstance(frame, FinalASRReadyProjectionV1) for frame in sink.frames)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_completed_response_identity_cannot_be_reused_after_other_response_or_directly() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        await add_output(transport, output_first=False)
        await finish_response(transport, pcm_first=False)
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_r2_speech", item_id="input_synthetic_2", audio_start_ms=10
        ))
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_2", binding=BINDING_2).status == "WAITING_PROVIDER_FINAL"
        await _deliver(transport, ResponseCreatedServerEvent(
            event_id="event_r2_created", response_id="response_synthetic_2", response_status="in_progress"
        ))
        await add_output(transport, response_id="response_synthetic_2", item_id="assistant_synthetic_2", output_first=False, prefix="event_r2")
        await finish_response(transport, response_id="response_synthetic_2", item_id="assistant_synthetic_2", pcm_first=False, prefix="event_r2")
        before_refs = [frame.candidate_ref for frame in sink.frames if isinstance(frame, CandidateObservationProjectionV1)]
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_r3_speech", item_id="input_synthetic_3", audio_start_ms=20
        ))
        assert adapter.bind_committed_turn(
            input_item_ref="input_synthetic_3",
            binding=CommittedCandidateBinding("turn_synthetic_3", "utterance_synthetic_3", "context_synthetic_3"),
        ).status == "WAITING_PROVIDER_FINAL"
        await _deliver(transport, ResponseCreatedServerEvent(
            event_id="event_r1_reused_after_r2", response_id="response_synthetic_1", response_status="in_progress"
        ))
        assert adapter.provider_context_state == "TAINTED"
        after_refs = [frame.candidate_ref for frame in sink.frames if isinstance(frame, CandidateObservationProjectionV1)]
        assert after_refs == before_refs
        await adapter.stop_pump()

        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        await add_output(transport, output_first=False)
        await finish_response(transport, pcm_first=False)
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_direct_reuse_speech", item_id="input_synthetic_2", audio_start_ms=10
        ))
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_2", binding=BINDING_2).status == "WAITING_PROVIDER_FINAL"
        await _deliver(transport, ResponseCreatedServerEvent(
            event_id="event_r1_direct_reuse", response_id="response_synthetic_1", response_status="in_progress"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_direct_reuse_of_a_terminal_response_identity_fails_before_duplicate_candidate_ref() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
        await add_output(transport, output_first=False)
        await finish_response(transport, pcm_first=False)
        before_refs = [frame.candidate_ref for frame in sink.frames if isinstance(frame, CandidateObservationProjectionV1)]
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_direct_reuse_speech_only", item_id="input_synthetic_2", audio_start_ms=10
        ))
        assert adapter.bind_committed_turn(input_item_ref="input_synthetic_2", binding=BINDING_2).status == "WAITING_PROVIDER_FINAL"
        await _deliver(transport, ResponseCreatedServerEvent(
            event_id="event_direct_reuse_terminal", response_id="response_synthetic_1", response_status="in_progress"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert [frame.candidate_ref for frame in sink.frames if isinstance(frame, CandidateObservationProjectionV1)] == before_refs
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_speech_stop_for_different_input_fails_closed() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_u1_started", item_id="input_u1", audio_start_ms=0
        ))
        await _deliver(transport, SpeechStoppedServerEvent(
            event_id="event_u2_stopped", item_id="input_u2", audio_end_ms=10
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("item_id", "content_index"),
    (("assistant_wrong", 0), ("assistant_synthetic_1", 1)),
)
def test_wrong_output_item_or_content_index_transcript_delta_fails_closed(item_id: str, content_index: int) -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        await add_output(transport, output_first=False)
        await _deliver(transport, ResponseAudioTranscriptDeltaServerEvent(
            event_id="event_wrong_content_delta", response_id="response_synthetic_1", item_id=item_id,
            output_index=0, content_index=content_index, delta="wrong identity"
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


def test_transcription_delta_after_asr_terminal_fails_closed() -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await _deliver(transport, SpeechStartedServerEvent(
            event_id="event_asr_terminal_speech", item_id="input_synthetic_1", audio_start_ms=0
        ))
        await _deliver(transport, InputTranscriptionCompletedServerEvent(
            event_id="event_asr_completed", item_id="input_synthetic_1", content_index=0, transcript="request"
        ))
        await _deliver(transport, InputTranscriptionDeltaServerEvent(
            event_id="event_delta_after_terminal", item_id="input_synthetic_1", content_index=0, text="late", stash=""
        ))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())


@pytest.mark.parametrize("terminal_status", ("completed", "failed"))
def test_late_pcm_after_non_cancel_terminal_taints_instead_of_silent_drop(terminal_status: str) -> None:
    async def scenario() -> None:
        adapter, sink, transport, _ = await ready_adapter()
        await start_response(transport)
        if terminal_status == "completed":
            adapter.bind_committed_turn(input_item_ref="input_synthetic_1", binding=BINDING)
            await add_output(transport, output_first=False)
            await finish_response(transport, pcm_first=False)
        else:
            await _deliver(transport, ResponseDoneServerEvent(
                event_id="event_failed_terminal", response_id="response_synthetic_1", terminal_status="failed"
            ))
        late = ResponseAudioDeltaServerEvent(
            event_id=f"event_late_pcm_{terminal_status}", response_id="response_synthetic_1", item_id="assistant_synthetic_1",
            output_index=0, content_index=0, pcm=bytearray(b"\x05\x06" * 4)
        )
        await _deliver(transport, late)
        assert late.pcm == bytearray(len(late.pcm))
        assert adapter.provider_context_state == "TAINTED"
        assert isinstance(sink.frames[-1], RebuildRequestedProjectionV1)
        await adapter.stop_pump()

    asyncio.run(scenario())
