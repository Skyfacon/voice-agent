"""Credential-safe synthetic ingress smoke for real Qwen enforced Control.

This intentionally does not claim real microphone, Voice, ASR, or Qwen PCM
coverage.  A redacted Fake Voice turn drives the real text-only Qwen Control
adapter through the authoritative coordinator journal, local Router, Gate, and
MockSlowTask/UserPatch owners.  Only bounded metadata is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    from experiments.qwen_realtime_fast_slow_web.fake_provider import (  # type: ignore
        FakeProviderConfig,
        FakeRealtimeProvider,
    )
    from experiments.qwen_realtime_fast_slow_web.provider_context import (  # type: ignore
        CredentialHandle,
        ProviderConfigurationError,
    )
    from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (  # type: ignore
        ENFORCED_CONTROL_MODE,
        QwenShadowRouterAdapter,
    )
    from experiments.qwen_realtime_fast_slow_web.session_coordinator import (  # type: ignore
        RealtimeSessionCoordinator,
    )
else:
    from .fake_provider import FakeProviderConfig, FakeRealtimeProvider
    from .provider_context import CredentialHandle, ProviderConfigurationError
    from .qwen_shadow_router_adapter import (
        ENFORCED_CONTROL_MODE,
        QwenShadowRouterAdapter,
    )
    from .session_coordinator import RealtimeSessionCoordinator


class _MetadataSink:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.binary_frame_count = 0

    async def send_json(self, data: Mapping[str, Any]) -> None:
        # Keep the in-process UI projection only long enough to calculate a
        # bounded allowlisted summary; never write it to disk.
        self.messages.append(dict(data))

    async def send_bytes(self, _data: bytes) -> None:
        self.binary_frame_count += 1

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a synthetic/redacted ingress smoke against real Qwen enforced "
            "Control; no real Voice/ASR/audio capability is claimed."
        )
    )
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--qwen-base-url", default=None)
    parser.add_argument("--verified-workspace-id", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser


def _last(messages: Sequence[Mapping[str, Any]], message_type: str) -> Mapping[str, Any] | None:
    return next(
        (
            message
            for message in reversed(messages)
            if message.get("type") == message_type
        ),
        None,
    )


async def _run(args: argparse.Namespace) -> int:
    try:
        credentials = CredentialHandle.resolve(
            safe_base_url=args.qwen_base_url,
            explicit_workspace_id=args.workspace_id,
            verified_workspace_id=args.verified_workspace_id,
        )
    except ProviderConfigurationError as error:
        print(json.dumps({"status": "failed", "code": error.code}, sort_keys=True))
        return 2
    if args.timeout_seconds <= 0:
        print(
            json.dumps(
                {"status": "failed", "code": "timeout_must_be_positive"},
                sort_keys=True,
            )
        )
        return 2

    sink = _MetadataSink()
    voice = FakeRealtimeProvider(
        FakeProviderConfig(response_audio_chunks=2, event_delay_seconds=0.001)
    )
    control = QwenShadowRouterAdapter(
        credentials,
        control_mode=ENFORCED_CONTROL_MODE,
    )
    coordinator = RealtimeSessionCoordinator(
        sink,
        voice,
        shadow_provider=control,
        provider_mode="qwen",
        routing_mode="enforced",
        audio_output="none",
        shadow_control_mode="dual_session_enforced_control",
        session_id="session_qfs_live_enforced_control",
        conversation_id="conversation_qfs_live_enforced_control",
    )
    try:
        await asyncio.wait_for(coordinator.start(), timeout=args.timeout_seconds)
        await voice.trigger_scenario("fast")
        await asyncio.wait_for(coordinator.wait_for_idle(), timeout=args.timeout_seconds)
        route_proposed = _last(sink.messages, "route.proposed")
        dispatch = _last(sink.messages, "dispatch.result")
        gate = _last(sink.messages, "gate.result")
        committed_assistant = [
            message
            for message in sink.messages
            if message.get("type") == "transcript.assistant.done"
            and message.get("server_committed") is True
        ]
        unsafe_assistant = [
            message
            for message in sink.messages
            if message.get("type") in {
                "transcript.assistant.delta",
                "transcript.assistant.done",
            }
            and message.get("server_committed") is not True
        ]
        route_agreement = (
            coordinator.state.qwen_route_hint
            == coordinator.state.local_router_decision
        )
        focus_agreement = (
            coordinator.state.qwen_task_focus_hint
            == coordinator.state.local_task_focus
        )
        foreground_act_agreement = (
            coordinator.state.shadow_foreground_act
            == coordinator.state.local_foreground_act
        )
        summary = {
            "status": (
                "passed"
                if route_proposed is not None
                and dispatch is not None
                and sink.binary_frame_count == 0
                and not unsafe_assistant
                else "failed"
            ),
            "smoke_kind": "synthetic_redacted_real_control",
            "microphone": "manual_not_executed",
            "voice_ingress": "fake",
            "control_provider": "real_qwen",
            "control_topology": "dual_session_enforced_control",
            "qwen_proposal_authority": "non_authoritative",
            "local_router_authority": "authoritative",
            "output": "text_only",
            "audio_output": "none",
            "slow_runtime": "mock",
            "function_call_coverage": 1 if route_proposed is not None else 0,
            "schema_status": coordinator.state.schema_status,
            "qwen_route_hint": coordinator.state.qwen_route_hint,
            "qwen_task_focus_hint": coordinator.state.qwen_task_focus_hint,
            "qwen_foreground_act": coordinator.state.shadow_foreground_act,
            "local_router_decision": coordinator.state.local_router_decision,
            "local_task_focus": coordinator.state.local_task_focus,
            "local_foreground_act": coordinator.state.local_foreground_act,
            "route_agreement": route_agreement,
            "task_focus_agreement": focus_agreement,
            "foreground_act_agreement": foreground_act_agreement,
            "overall_agreement": (
                route_agreement and focus_agreement and foreground_act_agreement
            ),
            "gate_status": gate.get("gate_status") if gate else None,
            "actual_dispatch": dispatch.get("actual_dispatch") if dispatch else None,
            "committed_text_count": len(committed_assistant),
            "unsafe_assistant_text_count": len(unsafe_assistant),
            "binary_playback_frame_count": sink.binary_frame_count,
            "request_to_first_delta_ms": (
                coordinator.state.shadow_request_to_first_delta_ms
            ),
            "request_to_function_done_ms": (
                coordinator.state.shadow_request_to_done_ms
            ),
            "function_done_to_local_router_gate_ms": (
                coordinator.state.function_done_to_local_router_ms
            ),
            "router_gate_latency_ms": coordinator.state.router_gate_latency_ms,
            "control_context_delete_count": coordinator.state.context_delete_count,
            "control_context_rebuild_count": coordinator.state.context_rebuild_count,
            "control_context_tainted": coordinator.state.context_tainted,
            "voice_cancel_count": coordinator.state.voice_cancel_count,
            "voice_suppressed_text_count": (
                coordinator.state.assistant_text_suppression_count
            ),
            "voice_suppressed_audio_count": coordinator.state.audio_suppression_count,
        }
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["status"] == "passed" else 1
    except asyncio.TimeoutError:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "enforced_control_smoke_timeout",
                    "smoke_kind": "synthetic_redacted_real_control",
                    "microphone": "manual_not_executed",
                },
                sort_keys=True,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "enforced_control_smoke_failed",
                    "smoke_kind": "synthetic_redacted_real_control",
                    "microphone": "manual_not_executed",
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        await coordinator.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
