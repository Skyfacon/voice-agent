from __future__ import annotations

from typing import Protocol

from .protocol import QwenClientEvent, QwenServerEvent


_SAFE_TRANSPORT_ERROR_CODES = frozenset(
    {
        "connection_failed",
        "protocol_error",
        "receive_failed",
        "send_failed",
        "transport_closed",
        "transport_failure",
    }
)


def _safe_error_code(value: object) -> str:
    if isinstance(value, str) and value in _SAFE_TRANSPORT_ERROR_CODES:
        return value
    return "transport_failure"


class QwenTransportError(RuntimeError):
    """A transport failure whose public representation contains safe facts only."""

    def __init__(self, code: str, *, terminal: bool) -> None:
        if not isinstance(terminal, bool):
            raise ValueError("invalid_transport_terminal")
        safe_code = _safe_error_code(code)
        self.code = safe_code
        self.terminal = terminal
        super().__init__(safe_code)


class QwenTransportClosedError(QwenTransportError):
    def __init__(self) -> None:
        super().__init__("transport_closed", terminal=True)


def safe_transport_exception(error: BaseException) -> dict[str, object]:
    if isinstance(error, QwenTransportError):
        return {
            "error_code": _safe_error_code(error.code),
            "terminal": (
                error.terminal if isinstance(error.terminal, bool) else True
            ),
        }
    return {"error_code": "transport_failure", "terminal": True}


class QwenRealtimeTransport(Protocol):
    async def open(self) -> None: ...

    async def send(self, event: QwenClientEvent) -> None: ...

    async def recv(self) -> QwenServerEvent: ...

    async def close(self) -> None: ...


__all__ = [
    "QwenRealtimeTransport",
    "QwenTransportClosedError",
    "QwenTransportError",
    "safe_transport_exception",
]
