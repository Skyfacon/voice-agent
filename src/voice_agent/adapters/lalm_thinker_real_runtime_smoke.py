from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import time
from typing import Any

from voice_agent.adapters.capabilities import AdapterCapability, BOOLEAN_CAPABILITY_FIELDS
from voice_agent.adapters.lalm_thinker_profile import build_lalm_thinker_capability
from voice_agent.adapters.lalm_thinker_runtime_adapter import (
    LALMThinkerRuntimeAdapter,
    LALM_THINKER_RUNTIME_CREDENTIAL_ENV_VAR,
    LALM_THINKER_RUNTIME_CREDENTIAL_REF,
    LALM_THINKER_RUNTIME_MODEL_ALIAS,
)
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


def main() -> int:
    metadata = run_lalm_thinker_real_runtime_smoke(repo_root=Path.cwd())
    print(json.dumps(metadata, sort_keys=True))
    return 0 if metadata["validated_count"] >= 1 else 1


def run_lalm_thinker_real_runtime_smoke(
    *,
    repo_root: Path,
    env: Mapping[str, str] | None = None,
    transport: object | None = None,
) -> dict[str, Any]:
    runtime_env = os.environ if env is None else env
    credential_value = runtime_env.get(LALM_THINKER_RUNTIME_CREDENTIAL_ENV_VAR)
    output_dir = _runtime_smoke_output_dir(repo_root)

    if credential_value is None or credential_value == "":
        metadata = _metadata_summary(
            output_dir=output_dir,
            success=False,
            validated_count=0,
            validation_failed_count=0,
            request_failed_count=1,
            failure_category="credential_missing",
            safe_refs=(),
            event_count=0,
        )
        _write_summary(metadata, output_dir=output_dir)
        return metadata

    startup = _start_runtime_smoke_session()
    committed_turn = _append_synthetic_committed_text_turn(startup.journal)
    adapter = LALMThinkerRuntimeAdapter(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        env=runtime_env,
        transport=transport,
    )
    result = adapter.handle_turn_ingress_committed(
        committed_turn,
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
    )

    safe_refs: tuple[dict[str, str], ...] = ()
    if result.thinker_emission is not None:
        event = result.thinker_emission.thinker_event
        safe_refs = (
            {
                "thinker_event_id": str(event["event_id"]),
                "semantic_frame_ref": str(event["semantic_frame_ref"]),
                "semantic_summary_ref": str(event["semantic_summary_ref"]),
            },
        )
    metadata = _metadata_summary(
        output_dir=output_dir,
        success=result.success,
        validated_count=1 if result.success else 0,
        validation_failed_count=1 if result.validation_failed_event is not None else 0,
        request_failed_count=1 if result.request_failed_event is not None else 0,
        failure_category=result.failure_category,
        safe_refs=safe_refs,
        event_count=len(startup.journal.events()),
    )
    _write_summary(metadata, output_dir=output_dir)
    return metadata


def _metadata_summary(
    *,
    output_dir: Path,
    success: bool,
    validated_count: int,
    validation_failed_count: int,
    request_failed_count: int,
    failure_category: str | None,
    safe_refs: tuple[dict[str, str], ...],
    event_count: int,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "success": success,
        "request_count": 1,
        "validated_count": validated_count,
        "validation_failed_count": validation_failed_count,
        "request_failed_count": request_failed_count,
        "provider_model_alias": LALM_THINKER_RUNTIME_MODEL_ALIAS,
        "provider_model_alias_recheck_date": "2026-06-15",
        "credential_ref": LALM_THINKER_RUNTIME_CREDENTIAL_REF,
        "credential_value_included": False,
        "secret_included": False,
        "authorization_header_included": False,
        "bearer_token_included": False,
        "raw_provider_request_included": False,
        "raw_provider_response_included": False,
        "candidate_text_included": False,
        "raw_audio_included": False,
        "raw_trace_included": False,
        "real_user_input_included": False,
        "full_prompt_included": False,
        "provider_native_tool_execution_included": False,
        "canonical_event_changes_included": False,
        "event_count": event_count,
        "safe_refs": list(safe_refs),
        "output_location": _relative_output_dir(output_dir),
        "output_file": f"{_relative_output_dir(output_dir)}/summary.json",
    }
    if failure_category is not None:
        metadata["failure_category"] = failure_category
        metadata["failure_ref"] = (
            f"validation://synthetic/lalm-thinker/runtime-smoke/{_slug(failure_category)}"
        )
    return metadata


def _start_runtime_smoke_session() -> object:
    return start_configured_session(
        session_id="sess_lalm_thinker_real_runtime_smoke",
        conversation_id="conv_lalm_thinker_real_runtime_smoke",
        runtime_config_ref="config://runtime/lalm-thinker/real-runtime-smoke",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://runtime/lalm-thinker/real-runtime-smoke",
            capability_version="mvp3.lalm-thinker.runtime-smoke.v1",
        ),
        capabilities=(
            _supporting_capability("asr"),
            build_lalm_thinker_capability(),
            _supporting_capability("slow_llm"),
            _supporting_capability("tts"),
        ),
    )


def _append_synthetic_committed_text_turn(journal: object) -> dict[str, object]:
    text_received = journal.append(
        event_name="TEXT_INPUT_RECEIVED",
        event_id="evt_lalm_thinker_real_runtime_smoke_text_received",
        source_module="access_layer",
        caused_by_event_id=str(journal.events()[1]["event_id"]),
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000000110,
        trace_redaction_level="metadata_only",
        input_span_id="input_lalm_thinker_real_runtime_smoke_001",
        text_span_id="text_lalm_thinker_real_runtime_smoke_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        text_ref="text://synthetic/lalm-thinker/runtime-smoke/001",
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id="evt_lalm_thinker_real_runtime_smoke_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(text_received["event_id"]),
        created_monotonic_ms=111,
        created_wall_clock_ms=1700000000111,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_real_runtime_smoke_001",
        input_span_id="input_lalm_thinker_real_runtime_smoke_001",
        input_modality="text",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id="evt_lalm_thinker_real_runtime_smoke_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=112,
        created_wall_clock_ms=1700000000112,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_real_runtime_smoke_001",
        input_span_id="input_lalm_thinker_real_runtime_smoke_001",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_lalm_thinker_real_runtime_smoke_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=113,
        created_wall_clock_ms=1700000000113,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_real_runtime_smoke_001",
        utterance_id="utt_lalm_thinker_real_runtime_smoke_001",
        input_span_id="input_lalm_thinker_real_runtime_smoke_001",
        text_span_id="text_lalm_thinker_real_runtime_smoke_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _supporting_capability(adapter_type: str) -> AdapterCapability:
    capabilities: dict[str, object] = {
        "supports_streaming_input": False,
        "supports_streaming_output": False,
        "supports_audio_input": adapter_type == "asr",
        "supports_audio_output": adapter_type == "tts",
        "supports_audio_timestamps": False,
        "supports_structured_json": adapter_type in {"asr", "slow_llm"},
        "supports_tool_calling": False,
        "supports_cancellation": False,
        "supports_emotion": False,
        "supports_audio_caption": False,
        "supports_tts": adapter_type == "tts",
        "supports_tts_truncate": False,
        "supports_tts_pause_resume": False,
        "supports_semantic_close": False,
        "supports_assistant_directedness": False,
    }
    if adapter_type == "tts":
        capabilities["supports_structured_json"] = False
    return AdapterCapability(
        adapter_id=f"mvp3_{adapter_type}_runtime_smoke_supporting",
        adapter_type=adapter_type,
        provider="runtime_smoke_supporting",
        model_name=f"runtime-smoke-supporting-{adapter_type}",
        deployment_mode="remote_api",
        endpoint=f"endpoint://runtime-smoke/supporting/{adapter_type}",
        health_status="configured",
        capability_version="mvp3.runtime-smoke.supporting.v1",
        latency_class="not_exercised",
        error_model=f"error-model://runtime-smoke/supporting/{adapter_type}",
        timeout_policy=f"timeout-policy://runtime-smoke/supporting/{adapter_type}",
        retry_policy=f"retry-policy://runtime-smoke/supporting/{adapter_type}",
        output_mode="real",
        config_ref=f"config://runtime-smoke/supporting/{adapter_type}",
        max_audio_seconds=60 if adapter_type == "asr" else None,
        max_context_tokens=4096 if adapter_type in {"asr", "slow_llm"} else None,
        max_output_tokens=1024 if adapter_type in {"asr", "slow_llm"} else None,
        expected_first_token_latency_ms=None,
        expected_first_audio_latency_ms=None,
        mocked=False,
        mock_profile_ref="",
        target_architecture_validation=True,
        unsupported_capabilities=tuple(
            field for field in BOOLEAN_CAPABILITY_FIELDS if capabilities[field] is False
        ),
        **capabilities,
    )


def _runtime_smoke_output_dir(repo_root: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return repo_root / "outputs" / "lalm-thinker" / "runtime-smoke" / stamp


def _write_summary(metadata: Mapping[str, Any], *, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(dict(metadata), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _relative_output_dir(output_dir: Path) -> str:
    parts = output_dir.parts
    try:
        outputs_index = parts.index("outputs")
    except ValueError:
        return "outputs/lalm-thinker/runtime-smoke/unknown"
    return "/".join(parts[outputs_index:])


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
