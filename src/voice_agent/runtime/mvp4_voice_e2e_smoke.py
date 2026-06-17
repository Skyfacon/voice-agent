from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


ROUTE_CHOICES = ("provider-free", "fast", "spawn", "patch")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.local_wav is not None and not args.allow_local_wav:
        print("local wav metadata requires --allow-local-wav", file=sys.stderr)
        return 2

    try:
        audio_input = _load_audio_input(args)
        payload = run_smoke_summary(route=args.route, audio_input=audio_input)
    except Exception as exc:
        print(_safe_error_message(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def run_smoke_summary(
    *,
    route: str,
    audio_input: mvp4.MVP4AudioInputMetadata,
) -> dict[str, Any]:
    if route == "provider-free":
        result = mvp4.run_provider_free_voice_e2e(audio_input=audio_input)
        response_summary: Mapping[str, Any] = {
            "response_kind": "runtime_summary",
            "route": "PROVIDER_FREE",
            "source_router_event_ids": _event_ids(result.router_decision_events),
            "response_text_ref": "response-text://synthetic/mvp4/provider-free-summary",
            "real_tts_used": False,
            "voice_output": "none",
        }
        control_plane_summary: Mapping[str, Any] = {
            "route": "PROVIDER_FREE",
            "router_decisions": [
                str(event["router_decision"]) for event in result.router_decision_events
            ],
        }
        events = result.events
    elif route == "fast":
        outcome = mvp4.run_mvp4_router_fast_only_voice_e2e(audio_input=audio_input)
        response_summary = outcome.response_summary
        control_plane_summary = outcome.control_plane_summary
        events = outcome.events
    elif route == "spawn":
        outcome = mvp4.run_mvp4_router_spawn_slowtask_voice_e2e(audio_input=audio_input)
        response_summary = outcome.response_summary
        control_plane_summary = outcome.control_plane_summary
        events = outcome.events
    elif route == "patch":
        outcome = mvp4.run_mvp4_router_patch_active_slowtask_voice_e2e(audio_input=audio_input)
        response_summary = outcome.response_summary
        control_plane_summary = outcome.control_plane_summary
        events = outcome.events
    else:
        raise ValueError("unsupported MVP-4 smoke route")

    return {
        "route": route,
        "status": "passed",
        **_audio_public_summary(audio_input),
        "router_decisions": _router_decisions(events),
        "router_event_ids": _event_ids_named(events, "ROUTER_DECISION_EMITTED"),
        "asr_event_ids": _event_ids_named(
            events,
            "MOCK_ASR_FRAME_EMITTED",
            "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        ),
        "thinker_event_ids": _event_ids_named(
            events,
            "MOCK_THINKER_FRAME_EMITTED",
            "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        ),
        "slowtask_event_ids": _event_ids_named(
            events,
            "SLOWTASK_CREATED",
            "SLOWTASK_STATE_CHANGED",
            "PLANNING_STARTED",
            "EVIDENCE_REVIEWED",
            "ARGUMENTS_RESOLVED",
            "SEMANTIC_COMMITMENT_EMITTED",
        ),
        "user_patch_event_ids": _event_ids_named(events, "USER_PATCH_RECEIVED"),
        "response_summary": dict(response_summary),
        "control_plane_summary": dict(control_plane_summary),
        "raw_audio_included": False,
        "raw_transcript_included": False,
        "provider_call_used": False,
        "real_tts_used": False,
        "voice_output": "none",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MVP-4 provider-free voice E2E smoke over safe audio metadata.",
    )
    parser.add_argument("--route", choices=ROUTE_CHOICES, required=True)
    parser.add_argument("--local-wav", help="Read metadata from a local wav path; requires opt-in.")
    parser.add_argument("--allow-local-wav", action="store_true")
    return parser


def _load_audio_input(args: argparse.Namespace) -> mvp4.MVP4AudioInputMetadata:
    if args.local_wav is not None:
        return mvp4.load_local_wav_metadata(
            Path(args.local_wav),
            allow_local_wav=True,
            fixture_id="redacted-local-wav",
        )
    return _synthetic_audio_for_route(str(args.route))


def _synthetic_audio_for_route(route: str) -> mvp4.MVP4AudioInputMetadata:
    return mvp4.load_synthetic_wav_metadata(
        fixture_id=f"synthetic-smoke-{route}",
        duration_ms=1000,
        sample_rate_hz=16000,
        channel_count=1,
    )


def _audio_public_summary(audio_input: mvp4.MVP4AudioInputMetadata) -> dict[str, Any]:
    public = audio_input.to_public_metadata()
    return {
        "input_source": public["input_source"],
        "fixture_id": public["fixture_id"],
        "duration_ms": public["duration_ms"],
        "sample_rate_hz": public["sample_rate_hz"],
        "channel_count": public["channel_count"],
        "safe_audio_ref": public["safe_audio_ref"],
    }


def _router_decisions(events: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(event["router_decision"])
        for event in events
        if event.get("event_name") == "ROUTER_DECISION_EMITTED"
    ]


def _event_ids(events: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(event["event_id"]) for event in events]


def _event_ids_named(events: Sequence[Mapping[str, Any]], *event_names: str) -> list[str]:
    wanted = set(event_names)
    return [
        str(event["event_id"])
        for event in events
        if str(event.get("event_name")) in wanted
    ]


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    if "No such file" in message or "not found" in message.lower():
        return "local wav metadata could not be read"
    return message


if __name__ == "__main__":
    raise SystemExit(main())
