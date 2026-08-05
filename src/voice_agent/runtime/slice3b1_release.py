from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import InitVar, dataclass, field, fields as dataclass_fields
import re
from threading import RLock
from typing import Any

from voice_agent.adapters.profiles import (
    AdapterProfileValidationError,
    capability_matrix_digest,
    validate_slice3b1_adapter_profile_set,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateEligibilityFactsV1,
)
from voice_agent.events.journal import (
    InMemoryEventJournal,
    JournalAppendRequest,
)
from voice_agent.privacy.redaction import (
    is_safe_release_token_id,
    is_safe_release_token_ref,
)
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyResult


SLICE3B1_GATE_POLICY_VERSION = "slice3b1.parallel_gate.v1"
SLICE3B1_CANDIDATE_CHECK_POLICY_VERSION = (
    "slice3b1.parallel_candidate_checks.v1"
)

_PARALLEL_TOPOLOGY = "speculative_candidate_parallel_route"
_CONTEXT_FACTORY_KEY = object()
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANDIDATE_AUDIO_FORMAT_REF = re.compile(
    r"\A(?=.{1,240}\Z)audio-format://(?:synthetic|local)/"
    r"[A-Za-z0-9][A-Za-z0-9._~-]{0,79}"
    r"(?:/[A-Za-z0-9][A-Za-z0-9._~-]{0,79})*\Z"
)
_EXPECTED_ADAPTER_IDS = {
    "asr": "slice3b1_qwen_realtime_asr_projection",
    "duplex_model": "slice3b1_qwen_realtime_fake",
    "fast_interaction": "slice3b1_parallel_fast_interaction_orchestrator",
    "route_evidence": "slice3b1_route_evidence_fake",
}
_GATE_READY_INTERACTION_STATES = frozenset({"TURN_COMMITTED", "RESPONDING"})
_PROVIDER_CONTEXT_STATES = frozenset(
    {"CLEAN", "CLEANUP_PENDING", "TAINTED", "REBUILDING", "CLOSED"}
)


class ParallelForegroundReleaseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ForegroundReleaseTokenV1:
    release_token_id: str
    session_id: str
    provider_session_generation: int
    context_snapshot_id: str
    source_event_seq: int
    turn_id: str
    utterance_id: str
    qwen_response_id: str
    qwen_output_item_id: str
    qwen_output_index: int
    qwen_content_index: int
    candidate_id: str
    candidate_transcript_digest: str
    candidate_pcm_manifest_digest: str
    candidate_audio_format_ref: str
    candidate_audio_duration_ms: int
    candidate_audio_shadow_verification_event_id: str | None
    router_decision_event_id: str
    route_evidence_event_id: str
    candidate_safety_evidence_event_id: str
    playback_epoch: int
    gate_policy_version: str

    def __post_init__(self) -> None:
        if not is_safe_release_token_id(self.release_token_id):
            raise ParallelForegroundReleaseError("release_token_id is invalid")
        for name in (
            "session_id",
            "context_snapshot_id",
            "turn_id",
            "utterance_id",
            "qwen_response_id",
            "qwen_output_item_id",
            "candidate_id",
            "candidate_audio_format_ref",
            "router_decision_event_id",
            "route_evidence_event_id",
            "candidate_safety_evidence_event_id",
            "gate_policy_version",
        ):
            _require_safe_token(getattr(self, name), name)
        if self.candidate_audio_shadow_verification_event_id is not None:
            _require_safe_token(
                self.candidate_audio_shadow_verification_event_id,
                "candidate_audio_shadow_verification_event_id",
            )
        _require_digest(
            self.candidate_transcript_digest,
            "candidate_transcript_digest",
        )
        _require_digest(
            self.candidate_pcm_manifest_digest,
            "candidate_pcm_manifest_digest",
        )
        if (
            _CANDIDATE_AUDIO_FORMAT_REF.fullmatch(
                self.candidate_audio_format_ref
            )
            is None
        ):
            raise ParallelForegroundReleaseError(
                "candidate_audio_format_ref is invalid"
            )
        _require_positive_int(
            self.provider_session_generation,
            "provider_session_generation",
        )
        _require_positive_int(self.source_event_seq, "source_event_seq")
        _require_nonnegative_int(self.qwen_output_index, "qwen_output_index")
        _require_nonnegative_int(self.qwen_content_index, "qwen_content_index")
        _require_nonnegative_int(self.playback_epoch, "playback_epoch")
        duration = _require_positive_int(
            self.candidate_audio_duration_ms,
            "candidate_audio_duration_ms",
        )
        if duration > 2_000:
            raise ParallelForegroundReleaseError(
                "candidate_audio_duration_ms exceeds 2000"
            )


@dataclass(frozen=True, slots=True)
class ParallelForegroundGateContextV1:
    assembly_stage: str = field(init=False, default="slice3b1_mock")
    output_mode: str = field(init=False, default="mock")
    native_pcm_enabled: bool = field(init=False, default=False)
    capability_snapshot_event_id: str
    capability_matrix_digest: str
    session_id: str
    provider_session_generation: int
    context_snapshot_id: str
    source_event_seq: int
    turn_id: str
    utterance_id: str
    qwen_response_id: str
    qwen_output_item_id: str
    qwen_output_index: int
    qwen_content_index: int
    candidate_id: str
    candidate_transcript_digest: str
    candidate_pcm_manifest_digest: str
    candidate_audio_format_ref: str
    candidate_audio_duration_ms: int
    candidate_audio_shadow_verification_event_id: str | None
    router_decision_event_id: str
    route_evidence_event_id: str
    candidate_safety_evidence_event_id: str
    playback_epoch: int
    gate_policy_version: str
    provider_context_state: str
    interaction_state: str
    candidate_check_policy_version: str
    candidate_unicode_scalar_count: int
    candidate_length_check: str
    candidate_duration_check: str
    candidate_terminal_check: str
    candidate_safety_decision: str
    native_pcm_capability_check: str
    generation_check: str
    context_snapshot_check: str
    route_evidence_check: str
    candidate_safety_check: str
    transcript_digest_check: str
    pcm_manifest_check: str
    correlation_check: str
    router_decision: str
    task_focus: str
    foreground_act: str
    risk_class: str
    _factory_key: InitVar[object] = None

    def __post_init__(self, _factory_key: object) -> None:
        if _factory_key is not _CONTEXT_FACTORY_KEY:
            raise TypeError(
                "ParallelForegroundGateContextV1 construction is internal"
            )


@dataclass(frozen=True, slots=True)
class PlaybackOutboxItemV1:
    outbox_item_id: str
    release_token_ref: str
    provider_session_generation: int
    qwen_response_id: str
    qwen_output_item_id: str
    qwen_output_index: int
    qwen_content_index: int
    candidate_id: str
    playback_epoch: int
    pcm_handle: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not self.release_token_ref.startswith(
                "release-token://synthetic/"
            )
            or not is_safe_release_token_ref(
                self.release_token_ref,
                allow_local=False,
            )
        ):
            raise ParallelForegroundReleaseError(
                "release_token_ref must be an exact synthetic release ref"
            )
        for name in (
            "outbox_item_id",
            "qwen_response_id",
            "qwen_output_item_id",
            "candidate_id",
        ):
            _require_safe_token(getattr(self, name), name)
        _require_positive_int(
            self.provider_session_generation,
            "provider_session_generation",
        )
        _require_nonnegative_int(self.qwen_output_index, "qwen_output_index")
        _require_nonnegative_int(self.qwen_content_index, "qwen_content_index")
        _require_nonnegative_int(self.playback_epoch, "playback_epoch")
        if not callable(getattr(self.pcm_handle, "release", None)):
            raise ParallelForegroundReleaseError(
                "pcm_handle must support terminal release"
            )


@dataclass(frozen=True, slots=True)
class _PlaybackOutboxReservation:
    item: PlaybackOutboxItemV1


class InMemoryPlaybackOutbox:
    __slots__ = ("_authority_lock", "_items", "_max_items")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("InMemoryPlaybackOutbox is final")

    def __init__(self, *, max_items: int) -> None:
        self._max_items = _require_positive_int(max_items, "max_items")
        self._items: list[PlaybackOutboxItemV1] = []
        self._authority_lock = RLock()

    def items(self) -> tuple[PlaybackOutboxItemV1, ...]:
        with self._authority_lock:
            return tuple(self._items)

    def _preflight_locked(
        self,
        item: PlaybackOutboxItemV1,
    ) -> _PlaybackOutboxReservation:
        if len(self._items) >= self._max_items:
            raise ParallelForegroundReleaseError("playback outbox capacity exceeded")
        if any(
            existing.outbox_item_id == item.outbox_item_id
            or existing.release_token_ref == item.release_token_ref
            for existing in self._items
        ):
            raise ParallelForegroundReleaseError(
                "duplicate playback outbox reservation"
            )
        return _PlaybackOutboxReservation(item=item)

    def _commit_locked(self, reservation: _PlaybackOutboxReservation) -> None:
        self._items.append(reservation.item)


@dataclass(frozen=True, slots=True)
class ParallelForegroundGateResult:
    gate_event: dict[str, Any]
    committed_event: dict[str, Any] | None
    discarded_event: dict[str, Any] | None
    release_token: ForegroundReleaseTokenV1 | None


def build_slice3b1_gate_context(
    *,
    journal: InMemoryEventJournal,
    assembly_result: RuntimeAdapterAssemblyResult,
    assembly_stage: str,
    capability_snapshot_event: Mapping[str, Any],
    eligibility_facts: CandidateEligibilityFactsV1,
    fast_interaction_output_event: Mapping[str, Any],
    candidate_event: Mapping[str, Any],
    router_decision_event: Mapping[str, Any],
    route_evidence_event: Mapping[str, Any],
    candidate_safety_event: Mapping[str, Any],
    provider_context_state: str,
    interaction_state: str,
    candidate_audio_shadow_verification_event_id: str | None = None,
) -> ParallelForegroundGateContextV1:
    if assembly_stage != "slice3b1_mock":
        raise ParallelForegroundReleaseError(
            "assembly_stage must be slice3b1_mock"
        )
    if not isinstance(assembly_result, RuntimeAdapterAssemblyResult):
        raise ParallelForegroundReleaseError(
            "assembly_result must be a validated runtime assembly"
        )
    matrices, matrix_digest = _validate_slice3b1_mock_assembly(assembly_result)
    del matrices
    snapshot = _require_recorded_event(
        journal,
        capability_snapshot_event,
        "capability snapshot",
    )
    if snapshot.get("event_name") != "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED":
        raise ParallelForegroundReleaseError(
            "capability snapshot event type is invalid"
        )
    for key, expected in assembly_result.capability_snapshot.items():
        if snapshot.get(key) != expected:
            raise ParallelForegroundReleaseError(
                "capability snapshot does not match assembly"
            )
    if (
        snapshot.get("capability_matrix_digest") != matrix_digest
        or assembly_result.capability_snapshot.get("capability_matrix_digest")
        != matrix_digest
    ):
        raise ParallelForegroundReleaseError(
            "capability snapshot digest does not match assembly"
        )
    allowed_snapshot_fields = {
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
        *assembly_result.capability_snapshot.keys(),
    }
    if set(snapshot) - allowed_snapshot_fields:
        raise ParallelForegroundReleaseError(
            "capability snapshot contains unsupported claims"
        )
    if not isinstance(eligibility_facts, CandidateEligibilityFactsV1):
        raise ParallelForegroundReleaseError(
            "eligibility_facts must be CandidateEligibilityFactsV1"
        )

    fast = _require_recorded_event(
        journal,
        fast_interaction_output_event,
        "Fast Interaction output",
    )
    candidate = _require_recorded_event(
        journal,
        candidate_event,
        "candidate",
    )
    router = _require_recorded_event(
        journal,
        router_decision_event,
        "Router decision",
    )
    route = _require_recorded_event(
        journal,
        route_evidence_event,
        "Route Evidence",
    )
    safety = _require_recorded_event(
        journal,
        candidate_safety_event,
        "candidate safety",
    )
    _validate_parallel_gate_bindings(
        eligibility_facts=eligibility_facts,
        fast=fast,
        candidate=candidate,
        router=router,
        route=route,
        safety=safety,
    )
    if provider_context_state not in _PROVIDER_CONTEXT_STATES:
        raise ParallelForegroundReleaseError("provider_context_state is invalid")
    _require_safe_token(interaction_state, "interaction_state")
    if candidate_audio_shadow_verification_event_id is not None:
        shadow = _event_by_id(
            journal,
            candidate_audio_shadow_verification_event_id,
            "shadow verification",
        )
        _validate_shadow_verification(shadow, eligibility_facts)

    length_check = (
        "PASS"
        if 1 <= eligibility_facts.candidate_unicode_scalar_count <= 80
        else "FAIL"
    )
    duration_check = (
        "PASS"
        if 1 <= eligibility_facts.candidate_audio_duration_ms <= 2_000
        else "FAIL"
    )
    terminal_check = (
        "PASS"
        if eligibility_facts.provider_terminal_status == "completed"
        and candidate.get("candidate_status") == "complete"
        else "FAIL"
    )
    prohibited_flags = safety.get("prohibited_flags")
    candidate_safety_check = (
        "PASS"
        if safety.get("decision") == "SAFE"
        and isinstance(prohibited_flags, (tuple, list))
        and len(prohibited_flags) == 0
        and _confidence(safety.get("confidence")) >= 0.90
        else "FAIL"
    )
    route_evidence_check = (
        "PASS"
        if route.get("normalization_status") == "normalized"
        and route.get("route_hint") == router.get("router_decision")
        and route.get("evidence_uncertainty") == "LOW"
        and _confidence(route.get("confidence")) >= 0.80
        else "FAIL"
    )
    source_event_seq = max(
        int(fast["event_seq"]),
        int(candidate["event_seq"]),
        int(router["event_seq"]),
        int(route["event_seq"]),
        int(safety["event_seq"]),
    )
    facts = eligibility_facts
    return ParallelForegroundGateContextV1(
        capability_snapshot_event_id=str(snapshot["event_id"]),
        capability_matrix_digest=matrix_digest,
        session_id=str(snapshot["session_id"]),
        provider_session_generation=facts.provider_session_generation,
        context_snapshot_id=facts.context_snapshot_id,
        source_event_seq=source_event_seq,
        turn_id=facts.turn_id,
        utterance_id=facts.utterance_id,
        qwen_response_id=facts.qwen_response_id,
        qwen_output_item_id=facts.qwen_output_item_id,
        qwen_output_index=facts.qwen_output_index,
        qwen_content_index=facts.qwen_content_index,
        candidate_id=facts.candidate_id,
        candidate_transcript_digest=facts.candidate_transcript_digest,
        candidate_pcm_manifest_digest=facts.candidate_pcm_manifest_digest,
        candidate_audio_format_ref=facts.candidate_audio_format_ref,
        candidate_audio_duration_ms=facts.candidate_audio_duration_ms,
        candidate_audio_shadow_verification_event_id=(
            candidate_audio_shadow_verification_event_id
        ),
        router_decision_event_id=str(router["event_id"]),
        route_evidence_event_id=str(route["event_id"]),
        candidate_safety_evidence_event_id=str(safety["event_id"]),
        playback_epoch=facts.bound_playback_epoch,
        gate_policy_version=SLICE3B1_GATE_POLICY_VERSION,
        provider_context_state=provider_context_state,
        interaction_state=interaction_state,
        candidate_check_policy_version=(
            SLICE3B1_CANDIDATE_CHECK_POLICY_VERSION
        ),
        candidate_unicode_scalar_count=facts.candidate_unicode_scalar_count,
        candidate_length_check=length_check,
        candidate_duration_check=duration_check,
        candidate_terminal_check=terminal_check,
        candidate_safety_decision=str(safety["decision"]),
        native_pcm_capability_check="FAIL",
        generation_check="PASS",
        context_snapshot_check="PASS",
        route_evidence_check=route_evidence_check,
        candidate_safety_check=candidate_safety_check,
        transcript_digest_check="PASS",
        pcm_manifest_check="PASS",
        correlation_check="PASS",
        router_decision=str(router["router_decision"]),
        task_focus=str(router.get("task_focus", "")),
        foreground_act=str(fast["foreground_act"]),
        risk_class=str(route["risk_class"]),
        _factory_key=_CONTEXT_FACTORY_KEY,
    )


def run_parallel_fast_foreground_gate(
    *,
    journal: InMemoryEventJournal,
    candidate_event: Mapping[str, Any],
    fast_interaction_output_event: Mapping[str, Any],
    router_decision_event: Mapping[str, Any],
    route_evidence_event: Mapping[str, Any],
    candidate_safety_event: Mapping[str, Any],
    context: ParallelForegroundGateContextV1,
    outbox: InMemoryPlaybackOutbox,
    event_ids: Mapping[str, str],
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> ParallelForegroundGateResult:
    if not isinstance(context, ParallelForegroundGateContextV1):
        raise ParallelForegroundReleaseError(
            "context must be ParallelForegroundGateContextV1"
        )
    if not isinstance(outbox, InMemoryPlaybackOutbox):
        raise ParallelForegroundReleaseError(
            "outbox must be InMemoryPlaybackOutbox"
        )
    fast = _require_recorded_event(
        journal,
        fast_interaction_output_event,
        "Fast Interaction output",
    )
    candidate = _require_recorded_event(journal, candidate_event, "candidate")
    router = _require_recorded_event(
        journal,
        router_decision_event,
        "Router decision",
    )
    route = _require_recorded_event(
        journal,
        route_evidence_event,
        "Route Evidence",
    )
    safety = _require_recorded_event(
        journal,
        candidate_safety_event,
        "candidate safety",
    )
    snapshot_matches = [
        event
        for event in journal.events()
        if event.get("event_id") == context.capability_snapshot_event_id
    ]
    if (
        len(snapshot_matches) != 1
        or snapshot_matches[0].get("event_name")
        != "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"
        or snapshot_matches[0].get("capability_matrix_digest")
        != context.capability_matrix_digest
    ):
        raise ParallelForegroundReleaseError(
            "canonical capability snapshot binding is invalid"
        )
    _validate_runtime_context_bindings(
        context=context,
        fast=fast,
        candidate=candidate,
        router=router,
        route=route,
        safety=safety,
    )
    ids = _validated_event_ids(
        journal,
        event_ids,
        required=(
            "gate_event_id",
            "gate_decision_id",
            "discard_event_id",
            "discard_id",
        ),
    )
    failure_reason = _parallel_failure_reason(context)
    gate_event, discarded_event = journal.append_atomic_batch(
        (
            JournalAppendRequest(
                event_name="FOREGROUND_ACT_GATE_FAILED",
                event_id=ids["gate_event_id"],
                source_module="slice3b1_fast_foreground_gate",
                caused_by_event_id=str(router["event_id"]),
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                trace_redaction_level="metadata_only",
                fields={
                    "gate_decision_id": ids["gate_decision_id"],
                    "candidate_event_id": str(candidate["event_id"]),
                    "router_decision_event_id": str(router["event_id"]),
                    "foreground_act": context.foreground_act,
                    "risk_class": context.risk_class,
                    "confidence": _confidence(route.get("confidence")),
                    "policy_version": context.gate_policy_version,
                    "failure_reason": failure_reason,
                    "downgrade_policy": "discard_only",
                    "fast_interaction_topology": _PARALLEL_TOPOLOGY,
                    **_parallel_gate_event_fields(context),
                    "authority_mode": "default_runtime",
                    "output_mode": "mock",
                    "qualification_status": "not_qualification",
                },
            ),
            JournalAppendRequest(
                event_name="FOREGROUND_OUTPUT_DISCARDED",
                event_id=ids["discard_event_id"],
                source_module="foreground_buffer",
                caused_by_event_id=ids["gate_event_id"],
                created_monotonic_ms=created_monotonic_ms + 1,
                created_wall_clock_ms=created_wall_clock_ms + 1,
                trace_redaction_level="metadata_only",
                fields={
                    "discard_id": ids["discard_id"],
                    "candidate_event_id": str(candidate["event_id"]),
                    "fast_interaction_output_event_id": str(fast["event_id"]),
                    "router_decision_event_id": str(router["event_id"]),
                    "discard_reason": failure_reason,
                    "fast_interaction_topology": _PARALLEL_TOPOLOGY,
                    "authority_mode": "default_runtime",
                    "output_mode": "mock",
                    "qualification_status": "not_qualification",
                },
            ),
        )
    )
    return ParallelForegroundGateResult(
        gate_event=gate_event,
        committed_event=None,
        discarded_event=discarded_event,
        release_token=None,
    )


def _compare_authorize_and_enqueue_contract_only(
    *,
    journal: InMemoryEventJournal,
    expected_token: ForegroundReleaseTokenV1,
    current_binding_reader: Callable[[], ForegroundReleaseTokenV1],
    candidate_eligibility_facts: CandidateEligibilityFactsV1,
    candidate_event: Mapping[str, Any],
    fast_interaction_output_event: Mapping[str, Any],
    release_token_ref: str,
    outbox: InMemoryPlaybackOutbox,
    pcm_handle: object,
    event_ids: Mapping[str, str],
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> ParallelForegroundGateResult:
    """Exercise the ADR-018 atomic release contract without runtime enablement.

    This private primitive is intentionally unreachable from runners and CLI
    surfaces. It proves exact comparison, journal atomicity, and memory-only
    outbox handoff while remaining mock and non-qualifying.
    """

    if not isinstance(expected_token, ForegroundReleaseTokenV1):
        _release_pcm_handle(pcm_handle)
        raise ParallelForegroundReleaseError(
            "expected_token must be ForegroundReleaseTokenV1"
        )
    if not isinstance(outbox, InMemoryPlaybackOutbox):
        _release_pcm_handle(pcm_handle)
        raise ParallelForegroundReleaseError(
            "outbox must be InMemoryPlaybackOutbox"
        )
    if not isinstance(
        candidate_eligibility_facts,
        CandidateEligibilityFactsV1,
    ):
        _release_pcm_handle(pcm_handle)
        raise ParallelForegroundReleaseError(
            "candidate_eligibility_facts must be CandidateEligibilityFactsV1"
        )
    if not callable(current_binding_reader):
        _release_pcm_handle(pcm_handle)
        raise ParallelForegroundReleaseError(
            "current_binding_reader must be callable"
        )

    with outbox._authority_lock:
        try:
            current = current_binding_reader()
            if not isinstance(current, ForegroundReleaseTokenV1):
                raise ParallelForegroundReleaseError(
                    "current binding is not ForegroundReleaseTokenV1"
                )
            for token_field in dataclass_fields(ForegroundReleaseTokenV1):
                field_name = token_field.name
                if getattr(expected_token, field_name) != getattr(
                    current,
                    field_name,
                ):
                    raise ParallelForegroundReleaseError(
                        f"binding mismatch: {field_name}"
                    )

            candidate = _require_recorded_event(
                journal,
                candidate_event,
                "candidate",
            )
            fast = _require_recorded_event(
                journal,
                fast_interaction_output_event,
                "Fast Interaction output",
            )
            router = _event_by_id(
                journal,
                expected_token.router_decision_event_id,
                "Router decision",
            )
            route = _event_by_id(
                journal,
                expected_token.route_evidence_event_id,
                "Route Evidence",
            )
            safety = _event_by_id(
                journal,
                expected_token.candidate_safety_evidence_event_id,
                "candidate safety",
            )
            _validate_contract_token_binding(
                token=expected_token,
                eligibility_facts=candidate_eligibility_facts,
                candidate=candidate,
                fast=fast,
                router=router,
                route=route,
                safety=safety,
                journal=journal,
            )

            expected_release_ref = (
                "release-token://synthetic/"
                f"{expected_token.release_token_id}"
            )
            if (
                release_token_ref != expected_release_ref
                or not is_safe_release_token_ref(
                    release_token_ref,
                    allow_local=False,
                )
            ):
                raise ParallelForegroundReleaseError(
                    "release_token_ref must equal the derived synthetic ref"
                )
            ids = _validated_event_ids(
                journal,
                event_ids,
                required=(
                    "gate_event_id",
                    "gate_decision_id",
                    "committed_event_id",
                    "foreground_output_id",
                ),
            )
            supplied_token_id = event_ids.get("release_token_id")
            if supplied_token_id != expected_token.release_token_id:
                raise ParallelForegroundReleaseError(
                    "event_ids release_token_id binding is invalid"
                )
            outbox_item = PlaybackOutboxItemV1(
                outbox_item_id=(
                    "playback_outbox_"
                    f"{expected_token.release_token_id.removeprefix('release_token_')}"
                ),
                release_token_ref=release_token_ref,
                provider_session_generation=(
                    expected_token.provider_session_generation
                ),
                qwen_response_id=expected_token.qwen_response_id,
                qwen_output_item_id=expected_token.qwen_output_item_id,
                qwen_output_index=expected_token.qwen_output_index,
                qwen_content_index=expected_token.qwen_content_index,
                candidate_id=expected_token.candidate_id,
                playback_epoch=expected_token.playback_epoch,
                pcm_handle=pcm_handle,
            )
            reservation = outbox._preflight_locked(outbox_item)
            confidence = min(
                _confidence(route.get("confidence")),
                _confidence(safety.get("confidence")),
            )
            gate_fields = {
                "gate_decision_id": ids["gate_decision_id"],
                "candidate_event_id": str(candidate["event_id"]),
                "router_decision_event_id": str(router["event_id"]),
                "foreground_act": "ANSWER",
                "risk_class": "LOW",
                "confidence": confidence,
                "policy_version": expected_token.gate_policy_version,
                "pass_reason": "mock_contract_exact_binding",
                "fast_interaction_topology": _PARALLEL_TOPOLOGY,
                "candidate_check_policy_version": (
                    SLICE3B1_CANDIDATE_CHECK_POLICY_VERSION
                ),
                "candidate_length_check": "PASS",
                "candidate_duration_check": "PASS",
                "candidate_terminal_check": "PASS",
                "native_pcm_capability_check": "PASS",
                "generation_check": "PASS",
                "context_snapshot_check": "PASS",
                "route_evidence_check": "PASS",
                "candidate_safety_check": "PASS",
                "transcript_digest_check": "PASS",
                "pcm_manifest_check": "PASS",
                "correlation_check": "PASS",
                "provider_session_generation": (
                    expected_token.provider_session_generation
                ),
                "context_snapshot_id": expected_token.context_snapshot_id,
                "route_evidence_event_id": (
                    expected_token.route_evidence_event_id
                ),
                "candidate_safety_evidence_event_id": (
                    expected_token.candidate_safety_evidence_event_id
                ),
                "release_token_ref": release_token_ref,
                "authority_mode": "mock_contract_only",
                "output_mode": "mock",
                "qualification_status": "not_qualification",
            }
            commit_fields = {
                "foreground_output_id": ids["foreground_output_id"],
                "turn_id": expected_token.turn_id,
                "utterance_id": expected_token.utterance_id,
                "output_ref": release_token_ref,
                "output_basis": "reply_candidate",
                "foreground_act": "ANSWER",
                "gate_event_id": ids["gate_event_id"],
                "router_decision_event_id": str(router["event_id"]),
                "user_visible_channel": "audio_pending",
                "fast_interaction_topology": _PARALLEL_TOPOLOGY,
                "release_token_ref": release_token_ref,
                "authority_mode": "mock_contract_only",
                "output_mode": "mock",
                "qualification_status": "not_qualification",
            }
            gate_event, committed_event = journal.append_atomic_batch(
                (
                    JournalAppendRequest(
                        event_name="FOREGROUND_ACT_GATE_PASSED",
                        event_id=ids["gate_event_id"],
                        source_module="slice3b1_fast_foreground_gate",
                        caused_by_event_id=str(router["event_id"]),
                        created_monotonic_ms=created_monotonic_ms,
                        created_wall_clock_ms=created_wall_clock_ms,
                        trace_redaction_level="metadata_only",
                        fields=gate_fields,
                    ),
                    JournalAppendRequest(
                        event_name="FOREGROUND_OUTPUT_COMMITTED",
                        event_id=ids["committed_event_id"],
                        source_module="foreground_output_runtime",
                        caused_by_event_id=ids["gate_event_id"],
                        created_monotonic_ms=created_monotonic_ms + 1,
                        created_wall_clock_ms=created_wall_clock_ms + 1,
                        trace_redaction_level="metadata_only",
                        fields=commit_fields,
                    ),
                )
            )
            outbox._commit_locked(reservation)
        except Exception:
            _release_pcm_handle(pcm_handle)
            raise

    return ParallelForegroundGateResult(
        gate_event=gate_event,
        committed_event=committed_event,
        discarded_event=None,
        release_token=expected_token,
    )


def _validate_slice3b1_mock_assembly(
    assembly_result: RuntimeAdapterAssemblyResult,
) -> tuple[tuple[dict[str, Any], ...], str]:
    try:
        validated_matrices = validate_slice3b1_adapter_profile_set(
            assembly_result.capabilities
        )
    except (AdapterProfileValidationError, TypeError, ValueError) as exc:
        raise ParallelForegroundReleaseError(
            "slice3b1 mock assembly validation failed"
        ) from exc
    normalized_declared = tuple(
        dict(matrix) for matrix in assembly_result.capability_matrices
    )
    if validated_matrices != normalized_declared:
        raise ParallelForegroundReleaseError(
            "assembly matrices do not match validated capabilities"
        )
    by_type = {str(matrix["adapter_type"]): matrix for matrix in validated_matrices}
    if set(by_type) != set(_EXPECTED_ADAPTER_IDS):
        raise ParallelForegroundReleaseError(
            "assembly adapter roles are incomplete"
        )
    for adapter_type, expected_id in _EXPECTED_ADAPTER_IDS.items():
        matrix = by_type[adapter_type]
        if (
            matrix.get("adapter_id") != expected_id
            or matrix.get("deployment_mode") != "provider_free"
            or matrix.get("output_mode") != "mock"
            or matrix.get("status") != "mock"
            or matrix.get("mocked") is not True
            or matrix.get("real_live_support") is not False
        ):
            raise ParallelForegroundReleaseError(
                "assembly adapter identity or mode is invalid"
            )
    if (
        by_type["duplex_model"].get(
            "supports_provider_native_audio_release"
        )
        is not False
    ):
        raise ParallelForegroundReleaseError(
            "assembly cannot claim native PCM release support"
        )
    return validated_matrices, capability_matrix_digest(validated_matrices)


def _validate_contract_token_binding(
    *,
    token: ForegroundReleaseTokenV1,
    eligibility_facts: CandidateEligibilityFactsV1,
    candidate: Mapping[str, Any],
    fast: Mapping[str, Any],
    router: Mapping[str, Any],
    route: Mapping[str, Any],
    safety: Mapping[str, Any],
    journal: InMemoryEventJournal,
) -> None:
    facts_expected = {
        "provider_session_generation": (
            eligibility_facts.provider_session_generation
        ),
        "context_snapshot_id": eligibility_facts.context_snapshot_id,
        "turn_id": eligibility_facts.turn_id,
        "utterance_id": eligibility_facts.utterance_id,
        "qwen_response_id": eligibility_facts.qwen_response_id,
        "qwen_output_item_id": eligibility_facts.qwen_output_item_id,
        "qwen_output_index": eligibility_facts.qwen_output_index,
        "qwen_content_index": eligibility_facts.qwen_content_index,
        "candidate_id": eligibility_facts.candidate_id,
        "candidate_transcript_digest": (
            eligibility_facts.candidate_transcript_digest
        ),
        "candidate_pcm_manifest_digest": (
            eligibility_facts.candidate_pcm_manifest_digest
        ),
        "candidate_audio_format_ref": (
            eligibility_facts.candidate_audio_format_ref
        ),
        "candidate_audio_duration_ms": (
            eligibility_facts.candidate_audio_duration_ms
        ),
        "playback_epoch": eligibility_facts.bound_playback_epoch,
    }
    if (
        any(
            getattr(token, name) != value
            for name, value in facts_expected.items()
        )
        or not 1
        <= eligibility_facts.candidate_unicode_scalar_count
        <= 80
        or eligibility_facts.provider_terminal_status != "completed"
    ):
        raise ParallelForegroundReleaseError(
            "contract candidate checks are not authorizing"
        )
    if (
        candidate.get("event_name") != "FOREGROUND_REPLY_CANDIDATE_EMITTED"
        or fast.get("event_name") != "FAST_INTERACTION_OUTPUT_EMITTED"
        or router.get("event_name") != "ROUTER_DECISION_EMITTED"
        or route.get("event_name") != "ROUTE_EVIDENCE_OUTPUT_EMITTED"
        or safety.get("event_name")
        != "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED"
    ):
        raise ParallelForegroundReleaseError(
            "contract predecessor event type is invalid"
        )
    expected = {
        "session_id": candidate.get("session_id"),
        "provider_session_generation": candidate.get(
            "provider_session_generation"
        ),
        "context_snapshot_id": candidate.get("context_snapshot_id"),
        "turn_id": candidate.get("turn_id"),
        "utterance_id": candidate.get("utterance_id"),
        "qwen_response_id": candidate.get("qwen_response_id"),
        "qwen_output_item_id": candidate.get("qwen_output_item_id"),
        "qwen_output_index": candidate.get("qwen_output_index"),
        "qwen_content_index": candidate.get("qwen_content_index"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_transcript_digest": candidate.get(
            "candidate_transcript_digest"
        ),
        "candidate_pcm_manifest_digest": candidate.get(
            "candidate_pcm_manifest_digest"
        ),
        "candidate_audio_format_ref": candidate.get(
            "candidate_audio_format_ref"
        ),
        "candidate_audio_duration_ms": candidate.get(
            "candidate_audio_duration_ms"
        ),
        "router_decision_event_id": router.get("event_id"),
        "route_evidence_event_id": route.get("event_id"),
        "candidate_safety_evidence_event_id": safety.get("event_id"),
    }
    if any(getattr(token, name) != value for name, value in expected.items()):
        raise ParallelForegroundReleaseError(
            "expected token does not match recorded predecessor bindings"
        )
    for event in (fast, route, safety):
        if (
            event.get("turn_id") != token.turn_id
            or event.get("utterance_id") != token.utterance_id
            or event.get("provider_session_generation")
            != token.provider_session_generation
            or event.get("context_snapshot_id")
            != token.context_snapshot_id
        ):
            raise ParallelForegroundReleaseError(
                "contract cross-event binding is inconsistent"
            )
    if (
        router.get("turn_id") != token.turn_id
        or router.get("utterance_id") != token.utterance_id
    ):
        raise ParallelForegroundReleaseError(
            "contract cross-event binding is inconsistent"
        )
    if (
        fast.get("route_evidence_event_id") != route.get("event_id")
        or fast.get("candidate_safety_evidence_event_id")
        != safety.get("event_id")
        or candidate.get("route_evidence_event_id") != route.get("event_id")
        or candidate.get("candidate_safety_evidence_event_id")
        != safety.get("event_id")
        or router.get("route_evidence_event_id") != route.get("event_id")
        or safety.get("qwen_response_id") != token.qwen_response_id
        or safety.get("candidate_transcript_digest")
        != token.candidate_transcript_digest
        or fast.get("route_evidence_adapter_request_id")
        != route.get("adapter_request_id")
        or fast.get("candidate_safety_adapter_request_id")
        != safety.get("adapter_request_id")
        or fast.get("output_mode") != "mock"
        or route.get("output_mode") != "mock"
        or safety.get("output_mode") != "mock"
    ):
        raise ParallelForegroundReleaseError(
            "contract cross-event binding is inconsistent"
        )
    fast_source_event_ids = fast.get("source_event_ids")
    candidate_source_event_ids = candidate.get("source_event_ids")
    if not isinstance(fast_source_event_ids, (tuple, list)):
        raise ParallelForegroundReleaseError(
            "contract cross-event binding is inconsistent"
        )
    required_fast_sources = {
        str(route["event_id"]),
        str(safety["event_id"]),
    }
    normalized_fast_sources = {
        str(event_id) for event_id in fast_source_event_ids
    }
    required_candidate_sources = {
        *normalized_fast_sources,
        str(fast["event_id"]),
    }
    if (
        not required_fast_sources.issubset(normalized_fast_sources)
        or not isinstance(candidate_source_event_ids, (tuple, list))
        or not required_candidate_sources.issubset(
            {str(event_id) for event_id in candidate_source_event_ids}
        )
        or tuple(fast.get("risk_tags", ()))
        != tuple(route.get("risk_tags", ()))
        or tuple(candidate.get("risk_tags", ()))
        != tuple(fast.get("risk_tags", ()))
        or _confidence(fast.get("confidence"))
        != min(
            _confidence(route.get("confidence")),
            _confidence(safety.get("confidence")),
        )
        or _confidence(candidate.get("confidence"))
        != _confidence(fast.get("confidence"))
    ):
        raise ParallelForegroundReleaseError(
            "contract cross-event binding is inconsistent"
        )
    if (
        token.gate_policy_version != SLICE3B1_GATE_POLICY_VERSION
        or candidate.get("fast_interaction_topology") != _PARALLEL_TOPOLOGY
        or fast.get("fast_interaction_topology") != _PARALLEL_TOPOLOGY
        or candidate.get("candidate_status") != "complete"
        or candidate.get("fast_interaction_output_event_id")
        != fast.get("event_id")
        or candidate.get("caused_by_event_id") != fast.get("event_id")
        or fast.get("route_evidence_event_id") != route.get("event_id")
        or fast.get("candidate_safety_evidence_event_id")
        != safety.get("event_id")
        or router.get("router_decision") != "FAST_ONLY"
        or router.get("task_focus") != "FOREGROUND_CHAT"
        or route.get("route_hint") != "FAST_ONLY"
        or route.get("task_focus_hint") != "FOREGROUND_CHAT"
        or route.get("foreground_act_hint") != "ANSWER"
        or route.get("normalization_status") != "normalized"
        or route.get("schema_name")
        != "voice_agent.route_evidence.output.v1"
        or route.get("evidence_uncertainty") != "LOW"
        or _confidence(route.get("confidence")) < 0.80
        or fast.get("foreground_act") != "ANSWER"
        or fast.get("risk_class") != "LOW"
        or route.get("risk_class") != "LOW"
        or safety.get("normalization_status") != "normalized"
        or safety.get("schema_name")
        != "voice_agent.candidate_safety.output.v1"
        or safety.get("decision") != "SAFE"
        or tuple(safety.get("prohibited_flags", ())) != ()
        or _confidence(safety.get("confidence")) < 0.90
    ):
        raise ParallelForegroundReleaseError(
            "contract cross-event or policy binding is not authorizing"
        )
    source_event_seq = max(
        int(event["event_seq"])
        for event in (candidate, fast, router, route, safety)
    )
    if token.source_event_seq != source_event_seq:
        raise ParallelForegroundReleaseError(
            "expected token source_event_seq is stale"
        )
    if token.candidate_audio_shadow_verification_event_id is not None:
        shadow = _event_by_id(
            journal,
            token.candidate_audio_shadow_verification_event_id,
            "shadow verification",
        )
        _validate_shadow_verification_from_token(shadow, token)


def _validate_parallel_gate_bindings(
    *,
    eligibility_facts: CandidateEligibilityFactsV1,
    fast: Mapping[str, Any],
    candidate: Mapping[str, Any],
    router: Mapping[str, Any],
    route: Mapping[str, Any],
    safety: Mapping[str, Any],
) -> None:
    expected_names = (
        (fast, "FAST_INTERACTION_OUTPUT_EMITTED"),
        (candidate, "FOREGROUND_REPLY_CANDIDATE_EMITTED"),
        (router, "ROUTER_DECISION_EMITTED"),
        (route, "ROUTE_EVIDENCE_OUTPUT_EMITTED"),
        (safety, "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED"),
    )
    for event, expected_name in expected_names:
        if event.get("event_name") != expected_name:
            raise ParallelForegroundReleaseError(
                "parallel Gate predecessor event type is invalid"
            )
    if (
        fast.get("fast_interaction_topology") != _PARALLEL_TOPOLOGY
        or candidate.get("fast_interaction_topology") != _PARALLEL_TOPOLOGY
    ):
        raise ParallelForegroundReleaseError(
            "parallel Gate requires speculative_candidate_parallel_route"
        )
    if (
        fast.get("adapter_id")
        != _EXPECTED_ADAPTER_IDS["fast_interaction"]
        or fast.get("qwen_candidate_adapter_id")
        != _EXPECTED_ADAPTER_IDS["duplex_model"]
        or route.get("adapter_id") != _EXPECTED_ADAPTER_IDS["route_evidence"]
        or safety.get("adapter_id") != _EXPECTED_ADAPTER_IDS["route_evidence"]
    ):
        raise ParallelForegroundReleaseError(
            "parallel Gate adapter identity is invalid"
        )
    if (
        fast.get("output_mode") != "mock"
        or route.get("output_mode") != "mock"
        or safety.get("output_mode") != "mock"
        or fast.get("normalization_status") != "normalized"
        or route.get("normalization_status") != "normalized"
        or safety.get("normalization_status") != "normalized"
        or route.get("schema_name")
        != "voice_agent.route_evidence.output.v1"
        or safety.get("schema_name")
        != "voice_agent.candidate_safety.output.v1"
    ):
        raise ParallelForegroundReleaseError(
            "parallel predecessor normalization binding is invalid"
        )
    facts = eligibility_facts
    event_fact_fields = (
        "provider_session_generation",
        "context_snapshot_id",
        "turn_id",
        "utterance_id",
        "qwen_response_id",
        "qwen_output_item_id",
        "qwen_output_index",
        "qwen_content_index",
        "candidate_id",
        "candidate_transcript_digest",
        "candidate_pcm_manifest_digest",
        "candidate_audio_format_ref",
        "candidate_audio_duration_ms",
    )
    for field_name in event_fact_fields:
        if candidate.get(field_name) != getattr(facts, field_name):
            raise ParallelForegroundReleaseError(
                "candidate event does not match eligibility facts"
            )
    for event in (fast, route, safety):
        if (
            event.get("provider_session_generation")
            != facts.provider_session_generation
            or event.get("context_snapshot_id") != facts.context_snapshot_id
            or event.get("turn_id") != facts.turn_id
            or event.get("utterance_id") != facts.utterance_id
        ):
            raise ParallelForegroundReleaseError(
                "parallel predecessor correlation is inconsistent"
            )
    if (
        router.get("turn_id") != facts.turn_id
        or router.get("utterance_id") != facts.utterance_id
    ):
        raise ParallelForegroundReleaseError(
            "parallel predecessor identity binding is inconsistent"
        )
    if (
        safety.get("qwen_response_id") != facts.qwen_response_id
        or safety.get("candidate_transcript_digest")
        != facts.candidate_transcript_digest
        or candidate.get("fast_interaction_output_event_id")
        != fast.get("event_id")
        or candidate.get("caused_by_event_id") != fast.get("event_id")
        or fast.get("route_evidence_event_id") != route.get("event_id")
        or fast.get("candidate_safety_evidence_event_id")
        != safety.get("event_id")
        or candidate.get("route_evidence_event_id") != route.get("event_id")
        or candidate.get("candidate_safety_evidence_event_id")
        != safety.get("event_id")
        or router.get("route_evidence_event_id") != route.get("event_id")
        or router.get("router_decision") != route.get("route_hint")
        or router.get("task_focus") != route.get("task_focus_hint")
        or fast.get("route_evidence_adapter_request_id")
        != route.get("adapter_request_id")
        or fast.get("candidate_safety_adapter_request_id")
        != safety.get("adapter_request_id")
        or fast.get("foreground_act") != route.get("foreground_act_hint")
        or fast.get("risk_class") != route.get("risk_class")
        or tuple(fast.get("risk_tags", ())) != tuple(route.get("risk_tags", ()))
        or _confidence(fast.get("confidence"))
        != min(
            _confidence(route.get("confidence")),
            _confidence(safety.get("confidence")),
        )
    ):
        raise ParallelForegroundReleaseError(
            "parallel predecessor identity binding is inconsistent"
        )
    source_event_ids = fast.get("source_event_ids")
    if not isinstance(source_event_ids, (tuple, list)) or not {
        str(route["event_id"]),
        str(safety["event_id"]),
    }.issubset({str(event_id) for event_id in source_event_ids}):
        raise ParallelForegroundReleaseError(
            "parallel predecessor evidence binding is inconsistent"
        )
    candidate_source_event_ids = candidate.get("source_event_ids")
    required_candidate_sources = {
        *{str(event_id) for event_id in source_event_ids},
        str(fast["event_id"]),
    }
    if (
        not isinstance(candidate_source_event_ids, (tuple, list))
        or not required_candidate_sources.issubset(
            {str(event_id) for event_id in candidate_source_event_ids}
        )
        or tuple(candidate.get("risk_tags", ()))
        != tuple(fast.get("risk_tags", ()))
        or _confidence(candidate.get("confidence"))
        != _confidence(fast.get("confidence"))
    ):
        raise ParallelForegroundReleaseError(
            "candidate evidence binding is inconsistent"
        )
    prohibited_flags = safety.get("prohibited_flags")
    semantic_categories = safety.get("semantic_categories")
    if (
        not isinstance(prohibited_flags, (tuple, list))
        or not isinstance(semantic_categories, (tuple, list))
        or any(not isinstance(value, str) for value in prohibited_flags)
        or any(not isinstance(value, str) for value in semantic_categories)
    ):
        raise ParallelForegroundReleaseError(
            "candidate safety evidence binding is invalid"
        )


def _validate_runtime_context_bindings(
    *,
    context: ParallelForegroundGateContextV1,
    fast: Mapping[str, Any],
    candidate: Mapping[str, Any],
    router: Mapping[str, Any],
    route: Mapping[str, Any],
    safety: Mapping[str, Any],
) -> None:
    if (
        context.assembly_stage != "slice3b1_mock"
        or context.output_mode != "mock"
        or context.native_pcm_enabled is not False
        or context.native_pcm_capability_check != "FAIL"
    ):
        raise ParallelForegroundReleaseError(
            "Slice 3B.1 context authority claims are invalid"
        )
    if (
        router.get("turn_id") != context.turn_id
        or router.get("utterance_id") != context.utterance_id
    ):
        raise ParallelForegroundReleaseError(
            "parallel Gate Router binding is stale or inconsistent"
        )
    expected = {
        "session_id": candidate.get("session_id"),
        "provider_session_generation": candidate.get(
            "provider_session_generation"
        ),
        "context_snapshot_id": candidate.get("context_snapshot_id"),
        "turn_id": candidate.get("turn_id"),
        "utterance_id": candidate.get("utterance_id"),
        "qwen_response_id": candidate.get("qwen_response_id"),
        "qwen_output_item_id": candidate.get("qwen_output_item_id"),
        "qwen_output_index": candidate.get("qwen_output_index"),
        "qwen_content_index": candidate.get("qwen_content_index"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_transcript_digest": candidate.get(
            "candidate_transcript_digest"
        ),
        "candidate_pcm_manifest_digest": candidate.get(
            "candidate_pcm_manifest_digest"
        ),
        "candidate_audio_format_ref": candidate.get(
            "candidate_audio_format_ref"
        ),
        "candidate_audio_duration_ms": candidate.get(
            "candidate_audio_duration_ms"
        ),
        "router_decision_event_id": router.get("event_id"),
        "route_evidence_event_id": route.get("event_id"),
        "candidate_safety_evidence_event_id": safety.get("event_id"),
        "router_decision": router.get("router_decision"),
        "task_focus": router.get("task_focus"),
        "foreground_act": fast.get("foreground_act"),
        "risk_class": route.get("risk_class"),
        "candidate_safety_decision": safety.get("decision"),
    }
    if any(getattr(context, name) != value for name, value in expected.items()):
        raise ParallelForegroundReleaseError(
            "parallel Gate context binding is stale or inconsistent"
        )
    source_event_seq = max(
        int(event["event_seq"])
        for event in (fast, candidate, router, route, safety)
    )
    if context.source_event_seq != source_event_seq:
        raise ParallelForegroundReleaseError(
            "parallel Gate context source_event_seq is stale"
        )


def _parallel_failure_reason(
    context: ParallelForegroundGateContextV1,
) -> str:
    checks = (
        (context.provider_context_state != "CLEAN", "provider_context_not_clean"),
        (
            context.interaction_state not in _GATE_READY_INTERACTION_STATES,
            "interaction_state_not_gate_ready",
        ),
        (context.router_decision != "FAST_ONLY", "route_not_fast_only"),
        (context.task_focus != "FOREGROUND_CHAT", "task_focus_not_foreground_chat"),
        (context.foreground_act != "ANSWER", "foreground_act_not_answer"),
        (context.risk_class != "LOW", "risk_not_low"),
        (context.candidate_length_check != "PASS", "candidate_length_failed"),
        (context.candidate_duration_check != "PASS", "candidate_duration_failed"),
        (context.candidate_terminal_check != "PASS", "candidate_terminal_failed"),
        (context.generation_check != "PASS", "generation_check_failed"),
        (
            context.context_snapshot_check != "PASS",
            "context_snapshot_check_failed",
        ),
        (context.route_evidence_check != "PASS", "route_evidence_check_failed"),
        (
            context.candidate_safety_check != "PASS",
            "candidate_safety_check_failed",
        ),
        (
            context.transcript_digest_check != "PASS",
            "transcript_digest_check_failed",
        ),
        (context.pcm_manifest_check != "PASS", "pcm_manifest_check_failed"),
        (context.correlation_check != "PASS", "correlation_check_failed"),
        (
            context.native_pcm_enabled is not True
            or context.native_pcm_capability_check != "PASS",
            "native_pcm_disabled",
        ),
    )
    for failed, reason in checks:
        if failed:
            return reason
    raise ParallelForegroundReleaseError(
        "Slice 3B.1 must not produce an enabled native PCM context"
    )


def _parallel_gate_event_fields(
    context: ParallelForegroundGateContextV1,
) -> dict[str, Any]:
    return {
        "candidate_check_policy_version": (
            context.candidate_check_policy_version
        ),
        "candidate_length_check": context.candidate_length_check,
        "candidate_duration_check": context.candidate_duration_check,
        "candidate_terminal_check": context.candidate_terminal_check,
        "native_pcm_capability_check": context.native_pcm_capability_check,
        "generation_check": context.generation_check,
        "context_snapshot_check": context.context_snapshot_check,
        "route_evidence_check": context.route_evidence_check,
        "candidate_safety_check": context.candidate_safety_check,
        "transcript_digest_check": context.transcript_digest_check,
        "pcm_manifest_check": context.pcm_manifest_check,
        "correlation_check": context.correlation_check,
        "provider_session_generation": context.provider_session_generation,
        "context_snapshot_id": context.context_snapshot_id,
        "route_evidence_event_id": context.route_evidence_event_id,
        "candidate_safety_evidence_event_id": (
            context.candidate_safety_evidence_event_id
        ),
    }


def _event_by_id(
    journal: InMemoryEventJournal,
    event_id: str,
    label: str,
) -> dict[str, Any]:
    _require_safe_token(event_id, f"{label}_event_id")
    matches = [
        event
        for event in journal.events()
        if event.get("event_id") == event_id
    ]
    if len(matches) != 1:
        raise ParallelForegroundReleaseError(
            f"{label} must resolve to one canonical journal event"
        )
    return matches[0]


def _validate_shadow_verification(
    shadow: Mapping[str, Any],
    facts: CandidateEligibilityFactsV1,
) -> None:
    if (
        shadow.get("event_name")
        != "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED"
        or shadow.get("turn_id") != facts.turn_id
        or shadow.get("utterance_id") != facts.utterance_id
        or shadow.get("qwen_response_id") != facts.qwen_response_id
        or shadow.get("candidate_transcript_digest")
        != facts.candidate_transcript_digest
        or shadow.get("candidate_pcm_manifest_digest")
        != facts.candidate_pcm_manifest_digest
        or shadow.get("audio_format_ref") != facts.candidate_audio_format_ref
        or shadow.get("decoded_duration_ms")
        != facts.candidate_audio_duration_ms
        or shadow.get("equivalence") != "MATCH"
        or shadow.get("output_mode") != "mock"
    ):
        raise ParallelForegroundReleaseError(
            "shadow verification does not match candidate facts"
        )


def _validate_shadow_verification_from_token(
    shadow: Mapping[str, Any],
    token: ForegroundReleaseTokenV1,
) -> None:
    if (
        shadow.get("event_name")
        != "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED"
        or shadow.get("turn_id") != token.turn_id
        or shadow.get("utterance_id") != token.utterance_id
        or shadow.get("qwen_response_id") != token.qwen_response_id
        or shadow.get("candidate_transcript_digest")
        != token.candidate_transcript_digest
        or shadow.get("candidate_pcm_manifest_digest")
        != token.candidate_pcm_manifest_digest
        or shadow.get("audio_format_ref") != token.candidate_audio_format_ref
        or shadow.get("decoded_duration_ms")
        != token.candidate_audio_duration_ms
        or shadow.get("equivalence") != "MATCH"
        or shadow.get("output_mode") != "mock"
    ):
        raise ParallelForegroundReleaseError(
            "shadow verification does not match release token"
        )


def _release_pcm_handle(pcm_handle: object) -> None:
    release = getattr(pcm_handle, "release", None)
    if callable(release):
        release()


def _require_recorded_event(
    journal: InMemoryEventJournal,
    event: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        raise ParallelForegroundReleaseError(f"{label} must be a mapping")
    event_id = event.get("event_id")
    matches = [
        candidate
        for candidate in journal.events()
        if candidate.get("event_id") == event_id
    ]
    if len(matches) != 1 or matches[0] != dict(event):
        raise ParallelForegroundReleaseError(
            f"{label} must match canonical journal payload"
        )
    return matches[0]


def _validated_event_ids(
    journal: InMemoryEventJournal,
    event_ids: Mapping[str, str],
    *,
    required: tuple[str, ...],
) -> dict[str, str]:
    if not isinstance(event_ids, Mapping):
        raise ParallelForegroundReleaseError("event_ids must be a mapping")
    normalized: dict[str, str] = {}
    for name in required:
        value = _require_safe_token(event_ids.get(name), name)
        if journal.has_event_id(value):
            raise ParallelForegroundReleaseError(
                "parallel Gate event_id is already recorded"
            )
        normalized[name] = value
    if len(set(normalized.values())) != len(normalized):
        raise ParallelForegroundReleaseError(
            "parallel Gate event IDs must be distinct"
        )
    return normalized


def _confidence(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ParallelForegroundReleaseError("confidence must be in [0, 1]")
    return float(value)


def _require_safe_token(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN.fullmatch(value) is None:
        raise ParallelForegroundReleaseError(f"{field_name} is invalid")
    return value


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_DIGEST.fullmatch(value) is None:
        raise ParallelForegroundReleaseError(f"{field_name} is invalid")
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ParallelForegroundReleaseError(f"{field_name} must be positive")
    return value


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ParallelForegroundReleaseError(
            f"{field_name} must be nonnegative"
        )
    return value


__all__ = [
    "ForegroundReleaseTokenV1",
    "InMemoryPlaybackOutbox",
    "ParallelForegroundGateContextV1",
    "ParallelForegroundGateResult",
    "ParallelForegroundReleaseError",
    "PlaybackOutboxItemV1",
    "build_slice3b1_gate_context",
    "run_parallel_fast_foreground_gate",
]
