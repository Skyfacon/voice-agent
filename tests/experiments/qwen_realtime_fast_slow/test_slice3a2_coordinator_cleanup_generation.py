from __future__ import annotations

import asyncio
from typing import Any, Mapping

import pytest

from experiments.qwen_realtime_fast_slow_web.capability_profile import (
    fake_capability_profile,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FakeShadowControlProvider,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    VoiceProviderEvent,
    VoiceSuppressionCounters,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    RealtimeSessionCoordinator,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _MemoryBrowserSink:
    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []

    async def send_json(self, data: Mapping[str, Any]) -> None:
        self.json_messages.append(dict(data))

    async def send_bytes(self, data: bytes) -> None:
        self.binary_messages.append(bytes(data))

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _GenerationBoundCleanupProvider:
    def __init__(
        self,
        *,
        cleanup_raises: bool = False,
        taint_on_cleanup_failure: bool = False,
    ) -> None:
        self.profile = fake_capability_profile()
        self.counters = VoiceSuppressionCounters()
        self.enforced_output_suppression = True
        self.ingress_generation = 1
        self.session_generation = 1
        self.context_tainted = False
        self.cleanup_raises = cleanup_raises
        self.taint_on_cleanup_failure = taint_on_cleanup_failure
        self.cleanup_started = asyncio.Event()
        self.release_cleanup = asyncio.Event()
        self.cleanup_calls = 0
        self.rebuild_calls = 0
        self.block_rebuild = False
        self.rebuild_started = asyncio.Event()
        self.release_rebuild = asyncio.Event()
        self.sent_audio_frames: list[bytes] = []

    async def connect(self) -> None:
        return None

    async def recv_event(self, *, receiver_generation: int) -> VoiceProviderEvent:
        if receiver_generation != self.session_generation:
            raise RuntimeError("voice_receiver_generation_stale")
        await asyncio.Future()
        raise AssertionError("unreachable")

    async def send_audio(self, pcm16le: bytes, *, ingress_generation: int) -> None:
        if ingress_generation != self.ingress_generation:
            raise RuntimeError("voice_ingress_generation_stale")
        self.sent_audio_frames.append(bytes(pcm16le))

    async def cancel_response(self) -> bool:
        return False

    async def cleanup_suppressed_response(self, _response_id: str) -> bool:
        self.cleanup_calls += 1
        self.cleanup_started.set()
        await self.release_cleanup.wait()
        if self.taint_on_cleanup_failure:
            self.context_tainted = True
        if self.cleanup_raises:
            raise RuntimeError("PRIVATE_STALE_CLEANUP_FAILURE")
        return False

    async def rebuild_if_tainted(self) -> bool:
        self.rebuild_calls += 1
        if not self.context_tainted:
            return False
        self.rebuild_started.set()
        if self.block_rebuild:
            await self.release_rebuild.wait()
        self.ingress_generation += 1
        self.session_generation += 1
        self.context_tainted = False
        return True

    async def close(self) -> None:
        return None


def _voice_event(
    event_type: str,
    *,
    response_id: str,
    generation: int,
    terminal: bool = False,
) -> VoiceProviderEvent:
    return VoiceProviderEvent(
        type=event_type,
        output_mode="real",
        response_id=response_id,
        provider_item_id=f"voice-output-generation-{generation:04d}",
        session_ref=f"voice-session-generation-{generation:04d}",
        session_generation=generation,
        status="cancelled" if terminal else None,
        terminal=terminal,
        suppressed=True,
        quarantined=True,
    )


@pytest.mark.parametrize("cleanup_raises", (False, True))
def test_stale_cleanup_failure_after_rebuild_is_noop_for_replacement_generation(
    cleanup_raises: bool,
) -> None:
    async def scenario() -> None:
        browser = _MemoryBrowserSink()
        provider = _GenerationBoundCleanupProvider(
            cleanup_raises=cleanup_raises,
        )
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a2_stale_cleanup",
            conversation_id="conversation_qfs_slice3a2_stale_cleanup",
        )
        response_id = "voice-response-generation-aba"
        await coordinator.start()
        try:
            await coordinator.handle_provider_event(
                _voice_event(
                    "response.created",
                    response_id=response_id,
                    generation=1,
                )
            )
            await coordinator.handle_provider_event(
                _voice_event(
                    "response.done",
                    response_id=response_id,
                    generation=1,
                    terminal=True,
                )
            )
            await asyncio.wait_for(provider.cleanup_started.wait(), timeout=1)
            old_cleanup_tasks = [
                task
                for task in coordinator._background_tasks
                if "voice-cleanup" in task.get_name()
            ]
            assert len(old_cleanup_tasks) == 1

            provider.context_tainted = True
            first_rebuild = coordinator._schedule_voice_rebuild()
            assert first_rebuild is not None
            assert (
                await asyncio.wait_for(
                    asyncio.shield(first_rebuild),
                    timeout=1,
                )
                is True
            )
            assert provider.session_generation == 2
            assert provider.rebuild_calls == 1

            await coordinator.handle_provider_event(
                _voice_event(
                    "response.created",
                    response_id=response_id,
                    generation=2,
                )
            )
            replacement_lifecycle = coordinator._voice_response_lifecycles[
                response_id
            ]
            fresh_pcm = b"\x01\x00" * 160
            assert await coordinator.submit_audio(fresh_pcm) is True
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            assert provider.sent_audio_frames == [fresh_pcm]

            provider.release_cleanup.set()
            await asyncio.wait_for(
                asyncio.gather(*old_cleanup_tasks, return_exceptions=True),
                timeout=1,
            )

            assert provider.rebuild_calls == 1
            assert coordinator._voice_rebuild_generation == 1
            assert coordinator.state.voice_context_rebuild_count == 1
            assert coordinator.state.voice_context_tainted is False
            assert coordinator.state.voice_session_status == "connected"
            assert (
                coordinator._voice_response_lifecycles.get(response_id)
                is replacement_lifecycle
            )
            assert replacement_lifecycle.terminal_status is None
            assert browser.binary_messages == []

            next_pcm = b"\x02\x00" * 160
            assert await coordinator.submit_audio(next_pcm) is True
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            assert provider.sent_audio_frames == [fresh_pcm, next_pcm]
        finally:
            provider.release_cleanup.set()
            await coordinator.close()

    _run(scenario())


def test_current_generation_cleanup_failure_triggers_one_coalesced_rebuild() -> None:
    async def scenario() -> None:
        browser = _MemoryBrowserSink()
        provider = _GenerationBoundCleanupProvider(
            taint_on_cleanup_failure=True,
        )
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a2_current_cleanup",
            conversation_id="conversation_qfs_slice3a2_current_cleanup",
        )
        response_id = "voice-response-current-cleanup"
        await coordinator.start()
        try:
            await coordinator.handle_provider_event(
                _voice_event(
                    "response.created",
                    response_id=response_id,
                    generation=1,
                )
            )
            await coordinator.handle_provider_event(
                _voice_event(
                    "response.done",
                    response_id=response_id,
                    generation=1,
                    terminal=True,
                )
            )
            await asyncio.wait_for(provider.cleanup_started.wait(), timeout=1)
            cleanup_tasks = [
                task
                for task in coordinator._background_tasks
                if "voice-cleanup" in task.get_name()
            ]
            assert len(cleanup_tasks) == 1

            provider.release_cleanup.set()
            await asyncio.wait_for(
                asyncio.gather(*cleanup_tasks, return_exceptions=True),
                timeout=1,
            )

            assert provider.rebuild_calls == 1
            assert provider.session_generation == 2
            assert coordinator._voice_rebuild_generation == 1
            assert coordinator.state.voice_context_rebuild_count == 1
            assert coordinator.state.voice_context_tainted is False
            assert coordinator.state.voice_session_status == "connected"
            assert browser.binary_messages == []
        finally:
            provider.release_cleanup.set()
            await coordinator.close()

    _run(scenario())


def test_concurrent_current_generation_cleanup_failures_coalesce_one_rebuild() -> None:
    async def scenario() -> None:
        browser = _MemoryBrowserSink()
        provider = _GenerationBoundCleanupProvider(
            taint_on_cleanup_failure=True,
        )
        provider.block_rebuild = True
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a2_concurrent_cleanup",
            conversation_id="conversation_qfs_slice3a2_concurrent_cleanup",
        )
        await coordinator.start()
        try:
            for index in range(2):
                response_id = f"voice-response-concurrent-{index}"
                await coordinator.handle_provider_event(
                    _voice_event(
                        "response.created",
                        response_id=response_id,
                        generation=1,
                    )
                )
                await coordinator.handle_provider_event(
                    _voice_event(
                        "response.done",
                        response_id=response_id,
                        generation=1,
                        terminal=True,
                    )
                )
            for _ in range(100):
                if provider.cleanup_calls == 2:
                    break
                await asyncio.sleep(0)
            assert provider.cleanup_calls == 2

            provider.release_cleanup.set()
            await asyncio.wait_for(provider.rebuild_started.wait(), timeout=1)
            await asyncio.sleep(0)

            assert provider.rebuild_calls == 1
            assert coordinator._voice_rebuild_generation == 1

            provider.release_rebuild.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=1)

            assert provider.rebuild_calls == 1
            assert provider.session_generation == 2
            assert coordinator.state.voice_context_rebuild_count == 1
            assert coordinator.state.voice_context_tainted is False
            assert coordinator.state.voice_session_status == "connected"
            assert coordinator._voice_response_lifecycles == {}
            assert browser.binary_messages == []
        finally:
            provider.release_cleanup.set()
            provider.release_rebuild.set()
            await coordinator.close()

    _run(scenario())


def test_close_during_blocked_cleanup_is_safe_and_content_free() -> None:
    async def scenario() -> None:
        browser = _MemoryBrowserSink()
        provider = _GenerationBoundCleanupProvider()
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a2_close_cleanup",
            conversation_id="conversation_qfs_slice3a2_close_cleanup",
        )
        await coordinator.start()
        response_id = "voice-response-close-cleanup"
        await coordinator.handle_provider_event(
            _voice_event(
                "response.created",
                response_id=response_id,
                generation=1,
            )
        )
        await coordinator.handle_provider_event(
            _voice_event(
                "response.done",
                response_id=response_id,
                generation=1,
                terminal=True,
            )
        )
        await asyncio.wait_for(provider.cleanup_started.wait(), timeout=1)

        await asyncio.wait_for(coordinator.close(), timeout=1)

        assert coordinator._closed is True
        assert coordinator._background_tasks == set()
        assert coordinator._voice_response_lifecycles == {}
        assert provider.rebuild_calls == 0
        assert browser.binary_messages == []
        serialized_metadata = repr(browser.json_messages)
        assert "PRIVATE_STALE_CLEANUP_FAILURE" not in serialized_metadata
        assert "Authorization" not in serialized_metadata
        assert "DASHSCOPE_API_KEY" not in serialized_metadata

    _run(scenario())
