from __future__ import annotations

import asyncio
from collections import deque

from .protocol import (
    ConversationItemDeleteClientEvent,
    InputAudioBufferAppendClientEvent,
    QwenClientEvent,
    QwenProtocolError,
    QwenServerEvent,
    ResponseAudioDeltaServerEvent,
    ResponseAudioTranscriptDeltaServerEvent,
    ResponseCancelClientEvent,
    ResponseDoneServerEvent,
    SessionCreatedServerEvent,
    SessionUpdateClientEvent,
    SessionUpdatedServerEvent,
    safe_wire_metadata,
)
from .scenarios import (
    ClientEventTemplate,
    QwenWireScript,
    ServerEventTemplate,
    SyntheticPayloadKind,
    WireStep,
)
from .transport import (
    QwenRealtimeTransport,
    QwenTransportClosedError,
    QwenTransportError,
)


class ScriptedFakeQwenWire(QwenRealtimeTransport):
    """Provider-free, permit-driven implementation of the shared wire contract."""

    def __init__(self, script: QwenWireScript) -> None:
        self._script = script
        self._step_index = 0
        self._opened = False
        self._closed = False
        self._virtual_ms = 0
        self._configuration = None
        self._queued: deque[tuple[WireStep, QwenServerEvent]] = deque()
        self._wake = asyncio.Event()
        self._timeline: list[dict[str, object]] = []

    async def open(self) -> None:
        if self._closed or self._opened:
            raise QwenTransportError("transport_failure", terminal=True)
        self._opened = True

    async def send(self, event: QwenClientEvent) -> None:
        self._ensure_open()
        step = self._current_client_step()
        self._match_client_template(step.event_template, event)
        row = self._timeline_row(step, event)
        if isinstance(event, SessionUpdateClientEvent):
            self._configuration = event.configuration
        self._timeline.append(row)
        self._step_index += 1

    async def recv(self) -> QwenServerEvent:
        self._ensure_open()
        while True:
            if self._closed:
                raise QwenTransportClosedError()
            if self._queued:
                _, event = self._queued.popleft()
                return event
            self._wake.clear()
            await self._wake.wait()

    async def close(self) -> None:
        if self._closed:
            return None
        self._closed = True
        while self._queued:
            _, event = self._queued.popleft()
            if isinstance(event, ResponseAudioDeltaServerEvent):
                event.pcm[:] = bytearray(len(event.pcm))
        self._wake.set()

    def release_next_server_event(self) -> int:
        self._ensure_open()
        if self._step_index >= len(self._script.steps):
            raise QwenTransportError("protocol_error", terminal=False)
        step = self._script.steps[self._step_index]
        if step.direction != "server":
            raise QwenTransportError("protocol_error", terminal=False)
        template = step.event_template
        assert isinstance(template, ServerEventTemplate)
        if (
            template.event_type == "session.updated"
            and self._configuration is None
        ):
            raise QwenTransportError("protocol_error", terminal=False)
        try:
            event = self._materialize(template)
            row = self._timeline_row(step, event)
        except QwenProtocolError as error:
            raise QwenTransportError("protocol_error", terminal=False) from error
        self._queued.append((step, event))
        self._timeline.append(row)
        self._step_index += 1
        self._virtual_ms = step.virtual_ms
        self._wake.set()
        return self._virtual_ms

    def safe_timeline(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(row) for row in self._timeline)

    def _ensure_open(self) -> None:
        if self._closed:
            raise QwenTransportClosedError()
        if not self._opened:
            raise QwenTransportError("transport_failure", terminal=True)

    def _current_client_step(self) -> WireStep:
        if self._step_index >= len(self._script.steps):
            raise QwenTransportError("protocol_error", terminal=False)
        step = self._script.steps[self._step_index]
        if step.direction != "client":
            raise QwenTransportError("protocol_error", terminal=False)
        return step

    @staticmethod
    def _match_client_template(
        template: ClientEventTemplate | ServerEventTemplate,
        event: QwenClientEvent,
    ) -> None:
        if not isinstance(template, ClientEventTemplate):
            raise QwenTransportError("protocol_error", terminal=False)
        if event.type != template.event_type:
            raise QwenTransportError("protocol_error", terminal=False)
        if template.item_id is not None:
            if not isinstance(event, ConversationItemDeleteClientEvent):
                raise QwenTransportError("protocol_error", terminal=False)
            if event.item_id != template.item_id:
                raise QwenTransportError("protocol_error", terminal=False)

    def _materialize(self, template: ServerEventTemplate) -> QwenServerEvent:
        if template.event_type == "session.created":
            return SessionCreatedServerEvent(
                event_id=template.event_id,
                session_id=self._required(template.session_id),
            )
        if template.event_type == "session.updated":
            if self._configuration is None:
                raise QwenTransportError("protocol_error", terminal=False)
            return SessionUpdatedServerEvent(
                event_id=template.event_id,
                session_id=self._required(template.session_id),
                configuration=self._configuration,
            )
        if template.event_type == "response.audio.delta":
            return ResponseAudioDeltaServerEvent(
                event_id=template.event_id,
                response_id=self._required(template.response_id),
                item_id=self._required(template.item_id),
                output_index=self._required_index(template.output_index),
                content_index=self._required_index(template.content_index),
                pcm=bytearray(template.byte_count),
            )
        if template.event_type == "response.audio_transcript.delta":
            return ResponseAudioTranscriptDeltaServerEvent(
                event_id=template.event_id,
                response_id=self._required(template.response_id),
                item_id=self._required(template.item_id),
                output_index=self._required_index(template.output_index),
                content_index=self._required_index(template.content_index),
                delta=self._synthetic_transcript(template.payload_kind),
            )
        if template.event_type == "response.done":
            return ResponseDoneServerEvent(
                event_id=template.event_id,
                response_id=self._required(template.response_id),
                terminal_status=template.terminal_status or "completed",
            )
        raise QwenTransportError("protocol_error", terminal=False)

    @staticmethod
    def _synthetic_transcript(kind: SyntheticPayloadKind) -> str:
        if kind is SyntheticPayloadKind.TRANSCRIPT_FRAGMENT:
            return "synthetic-fragment"
        return ""

    @staticmethod
    def _required(value: str | None) -> str:
        if value is None:
            raise QwenTransportError("protocol_error", terminal=False)
        return value

    @staticmethod
    def _required_index(value: int | None) -> int:
        if value is None:
            raise QwenTransportError("protocol_error", terminal=False)
        return value

    def _timeline_row(
        self,
        step: WireStep,
        event: QwenClientEvent | QwenServerEvent,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "wire_seq": step.wire_seq,
            "virtual_ms": step.virtual_ms,
            "direction": step.direction,
            "output_mode": "mock",
        }
        row.update(safe_wire_metadata(event))
        template = step.event_template
        if isinstance(template, ServerEventTemplate) and template.duration_ms:
            row["duration_ms"] = template.duration_ms
        return row


__all__ = ["ScriptedFakeQwenWire"]
