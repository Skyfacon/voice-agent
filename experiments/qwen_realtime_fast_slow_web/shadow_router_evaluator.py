"""Isolated deterministic Router evaluation for Slice 2 shadow proposals.

The evaluator deliberately owns a separate, short-lived journal for every
proposal.  It may reuse the accepted Router implementation, but none of its
events are appended to the authoritative browser-session journal and none of
its state is reduced into ``TaskFocusState`` or ``SlowTaskState``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from voice_agent.adapters.fast_interaction_contract import (
    FastInteractionBinding,
    FastInteractionOutput,
    emit_fast_interaction_events,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary

from .realtime_evidence import ProviderRouteProposal, RealtimeTurnEvidenceBundle


class ShadowProposalLike(Protocol):
    """Minimum validated proposal surface consumed by the local evaluator."""

    route_decision_hint: str
    task_focus_hint: str
    foreground_act: str
    risk_class: str
    risk_tags: Sequence[str]
    confidence: float
    task_like: bool
    complexity_hint: str
    evidence_uncertainty: str
    reply_candidate_text: str | None


@dataclass(frozen=True, slots=True)
class ShadowRouterEvaluation:
    local_router_decision: str
    local_task_focus: str
    local_foreground_act: str
    route_agreement: bool
    task_focus_agreement: bool
    foreground_act_agreement: bool
    agreement: str
    evaluation_latency_ms: int
    isolated_event_count: int

    def to_metadata(self) -> dict[str, Any]:
        return {
            "local_router_decision": self.local_router_decision,
            "local_task_focus": self.local_task_focus,
            "local_foreground_act": self.local_foreground_act,
            "route_agreement": self.route_agreement,
            "task_focus_agreement": self.task_focus_agreement,
            "foreground_act_agreement": self.foreground_act_agreement,
            "agreement": self.agreement,
            "function_done_to_local_router_ms": self.evaluation_latency_ms,
            "isolated_event_count": self.isolated_event_count,
        }


class ShadowRouterEvaluator:
    """Run the canonical deterministic Router against an isolated state copy."""

    def __init__(self, *, session_ref: str) -> None:
        safe_ref = _safe_token(session_ref, fallback="session")
        self._session_ref = safe_ref
        self._counter = 0

    def evaluate(
        self,
        *,
        proposal: ShadowProposalLike,
        turn_id: str,
        utterance_id: str,
        audio_span_id: str,
        asr_frame_ref: str,
        task_focus_snapshot: TaskFocusSnapshot,
        output_mode: str = "degraded",
    ) -> ShadowRouterEvaluation:
        """Evaluate one already validated proposal without authoritative writes."""

        started = time.monotonic()
        self._counter += 1
        sequence = self._counter
        safe_turn = _safe_token(turn_id, fallback=f"turn_{sequence}")
        safe_utterance = _safe_token(utterance_id, fallback=f"utterance_{sequence}")
        safe_audio = _safe_token(audio_span_id, fallback=f"audio_{sequence}")
        safe_asr = _safe_token(asr_frame_ref, fallback=f"asr_{sequence}")
        journal = InMemoryEventJournal(
            session_id=f"shadow_eval_{self._session_ref}_{sequence:04d}",
            conversation_id=f"shadow_eval_conversation_{self._session_ref}",
        )
        boundary = AdapterCallbackAppendBoundary(journal)
        router = MVP1Router(journal)
        now_mono, now_wall = _now_ms()

        session_started = journal.append(
            event_name="SESSION_STARTED",
            event_id=_event_id(sequence, "session_started"),
            source_module="qfs_shadow_router_evaluator",
            created_monotonic_ms=now_mono,
            created_wall_clock_ms=now_wall,
            trace_redaction_level="metadata_only",
            runtime_config_ref="runtime-config://experiment/qfs/shadow-evaluation",
            capability_snapshot_ref="capability://experiment/qfs/shadow-evaluation",
        )
        turn_committed = journal.append(
            event_name="TURN_INGRESS_COMMITTED",
            event_id=_event_id(sequence, "turn_committed"),
            source_module="qfs_shadow_router_evaluator",
            caused_by_event_id=str(session_started["event_id"]),
            created_monotonic_ms=now_mono + 1,
            created_wall_clock_ms=now_wall + 1,
            trace_redaction_level="metadata_only",
            turn_id=safe_turn,
            utterance_id=safe_utterance,
            input_modality="audio",
            audio_span_id=safe_audio,
            directedness="ASSUMED_DIRECTED",
            semantic_close="ASSUMED_CLOSED",
            ingress_outcome="COMMITTED",
        )
        asr_output = boundary.append_adapter_event(
            event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
            event_id=_event_id(sequence, "asr_output"),
            source_module="qfs_shadow_router_evaluator",
            caused_by_event_id=str(turn_committed["event_id"]),
            created_monotonic_ms=now_mono + 2,
            created_wall_clock_ms=now_wall + 2,
            trace_redaction_level="metadata_only",
            adapter_id="qfs_shadow_asr_projection_v1",
            adapter_type="asr",
            adapter_request_id=f"shadow_asr_request_{sequence:04d}",
            turn_id=safe_turn,
            utterance_id=safe_utterance,
            input_modality="audio",
            audio_span_id=safe_audio,
            asr_frame_ref=f"asr-frame://experiment/qfs-shadow/{safe_asr}",
            text_ref=f"text://redacted/qfs-shadow/{safe_turn}",
            transcript_finality="final",
            timestamp_status="unavailable",
            streaming_status="supported",
            normalization_status="normalized",
            output_mode="degraded",
        )
        # Bind the locally owned request/turn/ASR correlation through the same
        # experiment-local evidence contract used by Slice 1.  ``mock`` here
        # describes this isolated evaluation projection; the real/fake/
        # degraded provider mode remains separately carried by ``output_mode``
        # below and by the coordinator metadata.
        normalized_proposal = ProviderRouteProposal(
            scenario="shadow_evaluation",
            response_id=f"shadow_response_{sequence:04d}",
            provider_item_id=f"shadow_item_{sequence:04d}",
            route_hint=proposal.route_decision_hint,
            task_focus_hint=proposal.task_focus_hint,
            foreground_act=proposal.foreground_act,
            risk_class=proposal.risk_class,
            confidence=float(proposal.confidence),
            output_mode="mock",
        )
        evidence_bundle = RealtimeTurnEvidenceBundle(
            turn_id=safe_turn,
            utterance_id=safe_utterance,
            audio_span_id=safe_audio,
            provider_item_id=normalized_proposal.provider_item_id,
            response_id=normalized_proposal.response_id,
            playback_epoch=0,
            turn_committed_event=turn_committed,
            asr_frame_event=asr_output,
            proposal=normalized_proposal,
        )
        binding = FastInteractionBinding.from_turn_and_asr_fallback(
            evidence_bundle.turn_committed_event,
            asr_output_event=evidence_bundle.asr_frame_event,
            adapter_request_id=f"shadow_route_request_{sequence:04d}",
        )
        reply_ref = None
        candidate_id = None
        if proposal.reply_candidate_text:
            # The actual candidate remains transient in the provider adapter.
            reply_ref = f"reply-candidate://transient/qfs-shadow/{safe_turn}"
            candidate_id = f"shadow_candidate_{sequence:04d}"
        risk_tags = tuple(proposal.risk_tags) or ("shadow_evidence",)
        fast_output = FastInteractionOutput(
            adapter_id="qfs_qwen_shadow_router_v1",
            route_hint_ref=f"route-hint://experiment/qfs-shadow/{safe_turn}",
            route_prelude_ref=f"route-prelude://experiment/qfs-shadow/{safe_turn}",
            foreground_act=proposal.foreground_act,
            final_fast_evidence_ref=f"fast-evidence://experiment/qfs-shadow/{safe_turn}",
            risk_tags=risk_tags,
            risk_class=proposal.risk_class,
            confidence=float(proposal.confidence),
            output_mode=(
                output_mode
                if output_mode in {"real", "mock", "fallback", "degraded"}
                else "degraded"
            ),
            reply_candidate_ref=reply_ref,
            candidate_id=candidate_id,
            route_decision_hint=proposal.route_decision_hint,
            task_focus_hint=proposal.task_focus_hint,
        )
        emission = emit_fast_interaction_events(
            boundary=boundary,
            binding=binding,
            output=fast_output,
            output_event_id=_event_id(sequence, "fast_output"),
            candidate_event_id=(
                _event_id(sequence, "candidate") if reply_ref is not None else None
            ),
            created_monotonic_ms=now_mono + 3,
            created_wall_clock_ms=now_wall + 3,
            source_module="qfs_shadow_router_evaluator",
        )
        # Router consumes only normalized refs and enums.  Raw transcript and
        # raw function arguments never enter this isolated journal.
        router_evidence = dict(emission.output_event)
        router_evidence["task_like"] = bool(proposal.task_like)
        router_evidence["complexity_hint"] = _complexity_for_router(
            proposal.complexity_hint
        )
        router_evidence["evidence_uncertainty"] = str(
            proposal.evidence_uncertainty
        ).lower()
        router_result = router.emit_decision(
            turn_committed_event=evidence_bundle.turn_committed_event,
            asr_frame_event=evidence_bundle.asr_frame_event,
            fast_interaction_output_event=router_evidence,
            router_context=RouterContext(task_focus_snapshot=task_focus_snapshot),
            event_id=_event_id(sequence, "router_decision"),
            task_focus_state_event_id=_event_id(sequence, "task_focus_state"),
            created_monotonic_ms=now_mono + 5,
            created_wall_clock_ms=now_wall + 5,
        )
        router_event = router_result.router_decision_event
        local_route = str(router_event["router_decision"])
        local_focus = str(router_event["task_focus"])
        local_act = _local_foreground_act(local_route, local_focus)
        route_agreement = local_route == proposal.route_decision_hint
        focus_agreement = local_focus == proposal.task_focus_hint
        act_agreement = local_act == proposal.foreground_act
        latency_ms = max(0, int((time.monotonic() - started) * 1_000))
        return ShadowRouterEvaluation(
            local_router_decision=local_route,
            local_task_focus=local_focus,
            local_foreground_act=local_act,
            route_agreement=route_agreement,
            task_focus_agreement=focus_agreement,
            foreground_act_agreement=act_agreement,
            agreement=(
                "yes"
                if route_agreement and focus_agreement and act_agreement
                else "no"
            ),
            evaluation_latency_ms=latency_ms,
            isolated_event_count=len(journal.events()),
        )


def _local_foreground_act(route: str, focus: str) -> str:
    if focus == "AMBIGUOUS":
        return "CLARIFY"
    if route == "SPAWN_SLOW_TASK":
        return "ACK_SLOW"
    if route == "PATCH_ACTIVE_SLOW_TASK":
        return "ACK_PATCH"
    if route == "IGNORE":
        return "SILENCE"
    return "ANSWER"


def _complexity_for_router(value: str) -> str:
    return "complex" if value in {"MEDIUM", "HIGH"} else "low"


def _event_id(sequence: int, label: str) -> str:
    return f"evt_qfs_shadow_{sequence:04d}_{label}"


def _safe_token(value: object, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    token = "".join(char if char.isalnum() or char in "_-" else "_" for char in value)
    return token[:96].strip("_") or fallback


def _now_ms() -> tuple[int, int]:
    return int(time.monotonic() * 1_000), int(time.time() * 1_000)


__all__ = ["ShadowRouterEvaluation", "ShadowRouterEvaluator"]
