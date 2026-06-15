# ASR Adapter Integration Backlog

This backlog decomposes real ASR adapter integration into independently
reviewable PR/goal slices. Slice 0 is documentation only. Later slices must
preserve accepted ADR boundaries, use existing canonical events, and keep
provider calls behind explicit approval gates.

Global boundaries for every slice:

- Do not add canonical event names.
- Do not modify ADRs unless a slice discovers an architecture gap and pauses.
- Do not call a provider unless the slice explicitly includes an approved live
  eval or gated real transport step.
- Do not read env secrets before the approved live eval or gated transport
  slice.
- Do not add provider SDK dependencies unless separately approved in the
  relevant slice. Prefer provider-free fake transport until then.
- Do not commit raw audio, raw transcript, raw provider request/response,
  prompt dump, local trace, local replay cache, secrets, or unredacted real
  user input.
- Keep ASR output as transcript/text projection evidence only.
- Keep turn ingress, semantic close, assistant directedness, Router decisions,
  SlowTask final facts, confirmation, tool authorization, Tool Executor,
  Composer, and playback outside ASR.

## Slice 0: readiness plan + backlog only

### Objective

Create the ASR adapter readiness plan and this backlog. Lock current mainline
contract assumptions, research-source assumptions, forbidden scope, replay
safety, and live-eval gates without changing runtime behavior.

### Non-goals

- No adapter implementation.
- No provider SDK or transport.
- No provider calls or secret reads.
- No tests beyond documentation sanity checks unless a doc-only check fails.
- No ADR, spec, event registry, or canonical event change.

### Likely files

- Create: `docs/implementation/asr-adapter-readiness-plan.md`
- Create: `docs/implementation/asr-adapter-backlog.md`
- Read: `AGENTS.md`
- Read: `stage_b_adr_register.md`
- Read: ASR contract, tests, replay runner, specs, MVP-3 docs, and accepted
  ADRs listed in the readiness task.

### Contract constraints

- This slice only documents existing constraints.
- It must preserve `ASR_TRANSCRIPT_OUTPUT_EMITTED` as the canonical ASR output
  event and must not add new event names.
- It must document that `ASR_TRANSCRIPT_OUTPUT_EMITTED` is caused by
  `TURN_INGRESS_COMMITTED`.
- It must document safe refs: `asr_frame_ref`, `text_ref`, and optional
  `audio_timestamps_ref`.

### Tests / replay fixtures

- Run `git diff --check`.
- Full `./scripts/test` is not required because this slice is docs-only and
  does not modify executable code, schemas, fixtures, ADRs, or specs.

### Definition of done

- Readiness plan exists with all requested sections.
- Backlog exists with independently reviewable slices and suggested goal
  prompts.
- `.gitignore` coverage for local-only artifact paths is confirmed.
- Git diff contains only the two planning documents.
- Changes are committed on the current branch.

### Review checklist

- No ADR or canonical event change.
- No provider SDK, transport, or provider call.
- No secret/env read.
- No raw provider, transcript, audio, trace, replay cache, local path, or prompt
  dump copied from research materials.
- ASR is described as evidence only, not semantic truth or control authority.

### Suggested goal prompt for that slice

```text
In the current ASR adapter worktree, create docs-only ASR adapter readiness and
backlog documents. Read AGENTS.md, accepted ADRs, ASR contract, replay, specs,
MVP-3 docs, and metadata-only ASR research assumptions. Do not implement
adapter code, add SDKs, call providers, read secrets, or change canonical
events. Run git diff --check and commit the docs.
```

## Slice 1: provider-free capability/profile builder

### Objective

Add a provider-free ASR capability/profile builder that produces safe
metadata-only real/fallback/degraded ASR profile candidates and validates them
against existing capability rules before runtime assembly.

### Non-goals

- No provider selection beyond safe metadata labels.
- No provider SDK, HTTP client, health probe, or network call.
- No credential read or credential handle.
- No runtime transcript generation.
- No replay fixture generated from real provider output.

### Likely files

- Modify or create: `src/voice_agent/adapters/asr_profile.py`
- Modify: `src/voice_agent/adapters/profiles.py` only if existing validators
  need provider-neutral ASR helper coverage.
- Modify or create: `tests/adapters/test_asr_adapter_profile.py`
- Read: `docs/specs/model-adapter-capabilities.md`
- Read: `docs/specs/adapter-capability-profiles.md`

### Contract constraints

- `adapter_type=asr`.
- Required real readiness must include `supports_audio_input=true`.
- `supports_structured_json` may mean adapter-normalized ASR metadata only, not
  SlowTask semantic reasoning.
- Unsupported ownership capabilities must remain false or unsupported:
  tool calling, TTS, semantic close authority, assistant directedness authority,
  confirmation, tool authorization, and playback.
- Credential-like endpoint/config refs must fail closed.
- Mock-only profiles must not satisfy MVP-3 real readiness.

### Tests / replay fixtures

- Provider-free tests for valid real, fallback, and degraded ASR profile
  metadata.
- Tests that credential-like endpoint/config refs fail closed.
- Tests that unsupported capability mismatch fails closed.
- Tests that mock-only ASR profiles do not count as required MVP-3 real
  readiness.
- Run focused tests with `./scripts/test tests/adapters/test_asr_adapter_profile.py -q`.

### Definition of done

- ASR profile builder emits safe metadata without provider probes.
- Existing MVP-3 profile set validation can consume the ASR profile.
- Unsupported capabilities are explicit.
- No provider runtime path exists.
- Focused tests pass through `./scripts/test`.

### Review checklist

- No network call or provider import.
- No secret/env access.
- No credential-bearing endpoint/config refs.
- No capability overclaim from research assumptions.
- No changes to canonical events or ADRs.

### Suggested goal prompt for that slice

```text
Implement a provider-free ASR capability/profile builder. It must emit safe
metadata-only ASR profiles, fail closed for credential-like refs and unsupported
capability mismatch, and integrate with existing MVP-3 profile validators. Do
not add provider SDKs, transports, provider probes, secret reads, or runtime ASR
output. Use ./scripts/test for focused tests.
```

## Slice 2: request binding + normalized ASR transcript candidate schema

### Objective

Define provider-neutral request binding and normalized ASR transcript candidate
schema. The schema should bind transcript evidence to committed audio turns and
prepare safe refs for later parser/validator and contract emission.

### Non-goals

- No provider transport.
- No provider request body builder that contains raw audio.
- No raw transcript storage.
- No event emission.
- No Router, SlowTask, Tool Executor, Composer, or playback change.

### Likely files

- Create or modify: `src/voice_agent/adapters/asr_normalization.py`
- Modify or create: `tests/adapters/test_asr_transcript_normalization.py`
- Read: `src/voice_agent/adapters/asr_contract.py`
- Read: `src/voice_agent/understanding/mock_asr.py`
- Read: `docs/specs/event-registry.md`

### Contract constraints

- Binding must include `turn_id`, `utterance_id`, `audio_span_id`,
  `input_modality=audio`, `adapter_request_id`, and
  `turn_committed_event_id`.
- Candidate output must carry safe refs: `asr_frame_ref`, `text_ref`, and
  optional `audio_timestamps_ref`.
- Candidate output must distinguish final transcript, timestamp status,
  streaming status, normalization status, output mode, quality flags, and
  optional confidence/language/nbest metadata refs.
- ASR transcript is evidence and cannot directly produce `resolved_arguments`,
  `SemanticCommitment`, confirmation, or tool authorization.

### Tests / replay fixtures

- Tests that candidate binding rejects missing or mismatched committed turn
  metadata.
- Tests that text and ASR frame refs reject credential-like content.
- Tests that raw transcript fields, raw provider fields, raw audio fields, and
  prompt/provider body fields are rejected.
- Tests that timestamp unavailable and final-only streaming states are
  represented as degraded metadata.
- No replay fixture required yet; schema remains provider-free.

### Definition of done

- Normalized candidate dataclass or typed mapping exists with provider-neutral
  fields.
- Binding validation rejects unsafe or ownership-violating candidates.
- Tests prove the schema can represent final transcript, timestamp unavailable,
  and final-only degraded output without raw data.

### Review checklist

- Candidate schema contains refs and metadata only.
- No raw transcript, provider body, prompt dump, or local path.
- No direct event append.
- No semantics or ownership leakage into ASR.

### Suggested goal prompt for that slice

```text
Add provider-neutral ASR request binding and normalized transcript candidate
schema. Bind candidates to TURN_INGRESS_COMMITTED audio metadata and safe refs
only. Reject raw transcript/provider/audio payloads and ownership claims. No
provider transport and no event emission. Use ./scripts/test for focused tests.
```

## Slice 3: parser/validator + fake transport, no network

### Objective

Add parser/validator behavior for normalized ASR candidates using fake transport
responses only. Exercise timeout, malformed output, degraded timestamp,
final-only streaming, low-confidence/non-speech, and late-result metadata paths
without network access.

### Non-goals

- No provider SDK or real HTTP/WebSocket transport.
- No provider endpoint probe.
- No secret read.
- No raw provider response retention.
- No event emission beyond fake metadata classification unless existing
  provider-free adapter harness is reused in tests.

### Likely files

- Modify: `src/voice_agent/adapters/asr_normalization.py`
- Create or modify: `src/voice_agent/adapters/asr_fake_transport.py`
- Modify or create: `tests/adapters/test_asr_transcript_normalization.py`
- Modify or create: `tests/adapters/test_asr_fake_transport.py`

### Contract constraints

- Parser accepts only provider-neutral fake response shapes in tests.
- Malformed output maps to safe validation failure categories.
- Timeout and request failure map to safe failure metadata.
- Missing timestamps and final-only output remain explicit degraded metadata.
- Late results remain bound to original request/audio/turn refs and cannot
  advance current task state.

### Tests / replay fixtures

- Fake success response normalizes to a final transcript candidate with safe
  refs.
- Fake malformed response produces validation failure metadata and no success
  candidate.
- Fake timeout/request failure produces safe failure metadata and no success
  candidate.
- Fake timestamp-unavailable response produces degraded timestamp metadata.
- Fake final-only response produces degraded streaming metadata.
- Fake non-speech/low-confidence response sets explicit quality flags.
- Fake late response remains stale/ignored metadata and does not emit current
  output.

### Definition of done

- Parser/validator and fake transport are fully provider-free.
- Failure/degraded classifications are deterministic and safe.
- Tests cover success, validation failure, request failure, degraded timing,
  final-only streaming, quality risk, and late result.

### Review checklist

- No network-capable import.
- No provider-specific request body or response body in fixtures.
- No raw transcript in event-like output.
- No ASR control authority.
- Failure categories are redacted and bounded.

### Suggested goal prompt for that slice

```text
Implement provider-free ASR parser/validator and fake transport tests. Use fake
responses only to cover normalized success, malformed output, timeout/failure,
missing timestamps, final-only streaming, non-speech risk, and late result
metadata. Do not add network code, provider SDKs, provider calls, or secret
reads. Use ./scripts/test for focused tests.
```

## Slice 4: contract emission through AsrAdapterContract

### Objective

Connect validated normalized ASR candidates to `AsrAdapterContract` so success
output emits `ASR_TRANSCRIPT_OUTPUT_EMITTED` and required degraded events
through `AdapterCallbackAppendBoundary`.

### Non-goals

- No real provider transport.
- No new event names.
- No Router/SlowTask/Composer/Tool Executor behavior change.
- No raw payload in journal events.

### Likely files

- Modify: `src/voice_agent/adapters/asr_contract.py` only if a small helper is
  needed.
- Modify: `src/voice_agent/adapters/asr_normalization.py`
- Modify or create: `tests/adapters/test_asr_contract_emission.py`
- Read: `tests/adapters/test_mvp3_asr_adapter_contract.py`
- Read: `src/voice_agent/runtime/adapter_callback_boundary.py`

### Contract constraints

- Emission uses existing `AsrAdapterContract.emit_final_transcript()`.
- `ASR_TRANSCRIPT_OUTPUT_EMITTED` must be caused by
  `TURN_INGRESS_COMMITTED`.
- Missing timestamps and unsupported streaming must emit prior ASR
  `ADAPTER_OUTPUT_DEGRADED` events.
- Success event uses safe refs only.
- Output mode is `real`, `fallback`, or `degraded`; no `mock` success output
  for real ASR contract.

### Tests / replay fixtures

- Test validated candidate emits success event through callback boundary.
- Test timestamp unavailable emits degraded event before success.
- Test final-only streaming emits degraded event before success.
- Test unsafe refs and raw payload markers fail before event append.
- Test event envelope validation passes for emitted events.
- Test provider runtime remains blocked in contract emission tests.

### Definition of done

- Validated candidates can be emitted through the existing ASR contract.
- Contract emission preserves adapter callback sequencing and journal ordering.
- Degraded paths are replay-visible.
- Focused tests pass with provider probes blocked.

### Review checklist

- Uses existing canonical events only.
- Uses `AdapterCallbackAppendBoundary`.
- Does not allocate callback sequence outside the boundary.
- Does not emit raw provider output.
- Does not bypass committed audio turn causality.

### Suggested goal prompt for that slice

```text
Wire validated ASR transcript candidates into AsrAdapterContract emission.
Ensure ASR_TRANSCRIPT_OUTPUT_EMITTED is caused by TURN_INGRESS_COMMITTED and
uses only safe refs. Missing timestamps and final-only streaming must emit
ADAPTER_OUTPUT_DEGRADED first. Keep provider runtime blocked and use
./scripts/test for focused tests.
```

## Slice 5: replay / fixture safety coverage

### Objective

Add replay and fixture safety coverage for ASR real/fallback/degraded metadata
without provider rerun or raw artifacts.

### Non-goals

- No real provider fixture.
- No raw audio or raw transcript fixture.
- No provider body snapshot.
- No re-eval mode.
- No event registry changes.

### Likely files

- Modify or create: `tests/replay/test_asr_transcript_replay.py`
- Modify: `tests/fixtures/replay/mvp3/manifest.index.json` if adding a
  committed synthetic fixture is needed.
- Create: `tests/fixtures/replay/mvp3/<asr-synthetic-fixture>.fixture.json`
  only if synthetic/minimal replay coverage is not already sufficient.
- Read: `src/voice_agent/replay/runner.py`
- Read: `docs/specs/replay-spec.md`

### Contract constraints

- Replay uses recorded refs and metadata only.
- Replay rejects ASR output before committed turn.
- Replay rejects mismatched turn/utterance/audio span metadata.
- Replay rejects noncanonical timestamp/streaming status values.
- Replay rejects missing degraded event for unavailable timestamps or final-only
  streaming.
- Replay does not call provider, clocks, random, secret stores, or local audio
  storage.

### Tests / replay fixtures

- Synthetic fixture for successful ASR output with available timestamps and
  streaming support.
- Synthetic fixture or in-memory test for timestamp unavailable degraded path.
- Synthetic fixture or in-memory test for final-only streaming degraded path.
- Negative replay tests for raw payload fields and unsafe statuses.
- Fixture safety checks for no raw audio, raw trace, secret, unredacted real
  input, raw provider response, or raw transcript.

### Definition of done

- Replay covers ASR output causality and degraded status policies.
- Any committed fixture is synthetic/redacted/minimal and GitHub-safe.
- Replay diagnostics record data-plane refs without requiring raw payloads.
- Focused replay tests pass through `./scripts/test`.

### Review checklist

- No provider rerun during replay.
- No real output captured as fixture.
- No local-only artifact path or cache committed.
- Fixture manifest safety flags are correct.
- ASR evidence remains evidence only.

### Suggested goal prompt for that slice

```text
Add deterministic ASR replay and fixture safety coverage. Use synthetic or
in-memory events only. Cover success, timestamp degraded, final-only degraded,
raw payload rejection, and noncanonical status rejection. Replay must not call
providers or require raw audio. Use ./scripts/test for focused replay tests.
```

## Slice 6: live eval approval packet + fail-closed eval command skeleton

### Objective

Add an ASR live eval approval template and a fail-closed command skeleton that
does not call a provider until a complete approval packet exists. The command
should validate bounds, synthetic input policy, output path policy, redaction
policy, and forbidden artifact acknowledgements.

### Non-goals

- No live provider call in this slice.
- No secret read unless the approval parser uses fake placeholders and refuses
  real values.
- No provider SDK.
- No real transport.
- No raw audio fixture committed.

### Likely files

- Create: `docs/implementation/asr-live-eval-approval-template.md`
- Create or modify: `scripts/asr-live-eval` as a fail-closed skeleton.
- Create: `tests/adapters/test_asr_live_eval_approval.py` or
  `tests/scripts/test_asr_live_eval_approval.py`
- Create: `tests/fixtures/synthetic/asr-live-eval-inputs.jsonl` only with
  synthetic metadata refs, not raw audio.

### Contract constraints

- Approval packet must name approval status, approver, approval date, provider
  and model alias, model re-pin date, transport allowance, credential handling,
  max request count, max cost/quota, timeout, retry budget, synthetic input
  set, output storage path, redaction policy, cleanup policy, aggregate metadata
  policy, and forbidden artifact acknowledgement.
- Output storage path must be under ignored local-only paths such as
  `diagnostics/`, `traces/`, `replays/local/`, or `outputs/`.
- The skeleton must fail closed when approval is absent, pending, incomplete,
  over budget, or unsafe.
- The skeleton must not materialize a secret or provider client.

### Tests / replay fixtures

- Tests that missing approval fails closed.
- Tests that `approval_status=pending` fails closed.
- Tests that unsafe output path fails closed.
- Tests that missing budget/timeout/retry fields fail closed.
- Tests that synthetic input metadata with raw audio/transcript/provider markers
  fails closed.
- Tests that a complete fake approval reaches a dry-run "would run" status
  without provider calls.

### Definition of done

- Approval template exists and contains no secret placeholders that invite
  pasting values.
- Command skeleton is dry-run/fail-closed only.
- Tests prove the skeleton cannot run live without complete approval.
- No provider SDK, transport, or secret read is introduced.

### Review checklist

- No real provider call path.
- No real credential read.
- No raw audio committed as synthetic input.
- Output path must be ignored local-only.
- Aggregate metadata policy is explicit.

### Suggested goal prompt for that slice

```text
Add an ASR live eval approval template and fail-closed eval command skeleton.
The skeleton must validate a complete approval packet and safe synthetic inputs
but must not call a provider, read secrets, or add SDKs. It should fail closed
for pending/incomplete/unsafe approval. Use ./scripts/test for focused tests.
```

## Slice 7: gated real transport + metadata-only synthetic live eval

### Objective

After explicit human approval, add a gated ASR real transport behind the adapter
boundary and run a bounded synthetic metadata-only live eval. The live eval must
produce aggregate redacted metadata only and must not connect ASR to business
runtime by default.

### Non-goals

- No broad production runtime integration.
- No business module direct provider import.
- No raw audio, raw transcript, raw provider body, raw trace, diagnostics
  payload, local replay cache, secret, or real user input committed.
- No provider SDK unless the approval packet explicitly permits it.
- No ADR or canonical event change.
- No Router, SlowTask, Tool Executor, Composer, or playback ownership change.

### Likely files

- Create or modify: `src/voice_agent/adapters/asr_transport.py`
- Modify: `scripts/asr-live-eval`
- Create or modify: `tests/adapters/test_asr_transport_safety.py`
- Create: `docs/implementation/asr-live-eval-approval-packet.md` only after
  human approval.
- Create: `docs/implementation/asr-live-eval-closeout.md` with aggregate
  metadata only after the approved run.

### Contract constraints

- Transport must be adapter-internal.
- Business modules must not import provider SDKs, HTTP clients, provider
  response classes, or credential loaders.
- Credential values must be runtime-only and never serialized.
- Provider output must be parsed and normalized before any event emission.
- Malformed output must emit validation failure metadata, not success.
- Timeout/retry/failure/degraded paths must map to existing canonical adapter
  events.
- Valid final transcript output must still go through `AsrAdapterContract`.
- Deterministic replay must continue to use recorded refs and metadata only.

### Tests / replay fixtures

- Provider-free transport safety tests with fake transport and fake credential
  handle.
- Tests that business modules do not import real transport/provider modules.
- Tests that raw provider/request/response/header/secret markers are redacted
  or blocked before summaries.
- Approved live eval may run only after approval packet is complete.
- After live eval, run focused adapter tests and `git status --short --branch`.
- Any committed closeout must include aggregate counts, redacted status
  categories, timeout/retry counts, cleanup status, and forbidden artifact
  absence only.

### Definition of done

- Human-approved packet exists for the exact bounded eval.
- Real transport is adapter-internal and gated.
- Synthetic live eval completes within approved bounds or fails safely.
- Closeout records metadata-only aggregate results.
- No forbidden artifacts are committed.
- Replay and acceptance remain provider-free by default.

### Review checklist

- Approval packet is complete and explicit.
- No SDK unless approved.
- No secret value in code, docs, tests, logs, failure reasons, repr strings, or
  fixtures.
- No raw audio or raw transcript in committed inputs or outputs.
- No provider call from replay, Router, SlowTask, Tool Executor, Composer,
  Talker, or runtime assembly.
- ASR output remains evidence only and enters journal through existing contract
  and callback boundary.

### Suggested goal prompt for that slice

```text
With explicit human approval already recorded in the ASR live eval approval
packet, add a gated adapter-internal ASR real transport and run the bounded
synthetic metadata-only live eval. Do not connect ASR to business runtime by
default. Do not commit raw audio, raw transcript, provider bodies, traces,
replay caches, secrets, or real user input. Use existing canonical events and
AsrAdapterContract only. Use ./scripts/test for focused tests and report
metadata-only closeout.
```
