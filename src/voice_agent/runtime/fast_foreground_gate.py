from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import time
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.foreground_template_catalog import (
    foreground_template_by_ref,
    get_foreground_template,
)
from voice_agent.runtime.mvp5_live_approval import is_safe_mvp5_live_ref


FAST_FOREGROUND_GATE_POLICY_VERSION = "mvp6.3.fast_foreground_gate.v2"
FAST_FOREGROUND_CANDIDATE_POLICY_VERSION = "mvp6.3.candidate_policy.v1"

_INTERACTION_STATES = frozenset(
    {
        "IDLE",
        "COLLECTING_INPUT",
        "HOLDING_INPUT",
        "TURN_COMMITTED",
        "RESPONDING",
        "INTERRUPTING",
        "WAITING_USER",
    }
)
_GATE_READY_INTERACTION_STATES = frozenset({"TURN_COMMITTED", "RESPONDING"})
_TASK_FOCUS_STATES = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "FOREGROUND_CHAT",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "NON_ASSISTANT",
        "AMBIGUOUS",
    }
)
_SLOWTASK_STATES = frozenset(
    {
        "CREATED",
        "WAITING_FOR_SLOT",
        "PLANNING",
        "EXECUTING",
        "WAITING_FOR_USER_CONFIRMATION",
        "COMPLETED",
        "CANCELLED",
        "FAILED",
    }
)
_TERMINAL_SLOWTASK_STATES = frozenset({"COMPLETED", "CANCELLED", "FAILED"})
_CANDIDATE_POLICY_DECISIONS = frozenset({"allow", "quarantine"})
_CANDIDATE_POLICY_PROVENANCE = frozenset(
    {"trusted_synthetic", "local_deterministic_template", "provider_generated"}
)
_AUTHORITY_MODES = frozenset({"live_runtime", "trusted_synthetic_eval"})


class FastForegroundGateError(ValueError):
    pass


@dataclass(frozen=True)
class FastForegroundGateConfig:
    confidence_threshold: float = 0.8
    policy_version: str = FAST_FOREGROUND_GATE_POLICY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.confidence_threshold, (int, float))
            or isinstance(self.confidence_threshold, bool)
            or self.confidence_threshold < 0.0
            or self.confidence_threshold > 1.0
        ):
            raise FastForegroundGateError("confidence_threshold must be in [0, 1]")
        _require_safe_token(self.policy_version, "policy_version")


@dataclass(frozen=True, slots=True)
class CandidatePolicyDecision:
    """Local candidate disposition; never constructed from provider claims."""

    policy_version: str
    decision: str
    reason_code: str
    provenance: str

    def __post_init__(self) -> None:
        _require_safe_token(self.policy_version, "candidate_policy_version")
        _require_safe_token(self.reason_code, "candidate_policy_reason_code")
        if self.decision not in _CANDIDATE_POLICY_DECISIONS:
            raise FastForegroundGateError("candidate policy decision is invalid")
        if self.provenance not in _CANDIDATE_POLICY_PROVENANCE:
            raise FastForegroundGateError("candidate policy provenance is invalid")
        if self.provenance == "provider_generated" and self.decision != "quarantine":
            raise FastForegroundGateError(
                "provider-generated candidates cannot be locally policy-allowed"
            )

    @classmethod
    def trusted_synthetic(
        cls,
        *,
        policy_version: str = FAST_FOREGROUND_CANDIDATE_POLICY_VERSION,
        reason_code: str = "trusted_synthetic_fixture",
    ) -> CandidatePolicyDecision:
        return cls(
            policy_version=policy_version,
            decision="allow",
            reason_code=reason_code,
            provenance="trusted_synthetic",
        )

    @classmethod
    def trusted_local_template(
        cls,
        *,
        policy_version: str = FAST_FOREGROUND_CANDIDATE_POLICY_VERSION,
        reason_code: str = "server_owned_deterministic_template",
    ) -> CandidatePolicyDecision:
        return cls(
            policy_version=policy_version,
            decision="allow",
            reason_code=reason_code,
            provenance="local_deterministic_template",
        )

    @classmethod
    def quarantined_provider(
        cls,
        *,
        policy_version: str = FAST_FOREGROUND_CANDIDATE_POLICY_VERSION,
        reason_code: str = "arbitrary_provider_candidate",
    ) -> CandidatePolicyDecision:
        return cls(
            policy_version=policy_version,
            decision="quarantine",
            reason_code=reason_code,
            provenance="provider_generated",
        )


@dataclass(frozen=True, slots=True)
class FastForegroundGateContext:
    """Immutable, authority-bound context consumed by the core Gate.

    Raw candidate text never crosses this boundary. Missing authority fields
    are representable so a caller can produce a canonical fail-closed Gate
    decision instead of inventing optimistic defaults.
    """

    authority_mode: str
    authority_binding_status: str
    interaction_state: str | None
    interaction_state_ref: str | None
    task_focus: str | None
    task_focus_snapshot_ref: str | None
    has_active_slowtask: bool | None
    active_task_id: str | None
    active_slowtask_lifecycle: str | None
    pending_confirmation: bool | None
    pending_confirmation_id: str | None
    pending_confirmation_scope: str | None
    capability_snapshot_ref: str | None
    capability_health_status: str | None
    capability_output_mode: str | None
    capability_verification_status: str | None
    candidate_policy_decision: CandidatePolicyDecision
    schema_valid: bool | None
    confidence_threshold: float | None
    active_plan_version: int | None = None
    active_task_event_seq: int | None = None

    def __post_init__(self) -> None:
        if self.authority_mode not in _AUTHORITY_MODES:
            raise FastForegroundGateError("authority_mode is invalid")
        _require_safe_token(self.authority_binding_status, "authority_binding_status")
        for field_name in (
            "interaction_state",
            "interaction_state_ref",
            "task_focus",
            "task_focus_snapshot_ref",
            "active_task_id",
            "active_slowtask_lifecycle",
            "pending_confirmation_id",
            "pending_confirmation_scope",
            "capability_snapshot_ref",
            "capability_health_status",
            "capability_output_mode",
            "capability_verification_status",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_safe_token(value, field_name)
        for field_name in ("has_active_slowtask", "pending_confirmation", "schema_valid"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                raise FastForegroundGateError(f"{field_name} must be boolean or None")
        if not isinstance(self.candidate_policy_decision, CandidatePolicyDecision):
            raise FastForegroundGateError(
                "candidate_policy_decision must be a CandidatePolicyDecision"
            )
        if self.confidence_threshold is not None:
            _validate_threshold(self.confidence_threshold, "confidence_threshold")
        for field_name in ("active_plan_version", "active_task_event_seq"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 1
            ):
                raise FastForegroundGateError(f"{field_name} must be positive or None")


@dataclass(frozen=True)
class FastForegroundGateResult:
    gate_event: dict[str, Any]
    committed_event: dict[str, Any] | None
    discarded_event: dict[str, Any] | None
    gate_decision_ms: int
    output_finalize_ms: int


def run_missing_fast_foreground_gate(
    journal: InMemoryEventJournal,
    *,
    router_decision_event: Mapping[str, Any],
    event_id_prefix: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    config: FastForegroundGateConfig | None = None,
) -> FastForegroundGateResult:
    """Fail closed when FAST_ONLY has no Fast Interaction authority."""

    gate_started = time.monotonic()
    config = config or FastForegroundGateConfig()
    _require_event(router_decision_event, "ROUTER_DECISION_EMITTED")
    _require_canonical_journal_event(journal, router_decision_event)
    if router_decision_event.get("router_decision") != "FAST_ONLY":
        raise FastForegroundGateError(
            "missing Fast Interaction Gate is only valid for FAST_ONLY"
        )
    event_id_prefix = _require_safe_token(event_id_prefix, "event_id_prefix")
    safe_segment = _safe_segment(event_id_prefix)
    gate_event = journal.append(
        event_name="FOREGROUND_ACT_GATE_FAILED",
        event_id=f"{event_id_prefix}_failed",
        source_module="fast_foreground_gate",
        caused_by_event_id=str(router_decision_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        gate_decision_id=f"gate_{safe_segment}",
        router_decision_event_id=str(router_decision_event["event_id"]),
        foreground_act="CLARIFY",
        risk_class="UNKNOWN",
        confidence=0.0,
        policy_version=config.policy_version,
        failure_reason="fast_interaction_missing",
        downgrade_policy="template_clarify",
    )
    gate_decision_ms = _elapsed_ms(gate_started)
    output_started = time.monotonic()
    template = get_foreground_template(
        router_decision="FAST_ONLY",
        output_basis="template_clarify",
    )
    committed = _append_committed_output(
        journal,
        event_id=f"{event_id_prefix}_template_committed",
        caused_by_event_id=str(gate_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 1,
        created_wall_clock_ms=created_wall_clock_ms + 1,
        foreground_output_id=f"foreground_output_{safe_segment}_template",
        turn_id=str(router_decision_event["turn_id"]),
        utterance_id=str(router_decision_event["utterance_id"]),
        output_ref=template.template_ref,
        output_basis=template.output_basis,
        foreground_act=template.foreground_act,
        router_decision_event_id=str(router_decision_event["event_id"]),
        gate_event_id=str(gate_event["event_id"]),
        fallback_policy_ref=template.fallback_policy_ref,
        fallback_reason="fast_interaction_missing",
    )
    return FastForegroundGateResult(
        gate_event=gate_event,
        committed_event=committed,
        discarded_event=None,
        gate_decision_ms=gate_decision_ms,
        output_finalize_ms=_elapsed_ms(output_started),
    )


def run_fast_foreground_gate(
    journal: InMemoryEventJournal,
    *,
    candidate_event: Mapping[str, Any],
    fast_interaction_output_event: Mapping[str, Any],
    router_decision_event: Mapping[str, Any],
    context: FastForegroundGateContext,
    config: FastForegroundGateConfig | None = None,
    event_id_prefix: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> FastForegroundGateResult:
    gate_started = time.monotonic()
    config = config or FastForegroundGateConfig()
    _require_event(candidate_event, "FOREGROUND_REPLY_CANDIDATE_EMITTED")
    _require_event(fast_interaction_output_event, "FAST_INTERACTION_OUTPUT_EMITTED")
    _require_event(router_decision_event, "ROUTER_DECISION_EMITTED")
    _require_canonical_journal_event(journal, candidate_event)
    _require_canonical_journal_event(journal, fast_interaction_output_event)
    _require_canonical_journal_event(journal, router_decision_event)
    event_id_prefix = _require_safe_token(event_id_prefix, "event_id_prefix")
    _validate_candidate_provenance(
        candidate_event=candidate_event,
        fast_interaction_output_event=fast_interaction_output_event,
        router_decision_event=router_decision_event,
    )

    router_decision = str(router_decision_event["router_decision"])
    task_focus = str(router_decision_event.get("task_focus", ""))
    foreground_act = str(fast_interaction_output_event.get("foreground_act", ""))
    risk_class = str(fast_interaction_output_event.get("risk_class", ""))
    confidence = _confidence(fast_interaction_output_event.get("confidence", 0.0))
    threshold = (
        1.0
        if context.confidence_threshold is None
        else max(
            float(config.confidence_threshold), float(context.confidence_threshold)
        )
    )
    failure_reason = _failure_reason(
        router_decision=router_decision,
        task_focus=task_focus,
        foreground_act=foreground_act,
        risk_class=risk_class,
        risk_tags_present="risk_tags" in fast_interaction_output_event,
        risk_tags=_normalized_risk_tags(
            fast_interaction_output_event.get("risk_tags"),
            present="risk_tags" in fast_interaction_output_event,
        ),
        candidate_risk_tags_present="risk_tags" in candidate_event,
        candidate_risk_tags=_normalized_risk_tags(
            candidate_event.get("risk_tags"),
            present="risk_tags" in candidate_event,
        ),
        confidence=confidence,
        candidate_event=candidate_event,
        fast_interaction_output_event=fast_interaction_output_event,
        context=context,
        threshold=threshold,
    )

    if failure_reason is None:
        safe_segment = _safe_segment(event_id_prefix)
        gate_event = journal.append(
            event_name="FOREGROUND_ACT_GATE_PASSED",
            event_id=f"{event_id_prefix}_passed",
            source_module="fast_foreground_gate",
            caused_by_event_id=str(router_decision_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            gate_decision_id=f"gate_{safe_segment}",
            candidate_event_id=str(candidate_event["event_id"]),
            router_decision_event_id=str(router_decision_event["event_id"]),
            foreground_act="ANSWER",
            risk_class="LOW",
            confidence=confidence,
            policy_version=config.policy_version,
            pass_reason="fast_only_answer_low_risk_confident",
        )
        gate_decision_ms = _elapsed_ms(gate_started)
        output_started = time.monotonic()
        committed = _append_committed_output(
            journal,
            event_id=f"{event_id_prefix}_committed",
            caused_by_event_id=str(gate_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 1,
            created_wall_clock_ms=created_wall_clock_ms + 1,
            foreground_output_id=f"foreground_output_{safe_segment}",
            turn_id=str(router_decision_event["turn_id"]),
            utterance_id=str(router_decision_event["utterance_id"]),
            output_ref=str(candidate_event["candidate_ref"]),
            output_basis="reply_candidate",
            foreground_act="ANSWER",
            router_decision_event_id=str(router_decision_event["event_id"]),
            gate_event_id=str(gate_event["event_id"]),
        )
        return FastForegroundGateResult(
            gate_event=gate_event,
            committed_event=committed,
            discarded_event=None,
            gate_decision_ms=gate_decision_ms,
            output_finalize_ms=_elapsed_ms(output_started),
        )

    safe_segment = _safe_segment(event_id_prefix)
    gate_event = journal.append(
        event_name="FOREGROUND_ACT_GATE_FAILED",
        event_id=f"{event_id_prefix}_failed",
        source_module="fast_foreground_gate",
        caused_by_event_id=str(router_decision_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        gate_decision_id=f"gate_{safe_segment}",
        candidate_event_id=str(candidate_event["event_id"]),
        router_decision_event_id=str(router_decision_event["event_id"]),
        foreground_act=foreground_act,
        risk_class=risk_class,
        confidence=confidence,
        policy_version=config.policy_version,
        failure_reason=failure_reason,
        downgrade_policy=_downgrade_policy(
            router_decision,
            task_focus=task_focus,
            foreground_act=foreground_act,
        ),
    )
    gate_decision_ms = _elapsed_ms(gate_started)
    output_started = time.monotonic()
    discarded = journal.append(
        event_name="FOREGROUND_OUTPUT_DISCARDED",
        event_id=f"{event_id_prefix}_discarded",
        source_module="foreground_buffer",
        caused_by_event_id=str(gate_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 1,
        created_wall_clock_ms=created_wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        discard_id=f"discard_{safe_segment}",
        candidate_event_id=str(candidate_event["event_id"]),
        fast_interaction_output_event_id=str(fast_interaction_output_event["event_id"]),
        router_decision_event_id=str(router_decision_event["event_id"]),
        discard_reason=failure_reason,
    )
    committed: dict[str, Any] | None = None
    downgrade_policy = _downgrade_policy(
        router_decision,
        task_focus=task_focus,
        foreground_act=foreground_act,
    )
    if downgrade_policy == "template_clarify":
        template = get_foreground_template(
            router_decision=router_decision,
            output_basis=downgrade_policy,
        )
        committed = _append_committed_output(
            journal,
            event_id=f"{event_id_prefix}_template_committed",
            caused_by_event_id=str(gate_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 2,
            created_wall_clock_ms=created_wall_clock_ms + 2,
            foreground_output_id=f"foreground_output_{safe_segment}_template",
            turn_id=str(router_decision_event["turn_id"]),
            utterance_id=str(router_decision_event["utterance_id"]),
            output_ref=template.template_ref,
            output_basis=downgrade_policy,
            foreground_act=template.foreground_act,
            router_decision_event_id=str(router_decision_event["event_id"]),
            gate_event_id=str(gate_event["event_id"]),
            fallback_policy_ref=template.fallback_policy_ref,
            fallback_reason=failure_reason,
        )
    return FastForegroundGateResult(
        gate_event=gate_event,
        committed_event=committed,
        discarded_event=discarded,
        gate_decision_ms=gate_decision_ms,
        output_finalize_ms=_elapsed_ms(output_started),
    )


def commit_deferred_foreground_template(
    journal: InMemoryEventJournal,
    *,
    gate_result: FastForegroundGateResult,
    router_decision_event: Mapping[str, Any],
    output_basis: str,
    mutation_event: Mapping[str, Any] | None,
    fallback_reason: str,
    event_id_prefix: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    mutation_completion_event: Mapping[str, Any] | None = None,
) -> FastForegroundGateResult:
    """Commit one catalog template after a slow-route mutation outcome is known."""

    if gate_result.gate_event.get("event_name") != "FOREGROUND_ACT_GATE_FAILED":
        raise FastForegroundGateError("deferred template requires a failed Gate")
    if gate_result.gate_event.get("downgrade_policy") != "deferred_mutation_outcome":
        raise FastForegroundGateError("Gate does not have a deferred mutation outcome")
    if gate_result.discarded_event is None or gate_result.committed_event is not None:
        raise FastForegroundGateError("deferred Gate result is not commit-ready")
    _require_canonical_journal_event(journal, gate_result.gate_event)
    _require_canonical_journal_event(journal, gate_result.discarded_event)
    _require_canonical_journal_event(journal, router_decision_event)
    if gate_result.gate_event.get("router_decision_event_id") != router_decision_event.get(
        "event_id"
    ):
        raise FastForegroundGateError("deferred Gate must match Router decision")
    router_decision = str(router_decision_event.get("router_decision", ""))
    if output_basis == "template_ack":
        if mutation_event is None:
            raise FastForegroundGateError("template_ack requires completed mutation evidence")
        _require_canonical_journal_event(journal, mutation_event)
        expected_mutation_name = {
            "SPAWN_SLOW_TASK": "SLOWTASK_CREATED",
            "PATCH_ACTIVE_SLOW_TASK": "USER_PATCH_RECEIVED",
        }.get(router_decision)
        if (
            expected_mutation_name is None
            or mutation_event.get("event_name") != expected_mutation_name
            or mutation_event.get("caused_by_event_id")
            != router_decision_event.get("event_id")
        ):
            raise FastForegroundGateError(
                "template_ack mutation evidence does not match Router decision"
            )
        if router_decision == "PATCH_ACTIVE_SLOW_TASK":
            if mutation_completion_event is None:
                raise FastForegroundGateError(
                    "PATCH template_ack requires canonical mutation completion"
                )
            _validate_patch_mutation_tail(
                journal=journal,
                router_decision_event=router_decision_event,
                patch_event=mutation_event,
                completion_event=mutation_completion_event,
            )
        elif mutation_completion_event is not None:
            raise FastForegroundGateError(
                "mutation completion evidence is only valid for PATCH"
            )
    elif output_basis != "template_clarify":
        raise FastForegroundGateError("deferred commit basis is invalid")

    template = get_foreground_template(
        router_decision=router_decision,
        output_basis=output_basis,
    )
    safe_segment = _safe_segment(event_id_prefix)
    committed = _append_committed_output(
        journal,
        event_id=f"{event_id_prefix}_template_committed",
        caused_by_event_id=str(gate_result.gate_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        foreground_output_id=f"foreground_output_{safe_segment}_template",
        turn_id=str(router_decision_event["turn_id"]),
        utterance_id=str(router_decision_event["utterance_id"]),
        output_ref=template.template_ref,
        output_basis=template.output_basis,
        foreground_act=template.foreground_act,
        router_decision_event_id=str(router_decision_event["event_id"]),
        gate_event_id=str(gate_result.gate_event["event_id"]),
        fallback_policy_ref=template.fallback_policy_ref,
        fallback_reason=_require_safe_token(fallback_reason, "fallback_reason"),
    )
    return FastForegroundGateResult(
        gate_event=gate_result.gate_event,
        committed_event=committed,
        discarded_event=gate_result.discarded_event,
        gate_decision_ms=gate_result.gate_decision_ms,
        output_finalize_ms=gate_result.output_finalize_ms,
    )


def _validate_patch_mutation_tail(
    *,
    journal: InMemoryEventJournal,
    router_decision_event: Mapping[str, Any],
    patch_event: Mapping[str, Any],
    completion_event: Mapping[str, Any],
) -> None:
    _require_canonical_journal_event(journal, completion_event)
    if completion_event.get("event_name") != "SLOWTASK_STATE_CHANGED":
        raise FastForegroundGateError(
            "PATCH completion must be SLOWTASK_STATE_CHANGED"
        )
    task_id = patch_event.get("task_id")
    patch_id = patch_event.get("patch_id")
    patch_seq = _positive_int(patch_event.get("task_event_seq"), "task_event_seq")
    patch_plan = _positive_int(patch_event.get("plan_version"), "plan_version")
    completion_seq = _positive_int(
        completion_event.get("task_event_seq"),
        "completion_task_event_seq",
    )
    if (
        completion_event.get("task_id") != task_id
        or completion_seq != patch_seq + 5
        or completion_event.get("plan_version") != patch_plan + 1
        or completion_event.get("to_state") != "PLANNING"
    ):
        raise FastForegroundGateError("PATCH completion state is inconsistent")

    tail = [
        event
        for event in journal.events()
        if event.get("task_id") == task_id
        and patch_seq <= _optional_positive_int(event.get("task_event_seq"))
        <= completion_seq
    ]
    expected_names = (
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "PLANNING_RESTARTED",
        "TASK_REPLANNED",
        "SLOWTASK_STATE_CHANGED",
    )
    if tuple(event.get("event_name") for event in tail) != expected_names:
        raise FastForegroundGateError("PATCH canonical mutation tail is incomplete")
    received, interpreted, advanced, restarted, replanned, completed = tail
    if received != dict(patch_event) or completed != dict(completion_event):
        raise FastForegroundGateError("PATCH mutation mappings are not canonical")
    if (
        received.get("caused_by_event_id") != router_decision_event.get("event_id")
        or interpreted.get("caused_by_event_id") != received.get("event_id")
        or interpreted.get("patch_id") != patch_id
        or interpreted.get("plan_version") != patch_plan
        or interpreted.get("task_event_seq") != patch_seq + 1
        or interpreted.get("materially_changes_task") is not True
        or advanced.get("caused_by_event_id") != interpreted.get("event_id")
        or advanced.get("caused_by_user_patch_event_id") != received.get("event_id")
        or advanced.get("from_plan_version") != patch_plan
        or advanced.get("to_plan_version") != patch_plan + 1
        or advanced.get("plan_version") != patch_plan + 1
        or advanced.get("task_event_seq") != patch_seq + 2
        or restarted.get("caused_by_event_id") != advanced.get("event_id")
        or restarted.get("plan_version") != patch_plan + 1
        or restarted.get("task_event_seq") != patch_seq + 3
        or replanned.get("caused_by_event_id") != advanced.get("event_id")
        or replanned.get("plan_version") != patch_plan + 1
        or replanned.get("task_event_seq") != patch_seq + 4
        or completed.get("caused_by_event_id") != replanned.get("event_id")
    ):
        raise FastForegroundGateError("PATCH canonical mutation tail is inconsistent")


def _append_committed_output(
    journal: InMemoryEventJournal,
    *,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    foreground_output_id: str,
    turn_id: str,
    utterance_id: str,
    output_ref: str,
    output_basis: str,
    foreground_act: str,
    router_decision_event_id: str,
    gate_event_id: str | None = None,
    fallback_policy_ref: str | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    _require_safe_ref(output_ref, "output_ref")
    fields: dict[str, Any] = {}
    if gate_event_id is not None:
        fields["gate_event_id"] = gate_event_id
    if fallback_policy_ref is not None:
        fields["fallback_policy_ref"] = fallback_policy_ref
    if fallback_reason is not None:
        fields["fallback_reason"] = fallback_reason
    return journal.append(
        event_name="FOREGROUND_OUTPUT_COMMITTED",
        event_id=event_id,
        source_module="foreground_output_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        foreground_output_id=foreground_output_id,
        turn_id=turn_id,
        utterance_id=utterance_id,
        output_ref=output_ref,
        output_basis=output_basis,
        foreground_act=_require_safe_token(foreground_act, "foreground_act"),
        router_decision_event_id=router_decision_event_id,
        user_visible_channel="text",
        **fields,
    )


def _failure_reason(
    *,
    router_decision: str,
    task_focus: str,
    foreground_act: str,
    risk_class: str,
    risk_tags_present: bool,
    risk_tags: tuple[str, ...] | None,
    candidate_risk_tags_present: bool,
    candidate_risk_tags: tuple[str, ...] | None,
    confidence: float,
    candidate_event: Mapping[str, Any],
    fast_interaction_output_event: Mapping[str, Any],
    context: FastForegroundGateContext,
    threshold: float,
) -> str | None:
    if context.authority_binding_status == "missing":
        return "gate_authority_context_missing"
    if context.authority_binding_status != "bound":
        return "gate_authority_context_mismatch"
    if context.interaction_state is None or context.interaction_state_ref is None:
        return "interaction_state_missing"
    if context.interaction_state not in _INTERACTION_STATES:
        return "interaction_state_unknown"
    if context.task_focus is None or context.task_focus_snapshot_ref is None:
        return "task_focus_context_missing"
    if context.task_focus not in _TASK_FOCUS_STATES:
        return "task_focus_context_unknown"
    slowtask_context_failure = _slowtask_context_failure(context)
    if slowtask_context_failure is not None:
        return slowtask_context_failure
    candidate_policy_failure = _candidate_policy_failure(context)
    if candidate_policy_failure is not None:
        return candidate_policy_failure
    if context.capability_snapshot_ref is None:
        return "capability_context_missing"
    if (
        context.capability_health_status is None
        or context.capability_output_mode is None
        or context.capability_verification_status is None
    ):
        return "capability_context_missing"
    if context.schema_valid is None:
        return "schema_validation_missing"
    if context.confidence_threshold is None:
        return "confidence_threshold_missing"
    if not context.schema_valid:
        return "capability_schema_invalid"
    if context.capability_health_status != "ready":
        return "capability_not_ready"
    if context.capability_output_mode not in {"mock", "real"}:
        return "capability_not_ready"
    if context.capability_verification_status not in {
        "provider_free_verified",
        "real_live_verified",
    }:
        return "capability_not_ready"
    if fast_interaction_output_event.get("output_mode") != context.capability_output_mode:
        return "capability_output_mode_mismatch"
    if context.interaction_state not in _GATE_READY_INTERACTION_STATES:
        return "interaction_state_not_ready"
    if context.task_focus != task_focus:
        return "task_focus_context_mismatch"
    if context.pending_confirmation:
        return "pending_confirmation_active"
    if task_focus == "AMBIGUOUS":
        return "task_focus_ambiguous"
    if task_focus in {
        "ACTIVE_TASK_PATCH",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
    }:
        return "task_focus_not_foreground_chat"
    if task_focus != "FOREGROUND_CHAT":
        return "task_focus_not_foreground_chat"
    if router_decision != "FAST_ONLY":
        return "router_decision_not_fast_only"
    if foreground_act != "ANSWER":
        return "foreground_act_not_answer"
    if not risk_tags_present or not candidate_risk_tags_present:
        return "risk_tags_missing"
    if risk_tags is None or candidate_risk_tags is None:
        return "risk_tags_invalid"
    if risk_tags != candidate_risk_tags:
        return "risk_signal_conflict"
    risk_tags_are_low = risk_tags in {(), ("none",)}
    if risk_class == "LOW" and not risk_tags_are_low:
        return "risk_signal_conflict"
    if not risk_tags_are_low:
        return "risk_tag_not_low"
    if risk_class != "LOW":
        return "risk_class_not_low"
    if confidence < threshold:
        return "confidence_below_threshold"
    if candidate_event.get("candidate_status") != "complete":
        return "candidate_not_complete"
    candidate_ref = candidate_event.get("candidate_ref")
    if not isinstance(candidate_ref, str) or not is_safe_mvp5_live_ref(candidate_ref):
        return "candidate_boundary_unsafe"
    if (
        context.candidate_policy_decision.provenance == "local_deterministic_template"
    ):
        template = foreground_template_by_ref(candidate_ref)
        if template is None or template.router_decision != router_decision:
            return "candidate_template_ref_invalid"
        return "local_template_requires_fallback_commit"
    return None


def _candidate_policy_failure(context: FastForegroundGateContext) -> str | None:
    decision = context.candidate_policy_decision
    if decision.decision != "allow":
        return "candidate_policy_quarantined"
    if decision.provenance == "trusted_synthetic":
        if context.authority_mode != "trusted_synthetic_eval":
            return "candidate_policy_provenance_mismatch"
        return None
    if decision.provenance == "local_deterministic_template":
        return None
    return "candidate_policy_provenance_mismatch"


def _slowtask_context_failure(context: FastForegroundGateContext) -> str | None:
    if context.has_active_slowtask is None or context.pending_confirmation is None:
        return "active_slowtask_context_missing"
    if context.active_slowtask_lifecycle is not None:
        if context.active_slowtask_lifecycle not in _SLOWTASK_STATES:
            return "active_slowtask_lifecycle_unknown"
        if context.active_slowtask_lifecycle in _TERMINAL_SLOWTASK_STATES:
            return "active_slowtask_lifecycle_terminal"
    if context.has_active_slowtask:
        if (
            context.active_task_id is None
            or context.active_slowtask_lifecycle is None
            or context.active_plan_version is None
            or context.active_task_event_seq is None
        ):
            return "active_slowtask_context_missing"
    elif any(
        value is not None
        for value in (
            context.active_task_id,
            context.active_slowtask_lifecycle,
            context.active_plan_version,
            context.active_task_event_seq,
        )
    ):
        return "active_slowtask_context_inconsistent"
    if context.pending_confirmation:
        if not context.has_active_slowtask:
            return "pending_confirmation_context_inconsistent"
        if (
            context.pending_confirmation_id is None
            or context.pending_confirmation_scope is None
        ):
            return "pending_confirmation_context_missing"
        if context.active_slowtask_lifecycle != "WAITING_FOR_USER_CONFIRMATION":
            return "pending_confirmation_context_inconsistent"
    elif (
        context.pending_confirmation_id is not None
        or context.pending_confirmation_scope is not None
        or context.active_slowtask_lifecycle == "WAITING_FOR_USER_CONFIRMATION"
    ):
        return "pending_confirmation_context_inconsistent"
    return None


def _normalized_risk_tags(
    value: object,
    *,
    present: bool,
) -> tuple[str, ...] | None:
    if not present or value is None:
        return None
    if not isinstance(value, (list, tuple)):
        return None
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            return None
        token = item.strip().lower()
        if not token or token != item.lower():
            return None
        normalized.append(token)
    return tuple(normalized)


def _validate_candidate_provenance(
    *,
    candidate_event: Mapping[str, Any],
    fast_interaction_output_event: Mapping[str, Any],
    router_decision_event: Mapping[str, Any],
) -> None:
    fast_event_id = str(fast_interaction_output_event["event_id"])
    if candidate_event.get("fast_interaction_output_event_id") != fast_event_id:
        raise FastForegroundGateError("candidate must reference Fast Interaction output event")
    if candidate_event.get("caused_by_event_id") != fast_event_id:
        raise FastForegroundGateError("candidate must be caused by Fast Interaction output event")
    for field in ("turn_id", "utterance_id"):
        if candidate_event.get(field) != fast_interaction_output_event.get(field):
            raise FastForegroundGateError(f"candidate must match Fast Interaction {field}")
        if router_decision_event.get(field) != fast_interaction_output_event.get(field):
            raise FastForegroundGateError(f"router decision must match Fast Interaction {field}")
    if router_decision_event.get("fast_interaction_output_event_id") != fast_event_id:
        raise FastForegroundGateError("router decision must reference Fast Interaction output event")
    input_mode = fast_interaction_output_event.get("input_mode")
    if input_mode not in {"audio_native", "asr_text_fallback"}:
        raise FastForegroundGateError("Fast Interaction input_mode is invalid")
    if candidate_event.get("input_mode") != input_mode:
        raise FastForegroundGateError("candidate input_mode must match Fast Interaction output")
    if candidate_event.get("fast_interaction_input_mode") != input_mode:
        raise FastForegroundGateError(
            "candidate fast_interaction_input_mode must match Fast Interaction output"
        )
    source_event_ids = candidate_event.get("source_event_ids")
    if not isinstance(source_event_ids, (list, tuple)) or fast_event_id not in {
        str(event_id) for event_id in source_event_ids
    }:
        raise FastForegroundGateError("candidate source_event_ids must include Fast Interaction output")


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _downgrade_policy(
    router_decision: str,
    *,
    task_focus: str = "",
    foreground_act: str = "",
) -> str:
    if router_decision in {"SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"}:
        return "deferred_mutation_outcome"
    if router_decision == "FAST_ONLY" or task_focus == "AMBIGUOUS":
        return "template_clarify"
    return "discard_only"


def _require_event(event: Mapping[str, Any], expected_name: str) -> None:
    if event.get("event_name") != expected_name:
        raise FastForegroundGateError(f"expected {expected_name}")


def _require_canonical_journal_event(
    journal: InMemoryEventJournal,
    event: Mapping[str, Any],
) -> None:
    event_id = event.get("event_id")
    matches = [
        candidate
        for candidate in journal.events()
        if candidate.get("event_id") == event_id
    ]
    if len(matches) != 1 or matches[0] != dict(event):
        raise FastForegroundGateError(
            "Gate event mapping must match canonical journal payload"
        )


def _confidence(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FastForegroundGateError("confidence must be numeric")
    if value < 0.0 or value > 1.0:
        raise FastForegroundGateError("confidence must be in [0, 1]")
    return float(value)


def _validate_threshold(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0.0
        or value > 1.0
    ):
        raise FastForegroundGateError(f"{field} must be in [0, 1]")
    return float(value)


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise FastForegroundGateError(f"{field} must be positive")
    return value


def _optional_positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return -1
    return value


def _require_safe_ref(value: object, field: str) -> str:
    token = _require_safe_token(value, field)
    if "://" not in token or not is_safe_mvp5_live_ref(token):
        raise FastForegroundGateError(f"{field} must be a safe ref")
    return token


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise FastForegroundGateError(f"{field} must be a non-empty string")
    lowered = value.lower()
    if any(marker in lowered for marker in ("authorization=", "api_key=", "token=", "bearer ")):
        raise FastForegroundGateError(f"{field} must not contain credential-like content")
    if value.startswith(("/", "~", "\\")):
        raise FastForegroundGateError(f"{field} must not be a local path")
    return value


def _safe_segment(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_") or "unknown"
