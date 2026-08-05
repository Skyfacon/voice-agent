# Codex Context Slimming Design

## Status

Approved for shadow implementation planning on 2026-07-28.

Written user approval was received before the implementation plan was created.
Atomic switch approval remains separate.

## Date

2026-07-28

## Context

The repository contains legitimate voice-agent architecture, provider adapter,
authorization, privacy, replay, and safety-boundary work. The current
repo-level instruction and implementation-planning surfaces repeat many of the
same constraints:

- `AGENTS.md` is loaded automatically by Codex and is currently about 10 KiB.
- `docs/superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md`
  is about 152 KiB and is commonly used as a single execution surface.
- Detailed negative checklists and inline compliance commands are repeated
  across the repo instruction, accepted ADRs, plans, and acceptance material.
- The repository also contains real provider adapters, while Slice 3B.1 itself
  is provider-free. A long-lived Codex task can therefore accumulate both
  provider-free constraints and real-provider implementation context.

OpenAI's safeguards can occasionally intervene on legitimate or non-security
work. This design does not attempt to evade, disable, or obscure those
safeguards. It reduces unnecessary context, makes task scope more accurate, and
keeps the repository's accepted safety boundaries mechanically verifiable.

## Goal

Significantly reduce false-positive Codex safety interventions while keeping
the existing accepted ADR semantics and safety boundaries fully equivalent.

## Non-goals

This design does not:

- change voice-agent runtime behavior;
- change event schemas, journal ordering, replay semantics, Router authority,
  SlowTask authority, Tool Executor behavior, confirmation policy, Composer
  coverage, or Fast Foreground Gate behavior;
- remove or weaken privacy, credential, trace, audio, fixture, or Git artifact
  protections;
- delete the existing Slice 3B.1 master plan;
- consolidate or rewrite unrelated ADRs;
- perform a general source-code or test-suite refactor;
- encode, obfuscate, split, or rename terms for the purpose of bypassing a
  classifier;
- claim statistical proof from a small operational A/B sample.

## Governing Principles

1. Accepted ADRs remain the architecture source of truth.
2. Auto-loaded context contains durable invariants, not duplicated mechanical
   checklists.
3. Detailed enforcement belongs in tests, scripts, and referenced governance
   documents.
4. Active task context is proportional to the task being performed.
5. Complex work can still be requested at goal level; Task Cards and Work
   Packages are context-packaging mechanisms, not a requirement for the user to
   micromanage implementation.
6. Migration is shadow-first and reversible.
7. The old execution path remains active until equivalence and A/B gates pass.

## Selected Approach

Use a balanced shadow migration:

1. build candidate context surfaces alongside the current ones;
2. prove semantic equivalence locally;
3. run controlled Codex A/B scenarios;
4. update ADR-015 and switch the formal execution entry atomically;
5. retain the prior plan and a clear rollback path.

The alternatives rejected for this scope are:

- only splitting plans while leaving the auto-loaded instruction unchanged,
  because the persistent context would remain largely unchanged; and
- performing repo-wide documentation and source-code slimming at the same
  time, because it would expand scope and obscure which change affected Codex
  behavior.

## Architecture

### Source-of-truth layer

The following remain authoritative:

- `stage_b_adr_register.md`;
- accepted files under `docs/adr/`;
- canonical event and adapter specifications referenced by those ADRs.

The context-slimming layer may summarize or point to these sources. It may not
create a competing architecture rule.

### Shadow context layer

The shadow phase adds:

- `docs/governance/codex-context/AGENTS.candidate.md`
  - candidate for the future root `AGENTS.md`;
  - contains concise, durable invariants and precise source references;
  - is not auto-loaded during the shadow phase.
- `docs/governance/codex-context/invariant-map.md`
  - maps every current repo instruction and P0/P1 review item to a stable
    invariant, authoritative ADR location, and enforcement mechanism;
  - is the proof surface for semantic equivalence.
- `docs/governance/codex-task-cards/slice3b1/index.md`
  - lists Task Cards and Work Packages without copying their bodies.
- `docs/governance/codex-task-cards/slice3b1/TC-*.md`
  - contains bounded implementation context for one coherent unit.
- `docs/governance/codex-task-cards/slice3b1/WP-*.md`
  - coordinates a goal-level sequence of Task Cards.
- `scripts/codex-context-audit`
  - validates mappings, references, structure, and context budgets;
  - keeps detailed local compliance patterns out of normal plan prose;
  - emits concise pass/fail summaries by default.
- governance tests under `tests/governance/`
  - verify semantic coverage and audit-script behavior.

### Historical layer

The existing master plan remains at:

`docs/superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md`

During the shadow phase it is not moved or modified. After the switch, it
remains available as the historical design and execution baseline but is no
longer the default day-to-day implementation entry.

## Stable Invariant Families

The candidate instruction groups the current rules into the following stable
families:

| Family | Stable prefix | Scope |
| --- | --- | --- |
| ADR and scope governance | `INV-ADR` | Accepted decisions, scope expansion, and ADR-first development |
| Provider boundary | `INV-ADAPTER` | External model I/O and capability profiles |
| Journal and replay | `INV-JOURNAL` | Critical transitions, canonical events, serialized append, deterministic replay |
| Plan authority | `INV-PLAN` | Task identity, plan version, stale evidence, adoption, and SlowTask lifecycle |
| Tool authority | `INV-TOOL` | Tool Executor, confirmation, demo sandbox, and UI state changes |
| Commitment truthfulness | `INV-COMMITMENT` | SemanticCommitment, Composer coverage, and truthful progress |
| Artifact and privacy policy | `INV-PRIVACY` | Credentials, user data, traces, audio, fixtures, replay cache, and Git |
| Python concurrency | `INV-CONCURRENCY` | Async boundaries, blocking isolation, CPU work, and journal ownership |
| Foreground and projection authority | `INV-FOREGROUND` | Fast Gate, Route Evidence, Qwen context projection, PCM, and delivered history |
| Verification | `INV-VERIFY` | Canonical test entrypoint and per-slice replay or eval |

These families change presentation, not semantics. A family may contain
multiple individually addressable invariants.

## Semantic Equivalence Map

Every current `AGENTS.md` rule, sub-bullet, mandatory artifact rule, and P0/P1
review item must have one row in the equivalence map.

Each row contains:

| Field | Meaning |
| --- | --- |
| `legacy_ref` | Stable line-independent identifier plus the current source heading |
| `legacy_summary` | Concise description of the existing requirement |
| `invariant_id` | New stable invariant identifier |
| `candidate_ref` | Candidate instruction section |
| `authority_refs` | One or more accepted ADR sections |
| `enforcement_refs` | Tests, scripts, or review checks |
| `auto_context` | Whether the requirement must be stated directly in auto-loaded context |
| `equivalence_note` | Why the new wording preserves the old requirement |

Line numbers may be recorded as review aids but cannot be the primary
identifier because they drift.

The audit fails when:

- a legacy rule has no row;
- two incompatible rules are collapsed without an explicit reconciliation;
- an authority reference is missing or not accepted;
- a candidate invariant has no authoritative source;
- an enforcement reference is missing when the legacy rule required mechanical
  validation;
- the map claims a requirement is outside auto-context without providing a
  reliable discovery or enforcement path.

## Candidate Repo Instruction

The candidate root instruction should:

- point to the ADR register;
- state the stable invariants once;
- identify when the relevant ADR must be read;
- define the three execution modes;
- retain the canonical test command;
- point to detailed governance checks instead of copying their full patterns;
- remain understandable without opening the equivalence map;
- avoid relying on truncation or external memory for correctness.

Target size: at most 6 KiB.

The target is a context budget, not a license to omit requirements. If the full
equivalent rule set cannot fit, correctness wins and the migration does not
switch until the design is revised.

Changing `project_doc_max_bytes` to truncate the instruction is explicitly out
of scope.

## Execution Modes

### Quick mode

Quick mode is appropriate for localized work that:

- does not change an accepted ADR or architecture responsibility;
- stays within one existing component boundary;
- has direct existing verification;
- does not discover broader authority or lifecycle implications while running.

Ordinary questions, read-only audits, small documentation fixes, and localized
bug fixes do not require a Task Card.

### Task Card mode

Task Card mode is required when work touches an accepted architecture boundary,
including:

- canonical events or Event Journal behavior;
- provider adapters or capability profiles;
- task identity, plan version, stale evidence, or SlowTask lifecycle;
- Tool Executor, confirmation, or UI state authority;
- Composer or SemanticCommitment coverage;
- privacy, trace, audio, credential, or fixture policy;
- Fast Foreground Gate, Route Evidence, or Qwen projection authority;
- multiple component responsibilities.

A Task Card represents one coherent, independently verifiable implementation
unit. It is not required to be a tiny change.

### Work Package mode

A Work Package represents a goal that requires several dependent Task Cards.
The user may request the Work Package at goal level. Codex may progress through
its cards without the user manually dispatching each one.

Each card still has an independent verification gate. Failure stops the Work
Package at the current card; later edits may not mask the failure.

### Mode selection and escalation

Before mutation, Codex briefly states the selected mode and why.

Quick mode must be upgraded to a Task Card when newly discovered scope crosses
an architecture boundary. Scope may not expand silently.

A Task Card must be promoted into or attached to a Work Package when successful
completion depends on multiple independently verifiable cards.

## Task Card Contract

Each Task Card contains:

1. Task ID and title.
2. Goal.
3. Allowed write files.
4. Required read-only dependencies.
5. Exact ADR sections required for the task.
6. Input and output contracts.
7. Stable invariant IDs that apply.
8. Explicit non-goals.
9. Implementation outline.
10. Verification commands.
11. Pass criteria.
12. Stop conditions.
13. Evidence and handoff requirements.

Task Card constraints:

- recommended size: 4-8 KiB;
- hard maximum: 12 KiB;
- no copied global checklist;
- no copied full ADR;
- no large source, diff, trace, or fixture payload;
- no long inline audit pattern when a checked-in script can own it;
- no unrelated peer tasks;
- dependencies expressed by stable IDs and paths.

## Work Package Contract

Each Work Package contains:

1. Work Package ID and goal.
2. Ordered or dependency-based Task Card list.
3. Entry criteria.
4. Cross-card invariants.
5. Per-card verification policy.
6. Stop, retry, and rollback conditions.
7. Package-level acceptance criteria.
8. Final evidence handoff.

A Work Package does not copy Task Card bodies. It links them and explains only
the cross-card coordination that cannot live in one card.

## Context Budgets

The initial budgets are:

| Surface | Budget |
| --- | ---: |
| Candidate root instruction | 6 KiB maximum |
| Individual Task Card | 12 KiB maximum, 4-8 KiB recommended |
| Typical active bundle | 20 KiB recommended maximum |

The typical active bundle consists of:

- the active root instruction;
- the ADR register;
- one Task Card, or one Work Package plus the current Task Card;
- only the ADR sections and source files needed for the current step.

The budget excludes tool output that is necessary to diagnose an actual
failure, but tools should return bounded, redacted summaries by default.

Budget overruns fail the audit unless the exception is documented with:

- the required additional source;
- why it cannot be summarized or section-selected;
- the bounded duration of the exception;
- the verification that still protects semantic equivalence.

## Compliance Script Behavior

`scripts/codex-context-audit` is local and deterministic. It must not:

- call a model or provider;
- use the network;
- read environment credentials;
- modify the repository;
- emit raw sensitive values;
- depend on wall-clock ordering.

It should provide subcommands or equivalent checks for:

- `mapping`: legacy-to-candidate coverage;
- `references`: paths, headings, and accepted ADR status;
- `budgets`: instruction and card size limits;
- `cards`: Task Card and Work Package schema;
- `artifacts`: required ignored-path and fixture declarations;
- `all`: the complete local gate.

Default output is a concise rule-level summary. A diagnostic mode may identify
safe filenames, line numbers, and rule IDs, but must redact matched values.

## Testing

### Governance tests

Tests must verify:

- every legacy rule has exactly one primary mapping;
- every candidate invariant has accepted authority;
- enforcement references exist;
- no Task Card duplicates the full global instruction;
- size limits are enforced;
- the original master plan remains present during shadow migration;
- audit output does not expose matched values;
- audit execution is deterministic and provider-free.

### Existing project tests

The implementation plan must identify the existing acceptance, replay,
privacy, adapter, tool, and Fast Foreground tests that prove no runtime boundary
changed.

All Python tests use the repository's canonical `./scripts/test` entrypoint and
the configured local interpreter when required by `AGENTS.md`.

### No runtime behavior change

The context-slimming implementation should not require production source
changes. If an implementation step discovers that runtime code must change, it
stops and returns to ADR/design review rather than expanding this project.

## Shadow Rollout

### Phase 0: Baseline

Capture:

- current instruction size;
- current master-plan size;
- legacy rule inventory;
- current A/B scenario results;
- current relevant test baseline.

Raw task/request identifiers and screenshots remain local-only. A committed
acceptance summary contains only redacted aggregate results.

### Phase 1: Shadow build

Add candidate instructions, the equivalence map, Task Cards, Work Packages,
audit scripts, and governance tests without changing the active root
instruction or master-plan path.

### Phase 2: Local equivalence gate

Require:

- zero unmapped legacy rules;
- valid accepted-ADR references;
- passing governance checks;
- passing selected existing safety and replay tests;
- budget compliance;
- no production runtime diff caused by this project.

### A/B workspace preparation

The candidate instruction must not be activated in the working repository merely
to run the A/B test. Instead, prepare two disposable local snapshots from the
same bounded source state:

- the baseline snapshot uses the current root `AGENTS.md` and current execution
  entry; and
- the candidate snapshot differs only in the root instruction and the
  Task Card or Work Package execution entry under test.

The snapshot preparation mechanism must:

- include the same tracked and intentionally selected uncommitted source in
  both snapshots;
- exclude `.git`, environment files, diagnostics, traces, local replay caches,
  raw audio, dependency caches, and other ignored local artifacts;
- emit a manifest of included relative paths and content digests;
- prove that the allowed context-surface files are the only content differences
  between the two snapshots;
- place snapshots under an ignored or temporary local path;
- provide a cleanup command that targets only the explicitly created snapshot
  directories.

The candidate snapshot copies `AGENTS.candidate.md` into the root instruction
position inside that disposable snapshot. This exercises normal instruction
discovery without changing the active repository.

### Phase 3: Controlled Codex A/B

Run the same legitimate, authorized tasks with the same account, model, surface,
approximate time window, and paired snapshot source state.

Scenarios:

1. ordinary local task outside the repository;
2. README-only task in the repository;
3. Quick-mode localized task;
4. Task Card execution;
5. full master-plan execution as a diagnostic control.

Each scenario runs twice against the baseline snapshot and twice against the
candidate snapshot. Record:

- scenario and repetition;
- timestamp and timezone;
- product surface and model;
- exact bounded source set;
- whether content was unavailable, rerouted, delayed, or returned normally;
- visible responding model when available;
- redacted task or request identifier;
- notes on any uncontrolled difference.

If results are mixed, run one additional repeat in a later comparable window
and classify the result as inconclusive until the difference is understood.

### Operational A/B gate

The candidate may switch only when:

- README, Quick-mode, and Task Card candidate runs complete without a
  content-unavailable intervention;
- candidate behavior is no worse than baseline for ordinary local work;
- Task Card behavior is materially better than full master-plan behavior when
  the baseline reproduces the issue;
- all local equivalence and runtime-regression gates pass.

If the baseline issue does not reproduce, the result establishes no regression,
not proof that false positives were eliminated.

## Atomic Switch

After all gates pass:

1. revise ADR-015 to permit concise semantic invariants plus referenced
   mechanical enforcement;
2. keep ADR-015 accepted and preserve every existing rule's authority;
3. replace the root `AGENTS.md` with the reviewed candidate;
4. enable the Task Card and Work Package index as the normal complex-work
   entry;
5. mark the master plan as historical without deleting it;
6. run the complete local gate again;
7. record a redacted acceptance summary.

The switch must be one reviewable change set. It must not include unrelated
Slice 3B.1 implementation edits.

## Rollback

Rollback restores:

- the prior root `AGENTS.md`;
- the prior ADR-015 wording;
- the prior default execution entry.

The following may remain because they do not alter active behavior:

- equivalence map;
- audit script;
- governance tests;
- Task Cards and Work Packages;
- redacted A/B methodology and results.

Rollback is required when:

- a legacy rule is missing or weakened;
- an accepted ADR is contradicted;
- an existing safety or replay test regresses;
- Codex begins acting outside the declared mode or scope;
- the candidate causes new blocking in benign or localized scenarios;
- the atomic switch includes unrelated runtime changes.

## Error Handling

- Missing or ambiguous mapping: fail closed and retain the current instruction.
- Missing ADR section: fail the reference gate; do not substitute memory or a
  nearby document.
- Oversized card: split by responsibility or promote coordination into a Work
  Package.
- Quick-mode scope expansion: stop mutation and create a Task Card.
- Card verification failure: stop the Work Package at that card.
- A/B intervention: preserve the exact notice and redacted identifier locally,
  submit product feedback when appropriate, and do not weaken safety rules in
  response.
- Inconclusive A/B: retain the shadow state and gather another controlled
  sample.

## Security and Privacy

- A/B prompts use legitimate repository tasks only.
- No real credential, private user data, raw audio, raw trace, or unredacted
  provider payload is included in A/B artifacts.
- Local A/B evidence belongs under an ignored diagnostics path.
- Only synthetic or redacted summaries may be committed.
- Context slimming must improve clarity and proportionality; it must not hide
  an actual security-relevant request.

## Acceptance Criteria

The design is implemented successfully only when:

1. the shadow artifacts exist without changing the active instruction;
2. all legacy rules and P0/P1 checks have zero-omission mappings;
3. candidate invariants cite accepted authority;
4. governance and selected existing regression tests pass;
5. the candidate instruction and Task Cards meet their budgets;
6. the master plan remains available as historical evidence;
7. controlled A/B satisfies the operational gate or is explicitly classified
   as inconclusive without switching;
8. ADR-015 is revised before the active instruction changes;
9. the switch contains no runtime architecture change;
10. rollback is documented and verified;
11. no raw or sensitive A/B artifact is committed.

## Expected Repository Impact

Shadow phase:

- one design-approved candidate instruction;
- one semantic equivalence map;
- one Slice 3B.1 Task Card index;
- Task Cards and one or more Work Packages;
- one deterministic audit entrypoint;
- governance tests;
- a redacted acceptance template.

Switch phase:

- semantic-equivalent ADR-015 revision;
- concise root `AGENTS.md`;
- normal complex-work entry redirected to the Task Card index;
- historical marker for the master plan;
- redacted acceptance result.

No production runtime module is expected to change.

## Resolved Decisions

- Primary goal: reduce Codex false positives without weakening any accepted
  boundary.
- ADR-015 may be revised when semantics remain equivalent.
- Controlled A/B testing is required.
- The existing master plan is retained as historical evidence.
- Migration is shadow-first and atomically switched.
- Task Cards are not embedded in `AGENTS.md`.
- Quick mode remains available for ordinary vibe coding.
- Work Packages allow goal-level autonomous progress across related cards.
- Shadow A/B uses paired disposable local snapshots; it does not activate the
  candidate instruction in the working repository.
- Repo-wide source-code slimming is a separate future project.
