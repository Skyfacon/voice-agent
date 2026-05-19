"""Observation builders for ASR streaming eval dry-runs."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .cases import CaseDefinition, select_cases
from .schema import SCHEMA_VERSION, validate_observation


DEFAULT_CONTRACT_SNAPSHOT = "main@61e6afc"


def build_observation(case: CaseDefinition, index: int, contract_snapshot: str) -> dict[str, Any]:
    transcript_ref = (
        f"asr-snippet://synthetic/{case.case_id}/{index:03d}"
        if case.transcript_present
        else None
    )
    failure_category = case.failure_category
    output_mode = "mock"

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_snapshot": contract_snapshot,
        "observation_id": f"obs_asr_qwen_synthetic_{index:03d}_{case.case_id}",
        "case_id": case.case_id,
        "adapter_type": "asr",
        "provider": "synthetic",
        "model_name": "synthetic_fixture",
        "deployment_mode": "synthetic",
        "endpoint_ref": "synthetic-dry-run",
        "output_mode": output_mode,
        "expected_evidence_label": case.expected_label,
        "degradation_reason": case.degradation_reason,
        "input_fixture": {
            "fixture_kind": case.fixture_kind,
            "input_modality": "audio",
            "audio_duration_ms": case.audio_duration_ms,
            "sample_rate_hz": case.sample_rate_hz,
            "channels": case.channels,
            "audio_format": case.audio_format,
            "contains_real_user_input": False,
            "contains_audio_in_report": False,
            "playback_reference_ref": (
                f"playback-ref://synthetic/{case.case_id}"
                if case.playback_echo_context
                else None
            ),
        },
        "request_observation": {
            "adapter_request_id": f"adapter_req_synthetic_{index:03d}",
            "streaming_input_mode": (
                "realtime_probe"
                if case.true_realtime_microphone_streaming_input_observed
                else "synthetic_metadata"
            ),
            "streaming_output_requested": case.response_streaming_output_observed,
            "timeout_ms": 10000,
            "retry_count": 1 if case.retryable and failure_category else 0,
        },
        "transcript_observation": {
            "transcript_present": case.transcript_present,
            "transcript_length_chars": case.transcript_length_chars,
            "stored_full_transcript": False,
            "synthetic_snippet_ref": transcript_ref,
            "reliable_directed_user_input": False,
        },
        "streaming_observation": {
            "response_streaming_output_observed": case.response_streaming_output_observed,
            "delta_chunk_count": case.delta_chunk_count,
            "first_delta_ms": case.first_delta_ms,
            "final_delta_ms": case.final_delta_ms,
            "true_realtime_microphone_streaming_input_observed": (
                case.true_realtime_microphone_streaming_input_observed
            ),
            "input_chunk_duration_ms": case.input_chunk_duration_ms,
            "input_cadence_ms": case.input_cadence_ms,
            "backpressure_observed": "unknown",
        },
        "timestamp_observation": {
            "timestamp_source": case.timestamp_source,
            "units": case.timestamp_units,
            "audio_offset_basis": case.audio_offset_basis,
            "segment_count": case.segment_count,
            "word_count": case.word_count,
            "normalized": case.timestamp_normalized,
            "normalization_status": case.timestamp_status,
            "degraded_reason": (
                None
                if case.timestamp_status == "normalized"
                else "timing_unavailable_or_not_normalized"
            ),
        },
        "quality_flags": {
            "expected_non_speech": case.expected_non_speech,
            "non_speech_transcript_risk": case.non_speech_transcript_risk,
            "clipped_start_case": case.clipped_start_case,
            "playback_echo_context": case.playback_echo_context,
            "low_volume_case": case.low_volume_case,
            "confidence_available": "unknown",
            "n_best_available": "unknown",
            "language_available": "unknown",
            "punctuation_available": "unknown",
            "itn_available": "unknown",
        },
        "failure_observation": {
            "failure_category": failure_category,
            "retryable": case.retryable,
            "provider_confirmed_cancellation": case.provider_confirmed_cancellation,
            "client_close_observed": case.client_close_observed,
            "late_output_policy": case.late_output_policy,
        },
        "privacy": {
            "stored_audio": False,
            "stored_provider_body": False,
            "stored_sensitive_access_material": False,
        },
        "boundary_assertions": {
            "asr_is_semantic_truth_owner": False,
            "asr_decides_turn_ingress": False,
            "asr_decides_confirmation": False,
            "asr_authorizes_tools": False,
            "deterministic_replay_reruns_asr": False,
        },
    }
    errors = validate_observation(record)
    if errors:
        raise ValueError(f"invalid synthetic observation {case.case_id}: {errors}")
    return record


def build_case_set(case_set: str, contract_snapshot: str) -> list[dict[str, Any]]:
    return [
        build_observation(case, index, contract_snapshot)
        for index, case in enumerate(select_cases(case_set), start=1)
    ]


def write_jsonl(records: list[dict[str, Any]], output_path: pathlib.Path) -> pathlib.Path:
    resolved = output_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    return resolved
