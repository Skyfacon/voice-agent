"""Synthetic fixture policy helpers for Slow LLM retry eval dry-runs."""

from __future__ import annotations


DEFAULT_LOCAL_RUN_ROOT = "/private/tmp/voice-agent-slow-llm-retry-eval"


def fixture_policy_summary() -> dict[str, object]:
    return {
        "fixture_source": "synthetic_metadata",
        "writes_provider_body": False,
        "uses_real_user_input": False,
        "calls_provider": False,
        "executes_tools": False,
        "local_run_root": DEFAULT_LOCAL_RUN_ROOT,
    }
