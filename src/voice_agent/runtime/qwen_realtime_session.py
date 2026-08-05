from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from voice_agent.adapters.qwen_realtime.transport import QwenRealtimeTransport
from voice_agent.interaction.controller import (
    InteractionController,
    InteractionEpochSnapshot,
)


class QwenSessionRuntimeError(RuntimeError):
    """A bounded failure from the local Qwen session lifecycle."""


class _GenerationFencedAdapter(Protocol):
    provider_context_state: str

    def fence_for_generation(self, *, generation: int, playback_epoch: int) -> None: ...

    async def stop_pump(self) -> None: ...

    async def attach_open_transport(self, transport: QwenRealtimeTransport) -> None: ...


class QwenRealtimeSessionRuntime:
    """Serializes physical-transport replacement around controller-owned epochs."""

    def __init__(
        self,
        *,
        adapter: _GenerationFencedAdapter,
        transport_factory: Callable[[], QwenRealtimeTransport],
        interaction_controller: InteractionController,
        adapter_id: str = "qwen_realtime_adapter",
    ) -> None:
        self._adapter = adapter
        self._transport_factory = transport_factory
        self._interaction_controller = interaction_controller
        self._adapter_id = adapter_id
        self._generation = 0
        self._provider_context_state = "CLOSED"
        self._active_transport: QwenRealtimeTransport | None = None
        self._transport_close_uncertain = False
        self._lifecycle_lock = asyncio.Lock()
        self._rebuild_coalesce_lock = asyncio.Lock()
        self._inflight_rebuild: asyncio.Task[int] | None = None
        self._disposed = False
        self._transition_index = 0
        self._terminal_state_snapshot: str | None = None

    @property
    def provider_session_generation(self) -> int:
        return self._generation

    @property
    def provider_context_state(self) -> str:
        if self._provider_context_state == "CLOSED":
            return "CLOSED"
        return self._adapter.provider_context_state

    @property
    def provider_context_terminal_state(self) -> str:
        if self._terminal_state_snapshot is not None:
            return self._terminal_state_snapshot
        return self.provider_context_state

    async def connect(self) -> int:
        async with self._lifecycle_lock:
            if self._disposed:
                raise QwenSessionRuntimeError("runtime_disposed")
            if self._transport_close_uncertain:
                raise QwenSessionRuntimeError("possibly_live_transport")
            if self._active_transport is not None:
                return self._generation
            return await self._replace_transport(reason="connect", is_rebuild=False)

    async def rebuild(self, *, reason: str) -> int:
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a non-empty string")
        async with self._rebuild_coalesce_lock:
            task = self._inflight_rebuild
            if task is None or task.done():
                task = asyncio.create_task(self._run_rebuild(reason))
                self._inflight_rebuild = task
        try:
            return await asyncio.shield(task)
        finally:
            async with self._rebuild_coalesce_lock:
                if self._inflight_rebuild is task and task.done():
                    self._inflight_rebuild = None

    async def _run_rebuild(self, reason: str) -> int:
        async with self._lifecycle_lock:
            if self._disposed:
                raise QwenSessionRuntimeError("runtime_disposed")
            if self._transport_close_uncertain:
                raise QwenSessionRuntimeError("possibly_live_transport")
            return await self._replace_transport(reason=reason, is_rebuild=True)

    async def _replace_transport(self, *, reason: str, is_rebuild: bool) -> int:
        self._generation += 1
        generation = self._generation
        previous = self._interaction_controller.current_epoch_snapshot()
        epoch = (
            self._interaction_controller.advance_playback_epoch_for_provider_rebuild(
                provider_session_generation=generation,
                reason=reason,
            )
            if is_rebuild
            else previous
        )
        if is_rebuild and (
            epoch.playback_epoch <= previous.playback_epoch
            or epoch.interaction_state_version <= previous.interaction_state_version
        ):
            raise QwenSessionRuntimeError("playback_epoch_did_not_advance")

        # This transition, fence, and controller epoch mutation intentionally
        # have no await boundary between them.
        self._append_provider_rebuilding(
            generation=generation,
            epoch=epoch,
            reason=reason,
        )
        self._adapter.fence_for_generation(
            generation=generation,
            playback_epoch=epoch.playback_epoch,
        )

        await self._adapter.stop_pump()
        old_transport = self._active_transport
        if old_transport is not None:
            try:
                await old_transport.close()
            except Exception as exc:
                self._transport_close_uncertain = True
                raise QwenSessionRuntimeError("close_failed") from exc
            if self._active_transport is old_transport:
                self._active_transport = None

        transport = self._transport_factory()
        self._active_transport = transport
        try:
            await transport.open()
            await self._adapter.attach_open_transport(transport)
        except Exception as exc:
            try:
                await transport.close()
            except Exception:
                self._transport_close_uncertain = True
            else:
                if self._active_transport is transport:
                    self._active_transport = None
            raise QwenSessionRuntimeError("open_failed") from exc
        return generation

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._disposed:
                return
            if self._provider_context_state != "CLOSED":
                self._append_provider_closed(reason="logical_close")
            await self._dispose_resources_locked()

    async def dispose_resources(self) -> None:
        async with self._lifecycle_lock:
            await self._dispose_resources_locked()

    async def _dispose_resources_locked(self) -> None:
        if self._disposed:
            return
        self._terminal_state_snapshot = self.provider_context_state
        self._disposed = True
        await self._adapter.stop_pump()
        transport = self._active_transport
        if transport is not None:
            try:
                await transport.close()
            except Exception:
                self._transport_close_uncertain = True
            else:
                if self._active_transport is transport:
                    self._active_transport = None
        dispose = getattr(self._adapter, "dispose_resources", None)
        if dispose is not None:
            result = dispose()
            if hasattr(result, "__await__"):
                await result

    def _append_provider_rebuilding(
        self,
        *,
        generation: int,
        epoch: InteractionEpochSnapshot,
        reason: str,
    ) -> None:
        self._append_provider_transition(
            to_state="REBUILDING",
            generation=generation,
            reason=reason,
            epoch=epoch,
        )

    def _append_provider_closed(self, *, reason: str) -> None:
        self._append_provider_transition(
            to_state="CLOSED",
            generation=self._generation,
            reason=reason,
            epoch=None,
        )

    def _append_provider_transition(
        self,
        *,
        to_state: str,
        generation: int,
        reason: str,
        epoch: InteractionEpochSnapshot | None,
    ) -> None:
        self._transition_index += 1
        from_state = self.provider_context_state
        fields: dict[str, object] = {
            "adapter_id": self._adapter_id,
            "provider_session_generation": generation,
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            "source_event_ids": (),
            "output_mode": "mock",
        }
        if to_state == "REBUILDING":
            assert epoch is not None
            fields["playback_epoch"] = epoch.playback_epoch
            fields["interaction_state_version"] = epoch.interaction_state_version
        prior_events = self._interaction_controller.journal.events()
        if not prior_events:
            raise QwenSessionRuntimeError("missing_session_root")
        append_arguments: dict[str, object] = {
            "event_name": "PROVIDER_CONTEXT_STATE_CHANGED",
            "event_id": (
                f"evt_qwen_provider_context_{generation}_{self._transition_index}"
            ),
            "source_module": "qwen_realtime_session_runtime",
            "created_monotonic_ms": self._transition_index,
            "created_wall_clock_ms": (
                1_700_000_000_000 + self._transition_index
            ),
            "trace_redaction_level": "metadata_only",
            **fields,
        }
        append_arguments["caused_by_event_id"] = str(
            prior_events[-1]["event_id"]
        )
        self._interaction_controller.journal.append(
            **append_arguments,
        )
        self._provider_context_state = to_state


__all__ = ["QwenRealtimeSessionRuntime", "QwenSessionRuntimeError"]
