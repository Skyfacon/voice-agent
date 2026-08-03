from __future__ import annotations

import json
from pathlib import Path
import wave

from voice_agent.adapters.adapter_timing import AdapterTimingSnapshot
from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.fast_interaction_live_transport import FastInteractionProviderCompletion
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime import mvp5_live_router_runner as router_runner_module
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateContext,
)
from voice_agent.runtime.mvp5_live_router_runner import (
    MVP5ActiveSlowTaskContext,
    MVP5LiveRouterConfig,
    run_mvp5_live_router_runner,
)
from voice_agent.runtime.mvp5_live_voice_evidence import (
    MVP5LiveVoiceEvidenceConfig,
    run_mvp5_live_voice_evidence,
)


def test_fast_only_result_is_metadata_only_and_does_not_mutate_slowtask(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="fast-only",
        task_focus_hint="FOREGROUND_CHAT",
        task_like=False,
        complexity_hint="simple",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-fast-only",
            expected_route="FAST_ONLY",
        ),
    )

    metadata = result.to_metadata()
    event_names = [event["event_name"] for event in result.events]

    assert result.status == "routed"
    assert metadata["route_result_kind"] == "foreground_clarify"
    assert metadata["router_decision"] == "FAST_ONLY"
    assert _event(result.events, "ROUTER_DECISION_EMITTED")["task_focus"] == "FOREGROUND_CHAT"
    assert metadata["response_text_ref"].startswith("foreground-template://")
    assert "FOREGROUND_ACT_GATE_FAILED" in event_names
    assert _event(result.events, "FOREGROUND_OUTPUT_COMMITTED")[
        "output_basis"
    ] == "template_clarify"
    assert metadata["real_tts_used"] is False
    assert metadata["voice_output"] == "none"
    for forbidden_event in (
        "SLOWTASK_CREATED",
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
    ):
        assert forbidden_event not in event_names
    _assert_safe_summary(metadata)


def test_fast_interaction_fast_only_commits_gated_reply_without_thinker(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(
        tmp_path,
        route_slug="mvp63-fast-only-gated",
        router_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-route-fast-only-gated",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(
                task_focus="FOREGROUND_CHAT"
            ),
        ),
    )

    metadata = result.to_metadata()
    event_names = [event["event_name"] for event in result.events]
    fast_event = _event(result.events, "FAST_INTERACTION_OUTPUT_EMITTED")
    candidate_event = _event(result.events, "FOREGROUND_REPLY_CANDIDATE_EMITTED")
    gate_event = _event(result.events, "FOREGROUND_ACT_GATE_PASSED")
    committed = _event(result.events, "FOREGROUND_OUTPUT_COMMITTED")
    router_event = _event(result.events, "ROUTER_DECISION_EMITTED")

    assert "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED" not in event_names
    assert result.status == "routed"
    assert metadata["route_result_kind"] == "direct_answer"
    assert metadata["router_decision"] == "FAST_ONLY"
    assert metadata["evidence_ref_policy"] == "preserve_fast_ref"
    assert metadata["foreground_gate_decision"] == "passed"
    assert metadata["foreground_output_basis"] == "reply_candidate"
    assert metadata["fast_interaction_event_id"] == fast_event["event_id"]
    assert metadata["foreground_candidate_event_id"] == candidate_event["event_id"]
    assert metadata["foreground_gate_event_id"] == gate_event["event_id"]
    assert metadata["foreground_output_event_id"] == committed["event_id"]
    assert metadata["foreground_candidate_ref"] == candidate_event["candidate_ref"]
    assert metadata["foreground_output_ref"] == committed["output_ref"]
    assert metadata["response_text_ref"] == committed["output_ref"]
    assert metadata["router_ms"] >= 0
    assert metadata["foreground_gate_ms"] >= 0
    assert metadata["foreground_output_finalize_ms"] >= 0
    assert router_event["fast_interaction_output_event_id"] == fast_event["event_id"]
    assert committed["output_basis"] == "reply_candidate"
    assert committed["output_ref"] == candidate_event["candidate_ref"]
    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names
    _assert_safe_summary(metadata)


def test_live_router_without_explicit_gate_authority_context_fails_closed(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(
        tmp_path,
        route_slug="mvp63-missing-live-gate-context",
        router_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.99,
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-route-missing-live-gate-context",
            expected_route="FAST_ONLY",
        ),
    )

    assert result.foreground_gate_decision == "failed"
    assert result.foreground_gate_failure_reason == "gate_authority_context_missing"
    assert result.foreground_output_basis == "template_clarify"
    assert result.foreground_output_ref != result.foreground_candidate_ref
    assert result.response_text_ref == result.foreground_output_ref


def test_live_router_quarantines_arbitrary_provider_candidate_despite_low_claims(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(
        tmp_path,
        route_slug="mvp63-provider-candidate-quarantine",
        router_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.99,
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-route-provider-candidate-quarantine",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_live_provider_gate_context(
                task_focus="FOREGROUND_CHAT",
                verification_status="real_live_verified",
            ),
        ),
    )

    assert result.foreground_gate_failure_reason == "candidate_policy_quarantined"
    assert result.foreground_output_basis == "template_clarify"
    assert result.foreground_output_ref != result.foreground_candidate_ref


def test_live_router_uses_capability_snapshot_output_mode_not_provider_proposal(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(
        tmp_path,
        route_slug="mvp63-capability-mode-authority",
        router_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.99,
    )
    fast_event = next(
        event
        for event in evidence.events
        if event["event_name"] == "FAST_INTERACTION_OUTPUT_EMITTED"
    )
    fast_event["output_mode"] = "mock"

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-route-capability-mode-authority",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(
                task_focus="FOREGROUND_CHAT",
                capability_output_mode="mock",
            ),
        ),
    )

    assert result.foreground_gate_failure_reason == "capability_output_mode_mismatch"
    assert result.foreground_output_basis == "template_clarify"


def test_live_router_blocks_active_side_chat_while_confirmation_is_pending(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(
        tmp_path,
        route_slug="mvp63-pending-confirmation-side-chat",
        router_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.99,
    )
    active_context = MVP5ActiveSlowTaskContext(
        task_id="task_mvp63_pending_confirmation",
        current_plan_version=1,
        current_task_event_seq=7,
        lifecycle_phase="WAITING_FOR_USER_CONFIRMATION",
        pending_confirmation_id="confirmation_mvp63_pending",
        pending_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-route-pending-confirmation-side-chat",
            expected_route="FAST_ONLY",
            active_task_context=active_context,
            fast_foreground_gate_context=_trusted_synthetic_gate_context(
                task_focus="FOREGROUND_CHAT",
                active_task_context=active_context,
            ),
        ),
        journal=_journal_with_active_task_authority(evidence, active_context),
    )

    assert result.foreground_gate_failure_reason == "pending_confirmation_active"
    assert result.foreground_output_basis == "template_clarify"
    assert result.foreground_output_ref != result.foreground_candidate_ref


def test_fast_interaction_is_consumed_before_router_and_gate_without_post_router_reply_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    call_order: list[str] = []
    evidence = _live_fast_evidence_result(
        tmp_path,
        route_slug="mvp63-no-post-router-reply",
        router_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
        call_order=call_order,
    )

    original_emit_decision = router_runner_module.MVP1Router.emit_decision
    original_gate = router_runner_module.run_fast_foreground_gate

    def emit_decision_with_order(*args, **kwargs):
        call_order.append("router")
        return original_emit_decision(*args, **kwargs)

    def gate_with_order(*args, **kwargs):
        call_order.append("foreground_gate")
        return original_gate(*args, **kwargs)

    monkeypatch.setattr(
        router_runner_module.MVP1Router,
        "emit_decision",
        emit_decision_with_order,
    )
    monkeypatch.setattr(router_runner_module, "run_fast_foreground_gate", gate_with_order)

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-route-no-post-router-reply",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(
                task_focus="FOREGROUND_CHAT"
            ),
        ),
    )

    assert result.status == "routed"
    assert call_order == ["fast_interaction_before_router", "router", "foreground_gate"]
    assert "fast_reply_after_router" not in call_order


def test_fast_interaction_slow_route_discards_candidate_and_spawns_slowtask(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(
        tmp_path,
        route_slug="mvp63-spawn-gated",
        router_decision_candidate="SPAWN_SLOW_TASK",
        foreground_act="ACK_SLOW",
        risk_class="LOW",
        confidence=0.9,
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-route-spawn-gated",
            expected_route="SPAWN_SLOW_TASK",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(
                task_focus="NEW_TASK_CANDIDATE"
            ),
        ),
    )

    metadata = result.to_metadata()
    event_names = [event["event_name"] for event in result.events]
    fast_event = _event(result.events, "FAST_INTERACTION_OUTPUT_EMITTED")
    discarded = _event(result.events, "FOREGROUND_OUTPUT_DISCARDED")
    committed = _event(result.events, "FOREGROUND_OUTPUT_COMMITTED")
    created = _event(result.events, "SLOWTASK_CREATED")

    assert result.status == "routed"
    assert metadata["route_result_kind"] == "slowtask_spawn"
    assert metadata["router_decision"] == "SPAWN_SLOW_TASK"
    assert metadata["foreground_gate_decision"] == "failed"
    assert metadata["foreground_output_basis"] == "template_ack"
    assert metadata["foreground_discard_event_id"] == discarded["event_id"]
    assert metadata["foreground_output_event_id"] == committed["event_id"]
    assert metadata["foreground_output_ref"] == committed["output_ref"]
    assert metadata["foreground_fallback_policy_ref"] == committed[
        "fallback_policy_ref"
    ]
    assert metadata["foreground_fallback_reason"] == committed["fallback_reason"]
    assert metadata["fast_interaction_event_id"] == fast_event["event_id"]
    assert committed["output_basis"] == "template_ack"
    assert "FOREGROUND_OUTPUT_DISCARDED" in event_names
    assert "SLOWTASK_CREATED" in event_names
    assert str(created["task_id"]) == result.task_id
    assert f"event://mvp63/{fast_event['event_id']}" in created["source_evidence_refs"]
    assert str(fast_event["final_fast_evidence_ref"]) in created["source_evidence_refs"]
    _assert_safe_summary(metadata)


def test_spawn_slowtask_records_asr_and_thinker_refs_in_slowtask_evidence(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="spawn-route",
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-spawn-slowtask",
            expected_route="SPAWN_SLOW_TASK",
        ),
    )

    asr_event = _event(result.events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(result.events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    created = _event(result.events, "SLOWTASK_CREATED")
    reviewed = _event(result.events, "EVIDENCE_REVIEWED")
    slowtask_events = [
        event for event in result.events if event["event_name"] in result.slowtask_event_ids_by_name
    ]

    expected_refs = {
        f"event://mvp5/{asr_event['event_id']}",
        str(asr_event["asr_frame_ref"]),
        f"event://mvp5/{thinker_event['event_id']}",
        str(thinker_event["semantic_frame_ref"]),
    }
    assert result.to_metadata()["route_result_kind"] == "slowtask_spawn"
    assert _event(result.events, "ROUTER_DECISION_EMITTED")["task_focus"] == "NEW_TASK_CANDIDATE"
    assert expected_refs.issubset(set(created["source_evidence_refs"]))
    assert expected_refs.issubset(set(reviewed["evidence_refs"]))
    assert slowtask_events
    for event in slowtask_events:
        assert event["task_id"] == created["task_id"]
        assert event["plan_version"] == 1
        assert isinstance(event["task_event_seq"], int)
    _assert_safe_summary(result.to_metadata())


def test_patch_active_slowtask_receives_current_plan_user_patch_only(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="patch-active",
        task_focus_hint="ACTIVE_TASK_PATCH",
        task_like=True,
        complexity_hint="medium",
    )

    active_context = MVP5ActiveSlowTaskContext(
        task_id="task_mvp5_goal3_active",
        current_plan_version=1,
        current_task_event_seq=4,
        lifecycle_phase="PLANNING",
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-patch-active",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            active_task_context=active_context,
        ),
        journal=_journal_with_active_task_authority(evidence, active_context),
    )

    user_patch = _event(result.events, "USER_PATCH_RECEIVED")
    asr_event = _event(result.events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(result.events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    event_names = [event["event_name"] for event in result.events]

    assert result.to_metadata()["route_result_kind"] == "user_patch"
    assert _event(result.events, "ROUTER_DECISION_EMITTED")["task_focus"] == "ACTIVE_TASK_PATCH"
    assert user_patch["patch_id"] == "patch_mvp5_goal3_patch_active"
    assert user_patch["task_id"] == "task_mvp5_goal3_active"
    assert user_patch["plan_version"] == 1
    assert user_patch["observed_plan_version"] == 1
    assert user_patch["task_event_seq"] == 5
    assert user_patch["turn_id"] == evidence.turn_id
    assert user_patch["utterance_id"] == evidence.utterance_id
    assert user_patch["evidence_ref"].startswith("evidence://synthetic/mvp5/")
    assert f"audio-span://{evidence.audio_span_id}" in user_patch["authoritative_evidence_refs"]
    assert asr_event["asr_frame_ref"] in user_patch["authoritative_evidence_refs"]
    assert thinker_event["semantic_frame_ref"] in user_patch["non_authoritative_hypothesis_refs"]
    assert thinker_event["semantic_summary_ref"] in user_patch["non_authoritative_hypothesis_refs"]
    assert user_patch["evidence_pack"]["authoritative_evidence"]["source_event_ids"] == [
        _event(result.events, "TURN_INGRESS_COMMITTED")["event_id"],
        asr_event["event_id"],
    ]
    assert (
        user_patch["evidence_pack"]["non_authoritative_hypothesis"]["provenance"][
            "semantic_summary_ref"
        ]["source_event_id"]
        == thinker_event["event_id"]
    )
    assert event_names[event_names.index("USER_PATCH_RECEIVED") :] == [
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "PLANNING_RESTARTED",
        "TASK_REPLANNED",
        "SLOWTASK_STATE_CHANGED",
    ]
    for forbidden_event in (
        "CONFIRMATION_ACCEPTED",
        "TOOL_EXECUTION_AUTHORIZED",
    ):
        assert forbidden_event not in event_names
    for forbidden_field in (
        "resolved_arguments_ref",
        "constraints_ref",
        "goal_ref",
        "confirmation_id",
        "authorization_ref",
    ):
        assert forbidden_field not in user_patch
    _assert_safe_summary(result.to_metadata())


def test_active_task_patch_hint_without_active_context_is_blocked_without_mutation(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="patch-no-active",
        task_focus_hint="ACTIVE_TASK_PATCH",
        task_like=True,
        complexity_hint="medium",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-patch-no-active",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
        ),
    )

    metadata = result.to_metadata()
    event_names = [event["event_name"] for event in result.events]

    assert metadata["status"] == "blocked_missing_active_task_context"
    assert metadata["route_result_kind"] == "degraded"
    assert metadata["router_decision"] is None
    assert metadata["expected_route"] == "PATCH_ACTIVE_SLOW_TASK"
    assert metadata["expected_route_matched"] is False
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "SLOWTASK_CREATED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names
    _assert_safe_summary(metadata)


def _assert_safe_summary(metadata: dict[str, object]) -> None:
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["prompt_dump_included"] is False
    assert metadata["secret_included"] is False
    assert metadata["local_wav_path_included"] is False
    assert metadata["provider_call_used"] is False
    assert metadata["replay_reruns_provider"] is False
    assert metadata["real_tts_used"] is False
    assert metadata["voice_output"] == "none"
    rendered = json.dumps(metadata, sort_keys=True)
    for unsafe in (
        "DUMMY_TEST_CREDENTIAL",
        "file://",
        "data:",
        "audio/raw/",
        "diagnostics/",
        "traces/",
        "replays/local/",
        "raw transcript",
        "provider body",
        "prompt dump",
    ):
        assert unsafe not in rendered


def _live_evidence_result(
    tmp_path: Path,
    *,
    route_slug: str,
    task_focus_hint: str,
    task_like: bool,
    complexity_hint: str,
):
    wav_path = tmp_path / f"{route_slug}.wav"
    _write_wav_file(wav_path)
    asr_transport = FakeAsrTransport(
        (
            FakeAsrProviderResponse.success(
                asr_frame_ref=f"asr-frame://synthetic/mvp5/goal3/{route_slug}",
                text_ref=f"text://synthetic/mvp5/goal3/{route_slug}",
                audio_timestamps_ref=f"audio-timestamps://synthetic/mvp5/goal3/{route_slug}",
                streaming_status="supported",
                confidence_score=0.91,
            ),
        )
    )
    thinker_transport = _FakeThinkerAudioTransport(
        task_focus_hint=task_focus_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
    )

    return run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id=f"mvp5-goal3-{route_slug}",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
            requested_provider_calls=2,
            max_provider_calls=2,
        ),
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )


def _live_fast_evidence_result(
    tmp_path: Path,
    *,
    route_slug: str,
    router_decision_candidate: str,
    foreground_act: str,
    risk_class: str,
    confidence: float,
    call_order: list[str] | None = None,
):
    wav_path = tmp_path / f"{route_slug}.wav"
    _write_wav_file(wav_path)
    return run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id=f"mvp63-route-{route_slug}",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_fast_approval_packet(),
            credential_env_var_name="MVP63_TEST_PROVIDER_KEY",
            requested_provider_calls=1,
            max_provider_calls=1,
            timeout_ms=1500,
            fast_interaction_enabled=True,
            audio_native_thinker_enabled=False,
            fast_interaction_timeout_ms=1500,
        ),
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=_ExplodingAsrTransport(),
        thinker_transport=_ExplodingThinkerTransport(),
        fast_interaction_transport=_FakeFastInteractionTransport(
            router_decision_candidate=router_decision_candidate,
            foreground_act=foreground_act,
            risk_class=risk_class,
            confidence=confidence,
            call_order=call_order,
        ),
    )


class _FakeThinkerAudioTransport:
    def __init__(
        self,
        *,
        task_focus_hint: str,
        task_like: bool,
        complexity_hint: str,
    ) -> None:
        self.task_focus_hint = task_focus_hint
        self.task_like = task_like
        self.complexity_hint = complexity_hint

    def complete_audio(
        self,
        *,
        request_payload: object,
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        assert isinstance(request_payload, dict)
        assert audio_bytes
        assert audio_format == "wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp5-thinker-")
        assert timeout_ms == 30_000
        assert model_alias == LALM_THINKER_RUNTIME_MODEL_ALIAS
        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "neutral"},
            "audio_caption": {"status": "available", "label": "speech_available"},
        }
        skeleton["task_focus_hint"] = {
            "focus": self.task_focus_hint,
            "task_like": self.task_like,
            "complexity_hint": self.complexity_hint,
            "focus_confidence": 0.86,
            "evidence_uncertainty": "low",
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


class _FakeFastInteractionTransport:
    def __init__(
        self,
        *,
        router_decision_candidate: str,
        foreground_act: str,
        risk_class: str,
        confidence: float,
        call_order: list[str] | None = None,
    ) -> None:
        self.router_decision_candidate = router_decision_candidate
        self.foreground_act = foreground_act
        self.risk_class = risk_class
        self.confidence = confidence
        self.call_order = call_order

    def complete_audio_with_timing(
        self,
        *,
        request_payload: dict[str, object],
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
        turn_ingress_monotonic_ms: int,
    ) -> FastInteractionProviderCompletion:
        if self.call_order is not None:
            self.call_order.append("fast_interaction_before_router")
        assert request_payload["input_mode"] == "audio_native"
        assert request_payload["audio_payload_ref"]
        assert "text_ref" not in request_payload
        assert audio_bytes
        assert audio_format == "wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp63-fast-interaction-")
        assert timeout_ms == 1500
        assert model_alias == "qwen3.5-omni-flash"
        assert turn_ingress_monotonic_ms == 190
        assert "secret_materialized=False" in repr(credential_handle)
        return FastInteractionProviderCompletion(
            provider_text=json.dumps(
                {
                    "schema_name": "voice_agent.fast_interaction.output.v1",
                    "route_hint": {
                        "router_decision_candidate": self.router_decision_candidate,
                    },
                    "route_prelude": {"summary": "foreground route candidate"},
                    "foreground_act": self.foreground_act,
                    "reply_candidate": "A tiny safe spooky story.",
                    "final_fast_evidence": {"label": "foreground_route"},
                    "risk_tags": ["none"],
                    "risk_class": self.risk_class,
                    "confidence": self.confidence,
                    "output_mode": "real",
                    "boundary_assertions": {
                        "candidate_is_not_semantic_commitment": True,
                        "may_authorize_tools": False,
                        "may_execute_tools": False,
                        "may_accept_confirmation": False,
                        "may_mutate_slowtask_facts": False,
                        "runtime_gate_owns_display": True,
                    },
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            timing=_fast_timing_snapshot(),
        )


class _ExplodingThinkerTransport:
    def complete_audio(self, **_kwargs: object) -> str:
        raise AssertionError("audio-native thinker must not run for MVP6.3 fast route tests")


class _ExplodingAsrTransport:
    def transcribe(self, **_kwargs: object) -> object:
        raise AssertionError("ASR must not run in MVP6.3 audio-native fast primary path")


def _approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp5-live-route-results-goal3-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP5_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30_000,
        "safe_output_ref": "summary://mvp5/goal3/live-route-results-test",
    }


def _fast_approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp63-live-route-results-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp63_fast_interaction_runtime"],
        "credential_env_var_name": "MVP63_TEST_PROVIDER_KEY",
        "max_provider_calls": 1,
        "timeout_ms": 1500,
        "safe_output_ref": "summary://mvp63/live-route-results-test",
    }


def _trusted_synthetic_gate_context(
    *,
    task_focus: str,
    capability_output_mode: str = "real",
    active_task_context: MVP5ActiveSlowTaskContext | None = None,
) -> FastForegroundGateContext:
    pending = (
        active_task_context is not None
        and active_task_context.pending_confirmation_scope is not None
    )
    return FastForegroundGateContext(
        authority_mode="trusted_synthetic_eval",
        authority_binding_status="bound",
        interaction_state="TURN_COMMITTED",
        interaction_state_ref="interaction-state://synthetic/mvp63/turn-committed",
        task_focus=task_focus,
        task_focus_snapshot_ref="task-focus://synthetic/mvp63/independent-snapshot",
        has_active_slowtask=active_task_context is not None,
        active_task_id=(active_task_context.task_id if active_task_context else None),
        active_slowtask_lifecycle=(
            active_task_context.lifecycle_phase if active_task_context else None
        ),
        active_plan_version=(
            active_task_context.current_plan_version
            if active_task_context
            else None
        ),
        active_task_event_seq=(
            active_task_context.current_task_event_seq
            if active_task_context
            else None
        ),
        pending_confirmation=pending,
        pending_confirmation_id=(
            active_task_context.pending_confirmation_id if pending else None
        ),
        pending_confirmation_scope=(
            active_task_context.pending_confirmation_scope if pending else None
        ),
        capability_snapshot_ref="capability://mvp5/live-voice-evidence/provider-free",
        capability_health_status="ready",
        capability_output_mode=capability_output_mode,
        capability_verification_status="provider_free_verified",
        candidate_policy_decision=CandidatePolicyDecision.trusted_synthetic(),
        schema_valid=True,
        confidence_threshold=0.8,
    )


def _live_provider_gate_context(
    *,
    task_focus: str,
    verification_status: str,
) -> FastForegroundGateContext:
    return FastForegroundGateContext(
        authority_mode="live_runtime",
        authority_binding_status="bound",
        interaction_state="TURN_COMMITTED",
        interaction_state_ref="interaction-state://runtime/mvp63/turn-committed",
        task_focus=task_focus,
        task_focus_snapshot_ref="task-focus://runtime/mvp63/independent-snapshot",
        has_active_slowtask=False,
        active_task_id=None,
        active_slowtask_lifecycle=None,
        pending_confirmation=False,
        pending_confirmation_id=None,
        pending_confirmation_scope=None,
        capability_snapshot_ref="capability://mvp5/live-voice-evidence/provider-free",
        capability_health_status="ready",
        capability_output_mode="real",
        capability_verification_status=verification_status,
        candidate_policy_decision=CandidatePolicyDecision.quarantined_provider(),
        schema_valid=True,
        confidence_threshold=0.8,
    )


def _journal_with_active_task_authority(
    evidence: object,
    active_context: MVP5ActiveSlowTaskContext,
) -> InMemoryEventJournal:
    events = tuple(getattr(evidence, "events"))
    journal = InMemoryEventJournal(
        session_id=str(events[0]["session_id"]),
        conversation_id=str(events[0]["conversation_id"]),
    )
    for event in events:
        journal._append_validated_event(dict(event))
    last = journal.events()[-1]
    monotonic_ms = int(last["created_monotonic_ms"])
    wall_clock_ms = int(last["created_wall_clock_ms"])
    caused_by = str(last["event_id"])
    task_id = active_context.task_id

    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id=f"evt_{task_id}_authority_created",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by,
        created_monotonic_ms=monotonic_ms + 1,
        created_wall_clock_ms=wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref=f"goal://synthetic/mvp5/{task_id}",
    )
    created_state = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"evt_{task_id}_authority_created_state",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=monotonic_ms + 2,
        created_wall_clock_ms=wall_clock_ms + 2,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=2,
        from_state="CREATED",
        to_state="CREATED",
        reason="trusted_synthetic_authority_fixture",
    )
    planning = journal.append(
        event_name="PLANNING_STARTED",
        event_id=f"evt_{task_id}_authority_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created_state["event_id"]),
        created_monotonic_ms=monotonic_ms + 3,
        created_wall_clock_ms=wall_clock_ms + 3,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=3,
        planning_reason="trusted_synthetic_authority_fixture",
    )
    planning_state = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"evt_{task_id}_authority_planning_state",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning["event_id"]),
        created_monotonic_ms=monotonic_ms + 4,
        created_wall_clock_ms=wall_clock_ms + 4,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=4,
        from_state="CREATED",
        to_state="PLANNING",
        reason="trusted_synthetic_authority_fixture",
    )
    if active_context.lifecycle_phase == "PLANNING":
        assert active_context.current_plan_version == 1
        assert active_context.current_task_event_seq == 4
        return journal

    assert active_context.lifecycle_phase == "WAITING_FOR_USER_CONFIRMATION"
    assert active_context.current_plan_version == 1
    assert active_context.current_task_event_seq == 7
    assert active_context.pending_confirmation_id is not None
    assert active_context.pending_confirmation_scope is not None
    confirmation = journal.append(
        event_name="CONFIRMATION_REQUIRED",
        event_id=f"evt_{task_id}_authority_confirmation",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning_state["event_id"]),
        created_monotonic_ms=monotonic_ms + 5,
        created_wall_clock_ms=wall_clock_ms + 5,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=5,
        confirmation_id=active_context.pending_confirmation_id,
        confirmation_scope=active_context.pending_confirmation_scope,
        required_for_event_id=str(planning_state["event_id"]),
        prompt_ref=f"prompt://synthetic/mvp5/{task_id}/confirmation",
    )
    waiting = journal.append(
        event_name="WAITING_FOR_USER_CONFIRMATION",
        event_id=f"evt_{task_id}_authority_waiting",
        source_module="slowtask_runtime",
        caused_by_event_id=str(confirmation["event_id"]),
        created_monotonic_ms=monotonic_ms + 6,
        created_wall_clock_ms=wall_clock_ms + 6,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=6,
        confirmation_id=active_context.pending_confirmation_id,
    )
    journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"evt_{task_id}_authority_waiting_state",
        source_module="slowtask_runtime",
        caused_by_event_id=str(waiting["event_id"]),
        created_monotonic_ms=monotonic_ms + 7,
        created_wall_clock_ms=wall_clock_ms + 7,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=7,
        from_state="PLANNING",
        to_state="WAITING_FOR_USER_CONFIRMATION",
        reason="trusted_synthetic_authority_fixture",
    )
    return journal


def _event(events: tuple[dict[str, object], ...], event_name: str) -> dict[str, object]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]


def _write_wav_file(
    path: Path,
    *,
    sample_rate_hz: int = 16000,
    channel_count: int = 1,
    frame_count: int = 160,
) -> bytes:
    sample_width_bytes = 2
    silent_frame = b"\x00" * sample_width_bytes * channel_count
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channel_count)
        wav_file.setsampwidth(sample_width_bytes)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(silent_frame * frame_count)
    return path.read_bytes()


def _fast_timing_snapshot() -> AdapterTimingSnapshot:
    return AdapterTimingSnapshot(
        adapter_start_offset_ms=0,
        provider_request_start_offset_ms=5,
        provider_first_chunk_offset_ms=25,
        provider_full_response_offset_ms=65,
        adapter_event_emit_offset_ms=70,
        provider_ttft_ms=20,
        provider_full_response_ms=60,
        provider_generation_ms=40,
        stream_decode_ms=0,
        parse_validate_emit_ms=0,
        total_ms=70,
        timing_mode="streaming",
        ttft_available=True,
        ttft_source="provider_stream_chunk",
    )
