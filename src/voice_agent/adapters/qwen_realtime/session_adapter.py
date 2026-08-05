from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from typing import Literal

from .ephemeral_text_store import (
    EphemeralTextRefV1,
    EphemeralTextStore,
    EphemeralTextStoreError,
)
from .projections import (
    AmbientTerminalProjectionV1,
    CandidateCompletionV1,
    CandidateObservationProjectionV1,
    CandidateTranscriptCompleteV1,
    FinalASRReadyProjectionV1,
    ProviderContextProjectionV1,
    QwenProjectionFrameV1,
    QwenProjectionSink,
    RebuildRequestedProjectionV1,
    SpeechBoundaryProjectionV1,
)
from .protocol import (
    AmbientTranscriptionCompletedServerEvent,
    AmbientTranscriptionDeltaServerEvent,
    ConversationItemDeleteClientEvent,
    ConversationItemDeletedServerEvent,
    ConversationItemCreatedServerEvent,
    ErrorServerEvent,
    InputAudioBufferAppendClientEvent,
    InputAudioCommittedServerEvent,
    InputTranscriptionCompletedServerEvent,
    InputTranscriptionDeltaServerEvent,
    InputTranscriptionFailedServerEvent,
    QwenClientEvent,
    QwenServerEvent,
    QwenSessionConfiguration,
    ResponseAudioDeltaServerEvent,
    ResponseAudioDoneServerEvent,
    ResponseAudioTranscriptDeltaServerEvent,
    ResponseAudioTranscriptDoneServerEvent,
    ResponseCancelClientEvent,
    ResponseContentPartAddedServerEvent,
    ResponseContentPartDoneServerEvent,
    ResponseCreatedServerEvent,
    ResponseDoneServerEvent,
    ResponseOutputItemAddedServerEvent,
    ResponseOutputItemDoneServerEvent,
    SessionCreatedServerEvent,
    SessionUpdateClientEvent,
    SessionUpdatedServerEvent,
    SpeechStartedServerEvent,
    SpeechStoppedServerEvent,
)
from .quarantine import (
    CandidateQuarantine,
    CandidateQuarantineError,
    CommittedCandidateBinding,
)
from .transport import QwenRealtimeTransport, QwenTransportClosedError


_BENIGN_LATE_CANCEL_ERROR_CODES = frozenset(
    {
        "response_already_cancelled",
        "response_cancel_not_active",
        "response_cancelled",
    }
)


@dataclass(frozen=True, slots=True)
class ASRJoinDispositionV1:
    status: Literal["WAITING_PROVIDER_FINAL", "READY", "REJECTED"]
    final_asr_projection: FinalASRReadyProjectionV1 | None


@dataclass(frozen=True, slots=True)
class _ProviderASRFinal:
    content_index: int
    text_metadata: EphemeralTextRefV1


class QwenRealtimeSessionAdapter:
    """Generation-fenced state machine behind one sender and one receive Pump."""

    def __init__(
        self,
        *,
        configuration: QwenSessionConfiguration,
        projection_sink: QwenProjectionSink,
        quarantine: CandidateQuarantine,
        text_store: EphemeralTextStore,
        adapter_id: str = "qwen_realtime_adapter",
    ) -> None:
        if not isinstance(configuration, QwenSessionConfiguration):
            raise TypeError("invalid_session_configuration")
        if not isinstance(quarantine, CandidateQuarantine):
            raise TypeError("invalid_candidate_quarantine")
        if not isinstance(text_store, EphemeralTextStore):
            raise TypeError("invalid_ephemeral_text_store")
        self._configuration = configuration
        self._sink = projection_sink
        self._quarantine = quarantine
        self._quarantine_owners = [quarantine]
        self._text_store = text_store
        self._adapter_id = adapter_id

        self._generation = 0
        self._playback_epoch = 0
        self._interaction_state_version = 0
        self._provider_context_state = "CLOSED"
        self._transport: QwenRealtimeTransport | None = None
        self._pump: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._projection_lock = asyncio.Lock()
        self._active_projection_task: asyncio.Task[None] | None = None
        self._active_projection_generation: int | None = None
        self._fence_cancelled_projection_task: asyncio.Task[None] | None = None
        self._wire_send_seq = 0
        self._provider_event_seq = 0

        self._seen_event_ids: set[str] = set()
        self._session_id: str | None = None
        self._update_sent = False
        self._dropped_audio_frame_count = 0
        self._pending_delete_item_id: str | None = None
        self._pending_cancel_response_id: str | None = None
        self._last_response_terminal_id: str | None = None
        self._late_cancel_error_allowed = False

        self._current_input_item_ref: str | None = None
        self._current_input_generation: int | None = None
        self._current_input_speech_stopped = False
        self._current_input_asr_content_index: int | None = None
        self._historical_input_item_refs: set[str] = set()
        self._rejected_input_items: set[str] = set()
        self._bindings: dict[str, CommittedCandidateBinding] = {}
        self._provider_asr_finals: dict[str, _ProviderASRFinal] = {}
        self._asr_terminal_status: dict[str, Literal["COMPLETED", "FAILED"]] = {}
        self._asr_projections: dict[str, FinalASRReadyProjectionV1] = {}
        self._asr_sink_emitted: set[str] = set()
        self._asr_sink_scheduled: set[str] = set()
        self._deferred_asr_items: list[str] = []
        self._ambient_items: dict[str, int] = {}
        self._ambient_terminal_items: set[str] = set()

        self._seen_response_ids: set[str] = set()
        self._active_response_id: str | None = None
        self._active_candidate_id: str | None = None
        self._active_candidate_ref: str | None = None
        self._active_candidate_input_ref: str | None = None
        self._assistant_item_id: str | None = None
        self._known_output_item_id: str | None = None
        self._provider_response_terminal_observed = False
        self._active_response_terminal_status: (
            Literal["completed", "cancelled", "failed"] | None
        ) = None
        self._candidate_terminal_emitted = False
        self._transcript_completion_emitted = False
        self._full_completion_emitted = False
        self._deferred_transcript_completion = False
        self._deferred_full_completion = False
        self._deferred_flush_task: asyncio.Task[None] | None = None

    @property
    def provider_context_state(self) -> str:
        return self._provider_context_state

    @property
    def playback_epoch(self) -> int:
        return self._playback_epoch

    @property
    def wire_send_seq(self) -> int:
        return self._wire_send_seq

    @property
    def provider_event_seq(self) -> int:
        return self._provider_event_seq

    def fence_for_generation(
        self,
        *,
        generation: int,
        playback_epoch: int,
    ) -> None:
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
        ):
            raise ValueError("invalid_generation")
        if generation <= self._generation:
            raise ValueError("generation_did_not_advance")
        if (
            isinstance(playback_epoch, bool)
            or not isinstance(playback_epoch, int)
            or playback_epoch < 0
        ):
            raise ValueError("invalid_playback_epoch")
        self._generation = generation
        self._cancel_stale_projection_sink()
        if self._quarantine_has_response():
            if self._quarantine.disposition.status == "OPEN":
                self._discard_candidate(reason="discarded")
            successor = self._quarantine.spawn_successor()
            self._quarantine = successor
            self._quarantine_owners.append(successor)
        self._discard_all_asr()
        self._playback_epoch = playback_epoch
        # The controller's single private advance primitive increments both
        # counters together. The public fence intentionally remains the
        # two-argument ADR interface; binding the paired version here prevents
        # safe projections from publishing a stale zero after rebuild.
        self._interaction_state_version = playback_epoch
        self._provider_context_state = "REBUILDING"
        # Runtime calls stop_pump immediately after fencing; old handles remain
        # attached until that ordered step.
        self._seen_event_ids.clear()
        self._session_id = None
        self._update_sent = False
        self._pending_delete_item_id = None
        self._pending_cancel_response_id = None
        self._last_response_terminal_id = None
        self._late_cancel_error_allowed = False
        self._current_input_item_ref = None
        self._current_input_generation = None
        self._current_input_speech_stopped = False
        self._current_input_asr_content_index = None
        self._rejected_input_items.clear()
        self._bindings.clear()
        self._ambient_items.clear()
        self._seen_response_ids.clear()
        self._reset_active_response_correlation()

    async def attach_open_transport(
        self,
        transport: QwenRealtimeTransport,
    ) -> None:
        if self._provider_context_state != "REBUILDING":
            raise RuntimeError("adapter_not_fenced")
        if self._pump is not None and not self._pump.done():
            raise RuntimeError("second_pump")
        self._transport = transport
        self._pump = asyncio.create_task(
            self._run_pump(transport, self._generation)
        )

    async def stop_pump(self) -> None:
        pump = self._pump
        self._pump = None
        if pump is not None and not pump.done():
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:
                pass
        self._transport = None
        async with self._projection_lock:
            pass

    async def append_audio(
        self,
        pcm16le: bytes | bytearray | memoryview,
    ) -> bool:
        generation = self._generation
        try:
            payload = bytearray(memoryview(pcm16le).cast("B"))
        except (TypeError, ValueError):
            return False
        if not payload:
            return False
        event = InputAudioBufferAppendClientEvent(payload)
        try:
            async with self._send_lock:
                transport = self._transport
                if (
                    generation != self._generation
                    or self._provider_context_state != "CLEAN"
                    or transport is None
                ):
                    self._increment_dropped_audio()
                    return False
                self._wire_send_seq += 1
                await transport.send(event)
        finally:
            payload[:] = bytearray(len(payload))
        return True

    async def cancel_active_response(self) -> bool:
        generation = self._generation
        async with self._send_lock:
            response_id = self._active_response_id
            transport = self._transport
            if (
                generation != self._generation
                or self._provider_context_state != "CLEAN"
                or response_id is None
                or self._provider_response_terminal_observed
                or self._candidate_terminal_emitted
                or self._pending_cancel_response_id is not None
                or transport is None
            ):
                return False
            self._pending_cancel_response_id = response_id
            try:
                self._wire_send_seq += 1
                await transport.send(ResponseCancelClientEvent())
            except BaseException:
                if (
                    generation == self._generation
                    and self._pending_cancel_response_id == response_id
                ):
                    self._pending_cancel_response_id = None
                raise
            return True

    async def delete_assistant_item(self, item_id: str) -> bool:
        if not isinstance(item_id, str) or not item_id.strip():
            return False
        generation = self._generation
        async with self._send_lock:
            transport = self._transport
            if (
                generation != self._generation
                or self._provider_context_state != "CLEAN"
                or self._pending_delete_item_id is not None
                or transport is None
            ):
                return False
            self._pending_delete_item_id = item_id
            previous = self._provider_context_state
            self._provider_context_state = "CLEANUP_PENDING"
            try:
                projected = await self._emit_context(
                    previous,
                    "CLEANUP_PENDING",
                    "assistant_item_delete_sent",
                )
                if (
                    not projected
                    or generation != self._generation
                    or transport is not self._transport
                    or self._provider_context_state != "CLEANUP_PENDING"
                    or self._pending_delete_item_id != item_id
                ):
                    return False
                self._wire_send_seq += 1
                await transport.send(
                    ConversationItemDeleteClientEvent(item_id)
                )
            except BaseException:
                if (
                    generation == self._generation
                    and self._pending_delete_item_id == item_id
                ):
                    self._pending_delete_item_id = None
                    self._provider_context_state = previous
                raise
            return True

    def bind_committed_turn(
        self,
        *,
        input_item_ref: str,
        binding: CommittedCandidateBinding,
    ) -> ASRJoinDispositionV1:
        if (
            not isinstance(input_item_ref, str)
            or not input_item_ref.strip()
            or not isinstance(binding, CommittedCandidateBinding)
            or self._provider_context_state != "CLEAN"
            or self._current_input_item_ref != input_item_ref
            or self._current_input_generation != self._generation
            or input_item_ref in self._rejected_input_items
        ):
            return ASRJoinDispositionV1("REJECTED", None)
        if input_item_ref in self._bindings:
            raise RuntimeError("turn_already_bound")
        self._bindings[input_item_ref] = binding
        if self._active_candidate_input_ref == input_item_ref:
            try:
                self._quarantine.bind_committed_turn(binding)
            except CandidateQuarantineError as error:
                self._bindings.pop(input_item_ref, None)
                raise RuntimeError("candidate_binding_failed") from error
            self._defer_new_transcript_completion()
            if self._quarantine.completion() is not None:
                self._deferred_full_completion = True
                self._schedule_deferred_flush()
        projection = self._freeze_asr_projection(input_item_ref)
        if projection is not None:
            self._defer_projection_if_needed(input_item_ref, projection)
            return ASRJoinDispositionV1("READY", projection)
        return ASRJoinDispositionV1("WAITING_PROVIDER_FINAL", None)

    def asr_join_disposition(
        self,
        input_item_ref: str,
    ) -> ASRJoinDispositionV1:
        if input_item_ref in self._rejected_input_items:
            return ASRJoinDispositionV1("REJECTED", None)
        projection = self._asr_projections.get(input_item_ref)
        if projection is not None:
            return ASRJoinDispositionV1("READY", projection)
        return ASRJoinDispositionV1("WAITING_PROVIDER_FINAL", None)

    async def reject_or_hold_ingress(
        self,
        *,
        input_item_ref: str,
        disposition: Literal["rejected", "held"],
    ) -> bool:
        if (
            disposition not in {"rejected", "held"}
            or self._provider_context_state != "CLEAN"
            or input_item_ref != self._current_input_item_ref
            or self._current_input_generation != self._generation
        ):
            return False
        return await self._reject_turn(
            input_item_ref,
            disposition=disposition,
        )

    async def flush_deferred_projections(self) -> None:
        task = self._deferred_flush_task
        if task is not None and task is not asyncio.current_task():
            await asyncio.shield(task)
            return
        async with self._projection_lock:
            while self._deferred_asr_items:
                input_item_ref = self._deferred_asr_items.pop(0)
                self._asr_sink_scheduled.discard(input_item_ref)
                if (
                    input_item_ref in self._rejected_input_items
                    or input_item_ref in self._asr_sink_emitted
                ):
                    continue
                projection = self._asr_projections.get(input_item_ref)
                if projection is None:
                    continue
                await self._emit_asr_projection_under_projection_lock(
                    input_item_ref,
                    projection,
                )
            await self._emit_ready_candidate_under_projection_lock()

    async def expire_pending_cancel(self) -> bool:
        if self._pending_cancel_response_id is None:
            return False
        await self._taint(
            "missing_response_terminal",
            ("provider_cancel_timeout",),
        )
        return True

    async def expire_pending_delete(self) -> bool:
        if self._pending_delete_item_id is None:
            return False
        await self._taint("delete_ack_timeout", ("provider_delete_timeout",))
        return True

    async def dispose_resources(self) -> None:
        await self.stop_pump()
        flush = self._deferred_flush_task
        self._deferred_flush_task = None
        if flush is not None and not flush.done():
            flush.cancel()
            try:
                await flush
            except asyncio.CancelledError:
                pass
        for owner in self._quarantine_owners:
            try:
                owner.disposition
            except CandidateQuarantineError:
                continue
            owner.discard(reason="runner_finally")
        self._discard_all_asr()
        self._text_store.close()

    async def _send(self, event: QwenClientEvent) -> None:
        generation = self._generation
        transport = self._transport
        if transport is None:
            raise RuntimeError("transport_not_open")
        async with self._send_lock:
            if (
                generation != self._generation
                or transport is not self._transport
            ):
                raise RuntimeError("transport_generation_changed")
            self._wire_send_seq += 1
            await transport.send(event)

    async def _run_pump(
        self,
        transport: QwenRealtimeTransport,
        generation: int,
    ) -> None:
        try:
            while self._transport is transport and generation == self._generation:
                event = await transport.recv()
                if generation != self._generation:
                    self._wipe_server_pcm(event)
                    continue
                self._provider_event_seq += 1
                await self._handle(event, generation=generation)
        except asyncio.CancelledError:
            raise
        except QwenTransportClosedError:
            if (
                generation == self._generation
                and transport is self._transport
                and self._provider_context_state != "CLOSED"
            ):
                await self._taint(
                    "transport_closed",
                    ("provider_transport_closed",),
                )
            return
        except Exception:
            if (
                generation == self._generation
                and transport is self._transport
            ):
                await self._taint(
                    "pump_failure",
                    ("provider_pump_failure",),
                )

    async def _handle(
        self,
        event: QwenServerEvent,
        *,
        generation: int | None = None,
    ) -> None:
        bound_generation = self._generation if generation is None else generation
        if bound_generation != self._generation:
            self._wipe_server_pcm(event)
            return
        event_id = getattr(event, "event_id", None)
        if (
            not isinstance(event_id, str)
            or not event_id.strip()
            or event_id in self._seen_event_ids
        ):
            self._wipe_server_pcm(event)
            await self._taint(
                "duplicate_or_missing_event_id",
                ("provider_event_unknown",),
            )
            return
        self._seen_event_ids.add(event_id)

        try:
            if isinstance(event, SessionCreatedServerEvent):
                await self._handle_session_created(event)
                return
            if isinstance(event, SessionUpdatedServerEvent):
                await self._handle_session_updated(event)
                return
            if isinstance(event, ErrorServerEvent):
                await self._handle_error(event)
                return
            if self._provider_context_state not in {
                "CLEAN",
                "CLEANUP_PENDING",
            }:
                self._wipe_server_pcm(event)
                await self._taint("event_before_ready", (event_id,))
                return
            if isinstance(event, ConversationItemDeletedServerEvent):
                await self._handle_delete_ack(event)
                return
            if isinstance(event, ResponseDoneServerEvent):
                await self._handle_response_done(event)
                return
            if self._provider_context_state == "CLEANUP_PENDING":
                self._wipe_server_pcm(event)
                return
            await self._handle_clean_event(event)
        except CandidateQuarantineError:
            self._wipe_server_pcm(event)
            await self._taint("candidate_protocol_failure", (event_id,))

    async def _handle_session_created(
        self,
        event: SessionCreatedServerEvent,
    ) -> None:
        if (
            self._session_id is not None
            or self._provider_context_state != "REBUILDING"
        ):
            await self._taint(
                "unexpected_session_created",
                (event.event_id,),
            )
            return
        self._session_id = event.session_id
        await self._send(SessionUpdateClientEvent(self._configuration))
        self._update_sent = True

    async def _handle_session_updated(
        self,
        event: SessionUpdatedServerEvent,
    ) -> None:
        if (
            not self._update_sent
            or self._session_id != event.session_id
            or event.configuration != self._configuration
            or self._provider_context_state != "REBUILDING"
        ):
            await self._taint("session_update_mismatch", (event.event_id,))
            return
        self._provider_context_state = "CLEAN"
        await self._emit_context("REBUILDING", "CLEAN", "session_ready")

    async def _handle_clean_event(self, event: QwenServerEvent) -> None:
        if isinstance(event, SpeechStartedServerEvent):
            if event.item_id in self._historical_input_item_refs:
                await self._taint(
                    "provider_input_item_reused",
                    (event.event_id,),
                )
                return
            self._historical_input_item_refs.add(event.item_id)
            self._current_input_item_ref = event.item_id
            self._current_input_generation = self._generation
            self._current_input_speech_stopped = False
            self._current_input_asr_content_index = None
            await self._accept_projection(
                SpeechBoundaryProjectionV1(
                    self._generation,
                    "STARTED",
                    event.item_id,
                    event.audio_start_ms,
                )
            )
            return
        if isinstance(event, SpeechStoppedServerEvent):
            generation = self._generation
            if (
                event.item_id != self._current_input_item_ref
                or self._current_input_generation != self._generation
                or self._current_input_speech_stopped
            ):
                await self._taint(
                    "speech_stop_identity_mismatch",
                    (event.event_id,),
                )
                return
            self._current_input_speech_stopped = True
            delivered = await self._accept_projection(
                SpeechBoundaryProjectionV1(
                    generation,
                    "STOPPED",
                    event.item_id,
                    event.audio_end_ms,
                    event.stop_reason,
                )
            )
            if (
                not delivered
                or generation != self._generation
                or event.item_id != self._current_input_item_ref
                or self._current_input_generation != generation
            ):
                return
            if event.stop_reason == "turn_invalid":
                await self._reject_turn(
                    event.item_id,
                    disposition="rejected",
                )
            return
        if isinstance(event, InputAudioCommittedServerEvent):
            if (
                event.item_id != self._current_input_item_ref
                or self._current_input_generation != self._generation
            ):
                await self._taint(
                    "committed_input_identity_mismatch",
                    (event.event_id,),
                )
                return
            self._current_input_item_ref = event.item_id
            return
        if isinstance(event, InputTranscriptionDeltaServerEvent):
            if (
                event.item_id != self._current_input_item_ref
                or self._current_input_generation != self._generation
                or event.item_id in self._rejected_input_items
                or event.item_id in self._asr_terminal_status
                or (
                    self._current_input_asr_content_index is not None
                    and self._current_input_asr_content_index
                    != event.content_index
                )
            ):
                await self._taint(
                    "asr_delta_identity_mismatch",
                    (event.event_id,),
                )
                return
            self._current_input_asr_content_index = event.content_index
            return
        if isinstance(event, InputTranscriptionCompletedServerEvent):
            await self._accept_provider_asr_final(event)
            return
        if isinstance(event, InputTranscriptionFailedServerEvent):
            await self._accept_provider_asr_failure(event)
            return
        if isinstance(event, AmbientTranscriptionDeltaServerEvent):
            self._accept_ambient_delta(event)
            return
        if isinstance(event, AmbientTranscriptionCompletedServerEvent):
            await self._accept_ambient_completed(event)
            return
        if isinstance(event, ResponseCreatedServerEvent):
            await self._open_response(event)
            return
        if isinstance(event, ConversationItemCreatedServerEvent):
            await self._accept_conversation_item(event)
            return
        if isinstance(event, ResponseOutputItemAddedServerEvent):
            self._quarantine.accept_output_item(
                event_id=event.event_id,
                response_id=event.response_id,
                item_id=event.item_id,
                output_index=event.output_index,
                item_type=event.item_type,
                generation=self._generation,
            )
            self._known_output_item_id = event.item_id
            return
        if isinstance(event, ResponseContentPartAddedServerEvent):
            self._quarantine.accept_content_part(
                event_id=event.event_id,
                response_id=event.response_id,
                item_id=event.item_id,
                output_index=event.output_index,
                content_index=event.content_index,
                content_type=event.content_type,
                generation=self._generation,
            )
            return
        if isinstance(event, ResponseAudioTranscriptDeltaServerEvent):
            self._quarantine.append_transcript_delta(
                event_id=event.event_id,
                response_id=event.response_id,
                item_id=event.item_id,
                output_index=event.output_index,
                content_index=event.content_index,
                normalized_delta=event.delta,
                generation=self._generation,
            )
            return
        if isinstance(event, ResponseAudioDeltaServerEvent):
            try:
                if (
                    self._pending_cancel_response_id is not None
                ):
                    return
                if self._provider_response_terminal_observed:
                    if self._active_response_terminal_status == "cancelled":
                        return
                    await self._taint(
                        "late_pcm_after_non_cancel_terminal",
                        (event.event_id,),
                    )
                    return
                if self._candidate_terminal_emitted:
                    return
                self._quarantine.append_pcm_delta(
                    event_id=event.event_id,
                    response_id=event.response_id,
                    item_id=event.item_id,
                    output_index=event.output_index,
                    content_index=event.content_index,
                    pcm_chunk=event.pcm,
                    audio_format_ref="audio-format://pcm16le-24000-mono",
                    sample_rate_hz=24_000,
                    channels=1,
                    generation=self._generation,
                )
            finally:
                self._wipe_server_pcm(event)
            return
        if isinstance(event, ResponseAudioTranscriptDoneServerEvent):
            self._quarantine.mark_transcript_done(
                event_id=event.event_id,
                response_id=event.response_id,
                item_id=event.item_id,
                output_index=event.output_index,
                content_index=event.content_index,
                generation=self._generation,
            )
            await self._emit_new_transcript_completion()
            return
        if isinstance(event, ResponseAudioDoneServerEvent):
            self._quarantine.mark_audio_done(
                event_id=event.event_id,
                response_id=event.response_id,
                item_id=event.item_id,
                output_index=event.output_index,
                content_index=event.content_index,
                generation=self._generation,
            )
            return
        if isinstance(event, ResponseContentPartDoneServerEvent):
            self._quarantine.mark_content_done(
                event_id=event.event_id,
                response_id=event.response_id,
                item_id=event.item_id,
                output_index=event.output_index,
                content_index=event.content_index,
                content_type=event.content_type,
                generation=self._generation,
            )
            return
        if isinstance(event, ResponseOutputItemDoneServerEvent):
            self._quarantine.mark_output_item_done(
                event_id=event.event_id,
                response_id=event.response_id,
                item_id=event.item_id,
                output_index=event.output_index,
                item_type=event.item_type,
                generation=self._generation,
            )
            return
        await self._taint(
            "unsupported_provider_event",
            (getattr(event, "event_id", "provider_event_unknown"),),
        )

    async def _accept_provider_asr_final(
        self,
        event: InputTranscriptionCompletedServerEvent,
    ) -> None:
        if (
            event.item_id in self._asr_terminal_status
            or event.item_id in self._rejected_input_items
            or event.item_id != self._current_input_item_ref
            or self._current_input_generation != self._generation
            or (
                self._current_input_asr_content_index is not None
                and self._current_input_asr_content_index
                != event.content_index
            )
        ):
            await self._taint(
                "duplicate_or_rejected_asr_final",
                (event.event_id,),
            )
            return
        self._asr_terminal_status[event.item_id] = "COMPLETED"
        self._current_input_asr_content_index = event.content_index
        ref = self._make_asr_ref(event.item_id)
        try:
            metadata = self._text_store.put(
                kind="asr",
                ref=ref,
                normalized_text=event.transcript,
                max_unicode_scalars=2000,
            )
        except EphemeralTextStoreError:
            await self._taint("asr_text_store_failure", (event.event_id,))
            return
        if metadata.unicode_scalar_count < 1:
            self._text_store.discard(metadata.ref)
            await self._taint("empty_asr_final", (event.event_id,))
            return
        self._provider_asr_finals[event.item_id] = _ProviderASRFinal(
            content_index=event.content_index,
            text_metadata=metadata,
        )
        projection = self._freeze_asr_projection(event.item_id)
        if projection is not None:
            await self._emit_asr_projection(event.item_id, projection)

    async def _accept_provider_asr_failure(
        self,
        event: InputTranscriptionFailedServerEvent,
    ) -> None:
        if (
            event.item_id in self._asr_terminal_status
            or event.item_id != self._current_input_item_ref
            or self._current_input_generation != self._generation
            or (
                self._current_input_asr_content_index is not None
                and self._current_input_asr_content_index
                != event.content_index
            )
        ):
            await self._taint(
                "duplicate_asr_terminal",
                (event.event_id,),
            )
            return
        self._asr_terminal_status[event.item_id] = "FAILED"
        self._current_input_asr_content_index = event.content_index
        self._rejected_input_items.add(event.item_id)
        self._reject_asr(event.item_id)

    def _freeze_asr_projection(
        self,
        input_item_ref: str,
    ) -> FinalASRReadyProjectionV1 | None:
        existing = self._asr_projections.get(input_item_ref)
        if existing is not None:
            return existing
        provider_final = self._provider_asr_finals.get(input_item_ref)
        binding = self._bindings.get(input_item_ref)
        if provider_final is None or binding is None:
            return None
        metadata = provider_final.text_metadata
        projection = FinalASRReadyProjectionV1(
            provider_session_generation=self._generation,
            qwen_input_item_ref=input_item_ref,
            qwen_input_content_index=provider_final.content_index,
            turn_id=binding.turn_id,
            utterance_id=binding.utterance_id,
            transcript_ref=metadata.ref,
            transcript_digest=metadata.digest,
            transcript_unicode_scalar_count=metadata.unicode_scalar_count,
        )
        self._asr_projections[input_item_ref] = projection
        return projection

    def _defer_projection_if_needed(
        self,
        input_item_ref: str,
        projection: FinalASRReadyProjectionV1,
    ) -> None:
        if (
            input_item_ref in self._asr_sink_emitted
            or input_item_ref in self._asr_sink_scheduled
            or self._asr_projections.get(input_item_ref) is not projection
        ):
            return
        self._asr_sink_scheduled.add(input_item_ref)
        self._deferred_asr_items.append(input_item_ref)
        self._schedule_deferred_flush()

    def _accept_ambient_delta(
        self,
        event: AmbientTranscriptionDeltaServerEvent,
    ) -> None:
        if (
            event.item_id in self._ambient_terminal_items
            or
            event.item_id == self._current_input_item_ref
            or event.item_id in self._bindings
        ):
            raise CandidateQuarantineError("ambient_item_collision")
        previous = self._ambient_items.get(event.item_id)
        if previous is not None and previous != event.content_index:
            raise CandidateQuarantineError("ambient_content_mismatch")
        self._ambient_items[event.item_id] = event.content_index

    async def _accept_ambient_completed(
        self,
        event: AmbientTranscriptionCompletedServerEvent,
    ) -> None:
        if (
            event.item_id in self._ambient_terminal_items
            or
            event.item_id == self._current_input_item_ref
            or event.item_id in self._bindings
        ):
            raise CandidateQuarantineError("ambient_item_collision")
        previous = self._ambient_items.pop(event.item_id, event.content_index)
        if previous != event.content_index:
            raise CandidateQuarantineError("ambient_content_mismatch")
        self._ambient_terminal_items.add(event.item_id)
        await self._accept_projection(
            AmbientTerminalProjectionV1(
                self._generation,
                event.item_id,
                "completed",
            )
        )

    async def _open_response(
        self,
        event: ResponseCreatedServerEvent,
    ) -> None:
        if event.response_id in self._seen_response_ids:
            raise CandidateQuarantineError("response_id_reused")
        self._seen_response_ids.add(event.response_id)
        input_item_ref = self._current_input_item_ref
        if (
            input_item_ref is None
            or self._current_input_generation != self._generation
            or input_item_ref in self._rejected_input_items
        ):
            raise CandidateQuarantineError("response_without_input")
        if self._active_response_id is not None:
            if not self._candidate_terminal_emitted:
                raise CandidateQuarantineError("second_response")
            successor = self._quarantine.spawn_successor()
            self._quarantine = successor
            self._quarantine_owners.append(successor)
            self._reset_active_response_correlation()
        candidate_id = self._make_candidate_id(event.response_id)
        candidate_ref = f"candidate-ref://synthetic/{candidate_id}"
        self._quarantine.open_response(
            event_id=event.event_id,
            generation=self._generation,
            response_id=event.response_id,
            candidate_id=candidate_id,
            playback_epoch=self._playback_epoch,
            provisional_ingress_id=f"ingress_{candidate_id}",
            input_item_ref=input_item_ref,
        )
        self._active_response_id = event.response_id
        self._active_candidate_id = candidate_id
        self._active_candidate_ref = candidate_ref
        self._active_candidate_input_ref = input_item_ref
        self._assistant_item_id = None
        self._known_output_item_id = None
        self._candidate_terminal_emitted = False
        self._provider_response_terminal_observed = False
        self._transcript_completion_emitted = False
        self._full_completion_emitted = False
        binding = self._bindings.get(input_item_ref)
        if binding is not None:
            self._quarantine.bind_committed_turn(binding)
        await self._accept_projection(
            CandidateObservationProjectionV1(
                self._generation,
                candidate_id,
                event.response_id,
                "OPENED",
                candidate_ref,
            )
        )

    async def _accept_conversation_item(
        self,
        event: ConversationItemCreatedServerEvent,
    ) -> None:
        if event.role != "assistant":
            return
        response_id = self._require_active_response()
        self._quarantine.accept_assistant_item(
            event_id=event.event_id,
            response_id=response_id,
            item_id=event.item_id,
            item_type=event.item_type,
            role=event.role,
            generation=self._generation,
        )
        self._assistant_item_id = event.item_id
        self._known_output_item_id = event.item_id

    async def _handle_response_done(
        self,
        event: ResponseDoneServerEvent,
    ) -> None:
        generation = self._generation
        explicit_cancel_pending = (
            self._pending_cancel_response_id == event.response_id
        )
        if event.response_id == self._last_response_terminal_id:
            await self._taint(
                "duplicate_response_terminal",
                (event.event_id,),
            )
            return
        if event.response_id != self._active_response_id:
            await self._taint("response_identity_mismatch", (event.event_id,))
            return
        if self._provider_response_terminal_observed:
            await self._taint(
                "duplicate_response_terminal",
                (event.event_id,),
            )
            return
        if self._candidate_terminal_emitted:
            if (
                self._pending_cancel_response_id != event.response_id
                or event.terminal_status != "cancelled"
                or event.response_terminal_reason
                not in {"turn_detected", "client_cancelled"}
            ):
                await self._taint(
                    "completed_after_cancel",
                    (event.event_id,),
                )
                return
            self._pending_cancel_response_id = None
            self._last_response_terminal_id = event.response_id
            self._provider_response_terminal_observed = True
            self._active_response_terminal_status = "cancelled"
            self._late_cancel_error_allowed = explicit_cancel_pending
            return
        if event.terminal_status == "completed":
            if self._pending_cancel_response_id is not None:
                await self._taint(
                    "completed_after_cancel",
                    (event.event_id,),
                )
                return
            self._quarantine.mark_response_done(
                event_id=event.event_id,
                response_id=event.response_id,
                status=event.terminal_status,
                output_item_ids=tuple(
                    item.item_id for item in event.output_items
                ),
                generation=self._generation,
            )
            await self._emit_new_completion()
        elif event.terminal_status == "cancelled":
            if event.response_terminal_reason not in {
                "turn_detected",
                "client_cancelled",
            }:
                await self._taint(
                    "cancel_terminal_reason_mismatch",
                    (event.event_id,),
                )
                return
            if (
                event.response_terminal_reason == "client_cancelled"
                and self._pending_cancel_response_id != event.response_id
            ):
                await self._taint(
                    "cancel_terminal_reason_mismatch",
                    (event.event_id,),
                )
                return
            self._discard_candidate(reason="cancelled")
            await self._emit_candidate_terminal("CANCELLED")
        else:
            self._discard_candidate(reason="discarded")
            await self._emit_candidate_terminal("DISCARDED")
        if (
            generation != self._generation
            or self._active_response_id != event.response_id
        ):
            return
        if (
            event.terminal_status != "completed"
            or self._quarantine.completion() is not None
        ):
            self._candidate_terminal_emitted = True
        self._provider_response_terminal_observed = True
        self._pending_cancel_response_id = None
        self._last_response_terminal_id = event.response_id
        self._active_response_terminal_status = event.terminal_status
        self._late_cancel_error_allowed = (
            event.terminal_status == "cancelled"
            and explicit_cancel_pending
        )

    async def _emit_new_transcript_completion(self) -> None:
        async with self._projection_lock:
            await self._emit_ready_candidate_under_projection_lock(
                include_full=False
            )

    def _defer_new_transcript_completion(self) -> None:
        if self._transcript_completion_emitted:
            return
        completion = self._quarantine.transcript_completion()
        if completion is None:
            return
        self._deferred_transcript_completion = True
        self._schedule_deferred_flush()

    async def _emit_new_completion(self) -> None:
        async with self._projection_lock:
            await self._emit_ready_candidate_under_projection_lock()

    async def _emit_candidate_terminal(
        self,
        observation: Literal["DISCARDED", "CANCELLED"],
    ) -> bool:
        if self._candidate_terminal_emitted:
            return False
        if (
            self._active_response_id is None
            or self._active_candidate_id is None
        ):
            return False
        return await self._accept_projection(
            CandidateObservationProjectionV1(
                self._generation,
                self._active_candidate_id,
                self._active_response_id,
                observation,
            )
        )

    async def _reject_turn(
        self,
        input_item_ref: str,
        *,
        disposition: Literal["rejected", "held"],
    ) -> bool:
        generation = self._generation
        quarantine = self._quarantine
        response_id = self._active_response_id
        candidate_id = self._active_candidate_id
        output_item_id = self._known_output_item_id
        self._rejected_input_items.add(input_item_ref)
        self._bindings.pop(input_item_ref, None)
        self._reject_asr(input_item_ref)
        if (
            self._active_candidate_input_ref != input_item_ref
            or self._candidate_terminal_emitted
        ):
            return True
        if self._pending_cancel_response_id is None:
            await self.cancel_active_response()
        if (
            generation != self._generation
            or quarantine is not self._quarantine
            or response_id != self._active_response_id
            or candidate_id != self._active_candidate_id
        ):
            return True
        quarantine.discard(reason=disposition)
        if not await self._emit_candidate_terminal("CANCELLED"):
            return False
        if (
            generation != self._generation
            or quarantine is not self._quarantine
            or response_id != self._active_response_id
            or candidate_id != self._active_candidate_id
        ):
            return False
        self._candidate_terminal_emitted = True
        if output_item_id is not None:
            return await self.delete_assistant_item(output_item_id)
        return True

    async def _handle_delete_ack(
        self,
        event: ConversationItemDeletedServerEvent,
    ) -> None:
        if (
            self._provider_context_state != "CLEANUP_PENDING"
            or event.item_id != self._pending_delete_item_id
        ):
            await self._taint("delete_ack_mismatch", (event.event_id,))
            return
        self._pending_delete_item_id = None
        previous = self._provider_context_state
        self._provider_context_state = "CLEAN"
        await self._emit_context(previous, "CLEAN", "delete_ack")

    async def _handle_error(self, event: ErrorServerEvent) -> None:
        if (
            event.error_type == "invalid_request_error"
            and self._late_cancel_error_allowed
            and event.error_code in _BENIGN_LATE_CANCEL_ERROR_CODES
        ):
            self._late_cancel_error_allowed = False
            return
        await self._taint("provider_error", (event.event_id,))

    async def _taint(
        self,
        reason: str,
        source_ids: tuple[str, ...],
    ) -> None:
        if self._provider_context_state == "TAINTED":
            return
        generation = self._generation
        previous = self._provider_context_state
        self._provider_context_state = "TAINTED"
        self._discard_candidate(reason="discarded")
        if not await self._emit_context(previous, "TAINTED", reason):
            return
        if generation != self._generation:
            return
        safe_source_refs = tuple(
            self._opaque_provider_event_ref(source_id)
            for source_id in (
                source_ids or ("provider_event_unknown",)
            )
        )
        await self._accept_projection(
            RebuildRequestedProjectionV1(
                self._generation,
                reason,
                safe_source_refs,
            )
        )

    async def _emit_context(
        self,
        from_state: str,
        to_state: str,
        reason: str,
    ) -> bool:
        return await self._accept_projection(
            ProviderContextProjectionV1(
                self._generation,
                self._playback_epoch,
                self._interaction_state_version,
                from_state,
                to_state,
                reason,
                self._dropped_audio_frame_count,
            )
        )

    async def _accept_projection(
        self,
        frame: QwenProjectionFrameV1,
    ) -> bool:
        async with self._projection_lock:
            return await self._accept_projection_under_projection_lock(frame)

    async def _accept_projection_under_projection_lock(
        self,
        frame: QwenProjectionFrameV1,
    ) -> bool:
        generation = (
            frame.eligibility_facts.provider_session_generation
            if isinstance(frame, CandidateCompletionV1)
            else frame.provider_session_generation
        )
        if generation != self._generation:
            return False
        task = asyncio.create_task(self._sink.accept(frame))
        self._active_projection_task = task
        self._active_projection_generation = generation
        try:
            await task
        except asyncio.CancelledError:
            if (
                generation != self._generation
                and self._fence_cancelled_projection_task is task
            ):
                return False
            raise
        finally:
            if self._active_projection_task is task:
                self._active_projection_task = None
                self._active_projection_generation = None
            if self._fence_cancelled_projection_task is task:
                self._fence_cancelled_projection_task = None
        return generation == self._generation

    async def _emit_asr_projection(
        self,
        input_item_ref: str,
        projection: FinalASRReadyProjectionV1,
    ) -> bool:
        async with self._projection_lock:
            return await self._emit_asr_projection_under_projection_lock(
                input_item_ref,
                projection,
            )

    async def _emit_asr_projection_under_projection_lock(
        self,
        input_item_ref: str,
        projection: FinalASRReadyProjectionV1,
    ) -> bool:
        if (
            projection.provider_session_generation != self._generation
            or input_item_ref in self._rejected_input_items
            or input_item_ref in self._asr_sink_emitted
            or self._asr_projections.get(input_item_ref) is not projection
        ):
            return False
        if not await self._accept_projection_under_projection_lock(projection):
            return False
        self._asr_sink_emitted.add(input_item_ref)
        return True

    async def _emit_ready_candidate_under_projection_lock(
        self,
        *,
        include_full: bool = True,
    ) -> None:
        self._deferred_transcript_completion = False
        if not self._transcript_completion_emitted:
            transcript = self._quarantine.transcript_completion()
            if transcript is not None:
                current_transcript = (
                    self._quarantine.require_current_transcript_completion(
                        transcript
                    )
                )
                if not await self._accept_projection_under_projection_lock(
                    current_transcript
                ):
                    return
                self._transcript_completion_emitted = True
        if not include_full:
            return
        self._deferred_full_completion = False
        if self._full_completion_emitted:
            return
        completion = self._quarantine.completion()
        if completion is None:
            return
        current_completion = self._quarantine.require_current_completion(
            completion
        )
        if not await self._accept_projection_under_projection_lock(
            current_completion
        ):
            return
        self._full_completion_emitted = True
        self._candidate_terminal_emitted = True

    def _schedule_deferred_flush(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if (
            self._deferred_flush_task is None
            or self._deferred_flush_task.done()
        ):
            self._deferred_flush_task = asyncio.create_task(
                self.flush_deferred_projections()
            )

    def _discard_candidate(self, *, reason: str) -> None:
        try:
            self._quarantine.disposition
        except CandidateQuarantineError:
            return
        self._quarantine.discard(reason=reason)

    def _quarantine_has_response(self) -> bool:
        try:
            self._quarantine.disposition
        except CandidateQuarantineError:
            return False
        return True

    def _cancel_stale_projection_sink(self) -> None:
        task = self._active_projection_task
        if (
            task is not None
            and not task.done()
            and self._active_projection_generation != self._generation
        ):
            self._fence_cancelled_projection_task = task
            task.cancel()

    def _reset_active_response_correlation(self) -> None:
        self._active_response_id = None
        self._active_candidate_id = None
        self._active_candidate_ref = None
        self._active_candidate_input_ref = None
        self._assistant_item_id = None
        self._known_output_item_id = None
        self._candidate_terminal_emitted = False
        self._provider_response_terminal_observed = False
        self._active_response_terminal_status = None
        self._late_cancel_error_allowed = False
        self._transcript_completion_emitted = False
        self._full_completion_emitted = False
        self._deferred_transcript_completion = False
        self._deferred_full_completion = False

    def _increment_dropped_audio(self) -> None:
        self._dropped_audio_frame_count = min(
            self._dropped_audio_frame_count + 1,
            2_147_483_647,
        )

    def _discard_all_asr(self) -> None:
        for final in self._provider_asr_finals.values():
            self._text_store.discard(final.text_metadata.ref)
        self._provider_asr_finals.clear()
        self._asr_projections.clear()
        self._asr_sink_emitted.clear()
        self._asr_sink_scheduled.clear()
        self._deferred_asr_items.clear()
        self._asr_terminal_status.clear()

    def _reject_asr(self, input_item_ref: str) -> None:
        provider_final = self._provider_asr_finals.pop(input_item_ref, None)
        if provider_final is not None:
            self._text_store.discard(provider_final.text_metadata.ref)
        self._asr_projections.pop(input_item_ref, None)
        self._asr_sink_emitted.discard(input_item_ref)
        self._asr_sink_scheduled.discard(input_item_ref)

    def _require_active_response(self) -> str:
        if self._active_response_id is None:
            raise CandidateQuarantineError("candidate_not_open")
        return self._active_response_id

    def _make_candidate_id(self, response_id: str) -> str:
        digest = hashlib.sha256(response_id.encode("utf-8")).hexdigest()[:16]
        return f"candidate_g{self._generation}_{digest}"

    def _make_asr_ref(self, input_item_ref: str) -> str:
        digest = hashlib.sha256(
            f"{self._generation}:{input_item_ref}".encode("utf-8")
        ).hexdigest()
        return f"text-ref://synthetic/g{self._generation}/{digest}"

    def _opaque_provider_event_ref(self, event_id: str) -> str:
        digest = hashlib.sha256(
            f"{self._generation}:{event_id}".encode(
                "utf-8",
                errors="replace",
            )
        ).hexdigest()
        return f"provider-event-ref://local/g{self._generation}/{digest}"

    @staticmethod
    def _wipe_server_pcm(event: object) -> None:
        if isinstance(event, ResponseAudioDeltaServerEvent):
            event.pcm[:] = bytearray(len(event.pcm))


__all__ = ["ASRJoinDispositionV1", "QwenRealtimeSessionAdapter"]
