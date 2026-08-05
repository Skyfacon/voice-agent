from __future__ import annotations

from typing import Any

import pytest

from voice_agent.access.audio_ingress import (
    receive_audio_span_end,
    receive_audio_span_start,
)
from voice_agent.adapters.qwen_realtime.profile import (
    build_qwen_realtime_asr_fake_profile,
)
from voice_agent.adapters.route_evidence_contract import (
    RouteEvidenceOutputV1,
    RouteEvidenceRequestV1,
    emit_route_evidence_output_event,
)
from voice_agent.duplex.mock_duplex import MockDuplexRuleGate
from voice_agent.interaction.controller import InteractionController
from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
)
from voice_agent.runtime.session import start_mvp0_session


def _active_snapshot() -> TaskFocusSnapshot:
    return TaskFocusSnapshot(
        active_task_id="task_slice3b1_active_001",
        lifecycle_phase="PLANNING",
        current_plan_version=2,
    )


def _route_case(
    suffix: str,
    *,
    route_hint: str = "FAST_ONLY",
    task_focus_hint: str = "FOREGROUND_CHAT",
    active_task: bool = False,
    asr_output_mode: str = "real",
    route_output_mode: str = "real",
    route_before_asr: bool = False,
    asr_correlation_overrides: dict[str, Any] | None = None,
    route_extra_fields: dict[str, Any] | None = None,
    projection_includes_asr: bool = True,
    projection_source_event_seq_override: int | None = None,
    route_caused_by_projection: bool = True,
    route_context_is_projection: bool = True,
    use_canonical_emitter: bool = False,
) -> tuple[
    Any,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    RouterContext,
]:
    startup = start_mvp0_session(
        session_id=f"sess_adr018_router_{suffix}",
        conversation_id=f"conv_adr018_router_{suffix}",
        runtime_config_ref="config://synthetic/slice3b1/router",
        created_monotonic_ms=100,
        created_wall_clock_ms=1_700_000_000_100,
    )
    journal = startup.journal
    audio_span_id = f"audio_adr018_router_{suffix}"
    turn_id = f"turn_adr018_router_{suffix}"
    utterance_id = f"utt_adr018_router_{suffix}"
    audio_started = receive_audio_span_start(
        journal,
        event_id=f"evt_adr018_router_{suffix}_audio_started",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=110,
        created_wall_clock_ms=1_700_000_000_110,
        audio_span_id=audio_span_id,
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/pcm16-mono-24000",
    )
    duplex = MockDuplexRuleGate(journal)
    speech_started = duplex.record_speech_start(
        audio_started,
        event_id=f"evt_adr018_router_{suffix}_speech_started",
        created_monotonic_ms=111,
        created_wall_clock_ms=1_700_000_000_111,
        audio_sample_offset=0,
        vad_confidence=0.99,
    )
    controller = InteractionController(journal)
    controller.open_audio_turn(
        speech_started,
        turn_id=turn_id,
        created_monotonic_ms=112,
        created_wall_clock_ms=1_700_000_000_112,
    )
    audio_ended = receive_audio_span_end(
        journal,
        event_id=f"evt_adr018_router_{suffix}_audio_ended",
        caused_by_event_id=str(audio_started["event_id"]),
        created_monotonic_ms=120,
        created_wall_clock_ms=1_700_000_000_120,
        audio_span_id=audio_span_id,
        audio_sample_offset=24_000,
        duration_ms=1_000,
        end_reason="synthetic_complete",
    )
    speech_ended = duplex.record_speech_end(
        audio_ended,
        event_id=f"evt_adr018_router_{suffix}_speech_ended",
        created_monotonic_ms=121,
        created_wall_clock_ms=1_700_000_000_121,
        audio_sample_offset=24_000,
        vad_confidence=0.99,
        silence_duration_ms=240,
    )
    turn_committed = controller.commit_audio_ingress(
        speech_ended,
        turn_id=turn_id,
        utterance_id=utterance_id,
        created_monotonic_ms=122,
        created_wall_clock_ms=1_700_000_000_122,
    ).turn_committed

    qwen_profile = build_qwen_realtime_asr_fake_profile()
    asr_fields: dict[str, Any] = {}
    if asr_output_mode == "mock":
        asr_fields.update(
            provider_session_generation=1,
            qwen_input_item_ref=f"qwen-input-item://synthetic/{suffix}",
            qwen_input_content_index=0,
        )
    if asr_correlation_overrides is not None:
        asr_fields.update(asr_correlation_overrides)
    asr_event_id = f"evt_adr018_router_{suffix}_asr"
    projection_event_id = f"evt_adr018_router_{suffix}_route_context"

    def append_asr() -> dict[str, Any]:
        return journal.append(
            event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
            event_id=asr_event_id,
            source_module="asr_adapter",
            caused_by_event_id=str(turn_committed["event_id"]),
            created_monotonic_ms=130,
            created_wall_clock_ms=1_700_000_000_130,
            trace_redaction_level="metadata_only",
            adapter_id=(
                qwen_profile.adapter_id if asr_output_mode == "mock" else "mvp3_asr"
            ),
            adapter_type="asr",
            adapter_request_id=f"asr_request_adr018_router_{suffix}",
            turn_id=turn_id,
            utterance_id=utterance_id,
            input_modality="audio",
            audio_span_id=audio_span_id,
            asr_frame_ref=f"asr-frame://synthetic/adr018/router/{suffix}",
            text_ref=f"text-ref://synthetic/adr018/router/{suffix}",
            transcript_finality="final",
            timestamp_status="available",
            streaming_status="supported",
            output_mode=asr_output_mode,
            **asr_fields,
        )

    def append_projection(
        *,
        caused_by_event_id: str,
        source_event_seq: int,
    ) -> dict[str, Any]:
        return journal.append(
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
            event_id=projection_event_id,
            source_module="context_assembler",
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=135,
            created_wall_clock_ms=1_700_000_000_135,
            trace_redaction_level="metadata_only",
            projection_id=f"projection_adr018_router_{suffix}",
            target_role="route_evidence",
            source_event_ids=(
                (asr_event_id,)
                if projection_includes_asr
                else (str(turn_committed["event_id"]),)
            ),
            context_snapshot_id=f"context_snapshot_adr018_router_{suffix}",
            source_event_seq=(
                projection_source_event_seq_override
                if projection_source_event_seq_override is not None
                else source_event_seq
            ),
            provider_session_generation=1,
            projection_ref=f"context-projection://synthetic/adr018/router/{suffix}",
            policy_version="context_projection.synthetic.v1",
            redaction_status="metadata_only",
            output_mode="mock",
        )

    def append_route(
        *,
        caused_by_event_id: str,
        context_projection_event: dict[str, Any],
    ) -> dict[str, Any]:
        if use_canonical_emitter:
            if route_before_asr:
                raise AssertionError(
                    "canonical Route Evidence requires the final ASR predecessor"
                )
            return emit_route_evidence_output_event(
                boundary=AdapterCallbackAppendBoundary(journal),
                adapter_id="slice3b1_route_evidence_fake",
                request=RouteEvidenceRequestV1(
                    adapter_request_id=f"route_request_adr018_router_{suffix}",
                    turn_id=turn_id,
                    utterance_id=utterance_id,
                    final_asr_event_id=asr_event_id,
                    transcript_ref=str(asr_event["text_ref"]),
                    asr_confidence=None,
                    duplex_hints_ref=None,
                    qwen_semantic_hints_ref=None,
                    context_projection_event_id=str(
                        context_projection_event["event_id"]
                    ),
                    context_snapshot_id=str(
                        context_projection_event["context_snapshot_id"]
                    ),
                    active_task_public_snapshot_ref=None,
                    last_assistant_act="ANSWER",
                    expected_user_response="FREE_FORM",
                    policy_version="route_evidence.fake.v1",
                ),
                output=RouteEvidenceOutputV1(
                    route_hint=route_hint,
                    task_focus_hint=task_focus_hint,
                    foreground_act_hint="ANSWER",
                    ack_kind="CHAT",
                    risk_class="LOW",
                    risk_tags=(),
                    evidence_uncertainty="LOW",
                    confidence=0.93,
                ),
                final_asr_event=asr_event,
                context_projection_event=context_projection_event,
                event_id=f"evt_adr018_router_{suffix}_route_evidence",
                created_monotonic_ms=140,
                created_wall_clock_ms=1_700_000_000_140,
            )
        return journal.append(
            event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
            event_id=f"evt_adr018_router_{suffix}_route_evidence",
            source_module="route_evidence_adapter",
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=140,
            created_wall_clock_ms=1_700_000_000_140,
            trace_redaction_level="metadata_only",
            adapter_id="slice3b1_route_evidence_fake",
            adapter_type="route_evidence",
            adapter_request_id=f"route_request_adr018_router_{suffix}",
            adapter_callback_seq=1,
            turn_id=turn_id,
            utterance_id=utterance_id,
            final_asr_event_id=asr_event_id,
            context_projection_event_id=str(context_projection_event["event_id"]),
            context_snapshot_id=f"context_snapshot_adr018_router_{suffix}",
            provider_session_generation=1,
            route_hint=route_hint,
            task_focus_hint=task_focus_hint,
            foreground_act_hint="ANSWER",
            ack_kind="CHAT",
            risk_class="LOW",
            risk_tags=(),
            evidence_uncertainty="LOW",
            confidence=0.93,
            schema_name="voice_agent.route_evidence.output.v1",
            normalization_status="normalized",
            output_mode=route_output_mode,
            **(route_extra_fields or {}),
        )

    if route_before_asr:
        projection_event = append_projection(
            caused_by_event_id=str(turn_committed["event_id"]),
            source_event_seq=int(turn_committed["event_seq"]),
        )
        route_event = append_route(
            caused_by_event_id=str(projection_event["event_id"]),
            context_projection_event=projection_event,
        )
        asr_event = append_asr()
    else:
        asr_event = append_asr()
        projection_event = append_projection(
            caused_by_event_id=str(asr_event["event_id"]),
            source_event_seq=int(asr_event["event_seq"]),
        )
        route_event = append_route(
            caused_by_event_id=(
                str(projection_event["event_id"])
                if route_caused_by_projection
                else str(asr_event["event_id"])
            ),
            context_projection_event=(
                projection_event if route_context_is_projection else asr_event
            ),
        )
    context = RouterContext(
        task_focus_snapshot=_active_snapshot() if active_task else TaskFocusSnapshot()
    )
    return startup, turn_committed, asr_event, route_event, context


def _emit_route_decision(
    case: tuple[
        Any,
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        RouterContext,
    ],
    *,
    asr_event: dict[str, Any] | None = None,
    route_event: dict[str, Any] | None = None,
    thinker_event: dict[str, Any] | None = None,
    fast_event: dict[str, Any] | None = None,
):
    startup, turn_committed, canonical_asr, canonical_route, context = case
    return MVP1Router(startup.journal).emit_decision(
        turn_committed_event=turn_committed,
        asr_frame_event=canonical_asr if asr_event is None else asr_event,
        thinker_frame_event=thinker_event,
        fast_interaction_output_event=fast_event,
        route_evidence_output_event=(
            canonical_route if route_event is None else route_event
        ),
        router_context=context,
        event_id=f"evt_{turn_committed['turn_id']}_router_decision",
        task_focus_state_event_id=f"evt_{turn_committed['turn_id']}_focus_state",
        created_monotonic_ms=150,
        created_wall_clock_ms=1_700_000_000_150,
    )


@pytest.mark.parametrize(
    (
        "route_hint",
        "task_focus_hint",
        "active_task",
        "expected_route",
        "expected_focus",
    ),
    (
        ("FAST_ONLY", "FOREGROUND_CHAT", False, "FAST_ONLY", "FOREGROUND_CHAT"),
        (
            "SPAWN_SLOW_TASK",
            "NEW_TASK_CANDIDATE",
            False,
            "SPAWN_SLOW_TASK",
            "NEW_TASK_CANDIDATE",
        ),
        ("IGNORE", "NON_ASSISTANT", False, "IGNORE", "NON_ASSISTANT"),
        ("FAST_ONLY", "FOREGROUND_CHAT", True, "FAST_ONLY", "FOREGROUND_CHAT"),
        (
            "PATCH_ACTIVE_SLOW_TASK",
            "ACTIVE_TASK_PATCH",
            True,
            "PATCH_ACTIVE_SLOW_TASK",
            "ACTIVE_TASK_PATCH",
        ),
        (
            "PATCH_ACTIVE_SLOW_TASK",
            "NEW_TASK_CANDIDATE",
            True,
            "PATCH_ACTIVE_SLOW_TASK",
            "NEW_TASK_CANDIDATE",
        ),
        (
            "PATCH_ACTIVE_SLOW_TASK",
            "CANCEL_OR_PAUSE_CANDIDATE",
            True,
            "PATCH_ACTIVE_SLOW_TASK",
            "CANCEL_OR_PAUSE_CANDIDATE",
        ),
        ("FAST_ONLY", "AMBIGUOUS", True, "FAST_ONLY", "AMBIGUOUS"),
    ),
)
def test_route_evidence_branch_keeps_local_router_authoritative(
    route_hint: str,
    task_focus_hint: str,
    active_task: bool,
    expected_route: str,
    expected_focus: str,
) -> None:
    suffix = (
        f"{route_hint.lower()}_{task_focus_hint.lower()}_"
        f"{'active' if active_task else 'idle'}"
    )
    case = _route_case(
        suffix,
        route_hint=route_hint,
        task_focus_hint=task_focus_hint,
        active_task=active_task,
    )

    result = _emit_route_decision(case)
    router_event = result.router_decision_event
    route_event = case[3]

    assert router_event["router_decision"] == expected_route
    assert router_event["task_focus"] == expected_focus
    assert router_event["confidence"] == 0.93
    assert router_event["evidence_uncertainty"] == "LOW"
    assert router_event["caused_by_event_id"] == route_event["event_id"]
    assert router_event["route_evidence_event_id"] == route_event["event_id"]
    assert router_event["asr_frame_event_id"] == case[2]["event_id"]
    assert router_event["evidence_ref_policy"] == (
        "preserve_asr_and_route_evidence_refs"
    )
    assert "thinker_frame_event_id" not in router_event
    assert "fast_interaction_output_event_id" not in router_event
    assert all("candidate" not in field.lower() for field in router_event)


def test_route_hint_must_match_the_route_locally_derived_from_task_focus() -> None:
    case = _route_case(
        "contradictory_route_hint",
        route_hint="SPAWN_SLOW_TASK",
        task_focus_hint="FOREGROUND_CHAT",
    )

    with pytest.raises(ValueError, match="route_hint.*local Router"):
        _emit_route_decision(case)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("event_name", "FAST_INTERACTION_OUTPUT_EMITTED", "ROUTE_EVIDENCE"),
        ("turn_id", "turn_other", "turn_id"),
        ("utterance_id", "utterance_other", "utterance_id"),
        ("final_asr_event_id", "evt_asr_other", "final_asr_event_id"),
        ("adapter_type", "fast_interaction", "adapter_type=route_evidence"),
        ("normalization_status", "provider_raw", "normalized"),
        ("schema_name", "provider.route.raw.v1", "route_evidence.output.v1"),
        ("output_mode", "unknown", "output_mode"),
        ("route_hint", "REPLACE_TASK", "route_hint"),
        ("task_focus_hint", "REWRITE_GOAL", "task_focus_hint"),
    ),
)
def test_route_evidence_branch_rejects_noncanonical_or_mismatched_evidence(
    field: str,
    replacement: object,
    message: str,
) -> None:
    case = _route_case(f"invalid_route_{field}")
    bad_route = dict(case[3], **{field: replacement})

    with pytest.raises(ValueError, match=message):
        _emit_route_decision(case, route_event=bad_route)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("event_name", "MOCK_ASR_FRAME_EMITTED", "ASR_TRANSCRIPT_OUTPUT_EMITTED"),
        ("turn_id", "turn_other", "turn_id"),
        ("utterance_id", "utterance_other", "utterance_id"),
        ("caused_by_event_id", "evt_other", "TURN_INGRESS_COMMITTED"),
        ("transcript_finality", "partial", "final"),
    ),
)
def test_route_evidence_branch_requires_matching_canonical_final_asr(
    field: str,
    replacement: object,
    message: str,
) -> None:
    case = _route_case(f"invalid_asr_{field}")
    bad_asr = dict(case[2], **{field: replacement})

    with pytest.raises(ValueError, match=message):
        _emit_route_decision(case, asr_event=bad_asr)


def test_route_evidence_branch_requires_asr_evidence() -> None:
    case = _route_case("missing_asr")
    startup, turn_committed, _asr_event, route_event, context = case

    with pytest.raises(ValueError, match="final ASR"):
        MVP1Router(startup.journal).emit_decision(
            turn_committed_event=turn_committed,
            route_evidence_output_event=route_event,
            router_context=context,
            event_id="evt_adr018_router_missing_asr_decision",
            task_focus_state_event_id="evt_adr018_router_missing_asr_focus",
            created_monotonic_ms=150,
            created_wall_clock_ms=1_700_000_000_150,
        )


@pytest.mark.parametrize("forged_predecessor", ("asr", "route_evidence"))
def test_route_evidence_branch_rejects_forged_copies_of_journaled_predecessors(
    forged_predecessor: str,
) -> None:
    case = _route_case(f"forged_{forged_predecessor}")
    if forged_predecessor == "asr":
        forged_asr = dict(
            case[2],
            text_ref="text://synthetic/adr018/router/forged-caller-copy",
        )
        forged_route = case[3]
    else:
        forged_asr = case[2]
        forged_route = dict(
            case[3],
            route_hint="SPAWN_SLOW_TASK",
            task_focus_hint="NEW_TASK_CANDIDATE",
            foreground_act_hint="ACK_SLOW",
            ack_kind="PLAN_ACCEPTED",
            confidence=0.51,
        )

    with pytest.raises(ValueError, match="exactly match.*journal"):
        _emit_route_decision(
            case,
            asr_event=forged_asr,
            route_event=forged_route,
        )


def test_route_evidence_branch_requires_asr_to_precede_route_evidence() -> None:
    case = _route_case("route_before_asr", route_before_asr=True)

    with pytest.raises(ValueError, match="final ASR.*precede Route Evidence"):
        _emit_route_decision(case)


@pytest.mark.parametrize(
    ("suffix", "case_kwargs", "message"),
    (
        (
            "projection_missing_asr",
            {"projection_includes_asr": False},
            "source_event_ids.*final ASR",
        ),
        (
            "route_not_caused_by_projection",
            {"route_caused_by_projection": False},
            "caused_by_event_id.*context projection",
        ),
        (
            "projection_snapshot_before_asr",
            {"projection_source_event_seq_override": 1},
            "source_event_seq.*final ASR",
        ),
        (
            "route_context_ref_is_asr",
            {"route_context_is_projection": False},
            "MODEL_CONTEXT_PROJECTION_EMITTED",
        ),
    ),
)
def test_route_evidence_branch_validates_context_projection_predecessor(
    suffix: str,
    case_kwargs: dict[str, object],
    message: str,
) -> None:
    case = _route_case(suffix, **case_kwargs)

    with pytest.raises(ValueError, match=message):
        _emit_route_decision(case)


@pytest.mark.parametrize(
    "candidate_field",
    (
        "candidate_ref",
        "candidate_transcript_digest",
        "reply_candidate",
        "reply_delta_stream_ref",
    ),
)
def test_route_evidence_branch_rejects_candidate_fields(
    candidate_field: str,
) -> None:
    case = _route_case(f"candidate_field_{candidate_field}")
    bad_route = dict(
        case[3],
        **{candidate_field: f"candidate://synthetic/forbidden/{candidate_field}"},
    )

    with pytest.raises(ValueError, match="candidate"):
        _emit_route_decision(case, route_event=bad_route)


@pytest.mark.parametrize(
    "unknown_payload_field",
    ("reply_text", "response_delta", "transcript", "pcm"),
)
def test_route_evidence_branch_rejects_noncanonical_payload_fields(
    unknown_payload_field: str,
) -> None:
    case = _route_case(
        f"unknown_payload_{unknown_payload_field}",
        route_extra_fields={
            unknown_payload_field: (
                f"opaque://synthetic/forbidden/{unknown_payload_field}"
            )
        },
    )

    with pytest.raises(ValueError, match="unsupported field"):
        _emit_route_decision(case)


@pytest.mark.parametrize("legacy_branch", ("thinker", "fast_interaction"))
def test_route_evidence_branch_is_mutually_exclusive_with_legacy_evidence(
    legacy_branch: str,
) -> None:
    case = _route_case(f"exclusive_{legacy_branch}")
    turn_committed = case[1]
    if legacy_branch == "thinker":
        thinker_event = {
            "event_name": "MOCK_THINKER_FRAME_EMITTED",
            "event_id": f"evt_exclusive_{legacy_branch}",
            "turn_id": turn_committed["turn_id"],
            "utterance_id": turn_committed["utterance_id"],
            "caused_by_event_id": turn_committed["event_id"],
            "output_mode": "mock",
        }
        fast_event = None
    else:
        thinker_event = None
        fast_event = {
            "event_name": "FAST_INTERACTION_OUTPUT_EMITTED",
            "event_id": f"evt_exclusive_{legacy_branch}",
            "turn_id": turn_committed["turn_id"],
            "utterance_id": turn_committed["utterance_id"],
            "caused_by_event_id": turn_committed["event_id"],
            "input_mode": "audio_native",
            "adapter_type": "fast_interaction",
            "normalization_status": "normalized",
            "output_mode": "real",
        }

    with pytest.raises(ValueError, match="mutually exclusive"):
        _emit_route_decision(
            case,
            thinker_event=thinker_event,
            fast_event=fast_event,
        )


def test_provider_free_qwen_mock_asr_is_accepted_only_for_mock_route_evidence() -> None:
    case = _route_case(
        "qwen_mock_happy",
        asr_output_mode="mock",
        route_output_mode="mock",
    )

    result = _emit_route_decision(case)

    assert result.router_decision_event["router_decision"] == "FAST_ONLY"
    assert result.router_decision_event["route_evidence_event_id"] == case[3]["event_id"]


def test_canonical_route_evidence_emitter_output_is_accepted_by_router() -> None:
    case = _route_case(
        "canonical_emitter_to_router",
        asr_output_mode="mock",
        route_output_mode="mock",
        use_canonical_emitter=True,
    )
    route_event = case[3]

    result = _emit_route_decision(case)

    assert route_event["adapter_callback_seq"] == 1
    assert route_event["context_snapshot_id"] == (
        "context_snapshot_adr018_router_canonical_emitter_to_router"
    )
    assert route_event["provider_session_generation"] == 1
    assert result.router_decision_event["caused_by_event_id"] == route_event["event_id"]
    assert result.router_decision_event["route_evidence_event_id"] == (
        route_event["event_id"]
    )


@pytest.mark.parametrize(
    "missing_field",
    (
        "provider_session_generation",
        "qwen_input_item_ref",
        "qwen_input_content_index",
    ),
)
def test_provider_free_qwen_mock_asr_requires_every_correlation_field(
    missing_field: str,
) -> None:
    case = _route_case(
        f"qwen_mock_missing_{missing_field}",
        asr_output_mode="mock",
        route_output_mode="mock",
    )
    bad_asr = dict(case[2])
    bad_asr.pop(missing_field)

    with pytest.raises(ValueError, match=missing_field):
        _emit_route_decision(case, asr_event=bad_asr)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("provider_session_generation", False),
        ("provider_session_generation", 0),
        ("qwen_input_item_ref", 7),
        ("qwen_input_content_index", False),
        ("qwen_input_content_index", -1),
    ),
)
def test_provider_free_qwen_mock_asr_requires_typed_correlation_fields(
    field: str,
    invalid_value: object,
) -> None:
    case = _route_case(
        f"qwen_mock_invalid_{field}_{invalid_value!s}",
        asr_output_mode="mock",
        route_output_mode="mock",
        asr_correlation_overrides={field: invalid_value},
    )

    with pytest.raises(ValueError, match=field):
        _emit_route_decision(case)


def test_provider_free_qwen_mock_asr_requires_assembled_profile_adapter_id() -> None:
    case = _route_case(
        "qwen_mock_wrong_adapter",
        asr_output_mode="mock",
        route_output_mode="mock",
    )
    bad_asr = dict(case[2], adapter_id="some_other_mock_asr")

    with pytest.raises(ValueError, match="provider-free Qwen ASR profile"):
        _emit_route_decision(case, asr_event=bad_asr)


@pytest.mark.parametrize(
    ("route_field", "replacement", "message"),
    (
        ("output_mode", "real", "output_mode=mock"),
        ("normalization_status", "provider_raw", "normalized"),
    ),
)
def test_provider_free_qwen_mock_asr_requires_normalized_mock_route_evidence(
    route_field: str,
    replacement: str,
    message: str,
) -> None:
    case = _route_case(
        f"qwen_mock_bad_route_{route_field}",
        asr_output_mode="mock",
        route_output_mode="mock",
    )
    bad_route = dict(case[3], **{route_field: replacement})

    with pytest.raises(ValueError, match=message):
        _emit_route_decision(case, route_event=bad_route)


@pytest.mark.parametrize("legacy_branch", ("thinker", "fast_interaction"))
def test_provider_free_qwen_mock_asr_remains_rejected_by_legacy_router_branches(
    legacy_branch: str,
) -> None:
    case = _route_case(
        f"qwen_mock_legacy_{legacy_branch}",
        asr_output_mode="mock",
        route_output_mode="mock",
    )
    startup, turn_committed, asr_event, _route_event, context = case
    common = {
        "event_id": f"evt_adr018_qwen_mock_legacy_{legacy_branch}_decision",
        "task_focus_state_event_id": (
            f"evt_adr018_qwen_mock_legacy_{legacy_branch}_focus"
        ),
        "created_monotonic_ms": 150,
        "created_wall_clock_ms": 1_700_000_000_150,
    }
    if legacy_branch == "thinker":
        branch_fields = {
            "thinker_frame_event": {
                "event_name": "MOCK_THINKER_FRAME_EMITTED",
                "event_id": "evt_adr018_qwen_mock_legacy_thinker",
                "turn_id": turn_committed["turn_id"],
                "utterance_id": turn_committed["utterance_id"],
                "caused_by_event_id": turn_committed["event_id"],
                "output_mode": "mock",
            }
        }
    else:
        branch_fields = {
            "fast_interaction_output_event": {
                "event_name": "FAST_INTERACTION_OUTPUT_EMITTED",
                "event_id": "evt_adr018_qwen_mock_legacy_fast",
                "turn_id": turn_committed["turn_id"],
                "utterance_id": turn_committed["utterance_id"],
                "caused_by_event_id": turn_committed["event_id"],
                "input_mode": "audio_native",
                "adapter_type": "fast_interaction",
                "normalization_status": "normalized",
                "output_mode": "real",
            }
        }

    with pytest.raises(ValueError, match="output_mode"):
        MVP1Router(startup.journal).emit_decision(
            turn_committed_event=turn_committed,
            asr_frame_event=asr_event,
            router_context=context,
            **branch_fields,
            **common,
        )
