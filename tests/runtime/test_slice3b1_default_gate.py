from __future__ import annotations

from dataclasses import fields, replace
from importlib import import_module
from inspect import signature

import pytest

from qwen_slice3b1_support import gate_event_ids, parallel_gate_fixture
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateContext,
    FastForegroundGateError,
    run_fast_foreground_gate,
)
from voice_agent.runtime.slice3b1_release import (
    InMemoryPlaybackOutbox,
    ParallelForegroundGateContextV1,
    ParallelForegroundReleaseError,
    build_slice3b1_gate_context,
    run_parallel_fast_foreground_gate,
)


def _legacy_gate_context(*, capability_output_mode: str = "real") -> FastForegroundGateContext:
    return FastForegroundGateContext(
        authority_mode="trusted_synthetic_eval",
        authority_binding_status="bound",
        interaction_state="TURN_COMMITTED",
        interaction_state_ref="interaction-state://synthetic/slice3b1/committed",
        task_focus="FOREGROUND_CHAT",
        task_focus_snapshot_ref="task-focus://synthetic/slice3b1/snapshot",
        has_active_slowtask=False,
        active_task_id=None,
        active_slowtask_lifecycle=None,
        pending_confirmation=False,
        pending_confirmation_id=None,
        pending_confirmation_scope=None,
        capability_snapshot_ref="capability://synthetic/slice3b1/legacy-gate",
        capability_health_status="ready",
        capability_output_mode=capability_output_mode,
        capability_verification_status="provider_free_verified",
        candidate_policy_decision=CandidatePolicyDecision.trusted_synthetic(),
        schema_valid=True,
        confidence_threshold=0.8,
    )


def _legacy_atomic_gate_fixture(
    *, topology: str | None
) -> tuple[
    InMemoryEventJournal,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    suffix = topology or "missing"
    journal = InMemoryEventJournal(
        session_id=f"sess_slice3b1_legacy_gate_{suffix}",
        conversation_id=f"conv_slice3b1_legacy_gate_{suffix}",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id=f"evt_{suffix}_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1_700_000_000_001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/slice3b1/legacy-gate",
        capability_snapshot_ref="capability://synthetic/slice3b1/legacy-gate",
    )
    turn_committed = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_{suffix}_turn_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1_700_000_000_010,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_slice3b1_legacy_gate_{suffix}",
        utterance_id=f"utterance_slice3b1_legacy_gate_{suffix}",
        audio_span_id=f"audio_slice3b1_legacy_gate_{suffix}",
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    output_fields: dict[str, object] = {
        "adapter_id": "mvp63_fast_interaction_runtime",
        "adapter_type": "fast_interaction",
        "adapter_request_id": f"adapter_request_{suffix}",
        "turn_id": str(turn_committed["turn_id"]),
        "utterance_id": str(turn_committed["utterance_id"]),
        "input_modality": "audio",
        "source_event_ids": (str(turn_committed["event_id"]),),
        "route_hint_ref": f"route-hint://synthetic/slice3b1/{suffix}",
        "route_prelude_ref": f"route-prelude://synthetic/slice3b1/{suffix}",
        "foreground_act": "ANSWER",
        "final_fast_evidence_ref": f"fast-evidence://synthetic/slice3b1/{suffix}",
        "schema_name": "voice_agent.fast_interaction.output.v1",
        "normalization_status": "normalized",
        "output_mode": "real",
        "input_mode": "audio_native",
        "fast_interaction_input_mode": "audio_native",
        "risk_tags": ("none",),
        "risk_class": "LOW",
        "confidence": 0.91,
    }
    if topology is not None:
        output_fields["fast_interaction_topology"] = topology
    output_event = journal.append(
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
        event_id=f"evt_{suffix}_fast_interaction_output",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1_700_000_000_020,
        trace_redaction_level="metadata_only",
        **output_fields,
    )
    candidate_fields: dict[str, object] = {
        "candidate_id": f"candidate_slice3b1_legacy_gate_{suffix}",
        "fast_interaction_output_event_id": str(output_event["event_id"]),
        "turn_id": str(turn_committed["turn_id"]),
        "utterance_id": str(turn_committed["utterance_id"]),
        "candidate_ref": f"candidate://synthetic/slice3b1/{suffix}",
        "candidate_status": "complete",
        "input_mode": "audio_native",
        "fast_interaction_input_mode": "audio_native",
        "source_event_ids": (str(output_event["event_id"]),),
        "risk_tags": ("none",),
        "confidence": 0.91,
    }
    if topology is not None:
        candidate_fields["fast_interaction_topology"] = topology
    candidate_event = journal.append(
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id=f"evt_{suffix}_foreground_candidate",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(output_event["event_id"]),
        created_monotonic_ms=30,
        created_wall_clock_ms=1_700_000_000_030,
        trace_redaction_level="metadata_only",
        **candidate_fields,
    )
    router_event = journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id=f"evt_{suffix}_router_decision",
        source_module="router",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=40,
        created_wall_clock_ms=1_700_000_000_040,
        trace_redaction_level="metadata_only",
        turn_id=str(turn_committed["turn_id"]),
        utterance_id=str(turn_committed["utterance_id"]),
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
        confidence=0.91,
        evidence_uncertainty="low",
        fast_interaction_output_event_id=str(output_event["event_id"]),
    )
    return journal, candidate_event, output_event, router_event


@pytest.mark.parametrize("topology", (None, "atomic_single_call"))
def test_legacy_gate_preserves_atomic_topology_compatibility(
    topology: str | None,
) -> None:
    journal, candidate_event, output_event, router_event = (
        _legacy_atomic_gate_fixture(topology=topology)
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_legacy_gate_context(),
        event_id_prefix=f"evt_slice3b1_gate_atomic_{topology or 'missing'}",
        created_monotonic_ms=50,
        created_wall_clock_ms=1_700_000_000_050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_PASSED"
    assert result.committed_event is not None


def test_legacy_gate_rejects_parallel_topology_before_any_append() -> None:
    fixture = parallel_gate_fixture()
    before = fixture.journal.events()

    with pytest.raises(FastForegroundGateError, match="parallel"):
        run_fast_foreground_gate(
            fixture.journal,
            candidate_event=fixture.candidate_event,
            fast_interaction_output_event=fixture.fast_interaction_output_event,
            router_decision_event=fixture.router_decision_event,
            context=_legacy_gate_context(capability_output_mode="mock"),
            event_id_prefix="evt_slice3b1_gate_parallel_legacy_rejected",
            created_monotonic_ms=60,
            created_wall_clock_ms=1_700_000_000_060,
        )

    assert fixture.journal.events() == before


def test_slice3b1_default_gate_runtime_surface_exists() -> None:
    release = import_module("voice_agent.runtime.slice3b1_release")

    assert callable(release.build_slice3b1_gate_context)
    assert callable(release.run_parallel_fast_foreground_gate)
    assert callable(release.InMemoryPlaybackOutbox)


def _context(fixture):
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


def test_context_is_derived_from_validated_mock_assembly_and_candidate_facts() -> None:
    fixture = parallel_gate_fixture()

    context = _context(fixture)

    assert context.assembly_stage == "slice3b1_mock"
    assert context.output_mode == "mock"
    assert context.native_pcm_enabled is False
    assert context.native_pcm_capability_check == "FAIL"
    assert context.capability_snapshot_event_id == (
        fixture.capability_snapshot_event["event_id"]
    )
    assert context.capability_matrix_digest == (
        fixture.assembly_result.capability_snapshot[
            "capability_matrix_digest"
        ]
    )
    assert context.candidate_unicode_scalar_count == 20
    assert context.candidate_length_check == "PASS"
    assert context.candidate_duration_check == "PASS"
    assert context.candidate_terminal_check == "PASS"
    assert context.candidate_safety_decision == "SAFE"
    assert context.provider_context_state == "CLEAN"
    assert context.interaction_state == "TURN_COMMITTED"
    assert context.source_event_seq == fixture.candidate_event["event_seq"]
    assert "native_pcm_enabled" not in signature(
        build_slice3b1_gate_context
    ).parameters


def test_context_constructor_is_internal_only_and_context_is_immutable() -> None:
    context = _context(parallel_gate_fixture())
    direct_kwargs = {
        field.name: getattr(context, field.name)
        for field in fields(context)
        if field.init
    }

    with pytest.raises(TypeError, match="internal"):
        ParallelForegroundGateContextV1(**direct_kwargs)
    with pytest.raises(AttributeError):
        context.playback_epoch = 2  # type: ignore[misc]


@pytest.mark.parametrize("assembly_stage", ("slice3b1", "slice3b2_real", ""))
def test_context_rejects_non_mock_assembly_stage(assembly_stage: str) -> None:
    fixture = parallel_gate_fixture()

    with pytest.raises(ParallelForegroundReleaseError, match="assembly_stage"):
        build_slice3b1_gate_context(
            journal=fixture.journal,
            assembly_result=fixture.assembly_result,
            assembly_stage=assembly_stage,
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


def test_context_rejects_forged_snapshot_digest_and_mapping() -> None:
    fixture = parallel_gate_fixture()
    forged_snapshot = dict(
        fixture.capability_snapshot_event,
        capability_matrix_digest="sha256:" + "f" * 64,
    )

    with pytest.raises(ParallelForegroundReleaseError, match="snapshot"):
        build_slice3b1_gate_context(
            journal=fixture.journal,
            assembly_result=fixture.assembly_result,
            assembly_stage="slice3b1_mock",
            capability_snapshot_event=forged_snapshot,
            eligibility_facts=fixture.eligibility_facts,
            fast_interaction_output_event=fixture.fast_interaction_output_event,
            candidate_event=fixture.candidate_event,
            router_decision_event=fixture.router_decision_event,
            route_evidence_event=fixture.route_evidence_event,
            candidate_safety_event=fixture.candidate_safety_event,
            provider_context_state="CLEAN",
            interaction_state="TURN_COMMITTED",
        )


def test_context_rejects_recorded_snapshot_native_enable_claim() -> None:
    fixture = parallel_gate_fixture()
    journal = InMemoryEventJournal(
        session_id="sess_slice3b1_synthetic",
        conversation_id="conv_slice3b1_synthetic",
    )
    session = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_snapshot_extra_session",
        source_module="session_runtime",
        created_monotonic_ms=0,
        created_wall_clock_ms=1_700_000_000_000,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/slice3b1/snapshot-extra",
        capability_snapshot_ref=(
            fixture.assembly_result.capability_snapshot[
                "capability_snapshot_ref"
            ]
        ),
    )
    claimed = journal.append(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id="evt_snapshot_extra_claimed",
        source_module="adapter_registry",
        caused_by_event_id=str(session["event_id"]),
        created_monotonic_ms=1,
        created_wall_clock_ms=1_700_000_000_001,
        trace_redaction_level="metadata_only",
        **fixture.assembly_result.capability_snapshot,
        supports_provider_native_audio_release=True,
    )

    with pytest.raises(
        ParallelForegroundReleaseError,
        match="snapshot contains unsupported",
    ):
        build_slice3b1_gate_context(
            journal=journal,
            assembly_result=fixture.assembly_result,
            assembly_stage="slice3b1_mock",
            capability_snapshot_event=claimed,
            eligibility_facts=fixture.eligibility_facts,
            fast_interaction_output_event=fixture.fast_interaction_output_event,
            candidate_event=fixture.candidate_event,
            router_decision_event=fixture.router_decision_event,
            route_evidence_event=fixture.route_evidence_event,
            candidate_safety_event=fixture.candidate_safety_event,
            provider_context_state="CLEAN",
            interaction_state="TURN_COMMITTED",
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("supports_provider_native_audio_release", True),
        ("output_mode", "real"),
        ("deployment_mode", "real"),
        ("mocked", False),
    ),
)
def test_context_revalidates_exact_adapter_modes_and_native_release_claims(
    field_name: str,
    value: object,
) -> None:
    fixture = parallel_gate_fixture()
    capabilities = list(fixture.assembly_result.capabilities)
    capabilities[1 if field_name != "supports_provider_native_audio_release" else 0] = (
        replace(
            capabilities[
                1 if field_name != "supports_provider_native_audio_release" else 0
            ],
            **{field_name: value},
        )
    )
    forged_assembly = replace(
        fixture.assembly_result,
        capabilities=tuple(capabilities),
    )

    with pytest.raises(ParallelForegroundReleaseError, match="assembly"):
        build_slice3b1_gate_context(
            journal=fixture.journal,
            assembly_result=forged_assembly,
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


@pytest.mark.parametrize(
    "fixture_overrides",
    (
        {"fast_output_mode": "real"},
        {"route_output_mode": "real"},
        {"safety_output_mode": "real"},
        {"fast_route_adapter_request_id": "route_request_other"},
        {"fast_safety_adapter_request_id": "safety_request_other"},
        {"fast_risk_class": "HIGH"},
        {"fast_risk_tags": ("different",)},
    ),
)
def test_context_rejects_canonical_but_inconsistent_join_facts(
    fixture_overrides: dict[str, object],
) -> None:
    fixture = parallel_gate_fixture(**fixture_overrides)

    with pytest.raises(ParallelForegroundReleaseError, match="binding"):
        _context(fixture)


@pytest.mark.parametrize(
    "fixture_overrides",
    (
        {"candidate_safety_confidence": 0.2},
        {"candidate_safety_prohibited_flags": ("prohibited_claim",)},
    ),
)
def test_default_gate_fails_closed_on_non_authorizing_safety_evidence(
    fixture_overrides: dict[str, object],
) -> None:
    fixture = parallel_gate_fixture(**fixture_overrides)
    context = _context(fixture)

    result = run_parallel_fast_foreground_gate(
        journal=fixture.journal,
        candidate_event=fixture.candidate_event,
        fast_interaction_output_event=fixture.fast_interaction_output_event,
        router_decision_event=fixture.router_decision_event,
        route_evidence_event=fixture.route_evidence_event,
        candidate_safety_event=fixture.candidate_safety_event,
        context=context,
        outbox=InMemoryPlaybackOutbox(max_items=1),
        event_ids=gate_event_ids("unsafe_evidence"),
        created_monotonic_ms=100,
        created_wall_clock_ms=1_700_000_000_100,
    )

    assert context.candidate_safety_check == "FAIL"
    assert result.gate_event["failure_reason"] == (
        "candidate_safety_check_failed"
    )
    assert result.release_token is None


@pytest.mark.parametrize(
    ("fixture_overrides", "expected_reason"),
    (
        ({"candidate_unicode_scalar_count": 81}, "candidate_length_failed"),
        ({"candidate_audio_duration_ms": 2_001}, "candidate_duration_failed"),
        ({"candidate_status": "partial"}, "candidate_terminal_failed"),
    ),
)
def test_default_gate_fails_closed_on_candidate_eligibility_check(
    fixture_overrides: dict[str, object],
    expected_reason: str,
) -> None:
    fixture = parallel_gate_fixture(**fixture_overrides)
    context = _context(fixture)
    before = fixture.journal.events()

    result = run_parallel_fast_foreground_gate(
        journal=fixture.journal,
        candidate_event=fixture.candidate_event,
        fast_interaction_output_event=fixture.fast_interaction_output_event,
        router_decision_event=fixture.router_decision_event,
        route_evidence_event=fixture.route_evidence_event,
        candidate_safety_event=fixture.candidate_safety_event,
        context=context,
        outbox=InMemoryPlaybackOutbox(max_items=1),
        event_ids=gate_event_ids(expected_reason),
        created_monotonic_ms=100,
        created_wall_clock_ms=1_700_000_000_100,
    )

    assert result.gate_event["failure_reason"] == expected_reason
    assert result.release_token is None
    assert result.committed_event is None
    assert len(fixture.journal.events()) == len(before) + 2


@pytest.mark.parametrize(
    "fixture_overrides",
    (
        {"route_confidence": 0.79},
        {"route_evidence_uncertainty": "HIGH"},
    ),
)
def test_default_gate_requires_authorizing_route_evidence(
    fixture_overrides: dict[str, object],
) -> None:
    fixture = parallel_gate_fixture(**fixture_overrides)
    context = _context(fixture)

    result = run_parallel_fast_foreground_gate(
        journal=fixture.journal,
        candidate_event=fixture.candidate_event,
        fast_interaction_output_event=fixture.fast_interaction_output_event,
        router_decision_event=fixture.router_decision_event,
        route_evidence_event=fixture.route_evidence_event,
        candidate_safety_event=fixture.candidate_safety_event,
        context=context,
        outbox=InMemoryPlaybackOutbox(max_items=1),
        event_ids=gate_event_ids("route_not_authorizing"),
        created_monotonic_ms=100,
        created_wall_clock_ms=1_700_000_000_100,
    )

    assert context.route_evidence_check == "FAIL"
    assert result.gate_event["failure_reason"] == "route_evidence_check_failed"


@pytest.mark.parametrize(
    "fixture_overrides",
    (
        {"router_task_focus": "AMBIGUOUS"},
        {"router_turn_id": "turn_slice3b1_other"},
        {"router_utterance_id": "utterance_slice3b1_other"},
        {"candidate_risk_tags": ("different",)},
        {"candidate_confidence": 0.5},
        {"candidate_source_event_ids": ("evt_parallel_fast_output_synthetic",)},
    ),
)
def test_context_rejects_router_or_candidate_join_mismatch(
    fixture_overrides: dict[str, object],
) -> None:
    fixture = parallel_gate_fixture(**fixture_overrides)

    with pytest.raises(ParallelForegroundReleaseError, match="binding"):
        _context(fixture)


def test_context_rejects_unrecorded_shadow_verification_binding() -> None:
    fixture = parallel_gate_fixture()

    with pytest.raises(
        ParallelForegroundReleaseError,
        match="shadow verification",
    ):
        build_slice3b1_gate_context(
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
            candidate_audio_shadow_verification_event_id=(
                "evt_shadow_verification_missing"
            ),
        )


def test_slice3b1_default_gate_fails_without_token_commit_or_outbox() -> None:
    fixture = parallel_gate_fixture()
    outbox = InMemoryPlaybackOutbox(max_items=4)

    result = run_parallel_fast_foreground_gate(
        journal=fixture.journal,
        candidate_event=fixture.candidate_event,
        fast_interaction_output_event=fixture.fast_interaction_output_event,
        router_decision_event=fixture.router_decision_event,
        route_evidence_event=fixture.route_evidence_event,
        candidate_safety_event=fixture.candidate_safety_event,
        context=_context(fixture),
        outbox=outbox,
        event_ids=gate_event_ids("default_disabled"),
        created_monotonic_ms=100,
        created_wall_clock_ms=1_700_000_000_100,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == "native_pcm_disabled"
    assert result.release_token is None
    assert result.committed_event is None
    assert result.discarded_event is not None
    assert result.discarded_event["event_name"] == "FOREGROUND_OUTPUT_DISCARDED"
    assert result.discarded_event["discard_reason"] == "native_pcm_disabled"
    assert outbox.items() == ()
    assert [event["event_name"] for event in fixture.journal.events()][-2:] == [
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_DISCARDED",
    ]


def test_default_gate_rejects_forged_event_mapping_before_append() -> None:
    fixture = parallel_gate_fixture()
    before = fixture.journal.events()

    with pytest.raises(ParallelForegroundReleaseError, match="canonical"):
        run_parallel_fast_foreground_gate(
            journal=fixture.journal,
            candidate_event=dict(
                fixture.candidate_event,
                qwen_response_id="qwen_response_forged",
            ),
            fast_interaction_output_event=fixture.fast_interaction_output_event,
            router_decision_event=fixture.router_decision_event,
            route_evidence_event=fixture.route_evidence_event,
            candidate_safety_event=fixture.candidate_safety_event,
            context=_context(fixture),
            outbox=InMemoryPlaybackOutbox(max_items=4),
            event_ids=gate_event_ids("forged_mapping"),
            created_monotonic_ms=100,
            created_wall_clock_ms=1_700_000_000_100,
        )

    assert fixture.journal.events() == before


def test_default_gate_preflights_distinct_event_ids_before_atomic_append() -> None:
    fixture = parallel_gate_fixture()
    event_ids = gate_event_ids("duplicate_default_ids")
    event_ids["discard_event_id"] = event_ids["gate_event_id"]
    before = fixture.journal.events()

    with pytest.raises(ParallelForegroundReleaseError, match="distinct"):
        run_parallel_fast_foreground_gate(
            journal=fixture.journal,
            candidate_event=fixture.candidate_event,
            fast_interaction_output_event=fixture.fast_interaction_output_event,
            router_decision_event=fixture.router_decision_event,
            route_evidence_event=fixture.route_evidence_event,
            candidate_safety_event=fixture.candidate_safety_event,
            context=_context(fixture),
            outbox=InMemoryPlaybackOutbox(max_items=1),
            event_ids=event_ids,
            created_monotonic_ms=100,
            created_wall_clock_ms=1_700_000_000_100,
        )

    assert fixture.journal.events() == before
