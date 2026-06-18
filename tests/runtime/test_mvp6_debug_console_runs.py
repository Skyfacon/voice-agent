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


def test_live_provider_mode_delegates_after_approval_and_credential_without_network(
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
    captured_kwargs: dict[str, object] = {}

    def fake_runtime(**kwargs: object) -> dict[str, object]:
        captured_kwargs.update(kwargs)
        return {
            "status": "routed",
            "run_id": "mvp6_run_live_gate",
            "actual_route": "FAST_ONLY",
            "router_decision": "FAST_ONLY",
            "route_result_kind": "direct_answer",
            "expected_route": "auto",
            "expected_route_matched": True,
            "provider_call_used": True,
            "fake_transport_used": False,
            "asr_output_mode": "real",
            "thinker_output_mode": "real",
            "event_ids": ["evt_mvp6_live_gate"],
            "safe_refs": ["text://provider/dashscope/adapter-request-mvp6"],
        }

    monkeypatch.setattr(api, "run_mvp5_real_voice_e2e_single", fake_runtime)

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

    assert response["status"] == "completed"
    assert response["provider_call_used"] is True
    assert response["fake_transport_used"] is False
    assert captured_kwargs["live_provider"] is True
    assert captured_kwargs["asr_transport"] is None
    assert captured_kwargs["thinker_transport"] is None


def test_live_provider_mode_requires_approval_and_credential(tmp_path: Path) -> None:
    wav_path = tmp_path / "live.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=False,
        ),
        env={},
    )

    assert response["status"] == "approval_missing"
    assert response["provider_call_used"] is False
    assert response["fake_transport_used"] is False


def test_live_provider_mode_reports_credential_missing_without_provider_call(tmp_path: Path) -> None:
    wav_path = tmp_path / "live-missing-credential.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=False,
        ),
        env={},
    )

    assert response["status"] == "credential_missing"
    assert response["provider_call_used"] is False
    assert response["fake_transport_used"] is False


def test_live_question_text_resolves_from_process_local_asr_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    class FakeAsrLiveModule:
        @staticmethod
        def resolve_asr_live_transcript_text_ref(text_ref: str) -> str | None:
            assert text_ref == "text://provider/dashscope/adapter-request-mvp6"
            return "Plan a three day Tokyo trip"

    monkeypatch.setattr(api.importlib, "import_module", lambda name: FakeAsrLiveModule)
    metadata = {
        "safe_refs": ["text://provider/dashscope/adapter-request-mvp6"],
        "asr_output_mode": "degraded",
    }

    assert (
        api.resolve_mvp6_question_text(metadata, provider_mode="dashscope_live")
        == "Plan a three day Tokyo trip"
    )


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
