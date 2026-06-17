# MVP-5 Codex Goal Plan

This handoff splits MVP-5 into five large Codex goals that can be executed one
at a time in fresh threads. These are intentionally larger than implementation
slices: each goal should produce a meaningful branch checkpoint and may contain
several TDD cycles.

## Branch Bootstrap

Use this in every fresh Codex thread before setting the next MVP-5 goal:

```bash
cd /Users/a123/voice-agent
git fetch origin
git switch codex/mvp5-real-wav-live-e2e-docs || \
  git switch -c codex/mvp5-real-wav-live-e2e-docs --track origin/codex/mvp5-real-wav-live-e2e-docs
git pull --ff-only
```

Remote branch:

- `origin/codex/mvp5-real-wav-live-e2e-docs`

Planning docs already on this branch:

- `docs/implementation/mvp5-backlog.md`
- `docs/specs/mvp5-acceptance-scenarios.md`
- `docs/implementation/mvp5-goal-plan.md`

Runtime implementation must start by checking whether MVP-4 implementation
artifacts have landed on the branch. At planning time, `origin/main` contained
the MVP-4 backlog docs but not the prior MVP-4 runtime commits referenced by
the MVP-4 Goal 5 closeout request. If they are still absent, do not silently
rebuild MVP-4 inside MVP-5; first rebase, merge, or recreate the prerequisite
MVP-4 artifacts as an explicit prerequisite step.

## Global Boundaries For Every Goal

- Do not add canonical events without ADR.
- Do not modify accepted ADRs unless a stop condition is hit.
- Do not call providers outside adapters.
- Do not call real providers in default tests.
- Do not read real env secret values in provider-free tests or replay.
- Do not commit raw audio, raw transcript, provider request/response body,
  prompt dump, diagnostics, traces, local replay cache, local wav paths, or
  secrets.
- Replay must never rerun providers.
- Live provider execution must be explicit opt-in only.
- Local wav input must be explicit opt-in only.
- Smoke and live summaries must be metadata-only and path-redacted.
- No realtime microphone, full-duplex/AEC/barge-in expansion, real TTS/voice
  out, real Slow LLM loop, production privacy claim, or real external side
  effects.
- Python tests must run through `./scripts/test`.
- Finish each goal with `git diff --check`, a focused commit, and a push.

## Goal 1: MVP-5 Safety Foundation

**Objective**

Establish the safety and prerequisite foundation for all MVP-5 runtime work:
MVP-4 prerequisite checks, MVP-5 fixture/acceptance scaffolding, local wav input
gate, and live provider approval gate.

**Why this is one big goal**

The local wav gate and live approval gate are not useful separately: they are
the paired safety boundary that prevents MVP-5 from accidentally becoming
"read arbitrary local audio and call real providers." Keeping them together
makes later goals simpler and safer.

**Scope**

- Confirm branch, HEAD, `git status`, untracked files, and ignored local
  artifact roots.
- Confirm `.gitignore` covers `diagnostics/`, `traces/`, `replays/local/`,
  `audio/raw/`, `.env`, `.env.*`, and `outputs/`.
- Confirm required MVP-4 runtime/test/fixture artifacts exist, or fail with a
  clear prerequisite report before runtime work.
- Create or complete `tests/acceptance/test_mvp5_acceptance_scenarios.py` as a
  high-level provider-free skeleton.
- Create `tests/fixtures/replay/mvp5/README.md`.
- Create `tests/fixtures/replay/mvp5/manifest.index.json`.
- Create `src/voice_agent/runtime/mvp5_live_audio_input.py`.
- Create `src/voice_agent/runtime/mvp5_live_approval.py`.
- Create `tests/runtime/test_mvp5_live_audio_input.py`.
- Create `tests/runtime/test_mvp5_live_approval.py`.
- Add `docs/implementation/mvp5-live-eval-approval-template.md`.
- Enforce explicit local wav opt-in.
- Enforce explicit live provider approval.
- Validate credential env var names without printing or persisting secret
  values.

**Required default commands**

```bash
./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q
./scripts/test tests/runtime/test_mvp5_live_audio_input.py -q
./scripts/test tests/runtime/test_mvp5_live_approval.py -q
git diff --check
```

**Done when**

- MVP-4 prerequisites are either present or reported as a clear blocker.
- Local wav loading fails closed without explicit opt-in.
- Local wav metadata redacts absolute path and file name.
- Raw wav bytes stay in memory/local-only handles and never enter journal,
  fixtures, stdout, committed docs, or replay.
- Missing approval, missing credential env var, unsafe refs, or over-budget
  request plans fail before provider calls.
- MVP-5 fixture policy is GitHub-safe and provider-free by default.

**Suggested commit**

```text
feat: add MVP5 safety foundation
```

## Goal 2: Real ASR + Real Thinker Live Evidence Spine

**Objective**

Build the live evidence spine from one explicitly approved local wav to real
ASR and real Thinker adapter evidence for the same committed audio turn, while
keeping default tests fake-transport/provider-free.

**Why this is one big goal**

The user-facing MVP-5 question is not "can ASR run?" or "can Thinker run?" in
isolation. It is whether both real model boundaries can consume the same wav
turn and produce safe, joinable evidence for Router.

**Scope**

- Create `src/voice_agent/runtime/mvp5_live_voice_evidence.py`.
- Create `tests/runtime/test_mvp5_live_voice_evidence.py`.
- Reuse existing ASR adapter contracts and transport boundaries.
- Reuse existing LALM Thinker audio-native adapter contracts and transport
  boundaries.
- Commit an audio turn before adapter execution.
- Emit safe `ASR_TRANSCRIPT_OUTPUT_EMITTED` and
  `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` events tied to the same
  `turn_id`, `utterance_id`, and `audio_span_id`.
- Preserve explicit `output_mode=real|fallback|degraded`.
- Keep optional approved live execution outside default CI.

**Required default commands**

```bash
./scripts/test tests/runtime/test_mvp5_live_voice_evidence.py -q
./scripts/test tests/replay/test_asr_transcript_replay.py -q
./scripts/test tests/adapters/test_lalm_thinker_runtime_adapter.py -q
git diff --check
```

**Done when**

- Fake transports prove the event chain and safety boundaries.
- Approved live path is adapter-owned and opt-in.
- ASR and Thinker evidence bind to the same committed audio turn.
- Missing optional model capabilities degrade explicitly.
- Journal, fixture, and summary outputs contain safe refs only: no raw wav
  bytes, raw transcript, provider body, provider schema, prompt dump, credential
  value, or local wav path.

**Suggested commit**

```text
feat: add MVP5 live evidence spine
```

## Goal 3: Router Live Route Results

**Objective**

Pass MVP-5 ASR/Thinker evidence refs through Router and produce truthful
metadata-only results for the three existing route families:
direct answer/`FAST_ONLY`, `SPAWN_SLOW_TASK`, and `PATCH_ACTIVE_SLOW_TASK`.

**Why this is one big goal**

Router and route-result semantics are one acceptance surface. Splitting direct
answer, SlowTask spawn, and UserPatch into separate goals would encourage
slightly different summary/provenance behavior across the three paths. This
goal keeps the route contract coherent.

**Scope**

- Create `src/voice_agent/runtime/mvp5_live_router_runner.py`.
- Create `tests/runtime/test_mvp5_live_router_runner.py`.
- Create or extend `tests/runtime/test_mvp5_live_route_results.py`.
- Create `tests/replay/test_mvp5_live_route_replay.py`.
- Route live/fake ASR and Thinker evidence refs without copying raw payloads.
- Support expected-route assertions that report mismatch without forcing Router.
- Implement direct answer metadata summary with `response_text_ref` or
  `result_summary_ref`.
- Implement SlowTask spawn summary using existing SlowTask mock/control-plane
  events.
- Implement UserPatch summary using existing UserPatch evidence ownership.
- Preserve ASR authoritative evidence and Thinker hypothesis provenance.

**Required default commands**

```bash
./scripts/test tests/runtime/test_mvp5_live_router_runner.py -q
./scripts/test tests/runtime/test_mvp5_live_route_results.py -q
./scripts/test tests/replay/test_mvp5_live_route_replay.py -q
./scripts/test tests/runtime/test_mvp4_router_outcome_handling.py -q
./scripts/test tests/router/test_mvp4_voice_router_fusion.py -q
git diff --check
```

**Done when**

- Router references same-turn ASR and Thinker event ids.
- A single wav run reports the actual Router decision.
- Expected-route mismatch fails/report cleanly without route forcing.
- `FAST_ONLY` result has safe response/result summary refs,
  `real_tts_used=false`, and `voice_output=none`.
- `SPAWN_SLOW_TASK` records ASR/Thinker refs in `SLOWTASK_CREATED` and
  `EVIDENCE_REVIEWED`.
- `PATCH_ACTIVE_SLOW_TASK` records `task_id`, `plan_version`,
  `observed_plan_version`, and `task_event_seq` in `USER_PATCH_RECEIVED`.
- Patch receipt alone does not emit `USER_PATCH_INTERPRETED` or
  `PLAN_VERSION_ADVANCED`.
- No new response canonical event, real Slow LLM loop, real tool execution,
  real TTS, or playback is introduced.

**Suggested commit**

```text
feat: add MVP5 router route results
```

## Goal 4: Manual Smoke Command + Three-Route Wav Pack

**Objective**

Add the manual MVP-5 smoke command that can run either a single local wav or a
three-case local wav pack and output path-redacted metadata-only JSON.

**Why this is one big goal**

This is the human-facing MVP-5 verification surface. It should be built after
the route runner is coherent, then tested as a complete CLI experience rather
than as scattered helper functions.

**Scope**

- Create `scripts/mvp5-real-voice-e2e`.
- Create `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`.
- Create `tests/runtime/test_mvp5_real_voice_e2e_smoke.py`.
- Single-run mode accepts one local wav and reports one actual Router outcome.
- Three-route pack mode accepts a local-only manifest with one wav case per
  expected route: `FAST_ONLY`, `SPAWN_SLOW_TASK`, and
  `PATCH_ACTIVE_SLOW_TASK`.
- Pack mode must fail/report mismatches without forcing Router decisions.
- Stdout must be JSON metadata only.
- Local pack and local wavs must remain outside GitHub under ignored roots.

**Required default commands**

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

- Provider-free tests verify JSON shape, redaction, failures, and route mismatch
  handling.
- Live mode is opt-in and fails closed before unsafe execution.
- Stdout never includes local wav absolute path, file name, raw audio, raw
  transcript, provider body, prompt dump, provider headers, credential values,
  or secrets.
- The command can be used manually for one wav or three route-specific wavs.

**Suggested commit**

```text
feat: add MVP5 real voice smoke command
```

## Goal 5: Acceptance Runner + Closeout

**Objective**

Close MVP-5 with high-level scenario coverage, manifest coverage, replay/fixture
safety checks, closeout docs, and final verification.

**Why this is one big goal**

Closeout is not another runtime feature. It is the point where MVP-5 becomes
auditable: every scenario is mapped, every safety claim is checked, and remaining
non-goals are stated plainly.

**Scope**

- Complete `tests/acceptance/test_mvp5_acceptance_scenarios.py`.
- Update `tests/fixtures/replay/mvp5/manifest.index.json`.
- Create `docs/implementation/mvp5-closeout.md`.
- Include evidence commands run.
- Include optional approved live smoke evidence only if a human provides it.
- Document ADR stop conditions encountered, or state none encountered.

**Required default commands**

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
- Manifest coverage is metadata-only and GitHub-safe.
- Replay and acceptance do not rerun providers.
- Fixture/export/stdout safety gates reject unsafe raw artifacts and secrets.
- Closeout distinguishes default provider-free tests, fake transports, optional
  approved live provider evidence, replay safety, and remaining non-goals.
- MVP-5 does not claim realtime mic, full-duplex/AEC/barge-in, real TTS/voice
  out, real Slow LLM loop, production privacy, or real external side effects.

**Suggested commit**

```text
test: add MVP5 acceptance closeout
```

## Fresh Thread Start Template

Use one fresh Codex thread per goal. Paste this into the new thread, then append
the exact target goal section from this document.

```text
请在 /Users/a123/voice-agent 中工作。

先执行：
1. git fetch origin
2. git switch codex/mvp5-real-wav-live-e2e-docs 或从
   origin/codex/mvp5-real-wav-live-e2e-docs 创建同名本地分支
3. git pull --ff-only
4. 检查当前分支、HEAD、git status、untracked 文件
5. 阅读：
   - AGENTS.md
   - stage_b_adr_register.md
   - docs/implementation/mvp5-backlog.md
   - docs/specs/mvp5-acceptance-scenarios.md
   - docs/implementation/mvp5-goal-plan.md

硬边界：
- 不新增 canonical event，除非先走 ADR。
- 不修改 accepted ADR。
- 不在 adapter 外直接调用 provider。
- 默认测试不调用真实 provider。
- provider-free tests / replay 不读取真实 env secret。
- 不提交 raw audio、raw transcript、provider body、prompt dump、diagnostics、
  trace、local replay cache、local wav path、secret。
- Replay 不 rerun providers。
- Smoke/live summary 只能输出 safe metadata / refs / summary。
- 不接 realtime mic。
- 不实现 full-duplex/AEC/barge-in 扩展。
- 不实现 real TTS / voice out。
- 不实现 real Slow LLM loop。
- 不实现真实外部副作用 tool execution。

TDD 要求：
- 先写 failing tests。
- 用 ./scripts/test 运行目标测试确认失败。
- 再实现最小代码。
- 再用 ./scripts/test 运行相关测试。
- Python tests 必须通过 ./scripts/test，不要直接 pytest。
- 最后运行 git diff --check。

完成后：
- 总结改了哪些文件。
- 总结跑了哪些 ./scripts/test 和 smoke commands。
- 说明是否触发 ADR stop condition。
- commit 并 push 当前分支。
```

After each goal:

- run the listed tests through `./scripts/test`;
- run `git diff --check`;
- commit with the suggested message or a close equivalent;
- push the branch so the next thread starts from the updated remote state;
- start the next fresh thread from `git pull --ff-only`.
