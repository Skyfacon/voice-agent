from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from experiments.qwen_realtime_fast_slow_web.capability_profile import (
    fake_capability_profile,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FakeShadowScript,
    FakeShadowControlProvider,
    ShadowRouteRequest,
    ShadowRouteResult,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    VoiceProviderEvent,
    VoiceProviderError,
    VoiceSuppressionCounters,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    RealtimeSessionCoordinator,
)


def _run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


class _MemorySink:
    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []

    async def send_json(self, data: Mapping[str, Any]) -> None:
        self.json_messages.append(deepcopy(dict(data)))

    async def send_bytes(self, data: bytes) -> None:
        self.binary_messages.append(bytes(data))

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _BlockingRouteProposedSink(_MemorySink):
    def __init__(self) -> None:
        super().__init__()
        self.route_proposed_started = asyncio.Event()
        self.release_route_proposed = asyncio.Event()

    async def send_json(self, data: Mapping[str, Any]) -> None:
        if data.get("type") == "route.proposed":
            self.route_proposed_started.set()
            await self.release_route_proposed.wait()
        await super().send_json(data)


class _BlockingFailingVoiceSendErrorSink(_MemorySink):
    def __init__(self) -> None:
        super().__init__()
        self.voice_send_error_started = asyncio.Event()
        self.release_voice_send_error = asyncio.Event()

    async def send_json(self, data: Mapping[str, Any]) -> None:
        if (
            data.get("type") == "safe_error"
            and data.get("code") == "voice_send_failed"
        ):
            self.voice_send_error_started.set()
            await self.release_voice_send_error.wait()
            raise RuntimeError("synthetic_voice_send_error_sink_failure")
        await super().send_json(data)


class _BlockingTerminalProjectionSink(_MemorySink):
    def __init__(self) -> None:
        super().__init__()
        self.projection_started = asyncio.Event()
        self.release_projection = asyncio.Event()
        self.block_control_state = False

    async def send_json(self, data: Mapping[str, Any]) -> None:
        if data.get("type") == "control.state" and self.block_control_state:
            self.projection_started.set()
            await self.release_projection.wait()
        await super().send_json(data)


class _BlockingRecoveryTimelineSink(_MemorySink):
    def __init__(self) -> None:
        super().__init__()
        self.timeline_started = asyncio.Event()
        self.release_timeline = asyncio.Event()

    async def send_json(self, data: Mapping[str, Any]) -> None:
        if (
            data.get("type") == "timeline.metadata"
            and data.get("event") == "voice.recovery"
        ):
            self.timeline_started.set()
            await self.release_timeline.wait()
        await super().send_json(data)


class _CleanupRebuildingVoiceProvider:
    """Provider-free Voice generation used to model cleanup-only rebuild."""

    def __init__(self) -> None:
        self.profile = fake_capability_profile()
        self.counters = VoiceSuppressionCounters()
        self.enforced_output_suppression = True
        self.ingress_generation = 1
        self.session_generation = 1
        self.rebuild_calls = 0

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
        return True

    async def wait_response_complete(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _TypedIngressVoiceProvider(_CleanupRebuildingVoiceProvider):
    def __init__(self) -> None:
        super().__init__()
        self.availability_code = "available"
        self.sent_frames: list[bytes] = []
        self.send_attempt_count = 0
        self.context_tainted = False

    @property
    def ingress_availability_code(self) -> str:
        return self.availability_code

    async def send_audio(self, pcm: bytes, *, ingress_generation: int) -> None:
        self.send_attempt_count += 1
        if ingress_generation != self.ingress_generation:
            raise VoiceProviderError("voice_ingress_generation_stale")
        if self.availability_code != "available":
            raise VoiceProviderError(self.availability_code, retryable=True)
        self.sent_frames.append(bytes(pcm))


class _AlwaysFailingSendVoiceProvider(_TypedIngressVoiceProvider):
    async def send_audio(self, _pcm: bytes, *, ingress_generation: int) -> None:
        self.send_attempt_count += 1
        if ingress_generation != self.ingress_generation:
            raise VoiceProviderError("voice_ingress_generation_stale")
        self.context_tainted = True
        self.counters.audio_send_failure_count = 1
        raise VoiceProviderError("voice_send_failed", retryable=True)

    async def rebuild_if_tainted(self) -> bool:
        self.rebuild_calls += 1
        self.ingress_generation += 1
        self.session_generation += 1
        self.context_tainted = False
        self.counters.context_rebuild_count += 1
        return True


class _FailOnceSendVoiceProvider(_TypedIngressVoiceProvider):
    def __init__(self) -> None:
        super().__init__()
        self.failed_frame: bytes | None = None

    async def send_audio(self, pcm: bytes, *, ingress_generation: int) -> None:
        self.send_attempt_count += 1
        if ingress_generation != self.ingress_generation:
            raise VoiceProviderError("voice_ingress_generation_stale")
        if self.failed_frame is None:
            self.failed_frame = bytes(pcm)
            self.context_tainted = True
            self.availability_code = "voice_context_tainted"
            self.counters.audio_send_failure_count = 1
            raise VoiceProviderError("voice_send_failed", retryable=True)
        self.sent_frames.append(bytes(pcm))

    async def rebuild_if_tainted(self) -> bool:
        self.rebuild_calls += 1
        self.ingress_generation += 1
        self.session_generation += 1
        self.context_tainted = False
        self.availability_code = "available"
        self.counters.context_rebuild_count += 1
        return True


class _BlockingRecordingControlProvider(FakeShadowControlProvider):
    def __init__(self, scripts: list[FakeShadowScript] | None = None) -> None:
        super().__init__(scripts or ())
        self.analyze_started = asyncio.Event()
        self.release_analyze = asyncio.Event()
        self.requests: list[ShadowRouteRequest] = []

    async def analyze(
        self,
        request: ShadowRouteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> ShadowRouteResult:
        self.requests.append(request)
        self.analyze_started.set()
        await self.release_analyze.wait()
        return await super().analyze(request, timeout_seconds=timeout_seconds)


def _voice_event(
    event_type: str,
    *,
    index: int = 1,
    text: str | None = None,
    audio_end_ms: int | None = None,
) -> VoiceProviderEvent:
    return VoiceProviderEvent(
        type=event_type,
        output_mode="real",
        text=text,
        audio_start_ms=0,
        audio_end_ms=audio_end_ms,
        provider_item_id=f"voice-input-slice3a21-{index:04d}",
        turn_ref=f"voice-turn-slice3a21-{index:04d}",
        utterance_ref=f"voice-utterance-slice3a21-{index:04d}",
        audio_span_ref=f"voice-audio-slice3a21-{index:04d}",
        session_ref="voice-session-slice3a21-generation-0001",
        session_generation=1,
    )


def _events_for_turn(
    coordinator: RealtimeSessionCoordinator,
    event_names: set[str],
    turn_id: str,
) -> list[dict[str, Any]]:
    return [
        event
        for event in coordinator.journal.events()
        if event.get("event_name") in event_names
        and event.get("turn_id") == turn_id
    ]


def _gate_events_for_turn(
    coordinator: RealtimeSessionCoordinator,
    turn_id: str,
) -> list[dict[str, Any]]:
    router_ids = {
        str(event["event_id"])
        for event in _events_for_turn(
            coordinator, {"ROUTER_DECISION_EMITTED"}, turn_id
        )
    }
    return [
        event
        for event in coordinator.journal.events()
        if event.get("event_name")
        in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}
        and event.get("router_decision_event_id") in router_ids
    ]


async def _commit_voice_turn(
    coordinator: RealtimeSessionCoordinator,
    *,
    index: int = 1,
    transcript: str = "synthetic redacted committed turn",
) -> str:
    await coordinator.handle_provider_event(
        _voice_event("speech.started", index=index)
    )
    await coordinator.handle_provider_event(
        _voice_event("speech.stopped", index=index, audio_end_ms=100)
    )
    await coordinator.handle_provider_event(
        _voice_event(
            "user.transcript.final",
            index=index,
            text=transcript,
            audio_end_ms=100,
        )
    )
    asr_events = [
        event
        for event in coordinator.journal.events()
        if event.get("event_name") == "ASR_TRANSCRIPT_OUTPUT_EMITTED"
        and event.get("utterance_id")
    ]
    assert len(asr_events) == index
    return str(asr_events[-1]["turn_id"])


def test_cleanup_only_voice_rebuild_preserves_committed_control_authority_once() -> None:
    async def scenario() -> None:
        sink = _MemorySink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_committed_authority",
            conversation_id="conversation_qfs_slice3a21_committed_authority",
        )
        await coordinator.start()
        try:
            turn_id = await _commit_voice_turn(coordinator)
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)

            # This is the cleanup-only transport rotation from the real fault:
            # the ASR final is already locally committed and Control is running.
            rebuild = coordinator._schedule_voice_rebuild()
            assert rebuild is not None
            assert await asyncio.wait_for(asyncio.shield(rebuild), timeout=1) is True
            control.release_analyze.set()
            await asyncio.wait_for(coordinator._shadow_request_queue.join(), timeout=1)

            routers = _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, turn_id
            )
            gates = _gate_events_for_turn(coordinator, turn_id)
            assert (len(control.requests), len(routers), len(gates)) == (1, 1, 1)
            assert voice.rebuild_calls == 1
            assert sink.binary_messages == []
        finally:
            control.release_analyze.set()
            await coordinator.close()

    _run(scenario())


def test_voice_cleanup_error_before_final_asr_does_not_claim_control_terminal() -> None:
    async def scenario() -> None:
        sink = _MemorySink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_pre_asr_voice_error",
            conversation_id="conversation_qfs_slice3a21_pre_asr_voice_error",
        )
        await coordinator.start()
        try:
            await coordinator.handle_provider_event(
                _voice_event("speech.started")
            )
            await coordinator.handle_provider_event(
                _voice_event("speech.stopped", audio_end_ms=100)
            )
            await coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="provider.error",
                    output_mode="degraded",
                    error_code="provider_invalid_request",
                    terminal=False,
                    session_ref="voice-session-slice3a21-generation-0001",
                    session_generation=1,
                )
            )
            assert coordinator.state.voice_session_status == "connected"
            assert coordinator.state.voice_context_tainted is False
            assert await coordinator.submit_audio(b"\x21\x00" * 1_600) is True
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            await coordinator.handle_provider_event(
                _voice_event(
                    "user.transcript.final",
                    text="synthetic final after voice cleanup error",
                    audio_end_ms=100,
                )
            )
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)
            turn_id = str(control.requests[0].turn_id)
            control.release_analyze.set()
            await asyncio.wait_for(coordinator._shadow_request_queue.join(), timeout=1)

            asr = _events_for_turn(
                coordinator, {"ASR_TRANSCRIPT_OUTPUT_EMITTED"}, turn_id
            )
            routers = _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, turn_id
            )
            gates = _gate_events_for_turn(coordinator, turn_id)
            assert (len(asr), len(control.requests), len(routers), len(gates)) == (
                1,
                1,
                1,
                1,
            )
            assert not [
                item
                for item in coordinator.metadata_timeline
                if item.get("event") == "route.control.late_discarded"
                and item.get("metadata", {}).get("degraded_code")
                == "control_result_after_terminal"
            ]
            assert sink.binary_messages == []
        finally:
            control.release_analyze.set()
            await coordinator.close()

    _run(scenario())


def test_terminal_voice_rebuild_is_not_wedged_by_blocked_browser_projection() -> None:
    async def scenario() -> None:
        sink = _BlockingTerminalProjectionSink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_terminal_projection",
            conversation_id="conversation_qfs_slice3a21_terminal_projection",
        )
        await coordinator.start()
        failure_task: asyncio.Task[None] | None = None
        try:
            turn_id = await _commit_voice_turn(coordinator)
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)
            sink.block_control_state = True
            failure_task = asyncio.create_task(
                coordinator.handle_provider_event(
                    VoiceProviderEvent(
                        type="provider.disconnected",
                        output_mode="degraded",
                        error_code="voice_provider_disconnected",
                        terminal=True,
                        session_ref="voice-session-slice3a21-generation-0001",
                        session_generation=1,
                    )
                )
            )
            await asyncio.wait_for(sink.projection_started.wait(), timeout=1)

            rebuild = coordinator._voice_rebuild_task
            assert rebuild is not None
            assert (
                await asyncio.wait_for(asyncio.shield(rebuild), timeout=1.25)
                is True
            )
            assert voice.rebuild_calls == 1
            assert voice.session_generation == 2
            assert len(
                _events_for_turn(
                    coordinator, {"ROUTER_DECISION_EMITTED"}, turn_id
                )
            ) == 1
            assert len(_gate_events_for_turn(coordinator, turn_id)) == 1
            assert _events_for_turn(
                coordinator, {"SLOWTASK_CREATED"}, turn_id
            ) == []
            assert sink.binary_messages == []
        finally:
            sink.release_projection.set()
            control.release_analyze.set()
            if failure_task is not None:
                await asyncio.gather(failure_task, return_exceptions=True)
            await coordinator.close()

    _run(scenario())


@pytest.mark.parametrize(
    "supersede_action",
    (
        "new_speech",
        "explicit_interrupt",
        "playback_epoch_change",
        "disconnect_request",
        "browser_close",
    ),
)
def test_superseding_boundary_invalidates_old_control_result_without_rebinding(
    supersede_action: str,
) -> None:
    async def scenario() -> None:
        sink = _MemorySink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id=f"session_qfs_slice3a21_supersede_{supersede_action}",
            conversation_id=f"conversation_qfs_slice3a21_{supersede_action}",
        )
        await coordinator.start()
        closed = False
        try:
            old_turn_id = await _commit_voice_turn(coordinator)
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)

            if supersede_action == "new_speech":
                await coordinator.handle_provider_event(
                    _voice_event("speech.started", index=2)
                )
            elif supersede_action == "explicit_interrupt":
                await coordinator.handle_control({"type": "interrupt.request"})
            elif supersede_action == "playback_epoch_change":
                await coordinator._clear_voice_playback(reason="synthetic_epoch_change")
            elif supersede_action == "disconnect_request":
                await coordinator.handle_control({"type": "disconnect"})
            else:
                await coordinator.close()
                closed = True

            control.release_analyze.set()
            if not closed:
                await asyncio.wait_for(
                    coordinator._shadow_request_queue.join(), timeout=1
                )

            old_routers = _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, old_turn_id
            )
            old_gates = _gate_events_for_turn(coordinator, old_turn_id)
            assert len(control.requests) == 1
            assert old_routers == []
            assert old_gates == []
            assert sink.binary_messages == []
            assert not [
                message
                for message in sink.json_messages
                if message.get("type", "").startswith("transcript.assistant")
                and message.get("turn_id") == old_turn_id
            ]
        finally:
            control.release_analyze.set()
            if not closed:
                await coordinator.close()

    _run(scenario())


def test_disconnect_while_route_proposed_projection_is_blocked_revokes_authority() -> None:
    async def scenario() -> None:
        sink = _BlockingRouteProposedSink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_post_analyze_disconnect",
            conversation_id="conversation_qfs_slice3a21_post_analyze_disconnect",
        )
        await coordinator.start()
        try:
            turn_id = await _commit_voice_turn(coordinator)
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)
            control.release_analyze.set()
            await asyncio.wait_for(sink.route_proposed_started.wait(), timeout=1)

            assert _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, turn_id
            ) == []
            assert _gate_events_for_turn(coordinator, turn_id) == []

            await coordinator.handle_control({"type": "disconnect"})
            sink.release_route_proposed.set()
            await asyncio.wait_for(
                coordinator._shadow_request_queue.join(), timeout=1
            )

            assert len(control.requests) == 1
            assert _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, turn_id
            ) == []
            assert _gate_events_for_turn(coordinator, turn_id) == []
            assert not [
                message
                for message in sink.json_messages
                if message.get("type", "").startswith("transcript.assistant")
                and message.get("turn_id") == turn_id
            ]
            assert sink.binary_messages == []
        finally:
            control.release_analyze.set()
            sink.release_route_proposed.set()
            await coordinator.close()

    _run(scenario())


def test_new_committed_turn_supersedes_old_result_and_keeps_bindings_distinct() -> None:
    async def scenario() -> None:
        sink = _MemorySink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_new_committed_turn",
            conversation_id="conversation_qfs_slice3a21_new_committed_turn",
        )
        await coordinator.start()
        try:
            old_turn_id = await _commit_voice_turn(coordinator, index=1)
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)
            new_turn_id = await _commit_voice_turn(
                coordinator,
                index=2,
                transcript="synthetic redacted replacement turn",
            )

            control.release_analyze.set()
            await asyncio.wait_for(coordinator._shadow_request_queue.join(), timeout=2)

            old_routers = _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, old_turn_id
            )
            old_gates = _gate_events_for_turn(coordinator, old_turn_id)
            new_routers = _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, new_turn_id
            )
            new_gates = _gate_events_for_turn(coordinator, new_turn_id)
            assert len(control.requests) == 2
            assert old_routers == []
            assert old_gates == []
            assert len(new_routers) == 1
            assert len(new_gates) == 1
            assert control.requests[0].turn_id == old_turn_id
            assert control.requests[1].turn_id == new_turn_id
            assert control.requests[0].utterance_id != control.requests[1].utterance_id
            assert sink.binary_messages == []
        finally:
            control.release_analyze.set()
            await coordinator.close()

    _run(scenario())


def test_duplicate_asr_final_emits_only_one_control_router_gate_chain() -> None:
    async def scenario() -> None:
        sink = _MemorySink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_duplicate_final",
            conversation_id="conversation_qfs_slice3a21_duplicate_final",
        )
        await coordinator.start()
        try:
            turn_id = await _commit_voice_turn(coordinator)
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)
            await coordinator.handle_provider_event(
                _voice_event(
                    "user.transcript.final",
                    text="synthetic duplicate final must not enqueue",
                    audio_end_ms=100,
                )
            )
            control.release_analyze.set()
            await asyncio.wait_for(coordinator._shadow_request_queue.join(), timeout=2)
            rebuild = coordinator._voice_rebuild_task
            if rebuild is not None:
                await asyncio.wait_for(asyncio.shield(rebuild), timeout=1)

            asr = _events_for_turn(
                coordinator, {"ASR_TRANSCRIPT_OUTPUT_EMITTED"}, turn_id
            )
            routers = _events_for_turn(
                coordinator, {"ROUTER_DECISION_EMITTED"}, turn_id
            )
            gates = _gate_events_for_turn(coordinator, turn_id)
            assert (len(asr), len(control.requests), len(routers), len(gates)) == (
                1,
                1,
                1,
                1,
            )
            assert _events_for_turn(coordinator, {"SLOWTASK_CREATED"}, turn_id) == []
            assert _events_for_turn(coordinator, {"USER_PATCH_RECEIVED"}, turn_id) == []
            assert sink.binary_messages == []
        finally:
            control.release_analyze.set()
            await coordinator.close()

    _run(scenario())


def test_expected_recovery_pcm_is_dropped_coalesced_and_never_replayed() -> None:
    async def scenario() -> None:
        sink = _MemorySink()
        voice = _TypedIngressVoiceProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_recovery_pcm",
            conversation_id="conversation_qfs_slice3a21_recovery_pcm",
        )
        await coordinator.start()
        try:
            recovery_codes = (
                "voice_context_rebuilding",
                "voice_context_tainted",
                "voice_provider_not_connected",
                "voice_ingress_generation_stale",
                "voice_ingress_generation_retired",
            )
            accepted: list[bool] = []
            retired_frames: list[bytes] = []
            for code_index, code in enumerate(recovery_codes, start=1):
                voice.availability_code = code
                for frame_index in range(3):
                    frame = bytes([code_index, frame_index]) * 1_600
                    retired_frames.append(frame)
                    accepted.append(await coordinator.submit_audio(frame))

            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            assert accepted == [False] * len(retired_frames)
            assert voice.send_attempt_count == 0
            assert voice.sent_frames == []
            assert coordinator.state.voice_rebuild_pcm_drop_count == 15

            recovery_metadata = [
                message
                for message in sink.json_messages
                if message.get("type") in {"degraded", "voice.recovering"}
                and (
                    message.get("code") == "voice_recovering"
                    or message.get("degraded_code") == "voice_recovering"
                    or message.get("recovery_status") == "voice_recovering"
                )
            ]
            assert len(recovery_metadata) == 1
            assert not [
                message
                for message in sink.json_messages
                if message.get("type") == "safe_error"
                and message.get("code") == "audio_forward_failed"
            ]

            voice.availability_code = "available"
            fresh_frame = b"\x7f\x00" * 1_600
            assert await coordinator.submit_audio(fresh_frame) is True
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            assert voice.sent_frames == [fresh_frame]
            assert all(frame not in voice.sent_frames for frame in retired_frames)
        finally:
            await coordinator.close()

    _run(scenario())


def test_recovery_timeline_sink_cannot_wedge_pcm_drop_completion() -> None:
    async def scenario() -> None:
        sink = _BlockingRecoveryTimelineSink()
        voice = _TypedIngressVoiceProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_recovery_timeline",
            conversation_id="conversation_qfs_slice3a21_recovery_timeline",
        )
        await coordinator.start()
        try:
            voice.availability_code = "voice_context_tainted"
            submit = asyncio.create_task(
                coordinator.submit_audio(b"\x41\x00" * 1_600)
            )
            await asyncio.wait_for(sink.timeline_started.wait(), timeout=1)
            assert await asyncio.wait_for(submit, timeout=1) is False
            assert coordinator.state.voice_rebuild_pcm_drop_count == 1
            assert coordinator._input_task is not None
            assert not coordinator._input_task.done()
            assert sink.binary_messages == []
        finally:
            sink.release_timeline.set()
            await coordinator.close()

    _run(scenario())


def test_real_voice_send_failure_emits_one_safe_error_and_one_rebuild() -> None:
    async def scenario() -> None:
        sink = _MemorySink()
        voice = _AlwaysFailingSendVoiceProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_send_failure",
            conversation_id="conversation_qfs_slice3a21_send_failure",
        )
        await coordinator.start()
        try:
            for index in range(8):
                assert await coordinator.submit_audio(
                    bytes([index + 1, 0]) * 1_600
                ) is True
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            await asyncio.sleep(0)
            rebuild = coordinator._voice_rebuild_task
            if rebuild is not None:
                await asyncio.wait_for(asyncio.shield(rebuild), timeout=1)

            safe_errors = [
                message
                for message in sink.json_messages
                if message.get("type") == "safe_error"
            ]
            assert [message.get("code") for message in safe_errors] == [
                "voice_send_failed"
            ]
            assert voice.rebuild_calls == 1
            assert voice.counters.audio_send_failure_count == 1
            assert coordinator.state.voice_audio_send_failure_count == 1
            assert coordinator.state.voice_context_rebuild_count == 1
            # No duplicate scheduler raced this single failure. The adapter's
            # coalesced counter counts joined duplicate rebuild callers only.
            assert coordinator.state.voice_rebuild_coalesced_count == 0
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    _run(scenario())


def test_voice_send_failure_fences_before_failing_browser_projection() -> None:
    async def scenario() -> None:
        sink = _BlockingFailingVoiceSendErrorSink()
        voice = _FailOnceSendVoiceProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_send_failure_sink_fault",
            conversation_id="conversation_qfs_slice3a21_send_failure_sink_fault",
        )
        await coordinator.start()
        try:
            failed_frame = b"\x11\x00" * 1_600
            queued_old_frame = b"\x22\x00" * 1_600
            assert await coordinator.submit_audio(failed_frame) is True
            assert await coordinator.submit_audio(queued_old_frame) is True
            await asyncio.wait_for(
                sink.voice_send_error_started.wait(), timeout=1
            )

            # Recovery authority must be established before awaiting any
            # fallible browser projection.
            assert coordinator._voice_rebuild_generation == 1
            rebuild = coordinator._voice_rebuild_task
            assert rebuild is not None

            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)
            await asyncio.wait_for(asyncio.shield(rebuild), timeout=1)

            assert coordinator._input_task is not None
            assert not coordinator._input_task.done()
            fresh_frame = b"\x33\x00" * 1_600
            assert await coordinator.submit_audio(fresh_frame) is True
            await asyncio.wait_for(coordinator._input_queue.join(), timeout=1)

            assert voice.failed_frame == failed_frame
            assert voice.sent_frames == [fresh_frame]
            assert queued_old_frame not in voice.sent_frames
            assert sink.binary_messages == []
        finally:
            sink.release_voice_send_error.set()
            await coordinator.close()

    _run(scenario())


def test_metadata_is_bounded_and_omits_secrets_payloads_transcript_and_candidate() -> None:
    async def scenario() -> None:
        transcript_sentinel = "PRIVATE_FULL_TRANSCRIPT_SLICE3A21"
        candidate_sentinel = (
            "PRIVATE_CANDIDATE_SLICE3A21 Authorization: Bearer SENTINEL_SECRET"
        )
        raw_payload_sentinel = "PRIVATE_RAW_PROVIDER_EVENT_PAYLOAD_SLICE3A21"
        function_args_sentinel = "PRIVATE_FULL_FUNCTION_ARGUMENTS_SLICE3A21"
        sink = _MemorySink()
        voice = _CleanupRebuildingVoiceProvider()
        control = _BlockingRecordingControlProvider(
            [
                FakeShadowScript(
                    proposal_frame={
                        "schema_version": "qwen_realtime_route_v1",
                        "task_focus_hint": "FOREGROUND_CHAT",
                        "route_decision_hint": "FAST_ONLY",
                        "foreground_act": "ANSWER",
                        "task_like": False,
                        "complexity_hint": "LOW",
                        "evidence_uncertainty": "LOW",
                        "risk_class": "LOW",
                        "risk_tags": ["none"],
                        "confidence": 0.99,
                        "reply_candidate_text": (
                            candidate_sentinel
                            + function_args_sentinel
                            + raw_payload_sentinel
                        ),
                    }
                )
            ]
        )
        coordinator = RealtimeSessionCoordinator(
            sink,
            voice,  # type: ignore[arg-type]
            shadow_provider=control,
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a21_metadata_safety",
            conversation_id="conversation_qfs_slice3a21_metadata_safety",
        )
        await coordinator.start()
        try:
            await _commit_voice_turn(
                coordinator,
                transcript=transcript_sentinel,
            )
            await asyncio.wait_for(control.analyze_started.wait(), timeout=1)
            control.release_analyze.set()
            await asyncio.wait_for(coordinator._shadow_request_queue.join(), timeout=1)

            metadata_messages = [
                message
                for message in sink.json_messages
                if message.get("type")
                not in {
                    "transcript.user.delta",
                    "transcript.user.final",
                    "transcript.assistant.delta",
                    "transcript.assistant.done",
                }
            ]
            serialized_metadata = json.dumps(
                {
                    "journal": coordinator.journal.events(),
                    "timeline": list(coordinator.metadata_timeline),
                    "messages": metadata_messages,
                    "state": coordinator.state.to_metadata(),
                },
                sort_keys=True,
            )
            serialized_browser = json.dumps(sink.json_messages, sort_keys=True)
            for sentinel in (
                transcript_sentinel,
                candidate_sentinel,
                raw_payload_sentinel,
                function_args_sentinel,
                "Authorization",
                "Bearer",
                "SENTINEL_SECRET",
            ):
                assert sentinel not in serialized_metadata
            for sentinel in (
                candidate_sentinel,
                raw_payload_sentinel,
                function_args_sentinel,
                "Authorization",
                "Bearer",
                "SENTINEL_SECRET",
            ):
                assert sentinel not in serialized_browser
            assert sink.binary_messages == []
            assert coordinator.state.binary_playback_frame_count == 0
        finally:
            control.release_analyze.set()
            await coordinator.close()

    _run(scenario())


def test_ui_timeline_allowlists_bounded_cancel_and_recovery_metadata() -> None:
    app_js = (
        Path(__file__).parents[3]
        / "experiments"
        / "qwen_realtime_fast_slow_web"
        / "static"
        / "app.js"
    ).read_text(encoding="utf-8")

    bounded_fields = {
        "cancel_terminal_outcome",
        "voice_cancel_terminal_outcome",
        "voice_cancel_terminal_timeout_count",
        "voice_unsafe_cancel_terminal_count",
        "voice_completed_after_cancel_count",
        "voice_failed_after_cancel_count",
        "voice_rebuild_pcm_drop_count",
        "voice_audio_send_failure_count",
        "voice_rebuild_coalesced_count",
    }
    for field in bounded_fields:
        assert f'"{field}"' in app_js

    bounded_outcomes = {
        "cancelled_on_time",
        "cancelled_after_watchdog",
        "completed_after_cancel",
        "failed_after_cancel",
        "missing_terminal",
    }
    for outcome in bounded_outcomes:
        assert f'"{outcome}"' in app_js
    assert "cancel_terminal_outcome: CANCEL_TERMINAL_OUTCOMES" in app_js
    assert "voice_cancel_terminal_outcome: CANCEL_TERMINAL_OUTCOMES" in app_js
