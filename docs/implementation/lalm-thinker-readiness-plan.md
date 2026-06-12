# LALM Thinker Readiness Plan

Status: readiness_plan_only_no_runtime_approval

Date: 2026-06-12

This document plans the LALM / real Thinker adapter readiness path. It does not
implement an adapter, add a provider SDK, call a provider, read secrets, modify
canonical events, or approve live-provider evaluation.

## Goal

Prepare a provider-neutral, ADR-compliant path for a future LALM real Thinker
adapter that can emit normalized SemanticFrame-compatible evidence through the
existing `ThinkerAdapterContract`.

The immediate goal is readiness only: document constraints, baseline contracts,
safe normalization, replay/fixture requirements, approval gates, and an
implementation backlog that future PRs can execute independently.

## Non-goals

- No runtime adapter implementation.
- No provider SDK dependency.
- No provider endpoint call, health probe, or live eval.
- No environment secret read or credential lookup.
- No canonical event addition or ADR modification.
- No raw provider request body, response body, prompt dump, SDK object, tool
  payload, raw audio, raw trace, local replay cache, secret, token, cookie,
  credential, or unredacted real user input in docs, tests, fixtures, traces, or
  event payloads.
- No Router, SlowTask, Tool Executor, confirmation, Composer checker, playback,
  or trace/replay ownership change.
- No provider-native tool execution or authorization.
- No promotion of Thinker evidence into `SemanticCommitment`.

## Accepted ADR constraints

The current accepted ADR register remains the authority. This plan uses the
following constraints as hard gates:

| Source | Constraint for LALM Thinker readiness |
| --- | --- |
| ADR-002 | Use the per-session append-only Event Journal and existing canonical event names. Replay consumes recorded events and refs only; it must not rerun providers. |
| ADR-008 | ASR and Thinker are evidence sources. Router must not choose field winners, and SlowTask owns ambiguity/conflict resolution. |
| ADR-009 | Thinker-as-Composer may perform spoken realization only. It must not rewrite `SemanticCommitment` facts, confirmation state, tool status, risk warnings, or resolved arguments. |
| ADR-010 | GitHub/shareable replay artifacts must be synthetic, redacted, or minimal. Raw audio, raw trace, raw provider payloads, secrets, and unredacted real input are forbidden. |
| ADR-011 | All model calls must go through adapters. Every adapter declares capabilities and explicit `real`, `mock`, `fallback`, or `degraded` output modes. |
| ADR-012 | MVP-3 replaces real adapters behind existing boundaries and must not add new architecture capability. |
| ADR-016 | SlowTask owns lifecycle, plan version, confirmation, cancel, stale evidence adoption, and tool authorization state. |

Repository governance also requires `.gitignore` coverage for local-only
artifact directories. The current `.gitignore` covers `diagnostics/`, `traces/`,
`replays/local/`, `audio/raw/`, `.env`, `.env.*`, and `outputs/`.

## Current mainline Thinker contract baseline

Current mainline already has the provider-neutral MVP-3 Thinker contract:

- `src/voice_agent/adapters/thinker_contract.py`
- `tests/adapters/test_mvp3_thinker_adapter_contract.py`
- `src/voice_agent/replay/runner.py`
- `docs/specs/event-registry.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/adapter-capability-profiles.md`

Baseline behavior:

- `ThinkerAdapterContract.emit_semantic_frame` is the only planned output path
  for real Thinker SemanticFrame-compatible evidence.
- The canonical output event is
  `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED`.
- The output must be caused by a prior matching `TURN_INGRESS_COMMITTED`.
- Required output fields include `adapter_id`, `adapter_type=thinker`,
  `adapter_request_id`, `turn_id`, `utterance_id`, `input_modality`,
  `semantic_frame_schema=voice_agent.semantic_frame.v1`,
  `normalization_status=normalized`, `semantic_frame_ref`,
  `semantic_summary_ref`, and `output_mode=real|fallback|degraded`.
- Optional semantic evidence is represented only by refs plus statuses:
  `semantic_close_ref`, `assistant_directedness_ref`, `emotion_ref`,
  `audio_caption_ref`, and matching `*_status`.
- Optional statuses are only `available` or `unavailable`.
- Missing optional semantic fields require `output_mode=degraded` plus matching
  `ADAPTER_OUTPUT_DEGRADED` events for the missing capability.
- The adapter callback append boundary owns journal append serialization and
  `adapter_callback_seq`.
- Replay rejects raw/provider fields such as provider responses, provider
  schemas, raw semantic payload names, raw audio, and raw trace.
- Router may reference a real Thinker frame by `thinker_frame_event_id`, but it
  must not copy semantic refs or provider payload into the Router decision.
- UserPatch evidence may consume real Thinker refs as non-authoritative
  hypothesis, with provenance bound to the referenced Thinker event.

## Handoff summary

The handoff document was not present in this worktree at drafting time. Its
contents were read from the dedicated handoff branch as evidence only.

Useful handoff findings:

- Current mainline contracts, not historical spike artifacts, remain the
  implementation authority.
- Historical Qwen-Omni/LALM spike evidence suggests a provider can produce
  SemanticFrame-like structured JSON for synthetic text and local synthetic
  audio probes, but that evidence is not live-provider approval.
- The spike supports planning a provider-neutral skeleton, fake transport, and
  metadata-only eval path before any provider call.
- Semantic close, assistant-directedness, emotion, audio caption, cancellation,
  streaming input, provider alias, quota, pricing, and current limits remain
  unverified for live readiness.
- Provider-native tool-like deltas, if observed later, are proposal evidence
  only and never Tool Executor state.
- Composer safety cannot be proven by model self-report; independent
  CommitmentCoverageCheck and ProgressTruthfulnessCheck remain mandatory.

## Provider role and forbidden ownership

The LALM provider role is narrow:

- Produce transient adapter-internal candidate text/JSON from approved
  adapter-internal inputs after a future live approval gate.
- Allow adapter-local parsing and validation to derive normalized safe refs and
  metadata.
- Surface failures, timeouts, validation failures, and degradations through
  existing canonical adapter events.

The provider and Thinker adapter must not own:

- turn ingress, barge-in, truncate, or playback policy;
- Router field-level ASR/Thinker winner selection;
- SlowTask state, plan version, stale-evidence adoption, or final task facts;
- `SemanticCommitment` creation;
- confirmation acceptance, rejection, cancel, or tool authorization;
- Tool Executor execution, UI patching, idempotency, retry, or side effects;
- Composer coverage/truthfulness verdicts;
- playback approval or Talker output.

Thinker output is evidence only. It can inform evidence packs, task focus hints,
uncertainty, and SlowTask review, but it is not a commitment, authorization, or
execution instruction.

## Canonical event mapping

No new canonical event is needed for LALM Thinker readiness.

| Condition | Existing event or chain |
| --- | --- |
| Session records adapter modes | `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` |
| Retryable provider timeout/failure after future approval | `ADAPTER_REQUEST_RETRYING` |
| Final provider request failure after future approval | `ADAPTER_REQUEST_FAILED` |
| Provider/candidate output fails adapter schema validation | `ADAPTER_OUTPUT_VALIDATION_FAILED` |
| Unsupported or missing optional Thinker capability | `ADAPTER_OUTPUT_DEGRADED` |
| Valid normalized Thinker output | `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` |
| Router consumes Thinker evidence | `ROUTER_DECISION_EMITTED.thinker_frame_event_id` |
| SlowTask receives Thinker-derived patch evidence | `USER_PATCH_RECEIVED.evidence_pack.non_authoritative_hypothesis` with provenance |
| SlowTask reviews evidence | `EVIDENCE_REVIEWED` and follow-on SlowTask evidence events |
| Final facts are emitted | `SEMANTIC_COMMITMENT_EMITTED` by SlowTask, not Thinker |
| Composer realizes speech | `SPOKEN_PLAN_EMITTED` plus coverage/truthfulness checks |

The future adapter must emit events through existing journal append boundaries.
It must not write provider output directly into the Event Journal.

## Capability/profile plan

Initial LALM Thinker capability work should be provider-free and conservative:

- `adapter_type=thinker`.
- `output_mode=real` may be used in synthetic profile readiness only when the
  profile is non-mock, provider-neutral metadata and passes the existing MVP-3
  profile gates. Runtime provider behavior remains unapproved until a later
  live eval gate.
- `supports_structured_json=true` is required for real Thinker readiness.
- `supports_audio_input` may be planned as historically observed, but live
  readiness must recheck current provider limits.
- `supports_streaming_input`, `supports_audio_timestamps`,
  `supports_semantic_close`, `supports_assistant_directedness`,
  `supports_emotion`, `supports_audio_caption`, `supports_tool_calling`, and
  `supports_cancellation` must be declared honestly and degraded or unsupported
  until proven.
- `supports_audio_output`, `supports_tts`, `supports_tts_truncate`, and
  `supports_tts_pause_resume` are not Thinker-owned capabilities.
- Endpoint and config values must be safe refs, never credential-bearing URLs or
  inline provider config.
- Unsupported boolean capabilities must be listed in
  `unsupported_capabilities`.
- Mock, fallback, and degraded profiles may be present, but they do not count as
  required MVP-3 real readiness.

## SemanticFrame normalization plan

Future implementation should normalize in stages:

1. Bind a request to a prior `TURN_INGRESS_COMMITTED` event, including
   `turn_id`, `utterance_id`, `input_modality`, and any matching text/audio span
   ids.
2. Construct adapter-internal request metadata from refs and policy inputs only;
   do not retain full prompts, provider payloads, secrets, raw audio, or local
   debug paths.
3. Parse exactly one provider/candidate object in a strict adapter-local
   candidate schema, such as `lalm_thinker_semantic_frame_candidate.v1`.
4. Validate binding fields, schema version, evidence-only assertions,
   unsupported ownership assertions, and raw artifact retention flags.
5. Normalize valid candidate fields into system refs:
   `semantic_frame_ref`, `semantic_summary_ref`, and optional refs for semantic
   close, assistant-directedness, emotion, and audio caption.
6. Convert missing optional fields into explicit unavailable statuses and
   matching degraded metadata.
7. Emit through `ThinkerAdapterContract.emit_semantic_frame` only after
   validation and normalization.

The adapter-local candidate schema is not a canonical event. It must remain
inside adapter code/tests and may not become a downstream business schema.

## Safe ref and redaction policy

Allowed committed refs are synthetic, redacted, minimal, and provider-neutral,
for example:

- `semantic-frame://synthetic/...`
- `summary://synthetic/...`
- `semantic-close://synthetic/...`
- `assistant-directedness://synthetic/...`
- `emotion://synthetic/...`
- `audio-caption://synthetic/...`
- `validation://synthetic/...`
- `eval-summary://synthetic/...`

Refs and metadata must reject or redact:

- credential-like values, bearer values, API keys, tokens, cookies,
  authorization headers, passwords, and session secrets;
- provider request bodies, response bodies, SDK objects, provider schemas, raw
  SemanticFrame JSON, raw summaries, raw tool-call arguments, and full prompts;
- raw audio bytes, audio data URIs, generated audio payloads, and raw trace
  payloads;
- local-only artifact locations, including diagnostics, traces, local replay
  cache, and raw audio storage;
- decoded URL variants that hide unsafe values;
- unredacted real user input.

Errors and validation failures must report safe categories and failure refs, not
raw bodies or snippets.

## Replay and fixture safety plan

Replay and fixtures must remain provider-free:

- Deterministic replay consumes recorded events and safe refs only.
- Replay must not call the provider, read credentials, inspect environment
  secrets, use clocks/random/network, or require raw audio.
- GitHub fixtures must be hand-written minimal, synthetic, or redacted.
- Fixture manifests must state that they contain no raw audio, raw trace, real
  user input, secrets, unredacted tool result, or large raw web content.
- Synthetic success fixtures should include all optional refs available.
- Degraded fixtures should cover each optional missing capability with matching
  `ADAPTER_OUTPUT_DEGRADED`.
- Negative fixtures should cover forbidden payload field names, invalid status
  enums, status/ref mismatches, unsafe refs, missing turn linkage, Router
  non-prior Thinker refs, and UserPatch stale semantic refs.
- Late or mismatched output must remain bound to its original request/turn and
  must not advance current SlowTask state without a SlowTask-owned adoption
  path where applicable.

## Live eval approval gate

No live eval command should be runnable until a separate approval packet exists
and is approved.

The packet must include:

- provider and model alias with a current recheck date;
- endpoint/config refs with no credential values;
- synthetic input set only;
- cost, quota, timeout, retry, and cleanup limits;
- output location policy and proof it is repo-safe or local-only ignored;
- explicit redaction and non-retention policy for raw provider bodies, full
  prompts, raw audio, traces, replay cache, secrets, and real user input;
- fail-closed command behavior when approval or credentials are absent;
- statement that live observations may produce aggregate metadata summaries and
  synthetic fixtures only, not raw provider traces.

Approval of the packet authorizes only the named synthetic eval command and
budget. It does not authorize production traffic, real user input, external
side-effect tools, canonical event changes, or ownership changes.

## Open questions

- Which current LALM/Qwen-Omni model alias, endpoint class, and modality limits
  should be re-pinned before live eval?
- Should Thinker-as-Fast-System and Thinker-as-Composer share one provider
  client with separate role profiles, or separate adapter-local methods?
- What provider-neutral safe storage namespace should hold normalized
  SemanticFrame summaries for approved live eval?
- Should semantic close and assistant-directedness remain conservative policy
  fields, or be probed as evidence-only model fields?
- What bounded repair policy is acceptable for malformed candidate JSON before
  emitting validation failure?
- What cancellation proof is required before claiming provider-side cancellation
  support?
- What latency bucket is acceptable for Thinker evidence that is not in the
  Duplex hot path?

## Definition of done for readiness

Readiness is complete when:

- This plan and `docs/implementation/lalm-thinker-backlog.md` are committed.
- The docs reference current mainline contract files and accepted ADR
  constraints.
- The plan proposes no new canonical event, ADR change, provider SDK, provider
  call, secret read, runtime adapter, raw provider retention, or ownership
  change.
- The backlog slices are independently executable as future PRs/goals.
- `.gitignore` coverage for required local-only artifact classes has been
  checked.
- `git diff --check` passes.
- Full `./scripts/test` is intentionally not run for this docs-only change; any
  future code/test slice must use `./scripts/test`.
