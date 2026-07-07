from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice_agent.runtime.mvp6_debug_console_api import (
    MVP6DebugConsoleConfig,
    MVP6DebugConsoleError,
    build_mvp6_status_response,
    validate_mvp6_safe_response,
)


def test_status_defaults_to_fake_and_redacts_paths_and_secrets(tmp_path: Path) -> None:
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    status = build_mvp6_status_response(config, env={"MVP6_TEST_PROVIDER_KEY": "SECRET"})

    rendered = json.dumps(status, sort_keys=True)
    assert status["status"] == "ready"
    assert status["provider_modes"] == ["fake", "dashscope_live"]
    assert status["default_provider_mode"] == "fake"
    assert status["approval_loaded"] is False
    assert status["credential_present"] is False
    assert status["metadata_only_output"] is True
    assert status["qa_history_enabled_default"] is True
    assert status["routing_prompt_profile"]["profile_id"] == "lalm-thinker-routing-control"
    assert status["routing_prompt_profile"]["profile_version"] == "mvp6.2.zh-CN.v1"
    assert status["routing_prompt_profile"]["profile_hash"].startswith("sha256:")
    assert status["routing_prompt_profile"]["locale"] == "zh-CN"
    assert str(tmp_path) not in rendered
    assert "SECRET" not in rendered
    assert "approval_packet_path" not in rendered


def test_status_reports_live_provider_readiness_without_secret_value(tmp_path: Path) -> None:
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    status = build_mvp6_status_response(
        config,
        env={"MVP6_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
    )

    rendered = json.dumps(status, sort_keys=True)
    assert status["approval_loaded"] is True
    assert status["credential_env_var_name"] == "MVP6_TEST_PROVIDER_KEY"
    assert status["credential_present"] is True
    assert status["max_provider_calls"] == 2
    assert status["timeout_ms"] == 30000
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered


def test_status_reports_live_provider_not_ready_when_credential_missing(tmp_path: Path) -> None:
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    status = build_mvp6_status_response(config, env={})

    assert status["approval_loaded"] is True
    assert status["credential_env_var_name"] == "MVP6_TEST_PROVIDER_KEY"
    assert status["credential_present"] is False
    assert status["max_provider_calls"] == 2
    assert status["timeout_ms"] == 30000


def test_config_rejects_non_local_bind_host(tmp_path: Path) -> None:
    with pytest.raises(MVP6DebugConsoleError, match="localhost"):
        MVP6DebugConsoleConfig(
            output_root=tmp_path / "outputs" / "mvp6-debug-console",
            bind_host="0.0.0.0",
        )


def test_status_rejects_bool_provider_limits(tmp_path: Path) -> None:
    approval_packet = _approval_packet()
    approval_packet["max_provider_calls"] = True
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=approval_packet,
    )

    with pytest.raises(MVP6DebugConsoleError, match="max_provider_calls"):
        build_mvp6_status_response(config, env={"MVP6_TEST_PROVIDER_KEY": "SECRET"})


def test_safe_response_validation_rejects_non_json_objects(tmp_path: Path) -> None:
    with pytest.raises(MVP6DebugConsoleError, match="unsupported"):
        validate_mvp6_safe_response(tmp_path)


def _approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp6-local-debug-console-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP6_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30000,
        "safe_output_ref": "summary://mvp6/debug-console/test",
    }
