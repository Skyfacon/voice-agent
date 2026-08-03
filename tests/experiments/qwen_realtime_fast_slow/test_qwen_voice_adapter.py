from __future__ import annotations

import asyncio
import json
from collections import deque
from types import SimpleNamespace

import aiohttp
import pytest

from experiments.qwen_audio_realtime_web.provider_adapter import (
    NormalizedProviderEvent,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    QwenVoiceAdapter,
    VoiceProviderEvent,
    VoiceProviderError,
    _CorrelatedProviderEvent,
    _EnforcedQwenVoiceCore,
)
from experiments.qwen_realtime_fast_slow_web.provider_context import CredentialHandle


def run(coro):
    return asyncio.run(coro)


async def receive_current(adapter: QwenVoiceAdapter) -> VoiceProviderEvent:
    return await adapter.recv_event(
        receiver_generation=adapter.session_generation
    )


async def send_current(adapter: QwenVoiceAdapter, pcm16le: bytes) -> None:
    await adapter.send_audio(
        pcm16le,
        ingress_generation=adapter.ingress_generation,
    )


class ScriptedVoiceCore:
    def __init__(self, events: list[NormalizedProviderEvent] | None = None) -> None:
        self.events = deque(events or [])
        self.response_active = False
        self.connected = False
        self.closed = False
        self.connect_count = 0
        self.cancel_count = 0
        self.recv_count = 0
        self.audio_frames: list[bytes] = []

    async def connect(self) -> None:
        self.connect_count += 1
        self.connected = True

    async def send_audio(self, pcm16le: bytes) -> None:
        self.audio_frames.append(bytes(pcm16le))

    async def recv_event(self) -> NormalizedProviderEvent:
        self.recv_count += 1
        if not self.events:
            await asyncio.Future()
        return self.events.popleft()

    async def cancel_response(self) -> bool:
        if not self.response_active:
            return False
        self.response_active = False
        self.cancel_count += 1
        return True

    async def close(self) -> None:
        self.closed = True
        self.connected = False


class SuppressionVoiceCore(ScriptedVoiceCore):
    def __init__(
        self,
        events: list[NormalizedProviderEvent] | None = None,
        *,
        delete_confirmed: bool = True,
    ) -> None:
        super().__init__(events)
        self.delete_confirmed = delete_confirmed
        self.deleted_response_refs: list[str] = []
        self.cancel_requested = False

    async def recv_event(self) -> NormalizedProviderEvent:
        event = await super().recv_event()
        if event.type == "response.created":
            self.response_active = True
        elif event.type == "response.done":
            self.response_active = False
        return event

    async def cancel_response(self) -> bool:
        if not self.response_active or self.cancel_requested:
            return False
        self.cancel_requested = True
        self.cancel_count += 1
        return True

    async def delete_response_items(self, response_ref: str) -> bool:
        self.deleted_response_refs.append(response_ref)
        return self.delete_confirmed


class BlockingConnectVoiceCore(SuppressionVoiceCore):
    def __init__(self) -> None:
        super().__init__()
        self.connect_started = asyncio.Event()
        self.release_connect = asyncio.Event()

    async def connect(self) -> None:
        self.connect_started.set()
        await self.release_connect.wait()
        await super().connect()


class BlockingSendVoiceCore(SuppressionVoiceCore):
    def __init__(self) -> None:
        super().__init__()
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send_audio(self, pcm16le: bytes) -> None:
        self.send_started.set()
        await self.release_send.wait()
        await super().send_audio(pcm16le)


class BlockingReceiveVoiceCore(SuppressionVoiceCore):
    def __init__(self, event: NormalizedProviderEvent) -> None:
        super().__init__([event])
        self.receive_started = asyncio.Event()
        self.release_receive = asyncio.Event()

    async def recv_event(self) -> NormalizedProviderEvent:
        self.receive_started.set()
        await self.release_receive.wait()
        return await super().recv_event()


class RecordingWireSocket:
    def __init__(self) -> None:
        self.closed = False
        self.sent: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(dict(payload))


class IdleThenClosingWireSocket(RecordingWireSocket):
    def __init__(self) -> None:
        super().__init__()
        self.receive_cancel_count = 0
        self._incoming: asyncio.Queue[SimpleNamespace] = asyncio.Queue()

    async def receive(self) -> SimpleNamespace:
        try:
            return await self._incoming.get()
        except asyncio.CancelledError:
            self.receive_cancel_count += 1
            raise

    def close_transport(self) -> None:
        self._incoming.put_nowait(
            SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=None)
        )

    async def close(self) -> None:
        self.closed = True


def correlated_event(
    event_type: str,
    *,
    provider_item_ref: str | None,
    text: str | None = None,
    audio_start_ms: int | None = None,
    audio_end_ms: int | None = None,
    session_generation: int | None = None,
) -> _CorrelatedProviderEvent:
    return _CorrelatedProviderEvent(
        normalized=NormalizedProviderEvent(
            type=event_type,
            output_mode="real",
            text=text,
        ),
        provider_item_ref=provider_item_ref,
        audio_start_ms=audio_start_ms,
        audio_end_ms=audio_end_ms,
        session_generation=session_generation,
    )


def test_qwen_voice_adapter_delegates_connection_and_audio_without_replay() -> None:
    async def scenario() -> None:
        core = ScriptedVoiceCore()
        adapter = QwenVoiceAdapter(provider_core=core)
        frame = b"\x01\x00" * 1_600

        await adapter.connect()
        await adapter.connect()
        await send_current(adapter, frame)

        assert core.connect_count == 1
        assert core.audio_frames == [frame]
        assert adapter.sent_audio_frames == 1
        assert adapter.sent_audio_bytes == len(frame)
        assert adapter.profile.health_status == "ready"
        assert adapter.profile.output_mode == "real"
        assert adapter.profile.routing_mode == "shadow"
        assert adapter.profile.route_proposal_authority == "none"

        await adapter.close()
        await adapter.close()
        assert core.closed is True
        assert adapter.profile.health_status == "closed"
        # Closing clears session refs and never reconnects/replays accepted PCM.
        with pytest.raises(RuntimeError, match="qwen_voice_adapter_closed"):
            await adapter.connect()
        assert core.audio_frames == [frame]

    run(scenario())


def test_voice_asr_transcript_audio_and_response_events_get_local_refs() -> None:
    async def scenario() -> None:
        transcript = "transient real transcript sentinel"
        pcm = b"\x01\x00\x02\x00"
        core = ScriptedVoiceCore(
            [
                NormalizedProviderEvent(type="speech.started", output_mode="real"),
                NormalizedProviderEvent(
                    type="user.transcript.delta",
                    output_mode="real",
                    text="transient partial",
                ),
                NormalizedProviderEvent(
                    type="user.transcript.final",
                    output_mode="real",
                    text=transcript,
                ),
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_ref="response-safe-ref",
                ),
                NormalizedProviderEvent(
                    type="assistant.transcript.delta",
                    output_mode="real",
                    response_ref="response-safe-ref",
                    text="transient assistant",
                ),
                NormalizedProviderEvent(
                    type="response.audio.delta",
                    output_mode="real",
                    response_ref="response-safe-ref",
                    audio=pcm,
                ),
                NormalizedProviderEvent(
                    type="response.done",
                    output_mode="real",
                    response_ref="response-safe-ref",
                    status="completed",
                ),
            ]
        )
        adapter = QwenVoiceAdapter(provider_core=core)
        await adapter.connect()
        events = [await receive_current(adapter) for _ in range(7)]

        assert [event.type for event in events] == [
            "speech.started",
            "user.transcript.delta",
            "user.transcript.final",
            "response.created",
            "assistant.transcript.delta",
            "response.audio.delta",
            "response.done",
        ]
        assert {event.turn_ref for event in events} == {"voice-turn-0001"}
        assert events[1].provider_item_id == events[2].provider_item_id == (
            "voice-g0001-input-0001"
        )
        response_items = {
            event.provider_item_id for event in events[3:] if event.provider_item_id
        }
        assert response_items == {"voice-g0001-output-0001"}
        assert events[2].text == transcript
        assert events[5].audio == pcm
        await adapter.close()

    run(scenario())


def test_voice_cancel_is_guarded_by_core_active_response() -> None:
    async def scenario() -> None:
        core = ScriptedVoiceCore()
        adapter = QwenVoiceAdapter(provider_core=core)
        await adapter.connect()

        assert await adapter.cancel_response() is False
        core.response_active = True
        assert await adapter.cancel_response() is True
        assert await adapter.cancel_response() is False
        assert adapter.cancel_count == 1
        assert core.cancel_count == 1
        await adapter.close()

    run(scenario())


@pytest.mark.parametrize(
    ("provider_event", "health_status"),
    (
        (
            NormalizedProviderEvent(
                type="provider.error",
                output_mode="degraded",
                error_code="provider_error",
            ),
            "degraded",
        ),
        (
            NormalizedProviderEvent(
                type="provider.disconnected",
                output_mode="degraded",
                error_code="provider_disconnected",
                terminal=True,
            ),
            "disconnected",
        ),
        (
            NormalizedProviderEvent(
                type="provider.timeout",
                output_mode="degraded",
                error_code="provider_receive_timeout",
                terminal=True,
            ),
            "disconnected",
        ),
    ),
)
def test_voice_errors_are_safe_and_health_is_distinguishable(
    provider_event: NormalizedProviderEvent, health_status: str
) -> None:
    async def scenario() -> None:
        adapter = QwenVoiceAdapter(
            provider_core=ScriptedVoiceCore([provider_event])
        )
        await adapter.connect()
        event = await receive_current(adapter)

        assert event.type == provider_event.type
        assert event.output_mode == "degraded"
        assert event.error_code == provider_event.error_code
        assert adapter.profile.health_status == health_status
        assert adapter.profile.output_mode == "degraded"
        await adapter.close()

    run(scenario())


def test_voice_safe_metadata_never_serializes_transcript_pcm_or_payload() -> None:
    event = VoiceProviderEvent(
        type="response.audio.delta",
        output_mode="real",
        response_id="response-safe-ref",
        provider_item_id="voice-output-0001",
        turn_ref="voice-turn-0001",
        text="PRIVATE_TRANSCRIPT_SENTINEL",
        stash="PRIVATE_STASH_SENTINEL",
        audio=b"\x01\x00\x02\x00",
    )

    metadata = event.to_safe_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert metadata["audio_bytes"] == 4
    assert "text" not in metadata
    assert "stash" not in metadata
    assert "audio" not in metadata
    assert "PRIVATE_TRANSCRIPT_SENTINEL" not in serialized
    assert "PRIVATE_STASH_SENTINEL" not in serialized
    assert "01000200" not in serialized
    assert repr(event).find("PRIVATE_TRANSCRIPT_SENTINEL") == -1
    assert repr(event).find("01000200") == -1


def test_enforced_voice_suppresses_text_pcm_cancels_to_terminal_and_deletes() -> None:
    async def scenario() -> None:
        transcript = "PRIVATE_VOICE_ASSISTANT_TEXT_SENTINEL"
        pcm = b"\x01\x00\x02\x00"
        core = SuppressionVoiceCore(
            [
                correlated_event(
                    "speech.started",
                    provider_item_ref="raw-suppression-input",
                    audio_start_ms=0,
                ),
                correlated_event(
                    "speech.stopped",
                    provider_item_ref="raw-suppression-input",
                    audio_end_ms=100,
                ),
                correlated_event(
                    "user.transcript.final",
                    provider_item_ref="raw-suppression-input",
                    text="PRIVATE_USER_TRANSCRIPT_SENTINEL",
                ),
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_ref="response-safe-suppressed",
                ),
                NormalizedProviderEvent(
                    type="assistant.transcript.delta",
                    output_mode="real",
                    response_ref="response-safe-suppressed",
                    text=transcript,
                ),
                NormalizedProviderEvent(
                    type="response.audio.delta",
                    output_mode="real",
                    response_ref="response-safe-suppressed",
                    audio=pcm,
                ),
                NormalizedProviderEvent(
                    type="response.done",
                    output_mode="real",
                    response_ref="response-safe-suppressed",
                    status="cancelled",
                ),
            ]
        )
        adapter = QwenVoiceAdapter(
            provider_core=core, enforced_output_suppression=True
        )
        await adapter.connect()

        speech = await receive_current(adapter)
        speech_stopped = await receive_current(adapter)
        user_final = await receive_current(adapter)
        created = await receive_current(adapter)
        text_delta = await receive_current(adapter)
        audio_delta = await receive_current(adapter)
        done = await receive_current(adapter)

        assert speech.type == "speech.started"
        assert speech_stopped.type == "speech.stopped"
        assert user_final.text == "PRIVATE_USER_TRANSCRIPT_SENTINEL"
        assert created.suppressed is created.quarantined is True
        assert text_delta.text is None
        assert text_delta.suppressed is text_delta.quarantined is True
        assert audio_delta.audio is None
        assert audio_delta.byte_length == 0
        assert audio_delta.suppressed is audio_delta.quarantined is True
        assert done.terminal is True
        assert done.correlation_valid is True
        assert core.cancel_count == 1
        assert adapter.counters.cancel_request_count == 1
        assert adapter.counters.cancel_terminal_count == 1
        assert adapter.counters.suppressed_text_delta_count == 1
        assert adapter.counters.suppressed_audio_frame_count == 1
        assert adapter.counters.suppressed_audio_byte_count == len(pcm)

        assert await adapter.cleanup_suppressed_response(
            "response-safe-suppressed"
        ) is True
        assert core.deleted_response_refs == ["response-safe-suppressed"]
        assert adapter.counters.context_delete_count == 1
        assert adapter.context_tainted is False

        serialized = json.dumps(
            [
                created.to_safe_metadata(),
                text_delta.to_safe_metadata(),
                audio_delta.to_safe_metadata(),
                done.to_safe_metadata(),
                adapter.counters.to_metadata(),
            ],
            sort_keys=True,
        )
        assert transcript not in serialized
        assert pcm.hex() not in serialized
        assert "PRIVATE_USER_TRANSCRIPT_SENTINEL" not in serialized
        await adapter.close()

    run(scenario())


def test_enforced_voice_cleanup_without_terminal_fails_closed_and_rebuilds_only_voice() -> None:
    async def scenario() -> None:
        first = SuppressionVoiceCore(
            [
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_ref="response-no-terminal",
                )
            ]
        )
        replacement = SuppressionVoiceCore()
        created_cores: list[SuppressionVoiceCore] = []

        def factory() -> SuppressionVoiceCore:
            created_cores.append(replacement)
            return replacement

        adapter = QwenVoiceAdapter(
            provider_core=first,
            enforced_output_suppression=True,
            provider_core_factory=factory,
        )
        await adapter.connect()
        frame = b"\x01\x00" * 1_600
        await send_current(adapter, frame)
        created = await receive_current(adapter)
        assert created.suppressed is True
        assert adapter.counters.cancel_request_count == 1

        assert await adapter.cleanup_suppressed_response(
            "response-no-terminal"
        ) is False
        assert adapter.context_tainted is True
        assert adapter.session_state == "degraded"
        assert adapter.counters.correlation_failure_count == 1

        assert await adapter.rebuild_if_tainted() is True
        assert created_cores == [replacement]
        assert first.closed is True
        assert replacement.connected is True
        assert replacement.audio_frames == []
        assert adapter.sent_audio_frames == 1
        assert adapter.counters.context_rebuild_count == 1
        assert adapter.context_tainted is False
        assert adapter.session_state == "connected"
        await adapter.close()

    run(scenario())


def test_enforced_voice_delete_failure_taints_and_rebuild_does_not_replay_pcm() -> None:
    async def scenario() -> None:
        first = SuppressionVoiceCore(
            [
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_ref="response-delete-fail",
                ),
                NormalizedProviderEvent(
                    type="response.done",
                    output_mode="real",
                    response_ref="response-delete-fail",
                    status="cancelled",
                ),
            ],
            delete_confirmed=False,
        )
        replacement = SuppressionVoiceCore()
        adapter = QwenVoiceAdapter(
            provider_core=first,
            enforced_output_suppression=True,
            provider_core_factory=lambda: replacement,
        )
        await adapter.connect()
        pcm = b"\x02\x00" * 1_600
        await send_current(adapter, pcm)
        await receive_current(adapter)
        done = await receive_current(adapter)
        assert done.terminal is True

        assert await adapter.cleanup_suppressed_response(
            "response-delete-fail"
        ) is False
        assert adapter.counters.context_delete_failure_count == 1
        assert adapter.context_tainted is True
        assert await adapter.rebuild_if_tainted() is True
        assert replacement.audio_frames == []
        assert first.audio_frames == [pcm]
        assert adapter.counters.context_rebuild_count == 1
        await adapter.close()

    run(scenario())


def test_enforced_voice_late_or_uncorrelated_output_is_content_free_and_taints() -> None:
    async def scenario() -> None:
        core = SuppressionVoiceCore(
            [
                NormalizedProviderEvent(
                    type="assistant.transcript.delta",
                    output_mode="real",
                    response_ref="late-response",
                    text="LATE_PRIVATE_TEXT_SENTINEL",
                ),
                NormalizedProviderEvent(
                    type="response.audio.delta",
                    output_mode="real",
                    response_ref="late-response",
                    audio=b"\x03\x00\x04\x00",
                ),
            ]
        )
        adapter = QwenVoiceAdapter(
            provider_core=core, enforced_output_suppression=True
        )
        await adapter.connect()

        late_text = await receive_current(adapter)
        late_audio = await receive_current(adapter)

        assert late_text.text is None
        assert late_audio.audio is None
        assert late_text.correlation_valid is False
        assert late_audio.correlation_valid is False
        assert adapter.context_tainted is True
        assert adapter.counters.late_event_discard_count == 2
        assert adapter.counters.correlation_failure_count == 2
        serialized = json.dumps(
            [late_text.to_safe_metadata(), late_audio.to_safe_metadata()]
        )
        assert "LATE_PRIVATE_TEXT_SENTINEL" not in serialized
        assert "03000400" not in serialized
        await adapter.close()

    run(scenario())


def test_slice3a1_asr_final_requires_exact_item_turn_utterance_span_and_generation() -> None:
    async def scenario() -> None:
        core = ScriptedVoiceCore(
            [
                correlated_event(
                    "speech.started",
                    provider_item_ref="RAW-INPUT-ITEM-PRIVATE-A",
                    audio_start_ms=100,
                    session_generation=1,
                ),
                correlated_event(
                    "user.transcript.delta",
                    provider_item_ref="RAW-INPUT-ITEM-PRIVATE-A",
                    text="PRIVATE_PARTIAL_TRANSCRIPT",
                    session_generation=1,
                ),
                correlated_event(
                    "speech.stopped",
                    provider_item_ref="RAW-INPUT-ITEM-PRIVATE-A",
                    audio_end_ms=260,
                    session_generation=1,
                ),
                correlated_event(
                    "user.transcript.final",
                    provider_item_ref="RAW-INPUT-ITEM-PRIVATE-A",
                    text="PRIVATE_FINAL_TRANSCRIPT",
                    session_generation=1,
                ),
            ]
        )
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        events = [await receive_current(adapter) for _ in range(4)]

        assert all(event.correlation_valid for event in events)
        assert {event.provider_item_id for event in events} == {
            "voice-g0001-input-0001"
        }
        assert {event.turn_ref for event in events} == {"voice-turn-0001"}
        assert {event.utterance_ref for event in events} == {
            "voice-utterance-0001"
        }
        assert {event.audio_span_ref for event in events} == {
            "voice-audio-span-0001"
        }
        assert {event.session_ref for event in events} == {"voice-session-0001"}
        assert events[-1].audio_start_ms == 100
        assert events[-1].audio_end_ms == 260
        serialized = json.dumps(
            [event.to_safe_metadata() for event in events], sort_keys=True
        )
        assert "RAW-INPUT-ITEM-PRIVATE-A" not in serialized
        assert "PRIVATE_PARTIAL_TRANSCRIPT" not in serialized
        assert "PRIVATE_FINAL_TRANSCRIPT" not in serialized
        await adapter.close()

    run(scenario())


@pytest.mark.parametrize(
    ("events", "expected_code"),
    (
        (
            [
                correlated_event(
                    "speech.started", provider_item_ref="raw-a", audio_start_ms=0
                ),
                correlated_event(
                    "speech.stopped", provider_item_ref="raw-a", audio_end_ms=100
                ),
                correlated_event(
                    "user.transcript.final", provider_item_ref="raw-a", text="first"
                ),
                correlated_event(
                    "user.transcript.final",
                    provider_item_ref="raw-a",
                    text="PRIVATE_DUPLICATE_FINAL",
                ),
            ],
            "voice_input_item_unknown_old_or_mismatched",
        ),
        (
            [
                correlated_event(
                    "speech.started", provider_item_ref="raw-a", audio_start_ms=0
                ),
                correlated_event(
                    "user.transcript.delta",
                    provider_item_ref="raw-b",
                    text="PRIVATE_MISMATCHED_DELTA",
                ),
            ],
            "voice_input_item_unknown_old_or_mismatched",
        ),
        (
            [
                correlated_event(
                    "speech.started", provider_item_ref="raw-a", audio_start_ms=0
                ),
                correlated_event(
                    "user.transcript.final",
                    provider_item_ref=None,
                    text="PRIVATE_MISSING_ITEM_FINAL",
                ),
            ],
            "voice_input_item_missing",
        ),
        (
            [
                correlated_event(
                    "speech.started", provider_item_ref="raw-a", audio_start_ms=0
                ),
                correlated_event(
                    "speech.started", provider_item_ref="raw-b", audio_start_ms=120
                ),
                correlated_event(
                    "user.transcript.final",
                    provider_item_ref="raw-a",
                    text="PRIVATE_OLD_ITEM_FINAL",
                ),
            ],
            "voice_input_item_unknown_old_or_mismatched",
        ),
    ),
)
def test_slice3a1_duplicate_missing_mismatched_or_old_asr_is_content_free(
    events: list[_CorrelatedProviderEvent],
    expected_code: str,
) -> None:
    async def scenario() -> None:
        adapter = QwenVoiceAdapter(
            provider_core=ScriptedVoiceCore(events),
            enforced_output_suppression=True,
        )
        await adapter.connect()
        projected = [await receive_current(adapter) for _ in events]
        invalid = projected[-1]

        assert invalid.correlation_valid is False
        assert invalid.output_mode == "degraded"
        assert invalid.error_code == expected_code
        assert invalid.text is None
        assert invalid.provider_item_id is None
        serialized = json.dumps(invalid.to_safe_metadata(), sort_keys=True)
        for forbidden in (
            "PRIVATE_DUPLICATE_FINAL",
            "PRIVATE_MISMATCHED_DELTA",
            "PRIVATE_MISSING_ITEM_FINAL",
            "PRIVATE_OLD_ITEM_FINAL",
            "raw-a",
            "raw-b",
        ):
            assert forbidden not in serialized
        assert adapter.counters.correlation_failure_count >= 1
        assert adapter.counters.late_event_discard_count >= 1
        await adapter.close()

    run(scenario())


def test_slice3a1_interrupt_fences_late_asr_final_without_rebinding_new_turn() -> None:
    async def scenario() -> None:
        core = ScriptedVoiceCore(
            [
                correlated_event(
                    "speech.started", provider_item_ref="raw-old", audio_start_ms=10
                ),
                correlated_event(
                    "speech.stopped", provider_item_ref="raw-old", audio_end_ms=90
                ),
                correlated_event(
                    "user.transcript.final",
                    provider_item_ref="raw-old",
                    text="PRIVATE_LATE_AFTER_INTERRUPT",
                ),
                correlated_event(
                    "speech.started", provider_item_ref="raw-new", audio_start_ms=100
                ),
                correlated_event(
                    "speech.stopped", provider_item_ref="raw-new", audio_end_ms=190
                ),
                correlated_event(
                    "user.transcript.final",
                    provider_item_ref="raw-new",
                    text="PRIVATE_CURRENT_FINAL",
                ),
            ]
        )
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        old_start = await receive_current(adapter)
        old_stop = await receive_current(adapter)
        assert old_start.correlation_valid and old_stop.correlation_valid
        assert adapter.invalidate_current_input(reason="interrupt") is True
        late = await receive_current(adapter)
        new_start = await receive_current(adapter)
        new_stop = await receive_current(adapter)
        current = await receive_current(adapter)

        assert late.correlation_valid is False
        assert late.text is None
        assert current.correlation_valid is True
        assert current.provider_item_id == new_start.provider_item_id
        assert current.provider_item_id != old_start.provider_item_id
        assert current.turn_ref == new_stop.turn_ref
        assert current.text == "PRIVATE_CURRENT_FINAL"
        await adapter.close()

    run(scenario())


@pytest.mark.parametrize("terminal_status", ("completed", "failed"))
def test_slice3a1_completed_or_failed_after_cancel_is_unsafe_but_still_cleaned(
    terminal_status: str,
) -> None:
    async def scenario() -> None:
        response_id = f"response-{terminal_status}-after-cancel"
        core = SuppressionVoiceCore(
            [
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_ref=response_id,
                ),
                NormalizedProviderEvent(
                    type="response.done",
                    output_mode="real",
                    response_ref=response_id,
                    status=terminal_status,
                ),
            ]
        )
        replacement = SuppressionVoiceCore()
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
            provider_core_factory=lambda: replacement,
        )
        await adapter.connect()
        created = await receive_current(adapter)
        assert created.suppressed is True
        assert adapter.mark_response_output_ineligible(response_id) is True
        done = await receive_current(adapter)

        assert done.terminal is True
        assert done.output_mode == "degraded"
        assert adapter.counters.cancel_terminal_count == 0
        assert adapter.counters.unsafe_cancel_terminal_count == 1
        assert getattr(
            adapter.counters, f"{terminal_status}_after_cancel_count"
        ) == 1
        assert await adapter.wait_for_cancel_terminal(
            response_id, timeout_seconds=0.05
        ) is False
        assert await adapter.cleanup_suppressed_response(response_id) is False
        assert core.deleted_response_refs == [response_id]
        assert adapter.counters.context_delete_ack_count == 1
        assert adapter.context_tainted is True
        assert await adapter.rebuild_if_tainted() is True
        assert replacement.connected is True
        await adapter.close()

    run(scenario())


def test_slice3a1_cancel_terminal_watchdog_rebuilds_and_bounds_new_pcm_drop() -> None:
    async def scenario() -> None:
        response_id = "response-watchdog-timeout"
        first = SuppressionVoiceCore(
            [
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_ref=response_id,
                )
            ]
        )
        replacement = BlockingConnectVoiceCore()
        adapter = QwenVoiceAdapter(
            provider_core=first,
            enforced_output_suppression=True,
            provider_core_factory=lambda: replacement,
            cancel_terminal_timeout_seconds=0.01,
        )
        await adapter.connect()
        await send_current(adapter, b"\x01\x00" * 100)
        await receive_current(adapter)

        assert await adapter.wait_for_cancel_terminal(
            response_id, timeout_seconds=0.01
        ) is False
        assert adapter.counters.cancel_terminal_count == 0
        assert adapter.counters.cancel_terminal_timeout_count == 1
        assert adapter.context_tainted is True

        rebuild = asyncio.create_task(adapter.rebuild_if_tainted())
        await asyncio.wait_for(replacement.connect_started.wait(), timeout=1)
        with pytest.raises(VoiceProviderError, match="voice_context_rebuilding"):
            await send_current(adapter, b"\x02\x00" * 100)
        assert adapter.counters.rebuild_audio_drop_count == 1
        assert adapter.counters.rebuild_audio_drop_byte_count == 200
        assert replacement.audio_frames == []
        replacement.release_connect.set()
        assert await asyncio.wait_for(rebuild, timeout=1) is True
        assert first.audio_frames == [b"\x01\x00" * 100]
        assert replacement.audio_frames == []
        await adapter.close()

    run(scenario())


def test_slice3a1_successful_delete_keeps_late_output_permanently_ineligible() -> None:
    async def scenario() -> None:
        response_id = "response-delete-then-late"
        core = SuppressionVoiceCore(
            [
                NormalizedProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_ref=response_id,
                ),
                NormalizedProviderEvent(
                    type="response.done",
                    output_mode="real",
                    response_ref=response_id,
                    status="cancelled",
                ),
                NormalizedProviderEvent(
                    type="response.audio.delta",
                    output_mode="real",
                    response_ref=response_id,
                    audio=b"\x09\x00\x08\x00",
                ),
            ]
        )
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        await receive_current(adapter)
        done = await receive_current(adapter)
        assert done.status == "cancelled"
        assert await adapter.wait_for_cancel_terminal(response_id) is True
        assert await adapter.cleanup_suppressed_response(response_id) is True
        late = await receive_current(adapter)

        assert late.audio is None
        assert late.correlation_valid is False
        assert late.suppressed is late.quarantined is True
        assert adapter.counters.late_event_discard_count >= 1
        await adapter.close()

    run(scenario())


def test_slice3a1_core_delete_ack_is_resolved_only_by_single_receiver_path() -> None:
    async def make_core(timeout: float) -> tuple[_EnforcedQwenVoiceCore, RecordingWireSocket, str]:
        core = _EnforcedQwenVoiceCore(
            CredentialHandle("PRIVATE_CORE_KEY_SENTINEL", "ws-test-safe-123"),
            voice="longanqian",
            instructions=None,
            connect_timeout_seconds=1.0,
            receive_timeout_seconds=1.0,
            context_delete_timeout_seconds=timeout,
        )
        socket = RecordingWireSocket()
        core._websocket = socket  # type: ignore[assignment]
        core._connected = True
        created = core._normalize_and_track(
            {
                "type": "response.created",
                "response": {"id": "raw-response-private"},
            }
        )
        response_ref = created.response_ref
        assert response_ref
        core._normalize_and_track(
            {
                "type": "response.output_item.added",
                "response_id": "raw-response-private",
                "item": {"id": "raw-output-item-private"},
            }
        )
        core._normalize_and_track(
            {
                "type": "response.done",
                "response": {
                    "id": "raw-response-private",
                    "status": "cancelled",
                    "output": [{"id": "raw-output-item-private"}],
                },
            }
        )
        return core, socket, response_ref

    async def scenario() -> None:
        core, socket, response_ref = await make_core(0.2)
        delete = asyncio.create_task(core.delete_response_items(response_ref))
        for _ in range(20):
            if socket.sent:
                break
            await asyncio.sleep(0)
        assert socket.sent == [
            {
                "type": "conversation.item.delete",
                "item_id": "raw-output-item-private",
            }
        ]
        assert not delete.done()

        # The same ordered recv/normalization path that handles all provider
        # events resolves the acknowledgement; cleanup never calls receive().
        core._normalize_and_track(
            {
                "type": "conversation.item.deleted",
                "item_id": "raw-output-item-private",
            }
        )
        result = await asyncio.wait_for(delete, timeout=1)
        assert result.confirmed is True
        assert result.deleted_count == 1

        timeout_core, timeout_socket, timeout_ref = await make_core(0.01)
        timed_out = await timeout_core.delete_response_items(timeout_ref)
        assert timed_out.confirmed is False
        assert timeout_socket.sent

        serialized = json.dumps(
            {
                "confirmed": result.confirmed,
                "deleted_count": result.deleted_count,
                "timeout_confirmed": timed_out.confirmed,
            },
            sort_keys=True,
        )
        assert "PRIVATE_CORE_KEY_SENTINEL" not in serialized
        assert "raw-response-private" not in serialized
        assert "raw-output-item-private" not in serialized

    run(scenario())


def test_slice3a12_core_provider_response_and_output_item_ids_never_rebind() -> None:
    core = _EnforcedQwenVoiceCore(
        CredentialHandle("PRIVATE_REUSE_KEY_SENTINEL", "ws-test-safe-reuse"),
        voice="longanqian",
        instructions=None,
        connect_timeout_seconds=1.0,
        receive_timeout_seconds=1.0,
    )

    first = core._normalize_and_track(
        {
            "type": "response.created",
            "response": {"id": "raw-response-reused-private"},
        }
    )
    assert first.response_ref is not None
    core._normalize_and_track(
        {
            "type": "response.output_item.added",
            "response_id": "raw-response-reused-private",
            "item": {"id": "raw-output-reused-private"},
        }
    )
    core._normalize_and_track(
        {
            "type": "response.done",
            "response": {
                "id": "raw-response-reused-private",
                "status": "cancelled",
                "output": [{"id": "raw-output-reused-private"}],
            },
        }
    )
    core._responses.pop(first.response_ref, None)

    reused_response = core._normalize_and_track(
        {
            "type": "response.created",
            "response": {"id": "raw-response-reused-private"},
        }
    )
    assert reused_response.response_ref is None
    assert reused_response.output_mode == "degraded"
    assert reused_response.error_code == "voice_response_id_reused"

    second = core._normalize_and_track(
        {
            "type": "response.created",
            "response": {"id": "raw-response-second-private"},
        }
    )
    assert second.response_ref is not None
    core._normalize_and_track(
        {
            "type": "response.output_item.added",
            "response_id": "raw-response-second-private",
            "item": {"id": "raw-output-reused-private"},
        }
    )
    reused_output_terminal = core._normalize_and_track(
        {
            "type": "response.done",
            "response": {
                "id": "raw-response-second-private",
                "status": "cancelled",
                "output": [{"id": "raw-output-reused-private"}],
            },
        }
    )
    assert reused_output_terminal.response_ref is None
    assert reused_output_terminal.output_mode == "degraded"
    assert reused_output_terminal.error_code == "voice_terminal_correlation_invalid"

    metadata = json.dumps(
        {
            "response_reuse_error": reused_response.error_code,
            "output_reuse_error": reused_output_terminal.error_code,
            "seen_response_count": len(core._seen_raw_response_ids),
            "seen_output_count": len(core._output_item_owners),
        },
        sort_keys=True,
    )
    for forbidden in (
        "PRIVATE_REUSE_KEY_SENTINEL",
        "raw-response-reused-private",
        "raw-response-second-private",
        "raw-output-reused-private",
    ):
        assert forbidden not in metadata


def test_slice3a11_provider_idle_is_not_terminal_and_cancelled_receiver_leaves_no_orphan() -> None:
    async def scenario() -> None:
        core = _EnforcedQwenVoiceCore(
            CredentialHandle("PRIVATE_IDLE_KEY_SENTINEL", "ws-test-safe-idle"),
            voice="longanqian",
            instructions=None,
            connect_timeout_seconds=1.0,
            receive_timeout_seconds=0.01,
        )
        socket = IdleThenClosingWireSocket()
        core._websocket = socket  # type: ignore[assignment]
        core._connected = True

        receiver = asyncio.create_task(core.recv_event())
        await asyncio.sleep(0.03)
        assert receiver.done() is False
        assert core._connected is True

        pcm = b"\x01\x00" * 160
        await core.send_audio(pcm)
        assert socket.sent[-1]["type"] == "input_audio_buffer.append"

        receiver.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receiver
        assert socket.receive_cancel_count == 1
        assert core._connected is True

        # Cancellation of an idle receive is caller lifecycle, not a provider
        # terminal.  A later PCM frame is still valid on the same transport.
        await core.send_audio(pcm)
        assert len(socket.sent) == 2

        socket.close_transport()
        terminal = await core.recv_event()
        assert terminal.type == "provider.disconnected"
        assert terminal.terminal is True
        assert terminal.output_mode == "degraded"
        assert core._connected is False
        await core.close()

    run(scenario())


def test_slice3a12_enforced_pcm_requires_exact_generation_and_rebuild_fences_immediately() -> None:
    async def scenario() -> None:
        first = BlockingSendVoiceCore()
        replacement = BlockingConnectVoiceCore()
        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        generation = adapter.ingress_generation
        private_pcm = b"\x7f\x00" * 160

        with pytest.raises(
            VoiceProviderError, match="voice_ingress_generation_required"
        ):
            await adapter.send_audio(private_pcm)

        sending = asyncio.create_task(
            adapter.send_audio(
                private_pcm,
                ingress_generation=generation,
            )
        )
        await asyncio.wait_for(first.send_started.wait(), timeout=1)
        adapter._mark_context_tainted("test_rebuild_fence")
        rebuilding = asyncio.create_task(adapter.rebuild_if_tainted())
        await asyncio.wait_for(replacement.connect_started.wait(), timeout=1)

        assert adapter.rebuilding is True
        assert adapter.ingress_generation == generation + 1
        with pytest.raises(
            VoiceProviderError, match="voice_ingress_generation_stale"
        ):
            await adapter.send_audio(
                private_pcm,
                ingress_generation=generation,
            )
        with pytest.raises(VoiceProviderError, match="voice_context_rebuilding"):
            await adapter.send_audio(
                private_pcm,
                ingress_generation=adapter.ingress_generation,
            )

        replacement.release_connect.set()
        assert await asyncio.wait_for(rebuilding, timeout=1) is True
        first.release_send.set()
        with pytest.raises(
            VoiceProviderError, match="voice_ingress_generation_retired"
        ):
            await asyncio.wait_for(sending, timeout=1)

        assert replacement.audio_frames == []
        assert adapter.sent_audio_frames == 0
        assert adapter.counters.ingress_generation_drop_count == 4
        assert adapter.counters.rebuild_audio_drop_count == 2
        metadata = json.dumps(adapter.counters.to_metadata(), sort_keys=True)
        assert private_pcm.hex() not in metadata
        await adapter.close()

    run(scenario())


def test_slice3a12_transport_terminal_is_delivered_once_without_core_hot_loop() -> None:
    async def scenario() -> None:
        terminal = NormalizedProviderEvent(
            type="provider.disconnected",
            output_mode="degraded",
            error_code="provider_disconnected",
            terminal=True,
        )
        first = ScriptedVoiceCore([terminal, terminal])
        replacement = ScriptedVoiceCore(
            [NormalizedProviderEvent(type="session.updated", output_mode="real")]
        )
        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        old_generation = adapter.session_generation

        delivered = await adapter.recv_event(
            receiver_generation=old_generation
        )
        assert delivered.type == "provider.disconnected"
        assert delivered.session_generation == old_generation
        assert first.recv_count == 1

        with pytest.raises(
            VoiceProviderError, match="voice_receiver_generation_terminal"
        ):
            await adapter.recv_event(receiver_generation=old_generation)
        assert first.recv_count == 1
        assert adapter.counters.terminal_receiver_exit_count == 1

        assert await adapter.rebuild_if_tainted() is True
        assert adapter.session_generation == old_generation + 1
        with pytest.raises(
            VoiceProviderError, match="voice_receiver_generation_stale"
        ):
            await adapter.recv_event(receiver_generation=old_generation)
        current = await adapter.recv_event(
            receiver_generation=adapter.session_generation
        )
        assert current.type == "session.updated"
        assert replacement.recv_count == 1
        await adapter.close()

    run(scenario())


@pytest.mark.parametrize(
    "stale_event",
    (
        NormalizedProviderEvent(
            type="provider.disconnected",
            output_mode="degraded",
            error_code="PRIVATE_OLD_TERMINAL_SENTINEL",
            terminal=True,
        ),
        NormalizedProviderEvent(
            type="user.transcript.final",
            output_mode="real",
            text="PRIVATE_OLD_ASR_SENTINEL",
        ),
        NormalizedProviderEvent(
            type="response.audio.delta",
            output_mode="real",
            response_ref="old-response",
            audio=b"\x55\x00" * 80,
        ),
    ),
)
def test_slice3a12_inflight_old_generation_events_are_content_free(
    stale_event: NormalizedProviderEvent,
) -> None:
    async def scenario() -> None:
        first = BlockingReceiveVoiceCore(stale_event)
        replacement = ScriptedVoiceCore()
        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        old_generation = adapter.session_generation
        receiving = asyncio.create_task(
            adapter.recv_event(receiver_generation=old_generation)
        )
        await asyncio.wait_for(first.receive_started.wait(), timeout=1)

        adapter._mark_context_tainted("test_old_receiver_fence")
        assert await adapter.rebuild_if_tainted() is True
        assert adapter.session_generation == old_generation + 1
        first.release_receive.set()
        discarded = await asyncio.wait_for(receiving, timeout=1)

        assert discarded.type == "provider.ignored"
        assert discarded.terminal is True
        assert discarded.correlation_valid is False
        assert discarded.text is None
        assert discarded.audio is None
        assert discarded.stash is None
        assert discarded.session_generation == old_generation
        serialized = json.dumps(discarded.to_safe_metadata(), sort_keys=True)
        for forbidden in (
            "PRIVATE_OLD_TERMINAL_SENTINEL",
            "PRIVATE_OLD_ASR_SENTINEL",
            (b"\x55\x00" * 80).hex(),
        ):
            assert forbidden not in serialized
        assert adapter.counters.receiver_generation_discard_count == 1
        assert adapter.counters.late_event_discard_count == 1
        await adapter.close()

    run(scenario())


def test_slice3a13_concurrent_close_preserves_receiver_session_authority_ref() -> None:
    async def scenario() -> None:
        first = BlockingReceiveVoiceCore(
            NormalizedProviderEvent(
                type="provider.disconnected",
                output_mode="degraded",
                error_code="PRIVATE_CLOSE_RACE_SENTINEL",
                terminal=True,
            )
        )
        adapter = QwenVoiceAdapter(
            provider_core=first,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        old_generation = adapter.session_generation
        receiving = asyncio.create_task(
            adapter.recv_event(receiver_generation=old_generation)
        )
        await asyncio.wait_for(first.receive_started.wait(), timeout=1)

        await adapter.close()
        first.release_receive.set()
        discarded = await asyncio.wait_for(receiving, timeout=1)

        assert discarded.type == "provider.ignored"
        assert discarded.session_generation == old_generation
        assert discarded.session_ref == "voice-session-0001"
        assert discarded.correlation_valid is False
        assert discarded.text is None
        assert discarded.audio is None
        assert "PRIVATE_CLOSE_RACE_SENTINEL" not in json.dumps(
            discarded.to_safe_metadata(), sort_keys=True
        )

    run(scenario())


def test_slice3a12_provider_input_id_reuse_and_horizon_fail_closed() -> None:
    async def scenario() -> None:
        events: list[_CorrelatedProviderEvent] = []
        for index in range(64):
            raw_id = f"raw-input-{index:04d}"
            start = index * 20
            events.extend(
                (
                    correlated_event(
                        "speech.started",
                        provider_item_ref=raw_id,
                        audio_start_ms=start,
                    ),
                    correlated_event(
                        "speech.stopped",
                        provider_item_ref=raw_id,
                        audio_end_ms=start + 10,
                    ),
                    correlated_event(
                        "user.transcript.final",
                        provider_item_ref=raw_id,
                        text=f"synthetic-{index:04d}",
                    ),
                )
            )
        events.append(
            correlated_event(
                "speech.started",
                provider_item_ref="raw-input-new-at-horizon",
                audio_start_ms=2_000,
            )
        )
        adapter = QwenVoiceAdapter(
            provider_core=ScriptedVoiceCore(events),
            enforced_output_suppression=True,
        )
        await adapter.connect()

        valid = [await receive_current(adapter) for _ in range(64 * 3)]
        horizon = await receive_current(adapter)
        assert all(event.correlation_valid for event in valid)
        assert horizon.correlation_valid is False
        assert horizon.error_code == "voice_input_context_limit_exceeded"
        assert horizon.provider_item_id is None
        assert adapter.context_tainted is True
        assert len(adapter._input_item_contexts) == 64
        assert len(adapter._input_item_order) == 64
        assert adapter.counters.provider_item_id_horizon_count == 1

        # A duplicate ID is never rebound to a new local turn even after the
        # completed records have reached the bounded horizon.
        duplicate = adapter._project_correlated_input_event(
            correlated_event(
                "speech.started",
                provider_item_ref="raw-input-0000",
                audio_start_ms=2_020,
            )
        )
        assert duplicate.correlation_valid is False
        assert duplicate.error_code == "voice_input_item_duplicate_start"
        assert duplicate.provider_item_id is None
        assert adapter.counters.provider_item_id_reuse_count == 1
        await adapter.close()

    run(scenario())


def test_slice3a12_320_turns_rotate_before_id_eviction_and_remain_bounded() -> None:
    def turn_events(generation_index: int) -> list[_CorrelatedProviderEvent]:
        events: list[_CorrelatedProviderEvent] = []
        for turn_index in range(64):
            raw_id = f"g{generation_index:02d}-item-{turn_index:04d}"
            start = turn_index * 20
            events.extend(
                (
                    correlated_event(
                        "speech.started",
                        provider_item_ref=raw_id,
                        audio_start_ms=start,
                    ),
                    correlated_event(
                        "speech.stopped",
                        provider_item_ref=raw_id,
                        audio_end_ms=start + 10,
                    ),
                    correlated_event(
                        "user.transcript.final",
                        provider_item_ref=raw_id,
                        text="synthetic-final",
                    ),
                )
            )
        events.append(
            correlated_event(
                "speech.started",
                provider_item_ref=f"g{generation_index:02d}-rotate",
                audio_start_ms=2_000,
            )
        )
        return events

    async def scenario() -> None:
        cores = [ScriptedVoiceCore(turn_events(index)) for index in range(5)]
        replacements = deque(cores[1:])
        adapter = QwenVoiceAdapter(
            provider_core=cores[0],
            provider_core_factory=lambda: replacements.popleft(),
            enforced_output_suppression=True,
        )
        await adapter.connect()
        observed_item_refs: set[str] = set()

        for generation_index in range(5):
            generation = adapter.session_generation
            for _ in range(64 * 3):
                event = await adapter.recv_event(
                    receiver_generation=generation
                )
                assert event.correlation_valid is True
                if event.provider_item_id is not None:
                    observed_item_refs.add(event.provider_item_id)
                    assert f"voice-g{generation:04d}-" in event.provider_item_id
            horizon = await adapter.recv_event(
                receiver_generation=generation
            )
            assert horizon.correlation_valid is False
            assert len(adapter._input_item_contexts) == 64
            assert len(adapter._input_item_order) == 64
            assert len(adapter._seen_response_ids) == 0
            if generation_index < 4:
                assert await adapter.rebuild_if_tainted() is True

        assert len(observed_item_refs) == 320
        assert adapter.counters.provider_item_id_horizon_count == 5
        assert adapter.counters.context_rebuild_count == 4
        assert len(adapter._input_item_contexts) == 64
        await adapter.close()

    run(scenario())
