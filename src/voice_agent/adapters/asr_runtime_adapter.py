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

from voice_agent.adapters.asr_contract import AsrAdapterContract
from voice_agent.adapters.asr_live_eval import (
    ASR_LIVE_EVAL_CREDENTIAL_ENV_VAR,
    ASR_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH,
    ASR_LIVE_EVAL_DEFAULT_INPUT_PATH,
    load_asr_live_eval_synthetic_inputs,
    parse_asr_live_eval_approval_packet_markdown,
    validate_asr_live_eval_approval_packet,
    validate_asr_live_eval_synthetic_inputs,
)
from voice_agent.adapters.asr_live_transport import (
    ASR_LIVE_DASHSCOPE_PROVIDER_URL_REF,
    ASR_LIVE_SELECTED_MODEL_ALIAS,
    AsrLiveCredentialHandle,
    DashScopeAsrLiveDirectHTTPTransport,
    DashScopeAsrLiveTransportError,
)
from voice_agent.adapters.asr_normalization import (
    ASR_NORMALIZED_TRANSCRIPT_SCHEMA,
    AsrRequestBinding,
    emit_normalized_asr_candidate,
    normalize_asr_candidate,
)
from voice_agent.adapters.asr_profile import build_asr_capability_profile
from voice_agent.adapters.capabilities import AdapterCapability, CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.adapters.event_harness import FakeRealAdapterEventHarness
from voice_agent.adapters.profiles import build_capability_snapshot
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


ASR_RUNTIME_MODE_PROVIDER_FREE = "provider_free"
ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL = "approved_real_live_eval"
ASR_RUNTIME_MODES = frozenset(
    {
        ASR_RUNTIME_MODE_PROVIDER_FREE,
        ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL,
    }
)
ASR_RUNTIME_DEFAULT_ADAPTER_ID = "mvp3_asr"
ASR_RUNTIME_DEFAULT_PROVIDER_NAME = "Alibaba Cloud Bailian / DashScope"
ASR_RUNTIME_DEFAULT_TRANSPORT = "direct_http"
ASR_RUNTIME_CAPABILITY_VERSION = "mvp3.asr.runtime.v1"


class AsrRuntimeError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        failure_reasons: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_reasons = tuple(_safe_failure_reason(reason) for reason in (failure_reasons or (message,)))


@dataclass(frozen=True)
class AsrRuntimeConfig:
    mode: str = ASR_RUNTIME_MODE_PROVIDER_FREE
    adapter_id: str = ASR_RUNTIME_DEFAULT_ADAPTER_ID
    output_mode: str | None = None
    approval_packet_path: str | Path = ASR_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH
    input_path: str | Path = ASR_LIVE_EVAL_DEFAULT_INPUT_PATH
    credential_env_var: str = ASR_LIVE_EVAL_CREDENTIAL_ENV_VAR
    credential_ref: str = "secret-ref://local/asr-runtime/dashscope"
    runtime_config_ref: str = "config://synthetic/runtime/asr/provider-free"
    capability_snapshot_ref: str = "capability://synthetic/runtime/asr/provider-free"
    capability_version: str = ASR_RUNTIME_CAPABILITY_VERSION


@dataclass(frozen=True)
class AsrRuntimeTranscriptionSummary:
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
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "headers_included": False,
            "secret_included": False,
        }


@dataclass(frozen=True)
class AsrRuntimeSmokeSummary:
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
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "headers_included": False,
            "secret_included": False,
            "real_user_input_included": False,
        }


class AsrRuntimeAdapter:
    """Runtime ASR wrapper that keeps provider calls inside the adapter boundary."""

    def __init__(
        self,
        *,
        config: AsrRuntimeConfig,
        journal: InMemoryEventJournal,
        transport: object | None = None,
    ) -> None:
        _validate_runtime_config(config)
        self._config = config
        self._journal = journal
        self._boundary = AdapterCallbackAppendBoundary(journal)
        self._transport = transport

    def transcribe_committed_turn(
        self,
        *,
        turn_committed_event: Mapping[str, Any],
        case_id: str,
        audio_payload: bytes,
        audio_mime_type: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        approval_packet: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> AsrRuntimeTranscriptionSummary:
        if self._config.mode == ASR_RUNTIME_MODE_PROVIDER_FREE:
            raise AsrRuntimeError(
                "ASR runtime mode provider_free does not call real provider transport",
                failure_reasons=("provider_free_runtime_mode",),
            )
        _require_committed_turn_in_journal(self._journal, turn_committed_event)
        packet = _load_and_validate_approval_packet(self._config, approval_packet)
        _require_approval_request_capacity(
            journal=self._journal,
            adapter_id=self._config.adapter_id,
            max_request_count=int(packet["max_request_count"]),
        )
        credential_value = _credential_value_at_call_time(self._config, env)
        event_id_base = _runtime_event_id_base(case_id, turn_committed_event)
        binding = AsrRequestBinding.from_turn_committed_event(
            turn_committed_event,
            adapter_request_id=_adapter_request_id(case_id, turn_committed_event),
        )
        before_event_count = len(self._journal.events())

        retry_budget = int(packet["retry_budget"])
        retries_used = 0
        timeout_count = 0
        failure_reasons: list[str] = []
        while True:
            try:
                metadata = self._transport_or_default().transcribe(
                    audio_payload=audio_payload,
                    audio_mime_type=audio_mime_type,
                    credential_handle=AsrLiveCredentialHandle(
                        credential_ref=self._config.credential_ref,
                    ),
                    credential_value=credential_value,
                    adapter_request_id=binding.adapter_request_id,
                    timeout_ms=int(packet["per_request_timeout_ms"]),
                    model_alias=str(packet["model_alias"]),
                )
                break
            except DashScopeAsrLiveTransportError as exc:
                failure_reasons.extend(exc.failure_reasons)
                if exc.timeout:
                    timeout_count += 1
                if exc.retryable and retries_used < retry_budget:
                    retries_used += 1
                    self._emit_request_retrying(
                        binding=binding,
                        turn_committed_event=turn_committed_event,
                        event_id_base=event_id_base,
                        created_monotonic_ms=created_monotonic_ms + retries_used - 1,
                        created_wall_clock_ms=created_wall_clock_ms + retries_used - 1,
                        error=exc,
                        retry_count=retries_used,
                        timeout_ms=int(packet["per_request_timeout_ms"])
                        if exc.timeout
                        else None,
                    )
                    continue
                return self._emit_request_failure(
                    binding=binding,
                    turn_committed_event=turn_committed_event,
                    event_id_base=event_id_base,
                    created_monotonic_ms=created_monotonic_ms,
                    created_wall_clock_ms=created_wall_clock_ms,
                    error=exc,
                    retry_count=retries_used,
                    timeout_count=timeout_count,
                    failure_reasons=tuple(failure_reasons),
                    before_event_count=before_event_count,
                )

        metadata_map = _metadata_from_transport_result(metadata)
        if metadata_map.get("transcript_present") is not True:
            return self._emit_validation_failure(
                binding=binding,
                turn_committed_event=turn_committed_event,
                event_id_base=event_id_base,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                failure_reasons=("provider_transcript_absent",),
                before_event_count=before_event_count,
            )
        ref_failure_reasons: list[str] = []
        asr_frame_ref = _metadata_safe_ref(
            metadata_map,
            "asr_frame_ref",
            failure_reasons=ref_failure_reasons,
        )
        text_ref = _metadata_safe_ref(
            metadata_map,
            "text_ref",
            failure_reasons=ref_failure_reasons,
        )
        audio_timestamps_ref = _metadata_optional_safe_ref(
            metadata_map,
            "audio_timestamps_ref",
            failure_reasons=ref_failure_reasons,
        )
        if ref_failure_reasons:
            return self._emit_validation_failure(
                binding=binding,
                turn_committed_event=turn_committed_event,
                event_id_base=event_id_base,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                failure_reasons=tuple(ref_failure_reasons),
                before_event_count=before_event_count,
            )

        candidate = normalize_asr_candidate(
            binding=binding,
            asr_frame_ref=str(asr_frame_ref),
            text_ref=str(text_ref),
            audio_timestamps_ref=audio_timestamps_ref,
            timestamp_status="available" if audio_timestamps_ref else "unavailable",
            streaming_status="unsupported_final_only",
            output_mode="degraded",
        )
        contract = AsrAdapterContract(
            boundary=self._boundary,
            adapter_id=self._config.adapter_id,
            output_mode=candidate.output_mode,
        )
        emission = emit_normalized_asr_candidate(
            contract=contract,
            candidate=candidate,
            turn_committed_event=turn_committed_event,
            event_id=f"{event_id_base}_transcript",
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
        )
        emitted_events = self._journal.events()[before_event_count:]
        return AsrRuntimeTranscriptionSummary(
            attempted_request_count=1,
            success_count=1,
            failure_count=0,
            validation_failure_count=0,
            retry_count=retries_used,
            timeout_count=timeout_count,
            failure_category_counts=_failure_category_counts(failure_reasons),
            emitted_event_names=tuple(str(event["event_name"]) for event in emitted_events),
            output_modes=(str(emission.transcript_event["output_mode"]),),
            provider_alias=str(packet["provider_name"]),
            model_alias=str(packet["model_alias"]),
            provider_transport=ASR_RUNTIME_DEFAULT_TRANSPORT,
        )

    def _transport_or_default(self) -> object:
        if self._transport is not None:
            return self._transport
        return DashScopeAsrLiveDirectHTTPTransport()

    def _emit_request_retrying(
        self,
        *,
        binding: AsrRequestBinding,
        turn_committed_event: Mapping[str, Any],
        event_id_base: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        error: DashScopeAsrLiveTransportError,
        retry_count: int,
        timeout_ms: int | None,
    ) -> None:
        self._event_harness().emit_request_retrying(
            event_id=f"{event_id_base}_retrying_{retry_count}",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            retry_count=retry_count,
            retry_reason=_first_failure_reason(error.failure_reasons),
            timeout_ms=timeout_ms,
        )

    def _emit_request_failure(
        self,
        *,
        binding: AsrRequestBinding,
        turn_committed_event: Mapping[str, Any],
        event_id_base: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        error: DashScopeAsrLiveTransportError,
        retry_count: int,
        timeout_count: int,
        failure_reasons: Sequence[str],
        before_event_count: int,
    ) -> AsrRuntimeTranscriptionSummary:
        self._event_harness().emit_request_failed(
            event_id=f"{event_id_base}_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms + retry_count,
            created_wall_clock_ms=created_wall_clock_ms + retry_count,
            adapter_request_id=binding.adapter_request_id,
            failure_reason=_first_failure_reason(error.failure_reasons),
            retryable=error.retryable,
            timeout_ms=30000 if error.timeout else None,
        )
        emitted_events = self._journal.events()[before_event_count:]
        return AsrRuntimeTranscriptionSummary(
            attempted_request_count=1,
            success_count=0,
            failure_count=1,
            validation_failure_count=0,
            retry_count=retry_count,
            timeout_count=timeout_count,
            failure_category_counts=_failure_category_counts(failure_reasons),
            emitted_event_names=tuple(str(event["event_name"]) for event in emitted_events),
            output_modes=(),
            provider_alias=ASR_RUNTIME_DEFAULT_PROVIDER_NAME,
            model_alias=ASR_LIVE_SELECTED_MODEL_ALIAS,
            provider_transport=ASR_RUNTIME_DEFAULT_TRANSPORT,
        )

    def _emit_validation_failure(
        self,
        *,
        binding: AsrRequestBinding,
        turn_committed_event: Mapping[str, Any],
        event_id_base: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        failure_reasons: Sequence[str],
        before_event_count: int,
    ) -> AsrRuntimeTranscriptionSummary:
        self._event_harness().emit_output_validation_failed(
            event_id=f"{event_id_base}_validation_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            schema_name=ASR_NORMALIZED_TRANSCRIPT_SCHEMA,
            failure_reasons=tuple(_safe_failure_reason(reason) for reason in failure_reasons),
        )
        emitted_events = self._journal.events()[before_event_count:]
        return AsrRuntimeTranscriptionSummary(
            attempted_request_count=1,
            success_count=0,
            failure_count=1,
            validation_failure_count=1,
            retry_count=0,
            timeout_count=0,
            failure_category_counts=_failure_category_counts(failure_reasons),
            emitted_event_names=tuple(str(event["event_name"]) for event in emitted_events),
            output_modes=(),
            provider_alias=ASR_RUNTIME_DEFAULT_PROVIDER_NAME,
            model_alias=ASR_LIVE_SELECTED_MODEL_ALIAS,
            provider_transport=ASR_RUNTIME_DEFAULT_TRANSPORT,
        )

    def _event_harness(self) -> FakeRealAdapterEventHarness:
        return FakeRealAdapterEventHarness(
            boundary=self._boundary,
            adapter_id=self._config.adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="asr_adapter",
        )


def build_asr_runtime_capability_profile(
    config: AsrRuntimeConfig,
    *,
    approval_packet: Mapping[str, Any] | None = None,
) -> AdapterCapability:
    _validate_runtime_config(config)
    if config.mode == ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL:
        packet = _load_and_validate_approval_packet(config, approval_packet)
        return build_asr_capability_profile(
            adapter_id=config.adapter_id,
            provider=str(packet["provider_name"]),
            model_name=str(packet["model_alias"]),
            endpoint_ref=str(packet["provider_endpoint_ref"]),
            config_ref="config://runtime/asr/approved-real-live-eval",
            output_mode=config.output_mode or "real",
            deployment_mode="remote_api",
            supports_streaming_input=False,
            supports_streaming_output=False,
            supports_audio_timestamps=False,
            supports_cancellation=False,
            capability_version=config.capability_version,
            latency_class="remote_api_final_only",
            error_model="error-model://runtime/asr/dashscope/direct-http",
            timeout_policy="timeout-policy://runtime/asr/dashscope/live-eval",
            retry_policy="retry-policy://runtime/asr/dashscope/live-eval",
        )

    return build_asr_capability_profile(
        adapter_id=config.adapter_id,
        provider="provider_free",
        model_name="provider_free_asr_runtime",
        endpoint_ref="endpoint://synthetic/runtime/asr/provider-free",
        config_ref="config://synthetic/runtime/asr/provider-free",
        output_mode=config.output_mode or "degraded",
        deployment_mode="local",
        supports_streaming_input=False,
        supports_streaming_output=False,
        supports_audio_timestamps=False,
        supports_cancellation=False,
        capability_version=config.capability_version,
        latency_class="provider_free_runtime",
        error_model="error-model://synthetic/runtime/asr/provider-free",
        timeout_policy="timeout-policy://synthetic/runtime/asr/provider-free",
        retry_policy="retry-policy://synthetic/runtime/asr/provider-free",
        target_architecture_validation=False,
    )


def run_asr_runtime_synthetic_smoke(
    *,
    config: AsrRuntimeConfig,
    env: Mapping[str, str] | None = None,
    transport: object | None = None,
    approval_packet: Mapping[str, Any] | None = None,
    input_records: Sequence[Mapping[str, Any]] | None = None,
) -> AsrRuntimeSmokeSummary:
    if config.mode != ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL:
        raise AsrRuntimeError(
            "ASR runtime smoke requires approved_real_live_eval mode",
            failure_reasons=("real_runtime_mode_required",),
        )
    packet = _load_and_validate_approval_packet(config, approval_packet)
    records = (
        validate_asr_live_eval_synthetic_inputs(input_records)
        if input_records is not None
        else load_asr_live_eval_synthetic_inputs(Path(config.input_path))
    )
    selected_records = records[:1]
    journal, session_started = _build_runtime_smoke_journal(config, packet)
    adapter = AsrRuntimeAdapter(config=config, journal=journal, transport=transport)
    aggregate = _SmokeAggregate()

    for index, record in enumerate(selected_records, start=1):
        case_id = str(record.get("case_id", f"runtime-smoke-{index}"))
        committed_turn = _append_synthetic_audio_turn(
            journal,
            caused_by_event_id=str(session_started["event_id"]),
            case_id=case_id,
            event_index=index,
        )
        summary = adapter.transcribe_committed_turn(
            turn_committed_event=committed_turn,
            case_id=case_id,
            audio_payload=_build_synthetic_wav_bytes(),
            audio_mime_type="audio/wav",
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
    return AsrRuntimeSmokeSummary(
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
        provider_transport=ASR_RUNTIME_DEFAULT_TRANSPORT,
        output_storage_path=output_storage_path,
        cleanup_status=cleanup_status,
        local_output_path_exists_after_cleanup=local_output_path_exists,
        raw_artifact_absence_confirmed=not local_output_path_exists,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the approved synthetic ASR runtime smoke through the Event Journal wrapper."
    )
    parser.add_argument(
        "--approval-packet",
        default=str(ASR_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH),
    )
    parser.add_argument(
        "--input",
        default=str(ASR_LIVE_EVAL_DEFAULT_INPUT_PATH),
    )
    args = parser.parse_args(argv)

    try:
        summary = run_asr_runtime_synthetic_smoke(
            config=AsrRuntimeConfig(
                mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL,
                approval_packet_path=Path(args.approval_packet),
                input_path=Path(args.input),
                runtime_config_ref="config://synthetic/runtime/asr/approved-real-live-eval",
                capability_snapshot_ref="capability://synthetic/runtime/asr/approved-real-live-eval",
            ),
            env=os.environ,
        )
    except AsrRuntimeError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "failure_reasons": list(exc.failure_reasons),
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
        if self.event_names is None:
            self.event_names = []
        if self.failure_category_counts is None:
            self.failure_category_counts = Counter()
        if self.output_modes is None:
            self.output_modes = set()

    def add(self, summary: AsrRuntimeTranscriptionSummary) -> None:
        metadata = summary.to_metadata()
        self.attempted_request_count += int(metadata["attempted_request_count"])
        self.success_count += int(metadata["success_count"])
        self.failure_count += int(metadata["failure_count"])
        self.validation_failure_count += int(metadata["validation_failure_count"])
        self.retry_count += int(metadata["retry_count"])
        self.timeout_count += int(metadata["timeout_count"])
        assert self.event_names is not None
        assert self.failure_category_counts is not None
        assert self.output_modes is not None
        self.failure_category_counts.update(
            {
                str(category): int(count)
                for category, count in dict(metadata["failure_category_counts"]).items()
            }
        )
        self.event_names.extend(str(name) for name in metadata["emitted_event_names"])
        self.output_modes.update(str(mode) for mode in metadata["output_modes"])


def _build_runtime_smoke_journal(
    config: AsrRuntimeConfig,
    approval_packet: Mapping[str, Any],
) -> tuple[InMemoryEventJournal, dict[str, Any]]:
    capability = build_asr_runtime_capability_profile(
        config,
        approval_packet=approval_packet,
    )
    snapshot = build_capability_snapshot(
        [capability.to_dict()],
        capability_snapshot_ref=config.capability_snapshot_ref,
        capability_version=config.capability_version,
    )
    journal = InMemoryEventJournal(
        session_id="sess_asr_runtime_smoke_synthetic",
        conversation_id="conv_asr_runtime_smoke_synthetic",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_asr_runtime_smoke_session_started",
        source_module="session_runtime",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        trace_redaction_level="metadata_only",
        runtime_config_ref=config.runtime_config_ref,
        capability_snapshot_ref=snapshot["capability_snapshot_ref"],
    )
    journal.append(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id="evt_asr_runtime_smoke_capability_snapshot",
        source_module="adapter_registry",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=101,
        created_wall_clock_ms=1700000000101,
        trace_redaction_level="metadata_only",
        **snapshot,
    )
    return journal, session_started


def _append_synthetic_audio_turn(
    journal: InMemoryEventJournal,
    *,
    caused_by_event_id: str,
    case_id: str,
    event_index: int,
) -> dict[str, Any]:
    slug = _case_slug(case_id)
    audio_span_id = f"audio_runtime_asr_{event_index:03d}"
    turn_id = f"turn_runtime_asr_{event_index:03d}"
    utterance_id = f"utt_runtime_asr_{event_index:03d}"
    audio_started = journal.append(
        event_name="AUDIO_SPAN_STARTED",
        event_id=f"evt_runtime_asr_{slug}_audio_started",
        source_module="access_layer",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=110 + event_index,
        created_wall_clock_ms=1700000000110 + event_index,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/runtime/asr/wav-8khz-mono",
    )
    speech_started = journal.append(
        event_name="SPEECH_START_DETECTED",
        event_id=f"evt_runtime_asr_{slug}_speech_started",
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
        event_id=f"evt_runtime_asr_{slug}_turn_opened",
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
        event_id=f"evt_runtime_asr_{slug}_audio_ended",
        source_module="access_layer",
        caused_by_event_id=str(audio_started["event_id"]),
        created_monotonic_ms=160 + event_index,
        created_wall_clock_ms=1700000000160 + event_index,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=2000,
        duration_ms=250,
        end_reason="synthetic_runtime_smoke_complete",
    )
    speech_ended = journal.append(
        event_name="SPEECH_END_DETECTED",
        event_id=f"evt_runtime_asr_{slug}_speech_ended",
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
        event_id=f"evt_runtime_asr_{slug}_ingress_accepted",
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
        event_id=f"evt_runtime_asr_{slug}_ingress_committed",
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
    config: AsrRuntimeConfig,
    approval_packet: Mapping[str, Any] | None,
) -> dict[str, Any]:
    try:
        packet = (
            dict(approval_packet)
            if approval_packet is not None
            else parse_asr_live_eval_approval_packet_markdown(
                Path(config.approval_packet_path).read_text(encoding="utf-8")
            )
        )
    except FileNotFoundError as exc:
        raise AsrRuntimeError(
            "approval packet missing",
            failure_reasons=("approval packet missing",),
        ) from exc
    except OSError as exc:
        raise AsrRuntimeError(
            "approval packet unavailable",
            failure_reasons=("approval packet unavailable",),
        ) from exc

    try:
        validate_asr_live_eval_approval_packet(packet)
    except Exception as exc:
        reasons = getattr(exc, "failure_reasons", ("approval packet invalid",))
        raise AsrRuntimeError("approval packet invalid", failure_reasons=reasons) from exc
    if str(packet["model_alias"]) != ASR_LIVE_SELECTED_MODEL_ALIAS:
        raise AsrRuntimeError(
            "approval packet model alias is not selected ASR runtime alias",
            failure_reasons=("model_alias_not_selected",),
        )
    if (
        str(packet["provider_transport_allowance"])
        != "direct_http_only_preferred_sdk_allowed_only_if_official_docs_require_it"
    ):
        raise AsrRuntimeError(
            "approval packet transport allowance is not direct_http",
            failure_reasons=("transport_not_approved",),
        )
    return packet


def _validate_runtime_config(config: AsrRuntimeConfig) -> None:
    if config.mode not in ASR_RUNTIME_MODES:
        raise AsrRuntimeError("unsupported ASR runtime mode", failure_reasons=("unsupported_runtime_mode",))
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
            raise AsrRuntimeError(f"{field} must be a non-empty string")
        if field != "credential_env_var" and CREDENTIAL_LIKE_REF_PATTERN.search(value):
            raise AsrRuntimeError(f"{field} must be a safe ref")


def _credential_value_at_call_time(
    config: AsrRuntimeConfig,
    env: Mapping[str, str] | None,
) -> str:
    runtime_env = os.environ if env is None else env
    value = runtime_env.get(config.credential_env_var)
    if not isinstance(value, str) or value == "":
        raise AsrRuntimeError(
            "runtime credential missing",
            failure_reasons=("runtime credential missing",),
        )
    return value


def _metadata_from_transport_result(value: object) -> dict[str, Any]:
    if not hasattr(value, "to_metadata"):
        raise AsrRuntimeError(
            "ASR transport returned invalid metadata",
            failure_reasons=("transport_metadata_invalid",),
        )
    metadata = value.to_metadata()  # type: ignore[attr-defined]
    if not isinstance(metadata, Mapping):
        raise AsrRuntimeError(
            "ASR transport returned invalid metadata",
            failure_reasons=("transport_metadata_invalid",),
        )
    for flag in (
        "raw_audio_included",
        "raw_transcript_included",
        "raw_provider_request_included",
        "raw_provider_response_included",
        "headers_included",
        "authorization_header_included",
        "secret_included",
    ):
        if flag in metadata and metadata[flag] is not False:
            raise AsrRuntimeError(
                "ASR transport metadata contains forbidden marker",
                failure_reasons=("transport_metadata_forbidden_marker",),
            )
    rendered_values = repr(tuple(metadata.values()))
    if any(
        marker in rendered_values.lower()
        for marker in (
            "raw_transcript",
            "provider_response",
            "provider_request",
            "authorization",
            "api_key",
            "token=",
        )
    ):
        raise AsrRuntimeError(
            "ASR transport metadata contains forbidden marker",
            failure_reasons=("transport_metadata_forbidden_marker",),
        )
    return dict(metadata)


def _metadata_safe_ref(
    metadata: Mapping[str, Any],
    field: str,
    *,
    failure_reasons: list[str],
) -> str | None:
    value = metadata.get(field)
    if _is_safe_metadata_ref(value):
        return str(value)
    failure_reasons.append(f"provider_{field}_absent")
    return None


def _metadata_optional_safe_ref(
    metadata: Mapping[str, Any],
    field: str,
    *,
    failure_reasons: list[str],
) -> str | None:
    value = metadata.get(field)
    if value in (None, ""):
        return None
    if _is_safe_metadata_ref(value):
        return str(value)
    failure_reasons.append(f"provider_{field}_unsafe")
    return None


def _is_safe_metadata_ref(value: object) -> bool:
    if not isinstance(value, str) or value == "":
        return False
    lowered = value.lower()
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        return False
    forbidden_markers = (
        "raw_transcript",
        "raw_audio",
        "provider_request",
        "provider_response",
        "authorization",
        "api_key",
        "token=",
    )
    return not any(marker in lowered for marker in forbidden_markers)


def _require_committed_turn_in_journal(
    journal: InMemoryEventJournal,
    turn_committed_event: Mapping[str, Any],
) -> None:
    expected_event_id = str(turn_committed_event.get("event_id", ""))
    for event in journal.events():
        if event.get("event_id") != expected_event_id:
            continue
        if event.get("event_name") != "TURN_INGRESS_COMMITTED":
            break
        for field in ("turn_id", "utterance_id", "audio_span_id", "input_modality"):
            if event.get(field) != turn_committed_event.get(field):
                break
        else:
            return
        break
    raise AsrRuntimeError(
        "committed turn not in session journal",
        failure_reasons=("committed turn not in session journal",),
    )


def _require_approval_request_capacity(
    *,
    journal: InMemoryEventJournal,
    adapter_id: str,
    max_request_count: int,
) -> None:
    terminal_events = {
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
    }
    attempted_count = sum(
        1
        for event in journal.events()
        if event.get("event_name") in terminal_events
        and event.get("adapter_id") == adapter_id
        and event.get("adapter_type") == "asr"
    )
    if attempted_count >= max_request_count:
        raise AsrRuntimeError(
            "approval max_request_count exceeded",
            failure_reasons=("approval max_request_count exceeded",),
        )


def _adapter_request_id(case_id: str, turn_committed_event: Mapping[str, Any]) -> str:
    return (
        "adapter_request_runtime_asr_"
        f"{_case_slug(case_id)}_{_case_slug(str(turn_committed_event['event_id']))}"
    )


def _runtime_event_id_base(case_id: str, turn_committed_event: Mapping[str, Any]) -> str:
    return (
        "evt_runtime_asr_"
        f"{_case_slug(case_id)}_{_case_slug(str(turn_committed_event['event_id']))}"
    )


def _case_slug(value: str) -> str:
    slug = "".join(character if character.isalnum() or character in "-_" else "_" for character in value)
    return slug.replace("-", "_") or "synthetic_case"


def _ref_case_slug(value: str) -> str:
    slug = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    return slug or "synthetic-case"


def _first_failure_reason(reasons: Sequence[str]) -> str:
    if not reasons:
        return "request_failed"
    return _safe_failure_reason(reasons[0])


def _failure_category_counts(reasons: Sequence[str]) -> tuple[tuple[str, int], ...]:
    counter: Counter[str] = Counter()
    for reason in reasons:
        counter[_safe_failure_reason(reason)] += 1
    return tuple(sorted(counter.items()))


def _safe_failure_reason(reason: object) -> str:
    if not isinstance(reason, str) or reason == "":
        return "request_failed"
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
