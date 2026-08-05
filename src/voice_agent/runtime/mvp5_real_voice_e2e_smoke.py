from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
from voice_agent.router.router import MVP1_ROUTER_DECISIONS
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateContext,
)
from voice_agent.runtime.mvp5_live_router_runner import (
    MVP5ActiveSlowTaskContext,
    MVP5LiveRouterConfig,
    MVP5LiveRouteResult,
    run_mvp5_live_router_runner,
)
from voice_agent.runtime.mvp5_live_voice_evidence import (
    MVP5LiveVoiceEvidenceConfig,
    run_mvp5_live_voice_evidence,
)


class MVP5RealVoiceE2ESmokeError(ValueError):
    """Raised when MVP-5 real voice E2E smoke metadata would be unsafe."""


@dataclass(frozen=True)
class MVP5SmokePackCase:
    case_id: str
    local_wav: Path
    expected_route: str
    active_task_context: MVP5ActiveSlowTaskContext | None = None


TransportPair = tuple[object, object]
SingleTransportFactory = Callable[[], TransportPair]
PackTransportFactory = Callable[[MVP5SmokePackCase], TransportPair]

_EXPECTED_ROUTE_CHOICES = ("auto", *tuple(sorted(MVP1_ROUTER_DECISIONS)))
_PACK_EXPECTED_ROUTES = frozenset(
    {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"}
)
_REQUESTS_PER_CASE = 2
_FALSE_SAFETY_FLAGS = (
    "raw_audio_included",
    "raw_transcript_included",
    "raw_provider_body_included",
    "prompt_dump_included",
    "secret_included",
    "local_wav_path_included",
    "local_pack_path_included",
    "replay_reruns_provider",
    "real_tts_used",
)
_FORBIDDEN_KEYS = {
    "audio_bytes",
    "raw_audio",
    "raw_audio_bytes",
    "wav_bytes",
    "pcm_samples",
    "raw_transcript",
    "transcript_text",
    "provider_body",
    "provider_payload",
    "provider_request",
    "provider_response",
    "provider_headers",
    "authorization_header",
    "cookie",
    "credential",
    "token",
    "api_key",
    "prompt_dump",
    "local_wav",
    "local_wav_path",
    "local_pack_path",
    "pack_json",
    "approval_packet_path",
    "file_name",
    "filename",
}
_UNSAFE_STRING_MARKERS = (
    "file://",
    "data:",
    "/users/",
    "\\users\\",
    "/private/",
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    ".env",
    "authorization:",
    "authorization=",
    "cookie:",
    "api_key=",
    "token=",
    "bearer ",
    "raw transcript",
    "provider body",
    "provider payload",
    "prompt dump",
)


def run_mvp5_real_voice_e2e_single(
    *,
    local_wav: str | Path,
    live_provider: bool,
    allow_local_wav: bool,
    approval_packet: Mapping[str, Any],
    expected_route: str = "auto",
    run_id: str = "mvp5-real-voice-e2e-single",
    env: Mapping[str, str] | None = None,
    asr_transport: object | None = None,
    thinker_transport: object | None = None,
    fast_interaction_transport: object | None = None,
    fast_interaction_enabled: bool = False,
    audio_native_thinker_enabled: bool = True,
    asr_observation_enabled: bool = False,
    allow_fast_interaction_asr_text_fallback: bool = False,
    active_task_context: MVP5ActiveSlowTaskContext | None = None,
) -> dict[str, Any]:
    run_started = time.monotonic()
    run_id = _require_safe_token(run_id, "run_id")
    approval_packet = _require_mapping(approval_packet, "approval_packet")
    expected_route = _normalize_expected_route(expected_route, allow_auto=True)
    if expected_route == "PATCH_ACTIVE_SLOW_TASK" and active_task_context is None:
        raise MVP5RealVoiceE2ESmokeError(
            "PATCH_ACTIVE_SLOW_TASK expected route requires active task context"
        )
    if active_task_context is not None and not any(
        transport is not None
        for transport in (
            asr_transport,
            thinker_transport,
            fast_interaction_transport,
        )
    ):
        raise MVP5RealVoiceE2ESmokeError(
            "real-provider active task authority requires a canonical session journal"
        )
    credential_env_var_name = _credential_env_var_name(approval_packet)

    router_config = MVP5LiveRouterConfig(
        run_id=run_id,
        expected_route=expected_route,
        active_task_context=active_task_context,
        fast_foreground_gate_context=_live_fast_gate_context(
            active_task_context=active_task_context
        ),
    )
    fast_path_latency: dict[str, int] = {}

    def on_fast_evidence_ready(
        partial_evidence: Any,
        journal: InMemoryEventJournal,
    ) -> MVP5LiveRouteResult:
        _append_smoke_active_task_authority(journal, active_task_context)
        result = run_mvp5_live_router_runner(
            partial_evidence,
            config=router_config,
            journal=journal,
        )
        if result.router_ms is not None:
            fast_path_latency["router_ms"] = result.router_ms
        if result.foreground_gate_ms is not None:
            fast_path_latency["foreground_gate_ms"] = result.foreground_gate_ms
        if result.foreground_output_finalize_ms is not None:
            fast_path_latency["foreground_output_finalize_ms"] = (
                result.foreground_output_finalize_ms
            )
        fast_path_latency["fast_answer_ready_offset_ms"] = _elapsed_ms(run_started)
        return result

    evidence = run_mvp5_live_voice_evidence(
        local_wav=local_wav,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id=run_id,
            live_provider=live_provider,
            allow_local_wav=allow_local_wav,
            approval_packet=approval_packet,
            credential_env_var_name=credential_env_var_name,
            requested_provider_calls=_single_run_provider_call_budget(
                fast_interaction_enabled=fast_interaction_enabled,
                asr_observation_enabled=asr_observation_enabled,
                allow_fast_interaction_asr_text_fallback=allow_fast_interaction_asr_text_fallback,
            ),
            max_provider_calls=_positive_int(
                approval_packet.get("max_provider_calls"),
                "max_provider_calls",
            ),
            timeout_ms=_positive_int(approval_packet.get("timeout_ms"), "timeout_ms"),
            fast_interaction_enabled=fast_interaction_enabled,
            audio_native_thinker_enabled=audio_native_thinker_enabled,
            asr_observation_enabled=asr_observation_enabled,
            allow_fast_interaction_asr_text_fallback=allow_fast_interaction_asr_text_fallback,
        ),
        env={} if env is None else env,
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
        fast_interaction_transport=fast_interaction_transport,
        on_fast_evidence_ready=(
            on_fast_evidence_ready
            if fast_interaction_enabled and asr_observation_enabled
            else None
        ),
    )
    evidence_latency_debug = _normalize_latency_debug(
        getattr(evidence, "latency_debug", {}),
    )
    evidence_latency_debug.update(fast_path_latency)
    if asr_observation_enabled:
        evidence_latency_debug["qa_pair_ready_offset_ms"] = _elapsed_ms(run_started)
    thinker_transient_asr_text_used = bool(
        getattr(evidence, "thinker_transient_asr_text_used", False)
    )
    if evidence.status == "evidence_failed":
        metadata = _incomplete_evidence_metadata(
            evidence=evidence,
            run_id=run_id,
            expected_route=expected_route,
        )
        metadata["latency_debug"] = evidence_latency_debug
        metadata["thinker_transient_asr_text_used"] = thinker_transient_asr_text_used
        metadata["fast_interaction_enabled"] = fast_interaction_enabled
        metadata["fast_interaction_status"] = (
            "completed"
            if getattr(evidence, "fast_interaction_output_mode", None)
            else "failed"
            if fast_interaction_enabled
            else "not_run"
        )
        _validate_smoke_metadata(metadata)
        return metadata

    precomputed_route_result = getattr(evidence, "fast_path_result", None)
    if isinstance(precomputed_route_result, MVP5LiveRouteResult):
        route_result = replace(
            precomputed_route_result,
            events=tuple(evidence.events),
        )
    else:
        route_journal = _journal_from_smoke_evidence(evidence.events)
        _append_smoke_active_task_authority(
            route_journal,
            active_task_context,
        )
        route_result = run_mvp5_live_router_runner(
            evidence,
            config=router_config,
            journal=route_journal,
        )
        if route_result.router_ms is not None:
            evidence_latency_debug["router_ms"] = route_result.router_ms
        if route_result.foreground_gate_ms is not None:
            evidence_latency_debug["foreground_gate_ms"] = route_result.foreground_gate_ms
        if route_result.foreground_output_finalize_ms is not None:
            evidence_latency_debug["foreground_output_finalize_ms"] = (
                route_result.foreground_output_finalize_ms
            )

    metadata = route_result.to_metadata()
    metadata.update(
        {
            "run_id": run_id,
            "mode": "single",
            "input_source": "local_wav_opt_in",
            "asr_output_mode": evidence.asr_output_mode,
            "thinker_output_mode": evidence.thinker_output_mode,
            "fast_interaction_output_mode": getattr(
                evidence,
                "fast_interaction_output_mode",
                None,
            ),
            "fast_interaction_enabled": fast_interaction_enabled,
            "fast_interaction_status": (
                "completed"
                if getattr(evidence, "fast_interaction_output_mode", None)
                else "failed"
                if fast_interaction_enabled
                else "not_run"
            ),
            "local_wav_opt_in_used": evidence.local_wav_opt_in_used,
            "live_provider_approval_used": evidence.live_provider_approval_used,
            "provider_headers_included": False,
            "local_pack_path_included": False,
            "approval_packet_path_included": False,
            "thinker_transient_asr_text_used": thinker_transient_asr_text_used,
            "asr_observation_enabled": getattr(
                evidence,
                "asr_observation_enabled",
                False,
            ),
            "asr_observation_status": getattr(
                evidence,
                "asr_observation_status",
                "not_run",
            ),
            "asr_observation_event_id": (
                evidence.asr_event_id
                if getattr(evidence, "asr_observation_enabled", False)
                else None
            ),
            "latency_debug": evidence_latency_debug,
        }
    )
    if evidence.safe_refs:
        metadata["safe_refs"] = list(evidence.safe_refs)
    metadata.update(_asr_question_projection(evidence))
    metadata.update(_fast_interaction_projection(evidence))
    _validate_smoke_metadata(metadata)
    return metadata


def _live_fast_gate_context(
    *, active_task_context: MVP5ActiveSlowTaskContext | None
) -> FastForegroundGateContext:
    """Bind the live smoke to fail-closed provider candidate provenance.

    Interaction and task-focus values are replaced from canonical journal
    events by the live Router runner.  The remaining fields are locally owned
    execution/capability facts; none are accepted from provider payloads.
    """

    pending = bool(
        active_task_context is not None
        and active_task_context.pending_confirmation_scope is not None
    )
    return FastForegroundGateContext(
        authority_mode="live_runtime",
        authority_binding_status="bound",
        interaction_state=None,
        interaction_state_ref=None,
        task_focus=None,
        task_focus_snapshot_ref=None,
        has_active_slowtask=active_task_context is not None,
        active_task_id=(active_task_context.task_id if active_task_context else None),
        active_slowtask_lifecycle=(
            active_task_context.lifecycle_phase if active_task_context else None
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
        capability_output_mode="real",
        capability_verification_status="provider_free_verified",
        candidate_policy_decision=CandidatePolicyDecision.quarantined_provider(),
        schema_valid=True,
        confidence_threshold=0.8,
    )


def _journal_from_smoke_evidence(
    events: Sequence[Mapping[str, Any]],
) -> InMemoryEventJournal:
    if not events:
        raise MVP5RealVoiceE2ESmokeError("evidence events are required")
    journal = InMemoryEventJournal(
        session_id=str(events[0]["session_id"]),
        conversation_id=str(events[0]["conversation_id"]),
    )
    for event in events:
        journal._append_validated_event(dict(event))
    return journal


def _append_smoke_active_task_authority(
    journal: InMemoryEventJournal,
    active_task_context: MVP5ActiveSlowTaskContext | None,
) -> None:
    """Append the local smoke fixture's canonical current SlowTask state."""

    if active_task_context is None:
        return
    if (
        active_task_context.current_plan_version != 1
        or active_task_context.current_task_event_seq != 4
        or active_task_context.lifecycle_phase != "PLANNING"
        or active_task_context.terminal_status is not None
        or active_task_context.pending_confirmation_id is not None
        or active_task_context.pending_confirmation_scope is not None
    ):
        raise MVP5RealVoiceE2ESmokeError(
            "smoke active task authority must be canonical PLANNING plan 1 sequence 4"
        )
    if any(
        event.get("event_name") == "SLOWTASK_CREATED"
        and event.get("task_id") == active_task_context.task_id
        for event in journal.events()
    ):
        return

    last = journal.events()[-1]
    monotonic_ms = int(last["created_monotonic_ms"])
    wall_clock_ms = int(last["created_wall_clock_ms"])
    task_id = active_task_context.task_id
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip("-")
    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id=f"evt_smoke_{safe_task_id}_authority_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(last["event_id"]),
        created_monotonic_ms=monotonic_ms + 1,
        created_wall_clock_ms=wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref=f"goal://synthetic/mvp5/{safe_task_id}",
    )
    created_state = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"evt_smoke_{safe_task_id}_authority_created_state",
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
        reason="trusted_synthetic_smoke_authority",
    )
    planning = journal.append(
        event_name="PLANNING_STARTED",
        event_id=f"evt_smoke_{safe_task_id}_authority_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created_state["event_id"]),
        created_monotonic_ms=monotonic_ms + 3,
        created_wall_clock_ms=wall_clock_ms + 3,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=3,
        planning_reason="trusted_synthetic_smoke_authority",
    )
    journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"evt_smoke_{safe_task_id}_authority_planning_state",
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
        reason="trusted_synthetic_smoke_authority",
    )


def _incomplete_evidence_metadata(
    *,
    evidence: Any,
    run_id: str,
    expected_route: str,
) -> dict[str, Any]:
    metadata = evidence.to_metadata()
    metadata.update(
        {
            "run_id": run_id,
            "mode": "single",
            "input_source": "local_wav_opt_in",
            "route_result_kind": "blocked",
            "actual_route": None,
            "router_decision": None,
            "expected_route": expected_route,
            "expected_route_matched": False,
            "asr_output_mode": evidence.asr_output_mode,
            "thinker_output_mode": evidence.thinker_output_mode,
            "fast_interaction_output_mode": getattr(
                evidence,
                "fast_interaction_output_mode",
                None,
            ),
            "local_wav_opt_in_used": evidence.local_wav_opt_in_used,
            "live_provider_approval_used": evidence.live_provider_approval_used,
            "provider_headers_included": False,
            "local_pack_path_included": False,
            "approval_packet_path_included": False,
        }
    )
    metadata.update(_asr_question_projection(evidence))
    metadata.update(_fast_interaction_projection(evidence))
    return metadata


def _asr_question_projection(evidence: Any) -> dict[str, str]:
    asr_event_id = getattr(evidence, "asr_event_id", None)
    if not isinstance(asr_event_id, str) or asr_event_id == "":
        return {}
    for event in getattr(evidence, "events", ()):
        if event.get("event_id") != asr_event_id:
            continue
        if event.get("event_name") not in {
            "ASR_TRANSCRIPT_OUTPUT_EMITTED",
            "MOCK_ASR_FRAME_EMITTED",
        }:
            return {}
        text_ref = event.get("text_ref")
        if not isinstance(text_ref, str) or text_ref == "":
            return {}
        return {
            "question_event_id": asr_event_id,
            "question_text_ref": text_ref,
        }
    return {}


def _fast_interaction_projection(evidence: Any) -> dict[str, str]:
    fast_event_id = getattr(evidence, "fast_interaction_event_id", None)
    if not isinstance(fast_event_id, str) or fast_event_id == "":
        return {}
    for event in getattr(evidence, "events", ()):
        if event.get("event_id") != fast_event_id:
            continue
        if event.get("event_name") != "FAST_INTERACTION_OUTPUT_EMITTED":
            return {}
        adapter_request_id = event.get("adapter_request_id")
        if not isinstance(adapter_request_id, str) or adapter_request_id == "":
            return {}
        return {"fast_interaction_adapter_request_id": adapter_request_id}
    return {}


def run_mvp5_real_voice_e2e_pack(
    *,
    pack_json: str | Path,
    live_provider: bool,
    approval_packet: Mapping[str, Any],
    run_id: str = "mvp5-real-voice-e2e-pack",
    env: Mapping[str, str] | None = None,
    transport_factory: PackTransportFactory | None = None,
) -> dict[str, Any]:
    run_id = _require_safe_token(run_id, "run_id")
    approval_packet = _require_mapping(approval_packet, "approval_packet")
    pack = _load_pack_json(pack_json)
    pack_id = _require_safe_token(pack.get("pack_id"), "pack_id")
    cases = _parse_pack_cases(pack)
    _validate_pack_budget(cases=cases, approval_packet=approval_packet)

    case_summaries: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for case in cases:
        asr_transport: object | None = None
        thinker_transport: object | None = None
        if transport_factory is not None:
            asr_transport, thinker_transport = transport_factory(case)
        case_metadata = run_mvp5_real_voice_e2e_single(
            local_wav=case.local_wav,
            live_provider=live_provider,
            allow_local_wav=True,
            approval_packet=approval_packet,
            expected_route=case.expected_route,
            run_id=f"{run_id}-{case.case_id}",
            env=env,
            asr_transport=asr_transport,
            thinker_transport=thinker_transport,
            active_task_context=case.active_task_context,
        )
        summary = _pack_case_summary(case_id=case.case_id, metadata=case_metadata)
        case_summaries.append(summary)
        if summary.get("expected_route_matched") is False:
            mismatches.append(
                {
                    "case_id": case.case_id,
                    "expected_route": summary.get("expected_route"),
                    "actual_route": summary.get("actual_route"),
                }
            )

    aggregate_status = _aggregate_status(case_summaries=case_summaries, mismatches=mismatches)
    metadata: dict[str, Any] = {
        "run_id": run_id,
        "mode": "three_route_pack",
        "pack_id": pack_id,
        "status": aggregate_status,
        "aggregate_status": aggregate_status,
        "cases": case_summaries,
        "mismatches": mismatches,
        "provider_call_used": any(bool(case["provider_call_used"]) for case in case_summaries),
        "fake_transport_used": any(bool(case["fake_transport_used"]) for case in case_summaries),
        "raw_audio_included": False,
        "raw_transcript_included": False,
        "raw_provider_body_included": False,
        "prompt_dump_included": False,
        "secret_included": False,
        "local_wav_path_included": False,
        "local_pack_path_included": False,
        "provider_headers_included": False,
        "approval_packet_path_included": False,
        "replay_reruns_provider": False,
        "real_tts_used": False,
        "voice_output": "none",
    }
    _validate_smoke_metadata(metadata)
    return metadata


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    single_transport_factory: SingleTransportFactory | None = None,
    pack_transport_factory: PackTransportFactory | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    runtime_env = os.environ if env is None else env

    try:
        approval_packet = _load_approval_packet(args.approval_packet)
        runtime_env = _env_with_fake_credential_if_needed(
            runtime_env,
            approval_packet=approval_packet,
            use_fake_transport=bool(args.provider_free_fake_route or args.provider_free_fake_pack),
        )
        if args.local_wav_pack is not None:
            selected_pack_transport_factory = pack_transport_factory
            if selected_pack_transport_factory is None and args.provider_free_fake_pack:
                selected_pack_transport_factory = _provider_free_fake_pack_transport_factory
            payload = run_mvp5_real_voice_e2e_pack(
                pack_json=args.local_wav_pack,
                live_provider=bool(args.live_provider),
                approval_packet=approval_packet,
                run_id=args.run_id or "mvp5-real-voice-e2e-pack",
                env=runtime_env,
                transport_factory=selected_pack_transport_factory,
            )
        else:
            if args.local_wav is None:
                raise MVP5RealVoiceE2ESmokeError(
                    "single mode requires --local-wav or pack mode requires --allow-local-wav-pack"
                )
            if args.allow_local_wav is not True:
                raise MVP5RealVoiceE2ESmokeError("--allow-local-wav is required for single mode")
            asr_transport: object | None = None
            thinker_transport: object | None = None
            if single_transport_factory is not None:
                asr_transport, thinker_transport = single_transport_factory()
            elif args.provider_free_fake_route is not None:
                asr_transport, thinker_transport = _provider_free_fake_transports(
                    fake_route=str(args.provider_free_fake_route),
                    route_slug=args.run_id or "cli-single",
                )
            active_task_context = _active_task_context_from_args(args)
            payload = run_mvp5_real_voice_e2e_single(
                local_wav=args.local_wav,
                live_provider=bool(args.live_provider),
                allow_local_wav=bool(args.allow_local_wav),
                approval_packet=approval_packet,
                expected_route=str(args.expected_route),
                run_id=args.run_id or "mvp5-real-voice-e2e-single",
                env=runtime_env,
                asr_transport=asr_transport,
                thinker_transport=thinker_transport,
                active_task_context=active_task_context,
            )
    except Exception as exc:
        payload = _safe_failure_payload(exc)
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 1

    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload.get("status") in {"passed", "routed"} else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MVP-5 real voice E2E smoke over explicit local wav metadata.",
    )
    parser.add_argument("--live-provider", action="store_true", help="Explicitly opt in to live provider boundary checks.")
    parser.add_argument("--allow-local-wav", action="store_true", help="Allow one explicit local wav input.")
    parser.add_argument("--local-wav", help="Path to one local wav input; never emitted in stdout.")
    parser.add_argument(
        "--expected-route",
        choices=_EXPECTED_ROUTE_CHOICES,
        default="auto",
        help="Expected Router route for single mode; mismatch is reported, not forced.",
    )
    parser.add_argument(
        "--allow-local-wav-pack",
        dest="local_wav_pack",
        help="Path to a local-only three-route pack JSON; never emitted in stdout.",
    )
    parser.add_argument("--approval-packet", required=True, help="Structured approval packet path.")
    parser.add_argument("--run-id", help="Safe run id for metadata refs.")
    parser.add_argument("--active-task-id", help="Safe active SlowTask id for PATCH smoke.")
    parser.add_argument("--active-plan-version", type=int, help="Positive active SlowTask plan version.")
    parser.add_argument("--active-task-event-seq", type=int, help="Positive active SlowTask event sequence.")
    parser.add_argument(
        "--active-lifecycle-phase",
        default=None,
        help="Active SlowTask lifecycle phase; defaults to PLANNING when active context is supplied.",
    )
    parser.add_argument(
        "--provider-free-fake-route",
        choices=tuple(sorted(_PACK_EXPECTED_ROUTES)),
        help=(
            "Provider-free test mode: use adapter fake transports to naturally "
            "drive one Router route without real provider calls."
        ),
    )
    parser.add_argument(
        "--provider-free-fake-pack",
        action="store_true",
        help=(
            "Provider-free test mode: use adapter fake transports based on each "
            "pack case expected_route without real provider calls."
        ),
    )
    return parser


def _env_with_fake_credential_if_needed(
    env: Mapping[str, str],
    *,
    approval_packet: Mapping[str, Any],
    use_fake_transport: bool,
) -> Mapping[str, str]:
    if not use_fake_transport:
        return env
    credential_env_var_name = _credential_env_var_name(approval_packet)
    if env.get(credential_env_var_name):
        return env
    fake_env = dict(env)
    fake_env[credential_env_var_name] = "PROVIDER_FREE_FAKE_TRANSPORT_CREDENTIAL"
    return fake_env


def _active_task_context_from_args(args: argparse.Namespace) -> MVP5ActiveSlowTaskContext | None:
    active_task_id = getattr(args, "active_task_id", None)
    active_plan_version = getattr(args, "active_plan_version", None)
    active_task_event_seq = getattr(args, "active_task_event_seq", None)
    lifecycle_phase = getattr(args, "active_lifecycle_phase", None) or "PLANNING"
    values = (active_task_id, active_plan_version, active_task_event_seq)
    if all(value in (None, "") for value in values):
        return None
    if any(value in (None, "") for value in values):
        raise MVP5RealVoiceE2ESmokeError(
            "active task context requires active task id, plan version, and task event seq"
        )
    return MVP5ActiveSlowTaskContext(
        task_id=_require_safe_token(active_task_id, "active_task_id"),
        current_plan_version=_positive_int(active_plan_version, "active_plan_version"),
        current_task_event_seq=_positive_int(active_task_event_seq, "active_task_event_seq"),
        lifecycle_phase=_require_safe_token(lifecycle_phase, "active_lifecycle_phase"),
    )


def _provider_free_fake_pack_transport_factory(case: MVP5SmokePackCase) -> TransportPair:
    return _provider_free_fake_transports(
        fake_route=case.expected_route,
        route_slug=case.case_id,
    )


def build_mvp5_provider_free_fake_transports(
    *,
    fake_route: str,
    route_slug: str,
) -> TransportPair:
    """Build deterministic adapter fake transports for local debug/runtime tests."""

    return _provider_free_fake_transports(fake_route=fake_route, route_slug=route_slug)


def _provider_free_fake_transports(*, fake_route: str, route_slug: str) -> TransportPair:
    fake_route = _normalize_expected_route(fake_route, allow_auto=False)
    route_slug = _safe_slug(_require_safe_token(route_slug, "route_slug"))
    return (
        FakeAsrTransport(
            (
                FakeAsrProviderResponse.success(
                    asr_frame_ref=f"asr-frame://synthetic/mvp5/goal4/{route_slug}",
                    text_ref=f"text://synthetic/mvp5/goal4/{route_slug}",
                    audio_timestamps_ref=f"audio-timestamps://synthetic/mvp5/goal4/{route_slug}",
                    streaming_status="supported",
                    confidence_score=0.91,
                ),
            )
        ),
        _ProviderFreeFakeThinkerAudioTransport(fake_route=fake_route),
    )


class _ProviderFreeFakeThinkerAudioTransport:
    def __init__(self, *, fake_route: str) -> None:
        self._fake_route = fake_route

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
        if not isinstance(request_payload, Mapping):
            raise MVP5RealVoiceE2ESmokeError("fake Thinker transport requires request metadata")
        if not audio_bytes:
            raise MVP5RealVoiceE2ESmokeError("fake Thinker transport requires local audio bytes")
        if audio_format != "wav":
            raise MVP5RealVoiceE2ESmokeError("fake Thinker transport requires wav audio")
        if not credential_value:
            raise MVP5RealVoiceE2ESmokeError("fake Thinker transport requires credential presence")
        _require_safe_token(adapter_request_id, "adapter_request_id")
        _positive_int(timeout_ms, "timeout_ms")
        if model_alias != LALM_THINKER_RUNTIME_MODEL_ALIAS:
            raise MVP5RealVoiceE2ESmokeError("unexpected Thinker model alias")
        if "secret_materialized=False" not in repr(credential_handle):
            raise MVP5RealVoiceE2ESmokeError("credential handle must remain opaque")

        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "neutral"},
            "audio_caption": {"status": "available", "label": "speech_available"},
        }
        skeleton["task_focus_hint"] = _fake_task_focus_hint(self._fake_route)
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


def _fake_task_focus_hint(fake_route: str) -> dict[str, object]:
    if fake_route == "FAST_ONLY":
        return {
            "focus": "FOREGROUND_CHAT",
            "task_like": False,
            "complexity_hint": "simple",
            "focus_confidence": 0.86,
            "evidence_uncertainty": "low",
        }
    if fake_route == "SPAWN_SLOW_TASK":
        return {
            "focus": "NEW_TASK_CANDIDATE",
            "task_like": True,
            "complexity_hint": "complex",
            "focus_confidence": 0.9,
            "evidence_uncertainty": "low",
        }
    if fake_route == "PATCH_ACTIVE_SLOW_TASK":
        return {
            "focus": "ACTIVE_TASK_PATCH",
            "task_like": True,
            "complexity_hint": "medium",
            "focus_confidence": 0.92,
            "evidence_uncertainty": "low",
        }
    raise MVP5RealVoiceE2ESmokeError("provider-free fake route must be an MVP-5 route")


def _load_approval_packet(path_value: str | Path | None) -> Mapping[str, Any]:
    if path_value in (None, ""):
        raise MVP5RealVoiceE2ESmokeError("approval packet is required")
    path = Path(path_value)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MVP5RealVoiceE2ESmokeError("approval packet could not be read") from exc
    try:
        packet = json.loads(text)
    except json.JSONDecodeError:
        packet = _parse_json_block(text)
    return _require_mapping(packet, "approval_packet")


def _parse_json_block(text: str) -> Mapping[str, Any]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if match is None:
        raise MVP5RealVoiceE2ESmokeError("approval packet must contain JSON metadata")
    try:
        packet = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise MVP5RealVoiceE2ESmokeError("approval packet JSON metadata is invalid") from exc
    return _require_mapping(packet, "approval_packet")


def _load_pack_json(pack_json: str | Path) -> Mapping[str, Any]:
    path = Path(pack_json)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MVP5RealVoiceE2ESmokeError("pack JSON could not be read") from exc
    except json.JSONDecodeError as exc:
        raise MVP5RealVoiceE2ESmokeError("pack JSON metadata is invalid") from exc
    return _require_mapping(payload, "pack")


def _parse_pack_cases(pack: Mapping[str, Any]) -> tuple[MVP5SmokePackCase, ...]:
    raw_cases = pack.get("cases")
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes, bytearray)):
        raise MVP5RealVoiceE2ESmokeError("pack cases must be a list")

    cases: list[MVP5SmokePackCase] = []
    seen_case_ids: set[str] = set()
    for raw_case in raw_cases:
        case = _require_mapping(raw_case, "pack case")
        case_id = _require_safe_token(case.get("case_id"), "case_id")
        if case_id in seen_case_ids:
            raise MVP5RealVoiceE2ESmokeError("pack case ids must be unique")
        seen_case_ids.add(case_id)
        expected_route = _normalize_expected_route(
            case.get("expected_route"),
            allow_auto=False,
        )
        if expected_route not in _PACK_EXPECTED_ROUTES:
            raise MVP5RealVoiceE2ESmokeError("pack expected_route must be one of the three MVP-5 routes")
        active_task_context = _parse_active_task_context(case.get("active_task_context"))
        if expected_route == "PATCH_ACTIVE_SLOW_TASK" and active_task_context is None:
            raise MVP5RealVoiceE2ESmokeError(
                "PATCH_ACTIVE_SLOW_TASK pack case requires active_task_context"
            )
        local_wav = case.get("local_wav")
        if not isinstance(local_wav, str) or local_wav == "":
            raise MVP5RealVoiceE2ESmokeError("pack case local_wav is required")
        cases.append(
            MVP5SmokePackCase(
                case_id=case_id,
                local_wav=Path(local_wav),
                expected_route=expected_route,
                active_task_context=active_task_context,
            )
        )
    if not cases:
        raise MVP5RealVoiceE2ESmokeError("pack cases must not be empty")
    return tuple(cases)


def _parse_active_task_context(value: object) -> MVP5ActiveSlowTaskContext | None:
    if value in (None, ""):
        return None
    context = _require_mapping(value, "active_task_context")
    return MVP5ActiveSlowTaskContext(
        task_id=_require_safe_token(context.get("task_id"), "active_task_context.task_id"),
        current_plan_version=_positive_int(
            context.get("current_plan_version"),
            "active_task_context.current_plan_version",
        ),
        current_task_event_seq=_positive_int(
            context.get("current_task_event_seq"),
            "active_task_context.current_task_event_seq",
        ),
        lifecycle_phase=str(context.get("lifecycle_phase") or "PLANNING"),
        terminal_status=(
            str(context["terminal_status"])
            if context.get("terminal_status") not in (None, "")
            else None
        ),
        pending_confirmation_scope=(
            str(context["pending_confirmation_scope"])
            if context.get("pending_confirmation_scope") not in (None, "")
            else None
        ),
    )


def _validate_pack_budget(
    *,
    cases: Sequence[MVP5SmokePackCase],
    approval_packet: Mapping[str, Any],
) -> None:
    max_provider_calls = _positive_int(approval_packet.get("max_provider_calls"), "max_provider_calls")
    requested_provider_calls = len(cases) * _REQUESTS_PER_CASE
    if requested_provider_calls > max_provider_calls:
        raise MVP5RealVoiceE2ESmokeError("pack request budget exceeds approval packet")


def _single_run_provider_call_budget(
    *,
    fast_interaction_enabled: bool,
    asr_observation_enabled: bool,
    allow_fast_interaction_asr_text_fallback: bool,
) -> int:
    if fast_interaction_enabled:
        if asr_observation_enabled or allow_fast_interaction_asr_text_fallback:
            return 2
        return 1
    return _REQUESTS_PER_CASE


def _pack_case_summary(*, case_id: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "run_id",
        "mode",
        "status",
        "route_result_kind",
        "router_decision",
        "actual_route",
        "expected_route",
        "expected_route_matched",
        "event_names",
        "event_ids",
        "asr_event_id",
        "thinker_event_id",
        "router_event_id",
        "task_focus_state_event_id",
        "slowtask_event_ids_by_name",
        "user_patch_event_ids",
        "response_text_ref",
        "result_summary_ref",
        "task_id",
        "patch_id",
        "asr_output_mode",
        "thinker_output_mode",
        "provider_call_used",
        "fake_transport_used",
        "raw_audio_included",
        "raw_transcript_included",
        "raw_provider_body_included",
        "prompt_dump_included",
        "secret_included",
        "local_wav_path_included",
        "local_pack_path_included",
        "replay_reruns_provider",
        "real_tts_used",
        "voice_output",
    )
    summary = {"case_id": _require_safe_token(case_id, "case_id")}
    summary.update({key: metadata[key] for key in keys if key in metadata})
    _validate_smoke_metadata(summary)
    return summary


def _aggregate_status(
    *,
    case_summaries: Sequence[Mapping[str, Any]],
    mismatches: Sequence[Mapping[str, Any]],
) -> str:
    if mismatches:
        return "route_mismatch"
    if all(case.get("status") == "routed" and case.get("expected_route_matched") is True for case in case_summaries):
        return "passed"
    return "failed"


def _normalize_latency_debug(value: object) -> dict[str, Any]:
    fields = (
        "total_server_ms",
        "wav_validate_ms",
        "temp_wav_write_ms",
        "local_audio_gate_ms",
        "approval_gate_ms",
        "asr_provider_http_ms",
        "asr_normalize_emit_ms",
        "thinker_provider_http_ms",
        "thinker_adapter_start_offset_ms",
        "thinker_provider_request_start_offset_ms",
        "thinker_provider_first_chunk_offset_ms",
        "thinker_provider_full_response_offset_ms",
        "thinker_adapter_event_emit_offset_ms",
        "thinker_provider_ttft_ms",
        "thinker_provider_full_response_ms",
        "thinker_provider_generation_ms",
        "thinker_stream_decode_ms",
        "thinker_parse_validate_emit_ms",
        "fast_interaction_provider_http_ms",
        "fast_interaction_adapter_start_offset_ms",
        "fast_interaction_provider_request_start_offset_ms",
        "fast_interaction_provider_first_chunk_offset_ms",
        "fast_interaction_provider_full_response_offset_ms",
        "fast_interaction_adapter_event_emit_offset_ms",
        "fast_interaction_provider_ttft_ms",
        "fast_interaction_provider_full_response_ms",
        "fast_interaction_provider_generation_ms",
        "fast_interaction_stream_decode_ms",
        "fast_interaction_parse_validate_emit_ms",
        "fast_interaction_total_ms",
        "fast_interaction_timeout_ms",
        "fast_answer_ready_offset_ms",
        "qa_pair_ready_offset_ms",
        "foreground_gate_ms",
        "foreground_output_finalize_ms",
        "router_ms",
        "qa_history_ms",
    )
    bool_fields = (
        "provider_calls_parallel",
        "provider_calls_overlapped",
        "asr_started_before_thinker_finished",
        "thinker_started_before_asr_finished",
        "thinker_ttft_available",
        "fast_interaction_timed_out",
        "fast_interaction_ttft_available",
        "asr_started_before_fast_interaction_finished",
        "fast_interaction_started_before_asr_finished",
    )
    string_fields = (
        "thinker_ttft_source",
        "fast_interaction_input_mode",
        "fast_interaction_timing_mode",
        "fast_interaction_ttft_source",
        "fast_interaction_failure_category",
    )
    source = value if isinstance(value, Mapping) else {}
    latency_debug: dict[str, Any] = {}
    for field in fields:
        raw_value = source.get(field)
        latency_debug[field] = (
            None if raw_value is None else _non_negative_int(raw_value, field)
        )
    for field in bool_fields:
        latency_debug[field] = bool(source.get(field, False))
    for field in string_fields:
        raw_value = source.get(field, "")
        if raw_value is None:
            latency_debug[field] = ""
        elif isinstance(raw_value, str):
            latency_debug[field] = _require_safe_token(raw_value, field) if raw_value else ""
        else:
            raise MVP5RealVoiceE2ESmokeError(f"{field} must be a string")
    return latency_debug


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise MVP5RealVoiceE2ESmokeError(f"{field} must be a non-negative integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise MVP5RealVoiceE2ESmokeError(f"{field} must be a non-negative integer")
        value = int(value)
    if not isinstance(value, int) or value < 0:
        raise MVP5RealVoiceE2ESmokeError(f"{field} must be a non-negative integer")
    return value


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _safe_failure_payload(exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": "mvp5-real-voice-e2e-failed",
        "mode": "error",
        "status": "failed",
        "failure_reasons": [_safe_error_message(exc)],
        "provider_call_used": False,
        "fake_transport_used": False,
        "raw_audio_included": False,
        "raw_transcript_included": False,
        "raw_provider_body_included": False,
        "prompt_dump_included": False,
        "secret_included": False,
        "local_wav_path_included": False,
        "local_pack_path_included": False,
        "provider_headers_included": False,
        "approval_packet_path_included": False,
        "replay_reruns_provider": False,
        "real_tts_used": False,
        "voice_output": "none",
    }
    _validate_smoke_metadata(payload)
    return payload


def _safe_error_message(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if any(marker in lowered for marker in _UNSAFE_STRING_MARKERS) or message.startswith("/"):
        return "MVP-5 smoke failed before unsafe metadata could be emitted"
    return message


def _credential_env_var_name(approval_packet: Mapping[str, Any]) -> str:
    value = approval_packet.get("credential_env_var_name")
    if not isinstance(value, str) or value == "":
        raise MVP5RealVoiceE2ESmokeError("credential_env_var_name is required")
    return _require_safe_token(value, "credential_env_var_name")


def _normalize_expected_route(value: object, *, allow_auto: bool) -> str:
    if value in (None, ""):
        return "auto" if allow_auto else ""
    if value == "auto":
        if allow_auto:
            return "auto"
        raise MVP5RealVoiceE2ESmokeError("pack expected_route cannot be auto")
    if value not in MVP1_ROUTER_DECISIONS:
        raise MVP5RealVoiceE2ESmokeError("expected_route must be auto or an existing RouterDecision")
    return str(value)


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MVP5RealVoiceE2ESmokeError(f"{field} must be structured metadata")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise MVP5RealVoiceE2ESmokeError(f"{field} must be a positive integer")
    return value


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise MVP5RealVoiceE2ESmokeError(f"{field} must be a non-empty string")
    lowered = value.lower()
    if any(marker in lowered for marker in _UNSAFE_STRING_MARKERS):
        raise MVP5RealVoiceE2ESmokeError(f"{field} contains unsafe metadata")
    if value.startswith("/") or value.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", value):
        raise MVP5RealVoiceE2ESmokeError(f"{field} must not be a local path")
    return value


def _safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


def _validate_smoke_metadata(metadata: Mapping[str, Any]) -> None:
    for flag in _FALSE_SAFETY_FLAGS:
        if metadata.get(flag) is not False:
            raise MVP5RealVoiceE2ESmokeError(f"{flag} must be false in MVP-5 smoke metadata")
    if metadata.get("voice_output") not in (None, "none"):
        raise MVP5RealVoiceE2ESmokeError("voice_output must be none in MVP-5 smoke metadata")
    _reject_unsafe_metadata_value(metadata)


def _reject_unsafe_metadata_value(value: Any) -> None:
    if isinstance(value, bytes):
        raise MVP5RealVoiceE2ESmokeError("raw bytes are not allowed in MVP-5 smoke metadata")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _UNSAFE_STRING_MARKERS):
            raise MVP5RealVoiceE2ESmokeError(
                "unsafe string marker is not allowed in MVP-5 smoke metadata"
            )
        if value.startswith("/") or value.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", value):
            raise MVP5RealVoiceE2ESmokeError(
                "local paths are not allowed in MVP-5 smoke metadata"
            )
        return
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if str(child_key) in _FORBIDDEN_KEYS:
                raise MVP5RealVoiceE2ESmokeError(
                    "unsafe key is not allowed in MVP-5 smoke metadata"
                )
            _reject_unsafe_metadata_value(child_value)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_unsafe_metadata_value(item)


if __name__ == "__main__":
    raise SystemExit(main())
