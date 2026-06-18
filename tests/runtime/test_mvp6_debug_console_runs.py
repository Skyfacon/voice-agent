from __future__ import annotations

import base64
import json
from pathlib import Path
import wave

import pytest

from voice_agent.runtime.mvp6_debug_console_api import (
    MVP6DebugConsoleConfig,
    MVP6DebugConsoleError,
    MVP6RunRequest,
    run_mvp6_debug_console_audio,
)


def test_provider_free_run_delegates_to_mvp5_and_returns_safe_pipeline(tmp_path: Path) -> None:
    wav_path = tmp_path / "draft.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="fake",
            expected_route="FAST_ONLY",
            save_qa_history=True,
        ),
        env={},
    )

    rendered = json.dumps(response, sort_keys=True)
    assert response["status"] == "completed"
    assert response["provider_mode"] == "fake"
    assert response["actual_route"] == "FAST_ONLY"
    assert response["router_decision"] == "FAST_ONLY"
    assert response["expected_route_matched"] is True
    assert response["provider_call_used"] is False
    assert response["fake_transport_used"] is True
    assert response["question_text"]
    assert response["answer_display"] == "Router chose FAST_ONLY from FOREGROUND_CHAT evidence."
    assert [stage["stage"] for stage in response["pipeline"]] == [
        "local_audio_gate",
        "asr",
        "thinker",
        "router",
        "qa_history",
    ]
    assert response["safety"]["raw_audio_returned"] is False
    assert response["safety"]["raw_audio_saved_to_history"] is False
    assert str(tmp_path) not in rendered
    assert "draft.wav" not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered


def test_patch_run_requires_active_task_context(tmp_path: Path) -> None:
    wav_path = tmp_path / "patch.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="fake",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            save_qa_history=False,
        ),
        env={},
    )

    assert response["status"] == "blocked_missing_active_task_context"
    assert response["actual_route"] is None
    assert response["safety"]["raw_audio_returned"] is False


def test_patch_run_with_active_task_context_returns_patch_route(tmp_path: Path) -> None:
    wav_path = tmp_path / "patch-active.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="fake",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            save_qa_history=False,
            active_task_id="task_mvp6_active",
            active_plan_version=1,
            active_task_event_seq=1,
        ),
        env={},
    )

    assert response["status"] == "completed"
    assert response["actual_route"] == "PATCH_ACTIVE_SLOW_TASK"
    assert response["route_result_kind"] == "user_patch"
    assert response["expected_route_matched"] is True


def test_rejects_non_wav_upload_without_calling_runtime(tmp_path: Path) -> None:
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    with pytest.raises(MVP6DebugConsoleError, match="wav"):
        run_mvp6_debug_console_audio(
            config=config,
            request=MVP6RunRequest(
                audio_bytes=b"not a wav",
                audio_mime_type="audio/webm",
                provider_mode="fake",
                expected_route="auto",
                save_qa_history=False,
            ),
            env={},
        )


def test_live_provider_mode_is_blocked_before_task4_live_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "live.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    def fail_if_runtime_called(**_: object) -> dict[str, object]:
        raise AssertionError("live provider mode must not reach MVP5 runtime in Task 3")

    monkeypatch.setattr(api, "run_mvp5_real_voice_e2e_single", fail_if_runtime_called)

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=False,
        ),
        env={"MVP6_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
    )

    assert response["status"] == "live_provider_not_enabled"
    assert response["provider_call_used"] is False
    assert response["fake_transport_used"] is False


def _write_wav_file(path: Path) -> bytes:
    frames = b"\x00\x00" * 1600
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(frames)
    return path.read_bytes()


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
