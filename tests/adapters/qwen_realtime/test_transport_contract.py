from __future__ import annotations

from collections import deque

import pytest

from voice_agent.adapters.qwen_realtime.protocol import (
    QwenClientEvent,
    QwenServerEvent,
    parse_server_event,
)
from voice_agent.adapters.qwen_realtime.transport import (
    QwenTransportClosedError,
    QwenTransportError,
    safe_transport_exception,
)

from tests.adapters.qwen_realtime.transport_contract_suite import (
    exercise_qwen_transport_contract,
)


class SpyQwenTransport:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.sent: list[QwenClientEvent] = []
        self._incoming: deque[QwenServerEvent] = deque()

    async def open(self) -> None:
        self.opened = True
        return None

    async def send(self, event: QwenClientEvent) -> None:
        assert self.opened and not self.closed
        self.sent.append(event)

    async def recv(self) -> QwenServerEvent:
        if self.closed:
            raise QwenTransportClosedError()
        if not self._incoming:
            raise AssertionError("driver must supply the next server event")
        return self._incoming.popleft()

    async def close(self) -> None:
        self.closed = True

    def supply(self, event: QwenServerEvent) -> None:
        assert self.opened and not self.closed
        self._incoming.append(event)


def _drive_spy(
    transport: SpyQwenTransport,
    expected_type: str,
) -> None:
    payloads: dict[str, dict[str, object]] = {
        "session.created": {
            "event_id": "evt_contract_created",
            "type": "session.created",
            "session": {"id": "sess_contract"},
        },
        "session.updated": {
            "event_id": "evt_contract_updated",
            "type": "session.updated",
            "session": {
                "id": "sess_contract",
                "turn_detection": {"type": "smart_turn"},
                "modalities": ["text", "audio"],
                "voice": "synthetic_voice",
                "input_audio_transcription": {"model": "synthetic_asr"},
                "tools": [],
                "fast_role_profile": "fast-role://synthetic/v1",
            },
        },
    }
    transport.supply(parse_server_event(payloads[expected_type]))


def test_spy_exercises_fake_real_shared_transport_contract() -> None:
    exercise_qwen_transport_contract(SpyQwenTransport, _drive_spy)


def test_transport_error_normalizes_arbitrary_code_without_leakage() -> None:
    error = QwenTransportError(
        "SENTINEL_ARBITRARY_CALLER_CODE",
        terminal=True,
    )
    assert error.code == "transport_failure"
    assert str(error) == "transport_failure"
    assert "SENTINEL_ARBITRARY_CALLER_CODE" not in repr(error)
    assert safe_transport_exception(error) == {
        "error_code": "transport_failure",
        "terminal": True,
    }
    assert "SENTINEL_ARBITRARY_CALLER_CODE" not in repr(
        safe_transport_exception(error)
    )


@pytest.mark.parametrize("bad_terminal", ["yes", 1, None])
def test_transport_error_rejects_non_bool_terminal_without_leakage(
    bad_terminal: object,
) -> None:
    with pytest.raises(ValueError) as caught:
        QwenTransportError(
            "transport_closed",
            terminal=bad_terminal,  # type: ignore[arg-type]
        )
    assert str(caught.value) == "invalid_transport_terminal"
    assert repr(bad_terminal) not in str(caught.value)
