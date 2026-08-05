from __future__ import annotations

from collections import UserDict, UserList
from copy import deepcopy
from typing import Any, Callable

import pytest

from conftest import (
    MVP1_REPLAY_FIXTURE_DIR,
    MVP2_REPLAY_FIXTURE_DIR,
    MVP3_REPLAY_FIXTURE_DIR,
    load_json_fixture,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.user_patch.evidence_pack import UserPatchEvidencePackRuntime


PARALLEL_TOPOLOGY = "speculative_candidate_parallel_route"
TRANSCRIPT_DIGEST = "sha256:" + "1" * 64
PCM_MANIFEST_DIGEST = "sha256:" + "2" * 64
RELEASE_TOKEN_REF = (
    "release-token://synthetic/release_token_0123456789abcdef0123456789abcdef"
)
OTHER_RELEASE_TOKEN_REF = (
    "release-token://synthetic/release_token_abcdef0123456789abcdef0123456789"
)
COMPOSER_CHECK_FIXTURE = (
    MVP2_REPLAY_FIXTURE_DIR / "007-composer-checks.fixture.json"
)


class _HashSkewedStr(str):
    def __hash__(self) -> int:
        return super().__hash__() ^ 0x5A5A


def test_committed_parallel_chain_replays_deterministically() -> None:
    fixture = _committed_parallel_fixture()

    first = run_replay_fixture(fixture)
    second = run_replay_fixture(deepcopy(fixture))

    assert first.state_digest == second.state_digest
    assert first.qwen_parallel_state.provider_context_state == "CLEAN"
    assert first.qwen_parallel_state.route_evidence_event_ids == (
        "evt_route_evidence",
    )
    assert first.qwen_parallel_state.candidate_dispositions["cand_1"] == (
        "DISCARDED"
    )
    assert first.diagnostics["ignored_events"] == []
    assert first.diagnostics["adapter_outcomes"]["output_event_modes"][
        "evt_route_evidence"
    ] == "mock"
    assert first.diagnostics["adapter_outcomes"]["output_event_modes"][
        "evt_candidate_safety"
    ] == "mock"
    assert "qwen_parallel_state_hash" in first.state_digest


def test_rejected_smart_turn_replays_without_downstream_authority() -> None:
    fixture = _rejected_parallel_fixture()

    first = run_replay_fixture(fixture)
    second = run_replay_fixture(deepcopy(fixture))

    assert first.state_digest == second.state_digest
    assert first.interaction_state.turn_phase == "WAITING_USER"
    assert first.interaction_state.last_ingress_outcome == "REJECTED"
    assert first.qwen_parallel_state.provider_context_state == "CLEAN"
    assert first.diagnostics["ignored_events"] == []
    forbidden = {
        "TURN_INGRESS_COMMITTED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "ROUTE_EVIDENCE_OUTPUT_EMITTED",
        "ROUTER_DECISION_EMITTED",
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_COMMITTED",
        "FOREGROUND_OUTPUT_DISCARDED",
        "PLAYBACK_SPAN_STARTED",
    }
    assert not forbidden.intersection(
        event["event_name"] for event in first.ordered_events
    )


def test_native_release_chain_preserves_authority_and_delivery_identity() -> None:
    fixture = _native_release_fixture()

    first = run_replay_fixture(fixture)
    second = run_replay_fixture(deepcopy(fixture))

    assert first.state_digest == second.state_digest
    assert first.qwen_parallel_state.candidate_dispositions["cand_1"] == (
        "COMMITTED"
    )
    assert first.qwen_parallel_state.assistant_delivery_dispositions[
        "assistant-item://synthetic/1"
    ] == "FULL"
    assert first.qwen_parallel_state.shadow_verification_event_ids == (
        "evt_shadow_verification",
    )
    assert first.diagnostics["adapter_outcomes"]["output_event_modes"][
        "evt_shadow_verification"
    ] == "mock"
    assert first.playback_state.phase == "FINISHED"
    assert first.diagnostics["ignored_events"] == []


def test_native_full_chain_accepts_monotonic_commit_series() -> None:
    fixture = _native_release_fixture()
    _insert_partial_commit_before_full_commit(fixture)

    result = run_replay_fixture(fixture)

    assert result.playback_state.phase == "FINISHED"
    assert result.playback_state.latest_committed_offset_ms == 500


def test_native_full_delivery_requires_exact_not_required_cleanup() -> None:
    fixture = _native_release_fixture()
    _event_by_id(fixture, "evt_delivery_full")[
        "provider_item_cleanup_status"
    ] = "ACKNOWLEDGED"

    with pytest.raises(ReplayValidationError, match="FULL|NOT_REQUIRED|cleanup"):
        run_replay_fixture(fixture)


def test_native_full_delivery_requires_complete_candidate_coverage() -> None:
    fixture = _native_release_fixture()
    _sync_full_delivery_offset(fixture, 100)

    with pytest.raises(ReplayValidationError, match="FULL|coverage|duration"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "start_delta_ms",
    (
        pytest.param(-1, id="negative-start-delta"),
        pytest.param(1_001, id="late-start-delta"),
    ),
)
def test_native_started_delivery_requires_bounded_start_delta(
    start_delta_ms: int,
) -> None:
    fixture = _native_release_fixture()
    output = _event_by_id(fixture, "evt_output_committed")
    _event_by_id(fixture, "evt_playback_started")[
        "created_monotonic_ms"
    ] = int(output["created_monotonic_ms"]) + start_delta_ms

    with pytest.raises(ReplayValidationError, match="1,000|start|deadline"):
        run_replay_fixture(fixture)


def test_native_release_token_can_start_playback_only_once() -> None:
    fixture = _native_release_fixture()
    _insert_duplicate_release_token_playback_start(fixture)

    with pytest.raises(ReplayValidationError, match="token|start|playback"):
        run_replay_fixture(fixture)


def test_native_playback_start_cannot_rebind_assistant_item() -> None:
    fixture = _native_release_fixture()
    _event_by_id(fixture, "evt_playback_started")[
        "assistant_item_ref"
    ] = "assistant-item://synthetic/other"

    with pytest.raises(ReplayValidationError, match="assistant item|item"):
        run_replay_fixture(fixture)


def test_orphan_native_start_after_failed_gate_is_rejected() -> None:
    fixture = _committed_parallel_fixture()
    _append_orphan_native_start_after_failed_gate(fixture)

    with pytest.raises(ReplayValidationError, match="Gate|authority|orphan"):
        run_replay_fixture(fixture)


def test_tokenless_orphan_native_start_after_failed_gate_is_rejected() -> None:
    fixture = _committed_parallel_fixture()
    _append_orphan_native_start_after_failed_gate(fixture)
    _event_by_id(
        fixture,
        "evt_orphan_native_start_after_failed_gate",
    ).pop("release_token_ref")

    with pytest.raises(
        ReplayValidationError,
        match="native.*release.token|release.token.*native",
    ):
        run_replay_fixture(fixture)


def test_orphan_native_delivery_after_failed_gate_is_rejected() -> None:
    fixture = _committed_parallel_fixture()
    _append_orphan_native_delivery_after_failed_gate(fixture)

    with pytest.raises(ReplayValidationError, match="Gate|authority|output"):
        run_replay_fixture(fixture)


def test_tokenless_nonnative_spoken_plan_full_delivery_remains_legal() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    _append_tokenless_nonnative_spoken_plan_delivery(fixture)

    result = run_replay_fixture(fixture)

    assert result.playback_state.phase == "FINISHED"
    assert result.qwen_parallel_state.assistant_delivery_dispositions[
        "assistant-item://synthetic/mvp2/tokenless-tts"
    ] == "FULL"


def test_native_truncated_chain_preserves_interrupt_and_delivery_identity() -> None:
    fixture = _native_truncated_fixture()

    result = run_replay_fixture(fixture)

    assert result.playback_state.phase == "TRUNCATED"
    assert result.qwen_parallel_state.assistant_delivery_dispositions[
        "assistant-item://synthetic/1"
    ] == "TRUNCATED"
    assert result.qwen_parallel_state.shadow_verification_event_ids == (
        "evt_shadow_verification",
    )
    assert result.diagnostics["ignored_events"] == []


def test_native_truncated_chain_accepts_prior_partial_playback_commit() -> None:
    fixture = _native_truncated_fixture()
    _insert_partial_commit_before_interrupt(fixture)

    result = run_replay_fixture(fixture)

    assert result.playback_state.phase == "TRUNCATED"
    assert result.playback_state.latest_committed_offset_ms == 200


def test_native_truncated_chain_requires_real_interrupt_and_truncate_request() -> None:
    fixture = _native_truncated_fixture()
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"]
        not in {"evt_interrupt_native", "evt_truncate_requested_native"}
    ]
    truncated = _event_by_id(fixture, "evt_tts_truncated_native")
    truncated["caused_by_event_id"] = "evt_playback_started"
    truncated["truncate_request_event_id"] = "evt_missing_truncate_request"
    _resequence(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_truncate_requested_native",
            ).update(release_token_ref=OTHER_RELEASE_TOKEN_REF),
            id="truncate-request-release-token-mismatch",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_truncate_requested_native",
            ).update(playback_span_id="playback_other"),
            id="truncate-request-playback-span-mismatch",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_delivery_truncated",
            ).update(provider_item_cleanup_status="NOT_REQUIRED"),
            id="truncated-delivery-requires-provider-cleanup",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_delivery_truncated",
            ).update(
                delivery_offset_status="UNKNOWN",
                actual_stop_offset_ms=None,
            ),
            id="unknown-truncate-offset-requires-rebuild",
        ),
        pytest.param(
            lambda fixture: _append_full_terminals_to_truncated_fixture(
                fixture
            ),
            id="truncated-delivery-excludes-full-terminals",
        ),
        pytest.param(
            lambda fixture: _sync_truncated_delivery_offset(fixture, 600),
            id="truncated-offset-cannot-exceed-candidate-duration",
        ),
    ),
)
def test_native_truncated_mutations_fail_closed(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _native_truncated_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_shadow_mismatch_replays_only_with_taint_and_rebuild() -> None:
    fixture = _native_release_fixture()
    shadow = _event_by_id(fixture, "evt_shadow_verification")
    shadow.update(
        equivalence="MISMATCH",
        exact_numbers_entities_units_match=False,
    )
    _append_shadow_failure_recovery(fixture, shadow)

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.provider_context_state == "REBUILDING"
    assert result.qwen_parallel_state.provider_session_generation == 2


def test_native_not_started_chain_preserves_terminal_cleanup() -> None:
    result = run_replay_fixture(_native_not_started_fixture())

    assert result.qwen_parallel_state.assistant_delivery_dispositions[
        "assistant-item://synthetic/1"
    ] == "NOT_STARTED"


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_delivery_not_started",
            ).update(provider_item_cleanup_status="NOT_REQUIRED"),
            id="not-started-requires-provider-cleanup",
        ),
        pytest.param(
            lambda fixture: _append_orphan_playback_for_not_started(fixture),
            id="not-started-rejects-release-token-playback",
        ),
    ),
)
def test_native_not_started_mutations_fail_closed(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _native_not_started_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_selected_handoff_requires_and_accepts_matching_arbitration() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    arbitration = _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration",
        caused_by_event_id=handoff["event_id"],
        arbitration_id="arbitration_1",
        selected_source_type="progress",
        selected_source_event_id=handoff["event_id"],
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="current_progress_selected",
    )
    _append(
        fixture,
        "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
        "evt_handoff_selected",
        caused_by_event_id=arbitration["event_id"],
        handoff_id="handoff_1",
        disposition="SELECTED",
        response_arbitration_event_id=arbitration["event_id"],
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
        reason="arbitration_selected",
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "SELECTED"
    )
    assert result.qwen_parallel_state.response_arbitration_event_ids == (
        "evt_arbitration",
    )
    assert result.diagnostics["ignored_events"] == []


def test_queued_handoff_is_a_replayable_current_disposition() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    _append(
        fixture,
        "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
        "evt_handoff_queued",
        caused_by_event_id=handoff["event_id"],
        handoff_id="handoff_1",
        disposition="QUEUED",
        reason="waiting_for_idle",
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "QUEUED"
    )
    assert result.diagnostics["ignored_events"] == []


def test_emitted_handoff_without_any_disposition_fails_closed() -> None:
    fixture = _committed_parallel_fixture()
    _append_test_handoff(fixture)

    with pytest.raises(ReplayValidationError, match="handoff.*disposition"):
        run_replay_fixture(fixture)


def test_expired_handoff_cannot_be_selected_by_arbitration() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    handoff["expiry_status"] = "EXPIRED"
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )

    with pytest.raises(
        ReplayValidationError,
        match="expired handoff|cannot select an expired",
    ):
        run_replay_fixture(fixture)


def test_expired_handoff_requires_expired_disposition() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    handoff["expiry_status"] = "EXPIRED"
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="QUEUED",
    )

    with pytest.raises(
        ReplayValidationError,
        match="EXPIRED handoff.*EXPIRED disposition",
    ):
        run_replay_fixture(fixture)


def test_stale_handoff_requires_current_state_identity_mismatch() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="STALE",
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )

    with pytest.raises(
        ReplayValidationError,
        match="STALE handoff.*identity mismatch",
    ):
        run_replay_fixture(fixture)


def test_stale_handoff_accepts_current_state_identity_mismatch() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    _append(
        fixture,
        "PLANNING_RESTARTED",
        "evt_handoff_progress_restarted_for_stale",
        caused_by_event_id=str(handoff["event_id"]),
        source_module="slowtask_runtime",
        task_id="task_1",
        plan_version=1,
        task_event_seq=3,
        restart_reason="synthetic_newer_progress",
    )
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="STALE",
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=3,
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "STALE"
    )


def test_selected_handoff_revalidates_actual_slowtask_prefix_identity() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    _append(
        fixture,
        "PLANNING_RESTARTED",
        "evt_handoff_progress_after_emission",
        caused_by_event_id=str(handoff["event_id"]),
        source_module="slowtask_runtime",
        task_id="task_1",
        plan_version=1,
        task_event_seq=3,
        restart_reason="synthetic_progress_after_handoff",
    )
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )

    with pytest.raises(ReplayValidationError, match="actual|current"):
        run_replay_fixture(fixture)


def test_selected_handoff_requires_matching_current_state_identity() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=2,
        current_task_event_seq=2,
    )

    with pytest.raises(
        ReplayValidationError,
        match="SELECTED handoff.*current task identity",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture, handoff: handoff.update(
                source_event_ids=("evt_output_discarded",),
                caused_by_event_id="evt_output_discarded",
            ),
            id="raw-noncanonical-output-source",
        ),
        pytest.param(
            lambda fixture, handoff: handoff.update(
                task_id="task_forged",
                plan_version=7,
                task_event_seq=9,
            ),
            id="forged-current-plan-identity",
        ),
        pytest.param(
            lambda fixture, handoff: handoff.update(kind="FINAL"),
            id="handoff-kind-source-event-mismatch",
        ),
        pytest.param(
            lambda fixture, handoff: _event_by_id(
                fixture,
                str(handoff["source_event_ids"][-1]),
            ).update(source_module="forged_slowtask_owner"),
            id="forged-canonical-source-owner",
        ),
    ),
)
def test_handoff_requires_canonical_kind_matched_current_plan_sources(
    mutation: Callable[[dict[str, Any], dict[str, Any]], object],
) -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    mutation(fixture, handoff)
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id=str(handoff["task_id"]),
        current_plan_version=int(handoff["plan_version"]),
        current_task_event_seq=int(handoff["task_event_seq"]),
    )

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_selected_current_handoff_can_create_exact_composer_projection() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    disposition = _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )
    projection = _append_test_composer_projection(
        fixture,
        handoff=handoff,
        arbitration=arbitration,
        disposition=disposition,
    )

    result = run_replay_fixture(fixture)

    assert projection["event_id"] in (
        result.qwen_parallel_state.context_projection_event_ids
    )


def test_composer_projection_revalidates_current_slowtask_prefix() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    disposition = _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )
    _append(
        fixture,
        "PLANNING_RESTARTED",
        "evt_progress_after_selected_disposition",
        caused_by_event_id=str(disposition["event_id"]),
        source_module="slowtask_runtime",
        task_id="task_1",
        plan_version=1,
        task_event_seq=3,
        restart_reason="synthetic_progress_before_composer",
    )
    _append_test_composer_projection(
        fixture,
        handoff=handoff,
        arbitration=arbitration,
        disposition=disposition,
    )

    with pytest.raises(ReplayValidationError, match="Composer|current|SlowTask"):
        run_replay_fixture(fixture)


def test_later_arbitration_supersession_invalidates_old_selected_disposition() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    _append_superseding_handoff_arbitration(
        fixture,
        caused_by_event_id=str(arbitration["event_id"]),
        superseded_event_ids=(
            str(handoff["event_id"]),
            str(arbitration["event_id"]),
        ),
    )
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )

    with pytest.raises(ReplayValidationError, match="supersed"):
        run_replay_fixture(fixture)


def test_later_arbitration_supersession_invalidates_composer_projection() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    disposition = _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )
    _append_superseding_handoff_arbitration(
        fixture,
        caused_by_event_id=str(disposition["event_id"]),
        superseded_event_ids=(
            str(handoff["event_id"]),
            str(arbitration["event_id"]),
            str(disposition["event_id"]),
        ),
    )
    _append_test_composer_projection(
        fixture,
        handoff=handoff,
        arbitration=arbitration,
        disposition=disposition,
    )

    with pytest.raises(ReplayValidationError, match="supersed"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("kind", "source_event_name"),
    (
        ("DEGRADED", "SLOWTASK_DEGRADED"),
        ("FAILED", "SLOWTASK_FAILED"),
    ),
)
def test_terminal_handoff_kinds_select_through_final_arbitration(
    kind: str,
    source_event_name: str,
) -> None:
    fixture = _committed_parallel_fixture()
    progress = _append_current_progress_source(fixture)
    terminal_source = _append(
        fixture,
        source_event_name,
        f"evt_handoff_{kind.lower()}_source",
        caused_by_event_id=str(progress["event_id"]),
        source_module="slowtask_runtime",
        task_id="task_1",
        plan_version=1,
        task_event_seq=3,
        **(
            {"degraded_reason": "synthetic_degradation"}
            if kind == "DEGRADED"
            else {"failure_reason": "synthetic_failure"}
        ),
    )
    handoff = _append_test_handoff(
        fixture,
        source_event=terminal_source,
        kind=kind,
    )
    arbitration = _append_test_handoff_arbitration(
        fixture,
        handoff,
        selected_source_type="final",
    )
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=3,
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "SELECTED"
    )


def test_handoff_allows_multiple_same_plan_sources_through_latest_sequence() -> None:
    fixture = _committed_parallel_fixture()
    first_progress = _append_current_progress_source(fixture)
    latest_progress = _append(
        fixture,
        "PLANNING_RESTARTED",
        "evt_handoff_progress_restarted",
        caused_by_event_id=str(first_progress["event_id"]),
        source_module="slowtask_runtime",
        task_id="task_1",
        plan_version=1,
        task_event_seq=3,
        restart_reason="synthetic_retry",
    )
    handoff = _append_test_handoff(
        fixture,
        source_event=latest_progress,
    )
    handoff["source_event_ids"] = (
        first_progress["event_id"],
        latest_progress["event_id"],
    )
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=3,
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "SELECTED"
    )


def test_queued_handoff_can_later_be_selected_once() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="QUEUED",
    )
    arbitration = _append_test_handoff_arbitration(fixture, handoff)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="SELECTED",
        caused_by_event_id=str(arbitration["event_id"]),
        response_arbitration_event_id=str(arbitration["event_id"]),
        current_task_id="task_1",
        current_plan_version=1,
        current_task_event_seq=2,
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "SELECTED"
    )


@pytest.mark.parametrize("disposition", ("QUEUED", "STALE", "EXPIRED"))
def test_nonselected_handoff_cannot_create_composer_projection(
    disposition: str,
) -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    fields: dict[str, object] = {}
    if disposition == "STALE":
        fields.update(
            current_task_id="task_1",
            current_plan_version=2,
            current_task_event_seq=2,
        )
    if disposition == "EXPIRED":
        handoff["expiry_status"] = "EXPIRED"
    disposition_event = _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition=disposition,
        **fields,
    )
    _append_test_composer_projection(
        fixture,
        handoff=handoff,
        disposition=disposition_event,
    )

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("selected_source_type", "include_selected", "supersede_selected"),
    (
        pytest.param("none", True, False, id="none-with-selected-source"),
        pytest.param("user_fast", False, False, id="non-none-without-source"),
        pytest.param(
            "user_fast",
            True,
            True,
            id="same-source-selected-and-superseded",
        ),
    ),
)
def test_response_arbitration_contradictions_fail_closed(
    selected_source_type: str,
    include_selected: bool,
    supersede_selected: bool,
) -> None:
    fixture = _committed_parallel_fixture()
    fields: dict[str, object] = {
        "arbitration_id": "arbitration_contradiction",
        "selected_source_type": selected_source_type,
        "superseded_source_event_ids": (
            ("evt_output_discarded",) if supersede_selected else ()
        ),
        "provider_session_generation": 1,
        "playback_epoch": 0,
        "interaction_state_version": 0,
        "decision_reason": "synthetic_contradiction",
    }
    if include_selected:
        fields["selected_source_event_id"] = "evt_output_discarded"
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_contradiction",
        caused_by_event_id="evt_output_discarded",
        **fields,
    )

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "selected_source_event_id",
    (
        pytest.param("evt_candidate", id="candidate"),
        pytest.param("evt_gate_passed", id="gate-pass"),
        pytest.param("evt_output_committed", id="committed-output"),
    ),
)
def test_user_fast_arbitration_accepts_canonical_active_authority(
    selected_source_event_id: str,
) -> None:
    fixture = _native_release_fixture()
    _insert_user_fast_arbitration_before_playback(
        fixture,
        selected_source_event_id=selected_source_event_id,
    )

    result = run_replay_fixture(fixture)

    assert "evt_arbitration_select_user_fast" in (
        result.qwen_parallel_state.response_arbitration_event_ids
    )


@pytest.mark.parametrize(
    ("selected_source_type", "selected_source_event_id", "native_fixture"),
    (
        pytest.param(
            "user_fast",
            "evt_session_started",
            False,
            id="user-fast-cannot-select-root",
        ),
        pytest.param(
            "user_fast",
            "evt_output_discarded",
            False,
            id="user-fast-cannot-select-discard",
        ),
        pytest.param(
            "progress",
            "evt_candidate",
            True,
            id="progress-must-select-handoff",
        ),
    ),
)
def test_response_arbitration_selection_uses_canonical_source_allowlist(
    selected_source_type: str,
    selected_source_event_id: str,
    native_fixture: bool,
) -> None:
    fixture = (
        _native_release_fixture()
        if native_fixture
        else _committed_parallel_fixture()
    )
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_invalid_selected_source",
        caused_by_event_id=selected_source_event_id,
        arbitration_id="arbitration_invalid_selected_source",
        selected_source_type=selected_source_type,
        selected_source_event_id=selected_source_event_id,
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_invalid_selected_source",
    )

    with pytest.raises(ReplayValidationError, match="source|user_fast|handoff"):
        run_replay_fixture(fixture)


def test_user_fast_arbitration_rejects_candidate_after_failed_gate() -> None:
    fixture = _committed_parallel_fixture()
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_select_discarded_candidate",
        caused_by_event_id="evt_candidate",
        arbitration_id="arbitration_select_discarded_candidate",
        selected_source_type="user_fast",
        selected_source_event_id="evt_candidate",
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_discarded_candidate_selection",
    )

    with pytest.raises(ReplayValidationError, match="active|user_fast|Gate"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "terminal_status",
    (
        pytest.param("FULL", id="full"),
        pytest.param("TRUNCATED", id="truncated"),
        pytest.param("NOT_STARTED", id="not-started"),
    ),
)
@pytest.mark.parametrize(
    "selected_source_event_id",
    (
        pytest.param("evt_candidate", id="candidate"),
        pytest.param("evt_gate_passed", id="gate"),
        pytest.param("evt_output_committed", id="output"),
    ),
)
def test_user_fast_arbitration_rejects_authority_retired_by_delivery(
    terminal_status: str,
    selected_source_event_id: str,
) -> None:
    fixture = _native_fixture_for_delivery_status(terminal_status)
    _append_post_delivery_user_fast_arbitration(
        fixture,
        selected_source_event_id=selected_source_event_id,
    )

    with pytest.raises(
        ReplayValidationError,
        match="delivery.*retired|retired.*delivery",
    ):
        run_replay_fixture(fixture)


def test_post_delivery_none_arbitration_remains_legal() -> None:
    fixture = _native_release_fixture()
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_none_after_delivery",
        caused_by_event_id="evt_delivery_full",
        arbitration_id="arbitration_none_after_delivery",
        selected_source_type="none",
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_delivery_terminal_no_selection",
    )

    result = run_replay_fixture(fixture)

    assert "evt_arbitration_none_after_delivery" in (
        result.qwen_parallel_state.response_arbitration_event_ids
    )


def test_post_cancellation_none_arbitration_remains_legal() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    cancellation = _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="CANCELLED",
    )
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_none_after_cancellation",
        caused_by_event_id=str(cancellation["event_id"]),
        arbitration_id="arbitration_none_after_cancellation",
        selected_source_type="none",
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_cancelled_handoff_no_selection",
    )

    result = run_replay_fixture(fixture)

    assert "evt_arbitration_none_after_cancellation" in (
        result.qwen_parallel_state.response_arbitration_event_ids
    )


def test_response_arbitration_requires_canonical_causal_trigger() -> None:
    fixture = _committed_parallel_fixture()
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_root_trigger",
        caused_by_event_id="evt_session_started",
        arbitration_id="arbitration_root_trigger",
        selected_source_type="none",
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_root_trigger",
    )

    with pytest.raises(ReplayValidationError, match="trigger|caused_by"):
        run_replay_fixture(fixture)


def test_response_arbitration_cannot_supersede_arbitrary_root_event() -> None:
    fixture = _committed_parallel_fixture()
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_supersede_root",
        caused_by_event_id="evt_candidate",
        arbitration_id="arbitration_supersede_root",
        selected_source_type="none",
        superseded_source_event_ids=("evt_session_started",),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_root_supersession",
    )

    with pytest.raises(ReplayValidationError, match="supersed|authority"):
        run_replay_fixture(fixture)


def test_progress_handoff_can_coalesce_to_newer_current_progress() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    replacement = _append_replacement_progress_handoff(fixture)
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="COALESCED",
        caused_by_event_id=str(replacement["event_id"]),
        replacement_handoff_id=str(replacement["handoff_id"]),
    )
    _append_test_handoff_disposition(
        fixture,
        replacement,
        disposition="QUEUED",
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "COALESCED"
    )


@pytest.mark.parametrize(
    "replacement_variant",
    (
        pytest.param("same-task-sequence", id="replacement-not-newer"),
        pytest.param("expired", id="replacement-expired"),
        pytest.param("incompatible-kind", id="replacement-incompatible-kind"),
    ),
)
def test_coalesced_handoff_requires_eligible_current_replacement(
    replacement_variant: str,
) -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    replacement = _append_replacement_progress_handoff(
        fixture,
        newer=replacement_variant != "same-task-sequence",
        expiry_status=(
            "EXPIRED" if replacement_variant == "expired" else "CURRENT"
        ),
        incompatible_terminal=(
            replacement_variant == "incompatible-kind"
        ),
    )
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="COALESCED",
        caused_by_event_id=str(replacement["event_id"]),
        replacement_handoff_id=str(replacement["handoff_id"]),
    )
    _append_test_handoff_disposition(
        fixture,
        replacement,
        disposition=(
            "EXPIRED"
            if replacement["expiry_status"] == "EXPIRED"
            else "QUEUED"
        ),
    )

    with pytest.raises(
        ReplayValidationError,
        match="COALESCED|replacement|newer|CURRENT|compatible",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize("include_safety", (False, True))
def test_partial_route_and_candidate_safety_chains_are_replayable(
    include_safety: bool,
) -> None:
    fixture = _partial_evidence_fixture(include_safety=include_safety)

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.route_evidence_event_ids == (
        "evt_route_evidence",
    )
    assert result.qwen_parallel_state.candidate_safety_event_ids == (
        ("evt_candidate_safety",) if include_safety else ()
    )
    assert result.task_focus_state.router_decision_event_id == "evt_router"
    assert result.diagnostics["ignored_events"] == []


@pytest.mark.parametrize(
    ("bound_role", "terminal_event_name", "terminal_order"),
    (
        pytest.param(
            bound_role,
            terminal_event_name,
            terminal_order,
            id=f"{bound_role}-{terminal_event_name.casefold()}-{terminal_order}",
        )
        for bound_role in ("route", "safety")
        for terminal_event_name in (
            "ADAPTER_REQUEST_FAILED",
            "ADAPTER_OUTPUT_VALIDATION_FAILED",
            "ADAPTER_OUTPUT_DEGRADED",
        )
        for terminal_order in ("before-success", "after-success")
    ),
)
def test_partial_evidence_success_excludes_exact_request_terminal(
    bound_role: str,
    terminal_event_name: str,
    terminal_order: str,
) -> None:
    fixture = _partial_evidence_fixture(
        include_safety=bound_role == "safety"
    )
    _insert_partial_evidence_request_terminal(
        fixture,
        bound_role=bound_role,
        terminal_event_name=terminal_event_name,
        terminal_order=terminal_order,
    )

    with pytest.raises(
        ReplayValidationError,
        match="non-degraded success|terminal failure|degradation",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize("bound_role", ("route", "safety"))
@pytest.mark.parametrize(
    "unrelated_binding",
    ("adapter", "request"),
)
def test_partial_evidence_success_preserves_unrelated_request_terminal(
    bound_role: str,
    unrelated_binding: str,
) -> None:
    fixture = _partial_evidence_fixture(
        include_safety=bound_role == "safety"
    )
    _insert_partial_evidence_request_terminal(
        fixture,
        bound_role=bound_role,
        terminal_event_name="ADAPTER_REQUEST_FAILED",
        terminal_order="after-success",
        unrelated_binding=unrelated_binding,
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.route_evidence_event_ids == (
        "evt_route_evidence",
    )
    assert result.qwen_parallel_state.candidate_safety_event_ids == (
        ("evt_candidate_safety",) if bound_role == "safety" else ()
    )


def test_legacy_asr_degraded_evidence_retains_request_compatibility() -> None:
    fixture = load_json_fixture(
        MVP3_REPLAY_FIXTURE_DIR
        / "008-fallback-degraded-replay.fixture.json"
    )
    asr = next(
        event
        for event in fixture["events"]
        if event["event_name"] == "ASR_TRANSCRIPT_OUTPUT_EMITTED"
    )
    degraded = deepcopy(
        next(
            event
            for event in fixture["events"]
            if event["event_name"] == "ADAPTER_OUTPUT_DEGRADED"
        )
    )
    degraded.update(
        event_id="evt_mvp3_slice8_asr_final_only_degraded",
        source_module="asr_adapter",
        caused_by_event_id=asr["caused_by_event_id"],
        adapter_id=asr["adapter_id"],
        adapter_type="asr",
        adapter_request_id=asr["adapter_request_id"],
        degraded_reason="supports_streaming_output",
        missing_capability="supports_streaming_output",
        output_mode="degraded",
    )
    degraded.pop("fallback_adapter_id", None)
    asr.update(
        streaming_status="unsupported_final_only",
        output_mode="degraded",
    )
    insertion_index = fixture["events"].index(asr)
    fixture["events"].insert(insertion_index, degraded)
    _resequence(fixture)

    result = run_replay_fixture(fixture)

    assert result.adapter_health_state.output_event_modes[asr["event_id"]] == (
        "degraded"
    )


def test_candidate_safety_can_complete_before_route_and_router_authority() -> None:
    fixture = _committed_parallel_fixture()
    _make_candidate_safety_independent_before_route(fixture)

    result = run_replay_fixture(fixture)

    ordered_ids = [event["event_id"] for event in result.ordered_events]
    assert ordered_ids.index("evt_candidate_safety") < ordered_ids.index(
        "evt_route_evidence"
    )
    assert ordered_ids.index("evt_candidate_safety") < ordered_ids.index(
        "evt_router"
    )
    assert result.qwen_parallel_state.candidate_safety_event_ids == (
        "evt_candidate_safety",
    )


def test_qwen_final_asr_rejects_duplicate_committed_input_terminal() -> None:
    fixture = _committed_parallel_fixture()
    _append_duplicate_qwen_asr(fixture)

    with pytest.raises(ReplayValidationError, match="ASR|terminal|cardinality"):
        run_replay_fixture(fixture)


def test_candidate_safety_rejects_conflicting_response_terminal() -> None:
    fixture = _committed_parallel_fixture()
    _append_conflicting_candidate_safety(fixture)

    with pytest.raises(
        ReplayValidationError,
        match="candidate-safety|response|terminal|cardinality",
    ):
        run_replay_fixture(fixture)


def test_route_evidence_request_cannot_emit_terminals_for_two_turns() -> None:
    fixture = _committed_parallel_fixture()
    _append_second_route_only_turn(
        fixture,
        route_adapter_request_id="route_request_1",
    )

    with pytest.raises(
        ReplayValidationError,
        match="Route Evidence|request|terminal|cardinality",
    ):
        run_replay_fixture(fixture)


def test_provider_free_qwen_asr_only_terminal_is_replayable() -> None:
    fixture = _asr_only_fixture()

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.provider_context_state == "CLEAN"
    assert result.qwen_parallel_state.route_evidence_event_ids == ()
    assert result.adapter_health_state.output_event_modes["evt_asr_final"] == "mock"
    assert result.diagnostics["ignored_events"] == []


def test_provider_backed_committed_turn_requires_clean_context_at_acceptance() -> None:
    fixture = _provider_tainted_committed_fixture()

    with pytest.raises(ReplayValidationError, match="CLEAN"):
        run_replay_fixture(fixture)


def test_partial_qwen_commit_without_speech_generations_rejects_tainted_context() -> None:
    fixture = _provider_tainted_committed_fixture()
    _remove_optional_speech_generations(fixture)

    with pytest.raises(ReplayValidationError, match="CLEAN|provider"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "evidence_mode",
    (
        pytest.param("speech-start-only", id="speech-start-only"),
        pytest.param("qwen-session-only", id="qwen-session-only"),
    ),
)
def test_partial_qwen_commit_infers_provider_backing_without_end_generation(
    evidence_mode: str,
) -> None:
    fixture = _provider_tainted_committed_fixture()
    _remove_optional_speech_generations(fixture)
    _event_by_id(fixture, "evt_speech_end").pop("provider_event_ref")
    if evidence_mode == "qwen-session-only":
        _event_by_id(fixture, "evt_speech_start").pop("provider_event_ref")

    with pytest.raises(ReplayValidationError, match="CLEAN|provider"):
        run_replay_fixture(fixture)


def test_partial_qwen_commit_requires_exact_audio_start_cause() -> None:
    fixture = _provider_backed_committed_ingress_only_fixture()
    _event_by_id(fixture, "evt_speech_start")[
        "caused_by_event_id"
    ] = "evt_provider_clean"

    with pytest.raises(ReplayValidationError, match="AUDIO_SPAN_STARTED|topology"):
        run_replay_fixture(fixture)


def test_partial_qwen_commit_requires_turn_opened_to_be_caused_by_speech_start() -> None:
    fixture = _provider_backed_committed_ingress_only_fixture()
    _event_by_id(fixture, "evt_turn_opened")[
        "caused_by_event_id"
    ] = "evt_audio_started"

    with pytest.raises(ReplayValidationError, match="TURN_OPENED|speech"):
        run_replay_fixture(fixture)


def test_partial_qwen_commit_rejects_turn_opened_after_audio_end() -> None:
    fixture = _provider_backed_committed_ingress_only_fixture()
    _move_turn_opened_after_audio_end(fixture)

    with pytest.raises(ReplayValidationError, match="TURN_OPENED|order|topology"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "provider_stop_reason",
    (
        pytest.param("turn_invalid", id="turn-invalid"),
        pytest.param("synthetic_unknown_reason", id="unknown-stop-reason"),
    ),
)
def test_invalid_qwen_speech_stop_cannot_commit(
    provider_stop_reason: str,
) -> None:
    fixture = _provider_backed_committed_ingress_only_fixture()
    _event_by_id(fixture, "evt_speech_end")[
        "provider_stop_reason"
    ] = provider_stop_reason

    with pytest.raises(ReplayValidationError, match="REJECTED|stop|invalid"):
        run_replay_fixture(fixture)


def test_clean_qwen_trace_may_end_at_ingress_acceptance() -> None:
    fixture = _provider_backed_committed_ingress_only_fixture()
    _remove_event(fixture, "evt_turn_committed")

    result = run_replay_fixture(fixture)

    assert result.interaction_state.last_ingress_outcome == "ACCEPTED"


@pytest.mark.parametrize(
    "speech_events_with_generation",
    (
        pytest.param((), id="both-optional-generations-absent"),
        pytest.param(("evt_speech_start",), id="only-start-generation-present"),
        pytest.param(("evt_speech_end",), id="only-end-generation-present"),
    ),
)
def test_clean_qwen_commit_allows_optional_speech_generation_evidence(
    speech_events_with_generation: tuple[str, ...],
) -> None:
    fixture = _committed_parallel_fixture()
    for event_id in ("evt_speech_start", "evt_speech_end"):
        if event_id not in speech_events_with_generation:
            _event_by_id(fixture, event_id).pop(
                "provider_session_generation"
            )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.route_evidence_event_ids == (
        "evt_route_evidence",
    )


def test_qwen_asr_rejects_nonclean_provider_at_ingress_acceptance() -> None:
    fixture = _committed_parallel_fixture()
    _insert_transient_cleanup_around_acceptance(fixture)

    with pytest.raises(ReplayValidationError, match="accept|window|CLEAN"):
        run_replay_fixture(fixture)


def test_qwen_asr_rejects_transient_nonclean_speech_window() -> None:
    fixture = _committed_parallel_fixture()
    _insert_transient_cleanup_during_speech(fixture)

    with pytest.raises(ReplayValidationError, match="window|CLEAN"):
        run_replay_fixture(fixture)


def test_qwen_asr_requires_commit_to_reference_exact_prior_acceptance() -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_speech_start").pop(
        "provider_session_generation"
    )
    _event_by_id(fixture, "evt_speech_end").pop(
        "provider_session_generation"
    )
    _event_by_id(fixture, "evt_turn_committed")[
        "caused_by_event_id"
    ] = "evt_speech_end"

    with pytest.raises(ReplayValidationError, match="ACCEPTED|accept"):
        run_replay_fixture(fixture)


def test_post_rebuild_qwen_asr_cannot_launder_nonclean_committed_ingress() -> None:
    fixture = _committed_parallel_fixture()
    _launder_nonclean_commit_through_post_rebuild_asr(fixture)

    with pytest.raises(ReplayValidationError, match="commit|generation|CLEAN"):
        run_replay_fixture(fixture)


def test_nonclean_provider_turn_can_terminate_as_rejected_without_authority() -> None:
    fixture = _provider_tainted_rejected_fixture()

    result = run_replay_fixture(fixture)

    assert result.interaction_state.last_ingress_outcome == "REJECTED"
    assert result.qwen_parallel_state.route_evidence_event_ids == ()


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _forge_qwen_asr_adapter_id(fixture),
            id="forged-asr-profile",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_asr_final").update(
                provider_session_generation=2
            ),
            id="asr-generation-not-clean",
        ),
    ),
)
def test_provider_free_qwen_asr_only_requires_exact_capability_and_clean_generation(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _asr_only_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("include_safety", "mutation"),
    (
        pytest.param(
            False,
            lambda fixture: _event_by_id(fixture, "evt_route_evidence").update(
                turn_id="turn_other"
            ),
            id="partial-route-wrong-turn",
        ),
        pytest.param(
            False,
            lambda fixture: _event_by_id(fixture, "evt_router").update(
                route_evidence_event_id="evt_missing_route"
            ),
            id="partial-router-wrong-route-ref",
        ),
        pytest.param(
            True,
            lambda fixture: _event_by_id(fixture, "evt_candidate_safety").update(
                utterance_id="utt_other"
            ),
            id="partial-safety-wrong-utterance",
        ),
        pytest.param(
            True,
            lambda fixture: _event_by_id(fixture, "evt_candidate_safety").update(
                route_evidence_event_id="evt_missing_route"
            ),
            id="partial-safety-wrong-route-ref",
        ),
    ),
)
def test_partial_evidence_chain_mutations_fail_closed(
    include_safety: bool,
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _partial_evidence_fixture(include_safety=include_safety)
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _sync_route_confidence(fixture, 0.79),
            id="gate-pass-route-confidence-below-threshold",
        ),
        pytest.param(
            lambda fixture: _sync_safety_confidence(fixture, 0.89),
            id="gate-pass-safety-confidence-below-threshold",
        ),
        pytest.param(
            lambda fixture: _sync_route_uncertainty(fixture, "HIGH"),
            id="gate-pass-route-uncertainty-not-low",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_route_evidence",
            ).update(route_hint="SPAWN_SLOW_TASK"),
            id="router-decision-must-exactly-join-route-hint",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_route_evidence",
            ).update(task_focus_hint="NEW_TASK_CANDIDATE"),
            id="router-task-focus-must-exactly-join-route-hint",
        ),
    ),
)
def test_native_gate_pass_requires_canonical_evidence_thresholds_and_exact_joins(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _native_release_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_native_gate_pass_rejects_explicit_qwen_native_pcm_degradation() -> None:
    fixture = _native_release_fixture()
    _insert_relevant_adapter_adverse_event_before_gate(
        fixture,
        event_name="ADAPTER_OUTPUT_DEGRADED",
    )

    with pytest.raises(ReplayValidationError, match="capability|degrad|native"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "event_name",
    (
        pytest.param("ADAPTER_REQUEST_FAILED", id="request-failed"),
        pytest.param(
            "ADAPTER_OUTPUT_VALIDATION_FAILED",
            id="validation-failed",
        ),
        pytest.param("ADAPTER_HEALTHCHECK_FAILED", id="healthcheck-failed"),
    ),
)
def test_native_gate_pass_rejects_current_relevant_adapter_failure(
    event_name: str,
) -> None:
    fixture = _native_release_fixture()
    _insert_relevant_adapter_adverse_event_before_gate(
        fixture,
        event_name=event_name,
    )

    with pytest.raises(ReplayValidationError, match="adapter|failure|native"):
        run_replay_fixture(fixture)


def test_native_gate_pass_rejects_degraded_gate_output_mode() -> None:
    fixture = _native_release_fixture()
    _event_by_id(fixture, "evt_gate_passed")["output_mode"] = "degraded"

    with pytest.raises(ReplayValidationError, match="degraded|output_mode|native"):
        run_replay_fixture(fixture)


def test_native_gate_rejects_terminal_failure_for_bound_request() -> None:
    fixture = _native_release_fixture()
    _insert_nonblocking_adapter_failure(
        fixture,
        variant="bound-request-before-candidate",
    )

    with pytest.raises(ReplayValidationError, match="request|failure|native"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "bound_role",
    (
        pytest.param("route", id="route"),
        pytest.param("safety", id="safety"),
    ),
)
def test_bound_evidence_request_failure_before_snapshot_cannot_revive(
    bound_role: str,
) -> None:
    fixture = _native_release_fixture()
    _insert_bound_request_terminal_failure(
        fixture,
        bound_role=bound_role,
        target_event_id="evt_capability_snapshot",
    )

    with pytest.raises(
        ReplayValidationError,
        match="terminal|request|failure",
    ):
        run_replay_fixture(fixture)


def test_qwen_bound_request_failure_after_commit_invalidates_release() -> None:
    fixture = _native_release_fixture()
    _insert_bound_request_terminal_failure(
        fixture,
        bound_role="qwen_candidate",
        target_event_id="evt_playback_started",
    )

    with pytest.raises(
        ReplayValidationError,
        match="terminal|request|failure|release",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "variant",
    (
        pytest.param("unrelated-adapter", id="unrelated-adapter"),
        pytest.param("unrelated-request", id="unrelated-request"),
        pytest.param(
            "recovered-health-before-candidate",
            id="recovered-health",
        ),
    ),
)
def test_native_gate_ignores_noncurrent_or_unrelated_adapter_failure(
    variant: str,
) -> None:
    fixture = _native_release_fixture()
    _insert_nonblocking_adapter_failure(fixture, variant=variant)

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.candidate_dispositions["cand_1"] == (
        "COMMITTED"
    )


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_route_evidence",
            ).update(risk_tags={}),
            id="route-risk-tags-mapping",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_route_evidence",
            ).update(risk_tags=("duplicate", "duplicate")),
            id="route-risk-tags-duplicate",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_candidate_safety",
            ).update(prohibited_flags={}),
            id="safety-prohibited-flags-mapping",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_candidate_safety",
            ).update(
                semantic_categories=tuple(
                    f"category_{index}" for index in range(9)
                )
            ),
            id="safety-semantic-categories-over-canonical-limit",
        ),
    ),
)
def test_parallel_evidence_symbolic_arrays_use_canonical_contract_validation(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _committed_parallel_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _swap_event_seq(
                fixture,
                "evt_asr_final",
                "evt_route_evidence",
            ),
            id="route-evidence-before-final-asr",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_route_evidence").update(
                turn_id="turn_other"
            ),
            id="route-evidence-other-turn",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_router").update(
                route_evidence_event_id="evt_candidate"
            ),
            id="router-points-to-candidate",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate").update(
                candidate_transcript_digest="sha256:" + "3" * 64
            ),
            id="candidate-safety-transcript-digest-mismatch",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate").update(
                provider_session_generation=2
            ),
            id="candidate-composite-generation-mismatch",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_gate_failed").update(
                context_snapshot_id="snapshot_other"
            ),
            id="candidate-gate-snapshot-mismatch",
        ),
        pytest.param(
            lambda fixture: _append_duplicate_router(fixture),
            id="second-router",
        ),
        pytest.param(
            lambda fixture: _append_duplicate_gate(fixture),
            id="second-terminal-gate",
        ),
        pytest.param(
            lambda fixture: _append_duplicate_candidate_disposition(fixture),
            id="second-candidate-disposition",
        ),
        pytest.param(
            lambda fixture: _append_duplicate_event_id(fixture),
            id="duplicate-canonical-event-id",
        ),
        pytest.param(
            lambda fixture: _make_illegal_provider_transition(fixture),
            id="illegal-provider-transition",
        ),
        pytest.param(
            lambda fixture: _append_nonadvancing_rebuild(fixture),
            id="rebuild-without-newer-epoch-and-state-version",
        ),
        pytest.param(
            lambda fixture: _append_nonadvancing_parallel_barge_in(fixture),
            id="barge-in-does-not-advance-epoch",
        ),
        pytest.param(
            lambda fixture: _insert_rebuild_before_old_generation_candidate(
                fixture
            ),
            id="old-generation-candidate-after-rebuild",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_route_projection").update(
                source_event_seq=10_000
            ),
            id="projection-source-seq-not-existing-prefix",
        ),
    ),
)
def test_parallel_chain_mutations_fail_closed(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _committed_parallel_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "target_role",
    ("route_evidence", "candidate_safety", "composer"),
)
def test_context_projection_cannot_launder_sources_across_latest_fence(
    target_role: str,
) -> None:
    fixture = _committed_parallel_fixture()
    if target_role == "composer":
        handoff = _append_test_handoff(fixture)
        arbitration = _append_test_handoff_arbitration(fixture, handoff)
        disposition = _append_test_handoff_disposition(
            fixture,
            handoff,
            disposition="SELECTED",
            caused_by_event_id=str(arbitration["event_id"]),
            response_arbitration_event_id=str(arbitration["event_id"]),
            current_task_id="task_1",
            current_plan_version=1,
            current_task_event_seq=2,
        )
        projection = _append_test_composer_projection(
            fixture,
            handoff=handoff,
            arbitration=arbitration,
            disposition=disposition,
        )
    else:
        projection = _event_by_id(
            fixture,
            (
                "evt_route_projection"
                if target_role == "route_evidence"
                else "evt_safety_projection"
            ),
        )
    _insert_interrupt_immediately_before(fixture, projection["event_id"])

    with pytest.raises(ReplayValidationError, match="fence|prefix"):
        run_replay_fixture(fixture)


def test_delayed_projection_can_reference_a_later_immutable_prefix() -> None:
    fixture = _partial_evidence_fixture(include_safety=True)
    safety_projection = _event_by_id(fixture, "evt_safety_projection")
    safety_projection["source_event_seq"] = _event_by_id(
        fixture,
        "evt_router",
    )["event_seq"]
    safety_projection["context_snapshot_id"] = "snapshot_safety_delayed"
    _event_by_id(fixture, "evt_candidate_safety")[
        "context_snapshot_id"
    ] = "snapshot_safety_delayed"

    result = run_replay_fixture(fixture)

    assert "evt_safety_projection" in (
        result.qwen_parallel_state.context_projection_event_ids
    )


def test_context_snapshot_id_cannot_rebind_to_another_source_prefix() -> None:
    fixture = _committed_parallel_fixture()
    safety_projection = _event_by_id(fixture, "evt_safety_projection")
    safety_projection["source_event_seq"] = _event_by_id(
        fixture,
        "evt_router",
    )["event_seq"]

    with pytest.raises(ReplayValidationError, match="context_snapshot_id"):
        run_replay_fixture(fixture)


def test_context_snapshot_id_cannot_rebind_task_identity_metadata() -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_safety_projection").update(
        active_task_ref="context://synthetic/active/1",
        plan_version=1,
        task_event_seq=2,
    )

    with pytest.raises(ReplayValidationError, match="context_snapshot_id"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_output_committed").update(
                release_token_ref=OTHER_RELEASE_TOKEN_REF
            ),
            id="release-token-changes-between-gate-and-output",
        ),
        pytest.param(
            lambda fixture: _append_duplicate_delivery(fixture),
            id="duplicate-delivery-disposition",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_playback_started").update(
                qwen_output_item_id="qwen_output_item_other"
            ),
            id="native-playback-correlation-mismatch",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_delivery_full").update(
                playback_span_id="playback_other"
            ),
            id="delivery-playback-span-mismatch",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_playback_committed").update(
                caused_by_event_id="evt_output_committed"
            ),
            id="playback-commit-bypasses-start",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_delivery_full").update(
                caused_by_event_id="evt_playback_committed"
            ),
            id="delivery-bypasses-finish",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_router").update(
                router_decision="SPAWN_SLOW_TASK"
            ),
            id="gate-pass-requires-fast-only-router",
        ),
        pytest.param(
            lambda fixture: _insert_interrupt_before_stamped_playback(fixture),
            id="old-gate-token-cannot-start-after-interrupt",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate_safety").update(
                decision="UNSAFE",
                prohibited_flags=("unsafe_claim",),
            ),
            id="gate-pass-requires-safe-candidate-evidence",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_gate_passed").update(
                native_pcm_capability_check="FAIL"
            ),
            id="gate-pass-requires-all-checks-pass",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_delivery_full").update(
                actual_stop_offset_ms=499
            ),
            id="full-delivery-offset-must-match-final-coverage",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_route_evidence").update(
                risk_class="HIGH"
            ),
            id="route-high-risk-cannot-be-laundered-to-low",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate").update(
                confidence=0.7
            ),
            id="candidate-confidence-cannot-drift-from-composite",
        ),
        pytest.param(
            lambda fixture: _insert_arbitration_between_gate_and_commit(fixture),
            id="gate-and-commit-must-be-atomic-adjacent",
        ),
        pytest.param(
            lambda fixture: _insert_superseding_arbitration_before_playback(
                fixture
            ),
            id="superseded-release-cannot-start-playback",
        ),
        pytest.param(
            lambda fixture: _remove_event(
                fixture,
                "evt_shadow_verification",
            ),
            id="released-native-pcm-requires-shadow-terminal",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate").update(
                candidate_audio_duration_ms=True
            ),
            id="candidate-duration-rejects-bool",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate").update(
                candidate_audio_duration_ms=-1
            ),
            id="candidate-duration-rejects-negative",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate").update(
                candidate_audio_duration_ms=2_001
            ),
            id="candidate-duration-rejects-over-hard-cap",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_candidate").update(
                candidate_unicode_scalar_count=81
            ),
            id="candidate-scalar-count-rejects-over-hard-cap",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_shadow_verification",
            ).update(
                equivalence="MISMATCH",
                exact_numbers_entities_units_match=False,
            ),
            id="shadow-mismatch-cannot-leave-provider-clean",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_shadow_verification",
            ).update(
                normalized_transcript_digest="sha256:" + "9" * 64,
            ),
            id="shadow-normalized-digest-disagreement-requires-recovery",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_shadow_verification",
            ).update(decoded_duration_ms=499),
            id="shadow-duration-must-match-candidate",
        ),
        pytest.param(
            lambda fixture: _append_truncate_after_full(fixture),
            id="full-delivery-excludes-truncate-terminal",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_output_committed",
            ).update(user_visible_channel="text"),
            id="passed-native-output-requires-audio-pending-reconciliation",
        ),
        pytest.param(
            lambda fixture: _sync_full_delivery_offset(fixture, 600),
            id="full-playback-offset-cannot-exceed-candidate-duration",
        ),
        pytest.param(
            lambda fixture: _taint_provider_before_native_playback(fixture),
            id="native-first-byte-requires-current-clean-provider",
        ),
    ),
)
def test_native_release_mutations_fail_closed(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _native_release_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_selected_handoff_without_matching_arbitration_fails_closed() -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    _append(
        fixture,
        "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
        "evt_handoff_selected",
        caused_by_event_id=handoff["event_id"],
        handoff_id="handoff_1",
        disposition="SELECTED",
        reason="selected_without_arbitration",
    )

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_capability_snapshot",
            )["deployment_modes"].__setitem__(0, "remote_api"),
            id="not-provider-free",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_capability_snapshot").update(
                capability_version="slice3b1.other.v1"
            ),
            id="wrong-capability-version",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_asr_final").pop(
                "qwen_input_item_ref"
            ),
            id="missing-qwen-correlation",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_asr_final").update(
                qwen_input_item_ref=(
                    "https://provider.invalid/item?api_key=synthetic-secret"
                )
            ),
            id="credential-like-qwen-input-item-ref",
        ),
        pytest.param(
            lambda fixture: _event_by_id(fixture, "evt_asr_final").update(
                qwen_input_content_index="0"
            ),
            id="non-integer-qwen-input-content-index",
        ),
        pytest.param(
            lambda fixture: _forge_qwen_asr_adapter_id(fixture),
            id="forged-qwen-asr-adapter-id",
        ),
        pytest.param(
            lambda fixture: _event_by_id(
                fixture,
                "evt_capability_snapshot",
            ).update(capability_matrix_digest="sha256:" + "z" * 64),
            id="non-hex-capability-matrix-digest",
        ),
    ),
)
def test_mock_qwen_asr_requires_exact_provider_free_capability_evidence(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    fixture = _committed_parallel_fixture()
    mutation(fixture)

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_rejected_turn_cannot_gain_downstream_parallel_authority() -> None:
    fixture = _rejected_parallel_fixture()
    _append(
        fixture,
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "evt_illegal_asr",
        caused_by_event_id="evt_turn_rejected",
        adapter_id="slice3b1_qwen_realtime_asr_projection",
        adapter_type="asr",
        adapter_request_id="qwen_asr_request_illegal",
        turn_id="turn_1",
        utterance_id="utt_illegal",
        input_modality="audio",
        audio_span_id="audio_1",
        asr_frame_ref="asr-frame://synthetic/illegal",
        text_ref="text-ref://synthetic/illegal",
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
        provider_session_generation=1,
        qwen_input_item_ref="qwen-input-item://synthetic/illegal",
        qwen_input_content_index=0,
    )

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_replay_does_not_call_qwen_wire_or_route_evidence_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.adapters.qwen_realtime.scripted_wire import (
        ScriptedFakeQwenWire,
    )
    from voice_agent.adapters.qwen_realtime.session_adapter import (
        QwenRealtimeSessionAdapter,
    )
    from voice_agent.adapters.route_evidence_fake import FakeRouteEvidenceAdapter
    from voice_agent.runtime.slice3b1.orchestrator import (
        ParallelFastInteractionOrchestrator,
    )

    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay must consume canonical events only")

    def forbidden_sync(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay must consume canonical events only")

    monkeypatch.setattr(ScriptedFakeQwenWire, "open", forbidden)
    monkeypatch.setattr(ScriptedFakeQwenWire, "send", forbidden)
    monkeypatch.setattr(ScriptedFakeQwenWire, "recv", forbidden)
    monkeypatch.setattr(
        QwenRealtimeSessionAdapter,
        "attach_open_transport",
        forbidden,
    )
    monkeypatch.setattr(QwenRealtimeSessionAdapter, "append_audio", forbidden)
    monkeypatch.setattr(
        QwenRealtimeSessionAdapter,
        "bind_committed_turn",
        forbidden_sync,
    )
    monkeypatch.setattr(FakeRouteEvidenceAdapter, "classify_route", forbidden)
    monkeypatch.setattr(
        FakeRouteEvidenceAdapter,
        "classify_candidate_safety",
        forbidden,
    )
    monkeypatch.setattr(
        ParallelFastInteractionOrchestrator,
        "emit",
        forbidden_sync,
    )

    result = run_replay_fixture(_committed_parallel_fixture())

    assert result.result_status == "passed"


@pytest.mark.parametrize(
    ("fixture_kind", "event_id", "field", "value"),
    (
        pytest.param(
            "committed",
            "evt_route_evidence",
            "raw_prompt",
            "unredacted route prompt",
            id="route-raw-prompt",
        ),
        pytest.param(
            "committed",
            "evt_route_evidence",
            "Raw_Prompt",
            "case-variant unredacted route prompt",
            id="route-case-variant-raw-prompt",
        ),
        pytest.param(
            "committed",
            "evt_route_projection",
            "provider_payload",
            {"candidate": "provider body"},
            id="projection-provider-payload",
        ),
        pytest.param(
            "committed",
            "evt_candidate_safety",
            "api_key",
            "sk-synthetic-should-never-replay",
            id="safety-secret-field",
        ),
        pytest.param(
            "committed",
            "evt_provider_clean",
            "Diagnostic_Ref",
            "https://provider.example/raw/session",
            id="provider-mixed-case-unsafe-ref",
        ),
        pytest.param(
            "committed",
            "evt_fast_composite",
            "provider_response",
            {"output": "raw provider response"},
            id="parallel-fast-provider-response",
        ),
        pytest.param(
            "native",
            "evt_gate_passed",
            "cookie",
            "session=unsafe",
            id="gate-cookie",
        ),
        pytest.param(
            "native",
            "evt_shadow_verification",
            "raw_pcm",
            "base64-raw-pcm",
            id="shadow-raw-pcm",
        ),
        pytest.param(
            "native",
            "evt_delivery_full",
            "authorization",
            {"header": "Bearer unsafe"},
            id="delivery-authorization",
        ),
    ),
)
def test_adr018_events_reject_nested_raw_provider_and_secret_payloads(
    fixture_kind: str,
    event_id: str,
    field: str,
    value: object,
) -> None:
    fixture = (
        _native_release_fixture()
        if fixture_kind == "native"
        else _committed_parallel_fixture()
    )
    _event_by_id(fixture, event_id)["debug"] = {field: value}

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    (
        pytest.param(
            "ingress",
            "raw_prompt",
            "sensitive prompt text",
            id="ingress-nested-raw-prompt",
        ),
        pytest.param(
            "slowtask_source",
            "provider_payload",
            {"output": "raw slow provider body"},
            id="slowtask-source-nested-provider-payload",
        ),
    ),
)
def test_adr018_session_payload_guard_covers_every_event(
    target: str,
    field: str,
    value: object,
) -> None:
    fixture = _committed_parallel_fixture()
    if target == "ingress":
        event = _event_by_id(fixture, "evt_turn_committed")
    else:
        event = _append_current_progress_source(fixture)
        handoff = _append_test_handoff(fixture, source_event=event)
        _append_test_handoff_disposition(
            fixture,
            handoff,
            disposition="QUEUED",
        )
    event["debug"] = {field: value}

    with pytest.raises(ReplayValidationError):
        run_replay_fixture(fixture)


def test_adr018_session_payload_guard_preserves_safe_canonical_prompt_ref() -> None:
    fixture = _committed_parallel_fixture()
    _append_current_progress_source(fixture)
    confirmation = _append(
        fixture,
        "CONFIRMATION_REQUIRED",
        "evt_handoff_confirmation_required",
        caused_by_event_id="evt_handoff_progress",
        source_module="slowtask_runtime",
        confirmation_id="confirmation_1",
        task_id="task_1",
        plan_version=1,
        task_event_seq=3,
        confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
        required_for_event_id="evt_output_discarded",
        prompt_ref="prompt://synthetic/confirmation/1",
    )
    handoff = _append_test_handoff(
        fixture,
        source_event=confirmation,
        kind="CONFIRMATION",
    )
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="QUEUED",
    )

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.handoff_dispositions["handoff_1"] == (
        "QUEUED"
    )


def test_adr018_closed_world_rejects_unknown_pcm_blob_on_legacy_event() -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_session_started")["pcm_blob"] = "AAECAw=="

    with pytest.raises(ReplayValidationError, match="field|pcm_blob"):
        run_replay_fixture(fixture)


def test_adr018_closed_world_rejects_nested_renamed_raw_payload() -> None:
    fixture = _native_truncated_fixture()
    _event_by_id(fixture, "evt_interrupt_native")["confidence_summary"] = {
        "encoded_samples": "AAECAw==",
    }

    with pytest.raises(ReplayValidationError, match="field|encoded_samples"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("nested_field", "nested_value"),
    (
        pytest.param(
            "candidate_pcm_manifest_digest",
            PCM_MANIFEST_DIGEST,
            id="canonical-digest-camouflage",
        ),
        pytest.param(
            "event_id",
            "evt_nested_camouflage",
            id="canonical-identity-camouflage",
        ),
        pytest.param(
            "reason",
            {"event_id": "evt_nested_reason_camouflage"},
            id="canonical-reason-camouflage",
        ),
    ),
)
def test_adr018_confidence_summary_rejects_parent_schema_smuggling(
    nested_field: str,
    nested_value: object,
) -> None:
    fixture = _native_truncated_fixture()
    _event_by_id(fixture, "evt_interrupt_native")["confidence_summary"] = {
        nested_field: nested_value,
    }

    with pytest.raises(
        ReplayValidationError,
        match="confidence_summary|nested field|schema",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "unsafe_reason",
    (
        pytest.param(
            {"event_id": "evt_reason_camouflage"},
            id="mapping",
        ),
        pytest.param(["synthetic_reason"], id="sequence"),
        pytest.param(bytearray(b"synthetic_reason"), id="bytearray"),
    ),
)
def test_adr018_singular_reason_requires_symbolic_string(
    unsafe_reason: object,
) -> None:
    fixture = _native_release_fixture()
    _event_by_id(fixture, "evt_provider_clean")["reason"] = unsafe_reason

    with pytest.raises(
        ReplayValidationError,
        match="reason|symbolic|string|safe code",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "binary_value",
    (
        pytest.param(bytearray(b"session_runtime"), id="bytearray"),
        pytest.param(memoryview(b"session_runtime"), id="memoryview"),
    ),
)
def test_adr018_binary_metadata_containers_fail_closed(
    binary_value: object,
) -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_session_started")[
        "source_module"
    ] = binary_value

    with pytest.raises(ReplayValidationError, match="binary|source_module"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "unsafe_confidence",
    (
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(True, id="boolean"),
        pytest.param("0.5", id="string"),
        pytest.param(-0.1, id="below-range"),
        pytest.param(1.1, id="above-range"),
    ),
)
def test_adr018_confidence_summary_enforces_finite_unit_interval_numbers(
    unsafe_confidence: object,
) -> None:
    fixture = _native_truncated_fixture()
    _event_by_id(fixture, "evt_interrupt_native")["confidence_summary"] = {
        "echo_likelihood": "low",
        "vad_confidence": unsafe_confidence,
        "barge_in_confidence": 0.94,
    }

    with pytest.raises(
        ReplayValidationError,
        match="confidence|finite|range|number",
    ):
        run_replay_fixture(fixture)


def test_adr018_identity_metadata_rejects_short_prose() -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_session_started")[
        "source_module"
    ] = "short arbitrary prose"

    with pytest.raises(
        ReplayValidationError,
        match="source_module|symbolic|identity",
    ):
        run_replay_fixture(fixture)


def test_adr018_confidence_summary_rejects_private_prose() -> None:
    fixture = _native_truncated_fixture()
    _event_by_id(fixture, "evt_interrupt_native")[
        "confidence_summary"
    ] = "raw user utterance with private text"

    with pytest.raises(
        ReplayValidationError,
        match="confidence_summary|symbolic",
    ):
        run_replay_fixture(fixture)


def test_adr018_registered_thinker_hint_is_symbolic_by_default() -> None:
    fixture = _adr018_historical_mvp3_fixture()
    event = next(
        candidate
        for candidate in fixture["events"]
        if candidate["event_name"]
        == "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"
    )
    event["complexity_hint"] = (
        "summarize the private user request in detail"
    )

    with pytest.raises(
        ReplayValidationError,
        match="complexity_hint|symbolic",
    ):
        run_replay_fixture(fixture)


def test_adr018_registered_handoff_style_hint_is_symbolic_by_default(
) -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    handoff["response_style_hint"] = (
        "repeat the private user utterance verbatim"
    )
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="QUEUED",
    )

    with pytest.raises(
        ReplayValidationError,
        match="response_style_hint|symbolic",
    ):
        run_replay_fixture(fixture)


def test_adr018_preserves_canonical_bounded_redacted_text() -> None:
    fixture = _adr018_redacted_text_fixture()

    result = run_replay_fixture(fixture)

    text_input = next(
        event
        for event in result.ordered_events
        if event["event_name"] == "TEXT_INPUT_RECEIVED"
    )
    assert text_input["redacted_text"] == (
        "[synthetic text: hello assistant]"
    )


def test_adr018_closed_world_preserves_structured_confidence_summary() -> None:
    fixture = _native_truncated_fixture()
    _event_by_id(fixture, "evt_interrupt_native")["confidence_summary"] = {
        "echo_likelihood": "high",
        "vad_confidence": 0.96,
        "barge_in_confidence": 0.94,
    }

    result = run_replay_fixture(fixture)

    interrupt = next(
        event
        for event in result.ordered_events
        if event["event_id"] == "evt_interrupt_native"
    )
    assert interrupt["confidence_summary"] == {
        "echo_likelihood": "high",
        "vad_confidence": 0.96,
        "barge_in_confidence": 0.94,
    }


@pytest.mark.parametrize(
    ("event_id", "reason_field", "unsafe_reason"),
    (
        pytest.param(
            "evt_provider_clean",
            "reason",
            "provider cleanup explanation " * 8_000,
            id="unbounded-provider-context-reason",
        ),
        pytest.param(
            "evt_arbitration_select_user_fast",
            "decision_reason",
            "the response was selected because this is unrestricted prose",
            id="prose-response-arbitration-decision-reason",
        ),
    ),
)
def test_adr018_reason_fields_require_bounded_safe_codes(
    event_id: str,
    reason_field: str,
    unsafe_reason: str,
) -> None:
    fixture = _native_release_fixture()
    if event_id == "evt_arbitration_select_user_fast":
        _insert_user_fast_arbitration_before_playback(
            fixture,
            selected_source_event_id="evt_output_committed",
        )
    _event_by_id(fixture, event_id)[reason_field] = unsafe_reason

    with pytest.raises(ReplayValidationError, match="reason|safe code|bounded"):
        run_replay_fixture(fixture)


def test_adr018_non_reason_string_metadata_has_finite_bound() -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_session_started")[
        "source_module"
    ] = "x" * 1_025

    with pytest.raises(ReplayValidationError, match="bounded metadata string"):
        run_replay_fixture(fixture)


def test_adr018_closed_world_preserves_bounded_safe_reasons_and_refs() -> None:
    fixture = _native_release_fixture()
    _event_by_id(fixture, "evt_provider_clean")[
        "reason"
    ] = "session_config_validated"
    _insert_user_fast_arbitration_before_playback(
        fixture,
        selected_source_event_id="evt_output_committed",
    )
    _event_by_id(fixture, "evt_arbitration_select_user_fast")[
        "decision_reason"
    ] = "low_risk_chat_selected"
    _event_by_id(fixture, "evt_session_started")[
        "runtime_config_ref"
    ] = "config://synthetic/slice3b1/bounded-safe"

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.provider_context_state == "CLEAN"
    assert "evt_arbitration_select_user_fast" in (
        result.qwen_parallel_state.response_arbitration_event_ids
    )


def test_non_adr_legacy_fixture_preserves_unknown_field_compatibility() -> None:
    fixture = _empty_fixture("legacy-open-world")
    _append(
        fixture,
        "SESSION_STARTED",
        "evt_legacy_session_started",
        runtime_config_ref="config://synthetic/legacy/open-world",
        capability_snapshot_ref="capability://synthetic/legacy/open-world",
        pcm_blob="AAECAw==",
    )

    result = run_replay_fixture(fixture)

    assert result.ordered_events[0]["pcm_blob"] == "AAECAw=="


def test_non_adr_legacy_fixture_preserves_bytearray_envelope_behavior() -> None:
    fixture = _empty_fixture("legacy-bytearray-open-world")
    _append(
        fixture,
        "SESSION_STARTED",
        "evt_legacy_bytearray_session_started",
        runtime_config_ref="config://synthetic/legacy/open-world",
        capability_snapshot_ref="capability://synthetic/legacy/open-world",
    )
    fixture["events"][0]["source_module"] = bytearray(b"legacy_runtime")

    result = run_replay_fixture(fixture)

    assert result.ordered_events[0]["source_module"] == bytearray(
        b"legacy_runtime"
    )


def test_adr018_session_preserves_accepted_historical_slowtask_tts_shapes(
) -> None:
    fixture = _adr018_historical_mvp3_fixture()

    source_evidence = next(
        event
        for event in fixture["events"]
        if event["event_name"] == "SLOWTASK_CREATED"
    )
    tts_output = next(
        event
        for event in fixture["events"]
        if event["event_name"] == "TTS_SYNTHESIS_OUTPUT_EMITTED"
    )
    assert "source_evidence_refs" in source_evidence
    assert (tts_output["task_id"], tts_output["plan_version"]) == (
        "task_mvp3_slice8",
        2,
    )

    result = run_replay_fixture(fixture)

    replayed_slowtask = next(
        event
        for event in result.ordered_events
        if event["event_name"] == "SLOWTASK_CREATED"
    )
    replayed_tts = next(
        event
        for event in result.ordered_events
        if event["event_name"] == "TTS_SYNTHESIS_OUTPUT_EMITTED"
    )
    assert replayed_slowtask["source_evidence_refs"] == (
        source_evidence["source_evidence_refs"]
    )
    assert (replayed_tts["task_id"], replayed_tts["plan_version"]) == (
        "task_mvp3_slice8",
        2,
    )


@pytest.mark.parametrize(
    "accepted_failure_reason",
    (
        pytest.param("provider_timeout", id="symbolic-code"),
        pytest.param(
            "missing_required_field: resolved_arguments_ref",
            id="structured-diagnostic",
        ),
    ),
)
def test_adr018_failure_reasons_preserve_structured_diagnostics(
    accepted_failure_reason: str,
) -> None:
    fixture = _adr018_historical_mvp3_fixture()
    validation_failed = next(
        event
        for event in fixture["events"]
        if event["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    )
    validation_failed["failure_reasons"] = [accepted_failure_reason]

    result = run_replay_fixture(fixture)

    replayed_failure = next(
        event
        for event in result.ordered_events
        if event["event_id"] == validation_failed["event_id"]
    )
    assert replayed_failure["failure_reasons"] == [accepted_failure_reason]


@pytest.mark.parametrize(
    "unsafe_failure_reason",
    (
        pytest.param(
            "unrestricted diagnostic prose",
            id="unrestricted-prose",
        ),
        pytest.param(
            "missing_required_field: unsafe diagnostic prose",
            id="prose-detail",
        ),
        pytest.param(
            "missing required field: resolved_arguments_ref",
            id="prose-category",
        ),
    ),
)
def test_adr018_failure_reasons_reject_unrestricted_prose(
    unsafe_failure_reason: str,
) -> None:
    fixture = _adr018_historical_mvp3_fixture()
    validation_failed = next(
        event
        for event in fixture["events"]
        if event["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    )
    validation_failed["failure_reasons"] = [unsafe_failure_reason]

    with pytest.raises(
        ReplayValidationError,
        match="failure_reasons|structured|symbolic",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "unsafe_ref",
    (
        pytest.param(
            "my ssn is 123-45-6789",
            id="plain-text-laundered-as-ref",
        ),
        pytest.param(
            "handoff-facts://synthetic/" + "x" * 600,
            id="oversized-opaque-ref",
        ),
    ),
)
def test_adr018_refs_require_bounded_opaque_uri_grammar(
    unsafe_ref: str,
) -> None:
    fixture = _committed_parallel_fixture()
    handoff = _append_test_handoff(fixture)
    handoff["facts_ref"] = unsafe_ref
    _append_test_handoff_disposition(
        fixture,
        handoff,
        disposition="QUEUED",
    )

    with pytest.raises(ReplayValidationError, match="safe ref"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "binary_value",
    (
        pytest.param(bytearray(b"hidden-adr018"), id="bytearray"),
        pytest.param(memoryview(b"hidden-adr018"), id="memoryview"),
    ),
)
def test_same_text_nonplain_event_name_cannot_hide_adr018_binary_payload(
    binary_value: object,
) -> None:
    fixture = _adr018_redacted_text_fixture()
    for event in fixture["events"]:
        if event["event_name"] == "PROVIDER_CONTEXT_STATE_CHANGED":
            event["event_name"] = _HashSkewedStr(
                "PROVIDER_CONTEXT_STATE_CHANGED"
            )
    _event_by_id(fixture, "evt_redacted_text_session_started")[
        "source_module"
    ] = binary_value

    with pytest.raises(ReplayValidationError, match="ADR-018|binary|plain"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("target_event_id", "field", "nonplain_value"),
    (
        pytest.param(
            "evt_session_started",
            "source_module",
            _HashSkewedStr("slice3b1_replay_test"),
            id="string-subclass",
        ),
        pytest.param(
            "evt_interrupt_native",
            "confidence_summary",
            UserDict(
                {
                    "echo_likelihood": "high",
                    "vad_confidence": 0.96,
                    "barge_in_confidence": 0.94,
                }
            ),
            id="mapping-subclass",
        ),
        pytest.param(
            "evt_capability_snapshot",
            "adapter_ids",
            UserList(
                [
                    "slice3b1_qwen_realtime_asr_projection",
                    "slice3b1_qwen_realtime_fake",
                    "slice3b1_parallel_fast_interaction_orchestrator",
                    "slice3b1_route_evidence_fake",
                ]
            ),
            id="sequence-subclass",
        ),
    ),
)
def test_adr018_canonical_payload_requires_plain_container_types(
    target_event_id: str,
    field: str,
    nonplain_value: object,
) -> None:
    fixture = (
        _native_truncated_fixture()
        if target_event_id == "evt_interrupt_native"
        else _committed_parallel_fixture()
    )
    _event_by_id(fixture, target_event_id)[field] = nonplain_value

    with pytest.raises(ReplayValidationError, match="plain|container|string"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize("evidence_role", ("route", "safety"))
@pytest.mark.parametrize("terminal_order", ("before", "after"))
def test_bound_evidence_terminal_uses_normalized_exact_request_pair(
    evidence_role: str,
    terminal_order: str,
) -> None:
    fixture = _committed_parallel_fixture()
    event_id = (
        "evt_route_evidence"
        if evidence_role == "route"
        else "evt_candidate_safety"
    )
    success = _event_by_id(fixture, event_id)
    request_id = str(success["adapter_request_id"])
    success["adapter_request_id"] = _HashSkewedStr(request_id)
    terminal = _base_event(
        "ADAPTER_REQUEST_FAILED",
        f"evt_{evidence_role}_same_pair_terminal_{terminal_order}",
        caused_by_event_id=(
            "evt_route_projection"
            if evidence_role == "route"
            else "evt_candidate_safety_projection"
        ),
        adapter_id=str(success["adapter_id"]),
        adapter_type="route_evidence",
        adapter_request_id=request_id,
        failure_reason="synthetic_exact_pair_terminal",
        retryable=False,
        output_mode="mock",
    )
    if terminal_order == "before":
        _insert_event_before(
            fixture,
            target_event_id=event_id,
            event=terminal,
        )
    else:
        terminal["caused_by_event_id"] = "evt_output_discarded"
        fixture["events"].append(terminal)
        _resequence(fixture)

    with pytest.raises(
        ReplayValidationError,
        match="request|terminal|plain|string",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "invalid_number",
    (
        pytest.param(True, id="boolean"),
        pytest.param(-1, id="negative"),
        pytest.param(0.5, id="fractional"),
        pytest.param(2**63, id="huge"),
    ),
)
def test_adr018_timestamps_require_bounded_nonnegative_integers(
    invalid_number: object,
) -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_session_started")[
        "created_monotonic_ms"
    ] = invalid_number

    with pytest.raises(
        ReplayValidationError,
        match="created_monotonic_ms|integer|bounded",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    "invalid_count",
    (
        pytest.param(True, id="boolean"),
        pytest.param(-1, id="negative"),
        pytest.param(0.5, id="fractional"),
        pytest.param(2**31, id="huge"),
    ),
)
def test_adr018_counts_require_bounded_nonnegative_integers(
    invalid_count: object,
) -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_provider_clean")[
        "cleanup_item_count"
    ] = invalid_count

    with pytest.raises(
        ReplayValidationError,
        match="cleanup_item_count|integer|bounded",
    ):
        run_replay_fixture(fixture)


def test_adr018_huge_confidence_fails_with_controlled_validation_error(
) -> None:
    fixture = _committed_parallel_fixture()
    _event_by_id(fixture, "evt_route_evidence")[
        "confidence"
    ] = 10**10_000

    with pytest.raises(
        ReplayValidationError,
        match="confidence|finite|range|number",
    ):
        run_replay_fixture(fixture)


def test_adr018_accepts_canonical_integer_boundary_values() -> None:
    fixture = _committed_parallel_fixture()
    session = _event_by_id(fixture, "evt_session_started")
    session["created_monotonic_ms"] = 0
    session["created_wall_clock_ms"] = 9_007_199_254_740_991
    rebuilding = _event_by_id(fixture, "evt_provider_rebuilding")
    clean = _event_by_id(fixture, "evt_provider_clean")
    rebuilding["dropped_audio_frame_count"] = 2_147_483_647
    clean["dropped_audio_frame_count"] = 2_147_483_647
    clean["cleanup_item_count"] = 2_147_483_647

    result = run_replay_fixture(fixture)

    assert result.qwen_parallel_state.dropped_audio_frame_count == (
        2_147_483_647
    )


@pytest.mark.parametrize(
    ("event_id", "field", "value"),
    (
        pytest.param(
            "evt_interrupt_native",
            "audio_span_id",
            "audio_1",
            id="interrupt-controller-audio-span",
        ),
        pytest.param(
            "evt_truncate_requested_native",
            "audio_span_id",
            "audio_1",
            id="truncate-controller-audio-span",
        ),
        pytest.param(
            "evt_tts_truncated_native",
            "final_playback_offset_ms",
            250,
            id="talker-final-playback-offset",
        ),
    ),
)
def test_adr018_accepts_interrupt_and_truncate_producer_optional_fields(
    event_id: str,
    field: str,
    value: object,
) -> None:
    fixture = _native_truncated_fixture()
    _event_by_id(fixture, event_id)[field] = value

    result = run_replay_fixture(fixture)

    replayed = next(
        event
        for event in result.ordered_events
        if event["event_id"] == event_id
    )
    assert replayed[field] == value


@pytest.mark.parametrize(
    ("field", "value"),
    (
        pytest.param("audio_span_id", None, id="text-producer-null-audio-span"),
        pytest.param("language_hint", "en-US", id="text-language-hint"),
    ),
)
def test_adr018_accepts_documented_text_input_optional_fields(
    field: str,
    value: object,
) -> None:
    fixture = _adr018_redacted_text_fixture()
    _event_by_id(fixture, "evt_redacted_text_input")[field] = value

    result = run_replay_fixture(fixture)

    replayed = _ordered_event_by_id(result, "evt_redacted_text_input")
    assert replayed[field] == value


def test_adr018_accepts_documented_low_confidence_policy_ref() -> None:
    fixture = _rejected_parallel_fixture()
    _append(
        fixture,
        "LOW_CONFIDENCE_INGRESS",
        "evt_low_confidence_ingress",
        caused_by_event_id="evt_turn_rejected",
        audio_span_id="audio_1",
        confidence_fields=(),
        ingress_reason="provider_smart_turn_uncertain",
        policy_ref="policy://synthetic/ingress/low-confidence-v1",
    )

    result = run_replay_fixture(fixture)

    assert _ordered_event_by_id(
        result,
        "evt_low_confidence_ingress",
    )["policy_ref"] == "policy://synthetic/ingress/low-confidence-v1"


def test_adr018_accepts_documented_playback_progress_basis() -> None:
    fixture = _native_release_fixture()
    progress = _base_event(
        "PLAYBACK_PROGRESS",
        "evt_native_playback_progress",
        caused_by_event_id="evt_playback_started",
        playback_span_id="playback_1",
        playback_offset_ms=100,
        progress_basis="provider_offset",
    )
    _insert_event_before(
        fixture,
        target_event_id="evt_playback_committed",
        event=progress,
    )
    _event_by_id(fixture, "evt_playback_committed")[
        "caused_by_event_id"
    ] = "evt_native_playback_progress"

    result = run_replay_fixture(fixture)

    assert _ordered_event_by_id(
        result,
        "evt_native_playback_progress",
    )["progress_basis"] == "provider_offset"


def test_adr018_accepts_documented_invalid_output_ref() -> None:
    fixture = _committed_parallel_fixture()
    _append(
        fixture,
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "evt_unrelated_validation_failed",
        caused_by_event_id="evt_output_discarded",
        adapter_id="slice3b1_unrelated_validator",
        adapter_type="slow_llm",
        adapter_request_id="unrelated_validation_request_1",
        schema_name="voice_agent.synthetic.v1",
        failure_reasons=("invalid_synthetic_output",),
        invalid_output_ref="invalid-output://synthetic/unrelated/1",
        output_mode="mock",
    )

    result = run_replay_fixture(fixture)

    assert _ordered_event_by_id(
        result,
        "evt_unrelated_validation_failed",
    )["invalid_output_ref"] == "invalid-output://synthetic/unrelated/1"


def test_adr018_accepts_mock_understanding_producer_provenance() -> None:
    fixture = _adr018_mock_text_understanding_fixture()

    result = run_replay_fixture(fixture)

    mock_asr = _ordered_event_by_id(result, "evt_mock_text_asr")
    mock_thinker = _ordered_event_by_id(result, "evt_mock_text_thinker")
    assert mock_asr["text_span_id"] == "text_redacted_text_1"
    assert mock_thinker["input_modality"] == "text"


def test_adr018_accepts_real_thinker_text_span_id() -> None:
    fixture = _adr018_real_text_thinker_fixture()

    result = run_replay_fixture(fixture)

    thinker = _ordered_event_by_id(result, "evt_real_text_thinker")
    assert thinker["text_span_id"] == "text_redacted_text_1"


def test_actual_user_patch_runtime_event_replays_in_adr018_session() -> None:
    fixture = _adr018_actual_user_patch_fixture()

    result = run_replay_fixture(fixture)

    patch = _ordered_event_by_id(
        result,
        "evt_mvp1_slice6_user_patch_received",
    )
    assert patch["authoritative_evidence_refs"] == [
        "text://synthetic/mvp1/slice6/patch-redacted",
        "asr-frame://synthetic/mvp1/slice6/patch",
    ]
    task_focus_provenance = patch["evidence_pack"][
        "non_authoritative_hypothesis"
    ]["provenance"]["task_focus"]
    assert task_focus_provenance["evidence_ref"] == (
        "evt_mvp1_slice6_patch_router"
    )


@pytest.mark.parametrize(
    "unsafe_evidence_ref",
    (
        pytest.param(
            "/Users/example/private/patch",
            id="absolute-path",
        ),
        pytest.param(
            "https://provider.example/private-output",
            id="provider-url",
        ),
        pytest.param(
            "unrestricted private provenance prose",
            id="plain-prose",
        ),
        pytest.param(
            "evt malformed provenance id",
            id="malformed-event-id",
        ),
    ),
)
def test_user_patch_event_id_evidence_ref_rejects_unsafe_values(
    unsafe_evidence_ref: str,
) -> None:
    fixture = _adr018_actual_user_patch_fixture()
    patch = _event_by_id(
        fixture,
        "evt_mvp1_slice6_user_patch_received",
    )
    patch["evidence_pack"]["non_authoritative_hypothesis"][
        "provenance"
    ]["task_focus"]["evidence_ref"] = unsafe_evidence_ref

    with pytest.raises(
        ReplayValidationError,
        match="evidence_ref|safe|event",
    ):
        run_replay_fixture(fixture)


def test_adr018_mixed_non_string_event_keys_fail_with_controlled_error(
) -> None:
    fixture = _committed_parallel_fixture()
    event = _event_by_id(fixture, "evt_session_started")
    event["unknown_alias"] = "synthetic_alias"
    event[7] = "synthetic_numeric_key"

    with pytest.raises(
        ReplayValidationError,
        match="key|field|plain string",
    ):
        run_replay_fixture(fixture)


def _committed_parallel_fixture() -> dict[str, Any]:
    fixture = _empty_fixture("committed")
    _append(
        fixture,
        "SESSION_STARTED",
        "evt_session_started",
        runtime_config_ref="config://synthetic/slice3b1",
        capability_snapshot_ref="capability://synthetic/slice3b1/provider-free",
    )
    _append(
        fixture,
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "evt_capability_snapshot",
        caused_by_event_id="evt_session_started",
        capability_snapshot_ref="capability://synthetic/slice3b1/provider-free",
        adapter_ids=[
            "slice3b1_qwen_realtime_asr_projection",
            "slice3b1_qwen_realtime_fake",
            "slice3b1_parallel_fast_interaction_orchestrator",
            "slice3b1_route_evidence_fake",
        ],
        adapter_types=[
            "asr",
            "duplex_model",
            "fast_interaction",
            "route_evidence",
        ],
        deployment_modes=[
            "provider_free",
            "provider_free",
            "provider_free",
            "provider_free",
        ],
        output_modes=["mock", "mock", "mock", "mock"],
        capability_version="slice3b1.mock.v1",
        capability_matrix_digest="sha256:" + "a" * 64,
    )
    _append_provider_ready(fixture)
    _append_committed_audio_turn(fixture)
    _append_parallel_understanding_and_output(fixture)
    return fixture


def _rejected_parallel_fixture() -> dict[str, Any]:
    fixture = _empty_fixture("rejected")
    _append(
        fixture,
        "SESSION_STARTED",
        "evt_session_started",
        runtime_config_ref="config://synthetic/slice3b1",
        capability_snapshot_ref="capability://synthetic/slice3b1/provider-free",
    )
    _append(
        fixture,
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "evt_capability_snapshot",
        caused_by_event_id="evt_session_started",
        capability_snapshot_ref="capability://synthetic/slice3b1/provider-free",
        adapter_ids=[
            "slice3b1_qwen_realtime_asr_projection",
            "slice3b1_qwen_realtime_fake",
            "slice3b1_parallel_fast_interaction_orchestrator",
            "slice3b1_route_evidence_fake",
        ],
        adapter_types=[
            "asr",
            "duplex_model",
            "fast_interaction",
            "route_evidence",
        ],
        deployment_modes=[
            "provider_free",
            "provider_free",
            "provider_free",
            "provider_free",
        ],
        output_modes=["mock", "mock", "mock", "mock"],
        capability_version="slice3b1.mock.v1",
        capability_matrix_digest="sha256:" + "a" * 64,
    )
    _append_provider_ready(fixture)
    _append_audio_lifecycle_through_speech_end(
        fixture,
        provider_stop_reason="turn_invalid",
    )
    _append(
        fixture,
        "TURN_INGRESS_REJECTED",
        "evt_turn_rejected",
        caused_by_event_id="evt_speech_end",
        turn_id="turn_1",
        audio_span_id="audio_1",
        reject_reason="provider_smart_turn_invalid",
        ingress_outcome="REJECTED",
    )
    return fixture


def _native_release_fixture() -> dict[str, Any]:
    fixture = _committed_parallel_fixture()
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] not in {"evt_gate_failed", "evt_output_discarded"}
    ]
    _append(
        fixture,
        "FOREGROUND_ACT_GATE_PASSED",
        "evt_gate_passed",
        caused_by_event_id="evt_router",
        gate_decision_id="gate_decision_passed",
        candidate_event_id="evt_candidate",
        router_decision_event_id="evt_router",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.98,
        policy_version="slice3b1.fast_foreground_gate.v1",
        pass_reason="all_parallel_checks_passed",
        fast_interaction_topology=PARALLEL_TOPOLOGY,
        candidate_check_policy_version="slice3b1.candidate_checks.v1",
        candidate_length_check="PASS",
        candidate_duration_check="PASS",
        candidate_terminal_check="PASS",
        native_pcm_capability_check="PASS",
        generation_check="PASS",
        context_snapshot_check="PASS",
        route_evidence_check="PASS",
        candidate_safety_check="PASS",
        transcript_digest_check="PASS",
        pcm_manifest_check="PASS",
        correlation_check="PASS",
        provider_session_generation=1,
        context_snapshot_id="snapshot_1",
        route_evidence_event_id="evt_route_evidence",
        candidate_safety_evidence_event_id="evt_candidate_safety",
        release_token_ref=RELEASE_TOKEN_REF,
        output_mode="mock",
    )
    _append(
        fixture,
        "FOREGROUND_OUTPUT_COMMITTED",
        "evt_output_committed",
        caused_by_event_id="evt_gate_passed",
        foreground_output_id="foreground_output_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        output_ref="candidate-ref://synthetic/1",
        output_basis="reply_candidate",
        router_decision_event_id="evt_router",
        gate_event_id="evt_gate_passed",
        user_visible_channel="audio_pending",
        foreground_act="ANSWER",
        fast_interaction_topology=PARALLEL_TOPOLOGY,
        release_token_ref=RELEASE_TOKEN_REF,
        output_mode="mock",
    )
    _append(
        fixture,
        "PLAYBACK_SPAN_STARTED",
        "evt_playback_started",
        caused_by_event_id="evt_output_committed",
        playback_span_id="playback_1",
        audio_ref="audio-ref://memory-only/candidate-1",
        release_token_ref=RELEASE_TOKEN_REF,
        provider_session_generation=1,
        context_snapshot_id="snapshot_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        candidate_id="cand_1",
        qwen_response_id="qwen_response_1",
        qwen_output_item_id="qwen_output_item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        candidate_pcm_manifest_digest=PCM_MANIFEST_DIGEST,
        playback_epoch=0,
    )
    _append(
        fixture,
        "PLAYBACK_COMMITTED",
        "evt_playback_committed",
        caused_by_event_id="evt_playback_started",
        playback_span_id="playback_1",
        playback_offset_ms=500,
        commit_basis="provider_native_pcm",
        release_token_ref=RELEASE_TOKEN_REF,
    )
    _append(
        fixture,
        "PLAYBACK_FINISHED",
        "evt_playback_finished",
        caused_by_event_id="evt_playback_committed",
        playback_span_id="playback_1",
        final_playback_offset_ms=500,
        release_token_ref=RELEASE_TOKEN_REF,
    )
    delivery = _append(
        fixture,
        "ASSISTANT_DELIVERY_DISPOSITIONED",
        "evt_delivery_full",
        caused_by_event_id="evt_playback_finished",
        assistant_item_ref="assistant-item://synthetic/1",
        source_output_event_id="evt_output_committed",
        release_token_ref=RELEASE_TOKEN_REF,
        playback_span_id="playback_1",
        from_status="PENDING",
        to_status="FULL",
        actual_stop_offset_ms=500,
        delivery_offset_status="KNOWN",
        provider_item_cleanup_status="NOT_REQUIRED",
        source_event_ids=("evt_playback_committed", "evt_playback_finished"),
    )
    _append_shadow_verification(
        fixture,
        caused_by_event_id="evt_delivery_full",
    )
    return fixture


def _native_truncated_fixture() -> dict[str, Any]:
    fixture = _native_release_fixture()
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"]
        not in {
            "evt_playback_committed",
            "evt_playback_finished",
            "evt_delivery_full",
            "evt_shadow_verification",
        }
    ]
    interrupt = _append(
        fixture,
        "INTERRUPT_CANDIDATE",
        "evt_interrupt_native",
        caused_by_event_id="evt_playback_started",
        playback_span_id="playback_1",
        playback_offset_ms=250,
        policy_reason="provider_speech_started",
        confidence_summary="high",
        playback_epoch=1,
        interaction_state_version=1,
    )
    truncate_request = _append(
        fixture,
        "TTS_TRUNCATE_REQUESTED",
        "evt_truncate_requested_native",
        caused_by_event_id=interrupt["event_id"],
        playback_span_id="playback_1",
        cutoff_playback_offset_ms=250,
        interrupt_candidate_event_id=interrupt["event_id"],
        release_token_ref=RELEASE_TOKEN_REF,
        playback_epoch=1,
        interaction_state_version=1,
    )
    truncated = _append(
        fixture,
        "TTS_TRUNCATED",
        "evt_tts_truncated_native",
        caused_by_event_id=truncate_request["event_id"],
        playback_span_id="playback_1",
        actual_stop_offset_ms=250,
        truncate_request_event_id=truncate_request["event_id"],
        release_token_ref=RELEASE_TOKEN_REF,
        playback_epoch=1,
        interaction_state_version=1,
    )
    delivery = _append(
        fixture,
        "ASSISTANT_DELIVERY_DISPOSITIONED",
        "evt_delivery_truncated",
        caused_by_event_id=truncated["event_id"],
        assistant_item_ref="assistant-item://synthetic/1",
        source_output_event_id="evt_output_committed",
        release_token_ref=RELEASE_TOKEN_REF,
        playback_span_id="playback_1",
        from_status="PENDING",
        to_status="TRUNCATED",
        actual_stop_offset_ms=250,
        delivery_offset_status="KNOWN",
        provider_item_cleanup_status="ACKNOWLEDGED",
        source_event_ids=(truncate_request["event_id"], truncated["event_id"]),
    )
    _append_shadow_verification(
        fixture,
        caused_by_event_id=str(delivery["event_id"]),
    )
    return fixture


def _append_shadow_verification(
    fixture: dict[str, Any],
    *,
    caused_by_event_id: str,
) -> dict[str, Any]:
    return _append(
        fixture,
        "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED",
        "evt_shadow_verification",
        caused_by_event_id=caused_by_event_id,
        adapter_id="slice3b1_qwen_realtime_asr_projection",
        adapter_type="asr",
        adapter_request_id="shadow_request_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        qwen_response_id="qwen_response_1",
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        candidate_pcm_manifest_digest=PCM_MANIFEST_DIGEST,
        audio_format_ref="audio-format://synthetic/pcm16-mono-24000",
        decoded_duration_ms=500,
        independent_transcript_ref="transcript://synthetic/shadow/1",
        normalized_transcript_digest=TRANSCRIPT_DIGEST,
        exact_numbers_entities_units_match=True,
        equivalence="MATCH",
        output_mode="mock",
    )


def _append_shadow_failure_recovery(
    fixture: dict[str, Any],
    shadow_event: dict[str, Any],
) -> None:
    tainted = _append(
        fixture,
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_tainted_by_shadow",
        caused_by_event_id=str(shadow_event["event_id"]),
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLEAN",
        to_state="TAINTED",
        reason="candidate_audio_shadow_mismatch",
        source_event_ids=(shadow_event["event_id"],),
        playback_epoch=0,
        interaction_state_version=0,
        output_mode="mock",
    )
    _append(
        fixture,
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_rebuilding_after_shadow",
        caused_by_event_id=str(tainted["event_id"]),
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=2,
        from_state="TAINTED",
        to_state="REBUILDING",
        reason="shadow_failure_requires_rebuild",
        source_event_ids=(tainted["event_id"],),
        playback_epoch=1,
        interaction_state_version=1,
        output_mode="mock",
    )


def _native_not_started_fixture() -> dict[str, Any]:
    fixture = _native_release_fixture()
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"]
        not in {
            "evt_playback_started",
            "evt_playback_committed",
            "evt_playback_finished",
            "evt_delivery_full",
            "evt_shadow_verification",
        }
    ]
    delivery = _append(
        fixture,
        "ASSISTANT_DELIVERY_DISPOSITIONED",
        "evt_delivery_not_started",
        caused_by_event_id="evt_output_committed",
        assistant_item_ref="assistant-item://synthetic/1",
        source_output_event_id="evt_output_committed",
        release_token_ref=RELEASE_TOKEN_REF,
        from_status="PENDING",
        to_status="NOT_STARTED",
        delivery_offset_status="NOT_APPLICABLE",
        provider_item_cleanup_status="ACKNOWLEDGED",
        source_event_ids=("evt_output_committed",),
    )
    _append_shadow_verification(
        fixture,
        caused_by_event_id=str(delivery["event_id"]),
    )
    return fixture


def _native_fixture_for_delivery_status(
    terminal_status: str,
) -> dict[str, Any]:
    if terminal_status == "FULL":
        return _native_release_fixture()
    if terminal_status == "TRUNCATED":
        return _native_truncated_fixture()
    if terminal_status == "NOT_STARTED":
        return _native_not_started_fixture()
    raise AssertionError(f"unsupported terminal status: {terminal_status}")


def _append_tokenless_nonnative_spoken_plan_delivery(
    fixture: dict[str, Any],
) -> None:
    session_fields = {
        "session_id": "sess_mvp2_slice7",
        "conversation_id": "conv_mvp2_slice7",
        "source_module": "talker",
    }
    playback_span_id = "playback_mvp2_slice7_commitment"
    _event_by_id(
        fixture,
        "evt_mvp2_slice7_commitment_playback_started",
    ).update(
        provider_session_generation=7,
        context_snapshot_id="slowtask_tts_snapshot_7",
    )
    committed = _append(
        fixture,
        "PLAYBACK_COMMITTED",
        "evt_mvp2_slice7_commitment_playback_committed",
        caused_by_event_id=(
            "evt_mvp2_slice7_commitment_playback_started"
        ),
        playback_span_id=playback_span_id,
        playback_offset_ms=640,
        commit_basis="tts_synthesized_audio",
        **session_fields,
    )
    finished = _append(
        fixture,
        "PLAYBACK_FINISHED",
        "evt_mvp2_slice7_commitment_playback_finished",
        caused_by_event_id=str(committed["event_id"]),
        playback_span_id=playback_span_id,
        final_playback_offset_ms=640,
        finish_reason="mock_completed",
        **session_fields,
    )
    _append(
        fixture,
        "ASSISTANT_DELIVERY_DISPOSITIONED",
        "evt_mvp2_slice7_commitment_delivery_full",
        caused_by_event_id=str(finished["event_id"]),
        assistant_item_ref=(
            "assistant-item://synthetic/mvp2/tokenless-tts"
        ),
        source_output_event_id=(
            "evt_mvp2_slice7_commitment_spoken"
        ),
        playback_span_id=playback_span_id,
        from_status="PENDING",
        to_status="FULL",
        actual_stop_offset_ms=640,
        delivery_offset_status="KNOWN",
        provider_item_cleanup_status="NOT_REQUIRED",
        source_event_ids=(
            str(committed["event_id"]),
            str(finished["event_id"]),
        ),
        **session_fields,
    )


def _partial_evidence_fixture(*, include_safety: bool) -> dict[str, Any]:
    fixture = _committed_parallel_fixture()
    retained = {
        "evt_session_started",
        "evt_capability_snapshot",
        "evt_provider_rebuilding",
        "evt_provider_clean",
        "evt_audio_started",
        "evt_speech_start",
        "evt_turn_opened",
        "evt_audio_ended",
        "evt_speech_end",
        "evt_turn_accepted",
        "evt_turn_committed",
        "evt_asr_final",
        "evt_route_projection",
        "evt_route_evidence",
        "evt_router",
    }
    if include_safety:
        retained.update({"evt_safety_projection", "evt_candidate_safety"})
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] in retained
    ]
    return fixture


def _insert_partial_evidence_request_terminal(
    fixture: dict[str, Any],
    *,
    bound_role: str,
    terminal_event_name: str,
    terminal_order: str,
    unrelated_binding: str | None = None,
) -> None:
    bindings = {
        "route": (
            "evt_route_evidence",
            "slice3b1_route_evidence_fake",
            "route_request_1",
        ),
        "safety": (
            "evt_candidate_safety",
            "slice3b1_route_evidence_fake",
            "candidate_safety_request_1",
        ),
    }
    success_event_id, adapter_id, adapter_request_id = bindings[bound_role]
    if unrelated_binding == "adapter":
        adapter_id = "slice3b1_unrelated_route_evidence"
    elif unrelated_binding == "request":
        adapter_request_id = f"unrelated_{adapter_request_id}"
    elif unrelated_binding is not None:
        raise AssertionError(
            f"unsupported unrelated binding: {unrelated_binding}"
        )

    fields: dict[str, object] = {
        "adapter_id": adapter_id,
        "adapter_type": "route_evidence",
        "adapter_request_id": adapter_request_id,
        "output_mode": "mock",
    }
    if terminal_event_name == "ADAPTER_REQUEST_FAILED":
        fields.update(
            failure_reason="synthetic_request_failed",
            retryable=False,
        )
    elif terminal_event_name == "ADAPTER_OUTPUT_VALIDATION_FAILED":
        fields.update(
            schema_name="voice_agent.route_evidence.output.v1",
            failure_reasons=("synthetic_validation_failed",),
        )
    elif terminal_event_name == "ADAPTER_OUTPUT_DEGRADED":
        fields.update(
            degraded_reason="synthetic_request_degraded",
            missing_capability="supports_strict_json_validation",
            output_mode="degraded",
        )
    else:
        raise AssertionError(
            f"unsupported terminal event: {terminal_event_name}"
        )

    terminal = _base_event(
        terminal_event_name,
        (
            "evt_partial_"
            f"{bound_role}_{terminal_event_name.casefold()}_{terminal_order}"
        ),
        caused_by_event_id=(
            "evt_capability_snapshot"
            if terminal_order == "before-success"
            else success_event_id
        ),
        **fields,
    )
    if terminal_order == "before-success":
        _insert_event_before(
            fixture,
            target_event_id=success_event_id,
            event=terminal,
        )
        return
    if terminal_order != "after-success":
        raise AssertionError(f"unsupported terminal order: {terminal_order}")
    fixture["events"].append(terminal)
    _resequence(fixture)


def _asr_only_fixture() -> dict[str, Any]:
    fixture = _partial_evidence_fixture(include_safety=False)
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"]
        not in {"evt_route_projection", "evt_route_evidence", "evt_router"}
    ]
    return fixture


def _provider_tainted_committed_fixture() -> dict[str, Any]:
    fixture = _provider_backed_committed_ingress_only_fixture(
        keep_speech_generations=True,
    )
    provider_state = _event_by_id(fixture, "evt_provider_clean")
    provider_state.update(
        to_state="TAINTED",
        reason="session_update_not_validated",
    )
    return fixture


def _provider_backed_committed_ingress_only_fixture(
    *,
    keep_speech_generations: bool = False,
) -> dict[str, Any]:
    fixture = _committed_parallel_fixture()
    retained = {
        "evt_session_started",
        "evt_capability_snapshot",
        "evt_provider_rebuilding",
        "evt_provider_clean",
        "evt_audio_started",
        "evt_speech_start",
        "evt_turn_opened",
        "evt_audio_ended",
        "evt_speech_end",
        "evt_turn_accepted",
        "evt_turn_committed",
    }
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] in retained
    ]
    _resequence(fixture)
    if not keep_speech_generations:
        _remove_optional_speech_generations(fixture)
    return fixture


def _provider_tainted_rejected_fixture() -> dict[str, Any]:
    fixture = _provider_tainted_committed_fixture()
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"]
        not in {"evt_turn_accepted", "evt_turn_committed"}
    ]
    _resequence(fixture)
    _append(
        fixture,
        "TURN_INGRESS_REJECTED",
        "evt_turn_rejected_tainted",
        caused_by_event_id="evt_speech_end",
        turn_id="turn_1",
        audio_span_id="audio_1",
        reject_reason="provider_context_not_clean",
        ingress_outcome="REJECTED",
    )
    return fixture


def _move_turn_opened_after_audio_end(fixture: dict[str, Any]) -> None:
    events = fixture["events"]
    turn_opened = _event_by_id(fixture, "evt_turn_opened")
    events.remove(turn_opened)
    audio_end_index = next(
        event_index
        for event_index, event in enumerate(events)
        if event["event_id"] == "evt_audio_ended"
    )
    events.insert(audio_end_index + 1, turn_opened)
    _resequence(fixture)


def _launder_nonclean_commit_through_post_rebuild_asr(
    fixture: dict[str, Any],
) -> None:
    _event_by_id(fixture, "evt_provider_clean").update(
        to_state="TAINTED",
        reason="session_update_not_validated",
    )
    _event_by_id(fixture, "evt_speech_start").pop(
        "provider_session_generation"
    )
    _event_by_id(fixture, "evt_speech_end").pop(
        "provider_session_generation"
    )
    events = fixture["events"]
    asr_index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == "evt_asr_final"
    )
    rebuilding = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_rebuilding_after_nonclean_commit",
        caused_by_event_id="evt_turn_committed",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=2,
        from_state="TAINTED",
        to_state="REBUILDING",
        reason="synthetic_post_commit_rebuild",
        source_event_ids=("evt_turn_committed",),
        playback_epoch=1,
        interaction_state_version=1,
        output_mode="mock",
    )
    clean = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_clean_after_nonclean_commit",
        caused_by_event_id=str(rebuilding["event_id"]),
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=2,
        from_state="REBUILDING",
        to_state="CLEAN",
        reason="synthetic_post_commit_rebuild_complete",
        source_event_ids=(rebuilding["event_id"],),
        playback_epoch=1,
        interaction_state_version=1,
        output_mode="mock",
    )
    events[asr_index:asr_index] = [rebuilding, clean]
    for event_id in (
        "evt_asr_final",
        "evt_route_projection",
        "evt_route_evidence",
        "evt_safety_projection",
        "evt_candidate_safety",
        "evt_fast_composite",
        "evt_candidate",
        "evt_gate_failed",
    ):
        event = _event_by_id(fixture, event_id)
        event["provider_session_generation"] = 2
        if event.get("context_snapshot_id") == "snapshot_1":
            event["context_snapshot_id"] = "snapshot_2"
    _resequence(fixture)


def _insert_transient_cleanup_around_acceptance(
    fixture: dict[str, Any],
) -> None:
    _remove_optional_speech_generations(fixture)
    events = fixture["events"]
    accepted_index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == "evt_turn_accepted"
    )
    pending = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_cleanup_pending_before_accept",
        caused_by_event_id="evt_speech_end",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLEAN",
        to_state="CLEANUP_PENDING",
        reason="synthetic_cleanup_during_acceptance",
        source_event_ids=("evt_speech_end",),
        output_mode="mock",
    )
    events.insert(accepted_index, pending)
    committed_index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == "evt_turn_committed"
    )
    clean = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_clean_before_commit",
        caused_by_event_id=str(pending["event_id"]),
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLEANUP_PENDING",
        to_state="CLEAN",
        reason="synthetic_cleanup_completed_before_commit",
        source_event_ids=(pending["event_id"],),
        output_mode="mock",
    )
    events.insert(committed_index, clean)
    _resequence(fixture)


def _insert_transient_cleanup_during_speech(
    fixture: dict[str, Any],
) -> None:
    _remove_optional_speech_generations(fixture)
    events = fixture["events"]
    speech_start_index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == "evt_speech_start"
    )
    pending = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_cleanup_pending_during_speech",
        caused_by_event_id="evt_speech_start",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLEAN",
        to_state="CLEANUP_PENDING",
        reason="synthetic_cleanup_during_speech",
        source_event_ids=("evt_speech_start",),
        output_mode="mock",
    )
    events.insert(speech_start_index + 1, pending)
    speech_end_index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == "evt_speech_end"
    )
    clean = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_clean_before_speech_end",
        caused_by_event_id=str(pending["event_id"]),
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLEANUP_PENDING",
        to_state="CLEAN",
        reason="synthetic_cleanup_completed_before_speech_end",
        source_event_ids=(pending["event_id"],),
        output_mode="mock",
    )
    events.insert(speech_end_index, clean)
    _resequence(fixture)


def _remove_optional_speech_generations(
    fixture: dict[str, Any],
) -> None:
    _event_by_id(fixture, "evt_speech_start").pop(
        "provider_session_generation",
        None,
    )
    _event_by_id(fixture, "evt_speech_end").pop(
        "provider_session_generation",
        None,
    )


def _append_provider_ready(fixture: dict[str, Any]) -> None:
    _append(
        fixture,
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_rebuilding",
        caused_by_event_id="evt_capability_snapshot",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLOSED",
        to_state="REBUILDING",
        reason="initial_connect",
        source_event_ids=("evt_capability_snapshot",),
        playback_epoch=0,
        interaction_state_version=0,
        dropped_audio_frame_count=0,
        output_mode="mock",
    )
    _append(
        fixture,
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_clean",
        caused_by_event_id="evt_provider_rebuilding",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="REBUILDING",
        to_state="CLEAN",
        reason="session_updated_validated",
        source_event_ids=("evt_provider_rebuilding",),
        playback_epoch=0,
        interaction_state_version=0,
        dropped_audio_frame_count=0,
        output_mode="mock",
    )


def _append_committed_audio_turn(fixture: dict[str, Any]) -> None:
    _append_audio_lifecycle_through_speech_end(fixture)
    _append(
        fixture,
        "TURN_INGRESS_ACCEPTED",
        "evt_turn_accepted",
        caused_by_event_id="evt_speech_end",
        turn_id="turn_1",
        audio_span_id="audio_1",
        ingress_outcome="ACCEPTED",
    )
    _append(
        fixture,
        "TURN_INGRESS_COMMITTED",
        "evt_turn_committed",
        caused_by_event_id="evt_turn_accepted",
        turn_id="turn_1",
        utterance_id="utt_1",
        input_modality="audio",
        audio_span_id="audio_1",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _append_audio_lifecycle_through_speech_end(
    fixture: dict[str, Any],
    *,
    provider_stop_reason: str | None = None,
) -> None:
    _append(
        fixture,
        "AUDIO_SPAN_STARTED",
        "evt_audio_started",
        caused_by_event_id="evt_provider_clean",
        audio_span_id="audio_1",
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/pcm16-mono-24000",
    )
    _append(
        fixture,
        "SPEECH_START_DETECTED",
        "evt_speech_start",
        caused_by_event_id="evt_audio_started",
        audio_span_id="audio_1",
        audio_sample_offset=1_200,
        vad_confidence=0.99,
        provider_session_generation=1,
        provider_event_ref="qwen-event://synthetic/speech-start/1",
    )
    _append(
        fixture,
        "TURN_OPENED",
        "evt_turn_opened",
        caused_by_event_id="evt_speech_start",
        turn_id="turn_1",
        audio_span_id="audio_1",
        input_modality="audio",
        turn_phase="COLLECTING_INPUT",
    )
    _append(
        fixture,
        "AUDIO_SPAN_ENDED",
        "evt_audio_ended",
        caused_by_event_id="evt_speech_start",
        audio_span_id="audio_1",
        audio_sample_offset=12_000,
        duration_ms=500,
        end_reason="synthetic_speech_end",
    )
    fields: dict[str, object] = {}
    if provider_stop_reason is not None:
        fields["provider_stop_reason"] = provider_stop_reason
    _append(
        fixture,
        "SPEECH_END_DETECTED",
        "evt_speech_end",
        caused_by_event_id="evt_audio_ended",
        audio_span_id="audio_1",
        audio_sample_offset=12_000,
        vad_confidence=0.98,
        silence_duration_ms=400,
        provider_session_generation=1,
        provider_event_ref="qwen-event://synthetic/speech-end/1",
        **fields,
    )


def _append_parallel_understanding_and_output(fixture: dict[str, Any]) -> None:
    asr = _append(
        fixture,
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "evt_asr_final",
        caused_by_event_id="evt_turn_committed",
        adapter_id="slice3b1_qwen_realtime_asr_projection",
        adapter_type="asr",
        adapter_request_id="qwen_asr_request_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        input_modality="audio",
        audio_span_id="audio_1",
        asr_frame_ref="asr-frame://synthetic/slice3b1/1",
        text_ref="text-ref://synthetic/slice3b1/asr-1",
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
        provider_session_generation=1,
        qwen_input_item_ref="qwen-input-item://synthetic/1",
        qwen_input_content_index=0,
    )
    route_projection = _append(
        fixture,
        "MODEL_CONTEXT_PROJECTION_EMITTED",
        "evt_route_projection",
        caused_by_event_id=asr["event_id"],
        projection_id="projection_route_1",
        target_role="route_evidence",
        source_event_ids=(asr["event_id"],),
        context_snapshot_id="snapshot_1",
        source_event_seq=asr["event_seq"],
        provider_session_generation=1,
        projection_ref="context-projection://synthetic/route/1",
        policy_version="slice3b1.context.route.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )
    route = _append(
        fixture,
        "ROUTE_EVIDENCE_OUTPUT_EMITTED",
        "evt_route_evidence",
        caused_by_event_id=route_projection["event_id"],
        adapter_id="slice3b1_route_evidence_fake",
        adapter_type="route_evidence",
        adapter_request_id="route_request_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        final_asr_event_id=asr["event_id"],
        context_projection_event_id=route_projection["event_id"],
        context_snapshot_id="snapshot_1",
        provider_session_generation=1,
        route_hint="FAST_ONLY",
        task_focus_hint="FOREGROUND_CHAT",
        foreground_act_hint="ANSWER",
        ack_kind="CHAT",
        risk_class="LOW",
        risk_tags=("general_assistance",),
        evidence_uncertainty="LOW",
        confidence=0.98,
        schema_name="voice_agent.route_evidence.output.v1",
        normalization_status="normalized",
        output_mode="mock",
    )
    _append(
        fixture,
        "ROUTER_DECISION_EMITTED",
        "evt_router",
        caused_by_event_id=route["event_id"],
        turn_id="turn_1",
        utterance_id="utt_1",
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
        confidence=0.98,
        evidence_uncertainty="LOW",
        turn_committed_event_id="evt_turn_committed",
        asr_frame_event_id=asr["event_id"],
        route_evidence_event_id=route["event_id"],
        evidence_ref_policy="route_evidence_only",
    )
    safety_projection = _append(
        fixture,
        "MODEL_CONTEXT_PROJECTION_EMITTED",
        "evt_safety_projection",
        caused_by_event_id=asr["event_id"],
        projection_id="projection_safety_1",
        target_role="candidate_safety",
        source_event_ids=(asr["event_id"],),
        context_snapshot_id="snapshot_1",
        source_event_seq=asr["event_seq"],
        provider_session_generation=1,
        projection_ref="context-projection://synthetic/safety/1",
        policy_version="slice3b1.context.safety.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )
    safety = _append(
        fixture,
        "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        "evt_candidate_safety",
        caused_by_event_id=safety_projection["event_id"],
        adapter_id="slice3b1_route_evidence_fake",
        adapter_type="route_evidence",
        adapter_request_id="candidate_safety_request_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        qwen_response_id="qwen_response_1",
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        context_projection_event_id=safety_projection["event_id"],
        context_snapshot_id="snapshot_1",
        provider_session_generation=1,
        decision="SAFE",
        semantic_categories=("general_assistance",),
        prohibited_flags=(),
        confidence=0.99,
        schema_name="voice_agent.candidate_safety.output.v1",
        normalization_status="normalized",
        output_mode="mock",
    )
    fast = _append(
        fixture,
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "evt_fast_composite",
        caused_by_event_id=safety["event_id"],
        adapter_id="slice3b1_parallel_fast_interaction_orchestrator",
        adapter_type="fast_interaction",
        adapter_request_id="fast_request_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        route_hint_ref="route-hint://synthetic/parallel/1",
        route_prelude_ref="route-prelude://synthetic/parallel/1",
        foreground_act="ANSWER",
        final_fast_evidence_ref="evidence://synthetic/parallel/final-1",
        schema_name="voice_agent.fast_interaction.output.v1",
        normalization_status="normalized",
        output_mode="mock",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(asr["event_id"], route["event_id"], safety["event_id"]),
        risk_tags=("general_assistance",),
        risk_class="LOW",
        confidence=0.98,
        fast_interaction_topology=PARALLEL_TOPOLOGY,
        qwen_candidate_adapter_id="slice3b1_qwen_realtime_fake",
        qwen_candidate_adapter_request_id="qwen_candidate_request_1",
        route_evidence_event_id=route["event_id"],
        route_evidence_adapter_request_id=route["adapter_request_id"],
        candidate_safety_evidence_event_id=safety["event_id"],
        candidate_safety_adapter_request_id=safety["adapter_request_id"],
        context_snapshot_id="snapshot_1",
        provider_session_generation=1,
    )
    candidate = _append(
        fixture,
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "evt_candidate",
        caused_by_event_id=fast["event_id"],
        candidate_id="cand_1",
        fast_interaction_output_event_id=fast["event_id"],
        turn_id="turn_1",
        utterance_id="utt_1",
        candidate_ref="candidate-ref://synthetic/1",
        candidate_status="complete",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(
            asr["event_id"],
            route["event_id"],
            safety["event_id"],
            fast["event_id"],
        ),
        risk_tags=("general_assistance",),
        confidence=0.98,
        fast_interaction_topology=PARALLEL_TOPOLOGY,
        qwen_response_id="qwen_response_1",
        qwen_output_item_id="qwen_output_item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        candidate_pcm_manifest_digest=PCM_MANIFEST_DIGEST,
        candidate_audio_format_ref="audio-format://synthetic/pcm16-mono-24000",
        candidate_audio_duration_ms=500,
        provider_session_generation=1,
        context_snapshot_id="snapshot_1",
        route_evidence_event_id=route["event_id"],
        candidate_safety_evidence_event_id=safety["event_id"],
    )
    gate = _append(
        fixture,
        "FOREGROUND_ACT_GATE_FAILED",
        "evt_gate_failed",
        caused_by_event_id="evt_router",
        gate_decision_id="gate_decision_failed",
        candidate_event_id=candidate["event_id"],
        router_decision_event_id="evt_router",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.98,
        policy_version="slice3b1.fast_foreground_gate.v1",
        failure_reason="native_pcm_disabled",
        downgrade_policy="discard_only",
        fast_interaction_topology=PARALLEL_TOPOLOGY,
        candidate_check_policy_version="slice3b1.candidate_checks.v1",
        candidate_length_check="PASS",
        candidate_duration_check="PASS",
        candidate_terminal_check="PASS",
        native_pcm_capability_check="FAIL",
        generation_check="PASS",
        context_snapshot_check="PASS",
        route_evidence_check="PASS",
        candidate_safety_check="PASS",
        transcript_digest_check="PASS",
        pcm_manifest_check="PASS",
        correlation_check="PASS",
        provider_session_generation=1,
        context_snapshot_id="snapshot_1",
        route_evidence_event_id=route["event_id"],
        candidate_safety_evidence_event_id=safety["event_id"],
        output_mode="mock",
    )
    _append(
        fixture,
        "FOREGROUND_OUTPUT_DISCARDED",
        "evt_output_discarded",
        caused_by_event_id=gate["event_id"],
        discard_id="discard_1",
        candidate_event_id=candidate["event_id"],
        fast_interaction_output_event_id=fast["event_id"],
        router_decision_event_id="evt_router",
        discard_reason="native_pcm_disabled",
        fast_interaction_topology=PARALLEL_TOPOLOGY,
        output_mode="mock",
    )


def _make_candidate_safety_independent_before_route(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    safety_projection = _event_by_id(fixture, "evt_safety_projection")
    safety_event = _event_by_id(fixture, "evt_candidate_safety")
    events.remove(safety_projection)
    events.remove(safety_event)
    route_projection_index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == "evt_route_projection"
    )
    safety_projection["caused_by_event_id"] = "evt_asr_final"
    safety_projection["source_event_ids"] = ("evt_asr_final",)
    safety_event.pop("route_evidence_event_id", None)
    events[route_projection_index:route_projection_index] = [
        safety_projection,
        safety_event,
    ]
    _resequence(fixture)


def _append_duplicate_qwen_asr(fixture: dict[str, Any]) -> None:
    duplicate = deepcopy(_event_by_id(fixture, "evt_asr_final"))
    duplicate.update(
        event_id="evt_asr_final_duplicate",
        adapter_request_id="qwen_asr_request_duplicate",
    )
    event_seq = len(fixture["events"]) + 1
    duplicate["event_seq"] = event_seq
    duplicate["created_monotonic_ms"] = event_seq
    duplicate["created_wall_clock_ms"] = 1_700_000_000_000 + event_seq
    fixture["events"].append(duplicate)


def _append_conflicting_candidate_safety(
    fixture: dict[str, Any],
) -> None:
    duplicate = deepcopy(_event_by_id(fixture, "evt_candidate_safety"))
    duplicate.update(
        event_id="evt_candidate_safety_conflicting",
        adapter_request_id="candidate_safety_request_conflicting",
        decision="UNSAFE",
        prohibited_flags=("synthetic_conflict",),
    )
    event_seq = len(fixture["events"]) + 1
    duplicate["event_seq"] = event_seq
    duplicate["created_monotonic_ms"] = event_seq
    duplicate["created_wall_clock_ms"] = 1_700_000_000_000 + event_seq
    fixture["events"].append(duplicate)


def _append_second_route_only_turn(
    fixture: dict[str, Any],
    *,
    route_adapter_request_id: str,
) -> None:
    audio_started = _append(
        fixture,
        "AUDIO_SPAN_STARTED",
        "evt_audio_started_2",
        caused_by_event_id="evt_output_discarded",
        audio_span_id="audio_2",
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/pcm16-mono-24000",
    )
    speech_start = _append(
        fixture,
        "SPEECH_START_DETECTED",
        "evt_speech_start_2",
        caused_by_event_id=str(audio_started["event_id"]),
        audio_span_id="audio_2",
        audio_sample_offset=1_000,
        vad_confidence=0.99,
        provider_session_generation=1,
        provider_event_ref="qwen-event://synthetic/speech-start/2",
    )
    turn_opened = _append(
        fixture,
        "TURN_OPENED",
        "evt_turn_opened_2",
        caused_by_event_id=str(speech_start["event_id"]),
        turn_id="turn_2",
        audio_span_id="audio_2",
        input_modality="audio",
        turn_phase="COLLECTING_INPUT",
    )
    audio_ended = _append(
        fixture,
        "AUDIO_SPAN_ENDED",
        "evt_audio_ended_2",
        caused_by_event_id=str(speech_start["event_id"]),
        audio_span_id="audio_2",
        audio_sample_offset=10_000,
        duration_ms=375,
        end_reason="synthetic_speech_end",
    )
    speech_end = _append(
        fixture,
        "SPEECH_END_DETECTED",
        "evt_speech_end_2",
        caused_by_event_id=str(audio_ended["event_id"]),
        audio_span_id="audio_2",
        audio_sample_offset=10_000,
        vad_confidence=0.98,
        silence_duration_ms=400,
        provider_session_generation=1,
        provider_event_ref="qwen-event://synthetic/speech-end/2",
    )
    accepted = _append(
        fixture,
        "TURN_INGRESS_ACCEPTED",
        "evt_turn_accepted_2",
        caused_by_event_id=str(speech_end["event_id"]),
        turn_id=str(turn_opened["turn_id"]),
        audio_span_id="audio_2",
        ingress_outcome="ACCEPTED",
    )
    committed = _append(
        fixture,
        "TURN_INGRESS_COMMITTED",
        "evt_turn_committed_2",
        caused_by_event_id=str(accepted["event_id"]),
        turn_id="turn_2",
        utterance_id="utt_2",
        input_modality="audio",
        audio_span_id="audio_2",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    asr = _append(
        fixture,
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "evt_asr_final_2",
        caused_by_event_id=str(committed["event_id"]),
        adapter_id="slice3b1_qwen_realtime_asr_projection",
        adapter_type="asr",
        adapter_request_id="qwen_asr_request_2",
        turn_id="turn_2",
        utterance_id="utt_2",
        input_modality="audio",
        audio_span_id="audio_2",
        asr_frame_ref="asr-frame://synthetic/slice3b1/2",
        text_ref="text-ref://synthetic/slice3b1/asr-2",
        transcript_finality="final",
        timestamp_status="provider_correlated",
        streaming_status="complete",
        output_mode="mock",
        provider_session_generation=1,
        qwen_input_item_ref="qwen-input-item://synthetic/2",
        qwen_input_content_index=0,
    )
    projection = _append(
        fixture,
        "MODEL_CONTEXT_PROJECTION_EMITTED",
        "evt_route_projection_2",
        caused_by_event_id=str(asr["event_id"]),
        projection_id="projection_route_2",
        target_role="route_evidence",
        source_event_ids=(asr["event_id"],),
        context_snapshot_id="snapshot_2_route",
        source_event_seq=asr["event_seq"],
        provider_session_generation=1,
        projection_ref="context-projection://synthetic/route/2",
        policy_version="slice3b1.context.route.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )
    route = _append(
        fixture,
        "ROUTE_EVIDENCE_OUTPUT_EMITTED",
        "evt_route_evidence_2",
        caused_by_event_id=str(projection["event_id"]),
        adapter_id="slice3b1_route_evidence_fake",
        adapter_type="route_evidence",
        adapter_request_id=route_adapter_request_id,
        turn_id="turn_2",
        utterance_id="utt_2",
        final_asr_event_id=asr["event_id"],
        context_projection_event_id=projection["event_id"],
        context_snapshot_id="snapshot_2_route",
        provider_session_generation=1,
        route_hint="FAST_ONLY",
        task_focus_hint="FOREGROUND_CHAT",
        foreground_act_hint="ANSWER",
        ack_kind="CHAT",
        risk_class="LOW",
        risk_tags=("general_assistance",),
        evidence_uncertainty="LOW",
        confidence=0.98,
        schema_name="voice_agent.route_evidence.output.v1",
        normalization_status="normalized",
        output_mode="mock",
    )
    _append(
        fixture,
        "ROUTER_DECISION_EMITTED",
        "evt_router_2",
        caused_by_event_id=str(route["event_id"]),
        turn_id="turn_2",
        utterance_id="utt_2",
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
        confidence=0.98,
        evidence_uncertainty="LOW",
        turn_committed_event_id=committed["event_id"],
        asr_frame_event_id=asr["event_id"],
        route_evidence_event_id=route["event_id"],
        evidence_ref_policy="route_evidence_only",
    )


def _sync_route_confidence(
    fixture: dict[str, Any],
    confidence: float,
) -> None:
    for event_id in (
        "evt_route_evidence",
        "evt_router",
        "evt_fast_composite",
        "evt_candidate",
        "evt_gate_passed",
    ):
        _event_by_id(fixture, event_id)["confidence"] = confidence


def _sync_safety_confidence(
    fixture: dict[str, Any],
    confidence: float,
) -> None:
    _event_by_id(fixture, "evt_candidate_safety")["confidence"] = confidence
    _event_by_id(fixture, "evt_fast_composite")["confidence"] = confidence
    _event_by_id(fixture, "evt_candidate")["confidence"] = confidence


def _sync_route_uncertainty(
    fixture: dict[str, Any],
    uncertainty: str,
) -> None:
    _event_by_id(fixture, "evt_route_evidence")[
        "evidence_uncertainty"
    ] = uncertainty
    _event_by_id(fixture, "evt_router")["evidence_uncertainty"] = uncertainty


def _insert_relevant_adapter_adverse_event_before_gate(
    fixture: dict[str, Any],
    *,
    event_name: str,
) -> None:
    fields: dict[str, object] = {
        "adapter_id": "slice3b1_qwen_realtime_fake",
        "adapter_type": "duplex_model",
        "output_mode": "mock",
    }
    if event_name == "ADAPTER_OUTPUT_DEGRADED":
        fields.update(
            adapter_request_id="qwen_candidate_request_1",
            degraded_reason="synthetic_native_pcm_degradation",
            missing_capability="supports_provider_native_audio_release",
            output_mode="degraded",
        )
    elif event_name == "ADAPTER_REQUEST_FAILED":
        fields.update(
            adapter_request_id="qwen_candidate_request_1",
            failure_reason="synthetic_current_candidate_request_failure",
            retryable=False,
        )
    elif event_name == "ADAPTER_OUTPUT_VALIDATION_FAILED":
        fields.update(
            adapter_request_id="qwen_candidate_request_1",
            schema_name="voice_agent.qwen.candidate.v1",
            failure_reasons=("synthetic_candidate_validation_failure",),
        )
    elif event_name == "ADAPTER_HEALTHCHECK_FAILED":
        fields.update(
            health_status="unhealthy",
            failure_reason="synthetic_current_qwen_health_failure",
        )
    else:
        raise AssertionError(f"unsupported adverse event: {event_name}")
    _insert_event_before(
        fixture,
        target_event_id="evt_gate_passed",
        event=_base_event(
            event_name,
            f"evt_{event_name.casefold()}_before_gate",
            caused_by_event_id="evt_candidate",
            **fields,
        ),
    )


def _insert_nonblocking_adapter_failure(
    fixture: dict[str, Any],
    *,
    variant: str,
) -> None:
    if variant in {
        "bound-request-before-candidate",
        "recovered-health-before-candidate",
    }:
        target_event_id = "evt_fast_composite"
        caused_by_event_id = "evt_candidate_safety"
        adapter_id = "slice3b1_qwen_realtime_fake"
        adapter_request_id = "qwen_candidate_request_1"
    else:
        target_event_id = "evt_gate_passed"
        caused_by_event_id = "evt_candidate"
        adapter_id = (
            "slice3b1_unrelated_tts"
            if variant == "unrelated-adapter"
            else "slice3b1_qwen_realtime_fake"
        )
        adapter_request_id = (
            "unrelated_request_1"
            if variant == "unrelated-request"
            else "unrelated_tts_request_1"
        )
    event_name = (
        "ADAPTER_HEALTHCHECK_FAILED"
        if variant == "recovered-health-before-candidate"
        else "ADAPTER_REQUEST_FAILED"
    )
    fields: dict[str, object] = {
        "adapter_id": adapter_id,
        "adapter_type": (
            "tts" if variant == "unrelated-adapter" else "duplex_model"
        ),
        "output_mode": "mock",
    }
    if event_name == "ADAPTER_HEALTHCHECK_FAILED":
        fields.update(
            health_status="unhealthy",
            failure_reason=f"synthetic_{variant}",
        )
    else:
        fields.update(
            adapter_request_id=adapter_request_id,
            failure_reason=f"synthetic_{variant}",
            retryable=False,
        )
    _insert_event_before(
        fixture,
        target_event_id=target_event_id,
        event=_base_event(
            event_name,
            f"evt_nonblocking_adapter_failure_{variant}",
            caused_by_event_id=caused_by_event_id,
            **fields,
        ),
    )


def _insert_bound_request_terminal_failure(
    fixture: dict[str, Any],
    *,
    bound_role: str,
    target_event_id: str,
) -> None:
    bindings = {
        "route": (
            "slice3b1_route_evidence_fake",
            "route_evidence",
            "route_request_1",
        ),
        "safety": (
            "slice3b1_route_evidence_fake",
            "route_evidence",
            "candidate_safety_request_1",
        ),
        "qwen_candidate": (
            "slice3b1_qwen_realtime_fake",
            "duplex_model",
            "qwen_candidate_request_1",
        ),
    }
    adapter_id, adapter_type, adapter_request_id = bindings[bound_role]
    caused_by_event_id = (
        "evt_session_started"
        if target_event_id == "evt_capability_snapshot"
        else "evt_output_committed"
    )
    _insert_event_before(
        fixture,
        target_event_id=target_event_id,
        event=_base_event(
            "ADAPTER_REQUEST_FAILED",
            f"evt_bound_request_terminal_failure_{bound_role}",
            caused_by_event_id=caused_by_event_id,
            adapter_id=adapter_id,
            adapter_type=adapter_type,
            adapter_request_id=adapter_request_id,
            failure_reason=f"synthetic_terminal_{bound_role}_failure",
            retryable=False,
            output_mode="mock",
        ),
    )


def _insert_event_before(
    fixture: dict[str, Any],
    *,
    target_event_id: str,
    event: dict[str, Any],
) -> None:
    events = fixture["events"]
    target_index = next(
        event_index
        for event_index, candidate in enumerate(events)
        if candidate["event_id"] == target_event_id
    )
    events.insert(target_index, event)
    _resequence(fixture)


def _append_duplicate_router(fixture: dict[str, Any]) -> None:
    duplicate = deepcopy(_event_by_id(fixture, "evt_router"))
    duplicate["event_id"] = "evt_router_duplicate"
    duplicate["event_seq"] = len(fixture["events"]) + 1
    duplicate["created_monotonic_ms"] = duplicate["event_seq"]
    duplicate["created_wall_clock_ms"] = 1_700_000_000_000 + duplicate["event_seq"]
    fixture["events"].append(duplicate)


def _append_current_progress_source(
    fixture: dict[str, Any],
) -> dict[str, Any]:
    created = _append(
        fixture,
        "SLOWTASK_CREATED",
        "evt_handoff_task_created",
        caused_by_event_id="evt_output_discarded",
        source_module="slowtask_runtime",
        task_id="task_1",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/handoff/1",
    )
    return _append(
        fixture,
        "PLANNING_STARTED",
        "evt_handoff_progress",
        caused_by_event_id=str(created["event_id"]),
        source_module="slowtask_runtime",
        task_id="task_1",
        plan_version=1,
        task_event_seq=2,
        planning_reason="synthetic_current_plan_progress",
    )


def _append_test_handoff(
    fixture: dict[str, Any],
    *,
    source_event: dict[str, Any] | None = None,
    kind: str = "PROGRESS",
) -> dict[str, Any]:
    source = source_event or _append_current_progress_source(fixture)
    return _append(
        fixture,
        "SLOW_TO_FAST_HANDOFF_EMITTED",
        "evt_handoff",
        caused_by_event_id=str(source["event_id"]),
        handoff_id="handoff_1",
        kind=kind,
        delivery_mode="SPEAK_WHEN_IDLE",
        task_id=source["task_id"],
        plan_version=source["plan_version"],
        task_event_seq=source["task_event_seq"],
        source_event_ids=(source["event_id"],),
        facts_ref="handoff-facts://synthetic/1",
        must_say_fields_ref="must-say-fields://synthetic/1",
        forbidden_claims_ref="forbidden-claims://synthetic/1",
        priority=1,
        expiry_status="CURRENT",
        redaction_status="metadata_only",
    )


def _append_replacement_progress_handoff(
    fixture: dict[str, Any],
    *,
    newer: bool = True,
    expiry_status: str = "CURRENT",
    incompatible_terminal: bool = False,
) -> dict[str, Any]:
    prior_progress = _event_by_id(fixture, "evt_handoff_progress")
    source = prior_progress
    kind = "PROGRESS"
    if newer:
        if incompatible_terminal:
            source = _append(
                fixture,
                "SLOWTASK_DEGRADED",
                "evt_replacement_terminal_source",
                caused_by_event_id=str(prior_progress["event_id"]),
                source_module="slowtask_runtime",
                task_id="task_1",
                plan_version=1,
                task_event_seq=3,
                degraded_reason="synthetic_incompatible_replacement",
            )
            kind = "DEGRADED"
        else:
            source = _append(
                fixture,
                "PLANNING_RESTARTED",
                "evt_replacement_progress_source",
                caused_by_event_id="evt_handoff",
                source_module="slowtask_runtime",
                task_id="task_1",
                plan_version=1,
                task_event_seq=3,
                restart_reason="synthetic_newer_coalesced_progress",
            )
    return _append(
        fixture,
        "SLOW_TO_FAST_HANDOFF_EMITTED",
        "evt_handoff_replacement",
        caused_by_event_id=str(source["event_id"]),
        handoff_id="handoff_2",
        kind=kind,
        delivery_mode="SPEAK_WHEN_IDLE",
        task_id=source["task_id"],
        plan_version=source["plan_version"],
        task_event_seq=source["task_event_seq"],
        source_event_ids=(source["event_id"],),
        facts_ref="handoff-facts://synthetic/2",
        must_say_fields_ref="must-say-fields://synthetic/2",
        forbidden_claims_ref="forbidden-claims://synthetic/2",
        priority=1,
        expiry_status=expiry_status,
        redaction_status="metadata_only",
    )


def _append_test_handoff_arbitration(
    fixture: dict[str, Any],
    handoff: dict[str, Any],
    *,
    selected_source_type: str = "progress",
) -> dict[str, Any]:
    return _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration",
        caused_by_event_id=str(handoff["event_id"]),
        arbitration_id="arbitration_1",
        selected_source_type=selected_source_type,
        selected_source_event_id=handoff["event_id"],
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="test_handoff_selected",
    )


def _insert_user_fast_arbitration_before_playback(
    fixture: dict[str, Any],
    *,
    selected_source_event_id: str,
) -> None:
    events = fixture["events"]
    insertion_target = (
        "evt_gate_passed"
        if selected_source_event_id == "evt_candidate"
        else "evt_playback_started"
    )
    insertion_index = next(
        event_index
        for event_index, event in enumerate(events)
        if event["event_id"] == insertion_target
    )
    arbitration = _base_event(
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_select_user_fast",
        caused_by_event_id=selected_source_event_id,
        arbitration_id="arbitration_select_user_fast",
        selected_source_type="user_fast",
        selected_source_event_id=selected_source_event_id,
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_active_user_fast_selection",
    )
    events.insert(insertion_index, arbitration)
    _resequence(fixture)


def _append_post_delivery_user_fast_arbitration(
    fixture: dict[str, Any],
    *,
    selected_source_event_id: str,
) -> None:
    _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        (
            "evt_arbitration_reselect_retired_"
            f"{selected_source_event_id}"
        ),
        caused_by_event_id=selected_source_event_id,
        arbitration_id=(
            "arbitration_reselect_retired_"
            f"{selected_source_event_id}"
        ),
        selected_source_type="user_fast",
        selected_source_event_id=selected_source_event_id,
        superseded_source_event_ids=(),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_reselect_retired_user_fast",
    )


def _append_superseding_handoff_arbitration(
    fixture: dict[str, Any],
    *,
    caused_by_event_id: str,
    superseded_event_ids: tuple[str, ...],
) -> dict[str, Any]:
    return _append(
        fixture,
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_superseding_handoff",
        caused_by_event_id=caused_by_event_id,
        arbitration_id="arbitration_superseding_handoff",
        selected_source_type="none",
        superseded_source_event_ids=superseded_event_ids,
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_handoff_supersession",
    )


def _append_test_handoff_disposition(
    fixture: dict[str, Any],
    handoff: dict[str, Any],
    *,
    disposition: str,
    caused_by_event_id: str | None = None,
    **fields: object,
) -> dict[str, Any]:
    return _append(
        fixture,
        "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
        f"evt_handoff_{disposition.lower()}",
        caused_by_event_id=caused_by_event_id or str(handoff["event_id"]),
        handoff_id=handoff["handoff_id"],
        disposition=disposition,
        reason=f"test_{disposition.lower()}",
        **fields,
    )


def _append_test_composer_projection(
    fixture: dict[str, Any],
    *,
    handoff: dict[str, Any],
    disposition: dict[str, Any],
    arbitration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_event_ids = [str(handoff["event_id"])]
    if arbitration is not None:
        source_event_ids.append(str(arbitration["event_id"]))
    source_event_ids.append(str(disposition["event_id"]))
    return _append(
        fixture,
        "MODEL_CONTEXT_PROJECTION_EMITTED",
        "evt_composer_projection",
        caused_by_event_id=str(disposition["event_id"]),
        projection_id="projection_composer_1",
        target_role="composer",
        source_event_ids=tuple(source_event_ids),
        context_snapshot_id="snapshot_composer_1",
        source_event_seq=disposition["event_seq"],
        provider_session_generation=1,
        projection_ref="context-projection://synthetic/composer/1",
        policy_version="slice3b1.context.composer.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )


def _append_duplicate_gate(fixture: dict[str, Any]) -> None:
    duplicate = deepcopy(_event_by_id(fixture, "evt_gate_failed"))
    duplicate["event_id"] = "evt_gate_failed_duplicate"
    duplicate["gate_decision_id"] = "gate_decision_failed_duplicate"
    duplicate["event_seq"] = len(fixture["events"]) + 1
    duplicate["created_monotonic_ms"] = duplicate["event_seq"]
    duplicate["created_wall_clock_ms"] = 1_700_000_000_000 + duplicate["event_seq"]
    fixture["events"].append(duplicate)


def _append_duplicate_candidate_disposition(fixture: dict[str, Any]) -> None:
    duplicate = deepcopy(_event_by_id(fixture, "evt_output_discarded"))
    duplicate["event_id"] = "evt_output_discarded_duplicate"
    duplicate["discard_id"] = "discard_2"
    duplicate["event_seq"] = len(fixture["events"]) + 1
    duplicate["created_monotonic_ms"] = duplicate["event_seq"]
    duplicate["created_wall_clock_ms"] = 1_700_000_000_000 + duplicate["event_seq"]
    fixture["events"].append(duplicate)


def _append_duplicate_event_id(fixture: dict[str, Any]) -> None:
    duplicate = deepcopy(_event_by_id(fixture, "evt_candidate_safety"))
    duplicate["event_seq"] = len(fixture["events"]) + 1
    duplicate["created_monotonic_ms"] = duplicate["event_seq"]
    duplicate["created_wall_clock_ms"] = 1_700_000_000_000 + duplicate["event_seq"]
    fixture["events"].append(duplicate)


def _make_illegal_provider_transition(fixture: dict[str, Any]) -> None:
    event = _event_by_id(fixture, "evt_provider_rebuilding")
    event["to_state"] = "CLEAN"


def _append_nonadvancing_rebuild(fixture: dict[str, Any]) -> None:
    _append(
        fixture,
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_rebuild_without_fence",
        caused_by_event_id="evt_output_discarded",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=2,
        from_state="CLEAN",
        to_state="REBUILDING",
        reason="synthetic_rebuild",
        source_event_ids=("evt_output_discarded",),
        playback_epoch=0,
        interaction_state_version=0,
        output_mode="mock",
    )


def _append_nonadvancing_parallel_barge_in(fixture: dict[str, Any]) -> None:
    interrupt = _append(
        fixture,
        "INTERRUPT_CANDIDATE",
        "evt_interrupt",
        caused_by_event_id="evt_output_discarded",
        playback_span_id="playback_1",
        playback_offset_ms=100,
        policy_reason="provider_speech_started",
        confidence_summary="high",
        playback_epoch=0,
        interaction_state_version=0,
    )
    _append(
        fixture,
        "TTS_TRUNCATE_REQUESTED",
        "evt_truncate_requested",
        caused_by_event_id=interrupt["event_id"],
        playback_span_id="playback_1",
        cutoff_playback_offset_ms=100,
        interrupt_candidate_event_id=interrupt["event_id"],
        playback_epoch=0,
        interaction_state_version=0,
    )


def _insert_rebuild_before_old_generation_candidate(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    index = next(
        idx for idx, event in enumerate(events) if event["event_id"] == "evt_fast_composite"
    )
    rebuilding = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_rebuilding_generation_2",
        caused_by_event_id="evt_candidate_safety",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=2,
        from_state="CLEAN",
        to_state="REBUILDING",
        reason="synthetic_rebuild",
        source_event_ids=("evt_candidate_safety",),
        playback_epoch=1,
        interaction_state_version=1,
        output_mode="mock",
    )
    clean = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_clean_generation_2",
        caused_by_event_id="evt_provider_rebuilding_generation_2",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=2,
        from_state="REBUILDING",
        to_state="CLEAN",
        reason="synthetic_rebuild_complete",
        source_event_ids=("evt_provider_rebuilding_generation_2",),
        playback_epoch=1,
        interaction_state_version=1,
        output_mode="mock",
    )
    events[index:index] = [rebuilding, clean]
    _resequence(fixture)


def _insert_interrupt_before_stamped_playback(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    index = next(
        idx
        for idx, event in enumerate(events)
        if event["event_id"] == "evt_playback_started"
    )
    interrupt = _base_event(
        "INTERRUPT_CANDIDATE",
        "evt_interrupt_before_playback",
        caused_by_event_id="evt_output_committed",
        playback_span_id="playback_1",
        playback_offset_ms=0,
        policy_reason="provider_speech_started_before_first_byte",
        confidence_summary="high",
        playback_epoch=1,
        interaction_state_version=1,
    )
    truncate = _base_event(
        "TTS_TRUNCATE_REQUESTED",
        "evt_truncate_before_playback",
        caused_by_event_id="evt_interrupt_before_playback",
        playback_span_id="playback_1",
        cutoff_playback_offset_ms=0,
        interrupt_candidate_event_id="evt_interrupt_before_playback",
        playback_epoch=1,
        interaction_state_version=1,
    )
    events[index:index] = [interrupt, truncate]
    _event_by_id(fixture, "evt_playback_started")["playback_epoch"] = 1
    _resequence(fixture)


def _insert_interrupt_immediately_before(
    fixture: dict[str, Any],
    event_id: str,
) -> None:
    events = fixture["events"]
    index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == event_id
    )
    predecessor = events[index - 1]
    interrupt = _base_event(
        "INTERRUPT_CANDIDATE",
        f"evt_projection_fence_{event_id}",
        caused_by_event_id=str(predecessor["event_id"]),
        playback_span_id="playback_projection_fence",
        playback_offset_ms=0,
        policy_reason="synthetic_projection_fence",
        confidence_summary="high",
        playback_epoch=1,
        interaction_state_version=1,
    )
    events.insert(index, interrupt)
    _resequence(fixture)
    _event_by_id(fixture, event_id)["source_event_seq"] = interrupt[
        "event_seq"
    ]


def _taint_provider_before_native_playback(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    index = next(
        index
        for index, event in enumerate(events)
        if event["event_id"] == "evt_playback_started"
    )
    taint = _base_event(
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_provider_tainted_before_playback",
        caused_by_event_id="evt_output_committed",
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLEAN",
        to_state="TAINTED",
        reason="synthetic_pre_playback_taint",
        source_event_ids=("evt_output_committed",),
        playback_epoch=0,
        interaction_state_version=0,
        output_mode="mock",
    )
    events.insert(index, taint)
    _resequence(fixture)


def _sync_full_delivery_offset(
    fixture: dict[str, Any],
    offset_ms: int,
) -> None:
    _event_by_id(fixture, "evt_playback_committed")[
        "playback_offset_ms"
    ] = offset_ms
    _event_by_id(fixture, "evt_playback_finished")[
        "final_playback_offset_ms"
    ] = offset_ms
    _event_by_id(fixture, "evt_delivery_full")[
        "actual_stop_offset_ms"
    ] = offset_ms


def _sync_truncated_delivery_offset(
    fixture: dict[str, Any],
    offset_ms: int,
) -> None:
    _event_by_id(fixture, "evt_interrupt_native")[
        "playback_offset_ms"
    ] = offset_ms
    _event_by_id(fixture, "evt_truncate_requested_native")[
        "cutoff_playback_offset_ms"
    ] = offset_ms
    _event_by_id(fixture, "evt_tts_truncated_native")[
        "actual_stop_offset_ms"
    ] = offset_ms
    _event_by_id(fixture, "evt_delivery_truncated")[
        "actual_stop_offset_ms"
    ] = offset_ms


def _insert_arbitration_between_gate_and_commit(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    index = next(
        idx
        for idx, event in enumerate(events)
        if event["event_id"] == "evt_output_committed"
    )
    arbitration = _base_event(
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_between_gate_and_commit",
        caused_by_event_id="evt_gate_passed",
        arbitration_id="arbitration_between_gate_and_commit",
        selected_source_type="none",
        superseded_source_event_ids=("evt_candidate",),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="synthetic_supersession_race",
    )
    events.insert(index, arbitration)
    _resequence(fixture)


def _insert_superseding_arbitration_before_playback(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    index = next(
        idx
        for idx, event in enumerate(events)
        if event["event_id"] == "evt_playback_started"
    )
    arbitration = _base_event(
        "RESPONSE_ARBITRATION_DECIDED",
        "evt_arbitration_supersede_release",
        caused_by_event_id="evt_output_committed",
        arbitration_id="arbitration_supersede_release",
        selected_source_type="none",
        superseded_source_event_ids=("evt_output_committed",),
        provider_session_generation=1,
        playback_epoch=0,
        interaction_state_version=0,
        decision_reason="release_superseded_before_first_byte",
    )
    events.insert(index, arbitration)
    _resequence(fixture)


def _remove_event(fixture: dict[str, Any], event_id: str) -> None:
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] != event_id
    ]
    _resequence(fixture)


def _append_full_terminals_to_truncated_fixture(
    fixture: dict[str, Any],
) -> None:
    committed = _append(
        fixture,
        "PLAYBACK_COMMITTED",
        "evt_illegal_playback_committed_after_truncate",
        caused_by_event_id="evt_playback_started",
        playback_span_id="playback_1",
        playback_offset_ms=500,
        commit_basis="provider_native_pcm",
        release_token_ref=RELEASE_TOKEN_REF,
    )
    _append(
        fixture,
        "PLAYBACK_FINISHED",
        "evt_illegal_playback_finished_after_truncate",
        caused_by_event_id=str(committed["event_id"]),
        playback_span_id="playback_1",
        final_playback_offset_ms=500,
        release_token_ref=RELEASE_TOKEN_REF,
    )


def _insert_partial_commit_before_interrupt(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    index = next(
        idx
        for idx, event in enumerate(events)
        if event["event_id"] == "evt_interrupt_native"
    )
    commit = _base_event(
        "PLAYBACK_COMMITTED",
        "evt_partial_playback_committed",
        caused_by_event_id="evt_playback_started",
        playback_span_id="playback_1",
        playback_offset_ms=200,
        commit_basis="provider_native_pcm",
        release_token_ref=RELEASE_TOKEN_REF,
    )
    events.insert(index, commit)
    delivery = _event_by_id(fixture, "evt_delivery_truncated")
    delivery["source_event_ids"] = (
        *delivery["source_event_ids"],
        commit["event_id"],
    )
    _resequence(fixture)


def _insert_partial_commit_before_full_commit(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    index = next(
        idx
        for idx, event in enumerate(events)
        if event["event_id"] == "evt_playback_committed"
    )
    partial = _base_event(
        "PLAYBACK_COMMITTED",
        "evt_partial_playback_committed",
        caused_by_event_id="evt_playback_started",
        playback_span_id="playback_1",
        playback_offset_ms=250,
        commit_basis="provider_native_pcm",
        release_token_ref=RELEASE_TOKEN_REF,
    )
    events.insert(index, partial)
    _event_by_id(fixture, "evt_playback_committed")[
        "caused_by_event_id"
    ] = partial["event_id"]
    _resequence(fixture)


def _append_truncate_after_full(fixture: dict[str, Any]) -> None:
    interrupt = _append(
        fixture,
        "INTERRUPT_CANDIDATE",
        "evt_illegal_interrupt_after_full",
        caused_by_event_id="evt_delivery_full",
        playback_span_id="playback_1",
        playback_offset_ms=500,
        policy_reason="synthetic_late_interrupt",
        confidence_summary="high",
        playback_epoch=1,
        interaction_state_version=1,
    )
    request = _append(
        fixture,
        "TTS_TRUNCATE_REQUESTED",
        "evt_illegal_truncate_request_after_full",
        caused_by_event_id=str(interrupt["event_id"]),
        playback_span_id="playback_1",
        cutoff_playback_offset_ms=500,
        interrupt_candidate_event_id=interrupt["event_id"],
        release_token_ref=RELEASE_TOKEN_REF,
        playback_epoch=1,
        interaction_state_version=1,
    )
    _append(
        fixture,
        "TTS_TRUNCATED",
        "evt_illegal_truncated_after_full",
        caused_by_event_id=str(request["event_id"]),
        playback_span_id="playback_1",
        actual_stop_offset_ms=500,
        truncate_request_event_id=request["event_id"],
        release_token_ref=RELEASE_TOKEN_REF,
        playback_epoch=1,
        interaction_state_version=1,
    )


def _append_orphan_playback_for_not_started(
    fixture: dict[str, Any],
) -> None:
    _append(
        fixture,
        "PLAYBACK_SPAN_STARTED",
        "evt_orphan_playback_started",
        caused_by_event_id="evt_gate_passed",
        assistant_item_ref="assistant-item://synthetic/1",
        playback_span_id="playback_orphan",
        audio_ref="audio-ref://memory-only/candidate-1",
        release_token_ref=RELEASE_TOKEN_REF,
        provider_session_generation=1,
        context_snapshot_id="snapshot_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        candidate_id="cand_1",
        qwen_response_id="qwen_response_1",
        qwen_output_item_id="qwen_output_item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        candidate_pcm_manifest_digest=PCM_MANIFEST_DIGEST,
        playback_epoch=0,
    )


def _insert_duplicate_release_token_playback_start(
    fixture: dict[str, Any],
) -> None:
    events = fixture["events"]
    original = _event_by_id(fixture, "evt_playback_started")
    duplicate = deepcopy(original)
    duplicate.update(
        event_id="evt_playback_started_duplicate_token",
        caused_by_event_id="evt_gate_passed",
    )
    index = next(
        event_index
        for event_index, event in enumerate(events)
        if event["event_id"] == original["event_id"]
    )
    events.insert(index + 1, duplicate)
    _resequence(fixture)


def _append_orphan_native_start_after_failed_gate(
    fixture: dict[str, Any],
) -> None:
    _append(
        fixture,
        "PLAYBACK_SPAN_STARTED",
        "evt_orphan_native_start_after_failed_gate",
        caused_by_event_id="evt_output_discarded",
        playback_span_id="playback_orphan_failed_gate",
        audio_ref="audio-ref://memory-only/orphan-failed-gate",
        release_token_ref=RELEASE_TOKEN_REF,
        provider_session_generation=1,
        context_snapshot_id="snapshot_1",
        turn_id="turn_1",
        utterance_id="utt_1",
        candidate_id="cand_1",
        qwen_response_id="qwen_response_1",
        qwen_output_item_id="qwen_output_item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest=TRANSCRIPT_DIGEST,
        candidate_pcm_manifest_digest=PCM_MANIFEST_DIGEST,
        playback_epoch=0,
    )


def _append_orphan_native_delivery_after_failed_gate(
    fixture: dict[str, Any],
) -> None:
    _append(
        fixture,
        "ASSISTANT_DELIVERY_DISPOSITIONED",
        "evt_orphan_delivery_after_failed_gate",
        caused_by_event_id="evt_output_discarded",
        assistant_item_ref="assistant-item://synthetic/orphan-failed-gate",
        source_output_event_id="evt_output_discarded",
        release_token_ref=RELEASE_TOKEN_REF,
        from_status="PENDING",
        to_status="NOT_STARTED",
        delivery_offset_status="NOT_APPLICABLE",
        provider_item_cleanup_status="ACKNOWLEDGED",
        source_event_ids=("evt_output_discarded",),
    )


def _append_duplicate_delivery(fixture: dict[str, Any]) -> None:
    duplicate = deepcopy(_event_by_id(fixture, "evt_delivery_full"))
    duplicate["event_id"] = "evt_delivery_full_duplicate"
    duplicate["event_seq"] = len(fixture["events"]) + 1
    duplicate["created_monotonic_ms"] = duplicate["event_seq"]
    duplicate["created_wall_clock_ms"] = 1_700_000_000_000 + duplicate["event_seq"]
    fixture["events"].append(duplicate)


def _forge_qwen_asr_adapter_id(fixture: dict[str, Any]) -> None:
    forged_id = "forged_slice3b1_qwen_asr"
    _event_by_id(fixture, "evt_asr_final")["adapter_id"] = forged_id
    snapshot = _event_by_id(fixture, "evt_capability_snapshot")
    snapshot["adapter_ids"][0] = forged_id


def _swap_event_seq(
    fixture: dict[str, Any],
    first_event_id: str,
    second_event_id: str,
) -> None:
    first = _event_by_id(fixture, first_event_id)
    second = _event_by_id(fixture, second_event_id)
    first["event_seq"], second["event_seq"] = second["event_seq"], first["event_seq"]


def _resequence(fixture: dict[str, Any]) -> None:
    events_by_id = {
        str(event["event_id"]): event
        for event in fixture["events"]
    }
    for event_seq, event in enumerate(fixture["events"], start=1):
        event["event_seq"] = event_seq
        event["created_monotonic_ms"] = event_seq
        event["created_wall_clock_ms"] = 1_700_000_000_000 + event_seq
    for event in fixture["events"]:
        if event["event_name"] != "MODEL_CONTEXT_PROJECTION_EMITTED":
            continue
        source_seqs = [
            int(events_by_id[str(source_event_id)]["event_seq"])
            for source_event_id in event["source_event_ids"]
        ]
        event["source_event_seq"] = max(source_seqs)


def _adr018_redacted_text_fixture() -> dict[str, Any]:
    fixture = _empty_fixture("canonical-redacted-text")
    session = _append(
        fixture,
        "SESSION_STARTED",
        "evt_redacted_text_session_started",
        runtime_config_ref="config://synthetic/redacted-text",
        capability_snapshot_ref="capability://synthetic/redacted-text",
    )
    text_input = _append(
        fixture,
        "TEXT_INPUT_RECEIVED",
        "evt_redacted_text_input",
        caused_by_event_id=str(session["event_id"]),
        input_span_id="input_redacted_text_1",
        text_span_id="text_redacted_text_1",
        input_modality="text",
        redacted_text="[synthetic text: hello assistant]",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
    )
    rebuilding = _append(
        fixture,
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_redacted_text_provider_rebuilding",
        caused_by_event_id=str(text_input["event_id"]),
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="CLOSED",
        to_state="REBUILDING",
        reason="redacted_fixture_rebuild",
        source_event_ids=(text_input["event_id"],),
        playback_epoch=0,
        interaction_state_version=0,
        dropped_audio_frame_count=0,
        output_mode="mock",
    )
    _append(
        fixture,
        "PROVIDER_CONTEXT_STATE_CHANGED",
        "evt_redacted_text_provider_clean",
        caused_by_event_id=str(rebuilding["event_id"]),
        adapter_id="slice3b1_qwen_realtime_fake",
        provider_session_generation=1,
        from_state="REBUILDING",
        to_state="CLEAN",
        reason="redacted_fixture_ready",
        source_event_ids=(rebuilding["event_id"],),
        playback_epoch=0,
        interaction_state_version=0,
        dropped_audio_frame_count=0,
        output_mode="mock",
    )
    return fixture


def _adr018_mock_text_understanding_fixture() -> dict[str, Any]:
    fixture = _adr018_redacted_text_fixture()
    committed = _append_redacted_text_turn(fixture)
    mock_asr = _append(
        fixture,
        "MOCK_ASR_FRAME_EMITTED",
        "evt_mock_text_asr",
        caused_by_event_id=str(committed["event_id"]),
        turn_id="turn_redacted_text_1",
        utterance_id="utt_redacted_text_1",
        input_modality="text",
        text_span_id="text_redacted_text_1",
        asr_frame_ref="asr-frame://synthetic/redacted-text/1",
        output_mode="mock",
    )
    mock_thinker = _append(
        fixture,
        "MOCK_THINKER_FRAME_EMITTED",
        "evt_mock_text_thinker",
        caused_by_event_id=str(committed["event_id"]),
        turn_id="turn_redacted_text_1",
        utterance_id="utt_redacted_text_1",
        input_modality="text",
        semantic_frame_ref="semantic-frame://synthetic/redacted-text/1",
        output_mode="mock",
    )
    _append(
        fixture,
        "ROUTER_DECISION_EMITTED",
        "evt_mock_text_router",
        caused_by_event_id=str(mock_thinker["event_id"]),
        turn_id="turn_redacted_text_1",
        utterance_id="utt_redacted_text_1",
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
        confidence=0.9,
        evidence_uncertainty="low",
        turn_committed_event_id=str(committed["event_id"]),
        asr_frame_event_id=str(mock_asr["event_id"]),
        thinker_frame_event_id=str(mock_thinker["event_id"]),
    )
    return fixture


def _adr018_real_text_thinker_fixture() -> dict[str, Any]:
    fixture = _adr018_redacted_text_fixture()
    committed = _append_redacted_text_turn(fixture)
    thinker = _append(
        fixture,
        "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        "evt_real_text_thinker",
        caused_by_event_id=str(committed["event_id"]),
        adapter_id="synthetic_real_text_thinker",
        adapter_type="thinker",
        adapter_request_id="synthetic_real_text_thinker_request_1",
        turn_id="turn_redacted_text_1",
        utterance_id="utt_redacted_text_1",
        input_modality="text",
        text_span_id="text_redacted_text_1",
        semantic_frame_schema="voice_agent.semantic_frame.v1",
        normalization_status="normalized",
        semantic_frame_ref="semantic-frame://synthetic/redacted-text/real-1",
        semantic_summary_ref="summary://synthetic/redacted-text/real-1",
        semantic_close_status="available",
        semantic_close_ref="semantic-close://synthetic/redacted-text/real-1",
        assistant_directedness_status="available",
        assistant_directedness_ref=(
            "assistant-directedness://synthetic/redacted-text/real-1"
        ),
        emotion_status="available",
        emotion_ref="emotion://synthetic/redacted-text/real-1",
        audio_caption_status="available",
        audio_caption_ref="audio-caption://synthetic/redacted-text/real-1",
        output_mode="real",
    )
    _append(
        fixture,
        "ROUTER_DECISION_EMITTED",
        "evt_real_text_router",
        caused_by_event_id=str(thinker["event_id"]),
        turn_id="turn_redacted_text_1",
        utterance_id="utt_redacted_text_1",
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
        confidence=0.9,
        evidence_uncertainty="low",
        turn_committed_event_id=str(committed["event_id"]),
        thinker_frame_event_id=str(thinker["event_id"]),
    )
    return fixture


def _append_redacted_text_turn(
    fixture: dict[str, Any],
) -> dict[str, Any]:
    opened = _append(
        fixture,
        "TURN_OPENED",
        "evt_redacted_text_turn_opened",
        caused_by_event_id="evt_redacted_text_input",
        turn_id="turn_redacted_text_1",
        input_span_id="input_redacted_text_1",
        text_span_id="text_redacted_text_1",
        input_modality="text",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = _append(
        fixture,
        "TURN_INGRESS_ACCEPTED",
        "evt_redacted_text_turn_accepted",
        caused_by_event_id=str(opened["event_id"]),
        turn_id="turn_redacted_text_1",
        input_span_id="input_redacted_text_1",
        text_span_id="text_redacted_text_1",
        ingress_outcome="ACCEPTED",
    )
    return _append(
        fixture,
        "TURN_INGRESS_COMMITTED",
        "evt_redacted_text_turn_committed",
        caused_by_event_id=str(accepted["event_id"]),
        turn_id="turn_redacted_text_1",
        utterance_id="utt_redacted_text_1",
        input_span_id="input_redacted_text_1",
        text_span_id="text_redacted_text_1",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _adr018_actual_user_patch_fixture() -> dict[str, Any]:
    fixture = load_json_fixture(
        MVP1_REPLAY_FIXTURE_DIR
        / "006-plan-advance-replanning.fixture.json"
    )
    events = fixture["events"]
    patch_index = next(
        index
        for index, event in enumerate(events)
        if event["event_name"] == "USER_PATCH_RECEIVED"
    )
    original_patch = events[patch_index]
    journal = InMemoryEventJournal(
        session_id=str(original_patch["session_id"]),
        conversation_id=str(original_patch["conversation_id"]),
    )
    for event in events[:patch_index]:
        _append_existing_event_to_journal(journal, event)

    journal_events = journal.events()
    text_input = _journal_event_by_id(
        journal_events,
        "evt_mvp1_slice6_patch_text",
    )
    committed = _journal_event_by_id(
        journal_events,
        "evt_mvp1_slice6_patch_turn_committed",
    )
    asr = _journal_event_by_id(
        journal_events,
        "evt_mvp1_slice6_patch_asr",
    )
    thinker = _journal_event_by_id(
        journal_events,
        "evt_mvp1_slice6_patch_thinker",
    )
    router = _journal_event_by_id(
        journal_events,
        "evt_mvp1_slice6_patch_router",
    )
    original_pack = original_patch["evidence_pack"]
    authoritative = original_pack["authoritative_evidence"]
    hypothesis = original_pack["non_authoritative_hypothesis"]
    produced = UserPatchEvidencePackRuntime(
        journal
    ).receive_patch_from_router_decision(
        router_decision_event=router,
        turn_committed_event=committed,
        task_id=str(original_patch["task_id"]),
        current_plan_version=int(original_patch["plan_version"]),
        next_task_event_seq=int(original_patch["task_event_seq"]),
        patch_id=str(original_patch["patch_id"]),
        event_id=str(original_patch["event_id"]),
        evidence_ref=str(original_patch["evidence_ref"]),
        created_monotonic_ms=int(original_patch["created_monotonic_ms"]),
        created_wall_clock_ms=int(original_patch["created_wall_clock_ms"]),
        text_input_event=text_input,
        asr_frame_event=asr,
        thinker_frame_event=thinker,
        asr_nbest=authoritative["asr_nbest"],
        transcript_hint_ref=authoritative.get("transcript_hint_ref"),
        semantic_summary_ref=hypothesis.get("semantic_summary_ref"),
        audio_summary_ref=hypothesis.get("audio_summary_ref"),
        candidate_patch_types=original_patch["candidate_patch_types"],
        patch_hint=hypothesis.get("patch_hint"),
    )
    events[patch_index] = produced.user_patch_event
    _append_loaded_fixture_adr018_marker(fixture)
    return fixture


def _append_existing_event_to_journal(
    journal: InMemoryEventJournal,
    event: dict[str, Any],
) -> None:
    envelope_fields = {
        "event_name",
        "event_id",
        "event_seq",
        "event_schema_version",
        "session_id",
        "conversation_id",
        "source_module",
        "created_monotonic_ms",
        "created_wall_clock_ms",
        "trace_redaction_level",
        "caused_by_event_id",
        "supersedes_event_id",
    }
    fields = {
        key: deepcopy(value)
        for key, value in event.items()
        if key not in envelope_fields
    }
    journal.append(
        event_name=str(event["event_name"]),
        event_id=str(event["event_id"]),
        source_module=str(event["source_module"]),
        created_monotonic_ms=int(event["created_monotonic_ms"]),
        created_wall_clock_ms=int(event["created_wall_clock_ms"]),
        trace_redaction_level=str(event["trace_redaction_level"]),
        event_schema_version=str(event["event_schema_version"]),
        caused_by_event_id=event.get("caused_by_event_id"),
        supersedes_event_id=event.get("supersedes_event_id"),
        **fields,
    )


def _append_loaded_fixture_adr018_marker(
    fixture: dict[str, Any],
) -> None:
    terminal = fixture["events"][-1]
    shared = {
        "event_schema_version": "1.0",
        "session_id": terminal["session_id"],
        "conversation_id": terminal["conversation_id"],
        "source_module": "slice3b1_replay_test",
        "trace_redaction_level": "metadata_only",
        "adapter_id": "slice3b1_qwen_realtime_fake",
        "provider_session_generation": 1,
        "source_event_ids": (terminal["event_id"],),
        "playback_epoch": 0,
        "interaction_state_version": 0,
        "dropped_audio_frame_count": 0,
        "output_mode": "mock",
    }
    rebuilding = {
        **shared,
        "event_name": "PROVIDER_CONTEXT_STATE_CHANGED",
        "event_id": "evt_user_patch_provider_rebuilding",
        "event_seq": len(fixture["events"]) + 1,
        "created_monotonic_ms": int(terminal["created_monotonic_ms"]) + 1,
        "created_wall_clock_ms": int(terminal["created_wall_clock_ms"]) + 1,
        "caused_by_event_id": terminal["event_id"],
        "from_state": "CLOSED",
        "to_state": "REBUILDING",
        "reason": "user_patch_fixture_rebuild",
    }
    clean = {
        **shared,
        "event_name": "PROVIDER_CONTEXT_STATE_CHANGED",
        "event_id": "evt_user_patch_provider_clean",
        "event_seq": len(fixture["events"]) + 2,
        "created_monotonic_ms": int(terminal["created_monotonic_ms"]) + 2,
        "created_wall_clock_ms": int(terminal["created_wall_clock_ms"]) + 2,
        "caused_by_event_id": rebuilding["event_id"],
        "source_event_ids": (rebuilding["event_id"],),
        "from_state": "REBUILDING",
        "to_state": "CLEAN",
        "reason": "user_patch_fixture_ready",
    }
    fixture["events"].extend((rebuilding, clean))


def _adr018_historical_mvp3_fixture() -> dict[str, Any]:
    fixture = load_json_fixture(
        MVP3_REPLAY_FIXTURE_DIR
        / "008-fallback-degraded-replay.fixture.json"
    )
    session_started = fixture["events"][0]
    historical_terminal = fixture["events"][-1]
    shared_envelope = {
        "event_schema_version": "1.0",
        "session_id": session_started["session_id"],
        "conversation_id": session_started["conversation_id"],
        "source_module": "slice3b1_replay_test",
        "trace_redaction_level": "metadata_only",
    }
    provider_rebuilding = {
        **shared_envelope,
        "event_name": "PROVIDER_CONTEXT_STATE_CHANGED",
        "event_id": "evt_mvp3_slice8_provider_rebuilding",
        "caused_by_event_id": historical_terminal["event_id"],
        "adapter_id": "slice3b1_qwen_realtime_fake",
        "provider_session_generation": 1,
        "from_state": "CLOSED",
        "to_state": "REBUILDING",
        "reason": "historical_fixture_rebuild",
        "source_event_ids": (historical_terminal["event_id"],),
        "playback_epoch": 0,
        "interaction_state_version": 0,
        "dropped_audio_frame_count": 0,
        "output_mode": "mock",
    }
    provider_clean = {
        **shared_envelope,
        "event_name": "PROVIDER_CONTEXT_STATE_CHANGED",
        "event_id": "evt_mvp3_slice8_provider_clean",
        "caused_by_event_id": provider_rebuilding["event_id"],
        "adapter_id": "slice3b1_qwen_realtime_fake",
        "provider_session_generation": 1,
        "from_state": "REBUILDING",
        "to_state": "CLEAN",
        "reason": "historical_fixture_ready",
        "source_event_ids": (provider_rebuilding["event_id"],),
        "playback_epoch": 0,
        "interaction_state_version": 0,
        "dropped_audio_frame_count": 0,
        "output_mode": "mock",
    }
    fixture["events"].extend([provider_rebuilding, provider_clean])
    _resequence(fixture)
    return fixture


def _empty_fixture(case_id: str) -> dict[str, Any]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": f"slice3b1_parallel_{case_id}",
            "source_trace_ref": f"fixture://mvp6/slice3b1/{case_id}",
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
        "events": [],
    }


def _append(
    fixture: dict[str, Any],
    event_name: str,
    event_id: str,
    *,
    caused_by_event_id: str | None = None,
    **fields: object,
) -> dict[str, Any]:
    event = _base_event(
        event_name,
        event_id,
        caused_by_event_id=caused_by_event_id,
        **fields,
    )
    event_seq = len(fixture["events"]) + 1
    event["event_seq"] = event_seq
    event["created_monotonic_ms"] = event_seq
    event["created_wall_clock_ms"] = 1_700_000_000_000 + event_seq
    fixture["events"].append(event)
    return event


def _base_event(
    event_name: str,
    event_id: str,
    *,
    caused_by_event_id: str | None,
    **fields: object,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_name": event_name,
        "event_id": event_id,
        "event_schema_version": "1.0",
        "session_id": "sess_slice3b1_replay",
        "conversation_id": "conv_slice3b1_replay",
        "source_module": "slice3b1_replay_test",
        "trace_redaction_level": "metadata_only",
        **fields,
    }
    if caused_by_event_id is not None:
        event["caused_by_event_id"] = caused_by_event_id
    return event


def _event_by_id(fixture: dict[str, Any], event_id: str) -> dict[str, Any]:
    matches = [
        event
        for event in fixture["events"]
        if event["event_id"] == event_id
    ]
    assert len(matches) == 1
    return matches[0]


def _journal_event_by_id(
    events: list[dict[str, Any]],
    event_id: str,
) -> dict[str, Any]:
    matches = [
        event
        for event in events
        if event["event_id"] == event_id
    ]
    assert len(matches) == 1
    return matches[0]


def _ordered_event_by_id(
    result: object,
    event_id: str,
) -> dict[str, Any]:
    matches = [
        event
        for event in result.ordered_events
        if event["event_id"] == event_id
    ]
    assert len(matches) == 1
    return matches[0]
