# MVP-5 Codex Goal Plan

This handoff splits MVP-5 into large Codex goals that can be executed one at a
time in fresh threads. It assumes the thread starts from the remote feature
branch created for MVP-5 planning.

## Branch Bootstrap

Use this in a fresh Codex thread before setting the first runtime goal:

```bash
cd /Users/a123/voice-agent
git fetch origin
git switch codex/mvp5-real-wav-live-e2e-docs || \
  git switch -c codex/mvp5-real-wav-live-e2e-docs --track origin/codex/mvp5-real-wav-live-e2e-docs
git pull --ff-only
```

Current branch head at planning time:

- branch: `codex/mvp5-real-wav-live-e2e-docs`
- base: `origin/main`
- planning commit: `4b3a29e docs: add MVP5 live wav E2E backlog`

Runtime implementation must start by checking whether MVP-4 implementation
artifacts have landed on the branch. At planning time, `origin/main` contains
the MVP-4 backlog docs but not the prior MVP-4 runtime commits referenced by
the Goal 5 closeout request. If they are still absent, do not silently rebuild
MVP-4 inside a later goal; first rebase, merge, or recreate the prerequisite
MVP-4 artifacts as an explicit prerequisite step.

## Goal 1: MVP-5 Prerequisite And Safety Baseline

**Objective**

Prepare the branch for runtime work by verifying MVP-4 prerequisites, adding
MVP-5 fixture/safety scaffolding, and creating the first acceptance runner
skeleton that fails closed when prerequisites are missing.

**Scope**

- Confirm branch, HEAD, status, untracked files, and ignored local artifact
  roots.
- Confirm required MVP-4 modules/tests/fixtures are present.
- Add `tests/acceptance/test_mvp5_acceptance_scenarios.py`.
- Add `tests/fixtures/replay/mvp5/README.md`.
- Add `tests/fixtures/replay/mvp5/manifest.index.json`.
- Provider-free only; no real wav, provider, env secret, or network call.

**Primary commands**

```bash
./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q
git diff --check
```

**Done when**

- The branch either contains MVP-4 prerequisites or reports a clear blocking
  prerequisite failure.
- The MVP-5 scenario ids from `docs/specs/mvp5-acceptance-scenarios.md` are
  represented in the acceptance runner/manifest.
- Fixture safety policy is explicit and GitHub-safe.

**Suggested commit**

```text
test: add MVP5 acceptance safety baseline
```

## Goal 2: Local Wav Input Gate And Live Approval Guard

**Objective**

Implement the local wav input and live approval gates without calling any real
provider in default tests.

**Scope**

- Create `src/voice_agent/runtime/mvp5_live_audio_input.py`.
- Create `src/voice_agent/runtime/mvp5_live_approval.py`.
- Create `tests/runtime/test_mvp5_live_audio_input.py`.
- Create `tests/runtime/test_mvp5_live_approval.py`.
- Add `docs/implementation/mvp5-live-eval-approval-template.md`.
- Enforce explicit `--allow-local-wav` and `--live-provider` style gates.
- Validate credential env var presence by name only; never print or persist the
  secret value.

**Primary commands**

```bash
./scripts/test tests/runtime/test_mvp5_live_audio_input.py -q
./scripts/test tests/runtime/test_mvp5_live_approval.py -q
git diff --check
```

**Done when**

- Local wav mode fails closed unless explicitly allowed.
- Metadata redacts absolute path and file name.
- Raw bytes stay behind an in-memory/local-only handle and never enter journal,
  fixture, stdout, or committed docs.
- Missing approval, missing credential, unsafe refs, or over-budget requests
  fail before provider calls.

**Suggested commit**

```text
feat: add MVP5 live input approval gates
```

## Goal 3: Real ASR + Real Thinker Evidence Runner

**Objective**

Run ASR and Thinker over the same committed audio turn through existing adapter
boundaries, with fake-transport tests by default and optional approved live
execution only.

**Scope**

- Create `src/voice_agent/runtime/mvp5_live_voice_evidence.py`.
- Create `tests/runtime/test_mvp5_live_voice_evidence.py`.
- Reuse existing ASR and LALM Thinker adapter contracts.
- Emit safe `ASR_TRANSCRIPT_OUTPUT_EMITTED` and
  `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` events tied to the same
  `TURN_INGRESS_COMMITTED` audio turn.
- Preserve explicit `output_mode=real|fallback|degraded`.

**Primary commands**

```bash
./scripts/test tests/runtime/test_mvp5_live_voice_evidence.py -q
./scripts/test tests/replay/test_asr_transcript_replay.py -q
./scripts/test tests/adapters/test_lalm_thinker_runtime_adapter.py -q
git diff --check
```

**Done when**

- Fake transports prove the event chain and safety boundaries.
- Approved live path is adapter-owned and opt-in.
- Journal/summary never include raw wav bytes, raw transcript, provider body,
  provider schema, prompt dump, credential, or local wav path.

**Suggested commit**

```text
feat: add MVP5 live voice evidence runner
```

## Goal 4: Router Live Fusion And Direct Answer Summary

**Objective**

Pass MVP-5 live ASR/Thinker evidence refs through Router and produce a
metadata-only result for the actual single-run Router outcome, including the
direct answer / `FAST_ONLY` path.

**Scope**

- Create `src/voice_agent/runtime/mvp5_live_router_runner.py`.
- Create `tests/runtime/test_mvp5_live_router_runner.py`.
- Create or extend `tests/runtime/test_mvp5_live_route_results.py`.
- Support expected-route assertions that report mismatch without forcing Router.
- Implement direct answer summary as safe ref metadata only.

**Primary commands**

```bash
./scripts/test tests/runtime/test_mvp5_live_router_runner.py -q
./scripts/test tests/runtime/test_mvp5_live_route_results.py -q
./scripts/test tests/router/test_mvp4_voice_router_fusion.py -q
git diff --check
```

**Done when**

- Router references same-turn ASR and Thinker event ids.
- `FAST_ONLY` result has `response_text_ref` or `result_summary_ref`.
- Summary states `real_tts_used=false` and `voice_output=none`.
- No new response canonical event is added.

**Suggested commit**

```text
feat: add MVP5 live router fusion
```

## Goal 5: SlowTask Spawn And UserPatch Route Results

**Objective**

Complete the `SPAWN_SLOW_TASK` and `PATCH_ACTIVE_SLOW_TASK` route summaries
using existing SlowTask/UserPatch control-plane ownership and provenance rules.

**Scope**

- Extend `src/voice_agent/runtime/mvp5_live_router_runner.py`.
- Extend `tests/runtime/test_mvp5_live_route_results.py`.
- Create `tests/replay/test_mvp5_live_route_replay.py`.
- Preserve ASR authoritative evidence and Thinker hypothesis refs.
- Keep patch receipt separate from interpretation and plan advancement.

**Primary commands**

```bash
./scripts/test tests/runtime/test_mvp5_live_route_results.py -q
./scripts/test tests/replay/test_mvp5_live_route_replay.py -q
./scripts/test tests/runtime/test_mvp4_router_outcome_handling.py -q
git diff --check
```

**Done when**

- Spawn route records ASR/Thinker refs in `SLOWTASK_CREATED` and
  `EVIDENCE_REVIEWED`.
- Patch route records `task_id`, `plan_version`, `observed_plan_version`, and
  `task_event_seq` in `USER_PATCH_RECEIVED`.
- `USER_PATCH_INTERPRETED` and `PLAN_VERSION_ADVANCED` are not emitted by patch
  receipt alone.
- No real Slow LLM loop or external tool execution is introduced.

**Suggested commit**

```text
feat: add MVP5 slowtask patch route results
```

## Goal 6: Three-Route Smoke Command

**Objective**

Add the manual MVP-5 smoke command that can run either a single local wav or a
three-case local wav pack and output safe metadata-only JSON.

**Scope**

- Create `scripts/mvp5-real-voice-e2e`.
- Create `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`.
- Create `tests/runtime/test_mvp5_real_voice_e2e_smoke.py`.
- Single-run mode reports one actual Router outcome.
- Three-route pack mode verifies `FAST_ONLY`, `SPAWN_SLOW_TASK`, and
  `PATCH_ACTIVE_SLOW_TASK` without route forcing.

**Primary commands**

```bash
./scripts/test tests/runtime/test_mvp5_real_voice_e2e_smoke.py -q
scripts/mvp5-real-voice-e2e --help
git diff --check
```

**Optional approved live commands**

```bash
scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav \
  --local-wav <human-provided-local-wav> \
  --expected-route auto \
  --approval-packet <approved-local-approval-packet>

scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav-pack <human-provided-local-pack-json> \
  --approval-packet <approved-local-approval-packet>
```

**Done when**

- Provider-free tests verify JSON shape and redaction.
- Live mode is opt-in and fails closed before unsafe execution.
- Stdout never includes local wav path, file name, raw audio, raw transcript,
  provider body, prompt dump, provider headers, or secrets.

**Suggested commit**

```text
feat: add MVP5 real voice smoke command
```

## Goal 7: MVP-5 Acceptance Runner And Closeout

**Objective**

Close MVP-5 with a high-level acceptance runner, manifest coverage, fixture
safety checks, closeout docs, and final verification.

**Scope**

- Complete `tests/acceptance/test_mvp5_acceptance_scenarios.py`.
- Update `tests/fixtures/replay/mvp5/manifest.index.json`.
- Create `docs/implementation/mvp5-closeout.md`.
- Include evidence commands run and optional approved live smoke evidence if a
  human provides it.

**Primary commands**

```bash
./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q
./scripts/test tests/runtime/test_mvp5_live_audio_input.py -q
./scripts/test tests/runtime/test_mvp5_live_approval.py -q
./scripts/test tests/runtime/test_mvp5_live_voice_evidence.py -q
./scripts/test tests/runtime/test_mvp5_live_router_runner.py -q
./scripts/test tests/runtime/test_mvp5_live_route_results.py -q
./scripts/test tests/runtime/test_mvp5_real_voice_e2e_smoke.py -q
./scripts/test tests/replay/test_mvp5_live_route_replay.py -q
git diff --check
./scripts/test
```

**Done when**

- Every required scenario id in
  `docs/specs/mvp5-acceptance-scenarios.md` is covered.
- Closeout distinguishes default provider-free tests, fake transports, optional
  approved live provider evidence, replay safety, and non-goals.
- MVP-5 does not claim realtime mic, full-duplex/AEC/barge-in, real TTS/voice
  out, real Slow LLM loop, production privacy, or real external side effects.

**Suggested commit**

```text
test: add MVP5 acceptance closeout
```

## Recommended Thread Strategy

Use one fresh Codex thread per goal. Start each thread with the branch bootstrap,
then paste only the target goal plus the hard boundaries from
`docs/implementation/mvp5-backlog.md` and the relevant scenarios from
`docs/specs/mvp5-acceptance-scenarios.md`.

After each goal:

- run the listed tests through `./scripts/test`;
- run `git diff --check`;
- commit with the suggested message or a close equivalent;
- push the branch so the next thread starts from the updated remote state.
