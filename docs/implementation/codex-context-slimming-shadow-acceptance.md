# Codex Context Slimming Shadow Acceptance

A/B status: not-run

Atomic switch: not-authorized

## Status contract

The acceptance status enum is `not-run`, `inconclusive`, `passed`, `failed`.
The current status is deliberately `not-run`: this record does not claim that
an operational A/B has occurred.

## Frozen baseline

| Surface | UTF-8 bytes | SHA-256 |
| --- | ---: | --- |
| Active root instruction | 9,950 | `c9674b955b0bda8b301b7159f6a87016989ac318262999d60247045af652d984` |
| Slice 3B.1 master plan | 151,857 | `1d047b13d7adc775b25fa6eeede452e75c3710234deb9f505bb3124f927c3cb4` |

- Legacy instruction inventory: 111 items.
- Audit schema/version: `voice_agent.codex_context.audit.v1`.
- Baseline authority:
  `docs/governance/codex-context/shadow-baseline.md`.

## Shadow artifact sizes

| Artifact | UTF-8 bytes | Gate |
| --- | ---: | --- |
| Candidate instruction | 6,056 | at or below 6 KiB |
| Eleven Task Cards | 4,845–7,981 each | every card below 12 KiB |
| Slice 3B.1 Work Package | 2,970 | inside the 2–4 KiB target |
| Task Card index | 2,627 | compact navigation only |

The invariant map contains exactly 111 primary legacy-rule rows.

## Local-equivalence command results

| Gate | Command | Result |
| --- | --- | --- |
| Governance tests | `./scripts/test tests/governance -q` | passed: 80 |
| Complete deterministic governance audit | `./scripts/codex-context-audit all` | passed: counts 111 / 373 / 14 / 12 / 22; `switch_ready=false` |
| Snapshot prepare | `scripts/codex-context-snapshot prepare` | passed: 422 entries; pair digest `ee8efc81346e4df1af5a999f23ccae12e55e3208cc4320ca4468895b0973a40f` |
| Snapshot verify | `scripts/codex-context-snapshot verify` | passed: two expected differences |
| Snapshot cleanup | `scripts/codex-context-snapshot cleanup` | passed: exact pair removed; no private-container residue |

These are bounded summaries, not complete command output. No local snapshot
location or interaction content is committed.

## Selected runtime-regression results

The unchanged-runtime selection is the nine-test command frozen in
`docs/governance/codex-context/shadow-baseline.md`.

| Regression set | Result | Evidence allowed here |
| --- | --- | --- |
| Selected provider-free replay, privacy, task authority, Composer, gate, and adapter checks | passed: 9 in 0.38 s; same node set as the frozen baseline | aggregate pass count and duration |
| Full repository suite | passed: 3,428 in 57.04 s | aggregate pass, skip, and failure counts |
| Production runtime diff attributable to context slimming | zero plan-owned production runtime files | bounded changed-path count |

The pre/post worktree comparison preserved every pre-existing modified or
untracked surface. The pre-shadow aggregate `tests/governance/` entry now
resolves to the still-untracked ADR-018 consistency test because the new shadow
governance files were committed; no unrelated user path was reset, restored,
overwritten, staged, or absorbed.

## Redacted A/B results

Methodology:
`docs/governance/codex-context/ab-scenarios.md`.

| scenario_id | arm | repeat_id | outcome | timestamp_timezone | visible_model | redacted_identifier_suffix | uncontrolled_difference_note |
| --- | --- | --- | --- | --- | --- | --- | --- |

Rows remain empty while A/B status is `not-run`. If runs occur, `outcome` is
limited to `normal`, `content_unavailable`, `rerouted`, `delayed`, or `other`.
The fixed first-window repeats are `B1`, `B2`, `C1`, and `C2`; only mixed
evidence permits later comparable repeats `B3` and `C3`.

This table is the complete committed A/B result schema. It contains no account
identifier, interaction body, captured UI image, complete task/thread/request
identifier, local log, or local snapshot location.

## Operational gate decision

Decision: `not-authorized`.

No candidate activation is permitted from this template. A future reviewer may
not recommend the Atomic Switch from an operational result alone.
`switch_ready` remains `false`; the sole reported prerequisite is
`ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED`.

## Switch prerequisites

A future reviewer may recommend the Atomic Switch only after all of the
following are satisfied:

1. the complete governance audit passes with zero unmapped legacy rules and
   valid accepted-ADR authority;
2. context budgets, Task Card/Work Package structure, and artifact checks pass;
3. the selected unchanged-runtime regressions and full repository suite pass;
4. AB-02, AB-03, and AB-04 candidate runs complete without a
   `content_unavailable` outcome;
5. candidate ordinary-local behavior is no worse than baseline;
6. when the baseline reproduces the issue, Task Card behavior is materially
   better than full-master-plan behavior;
7. mixed results have been classified `inconclusive` or resolved by the fixed
   later paired-repeat policy;
8. a human explicitly approves the switch and the ADR-015 prerequisite is
   completed.

## Explicit non-claims

- This record does not claim that false-positive interventions are eliminated
  or reduced by a statistically established rate.
- AB-01 is an account/model/surface control and cannot establish an effect from
  the candidate repository context.
- If the baseline issue does not reproduce, the evidence establishes at most
  no observed regression in this small run.
- AB-04 changes both `AGENTS.md` and `CODEX_TASK.md`; it cannot attribute an
  outcome to either surface alone.
- Local equivalence does not predict service behavior, and operational A/B does
  not replace ADR or runtime regression gates.
- Snapshot cleanup assumes no concurrent mutation of its randomly named private
  container by another process running as the same OS identity; this is not a
  claim of cross-process isolation.
- This shadow acceptance does not modify active instructions, ADR authority, or
  the default execution entry.

## Rollback readiness

- The active root `AGENTS.md` remains unchanged.
- ADR-015 remains unchanged and accepted.
- The original Slice 3B.1 master plan remains in place.
- Candidate instructions, the equivalence map, Task Cards, Work Packages, and
  audit tooling are shadow artifacts and do not activate themselves.
- Disposable pairs have an explicit verified cleanup command in the A/B
  methodology.

Rollback status: ready for the current shadow state; no Atomic Switch has
occurred. Any future switch needs a separately reviewed change set that can
restore the prior root instruction, ADR-015 wording, and default execution
entry together.

## Reviewer verdict

Verdict: `passed` for the Shadow Completion Gate.

Three independent read-only reviews covered semantic equivalence and authority,
Task Card/Work Package structure, and deterministic audit/snapshot safety.
Each reported zero P0, P1, or P2 findings after the review fixes were applied.

This verdict covers the local shadow build only. It does not claim an
operational A/B result, does not satisfy the ADR-015 switch prerequisite, and
does not authorize candidate activation. A/B status remains `not-run` and the
Atomic switch remains `not-authorized`.
