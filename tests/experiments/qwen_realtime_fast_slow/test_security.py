from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.qwen_realtime_fast_slow_web import live_shadow_smoke


REPO_ROOT = Path(__file__).resolve().parents[3]
SPIKE_ROOT = REPO_ROOT / "experiments" / "qwen_realtime_fast_slow_web"
TEST_ROOT = Path(__file__).parent


def test_spike_contains_no_raw_audio_trace_or_local_replay_artifacts() -> None:
    forbidden_suffixes = {
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".ogg",
        ".opus",
        ".pcm",
        ".raw",
        ".trace",
        ".wav",
        ".webm",
    }
    offenders = [
        path.relative_to(REPO_ROOT)
        for root in (SPIKE_ROOT, TEST_ROOT)
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]

    assert offenders == []
    assert not (SPIKE_ROOT / "traces").exists()
    assert not (SPIKE_ROOT / "replays" / "local").exists()
    assert not (SPIKE_ROOT / "audio" / "raw").exists()


def test_real_endpoint_and_secret_lookup_are_confined_to_backend_adapters() -> None:
    executable_files = [
        path
        for path in SPIKE_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".js", ".html"}
    ]
    sources = {
        path.relative_to(SPIKE_ROOT): path.read_text(encoding="utf-8")
        for path in executable_files
    }
    locations = {
        marker: {
            str(path)
            for path, source in sources.items()
            if marker in source
        }
        for marker in (
            "DASHSCOPE_API_KEY",
            "QWEN_REALTIME_WORKSPACE_ID",
            "wss://",
            "maas.aliyuncs.com",
            "api-ws/v1/realtime",
            "ClientSession(",
            ".ws_connect(",
        )
    }

    assert locations["DASHSCOPE_API_KEY"] == {"provider_context.py"}
    assert locations["QWEN_REALTIME_WORKSPACE_ID"] == {"provider_context.py"}
    for marker in ("wss://", "maas.aliyuncs.com", "api-ws/v1/realtime"):
        assert locations[marker] == {"provider_context.py"}
    # Slice 3A's contained Voice transport needs raw output-item correlation
    # for confirmed cancel/delete/rebuild.  Both outbound transports remain
    # backend adapters; endpoint and credential lookup stay provider_context-only.
    expected_transport_modules = {
        "qwen_shadow_router_adapter.py",
        "qwen_voice_adapter.py",
    }
    assert locations["ClientSession("] == expected_transport_modules
    assert locations[".ws_connect("] == expected_transport_modules


def test_browser_assets_have_no_provider_endpoint_or_credential_surface() -> None:
    static_root = SPIKE_ROOT / "static"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(static_root.rglob("*"))
        if path.is_file()
    )

    for forbidden in (
        "DASHSCOPE_API_KEY",
        "QWEN_REALTIME_WORKSPACE_ID",
        "Authorization",
        "Bearer ",
        "wss://",
        "maas.aliyuncs.com",
        "api-ws/v1/realtime",
    ):
        assert forbidden not in combined


def test_provider_modules_do_not_print_or_log_wire_payloads() -> None:
    provider_modules = (
        SPIKE_ROOT / "provider_context.py",
        SPIKE_ROOT / "qwen_voice_adapter.py",
        SPIKE_ROOT / "qwen_shadow_router_adapter.py",
    )
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in provider_modules
    )

    for forbidden in (
        "print(",
        "logging.",
        "logger.",
        "traceback.print",
        "set_trace(",
    ):
        assert forbidden not in combined


def test_main_runtime_does_not_import_the_isolated_experiment() -> None:
    marker = "qwen_realtime_fast_slow_web"
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in (REPO_ROOT / "src" / "voice_agent").rglob("*.py")
        if marker in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_repository_exclusions_cover_mandatory_local_artifacts() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    entries = {line.strip().lstrip("/") for line in gitignore if line.strip()}

    assert {
        "diagnostics/",
        "traces/",
        "replays/local/",
        "audio/raw/",
        ".env",
        ".env.*",
    } <= entries


def test_fake_controls_are_synthetic_scenario_ids_not_free_text_inputs() -> None:
    index = (SPIKE_ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'data-scenario="fast"' in index
    assert 'data-scenario="spawn"' in index
    assert 'data-scenario="patch"' in index
    assert 'data-scenario="ignore"' in index
    assert 'data-scenario="ambiguous"' in index
    assert "<textarea" not in index.lower()
    assert 'type="text"' not in index.lower()


def test_live_shadow_smoke_emits_only_safe_metadata(monkeypatch, capsys) -> None:
    secret = "PRIVATE_LIVE_SMOKE_CREDENTIAL_SENTINEL"
    candidate = "PRIVATE_LIVE_SMOKE_CANDIDATE_SENTINEL"

    class FakeCredentials:
        @classmethod
        def resolve(cls, **_kwargs):
            return cls()

        def __repr__(self) -> str:
            return secret

        def to_metadata(self) -> dict[str, object]:
            return {"configured": True, "workspace_ref": "workspace-safe-ref"}

    class FakeCounters:
        def to_metadata(self) -> dict[str, int]:
            return {"request_count": 1, "error_count": 0}

    class FakeResult:
        schema_valid = True
        proposal = SimpleNamespace(reply_candidate_text=candidate)
        output_mode = "real"
        latency = SimpleNamespace(function_call_done_to_result_ms=3.5)

        def to_safe_metadata(self) -> dict[str, object]:
            return {"output_mode": "real", "schema_valid": True}

    class FakeAdapter:
        def __init__(self, credentials) -> None:
            assert repr(credentials) == secret
            self.counters = FakeCounters()

        async def connect(self) -> None:
            return None

        async def analyze(self, request, *, timeout_seconds: float):
            assert request.transcript == live_shadow_smoke._SYNTHETIC_TRANSCRIPT
            assert timeout_seconds == 15.0
            return FakeResult()

        async def close(self) -> None:
            return None

    class FakeEvaluation:
        evaluation_latency_ms = 4.0

        def to_metadata(self) -> dict[str, object]:
            return {"local_route_decision": "SPAWN_SLOW_TASK"}

    class FakeEvaluator:
        def __init__(self, *, session_ref: str) -> None:
            assert session_ref == "live_shadow_smoke"

        def evaluate(self, **_kwargs):
            return FakeEvaluation()

    monkeypatch.setattr(live_shadow_smoke, "CredentialHandle", FakeCredentials)
    monkeypatch.setattr(live_shadow_smoke, "QwenShadowRouterAdapter", FakeAdapter)
    monkeypatch.setattr(live_shadow_smoke, "ShadowRouterEvaluator", FakeEvaluator)

    exit_code = asyncio.run(
        live_shadow_smoke._run(
            argparse.Namespace(
                workspace_id=None,
                qwen_base_url=None,
                verified_workspace_id=None,
                timeout=15.0,
            )
        )
    )
    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, sort_keys=True)

    assert exit_code == 0, payload
    assert payload["smoke_status"] == "executed_pass"
    assert payload["voice_audio_executed"] is False
    assert payload["topology"] == "dual_session_shadow_control_only"
    assert secret not in serialized
    assert candidate not in serialized
    assert live_shadow_smoke._SYNTHETIC_TRANSCRIPT not in serialized
