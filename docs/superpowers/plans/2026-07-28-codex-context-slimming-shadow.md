# Codex Context Slimming Shadow Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a shadow Codex context system that materially reduces
unnecessary auto-loaded and task-loaded context while preserving every current
repository governance rule, accepted ADR boundary, and runtime safety behavior.

**Architecture:** Keep the current root `AGENTS.md`, accepted ADRs, and Slice
3B.1 master plan active and unchanged. Add a governance-only Python package,
candidate instruction, line-independent equivalence map, bounded Task Cards,
one Work Package, deterministic audit CLI, and paired disposable snapshot
tooling. Prove the shadow artifacts locally, then prepare controlled A/B
evidence; do not perform the active switch in this plan.

**Tech Stack:** Python 3.11 standard library, frozen dataclasses, `argparse`,
`hashlib`, `json`, `pathlib`, `shutil`, Bash entrypoints, Markdown governance
artifacts, and pytest through the repository's `./scripts/test` wrapper.

**Approved design:**
`docs/superpowers/specs/2026-07-28-codex-context-slimming-design.md`

**Written approval:** Received from the user on 2026-07-28 before this plan was
created. The approved design status is synchronized in the same planning change.

## Global Constraints

- This is **Shadow mode**. Do not replace or edit root `AGENTS.md`.
- Do not edit accepted ADRs in this plan. ADR-015 clarification and the root
  instruction replacement belong to a separate Atomic Switch plan after the
  operational A/B gate passes.
- Do not edit, move, or delete
  `docs/superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md`.
- Do not change production runtime behavior, event schemas, adapter behavior,
  Router/Gate authority, replay behavior, tool behavior, or UI behavior.
- New Python files under `src/voice_agent/governance/` are governance tooling
  only. No runtime module may import them.
- Use only the Python standard library in governance tooling. Do not add or
  install dependencies.
- Run Python tests only through `./scripts/test`. Every test command below uses
  the configured interpreter explicitly.

- Preserve the existing dirty worktree. Never reset, restore, clean, stage, or
  commit unrelated paths.
- Before the first mutation and before every task commit, require
  `git diff --cached --quiet`. If the index already contains user changes, do
  not unstage them; stop and ask the user to clear or commit that index state.
- Every task begins with a scoped `git status --short` and ends with a scoped
  diff review. A commit may contain only the files listed for that task.
- Default CLI output must be deterministic, bounded, and redacted. It may
  contain stable rule IDs, error codes, counts, relative paths, and line
  numbers. It must not contain matched source text, environment values,
  absolute paths, raw exception values, file content, timestamps, random IDs,
  or credentials.
- Snapshot creation is the only mutating tool in this plan. It may write only
  beneath an explicit output directory in `/tmp` or an ignored diagnostics
  path and must use a sentinel plus a manifest for cleanup.
- If any step requires a production runtime edit, new architecture authority,
  a new event, broader scope, provider access, or network access, stop and
  return to design/ADR review.

## Phase Boundary and Authority Reconciliation

The read-only audit found two legacy rule groups whose operational detail is
present in root `AGENTS.md` but not stated verbatim in an accepted ADR:

- `INV-CONCURRENCY`: CPython/GIL assumptions, async/blocking isolation, thread
  restrictions, and sidecar integration detail.
- `INV-VERIFY`: the canonical `./scripts/test` command, interpreter selection,
  no-auto-install behavior, and human approval for dependency fetches.

The shadow map must not hide this fact. For these rows:

1. cite accepted ADR-015 `Decision` as the authority for the repository
   instruction surface;
2. cite the behavioral ADRs that cover the underlying safety property
   (primarily ADR-002 and ADR-012);
3. retain the operational specificity directly in the candidate instruction;
4. set `switch_prerequisite` to
   `ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED`;
5. make `switch_readiness` fail until a later Atomic Switch change explicitly
   adds the equivalent wording to ADR-015.

This allows the shadow equivalence check to be truthful without claiming that
ADR-015 already contains wording it does not contain. The active root
instruction remains authoritative throughout this plan.

## Baseline Snapshot

At plan-writing time:

| Surface | UTF-8 bytes | SHA-256 |
| --- | ---: | --- |
| root `AGENTS.md` | 9,950 | `c9674b955b0bda8b301b7159f6a87016989ac318262999d60247045af652d984` |
| Slice 3B.1 master plan | 151,857 | `1d047b13d7adc775b25fa6eeede452e75c3710234deb9f505bb3124f927c3cb4` |

The implementation must re-read these values before Task 1. If either digest
changed, do not overwrite the new state or silently update expected mappings.
Record the new digest, review the changed source, and update this plan or the
approved design before continuing.

## Repository Impact

```text
docs/
├── governance/
│   ├── codex-context/
│   │   ├── AGENTS.candidate.md
│   │   ├── ab-scenarios.md
│   │   ├── invariant-map.md
│   │   └── shadow-baseline.md
│   └── codex-task-cards/
│       └── slice3b1/
│           ├── index.md
│           ├── TC-S3B1-01-events-and-envelopes.md
│           ├── TC-S3B1-02-capabilities-and-assembly.md
│           ├── TC-S3B1-03-protocol-and-transport.md
│           ├── TC-S3B1-04-scripted-wire.md
│           ├── TC-S3B1-05-candidate-quarantine.md
│           ├── TC-S3B1-06-session-lifecycle.md
│           ├── TC-S3B1-07-route-evidence-and-orchestration.md
│           ├── TC-S3B1-08-gate-and-release.md
│           ├── TC-S3B1-09-replay.md
│           ├── TC-S3B1-10-scenario-runner.md
│           ├── TC-S3B1-11-cli-and-acceptance.md
│           └── WP-S3B1-01.md
└── implementation/
│   └── codex-context-slimming-shadow-acceptance.md
scripts/
├── codex-context-audit
└── codex-context-snapshot
src/voice_agent/governance/
├── __init__.py
└── codex_context/
    ├── __init__.py
    ├── audit.py
    ├── audit_cli.py
    ├── markdown.py
    ├── model.py
    ├── snapshot.py
    └── snapshot_cli.py
tests/governance/
├── codex_context_test_support.py
├── test_codex_context_cli.py
├── test_codex_context_mapping.py
├── test_codex_context_snapshots.py
└── test_codex_context_structure.py
```

## Stable Data Contracts

Use these public types and names throughout the implementation. Keep them in
`src/voice_agent/governance/codex_context/model.py`.

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

AuditCheck = Literal["mapping", "references", "budgets", "cards", "artifacts"]
Severity = Literal["error", "warning"]
EnforcementKind = Literal["pytest", "script", "review-check"]


@dataclass(frozen=True)
class LegacyRule:
    legacy_ref: str
    source_heading: str
    source_kind: str
    normalized_digest: str


@dataclass(frozen=True)
class AuthorityRef:
    path: PurePosixPath
    heading: str


@dataclass(frozen=True)
class EnforcementRef:
    kind: EnforcementKind
    path: PurePosixPath
    symbol: str


@dataclass(frozen=True)
class CandidateInvariant:
    invariant_id: str
    heading: str
    normalized_clause_digest: str


@dataclass(frozen=True)
class InvariantMapping:
    legacy_ref: str
    legacy_summary: str
    source_heading: str
    normalized_digest: str
    invariant_id: str
    candidate_ref: str
    candidate_clause_digest: str
    authority_refs: tuple[AuthorityRef, ...]
    enforcement_refs: tuple[EnforcementRef, ...]
    auto_context: bool
    equivalence_note: str
    switch_prerequisite: str | None


@dataclass(frozen=True)
class AuditPaths:
    repo_root: Path
    legacy_instruction: Path
    candidate_instruction: Path
    invariant_map: Path
    card_root: Path
    adr_register: Path
    master_plan: Path


@dataclass(frozen=True)
class AuditIssue:
    check: AuditCheck
    code: str
    rule_id: str | None
    relative_path: PurePosixPath | None
    line: int | None
    severity: Severity = "error"


@dataclass(frozen=True)
class CheckReport:
    check: AuditCheck
    issues: tuple[AuditIssue, ...]
    checked_count: int

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class AuditReport:
    reports: tuple[CheckReport, ...]
    switch_ready: bool
    switch_prerequisites: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(report.passed for report in self.reports)
```

`passed` means the requested shadow checks passed. `switch_ready` is stricter:
it remains false while
`ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED` is present.

---

## Task 1: Freeze the approved baseline and implement the legacy-rule inventory

**Files:**

- Create: `docs/governance/codex-context/shadow-baseline.md`
- Create: `src/voice_agent/governance/__init__.py`
- Create: `src/voice_agent/governance/codex_context/__init__.py`
- Create: `src/voice_agent/governance/codex_context/model.py`
- Create: `src/voice_agent/governance/codex_context/markdown.py`
- Create: `tests/governance/codex_context_test_support.py`
- Create: `tests/governance/test_codex_context_mapping.py`

### Step 1.1: Revalidate the source baseline and worktree scope

- [ ] Run:

  ```bash
  wc -c AGENTS.md \
    docs/superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md
  shasum -a 256 AGENTS.md \
    docs/superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md
  git status --short
  git diff --cached --quiet
  ```

- [ ] Confirm the sizes and digests match the Baseline Snapshot above.
- [ ] Save the complete `git status --short` output outside Git under
  `diagnostics/codex-context/pre-shadow-status.txt`. The `diagnostics/` path is
  already ignored; create the local-only file with `apply_patch`, not shell
  redirection, and do not commit it.
- [ ] Confirm `git diff --cached --quiet` exits zero. If it does not, stop
  without changing the user's index.
- [ ] Confirm root `AGENTS.md`, ADR-015, ADR-018, and the master plan are dirty
  or untracked exactly as expected. Do not alter their pre-existing content.

Expected outcome: baseline matches, and no cleanup/reset action is needed. If a
digest differs, stop this task.

### Step 1.2: Capture the pre-mutation runtime baseline

- [ ] Before creating any shadow artifact or Python package, run exactly:

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

- [ ] Record only test node IDs, pass/fail counts, and safe failure categories in
  the local pre-shadow diagnostics record. Record the operational A/B state as
  `not-run`.
- [ ] If this selected suite fails, stop before mutation. Preserve the failure
  as the pre-existing baseline and ask for direction; do not repair runtime
  code in this context-slimming plan.
- [ ] The selected suite is the declared pre-mutation runtime baseline. The full
  suite is intentionally deferred to Task 8 because the worktree contains
  active Slice 3B.1 development, but it must still run before shadow completion.

### Step 1.3: Write the failing inventory tests

- [ ] Add a test support builder that creates a minimal synthetic repository
  without reading the live repository:

  ```python
  from __future__ import annotations

  from pathlib import Path


  def write_text(root: Path, relative_path: str, content: str) -> Path:
      path = root / relative_path
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(content, encoding="utf-8")
      return path
  ```

- [ ] Add these tests to
  `tests/governance/test_codex_context_mapping.py`:

  ```python
  from __future__ import annotations

  from pathlib import Path

  from voice_agent.governance.codex_context.markdown import (
      collect_legacy_rules,
      normalize_requirement,
  )


  ROOT = Path(__file__).resolve().parents[2]


  def test_normalization_is_independent_of_line_wrapping_and_line_numbers() -> None:
      assert normalize_requirement("alpha\n  beta  `x`") == "alpha beta `x`"
      assert normalize_requirement("alpha beta `x`") == "alpha beta `x`"


  def test_live_legacy_inventory_has_exact_expected_coverage() -> None:
      rules = collect_legacy_rules(ROOT / "AGENTS.md")
      assert len(rules) == 111
      assert len({rule.legacy_ref for rule in rules}) == 111
      assert len({rule.normalized_digest for rule in rules}) == 111
      assert {rule.source_kind for rule in rules} == {
          "preamble-rule",
          "ordered-rule",
          "nested-rule",
          "section-rule",
          "standalone-rule",
      }


  def test_inventory_rejects_a_missing_governance_section(tmp_path: Path) -> None:
      path = tmp_path / "AGENTS.md"
      path.write_text("# AGENTS.md\n\n## Core Rules\n\n1. rule\n", encoding="utf-8")
      try:
          collect_legacy_rules(path)
      except ValueError as exc:
          assert str(exc) == "legacy_instruction_missing_required_sections"
      else:
          raise AssertionError("missing governance sections must fail closed")
  ```

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test \
    tests/governance/test_codex_context_mapping.py::test_normalization_is_independent_of_line_wrapping_and_line_numbers \
    tests/governance/test_codex_context_mapping.py::test_live_legacy_inventory_has_exact_expected_coverage \
    tests/governance/test_codex_context_mapping.py::test_inventory_rejects_a_missing_governance_section \
    -q
  ```

Expected RED: import failure because the governance package does not exist.

### Step 1.4: Implement typed models and deterministic Markdown inventory

- [ ] Add the Stable Data Contracts above to `model.py`.
- [ ] Export only documented public types from the two `__init__.py` files.
- [ ] Implement in `markdown.py`:

  ```python
  def normalize_requirement(value: str) -> str:
      return " ".join(value.split())


  def requirement_digest(value: str) -> str:
      normalized = normalize_requirement(value)
      return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


  def collect_legacy_rules(path: Path) -> tuple[LegacyRule, ...]:
      text = path.read_text(encoding="utf-8")
      return collect_legacy_rules_from_text(text)
  ```

- [ ] `collect_legacy_rules_from_text` must inventory exactly these semantic
  surfaces by heading, not by line number:

  | Surface | Items |
  | --- | ---: |
  | Repository-governance preamble, ADR register declaration, and accepted-ADR location | 3 |
  | 13 ordered Core Rules | 13 |
  | nested bullets beneath Core Rules | 49 |
  | MVP Scope Reminder | 4 |
  | Local Debug Artifacts | 6 |
  | Mandatory Repository Artifact Rules, including six ignore paths and the final synthetic-fixture sentence | 13 |
  | Code Review P0/P1 Checklist | 22 |
  | ADR Index source-of-truth sentence | 1 |
  | **Total** | **111** |

- [ ] Assign stable refs by semantic surface and explicit ordinal, for example
  `LEGACY-PREAMBLE-01`, `LEGACY-CORE-01`, `LEGACY-CORE-01-01`,
  `LEGACY-ARTIFACT-IGNORE-01`, and `LEGACY-REVIEW-01`. Store a digest of
  normalized source text so wording drift fails review.
- [ ] Reject missing required headings, duplicate digests, malformed list
  nesting, or a total other than 111 with stable error codes. Never include
  source text in exception messages.
- [ ] Treat the three preamble declarations as governance rules, not metadata:
  the root file is the repository governance entry, the ADR register is
  `stage_b_adr_register.md`, and accepted decisions live under `docs/adr/`.

### Step 1.5: Record the safe baseline

- [ ] Create `shadow-baseline.md` with:

  - date and `Asia/Shanghai` timezone;
  - the two byte counts and digests above;
  - legacy inventory count `111`;
  - current active surfaces;
  - selected pre-mutation runtime baseline counts;
  - operational A/B state `not-run`;
  - statement that root `AGENTS.md`, ADRs, and master plan remain active;
  - statement that raw task IDs, screenshots, prompts, and status output remain
    local-only;
  - selected regression commands to be captured in Task 8.

- [ ] Do not paste `git status`, request IDs, prompts, source text, or logs into
  this committed document.

### Step 1.6: Verify and commit Task 1

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance/test_codex_context_mapping.py -q
  git diff --check -- \
    docs/governance/codex-context/shadow-baseline.md \
    src/voice_agent/governance \
    tests/governance/codex_context_test_support.py \
    tests/governance/test_codex_context_mapping.py
  ```

- [ ] Review the scoped diff and confirm no live instruction, ADR, master plan,
  or runtime file changed.
- [ ] Commit only Task 1 files:

  ```bash
  git add \
    docs/governance/codex-context/shadow-baseline.md \
    src/voice_agent/governance/__init__.py \
    src/voice_agent/governance/codex_context/__init__.py \
    src/voice_agent/governance/codex_context/model.py \
    src/voice_agent/governance/codex_context/markdown.py \
    tests/governance/codex_context_test_support.py \
    tests/governance/test_codex_context_mapping.py
  git diff --cached --name-only
  git commit -m "test: inventory codex governance rules"
  ```

---

## Task 2: Add the candidate instruction and zero-omission equivalence map

**Files:**

- Create: `docs/governance/codex-context/AGENTS.candidate.md`
- Create: `docs/governance/codex-context/invariant-map.md`
- Modify: `src/voice_agent/governance/codex_context/markdown.py`
- Modify: `tests/governance/test_codex_context_mapping.py`

### Step 2.1: Write failing map parsing and coverage tests

- [ ] Add tests named
  `test_mapping_requires_exactly_one_primary_row_per_legacy_rule`,
  `test_mapping_rejects_candidate_invariant_without_accepted_authority`,
  `test_mapping_requires_existing_enforcement_reference`, and
  `test_mapping_marks_only_known_operational_authority_gaps`,
  `test_mapping_resolves_every_candidate_ref_and_invariant_clause`, and
  `test_mapping_rejects_orphan_candidate_invariant`.

- [ ] Implement the test bodies against the live root instruction, candidate,
  map, ADR register, and repository root. Assert:

  - mapped `legacy_ref` set equals the 111-rule inventory set;
  - every legacy ref occurs exactly once as a primary map row;
  - every normalized digest equals the current source digest;
  - every candidate invariant prefix is one of the ten approved families;
  - every `candidate_ref` is an exact candidate heading;
  - every `invariant_id` is present as an individually addressable clause under
    that heading;
  - every `candidate_clause_digest` equals the normalized live clause digest;
  - the mapped invariant-ID set equals the candidate invariant-ID set, so a
    missing or orphan candidate clause fails;
  - every `auto_context=true` row resolves to a clause stated directly in the
    candidate, not only to the map or an external document;
  - every mapping has at least one authority and one enforcement ref;
  - the only permitted switch prerequisite is
    `ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED`;
  - that prerequisite appears only on `INV-CONCURRENCY-*` and
    `INV-VERIFY-*` rows.

- [ ] Run the six tests through `./scripts/test`.

Expected RED: candidate/map files and `load_invariant_map` do not exist.

### Step 2.2: Implement the canonical map representation

- [ ] In `invariant-map.md`, keep a short human-readable introduction and
  invariant-family summary.
- [ ] Store machine-readable rows between these exact markers:

  ````markdown
  <!-- codex-context-map:v1 begin -->
  ```json
  {"schema":"voice_agent.codex_context.invariant_map.v1","rows":[]}
  ```
  <!-- codex-context-map:v1 end -->
  ````

- [ ] Populate `rows` with all 111 mappings. Each row must contain:

  ```json
  {
    "legacy_ref": "LEGACY-CORE-01",
    "legacy_summary": "Architecture changes follow accepted ADRs",
    "source_heading": "基本原则 / Core Rules",
    "normalized_digest": "64 lowercase hexadecimal characters",
    "invariant_id": "INV-ADR-01",
    "candidate_ref": "INV-ADR — ADR and scope governance",
    "candidate_clause_digest": "64 lowercase hexadecimal characters",
    "authority_refs": [
      {
        "path": "docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md",
        "heading": "Decision"
      }
    ],
    "enforcement_refs": [
      {
        "kind": "review-check",
        "path": "docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md",
        "symbol": "Validation Method"
      }
    ],
    "auto_context": true,
    "equivalence_note": "The candidate states the same precondition and points to the accepted register.",
    "switch_prerequisite": null
  }
  ```

- [ ] The JSON must be valid, UTF-8, sorted by `legacy_ref`, and free of
  comments or trailing commas.
- [ ] Implement:

  ```python
  MAP_BEGIN = "<!-- codex-context-map:v1 begin -->"
  MAP_END = "<!-- codex-context-map:v1 end -->"


  def load_invariant_map(path: Path) -> tuple[InvariantMapping, ...]:
      return load_invariant_map_from_text(path.read_text(encoding="utf-8"))
  ```

- [ ] Reject duplicate refs, unknown fields, malformed booleans, empty
  summaries, empty equivalence notes, invalid invariant prefixes, absolute
  paths, parent traversal, invalid enforcement kinds, empty enforcement
  symbols, and non-hex legacy/candidate digests with stable error codes.

- [ ] Implement
  `collect_candidate_invariants(path: Path) -> tuple[CandidateInvariant, ...]`.
  It must parse exact Markdown headings and invariant clauses, normalize each
  clause, calculate its digest, and reject duplicate IDs or an invariant clause
  outside its declared family heading.

### Step 2.3: Write the candidate instruction

- [ ] Keep `AGENTS.candidate.md` self-contained and at most 6,144 UTF-8 bytes.
- [ ] Include exactly these high-level sections:

  1. `# AGENTS.md`
  2. `## Authority and mode selection`
  3. `## Stable invariants`
  4. `## Verification and detailed checks`
  5. `## Scope reminder`

- [ ] Give each family an exact third-level heading of the form
  `### INV-ADR — ADR and scope governance`. Under it, write individually
  addressable clauses whose lines begin with a stable ID such as
  `- INV-ADR-01:`. State all ten invariant families once:

  - `INV-ADR`: accepted ADRs and scope changes;
  - `INV-ADAPTER`: adapter-only external model I/O and truthful capabilities;
  - `INV-JOURNAL`: critical transitions, canonical events, serialized append,
    and deterministic replay;
  - `INV-PLAN`: task identity, plan version, stale evidence, adopt/rebase,
    lifecycle, confirmation, and cancellation;
  - `INV-TOOL`: Tool Executor authority, demo sandbox, UI patching, web evidence,
    and confirmation;
  - `INV-COMMITMENT`: immutable commitments, coverage, and truthful progress;
  - `INV-PRIVACY`: no secrets/raw artifacts, redaction, allowed fixtures, and
    required ignored paths;
  - `INV-CONCURRENCY`: CPython assumption, async boundary, isolated blocking/CPU
    work, thread restriction, serialized journal ownership, deterministic
    reducer/replay, and sidecar boundary;
  - `INV-FOREGROUND`: local Router/Gate authority, quarantined candidate,
    release/PCM contract, trustworthy context projection, and delivered
    history;
  - `INV-VERIFY`: canonical local test entrypoint, no automatic dependency
    fetch, and replay/eval per slice.

- [ ] Define Quick, Task Card, and Work Package mode selection and escalation in
  concise prose. Task Cards are linked, not embedded.
- [ ] Link:

  - `stage_b_adr_register.md`;
  - `docs/adr/`;
  - `docs/governance/codex-context/invariant-map.md`;
  - `docs/governance/codex-task-cards/slice3b1/index.md`;
  - `scripts/codex-context-audit`;
  - `./scripts/test`.

- [ ] Preserve all six ignore patterns directly or by an unambiguous required
  set in auto-context:
  `diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`, `.env`, `.env.*`.
- [ ] Do not use euphemisms or obfuscation. Concision comes from deduplication
  and references, not from hiding the repository's actual boundaries.

### Step 2.4: Populate authority and enforcement mappings

- [ ] Use this primary-family allocation:

  | Family | Legacy coverage |
  | --- | --- |
  | `INV-ADR` | governance preamble, Core 1 and 11, MVP scope, ADR index |
  | `INV-ADAPTER` | Core 2 and direct-provider review rule |
  | `INV-JOURNAL` | Core 3 and journal/event/controller review rules |
  | `INV-PLAN` | Core 4 and stale/plan-binding review rules |
  | `INV-TOOL` | Core 8-9 and tool/authorization review rules |
  | `INV-COMMITMENT` | Core 7 and Composer review rule |
  | `INV-PRIVACY` | Core 5-6, local/mandatory artifacts, ignores, sensitive-log review rule |
  | `INV-CONCURRENCY` | Core 12 and concurrency/blocking/sidecar review rules |
  | `INV-FOREGROUND` | Fast Gate plus all ADR-018 authority/projection/PCM/history/memory review rules |
  | `INV-VERIFY` | Core 10 and 13 |

- [ ] Use accepted ADR authority references from ADR-001, ADR-002, ADR-004,
  ADR-005, ADR-009, ADR-010, ADR-011, ADR-012, ADR-013, ADR-014, ADR-015,
  ADR-016, ADR-017, and ADR-018 as applicable. Use exact second-level heading
  names, never line numbers.
- [ ] Use existing tests as behavioral enforcement references. At minimum map
  to the event journal, deterministic replay, stale result, destructive
  confirmation, Composer coverage, progress truthfulness, fixture safety,
  Fast Foreground Gate, Router authority, context projection, release contract,
  provider readiness, and ADR-018 replay suites identified in the approved
  design audit.
- [ ] Give every enforcement reference one truthful kind:

  - `pytest`: an existing Python test path plus an exact `test_*` function;
  - `script`: an existing executable repository script plus an exact supported
    command/check name;
  - `review-check`: an exact named review-check heading in root `AGENTS.md`,
    the candidate instruction, or an accepted ADR.

- [ ] Do not use `stage_b_adr_register.md`, a generic source document, or a
  path-only reference as enforcement. The register is authority discovery; it
  is not a mechanical or review enforcement mechanism.
- [ ] Give the native/sidecar review rule one primary family
  (`INV-CONCURRENCY`) and secondary authorities for adapter, tool, and journal
  boundaries. Do not duplicate its primary row.

### Step 2.5: Run the focused gate and commit

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance/test_codex_context_mapping.py -q
  wc -c docs/governance/codex-context/AGENTS.candidate.md
  git diff --check -- \
    docs/governance/codex-context/AGENTS.candidate.md \
    docs/governance/codex-context/invariant-map.md \
    src/voice_agent/governance/codex_context/markdown.py \
    tests/governance/test_codex_context_mapping.py
  ```

- [ ] Expected GREEN: 111 exact mappings, candidate no larger than 6,144
  bytes, and only the two known operational groups carry a switch prerequisite.
- [ ] Commit only Task 2 files:

  ```bash
  git add \
    docs/governance/codex-context/AGENTS.candidate.md \
    docs/governance/codex-context/invariant-map.md \
    src/voice_agent/governance/codex_context/markdown.py \
    tests/governance/test_codex_context_mapping.py
  git diff --cached --name-only
  git commit -m "docs: add shadow codex invariants"
  ```

---

## Task 3: Implement reference, budget, card, and artifact auditors

**Files:**

- Create: `src/voice_agent/governance/codex_context/audit.py`
- Create: `tests/governance/test_codex_context_structure.py`
- Modify: `src/voice_agent/governance/codex_context/__init__.py`
- Modify: `tests/governance/test_codex_context_mapping.py`

### Step 3.1: Write failing reference tests

- [ ] Add tests named
  `test_references_require_exact_heading_and_registered_accepted_adr`,
  `test_reference_rejects_parent_traversal_and_absolute_paths`, and
  `test_enforcement_reference_requires_existing_symbol`,
  `test_enforcement_rejects_register_and_generic_document_references`, and
  `test_candidate_reference_rejects_missing_heading_clause_or_digest_drift`.

- [ ] Use synthetic ADR/register fixtures. Verify exact Markdown heading
  matching, `## Status` value `accepted`, ADR register membership, repository
  containment, candidate heading/clause resolution, existing enforcement paths,
  and exact symbol discovery.
- [ ] Run the five tests. Expected RED: `audit_references` does not exist.

### Step 3.2: Implement reference validation

- [ ] Implement `default_audit_paths(repo_root: Path) -> AuditPaths` with these
  exact relative paths:

  ```python
  def default_audit_paths(repo_root: Path) -> AuditPaths:
      return AuditPaths(
          repo_root=repo_root,
          legacy_instruction=repo_root / "AGENTS.md",
          candidate_instruction=repo_root
          / "docs/governance/codex-context/AGENTS.candidate.md",
          invariant_map=repo_root
          / "docs/governance/codex-context/invariant-map.md",
          card_root=repo_root
          / "docs/governance/codex-task-cards/slice3b1",
          adr_register=repo_root / "stage_b_adr_register.md",
          master_plan=repo_root
          / "docs/superpowers/plans/"
          "2026-07-27-qwen-slice3b1-protocol-faithful-fake.md",
      )
  ```

- [ ] Implement `audit_mapping(paths: AuditPaths) -> CheckReport` and
  `audit_references(paths: AuditPaths) -> CheckReport` with the checks specified
  below.

- [ ] `audit_mapping` performs set equality, duplicate, digest, prefix,
  auto-context, candidate-clause/digest, orphan-clause, and switch-prerequisite
  checks.
- [ ] `audit_references` validates exact paths/headings/accepted status and
  enforcement paths/symbols. For `pytest`, parse the file with `ast` and require
  the exact top-level or class test function without importing it. For `script`,
  require a regular executable file; symbol `__entrypoint__` validates the
  executable itself, while any other symbol must be a literal supported
  subcommand/check token in the script or its directly invoked CLI module. For
  `review-check`, require an exact Markdown heading in one of the permitted
  governance/ADR surfaces. It must never import referenced Python modules or
  execute referenced scripts.
- [ ] Reject the ADR register, arbitrary Markdown, path-only references,
  non-test Python symbols, and a script without an executable bit as
  enforcement.
- [ ] Sort issues by `(check, code, rule_id, relative_path, line)` with `None`
  normalized to an empty string or zero only in the sort key.

### Step 3.3: Write failing structure and budget tests

- [ ] Add tests named
  `test_budgets_count_utf8_bytes_and_enforce_6_12_20_kib`,
  `test_cards_require_every_task_card_contract_section`,
  `test_work_packages_reference_existing_cards_without_copying_card_bodies`,
  `test_card_rejects_embedded_full_candidate_instruction`, and
  `test_artifacts_require_ignored_paths_and_historical_master_plan`.

- [ ] Synthetic tests must prove UTF-8 byte counting rather than character
  counting and exercise boundaries at 6,144, 12,288, and 20,480 bytes.
- [ ] Run the tests. Expected RED: the three auditors do not exist.

### Step 3.4: Implement structure auditors

- [ ] Define these exact constants:

  ```python
  CANDIDATE_MAX_BYTES = 6 * 1024
  CARD_MAX_BYTES = 12 * 1024
  ACTIVE_BUNDLE_RECOMMENDED_BYTES = 20 * 1024
  ```

- [ ] Implement `audit_budgets(paths: AuditPaths) -> CheckReport`,
  `audit_cards(paths: AuditPaths) -> CheckReport`, and
  `audit_artifacts(paths: AuditPaths) -> CheckReport` with the checks specified
  below.

- [ ] Required Task Card headings are the 13 contract fields from the approved
  design: Task ID/title, Goal, Allowed write files, Required read-only
  dependencies, Exact ADR sections, Input/output contracts, Stable invariant
  IDs, Non-goals, Implementation outline, Verification commands, Pass
  criteria, Stop conditions, and Evidence/handoff.
- [ ] Required Work Package headings are the eight contract fields from the
  approved design.
- [ ] Parse dependencies and paths as explicit Markdown links or inline paths.
  Require referenced cards and files to exist. Reject a card that contains all
  ten candidate invariant bodies or more than 70 percent of the candidate
  instruction's normalized non-heading lines.
- [ ] Budget errors:

  - candidate above 6 KiB: error;
  - card above 12 KiB: error;
  - active bundle above 20 KiB: warning only during shadow, with the calculated
    component sizes;
  - Work Package/card exception without all four exception fields from the
    design: error.

- [ ] `audit_artifacts` verifies:

  - required `.gitignore` coverage for `diagnostics/`, `traces/`,
    `replays/local/`, `audio/raw/`, `.env`, and `.env.*`;
  - original master plan exists and its digest matches the Task 1 baseline;
  - candidate and cards contain no embedded data URI, PEM boundary, or known
    raw-artifact path;
  - every declared fixture enforcement path exists.

- [ ] Artifact diagnostics may report rule IDs and relative paths only. Do not
  report matched content.

### Step 3.5: Run focused tests and commit

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test \
    tests/governance/test_codex_context_mapping.py \
    tests/governance/test_codex_context_structure.py \
    -q
  git diff --check -- \
    src/voice_agent/governance/codex_context \
    tests/governance/test_codex_context_mapping.py \
    tests/governance/test_codex_context_structure.py
  ```

- [ ] Commit only Task 3 files:

  ```bash
  git add \
    src/voice_agent/governance/codex_context/__init__.py \
    src/voice_agent/governance/codex_context/audit.py \
    tests/governance/test_codex_context_mapping.py \
    tests/governance/test_codex_context_structure.py
  git diff --cached --name-only
  git commit -m "test: enforce codex context structure"
  ```

---

## Task 4: Create the Slice 3B.1 Task Cards and Work Package

**Files:**

- Create: `docs/governance/codex-task-cards/slice3b1/index.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-01-events-and-envelopes.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-02-capabilities-and-assembly.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-03-protocol-and-transport.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-04-scripted-wire.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-05-candidate-quarantine.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-06-session-lifecycle.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-07-route-evidence-and-orchestration.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-08-gate-and-release.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-09-replay.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-10-scenario-runner.md`
- Create:
  `docs/governance/codex-task-cards/slice3b1/TC-S3B1-11-cli-and-acceptance.md`
- Create: `docs/governance/codex-task-cards/slice3b1/WP-S3B1-01.md`
- Modify: `tests/governance/test_codex_context_structure.py`

### Step 4.1: Add failing live-card contract tests

- [ ] Add tests named
  `test_live_slice3b1_cards_match_declared_dependency_dag`,
  `test_live_slice3b1_cards_stay_within_write_sets_and_budgets`,
  `test_live_work_package_promotes_master_plan_task12_to_package_gate`, and
  `test_live_work_package_requires_verify_first_resume_audit`.

- [ ] Encode this dependency DAG:

  ```python
  EXPECTED_DEPENDENCIES = {
      "TC-S3B1-01": (),
      "TC-S3B1-02": ("TC-S3B1-01",),
      "TC-S3B1-03": (),
      "TC-S3B1-04": ("TC-S3B1-03",),
      "TC-S3B1-05": ("TC-S3B1-03",),
      "TC-S3B1-06": (
          "TC-S3B1-01",
          "TC-S3B1-02",
          "TC-S3B1-03",
          "TC-S3B1-04",
          "TC-S3B1-05",
      ),
      "TC-S3B1-07": (
          "TC-S3B1-01",
          "TC-S3B1-02",
          "TC-S3B1-05",
          "TC-S3B1-06",
      ),
      "TC-S3B1-08": (
          "TC-S3B1-01",
          "TC-S3B1-02",
          "TC-S3B1-05",
          "TC-S3B1-06",
          "TC-S3B1-07",
      ),
      "TC-S3B1-09": (
          "TC-S3B1-01",
          "TC-S3B1-06",
          "TC-S3B1-07",
          "TC-S3B1-08",
      ),
      "TC-S3B1-10": (
          "TC-S3B1-01",
          "TC-S3B1-02",
          "TC-S3B1-03",
          "TC-S3B1-04",
          "TC-S3B1-05",
          "TC-S3B1-06",
          "TC-S3B1-07",
          "TC-S3B1-08",
          "TC-S3B1-09",
      ),
      "TC-S3B1-11": ("TC-S3B1-09", "TC-S3B1-10"),
  }
  ```

- [ ] Run the four tests. Expected RED: card files do not exist.

### Step 4.2: Create the card index

- [ ] `index.md` contains:

  - a short explanation of Quick/Task Card/Work Package usage;
  - a table with ID, title, dependencies, status, and link;
  - one link to `WP-S3B1-01.md`;
  - one link to the historical master plan;
  - no copied card body or global checklist;
  - status values limited to `not-started`, `in-progress`, `blocked`,
    `verified`, and `superseded`.

- [ ] Initialize card statuses using a verify-first rule. Existing source paths
  do not imply completion; initialize all cards to `not-started` until their
  focused and overlap tests are run.

### Step 4.3: Create the eleven cards

- [ ] Use the same 13 headings in every card.
- [ ] Copy no implementation body from the master plan. Preserve stable
  interfaces, allowed writes, required reads, exact ADR headings, tests, pass
  criteria, and stop conditions.
- [ ] Use this source decomposition:

  | Card | Historical plan lines | Recommended size | Core scope |
  | --- | ---: | ---: | --- |
  | `TC-S3B1-01` | 110-613 | 6-8 KiB | canonical events, conditional envelopes, safe refs |
  | `TC-S3B1-02` | 614-888 | 5-7 KiB | provider-free capabilities and assembly |
  | `TC-S3B1-03` | 889-1212 | 5-7 KiB | typed protocol and shared transport |
  | `TC-S3B1-04` | 1213-1373 | 4-6 KiB | deterministic scripted wire |
  | `TC-S3B1-05` | 1374-1667 | 6-8 KiB | quarantine and ephemeral text/PCM ownership |
  | `TC-S3B1-06` | 1668-2077 | 7-8 KiB | session adapter, Pump, readiness, generation |
  | `TC-S3B1-07` | 2078-2392 | 7-8 KiB | context, independent evidence, Router, join-only orchestration |
  | `TC-S3B1-08` | 2393-2684 | 7-8 KiB | fail-closed Gate and contract-only release |
  | `TC-S3B1-09` | 2685-2950 | 6-8 KiB | replay reducer and conditional digest |
  | `TC-S3B1-10` | 2951-3366 | 7-8 KiB | controller ingress, runner, scenarios, safe result |
  | `TC-S3B1-11` | 3367-3584 | 5-7 KiB | CLI, minimal fixtures, acceptance evidence |

- [ ] For `Allowed write files`, reproduce only the exact `Files` block of the
  matching historical task. All other paths are read-only.
- [ ] For `Exact ADR sections`, use exact headings, not line numbers. At
  minimum:

  - Cards 01 and 09: ADR-002 `Decision`, `Canonical MVP-0 Event Registry`,
    `ADR-018 Canonical Event Addendum`; ADR-018 `Decision`;
  - Cards 02 and 07: ADR-011 `Decision`, ADR-017 `Decision`, ADR-018 `Decision`;
  - Cards 03-06: ADR-001/003/018 decision sections as applicable;
  - Card 08: ADR-002/017/018 decision and addendum sections;
  - Cards 10-11: ADR-010/015/018 decision and validation sections.

- [ ] Each card includes its focused test command copied from the historical
  task's verification block, plus overlap regressions for already-completed
  dependencies.
- [ ] Each card stops on:

  - ADR conflict;
  - write-set expansion;
  - new architecture capability or event;
  - runtime/provider/network scope expansion;
  - sensitive artifact discovery;
  - focused or overlap test failure.

- [ ] Add the card-specific stop conditions from the decomposition audit:

  - 01: unregistered event, legacy schema drift, unsafe ref/token;
  - 02: mock presented as real/live, native PCM enabled, snapshot-shape drift;
  - 03: transport acquires generation/turn/route/Gate/journal/playback authority;
  - 04: network/credential/time/random dependency or Fake-emitted authority;
  - 05: payload escapes wipeable memory or mutable handle crosses boundary;
  - 06: second Pump/sender, adapter-owned generation, non-clean buffering,
    controller bypass;
  - 07: candidate-visible route classification, authoritative provider memory,
    moved Router authority, model/Gate call from orchestrator;
  - 08: normal runner creates release token/outbox, public contract harness,
    non-atomic append, legacy Gate drift;
  - 09: replay reruns Fake/model/network, reconstructs payload, or depends on
    scheduling;
  - 10: runner/projector owns ingress authority, reads private quarantine state,
    or emits unsafe result data;
  - 11: live/provider/native option, raw fixture content, Fake rerun in replay,
    or unsupported acceptance claim.

### Step 4.4: Create `WP-S3B1-01`

- [ ] Keep the Work Package between 2 and 4 KiB.
- [ ] Include the dependency DAG, entry criteria, cross-card invariants,
  per-card verification, stop/retry/rollback, package acceptance, and final
  evidence headings.
- [ ] Entry criteria:

  - ADR-018 remains accepted and registered;
  - current worktree is recorded without reset/restore;
  - each card receives a verify-first resume audit;
  - file existence is never treated as completion.

- [ ] Promote historical Task 12 (lines 3585-3766) into package-level gates:

  - focused suite;
  - overlap regressions;
  - full `./scripts/test -q`;
  - deterministic repository safety audit;
  - pre/post worktree comparison;
  - independent review;
  - final acceptance-criterion mapping.

- [ ] Do not create a verification-only Task Card.
- [ ] State that the user may request the Work Package goal once; Codex may
  progress card-by-card until a stop condition is met.

### Step 4.5: Verify and commit

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance/test_codex_context_structure.py -q
  wc -c docs/governance/codex-task-cards/slice3b1/*.md
  git diff --check -- docs/governance/codex-task-cards/slice3b1 \
    tests/governance/test_codex_context_structure.py
  ```

- [ ] Confirm every card is no larger than 12,288 bytes and the Work Package
  does not copy card bodies.
- [ ] Commit only Task 4 files:

  ```bash
  git add \
    docs/governance/codex-task-cards/slice3b1 \
    tests/governance/test_codex_context_structure.py
  git diff --cached --name-only
  git commit -m "docs: package slice3b1 into task cards"
  ```

---

## Task 5: Add the deterministic redacted audit CLI

**Files:**

- Create: `src/voice_agent/governance/codex_context/audit_cli.py`
- Create: `scripts/codex-context-audit`
- Create: `tests/governance/test_codex_context_cli.py`
- Modify: `src/voice_agent/governance/codex_context/audit.py`
- Modify: `src/voice_agent/governance/codex_context/__init__.py`

### Step 5.1: Write failing audit orchestration and rendering tests

- [ ] Add tests named
  `test_all_output_is_compact_sorted_and_deterministic`,
  `test_diagnostic_output_contains_only_safe_ids_relative_paths_and_lines`,
  `test_audit_does_not_read_environment_network_clock_or_randomness`, and
  `test_script_entrypoint_uses_repository_python`.

- [ ] In the isolation test, patch `os.environ` access, socket creation,
  `time.time`, `datetime.now`, `random.random`, and `secrets.token_hex` to raise.
  Call the audit against a complete synthetic repo and assert it still
  completes.
- [ ] Put a unique synthetic sensitive marker in a malformed fixture. Assert
  the marker is absent from normal output, diagnostic output, and exception
  messages.
- [ ] Run the four tests. Expected RED: CLI and script do not exist.

### Step 5.2: Implement audit orchestration

- [ ] Add the fixed check order:

  ```python
  CHECK_ORDER: tuple[AuditCheck, ...] = (
      "mapping",
      "references",
      "budgets",
      "cards",
      "artifacts",
  )
  ```

- [ ] Implement
  `run_audit(paths: AuditPaths, checks: tuple[AuditCheck, ...] = CHECK_ORDER) ->
  AuditReport` and
  `render_audit_json(report: AuditReport, *, diagnostic: bool = False) -> str`
  with the rendering contract below.

- [ ] Deduplicate requested checks while preserving `CHECK_ORDER`.
- [ ] Deduplicate and lexically sort switch prerequisites. Set `switch_ready`
  true only when every requested report passes and the prerequisite set is
  empty.
- [ ] Return compact sorted JSON using:

  ```python
  json.dumps(
      payload,
      ensure_ascii=False,
      sort_keys=True,
      separators=(",", ":"),
      allow_nan=False,
  ) + "\n"
  ```

- [ ] Normal output schema:

  ```json
  {
    "checks": [
      {"checked_count": 111, "error_count": 0, "name": "mapping", "passed": true}
    ],
    "passed": true,
    "schema": "voice_agent.codex_context.audit.v1",
    "switch_prerequisites": [
      "ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED"
    ],
    "switch_ready": false
  }
  ```

- [ ] Diagnostic mode may add an `issues` array with only `check`, `code`,
  `line`, `relative_path`, `rule_id`, and `severity`.
- [ ] Exit zero when requested shadow checks pass even if `switch_ready` is
  false. `switch_ready` is a separate explicit field, never silently promoted.

### Step 5.3: Implement the CLI and wrapper

- [ ] `audit_cli.py` exposes `mapping`, `references`, `budgets`, `cards`,
  `artifacts`, and `all`, each with optional `--diagnostic` and
  `--repo-root`.
- [ ] `--repo-root` defaults to the repository resolved from the module path.
  Normalize it once; output never prints the absolute value.
- [ ] `main(argv: Sequence[str] | None = None) -> int` returns `0` on passed
  requested checks and `1` otherwise. Argument errors use argparse exit `2`.
- [ ] Create this wrapper:

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  cd "$REPO_ROOT"

  PYTHON_BIN="${VOICE_AGENT_PYTHON:-python3}"
  export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  exec "$PYTHON_BIN" -m voice_agent.governance.codex_context.audit_cli "$@"
  ```

- [ ] Make the wrapper executable with `chmod +x scripts/codex-context-audit`.

### Step 5.4: Verify determinism and commit

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance/test_codex_context_cli.py -q
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/codex-context-audit all
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/codex-context-audit all --diagnostic
  git diff --check -- \
    scripts/codex-context-audit \
    src/voice_agent/governance/codex_context \
    tests/governance/test_codex_context_cli.py
  ```

- [ ] Run `all` twice and compare output with `cmp` using two files under
  `/tmp`; they must be byte-identical.
- [ ] Confirm output reports `passed: true`,
  `switch_ready: false`, and the ADR-015 prerequisite.
- [ ] Commit only Task 5 files:

  ```bash
  git add \
    scripts/codex-context-audit \
    src/voice_agent/governance/codex_context/audit.py \
    src/voice_agent/governance/codex_context/audit_cli.py \
    src/voice_agent/governance/codex_context/__init__.py \
    tests/governance/test_codex_context_cli.py
  git diff --cached --name-only
  git commit -m "feat: add deterministic codex context audit"
  ```

---

## Task 6: Build safe paired disposable snapshot tooling

**Files:**

- Create: `src/voice_agent/governance/codex_context/snapshot.py`
- Create: `src/voice_agent/governance/codex_context/snapshot_cli.py`
- Create: `scripts/codex-context-snapshot`
- Create: `tests/governance/test_codex_context_snapshots.py`
- Modify: `src/voice_agent/governance/codex_context/model.py`
- Modify: `src/voice_agent/governance/codex_context/__init__.py`

### Step 6.1: Add snapshot data contracts

- [ ] Add to `model.py`:

  ```python
  @dataclass(frozen=True)
  class SnapshotRequest:
      repo_root: Path
      output_root: Path
      candidate_instruction: PurePosixPath
      baseline_entry: PurePosixPath
      candidate_entry: PurePosixPath
      selected_uncommitted: tuple[PurePosixPath, ...] = ()


  @dataclass(frozen=True)
  class SourceEntry:
      relative_path: PurePosixPath
      sha256: str
      size_bytes: int
      origin: Literal["tracked", "selected-uncommitted", "overlay"]


  @dataclass(frozen=True)
  class SnapshotPairManifest:
      schema: str
      pair_digest: str
      pair_name: str
      anchor_kind: Literal["system-temp", "ignored-repo-diagnostics"]
      anchor_digest: str
      source_entries: tuple[SourceEntry, ...]
      expected_differences: tuple[PurePosixPath, ...]


  @dataclass(frozen=True)
  class SnapshotVerification:
      passed: bool
      issue_codes: tuple[str, ...]
      observed_differences: tuple[PurePosixPath, ...]
  ```

### Step 6.2: Write all failing snapshot tests

- [ ] Add tests named
  `test_prepare_pair_uses_same_tracked_and_selected_uncommitted_source`,
  `test_prepare_pair_rejects_ignored_sensitive_cache_and_symlink_paths`,
  `test_prepare_refuses_to_overwrite_existing_pair`,
  `test_prepare_rejects_repo_root_ancestor_and_arbitrary_output_parent`,
  `test_prepare_rejects_symlink_between_anchor_and_pair`,
  `test_pair_diff_matches_overlay_digests_for_same_and_different_entries`,
  `test_manifest_contains_only_safe_sorted_metadata_and_sha256`,
  `test_verify_rejects_unexpected_difference_or_digest_drift`,
  `test_cleanup_requires_pair_sentinel_and_removes_only_manifested_paths`,
  `test_verify_and_cleanup_reject_wrong_anchor_arbitrary_root_and_symlink_parent`,
  `test_snapshot_cli_requires_exact_pair_and_approved_parent`, and
  `test_snapshot_script_entrypoint_uses_repository_python`.

- [ ] Build synthetic Git repositories under `tmp_path` using local
  `git init`, `git add`, and `git commit` only. Configure repository-local
  author name/email in the fixture. Include:

  - tracked files with working-tree modifications;
  - one explicitly selected untracked Task Card;
  - ignored `.env`, diagnostics, traces, replay cache, raw audio, and dependency
    cache paths;
  - a symlink;
  - a FIFO or special file when supported.

- [ ] Assert source selection uses current working-tree bytes for tracked files,
  includes only explicitly selected untracked files, and rejects every unsafe
  path before copying.
- [ ] Assert output containment accepts only a fresh direct child beneath:

  - the canonical system temporary anchor; or
  - `<repo>/diagnostics/codex-context/snapshots/` after Git confirms that anchor
    is ignored.

- [ ] Reject the repository root, any repository ancestor, any arbitrary
  directory, an existing pair root, a symlink pair root, and any
  user-controlled symlink component below the approved anchor.
- [ ] Run the complete snapshot test file:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance/test_codex_context_snapshots.py -q
  ```

  Expected RED: snapshot module and behaviors do not exist. No implementation
  step may begin until all twelve intended tests have been collected and the RED
  failure has been observed.

### Step 6.3: Implement safe source collection

- [ ] Implement
  `collect_source_entries(request: SnapshotRequest) -> tuple[SourceEntry, ...]`,
  `prepare_snapshot_pair(request: SnapshotRequest) -> SnapshotPairManifest`,
  `verify_snapshot_pair(pair_root: Path, *, approved_parent: Path) ->
  SnapshotVerification`, and
  `cleanup_snapshot_pair(pair_root: Path, *, approved_parent: Path) -> None`
  with the containment rules below.

- [ ] Treat `SnapshotRequest.output_root` as the exact pair root, not as a
  parent directory. It must not exist and its parent must be an approved anchor.
- [ ] Require the pair-root basename to match
  `[A-Za-z0-9][A-Za-z0-9._-]{0,80}` so CLI output and manifest metadata remain
  bounded and single-line.
- [ ] Implement one containment validator shared by prepare, verify, and
  cleanup. Canonicalize only the known system/repository anchors, use `lstat`
  for user-controlled components beneath them, and reject any symlink or
  non-directory component. Never infer safety from a string prefix.
- [ ] For system-temp output, accept a fresh direct child of the canonical
  `tempfile.gettempdir()` anchor or canonical `/tmp` anchor. For repository
  output, accept only a fresh direct child of
  `<repo>/diagnostics/codex-context/snapshots/` after `git check-ignore`
  confirms the anchor is ignored. Reject every other parent.
- [ ] Verify and cleanup require the caller's `approved_parent`; require
  `pair_root.parent` to equal it after approved-anchor validation.

- [ ] Use `git ls-files -z` to enumerate tracked files with
  `subprocess.run(..., check=True)`. Validate explicitly selected untracked
  paths with `git check-ignore --stdin -z`; for that command use `check=False`,
  treat return code `1` as “no selected path is ignored,” treat return code `0`
  as a successful result whose output identifies paths to reject, and treat any
  return code above `1` as a Git failure. Invoke Git with an argument list,
  fixed `cwd=request.repo_root`, bounded captured output, and no shell.
- [ ] Reject:

  - `.git`;
  - `.env` and `.env.*`;
  - `diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`;
  - `__pycache__/`, `.pytest_cache/`, `.venv/`, `node_modules/`;
  - ignored paths;
  - absolute paths and parent traversal;
  - symlinks and non-regular files.

- [ ] Read regular files as bytes and copy without transformation. Sort all
  relative POSIX paths before processing.

### Step 6.4: Implement pair overlays and verification

- [ ] Create this exact layout:

  ```text
  <pair-root>/
  ├── .codex-context-snapshot-pair.v1
  ├── pair-manifest.json
  ├── baseline/
  │   ├── AGENTS.md
  │   └── CODEX_TASK.md
  └── candidate/
      ├── AGENTS.md
      └── CODEX_TASK.md
  ```

- [ ] Both snapshots begin from the same selected source entries.
- [ ] Overlay only:

  - live root `AGENTS.md` as baseline `AGENTS.md`;
  - candidate instruction as candidate `AGENTS.md`;
  - `baseline_entry` as baseline `CODEX_TASK.md`;
  - `candidate_entry` as candidate `CODEX_TASK.md`.

- [ ] Manifest content:

  - schema `voice_agent.codex_context.snapshot_pair.v1`;
  - pair-root basename;
  - anchor kind and SHA-256 digest of the canonical anchor identity, never its
    raw absolute path;
  - sorted relative paths;
  - SHA-256 and byte size;
  - origin values;
  - expected differences computed from the two overlay digest pairs;
  - a content-derived pair digest.

- [ ] Candidate `AGENTS.md` must differ from baseline `AGENTS.md`; reject prepare
  if it does not. Therefore `AGENTS.md` is always expected to differ.
- [ ] Include `CODEX_TASK.md` in `expected_differences` only when the baseline
  and candidate entry bytes differ. Identical task entries are valid for
  instruction-only scenarios.
- [ ] Manifest must contain no timestamp, random value, absolute path, source
  content, Git remote, branch, commit author, or environment value.
- [ ] Verifier re-hashes all files, rejects missing/extra paths or digest drift,
  recomputes overlay digests, and requires the observed baseline/candidate diff
  set to equal `expected_differences`.
- [ ] Store schema, pair name, anchor kind/digest, and pair digest in both the
  sentinel and manifest. Verification and cleanup recompute and compare all
  bindings before acting.
- [ ] Cleanup requires the exact bound sentinel, valid manifest, valid approved
  parent, and matching pair-root basename. It removes only `baseline/`,
  `candidate/`, the manifest, sentinel, and then the empty pair root. It
  refuses a symlink pair root, unexpected child, invalid binding, repository
  root/ancestor, arbitrary parent, or target outside the supplied approved
  parent.

### Step 6.5: Implement snapshot CLI and wrapper

- [ ] `snapshot_cli.py` exposes:

  - `prepare --repo-root PATH --output-root PATH --baseline-entry RELPATH
    --candidate-entry RELPATH [--include-uncommitted RELPATH]`;
  - `verify --pair-root PATH --approved-parent PATH`;
  - `cleanup --pair-root PATH --approved-parent PATH`.

- [ ] Require `--output-root` and entry paths for prepare. Require both exact
  `--pair-root` and `--approved-parent` for verify/cleanup; do not invent a
  broad default cleanup target.
- [ ] Return deterministic compact JSON containing only schema, pass/fail,
  pair-root basename, counts, digests, and safe issue codes.
- [ ] Use a wrapper identical in structure to `scripts/codex-context-audit`,
  changing only the module to
  `voice_agent.governance.codex_context.snapshot_cli`.
- [ ] Make it executable.

### Step 6.6: Run the complete snapshot GREEN gate

- [ ] Run the same complete snapshot test file used for RED. Fix only snapshot
  tooling until all twelve tests pass. Do not weaken containment, expected-diff,
  binding, CLI, or cleanup assertions to obtain GREEN.

### Step 6.7: Verify and commit

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance/test_codex_context_snapshots.py -q
  git diff --check -- \
    scripts/codex-context-snapshot \
    src/voice_agent/governance/codex_context \
    tests/governance/test_codex_context_snapshots.py
  ```

- [ ] Run one local prepare/verify/cleanup cycle with exact pair root
  `/tmp/codex-context-shadow-plan-check`. First prove that path does not exist;
  if it exists, stop and choose a new explicit direct child of `/tmp` rather
  than deleting or overwriting it. Name every selected untracked card
  explicitly. Pass `/tmp` as the approved parent to verify and cleanup.
- [ ] Commit only Task 6 files:

  ```bash
  git add \
    scripts/codex-context-snapshot \
    src/voice_agent/governance/codex_context/model.py \
    src/voice_agent/governance/codex_context/snapshot.py \
    src/voice_agent/governance/codex_context/snapshot_cli.py \
    src/voice_agent/governance/codex_context/__init__.py \
    tests/governance/test_codex_context_snapshots.py
  git diff --cached --name-only
  git commit -m "feat: prepare paired codex context snapshots"
  ```

---

## Task 7: Define controlled A/B scenarios and redacted evidence handoff

**Files:**

- Create: `docs/governance/codex-context/ab-scenarios.md`
- Create:
  `docs/implementation/codex-context-slimming-shadow-acceptance.md`
- Modify: `tests/governance/test_codex_context_structure.py`
- Modify: `src/voice_agent/governance/codex_context/audit.py`

### Step 7.1: Add failing methodology and artifact tests

- [ ] Add tests named
  `test_ab_methodology_has_five_scenarios_and_fixed_repeat_policy`,
  `test_ab_acceptance_template_contains_only_redacted_metadata_fields`, and
  `test_artifact_audit_requires_ab_documents_and_snapshot_commands`, and
  `test_ab_scenarios_declare_expected_snapshot_difference_sets`.

- [ ] Assert five stable scenario IDs, two baseline and two candidate repeats,
  later-window tie-break policy, operational gate, non-claim language, and
  absence of fields for raw prompt, raw response, screenshot, or full request
  ID. Assert AB-02, AB-03, and AB-05 expect only `AGENTS.md` to differ; AB-04
  expects both `AGENTS.md` and `CODEX_TASK.md` to differ.
- [ ] Run the tests. Expected RED: documents do not exist.

### Step 7.2: Write the controlled scenario protocol

- [ ] Define these five scenarios in `ab-scenarios.md`:

  | ID | Legitimate bounded task | Baseline entry | Candidate entry |
  | --- | --- | --- | --- |
  | `AB-01` | outside-repo review of a tiny local Python function | same short task | same short task |
  | `AB-02` | summarize only repository README | short README task | same short README task |
  | `AB-03` | Quick-mode read-only audit of one small file and its test | short scoped task | same scoped task |
  | `AB-04` | execute or review one Task Card | equivalent master-plan excerpt | exact card |
  | `AB-05` | full Slice 3B.1 master-plan control | full master plan | full master plan |

- [ ] For every scenario specify:

  - same account, model, product surface, and approximate time window;
  - two baseline and two candidate repetitions;
  - one later comparable repeat when mixed;
  - legitimate/local/provider-free wording;
  - no external target, real credential, raw audio, raw trace, or real side
    effect;
  - outcome enum: `normal`, `content_unavailable`, `rerouted`, `delayed`,
    `other`;
  - timestamp/timezone, visible responding model when available, redacted
    identifier suffix, and uncontrolled-difference note.

- [ ] AB-01 is a neutral account/surface control. Run both labeled arms in
  equivalent empty directories outside the repository, with no repo instruction
  loaded. It diagnoses a global/account-level intervention and is not evidence
  that the candidate changed behavior.
- [ ] AB-02, AB-03, and AB-05 use paired snapshots whose entry bytes are
  identical; their manifest must expect only `AGENTS.md` to differ.
- [ ] AB-04 uses an equivalent baseline excerpt and exact candidate card; its
  manifest must expect both `AGENTS.md` and `CODEX_TASK.md` to differ.
- [ ] For AB-02 through AB-05 require the same bounded source manifest and a
  passing snapshot verification before either arm runs.
- [ ] Include exact prepare, verify, and cleanup command templates using
  `scripts/codex-context-snapshot`, including `--approved-parent` for verify and
  cleanup. Use `<PAIR_ROOT>`, `<APPROVED_PARENT>`, and `<ENTRY_PATH>` only as
  user-supplied command arguments in documentation; do not put them in code or
  tests as unresolved implementation values.

### Step 7.3: Write the acceptance template

- [ ] `codex-context-slimming-shadow-acceptance.md` contains:

  - status enum `not-run`, `inconclusive`, `passed`, `failed`;
  - baseline sizes/digests and audit version;
  - local-equivalence command results;
  - selected runtime-regression results;
  - one redacted A/B result table using the fields above;
  - operational gate decision;
  - explicit non-claims;
  - switch prerequisites;
  - rollback readiness;
  - reviewer verdict.

- [ ] Do not commit actual screenshots, prompt/response bodies, thread IDs,
  request IDs, logs, absolute snapshot paths, or local user input.
- [ ] Initialize the status to `not-run` and switch decision to `not-authorized`.
  This plan does not claim A/B completion.

### Step 7.4: Extend artifact audit and commit

- [ ] Make `audit_artifacts` require both documents, the five scenario IDs, safe
  result-field names, snapshot prepare/verify/cleanup references, and
  `not-authorized` switch state.
- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance/test_codex_context_structure.py -q
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/codex-context-audit all
  git diff --check -- \
    docs/governance/codex-context/ab-scenarios.md \
    docs/implementation/codex-context-slimming-shadow-acceptance.md \
    src/voice_agent/governance/codex_context/audit.py \
    tests/governance/test_codex_context_structure.py
  ```

- [ ] Commit only Task 7 files:

  ```bash
  git add \
    docs/governance/codex-context/ab-scenarios.md \
    docs/implementation/codex-context-slimming-shadow-acceptance.md \
    src/voice_agent/governance/codex_context/audit.py \
    tests/governance/test_codex_context_structure.py
  git diff --cached --name-only
  git commit -m "docs: define codex context shadow ab gate"
  ```

---

## Task 8: Run the shadow equivalence and unchanged-runtime acceptance gate

**Files:**

- Modify:
  `docs/implementation/codex-context-slimming-shadow-acceptance.md`
- Modify only if a governance defect is found:
  `docs/governance/codex-context/AGENTS.candidate.md`
- Modify only if a governance defect is found:
  `docs/governance/codex-context/invariant-map.md`
- Modify only if a governance defect is found:
  `docs/governance/codex-task-cards/slice3b1/*.md`
- Modify only if a governance defect is found:
  `src/voice_agent/governance/codex_context/*.py`
- Modify only if a governance defect is found:
  `tests/governance/test_codex_context_*.py`

### Step 8.1: Run all governance tests

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance -q
  ```

- [ ] Expected: all governance tests pass. Pre-existing tests in
  `tests/governance/` must remain included.
- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/codex-context-audit all
  ```

- [ ] Expected:

  - `passed` is `true`;
  - mapping checked count is `111`;
  - all five check reports pass;
  - `switch_ready` is `false`;
  - sole switch prerequisite is
    `ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED`.

### Step 8.2: Run selected unchanged-runtime regressions

- [ ] Run exactly:

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

- [ ] Compare the node set and result to the passing Task 1 baseline. Any new
  failure blocks shadow completion. Do not fix runtime code in this plan;
  record the exact failing test name and safe failure category locally and
  return ownership to the relevant Slice card.

### Step 8.3: Verify snapshot behavior against the real bounded source

- [ ] Prepare one pair under a newly created dedicated directory in `/tmp`,
  using:

  - baseline entry:
    `docs/superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md`;
  - candidate entry:
    `docs/governance/codex-task-cards/slice3b1/WP-S3B1-01.md`;
  - every required untracked source path named explicitly.

- [ ] Run `verify` and inspect the safe manifest summary.
- [ ] Confirm the only differences are root `AGENTS.md` and `CODEX_TASK.md`.
- [ ] Run `cleanup` against the exact pair root and confirm only that pair was
  removed.

### Step 8.4: Run the full repository suite

- [ ] Run:

  ```bash
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test -q
  ```

- [ ] Do not claim success from an earlier or partial run.
- [ ] If the suite fails, distinguish:

  - governance regression introduced by this plan;
  - active dirty-worktree failure outside this plan's ownership;
  - environment/test-infrastructure failure.

- [ ] Fix only governance regressions within this plan. Record other categories
  without changing unrelated runtime files and leave shadow completion blocked.
  Because Task 1 establishes only the selected regression baseline, do not call
  an unrelated full-suite failure “demonstrably pre-existing” without separate
  evidence.

### Step 8.5: Compare the worktree and update safe acceptance evidence

- [ ] Run:

  ```bash
  git status --short
  git diff --check
  git diff --name-only
  git diff --stat
  ```

- [ ] Compare current status to
  `diagnostics/codex-context/pre-shadow-status.txt`.
- [ ] Confirm all new differences belong to the files in Repository Impact and
  no pre-existing user path was reset, restored, or overwritten.
- [ ] Update the acceptance document with:

  - command names;
  - pass/fail and counts;
  - no raw output;
  - candidate/card sizes;
  - map count;
  - snapshot verification status;
  - full-suite status;
  - `switch_ready: false`;
  - `A/B status: not-run`;
  - `Atomic switch: not-authorized`.

### Step 8.6: Request independent review

- [ ] Use `superpowers:requesting-code-review` or an independent subagent to
  review:

  - 111-row zero-omission mapping;
  - truthful authority references and the ADR-015 prerequisite;
  - candidate semantic equivalence and 6 KiB budget;
  - Task Card write sets, DAG, and stop conditions;
  - deterministic/redacted audit output;
  - snapshot containment, symlink rejection, manifest, and cleanup safety;
  - absence of runtime behavior changes;
  - preservation of root `AGENTS.md`, accepted ADRs, and master plan.

- [ ] Address P0/P1 findings within governance scope and rerun affected focused
  tests plus Steps 8.1-8.5. Do not accept a review suggestion that weakens a
  legacy rule or expands runtime scope.

### Step 8.7: Final verification and commit

- [ ] Run fresh:

  ```bash
  git diff --cached --quiet
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/test tests/governance -q
  VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
    ./scripts/codex-context-audit all
  git diff --check
  ```

- [ ] The first command above must confirm an empty index. Commit only already
  tracked plan-owned files changed by Task 8. Use this exact allowlist with
  `-u`; do not replace it with a directory:

  ```bash
  git add -u -- \
    docs/governance/codex-context/AGENTS.candidate.md \
    docs/governance/codex-context/ab-scenarios.md \
    docs/governance/codex-context/invariant-map.md \
    docs/governance/codex-context/shadow-baseline.md \
    docs/governance/codex-task-cards/slice3b1/index.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-01-events-and-envelopes.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-02-capabilities-and-assembly.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-03-protocol-and-transport.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-04-scripted-wire.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-05-candidate-quarantine.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-06-session-lifecycle.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-07-route-evidence-and-orchestration.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-08-gate-and-release.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-09-replay.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-10-scenario-runner.md \
    docs/governance/codex-task-cards/slice3b1/TC-S3B1-11-cli-and-acceptance.md \
    docs/governance/codex-task-cards/slice3b1/WP-S3B1-01.md \
    docs/implementation/codex-context-slimming-shadow-acceptance.md \
    scripts/codex-context-audit \
    scripts/codex-context-snapshot \
    src/voice_agent/governance/__init__.py \
    src/voice_agent/governance/codex_context/__init__.py \
    src/voice_agent/governance/codex_context/audit.py \
    src/voice_agent/governance/codex_context/audit_cli.py \
    src/voice_agent/governance/codex_context/markdown.py \
    src/voice_agent/governance/codex_context/model.py \
    src/voice_agent/governance/codex_context/snapshot.py \
    src/voice_agent/governance/codex_context/snapshot_cli.py \
    tests/governance/codex_context_test_support.py \
    tests/governance/test_codex_context_cli.py \
    tests/governance/test_codex_context_mapping.py \
    tests/governance/test_codex_context_snapshots.py \
    tests/governance/test_codex_context_structure.py
  git diff --cached --name-only
  git commit -m "test: verify codex context shadow build"
  ```

- [ ] Before committing, inspect `git diff --cached --name-only` and require
  every entry to be in the exact allowlist above. If any other path appears,
  stop without committing; the commit must not absorb current Slice 3B.1 or
  pre-existing governance work.

## Shadow Completion Gate

This plan is complete only when all of the following are true:

1. Root `AGENTS.md`, accepted ADRs, and the historical master plan retain their
   pre-plan content.
2. The 111-rule inventory maps one-to-one with no missing or duplicate primary
   rows.
3. Candidate instruction is no larger than 6 KiB and remains independently
   understandable.
4. Eleven Task Cards and one Work Package satisfy their schemas and budgets.
5. Historical Task 12 is represented as package-level acceptance, not a twelfth
   implementation card.
6. Audit checks pass deterministically with redacted output.
7. Snapshot pair creation, exact-diff verification, and sentinel-gated cleanup
   pass.
8. The selected unchanged-runtime regressions pass both before mutation and at
   final verification with the same test-node set.
9. The full repository suite passes in a fresh final run.
10. A/B methodology and redacted acceptance template exist.
11. Operational A/B remains unclaimed until actually run.
12. `switch_ready` remains false until ADR-015 is explicitly revised in a
    separate Atomic Switch plan.
13. No raw prompt, response, screenshot, task ID, request ID, credential, user
    input, audio, trace, replay cache, or provider payload is committed.

## Post-Plan Handoff

After the Shadow Completion Gate:

1. Use the paired snapshots and `ab-scenarios.md` to run the controlled
   operational A/B.
2. Record only redacted aggregate evidence in the acceptance document.
3. If the operational gate is inconclusive or fails, keep the shadow state and
   do not change active instructions.
4. If it passes, write and review a separate Atomic Switch implementation plan
   covering the ADR-015 clarification, root instruction replacement, historical
   marker, rollback proof, and final full-suite verification.

This plan never authorizes the Atomic Switch by itself.
