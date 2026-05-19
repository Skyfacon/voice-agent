# Model Spike Adapter Profile Hardening Checklist

## Status

research_hardening_checklist_metadata_only

This document is a research checklist for hardening model-spike profile drafts before any MVP-3 integration consideration. It does not authorize runtime integration, provider calls, real business adapters, ADR/spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Historical default contract snapshot for 2026-05-11 / 2026-05-12 evidence: `main@61e6afc`
- New hardening snapshot after mainline sync: `main@ac1b43f` or newer
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- MVP-1 closeout reference: `4dea276 Document MVP-1 closeout architecture status`
- Mainline sync addendum: `docs/research/model-spike-mainline-sync-2026-05-17.md`
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- Event and replay references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`
- Boundary references: ADR-003, ADR-008, ADR-009, and ADR-016

## Scope

In scope:

- A common hardening checklist for ASR, TTS / Talker, Slow LLM, Thinker, Thinker-as-Composer, and Duplex / VAD candidate profiles.
- Per-candidate entry criteria for identity, capability, error policy, replay-safe metadata, unsupported capabilities, and owner-boundary assertions.
- A clear separation between observed evidence, synthetic eval evidence, degraded evidence, unknown gaps, and unsupported ownership.
- A research-only sequence for turning current profile drafts into MVP-3-ready profile candidates.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No provider execution in this checklist step.
- No business adapter implementation.
- No generated audio, provider bodies, raw trace, local replay cache, real user input, or secret-bearing material.
- No claim that any candidate is ready for MVP-3 integration today.

## Source Evidence

Current summaries:

- `docs/research/model-spike-mainline-sync-2026-05-17.md`
- `docs/research/model-spike-phase-summary-2026-05-12.md`
- `docs/research/model-spike-integration-ledger.md`

Profile drafts:

- `docs/research/profiles/slow-llm-qwen-capability-profile-draft-2026-05-11.md`
- `docs/research/profiles/tts-cosyvoice-capability-profile-draft-2026-05-12.md`
- `docs/research/profiles/asr-qwen-asr-capability-profile-draft-2026-05-12.md`
- `docs/research/profiles/thinker-qwen-omni-capability-profile-draft-2026-05-12.md`

Proof plans and dry-run summaries:

- `docs/research/profiles/slow-llm-qwen-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/tts-cosyvoice-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/asr-qwen-asr-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/thinker-qwen-omni-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/thinker-as-composer-boundary-hardening-addendum-2026-05-12.md`
- `docs/research/spikes/slow-llm-retry-cancellation-eval-plan-2026-05-12.md`
- `docs/research/spikes/slow-llm-retry-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/tts-cosyvoice-playback-truncate-proof-plan-2026-05-12.md`
- `docs/research/spikes/tts-cosyvoice-playback-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-streaming-timestamp-cancellation-proof-plan-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-streaming-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/thinker-qwen-omni-eval-harness-plan-2026-05-12.md`
- `docs/research/spikes/thinker-composer-boundary-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/duplex-vad-realtime-ingress-proof-plan-2026-05-12.md`

## Evidence Labels

Use these labels consistently in profile hardening:

| label | meaning | allowed profile use |
| --- | --- | --- |
| `observed_real` | directly observed in a metadata-only real-provider or local run | Can support candidate capability claims, bounded to that run and candidate role. |
| `observed_degraded` | directly observed but incomplete, unsafe, or not enough for target behavior | Can support degradation policy and blocking gaps. |
| `synthetic_eval` | covered by spike-local dry-run observations only | Can support schema and boundary shape, not real provider capability. |
| `docs_only_unobserved` | documented or inferred but not directly observed in this lane | Must be rechecked before hardening. |
| `unknown` | no reliable evidence yet | Must remain a gap or block the affected feature. |
| `unsupported` | outside candidate role or explicitly not owned | Must be listed so runtime cannot rely on it silently. |

## Global Entry Gate

A candidate profile can move from draft to hardening only when all of these are true:

| gate | required evidence |
| --- | --- |
| Research boundary | Profile work stays under `docs/research/` and approved spike-local tooling only. |
| Candidate identity | Candidate role, provider alias, model alias observed date, deployment mode, endpoint ref, and output label are recorded without secret-bearing values. |
| Capability matrix | Every ADR-011 capability is labeled as observed, degraded, synthetic-only, unknown, unsupported, or not applicable for the role. |
| Error taxonomy | Timeout, retryable failure, final failure, validation failure, degradation, client close, and provider-confirmed cancellation are separated. |
| Replay posture | Deterministic replay consumes metadata or synthetic fixtures and does not rerun providers. |
| Privacy posture | Reports do not contain generated audio, provider bodies, raw trace, local replay cache, real user input, or secret-bearing material. |
| Owner boundaries | Candidate output is evidence only unless an accepted owner component records the corresponding event/state transition. |
| Protected dirs | No profile hardening step modifies runtime code, tests, ADRs, or specs. |

## Common Profile Checklist

Each hardened profile should include these sections:

| section | hardening requirement |
| --- | --- |
| Status | Must say research profile only, not runtime integration. |
| Contract Snapshot | Must reference `main@ac1b43f` or newer for new hardening work; older run evidence should preserve its historical `main@61e6afc` snapshot. |
| Candidate Identity | Must pin role, provider alias, model alias observed date, deployment mode, endpoint ref, output label, and health observation. |
| Source Evidence | Must cite run reports, profile drafts, proof plans, and dry-run summaries used. |
| Capability Matrix | Must cover all required capability fields and numeric limits in ADR-011, using evidence labels. |
| Observed Capabilities | Must distinguish direct observations from synthetic eval coverage. |
| Degraded Capabilities | Must define required runtime behavior and future event mapping. |
| Unsupported Capabilities | Must list role-forbidden behavior and ownership boundaries. |
| Unknown / Needs Recheck | Must include current model alias, endpoint limits, timing limits, retry/cancel semantics, and quality gaps. |
| Error / Retry / Cancellation | Must distinguish client-side abort/timeout from provider-confirmed cancellation. |
| Replay-Safe Metadata | Must define metadata-only refs, ids, timing buckets, and no-provider-rerun replay posture. |
| Owner Boundary Notes | Must name the actual owner for Interaction, Router, SlowTask, Tool Executor, Composer, Talker, and Event Journal transitions. |
| MVP Fit | Must state fit to MVP-0 / MVP-1 / MVP-2 / MVP-3 without expanding architecture. |
| Recommendation | Must be one of `harden_next`, `harden_after_gap`, `defer`, or `block_for_mvp3`. |

## Candidate Hardening Matrix

| candidate | current profile state | can harden next? | must close before MVP-3 consideration |
| --- | --- | --- | --- |
| Slow LLM: DashScope Qwen | strongest observed structured JSON profile | yes | current model alias recheck, provider-confirmed cancellation, live retry taxonomy, streaming JSON partial behavior, late result policy mapping. |
| TTS: DashScope CosyVoice | viable synthesis profile | yes, with truncate caveat | playback stop-offset proof, provider cancellation separation, late/partial audio behavior, format/rate/voice matrix, no generated audio in reports. |
| ASR: DashScope Qwen-ASR | viable transcript/timestamp evidence profile | yes, after realtime gap remains explicit | true realtime mic input proof or degraded label, silence/non-speech policy, timestamp normalization, confidence calibration, provider cancellation. |
| Thinker: DashScope Qwen-Omni | viable SemanticFrame evidence profile | yes, for post-commit evidence only | schema stability set, semantic close and directedness remain unknown, response latency caveat, provider cancellation, evidence provenance checks. |
| Thinker-as-Composer: Qwen-Omni role | preliminary Composer shape only | yes as boundary eval, not runtime proof | independent coverage/truthfulness checks, protected-field diff checks, stale evidence rejection, confirmation state preservation. |
| Duplex / VAD: local WebRTC VAD | local speech activity evidence | harden after local harness | live mic scheduling, playback reference/AEC proof, echo/noise false-positive bounds, directedness and semantic close not owned. |
| Slow LLM comparison: DeepSeek | deferred comparison | no | same structured JSON suite, local validation, retry/cancel/latency metadata, model alias recheck. |

## Slow LLM Checklist

Candidate: DashScope / Bailian Qwen structured JSON.

Required before `harden_next`:

- Record current model alias and endpoint ref for the hardening date.
- Confirm profile labels for structured JSON, missing evidence preservation, conflict preservation, untrusted evidence boundary, schema validation, and bounded repair.
- Use spike-local dry-run coverage from `tools/model_spikes/slow_llm_retry_eval/` as synthetic eval evidence only.
- Define validation failure mapping to adapter validation failure metadata before SlowTask consumption.
- Define retry budget, retry reasons, and final failure behavior.
- Bind every planning result to `task_id`, current `plan_version`, `task_event_seq`, adapter request id, and causal refs.
- For UserPatch-like or patch-planning evidence, preserve `observed_plan_version` and `interpreted_against_plan_version` when modeling the MVP-1 owner chain.
- Define old-plan and terminal late result behavior as stale unless SlowTask explicitly adopts/rebases through `STALE_EVIDENCE_ADOPTED`.
- Map stale-result synthetic cases to the post-closeout required fields for `TOOL_RESULT_MARKED_STALE` and `STALE_EVIDENCE_RECORDED`, including current-plan `plan_version` and new `task_event_seq`.
- Mark provider-confirmed cancellation as `unknown` unless directly observed.
- Keep tool-like output as proposal evidence only.

Blockers for MVP-3 consideration:

- Provider-confirmed cancellation remains unknown.
- Streaming structured JSON partial behavior is not live-observed.
- Provider-side transient failure and rate-limit taxonomy are not live-observed.
- DeepSeek remains comparison-only until equivalent evidence exists.

Owner boundary assertions:

- Slow LLM does not own SlowTask state.
- Slow LLM does not accept confirmation.
- Slow LLM does not authorize or execute tools.
- Slow LLM does not mutate UI.
- Slow LLM does not set terminal task status from raw model output.

Recommendation: `harden_next`.

## TTS / Talker Checklist

Candidate: DashScope / Bailian CosyVoice.

Required before `harden_next`:

- Record current model alias, endpoint ref, voice id, requested format, sample rate, and first-audio bucket.
- Preserve `observed_real` for basic synthesis and streaming audio output, bounded to existing run evidence.
- Keep playback progress and truncate chain as `synthetic_eval` until a playback proof runs.
- Separate provider stream close, client close, local playback stop, and Interaction truncate.
- Define output metadata: first audio, chunk count, byte count, duration bucket, format/rate fields, voice id, timestamp/alignment availability, stream end reason.
- Define failure metadata: timeout, retryable failure, format mismatch, late audio, partial audio, client close, provider cancellation unknown.
- State that generated audio is not a replay-safe artifact and is not committed.

Blockers for MVP-3 consideration:

- Talker playback progress and actual stop offset are not real-proven.
- Provider-confirmed cancellation is unknown.
- Format/rate/voice coverage is narrow.
- Late audio after stop/truncate remains synthetic-only.

Owner boundary assertions:

- TTS is audio synthesis evidence/provider only.
- Talker/playback owns playback span state and `actual_stop_offset_ms`.
- Interaction Controller owns truncate request.
- TTS output and playback committed are not user acknowledgement.
- TTS output and playback committed are not SemanticCommitment.
- TTS cannot decide confirmation, tool authorization, task completion, resolved arguments, risk warnings, semantic close, assistant-directedness, or interrupt policy.

Recommendation: `harden_next` with truncate caveat.

## ASR Checklist

Candidate: DashScope / Bailian Qwen-ASR.

Required before `harden_after_gap`:

- Record current model aliases for chat ASR and file transcription surfaces.
- Keep final transcript-like output, response streaming output, audio input, and timestamp-like metadata as observed evidence.
- Keep true realtime microphone input as `unknown` unless directly exercised.
- Preserve silence/non-speech false positive as degraded quality evidence.
- Define normalized timestamp shape: source surface, units, offset basis, segment count, word count, confidence availability, malformed/missing behavior.
- Define transcript metadata without full transcript persistence when not needed: length, snippet ref, confidence fields, timing refs, output label, reliability flags.
- Separate client timeout, stream close, provider cancellation, retryable failure, and late transcript after superseded turn.
- Keep ASR / Thinker conflict as evidence for SlowTask-led review, not Router field arbitration.

Blockers for MVP-3 consideration:

- True realtime mic input remains unknown.
- Silence/non-speech risk needs policy and eval thresholds.
- Confidence calibration and timestamp normalization remain incomplete.
- Provider-confirmed cancellation is unknown.

Owner boundary assertions:

- ASR is text projection evidence only.
- ASR does not own turn ingress.
- ASR does not decide semantic close or assistant-directedness.
- ASR transcript is not SemanticCommitment.
- ASR does not own confirmation, tool authorization, resolved arguments, risk warnings, or task completion.

Recommendation: `harden_after_gap`.

## Thinker Checklist

Candidate: DashScope / Bailian Qwen-Omni as Thinker / SemanticFrame evidence provider.

Required before `harden_after_gap`:

- Record current model alias, endpoint ref, role contract, and output label.
- Preserve observed structured SemanticFrame JSON, evidence separation, ambiguity preservation, untrusted web evidence boundary, audio Data URL input, and streaming text output.
- Keep full structured response latency marked unsuitable for Duplex hot path.
- Keep true realtime mic input, audio timestamps, semantic close, and assistant-directedness as unknown unless directly observed.
- Define SemanticFrame metadata: input modality, evidence refs, intent hint, slot hints, uncertainty, emotion evidence, audio-caption evidence, provenance, degradation.
- Define provider-native tool proposals as proposal evidence only.
- Define timeout, retry, validation failure, late frame, and provider cancellation metadata.

Blockers for MVP-3 consideration:

- Semantic close and assistant-directedness are not observed and cannot be marked real.
- Larger schema stability set is incomplete.
- Provider-confirmed cancellation is unknown.
- Realtime audio input is not proven.

Owner boundary assertions:

- Thinker output is SemanticFrame evidence, not SemanticCommitment.
- Thinker does not own Router winner selection.
- Thinker does not own SlowTask final facts, confirmation, tool authorization, task completion, or resolved arguments.
- Thinker evidence cannot bypass Interaction Controller.
- Emotion, audio caption, intent hints, slot hints, semantic close, and directedness remain evidence, not final facts.

Recommendation: `harden_after_gap` for MVP-3 profile; safe to continue research eval now.

## Thinker-as-Composer Checklist

Candidate role: Qwen-Omni as Composer role, separate from Thinker fast-system role.

Required before `harden_after_gap`:

- Keep Composer as a role contract, not a fact owner.
- Require `SemanticCommitment` or progress event refs as source input.
- Require `source_commitment_id` or progress source ids in SpokenPlan metadata, aligned with MVP-2 `SPOKEN_PLAN_EMITTED` scenarios.
- Require `coverage_check_required` and/or `truthfulness_check_required` flags when the source requires downstream gating.
- Require independent coverage and progress-truthfulness checks before Talker playback.
- Compare protected fields using structured metadata rather than model self-report alone.
- Cover immutable facts, must-say fields, forbidden rewrites, key numbers/dates/locations/names, risk warnings, confirmation state, tool/demo status, untrusted evidence attribution, and stale evidence rejection.
- Define coverage failure behavior: no Talker playback, retry or degraded template response.

Blockers for MVP-3 consideration:

- Runtime coverage/truthfulness chain is not proven in this research lane.
- Protected-field diff checking is synthetic-only.
- Confirmation and stale evidence safety require owner-chain proof.

Owner boundary assertions:

- SemanticCommitment remains SlowTask fact source.
- Composer only realizes approved content as SpokenPlan.
- Composer cannot rewrite immutable facts or resolved arguments.
- Composer cannot remove risk warnings or must-say fields.
- Composer cannot infer confirmation acceptance.
- Composer cannot turn demo dry-run status into real external completion.

Recommendation: `harden_after_gap` for runtime use; continue boundary eval.

## Duplex / VAD Checklist

Candidate: local WebRTC VAD for speech activity evidence.

Required before `harden_after_gap`:

- Add or finish a spike-local VAD harness with metadata-only JSONL.
- Record frame duration, mode, sample rate, speech start/end offsets, hangover behavior, false-positive classes, and playback reference availability.
- Separate speech activity from semantic close and assistant-directedness.
- Record echo likelihood and playback overlap metadata for barge-in candidate proof.
- Keep real AEC/live mic scheduling as unknown unless locally exercised.
- Define how VAD evidence maps to `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, and `BARGE_IN_CANDIDATE` metadata.

Blockers for MVP-3 consideration:

- Live mic scheduling and real playback reference behavior are unproven.
- Echo/noise false-positive boundaries are not quantified enough.
- Semantic close and assistant-directedness remain outside VAD authority.

Owner boundary assertions:

- VAD provides speech activity evidence only.
- Duplex/VAD does not own turn ingress commit.
- Duplex/VAD does not own truncate confirmation.
- Interaction Controller decides interrupt/truncate request.
- Talker/playback confirms stopped playback.

Recommendation: `harden_after_gap`; next local proof if focusing live audio.

## Replay-Safe Metadata Checklist

Every hardened profile should define a minimal metadata shape with:

- `contract_snapshot`
- candidate profile id
- adapter role
- provider alias
- model alias observed date
- deployment mode
- endpoint ref
- output label
- adapter request id
- source event refs or synthetic fixture refs
- timing buckets
- validation status
- failure category
- retry count and retry reason
- provider-confirmed cancellation flag with `unknown` allowed
- stale/late output policy where task-bound
- privacy flags proving no generated audio, provider bodies, raw trace, local replay cache, real user input, or secret-bearing material

Deterministic replay must consume the metadata or synthetic fixture only. It must not rerun real ASR, Thinker, Slow LLM, TTS, tools, VAD, or provider services by default.

## Event Mapping Checklist

Profiles should map future adapter observations to event families without creating new event names:

| area | allowed mapping | forbidden mapping |
| --- | --- | --- |
| Adapter health | healthcheck failed, retrying, request failed, validation failed, degraded | No request bodies or secret-bearing values in events. |
| ASR evidence | ASR frame refs and output label after turn ingress owner accepts input | No ASR-owned turn commit or SemanticCommitment. |
| Thinker evidence | SemanticFrame refs and evidence provenance | No Thinker-owned final facts or Router winner selection. |
| Slow LLM evidence | validated task-bound planning evidence | No direct SlowTask state mutation from raw output. |
| Composer | SpokenPlan plus independent check refs | No playback without coverage/truthfulness pass for committed facts. |
| TTS / Talker | playback span, progress, committed, truncate requested, truncated | No provider-close-as-truncate and no playback-as-acknowledgement. |
| Tool-like output | proposal evidence only | No model-owned tool execution or authorization. |

## MVP Fit Checklist

| slice | profile hardening implication |
| --- | --- |
| MVP-0 | Real adapters are not required; current work informs future replacement and replay/eval shape. |
| MVP-1 | Slow LLM evidence must preserve post-closeout plan version, observed plan version, task event sequence, stale/adoption policy, terminal stickiness, and SlowTask ownership. |
| MVP-2 | Composer role must pass coverage/truthfulness checks; tool proposals remain Tool Executor-owned; UI state changes can only come from `TOOL_UI_STATE_PATCHED`; webSearch remains `UNTRUSTED_WEB_EVIDENCE`. |
| MVP-3 | Real ASR / Thinker / Slow LLM / TTS adapters can be considered only without adding new architecture capabilities. |

## Hardening Sequence

Recommended sequence:

1. Slow LLM Qwen hardening addendum is first because structured JSON, validation, bounded repair, and stale policy are strongest.
2. TTS CosyVoice hardening addendum is second, with playback/truncate proof kept separate from provider synthesis.
3. ASR Qwen-ASR hardening addendum is third, with realtime input and silence-risk gaps kept explicit.
4. Thinker Qwen-Omni hardening addendum is fourth, keeping it out of Duplex hot path and preserving SemanticFrame-only authority.
5. Thinker-as-Composer boundary hardening addendum is focused on spoken realization, protected-field checks, and playback gates; model self-report remains insufficient as safety proof.
6. Add Duplex/VAD local harness only when the next focus is live audio ingress and playback-reference proof.
7. Defer DeepSeek comparison until equivalent live evidence exists.

## Exit Criteria For This Research Phase

This research phase can be considered ready for a later MVP-3 integration planning discussion when:

- Each primary candidate has a hardened profile with all capability fields labeled.
- Every unknown or unsupported field has a degradation or block policy.
- Every task-bound model output has a request id and causal binding shape.
- Provider-confirmed cancellation is either directly observed or explicitly marked unknown with stale/late-output behavior.
- Replay-safe metadata shapes exist for all primary domains.
- Owner-boundary assertions are explicit for Interaction, Router, SlowTask, Tool Executor, Composer, Talker/playback, and Event Journal.
- No profile requires committing generated audio, provider bodies, raw trace, local replay cache, real user input, or secret-bearing material.

## Recommendation

Proceed with profile hardening in research docs only. Do not start runtime integration from this checklist.

The next concrete work item is Duplex/VAD local harness work if realtime ingress becomes the priority, or a consolidated MVP-3 readiness gap review if integration planning becomes the priority.
