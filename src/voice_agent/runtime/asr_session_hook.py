from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
from typing import Any
import wave

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.events.journal import InMemoryEventJournal


ASR_SESSION_ASR_MODE_PROVIDER_FREE = "provider_free"
ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL = "approved_real_live_eval"
ASR_SESSION_ASR_MODES = frozenset(
    {
        ASR_SESSION_ASR_MODE_PROVIDER_FREE,
        ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL,
    }
)
ASR_SESSION_DEFAULT_ADAPTER_ID = "mvp3_asr"
ASR_SESSION_DEFAULT_PROVIDER_NAME = "Alibaba Cloud Bailian / DashScope"
ASR_SESSION_DEFAULT_MODEL_ALIAS = "qwen3-asr-flash"
ASR_SESSION_DEFAULT_TRANSPORT = "direct_http"
ASR_SESSION_CAPABILITY_VERSION = "mvp3.asr.session-hook.v1"
ASR_SESSION_DEFAULT_APPROVAL_PACKET_PATH = (
    "docs/implementation/asr-live-eval-approval-packet.md"
)
ASR_SESSION_DEFAULT_INPUT_PATH = "tests/fixtures/synthetic/asr-live-eval-inputs.jsonl"


class AsrSessionHookError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        failure_reasons: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_reasons = tuple(_safe_failure_reason(reason) for reason in (failure_reasons or (message,)))


@dataclass(frozen=True)
class AsrSessionAsrConfig:
    mode: str = ASR_SESSION_ASR_MODE_PROVIDER_FREE
    adapter_id: str = ASR_SESSION_DEFAULT_ADAPTER_ID
    output_mode: str | None = None
    approval_packet_path: str | Path = ASR_SESSION_DEFAULT_APPROVAL_PACKET_PATH
    input_path: str | Path = ASR_SESSION_DEFAULT_INPUT_PATH
    credential_env_var: str = "DASHSCOPE_API_KEY"
    credential_ref: str = "secret-ref://local/asr-session-hook/dashscope"
    runtime_config_ref: str = "config://synthetic/runtime/asr/session-hook/provider-free"
    capability_snapshot_ref: str = "capability://synthetic/runtime/asr/session-hook/provider-free"
    capability_version: str = ASR_SESSION_CAPABILITY_VERSION


@dataclass(frozen=True)
class AsrSessionHookSummary:
    attempted_request_count: int
    success_count: int
    failure_count: int
    validation_failure_count: int
    retry_count: int
    timeout_count: int
    failure_category_counts: tuple[tuple[str, int], ...]
    emitted_event_names: tuple[str, ...]
    output_modes: tuple[str, ...]
    provider_alias: str
    model_alias: str
    provider_transport: str
    hook_status: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "attempted_request_count": self.attempted_request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "validation_failure_count": self.validation_failure_count,
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "failure_category_counts": dict(self.failure_category_counts),
            "emitted_event_names": list(self.emitted_event_names),
            "output_modes": list(self.output_modes),
            "provider_alias": self.provider_alias,
            "model_alias": self.model_alias,
            "provider_transport": self.provider_transport,
            "hook_status": self.hook_status,
            "hook_path": "session_level_opt_in_asr_hook",
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "headers_included": False,
            "secret_included": False,
        }


@dataclass(frozen=True)
class AsrLiveSessionSmokeSummary:
    attempted_request_count: int
    success_count: int
    failure_count: int
    validation_failure_count: int
    retry_count: int
    timeout_count: int
    failure_category_counts: tuple[tuple[str, int], ...]
    event_names: tuple[str, ...]
    output_modes: tuple[str, ...]
    provider_alias: str
    model_alias: str
    provider_transport: str
    output_storage_path: str
    cleanup_status: str
    local_output_path_exists_after_cleanup: bool
    raw_artifact_absence_confirmed: bool

    def to_metadata(self) -> dict[str, object]:
        return {
            "attempted_request_count": self.attempted_request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "validation_failure_count": self.validation_failure_count,
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "failure_category_counts": dict(self.failure_category_counts),
            "event_names": list(self.event_names),
            "output_modes": list(self.output_modes),
            "provider_alias": self.provider_alias,
            "model_alias": self.model_alias,
            "provider_transport": self.provider_transport,
            "output_storage_path": self.output_storage_path,
            "cleanup_status": self.cleanup_status,
            "local_output_path_exists_after_cleanup": self.local_output_path_exists_after_cleanup,
            "raw_artifact_absence_confirmed": self.raw_artifact_absence_confirmed,
            "hook_path": "session_level_opt_in_asr_hook",
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "headers_included": False,
            "secret_included": False,
            "real_user_input_included": False,
        }


def run_asr_for_committed_audio_turn(
    *,
    journal: InMemoryEventJournal,
    turn_committed_event: Mapping[str, Any],
    case_id: str,
    audio_payload: bytes,
    audio_mime_type: str,
    config: AsrSessionAsrConfig | None = None,
    transport: object | None = None,
    approval_packet: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> AsrSessionHookSummary:
    config = config or AsrSessionAsrConfig()
    _validate_config(config)
    _validate_committed_audio_turn(turn_committed_event)

    if config.mode == ASR_SESSION_ASR_MODE_PROVIDER_FREE:
        return AsrSessionHookSummary(
            attempted_request_count=0,
            success_count=0,
            failure_count=0,
            validation_failure_count=0,
            retry_count=0,
            timeout_count=0,
            failure_category_counts=(),
            emitted_event_names=(),
            output_modes=(),
            provider_alias="provider_free",
            model_alias="provider_free_asr_session_hook",
            provider_transport="none",
            hook_status="skipped_provider_free",
        )

    runtime_config = _to_runtime_config(config)
    AsrRuntimeAdapter = _load_asr_runtime_adapter_class()
    adapter = AsrRuntimeAdapter(config=runtime_config, journal=journal, transport=transport)
    runtime_summary = adapter.transcribe_committed_turn(
        turn_committed_event=turn_committed_event,
        case_id=case_id,
        audio_payload=audio_payload,
        audio_mime_type=audio_mime_type,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        approval_packet=approval_packet,
        env=env,
    )
    metadata = runtime_summary.to_metadata()
    return AsrSessionHookSummary(
        attempted_request_count=int(metadata["attempted_request_count"]),
        success_count=int(metadata["success_count"]),
        failure_count=int(metadata["failure_count"]),
        validation_failure_count=int(metadata["validation_failure_count"]),
        retry_count=int(metadata["retry_count"]),
        timeout_count=int(metadata["timeout_count"]),
        failure_category_counts=tuple(
            sorted(
                (str(category), int(count))
                for category, count in dict(metadata["failure_category_counts"]).items()
            )
        ),
        emitted_event_names=tuple(str(name) for name in metadata["emitted_event_names"]),
        output_modes=tuple(str(mode) for mode in metadata["output_modes"]),
        provider_alias=str(metadata["provider_alias"]),
        model_alias=str(metadata["model_alias"]),
        provider_transport=str(metadata["provider_transport"]),
        hook_status="attempted_opt_in_asr",
    )


def build_asr_session_capability_snapshot(
    *,
    configs: Sequence[AsrSessionAsrConfig],
    approval_packet: Mapping[str, Any] | None = None,
    capability_snapshot_ref: str,
    capability_version: str,
) -> dict[str, Any]:
    _require_safe_non_empty_ref(capability_snapshot_ref, "capability_snapshot_ref")
    _require_safe_non_empty_ref(capability_version, "capability_version")
    build_profile, build_snapshot = _load_asr_runtime_profile_builders()
    profiles = [
        build_profile(_to_runtime_config(config), approval_packet=approval_packet).to_dict()
        for config in configs
    ]
    return build_snapshot(
        profiles,
        capability_snapshot_ref=capability_snapshot_ref,
        capability_version=capability_version,
    )


def run_asr_live_session_synthetic_smoke(
    *,
    config: AsrSessionAsrConfig,
    env: Mapping[str, str] | None = None,
    transport: object | None = None,
    approval_packet: Mapping[str, Any] | None = None,
    input_records: Sequence[Mapping[str, Any]] | None = None,
) -> AsrLiveSessionSmokeSummary:
    _validate_config(config)
    if config.mode != ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL:
        raise AsrSessionHookError(
            "ASR live session smoke requires approved_real_live_eval mode",
            failure_reasons=("real_runtime_mode_required",),
        )

    packet = _load_and_validate_approval_packet(config, approval_packet)
    records = _load_and_validate_input_records(config, input_records)
    selected_records = records[:1]
    journal, session_started = _build_live_session_smoke_journal(config, packet)
    aggregate = _SmokeAggregate()

    for index, record in enumerate(selected_records, start=1):
        case_id = str(record.get("case_id", f"asr-live-session-smoke-{index}"))
        committed_turn = _append_synthetic_committed_audio_turn(
            journal,
            caused_by_event_id=str(session_started["event_id"]),
            case_id=case_id,
            event_index=index,
        )
        summary = run_asr_for_committed_audio_turn(
            journal=journal,
            turn_committed_event=committed_turn,
            case_id=case_id,
            audio_payload=_build_synthetic_wav_bytes(),
            audio_mime_type="audio/wav",
            config=config,
            transport=transport,
            approval_packet=packet,
            env=env,
            created_monotonic_ms=300 + index * 100,
            created_wall_clock_ms=1700000000300 + index * 100,
        )
        aggregate.add(summary)

    output_storage_path = str(packet["output_storage_path"])
    cleanup_status = str(packet["cleanup_policy"])
    if cleanup_status == "delete_local_outputs_after_summary":
        shutil.rmtree(output_storage_path, ignore_errors=True)
    local_output_path_exists = Path(output_storage_path).exists()
    return AsrLiveSessionSmokeSummary(
        attempted_request_count=aggregate.attempted_request_count,
        success_count=aggregate.success_count,
        failure_count=aggregate.failure_count,
        validation_failure_count=aggregate.validation_failure_count,
        retry_count=aggregate.retry_count,
        timeout_count=aggregate.timeout_count,
        failure_category_counts=tuple(sorted(aggregate.failure_category_counts.items())),
        event_names=tuple(aggregate.event_names),
        output_modes=tuple(sorted(aggregate.output_modes)),
        provider_alias=str(packet["provider_name"]),
        model_alias=str(packet["model_alias"]),
        provider_transport=ASR_SESSION_DEFAULT_TRANSPORT,
        output_storage_path=output_storage_path,
        cleanup_status=cleanup_status,
        local_output_path_exists_after_cleanup=local_output_path_exists,
        raw_artifact_absence_confirmed=not local_output_path_exists,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run approved synthetic ASR through the opt-in live-session hook."
    )
    parser.add_argument(
        "--approval-packet",
        default=ASR_SESSION_DEFAULT_APPROVAL_PACKET_PATH,
    )
    parser.add_argument(
        "--input",
        default=ASR_SESSION_DEFAULT_INPUT_PATH,
    )
    args = parser.parse_args(argv)

    try:
        summary = run_asr_live_session_synthetic_smoke(
            config=AsrSessionAsrConfig(
                mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL,
                approval_packet_path=Path(args.approval_packet),
                input_path=Path(args.input),
                runtime_config_ref="config://synthetic/runtime/asr/session-hook/approved-real-live-eval",
                capability_snapshot_ref="capability://synthetic/runtime/asr/session-hook/approved-real-live-eval",
            ),
            env=os.environ,
        )
    except Exception as exc:
        failure_reasons = tuple(
            _safe_failure_reason(reason)
            for reason in getattr(exc, "failure_reasons", ("asr_live_session_smoke_failed",))
        )
        print(
            json.dumps(
                {
                    "success": False,
                    "failure_reasons": list(failure_reasons),
                    "raw_audio_included": False,
                    "raw_transcript_included": False,
                    "raw_provider_body_included": False,
                    "headers_included": False,
                    "secret_included": False,
                },
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps({"success": True, "summary": summary.to_metadata()}, sort_keys=True))
    return 0


@dataclass
class _SmokeAggregate:
    attempted_request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    validation_failure_count: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    failure_category_counts: Counter[str] | None = None
    event_names: list[str] | None = None
    output_modes: set[str] | None = None

    def __post_init__(self) -> None:
        if self.failure_category_counts is None:
            self.failure_category_counts = Counter()
        if self.event_names is None:
            self.event_names = []
        if self.output_modes is None:
            self.output_modes = set()

    def add(self, summary: AsrSessionHookSummary) -> None:
        metadata = summary.to_metadata()
        self.attempted_request_count += int(metadata["attempted_request_count"])
        self.success_count += int(metadata["success_count"])
        self.failure_count += int(metadata["failure_count"])
        self.validation_failure_count += int(metadata["validation_failure_count"])
        self.retry_count += int(metadata["retry_count"])
        self.timeout_count += int(metadata["timeout_count"])
        assert self.failure_category_counts is not None
        assert self.event_names is not None
        assert self.output_modes is not None
        self.failure_category_counts.update(
            {
                str(category): int(count)
                for category, count in dict(metadata["failure_category_counts"]).items()
            }
        )
        self.event_names.extend(str(name) for name in metadata["emitted_event_names"])
        self.output_modes.update(str(mode) for mode in metadata["output_modes"])


def _build_live_session_smoke_journal(
    config: AsrSessionAsrConfig,
    approval_packet: Mapping[str, Any],
) -> tuple[InMemoryEventJournal, dict[str, Any]]:
    snapshot = build_asr_session_capability_snapshot(
        configs=(config,),
        approval_packet=approval_packet,
        capability_snapshot_ref=config.capability_snapshot_ref,
        capability_version=config.capability_version,
    )
    journal = InMemoryEventJournal(
        session_id="sess_asr_live_session_smoke_synthetic",
        conversation_id="conv_asr_live_session_smoke_synthetic",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_asr_live_session_smoke_session_started",
        source_module="session_runtime",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        trace_redaction_level="metadata_only",
        runtime_config_ref=config.runtime_config_ref,
        capability_snapshot_ref=snapshot["capability_snapshot_ref"],
    )
    journal.append(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id="evt_asr_live_session_smoke_capability_snapshot",
        source_module="adapter_registry",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=101,
        created_wall_clock_ms=1700000000101,
        trace_redaction_level="metadata_only",
        **snapshot,
    )
    return journal, session_started


def _append_synthetic_committed_audio_turn(
    journal: InMemoryEventJournal,
    *,
    caused_by_event_id: str,
    case_id: str,
    event_index: int,
) -> dict[str, Any]:
    slug = _case_slug(case_id)
    audio_span_id = f"audio_live_session_asr_{event_index:03d}"
    turn_id = f"turn_live_session_asr_{event_index:03d}"
    utterance_id = f"utt_live_session_asr_{event_index:03d}"
    audio_started = journal.append(
        event_name="AUDIO_SPAN_STARTED",
        event_id=f"evt_live_session_asr_{slug}_audio_started",
        source_module="access_layer",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=110 + event_index,
        created_wall_clock_ms=1700000000110 + event_index,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/runtime/asr/live-session/wav-8khz-mono",
    )
    speech_started = journal.append(
        event_name="SPEECH_START_DETECTED",
        event_id=f"evt_live_session_asr_{slug}_speech_started",
        source_module="duplex",
        caused_by_event_id=str(audio_started["event_id"]),
        created_monotonic_ms=120 + event_index,
        created_wall_clock_ms=1700000000120 + event_index,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=0,
        vad_confidence=0.99,
    )
    journal.append(
        event_name="TURN_OPENED",
        event_id=f"evt_live_session_asr_{slug}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_started["event_id"]),
        created_monotonic_ms=130 + event_index,
        created_wall_clock_ms=1700000000130 + event_index,
        trace_redaction_level="metadata_only",
        turn_id=turn_id,
        audio_span_id=audio_span_id,
        input_modality="audio",
        turn_phase="COLLECTING_INPUT",
    )
    audio_ended = journal.append(
        event_name="AUDIO_SPAN_ENDED",
        event_id=f"evt_live_session_asr_{slug}_audio_ended",
        source_module="access_layer",
        caused_by_event_id=str(audio_started["event_id"]),
        created_monotonic_ms=160 + event_index,
        created_wall_clock_ms=1700000000160 + event_index,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=2000,
        duration_ms=250,
        end_reason="synthetic_live_session_smoke_complete",
    )
    speech_ended = journal.append(
        event_name="SPEECH_END_DETECTED",
        event_id=f"evt_live_session_asr_{slug}_speech_ended",
        source_module="duplex",
        caused_by_event_id=str(audio_ended["event_id"]),
        created_monotonic_ms=170 + event_index,
        created_wall_clock_ms=1700000000170 + event_index,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=2000,
        vad_confidence=0.99,
        silence_duration_ms=520,
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"evt_live_session_asr_{slug}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_ended["event_id"]),
        created_monotonic_ms=180 + event_index,
        created_wall_clock_ms=1700000000180 + event_index,
        trace_redaction_level="metadata_only",
        turn_id=turn_id,
        audio_span_id=audio_span_id,
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_live_session_asr_{slug}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=190 + event_index,
        created_wall_clock_ms=1700000000190 + event_index,
        trace_redaction_level="metadata_only",
        turn_id=turn_id,
        utterance_id=utterance_id,
        audio_span_id=audio_span_id,
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _load_and_validate_approval_packet(
    config: AsrSessionAsrConfig,
    approval_packet: Mapping[str, Any] | None,
) -> dict[str, Any]:
    (
        parse_asr_live_eval_approval_packet_markdown,
        validate_asr_live_eval_approval_packet,
        _,
        _,
    ) = _load_live_eval_helpers()
    try:
        packet = (
            dict(approval_packet)
            if approval_packet is not None
            else parse_asr_live_eval_approval_packet_markdown(
                Path(config.approval_packet_path).read_text(encoding="utf-8")
            )
        )
    except FileNotFoundError as exc:
        raise AsrSessionHookError(
            "approval packet missing",
            failure_reasons=("approval packet missing",),
        ) from exc
    except OSError as exc:
        raise AsrSessionHookError(
            "approval packet unavailable",
            failure_reasons=("approval packet unavailable",),
        ) from exc
    try:
        validate_asr_live_eval_approval_packet(packet)
    except Exception as exc:
        reasons = getattr(exc, "failure_reasons", ("approval packet invalid",))
        raise AsrSessionHookError("approval packet invalid", failure_reasons=reasons) from exc
    return packet


def _load_and_validate_input_records(
    config: AsrSessionAsrConfig,
    input_records: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    (
        _,
        _,
        load_asr_live_eval_synthetic_inputs,
        validate_asr_live_eval_synthetic_inputs,
    ) = _load_live_eval_helpers()
    return (
        validate_asr_live_eval_synthetic_inputs(input_records)
        if input_records is not None
        else load_asr_live_eval_synthetic_inputs(Path(config.input_path))
    )


def _load_live_eval_helpers() -> tuple[object, object, object, object]:
    from voice_agent.adapters.asr_live_eval import (
        load_asr_live_eval_synthetic_inputs,
        parse_asr_live_eval_approval_packet_markdown,
        validate_asr_live_eval_approval_packet,
        validate_asr_live_eval_synthetic_inputs,
    )

    return (
        parse_asr_live_eval_approval_packet_markdown,
        validate_asr_live_eval_approval_packet,
        load_asr_live_eval_synthetic_inputs,
        validate_asr_live_eval_synthetic_inputs,
    )


def _load_asr_runtime_adapter_class() -> object:
    from voice_agent.adapters.asr_runtime_adapter import AsrRuntimeAdapter

    return AsrRuntimeAdapter


def _load_asr_runtime_profile_builders() -> tuple[object, object]:
    from voice_agent.adapters.asr_runtime_adapter import build_asr_runtime_capability_profile
    from voice_agent.adapters.profiles import build_capability_snapshot

    return build_asr_runtime_capability_profile, build_capability_snapshot


def _to_runtime_config(config: AsrSessionAsrConfig) -> object:
    from voice_agent.adapters.asr_runtime_adapter import AsrRuntimeConfig

    return AsrRuntimeConfig(
        mode=config.mode,
        adapter_id=config.adapter_id,
        output_mode=config.output_mode,
        approval_packet_path=config.approval_packet_path,
        input_path=config.input_path,
        credential_env_var=config.credential_env_var,
        credential_ref=config.credential_ref,
        runtime_config_ref=config.runtime_config_ref,
        capability_snapshot_ref=config.capability_snapshot_ref,
        capability_version=config.capability_version,
    )


def _validate_config(config: AsrSessionAsrConfig) -> None:
    if config.mode not in ASR_SESSION_ASR_MODES:
        raise AsrSessionHookError(
            "unsupported ASR session hook mode",
            failure_reasons=("unsupported_asr_session_hook_mode",),
        )
    for field in (
        "adapter_id",
        "credential_env_var",
        "credential_ref",
        "runtime_config_ref",
        "capability_snapshot_ref",
        "capability_version",
    ):
        value = getattr(config, field)
        if not isinstance(value, str) or value == "":
            raise AsrSessionHookError(f"{field} must be a non-empty string")
        if field != "credential_env_var" and CREDENTIAL_LIKE_REF_PATTERN.search(value):
            raise AsrSessionHookError(f"{field} must be a safe ref")


def _validate_committed_audio_turn(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise AsrSessionHookError(
            "ASR session hook requires TURN_INGRESS_COMMITTED",
            failure_reasons=("turn_ingress_committed_required",),
        )
    if event.get("input_modality") != "audio" or event.get("audio_span_id") in (None, ""):
        raise AsrSessionHookError(
            "ASR session hook requires committed audio turn metadata",
            failure_reasons=("committed_audio_turn_required",),
        )


def _require_safe_non_empty_ref(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise AsrSessionHookError(f"{field} must be a non-empty string")
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        raise AsrSessionHookError(f"{field} must be a safe ref")
    return value


def _case_slug(value: str) -> str:
    slug = "".join(character if character.isalnum() or character in "-_" else "_" for character in value)
    return slug.replace("-", "_") or "synthetic_case"


def _safe_failure_reason(reason: object) -> str:
    if not isinstance(reason, str) or reason == "":
        return "asr_session_hook_failed"
    lowered = reason.lower()
    if (
        CREDENTIAL_LIKE_REF_PATTERN.search(reason)
        or "raw_provider_body" in lowered
        or "raw_transcript" in lowered
        or "raw_audio" in lowered
        or "authorization" in lowered
    ):
        return "redacted_failure"
    return reason


def _build_synthetic_wav_bytes() -> bytes:
    sample_rate = 8000
    duration_seconds = 0.25
    amplitude = 800
    frequency = 440
    frame_count = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for frame_index in range(frame_count):
            sample = int(amplitude * math.sin(2 * math.pi * frequency * frame_index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
