# Model Spike Phase Summary

## Status

phase_summary_after_spike_local_eval_harnesses

This document refreshes the 2026-05-11 phase summary after the spike-local metadata-only eval harnesses and proof plans were added. It is research coordination only. It does not authorize runtime integration, real business adapters, ADR/spec changes, provider calls, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Scope boundary: model spike evidence stays adapter-shaped, metadata-only, replay-safe, and outside the main runtime until a later approved integration branch.

## Scope

In scope:

- Summarize current ASR, TTS, Slow LLM, Thinker / Composer, and Duplex / VAD spike evidence.
- Distinguish `observed_real`, `observed_degraded`, `synthetic_eval`, `unknown`, and `unsupported`.
- Record which spike-local dry-run harnesses now exist and validate.
- Update MVP-3 readiness gates without widening MVP scope.
- Recommend the next model-spike steps.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No real provider call.
- No main runtime wiring.
- No business adapter implementation.
- No generated audio, provider bodies, raw trace, local replay cache, real user input, or secret-bearing value.

## Source Evidence

Primary run reports and profiles:

- `docs/research/spikes/slow-llm-dashscope-qwen-json-run-2026-05-11.md`
- `docs/research/spikes/slow-llm-deepseek-json-run-2026-05-11.md`
- `docs/research/profiles/slow-llm-qwen-capability-profile-draft-2026-05-11.md`
- `docs/research/profiles/slow-llm-qwen-profile-hardening-addendum-2026-05-12.md`
- `docs/research/spikes/tts-dashscope-bailian-run-2026-05-11.md`
- `docs/research/profiles/tts-cosyvoice-capability-profile-draft-2026-05-12.md`
- `docs/research/profiles/tts-cosyvoice-profile-hardening-addendum-2026-05-12.md`
- `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md`
- `docs/research/profiles/asr-qwen-asr-capability-profile-draft-2026-05-12.md`
- `docs/research/profiles/asr-qwen-asr-profile-hardening-addendum-2026-05-12.md`
- `docs/research/spikes/thinker-dashscope-qwen-omni-run-2026-05-11.md`
- `docs/research/profiles/thinker-qwen-omni-capability-profile-draft-2026-05-12.md`
- `docs/research/profiles/thinker-qwen-omni-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/thinker-as-composer-boundary-hardening-addendum-2026-05-12.md`
- `docs/research/spikes/duplex-vad-local-run-2026-05-11.md`
- `docs/research/spikes/duplex-vad-webrtcvad-local-run-2026-05-11.md`

Proof plans and dry-run eval summaries added by the current model-spike lane:

- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/spikes/tts-cosyvoice-playback-truncate-proof-plan-2026-05-12.md`
- `docs/research/spikes/tts-cosyvoice-playback-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-streaming-timestamp-cancellation-proof-plan-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-streaming-eval-harness-implementation-plan-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-streaming-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/slow-llm-retry-cancellation-eval-plan-2026-05-12.md`
- `docs/research/spikes/slow-llm-retry-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/duplex-vad-realtime-ingress-proof-plan-2026-05-12.md`
- `docs/research/spikes/thinker-qwen-omni-eval-harness-plan-2026-05-12.md`
- `docs/research/spikes/thinker-composer-boundary-eval-dry-run-2026-05-12.md`

Spike-local harnesses now present:

- `tools/model_spikes/asr_streaming_eval/`
- `tools/model_spikes/tts_playback_eval/`
- `tools/model_spikes/slow_llm_retry_eval/`
- `tools/model_spikes/thinker_composer_eval/`

## Executive Conclusion

Model spike work has crossed from ad-hoc run reports into repeatable, spike-local, metadata-only eval shape for the main model-adapter surfaces.

The strongest MVP-3 candidates remain:

- Slow LLM: DashScope / Bailian Qwen for structured JSON planning evidence.
- TTS: DashScope / Bailian CosyVoice for basic synthesis and streaming audio evidence.
- ASR: DashScope / Bailian Qwen-ASR for transcript and timestamp-like evidence.
- Thinker / Composer: DashScope / Bailian Qwen-Omni for SemanticFrame evidence and preliminary Composer-role shape.
- Duplex / VAD: local WebRTC VAD as speech activity evidence, not semantic authority.

The main conclusion is unchanged but sharper: these models can provide adapter-shaped evidence, but none should own Interaction Controller decisions, Router authority, SlowTask lifecycle, SemanticCommitment truth, Tool Executor authorization/execution, or Talker playback state.

## Dry-Run Harness Status

Fresh full-synthetic dry-runs on 2026-05-12 produced and validated:

| harness | full synthetic observations | validation | provider calls | raw artifacts | main coverage |
| --- | ---: | --- | --- | --- | --- |
| ASR streaming eval | 23 | pass | false | none | transcripts, timestamps, streaming output, realtime gap, timeout, cancellation, late transcript, semantic-truth boundary |
| TTS playback eval | 20 | pass | false | none | synthesis, first audio, format/sample rate/voice id, playback progress, truncate chain, client close, local stop, late/partial audio |
| Slow LLM retry eval | 21 | pass | false | none | validation, bounded repair, retry, timeout, client abort, stale result, tool proposal, web evidence, context degradation |
| Thinker / Composer eval | 22 | pass | false | none | SemanticFrame, evidence separation, ASR/Thinker conflict, tool proposal, Composer coverage/truthfulness boundaries |

These harnesses are not runtime tests. They provide repeatable research observations and schema shapes that can later inform adapter profiles and pre-integration evals.

## Candidate Readiness Matrix

| domain | primary candidate | current evidence label | strongest evidence | blocking gaps before MVP-3 consideration | current recommendation |
| --- | --- | --- | --- | --- | --- |
| Slow LLM | DashScope / Bailian Qwen | observed_real + synthetic_eval | validated JSON, insufficient-evidence handling, conflict preservation, bounded repair, tool proposal shape | provider-confirmed cancellation, live retry taxonomy, streaming partial JSON quality, current alias re-pin | profile is closest; prepare adapter-design notes only after owner boundaries are checked |
| Slow LLM comparison | DeepSeek current text API | deferred / unknown | API shape documented; no live comparison in this lane | local provider access, same JSON suite, retry/cancel/latency evidence | keep deferred; not a blocker |
| TTS / Talker | DashScope / Bailian CosyVoice | observed_real + synthetic_eval | basic synthesis, streaming audio chunks, timestamp metadata, first-audio evidence | playback-controller stop accuracy, provider-confirmed cancellation, late audio handling, real truncate proof | viable for TTS candidate; truncate remains Talker/Interaction proof |
| ASR | DashScope / Bailian Qwen-ASR | observed_real/degraded + synthetic_eval | final transcript-like output, response streaming, filetrans timestamp-like metadata | true realtime mic streaming, silence false positives, confidence calibration, provider cancellation, timestamp normalization | viable for ASR candidate; needs realtime ingress proof before integration |
| Thinker | DashScope / Bailian Qwen-Omni | observed_real/degraded + synthetic_eval | validated SemanticFrame JSON, audio Data URL input, uncertainty/evidence separation, untrusted web boundary | semantic close and directedness not observed, full response too slow for hot path, larger schema stability | viable post-commit evidence candidate; keep out of Duplex hot path |
| Thinker-as-Composer | DashScope / Bailian Qwen-Omni role | observed_degraded + synthetic_eval | parseable Composer-role shape, protected-field summary, synthetic coverage/truthfulness cases | independent CoverageCheck / ProgressTruthfulnessCheck runtime chain not implemented here | usable as eval direction only; cannot self-attest safety |
| Duplex / VAD | local WebRTC VAD | observed_real/degraded + planned proof | synthetic frame decisions and latency; known echo/noise risks | live mic scheduling, real AEC/playback reference, semantic close, directedness | next live-ish local proof target; no model authority expansion |

## Capability Conclusions

| capability | conclusion |
| --- | --- |
| Structured JSON planning | `observed_real` for DashScope Qwen Slow LLM; dry-run eval now covers validation, repair, stale, retry, timeout, and tool-proposal boundaries. |
| Basic TTS synthesis | `observed_real` for CosyVoice basic synthesis and streaming audio; dry-run eval now covers playback/truncate event shape separately. |
| TTS truncate | `synthetic_eval` for event shape only; real provider close/client abort/local stop cannot be treated as `TTS_TRUNCATED`. |
| ASR transcript evidence | `observed_real/degraded`; Qwen-ASR produced transcript-like output, but silence/non-speech remains risky. |
| ASR realtime streaming input | `unknown`; response streaming output does not prove true realtime microphone streaming. |
| Thinker SemanticFrame | `observed_real/degraded`; Qwen-Omni can emit validated frames, but quality/latency/authority are constrained. |
| Semantic close | `unknown`; no current model or VAD proof may claim semantic-close authority. |
| Assistant directedness | `unknown`; no current proof may silently assume model-owned directedness. |
| Tool calling | proposal evidence only; Tool Executor remains sole execution and authorization owner. |
| Provider-confirmed cancellation | mostly `unknown/degraded`; client timeout/close is not provider-confirmed cancellation. |
| Deterministic replay | metadata-only; replay must not rerun real ASR, Thinker, Slow LLM, TTS, tools, VAD, or provider services by default. |

## Ownership Boundaries

Current model-spike evidence supports these boundaries:

- ASR output is text projection evidence, not turn ingress, final semantic truth, confirmation, or task completion.
- Thinker output is SemanticFrame evidence, not SemanticCommitment, Router authority, confirmation, resolved arguments, or tool authorization.
- Thinker-as-Composer realizes approved facts into SpokenPlan, but cannot rewrite `immutable_facts`, remove `must_say_fields`, alter `resolved_arguments`, change tool status, remove risk warnings, or infer confirmation state.
- Slow LLM output is structured planning evidence behind validation, not SlowTask state mutation, confirmation, tool execution, UI mutation, or terminal task status.
- TTS / CosyVoice is audio synthesis evidence/provider, not turn ingress owner, Interaction Controller, Router, SlowTask, or semantic truth owner.
- Talker/playback owns playback span state and stop offsets.
- Interaction Controller owns truncate request.
- Tool Executor owns tool execution, authorization, idempotency, and UI state patches.

## MVP Readiness Gates

| gate | 2026-05-12 status | evidence | remaining gap |
| --- | --- | --- | --- |
| Gate 0: research-only boundary | pass | Work stayed in `docs/research/` and `tools/model_spikes/`; protected dirs unchanged in this lane. | Keep guarding provider/live integration separately. |
| Gate 1: spike-local eval readiness | pass for ASR/TTS/Slow LLM/Thinker | Four metadata-only harnesses validate full synthetic matrices. | Duplex/VAD harness code is still not added in this specific refresh. |
| Gate 2: adapter profile hardening | partial/pass by domain | Profile drafts exist for ASR, TTS, Thinker, Slow LLM; proof plans identify gaps. | Need one consolidated adapter-profile hardening pass with official current model aliases and limits. |
| Gate 3: MVP-3 integration consideration | not ready | Evidence is adapter-shaped but not runtime-integrated. | Need approved integration branch, real adapter design, replay/eval fixtures, provider health/error policy, and owner-boundary tests. |

## Recommended Next Plan

1. Use `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md` as the profile hardening gate.
2. Slow LLM, TTS, ASR, Thinker, and focused Composer-boundary hardening addenda are complete; keep them as research candidates, not integration approval.
3. Add or finish the local Duplex/VAD spike-local harness if the next proof target remains realtime ingress and playback-reference behavior.
4. If human approves provider calls later, rerun only selected cases against real providers and write metadata-only run reports; do not store raw payloads or generated audio.
5. Defer any `src/voice_agent/` adapter implementation until a separate MVP-3 integration thread/branch explicitly approves it.

## Recommendation

Proceed with research hardening, not runtime integration.

The next best work item is Duplex/VAD local harness work if the focus shifts back to realtime ingress and playback-reference behavior. If the focus is integration planning instead, prepare a consolidated MVP-3 readiness gap review from the hardened profiles.
