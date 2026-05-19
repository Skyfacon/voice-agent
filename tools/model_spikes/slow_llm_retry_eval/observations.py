"""Observation builders for Slow LLM retry eval dry-runs."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .cases import CaseDefinition, select_cases
from .schema import SCHEMA_VERSION, validate_observation


DEFAULT_CONTRACT_SNAPSHOT = "main@61e6afc"


def build_observation(case: CaseDefinition, index: int, contract_snapshot: str) -> dict[str, Any]:
    output_mode = case.output_mode
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_snapshot": contract_snapshot,
        "observation_id": f"obs_slow_llm_retry_synthetic_{index:03d}_{case.case_id}",
        "case_id": case.case_id,
        "observation_kind": case.observation_kind,
        "expected_evidence_label": case.expected_label,
        "degradation_reason": case.degradation_reason,
        "candidate": {
            "adapter_type": "slow_llm",
            "provider": "synthetic",
            "model_name": "synthetic_fixture",
            "deployment_mode": "synthetic",
            "endpoint_ref": "synthetic-dry-run",
            "output_mode": output_mode,
        },
        "task_binding": {
            "task_id": case.task_id,
            "plan_version": case.plan_version,
            "task_event_seq": case.task_event_seq,
            "adapter_request_id": f"adapter_req_synthetic_{index:03d}",
            "causal_source_refs": [f"event_ref://synthetic/{case.case_id}"],
        },
        "adapter_result": {
            "result_arrival_order": case.result_arrival_order,
            "parse_status": case.parse_status,
            "schema_status": case.schema_status,
            "final_validation_status": case.final_validation_status,
            "retry_count": case.retry_count,
            "retry_reason": case.retry_reason,
            "retry_budget_exhausted": case.retry_budget_exhausted,
            "timeout_ms": case.timeout_ms,
            "failure_category": case.failure_category,
            "provider_cancel_confirmed": case.provider_cancel_confirmed,
            "client_abort_observed": case.client_abort_observed,
            "streaming_partial_json": case.streaming_partial_json,
            "partial_chunk_count": case.partial_chunk_count,
            "raw_provider_body_stored": case.raw_provider_body_stored,
        },
        "slowtask_effect": {
            "current_plan_version_at_arrival": case.current_plan_version_at_arrival,
            "terminal_state_at_arrival": case.terminal_state_at_arrival,
            "should_mark_stale": case.should_mark_stale,
            "may_advance_current_task": case.may_advance_current_task,
            "requires_explicit_adopt_or_rebase": case.requires_explicit_adopt_or_rebase,
            "adoption_recorded": case.adoption_recorded,
            "adoption_mode": case.adoption_mode,
            "slowtask_review_required": True,
        },
        "tool_boundary": {
            "tool_proposal_present": case.tool_proposal_present,
            "tool_execution_started": case.tool_execution_started,
            "confirmation_required": case.confirmation_required,
            "confirmation_accepted": case.confirmation_accepted,
            "web_evidence_untrusted": case.web_evidence_untrusted,
            "web_evidence_trusted_as_instruction": case.web_evidence_trusted_as_instruction,
        },
        "privacy": {
            "raw_trace_stored": False,
            "real_user_input_stored": False,
            "secret_material_stored": False,
            "deterministic_replay_reruns_provider": False,
        },
        "boundary_assertions": {
            "model_output_owns_slowtask_state": False,
            "model_output_accepts_confirmation": False,
            "model_output_authorizes_tools": False,
            "model_output_mutates_ui": False,
            "model_output_sets_terminal_task_status": False,
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
