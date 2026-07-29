# Codex Context Shadow Baseline

- Captured: 2026-07-29 (Asia/Shanghai)
- Shadow mode: active instructions remain unchanged
- Legacy instruction inventory: 111 items
- Operational A/B: not-run

## Frozen source surfaces

| Active surface | UTF-8 bytes | SHA-256 |
| --- | ---: | --- |
| Root `AGENTS.md` | 9,950 | `c9674b955b0bda8b301b7159f6a87016989ac318262999d60247045af652d984` |
| Slice 3B.1 master plan | 151,857 | `1d047b13d7adc775b25fa6eeede452e75c3710234deb9f505bb3124f927c3cb4` |

The root `AGENTS.md`, accepted ADRs, ADR register, and Slice 3B.1 master plan
remain the active governance and implementation surfaces throughout shadow
mode. The shadow inventory does not replace or weaken them.

## Pre-mutation runtime baseline

The selected provider-free regression baseline passed 9 of 9 tests. It covered
deterministic replay isolation, local artifact exclusions, state-digest
redaction, provider-free acceptance replay, stale evidence, destructive-action
confirmation, Composer coverage, the fast foreground gate, and the parallel
fast-interaction profile.

Task 8 will recapture this selected regression command and run the deferred full
suite before shadow completion. Operational A/B remains `not-run`.

The selected unchanged-runtime command to recapture in Task 8 is:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test \
  tests/replay/test_deterministic_replay.py::test_replay_does_not_call_network_clock_random_or_missing_ref_fetchers \
  tests/replay/test_fixture_safety.py::test_local_debug_artifacts_are_ignored_before_runtime_writes \
  tests/state/test_state_digest.py::test_state_digest_excludes_raw_sensitive_and_tool_credential_payloads \
  tests/acceptance/test_mvp4_acceptance_scenarios.py::test_provider_free_acceptance_replays_fake_asr_and_thinker_without_provider_or_secret_reads \
  tests/replay/test_stale_tool_result_replay.py::test_slice8_no_adoption_fixture_replays_stale_evidence_without_advancement \
  tests/replay/test_demo_destructive_confirmation_replay_mvp2.py::test_demo_destructive_confirmation_fixture_replays_without_backend_execution \
  tests/replay/test_composer_checks_replay_mvp2.py::test_replay_accepts_playback_after_valid_coverage_pass \
  tests/runtime/test_mvp63_fast_foreground_gate.py::test_gate_passes_only_fast_only_answer_low_risk_candidate \
  tests/adapters/test_parallel_fast_interaction_profile.py::test_parallel_orchestrator_profile_is_local_join_only \
  -q
```

Task 8 will also run the deferred full-suite command:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test -q
```

## Local-only evidence

Raw task identifiers, screenshots, prompts, complete status output, and test
logs remain in ignored local diagnostics only. They are not part of this
committed baseline.
