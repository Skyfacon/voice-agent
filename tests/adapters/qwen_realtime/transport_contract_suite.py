from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from voice_agent.adapters.qwen_realtime.protocol import (
    ConversationItemDeleteClientEvent,
    InputAudioBufferAppendClientEvent,
    QwenServerEvent,
    QwenSessionConfiguration,
    ResponseCancelClientEvent,
    SessionUpdateClientEvent,
)
from voice_agent.adapters.qwen_realtime.transport import (
    QwenRealtimeTransport,
    QwenTransportClosedError,
    safe_transport_exception,
)


TransportFactory = Callable[[], QwenRealtimeTransport]
TransportDriver = Callable[
    [QwenRealtimeTransport, str],
    Awaitable[None] | None,
]

CONTRACT_CONFIGURATION = QwenSessionConfiguration(
    turn_detection_type="smart_turn",
    modalities=("text", "audio"),
    voice="synthetic_voice",
    input_audio_transcription=(("model", "synthetic_asr"),),
    tools=(),
    fast_role_profile="fast-role://synthetic/v1",
)


def exercise_qwen_transport_contract(
    factory: TransportFactory,
    driver: TransportDriver,
) -> None:
    """Exercise behavior shared unchanged by Spy, Fake, and Real transports."""

    async def drive(
        transport: QwenRealtimeTransport,
        expected_type: str,
    ) -> None:
        result = driver(transport, expected_type)
        if inspect.isawaitable(result):
            await result

    async def scenario() -> None:
        transport = factory()
        assert await transport.open() is None

        await drive(transport, "session.created")
        created = await transport.recv()
        assert isinstance(created, QwenServerEvent)
        assert created.type == "session.created"

        await transport.send(
            SessionUpdateClientEvent(configuration=CONTRACT_CONFIGURATION)
        )
        await drive(transport, "session.updated")
        updated = await transport.recv()
        assert isinstance(updated, QwenServerEvent)
        assert updated.type == "session.updated"

        allowed = (
            InputAudioBufferAppendClientEvent(
                pcm16le=bytearray(b"\x13\x37")
            ),
            ResponseCancelClientEvent(),
            ConversationItemDeleteClientEvent(item_id="output_item_1"),
        )
        for event in allowed:
            assert await transport.send(event) is None

        assert await transport.close() is None
        try:
            await transport.recv()
        except QwenTransportClosedError as error:
            assert safe_transport_exception(error) == {
                "error_code": "transport_closed",
                "terminal": True,
            }
            assert "1337" not in repr(error)
        else:
            raise AssertionError("recv() after close must fail terminally")

    asyncio.run(scenario())
