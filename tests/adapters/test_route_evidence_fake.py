from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict, fields, replace
from typing import Iterator

import pytest

from voice_agent.adapters.qwen_realtime.ephemeral_text_store import (
    EphemeralTextRefV1,
    EphemeralTextStore,
    SensitiveTextLease,
    SensitiveTextLeaseError,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateTranscriptCompleteV1,
)
from voice_agent.adapters.route_evidence_contract import (
    CANDIDATE_SAFETY_SCHEMA_NAME,
    ROUTE_EVIDENCE_SCHEMA_NAME,
    CandidateSafetyEvidenceV1,
    CandidateSafetyRequestV1,
    RouteEvidenceAdapter,
    RouteEvidenceContractError,
    RouteEvidenceOutputV1,
    RouteEvidenceRequestV1,
    emit_candidate_safety_evidence_output_event,
    emit_route_evidence_output_event,
)
from voice_agent.adapters.route_evidence_fake import (
    CandidateSafetyFakeDirective,
    FakeRouteEvidenceAdapter,
    RouteEvidenceFakeDirective,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
)


ROUTE_REQUEST_FIELDS = (
    "adapter_request_id",
    "turn_id",
    "utterance_id",
    "final_asr_event_id",
    "transcript_ref",
    "asr_confidence",
    "duplex_hints_ref",
    "qwen_semantic_hints_ref",
    "context_projection_event_id",
    "context_snapshot_id",
    "active_task_public_snapshot_ref",
    "last_assistant_act",
    "expected_user_response",
    "policy_version",
)
CANDIDATE_REQUEST_FIELDS = (
    "adapter_request_id",
    "turn_id",
    "utterance_id",
    "qwen_response_id",
    "candidate_ref",
    "candidate_transcript_digest",
    "context_projection_event_id",
    "context_snapshot_id",
    "route_evidence_event_id",
    "task_focus_state_ref",
    "active_task_public_snapshot_ref",
    "policy_version",
)
RAW_OR_PROVIDER_FIELDS = frozenset(
    {
        "candidate_text",
        "candidate_pcm",
        "pcm",
        "raw_prompt",
        "provider_state",
        "provider_body",
        "tool_result",
        "private_reasoning",
    }
)


def _route_request(**overrides: object) -> RouteEvidenceRequestV1:
    values: dict[str, object] = {
        "adapter_request_id": "route_request_synthetic_001",
        "turn_id": "turn_synthetic_001",
        "utterance_id": "utterance_synthetic_001",
        "final_asr_event_id": "evt_final_asr_synthetic_001",
        "transcript_ref": "text-ref://synthetic/asr_001",
        "asr_confidence": 0.98,
        "duplex_hints_ref": "duplex-hints://synthetic/001",
        "qwen_semantic_hints_ref": "semantic-hints://synthetic/001",
        "context_projection_event_id": "evt_route_context_synthetic_001",
        "context_snapshot_id": "context_snapshot_synthetic_001",
        "active_task_public_snapshot_ref": None,
        "last_assistant_act": "ANSWER",
        "expected_user_response": "FREE_FORM",
        "policy_version": "route_evidence.fake.v1",
    }
    values.update(overrides)
    return RouteEvidenceRequestV1(**values)


def _candidate_request(
    metadata: EphemeralTextRefV1 | None = None,
    **overrides: object,
) -> CandidateSafetyRequestV1:
    values: dict[str, object] = {
        "adapter_request_id": "candidate_safety_request_synthetic_001",
        "turn_id": "turn_synthetic_001",
        "utterance_id": "utterance_synthetic_001",
        "qwen_response_id": "qwen_response_synthetic_001",
        "candidate_ref": (
            metadata.ref
            if metadata is not None
            else "candidate-ref://synthetic/candidate_001"
        ),
        "candidate_transcript_digest": (
            metadata.digest if metadata is not None else "0" * 64
        ),
        "context_projection_event_id": "evt_safety_context_synthetic_001",
        "context_snapshot_id": "context_snapshot_synthetic_001",
        "route_evidence_event_id": None,
        "task_focus_state_ref": "task-focus://synthetic/001",
        "active_task_public_snapshot_ref": None,
        "policy_version": "candidate_safety.fake.v1",
    }
    values.update(overrides)
    return CandidateSafetyRequestV1(**values)


def _put_asr(
    store: EphemeralTextStore,
    *,
    text: str = "请帮我简单解释一下这个概念",
    ref: str = "text-ref://synthetic/asr_001",
    max_unicode_scalars: int = 2_000,
) -> EphemeralTextRefV1:
    return store.put(
        kind="asr",
        ref=ref,
        normalized_text=text,
        max_unicode_scalars=max_unicode_scalars,
    )


def _put_candidate(
    store: EphemeralTextStore,
    *,
    text: str = "当然，可以简单理解为一个低风险说明。",
    ref: str = "candidate-ref://synthetic/candidate_001",
) -> EphemeralTextRefV1:
    return store.put(
        kind="candidate",
        ref=ref,
        normalized_text=text,
        max_unicode_scalars=80,
    )


def _fake(
    store: EphemeralTextStore,
    *,
    route_text_refs: tuple[EphemeralTextRefV1, ...] = (),
    candidate_transcript_completions: tuple[
        CandidateTranscriptCompleteV1, ...
    ] = (),
    route_directive: RouteEvidenceFakeDirective = RouteEvidenceFakeDirective.FAST_ONLY,
    candidate_directive: CandidateSafetyFakeDirective = CandidateSafetyFakeDirective.SAFE,
) -> FakeRouteEvidenceAdapter:
    return FakeRouteEvidenceAdapter(
        text_store=store,
        route_text_refs=route_text_refs,
        candidate_transcript_completions=candidate_transcript_completions,
        route_directive=route_directive,
        candidate_safety_directive=candidate_directive,
    )


def test_request_contracts_are_frozen_slot_only_and_exclude_raw_or_cross_role_data() -> None:
    assert tuple(field.name for field in fields(RouteEvidenceRequestV1)) == ROUTE_REQUEST_FIELDS
    assert (
        tuple(field.name for field in fields(CandidateSafetyRequestV1))
        == CANDIDATE_REQUEST_FIELDS
    )
    assert RAW_OR_PROVIDER_FIELDS.isdisjoint(ROUTE_REQUEST_FIELDS)
    assert RAW_OR_PROVIDER_FIELDS.isdisjoint(CANDIDATE_REQUEST_FIELDS)
    assert "candidate_ref" not in ROUTE_REQUEST_FIELDS

    route_request = _route_request()
    candidate_request = _candidate_request()
    assert not hasattr(route_request, "__dict__")
    assert not hasattr(candidate_request, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        route_request.turn_id = "changed"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        candidate_request.turn_id = "changed"  # type: ignore[misc]
    assert "candidate-ref://" not in repr(candidate_request)


@pytest.mark.parametrize(
    ("factory", "overrides", "error"),
    (
        (_route_request, {"transcript_ref": "https://provider.example/raw"}, "transcript_ref"),
        (_route_request, {"asr_confidence": True}, "asr_confidence"),
        (_route_request, {"asr_confidence": 1.01}, "asr_confidence"),
        (
            _route_request,
            {"active_task_public_snapshot_ref": "Bearer secret-value"},
            "active_task_public_snapshot_ref",
        ),
        (
            _candidate_request,
            {"candidate_transcript_digest": "not-a-digest"},
            "candidate_transcript_digest",
        ),
        (
            _candidate_request,
            {"task_focus_state_ref": "raw_prompt=override"},
            "task_focus_state_ref",
        ),
    ),
)
def test_request_contracts_reject_unsafe_or_malformed_values(
    factory: object,
    overrides: dict[str, object],
    error: str,
) -> None:
    with pytest.raises(RouteEvidenceContractError, match=error):
        factory(**overrides)  # type: ignore[operator]


def test_route_request_accepts_bounded_versioned_symbolic_context_values() -> None:
    request = _route_request(
        last_assistant_act="assistant_answer.v1",
        expected_user_response="free_form",
    )

    assert request.last_assistant_act == "assistant_answer.v1"
    assert request.expected_user_response == "free_form"


def test_output_contracts_are_strict_and_normalized() -> None:
    route = RouteEvidenceOutputV1(
        route_hint="FAST_ONLY",
        task_focus_hint="FOREGROUND_CHAT",
        foreground_act_hint="ANSWER",
        ack_kind="CHAT",
        risk_class="LOW",
        risk_tags=("low_risk",),
        evidence_uncertainty="LOW",
        confidence=0.98,
    )
    safety = CandidateSafetyEvidenceV1(
        decision="SAFE",
        semantic_categories=("general_assistance",),
        prohibited_flags=(),
        confidence=0.99,
        candidate_transcript_digest="1" * 64,
    )

    assert route.schema_name == ROUTE_EVIDENCE_SCHEMA_NAME
    assert route.normalization_status == "normalized"
    assert route.output_mode == "mock"
    assert safety.schema_name == CANDIDATE_SAFETY_SCHEMA_NAME
    assert safety.normalization_status == "normalized"
    assert safety.output_mode == "mock"
    with pytest.raises(TypeError):
        RouteEvidenceOutputV1(  # type: ignore[call-arg]
            route_hint="FAST_ONLY",
            task_focus_hint="FOREGROUND_CHAT",
            foreground_act_hint="ANSWER",
            ack_kind="CHAT",
            risk_class="LOW",
            risk_tags=(),
            evidence_uncertainty="LOW",
            confidence=0.98,
            raw_prompt="forbidden",
        )


@pytest.mark.parametrize(
    ("factory", "kwargs", "error"),
    (
        (
            RouteEvidenceOutputV1,
            {
                "route_hint": "UNKNOWN",
                "task_focus_hint": "FOREGROUND_CHAT",
                "foreground_act_hint": "ANSWER",
                "ack_kind": "CHAT",
                "risk_class": "LOW",
                "risk_tags": (),
                "evidence_uncertainty": "LOW",
                "confidence": 0.98,
            },
            "route_hint",
        ),
        (
            RouteEvidenceOutputV1,
            {
                "route_hint": "FAST_ONLY",
                "task_focus_hint": "FOREGROUND_CHAT",
                "foreground_act_hint": "ANSWER",
                "ack_kind": "CHAT",
                "risk_class": "LOW",
                "risk_tags": tuple(f"risk_{index}" for index in range(9)),
                "evidence_uncertainty": "LOW",
                "confidence": 0.98,
            },
            "risk_tags",
        ),
        (
            CandidateSafetyEvidenceV1,
            {
                "decision": "MAYBE",
                "semantic_categories": (),
                "prohibited_flags": (),
                "confidence": 0.99,
                "candidate_transcript_digest": "1" * 64,
            },
            "decision",
        ),
        (
            CandidateSafetyEvidenceV1,
            {
                "decision": "SAFE",
                "semantic_categories": tuple(
                    f"category_{index}" for index in range(9)
                ),
                "prohibited_flags": (),
                "confidence": 0.99,
                "candidate_transcript_digest": "1" * 64,
            },
            "semantic_categories",
        ),
    ),
)
def test_output_contracts_reject_unknown_enums_and_oversized_collections(
    factory: object,
    kwargs: dict[str, object],
    error: str,
) -> None:
    with pytest.raises(RouteEvidenceContractError, match=error):
        factory(**kwargs)  # type: ignore[operator]


def test_fake_classifies_route_without_receiving_or_retaining_candidate_text() -> None:
    store = EphemeralTextStore()
    metadata = _put_asr(store)
    adapter = _fake(store, route_text_refs=(metadata,))

    assert isinstance(adapter, RouteEvidenceAdapter)
    output = asyncio.run(adapter.classify_route(_route_request()))

    assert output.route_hint == "FAST_ONLY"
    assert output.task_focus_hint == "FOREGROUND_CHAT"
    assert output.foreground_act_hint == "ANSWER"
    assert output.confidence >= 0.8
    serialized = asdict(output)
    assert metadata.ref not in serialized.values()
    assert "请帮我简单解释一下这个概念" not in serialized.values()
    assert not any("candidate" in field.name for field in fields(RouteEvidenceOutputV1))


def test_fake_candidate_safety_resolves_only_complete_candidate_ref_and_digest() -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)
    adapter = _fake(
        store,
        candidate_transcript_completions=(_candidate_transcript(metadata),),
    )

    output = asyncio.run(adapter.classify_candidate_safety(_candidate_request(metadata)))

    assert output.decision == "SAFE"
    assert output.candidate_transcript_digest == metadata.digest
    serialized = asdict(output)
    assert metadata.ref not in serialized.values()
    assert "当然，可以简单理解为一个低风险说明。" not in serialized.values()


def test_candidate_safety_fails_closed_without_registered_transcript_completion() -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)

    output = asyncio.run(
        _fake(store).classify_candidate_safety(_candidate_request(metadata))
    )

    assert output.decision == "UNCERTAIN"
    assert output.confidence == 0.0
    assert "candidate_transcript_not_registered" in output.prohibited_flags


@pytest.mark.parametrize(
    ("mutation", "expected_flag"),
    (
        ({"turn_id": "turn_stale"}, "candidate_transcript_turn_id_mismatch"),
        (
            {"utterance_id": "utterance_stale"},
            "candidate_transcript_utterance_id_mismatch",
        ),
        (
            {"qwen_response_id": "response_stale"},
            "candidate_transcript_qwen_response_id_mismatch",
        ),
        (
            {"context_snapshot_id": "context_snapshot_stale"},
            "candidate_transcript_context_snapshot_id_mismatch",
        ),
        (
            {"candidate_transcript_digest": "f" * 64},
            "candidate_transcript_digest_mismatch",
        ),
        (
            {"candidate_unicode_scalar_count": 79},
            "candidate_transcript_scalar_count_mismatch",
        ),
        (
            {"candidate_unicode_scalar_count": 81},
            "candidate_transcript_scalar_count_over_bound",
        ),
        (
            {"candidate_ref": "candidate-ref://synthetic/other"},
            "candidate_transcript_not_registered",
        ),
    ),
)
def test_candidate_safety_rejects_mismatched_or_stale_registered_completion(
    mutation: dict[str, object],
    expected_flag: str,
) -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)
    completion = replace(_candidate_transcript(metadata), **mutation)

    output = asyncio.run(
        _fake(
            store,
            candidate_transcript_completions=(completion,),
        ).classify_candidate_safety(_candidate_request(metadata))
    )

    assert output.decision == "UNCERTAIN"
    assert output.confidence == 0.0
    assert expected_flag in output.prohibited_flags


@pytest.mark.parametrize(
    ("case", "expected_tag"),
    (
        ("missing", "text_ref_not_registered"),
        ("wrong_kind", "text_ref_kind_mismatch"),
        ("stale", "text_ref_not_found"),
        ("digest_mismatch", "text_ref_digest_mismatch"),
        ("over_bound", "text_ref_bounds_mismatch"),
        ("discarded", "text_ref_not_found"),
    ),
)
def test_route_ref_failures_return_typed_fail_closed_evidence(
    case: str,
    expected_tag: str,
) -> None:
    store = EphemeralTextStore()
    request = _route_request()
    metadata: EphemeralTextRefV1 | None = None

    if case == "missing":
        refs: tuple[EphemeralTextRefV1, ...] = ()
    elif case == "wrong_kind":
        metadata = _put_candidate(store)
        request = _route_request(transcript_ref=metadata.ref)
        refs = (metadata,)
    elif case in {"stale", "discarded"}:
        metadata = _put_asr(store)
        refs = (metadata,)
        store.discard(metadata.ref)
    elif case == "digest_mismatch":
        metadata = _put_asr(store)
        refs = (replace(metadata, digest="f" * 64),)
    elif case == "over_bound":
        metadata = _put_asr(
            store,
            text="字" * 2_001,
            max_unicode_scalars=2_001,
        )
        refs = (metadata,)
    else:  # pragma: no cover - table is closed above
        raise AssertionError(case)

    output = asyncio.run(_fake(store, route_text_refs=refs).classify_route(request))

    assert output.route_hint == "IGNORE"
    assert output.task_focus_hint == "AMBIGUOUS"
    assert output.foreground_act_hint == "CLARIFY"
    assert output.risk_class == "UNKNOWN"
    assert output.evidence_uncertainty == "HIGH"
    assert output.confidence == 0.0
    assert expected_tag in output.risk_tags


@pytest.mark.parametrize(
    ("case", "expected_flag"),
    (
        ("missing", "text_ref_not_found"),
        ("wrong_kind", "text_ref_kind_mismatch"),
        ("digest_mismatch", "text_ref_digest_mismatch"),
        ("discarded", "text_ref_not_found"),
    ),
)
def test_candidate_ref_failures_return_typed_uncertain_evidence(
    case: str,
    expected_flag: str,
) -> None:
    store = EphemeralTextStore()
    if case == "missing":
        request = _candidate_request()
        completion = _candidate_transcript(
            EphemeralTextRefV1(
                kind="candidate",
                ref=request.candidate_ref,
                digest=request.candidate_transcript_digest,
                unicode_scalar_count=1,
            )
        )
    elif case == "wrong_kind":
        metadata = _put_asr(store)
        request = _candidate_request(
            candidate_ref=metadata.ref,
            candidate_transcript_digest=metadata.digest,
        )
        completion = _candidate_transcript(metadata)
    else:
        metadata = _put_candidate(store)
        request = _candidate_request(metadata)
        completion = _candidate_transcript(metadata)
        if case == "digest_mismatch":
            request = replace(request, candidate_transcript_digest="f" * 64)
            completion = replace(
                completion,
                candidate_transcript_digest=request.candidate_transcript_digest,
            )
        else:
            store.discard(metadata.ref)

    output = asyncio.run(
        _fake(
            store,
            candidate_transcript_completions=(completion,),
        ).classify_candidate_safety(request)
    )

    assert output.decision == "UNCERTAIN"
    assert output.confidence == 0.0
    assert expected_flag in output.prohibited_flags
    assert output.candidate_transcript_digest == request.candidate_transcript_digest


class _RecordingTextStore(EphemeralTextStore):
    __slots__ = ("last_lease",)

    def __init__(self) -> None:
        super().__init__()
        self.last_lease: SensitiveTextLease | None = None

    @contextmanager
    def resolve(
        self,
        ref: str,
        *,
        expected_kind: str,
        expected_digest: str,
        max_unicode_scalars: int,
    ) -> Iterator[SensitiveTextLease]:
        with super().resolve(
            ref,
            expected_kind=expected_kind,  # type: ignore[arg-type]
            expected_digest=expected_digest,
            max_unicode_scalars=max_unicode_scalars,
        ) as lease:
            self.last_lease = lease
            yield lease


@pytest.mark.parametrize("operation", ("route", "candidate"))
def test_fake_never_retains_a_sensitive_text_lease_after_call(operation: str) -> None:
    store = _RecordingTextStore()
    if operation == "route":
        metadata = _put_asr(store)
        adapter = _fake(store, route_text_refs=(metadata,))
        asyncio.run(adapter.classify_route(_route_request()))
    else:
        metadata = _put_candidate(store)
        adapter = _fake(
            store,
            candidate_transcript_completions=(_candidate_transcript(metadata),),
        )
        asyncio.run(adapter.classify_candidate_safety(_candidate_request(metadata)))

    assert store.last_lease is not None
    with pytest.raises(SensitiveTextLeaseError, match="inactive"):
        _ = store.last_lease.text
    assert "SensitiveTextLease" not in repr(adapter)


@pytest.mark.parametrize(
    ("directive", "expected_route", "expected_focus"),
    (
        (RouteEvidenceFakeDirective.FAST_ONLY, "FAST_ONLY", "FOREGROUND_CHAT"),
        (
            RouteEvidenceFakeDirective.SPAWN_SLOW_TASK,
            "SPAWN_SLOW_TASK",
            "NEW_TASK_CANDIDATE",
        ),
        (
            RouteEvidenceFakeDirective.PATCH_ACTIVE_SLOW_TASK,
            "PATCH_ACTIVE_SLOW_TASK",
            "ACTIVE_TASK_PATCH",
        ),
        (RouteEvidenceFakeDirective.IGNORE, "IGNORE", "NON_ASSISTANT"),
        (
            RouteEvidenceFakeDirective.ACTIVE_TASK_CANCEL_OR_CONFIRMATION,
            "PATCH_ACTIVE_SLOW_TASK",
            "CANCEL_OR_PAUSE_CANDIDATE",
        ),
        (
            RouteEvidenceFakeDirective.ACTIVE_TASK_AMBIGUOUS,
            "IGNORE",
            "AMBIGUOUS",
        ),
    ),
)
def test_route_symbolic_directives_cover_authoritative_route_and_focus_evidence(
    directive: RouteEvidenceFakeDirective,
    expected_route: str,
    expected_focus: str,
) -> None:
    store = EphemeralTextStore()
    metadata = _put_asr(store)

    output = asyncio.run(
        _fake(
            store,
            route_text_refs=(metadata,),
            route_directive=directive,
        ).classify_route(_route_request())
    )

    assert output.route_hint == expected_route
    assert output.task_focus_hint == expected_focus


@pytest.mark.parametrize(
    "directive",
    (
        RouteEvidenceFakeDirective.TIMEOUT,
        RouteEvidenceFakeDirective.MALFORMED_JSON,
        RouteEvidenceFakeDirective.UNKNOWN_ENUM,
        RouteEvidenceFakeDirective.OVERSIZED_OUTPUT,
        RouteEvidenceFakeDirective.LOW_CONFIDENCE,
        RouteEvidenceFakeDirective.PROHIBITED_RISK,
    ),
)
def test_invalid_route_directives_normalize_to_typed_fail_closed_evidence(
    directive: RouteEvidenceFakeDirective,
) -> None:
    store = EphemeralTextStore()
    metadata = _put_asr(store)

    output = asyncio.run(
        _fake(
            store,
            route_text_refs=(metadata,),
            route_directive=directive,
        ).classify_route(_route_request())
    )

    assert output.route_hint == "IGNORE"
    assert output.task_focus_hint == "AMBIGUOUS"
    assert output.foreground_act_hint == "CLARIFY"
    assert output.confidence == 0.0
    assert output.risk_class in {"HIGH", "UNKNOWN"}
    assert output.risk_tags


@pytest.mark.parametrize(
    ("directive", "expected_decision"),
    (
        (CandidateSafetyFakeDirective.SAFE, "SAFE"),
        (CandidateSafetyFakeDirective.UNSAFE, "UNSAFE"),
        (CandidateSafetyFakeDirective.UNCERTAIN, "UNCERTAIN"),
        (CandidateSafetyFakeDirective.TIMEOUT, "UNCERTAIN"),
        (CandidateSafetyFakeDirective.MALFORMED_JSON, "UNCERTAIN"),
        (CandidateSafetyFakeDirective.UNKNOWN_ENUM, "UNCERTAIN"),
        (CandidateSafetyFakeDirective.OVERSIZED_OUTPUT, "UNCERTAIN"),
        (CandidateSafetyFakeDirective.LOW_CONFIDENCE, "UNCERTAIN"),
        (CandidateSafetyFakeDirective.PROHIBITED_RISK, "UNSAFE"),
    ),
)
def test_candidate_safety_symbolic_directives_fail_closed(
    directive: CandidateSafetyFakeDirective,
    expected_decision: str,
) -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)

    output = asyncio.run(
        _fake(
            store,
            candidate_transcript_completions=(_candidate_transcript(metadata),),
            candidate_directive=directive,
        ).classify_candidate_safety(_candidate_request(metadata))
    )

    assert output.decision == expected_decision
    if expected_decision != "SAFE":
        assert output.prohibited_flags or output.semantic_categories


def _journal_and_projection(
    *,
    target_role: str,
    event_id: str,
    context_snapshot_id: str = "context_snapshot_synthetic_001",
    provider_session_generation: int = 7,
    qwen_input_item_ref: str = "qwen-input-item://synthetic/001",
    final_asr_extra: dict[str, object] | None = None,
) -> tuple[InMemoryEventJournal, AdapterCallbackAppendBoundary, dict[str, object]]:
    journal = InMemoryEventJournal(
        session_id="session_synthetic_001",
        conversation_id="conversation_synthetic_001",
    )
    session = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_session_started_synthetic_001",
        source_module="session_runtime",
        created_monotonic_ms=0,
        created_wall_clock_ms=1_700_000_000_000,
        trace_redaction_level="metadata_only",
        runtime_config_ref="runtime-config://synthetic/001",
        capability_snapshot_ref="capability://synthetic/001",
    )
    committed = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_turn_committed_synthetic_001",
        source_module="interaction_controller",
        caused_by_event_id=str(session["event_id"]),
        created_monotonic_ms=1,
        created_wall_clock_ms=1_700_000_000_001,
        trace_redaction_level="metadata_only",
        turn_id="turn_synthetic_001",
        utterance_id="utterance_synthetic_001",
        audio_span_id="audio_span_synthetic_001",
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    final_asr = journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id="evt_final_asr_synthetic_001",
        source_module="qwen_realtime_asr_projection",
        caused_by_event_id=str(committed["event_id"]),
        created_monotonic_ms=2,
        created_wall_clock_ms=1_700_000_000_002,
        trace_redaction_level="metadata_only",
        adapter_id="slice3b1_qwen_realtime_asr_fake",
        adapter_type="asr",
        adapter_request_id="asr_request_synthetic_001",
        turn_id="turn_synthetic_001",
        utterance_id="utterance_synthetic_001",
        input_modality="audio",
        audio_span_id="audio_span_synthetic_001",
        asr_frame_ref="asr-frame://synthetic/001",
        text_ref="text-ref://synthetic/asr_001",
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
        provider_session_generation=provider_session_generation,
        qwen_input_item_ref=qwen_input_item_ref,
        qwen_input_content_index=0,
        **(final_asr_extra or {}),
    )
    projection = journal.append(
        event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        event_id=event_id,
        source_module="context_assembler",
        caused_by_event_id=str(final_asr["event_id"]),
        created_monotonic_ms=3,
        created_wall_clock_ms=1_700_000_000_003,
        trace_redaction_level="metadata_only",
        projection_id=f"projection_{target_role}_synthetic_001",
        target_role=target_role,
        source_event_ids=(str(final_asr["event_id"]),),
        context_snapshot_id=context_snapshot_id,
        source_event_seq=int(final_asr["event_seq"]),
        provider_session_generation=provider_session_generation,
        projection_ref=f"context-projection://synthetic/{target_role}/001",
        policy_version="context_projection.fake.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )
    return journal, AdapterCallbackAppendBoundary(journal), projection


def _final_asr_event(
    *,
    provider_session_generation: int = 7,
    canonical: bool = True,
    qwen_input_item_ref: str = "qwen-input-item://synthetic/001",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "event_id": "evt_final_asr_synthetic_001",
        "event_seq": 3,
        "event_schema_version": "1.0",
        "session_id": "session_synthetic_001",
        "conversation_id": "conversation_synthetic_001",
        "source_module": "qwen_realtime_asr_projection",
        "created_monotonic_ms": 2,
        "created_wall_clock_ms": 1_700_000_000_002,
        "caused_by_event_id": "evt_turn_committed_synthetic_001",
        "trace_redaction_level": "metadata_only",
        "adapter_id": "slice3b1_qwen_realtime_asr_fake",
        "adapter_type": "asr",
        "adapter_request_id": "asr_request_synthetic_001",
        "turn_id": "turn_synthetic_001",
        "utterance_id": "utterance_synthetic_001",
        "input_modality": "audio",
        "audio_span_id": "audio_span_synthetic_001",
        "asr_frame_ref": "asr-frame://synthetic/001",
        "text_ref": "text-ref://synthetic/asr_001",
        "transcript_finality": "final",
        "timestamp_status": "provider_correlated",
        "streaming_status": "complete",
        "provider_session_generation": provider_session_generation,
        "qwen_input_item_ref": qwen_input_item_ref,
        "qwen_input_content_index": 0,
        "output_mode": "mock",
    }
    if not canonical:
        event.pop("event_seq")
    event.update(extra or {})
    return event


def _candidate_transcript(
    metadata: EphemeralTextRefV1,
    *,
    provider_session_generation: int = 7,
) -> CandidateTranscriptCompleteV1:
    return CandidateTranscriptCompleteV1(
        provider_session_generation=provider_session_generation,
        qwen_response_id="qwen_response_synthetic_001",
        candidate_id="candidate_synthetic_001",
        turn_id="turn_synthetic_001",
        utterance_id="utterance_synthetic_001",
        context_snapshot_id="context_snapshot_synthetic_001",
        candidate_ref=metadata.ref,
        candidate_transcript_digest=metadata.digest,
        candidate_unicode_scalar_count=metadata.unicode_scalar_count,
    )


def test_route_evidence_event_uses_serialized_boundary_and_safe_context_binding() -> None:
    _, boundary, projection = _journal_and_projection(
        target_role="route_evidence",
        event_id="evt_route_context_synthetic_001",
    )
    output = RouteEvidenceOutputV1(
        route_hint="FAST_ONLY",
        task_focus_hint="FOREGROUND_CHAT",
        foreground_act_hint="ANSWER",
        ack_kind="CHAT",
        risk_class="LOW",
        risk_tags=("low_risk",),
        evidence_uncertainty="LOW",
        confidence=0.98,
    )

    event = emit_route_evidence_output_event(
        boundary=boundary,
        adapter_id="slice3b1_route_evidence_fake",
        request=_route_request(),
        output=output,
        final_asr_event=_final_asr_event(),
        context_projection_event=projection,
        event_id="evt_route_evidence_synthetic_001",
        created_monotonic_ms=2,
        created_wall_clock_ms=1_700_000_000_002,
    )

    assert event["event_name"] == "ROUTE_EVIDENCE_OUTPUT_EMITTED"
    assert event["adapter_callback_seq"] == 1
    assert event["caused_by_event_id"] == projection["event_id"]
    assert event["final_asr_event_id"] == "evt_final_asr_synthetic_001"
    assert event["context_snapshot_id"] == "context_snapshot_synthetic_001"
    assert event["provider_session_generation"] == 7
    for forbidden in (
        "transcript_ref",
        "candidate_ref",
        "duplex_hints_ref",
        "qwen_semantic_hints_ref",
        "raw_prompt",
        "resolved_text",
    ):
        assert forbidden not in event


def test_route_evidence_event_rejects_a_noncanonical_final_asr_mapping() -> None:
    _, boundary, projection = _journal_and_projection(
        target_role="route_evidence",
        event_id="evt_route_context_synthetic_001",
    )

    with pytest.raises(RouteEvidenceContractError, match="event_seq"):
        emit_route_evidence_output_event(
            boundary=boundary,
            adapter_id="slice3b1_route_evidence_fake",
            request=_route_request(),
            output=RouteEvidenceOutputV1.fail_closed("test"),
            final_asr_event=_final_asr_event(canonical=False),
            context_projection_event=projection,
            event_id="evt_route_evidence_synthetic_001",
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )


def test_route_evidence_event_accepts_a_safe_opaque_qwen_input_item_id() -> None:
    _, boundary, projection = _journal_and_projection(
        target_role="route_evidence",
        event_id="evt_route_context_synthetic_001",
        qwen_input_item_ref="input_item_1",
    )
    final_asr = _final_asr_event(qwen_input_item_ref="input_item_1")

    event = emit_route_evidence_output_event(
        boundary=boundary,
        adapter_id="slice3b1_route_evidence_fake",
        request=_route_request(),
        output=RouteEvidenceOutputV1.fail_closed("test"),
        final_asr_event=final_asr,
        context_projection_event=projection,
        event_id="evt_route_evidence_synthetic_001",
        created_monotonic_ms=4,
        created_wall_clock_ms=1_700_000_000_004,
    )

    assert event["provider_session_generation"] == 7
    assert "qwen_input_item_ref" not in event


def test_route_evidence_event_rejects_recorded_asr_content_fields() -> None:
    raw_field = {"redacted_text": "synthetic-redacted-body"}
    _, boundary, projection = _journal_and_projection(
        target_role="route_evidence",
        event_id="evt_route_context_synthetic_001",
        final_asr_extra=raw_field,
    )

    with pytest.raises(RouteEvidenceContractError, match="redacted_text"):
        emit_route_evidence_output_event(
            boundary=boundary,
            adapter_id="slice3b1_route_evidence_fake",
            request=_route_request(),
            output=RouteEvidenceOutputV1.fail_closed("test"),
            final_asr_event=_final_asr_event(extra=raw_field),
            context_projection_event=projection,
            event_id="evt_route_evidence_synthetic_001",
            created_monotonic_ms=4,
            created_wall_clock_ms=1_700_000_000_004,
        )


def test_candidate_safety_event_uses_serialized_boundary_and_safe_context_binding() -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)
    transcript = _candidate_transcript(metadata)
    _, boundary, projection = _journal_and_projection(
        target_role="candidate_safety",
        event_id="evt_safety_context_synthetic_001",
    )
    output = CandidateSafetyEvidenceV1(
        decision="SAFE",
        semantic_categories=("general_assistance",),
        prohibited_flags=(),
        confidence=0.99,
        candidate_transcript_digest=metadata.digest,
    )

    event = emit_candidate_safety_evidence_output_event(
        boundary=boundary,
        adapter_id="slice3b1_route_evidence_fake",
        request=_candidate_request(metadata),
        output=output,
        candidate_transcript=transcript,
        context_projection_event=projection,
        event_id="evt_candidate_safety_synthetic_001",
        created_monotonic_ms=2,
        created_wall_clock_ms=1_700_000_000_002,
    )

    assert event["event_name"] == "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED"
    assert event["adapter_callback_seq"] == 1
    assert event["caused_by_event_id"] == projection["event_id"]
    assert event["context_snapshot_id"] == "context_snapshot_synthetic_001"
    assert event["provider_session_generation"] == 7
    assert event["candidate_transcript_digest"] == metadata.digest
    for forbidden in (
        "candidate_ref",
        "task_focus_state_ref",
        "active_task_public_snapshot_ref",
        "raw_prompt",
        "resolved_text",
    ):
        assert forbidden not in event


def test_candidate_safety_event_rejects_an_unbound_optional_route_event() -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)
    _, boundary, projection = _journal_and_projection(
        target_role="candidate_safety",
        event_id="evt_safety_context_synthetic_001",
    )

    with pytest.raises(RouteEvidenceContractError, match="route_evidence_event_id"):
        emit_candidate_safety_evidence_output_event(
            boundary=boundary,
            adapter_id="slice3b1_route_evidence_fake",
            request=_candidate_request(
                metadata,
                route_evidence_event_id="evt_route_evidence_unbound",
            ),
            output=CandidateSafetyEvidenceV1.fail_closed(
                metadata.digest,
                "test",
            ),
            candidate_transcript=_candidate_transcript(metadata),
            context_projection_event=projection,
            event_id="evt_candidate_safety_synthetic_001",
            created_monotonic_ms=4,
            created_wall_clock_ms=1_700_000_000_004,
        )


@pytest.mark.parametrize(
    ("operation", "predecessor", "mutation"),
    (
        ("route", "final_asr", {"source_module": "forged_asr_source"}),
        ("route", "context", {"policy_version": "forged.context.v1"}),
        ("candidate", "context", {"policy_version": "forged.context.v1"}),
    ),
)
def test_evidence_emission_requires_exact_recorded_predecessors(
    operation: str,
    predecessor: str,
    mutation: dict[str, object],
) -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)
    target_role = "route_evidence" if operation == "route" else "candidate_safety"
    context_event_id = (
        "evt_route_context_synthetic_001"
        if operation == "route"
        else "evt_safety_context_synthetic_001"
    )
    _, boundary, projection = _journal_and_projection(
        target_role=target_role,
        event_id=context_event_id,
    )
    final_asr = _final_asr_event()
    if predecessor == "final_asr":
        final_asr = {**final_asr, **mutation}
    else:
        projection = {**projection, **mutation}

    with pytest.raises(RouteEvidenceContractError, match="recorded predecessor"):
        if operation == "route":
            emit_route_evidence_output_event(
                boundary=boundary,
                adapter_id="slice3b1_route_evidence_fake",
                request=_route_request(),
                output=RouteEvidenceOutputV1.fail_closed("test"),
                final_asr_event=final_asr,
                context_projection_event=projection,
                event_id="evt_route_evidence_synthetic_001",
                created_monotonic_ms=4,
                created_wall_clock_ms=1_700_000_000_004,
            )
        else:
            emit_candidate_safety_evidence_output_event(
                boundary=boundary,
                adapter_id="slice3b1_route_evidence_fake",
                request=_candidate_request(metadata),
                output=CandidateSafetyEvidenceV1.fail_closed(
                    metadata.digest,
                    "test",
                ),
                candidate_transcript=_candidate_transcript(metadata),
                context_projection_event=projection,
                event_id="evt_candidate_safety_synthetic_001",
                created_monotonic_ms=4,
                created_wall_clock_ms=1_700_000_000_004,
            )


@pytest.mark.parametrize(
    ("operation", "mutation", "error"),
    (
        ("route", {"target_role": "candidate_safety"}, "target_role"),
        (
            "route",
            {"context_snapshot_id": "context_snapshot_wrong"},
            "context_snapshot_id",
        ),
        ("route", {"provider_session_generation": 8}, "provider_session_generation"),
        ("candidate", {"target_role": "route_evidence"}, "target_role"),
        (
            "candidate",
            {"context_snapshot_id": "context_snapshot_wrong"},
            "context_snapshot_id",
        ),
        ("candidate", {"provider_session_generation": 8}, "provider_session_generation"),
    ),
)
def test_evidence_emission_rejects_context_or_generation_mismatch(
    operation: str,
    mutation: dict[str, object],
    error: str,
) -> None:
    store = EphemeralTextStore()
    metadata = _put_candidate(store)
    target_role = "route_evidence" if operation == "route" else "candidate_safety"
    context_event_id = (
        "evt_route_context_synthetic_001"
        if operation == "route"
        else "evt_safety_context_synthetic_001"
    )
    _, boundary, projection = _journal_and_projection(
        target_role=target_role,
        event_id=context_event_id,
    )
    mutated_projection = {**projection, **mutation}

    with pytest.raises(RouteEvidenceContractError, match=error):
        if operation == "route":
            emit_route_evidence_output_event(
                boundary=boundary,
                adapter_id="slice3b1_route_evidence_fake",
                request=_route_request(),
                output=RouteEvidenceOutputV1.fail_closed("test"),
                final_asr_event=_final_asr_event(),
                context_projection_event=mutated_projection,
                event_id="evt_route_evidence_synthetic_001",
                created_monotonic_ms=2,
                created_wall_clock_ms=1_700_000_000_002,
            )
        else:
            emit_candidate_safety_evidence_output_event(
                boundary=boundary,
                adapter_id="slice3b1_route_evidence_fake",
                request=_candidate_request(metadata),
                output=CandidateSafetyEvidenceV1.fail_closed(
                    metadata.digest,
                    "test",
                ),
                candidate_transcript=_candidate_transcript(metadata),
                context_projection_event=mutated_projection,
                event_id="evt_candidate_safety_synthetic_001",
                created_monotonic_ms=2,
                created_wall_clock_ms=1_700_000_000_002,
            )
