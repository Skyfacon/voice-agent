from __future__ import annotations

import ast
from pathlib import Path

from voice_agent.adapters.qwen_realtime.scenarios import (
    ClientEventTemplate,
    QwenWireScript,
    ServerEventTemplate,
    SyntheticPayloadKind,
    WireStep,
    get_qwen_wire_script,
)
from voice_agent.adapters.qwen_realtime.scripted_wire import ScriptedFakeQwenWire
from voice_agent.adapters.qwen_realtime.protocol import (
    InputAudioBufferAppendClientEvent,
    QwenSessionConfiguration,
    SessionUpdateClientEvent,
)

import asyncio
import pytest


_MODULE_ROOT = Path(__file__).parents[3] / "src/voice_agent/adapters/qwen_realtime"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_fake_modules_do_not_import_clock_sleep_random_environment_or_network() -> None:
    imports = _imports(_MODULE_ROOT / "scenarios.py") | _imports(
        _MODULE_ROOT / "scripted_wire.py"
    )
    assert not imports & {
        "os",
        "pathlib",
        "random",
        "socket",
        "time",
        "urllib",
        "requests",
        "httpx",
        "websockets",
    }


def test_fake_scheduler_has_no_production_sleep_or_raw_audio_fixture() -> None:
    scenarios_source = (_MODULE_ROOT / "scenarios.py").read_text(encoding="utf-8")
    wire_source = (_MODULE_ROOT / "scripted_wire.py").read_text(encoding="utf-8")
    assert "asyncio.sleep" not in wire_source
    assert "base64" not in scenarios_source
    assert "credential" not in scenarios_source
    assert "prompt" not in scenarios_source
    assert "route.proposed" not in scenarios_source
    scenario_tree = ast.parse(scenarios_source)
    assert not any(
        isinstance(node, ast.Constant) and isinstance(node.value, bytes)
        for node in ast.walk(scenario_tree)
    )


def test_scenario_source_is_symbolic_and_contains_no_route_authority() -> None:
    script = get_qwen_wire_script("multiple_audio_appends_without_ack")
    assert script.fixture_domain == "GITHUB_ALLOWED"
    assert script.generated_from == "synthetic"
    assert script.scenario_source == "SYNTHETIC"
    for step in script.steps:
        template = step.event_template
        assert template.payload_kind in SyntheticPayloadKind
        assert not hasattr(template, "route")
        assert not hasattr(template, "turn_id")
        assert not hasattr(template, "utterance_id")
        assert not hasattr(template, "playback_epoch")


def test_safe_timeline_is_metadata_only_and_mock_labeled() -> None:
    script = get_qwen_wire_script("multiple_audio_appends_without_ack")
    rendered = repr(script)
    assert "route.proposed" not in rendered
    assert "base64" not in rendered
    assert "pcm=" not in rendered


@pytest.mark.parametrize(
    "unsafe_ref",
    (
        "Bearer_secret",
        "person@example.com",
        "/Users/person/file",
        "file:///tmp/data",
        "opaque?query=1",
        "opaque#fragment",
        "has space",
        "x" * 65,
    ),
)
def test_direct_template_construction_rejects_unsafe_refs_without_echo(
    unsafe_ref: str,
) -> None:
    with pytest.raises(ValueError) as caught:
        ServerEventTemplate(
            event_type="session.created",
            payload_kind=SyntheticPayloadKind.SESSION_DEFAULTS,
            event_id=unsafe_ref,
            session_id="sess_fake_001",
        )
    assert unsafe_ref not in str(caught.value)
    assert unsafe_ref not in repr(caught.value)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: WireStep(
            wire_seq=0,
            virtual_ms=0,
            direction="sideways",  # type: ignore[arg-type]
            event_template=ClientEventTemplate(event_type="session.update"),
        ),
        lambda: ServerEventTemplate(
            event_type="session.created",
            payload_kind=SyntheticPayloadKind.PCM_FRAME,
            event_id="evt_fake_001",
            session_id="sess_fake_001",
        ),
        lambda: ServerEventTemplate(
            event_type="response.audio.delta",
            payload_kind=SyntheticPayloadKind.PCM_FRAME,
            event_id="evt_fake_001",
            response_id="resp_fake_001",
            item_id="item_fake_001",
            output_index=0,
            content_index=0,
            byte_count=-1,
        ),
        lambda: QwenWireScript(
            scenario_id="bad provenance",
            steps=(
                WireStep(
                    wire_seq=0,
                    virtual_ms=0,
                    direction="client",
                    event_template=ClientEventTemplate(event_type="session.update"),
                ),
            ),
        ),
        lambda: QwenWireScript(
            scenario_id="script_fake_001",
            steps=[
                WireStep(
                    wire_seq=1,
                    virtual_ms=1,
                    direction="client",
                    event_template=ClientEventTemplate(event_type="session.update"),
                ),
                WireStep(
                    wire_seq=1,
                    virtual_ms=0,
                    direction="client",
                    event_template=ClientEventTemplate(event_type="response.cancel"),
                ),
            ],  # type: ignore[arg-type]
            fixture_domain="LOCAL_ONLY",  # type: ignore[arg-type]
        ),
    ),
)
def test_invalid_script_construction_fails_closed(factory: object) -> None:
    assert callable(factory)
    with pytest.raises(ValueError):
        factory()


def test_list_backing_cannot_mutate_constructed_script_or_wire() -> None:
    steps = [
        WireStep(
            wire_seq=0,
            virtual_ms=0,
            direction="client",
            event_template=ClientEventTemplate(event_type="session.update"),
        )
    ]
    script = QwenWireScript(scenario_id="script_fake_001", steps=steps)  # type: ignore[arg-type]
    wire = ScriptedFakeQwenWire(script)
    steps.clear()
    assert len(script.steps) == 1
    assert len(wire._script.steps) == 1


def test_safe_timeline_uses_only_allowlisted_metadata_and_hides_pcm_sentinel() -> None:
    configuration = QwenSessionConfiguration(
        turn_detection_type="smart_turn",
        modalities=("text", "audio"),
        voice="synthetic_voice",
        input_audio_transcription=(("model", "synthetic_asr"),),
        tools=(),
        fast_role_profile="fast-role://synthetic/v1",
    )

    async def scenario() -> tuple[dict[str, object], ...]:
        wire = ScriptedFakeQwenWire(
            get_qwen_wire_script("multiple_audio_appends_without_ack")
        )
        await wire.open()
        wire.release_next_server_event()
        await wire.recv()
        await wire.send(SessionUpdateClientEvent(configuration=configuration))
        wire.release_next_server_event()
        await wire.recv()
        await wire.send(
            InputAudioBufferAppendClientEvent(
                pcm16le=bytearray(b"TIMELINE_SECRET_SENTINEL")
            )
        )
        await wire.send(
            InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x00\x00"))
        )
        return wire.safe_timeline()

    timeline = asyncio.run(scenario())
    allowed = {
        "wire_seq", "virtual_ms", "direction", "output_mode", "type",
        "provider_event_id_ref", "provider_session_ref", "qwen_response_id",
        "qwen_item_ref", "previous_qwen_item_ref", "qwen_output_index",
        "qwen_content_index", "terminal_status", "terminal_reason",
        "byte_count", "duration_ms",
    }
    assert all(set(row) <= allowed and row["output_mode"] == "mock" for row in timeline)
    assert "TIMELINE_SECRET_SENTINEL" not in repr(timeline)
