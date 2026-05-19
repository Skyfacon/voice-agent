"""Synthetic fixture policy for the Thinker / Composer eval harness."""

from __future__ import annotations


DEFAULT_LOCAL_RUN_ROOT = "/private/tmp/voice-agent-thinker-composer-eval"


def fixture_policy_summary() -> dict[str, object]:
    return {
        "fixture_domain": "synthetic_metadata_only",
        "allowed_fixture_kinds": [
            "synthetic_text",
            "synthetic_audio_metadata",
            "synthetic_asr_and_audio_metadata",
            "synthetic_semantic_commitment",
        ],
        "contains_real_user_input": False,
        "contains_raw_audio": False,
        "contains_provider_bodies": False,
        "contains_local_traces": False,
        "contains_replay_cache": False,
        "calls_provider": False,
        "executes_tools": False,
        "deterministic_replay_reruns_provider": False,
    }
