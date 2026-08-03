from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Mapping

from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeRealtimeProvider,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    SCHEMA_VERSION,
    FakeShadowControlProvider,
    FakeShadowScript,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    RealtimeSessionCoordinator,
)


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


class MemorySink:
    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.binary_messages: list[bytes] = []

    async def send_json(self, data: Mapping[str, Any]) -> None:
        self.json_messages.append(deepcopy(dict(data)))

    async def send_bytes(self, data: bytes) -> None:
        self.binary_messages.append(bytes(data))

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        return None


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
        "reply_candidate_text": "PRIVATE_PROVIDER_CANDIDATE",
    }
    frame.update(overrides)
    return frame


def spawn_frame() -> dict[str, object]:
    return proposal_frame(
        task_focus_hint="NEW_TASK_CANDIDATE",
        route_decision_hint="SPAWN_SLOW_TASK",
        foreground_act="ACK_SLOW",
        task_like=True,
        complexity_hint="HIGH",
        reply_candidate_text=None,
    )


def patch_frame() -> dict[str, object]:
    return proposal_frame(
        task_focus_hint="ACTIVE_TASK_PATCH",
        route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
        foreground_act="ACK_PATCH",
        task_like=True,
        complexity_hint="MEDIUM",
        reply_candidate_text=None,
    )


async def make_coordinator(
    scripts: list[FakeShadowScript],
    *,
    suffix: str,
) -> tuple[RealtimeSessionCoordinator, FakeRealtimeProvider, MemorySink]:
    sink = MemorySink()
    voice = FakeRealtimeProvider(
        FakeProviderConfig(response_audio_chunks=1, event_delay_seconds=0)
    )
    coordinator = RealtimeSessionCoordinator(
        sink,
        voice,
        shadow_provider=FakeShadowControlProvider(scripts),
        provider_mode="qwen",
        routing_mode="enforced",
        audio_output="none",
        shadow_control_mode="dual_session",
        session_id=f"session_qfs_slice3a13_{suffix}",
        conversation_id=f"conversation_qfs_slice3a13_{suffix}",
    )
    await coordinator.start()
    await asyncio.sleep(0)
    return coordinator, voice, sink


def events_named(
    coordinator: RealtimeSessionCoordinator, event_name: str
) -> list[dict[str, Any]]:
    return [
        event
        for event in coordinator.journal.events()
        if event.get("event_name") == event_name
    ]


def assistant_done_for_turn(
    sink: MemorySink, turn_id: str
) -> list[dict[str, Any]]:
    return [
        message
        for message in sink.json_messages
        if message.get("type") == "transcript.assistant.done"
        and message.get("turn_id") == turn_id
    ]


def test_slice3a13_quarantined_fast_candidate_commits_clarify_not_ack() -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [FakeShadowScript(proposal_frame=proposal_frame())],
            suffix="quarantined_fast",
        )
        try:
            await voice.trigger_scenario("fast")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(events_named(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"])
            commits = [
                event
                for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
                if event.get("turn_id") == turn_id
            ]
            assert len(commits) == 1
            commit = commits[0]
            assert commit["output_basis"] == "template_clarify"
            visible = assistant_done_for_turn(sink, turn_id)
            assert len(visible) == 1
            assert visible[0]["foreground_act"] == "CLARIFY"
            assert visible[0]["output_basis"] == commit["output_basis"]
            assert visible[0]["output_ref"] == commit["output_ref"]
            assert visible[0]["commit_ref"] == commit["event_id"]
            assert visible[0]["text"] != "PRIVATE_PROVIDER_CANDIDATE"
            assert sink.binary_messages == []
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a13_spawn_ack_commit_occurs_only_after_complete_mutation() -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [FakeShadowScript(proposal_frame=spawn_frame())],
            suffix="spawn_complete",
        )
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(events_named(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"])
            commits = [
                event
                for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
                if event.get("turn_id") == turn_id
            ]
            assert len(commits) == 1
            commit = commits[0]
            assert commit["output_basis"] == "template_ack"
            mutation_tail = events_named(coordinator, "PLANNING_STARTED")[-1]
            assert int(commit["event_seq"]) > int(mutation_tail["event_seq"])
            visible = assistant_done_for_turn(sink, turn_id)
            assert len(visible) == 1
            assert visible[0]["foreground_act"] == "ACK_SLOW"
            assert visible[0]["output_ref"] == commit["output_ref"]
            assert visible[0]["output_basis"] == "template_ack"
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a13_partial_spawn_never_commits_or_delivers_success_ack() -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [FakeShadowScript(proposal_frame=spawn_frame())],
            suffix="spawn_partial",
        )
        original_append = coordinator.journal.append

        def append_then_fail(**kwargs: Any) -> dict[str, Any]:
            event = original_append(**kwargs)
            if kwargs.get("event_name") == "PLANNING_STARTED":
                raise RuntimeError("PRIVATE_PARTIAL_MUTATION")
            return event

        coordinator.journal.append = append_then_fail  # type: ignore[method-assign]
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(events_named(coordinator, "TURN_INGRESS_COMMITTED")[-1]["turn_id"])
            commits = [
                event
                for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
                if event.get("turn_id") == turn_id
            ]
            assert len(commits) == 1
            assert commits[0]["output_basis"] == "template_clarify"
            visible = assistant_done_for_turn(sink, turn_id)
            assert len(visible) == 1
            assert visible[0]["foreground_act"] == "CLARIFY"
            assert visible[0]["output_ref"] == commits[0]["output_ref"]
            assert all(message.get("foreground_act") != "ACK_SLOW" for message in visible)
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a13_patch_ack_commit_occurs_only_after_complete_mutation() -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [
                FakeShadowScript(proposal_frame=spawn_frame()),
                FakeShadowScript(proposal_frame=patch_frame()),
            ],
            suffix="patch_complete",
        )
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            before_turns = len(events_named(coordinator, "TURN_INGRESS_COMMITTED"))
            before_patch_events = len(events_named(coordinator, "USER_PATCH_RECEIVED"))

            await voice.trigger_scenario("patch")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(
                events_named(coordinator, "TURN_INGRESS_COMMITTED")[before_turns][
                    "turn_id"
                ]
            )
            patch_event = events_named(coordinator, "USER_PATCH_RECEIVED")[
                before_patch_events
            ]
            commits = [
                event
                for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
                if event.get("turn_id") == turn_id
            ]
            assert len(commits) == 1
            assert commits[0]["output_basis"] == "template_ack"
            assert int(commits[0]["event_seq"]) > int(patch_event["event_seq"])
            visible = assistant_done_for_turn(sink, turn_id)
            assert len(visible) == 1
            assert visible[0]["foreground_act"] == "ACK_PATCH"
            assert visible[0]["output_ref"] == commits[0]["output_ref"]
            assert visible[0]["output_basis"] == "template_ack"
        finally:
            await coordinator.close()

    run(scenario())


def test_slice3a13_partial_patch_never_commits_or_delivers_success_ack() -> None:
    async def scenario() -> None:
        coordinator, voice, sink = await make_coordinator(
            [
                FakeShadowScript(proposal_frame=spawn_frame()),
                FakeShadowScript(proposal_frame=patch_frame()),
            ],
            suffix="patch_partial",
        )
        try:
            await voice.trigger_scenario("spawn")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            before_turns = len(events_named(coordinator, "TURN_INGRESS_COMMITTED"))
            original_append = coordinator.journal.append

            def append_then_fail(**kwargs: Any) -> dict[str, Any]:
                event = original_append(**kwargs)
                if kwargs.get("event_name") == "PLANNING_RESTARTED":
                    raise RuntimeError("PRIVATE_PARTIAL_PATCH")
                return event

            coordinator.journal.append = append_then_fail  # type: ignore[method-assign]
            await voice.trigger_scenario("patch")
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            turn_id = str(
                events_named(coordinator, "TURN_INGRESS_COMMITTED")[before_turns][
                    "turn_id"
                ]
            )
            commits = [
                event
                for event in events_named(coordinator, "FOREGROUND_OUTPUT_COMMITTED")
                if event.get("turn_id") == turn_id
            ]
            assert len(commits) == 1
            assert commits[0]["output_basis"] == "template_clarify"
            visible = assistant_done_for_turn(sink, turn_id)
            assert len(visible) == 1
            assert visible[0]["foreground_act"] == "CLARIFY"
            assert visible[0]["output_ref"] == commits[0]["output_ref"]
            assert all(
                message.get("foreground_act") != "ACK_PATCH"
                for message in visible
            )
        finally:
            await coordinator.close()

    run(scenario())
