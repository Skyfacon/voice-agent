from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from experiments.qwen_audio_realtime_web.capability_profile import (
    fake_capability_profile,
    qwen_capability_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_ROOT = REPO_ROOT / "experiments" / "qwen_audio_realtime_web"
REPORT = (
    REPO_ROOT
    / "docs"
    / "research"
    / "spikes"
    / "qwen-audio-realtime-2026-07-15.md"
)


def test_capability_profiles_distinguish_real_mock_and_degraded() -> None:
    fake = fake_capability_profile()
    real = qwen_capability_profile()
    degraded = replace(real, health_status="degraded", output_mode="degraded")

    assert (fake.output_mode, fake.mocked, fake.health_status) == (
        "mock",
        True,
        "ready",
    )
    assert (real.output_mode, real.mocked, real.health_status) == (
        "real",
        False,
        "not_executed",
    )
    assert (degraded.output_mode, degraded.mocked, degraded.health_status) == (
        "degraded",
        False,
        "degraded",
    )
    assert len({fake.adapter_id, real.adapter_id}) == 2


def test_capability_metadata_is_json_safe_and_contains_no_credential_fields(
    monkeypatch,
) -> None:
    sentinel = "DO_NOT_SERIALIZE_CREDENTIAL"
    monkeypatch.setenv("DASHSCOPE_API_KEY", sentinel)
    monkeypatch.setenv("QWEN_REALTIME_WORKSPACE_ID", "workspace-private-sentinel")

    for profile in (fake_capability_profile(), qwen_capability_profile()):
        metadata = profile.to_metadata()
        serialized = json.dumps(metadata, sort_keys=True)

        assert json.loads(serialized) == metadata
        assert sentinel not in serialized
        assert "workspace-private-sentinel" not in serialized
        assert "authorization" not in serialized.lower()
        assert "api_key" not in serialized.lower()
        assert "credential" not in metadata
        assert set(metadata) >= {
            "adapter_id",
            "adapter_type",
            "provider",
            "model_name",
            "deployment_mode",
            "endpoint_ref",
            "health_status",
            "capability_version",
            "latency_class",
            "error_model",
            "timeout_policy",
            "retry_policy",
            "output_mode",
        }


def test_capability_profiles_do_not_overclaim_adr003_truncate_or_aec() -> None:
    for profile in (fake_capability_profile(), qwen_capability_profile()):
        assert profile.supports_provider_response_cancel is True
        assert profile.supports_local_playback_clear is True
        assert profile.supports_playback_epoch is True
        assert profile.supports_tts_truncate is False
        assert profile.supports_playback_reference_aec is False


def test_qwen_profile_uses_safe_endpoint_reference_and_disables_tools() -> None:
    profile = qwen_capability_profile()

    assert profile.model_name == "qwen-audio-3.0-realtime-plus"
    assert profile.endpoint_ref == "aliyun-bailian/cn-beijing/realtime"
    assert "wss://" not in profile.endpoint_ref
    assert "?" not in profile.endpoint_ref
    assert profile.tools_enabled is False
    assert profile.supports_tool_calling is False
    assert profile.turn_detection == "smart_turn"
    assert profile.input_audio_format == "pcm16le/16000/mono"
    assert profile.output_audio_format == "pcm16le/24000/mono"


def test_no_raw_audio_or_trace_fixture_is_committed_for_spike() -> None:
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
    roots = (SPIKE_ROOT, Path(__file__).parent)
    forbidden = [
        path.relative_to(REPO_ROOT)
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]

    assert forbidden == []


def test_external_provider_connection_is_confined_to_spike_adapter() -> None:
    provider_markers = (
        "cn-beijing.maas.aliyuncs.com",
        "api-ws/v1/realtime",
    )
    offenders: list[str] = []
    for path in SPIKE_ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in provider_markers):
            if path.name != "provider_adapter.py":
                offenders.append(path.name)

    assert offenders == []


def test_report_records_real_synthetic_live_evidence_without_overclaim() -> None:
    report = REPORT.read_text(encoding="utf-8")

    assert "real_connection_smoke=executed_no_audio" in report
    assert "real_audio_turn_smoke=executed_synthetic" in report
    assert "real_barge_in_smoke=executed_synthetic" in report
    assert "real_device_smoke=not_executed" in report
    assert "real_10min_smoke=not_executed" in report
    assert "Provider=real" in report
    assert "session.created" in report
    assert "session.updated" in report
    assert "旧 provider response 到达 `status=cancelled`" in report
    assert "新轮 response 随后 `completed`" in report
    assert "实际 provider 转写或回复原文" in report
    assert "真人麦克风" in report
    assert "10 分钟稳定性仍为 `not_executed`" in report
    assert "console 0 error / 0 warning" in report
    assert "qwen-audio-3.0-realtime-plus" in report
    assert "ADR-001" in report
    assert "ADR-003" in report
    assert "playback-reference AEC" in report
    assert "不是核心 Event Journal" in report
    assert "100 ms" in report and "20–40 ms" in report
    assert "DASHSCOPE_API_KEY" in report
    assert "QWEN_REALTIME_WORKSPACE_ID" in report


def test_static_frontend_uses_audio_worklets_and_never_requests_credentials() -> None:
    index = (SPIKE_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (SPIKE_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    capture = (SPIKE_ROOT / "static" / "mic-worklet.js").read_text(
        encoding="utf-8"
    )
    player = (SPIKE_ROOT / "static" / "player-worklet.js").read_text(
        encoding="utf-8"
    )

    assert "Start microphone" in index
    assert "AudioWorkletProcessor" in capture
    assert "targetSampleRate = 16_000" in capture
    assert "chunkSamples = 1_600" in capture
    assert "AudioWorkletProcessor" in player
    assert "SOURCE_SAMPLE_RATE = 24_000" in player
    assert "late_audio_dropped" in player
    assert "decodeAudioData" not in capture + player
    assert "DASHSCOPE_API_KEY" not in index + app + capture + player
    assert "QWEN_REALTIME_WORKSPACE_ID" not in index + app + capture + player

    refresh_buttons_start = app.index("function refreshButtons()")
    refresh_buttons_end = app.index("function refreshModeNotice()")
    refresh_buttons = app[refresh_buttons_start:refresh_buttons_end]
    assert "state.providerSessionReady" in refresh_buttons
    assert "elements.startMic.disabled" in refresh_buttons
    assert '"session.updated"' in app
