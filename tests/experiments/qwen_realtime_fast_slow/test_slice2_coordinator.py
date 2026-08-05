from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Mapping

from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeRealtimeProvider,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FakeShadowControlProvider,
    FakeShadowScript,
    SCHEMA_VERSION,
    ShadowAdapterCounters,
    ShadowRouteRequest,
    ShadowRouteResult,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    ActiveSlowTaskState,
    CoordinatorConfig,
    RealtimeSessionCoordinator,
)


def run(coro):
    return asyncio.run(coro)


def proposal_frame(**overrides: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "task_focus_hint": "FOREGROUND_CHAT",
        "route_decision_hint": "FAST_ONLY",
        "foreground_act": "ANSWER",
        "task_like": False,
        "complexity_hint": "LOW",
        "evidence_uncertainty": "LOW",
        "risk_class": "LOW",
        "risk_tags": ["none"],
        "confidence": 0.95,
        "reply_candidate_text": "SHADOW-CANDIDATE-MUST-STAY-TRANSIENT",
    }
    frame.update(overrides)
    return frame


class MemoryBrowserSink:
    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []
        self.records: list[tuple[str, Any]] = []
        self.closed = False

    async def send_json(self, data: Mapping[str, Any]) -> None:
        copied = deepcopy(dict(data))
        self.json_messages.append(copied)
        self.records.append(("json", copied))

    async def send_bytes(self, data: bytes) -> None:
        copied = bytes(data)
        self.binary_messages.append(copied)
        self.records.append(("binary", copied))

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        self.closed = True


class RecordingShadowProvider(FakeShadowControlProvider):
    def __init__(self, scripts=()) -> None:
        super().__init__(scripts)
        self.requests: list[ShadowRouteRequest] = []

    async def analyze(
        self,
        request: ShadowRouteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> ShadowRouteResult:
        self.requests.append(request)
        return await super().analyze(request, timeout_seconds=timeout_seconds)


class BlockingFirstShadowProvider(RecordingShadowProvider):
    def __init__(self, scripts=()) -> None:
        super().__init__(scripts)
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def analyze(
        self,
        request: ShadowRouteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> ShadowRouteResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            self.first_started.set()
            await self.release_first.wait()
        return await FakeShadowControlProvider.analyze(
            self, request, timeout_seconds=timeout_seconds
        )


class WrongCorrelationShadowProvider(RecordingShadowProvider):
    async def analyze(
        self,
        request: ShadowRouteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> ShadowRouteResult:
        self.requests.append(request)
        valid = await FakeShadowControlProvider.analyze(
            self, request, timeout_seconds=timeout_seconds
        )
        return ShadowRouteResult(
            request_id="wrong-request",
            turn_id="wrong-turn",
            utterance_id="wrong-utterance",
            safe_turn_ref=valid.safe_turn_ref,
            output_mode=valid.output_mode,
            schema_valid=valid.schema_valid,
            proposal=valid.proposal,
            latency=valid.latency,
        )


async def make_shadow_coordinator(
    shadow_provider: FakeShadowControlProvider,
    *,
    config: CoordinatorConfig | None = None,
    voice_config: FakeProviderConfig | None = None,
) -> tuple[
    RealtimeSessionCoordinator,
    FakeRealtimeProvider,
    MemoryBrowserSink,
]:
    sink = MemoryBrowserSink()
    voice = FakeRealtimeProvider(
        voice_config
        or FakeProviderConfig(response_audio_chunks=2, event_delay_seconds=0)
    )
    coordinator = RealtimeSessionCoordinator(
        sink,
        voice,
        shadow_provider=shadow_provider,
        provider_mode="fake",
        routing_mode="shadow",
        audio_output="fake_pcm",
        shadow_control_mode="dual_session_shadow",
        config=config,
        session_id="session_qfs_shadow_test",
        conversation_id="conversation_qfs_shadow_test",
    )
    await coordinator.start()
    await asyncio.sleep(0)
    return coordinator, voice, sink


def by_type(messages: list[dict[str, Any]], message_type: str) -> list[dict[str, Any]]:
    return [message for message in messages if message.get("type") == message_type]


def journal_names(coordinator: RealtimeSessionCoordinator) -> list[str]:
    return [str(event["event_name"]) for event in coordinator.journal.events()]


async def wait_until(predicate, *, timeout: float = 1.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=timeout)


def assert_no_shadow_authority_mutation(coordinator: RealtimeSessionCoordinator) -> None:
    names = journal_names(coordinator)
    assert "ROUTER_DECISION_EMITTED" not in names
    assert "TASK_FOCUS_STATE_UPDATED" not in names
    assert not any(name.startswith("SLOWTASK_") for name in names)
    assert not any(name.startswith("USER_PATCH_") for name in names)
    assert "PLAN_VERSION_ADVANCED" not in names
    assert "FOREGROUND_ACT_GATE_PASSED" not in names
    assert "FOREGROUND_ACT_GATE_FAILED" not in names
    assert "FOREGROUND_OUTPUT_COMMITTED" not in names
    assert "FOREGROUND_OUTPUT_DISCARDED" not in names
    assert coordinator.state.router_decision is None
    assert coordinator.state.task_focus is None
    assert coordinator.state.gate_status is None


def test_dual_session_shadow_forwards_final_once_and_keeps_voice_visible() -> None:
    async def scenario() -> None:
        shadow = RecordingShadowProvider(["valid"])
        coordinator, voice, sink = await make_shadow_coordinator(shadow)
        try:
            ready = by_type(sink.json_messages, "session.ready")[-1]
            assert ready["provider_mode"] == "fake"
            assert ready["routing_mode"] == "shadow"
            assert ready["audio_output"] == "fake_pcm"
            assert ready["shadow_control_mode"] == "dual_session_shadow"
            assert ready["voice_session_status"] == "connected"
            assert ready["shadow_control_session_status"] == "connected"
            assert ready["output_mode"] == "mock"

            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert len(shadow.requests) == 1
            forwarded = shadow.requests[0]
            assert forwarded.transcript.startswith("[synthetic]")
            assert forwarded.task_focus_snapshot == {
                "has_active_non_terminal_task": False,
                "pending_confirmation": False,
                "side_conversation_allowed": True,
                "default_patch_policy": "NO_ACTIVE_TASK",
                "ambiguous_input_policy": "CLARIFY",
            }
            assert len(by_type(sink.json_messages, "transcript.user.final")) == 1
            assert by_type(sink.json_messages, "transcript.assistant.done")
            assert len(sink.binary_messages) == 2
            assert len(by_type(sink.json_messages, "route.shadow.proposed")) == 1
            assert len(by_type(sink.json_messages, "route.shadow.validated")) == 1
            compared = by_type(sink.json_messages, "route.shadow.compared")[-1]
            assert compared["qwen_route_hint"] == "FAST_ONLY"
            assert compared["local_router_decision"] == "FAST_ONLY"
            assert compared["agreement"] == "yes"
            assert compared["schema_status"] == "valid"
            assert not by_type(sink.json_messages, "route.decided")
            assert not by_type(sink.json_messages, "gate.result")
            assert not by_type(sink.json_messages, "slowtask.state")
            assert not by_type(sink.json_messages, "userpatch.accepted")
            serialized_ui = json.dumps(sink.json_messages, sort_keys=True)
            assert "SHADOW-CANDIDATE-MUST-STAY-TRANSIENT" not in serialized_ui
            assert_no_shadow_authority_mutation(coordinator)
            assert coordinator.state.active_task is None
        finally:
            await coordinator.close()

    run(scenario())


def test_shadow_mismatch_and_pending_context_do_not_patch_authoritative_task() -> None:
    async def scenario() -> None:
        shadow = RecordingShadowProvider(
            [
                FakeShadowScript(
                    proposal_frame=proposal_frame(
                        task_focus_hint="ACTIVE_TASK_PATCH",
                        route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
                        foreground_act="ACK_PATCH",
                        task_like=True,
                        complexity_hint="MEDIUM",
                    )
                )
            ]
        )
        coordinator, voice, sink = await make_shadow_coordinator(shadow)
        authoritative_task = ActiveSlowTaskState(
            task_id="task_qfs_authoritative",
            lifecycle="WAITING_FOR_USER_CONFIRMATION",
            plan_version=7,
            task_event_seq=11,
            pending_confirmation_id="confirmation_qfs_1",
            pending_confirmation_scope="TASK_CANCEL",
        )
        coordinator.state.active_task = authoritative_task
        before = deepcopy(authoritative_task.to_metadata())
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            compared = by_type(sink.json_messages, "route.shadow.compared")[-1]
            assert compared["qwen_route_hint"] == "PATCH_ACTIVE_SLOW_TASK"
            assert compared["local_router_decision"] == "PATCH_ACTIVE_SLOW_TASK"
            assert compared["active_task_present"] is True
            assert compared["pending_confirmation_present"] is True
            assert compared["agreement"] == "yes"
            assert shadow.requests[0].task_focus_snapshot == {
                "has_active_non_terminal_task": True,
                "active_task_ref": shadow.requests[0].task_focus_snapshot[
                    "active_task_ref"
                ],
                "lifecycle_phase": "WAITING_FOR_USER_CONFIRMATION",
                "current_plan_version": 7,
                "pending_confirmation": True,
                "side_conversation_allowed": True,
                "default_patch_policy": "ACTIVE_TASK_PATCH_ONLY",
                "ambiguous_input_policy": "CLARIFY",
            }
            assert coordinator.state.active_task is authoritative_task
            assert coordinator.state.active_task.to_metadata() == before
            assert not by_type(sink.json_messages, "userpatch.accepted")
            assert_no_shadow_authority_mutation(coordinator)
        finally:
            await coordinator.close()

    run(scenario())


def test_shadow_degraded_timeout_and_disconnect_never_stop_voice_output() -> None:
    async def execute(script: str) -> tuple[RealtimeSessionCoordinator, list[dict[str, Any]], int]:
        shadow = RecordingShadowProvider([script])
        coordinator, voice, sink = await make_shadow_coordinator(
            shadow,
            config=CoordinatorConfig(shadow_request_timeout_seconds=0.01),
        )
        await voice.trigger_scenario("fast")
        await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
        return coordinator, sink.json_messages, len(sink.binary_messages)

    async def scenario() -> None:
        for script, expected_code in (
            ("plain_text", "shadow_ordinary_text_instead_of_function_call"),
            ("timeout", "shadow_request_timeout"),
            ("disconnect", "shadow_provider_disconnected"),
        ):
            coordinator, messages, binary_count = await execute(script)
            try:
                degraded_messages = by_type(messages, "route.shadow.degraded")
                assert degraded_messages, (
                    [message.get("type") for message in messages],
                    coordinator._shadow_worker_task.exception()
                    if coordinator._shadow_worker_task is not None
                    and coordinator._shadow_worker_task.done()
                    else None,
                )
                degraded = degraded_messages[-1]
                assert degraded["degraded_code"] == expected_code
                assert degraded["agreement"] == "not_available"
                assert not by_type(messages, "route.shadow.proposed")
                assert by_type(messages, "transcript.assistant.done")
                assert binary_count == 2
                assert coordinator.state.voice_session_status == "connected"
                assert_no_shadow_authority_mutation(coordinator)
            finally:
                await coordinator.close()

    run(scenario())


def test_context_delete_taint_rebuild_is_visible_but_non_authoritative() -> None:
    async def scenario() -> None:
        shadow = RecordingShadowProvider(["delete_fail", "valid"])
        coordinator, voice, sink = await make_shadow_coordinator(shadow)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert shadow.counters.context_delete_failure_count == 1
            assert shadow.counters.context_rebuild_count == 1
            assert coordinator.state.context_rebuild_count == 1
            assert coordinator.state.context_tainted is False
            assert coordinator.state.shadow_control_session_status == "connected"

            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert len(shadow.requests) == 2
            assert len(by_type(sink.json_messages, "route.shadow.compared")) == 2
            assert coordinator.state.context_delete_count == 2
            assert coordinator.state.context_rebuild_count == 1
            assert_no_shadow_authority_mutation(coordinator)
        finally:
            await coordinator.close()

    run(scenario())


def test_late_result_and_bounded_queue_drop_do_not_rebind_new_turn() -> None:
    async def scenario() -> None:
        shadow = BlockingFirstShadowProvider(["valid", "valid"])
        coordinator, voice, sink = await make_shadow_coordinator(
            shadow,
            config=CoordinatorConfig(
                max_shadow_request_queue=1,
                shadow_request_timeout_seconds=1.0,
            ),
            voice_config=FakeProviderConfig(
                response_audio_chunks=1,
                event_delay_seconds=0,
            ),
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(shadow.first_started.wait(), timeout=2)
            await voice.trigger_scenario("fast")
            await voice.trigger_scenario("fast")
            await wait_until(
                lambda: len(by_type(sink.json_messages, "transcript.user.final")) >= 3,
                timeout=2,
            )
            shadow.release_first.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            # First became stale while active; second was dropped from the
            # one-slot queue; only the newest third turn was compared.
            assert len(shadow.requests) == 2
            assert shadow.counters.late_event_discard_count >= 1
            assert coordinator.state.shadow_drop_count >= 1
            compared = by_type(sink.json_messages, "route.shadow.compared")
            assert len(compared) == 1
            assert compared[0]["safe_turn_ref"] == shadow.requests[-1].safe_turn_ref
            assert compared[0]["safe_turn_ref"] != shadow.requests[0].safe_turn_ref
            assert_no_shadow_authority_mutation(coordinator)
        finally:
            shadow.release_first.set()
            await coordinator.close()

    run(scenario())


def test_invalid_shadow_result_correlation_is_degraded_and_not_compared() -> None:
    async def scenario() -> None:
        shadow = WrongCorrelationShadowProvider(["valid"])
        coordinator, voice, sink = await make_shadow_coordinator(shadow)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            degraded_messages = by_type(sink.json_messages, "route.shadow.degraded")
            assert degraded_messages, (
                [message.get("type") for message in sink.json_messages],
                coordinator._shadow_worker_task.exception()
                if coordinator._shadow_worker_task is not None
                and coordinator._shadow_worker_task.done()
                else None,
            )
            degraded = degraded_messages[-1]
            assert degraded["degraded_code"] == "shadow_result_correlation_invalid"
            assert degraded["agreement"] == "not_available"
            assert not by_type(sink.json_messages, "route.shadow.proposed")
            assert not by_type(sink.json_messages, "route.shadow.compared")
            assert_no_shadow_authority_mutation(coordinator)
        finally:
            await coordinator.close()

    run(scenario())


def test_context_incompatible_valid_proposal_degrades_without_stopping_worker() -> None:
    async def scenario() -> None:
        shadow = RecordingShadowProvider(
            [
                FakeShadowScript(
                    proposal_frame=proposal_frame(
                        task_focus_hint="ACTIVE_TASK_PATCH",
                        route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
                        foreground_act="ACK_PATCH",
                        task_like=True,
                    )
                )
            ]
        )
        coordinator, voice, sink = await make_shadow_coordinator(shadow)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert by_type(sink.json_messages, "route.shadow.proposed")
            assert by_type(sink.json_messages, "route.shadow.validated")[-1][
                "schema_status"
            ] == "valid"
            assert not by_type(sink.json_messages, "route.shadow.compared")
            degraded = by_type(sink.json_messages, "route.shadow.degraded")[-1]
            assert degraded["degraded_code"] == (
                "shadow_local_router_evaluation_failed"
            )
            assert degraded["schema_status"] == "valid"
            assert by_type(sink.json_messages, "transcript.assistant.done")
            assert coordinator._shadow_worker_task is not None
            assert not coordinator._shadow_worker_task.done()
            assert_no_shadow_authority_mutation(coordinator)
        finally:
            await coordinator.close()

    run(scenario())


def test_voice_disconnect_is_terminal_for_voice_but_does_not_promote_shadow() -> None:
    async def scenario() -> None:
        shadow = RecordingShadowProvider()
        coordinator, voice, sink = await make_shadow_coordinator(shadow)
        try:
            await voice.trigger_scenario("provider_disconnect")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            errors = by_type(sink.json_messages, "safe_error")
            assert errors
            assert errors[-1]["terminal"] is True
            assert errors[-1]["code"] == "synthetic_provider_disconnect"
            assert coordinator.state.voice_session_status == "disconnected"
            assert coordinator.state.shadow_control_session_status == "connected"
            assert coordinator.state.active_task is None
            assert not by_type(sink.json_messages, "route.shadow.proposed")
            assert not by_type(sink.json_messages, "route.shadow.compared")
            assert_no_shadow_authority_mutation(coordinator)
        finally:
            await coordinator.close()

    run(scenario())


def test_shadow_metadata_timeline_has_no_audio_transcript_or_full_arguments() -> None:
    async def scenario() -> None:
        shadow = RecordingShadowProvider(["valid"])
        coordinator, voice, sink = await make_shadow_coordinator(shadow)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            timeline = json.dumps(list(coordinator.metadata_timeline), sort_keys=True)
            journal = json.dumps(coordinator.journal.events(), sort_keys=True)

            for serialized in (timeline, journal):
                for forbidden in (
                    "SHADOW-CANDIDATE-MUST-STAY-TRANSIENT",
                    "Synthetic fast reply.",
                    "[synthetic] handle this quick question",
                    "function_arguments",
                    "provider_payload",
                    "raw_audio",
                    "authorization",
                    "api_key",
                    "Bearer ",
                ):
                    assert forbidden not in serialized
            assert_no_shadow_authority_mutation(coordinator)
        finally:
            await coordinator.close()

    run(scenario())
