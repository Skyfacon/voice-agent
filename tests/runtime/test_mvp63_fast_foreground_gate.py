from __future__ import annotations

import pytest

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateConfig,
    FastForegroundGateContext,
    FastForegroundGateError,
    run_fast_foreground_gate,
)
from voice_agent.runtime.foreground_template_catalog import (
    FOREGROUND_TEMPLATE_CATALOG_VERSION,
    get_foreground_template,
    resolve_foreground_template,
)


def test_gate_passes_only_fast_only_answer_low_risk_candidate() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(task_focus=str(router_event["task_focus"])),
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix="evt_mvp63_gate_pass",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_PASSED"
    assert result.gate_event["pass_reason"] == "fast_only_answer_low_risk_confident"
    assert result.committed_event is not None
    assert result.committed_event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
    assert result.committed_event["output_basis"] == "reply_candidate"
    assert result.committed_event["output_ref"] == candidate_event["candidate_ref"]
    assert result.committed_event["gate_event_id"] == result.gate_event["event_id"]
    assert result.discarded_event is None
    assert [event["event_name"] for event in journal.events()][-2:] == [
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_OUTPUT_COMMITTED",
    ]


def test_gate_discards_spawn_slow_task_candidate_but_defers_success_ack() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="SPAWN_SLOW_TASK",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(task_focus=str(router_event["task_focus"])),
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix="evt_mvp63_gate_discard",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == "task_focus_not_foreground_chat"
    assert result.gate_event["downgrade_policy"] == "deferred_mutation_outcome"
    assert result.discarded_event is not None
    assert result.discarded_event["event_name"] == "FOREGROUND_OUTPUT_DISCARDED"
    assert result.discarded_event["discard_reason"] == "task_focus_not_foreground_chat"
    assert result.discarded_event["fast_interaction_output_event_id"] == output_event["event_id"]
    assert result.committed_event is None
    assert [event["event_name"] for event in journal.events()][-2:] == [
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_DISCARDED",
    ]


def test_gate_discards_ambiguous_candidate_and_commits_template_clarify() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        task_focus="AMBIGUOUS",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(task_focus=str(router_event["task_focus"])),
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix="evt_mvp63_gate_ambiguous",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert router_event["router_decision"] == "FAST_ONLY"
    assert router_event["task_focus"] == "AMBIGUOUS"
    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == "task_focus_ambiguous"
    assert result.gate_event["downgrade_policy"] == "template_clarify"
    assert result.discarded_event is not None
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] == "template_clarify"
    assert result.committed_event["fallback_policy_ref"].endswith(
        "/fast-only/template_clarify"
    )


def test_patch_candidate_discard_defers_commit_until_mutation_outcome() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="CANCEL_OR_PAUSE_CANDIDATE",
        foreground_act="CLARIFY",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(task_focus=str(router_event["task_focus"])),
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix="evt_mvp63_gate_patch_clarify",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == "task_focus_not_foreground_chat"
    assert result.gate_event["downgrade_policy"] == "deferred_mutation_outcome"
    assert result.gate_event["caused_by_event_id"] == router_event["event_id"]
    assert result.discarded_event is not None
    assert result.discarded_event["candidate_event_id"] == candidate_event["event_id"]
    assert result.discarded_event["caused_by_event_id"] == result.gate_event["event_id"]
    assert result.committed_event is None
    assert [event["event_name"] for event in journal.events()][-2:] == [
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_DISCARDED",
    ]


def test_patch_non_clarify_also_defers_success_ack() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="ACTIVE_TASK_PATCH",
        foreground_act="ACK_PATCH",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(task_focus=str(router_event["task_focus"])),
        event_id_prefix="evt_mvp63_gate_patch_ack",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["downgrade_policy"] == "deferred_mutation_outcome"
    assert result.discarded_event is not None
    assert result.committed_event is None


def test_gate_rejects_candidate_from_different_fast_output() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )
    mismatched_candidate = dict(
        candidate_event,
        fast_interaction_output_event_id="evt_mvp63_other_fast_output",
    )

    with pytest.raises(FastForegroundGateError, match="canonical journal payload"):
        run_fast_foreground_gate(
            journal,
            candidate_event=mismatched_candidate,
            fast_interaction_output_event=output_event,
            router_decision_event=router_event,
            context=_gate_context(task_focus=str(router_event["task_focus"])),
            config=FastForegroundGateConfig(confidence_threshold=0.8),
            event_id_prefix="evt_mvp63_gate_mismatch",
            created_monotonic_ms=50,
            created_wall_clock_ms=1700000000050,
        )


@pytest.mark.parametrize(
    ("foreground_act", "risk_class", "confidence", "expected_reason"),
    (
        ("ACK_SLOW", "LOW", 0.91, "foreground_act_not_answer"),
        ("ANSWER", "MEDIUM", 0.91, "risk_class_not_low"),
        ("ANSWER", "LOW", 0.42, "confidence_below_threshold"),
    ),
)
def test_gate_fails_candidate_policy_without_slowtask_or_patch_mutation(
    foreground_act: str,
    risk_class: str,
    confidence: float,
    expected_reason: str,
) -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act=foreground_act,
        risk_class=risk_class,
        confidence=confidence,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(task_focus=str(router_event["task_focus"])),
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix=f"evt_mvp63_gate_fail_{expected_reason}",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == expected_reason
    assert result.discarded_event is not None
    assert result.discarded_event["discard_reason"] == expected_reason
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] == "template_clarify"
    event_names = [event["event_name"] for event in journal.events()]
    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "SEMANTIC_COMMITMENT_EMITTED" not in event_names


@pytest.mark.parametrize(
    ("risk_class", "output_tags", "candidate_tags", "expected_reason"),
    (
        ("LOW", ("payment",), ("payment",), "risk_signal_conflict"),
        ("LOW", ("other",), ("other",), "risk_signal_conflict"),
        ("LOW", ("payment",), ("none",), "risk_signal_conflict"),
        ("MEDIUM", ("none",), ("none",), "risk_class_not_low"),
    ),
)
def test_gate_never_treats_low_class_with_risky_or_conflicting_tags_as_safe(
    risk_class: str,
    output_tags: tuple[str, ...],
    candidate_tags: tuple[str, ...],
    expected_reason: str,
) -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class=risk_class,
        confidence=0.95,
        output_risk_tags=output_tags,
        candidate_risk_tags=candidate_tags,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(),
        event_id_prefix=f"evt_mvp63_risk_{risk_class}_{expected_reason}_{len(output_tags)}",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == expected_reason
    assert result.discarded_event is not None
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] == "template_clarify"
    assert result.committed_event["output_ref"] != candidate_event["candidate_ref"]


def test_provider_low_risk_claims_never_self_verify_candidate() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.99,
        output_risk_tags=("none",),
        candidate_risk_tags=("none",),
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(
            authority_mode="live_runtime",
            candidate_policy_decision=CandidatePolicyDecision.quarantined_provider(),
            capability_verification_status="real_live_verified",
        ),
        event_id_prefix="evt_mvp63_provider_candidate_quarantined",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["failure_reason"] == "candidate_policy_quarantined"
    assert result.discarded_event is not None
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] == "template_clarify"
    assert result.committed_event["output_ref"] != candidate_event["candidate_ref"]


def test_missing_risk_tags_are_distinct_from_explicit_empty_tags() -> None:
    missing = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.95,
        output_risk_tags=(),
        candidate_risk_tags=(),
        output_risk_tags_present=False,
    )
    missing_result = run_fast_foreground_gate(
        missing[0],
        candidate_event=missing[1],
        fast_interaction_output_event=missing[2],
        router_decision_event=missing[3],
        context=_gate_context(),
        event_id_prefix="evt_mvp63_missing_risk_tags",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    explicit_empty = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.95,
        output_risk_tags=(),
        candidate_risk_tags=(),
    )
    empty_result = run_fast_foreground_gate(
        explicit_empty[0],
        candidate_event=explicit_empty[1],
        fast_interaction_output_event=explicit_empty[2],
        router_decision_event=explicit_empty[3],
        context=_gate_context(),
        event_id_prefix="evt_mvp63_explicit_empty_risk_tags",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert missing_result.gate_event["failure_reason"] == "risk_tags_missing"
    assert empty_result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_PASSED"


def test_active_slowtask_side_chat_requires_authoritative_foreground_focus() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.95,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(
            has_active_slowtask=True,
            active_task_id="task_mvp63_side_chat",
            active_slowtask_lifecycle="PLANNING",
        ),
        event_id_prefix="evt_mvp63_active_side_chat",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_PASSED"


@pytest.mark.parametrize(
    ("context_overrides", "expected_reason"),
    (
        (
            {
                "has_active_slowtask": True,
                "active_task_id": "task_mvp63_pending",
                "active_slowtask_lifecycle": "WAITING_FOR_USER_CONFIRMATION",
                "pending_confirmation": True,
                "pending_confirmation_id": "confirmation_mvp63_pending",
                "pending_confirmation_scope": "DEMO_DESTRUCTIVE_ACTION",
            },
            "pending_confirmation_active",
        ),
        (
            {
                "task_focus": "ACTIVE_TASK_PATCH",
                "has_active_slowtask": True,
                "active_task_id": "task_mvp63_patch",
                "active_slowtask_lifecycle": "PLANNING",
            },
            "task_focus_not_foreground_chat",
        ),
        ({"capability_health_status": "degraded"}, "capability_not_ready"),
        ({"capability_health_status": "unavailable"}, "capability_not_ready"),
        ({"capability_output_mode": "not_executed"}, "capability_not_ready"),
        (
            {"capability_verification_status": "unsupported_or_unverified"},
            "capability_not_ready",
        ),
        ({"schema_valid": False}, "capability_schema_invalid"),
        (
            {
                "candidate_policy_decision": (
                    CandidatePolicyDecision.quarantined_provider()
                )
            },
            "candidate_policy_quarantined",
        ),
        ({"interaction_state": "IDLE"}, "interaction_state_not_ready"),
        ({"interaction_state": "CORRUPTED_UNKNOWN_STATE"}, "interaction_state_unknown"),
        (
            {
                "has_active_slowtask": True,
                "active_task_id": "task_mvp63_invalid",
                "active_slowtask_lifecycle": "CORRUPTED_LIFECYCLE",
            },
            "active_slowtask_lifecycle_unknown",
        ),
    ),
)
def test_gate_typed_context_fails_closed_before_candidate_release(
    context_overrides: dict[str, object],
    expected_reason: str,
) -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        task_focus=str(context_overrides.get("task_focus", "FOREGROUND_CHAT")),
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.95,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(**context_overrides),  # type: ignore[arg-type]
        event_id_prefix=f"evt_mvp63_context_{expected_reason}_{len(journal.events())}",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == expected_reason
    assert result.discarded_event is not None
    assert result.discarded_event["candidate_event_id"] == candidate_event["event_id"]
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] != "reply_candidate"


def test_gate_rejects_mapping_that_differs_from_canonical_journal_payload() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.95,
    )
    forged_output = dict(output_event, confidence=0.99)

    with pytest.raises(FastForegroundGateError, match="canonical journal payload"):
        run_fast_foreground_gate(
            journal,
            candidate_event=candidate_event,
            fast_interaction_output_event=forged_output,
            router_decision_event=router_event,
            context=_gate_context(),
            event_id_prefix="evt_mvp63_mapping_forgery",
            created_monotonic_ms=50,
            created_wall_clock_ms=1700000000050,
        )


def test_exact_versioned_template_catalog_rejects_forged_refs_and_mismatches() -> None:
    ack = get_foreground_template(
        router_decision="SPAWN_SLOW_TASK",
        output_basis="template_ack",
    )
    clarify = get_foreground_template(
        router_decision="FAST_ONLY",
        output_basis="template_clarify",
    )

    assert ack.catalog_version == FOREGROUND_TEMPLATE_CATALOG_VERSION
    assert ack.foreground_act == "ACK_SLOW"
    assert clarify.foreground_act == "CLARIFY"
    assert resolve_foreground_template(
        output_ref=ack.template_ref,
        output_basis=ack.output_basis,
        fallback_policy_ref=ack.fallback_policy_ref,
        router_decision=ack.router_decision,
    ) == ack
    assert resolve_foreground_template(
        output_ref=f"{ack.template_ref}-forged",
        output_basis=ack.output_basis,
        fallback_policy_ref=ack.fallback_policy_ref,
        router_decision=ack.router_decision,
    ) is None
    assert resolve_foreground_template(
        output_ref=ack.template_ref,
        output_basis="template_clarify",
        fallback_policy_ref=ack.fallback_policy_ref,
        router_decision=ack.router_decision,
    ) is None


def test_forged_local_template_candidate_fails_closed_to_exact_clarify() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.95,
        candidate_ref="foreground-template://mvp6.3/v1/fast-only/forged",
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        context=_gate_context(
            authority_mode="live_runtime",
            candidate_policy_decision=CandidatePolicyDecision.trusted_local_template(),
        ),
        event_id_prefix="evt_mvp63_forged_local_template",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["failure_reason"] == "candidate_template_ref_invalid"
    assert result.committed_event is not None
    resolved = resolve_foreground_template(
        output_ref=result.committed_event["output_ref"],
        output_basis=result.committed_event["output_basis"],
        fallback_policy_ref=result.committed_event["fallback_policy_ref"],
        router_decision=router_event["router_decision"],
    )
    assert resolved is not None
    assert resolved.foreground_act == "CLARIFY"


def test_gate_context_and_candidate_policy_are_immutable_typed_objects() -> None:
    context = _gate_context()
    with pytest.raises(AttributeError):
        context.pending_confirmation = True  # type: ignore[misc]

    with pytest.raises(AttributeError):
        context.candidate_policy_decision.decision = "quarantine"  # type: ignore[misc]

    with pytest.raises(FastForegroundGateError, match="CandidatePolicyDecision"):
        _gate_context(candidate_policy_decision=True)  # type: ignore[arg-type]

    with pytest.raises(
        FastForegroundGateError,
        match="provider-generated candidates cannot",
    ):
        CandidatePolicyDecision(
            policy_version="unsafe-provider-self-verification.v1",
            decision="allow",
            reason_code="provider_claimed_low_risk",
            provenance="provider_generated",
        )


def _journal_with_fast_candidate(
    *,
    router_decision: str,
    foreground_act: str,
    risk_class: str,
    confidence: float,
    task_focus: str | None = None,
    output_risk_tags: tuple[str, ...] = ("none",),
    output_risk_tags_present: bool = True,
    candidate_risk_tags: tuple[str, ...] | None = None,
    candidate_ref: str | None = None,
) -> tuple[InMemoryEventJournal, dict[str, object], dict[str, object], dict[str, object]]:
    suffix = f"{router_decision}_{foreground_act}_{risk_class}_{int(confidence * 100)}".lower()
    journal = InMemoryEventJournal(
        session_id=f"sess_mvp63_fast_gate_{suffix}",
        conversation_id=f"conv_mvp63_fast_gate_{suffix}",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id=f"evt_{suffix}_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/mvp63/fast-gate",
        capability_snapshot_ref="capability://synthetic/mvp63/fast-gate",
    )
    turn_committed = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_{suffix}_turn_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000000010,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_mvp63_fast_gate_{suffix}",
        utterance_id=f"utt_mvp63_fast_gate_{suffix}",
        input_modality="audio",
        audio_span_id=f"audio_mvp63_fast_gate_{suffix}",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    output_fields: dict[str, object] = {
        "adapter_id": "mvp63_fast_interaction_runtime",
        "adapter_type": "fast_interaction",
        "adapter_request_id": f"adapter_request_mvp63_fast_gate_{suffix}",
        "turn_id": str(turn_committed["turn_id"]),
        "utterance_id": str(turn_committed["utterance_id"]),
        "input_modality": "audio",
        "source_event_ids": (str(turn_committed["event_id"]),),
        "route_hint_ref": f"route-hint://synthetic/mvp63/fast-gate/{suffix}",
        "route_prelude_ref": f"route-prelude://synthetic/mvp63/fast-gate/{suffix}",
        "foreground_act": foreground_act,
        "final_fast_evidence_ref": (
            f"fast-evidence://synthetic/mvp63/fast-gate/{suffix}"
        ),
        "schema_name": "voice_agent.fast_interaction.output.v1",
        "normalization_status": "normalized",
        "output_mode": "real",
        "input_mode": "audio_native",
        "fast_interaction_input_mode": "audio_native",
        "risk_class": risk_class,
        "confidence": confidence,
    }
    if output_risk_tags_present:
        output_fields["risk_tags"] = output_risk_tags
    output_event = journal.append(
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
        event_id=f"evt_{suffix}_fast_interaction_output",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000000020,
        trace_redaction_level="metadata_only",
        **output_fields,
    )
    candidate_fields: dict[str, object] = {
        "candidate_id": f"candidate_mvp63_fast_gate_{suffix}",
        "fast_interaction_output_event_id": str(output_event["event_id"]),
        "turn_id": str(turn_committed["turn_id"]),
        "utterance_id": str(turn_committed["utterance_id"]),
        "candidate_ref": (
            candidate_ref
            or f"foreground-candidate://synthetic/mvp63/fast-gate/{suffix}"
        ),
        "candidate_status": "complete",
        "input_mode": "audio_native",
        "fast_interaction_input_mode": "audio_native",
        "source_event_ids": (str(output_event["event_id"]),),
        "confidence": confidence,
    }
    candidate_fields["risk_tags"] = (
        output_risk_tags
        if candidate_risk_tags is None
        else candidate_risk_tags
    )
    candidate_event = journal.append(
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id=f"evt_{suffix}_foreground_candidate",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(output_event["event_id"]),
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        trace_redaction_level="metadata_only",
        **candidate_fields,
    )
    router_task_focus = (
        task_focus
        if task_focus is not None
        else "FOREGROUND_CHAT"
        if router_decision == "FAST_ONLY"
        else "AMBIGUOUS"
        if router_decision == "AMBIGUOUS"
        else "NEW_TASK_CANDIDATE"
    )
    router_event = journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id=f"evt_{suffix}_router_decision",
        source_module="router",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000000040,
        trace_redaction_level="metadata_only",
        turn_id=str(turn_committed["turn_id"]),
        utterance_id=str(turn_committed["utterance_id"]),
        router_decision=router_decision,
        task_focus=router_task_focus,
        confidence=0.91,
        evidence_uncertainty="low",
        fast_interaction_output_event_id=str(output_event["event_id"]),
    )
    return journal, candidate_event, output_event, router_event


def _gate_context(
    *,
    authority_mode: str = "trusted_synthetic_eval",
    authority_binding_status: str = "bound",
    task_focus: str = "FOREGROUND_CHAT",
    interaction_state: str = "TURN_COMMITTED",
    interaction_state_ref: str | None = "interaction-state://synthetic/mvp63/committed",
    task_focus_snapshot_ref: str | None = "task-focus://synthetic/mvp63/snapshot",
    has_active_slowtask: bool = False,
    active_task_id: str | None = None,
    active_slowtask_lifecycle: str | None = None,
    active_plan_version: int | None = None,
    active_task_event_seq: int | None = None,
    pending_confirmation: bool = False,
    pending_confirmation_id: str | None = None,
    pending_confirmation_scope: str | None = None,
    capability_snapshot_ref: str | None = "capability://synthetic/mvp63/fast-gate",
    capability_health_status: str = "ready",
    capability_output_mode: str = "real",
    capability_verification_status: str = "provider_free_verified",
    candidate_policy_decision: CandidatePolicyDecision | object | None = None,
    schema_valid: bool = True,
    confidence_threshold: float = 0.8,
) -> FastForegroundGateContext:
    return FastForegroundGateContext(
        authority_mode=authority_mode,
        authority_binding_status=authority_binding_status,
        interaction_state=interaction_state,
        interaction_state_ref=interaction_state_ref,
        task_focus=task_focus,
        task_focus_snapshot_ref=task_focus_snapshot_ref,
        has_active_slowtask=has_active_slowtask,
        active_task_id=active_task_id,
        active_slowtask_lifecycle=active_slowtask_lifecycle,
        pending_confirmation=pending_confirmation,
        pending_confirmation_id=pending_confirmation_id,
        pending_confirmation_scope=pending_confirmation_scope,
        capability_snapshot_ref=capability_snapshot_ref,
        capability_health_status=capability_health_status,
        capability_output_mode=capability_output_mode,
        capability_verification_status=capability_verification_status,
        candidate_policy_decision=(
            CandidatePolicyDecision.trusted_synthetic()
            if candidate_policy_decision is None
            else candidate_policy_decision
        ),  # type: ignore[arg-type]
        schema_valid=schema_valid,
        confidence_threshold=confidence_threshold,
        active_plan_version=(
            1
            if has_active_slowtask and active_plan_version is None
            else active_plan_version
        ),
        active_task_event_seq=(
            1
            if has_active_slowtask and active_task_event_seq is None
            else active_task_event_seq
        ),
    )
