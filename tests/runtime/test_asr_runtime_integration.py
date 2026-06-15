from __future__ import annotations

import ast
import http.client
import json
from pathlib import Path
import socket
from typing import Any
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import (
    valid_mvp3_real_profiles,
)
from tests.adapters.test_mvp3_asr_adapter_contract import (
    _append_committed_audio_turn,
    _github_allowed_replay_manifest,
)
from voice_agent.adapters.asr_live_transport import (
    ASR_LIVE_DASHSCOPE_PROVIDER_URL_REF,
    ASR_LIVE_SELECTED_MODEL_ALIAS,
    DashScopeAsrLiveTransportError,
)
from voice_agent.adapters.asr_runtime_adapter import (
    ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL,
    ASR_RUNTIME_MODE_PROVIDER_FREE,
    AsrRuntimeAdapter,
    AsrRuntimeConfig,
    AsrRuntimeError,
    build_asr_runtime_capability_profile,
    run_asr_runtime_synthetic_smoke,
)
from voice_agent.adapters.profiles import build_capability_snapshot
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


def test_provider_free_default_does_not_call_provider_or_emit_real_asr() -> None:
    startup = _start_mvp3_runtime_session("sess_asr_runtime_provider_free_default")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_runtime_provider_free_default",
    )
    transport = _FakeRuntimeAsrTransport(("success",))
    adapter = AsrRuntimeAdapter(
        config=AsrRuntimeConfig(),
        journal=startup.journal,
        transport=transport,
    )

    with pytest.raises(AsrRuntimeError, match="provider_free"):
        adapter.transcribe_committed_turn(
            turn_committed_event=committed_turn,
            case_id="provider-free-default",
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            approval_packet=_approved_packet(),
            env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
            created_monotonic_ms=300,
            created_wall_clock_ms=1700000000300,
        )

    assert transport.calls == []
    assert "ASR_TRANSCRIPT_OUTPUT_EMITTED" not in {
        event["event_name"] for event in startup.journal.events()
    }


def test_explicit_real_runtime_mode_uses_transport_and_emits_asr_contract_events() -> None:
    startup = _start_mvp3_runtime_session("sess_asr_runtime_real_fake_transport")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_runtime_real_fake_transport",
    )
    transport = _FakeRuntimeAsrTransport(("success",))
    adapter = AsrRuntimeAdapter(
        config=AsrRuntimeConfig(mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL),
        journal=startup.journal,
        transport=transport,
    )

    summary = adapter.transcribe_committed_turn(
        turn_committed_event=committed_turn,
        case_id="fake-real-success",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        approval_packet=_approved_packet(),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )

    emitted = startup.journal.events()[-3:]
    assert [event["event_name"] for event in emitted] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    ]
    assert [event["missing_capability"] for event in emitted[:-1]] == [
        "supports_audio_timestamps",
        "supports_streaming_output",
    ]
    transcript = emitted[-1]
    assert transcript["caused_by_event_id"] == committed_turn["event_id"]
    assert transcript["asr_frame_ref"] == "asr-frame://synthetic/runtime/asr/fake-real-success"
    assert transcript["text_ref"] == "text://synthetic/runtime/asr/fake-real-success"
    assert transcript["timestamp_status"] == "unavailable"
    assert transcript["streaming_status"] == "unsupported_final_only"
    assert transcript["output_mode"] == "degraded"
    assert all(validate_event_envelope(event) == event for event in emitted)
    assert transport.calls == [
        {
            "audio_payload_present": True,
            "audio_mime_type": "audio/wav",
            "adapter_request_id": "adapter_request_runtime_asr_fake_real_success",
            "timeout_ms": 30000,
            "model_alias": ASR_LIVE_SELECTED_MODEL_ALIAS,
        }
    ]
    assert summary.to_metadata()["emitted_event_names"] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    ]
    assert "runtime-credential-value-for-test-only" not in repr(startup.journal.events())
    assert "provider_response" not in repr(startup.journal.events())

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )
    assert replay_result.result_status == "passed"


def test_missing_approval_fails_closed_before_transport_call(tmp_path: Path) -> None:
    startup = _start_mvp3_runtime_session("sess_asr_runtime_missing_approval")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_runtime_missing_approval",
    )
    transport = _FakeRuntimeAsrTransport(("success",))
    adapter = AsrRuntimeAdapter(
        config=AsrRuntimeConfig(
            mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL,
            approval_packet_path=tmp_path / "missing-approval.md",
        ),
        journal=startup.journal,
        transport=transport,
    )

    with pytest.raises(AsrRuntimeError, match="approval packet missing"):
        adapter.transcribe_committed_turn(
            turn_committed_event=committed_turn,
            case_id="missing-approval",
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
            created_monotonic_ms=300,
            created_wall_clock_ms=1700000000300,
        )

    assert transport.calls == []


def test_missing_credential_fails_closed_before_transport_call() -> None:
    startup = _start_mvp3_runtime_session("sess_asr_runtime_missing_credential")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_runtime_missing_credential",
    )
    transport = _FakeRuntimeAsrTransport(("success",))
    adapter = AsrRuntimeAdapter(
        config=AsrRuntimeConfig(mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL),
        journal=startup.journal,
        transport=transport,
    )

    with pytest.raises(AsrRuntimeError) as captured:
        adapter.transcribe_committed_turn(
            turn_committed_event=committed_turn,
            case_id="missing-credential",
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            approval_packet=_approved_packet(),
            env={},
            created_monotonic_ms=300,
            created_wall_clock_ms=1700000000300,
        )

    assert captured.value.failure_reasons == ("runtime credential missing",)
    assert "DASHSCOPE_API_KEY" not in repr(captured.value)
    assert transport.calls == []


def test_runtime_maps_timeout_failure_and_validation_to_existing_adapter_events() -> None:
    startup = _start_mvp3_runtime_session("sess_asr_runtime_error_mapping")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_runtime_error_mapping",
    )
    adapter = AsrRuntimeAdapter(
        config=AsrRuntimeConfig(mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL),
        journal=startup.journal,
        transport=_FakeRuntimeAsrTransport(("timeout", "missing_transcript")),
    )

    timeout_summary = adapter.transcribe_committed_turn(
        turn_committed_event=committed_turn,
        case_id="timeout-case",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        approval_packet=_approved_packet(),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )
    validation_summary = adapter.transcribe_committed_turn(
        turn_committed_event=committed_turn,
        case_id="missing-transcript-case",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        approval_packet=_approved_packet(),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=400,
        created_wall_clock_ms=1700000000400,
    )

    event_names = [event["event_name"] for event in startup.journal.events()]
    assert "ADAPTER_REQUEST_RETRYING" in event_names
    assert "ADAPTER_REQUEST_FAILED" in event_names
    assert "ADAPTER_OUTPUT_VALIDATION_FAILED" in event_names
    assert timeout_summary.to_metadata()["failure_count"] == 1
    assert timeout_summary.to_metadata()["retry_count"] == 1
    assert validation_summary.to_metadata()["validation_failure_count"] == 1
    assert "ASR_TRANSCRIPT_OUTPUT_EMITTED" not in timeout_summary.to_metadata()[
        "emitted_event_names"
    ]
    assert "raw_provider_body" not in repr(startup.journal.events())


def test_runtime_smoke_helper_runs_one_synthetic_case_and_returns_metadata_only() -> None:
    summary = run_asr_runtime_synthetic_smoke(
        config=AsrRuntimeConfig(mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL),
        approval_packet=_approved_packet(),
        input_records=(_safe_input_record(),),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        transport=_FakeRuntimeAsrTransport(("success",)),
    ).to_metadata()

    assert summary["attempted_request_count"] == 1
    assert summary["success_count"] == 1
    assert summary["failure_count"] == 0
    assert summary["provider_alias"] == "Alibaba Cloud Bailian / DashScope"
    assert summary["model_alias"] == ASR_LIVE_SELECTED_MODEL_ALIAS
    assert summary["provider_transport"] == "direct_http"
    assert summary["event_names"] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    ]
    assert summary["output_modes"] == ["degraded"]
    assert summary["raw_audio_included"] is False
    assert summary["raw_transcript_included"] is False
    assert summary["raw_provider_body_included"] is False
    assert summary["secret_included"] is False
    assert "runtime-credential-value-for-test-only" not in json.dumps(summary)


def test_runtime_and_replay_modules_do_not_import_asr_live_transport() -> None:
    for root in (Path("src/voice_agent/runtime"), Path("src/voice_agent/replay")):
        imported_modules: set[str] = set()
        for path in root.rglob("*.py"):
            imported_modules.update(_imported_modules(path.read_text(encoding="utf-8")))

        assert "voice_agent.adapters.asr_live_transport" not in imported_modules


def test_asr_runtime_wrapper_has_no_provider_sdk_import_or_raw_closeout() -> None:
    wrapper_source = Path("src/voice_agent/adapters/asr_runtime_adapter.py").read_text(
        encoding="utf-8"
    )
    imported_modules = _imported_modules(wrapper_source)
    closeout = Path("docs/implementation/asr-runtime-integration-closeout.md").read_text(
        encoding="utf-8"
    )
    normalized_closeout = closeout.lower()

    assert imported_modules.isdisjoint(
        {
            "dashscope",
            "openai",
            "requests",
            "websocket",
            "websockets",
            "socket",
        }
    )
    for required_text in (
        "attempted request count: 1",
        "success count: 1",
        "failure count: 0",
    ):
        assert required_text in normalized_closeout
    for required_text in (
        "raw audio included: false",
        "raw transcript included: false",
        "raw provider body included: false",
        "secret included: false",
        "no raw audio",
        "no adr change",
        "canonical event change",
    ):
        assert required_text in normalized_closeout
    for forbidden in (
        "DASHSCOPE_API_KEY=",
        "api_key=",
        "Bearer ",
        "raw provider request body:",
        "raw provider response body:",
    ):
        assert forbidden not in closeout


def test_startup_and_replay_do_not_probe_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _block_network_probe_attempts(monkeypatch)

    startup = _start_mvp3_runtime_session("sess_asr_runtime_startup_no_probe")
    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert result.result_status == "passed"
    assert calls == []


def test_asr_runtime_capability_snapshot_distinguishes_modes() -> None:
    profiles = (
        build_asr_runtime_capability_profile(
            AsrRuntimeConfig(
                mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL,
                adapter_id="asr_runtime_real",
            ),
            approval_packet=_approved_packet(),
        ),
        build_asr_runtime_capability_profile(
            AsrRuntimeConfig(
                mode=ASR_RUNTIME_MODE_PROVIDER_FREE,
                adapter_id="asr_runtime_fallback",
                output_mode="fallback",
            )
        ),
        build_asr_runtime_capability_profile(
            AsrRuntimeConfig(
                mode=ASR_RUNTIME_MODE_PROVIDER_FREE,
                adapter_id="asr_runtime_degraded",
                output_mode="degraded",
            )
        ),
    )

    snapshot = build_capability_snapshot(
        [profile.to_dict() for profile in profiles],
        capability_snapshot_ref="capability://synthetic/runtime/asr/modes",
        capability_version="mvp3.asr.runtime.v1",
    )

    assert snapshot["adapter_ids"] == [
        "asr_runtime_real",
        "asr_runtime_fallback",
        "asr_runtime_degraded",
    ]
    assert snapshot["output_modes"] == ["real", "fallback", "degraded"]


def _start_mvp3_runtime_session(session_id: str) -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_asr_runtime_integration_synthetic",
        runtime_config_ref="config://synthetic/mvp3/asr-runtime-integration",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/asr-runtime-integration",
            capability_version="mvp3.contract.v1",
        ),
        capabilities=valid_mvp3_real_profiles(),
    )


def _approved_packet() -> dict[str, object]:
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
        "max_request_count": 2,
        "max_cost_quota": "free_quota_only_stop_on_any_paid_or_quota_warning",
        "per_request_timeout_ms": 30000,
        "retry_budget": 1,
        "synthetic_input_set_path": "tests/fixtures/synthetic/asr-live-eval-inputs.jsonl",
        "input_redaction_status": "synthetic_metadata_refs_only",
        "real_user_input_included": False,
        "output_storage_path": "diagnostics/asr/runtime-smoke",
        "redaction_policy": "metadata_only_no_raw_audio_transcript_or_provider_body",
        "cleanup_policy": "delete_local_outputs_after_summary",
        "aggregate_metadata_commit_policy": "allowed_if_redacted_metadata_only",
        "forbidden_commit_artifacts_acknowledged": True,
        "provider_endpoint_ref": ASR_LIVE_DASHSCOPE_PROVIDER_URL_REF,
        "provider_endpoint_shape": "openai_compatible_chat_completions_multimodal_input_audio_data_url",
        "docs_source_urls": "https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference, https://help.aliyun.com/zh/model-studio/model-pricing",
        "provider_sdk_assumption": "sdk_not_required_direct_http_only",
        "model_alias_basis": "official_qwen_asr_api_reference_checked_2026_06_15",
    }


def _safe_input_record() -> dict[str, object]:
    return {
        "case_id": "asr_runtime_smoke_001",
        "audio_source_ref": "audio-source://synthetic/asr/runtime-smoke/001",
        "text_projection_ref": "text-projection://synthetic/asr/runtime-smoke/001",
        "timing_metadata_ref": "timing://synthetic/asr/runtime-smoke/001",
        "redaction_status": "synthetic_metadata_refs_only",
        "real_input": False,
        "artifact_retention": "metadata_refs_only",
    }


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _block_network_probe_attempts(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("runtime startup/replay must not probe ASR provider")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_called)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_called)
    return calls


class _FakeRuntimeAsrTransport:
    def __init__(self, outcomes: tuple[str, ...]) -> None:
        self._outcomes = outcomes
        self._next_index = 0
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        *,
        audio_payload: bytes,
        audio_mime_type: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> object:
        self.calls.append(
            {
                "audio_payload_present": bool(audio_payload),
                "audio_mime_type": audio_mime_type,
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
        if outcome == "missing_transcript":
            return _FakeRuntimeAsrMetadata(adapter_request_id, transcript_present=False)
        return _FakeRuntimeAsrMetadata(adapter_request_id, transcript_present=True)


class _FakeRuntimeAsrMetadata:
    def __init__(self, adapter_request_id: str, *, transcript_present: bool) -> None:
        self.adapter_request_id = adapter_request_id
        self.transcript_present = transcript_present

    def to_metadata(self) -> dict[str, object]:
        return {
            "adapter_request_id": self.adapter_request_id,
            "provider_transport": "direct_http",
            "model_alias": ASR_LIVE_SELECTED_MODEL_ALIAS,
            "success": True,
            "transcript_present": self.transcript_present,
            "response_text_size_bucket": "small" if self.transcript_present else "empty",
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "headers_included": False,
            "secret_included": False,
        }
