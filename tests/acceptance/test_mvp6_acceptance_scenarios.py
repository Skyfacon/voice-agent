from __future__ import annotations

import json
from pathlib import Path
import wave

from voice_agent.adapters.adapter_timing import AdapterTimingSnapshot
from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.fast_interaction_live_transport import (
    FastInteractionLiveTransportError,
    FastInteractionProviderCompletion,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.replay.runner import run_replay_fixture
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


SCENARIOS = (
    "MVP6-LOCAL-CONSOLE-STARTUP-001",
    "MVP6-MIC-DRAFT-RUN-001",
    "MVP6-PROVIDER-FREE-RUN-001",
    "MVP6-LIVE-PROVIDER-GATE-001",
    "MVP6-PIPELINE-INSPECTOR-001",
    "MVP6-QA-HISTORY-001",
    "MVP6-SAFETY-REDACTION-001",
    "MVP6-NO-ARCHITECTURE-EXPANSION-001",
)
MVP63_SCENARIOS = (
    "MVP6.3-LIVE-FAST-ANSWER-PASS-001",
    "MVP6.3-LIVE-QA-PARALLEL-001",
    "MVP6.3-LIVE-ASR-FAIL-ANSWER-PRESERVED-001",
    "MVP6.3-LIVE-FAST-TIMEOUT-FALLBACK-001",
    "MVP6.3-LIVE-SLOW-DISCARD-TEMPLATE-001",
    "MVP6.3-LIVE-PATCH-DISCARD-TEMPLATE-001",
    "MVP6.3-REPLAY-NO-PROVIDER-RERUN-001",
    "MVP6.3-SAFETY-EXPORT-001",
)


def test_mvp6_operating_doc_lists_all_acceptance_scenarios() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    for scenario in SCENARIOS:
        assert scenario in doc


def test_mvp6_operating_doc_states_non_goals_and_safe_artifacts() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    normalized_doc = " ".join(doc.split())
    required_phrases = (
        "## Local Artifact Policy",
        "All MVP6 artifacts are local-only",
        "`outputs/mvp6-debug-console/`, which is ignored by the repository",
        "approval packets",
        "uploaded browser draft wav files",
        "manual debug",
        "ignored local-only path",
        "No realtime microphone streaming",
        "No full-duplex, AEC, or barge-in",
        "No real TTS",
        "No real Slow LLM",
        "No production demo UI claim",
        "No real external side-effect tool execution",
        "No new canonical event",
        "No new RouterDecision",
        "outputs/mvp6-debug-console/qa-history.jsonl",
        "QA history is local-only",
        "raw audio is not saved to QA history",
        "Provider request bodies",
        "provider response bodies",
        "prompt dumps",
        "local paths",
        "filenames",
        "secrets",
    )
    for phrase in required_phrases:
        assert phrase in normalized_doc


def test_mvp6_operating_doc_includes_command_and_approval_template() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    required_phrases = (
        "scripts/mvp6-debug-console",
        "--approval-packet outputs/mvp6-debug-console/approval.json",
        "--output-root outputs/mvp6-debug-console",
        "--host 127.0.0.1",
        "--port 8766",
        '"approval_id": "mvp6-local-debug-console-local"',
        '"live_provider_opt_in": true',
        '"local_wav_opt_in": true',
        '"metadata_only_output": true',
        '"replay_reruns_provider": false',
        '"provider_adapter_ids": ["mvp5_asr_adapter", "mvp63_fast_interaction_runtime"]',
        '"credential_env_var_name": "DASHSCOPE_API_KEY"',
        '"max_provider_calls": 2',
        '"timeout_ms": 1500',
        '"safe_output_ref": "summary://mvp6/debug-console/local"',
    )
    for phrase in required_phrases:
        assert phrase in doc


def test_mvp63_manual_doc_lists_all_acceptance_scenarios() -> None:
    doc = Path("docs/implementation/mvp6.3-live-fast-interaction-manual-debug.md").read_text(
        encoding="utf-8"
    )
    for scenario in MVP63_SCENARIOS:
        assert scenario in doc


def test_mvp63_live_fast_answer_pass_acceptance(tmp_path: Path) -> None:
    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-LIVE-FAST-ANSWER-PASS-001",
        route_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-acceptance-fast-answer-pass",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(),
        ),
    )
    metadata = result.to_metadata()

    assert metadata["router_decision"] == "FAST_ONLY"
    assert metadata["foreground_gate_decision"] == "passed"
    assert metadata["foreground_output_basis"] == "reply_candidate"
    assert "SLOWTASK_CREATED" not in metadata["event_names"]
    assert "USER_PATCH_RECEIVED" not in metadata["event_names"]
    _assert_acceptance_safe(metadata)


def test_mvp63_live_qa_parallel_acceptance(tmp_path: Path) -> None:
    captured_route: list[object] = []

    def on_fast_ready(partial_result: object, journal: object) -> object:
        route_result = run_mvp5_live_router_runner(
            partial_result,
            config=MVP5LiveRouterConfig(
                run_id="mvp63-acceptance-qa-parallel",
                expected_route="FAST_ONLY",
                fast_foreground_gate_context=_trusted_synthetic_gate_context(),
            ),
            journal=journal,
        )
        captured_route.append(route_result)
        return route_result

    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-LIVE-QA-PARALLEL-001",
        route_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        asr_observation=True,
        asr_transport=FakeAsrTransport(
            (
                FakeAsrProviderResponse.success(
                    asr_frame_ref="asr-frame://synthetic/mvp63/acceptance-qa",
                    text_ref="text://synthetic/mvp63/acceptance-qa",
                    audio_timestamps_ref=None,
                    streaming_status="unsupported_final_only",
                ),
            )
        ),
        on_fast_evidence_ready=on_fast_ready,
    )

    committed = _event(evidence.events, "FOREGROUND_OUTPUT_COMMITTED")
    asr_event = _event(evidence.events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    router_event = _event(evidence.events, "ROUTER_DECISION_EMITTED")
    assert committed["event_seq"] < asr_event["event_seq"]
    assert "asr_frame_event_id" not in router_event
    assert router_event["evidence_ref_policy"] == "preserve_fast_ref"
    assert evidence.fast_path_result is captured_route[0]
    assert evidence.asr_observation_status == "completed"
    assert evidence.fast_interaction_input_mode == "audio_native"
    replay = run_replay_fixture(_fixture_from_events(evidence.events))
    assert replay.result_status == "passed"
    assert replay.manifest.allowed_re_eval_components == ()
    _assert_acceptance_safe(evidence.to_metadata())


def test_mvp63_asr_failure_preserves_answer_acceptance(tmp_path: Path) -> None:
    def on_fast_ready(partial_result: object, journal: object) -> object:
        return run_mvp5_live_router_runner(
            partial_result,
            config=MVP5LiveRouterConfig(
                run_id="mvp63-acceptance-asr-failure",
                expected_route="FAST_ONLY",
                fast_foreground_gate_context=_trusted_synthetic_gate_context(),
            ),
            journal=journal,
        )

    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-LIVE-ASR-FAIL-ANSWER-PRESERVED-001",
        route_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        asr_observation=True,
        asr_transport=FakeAsrTransport(
            (FakeAsrProviderResponse.request_failure("provider_unavailable"),)
        ),
        on_fast_evidence_ready=on_fast_ready,
    )

    committed = _event(evidence.events, "FOREGROUND_OUTPUT_COMMITTED")
    asr_failure = next(
        event
        for event in evidence.events
        if event["event_name"] == "ADAPTER_REQUEST_FAILED"
        and event["adapter_type"] == "asr"
    )
    assert committed["event_seq"] < asr_failure["event_seq"]
    assert evidence.asr_observation_status == "failed"
    assert evidence.fast_path_result is not None
    _assert_acceptance_safe(evidence.to_metadata())


def test_mvp63_live_fast_timeout_fallback_acceptance(tmp_path: Path) -> None:
    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-LIVE-FAST-TIMEOUT-FALLBACK-001",
        route_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
        fast_transport=_FailingFastInteractionTransport(
            FastInteractionLiveTransportError(
                "provider response DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK",
                category="provider_timeout",
                failure_reasons=("provider_timeout",),
            )
        ),
    )
    metadata = evidence.to_metadata()
    event_names = metadata["event_names"]

    assert metadata["status"] == "evidence_failed"
    assert metadata["latency_debug"]["fast_interaction_timed_out"] is True
    assert "ADAPTER_REQUEST_FAILED" in event_names
    assert "FAST_INTERACTION_OUTPUT_EMITTED" not in event_names
    assert "FOREGROUND_OUTPUT_COMMITTED" not in event_names
    _assert_acceptance_safe(metadata)


def test_mvp63_live_slow_discard_template_acceptance(tmp_path: Path) -> None:
    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-LIVE-SLOW-DISCARD-TEMPLATE-001",
        route_decision_candidate="SPAWN_SLOW_TASK",
        foreground_act="ACK_SLOW",
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-acceptance-slow-discard-template",
            expected_route="SPAWN_SLOW_TASK",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(),
        ),
    )
    metadata = result.to_metadata()

    assert metadata["router_decision"] == "SPAWN_SLOW_TASK"
    assert metadata["foreground_gate_decision"] == "failed"
    assert metadata["foreground_output_basis"] == "template_ack"
    assert "FOREGROUND_OUTPUT_DISCARDED" in metadata["event_names"]
    assert "SLOWTASK_CREATED" in metadata["event_names"]
    _assert_acceptance_safe(metadata)


def test_mvp63_live_patch_discard_template_acceptance(tmp_path: Path) -> None:
    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-LIVE-PATCH-DISCARD-TEMPLATE-001",
        route_decision_candidate="PATCH_ACTIVE_SLOW_TASK",
        foreground_act="ACK_PATCH",
    )
    active_context = MVP5ActiveSlowTaskContext(
        task_id="task_mvp63_acceptance_active",
        current_plan_version=1,
        current_task_event_seq=4,
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-acceptance-patch-discard-template",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            active_task_context=active_context,
        ),
        journal=_active_task_authority_journal(evidence, active_context),
    )
    metadata = result.to_metadata()

    assert metadata["router_decision"] == "PATCH_ACTIVE_SLOW_TASK"
    assert metadata["foreground_gate_decision"] == "failed"
    assert metadata["foreground_output_basis"] == "template_clarify"
    assert metadata["status"] == "blocked_missing_thinker_patch_evidence"
    assert "FOREGROUND_OUTPUT_DISCARDED" in metadata["event_names"]
    assert "USER_PATCH_RECEIVED" not in metadata["event_names"]
    _assert_acceptance_safe(metadata)


def test_mvp63_replay_no_provider_rerun_acceptance(tmp_path: Path) -> None:
    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-REPLAY-NO-PROVIDER-RERUN-001",
        route_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-acceptance-replay-no-provider-rerun",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(),
        ),
    )
    fixture = _fixture_from_events(result.events)
    replay = run_replay_fixture(fixture)

    assert replay.result_status == "passed"
    assert result.to_metadata()["replay_reruns_provider"] is False
    _assert_acceptance_safe(fixture)


def test_mvp63_safety_export_acceptance(tmp_path: Path) -> None:
    evidence = _fast_evidence(
        tmp_path,
        scenario_id="MVP6.3-SAFETY-EXPORT-001",
        route_decision_candidate="FAST_ONLY",
        foreground_act="ANSWER",
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-acceptance-safety-export",
            expected_route="FAST_ONLY",
            fast_foreground_gate_context=_trusted_synthetic_gate_context(),
        ),
    )

    _assert_acceptance_safe(evidence.to_metadata())
    _assert_acceptance_safe(result.to_metadata())


def _trusted_synthetic_gate_context() -> FastForegroundGateContext:
    return FastForegroundGateContext(
        authority_mode="trusted_synthetic_eval",
        authority_binding_status="bound",
        interaction_state=None,
        interaction_state_ref=None,
        task_focus=None,
        task_focus_snapshot_ref=None,
        has_active_slowtask=False,
        active_task_id=None,
        active_slowtask_lifecycle=None,
        pending_confirmation=False,
        pending_confirmation_id=None,
        pending_confirmation_scope=None,
        capability_snapshot_ref="capability://mvp5/live-voice-evidence/provider-free",
        capability_health_status="ready",
        capability_output_mode="real",
        capability_verification_status="provider_free_verified",
        candidate_policy_decision=CandidatePolicyDecision.trusted_synthetic(),
        schema_valid=True,
        confidence_threshold=0.8,
    )


def _fast_evidence(
    tmp_path: Path,
    *,
    scenario_id: str,
    route_decision_candidate: str,
    foreground_act: str,
    fast_transport: object | None = None,
    asr_observation: bool = False,
    asr_transport: object | None = None,
    on_fast_evidence_ready: object | None = None,
):
    slug = _slug(scenario_id)
    wav_path = tmp_path / f"{slug}.wav"
    _write_wav_file(wav_path)
    return run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id=f"mvp63-acceptance-{slug}",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_fast_approval_packet(asr_observation=asr_observation),
            credential_env_var_name="MVP63_TEST_PROVIDER_KEY",
            requested_provider_calls=2 if asr_observation else 1,
            max_provider_calls=2 if asr_observation else 1,
            timeout_ms=1500,
            fast_interaction_enabled=True,
            audio_native_thinker_enabled=False,
            asr_observation_enabled=asr_observation,
            fast_interaction_timeout_ms=1500,
        ),
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=asr_transport or _ExplodingAsrTransport(),
        thinker_transport=_ExplodingThinkerTransport(),
        fast_interaction_transport=fast_transport
        or _FakeFastInteractionTransport(
            route_decision_candidate=route_decision_candidate,
            foreground_act=foreground_act,
        ),
        on_fast_evidence_ready=on_fast_evidence_ready,
    )


class _FakeFastInteractionTransport:
    def __init__(self, *, route_decision_candidate: str, foreground_act: str) -> None:
        self.route_decision_candidate = route_decision_candidate
        self.foreground_act = foreground_act

    def complete_audio_with_timing(self, **kwargs: object) -> FastInteractionProviderCompletion:
        assert str(kwargs["credential_value"]).startswith("DUMMY_TEST_CREDENTIAL")
        assert kwargs["timeout_ms"] == 1500
        return FastInteractionProviderCompletion(
            provider_text=json.dumps(
                {
                    "schema_name": "voice_agent.fast_interaction.output.v1",
                    "route_hint": {"router_decision_candidate": self.route_decision_candidate},
                    "route_prelude": {"summary": "acceptance route"},
                    "foreground_act": self.foreground_act,
                    "reply_candidate": "A tiny safe spooky story.",
                    "final_fast_evidence": {"label": "acceptance"},
                    "risk_tags": ["none"],
                    "risk_class": "LOW",
                    "confidence": 0.91,
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


class _FailingFastInteractionTransport:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def complete_audio_with_timing(self, **_kwargs: object) -> FastInteractionProviderCompletion:
        raise self._exc


class _ExplodingAsrTransport:
    def transcribe(self, **_kwargs: object) -> object:
        raise AssertionError("ASR must not run in MVP6.3 audio-native fast primary path")


class _ExplodingThinkerTransport:
    def complete_audio(self, **_kwargs: object) -> str:
        raise AssertionError("audio-native thinker must not run in MVP6.3 acceptance fast path")


def _fixture_from_events(events: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": "mvp63_acceptance_fast_replay",
            "source_trace_ref": "fixture://mvp63/acceptance/fast-replay",
            "replay_mode": "deterministic",
            "event_schema_version_range": ["1.0"],
            "fixture_domain": "GITHUB_ALLOWED",
            "generated_from": "synthetic",
            "contains_raw_audio": False,
            "contains_raw_trace": False,
            "contains_real_user_input": False,
            "contains_secrets": False,
            "contains_unredacted_tool_result": False,
            "contains_large_raw_web_content": False,
            "allowed_re_eval_components": [],
        },
        "events": [dict(event) for event in events],
    }


def _event(
    events: tuple[dict[str, object], ...],
    event_name: str,
) -> dict[str, object]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]


def _active_task_authority_journal(
    evidence: object,
    context: MVP5ActiveSlowTaskContext,
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
    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp63_acceptance_active_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(last["event_id"]),
        created_monotonic_ms=monotonic_ms + 1,
        created_wall_clock_ms=wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        task_id=context.task_id,
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp63/acceptance-active",
    )
    created_state = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp63_acceptance_active_created_state",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=monotonic_ms + 2,
        created_wall_clock_ms=wall_clock_ms + 2,
        trace_redaction_level="metadata_only",
        task_id=context.task_id,
        plan_version=1,
        task_event_seq=2,
        from_state="CREATED",
        to_state="CREATED",
        reason="trusted_synthetic_acceptance_authority",
    )
    planning = journal.append(
        event_name="PLANNING_STARTED",
        event_id="evt_mvp63_acceptance_active_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created_state["event_id"]),
        created_monotonic_ms=monotonic_ms + 3,
        created_wall_clock_ms=wall_clock_ms + 3,
        trace_redaction_level="metadata_only",
        task_id=context.task_id,
        plan_version=1,
        task_event_seq=3,
        planning_reason="trusted_synthetic_acceptance_authority",
    )
    journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp63_acceptance_active_planning_state",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning["event_id"]),
        created_monotonic_ms=monotonic_ms + 4,
        created_wall_clock_ms=wall_clock_ms + 4,
        trace_redaction_level="metadata_only",
        task_id=context.task_id,
        plan_version=1,
        task_event_seq=4,
        from_state="CREATED",
        to_state="PLANNING",
        reason="trusted_synthetic_acceptance_authority",
    )
    return journal


def _fast_approval_packet(*, asr_observation: bool = False) -> dict[str, object]:
    adapter_ids = ["mvp63_fast_interaction_runtime"]
    max_provider_calls = 1
    if asr_observation:
        adapter_ids = ["mvp5_asr_adapter", "mvp63_fast_interaction_runtime"]
        max_provider_calls = 2
    return {
        "approval_id": "mvp63-acceptance-fast-interaction",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": adapter_ids,
        "credential_env_var_name": "MVP63_TEST_PROVIDER_KEY",
        "max_provider_calls": max_provider_calls,
        "timeout_ms": 1500,
        "safe_output_ref": "summary://mvp63/acceptance/fast-interaction",
    }


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


def _assert_acceptance_safe(value: object) -> None:
    rendered = json.dumps(value, sort_keys=True)
    for unsafe in (
        '"raw_audio":',
        "raw_audio_bytes",
        '"provider_body":',
        '"provider_request":',
        '"provider_response":',
        '"prompt_dump":',
        "provider body",
        "provider request",
        "provider response",
        "prompt dump",
        "DUMMY_TEST_CREDENTIAL",
        "diagnostics/",
        "traces/",
        "replays/local/",
        "/Users/",
        "/private/",
        "A tiny safe spooky story.",
    ):
        assert unsafe not in rendered


def _write_wav_file(path: Path) -> bytes:
    frames = b"\x00\x00" * 160
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(frames)
    return path.read_bytes()


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
