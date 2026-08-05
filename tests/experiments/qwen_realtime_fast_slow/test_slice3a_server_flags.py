from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from experiments.qwen_realtime_fast_slow_web import server
from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeRealtimeProvider,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FakeShadowControlProvider,
)


def voice_factory() -> FakeRealtimeProvider:
    return FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))


def control_factory() -> FakeShadowControlProvider:
    return FakeShadowControlProvider()


def test_cli_accepts_only_explicit_qwen_enforced_text_only_mock_combination() -> None:
    parser = server._build_parser()
    enforced = parser.parse_args(
        [
            "--provider",
            "qwen",
            "--routing",
            "enforced",
            "--slow-runtime",
            "mock",
            "--audio-output",
            "none",
            "--shadow-control",
            "dual_session",
        ]
    )

    assert enforced.provider == "qwen"
    assert enforced.routing == "enforced"
    assert enforced.slow_runtime == "mock"
    assert enforced.audio_output == "none"
    assert enforced.shadow_control == "dual_session"


def test_app_factory_accepts_qwen_enforced_only_with_injected_dual_sessions() -> None:
    app = server.create_app(
        provider_mode="qwen",
        routing_mode="enforced",
        slow_runtime_mode="mock",
        audio_output="none",
        shadow_control_mode="dual_session",
        provider_factory=voice_factory,
        shadow_provider_factory=control_factory,
    )

    assert app["qfs.provider_mode"] == "qwen"
    assert app["qfs.routing_mode"] == "enforced"
    assert app["qfs.slow_runtime_mode"] == "mock"
    assert app["qfs.audio_output"] == "none"
    assert app["qfs.shadow_control_mode"] == "dual_session_enforced_control"


@pytest.mark.parametrize(
    ("audio_output", "error_code"),
    (
        (None, "qwen_enforced_provider_audio_unsupported"),
        ("qwen", "qwen_enforced_provider_audio_unsupported"),
        ("fake_pcm", "qwen_enforced_provider_audio_unsupported"),
    ),
)
def test_app_factory_rejects_any_qwen_enforced_audio_output(
    audio_output: str | None, error_code: str
) -> None:
    with pytest.raises(ValueError, match=error_code):
        server.create_app(
            provider_mode="qwen",
            routing_mode="enforced",
            slow_runtime_mode="mock",
            audio_output=audio_output,
            shadow_control_mode="dual_session",
            provider_factory=voice_factory,
            shadow_provider_factory=control_factory,
        )


def test_qwen_without_routing_keeps_shadow_default(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCredentials:
        @classmethod
        def resolve(cls, **_kwargs):
            return cls()

    def capture_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(server, "CredentialHandle", FakeCredentials)
    monkeypatch.setattr(server, "create_app", capture_create_app)
    monkeypatch.setattr(server.web, "run_app", lambda *_args, **_kwargs: None)

    assert server.main(["--provider", "qwen"]) == 0
    assert captured["provider_mode"] == "qwen"
    assert captured["routing_mode"] == "shadow"
    assert captured["audio_output"] == "qwen"
    assert captured["slow_runtime_mode"] == "mock"
    assert captured["shadow_control_mode"] == "dual_session"


@pytest.mark.parametrize(
    "argv",
    (
        ["--provider", "qwen", "--routing", "enforced"],
        [
            "--provider",
            "qwen",
            "--routing",
            "enforced",
            "--audio-output",
            "qwen",
        ],
        [
            "--provider",
            "qwen",
            "--routing",
            "enforced",
            "--audio-output",
            "fake_pcm",
        ],
    ),
)
def test_cli_rejects_qwen_enforced_unless_audio_none(
    argv: list[str], capsys
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        server.main(argv)
    assert exc_info.value.code == 2
    assert "qwen_enforced_provider_audio_unsupported" in capsys.readouterr().err


def test_enforced_health_projection_is_safe_and_explicit(monkeypatch) -> None:
    app = server.create_app(
        provider_mode="qwen",
        routing_mode="enforced",
        slow_runtime_mode="mock",
        audio_output="none",
        shadow_control_mode="dual_session",
        provider_factory=voice_factory,
        shadow_provider_factory=control_factory,
    )

    # The app-level configuration is the source for /healthz; asserting it
    # provider-free avoids requiring a loopback bind in restricted sandboxes.
    projected = {
        "provider_mode": app["qfs.provider_mode"],
        "routing_mode": app["qfs.routing_mode"],
        "slow_runtime_mode": app["qfs.slow_runtime_mode"],
        "audio_output": app["qfs.audio_output"],
        "control_topology": app["qfs.shadow_control_mode"],
    }
    serialized = json.dumps(projected, sort_keys=True).lower()

    assert projected == {
        "provider_mode": "qwen",
        "routing_mode": "enforced",
        "slow_runtime_mode": "mock",
        "audio_output": "none",
        "control_topology": "dual_session_enforced_control",
    }
    for forbidden in (
        "authorization",
        "bearer ",
        "api_key",
        "credential",
        "provider_payload",
    ):
        assert forbidden not in serialized


def test_slice3a1_not_executed_real_health_never_projects_ready_or_ok() -> None:
    async def scenario() -> None:
        app = server.create_app(
            provider_mode="qwen",
            routing_mode="enforced",
            slow_runtime_mode="mock",
            audio_output="none",
            shadow_control_mode="dual_session",
            provider_factory=voice_factory,
            shadow_provider_factory=control_factory,
        )
        response = await server._health_handler(SimpleNamespace(app=app))
        payload = json.loads(response.text)

        assert payload["status"] != "ok"
        assert payload["output_mode"] == "not_executed"
        assert payload["degraded"] is True
        assert payload["capabilities"]["health_status"] == "not_executed"
        assert payload["capabilities"]["verification_status"] == "not_executed"
        assert payload["capabilities"]["real_live_verified"] is False
        assert payload["shadow_capabilities"]["real_live_verified"] is False
        serialized = json.dumps(payload, sort_keys=True).lower()
        for forbidden in (
            "authorization",
            "bearer ",
            "api_key",
            "credential",
            "provider_payload",
            "raw_transcript",
        ):
            assert forbidden not in serialized

    asyncio.run(scenario())
