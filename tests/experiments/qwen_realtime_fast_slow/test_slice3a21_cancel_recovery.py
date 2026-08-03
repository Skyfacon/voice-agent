from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any, Mapping

import pytest

from experiments.qwen_audio_realtime_web.provider_adapter import (
    NormalizedProviderEvent,
)
from experiments.qwen_realtime_fast_slow_web.provider_context import (
    CredentialHandle,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    QwenVoiceAdapter,
    VoiceProviderError,
    _EnforcedQwenVoiceCore,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FakeShadowControlProvider,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    RealtimeSessionCoordinator,
)


def run(coro):
    return asyncio.run(coro)


class ScriptedSuppressionCore:
    def __init__(
        self,
        events: list[NormalizedProviderEvent] | None = None,
        *,
        delete_confirmed: bool = True,
        send_error: Exception | None = None,
    ) -> None:
        self.events = deque(events or [])
        self.delete_confirmed = delete_confirmed
        self.send_error = send_error
        self.response_active = False
        self.connected = False
        self.connect_count = 0
        self.close_count = 0
        self.cancel_count = 0
        self.send_count = 0
        self.deleted_response_count = 0
        self.audio_frames: list[bytes] = []

    async def connect(self) -> None:
        self.connect_count += 1
        self.connected = True

    async def send_audio(self, pcm16le: bytes) -> None:
        self.send_count += 1
        if self.send_error is not None:
            raise self.send_error
        self.audio_frames.append(bytes(pcm16le))

    async def recv_event(self) -> NormalizedProviderEvent:
        if not self.events:
            await asyncio.Future()
        event = self.events.popleft()
        if event.type == "response.created":
            self.response_active = True
        elif event.type == "response.done":
            self.response_active = False
        return event

    async def cancel_response(self) -> bool:
        if not self.response_active or self.cancel_count:
            return False
        self.cancel_count += 1
        return True

    async def delete_response_items(self, _response_ref: str) -> bool:
        self.deleted_response_count += 1
        return self.delete_confirmed

    async def close(self) -> None:
        self.close_count += 1
        self.connected = False


class BlockingReplacementCore(ScriptedSuppressionCore):
    def __init__(self) -> None:
        super().__init__()
        self.connect_started = asyncio.Event()
        self.release_connect = asyncio.Event()

    async def connect(self) -> None:
        self.connect_started.set()
        await self.release_connect.wait()
        await super().connect()


class ClosingReceiveCore(ScriptedSuppressionCore):
    """Unblock an old receive only when cleanup rebuild closes its core."""

    def __init__(self, events: list[NormalizedProviderEvent]) -> None:
        super().__init__(events)
        self.receive_waiting = asyncio.Event()
        self.receive_released_by_close = asyncio.Event()
        self._closed_event = asyncio.Event()

    async def recv_event(self) -> NormalizedProviderEvent:
        if self.events:
            return await super().recv_event()
        self.receive_waiting.set()
        await self._closed_event.wait()
        self.receive_released_by_close.set()
        return NormalizedProviderEvent(
            type="provider.disconnected",
            output_mode="degraded",
            error_code="synthetic_old_core_closed",
            terminal=True,
        )

    async def delete_response_items(self, response_ref: str) -> bool:
        await self.receive_waiting.wait()
        return await super().delete_response_items(response_ref)

    async def close(self) -> None:
        await super().close()
        self._closed_event.set()


class BlockingReplacementSessionCore(BlockingReplacementCore):
    def __init__(self) -> None:
        super().__init__()
        self.events.append(
            NormalizedProviderEvent(type="session.updated", output_mode="real")
        )
        self.session_event_consumed = asyncio.Event()

    async def recv_event(self) -> NormalizedProviderEvent:
        event = await super().recv_event()
        if event.type == "session.updated":
            self.session_event_consumed.set()
        return event


class MemorySink:
    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []

    async def send_json(self, data: Mapping[str, Any]) -> None:
        self.json_messages.append(dict(data))

    async def send_bytes(self, data: bytes) -> None:
        self.binary_messages.append(bytes(data))

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        return None


async def receive_current(adapter: QwenVoiceAdapter):
    return await adapter.recv_event(
        receiver_generation=adapter.session_generation,
    )


def response_event(
    event_type: str,
    response_ref: str,
    *,
    status: str | None = None,
    text: str | None = None,
    audio: bytes | None = None,
) -> NormalizedProviderEvent:
    return NormalizedProviderEvent(
        type=event_type,
        output_mode="real",
        response_ref=response_ref,
        status=status,
        text=text,
        audio=audio,
    )


def test_cancelled_on_time_is_bounded_and_quarantines_all_output() -> None:
    async def scenario() -> None:
        response_ref = "synthetic-response-on-time"
        private_text = "SYNTHETIC_PRIVATE_PROVIDER_TEXT"
        private_audio = b"\x37\x00" * 80
        events = [response_event("response.created", response_ref)]
        events.extend(
            response_event(
                "assistant.transcript.delta",
                response_ref,
                text=private_text,
            )
            for _ in range(17)
        )
        events.extend(
            response_event(
                "response.audio.delta",
                response_ref,
                audio=private_audio,
            )
            for _ in range(17)
        )
        events.append(
            response_event(
                "response.done",
                response_ref,
                status="cancelled",
            )
        )
        core = ScriptedSuppressionCore(events)
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()

        created = await receive_current(adapter)
        suppressed = [await receive_current(adapter) for _ in range(34)]
        terminal = await receive_current(adapter)

        assert created.suppressed is created.quarantined is True
        assert all(event.text is None and event.audio is None for event in suppressed)
        assert terminal.suppressed is terminal.quarantined is True
        assert terminal.output_mode == "real"
        assert adapter.cancel_terminal_outcome == "cancelled_on_time"
        with pytest.raises(AttributeError):
            adapter.cancel_terminal_outcome = "completed_after_cancel"  # type: ignore[misc]
        assert adapter.counters.suppressed_text_delta_count == 17
        assert adapter.counters.suppressed_audio_frame_count == 17
        assert adapter.counters.cancel_terminal_count == 1
        assert adapter.counters.unsafe_cancel_terminal_count == 0
        assert await adapter.wait_for_cancel_terminal(response_ref) is True
        assert await adapter.cleanup_suppressed_response(response_ref) is True
        assert adapter.counters.context_delete_ack_count == 1

        metadata = json.dumps(
            {
                "cancel_terminal_outcome": adapter.cancel_terminal_outcome,
                "counters": adapter.counters.to_metadata(),
                "terminal": terminal.to_safe_metadata(),
            },
            sort_keys=True,
        )
        assert private_text not in metadata
        assert private_audio.hex() not in metadata
        assert response_ref not in json.dumps(
            {
                "cancel_terminal_outcome": adapter.cancel_terminal_outcome,
                "counters": adapter.counters.to_metadata(),
            },
            sort_keys=True,
        )
        await adapter.close()

    run(scenario())


def test_watchdog_classifies_missing_then_late_cancelled_and_stays_unsafe() -> None:
    async def scenario() -> None:
        response_ref = "synthetic-response-watchdog"
        core = ScriptedSuppressionCore(
            [
                response_event("response.created", response_ref),
                response_event(
                    "response.done",
                    response_ref,
                    status="cancelled",
                ),
            ]
        )
        replacement = ScriptedSuppressionCore()
        adapter = QwenVoiceAdapter(
            provider_core=core,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        await receive_current(adapter)

        assert await adapter.wait_for_cancel_terminal(
            response_ref,
            timeout_seconds=0.001,
        ) is False
        assert adapter.cancel_terminal_outcome == "missing_terminal"
        assert adapter.counters.cancel_terminal_timeout_count == 1
        assert adapter.context_tainted is True

        terminal = await receive_current(adapter)
        assert terminal.output_mode == "degraded"
        assert adapter.cancel_terminal_outcome == "cancelled_after_watchdog"
        assert adapter.counters.cancel_terminal_count == 0
        assert adapter.counters.unsafe_cancel_terminal_count == 1
        assert await adapter.cleanup_suppressed_response(response_ref) is False
        assert adapter.counters.context_delete_ack_count == 1
        assert await adapter.rebuild_if_tainted() is True
        assert replacement.connect_count == 1
        await adapter.close()

    run(scenario())


@pytest.mark.parametrize(
    ("terminal_status", "outcome", "counter_name"),
    (
        ("completed", "completed_after_cancel", "completed_after_cancel_count"),
        ("failed", "failed_after_cancel", "failed_after_cancel_count"),
    ),
)
def test_completed_or_failed_after_cancel_remains_fail_closed(
    terminal_status: str,
    outcome: str,
    counter_name: str,
) -> None:
    async def scenario() -> None:
        response_ref = f"synthetic-response-{terminal_status}"
        core = ScriptedSuppressionCore(
            [
                response_event("response.created", response_ref),
                response_event(
                    "response.done",
                    response_ref,
                    status=terminal_status,
                ),
            ]
        )
        replacement = ScriptedSuppressionCore()
        adapter = QwenVoiceAdapter(
            provider_core=core,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        await receive_current(adapter)
        terminal = await receive_current(adapter)

        assert terminal.output_mode == "degraded"
        assert adapter.cancel_terminal_outcome == outcome
        assert adapter.context_tainted is True
        assert adapter.counters.unsafe_cancel_terminal_count == 1
        assert getattr(adapter.counters, counter_name) == 1
        assert await adapter.cleanup_suppressed_response(response_ref) is False
        assert adapter.counters.context_delete_ack_count == 1
        assert await adapter.rebuild_if_tainted() is True
        assert replacement.connect_count == 1
        await adapter.close()

    run(scenario())


def test_invalid_terminal_correlation_has_no_safe_outcome_and_taints() -> None:
    async def scenario() -> None:
        core = ScriptedSuppressionCore(
            [
                response_event(
                    "response.done",
                    "synthetic-uncorrelated-response",
                    status="cancelled",
                )
            ]
        )
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()

        terminal = await receive_current(adapter)

        assert terminal.correlation_valid is False
        assert terminal.output_mode == "degraded"
        assert adapter.cancel_terminal_outcome is None
        assert adapter.context_tainted is True
        assert adapter.counters.correlation_failure_count == 1
        assert adapter.counters.cancel_terminal_count == 0
        await adapter.close()

    run(scenario())


@pytest.mark.parametrize("delete_confirmed", (True, False))
def test_delete_ack_complete_or_missing_is_fail_closed_when_unconfirmed(
    delete_confirmed: bool,
) -> None:
    async def scenario() -> None:
        response_ref = "synthetic-response-delete-ack"
        core = ScriptedSuppressionCore(
            [
                response_event("response.created", response_ref),
                response_event(
                    "response.done",
                    response_ref,
                    status="cancelled",
                ),
            ],
            delete_confirmed=delete_confirmed,
        )
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        await receive_current(adapter)
        await receive_current(adapter)

        cleaned = await adapter.cleanup_suppressed_response(response_ref)

        assert cleaned is delete_confirmed
        assert adapter.cancel_terminal_outcome == "cancelled_on_time"
        assert adapter.counters.context_delete_ack_count == int(delete_confirmed)
        assert adapter.counters.context_delete_failure_count == int(
            not delete_confirmed
        )
        assert adapter.context_tainted is (not delete_confirmed)
        await adapter.close()

    run(scenario())


def test_output_inventory_overflow_and_late_item_remain_content_free() -> None:
    core = _EnforcedQwenVoiceCore(
        CredentialHandle(
            "SYNTHETIC_PRIVATE_CREDENTIAL",
            "synthetic-workspace",
        ),
        voice="longanqian",
        instructions=None,
        connect_timeout_seconds=1.0,
        receive_timeout_seconds=1.0,
    )
    raw_response_ref = "synthetic-raw-response"
    created = core._normalize_and_track(
        {
            "type": "response.created",
            "response": {"id": raw_response_ref},
        }
    )
    assert created.response_ref is not None
    for index in range(9):
        core._normalize_and_track(
            {
                "type": "response.output_item.added",
                "response_id": raw_response_ref,
                "item": {"id": f"synthetic-output-{index}"},
            }
        )
    terminal = core._normalize_and_track(
        {
            "type": "response.done",
            "response": {
                "id": raw_response_ref,
                "status": "cancelled",
                "output": [],
            },
        }
    )
    assert terminal.response_ref is None
    assert terminal.error_code == "voice_terminal_correlation_invalid"

    core._normalize_and_track(
        {
            "type": "response.output_item.added",
            "response_id": raw_response_ref,
            "item": {"id": "synthetic-late-output"},
        }
    )
    context = core._responses[created.response_ref]
    assert context.overflowed is True
    assert context.correlation_invalid is True

    safe_metadata = json.dumps(
        {
            "terminal_type": terminal.type,
            "terminal_mode": terminal.output_mode,
            "terminal_error": terminal.error_code,
            "inventory_overflow": context.overflowed,
            "late_item_invalid": context.correlation_invalid,
        },
        sort_keys=True,
    )
    for forbidden in (
        "SYNTHETIC_PRIVATE_CREDENTIAL",
        raw_response_ref,
        "synthetic-late-output",
    ):
        assert forbidden not in safe_metadata


def test_ingress_availability_is_typed_across_recovery() -> None:
    async def scenario() -> None:
        first = ScriptedSuppressionCore()
        replacement = BlockingReplacementCore()
        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        assert adapter.ingress_availability_code == "voice_provider_not_connected"
        await adapter.connect()
        assert adapter.ingress_availability_code == "available"

        adapter._mark_context_tainted("synthetic_test_taint")
        assert adapter.ingress_availability_code == "voice_context_tainted"
        rebuild = asyncio.create_task(adapter.rebuild_if_tainted())
        await asyncio.wait_for(replacement.connect_started.wait(), timeout=1)
        assert adapter.ingress_availability_code == "voice_context_rebuilding"

        replacement.release_connect.set()
        assert await asyncio.wait_for(rebuild, timeout=1) is True
        assert adapter.ingress_availability_code == "available"
        await adapter.close()
        assert adapter.ingress_availability_code == "voice_adapter_closed"

    run(scenario())


def test_actual_send_failure_is_normalized_counted_and_taints_only_once() -> None:
    async def scenario() -> None:
        private_pcm = b"\x71\x00" * 80
        core = ScriptedSuppressionCore(
            send_error=RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_FAILURE"),
        )
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        generation = adapter.ingress_generation

        with pytest.raises(VoiceProviderError) as first_failure:
            await adapter.send_audio(
                private_pcm,
                ingress_generation=generation,
            )
        assert first_failure.value.code == "voice_send_failed"
        assert first_failure.value.retryable is True
        assert "SYNTHETIC_PRIVATE_PROVIDER_FAILURE" not in str(first_failure.value)
        assert adapter.counters.audio_send_failure_count == 1
        assert adapter.context_tainted is True
        assert adapter.ingress_availability_code == "voice_context_tainted"

        with pytest.raises(VoiceProviderError) as later_frame:
            await adapter.send_audio(
                private_pcm,
                ingress_generation=generation,
            )
        assert later_frame.value.code == "voice_context_tainted"
        assert core.send_count == 1
        assert adapter.counters.audio_send_failure_count == 1

        metadata = json.dumps(adapter.counters.to_metadata(), sort_keys=True)
        assert private_pcm.hex() not in metadata
        assert "SYNTHETIC_PRIVATE_PROVIDER_FAILURE" not in metadata
        await adapter.close()

    run(scenario())


def test_concurrent_rebuild_calls_coalesce_and_count_waiters() -> None:
    async def scenario() -> None:
        first = ScriptedSuppressionCore()
        replacement = BlockingReplacementCore()
        factory_calls = 0

        def factory() -> ScriptedSuppressionCore:
            nonlocal factory_calls
            factory_calls += 1
            return replacement

        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=factory,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        adapter._mark_context_tainted("synthetic_test_rebuild")

        rebuilds = [
            asyncio.create_task(adapter.rebuild_if_tainted())
            for _ in range(5)
        ]
        await asyncio.wait_for(replacement.connect_started.wait(), timeout=1)
        replacement.release_connect.set()
        results = await asyncio.wait_for(
            asyncio.gather(*rebuilds),
            timeout=1,
        )

        assert results.count(True) == 1
        assert factory_calls == 1
        assert replacement.connect_count == 1
        assert adapter.counters.context_rebuild_count == 1
        assert adapter.counters.rebuild_coalesced_count == 4
        await adapter.close()

    run(scenario())


def test_cleanup_rebuild_parks_receiver_until_replacement_generation_connects() -> None:
    async def scenario() -> None:
        response_ref = "synthetic-response-receiver-handoff"
        old_core = ClosingReceiveCore(
            [
                response_event("response.created", response_ref),
                response_event(
                    "response.done",
                    response_ref,
                    status="completed",
                ),
            ]
        )
        replacement = BlockingReplacementSessionCore()
        adapter = QwenVoiceAdapter(
            provider_core=old_core,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        sink = MemorySink()
        coordinator = RealtimeSessionCoordinator(
            sink,
            adapter,
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_receiver_handoff",
            conversation_id="conversation_qfs_slice3a21_receiver_handoff",
        )
        await coordinator.start()
        try:
            await asyncio.wait_for(replacement.connect_started.wait(), timeout=1)
            await asyncio.wait_for(
                old_core.receive_released_by_close.wait(),
                timeout=1,
            )
            for _ in range(5):
                await asyncio.sleep(0)

            assert coordinator._provider_task is not None
            assert coordinator._provider_task.done() is False

            replacement.release_connect.set()
            rebuild = coordinator._voice_rebuild_task
            assert rebuild is not None
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True
            await asyncio.wait_for(
                replacement.session_event_consumed.wait(),
                timeout=1,
            )
            assert adapter.session_generation == 2
            assert not [
                message
                for message in sink.json_messages
                if message.get("type") == "safe_error"
                and message.get("code") == "provider_event_processing_failed"
            ]
            assert sink.binary_messages == []
        finally:
            replacement.release_connect.set()
            await coordinator.close()

    run(scenario())


def test_terminal_provider_error_taints_adapter_and_advances_real_generation() -> None:
    async def scenario() -> None:
        first = ScriptedSuppressionCore(
            [
                NormalizedProviderEvent(
                    type="provider.error",
                    output_mode="degraded",
                    error_code="synthetic_terminal_provider_error",
                    terminal=True,
                )
            ]
        )
        replacement = ScriptedSuppressionCore()
        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        sink = MemorySink()
        coordinator = RealtimeSessionCoordinator(
            sink,
            adapter,
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_terminal_error_rebuild",
            conversation_id="conversation_qfs_slice3a21_terminal_error_rebuild",
        )
        await coordinator.start()
        try:
            for _ in range(100):
                rebuild = coordinator._voice_rebuild_task
                if rebuild is not None:
                    break
                await asyncio.sleep(0)
            else:
                raise AssertionError("terminal provider error did not schedule rebuild")

            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True
            assert adapter.session_generation == 2
            assert adapter.context_tainted is False
            assert replacement.connect_count == 1
            assert coordinator.state.voice_session_status == "connected"
            assert coordinator.state.voice_context_tainted is False
            assert coordinator._provider_task is not None
            assert coordinator._provider_task.done() is False
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_invalid_input_correlation_taints_adapter_before_generation_rebuild() -> None:
    async def scenario() -> None:
        first = ScriptedSuppressionCore()
        replacement = ScriptedSuppressionCore()
        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=lambda: replacement,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        old_generation = adapter.session_generation
        try:
            invalid = adapter._project_correlated_input_event(
                NormalizedProviderEvent(
                    type="speech.started",
                    output_mode="real",
                )
            )

            assert invalid.correlation_valid is False
            assert invalid.error_code == "voice_input_item_missing"
            assert adapter.context_tainted is True
            assert await adapter.rebuild_if_tainted() is True
            assert adapter.session_generation == old_generation + 1
            assert adapter.context_tainted is False
            assert replacement.connect_count == 1
        finally:
            await adapter.close()

    run(scenario())
