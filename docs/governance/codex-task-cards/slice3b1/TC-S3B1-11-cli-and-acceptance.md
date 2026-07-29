# TC-S3B1-11 CLI and Acceptance

## Task ID and title

`TC-S3B1-11` — Presentation-only CLI, minimal canonical fixtures, safety gates,
and acceptance evidence. Status: `not-started`. Historical source: Slice 3B.1
master-plan Task 11.

## Goal

Expose the stable provider-free result without duplicating runtime logic, and
commit only minimal synthetic canonical replay evidence that proves
determinism, artifact safety, and explicit Slice 3B.1 non-claims.

## Allowed write files

- Create: `src/voice_agent/runtime/slice3b1/cli.py`
- Create: `scripts/qwen-slice3b1`
- Create: `tests/runtime/test_slice3b1_cli.py`
- Create: `tests/replay/test_slice3b1_fixture_safety.py`
- Modify: `tests/replay/test_fixture_safety.py`
- Create: `tests/fixtures/replay/mvp6/slice3b1/README.md`
- Create: `tests/fixtures/replay/mvp6/slice3b1/manifest.index.json`
- Create: `tests/fixtures/replay/mvp6/slice3b1/000-provider-free-happy-path.fixture.json`
- Create: `tests/fixtures/replay/mvp6/slice3b1/008-replay-safety.fixture.json`
- Create: `docs/implementation/qwen-slice3b1-provider-free-acceptance.md`

## Required read-only dependencies

- [TC-S3B1-09](TC-S3B1-09-replay.md)
- [TC-S3B1-10](TC-S3B1-10-scenario-runner.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`

## Exact ADR sections

- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md` — `Decision`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md` — `Validation Method`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md` — `Decision`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md` — `Validation Method`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md` — `ADR-018 Repository Review Addendum`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Validation Method`

## Input and output contracts

CLI B accepts `--list-scenarios` or one `--scenario <id>` with optional
`--json`, then renders the same `Slice3B1RunV1` from Card 10. It contains no
protocol, Router, Gate, or replay logic. Unknown scenarios fail safely with
exit code 2 and no traceback or raw payload.

The two fixtures contain canonical events only, never provider wire events,
PCM, prompt material, credentials, real user input, or Fake reruns. Safety
allowlists remain narrow and validate opaque release refs without relaxing the
general forbidden-token rule.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-JOURNAL-01`
- `INV-PRIVACY-01`
- `INV-PRIVACY-02`
- `INV-PRIVACY-03`
- `INV-FOREGROUND-02`
- `INV-VERIFY-02`

## Non-goals

- No real Qwen WebSocket, credential read, native PCM authorization/playback,
  Page C, Slow-to-Fast/Composer runtime, or Slice 3B.2 implementation.
- No CLI enable flag for native PCM, provider URL, API key, live mode, Talker,
  or Page C.
- No raw audio/trace, provider body, prompt, secret, unredacted input, local
  reference, or provider-wire recording in committed fixtures.

## Implementation outline

1. Verify Cards 09–10 and add RED tests for the presentation-only CLI.
2. Implement the wrapper and renderer around the existing result/catalog only.
3. Add exactly two minimal `GITHUB_ALLOWED`, synthetic, canonical fixtures and
   an index that distinguishes runtime parameter coverage from committed replay.
4. Extend shared fixture safety only for exact validated release authority
   keys; test malformed/local refs and zero provider/Fake/network calls.
5. Write acceptance evidence using the required eight-section outline and fill
   results only after commands actually run.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/runtime/test_slice3b1_cli.py tests/replay/test_slice3b1_fixture_safety.py tests/replay/test_fixture_safety.py -q
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/qwen-slice3b1 --scenario valid_turn_response_starts_before_asr_final --json
git diff --check -- src/voice_agent/runtime/slice3b1/cli.py scripts/qwen-slice3b1 tests/runtime/test_slice3b1_cli.py tests/replay/test_slice3b1_fixture_safety.py tests/replay/test_fixture_safety.py tests/fixtures/replay/mvp6/slice3b1/README.md tests/fixtures/replay/mvp6/slice3b1/manifest.index.json tests/fixtures/replay/mvp6/slice3b1/000-provider-free-happy-path.fixture.json tests/fixtures/replay/mvp6/slice3b1/008-replay-safety.fixture.json docs/implementation/qwen-slice3b1-provider-free-acceptance.md
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

Scenario listing exactly matches the catalog; JSON uses the stable safe schema;
unknown input exits safely; both fixtures pass repository safety and replay
twice to identical digests without external calls; only the declared fixture
files exist; acceptance evidence records actual commands and every required
non-claim; default output remains mock and Gate-failed.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop on duplicated runtime logic,
schema/catalog drift, unsafe fixture/ref, replay rerunning the Fake/provider,
forbidden CLI option, or unsupported qualification claim. Do not stage, commit,
push, enable native PCM, or begin Slice 3B.2/Page C.

## Evidence and handoff

Record CLI snapshots/exit codes, exact fixture inventory and manifests,
deterministic digest pairs, recursive safety scan results, zero-call probes,
non-claim coverage, safe changed paths, and command results. Hand the complete
Cards 01–11 evidence set to `WP-S3B1-01` package acceptance; file existence
alone is never completion proof.
