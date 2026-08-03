from __future__ import annotations

import asyncio
from collections import deque

import pytest

from experiments.qwen_audio_realtime_web.provider_adapter import (
    NormalizedProviderEvent,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    QwenVoiceAdapter,
    VoiceProviderError,
)


def _run(coro) -> None:
    asyncio.run(coro)


def _response_events(
    response_id: str,
    *,
    include_late_output: bool = False,
) -> list[NormalizedProviderEvent]:
    events = [
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
            terminal=True,
        ),
    ]
    if include_late_output:
        events.append(
            NormalizedProviderEvent(
                type="assistant.transcript.delta",
                output_mode="real",
                response_ref=response_id,
                text="PRIVATE_STALE_OUTPUT_SENTINEL",
            )
        )
    return events


class _CleanupCore:
    def __init__(
        self,
        events: list[NormalizedProviderEvent],
        *,
        delete_outcome: str = "success",
        block_delete: bool = False,
    ) -> None:
        self.events = deque(events)
        self.delete_outcome = delete_outcome
        self.block_delete = block_delete
        self.delete_started = asyncio.Event()
        self.release_delete = asyncio.Event()
        self.response_active = False
        self.cancel_requested = False
        self.connected = False
        self.closed = False
        self.audio_frames: list[bytes] = []
        self.deleted_response_refs: list[str] = []

    async def connect(self) -> None:
        self.connected = True

    async def send_audio(self, pcm16le: bytes) -> None:
        self.audio_frames.append(bytes(pcm16le))

    async def recv_event(self) -> NormalizedProviderEvent:
        event = self.events.popleft()
        if event.type == "response.created":
            self.response_active = True
        elif event.type == "response.done":
            self.response_active = False
        return event

    async def cancel_response(self) -> bool:
        if not self.response_active or self.cancel_requested:
            return False
        self.cancel_requested = True
        return True

    async def delete_response_items(self, response_ref: str) -> bool:
        self.deleted_response_refs.append(response_ref)
        self.delete_started.set()
        if self.block_delete:
            await self.release_delete.wait()
        if self.delete_outcome == "exception":
            raise RuntimeError("private provider delete failure")
        return self.delete_outcome == "success"

    async def close(self) -> None:
        self.closed = True
        self.connected = False


async def _receive_current(adapter: QwenVoiceAdapter):
    return await adapter.recv_event(
        receiver_generation=adapter.session_generation
    )


async def _send_current(adapter: QwenVoiceAdapter, pcm16le: bytes) -> None:
    await adapter.send_audio(
        pcm16le,
        ingress_generation=adapter.ingress_generation,
    )


@pytest.mark.parametrize("delete_outcome", ("failure", "exception"))
def test_stale_cleanup_failure_after_rebuild_is_content_free_noop(
    delete_outcome: str,
) -> None:
    async def scenario() -> None:
        response_id = f"same-response-{delete_outcome}"
        old_core = _CleanupCore(
            _response_events(response_id, include_late_output=True),
            delete_outcome=delete_outcome,
            block_delete=True,
        )
        replacement_core = _CleanupCore([])
        adapter = QwenVoiceAdapter(
            provider_core=old_core,
            enforced_output_suppression=True,
            provider_core_factory=lambda: replacement_core,
        )
        await adapter.connect()
        await _receive_current(adapter)
        await _receive_current(adapter)

        cleanup = asyncio.create_task(
            adapter.cleanup_suppressed_response(response_id)
        )
        await asyncio.wait_for(old_core.delete_started.wait(), timeout=1)
        late = await _receive_current(adapter)
        assert late.text is None
        assert late.correlation_valid is False
        assert adapter.context_tainted is True

        assert await adapter.rebuild_if_tainted() is True
        assert adapter.session_generation == 2
        assert adapter.context_tainted is False
        fresh_pcm = b"\x01\x00" * 100
        await _send_current(adapter, fresh_pcm)
        failure_count = adapter.counters.context_delete_failure_count
        delete_count = adapter.counters.context_delete_count
        ack_count = adapter.counters.context_delete_ack_count

        old_core.release_delete.set()
        assert await asyncio.wait_for(cleanup, timeout=1) is False
        assert adapter.counters.context_delete_failure_count == failure_count
        assert adapter.counters.context_delete_count == delete_count
        assert adapter.counters.context_delete_ack_count == ack_count
        assert adapter.context_tainted is False
        assert adapter.session_state == "connected"
        assert replacement_core.audio_frames == [fresh_pcm]
        await adapter.close()

    _run(scenario())


def test_stale_cleanup_success_cannot_retire_same_id_replacement_lifecycle() -> None:
    async def scenario() -> None:
        response_id = "same-response-success"
        old_core = _CleanupCore(
            _response_events(response_id, include_late_output=True),
            block_delete=True,
        )
        replacement_core = _CleanupCore(_response_events(response_id))
        adapter = QwenVoiceAdapter(
            provider_core=old_core,
            enforced_output_suppression=True,
            provider_core_factory=lambda: replacement_core,
        )
        await adapter.connect()
        await _receive_current(adapter)
        await _receive_current(adapter)

        old_cleanup = asyncio.create_task(
            adapter.cleanup_suppressed_response(response_id)
        )
        await asyncio.wait_for(old_core.delete_started.wait(), timeout=1)
        await _receive_current(adapter)
        assert adapter.context_tainted is True
        assert await adapter.rebuild_if_tainted() is True

        replacement_created = await _receive_current(adapter)
        replacement_done = await _receive_current(adapter)
        assert replacement_created.correlation_valid is True
        assert replacement_done.correlation_valid is True
        replacement_lifecycle = adapter._suppressed_responses[response_id]
        delete_count = adapter.counters.context_delete_count
        ack_count = adapter.counters.context_delete_ack_count
        fresh_pcm = b"\x02\x00" * 100
        await _send_current(adapter, fresh_pcm)

        old_core.release_delete.set()
        assert await asyncio.wait_for(old_cleanup, timeout=1) is False
        assert adapter._suppressed_responses[response_id] is replacement_lifecycle
        assert replacement_lifecycle.cleanup_confirmed is False
        assert response_id not in adapter._stale_response_ids
        assert adapter.counters.context_delete_count == delete_count
        assert adapter.counters.context_delete_ack_count == ack_count
        assert adapter.context_tainted is False
        assert adapter.session_state == "connected"
        assert replacement_core.audio_frames == [fresh_pcm]

        assert await adapter.cleanup_suppressed_response(response_id) is True
        assert replacement_core.deleted_response_refs == [response_id]
        await adapter.close()

    _run(scenario())


@pytest.mark.parametrize("delete_outcome", ("failure", "exception"))
def test_current_generation_cleanup_failure_remains_fail_closed(
    delete_outcome: str,
) -> None:
    async def scenario() -> None:
        response_id = f"current-response-{delete_outcome}"
        core = _CleanupCore(
            _response_events(response_id),
            delete_outcome=delete_outcome,
        )
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        await _receive_current(adapter)
        await _receive_current(adapter)

        lifecycle = adapter._suppressed_responses[response_id]
        assert await adapter.cleanup_suppressed_response(response_id) is False
        assert adapter.counters.context_delete_failure_count == 1
        assert adapter.counters.context_delete_count == 0
        assert adapter.counters.context_delete_ack_count == 0
        assert adapter.context_tainted is True
        assert adapter.session_state == "degraded"
        assert adapter._suppressed_responses[response_id] is lifecycle
        assert lifecycle.cleanup_confirmed is False
        assert response_id not in adapter._stale_response_ids
        with pytest.raises(VoiceProviderError, match="voice_context_tainted"):
            await _send_current(adapter, b"\x03\x00" * 100)
        await adapter.close()

    _run(scenario())
