"""Synthetic case definitions for the Slow LLM retry eval harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    observation_kind: str
    expected_label: str
    output_mode: str = "mock"
    task_id: str = "task_synthetic_001"
    plan_version: int = 1
    task_event_seq: int = 7
    current_plan_version_at_arrival: int = 1
    terminal_state_at_arrival: str | None = None
    result_arrival_order: str = "on_time_current_plan"
    parse_status: str = "pass"
    schema_status: str = "pass"
    retry_count: int = 0
    retry_reason: str | None = None
    retry_budget_exhausted: bool = False
    timeout_ms: int | None = None
    failure_category: str | None = None
    provider_cancel_confirmed: str = "unknown"
    client_abort_observed: bool = False
    streaming_partial_json: bool = False
    partial_chunk_count: int = 0
    final_validation_status: str = "pass"
    should_mark_stale: bool = False
    may_advance_current_task: bool = False
    requires_explicit_adopt_or_rebase: bool = False
    adoption_recorded: bool = False
    adoption_mode: str | None = None
    tool_proposal_present: bool = False
    tool_execution_started: bool = False
    confirmation_required: bool = False
    confirmation_accepted: bool = False
    web_evidence_untrusted: bool = False
    web_evidence_trusted_as_instruction: bool = False
    raw_provider_body_stored: bool = False
    degradation_reason: str | None = None


SMOKE_CASES = (
    "validated_json_current_plan",
    "bounded_schema_repair_success",
    "client_timeout_probe",
    "late_result_old_plan_stale_probe",
    "tool_proposal_confirmation_required_probe",
)

FULL_SYNTHETIC_CASES = (
    "validated_json_current_plan",
    "missing_required_slot_retry_blocked",
    "conflicting_evidence_retry_blocked",
    "weak_schema_validation_failure",
    "bounded_schema_repair_success",
    "bounded_schema_repair_exhausted",
    "client_timeout_probe",
    "client_abort_unconfirmed_cancel_probe",
    "provider_confirmed_cancel_probe",
    "retryable_provider_failure_probe",
    "non_retryable_provider_failure_probe",
    "late_result_same_plan_probe",
    "late_result_old_plan_stale_probe",
    "terminal_task_late_result_probe",
    "explicit_stale_adoption_probe",
    "streaming_partial_json_probe",
    "malformed_json_probe",
    "tool_proposal_confirmation_required_probe",
    "web_evidence_injection_retry_probe",
    "context_limit_degradation_probe",
    "deepseek_comparison_deferred_probe",
)


def _case(case_id: str, observation_kind: str, expected_label: str, **kwargs: object) -> CaseDefinition:
    return CaseDefinition(
        case_id=case_id,
        observation_kind=observation_kind,
        expected_label=expected_label,
        **kwargs,
    )


CASES: dict[str, CaseDefinition] = {
    "validated_json_current_plan": _case(
        "validated_json_current_plan",
        "adapter_validation_observation",
        "prior_observed_real_validated_json",
    ),
    "missing_required_slot_retry_blocked": _case(
        "missing_required_slot_retry_blocked",
        "adapter_validation_observation",
        "prior_observed_real_insufficient_evidence",
        may_advance_current_task=False,
        degradation_reason="missing slot remains insufficient evidence until SlowTask review",
    ),
    "conflicting_evidence_retry_blocked": _case(
        "conflicting_evidence_retry_blocked",
        "adapter_validation_observation",
        "prior_observed_real_conflict_preserved",
        degradation_reason="conflict preserved; no invented field winner",
    ),
    "weak_schema_validation_failure": _case(
        "weak_schema_validation_failure",
        "adapter_validation_observation",
        "prior_observed_real_validation_failure_detection",
        output_mode="degraded",
        schema_status="fail",
        failure_category="schema_validation_failed",
        final_validation_status="fail",
    ),
    "bounded_schema_repair_success": _case(
        "bounded_schema_repair_success",
        "adapter_retry_observation",
        "prior_observed_real_bounded_repair",
        retry_count=2,
        retry_reason="schema_validation_failed",
        final_validation_status="pass",
    ),
    "bounded_schema_repair_exhausted": _case(
        "bounded_schema_repair_exhausted",
        "adapter_retry_observation",
        "synthetic_retry_budget_exhausted",
        output_mode="degraded",
        parse_status="pass",
        schema_status="fail",
        retry_count=2,
        retry_reason="schema_validation_failed",
        retry_budget_exhausted=True,
        final_validation_status="fail",
        failure_category="retry_budget_exhausted",
    ),
    "client_timeout_probe": _case(
        "client_timeout_probe",
        "adapter_timeout_observation",
        "prior_observed_degraded_client_timeout",
        output_mode="degraded",
        parse_status="not_applicable",
        schema_status="not_applicable",
        timeout_ms=1,
        failure_category="client_timeout",
        provider_cancel_confirmed="unknown",
        final_validation_status="not_applicable",
    ),
    "client_abort_unconfirmed_cancel_probe": _case(
        "client_abort_unconfirmed_cancel_probe",
        "adapter_cancellation_observation",
        "synthetic_client_abort_unconfirmed",
        output_mode="degraded",
        parse_status="not_applicable",
        schema_status="not_applicable",
        failure_category="client_abort",
        client_abort_observed=True,
        provider_cancel_confirmed="unknown",
        final_validation_status="not_applicable",
    ),
    "provider_confirmed_cancel_probe": _case(
        "provider_confirmed_cancel_probe",
        "adapter_cancellation_observation",
        "unknown_provider_confirmed_cancellation",
        output_mode="degraded",
        parse_status="not_applicable",
        schema_status="not_applicable",
        failure_category="provider_cancellation_unconfirmed",
        provider_cancel_confirmed="unknown",
        final_validation_status="not_applicable",
    ),
    "retryable_provider_failure_probe": _case(
        "retryable_provider_failure_probe",
        "adapter_retry_observation",
        "synthetic_retryable_provider_failure",
        output_mode="degraded",
        parse_status="not_applicable",
        schema_status="not_applicable",
        retry_count=1,
        retry_reason="retryable_provider_failure",
        failure_category="retryable_provider_failure",
        final_validation_status="not_applicable",
    ),
    "non_retryable_provider_failure_probe": _case(
        "non_retryable_provider_failure_probe",
        "adapter_validation_observation",
        "synthetic_non_retryable_provider_failure",
        output_mode="degraded",
        parse_status="not_applicable",
        schema_status="not_applicable",
        failure_category="non_retryable_provider_failure",
        final_validation_status="not_applicable",
    ),
    "late_result_same_plan_probe": _case(
        "late_result_same_plan_probe",
        "late_result_observation",
        "synthetic_late_same_plan_reviewable",
        result_arrival_order="late_same_plan",
        may_advance_current_task=False,
        degradation_reason="validated output still requires SlowTask review",
    ),
    "late_result_old_plan_stale_probe": _case(
        "late_result_old_plan_stale_probe",
        "late_result_observation",
        "synthetic_old_plan_stale",
        current_plan_version_at_arrival=2,
        result_arrival_order="late_after_plan_advance",
        should_mark_stale=True,
        requires_explicit_adopt_or_rebase=True,
        degradation_reason="old plan output must not advance current task",
    ),
    "terminal_task_late_result_probe": _case(
        "terminal_task_late_result_probe",
        "late_result_observation",
        "synthetic_terminal_late_stale",
        terminal_state_at_arrival="cancelled",
        result_arrival_order="late_after_terminal_state",
        should_mark_stale=True,
        requires_explicit_adopt_or_rebase=True,
    ),
    "explicit_stale_adoption_probe": _case(
        "explicit_stale_adoption_probe",
        "stale_result_event_shape",
        "synthetic_explicit_stale_adoption_shape",
        current_plan_version_at_arrival=2,
        result_arrival_order="late_after_plan_advance",
        should_mark_stale=True,
        requires_explicit_adopt_or_rebase=True,
        adoption_recorded=True,
        adoption_mode="explicit_rebase",
        may_advance_current_task=False,
    ),
    "streaming_partial_json_probe": _case(
        "streaming_partial_json_probe",
        "adapter_validation_observation",
        "docs_only_unobserved_streaming_json_shape",
        output_mode="degraded",
        streaming_partial_json=True,
        partial_chunk_count=4,
        final_validation_status="pass",
        degradation_reason="partial streaming chunks must not update task facts",
    ),
    "malformed_json_probe": _case(
        "malformed_json_probe",
        "adapter_validation_observation",
        "synthetic_malformed_json_parse_failure",
        output_mode="degraded",
        parse_status="fail",
        schema_status="not_applicable",
        final_validation_status="fail",
        failure_category="parse_failed",
    ),
    "tool_proposal_confirmation_required_probe": _case(
        "tool_proposal_confirmation_required_probe",
        "tool_proposal_boundary_observation",
        "prior_observed_real_tool_proposal_shape",
        tool_proposal_present=True,
        confirmation_required=True,
        tool_execution_started=False,
        confirmation_accepted=False,
    ),
    "web_evidence_injection_retry_probe": _case(
        "web_evidence_injection_retry_probe",
        "adapter_retry_observation",
        "prior_observed_real_untrusted_web_boundary",
        retry_count=1,
        retry_reason="schema_validation_failed",
        web_evidence_untrusted=True,
        web_evidence_trusted_as_instruction=False,
    ),
    "context_limit_degradation_probe": _case(
        "context_limit_degradation_probe",
        "adapter_validation_observation",
        "synthetic_context_limit_degradation",
        output_mode="degraded",
        failure_category="context_limit_degraded",
        final_validation_status="not_applicable",
        parse_status="not_applicable",
        schema_status="not_applicable",
    ),
    "deepseek_comparison_deferred_probe": _case(
        "deepseek_comparison_deferred_probe",
        "case_verdict",
        "unknown_runtime_deepseek_deferred",
        output_mode="degraded",
        parse_status="not_applicable",
        schema_status="not_applicable",
        failure_category="not_executed_key_missing",
        final_validation_status="not_applicable",
    ),
}


CASE_SETS: dict[str, tuple[str, ...]] = {
    "smoke": SMOKE_CASES,
    "full_synthetic": FULL_SYNTHETIC_CASES,
}


def select_cases(case_set: str) -> list[CaseDefinition]:
    if case_set == "provider_probe":
        raise ValueError("provider_probe is unavailable by default")
    try:
        case_ids = CASE_SETS[case_set]
    except KeyError as exc:
        raise ValueError(f"unknown case set: {case_set}") from exc
    return [CASES[case_id] for case_id in case_ids]
