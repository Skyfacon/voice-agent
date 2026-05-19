# Model Spike Count Reconciliation 2026-05-18

## 0. Status

- Status: `research_only_count_reconciliation`
- Date: 2026-05-18
- Lane: model spike research
- Scope: reconcile 2026-05-11/12 dry-run summary smoke counts with full synthetic counts recorded in ledger, phase summaries, profile hardening addenda, and spike-local harness reports.
- Non-goal: no runtime adapter implementation, no provider wiring, no real mic/playback, no mainline contract/spec/ADR edits.

This document is a count and evidence-inventory reconciliation note. It does not upgrade any dry-run or synthetic count into real provider capability or MVP3 integration approval.

## 1. 当前分支 / git 状态 / observed main snapshot

Observed local commands:

```text
git status --short --branch
## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]
 M docs/research/model-spike-integration-ledger.md
 ?? docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md
 ?? docs/research/model-spike-mainline-sync-2026-05-17.md
 ?? docs/research/model-spike-mainline-sync-2026-05-18.md
 ?? docs/research/model-spike-mvp3-readiness-review-2026-05-18.md
 ?? docs/research/model-spike-phase-summary-2026-05-11.md
 ?? docs/research/model-spike-phase-summary-2026-05-12.md
 ?? docs/research/profiles/
 ?? docs/research/spikes/...
 ?? tools/
```

Observed main:

```text
git rev-parse --short main
ced2077
```

Observed `main` top commits:

```text
ced2077 Merge pull request #22 from Skyfacon/mvp2/slice3-tool-ui-state-patch
0d2870f fix: harden MVP2 UI patch replay validation
6f6e549 feat: add MVP2 tool UI state replay
f325483 Merge pull request #21 from Skyfacon/mvp2/slice2-demo-tool-executor-skeleton
a52585b fix: harden MVP2 tool executor policy gates
2c7a567 feat: add MVP2 demo tool executor skeleton
5741ae3 Merge pull request #20 from Skyfacon/mvp2/slice1-tool-execution-state
de71948 feat: add MVP2 tool execution replay state
ac1b43f Merge pull request #19 from Skyfacon/mvp2/slice0-replay-safety
```

Interpretation:

- This thread observed `main@ced2077`, which is newer than the previous 2026-05-18 sync addendum's `main@f325483`.
- The new delta after `f325483` is MVP2 Slice 3 Tool UI State Patch / UI patch replay validation.
- Count reconciliation is not a replacement for a full `main@ced2077` contract sync. It records the current observed baseline so later Tool Executor event mapping can include UI patch replay.

## 2. 本次 reconciliation 的范围和非目标

In scope:

- Reconcile `case_set=smoke` summaries against `case_set=full_synthetic` counts.
- Identify whether count mismatches are naming/scope differences or actual evidence gaps.
- Preserve historical `main@61e6afc` labels for 2026-05-11/12 evidence.
- State which future documents should reference `main@ced2077` or newer.
- Keep all conclusions research-only.

Out of scope:

- No provider calls.
- No real mic or playback-device run.
- No raw audio, generated audio, raw trace, replay cache, secret, or real user input.
- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No new runtime behavior, adapter implementation, or mainline replay fixture.

## 3. Count source inventory

| Source | Count signal | Count type | Notes |
| --- | --- | --- | --- |
| `docs/research/model-spike-mvp3-readiness-review-2026-05-18.md` | Flags the known mismatch: ASR/TTS/Slow LLM dry-run summaries show 5, while ledger/profile summaries show full synthetic ASR 23, TTS 20, Slow LLM 21, Thinker 22. | reconciliation prompt source | It used `main@f325483`; this thread observed `main@ced2077`. |
| `docs/research/model-spike-integration-ledger.md` | ASR 23, TTS 20, Slow LLM 21, Thinker/Composer 22. | full_synthetic count | Counts are recorded as fresh full-synthetic dry-run counts with validation pass, provider calls false, runtime imports false. |
| `docs/research/model-spike-phase-summary-2026-05-12.md` | Same four full-synthetic counts: 23 / 20 / 21 / 22. | full_synthetic count | Confirms validation pass and no provider calls/raw artifacts. |
| `docs/research/profiles/*hardening-addendum-2026-05-12.md` | Per-profile fresh local full-synthetic checks: Slow LLM 21, TTS 20, ASR 23, Thinker 22, Composer boundary 22 shared. | full_synthetic count | Profile addenda cite generated temp JSONL and validation zero errors. |
| `docs/research/spikes/asr-qwen-asr-streaming-eval-dry-run-2026-05-12.md` | 5 observations, 5 unique cases. | smoke / dry-run summary count | Matches `tools/model_spikes/asr_streaming_eval/cases.py` smoke set. |
| `docs/research/spikes/tts-cosyvoice-playback-eval-dry-run-2026-05-12.md` | 5 observations, 5 unique cases. | smoke / dry-run summary count | Matches `tools/model_spikes/tts_playback_eval/cases.py` smoke set. |
| `docs/research/spikes/slow-llm-retry-eval-dry-run-2026-05-12.md` | 5 observations, 5 unique cases. | smoke / dry-run summary count | Matches `tools/model_spikes/slow_llm_retry_eval/cases.py` smoke set. |
| `docs/research/spikes/thinker-composer-boundary-eval-dry-run-2026-05-12.md` | 22 observations, 22 unique cases. | full_synthetic dry-run summary count | Despite the generic title, this summary is the full matrix, not a 5-case smoke summary. |
| `tools/model_spikes/*/cases.py` | Defines `SMOKE_CASES` and `FULL_SYNTHETIC_CASES`. | case-set source of truth for spike-local tools | ASR smoke 5/full 23; TTS smoke 5/full 20; Slow LLM smoke 5/full 21; Thinker/Composer smoke 5/full 22. |
| `docs/research/spikes/duplex-vad-webrtcvad-harness-run-2026-05-11.md` | 11 synthetic cases, 91 observations, 4/4 self-check pass, 0 skipped dependency-backed checks in temp venv. | separate local harness count | Not a smoke/full_synthetic model-eval case set; do not mix with ASR/TTS/Slow/Thinker matrices. |

## 4. 各领域计数对照表

| Domain | Smoke / dry-run summary count | Full_synthetic count | Skipped / degraded / unsupported / unknown count signal | Source | Reconciliation |
| --- | ---: | ---: | --- | --- | --- |
| Slow LLM | 5 | 21 | Smoke summary: 1 degraded client timeout, 1 synthetic stale case; full label distribution not summarized in docs. | dry-run summary, profile addendum, ledger, `slow_llm_retry_eval/cases.py` | Mismatch is expected: 5-case smoke subset vs 21-case full matrix. Not a blocker if cited correctly. |
| ASR | 5 | 23 | Smoke summary: 2 degraded labels (`client_timeout`, `non_speech_risk`); full label distribution not summarized in docs. | dry-run summary, profile addendum, ledger, `asr_streaming_eval/cases.py` | Mismatch is expected: 5-case smoke subset vs 23-case full matrix. Not a blocker if cited correctly. |
| TTS | 5 | 20 | Smoke summary: 1 degraded client close, 2 synthetic playback/truncate shape cases; full label distribution not summarized in docs. | dry-run summary, profile addendum, ledger, `tts_playback_eval/cases.py` | Mismatch is expected: 5-case smoke subset vs 20-case full matrix. Not a blocker if cited correctly. |
| Thinker | no separate committed 5-case smoke summary found; tool smoke set defines 5 | 22 shared Thinker/Composer matrix | Full summary includes 2 unknown labels (`semantic_close`, `assistant_directedness`) and 1 degraded client timeout label; unsupported authority is described in profiles but not counted. | Thinker/Composer dry-run summary, profile addendum, ledger, `thinker_composer_eval/cases.py` | No count mismatch in committed summary: it already reports 22 full cases. The 5-case smoke set exists in tooling only. |
| Thinker-as-Composer | no separate committed 5-case smoke summary found; tool smoke set includes Composer cases | 22 shared matrix; 7 `composer_*` boundary subcases in the full case list | Full summary includes coverage failure, must-say, risk warning, confirmation, stale evidence, demo status, and immutable-facts cases; no separate Composer-only full_synthetic suite count is reported. | Composer hardening addendum, Thinker/Composer dry-run summary, `thinker_composer_eval/cases.py` | Do not double-count 22 for Thinker plus 22 for Composer as 44. It is one shared 22-case matrix reused by both profile addenda. |
| Duplex/VAD | not applicable | not applicable | WebRTC harness: 11 synthetic cases, 91 observations, 4/4 self-check pass, no skipped dependency-backed check in the temp venv. Unsupported: semantic close, directedness, TTS truncate confirmation at VAD layer. | WebRTC VAD harness run report | Separate harness count, not comparable to smoke/full_synthetic model eval counts. |
| webSearch/RAG | no standalone smoke count | unknown / not reported as standalone suite | web evidence appears inside Slow LLM and Thinker/Composer cases; no dedicated RAG count. | Slow LLM full case list, Thinker/Composer full case list, readiness review | No standalone count exists. Treat webSearch/RAG as boundary evidence only, not readiness evidence. |

## 5. Count vocabulary

| Term | Meaning in this lane | Count handling |
| --- | --- | --- |
| `smoke count` | Small tool case set used for fast dry-run sanity. | ASR/TTS/Slow LLM committed summaries each report 5. Thinker/Composer tooling defines a 5-case smoke set, but the committed summary reports full 22. |
| `dry-run summary count` | Count printed in a committed dry-run summary markdown. | Can be smoke or full_synthetic depending on the case set used. The title alone is insufficient. |
| `full_synthetic count` | Complete metadata-only synthetic matrix for a harness. | ASR 23, TTS 20, Slow LLM 21, Thinker/Composer 22. |
| `skipped` | Cases or dependency-backed checks intentionally not run. | Only the VAD harness report explicitly states no dependency-backed self-check was skipped. Other full_synthetic docs do not publish skipped counts. |
| `degraded` | Observations that represent incomplete or unsafe behavior, such as client timeout or non-speech risk. | Smoke summaries publish some degraded labels; full label distributions are not consistently committed. Do not infer missing distributions. |
| `unsupported` | Behavior outside a candidate role or owner boundary. | Profile addenda list unsupported capabilities qualitatively; they usually do not provide unsupported counts. |
| `unknown / not reported` | No reliable count found in committed docs or directly read case-set definitions. | Keep as `unknown` or `not reported`; do not fill from memory or assumption. |

## 6. Integration ledger consistency check

The integration ledger records:

| Harness | Ledger full_synthetic count | Confirming source | Consistency |
| --- | ---: | --- | --- |
| ASR streaming eval | 23 | ASR profile hardening addendum and `asr_streaming_eval/cases.py` full list | consistent |
| TTS playback eval | 20 | TTS profile hardening addendum and `tts_playback_eval/cases.py` full list | consistent |
| Slow LLM retry eval | 21 | Slow LLM profile hardening addendum and `slow_llm_retry_eval/cases.py` full list | consistent |
| Thinker / Composer eval | 22 | Thinker profile addendum, Composer boundary addendum, committed dry-run summary, and `thinker_composer_eval/cases.py` full list | consistent, but shared across Thinker and Composer |

No ledger full_synthetic count mismatch was found.

The visible mismatch is documentation granularity:

- ASR/TTS/Slow LLM committed dry-run summaries report `case_set=smoke` counts of 5.
- Profile addenda and phase/ledger summaries report `case_set=full_synthetic` counts.
- Thinker/Composer committed dry-run summary already reports 22 full cases, not 5.

## 7. 与 MVP3 readiness Go / No-Go 的关系

The readiness review already marked count reconciliation as a required cleanup before Tool Executor and Composer mapping. This document resolves the count wording problem, but it does not change MVP3 integration readiness.

Still Go for planning:

- Use full_synthetic counts as evidence-inventory coverage, not runtime proof.
- Use smoke counts only when explicitly citing smoke summaries.
- Keep historical 2026-05-11/12 evidence as historical `main@61e6afc`.
- Proceed to event mapping matrices after this count baseline is clear.

Still No-Go:

- No runtime adapter implementation.
- No real provider integration.
- No real mic/playback/device tests.
- No model-owned tool execution, UI patching, confirmation, or Composer self-attested playback approval.
- No raw artifacts or protected-dir edits.

## 8. Count mismatch classification

| Mismatch / ambiguity | Classification | Blocker? | Action |
| --- | --- | --- | --- |
| ASR 5 vs 23 | Scope difference: smoke subset vs full matrix. | No, unless a later doc cites 5 as full coverage. | Cite as `ASR smoke=5`, `ASR full_synthetic=23`. |
| TTS 5 vs 20 | Scope difference: smoke subset vs full matrix. | No, unless a later doc cites 5 as full coverage. | Cite as `TTS smoke=5`, `TTS full_synthetic=20`. |
| Slow LLM 5 vs 21 | Scope difference: smoke subset vs full matrix. | No, unless a later doc cites 5 as full coverage. | Cite as `Slow LLM smoke=5`, `Slow LLM full_synthetic=21`. |
| Thinker/Composer dry-run title vs 22 count | Naming ambiguity: dry-run summary is full_synthetic, not smoke. | No. | Cite the case set or count explicitly; avoid saying all dry-run summaries are smoke. |
| Thinker 22 and Composer 22 | Shared-suite ambiguity. | Potential blocker for evidence inventory if summed as 44. | Treat as one shared 22-case matrix, with Composer-specific subcases called out separately. |
| Duplex/VAD 91 vs model eval full_synthetic counts | Different harness type. | No. | Keep WebRTC VAD harness count separate from ASR/TTS/Slow/Thinker full_synthetic matrices. |
| webSearch/RAG standalone count missing | Real gap: no dedicated standalone suite count. | Not a blocker for count reconciliation; blocker for any RAG readiness claim. | Keep `unknown / not reported` until a dedicated synthetic/mock webSearch/RAG eval exists. |

## 9. Evidence still historical `main@61e6afc`

The following remain historical evidence and should not be silently upgraded:

- 2026-05-11 real/provider metadata run reports:
  - Slow LLM Qwen JSON run.
  - DeepSeek deferred comparison report.
  - TTS DashScope/Bailian run.
  - ASR DashScope/Bailian run.
  - Thinker Qwen-Omni run.
  - Duplex/VAD local and WebRTC VAD reports.
- 2026-05-12 dry-run summaries and profile hardening addenda unless explicitly re-mapped:
  - ASR streaming eval.
  - TTS playback eval.
  - Slow LLM retry eval.
  - Thinker/Composer boundary eval.
  - Candidate hardening addenda.

These artifacts are still useful. Their correct label is historical evidence with `historical_contract_snapshot=main@61e6afc`.

## 10. Conclusions to upgrade to current observed main

Future research docs should use `contract_snapshot=main@ced2077` or newer, while preserving `historical_contract_snapshot=main@61e6afc` for reused 2026-05-11/12 evidence.

Upgrade requirements:

- Tool-like model output must map to MVP2 Tool Executor events and policy gates.
- UI mutation evidence must account for the newly observed Tool UI State Patch / UI patch replay baseline after `f325483`.
- Slow LLM stale/current-plan cases must be rechecked against current `task_id`, `plan_version`, `task_event_seq`, `tool_call_id`, idempotency, and stale adoption rules.
- Composer/checker cases must map to `SPOKEN_PLAN_EMITTED`, coverage/truthfulness check events, and playback approval refs.
- webSearch/RAG remains `UNTRUSTED_WEB_EVIDENCE`; no standalone readiness count exists.

Count reconciliation itself is complete enough to unblock the next mapping thread, but it does not replace a dedicated `main@ced2077` sync addendum if that level of contract review is needed.

## 11. Inputs for MVP2 Tool Executor event mapping matrix

Use this count baseline:

| Input | Use in next matrix |
| --- | --- |
| Slow LLM smoke 5 / full 21 | Map full cases, especially tool proposal, stale/adoption, web evidence, malformed JSON, provider cancel, retry, context degradation. |
| ASR smoke 5 / full 23 | Treat ASR as evidence only; tool-relevant transcript must still pass Interaction, Router, SlowTask review, and Tool Executor authorization. |
| TTS smoke 5 / full 20 | Keep playback/truncate cases separate from provider synthesis; no UI/tool authority. |
| Thinker/Composer shared full 22 | Split matrix rows by role: Thinker SemanticFrame evidence vs Composer SpokenPlan/check boundary. Do not double-count as 44. |
| Duplex/VAD 91 | Use only for Duplex/Interaction/Talker ownership references; not a Tool Executor case source. |
| webSearch/RAG unknown standalone | Include as Tool Executor boundary requirement, but do not claim dedicated count coverage. |

The next matrix should cite `main@ced2077` or newer and must include `TOOL_UI_STATE_PATCHED` / UI patch replay implications.

## 12. Go / No-Go checklist

| Decision | Status | Reason |
| --- | --- | --- |
| Use full_synthetic counts for evidence inventory | Go | Counts are consistent across ledger, phase summary, profile addenda, and tool case definitions. |
| Use smoke summaries for quick orientation | Go with label | Only if explicitly labeled `smoke=5`. |
| Treat ASR/TTS/Slow 5-count summaries as full coverage | No-Go | They are smoke summaries. |
| Sum Thinker 22 plus Composer 22 as 44 | No-Go | It is a shared 22-case matrix. |
| Treat Duplex/VAD 91 as full_synthetic model eval | No-Go | It is a separate WebRTC VAD local harness matrix. |
| Claim standalone webSearch/RAG eval coverage | No-Go | Count is unknown/not reported. |
| Proceed to MVP2 Tool Executor event mapping matrix | Go | Count baseline is now clear enough for mapping. |
| Proceed to runtime adapter integration | No-Go | No integration approval, no current-main replay fixture proof, no provider/runtime safety gate. |

## 13. Human approval gates

Human approval is required before:

- Editing any protected directory: `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- Running real provider calls or live provider evals.
- Running real microphone, playback, or device tests.
- Capturing or storing raw audio, generated audio, raw trace, local replay cache, secrets, or real user input.
- Creating committed replay/eval fixtures outside the approved synthetic/redacted/minimal boundary.
- Promoting any count into MVP3 readiness without current-main event mapping and replay/eval proof.
- Treating webSearch/RAG as a real external fetch instead of synthetic/mock untrusted evidence.

## 14. Summary

The main reconciliation result is simple:

- ASR: `smoke=5`, `full_synthetic=23`.
- TTS: `smoke=5`, `full_synthetic=20`.
- Slow LLM: `smoke=5`, `full_synthetic=21`.
- Thinker/Composer: committed summary is already `full_synthetic=22`; tooling also defines `smoke=5`.
- Duplex/VAD: separate local WebRTC harness, `cases=11`, `observations=91`, self-check `4/4`.
- webSearch/RAG: no standalone count; only embedded boundary cases.

No count mismatch blocks the next research-only mapping thread. The only blocker would be using a smoke count as a full_synthetic count, double-counting the shared Thinker/Composer suite, or claiming standalone webSearch/RAG coverage that does not exist.
