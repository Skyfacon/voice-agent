from __future__ import annotations

import asyncio
import json
from collections import Counter
from copy import deepcopy
from typing import Any, Mapping

import pytest

from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeRealtimeProvider,
)
from experiments.qwen_realtime_fast_slow_web.capability_profile import (
    fake_capability_profile,
)
from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (
    VoiceProviderEvent,
    VoiceSuppressionCounters,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    SCHEMA_VERSION,
    FakeShadowControlProvider,
    FakeShadowScript,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
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


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


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
        "confidence": 0.99,
        "reply_candidate_text": "PROVIDER-CANDIDATE-MUST-STAY-QUARANTINED",
    }
    frame.update(overrides)
    return frame


def spawn_frame(*, candidate: str | None = None) -> dict[str, object]:
    return proposal_frame(
        task_focus_hint="NEW_TASK_CANDIDATE",
        route_decision_hint="SPAWN_SLOW_TASK",
        foreground_act="ACK_SLOW",
        task_like=True,
        complexity_hint="HIGH",
        reply_candidate_text=candidate,
    )


def patch_frame(*, candidate: str | None = None) -> dict[str, object]:
    return proposal_frame(
        task_focus_hint="ACTIVE_TASK_PATCH",
        route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
        foreground_act="ACK_PATCH",
        task_like=True,
        complexity_hint="MEDIUM",
        reply_candidate_text=candidate,
    )


class FaultBrowserSink:
    """Browser sink that can fail before or ambiguously after one JSON send."""

    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.ambiguous_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []
        self._fault_type: str | None = None
        self._fault_phase = "before"
        self._armed = False
        self.failure_count = 0

    def arm(self, message_type: str, *, phase: str) -> None:
        if phase not in {"before", "during", "after"}:
            raise ValueError("fault phase must be before, during, or after")
        self._fault_type = message_type
        self._fault_phase = phase
        self._armed = True
        self.failure_count = 0

    async def send_json(self, data: Mapping[str, Any]) -> None:
        copied = deepcopy(dict(data))
        should_fail = bool(
            self._armed
            and self.failure_count == 0
            and copied.get("type") == self._fault_type
        )
        if should_fail and self._fault_phase == "before":
            self.failure_count += 1
            raise RuntimeError("PRIVATE_SLICE3A12_BROWSER_FAULT")
        if should_fail and self._fault_phase == "during":
            # The coordinator cannot know whether a transport/parser failure
            # exposed this semantic envelope.  Track it as potentially visible
            # and require recovery to preserve its identity and meaning.
            self.ambiguous_messages.append(copied)
            self.failure_count += 1
            raise RuntimeError("PRIVATE_SLICE3A12_BROWSER_FAULT")
        self.json_messages.append(copied)
        if should_fail:
            self.failure_count += 1
            raise RuntimeError("PRIVATE_SLICE3A12_BROWSER_FAULT")

    async def send_bytes(self, data: bytes) -> None:
        self.binary_messages.append(bytes(data))

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class GenerationWatchdogProvider:
    """Small provider-free Voice lifecycle fixture with explicit generations."""

    def __init__(self) -> None:
        self.profile = fake_capability_profile()
        self.counters = VoiceSuppressionCounters()
        self.ingress_generation = 1
        self.session_generation = 1
        self.rebuild_calls = 0
        self.sent_audio_frames = 0
        self.recv_generations: list[int] = []
        self._events: asyncio.Queue[VoiceProviderEvent] = asyncio.Queue()
        self._closed = False

    async def connect(self) -> None:
        for event_type in ("session.created", "session.updated"):
            await self._events.put(
                VoiceProviderEvent(
                    type=event_type,
                    output_mode="mock",
                    session_ref="voice-session-generation-0001",
                    session_generation=self.session_generation,
                )
            )

    async def recv_event(self, *, receiver_generation: int) -> VoiceProviderEvent:
        if receiver_generation != self.session_generation:
            raise RuntimeError("voice_receiver_generation_stale")
        self.recv_generations.append(receiver_generation)
        return await self._events.get()

    async def queue_event(self, event: VoiceProviderEvent) -> None:
        await self._events.put(event)

    def event_processed(self) -> None:
        self._events.task_done()

    async def wait_events_drained(self) -> None:
        await self._events.join()

    async def wait_response_complete(self) -> None:
        return None

    async def send_audio(self, _pcm: bytes, *, ingress_generation: int) -> None:
        if ingress_generation != self.ingress_generation:
            raise RuntimeError("voice_ingress_generation_stale")
        self.sent_audio_frames += 1

    async def cancel_response(self) -> bool:
        self.counters.cancel_request_count += 1
        return True

    async def wait_for_cancel_terminal(
        self, _response_id: str, *, timeout_seconds: float
    ) -> bool:
        await asyncio.sleep(min(timeout_seconds, 0.001))
        self.counters.cancel_terminal_timeout_count += 1
        return False

    async def rebuild_if_tainted(self) -> bool:
        self.rebuild_calls += 1
        self.ingress_generation += 1
        self.session_generation += 1
        return True

    async def close(self) -> None:
        self._closed = True


async def make_coordinator(
    scripts: list[FakeShadowScript],
    *,
    sink: FaultBrowserSink | None = None,
    session_suffix: str = "authority",
    config: CoordinatorConfig | None = None,
) -> tuple[RealtimeSessionCoordinator, FakeRealtimeProvider, FaultBrowserSink]:
    browser = sink or FaultBrowserSink()
    voice = FakeRealtimeProvider(
        FakeProviderConfig(response_audio_chunks=1, event_delay_seconds=0)
    )
    coordinator = RealtimeSessionCoordinator(
        browser,
        voice,
        shadow_provider=FakeShadowControlProvider(scripts),
        provider_mode="qwen",
        routing_mode="enforced",
        audio_output="none",
        shadow_control_mode="dual_session",
        config=config,
        session_id=f"session_qfs_slice3a12_{session_suffix}",
        conversation_id=f"conversation_qfs_slice3a12_{session_suffix}",
    )
    await coordinator.start()
    await asyncio.sleep(0)
    return coordinator, voice, browser


def by_type(messages: list[dict[str, Any]], message_type: str) -> list[dict[str, Any]]:
    return [message for message in messages if message.get("type") == message_type]


def events_named(
    coordinator: RealtimeSessionCoordinator, event_name: str
) -> list[dict[str, Any]]:
    return [
        event
        for event in coordinator.journal.events()
        if event.get("event_name") == event_name
    ]


def replay_fixture(events: list[dict[str, Any]], *, suffix: str) -> dict[str, Any]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": f"replay_qfs_slice3a12_{suffix}",
            "source_trace_ref": f"fixture://qfs/slice3a12/{suffix}",
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


def assistant_messages_for_turn(
    sink: FaultBrowserSink, turn_id: str
) -> list[dict[str, Any]]:
    return [
        message
        for message in sink.json_messages + sink.ambiguous_messages
        if message.get("type")
        in {"transcript.assistant.delta", "transcript.assistant.done"}
        and message.get("turn_id") == turn_id
    ]


def assert_at_most_one_visible_semantic_reply(
    sink: FaultBrowserSink, turn_id: str
) -> None:
    visible = assistant_messages_for_turn(sink, turn_id)
    response_ids = {str(message.get("response_id")) for message in visible}
    acts = {str(message.get("foreground_act")) for message in visible}
    assert len(response_ids) <= 1
    assert len(acts) <= 1
    done_by_response = Counter(
        str(message.get("response_id"))
        for message in visible
        if message.get("type") == "transcript.assistant.done"
    )
    assert all(count <= 1 for count in done_by_response.values())
    if any(message.get("foreground_act") != "CLARIFY" for message in visible):
        assert not any(
            message.get("foreground_act") == "CLARIFY" for message in visible
        )


def assert_one_authority_chain(
    coordinator: RealtimeSessionCoordinator, turn_id: str
) -> None:
    routers = [
        event
        for event in events_named(coordinator, "ROUTER_DECISION_EMITTED")
        if event.get("turn_id") == turn_id
    ]
    assert len(routers) == 1
    router_id = str(routers[0]["event_id"])
    gates = [
        event
        for event in coordinator.journal.events()
        if event.get("event_name")
        in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}
        and event.get("router_decision_event_id") == router_id
    ]
    assert len(gates) <= 1
    committed = [
        event
        for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
        if event.get("turn_id") == turn_id
    ]
    assert len(committed) <= 1
    discarded = [
        event
        for event in events_named(coordinator, "FOREGROUND_OUTPUT_DISCARDED")
        if event.get("router_decision_event_id") == router_id
    ]
    assert len(discarded) <= 1


ARBITRARY_PROVIDER_CLAIMS = (
    "I have cancelled your active task.",
    "Your reservation has been finalized for tomorrow.",
    "The note is already on its way to the client.",
    "The current plan has been replaced with the new one.",
    "Take 10mg twice daily.",
    "I authorized the tool execution.",
    "The transfer of one hundred dollars is complete.",
    "已为你取消当前任务。",
    "已经替你转账100元。",
    "酒店房间已经预订成功。",
    "邮件我刚刚发给客户了。",
    "旧数据已经全部删除。",
)


@pytest.mark.parametrize("candidate_text", ARBITRARY_PROVIDER_CLAIMS)
def test_slice3a12_arbitrary_provider_candidate_is_policy_quarantined(
    candidate_text: str,
) -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [
                FakeShadowScript(
                    proposal_frame=proposal_frame(
                        risk_class="LOW",
                        risk_tags=["none"],
                        confidence=0.999,
                        reply_candidate_text=candidate_text,
                    )
                )
            ],
            session_suffix="candidate",
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(events_named(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"])
            assert_one_authority_chain(coordinator, turn_id)
            gates = [
                event
                for event in events_named(coordinator, "FOREGROUND_ACT_GATE_FAILED")
                if event.get("turn_id") == turn_id
                or event.get("router_decision_event_id")
                == events_named(coordinator, "ROUTER_DECISION_EMITTED")[-1]["event_id"]
            ]
            assert len(gates) == 1
            gate = gates[0]
            assert isinstance(gate.get("policy_version"), str) and gate["policy_version"]
            reason = str(gate.get("failure_reason", "")).lower()
            assert any(
                marker in reason
                for marker in ("candidate", "policy", "provider", "quarantin")
            )
            assert not [
                event
                for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
                if event.get("turn_id") == turn_id
                and event.get("output_basis") == "reply_candidate"
            ]
            assert [
                event
                for event in events_named(coordinator, "FOREGROUND_OUTPUT_DISCARDED")
                if event.get("router_decision_event_id")
                == events_named(coordinator, "ROUTER_DECISION_EMITTED")[-1]["event_id"]
            ]
            visible = assistant_messages_for_turn(sink, turn_id)
            assert all(message.get("source") != "control_candidate" for message in visible)
            assert all(message.get("text") != candidate_text for message in visible)
            serialized_authority = json.dumps(
                {
                    "journal": coordinator.journal.events(),
                    "timeline": list(coordinator.metadata_timeline),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            assert candidate_text not in serialized_authority
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize("route_kind", ("fast", "spawn", "patch"))
@pytest.mark.parametrize(
    ("fault_type", "fault_phase"),
    (
        ("transcript.assistant.delta", "before"),
        ("transcript.assistant.delta", "during"),
        ("transcript.assistant.delta", "after"),
        ("transcript.assistant.done", "before"),
        ("transcript.assistant.done", "during"),
        ("transcript.assistant.done", "after"),
        ("dispatch.result", "before"),
        ("dispatch.result", "during"),
        ("dispatch.result", "after"),
        ("timeline.metadata", "before"),
        ("timeline.metadata", "during"),
        ("timeline.metadata", "after"),
    ),
)
def test_slice3a12_visible_delivery_fault_has_one_response_identity_and_semantic(
    route_kind: str,
    fault_type: str,
    fault_phase: str,
) -> None:
    async def scenario() -> None:
        scripts = [FakeShadowScript(proposal_frame=spawn_frame())]
        if route_kind == "patch":
            scripts.append(FakeShadowScript(proposal_frame=patch_frame()))
        elif route_kind == "fast":
            scripts = [FakeShadowScript(proposal_frame=proposal_frame())]
        sink = FaultBrowserSink()
        coordinator, voice, _ = await make_coordinator(
            scripts,
            sink=sink,
            session_suffix=f"delivery_{route_kind}_{fault_type}",
        )
        try:
            if route_kind == "patch":
                await voice.trigger_scenario("spawn")
                await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            before_turns = len(events_named(coordinator, "TURN_INGRESS_COMMITTED"))
            before_created = len(events_named(coordinator, "SLOWTASK_CREATED"))
            before_patches = len(events_named(coordinator, "USER_PATCH_RECEIVED"))
            sink.arm(fault_type, phase=fault_phase)

            await voice.trigger_scenario(route_kind)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn = events_named(coordinator, "TURN_INGRESS_COMMITTED")[before_turns]
            turn_id = str(turn["turn_id"])
            assert sink.failure_count == 1
            assert_one_authority_chain(coordinator, turn_id)
            assert_at_most_one_visible_semantic_reply(sink, turn_id)
            dispatches = [
                message
                for message in by_type(sink.json_messages, "dispatch.result")
                if message.get("turn_id") == turn_id
            ]
            assert len(dispatches) <= 1
            assert len(events_named(coordinator, "SLOWTASK_CREATED")) - before_created <= 1
            assert len(events_named(coordinator, "USER_PATCH_RECEIVED")) - before_patches <= 1
            assert sink.binary_messages == []
            assert "PRIVATE_SLICE3A12_BROWSER_FAULT" not in json.dumps(
                sink.json_messages, sort_keys=True
            )
        finally:
            await coordinator.close()

    run(scenario())


SPAWN_APPEND_BOUNDARIES = (
    ("SLOWTASK_CREATED", 1),
    ("SLOWTASK_STATE_CHANGED", 1),
    ("PLANNING_STARTED", 1),
    ("SLOWTASK_STATE_CHANGED", 2),
)

PATCH_APPEND_BOUNDARIES = (
    ("USER_PATCH_RECEIVED", 1),
    ("USER_PATCH_INTERPRETED", 1),
    ("PLAN_VERSION_ADVANCED", 1),
    ("PLANNING_RESTARTED", 1),
    ("TASK_REPLANNED", 1),
    ("SLOWTASK_STATE_CHANGED", 1),
)


def install_post_append_fault(
    coordinator: RealtimeSessionCoordinator,
    *,
    event_name: str,
    target_delta: int,
) -> None:
    original = coordinator.journal.append
    baseline = len(events_named(coordinator, event_name))
    seen = 0

    def append_then_fail(**kwargs: Any) -> dict[str, Any]:
        nonlocal seen
        event = original(**kwargs)
        if kwargs.get("event_name") == event_name:
            seen += 1
            if seen == target_delta:
                raise RuntimeError("PRIVATE_SLICE3A12_POST_APPEND_FAULT")
        return event

    coordinator.journal.append = append_then_fail  # type: ignore[method-assign]
    assert len(events_named(coordinator, event_name)) == baseline


def assert_runtime_matches_replay(coordinator: RealtimeSessionCoordinator, *, suffix: str) -> None:
    events = coordinator.journal.events()
    fixture = replay_fixture(events, suffix=suffix)
    first = run_replay_fixture(fixture)
    second = run_replay_fixture(fixture)
    assert first.ordered_events == second.ordered_events
    assert first.state_digest == second.state_digest
    runtime = coordinator.state.active_task
    if first.slowtask_state.last_task_id is None:
        assert runtime is None
        return
    task_id = first.slowtask_state.last_task_id
    replayed = first.slowtask_state.tasks[task_id]
    assert runtime is not None
    assert runtime.task_id == task_id
    assert runtime.lifecycle == replayed.lifecycle_state
    assert runtime.plan_version == replayed.current_plan_version
    assert runtime.task_event_seq == replayed.current_task_event_seq
    assert runtime.terminal_status == replayed.terminal_outcome
    assert runtime.pending_confirmation_id == (
        replayed.confirmation_state.pending_confirmation_id
    )
    assert runtime.pending_confirmation_scope == (
        replayed.confirmation_state.confirmation_scope
        if replayed.confirmation_state.pending_confirmation_id is not None
        else None
    )


@pytest.mark.parametrize(
    ("event_name", "target_delta"),
    SPAWN_APPEND_BOUNDARIES,
    ids=(
        "after-created",
        "after-created-state",
        "after-planning-started",
        "after-planning-state",
    ),
)
def test_slice3a12_spawn_post_append_failure_reconciles_runtime_to_replay(
    event_name: str,
    target_delta: int,
) -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [FakeShadowScript(proposal_frame=spawn_frame())],
            session_suffix=f"spawn_fault_{event_name}",
        )
        try:
            install_post_append_fault(
                coordinator, event_name=event_name, target_delta=target_delta
            )
            before_turns = len(events_named(coordinator, "TURN_INGRESS_COMMITTED"))
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(
                events_named(coordinator, "TURN_INGRESS_COMMITTED")[before_turns][
                    "turn_id"
                ]
            )
            assert len(events_named(coordinator, "SLOWTASK_CREATED")) == 1
            assert_runtime_matches_replay(
                coordinator, suffix=f"spawn_{event_name}_{target_delta}"
            )
            dispatches = [
                message
                for message in by_type(sink.json_messages, "dispatch.result")
                if message.get("turn_id") == turn_id
            ]
            assert len(dispatches) == 1
            assert dispatches[0].get("actual_dispatch") != "mock_slow_spawn"
            assert_at_most_one_visible_semantic_reply(sink, turn_id)
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    ("event_name", "target_delta"),
    PATCH_APPEND_BOUNDARIES,
    ids=(
        "after-received",
        "after-interpreted",
        "after-plan-advanced",
        "after-planning-restarted",
        "after-task-replanned",
        "after-planning-state",
    ),
)
def test_slice3a12_patch_post_append_failure_reconciles_runtime_to_replay(
    event_name: str,
    target_delta: int,
) -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [
                FakeShadowScript(proposal_frame=spawn_frame()),
                FakeShadowScript(proposal_frame=patch_frame()),
            ],
            session_suffix=f"patch_fault_{event_name}",
        )
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            assert coordinator.state.active_task is not None
            install_post_append_fault(
                coordinator, event_name=event_name, target_delta=target_delta
            )
            before_turns = len(events_named(coordinator, "TURN_INGRESS_COMMITTED"))
            before_patches = len(events_named(coordinator, "USER_PATCH_RECEIVED"))

            await voice.trigger_scenario("patch")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(
                events_named(coordinator, "TURN_INGRESS_COMMITTED")[before_turns][
                    "turn_id"
                ]
            )
            assert len(events_named(coordinator, "USER_PATCH_RECEIVED")) == (
                before_patches + 1
            )
            assert_runtime_matches_replay(
                coordinator, suffix=f"patch_{event_name}_{target_delta}"
            )
            patch_ids = [
                str(event["patch_id"])
                for event in events_named(coordinator, "USER_PATCH_RECEIVED")
            ]
            assert len(patch_ids) == len(set(patch_ids))
            dispatches = [
                message
                for message in by_type(sink.json_messages, "dispatch.result")
                if message.get("turn_id") == turn_id
            ]
            assert len(dispatches) == 1
            assert dispatches[0].get("actual_dispatch") != "user_patch"
            assert_at_most_one_visible_semantic_reply(sink, turn_id)
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a12_user_patch_interpretation_failure_is_received_only_and_replayable() -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [
                FakeShadowScript(proposal_frame=spawn_frame()),
                FakeShadowScript(proposal_frame=patch_frame()),
            ],
            session_suffix="patch_interpretation_failure",
        )
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            before_received = len(events_named(coordinator, "USER_PATCH_RECEIVED"))
            before_interpreted = len(events_named(coordinator, "USER_PATCH_INTERPRETED"))
            before_turns = len(events_named(coordinator, "TURN_INGRESS_COMMITTED"))

            def interpretation_failure(**_kwargs: Any) -> Any:
                raise ValueError("PRIVATE_SLICE3A12_INTERPRETATION_FAULT")

            coordinator._slow_runtime.interpret_user_patch = interpretation_failure  # type: ignore[method-assign]
            await voice.trigger_scenario("patch")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(
                events_named(coordinator, "TURN_INGRESS_COMMITTED")[before_turns][
                    "turn_id"
                ]
            )
            assert len(events_named(coordinator, "USER_PATCH_RECEIVED")) == (
                before_received + 1
            )
            assert len(events_named(coordinator, "USER_PATCH_INTERPRETED")) == (
                before_interpreted
            )
            assert_runtime_matches_replay(coordinator, suffix="interpretation_failure")
            dispatches = [
                message
                for message in by_type(sink.json_messages, "dispatch.result")
                if message.get("turn_id") == turn_id
            ]
            assert len(dispatches) == 1
            assert dispatches[0].get("actual_dispatch") != "user_patch"
            assert_at_most_one_visible_semantic_reply(sink, turn_id)
            assert "PRIVATE_SLICE3A12_INTERPRETATION_FAULT" not in json.dumps(
                sink.json_messages, sort_keys=True
            )
        finally:
            await coordinator.close()

    run(scenario())


@pytest.mark.parametrize(
    "case",
    ("spawn_no_candidate", "patch_no_candidate", "ignore", "degraded", "quarantined_fast", "local_ack"),
)
def test_slice3a12_no_candidate_and_quarantine_routes_replay_deterministically(
    case: str,
) -> None:
    async def scenario() -> tuple[list[dict[str, Any]], str]:
        if case in {"spawn_no_candidate", "local_ack"}:
            scripts = [FakeShadowScript(proposal_frame=spawn_frame())]
            route = "spawn"
        elif case == "patch_no_candidate":
            scripts = [
                FakeShadowScript(proposal_frame=spawn_frame()),
                FakeShadowScript(proposal_frame=patch_frame()),
            ]
            route = "patch"
        elif case == "ignore":
            scripts = [
                FakeShadowScript(
                    proposal_frame=proposal_frame(
                        task_focus_hint="NON_ASSISTANT",
                        route_decision_hint="IGNORE",
                        foreground_act="SILENCE",
                        reply_candidate_text=None,
                    )
                )
            ]
            route = "ignore"
        elif case == "degraded":
            scripts = [FakeShadowScript(scenario="provider_error")]
            route = "fast"
        else:
            scripts = [
                FakeShadowScript(
                    proposal_frame=proposal_frame(
                        reply_candidate_text="PRIVATE_QUARANTINED_FAST_CANDIDATE"
                    )
                )
            ]
            route = "fast"
        coordinator, voice, sink = await make_coordinator(
            scripts, session_suffix=f"replay_{case}"
        )
        try:
            if case == "patch_no_candidate":
                await voice.trigger_scenario("spawn")
                await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            await voice.trigger_scenario(route)
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            if case in {"spawn_no_candidate", "patch_no_candidate", "ignore", "local_ack"}:
                latest_router = events_named(coordinator, "ROUTER_DECISION_EMITTED")[-1]
                gates = [
                    event
                    for event in events_named(coordinator, "FOREGROUND_ACT_GATE_FAILED")
                    if event.get("router_decision_event_id") == latest_router["event_id"]
                ]
                assert len(gates) <= 1
                if gates:
                    # The only legal Gate path has a real candidate event. A
                    # made-up ID or a candidate-less Gate event is forbidden.
                    candidate_id = gates[0].get("candidate_event_id")
                    assert isinstance(candidate_id, str) and candidate_id
                    assert any(
                        event.get("event_name")
                        == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
                        and event.get("event_id") == candidate_id
                        for event in coordinator.journal.events()
                    )
                else:
                    # With no candidate, a local fallback may commit directly
                    # from an explicit fallback policy without inventing Gate
                    # or candidate authority.
                    latest_committed = [
                        event
                        for event in events_named(
                            coordinator, "FOREGROUND_OUTPUT_COMMITTED"
                        )
                        if event.get("router_decision_event_id")
                        == latest_router["event_id"]
                    ]
                    assert all(
                        event.get("fallback_policy_ref")
                        and event.get("fallback_reason")
                        for event in latest_committed
                    )
            if case in {"spawn_no_candidate", "local_ack"}:
                assert events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")[-1][
                    "output_basis"
                ] == "template_ack"
            if case == "quarantined_fast":
                assert events_named(coordinator, "FOREGROUND_OUTPUT_DISCARDED")
                assert not [
                    event
                    for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
                    if event.get("output_basis") == "reply_candidate"
                ]
                serialized = json.dumps(
                    {
                        "journal": coordinator.journal.events(),
                        "timeline": list(coordinator.metadata_timeline),
                    },
                    sort_keys=True,
                )
                assert "PRIVATE_QUARANTINED_FAST_CANDIDATE" not in serialized
            assert sink.binary_messages == []
            return coordinator.journal.events(), case
        finally:
            await coordinator.close()

    events, suffix = run(scenario())
    canonical = (
        MVP0_EVENT_NAMES | MVP1_EVENT_NAMES | MVP2_EVENT_NAMES | FAST_FOREGROUND_EVENT_NAMES
    )
    assert {str(event["event_name"]) for event in events} <= canonical
    fixture = replay_fixture(events, suffix=suffix)
    first = run_replay_fixture(fixture)
    second = run_replay_fixture(fixture)
    assert first.ordered_events == second.ordered_events
    assert first.state_digest == second.state_digest


def test_slice3a12_watchdog_timeline_failure_still_rebuilds_and_stale_generation_is_ignored() -> None:
    async def scenario() -> None:
        sink = FaultBrowserSink()
        provider = GenerationWatchdogProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            config=CoordinatorConfig(voice_cancel_terminal_timeout_seconds=0.01),
            session_id="session_qfs_slice3a12_watchdog",
            conversation_id="conversation_qfs_slice3a12_watchdog",
        )
        await coordinator.start()
        await asyncio.sleep(0)
        try:
            sink.arm("timeline.metadata", phase="after")
            await coordinator.handle_provider_event(
                VoiceProviderEvent(
                    type="response.created",
                    output_mode="real",
                    response_id="voice-response-watchdog",
                    provider_item_id="voice-output-watchdog",
                    session_ref="voice-session-generation-0001",
                    session_generation=1,
                    suppressed=True,
                    quarantined=True,
                )
            )
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert sink.failure_count == 1
            assert provider.rebuild_calls == 1
            assert provider.session_generation == 2
            assert coordinator.state.voice_context_rebuild_count == 1
            assert coordinator.state.voice_context_tainted is False
            assert coordinator.state.voice_session_status == "connected"
            assert not [task for task in coordinator._background_tasks if task.done()]

            before_status = coordinator.state.voice_session_status
            before_asr = len(events_named(coordinator, "ASR_TRANSCRIPT_OUTPUT_EMITTED"))
            before_discarded = coordinator.state.discarded_late_audio_frames
            stale_events = (
                VoiceProviderEvent(
                    type="provider.disconnected",
                    output_mode="degraded",
                    session_ref="voice-session-generation-0001",
                    session_generation=1,
                    error_code="PRIVATE_STALE_TERMINAL",
                    terminal=True,
                ),
                VoiceProviderEvent(
                    type="user.transcript.final",
                    output_mode="real",
                    provider_item_id="voice-input-stale",
                    turn_ref="voice-turn-stale",
                    utterance_ref="voice-utterance-stale",
                    audio_span_ref="voice-audio-stale",
                    session_generation=1,
                    text="PRIVATE_STALE_ASR_FINAL",
                ),
                VoiceProviderEvent(
                    type="response.audio.delta",
                    output_mode="real",
                    response_id="voice-response-stale",
                    provider_item_id="voice-output-stale",
                    session_generation=1,
                    audio=b"\x03\x00" * 80,
                    suppressed=True,
                    quarantined=True,
                ),
            )
            for event in stale_events:
                await coordinator.handle_provider_event(event)  # type: ignore[arg-type]

            assert coordinator.state.voice_session_status == before_status
            assert len(events_named(coordinator, "ASR_TRANSCRIPT_OUTPUT_EMITTED")) == before_asr
            assert coordinator.state.discarded_late_audio_frames == before_discarded + 3
            assert sink.binary_messages == []
            serialized = json.dumps(
                {
                    "journal": coordinator.journal.events(),
                    "timeline": list(coordinator.metadata_timeline),
                    "messages": sink.json_messages,
                },
                sort_keys=True,
            )
            assert "PRIVATE_STALE_TERMINAL" not in serialized
            assert "PRIVATE_STALE_ASR_FINAL" not in serialized
            assert (b"\x03\x00" * 80).hex() not in serialized
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a12_terminal_receiver_rebuilds_then_consumes_only_new_generation() -> None:
    async def scenario() -> None:
        sink = FaultBrowserSink()
        provider = GenerationWatchdogProvider()
        coordinator = RealtimeSessionCoordinator(
            sink,
            provider,  # type: ignore[arg-type]
            shadow_provider=FakeShadowControlProvider(),
            provider_mode="qwen",
            routing_mode="enforced",
            audio_output="none",
            shadow_control_mode="dual_session",
            session_id="session_qfs_slice3a12_terminal_receiver",
            conversation_id="conversation_qfs_slice3a12_terminal_receiver",
        )
        await coordinator.start()
        try:
            await asyncio.wait_for(provider.wait_events_drained(), timeout=1)
            sink.arm("safe_error", phase="before")
            await provider.queue_event(
                VoiceProviderEvent(
                    type="provider.disconnected",
                    output_mode="degraded",
                    session_ref="voice-session-generation-0001",
                    session_generation=1,
                    error_code="PRIVATE_TERMINAL_RECEIVER",
                    terminal=True,
                )
            )
            for _ in range(100):
                if provider.session_generation == 2:
                    break
                await asyncio.sleep(0.01)
            assert provider.rebuild_calls == 1
            assert provider.session_generation == 2

            await provider.queue_event(
                VoiceProviderEvent(
                    type="session.updated",
                    output_mode="mock",
                    session_ref="voice-session-generation-0002",
                    session_generation=2,
                )
            )
            await asyncio.wait_for(provider.wait_events_drained(), timeout=1)
            for _ in range(100):
                if coordinator.state.voice_session_status == "connected":
                    break
                await asyncio.sleep(0.01)

            assert coordinator.state.voice_session_status == "connected"
            assert provider.recv_generations[-1] == 2
            first_generation_receives = [
                generation
                for generation in provider.recv_generations
                if generation == 1
            ]
            # Two startup events plus one terminal; the retired generation is
            # never polled again after terminal ownership transfers.
            assert len(first_generation_receives) == 3
            assert sink.failure_count == 1
            assert "PRIVATE_TERMINAL_RECEIVER" not in json.dumps(
                sink.json_messages, sort_keys=True
            )
        finally:
            await coordinator.close()

    run(scenario())
