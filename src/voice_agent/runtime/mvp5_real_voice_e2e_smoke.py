from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
from voice_agent.router.router import MVP1_ROUTER_DECISIONS
from voice_agent.runtime.mvp5_live_router_runner import (
    MVP5ActiveSlowTaskContext,
    MVP5LiveRouterConfig,
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
    active_task_context: MVP5ActiveSlowTaskContext | None = None,
) -> dict[str, Any]:
    run_id = _require_safe_token(run_id, "run_id")
    approval_packet = _require_mapping(approval_packet, "approval_packet")
    expected_route = _normalize_expected_route(expected_route, allow_auto=True)
    if expected_route == "PATCH_ACTIVE_SLOW_TASK" and active_task_context is None:
        raise MVP5RealVoiceE2ESmokeError(
            "PATCH_ACTIVE_SLOW_TASK expected route requires active task context"
        )
    credential_env_var_name = _credential_env_var_name(approval_packet)

    evidence = run_mvp5_live_voice_evidence(
        local_wav=local_wav,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id=run_id,
            live_provider=live_provider,
            allow_local_wav=allow_local_wav,
            approval_packet=approval_packet,
            credential_env_var_name=credential_env_var_name,
            requested_provider_calls=_REQUESTS_PER_CASE,
            max_provider_calls=_positive_int(
                approval_packet.get("max_provider_calls"),
                "max_provider_calls",
            ),
        ),
        env={} if env is None else env,
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )
    route_result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id=run_id,
            expected_route=expected_route,
            active_task_context=active_task_context,
        ),
    )

    metadata = route_result.to_metadata()
    metadata.update(
        {
            "run_id": run_id,
            "mode": "single",
            "input_source": "local_wav_opt_in",
            "asr_output_mode": evidence.asr_output_mode,
            "thinker_output_mode": evidence.thinker_output_mode,
            "local_wav_opt_in_used": evidence.local_wav_opt_in_used,
            "live_provider_approval_used": evidence.live_provider_approval_used,
            "provider_headers_included": False,
            "local_pack_path_included": False,
            "approval_packet_path_included": False,
        }
    )
    if evidence.safe_refs:
        metadata["safe_refs"] = list(evidence.safe_refs)
    _validate_smoke_metadata(metadata)
    return metadata


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
