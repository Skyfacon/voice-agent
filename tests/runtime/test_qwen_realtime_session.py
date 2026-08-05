from __future__ import annotations

import asyncio

import pytest

from voice_agent.adapters.qwen_realtime.protocol import (
    QwenClientEvent,
    QwenServerEvent,
)
from voice_agent.interaction.controller import InteractionController
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.qwen_realtime_session import (
    QwenRealtimeSessionRuntime,
    QwenSessionRuntimeError,
)

from tests.qwen_slice3b1_support import parallel_journal


class LifecycleSpyAdapter:
    def __init__(self, observed: list[tuple[str, int]]) -> None:
        self.observed = observed
        self.generation = 0
        self.provider_context_state = "CLOSED"

    def fence_for_generation(self, *, generation: int, playback_epoch: int) -> None:
        self.generation = generation
        self.provider_context_state = "REBUILDING"
        self.observed.append(("fence", generation))

    async def stop_pump(self) -> None:
        self.observed.append(("stop", self.generation))
        return None

    async def attach_open_transport(self, transport: object) -> None:
        return None

    async def dispose_resources(self) -> None:
        return None


class LifecycleSpyTransport:
    def __init__(
        self,
        observed: list[tuple[str, int]],
        adapter: LifecycleSpyAdapter,
        *,
        fail_open: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.observed = observed
        self.adapter = adapter
        self.fail_open = fail_open
        self.fail_close = fail_close
        self.close_count = 0

    async def open(self) -> None:
        self.observed.append(("open", self.adapter.generation))
        if self.fail_open:
            raise OSError("synthetic open failure")

    async def send(self, event: QwenClientEvent) -> None:
        raise AssertionError("lifecycle test does not send")

    async def recv(self) -> QwenServerEvent:
        raise AssertionError("lifecycle test does not receive")

    async def close(self) -> None:
        self.close_count += 1
        self.observed.append(("close", self.adapter.generation))
        if self.fail_close:
            raise OSError("synthetic close failure")


def test_runtime_advances_generation_before_open_without_advancing_initial_epoch() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )

        generation = await runtime.connect()

        assert generation == 1
        assert observed[:3] == [("fence", 1), ("stop", 1), ("open", 1)]
        assert controller.current_epoch_snapshot().playback_epoch == 0
        assert controller.current_epoch_snapshot().interaction_state_version == 0

    asyncio.run(scenario())


def test_open_failure_keeps_advanced_generation_non_clean() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(
                observed, adapter, fail_open=True
            ),
            interaction_controller=InteractionController(parallel_journal()),
        )

        with pytest.raises(QwenSessionRuntimeError, match="open"):
            await runtime.connect()

        assert runtime.provider_session_generation == 1
        assert runtime.provider_context_state != "CLEAN"

    asyncio.run(scenario())


def test_open_failure_does_not_make_following_connect_look_connected() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        attempts = 0

        def transport_factory() -> LifecycleSpyTransport:
            nonlocal attempts
            attempts += 1
            return LifecycleSpyTransport(
                observed, adapter, fail_open=(attempts == 1)
            )

        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=transport_factory,
            interaction_controller=InteractionController(parallel_journal()),
        )
        with pytest.raises(QwenSessionRuntimeError, match="open"):
            await runtime.connect()

        assert await runtime.connect() == 2
        assert observed[-3:] == [("fence", 2), ("stop", 2), ("open", 2)]

    asyncio.run(scenario())


def test_failed_old_close_keeps_single_physical_handle_across_retry() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        transports: list[LifecycleSpyTransport] = []

        def factory() -> LifecycleSpyTransport:
            transport = LifecycleSpyTransport(
                observed,
                adapter,
                fail_close=(not transports),
            )
            transports.append(transport)
            return transport

        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=factory,
            interaction_controller=InteractionController(parallel_journal()),
        )
        assert await runtime.connect() == 1
        with pytest.raises(QwenSessionRuntimeError, match="close_failed"):
            await runtime.rebuild(reason="synthetic_close_failure")
        # Retry must retain or safely quarantine the unclosed physical handle;
        # it must not manufacture a second open transport behind its back.
        with pytest.raises(QwenSessionRuntimeError):
            await runtime.connect()
        assert len(transports) == 1
        assert transports[0].close_count >= 1

    asyncio.run(scenario())


def test_failed_open_cleanup_close_keeps_single_physical_handle_across_retry() -> None:
    class AttachFailureAdapter(LifecycleSpyAdapter):
        def __init__(self, observed: list[tuple[str, int]]) -> None:
            super().__init__(observed)
            self.attach_calls = 0

        async def attach_open_transport(
            self,
            transport: QwenRealtimeTransport,
        ) -> None:
            self.attach_calls += 1
            if self.attach_calls == 1:
                raise OSError("synthetic attach failure")

    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = AttachFailureAdapter(observed)
        transports: list[LifecycleSpyTransport] = []

        def factory() -> LifecycleSpyTransport:
            transport = LifecycleSpyTransport(
                observed,
                adapter,
                fail_close=(not transports),
            )
            transports.append(transport)
            return transport

        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=factory,
            interaction_controller=InteractionController(parallel_journal()),
        )
        with pytest.raises(QwenSessionRuntimeError, match="open_failed"):
            await runtime.connect()
        with pytest.raises(QwenSessionRuntimeError):
            await runtime.connect()
        assert len(transports) == 1
        assert transports[0].close_count >= 1

    asyncio.run(scenario())


def test_rebuild_advances_controller_epoch_before_fence_and_open() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )
        await runtime.connect()

        generation = await runtime.rebuild(reason="synthetic_rebuild")

        assert generation == 2
        assert controller.current_epoch_snapshot().playback_epoch == 1
        assert controller.current_epoch_snapshot().interaction_state_version == 1
        assert observed[-4:] == [
            ("fence", 2),
            ("stop", 2),
            ("close", 2),
            ("open", 2),
        ]
        rebuilding = [
            event
            for event in controller._journal.events()
            if event["event_name"] == "PROVIDER_CONTEXT_STATE_CHANGED"
            and event["to_state"] == "REBUILDING"
        ]
        assert rebuilding[-1]["provider_session_generation"] == 2
        assert rebuilding[-1]["playback_epoch"] == 1
        assert rebuilding[-1]["interaction_state_version"] == 1

    asyncio.run(scenario())


def test_rebuild_orders_epoch_then_journal_then_fence_before_old_close_and_open() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())
        original_append = controller.journal.append

        def recording_append(**kwargs: object) -> dict[str, object]:
            if kwargs["event_name"] == "PROVIDER_CONTEXT_STATE_CHANGED":
                observed.append(("journal", int(kwargs["provider_session_generation"])))
            return original_append(**kwargs)  # type: ignore[arg-type]

        controller.journal.append = recording_append  # type: ignore[method-assign]
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )
        await runtime.connect()
        observed.clear()

        await runtime.rebuild(reason="synthetic_rebuild")

        assert observed == [
            ("journal", 2),
            ("fence", 2),
            ("stop", 2),
            ("close", 2),
            ("open", 2),
        ]
        assert controller.current_epoch_snapshot().playback_epoch == 1

    asyncio.run(scenario())


def test_failed_rebuilding_append_does_not_fence_or_open() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())

        def failing_append(**kwargs: object) -> dict[str, object]:
            raise RuntimeError("synthetic append failure")

        controller.journal.append = failing_append  # type: ignore[method-assign]
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )

        with pytest.raises(RuntimeError, match="append failure"):
            await runtime.connect()
        assert runtime.provider_session_generation == 1
        assert observed == []

    asyncio.run(scenario())


def test_concurrent_rebuilds_coalesce_and_leave_one_active_handle() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        transports: list[LifecycleSpyTransport] = []

        def factory() -> LifecycleSpyTransport:
            transport = LifecycleSpyTransport(observed, adapter)
            transports.append(transport)
            return transport

        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=factory,
            interaction_controller=InteractionController(parallel_journal()),
        )
        assert await runtime.connect() == 1
        generations = await asyncio.gather(
            runtime.rebuild(reason="same_synthetic_rebuild"),
            runtime.rebuild(reason="same_synthetic_rebuild"),
            runtime.rebuild(reason="same_synthetic_rebuild"),
        )
        assert generations == [2, 2, 2]
        assert runtime.provider_session_generation == 2
        assert len(transports) == 2
        assert transports[0].close_count == 1
        assert transports[1].close_count == 0

    asyncio.run(scenario())


def test_close_is_logical_once_and_dispose_is_silent_idempotent() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )
        await runtime.connect()
        await runtime.close()
        event_count = len(controller.journal.events())
        await runtime.close()
        await runtime.dispose_resources()
        assert len(controller.journal.events()) == event_count
        closed = [
            event
            for event in controller.journal.events()
            if event["event_name"] == "PROVIDER_CONTEXT_STATE_CHANGED"
            and event["to_state"] == "CLOSED"
        ]
        assert len(closed) == 1
        assert runtime.provider_context_terminal_state == "CLOSED"

    asyncio.run(scenario())


def test_dispose_preserves_pre_cleanup_clean_terminal_snapshot() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )
        await runtime.connect()
        adapter.provider_context_state = "CLEAN"
        event_count = len(controller.journal.events())

        await runtime.dispose_resources()

        assert runtime.provider_context_terminal_state == "CLEAN"
        assert len(controller.journal.events()) == event_count

    asyncio.run(scenario())


def test_close_after_resource_disposal_is_silent_and_preserves_terminal_snapshot() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )
        await runtime.connect()
        adapter.provider_context_state = "CLEAN"
        await runtime.dispose_resources()
        event_count = len(controller.journal.events())

        await runtime.close()

        assert len(controller.journal.events()) == event_count
        assert runtime.provider_context_terminal_state == "CLEAN"

    asyncio.run(scenario())


def test_fresh_empty_journal_fails_closed_before_fence_or_open() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        journal = InMemoryEventJournal(
            session_id="session_empty_synthetic",
            conversation_id="conversation_empty_synthetic",
        )
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=InteractionController(journal),
        )

        with pytest.raises(QwenSessionRuntimeError, match="missing_session_root"):
            await runtime.connect()
        assert runtime.provider_session_generation == 1
        assert journal.events() == []
        assert observed == []

    asyncio.run(scenario())


def test_rebuild_and_close_journal_actual_adapter_clean_from_state() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        controller = InteractionController(parallel_journal())
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=controller,
        )
        await runtime.connect()
        adapter.provider_context_state = "CLEAN"

        await runtime.rebuild(reason="synthetic_after_clean")
        rebuilding = [
            event
            for event in controller.journal.events()
            if event["event_name"] == "PROVIDER_CONTEXT_STATE_CHANGED"
            and event["provider_session_generation"] == 2
        ][0]
        assert rebuilding["from_state"] == "CLEAN"

        adapter.provider_context_state = "CLEAN"
        await runtime.close()
        closed = [
            event
            for event in controller.journal.events()
            if event["event_name"] == "PROVIDER_CONTEXT_STATE_CHANGED"
            and event["to_state"] == "CLOSED"
        ][0]
        assert closed["from_state"] == "CLEAN"

    asyncio.run(scenario())
