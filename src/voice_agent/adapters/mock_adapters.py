from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from voice_agent.adapters.capabilities import AdapterCapability, BOOLEAN_CAPABILITY_FIELDS


MVP0_MOCK_CAPABILITY_SNAPSHOT_REF = "capability://synthetic/mvp0/mock-adapters-v1"
MVP0_MOCK_CAPABILITY_VERSION = "mvp0.mock.v1"


def mvp0_mock_adapter_capabilities() -> tuple[AdapterCapability, ...]:
    return (
        _mock_asr_capability(),
        _mock_thinker_capability(),
        _mock_talker_capability(),
    )


def mvp0_capability_snapshot(capabilities: Iterable[AdapterCapability]) -> dict[str, Any]:
    matrices = [capability.to_dict() for capability in capabilities]
    return {
        "capability_snapshot_ref": MVP0_MOCK_CAPABILITY_SNAPSHOT_REF,
        "adapter_ids": [matrix["adapter_id"] for matrix in matrices],
        "adapter_types": [matrix["adapter_type"] for matrix in matrices],
        "deployment_modes": [matrix["deployment_mode"] for matrix in matrices],
        "output_modes": [matrix["output_mode"] for matrix in matrices],
        "capability_version": MVP0_MOCK_CAPABILITY_VERSION,
    }


def _base_mock_capability(**overrides: Any) -> AdapterCapability:
    fields: dict[str, Any] = {
        "provider": "mock",
        "deployment_mode": "mock",
        "endpoint": "mock://mvp0/adapter",
        "health_status": "healthy_mock",
        "capability_version": MVP0_MOCK_CAPABILITY_VERSION,
        "latency_class": "mock_instant",
        "error_model": "mock-error-model://synthetic/mvp0/no-provider-errors",
        "timeout_policy": "timeout-policy://synthetic/mvp0/no-provider-timeout",
        "retry_policy": "retry-policy://synthetic/mvp0/no-provider-retry",
        "output_mode": "mock",
        "config_ref": "config://synthetic/mvp0/mock-adapters",
        "supports_streaming_input": False,
        "supports_streaming_output": False,
        "supports_audio_input": False,
        "supports_audio_output": False,
        "supports_audio_timestamps": False,
        "supports_structured_json": False,
        "supports_tool_calling": False,
        "supports_cancellation": False,
        "supports_emotion": False,
        "supports_audio_caption": False,
        "supports_tts": False,
        "supports_tts_truncate": False,
        "supports_tts_pause_resume": False,
        "supports_semantic_close": False,
        "supports_assistant_directedness": False,
        "max_audio_seconds": None,
        "max_context_tokens": None,
        "max_output_tokens": None,
        "expected_first_token_latency_ms": None,
        "expected_first_audio_latency_ms": None,
        "mocked": True,
        "target_architecture_validation": False,
    }
    fields.update(overrides)
    fields["unsupported_capabilities"] = tuple(
        field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)


def _mock_asr_capability() -> AdapterCapability:
    return _base_mock_capability(
        adapter_id="mock_asr",
        adapter_type="asr",
        model_name="mvp0_mock_asr_profile",
        endpoint="mock://mvp0/asr",
        mock_profile_ref="mock-profile://synthetic/mvp0/asr-final-transcript",
        supports_streaming_input=True,
        supports_streaming_output=True,
        supports_audio_input=True,
        supports_audio_timestamps=True,
        supports_structured_json=True,
        max_audio_seconds=30,
        max_output_tokens=256,
        expected_first_token_latency_ms=0,
    )


def _mock_thinker_capability() -> AdapterCapability:
    return _base_mock_capability(
        adapter_id="mock_thinker",
        adapter_type="thinker",
        model_name="mvp0_mock_thinker_profile",
        endpoint="mock://mvp0/thinker",
        mock_profile_ref="mock-profile://synthetic/mvp0/semantic-frame",
        supports_streaming_input=True,
        supports_streaming_output=True,
        supports_audio_input=True,
        supports_audio_timestamps=True,
        supports_structured_json=True,
        supports_emotion=True,
        supports_audio_caption=True,
        supports_semantic_close=True,
        supports_assistant_directedness=True,
        max_audio_seconds=30,
        max_context_tokens=4096,
        max_output_tokens=512,
        expected_first_token_latency_ms=0,
    )


def _mock_talker_capability() -> AdapterCapability:
    return _base_mock_capability(
        adapter_id="mock_talker",
        adapter_type="tts",
        model_name="mvp0_mock_talker_profile",
        endpoint="mock://mvp0/talker",
        mock_profile_ref="mock-profile://synthetic/mvp0/talker-playback-progress",
        supports_streaming_output=True,
        supports_audio_output=True,
        supports_audio_timestamps=True,
        supports_tts=True,
        supports_tts_truncate=True,
        max_context_tokens=1024,
        expected_first_audio_latency_ms=0,
    )
