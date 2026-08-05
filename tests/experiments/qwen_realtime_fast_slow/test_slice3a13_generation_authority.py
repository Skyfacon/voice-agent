from __future__ import annotations

import asyncio
import json
from collections import deque
from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any, Mapping

import pytest

from experiments.qwen_audio_realtime_web.provider_adapter import (
    NormalizedProviderEvent,
)
from experiments.qwen_realtime_fast_slow_web.candidate_quarantine import (
    CandidateQuarantine,
)
from experiments.qwen_realtime_fast_slow_web.capability_profile import (
    fake_capability_profile,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    QwenVoiceAdapter,
    VoiceProviderError,
    VoiceProviderEvent,
    VoiceSuppressionCounters,
    _CorrelatedProviderEvent,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FakeShadowControlProvider,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    CoordinatorConfig,
    RealtimeSessionCoordinator,
)


def _run(coro):
    return asyncio.run(coro)


class _SyntheticVoiceCore:
    def __init__(
        self,
        events: list[NormalizedProviderEvent | _CorrelatedProviderEvent] | None = None,
        *,
        block_connect: bool = False,
        block_send: bool = False,
    ) -> None:
        self.events = deque(events or [])
        self.response_active = False
        self.audio_frames: list[bytes] = []
        self.connect_count = 0
        self.close_count = 0
        self._block_connect = block_connect
        self._block_send = block_send
        self.connect_started = asyncio.Event()
        self.release_connect = asyncio.Event()
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def connect(self) -> None:
        self.connect_count += 1
        self.connect_started.set()
        if self._block_connect:
            await self.release_connect.wait()

    async def send_audio(self, pcm16le: bytes) -> None:
        self.send_started.set()
        if self._block_send:
            await self.release_send.wait()
        self.audio_frames.append(bytes(pcm16le))

    async def recv_event(
        self,
    ) -> NormalizedProviderEvent | _CorrelatedProviderEvent:
        if not self.events:
            await asyncio.Future()
        event = self.events.popleft()
        if event.type == "response.created":
            self.response_active = True
        elif event.type == "response.done":
            self.response_active = False
        return event

    async def cancel_response(self) -> bool:
        if not self.response_active:
            return False
        self.response_active = False
        return True

    async def delete_response_items(self, _response_ref: str) -> bool:
        return True

    async def close(self) -> None:
        self.close_count += 1


class _BlockingFinalBrowserSink:
    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []
        self.final_send_started = asyncio.Event()
        self.release_final_send = asyncio.Event()

    async def send_json(self, data: Mapping[str, Any]) -> None:
        copied = deepcopy(dict(data))
        if copied.get("type") == "transcript.user.final":
            self.final_send_started.set()
            await self.release_final_send.wait()
        self.json_messages.append(copied)

    async def send_bytes(self, data: bytes) -> None:
        self.binary_messages.append(bytes(data))

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _BlockingMessageBrowserSink(_BlockingFinalBrowserSink):
    def __init__(self) -> None:
        super().__init__()
        self.blocked_type: str | None = None
        self.blocked_send_started = asyncio.Event()
        self.release_blocked_send = asyncio.Event()

    def arm(self, message_type: str) -> None:
        self.blocked_type = message_type
        self.blocked_send_started = asyncio.Event()
        self.release_blocked_send = asyncio.Event()

    async def send_json(self, data: Mapping[str, Any]) -> None:
        copied = deepcopy(dict(data))
        if copied.get("type") == self.blocked_type:
            self.blocked_send_started.set()
            await self.release_blocked_send.wait()
            self.blocked_type = None
        self.json_messages.append(copied)


class _GenerationRebuildProvider:
    def __init__(self) -> None:
        self.profile = fake_capability_profile()
        self.counters = VoiceSuppressionCounters()
        self.enforced_output_suppression = True
        self.ingress_generation = 1
        self.session_generation = 1
        self.rebuild_calls = 0
        self.block_cleanup = False
        self.cleanup_started = asyncio.Event()
        self.release_cleanup = asyncio.Event()

    async def connect(self) -> None:
        return None

    async def recv_event(self, *, receiver_generation: int) -> VoiceProviderEvent:
        if receiver_generation != self.session_generation:
            raise RuntimeError("voice_receiver_generation_stale")
        await asyncio.Future()
        raise AssertionError("unreachable")

    async def send_audio(self, _pcm: bytes, *, ingress_generation: int) -> None:
        if ingress_generation != self.ingress_generation:
            raise RuntimeError("voice_ingress_generation_stale")

    async def rebuild_if_tainted(self) -> bool:
        self.rebuild_calls += 1
        self.ingress_generation += 1
        self.session_generation += 1
        return True

    async def cancel_response(self) -> bool:
        return False

    async def cleanup_suppressed_response(self, _response_id: str) -> bool:
        self.cleanup_started.set()
        if self.block_cleanup:
            await self.release_cleanup.wait()
        return True

    async def wait_response_complete(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _input_event(
    event_type: str,
    *,
    provider_item_ref: str,
    audio_start_ms: int | None = None,
    audio_end_ms: int | None = None,
    text: str | None = None,
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
    )


async def _open_and_stop_voice_turn(
    coordinator: RealtimeSessionCoordinator,
    *,
    generation: int,
    index: int,
) -> None:
    correlation = {
        "provider_item_id": f"voice-input-generation-{generation:04d}-{index:04d}",
        "turn_ref": f"voice-turn-generation-{generation:04d}-{index:04d}",
        "utterance_ref": f"voice-utterance-generation-{generation:04d}-{index:04d}",
        "audio_span_ref": f"voice-audio-generation-{generation:04d}-{index:04d}",
        "session_ref": f"voice-session-generation-{generation:04d}",
        "session_generation": generation,
    }
    await coordinator.handle_provider_event(
        VoiceProviderEvent(
            type="speech.started",
            output_mode="real",
            audio_start_ms=0,
            **correlation,
        )
    )
    await coordinator.handle_provider_event(
        VoiceProviderEvent(
            type="speech.stopped",
            output_mode="real",
            audio_start_ms=0,
            audio_end_ms=100,
            **correlation,
        )
    )


def test_candidate_quarantine_rejects_boolean_release_epoch_without_content_leak() -> None:
    quarantine = CandidateQuarantine()
    candidate_sentinel = "SYNTHETIC_PRIVATE_CANDIDATE_SENTINEL"
    quarantine.start(
        response_id="response-safe",
        provider_item_id="item-safe",
        turn_id="turn-safe",
        utterance_id="utterance-safe",
        playback_epoch=1,
    )
    assert quarantine.append_text("response-safe", candidate_sentinel) is True

    with pytest.raises(ValueError, match="playback_epoch") as caught:
        quarantine.release(
            "response-safe",
            expected_playback_epoch=True,
        )

    assert candidate_sentinel not in str(caught.value)
    assert quarantine.snapshot("response-safe") is not None
    assert candidate_sentinel not in json.dumps(
        quarantine.counters(), sort_keys=True
    )


def test_input_id_horizon_allows_64_then_fences_65_and_coalesces_rebuild() -> None:
    async def scenario() -> None:
        first = _SyntheticVoiceCore()
        replacement = _SyntheticVoiceCore(block_connect=True)
        factory_calls = 0

        def replacement_factory() -> _SyntheticVoiceCore:
            nonlocal factory_calls
            factory_calls += 1
            return replacement

        adapter = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=replacement_factory,
            enforced_output_suppression=True,
        )
        await adapter.connect()
        old_generation = adapter.session_generation
        old_session_ref: str | None = None
        sixty_fourth = None

        for index in range(64):
            raw_id = f"synthetic-input-{index:04d}"
            start_ms = index * 20
            started = adapter._project_correlated_input_event(
                _input_event(
                    "speech.started",
                    provider_item_ref=raw_id,
                    audio_start_ms=start_ms,
                )
            )
            stopped = adapter._project_correlated_input_event(
                _input_event(
                    "speech.stopped",
                    provider_item_ref=raw_id,
                    audio_end_ms=start_ms + 10,
                )
            )
            final = adapter._project_correlated_input_event(
                _input_event(
                    "user.transcript.final",
                    provider_item_ref=raw_id,
                    text="synthetic-redacted-final",
                )
            )
            assert started.correlation_valid is True
            assert stopped.correlation_valid is True
            assert final.correlation_valid is True
            assert final.session_generation == old_generation
            old_session_ref = final.session_ref
            sixty_fourth = final

        assert sixty_fourth is not None
        with pytest.raises(FrozenInstanceError):
            sixty_fourth.session_generation = old_generation + 1  # type: ignore[misc]

        horizon = adapter._project_correlated_input_event(
            _input_event(
                "speech.started",
                provider_item_ref="synthetic-input-at-horizon",
                audio_start_ms=1_300,
            )
        )
        assert horizon.correlation_valid is False
        assert horizon.error_code == "voice_input_context_limit_exceeded"
        assert horizon.text is None
        assert adapter.context_tainted is True
        assert adapter.counters.provider_item_id_horizon_count == 1

        rebuilds = [
            asyncio.create_task(adapter.rebuild_if_tainted())
            for _ in range(5)
        ]
        await asyncio.wait_for(replacement.connect_started.wait(), timeout=1)
        assert adapter.session_generation == old_generation + 1
        old_pcm = b"\x33\x00" * 80
        with pytest.raises(
            VoiceProviderError, match="voice_ingress_generation_stale"
        ):
            await adapter.send_audio(
                old_pcm,
                ingress_generation=old_generation,
            )

        replacement.release_connect.set()
        results = await asyncio.wait_for(
            asyncio.gather(*rebuilds),
            timeout=1,
        )
        assert results.count(True) == 1
        assert factory_calls == 1
        assert adapter.counters.context_rebuild_count == 1
        assert replacement.audio_frames == []

        current_pcm = b"\x44\x00" * 80
        await adapter.send_audio(
            current_pcm,
            ingress_generation=adapter.ingress_generation,
        )
        assert replacement.audio_frames == [current_pcm]

        new_started = adapter._project_correlated_input_event(
            _input_event(
                "speech.started",
                provider_item_ref="synthetic-new-generation-input",
                audio_start_ms=0,
            )
        )
        assert new_started.correlation_valid is True
        assert new_started.session_generation == old_generation + 1
        assert new_started.session_ref != old_session_ref
        assert sixty_fourth.session_generation == old_generation
        assert sixty_fourth.session_ref == old_session_ref
        await adapter.close()

    _run(scenario())


def test_response_id_horizon_allows_64_then_taints_65_content_free() -> None:
    async def scenario() -> None:
        events: list[NormalizedProviderEvent] = []
        for index in range(65):
            response_ref = f"synthetic-response-{index:04d}"
            events.extend(
                (
                    NormalizedProviderEvent(
                        type="response.created",
                        output_mode="real",
                        response_ref=response_ref,
                    ),
                    NormalizedProviderEvent(
                        type="response.done",
                        output_mode="real",
                        response_ref=response_ref,
                        status="cancelled",
                        terminal=True,
                    ),
                )
            )
        core = _SyntheticVoiceCore(events)
        adapter = QwenVoiceAdapter(
            provider_core=core,
            enforced_output_suppression=True,
        )
        await adapter.connect()

        for index in range(64):
            created = await adapter.recv_event(
                receiver_generation=adapter.session_generation
            )
            terminal = await adapter.recv_event(
                receiver_generation=adapter.session_generation
            )
            assert created.correlation_valid is True
            assert created.quarantined is True
            assert terminal.correlation_valid is True
            assert terminal.status == "cancelled"
            assert await adapter.cleanup_suppressed_response(
                f"synthetic-response-{index:04d}"
            ) is True

        horizon = await adapter.recv_event(
            receiver_generation=adapter.session_generation
        )
        assert horizon.correlation_valid is False
        assert horizon.quarantined is True
        assert horizon.text is None
        assert horizon.audio is None
        assert horizon.stash is None
        assert adapter.context_tainted is True
        assert len(adapter._seen_response_ids) == 64
        assert adapter.counters.provider_item_id_horizon_count == 1
        safe = json.dumps(horizon.to_safe_metadata(), sort_keys=True)
        assert "synthetic-redacted-final" not in safe
        await adapter.close()

    _run(scenario())


def test_rebuild_during_blocked_asr_final_discards_old_authority_content_free() -> None:
    async def scenario() -> None:
        browser = _BlockingFinalBrowserSink()
        provider = _GenerationRebuildProvider()
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_generation_fence",
            conversation_id="conversation_qfs_slice3a13_generation_fence",
        )
        await coordinator.start()
        try:
            correlation = {
                "provider_item_id": "voice-input-generation-0001",
                "turn_ref": "voice-turn-generation-0001",
                "utterance_ref": "voice-utterance-generation-0001",
                "audio_span_ref": "voice-audio-generation-0001",
                "session_ref": "voice-session-generation-0001",
                "session_generation": 1,
            }
            await coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="speech.started",
                    output_mode="real",
                    audio_start_ms=0,
                    **correlation,
                )
            )
            await coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="speech.stopped",
                    output_mode="real",
                    audio_start_ms=0,
                    audio_end_ms=100,
                    **correlation,
                )
            )

            sentinel = "SYNTHETIC_STALE_ASR_SENTINEL"
            old_final = asyncio.create_task(
                coordinator.handle_provider_event(
                    VoiceProviderEvent(
                        type="user.transcript.final",
                        output_mode="real",
                        text=sentinel,
                        audio_start_ms=0,
                        audio_end_ms=100,
                        **correlation,
                    )
                )
            )
            await asyncio.wait_for(browser.final_send_started.wait(), timeout=1)

            rebuild = coordinator._schedule_voice_rebuild()
            assert rebuild is not None
            assert coordinator._voice_rebuild_generation == 1
            await asyncio.wait_for(old_final, timeout=1)
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True

            journal = coordinator.journal.events()
            assert not [
                event
                for event in journal
                if event["event_name"] == "ASR_TRANSCRIPT_OUTPUT_EMITTED"
            ]
            assert not [
                event
                for event in journal
                if event["event_name"]
                in {
                    "ROUTER_DECISION_EMITTED",
                    "SLOWTASK_CREATED",
                    "USER_PATCH_RECEIVED",
                }
            ]
            assert coordinator.state.active_task is None
            assert coordinator._shadow_request_queue.qsize() == 0
            assert coordinator.state.stale_provider_event_discard_count >= 1
            assert provider.rebuild_calls == 1
            assert provider.session_generation == 2
            assert not [
                message
                for message in browser.json_messages
                if message.get("type") == "transcript.user.final"
            ]
            serialized = json.dumps(
                {
                    "journal": journal,
                    "timeline": list(coordinator.metadata_timeline),
                    "browser": browser.json_messages,
                },
                sort_keys=True,
            )
            assert sentinel not in serialized
            assert browser.binary_messages == []
        finally:
            browser.release_final_send.set()
            await coordinator.close()

    _run(scenario())


def test_enforced_provider_event_without_session_ref_has_no_authority() -> None:
    async def scenario() -> None:
        browser = _BlockingFinalBrowserSink()
        provider = _GenerationRebuildProvider()
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_missing_session_ref",
            conversation_id="conversation_qfs_slice3a13_missing_session_ref",
        )
        await coordinator.start()
        try:
            before = coordinator.state.stale_provider_event_discard_count
            await coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_id="response_missing_session_ref",
                    session_generation=provider.session_generation,
                )
            )

            assert "response_missing_session_ref" not in (
                coordinator._voice_response_lifecycles
            )
            assert coordinator.state.stale_provider_event_discard_count == before + 1
            assert not [
                message
                for message in browser.json_messages
                if message.get("response_id") == "response_missing_session_ref"
            ]
        finally:
            await coordinator.close()

    _run(scenario())


def test_coordinator_automatically_rotates_input_horizon_once_and_drains_old_pcm() -> None:
    async def scenario() -> None:
        browser = _BlockingFinalBrowserSink()
        first = _SyntheticVoiceCore(block_send=True)
        replacement = _SyntheticVoiceCore()
        factory_calls = 0

        def replacement_factory() -> _SyntheticVoiceCore:
            nonlocal factory_calls
            factory_calls += 1
            return replacement

        provider = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=replacement_factory,
            enforced_output_suppression=True,
        )
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_input_horizon",
            conversation_id="conversation_qfs_slice3a13_input_horizon",
        )
        await coordinator.start()
        old_generation = provider.session_generation
        old_pcm = b"\x55\x00" * 80
        try:
            assert await coordinator.submit_audio(old_pcm) is True
            await asyncio.wait_for(first.send_started.wait(), timeout=1)
            for _ in range(3):
                assert await coordinator.submit_audio(old_pcm) is True
            assert coordinator.input_queue_depth == 3

            for index in range(64):
                projected = provider._project_correlated_input_event(
                    _input_event(
                        "speech.started",
                        provider_item_ref=f"synthetic-coordinator-input-{index:04d}",
                        audio_start_ms=index * 20,
                    )
                )
                assert projected.correlation_valid is True
                await coordinator.handle_provider_event(projected)

            horizon = provider._project_correlated_input_event(
                _input_event(
                    "speech.started",
                    provider_item_ref="synthetic-coordinator-input-at-horizon",
                    audio_start_ms=1_300,
                )
            )
            assert horizon.correlation_valid is False
            assert provider.context_tainted is True

            # The invalid provider event is the lifecycle trigger.  This test
            # never invokes either rebuild API directly.
            await coordinator.handle_provider_event(horizon)
            rebuild = coordinator._voice_rebuild_task
            assert rebuild is not None
            assert coordinator._voice_rebuild_generation == 1
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True

            assert provider.session_generation == old_generation + 1
            assert provider.context_tainted is False
            assert provider.counters.context_rebuild_count == 1
            assert coordinator.state.voice_context_rebuild_count == 1
            assert factory_calls == 1
            assert coordinator.input_queue_depth == 0
            assert coordinator.state.voice_rebuild_pcm_drop_count >= 3
            assert replacement.audio_frames == []

            first.release_send.set()
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            assert replacement.audio_frames == []

            new_start = provider._project_correlated_input_event(
                _input_event(
                    "speech.started",
                    provider_item_ref="synthetic-coordinator-new-generation-input",
                    audio_start_ms=0,
                )
            )
            assert new_start.correlation_valid is True
            assert new_start.session_generation == old_generation + 1
            await coordinator.handle_provider_event(new_start)

            current_pcm = b"\x66\x00" * 80
            assert await coordinator.submit_audio(current_pcm) is True
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            assert replacement.audio_frames == [current_pcm]
            assert old_pcm not in replacement.audio_frames
        finally:
            first.release_send.set()
            await coordinator.close()

    _run(scenario())


def test_coordinator_owns_320_turn_horizon_rotation_without_manual_rebuild() -> None:
    async def scenario() -> None:
        cores = [_SyntheticVoiceCore() for _ in range(5)]
        replacements = deque(cores[1:])
        factory_calls = 0

        def replacement_factory() -> _SyntheticVoiceCore:
            nonlocal factory_calls
            factory_calls += 1
            return replacements.popleft()

        provider = QwenVoiceAdapter(
            provider_core=cores[0],
            provider_core_factory=replacement_factory,
            enforced_output_suppression=True,
        )
        browser = _BlockingFinalBrowserSink()
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_320_turn_rotation",
            conversation_id="conversation_qfs_slice3a13_320_turn_rotation",
        )
        await coordinator.start()
        observed_item_refs: set[str] = set()
        try:
            for generation_index in range(5):
                generation = provider.session_generation
                for turn_index in range(64):
                    projected = provider._project_correlated_input_event(
                        _input_event(
                            "speech.started",
                            provider_item_ref=(
                                f"synthetic-g{generation_index:02d}-"
                                f"input-{turn_index:04d}"
                            ),
                            audio_start_ms=turn_index * 20,
                        )
                    )
                    assert projected.correlation_valid is True
                    assert projected.session_generation == generation
                    assert projected.provider_item_id is not None
                    observed_item_refs.add(projected.provider_item_id)
                    await coordinator.handle_provider_event(projected)

                assert len(provider._input_item_contexts) == 64
                assert len(provider._input_item_order) == 64
                if generation_index == 4:
                    break

                horizon = provider._project_correlated_input_event(
                    _input_event(
                        "speech.started",
                        provider_item_ref=(
                            f"synthetic-g{generation_index:02d}-rotate"
                        ),
                        audio_start_ms=2_000,
                    )
                )
                assert horizon.correlation_valid is False
                assert horizon.error_code == "voice_input_context_limit_exceeded"

                # The invalid event transfers lifecycle ownership to the
                # coordinator. This stress path never invokes either rebuild
                # API directly.
                await coordinator.handle_provider_event(horizon)
                rebuild = coordinator._voice_rebuild_task
                assert rebuild is not None
                assert await asyncio.wait_for(
                    asyncio.shield(rebuild),
                    timeout=1,
                ) is True
                assert provider.session_generation == generation + 1
                assert provider.context_tainted is False
                assert len(provider._input_item_contexts) == 0

            assert len(observed_item_refs) == 320
            assert factory_calls == 4
            assert provider.counters.provider_item_id_horizon_count == 4
            assert provider.counters.context_rebuild_count == 4
            assert coordinator.state.voice_context_rebuild_count == 4
            assert coordinator.state.voice_session_status == "connected"
            assert coordinator._closed is False
            assert browser.binary_messages == []
        finally:
            await coordinator.close()

    _run(scenario())


def test_coordinator_response_horizon_error_storm_schedules_one_rotation() -> None:
    async def scenario() -> None:
        browser = _BlockingFinalBrowserSink()
        first = _SyntheticVoiceCore()
        replacement = _SyntheticVoiceCore()
        factory_calls = 0

        def replacement_factory() -> _SyntheticVoiceCore:
            nonlocal factory_calls
            factory_calls += 1
            return replacement

        provider = QwenVoiceAdapter(
            provider_core=first,
            provider_core_factory=replacement_factory,
            enforced_output_suppression=True,
        )
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_response_horizon",
            conversation_id="conversation_qfs_slice3a13_response_horizon",
        )
        await coordinator.start()
        old_generation = provider.session_generation
        try:
            for index in range(64):
                response_id = f"synthetic-coordinator-response-{index:04d}"
                first.response_active = True
                created = await provider._suppress_voice_output(
                    VoiceProviderEvent(
                        type="response.created",
                        output_mode="real",
                        response_id=response_id,
                        provider_item_id=f"voice-output-{index:04d}",
                        session_ref="voice-session-0001",
                        session_generation=old_generation,
                    )
                )
                terminal = await provider._suppress_voice_output(
                    VoiceProviderEvent(
                        type="response.done",
                        output_mode="real",
                        response_id=response_id,
                        provider_item_id=f"voice-output-{index:04d}",
                        session_ref="voice-session-0001",
                        session_generation=old_generation,
                        status="cancelled",
                        terminal=True,
                    )
                )
                assert created.correlation_valid is True
                assert terminal.correlation_valid is True
                assert await provider.cleanup_suppressed_response(response_id) is True

            first.response_active = True
            horizon = await provider._suppress_voice_output(
                VoiceProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_id="synthetic-coordinator-response-at-horizon",
                    provider_item_id="voice-output-at-horizon",
                    session_ref="voice-session-0001",
                    session_generation=old_generation,
                )
            )
            assert horizon.correlation_valid is False
            assert horizon.text is None
            assert horizon.audio is None
            assert provider.context_tainted is True

            # A burst of the same bounded, content-free failure must transfer
            # ownership to one active coordinator rebuild.
            await asyncio.gather(
                *(
                    coordinator.handle_provider_event(horizon)
                    for _ in range(5)
                )
            )
            rebuild = coordinator._voice_rebuild_task
            assert rebuild is not None
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True
            assert factory_calls == 1
            assert provider.counters.context_rebuild_count == 1
            assert coordinator.state.voice_context_rebuild_count == 1
            assert provider.session_generation == old_generation + 1
            assert provider.context_tainted is False
            assert coordinator.state.voice_session_status == "connected"
            assert browser.binary_messages == []
        finally:
            await coordinator.close()

    _run(scenario())


def test_inflight_response_created_control_projection_is_cancelled_on_rebuild() -> None:
    async def scenario() -> None:
        browser = _BlockingMessageBrowserSink()
        provider = _GenerationRebuildProvider()
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_created_await_fence",
            conversation_id="conversation_qfs_slice3a13_created_await_fence",
        )
        await coordinator.start()
        browser.arm("control.state")
        old_created = asyncio.create_task(
            coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_id="voice-response-created-await",
                    provider_item_id="voice-output-created-await",
                    session_ref="voice-session-generation-0001",
                    session_generation=1,
                    suppressed=True,
                    quarantined=True,
                )
            )
        )
        try:
            await asyncio.wait_for(browser.blocked_send_started.wait(), timeout=1)
            message_index_before = len(browser.json_messages)
            rebuild = coordinator._schedule_voice_rebuild()
            assert rebuild is not None
            for _ in range(100):
                if provider.session_generation == 2:
                    break
                await asyncio.sleep(0)
            assert provider.session_generation == 2

            # Retirement must cancel the authority-guarded browser projection;
            # releasing the fake sink here would race that cancellation.
            await asyncio.wait_for(old_created, timeout=1)
            browser.blocked_type = None
            browser.release_blocked_send.set()
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True

            stale_control_projections = [
                message
                for message in browser.json_messages[message_index_before:]
                if message.get("type") == "control.state"
                and message.get("voice_context_rebuild_count") == 0
            ]
            assert stale_control_projections == []
            assert "voice-response-created-await" not in (
                coordinator._voice_response_lifecycles
            )
        finally:
            browser.release_blocked_send.set()
            await asyncio.gather(old_created, return_exceptions=True)
            await coordinator.close()

    _run(scenario())


def test_old_response_done_cleanup_cannot_retire_same_id_replacement_lifecycle() -> None:
    async def scenario() -> None:
        browser = _BlockingMessageBrowserSink()
        provider = _GenerationRebuildProvider()
        provider.block_cleanup = True
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_done_aba",
            conversation_id="conversation_qfs_slice3a13_done_aba",
        )
        response_id = "voice-response-generation-aba"
        await coordinator.start()
        await coordinator.handle_provider_event(
            VoiceProviderEvent(
                type="response.created",
                output_mode="real",
                response_id=response_id,
                provider_item_id="voice-output-generation-old",
                session_ref="voice-session-generation-0001",
                session_generation=1,
                suppressed=True,
                quarantined=True,
            )
        )
        blocked_projection = asyncio.Event()
        release_projection = asyncio.Event()
        block_projection_once = True

        async def blocking_send_control_state(*args: Any, **kwargs: Any) -> None:
            nonlocal block_projection_once
            del args, kwargs
            if block_projection_once:
                block_projection_once = False
                blocked_projection.set()
                await release_projection.wait()

        coordinator._send_control_state = blocking_send_control_state  # type: ignore[method-assign]
        old_done = asyncio.create_task(
            coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="response.done",
                    output_mode="real",
                    response_id=response_id,
                    provider_item_id="voice-output-generation-old",
                    session_ref="voice-session-generation-0001",
                    session_generation=1,
                    status="cancelled",
                    terminal=True,
                    suppressed=True,
                    quarantined=True,
                )
            )
        )
        try:
            await asyncio.wait_for(provider.cleanup_started.wait(), timeout=1)
            await asyncio.wait_for(blocked_projection.wait(), timeout=1)
            cleanup_tasks = [
                task
                for task in coordinator._background_tasks
                if "voice-cleanup" in task.get_name()
            ]
            assert len(cleanup_tasks) == 1

            rebuild = coordinator._schedule_voice_rebuild()
            assert rebuild is not None
            for _ in range(100):
                if provider.session_generation == 2:
                    break
                await asyncio.sleep(0)
            assert provider.session_generation == 2
            release_projection.set()
            await asyncio.wait_for(old_done, timeout=1)
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True

            await coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_id=response_id,
                    provider_item_id="voice-output-generation-new",
                    session_ref="voice-session-generation-0002",
                    session_generation=2,
                    suppressed=True,
                    quarantined=True,
                )
            )
            assert response_id in coordinator._voice_response_lifecycles

            provider.release_cleanup.set()
            await asyncio.wait_for(
                asyncio.gather(*cleanup_tasks, return_exceptions=True),
                timeout=1,
            )
            assert response_id in coordinator._voice_response_lifecycles
            assert (
                coordinator._voice_response_lifecycles[response_id].terminal_status
                is None
            )
        finally:
            release_projection.set()
            provider.release_cleanup.set()
            await asyncio.gather(old_done, return_exceptions=True)
            await coordinator.close()

    _run(scenario())


def test_invalid_response_fences_generation_before_awaiting_fail_closed_path() -> None:
    async def scenario() -> None:
        browser = _BlockingFinalBrowserSink()
        provider = _GenerationRebuildProvider()
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a13_invalid_response_order",
            conversation_id="conversation_qfs_slice3a13_invalid_response_order",
        )
        await coordinator.start()
        entered_fail_closed = asyncio.Event()
        release_fail_closed = asyncio.Event()
        original_fail_closed = coordinator._commit_fail_closed_turn

        async def blocking_fail_closed(*args: Any, **kwargs: Any) -> None:
            entered_fail_closed.set()
            await release_fail_closed.wait()
            await original_fail_closed(*args, **kwargs)

        coordinator._commit_fail_closed_turn = blocking_fail_closed  # type: ignore[method-assign]
        handling = asyncio.create_task(
            coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="response.created",
                    output_mode="degraded",
                    response_id="voice-response-at-horizon",
                    session_ref="voice-session-generation-0001",
                    session_generation=1,
                    error_code="voice_response_id_horizon_reached",
                    suppressed=True,
                    quarantined=True,
                    correlation_valid=False,
                )
            )
        )
        try:
            await asyncio.wait_for(entered_fail_closed.wait(), timeout=1)
            assert coordinator._voice_rebuild_generation == 1
            assert coordinator._voice_rebuild_task is not None
        finally:
            release_fail_closed.set()
            await asyncio.gather(handling, return_exceptions=True)
            await coordinator.close()

    _run(scenario())


def test_committed_asr_queue_full_path_survives_cleanup_rebuild_content_free() -> None:
    async def scenario() -> None:
        blocked_site = "timeline"
        browser = _BlockingMessageBrowserSink()
        provider = _GenerationRebuildProvider()
        shadow = FakeShadowControlProvider()
        coordinator = RealtimeSessionCoordinator(
            browser,
            provider,  # type: ignore[arg-type]
            shadow_provider=shadow,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            config=CoordinatorConfig(max_shadow_request_queue=1),
            session_id=f"session_qfs_slice3a13_queue_full_{blocked_site}",
            conversation_id=f"conversation_qfs_slice3a13_queue_full_{blocked_site}",
        )
        await coordinator.start()
        assert coordinator._shadow_worker_task is not None
        coordinator._shadow_worker_task.cancel()
        await asyncio.gather(
            coordinator._shadow_worker_task, return_exceptions=True
        )
        coordinator._shadow_worker_task = None

        await _open_and_stop_voice_turn(coordinator, generation=1, index=1)
        first_turn = coordinator._current_turn
        assert first_turn is not None
        await coordinator.handle_provider_event(
            VoiceProviderEvent(
                type="user.transcript.final",
                output_mode="real",
                provider_item_id="voice-input-generation-0001-0001",
                turn_ref="voice-turn-generation-0001-0001",
                utterance_ref="voice-utterance-generation-0001-0001",
                audio_span_ref="voice-audio-generation-0001-0001",
                session_ref="voice-session-generation-0001",
                session_generation=1,
                audio_start_ms=0,
                audio_end_ms=100,
                text="synthetic-queue-filler",
            )
        )
        assert coordinator._shadow_request_queue.qsize() == 1

        await _open_and_stop_voice_turn(coordinator, generation=1, index=2)
        second_turn = coordinator._current_turn
        assert second_turn is not None
        blocked = asyncio.Event()
        release = asyncio.Event()
        original_timeline = coordinator._timeline

        async def maybe_block_timeline(
            label: str, fields: Mapping[str, Any]
        ) -> None:
            if (
                blocked_site == "timeline"
                and label == "route.control.degraded"
                and fields.get("degraded_code") == "shadow_request_queue_dropped"
            ):
                blocked.set()
                await release.wait()
            await original_timeline(label, fields)

        coordinator._timeline = maybe_block_timeline  # type: ignore[method-assign]
        sentinel = f"SYNTHETIC_STALE_QUEUE_ASR_{blocked_site.upper()}"
        old_final = asyncio.create_task(
            coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="user.transcript.final",
                    output_mode="real",
                    provider_item_id="voice-input-generation-0001-0002",
                    turn_ref="voice-turn-generation-0001-0002",
                    utterance_ref="voice-utterance-generation-0001-0002",
                    audio_span_ref="voice-audio-generation-0001-0002",
                    session_ref="voice-session-generation-0001",
                    session_generation=1,
                    audio_start_ms=0,
                    audio_end_ms=100,
                    text=sentinel,
                )
            )
        )
        try:
            await asyncio.wait_for(blocked.wait(), timeout=1)
            rebuild = coordinator._schedule_voice_rebuild()
            assert rebuild is not None
            for _ in range(100):
                if provider.session_generation == 2:
                    break
                await asyncio.sleep(0)
            assert provider.session_generation == 2
            release.set()
            await asyncio.wait_for(old_final, timeout=1)
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True

            queued_turn_ids = [
                envelope.turn.turn_id
                for envelope in tuple(coordinator._shadow_request_queue._queue)
            ]
            committed_asr_events = [
                event
                for event in coordinator.journal.events()
                if event.get("event_name") == "ASR_TRANSCRIPT_OUTPUT_EMITTED"
                and event.get("turn_id") == second_turn.turn_id
            ]
            assert {
                "queued_old_turn": second_turn.turn_id in queued_turn_ids,
                "control_analyze_called": shadow.counters.request_count != 0,
                "sentinel_in_metadata_or_journal": sentinel
                in json.dumps(
                    {
                        "journal": coordinator.journal.events(),
                        "timeline": list(coordinator.metadata_timeline),
                    },
                    sort_keys=True,
                ),
            } == {
                # Canonical final ASR was already appended before the
                # cleanup-only Voice rebuild. Local committed-turn
                # authority therefore preserves the queued Control work.
                "queued_old_turn": True,
                "control_analyze_called": False,
                "sentinel_in_metadata_or_journal": False,
            }
            assert len(committed_asr_events) == 1
        finally:
            release.set()
            await asyncio.gather(old_final, return_exceptions=True)
            await coordinator.close()

    _run(scenario())
