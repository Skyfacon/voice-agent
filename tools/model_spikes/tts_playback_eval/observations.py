"""Observation builders for TTS playback eval dry-runs."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .cases import CaseDefinition, select_cases
from .schema import SCHEMA_VERSION, validate_observation


DEFAULT_CONTRACT_SNAPSHOT = "main@61e6afc"


def build_observation(case: CaseDefinition, index: int, contract_snapshot: str) -> dict[str, Any]:
    playback_span_id = f"playback_synthetic_{index:03d}" if case.playback_started else None
    truncate_request_event_id = (
        f"evt_tts_truncate_requested_{index:03d}" if case.truncate_requested else None
    )
    tts_truncated = case.actual_stop_offset_ms is not None and case.truncate_requested
    playback_committed = case.committed_offset_ms is not None

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_snapshot": contract_snapshot,
        "observation_id": f"obs_tts_playback_synthetic_{index:03d}_{case.case_id}",
        "case_id": case.case_id,
        "observation_kind": case.observation_kind,
        "output_mode": case.output_mode,
        "expected_evidence_label": case.expected_label,
        "degradation_reason": case.degradation_reason,
        "adapter_observation": {
            "adapter_type": "tts_talker",
            "provider": "synthetic",
            "model_name": "synthetic_fixture",
            "deployment_mode": "synthetic",
            "endpoint_ref": "synthetic-dry-run",
            "output_mode": case.output_mode,
        },
        "request_metadata": {
            "synthetic_input_ref": f"text_ref://synthetic/tts/{case.case_id}",
            "spoken_plan_id": (
                f"spoken_plan_synthetic_{index:03d}" if case.spoken_plan_approved else None
            ),
            "spoken_plan_approved": case.spoken_plan_approved,
            "risk_warning_preserved": case.risk_warning_preserved,
            "voice_id": case.voice_id,
            "format_requested": case.format_requested,
            "sample_rate_requested_hz": case.sample_rate_requested_hz,
            "word_timestamps_requested": True,
        },
        "stream_metadata": {
            "first_audio_latency_ms": case.first_audio_latency_ms,
            "total_synthesis_latency_ms": case.total_synthesis_latency_ms,
            "audio_duration_ms_estimated": case.audio_duration_ms_estimated,
            "audio_duration_basis": "synthetic_metadata_or_prior_run_bucket",
            "chunk_count": case.chunk_count,
            "audio_byte_count": case.audio_byte_count,
            "stream_end_reason": case.stream_end_reason,
            "provider_cancel_confirmed": case.provider_cancel_confirmed,
            "word_timestamp_events_observed": case.word_timestamp_events_observed,
            "format_observed": case.format_observed,
            "sample_rate_observed_hz": case.sample_rate_observed_hz,
            "mismatch_category": case.mismatch_category,
            "partial_audio": case.partial_audio,
        },
        "playback_metadata": {
            "playback_span_id": playback_span_id,
            "playback_started": case.playback_started,
            "progress_offsets_ms": list(case.progress_offsets_ms),
            "playback_committed": playback_committed,
            "committed_offset_ms": case.committed_offset_ms,
            "commit_basis": case.commit_basis,
            "final_playback_offset_ms": case.final_playback_offset_ms,
            "event_observations": list(case.event_observations),
        },
        "control_metadata": {
            "truncate_requested": case.truncate_requested,
            "truncate_request_event_id": truncate_request_event_id,
            "cutoff_playback_offset_ms": case.cutoff_playback_offset_ms,
            "tts_truncated": tts_truncated,
            "actual_stop_offset_ms": case.actual_stop_offset_ms,
            "local_playback_stop_observed": case.local_playback_stop_observed,
            "client_close_observed": case.client_close_observed,
            "timeout_observed": case.timeout_observed,
            "retry_count": case.retry_count,
            "retry_reason": case.retry_reason,
            "late_audio_chunk_count": case.late_audio_chunk_count,
            "late_audio_policy": case.late_audio_policy,
        },
        "privacy": {
            "generated_audio_stored": False,
            "provider_response_body_stored": False,
            "request_secret_material_stored": False,
            "deterministic_replay_reruns_tts": False,
            "playback_progress_uses_offsets_and_refs": True,
            "raw_audio_required_for_replay": False,
        },
        "boundary_assertions": {
            "talker_playback_owns_playback_state": True,
            "interaction_owns_truncate_request": True,
            "tts_adapter_only_provides_audio_metadata": True,
            "tts_output_is_user_acknowledgement": False,
            "tts_output_is_semantic_commitment": False,
            "tts_decides_confirmation": False,
            "tts_authorizes_tools": False,
            "tts_decides_task_completion": False,
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
