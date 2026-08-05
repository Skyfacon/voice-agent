from __future__ import annotations

from dataclasses import dataclass
import hashlib

from voice_agent.adapters.parallel_fast_interaction_profile import (
    build_parallel_fast_interaction_orchestrator_profile,
)
from voice_agent.adapters.qwen_realtime.profile import (
    build_qwen_realtime_asr_fake_profile,
    build_qwen_realtime_fake_profile,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateEligibilityFactsV1,
)
from voice_agent.adapters.route_evidence_profile import (
    build_route_evidence_fake_profile,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.assembly import (
    RuntimeAdapterAssemblyConfig,
    RuntimeAdapterAssemblyResult,
    assemble_runtime_adapters,
)
from voice_agent.runtime.session import start_configured_session


SYNTHETIC_RELEASE_TOKEN_REF = (
    "release-token://synthetic/release_token_0123456789abcdef0123456789abcdef"
)


def base_canonical_event(
    event_name: str,
    *,
    event_id: str,
    event_seq: int,
    caused_by_event_id: str | None,
    **fields: object,
) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": event_name,
        "event_id": event_id,
        "event_seq": event_seq,
        "event_schema_version": "1.0",
        "session_id": "sess_slice3b1_synthetic",
        "conversation_id": "conv_slice3b1_synthetic",
        "source_module": "slice3b1_test_support",
        "created_monotonic_ms": event_seq,
        "created_wall_clock_ms": 1_700_000_000_000 + event_seq,
        "trace_redaction_level": "metadata_only",
        **fields,
    }
    if caused_by_event_id is not None:
        event["caused_by_event_id"] = caused_by_event_id
    return event


def valid_adr018_event(event_name: str) -> dict[str, object]:
    fields_by_event: dict[str, dict[str, object]] = {
        "ROUTE_EVIDENCE_OUTPUT_EMITTED": {
            "adapter_id": "route_evidence_adapter_synthetic",
            "adapter_type": "route_evidence",
            "adapter_request_id": "route_request_synthetic_001",
            "turn_id": "turn_slice3b1_synthetic",
            "utterance_id": "utterance_slice3b1_synthetic",
            "final_asr_event_id": "evt_asr_final_synthetic",
            "context_projection_event_id": "evt_route_projection_synthetic",
            "route_hint": "FAST_ONLY",
            "task_focus_hint": "FOREGROUND_CHAT",
            "foreground_act_hint": "ANSWER",
            "ack_kind": "CHAT",
            "risk_class": "LOW",
            "risk_tags": (),
            "evidence_uncertainty": "LOW",
            "confidence": 0.98,
            "schema_name": "voice_agent.route_evidence.output.v1",
            "normalization_status": "normalized",
            "output_mode": "mock",
        },
        "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": {
            "adapter_id": "route_evidence_adapter_synthetic",
            "adapter_type": "route_evidence",
            "adapter_request_id": "candidate_safety_request_synthetic_001",
            "turn_id": "turn_slice3b1_synthetic",
            "utterance_id": "utterance_slice3b1_synthetic",
            "qwen_response_id": "qwen_response_synthetic_001",
            "candidate_transcript_digest": "sha256:" + "1" * 64,
            "context_projection_event_id": "evt_safety_projection_synthetic",
            "decision": "SAFE",
            "semantic_categories": ("general_assistance",),
            "prohibited_flags": (),
            "confidence": 0.99,
            "schema_name": "voice_agent.candidate_safety.output.v1",
            "normalization_status": "normalized",
            "output_mode": "mock",
        },
        "MODEL_CONTEXT_PROJECTION_EMITTED": {
            "projection_id": "projection_slice3b1_synthetic",
            "target_role": "route_evidence",
            "source_event_ids": ("evt_asr_final_synthetic",),
            "context_snapshot_id": "context_snapshot_synthetic_001",
            "source_event_seq": 2,
            "provider_session_generation": 1,
            "projection_ref": "context-projection://synthetic/route/001",
            "policy_version": "context_projection.synthetic.v1",
            "redaction_status": "metadata_only",
            "output_mode": "mock",
        },
        "SLOW_TO_FAST_HANDOFF_EMITTED": {
            "handoff_id": "handoff_synthetic_001",
            "kind": "PROGRESS",
            "delivery_mode": "CONTEXT_ONLY",
            "task_id": "task_slice3b1_synthetic",
            "plan_version": 1,
            "task_event_seq": 1,
            "source_event_ids": ("evt_slow_progress_synthetic",),
            "facts_ref": "handoff-facts://synthetic/001",
            "must_say_fields_ref": "must-say-fields://synthetic/001",
            "forbidden_claims_ref": "forbidden-claims://synthetic/001",
            "priority": 1,
            "expiry_status": "CURRENT",
            "redaction_status": "metadata_only",
        },
        "SLOW_TO_FAST_HANDOFF_DISPOSITIONED": {
            "handoff_id": "handoff_synthetic_001",
            "disposition": "QUEUED",
            "reason": "synthetic_queue",
        },
        "RESPONSE_ARBITRATION_DECIDED": {
            "arbitration_id": "arbitration_synthetic_001",
            "selected_source_type": "user_fast",
            "superseded_source_event_ids": (),
            "provider_session_generation": 1,
            "playback_epoch": 0,
            "interaction_state_version": 0,
            "decision_reason": "synthetic_user_fast_selected",
        },
        "PROVIDER_CONTEXT_STATE_CHANGED": {
            "adapter_id": "qwen_realtime_adapter_synthetic",
            "provider_session_generation": 1,
            "from_state": "CLEAN",
            "to_state": "CLEANUP_PENDING",
            "reason": "synthetic_cleanup",
            "source_event_ids": ("evt_cleanup_source_synthetic",),
            "output_mode": "mock",
        },
        "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": {
            "adapter_id": "shadow_asr_adapter_synthetic",
            "adapter_type": "asr",
            "adapter_request_id": "shadow_asr_request_synthetic_001",
            "turn_id": "turn_slice3b1_synthetic",
            "utterance_id": "utterance_slice3b1_synthetic",
            "qwen_response_id": "qwen_response_synthetic_001",
            "candidate_transcript_digest": "sha256:" + "1" * 64,
            "candidate_pcm_manifest_digest": "sha256:" + "2" * 64,
            "audio_format_ref": "audio-format://synthetic/pcm16-mono-24000",
            "decoded_duration_ms": 500,
            "independent_transcript_ref": "transcript://synthetic/shadow/001",
            "normalized_transcript_digest": "sha256:" + "1" * 64,
            "exact_numbers_entities_units_match": True,
            "equivalence": "MATCH",
            "output_mode": "mock",
        },
        "ASSISTANT_DELIVERY_DISPOSITIONED": {
            "assistant_item_ref": "assistant-item://synthetic/001",
            "source_output_event_id": "evt_foreground_output_synthetic",
            "from_status": "PENDING",
            "to_status": "NOT_STARTED",
            "delivery_offset_status": "NOT_APPLICABLE",
            "provider_item_cleanup_status": "NOT_REQUIRED",
            "source_event_ids": ("evt_arbitration_synthetic",),
        },
    }
    try:
        fields = fields_by_event[event_name]
    except KeyError as exc:
        raise ValueError(f"unsupported ADR-018 event: {event_name}") from exc
    return base_canonical_event(
        event_name,
        event_id=f"evt_{event_name.lower()}_synthetic",
        event_seq=3,
        caused_by_event_id="evt_slice3b1_cause_synthetic",
        **fields,
    )


def valid_asr_event(*, qwen_backed: bool = False) -> dict[str, object]:
    event = base_canonical_event(
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id="evt_asr_transcript_output_synthetic",
        event_seq=3,
        caused_by_event_id="evt_turn_ingress_committed_synthetic",
        adapter_id="asr_adapter_synthetic",
        adapter_type="asr",
        adapter_request_id="asr_request_synthetic_001",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        input_modality="audio",
        audio_span_id="audio_span_synthetic_001",
        asr_frame_ref="asr-frame://synthetic/001",
        text_ref="text://synthetic/asr/001",
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
    )
    if qwen_backed:
        event.update(
            provider_session_generation=1,
            qwen_input_item_ref="qwen-input-item://synthetic/001",
            qwen_input_content_index=0,
        )
    return event


def valid_legacy_candidate_event() -> dict[str, object]:
    return base_canonical_event(
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id="evt_legacy_candidate_synthetic",
        event_seq=5,
        caused_by_event_id="evt_legacy_fast_output_synthetic",
        candidate_id="candidate_legacy_synthetic",
        fast_interaction_output_event_id="evt_legacy_fast_output_synthetic",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        candidate_ref="candidate://synthetic/legacy/001",
        candidate_status="complete",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=("evt_turn_ingress_committed_synthetic",),
        risk_tags=("low_risk",),
        confidence=0.91,
    )


def valid_parallel_fast_event() -> dict[str, object]:
    return base_canonical_event(
        "FAST_INTERACTION_OUTPUT_EMITTED",
        event_id="evt_parallel_fast_output_synthetic",
        event_seq=4,
        caused_by_event_id="evt_turn_ingress_committed_synthetic",
        adapter_id="fast_orchestrator_synthetic",
        adapter_type="fast_interaction",
        adapter_request_id="fast_orchestration_synthetic_001",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        route_hint_ref="route-hint://synthetic/parallel/001",
        route_prelude_ref="route-prelude://synthetic/parallel/001",
        foreground_act="ANSWER",
        final_fast_evidence_ref="evidence://synthetic/parallel/final",
        schema_name="voice_agent.fast_interaction.output.v1",
        normalization_status="normalized",
        output_mode="mock",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=("evt_turn_ingress_committed_synthetic",),
        fast_interaction_topology="speculative_candidate_parallel_route",
        qwen_candidate_adapter_id="qwen_realtime_adapter_synthetic",
        qwen_candidate_adapter_request_id="qwen_candidate_request_synthetic_001",
        route_evidence_event_id="evt_route_evidence_synthetic",
        route_evidence_adapter_request_id="route_request_synthetic_001",
        candidate_safety_evidence_event_id="evt_candidate_safety_synthetic",
        candidate_safety_adapter_request_id="candidate_safety_request_synthetic_001",
        context_snapshot_id="context_snapshot_synthetic_001",
        provider_session_generation=1,
    )


def valid_parallel_candidate_event() -> dict[str, object]:
    event = valid_legacy_candidate_event()
    event.update(
        event_id="evt_parallel_candidate_synthetic",
        caused_by_event_id="evt_parallel_fast_output_synthetic",
        candidate_id="candidate_parallel_synthetic",
        fast_interaction_output_event_id="evt_parallel_fast_output_synthetic",
        candidate_ref="candidate://synthetic/parallel/001",
        fast_interaction_topology="speculative_candidate_parallel_route",
        qwen_response_id="qwen_response_synthetic_001",
        qwen_output_item_id="qwen_output_item_synthetic_001",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest="sha256:" + "1" * 64,
        candidate_pcm_manifest_digest="sha256:" + "2" * 64,
        candidate_audio_format_ref="audio-format://synthetic/pcm16-mono-24000",
        candidate_audio_duration_ms=500,
        provider_session_generation=1,
        context_snapshot_id="context_snapshot_synthetic_001",
    )
    return event


def parallel_journal() -> InMemoryEventJournal:
    journal = InMemoryEventJournal(
        session_id="sess_slice3b1_synthetic",
        conversation_id="conv_slice3b1_synthetic",
    )
    journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_slice3b1_session_started",
        source_module="session_runtime",
        created_monotonic_ms=0,
        created_wall_clock_ms=1_700_000_000_000,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/slice3b1",
        capability_snapshot_ref="capability://synthetic/slice3b1",
    )
    return journal


@dataclass(frozen=True, slots=True)
class ParallelGateFixture:
    journal: InMemoryEventJournal
    assembly_result: RuntimeAdapterAssemblyResult
    capability_snapshot_event: dict[str, object]
    eligibility_facts: CandidateEligibilityFactsV1
    fast_interaction_output_event: dict[str, object]
    candidate_event: dict[str, object]
    router_decision_event: dict[str, object]
    route_evidence_event: dict[str, object]
    candidate_safety_event: dict[str, object]


def slice3b1_assembly_result() -> RuntimeAdapterAssemblyResult:
    return assemble_runtime_adapters(
        RuntimeAdapterAssemblyConfig(
            stage="slice3b1_mock",
            capability_snapshot_ref=(
                "capability://synthetic/slice3b1/provider-free"
            ),
            capability_version="slice3b1.mock.v1",
        ),
        (
            build_qwen_realtime_fake_profile(),
            build_qwen_realtime_asr_fake_profile(),
            build_route_evidence_fake_profile(),
            build_parallel_fast_interaction_orchestrator_profile(),
        ),
    )


def parallel_gate_fixture(
    *,
    candidate_unicode_scalar_count: int = 20,
    candidate_audio_duration_ms: int = 500,
    provider_terminal_status: str = "completed",
    candidate_safety_decision: str = "SAFE",
    candidate_safety_confidence: float = 0.99,
    candidate_safety_prohibited_flags: tuple[str, ...] = (),
    candidate_safety_normalization_status: str = "normalized",
    route_confidence: float = 0.98,
    route_evidence_uncertainty: str = "LOW",
    router_task_focus: str = "FOREGROUND_CHAT",
    router_turn_id: str = "turn_slice3b1_synthetic",
    router_utterance_id: str = "utterance_slice3b1_synthetic",
    candidate_status: str = "complete",
    fast_output_mode: str = "mock",
    route_output_mode: str = "mock",
    safety_output_mode: str = "mock",
    fast_route_adapter_request_id: str = "route_request_synthetic_001",
    fast_safety_adapter_request_id: str = (
        "candidate_safety_request_synthetic_001"
    ),
    fast_risk_class: str = "LOW",
    fast_risk_tags: tuple[str, ...] = ("general_assistance",),
    candidate_risk_tags: tuple[str, ...] | None = None,
    candidate_confidence: float | None = None,
    candidate_source_event_ids: tuple[str, ...] | None = None,
) -> ParallelGateFixture:
    profiles = (
        build_qwen_realtime_fake_profile(),
        build_qwen_realtime_asr_fake_profile(),
        build_route_evidence_fake_profile(),
        build_parallel_fast_interaction_orchestrator_profile(),
    )
    assembly_config = RuntimeAdapterAssemblyConfig(
        stage="slice3b1_mock",
        capability_snapshot_ref=(
            "capability://synthetic/slice3b1/provider-free"
        ),
        capability_version="slice3b1.mock.v1",
    )
    assembly_result = assemble_runtime_adapters(assembly_config, profiles)
    startup = start_configured_session(
        session_id="sess_slice3b1_synthetic",
        conversation_id="conv_slice3b1_synthetic",
        runtime_config_ref="config://synthetic/slice3b1/provider-free",
        created_monotonic_ms=0,
        created_wall_clock_ms=1_700_000_000_000,
        assembly_config=assembly_config,
        capabilities=profiles,
    )
    journal = startup.journal
    capability_snapshot_event = journal.events()[1]
    session_started = journal.events()[0]
    turn = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_turn_ingress_committed_synthetic",
        source_module="interaction_controller",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1_700_000_000_010,
        trace_redaction_level="metadata_only",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        input_modality="audio",
        audio_span_id="audio_span_slice3b1_synthetic",
        directedness="assistant_directed",
        semantic_close=True,
        ingress_outcome="COMMITTED",
    )
    final_asr = journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id="evt_asr_final_synthetic",
        source_module="qwen_realtime_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1_700_000_000_020,
        trace_redaction_level="metadata_only",
        adapter_id="slice3b1_qwen_realtime_asr_projection",
        adapter_type="asr",
        adapter_request_id="qwen_asr_request_synthetic_001",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        input_modality="audio",
        audio_span_id="audio_span_slice3b1_synthetic",
        asr_frame_ref="asr-frame://synthetic/slice3b1/001",
        text_ref="text-ref://synthetic/slice3b1/asr-001",
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
        provider_session_generation=1,
        qwen_input_item_ref="qwen-input-item://synthetic/slice3b1/001",
        qwen_input_content_index=0,
    )
    route_projection = journal.append(
        event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        event_id="evt_route_projection_synthetic",
        source_module="context_assembler",
        caused_by_event_id=str(final_asr["event_id"]),
        created_monotonic_ms=30,
        created_wall_clock_ms=1_700_000_000_030,
        trace_redaction_level="metadata_only",
        projection_id="projection_route_synthetic_001",
        target_role="route_evidence",
        source_event_ids=(str(final_asr["event_id"]),),
        context_snapshot_id="context_snapshot_synthetic_001",
        source_event_seq=int(final_asr["event_seq"]),
        provider_session_generation=1,
        projection_ref="context-projection://synthetic/route/001",
        policy_version="slice3b1.context.route.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )
    route_evidence_event = journal.append(
        event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
        event_id="evt_route_evidence_synthetic",
        source_module="route_evidence_adapter",
        caused_by_event_id=str(route_projection["event_id"]),
        created_monotonic_ms=31,
        created_wall_clock_ms=1_700_000_000_031,
        trace_redaction_level="metadata_only",
        adapter_id="slice3b1_route_evidence_fake",
        adapter_type="route_evidence",
        adapter_request_id="route_request_synthetic_001",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        final_asr_event_id=str(final_asr["event_id"]),
        context_projection_event_id=str(route_projection["event_id"]),
        context_snapshot_id="context_snapshot_synthetic_001",
        provider_session_generation=1,
        route_hint="FAST_ONLY",
        task_focus_hint="FOREGROUND_CHAT",
        foreground_act_hint="ANSWER",
        ack_kind="CHAT",
        risk_class="LOW",
        risk_tags=("general_assistance",),
        evidence_uncertainty=route_evidence_uncertainty,
        confidence=route_confidence,
        schema_name="voice_agent.route_evidence.output.v1",
        normalization_status="normalized",
        output_mode=route_output_mode,
    )
    router_decision_event = journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id="evt_router_decision_synthetic",
        source_module="router",
        caused_by_event_id=str(route_evidence_event["event_id"]),
        created_monotonic_ms=32,
        created_wall_clock_ms=1_700_000_000_032,
        trace_redaction_level="metadata_only",
        turn_id=router_turn_id,
        utterance_id=router_utterance_id,
        router_decision="FAST_ONLY",
        task_focus=router_task_focus,
        confidence=route_confidence,
        evidence_uncertainty=route_evidence_uncertainty,
        turn_committed_event_id=str(turn["event_id"]),
        asr_frame_event_id=str(final_asr["event_id"]),
        route_evidence_event_id=str(route_evidence_event["event_id"]),
        evidence_ref_policy="route_evidence_only",
    )
    safety_projection = journal.append(
        event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        event_id="evt_safety_projection_synthetic",
        source_module="context_assembler",
        caused_by_event_id=str(route_evidence_event["event_id"]),
        created_monotonic_ms=40,
        created_wall_clock_ms=1_700_000_000_040,
        trace_redaction_level="metadata_only",
        projection_id="projection_safety_synthetic_001",
        target_role="candidate_safety",
        source_event_ids=(
            str(final_asr["event_id"]),
            str(route_evidence_event["event_id"]),
        ),
        context_snapshot_id="context_snapshot_synthetic_001",
        source_event_seq=int(route_evidence_event["event_seq"]),
        provider_session_generation=1,
        projection_ref="context-projection://synthetic/safety/001",
        policy_version="slice3b1.context.safety.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )
    candidate_safety_event = journal.append(
        event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        event_id="evt_candidate_safety_synthetic",
        source_module="route_evidence_adapter",
        caused_by_event_id=str(safety_projection["event_id"]),
        created_monotonic_ms=41,
        created_wall_clock_ms=1_700_000_000_041,
        trace_redaction_level="metadata_only",
        adapter_id="slice3b1_route_evidence_fake",
        adapter_type="route_evidence",
        adapter_request_id="candidate_safety_request_synthetic_001",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        qwen_response_id="qwen_response_synthetic_001",
        candidate_transcript_digest="sha256:" + "1" * 64,
        context_projection_event_id=str(safety_projection["event_id"]),
        context_snapshot_id="context_snapshot_synthetic_001",
        provider_session_generation=1,
        route_evidence_event_id=str(route_evidence_event["event_id"]),
        decision=candidate_safety_decision,
        semantic_categories=("general_assistance",),
        prohibited_flags=candidate_safety_prohibited_flags,
        confidence=candidate_safety_confidence,
        schema_name="voice_agent.candidate_safety.output.v1",
        normalization_status=candidate_safety_normalization_status,
        output_mode=safety_output_mode,
    )
    fast_interaction_output_event = journal.append(
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
        event_id="evt_parallel_fast_output_synthetic",
        source_module="slice3b1_parallel_fast_interaction_orchestrator",
        caused_by_event_id=str(candidate_safety_event["event_id"]),
        created_monotonic_ms=50,
        created_wall_clock_ms=1_700_000_000_050,
        trace_redaction_level="metadata_only",
        adapter_id="slice3b1_parallel_fast_interaction_orchestrator",
        adapter_type="fast_interaction",
        adapter_request_id="fast_orchestration_synthetic_001",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        route_hint_ref="route-hint://synthetic/parallel/001",
        route_prelude_ref="route-prelude://synthetic/parallel/001",
        foreground_act="ANSWER",
        final_fast_evidence_ref="evidence://synthetic/parallel/final",
        schema_name="voice_agent.fast_interaction.output.v1",
        normalization_status="normalized",
        output_mode=fast_output_mode,
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(
            str(final_asr["event_id"]),
            str(route_evidence_event["event_id"]),
            str(candidate_safety_event["event_id"]),
        ),
        risk_tags=fast_risk_tags,
        risk_class=fast_risk_class,
        confidence=min(route_confidence, candidate_safety_confidence),
        fast_interaction_topology="speculative_candidate_parallel_route",
        qwen_candidate_adapter_id="slice3b1_qwen_realtime_fake",
        qwen_candidate_adapter_request_id=(
            "qwen_candidate_request_synthetic_001"
        ),
        route_evidence_event_id=str(route_evidence_event["event_id"]),
        route_evidence_adapter_request_id=fast_route_adapter_request_id,
        candidate_safety_evidence_event_id=str(
            candidate_safety_event["event_id"]
        ),
        candidate_safety_adapter_request_id=fast_safety_adapter_request_id,
        context_snapshot_id="context_snapshot_synthetic_001",
        provider_session_generation=1,
    )
    candidate_event = journal.append(
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id="evt_parallel_candidate_synthetic",
        source_module="slice3b1_candidate_quarantine",
        caused_by_event_id=str(fast_interaction_output_event["event_id"]),
        created_monotonic_ms=51,
        created_wall_clock_ms=1_700_000_000_051,
        trace_redaction_level="metadata_only",
        candidate_id="candidate_parallel_synthetic",
        fast_interaction_output_event_id=str(
            fast_interaction_output_event["event_id"]
        ),
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        candidate_ref="candidate-ref://synthetic/slice3b1/001",
        candidate_status=candidate_status,
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(
            candidate_source_event_ids
            if candidate_source_event_ids is not None
            else (
                *fast_interaction_output_event["source_event_ids"],
                str(fast_interaction_output_event["event_id"]),
            )
        ),
        risk_tags=(
            fast_risk_tags
            if candidate_risk_tags is None
            else candidate_risk_tags
        ),
        confidence=(
            min(route_confidence, candidate_safety_confidence)
            if candidate_confidence is None
            else candidate_confidence
        ),
        fast_interaction_topology="speculative_candidate_parallel_route",
        qwen_response_id="qwen_response_synthetic_001",
        qwen_output_item_id="qwen_output_item_synthetic_001",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest="sha256:" + "1" * 64,
        candidate_pcm_manifest_digest="sha256:" + "2" * 64,
        candidate_audio_format_ref=(
            "audio-format://synthetic/pcm16-mono-24000"
        ),
        candidate_audio_duration_ms=candidate_audio_duration_ms,
        provider_session_generation=1,
        context_snapshot_id="context_snapshot_synthetic_001",
        route_evidence_event_id=str(route_evidence_event["event_id"]),
        candidate_safety_evidence_event_id=str(
            candidate_safety_event["event_id"]
        ),
    )
    eligibility_facts = CandidateEligibilityFactsV1(
        provider_session_generation=1,
        qwen_response_id="qwen_response_synthetic_001",
        qwen_output_item_id="qwen_output_item_synthetic_001",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_id="candidate_parallel_synthetic",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        context_snapshot_id="context_snapshot_synthetic_001",
        bound_playback_epoch=0,
        candidate_transcript_digest="sha256:" + "1" * 64,
        candidate_unicode_scalar_count=candidate_unicode_scalar_count,
        candidate_pcm_manifest_digest="sha256:" + "2" * 64,
        candidate_audio_format_ref=(
            "audio-format://synthetic/pcm16-mono-24000"
        ),
        candidate_audio_duration_ms=candidate_audio_duration_ms,
        provider_terminal_status=provider_terminal_status,  # type: ignore[arg-type]
    )
    return ParallelGateFixture(
        journal=journal,
        assembly_result=assembly_result,
        capability_snapshot_event=capability_snapshot_event,
        eligibility_facts=eligibility_facts,
        fast_interaction_output_event=fast_interaction_output_event,
        candidate_event=candidate_event,
        router_decision_event=router_decision_event,
        route_evidence_event=route_evidence_event,
        candidate_safety_event=candidate_safety_event,
    )


def valid_fast_router_event() -> dict[str, object]:
    return parallel_gate_fixture().router_decision_event


def valid_route_evidence_event() -> dict[str, object]:
    return parallel_gate_fixture().route_evidence_event


def valid_safe_candidate_evidence_event() -> dict[str, object]:
    return parallel_gate_fixture().candidate_safety_event


def valid_default_parallel_context():
    from voice_agent.runtime.slice3b1_release import (
        build_slice3b1_gate_context,
    )

    fixture = parallel_gate_fixture()
    return build_slice3b1_gate_context(
        journal=fixture.journal,
        assembly_result=fixture.assembly_result,
        assembly_stage="slice3b1_mock",
        capability_snapshot_event=fixture.capability_snapshot_event,
        eligibility_facts=fixture.eligibility_facts,
        fast_interaction_output_event=fixture.fast_interaction_output_event,
        candidate_event=fixture.candidate_event,
        router_decision_event=fixture.router_decision_event,
        route_evidence_event=fixture.route_evidence_event,
        candidate_safety_event=fixture.candidate_safety_event,
        provider_context_state="CLEAN",
        interaction_state="TURN_COMMITTED",
    )


def gate_event_ids(case_id: str) -> dict[str, str]:
    token_hex = hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:32]
    return {
        "gate_event_id": f"evt_slice3b1_gate_{case_id}",
        "gate_decision_id": f"gate_slice3b1_{case_id}",
        "discard_event_id": f"evt_slice3b1_discard_{case_id}",
        "discard_id": f"discard_slice3b1_{case_id}",
        "committed_event_id": f"evt_slice3b1_commit_{case_id}",
        "foreground_output_id": f"foreground_output_slice3b1_{case_id}",
        "release_token_id": f"release_token_{token_hex}",
    }
