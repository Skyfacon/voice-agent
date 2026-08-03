# Slice 3A.1.3 Generation-Fenced Authority and Journal/Replay Closure Plan

**Goal:** Close the provider-free authority, delivery, horizon, Gate, and replay gaps that invalidate the prior Slice 3A.1.2 acceptance.

**Constraints:** Preserve accepted ADR boundaries and canonical event names; keep Qwen output quarantined and Local Router authoritative; use only mock/local providers; do not commit, push, or open a PR.

## Frozen ownership

- Main thread: `experiments/qwen_realtime_fast_slow_web/session_coordinator.py`, delivery-authority tests, acceptance/proposal/README documents, integration and final verification.
- Gate agent: foreground template catalog, Fast Foreground Gate, MVP5 live runner, and Gate/runtime tests only.
- Replay agent: replay runner, state digest, and replay tests only.
- Voice/Test agent: Voice adapter, candidate quarantine, generation/horizon tests, and adapter tests only. It may add coordinator-facing tests but must not edit the coordinator.

## TDD execution

1. Add deterministic failing tests for generation TOCTOU, both bounded Voice horizons, epoch type confusion, delivery truth-table behavior, exact template refs, current-state Gate binding, missing-candidate Gate closure, replay cardinality, and digest authority.
2. Add an immutable Voice authority token and revalidate it after every awaited boundary before authoritative state, journal, Router, Gate, SlowTask, UserPatch, QA, playback, or control mutation.
3. Trigger one coalesced Voice-only rebuild at either input or response horizon, drain retired PCM, and prove the replacement generation accepts new input.
4. Centralize versioned deterministic templates and align candidate, Gate, commit, delivery, and mutation-completion semantics.
5. Bind Gate inputs to current reducer/task/capability/journal authority and force a terminal Gate+commit for FAST_ONLY when candidate evidence is missing.
6. Reject duplicate authoritative per-turn replay chains and include stable foreground authority identities in the replay digest.
7. Mark Slice 3A.1.2 invalidated, amend the proposed ADR without changing the accepted register, add the Slice 3A.1.3 acceptance record, and update the experiment README.
8. Run focused red/green tests, both required regression suites, full project tests, `git diff --check`, artifact/secret scans, and an independent review pass.

## Hard-gate verdict

Advance to Slice 3A.2 only if every required deterministic and regression command passes, the independent review finds no P0/P1, and documentation explicitly records the provider-free limits. Otherwise report `BLOCKED` with the exact failed gate.
