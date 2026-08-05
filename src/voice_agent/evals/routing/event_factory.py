from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from voice_agent.evals.routing.case import RoutingCase, validate_routing_case
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.router.router import (
    MVP1_ROUTER_DECISIONS,
    MVP1_TASK_FOCUS_VALUES,
    RouterContext,
    TaskFocusSnapshot,
)
from voice_agent.runtime.session import start_mvp0_session


PREDICTED_DIRECTEDNESS_VALUES = frozenset({"ASSUMED_DIRECTED", "NOT_DIRECTED"})
PREDICTED_FOREGROUND_ACTS = frozenset(
    {"ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY"}
)
PREDICTED_RISK_CLASSES = frozenset({"LOW", "MEDIUM", "HIGH"})


class ScenarioEventFactoryError(ValueError):
    pass


@dataclass(frozen=True)
class PredictedRoutingEvidence:
    """Explicit model prediction used to construct provider-free evidence.

    Nothing in this type is populated from a case's gold labels by the event
    factory or router runner.  Policy-layer tests that intentionally need label
    derived evidence must call the conspicuously named oracle helper in
    ``router_runner``.
    """

    task_focus_hint: str | None
    route_decision_hint: str | None
    task_like: bool
    complexity_hint: str
    evidence_uncertainty: str
    directedness: str = "ASSUMED_DIRECTED"
    foreground_act: str = "CLARIFY"
    risk_class: str = "LOW"
    confidence: float = 0.8
    emit_candidate: bool = True

    def __post_init__(self) -> None:
        if self.task_focus_hint is not None and self.task_focus_hint not in MVP1_TASK_FOCUS_VALUES:
            raise ScenarioEventFactoryError("task_focus_hint must be an ADR-006 focus value")
        if (
            self.route_decision_hint is not None
            and self.route_decision_hint not in MVP1_ROUTER_DECISIONS
        ):
            raise ScenarioEventFactoryError("route_decision_hint must be an MVP-1 route")
        if not isinstance(self.task_like, bool):
            raise ScenarioEventFactoryError("task_like must be a boolean")
        if not isinstance(self.emit_candidate, bool):
            raise ScenarioEventFactoryError("emit_candidate must be a boolean")
        if not isinstance(self.complexity_hint, str) or not self.complexity_hint:
            raise ScenarioEventFactoryError("complexity_hint must be a non-empty string")
        if not isinstance(self.evidence_uncertainty, str) or not self.evidence_uncertainty:
            raise ScenarioEventFactoryError("evidence_uncertainty must be a non-empty string")
        if self.directedness not in PREDICTED_DIRECTEDNESS_VALUES:
            raise ScenarioEventFactoryError(
                f"directedness must be one of {sorted(PREDICTED_DIRECTEDNESS_VALUES)}"
            )
        if self.foreground_act not in PREDICTED_FOREGROUND_ACTS:
            raise ScenarioEventFactoryError(
                f"foreground_act must be one of {sorted(PREDICTED_FOREGROUND_ACTS)}"
            )
        if self.risk_class not in PREDICTED_RISK_CLASSES:
            raise ScenarioEventFactoryError(
                f"risk_class must be one of {sorted(PREDICTED_RISK_CLASSES)}"
            )
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ScenarioEventFactoryError("confidence must be a number between 0 and 1")


@dataclass(frozen=True)
class ScenarioEventBundle:
    case_id: str
    model_input: dict[str, Any]
    journal: InMemoryEventJournal
    router_context: RouterContext
    turn_opened_event: dict[str, Any]
    ingress_accepted_event: dict[str, Any]
    turn_committed_event: dict[str, Any]
    asr_event: dict[str, Any] | None
    fast_interaction_event: dict[str, Any]
    candidate_event: dict[str, Any] | None


class ScenarioEventFactory:
    """Build deterministic, provider-free canonical events for one eval case."""

    BASE_MONOTONIC_MS = 1_000
    BASE_WALL_CLOCK_MS = 1_700_000_001_000

    def build(
        self,
        case: RoutingCase | Mapping[str, Any],
        *,
        predicted_evidence: PredictedRoutingEvidence,
    ) -> ScenarioEventBundle:
        normalized = case if isinstance(case, RoutingCase) else validate_routing_case(case)
        case_id = normalized.case_id
        session_id = f"sess_routing_eval_{case_id}"
        startup = start_mvp0_session(
            session_id=session_id,
            conversation_id=f"conv_routing_eval_{case_id}",
            runtime_config_ref="config://synthetic/routing-eval/policy-v1",
            created_monotonic_ms=self.BASE_MONOTONIC_MS,
            created_wall_clock_ms=self.BASE_WALL_CLOCK_MS,
        )
        journal = startup.journal
        turn_opened, accepted, committed = self._append_turn(
            journal,
            case=normalized,
            directedness=predicted_evidence.directedness,
        )
        # The manifest may contain synthetic text before TTS materialization, but
        # this policy runner evaluates the audio-native production route.  The
        # source text remains in model_input only; the canonical runtime envelope
        # is always an audio turn and never journals that text.
        asr_event = None
        fast_event = self._append_fast_interaction(
            journal,
            case_id=case_id,
            turn=committed,
            asr_event=asr_event,
            predicted_evidence=predicted_evidence,
        )
        candidate_event = None
        if predicted_evidence.emit_candidate:
            candidate_event = self._append_candidate(
                journal,
                case_id=case_id,
                fast_event=fast_event,
                predicted_evidence=predicted_evidence,
            )
        return ScenarioEventBundle(
            case_id=case_id,
            model_input=normalized.to_model_input(),
            journal=journal,
            router_context=self.router_context_for_case(normalized),
            turn_opened_event=turn_opened,
            ingress_accepted_event=accepted,
            turn_committed_event=committed,
            asr_event=asr_event,
            fast_interaction_event=fast_event,
            candidate_event=candidate_event,
        )

    @staticmethod
    def router_context_for_case(case: RoutingCase) -> RouterContext:
        active_task = case.context.active_task
        if active_task is None:
            return RouterContext(task_focus_snapshot=TaskFocusSnapshot())
        terminal_status = (
            active_task.lifecycle_phase
            if active_task.lifecycle_phase in {"COMPLETED", "CANCELLED", "FAILED"}
            else None
        )
        return RouterContext(
            task_focus_snapshot=TaskFocusSnapshot(
                active_task_id=active_task.task_id,
                lifecycle_phase=active_task.lifecycle_phase,
                terminal_status=terminal_status,
                current_plan_version=active_task.plan_version,
                pending_confirmation_scope=active_task.pending_confirmation_scope,
            ),
            side_conversation_allowed=True,
            default_patch_policy=(
                "NO_ACTIVE_TASK" if terminal_status is not None else "ACTIVE_TASK_PATCH_ONLY"
            ),
            ambiguous_input_policy="CLARIFY",
        )

    def _append_turn(
        self,
        journal: InMemoryEventJournal,
        *,
        case: RoutingCase,
        directedness: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        case_id = case.case_id
        parent_event_id = str(journal.events()[-1]["event_id"])
        span_field = "audio_span_id"
        span_value = f"audio_span_routing_eval_{case_id}"
        turn_opened = journal.append(
            event_name="TURN_OPENED",
            event_id=f"evt_routing_eval_{case_id}_turn_opened",
            source_module="interaction_controller",
            caused_by_event_id=parent_event_id,
            created_monotonic_ms=self.BASE_MONOTONIC_MS + 10,
            created_wall_clock_ms=self.BASE_WALL_CLOCK_MS + 10,
            trace_redaction_level="metadata_only",
            turn_id=f"turn_routing_eval_{case_id}",
            turn_phase="COLLECTING_INPUT",
            input_modality="audio",
            **{span_field: span_value},
        )
        accepted = journal.append(
            event_name="TURN_INGRESS_ACCEPTED",
            event_id=f"evt_routing_eval_{case_id}_ingress_accepted",
            source_module="interaction_controller",
            caused_by_event_id=str(turn_opened["event_id"]),
            created_monotonic_ms=self.BASE_MONOTONIC_MS + 11,
            created_wall_clock_ms=self.BASE_WALL_CLOCK_MS + 11,
            trace_redaction_level="metadata_only",
            turn_id=str(turn_opened["turn_id"]),
            ingress_outcome="ACCEPTED",
            **{span_field: span_value},
        )
        committed = journal.append(
            event_name="TURN_INGRESS_COMMITTED",
            event_id=f"evt_routing_eval_{case_id}_ingress_committed",
            source_module="interaction_controller",
            caused_by_event_id=str(accepted["event_id"]),
            created_monotonic_ms=self.BASE_MONOTONIC_MS + 12,
            created_wall_clock_ms=self.BASE_WALL_CLOCK_MS + 12,
            trace_redaction_level="metadata_only",
            turn_id=str(turn_opened["turn_id"]),
            utterance_id=f"utt_routing_eval_{case_id}",
            input_modality="audio",
            directedness=directedness,
            semantic_close="ASSUMED_CLOSED",
            ingress_outcome="COMMITTED",
            **{span_field: span_value},
        )
        return turn_opened, accepted, committed

    def _append_fast_interaction(
        self,
        journal: InMemoryEventJournal,
        *,
        case_id: str,
        turn: Mapping[str, Any],
        asr_event: Mapping[str, Any] | None,
        predicted_evidence: PredictedRoutingEvidence,
    ) -> dict[str, Any]:
        input_mode = "audio_native" if asr_event is None else "asr_text_fallback"
        caused_by = str(turn["event_id"] if asr_event is None else asr_event["event_id"])
        source_event_ids = (
            (str(turn["event_id"]),)
            if asr_event is None
            else (str(turn["event_id"]), str(asr_event["event_id"]))
        )
        optional_fields: dict[str, Any] = {}
        if predicted_evidence.task_focus_hint is not None:
            optional_fields["task_focus_hint"] = predicted_evidence.task_focus_hint
        if predicted_evidence.route_decision_hint is not None:
            optional_fields["route_decision_hint"] = predicted_evidence.route_decision_hint
        return journal.append(
            event_name="FAST_INTERACTION_OUTPUT_EMITTED",
            event_id=f"evt_routing_eval_{case_id}_fast_interaction",
            source_module="routing_eval_fast_interaction_adapter",
            caused_by_event_id=caused_by,
            created_monotonic_ms=self.BASE_MONOTONIC_MS + 21,
            created_wall_clock_ms=self.BASE_WALL_CLOCK_MS + 21,
            trace_redaction_level="metadata_only",
            adapter_id="routing_eval_synthetic_fast_interaction",
            adapter_type="fast_interaction",
            adapter_request_id=f"req_routing_eval_{case_id}_fast_interaction",
            turn_id=str(turn["turn_id"]),
            utterance_id=str(turn["utterance_id"]),
            input_modality=str(turn["input_modality"]),
            input_mode=input_mode,
            fast_interaction_input_mode=input_mode,
            source_event_ids=source_event_ids,
            route_hint_ref=f"route-hint://synthetic/routing-eval/{case_id}",
            route_prelude_ref=f"route-prelude://synthetic/routing-eval/{case_id}",
            foreground_act=predicted_evidence.foreground_act,
            final_fast_evidence_ref=f"fast-evidence://synthetic/routing-eval/{case_id}",
            risk_tags=("none",),
            risk_class=predicted_evidence.risk_class,
            confidence=float(predicted_evidence.confidence),
            schema_name="voice_agent.fast_interaction.output.v1",
            normalization_status="normalized",
            output_mode="mock",
            task_like=predicted_evidence.task_like,
            complexity_hint=predicted_evidence.complexity_hint,
            evidence_uncertainty=predicted_evidence.evidence_uncertainty,
            **optional_fields,
        )

    def _append_candidate(
        self,
        journal: InMemoryEventJournal,
        *,
        case_id: str,
        fast_event: Mapping[str, Any],
        predicted_evidence: PredictedRoutingEvidence,
    ) -> dict[str, Any]:
        return journal.append(
            event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
            event_id=f"evt_routing_eval_{case_id}_foreground_candidate",
            source_module="routing_eval_foreground_buffer",
            caused_by_event_id=str(fast_event["event_id"]),
            created_monotonic_ms=self.BASE_MONOTONIC_MS + 22,
            created_wall_clock_ms=self.BASE_WALL_CLOCK_MS + 22,
            trace_redaction_level="metadata_only",
            candidate_id=f"candidate_routing_eval_{case_id}",
            fast_interaction_output_event_id=str(fast_event["event_id"]),
            turn_id=str(fast_event["turn_id"]),
            utterance_id=str(fast_event["utterance_id"]),
            input_mode=str(fast_event["input_mode"]),
            fast_interaction_input_mode=str(fast_event["fast_interaction_input_mode"]),
            source_event_ids=(str(fast_event["event_id"]),),
            candidate_ref=f"foreground-candidate://synthetic/routing-eval/{case_id}",
            candidate_status="complete",
            risk_tags=("none",),
            confidence=float(predicted_evidence.confidence),
        )
