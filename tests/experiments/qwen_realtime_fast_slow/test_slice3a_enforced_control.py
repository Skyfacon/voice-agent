from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Mapping

import pytest

from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeProviderEvent,
    FakeRealtimeProvider,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    MAX_REPLY_CANDIDATE_CHARS,
    SCHEMA_VERSION,
    FakeShadowControlProvider,
    FakeShadowScript,
    ShadowRouteRequest,
    ShadowRouteResult,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    VoiceProviderEvent,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    ActiveSlowTaskState,
    CoordinatorConfig,
    RealtimeSessionCoordinator,
)
from voice_agent.events.registry import (
    FAST_FOREGROUND_EVENT_NAMES,
    MVP0_EVENT_NAMES,
    MVP1_EVENT_NAMES,
    MVP2_EVENT_NAMES,
)
from voice_agent.replay.runner import run_replay_fixture


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
        "reply_candidate_text": "CONTROL-CANDIDATE-SENTINEL",
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


class FaultOnceBrowserSink(MemoryBrowserSink):
    def __init__(
        self,
        message_type: str,
        *,
        fail_after_record: bool = False,
        armed: bool = True,
    ) -> None:
        super().__init__()
        self.message_type = message_type
        self.fail_after_record = fail_after_record
        self.armed = armed
        self.failure_count = 0

    async def send_json(self, data: Mapping[str, Any]) -> None:
        should_fail = (
            self.armed
            and self.failure_count == 0
            and data.get("type") == self.message_type
        )
        if should_fail and not self.fail_after_record:
            self.failure_count += 1
            raise RuntimeError("PRIVATE_BROWSER_FAULT_SENTINEL")
        await super().send_json(data)
        if should_fail:
            self.failure_count += 1
            raise RuntimeError("PRIVATE_BROWSER_FAULT_SENTINEL")


class RecordingControlProvider(FakeShadowControlProvider):
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


class BlockingFirstControlProvider(RecordingControlProvider):
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


class BlockingNthControlProvider(RecordingControlProvider):
    def __init__(self, scripts=(), *, block_index: int) -> None:
        super().__init__(scripts)
        self.block_index = block_index
        self.block_started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(
        self,
        request: ShadowRouteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> ShadowRouteResult:
        self.requests.append(request)
        if len(self.requests) == self.block_index:
            self.block_started.set()
            await self.release.wait()
        return await FakeShadowControlProvider.analyze(
            self, request, timeout_seconds=timeout_seconds
        )


class SlowCancelControlProvider(BlockingFirstControlProvider):
    def __init__(self, scripts=()) -> None:
        super().__init__(scripts)
        self.cancel_started = asyncio.Event()
        self.release_cancel = asyncio.Event()
        self.cancel_should_block = False

    async def cancel_active_request(self) -> bool:
        if not self.cancel_should_block:
            return await super().cancel_active_request()
        self.cancel_started.set()
        await self.release_cancel.wait()
        return await super().cancel_active_request()


class WrongCorrelationControlProvider(RecordingControlProvider):
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


class DeleteFailRebuildingVoiceProvider(FakeRealtimeProvider):
    def __init__(self) -> None:
        super().__init__(
            FakeProviderConfig(response_audio_chunks=2, event_delay_seconds=0.01)
        )
        self.cleanup_calls: list[str] = []
        self.rebuild_calls = 0

    async def cleanup_suppressed_response(self, response_id: str) -> bool:
        self.cleanup_calls.append(response_id)
        return False

    async def rebuild_if_tainted(self) -> bool:
        self.rebuild_calls += 1
        return True


class BlockingRebuildVoiceProvider(FakeRealtimeProvider):
    def __init__(self, *, rebuild_success: bool) -> None:
        super().__init__(FakeProviderConfig(event_delay_seconds=0))
        self.rebuild_success = rebuild_success
        self.rebuild_calls = 0
        self.rebuild_started = asyncio.Event()
        self.release_rebuild = asyncio.Event()

    async def rebuild_if_tainted(self) -> bool:
        self.rebuild_calls += 1
        self.rebuild_started.set()
        await self.release_rebuild.wait()
        return self.rebuild_success


async def make_enforced_coordinator(
    control: FakeShadowControlProvider,
    *,
    config: CoordinatorConfig | None = None,
    voice_config: FakeProviderConfig | None = None,
    voice_provider: FakeRealtimeProvider | None = None,
    browser_sink: MemoryBrowserSink | None = None,
    session_id: str = "session_qfs_slice3a",
) -> tuple[RealtimeSessionCoordinator, FakeRealtimeProvider, MemoryBrowserSink]:
    sink = browser_sink or MemoryBrowserSink()
    voice = voice_provider or FakeRealtimeProvider(
        voice_config
        or FakeProviderConfig(response_audio_chunks=2, event_delay_seconds=0.001)
    )
    coordinator = RealtimeSessionCoordinator(
        sink,
        voice,
        shadow_provider=control,
        provider_mode="qwen",
        routing_mode="enforced",
        audio_output="none",
        shadow_control_mode="dual_session",
        config=config,
        session_id=session_id,
        conversation_id=f"conversation_{session_id}",
    )
    await coordinator.start()
    await asyncio.sleep(0)
    return coordinator, voice, sink


def by_type(messages: list[dict[str, Any]], message_type: str) -> list[dict[str, Any]]:
    return [message for message in messages if message.get("type") == message_type]


def journal_events(
    coordinator: RealtimeSessionCoordinator, event_name: str
) -> list[dict[str, Any]]:
    return [
        event
        for event in coordinator.journal.events()
        if event["event_name"] == event_name
    ]


def journal_names(coordinator: RealtimeSessionCoordinator) -> list[str]:
    return [str(event["event_name"]) for event in coordinator.journal.events()]


def assert_turn_has_unique_terminal_authority(
    coordinator: RealtimeSessionCoordinator,
    sink: MemoryBrowserSink,
    turn_id: str,
) -> None:
    routers = [
        event
        for event in journal_events(coordinator, "ROUTER_DECISION_EMITTED")
        if event.get("turn_id") == turn_id
    ]
    assert len(routers) <= 1
    router_ids = {str(event["event_id"]) for event in routers}
    gates = [
        event
        for event in coordinator.journal.events()
        if event["event_name"]
        in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}
        and event.get("router_decision_event_id") in router_ids
    ]
    assert len(gates) <= 1
    committed = [
        event
        for event in journal_events(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
        if event.get("turn_id") == turn_id
    ]
    discarded = [
        event
        for event in journal_events(coordinator, "FOREGROUND_OUTPUT_DISCARDED")
        if event.get("router_decision_event_id") in router_ids
    ]
    assert len(committed) <= 1
    assert len(discarded) <= 1
    if committed and committed[0].get("output_basis") == "reply_candidate":
        assert discarded == []
    if gates:
        gate_id = gates[0]["event_id"]
        assert all(event.get("gate_event_id") == gate_id for event in committed)
        assert all(event.get("caused_by_event_id") == gate_id for event in discarded)
    assert len(
        [
            event
            for event in journal_events(coordinator, "SLOWTASK_CREATED")
            if event.get("created_from_turn_id") == turn_id
            or event.get("turn_id") == turn_id
        ]
    ) <= 1
    assert len(
        [
            event
            for event in journal_events(coordinator, "USER_PATCH_RECEIVED")
            if event.get("turn_id") == turn_id
        ]
    ) <= 1
    dispatches = [
        message
        for message in by_type(sink.json_messages, "dispatch.result")
        if message.get("turn_id") == turn_id
    ]
    assert len(dispatches) == 1


def replay_fixture(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": "replay_qfs_slice3a_enforced",
            "source_trace_ref": "fixture://qfs/slice3a/enforced",
            "replay_mode": "deterministic",
            "event_schema_version_range": ["1.0"],
            "fixture_domain": "GITHUB_ALLOWED",
            "generated_from": "synthetic",
            "contains_raw_audio": False,
            "contains_raw_trace": False,
            "contains_real_user_input": False,
            "contains_secrets": False,
            "contains_unredacted_tool_result": False,
            "contains_large_raw_web_content": False,
            "allowed_re_eval_components": [],
        },
        "events": events,
    }


def assert_server_committed_template(message: Mapping[str, Any], act: str) -> None:
    assert message["server_committed"] is True
    assert message["source"] == "controlled_template"
    assert message["foreground_act"] == act
    assert isinstance(message["commit_ref"], str) and message["commit_ref"]


def voice_input_event(
    event_type: str,
    *,
    item: str | None,
    turn: str,
    utterance: str,
    span: str,
    text: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    correlation_valid: bool = True,
    error_code: str | None = None,
) -> VoiceProviderEvent:
    return VoiceProviderEvent(
        type=event_type,
        output_mode="real" if correlation_valid else "degraded",
        provider_item_id=item,
        turn_ref=turn,
        utterance_ref=utterance,
        audio_span_ref=span,
        session_ref="voice-session-0001",
        text=text,
        audio_start_ms=start_ms,
        audio_end_ms=end_ms,
        correlation_valid=correlation_valid,
        error_code=error_code,
        suppressed=not correlation_valid,
        quarantined=not correlation_valid,
    )


def test_dual_session_enforced_connects_and_projects_explicit_authority() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider()
        coordinator, _voice, sink = await make_enforced_coordinator(control)
        try:
            ready = by_type(sink.json_messages, "session.ready")[-1]
            assert ready["provider_mode"] == "qwen"
            assert ready["routing_mode"] == "enforced"
            assert ready["audio_output"] == "none"
            assert ready["output"] == "text_only"
            assert ready["slow_runtime_mode"] == "mock"
            assert ready["control_topology"] == "dual_session_enforced_control"
            assert ready["experimental"] is True
            assert ready["qwen_proposal_authority"] == "non_authoritative"
            assert ready["local_router_authority"] == "authoritative"
            assert ready["provider_native_audio_disabled"] is True
            assert ready["voice_session_status"] == "connected"
            assert ready["shadow_control_session_status"] == "connected"
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_continuous_voice_pcm_commits_final_once_and_control_snapshot_is_minimal() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider([FakeShadowScript(proposal_frame=proposal_frame())])
        coordinator, voice, sink = await make_enforced_coordinator(
            control,
            voice_config=FakeProviderConfig(
                auto_stop_after_voiced_frames=3,
                transcript_delta_every_frames=1,
                response_audio_chunks=2,
                event_delay_seconds=0,
            ),
        )
        try:
            await coordinator.handle_control({"type": "microphone.start"})
            pcm = (1_000).to_bytes(2, "little", signed=True) * 1_600
            assert [await coordinator.submit_audio(pcm) for _ in range(3)] == [
                True,
                True,
                True,
            ]
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert voice.sent_audio_frames == 3
            assert len(by_type(sink.json_messages, "transcript.user.delta")) == 3
            assert len(by_type(sink.json_messages, "transcript.user.final")) == 1
            assert len(control.requests) == 1
            request = control.requests[0]
            assert request.transcript.startswith("[synthetic]")
            assert request.task_focus_snapshot == {
                "has_active_non_terminal_task": False,
                "pending_confirmation": False,
                "side_conversation_allowed": True,
                "default_patch_policy": "NO_ACTIVE_TASK",
                "ambiguous_input_policy": "CLARIFY",
            }
            assert len(journal_events(coordinator, "TURN_INGRESS_COMMITTED")) == 1
            assert len(journal_events(coordinator, "ROUTER_DECISION_EMITTED")) == 1
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_provider_fast_candidate_is_quarantined_and_local_template_is_committed() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider([FakeShadowScript(proposal_frame=proposal_frame())])
        coordinator, voice, sink = await make_enforced_coordinator(
            control,
            voice_config=FakeProviderConfig(
                response_audio_chunks=2, event_delay_seconds=0.01
            ),
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            decisions = by_type(sink.json_messages, "route.decided")
            assert len(decisions) == 1
            assert decisions[0]["router_decision"] == "FAST_ONLY"
            assert decisions[0]["task_focus"] == "FOREGROUND_CHAT"
            gate_message = by_type(sink.json_messages, "gate.result")[-1]
            assert gate_message["gate_status"] == "failed"
            assert gate_message["failure_reason"] == "candidate_policy_quarantined"
            dispatch = by_type(sink.json_messages, "dispatch.result")[-1]
            assert dispatch["actual_dispatch"] == "clarify"
            assistants = by_type(sink.json_messages, "transcript.assistant.done")
            assert len(assistants) == 1
            assistant = assistants[0]
            assert assistant["text"] != "CONTROL-CANDIDATE-SENTINEL"
            assert assistant["source"] == "controlled_template"
            assert assistant["foreground_act"] == "CLARIFY"
            assert assistant["server_committed"] is True
            assert isinstance(assistant["commit_ref"], str) and assistant["commit_ref"]

            gate_index = next(
                index
                for index, record in enumerate(sink.records)
                if record[0] == "json" and record[1].get("type") == "gate.result"
            )
            assistant_index = next(
                index
                for index, record in enumerate(sink.records)
                if record[0] == "json"
                and record[1].get("type") == "transcript.assistant.done"
            )
            assert assistant_index > gate_index
            names = journal_names(coordinator)
            assert names.index("ROUTER_DECISION_EMITTED") < names.index(
                "FOREGROUND_ACT_GATE_FAILED"
            ) < names.index("FOREGROUND_OUTPUT_DISCARDED") < names.index(
                "FOREGROUND_OUTPUT_COMMITTED"
            )
            assert not journal_events(coordinator, "FOREGROUND_ACT_GATE_PASSED")
            assert not [
                event
                for event in journal_events(
                    coordinator, "FOREGROUND_OUTPUT_COMMITTED"
                )
                if event.get("output_basis") == "reply_candidate"
            ]
            assert "Synthetic fast reply." not in json.dumps(sink.json_messages)
            assert sink.binary_messages == []
            assert voice.cancel_count == 1
            assert coordinator.state.voice_cancel_count == 1
            assert coordinator.state.voice_cancel_terminal_count == 1
            assert coordinator.state.voice_context_delete_count == 1
            assert coordinator.state.assistant_text_suppression_count >= 1
            assert coordinator.state.audio_suppression_count >= 1
            assert coordinator.state.binary_playback_frame_count == 0
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    "overrides",
    (
        {"reply_candidate_text": ""},
        {"reply_candidate_text": "x" * (MAX_REPLY_CANDIDATE_CHARS + 1)},
        {"route_decision_hint": "SPAWN_SLOW_TASK"},
        {"risk_class": "HIGH"},
        {"confidence": 0.2},
    ),
)
def test_fast_missing_oversized_disagreeing_or_unsafe_candidate_fails_closed(
    overrides: dict[str, object],
) -> None:
    async def scenario() -> None:
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=proposal_frame(**overrides))]
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert coordinator.state.active_task is None
            assert not by_type(sink.json_messages, "slowtask.state")
            assert not by_type(sink.json_messages, "userpatch.accepted")
            visible = by_type(sink.json_messages, "transcript.assistant.done")
            if visible:
                assert_server_committed_template(visible[-1], "CLARIFY")
                assert visible[-1]["text"] != overrides.get("reply_candidate_text")
            assert "Synthetic fast reply." not in json.dumps(sink.json_messages)
            assert sink.binary_messages == []
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
        finally:
            await coordinator.close()

    run(scenario())


def test_local_spawn_is_authoritative_and_creates_exactly_one_mock_task() -> None:
    async def scenario() -> None:
        frame = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="FAST_ONLY",  # provider hint deliberately disagrees
            foreground_act="ANSWER",
            task_like=True,
            complexity_hint="HIGH",
            reply_candidate_text="UNTRUSTED-SPAWN-CANDIDATE",
        )
        control = RecordingControlProvider([FakeShadowScript(proposal_frame=frame)])
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            decision = by_type(sink.json_messages, "route.decided")[-1]
            assert decision["router_decision"] == "SPAWN_SLOW_TASK"
            assert by_type(sink.json_messages, "dispatch.result")[-1][
                "actual_dispatch"
            ] == "mock_slow_spawn"
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.plan_version == 1
            assert len(journal_events(coordinator, "SLOWTASK_CREATED")) == 1
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
            assistant = by_type(sink.json_messages, "transcript.assistant.done")[-1]
            assert_server_committed_template(assistant, "ACK_SLOW")
            serialized = json.dumps(sink.json_messages)
            assert "UNTRUSTED-SPAWN-CANDIDATE" not in serialized
            assert "Uncommitted provider slow-task answer." not in serialized
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_patch_rereads_authoritative_task_and_binds_userpatch_events() -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        patch = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            complexity_hint="MEDIUM",
            reply_candidate_text="UNTRUSTED-PATCH-CANDIDATE",
        )
        control = RecordingControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=patch),
            ]
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            task = coordinator.state.active_task
            assert task is not None
            task_id = task.task_id
            old_version = task.plan_version

            start = len(sink.json_messages)
            await voice.trigger_scenario("patch")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            messages = sink.json_messages[start:]

            assert by_type(messages, "route.decided")[-1]["router_decision"] == (
                "PATCH_ACTIVE_SLOW_TASK"
            )
            accepted = by_type(messages, "userpatch.accepted")[-1]
            assert accepted["task_id"] == task_id
            assert accepted["observed_plan_version"] == old_version
            assert accepted["plan_version"] == old_version + 1
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.task_id == task_id
            assert coordinator.state.active_task.plan_version == old_version + 1
            assert by_type(messages, "dispatch.result")[-1]["actual_dispatch"] == (
                "user_patch"
            )
            assistant = by_type(messages, "transcript.assistant.done")[-1]
            assert_server_committed_template(assistant, "ACK_PATCH")
            for event_name in (
                "USER_PATCH_RECEIVED",
                "USER_PATCH_INTERPRETED",
                "PLAN_VERSION_ADVANCED",
            ):
                events = journal_events(coordinator, event_name)
                assert events
                assert events[-1]["task_id"] == task_id
            assert "UNTRUSTED-PATCH-CANDIDATE" not in json.dumps(messages)
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_stale_patch_snapshot_never_applies_to_the_old_plan_version() -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        patch = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            complexity_hint="MEDIUM",
        )
        control = BlockingNthControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=patch),
            ],
            block_index=2,
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            task = coordinator.state.active_task
            assert task is not None
            old_version = task.plan_version

            await voice.trigger_scenario("patch")
            await asyncio.wait_for(control.block_started.wait(), timeout=2)
            # Simulate an authoritative lifecycle owner advancing while the
            # remote Control result is still in flight.
            task.plan_version += 4
            task.task_event_seq += 4
            current_version = task.plan_version
            control.release.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            patches = by_type(sink.json_messages, "userpatch.accepted")
            if patches:
                accepted = patches[-1]
                assert accepted["observed_plan_version"] == current_version
                assert accepted["observed_plan_version"] != old_version
                assert accepted["plan_version"] == current_version + 1
            else:
                assert by_type(sink.json_messages, "dispatch.result")[-1][
                    "actual_dispatch"
                ] == "degraded"
                assert coordinator.state.active_task.plan_version == current_version
            dispatch = by_type(sink.json_messages, "dispatch.result")[-1]
            assert dispatch["stale_status"] in {
                "rebased_current_state",
                "failed_closed",
                "re_evaluated_same_task_plan_advanced",
            }
            assert sink.binary_messages == []
        finally:
            control.release.set()
            await coordinator.close()

    run(scenario())


def test_qwen_cancel_hint_enters_userpatch_confirmation_instead_of_cancelling_directly() -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        cancel = proposal_frame(
            task_focus_hint="CANCEL_OR_PAUSE_CANDIDATE",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="CLARIFY",
            task_like=True,
            complexity_hint="LOW",
            reply_candidate_text="QWEN-MUST-NOT-CANCEL-DIRECTLY",
        )
        control = RecordingControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=cancel),
            ]
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            task = coordinator.state.active_task
            assert task is not None
            task_id = task.task_id

            start = len(sink.json_messages)
            await voice.trigger_scenario("cancel")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            messages = sink.json_messages[start:]

            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.task_id == task_id
            assert coordinator.state.active_task.terminal_status is None
            assert coordinator.state.active_task.lifecycle == (
                "WAITING_FOR_USER_CONFIRMATION"
            )
            assert coordinator.state.active_task.pending_confirmation_scope == (
                "TASK_CANCEL"
            )
            assert by_type(messages, "userpatch.accepted")
            assert by_type(messages, "dispatch.result")[-1]["actual_dispatch"] == (
                "user_patch"
            )
            assert journal_events(coordinator, "CONFIRMATION_REQUIRED")
            assert not journal_events(coordinator, "SLOWTASK_CANCELLED")
            assert "QWEN-MUST-NOT-CANCEL-DIRECTLY" not in json.dumps(messages)
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    ("frame", "voice_scenario", "expected_dispatch", "expected_act"),
    (
        (
            proposal_frame(
                task_focus_hint="NON_ASSISTANT",
                route_decision_hint="IGNORE",
                foreground_act="SILENCE",
                confidence=0.99,
            ),
            "ignore",
            "ignore",
            None,
        ),
        (
            proposal_frame(
                task_focus_hint="AMBIGUOUS",
                route_decision_hint="FAST_ONLY",
                foreground_act="ANSWER",
                confidence=0.5,
            ),
            "ambiguous",
            "clarify",
            "CLARIFY",
        ),
    ),
)
def test_ignore_is_silent_and_ambiguous_uses_only_controlled_clarify(
    frame: dict[str, object],
    voice_scenario: str,
    expected_dispatch: str,
    expected_act: str | None,
) -> None:
    async def scenario() -> None:
        control = RecordingControlProvider([FakeShadowScript(proposal_frame=frame)])
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario(voice_scenario)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            dispatch = by_type(sink.json_messages, "dispatch.result")[-1]
            assert dispatch["actual_dispatch"] == expected_dispatch
            assistants = by_type(sink.json_messages, "transcript.assistant.done")
            if expected_act is None:
                assert assistants == []
            else:
                assert len(assistants) == 1
                assert_server_committed_template(assistants[0], expected_act)
            assert coordinator.state.active_task is None
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
            assert "Uncommitted provider" not in json.dumps(sink.json_messages)
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    "script",
    (
        "plain_text",
        "malformed",
        "wrong_name",
        "provider_error",
        "disconnect",
        FakeShadowScript(
            proposal_frame={
                key: value
                for key, value in proposal_frame().items()
                if key != "foreground_act"
            }
        ),
        FakeShadowScript(proposal_frame=proposal_frame(risk_class="CRITICAL")),
        FakeShadowScript(proposal_frame=proposal_frame(confidence=1.5)),
    ),
)
def test_invalid_or_missing_function_call_fails_closed_without_state_mutation(
    script: FakeShadowScript | str,
) -> None:
    async def scenario() -> None:
        control = RecordingControlProvider([script])
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert coordinator.state.active_task is None
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
            assert not journal_events(coordinator, "PLAN_VERSION_ADVANCED")
            assistants = by_type(sink.json_messages, "transcript.assistant.done")
            if assistants:
                assert_server_committed_template(assistants[-1], "CLARIFY")
            assert "CONTROL-CANDIDATE-SENTINEL" not in json.dumps(
                sink.json_messages
            )
            assert "Synthetic fast reply." not in json.dumps(sink.json_messages)
            assert sink.binary_messages == []
            dispatch = by_type(sink.json_messages, "dispatch.result")
            assert len(dispatch) == 1
            assert dispatch[0]["actual_dispatch"] == "degraded"
            assert len(journal_events(coordinator, "TURN_INGRESS_COMMITTED")) == 1
            assert len(journal_events(coordinator, "ROUTER_DECISION_EMITTED")) == 1
        finally:
            await coordinator.close()

    run(scenario())


def test_timeout_fails_closed_and_context_delete_failure_rebuilds_control_only() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider(
            ["timeout", "delete_fail", FakeShadowScript(proposal_frame=proposal_frame())]
        )
        coordinator, voice, sink = await make_enforced_coordinator(
            control,
            config=CoordinatorConfig(shadow_request_timeout_seconds=0.01),
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert control.counters.timeout_count == 1
            assert coordinator.state.active_task is None

            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert control.counters.context_delete_failure_count == 1

            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert control.counters.context_rebuild_count >= 1
            assert coordinator.state.voice_session_status == "connected"
            assert coordinator.state.shadow_control_session_status == "connected"
            assert len(control.requests) == 3
            assert len(journal_events(coordinator, "SLOWTASK_CREATED")) == 0
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_voice_delete_failure_rebuilds_only_voice_and_never_releases_output() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=proposal_frame())]
        )
        voice = DeleteFailRebuildingVoiceProvider()
        coordinator, _voice, sink = await make_enforced_coordinator(
            control, voice_provider=voice
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert len(voice.cleanup_calls) == 1
            assert voice.rebuild_calls == 1
            assert coordinator.state.voice_context_rebuild_count == 1
            assert coordinator.state.voice_context_tainted is False
            assert coordinator.state.voice_session_status == "connected"
            assert coordinator.state.shadow_control_session_status == "connected"
            assert coordinator.state.voice_cancel_count == 1
            assert coordinator.state.voice_cancel_terminal_count == 1
            assert "Synthetic fast reply." not in json.dumps(sink.json_messages)
            assert sink.binary_messages == []
            assert coordinator.state.binary_playback_frame_count == 0
        finally:
            await coordinator.close()

    run(scenario())


def test_wrong_correlation_late_result_queue_drop_and_supersede_never_rebind() -> None:
    async def wrong_correlation() -> None:
        control = WrongCorrelationControlProvider([FakeShadowScript(proposal_frame=proposal_frame())])
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert coordinator.state.active_task is None
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert "CONTROL-CANDIDATE-SENTINEL" not in json.dumps(
                sink.json_messages
            )
            assert sink.binary_messages == []
            assert by_type(sink.json_messages, "dispatch.result")
        finally:
            await coordinator.close()

    async def supersede() -> None:
        frame = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        control = BlockingFirstControlProvider(
            [
                FakeShadowScript(proposal_frame=frame),
                FakeShadowScript(proposal_frame=proposal_frame()),
            ]
        )
        coordinator, voice, sink = await make_enforced_coordinator(
            control,
            config=CoordinatorConfig(
                max_shadow_request_queue=1,
                shadow_request_timeout_seconds=1.0,
            ),
            voice_config=FakeProviderConfig(
                response_audio_chunks=1, event_delay_seconds=0
            ),
        )
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(control.first_started.wait(), timeout=2)
            await voice.trigger_scenario("fast")
            await voice.trigger_scenario("fast")
            control.release_first.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert coordinator.state.active_task is None
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert coordinator.state.shadow_drop_count >= 1
            assert control.counters.late_event_discard_count >= 1
            # Only the newest committed turn may reach the authoritative
            # Router/Gate/dispatch chain. Superseded and queue-dropped Control
            # work is metadata-only late evidence.
            assert len(by_type(sink.json_messages, "dispatch.result")) == 1
            assert len(journal_events(coordinator, "ROUTER_DECISION_EMITTED")) == 1
            assert (
                len(journal_events(coordinator, "FOREGROUND_ACT_GATE_PASSED"))
                + len(journal_events(coordinator, "FOREGROUND_ACT_GATE_FAILED"))
                == 1
            )
            assert sink.binary_messages == []
        finally:
            control.release_first.set()
            await coordinator.close()

    run(wrong_correlation())
    run(supersede())


def test_enforced_journal_is_authoritative_registry_only_and_replays() -> None:
    async def capture() -> tuple[list[dict[str, Any]], MemoryBrowserSink]:
        control = RecordingControlProvider([FakeShadowScript(proposal_frame=proposal_frame())])
        coordinator, voice, sink = await make_enforced_coordinator(
            control, session_id="session_qfs_slice3a_replay"
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            return coordinator.journal.events(), sink
        finally:
            await coordinator.close()

    events, sink = run(capture())
    canonical = (
        MVP0_EVENT_NAMES | MVP1_EVENT_NAMES | MVP2_EVENT_NAMES | FAST_FOREGROUND_EVENT_NAMES
    )
    names = [event["event_name"] for event in events]
    assert set(names) <= canonical
    assert len([name for name in names if name == "TURN_INGRESS_COMMITTED"]) == 1
    assert len([name for name in names if name == "ROUTER_DECISION_EMITTED"]) == 1
    assert not {
        "route.enforced.proposed",
        "route.enforced.completed",
        "slowtask.start.signal",
        "patch.signal",
    } & set(names)
    assert [event["event_seq"] for event in events] == list(range(1, len(events) + 1))
    first = run_replay_fixture(replay_fixture(events))
    second = run_replay_fixture(replay_fixture(events))
    assert first.state_digest == second.state_digest
    assert first.ordered_events == second.ordered_events
    assert by_type(sink.json_messages, "control.state")


def test_metadata_journal_and_timeline_exclude_voice_text_candidate_and_raw_inputs() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider([FakeShadowScript(proposal_frame=proposal_frame())])
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            timeline = json.dumps(list(coordinator.metadata_timeline), sort_keys=True)
            journal = json.dumps(coordinator.journal.events(), sort_keys=True)
            for serialized in (timeline, journal):
                lowered = serialized.lower()
                for forbidden in (
                    "control-candidate-sentinel",
                    "synthetic fast reply",
                    "[synthetic] hello assistant",
                    "function_arguments",
                    "provider_payload",
                    "raw_audio",
                    "authorization",
                    "api_key",
                    "bearer ",
                ):
                    assert forbidden not in lowered
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize("failure_type", ("provider.error", "provider.disconnected"))
def test_slice3a1_voice_failure_owns_the_only_terminal_before_late_spawn(
    failure_type: str,
) -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
            reply_candidate_text=None,
        )
        control = BlockingFirstControlProvider(
            [FakeShadowScript(proposal_frame=spawn)]
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(control.first_started.wait(), timeout=2)
            turn_id = str(
                journal_events(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"]
            )
            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type=failure_type,
                    output_mode="degraded",
                    error_code="synthetic_voice_failure",
                    terminal=failure_type == "provider.disconnected",
                )
            )
            control.release_first.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert_turn_has_unique_terminal_authority(coordinator, sink, turn_id)
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
            assert not by_type(sink.json_messages, "slowtask.state")
            assert sink.binary_messages == []
        finally:
            control.release_first.set()
            await coordinator.close()

    run(scenario())


def test_slice3a1_fail_closed_terminal_discards_late_patch_without_advancing_task() -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        patch = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            complexity_hint="MEDIUM",
            reply_candidate_text=None,
        )
        control = BlockingNthControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=patch),
            ],
            block_index=2,
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            task = coordinator.state.active_task
            assert task is not None
            task_id = task.task_id
            plan_version = task.plan_version
            patch_count = len(journal_events(coordinator, "USER_PATCH_RECEIVED"))

            await voice.trigger_scenario("patch")
            await asyncio.wait_for(control.block_started.wait(), timeout=2)
            turn_id = str(
                journal_events(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"]
            )
            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type="provider.error",
                    output_mode="degraded",
                    error_code="synthetic_voice_failure",
                )
            )
            control.release.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert_turn_has_unique_terminal_authority(coordinator, sink, turn_id)
            assert len(journal_events(coordinator, "USER_PATCH_RECEIVED")) == patch_count
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.task_id == task_id
            assert coordinator.state.active_task.plan_version == plan_version
            assert sink.binary_messages == []
        finally:
            control.release.set()
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize("route_kind", ("spawn", "patch"))
def test_slice3a1_candidate_absent_uses_local_template_and_worker_survives(
    route_kind: str,
) -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
            reply_candidate_text=None,
        )
        patch = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            complexity_hint="MEDIUM",
            reply_candidate_text=None,
        )
        scripts = [FakeShadowScript(proposal_frame=spawn)]
        if route_kind == "patch":
            scripts.append(FakeShadowScript(proposal_frame=patch))
        scripts.append(FakeShadowScript(proposal_frame=proposal_frame()))
        control = RecordingControlProvider(scripts)
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            first_assistant = by_type(
                sink.json_messages, "transcript.assistant.done"
            )[-1]
            assert_server_committed_template(first_assistant, "ACK_SLOW")
            if route_kind == "patch":
                await voice.trigger_scenario("patch")
                await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
                patch_assistant = by_type(
                    sink.json_messages, "transcript.assistant.done"
                )[-1]
                assert_server_committed_template(patch_assistant, "ACK_PATCH")

            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert by_type(sink.json_messages, "dispatch.result")[-1][
                "actual_dispatch"
            ] == "clarify"
            assert_server_committed_template(
                by_type(sink.json_messages, "transcript.assistant.done")[-1],
                "CLARIFY",
            )
            assert coordinator._shadow_worker_task is not None
            assert not coordinator._shadow_worker_task.done()
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a1_worker_normalizes_one_handler_exception_and_processes_next_turn() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider(
            [
                FakeShadowScript(proposal_frame=proposal_frame()),
                FakeShadowScript(proposal_frame=proposal_frame()),
            ]
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        original = coordinator._consume_enforced_result
        calls = 0

        async def explode_once(envelope, result) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("PRIVATE_HANDLER_EXCEPTION_SENTINEL")
            await original(envelope, result)

        coordinator._consume_enforced_result = explode_once  # type: ignore[method-assign]
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert calls == 2
            assert coordinator._shadow_worker_task is not None
            assert not coordinator._shadow_worker_task.done()
            assert by_type(sink.json_messages, "dispatch.result")[-1][
                "actual_dispatch"
            ] == "clarify"
            serialized = json.dumps(sink.json_messages, sort_keys=True)
            assert "PRIVATE_HANDLER_EXCEPTION_SENTINEL" not in serialized
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    ("confirmation_signal", "voice_scenario", "expected_event", "cancelled"),
    (
        ("ACCEPT", "confirm", "CONFIRMATION_ACCEPTED", True),
        ("REJECT", "reject_confirmation", "CONFIRMATION_REJECTED", False),
    ),
)
def test_slice3a1_pending_confirmation_requires_explicit_bound_signal(
    confirmation_signal: str,
    voice_scenario: str,
    expected_event: str,
    cancelled: bool,
) -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        cancel = proposal_frame(
            task_focus_hint="CANCEL_OR_PAUSE_CANDIDATE",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="CLARIFY",
            task_like=True,
            confirmation_signal_hint="NOT_APPLICABLE",
        )
        confirm = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            confirmation_signal_hint=confirmation_signal,
            reply_candidate_text=None,
        )
        control = RecordingControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=cancel),
                FakeShadowScript(proposal_frame=confirm),
            ]
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            await voice.trigger_scenario("cancel")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            task = coordinator.state.active_task
            assert task is not None
            confirmation_id = task.pending_confirmation_id
            assert confirmation_id

            await voice.trigger_scenario(voice_scenario)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert len(journal_events(coordinator, expected_event)) == 1
            opposite = (
                "CONFIRMATION_REJECTED"
                if expected_event == "CONFIRMATION_ACCEPTED"
                else "CONFIRMATION_ACCEPTED"
            )
            assert not journal_events(coordinator, opposite)
            assert bool(journal_events(coordinator, "SLOWTASK_CANCELLED")) is cancelled
            assert coordinator.state.active_task is not None
            assert (
                coordinator.state.active_task.terminal_status == "CANCELLED"
            ) is cancelled
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    ("final_script", "voice_scenario"),
    (
        (
            FakeShadowScript(
                proposal_frame=proposal_frame(
                    task_focus_hint="AMBIGUOUS",
                    route_decision_hint="FAST_ONLY",
                    foreground_act="CLARIFY",
                    confidence=0.5,
                    confirmation_signal_hint="AMBIGUOUS",
                    reply_candidate_text=None,
                )
            ),
            "ambiguous",
        ),
        (
            FakeShadowScript(
                proposal_frame=proposal_frame(
                    task_focus_hint="NON_ASSISTANT",
                    route_decision_hint="IGNORE",
                    foreground_act="SILENCE",
                    confidence=0.99,
                    confirmation_signal_hint="ACCEPT",
                    reply_candidate_text=None,
                )
            ),
            "ignore",
        ),
        (
            FakeShadowScript(
                proposal_frame=proposal_frame(
                    task_focus_hint="ACTIVE_TASK_PATCH",
                    route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
                    foreground_act="ACK_PATCH",
                    confirmation_signal_hint="NOT_APPLICABLE",
                    reply_candidate_text=None,
                )
            ),
            "patch",
        ),
        (FakeShadowScript(scenario="provider_error"), "confirm"),
        (FakeShadowScript(scenario="timeout"), "confirm"),
    ),
)
def test_slice3a1_nonexplicit_confirmation_never_resolves_or_cancels(
    final_script: FakeShadowScript,
    voice_scenario: str,
) -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        cancel = proposal_frame(
            task_focus_hint="CANCEL_OR_PAUSE_CANDIDATE",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="CLARIFY",
            task_like=True,
            confirmation_signal_hint="NOT_APPLICABLE",
        )
        control = RecordingControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=cancel),
                final_script,
            ]
        )
        coordinator, voice, sink = await make_enforced_coordinator(
            control,
            config=CoordinatorConfig(shadow_request_timeout_seconds=0.02),
        )
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            await voice.trigger_scenario("cancel")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            task = coordinator.state.active_task
            assert task is not None
            confirmation_id = task.pending_confirmation_id
            confirmation_scope = task.pending_confirmation_scope
            assert confirmation_id and confirmation_scope

            await voice.trigger_scenario(voice_scenario)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert not journal_events(coordinator, "CONFIRMATION_ACCEPTED")
            assert not journal_events(coordinator, "CONFIRMATION_REJECTED")
            assert not journal_events(coordinator, "SLOWTASK_CANCELLED")
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.pending_confirmation_id == confirmation_id
            assert (
                coordinator.state.active_task.pending_confirmation_scope
                == confirmation_scope
            )
            if voice_scenario == "ignore":
                current_turn = journal_events(
                    coordinator, "TURN_INGRESS_COMMITTED"
                )[-1]["turn_id"]
                assert not [
                    message
                    for message in by_type(
                        sink.json_messages, "transcript.assistant.done"
                    )
                    if message.get("turn_id") == current_turn
                ]
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    "mutation",
    ("confirmation_id", "confirmation_scope", "plan_version"),
)
def test_slice3a1_explicit_confirmation_fails_closed_when_binding_is_stale(
    mutation: str,
) -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        cancel = proposal_frame(
            task_focus_hint="CANCEL_OR_PAUSE_CANDIDATE",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="CLARIFY",
            task_like=True,
            confirmation_signal_hint="NOT_APPLICABLE",
        )
        accept = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            confirmation_signal_hint="ACCEPT",
            reply_candidate_text=None,
        )
        control = BlockingNthControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=cancel),
                FakeShadowScript(proposal_frame=accept),
            ],
            block_index=3,
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            await voice.trigger_scenario("cancel")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            task = coordinator.state.active_task
            assert task is not None

            await voice.trigger_scenario("confirm")
            await asyncio.wait_for(control.block_started.wait(), timeout=2)
            before_patches = len(journal_events(coordinator, "USER_PATCH_RECEIVED"))
            if mutation == "confirmation_id":
                task.pending_confirmation_id = "confirmation_replacement"
            elif mutation == "confirmation_scope":
                task.pending_confirmation_scope = "DESTRUCTIVE_TOOL_EXECUTION"
            else:
                task.plan_version += 1
                task.task_event_seq += 1
            expected_id = task.pending_confirmation_id
            expected_scope = task.pending_confirmation_scope
            expected_version = task.plan_version
            control.release.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert not journal_events(coordinator, "CONFIRMATION_ACCEPTED")
            assert not journal_events(coordinator, "CONFIRMATION_REJECTED")
            assert not journal_events(coordinator, "SLOWTASK_CANCELLED")
            assert len(journal_events(coordinator, "USER_PATCH_RECEIVED")) == before_patches
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.pending_confirmation_id == expected_id
            assert coordinator.state.active_task.pending_confirmation_scope == expected_scope
            assert coordinator.state.active_task.plan_version == expected_version
            assert by_type(sink.json_messages, "dispatch.result")[-1][
                "actual_dispatch"
            ] == "degraded"
            assert sink.binary_messages == []
        finally:
            control.release.set()
            await coordinator.close()

    run(scenario())


def test_slice3a1_inflight_patch_cannot_rebase_onto_replacement_task_identity() -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
        )
        patch = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            complexity_hint="MEDIUM",
            reply_candidate_text="OLD-TASK-PATCH-CANDIDATE",
        )
        control = BlockingNthControlProvider(
            [
                FakeShadowScript(proposal_frame=spawn),
                FakeShadowScript(proposal_frame=patch),
            ],
            block_index=2,
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            await voice.trigger_scenario("patch")
            await asyncio.wait_for(control.block_started.wait(), timeout=2)
            existing = coordinator.state.active_task
            assert existing is not None
            coordinator.state.active_task = ActiveSlowTaskState(
                task_id="task_replacement_identity",
                lifecycle="CREATED",
                plan_version=1,
                task_event_seq=1,
            )
            patch_count = len(journal_events(coordinator, "USER_PATCH_RECEIVED"))
            control.release.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert len(journal_events(coordinator, "USER_PATCH_RECEIVED")) == patch_count
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.task_id == "task_replacement_identity"
            assert coordinator.state.active_task.plan_version == 1
            assert "OLD-TASK-PATCH-CANDIDATE" not in json.dumps(
                sink.json_messages, sort_keys=True
            )
            assert sink.binary_messages == []
        finally:
            control.release.set()
            await coordinator.close()

    run(scenario())


def test_slice3a1_superseded_queue_drop_and_late_result_have_zero_visible_output() -> None:
    async def scenario() -> None:
        controls = [
            FakeShadowScript(
                proposal_frame=proposal_frame(reply_candidate_text="STALE-TURN-ONE")
            ),
            FakeShadowScript(
                proposal_frame=proposal_frame(reply_candidate_text="CURRENT-TURN-THREE")
            ),
        ]
        control = BlockingFirstControlProvider(controls)
        coordinator, voice, sink = await make_enforced_coordinator(
            control,
            config=CoordinatorConfig(
                max_shadow_request_queue=1,
                shadow_request_timeout_seconds=1.0,
            ),
            voice_config=FakeProviderConfig(event_delay_seconds=0),
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(control.first_started.wait(), timeout=2)
            await voice.trigger_scenario("fast")
            await voice.trigger_scenario("fast")
            committed = journal_events(coordinator, "TURN_INGRESS_COMMITTED")
            assert len(committed) == 3
            current_turn_id = str(committed[-1]["turn_id"])
            control.release_first.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assistants = by_type(sink.json_messages, "transcript.assistant.done")
            assert assistants
            assert {message.get("turn_id") for message in assistants} == {
                current_turn_id
            }
            assert assistants[-1]["text"] != "CURRENT-TURN-THREE"
            assert assistants[-1]["source"] == "controlled_template"
            assert assistants[-1]["foreground_act"] == "CLARIFY"
            serialized = json.dumps(assistants, sort_keys=True)
            assert "STALE-TURN-ONE" not in serialized
            assert sink.binary_messages == []
        finally:
            control.release_first.set()
            await coordinator.close()

    run(scenario())


def test_slice3a1_slow_control_cancel_never_holds_mutation_lock_or_reorders_journal() -> None:
    async def scenario() -> None:
        control = SlowCancelControlProvider(
            [FakeShadowScript(proposal_frame=proposal_frame())]
        )
        coordinator, voice, _sink = await make_enforced_coordinator(control)
        speech_task: asyncio.Task[None] | None = None
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(control.first_started.wait(), timeout=2)
            control.cancel_should_block = True
            speech_task = asyncio.create_task(
                coordinator.handle_provider_event(
                    voice_input_event(
                        "speech.started",
                        item="voice-input-slow-cancel",
                        turn="voice-turn-slow-cancel",
                        utterance="voice-utterance-slow-cancel",
                        span="voice-audio-span-slow-cancel",
                        start_ms=500,
                    )
                )
            )
            await asyncio.wait_for(control.cancel_started.wait(), timeout=2)

            # The generation fence and speech ingress must not wait for a slow
            # provider network cancellation while holding coordinator state.
            await asyncio.wait_for(asyncio.shield(speech_task), timeout=0.2)
            await asyncio.wait_for(
                coordinator.handle_provider_event(
                    FakeProviderEvent(type="session.updated", output_mode="mock")
                ),
                timeout=0.2,
            )
            seqs = [event["event_seq"] for event in coordinator.journal.events()]
            assert seqs == list(range(1, len(seqs) + 1))
        finally:
            control.release_cancel.set()
            control.release_first.set()
            if speech_task is not None:
                await asyncio.gather(speech_task, return_exceptions=True)
            await coordinator.close()

    run(scenario())


def test_slice3a1_coordinator_routes_one_exactly_bound_asr_final_only_once() -> None:
    async def scenario() -> None:
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=proposal_frame())]
        )
        coordinator, _voice, sink = await make_enforced_coordinator(control)
        item = "voice-input-opaque-0001"
        try:
            await coordinator.handle_provider_event(
                voice_input_event(
                    "speech.started",
                    item=item,
                    turn="voice-turn-0001",
                    utterance="voice-utterance-0001",
                    span="voice-audio-span-0001",
                    start_ms=10,
                )
            )
            await coordinator.handle_provider_event(
                voice_input_event(
                    "speech.stopped",
                    item=item,
                    turn="voice-turn-0001",
                    utterance="voice-utterance-0001",
                    span="voice-audio-span-0001",
                    start_ms=10,
                    end_ms=170,
                )
            )
            final = voice_input_event(
                "user.transcript.final",
                item=item,
                turn="voice-turn-0001",
                utterance="voice-utterance-0001",
                span="voice-audio-span-0001",
                text="PRIVATE_EXACT_BOUND_FINAL",
                start_ms=10,
                end_ms=170,
            )
            await coordinator.handle_provider_event(final)
            await coordinator.handle_provider_event(final)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert len(control.requests) == 1
            assert len(journal_events(coordinator, "ASR_TRANSCRIPT_OUTPUT_EMITTED")) == 1
            assert len(journal_events(coordinator, "ROUTER_DECISION_EMITTED")) == 1
            assert len(by_type(sink.json_messages, "dispatch.result")) == 1
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    "invalid_final",
    (
        voice_input_event(
            "user.transcript.final",
            item=None,
            turn="voice-turn-0001",
            utterance="voice-utterance-0001",
            span="voice-audio-span-0001",
            text="PRIVATE_MISSING_ITEM_COORDINATOR_FINAL",
            correlation_valid=False,
            error_code="voice_input_item_missing",
        ),
        voice_input_event(
            "user.transcript.final",
            item="voice-input-opaque-old",
            turn="voice-turn-old",
            utterance="voice-utterance-old",
            span="voice-audio-span-old",
            text="PRIVATE_OLD_ITEM_COORDINATOR_FINAL",
            correlation_valid=False,
            error_code="voice_input_item_unknown_old_or_mismatched",
        ),
    ),
)
def test_slice3a1_invalid_asr_final_never_binds_current_turn_or_control_request(
    invalid_final: VoiceProviderEvent,
) -> None:
    async def scenario() -> None:
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=proposal_frame())]
        )
        coordinator, _voice, sink = await make_enforced_coordinator(control)
        current_item = "voice-input-opaque-current"
        try:
            await coordinator.handle_provider_event(
                voice_input_event(
                    "speech.started",
                    item=current_item,
                    turn="voice-turn-current",
                    utterance="voice-utterance-current",
                    span="voice-audio-span-current",
                    start_ms=200,
                )
            )
            await coordinator.handle_provider_event(
                voice_input_event(
                    "speech.stopped",
                    item=current_item,
                    turn="voice-turn-current",
                    utterance="voice-utterance-current",
                    span="voice-audio-span-current",
                    start_ms=200,
                    end_ms=360,
                )
            )
            await coordinator.handle_provider_event(invalid_final)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert control.requests == []
            assert not journal_events(coordinator, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
            assert len(journal_events(coordinator, "ROUTER_DECISION_EMITTED")) <= 1
            serialized = json.dumps(
                {
                    "timeline": list(coordinator.metadata_timeline),
                    "journal": coordinator.journal.events(),
                },
                sort_keys=True,
            )
            assert "PRIVATE_MISSING_ITEM_COORDINATOR_FINAL" not in serialized
            assert "PRIVATE_OLD_ITEM_COORDINATOR_FINAL" not in serialized
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    "phase",
    ("post_fast", "post_router", "route_json", "post_gate", "timeline"),
)
def test_slice3a11_phase_faults_have_one_terminal_chain_and_no_duplicate_mutation(
    phase: str,
) -> None:
    async def scenario() -> None:
        frame = proposal_frame(
            reply_candidate_text=(None if phase == "post_router" else "FAULT-CANDIDATE")
        )
        sink = (
            FaultOnceBrowserSink(
                {
                    "route_json": "route.decided",
                    "post_gate": "gate.result",
                    "timeline": "timeline.metadata",
                }[phase],
                armed=phase != "timeline",
            )
            if phase in {"route_json", "post_gate", "timeline"}
            else MemoryBrowserSink()
        )
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=frame)]
        )
        coordinator, voice, _ = await make_enforced_coordinator(
            control, browser_sink=sink
        )
        try:
            if phase == "timeline":
                sink.armed = True
            if phase == "post_fast":
                original = coordinator._router.emit_decision
                injected = False

                def fail_once_after_fast(*args: Any, **kwargs: Any):
                    nonlocal injected
                    if not injected:
                        injected = True
                        raise RuntimeError("PRIVATE_POST_FAST_FAULT_SENTINEL")
                    return original(*args, **kwargs)

                coordinator._router.emit_decision = fail_once_after_fast  # type: ignore[method-assign]
            elif phase == "post_router":
                original_gate_failure = coordinator._append_enforced_gate_failure
                injected = False

                def fail_once_after_router(*args: Any, **kwargs: Any):
                    nonlocal injected
                    if not injected:
                        injected = True
                        raise RuntimeError("PRIVATE_POST_ROUTER_FAULT_SENTINEL")
                    return original_gate_failure(*args, **kwargs)

                coordinator._append_enforced_gate_failure = fail_once_after_router  # type: ignore[method-assign]

            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            turn_id = str(journal_events(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"])

            assert_turn_has_unique_terminal_authority(coordinator, sink, turn_id)
            assert not journal_events(coordinator, "SLOWTASK_CREATED")
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
            assert sink.binary_messages == []
            assert "PRIVATE_" not in json.dumps(sink.json_messages, sort_keys=True)
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    ("operation", "raise_after_delegate"),
    (
        ("spawn", False),
        ("spawn", True),
        ("patch", False),
        ("patch", True),
    ),
)
def test_slice3a11_spawn_and_patch_faults_never_duplicate_task_mutation(
    operation: str, raise_after_delegate: bool
) -> None:
    async def scenario() -> None:
        spawn = proposal_frame(
            task_focus_hint="NEW_TASK_CANDIDATE",
            route_decision_hint="SPAWN_SLOW_TASK",
            foreground_act="ACK_SLOW",
            task_like=True,
            complexity_hint="HIGH",
            reply_candidate_text=None,
        )
        patch = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            complexity_hint="MEDIUM",
            reply_candidate_text=None,
        )
        scripts = [FakeShadowScript(proposal_frame=spawn)]
        if operation == "patch":
            scripts.append(FakeShadowScript(proposal_frame=patch))
        control = RecordingControlProvider(scripts)
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            if operation == "patch":
                await voice.trigger_scenario("spawn")
                await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
                assert coordinator.state.active_task is not None

            method_name = f"_{'spawn_slow_task' if operation == 'spawn' else 'apply_user_patch'}"
            original = getattr(coordinator, method_name)

            async def injected_fault(*args: Any, **kwargs: Any) -> None:
                if raise_after_delegate:
                    await original(*args, **kwargs)
                raise RuntimeError(f"PRIVATE_{operation.upper()}_FAULT_SENTINEL")

            setattr(coordinator, method_name, injected_fault)
            before_turns = len(journal_events(coordinator, "TURN_INGRESS_COMMITTED"))
            mutation_name = (
                "SLOWTASK_CREATED" if operation == "spawn" else "USER_PATCH_RECEIVED"
            )
            before_mutations = len(journal_events(coordinator, mutation_name))
            await voice.trigger_scenario(operation)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            turn = journal_events(coordinator, "TURN_INGRESS_COMMITTED")[before_turns]

            assert_turn_has_unique_terminal_authority(
                coordinator, sink, str(turn["turn_id"])
            )
            mutation_delta = (
                len(journal_events(coordinator, mutation_name)) - before_mutations
            )
            assert mutation_delta == int(raise_after_delegate)
            assert sink.binary_messages == []
            assert "PRIVATE_" not in json.dumps(sink.json_messages, sort_keys=True)
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize("confirmation_signal", ("ACCEPT", "REJECT"))
def test_slice3a11_orphan_confirmation_signal_has_zero_task_mutation(
    confirmation_signal: str,
) -> None:
    async def scenario() -> None:
        orphan = proposal_frame(
            task_focus_hint="ACTIVE_TASK_PATCH",
            route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
            foreground_act="ACK_PATCH",
            task_like=True,
            confirmation_signal_hint=confirmation_signal,
            reply_candidate_text=None,
        )
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=orphan)]
        )
        coordinator, voice, sink = await make_enforced_coordinator(control)
        try:
            await voice.trigger_scenario(
                "confirm" if confirmation_signal == "ACCEPT" else "reject_confirmation"
            )
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert coordinator.state.active_task is None
            assert not journal_events(coordinator, "USER_PATCH_RECEIVED")
            assert not journal_events(coordinator, "PLAN_VERSION_ADVANCED")
            assert not journal_events(coordinator, "CONFIRMATION_ACCEPTED")
            assert not journal_events(coordinator, "CONFIRMATION_REJECTED")
            assert not journal_events(coordinator, "SLOWTASK_CANCELLED")
            turn_id = str(journal_events(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"])
            assert_turn_has_unique_terminal_authority(coordinator, sink, turn_id)
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a11_long_session_bounds_correlations_and_never_rebinds_evicted_ids() -> None:
    async def scenario() -> None:
        limit = 4
        turns = 300
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=proposal_frame()) for _ in range(turns)]
        )
        coordinator, voice, sink = await make_enforced_coordinator(
            control,
            config=CoordinatorConfig(
                max_correlation_tombstones=limit,
                max_metadata_timeline_entries=32,
            ),
            voice_config=FakeProviderConfig(
                response_audio_chunks=1, event_delay_seconds=0
            ),
        )
        try:
            for _ in range(turns):
                await voice.trigger_scenario("fast")
                await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            dispatch_count = len(by_type(sink.json_messages, "dispatch.result"))
            router_count = len(journal_events(coordinator, "ROUTER_DECISION_EMITTED"))
            assert dispatch_count == turns
            assert router_count == turns
            assert len(coordinator._enforced_terminal_turn_ids) <= limit
            assert len(coordinator._voice_response_tombstones) <= limit
            assert len(coordinator._voice_input_item_tombstones) <= limit
            assert len(coordinator._voice_response_lifecycles) == 0
            assert len(coordinator._voice_response_epochs) == 0
            assert len(coordinator._voice_input_item_turns) == 0

            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type="response.done",
                    output_mode="mock",
                    response_id="provider-response-0001",
                    status="cancelled",
                )
            )
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert len(by_type(sink.json_messages, "dispatch.result")) == dispatch_count
            assert len(journal_events(coordinator, "ROUTER_DECISION_EMITTED")) == router_count
            assert coordinator._voice_active_response_id is None
            assert coordinator.state.active_task is None
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize("rebuild_success", (True, False))
def test_slice3a11_invalid_response_created_coalesces_voice_rebuild_and_bounds_pcm_drop(
    rebuild_success: bool,
) -> None:
    async def scenario() -> None:
        voice = BlockingRebuildVoiceProvider(rebuild_success=rebuild_success)
        control = RecordingControlProvider(
            [FakeShadowScript(proposal_frame=proposal_frame())]
        )
        config = CoordinatorConfig(max_input_queue_frames=3)
        coordinator, _voice, sink = await make_enforced_coordinator(
            control, config=config, voice_provider=voice
        )
        invalid = VoiceProviderEvent(
            type="response.created",
            output_mode="degraded",
            response_id=None,
            correlation_valid=False,
            error_code="voice_response_correlation_incomplete",
        )
        try:
            await coordinator.handle_provider_event(invalid)
            await asyncio.wait_for(voice.rebuild_started.wait(), timeout=1)
            await asyncio.gather(
                coordinator.handle_provider_event(invalid),
                coordinator.handle_provider_event(invalid),
            )
            assert voice.rebuild_calls == 1

            pcm = b"\x01\x00" * 160
            for _ in range(config.max_input_queue_frames + 2):
                await coordinator.submit_audio(pcm)
            await asyncio.sleep(0)
            assert voice.sent_audio_frames == 0
            assert 1 <= coordinator.state.voice_rebuild_pcm_drop_count <= (
                config.max_input_queue_frames + 2
            )
            assert coordinator.input_queue_depth <= config.max_input_queue_frames

            voice.release_rebuild.set()
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert voice.rebuild_calls == 1
            assert coordinator.state.voice_context_tainted is (not rebuild_success)
            assert coordinator.state.voice_session_status == (
                "connected" if rebuild_success else "degraded"
            )
            assert coordinator.state.voice_context_rebuild_count == int(rebuild_success)
            assert coordinator.state.shadow_control_session_status == "connected"
            assert coordinator._shadow_worker_task is not None
            assert coordinator._shadow_worker_task.done() is False

            if rebuild_success:
                await voice.trigger_scenario("fast")
                await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
                assert by_type(sink.json_messages, "dispatch.result")[-1][
                    "actual_dispatch"
                ] == "clarify"
        finally:
            voice.release_rebuild.set()
            await coordinator.close()

    run(scenario())
