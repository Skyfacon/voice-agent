# Codex Context Shadow A/B Scenarios

## Purpose and authority

This protocol compares the active repository context with the shadow candidate
context without changing the working repository. It is a small operational
check, not statistical proof and not authority to perform the Atomic Switch.
Accepted ADRs, the active root `AGENTS.md`, and the current execution entry
remain authoritative throughout the runs.

## Fixed run envelope

Every scenario uses a legitimate, bounded, local, provider-free voice-agent
task. It has no external target, no real credential, no raw audio, no raw
trace, and no real side effect. The two arms use the same account, same model,
same product surface, and same approximate time window. They also use the same
task wording except for the explicitly declared execution-entry difference in
AB-04.

For AB-02 through AB-05, both arms come from one prepared pair with the same
bounded source manifest. Snapshot verification must pass before either arm is
opened. A failed verification invalidates both arms; it is not an A/B outcome.

The allowed outcome enum is:

- `normal`
- `content_unavailable`
- `rerouted`
- `delayed`
- `other`

Use the fixed first-window order `B1`, `C1`, `B2`, `C2`, where `B` is the
baseline arm and `C` is the candidate arm. `B1`, `B2`, `C1`, and `C2` must all
use the fixed run envelope above.

If either arm is internally inconsistent, the arms overlap in a way that
prevents a conclusion, or an uncontrolled difference may explain the result,
classify the scenario as `inconclusive`. Only then, in one later comparable
window, run the paired repeats `B3` and `C3`. Do not run `B3` or `C3` to replace
an inconvenient but internally consistent result. A later pair that remains
mixed stays `inconclusive`.

## Allowed result record

The committed result handoff may use only this redacted table schema:

| scenario_id | arm | repeat_id | outcome | timestamp_timezone | visible_model | redacted_identifier_suffix | uncontrolled_difference_note |
| --- | --- | --- | --- | --- | --- | --- | --- |

`redacted_identifier_suffix` is an explicitly shortened suffix, never a
complete task, thread, or request identifier. Notes are bounded descriptions
of environmental differences, not interaction bodies. Account identifiers,
interaction bodies, captured UI images, complete identifiers, local logs, and
local snapshot locations remain outside committed artifacts.

## AB-01

**Neutral outside-repository account/surface control**

- Legitimate bounded task: review one tiny local Python function for a simple
  correctness issue.
- Baseline entry: the same short task.
- Candidate entry: the same short task.
- Workspace: two equivalent empty directories outside the repository, with no
  repository instruction or repository content loaded.
- Snapshot pair: none. The `B` and `C` labels are scheduling labels only.

AB-01 diagnoses an account-, model-, or product-surface-level intervention. It
does not test the candidate instruction and is never evidence that the
candidate changed behavior.

## AB-02

**README-only repository control**

- Legitimate bounded task: summarize only the repository `README.md`, without
  changing files.
- Baseline entry and candidate entry: the same short README-only task.
- Entry bytes: identical
- Expected snapshot differences: `AGENTS.md`

The manifest and passing verification must show that `AGENTS.md` is the only
content difference between arms.

## AB-03

**Quick-mode localized audit**

- Legitimate bounded task: perform a read-only audit of one named small source
  file and its one named test.
- Baseline entry and candidate entry: the same short, file-scoped task.
- Entry bytes: identical
- Expected snapshot differences: `AGENTS.md`

The task must stay inside one existing component boundary. Discovering an
architecture-boundary question stops the run rather than expanding its scope.

## AB-04

**One Task Card comparison**

- Legitimate bounded task: review or execute one named Task Card and only its
  declared local verification.
- Baseline entry: a bounded master-plan excerpt that is semantically equivalent
  to the selected card.
- Candidate entry: the exact selected Task Card.
- Entry bytes: different
- Expected snapshot differences: `AGENTS.md`, `CODEX_TASK.md`

AB-04 is a bundled comparison: both the root instruction and execution entry
differ. Its result cannot separately attribute an effect to one of those two
surfaces.

## AB-05

**Full Slice 3B.1 master-plan diagnostic control**

- Legitimate bounded task: use the complete Slice 3B.1 master plan to identify
  and handle the same named provider-free local step in both arms.
- Baseline entry and candidate entry: the same complete master plan.
- Entry bytes: identical
- Expected snapshot differences: `AGENTS.md`

AB-05 measures the effect of the root instruction while retaining the large
historical execution context. It is a diagnostic control, not the preferred
day-to-day execution mode.

## Snapshot command templates

Use a new, non-existing direct child of an approved temporary or ignored
diagnostics parent for each pair. For AB-02, AB-03, and AB-05, pass the same
repository-relative entry path to both entry arguments. For AB-04, pass the
baseline excerpt path to the first entry argument and the exact Task Card path
to the second.

Prepare a pair whose entry files are already tracked:

```bash
scripts/codex-context-snapshot prepare \
  --repo-root . \
  --output-root "<PAIR_ROOT>" \
  --baseline-entry "<ENTRY_PATH>" \
  --candidate-entry "<ENTRY_PATH>"
```

When an approved entry is intentionally uncommitted, explicitly select it.
Repeat the final option once for each distinct uncommitted entry:

```bash
scripts/codex-context-snapshot prepare \
  --repo-root . \
  --output-root "<PAIR_ROOT>" \
  --baseline-entry "<ENTRY_PATH>" \
  --candidate-entry "<ENTRY_PATH>" \
  --include-uncommitted "<ENTRY_PATH>"
```

Verify the prepared pair before either arm runs:

```bash
scripts/codex-context-snapshot verify \
  --pair-root "<PAIR_ROOT>" \
  --approved-parent "<APPROVED_PARENT>"
```

After recording only the allowed redacted metadata, verify once more and then
clean up the exact pair:

```bash
scripts/codex-context-snapshot verify \
  --pair-root "<PAIR_ROOT>" \
  --approved-parent "<APPROVED_PARENT>"
scripts/codex-context-snapshot cleanup \
  --pair-root "<PAIR_ROOT>" \
  --approved-parent "<APPROVED_PARENT>"
```

Cleanup is narrowly scoped to a verified pair. Its safety argument assumes
that no other process running as the same OS identity concurrently mutates the
tool's randomly named private snapshot container. This is an operational
assumption, not a claim of cross-process isolation.

## Classification

A scenario is `passed` only when its declared gate is satisfied with no
unexplained uncontrolled difference. It is `failed` when a stable result
violates that gate. It is `inconclusive` for mixed or non-comparable evidence,
including a non-reproducing baseline where the intended comparison cannot be
made. Before any operational run, it is `not-run`.

The overall candidate gate also requires all local equivalence and unchanged
runtime checks. Scenario results alone never authorize the Atomic Switch.
