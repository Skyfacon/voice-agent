from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.adapters.test_mvp3_adapter_profiles import mvp3_real_capability
from voice_agent.adapters.lalm_thinker_profile import build_lalm_thinker_capability
from voice_agent.adapters.lalm_thinker_real_runtime_smoke import (
    run_lalm_thinker_real_runtime_smoke,
)
from voice_agent.adapters.lalm_thinker_runtime_adapter import (
    LALMThinkerRuntimeAdapter,
    LALM_THINKER_RUNTIME_ADAPTER_ID,
    LALM_THINKER_RUNTIME_MODEL_ALIAS,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
)
from voice_agent.adapters.lalm_thinker_live_transport import LALMThinkerLiveTransportError
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


def test_default_lalm_thinker_runtime_profile_is_real_dashscope_adapter() -> None:
    capability = build_lalm_thinker_capability()

    assert capability.adapter_id == LALM_THINKER_RUNTIME_ADAPTER_ID
    assert capability.provider == "dashscope_bailian"
    assert capability.model_name == LALM_THINKER_RUNTIME_MODEL_ALIAS
    assert capability.deployment_mode == "remote_api"
    assert capability.output_mode == "real"
    assert capability.supports_structured_json is True
    assert capability.mocked is False
    assert "provider-free" not in repr(capability.to_dict()).lower()


def test_runtime_adapter_constructs_default_direct_http_metadata_without_provider_call() -> None:
    startup = _start_session()
    adapter = LALMThinkerRuntimeAdapter(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
    )

    metadata = adapter.to_metadata()

    assert metadata["adapter_id"] == LALM_THINKER_RUNTIME_ADAPTER_ID
    assert metadata["model_alias"] == LALM_THINKER_RUNTIME_MODEL_ALIAS
    assert metadata["credential_ref"] == "secret-ref://runtime-env/dashscope-api-key"
    assert metadata["provider_transport"] == "direct_http"
    assert metadata["raw_provider_request_included"] is False
    assert metadata["raw_provider_response_included"] is False
    assert "runtime-secret-value-for-test-only" not in repr(metadata)
    assert "Bearer " not in repr(metadata)


def test_missing_dashscope_api_key_fails_fast_before_transport_call() -> None:
    startup = _start_session(session_id="sess_lalm_thinker_runtime_missing_key")
    committed_turn = _append_committed_text_turn(startup.journal)
    transport = _RuntimeFakeTransport(mode="valid")
    adapter = LALMThinkerRuntimeAdapter(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        env={},
        transport=transport,
    )

    result = adapter.handle_turn_ingress_committed(
        committed_turn,
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
    )

    assert result.success is False
    assert result.failure_category == "credential_missing"
    assert transport.call_count == 0
    assert result.request_failed_event is not None
    assert result.request_failed_event["event_name"] == "ADAPTER_REQUEST_FAILED"
    assert result.request_failed_event["failure_reason"] == "credential_missing"
    assert result.request_failed_event["output_mode"] == "real"
    assert "DASHSCOPE_API_KEY" not in repr(result.request_failed_event)
    assert "runtime-secret-value-for-test-only" not in repr(startup.journal.events())


def test_valid_provider_text_emits_normalized_thinker_contract_event() -> None:
    startup = _start_session(session_id="sess_lalm_thinker_runtime_valid")
    committed_turn = _append_committed_text_turn(startup.journal)
    transport = _RuntimeFakeTransport(mode="valid")
    adapter = LALMThinkerRuntimeAdapter(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=transport,
    )

    result = adapter.handle_turn_ingress_committed(
        committed_turn,
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
    )

    assert result.success is True
    assert result.thinker_emission is not None
    assert result.validation_failed_event is None
    assert result.request_failed_event is None
    assert transport.call_count == 1
    thinker_event = result.thinker_emission.thinker_event
    assert thinker_event["event_name"] == "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"
    assert thinker_event["adapter_id"] == LALM_THINKER_RUNTIME_ADAPTER_ID
    assert thinker_event["output_mode"] == "real"
    assert thinker_event["caused_by_event_id"] == committed_turn["event_id"]
    assert thinker_event["semantic_frame_ref"].startswith(
        "semantic-frame://synthetic/lalm-thinker/adapter-owned/"
    )
    assert "provider_text" not in repr(result.to_metadata())
    assert "runtime-secret-value-for-test-only" not in repr(startup.journal.events())
    assert "Bearer " not in repr(startup.journal.events())


def test_invalid_provider_text_emits_validation_failure_without_thinker_event() -> None:
    startup = _start_session(session_id="sess_lalm_thinker_runtime_invalid")
    committed_turn = _append_committed_text_turn(startup.journal)
    adapter = LALMThinkerRuntimeAdapter(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=_RuntimeFakeTransport(mode="invalid"),
    )

    result = adapter.handle_turn_ingress_committed(
        committed_turn,
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
    )

    assert result.success is False
    assert result.thinker_emission is None
    assert result.validation_failed_event is not None
    assert result.validation_failed_event["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    assert result.validation_failed_event["schema_name"] == LALM_THINKER_CANDIDATE_SCHEMA_VERSION
    assert result.validation_failed_event["failure_reasons"] == ["fenced_markdown"]
    assert "```json" not in repr(result.validation_failed_event)
    assert "runtime-secret-value-for-test-only" not in repr(startup.journal.events())


def test_transport_failure_emits_safe_request_failed_metadata() -> None:
    startup = _start_session(session_id="sess_lalm_thinker_runtime_transport_failed")
    committed_turn = _append_committed_text_turn(startup.journal)
    adapter = LALMThinkerRuntimeAdapter(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=_RuntimeFakeTransport(mode="provider_request_failed"),
    )

    result = adapter.handle_turn_ingress_committed(
        committed_turn,
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
    )

    assert result.success is False
    assert result.failure_category == "provider_request_failed"
    assert result.request_failed_event is not None
    assert result.request_failed_event["failure_reason"] == "provider_request_failed"
    assert "raw body" not in repr(result.request_failed_event).lower()
    assert "runtime-secret-value-for-test-only" not in repr(startup.journal.events())


def test_replay_runner_does_not_import_runtime_adapter_or_live_transport() -> None:
    source = Path("src/voice_agent/replay/runner.py").read_text(encoding="utf-8")

    assert "lalm_thinker_runtime_adapter" not in source
    assert "lalm_thinker_live_transport" not in source
    assert "DASHSCOPE_API_KEY" not in source


def test_runtime_smoke_missing_key_writes_safe_metadata_without_transport_call(tmp_path: Path) -> None:
    transport = _RuntimeFakeTransport(mode="valid")

    metadata = run_lalm_thinker_real_runtime_smoke(
        repo_root=tmp_path,
        env={},
        transport=transport,
    )

    assert metadata["success"] is False
    assert metadata["validated_count"] == 0
    assert metadata["request_failed_count"] == 1
    assert metadata["failure_category"] == "credential_missing"
    assert metadata["credential_ref"] == "secret-ref://runtime-env/dashscope-api-key"
    assert metadata["credential_value_included"] is False
    assert transport.call_count == 0
    summary_path = tmp_path / metadata["output_file"]
    assert summary_path.exists()
    rendered = summary_path.read_text(encoding="utf-8")
    assert "DASHSCOPE_API_KEY" not in rendered
    assert "runtime-secret-value-for-test-only" not in rendered
    assert "Bearer " not in rendered
    assert "provider_text" not in rendered


def test_runtime_smoke_with_fake_transport_writes_validated_metadata_only(tmp_path: Path) -> None:
    transport = _RuntimeFakeTransport(mode="valid")

    metadata = run_lalm_thinker_real_runtime_smoke(
        repo_root=tmp_path,
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=transport,
    )

    assert metadata["success"] is True
    assert metadata["validated_count"] == 1
    assert metadata["validation_failed_count"] == 0
    assert metadata["request_failed_count"] == 0
    assert metadata["safe_refs"]
    assert metadata["raw_provider_request_included"] is False
    assert metadata["raw_provider_response_included"] is False
    summary_path = tmp_path / metadata["output_file"]
    assert summary_path.exists()
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted == metadata
    rendered = repr(metadata)
    assert "DASHSCOPE_API_KEY" not in rendered
    assert "runtime-secret-value-for-test-only" not in rendered
    assert "Bearer " not in rendered
    assert "provider_text" not in rendered


class _RuntimeFakeTransport:
    def __init__(self, *, mode: str) -> None:
        self.mode = mode
        self.call_count = 0

    def complete(
        self,
        *,
        request_payload: object,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        assert isinstance(request_payload, dict)
        assert credential_value == "runtime-secret-value-for-test-only"
        assert adapter_request_id.startswith("adapter-request-lalm-thinker-runtime-")
        assert timeout_ms == 60_000
        assert model_alias == LALM_THINKER_RUNTIME_MODEL_ALIAS
        assert "secret_materialized=False" in repr(credential_handle)
        self.call_count += 1
        if self.mode == "provider_request_failed":
            raise LALMThinkerLiveTransportError(
                "raw body must not leak",
                category="provider_request_failed",
                failure_reasons=("provider_request_failed",),
            )
        if self.mode == "invalid":
            return "```json\n{}\n```"
        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "calm"},
            "audio_caption": {"status": "available", "label": "caption_available"},
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


def _start_session(*, session_id: str = "sess_lalm_thinker_runtime") -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_lalm_thinker_runtime",
        runtime_config_ref="config://runtime/lalm-thinker/default-real",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://runtime/lalm-thinker/default-real",
            capability_version="mvp3.lalm-thinker.runtime.v1",
        ),
        capabilities=(
            mvp3_real_capability("asr"),
            build_lalm_thinker_capability(),
            mvp3_real_capability("slow_llm"),
            mvp3_real_capability("tts"),
        ),
    )


def _append_committed_text_turn(journal: object) -> dict[str, object]:
    text_received = journal.append(
        event_name="TEXT_INPUT_RECEIVED",
        event_id="evt_lalm_thinker_runtime_text_received",
        source_module="access_layer",
        caused_by_event_id=str(journal.events()[1]["event_id"]),
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000000110,
        trace_redaction_level="metadata_only",
        input_span_id="input_lalm_thinker_runtime_001",
        text_span_id="text_lalm_thinker_runtime_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        text_ref="text://synthetic/lalm-thinker/runtime-smoke-input",
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id="evt_lalm_thinker_runtime_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(text_received["event_id"]),
        created_monotonic_ms=111,
        created_wall_clock_ms=1700000000111,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_runtime_001",
        input_span_id="input_lalm_thinker_runtime_001",
        input_modality="text",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id="evt_lalm_thinker_runtime_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=112,
        created_wall_clock_ms=1700000000112,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_runtime_001",
        input_span_id="input_lalm_thinker_runtime_001",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_lalm_thinker_runtime_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=113,
        created_wall_clock_ms=1700000000113,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_runtime_001",
        utterance_id="utt_lalm_thinker_runtime_001",
        input_span_id="input_lalm_thinker_runtime_001",
        text_span_id="text_lalm_thinker_runtime_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
