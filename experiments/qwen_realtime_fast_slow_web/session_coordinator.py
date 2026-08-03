"""Single-owner realtime session coordinator for the Fast/Slow spike.

All critical state mutation happens on one asyncio loop behind one coordinator
lock.  Provider reply text and PCM remain quarantined until the existing local
Router and Fast Foreground Gate authorize an output.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Mapping, Protocol

from voice_agent.adapters.fast_interaction_contract import (
    FastInteractionBinding,
    FastInteractionOutput,
    emit_fast_interaction_events,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.interaction.controller import InteractionController
from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateConfig,
    FastForegroundGateContext,
    FastForegroundGateResult,
    commit_deferred_foreground_template,
    run_fast_foreground_gate,
)
from voice_agent.runtime.foreground_template_catalog import (
    get_foreground_template,
    resolve_foreground_template,
)
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.state.interaction_state import InteractionState
from voice_agent.state.slowtask_state import (
    SLOWTASK_EVENT_NAMES,
    SlowTaskState,
    SlowTaskStateError,
)
from voice_agent.user_patch.evidence_pack import UserPatchEvidencePackRuntime

from .browser_protocol import (
    FAKE_SCENARIOS,
    MICROPHONE_FAKE_SCENARIOS,
    metadata_only_copy,
    pack_output_audio,
    safe_code,
    safe_error_message,
    server_message,
    validate_input_audio_frame,
)
from .candidate_quarantine import CandidateQuarantine, QuarantineLimits
from .fake_provider import (
    FakeProviderDisconnected,
    FakeProviderEvent,
    FakeRealtimeProvider,
)
from .realtime_evidence import ProviderRouteProposal, RealtimeTurnEvidenceBundle
from .qwen_shadow_router_adapter import (
    ShadowRouteRequest,
    ShadowRouteResult,
)
from .shadow_router_evaluator import ShadowRouterEvaluator


_VOICE_TRANSIENT_INGRESS_CODES = frozenset(
    {
        "voice_context_rebuilding",
        "voice_context_tainted",
        "voice_provider_not_connected",
        "voice_ingress_generation_stale",
        "voice_ingress_generation_retired",
    }
)
_VOICE_SEND_FAILURE_CODE = "voice_send_failed"


class BrowserSink(Protocol):
    async def send_json(self, data: Mapping[str, Any]) -> Any: ...

    async def send_bytes(self, data: bytes) -> Any: ...

    async def close(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class CoordinatorConfig:
    max_input_queue_frames: int = 24
    max_output_queue_batches: int = 4
    max_metadata_timeline_entries: int = 160
    max_shadow_request_queue: int = 2
    shadow_request_timeout_seconds: float = 12.0
    voice_cancel_terminal_timeout_seconds: float = 2.0
    browser_projection_timeout_seconds: float = 0.25
    gate_confidence_threshold: float = 0.8
    max_correlation_tombstones: int = 256
    quarantine_limits: QuarantineLimits = field(default_factory=QuarantineLimits)

    def __post_init__(self) -> None:
        if min(
            self.max_input_queue_frames,
            self.max_output_queue_batches,
            self.max_metadata_timeline_entries,
            self.max_shadow_request_queue,
            self.max_correlation_tombstones,
        ) < 1:
            raise ValueError("coordinator queue/timeline limits must be positive")
        if self.shadow_request_timeout_seconds <= 0:
            raise ValueError("shadow_request_timeout_seconds must be positive")
        if self.voice_cancel_terminal_timeout_seconds <= 0:
            raise ValueError(
                "voice_cancel_terminal_timeout_seconds must be positive"
            )
        if self.browser_projection_timeout_seconds <= 0:
            raise ValueError(
                "browser_projection_timeout_seconds must be positive"
            )
        if (
            not isinstance(self.gate_confidence_threshold, (int, float))
            or isinstance(self.gate_confidence_threshold, bool)
            or not 0.0 <= float(self.gate_confidence_threshold) <= 1.0
        ):
            raise ValueError("gate_confidence_threshold must be in [0, 1]")


@dataclass(slots=True)
class ActiveSlowTaskState:
    task_id: str
    lifecycle: str
    plan_version: int
    task_event_seq: int
    terminal_status: str | None = None
    pending_confirmation_id: str | None = None
    pending_confirmation_scope: str | None = None

    @property
    def active_non_terminal(self) -> bool:
        return self.terminal_status is None and self.lifecycle not in {
            "COMPLETED",
            "CANCELLED",
            "FAILED",
        }

    def to_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "task_id": self.task_id,
            "lifecycle": self.lifecycle,
            "plan_version": self.plan_version,
            "task_event_seq": self.task_event_seq,
        }
        if self.terminal_status is not None:
            result["terminal_status"] = self.terminal_status
        if self.pending_confirmation_id is not None:
            result["pending_confirmation_id"] = self.pending_confirmation_id
        if self.pending_confirmation_scope is not None:
            result["pending_confirmation_scope"] = self.pending_confirmation_scope
        return result


@dataclass(slots=True)
class CoordinatorState:
    status: str = "CONNECTING"
    playback_epoch: int = 0
    microphone_active: bool = False
    playback_enabled: bool = True
    configured_scenario: str = "fast"
    router_decision: str | None = None
    task_focus: str | None = None
    foreground_act: str | None = None
    gate_status: str | None = None
    dropped_input_frames: int = 0
    dropped_output_frames: int = 0
    discarded_late_audio_frames: int = 0
    clear_latency_ms: int = 0
    provider_cancel_count: int = 0
    disconnect_requested: bool = False
    active_task: ActiveSlowTaskState | None = None
    provider_mode: str = "fake"
    routing_mode: str = "enforced"
    audio_output: str = "fake_pcm"
    shadow_control_mode: str = "dual_session_shadow"
    voice_session_status: str = "connecting"
    shadow_control_session_status: str = "not_available"
    safe_turn_ref: str | None = None
    qwen_task_focus_hint: str | None = None
    qwen_route_hint: str | None = None
    local_router_decision: str | None = None
    local_task_focus: str | None = None
    local_foreground_act: str | None = None
    shadow_foreground_act: str | None = None
    shadow_risk_class: str | None = None
    shadow_confidence: float | None = None
    schema_status: str = "not_available"
    agreement: str = "not_available"
    asr_to_shadow_request_ms: float | None = None
    shadow_request_to_first_delta_ms: float | None = None
    shadow_request_to_done_ms: float | None = None
    function_done_to_local_router_ms: float | None = None
    control_timeout_count: int = 0
    control_error_count: int = 0
    control_cancel_count: int = 0
    control_cancel_terminal_count: int = 0
    context_delete_count: int = 0
    context_rebuild_count: int = 0
    shadow_drop_count: int = 0
    context_tainted: bool = False
    control_topology: str = "none"
    output: str = "audio"
    slow_runtime_mode: str = "mock"
    experimental: bool = False
    qwen_proposal_authority: str = "non_authoritative"
    local_router_authority: str = "authoritative"
    provider_native_audio_disabled: bool = False
    actual_dispatch: str | None = None
    stale_status: str = "current"
    router_gate_latency_ms: float | None = None
    voice_cancel_count: int = 0
    voice_cancel_terminal_count: int = 0
    voice_cancel_terminal_timeout_count: int = 0
    voice_unsafe_cancel_terminal_count: int = 0
    voice_completed_after_cancel_count: int = 0
    voice_failed_after_cancel_count: int = 0
    voice_context_delete_count: int = 0
    voice_context_rebuild_count: int = 0
    voice_rebuild_pcm_drop_count: int = 0
    voice_audio_send_failure_count: int = 0
    voice_rebuild_coalesced_count: int = 0
    voice_cancel_terminal_outcome: str | None = None
    voice_context_tainted: bool = False
    assistant_text_suppression_count: int = 0
    audio_suppression_count: int = 0
    binary_playback_frame_count: int = 0
    stale_provider_event_discard_count: int = 0

    def to_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.status,
            "playback_epoch": self.playback_epoch,
            "microphone_active": self.microphone_active,
            "playback_enabled": self.playback_enabled,
            "scenario": self.configured_scenario,
            "dropped_input_frames": self.dropped_input_frames,
            "dropped_output_frames": self.dropped_output_frames,
            "discarded_late_audio_frames": self.discarded_late_audio_frames,
            "clear_latency_ms": self.clear_latency_ms,
            "provider_cancel_count": self.provider_cancel_count,
            "provider_mode": self.provider_mode,
            "routing_mode": self.routing_mode,
            "audio_output": self.audio_output,
            "shadow_control_mode": self.shadow_control_mode,
            "voice_session_status": self.voice_session_status,
            "shadow_control_session_status": self.shadow_control_session_status,
            "schema_status": self.schema_status,
            "agreement": self.agreement,
            "control_timeout_count": self.control_timeout_count,
            "control_error_count": self.control_error_count,
            "control_cancel_count": self.control_cancel_count,
            "control_cancel_terminal_count": self.control_cancel_terminal_count,
            "context_delete_count": self.context_delete_count,
            "context_rebuild_count": self.context_rebuild_count,
            "shadow_drop_count": self.shadow_drop_count,
            "context_tainted": self.context_tainted,
            "control_topology": self.control_topology,
            "output": self.output,
            "slow_runtime_mode": self.slow_runtime_mode,
            "experimental": self.experimental,
            "qwen_proposal_authority": self.qwen_proposal_authority,
            "local_router_authority": self.local_router_authority,
            "provider_native_audio_disabled": self.provider_native_audio_disabled,
            "stale_status": self.stale_status,
            "voice_cancel_count": self.voice_cancel_count,
            "voice_cancel_terminal_count": self.voice_cancel_terminal_count,
            "voice_cancel_terminal_timeout_count": (
                self.voice_cancel_terminal_timeout_count
            ),
            "voice_unsafe_cancel_terminal_count": (
                self.voice_unsafe_cancel_terminal_count
            ),
            "voice_completed_after_cancel_count": (
                self.voice_completed_after_cancel_count
            ),
            "voice_failed_after_cancel_count": self.voice_failed_after_cancel_count,
            "voice_context_delete_count": self.voice_context_delete_count,
            "voice_context_rebuild_count": self.voice_context_rebuild_count,
            "voice_rebuild_pcm_drop_count": self.voice_rebuild_pcm_drop_count,
            "voice_audio_send_failure_count": self.voice_audio_send_failure_count,
            "voice_rebuild_coalesced_count": self.voice_rebuild_coalesced_count,
            "voice_context_tainted": self.voice_context_tainted,
            "assistant_text_suppression_count": self.assistant_text_suppression_count,
            "audio_suppression_count": self.audio_suppression_count,
            "binary_playback_frame_count": self.binary_playback_frame_count,
            "stale_provider_event_discard_count": (
                self.stale_provider_event_discard_count
            ),
        }
        for key in ("router_decision", "task_focus", "foreground_act", "gate_status"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.active_task is not None:
            result.update(self.active_task.to_metadata())
        optional_fields = {
            "safe_turn_ref": self.safe_turn_ref,
            "qwen_task_focus_hint": self.qwen_task_focus_hint,
            "qwen_route_hint": self.qwen_route_hint,
            "local_router_decision": self.local_router_decision,
            "local_task_focus": self.local_task_focus,
            "local_foreground_act": self.local_foreground_act,
            "foreground_act": self.shadow_foreground_act,
            "risk_class": self.shadow_risk_class,
            "confidence": self.shadow_confidence,
            "asr_to_shadow_request_ms": self.asr_to_shadow_request_ms,
            "shadow_request_to_first_delta_ms": self.shadow_request_to_first_delta_ms,
            "shadow_request_to_done_ms": self.shadow_request_to_done_ms,
            "function_done_to_local_router_ms": self.function_done_to_local_router_ms,
            "actual_dispatch": self.actual_dispatch,
            "router_gate_latency_ms": self.router_gate_latency_ms,
            "voice_cancel_terminal_outcome": self.voice_cancel_terminal_outcome,
        }
        result.update(
            {key: value for key, value in optional_fields.items() if value is not None}
        )
        return result


@dataclass(frozen=True, slots=True)
class _CommittedTurnAuthority:
    """Local authority transferred at the canonical final-ASR boundary.

    A Voice transport generation may be retired for cleanup after this token
    is created.  Control work is therefore fenced by local turn identity and
    playback/supersession state, not by the provider transport generation.
    """

    session_id: str
    conversation_id: str
    turn_id: str
    utterance_id: str
    asr_event_id: str
    asr_frame_ref: str
    playback_epoch: int


@dataclass(slots=True)
class _TurnContext:
    index: int
    turn_id: str
    utterance_id: str
    audio_span_id: str
    playback_epoch: int
    scenario: str
    speech_start_event: dict[str, Any]
    provider_input_item_ref: str | None = None
    provider_turn_ref: str | None = None
    provider_utterance_ref: str | None = None
    provider_audio_span_ref: str | None = None
    provider_session_ref: str | None = None
    provider_final_seen: bool = False
    turn_committed_event: dict[str, Any] | None = None
    asr_frame_event: dict[str, Any] | None = None
    committed_control_authority: _CommittedTurnAuthority | None = field(
        default=None,
        repr=False,
    )
    authority: _EnforcedTurnAuthority = field(default_factory=lambda: _EnforcedTurnAuthority())


@dataclass(slots=True)
class _EnforcedTurnAuthority:
    claimed: bool = False
    fast_interaction_output_event: dict[str, Any] | None = None
    candidate_event: dict[str, Any] | None = None
    router_decision_event: dict[str, Any] | None = None
    gate_result: FastForegroundGateResult | None = None
    degraded_event: dict[str, Any] | None = None
    route_delivery_attempted: bool = False
    gate_delivery_attempted: bool = False
    dispatch_metadata_attempted: bool = False
    delivery_degraded_recorded: bool = False
    mutation_kind: str | None = None
    mutation_started: bool = False
    mutation_completed: bool = False
    mutation_outcome: str = "not_started"
    delivery_state: str = "delivery_not_started"
    delivery_response_id: str | None = None
    semantic_response_kind: str | None = None
    delivery_commit_ref: str | None = None
    delivery_output_ref: str | None = None
    delivery_output_basis: str | None = None


@dataclass(frozen=True, slots=True)
class _VoiceIngressFrame:
    pcm16le: bytes = field(repr=False)
    coordinator_generation: int
    provider_generation: int | None


@dataclass(frozen=True, slots=True)
class _ProviderAuthorityToken:
    """Immutable authority captured before provider-event dispatch.

    The retirement event lets a blocked browser projection be cancelled as
    soon as the coordinator fences the generation. Provider generation is
    still polled so an adapter-owned rebuild cannot hide behind the lock.
    """

    provider_generation: int
    coordinator_generation: int
    session_ref: str
    retirement_event: asyncio.Event = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _MutationOutcome:
    kind: str
    status: str
    canonical_event_count: int
    reason_code: str

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(slots=True)
class _ResponseContext:
    response_id: str
    provider_item_id: str
    playback_epoch: int
    scenario: str
    turn: _TurnContext
    route_processed: bool = False
    done_status: str | None = None


@dataclass(frozen=True, slots=True)
class _PlaybackBatch:
    response_id: str
    turn_id: str
    utterance_id: str
    playback_epoch: int
    audio_chunks: tuple[bytes, ...] = field(repr=False)
    committed_event_id: str = ""


@dataclass(slots=True)
class _VoiceResponseLifecycle:
    response_id: str
    playback_epoch: int
    authority_token: _ProviderAuthorityToken | None = field(
        repr=False,
        compare=False,
    )
    output_eligible: bool = True
    cancel_requested: bool = False
    terminal_status: str | None = None
    cleanup_complete: bool = False
    watchdog_task: asyncio.Task[None] | None = None


@dataclass(frozen=True, slots=True)
class _ShadowRequestEnvelope:
    request: Any
    turn: _TurnContext
    task_focus_snapshot: TaskFocusSnapshot
    safe_turn_ref: str
    asr_final_monotonic_ms: int
    playback_epoch: int
    final_transcript_nonempty: bool
    task_identity_ref: str | None
    pending_confirmation_id: str | None
    pending_confirmation_scope: str | None
    requested_plan_version: int | None
    requested_task_event_seq: int | None
    committed_control_authority: _CommittedTurnAuthority | None = field(
        repr=False,
        compare=False,
    )


class RealtimeSessionCoordinator:
    """Own one browser/provider session and its bounded async resources."""

    def __init__(
        self,
        browser_sink: BrowserSink,
        provider: Any,
        *,
        shadow_provider: Any | None = None,
        provider_mode: str = "fake",
        routing_mode: str = "enforced",
        audio_output: str | None = None,
        shadow_control_mode: str = "dual_session_shadow",
        config: CoordinatorConfig | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        if provider_mode not in {"fake", "qwen"}:
            raise ValueError("provider_mode must be fake or qwen")
        if routing_mode not in {"enforced", "shadow"}:
            raise ValueError("routing_mode must be enforced or shadow")
        qwen_enforced = provider_mode == "qwen" and routing_mode == "enforced"
        control_enabled = routing_mode == "shadow" or qwen_enforced
        if control_enabled and shadow_provider is None:
            raise ValueError("shadow_provider_required")
        resolved_audio_output = audio_output or (
            "qwen" if provider_mode == "qwen" else "fake_pcm"
        )
        if resolved_audio_output not in {"qwen", "fake_pcm", "none"}:
            raise ValueError("audio_output must be qwen, fake_pcm, or none")
        if qwen_enforced and resolved_audio_output != "none":
            raise ValueError("qwen_enforced_provider_audio_unsupported")
        if shadow_control_mode not in {
            "dual_session",
            "dual_session_shadow",
            "dual_session_enforced_control",
            "none",
        }:
            raise ValueError("shadow_control_mode_unsupported")
        if control_enabled and shadow_control_mode == "none":
            raise ValueError("shadow_control_mode_required")
        resolved_shadow_control_mode = (
            "dual_session_enforced_control"
            if qwen_enforced
            else ("dual_session_shadow" if routing_mode == "shadow" else "none")
        )
        self.browser_sink = browser_sink
        self.provider = provider
        self.shadow_provider = shadow_provider
        self.provider_mode = provider_mode
        self.routing_mode = routing_mode
        self.qwen_enforced = qwen_enforced
        self.control_enabled = control_enabled
        self.audio_output = resolved_audio_output
        self.shadow_control_mode = resolved_shadow_control_mode
        self.config = config or CoordinatorConfig()
        suffix = uuid.uuid4().hex[:12]
        self.session_id = session_id or f"session_qfs_{suffix}"
        self.conversation_id = conversation_id or f"conversation_qfs_{suffix}"
        self.journal = InMemoryEventJournal(
            session_id=self.session_id,
            conversation_id=self.conversation_id,
        )
        self.state = CoordinatorState(
            provider_mode=provider_mode,
            routing_mode=routing_mode,
            audio_output=resolved_audio_output,
            shadow_control_mode=resolved_shadow_control_mode,
            shadow_control_session_status=(
                "connecting" if control_enabled else "not_available"
            ),
            control_topology=resolved_shadow_control_mode,
            output="text_only" if qwen_enforced else "audio",
            experimental=qwen_enforced,
            provider_native_audio_disabled=qwen_enforced,
        )
        self.quarantine = CandidateQuarantine(self.config.quarantine_limits)
        self.metadata_timeline: deque[dict[str, Any]] = deque(
            maxlen=self.config.max_metadata_timeline_entries
        )

        self._callback_boundary = AdapterCallbackAppendBoundary(self.journal)
        self._interaction = InteractionController(self.journal)
        self._router = MVP1Router(self.journal)
        self._slow_runtime = MockSlowTaskRuntime(self.journal)
        self._patch_runtime = UserPatchEvidencePackRuntime(self.journal)
        self._input_queue: asyncio.Queue[_VoiceIngressFrame] = asyncio.Queue(
            maxsize=self.config.max_input_queue_frames
        )
        self._output_queue: asyncio.Queue[_PlaybackBatch] = asyncio.Queue(
            maxsize=self.config.max_output_queue_batches
        )
        self._shadow_request_queue: asyncio.Queue[_ShadowRequestEnvelope] = (
            asyncio.Queue(maxsize=self.config.max_shadow_request_queue)
        )
        self._state_lock = asyncio.Lock()
        self._provider_task: asyncio.Task[None] | None = None
        self._input_task: asyncio.Task[None] | None = None
        self._output_task: asyncio.Task[None] | None = None
        self._shadow_worker_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._started = False
        self._closed = False
        self._event_counter = 0
        self._timeline_counter = 0
        self._turn_counter = 0
        self._current_turn: _TurnContext | None = None
        self._responses: dict[str, _ResponseContext] = {}
        self._response_order: deque[str] = deque(maxlen=32)
        self._session_started_event: dict[str, Any] | None = None
        self._active_playback_span_id: str | None = None
        self._active_playback_offset_ms = 0
        self._voice_response_epochs: dict[str, int] = {}
        self._voice_active_response_id: str | None = None
        self._voice_response_lifecycles: dict[str, _VoiceResponseLifecycle] = {}
        self._voice_input_item_turns: dict[str, str] = {}
        self._voice_response_tombstones: set[str] = set()
        self._voice_response_tombstone_order: deque[str] = deque()
        self._voice_input_item_tombstones: set[str] = set()
        self._voice_input_item_tombstone_order: deque[str] = deque()
        self._voice_rebuild_task: asyncio.Task[Any] | None = None
        self._voice_rebuild_generation = 0
        self._voice_rebuild_attempted_generation = -1
        self._voice_generation_retired = asyncio.Event()
        self._voice_session_ref: str | None = None
        self._voice_cancel_terminal_timeout_count = 0
        self._voice_rebuild_pcm_drop_count = 0
        self._voice_audio_send_failure_count = 0
        self._voice_rebuild_coalesced_count = 0
        self._voice_recovery_episode_code: str | None = None
        self._voice_send_failure_reported_generation = -1
        self._voice_playback_started: set[str] = set()
        self._latest_shadow_turn_id: str | None = None
        self._shadow_requested_turn_ids: set[str] = set()
        self._shadow_evaluator = ShadowRouterEvaluator(session_ref=self.session_id)
        self._shadow_available = False
        self._shadow_queue_drop_count = 0
        self._shadow_local_error_count = 0
        self._last_shadow_output_mode = "not_available"
        self._enforced_terminal_turn_ids: set[str] = set()
        self._enforced_terminal_turn_order: deque[str] = deque()

    @property
    def input_queue_depth(self) -> int:
        return self._input_queue.qsize()

    @property
    def output_queue_depth(self) -> int:
        return self._output_queue.qsize()

    async def start(self) -> None:
        if self._started:
            return
        if self._closed:
            raise RuntimeError("coordinator_closed")
        now_mono, now_wall = _now_ms()
        self._session_started_event = self.journal.append(
            event_name="SESSION_STARTED",
            event_id=self._next_event_id("session_started"),
            source_module="qwen_realtime_fast_slow_coordinator",
            created_monotonic_ms=now_mono,
            created_wall_clock_ms=now_wall,
            trace_redaction_level="metadata_only",
            runtime_config_ref=(
                "runtime-config://experiment/qfs/slice3a-enforced-control"
                if self.qwen_enforced
                else ("runtime-config://experiment/qfs/slice2-shadow"
                if self.routing_mode == "shadow"
                else "runtime-config://synthetic/qfs/slice1"
                )
            ),
            capability_snapshot_ref=(
                "capability://experiment/qfs/dual-session-enforced-control/v1"
                if self.qwen_enforced
                else ("capability://experiment/qfs/dual-session-shadow/v1"
                if self.routing_mode == "shadow"
                else "capability://synthetic/qfs/fake/v1"
                )
            ),
        )
        profile = self.provider.profile
        shadow_profile = (
            getattr(self.shadow_provider, "profile", None)
            if self.shadow_provider is not None
            else None
        )
        self.journal.append(
            event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
            event_id=self._next_event_id("capability_snapshot"),
            source_module="qwen_realtime_fast_slow_coordinator",
            caused_by_event_id=str(self._session_started_event["event_id"]),
            created_monotonic_ms=now_mono + 1,
            created_wall_clock_ms=now_wall + 1,
            trace_redaction_level="metadata_only",
            capability_snapshot_ref=(
                "capability://experiment/qfs/dual-session-enforced-control/v1"
                if self.qwen_enforced
                else ("capability://experiment/qfs/dual-session-shadow/v1"
                if self.routing_mode == "shadow"
                else "capability://synthetic/qfs/fake/v1"
                )
            ),
            adapter_ids=(
                [str(profile.adapter_id), str(shadow_profile.adapter_id)]
                if shadow_profile is not None
                else [
                    "qfs_fake_duplex_v1",
                    "qfs_fake_asr_v1",
                    "qfs_fake_fast_interaction_v1",
                ]
            ),
            adapter_types=(
                ["duplex_voice", "fast_interaction_shadow"]
                if shadow_profile is not None
                else ["duplex", "asr", "fast_interaction"]
            ),
            deployment_modes=(
                [str(profile.deployment_mode), str(shadow_profile.deployment_mode)]
                if shadow_profile is not None
                else ["mock", "mock", "mock"]
            ),
            output_modes=(
                [str(profile.output_mode), str(shadow_profile.output_mode)]
                if shadow_profile is not None
                else ["mock", "mock", "mock"]
            ),
        )
        await self.provider.connect()
        self.state.voice_session_status = "connected"
        if self.control_enabled:
            try:
                assert self.shadow_provider is not None
                await self.shadow_provider.connect()
                self._shadow_available = True
                self.state.shadow_control_session_status = "connected"
                self._last_shadow_output_mode = str(self.shadow_provider.profile.output_mode)
            except Exception:
                # Shadow control is optional; enforced control fails closed
                # until it can reconnect. Never expose provider exceptions.
                self._shadow_available = False
                self.state.shadow_control_session_status = "degraded"
                self._shadow_local_error_count += 1
                self.state.control_error_count = self._shadow_local_error_count
                self._last_shadow_output_mode = "degraded"
        profile = self.provider.profile
        shadow_profile = (
            getattr(self.shadow_provider, "profile", None)
            if self.shadow_provider is not None
            else None
        )
        self._provider_task = asyncio.create_task(
            self._provider_loop(), name=f"qfs-voice-provider-{self.session_id}"
        )
        self._input_task = asyncio.create_task(
            self._input_loop(), name=f"qfs-input-{self.session_id}"
        )
        self._output_task = asyncio.create_task(
            self._output_loop(), name=f"qfs-output-{self.session_id}"
        )
        if self.control_enabled:
            self._shadow_worker_task = asyncio.create_task(
                self._shadow_request_worker(),
                name=f"qfs-shadow-request-worker-{self.session_id}",
            )
        self._started = True
        self.state.status = "LISTENING"
        await self._send_json(
            "session.ready",
            session_id=self.session_id,
            provider_mode=self.provider_mode,
            routing_mode=self.routing_mode,
            audio_output=self.audio_output,
            shadow_control_mode=self.shadow_control_mode,
            control_topology=self.shadow_control_mode,
            output=self.state.output,
            slow_runtime_mode="mock",
            experimental=self.qwen_enforced,
            qwen_proposal_authority="non_authoritative",
            local_router_authority="authoritative",
            provider_native_audio_disabled=self.qwen_enforced,
            voice_session_status=self.state.voice_session_status,
            shadow_control_session_status=self.state.shadow_control_session_status,
            output_mode=str(profile.output_mode),
            degraded=self.state.shadow_control_session_status == "degraded",
            playback_epoch=self.state.playback_epoch,
            capabilities=profile.to_metadata(),
            shadow_capabilities=(
                shadow_profile.to_metadata() if shadow_profile is not None else None
            ),
        )
        if self.control_enabled and not self._shadow_available:
            if self.qwen_enforced:
                await self._send_control_state(output_mode="degraded")
            else:
                await self._emit_shadow_degraded(
                    code="shadow_control_connect_failed", safe_turn_ref=None
                )
        await self._send_state("session_started")

    async def handle_control(self, payload: Mapping[str, Any]) -> None:
        message_type = payload.get("type")
        if message_type == "session.configure":
            scenario = payload.get("scenario")
            if scenario is not None:
                if scenario not in MICROPHONE_FAKE_SCENARIOS:
                    await self.report_safe_error("microphone_scenario_unsupported")
                    return
                if self.provider_mode == "fake":
                    self.state.configured_scenario = str(scenario)
                    self.provider.configure(default_scenario=str(scenario))
            playback_enabled = payload.get("playback_enabled")
            if playback_enabled is not None:
                if not isinstance(playback_enabled, bool):
                    await self.report_safe_error("playback_enabled_invalid")
                    return
                self.state.playback_enabled = playback_enabled
            await self._send_state("session_configured")
            return
        if message_type == "microphone.start":
            self.state.microphone_active = True
            self.state.status = "LISTENING"
            await self._send_state("microphone_started")
            return
        if message_type == "microphone.stop":
            self.state.microphone_active = False
            try:
                await self.provider.finish_turn(self.state.configured_scenario)
            except FakeProviderDisconnected:
                await self.report_safe_error(
                    "fake_provider_disconnected", terminal=True, retryable=False
                )
            await self._send_state("microphone_stopped")
            return
        if message_type == "synthetic.turn":
            if self.provider_mode != "fake":
                await self.report_safe_error("synthetic_turn_fake_only")
                return
            scenario = payload.get("scenario")
            if scenario not in FAKE_SCENARIOS:
                await self.report_safe_error("synthetic_scenario_unsupported")
                return
            try:
                await self.provider.trigger_scenario(
                    str(scenario),
                    confidence=_optional_confidence(payload.get("confidence")),
                    risk_class=_optional_enum(
                        payload.get("risk_class"), {"LOW", "MEDIUM", "HIGH"}
                    ),
                    foreground_act=_optional_enum(
                        payload.get("foreground_act"),
                        {"ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY"},
                    ),
                )
            except ValueError:
                await self.report_safe_error("synthetic_override_invalid")
            return
        if message_type == "interrupt.request":
            async with self._state_lock:
                await self._interrupt_locked(reason="explicit_interrupt", audio_span_id=None)
            return
        if message_type == "disconnect":
            self.state.disconnect_requested = True
            return
        await self.report_safe_error("control_type_unsupported")

    async def submit_audio(self, pcm16le: bytes) -> bool:
        validate_input_audio_frame(pcm16le)
        if self._closed:
            return False
        provider_generation = self._provider_ingress_generation()
        availability_code = self._voice_ingress_availability_code()
        if self.qwen_enforced and availability_code != "available":
            self._record_voice_rebuild_pcm_drop()
            await self._notify_voice_recovery_once(availability_code)
            return False
        if self._input_queue.full():
            try:
                self._input_queue.get_nowait()
                self._input_queue.task_done()
            except asyncio.QueueEmpty:
                pass
            self.state.dropped_input_frames += 1
            await self._send_flow()
        self._input_queue.put_nowait(
            _VoiceIngressFrame(
                pcm16le=pcm16le,
                coordinator_generation=self._voice_rebuild_generation,
                provider_generation=provider_generation,
            )
        )
        return True

    async def handle_binary_audio(self, pcm16le: bytes) -> bool:
        return await self.submit_audio(pcm16le)

    async def handle_provider_event(self, event: FakeProviderEvent) -> None:
        authority_token = self._capture_provider_authority(event)
        async with self._state_lock:
            if not self._provider_authority_current(authority_token, event):
                self._discard_stale_provider_authority()
                return
            await self._handle_provider_event_locked(
                event, authority_token=authority_token
            )

    async def wait_for_idle(self) -> None:
        """Wait until all currently scheduled fake work reaches browser sinks."""

        await self._input_queue.join()
        wait_response_complete = getattr(self.provider, "wait_response_complete", None)
        if wait_response_complete is not None:
            await wait_response_complete()
        wait_events_drained = getattr(self.provider, "wait_events_drained", None)
        if wait_events_drained is not None:
            await wait_events_drained()
        if self.control_enabled:
            await self._shadow_request_queue.join()
        await self._output_queue.join()
        pending = tuple(task for task in self._background_tasks if not task.done())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)

    async def report_safe_error(
        self, code: object, *, terminal: bool = False, retryable: bool = False
    ) -> None:
        if terminal:
            self.state.status = "ERROR"
        await self.browser_sink.send_json(
            safe_error_message(
                code,
                terminal=terminal,
                retryable=retryable,
                playback_epoch=self.state.playback_epoch,
            )
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.state.status = "DISCONNECTED"
        self.quarantine.clear(reason="disconnect")
        self._drain_input_queue()
        self._drain_output_queue()
        self._drain_shadow_queue()
        for task in (
            self._provider_task,
            self._input_task,
            self._output_task,
            self._shadow_worker_task,
            *tuple(self._background_tasks),
        ):
            if task is not None and not task.done():
                task.cancel()
        tasks = tuple(
            task
            for task in (
                self._provider_task,
                self._input_task,
                self._output_task,
                self._shadow_worker_task,
                *tuple(self._background_tasks),
            )
            if task is not None
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.provider.close()
        if self.shadow_provider is not None:
            try:
                await self.shadow_provider.close()
            except Exception:
                pass
        self._responses.clear()
        self._response_order.clear()
        self._current_turn = None
        self._voice_response_epochs.clear()
        self._voice_response_lifecycles.clear()
        self._voice_input_item_turns.clear()
        self._voice_response_tombstones.clear()
        self._voice_response_tombstone_order.clear()
        self._voice_input_item_tombstones.clear()
        self._voice_input_item_tombstone_order.clear()
        self._voice_rebuild_task = None
        self._voice_rebuild_attempted_generation = -1
        self._voice_session_ref = None
        self._voice_playback_started.clear()
        self._shadow_requested_turn_ids.clear()
        self._latest_shadow_turn_id = None
        self._enforced_terminal_turn_ids.clear()
        self._enforced_terminal_turn_order.clear()
        self._background_tasks.clear()

    async def _provider_loop(self) -> None:
        try:
            while not self._closed:
                receiver_generation = self._provider_ingress_generation()
                try:
                    if hasattr(self.provider, "ingress_generation"):
                        if receiver_generation is None:
                            return
                        event = await self.provider.recv_event(
                            receiver_generation=receiver_generation
                        )
                    else:
                        event = await self.provider.recv_event()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    code = str(getattr(error, "code", ""))
                    if code == "voice_receiver_generation_rebuilding":
                        # A cleanup rebuild fences the old receiver before the
                        # replacement core finishes its handshake. Park the
                        # single receiver owner on that bounded rebuild rather
                        # than letting it exit or poll the half-built core.
                        rebuild_task = self._voice_rebuild_task
                        rebuilt = False
                        if rebuild_task is not None:
                            try:
                                rebuilt = bool(
                                    await asyncio.shield(rebuild_task)
                                )
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                rebuilt = False
                        if rebuilt and not self._closed:
                            continue
                        return
                    if code in {
                        "voice_receiver_generation_stale",
                        "voice_receiver_generation_terminal",
                    }:
                        if (
                            not self._closed
                            and receiver_generation
                            != self._provider_ingress_generation()
                        ):
                            # Rebuild explicitly starts consumption of the new
                            # generation; the retired receiver owns no state.
                            continue
                        return
                    raise
                processing_error: Exception | None = None
                try:
                    await self.handle_provider_event(event)
                except Exception as error:
                    processing_error = error
                finally:
                    event_processed = getattr(self.provider, "event_processed", None)
                    if event_processed is not None:
                        event_processed()
                terminal_event = event.type in {
                    "provider.disconnected",
                    "provider.timeout",
                } or (
                    event.type == "provider.error"
                    and bool(getattr(event, "terminal", False))
                )
                if terminal_event:
                    # A terminal provider event has one lifecycle owner. Park
                    # on its explicit rebuild, then bind the same receiver
                    # loop to the replacement generation. Never poll the dead
                    # core and never depend on browser metadata succeeding.
                    rebuild_task = self._voice_rebuild_task
                    rebuilt = False
                    if rebuild_task is not None:
                        try:
                            rebuilt = bool(await asyncio.shield(rebuild_task))
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            rebuilt = False
                    if rebuilt and not self._closed:
                        continue
                    if processing_error is not None:
                        raise processing_error
                    return
                if processing_error is not None:
                    raise processing_error
        except asyncio.CancelledError:
            raise
        except FakeProviderDisconnected:
            if not self._closed:
                await self.report_safe_error(
                    "fake_provider_disconnected", terminal=True, retryable=False
                )
        except Exception:
            if not self._closed:
                self.state.voice_session_status = "disconnected"
                await self.report_safe_error(
                    "provider_event_processing_failed", terminal=True, retryable=False
                )

    async def _input_loop(self) -> None:
        try:
            while not self._closed:
                frame = await self._input_queue.get()
                try:
                    availability_code = self._voice_ingress_availability_code()
                    if (
                        self.qwen_enforced
                        and (
                            availability_code != "available"
                            or frame.coordinator_generation
                            != self._voice_rebuild_generation
                            or frame.provider_generation
                            != self._provider_ingress_generation()
                            or (
                                self._voice_rebuild_task is not None
                                and not self._voice_rebuild_task.done()
                            )
                        )
                    ):
                        self._record_voice_rebuild_pcm_drop()
                        await self._notify_voice_recovery_once(
                            (
                                availability_code
                                if availability_code != "available"
                                else "voice_ingress_generation_retired"
                            )
                        )
                        continue
                    if self.qwen_enforced and (
                        hasattr(self.provider, "ingress_generation")
                        or hasattr(self.provider, "session_generation")
                    ):
                        assert frame.provider_generation is not None
                        await self.provider.send_audio(
                            frame.pcm16le,
                            ingress_generation=frame.provider_generation,
                        )
                    else:
                        await self.provider.send_audio(frame.pcm16le)
                    self._voice_recovery_episode_code = None
                except FakeProviderDisconnected:
                    await self.report_safe_error(
                        "fake_provider_disconnected", terminal=True, retryable=False
                    )
                except Exception as error:
                    code = self._voice_provider_error_code(error)
                    if self.qwen_enforced and code in _VOICE_TRANSIENT_INGRESS_CODES:
                        self._record_voice_rebuild_pcm_drop()
                        await self._notify_voice_recovery_once(code)
                    elif self.qwen_enforced and code == _VOICE_SEND_FAILURE_CODE:
                        self._voice_audio_send_failure_count += 1
                        self.state.voice_audio_send_failure_count = max(
                            self.state.voice_audio_send_failure_count,
                            self._voice_audio_send_failure_count,
                        )
                        self.state.voice_context_tainted = True
                        self.state.voice_session_status = "degraded"
                        generation = frame.coordinator_generation
                        report_failure = (
                            self._voice_send_failure_reported_generation != generation
                        )
                        if report_failure:
                            self._voice_send_failure_reported_generation = generation
                        # Establish the recovery fence and drain retired PCM
                        # before any fallible browser projection.
                        self._schedule_voice_rebuild()
                        if report_failure:
                            await self._await_browser_projection_best_effort(
                                self.report_safe_error(
                                    _VOICE_SEND_FAILURE_CODE,
                                    retryable=True,
                                )
                            )
                    else:
                        if self.qwen_enforced:
                            await self._await_browser_projection_best_effort(
                                self.report_safe_error("audio_forward_failed")
                            )
                        else:
                            await self.report_safe_error("audio_forward_failed")
                finally:
                    self._input_queue.task_done()
        except asyncio.CancelledError:
            raise

    async def _output_loop(self) -> None:
        try:
            while not self._closed:
                batch = await self._output_queue.get()
                try:
                    await self._play_batch(batch)
                finally:
                    self._output_queue.task_done()
        except asyncio.CancelledError:
            raise

    async def _handle_provider_event_locked(
        self,
        event: FakeProviderEvent,
        *,
        authority_token: _ProviderAuthorityToken | None = None,
    ) -> None:
        if self.routing_mode == "shadow":
            await self._handle_shadow_voice_event_locked(event)
            return
        if self.qwen_enforced:
            await self._handle_enforced_voice_event_locked(
                event, authority_token=authority_token
            )
            return
        if event.type in {"session.created", "session.updated"}:
            await self._timeline("provider_session", {"degraded": False, "output_mode": "mock"})
            return
        if event.type == "speech.started":
            await self._on_speech_started(event)
            return
        if event.type == "speech.stopped":
            await self._on_speech_stopped(event)
            return
        if event.type == "user.transcript.delta":
            await self._on_user_transcript(event, final=False)
            return
        if event.type == "user.transcript.final":
            await self._on_user_transcript(event, final=True)
            return
        if event.type == "response.created":
            await self._on_response_created(event)
            return
        if event.type == "assistant.transcript.delta":
            self._quarantine_text(event)
            return
        if event.type == "assistant.transcript.done":
            return
        if event.type == "response.audio.delta":
            await self._quarantine_audio(event)
            return
        if event.type == "route.proposed":
            await self._on_route_proposed(event)
            return
        if event.type == "response.done":
            await self._on_response_done(event)
            return
        if event.type == "provider.error":
            await self._interrupt_locked(reason="provider_error", audio_span_id=None)
            self.state.status = "ERROR"
            await self._send_json(
                "degraded",
                code=event.error_code or "synthetic_provider_error",
                output_mode="degraded",
                playback_epoch=self.state.playback_epoch,
            )
            await self.report_safe_error(
                event.error_code or "synthetic_provider_error",
                terminal=event.terminal,
                retryable=not event.terminal,
            )
            return
        if event.type == "provider.disconnected":
            await self._interrupt_locked(reason="provider_disconnect", audio_span_id=None)
            self.state.status = "ERROR"
            await self._send_json(
                "degraded",
                code="synthetic_provider_disconnect",
                output_mode="degraded",
                playback_epoch=self.state.playback_epoch,
            )
            await self.report_safe_error(
                "synthetic_provider_disconnect", terminal=True, retryable=False
            )
            return
        await self.report_safe_error("provider_event_unsupported")

    async def _handle_shadow_voice_event_locked(self, event: Any) -> None:
        """Project Voice Session events without consulting shadow routing."""

        if event.type in {"session.created", "session.updated"}:
            self.state.voice_session_status = "connected"
            await self._timeline(
                "voice.session",
                {
                    "provider_mode": self.provider_mode,
                    "routing_mode": "shadow",
                    "output_mode": str(getattr(event, "output_mode", "degraded")),
                },
            )
            return
        if event.type == "speech.started":
            await self._on_speech_started(event)
            return
        if event.type == "speech.stopped":
            await self._on_speech_stopped(event)
            return
        if event.type == "user.transcript.delta":
            await self._on_user_transcript(event, final=False)
            return
        if event.type == "user.transcript.final":
            await self._on_user_transcript(event, final=True)
            return
        if event.type == "response.created":
            await self._on_shadow_voice_response_created(event)
            return
        if event.type == "assistant.transcript.delta":
            await self._on_shadow_voice_transcript(event, final=False)
            return
        if event.type == "assistant.transcript.done":
            await self._on_shadow_voice_transcript(event, final=True)
            return
        if event.type == "response.audio.delta":
            await self._on_shadow_voice_audio(event)
            return
        if event.type in {"response.audio.done", "provider.ignored", "route.proposed"}:
            # A fake voice fixture may still emit its Slice 1 route proposal.
            # Shadow mode never consumes or promotes it.
            return
        if event.type == "response.done":
            await self._on_shadow_voice_response_done(event)
            return
        if event.type == "provider.error":
            terminal = bool(getattr(event, "terminal", False))
            self.state.voice_session_status = (
                "disconnected" if terminal else "degraded"
            )
            if terminal:
                self._drain_input_queue()
                await self._clear_voice_playback(reason="voice_provider_error")
            await self._send_json(
                "degraded",
                code=getattr(event, "error_code", None) or "voice_provider_error",
                output_mode="degraded",
                playback_epoch=self.state.playback_epoch,
            )
            await self.report_safe_error(
                getattr(event, "error_code", None) or "voice_provider_error",
                terminal=terminal,
                retryable=not terminal,
            )
            await self._send_state("voice_provider_error")
            return
        if event.type in {"provider.disconnected", "provider.timeout"}:
            self.state.voice_session_status = "disconnected"
            self.state.status = "ERROR"
            self._drain_input_queue()
            await self._clear_voice_playback(reason="voice_provider_disconnected")
            await self.report_safe_error(
                getattr(event, "error_code", None) or "voice_provider_disconnected",
                terminal=True,
                retryable=False,
            )
            await self._send_state("voice_provider_disconnected")
            return
        await self.report_safe_error("voice_provider_event_unsupported")

    async def _handle_enforced_voice_event_locked(
        self,
        event: Any,
        *,
        authority_token: _ProviderAuthorityToken | None,
    ) -> None:
        """Consume Voice ingress while prohibiting every assistant output."""

        if not self._provider_authority_current(authority_token, event):
            self._discard_stale_provider_authority()
            return
        if event.type in {"session.created", "session.updated"}:
            self.state.voice_session_status = "connected"
            await self._timeline(
                "voice.session",
                {
                    "provider_mode": self.provider_mode,
                    "routing_mode": "enforced",
                    "audio_output": "none",
                    "control_topology": self.shadow_control_mode,
                    "output_mode": str(getattr(event, "output_mode", "degraded")),
                },
            )
            return
        if event.type == "speech.started":
            await self._on_speech_started(
                event, authority_token=authority_token
            )
            return
        if event.type == "speech.stopped":
            await self._on_speech_stopped(
                event, authority_token=authority_token
            )
            return
        if event.type == "user.transcript.delta":
            await self._on_user_transcript(
                event, final=False, authority_token=authority_token
            )
            return
        if event.type == "user.transcript.final":
            await self._on_user_transcript(
                event, final=True, authority_token=authority_token
            )
            return
        if event.type == "response.created":
            await self._on_enforced_voice_response_created(
                event,
                authority_token=authority_token,
            )
            return
        if event.type in {"assistant.transcript.delta", "assistant.transcript.done"}:
            self.state.assistant_text_suppression_count += 1
            await self._refresh_voice_suppression_counters()
            if not self._provider_authority_current(authority_token, event):
                self._discard_stale_provider_authority()
            return
        if event.type == "response.audio.delta":
            self.state.audio_suppression_count += 1
            await self._refresh_voice_suppression_counters()
            if not self._provider_authority_current(authority_token, event):
                self._discard_stale_provider_authority()
            return
        if event.type in {
            "response.audio.done",
            "provider.ignored",
            "route.proposed",
        }:
            # Voice route/text/audio is never FastInteraction evidence.
            return
        if event.type == "response.done":
            await self._on_enforced_voice_response_done(
                event,
                authority_token=authority_token,
            )
            return
        if event.type in {"provider.error", "provider.disconnected", "provider.timeout"}:
            terminal = event.type != "provider.error" or bool(
                getattr(event, "terminal", False)
            )
            if terminal:
                self.state.voice_session_status = "disconnected"
                self.state.voice_context_tainted = True
                self._drain_input_queue()
                # Recovery is scheduled before any best-effort browser/UI
                # projection so a broken sink cannot wedge Voice lifecycle.
                self._schedule_voice_rebuild()
            turn = self._current_turn
            pre_asr_nonterminal_error = bool(
                event.type == "provider.error"
                and not terminal
                and turn is not None
                and turn.asr_frame_event is None
            )
            if not pre_asr_nonterminal_error:
                # A real Voice failure may still win the one terminal claim
                # after local ASR authority exists. A non-terminal cleanup
                # error before final ASR owns no local Control terminal:
                # claiming it would tombstone the later committed result.
                await self._await_browser_projection_best_effort(
                    self._commit_fail_closed_turn(
                        turn,
                        code=(
                            getattr(event, "error_code", None)
                            or "voice_provider_degraded"
                        ),
                        assistant_directed=True,
                    )
                )
            await self._await_browser_projection_best_effort(
                self.report_safe_error(
                    getattr(event, "error_code", None)
                    or "voice_provider_degraded",
                    terminal=terminal,
                    retryable=not terminal,
                )
            )
            return
        await self.report_safe_error("voice_provider_event_unsupported")

    async def _on_enforced_voice_response_created(
        self,
        event: Any,
        *,
        authority_token: _ProviderAuthorityToken | None,
    ) -> None:
        if not self._provider_authority_current(authority_token, event):
            self._discard_stale_provider_authority()
            return
        response_id = getattr(event, "response_id", None)
        if (
            not isinstance(response_id, str)
            or not response_id
            or not bool(getattr(event, "correlation_valid", True))
            or response_id in self._voice_response_lifecycles
            or response_id in self._voice_response_tombstones
        ):
            self.state.voice_context_tainted = True
            self.state.voice_session_status = "degraded"
            self._schedule_voice_rebuild()
            await self._commit_fail_closed_turn(
                self._current_turn,
                code="voice_response_correlation_incomplete",
                assistant_directed=True,
            )
            return
        previous_response_id = self._voice_active_response_id
        if previous_response_id is not None:
            self.state.voice_context_tainted = True
            self.state.voice_session_status = "degraded"
            previous = self._voice_response_lifecycles.get(previous_response_id)
            if previous is not None:
                previous.output_eligible = False
            fence_previous = getattr(
                self.provider, "mark_response_output_ineligible", None
            )
            if callable(fence_previous):
                fence_previous(previous_response_id)
            self._schedule_voice_rebuild()
            await self._commit_fail_closed_turn(
                self._current_turn,
                code="voice_response_overlap_invalid",
                assistant_directed=True,
            )
            return
        self._voice_response_epochs[response_id] = self.state.playback_epoch
        lifecycle = _VoiceResponseLifecycle(
            response_id=response_id,
            playback_epoch=self.state.playback_epoch,
            authority_token=authority_token,
            output_eligible=False,
            cancel_requested=True,
        )
        self._voice_response_lifecycles[response_id] = lifecycle
        self._voice_active_response_id = response_id
        # The enforced Voice adapter cancels synchronously while normalizing
        # ``response.created``.  Cancelling here again would race the matching
        # cancelled terminal and obscure the adapter-owned correlation count.
        # Provider-free tests use the legacy fake Voice directly, so they need
        # one coordinator-owned cancellation to exercise the same lifecycle.
        if not bool(getattr(self.provider, "enforced_output_suppression", False)):
            self._spawn_background(
                self._cancel_voice_response_outside_lock(
                    response_id=response_id,
                    playback_epoch=lifecycle.playback_epoch,
                    expected_lifecycle=lifecycle,
                ),
                name=f"qfs-voice-cancel-{self.session_id}-{response_id}",
            )
        lifecycle.watchdog_task = self._spawn_background(
            self._voice_cancel_watchdog(
                response_id=response_id,
                expected_lifecycle=lifecycle,
            ),
            name=f"qfs-voice-cancel-watchdog-{self.session_id}-{response_id}",
        )
        await self._refresh_voice_suppression_counters()
        control_projection = self._send_control_state(
            output_mode=str(getattr(event, "output_mode", "degraded"))
        )
        if authority_token is None:
            await control_projection
        else:
            await self._await_provider_authority_guarded(
                control_projection,
                authority_token=authority_token,
                event=event,
            )

    async def _on_enforced_voice_response_done(
        self,
        event: Any,
        *,
        authority_token: _ProviderAuthorityToken | None,
    ) -> None:
        if not self._provider_authority_current(authority_token, event):
            self._discard_stale_provider_authority()
            return
        response_id = getattr(event, "response_id", None)
        lifecycle = (
            self._voice_response_lifecycles.get(response_id)
            if isinstance(response_id, str)
            else None
        )
        if (
            lifecycle is None
            or lifecycle.authority_token != authority_token
            or lifecycle.terminal_status is not None
            or not bool(getattr(event, "correlation_valid", True))
        ):
            self.state.discarded_late_audio_frames += 1
            await self._refresh_voice_suppression_counters()
            return
        status = str(getattr(event, "status", "unknown") or "unknown")
        lifecycle.terminal_status = status
        lifecycle.output_eligible = False
        if lifecycle.watchdog_task is not None:
            lifecycle.watchdog_task.cancel()
        if status == "cancelled" and not bool(
            getattr(self.provider, "enforced_output_suppression", False)
        ):
            # The real enforced adapter increments only when both the cancel
            # send and matching cancelled terminal are proven.  Its counter is
            # projected below; do not overclaim from terminal status alone.
            self.state.voice_cancel_terminal_count += 1
        elif status != "cancelled":
            # completed/failed after cancel is never a successful terminal.
            self.state.voice_context_tainted = True
            self.state.voice_session_status = "degraded"
        if self._voice_active_response_id == response_id:
            self._voice_active_response_id = None
        self._spawn_background(
            self._cleanup_voice_response_outside_lock(
                response_id=response_id,
                expected_lifecycle=lifecycle,
            ),
            name=f"qfs-voice-cleanup-{self.session_id}-{response_id}",
        )
        await self._refresh_voice_suppression_counters()
        control_projection = self._send_control_state(
            output_mode=("real" if status == "cancelled" else "degraded")
        )
        bounded_projection = bool(
            getattr(self.provider, "enforced_output_suppression", False)
        )
        if authority_token is None and not bounded_projection:
            # Provider-free fixtures preserve their deterministic single-loop
            # scheduling contract.  The real enforced adapter needs the
            # bounded projection because its receiver owns live recovery.
            await control_projection
        elif authority_token is None:
            await self._await_browser_projection_best_effort(
                control_projection
            )
        elif not bounded_projection:
            await self._await_provider_authority_guarded(
                control_projection,
                authority_token=authority_token,
                event=event,
            )
        else:
            await self._await_browser_projection_best_effort(
                self._await_provider_authority_guarded(
                    control_projection,
                    authority_token=authority_token,
                    event=event,
                )
            )

    async def _cancel_voice_response_outside_lock(
        self,
        *,
        response_id: str,
        playback_epoch: int,
        expected_lifecycle: _VoiceResponseLifecycle,
    ) -> None:
        try:
            cancelled = bool(await self.provider.cancel_response())
        except Exception:
            cancelled = False
        async with self._state_lock:
            lifecycle = self._voice_response_lifecycles.get(response_id)
            if (
                lifecycle is not expected_lifecycle
                or lifecycle.playback_epoch != playback_epoch
                or not self._provider_token_current(lifecycle.authority_token)
            ):
                return
            if cancelled:
                self.state.provider_cancel_count += 1
                self.state.voice_cancel_count += 1
            else:
                self.state.voice_context_tainted = True
                self.state.voice_session_status = "degraded"
            await self._refresh_voice_suppression_counters()

    async def _cleanup_voice_response_outside_lock(
        self,
        *,
        response_id: str,
        expected_lifecycle: _VoiceResponseLifecycle,
    ) -> None:
        authority_token = expected_lifecycle.authority_token
        cleanup = getattr(self.provider, "cleanup_suppressed_response", None)
        cleanup_ok = False
        if callable(cleanup):
            try:
                cleanup_ok = bool(await cleanup(response_id))
            except Exception:
                cleanup_ok = False
        elif str(getattr(self.provider.profile, "output_mode", "degraded")) == "mock":
            # Provider-free fake cleanup is the in-memory discard itself.
            cleanup_ok = True

        # Cleanup crosses a provider await. Recheck the exact lifecycle and
        # immutable Voice authority before a stale completion can mutate the
        # replacement generation or schedule another rebuild. The real
        # enforced adapter exposes ``context_tainted``; legacy provider-free
        # fixtures without that projection retain their historical
        # cleanup-failure-means-tainted behavior.
        async with self._state_lock:
            lifecycle = self._voice_response_lifecycles.get(response_id)
            if (
                lifecycle is not expected_lifecycle
                or lifecycle.authority_token != authority_token
                or not self._provider_token_current(authority_token)
            ):
                return
            if cleanup_ok:
                lifecycle.cleanup_complete = True
                if str(getattr(self.provider.profile, "output_mode", "degraded")) == "mock":
                    self.state.voice_context_delete_count += 1
                self.state.voice_context_tainted = False
                self.state.voice_session_status = "connected"
                self._retire_voice_response_locked(response_id)
                await self._refresh_voice_suppression_counters()
                control_projection = self._send_control_state(output_mode="real")
                if bool(
                    getattr(self.provider, "enforced_output_suppression", False)
                ):
                    await self._await_browser_projection_best_effort(
                        control_projection
                    )
                else:
                    await control_projection
                return

            provider_context_tainted = getattr(
                self.provider, "context_tainted", None
            )
            if provider_context_tainted is False:
                return
            self.state.voice_context_tainted = True
            self.state.voice_session_status = "degraded"

        # Never hold the coordinator mutation lock across provider rebuild
        # I/O. The rebuild task owns the resulting state projection and
        # lifecycle retirement.
        await self._ensure_voice_rebuild_outside_lock()

    async def _voice_cancel_watchdog(
        self,
        *,
        response_id: str,
        expected_lifecycle: _VoiceResponseLifecycle,
    ) -> None:
        waiter = getattr(self.provider, "wait_for_cancel_terminal", None)
        provider_timeout_before = int(
            getattr(
                getattr(self.provider, "counters", None),
                "cancel_terminal_timeout_count",
                0,
            )
        )
        if callable(waiter):
            try:
                await waiter(
                    response_id,
                    timeout_seconds=self.config.voice_cancel_terminal_timeout_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            provider_timeout_after = int(
                getattr(
                    getattr(self.provider, "counters", None),
                    "cancel_terminal_timeout_count",
                    0,
                )
            )
            timed_out = provider_timeout_after > provider_timeout_before
        else:
            await asyncio.sleep(self.config.voice_cancel_terminal_timeout_seconds)
            timed_out = True
        if not timed_out:
            return
        async with self._state_lock:
            lifecycle = self._voice_response_lifecycles.get(response_id)
            if (
                lifecycle is not expected_lifecycle
                or lifecycle.terminal_status is not None
                or not self._provider_token_current(lifecycle.authority_token)
            ):
                return
            lifecycle.terminal_status = "timeout"
            lifecycle.output_eligible = False
            self._voice_cancel_terminal_timeout_count += 1
            self.state.voice_cancel_terminal_timeout_count = max(
                self.state.voice_cancel_terminal_timeout_count,
                self._voice_cancel_terminal_timeout_count,
            )
            self.state.voice_context_tainted = True
            self.state.voice_session_status = "degraded"
            if self._voice_active_response_id == response_id:
                self._voice_active_response_id = None
            await self._await_browser_projection_best_effort(
                self._timeline_best_effort(
                    "voice.cancel_terminal_timeout",
                    {
                        "safe_response_ref": f"voice-response-timeout-{len(self._voice_response_lifecycles):04d}",
                        "voice_cancel_terminal_timeout_count": self.state.voice_cancel_terminal_timeout_count,
                        "output_mode": "degraded",
                    },
                )
            )
        await self._ensure_voice_rebuild_outside_lock()
        async with self._state_lock:
            if (
                self._voice_response_lifecycles.get(response_id)
                is not expected_lifecycle
            ):
                return
            self._retire_voice_response_locked(response_id)
            await self._refresh_voice_suppression_counters()
            await self._await_browser_projection_best_effort(
                self._send_control_state(output_mode="degraded")
            )

    def _schedule_voice_rebuild(self) -> asyncio.Task[Any] | None:
        current = self._voice_rebuild_task
        if current is not None and not current.done():
            self._voice_rebuild_coalesced_count += 1
            self.state.voice_rebuild_coalesced_count = max(
                self.state.voice_rebuild_coalesced_count,
                self._voice_rebuild_coalesced_count,
            )
            return current
        # Fence ingress immediately, before the network rebuild coroutine can
        # run. Queued PCM belongs to the retired generation and is never
        # replayed into the replacement provider core.
        self._voice_generation_retired.set()
        self._voice_generation_retired = asyncio.Event()
        self._voice_rebuild_generation += 1
        self._voice_rebuild_attempted_generation = self._voice_rebuild_generation
        drained = self._drain_input_queue()
        for _ in range(drained):
            self._record_voice_rebuild_pcm_drop()
        current = self._spawn_background(
            self._perform_voice_rebuild_outside_lock(),
            name=(
                f"qfs-voice-rebuild-{self.session_id}-"
                f"{self._voice_rebuild_generation:04d}"
            ),
        )
        self._voice_rebuild_task = current
        return current

    async def _ensure_voice_rebuild_outside_lock(self) -> bool:
        task = self._schedule_voice_rebuild()
        if task is None:
            return False
        try:
            return bool(await asyncio.shield(task))
        except asyncio.CancelledError:
            raise
        except Exception:
            return False

    async def _perform_voice_rebuild_outside_lock(self) -> bool:
        rebuild = getattr(self.provider, "rebuild_if_tainted", None)
        rebuilt = False
        if callable(rebuild):
            try:
                rebuilt = bool(await rebuild())
            except asyncio.CancelledError:
                raise
            except Exception:
                rebuilt = False
        async with self._state_lock:
            if self._closed:
                return False
            if rebuilt:
                self.state.voice_context_tainted = False
                # The adapter increments its rebuild counter before this
                # coroutine reacquires the coordinator lock.  A concurrent
                # projection can therefore synchronize that value into state
                # first; incrementing again would double-count one physical
                # generation rotation.
                self.state.voice_context_rebuild_count = max(
                    self.state.voice_context_rebuild_count,
                    self._voice_rebuild_generation,
                )
                self.state.voice_session_status = "connected"
                self._voice_recovery_episode_code = None
                self._voice_session_ref = None
                for response_id in tuple(self._voice_response_lifecycles):
                    self._retire_voice_response_locked(response_id)
                for item_id in tuple(self._voice_input_item_turns):
                    self._retire_voice_input_item_locked(item_id)
                # Provider response/input identifiers are scoped to one
                # physical Voice generation.  The generation token is the ABA
                # fence; old tombstones must not reject a legitimate same-id
                # object created by the replacement session.
                self._voice_response_tombstones.clear()
                self._voice_response_tombstone_order.clear()
                self._voice_input_item_tombstones.clear()
                self._voice_input_item_tombstone_order.clear()
            else:
                self.state.voice_context_tainted = True
                self.state.voice_session_status = "degraded"
            await self._refresh_voice_suppression_counters()
            await self._await_browser_projection_best_effort(
                self._send_control_state(
                    output_mode="real" if rebuilt else "degraded"
                )
            )
        return rebuilt

    def _retire_voice_response_locked(self, response_id: str) -> None:
        lifecycle = self._voice_response_lifecycles.pop(response_id, None)
        self._voice_response_epochs.pop(response_id, None)
        self._voice_playback_started.discard(response_id)
        if self._voice_active_response_id == response_id:
            self._voice_active_response_id = None
        if lifecycle is not None:
            watchdog = lifecycle.watchdog_task
            current = asyncio.current_task()
            if watchdog is not None and watchdog is not current and not watchdog.done():
                watchdog.cancel()
        self._remember_bounded_tombstone(
            response_id,
            values=self._voice_response_tombstones,
            order=self._voice_response_tombstone_order,
        )

    def _retire_voice_input_item_locked(self, item_id: str) -> None:
        self._voice_input_item_turns.pop(item_id, None)
        self._remember_bounded_tombstone(
            item_id,
            values=self._voice_input_item_tombstones,
            order=self._voice_input_item_tombstone_order,
        )

    def _provider_ingress_generation(self) -> int | None:
        value = getattr(self.provider, "ingress_generation", None)
        if value is None:
            value = getattr(self.provider, "session_generation", None)
        if value is None:
            return self._voice_rebuild_generation if self.qwen_enforced else None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        return value

    def _voice_ingress_availability_code(self) -> str:
        if not self.qwen_enforced:
            return "available"
        if (
            self._voice_rebuild_task is not None
            and not self._voice_rebuild_task.done()
        ):
            return "voice_context_rebuilding"
        if self.state.voice_context_tainted:
            return "voice_context_tainted"
        if self.state.voice_session_status != "connected":
            return "voice_provider_not_connected"
        provider_code = getattr(self.provider, "ingress_availability_code", None)
        if provider_code in _VOICE_TRANSIENT_INGRESS_CODES:
            return str(provider_code)
        if provider_code == "voice_adapter_closed":
            return "voice_provider_not_connected"
        if self._provider_ingress_generation() is None:
            return "voice_provider_not_connected"
        return "available"

    @staticmethod
    def _voice_provider_error_code(error: Exception) -> str | None:
        code = getattr(error, "code", None)
        if not isinstance(code, str):
            return None
        if code == _VOICE_SEND_FAILURE_CODE or code in _VOICE_TRANSIENT_INGRESS_CODES:
            return code
        return None

    async def _notify_voice_recovery_once(self, code: str) -> None:
        safe_recovery_code = (
            code
            if code in _VOICE_TRANSIENT_INGRESS_CODES
            else "voice_provider_not_connected"
        )
        if self._voice_recovery_episode_code is not None:
            return
        self._voice_recovery_episode_code = safe_recovery_code
        await self._await_browser_projection_best_effort(
            self._send_json_best_effort(
                "degraded",
                degraded_code="voice_recovering",
                recovery_status="voice_recovering",
                recovery_code=safe_recovery_code,
                voice_rebuild_pcm_drop_count=(
                    self.state.voice_rebuild_pcm_drop_count
                ),
                output_mode="degraded",
            )
        )
        await self._await_browser_projection_best_effort(
            self._timeline_best_effort(
                "voice.recovery",
                {
                    "degraded_code": "voice_recovering",
                    "recovery_status": "voice_recovering",
                    "recovery_code": safe_recovery_code,
                    "voice_rebuild_pcm_drop_count": (
                        self.state.voice_rebuild_pcm_drop_count
                    ),
                    "output_mode": "degraded",
                },
            )
        )

    def _provider_event_generation_current(self, event: Any) -> bool:
        if not hasattr(self.provider, "ingress_generation"):
            return True
        current = self._provider_ingress_generation()
        event_generation = getattr(event, "session_generation", None)
        return bool(
            current is not None
            and isinstance(event_generation, int)
            and not isinstance(event_generation, bool)
            and event_generation == current
        )

    def _capture_provider_authority(
        self, event: Any
    ) -> _ProviderAuthorityToken | None:
        if not self.qwen_enforced:
            return None
        if not (
            hasattr(self.provider, "ingress_generation")
            or hasattr(self.provider, "session_generation")
        ):
            return None
        provider_generation = self._provider_ingress_generation()
        if provider_generation is None:
            return None
        event_generation = getattr(event, "session_generation", None)
        session_ref = getattr(event, "session_ref", None)
        if (
            not isinstance(event_generation, int)
            or isinstance(event_generation, bool)
            or event_generation != provider_generation
            or not isinstance(session_ref, str)
            or not session_ref
        ):
            return None
        return _ProviderAuthorityToken(
            provider_generation=provider_generation,
            coordinator_generation=self._voice_rebuild_generation,
            session_ref=session_ref,
            retirement_event=self._voice_generation_retired,
        )

    def _provider_token_current(
        self,
        token: _ProviderAuthorityToken | None,
    ) -> bool:
        if not self.qwen_enforced:
            return True
        if token is None:
            return not (
                hasattr(self.provider, "ingress_generation")
                or hasattr(self.provider, "session_generation")
            )
        if token.retirement_event.is_set():
            return False
        if token.coordinator_generation != self._voice_rebuild_generation:
            return False
        current_provider_generation = self._provider_ingress_generation()
        if token.provider_generation != current_provider_generation:
            return False
        if (
            isinstance(self._voice_session_ref, str)
            and self._voice_session_ref
            and token.session_ref != self._voice_session_ref
        ):
            return False
        return True

    def _provider_authority_current(
        self,
        token: _ProviderAuthorityToken | None,
        event: Any,
    ) -> bool:
        if not self._provider_token_current(token):
            return False
        if token is None:
            return True
        event_generation = getattr(event, "session_generation", None)
        if (
            not isinstance(event_generation, int)
            or isinstance(event_generation, bool)
            or event_generation != token.provider_generation
        ):
            return False
        event_session_ref = getattr(event, "session_ref", None)
        if (
            not isinstance(event_session_ref, str)
            or not event_session_ref
            or event_session_ref != token.session_ref
        ):
            return False
        return True

    def _committed_control_authority_current(
        self,
        token: _CommittedTurnAuthority | None,
        turn: _TurnContext,
    ) -> bool:
        """Validate local committed-turn authority without Voice generation.

        Provider authority is required through the canonical final ASR append.
        After that boundary, cleanup-only Voice rebuilds must not revoke an
        already committed Control request.  New speech, explicit interrupt,
        a newer committed turn, disconnect, or correlation mismatch still
        retires the local authority.
        """

        if not self.qwen_enforced:
            return True
        if self._closed or self.state.disconnect_requested or token is None:
            return False
        if token.session_id != self.session_id:
            return False
        if token.conversation_id != self.conversation_id:
            return False
        if token.turn_id != turn.turn_id or token.utterance_id != turn.utterance_id:
            return False
        if token.playback_epoch != turn.playback_epoch:
            return False
        if token.playback_epoch != self.state.playback_epoch:
            return False
        if self._latest_shadow_turn_id != turn.turn_id:
            return False
        if turn.committed_control_authority != token:
            return False
        asr_event = turn.asr_frame_event
        if asr_event is None:
            return False
        return bool(
            asr_event.get("event_id") == token.asr_event_id
            and asr_event.get("asr_frame_ref") == token.asr_frame_ref
            and asr_event.get("turn_id") == token.turn_id
            and asr_event.get("utterance_id") == token.utterance_id
        )

    def _discard_stale_provider_authority(self) -> None:
        """Record a content-free late discard without journal/UI projection."""

        self.state.discarded_late_audio_frames += 1
        self.state.stale_provider_event_discard_count += 1

    async def _send_json_authority_guarded(
        self,
        message_type: str,
        *,
        authority_token: _ProviderAuthorityToken,
        event: Any,
        **fields: Any,
    ) -> bool:
        """Cancel a blocked browser projection when its generation retires."""

        return await self._await_provider_authority_guarded(
            self._send_json(message_type, **fields),
            authority_token=authority_token,
            event=event,
        )

    async def _await_provider_authority_guarded(
        self,
        awaitable: Awaitable[Any],
        *,
        authority_token: _ProviderAuthorityToken,
        event: Any,
    ) -> bool:
        """Cancel any blocked provider-originated projection on retirement."""

        if not self._provider_authority_current(authority_token, event):
            if hasattr(awaitable, "close"):
                awaitable.close()  # type: ignore[union-attr]
            self._discard_stale_provider_authority()
            return False
        send_task = asyncio.create_task(awaitable)
        retired_task = asyncio.create_task(authority_token.retirement_event.wait())
        try:
            while not send_task.done():
                if not self._provider_authority_current(authority_token, event):
                    send_task.cancel()
                    await asyncio.gather(send_task, return_exceptions=True)
                    self._discard_stale_provider_authority()
                    return False
                await asyncio.wait(
                    (send_task, retired_task),
                    timeout=0.002,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            if not self._provider_authority_current(authority_token, event):
                self._discard_stale_provider_authority()
                return False
            await send_task
            return True
        finally:
            if not retired_task.done():
                retired_task.cancel()
            await asyncio.gather(retired_task, return_exceptions=True)

    def _record_voice_rebuild_pcm_drop(self) -> None:
        self._voice_rebuild_pcm_drop_count += 1
        self.state.voice_rebuild_pcm_drop_count = max(
            self.state.voice_rebuild_pcm_drop_count,
            self._voice_rebuild_pcm_drop_count,
        )

    async def _on_shadow_voice_response_created(self, event: Any) -> None:
        response_id = getattr(event, "response_id", None)
        if (
            not isinstance(response_id, str)
            or not response_id
            or response_id in self._voice_response_epochs
            or response_id in self._voice_response_tombstones
        ):
            await self.report_safe_error("voice_response_correlation_incomplete")
            return
        if self._voice_active_response_id is not None:
            # A second response must own a fresh playback generation.  The
            # provider documents one active response at a time, so overlap is
            # treated conservatively and the older response becomes stale.
            await self._clear_voice_playback(reason="voice_response_replaced")
        self._voice_response_epochs[response_id] = self.state.playback_epoch
        self._voice_active_response_id = response_id
        self._voice_playback_started.add(response_id)
        self.state.status = "RESPONDING"
        await self._send_json(
            "playback.begin",
            playback_epoch=self.state.playback_epoch,
            response_id=response_id,
            playback_span_id=f"voice_playback_{self._slug}_{self.state.playback_epoch}",
            sample_rate=24_000,
            channels=1,
            source="qwen_voice_session_shadow_ux",
            output_mode=str(getattr(event, "output_mode", "degraded")),
        )

    async def _on_shadow_voice_transcript(self, event: Any, *, final: bool) -> None:
        response_id = getattr(event, "response_id", None)
        if not self._voice_response_is_current(response_id):
            return
        turn = self._current_turn
        await self._send_json(
            "transcript.assistant.done" if final else "transcript.assistant.delta",
            text=getattr(event, "text", None) or "",
            turn_id=turn.turn_id if turn is not None else None,
            utterance_id=turn.utterance_id if turn is not None else None,
            response_id=response_id,
            source="qwen_voice_session",
            output_mode=str(getattr(event, "output_mode", "degraded")),
        )

    async def _on_shadow_voice_audio(self, event: Any) -> None:
        response_id = getattr(event, "response_id", None)
        audio = getattr(event, "audio", None)
        expected_mode = "qwen" if self.provider_mode == "qwen" else "fake_pcm"
        if not self.state.playback_enabled or self.audio_output != expected_mode:
            return
        if (
            not isinstance(audio, bytes)
            or not audio
            or not self._voice_response_is_current(response_id)
        ):
            self.state.discarded_late_audio_frames += 1
            await self._send_flow()
            return
        await self.browser_sink.send_bytes(pack_output_audio(self.state.playback_epoch, audio))
        self._active_playback_offset_ms += _pcm_duration_ms(audio, sample_rate=24_000)

    async def _on_shadow_voice_response_done(self, event: Any) -> None:
        response_id = getattr(event, "response_id", None)
        if not isinstance(response_id, str):
            return
        epoch = self._voice_response_epochs.get(response_id)
        if epoch != self.state.playback_epoch or response_id != self._voice_active_response_id:
            return
        self._voice_active_response_id = None
        self.state.status = "LISTENING"
        await self._send_json(
            "playback.end",
            playback_epoch=epoch,
            response_id=response_id,
            playback_span_id=f"voice_playback_{self._slug}_{epoch}",
            status=str(getattr(event, "status", None) or "unknown"),
            source="qwen_voice_session_shadow_ux",
        )
        await self._send_state("voice_response_done")
        self._retire_voice_response_locked(response_id)

    async def _enqueue_shadow_request(
        self,
        *,
        turn: _TurnContext,
        transcript: str,
        asr_final_monotonic_ms: int,
    ) -> bool:
        """Queue one locally bound final transcript for non-authoritative analysis."""

        committed_authority = turn.committed_control_authority
        if self.qwen_enforced and committed_authority is None:
            return False
        if turn.turn_id in self._shadow_requested_turn_ids:
            return False
        self._shadow_requested_turn_ids.add(turn.turn_id)
        if len(self._shadow_requested_turn_ids) > 64:
            # The set is only a duplicate fence; correlation for live work is
            # carried by the bounded queue and ``_latest_shadow_turn_id``.
            self._shadow_requested_turn_ids = {turn.turn_id}
        self._latest_shadow_turn_id = turn.turn_id
        snapshot = self._router_context().task_focus_snapshot
        task_context = {
            "active_task_id": snapshot.active_task_id,
            "lifecycle_phase": snapshot.lifecycle_phase,
            "terminal_status": snapshot.terminal_status,
            "current_plan_version": snapshot.current_plan_version,
            "pending_confirmation_scope": snapshot.pending_confirmation_scope,
            "has_active_non_terminal_task": snapshot.has_active_non_terminal_task,
            "side_conversation_allowed": True,
            "default_patch_policy": (
                "ACTIVE_TASK_PATCH_ONLY"
                if snapshot.has_active_non_terminal_task
                else "NO_ACTIVE_TASK"
            ),
            "ambiguous_input_policy": "CLARIFY",
        }
        asr_frame_ref = (
            str(turn.asr_frame_event.get("asr_frame_ref"))
            if turn.asr_frame_event is not None
            else f"asr-frame://experiment/qfs-shadow/{turn.index}"
        )
        try:
            request = ShadowRouteRequest(
                request_id=f"shadow_req_{self._slug}_{turn.index:04d}",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                asr_frame_ref=asr_frame_ref,
                transcript=transcript,
                task_focus_snapshot=task_context,
                asr_final_monotonic_ms=float(asr_final_monotonic_ms),
            )
        except ValueError as error:
            if self.qwen_enforced:
                await self._commit_fail_closed_turn(
                    turn,
                    code=str(error),
                    assistant_directed=bool(transcript.strip()),
                )
            else:
                await self._emit_shadow_degraded(
                    code=str(error),
                    safe_turn_ref=f"shadow-turn-unavailable-{turn.index:04d}",
                )
            return
        envelope = _ShadowRequestEnvelope(
            request=request,
            turn=turn,
            task_focus_snapshot=snapshot,
            safe_turn_ref=request.safe_turn_ref,
            asr_final_monotonic_ms=asr_final_monotonic_ms,
            playback_epoch=turn.playback_epoch,
            final_transcript_nonempty=bool(transcript.strip()),
            task_identity_ref=(
                str(request.task_focus_snapshot["active_task_ref"])
                if isinstance(
                    request.task_focus_snapshot.get("active_task_ref"), str
                )
                else None
            ),
            pending_confirmation_id=(
                self.state.active_task.pending_confirmation_id
                if self.state.active_task is not None
                and self.state.active_task.task_id == snapshot.active_task_id
                else None
            ),
            pending_confirmation_scope=snapshot.pending_confirmation_scope,
            requested_plan_version=snapshot.current_plan_version,
            requested_task_event_seq=(
                self.state.active_task.task_event_seq
                if self.state.active_task is not None
                and self.state.active_task.task_id == snapshot.active_task_id
                else None
            ),
            committed_control_authority=committed_authority,
        )
        if self._shadow_request_queue.full():
            try:
                dropped = self._shadow_request_queue.get_nowait()
                self._shadow_request_queue.task_done()
                self._shadow_queue_drop_count += 1
                self.state.shadow_drop_count += 1
                if self.qwen_enforced:
                    self._record_shadow_late_discard()
                await self._timeline(
                    (
                        "route.control.degraded"
                        if self.qwen_enforced
                        else "route.shadow.degraded"
                    ),
                    {
                        "safe_turn_ref": dropped.safe_turn_ref,
                        "degraded_code": "shadow_request_queue_dropped",
                        "routing_mode": self.routing_mode,
                        "output_mode": "degraded",
                    },
                )
            except asyncio.QueueEmpty:
                pass
        if not self._committed_control_authority_current(
            committed_authority,
            turn,
        ):
            self._shadow_requested_turn_ids.discard(turn.turn_id)
            return False
        self._shadow_request_queue.put_nowait(envelope)
        await self._refresh_shadow_counters()
        if not self._committed_control_authority_current(
            committed_authority,
            turn,
        ):
            # The worker independently validates local committed authority
            # before Control ingress.  Do not project superseded state here.
            return False
        if self.qwen_enforced:
            await self._send_control_state(output_mode=self._last_shadow_output_mode)
        else:
            await self._send_shadow_state(output_mode=self._last_shadow_output_mode)
        return True

    async def _shadow_request_worker(self) -> None:
        """Serialize control requests; failures never cancel the Voice Session."""

        try:
            while not self._closed:
                envelope = await self._shadow_request_queue.get()
                try:
                    if (
                        self.qwen_enforced
                        and not self._committed_control_authority_current(
                            envelope.committed_control_authority,
                            envelope.turn,
                        )
                    ):
                        await self._discard_late_enforced_result(
                            envelope.turn,
                            code="control_request_superseded",
                        )
                        continue
                    if envelope.turn.turn_id != self._latest_shadow_turn_id:
                        self._record_shadow_late_discard()
                        await self._timeline(
                            (
                                "route.control.degraded"
                                if self.qwen_enforced
                                else "route.shadow.degraded"
                            ),
                            {
                                "safe_turn_ref": envelope.safe_turn_ref,
                                "degraded_code": "shadow_request_superseded",
                                "routing_mode": self.routing_mode,
                                "output_mode": "degraded",
                            },
                        )
                        continue
                    if self.shadow_provider is None:
                        result = ShadowRouteResult.degraded(
                            envelope.request,
                            "shadow_control_unavailable",
                            output_mode="degraded",
                        )
                    else:
                        if not self._shadow_available:
                            try:
                                await self.shadow_provider.connect()
                                self._shadow_available = True
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                self._shadow_local_error_count += 1
                        if (
                            self.qwen_enforced
                            and not self._committed_control_authority_current(
                                envelope.committed_control_authority,
                                envelope.turn,
                            )
                        ):
                            await self._discard_late_enforced_result(
                                envelope.turn,
                                code="control_request_superseded",
                            )
                            continue
                        if not self._shadow_available:
                            result = ShadowRouteResult.degraded(
                                envelope.request,
                                "shadow_control_unavailable",
                                output_mode="degraded",
                            )
                        else:
                            try:
                                result = await self.shadow_provider.analyze(
                                    envelope.request,
                                    timeout_seconds=(
                                        self.config.shadow_request_timeout_seconds
                                    ),
                                )
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                self._shadow_local_error_count += 1
                                result = ShadowRouteResult.degraded(
                                    envelope.request,
                                    "shadow_control_request_failed",
                                    output_mode="degraded",
                                    context_tainted=True,
                                )
                    async with self._state_lock:
                        if (
                            self.qwen_enforced
                            and not self._committed_control_authority_current(
                                envelope.committed_control_authority,
                                envelope.turn,
                            )
                        ):
                            await self._discard_late_enforced_result(
                                envelope.turn,
                                code="control_request_superseded",
                            )
                            continue
                        if not isinstance(result, ShadowRouteResult):
                            self._shadow_local_error_count += 1
                            result = ShadowRouteResult.degraded(
                                envelope.request,
                                "control_result_type_invalid",
                                output_mode="degraded",
                                context_tainted=True,
                            )
                        provider_session_state = str(
                            getattr(self.shadow_provider, "session_state", "degraded")
                        )
                        self._shadow_available = provider_session_state in {
                            "connected",
                            "degraded",
                        }
                        if (
                            result.request_id != envelope.request.request_id
                            or result.turn_id != envelope.turn.turn_id
                            or result.utterance_id != envelope.turn.utterance_id
                        ):
                            self._shadow_local_error_count += 1
                            if self.qwen_enforced:
                                await self._commit_fail_closed_turn(
                                    envelope.turn,
                                    code="control_result_correlation_invalid",
                                    assistant_directed=envelope.final_transcript_nonempty,
                                )
                            else:
                                await self._emit_shadow_degraded(
                                    code="shadow_result_correlation_invalid",
                                    safe_turn_ref=envelope.safe_turn_ref,
                                )
                            continue
                        if (
                            result.turn_id != self._latest_shadow_turn_id
                            or (
                                self.qwen_enforced
                                and envelope.playback_epoch != self.state.playback_epoch
                            )
                        ):
                            self._record_shadow_late_discard()
                            await self._timeline(
                                (
                                    "route.control.degraded"
                                    if self.qwen_enforced
                                    else "route.shadow.degraded"
                                ),
                                {
                                    "safe_turn_ref": result.safe_turn_ref,
                                    "degraded_code": "shadow_late_result_discarded",
                                    "routing_mode": self.routing_mode,
                                    "output_mode": "degraded",
                                },
                            )
                            continue
                        if self.qwen_enforced:
                            await self._consume_enforced_result(envelope, result)
                        else:
                            await self._consume_shadow_result(envelope, result)
                    # Rebuild is a network operation and therefore happens
                    # outside the coordinator mutation lock. Voice events can
                    # continue while only the control connection is replaced.
                    await self._rebuild_shadow_if_tainted()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # One malformed result or local handler defect must not
                    # kill the serialized worker or leave queue.join blocked.
                    # Exception text is intentionally not projected.
                    self._shadow_local_error_count += 1
                    async with self._state_lock:
                        if self.qwen_enforced:
                            if self._committed_control_authority_current(
                                envelope.committed_control_authority,
                                envelope.turn,
                            ):
                                await self._commit_fail_closed_turn(
                                    envelope.turn,
                                    code="control_worker_request_failed",
                                    assistant_directed=(
                                        envelope.final_transcript_nonempty
                                    ),
                                )
                            else:
                                await self._discard_late_enforced_result(
                                    envelope.turn,
                                    code="control_worker_request_superseded",
                                )
                        else:
                            await self._emit_shadow_degraded(
                                code="shadow_worker_request_failed",
                                safe_turn_ref=envelope.safe_turn_ref,
                            )
                finally:
                    self._shadow_request_queue.task_done()
        except asyncio.CancelledError:
            raise

    async def _consume_shadow_result(
        self,
        envelope: _ShadowRequestEnvelope,
        result: ShadowRouteResult,
    ) -> None:
        self.state.safe_turn_ref = result.safe_turn_ref
        self.state.context_tainted = bool(result.context_tainted)
        self.state.context_delete_count = int(result.context_delete_count)
        self.state.context_rebuild_count = int(result.context_rebuild_count)
        self.state.asr_to_shadow_request_ms = (
            result.latency.asr_final_to_request_ms
        )
        self.state.shadow_request_to_first_delta_ms = (
            result.latency.request_to_function_call_first_delta_ms
        )
        self.state.shadow_request_to_done_ms = (
            result.latency.request_to_function_call_done_ms
        )
        self.state.function_done_to_local_router_ms = (
            result.latency.function_call_done_to_result_ms
        )
        self._last_shadow_output_mode = str(result.output_mode)
        await self._refresh_shadow_counters()

        if not result.schema_valid or result.proposal is None:
            await self._emit_shadow_degraded(
                code=result.degraded_code or "shadow_proposal_not_available",
                safe_turn_ref=result.safe_turn_ref,
                schema_invalid=True,
            )
            return

        proposal = result.proposal
        self.state.qwen_task_focus_hint = proposal.task_focus_hint
        self.state.qwen_route_hint = proposal.route_decision_hint
        self.state.shadow_foreground_act = proposal.foreground_act
        self.state.shadow_risk_class = proposal.risk_class
        self.state.shadow_confidence = float(proposal.confidence)
        self.state.schema_status = "valid"
        proposed_fields = {
            "provider_mode": self.provider_mode,
            "routing_mode": "shadow",
            "safe_turn_ref": result.safe_turn_ref,
            "qwen_task_focus_hint": proposal.task_focus_hint,
            "qwen_route_hint": proposal.route_decision_hint,
            "foreground_act": proposal.foreground_act,
            "risk_class": proposal.risk_class,
            "confidence": float(proposal.confidence),
            "proposal_available": True,
            "output_mode": result.output_mode,
        }
        await self._send_json("route.shadow.proposed", **proposed_fields)
        await self._timeline("route.shadow.proposed", proposed_fields)
        validated_fields = {
            **proposed_fields,
            "schema_status": "valid",
        }
        await self._send_json("route.shadow.validated", **validated_fields)
        await self._timeline("route.shadow.validated", validated_fields)

        try:
            evaluation = self._shadow_evaluator.evaluate(
                proposal=proposal,
                turn_id=envelope.turn.turn_id,
                utterance_id=envelope.turn.utterance_id,
                audio_span_id=envelope.turn.audio_span_id,
                asr_frame_ref=str(envelope.request.asr_frame_ref),
                task_focus_snapshot=envelope.task_focus_snapshot,
                output_mode=result.output_mode,
            )
        except Exception:
            self._shadow_local_error_count += 1
            await self._emit_shadow_degraded(
                code="shadow_local_router_evaluation_failed",
                safe_turn_ref=result.safe_turn_ref,
                schema_status="valid",
                preserve_proposal=True,
            )
            return
        self.state.local_router_decision = evaluation.local_router_decision
        self.state.local_task_focus = evaluation.local_task_focus
        self.state.local_foreground_act = evaluation.local_foreground_act
        self.state.agreement = evaluation.agreement
        provider_done_to_result = result.latency.function_call_done_to_result_ms or 0.0
        self.state.function_done_to_local_router_ms = round(
            provider_done_to_result + evaluation.evaluation_latency_ms, 3
        )
        compared_fields = {
            **proposed_fields,
            **evaluation.to_metadata(),
            "function_done_to_local_router_ms": (
                self.state.function_done_to_local_router_ms
            ),
            "active_task_present": (
                envelope.task_focus_snapshot.has_active_non_terminal_task
            ),
            "pending_confirmation_present": bool(
                envelope.task_focus_snapshot.pending_confirmation_scope
            ),
            "schema_status": "valid",
        }
        await self._send_json("route.shadow.compared", **compared_fields)
        await self._timeline("route.shadow.compared", compared_fields)
        self.state.shadow_control_session_status = (
            "degraded" if result.context_tainted or result.degraded_code else "connected"
        )
        await self._send_shadow_state(output_mode=result.output_mode)

    async def _consume_enforced_result(
        self,
        envelope: _ShadowRequestEnvelope,
        result: ShadowRouteResult,
    ) -> None:
        """Normalize provider evidence, then run the authoritative local chain."""

        if envelope.turn.turn_id in self._enforced_terminal_turn_ids:
            await self._discard_late_enforced_result(
                envelope.turn, code="control_result_after_terminal"
            )
            return

        self.state.safe_turn_ref = result.safe_turn_ref
        self.state.context_tainted = bool(result.context_tainted)
        self.state.context_delete_count = int(result.context_delete_count)
        self.state.context_rebuild_count = int(result.context_rebuild_count)
        self.state.asr_to_shadow_request_ms = result.latency.asr_final_to_request_ms
        self.state.shadow_request_to_first_delta_ms = (
            result.latency.request_to_function_call_first_delta_ms
        )
        self.state.shadow_request_to_done_ms = (
            result.latency.request_to_function_call_done_ms
        )
        self.state.function_done_to_local_router_ms = (
            result.latency.function_call_done_to_result_ms
        )
        self._last_shadow_output_mode = str(result.output_mode)
        await self._refresh_shadow_counters()
        if not self._committed_control_authority_current(
            envelope.committed_control_authority,
            envelope.turn,
        ):
            await self._discard_late_enforced_result(
                envelope.turn,
                code="control_result_superseded_before_route",
            )
            return
        if (
            result.context_tainted
            or not result.schema_valid
            or result.proposal is None
        ):
            await self._commit_fail_closed_turn(
                envelope.turn,
                code=result.degraded_code or "control_proposal_not_available",
                assistant_directed=envelope.final_transcript_nonempty,
            )
            return

        proposal = result.proposal
        try:
            normalized = ProviderRouteProposal(
                scenario="qwen_enforced_control",
                response_id=result.request_id,
                provider_item_id=f"control_item_{envelope.turn.index:04d}",
                route_hint=proposal.route_decision_hint,
                task_focus_hint=proposal.task_focus_hint,
                foreground_act=proposal.foreground_act,
                risk_class=proposal.risk_class,
                confidence=float(proposal.confidence),
                output_mode=result.output_mode,
                task_like=bool(proposal.task_like),
                complexity_hint=proposal.complexity_hint,
                evidence_uncertainty=proposal.evidence_uncertainty,
                risk_tags=tuple(proposal.risk_tags),
                reply_candidate_text=proposal.reply_candidate_text,
            )
        except ValueError:
            await self._commit_fail_closed_turn(
                envelope.turn,
                code="control_proposal_normalization_failed",
                assistant_directed=envelope.final_transcript_nonempty,
            )
            return

        self.state.qwen_task_focus_hint = normalized.task_focus_hint
        self.state.qwen_route_hint = normalized.route_hint
        self.state.shadow_foreground_act = normalized.foreground_act
        self.state.shadow_risk_class = normalized.risk_class
        self.state.shadow_confidence = normalized.confidence
        self.state.schema_status = "valid"
        proposed_fields = {
            "provider_mode": "qwen",
            "routing_mode": "enforced",
            "safe_turn_ref": result.safe_turn_ref,
            "qwen_task_focus_hint": normalized.task_focus_hint,
            "qwen_route_hint": normalized.route_hint,
            "foreground_act": normalized.foreground_act,
            "risk_class": normalized.risk_class,
            "confidence": normalized.confidence,
            "proposal_available": True,
            "schema_status": "valid",
            "output_mode": result.output_mode,
        }
        await self._send_json("route.proposed", **proposed_fields)
        if not self._committed_control_authority_current(
            envelope.committed_control_authority,
            envelope.turn,
        ):
            await self._discard_late_enforced_result(
                envelope.turn,
                code="control_result_superseded_after_projection",
            )
            return
        await self._timeline("route.control.proposed", proposed_fields)
        if not self._committed_control_authority_current(
            envelope.committed_control_authority,
            envelope.turn,
        ):
            await self._discard_late_enforced_result(
                envelope.turn,
                code="control_result_superseded_before_route",
            )
            return
        await self._route_and_gate_enforced(
            envelope,
            normalized,
            confirmation_signal_hint=str(proposal.confirmation_signal_hint),
        )

    async def _route_and_gate_enforced(
        self,
        envelope: _ShadowRequestEnvelope,
        provider_proposal: ProviderRouteProposal,
        *,
        confirmation_signal_hint: str,
    ) -> None:
        turn = envelope.turn
        if not self._committed_control_authority_current(
            envelope.committed_control_authority,
            turn,
        ):
            await self._discard_late_enforced_result(
                turn,
                code="control_route_authority_retired",
            )
            return
        if turn.authority.claimed or turn.turn_id in self._enforced_terminal_turn_ids:
            await self._discard_late_enforced_result(
                turn, code="control_route_after_terminal"
            )
            return
        if turn.turn_committed_event is None or turn.asr_frame_event is None:
            await self._commit_fail_closed_turn(
                turn,
                code="control_route_evidence_incomplete",
                assistant_directed=envelope.final_transcript_nonempty,
            )
            return
        if (
            turn.turn_id != self._latest_shadow_turn_id
            or envelope.playback_epoch != self.state.playback_epoch
        ):
            await self._commit_fail_closed_turn(
                turn,
                code="control_turn_epoch_stale",
                assistant_directed=envelope.final_transcript_nonempty,
            )
            return

        current_snapshot = self._router_context().task_focus_snapshot
        active_task = self.state.active_task
        current_confirmation_id = (
            active_task.pending_confirmation_id
            if active_task is not None
            and active_task.task_id == current_snapshot.active_task_id
            else None
        )
        task_identity_changed = (
            current_snapshot.active_task_id
            != envelope.task_focus_snapshot.active_task_id
            or current_snapshot.has_active_non_terminal_task
            != envelope.task_focus_snapshot.has_active_non_terminal_task
        )
        confirmation_binding_changed = (
            current_snapshot.pending_confirmation_scope
            != envelope.pending_confirmation_scope
            or current_confirmation_id != envelope.pending_confirmation_id
        )
        explicit_confirmation = confirmation_signal_hint in {"ACCEPT", "REJECT"}
        confirmation_plan_stale = bool(
            explicit_confirmation
            and current_snapshot.current_plan_version
            != envelope.requested_plan_version
        )
        confirmation_sequence_stale = bool(
            explicit_confirmation
            and active_task is not None
            and active_task.task_event_seq != envelope.requested_task_event_seq
        )
        orphan_confirmation = bool(
            explicit_confirmation
            and (
                current_confirmation_id is None
                or current_snapshot.pending_confirmation_scope is None
            )
        )
        if (
            task_identity_changed
            or confirmation_binding_changed
            or confirmation_plan_stale
            or confirmation_sequence_stale
            or orphan_confirmation
        ):
            await self._commit_fail_closed_turn(
                turn,
                code=(
                    "control_task_identity_changed"
                    if task_identity_changed
                    else (
                        "control_confirmation_binding_changed"
                        if confirmation_binding_changed
                        else (
                            "control_confirmation_plan_version_stale"
                            if confirmation_plan_stale
                            else (
                                "control_confirmation_task_event_seq_stale"
                                if confirmation_sequence_stale
                                else "control_confirmation_orphan"
                            )
                        )
                    )
                ),
                assistant_directed=envelope.final_transcript_nonempty,
            )
            return

        effective_confirmation_signal = confirmation_signal_hint
        if explicit_confirmation and (
            provider_proposal.task_focus_hint in {"NON_ASSISTANT", "AMBIGUOUS"}
            or provider_proposal.route_hint == "IGNORE"
            or provider_proposal.confidence
            < float(self.config.gate_confidence_threshold)
            or provider_proposal.evidence_uncertainty == "HIGH"
        ):
            effective_confirmation_signal = "AMBIGUOUS"

        if not self._claim_enforced_terminal(turn):
            await self._discard_late_enforced_result(
                turn, code="control_terminal_claim_lost"
            )
            return
        try:
            await self._route_and_gate_enforced_claimed(
                envelope,
                provider_proposal,
                confirmation_signal_hint=effective_confirmation_signal,
                current_snapshot=current_snapshot,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._commit_fail_closed_turn(
                turn,
                code="control_authoritative_dispatch_failed",
                assistant_directed=envelope.final_transcript_nonempty,
            )

    async def _route_and_gate_enforced_claimed(
        self,
        envelope: _ShadowRequestEnvelope,
        provider_proposal: ProviderRouteProposal,
        *,
        confirmation_signal_hint: str,
        current_snapshot: TaskFocusSnapshot,
    ) -> None:
        turn = envelope.turn
        effective_proposal = provider_proposal
        active_task = self.state.active_task
        if (
            active_task is not None
            and active_task.active_non_terminal
            and active_task.pending_confirmation_scope is not None
        ):
            if confirmation_signal_hint in {"ACCEPT", "REJECT"}:
                effective_proposal = provider_proposal.with_local_focus_override(
                    route_hint="PATCH_ACTIVE_SLOW_TASK",
                    task_focus_hint="ACTIVE_TASK_PATCH",
                )
            elif provider_proposal.task_focus_hint == "NON_ASSISTANT" or (
                provider_proposal.route_hint == "IGNORE"
            ):
                effective_proposal = provider_proposal
            else:
                # Ambiguous, missing and ordinary task-patch proposals cannot
                # consume a pending confirmation.  Keep it pending and use a
                # controlled local clarification with no UserPatch mutation.
                effective_proposal = provider_proposal.with_local_focus_override(
                    route_hint="FAST_ONLY",
                    task_focus_hint="AMBIGUOUS",
                )

        self.state.stale_status = (
            "re_evaluated_same_task_plan_advanced"
            if (
                current_snapshot.active_task_id
                == envelope.task_focus_snapshot.active_task_id
                and current_snapshot.current_plan_version
                != envelope.requested_plan_version
            )
            else (
                "re_evaluated_current_state"
                if current_snapshot != envelope.task_focus_snapshot
                else "current"
            )
        )
        route_started = time.monotonic()
        now_mono, now_wall = _now_ms()
        safe_turn = f"{self._slug}_{turn.index:04d}"
        try:
            binding = FastInteractionBinding.from_turn_and_asr_fallback(
                turn.turn_committed_event,
                asr_output_event=turn.asr_frame_event,
                adapter_request_id=f"control_fast_request_{safe_turn}",
            )
            provider_has_candidate = effective_proposal.reply_candidate_text is not None
            try:
                local_candidate_template = get_foreground_template(
                    router_decision=effective_proposal.route_hint,
                    output_basis="template_clarify",
                )
            except ValueError:
                local_candidate_template = get_foreground_template(
                    router_decision="FAST_ONLY",
                    output_basis="template_clarify",
                )
            fast_output = FastInteractionOutput(
                adapter_id="qfs_qwen_enforced_control_fast_interaction_v1",
                route_hint_ref=f"route-hint://experiment/qfs-control/{safe_turn}",
                route_prelude_ref=f"route-prelude://experiment/qfs-control/{safe_turn}",
                foreground_act=effective_proposal.foreground_act,
                final_fast_evidence_ref=f"fast-evidence://experiment/qfs-control/{safe_turn}",
                risk_tags=effective_proposal.risk_tags or ("provider_evidence",),
                risk_class=effective_proposal.risk_class,
                confidence=effective_proposal.confidence,
                output_mode=effective_proposal.output_mode,
                reply_candidate_ref=(
                    f"reply-candidate://transient/qfs-control/{safe_turn}"
                    if provider_has_candidate
                    else local_candidate_template.template_ref
                ),
                candidate_id=(
                    f"control_candidate_{safe_turn}"
                    if provider_has_candidate
                    else f"local_template_candidate_{safe_turn}"
                ),
                route_decision_hint=effective_proposal.route_hint,
                task_focus_hint=effective_proposal.task_focus_hint,
            )
            emission = emit_fast_interaction_events(
                boundary=self._callback_boundary,
                binding=binding,
                output=fast_output,
                output_event_id=self._next_event_id("control_fast_interaction_output"),
                candidate_event_id=self._next_event_id(
                    "control_foreground_candidate"
                    if provider_has_candidate
                    else "control_local_template_candidate"
                ),
                created_monotonic_ms=now_mono,
                created_wall_clock_ms=now_wall,
                source_module="qwen_enforced_control_fast_interaction_adapter",
            )
            turn.authority.fast_interaction_output_event = dict(emission.output_event)
            turn.authority.candidate_event = (
                dict(emission.candidate_event)
                if emission.candidate_event is not None
                else None
            )
            router_evidence = dict(emission.output_event)
            router_evidence["task_like"] = effective_proposal.task_like
            router_evidence["complexity_hint"] = (
                "complex"
                if effective_proposal.complexity_hint in {"MEDIUM", "HIGH"}
                else "low"
            )
            router_evidence["evidence_uncertainty"] = (
                effective_proposal.evidence_uncertainty.lower()
            )
            router_result = self._router.emit_decision(
                turn_committed_event=turn.turn_committed_event,
                asr_frame_event=turn.asr_frame_event,
                fast_interaction_output_event=router_evidence,
                router_context=RouterContext(task_focus_snapshot=current_snapshot),
                event_id=self._next_event_id("control_router_decision"),
                task_focus_state_event_id=self._next_event_id("control_task_focus_state"),
                created_monotonic_ms=now_mono + 2,
                created_wall_clock_ms=now_wall + 2,
            )
            turn.authority.router_decision_event = dict(
                router_result.router_decision_event
            )
        except Exception:
            await self._commit_fail_closed_turn(
                turn,
                code="control_local_router_failed_closed",
                assistant_directed=envelope.final_transcript_nonempty,
            )
            return

        router_event = router_result.router_decision_event
        route = str(router_event["router_decision"])
        task_focus = str(router_event.get("task_focus", ""))
        self.state.router_decision = route
        self.state.task_focus = task_focus
        self.state.foreground_act = effective_proposal.foreground_act
        self.state.local_router_decision = route
        self.state.local_task_focus = task_focus
        self.state.local_foreground_act = _local_foreground_act(route, task_focus)
        turn.authority.route_delivery_attempted = True
        await self._send_json_best_effort(
            "route.decided",
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            router_decision=route,
            task_focus=task_focus,
            confidence=float(router_event.get("confidence", 0.0)),
            evidence_uncertainty=str(router_event.get("evidence_uncertainty", "low")),
            active_task_id=router_event.get("active_task_id"),
            route_hint=provider_proposal.route_hint,
            task_focus_hint=provider_proposal.task_focus_hint,
            authority="local_router",
        )
        await self._timeline_best_effort(
            "route.control.decided",
            {
                "router_decision": route,
                "task_focus": task_focus,
                "qwen_route_hint": provider_proposal.route_hint,
                "stale_status": self.state.stale_status,
                "output_mode": effective_proposal.output_mode,
            },
        )

        candidate_event = emission.candidate_event
        assert candidate_event is not None
        bundle = RealtimeTurnEvidenceBundle(
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            audio_span_id=turn.audio_span_id,
            provider_item_id=effective_proposal.provider_item_id,
            response_id=effective_proposal.response_id,
            playback_epoch=envelope.playback_epoch,
            turn_committed_event=turn.turn_committed_event,
            asr_frame_event=turn.asr_frame_event,
            proposal=effective_proposal,
        )
        mutation: _MutationOutcome | None = None
        if route == "SPAWN_SLOW_TASK":
            turn.authority.mutation_kind = "spawn_slow_task"
            turn.authority.mutation_started = True
            mutation = await self._spawn_slow_task(router_event, bundle)
            turn.authority.mutation_outcome = mutation.status
            turn.authority.mutation_completed = mutation.completed
            dispatch = "mock_slow_spawn" if mutation.completed else "degraded"
        elif route == "PATCH_ACTIVE_SLOW_TASK":
            turn.authority.mutation_kind = "user_patch"
            turn.authority.mutation_started = True
            mutation = await self._apply_user_patch(
                router_event,
                bundle,
                confirmation_signal_hint=confirmation_signal_hint,
            )
            turn.authority.mutation_outcome = mutation.status
            turn.authority.mutation_completed = mutation.completed
            dispatch = "user_patch" if mutation.completed else "degraded"
        elif route == "IGNORE":
            dispatch = "ignore"
        else:
            dispatch = "clarify"

        gate = run_fast_foreground_gate(
            self.journal,
            candidate_event=candidate_event,
            fast_interaction_output_event=emission.output_event,
            router_decision_event=router_event,
            context=self._fast_foreground_gate_context(
                router_decision_event=router_event
            ),
            config=FastForegroundGateConfig(
                confidence_threshold=float(self.config.gate_confidence_threshold)
            ),
            event_id_prefix=self._next_event_id("control_foreground_gate"),
            created_monotonic_ms=now_mono + 4,
            created_wall_clock_ms=now_wall + 4,
        )
        if route in {"SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"}:
            assert mutation is not None
            mutation_event_name = (
                "SLOWTASK_CREATED"
                if route == "SPAWN_SLOW_TASK"
                else "USER_PATCH_RECEIVED"
            )
            mutation_events = [
                event
                for event in self.journal.events()
                if event.get("event_name") == mutation_event_name
                and event.get("caused_by_event_id") == router_event.get("event_id")
            ]
            mutation_event = (
                mutation_events[0]
                if mutation.completed and len(mutation_events) == 1
                else None
            )
            mutation_completion_event = (
                self._patch_mutation_completion_event(mutation_event)
                if route == "PATCH_ACTIVE_SLOW_TASK"
                and mutation_event is not None
                else None
            )
            ack_ready = bool(
                mutation.completed
                and mutation_event is not None
                and (
                    route == "SPAWN_SLOW_TASK"
                    or mutation_completion_event is not None
                )
            )
            gate = commit_deferred_foreground_template(
                self.journal,
                gate_result=gate,
                router_decision_event=router_event,
                output_basis=(
                    "template_ack"
                    if ack_ready
                    else "template_clarify"
                ),
                mutation_event=mutation_event,
                mutation_completion_event=mutation_completion_event,
                fallback_reason=mutation.reason_code,
                event_id_prefix=self._next_event_id(
                    "control_deferred_foreground"
                ),
                created_monotonic_ms=now_mono + 6,
                created_wall_clock_ms=now_wall + 6,
            )
        turn.authority.gate_result = gate

        passed = bool(
            candidate_event is not None
            and gate.gate_event.get("event_name")
            == "FOREGROUND_ACT_GATE_PASSED"
            and gate.committed_event is not None
            and gate.committed_event.get("output_basis") == "reply_candidate"
            and gate.discarded_event is None
        )
        self.state.gate_status = (
            "passed" if passed else ("discarded" if route != "FAST_ONLY" else "failed")
        )
        if route == "FAST_ONLY":
            dispatch = "fast_text" if passed else "clarify"
        self.state.router_gate_latency_ms = round(
            max(0.0, (time.monotonic() - route_started) * 1_000), 3
        )
        self.state.function_done_to_local_router_ms = round(
            (self.state.function_done_to_local_router_ms or 0.0)
            + self.state.router_gate_latency_ms,
            3,
        )
        gate_fields: dict[str, Any] = {
            "gate_status": self.state.gate_status,
            "foreground_act": effective_proposal.foreground_act,
            "risk_class": effective_proposal.risk_class,
            "confidence": effective_proposal.confidence,
            "router_decision": route,
            "task_focus": task_focus,
            "router_gate_latency_ms": self.state.router_gate_latency_ms,
        }
        if gate.gate_event.get("failure_reason") is not None:
            gate_fields["failure_reason"] = str(gate.gate_event["failure_reason"])
        if gate.committed_event is not None:
            gate_fields["output_basis"] = str(gate.committed_event["output_basis"])
        turn.authority.gate_delivery_attempted = True
        await self._send_json_best_effort("gate.result", **gate_fields)
        await self._timeline_best_effort("gate.result", gate_fields)

        if passed:
            assert effective_proposal.reply_candidate_text is not None
            assert gate.committed_event is not None
            await self._send_committed_text(
                text=effective_proposal.reply_candidate_text,
                turn=turn,
                response_id=effective_proposal.response_id,
                foreground_act="ANSWER",
                source="control_candidate",
                commit_ref=str(gate.committed_event["event_id"]),
                output_ref=str(gate.committed_event["output_ref"]),
                output_basis=str(gate.committed_event["output_basis"]),
                output_mode=effective_proposal.output_mode,
            )
        elif route != "IGNORE" and gate.committed_event is not None:
            template = resolve_foreground_template(
                output_ref=gate.committed_event.get("output_ref"),
                output_basis=gate.committed_event.get("output_basis"),
                fallback_policy_ref=gate.committed_event.get(
                    "fallback_policy_ref"
                ),
                router_decision=route,
            )
            if template is not None:
                await self._send_committed_text(
                    text=template.text,
                    turn=turn,
                    response_id=effective_proposal.response_id,
                    foreground_act=template.foreground_act,
                    source="controlled_template",
                    commit_ref=str(gate.committed_event["event_id"]),
                    output_ref=template.template_ref,
                    output_basis=template.output_basis,
                    output_mode="fallback",
                )

        self.state.actual_dispatch = dispatch
        self.state.status = (
            "SLOWTASK"
            if dispatch in {"mock_slow_spawn", "user_patch"}
            else "LISTENING"
        )
        turn.authority.dispatch_metadata_attempted = True
        await self._send_json_best_effort(
            "dispatch.result",
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            actual_dispatch=dispatch,
            safe_turn_ref=envelope.safe_turn_ref,
            router_decision=route,
            task_focus=task_focus,
            gate_status=self.state.gate_status,
            stale_status=self.state.stale_status,
            mutation_outcome=turn.authority.mutation_outcome,
            delivery_state=turn.authority.delivery_state,
            response_id=turn.authority.delivery_response_id,
            semantic_response_kind=turn.authority.semantic_response_kind,
            task_id=(self.state.active_task.task_id if self.state.active_task else None),
            plan_version=(
                self.state.active_task.plan_version if self.state.active_task else None
            ),
            output_mode=(effective_proposal.output_mode if passed else "fallback"),
        )
        try:
            await self._send_control_state(output_mode=effective_proposal.output_mode)
        except Exception:
            pass
        try:
            await self._send_state("enforced_route_complete")
        except Exception:
            pass

    def _append_enforced_gate_failure(
        self,
        *,
        candidate_event: Mapping[str, Any],
        fast_interaction_output_event: Mapping[str, Any],
        router_decision_event: Mapping[str, Any],
        failure_reason: str,
        template_output_basis: str | None = None,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> FastForegroundGateResult:
        """Append a canonical fail-closed Gate result for Slice 3A checks.

        The shared gate cannot be called without a candidate, and it cannot
        express the extra provider/local FAST agreement check.  This helper
        emits the same canonical registry events and metadata-only refs for
        precisely those two enforced-control cases.
        """

        event_prefix = self._next_event_id("control_foreground_gate")
        safe_segment = f"{self._slug}_{self._event_counter:06d}"
        foreground_act = str(
            fast_interaction_output_event.get("foreground_act", "CLARIFY")
        )
        risk_class = str(fast_interaction_output_event.get("risk_class", "HIGH"))
        confidence = float(fast_interaction_output_event.get("confidence", 0.0))
        route = str(router_decision_event["router_decision"])
        task_focus = str(router_decision_event.get("task_focus", "AMBIGUOUS"))
        if route == "IGNORE":
            downgrade_policy = "silence"
        elif template_output_basis in {"template_ack", "template_clarify"}:
            downgrade_policy = str(template_output_basis)
        else:
            downgrade_policy = "template_clarify"
        gate_event = self.journal.append(
            event_name="FOREGROUND_ACT_GATE_FAILED",
            event_id=f"{event_prefix}_failed",
            source_module="fast_foreground_gate",
            caused_by_event_id=str(router_decision_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            gate_decision_id=f"gate_{safe_segment}",
            candidate_event_id=str(candidate_event["event_id"]),
            router_decision_event_id=str(router_decision_event["event_id"]),
            foreground_act=foreground_act,
            risk_class=risk_class,
            confidence=confidence,
            policy_version=FastForegroundGateConfig().policy_version,
            failure_reason=safe_code(
                failure_reason, fallback="control_gate_failed_closed"
            ),
            downgrade_policy=downgrade_policy,
        )
        discarded: dict[str, Any] | None = self.journal.append(
            event_name="FOREGROUND_OUTPUT_DISCARDED",
            event_id=f"{event_prefix}_discarded",
            source_module="foreground_buffer",
            caused_by_event_id=str(gate_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 1,
            created_wall_clock_ms=created_wall_clock_ms + 1,
            trace_redaction_level="metadata_only",
            discard_id=f"discard_{safe_segment}",
            candidate_event_id=str(candidate_event["event_id"]),
            fast_interaction_output_event_id=str(
                fast_interaction_output_event["event_id"]
            ),
            router_decision_event_id=str(router_decision_event["event_id"]),
            discard_reason=safe_code(
                failure_reason, fallback="control_gate_failed_closed"
            ),
        )
        committed: dict[str, Any] | None = None
        if downgrade_policy in {"template_ack", "template_clarify"}:
            template = get_foreground_template(
                router_decision=route,
                output_basis=downgrade_policy,
            )
            committed = self.journal.append(
                event_name="FOREGROUND_OUTPUT_COMMITTED",
                event_id=f"{event_prefix}_template_committed",
                source_module="foreground_output_runtime",
                caused_by_event_id=str(gate_event["event_id"]),
                created_monotonic_ms=created_monotonic_ms + 2,
                created_wall_clock_ms=created_wall_clock_ms + 2,
                trace_redaction_level="metadata_only",
                foreground_output_id=f"foreground_output_{safe_segment}_template",
                turn_id=str(router_decision_event["turn_id"]),
                utterance_id=str(router_decision_event["utterance_id"]),
                output_ref=template.template_ref,
                output_basis=downgrade_policy,
                foreground_act=template.foreground_act,
                router_decision_event_id=str(router_decision_event["event_id"]),
                gate_event_id=str(gate_event["event_id"]),
                fallback_policy_ref=template.fallback_policy_ref,
                fallback_reason=safe_code(
                    failure_reason, fallback="control_gate_failed_closed"
                ),
                user_visible_channel="text",
            )
            discarded["replacement_output_event_id"] = str(committed["event_id"])
        return FastForegroundGateResult(
            gate_event=gate_event,
            committed_event=committed,
            discarded_event=discarded,
            gate_decision_ms=0,
            output_finalize_ms=0,
        )

    def _recover_enforced_authority_from_journal(
        self, turn: _TurnContext
    ) -> None:
        """Rehydrate phase refs after an injected exception landed post-append."""

        authority = turn.authority
        events = self.journal.events()
        if authority.fast_interaction_output_event is None:
            authority.fast_interaction_output_event = next(
                (
                    dict(event)
                    for event in events
                    if event.get("event_name") == "FAST_INTERACTION_OUTPUT_EMITTED"
                    and event.get("turn_id") == turn.turn_id
                ),
                None,
            )
        fast_event = authority.fast_interaction_output_event
        if authority.candidate_event is None and fast_event is not None:
            authority.candidate_event = next(
                (
                    dict(event)
                    for event in events
                    if event.get("event_name")
                    == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
                    and event.get("fast_interaction_output_event_id")
                    == fast_event.get("event_id")
                ),
                None,
            )
        if authority.router_decision_event is None:
            authority.router_decision_event = next(
                (
                    dict(event)
                    for event in events
                    if event.get("event_name") == "ROUTER_DECISION_EMITTED"
                    and event.get("turn_id") == turn.turn_id
                ),
                None,
            )
        router_event = authority.router_decision_event
        if authority.gate_result is None and router_event is not None:
            gate_event = next(
                (
                    dict(event)
                    for event in events
                    if event.get("event_name")
                    in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}
                    and event.get("router_decision_event_id")
                    == router_event.get("event_id")
                ),
                None,
            )
            if gate_event is not None:
                committed = next(
                    (
                        dict(event)
                        for event in events
                        if event.get("event_name") == "FOREGROUND_OUTPUT_COMMITTED"
                        and event.get("gate_event_id") == gate_event.get("event_id")
                    ),
                    None,
                )
                discarded = next(
                    (
                        dict(event)
                        for event in events
                        if event.get("event_name") == "FOREGROUND_OUTPUT_DISCARDED"
                        and event.get("caused_by_event_id") == gate_event.get("event_id")
                    ),
                    None,
                )
                authority.gate_result = FastForegroundGateResult(
                    gate_event=gate_event,
                    committed_event=committed,
                    discarded_event=discarded,
                    gate_decision_ms=0,
                    output_finalize_ms=0,
                )

    def _ensure_enforced_degraded_event(
        self, turn: _TurnContext, *, normalized_code: str
    ) -> dict[str, Any] | None:
        authority = turn.authority
        if authority.degraded_event is not None:
            return authority.degraded_event
        if turn.asr_frame_event is None:
            return None
        now_mono, now_wall = _now_ms()
        authority.degraded_event = self._callback_boundary.append_adapter_event(
            event_name="ADAPTER_OUTPUT_DEGRADED",
            event_id=self._next_event_id("control_output_degraded"),
            source_module="qwen_enforced_control_fast_interaction_adapter",
            caused_by_event_id=str(turn.asr_frame_event["event_id"]),
            created_monotonic_ms=now_mono,
            created_wall_clock_ms=now_wall,
            trace_redaction_level="metadata_only",
            adapter_id="qfs_qwen_enforced_control_fast_interaction_v1",
            adapter_type="fast_interaction",
            adapter_request_id=f"control_degraded_{self._slug}_{turn.index:04d}",
            degraded_reason=normalized_code,
            output_mode="degraded",
        )
        return authority.degraded_event

    async def _commit_fail_closed_turn(
        self,
        turn: _TurnContext | None,
        *,
        code: object,
        assistant_directed: bool,
    ) -> None:
        """Complete only missing authority phases, never replay an emitted one."""

        normalized_code = safe_code(code, fallback="control_failed_closed")
        if turn is None:
            return
        authority = turn.authority
        if not authority.claimed and not self._claim_enforced_terminal(turn):
            return
        self._recover_enforced_authority_from_journal(turn)
        if authority.delivery_state != "delivery_not_started":
            # A browser send may have succeeded before raising. Once any
            # semantic delivery is attempted, recovery can emit metadata only;
            # it must never create a different CLARIFY/ACK response id.
            self._ensure_enforced_degraded_event(
                turn, normalized_code=normalized_code
            )
            authority.delivery_state = (
                "delivery_terminal"
                if authority.delivery_state == "delivery_terminal"
                else "delivery_ambiguous"
            )
            authority.dispatch_metadata_attempted = True
            await self._send_json_best_effort(
                "dispatch.result",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                actual_dispatch="degraded",
                safe_turn_ref=f"turn-{turn.index:04d}",
                gate_status=self.state.gate_status or "failed",
                stale_status="delivery_ambiguous",
                degraded_code=normalized_code,
                response_id=authority.delivery_response_id,
                semantic_response_kind=authority.semantic_response_kind,
                delivery_state=authority.delivery_state,
                output_mode="degraded",
            )
            return
        # Browser/timeline/control-state failures after the one dispatch
        # attempt are degraded delivery only.  They cannot reopen authority.
        if authority.dispatch_metadata_attempted:
            self._ensure_enforced_degraded_event(
                turn, normalized_code=normalized_code
            )
            if not authority.delivery_degraded_recorded:
                authority.delivery_degraded_recorded = True
                self._timeline_counter += 1
                self.metadata_timeline.append(
                    {
                        "event": "route.control.delivery_degraded",
                        "index": self._timeline_counter,
                        "metadata": {
                            "safe_turn_ref": f"turn-{turn.index:04d}",
                            "degraded_code": normalized_code,
                            "output_mode": "degraded",
                        },
                    }
                )
            return
        if turn.turn_committed_event is None or turn.asr_frame_event is None:
            self.state.actual_dispatch = "degraded"
            authority.dispatch_metadata_attempted = True
            await self._send_json_best_effort(
                "dispatch.result",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                actual_dispatch="degraded",
                safe_turn_ref=self.state.safe_turn_ref,
                gate_status="failed",
                stale_status="unavailable",
                degraded_code=normalized_code,
                output_mode="degraded",
            )
            return
        now_mono, now_wall = _now_ms()
        degraded = self._ensure_enforced_degraded_event(
            turn, normalized_code=normalized_code
        )
        assert degraded is not None
        if not self._turn_is_user_visible_eligible(turn):
            # A superseded turn may record a metadata-only adapter failure,
            # but it must not append a second Router/Gate chain or display a
            # late clarification over the current turn.
            authority.dispatch_metadata_attempted = True
            await self._send_json_best_effort(
                "dispatch.result",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                actual_dispatch="degraded",
                safe_turn_ref=f"late-turn-{turn.index:04d}",
                gate_status="failed",
                stale_status="superseded",
                degraded_code=normalized_code,
                caused_by_event_id=str(degraded["event_id"]),
                output_mode="degraded",
            )
            return
        focus = "AMBIGUOUS" if assistant_directed else "NON_ASSISTANT"
        foreground_act = "CLARIFY" if assistant_directed else "SILENCE"
        if authority.fast_interaction_output_event is None:
            fallback_template = get_foreground_template(
                router_decision="FAST_ONLY",
                output_basis="template_clarify",
            )
            binding = FastInteractionBinding.from_turn_and_asr_fallback(
                turn.turn_committed_event,
                asr_output_event=turn.asr_frame_event,
                adapter_request_id=f"control_fallback_{self._slug}_{turn.index:04d}",
            )
            emission = emit_fast_interaction_events(
                boundary=self._callback_boundary,
                binding=binding,
                output=FastInteractionOutput(
                    adapter_id="qfs_qwen_enforced_control_fallback_v1",
                    route_hint_ref=(
                        f"route-hint://experiment/qfs-control-fallback/{turn.index}"
                    ),
                    route_prelude_ref=(
                        f"route-prelude://experiment/qfs-control-fallback/{turn.index}"
                    ),
                    foreground_act=foreground_act,
                    final_fast_evidence_ref=(
                        f"fast-evidence://experiment/qfs-control-fallback/{turn.index}"
                    ),
                    risk_tags=("provider_degraded",),
                    risk_class="HIGH",
                    confidence=0.0,
                    output_mode="degraded",
                    reply_candidate_ref=fallback_template.template_ref,
                    candidate_id=(
                        f"control_fallback_candidate_{self._slug}_{turn.index:04d}"
                    ),
                    route_decision_hint=(
                        "FAST_ONLY" if assistant_directed else "IGNORE"
                    ),
                    task_focus_hint=focus,
                ),
                output_event_id=self._next_event_id("control_fallback_fast_output"),
                candidate_event_id=self._next_event_id(
                    "control_fallback_local_template_candidate"
                ),
                created_monotonic_ms=now_mono + 1,
                created_wall_clock_ms=now_wall + 1,
                source_module="qwen_enforced_control_fast_interaction_adapter",
            )
            authority.fast_interaction_output_event = dict(emission.output_event)
            assert emission.candidate_event is not None
            authority.candidate_event = dict(emission.candidate_event)
        if (
            authority.candidate_event is None
            and authority.fast_interaction_output_event is not None
        ):
            try:
                authority.candidate_event = self._append_local_template_candidate(
                    turn,
                    fast_interaction_output_event=(
                        authority.fast_interaction_output_event
                    ),
                    created_monotonic_ms=now_mono + 2,
                    created_wall_clock_ms=now_wall + 2,
                )
            except Exception:
                self._recover_enforced_authority_from_journal(turn)
        if authority.router_decision_event is None:
            router_evidence = dict(authority.fast_interaction_output_event)
            router_evidence.update(
                task_like=False,
                complexity_hint="low",
                evidence_uncertainty="high",
                route_decision_hint=(
                    "FAST_ONLY" if assistant_directed else "IGNORE"
                ),
                task_focus_hint=focus,
                foreground_act=foreground_act,
            )
            try:
                router_result = self._router.emit_decision(
                    turn_committed_event=turn.turn_committed_event,
                    asr_frame_event=turn.asr_frame_event,
                    fast_interaction_output_event=router_evidence,
                    router_context=self._router_context(),
                    event_id=self._next_event_id("control_fallback_router_decision"),
                    task_focus_state_event_id=self._next_event_id(
                        "control_fallback_task_focus_state"
                    ),
                    created_monotonic_ms=now_mono + 3,
                    created_wall_clock_ms=now_wall + 3,
                )
                authority.router_decision_event = dict(
                    router_result.router_decision_event
                )
            except Exception:
                self._recover_enforced_authority_from_journal(turn)
        router_event = authority.router_decision_event
        if router_event is None:
            self.state.actual_dispatch = "degraded"
            authority.dispatch_metadata_attempted = True
            await self._send_json_best_effort(
                "dispatch.result",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                actual_dispatch="degraded",
                gate_status="failed",
                stale_status="failed_closed",
                degraded_code=normalized_code,
                caused_by_event_id=str(degraded["event_id"]),
                output_mode="degraded",
            )
            return
        route = str(router_event["router_decision"])
        task_focus = str(router_event["task_focus"])
        if authority.gate_result is None:
            try:
                authority.gate_result = self._append_enforced_gate_failure(
                    candidate_event=authority.candidate_event,
                    fast_interaction_output_event=(
                        authority.fast_interaction_output_event
                    ),
                    router_decision_event=router_event,
                    failure_reason=normalized_code,
                    created_monotonic_ms=now_mono + 5,
                    created_wall_clock_ms=now_wall + 5,
                )
            except Exception:
                self._recover_enforced_authority_from_journal(turn)
                if authority.gate_result is None:
                    try:
                        authority.gate_result = self._append_enforced_gate_failure(
                            candidate_event=authority.candidate_event,
                            fast_interaction_output_event=(
                                authority.fast_interaction_output_event
                            ),
                            router_decision_event=router_event,
                            failure_reason=normalized_code,
                            created_monotonic_ms=now_mono + 5,
                            created_wall_clock_ms=now_wall + 5,
                        )
                    except Exception:
                        self._recover_enforced_authority_from_journal(turn)
        gate = authority.gate_result
        if gate is None:
            self.state.actual_dispatch = "degraded"
            authority.dispatch_metadata_attempted = True
            await self._send_json_best_effort(
                "dispatch.result",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                actual_dispatch="degraded",
                router_decision=route,
                task_focus=task_focus,
                gate_status="failed",
                stale_status="failed_closed",
                degraded_code=normalized_code,
                caused_by_event_id=str(degraded["event_id"]),
                output_mode="degraded",
            )
            return
        self.state.router_decision = route
        self.state.task_focus = task_focus
        self.state.local_router_decision = route
        self.state.local_task_focus = task_focus
        self.state.local_foreground_act = foreground_act
        self.state.foreground_act = foreground_act
        self.state.gate_status = "failed"
        self.state.actual_dispatch = "degraded"
        self.state.status = "LISTENING"
        self.state.stale_status = "failed_closed"
        if not authority.route_delivery_attempted:
            authority.route_delivery_attempted = True
            await self._send_json_best_effort(
                "route.decided",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                router_decision=route,
                task_focus=task_focus,
                confidence=0.0,
                evidence_uncertainty="high",
                authority="local_router",
                output_mode="degraded",
            )
        if not authority.gate_delivery_attempted:
            authority.gate_delivery_attempted = True
            await self._send_json_best_effort(
                "gate.result",
                gate_status="failed",
                foreground_act=foreground_act,
                risk_class="HIGH",
                confidence=0.0,
                router_decision=route,
                task_focus=task_focus,
                failure_reason=normalized_code,
                output_basis=(
                    gate.committed_event.get("output_basis")
                    if gate.committed_event is not None
                    else None
                ),
                output_mode="degraded",
            )
        if assistant_directed and gate.committed_event is not None:
            try:
                template = resolve_foreground_template(
                    output_ref=gate.committed_event.get("output_ref"),
                    output_basis=gate.committed_event.get("output_basis"),
                    fallback_policy_ref=gate.committed_event.get(
                        "fallback_policy_ref"
                    ),
                    router_decision=route,
                )
                if template is not None:
                    await self._await_browser_projection_best_effort(
                        self._send_committed_text(
                            text=template.text,
                            turn=turn,
                            response_id=f"control_fallback_{turn.index:04d}",
                            foreground_act=template.foreground_act,
                            source="controlled_template",
                            commit_ref=str(gate.committed_event["event_id"]),
                            output_ref=template.template_ref,
                            output_basis=template.output_basis,
                            output_mode="degraded",
                        )
                    )
            except Exception:
                pass
        authority.dispatch_metadata_attempted = True
        await self._send_json_best_effort(
            "dispatch.result",
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            actual_dispatch="degraded",
            safe_turn_ref=self.state.safe_turn_ref,
            router_decision=route,
            task_focus=task_focus,
            gate_status="failed",
            stale_status="failed_closed",
            degraded_code=normalized_code,
            caused_by_event_id=str(degraded["event_id"]),
            output_mode="degraded",
        )
        await self._await_browser_projection_best_effort(
            self._send_control_state(output_mode="degraded")
        )

    def _append_local_template_candidate(
        self,
        turn: _TurnContext,
        *,
        fast_interaction_output_event: Mapping[str, Any],
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> dict[str, Any]:
        input_mode = str(
            fast_interaction_output_event.get("input_mode", "asr_text_fallback")
        )
        template = get_foreground_template(
            router_decision="FAST_ONLY",
            output_basis="template_clarify",
        )
        return self._callback_boundary.append_adapter_event(
            event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
            event_id=self._next_event_id("control_recovery_local_template_candidate"),
            source_module="foreground_buffer",
            caused_by_event_id=str(fast_interaction_output_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            candidate_id=(
                f"control_recovery_template_{self._slug}_{turn.index:04d}"
            ),
            fast_interaction_output_event_id=str(
                fast_interaction_output_event["event_id"]
            ),
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            candidate_ref=template.template_ref,
            candidate_status="complete",
            input_mode=input_mode,
            fast_interaction_input_mode=input_mode,
            source_event_ids=(str(fast_interaction_output_event["event_id"]),),
            risk_tags=tuple(
                fast_interaction_output_event.get(
                    "risk_tags", ("provider_degraded",)
                )
            ),
            confidence=float(fast_interaction_output_event.get("confidence", 0.0)),
        )

    async def _send_committed_text(
        self,
        *,
        text: str,
        turn: _TurnContext,
        response_id: str,
        foreground_act: str,
        source: str,
        commit_ref: str,
        output_ref: str,
        output_basis: str,
        output_mode: str,
    ) -> None:
        authority = turn.authority
        if authority.delivery_state != "delivery_not_started":
            if (
                authority.delivery_response_id != response_id
                or authority.semantic_response_kind != foreground_act
                or authority.delivery_commit_ref != commit_ref
                or authority.delivery_output_ref != output_ref
                or authority.delivery_output_basis != output_basis
            ):
                raise RuntimeError("semantic_delivery_authority_conflict")
            # Recovery never creates a second browser-visible semantic reply.
            return
        authority.delivery_response_id = response_id
        authority.semantic_response_kind = foreground_act
        authority.delivery_commit_ref = commit_ref
        authority.delivery_output_ref = output_ref
        authority.delivery_output_basis = output_basis
        # Record the attempt before the first operation that may have an
        # externally visible effect. An exception from the sink is ambiguous:
        # it may have accepted the frame before raising.
        authority.delivery_state = "delivery_attempted"
        fields = {
            "text": text,
            "turn_id": turn.turn_id,
            "utterance_id": turn.utterance_id,
            "response_id": response_id,
            "foreground_act": foreground_act,
            "source": source,
            "server_committed": True,
            "commit_ref": commit_ref,
            "output_ref": output_ref,
            "output_basis": output_basis,
            "output": "text_only",
            "audio_output": "none",
            "output_mode": output_mode,
        }
        try:
            await self._send_json("transcript.assistant.delta", **fields)
            authority.delivery_state = "delivery_started"
            await self._send_json("transcript.assistant.done", **fields)
            authority.delivery_state = "delivery_terminal"
        except Exception:
            authority.delivery_state = "delivery_ambiguous"
            raise

    async def _refresh_voice_suppression_counters(self) -> None:
        counters = getattr(self.provider, "counters", None)
        if counters is not None:
            self.state.assistant_text_suppression_count = max(
                self.state.assistant_text_suppression_count,
                int(getattr(counters, "suppressed_text_delta_count", 0)),
            )
            self.state.audio_suppression_count = max(
                self.state.audio_suppression_count,
                int(getattr(counters, "suppressed_audio_frame_count", 0)),
            )
            cancel_count = int(getattr(counters, "cancel_request_count", 0))
            self.state.voice_cancel_count = max(
                self.state.voice_cancel_count, cancel_count
            )
            self.state.provider_cancel_count = max(
                self.state.provider_cancel_count, cancel_count
            )
            self.state.voice_cancel_terminal_count = max(
                self.state.voice_cancel_terminal_count,
                int(getattr(counters, "cancel_terminal_count", 0)),
            )
            self.state.voice_cancel_terminal_timeout_count = max(
                self.state.voice_cancel_terminal_timeout_count,
                int(getattr(counters, "cancel_terminal_timeout_count", 0)),
                self._voice_cancel_terminal_timeout_count,
            )
            self.state.voice_unsafe_cancel_terminal_count = max(
                self.state.voice_unsafe_cancel_terminal_count,
                int(getattr(counters, "unsafe_cancel_terminal_count", 0)),
            )
            self.state.voice_completed_after_cancel_count = max(
                self.state.voice_completed_after_cancel_count,
                int(getattr(counters, "completed_after_cancel_count", 0)),
            )
            self.state.voice_failed_after_cancel_count = max(
                self.state.voice_failed_after_cancel_count,
                int(getattr(counters, "failed_after_cancel_count", 0)),
            )
            self.state.voice_context_delete_count = max(
                self.state.voice_context_delete_count,
                int(getattr(counters, "context_delete_count", 0)),
            )
            self.state.voice_context_rebuild_count = max(
                self.state.voice_context_rebuild_count,
                int(getattr(counters, "context_rebuild_count", 0)),
            )
            self.state.voice_rebuild_pcm_drop_count = max(
                self.state.voice_rebuild_pcm_drop_count,
                int(getattr(counters, "rebuild_audio_drop_count", 0)),
                self._voice_rebuild_pcm_drop_count,
            )
            self.state.voice_audio_send_failure_count = max(
                self.state.voice_audio_send_failure_count,
                int(getattr(counters, "audio_send_failure_count", 0)),
                self._voice_audio_send_failure_count,
            )
            self.state.voice_rebuild_coalesced_count = max(
                self.state.voice_rebuild_coalesced_count,
                int(getattr(counters, "rebuild_coalesced_count", 0)),
                self._voice_rebuild_coalesced_count,
            )
        cancel_outcome = getattr(self.provider, "cancel_terminal_outcome", None)
        if cancel_outcome in {
            "cancelled_on_time",
            "cancelled_after_watchdog",
            "completed_after_cancel",
            "failed_after_cancel",
            "missing_terminal",
        }:
            self.state.voice_cancel_terminal_outcome = cancel_outcome
        self.state.voice_context_tainted = bool(
            getattr(self.provider, "context_tainted", self.state.voice_context_tainted)
        )

    async def _send_control_state(
        self,
        *,
        output_mode: str,
        authority_token: _ProviderAuthorityToken | None = None,
        authority_event: Any | None = None,
    ) -> None:
        await self._refresh_shadow_counters()
        await self._refresh_voice_suppression_counters()
        if (
            authority_token is not None
            and authority_event is not None
            and not self._provider_authority_current(
                authority_token,
                authority_event,
            )
        ):
            self._discard_stale_provider_authority()
            return
        snapshot = self._router_context().task_focus_snapshot
        fields = {
            "provider_mode": self.provider_mode,
            "routing_mode": self.routing_mode,
            "control_topology": self.state.control_topology,
            "output": "text_only",
            "audio_output": "none",
            "slow_runtime_mode": self.state.slow_runtime_mode,
            "experimental": True,
            "qwen_proposal_authority": "non_authoritative",
            "local_router_authority": "authoritative",
            "provider_native_audio_disabled": True,
            "voice_session_status": self.state.voice_session_status,
            "shadow_control_session_status": self.state.shadow_control_session_status,
            "safe_turn_ref": self.state.safe_turn_ref,
            "qwen_task_focus_hint": self.state.qwen_task_focus_hint,
            "qwen_route_hint": self.state.qwen_route_hint,
            "local_router_decision": self.state.local_router_decision,
            "local_task_focus": self.state.local_task_focus,
            "local_foreground_act": self.state.local_foreground_act,
            "gate_status": self.state.gate_status,
            "actual_dispatch": self.state.actual_dispatch,
            "stale_status": self.state.stale_status,
            "active_task_present": snapshot.has_active_non_terminal_task,
            "pending_confirmation_present": bool(
                snapshot.pending_confirmation_scope
            ),
            "task_id": snapshot.active_task_id,
            "plan_version": snapshot.current_plan_version,
            "router_gate_latency_ms": self.state.router_gate_latency_ms,
            "control_timeout_count": self.state.control_timeout_count,
            "control_error_count": self.state.control_error_count,
            "context_delete_count": self.state.context_delete_count,
            "context_rebuild_count": self.state.context_rebuild_count,
            "context_tainted": self.state.context_tainted,
            "voice_cancel_count": self.state.voice_cancel_count,
            "voice_cancel_terminal_count": self.state.voice_cancel_terminal_count,
            "voice_cancel_terminal_timeout_count": (
                self.state.voice_cancel_terminal_timeout_count
            ),
            "voice_unsafe_cancel_terminal_count": (
                self.state.voice_unsafe_cancel_terminal_count
            ),
            "voice_completed_after_cancel_count": (
                self.state.voice_completed_after_cancel_count
            ),
            "voice_failed_after_cancel_count": (
                self.state.voice_failed_after_cancel_count
            ),
            "voice_context_delete_count": self.state.voice_context_delete_count,
            "voice_context_rebuild_count": self.state.voice_context_rebuild_count,
            "voice_rebuild_pcm_drop_count": self.state.voice_rebuild_pcm_drop_count,
            "voice_audio_send_failure_count": (
                self.state.voice_audio_send_failure_count
            ),
            "voice_rebuild_coalesced_count": (
                self.state.voice_rebuild_coalesced_count
            ),
            "voice_cancel_terminal_outcome": (
                self.state.voice_cancel_terminal_outcome
            ),
            "voice_context_tainted": self.state.voice_context_tainted,
            "assistant_text_suppression_count": (
                self.state.assistant_text_suppression_count
            ),
            "audio_suppression_count": self.state.audio_suppression_count,
            "binary_playback_frame_count": self.state.binary_playback_frame_count,
            "stale_provider_event_discard_count": (
                self.state.stale_provider_event_discard_count
            ),
            "trace_redaction_level": "metadata_only",
            "output_mode": output_mode,
        }
        if authority_token is not None and authority_event is not None:
            await self._send_json_authority_guarded(
                "control.state",
                authority_token=authority_token,
                event=authority_event,
                **fields,
            )
            return
        await self._send_json("control.state", **fields)

    async def _rebuild_shadow_if_tainted(self) -> None:
        if self.shadow_provider is None or not bool(
            getattr(self.shadow_provider, "context_tainted", False)
        ):
            return
        try:
            rebuilt = await self.shadow_provider.rebuild_if_tainted()
        except Exception:
            rebuilt = False
        async with self._state_lock:
            if rebuilt:
                self.state.context_tainted = False
            await self._refresh_shadow_counters()
            if rebuilt:
                self._shadow_available = True
                self.state.context_tainted = False
                self.state.shadow_control_session_status = "connected"
                self._last_shadow_output_mode = str(
                    self.shadow_provider.profile.output_mode
                )
                if self.qwen_enforced:
                    await self._send_control_state(
                        output_mode=self._last_shadow_output_mode
                    )
                else:
                    await self._send_shadow_state(
                        output_mode=self._last_shadow_output_mode
                    )
            else:
                self._shadow_available = False
                self.state.context_tainted = True
                self.state.shadow_control_session_status = "degraded"
                if self.qwen_enforced:
                    await self._send_control_state(output_mode="degraded")

    async def _emit_shadow_degraded(
        self,
        *,
        code: object,
        safe_turn_ref: str | None,
        schema_invalid: bool = False,
        schema_status: str | None = None,
        preserve_proposal: bool = False,
    ) -> None:
        self.state.safe_turn_ref = safe_turn_ref
        if not preserve_proposal:
            self.state.qwen_task_focus_hint = None
            self.state.qwen_route_hint = None
            self.state.shadow_foreground_act = None
            self.state.shadow_risk_class = None
            self.state.shadow_confidence = None
        self.state.local_router_decision = None
        self.state.local_task_focus = None
        self.state.local_foreground_act = None
        self.state.schema_status = (
            schema_status
            if schema_status in {"valid", "invalid", "not_available"}
            else ("invalid" if schema_invalid else "not_available")
        )
        self.state.agreement = "not_available"
        self.state.shadow_control_session_status = "degraded"
        self._last_shadow_output_mode = "degraded"
        normalized_code = safe_code(code, fallback="shadow_control_degraded")
        await self._refresh_shadow_counters()
        fields = {
            "provider_mode": self.provider_mode,
            "routing_mode": "shadow",
            "shadow_control_session_status": "degraded",
            "safe_turn_ref": safe_turn_ref,
            "schema_status": self.state.schema_status,
            "agreement": "not_available",
            "degraded_code": normalized_code,
            "control_timeout_count": self.state.control_timeout_count,
            "control_error_count": self.state.control_error_count,
            "shadow_drop_count": self.state.shadow_drop_count,
            "context_tainted": self.state.context_tainted,
            "output_mode": "degraded",
        }
        await self._send_json("route.shadow.degraded", **fields)
        await self._timeline("route.shadow.degraded", fields)
        await self._send_shadow_state(output_mode="degraded")

    async def _refresh_shadow_counters(self) -> None:
        counters = getattr(self.shadow_provider, "counters", None)
        if counters is not None:
            self.state.control_timeout_count = int(
                getattr(counters, "timeout_count", self.state.control_timeout_count)
            )
            self.state.control_error_count = self._shadow_local_error_count + int(
                getattr(counters, "error_count", 0)
            )
            self.state.context_delete_count = int(
                getattr(counters, "context_delete_count", self.state.context_delete_count)
            )
            self.state.context_rebuild_count = int(
                getattr(counters, "context_rebuild_count", self.state.context_rebuild_count)
            )
            self.state.shadow_drop_count = self._shadow_queue_drop_count + int(
                getattr(counters, "request_drop_count", 0)
            )
            self.state.control_cancel_count = int(
                getattr(counters, "cancel_request_count", self.state.control_cancel_count)
            )
            self.state.control_cancel_terminal_count = int(
                getattr(
                    counters,
                    "cancel_terminal_count",
                    self.state.control_cancel_terminal_count,
                )
            )
        self.state.context_tainted = self.state.context_tainted or bool(
            getattr(self.shadow_provider, "context_tainted", False)
        )

    async def _send_shadow_state(self, *, output_mode: str) -> None:
        task_snapshot = self._router_context().task_focus_snapshot
        await self._send_json(
            "shadow.state",
            provider_mode=self.provider_mode,
            routing_mode=self.routing_mode,
            audio_output=self.audio_output,
            shadow_control_mode=self.shadow_control_mode,
            voice_session_status=self.state.voice_session_status,
            shadow_control_session_status=self.state.shadow_control_session_status,
            safe_turn_ref=self.state.safe_turn_ref,
            qwen_task_focus_hint=self.state.qwen_task_focus_hint,
            qwen_route_hint=self.state.qwen_route_hint,
            local_router_decision=self.state.local_router_decision,
            local_task_focus=self.state.local_task_focus,
            local_foreground_act=self.state.local_foreground_act,
            foreground_act=self.state.shadow_foreground_act,
            risk_class=self.state.shadow_risk_class,
            confidence=self.state.shadow_confidence,
            schema_status=self.state.schema_status,
            agreement=self.state.agreement,
            asr_to_shadow_request_ms=self.state.asr_to_shadow_request_ms,
            shadow_request_to_first_delta_ms=(
                self.state.shadow_request_to_first_delta_ms
            ),
            shadow_request_to_done_ms=self.state.shadow_request_to_done_ms,
            function_done_to_local_router_ms=(
                self.state.function_done_to_local_router_ms
            ),
            control_timeout_count=self.state.control_timeout_count,
            control_error_count=self.state.control_error_count,
            control_cancel_count=self.state.control_cancel_count,
            control_cancel_terminal_count=self.state.control_cancel_terminal_count,
            context_delete_count=self.state.context_delete_count,
            context_rebuild_count=self.state.context_rebuild_count,
            shadow_drop_count=self.state.shadow_drop_count,
            context_tainted=self.state.context_tainted,
            active_task_present=task_snapshot.has_active_non_terminal_task,
            pending_confirmation_present=bool(
                task_snapshot.pending_confirmation_scope
            ),
            output_mode=output_mode,
        )

    async def _clear_voice_playback(self, *, reason: str) -> None:
        started = time.monotonic()
        self.state.playback_epoch += 1
        previous_response_id = self._voice_active_response_id
        self._voice_active_response_id = None
        if previous_response_id is not None:
            self._retire_voice_response_locked(previous_response_id)
        self._active_playback_offset_ms = 0
        self.state.clear_latency_ms = max(
            0, int((time.monotonic() - started) * 1_000)
        )
        await self._send_json(
            "playback.clear",
            playback_epoch=self.state.playback_epoch,
            reason=reason,
            clear_latency_ms=self.state.clear_latency_ms,
            discarded_late_audio_frames=self.state.discarded_late_audio_frames,
            stale_provider_event_discard_count=(
                self.state.stale_provider_event_discard_count
            ),
            dropped_output_frames=self.state.dropped_output_frames,
        )

    def _voice_response_is_current(self, response_id: object) -> bool:
        return bool(
            isinstance(response_id, str)
            and response_id == self._voice_active_response_id
            and self._voice_response_epochs.get(response_id) == self.state.playback_epoch
        )

    def _record_shadow_late_discard(self) -> None:
        counters = getattr(self.shadow_provider, "counters", None)
        if counters is not None and hasattr(counters, "late_event_discard_count"):
            counters.late_event_discard_count += 1

    def _claim_enforced_terminal(self, turn: _TurnContext | None) -> bool:
        """Atomically claim one authoritative terminal while state lock is held."""

        if (
            turn is None
            or turn.authority.claimed
            or turn.turn_id in self._enforced_terminal_turn_ids
        ):
            return False
        turn.authority.claimed = True
        self._remember_bounded_tombstone(
            turn.turn_id,
            values=self._enforced_terminal_turn_ids,
            order=self._enforced_terminal_turn_order,
        )
        return True

    def _remember_bounded_tombstone(
        self,
        value: str,
        *,
        values: set[str],
        order: deque[str],
    ) -> None:
        if value in values:
            return
        while len(order) >= self.config.max_correlation_tombstones:
            values.discard(order.popleft())
        order.append(value)
        values.add(value)

    async def _discard_late_enforced_result(
        self, turn: _TurnContext | None, *, code: str
    ) -> None:
        self._record_shadow_late_discard()
        await self._timeline(
            "route.control.late_discarded",
            {
                "safe_turn_ref": (
                    f"late-turn-{turn.index:04d}" if turn is not None else "late-turn"
                ),
                "degraded_code": safe_code(
                    code, fallback="control_terminal_already_committed"
                ),
                "routing_mode": self.routing_mode,
                "output_mode": "degraded",
            },
        )

    def _turn_is_user_visible_eligible(self, turn: _TurnContext) -> bool:
        return bool(
            self._current_turn is turn
            and turn.playback_epoch == self.state.playback_epoch
            and self._latest_shadow_turn_id == turn.turn_id
        )

    def _voice_input_event_refs(
        self, event: Any
    ) -> tuple[str, str, str, str, str] | None:
        """Return adapter-owned opaque refs required by enforced Voice input."""

        if not self.qwen_enforced:
            return None
        if not bool(getattr(event, "correlation_valid", True)):
            return None
        provider_item_ref = getattr(event, "provider_item_id", None)
        provider_turn_ref = getattr(event, "turn_ref", None)
        provider_utterance_ref = getattr(event, "utterance_ref", None)
        provider_audio_span_ref = getattr(event, "audio_span_ref", None)
        provider_session_ref = getattr(event, "session_ref", None)
        if str(getattr(event, "output_mode", "degraded")) != "real":
            # Provider-free acceptance uses the deterministic fake, whose
            # turn_ref is the complete synthetic correlation contract.
            provider_item_ref = provider_item_ref or provider_turn_ref
            provider_session_ref = provider_session_ref or "mock-voice-session"
            provider_utterance_ref = (
                provider_utterance_ref
                or (
                    f"{provider_turn_ref}:utterance"
                    if isinstance(provider_turn_ref, str)
                    else None
                )
            )
            provider_audio_span_ref = (
                provider_audio_span_ref
                or (
                    f"{provider_turn_ref}:audio-span"
                    if isinstance(provider_turn_ref, str)
                    else None
                )
            )
        if not all(
            isinstance(value, str) and bool(value)
            for value in (
                provider_item_ref,
                provider_turn_ref,
                provider_utterance_ref,
                provider_audio_span_ref,
                provider_session_ref,
            )
        ):
            return None
        return (
            str(provider_item_ref),
            str(provider_turn_ref),
            str(provider_utterance_ref),
            str(provider_audio_span_ref),
            str(provider_session_ref),
        )

    def _voice_event_matches_turn(self, event: Any, turn: _TurnContext) -> bool:
        refs = self._voice_input_event_refs(event)
        if refs is None:
            return False
        (
            provider_item_ref,
            provider_turn_ref,
            provider_utterance_ref,
            provider_audio_span_ref,
            provider_session_ref,
        ) = refs
        return bool(
            provider_item_ref == turn.provider_input_item_ref
            and provider_turn_ref == turn.provider_turn_ref
            and provider_utterance_ref == turn.provider_utterance_ref
            and provider_audio_span_ref == turn.provider_audio_span_ref
            and provider_session_ref == turn.provider_session_ref
            and self._voice_input_item_turns.get(provider_item_ref) == turn.turn_id
            and provider_session_ref == self._voice_session_ref
        )

    async def _reject_voice_input_event(
        self, *, event: Any, code: str, turn: _TurnContext | None
    ) -> None:
        self.state.voice_context_tainted = True
        self.state.voice_session_status = "degraded"
        if self.qwen_enforced:
            # Correlation/horizon failure retires the entire bounded Voice
            # generation. Fence and drain it before any browser projection.
            self._schedule_voice_rebuild()
            await self._await_browser_projection_best_effort(
                self.report_safe_error(
                    getattr(event, "error_code", None) or code,
                    terminal=False,
                    retryable=True,
                )
            )
            return
        await self._commit_fail_closed_turn(
            turn,
            code=(getattr(event, "error_code", None) or code),
            assistant_directed=False,
        )
        await self.report_safe_error(
            getattr(event, "error_code", None) or code,
            terminal=False,
            retryable=True,
        )

    async def _on_speech_started(
        self,
        event: FakeProviderEvent,
        *,
        authority_token: _ProviderAuthorityToken | None = None,
    ) -> None:
        input_refs = self._voice_input_event_refs(event)
        if self.qwen_enforced and input_refs is None:
            await self._reject_voice_input_event(
                event=event,
                code="voice_speech_start_correlation_invalid",
                turn=self._current_turn,
            )
            return
        if self.qwen_enforced:
            assert input_refs is not None
            provider_input_item_ref, _, _, _, _ = input_refs
            if (
                provider_input_item_ref in self._voice_input_item_turns
                or provider_input_item_ref in self._voice_input_item_tombstones
            ):
                await self._reject_voice_input_event(
                    event=event,
                    code="voice_speech_start_item_reused",
                    turn=self._current_turn,
                )
                return
        prospective_audio_span_id = f"audio_{self._slug}_{self._turn_counter + 1:04d}"
        await self._interrupt_locked(
            reason="speech_started",
            audio_span_id=prospective_audio_span_id,
        )
        if not self._provider_authority_current(authority_token, event):
            self._discard_stale_provider_authority()
            return
        if event.interrupt_only:
            return
        self._turn_counter += 1
        turn_id = f"turn_{self._slug}_{self._turn_counter:04d}"
        utterance_id = f"utterance_{self._slug}_{self._turn_counter:04d}"
        audio_span_id = f"audio_{self._slug}_{self._turn_counter:04d}"
        now_mono, now_wall = _now_ms()
        assert self._session_started_event is not None
        audio_started = self.journal.append(
            event_name="AUDIO_SPAN_STARTED",
            event_id=self._next_event_id("audio_span_started"),
            source_module=self._voice_source_module,
            caused_by_event_id=str(self._session_started_event["event_id"]),
            created_monotonic_ms=now_mono,
            created_wall_clock_ms=now_wall,
            trace_redaction_level="metadata_only",
            audio_span_id=audio_span_id,
            audio_sample_offset=0,
            audio_format_ref="audio-format://pcm16le/16000/mono",
            input_modality="audio",
        )
        speech_start = self.journal.append(
            event_name="SPEECH_START_DETECTED",
            event_id=self._next_event_id("speech_start"),
            source_module=self._voice_source_module,
            caused_by_event_id=str(audio_started["event_id"]),
            created_monotonic_ms=now_mono + 1,
            created_wall_clock_ms=now_wall + 1,
            trace_redaction_level="metadata_only",
            audio_span_id=audio_span_id,
            audio_sample_offset=0,
            vad_confidence=0.99,
            detection_basis=(
                "provider_projection:qwen_smart_turn"
                if self.provider_mode == "qwen"
                else "mock_rule:synthetic_speech_start"
            ),
        )
        self._interaction.open_audio_turn(
            speech_start,
            turn_id=turn_id,
            created_monotonic_ms=now_mono + 2,
            created_wall_clock_ms=now_wall + 2,
        )
        self._current_turn = _TurnContext(
            index=self._turn_counter,
            turn_id=turn_id,
            utterance_id=utterance_id,
            audio_span_id=audio_span_id,
            playback_epoch=self.state.playback_epoch,
            scenario=(
                getattr(event, "scenario", None)
                or ("shadow" if self.routing_mode == "shadow" else self.state.configured_scenario)
            ),
            speech_start_event=speech_start,
            provider_input_item_ref=(input_refs[0] if input_refs is not None else None),
            provider_turn_ref=(input_refs[1] if input_refs is not None else None),
            provider_utterance_ref=(input_refs[2] if input_refs is not None else None),
            provider_audio_span_ref=(input_refs[3] if input_refs is not None else None),
            provider_session_ref=(input_refs[4] if input_refs is not None else None),
        )
        if input_refs is not None:
            self._voice_session_ref = input_refs[4]
            self._voice_input_item_turns[input_refs[0]] = turn_id
        self.state.status = "LISTENING"
        # playback.clear above is the one authoritative clear signal.  Keep
        # the following state projection from triggering a duplicate browser
        # clear for the same speech start.
        await self._send_state("speech_turn_opened")

    async def _on_speech_stopped(
        self,
        event: FakeProviderEvent,
        *,
        authority_token: _ProviderAuthorityToken | None = None,
    ) -> None:
        if not self._provider_authority_current(authority_token, event):
            self._discard_stale_provider_authority()
            return
        turn = self._current_turn
        if turn is None or turn.turn_committed_event is not None:
            await self.report_safe_error("speech_stop_without_open_turn")
            return
        if self.qwen_enforced and not self._voice_event_matches_turn(event, turn):
            await self._reject_voice_input_event(
                event=event,
                code="voice_speech_stop_correlation_invalid",
                turn=turn,
            )
            return
        now_mono, now_wall = _now_ms()
        speech_end = self.journal.append(
            event_name="SPEECH_END_DETECTED",
            event_id=self._next_event_id("speech_end"),
            source_module=self._voice_source_module,
            caused_by_event_id=str(turn.speech_start_event["event_id"]),
            created_monotonic_ms=now_mono,
            created_wall_clock_ms=now_wall,
            trace_redaction_level="metadata_only",
            audio_span_id=turn.audio_span_id,
            audio_sample_offset=1_600,
            vad_confidence=0.99,
            silence_duration_ms=200,
            detection_basis=(
                "provider_projection:qwen_smart_turn"
                if self.provider_mode == "qwen"
                else "mock_rule:synthetic_speech_stop"
            ),
        )
        commit_result = self._interaction.commit_audio_ingress(
            speech_end,
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            created_monotonic_ms=now_mono + 1,
            created_wall_clock_ms=now_wall + 1,
        )
        turn.turn_committed_event = commit_result.turn_committed
        self.journal.append(
            event_name="AUDIO_SPAN_ENDED",
            event_id=self._next_event_id("audio_span_ended"),
            source_module=self._voice_source_module,
            caused_by_event_id=str(speech_end["event_id"]),
            created_monotonic_ms=now_mono + 3,
            created_wall_clock_ms=now_wall + 3,
            trace_redaction_level="metadata_only",
            audio_span_id=turn.audio_span_id,
            audio_sample_offset=1_600,
            duration_ms=100,
            end_reason=(
                "provider_speech_stopped"
                if self.provider_mode == "qwen"
                else "synthetic_speech_stopped"
            ),
        )
        self.state.status = "ROUTING"
        await self._send_state("speech_stopped")

    async def _on_user_transcript(
        self,
        event: FakeProviderEvent,
        *,
        final: bool,
        authority_token: _ProviderAuthorityToken | None = None,
    ) -> None:
        if not self._provider_authority_current(authority_token, event):
            self._discard_stale_provider_authority()
            return
        turn = self._current_turn
        if turn is None:
            await self.report_safe_error("transcript_without_open_turn")
            return
        if self.qwen_enforced and (
            not self._voice_event_matches_turn(event, turn)
            or (final and turn.provider_final_seen)
        ):
            await self._reject_voice_input_event(
                event=event,
                code=(
                    "voice_transcript_final_duplicate"
                    if final and turn.provider_final_seen
                    else "voice_transcript_correlation_invalid"
                ),
                turn=turn,
            )
            return
        message_type = "transcript.user.final" if final else "transcript.user.delta"
        fields = {
            "text": event.text
            or ("" if self.provider_mode == "qwen" else "[synthetic]"),
            "turn_id": turn.turn_id,
            "utterance_id": turn.utterance_id,
            "audio_span_id": turn.audio_span_id,
            "output_mode": str(getattr(event, "output_mode", "degraded")),
        }
        if authority_token is None:
            await self._send_json(message_type, **fields)
        elif not await self._send_json_authority_guarded(
            message_type,
            authority_token=authority_token,
            event=event,
            **fields,
        ):
            return
        if not self._provider_authority_current(authority_token, event):
            self._discard_stale_provider_authority()
            return
        if not final:
            return
        turn.provider_final_seen = True
        if turn.turn_committed_event is None:
            await self.report_safe_error("final_transcript_before_turn_commit")
            return
        now_mono, now_wall = _now_ms()
        if self.control_enabled:
            raw_provider_output_mode = str(
                getattr(event, "output_mode", "degraded")
            )
            provider_output_mode = raw_provider_output_mode
            if self.qwen_enforced:
                # The provider event does not include word/audio timestamps.
                # ADR-010 requires explicit degradation before projecting an
                # ASR output with that capability missing.
                provider_output_mode = "degraded"
            adapter_id = (
                "qfs_qwen_voice_asr_v1"
                if self.provider_mode == "qwen"
                and raw_provider_output_mode == "real"
                else "qfs_fake_voice_asr_shadow_v1"
            )
            adapter_request_id = f"voice_asr_{self._slug}_{turn.index:04d}"
            if provider_output_mode == "degraded":
                self._callback_boundary.append_adapter_event(
                    event_name="ADAPTER_OUTPUT_DEGRADED",
                    event_id=self._next_event_id("asr_timestamp_degraded"),
                    source_module=self._voice_source_module,
                    caused_by_event_id=str(turn.turn_committed_event["event_id"]),
                    created_monotonic_ms=now_mono,
                    created_wall_clock_ms=now_wall,
                    trace_redaction_level="metadata_only",
                    adapter_id=adapter_id,
                    adapter_type="asr",
                    adapter_request_id=adapter_request_id,
                    degraded_reason="audio_timestamps_unavailable",
                    missing_capability="supports_audio_timestamps",
                    output_mode="degraded",
                )
            turn.asr_frame_event = self._callback_boundary.append_adapter_event(
                event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
                event_id=self._next_event_id("real_asr"),
                source_module=self._voice_source_module,
                caused_by_event_id=str(turn.turn_committed_event["event_id"]),
                created_monotonic_ms=now_mono + 1,
                created_wall_clock_ms=now_wall + 1,
                trace_redaction_level="metadata_only",
                adapter_id=adapter_id,
                adapter_type="asr",
                adapter_request_id=adapter_request_id,
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                input_modality="audio",
                audio_span_id=turn.audio_span_id,
                asr_frame_ref=f"asr-frame://experiment/qfs-control/{turn.index}",
                text_ref=f"text://redacted/qfs-control/{turn.index}",
                transcript_finality="final",
                timestamp_status="unavailable",
                streaming_status="supported",
                normalization_status="normalized",
                output_mode=provider_output_mode,
            )
            if self.qwen_enforced:
                # This synchronous assignment is the authority-transfer
                # boundary: provider authority was checked immediately before
                # the canonical ASR append, and no await occurs between them.
                turn.committed_control_authority = _CommittedTurnAuthority(
                    session_id=self.session_id,
                    conversation_id=self.conversation_id,
                    turn_id=turn.turn_id,
                    utterance_id=turn.utterance_id,
                    asr_event_id=str(turn.asr_frame_event["event_id"]),
                    asr_frame_ref=str(turn.asr_frame_event["asr_frame_ref"]),
                    playback_epoch=turn.playback_epoch,
                )
            enqueued = await self._enqueue_shadow_request(
                turn=turn,
                transcript=event.text or "",
                asr_final_monotonic_ms=now_mono,
            )
            if not enqueued:
                return
            if self.qwen_enforced and turn.provider_input_item_ref is not None:
                self._retire_voice_input_item_locked(turn.provider_input_item_ref)
        else:
            turn.asr_frame_event = self.journal.append(
                event_name="MOCK_ASR_FRAME_EMITTED",
                event_id=self._next_event_id("mock_asr"),
                source_module="fake_qwen_asr_projection",
                caused_by_event_id=str(turn.turn_committed_event["event_id"]),
                created_monotonic_ms=now_mono,
                created_wall_clock_ms=now_wall,
                trace_redaction_level="redacted_fixture",
                turn_id=turn.turn_id,
                utterance_id=turn.utterance_id,
                input_modality="audio",
                audio_span_id=turn.audio_span_id,
                asr_frame_ref=f"asr-frame://synthetic/qfs/{turn.index}",
                text_ref=f"text://synthetic/qfs/{turn.index}/redacted",
                output_mode="mock",
            )

    async def _on_response_created(self, event: FakeProviderEvent) -> None:
        turn = self._current_turn
        if (
            turn is None
            or turn.turn_committed_event is None
            or turn.asr_frame_event is None
            or event.response_id is None
            or event.provider_item_id is None
        ):
            await self.report_safe_error("response_correlation_incomplete")
            return
        context = _ResponseContext(
            response_id=event.response_id,
            provider_item_id=event.provider_item_id,
            playback_epoch=turn.playback_epoch,
            scenario=event.scenario or turn.scenario,
            turn=turn,
        )
        self._remember_response(context)
        self.quarantine.start(
            response_id=context.response_id,
            provider_item_id=context.provider_item_id,
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            playback_epoch=context.playback_epoch,
        )
        self.state.status = "ROUTING"

    def _quarantine_text(self, event: FakeProviderEvent) -> None:
        context = self._responses.get(event.response_id or "")
        if (
            event.response_id is None
            or event.text is None
            or context is None
            or event.provider_item_id != context.provider_item_id
        ):
            self.quarantine.dropped_text_deltas += 1
            return
        self.quarantine.append_text(event.response_id, event.text)

    async def _quarantine_audio(self, event: FakeProviderEvent) -> None:
        if event.response_id is None or event.audio is None:
            self.state.discarded_late_audio_frames += 1
            await self._send_flow()
            return
        context = self._responses.get(event.response_id)
        if (
            context is None
            or event.provider_item_id != context.provider_item_id
            or context.playback_epoch != self.state.playback_epoch
            or event.response_id not in self.quarantine.active_response_ids
        ):
            self.state.discarded_late_audio_frames += 1
            await self._send_flow()
            return
        if not self.quarantine.append_audio(event.response_id, event.audio):
            await self._send_json(
                "degraded",
                code="candidate_quarantine_overflow",
                output_mode="degraded",
                playback_epoch=self.state.playback_epoch,
            )

    async def _on_route_proposed(self, event: FakeProviderEvent) -> None:
        if event.response_id is None or event.provider_item_id is None:
            await self.report_safe_error("route_proposal_correlation_incomplete")
            return
        context = self._responses.get(event.response_id)
        if context is None or context.provider_item_id != event.provider_item_id:
            await self.report_safe_error("route_proposal_correlation_mismatch")
            return
        if (
            context.playback_epoch != self.state.playback_epoch
            or context.response_id not in self.quarantine.active_response_ids
        ):
            # Interrupt/cancel is a generation fence.  Stale provider evidence
            # must not reach Router, Gate, SlowTask, or UserPatch.
            context.route_processed = True
            self.quarantine.discard(
                context.response_id, reason="response_epoch_stale"
            )
            if await self.provider.cancel_response():
                self.state.provider_cancel_count += 1
            await self._timeline(
                "route.stale_discarded",
                {"playback_epoch": context.playback_epoch},
            )
            await self._send_flow()
            return
        proposal = ProviderRouteProposal(
            scenario=event.scenario or context.scenario,
            response_id=event.response_id,
            provider_item_id=event.provider_item_id,
            route_hint=str(event.route_hint),
            task_focus_hint=str(event.task_focus_hint),
            foreground_act=str(event.foreground_act),
            risk_class=str(event.risk_class),
            confidence=float(event.confidence if event.confidence is not None else 0.0),
            output_mode="mock",
        )
        await self._send_json("route.proposed", **proposal.to_metadata())
        await self._timeline("route.proposed", proposal.to_metadata())
        await self._route_and_gate(context, proposal)

    async def _on_response_done(self, event: FakeProviderEvent) -> None:
        if event.response_id is None:
            return
        context = self._responses.get(event.response_id)
        if context is None:
            return
        context.done_status = event.status or "completed"
        if not context.route_processed and event.response_id in self.quarantine.active_response_ids:
            self.quarantine.discard(event.response_id, reason="response_done_without_route")
            await self.report_safe_error("response_done_without_local_route")

    async def _route_and_gate(
        self, context: _ResponseContext, provider_proposal: ProviderRouteProposal
    ) -> None:
        turn = context.turn
        if turn.turn_committed_event is None or turn.asr_frame_event is None:
            await self.report_safe_error("route_evidence_incomplete")
            return
        effective_proposal = provider_proposal
        active_task = self.state.active_task
        if (
            active_task is not None
            and active_task.active_non_terminal
            and active_task.pending_confirmation_scope is not None
        ):
            # Pending confirmation input is forced into the UserPatch path.
            # This is contextual evidence normalization; Router still owns the
            # final decision and the provider never advances task state.
            effective_proposal = provider_proposal.with_local_focus_override(
                route_hint="PATCH_ACTIVE_SLOW_TASK",
                task_focus_hint="ACTIVE_TASK_PATCH",
            )
        bundle = RealtimeTurnEvidenceBundle(
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            audio_span_id=turn.audio_span_id,
            provider_item_id=context.provider_item_id,
            response_id=context.response_id,
            playback_epoch=context.playback_epoch,
            turn_committed_event=turn.turn_committed_event,
            asr_frame_event=turn.asr_frame_event,
            proposal=effective_proposal,
        )
        now_mono, now_wall = _now_ms()
        safe_turn = f"{self._slug}_{turn.index:04d}"
        candidate_snapshot = self.quarantine.snapshot(context.response_id)
        candidate_integrity_ok = (
            candidate_snapshot is not None and not candidate_snapshot.overflowed
        )
        effective_confidence = (
            float(effective_proposal.confidence) if candidate_integrity_ok else 0.0
        )
        binding = FastInteractionBinding.from_turn_audio(
            bundle.turn_committed_event,
            adapter_request_id=f"fast_request_{safe_turn}",
            audio_frame_ref=f"audio-frame://synthetic/qfs/{safe_turn}",
        )
        fast_output = FastInteractionOutput(
            adapter_id="qfs_fake_fast_interaction_v1",
            route_hint_ref=f"route-hint://synthetic/qfs/{safe_turn}",
            route_prelude_ref=f"route-prelude://synthetic/qfs/{safe_turn}",
            foreground_act=effective_proposal.foreground_act,
            final_fast_evidence_ref=f"fast-evidence://synthetic/qfs/{safe_turn}",
            risk_tags=(
                ("none",)
                if candidate_integrity_ok
                else ("candidate_quarantine_overflow",)
            ),
            risk_class=effective_proposal.risk_class,
            confidence=effective_confidence,
            output_mode="mock",
            reply_candidate_ref=f"reply-candidate://synthetic/qfs/{safe_turn}",
            candidate_id=f"candidate_{safe_turn}",
            route_decision_hint=effective_proposal.route_hint,
            task_focus_hint=effective_proposal.task_focus_hint,
        )
        emission = emit_fast_interaction_events(
            boundary=self._callback_boundary,
            binding=binding,
            output=fast_output,
            output_event_id=self._next_event_id("fast_interaction_output"),
            candidate_event_id=self._next_event_id("foreground_candidate"),
            created_monotonic_ms=now_mono,
            created_wall_clock_ms=now_wall,
            source_module="fake_qwen_fast_interaction_projection",
        )
        assert emission.candidate_event is not None
        router_result = self._router.emit_decision(
            turn_committed_event=bundle.turn_committed_event,
            asr_frame_event=bundle.asr_frame_event,
            fast_interaction_output_event=emission.output_event,
            router_context=self._router_context(),
            event_id=self._next_event_id("router_decision"),
            task_focus_state_event_id=self._next_event_id("task_focus_state"),
            created_monotonic_ms=now_mono + 2,
            created_wall_clock_ms=now_wall + 2,
        )
        router_event = router_result.router_decision_event
        route = str(router_event["router_decision"])
        task_focus = str(router_event.get("task_focus", ""))
        self.state.router_decision = route
        self.state.task_focus = task_focus
        self.state.foreground_act = effective_proposal.foreground_act
        await self._send_json(
            "route.decided",
            turn_id=turn.turn_id,
            utterance_id=turn.utterance_id,
            router_decision=route,
            task_focus=task_focus,
            confidence=float(router_event.get("confidence", 0.0)),
            evidence_uncertainty=str(router_event.get("evidence_uncertainty", "low")),
            active_task_id=router_event.get("active_task_id"),
            route_hint=provider_proposal.route_hint,
            task_focus_hint=provider_proposal.task_focus_hint,
        )
        await self._timeline(
            "route.decided",
            {
                "router_decision": route,
                "task_focus": task_focus,
                "confidence": router_event.get("confidence"),
            },
        )
        gate = run_fast_foreground_gate(
            self.journal,
            candidate_event=emission.candidate_event,
            fast_interaction_output_event=emission.output_event,
            router_decision_event=router_event,
            context=self._fast_foreground_gate_context(),
            config=FastForegroundGateConfig(
                confidence_threshold=float(self.config.gate_confidence_threshold)
            ),
            event_id_prefix=self._next_event_id("foreground_gate"),
            created_monotonic_ms=now_mono + 4,
            created_wall_clock_ms=now_wall + 4,
        )
        passed = gate.committed_event is not None and gate.discarded_event is None
        gate_status = "passed" if passed else ("discarded" if route != "FAST_ONLY" else "failed")
        self.state.gate_status = gate_status
        gate_fields: dict[str, Any] = {
            "gate_status": gate_status,
            "foreground_act": effective_proposal.foreground_act,
            "risk_class": effective_proposal.risk_class,
            "confidence": effective_confidence,
            "router_decision": route,
            "task_focus": task_focus,
        }
        if gate.gate_event.get("failure_reason") is not None:
            gate_fields["failure_reason"] = str(gate.gate_event["failure_reason"])
        if gate.committed_event is not None:
            gate_fields["output_basis"] = str(gate.committed_event["output_basis"])
        await self._send_json("gate.result", **gate_fields)
        await self._timeline("gate.result", gate_fields)

        mutation: _MutationOutcome | None = None
        if route == "SPAWN_SLOW_TASK":
            mutation = await self._spawn_slow_task(router_event, bundle)
        elif route == "PATCH_ACTIVE_SLOW_TASK":
            mutation = await self._apply_user_patch(router_event, bundle)
        if mutation is not None:
            mutation_event_name = (
                "SLOWTASK_CREATED"
                if route == "SPAWN_SLOW_TASK"
                else "USER_PATCH_RECEIVED"
            )
            mutation_events = [
                event
                for event in self.journal.events()
                if event.get("event_name") == mutation_event_name
                and event.get("caused_by_event_id") == router_event.get("event_id")
            ]
            mutation_event = (
                mutation_events[0]
                if mutation.completed and len(mutation_events) == 1
                else None
            )
            mutation_completion_event = (
                self._patch_mutation_completion_event(mutation_event)
                if route == "PATCH_ACTIVE_SLOW_TASK"
                and mutation_event is not None
                else None
            )
            ack_ready = bool(
                mutation.completed
                and mutation_event is not None
                and (
                    route == "SPAWN_SLOW_TASK"
                    or mutation_completion_event is not None
                )
            )
            gate = commit_deferred_foreground_template(
                self.journal,
                gate_result=gate,
                router_decision_event=router_event,
                output_basis=(
                    "template_ack"
                    if ack_ready
                    else "template_clarify"
                ),
                mutation_event=mutation_event,
                mutation_completion_event=mutation_completion_event,
                fallback_reason=mutation.reason_code,
                event_id_prefix=self._next_event_id(
                    "deferred_foreground"
                ),
                created_monotonic_ms=now_mono + 6,
                created_wall_clock_ms=now_wall + 6,
            )

        if passed:
            candidate = self.quarantine.release(
                context.response_id,
                expected_playback_epoch=self.state.playback_epoch,
            )
            if candidate is None:
                await self._send_json(
                    "degraded",
                    code="candidate_release_failed_closed",
                    output_mode="degraded",
                    playback_epoch=self.state.playback_epoch,
                )
            else:
                await self._release_candidate(
                    candidate.text_deltas,
                    candidate.audio_chunks,
                    response_id=context.response_id,
                    turn_id=turn.turn_id,
                    utterance_id=turn.utterance_id,
                    foreground_act="ANSWER",
                    committed_event_id=str(gate.committed_event["event_id"]),
                )
        else:
            self.quarantine.discard(context.response_id, reason="local_gate_discard")
            if await self.provider.cancel_response():
                self.state.provider_cancel_count += 1
            committed = gate.committed_event
            template = (
                resolve_foreground_template(
                    output_ref=committed.get("output_ref"),
                    output_basis=committed.get("output_basis"),
                    fallback_policy_ref=committed.get("fallback_policy_ref"),
                    router_decision=route,
                )
                if committed is not None
                else None
            )
            if template is not None:
                await self._send_json(
                    "transcript.assistant.delta",
                    text=template.text,
                    turn_id=turn.turn_id,
                    utterance_id=turn.utterance_id,
                    response_id=context.response_id,
                    foreground_act=template.foreground_act,
                    source="controlled_template",
                    commit_ref=str(committed["event_id"]),
                    output_ref=template.template_ref,
                    output_basis=template.output_basis,
                    output_mode="mock",
                )
                await self._send_json(
                    "transcript.assistant.done",
                    text=template.text,
                    turn_id=turn.turn_id,
                    utterance_id=turn.utterance_id,
                    response_id=context.response_id,
                    foreground_act=template.foreground_act,
                    source="controlled_template",
                    commit_ref=str(committed["event_id"]),
                    output_ref=template.template_ref,
                    output_basis=template.output_basis,
                    output_mode="mock",
                )
        context.route_processed = True
        self.state.status = "SLOWTASK" if route in {
            "SPAWN_SLOW_TASK",
            "PATCH_ACTIVE_SLOW_TASK",
        } else "RESPONDING"
        await self._send_state("route_complete")
        await self._send_flow()

    async def _spawn_slow_task(
        self,
        router_event: Mapping[str, Any],
        bundle: RealtimeTurnEvidenceBundle,
    ) -> _MutationOutcome:
        before_count = self._slowtask_canonical_event_count()
        active = self.state.active_task
        if active is not None and active.active_non_terminal:
            await self._send_json_best_effort(
                "safe_error",
                code="single_active_slowtask_violation",
                terminal=False,
                retryable=False,
            )
            return _MutationOutcome(
                kind="spawn_slow_task",
                status="failed",
                canonical_event_count=0,
                reason_code="single_active_slowtask_violation",
            )
        task_id = f"task_qfs_{self._slug}_{bundle.turn_id.rsplit('_', 1)[-1]}"
        now_mono, now_wall = _now_ms()
        try:
            created = self._slow_runtime.create_from_router_spawn(
                router_decision_event=router_event,
                task_id=task_id,
                initial_goal_ref=f"goal://synthetic/qfs/{bundle.turn_id}",
                event_id_prefix=self._next_event_id("slowtask_spawn"),
                created_monotonic_ms=now_mono,
                created_wall_clock_ms=now_wall,
                source_evidence_refs=(
                    f"event://synthetic/qfs/{bundle.asr_frame_event['event_id']}",
                    f"fast-evidence://synthetic/qfs/{bundle.turn_id}",
                ),
            )
            self._slow_runtime.start_planning(
                task_id=task_id,
                plan_version=created.plan_version,
                caused_by_event_id=str(created.produced_events[-1]["event_id"]),
                event_id_prefix=self._next_event_id("slowtask_planning"),
                created_monotonic_ms=now_mono + 2,
                created_wall_clock_ms=now_wall + 2,
                start_task_event_seq=3,
            )
        except Exception:
            appended = self._slowtask_canonical_event_count() - before_count
            reconciled = self._reconcile_active_task_from_journal()
            return _MutationOutcome(
                kind="spawn_slow_task",
                status=("partial_reconciled" if appended > 0 and reconciled else "failed"),
                canonical_event_count=max(0, appended),
                reason_code=(
                    "slowtask_spawn_partial_reconciled"
                    if appended > 0 and reconciled
                    else "slowtask_spawn_failed"
                ),
            )
        appended = self._slowtask_canonical_event_count() - before_count
        reconciled = self._reconcile_active_task_from_journal()
        if reconciled is None or reconciled.task_id != task_id:
            return _MutationOutcome(
                kind="spawn_slow_task",
                status="failed",
                canonical_event_count=max(0, appended),
                reason_code="slowtask_spawn_reconciliation_failed",
            )
        await self._send_slowtask_state_best_effort()
        return _MutationOutcome(
            kind="spawn_slow_task",
            status="completed",
            canonical_event_count=max(0, appended),
            reason_code="slowtask_spawn_completed",
        )

    async def _apply_user_patch(
        self,
        router_event: Mapping[str, Any],
        bundle: RealtimeTurnEvidenceBundle,
        *,
        confirmation_signal_hint: str = "NOT_APPLICABLE",
    ) -> _MutationOutcome:
        before_count = self._slowtask_canonical_event_count()
        task = self.state.active_task
        if task is None or not task.active_non_terminal:
            return _MutationOutcome(
                kind="user_patch",
                status="failed",
                canonical_event_count=0,
                reason_code="patch_requires_active_slowtask",
            )
        scenario = bundle.proposal.scenario
        if (
            self.qwen_enforced
            and task.pending_confirmation_scope is not None
            and confirmation_signal_hint in {"ACCEPT", "REJECT"}
        ):
            patch_type = "confirmation_candidate"
        elif self.qwen_enforced and (
            bundle.proposal.task_focus_hint == "CANCEL_OR_PAUSE_CANDIDATE"
        ):
            patch_type = "cancel_candidate"
        elif self.qwen_enforced and (
            bundle.proposal.task_focus_hint == "NEW_TASK_CANDIDATE"
        ):
            patch_type = "switch_task_candidate"
        else:
            patch_type = _patch_type_for_scenario(
                scenario,
                pending_confirmation=task.pending_confirmation_scope is not None,
            )
        old_plan_version = task.plan_version
        now_mono, now_wall = _now_ms()
        patch_id = f"patch_qfs_{self._slug}_{bundle.turn_id.rsplit('_', 1)[-1]}"
        try:
            received = self._patch_runtime.receive_patch_from_router_decision(
                router_decision_event=router_event,
                turn_committed_event=bundle.turn_committed_event,
                asr_frame_event=bundle.asr_frame_event,
                task_id=task.task_id,
                current_plan_version=task.plan_version,
                next_task_event_seq=task.task_event_seq + 1,
                patch_id=patch_id,
                event_id=self._next_event_id("user_patch_received"),
                evidence_ref=f"evidence://synthetic/qfs/{bundle.turn_id}/patch",
                created_monotonic_ms=now_mono,
                created_wall_clock_ms=now_wall,
                transcript_hint_ref=(
                    str(bundle.asr_frame_event.get("text_ref", "")) or None
                ),
                audio_summary_ref=f"audio-summary://synthetic/qfs/{bundle.turn_id}",
                candidate_patch_types=(patch_type,),
                patch_hint="synthetic_active_task_patch_candidate",
            )
        except Exception:
            return self._partial_mutation_outcome(
                kind="user_patch",
                before_count=before_count,
                partial_reason="user_patch_receive_partial_reconciled",
                failed_reason="user_patch_receive_failed",
            )
        confirmation_signal: str | None = None
        if patch_type == "confirmation_candidate":
            if self.qwen_enforced:
                confirmation_signal = {
                    "ACCEPT": "accepted",
                    "REJECT": "rejected",
                }.get(confirmation_signal_hint)
                if confirmation_signal is None:
                    return self._partial_mutation_outcome(
                        kind="user_patch",
                        before_count=before_count,
                        partial_reason=(
                            "confirmation_signal_partial_reconciled"
                        ),
                        failed_reason=(
                            "confirmation_signal_not_explicit_failed_closed"
                        ),
                    )
            else:
                confirmation_signal = (
                    "rejected" if scenario == "reject_confirmation" else "accepted"
                )
        try:
            interpreted = self._slow_runtime.interpret_user_patch(
                user_patch_event=received.user_patch_event,
                event_id_prefix=self._next_event_id("user_patch_interpret"),
                created_monotonic_ms=now_mono + 1,
                created_wall_clock_ms=now_wall + 1,
                current_lifecycle_state=task.lifecycle,
                confirmation_id=f"confirmation_qfs_{self._slug}_{bundle.turn_id}",
                prompt_ref=f"prompt://synthetic/qfs/{bundle.turn_id}/confirm",
                pending_confirmation_id=task.pending_confirmation_id,
                pending_confirmation_scope=task.pending_confirmation_scope,
                confirmation_signal=confirmation_signal,
                authorization_ref=(
                    f"authorization://synthetic/qfs/{bundle.turn_id}/accepted"
                    if confirmation_signal == "accepted"
                    else None
                ),
                return_to_state="PLANNING",
            )
        except (ValueError, SlowTaskStateError):
            return self._partial_mutation_outcome(
                kind="user_patch",
                before_count=before_count,
                partial_reason="user_patch_interpretation_partial_reconciled",
                failed_reason="user_patch_interpretation_failed_closed",
            )
        except Exception:
            return self._partial_mutation_outcome(
                kind="user_patch",
                before_count=before_count,
                partial_reason="user_patch_append_partial_reconciled",
                failed_reason="user_patch_append_failed",
            )
        reconciled = self._reconcile_active_task_from_journal()
        appended = self._slowtask_canonical_event_count() - before_count
        if reconciled is None or reconciled.task_id != task.task_id:
            return _MutationOutcome(
                kind="user_patch",
                status="failed",
                canonical_event_count=max(0, appended),
                reason_code="user_patch_reconciliation_failed",
            )
        await self._send_json_best_effort(
            "userpatch.accepted",
            patch_id=patch_id,
            task_id=reconciled.task_id,
            observed_plan_version=old_plan_version,
            plan_version=reconciled.plan_version,
            task_event_seq=reconciled.task_event_seq,
            candidate_patch_type=patch_type,
        )
        await self._send_slowtask_state_best_effort()
        return _MutationOutcome(
            kind="user_patch",
            status="completed",
            canonical_event_count=max(0, appended),
            reason_code="user_patch_completed",
        )

    async def _release_candidate(
        self,
        text_deltas: tuple[str, ...],
        audio_chunks: tuple[bytes, ...],
        *,
        response_id: str,
        turn_id: str,
        utterance_id: str,
        foreground_act: str,
        committed_event_id: str,
    ) -> None:
        for delta in text_deltas:
            await self._send_json(
                "transcript.assistant.delta",
                text=delta,
                turn_id=turn_id,
                utterance_id=utterance_id,
                response_id=response_id,
                foreground_act=foreground_act,
                source="provider_candidate",
                output_mode="mock",
            )
        await self._send_json(
            "transcript.assistant.done",
            text="".join(text_deltas),
            turn_id=turn_id,
            utterance_id=utterance_id,
            response_id=response_id,
            foreground_act=foreground_act,
            source="provider_candidate",
            output_mode="mock",
        )
        if not self.state.playback_enabled or not audio_chunks:
            return
        batch = _PlaybackBatch(
            response_id=response_id,
            turn_id=turn_id,
            utterance_id=utterance_id,
            playback_epoch=self.state.playback_epoch,
            audio_chunks=audio_chunks,
            committed_event_id=committed_event_id,
        )
        if self._output_queue.full():
            self.state.dropped_output_frames += len(audio_chunks)
            await self._send_flow()
            return
        self._output_queue.put_nowait(batch)

    async def _play_batch(self, batch: _PlaybackBatch) -> None:
        async with self._state_lock:
            if batch.playback_epoch != self.state.playback_epoch:
                self.state.discarded_late_audio_frames += len(batch.audio_chunks)
                await self._send_flow()
                return
            now_mono, now_wall = _now_ms()
            playback_span_id = f"playback_{self._slug}_{batch.playback_epoch}_{self._event_counter + 1}"
            started = self.journal.append(
                event_name="PLAYBACK_SPAN_STARTED",
                event_id=self._next_event_id("playback_started"),
                source_module="qwen_realtime_fast_slow_playback",
                caused_by_event_id=batch.committed_event_id,
                created_monotonic_ms=now_mono,
                created_wall_clock_ms=now_wall,
                trace_redaction_level="metadata_only",
                playback_span_id=playback_span_id,
                tts_stream_ref=f"tts-stream://synthetic/qfs/{playback_span_id}",
                playback_epoch=batch.playback_epoch,
                response_id=batch.response_id,
            )
            self._active_playback_span_id = playback_span_id
            self._active_playback_offset_ms = 0
            self.state.status = "RESPONDING"
            await self._send_json(
                "playback.begin",
                playback_epoch=batch.playback_epoch,
                response_id=batch.response_id,
                playback_span_id=playback_span_id,
                sample_rate=24_000,
                channels=1,
            )
            sent_chunks = 0
            for chunk in batch.audio_chunks:
                if batch.playback_epoch != self.state.playback_epoch:
                    self.state.discarded_late_audio_frames += len(batch.audio_chunks) - sent_chunks
                    await self._send_flow()
                    return
                await self.browser_sink.send_bytes(pack_output_audio(batch.playback_epoch, chunk))
                sent_chunks += 1
                self._active_playback_offset_ms += _pcm_duration_ms(chunk, sample_rate=24_000)
            self.journal.append(
                event_name="PLAYBACK_FINISHED",
                event_id=self._next_event_id("playback_finished"),
                source_module="qwen_realtime_fast_slow_playback",
                caused_by_event_id=str(started["event_id"]),
                created_monotonic_ms=now_mono + 1,
                created_wall_clock_ms=now_wall + 1,
                trace_redaction_level="metadata_only",
                playback_span_id=playback_span_id,
                final_playback_offset_ms=self._active_playback_offset_ms,
                playback_epoch=batch.playback_epoch,
            )
            self._active_playback_span_id = None
            self._active_playback_offset_ms = 0
            await self._send_json(
                "playback.end",
                playback_epoch=batch.playback_epoch,
                response_id=batch.response_id,
                playback_span_id=playback_span_id,
                status="completed",
            )

    async def _interrupt_locked(
        self, *, reason: str, audio_span_id: str | None
    ) -> None:
        started = time.monotonic()
        self.state.playback_epoch += 1
        interrupt_epoch = self.state.playback_epoch
        self._latest_shadow_turn_id = None
        active_voice_response_id = self._voice_active_response_id
        self._voice_active_response_id = None
        for response_id, lifecycle in self._voice_response_lifecycles.items():
            if lifecycle.terminal_status is None:
                lifecycle.output_eligible = False
                mark_ineligible = getattr(
                    self.provider, "mark_response_output_ineligible", None
                )
                if callable(mark_ineligible):
                    mark_ineligible(response_id)
        if reason != "speech_started":
            invalidate_input = getattr(self.provider, "invalidate_current_input", None)
            if callable(invalidate_input):
                invalidate_input(reason=reason)
        self.quarantine.clear(reason=reason)
        self._drain_output_queue()
        self._spawn_background(
            self._cancel_interrupt_providers_outside_lock(
                interrupt_epoch=interrupt_epoch,
                response_id=active_voice_response_id,
            ),
            name=f"qfs-interrupt-cancel-{self.session_id}-{interrupt_epoch}",
        )
        playback_span_id = self._active_playback_span_id
        if playback_span_id is not None:
            now_mono, now_wall = _now_ms()
            assert self._session_started_event is not None
            barge = self.journal.append(
                event_name="BARGE_IN_CANDIDATE",
                event_id=self._next_event_id("barge_in_candidate"),
                source_module=self._voice_source_module,
                caused_by_event_id=str(self.journal.events()[-1]["event_id"]),
                created_monotonic_ms=now_mono,
                created_wall_clock_ms=now_wall,
                trace_redaction_level="metadata_only",
                audio_span_id=audio_span_id or f"interrupt_audio_{self._event_counter}",
                playback_span_id=playback_span_id,
                playback_offset_ms=self._active_playback_offset_ms,
                echo_likelihood=0.0,
                vad_confidence=0.99,
                barge_in_confidence=0.99,
            )
            truncate = self._interaction.request_truncate_for_barge_in(
                barge,
                interrupt_event_id=self._next_event_id("interrupt_candidate"),
                truncate_request_event_id=self._next_event_id("truncate_requested"),
                created_monotonic_ms=now_mono + 1,
                created_wall_clock_ms=now_wall + 1,
                cutoff_playback_offset_ms=self._active_playback_offset_ms,
            )
            self.journal.append(
                event_name="TTS_TRUNCATED",
                event_id=self._next_event_id("tts_truncated"),
                source_module="qwen_realtime_fast_slow_playback",
                caused_by_event_id=str(truncate.truncate_requested["event_id"]),
                created_monotonic_ms=now_mono + 2,
                created_wall_clock_ms=now_wall + 2,
                trace_redaction_level="metadata_only",
                playback_span_id=playback_span_id,
                actual_stop_offset_ms=self._active_playback_offset_ms,
                truncate_request_event_id=str(truncate.truncate_requested["event_id"]),
            )
            self._active_playback_span_id = None
            self._active_playback_offset_ms = 0
        self.state.clear_latency_ms = max(0, int((time.monotonic() - started) * 1_000))
        self.state.status = "INTERRUPTED"
        await self._send_json(
            "playback.clear",
            playback_epoch=self.state.playback_epoch,
            reason=reason,
            clear_latency_ms=self.state.clear_latency_ms,
            discarded_late_audio_frames=self.state.discarded_late_audio_frames,
            dropped_output_frames=self.state.dropped_output_frames,
        )

    async def _cancel_interrupt_providers_outside_lock(
        self, *, interrupt_epoch: int, response_id: str | None
    ) -> None:
        control_cancelled = False
        control_failed = False
        cancel_control = getattr(self.shadow_provider, "cancel_active_request", None)
        if self.control_enabled and callable(cancel_control):
            try:
                control_cancelled = bool(await cancel_control())
            except Exception:
                control_failed = True
        voice_cancelled = False
        if response_id is not None:
            try:
                voice_cancelled = bool(await self.provider.cancel_response())
            except Exception:
                voice_cancelled = False
        async with self._state_lock:
            if self._closed:
                return
            # Cancellation belongs to the fenced generation.  A later turn
            # may already be live, so never mutate its routing/status fields.
            generation_is_current = interrupt_epoch == self.state.playback_epoch
            if control_failed:
                self._shadow_local_error_count += 1
            if control_cancelled:
                self.state.control_cancel_count += 1
            if voice_cancelled:
                self.state.provider_cancel_count += 1
                if self.qwen_enforced:
                    self.state.voice_cancel_count += 1
            if (
                response_id is not None
                and generation_is_current
                and response_id in self._voice_response_lifecycles
            ):
                self._voice_response_lifecycles[response_id].cancel_requested = True
            await self._refresh_shadow_counters()
            await self._refresh_voice_suppression_counters()
        await self._timeline(
            "playback.clear",
            {
                "playback_epoch": self.state.playback_epoch,
                "clear_latency_ms": self.state.clear_latency_ms,
                "discarded_late_audio_frames": self.state.discarded_late_audio_frames,
                "dropped_output_frames": self.state.dropped_output_frames,
            },
        )

    def _router_context(self) -> RouterContext:
        task = self.state.active_task
        if task is None:
            return RouterContext(task_focus_snapshot=TaskFocusSnapshot())
        return RouterContext(
            task_focus_snapshot=TaskFocusSnapshot(
                active_task_id=task.task_id,
                lifecycle_phase=task.lifecycle,
                terminal_status=task.terminal_status,
                current_plan_version=task.plan_version,
                pending_confirmation_scope=task.pending_confirmation_scope,
            )
        )

    def _slowtask_canonical_event_count(self) -> int:
        return sum(
            1
            for event in self.journal.events()
            if event.get("event_name") in SLOWTASK_EVENT_NAMES
        )

    def _patch_mutation_completion_event(
        self,
        patch_event: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        patch_seq = patch_event.get("task_event_seq")
        plan_version = patch_event.get("plan_version")
        task_id = patch_event.get("task_id")
        if (
            not isinstance(patch_seq, int)
            or isinstance(patch_seq, bool)
            or not isinstance(plan_version, int)
            or isinstance(plan_version, bool)
            or not isinstance(task_id, str)
            or not task_id
        ):
            return None
        matches = [
            event
            for event in self.journal.events()
            if event.get("event_name") == "SLOWTASK_STATE_CHANGED"
            and event.get("task_id") == task_id
            and event.get("task_event_seq") == patch_seq + 5
            and event.get("plan_version") == plan_version + 1
            and event.get("to_state") == "PLANNING"
        ]
        return matches[0] if len(matches) == 1 else None

    def _reconcile_active_task_from_journal(self) -> ActiveSlowTaskState | None:
        replay_state = SlowTaskState()
        try:
            for event in self.journal.events():
                replay_state.reduce_event(event)
        except (KeyError, TypeError, ValueError, SlowTaskStateError):
            return None
        if not replay_state.tasks:
            self.state.active_task = None
            return None
        non_terminal = [
            task for task in replay_state.tasks.values() if not task.is_terminal
        ]
        if len(non_terminal) > 1:
            return None
        if non_terminal:
            record = non_terminal[0]
        else:
            last_task_id = replay_state.last_task_id
            if last_task_id is None:
                self.state.active_task = None
                return None
            record = replay_state.tasks[last_task_id]
        confirmation = record.confirmation_state
        pending_confirmation_id = confirmation.pending_confirmation_id
        reconciled = ActiveSlowTaskState(
            task_id=record.task_id,
            lifecycle=record.lifecycle_state,
            plan_version=record.current_plan_version,
            task_event_seq=record.current_task_event_seq,
            terminal_status=record.terminal_outcome,
            pending_confirmation_id=pending_confirmation_id,
            pending_confirmation_scope=(
                confirmation.confirmation_scope
                if pending_confirmation_id is not None
                else None
            ),
        )
        self.state.active_task = reconciled
        return reconciled

    def _partial_mutation_outcome(
        self,
        *,
        kind: str,
        before_count: int,
        partial_reason: str,
        failed_reason: str,
    ) -> _MutationOutcome:
        appended = max(0, self._slowtask_canonical_event_count() - before_count)
        reconciled = self._reconcile_active_task_from_journal()
        partial = appended > 0 and reconciled is not None
        return _MutationOutcome(
            kind=kind,
            status="partial_reconciled" if partial else "failed",
            canonical_event_count=appended,
            reason_code=partial_reason if partial else failed_reason,
        )

    def _fast_foreground_gate_context(
        self,
        *,
        router_decision_event: Mapping[str, Any] | None = None,
    ) -> FastForegroundGateContext:
        task = self.state.active_task
        active = bool(task is not None and task.active_non_terminal)
        capability_owner = (
            self.shadow_provider if self.control_enabled else self.provider
        )
        profile = getattr(capability_owner, "profile", None)
        # In the enforced Qwen topology the candidate crosses the provider
        # evidence boundary even when provider-free tests substitute the
        # deterministic fake transport.  Transport provenance must not turn a
        # provider-shaped candidate into a locally trusted one.
        provider_generated = self.qwen_enforced
        policy = (
            CandidatePolicyDecision.quarantined_provider()
            if provider_generated
            else CandidatePolicyDecision.trusted_synthetic()
        )
        capability_snapshot_ref = (
            str(self._session_started_event["capability_snapshot_ref"])
            if self._session_started_event is not None
            else None
        )
        events = self.journal.events()
        task_focus_events = [
            event
            for event in events
            if event.get("event_name") == "TASK_FOCUS_STATE_UPDATED"
            and (
                router_decision_event is None
                or event.get("router_decision_event_id")
                == router_decision_event.get("event_id")
            )
        ]
        task_focus_ref = (
            str(task_focus_events[-1]["event_id"]) if task_focus_events else None
        )
        task_focus = (
            str(task_focus_events[-1].get("last_focus_decision", ""))
            if task_focus_events
            else None
        )
        interaction_state = InteractionState()
        for event in events:
            interaction_state.reduce_event(event)
        interaction_state_ref = interaction_state.last_interaction_event_id
        target_turn_matches = bool(
            router_decision_event is None
            or interaction_state.current_turn_id
            == router_decision_event.get("turn_id")
        )
        router_task_matches = True
        if router_decision_event is not None:
            route = str(router_decision_event.get("router_decision", ""))
            router_task_id = router_decision_event.get("active_task_id")
            if route == "PATCH_ACTIVE_SLOW_TASK":
                router_task_matches = bool(
                    active
                    and task is not None
                    and router_task_id == task.task_id
                )
            elif route == "SPAWN_SLOW_TASK":
                router_task_matches = router_task_id in (None, "")
        pending_confirmation = bool(
            active and task is not None and task.pending_confirmation_scope
        )
        return FastForegroundGateContext(
            authority_mode=(
                "live_runtime" if provider_generated else "trusted_synthetic_eval"
            ),
            authority_binding_status=(
                "bound"
                if (
                    capability_snapshot_ref is not None
                    and len(task_focus_events) == 1
                    and interaction_state_ref is not None
                    and target_turn_matches
                    and router_task_matches
                )
                else "missing"
            ),
            interaction_state=interaction_state.turn_phase,
            interaction_state_ref=interaction_state_ref,
            task_focus=task_focus,
            task_focus_snapshot_ref=task_focus_ref,
            has_active_slowtask=active,
            active_task_id=(task.task_id if active and task else None),
            active_slowtask_lifecycle=(task.lifecycle if active and task else None),
            pending_confirmation=pending_confirmation,
            pending_confirmation_id=(
                task.pending_confirmation_id
                if pending_confirmation and task is not None
                else None
            ),
            pending_confirmation_scope=(
                task.pending_confirmation_scope
                if pending_confirmation and task is not None
                else None
            ),
            active_plan_version=(task.plan_version if active and task else None),
            active_task_event_seq=(
                task.task_event_seq if active and task else None
            ),
            capability_snapshot_ref=capability_snapshot_ref,
            capability_health_status=str(
                getattr(profile, "health_status", "unavailable")
            ),
            capability_output_mode=str(
                getattr(profile, "output_mode", "degraded")
            ),
            capability_verification_status=str(
                getattr(profile, "verification_status", "not_executed")
            ),
            candidate_policy_decision=policy,
            schema_valid=(
                not self.control_enabled or self.state.schema_status == "valid"
            ),
            confidence_threshold=float(self.config.gate_confidence_threshold),
        )

    async def _send_slowtask_state(self) -> None:
        task = self.state.active_task
        if task is None:
            return
        await self._send_json("slowtask.state", **task.to_metadata(), output_mode="mock")
        await self._timeline("slowtask.state", task.to_metadata())

    async def _send_slowtask_state_best_effort(self) -> None:
        task = self.state.active_task
        if task is None:
            return
        await self._send_json_best_effort(
            "slowtask.state", **task.to_metadata(), output_mode="mock"
        )
        await self._timeline_best_effort("slowtask.state", task.to_metadata())

    async def _send_state(self, reason: str) -> None:
        output_mode = str(getattr(self.provider.profile, "output_mode", "degraded"))
        await self._send_json(
            "state.changed",
            **self.state.to_metadata(),
            reason=reason,
            output_mode=output_mode,
        )

    async def _send_flow(self) -> None:
        await self._send_json(
            "flow.changed",
            dropped_input_frames=self.state.dropped_input_frames,
            dropped_output_frames=self.state.dropped_output_frames,
            discarded_late_audio_frames=self.state.discarded_late_audio_frames,
            input_queue_depth=self.input_queue_depth,
            output_queue_depth=self.output_queue_depth,
            quarantine=self.quarantine.counters(),
            playback_epoch=self.state.playback_epoch,
        )

    async def _send_json(self, message_type: str, **fields: Any) -> None:
        await self.browser_sink.send_json(server_message(message_type, **fields))

    async def _await_browser_projection_best_effort(
        self, projection: Any
    ) -> bool:
        try:
            await asyncio.wait_for(
                projection,
                timeout=self.config.browser_projection_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        return True

    async def _send_json_best_effort(self, message_type: str, **fields: Any) -> bool:
        try:
            await self._send_json(message_type, **fields)
        except Exception:
            return False
        return True

    async def _timeline(self, label: str, fields: Mapping[str, Any]) -> None:
        self._timeline_counter += 1
        entry = {
            "event": label,
            "index": self._timeline_counter,
            "metadata": metadata_only_copy(fields),
        }
        self.metadata_timeline.append(entry)
        await self._send_json("timeline.metadata", **entry)

    async def _timeline_best_effort(
        self, label: str, fields: Mapping[str, Any]
    ) -> bool:
        try:
            await self._timeline(label, fields)
        except Exception:
            return False
        return True

    def _spawn_background(self, coroutine: Any, *, name: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._consume_background_completion)
        return task

    def _consume_background_completion(self, task: asyncio.Task[Any]) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            # Background failures are normalized by the owning coroutine. The
            # callback only guarantees the exception is retrieved.
            return

    def _remember_response(self, context: _ResponseContext) -> None:
        if len(self._response_order) == self._response_order.maxlen:
            oldest = self._response_order.popleft()
            self._responses.pop(oldest, None)
        self._response_order.append(context.response_id)
        self._responses[context.response_id] = context

    def _drain_output_queue(self) -> int:
        dropped = 0
        while True:
            try:
                batch = self._output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            dropped += len(batch.audio_chunks)
            self._output_queue.task_done()
        self.state.dropped_output_frames += dropped
        return dropped

    def _drain_input_queue(self) -> int:
        drained = 0
        while True:
            try:
                self._input_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            drained += 1
            self._input_queue.task_done()
        return drained

    def _drain_shadow_queue(self) -> int:
        drained = 0
        while True:
            try:
                self._shadow_request_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            drained += 1
            self._shadow_request_queue.task_done()
        return drained

    def _next_event_id(self, label: str) -> str:
        self._event_counter += 1
        safe_label = "".join(char if char.isalnum() else "_" for char in label).strip("_")
        return f"evt_qfs_{self._slug}_{self._event_counter:06d}_{safe_label}"

    @property
    def _slug(self) -> str:
        return "".join(
            char.lower() if char.isalnum() else "_" for char in self.session_id
        ).strip("_") or "session"

    @property
    def _voice_source_module(self) -> str:
        return (
            "qwen_voice_session_projection"
            if self.provider_mode == "qwen"
            else "fake_qwen_voice_projection"
        )


def _local_foreground_act(route: str, focus: str) -> str:
    if focus == "AMBIGUOUS":
        return "CLARIFY"
    if route == "SPAWN_SLOW_TASK":
        return "ACK_SLOW"
    if route == "PATCH_ACTIVE_SLOW_TASK":
        return "ACK_PATCH"
    if route == "IGNORE":
        return "SILENCE"
    return "ANSWER"


def _patch_type_for_scenario(scenario: str, *, pending_confirmation: bool) -> str:
    if pending_confirmation:
        return "confirmation_candidate"
    if scenario == "cancel":
        return "cancel_candidate"
    if scenario in {"confirm", "reject_confirmation"}:
        return "confirmation_candidate"
    return "constraint_update_candidate"


def _optional_confidence(value: object) -> float | None:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError("confidence_invalid")
    return float(value)


def _optional_enum(value: object, allowed: set[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("synthetic_override_invalid")
    return value


def _pcm_duration_ms(pcm16le: bytes, *, sample_rate: int) -> int:
    return max(0, len(pcm16le) * 1_000 // (2 * sample_rate))


def _now_ms() -> tuple[int, int]:
    return int(time.monotonic() * 1_000), int(time.time() * 1_000)


__all__ = [
    "ActiveSlowTaskState",
    "BrowserSink",
    "CoordinatorConfig",
    "CoordinatorState",
    "RealtimeSessionCoordinator",
]
