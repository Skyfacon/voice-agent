from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import time
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.mvp5_live_approval import is_safe_mvp5_live_ref


FAST_FOREGROUND_GATE_POLICY_VERSION = "mvp6.3.fast_foreground_gate.v1"


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


@dataclass(frozen=True)
class FastForegroundGateResult:
    gate_event: dict[str, Any]
    committed_event: dict[str, Any] | None
    discarded_event: dict[str, Any] | None
    gate_decision_ms: int
    output_finalize_ms: int


def run_fast_foreground_gate(
    journal: InMemoryEventJournal,
    *,
    candidate_event: Mapping[str, Any],
    fast_interaction_output_event: Mapping[str, Any],
    router_decision_event: Mapping[str, Any],
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
    event_id_prefix = _require_safe_token(event_id_prefix, "event_id_prefix")
    _validate_candidate_provenance(
        candidate_event=candidate_event,
        fast_interaction_output_event=fast_interaction_output_event,
        router_decision_event=router_decision_event,
    )

    router_decision = str(router_decision_event["router_decision"])
    task_focus = str(router_decision_event.get("task_focus", ""))
    foreground_act = str(fast_interaction_output_event["foreground_act"])
    risk_class = str(fast_interaction_output_event.get("risk_class", "MEDIUM"))
    confidence = _confidence(fast_interaction_output_event.get("confidence", 0.0))
    failure_reason = _failure_reason(
        router_decision=router_decision,
        task_focus=task_focus,
        foreground_act=foreground_act,
        risk_class=risk_class,
        confidence=confidence,
        candidate_event=candidate_event,
        threshold=float(config.confidence_threshold),
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
        downgrade_policy=_downgrade_policy(router_decision, task_focus=task_focus),
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
    downgrade_policy = _downgrade_policy(router_decision, task_focus=task_focus)
    if downgrade_policy in {"template_ack", "template_clarify"}:
        committed = _append_committed_output(
            journal,
            event_id=f"{event_id_prefix}_template_committed",
            caused_by_event_id=str(gate_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 2,
            created_wall_clock_ms=created_wall_clock_ms + 2,
            foreground_output_id=f"foreground_output_{safe_segment}_template",
            turn_id=str(router_decision_event["turn_id"]),
            utterance_id=str(router_decision_event["utterance_id"]),
            output_ref=f"foreground-template://synthetic/{safe_segment}/{_template_suffix(downgrade_policy)}",
            output_basis=downgrade_policy,
            router_decision_event_id=str(router_decision_event["event_id"]),
            gate_event_id=str(gate_event["event_id"]),
            fallback_policy_ref=f"fallback-policy://synthetic/{safe_segment}/{downgrade_policy}",
            fallback_reason=failure_reason,
        )
        discarded["replacement_output_event_id"] = str(committed["event_id"])
    return FastForegroundGateResult(
        gate_event=gate_event,
        committed_event=committed,
        discarded_event=discarded,
        gate_decision_ms=gate_decision_ms,
        output_finalize_ms=_elapsed_ms(output_started),
    )


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
    confidence: float,
    candidate_event: Mapping[str, Any],
    threshold: float,
) -> str | None:
    if task_focus == "AMBIGUOUS":
        return "task_focus_ambiguous"
    if router_decision != "FAST_ONLY":
        return "router_decision_not_fast_only"
    if foreground_act != "ANSWER":
        return "foreground_act_not_answer"
    if risk_class != "LOW":
        return "risk_class_not_low"
    if confidence < threshold:
        return "confidence_below_threshold"
    if candidate_event.get("candidate_status") != "complete":
        return "candidate_not_complete"
    candidate_ref = candidate_event.get("candidate_ref")
    if not isinstance(candidate_ref, str) or not is_safe_mvp5_live_ref(candidate_ref):
        return "candidate_boundary_unsafe"
    return None


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


def _downgrade_policy(router_decision: str, *, task_focus: str = "") -> str:
    if task_focus == "AMBIGUOUS":
        return "template_clarify"
    if router_decision in {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"}:
        return "template_ack"
    if router_decision in {"AMBIGUOUS"}:
        return "template_clarify"
    return "discard_only"


def _template_suffix(downgrade_policy: str) -> str:
    if downgrade_policy == "template_clarify":
        return "clarify"
    return "ack"


def _require_event(event: Mapping[str, Any], expected_name: str) -> None:
    if event.get("event_name") != expected_name:
        raise FastForegroundGateError(f"expected {expected_name}")


def _confidence(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FastForegroundGateError("confidence must be numeric")
    if value < 0.0 or value > 1.0:
        raise FastForegroundGateError("confidence must be in [0, 1]")
    return float(value)


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
