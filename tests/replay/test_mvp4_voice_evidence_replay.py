from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

import pytest

from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


def test_spawn_slowtask_replay_reconstructs_voice_evidence_provenance() -> None:
    runtime_result = mvp4.run_mvp4_router_spawn_slowtask_voice_e2e()
    fixture = _mvp4_replay_fixture(
        runtime_result.events,
        replay_id="replay_mvp4_voice_spawn_provenance_in_memory",
        source_trace_ref="fixture://mvp4/in-memory/spawn-provenance",
    )
    mvp4.validate_mvp4_fixture_safety(fixture)

    replay_result = run_replay_fixture(fixture)
    events_by_id = _events_by_id(replay_result.ordered_events)
    router_event = _single(replay_result.ordered_events, "ROUTER_DECISION_EMITTED")
    created_event = _single(replay_result.ordered_events, "SLOWTASK_CREATED")
    reviewed_event = _single(replay_result.ordered_events, "EVIDENCE_REVIEWED")
    commitment_event = _single(replay_result.ordered_events, "SEMANTIC_COMMITMENT_EMITTED")
    expected_refs = _router_voice_evidence_refs(router_event, events_by_id)

    assert router_event["router_decision"] == "SPAWN_SLOW_TASK"
    assert created_event["source_evidence_refs"] == expected_refs
    assert reviewed_event["evidence_refs"] == expected_refs
    assert created_event["caused_by_event_id"] == router_event["event_id"]
    assert reviewed_event["task_id"] == created_event["task_id"]
    assert commitment_event["task_id"] == created_event["task_id"]

    task = replay_result.slowtask_state.tasks[str(created_event["task_id"])]
    assert task.source_evidence_refs == tuple(expected_refs)
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == commitment_event["task_event_seq"] + 1
    assert task.lifecycle_state == "COMPLETED"
    assert task.resolved_arguments_refs == ("args://synthetic/mvp4/router-outcome/spawn",)
    assert task.argument_provenance_refs == (
        "provenance://synthetic/mvp4/router-outcome/spawn",
        "provenance://synthetic/mvp4/router-outcome/spawn/asr",
        "provenance://synthetic/mvp4/router-outcome/spawn/thinker",
    )
    assert [
        event.refs
        for event in task.evidence_events
        if event.event_name == "EVIDENCE_REVIEWED"
    ] == [tuple(expected_refs)]
    assert [commitment.commitment_id for commitment in task.semantic_commitments] == [
        "commitment_mvp4_router_outcome_spawn"
    ]

    event_names = {event["event_name"] for event in replay_result.ordered_events}
    assert "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED" not in event_names
    assert "TTS_SYNTHESIS_OUTPUT_EMITTED" not in event_names
    assert not any(name.startswith("TOOL_") for name in event_names)


def test_patch_userpatch_replay_reconstructs_voice_evidence_provenance_without_plan_advance() -> None:
    runtime_result = mvp4.run_mvp4_router_patch_active_slowtask_voice_e2e()
    fixture = _mvp4_replay_fixture(
        runtime_result.events,
        replay_id="replay_mvp4_voice_patch_provenance_in_memory",
        source_trace_ref="fixture://mvp4/in-memory/patch-provenance",
    )
    mvp4.validate_mvp4_fixture_safety(fixture)

    replay_result = run_replay_fixture(fixture)
    user_patch = _single(replay_result.ordered_events, "USER_PATCH_RECEIVED")
    router_event = _event_by_id(replay_result.ordered_events, str(user_patch["caused_by_event_id"]))
    turn_event = _event_by_id(replay_result.ordered_events, str(router_event["turn_committed_event_id"]))
    asr_event = _event_by_id(replay_result.ordered_events, str(router_event["asr_frame_event_id"]))
    thinker_event = _event_by_id(replay_result.ordered_events, str(router_event["thinker_frame_event_id"]))
    evidence_pack = user_patch["evidence_pack"]
    authoritative = evidence_pack["authoritative_evidence"]
    hypothesis = evidence_pack["non_authoritative_hypothesis"]

    assert router_event["router_decision"] == "PATCH_ACTIVE_SLOW_TASK"
    assert user_patch["task_id"] == router_event["active_task_id"]
    assert user_patch["plan_version"] == 1
    assert user_patch["observed_plan_version"] == 1
    assert user_patch["task_event_seq"] == 5
    assert user_patch["turn_id"] == turn_event["turn_id"]
    assert user_patch["utterance_id"] == turn_event["utterance_id"]

    assert authoritative["input_modality"] == "audio"
    assert authoritative["audio_span_id"] == turn_event["audio_span_id"]
    assert turn_event["event_id"] in authoritative["source_event_ids"]
    assert asr_event["event_id"] in authoritative["source_event_ids"]
    assert authoritative["asr_frame_ref"] == asr_event["asr_frame_ref"]
    assert authoritative["asr_text_ref"] == asr_event["text_ref"]
    assert authoritative["asr_nbest"][0]["source_event_id"] == asr_event["event_id"]
    assert authoritative["asr_nbest"][0]["text_ref"] == asr_event["text_ref"]
    assert authoritative["provenance"]["asr_nbest"][0]["source"] == "asr"
    assert authoritative["provenance"]["asr_nbest"][0]["source_event_id"] == asr_event["event_id"]
    assert authoritative["provenance"]["asr_nbest"][0]["evidence_ref"] == asr_event["asr_frame_ref"]

    assert hypothesis["semantic_frame_ref"] == thinker_event["semantic_frame_ref"]
    assert hypothesis["semantic_summary_ref"] == thinker_event["semantic_summary_ref"]
    assert hypothesis["provenance"]["semantic_summary_ref"] == {
        "source": "thinker",
        "source_event_id": thinker_event["event_id"],
        "evidence_ref": thinker_event["semantic_frame_ref"],
    }

    task = replay_result.slowtask_state.tasks[str(user_patch["task_id"])]
    assert task.lifecycle_state == "PLANNING"
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == user_patch["task_event_seq"]
    assert task.initial_goal_ref == "goal://synthetic/mvp4/router-outcome/active"
    assert task.resolved_arguments_refs == ()
    assert task.argument_provenance_refs == ()
    assert task.user_patch_interpretations == ()
    assert task.confirmation_state.pending_confirmation_id is None
    assert [(patch.patch_id, patch.evidence_ref) for patch in task.user_patch_evidence] == [
        ("patch_mvp4_router_outcome_voice", "evidence://synthetic/mvp4/router-outcome/voice-patch")
    ]

    event_names = {event["event_name"] for event in replay_result.ordered_events}
    assert "USER_PATCH_INTERPRETED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names
    assert not any(name.startswith("TOOL_") for name in event_names)


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["authoritative_evidence"][
                "source_event_ids"
            ].remove(_asr["event_id"]),
            "asr_frame_event_id",
        ),
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["authoritative_evidence"].__setitem__(
                "asr_frame_ref",
                "asr-frame://synthetic/mvp4/mismatched-userpatch-asr-frame",
            ),
            "asr_frame_ref",
        ),
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["authoritative_evidence"].__setitem__(
                "asr_text_ref",
                "text://synthetic/mvp4/mismatched-userpatch-asr-text",
            ),
            "asr_text_ref",
        ),
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["authoritative_evidence"][
                "asr_nbest"
            ][0].__setitem__("source_event_id", "evt_mvp4_unrelated_asr"),
            "asr_nbest",
        ),
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["authoritative_evidence"][
                "provenance"
            ]["asr_nbest"][0].__setitem__("source_event_id", "evt_mvp4_unrelated_asr"),
            "asr_nbest provenance",
        ),
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["non_authoritative_hypothesis"][
                "provenance"
            ]["semantic_summary_ref"].__setitem__("source_event_id", "evt_mvp4_unrelated_thinker"),
            "thinker_frame_event_id",
        ),
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["non_authoritative_hypothesis"].__setitem__(
                "semantic_frame_ref",
                "semantic-frame://synthetic/mvp4/mismatched-userpatch-thinker-frame",
            ),
            "semantic_frame_ref",
        ),
        (
            lambda patch, _router, _asr, _thinker: patch["evidence_pack"]["non_authoritative_hypothesis"].__setitem__(
                "semantic_summary_ref",
                "summary://synthetic/mvp4/mismatched-userpatch-thinker-summary",
            ),
            "semantic_summary_ref",
        ),
    ],
)
def test_replay_rejects_mismatched_router_userpatch_voice_evidence_refs(
    mutate: Callable[[dict[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], object],
    expected_error: str,
) -> None:
    fixture = _patch_fixture()
    user_patch = _single_mutable(fixture["events"], "USER_PATCH_RECEIVED")
    router_event = _event_by_id(fixture["events"], str(user_patch["caused_by_event_id"]))
    asr_event = _event_by_id(fixture["events"], str(router_event["asr_frame_event_id"]))
    thinker_event = _event_by_id(fixture["events"], str(router_event["thinker_frame_event_id"]))

    mutate(user_patch, router_event, asr_event, thinker_event)

    with pytest.raises(ReplayValidationError, match=expected_error):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("event_name", "field", "drop_index", "expected_error"),
    [
        ("SLOWTASK_CREATED", "source_evidence_refs", 0, "SLOWTASK_CREATED source_evidence_refs"),
        ("SLOWTASK_CREATED", "source_evidence_refs", 1, "SLOWTASK_CREATED source_evidence_refs"),
        ("EVIDENCE_REVIEWED", "evidence_refs", 0, "EVIDENCE_REVIEWED evidence_refs"),
        ("EVIDENCE_REVIEWED", "evidence_refs", 1, "EVIDENCE_REVIEWED evidence_refs"),
    ],
)
def test_replay_rejects_mismatched_router_slowtask_spawn_voice_evidence_refs(
    event_name: str,
    field: str,
    drop_index: int,
    expected_error: str,
) -> None:
    fixture = _spawn_fixture()
    event = _single_mutable(fixture["events"], event_name)
    event[field] = [
        ref
        for index, ref in enumerate(event[field])
        if index != drop_index
    ]

    with pytest.raises(ReplayValidationError, match=expected_error):
        run_replay_fixture(fixture)


def _spawn_fixture() -> dict[str, Any]:
    runtime_result = mvp4.run_mvp4_router_spawn_slowtask_voice_e2e()
    return _mvp4_replay_fixture(
        runtime_result.events,
        replay_id="replay_mvp4_voice_spawn_negative_in_memory",
        source_trace_ref="fixture://mvp4/in-memory/spawn-negative",
    )


def _patch_fixture() -> dict[str, Any]:
    runtime_result = mvp4.run_mvp4_router_patch_active_slowtask_voice_e2e()
    return _mvp4_replay_fixture(
        runtime_result.events,
        replay_id="replay_mvp4_voice_patch_negative_in_memory",
        source_trace_ref="fixture://mvp4/in-memory/patch-negative",
    )


def _mvp4_replay_fixture(
    events: tuple[dict[str, Any], ...],
    *,
    replay_id: str,
    source_trace_ref: str,
) -> dict[str, Any]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": replay_id,
            "source_trace_ref": source_trace_ref,
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
        "events": deepcopy(list(events)),
    }


def _events_by_id(events: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(event["event_id"]): event for event in events}


def _router_voice_evidence_refs(
    router_event: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    asr_event = events_by_id[str(router_event["asr_frame_event_id"])]
    thinker_event = events_by_id[str(router_event["thinker_frame_event_id"])]
    return [str(asr_event["asr_frame_ref"]), str(thinker_event["semantic_frame_ref"])]


def _single(events: tuple[dict[str, Any], ...], event_name: str) -> dict[str, Any]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]


def _single_mutable(events: list[dict[str, Any]], event_name: str) -> dict[str, Any]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]


def _event_by_id(events: tuple[dict[str, Any], ...] | list[dict[str, Any]], event_id: str) -> dict[str, Any]:
    matches = [event for event in events if event["event_id"] == event_id]
    assert len(matches) == 1
    return matches[0]
