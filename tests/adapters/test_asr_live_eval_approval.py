from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from voice_agent.adapters.asr_live_transport import (
    ASR_LIVE_SELECTED_MODEL_ALIAS,
    AsrLiveCredentialHandle,
    DashScopeAsrLiveTransportError,
)
from voice_agent.adapters.asr_live_eval import (
    ASR_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH,
    ASR_LIVE_EVAL_REQUIRED_APPROVAL_FIELDS,
    AsrLiveEvalApprovalError,
    load_asr_live_eval_synthetic_inputs,
    main,
    parse_asr_live_eval_approval_packet_markdown,
    run_asr_live_eval_dry_run,
    run_asr_live_eval_entrypoint,
    run_asr_synthetic_live_eval,
    validate_asr_live_eval_approval_packet,
    validate_asr_live_eval_synthetic_inputs,
)


def test_missing_approval_packet_fails_closed(tmp_path: Path) -> None:
    missing_packet = tmp_path / "missing-approval.md"

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        run_asr_live_eval_entrypoint(
            approval_packet_path=missing_packet,
            input_path=Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl"),
        )

    assert captured.value.failure_reasons == ["approval packet missing"]


def test_pending_approval_fails_closed() -> None:
    packet = _approved_packet()
    packet["approval_status"] = "pending"

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        validate_asr_live_eval_approval_packet(packet)

    assert captured.value.failure_reasons == ["approval_status is not approved"]


@pytest.mark.parametrize(
    "field",
    (
        "approver",
        "approval_date",
        "model_alias",
        "model_alias_repin_date",
        "max_request_count",
        "max_cost_quota",
        "per_request_timeout_ms",
        "retry_budget",
        "synthetic_input_set_path",
    ),
)
def test_missing_required_approval_fields_fail_closed(field: str) -> None:
    packet = _approved_packet()
    del packet[field]

    with pytest.raises(AsrLiveEvalApprovalError, match="missing approval field"):
        validate_asr_live_eval_approval_packet(packet)


def test_unsafe_output_path_fails_closed() -> None:
    packet = _approved_packet()
    packet["output_storage_path"] = "docs/implementation/asr-live-eval-output.json"

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        validate_asr_live_eval_approval_packet(packet)

    assert captured.value.failure_reasons == ["output_storage_path must be local-only"]


def test_unsafe_synthetic_input_set_path_fails_closed() -> None:
    packet = _approved_packet()
    packet["synthetic_input_set_path"] = "audio/raw/asr-live-eval-inputs.jsonl"

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        validate_asr_live_eval_approval_packet(packet)

    assert captured.value.failure_reasons == ["synthetic_input_set_path is unsafe"]


def test_real_user_input_flag_fails_closed() -> None:
    packet = _approved_packet()
    packet["real_user_input_included"] = True

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        validate_asr_live_eval_approval_packet(packet)

    assert captured.value.failure_reasons == ["real user input is not allowed"]


def test_missing_forbidden_artifact_acknowledgement_fails_closed() -> None:
    packet = _approved_packet()
    packet["forbidden_commit_artifacts_acknowledged"] = False

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        validate_asr_live_eval_approval_packet(packet)

    assert captured.value.failure_reasons == [
        "forbidden commit artifacts must be acknowledged"
    ]


@pytest.mark.parametrize(
    ("marker", "record"),
    (
        ("raw_audio", {"raw_audio": "audio://synthetic/asr/not-allowed"}),
        ("audio_bytes", {"audio_bytes": "AAAA"}),
        ("raw_transcript", {"raw_transcript": "not allowed"}),
        ("transcript_text", {"transcript_text": "not allowed"}),
        ("provider_request", {"provider_request": {"body": "not allowed"}}),
        ("provider_response", {"provider_response": {"body": "not allowed"}}),
        ("request_body", {"request_body": "not allowed"}),
        ("response_body", {"response_body": "not allowed"}),
        ("prompt_dump", {"prompt_dump": "not allowed"}),
        ("api_key", {"metadata_ref": "api_key=sk-synthetic-not-real"}),
        ("token", {"metadata_ref": "token=synthetic-not-real"}),
        ("authorization", {"metadata_ref": "authorization=synthetic-not-real"}),
        ("credential", {"metadata_ref": "credential=synthetic-not-real"}),
        ("password", {"metadata_ref": "password=synthetic-not-real"}),
        ("Bearer", {"metadata_ref": "Bearer synthetic-not-real"}),
        ("local path", {"metadata_ref": "/Users/a123/local/audio.wav"}),
    ),
)
def test_synthetic_input_forbidden_raw_provider_or_secret_markers_fail_closed(
    marker: str,
    record: dict[str, object],
) -> None:
    safe_record = dict(_safe_input_record())
    safe_record.update(record)

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        validate_asr_live_eval_synthetic_inputs((safe_record,))

    assert marker in captured.value.failure_reasons[0]


def test_complete_fake_approval_and_safe_synthetic_input_returns_dry_run_success() -> None:
    approval_metadata = validate_asr_live_eval_approval_packet(_approved_packet()).to_dict()
    records = load_asr_live_eval_synthetic_inputs(
        Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl")
    )

    summary = run_asr_live_eval_dry_run(
        approval_packet=_approved_packet(),
        input_records=records,
    )

    assert approval_metadata["approval_packet_complete"] is True
    assert approval_metadata["provider_call_allowed"] is True
    assert approval_metadata["secret_read_allowed"] is False
    assert summary == {
        "status": "would_run_provider_gated_synthetic_live_eval",
        "dry_run": True,
        "provider_call_allowed": True,
        "secret_read_allowed": False,
        "approved_eval_scope": "asr_provider_discovery_and_synthetic_live_eval",
        "provider_name": "Alibaba Cloud Bailian / DashScope",
        "model_alias": "qwen3-asr-flash",
        "model_alias_repin_date": "2026-06-15",
        "synthetic_input_record_count": 2,
        "max_request_count": 2,
        "per_request_timeout_ms": 30000,
        "retry_budget": 1,
        "output_storage_path": "diagnostics/asr/live-eval",
        "cleanup_policy": "delete_local_outputs_after_summary",
        "aggregate_metadata_commit_policy": "allowed_if_redacted_metadata_only",
        "raw_audio_included": False,
        "raw_transcript_included": False,
        "raw_provider_body_included": False,
        "headers_included": False,
        "secret_included": False,
        "real_user_input_included": False,
    }
    assert "audio_source_ref" not in repr(summary)
    assert "text_projection_ref" not in repr(summary)
    assert "provider_request" not in repr(summary)
    assert "provider_response" not in repr(summary)


def test_entrypoint_and_command_output_are_redacted_dry_run_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    packet_path = tmp_path / "approval-packet.md"
    packet_path.write_text(_markdown_packet_text(_approved_packet()), encoding="utf-8")

    metadata = run_asr_live_eval_entrypoint(
        approval_packet_path=packet_path,
        input_path=Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl"),
    )
    exit_code = main(
        [
            "--approval-packet",
            str(packet_path),
            "--input",
            "tests/fixtures/synthetic/asr-live-eval-inputs.jsonl",
        ]
    )
    printed = capsys.readouterr().out

    assert metadata["status"] == "would_run_provider_gated_synthetic_live_eval"
    assert exit_code == 0
    printed_json = json.loads(printed)
    assert printed_json["success"] is True
    assert printed_json["summary"]["provider_call_allowed"] is True
    assert printed_json["summary"]["secret_read_allowed"] is False
    assert "audio_source_ref" not in printed
    assert "text_projection_ref" not in printed
    assert "provider_request" not in printed
    assert "provider_response" not in printed
    assert "Bearer " not in printed


def test_missing_runtime_credential_fails_closed_before_transport_call() -> None:
    transport = _FakeAsrLiveTransport(("success",))

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        run_asr_synthetic_live_eval(
            approval_packet=_approved_packet(),
            input_records=load_asr_live_eval_synthetic_inputs(
                Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl")
            ),
            transport=transport,
            credential_handle=AsrLiveCredentialHandle(
                credential_ref="secret-ref://local/asr-live-eval/dashscope",
            ),
            credential_value=None,
        )

    assert captured.value.failure_reasons == ["credential value missing"]
    assert transport.calls == []
    assert "DASHSCOPE_API_KEY" not in repr(captured.value)


def test_delegated_model_selection_must_resolve_concrete_alias_before_provider_call() -> None:
    packet = _approved_packet()
    packet["model_alias"] = "asr-model-human-repin-required"
    transport = _FakeAsrLiveTransport(("success",))

    with pytest.raises(AsrLiveEvalApprovalError) as captured:
        run_asr_synthetic_live_eval(
            approval_packet=packet,
            input_records=load_asr_live_eval_synthetic_inputs(
                Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl")
            ),
            transport=transport,
            credential_handle=AsrLiveCredentialHandle(
                credential_ref="secret-ref://local/asr-live-eval/dashscope",
            ),
            credential_value="runtime-credential-value-for-test-only",
        )

    assert captured.value.failure_reasons == ["model_alias requires provider discovery re-pin"]
    assert transport.calls == []


def test_fake_transport_success_returns_metadata_only_live_eval_summary() -> None:
    transport = _FakeAsrLiveTransport(("success", "success"))

    summary = run_asr_synthetic_live_eval(
        approval_packet=_approved_packet(),
        input_records=load_asr_live_eval_synthetic_inputs(
            Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl")
        ),
        transport=transport,
        credential_handle=AsrLiveCredentialHandle(
            credential_ref="secret-ref://local/asr-live-eval/dashscope",
        ),
        credential_value="runtime-credential-value-for-test-only",
    )

    metadata = summary.to_metadata()
    assert metadata == {
        "attempted_request_count": 2,
        "success_count": 2,
        "request_failed_count": 0,
        "retry_count": 0,
        "timeout_count": 0,
        "failure_category_counts": {},
        "output_storage_path": "diagnostics/asr/live-eval",
        "cleanup_status": "delete_local_outputs_after_summary",
        "aggregate_metadata_commit_policy": "allowed_if_redacted_metadata_only",
        "raw_audio_included": False,
        "raw_transcript_included": False,
        "raw_provider_body_included": False,
        "headers_included": False,
        "secret_included": False,
        "provider_call_allowed": True,
        "real_user_input_included": False,
    }
    assert [call["model_alias"] for call in transport.calls] == [
        ASR_LIVE_SELECTED_MODEL_ALIAS,
        ASR_LIVE_SELECTED_MODEL_ALIAS,
    ]
    assert all(call["audio_payload_present"] is True for call in transport.calls)
    assert "runtime-credential-value-for-test-only" not in repr(metadata)
    assert "audio_source_ref" not in repr(metadata)
    assert "text_projection_ref" not in repr(metadata)
    assert "forbidden transcript" not in repr(metadata)
    assert "provider_response" not in repr(metadata)


def test_fake_transport_empty_transcript_is_redacted_failure() -> None:
    transport = _FakeAsrLiveTransport(("missing_transcript",))

    summary = run_asr_synthetic_live_eval(
        approval_packet=_approved_packet(max_request_count=1),
        input_records=load_asr_live_eval_synthetic_inputs(
            Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl")
        ),
        transport=transport,
        credential_handle=AsrLiveCredentialHandle(
            credential_ref="secret-ref://local/asr-live-eval/dashscope",
        ),
        credential_value="runtime-credential-value-for-test-only",
    )

    metadata = summary.to_metadata()
    assert metadata["attempted_request_count"] == 1
    assert metadata["success_count"] == 0
    assert metadata["request_failed_count"] == 1
    assert metadata["failure_category_counts"] == {
        "provider_transcript_absent": 1,
    }
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert "forbidden transcript" not in repr(metadata)


def test_fake_timeout_and_failure_return_redacted_metadata_only_summary() -> None:
    transport = _FakeAsrLiveTransport(("timeout", "failure"))

    summary = run_asr_synthetic_live_eval(
        approval_packet=_approved_packet(max_request_count=1),
        input_records=load_asr_live_eval_synthetic_inputs(
            Path("tests/fixtures/synthetic/asr-live-eval-inputs.jsonl")
        ),
        transport=transport,
        credential_handle=AsrLiveCredentialHandle(
            credential_ref="secret-ref://local/asr-live-eval/dashscope",
        ),
        credential_value="runtime-credential-value-for-test-only",
    )

    metadata = summary.to_metadata()
    assert metadata["attempted_request_count"] == 1
    assert metadata["success_count"] == 0
    assert metadata["request_failed_count"] == 1
    assert metadata["retry_count"] == 1
    assert metadata["timeout_count"] == 1
    assert metadata["failure_category_counts"] == {
        "provider_request_failed": 1,
        "provider_timeout": 1,
    }
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["headers_included"] is False
    assert metadata["secret_included"] is False
    assert "api_key" not in repr(metadata).lower()
    assert "runtime-credential-value-for-test-only" not in repr(metadata)


def test_approval_packet_repins_docs_and_selected_model_alias() -> None:
    text = ASR_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH.read_text(encoding="utf-8")
    packet = parse_asr_live_eval_approval_packet_markdown(text)
    metadata = validate_asr_live_eval_approval_packet(packet).to_dict()

    assert metadata["approval_packet_complete"] is True
    assert packet["approval_status"] == (
        "approved_for_asr_provider_discovery_and_synthetic_live_eval"
    )
    assert packet["approver"] == "a123"
    assert packet["approval_date"] == "2026-06-15"
    assert packet["provider_name"] == "Alibaba Cloud Bailian / DashScope"
    assert packet["model_alias"] == "qwen3-asr-flash"
    assert packet["model_alias_repin_date"] == "2026-06-15"
    assert (
        packet["provider_transport_allowance"]
        == "direct_http_only_preferred_sdk_allowed_only_if_official_docs_require_it"
    )
    assert "https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference" in text
    assert "https://help.aliyun.com/zh/model-studio/model-pricing" in text
    assert "DASHSCOPE_API_KEY=" not in text
    assert "api_key=" not in text.lower()
    assert "Bearer " not in text


def test_asr_live_eval_code_and_wrapper_do_not_import_provider_sdk() -> None:
    source_path = Path("src/voice_agent/adapters/asr_live_eval.py")
    transport_path = Path("src/voice_agent/adapters/asr_live_transport.py")
    script_path = Path("scripts/asr-live-eval")
    source = source_path.read_text(encoding="utf-8")
    transport_source = transport_path.read_text(encoding="utf-8")
    script = script_path.read_text(encoding="utf-8")
    imported_modules = _imported_modules(source)
    transport_imported_modules = _imported_modules(transport_source)

    forbidden_imports = {
        "dashscope",
        "openai",
        "requests",
        "http.client",
        "websocket",
        "websockets",
        "socket",
    }
    assert imported_modules.isdisjoint(forbidden_imports)
    assert transport_imported_modules.isdisjoint(forbidden_imports)
    for forbidden in (
        "OPENAI_API_KEY",
        "api_key=",
        "qwen_slow_llm_live_transport",
        "AsrAdapterContract",
        "FakeAsrTransport",
    ):
        assert forbidden not in source
        assert forbidden not in script
        assert forbidden not in transport_source


def test_business_modules_do_not_import_asr_live_transport() -> None:
    business_roots = (
        Path("src/voice_agent/access"),
        Path("src/voice_agent/checks"),
        Path("src/voice_agent/composer"),
        Path("src/voice_agent/demo_backend"),
        Path("src/voice_agent/duplex"),
        Path("src/voice_agent/events"),
        Path("src/voice_agent/interaction"),
        Path("src/voice_agent/replay"),
        Path("src/voice_agent/router"),
        Path("src/voice_agent/runtime"),
        Path("src/voice_agent/slowtask"),
        Path("src/voice_agent/state"),
        Path("src/voice_agent/talker"),
        Path("src/voice_agent/tools"),
        Path("src/voice_agent/understanding"),
        Path("src/voice_agent/user_patch"),
    )
    imported_modules: set[str] = set()
    for root in business_roots:
        for path in root.rglob("*.py"):
            imported_modules.update(_imported_modules(path.read_text(encoding="utf-8")))

    assert "voice_agent.adapters.asr_live_transport" not in imported_modules


def test_asr_live_eval_closeout_is_aggregate_metadata_only() -> None:
    closeout_path = Path("docs/implementation/asr-live-eval-closeout.md")
    text = closeout_path.read_text(encoding="utf-8")
    normalized = text.lower()

    for required_text in (
        "qwen3-asr-flash",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "approved synthetic live eval ran successfully",
        "attempted request count: 2",
        "success count: 2",
        "redacted failure categories: none",
        "not connected to business runtime",
        "no new canonical event",
        "no adr change",
        "no sdk import",
    ):
        assert required_text in normalized
    for forbidden in (
        "raw audio included: false",
        "raw transcript included: false",
        "raw provider body included: false",
        "headers included: false",
        "secret included: false",
    ):
        assert forbidden in normalized


def test_approval_template_documents_required_fields_and_forbidden_commit_artifacts() -> None:
    template = Path("docs/implementation/asr-live-eval-approval-template.md")
    text = template.read_text(encoding="utf-8")

    for field in ASR_LIVE_EVAL_REQUIRED_APPROVAL_FIELDS:
        assert f"- {field}:" in text
    for forbidden in (
        "raw audio",
        "raw transcript",
        "raw provider request body",
        "raw provider response body",
        "headers",
        "raw trace",
        "generated audio",
        "local replay cache",
        "secrets",
        "real user input",
        "large raw web content",
    ):
        assert forbidden in text
    assert "approval_status: pending" in text


def test_markdown_parser_handles_fake_packet_without_secret_values() -> None:
    packet = parse_asr_live_eval_approval_packet_markdown(
        _markdown_packet_text(_approved_packet())
    )

    assert packet == _approved_packet()
    assert "api_key=" not in repr(packet).lower()
    assert "Bearer " not in repr(packet)


def _approved_packet(*, max_request_count: int = 2) -> dict[str, object]:
    return {
        "approval_status": "approved_for_asr_provider_discovery_and_synthetic_live_eval",
        "approver": "a123",
        "approval_date": "2026-06-15",
        "approved_eval_scope": "asr_provider_discovery_and_synthetic_live_eval",
        "provider_name": "Alibaba Cloud Bailian / DashScope",
        "model_alias": "qwen3-asr-flash",
        "model_alias_repin_date": "2026-06-15",
        "provider_transport_allowance": "direct_http_only_preferred_sdk_allowed_only_if_official_docs_require_it",
        "credential_source": "runtime_only_user_provided_environment_or_shell_session",
        "credential_runtime_scope": "adapter_internal_call_time_only",
        "max_request_count": max_request_count,
        "max_cost_quota": "free_quota_only_stop_on_any_paid_or_quota_warning",
        "per_request_timeout_ms": 30000,
        "retry_budget": 1,
        "synthetic_input_set_path": "tests/fixtures/synthetic/asr-live-eval-inputs.jsonl",
        "input_redaction_status": "synthetic_metadata_refs_only",
        "real_user_input_included": False,
        "output_storage_path": "diagnostics/asr/live-eval",
        "redaction_policy": "metadata_only_no_raw_audio_transcript_or_provider_body",
        "cleanup_policy": "delete_local_outputs_after_summary",
        "aggregate_metadata_commit_policy": "allowed_if_redacted_metadata_only",
        "forbidden_commit_artifacts_acknowledged": True,
        "provider_endpoint_ref": "provider-url://dashscope/qwen-asr/openai-compatible-chat-completions",
        "provider_endpoint_shape": "openai_compatible_chat_completions_multimodal_input_audio_data_url",
        "docs_source_urls": "https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference, https://help.aliyun.com/zh/model-studio/model-pricing",
        "provider_sdk_assumption": "sdk_not_required_direct_http_only",
        "model_alias_basis": "official_qwen_asr_api_reference_checked_2026_06_15",
    }


def _safe_input_record() -> dict[str, object]:
    return {
        "case_id": "asr_synthetic_live_eval_001",
        "audio_source_ref": "audio-source://synthetic/asr/live-eval/001",
        "text_projection_ref": "text-projection://synthetic/asr/live-eval/001",
        "timing_metadata_ref": "timing://synthetic/asr/live-eval/001",
        "redaction_status": "synthetic_metadata_refs_only",
        "real_input": False,
        "artifact_retention": "metadata_refs_only",
    }


def _markdown_packet_text(packet: dict[str, object]) -> str:
    lines = ["# Synthetic ASR Approval Packet", ""]
    for key, value in packet.items():
        if isinstance(value, bool):
            rendered_value = str(value).lower()
        else:
            rendered_value = str(value)
        lines.append(f"- {key}: {rendered_value}")
    return "\n".join(lines) + "\n"


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


class _FakeAsrLiveTransport:
    def __init__(self, outcomes: tuple[str, ...]) -> None:
        self._outcomes = outcomes
        self.calls: list[dict[str, object]] = []
        self._next_index = 0

    def transcribe(
        self,
        *,
        audio_payload: bytes,
        audio_mime_type: str,
        credential_handle: AsrLiveCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> object:
        self.calls.append(
            {
                "audio_payload_present": len(audio_payload) > 0,
                "audio_mime_type": audio_mime_type,
                "credential_ref": credential_handle.credential_ref,
                "adapter_request_id": adapter_request_id,
                "timeout_ms": timeout_ms,
                "model_alias": model_alias,
            }
        )
        outcome = self._outcomes[min(self._next_index, len(self._outcomes) - 1)]
        self._next_index += 1
        if outcome == "timeout":
            raise DashScopeAsrLiveTransportError(
                "provider timeout",
                failure_reasons=("provider_timeout",),
                retryable=True,
                timeout=True,
            )
        if outcome == "failure":
            raise DashScopeAsrLiveTransportError(
                "provider request failed",
                failure_reasons=("provider_request_failed",),
                retryable=False,
            )
        if outcome == "missing_transcript":
            return _FakeAsrLiveCallMetadata(
                adapter_request_id=adapter_request_id,
                transcript_present=False,
            )
        return _FakeAsrLiveCallMetadata(
            adapter_request_id=adapter_request_id,
            transcript_present=True,
        )


class _FakeAsrLiveCallMetadata:
    def __init__(self, *, adapter_request_id: str, transcript_present: bool) -> None:
        self.adapter_request_id = adapter_request_id
        self.transcript_present = transcript_present

    def to_metadata(self) -> dict[str, object]:
        return {
            "adapter_request_id": self.adapter_request_id,
            "success": True,
            "transcript_present": self.transcript_present,
            "asr_frame_ref": f"asr-frame://provider/dashscope/{self.adapter_request_id}",
            "text_ref": f"text://provider/dashscope/{self.adapter_request_id}",
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "headers_included": False,
            "secret_included": False,
        }
