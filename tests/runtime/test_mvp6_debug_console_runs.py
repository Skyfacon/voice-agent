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
    validate_mvp6_safe_response,
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
    assert response["answer_display"] == (
        "FAST_ONLY selected; real fast answer is not implemented in MVP6.1 debug console."
    )
    assert _latency_debug_is_safe(response["latency_debug"])
    assert response["latency_debug"]["total_server_ms"] >= 0
    assert response["latency_debug"]["wav_validate_ms"] >= 0
    assert response["latency_debug"]["temp_wav_write_ms"] >= 0
    assert response["latency_debug"]["local_audio_gate_ms"] >= 0
    assert response["latency_debug"]["approval_gate_ms"] >= 0
    assert response["latency_debug"]["asr_provider_http_ms"] >= 0
    assert response["latency_debug"]["asr_normalize_emit_ms"] >= 0
    assert response["latency_debug"]["thinker_provider_http_ms"] >= 0
    assert response["latency_debug"]["thinker_parse_validate_emit_ms"] >= 0
    assert response["latency_debug"]["router_ms"] >= 0
    assert response["latency_debug"]["qa_history_ms"] >= 0
    assert isinstance(response["latency_debug"]["provider_calls_parallel"], bool)
    assert isinstance(response["latency_debug"]["asr_started_before_thinker_finished"], bool)
    assert isinstance(response["latency_debug"]["thinker_started_before_asr_finished"], bool)
    assert response["thinker_transient_asr_text_used"] is False
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


def test_safe_response_allows_request_metadata_refs_but_rejects_data_urls() -> None:
    validate_mvp6_safe_response(
        {
            "model_io_debug": {
                "request_metadata_ref": "request-metadata://mvp5/live-voice-evidence/run-001",
                "audio_data": "[redacted-audio-base64]",
            }
        }
    )

    with pytest.raises(MVP6DebugConsoleError, match="unsafe response value"):
        validate_mvp6_safe_response(
            {
                "model_io_debug": {
                    "audio_data": "data:audio/wav;base64,UklGRg==",
                }
            }
        )


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
    assert response["answer_display"] == "收到，我会把这点补充到当前任务里。"


def test_spawn_slow_task_uses_local_reassurance_template(tmp_path: Path) -> None:
    wav_path = tmp_path / "spawn.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="fake",
            expected_route="SPAWN_SLOW_TASK",
            save_qa_history=False,
        ),
        env={},
    )

    assert response["status"] == "completed"
    assert response["actual_route"] == "SPAWN_SLOW_TASK"
    assert response["answer_display"] == "我帮你看一下，请稍等。"


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
    assert "model_io_debug" not in response
    assert captured_kwargs["live_provider"] is True
    assert captured_kwargs["asr_transport"] is None
    assert captured_kwargs["thinker_transport"] is None


def test_live_provider_mode_can_return_local_only_model_io_debug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "live-debug.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    def fake_runtime(**_kwargs: object) -> dict[str, object]:
        return {
            "status": "evidence_failed",
            "run_id": "mvp6_run_live_debug",
            "actual_route": None,
            "router_decision": None,
            "route_result_kind": "blocked",
            "expected_route": "auto",
            "expected_route_matched": False,
            "provider_call_used": True,
            "fake_transport_used": False,
            "asr_output_mode": "real",
            "thinker_output_mode": None,
            "failure_reasons": ["fenced_markdown"],
            "event_ids": ["evt_mvp6_live_debug"],
            "safe_refs": ["text://provider/dashscope/adapter-request-mvp5-asr-mvp6-run-live-debug"],
        }

    class FakeAsrLiveModule:
        @staticmethod
        def resolve_asr_live_transcript_text_ref(_text_ref: str) -> str:
            return "Give me a short joke"

        @staticmethod
        def resolve_asr_live_model_io_debug(_adapter_request_id: str) -> dict[str, object]:
            return {
                "adapter": "asr",
                "request_body": {
                    "messages": [
                        {
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {"data": "[redacted-audio-base64]"},
                                }
                            ]
                        }
                    ]
                },
                "provider_text": "Give me a short joke",
                "raw_audio_visible": False,
                "authorization_header_visible": False,
            }

    class FakeThinkerLiveModule:
        @staticmethod
        def resolve_lalm_thinker_live_model_io_debug(_adapter_request_id: str) -> dict[str, object]:
            return {
                "adapter": "thinker",
                "system_message": "Return only one lalm_thinker_semantic_frame_candidate.v1 JSON object.",
                "request_body": {
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system"}, {"role": "user"}],
                },
                "provider_text": "```json\n{}\n```",
                "raw_audio_visible": False,
                "authorization_header_visible": False,
            }

    def fake_import_module(name: str) -> object:
        if name == "voice_agent.adapters.asr_live_transport":
            return FakeAsrLiveModule
        if name == "voice_agent.adapters.lalm_thinker_live_transport":
            return FakeThinkerLiveModule
        raise AssertionError(name)

    monkeypatch.setattr(api, "run_mvp5_real_voice_e2e_single", fake_runtime)
    monkeypatch.setattr(api.importlib, "import_module", fake_import_module)

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=True,
            show_model_io=True,
        ),
        env={"MVP6_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
    )

    model_io = response["model_io_debug"]
    rendered = json.dumps(response, sort_keys=True)
    assert model_io["saved_to_history"] is False
    assert model_io["asr"]["provider_text"] == "Give me a short joke"
    assert "lalm_thinker_semantic_frame_candidate.v1" in model_io["thinker"]["system_message"]
    assert model_io["thinker"]["provider_text"] == "```json\n{}\n```"
    assert "[redacted-audio-base64]" in rendered
    assert "DUMMY_TEST_CREDENTIAL" not in rendered
    assert "data:audio" not in rendered
    assert str(tmp_path) not in rendered


def test_live_provider_evidence_failure_returns_failed_pipeline_without_router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "live-failed.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    def fake_runtime(**_kwargs: object) -> dict[str, object]:
        return {
            "status": "evidence_failed",
            "run_id": "mvp6_run_live_failed",
            "actual_route": None,
            "router_decision": None,
            "route_result_kind": "blocked",
            "expected_route": "auto",
            "expected_route_matched": False,
            "provider_call_used": True,
            "fake_transport_used": False,
            "asr_output_mode": "real",
            "thinker_output_mode": None,
            "failure_reasons": ["invalid_json"],
            "event_ids": ["evt_mvp6_live_failed"],
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

    stages = {stage["stage"]: stage["status"] for stage in response["pipeline"]}
    assert response["status"] == "evidence_failed"
    assert response["route_result_kind"] == "blocked"
    assert response["actual_route"] is None
    assert response["answer_display"] == "Run did not reach router."
    assert response["failure_reasons"] == ["invalid_json"]
    assert response["thinker_io_shape"] == {
        "input_modality": "audio",
        "audio_passed_to_adapter": True,
        "transient_asr_text_present": False,
        "candidate_schema": "lalm_thinker_semantic_frame_candidate.v1",
        "expected_output": "single_json_object",
        "routing_hint_field": "task_focus_hint.focus",
        "provider_text_visible": False,
        "raw_audio_visible": False,
        "failure_reasons": ["invalid_json"],
    }
    assert stages["local_audio_gate"] == "passed"
    assert stages["asr"] == "completed"
    assert stages["thinker"] == "failed"
    assert stages["router"] == "not_run"
    assert stages["qa_history"] == "skipped"


def test_latency_debug_rejects_unsafe_fields_from_runtime_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "unsafe-latency.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    def fake_runtime(**_kwargs: object) -> dict[str, object]:
        return {
            "status": "routed",
            "run_id": "mvp6_run_unsafe_latency",
            "actual_route": "FAST_ONLY",
            "router_decision": "FAST_ONLY",
            "route_result_kind": "direct_answer",
            "expected_route": "auto",
            "expected_route_matched": True,
            "provider_call_used": True,
            "fake_transport_used": False,
            "asr_output_mode": "real",
            "thinker_output_mode": "real",
            "event_ids": ["evt_mvp6_unsafe_latency"],
            "safe_refs": [],
            "latency_debug": {
                "total_server_ms": 1,
                "provider_response": "must not pass through",
            },
        }

    monkeypatch.setattr(api, "run_mvp5_real_voice_e2e_single", fake_runtime)

    with pytest.raises(MVP6DebugConsoleError, match="latency_debug"):
        run_mvp6_debug_console_audio(
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


def _latency_debug_is_safe(latency_debug: object) -> bool:
    assert isinstance(latency_debug, dict)
    rendered = json.dumps(latency_debug, sort_keys=True)
    forbidden_terms = (
        "raw_audio",
        "audio_bytes",
        "wav_bytes",
        "transcript",
        "provider_body",
        "provider_request",
        "provider_response",
        "prompt",
        "secret",
        "token",
        "api_key",
        "/Users/",
        "/private/",
        "file://",
    )
    assert all(term not in rendered for term in forbidden_terms)
    return True
