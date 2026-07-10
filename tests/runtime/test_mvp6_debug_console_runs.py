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
    assert response["question_text"] is None
    assert response["question_status"] == "ref_unresolved"
    assert response["question_source"] == "unavailable"
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
    assert captured_kwargs["fast_interaction_enabled"] is True
    assert captured_kwargs["audio_native_thinker_enabled"] is False
    assert captured_kwargs["asr_observation_enabled"] is True


def test_debug_console_displays_gated_fast_interaction_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "fast-live.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(
            provider_adapter_ids=[
                "mvp5_asr_adapter",
                "mvp63_fast_interaction_runtime",
            ],
            max_provider_calls=2,
            timeout_ms=1500,
        ),
    )

    def fake_runtime(**kwargs: object) -> dict[str, object]:
        assert kwargs["fast_interaction_enabled"] is True
        assert kwargs["audio_native_thinker_enabled"] is False
        assert kwargs["asr_observation_enabled"] is True
        return {
            "status": "routed",
            "run_id": "mvp6_run_fast_live",
            "actual_route": "FAST_ONLY",
            "router_decision": "FAST_ONLY",
            "route_result_kind": "direct_answer",
            "expected_route": "auto",
            "expected_route_matched": True,
            "provider_call_used": True,
            "fake_transport_used": False,
            "asr_output_mode": "real",
            "thinker_output_mode": None,
            "fast_interaction_output_mode": "real",
            "foreground_gate_decision": "passed",
            "foreground_output_basis": "reply_candidate",
                "foreground_output_event_id": "evt_mvp63_debug_fast_output_committed",
                "foreground_output_ref": "foreground-candidate://synthetic/mvp63/debug-console",
                "foreground_candidate_ref": "foreground-candidate://synthetic/mvp63/debug-console",
            "asr_observation_enabled": True,
            "asr_observation_status": "completed",
            "question_event_id": "evt_mvp63_debug_fast_asr_transcript",
            "question_text_ref": (
                "text://provider/dashscope/adapter-request-mvp6-fast-question"
            ),
            "event_ids": ["evt_mvp63_debug_fast"],
            "safe_refs": [
                "text://provider/dashscope/adapter-request-mvp6-fast-question",
                "foreground-candidate://synthetic/mvp63/debug-console",
            ],
            "latency_debug": {
                "fast_interaction_provider_http_ms": 400,
                "fast_interaction_parse_validate_emit_ms": 5,
                "fast_interaction_total_ms": 405,
                "fast_interaction_timeout_ms": 1500,
                "fast_interaction_timed_out": False,
            },
        }

    class FakeFastInteractionRuntimeModule:
        @staticmethod
        def resolve_asr_live_transcript_text_ref(text_ref: str) -> str | None:
            assert text_ref == "text://provider/dashscope/adapter-request-mvp6-fast-question"
            return "给我讲一个短短的恐怖故事"

        @staticmethod
        def resolve_fast_interaction_reply_candidate_ref(candidate_ref: str) -> str | None:
            assert candidate_ref == "foreground-candidate://synthetic/mvp63/debug-console"
            return "好，我讲一个短短的恐怖故事。"

    monkeypatch.setattr(api, "run_mvp5_real_voice_e2e_single", fake_runtime)
    monkeypatch.setattr(
        api.importlib,
        "import_module",
        lambda name: FakeFastInteractionRuntimeModule,
    )

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=True,
        ),
        env={"MVP6_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
    )

    assert response["answer_display"] == "好，我讲一个短短的恐怖故事。"
    assert response["question_text"] == "给我讲一个短短的恐怖故事"
    assert response["question_source"] == "asr_transcript"
    assert response["qa_status"] == "complete"
    assert response["fast_interaction_output_mode"] == "real"
    assert response["foreground_gate_decision"] == "passed"
    assert response["foreground_output_basis"] == "reply_candidate"
    assert response["latency_debug"]["fast_interaction_total_ms"] == 405
    saved_history = json.loads(config.history_path.read_text(encoding="utf-8").strip())
    assert saved_history["question_text"] == "给我讲一个短短的恐怖故事"
    assert saved_history["question_source"] == "asr_transcript"
    assert saved_history["answer_display"] == "好，我讲一个短短的恐怖故事。"
    assert saved_history["foreground_gate_decision"] == "passed"
    assert saved_history["foreground_output_basis"] == "reply_candidate"
    assert saved_history["latency_debug"]["fast_interaction_total_ms"] == 405


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
    assert model_io["asr"]["metadata_only"] is True
    assert model_io["asr"]["content_redacted"] is True
    assert model_io["asr"]["provider_output_available"] is True
    assert model_io["asr"]["provider_output_char_count"] == len("Give me a short joke")
    assert model_io["thinker"]["metadata_only"] is True
    assert model_io["thinker"]["content_redacted"] is True
    assert model_io["thinker"]["request_payload_available"] is True
    assert model_io["thinker"]["system_instruction_available"] is True
    assert model_io["thinker"]["provider_output_char_count"] == len("```json\n{}\n```")
    assert "Give me a short joke" not in rendered
    assert "Return only one" not in rendered
    assert "```json" not in rendered
    assert "[redacted-audio-base64]" not in rendered
    assert "request_body" not in rendered
    assert "system_message" not in rendered
    assert '"provider_text"' not in rendered
    assert "DUMMY_TEST_CREDENTIAL" not in rendered
    assert "data:audio" not in rendered
    assert str(tmp_path) not in rendered


def test_asr_observation_failure_preserves_committed_answer_on_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "asr-failed-fast-answer.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(
            provider_adapter_ids=[
                "mvp5_asr_adapter",
                "mvp63_fast_interaction_runtime",
            ],
            max_provider_calls=2,
            timeout_ms=1500,
        ),
    )
    monkeypatch.setattr(
        api,
        "run_mvp5_real_voice_e2e_single",
        lambda **_kwargs: {
            "status": "routed",
            "run_id": "mvp6_run_asr_failed_fast_answer",
            "actual_route": "FAST_ONLY",
            "router_decision": "FAST_ONLY",
            "route_result_kind": "direct_answer",
            "expected_route": "auto",
            "expected_route_matched": True,
            "provider_call_used": True,
            "fake_transport_used": False,
            "asr_output_mode": None,
            "asr_observation_enabled": True,
            "asr_observation_status": "failed",
            "fast_interaction_output_mode": "real",
            "foreground_gate_decision": "passed",
            "foreground_output_basis": "reply_candidate",
                "foreground_output_event_id": "evt_mvp63_committed_after_asr_failure",
                "foreground_output_ref": "foreground-candidate://synthetic/mvp63/asr-failure",
                "foreground_candidate_ref": "foreground-candidate://synthetic/mvp63/asr-failure",
            "event_ids": ["evt_mvp63_committed_after_asr_failure"],
            "safe_refs": ["foreground-candidate://synthetic/mvp63/asr-failure"],
        },
    )

    class FakeFastModule:
        @staticmethod
        def resolve_fast_interaction_reply_candidate_ref(candidate_ref: str) -> str | None:
            assert candidate_ref == "foreground-candidate://synthetic/mvp63/asr-failure"
            return "回答仍然可以正常展示。"

    monkeypatch.setattr(api.importlib, "import_module", lambda _name: FakeFastModule)
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

    assert response["question_text"] is None
    assert response["question_status"] == "failed"
    assert response["answer_display"] == "回答仍然可以正常展示。"
    assert response["answer_status"] == "committed"
    assert response["qa_status"] == "question_unavailable"


def test_fast_failure_preserves_asr_question_without_candidate_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "fast-failed-asr-question.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )
    question_ref = "text://provider/dashscope/adapter-request-mvp6-fast-failed"
    monkeypatch.setattr(
        api,
        "run_mvp5_real_voice_e2e_single",
        lambda **_kwargs: {
            "status": "evidence_failed",
            "run_id": "mvp6_run_fast_failed_asr_question",
            "actual_route": None,
            "router_decision": None,
            "route_result_kind": "blocked",
            "expected_route": "auto",
            "expected_route_matched": False,
            "provider_call_used": True,
            "fake_transport_used": False,
            "asr_output_mode": "real",
            "asr_observation_enabled": True,
            "asr_observation_status": "completed",
            "fast_interaction_output_mode": None,
            "question_event_id": "evt_mvp6_fast_failed_asr_question",
            "question_text_ref": question_ref,
            "failure_reasons": ["provider_timeout"],
            "event_ids": ["evt_mvp6_fast_failed_asr_question"],
            "safe_refs": [question_ref],
        },
    )

    class FakeAsrModule:
        @staticmethod
        def resolve_asr_live_transcript_text_ref(text_ref: str) -> str | None:
            assert text_ref == question_ref
            return "我的问题仍然应该显示"

    monkeypatch.setattr(api.importlib, "import_module", lambda _name: FakeAsrModule)
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

    assert response["question_text"] == "我的问题仍然应该显示"
    assert response["question_status"] == "available"
    assert response["answer_status"] == "unavailable"
    assert response["answer_display"] == "Run did not reach router."
    assert response["qa_status"] == "failed"


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


def test_live_question_text_is_resolved_for_local_qa_response(
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
        "question_event_id": "evt_mvp6_asr_transcript",
        "question_text_ref": "text://provider/dashscope/adapter-request-mvp6",
    }

    assert api.resolve_mvp6_question_text(metadata, provider_mode="dashscope_live") == (
        "Plan a three day Tokyo trip"
    )


def test_committed_candidate_ref_mismatch_is_not_displayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    monkeypatch.setattr(
        api.importlib,
        "import_module",
        lambda _name: pytest.fail("mismatched candidate ref must not be resolved"),
    )
    response = api._response_from_mvp5_metadata(
        {
            "status": "routed",
            "run_id": "mvp6_ref_mismatch",
            "actual_route": "FAST_ONLY",
            "router_decision": "FAST_ONLY",
            "fast_interaction_enabled": True,
            "fast_interaction_status": "completed",
            "fast_interaction_output_mode": "real",
            "foreground_gate_decision": "passed",
            "foreground_output_event_id": "evt_committed",
            "foreground_output_basis": "reply_candidate",
            "foreground_output_ref": "foreground-candidate://synthetic/committed",
            "foreground_candidate_ref": "foreground-candidate://synthetic/different",
        },
        provider_mode="dashscope_live",
        question_text=None,
        history_written=False,
    )

    assert response["answer_status"] == "unavailable"
    assert response["answer_source"] == "none"
    assert response["answer_display"] == (
        "Run did not commit resolvable foreground output."
    )


def test_committed_template_requires_runtime_catalog_provenance() -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    metadata = {
        "status": "routed",
        "run_id": "mvp6_template_provenance",
        "actual_route": "SPAWN_SLOW_TASK",
        "router_decision": "SPAWN_SLOW_TASK",
        "fast_interaction_enabled": True,
        "fast_interaction_status": "completed",
        "fast_interaction_output_mode": "real",
        "foreground_gate_decision": "failed",
        "foreground_output_event_id": "evt_template_committed",
        "foreground_output_basis": "template_ack",
        "foreground_output_ref": "foreground-template://synthetic/run/ack",
        "foreground_fallback_policy_ref": (
            "fallback-policy://synthetic/run/template_ack"
        ),
        "foreground_fallback_reason": "router_decision_not_fast_only",
    }

    response = api._response_from_mvp5_metadata(
        metadata,
        provider_mode="dashscope_live",
        question_text="请帮我做一个复杂任务",
        history_written=False,
    )

    assert response["answer_status"] == "fallback"
    assert response["answer_source"] == "runtime_template_fallback"
    assert response["answer_display"] == "我帮你看一下，请稍等。"

    invalid_response = api._response_from_mvp5_metadata(
        {
            **metadata,
            "foreground_fallback_policy_ref": (
                "fallback-policy://synthetic/run/template_clarify"
            ),
        },
        provider_mode="dashscope_live",
        question_text="请帮我做一个复杂任务",
        history_written=False,
    )
    assert invalid_response["answer_status"] == "unavailable"
    assert invalid_response["answer_display"] == (
        "Run did not commit resolvable foreground output."
    )


def test_fast_failure_pipeline_does_not_report_thinker_failure() -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    response = api._response_from_mvp5_metadata(
        {
            "status": "evidence_failed",
            "run_id": "mvp6_fast_failed",
            "actual_route": None,
            "asr_output_mode": "real",
            "fast_interaction_enabled": True,
            "fast_interaction_status": "failed",
            "failure_reasons": ["provider_timeout"],
        },
        provider_mode="dashscope_live",
        question_text="测试问题",
        history_written=False,
    )

    stages = {stage["stage"]: stage for stage in response["pipeline"]}
    assert stages["fast_interaction"]["status"] == "failed"
    assert "thinker" not in stages


def test_question_and_answer_credentials_are_redacted_before_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    wav_path = tmp_path / "credential-redaction.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(
            provider_adapter_ids=[
                "mvp5_asr_adapter",
                "mvp63_fast_interaction_runtime",
            ],
            max_provider_calls=2,
            timeout_ms=1500,
        ),
    )
    monkeypatch.setattr(
        api,
        "run_mvp5_real_voice_e2e_single",
        lambda **_kwargs: {
            "status": "routed",
            "run_id": "mvp6_credential_redaction",
            "actual_route": "FAST_ONLY",
            "router_decision": "FAST_ONLY",
            "provider_call_used": True,
            "asr_output_mode": "real",
            "question_text_ref": "text://provider/dashscope/credential-redaction",
            "fast_interaction_enabled": True,
            "fast_interaction_status": "completed",
            "fast_interaction_output_mode": "real",
            "foreground_gate_decision": "passed",
            "foreground_output_event_id": "evt_credential_committed",
            "foreground_output_basis": "reply_candidate",
            "foreground_output_ref": "foreground-candidate://synthetic/credential",
            "foreground_candidate_ref": "foreground-candidate://synthetic/credential",
        },
    )

    class CredentialResolverModule:
        @staticmethod
        def resolve_asr_live_transcript_text_ref(_text_ref: str) -> str:
            return "sk-ABCDEFGHIJKLMNOPQRSTUVWX"

        @staticmethod
        def resolve_fast_interaction_reply_candidate_ref(_candidate_ref: str) -> str:
            return "eyJabcdefgh.ijklmnop.qrstuvwx"

    monkeypatch.setattr(
        api.importlib,
        "import_module",
        lambda _name: CredentialResolverModule,
    )

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=True,
        ),
        env={"MVP6_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
    )

    rendered_response = json.dumps(response, sort_keys=True)
    rendered_history = config.history_path.read_text(encoding="utf-8")
    assert response["question_status"] == "redacted"
    assert response["answer_status"] == "redacted"
    assert response["qa_status"] == "redacted"
    assert response["credential_redaction_applied"] is True
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in rendered_response
    assert "eyJabcdefgh.ijklmnop.qrstuvwx" not in rendered_response
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in rendered_history
    assert "eyJabcdefgh.ijklmnop.qrstuvwx" not in rendered_history


def test_missing_latency_values_remain_null() -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    latency = api._normalize_mvp6_latency_debug({})

    assert latency["fast_interaction_provider_ttft_ms"] is None
    assert latency["foreground_gate_ms"] is None
    assert latency["foreground_output_finalize_ms"] is None


def _write_wav_file(path: Path) -> bytes:
    frames = b"\x00\x00" * 1600
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(frames)
    return path.read_bytes()


def _approval_packet(
    *,
    provider_adapter_ids: list[str] | None = None,
    max_provider_calls: int = 2,
    timeout_ms: int = 30000,
) -> dict[str, object]:
    return {
        "approval_id": "mvp6-local-debug-console-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": provider_adapter_ids
        or ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP6_TEST_PROVIDER_KEY",
        "max_provider_calls": max_provider_calls,
        "timeout_ms": timeout_ms,
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
        "raw_provider_request",
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
