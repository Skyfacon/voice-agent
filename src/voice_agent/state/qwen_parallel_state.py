from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from voice_agent.events.registry import ADR018_EVENT_NAMES
from voice_agent.privacy.redaction import is_safe_release_token_ref


_PARALLEL_TOPOLOGY = "speculative_candidate_parallel_route"
_PARALLEL_EVENT_NAMES = frozenset(
    {
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_COMMITTED",
        "FOREGROUND_OUTPUT_DISCARDED",
    }
)
_FENCE_EVENT_NAMES = frozenset(
    {"INTERRUPT_CANDIDATE", "TTS_TRUNCATE_REQUESTED"}
)
_PROVIDER_CONTEXT_STATES = frozenset(
    {"CLEAN", "CLEANUP_PENDING", "TAINTED", "REBUILDING", "CLOSED"}
)
_LEGAL_PROVIDER_TRANSITIONS = {
    "CLOSED": frozenset({"REBUILDING"}),
    "REBUILDING": frozenset({"CLEAN", "TAINTED", "CLOSED"}),
    "CLEAN": frozenset(
        {"CLEANUP_PENDING", "TAINTED", "REBUILDING", "CLOSED"}
    ),
    "CLEANUP_PENDING": frozenset(
        {"CLEAN", "TAINTED", "REBUILDING", "CLOSED"}
    ),
    "TAINTED": frozenset({"REBUILDING", "CLOSED"}),
}
_PROJECTION_ROLES = frozenset(
    {"route_evidence", "candidate_safety", "fast_candidate", "composer"}
)
_CANDIDATE_SAFETY_DECISIONS = frozenset(
    {"SAFE", "UNSAFE", "UNCERTAIN"}
)
_HANDOFF_DISPOSITIONS = frozenset(
    {
        "QUEUED",
        "COALESCED",
        "SELECTED",
        "STALE",
        "EXPIRED",
        "CANCELLED",
        "DISCARDED",
    }
)
_TERMINAL_HANDOFF_DISPOSITIONS = _HANDOFF_DISPOSITIONS - {"QUEUED"}
_HANDOFF_KINDS = frozenset(
    {
        "PROGRESS",
        "CLARIFICATION",
        "CONFIRMATION",
        "FINAL",
        "DEGRADED",
        "FAILED",
    }
)
_HANDOFF_EXPIRY_STATUSES = frozenset({"CURRENT", "EXPIRED"})
_HANDOFF_SOURCE_TYPE_BY_KIND = {
    "PROGRESS": "progress",
    "CLARIFICATION": "clarification",
    "CONFIRMATION": "confirmation",
    "FINAL": "final",
    "DEGRADED": "final",
    "FAILED": "final",
}
_DELIVERY_DISPOSITIONS = frozenset({"FULL", "TRUNCATED", "NOT_STARTED"})
_ARBITRATION_SOURCE_TYPES = frozenset(
    {
        "user_fast",
        "confirmation",
        "clarification",
        "progress",
        "final",
        "none",
    }
)
_SAFE_TOKEN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/~-]{0,255}\Z")
_SAFE_REF = re.compile(
    r"\A[a-z][a-z0-9-]{0,47}://[A-Za-z0-9._~:/-]{1,384}\Z"
)
_SAFE_DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_MAX_SAFE_REF_CHARS = 435
_MAX_TRACKED_ITEMS = 512
_MAX_TRACKED_EVENT_IDS = 4_096
_MAX_COUNTER = 2_147_483_647


class QwenParallelStateError(ValueError):
    """A deterministic ADR-018 reducer contract violation."""


@dataclass(frozen=True, slots=True)
class CandidateReplayIdentityV1:
    provider_session_generation: int
    context_snapshot_id: str
    qwen_response_id: str
    qwen_output_item_id: str
    qwen_output_index: int
    qwen_content_index: int
    candidate_transcript_digest: str
    candidate_pcm_manifest_digest: str


@dataclass(frozen=True, slots=True)
class _ProjectionBinding:
    target_role: str
    context_snapshot_id: str
    provider_session_generation: int
    source_event_seq: int
    active_task_ref: str | None
    plan_version: int | None
    task_event_seq: int | None
    pending_confirmation_ref: str | None
    playback_epoch: int
    interaction_state_version: int


@dataclass(frozen=True, slots=True)
class _ContextSnapshotBinding:
    provider_session_generation: int
    source_event_seq: int
    interaction_state_version: int
    task_focus_state_version: int | None
    active_task_ref: str | None
    active_task_state: str | None
    plan_version: int | None
    task_event_seq: int | None
    pending_confirmation_ref: str | None
    last_assistant_act: str | None
    recent_dialogue_refs: tuple[str, ...] | None
    session_summary_ref: str | None
    persona_profile_id: str | None
    policy_versions: object | None
    redaction_status: str | None


@dataclass(frozen=True, slots=True)
class _RouteEvidenceBinding:
    adapter_request_id: str
    turn_id: str
    final_asr_event_id: str
    context_snapshot_id: str
    provider_session_generation: int
    playback_epoch: int
    interaction_state_version: int


@dataclass(frozen=True, slots=True)
class _CandidateSafetyBinding:
    adapter_request_id: str
    context_snapshot_id: str
    provider_session_generation: int
    qwen_response_id: str
    candidate_transcript_digest: str
    decision: str
    playback_epoch: int
    interaction_state_version: int


@dataclass(frozen=True, slots=True)
class _ParallelFastBinding:
    context_snapshot_id: str
    provider_session_generation: int
    route_evidence_event_id: str
    candidate_safety_evidence_event_id: str
    playback_epoch: int
    interaction_state_version: int


@dataclass(frozen=True, slots=True)
class _GateBinding:
    candidate_id: str
    candidate_event_id: str
    passed: bool
    release_token_ref: str | None
    provider_session_generation: int
    context_snapshot_id: str
    route_evidence_event_id: str
    candidate_safety_evidence_event_id: str
    candidate_playback_epoch: int
    candidate_interaction_state_version: int
    observed_provider_session_generation: int
    observed_provider_context_state: str
    observed_playback_epoch: int
    observed_interaction_state_version: int


@dataclass(frozen=True, slots=True)
class _TerminalOutputBinding:
    candidate_id: str
    gate_event_id: str
    disposition: str


@dataclass(frozen=True, slots=True)
class _HandoffBinding:
    event_id: str
    emission_ordinal: int
    kind: str
    expiry_status: str
    task_id: str
    plan_version: int
    task_event_seq: int


@dataclass(frozen=True, slots=True)
class _ArbitrationBinding:
    selected_source_type: str
    selected_source_event_id: str | None
    superseded_source_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SelectedHandoffBinding:
    arbitration_event_id: str
    disposition_event_id: str


@dataclass(frozen=True, slots=True)
class _CoalescedHandoffBinding:
    replacement_handoff_id: str
    disposition_event_id: str


@dataclass
class QwenParallelState:
    provider_session_generation: int | None = None
    provider_context_state: str = "CLOSED"
    playback_epoch: int = 0
    interaction_state_version: int = 0
    dropped_audio_frame_count: int = 0
    context_projection_event_ids: tuple[str, ...] = ()
    route_evidence_event_ids: tuple[str, ...] = ()
    candidate_safety_event_ids: tuple[str, ...] = ()
    shadow_verification_event_ids: tuple[str, ...] = ()
    response_arbitration_event_ids: tuple[str, ...] = ()
    handoff_dispositions: dict[str, str] = field(default_factory=dict)
    candidate_identities: dict[str, CandidateReplayIdentityV1] = field(
        default_factory=dict
    )
    candidate_dispositions: dict[str, str] = field(default_factory=dict)
    assistant_delivery_dispositions: dict[str, str] = field(
        default_factory=dict
    )
    saw_adr018_event: bool = False
    _seen_owned_event_ids: set[str] = field(
        default_factory=set, init=False, repr=False
    )
    _projection_by_event_id: dict[str, _ProjectionBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _projection_id_to_event_id: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _context_snapshot_by_id: dict[str, _ContextSnapshotBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _route_evidence_by_event_id: dict[str, _RouteEvidenceBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _route_terminal_by_turn: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _route_terminal_by_final_asr: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _route_terminal_by_request: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_safety_by_event_id: dict[str, _CandidateSafetyBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_safety_terminal_by_response: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_safety_terminal_by_request: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _parallel_fast_by_event_id: dict[str, _ParallelFastBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_event_to_id: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_response_to_id: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_fast_output_to_id: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_fence_by_id: dict[str, tuple[int, int]] = field(
        default_factory=dict, init=False, repr=False
    )
    _gate_by_event_id: dict[str, _GateBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _candidate_gate_event_id: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _terminal_output_by_event_id: dict[str, _TerminalOutputBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _retired_user_fast_authority_event_ids: set[str] = field(
        default_factory=set, init=False, repr=False
    )
    _shadow_response_ids: set[str] = field(
        default_factory=set, init=False, repr=False
    )
    _handoff_by_id: dict[str, _HandoffBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _arbitration_by_event_id: dict[str, _ArbitrationBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _arbitration_id_to_event_id: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _selected_handoff_by_id: dict[str, _SelectedHandoffBinding] = field(
        default_factory=dict, init=False, repr=False
    )
    _coalesced_handoff_by_id: dict[
        str, _CoalescedHandoffBinding
    ] = field(default_factory=dict, init=False, repr=False)
    _pending_interrupt_fence: tuple[str, int, int] | None = field(
        default=None, init=False, repr=False
    )
    _source_event_seq_lower_bound: int = field(
        default=0, init=False, repr=False
    )

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        event_name_value = event.get("event_name")
        if not isinstance(event_name_value, str):
            return False
        event_name = event_name_value
        if not self._owns_event(event_name, event):
            return False

        event_id = _require_safe_token(event.get("event_id"), "event_id")
        if event_id in self._seen_owned_event_ids:
            raise QwenParallelStateError("duplicate event_id")
        _require_capacity(
            len(self._seen_owned_event_ids),
            "owned event",
            limit=_MAX_TRACKED_EVENT_IDS,
        )

        handlers = {
            "PROVIDER_CONTEXT_STATE_CHANGED": self._reduce_provider_context,
            "MODEL_CONTEXT_PROJECTION_EMITTED": self._reduce_projection,
            "ROUTE_EVIDENCE_OUTPUT_EMITTED": self._reduce_route_evidence,
            "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": (
                self._reduce_candidate_safety
            ),
            "FAST_INTERACTION_OUTPUT_EMITTED": self._reduce_parallel_fast,
            "FOREGROUND_REPLY_CANDIDATE_EMITTED": self._reduce_candidate,
            "FOREGROUND_ACT_GATE_PASSED": self._reduce_gate,
            "FOREGROUND_ACT_GATE_FAILED": self._reduce_gate,
            "FOREGROUND_OUTPUT_COMMITTED": self._reduce_commit,
            "FOREGROUND_OUTPUT_DISCARDED": self._reduce_discard,
            "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": (
                self._reduce_shadow_verification
            ),
            "SLOW_TO_FAST_HANDOFF_EMITTED": self._reduce_handoff_emitted,
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED": (
                self._reduce_handoff_disposition
            ),
            "RESPONSE_ARBITRATION_DECIDED": self._reduce_arbitration,
            "ASSISTANT_DELIVERY_DISPOSITIONED": self._reduce_delivery,
            "INTERRUPT_CANDIDATE": self._reduce_interrupt,
            "TTS_TRUNCATE_REQUESTED": self._reduce_truncate,
        }
        handler = handlers.get(event_name)
        if handler is None:
            raise QwenParallelStateError(
                f"missing reducer for owned event {event_name}"
            )
        handler(event, event_id)
        self._seen_owned_event_ids.add(event_id)
        if event_name in ADR018_EVENT_NAMES:
            self.saw_adr018_event = True
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        authority_state = {
            "seen_owned_event_ids": tuple(sorted(self._seen_owned_event_ids)),
            "projection_by_event_id": {
                key: asdict(self._projection_by_event_id[key])
                for key in sorted(self._projection_by_event_id)
            },
            "projection_id_to_event_id": {
                key: self._projection_id_to_event_id[key]
                for key in sorted(self._projection_id_to_event_id)
            },
            "context_snapshot_by_id": {
                key: asdict(self._context_snapshot_by_id[key])
                for key in sorted(self._context_snapshot_by_id)
            },
            "route_evidence_by_event_id": {
                key: asdict(self._route_evidence_by_event_id[key])
                for key in sorted(self._route_evidence_by_event_id)
            },
            "route_terminal_by_turn": {
                key: self._route_terminal_by_turn[key]
                for key in sorted(self._route_terminal_by_turn)
            },
            "route_terminal_by_final_asr": {
                key: self._route_terminal_by_final_asr[key]
                for key in sorted(self._route_terminal_by_final_asr)
            },
            "route_terminal_by_request": {
                key: self._route_terminal_by_request[key]
                for key in sorted(self._route_terminal_by_request)
            },
            "candidate_safety_by_event_id": {
                key: asdict(self._candidate_safety_by_event_id[key])
                for key in sorted(self._candidate_safety_by_event_id)
            },
            "candidate_safety_terminal_by_response": {
                key: self._candidate_safety_terminal_by_response[key]
                for key in sorted(
                    self._candidate_safety_terminal_by_response
                )
            },
            "candidate_safety_terminal_by_request": {
                key: self._candidate_safety_terminal_by_request[key]
                for key in sorted(
                    self._candidate_safety_terminal_by_request
                )
            },
            "parallel_fast_by_event_id": {
                key: asdict(self._parallel_fast_by_event_id[key])
                for key in sorted(self._parallel_fast_by_event_id)
            },
            "candidate_event_to_id": {
                key: self._candidate_event_to_id[key]
                for key in sorted(self._candidate_event_to_id)
            },
            "candidate_response_to_id": {
                key: self._candidate_response_to_id[key]
                for key in sorted(self._candidate_response_to_id)
            },
            "candidate_fast_output_to_id": {
                key: self._candidate_fast_output_to_id[key]
                for key in sorted(self._candidate_fast_output_to_id)
            },
            "candidate_fence_by_id": {
                key: tuple(self._candidate_fence_by_id[key])
                for key in sorted(self._candidate_fence_by_id)
            },
            "gate_by_event_id": {
                key: _gate_binding_digest(self._gate_by_event_id[key])
                for key in sorted(self._gate_by_event_id)
            },
            "candidate_gate_event_id": {
                key: self._candidate_gate_event_id[key]
                for key in sorted(self._candidate_gate_event_id)
            },
            "terminal_output_by_event_id": {
                key: asdict(self._terminal_output_by_event_id[key])
                for key in sorted(self._terminal_output_by_event_id)
            },
            "retired_user_fast_authority_event_ids": tuple(
                sorted(self._retired_user_fast_authority_event_ids)
            ),
            "shadow_response_ids": tuple(sorted(self._shadow_response_ids)),
            "handoff_by_id": {
                key: asdict(self._handoff_by_id[key])
                for key in sorted(self._handoff_by_id)
            },
            "arbitration_by_event_id": {
                key: asdict(self._arbitration_by_event_id[key])
                for key in sorted(self._arbitration_by_event_id)
            },
            "arbitration_id_to_event_id": {
                key: self._arbitration_id_to_event_id[key]
                for key in sorted(self._arbitration_id_to_event_id)
            },
            "selected_handoff_by_id": {
                key: asdict(self._selected_handoff_by_id[key])
                for key in sorted(self._selected_handoff_by_id)
            },
            "coalesced_handoff_by_id": {
                key: asdict(self._coalesced_handoff_by_id[key])
                for key in sorted(self._coalesced_handoff_by_id)
            },
            "pending_interrupt_fence": (
                tuple(self._pending_interrupt_fence)
                if self._pending_interrupt_fence is not None
                else None
            ),
            "source_event_seq_lower_bound": (
                self._source_event_seq_lower_bound
            ),
        }
        return {
            "saw_adr018_event": self.saw_adr018_event,
            "provider_session_generation": self.provider_session_generation,
            "provider_context_state": self.provider_context_state,
            "playback_epoch": self.playback_epoch,
            "interaction_state_version": self.interaction_state_version,
            "dropped_audio_frame_count": self.dropped_audio_frame_count,
            "context_projection_event_ids": tuple(
                self.context_projection_event_ids
            ),
            "route_evidence_event_ids": tuple(self.route_evidence_event_ids),
            "candidate_safety_event_ids": tuple(
                self.candidate_safety_event_ids
            ),
            "shadow_verification_event_ids": tuple(
                self.shadow_verification_event_ids
            ),
            "response_arbitration_event_ids": tuple(
                self.response_arbitration_event_ids
            ),
            "handoff_dispositions": {
                key: self.handoff_dispositions[key]
                for key in sorted(self.handoff_dispositions)
            },
            "candidate_identities": {
                key: asdict(self.candidate_identities[key])
                for key in sorted(self.candidate_identities)
            },
            "candidate_dispositions": {
                key: self.candidate_dispositions[key]
                for key in sorted(self.candidate_dispositions)
            },
            "assistant_delivery_dispositions": {
                key: self.assistant_delivery_dispositions[key]
                for key in sorted(self.assistant_delivery_dispositions)
            },
            "authority_state": authority_state,
        }

    def _owns_event(
        self,
        event_name: str,
        event: Mapping[str, Any],
    ) -> bool:
        if event_name in ADR018_EVENT_NAMES:
            return True
        if event_name in _FENCE_EVENT_NAMES:
            return (
                "playback_epoch" in event
                or "interaction_state_version" in event
            )
        if event_name not in _PARALLEL_EVENT_NAMES:
            return False
        if event.get("fast_interaction_topology") == _PARALLEL_TOPOLOGY:
            return True

        candidate_event_id = event.get("candidate_event_id")
        if (
            isinstance(candidate_event_id, str)
            and candidate_event_id in self._candidate_event_to_id
        ):
            return True
        gate_event_id = event.get("gate_event_id")
        return (
            isinstance(gate_event_id, str)
            and gate_event_id in self._gate_by_event_id
        )

    def _reduce_provider_context(
        self,
        event: Mapping[str, Any],
        _event_id: str,
    ) -> None:
        generation = _require_positive_int(
            event.get("provider_session_generation"),
            "provider_session_generation",
        )
        from_state = _require_enum(
            event.get("from_state"),
            "from_state",
            _PROVIDER_CONTEXT_STATES,
        )
        to_state = _require_enum(
            event.get("to_state"),
            "to_state",
            _PROVIDER_CONTEXT_STATES,
        )
        if from_state != self.provider_context_state:
            raise QwenParallelStateError(
                "provider transition from_state does not match reducer state"
            )
        if to_state not in _LEGAL_PROVIDER_TRANSITIONS[from_state]:
            raise QwenParallelStateError("illegal provider transition")

        current_generation = self.provider_session_generation
        if current_generation is None:
            if (
                generation != 1
                or from_state != "CLOSED"
                or to_state != "REBUILDING"
            ):
                raise QwenParallelStateError(
                    "initial provider generation must be generation 1 rebuild"
                )
        else:
            if generation < current_generation:
                raise QwenParallelStateError(
                    "provider generation must be non-decreasing"
                )
            if generation > current_generation and to_state != "REBUILDING":
                raise QwenParallelStateError(
                    "provider generation may advance only on rebuild"
                )
            if to_state == "REBUILDING" and generation <= current_generation:
                raise QwenParallelStateError(
                    "later provider rebuild requires a newer generation"
                )
            if to_state != "REBUILDING" and generation != current_generation:
                raise QwenParallelStateError(
                    "ordinary provider transition must preserve generation"
                )

        has_epoch = "playback_epoch" in event
        has_version = "interaction_state_version" in event
        if has_epoch != has_version:
            raise QwenParallelStateError(
                "provider rebuild fence requires epoch and state version"
            )
        new_epoch = self.playback_epoch
        new_version = self.interaction_state_version
        new_source_event_seq_lower_bound = (
            self._source_event_seq_lower_bound
        )
        if to_state == "REBUILDING":
            if not has_epoch:
                raise QwenParallelStateError(
                    "provider rebuild fence is missing"
                )
            new_epoch = _require_nonnegative_int(
                event.get("playback_epoch"),
                "playback_epoch",
            )
            new_version = _require_nonnegative_int(
                event.get("interaction_state_version"),
                "interaction_state_version",
            )
            if current_generation is not None and (
                new_epoch <= self.playback_epoch
                or new_version <= self.interaction_state_version
            ):
                raise QwenParallelStateError(
                    "later provider rebuild fence must strictly advance"
                )
            if "event_seq" in event:
                fence_event_seq = _require_positive_int(
                    event.get("event_seq"),
                    "event_seq",
                )
                if fence_event_seq <= self._source_event_seq_lower_bound:
                    raise QwenParallelStateError(
                        "provider rebuild source prefix fence must advance"
                    )
                new_source_event_seq_lower_bound = fence_event_seq
        elif has_epoch:
            event_epoch = _require_nonnegative_int(
                event.get("playback_epoch"),
                "playback_epoch",
            )
            event_version = _require_nonnegative_int(
                event.get("interaction_state_version"),
                "interaction_state_version",
            )
            if (
                event_epoch != self.playback_epoch
                or event_version != self.interaction_state_version
            ):
                raise QwenParallelStateError(
                    "ordinary provider transition changed the fence"
                )

        dropped_count = self.dropped_audio_frame_count
        if "dropped_audio_frame_count" in event:
            dropped_count = _require_nonnegative_int(
                event.get("dropped_audio_frame_count"),
                "dropped_audio_frame_count",
            )
            if dropped_count < self.dropped_audio_frame_count:
                raise QwenParallelStateError(
                    "dropped_audio_frame_count must be non-decreasing"
                )

        self.provider_session_generation = generation
        self.provider_context_state = to_state
        self.playback_epoch = new_epoch
        self.interaction_state_version = new_version
        self.dropped_audio_frame_count = dropped_count
        self._source_event_seq_lower_bound = (
            new_source_event_seq_lower_bound
        )

    def _reduce_projection(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        generation = self._require_current_clean_generation(event)
        projection_id = _require_safe_token(
            event.get("projection_id"),
            "projection_id",
        )
        target_role = _require_enum(
            event.get("target_role"),
            "target_role",
            _PROJECTION_ROLES,
        )
        snapshot_id = _require_safe_token(
            event.get("context_snapshot_id"),
            "context_snapshot_id",
        )
        source_event_seq = _require_positive_int(
            event.get("source_event_seq"),
            "source_event_seq",
        )
        if source_event_seq < self._source_event_seq_lower_bound:
            raise QwenParallelStateError(
                "projection source event prefix predates current authority fence"
            )
        source_event_ids = _validate_optional_id_sequence(
            event.get("source_event_ids")
        )
        snapshot_interaction_state_version = (
            self.interaction_state_version
        )
        if "interaction_state_version" in event:
            declared_interaction_state_version = _require_nonnegative_int(
                event.get("interaction_state_version"),
                "interaction_state_version",
            )
            if (
                declared_interaction_state_version
                != snapshot_interaction_state_version
            ):
                raise QwenParallelStateError(
                    "context snapshot interaction state version mismatch"
                )
        snapshot_binding = _ContextSnapshotBinding(
            provider_session_generation=generation,
            source_event_seq=source_event_seq,
            interaction_state_version=snapshot_interaction_state_version,
            task_focus_state_version=_optional_nonnegative_int(
                event.get("task_focus_state_version"),
                "task_focus_state_version",
            ),
            active_task_ref=_optional_safe_ref(
                event.get("active_task_ref"),
                "active_task_ref",
            ),
            active_task_state=_optional_safe_token(
                event.get("active_task_state"),
                "active_task_state",
            ),
            plan_version=_optional_positive_int(
                event.get("plan_version"),
                "plan_version",
            ),
            task_event_seq=_optional_positive_int(
                event.get("task_event_seq"),
                "task_event_seq",
            ),
            pending_confirmation_ref=_optional_safe_ref(
                event.get("pending_confirmation_ref"),
                "pending_confirmation_ref",
            ),
            last_assistant_act=_optional_safe_token(
                event.get("last_assistant_act"),
                "last_assistant_act",
            ),
            recent_dialogue_refs=_validate_optional_ref_sequence(
                event.get("recent_dialogue_refs"),
                "recent_dialogue_refs",
            ),
            session_summary_ref=_optional_safe_ref(
                event.get("session_summary_ref"),
                "session_summary_ref",
            ),
            persona_profile_id=_optional_safe_token(
                event.get("persona_profile_id"),
                "persona_profile_id",
            ),
            policy_versions=_normalize_optional_policy_versions(
                event.get("policy_versions")
            ),
            redaction_status=_optional_safe_token(
                event.get("redaction_status"),
                "redaction_status",
            ),
        )
        prior_snapshot_binding = self._context_snapshot_by_id.get(
            snapshot_id
        )
        if (
            prior_snapshot_binding is not None
            and prior_snapshot_binding != snapshot_binding
        ):
            raise QwenParallelStateError(
                "context_snapshot_id immutable identity mismatch"
            )
        if target_role == "composer":
            has_selected_handoff_source = False
            for source_event_id in source_event_ids:
                handoff = self._handoff_for_event_id(source_event_id)
                if handoff is None:
                    continue
                handoff_id, binding = handoff
                if (
                    binding.expiry_status != "CURRENT"
                    or self.handoff_dispositions.get(handoff_id) != "SELECTED"
                    or handoff_id not in self._selected_handoff_by_id
                ):
                    raise QwenParallelStateError(
                        "composer projection requires an exact CURRENT and "
                        "SELECTED handoff emission source"
                    )
                selected_binding = self._selected_handoff_by_id[handoff_id]
                arbitration = self._arbitration_by_event_id.get(
                    selected_binding.arbitration_event_id
                )
                if (
                    arbitration is None
                    or arbitration.selected_source_event_id
                    != binding.event_id
                    or arbitration.selected_source_type
                    != _HANDOFF_SOURCE_TYPE_BY_KIND[binding.kind]
                ):
                    raise QwenParallelStateError(
                        "composer projection requires an exact CURRENT and "
                        "SELECTED handoff emission source"
                    )
                if self._authority_ids_are_superseded(
                    (
                        binding.event_id,
                        selected_binding.arbitration_event_id,
                        selected_binding.disposition_event_id,
                    )
                ):
                    raise QwenParallelStateError(
                        "composer handoff selection authority was superseded"
                    )
                has_selected_handoff_source = True
            if not has_selected_handoff_source:
                raise QwenParallelStateError(
                    "composer projection requires an exact CURRENT and "
                    "SELECTED handoff emission source"
                )
        if projection_id in self._projection_id_to_event_id:
            raise QwenParallelStateError("duplicate projection_id")
        _require_capacity(
            len(self.context_projection_event_ids),
            "context projection",
        )
        if prior_snapshot_binding is None:
            _require_capacity(
                len(self._context_snapshot_by_id),
                "context snapshot",
            )

        binding = _ProjectionBinding(
            target_role=target_role,
            context_snapshot_id=snapshot_id,
            provider_session_generation=generation,
            source_event_seq=source_event_seq,
            active_task_ref=snapshot_binding.active_task_ref,
            plan_version=snapshot_binding.plan_version,
            task_event_seq=snapshot_binding.task_event_seq,
            pending_confirmation_ref=(
                snapshot_binding.pending_confirmation_ref
            ),
            playback_epoch=self.playback_epoch,
            interaction_state_version=self.interaction_state_version,
        )
        self._projection_by_event_id[event_id] = binding
        self._projection_id_to_event_id[projection_id] = event_id
        if prior_snapshot_binding is None:
            self._context_snapshot_by_id[snapshot_id] = snapshot_binding
        self.context_projection_event_ids += (event_id,)

    def _reduce_route_evidence(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        projection_event_id = _require_safe_token(
            event.get("context_projection_event_id"),
            "context_projection_event_id",
        )
        projection = self._projection_by_event_id.get(projection_event_id)
        if projection is None or projection.target_role != "route_evidence":
            raise QwenParallelStateError(
                "route evidence requires its route projection"
            )
        self._require_projection_current_fence(projection)
        self._require_binding_current_and_clean(
            projection.provider_session_generation
        )
        request_id = _require_safe_token(
            event.get("adapter_request_id"),
            "adapter_request_id",
        )
        turn_id = _require_safe_token(event.get("turn_id"), "turn_id")
        final_asr_event_id = _require_safe_token(
            event.get("final_asr_event_id"),
            "final_asr_event_id",
        )
        if (
            turn_id in self._route_terminal_by_turn
            or final_asr_event_id in self._route_terminal_by_final_asr
            or request_id in self._route_terminal_by_request
        ):
            raise QwenParallelStateError(
                "route evidence terminal correlation is already bound"
            )
        _require_capacity(
            len(self.route_evidence_event_ids),
            "route evidence",
        )

        self._route_evidence_by_event_id[event_id] = _RouteEvidenceBinding(
            adapter_request_id=request_id,
            turn_id=turn_id,
            final_asr_event_id=final_asr_event_id,
            context_snapshot_id=projection.context_snapshot_id,
            provider_session_generation=projection.provider_session_generation,
            playback_epoch=self.playback_epoch,
            interaction_state_version=self.interaction_state_version,
        )
        self._route_terminal_by_turn[turn_id] = event_id
        self._route_terminal_by_final_asr[final_asr_event_id] = event_id
        self._route_terminal_by_request[request_id] = event_id
        self.route_evidence_event_ids += (event_id,)

    def _reduce_candidate_safety(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        projection_event_id = _require_safe_token(
            event.get("context_projection_event_id"),
            "context_projection_event_id",
        )
        projection = self._projection_by_event_id.get(projection_event_id)
        if projection is None or projection.target_role != "candidate_safety":
            raise QwenParallelStateError(
                "candidate safety requires its safety projection"
            )
        self._require_projection_current_fence(projection)
        self._require_binding_current_and_clean(
            projection.provider_session_generation
        )
        request_id = _require_safe_token(
            event.get("adapter_request_id"),
            "adapter_request_id",
        )
        response_id = _require_safe_token(
            event.get("qwen_response_id"),
            "qwen_response_id",
        )
        transcript_digest = _require_digest(
            event.get("candidate_transcript_digest"),
            "candidate_transcript_digest",
        )
        decision = _require_enum(
            event.get("decision"),
            "decision",
            _CANDIDATE_SAFETY_DECISIONS,
        )
        if (
            response_id in self._candidate_safety_terminal_by_response
            or request_id in self._candidate_safety_terminal_by_request
        ):
            raise QwenParallelStateError(
                "candidate safety terminal correlation is already bound"
            )
        _require_capacity(
            len(self.candidate_safety_event_ids),
            "candidate safety evidence",
        )

        self._candidate_safety_by_event_id[event_id] = (
            _CandidateSafetyBinding(
                adapter_request_id=request_id,
                context_snapshot_id=projection.context_snapshot_id,
                provider_session_generation=(
                    projection.provider_session_generation
                ),
                qwen_response_id=response_id,
                candidate_transcript_digest=transcript_digest,
                decision=decision,
                playback_epoch=self.playback_epoch,
                interaction_state_version=self.interaction_state_version,
            )
        )
        self._candidate_safety_terminal_by_response[response_id] = event_id
        self._candidate_safety_terminal_by_request[request_id] = event_id
        self.candidate_safety_event_ids += (event_id,)

    def _reduce_parallel_fast(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        generation = self._require_current_clean_generation(event)
        snapshot_id = _require_safe_token(
            event.get("context_snapshot_id"),
            "context_snapshot_id",
        )
        route_event_id = _require_safe_token(
            event.get("route_evidence_event_id"),
            "route_evidence_event_id",
        )
        safety_event_id = _require_safe_token(
            event.get("candidate_safety_evidence_event_id"),
            "candidate_safety_evidence_event_id",
        )
        route = self._route_evidence_by_event_id.get(route_event_id)
        safety = self._candidate_safety_by_event_id.get(safety_event_id)
        if route is None:
            raise QwenParallelStateError(
                "parallel fast output requires route evidence"
            )
        if safety is None:
            raise QwenParallelStateError(
                "parallel fast output requires candidate safety evidence"
            )
        if (
            route.provider_session_generation != generation
            or safety.provider_session_generation != generation
        ):
            raise QwenParallelStateError(
                "parallel fast output generation mismatch"
            )
        if (
            route.playback_epoch != self.playback_epoch
            or route.interaction_state_version
            != self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "parallel fast output route evidence fence is stale"
            )
        if (
            safety.playback_epoch != self.playback_epoch
            or safety.interaction_state_version
            != self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "parallel fast output candidate safety evidence fence is stale"
            )
        if (
            route.context_snapshot_id != snapshot_id
            or safety.context_snapshot_id != snapshot_id
        ):
            raise QwenParallelStateError(
                "parallel fast output context snapshot mismatch"
            )
        _require_capacity(
            len(self._parallel_fast_by_event_id),
            "parallel fast output",
        )

        self._parallel_fast_by_event_id[event_id] = _ParallelFastBinding(
            context_snapshot_id=snapshot_id,
            provider_session_generation=generation,
            route_evidence_event_id=route_event_id,
            candidate_safety_evidence_event_id=safety_event_id,
            playback_epoch=self.playback_epoch,
            interaction_state_version=self.interaction_state_version,
        )

    def _reduce_candidate(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        generation = self._require_current_clean_generation(event)
        candidate_id = _require_safe_token(
            event.get("candidate_id"),
            "candidate_id",
        )
        fast_output_event_id = _require_safe_token(
            event.get("fast_interaction_output_event_id"),
            "fast_interaction_output_event_id",
        )
        fast = self._parallel_fast_by_event_id.get(fast_output_event_id)
        if fast is None:
            raise QwenParallelStateError(
                "parallel candidate requires its fast output"
            )
        snapshot_id = _require_safe_token(
            event.get("context_snapshot_id"),
            "context_snapshot_id",
        )
        if generation != fast.provider_session_generation:
            raise QwenParallelStateError(
                "parallel candidate generation mismatch"
            )
        if snapshot_id != fast.context_snapshot_id:
            raise QwenParallelStateError(
                "parallel candidate context snapshot mismatch"
            )
        if (
            fast.playback_epoch != self.playback_epoch
            or fast.interaction_state_version
            != self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "parallel fast output fence is stale"
            )
        safety = self._candidate_safety_by_event_id[
            fast.candidate_safety_evidence_event_id
        ]
        response_id = _require_safe_token(
            event.get("qwen_response_id"),
            "qwen_response_id",
        )
        output_item_id = _require_safe_token(
            event.get("qwen_output_item_id"),
            "qwen_output_item_id",
        )
        output_index = _require_nonnegative_int(
            event.get("qwen_output_index"),
            "qwen_output_index",
        )
        content_index = _require_nonnegative_int(
            event.get("qwen_content_index"),
            "qwen_content_index",
        )
        transcript_digest = _require_digest(
            event.get("candidate_transcript_digest"),
            "candidate_transcript_digest",
        )
        pcm_digest = _require_digest(
            event.get("candidate_pcm_manifest_digest"),
            "candidate_pcm_manifest_digest",
        )
        if response_id != safety.qwen_response_id:
            raise QwenParallelStateError(
                "parallel candidate response correlation mismatch"
            )
        if transcript_digest != safety.candidate_transcript_digest:
            raise QwenParallelStateError(
                "parallel candidate transcript digest mismatch"
            )
        if candidate_id in self.candidate_identities:
            raise QwenParallelStateError("duplicate candidate_id")
        if event_id in self._candidate_event_to_id:
            raise QwenParallelStateError("duplicate candidate event")
        if response_id in self._candidate_response_to_id:
            raise QwenParallelStateError(
                "candidate response identity is already bound"
            )
        if fast_output_event_id in self._candidate_fast_output_to_id:
            raise QwenParallelStateError(
                "parallel fast output already has a candidate"
            )
        _require_capacity(len(self.candidate_identities), "candidate identity")

        identity = CandidateReplayIdentityV1(
            provider_session_generation=generation,
            context_snapshot_id=snapshot_id,
            qwen_response_id=response_id,
            qwen_output_item_id=output_item_id,
            qwen_output_index=output_index,
            qwen_content_index=content_index,
            candidate_transcript_digest=transcript_digest,
            candidate_pcm_manifest_digest=pcm_digest,
        )
        self.candidate_identities[candidate_id] = identity
        self._candidate_event_to_id[event_id] = candidate_id
        self._candidate_response_to_id[response_id] = candidate_id
        self._candidate_fast_output_to_id[fast_output_event_id] = candidate_id
        self._candidate_fence_by_id[candidate_id] = (
            self.playback_epoch,
            self.interaction_state_version,
        )

    def _reduce_gate(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        event_name = str(event["event_name"])
        passed = event_name == "FOREGROUND_ACT_GATE_PASSED"
        generation = _require_positive_int(
            event.get("provider_session_generation"),
            "provider_session_generation",
        )
        candidate_event_id = _require_safe_token(
            event.get("candidate_event_id"),
            "candidate_event_id",
        )
        candidate_id = self._candidate_event_to_id.get(candidate_event_id)
        if candidate_id is None:
            raise QwenParallelStateError(
                "parallel Gate requires its candidate event"
            )
        identity = self.candidate_identities[candidate_id]
        if generation != identity.provider_session_generation:
            raise QwenParallelStateError("parallel Gate generation mismatch")
        snapshot_id = _require_safe_token(
            event.get("context_snapshot_id"),
            "context_snapshot_id",
        )
        if snapshot_id != identity.context_snapshot_id:
            raise QwenParallelStateError(
                "parallel Gate context snapshot mismatch"
            )
        candidate_fence = self._candidate_fence_by_id.get(candidate_id)
        if candidate_fence is None:
            raise QwenParallelStateError(
                "parallel Gate candidate fence is missing"
            )
        if passed:
            self._require_binding_current_and_clean(generation)
            if candidate_fence != (
                self.playback_epoch,
                self.interaction_state_version,
            ):
                raise QwenParallelStateError(
                    "parallel Gate candidate fence is stale"
                )
        fast_output_event_id = _candidate_fast_output_event_id(
            self._candidate_fast_output_to_id,
            candidate_id,
        )
        fast = self._parallel_fast_by_event_id[fast_output_event_id]
        route_event_id = _require_safe_token(
            event.get("route_evidence_event_id"),
            "route_evidence_event_id",
        )
        safety_event_id = _require_safe_token(
            event.get("candidate_safety_evidence_event_id"),
            "candidate_safety_evidence_event_id",
        )
        if route_event_id != fast.route_evidence_event_id:
            raise QwenParallelStateError(
                "parallel Gate route evidence mismatch"
            )
        if safety_event_id != fast.candidate_safety_evidence_event_id:
            raise QwenParallelStateError(
                "parallel Gate candidate safety evidence mismatch"
            )
        if candidate_id in self._candidate_gate_event_id:
            raise QwenParallelStateError(
                "candidate already has a terminal Gate"
            )

        release_token_ref: str | None = None
        if passed:
            release_token_ref = _require_release_token_ref(
                event.get("release_token_ref")
            )
        elif "release_token_ref" in event:
            release_token_ref = _require_release_token_ref(
                event.get("release_token_ref")
            )
        _require_capacity(len(self._gate_by_event_id), "parallel Gate")

        self._gate_by_event_id[event_id] = _GateBinding(
            candidate_id=candidate_id,
            candidate_event_id=candidate_event_id,
            passed=passed,
            release_token_ref=release_token_ref,
            provider_session_generation=generation,
            context_snapshot_id=snapshot_id,
            route_evidence_event_id=route_event_id,
            candidate_safety_evidence_event_id=safety_event_id,
            candidate_playback_epoch=candidate_fence[0],
            candidate_interaction_state_version=candidate_fence[1],
            observed_provider_session_generation=(
                self.provider_session_generation
            ),
            observed_provider_context_state=self.provider_context_state,
            observed_playback_epoch=self.playback_epoch,
            observed_interaction_state_version=(
                self.interaction_state_version
            ),
        )
        self._candidate_gate_event_id[candidate_id] = event_id

    def _reduce_commit(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        gate_event_id = _require_safe_token(
            event.get("gate_event_id"),
            "gate_event_id",
        )
        gate = self._gate_by_event_id.get(gate_event_id)
        if gate is None or not gate.passed:
            raise QwenParallelStateError(
                "parallel commit requires a passed Gate"
            )
        release_token_ref = _require_release_token_ref(
            event.get("release_token_ref")
        )
        if release_token_ref != gate.release_token_ref:
            raise QwenParallelStateError(
                "parallel commit release token ref mismatch"
            )
        identity = self.candidate_identities[gate.candidate_id]
        if (
            identity.provider_session_generation
            != self.provider_session_generation
        ):
            raise QwenParallelStateError(
                "parallel commit candidate generation is stale"
            )
        if self.provider_context_state != "CLEAN":
            raise QwenParallelStateError(
                "parallel commit requires CLEAN provider context"
            )
        if (
            gate.candidate_playback_epoch != self.playback_epoch
            or gate.candidate_interaction_state_version
            != self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "parallel commit Gate fence is stale"
            )
        if gate.candidate_id in self.candidate_dispositions:
            raise QwenParallelStateError(
                "candidate already has a terminal disposition"
            )

        self.candidate_dispositions[gate.candidate_id] = "COMMITTED"
        self._terminal_output_by_event_id[event_id] = (
            _TerminalOutputBinding(
                candidate_id=gate.candidate_id,
                gate_event_id=gate_event_id,
                disposition="COMMITTED",
            )
        )

    def _reduce_discard(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        candidate_event_id = _require_safe_token(
            event.get("candidate_event_id"),
            "candidate_event_id",
        )
        candidate_id = self._candidate_event_to_id.get(candidate_event_id)
        if candidate_id is None:
            raise QwenParallelStateError(
                "parallel discard requires its candidate event"
            )
        fast_output_event_id = _require_safe_token(
            event.get("fast_interaction_output_event_id"),
            "fast_interaction_output_event_id",
        )
        expected_candidate_id = self._candidate_fast_output_to_id.get(
            fast_output_event_id
        )
        if expected_candidate_id != candidate_id:
            raise QwenParallelStateError(
                "parallel discard fast output mismatch"
            )
        gate_event_id = _require_safe_token(
            event.get("caused_by_event_id"),
            "caused_by_event_id",
        )
        gate = self._gate_by_event_id.get(gate_event_id)
        if (
            gate is None
            or gate.passed
            or gate.candidate_id != candidate_id
        ):
            raise QwenParallelStateError(
                "parallel discard requires its failed Gate"
            )
        if candidate_id in self.candidate_dispositions:
            raise QwenParallelStateError(
                "candidate already has a terminal disposition"
            )

        self.candidate_dispositions[candidate_id] = "DISCARDED"
        self._terminal_output_by_event_id[event_id] = (
            _TerminalOutputBinding(
                candidate_id=candidate_id,
                gate_event_id=gate_event_id,
                disposition="DISCARDED",
            )
        )

    def _reduce_shadow_verification(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        response_id = _require_safe_token(
            event.get("qwen_response_id"),
            "qwen_response_id",
        )
        candidate_id = self._candidate_response_to_id.get(response_id)
        if candidate_id is None:
            raise QwenParallelStateError(
                "shadow verification requires a known candidate response"
            )
        identity = self.candidate_identities[candidate_id]
        transcript_digest = _require_digest(
            event.get("candidate_transcript_digest"),
            "candidate_transcript_digest",
        )
        pcm_digest = _require_digest(
            event.get("candidate_pcm_manifest_digest"),
            "candidate_pcm_manifest_digest",
        )
        if transcript_digest != identity.candidate_transcript_digest:
            raise QwenParallelStateError(
                "shadow verification transcript digest mismatch"
            )
        if pcm_digest != identity.candidate_pcm_manifest_digest:
            raise QwenParallelStateError(
                "shadow verification PCM digest mismatch"
            )
        if response_id in self._shadow_response_ids:
            raise QwenParallelStateError(
                "duplicate shadow verification for candidate response"
            )
        if "decoded_duration_ms" in event:
            _require_nonnegative_int(
                event.get("decoded_duration_ms"),
                "decoded_duration_ms",
            )
        _require_capacity(
            len(self.shadow_verification_event_ids),
            "shadow verification",
        )

        self._shadow_response_ids.add(response_id)
        self.shadow_verification_event_ids += (event_id,)

    def _reduce_handoff_emitted(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        handoff_id = _require_safe_token(
            event.get("handoff_id"),
            "handoff_id",
        )
        if handoff_id in self._handoff_by_id:
            raise QwenParallelStateError("duplicate handoff_id")
        kind = _require_enum(
            event.get("kind"),
            "kind",
            _HANDOFF_KINDS,
        )
        expiry_status = _require_enum(
            event.get("expiry_status"),
            "expiry_status",
            _HANDOFF_EXPIRY_STATUSES,
        )
        task_id = _require_safe_token(event.get("task_id"), "task_id")
        plan_version = _require_positive_int(
            event.get("plan_version"),
            "plan_version",
        )
        task_event_seq = _require_positive_int(
            event.get("task_event_seq"),
            "task_event_seq",
        )
        _validate_optional_id_sequence(event.get("source_event_ids"))
        _require_capacity(len(self._handoff_by_id), "slow handoff")

        self._handoff_by_id[handoff_id] = _HandoffBinding(
            event_id=event_id,
            emission_ordinal=len(self._handoff_by_id) + 1,
            kind=kind,
            expiry_status=expiry_status,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=task_event_seq,
        )

    def _reduce_handoff_disposition(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        handoff_id = _require_safe_token(
            event.get("handoff_id"),
            "handoff_id",
        )
        handoff = self._handoff_by_id.get(handoff_id)
        if handoff is None:
            raise QwenParallelStateError(
                "handoff disposition requires an emitted handoff"
            )
        disposition = _require_enum(
            event.get("disposition"),
            "disposition",
            _HANDOFF_DISPOSITIONS,
        )
        previous = self.handoff_dispositions.get(handoff_id)
        if previous in _TERMINAL_HANDOFF_DISPOSITIONS:
            raise QwenParallelStateError(
                "handoff already has a terminal disposition"
            )
        if previous == "QUEUED" and disposition == "QUEUED":
            raise QwenParallelStateError(
                "handoff QUEUED disposition cannot repeat"
            )
        if handoff.expiry_status == "EXPIRED" and disposition != "EXPIRED":
            raise QwenParallelStateError(
                "EXPIRED handoff requires an EXPIRED disposition"
            )

        if disposition == "SELECTED":
            current_task_id = _require_safe_token(
                event.get("current_task_id"),
                "current_task_id",
            )
            current_plan_version = _require_positive_int(
                event.get("current_plan_version"),
                "current_plan_version",
            )
            current_task_event_seq = _require_positive_int(
                event.get("current_task_event_seq"),
                "current_task_event_seq",
            )
            if (
                current_task_id,
                current_plan_version,
                current_task_event_seq,
            ) != (
                handoff.task_id,
                handoff.plan_version,
                handoff.task_event_seq,
            ):
                raise QwenParallelStateError(
                    "SELECTED handoff current task identity mismatch"
                )
            arbitration_event_id = _require_safe_token(
                event.get("response_arbitration_event_id"),
                "response_arbitration_event_id",
            )
            arbitration = self._arbitration_by_event_id.get(
                arbitration_event_id
            )
            if arbitration is None:
                raise QwenParallelStateError(
                    "selected handoff requires prior arbitration"
                )
            if (
                arbitration.selected_source_event_id
                != handoff.event_id
            ):
                raise QwenParallelStateError(
                    "selected handoff does not match arbitration"
                )
            expected_source_type = _HANDOFF_SOURCE_TYPE_BY_KIND[
                handoff.kind
            ]
            if arbitration.selected_source_type != expected_source_type:
                raise QwenParallelStateError(
                    "selected handoff kind does not match arbitration source"
                )
            if self._authority_ids_are_superseded(
                (handoff.event_id, arbitration_event_id)
            ):
                raise QwenParallelStateError(
                    "selected handoff arbitration authority was superseded"
                )
        elif disposition == "STALE":
            current_task_id = _require_safe_token(
                event.get("current_task_id"),
                "current_task_id",
            )
            current_plan_version = _require_positive_int(
                event.get("current_plan_version"),
                "current_plan_version",
            )
            current_task_event_seq = _require_positive_int(
                event.get("current_task_event_seq"),
                "current_task_event_seq",
            )
            if (
                current_task_id,
                current_plan_version,
                current_task_event_seq,
            ) == (
                handoff.task_id,
                handoff.plan_version,
                handoff.task_event_seq,
            ):
                raise QwenParallelStateError(
                    "STALE handoff requires a current task identity mismatch"
                )
        elif disposition == "COALESCED":
            replacement_id = _require_safe_token(
                event.get("replacement_handoff_id"),
                "replacement_handoff_id",
            )
            replacement = self._handoff_by_id.get(replacement_id)
            if replacement_id == handoff_id or replacement is None:
                raise QwenParallelStateError(
                    "coalesced handoff requires a distinct replacement"
                )
            if replacement.expiry_status != "CURRENT":
                raise QwenParallelStateError(
                    "coalesced handoff replacement must be CURRENT"
                )
            if (
                replacement.task_id != handoff.task_id
                or replacement.plan_version != handoff.plan_version
            ):
                raise QwenParallelStateError(
                    "coalesced handoff replacement task and plan mismatch"
                )
            if replacement.task_event_seq <= handoff.task_event_seq:
                raise QwenParallelStateError(
                    "coalesced handoff replacement must be newer"
                )
            if replacement.emission_ordinal <= handoff.emission_ordinal:
                raise QwenParallelStateError(
                    "coalesced handoff replacement must be emitted later"
                )
            if (
                _HANDOFF_SOURCE_TYPE_BY_KIND[replacement.kind]
                != _HANDOFF_SOURCE_TYPE_BY_KIND[handoff.kind]
            ):
                raise QwenParallelStateError(
                    "coalesced handoff replacement kind is incompatible"
                )
            if self.handoff_dispositions.get(replacement_id) not in (
                None,
                "QUEUED",
            ):
                raise QwenParallelStateError(
                    "coalesced handoff replacement lifecycle is ineligible"
                )

        self.handoff_dispositions[handoff_id] = disposition
        if disposition == "SELECTED":
            self._selected_handoff_by_id[handoff_id] = (
                _SelectedHandoffBinding(
                    arbitration_event_id=arbitration_event_id,
                    disposition_event_id=event_id,
                )
            )
        elif disposition == "COALESCED":
            self._coalesced_handoff_by_id[handoff_id] = (
                _CoalescedHandoffBinding(
                    replacement_handoff_id=replacement_id,
                    disposition_event_id=event_id,
                )
            )

    def _reduce_arbitration(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        generation = _require_positive_int(
            event.get("provider_session_generation"),
            "provider_session_generation",
        )
        if generation != self.provider_session_generation:
            raise QwenParallelStateError(
                "response arbitration generation mismatch"
            )
        epoch = _require_nonnegative_int(
            event.get("playback_epoch"),
            "playback_epoch",
        )
        version = _require_nonnegative_int(
            event.get("interaction_state_version"),
            "interaction_state_version",
        )
        if (
            epoch != self.playback_epoch
            or version != self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "response arbitration fence mismatch"
            )
        arbitration_id = _require_safe_token(
            event.get("arbitration_id"),
            "arbitration_id",
        )
        if arbitration_id in self._arbitration_id_to_event_id:
            raise QwenParallelStateError("duplicate arbitration_id")
        selected_source_type = _require_enum(
            event.get("selected_source_type"),
            "selected_source_type",
            _ARBITRATION_SOURCE_TYPES,
        )
        selected_source_event_id = _optional_safe_token(
            event.get("selected_source_event_id"),
            "selected_source_event_id",
        )
        if selected_source_type == "none":
            if selected_source_event_id is not None:
                raise QwenParallelStateError(
                    "none arbitration selected source must be absent"
                )
        elif selected_source_event_id is None:
            raise QwenParallelStateError(
                "response arbitration selected source is required"
            )
        elif selected_source_type == "user_fast":
            if not self._is_eligible_user_fast_authority(
                selected_source_event_id
            ):
                raise QwenParallelStateError(
                    "user_fast arbitration requires a known eligible "
                    "candidate, passed Gate, or committed output"
                )
        else:
            selected_handoff = self._handoff_for_event_id(
                selected_source_event_id
            )
            if selected_handoff is None:
                raise QwenParallelStateError(
                    "handoff arbitration requires a known handoff source"
                )
            handoff_id, handoff = selected_handoff
            if handoff.expiry_status != "CURRENT":
                raise QwenParallelStateError(
                    "response arbitration cannot select an expired handoff"
                )
            if self.handoff_dispositions.get(handoff_id) not in (
                None,
                "QUEUED",
            ):
                raise QwenParallelStateError(
                    "response arbitration requires a CURRENT handoff"
                )
            if (
                _HANDOFF_SOURCE_TYPE_BY_KIND[handoff.kind]
                != selected_source_type
            ):
                raise QwenParallelStateError(
                    "response arbitration source type does not match "
                    "handoff kind"
                )
        superseded_source_event_ids = tuple(
            sorted(
                _validate_optional_id_sequence(
                    event.get("superseded_source_event_ids")
                )
            )
        )
        if any(
            not self._is_known_canonical_authority_event_id(
                source_event_id
            )
            for source_event_id in superseded_source_event_ids
        ):
            raise QwenParallelStateError(
                "superseded source must reference known canonical authority"
            )
        if (
            selected_source_event_id is not None
            and selected_source_event_id in superseded_source_event_ids
        ):
            raise QwenParallelStateError(
                "selected source cannot also be superseded"
            )
        _require_capacity(
            len(self.response_arbitration_event_ids),
            "response arbitration",
        )

        self._arbitration_by_event_id[event_id] = _ArbitrationBinding(
            selected_source_type=selected_source_type,
            selected_source_event_id=selected_source_event_id,
            superseded_source_event_ids=superseded_source_event_ids,
        )
        self._arbitration_id_to_event_id[arbitration_id] = event_id
        self.response_arbitration_event_ids += (event_id,)

    def _reduce_delivery(
        self,
        event: Mapping[str, Any],
        _event_id: str,
    ) -> None:
        assistant_item_ref = _require_safe_token(
            event.get("assistant_item_ref"),
            "assistant_item_ref",
        )
        source_output_event_id = _require_safe_token(
            event.get("source_output_event_id"),
            "source_output_event_id",
        )
        if event.get("from_status") != "PENDING":
            raise QwenParallelStateError(
                "assistant delivery must transition from PENDING"
            )
        to_status = _require_enum(
            event.get("to_status"),
            "to_status",
            _DELIVERY_DISPOSITIONS,
        )
        if assistant_item_ref in self.assistant_delivery_dispositions:
            raise QwenParallelStateError(
                "assistant item already has a terminal delivery disposition"
            )
        if "release_token_ref" in event:
            _require_release_token_ref(event.get("release_token_ref"))
        if "actual_stop_offset_ms" in event:
            _require_nonnegative_int(
                event.get("actual_stop_offset_ms"),
                "actual_stop_offset_ms",
            )
        _validate_optional_id_sequence(event.get("source_event_ids"))
        _require_capacity(
            len(self.assistant_delivery_dispositions),
            "assistant delivery disposition",
        )

        self.assistant_delivery_dispositions[assistant_item_ref] = to_status
        output = self._terminal_output_by_event_id.get(
            source_output_event_id
        )
        if output is not None and output.disposition == "COMMITTED":
            gate = self._gate_by_event_id[output.gate_event_id]
            self._retired_user_fast_authority_event_ids.update(
                (
                    gate.candidate_event_id,
                    output.gate_event_id,
                    source_output_event_id,
                )
            )

    def _reduce_interrupt(
        self,
        event: Mapping[str, Any],
        event_id: str,
    ) -> None:
        if (
            "playback_epoch" not in event
            or "interaction_state_version" not in event
        ):
            raise QwenParallelStateError(
                "interrupt fence requires epoch and state version"
            )
        if self.provider_session_generation is None:
            raise QwenParallelStateError(
                "interrupt fence requires initialized provider state"
            )
        if self._pending_interrupt_fence is not None:
            raise QwenParallelStateError(
                "prior interrupt is missing its truncate request"
            )
        epoch = _require_nonnegative_int(
            event.get("playback_epoch"),
            "playback_epoch",
        )
        version = _require_nonnegative_int(
            event.get("interaction_state_version"),
            "interaction_state_version",
        )
        if (
            epoch <= self.playback_epoch
            or version <= self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "interrupt fence must strictly advance"
            )
        source_event_seq_lower_bound = self._source_event_seq_lower_bound
        if "event_seq" in event:
            interrupt_event_seq = _require_positive_int(
                event.get("event_seq"),
                "event_seq",
            )
            if interrupt_event_seq <= self._source_event_seq_lower_bound:
                raise QwenParallelStateError(
                    "interrupt source prefix fence must advance"
                )
            source_event_seq_lower_bound = interrupt_event_seq

        self.playback_epoch = epoch
        self.interaction_state_version = version
        self._pending_interrupt_fence = (event_id, epoch, version)
        self._source_event_seq_lower_bound = (
            source_event_seq_lower_bound
        )

    def _reduce_truncate(
        self,
        event: Mapping[str, Any],
        _event_id: str,
    ) -> None:
        if (
            "playback_epoch" not in event
            or "interaction_state_version" not in event
        ):
            raise QwenParallelStateError(
                "truncate fence requires epoch and state version"
            )
        pending = self._pending_interrupt_fence
        if pending is None:
            raise QwenParallelStateError(
                "truncate request has no pending interrupt"
            )
        interrupt_event_id = _require_safe_token(
            event.get("interrupt_candidate_event_id"),
            "interrupt_candidate_event_id",
        )
        epoch = _require_nonnegative_int(
            event.get("playback_epoch"),
            "playback_epoch",
        )
        version = _require_nonnegative_int(
            event.get("interaction_state_version"),
            "interaction_state_version",
        )
        if (
            interrupt_event_id != pending[0]
            or epoch != pending[1]
            or version != pending[2]
            or epoch != self.playback_epoch
            or version != self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "truncate request does not preserve its interrupt fence"
            )

        self._pending_interrupt_fence = None

    def _require_current_clean_generation(
        self,
        event: Mapping[str, Any],
    ) -> int:
        generation = _require_positive_int(
            event.get("provider_session_generation"),
            "provider_session_generation",
        )
        self._require_binding_current_and_clean(generation)
        return generation

    def _require_binding_current_and_clean(self, generation: int) -> None:
        if generation != self.provider_session_generation:
            raise QwenParallelStateError(
                "parallel event provider generation mismatch"
            )
        if self.provider_context_state != "CLEAN":
            raise QwenParallelStateError(
                "parallel provider-backed event requires CLEAN context"
            )

    def _require_projection_current_fence(
        self,
        projection: _ProjectionBinding,
    ) -> None:
        if (
            projection.playback_epoch != self.playback_epoch
            or projection.interaction_state_version
            != self.interaction_state_version
        ):
            raise QwenParallelStateError(
                "context projection fence is stale"
            )

    def _handoff_for_event_id(
        self,
        event_id: str,
    ) -> tuple[str, _HandoffBinding] | None:
        for handoff_id, binding in self._handoff_by_id.items():
            if binding.event_id == event_id:
                return handoff_id, binding
        return None

    def _authority_ids_are_superseded(
        self,
        authority_event_ids: tuple[str, ...],
    ) -> bool:
        authority_ids = frozenset(authority_event_ids)
        return any(
            not authority_ids.isdisjoint(
                arbitration.superseded_source_event_ids
            )
            for arbitration in self._arbitration_by_event_id.values()
        )

    def _is_eligible_user_fast_authority(self, event_id: str) -> bool:
        if event_id in self._retired_user_fast_authority_event_ids:
            return False
        candidate_id = self._candidate_event_to_id.get(event_id)
        if candidate_id is not None:
            if candidate_id in self.candidate_dispositions:
                return False
            gate_event_id = self._candidate_gate_event_id.get(candidate_id)
            if gate_event_id is None:
                return True
            return self._gate_by_event_id[gate_event_id].passed

        gate = self._gate_by_event_id.get(event_id)
        if gate is not None:
            return gate.passed

        output = self._terminal_output_by_event_id.get(event_id)
        return output is not None and output.disposition == "COMMITTED"

    def _is_known_canonical_authority_event_id(
        self,
        event_id: str,
    ) -> bool:
        if (
            event_id in self._candidate_event_to_id
            or event_id in self._gate_by_event_id
            or event_id in self._terminal_output_by_event_id
            or event_id in self._arbitration_by_event_id
        ):
            return True
        if self._handoff_for_event_id(event_id) is not None:
            return True
        return any(
            binding.disposition_event_id == event_id
            for binding in self._selected_handoff_by_id.values()
        )


def _candidate_fast_output_event_id(
    bindings: Mapping[str, str],
    candidate_id: str,
) -> str:
    matches = [
        event_id
        for event_id, bound_candidate_id in bindings.items()
        if bound_candidate_id == candidate_id
    ]
    if len(matches) != 1:
        raise QwenParallelStateError(
            "candidate fast output correlation is not unique"
        )
    return matches[0]


def _gate_binding_digest(binding: _GateBinding) -> dict[str, Any]:
    digest = asdict(binding)
    if binding.release_token_ref is None:
        digest.pop("release_token_ref")
    return digest


def _require_capacity(
    current_size: int,
    label: str,
    *,
    limit: int = _MAX_TRACKED_ITEMS,
) -> None:
    if current_size >= limit:
        raise QwenParallelStateError(f"{label} state exceeds bounded capacity")


def _require_safe_token(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN.fullmatch(value) is None:
        raise QwenParallelStateError(f"invalid {label}")
    return value


def _optional_safe_token(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_safe_token(value, label)


def _require_safe_ref(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_SAFE_REF_CHARS
        or _SAFE_REF.fullmatch(value) is None
    ):
        raise QwenParallelStateError(f"invalid {label}")
    return value


def _optional_safe_ref(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_safe_ref(value, label)


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_DIGEST.fullmatch(value) is None:
        raise QwenParallelStateError(f"invalid {label} digest")
    return value


def _require_release_token_ref(value: object) -> str:
    if not isinstance(value, str) or not is_safe_release_token_ref(value):
        raise QwenParallelStateError("invalid release token ref")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_COUNTER
    ):
        raise QwenParallelStateError(f"invalid {label}")
    return value


def _require_positive_int(value: object, label: str) -> int:
    integer = _require_nonnegative_int(value, label)
    if integer == 0:
        raise QwenParallelStateError(f"invalid {label}")
    return integer


def _optional_nonnegative_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _require_nonnegative_int(value, label)


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _require_positive_int(value, label)


def _require_enum(
    value: object,
    label: str,
    allowed: frozenset[str],
) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise QwenParallelStateError(f"invalid {label}")
    return value


def _validate_optional_id_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise QwenParallelStateError("source event IDs must be a sequence")
    if len(value) > _MAX_TRACKED_ITEMS:
        raise QwenParallelStateError("source event IDs exceed bounded capacity")
    ids = tuple(
        _require_safe_token(item, "source_event_id")
        for item in value
    )
    if len(ids) != len(set(ids)):
        raise QwenParallelStateError("duplicate source event ID")
    return ids


def _validate_optional_ref_sequence(
    value: object,
    label: str,
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise QwenParallelStateError(f"{label} must be a sequence")
    if len(value) > _MAX_TRACKED_ITEMS:
        raise QwenParallelStateError(f"{label} exceed bounded capacity")
    return tuple(_require_safe_ref(item, label) for item in value)


def _normalize_optional_policy_versions(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        if len(value) > _MAX_TRACKED_ITEMS:
            raise QwenParallelStateError(
                "policy_versions exceed bounded capacity"
            )
        return tuple(
            sorted(
                (
                    _require_safe_token(key, "policy_versions key"),
                    _normalize_policy_version_value(version),
                )
                for key, version in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_TRACKED_ITEMS:
            raise QwenParallelStateError(
                "policy_versions exceed bounded capacity"
            )
        return tuple(
            _normalize_policy_version_value(item) for item in value
        )
    return _normalize_policy_version_value(value)


def _normalize_policy_version_value(value: object) -> str | int:
    if isinstance(value, str):
        return _require_safe_token(value, "policy_versions value")
    return _require_nonnegative_int(value, "policy_versions value")


__all__ = [
    "CandidateReplayIdentityV1",
    "QwenParallelState",
    "QwenParallelStateError",
]
