from __future__ import annotations

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
from typing import Any
import wave

from voice_agent.adapters.capabilities import AdapterCapability, BOOLEAN_CAPABILITY_FIELDS
from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    LALMThinkerLiveDirectHTTPTransport,
    LALMThinkerLiveTransportError,
)
from voice_agent.adapters.lalm_thinker_profile import build_lalm_thinker_capability
from voice_agent.adapters.lalm_thinker_runtime_adapter import (
    LALM_THINKER_RUNTIME_ADAPTER_ID,
    LALM_THINKER_RUNTIME_CREDENTIAL_ENV_VAR,
    LALM_THINKER_RUNTIME_CREDENTIAL_REF,
    LALM_THINKER_RUNTIME_MODEL_ALIAS,
    LALM_THINKER_RUNTIME_TIMEOUT_MS,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    build_lalm_thinker_live_request_payload,
    emit_lalm_thinker_provider_text_result,
    emit_lalm_thinker_request_failed,
)
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


_SYNTHETIC_AUDIO_TEXT = "turn on the desk lamp"
_SYNTHETIC_AUDIO_INPUT_REF = (
    "audio://synthetic/lalm-thinker/audio-native-smoke/synthetic-speech-001"
)


def main() -> int:
    metadata = run_lalm_thinker_audio_native_smoke(repo_root=Path.cwd())
    print(json.dumps(metadata, sort_keys=True))
    return 0 if metadata["validated_count"] >= 1 else 1


def run_lalm_thinker_audio_native_smoke(
    *,
    repo_root: Path,
    env: Mapping[str, str] | None = None,
    transport: object | None = None,
    audio_bytes: bytes | None = None,
) -> dict[str, Any]:
    runtime_env = os.environ if env is None else env
    output_dir = _audio_native_output_dir(repo_root)
    credential_value = runtime_env.get(LALM_THINKER_RUNTIME_CREDENTIAL_ENV_VAR)

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
            local_audio_generated=False,
        )
        _write_summary(metadata, output_dir=output_dir)
        return metadata

    local_audio_generated = False
    if audio_bytes is None:
        audio_bytes = _generate_local_synthetic_speech_wav(output_dir)
        local_audio_generated = True

    startup = _start_audio_native_session()
    committed_turn = _append_synthetic_committed_audio_turn(startup.journal)
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    binding = bind_lalm_thinker_request(
        turn_committed_event=committed_turn,
        adapter_request_id="adapter-request-lalm-thinker-audio-native-001",
        request_metadata_ref="request-metadata://runtime/lalm-thinker/audio-native-smoke/001",
        input_ref=_SYNTHETIC_AUDIO_INPUT_REF,
        policy_ref="policy://runtime/lalm-thinker/evidence-only",
        expected_turn_committed_event_id=str(committed_turn["event_id"]),
    )
    live_transport = transport if transport is not None else LALMThinkerLiveDirectHTTPTransport()
    credential_handle = LALMThinkerCredentialHandle(
        credential_ref=LALM_THINKER_RUNTIME_CREDENTIAL_REF,
    )

    try:
        provider_text = live_transport.complete_audio(
            request_payload=build_lalm_thinker_live_request_payload(binding=binding),
            audio_bytes=audio_bytes,
            audio_format="wav",
            credential_handle=credential_handle,
            credential_value=credential_value,
            adapter_request_id=binding.adapter_request_id,
            timeout_ms=LALM_THINKER_RUNTIME_TIMEOUT_MS,
            model_alias=LALM_THINKER_RUNTIME_MODEL_ALIAS,
        )
    except LALMThinkerLiveTransportError as exc:
        request_failed = emit_lalm_thinker_request_failed(
            boundary=boundary,
            event_id="evt_lalm_thinker_audio_native_request_failed",
            caused_by_event_id=str(committed_turn["event_id"]),
            created_monotonic_ms=210,
            created_wall_clock_ms=1700000000210,
            adapter_request_id=binding.adapter_request_id,
            failure_reason=exc.category,
            retryable=False,
            timeout_ms=LALM_THINKER_RUNTIME_TIMEOUT_MS,
            adapter_id=LALM_THINKER_RUNTIME_ADAPTER_ID,
        )
        metadata = _metadata_summary(
            output_dir=output_dir,
            success=False,
            validated_count=0,
            validation_failed_count=0,
            request_failed_count=1,
            failure_category=str(request_failed["failure_reason"]),
            safe_refs=(),
            event_count=len(startup.journal.events()),
            local_audio_generated=local_audio_generated,
        )
        _write_summary(metadata, output_dir=output_dir)
        return metadata

    result = emit_lalm_thinker_provider_text_result(
        boundary=boundary,
        adapter_id=LALM_THINKER_RUNTIME_ADAPTER_ID,
        provider_text=provider_text,
        expected_binding=binding,
        success_event_id="evt_lalm_thinker_audio_native_semantic_frame",
        validation_failed_event_id="evt_lalm_thinker_audio_native_validation_failed",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
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
        request_failed_count=0,
        failure_category="provider_output_validation_failed" if not result.success else None,
        safe_refs=safe_refs,
        event_count=len(startup.journal.events()),
        local_audio_generated=local_audio_generated,
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
    local_audio_generated: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "success": success,
        "request_count": 1,
        "validated_count": validated_count,
        "validation_failed_count": validation_failed_count,
        "request_failed_count": request_failed_count,
        "provider_model_alias": LALM_THINKER_RUNTIME_MODEL_ALIAS,
        "provider_model_alias_recheck_date": "2026-06-15",
        "input_modality": "audio",
        "audio_input_mode": "native_audio",
        "audio_format": "wav",
        "audio_input_ref": _SYNTHETIC_AUDIO_INPUT_REF,
        "local_audio_generated": local_audio_generated,
        "audio_artifact_retention": "local_only_ignored",
        "credential_ref": LALM_THINKER_RUNTIME_CREDENTIAL_REF,
        "credential_value_included": False,
        "secret_included": False,
        "authorization_header_included": False,
        "bearer_token_included": False,
        "raw_provider_request_included": False,
        "raw_provider_response_included": False,
        "candidate_text_included": False,
        "raw_audio_included": False,
        "audio_bytes_retained": False,
        "raw_trace_included": False,
        "real_user_input_included": False,
        "full_prompt_included": False,
        "provider_native_tool_execution_included": False,
        "canonical_event_changes_included": False,
        "capability_profile_updated": False,
        "event_count": event_count,
        "safe_refs": list(safe_refs),
        "output_location": _relative_output_dir(output_dir),
        "output_file": f"{_relative_output_dir(output_dir)}/summary.json",
    }
    if failure_category is not None:
        metadata["failure_category"] = failure_category
        metadata["failure_ref"] = (
            f"validation://synthetic/lalm-thinker/audio-native-smoke/{_slug(failure_category)}"
        )
    return metadata


def _start_audio_native_session() -> object:
    return start_configured_session(
        session_id="sess_lalm_thinker_audio_native_smoke",
        conversation_id="conv_lalm_thinker_audio_native_smoke",
        runtime_config_ref="config://runtime/lalm-thinker/audio-native-smoke",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://runtime/lalm-thinker/audio-native-smoke",
            capability_version="mvp3.lalm-thinker.audio-native-smoke.v1",
        ),
        capabilities=(
            _supporting_capability("asr"),
            build_lalm_thinker_capability(),
            _supporting_capability("slow_llm"),
            _supporting_capability("tts"),
        ),
    )


def _append_synthetic_committed_audio_turn(journal: object) -> dict[str, object]:
    span_started = journal.append(
        event_name="AUDIO_SPAN_STARTED",
        event_id="evt_lalm_thinker_audio_native_span_started",
        source_module="access_layer",
        caused_by_event_id=str(journal.events()[1]["event_id"]),
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000000110,
        trace_redaction_level="metadata_only",
        audio_span_id="audio_lalm_thinker_audio_native_001",
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/lalm-thinker/pcm16-mono-16khz",
    )
    span_ended = journal.append(
        event_name="AUDIO_SPAN_ENDED",
        event_id="evt_lalm_thinker_audio_native_span_ended",
        source_module="access_layer",
        caused_by_event_id=str(span_started["event_id"]),
        created_monotonic_ms=111,
        created_wall_clock_ms=1700000000111,
        trace_redaction_level="metadata_only",
        audio_span_id="audio_lalm_thinker_audio_native_001",
        audio_sample_offset=16000,
        duration_ms=1000,
        end_reason="synthetic_audio_complete",
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id="evt_lalm_thinker_audio_native_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(span_ended["event_id"]),
        created_monotonic_ms=112,
        created_wall_clock_ms=1700000000112,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_audio_native_001",
        audio_span_id="audio_lalm_thinker_audio_native_001",
        input_modality="audio",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id="evt_lalm_thinker_audio_native_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=113,
        created_wall_clock_ms=1700000000113,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_audio_native_001",
        audio_span_id="audio_lalm_thinker_audio_native_001",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_lalm_thinker_audio_native_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=114,
        created_wall_clock_ms=1700000000114,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_audio_native_001",
        utterance_id="utt_lalm_thinker_audio_native_001",
        audio_span_id="audio_lalm_thinker_audio_native_001",
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _generate_local_synthetic_speech_wav(output_dir: Path) -> bytes:
    output_dir.mkdir(parents=True, exist_ok=True)
    aiff_path = output_dir / "synthetic-speech.aiff"
    wav_path = output_dir / "synthetic-speech.wav"
    if shutil.which("say") is not None and shutil.which("afconvert") is not None:
        try:
            subprocess.run(
                ["say", "-o", str(aiff_path), _SYNTHETIC_AUDIO_TEXT],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff_path), str(wav_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return wav_path.read_bytes()
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
    _generate_portable_synthetic_wav(wav_path)
    return wav_path.read_bytes()


def _generate_portable_synthetic_wav(wav_path: Path) -> None:
    sample_rate = 16_000
    duration_seconds = 1.0
    amplitude = 0.25
    frame_count = int(sample_rate * duration_seconds)
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(frame_count):
            value = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * index / sample_rate))
            wav_file.writeframes(struct.pack("<h", value))


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
        adapter_id=f"mvp3_{adapter_type}_audio_native_supporting",
        adapter_type=adapter_type,
        provider="audio_native_smoke_supporting",
        model_name=f"audio-native-smoke-supporting-{adapter_type}",
        deployment_mode="remote_api",
        endpoint=f"endpoint://audio-native-smoke/supporting/{adapter_type}",
        health_status="configured",
        capability_version="mvp3.audio-native-smoke.supporting.v1",
        latency_class="not_exercised",
        error_model=f"error-model://audio-native-smoke/supporting/{adapter_type}",
        timeout_policy=f"timeout-policy://audio-native-smoke/supporting/{adapter_type}",
        retry_policy=f"retry-policy://audio-native-smoke/supporting/{adapter_type}",
        output_mode="real",
        config_ref=f"config://audio-native-smoke/supporting/{adapter_type}",
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


def _audio_native_output_dir(repo_root: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return repo_root / "outputs" / "lalm-thinker" / "audio-native-smoke" / stamp


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
        return "outputs/lalm-thinker/audio-native-smoke/unknown"
    return "/".join(parts[outputs_index:])


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
