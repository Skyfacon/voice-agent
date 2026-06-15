from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from voice_agent.adapters.asr_live_eval import (
    ASR_LIVE_EVAL_REQUIRED_APPROVAL_FIELDS,
    AsrLiveEvalApprovalError,
    load_asr_live_eval_synthetic_inputs,
    main,
    parse_asr_live_eval_approval_packet_markdown,
    run_asr_live_eval_dry_run,
    run_asr_live_eval_entrypoint,
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
    assert approval_metadata["provider_call_allowed"] is False
    assert approval_metadata["secret_read_allowed"] is False
    assert summary == {
        "status": "would_run_dry_run_only",
        "dry_run": True,
        "provider_call_allowed": False,
        "secret_read_allowed": False,
        "approved_eval_scope": "synthetic_asr_live_eval_dry_run_only",
        "provider_name": "synthetic-asr-provider-placeholder",
        "model_alias": "asr-model-human-repin-2026-06-15",
        "model_alias_repin_date": "2026-06-15",
        "synthetic_input_record_count": 2,
        "max_request_count": 2,
        "per_request_timeout_ms": 15000,
        "retry_budget": 0,
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

    assert metadata["status"] == "would_run_dry_run_only"
    assert exit_code == 0
    printed_json = json.loads(printed)
    assert printed_json["success"] is True
    assert printed_json["summary"]["provider_call_allowed"] is False
    assert printed_json["summary"]["secret_read_allowed"] is False
    assert "audio_source_ref" not in printed
    assert "text_projection_ref" not in printed
    assert "provider_request" not in printed
    assert "provider_response" not in printed
    assert "Bearer " not in printed


def test_asr_live_eval_code_and_wrapper_do_not_import_provider_network_or_secret_apis() -> None:
    source_path = Path("src/voice_agent/adapters/asr_live_eval.py")
    script_path = Path("scripts/asr-live-eval")
    source = source_path.read_text(encoding="utf-8")
    script = script_path.read_text(encoding="utf-8")
    imported_modules = _imported_modules(source)

    forbidden_imports = {
        "dashscope",
        "openai",
        "requests",
        "urllib.request",
        "http.client",
        "websocket",
        "websockets",
        "socket",
        "os",
    }
    assert imported_modules.isdisjoint(forbidden_imports)
    for forbidden in (
        "os.environ",
        "getenv",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
        "api_key=",
        "Authorization",
        "Bearer ",
        "qwen_slow_llm_live_transport",
        "AsrAdapterContract",
        "FakeAsrTransport",
    ):
        assert forbidden not in source
        assert forbidden not in script


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


def _approved_packet() -> dict[str, object]:
    return {
        "approval_status": "approved_for_asr_synthetic_live_eval",
        "approver": "synthetic-human-approval-fixture",
        "approval_date": "2026-06-15",
        "approved_eval_scope": "synthetic_asr_live_eval_dry_run_only",
        "provider_name": "synthetic-asr-provider-placeholder",
        "model_alias": "asr-model-human-repin-2026-06-15",
        "model_alias_repin_date": "2026-06-15",
        "provider_transport_allowance": "dry_run_validation_only",
        "credential_source": "runtime_only_human_managed_no_value_in_packet",
        "credential_runtime_scope": "adapter_internal_call_time_only_future_goal",
        "max_request_count": 2,
        "max_cost_quota": "zero_cost_dry_run_only",
        "per_request_timeout_ms": 15000,
        "retry_budget": 0,
        "synthetic_input_set_path": "tests/fixtures/synthetic/asr-live-eval-inputs.jsonl",
        "input_redaction_status": "synthetic_metadata_refs_only",
        "real_user_input_included": False,
        "output_storage_path": "diagnostics/asr/live-eval",
        "redaction_policy": "metadata_only_no_raw_audio_transcript_or_provider_body",
        "cleanup_policy": "delete_local_outputs_after_summary",
        "aggregate_metadata_commit_policy": "allowed_if_redacted_metadata_only",
        "forbidden_commit_artifacts_acknowledged": True,
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
