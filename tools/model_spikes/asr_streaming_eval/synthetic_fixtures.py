"""Synthetic fixture policy helpers for ASR streaming eval dry-runs."""

from __future__ import annotations

DEFAULT_LOCAL_RUN_ROOT = "/private/tmp/voice-agent-asr-streaming-eval"


def fixture_policy_summary() -> dict[str, object]:
    return {
        "fixture_source": "synthetic_metadata",
        "writes_audio": False,
        "uses_real_user_input": False,
        "calls_provider": False,
        "local_run_root": DEFAULT_LOCAL_RUN_ROOT,
    }
