"""Observation builders for Thinker / Composer eval dry-runs."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .cases import CaseDefinition, select_cases
from .schema import SCHEMA_VERSION, validate_observation


DEFAULT_CONTRACT_SNAPSHOT = "main@61e6afc"


def build_observation(case: CaseDefinition, index: int, contract_snapshot: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_snapshot": contract_snapshot,
        "observation_id": f"obs_thinker_composer_synthetic_{index:03d}_{case.case_id}",
        "case_id": case.case_id,
        "observation_kind": case.observation_kind,
        "expected_evidence_label": case.expected_label,
        "degradation_reason": case.degradation_reason,
        "candidate": {
            "adapter_type": case.adapter_type,
            "provider": "synthetic",
            "model_name": "synthetic_fixture",
            "deployment_mode": "synthetic",
            "endpoint_ref": "synthetic-dry-run",
            "output_mode": case.output_mode,
            "role_contract": case.role_contract,
        },
        "input_fixture": {
            "fixture_kind": case.fixture_kind,
            "input_modality": case.input_modality,
            "fixture_ref": f"thinker-composer-fixture://synthetic/{case.case_id}/001",
            "asr_frame_ref": _optional_ref(case, "asr"),
            "semantic_commitment_ref": _optional_ref(case, "commitment"),
            "external_evidence_ref": _optional_ref(case, "external"),
            "contains_real_user_input": False,
            "contains_raw_audio_in_report": False,
            "contains_provider_body_in_report": False,
        },
        "request_observation": {
            "adapter_request_id": f"adapter_req_synthetic_thinker_{index:03d}",
            "request_status": case.request_status,
            "calls_provider": False,
            "executes_tools": False,
            "imports_main_runtime": False,
            "streaming_output_requested": case.streaming_output_observed,
            "timeout_ms": 20000 if case.failure_category != "client_timeout" else 1,
        },
        "semantic_frame_observation": {
            "schema_parse_passed": case.schema_parse_passed,
            "schema_validation_passed": case.schema_validation_passed,
            "semantic_frame_not_commitment": case.semantic_frame_not_commitment,
            "provenance_preserved": case.provenance_preserved,
            "evidence_refs_separated": case.evidence_refs_separated,
            "ambiguity_preserved": case.ambiguity_preserved,
            "missing_slot_preserved": case.missing_slot_preserved,
            "asr_thinker_conflict_preserved": case.asr_thinker_conflict_preserved,
            "web_evidence_untrusted": case.web_evidence_untrusted,
            "web_evidence_trusted_as_instruction": case.web_evidence_trusted_as_instruction,
            "emotion_evidence_status": case.emotion_evidence_status,
            "audio_caption_status": case.audio_caption_status,
            "semantic_close_status": case.semantic_close_status,
            "assistant_directedness_status": case.assistant_directedness_status,
        },
        "composer_observation": {
            "source_commitment_present": case.source_commitment_present,
            "spoken_plan_emitted": case.spoken_plan_emitted,
            "coverage_check_required": case.coverage_check_required,
            "coverage_check_passed": case.coverage_check_passed,
            "truthfulness_check_required": case.truthfulness_check_required,
            "truthfulness_check_passed": case.truthfulness_check_passed,
            "immutable_facts_preserved": case.immutable_facts_preserved,
            "must_say_fields_covered": case.must_say_fields_covered,
            "forbidden_rewrites_absent": case.forbidden_rewrites_absent,
            "risk_warnings_preserved": case.risk_warnings_preserved,
            "confirmation_state_preserved": case.confirmation_state_preserved,
            "resolved_arguments_preserved": case.resolved_arguments_preserved,
            "stale_evidence_not_used": case.stale_evidence_not_used,
            "dry_run_status_truthful": case.dry_run_status_truthful,
        },
        "boundary_observation": {
            "router_selected_winner": False,
            "slowtask_commitment_owner": True,
            "interaction_ingress_owner": True,
            "tool_executor_required": True,
            "tool_proposal_only": case.tool_proposal_present,
            "tool_execution_started": case.tool_execution_started,
            "confirmation_required": case.confirmation_required,
            "model_accepts_confirmation": case.confirmation_accepted_by_model,
            "model_authorizes_tools": False,
            "talker_playback_allowed": case.talker_playback_allowed,
        },
        "streaming_observation": {
            "streaming_output_observed": case.streaming_output_observed,
            "delta_chunk_count": case.delta_chunk_count,
            "first_delta_ms": case.first_delta_ms,
            "full_response_ms": case.full_response_ms,
            "full_response_suitable_for_duplex_hot_path": False,
        },
        "failure_observation": {
            "failure_category": case.failure_category,
            "retryable": case.retryable,
            "provider_cancel_confirmed": case.provider_cancel_confirmed,
            "late_output_policy": case.late_output_policy,
        },
        "privacy": {
            "stored_audio": False,
            "stored_provider_body": False,
            "stored_trace": False,
            "stored_secret_material": False,
            "deterministic_replay_reruns_provider": False,
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


def _optional_ref(case: CaseDefinition, kind: str) -> str | None:
    if kind == "asr" and ("asr_" in case.case_id or "conflicting_asr" in case.case_id):
        return f"asr-frame-ref://synthetic/{case.case_id}"
    if kind == "commitment" and case.adapter_type == "thinker_as_composer":
        return f"semantic-commitment-ref://synthetic/{case.case_id}"
    if kind == "external" and case.web_evidence_untrusted:
        return f"external-evidence-ref://synthetic/{case.case_id}"
    return None
