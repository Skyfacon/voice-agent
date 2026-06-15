from __future__ import annotations

import ast
import http.client
from pathlib import Path
import socket
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from tests.adapters.test_mvp3_asr_adapter_contract import (
    _append_committed_audio_turn,
    _github_allowed_replay_manifest,
)
from tests.runtime.test_asr_runtime_integration import _approved_packet
from voice_agent.adapters.asr_live_transport import (
    ASR_LIVE_DASHSCOPE_PROVIDER_URL_REF,
    ASR_LIVE_SELECTED_MODEL_ALIAS,
    DashScopeAsrLiveTransportError,
)
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.asr_session_hook import (
    ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL,
    ASR_SESSION_ASR_MODE_PROVIDER_FREE,
    AsrSessionAsrConfig,
    build_asr_session_capability_snapshot,
    run_asr_for_committed_audio_turn,
    run_asr_live_session_synthetic_smoke,
)
from voice_agent.runtime.session import start_configured_session


def test_provider_free_default_session_hook_does_not_call_provider_or_emit_asr() -> None:
    startup = _start_mvp3_session("sess_asr_live_hook_provider_free")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_live_hook_provider_free",
    )
    transport = _FakeSessionAsrTransport(("success",))

    result = run_asr_for_committed_audio_turn(
        journal=startup.journal,
        turn_committed_event=committed_turn,
        case_id="provider-free-default",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        transport=transport,
        approval_packet=_approved_packet(),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )

    assert result.to_metadata()["attempted_request_count"] == 0
    assert result.to_metadata()["hook_status"] == "skipped_provider_free"
    assert transport.calls == []
    assert "ASR_TRANSCRIPT_OUTPUT_EMITTED" not in {
        event["event_name"] for event in startup.journal.events()
    }


def test_opt_in_real_session_hook_emits_asr_after_matching_turn_commit() -> None:
    startup = _start_mvp3_session("sess_asr_live_hook_real_success")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_live_hook_real_success",
    )
    transport = _FakeSessionAsrTransport(("success",))

    result = run_asr_for_committed_audio_turn(
        journal=startup.journal,
        turn_committed_event=committed_turn,
        case_id="real-success",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        config=AsrSessionAsrConfig(mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL),
        transport=transport,
        approval_packet=_approved_packet(),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )

    emitted = startup.journal.events()[-3:]
    transcript = emitted[-1]

    assert [event["event_name"] for event in emitted] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    ]
    assert transcript["event_seq"] > committed_turn["event_seq"]
    assert transcript["caused_by_event_id"] == committed_turn["event_id"]
    assert transcript["turn_id"] == committed_turn["turn_id"]
    assert transcript["utterance_id"] == committed_turn["utterance_id"]
    assert transcript["audio_span_id"] == committed_turn["audio_span_id"]
    assert transcript["asr_frame_ref"] == (
        "asr-frame://provider/dashscope/" + transport.calls[0]["adapter_request_id"]
    )
    assert transcript["text_ref"] == (
        "text://provider/dashscope/" + transport.calls[0]["adapter_request_id"]
    )
    assert "audio_timestamps_ref" not in transcript
    assert transcript["timestamp_status"] == "unavailable"
    assert transcript["streaming_status"] == "unsupported_final_only"
    assert transcript["output_mode"] == "degraded"
    assert transport.calls == [
        {
            "audio_payload_present": True,
            "audio_mime_type": "audio/wav",
            "adapter_request_id": transport.calls[0]["adapter_request_id"],
            "timeout_ms": 30000,
            "model_alias": ASR_LIVE_SELECTED_MODEL_ALIAS,
        }
    ]
    assert str(committed_turn["event_id"]).replace("-", "_") in str(
        transport.calls[0]["adapter_request_id"]
    )
    assert result.to_metadata()["emitted_event_names"] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    ]
    assert "runtime-credential-value-for-test-only" not in repr(startup.journal.events())

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )
    assert replay_result.result_status == "passed"


def test_missing_approval_fails_closed_before_session_hook_transport_call(tmp_path: Path) -> None:
    startup = _start_mvp3_session("sess_asr_live_hook_missing_approval")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_live_hook_missing_approval",
    )
    transport = _FakeSessionAsrTransport(("success",))

    with pytest.raises(Exception, match="approval packet missing"):
        run_asr_for_committed_audio_turn(
            journal=startup.journal,
            turn_committed_event=committed_turn,
            case_id="missing-approval",
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            config=AsrSessionAsrConfig(
                mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL,
                approval_packet_path=tmp_path / "missing-approval.md",
            ),
            transport=transport,
            env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
            created_monotonic_ms=300,
            created_wall_clock_ms=1700000000300,
        )

    assert transport.calls == []


def test_missing_credential_fails_closed_before_session_hook_transport_call() -> None:
    startup = _start_mvp3_session("sess_asr_live_hook_missing_credential")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_live_hook_missing_credential",
    )
    transport = _FakeSessionAsrTransport(("success",))

    with pytest.raises(Exception) as captured:
        run_asr_for_committed_audio_turn(
            journal=startup.journal,
            turn_committed_event=committed_turn,
            case_id="missing-credential",
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            config=AsrSessionAsrConfig(mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL),
            transport=transport,
            approval_packet=_approved_packet(),
            env={},
            created_monotonic_ms=300,
            created_wall_clock_ms=1700000000300,
        )

    assert "DASHSCOPE_API_KEY" not in repr(captured.value)
    assert transport.calls == []


def test_malformed_or_absent_transcript_emits_validation_failed_event() -> None:
    startup = _start_mvp3_session("sess_asr_live_hook_validation_failure")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_live_hook_validation_failure",
    )

    result = run_asr_for_committed_audio_turn(
        journal=startup.journal,
        turn_committed_event=committed_turn,
        case_id="missing-transcript",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        config=AsrSessionAsrConfig(mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL),
        transport=_FakeSessionAsrTransport(("missing_transcript",)),
        approval_packet=_approved_packet(),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )

    assert startup.journal.events()[-1]["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    assert result.to_metadata()["validation_failure_count"] == 1
    assert "ASR_TRANSCRIPT_OUTPUT_EMITTED" not in result.to_metadata()["emitted_event_names"]


def test_timeout_retry_and_final_failure_emit_existing_adapter_events() -> None:
    startup = _start_mvp3_session("sess_asr_live_hook_timeout")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_live_hook_timeout",
    )

    result = run_asr_for_committed_audio_turn(
        journal=startup.journal,
        turn_committed_event=committed_turn,
        case_id="timeout",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        config=AsrSessionAsrConfig(mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL),
        transport=_FakeSessionAsrTransport(("timeout", "timeout")),
        approval_packet=_approved_packet(),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )

    assert result.to_metadata()["retry_count"] == 1
    assert result.to_metadata()["timeout_count"] == 2
    assert result.to_metadata()["emitted_event_names"] == [
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_REQUEST_FAILED",
    ]


def test_timeout_retry_then_success_calls_transport_twice() -> None:
    startup = _start_mvp3_session("sess_asr_live_hook_retry_then_success")
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix="evt_asr_live_hook_retry_then_success",
    )
    transport = _FakeSessionAsrTransport(("timeout", "success"))

    result = run_asr_for_committed_audio_turn(
        journal=startup.journal,
        turn_committed_event=committed_turn,
        case_id="retry-then-success",
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        config=AsrSessionAsrConfig(mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL),
        transport=transport,
        approval_packet=_approved_packet(max_request_count=1, retry_budget=1),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )

    assert len(transport.calls) == 2
    assert result.to_metadata()["success_count"] == 1
    assert result.to_metadata()["retry_count"] == 1
    assert result.to_metadata()["timeout_count"] == 1
    assert result.to_metadata()["emitted_event_names"] == [
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    ]


def test_replay_startup_and_business_runtime_do_not_import_or_probe_asr_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _block_network_probe_attempts(monkeypatch)

    startup = _start_mvp3_session("sess_asr_live_hook_no_probe")
    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert replay_result.result_status == "passed"
    assert calls == []
    for root in (
        Path("src/voice_agent/runtime"),
        Path("src/voice_agent/replay"),
        Path("src/voice_agent/router"),
        Path("src/voice_agent/slowtask"),
        Path("src/voice_agent/composer"),
    ):
        imported_modules: set[str] = set()
        for path in root.rglob("*.py"):
            imported_modules.update(_imported_modules(path.read_text(encoding="utf-8")))
        assert "voice_agent.adapters.asr_live_transport" not in imported_modules


def test_session_hook_capability_snapshot_distinguishes_real_fallback_degraded() -> None:
    snapshot = build_asr_session_capability_snapshot(
        configs=(
            AsrSessionAsrConfig(
                mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL,
                adapter_id="asr_session_real",
            ),
            AsrSessionAsrConfig(
                mode=ASR_SESSION_ASR_MODE_PROVIDER_FREE,
                adapter_id="asr_session_fallback",
                output_mode="fallback",
            ),
            AsrSessionAsrConfig(
                mode=ASR_SESSION_ASR_MODE_PROVIDER_FREE,
                adapter_id="asr_session_degraded",
                output_mode="degraded",
            ),
        ),
        approval_packet=_approved_packet(),
        capability_snapshot_ref="capability://synthetic/runtime/asr/session-hook",
        capability_version="mvp3.asr.session-hook.v1",
    )

    assert snapshot["adapter_ids"] == [
        "asr_session_real",
        "asr_session_fallback",
        "asr_session_degraded",
    ]
    assert snapshot["output_modes"] == ["real", "fallback", "degraded"]


def test_live_session_synthetic_smoke_runs_through_session_hook_and_returns_metadata_only() -> None:
    summary = run_asr_live_session_synthetic_smoke(
        config=AsrSessionAsrConfig(mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL),
        approval_packet=_approved_packet(),
        input_records=(
            {
                "case_id": "asr_live_session_smoke_001",
                "audio_source_ref": "audio-source://synthetic/asr/live-session/001",
                "text_projection_ref": "text-projection://synthetic/asr/live-session/001",
                "timing_metadata_ref": "timing://synthetic/asr/live-session/001",
                "redaction_status": "synthetic_metadata_refs_only",
                "real_input": False,
                "artifact_retention": "metadata_refs_only",
            },
        ),
        env={"DASHSCOPE_API_KEY": "runtime-credential-value-for-test-only"},
        transport=_FakeSessionAsrTransport(("success",)),
    ).to_metadata()

    assert summary["attempted_request_count"] == 1
    assert summary["success_count"] == 1
    assert summary["failure_count"] == 0
    assert summary["event_names"] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    ]
    assert summary["output_modes"] == ["degraded"]
    assert summary["provider_alias"] == "Alibaba Cloud Bailian / DashScope"
    assert summary["model_alias"] == ASR_LIVE_SELECTED_MODEL_ALIAS
    assert summary["provider_transport"] == "direct_http"
    assert summary["hook_path"] == "session_level_opt_in_asr_hook"
    assert summary["raw_audio_included"] is False
    assert summary["raw_transcript_included"] is False
    assert summary["raw_provider_body_included"] is False
    assert summary["secret_included"] is False
    assert "runtime-credential-value-for-test-only" not in repr(summary)


def _start_mvp3_session(session_id: str) -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_asr_live_session_hook_synthetic",
        runtime_config_ref="config://synthetic/mvp3/asr-live-session-hook",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/asr-live-session-hook",
            capability_version="mvp3.contract.v1",
        ),
        capabilities=valid_mvp3_real_profiles(),
    )


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


class _FakeSessionAsrTransport:
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
            return _FakeSessionAsrMetadata(adapter_request_id, transcript_present=False)
        return _FakeSessionAsrMetadata(adapter_request_id, transcript_present=True)


class _FakeSessionAsrMetadata:
    def __init__(self, adapter_request_id: str, *, transcript_present: bool) -> None:
        self.adapter_request_id = adapter_request_id
        self.transcript_present = transcript_present

    def to_metadata(self) -> dict[str, object]:
        return {
            "adapter_request_id": self.adapter_request_id,
            "provider_transport": "direct_http",
            "provider_url_ref": ASR_LIVE_DASHSCOPE_PROVIDER_URL_REF,
            "model_alias": ASR_LIVE_SELECTED_MODEL_ALIAS,
            "success": True,
            "transcript_present": self.transcript_present,
            "asr_frame_ref": f"asr-frame://provider/dashscope/{self.adapter_request_id}",
            "text_ref": f"text://provider/dashscope/{self.adapter_request_id}",
            "response_text_size_bucket": "small" if self.transcript_present else "empty",
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "headers_included": False,
            "secret_included": False,
        }
