# Qwen Single-Session Slice 3B.0 Governance Acceptance

## Status

ADR-018 was initially accepted on 2026-07-25. Its WebSocket protocol
clarification and related register, canonical-event, adapter-capability, and
cross-ADR governance synchronization were updated on 2026-07-26. This record
authorizes the separately written and reviewed Slice 3B child implementation
plans listed below. It makes no runtime capability, real-provider
qualification, native-PCM enablement, or production-readiness claim.

## Accepted ADR and scope

The authoritative decision is
[`ADR-018 Single-session Qwen Realtime, Parallel Route Evidence, and Slow-to-Fast Context Projection`](../adr/ADR-018%20Single-session%20Qwen%20Realtime%20Parallel%20Route%20Evidence%20and%20Slow-to-Fast%20Context%20Projection.md),
registered as `accepted` in `stage_b_adr_register.md`.

Its scope is Post-ADR-017 / MVP6.x Slice 3B. Slice 3A.2.1 remains the
dual-session, provider-audio-disabled recovery hotfix and gains no
single-session or provider-native playback authority from this record. Slice
3B phase one is bounded to one logical Qwen Realtime session per browser
Connect, at most one active provider WebSocket transport generation at a time,
session-only memory, and one active SlowTask. A rebuild advances the provider
generation without creating a second logical conversation. Durable
cross-session memory, multiple active SlowTasks, pause/resume,
streaming-prefix playback, production privacy/retention, and real external
side effects remain outside the accepted scope.

The 2026-07-26 protocol clarification requires the provider-free Fake and the
future Real WebSocket transport to feed the same Session Adapter through one
serialized sender and one receive Session Pump per generation. The focused
Slice 3B.1 design is
[`2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`](../superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md).

The Interaction Controller, Local Router, Fast Foreground Gate, SlowTask,
Tool Executor, Thinker-as-Composer checks, Event Journal, and deterministic
replay retain their accepted authority boundaries. Models and provider state
remain non-authoritative evidence or projections.

## Canonical event additions

ADR-018 and ADR-002 document exactly these nine canonical additions:

- `ROUTE_EVIDENCE_OUTPUT_EMITTED`
- `CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED`
- `MODEL_CONTEXT_PROJECTION_EMITTED`
- `SLOW_TO_FAST_HANDOFF_EMITTED`
- `SLOW_TO_FAST_HANDOFF_DISPOSITIONED`
- `RESPONSE_ARBITRATION_DECIDED`
- `PROVIDER_CONTEXT_STATE_CHANGED`
- `CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED`
- `ASSISTANT_DELIVERY_DISPOSITIONED`

Each addition has an owner, required fields, causal predecessor, replay
meaning, and redaction boundary. Replay consumes recorded bounded refs,
decisions, digests, dispositions, and state changes; it never reruns a model,
tool, or TTS and never requires raw PCM or provider payloads.

## Existing event compatibility

ADR-018 documents backward-compatible amendments to these existing events:

- `ASR_TRANSCRIPT_OUTPUT_EMITTED`
- `FAST_INTERACTION_OUTPUT_EMITTED`
- `FOREGROUND_REPLY_CANDIDATE_EMITTED`
- `FOREGROUND_ACT_GATE_PASSED`
- `FOREGROUND_ACT_GATE_FAILED`
- `FOREGROUND_OUTPUT_COMMITTED`
- `PLAYBACK_SPAN_STARTED`
- `PLAYBACK_COMMITTED`
- `PLAYBACK_FINISHED`
- `TTS_TRUNCATED`

Existing atomic-single-call events and historical fixtures remain valid. A
missing `fast_interaction_topology` means legacy `atomic_single_call`; new
parallel events use `speculative_candidate_parallel_route`. The compatibility
default does not invent Route Evidence, Candidate Safety, provider-generation,
transcript-digest, or PCM-manifest provenance for historical data.

## Adapter capability additions

ADR-011 and the derived capability specifications add
`adapter_type=route_evidence` with:

- `supports_route_schema`
- `supports_task_focus`
- `supports_foreground_act_hint`
- `supports_ack_kind`
- `supports_candidate_safety_schema`
- `supports_prohibited_claim_detection`
- `supports_strict_json_validation`
- `supports_risk_tags`
- `supports_confidence`

The ASR capability matrix adds:

- `supports_candidate_output_audio_shadow_verification`

Qwen role/session profiles independently declare:

- `supports_smart_turn`
- `supports_streaming_asr`
- `supports_provider_response_cancellation`
- `supports_provider_item_create`
- `supports_provider_item_delete_ack`
- `supports_manual_response_while_idle`
- `supports_text_only_response_override`
- `supports_candidate_quarantine`
- `supports_provider_native_audio_release`
- `supports_provider_context_readiness`
- `supports_context_rebuild`

Documentation support, provider-free test support, real-live support, and
`real|mock|fallback|degraded` status are separate facts. Missing required
capability fails closed or selects an explicit text/TTS/template fallback;
documentation or provider-free evidence never implies real-live support.

## Online PCM latency policy

The online low-latency path performs no per-turn independent PCM
back-transcription. Complete short candidates stay in memory-only quarantine
and require a complete transcript, complete PCM, exact
provider-generation/response/output-item/output-index/content-index
correlation over every delta observed by the single receive Pump, immutable
`candidate_transcript_digest` and `candidate_pcm_manifest_digest`,
independent Candidate Safety Evidence, current capability state, and
deterministic policy checks.

There is no audible PCM before the authoritative Fast Foreground Gate.
Only `FAST_ONLY + FOREGROUND_CHAT + ANSWER`, low risk, current bindings, exact
correlation and digests, and all checks passing can create an immutable
`ForegroundReleaseTokenV1`. Talker must validate that unchanged token before
`PLAYBACK_SPAN_STARTED` and before writing the first PCM byte. Phase one admits
only completed candidates of at most 80 Unicode scalar values and 2,000 ms
decoded audio; prefixes and partial correlation fail closed.

Independent PCM back-transcription latency is measured separately. Failure to
meet the online SLO while preserving every safety condition leaves
provider-native PCM disabled; latency cannot be recovered by releasing an
unapproved prefix.

## PCM qualification and shadow policy

Native PCM remains disabled until pre-promotion PCM back-transcription
qualification passes for a locked synthetic or provider-generated corpus with
playback disabled. Native-PCM promotion requires at least 100 locked
transcript/PCM pairs, including at least 60 matches and 40 mismatches, zero
mismatches classified `MATCH`, and at least 95 percent of true pairs classified
`MATCH`.

After promotion, every released native-PCM turn receives non-blocking live PCM
shadow verification through an independent ASR adapter. Shadow verification
never authorizes, delays, or gates the current turn. `MISMATCH`, `UNCERTAIN`,
timeout, or digest disagreement disables native PCM for subsequent turns in
the Connect session, taints and rebuilds provider context, and selects an
approved text/TTS/template fallback. The result records only digests, bounded
refs, format/duration metadata, equivalence, and capability mode; it contains
no PCM or raw transcript. PCM remains memory-only and is destroyed after
playback or discard plus shadow completion or timeout.

## Context and delivery authority

The local Context Assembler derives immutable `ContextSnapshotV1` projections
only from the per-session Event Journal, reducer state, committed local
conversation items, bounded in-memory Session Memory, and versioned
persona/style configuration. Provider conversation is a cache and projection,
never authoritative task, plan, confirmation, journal, or memory state.
Slice 3B adds no durable or cross-Connect memory.

Provider-backed ingress requires `provider_context_state=CLEAN`. During
cleanup, taint, or rebuild, microphone frames are dropped at the boundary,
bounded/coalesced counts are recorded, and audio is never queued or replayed.
Before rebuild network work, Session Runtime advances provider generation and
the serialized control authority asks Interaction Controller to advance
playback epoch; the Adapter only binds/validates them. Rebuild reconstructs only
locally committed, bounded projections.

SlowTask material may enter fast expression only through a sanitized,
current-plan `SlowToFastHandoffV1`. Raw Slow LLM text, private reasoning, raw
tool output, stale evidence, and untrusted web content are excluded. Phase one
uses a text-only Qwen Composer followed by ProgressTruthfulnessCheck or
CommitmentCoverageCheck before TTS/Talker; Composer cannot rewrite canonical
facts or authority state.

Every provisional assistant item reaches exactly one terminal
`FULL|TRUNCATED|NOT_STARTED` delivery disposition. Only actually delivered
content may enter local/provider history; unheard output and undelivered
suffixes never become shared conversational facts.

## Automated checks

The accepted ADR consistency test verifies accepted/register scope,
canonical-event synchronization, capability synchronization, and the
fail-closed online PCM policy. The exact focused Task 4 regression also
preserves the existing atomic Fast Interaction event and capability contracts:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test \
  tests/governance/test_adr018_document_consistency.py \
  tests/events/test_fast_foreground_event_registry.py \
  tests/adapters/test_fast_interaction_capability.py \
  tests/adapters/test_mvp3_adapter_capability_profiles_spec.py \
  -q
```

Fresh Task 4 result: exit `0`; `38 passed in 0.06s`. This governance
acceptance does not substitute for the provider-free, corpus, live-device,
long-session, critical-violation, security, or SLO gates assigned to later
child plans.

## Security checks

Repository formatting, status, credential-pattern, and prohibited-artifact
checks are required at this handoff. Shareable repository and trace artifacts
must contain no raw PCM, raw audio, raw provider payload, secret, credential,
authorization header, unredacted real transcript, or private reasoning.
Only synthetic, redacted, minimal fixtures and bounded safe refs/metadata are
eligible.

Fresh Task 4 results:

- `git diff --check`: exit `0`, no output;
- the exact credential scan: exit `1`, no matches, which is the clean result;
- no tracked prohibited debug-artifact path or raw media/trace extension;
- no untracked file under `diagnostics/`, `traces/`, `replays/local/`, or
  `audio/raw/`;
- no raw media or trace extension under this acceptance record's
  `docs/implementation` and `tests/governance` scope.

The pre-existing dirty worktree was preserved. The Task 4 report records its
paths separately from this task's two documentation artifacts.

## Runtime capabilities not yet implemented

- single logical Qwen Realtime session runtime with one active, replaceable
  provider transport generation
- real Route Evidence enforcement
- real Candidate Safety enforcement
- native PCM release
- provider context cleanup/rebuild implementation
- Slow-to-Fast Composer bridge
- real-device SLO qualification
- 30-minute/50-turn live qualification

## Required child plans

1. Slice 3B.1 provider-free parallel topology and replay
2. Slice 3B.2 real Qwen WebSocket transport plus real route/candidate-safety
   and candidate-audio shadow/qualification, with provider PCM still inaudible
3. Slice 3B.3 enforced route with provider PCM still disabled
4. Slice 3B.4 qualified native-PCM release and barge-in
5. Slice 3B.5 Slow-to-Fast same-session Composer bridge
6. Slice 3B.6 human-present long-session acceptance

Every child plan must be written and reviewed separately before its code is
implemented.
