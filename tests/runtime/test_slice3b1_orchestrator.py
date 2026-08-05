from __future__ import annotations

import asyncio
import json

import pytest

from qwen_slice3b1_support import parallel_journal
from voice_agent.adapters.qwen_realtime.ephemeral_text_store import (
    EphemeralTextStore,
)
from voice_agent.adapters.qwen_realtime.profile import (
    build_qwen_realtime_asr_fake_profile,
    build_qwen_realtime_fake_profile,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateCompletionV1,
    CandidateEligibilityFactsV1,
    CandidateTranscriptCompleteV1,
)
from voice_agent.adapters.parallel_fast_interaction_profile import (
    build_parallel_fast_interaction_orchestrator_profile,
)
from voice_agent.adapters.route_evidence_contract import (
    CandidateSafetyRequestV1,
    RouteEvidenceRequestV1,
    emit_candidate_safety_evidence_output_event,
    emit_route_evidence_output_event,
)
from voice_agent.adapters.route_evidence_fake import FakeRouteEvidenceAdapter
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
)
from voice_agent.runtime.slice3b1.context_projection import (
    ContextProjectionSourceAuthorityV1,
    ContextProjectionSourceV1,
    build_context_projection,
)
from voice_agent.runtime.slice3b1.orchestrator import (
    ParallelEmissionEventIds,
    ParallelFastInteractionOrchestrator,
    ParallelFastInteractionOrchestratorError,
)


TURN_ID = "turn_slice3b1_synthetic"
UTTERANCE_ID = "utterance_slice3b1_synthetic"
CONTEXT_SNAPSHOT_ID = "context_snapshot_slice3b1_001"
GENERATION = 1
RESPONSE_ID = "qwen_response_slice3b1_001"
ITEM_ID = "qwen_output_item_slice3b1_001"
TRANSCRIPT_DIGEST = "1" * 64
PCM_DIGEST = "2" * 64
CANDIDATE_REF = "candidate-ref://synthetic/slice3b1/candidate-001"


def test_join_emits_parallel_output_then_candidate_with_exact_safe_provenance() -> None:
    journal, final_asr, route, safety = _recorded_inputs(route_finishes_last=False)
    orchestrator = _orchestrator(journal)

    emission = orchestrator.emit(
        final_asr_event=final_asr,
        route_evidence_event=route,
        candidate_safety_event=safety,
        candidate=_candidate(),
        event_ids=_event_ids(),
        created_monotonic_ms=50,
        created_wall_clock_ms=1_700_000_000_050,
    )

    output = emission.fast_interaction_output_event
    candidate = emission.candidate_event
    profile = build_parallel_fast_interaction_orchestrator_profile()
    qwen_profile = build_qwen_realtime_fake_profile()

    assert output["event_name"] == "FAST_INTERACTION_OUTPUT_EMITTED"
    assert candidate["event_name"] == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
    assert output["event_seq"] + 1 == candidate["event_seq"]
    assert output["caused_by_event_id"] == safety["event_id"]
    assert candidate["caused_by_event_id"] == output["event_id"]
    assert output["adapter_id"] == profile.adapter_id
    assert output["adapter_request_id"] == "parallel_join_request_001"
    assert output["qwen_candidate_adapter_id"] == qwen_profile.adapter_id
    assert output["qwen_candidate_adapter_request_id"] == (
        "qwen_candidate_request_001"
    )
    assert output["route_evidence_event_id"] == route["event_id"]
    assert output["route_evidence_adapter_request_id"] == (
        route["adapter_request_id"]
    )
    assert output["candidate_safety_evidence_event_id"] == safety["event_id"]
    assert output["candidate_safety_adapter_request_id"] == (
        safety["adapter_request_id"]
    )
    assert output["fast_interaction_topology"] == (
        "speculative_candidate_parallel_route"
    )
    assert output["input_mode"] == "audio_native"
    assert output["foreground_act"] == route["foreground_act_hint"]
    assert output["risk_class"] == route["risk_class"]
    assert output["risk_tags"] == route["risk_tags"]
    assert output["confidence"] == min(route["confidence"], safety["confidence"])
    assert output["provider_session_generation"] == GENERATION
    assert output["context_snapshot_id"] == CONTEXT_SNAPSHOT_ID
    assert set(output["source_event_ids"]) == {
        final_asr["event_id"],
        route["event_id"],
        safety["event_id"],
    }

    facts = _candidate().eligibility_facts
    assert candidate["candidate_ref"] == CANDIDATE_REF
    assert candidate["candidate_id"] == facts.candidate_id
    assert candidate["qwen_response_id"] == RESPONSE_ID
    assert candidate["qwen_output_item_id"] == ITEM_ID
    assert candidate["qwen_output_index"] == 0
    assert candidate["qwen_content_index"] == 0
    assert candidate["candidate_transcript_digest"] == TRANSCRIPT_DIGEST
    assert candidate["candidate_pcm_manifest_digest"] == PCM_DIGEST
    assert candidate["candidate_audio_duration_ms"] == 500
    assert candidate["provider_session_generation"] == GENERATION
    assert candidate["context_snapshot_id"] == CONTEXT_SNAPSHOT_ID
    assert output["event_id"] in candidate["source_event_ids"]

    rendered = json.dumps(journal.events(), sort_keys=True)
    assert "candidate quick reply" not in rendered
    assert "raw_transcript" not in rendered
    assert "raw_prompt" not in rendered
    assert "provider_payload" not in rendered
    assert not any(
        event["event_name"].startswith("FOREGROUND_ACT_GATE_")
        or event["event_name"] == "ROUTER_DECISION_EMITTED"
        or event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
        for event in journal.events()
    )


@pytest.mark.parametrize("route_finishes_last", (False, True))
def test_join_uses_last_recorded_material_predecessor(
    route_finishes_last: bool,
) -> None:
    journal, final_asr, route, safety = _recorded_inputs(
        route_finishes_last=route_finishes_last
    )

    emission = _orchestrator(journal).emit(
        final_asr_event=final_asr,
        route_evidence_event=route,
        candidate_safety_event=safety,
        candidate=_candidate(),
        event_ids=_event_ids(),
        created_monotonic_ms=50,
        created_wall_clock_ms=1_700_000_000_050,
    )

    expected = max((route, safety), key=lambda event: int(event["event_seq"]))
    assert (
        emission.fast_interaction_output_event["caused_by_event_id"]
        == expected["event_id"]
    )


def test_join_accepts_canonical_qwen_opaque_input_item_token() -> None:
    journal, final_asr, route, safety = _recorded_inputs(
        route_finishes_last=False,
        qwen_input_item_ref="input_item_1",
    )

    emission = _orchestrator(journal).emit(
        final_asr_event=final_asr,
        route_evidence_event=route,
        candidate_safety_event=safety,
        candidate=_candidate(),
        event_ids=_event_ids(),
        created_monotonic_ms=50,
        created_wall_clock_ms=1_700_000_000_050,
    )

    assert emission.fast_interaction_output_event["event_name"] == (
        "FAST_INTERACTION_OUTPUT_EMITTED"
    )


@pytest.mark.parametrize("route_finishes_last", (False, True))
def test_actual_projection_fake_evidence_and_join_form_one_safe_chain(
    route_finishes_last: bool,
) -> None:
    (
        journal,
        boundary,
        final_asr,
        route,
        safety,
        candidate,
        store,
    ) = _actual_evidence_chain(route_finishes_last=route_finishes_last)
    try:
        emission = ParallelFastInteractionOrchestrator(
            boundary=boundary,
            adapter_request_id="parallel_join_actual_001",
            qwen_candidate_adapter_request_id="qwen_candidate_actual_001",
        ).emit(
            final_asr_event=final_asr,
            route_evidence_event=route,
            candidate_safety_event=safety,
            candidate=candidate,
            event_ids=ParallelEmissionEventIds(
                fast_interaction_output_event_id="evt_parallel_actual_output",
                candidate_event_id="evt_parallel_actual_candidate",
            ),
            created_monotonic_ms=80,
            created_wall_clock_ms=1_700_000_000_080,
        )
    finally:
        store.close()

    assert emission.fast_interaction_output_event["route_evidence_event_id"] == (
        route["event_id"]
    )
    assert emission.fast_interaction_output_event[
        "candidate_safety_evidence_event_id"
    ] == safety["event_id"]
    expected_cause = max(
        (route, safety),
        key=lambda event: int(event["event_seq"]),
    )
    assert emission.fast_interaction_output_event["caused_by_event_id"] == (
        expected_cause["event_id"]
    )
    serialized = json.dumps(journal.events(), sort_keys=True)
    assert "请解释这个概念" not in serialized
    assert "可以，先给你一个简短说明。" not in serialized
    assert "raw_prompt" not in serialized
    assert "provider_payload" not in serialized


def test_unsafe_candidate_evidence_remains_evidence_and_is_not_a_route_or_gate() -> None:
    journal, final_asr, route, safety = _recorded_inputs(
        route_finishes_last=False,
        safety_decision="UNSAFE",
        prohibited_flags=("unsupported_promise",),
    )

    emission = _orchestrator(journal).emit(
        final_asr_event=final_asr,
        route_evidence_event=route,
        candidate_safety_event=safety,
        candidate=_candidate(),
        event_ids=_event_ids(),
        created_monotonic_ms=50,
        created_wall_clock_ms=1_700_000_000_050,
    )

    assert emission.fast_interaction_output_event[
        "candidate_safety_evidence_event_id"
    ] == safety["event_id"]
    assert not any(
        event["event_name"]
        in {
            "ROUTER_DECISION_EMITTED",
            "FOREGROUND_ACT_GATE_PASSED",
            "FOREGROUND_ACT_GATE_FAILED",
            "FOREGROUND_OUTPUT_COMMITTED",
        }
        for event in journal.events()
    )


@pytest.mark.parametrize(
    ("target", "field", "forged", "expected"),
    (
        ("final_asr", "turn_id", "other_turn", "turn_id"),
        ("final_asr", "utterance_id", "other_utterance", "utterance_id"),
        ("final_asr", "provider_session_generation", 2, "generation"),
        ("route", "final_asr_event_id", "evt_other_asr", "final_asr_event_id"),
        ("route", "context_snapshot_id", "other_context", "context_snapshot"),
        ("route", "provider_session_generation", 2, "generation"),
        ("route", "normalization_status", "raw", "route_evidence_event"),
        ("safety", "qwen_response_id", "other_response", "qwen_response_id"),
        (
            "safety",
            "candidate_transcript_digest",
            "3" * 64,
            "transcript_digest",
        ),
        ("safety", "context_snapshot_id", "other_context", "context_snapshot"),
        ("safety", "provider_session_generation", 2, "generation"),
        (
            "safety",
            "route_evidence_event_id",
            "evt_other_route_evidence",
            "route_evidence_event_id",
        ),
        (
            "safety",
            "schema_name",
            "forged.schema.v1",
            "candidate_safety_event",
        ),
    ),
)
def test_join_fails_closed_on_cross_evidence_identity_mismatch(
    target: str,
    field: str,
    forged: object,
    expected: str,
) -> None:
    journal, final_asr, route, safety = _recorded_inputs(route_finishes_last=False)
    selected = {
        "final_asr": final_asr,
        "route": route,
        "safety": safety,
    }[target]
    selected[field] = forged
    before = journal.events()

    with pytest.raises(ParallelFastInteractionOrchestratorError, match=expected):
        _orchestrator(journal).emit(
            final_asr_event=final_asr,
            route_evidence_event=route,
            candidate_safety_event=safety,
            candidate=_candidate(),
            event_ids=_event_ids(),
            created_monotonic_ms=50,
            created_wall_clock_ms=1_700_000_000_050,
        )

    assert journal.events() == before


@pytest.mark.parametrize(
    ("candidate_overrides", "expected"),
    (
        (
            {"candidate_unicode_scalar_count": 81},
            "candidate_unicode_scalar_count",
        ),
        (
            {"candidate_audio_duration_ms": 2_001},
            "candidate_audio_duration_ms",
        ),
        (
            {"candidate_ref": "candidate://not-store-owned"},
            "candidate_ref",
        ),
    ),
)
def test_join_fails_closed_before_append_on_candidate_bounds_or_ref(
    candidate_overrides: dict[str, object],
    expected: str,
) -> None:
    journal, final_asr, route, safety = _recorded_inputs(route_finishes_last=False)
    before = journal.events()
    candidate = _candidate(**candidate_overrides)  # type: ignore[arg-type]

    with pytest.raises(ParallelFastInteractionOrchestratorError, match=expected):
        _orchestrator(journal).emit(
            final_asr_event=final_asr,
            route_evidence_event=route,
            candidate_safety_event=safety,
            candidate=candidate,
            event_ids=_event_ids(),
            created_monotonic_ms=50,
            created_wall_clock_ms=1_700_000_000_050,
        )

    assert journal.events() == before


@pytest.mark.parametrize(
    "candidate_audio_format_ref",
    (
        "http://example.invalid/pcm16-mono-24000",
        "https://example.invalid/pcm16-mono-24000",
        "file:///tmp/pcm16-mono-24000",
        "audio-format://synthetic/user:secret@example.invalid",
        "audio-format://provider/pcm16-mono-24000",
        "candidate-audio-format://synthetic/pcm16-mono-24000",
    ),
)
def test_join_rejects_noncanonical_candidate_audio_format_ref_before_append(
    candidate_audio_format_ref: str,
) -> None:
    journal, final_asr, route, safety = _recorded_inputs(route_finishes_last=False)
    before = journal.events()

    with pytest.raises(
        ParallelFastInteractionOrchestratorError,
        match="candidate_audio_format_ref",
    ):
        _orchestrator(journal).emit(
            final_asr_event=final_asr,
            route_evidence_event=route,
            candidate_safety_event=safety,
            candidate=_candidate(
                candidate_audio_format_ref=candidate_audio_format_ref,
            ),
            event_ids=_event_ids(),
            created_monotonic_ms=50,
            created_wall_clock_ms=1_700_000_000_050,
        )

    assert journal.events() == before


def test_join_requires_full_candidate_completion_not_transcript_only() -> None:
    journal, final_asr, route, safety = _recorded_inputs(route_finishes_last=False)
    transcript_only = CandidateTranscriptCompleteV1(
        provider_session_generation=GENERATION,
        qwen_response_id=RESPONSE_ID,
        candidate_id="candidate_slice3b1_001",
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        context_snapshot_id=CONTEXT_SNAPSHOT_ID,
        candidate_ref=CANDIDATE_REF,
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        candidate_unicode_scalar_count=20,
    )

    with pytest.raises(
        ParallelFastInteractionOrchestratorError,
        match="CandidateCompletionV1",
    ):
        _orchestrator(journal).emit(
            final_asr_event=final_asr,
            route_evidence_event=route,
            candidate_safety_event=safety,
            candidate=transcript_only,  # type: ignore[arg-type]
            event_ids=_event_ids(),
            created_monotonic_ms=50,
            created_wall_clock_ms=1_700_000_000_050,
        )


def test_duplicate_event_ids_fail_before_a_second_partial_chain() -> None:
    journal, final_asr, route, safety = _recorded_inputs(route_finishes_last=False)
    orchestrator = _orchestrator(journal)
    kwargs = {
        "final_asr_event": final_asr,
        "route_evidence_event": route,
        "candidate_safety_event": safety,
        "candidate": _candidate(),
        "event_ids": _event_ids(),
        "created_monotonic_ms": 50,
        "created_wall_clock_ms": 1_700_000_000_050,
    }
    orchestrator.emit(**kwargs)
    before = journal.events()

    with pytest.raises(ParallelFastInteractionOrchestratorError, match="Duplicate"):
        orchestrator.emit(**kwargs)

    assert journal.events() == before


@pytest.mark.parametrize("case", ("unrecorded_route", "forged_recorded_route"))
def test_join_requires_exact_evidence_already_recorded_in_same_boundary(
    case: str,
) -> None:
    journal, final_asr, route, safety = _recorded_inputs(route_finishes_last=False)
    if case == "unrecorded_route":
        safety.pop("route_evidence_event_id")
        route["event_id"] = "evt_route_evidence_unrecorded"
    else:
        route.update(
            route_hint="IGNORE",
            task_focus_hint="NON_ASSISTANT",
            foreground_act_hint="SILENCE",
            ack_kind="SILENCE",
        )
    before = journal.events()

    with pytest.raises(
        ParallelFastInteractionOrchestratorError,
        match="recorded",
    ):
        _orchestrator(journal).emit(
            final_asr_event=final_asr,
            route_evidence_event=route,
            candidate_safety_event=safety,
            candidate=_candidate(),
            event_ids=_event_ids(),
            created_monotonic_ms=50,
            created_wall_clock_ms=1_700_000_000_050,
        )

    assert journal.events() == before


def _orchestrator(journal: object) -> ParallelFastInteractionOrchestrator:
    return ParallelFastInteractionOrchestrator(
        boundary=AdapterCallbackAppendBoundary(journal),  # type: ignore[arg-type]
        adapter_request_id="parallel_join_request_001",
        qwen_candidate_adapter_request_id="qwen_candidate_request_001",
    )


def _event_ids() -> ParallelEmissionEventIds:
    return ParallelEmissionEventIds(
        fast_interaction_output_event_id="evt_parallel_fast_output_001",
        candidate_event_id="evt_parallel_candidate_001",
    )


def _candidate(
    *,
    candidate_ref: str = CANDIDATE_REF,
    candidate_unicode_scalar_count: int = 20,
    candidate_audio_format_ref: str = (
        "audio-format://synthetic/pcm16-mono-24000"
    ),
    candidate_audio_duration_ms: int = 500,
) -> CandidateCompletionV1:
    facts = CandidateEligibilityFactsV1(
        provider_session_generation=GENERATION,
        qwen_response_id=RESPONSE_ID,
        qwen_output_item_id=ITEM_ID,
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_id="candidate_slice3b1_001",
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        context_snapshot_id=CONTEXT_SNAPSHOT_ID,
        bound_playback_epoch=0,
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        candidate_unicode_scalar_count=candidate_unicode_scalar_count,
        candidate_pcm_manifest_digest=PCM_DIGEST,
        candidate_audio_format_ref=candidate_audio_format_ref,
        candidate_audio_duration_ms=candidate_audio_duration_ms,
        provider_terminal_status="completed",
    )
    return CandidateCompletionV1(
        candidate_ref=candidate_ref,
        eligibility_facts=facts,
    )


def _actual_evidence_chain(
    *,
    route_finishes_last: bool,
) -> tuple[
    object,
    AdapterCallbackAppendBoundary,
    dict[str, object],
    dict[str, object],
    dict[str, object],
    CandidateCompletionV1,
    EphemeralTextStore,
]:
    journal = parallel_journal()
    session_started = journal.events()[0]
    turn = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_actual_turn",
        source_module="interaction_controller",
        caused_by_event_id=session_started["event_id"],
        created_monotonic_ms=10,
        created_wall_clock_ms=1_700_000_000_010,
        trace_redaction_level="metadata_only",
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        input_modality="audio",
        audio_span_id="audio_span_actual_001",
        directedness="assistant_directed",
        semantic_close=True,
        ingress_outcome="COMMITTED",
    )
    store = EphemeralTextStore()
    asr_source_text = "请解释这个概念"
    asr_text = store.put(
        kind="asr",
        ref="text-ref://synthetic/slice3b1/actual-asr",
        normalized_text=asr_source_text,
        max_unicode_scalars=2_000,
    )
    candidate_text = store.put(
        kind="candidate",
        ref="candidate-ref://synthetic/slice3b1/actual-candidate",
        normalized_text="可以，先给你一个简短说明。",
        max_unicode_scalars=80,
    )
    asr_profile = build_qwen_realtime_asr_fake_profile()
    final_asr = journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id="evt_actual_asr",
        source_module="qwen_realtime_adapter",
        caused_by_event_id=turn["event_id"],
        created_monotonic_ms=20,
        created_wall_clock_ms=1_700_000_000_020,
        trace_redaction_level="metadata_only",
        adapter_id=asr_profile.adapter_id,
        adapter_type="asr",
        adapter_request_id="qwen_actual_asr_request",
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        input_modality="audio",
        audio_span_id="audio_span_actual_001",
        asr_frame_ref="asr-frame://synthetic/slice3b1/actual",
        text_ref=asr_text.ref,
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
        provider_session_generation=GENERATION,
        qwen_input_item_ref="input_item_actual_1",
        qwen_input_content_index=0,
    )
    candidate_transcript = CandidateTranscriptCompleteV1(
        provider_session_generation=GENERATION,
        qwen_response_id=RESPONSE_ID,
        candidate_id="candidate_slice3b1_actual",
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        context_snapshot_id=CONTEXT_SNAPSHOT_ID,
        candidate_ref=candidate_text.ref,
        candidate_transcript_digest=candidate_text.digest,
        candidate_unicode_scalar_count=candidate_text.unicode_scalar_count,
    )
    evidence_adapter = FakeRouteEvidenceAdapter(
        text_store=store,
        route_text_refs=(asr_text,),
        candidate_transcript_completions=(candidate_transcript,),
    )
    boundary = AdapterCallbackAppendBoundary(journal)
    source_authority = ContextProjectionSourceAuthorityV1(journal=journal)
    source_authority.register(
        kind="current_transcript",
        ref=asr_text.ref,
        normalized_text=asr_source_text,
        source_event_id=str(final_asr["event_id"]),
    )

    def projection(
        *,
        event_id: str,
        target_role: str,
        source_events: tuple[dict[str, object], ...],
        created: int,
    ) -> dict[str, object]:
        result = build_context_projection(
            journal=journal,
            event_id=event_id,
            source=ContextProjectionSourceV1(
                session_id="sess_slice3b1_synthetic",
                current_transcript_ref=asr_text.ref,
                current_transcript_char_count=asr_text.unicode_scalar_count,
                recent_committed_item_refs=(),
                recent_dialogue_summary_ref=None,
                recent_dialogue_summary_char_count=0,
                active_task_public_summary_ref=None,
                active_task_public_summary_char_count=0,
                session_memory_hint_refs=(),
                session_memory_hint_char_count=0,
                source_event_ids=tuple(
                    str(event["event_id"]) for event in source_events
                ),
                source_event_seq=int(source_events[-1]["event_seq"]),
                provider_session_generation=GENERATION,
                context_snapshot_id=CONTEXT_SNAPSHOT_ID,
                target_role=target_role,  # type: ignore[arg-type]
            ),
            source_authority=source_authority,
            created_monotonic_ms=created,
            created_wall_clock_ms=1_700_000_000_000 + created,
        )
        return dict(result.event)

    def emit_route(
        *,
        context: dict[str, object],
        created: int,
    ) -> dict[str, object]:
        request = RouteEvidenceRequestV1(
            adapter_request_id="route_actual_request",
            turn_id=TURN_ID,
            utterance_id=UTTERANCE_ID,
            final_asr_event_id=str(final_asr["event_id"]),
            transcript_ref=asr_text.ref,
            asr_confidence=0.98,
            duplex_hints_ref=None,
            qwen_semantic_hints_ref=None,
            context_projection_event_id=str(context["event_id"]),
            context_snapshot_id=CONTEXT_SNAPSHOT_ID,
            active_task_public_snapshot_ref=None,
            last_assistant_act="ANSWER",
            expected_user_response="FREE_FORM",
            policy_version="route_evidence.fake.v1",
        )
        output = asyncio.run(evidence_adapter.classify_route(request))
        return emit_route_evidence_output_event(
            boundary=boundary,
            adapter_id="slice3b1_route_evidence_fake",
            request=request,
            output=output,
            final_asr_event=final_asr,
            context_projection_event=context,
            event_id="evt_actual_route_evidence",
            created_monotonic_ms=created,
            created_wall_clock_ms=1_700_000_000_000 + created,
        )

    def emit_safety(
        *,
        context: dict[str, object],
        created: int,
        route_event: dict[str, object] | None,
    ) -> dict[str, object]:
        request = CandidateSafetyRequestV1(
            adapter_request_id="candidate_safety_actual_request",
            turn_id=TURN_ID,
            utterance_id=UTTERANCE_ID,
            qwen_response_id=RESPONSE_ID,
            candidate_ref=candidate_text.ref,
            candidate_transcript_digest=candidate_text.digest,
            context_projection_event_id=str(context["event_id"]),
            context_snapshot_id=CONTEXT_SNAPSHOT_ID,
            route_evidence_event_id=(
                str(route_event["event_id"])
                if route_event is not None
                else None
            ),
            task_focus_state_ref="task-focus://synthetic/actual",
            active_task_public_snapshot_ref=None,
            policy_version="candidate_safety.fake.v1",
        )
        output = asyncio.run(
            evidence_adapter.classify_candidate_safety(request)
        )
        return emit_candidate_safety_evidence_output_event(
            boundary=boundary,
            adapter_id="slice3b1_route_evidence_fake",
            request=request,
            output=output,
            candidate_transcript=candidate_transcript,
            context_projection_event=context,
            event_id="evt_actual_candidate_safety",
            created_monotonic_ms=created,
            created_wall_clock_ms=1_700_000_000_000 + created,
        )

    if route_finishes_last:
        route_context = projection(
            event_id="evt_actual_route_context",
            target_role="route_evidence",
            source_events=(final_asr,),
            created=30,
        )
        safety_context = projection(
            event_id="evt_actual_safety_context",
            target_role="candidate_safety",
            source_events=(final_asr, route_context),
            created=31,
        )
        safety = emit_safety(
            context=safety_context,
            created=32,
            route_event=None,
        )
        route = emit_route(context=route_context, created=40)
    else:
        route_context = projection(
            event_id="evt_actual_route_context",
            target_role="route_evidence",
            source_events=(final_asr,),
            created=30,
        )
        route = emit_route(context=route_context, created=31)
        safety_context = projection(
            event_id="evt_actual_safety_context",
            target_role="candidate_safety",
            source_events=(final_asr, route),
            created=40,
        )
        safety = emit_safety(
            context=safety_context,
            created=41,
            route_event=route,
        )

    facts = CandidateEligibilityFactsV1(
        provider_session_generation=GENERATION,
        qwen_response_id=RESPONSE_ID,
        qwen_output_item_id=ITEM_ID,
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_id=candidate_transcript.candidate_id,
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        context_snapshot_id=CONTEXT_SNAPSHOT_ID,
        bound_playback_epoch=0,
        candidate_transcript_digest=candidate_text.digest,
        candidate_unicode_scalar_count=candidate_text.unicode_scalar_count,
        candidate_pcm_manifest_digest=PCM_DIGEST,
        candidate_audio_format_ref="audio-format://synthetic/pcm16-mono-24000",
        candidate_audio_duration_ms=500,
        provider_terminal_status="completed",
    )
    candidate = CandidateCompletionV1(
        candidate_ref=candidate_text.ref,
        eligibility_facts=facts,
    )
    return journal, boundary, final_asr, route, safety, candidate, store


def _recorded_inputs(
    *,
    route_finishes_last: bool,
    safety_decision: str = "SAFE",
    prohibited_flags: tuple[str, ...] = (),
    qwen_input_item_ref: str = "qwen-input-item://synthetic/slice3b1/001",
) -> tuple[object, dict[str, object], dict[str, object], dict[str, object]]:
    journal = parallel_journal()
    session_started = journal.events()[0]
    turn = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_turn_slice3b1_001",
        source_module="interaction_controller",
        caused_by_event_id=session_started["event_id"],
        created_monotonic_ms=10,
        created_wall_clock_ms=1_700_000_000_010,
        trace_redaction_level="metadata_only",
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        input_modality="audio",
        audio_span_id="audio_span_slice3b1_001",
        directedness="assistant_directed",
        semantic_close=True,
        ingress_outcome="COMMITTED",
    )
    asr_profile = build_qwen_realtime_asr_fake_profile()
    final_asr = journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id="evt_asr_slice3b1_001",
        source_module="qwen_realtime_adapter",
        caused_by_event_id=turn["event_id"],
        created_monotonic_ms=20,
        created_wall_clock_ms=1_700_000_000_020,
        trace_redaction_level="metadata_only",
        adapter_id=asr_profile.adapter_id,
        adapter_type="asr",
        adapter_request_id="qwen_asr_request_001",
        turn_id=TURN_ID,
        utterance_id=UTTERANCE_ID,
        input_modality="audio",
        audio_span_id="audio_span_slice3b1_001",
        asr_frame_ref="asr-frame://synthetic/slice3b1/001",
        text_ref="text-ref://synthetic/slice3b1/asr-001",
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
        provider_session_generation=GENERATION,
        qwen_input_item_ref=qwen_input_item_ref,
        qwen_input_content_index=0,
    )

    def append_projection(
        *,
        event_id: str,
        role: str,
        created: int,
    ) -> dict[str, object]:
        return journal.append(
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
            event_id=event_id,
            source_module="context_assembler",
            caused_by_event_id=final_asr["event_id"],
            created_monotonic_ms=created,
            created_wall_clock_ms=1_700_000_000_000 + created,
            trace_redaction_level="metadata_only",
            projection_id=f"projection_{role}_001",
            target_role=role,
            source_event_ids=(final_asr["event_id"],),
            context_snapshot_id=CONTEXT_SNAPSHOT_ID,
            source_event_seq=final_asr["event_seq"],
            provider_session_generation=GENERATION,
            projection_ref=f"context-projection://synthetic/{role}/001",
            policy_version="slice3b1.context.route.v1",
            redaction_status="metadata_only",
            output_mode="mock",
        )

    def append_route(created: int) -> dict[str, object]:
        projection = append_projection(
            event_id="evt_route_projection_001",
            role="route_evidence",
            created=created,
        )
        return journal.append(
            event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
            event_id="evt_route_evidence_001",
            source_module="route_evidence_adapter",
            caused_by_event_id=projection["event_id"],
            created_monotonic_ms=created + 1,
            created_wall_clock_ms=1_700_000_000_001 + created,
            trace_redaction_level="metadata_only",
            adapter_id="slice3b1_route_evidence_fake",
            adapter_type="route_evidence",
            adapter_request_id="route_request_001",
            turn_id=TURN_ID,
            utterance_id=UTTERANCE_ID,
            final_asr_event_id=final_asr["event_id"],
            context_projection_event_id=projection["event_id"],
            context_snapshot_id=CONTEXT_SNAPSHOT_ID,
            provider_session_generation=GENERATION,
            route_hint="FAST_ONLY",
            task_focus_hint="FOREGROUND_CHAT",
            foreground_act_hint="ANSWER",
            ack_kind="CHAT",
            risk_class="LOW",
            risk_tags=("general_assistance",),
            evidence_uncertainty="LOW",
            confidence=0.96,
            schema_name="voice_agent.route_evidence.output.v1",
            normalization_status="normalized",
            output_mode="mock",
        )

    def append_safety(
        created: int,
        *,
        route_evidence_event_id: str | None = None,
    ) -> dict[str, object]:
        projection = append_projection(
            event_id="evt_safety_projection_001",
            role="candidate_safety",
            created=created,
        )
        optional_fields: dict[str, object] = {}
        if route_evidence_event_id is not None:
            optional_fields["route_evidence_event_id"] = (
                route_evidence_event_id
            )
        return journal.append(
            event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
            event_id="evt_candidate_safety_001",
            source_module="route_evidence_adapter",
            caused_by_event_id=projection["event_id"],
            created_monotonic_ms=created + 1,
            created_wall_clock_ms=1_700_000_000_001 + created,
            trace_redaction_level="metadata_only",
            adapter_id="slice3b1_route_evidence_fake",
            adapter_type="route_evidence",
            adapter_request_id="candidate_safety_request_001",
            turn_id=TURN_ID,
            utterance_id=UTTERANCE_ID,
            qwen_response_id=RESPONSE_ID,
            candidate_transcript_digest=TRANSCRIPT_DIGEST,
            context_projection_event_id=projection["event_id"],
            context_snapshot_id=CONTEXT_SNAPSHOT_ID,
            provider_session_generation=GENERATION,
            decision=safety_decision,
            semantic_categories=("general_assistance",),
            prohibited_flags=prohibited_flags,
            confidence=0.94,
            schema_name="voice_agent.candidate_safety.output.v1",
            normalization_status="normalized",
            output_mode="mock",
            **optional_fields,
        )

    if route_finishes_last:
        safety = append_safety(30)
        route = append_route(40)
    else:
        route = append_route(30)
        safety = append_safety(
            40,
            route_evidence_event_id=str(route["event_id"]),
        )
    return journal, final_asr, route, safety
