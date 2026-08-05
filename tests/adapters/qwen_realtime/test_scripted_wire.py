from __future__ import annotations

import asyncio

import pytest

from voice_agent.adapters.qwen_realtime.protocol import (
    InputAudioBufferAppendClientEvent,
    QwenSessionConfiguration,
    ResponseCancelClientEvent,
    SessionUpdateClientEvent,
)
from voice_agent.adapters.qwen_realtime.scripted_wire import (
    ScriptedFakeQwenWire,
)
from voice_agent.adapters.qwen_realtime.scenarios import (
    QwenWireScript,
    ServerEventTemplate,
    SyntheticPayloadKind,
    WireStep,
    get_qwen_wire_script,
)
from voice_agent.adapters.qwen_realtime.transport import (
    QwenTransportClosedError,
    QwenTransportError,
)

from tests.adapters.qwen_realtime.transport_contract_suite import (
    exercise_qwen_transport_contract,
)


TEST_CONFIGURATION = QwenSessionConfiguration(
    turn_detection_type="smart_turn",
    modalities=("text", "audio"),
    voice="synthetic_voice",
    input_audio_transcription=(("model", "synthetic_asr"),),
    tools=(),
    fast_role_profile="fast-role://synthetic/v1",
)


async def opened_ready_wire(scenario_id: str) -> ScriptedFakeQwenWire:
    wire = ScriptedFakeQwenWire(get_qwen_wire_script(scenario_id))
    await wire.open()
    wire.release_next_server_event()
    created = await wire.recv()
    assert created.type == "session.created"
    await wire.send(SessionUpdateClientEvent(configuration=TEST_CONFIGURATION))
    wire.release_next_server_event()
    updated = await wire.recv()
    assert updated.type == "session.updated"
    return wire


def test_open_then_recv_yields_session_created_only_after_release() -> None:
    async def scenario() -> None:
        wire = ScriptedFakeQwenWire(
            get_qwen_wire_script("bootstrap_requires_session_update")
        )
        assert await wire.open() is None
        recv_task = asyncio.create_task(wire.recv())
        await asyncio.sleep(0)
        assert not recv_task.done()
        assert wire.release_next_server_event() == 0
        assert (await recv_task).type == "session.created"

    asyncio.run(scenario())


def test_multiple_audio_appends_have_no_per_frame_ack() -> None:
    async def scenario() -> None:
        wire = await opened_ready_wire("multiple_audio_appends_without_ack")
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x00\x00"))
        )
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x01\x00"))
        )
        assert [row["direction"] for row in wire.safe_timeline()][-2:] == [
            "client",
            "client",
        ]

    asyncio.run(scenario())


def test_wrong_client_type_does_not_advance_repeatable_append_state() -> None:
    async def scenario() -> None:
        wire = await opened_ready_wire("multiple_audio_appends_without_ack")
        before_index = wire._step_index
        before_timeline = wire.safe_timeline()
        with pytest.raises(QwenTransportError) as caught:
            await wire.send(ResponseCancelClientEvent())
        assert caught.value.code == "protocol_error"
        assert wire._step_index == before_index
        assert wire.safe_timeline() == before_timeline
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x00\x00"))
        )
        assert wire._step_index == before_index + 1

    asyncio.run(scenario())


def test_each_actual_append_has_a_unique_increasing_wire_sequence() -> None:
    async def scenario() -> None:
        wire = await opened_ready_wire("multiple_audio_appends_without_ack")
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x00\x00"))
        )
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x01\x00"))
        )
        append_rows = [
            row
            for row in wire.safe_timeline()
            if row["type"] == "input_audio_buffer.append"
        ]
        assert [row["wire_seq"] for row in append_rows] == [3, 4]

    asyncio.run(scenario())


def test_fake_exercises_shared_qwen_transport_contract() -> None:
    def driver(transport: ScriptedFakeQwenWire, expected_type: str) -> None:
        assert expected_type in {"session.created", "session.updated"}
        transport.release_next_server_event()

    exercise_qwen_transport_contract(
        lambda: ScriptedFakeQwenWire(
            get_qwen_wire_script("transport_contract_client_sequence")
        ),
        driver,
    )


def test_send_requires_the_next_scripted_client_step() -> None:
    async def scenario() -> None:
        wire = ScriptedFakeQwenWire(
            get_qwen_wire_script("bootstrap_requires_session_update")
        )
        await wire.open()
        with pytest.raises(QwenTransportError) as caught:
            await wire.send(ResponseCancelClientEvent())
        assert caught.value.code == "protocol_error"

    asyncio.run(scenario())


def test_session_updated_cannot_release_before_matching_client_update() -> None:
    async def scenario() -> None:
        wire = ScriptedFakeQwenWire(
            get_qwen_wire_script("bootstrap_requires_session_update")
        )
        await wire.open()
        wire.release_next_server_event()
        assert (await wire.recv()).type == "session.created"
        with pytest.raises(QwenTransportError) as caught:
            wire.release_next_server_event()
        assert caught.value.code == "protocol_error"

    asyncio.run(scenario())


def test_repeated_runs_have_identical_safe_timelines() -> None:
    async def run_once() -> tuple[dict[str, object], ...]:
        wire = await opened_ready_wire("multiple_audio_appends_without_ack")
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x00\x00"))
        )
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x01\x00"))
        )
        return wire.safe_timeline()

    assert asyncio.run(run_once()) == asyncio.run(run_once())


def test_close_wakes_blocked_recv_with_typed_terminal_error() -> None:
    async def scenario() -> None:
        wire = ScriptedFakeQwenWire(
            get_qwen_wire_script("bootstrap_requires_session_update")
        )
        await wire.open()
        recv_task = asyncio.create_task(wire.recv())
        await asyncio.sleep(0)
        await wire.close()
        with pytest.raises(QwenTransportClosedError):
            await recv_task

    asyncio.run(scenario())


def test_materialization_failure_does_not_partially_advance_wire_state() -> None:
    async def scenario() -> None:
        broken_step = WireStep(
            wire_seq=0,
            virtual_ms=7,
            direction="server",
            event_template=ServerEventTemplate(
                event_type="session.created",
                payload_kind=SyntheticPayloadKind.SESSION_DEFAULTS,
                event_id="evt_fake_001",
                session_id="sess_fake_001",
            ),
        )
        object.__setattr__(broken_step.event_template, "session_id", None)
        broken = QwenWireScript(
            scenario_id="broken_materializer",
            steps=(broken_step,),
        )
        wire = ScriptedFakeQwenWire(broken)
        await wire.open()
        before = (wire._step_index, wire._virtual_ms, tuple(wire._queued))
        with pytest.raises(QwenTransportError) as caught:
            wire.release_next_server_event()
        assert caught.value.code == "protocol_error"
        assert (wire._step_index, wire._virtual_ms, tuple(wire._queued)) == before
        assert wire.safe_timeline() == ()

    asyncio.run(scenario())
