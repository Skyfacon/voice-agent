from __future__ import annotations

from types import SimpleNamespace

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateContext,
)
from voice_agent.runtime.foreground_template_catalog import (
    resolve_foreground_template,
)
from voice_agent.runtime.mvp5_live_router_runner import (
    MVP5ActiveSlowTaskContext,
    MVP5LiveRouterConfig,
    run_mvp5_live_router_runner,
)
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime


def test_missing_fast_candidate_gets_terminal_failed_gate_and_exact_clarify() -> None:
    evidence = _fast_evidence(include_candidate=False)

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-missing-fast-candidate",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_gate_context(),
        ),
    )

    assert result.foreground_gate_decision == "failed"
    assert result.foreground_gate_failure_reason == (
        "local_template_requires_fallback_commit"
    )
    assert result.foreground_output_basis == "template_clarify"
    assert result.response_text_ref == result.foreground_output_ref
    assert "direct-answer" not in str(result.response_text_ref)
    candidates = [
        event
        for event in result.events
        if event["event_name"] == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
    ]
    assert len(candidates) == 1
    assert candidates[0]["source_module"] == "foreground_template_catalog"
    committed = _event(result.events, "FOREGROUND_OUTPUT_COMMITTED")
    router = _event(result.events, "ROUTER_DECISION_EMITTED")
    template = resolve_foreground_template(
        output_ref=committed["output_ref"],
        output_basis=committed["output_basis"],
        fallback_policy_ref=committed["fallback_policy_ref"],
        router_decision=router["router_decision"],
    )
    assert template is not None
    assert template.foreground_act == "CLARIFY"


def test_fast_only_without_fast_interaction_still_gets_terminal_clarify_gate() -> None:
    evidence = _thinker_only_evidence()

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-no-fast-evidence",
            expected_route="FAST_ONLY",
        ),
    )

    assert result.foreground_gate_decision == "failed"
    assert result.foreground_gate_failure_reason == "fast_interaction_missing"
    assert result.foreground_output_basis == "template_clarify"
    assert result.route_result_kind == "foreground_clarify"
    assert result.foreground_output_ref == result.response_text_ref
    assert "direct-answer" not in str(result.response_text_ref)
    assert not any(
        event["event_name"] == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
        for event in result.events
    )


def test_current_interrupted_reducer_state_overrides_historical_turn_commit() -> None:
    evidence = _fast_evidence(include_candidate=True, interrupted=True)

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-current-interrupted",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_gate_context(),
        ),
    )

    assert result.foreground_gate_decision == "failed"
    assert result.foreground_gate_failure_reason == "interaction_state_not_ready"
    assert result.foreground_output_basis == "template_clarify"


def test_active_task_plan_and_sequence_mismatch_fails_authority_binding() -> None:
    evidence = _fast_evidence(
        include_candidate=True,
        include_active_task_history=True,
    )
    active = MVP5ActiveSlowTaskContext(
        task_id="task_authoritative",
        current_plan_version=1,
        current_task_event_seq=4,
        lifecycle_phase="PLANNING",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-active-stale-binding",
            expected_route="FAST_ONLY",
            active_task_context=active,
            fast_foreground_gate_context=_gate_context(
                has_active_slowtask=True,
                active_task_id="task_authoritative",
                active_slowtask_lifecycle="PLANNING",
                active_plan_version=1,
                active_task_event_seq=3,
            ),
        ),
    )

    assert result.foreground_gate_failure_reason == "gate_authority_context_mismatch"
    assert result.foreground_output_basis == "template_clarify"


def test_journal_reduced_active_task_authority_overrides_stale_caller_snapshot() -> None:
    evidence = _fast_evidence(
        include_candidate=True,
        include_active_task_history=True,
    )
    stale_active = MVP5ActiveSlowTaskContext(
        task_id="task_authoritative",
        current_plan_version=1,
        current_task_event_seq=3,
        lifecycle_phase="PLANNING",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-journal-active-authority",
            expected_route="FAST_ONLY",
            active_task_context=stale_active,
            fast_foreground_gate_context=_gate_context(
                has_active_slowtask=True,
                active_task_id="task_authoritative",
                active_slowtask_lifecycle="PLANNING",
                active_plan_version=1,
                active_task_event_seq=3,
            ),
        ),
    )

    assert result.foreground_gate_failure_reason == "gate_authority_context_mismatch"
    assert result.foreground_output_basis == "template_clarify"


def test_active_task_snapshot_without_canonical_history_cannot_patch() -> None:
    evidence = _fast_evidence(
        include_candidate=True,
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="ACTIVE_TASK_PATCH",
        foreground_act="ACK_PATCH",
        include_understanding=True,
    )
    caller_snapshot = MVP5ActiveSlowTaskContext(
        task_id="task_unjournaled_snapshot",
        current_plan_version=4,
        current_task_event_seq=9,
        lifecycle_phase="PLANNING",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-unjournaled-patch-authority",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            active_task_context=caller_snapshot,
            fast_foreground_gate_context=_gate_context(
                task_focus="ACTIVE_TASK_PATCH",
                has_active_slowtask=True,
                active_task_id=caller_snapshot.task_id,
                active_slowtask_lifecycle=caller_snapshot.lifecycle_phase,
                active_plan_version=caller_snapshot.current_plan_version,
                active_task_event_seq=caller_snapshot.current_task_event_seq,
            ),
        ),
    )

    assert result.route_result_kind == "degraded"
    assert not any(
        event["event_name"] == "USER_PATCH_RECEIVED" for event in result.events
    )
    assert not any(
        event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
        and event.get("foreground_act") == "ACK_PATCH"
        for event in result.events
    )


def test_spawn_ack_is_committed_only_after_canonical_mutation_completes() -> None:
    evidence = _fast_evidence(
        include_candidate=True,
        router_decision="SPAWN_SLOW_TASK",
        task_focus="NEW_TASK_CANDIDATE",
        foreground_act="ACK_SLOW",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-spawn-success",
            expected_route="SPAWN_SLOW_TASK",
            fast_foreground_gate_context=_gate_context(
                task_focus="NEW_TASK_CANDIDATE"
            ),
        ),
    )

    committed = _event(result.events, "FOREGROUND_OUTPUT_COMMITTED")
    created = _event(result.events, "SLOWTASK_CREATED")
    assert committed["output_basis"] == "template_ack"
    assert int(committed["event_seq"]) > int(created["event_seq"])
    template = resolve_foreground_template(
        output_ref=committed["output_ref"],
        output_basis=committed["output_basis"],
        fallback_policy_ref=committed["fallback_policy_ref"],
        router_decision="SPAWN_SLOW_TASK",
    )
    assert template is not None
    assert template.foreground_act == "ACK_SLOW"


def test_partial_spawn_mutation_never_commits_success_ack(monkeypatch) -> None:
    evidence = _fast_evidence(
        include_candidate=True,
        router_decision="SPAWN_SLOW_TASK",
        task_focus="NEW_TASK_CANDIDATE",
        foreground_act="ACK_SLOW",
    )

    def append_partial_then_fail(
        runtime: MockSlowTaskRuntime,
        **kwargs: object,
    ) -> object:
        router_event = kwargs["router_decision_event"]
        assert isinstance(router_event, dict)
        runtime._journal.append(
            event_name="SLOWTASK_CREATED",
            event_id="evt_slice3a13_partial_slowtask_created",
            source_module="slowtask_runtime",
            caused_by_event_id=str(router_event["event_id"]),
            created_monotonic_ms=80,
            created_wall_clock_ms=1700000000080,
            trace_redaction_level="metadata_only",
            task_id="task_slice3a13_partial",
            plan_version=1,
            task_event_seq=1,
            initial_goal_ref="goal://synthetic/slice3a13/partial",
        )
        raise RuntimeError("synthetic mutation failure")

    monkeypatch.setattr(
        MockSlowTaskRuntime,
        "run_spawn_planning_completed",
        append_partial_then_fail,
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-spawn-partial",
            expected_route="SPAWN_SLOW_TASK",
            fast_foreground_gate_context=_gate_context(
                task_focus="NEW_TASK_CANDIDATE"
            ),
        ),
    )

    commits = [
        event
        for event in result.events
        if event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
    ]
    assert result.status == "degraded_mutation_failed"
    assert len(commits) == 1
    assert commits[0]["output_basis"] == "template_clarify"
    assert all(event["output_basis"] != "template_ack" for event in commits)


def test_patch_ack_requires_full_canonical_tail_and_reducer_reconcile() -> None:
    evidence = _fast_evidence(
        include_candidate=True,
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="ACTIVE_TASK_PATCH",
        foreground_act="ACK_PATCH",
        include_understanding=True,
        include_active_task_history=True,
    )
    active = MVP5ActiveSlowTaskContext(
        task_id="task_authoritative",
        current_plan_version=1,
        current_task_event_seq=4,
        lifecycle_phase="PLANNING",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-patch-full-tail",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            active_task_context=active,
            fast_foreground_gate_context=_gate_context(
                task_focus="ACTIVE_TASK_PATCH",
                has_active_slowtask=True,
                active_task_id=active.task_id,
                active_slowtask_lifecycle=active.lifecycle_phase,
                active_plan_version=active.current_plan_version,
                active_task_event_seq=active.current_task_event_seq,
            ),
        ),
    )

    names = [event["event_name"] for event in result.events]
    for required in (
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "PLANNING_RESTARTED",
        "TASK_REPLANNED",
        "SLOWTASK_STATE_CHANGED",
    ):
        assert required in names
    committed = _event(result.events, "FOREGROUND_OUTPUT_COMMITTED")
    completion = [
        event
        for event in result.events
        if event["event_name"] == "SLOWTASK_STATE_CHANGED"
    ][-1]
    assert committed["output_basis"] == "template_ack"
    assert committed["foreground_act"] == "ACK_PATCH"
    assert int(committed["event_seq"]) > int(completion["event_seq"])


def test_partial_patch_tail_never_commits_ack_patch(monkeypatch) -> None:
    evidence = _fast_evidence(
        include_candidate=True,
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="ACTIVE_TASK_PATCH",
        foreground_act="ACK_PATCH",
        include_understanding=True,
        include_active_task_history=True,
    )
    active = MVP5ActiveSlowTaskContext(
        task_id="task_authoritative",
        current_plan_version=1,
        current_task_event_seq=4,
        lifecycle_phase="PLANNING",
    )

    def append_interpretation_then_fail(
        runtime: MockSlowTaskRuntime,
        **kwargs: object,
    ) -> object:
        patch = kwargs["user_patch_event"]
        assert isinstance(patch, dict)
        runtime._journal.append(
            event_name="USER_PATCH_INTERPRETED",
            event_id="evt_slice3a13_partial_patch_interpreted",
            source_module="slowtask_runtime",
            caused_by_event_id=str(patch["event_id"]),
            created_monotonic_ms=70,
            created_wall_clock_ms=1700000000070,
            trace_redaction_level="metadata_only",
            patch_id=str(patch["patch_id"]),
            task_id=str(patch["task_id"]),
            plan_version=int(patch["plan_version"]),
            task_event_seq=int(patch["task_event_seq"]) + 1,
            observed_plan_version=int(patch["observed_plan_version"]),
            interpreted_against_plan_version=int(patch["observed_plan_version"]),
            interpretation_type="constraint_update",
            materially_changes_task=True,
            interpretation_reason="synthetic_partial_patch",
            source_evidence_refs=(),
        )
        raise RuntimeError("synthetic partial patch failure")

    monkeypatch.setattr(
        MockSlowTaskRuntime,
        "interpret_user_patch",
        append_interpretation_then_fail,
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="slice3a13-patch-partial",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            active_task_context=active,
            fast_foreground_gate_context=_gate_context(
                task_focus="ACTIVE_TASK_PATCH",
                has_active_slowtask=True,
                active_task_id=active.task_id,
                active_slowtask_lifecycle=active.lifecycle_phase,
                active_plan_version=active.current_plan_version,
                active_task_event_seq=active.current_task_event_seq,
            ),
        ),
    )

    commits = [
        event
        for event in result.events
        if event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
    ]
    assert result.status == "degraded_mutation_failed"
    assert len(commits) == 1
    assert commits[0]["output_basis"] == "template_clarify"
    assert commits[0]["foreground_act"] == "CLARIFY"


def _fast_evidence(
    *,
    include_candidate: bool,
    interrupted: bool = False,
    router_decision: str = "FAST_ONLY",
    task_focus: str = "FOREGROUND_CHAT",
    foreground_act: str = "ANSWER",
    include_understanding: bool = False,
    include_active_task_history: bool = False,
) -> SimpleNamespace:
    journal = InMemoryEventJournal(
        session_id="sess_slice3a13_gate",
        conversation_id="conv_slice3a13_gate",
    )
    started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_slice3a13_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/slice3a13/gate",
        capability_snapshot_ref="capability://synthetic/slice3a13/gate",
    )
    journal.append(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id="evt_slice3a13_capability",
        source_module="session_runtime",
        caused_by_event_id=str(started["event_id"]),
        created_monotonic_ms=2,
        created_wall_clock_ms=1700000000002,
        trace_redaction_level="metadata_only",
        capability_snapshot_ref="capability://synthetic/slice3a13/gate",
        adapter_ids=("mvp63_fast_interaction_runtime",),
        adapter_types=("fast_interaction",),
        deployment_modes=("in_process",),
        output_modes=("real",),
    )
    if include_active_task_history:
        created = journal.append(
            event_name="SLOWTASK_CREATED",
            event_id="evt_slice3a13_existing_task_created",
            source_module="slowtask_runtime",
            caused_by_event_id="evt_slice3a13_capability",
            created_monotonic_ms=3,
            created_wall_clock_ms=1700000000003,
            trace_redaction_level="metadata_only",
            task_id="task_authoritative",
            plan_version=1,
            task_event_seq=1,
            initial_goal_ref="goal://synthetic/slice3a13/existing",
        )
        created_state = journal.append(
            event_name="SLOWTASK_STATE_CHANGED",
            event_id="evt_slice3a13_existing_task_state_created",
            source_module="slowtask_runtime",
            caused_by_event_id=str(created["event_id"]),
            created_monotonic_ms=4,
            created_wall_clock_ms=1700000000004,
            trace_redaction_level="metadata_only",
            task_id="task_authoritative",
            plan_version=1,
            task_event_seq=2,
            from_state="CREATED",
            to_state="CREATED",
            reason="created_snapshot",
        )
        planning = journal.append(
            event_name="PLANNING_STARTED",
            event_id="evt_slice3a13_existing_task_planning",
            source_module="slowtask_runtime",
            caused_by_event_id=str(created_state["event_id"]),
            created_monotonic_ms=5,
            created_wall_clock_ms=1700000000005,
            trace_redaction_level="metadata_only",
            task_id="task_authoritative",
            plan_version=1,
            task_event_seq=3,
            planning_reason="synthetic_existing_task",
        )
        journal.append(
            event_name="SLOWTASK_STATE_CHANGED",
            event_id="evt_slice3a13_existing_task_state_planning",
            source_module="slowtask_runtime",
            caused_by_event_id=str(planning["event_id"]),
            created_monotonic_ms=6,
            created_wall_clock_ms=1700000000006,
            trace_redaction_level="metadata_only",
            task_id="task_authoritative",
            plan_version=1,
            task_event_seq=4,
            from_state="CREATED",
            to_state="PLANNING",
            reason="synthetic_existing_task",
        )
    turn = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_slice3a13_turn_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000000010,
        trace_redaction_level="metadata_only",
        turn_id="turn_slice3a13_gate",
        utterance_id="utt_slice3a13_gate",
        input_modality="audio",
        audio_span_id="audio_slice3a13_gate",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    asr = None
    thinker = None
    if include_understanding:
        asr = journal.append(
            event_name="MOCK_ASR_FRAME_EMITTED",
            event_id="evt_slice3a13_mock_asr",
            source_module="mock_asr",
            caused_by_event_id=str(turn["event_id"]),
            created_monotonic_ms=15,
            created_wall_clock_ms=1700000000015,
            trace_redaction_level="redacted_fixture",
            turn_id=str(turn["turn_id"]),
            utterance_id=str(turn["utterance_id"]),
            input_modality="audio",
            asr_frame_ref="asr-frame://synthetic/slice3a13/patch",
            output_mode="mock",
        )
        thinker = journal.append(
            event_name="MOCK_THINKER_FRAME_EMITTED",
            event_id="evt_slice3a13_mock_thinker",
            source_module="mock_thinker",
            caused_by_event_id=str(turn["event_id"]),
            created_monotonic_ms=16,
            created_wall_clock_ms=1700000000016,
            trace_redaction_level="redacted_fixture",
            turn_id=str(turn["turn_id"]),
            utterance_id=str(turn["utterance_id"]),
            semantic_frame_ref="semantic-frame://synthetic/slice3a13/patch",
            task_focus_hint=task_focus,
            task_like=True,
            complexity_hint="task",
            focus_confidence=0.95,
            evidence_uncertainty="low",
            output_mode="mock",
        )
    fast = journal.append(
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
        event_id="evt_slice3a13_fast_output",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000000020,
        trace_redaction_level="metadata_only",
        adapter_id="mvp63_fast_interaction_runtime",
        adapter_type="fast_interaction",
        adapter_request_id="request_slice3a13_fast",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        source_event_ids=(str(turn["event_id"]),),
        route_hint_ref="route-hint://synthetic/slice3a13/gate",
        route_prelude_ref="route-prelude://synthetic/slice3a13/gate",
        route_decision_hint=router_decision,
        task_focus_hint=task_focus,
        foreground_act=foreground_act,
        final_fast_evidence_ref="fast-evidence://synthetic/slice3a13/gate",
        schema_name="voice_agent.fast_interaction.output.v1",
        normalization_status="normalized",
        output_mode="real",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        risk_tags=("none",),
        risk_class="LOW",
        confidence=0.95,
    )
    candidate = None
    if include_candidate:
        candidate = journal.append(
            event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
            event_id="evt_slice3a13_candidate",
            source_module="fast_interaction_adapter",
            caused_by_event_id=str(fast["event_id"]),
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
            trace_redaction_level="metadata_only",
            candidate_id="candidate_slice3a13_gate",
            fast_interaction_output_event_id=str(fast["event_id"]),
            turn_id=str(turn["turn_id"]),
            utterance_id=str(turn["utterance_id"]),
            candidate_ref="foreground-candidate://synthetic/slice3a13/gate",
            candidate_status="complete",
            input_mode="audio_native",
            fast_interaction_input_mode="audio_native",
            source_event_ids=(str(fast["event_id"]),),
            risk_tags=("none",),
            confidence=0.95,
        )
    if interrupted:
        journal.append(
            event_name="INTERRUPT_CANDIDATE",
            event_id="evt_slice3a13_interrupt",
            source_module="interaction_controller",
            caused_by_event_id=str(fast["event_id"]),
            created_monotonic_ms=35,
            created_wall_clock_ms=1700000000035,
            trace_redaction_level="metadata_only",
            playback_span_id="playback_slice3a13",
            playback_offset_ms=12,
            policy_reason="synthetic_interrupt_probe",
            confidence_summary="high",
        )
    return SimpleNamespace(
        events=tuple(journal.events()),
        fast_interaction_event_id=str(fast["event_id"]),
        foreground_candidate_event_id=(
            str(candidate["event_id"]) if candidate is not None else None
        ),
        thinker_event_id=(str(thinker["event_id"]) if thinker is not None else None),
        asr_event_id=(str(asr["event_id"]) if asr is not None else None),
        asr_observation_enabled=False,
        provider_call_used=False,
        fake_transport_used=True,
    )


def _thinker_only_evidence() -> SimpleNamespace:
    evidence = _fast_evidence(
        include_candidate=False,
        include_understanding=True,
    )
    filtered = tuple(
        event
        for event in evidence.events
        if event["event_name"] != "FAST_INTERACTION_OUTPUT_EMITTED"
    )
    return SimpleNamespace(
        events=filtered,
        fast_interaction_event_id=None,
        foreground_candidate_event_id=None,
        thinker_event_id=evidence.thinker_event_id,
        asr_event_id=evidence.asr_event_id,
        asr_observation_enabled=False,
        provider_call_used=False,
        fake_transport_used=True,
    )


def _gate_context(
    *,
    task_focus: str = "FOREGROUND_CHAT",
    has_active_slowtask: bool = False,
    active_task_id: str | None = None,
    active_slowtask_lifecycle: str | None = None,
    active_plan_version: int | None = None,
    active_task_event_seq: int | None = None,
) -> FastForegroundGateContext:
    return FastForegroundGateContext(
        authority_mode="trusted_synthetic_eval",
        authority_binding_status="bound",
        interaction_state="TURN_COMMITTED",
        interaction_state_ref="interaction-state://synthetic/slice3a13",
        task_focus=task_focus,
        task_focus_snapshot_ref="task-focus://synthetic/slice3a13",
        has_active_slowtask=has_active_slowtask,
        active_task_id=active_task_id,
        active_slowtask_lifecycle=active_slowtask_lifecycle,
        pending_confirmation=False,
        pending_confirmation_id=None,
        pending_confirmation_scope=None,
        capability_snapshot_ref="capability://synthetic/slice3a13/gate",
        capability_health_status="ready",
        capability_output_mode="real",
        capability_verification_status="provider_free_verified",
        candidate_policy_decision=CandidatePolicyDecision.trusted_synthetic(),
        schema_valid=True,
        confidence_threshold=0.8,
        active_plan_version=active_plan_version,
        active_task_event_seq=active_task_event_seq,
    )


def _event(
    events: tuple[dict[str, object], ...],
    event_name: str,
) -> dict[str, object]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]
