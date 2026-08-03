"""Credential-safe real Qwen text Shadow Control smoke.

The script sends one fixed synthetic transcript, prints only allowlisted
metadata, and never enables Voice audio, tools, Router authority, or persistence.
Load credentials in the parent shell; do not pass the API key as an argument.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    from experiments.qwen_realtime_fast_slow_web.provider_context import (  # type: ignore
        CredentialHandle,
        ProviderConfigurationError,
    )
    from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (  # type: ignore
        QwenShadowRouterAdapter,
        ShadowProviderError,
        ShadowRouteRequest,
    )
    from experiments.qwen_realtime_fast_slow_web.shadow_router_evaluator import (  # type: ignore
        ShadowRouterEvaluator,
    )
    from voice_agent.router.router import TaskFocusSnapshot  # type: ignore
else:
    from .provider_context import CredentialHandle, ProviderConfigurationError
    from .qwen_shadow_router_adapter import (
        QwenShadowRouterAdapter,
        ShadowProviderError,
        ShadowRouteRequest,
    )
    from .shadow_router_evaluator import ShadowRouterEvaluator
    from voice_agent.router.router import TaskFocusSnapshot


_SYNTHETIC_TRANSCRIPT = (
    "[synthetic redacted smoke] Please compare whether planning a two-day "
    "fictional museum trip looks like a new task."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one metadata-only real Qwen Shadow Control smoke."
    )
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--qwen-base-url", default=None)
    parser.add_argument("--verified-workspace-id", default=None)
    parser.add_argument("--timeout", type=float, default=12.0)
    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        credentials = CredentialHandle.resolve(
            safe_base_url=args.qwen_base_url,
            explicit_workspace_id=args.workspace_id,
            verified_workspace_id=args.verified_workspace_id,
        )
    except ProviderConfigurationError as error:
        print(json.dumps({"smoke_status": "not_executed", "code": error.code}))
        return 2

    adapter = QwenShadowRouterAdapter(credentials)
    request = ShadowRouteRequest(
        request_id="shadow_live_smoke_0001",
        turn_id="turn_live_smoke_0001",
        utterance_id="utterance_live_smoke_0001",
        asr_frame_ref="asr-frame://synthetic/qfs-live-smoke/0001",
        transcript=_SYNTHETIC_TRANSCRIPT,
        task_focus_snapshot={
            "has_active_non_terminal_task": False,
            "pending_confirmation_scope": None,
            "side_conversation_allowed": True,
            "default_patch_policy": "NO_ACTIVE_TASK",
            "ambiguous_input_policy": "CLARIFY",
        },
        asr_final_monotonic_ms=time.monotonic_ns() / 1_000_000.0,
    )
    try:
        await adapter.connect()
        result = await adapter.analyze(request, timeout_seconds=args.timeout)
        safe_result = result.to_safe_metadata()
        passed = bool(result.schema_valid and result.proposal is not None)
        comparison = None
        if result.proposal is not None:
            evaluation = ShadowRouterEvaluator(
                session_ref="live_shadow_smoke"
            ).evaluate(
                proposal=result.proposal,
                turn_id=request.turn_id,
                utterance_id=request.utterance_id,
                audio_span_id="audio_live_smoke_0001",
                asr_frame_ref=request.asr_frame_ref,
                task_focus_snapshot=TaskFocusSnapshot(),
                output_mode=result.output_mode,
            )
            comparison = evaluation.to_metadata()
            comparison["isolated_router_evaluation_ms"] = (
                evaluation.evaluation_latency_ms
            )
            comparison["function_done_to_local_router_ms"] = round(
                (result.latency.function_call_done_to_result_ms or 0.0)
                + evaluation.evaluation_latency_ms,
                3,
            )
        print(
            json.dumps(
                {
                    "smoke_status": "executed_pass" if passed else "executed_degraded",
                    "topology": "dual_session_shadow_control_only",
                    "provider": "qwen",
                    "routing": "shadow",
                    "voice_audio_executed": False,
                    "credentials": credentials.to_metadata(),
                    "result": safe_result,
                    "comparison": comparison,
                    "counters": adapter.counters.to_metadata(),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if passed else 3
    except ShadowProviderError as error:
        print(
            json.dumps(
                {
                    "smoke_status": "executed_degraded",
                    "provider": "qwen",
                    "routing": "shadow",
                    "code": error.code,
                },
                sort_keys=True,
            )
        )
        return 3
    except Exception:
        print(
            json.dumps(
                {
                    "smoke_status": "executed_degraded",
                    "provider": "qwen",
                    "routing": "shadow",
                    "code": "shadow_live_smoke_failed",
                },
                sort_keys=True,
            )
        )
        return 3
    finally:
        await adapter.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
