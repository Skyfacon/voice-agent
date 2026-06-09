from __future__ import annotations

import http.client
from pathlib import Path
import random
import socket
import time
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.thinker_contract import ThinkerAdapterContract
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session
from voice_agent.understanding.mock_asr import emit_mock_asr_frame
from voice_agent.user_patch.evidence_pack import construct_user_patch_evidence_pack
from voice_agent.user_patch.evidence_pack import UserPatchEvidencePackRuntime


SPEC_PATH = Path("docs/specs/mvp3-acceptance-scenarios.md")
THINKER_OUTPUT_EVENT_NAME = "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"


def test_mvp3_thinker_contract_spec_names_slice5_contract() -> None:
    thinker_section = SPEC_PATH.read_text(encoding="utf-8").split(
        "## Scenario MVP3-THINKER-CONTRACT-001",
        maxsplit=1,
    )[1].split("## Scenario", maxsplit=1)[0]

    for required_text in (
        "Thinker structured SemanticFrame-compatible output contract",
        "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        "Output is normalized before Router/SlowTask use",
        "missing optional semantic fields degrade explicitly",
        "Replay uses recorded refs only",
        "No provider-specific schema leakage into Router or SlowTask",
    ):
        assert required_text in thinker_section


def test_thinker_semantic_frame_contract_emits_normalized_refs_and_degradation_events_without_provider_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = _start_mvp3_thinker_contract_session()
    committed_turn = _append_committed_text_turn(startup.journal)
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    blocked_calls = _block_provider_runtime(monkeypatch)

    contract = ThinkerAdapterContract(
        boundary=boundary,
        adapter_id="mvp3_thinker",
        output_mode="degraded",
    )

    emission = contract.emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_semantic_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_slice5_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/semantic-frame-001",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/semantic-summary-001",
        semantic_close_ref=None,
        assistant_directedness_ref=None,
        emotion_ref=None,
        audio_caption_ref=None,
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
        focus_confidence=0.86,
        evidence_uncertainty="high",
    )

    events = startup.journal.events()
    emitted = events[-5:]
    thinker = emission.thinker_event

    assert [event["event_name"] for event in emitted] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        THINKER_OUTPUT_EVENT_NAME,
    ]
    assert emission.degraded_events == tuple(emitted[:4])
    assert thinker == emitted[4]
    assert [event["event_seq"] for event in emitted] == [7, 8, 9, 10, 11]
    assert [event["adapter_callback_seq"] for event in emitted] == [1, 2, 3, 4, 5]
    assert [event["missing_capability"] for event in emitted[:4]] == [
        "supports_semantic_close",
        "supports_assistant_directedness",
        "supports_emotion",
        "supports_audio_caption",
    ]
    assert {event["output_mode"] for event in emitted} == {"degraded"}

    assert thinker["adapter_id"] == "mvp3_thinker"
    assert thinker["adapter_type"] == "thinker"
    assert thinker["turn_id"] == committed_turn["turn_id"]
    assert thinker["utterance_id"] == committed_turn["utterance_id"]
    assert thinker["input_modality"] == "text"
    assert thinker["adapter_request_id"] == "adapter_request_mvp3_thinker_slice5_001"
    assert thinker["semantic_frame_schema"] == "voice_agent.semantic_frame.v1"
    assert thinker["normalization_status"] == "normalized"
    assert thinker["semantic_frame_ref"] == "semantic-frame://synthetic/mvp3/slice5/semantic-frame-001"
    assert thinker["semantic_summary_ref"] == "summary://synthetic/mvp3/slice5/semantic-summary-001"
    assert thinker["semantic_close_status"] == "unavailable"
    assert thinker["assistant_directedness_status"] == "unavailable"
    assert thinker["emotion_status"] == "unavailable"
    assert thinker["audio_caption_status"] == "unavailable"
    assert "semantic_close" not in thinker
    assert "assistant_directedness" not in thinker
    assert "emotion" not in thinker
    assert "audio_caption" not in thinker
    assert "provider_response" not in thinker
    assert "provider_schema" not in thinker

    assert all(validate_event_envelope(event) == event for event in emitted)
    assert _forbidden_payload_terms_are_absent(events)

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": events,
        }
    )

    assert replay_result.result_status == "passed"
    assert replay_result.adapter_health_state.output_event_modes[thinker["event_id"]] == "degraded"
    assert replay_result.adapter_health_state.adapters["mvp3_thinker"].missing_capabilities == (
        "supports_assistant_directedness",
        "supports_audio_caption",
        "supports_emotion",
        "supports_semantic_close",
    )
    assert {
        "event_id": thinker["event_id"],
        "field": "semantic_frame_ref",
        "ref": "semantic-frame://synthetic/mvp3/slice5/semantic-frame-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert {
        "event_id": thinker["event_id"],
        "field": "semantic_summary_ref",
        "ref": "summary://synthetic/mvp3/slice5/semantic-summary-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert blocked_calls == []


def test_replay_accepts_router_decision_referencing_real_thinker_semantic_frame_output() -> None:
    startup = _start_mvp3_thinker_contract_session(session_id="sess_mvp3_slice5_thinker_router_synthetic")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_mvp3_slice5_thinker_router",
    )
    contract = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    )
    emission = contract.emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_router_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_router_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/router-frame-001",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/router-summary-001",
        semantic_close_ref="semantic-close://synthetic/mvp3/slice5/router-closed",
        assistant_directedness_ref="assistant-directedness://synthetic/mvp3/slice5/router-directed",
        emotion_ref="emotion://synthetic/mvp3/slice5/router-calm",
        audio_caption_ref="audio-caption://synthetic/mvp3/slice5/router-caption",
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
        focus_confidence=0.9,
        evidence_uncertainty="low",
    )
    router_event = startup.journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id="evt_mvp3_slice5_thinker_router_decision",
        source_module="router",
        caused_by_event_id=str(emission.thinker_event["event_id"]),
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
        trace_redaction_level="metadata_only",
        turn_id=str(committed_turn["turn_id"]),
        utterance_id=str(committed_turn["utterance_id"]),
        router_decision="SPAWN_SLOW_TASK",
        task_focus="NEW_TASK_CANDIDATE",
        confidence=0.9,
        evidence_uncertainty="low",
        turn_committed_event_id=str(committed_turn["event_id"]),
        thinker_frame_event_id=str(emission.thinker_event["event_id"]),
    )

    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert result.task_focus_state.last_focus_event_id == router_event["event_id"]
    assert result.adapter_health_state.output_event_modes[emission.thinker_event["event_id"]] == "real"


def test_mvp1_router_consumes_normalized_real_thinker_metadata_without_provider_schema() -> None:
    startup = _start_mvp3_thinker_contract_session(session_id="sess_mvp3_slice5_thinker_router_runtime_synthetic")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_mvp3_slice5_thinker_router_runtime",
    )
    asr_event = emit_mock_asr_frame(
        startup.journal,
        committed_turn,
        event_id="evt_mvp3_slice5_thinker_router_runtime_mock_asr",
        created_monotonic_ms=205,
        created_wall_clock_ms=1700000000205,
        asr_frame_ref="asr-frame://synthetic/mvp3/slice5/router-runtime",
    )
    emission = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    ).emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_router_runtime_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_router_runtime_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/router-runtime",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/router-runtime",
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
        focus_confidence=0.88,
        evidence_uncertainty="low",
        **_available_optional_refs(),
    )

    result = MVP1Router(startup.journal).emit_decision(
        turn_committed_event=committed_turn,
        asr_frame_event=asr_event,
        thinker_frame_event=emission.thinker_event,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        event_id="evt_mvp3_slice5_thinker_router_runtime_decision",
        task_focus_state_event_id="evt_mvp3_slice5_thinker_router_runtime_focus_state",
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
    )

    router_event = result.router_decision_event
    assert router_event["router_decision"] == "SPAWN_SLOW_TASK"
    assert router_event["task_focus"] == "NEW_TASK_CANDIDATE"
    assert router_event["thinker_frame_event_id"] == emission.thinker_event["event_id"]
    assert "semantic_frame_ref" not in router_event
    assert "provider_response" not in router_event


def test_user_patch_evidence_pack_consumes_real_thinker_refs_as_non_authoritative_hypothesis() -> None:
    startup = _start_mvp3_thinker_contract_session(session_id="sess_mvp3_slice5_thinker_user_patch_synthetic")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_mvp3_slice5_thinker_user_patch",
    )
    emission = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    ).emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_user_patch_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_user_patch_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/user-patch",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/user-patch",
        **_available_optional_refs(),
    )
    router_event = startup.journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id="evt_mvp3_slice5_thinker_user_patch_router",
        source_module="router",
        caused_by_event_id=str(emission.thinker_event["event_id"]),
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
        trace_redaction_level="metadata_only",
        turn_id=str(committed_turn["turn_id"]),
        utterance_id=str(committed_turn["utterance_id"]),
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="ACTIVE_TASK_PATCH",
        active_task_id="task_mvp3_slice5_active",
        confidence=0.82,
        evidence_uncertainty="medium",
        turn_committed_event_id=str(committed_turn["event_id"]),
        thinker_frame_event_id=str(emission.thinker_event["event_id"]),
    )

    pack = construct_user_patch_evidence_pack(
        router_decision_event=router_event,
        turn_committed_event=committed_turn,
        thinker_frame_event=emission.thinker_event,
        evidence_ref="evidence://synthetic/mvp3/slice5/user-patch",
        semantic_summary_ref=str(emission.thinker_event["semantic_summary_ref"]),
        audio_summary_ref="audio-summary://synthetic/mvp3/slice5/user-patch",
        candidate_patch_types=["constraint_update_candidate"],
    )

    assert pack.non_authoritative_hypothesis["semantic_frame_ref"] == emission.thinker_event["semantic_frame_ref"]
    assert pack.non_authoritative_hypothesis["semantic_summary_ref"] == emission.thinker_event["semantic_summary_ref"]
    assert pack.non_authoritative_hypothesis["provenance"]["semantic_summary_ref"] == {
        "source": "thinker",
        "source_event_id": emission.thinker_event["event_id"],
        "evidence_ref": emission.thinker_event["semantic_frame_ref"],
    }
    assert "provider_response" not in repr(pack.to_dict())


def test_user_patch_evidence_pack_binds_omitted_summary_ref_to_real_thinker_event() -> None:
    startup = _start_mvp3_thinker_contract_session(session_id="sess_mvp3_slice5_thinker_user_patch_omitted_summary")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_mvp3_slice5_thinker_user_patch_omitted_summary",
    )
    emission = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    ).emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_user_patch_omitted_summary_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_user_patch_omitted_summary_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/user-patch-omitted-summary",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/user-patch-omitted-summary",
        **_available_optional_refs(),
    )
    router_event = _append_patch_router_event(
        startup.journal,
        committed_turn=committed_turn,
        thinker_event=emission.thinker_event,
        event_id="evt_mvp3_slice5_thinker_user_patch_omitted_summary_router",
    )

    pack = construct_user_patch_evidence_pack(
        router_decision_event=router_event,
        turn_committed_event=committed_turn,
        thinker_frame_event=emission.thinker_event,
        evidence_ref="evidence://synthetic/mvp3/slice5/user-patch-omitted-summary",
        candidate_patch_types=["constraint_update_candidate"],
    )

    assert pack.non_authoritative_hypothesis["semantic_summary_ref"] == emission.thinker_event["semantic_summary_ref"]
    assert pack.non_authoritative_hypothesis["provenance"]["semantic_summary_ref"]["source_event_id"] == emission.thinker_event["event_id"]


def test_user_patch_evidence_pack_rejects_stale_summary_ref_for_real_thinker_event() -> None:
    startup = _start_mvp3_thinker_contract_session(session_id="sess_mvp3_slice5_thinker_user_patch_stale_summary")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_mvp3_slice5_thinker_user_patch_stale_summary",
    )
    emission = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    ).emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_user_patch_stale_summary_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_user_patch_stale_summary_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/user-patch-stale-summary",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/user-patch-current-summary",
        **_available_optional_refs(),
    )
    router_event = _append_patch_router_event(
        startup.journal,
        committed_turn=committed_turn,
        thinker_event=emission.thinker_event,
        event_id="evt_mvp3_slice5_thinker_user_patch_stale_summary_router",
    )

    with pytest.raises(ValueError, match="semantic_summary_ref"):
        construct_user_patch_evidence_pack(
            router_decision_event=router_event,
            turn_committed_event=committed_turn,
            thinker_frame_event=emission.thinker_event,
            evidence_ref="evidence://synthetic/mvp3/slice5/user-patch-stale-summary",
            semantic_summary_ref="summary://synthetic/mvp3/slice5/user-patch-stale-summary",
            candidate_patch_types=["constraint_update_candidate"],
        )


def test_replay_rejects_user_patch_summary_ref_not_recorded_by_real_thinker_event() -> None:
    startup = _start_mvp3_thinker_contract_session(session_id="sess_mvp3_slice5_thinker_replay_stale_summary")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_mvp3_slice5_thinker_replay_stale_summary",
    )
    emission = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    ).emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_replay_stale_summary_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_replay_stale_summary_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/replay-stale-summary",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/replay-current-summary",
        **_available_optional_refs(),
    )
    startup.journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp3_slice5_thinker_replay_stale_summary_task_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(emission.thinker_event["event_id"]),
        created_monotonic_ms=215,
        created_wall_clock_ms=1700000000215,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice5_active",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp3/slice5/replay-stale-summary",
    )
    router_event = _append_patch_router_event(
        startup.journal,
        committed_turn=committed_turn,
        thinker_event=emission.thinker_event,
        event_id="evt_mvp3_slice5_thinker_replay_stale_summary_router",
    )
    result = UserPatchEvidencePackRuntime(startup.journal).receive_patch_from_router_decision(
        router_decision_event=router_event,
        turn_committed_event=committed_turn,
        task_id="task_mvp3_slice5_active",
        current_plan_version=1,
        next_task_event_seq=2,
        patch_id="patch_mvp3_slice5_stale_summary",
        event_id="evt_mvp3_slice5_thinker_replay_stale_summary_patch",
        evidence_ref="evidence://synthetic/mvp3/slice5/replay-stale-summary",
        created_monotonic_ms=230,
        created_wall_clock_ms=1700000000230,
        thinker_frame_event=emission.thinker_event,
        semantic_summary_ref=str(emission.thinker_event["semantic_summary_ref"]),
        candidate_patch_types=["constraint_update_candidate"],
    )
    events = startup.journal.events()
    patch_event = next(event for event in events if event["event_id"] == result.user_patch_event["event_id"])
    patch_event["non_authoritative_hypothesis_refs"] = [
        "semantic-frame://synthetic/mvp3/slice5/replay-stale-summary",
        "summary://synthetic/mvp3/slice5/replay-stale-summary",
    ]
    patch_event["evidence_pack"]["non_authoritative_hypothesis"][
        "semantic_summary_ref"
    ] = "summary://synthetic/mvp3/slice5/replay-stale-summary"

    with pytest.raises(ReplayValidationError, match="semantic_summary_ref"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


@pytest.mark.parametrize(
    ("status_field", "invalid_status"),
    (
        ("semantic_close_status", "assumed_closed"),
        ("assistant_directedness_status", "assumed_directed"),
        ("emotion_status", "neutral"),
        ("audio_caption_status", "missing"),
    ),
)
def test_replay_rejects_noncanonical_thinker_status_values(
    status_field: str,
    invalid_status: str,
) -> None:
    startup = _start_mvp3_thinker_contract_session(
        session_id=f"sess_mvp3_slice5_thinker_bad_{status_field}_synthetic"
    )
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix=f"evt_mvp3_slice5_thinker_bad_{status_field}",
    )
    contract = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    )
    emission = contract.emit_semantic_frame(
        event_id=f"evt_mvp3_slice5_thinker_bad_{status_field}_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id=f"adapter_request_mvp3_thinker_bad_{status_field}_001",
        semantic_frame_ref=f"semantic-frame://synthetic/mvp3/slice5/bad-{status_field}",
        semantic_summary_ref=f"summary://synthetic/mvp3/slice5/bad-{status_field}",
        semantic_close_ref=f"semantic-close://synthetic/mvp3/slice5/bad-{status_field}",
        assistant_directedness_ref=f"assistant-directedness://synthetic/mvp3/slice5/bad-{status_field}",
        emotion_ref=f"emotion://synthetic/mvp3/slice5/bad-{status_field}",
        audio_caption_ref=f"audio-caption://synthetic/mvp3/slice5/bad-{status_field}",
    )
    events = startup.journal.events()
    thinker = next(event for event in events if event["event_id"] == emission.thinker_event["event_id"])
    thinker[status_field] = invalid_status

    with pytest.raises(ReplayValidationError, match=status_field):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


@pytest.mark.parametrize(
    ("missing_field", "missing_capability"),
    (
        ("semantic_close_ref", "supports_semantic_close"),
        ("assistant_directedness_ref", "supports_assistant_directedness"),
        ("emotion_ref", "supports_emotion"),
        ("audio_caption_ref", "supports_audio_caption"),
    ),
)
def test_thinker_contract_requires_degraded_mode_for_missing_optional_semantic_fields(
    missing_field: str,
    missing_capability: str,
) -> None:
    startup = _start_mvp3_thinker_contract_session(
        session_id=f"sess_mvp3_slice5_thinker_missing_{missing_field}_synthetic"
    )
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix=f"evt_mvp3_slice5_thinker_missing_{missing_field}",
    )
    refs = _available_optional_refs()
    refs[missing_field] = None
    contract = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    )

    with pytest.raises(ValueError, match=missing_capability):
        contract.emit_semantic_frame(
            event_id=f"evt_mvp3_slice5_thinker_missing_{missing_field}_frame",
            caused_by_event_id=str(committed_turn["event_id"]),
            created_monotonic_ms=210,
            created_wall_clock_ms=1700000000210,
            turn_committed_event=committed_turn,
            adapter_request_id=f"adapter_request_mvp3_thinker_missing_{missing_field}_001",
            semantic_frame_ref=f"semantic-frame://synthetic/mvp3/slice5/missing-{missing_field}",
            semantic_summary_ref=f"summary://synthetic/mvp3/slice5/missing-{missing_field}",
            **refs,
        )


def test_replay_rejects_provider_specific_thinker_payload_leaking_downstream() -> None:
    startup = _start_mvp3_thinker_contract_session(session_id="sess_mvp3_slice5_thinker_provider_payload_synthetic")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_mvp3_slice5_thinker_provider_payload",
    )
    contract = ThinkerAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_thinker",
        output_mode="real",
    )
    emission = contract.emit_semantic_frame(
        event_id="evt_mvp3_slice5_thinker_provider_payload_frame",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_thinker_provider_payload_001",
        semantic_frame_ref="semantic-frame://synthetic/mvp3/slice5/provider-payload",
        semantic_summary_ref="summary://synthetic/mvp3/slice5/provider-payload",
        **_available_optional_refs(),
    )
    events = startup.journal.events()
    thinker = next(event for event in events if event["event_id"] == emission.thinker_event["event_id"])
    thinker["provider_response"] = {"choices": [{"message": "provider-specific"}]}

    with pytest.raises(ReplayValidationError, match="provider"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


def _start_mvp3_thinker_contract_session(
    *,
    session_id: str = "sess_mvp3_slice5_thinker_synthetic",
) -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_mvp3_slice5_thinker_synthetic",
        runtime_config_ref="config://synthetic/mvp3/slice5-thinker-contract",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/slice5-thinker-contract",
            capability_version="mvp3.contract.v1",
        ),
        capabilities=valid_mvp3_real_profiles(),
    )


def _append_committed_text_turn(
    journal: object,
    *,
    event_id_prefix: str = "evt_mvp3_slice5_thinker",
) -> dict[str, object]:
    snapshot_event_id = str(journal.events()[1]["event_id"])
    text_received = journal.append(
        event_name="TEXT_INPUT_RECEIVED",
        event_id=f"{event_id_prefix}_text_received",
        source_module="access_layer",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000000110,
        trace_redaction_level="redacted_fixture",
        input_span_id="input_mvp3_slice5_001",
        text_span_id="text_mvp3_slice5_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        text_ref="text://synthetic/mvp3/slice5/redacted-input-001",
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id=f"{event_id_prefix}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(text_received["event_id"]),
        created_monotonic_ms=111,
        created_wall_clock_ms=1700000000111,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp3_slice5_001",
        input_span_id="input_mvp3_slice5_001",
        input_modality="text",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"{event_id_prefix}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=112,
        created_wall_clock_ms=1700000000112,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp3_slice5_001",
        input_span_id="input_mvp3_slice5_001",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"{event_id_prefix}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=113,
        created_wall_clock_ms=1700000000113,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp3_slice5_001",
        utterance_id="utt_mvp3_slice5_001",
        input_span_id="input_mvp3_slice5_001",
        text_span_id="text_mvp3_slice5_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _append_patch_router_event(
    journal: object,
    *,
    committed_turn: dict[str, object],
    thinker_event: dict[str, object],
    event_id: str,
) -> dict[str, object]:
    return journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id=event_id,
        source_module="router",
        caused_by_event_id=str(thinker_event["event_id"]),
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
        trace_redaction_level="metadata_only",
        turn_id=str(committed_turn["turn_id"]),
        utterance_id=str(committed_turn["utterance_id"]),
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus="ACTIVE_TASK_PATCH",
        active_task_id="task_mvp3_slice5_active",
        confidence=0.82,
        evidence_uncertainty="medium",
        turn_committed_event_id=str(committed_turn["event_id"]),
        thinker_frame_event_id=str(thinker_event["event_id"]),
    )


def _available_optional_refs() -> dict[str, str | None]:
    return {
        "semantic_close_ref": "semantic-close://synthetic/mvp3/slice5/closed",
        "assistant_directedness_ref": "assistant-directedness://synthetic/mvp3/slice5/directed",
        "emotion_ref": "emotion://synthetic/mvp3/slice5/calm",
        "audio_caption_ref": "audio-caption://synthetic/mvp3/slice5/caption",
    }


def _github_allowed_replay_manifest() -> dict[str, object]:
    return {
        "manifest_schema_version": "1.0",
        "replay_id": "replay_mvp3_slice5_thinker_contract_synthetic",
        "source_trace_ref": "fixture://mvp3/slice5-thinker-contract",
        "replay_mode": "deterministic",
        "event_schema_version_range": ["1.0"],
        "fixture_domain": "GITHUB_ALLOWED",
        "generated_from": "hand_written_minimal",
        "contains_raw_audio": False,
        "contains_raw_trace": False,
        "contains_real_user_input": False,
        "contains_secrets": False,
        "contains_unredacted_tool_result": False,
        "contains_large_raw_web_content": False,
        "allowed_re_eval_components": [],
    }


def _block_provider_runtime(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    blocked_calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        blocked_calls.append((args, kwargs))
        raise AssertionError("Thinker contract and replay must not call provider runtime")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_called)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    monkeypatch.setattr(time, "time", fail_if_called)
    monkeypatch.setattr(time, "monotonic", fail_if_called)
    monkeypatch.setattr(random, "random", fail_if_called)
    return blocked_calls


def _forbidden_payload_terms_are_absent(events: list[dict[str, object]]) -> bool:
    rendered = repr(events)
    forbidden_terms = (
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_thinker_output",
        "provider_response",
        "provider_schema",
        "authorization",
        "credential",
        "api_key",
        "token",
    )
    return all(term not in rendered.lower() for term in forbidden_terms)
