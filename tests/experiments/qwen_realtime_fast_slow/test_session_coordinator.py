from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Mapping

import pytest

from experiments.qwen_realtime_fast_slow_web.browser_protocol import (
    unpack_output_audio,
)
from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeProviderEvent,
    FakeRealtimeProvider,
)
from experiments.qwen_realtime_fast_slow_web.session_coordinator import (
    CoordinatorConfig,
    RealtimeSessionCoordinator,
)
from voice_agent.replay.runner import run_replay_fixture


def run(coro):
    return asyncio.run(coro)


def pcm_frame(amplitude: int = 1_000, samples: int = 1_600) -> bytes:
    return amplitude.to_bytes(2, "little", signed=True) * samples


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


async def make_coordinator(
    *,
    coordinator_config: CoordinatorConfig | None = None,
    provider_config: FakeProviderConfig | None = None,
    session_id: str = "session_qfs_test",
) -> tuple[RealtimeSessionCoordinator, FakeRealtimeProvider, MemoryBrowserSink]:
    sink = MemoryBrowserSink()
    provider = FakeRealtimeProvider(
        provider_config or FakeProviderConfig(event_delay_seconds=0)
    )
    coordinator = RealtimeSessionCoordinator(
        sink,
        provider,
        config=coordinator_config,
        session_id=session_id,
        conversation_id=f"conversation_{session_id}",
    )
    await coordinator.start()
    # Let the two provider session metadata events cross the receive loop.
    await asyncio.sleep(0)
    return coordinator, provider, sink


async def run_scenario(
    coordinator: RealtimeSessionCoordinator,
    sink: MemoryBrowserSink,
    scenario: str,
    **overrides: object,
) -> tuple[list[dict[str, Any]], list[tuple[str, Any]]]:
    json_start = len(sink.json_messages)
    record_start = len(sink.records)
    await coordinator.handle_control(
        {"type": "synthetic.turn", "scenario": scenario, **overrides}
    )
    await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
    return sink.json_messages[json_start:], sink.records[record_start:]


def by_type(messages: list[dict[str, Any]], message_type: str) -> list[dict[str, Any]]:
    return [message for message in messages if message.get("type") == message_type]


def journal_names(coordinator: RealtimeSessionCoordinator) -> list[str]:
    return [str(event["event_name"]) for event in coordinator.journal.events()]


async def wait_until(predicate, *, timeout: float = 1.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=timeout)


def test_session_start_and_configure_publish_mock_ready_and_state() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator()
        try:
            ready = by_type(sink.json_messages, "session.ready")
            assert len(ready) == 1
            assert ready[0]["session_id"] == "session_qfs_test"
            assert ready[0]["provider_mode"] == "fake"
            assert ready[0]["output_mode"] == "mock"
            assert ready[0]["degraded"] is False
            assert ready[0]["capabilities"]["supports_real_provider"] is False

            await coordinator.handle_control(
                {
                    "type": "session.configure",
                    "scenario": "ambiguous",
                    "playback_enabled": False,
                }
            )
            await coordinator.handle_control({"type": "microphone.start"})

            assert coordinator.state.configured_scenario == "ambiguous"
            assert coordinator.state.playback_enabled is False
            assert coordinator.state.microphone_active is True
            assert provider.default_scenario == "ambiguous"
            assert by_type(sink.json_messages, "state.changed")[-1]["reason"] == (
                "microphone_started"
            )
            names = journal_names(coordinator)
            assert names[:2] == [
                "SESSION_STARTED",
                "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
            ]
        finally:
            await coordinator.close()

    run(scenario())


def test_continuous_binary_audio_forwarding_emits_asr_delta_and_final() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator(
            provider_config=FakeProviderConfig(
                auto_stop_after_voiced_frames=3,
                transcript_delta_every_frames=1,
                response_audio_chunks=2,
                event_delay_seconds=0,
            )
        )
        try:
            await coordinator.handle_control({"type": "microphone.start"})
            frame = pcm_frame()
            assert [await coordinator.submit_audio(frame) for _ in range(3)] == [
                True,
                True,
                True,
            ]
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)

            assert provider.sent_audio_frames == 3
            assert provider.sent_audio_bytes == 3 * len(frame)
            assert len(by_type(sink.json_messages, "transcript.user.delta")) == 3
            finals = by_type(sink.json_messages, "transcript.user.final")
            assert len(finals) == 1
            assert finals[0]["text"].startswith("[synthetic]")
            names = journal_names(coordinator)
            assert "TURN_INGRESS_COMMITTED" in names
            assert "MOCK_ASR_FRAME_EMITTED" in names
            assert "ROUTER_DECISION_EMITTED" in names
        finally:
            await coordinator.close()

    run(scenario())


def test_fast_only_gate_passes_before_candidate_text_or_pcm_becomes_visible() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator()
        try:
            messages, records = await run_scenario(coordinator, sink, "fast")

            proposal = by_type(messages, "route.proposed")[-1]
            decision = by_type(messages, "route.decided")[-1]
            gate = by_type(messages, "gate.result")[-1]
            assert proposal["route_hint"] == "FAST_ONLY"
            assert decision["router_decision"] == "FAST_ONLY"
            assert decision["task_focus"] == "FOREGROUND_CHAT"
            assert gate["gate_status"] == "passed"

            gate_index = next(
                index
                for index, (kind, value) in enumerate(records)
                if kind == "json" and value.get("type") == "gate.result"
            )
            visible_indexes = [
                index
                for index, (kind, value) in enumerate(records)
                if kind == "binary"
                or (kind == "json" and value.get("type", "").startswith("transcript.assistant"))
            ]
            assert visible_indexes and min(visible_indexes) > gate_index
            assistant = by_type(messages, "transcript.assistant.done")[-1]
            assert assistant["text"] == "Synthetic fast reply."
            assert assistant["source"] == "provider_candidate"

            assert sink.binary_messages
            unpacked = [unpack_output_audio(frame) for frame in sink.binary_messages]
            assert {epoch for epoch, _pcm in unpacked} == {
                coordinator.state.playback_epoch
            }
            assert all(pcm and len(pcm) % 2 == 0 for _epoch, pcm in unpacked)
            names = journal_names(coordinator)
            for required in (
                "FAST_INTERACTION_OUTPUT_EMITTED",
                "FOREGROUND_REPLY_CANDIDATE_EMITTED",
                "ROUTER_DECISION_EMITTED",
                "FOREGROUND_ACT_GATE_PASSED",
                "FOREGROUND_OUTPUT_COMMITTED",
                "PLAYBACK_SPAN_STARTED",
                "PLAYBACK_FINISHED",
            ):
                assert required in names
            assert coordinator.quarantine.active_response_ids == ()
        finally:
            await coordinator.close()

    run(scenario())


def test_fast_gate_rejects_high_risk_candidate_and_uses_controlled_clarify() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator()
        try:
            messages, records = await run_scenario(
                coordinator, sink, "fast", risk_class="HIGH"
            )

            assert by_type(messages, "route.decided")[-1]["router_decision"] == (
                "FAST_ONLY"
            )
            gate = by_type(messages, "gate.result")[-1]
            assert gate["gate_status"] == "failed"
            assert gate["risk_class"] == "HIGH"
            assistant = by_type(messages, "transcript.assistant.done")[-1]
            assert assistant["source"] == "controlled_template"
            assert assistant["foreground_act"] == "CLARIFY"
            assert "Synthetic fast reply" not in json.dumps(messages)
            assert not any(kind == "binary" for kind, _value in records)
            assert provider.cancel_count == 1
            assert coordinator.quarantine.active_response_ids == ()
            assert "FOREGROUND_ACT_GATE_FAILED" in journal_names(coordinator)
            assert "FOREGROUND_OUTPUT_DISCARDED" in journal_names(coordinator)
        finally:
            await coordinator.close()

    run(scenario())


def test_spawn_creates_one_mock_slowtask_and_discards_provider_candidate() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator()
        try:
            messages, records = await run_scenario(coordinator, sink, "spawn")

            assert by_type(messages, "route.decided")[-1]["router_decision"] == (
                "SPAWN_SLOW_TASK"
            )
            assert by_type(messages, "gate.result")[-1]["gate_status"] == "discarded"
            task = coordinator.state.active_task
            assert task is not None
            assert task.lifecycle == "PLANNING"
            assert task.plan_version == 1
            slowtask = by_type(messages, "slowtask.state")[-1]
            assert slowtask["task_id"] == task.task_id
            assert slowtask["plan_version"] == 1
            assistant = by_type(messages, "transcript.assistant.done")[-1]
            assert assistant["foreground_act"] == "ACK_SLOW"
            assert assistant["source"] == "controlled_template"
            assert "Uncommitted provider slow-task answer" not in json.dumps(messages)
            assert not any(kind == "binary" for kind, _value in records)
            assert provider.cancel_count == 1
            assert "SLOWTASK_CREATED" in journal_names(coordinator)
        finally:
            await coordinator.close()

    run(scenario())


def test_second_spawn_is_routed_as_patch_and_never_creates_two_active_tasks() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator()
        try:
            await run_scenario(coordinator, sink, "spawn")
            first_task = coordinator.state.active_task
            assert first_task is not None
            first_task_id = first_task.task_id

            messages, _records = await run_scenario(coordinator, sink, "spawn")
            task = coordinator.state.active_task
            assert task is not None
            assert task.task_id == first_task_id
            assert task.plan_version == 2
            assert by_type(messages, "route.decided")[-1]["router_decision"] == (
                "PATCH_ACTIVE_SLOW_TASK"
            )
            created = [
                event
                for event in coordinator.journal.events()
                if event["event_name"] == "SLOWTASK_CREATED"
            ]
            assert len(created) == 1
        finally:
            await coordinator.close()

    run(scenario())


def test_patch_flows_through_userpatch_and_advances_bound_plan_version() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator()
        try:
            await run_scenario(coordinator, sink, "spawn")
            task = coordinator.state.active_task
            assert task is not None
            task_id = task.task_id
            old_plan_version = task.plan_version

            messages, records = await run_scenario(coordinator, sink, "patch")
            patch = by_type(messages, "userpatch.accepted")[-1]
            assert by_type(messages, "route.decided")[-1]["router_decision"] == (
                "PATCH_ACTIVE_SLOW_TASK"
            )
            assert patch["task_id"] == task_id
            assert patch["observed_plan_version"] == old_plan_version
            assert patch["plan_version"] == old_plan_version + 1
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.task_id == task_id
            assert coordinator.state.active_task.plan_version == old_plan_version + 1
            assistant = by_type(messages, "transcript.assistant.done")[-1]
            assert assistant["foreground_act"] == "ACK_PATCH"
            assert "Uncommitted provider patch answer" not in json.dumps(messages)
            assert not any(kind == "binary" for kind, _value in records)
            names = journal_names(coordinator)
            assert "USER_PATCH_RECEIVED" in names
            assert "USER_PATCH_INTERPRETED" in names
            patch_events = [
                event
                for event in coordinator.journal.events()
                if event["event_name"] in {"USER_PATCH_RECEIVED", "USER_PATCH_INTERPRETED"}
            ]
            assert all(event["task_id"] == task_id for event in patch_events)
            assert all("plan_version" in event for event in patch_events)
        finally:
            await coordinator.close()

    run(scenario())


def test_ignore_discards_candidate_and_produces_no_assistant_or_audio() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator()
        try:
            messages, records = await run_scenario(coordinator, sink, "ignore")

            assert by_type(messages, "route.decided")[-1]["router_decision"] == "IGNORE"
            assert by_type(messages, "gate.result")[-1]["gate_status"] == "discarded"
            assert by_type(messages, "transcript.assistant.delta") == []
            assert by_type(messages, "transcript.assistant.done") == []
            assert not any(kind == "binary" for kind, _value in records)
            assert provider.cancel_count == 1
            assert coordinator.quarantine.active_response_ids == ()
        finally:
            await coordinator.close()

    run(scenario())


def test_ambiguous_input_discards_candidate_and_uses_controlled_clarify() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator()
        try:
            messages, records = await run_scenario(coordinator, sink, "ambiguous")

            decision = by_type(messages, "route.decided")[-1]
            assert decision["router_decision"] == "FAST_ONLY"
            assert decision["task_focus"] == "AMBIGUOUS"
            assert by_type(messages, "gate.result")[-1]["gate_status"] == "failed"
            assistant = by_type(messages, "transcript.assistant.done")[-1]
            assert assistant["foreground_act"] == "CLARIFY"
            assert assistant["source"] == "controlled_template"
            assert "Uncommitted provider ambiguous answer" not in json.dumps(messages)
            assert not any(kind == "binary" for kind, _value in records)
        finally:
            await coordinator.close()

    run(scenario())


def test_pending_confirmation_input_stays_on_patch_path_and_slowtask_owns_cancel() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator()
        try:
            await run_scenario(coordinator, sink, "spawn")
            cancel_messages, _ = await run_scenario(coordinator, sink, "cancel")
            task = coordinator.state.active_task
            assert task is not None
            assert by_type(cancel_messages, "route.decided")[-1]["router_decision"] == (
                "PATCH_ACTIVE_SLOW_TASK"
            )
            assert task.lifecycle == "WAITING_FOR_USER_CONFIRMATION"
            assert task.pending_confirmation_scope == "TASK_CANCEL"
            version_waiting = task.plan_version

            confirm_messages, _ = await run_scenario(coordinator, sink, "confirm")
            assert by_type(confirm_messages, "route.decided")[-1]["router_decision"] == (
                "PATCH_ACTIVE_SLOW_TASK"
            )
            assert by_type(confirm_messages, "userpatch.accepted")
            assert coordinator.state.active_task is not None
            assert coordinator.state.active_task.terminal_status == "CANCELLED"
            assert coordinator.state.active_task.pending_confirmation_scope is None
            assert coordinator.state.active_task.plan_version == version_waiting
            names = journal_names(coordinator)
            assert "CONFIRMATION_REQUIRED" in names
            assert "CONFIRMATION_ACCEPTED" in names
            assert "SLOWTASK_CANCELLED" in names
        finally:
            await coordinator.close()

    run(scenario())


def test_explicit_interrupt_cancels_response_clears_quarantine_and_drops_late_audio() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator(
            provider_config=FakeProviderConfig(
                response_audio_chunks=8,
                event_delay_seconds=0.01,
                late_audio_after_cancel=True,
            )
        )
        try:
            await coordinator.handle_control(
                {"type": "synthetic.turn", "scenario": "fast"}
            )
            await wait_until(
                lambda: provider.response_active
                and bool(coordinator.quarantine.active_response_ids),
                timeout=1,
            )
            epoch_before = coordinator.state.playback_epoch
            record_start = len(sink.records)

            await coordinator.handle_control({"type": "interrupt.request"})
            await asyncio.wait_for(coordinator.wait_for_idle(), timeout=3)
            records = sink.records[record_start:]

            assert coordinator.state.playback_epoch == epoch_before + 1
            assert provider.cancel_count == 1
            assert coordinator.state.provider_cancel_count == 1
            assert coordinator.quarantine.active_response_ids == ()
            assert coordinator.state.discarded_late_audio_frames >= 1
            clear = next(
                value
                for kind, value in records
                if kind == "json" and value.get("type") == "playback.clear"
            )
            assert clear["reason"] == "explicit_interrupt"
            assert clear["playback_epoch"] == epoch_before + 1
            assert not any(kind == "binary" for kind, _value in records)
            assert not any(
                kind == "json" and value.get("type") == "route.decided"
                for kind, value in records
            )
        finally:
            await coordinator.close()

    run(scenario())


def test_speech_started_late_audio_scenario_advances_epoch_and_discards_old_pcm() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator(
            provider_config=FakeProviderConfig(
                response_audio_chunks=1,
                event_delay_seconds=0,
                late_audio_after_cancel=True,
            )
        )
        try:
            messages, _records = await run_scenario(coordinator, sink, "late_audio")

            clears = by_type(messages, "playback.clear")
            assert len(clears) >= 2
            assert clears[-1]["reason"] == "speech_started"
            assert coordinator.state.playback_epoch >= 2
            assert coordinator.state.discarded_late_audio_frames >= 1
            assert by_type(messages, "flow.changed")[-1][
                "discarded_late_audio_frames"
            ] >= 1
        finally:
            await coordinator.close()

    run(scenario())


def test_input_and_output_queues_are_bounded_and_count_drops() -> None:
    async def scenario() -> None:
        sink = MemoryBrowserSink()
        provider = FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))
        coordinator = RealtimeSessionCoordinator(
            sink,
            provider,
            config=CoordinatorConfig(
                max_input_queue_frames=2,
                max_output_queue_batches=1,
            ),
            session_id="session_qfs_bounds",
            conversation_id="conversation_qfs_bounds",
        )
        try:
            frame = pcm_frame()
            await coordinator.submit_audio(frame)
            await coordinator.submit_audio(frame)
            await coordinator.submit_audio(frame)
            assert coordinator.input_queue_depth == 2
            assert coordinator.state.dropped_input_frames == 1

            await coordinator._release_candidate(  # noqa: SLF001 - bounded queue seam
                ("synthetic",),
                (b"\x01\x00",),
                response_id="response-1",
                turn_id="turn-1",
                utterance_id="utterance-1",
                foreground_act="ANSWER",
                committed_event_id="event-commit-1",
            )
            await coordinator._release_candidate(  # noqa: SLF001 - bounded queue seam
                ("synthetic",),
                (b"\x02\x00", b"\x03\x00"),
                response_id="response-2",
                turn_id="turn-2",
                utterance_id="utterance-2",
                foreground_act="ANSWER",
                committed_event_id="event-commit-2",
            )
            assert coordinator.output_queue_depth == 1
            assert coordinator.state.dropped_output_frames == 2
            assert by_type(sink.json_messages, "flow.changed")[-1][
                "dropped_output_frames"
            ] == 2
        finally:
            await coordinator.close()

    run(scenario())


def test_provider_error_disconnect_and_safe_error_are_normalized() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator()
        try:
            await provider.trigger_error(
                "Bearer credential from raw provider body", terminal=False
            )
            await provider.wait_events_drained()
            await coordinator.report_safe_error(
                "https://unsafe.example/?token=secret", terminal=False
            )
            await provider.trigger_disconnect()
            await provider.wait_events_drained()

            degraded = by_type(sink.json_messages, "degraded")
            errors = by_type(sink.json_messages, "safe_error")
            assert degraded[0]["output_mode"] == "degraded"
            assert degraded[-1]["code"] == "synthetic_provider_disconnect"
            assert errors[-1]["terminal"] is True
            serialized = json.dumps(errors, sort_keys=True)
            assert "Bearer credential" not in serialized
            assert "unsafe.example" not in serialized
            assert "token=secret" not in serialized
            assert "internal_error" in serialized
            assert "synthetic_provider_disconnect" in serialized
        finally:
            await coordinator.close()

    run(scenario())


def test_disconnect_control_and_close_clear_session_owned_resources() -> None:
    async def scenario() -> None:
        coordinator, provider, _sink = await make_coordinator()
        await coordinator.handle_control({"type": "disconnect"})
        assert coordinator.state.disconnect_requested is True

        await coordinator.close()
        await coordinator.close()
        assert coordinator.state.status == "DISCONNECTED"
        assert provider.profile.health_status == "closed"
        assert coordinator.input_queue_depth == 0
        assert coordinator.output_queue_depth == 0
        assert coordinator.quarantine.active_response_ids == ()

    run(scenario())


def test_close_drains_input_frames_that_were_never_forwarded() -> None:
    async def scenario() -> None:
        sink = MemoryBrowserSink()
        provider = FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))
        coordinator = RealtimeSessionCoordinator(
            sink,
            provider,
            session_id="session_qfs_close_pending",
            conversation_id="conversation_qfs_close_pending",
        )
        await coordinator.submit_audio(pcm_frame())
        await coordinator.submit_audio(pcm_frame())
        assert coordinator.input_queue_depth == 2

        await coordinator.close()

        assert coordinator.input_queue_depth == 0
        assert provider.profile.health_status == "closed"

    run(scenario())


def test_microphone_default_rejects_provider_failure_control_scenarios() -> None:
    async def scenario() -> None:
        coordinator, provider, sink = await make_coordinator()
        try:
            await coordinator.handle_control(
                {"type": "session.configure", "scenario": "provider_error"}
            )

            assert coordinator.state.configured_scenario == "fast"
            assert provider.default_scenario == "fast"
            assert by_type(sink.json_messages, "safe_error")[-1]["code"] == (
                "microphone_scenario_unsupported"
            )
        finally:
            await coordinator.close()

    run(scenario())


def test_interrupt_before_response_created_fences_late_spawn_route() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator()
        try:
            turn_ref = "provider-turn-late-response"
            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type="speech.started", scenario="spawn", turn_ref=turn_ref
                )
            )
            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type="speech.stopped", scenario="spawn", turn_ref=turn_ref
                )
            )
            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type="user.transcript.final",
                    scenario="spawn",
                    turn_ref=turn_ref,
                    text="[synthetic] late response route",
                )
            )
            await coordinator.handle_control({"type": "interrupt.request"})
            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type="response.created",
                    scenario="spawn",
                    turn_ref=turn_ref,
                    response_id="provider-response-late",
                    provider_item_id="provider-item-late",
                )
            )
            await coordinator.handle_provider_event(
                FakeProviderEvent(
                    type="route.proposed",
                    scenario="spawn",
                    response_id="provider-response-late",
                    provider_item_id="provider-item-late",
                    route_hint="SPAWN_SLOW_TASK",
                    task_focus_hint="NEW_TASK_CANDIDATE",
                    foreground_act="ANSWER",
                    risk_class="LOW",
                    confidence=0.99,
                )
            )

            assert coordinator.state.active_task is None
            assert by_type(sink.json_messages, "route.decided") == []
            assert "ROUTER_DECISION_EMITTED" not in journal_names(coordinator)
            assert coordinator.quarantine.active_response_ids == ()
        finally:
            await coordinator.close()

    run(scenario())


def test_json_metadata_and_canonical_journal_contain_no_pcm_or_credentials() -> None:
    async def scenario() -> None:
        coordinator, _provider, sink = await make_coordinator()
        try:
            await run_scenario(coordinator, sink, "fast")
            await run_scenario(coordinator, sink, "spawn")

            def visit(value: object, path: str = "root") -> None:
                assert not isinstance(value, bytes), f"{path} contains raw bytes"
                if isinstance(value, Mapping):
                    for key, child in value.items():
                        lowered = str(key).lower()
                        assert lowered not in {
                            "api_key",
                            "authorization_header",
                            "cookie",
                            "credential",
                            "raw_audio",
                            "raw_provider_payload",
                        }
                        visit(child, f"{path}.{key}")
                elif isinstance(value, (list, tuple)):
                    for index, child in enumerate(value):
                        visit(child, f"{path}[{index}]")

            visit(sink.json_messages, "browser_json")
            visit(list(coordinator.metadata_timeline), "timeline")
            visit(coordinator.journal.events(), "journal")
            serialized_timeline = json.dumps(
                list(coordinator.metadata_timeline), sort_keys=True
            ).lower()
            assert "synthetic fast reply" not in serialized_timeline
            assert "uncommitted provider" not in serialized_timeline
            assert "raw_audio" not in serialized_timeline
        finally:
            await coordinator.close()

    run(scenario())


def replay_fixture(events: list[dict[str, Any]], suffix: str) -> dict[str, Any]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": f"replay_qfs_{suffix}",
            "source_trace_ref": f"fixture://qfs/{suffix}",
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


def test_canonical_journal_replays_deterministically_without_provider_rerun() -> None:
    async def capture() -> list[dict[str, Any]]:
        coordinator, _provider, sink = await make_coordinator(
            session_id="session_qfs_replay"
        )
        try:
            await run_scenario(coordinator, sink, "fast")
            return coordinator.journal.events()
        finally:
            await coordinator.close()

    events = run(capture())
    assert [event["event_seq"] for event in events] == list(
        range(1, len(events) + 1)
    )
    first = run_replay_fixture(replay_fixture(events, "fast"))
    second = run_replay_fixture(replay_fixture(events, "fast"))

    assert first.state_digest == second.state_digest
    assert first.ordered_events == second.ordered_events
    assert first.state_digest["overall_digest"]
