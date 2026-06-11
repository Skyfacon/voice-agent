from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any

from voice_agent.adapters.capabilities import (
    AdapterCapability,
    BOOLEAN_CAPABILITY_FIELDS,
    CREDENTIAL_LIKE_REF_PATTERN,
)
from voice_agent.adapters.slow_llm_contract import SlowLLMStructuredOutputContract


class QwenSlowLLMAdapterSkeletonError(ValueError):
    def __init__(self, message: str, *, failure_reasons: Sequence[str] | None = None) -> None:
        super().__init__(message)
        self.failure_reasons = list(failure_reasons or (message,))


QWEN_SLOW_LLM_EVIDENCE_SCHEMA_VERSION = "slow_llm_qwen_evidence_v1"
QWEN_SLOW_LLM_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
QWEN_SLOW_LLM_ARRIVAL_CURRENT = "current_plan_reviewable_evidence"
QWEN_SLOW_LLM_ARRIVAL_STALE = "stale_old_plan_evidence"
QWEN_SLOW_LLM_ARRIVAL_TERMINAL = "terminal_task_late_evidence"
QWEN_SLOW_LLM_ARRIVAL_TASK_MISMATCH = "task_mismatch_ignored"
QWEN_SLOW_LLM_MAX_REPAIR_ATTEMPTS = 2

_REPAIRABLE_FAILURE_CATEGORIES = frozenset(
    {
        "parse_failure",
        "schema_failure",
        "boundary_assertion_failure",
    }
)
_NON_REPAIRABLE_FAILURE_CATEGORIES = frozenset(
    {
        "unsafe_ref",
        "credential_like_content",
        "task_binding_mismatch",
        "old_plan_late_output",
        "terminal_task_late_output",
        "ownership_claim",
        "raw_artifact_retention",
    }
)

_REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "task_binding",
    "task_analysis",
    "missing_fields",
    "conflicting_fields",
    "proposed_resolved_arguments_evidence",
    "tool_proposal",
    "confirmation_risk_hints",
    "validation_metadata",
    "boundary_assertions",
)
_BOUNDARY_ASSERTIONS = (
    "no_tool_authorization",
    "no_tool_execution",
    "no_ui_patch",
    "no_semantic_commitment_event",
    "no_checker_verdict",
    "no_playback_action",
)
_FORBIDDEN_OWNERSHIP_FIELDS = frozenset(
    {
        "event_name",
        "tool_authorization",
        "tool_execution",
        "tool_result",
        "ui_patch",
        "semantic_commitment",
        "spoken_plan",
        "checker_verdict",
        "playback_action",
        "slowtask_lifecycle",
        "plan_version_advanced",
    }
)
_DISALLOWED_RAW_ARTIFACT_MARKERS = (
    "raw_provider_body",
    "raw_audio",
    "audio/raw",
    "traces/",
    "diagnostics/",
    "replays/local",
    "local replay cache",
)
_DISALLOWED_RAW_ARTIFACT_FIELDS = frozenset(
    {
        "raw_provider_body",
        "raw_audio",
        "raw_trace",
        "raw_provider_request",
        "raw_provider_response",
        "raw_request_body",
        "raw_response_body",
        "large_raw_web_content",
    }
)


@dataclass(frozen=True)
class QwenSlowLLMRepairDecision:
    repairable: bool
    repair_action: str
    failure_category: str
    failure_reasons: tuple[str, ...]
    current_repair_attempt: int
    next_repair_attempt: int | None
    failure_terminal: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "repairable": self.repairable,
            "repair_action": self.repair_action,
            "failure_category": self.failure_category,
            "failure_reasons": list(self.failure_reasons),
            "current_repair_attempt": self.current_repair_attempt,
            "next_repair_attempt": self.next_repair_attempt,
            "max_repair_attempts": QWEN_SLOW_LLM_MAX_REPAIR_ATTEMPTS,
            "raw_provider_body_included": False,
            "provider_call_allowed": False,
            "raw_prompt_constructed": False,
            "failure_terminal": self.failure_terminal,
        }


@dataclass(frozen=True)
class QwenSlowLLMStructuredOutputMetadata:
    adapter_request_id: str
    output_mode: str
    slow_llm_output_ref: str
    structured_output_ref: str
    validation_result_ref: str
    validation_status: str
    may_advance_current_task: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_request_id": self.adapter_request_id,
            "output_mode": self.output_mode,
            "slow_llm_output_ref": self.slow_llm_output_ref,
            "structured_output_ref": self.structured_output_ref,
            "validation_result_ref": self.validation_result_ref,
            "validation_status": self.validation_status,
            "raw_provider_body_included": False,
            "may_advance_current_task": self.may_advance_current_task,
        }


@dataclass(frozen=True)
class QwenSlowLLMStructuredOutputEmission:
    structured_output_event: dict[str, Any]
    metadata: QwenSlowLLMStructuredOutputMetadata


@dataclass(frozen=True)
class QwenSlowLLMRequestBinding:
    task_id: str
    plan_version: int
    observed_plan_version: int
    interpreted_against_plan_version: int
    task_event_seq: int
    adapter_request_id: str
    causal_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty_string(self.task_id, "task_id")
        _require_positive_int(self.plan_version, "plan_version")
        _require_positive_int(self.observed_plan_version, "observed_plan_version")
        _require_positive_int(
            self.interpreted_against_plan_version,
            "interpreted_against_plan_version",
        )
        _require_positive_int(self.task_event_seq, "task_event_seq")
        _require_safe_ref(self.adapter_request_id, "adapter_request_id")
        if not _is_string_sequence(self.causal_refs):
            raise QwenSlowLLMAdapterSkeletonError("causal_refs must be a sequence of strings")
        causal_refs = tuple(self.causal_refs)
        for causal_ref in causal_refs:
            _require_safe_ref(causal_ref, "causal_refs")
        object.__setattr__(self, "causal_refs", causal_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "plan_version": self.plan_version,
            "observed_plan_version": self.observed_plan_version,
            "interpreted_against_plan_version": self.interpreted_against_plan_version,
            "task_event_seq": self.task_event_seq,
            "adapter_request_id": self.adapter_request_id,
            "causal_refs": list(self.causal_refs),
        }


def build_qwen_slow_llm_capability(
    *,
    model_name: str = "Qwen3.6 Plus",
    model_alias: str | None = None,
) -> AdapterCapability:
    """Build credential-free Qwen Slow LLM metadata without probing a provider."""

    _require_non_empty_string(model_name, "model_name")
    if model_alias is not None:
        _require_safe_ref(model_alias, "model_alias")

    fields: dict[str, object] = {
        "adapter_id": "slow_llm_qwen_mvp3_skeleton",
        "adapter_type": "slow_llm",
        "provider": "dashscope_qwen",
        "model_name": model_name,
        "deployment_mode": "remote_api",
        "endpoint": "endpoint://dashscope/qwen/slow-llm",
        "health_status": "configured",
        "capability_version": "mvp3.qwen-slow-llm.skeleton.v1",
        "latency_class": "provider_metadata_only",
        "error_model": "error-model://qwen/slow-llm/skeleton",
        "timeout_policy": "timeout-policy://qwen/slow-llm/skeleton",
        "retry_policy": "retry-policy://qwen/slow-llm/skeleton",
        "output_mode": "real",
        "config_ref": "config://runtime/qwen-slow-llm",
        "supports_streaming_input": False,
        "supports_streaming_output": False,
        "supports_audio_input": False,
        "supports_audio_output": False,
        "supports_audio_timestamps": False,
        "supports_structured_json": True,
        "supports_tool_calling": True,
        "supports_cancellation": False,
        "supports_emotion": False,
        "supports_audio_caption": False,
        "supports_tts": False,
        "supports_tts_truncate": False,
        "supports_tts_pause_resume": False,
        "supports_semantic_close": False,
        "supports_assistant_directedness": False,
        "max_audio_seconds": None,
        "max_context_tokens": 32768,
        "max_output_tokens": 4096,
        "expected_first_token_latency_ms": None,
        "expected_first_audio_latency_ms": None,
        "mocked": False,
        "mock_profile_ref": "",
        "target_architecture_validation": True,
    }
    fields["unsupported_capabilities"] = tuple(
        field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)  # type: ignore[arg-type]


def build_qwen_slow_llm_request_payload(
    *,
    binding: QwenSlowLLMRequestBinding,
    task_evidence_ref: str,
    untrusted_web_evidence_refs: Sequence[str] = (),
) -> dict[str, Any]:
    task_evidence_ref = _require_safe_ref(task_evidence_ref, "task_evidence_ref")
    if not _is_string_sequence(untrusted_web_evidence_refs):
        raise QwenSlowLLMAdapterSkeletonError(
            "untrusted_web_evidence_refs must be a sequence of strings"
        )
    web_refs = [
        _require_safe_ref(ref, "untrusted_web_evidence_refs")
        for ref in untrusted_web_evidence_refs
    ]
    return {
        "request_metadata": binding.to_dict(),
        "task_evidence": {
            "ref": task_evidence_ref,
            "raw_content_included": False,
        },
        "untrusted_web_evidence": {
            "refs": web_refs,
            "label": "UNTRUSTED_WEB_EVIDENCE",
            "instruction_authority": "none",
        },
        "instruction_boundary": {
            "provider_output_role": "evidence_candidate_only",
            "may_emit_event_journal_events": False,
            "may_execute_tools": False,
            "may_patch_ui": False,
            "may_create_semantic_commitments": False,
            "may_emit_spoken_plans": False,
            "json_output_schema": QWEN_SLOW_LLM_EVIDENCE_SCHEMA_VERSION,
        },
    }


def decide_qwen_slow_llm_repair(
    *,
    failure_category: str,
    repair_attempt: int,
    failure_reasons: Sequence[str],
) -> QwenSlowLLMRepairDecision:
    """Return local repair metadata only; never call providers or build prompts."""

    failure_category = _require_non_empty_string(failure_category, "failure_category")
    if (
        not isinstance(repair_attempt, int)
        or isinstance(repair_attempt, bool)
        or repair_attempt < 0
    ):
        raise QwenSlowLLMAdapterSkeletonError("repair_attempt must be a non-negative integer")
    normalized_reasons = _normalize_failure_reasons(failure_reasons)

    can_repair = (
        failure_category in _REPAIRABLE_FAILURE_CATEGORIES
        and repair_attempt < QWEN_SLOW_LLM_MAX_REPAIR_ATTEMPTS
    )
    if can_repair:
        return QwenSlowLLMRepairDecision(
            repairable=True,
            repair_action="attempt_local_bounded_repair",
            failure_category=failure_category,
            failure_reasons=normalized_reasons,
            current_repair_attempt=repair_attempt,
            next_repair_attempt=repair_attempt + 1,
            failure_terminal=False,
        )

    return QwenSlowLLMRepairDecision(
        repairable=False,
        repair_action="fail_closed",
        failure_category=failure_category,
        failure_reasons=normalized_reasons,
        current_repair_attempt=repair_attempt,
        next_repair_attempt=None,
        failure_terminal=True,
    )


def parse_qwen_slow_llm_evidence_json(raw_text: str) -> dict[str, Any]:
    if not isinstance(raw_text, str):
        _fail("expected a single JSON object")
    stripped = raw_text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        _fail("expected a single JSON object")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise QwenSlowLLMAdapterSkeletonError(
            "expected a single JSON object",
            failure_reasons=("parse failure: expected a single JSON object",),
        ) from exc
    if not isinstance(parsed, dict):
        _fail("expected a single JSON object")
    return parsed


def validate_qwen_slow_llm_evidence(
    output: Mapping[str, Any],
    *,
    expected_binding: QwenSlowLLMRequestBinding,
) -> dict[str, Any]:
    if not isinstance(output, Mapping):
        _fail("output must be a JSON object")
    _reject_forbidden_ownership_fields(output)
    _reject_raw_artifact_retention_fields(output)
    _reject_unsafe_payload_text(output)

    normalized = deepcopy(dict(output))
    for field in _REQUIRED_TOP_LEVEL_FIELDS:
        if field not in normalized:
            _fail(f"missing required field: {field}")

    if normalized["schema_version"] != QWEN_SLOW_LLM_EVIDENCE_SCHEMA_VERSION:
        _fail("unsupported schema_version")
    if normalized["task_binding"] != expected_binding.to_dict():
        _fail("task binding must match request binding")

    _validate_task_analysis(normalized["task_analysis"])
    _validate_list(normalized["missing_fields"], "missing_fields")
    _validate_list(normalized["conflicting_fields"], "conflicting_fields")
    _validate_mapping(
        normalized["proposed_resolved_arguments_evidence"],
        "proposed_resolved_arguments_evidence",
    )
    _validate_tool_proposal(normalized["tool_proposal"])
    _validate_list(normalized["confirmation_risk_hints"], "confirmation_risk_hints")
    _validate_validation_metadata(normalized["validation_metadata"])
    _validate_boundary_assertions(normalized["boundary_assertions"])

    normalized["validation_status"] = "validated_evidence_candidate"
    normalized["may_advance_current_task"] = False
    return normalized


def build_qwen_slow_llm_structured_output_metadata(
    validated_evidence: Mapping[str, Any],
    *,
    expected_binding: QwenSlowLLMRequestBinding,
    ref_namespace: str = "qwen-slow-llm",
) -> QwenSlowLLMStructuredOutputMetadata:
    if not isinstance(validated_evidence, Mapping):
        _fail("validated_evidence must be an object")
    if validated_evidence.get("validation_status") != "validated_evidence_candidate":
        _fail("validated_evidence must pass validate_qwen_slow_llm_evidence first")
    if validated_evidence.get("may_advance_current_task") is not False:
        _fail("validated_evidence must not advance current task")
    if validated_evidence.get("task_binding") != expected_binding.to_dict():
        _fail("task binding must match request binding")

    validation_metadata = _validate_mapping(
        validated_evidence.get("validation_metadata"),
        "validation_metadata",
    )
    output_mode = validation_metadata.get("output_mode")
    if output_mode not in QWEN_SLOW_LLM_OUTPUT_MODES:
        _fail("validation_metadata.output_mode must be real, fallback, or degraded")

    namespace_slug = _safe_ref_slug(_require_safe_ref(ref_namespace, "ref_namespace"))
    request_slug = _safe_ref_slug(expected_binding.adapter_request_id)
    slow_llm_output_ref = _require_safe_ref(
        f"slow-llm-output://synthetic/{namespace_slug}/{request_slug}",
        "slow_llm_output_ref",
    )
    structured_output_ref = _require_safe_ref(
        f"structured-output://synthetic/{namespace_slug}/{request_slug}",
        "structured_output_ref",
    )
    validation_result_ref = _require_safe_ref(
        f"validation://synthetic/{namespace_slug}/{request_slug}",
        "validation_result_ref",
    )

    return QwenSlowLLMStructuredOutputMetadata(
        adapter_request_id=expected_binding.adapter_request_id,
        output_mode=str(output_mode),
        slow_llm_output_ref=slow_llm_output_ref,
        structured_output_ref=structured_output_ref,
        validation_result_ref=validation_result_ref,
        validation_status="validated_evidence_candidate",
        may_advance_current_task=False,
    )


def emit_qwen_slow_llm_structured_output(
    *,
    contract: SlowLLMStructuredOutputContract,
    output: Mapping[str, Any],
    expected_binding: QwenSlowLLMRequestBinding,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    slowtask_event: Mapping[str, Any],
    ref_namespace: str = "qwen-slow-llm",
) -> QwenSlowLLMStructuredOutputEmission:
    validated = validate_qwen_slow_llm_evidence(
        output,
        expected_binding=expected_binding,
    )
    metadata = build_qwen_slow_llm_structured_output_metadata(
        validated,
        expected_binding=expected_binding,
        ref_namespace=ref_namespace,
    )
    emission = contract.emit_structured_output(
        event_id=event_id,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        slowtask_event=slowtask_event,
        adapter_request_id=metadata.adapter_request_id,
        slow_llm_output_ref=metadata.slow_llm_output_ref,
        structured_output_ref=metadata.structured_output_ref,
        validation_result_ref=metadata.validation_result_ref,
    )
    return QwenSlowLLMStructuredOutputEmission(
        structured_output_event=emission.structured_output_event,
        metadata=metadata,
    )


def classify_qwen_slow_llm_arrival(
    binding: QwenSlowLLMRequestBinding,
    *,
    current_task_id: str,
    current_plan_version: int,
    task_is_terminal: bool,
) -> str:
    _require_non_empty_string(current_task_id, "current_task_id")
    _require_positive_int(current_plan_version, "current_plan_version")
    if not isinstance(task_is_terminal, bool):
        raise QwenSlowLLMAdapterSkeletonError("task_is_terminal must be a boolean")

    if binding.task_id != current_task_id:
        return QWEN_SLOW_LLM_ARRIVAL_TASK_MISMATCH
    if task_is_terminal:
        return QWEN_SLOW_LLM_ARRIVAL_TERMINAL
    if binding.plan_version != current_plan_version:
        return QWEN_SLOW_LLM_ARRIVAL_STALE
    return QWEN_SLOW_LLM_ARRIVAL_CURRENT


def _validate_task_analysis(value: Any) -> None:
    analysis = _validate_mapping(value, "task_analysis")
    for field in ("summary", "intent", "confidence"):
        if field not in analysis:
            _fail(f"missing required field: task_analysis.{field}")
        if not isinstance(analysis[field], str) or analysis[field] == "":
            _fail(f"task_analysis.{field} must be a non-empty string")
    if analysis["confidence"] not in {"low", "medium", "high"}:
        _fail("task_analysis.confidence must be low, medium, or high")


def _validate_tool_proposal(value: Any) -> None:
    proposal = _validate_mapping(value, "tool_proposal")
    if proposal.get("proposal_only") is not True:
        _fail("tool_proposal must be proposal-only")
    if proposal.get("requires_slowtask_resolution") is not True:
        _fail("tool_proposal requires SlowTask resolution")
    args_status = proposal.get("args_status")
    if args_status not in {"none", "partial", "candidate_ready"}:
        _fail("tool_proposal.args_status must be none, partial, or candidate_ready")
    for field in ("partial_args", "candidate_ready_args"):
        _validate_mapping(proposal.get(field), f"tool_proposal.{field}")


def _validate_validation_metadata(value: Any) -> None:
    metadata = _validate_mapping(value, "validation_metadata")
    if metadata.get("output_mode") not in QWEN_SLOW_LLM_OUTPUT_MODES:
        _fail("validation_metadata.output_mode must be real, fallback, or degraded")
    repair_attempt = metadata.get("repair_attempt")
    if not isinstance(repair_attempt, int) or isinstance(repair_attempt, bool) or repair_attempt < 0:
        _fail("validation_metadata.repair_attempt must be a non-negative integer")
    if metadata.get("web_evidence_treated_as_untrusted") is not True:
        _fail("web evidence must remain untrusted")
    if metadata.get("forbidden_instruction_sources_ignored") is not True:
        _fail("forbidden instruction sources must be ignored")


def _validate_boundary_assertions(value: Any) -> None:
    assertions = _validate_mapping(value, "boundary_assertions")
    for assertion in _BOUNDARY_ASSERTIONS:
        if assertions.get(assertion) is not True:
            _fail(f"boundary assertion must be true: {assertion}")


def _validate_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    return value


def _validate_list(value: Any, field: str) -> None:
    if not isinstance(value, list):
        _fail(f"{field} must be a list")


def _reject_forbidden_ownership_fields(value: Any) -> None:
    for key, nested in _iter_mapping_items(value):
        if key in _FORBIDDEN_OWNERSHIP_FIELDS:
            _fail(f"forbidden ownership field present: {key}")
        _reject_forbidden_ownership_fields(nested)


def _reject_raw_artifact_retention_fields(value: Any) -> None:
    for key, nested in _iter_mapping_items(value):
        if key in _DISALLOWED_RAW_ARTIFACT_FIELDS:
            _fail("payload must not retain raw provider artifacts")
        _reject_raw_artifact_retention_fields(nested)


def _reject_unsafe_payload_text(value: Any) -> None:
    if isinstance(value, str):
        _require_safe_payload_text(value)
    elif isinstance(value, Mapping):
        for nested in value.values():
            _reject_unsafe_payload_text(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            _reject_unsafe_payload_text(nested)


def _iter_mapping_items(value: Any) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple((str(key), nested) for key, nested in value.items())


def _require_safe_ref(value: str, field: str) -> str:
    value = _require_non_empty_string(value, field)
    lowered = value.lower()
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        raise QwenSlowLLMAdapterSkeletonError(
            f"{field} must not contain credential-like content"
        )
    if any(marker in lowered for marker in _DISALLOWED_RAW_ARTIFACT_MARKERS):
        raise QwenSlowLLMAdapterSkeletonError(f"{field} must not reference raw local artifacts")
    return value


def _require_safe_payload_text(value: str) -> None:
    lowered = value.lower()
    if any(marker in lowered for marker in _DISALLOWED_RAW_ARTIFACT_MARKERS):
        raise QwenSlowLLMAdapterSkeletonError("payload must not reference raw local artifacts")
    if any(
        marker in lowered
        for marker in (
            "bearer ",
            "api_key=",
            "api-key=",
            "authorization=",
            "credential=",
            "token=",
            "password=",
        )
    ):
        raise QwenSlowLLMAdapterSkeletonError("payload must not contain credential-like content")
    if lowered.startswith("sk-") or " sk-" in lowered:
        raise QwenSlowLLMAdapterSkeletonError("payload must not contain credential-like content")


def _normalize_failure_reasons(failure_reasons: Sequence[str]) -> tuple[str, ...]:
    if (
        not _is_string_sequence(failure_reasons)
        or not failure_reasons
        or any(reason == "" for reason in failure_reasons)
    ):
        raise QwenSlowLLMAdapterSkeletonError(
            "failure_reasons must be a non-empty sequence of strings"
        )
    normalized: list[str] = []
    for reason in failure_reasons:
        if _contains_unsafe_payload_text(reason):
            normalized.append("unsafe failure reason redacted")
        else:
            normalized.append(reason)
    return tuple(normalized)


def _contains_unsafe_payload_text(value: str) -> bool:
    lowered = value.lower()
    return (
        any(marker in lowered for marker in _DISALLOWED_RAW_ARTIFACT_MARKERS)
        or any(
            marker in lowered
            for marker in (
                "bearer ",
                "api_key=",
                "api-key=",
                "authorization=",
                "credential=",
                "token=",
                "password=",
            )
        )
        or lowered.startswith("sk-")
        or " sk-" in lowered
        or CREDENTIAL_LIKE_REF_PATTERN.search(value) is not None
    )


def _safe_ref_slug(value: str) -> str:
    characters = [character if character.isalnum() or character in "-_" else "-" for character in value]
    slug = "".join(characters).strip("-")
    if not slug:
        raise QwenSlowLLMAdapterSkeletonError("safe ref slug must not be empty")
    return slug


def _require_non_empty_string(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise QwenSlowLLMAdapterSkeletonError(f"{field} must be a non-empty string")
    return value


def _require_positive_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise QwenSlowLLMAdapterSkeletonError(f"{field} must be a positive integer")


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and all(
        isinstance(item, str) for item in value
    )


def _fail(message: str) -> None:
    raise QwenSlowLLMAdapterSkeletonError(message, failure_reasons=(message,))
