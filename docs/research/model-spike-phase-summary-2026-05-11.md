# Model Spike Phase Summary

## Status

phase_summary_for_profile_hardening_planning

This document summarizes the current model spike evidence and recommends the next work sequence. It is research coordination only. It does not authorize runtime integration, real business adapters, ADR/spec changes, or MVP scope expansion.

## Date

2026-05-11

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Scope boundary: model spike evidence must stay adapter-shaped, metadata-only, replay-safe, and outside the main runtime until a later approved integration branch.

## One-Line Conclusion

候选基本成型，边界还要硬化。

## Executive Summary

The model spike lane has moved from candidate research to observed capability evidence for the primary DashScope / Bailian path:

- Slow LLM structured planning has the strongest evidence today. DashScope Qwen produced validated JSON, handled missing/conflicting evidence, and converged through bounded schema repair.
- TTS is viable for basic Talker output. DashScope CosyVoice produced streaming audio chunks and timestamp metadata, but truncate remains playback-owned.
- ASR is promising for transcript evidence and timestamp metadata. DashScope Qwen-ASR produced non-empty transcripts, streaming output, and filetrans timestamp-like structures, but true realtime microphone streaming and silence robustness remain open.
- Thinker is promising for SemanticFrame evidence. DashScope Qwen-Omni produced validated structured frames from text and local synthetic audio, but full-stream latency is too slow for Duplex hot path and semantic/directedness authority remains unsupported.
- Duplex/VAD should stay local-first. WebRTC VAD is worth turning into a spike-local harness, but it has clear false-positive and playback-echo risks without playback reference.
- DeepSeek is still a comparison candidate only. The run was not executed because the local credential was missing.

The common pattern is healthy: candidates can be shaped into adapter evidence, but cancellation, truncate, semantic close, assistant-directedness, live audio behavior, and replay boundaries must remain explicit degraded/unknown/unsupported fields.

## Source Documents Reviewed

Coordination and selection:

- `docs/research/model-selection.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-spike-execution-plan.md`
- `docs/research/model-spike-integration-ledger.md`

Run reports and harness plan:

- `docs/research/spikes/slow-llm-dashscope-qwen-json-run-2026-05-11.md`
- `docs/research/spikes/slow-llm-deepseek-json-run-2026-05-11.md`
- `docs/research/spikes/tts-dashscope-bailian-run-2026-05-11.md`
- `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md`
- `docs/research/spikes/thinker-dashscope-qwen-omni-run-2026-05-11.md`
- `docs/research/spikes/duplex-vad-local-run-2026-05-11.md`
- `docs/research/spikes/duplex-vad-webrtcvad-local-run-2026-05-11.md`
- `docs/research/spikes/duplex-vad-webrtcvad-harness-plan-2026-05-11.md`
- May 9 capability spike reports for ASR, TTS, Thinker, Slow LLM, and Duplex.

Contract references:

- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`

## Candidate Readiness Matrix

| domain | current primary candidate | current state | strongest evidence | main degraded / unknown fields | recommendation |
| --- | --- | --- | --- | --- | --- |
| Slow LLM | DashScope / Bailian `qwen3.6-plus` | observed real for structured JSON | strict schema pass, insufficient-evidence behavior, conflict preservation, tool proposal shape, bounded repair | provider-confirmed cancellation, streaming latency, future model alias pinning | enter adapter profile draft first |
| Slow LLM comparison | DeepSeek current text API | not executed | official API shape only | live JSON validation, latency, retry, cancellation all unknown | defer until local credential is present |
| TTS / Talker | DashScope / Bailian `cosyvoice-v3-flash` | observed real for synthesis and streaming output | first audio around 0.5-0.7s, binary chunks, word timestamp events | provider-confirmed cancellation, playback stop offset, model-layer truncate unsupported | enter profile draft after Slow LLM; keep truncate playback-owned |
| ASR | DashScope / Bailian `qwen3-asr-flash` | observed real/degraded for transcript evidence | final transcript-like output, response streaming, filetrans timestamp-like metadata | true realtime mic streaming input, silence false positives, confidence quality, exact timestamp granularity, cancellation | enter profile draft after a small ASR eval harness plan |
| Thinker | DashScope / Bailian `qwen3.5-omni-plus` | observed real/degraded for SemanticFrame evidence | validated JSON frames, audio Data URL input, evidence separation, web evidence marked untrusted, tool proposal deltas | realtime audio streaming input, audio timestamps, semantic close, assistant-directedness, Composer enforcement, full response latency | profile draft later; keep out of hot path |
| Duplex / VAD | local WebRTC VAD | observed real for synthetic frame decisions; degraded for echo/live behavior | 10/20/30 ms frame matrix, mode 0/2/3, speech-start latency, playback residual simulation | real device echo, real AEC, natural speech quality, noise/tone false positives, live scheduling | build spike-local harness next before profile hardening |
| Duplex baseline | local energy gate | executed degraded baseline | event-shape and offset semantics | not a real VAD dependency | retain only as baseline evidence |

## Capability Label Summary

| capability area | real evidence today | degraded evidence today | unsupported / not owner | unknown |
| --- | --- | --- | --- | --- |
| Structured SlowTask JSON | DashScope Qwen strict schema and repair | streaming not exercised | audio, TTS, semantic close for Slow LLM role | provider-confirmed cancellation |
| Tool-like output | DashScope Qwen schema-level proposal; Qwen-Omni provider-native proposal deltas | execution normalization still required | execution and authorization are Tool Executor-owned | provider behavior under larger tool schemas |
| TTS basic speech | CosyVoice binary audio chunks | client close is only degraded cancellation | model-layer `TTS_TRUNCATED` | playback-controller stop accuracy |
| TTS timestamps | CosyVoice word timestamp events | playback offset remains Talker-owned | semantic acknowledgement | alignment quality across longer outputs |
| ASR transcript | Qwen-ASR final transcript-like output | silence produced non-empty output risk | turn ingress and final semantic truth | quality across eval set |
| ASR timestamps | filetrans timestamp-like and word-like output | exact granularity not normalized | playback state | realtime streaming timestamp behavior |
| Thinker SemanticFrame | Qwen-Omni validated JSON frames | full-stream latency too high for hot path | turn ingress, SlowTask final facts, confirmation, tool authorization | schema stability over larger eval set |
| Thinker audio input | Qwen-Omni accepted synthetic WAV Data URL | true realtime input unknown | audio output for Thinker method | audio timestamp availability |
| Duplex speech activity | WebRTC VAD synthetic PCM decisions | live mic and natural speech unmeasured | semantic close, assistant-directedness, truncate confirmation | real-device echo robustness |
| Playback reference / echo | idealized residual blocks playback-only candidate | real AEC not validated | VAD cannot own `TTS_TRUNCATED` | room/device echo behavior |

## Domain Notes

### Slow LLM

DashScope Qwen is the most profile-ready candidate. It has observed real structured JSON behavior, local schema validation, explicit insufficient-evidence handling, conflict preservation, and bounded repair. It also demonstrated the right shape for tool proposal evidence without execution.

The remaining hardening work is not model quality in the abstract; it is adapter discipline:

- normalize validated output into task-bound metadata;
- keep invalid JSON out of SlowTask state;
- record retry/validation failures as adapter evidence;
- keep late output stale-friendly;
- pin the exact model alias again when profile hardening starts.

DeepSeek should remain a comparison lane, not a blocker.

### TTS / Talker

DashScope CosyVoice is credible for basic TTS. It produced streaming binary audio chunks and timestamp metadata with useful first-audio latency for short synthetic prompts.

The critical boundary is still ADR-003:

- model request close or timeout is not truncate confirmation;
- word timestamps are alignment evidence, not playback delivery state;
- `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, and `TTS_TRUNCATED` must be produced by Talker/playback.

TTS can enter profile drafting after Slow LLM, but target barge-in validation needs playback-controller proof, not only provider proof.

### ASR

DashScope Qwen-ASR is promising for a future ASR adapter. It produced final transcript-like evidence, streaming response deltas, and timestamp-like filetrans metadata.

The main concerns are quality and input mode:

- true realtime microphone streaming input was not exercised;
- silence/non-speech produced a short non-empty transcript-like output;
- exact timestamp granularity must be normalized;
- transcript must remain evidence only, not the semantic truth source.

ASR should get a small eval harness plan before final profile hardening.

### Thinker

DashScope Qwen-Omni is promising for post-commit Thinker evidence and possible Composer-role experiments. It produced valid `SemanticFrame` JSON, preserved uncertainty, separated evidence sources, handled synthetic web evidence as untrusted evidence, accepted local synthetic audio input, and produced provider-native tool proposal deltas.

It must not enter the Duplex hot path:

- full structured responses ranged from seconds to many seconds;
- semantic close and assistant-directedness were not directly validated;
- Composer safety checks are preliminary and cannot replace coverage/truthfulness checks;
- SlowTask facts, confirmation, conflict resolution, and tool authorization remain owned elsewhere.

### Duplex / VAD

The WebRTC VAD path is the right next local harness target. It is light, local, repeatable, and maps well to `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, and `BARGE_IN_CANDIDATE` metadata.

It also showed exactly why the harness is needed:

- clean synthetic speech starts fast enough algorithmically;
- tone and white noise false positives are real risks;
- playback-only raw mic activity looks like speech without reference handling;
- idealized residual subtraction is not real AEC;
- VAD cannot provide semantic close, assistant-directedness, or truncate confirmation.

## Cross-Cutting Boundary Decisions

These decisions should guide every next phase:

- Keep the layered adapter stack. Do not merge ASR, Thinker, TTS, Duplex, and SlowTask into one omni owner.
- Keep WebRTC VAD local and evidence-only. It emits speech and barge-in candidate metadata; it does not decide turn semantics.
- Keep ASR as text projection evidence. It cannot bypass Interaction Controller or resolve task facts alone.
- Keep Thinker as SemanticFrame evidence and Composer realization. It cannot own SlowTask final facts, confirmation, tool execution, or playback.
- Keep Slow LLM as structured planning evidence behind validation. It cannot execute tools directly or advance stale results without owner policy.
- Keep TTS truncate playback-owned. Provider-side request close, timeout, or cancellation cannot become `TTS_TRUNCATED`.
- Keep deterministic replay metadata-only. Replay should consume recorded metadata or synthetic fixtures and should not rerun real models or WebRTC VAD by default.

## Gate Assessment

| gate | status | evidence |
| --- | --- | --- |
| Gate 0: research-only readiness | pass | Work stayed in `research/model-spikes`; reports are under `docs/research`; no runtime/spec/ADR changes are required. |
| Gate 1: spike-local experiment readiness | mostly pass | Synthetic inputs, redaction rules, metadata-only reports, provider credential handling, and run report structure exist. WebRTC VAD now has a concrete harness proposal. |
| Gate 2: adapter profile hardening | partial | Slow LLM and TTS are closest. ASR and Thinker need small eval/harness tightening. Duplex/VAD needs spike-local harness code first. DeepSeek is deferred. |
| Gate 3: MVP-3 integration consideration | not ready | Profile drafts, replay/eval fixtures, and playback-controller truncate proof are not yet in place. |

## Recommended Next Arrangement

### Step 1: Create this phase summary

This document becomes the entry point for the current evidence set and replaces ad-hoc navigation across many run reports.

### Step 2: Build the first spike-local harness

Create the approved WebRTC VAD harness under:

```text
tools/model_spikes/duplex_vad/
```

It should produce metadata-only JSONL, validate an observation schema, keep generated audio under `/private/tmp`, and retain the 10/20/30 ms by mode 0/2/3 matrix. It must not import or call main runtime modules.

### Step 3: Draft adapter capability profiles in order

Recommended order:

1. Slow LLM: DashScope Qwen structured JSON profile.
2. TTS: DashScope CosyVoice synthesis and streaming output profile.
3. ASR: DashScope Qwen-ASR transcript/timestamp profile after a small eval harness plan.
4. Thinker: DashScope Qwen-Omni SemanticFrame profile after schema/eval tightening.
5. Duplex/VAD: WebRTC VAD profile only after harness repeatability and playback-reference plan are stronger.

### Step 4: Convert selected observations into replay/eval-safe fixtures

Do not use raw provider payload or raw audio. Convert only minimal synthetic metadata needed to test:

- Slow LLM schema validation and stale-friendly timeout behavior.
- TTS playback span compatibility and truncate ownership separation.
- ASR transcript evidence and timestamp availability.
- Thinker evidence separation and Composer safety boundaries.
- Duplex barge-in candidate to Interaction Controller truncate-request causal shape.

### Step 5: Re-evaluate deferred comparison candidates

Run DeepSeek Slow LLM comparison when the local credential exists. Later comparisons can include self-hosted ASR/TTS/Thinker candidates, but only after the primary DashScope path has profile drafts.

## Near-Term Work Queue

| priority | work item | output |
| --- | --- | --- |
| P0 | WebRTC VAD spike-local harness code | `tools/model_spikes/duplex_vad/` with metadata JSONL and schema |
| P0 | Slow LLM Qwen profile draft | research profile or capability observation mapped to ADR-011 fields |
| P1 | TTS CosyVoice profile draft | playback-owned truncate notes plus streaming/timestamp capability profile |
| P1 | ASR eval harness plan | synthetic cases for silence, clipped speech, mixed language, timestamps |
| P1 | Thinker schema/eval tightening | SemanticFrame schema checks and Composer boundary eval cases |
| P2 | DeepSeek comparison rerun | same Slow LLM synthetic JSON cases as Qwen |

## Final Recommendation

Proceed to spike-local harness and profile hardening, but not runtime integration.

The practical path is:

1. build WebRTC VAD harness for repeatability;
2. draft Slow LLM and TTS capability profiles from the strongest observed evidence;
3. tighten ASR and Thinker with small eval plans;
4. only then discuss MVP-3 integration branches.

This keeps model choice evidence moving while preserving the repository's core architecture rule: models provide adapter-shaped evidence, not hidden control flow.
