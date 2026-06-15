# LALM Thinker Implementation Backlog

Status: readiness_backlog_only_no_runtime_approval

Date: 2026-06-12

This backlog decomposes LALM / real Thinker adapter readiness into independent
future PRs or goals. Slice 0 is the current docs-only work. Later slices must
remain provider-free until the explicit live eval approval gate.

## Global constraints

- Do not add canonical events.
- Do not modify ADRs unless a slice discovers a true architecture gap and stops
  for review.
- Do not call a provider, read secrets, or add provider SDKs before the
  approval-gated transport slice.
- Do not implement provider behavior outside adapters.
- Do not write raw provider output, full prompts, provider schemas, raw audio,
  raw traces, local replay cache, secrets, or unredacted real user input into
  the Event Journal, fixtures, tests, docs, or committed diagnostics.
- Thinker output is evidence only, not `SemanticCommitment`.
- Router does not choose ASR/Thinker field winners.
- SlowTask owns ambiguity resolution, plan version, stale evidence, lifecycle,
  confirmation, cancel, and final facts.
- Tool Executor owns tool execution, authorization checks, side effects, UI
  patching, idempotency, and tool result normalization.
- Composer coverage/truthfulness checks and playback approval ownership do not
  move to Thinker or the provider.
- All Python tests must run through `./scripts/test`.

## Slice 0: readiness plan + backlog only

### Objective

Create the LALM Thinker readiness plan and implementation backlog without
runtime code, provider SDKs, provider calls, secret reads, or event changes.

### Non-goals

- No adapter implementation.
- No provider-free skeleton code.
- No tests or fixtures beyond documentation references.
- No cherry-pick of unrelated handoff branch changes.

### Likely files

- Create: `docs/implementation/lalm-thinker-readiness-plan.md`
- Create: `docs/implementation/lalm-thinker-backlog.md`

### Contract constraints

- Current accepted ADRs and current mainline Thinker contract are the authority.
- The handoff is evidence only and does not approve live provider use.
- `.gitignore` must cover local-only artifacts before any future artifact dirs
  are created.

### Tests / replay fixtures

- Run `git diff --check`.
- Full `./scripts/test` is not required for this docs-only slice.

### Definition of done

- Both docs exist and contain no provider payload, prompt dump, secret, raw
  audio, raw trace, local replay cache, or unredacted real input.
- The readiness plan includes Goal, Non-goals, ADR constraints, current
  baseline, handoff summary, provider ownership limits, event mapping,
  capability/profile plan, normalization plan, safe ref/redaction policy,
  replay safety, live eval gate, open questions, and readiness done criteria.
- The backlog contains independently executable future slices.
- `git diff --check` passes.
- Changes are committed.

### Review checklist

- No new canonical event is proposed.
- No live-provider approval is implied.
- No future slice silently moves Router, SlowTask, Tool Executor, Composer,
  checker, or playback ownership.
- `.gitignore` coverage is stated accurately.

### Suggested goal prompt for that slice

```text
Work in the current voice-agent worktree. Create docs-only LALM Thinker
readiness and backlog documents. Do not implement adapter code, add provider
SDKs, call providers, read secrets, modify ADRs, or add canonical events. Run
git diff --check and commit the docs.
```

## Slice 1: provider-free capability/profile builder

### Objective

Add a provider-free LALM Thinker capability/profile builder that can satisfy
existing MVP-3 profile validation while declaring unsupported capabilities
honestly.

### Non-goals

- No provider SDK import.
- No endpoint probe, healthcheck, or network call.
- No credential handling beyond safe placeholder refs.
- No SemanticFrame parsing or contract emission.

### Likely files

- Create: `src/voice_agent/adapters/lalm_thinker_profile.py`
- Create: `tests/adapters/test_lalm_thinker_profile.py`
- Modify only if necessary: `docs/specs/adapter-capability-profiles.md`

### Contract constraints

- Profiles must pass `validate_capability_matrix`.
- Required MVP-3 real readiness must still pass
  `validate_mvp3_adapter_profile_set` without provider probing.
- Endpoint/config values must be safe refs and must fail closed if
  credential-like.
- `supports_structured_json=true` is required for Thinker readiness.
- Optional capabilities that are unproven must be explicit in
  `unsupported_capabilities`.

### Tests / replay fixtures

- Add focused tests for valid synthetic LALM Thinker profile metadata.
- Add negative tests for mock-only, credential-like endpoint/config refs,
  missing required capability fields, unsupported capability list mismatch, and
  false target-architecture claims.
- Run:

```bash
./scripts/test tests/adapters/test_lalm_thinker_profile.py -q
./scripts/test tests/adapters/test_mvp3_adapter_capability_profiles_spec.py -q
```

### Definition of done

- Provider-free LALM Thinker profile metadata builds deterministically.
- No network, provider SDK, clocks, random, or secret access is needed.
- Fallback/degraded profiles are explicit and do not count as real readiness.
- Existing MVP-3 profile tests remain green.

### Review checklist

- Does the profile declare `adapter_type=thinker` and `output_mode` honestly?
- Are unproven semantic close, assistant-directedness, emotion, audio caption,
  streaming input, timestamp, tool calling, and cancellation capabilities
  either proven by tests or marked unsupported/degraded?
- Are endpoint/config refs credential-free?
- Does runtime assembly remain provider-free?

### Suggested goal prompt for that slice

```text
Implement a provider-free LALM Thinker capability/profile builder only. Do not
add provider SDKs, network calls, live eval, adapter runtime behavior, secret
reads, or event changes. Add focused profile tests and run them through
./scripts/test.
```

## Slice 2: request binding + normalized SemanticFrame candidate schema

### Objective

Define provider-free request binding and an adapter-local normalized candidate
schema for LALM Thinker SemanticFrame evidence.

### Non-goals

- No provider client or fake transport.
- No parser/validator implementation beyond schema constants and builder
  shape if a separate parser slice is cleaner.
- No `ThinkerAdapterContract` emission.
- No Router, SlowTask, Tool Executor, Composer, or replay behavior change.

### Likely files

- Create: `src/voice_agent/adapters/lalm_thinker_binding.py`
- Create: `tests/adapters/test_lalm_thinker_binding.py`
- Modify only if necessary: `docs/implementation/lalm-thinker-readiness-plan.md`

### Contract constraints

- Request binding must require a prior `TURN_INGRESS_COMMITTED` event.
- Binding must preserve `turn_id`, `utterance_id`, `input_modality`, and any
  matching `text_span_id` or `audio_span_id`.
- The candidate schema is adapter-local, not a canonical event or downstream
  schema.
- Candidate fields must be evidence-only and must not claim ownership of
  commitment, confirmation, tool authorization, tool execution, playback, or
  checker verdicts.
- Request metadata must use refs and safe policy identifiers, not raw prompts,
  raw audio, provider payloads, or secrets.

### Tests / replay fixtures

- Test successful binding from text and audio committed turns using synthetic
  event metadata.
- Test rejection of non-`TURN_INGRESS_COMMITTED` inputs and mismatched causal
  ids.
- Test that candidate schema constants do not introduce new journal event names.
- Test that request metadata has no forbidden raw/provider/secret field names.
- Run:

```bash
./scripts/test tests/adapters/test_lalm_thinker_binding.py -q
```

### Definition of done

- Binding objects are deterministic, provider-free, and safe to serialize as
  metadata.
- Candidate schema fields are documented in code comments or tests without
  copying full prompts or provider payloads.
- No downstream module consumes candidate payloads directly.

### Review checklist

- Is every request bound to a committed turn?
- Are text/audio span ids preserved only when present in the committed turn?
- Does the schema call Thinker output evidence, not facts or commitments?
- Are forbidden ownership claims impossible or rejected?

### Suggested goal prompt for that slice

```text
Add provider-free LALM Thinker request binding and adapter-local candidate
schema metadata. Do not add transport, provider SDKs, provider calls, secret
reads, contract emission, replay changes, or canonical events. Add focused
tests through ./scripts/test.
```

## Slice 3: parser/validator + fake transport, no network

### Objective

Implement strict parser/validator behavior and a fake transport that returns
synthetic candidate payloads without any provider or network access.

### Non-goals

- No real transport.
- No provider SDK.
- No live eval command.
- No `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` emission yet unless Slice 4
  explicitly folds it in.

### Likely files

- Create: `src/voice_agent/adapters/lalm_thinker_skeleton.py`
- Modify: `src/voice_agent/adapters/lalm_thinker_binding.py`
- Create: `tests/adapters/test_lalm_thinker_skeleton.py`

### Contract constraints

- Parser accepts exactly one candidate object and rejects prose wrappers,
  fenced markdown, multiple objects, arrays, and empty content.
- Validator rejects binding mismatches, unsupported schema versions, forbidden
  ownership claims, provider-native tool execution claims, raw artifact
  retention claims, and unsafe refs.
- Fake transport must be injectable only through adapter-internal test seams.
- Validation failure maps to safe failure categories and refs, not raw payload
  snippets.

### Tests / replay fixtures

- Test strict parsing success and malformed input rejection.
- Test validation success with all optional evidence refs present.
- Test validation success with optional evidence unavailable.
- Test rejection of provider response fields, provider schema fields, raw
  SemanticFrame payload names, raw prompt/payload markers, unsafe refs, and
  ownership claims.
- Monkeypatch network/time/random entry points to prove the fake path does not
  call them.
- Run:

```bash
./scripts/test tests/adapters/test_lalm_thinker_skeleton.py -q
```

### Definition of done

- Fake transport produces only synthetic provider-neutral candidate metadata.
- Parser/validator fail closed and never expose raw candidate bodies in events,
  diagnostics, or assertion messages.
- The validated object is still evidence-only and has not been emitted through
  the main contract.

### Review checklist

- Can malformed or wrapped model text accidentally pass?
- Are raw provider/prompt/tool/audio fields rejected before append?
- Are validation errors safe to commit?
- Is the fake transport impossible for business modules to import as a provider
  client?

### Suggested goal prompt for that slice

```text
Implement a provider-free LALM Thinker parser/validator and fake transport. No
provider SDK, network, live eval, secret read, contract emission, ADR change, or
canonical event change. Add fail-closed tests with ./scripts/test.
```

## Slice 4: contract emission through ThinkerAdapterContract

### Objective

Convert validated LALM Thinker candidate metadata into
`ThinkerAdapterContract.emit_semantic_frame` calls and existing canonical
adapter events.

### Non-goals

- No real provider transport.
- No new event names.
- No Router/SlowTask semantic behavior changes beyond consuming existing event
  refs already supported by mainline.
- No provider output written directly to the Event Journal.

### Likely files

- Modify: `src/voice_agent/adapters/lalm_thinker_skeleton.py`
- Modify: `tests/adapters/test_lalm_thinker_skeleton.py`
- Possibly modify: `tests/adapters/test_mvp3_thinker_adapter_contract.py`
  only for additional integration coverage.

### Contract constraints

- Emit only through `ThinkerAdapterContract`.
- Emit `ADAPTER_OUTPUT_DEGRADED` before
  `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` when optional semantic fields are
  unavailable.
- Preserve caused-by linkage to `TURN_INGRESS_COMMITTED`.
- Preserve `adapter_callback_seq` ownership in `AdapterCallbackAppendBoundary`.
- Use `output_mode=real|fallback|degraded`; no `mock` output mode for the real
  Thinker event.
- `semantic_frame_ref` and `semantic_summary_ref` are required safe refs.

### Tests / replay fixtures

- Test successful all-refs-available emission and replay.
- Test degraded emission for each missing optional capability and replay.
- Test rejection of status/ref mismatch if events are tampered.
- Test Router reference to emitted Thinker event remains metadata-only.
- Test UserPatch evidence pack binds the emitted refs as non-authoritative
  hypothesis.
- Run:

```bash
./scripts/test tests/adapters/test_lalm_thinker_skeleton.py -q
./scripts/test tests/adapters/test_mvp3_thinker_adapter_contract.py -q
```

### Definition of done

- Validated fake LALM Thinker candidates can produce canonical contract events.
- Replay passes for safe success/degraded paths and fails for tampered unsafe
  paths.
- No provider-specific schema or raw payload reaches Router, UserPatch,
  SlowTask, or replay fixtures.

### Review checklist

- Are degraded events paired with missing optional statuses?
- Does the Thinker event match the committed turn?
- Does Router only reference `thinker_frame_event_id`?
- Does UserPatch provenance match the referenced Thinker event refs?

### Suggested goal prompt for that slice

```text
Wire validated provider-free LALM Thinker candidate metadata into
ThinkerAdapterContract emission only. Keep fake transport only; no provider SDK,
network, secret reads, new events, ADR changes, or ownership changes. Add replay
coverage and run tests through ./scripts/test.
```

## Slice 5: replay / fixture safety coverage

### Objective

Harden replay and fixture safety for LALM Thinker-specific leak, tamper, and
stale/ref mismatch cases using synthetic fixtures only.

### Non-goals

- No provider SDK or live eval.
- No raw provider trace-derived fixture.
- No new replay mode that calls providers.
- No change to accepted canonical event names.

### Likely files

- Create: `tests/fixtures/replay/mvp3/lalm-thinker/README.md`
- Create synthetic fixtures under `tests/fixtures/replay/mvp3/lalm-thinker/`
- Create or modify: `tests/adapters/test_lalm_thinker_replay_safety.py`
- Modify only if needed: `src/voice_agent/replay/runner.py`

### Contract constraints

- Replay consumes safe refs and recorded metadata only.
- Fixture manifests must declare GitHub-safe content.
- Forbidden fields include raw audio, audio bytes, raw trace, raw Thinker
  output, provider response, provider payload, provider schema,
  provider-specific schema, raw semantic frame, raw semantic summary,
  direct semantic field payloads, raw prompt markers, and unsafe refs.
- UserPatch Thinker hypotheses must match referenced Thinker event refs.

### Tests / replay fixtures

- Success fixture with all optional refs available.
- Degraded fixture with all optional refs unavailable and matching degraded
  events.
- Negative fixtures for invalid `output_mode`, invalid optional status enums,
  available-without-ref, unavailable-with-ref, missing degraded event, raw
  payload fields, provider schema fields, unsafe refs, Router non-prior Thinker
  refs, UserPatch stale `semantic_summary_ref`, and nested provider metadata
  leakage.
- Run:

```bash
./scripts/test tests/adapters/test_lalm_thinker_replay_safety.py -q
./scripts/test tests/adapters/test_mvp3_thinker_adapter_contract.py -q
```

### Definition of done

- LALM Thinker fixtures are synthetic/minimal and replay deterministically.
- Replay rejects provider/raw/unsafe leakage, including nested cases if this
  slice adds that coverage.
- Replay never calls provider, reads credentials, or requires raw audio.

### Review checklist

- Are all fixtures GitHub-safe by manifest and content?
- Do negative fixtures fail for the intended reason?
- Are fixture refs synthetic and provider-neutral?
- Did any replay validation change weaken existing ASR, Slow LLM, or TTS
  contracts?

### Suggested goal prompt for that slice

```text
Add synthetic LALM Thinker replay and fixture safety coverage. Do not add
provider SDKs, provider calls, secret reads, raw trace/audio fixtures, new
events, or runtime adapter behavior. Use ./scripts/test for focused replay
tests.
```

## Slice 6: live eval approval packet + fail-closed eval command skeleton

### Objective

Create a live eval approval packet template and a command skeleton that fails
closed unless explicit approval metadata is present.

### Non-goals

- No actual provider call.
- No credential read.
- No provider SDK.
- No live eval output generation.
- No adapter runtime selection for production.

### Likely files

- Create: `docs/implementation/lalm-thinker-live-eval-approval-template.md`
- Create: `scripts/lalm-thinker-live-eval`
- Create: `tests/adapters/test_lalm_thinker_live_eval_gate.py`
- Modify: `.gitignore` only if a new local-only output directory is introduced.

### Contract constraints

- The command must fail closed by default.
- Approval packet must name provider/model alias, synthetic input set, cost and
  quota budget, timeout/retry limits, output location, cleanup policy, and
  redaction policy.
- Command must refuse to run if output location is not local-only ignored or
  explicitly metadata-only and repo-safe.
- Command must not read environment secrets in this slice.
- Approval packet must state that raw provider bodies, prompts, raw audio,
  traces, replay cache, secrets, and real user inputs are not retained.

### Tests / replay fixtures

- Test command/help path is available without provider SDK.
- Test missing approval fails closed.
- Test malformed approval fails closed.
- Test output directory safety checks reject non-ignored local-only paths if a
  local output path is configured.
- Run:

```bash
./scripts/test tests/adapters/test_lalm_thinker_live_eval_gate.py -q
```

### Definition of done

- The eval command cannot reach a provider.
- Approval template is explicit enough for human review.
- Failure messages are safe and contain no secret names or raw payloads.
- Any new local-only output path is ignored before use.

### Review checklist

- Can the command accidentally run without approval?
- Does the skeleton import provider SDKs or read secrets?
- Does the approval packet authorize only synthetic metadata eval?
- Are local-only artifacts ignored before any future generation?

### Suggested goal prompt for that slice

```text
Create a LALM Thinker live eval approval template and fail-closed command
skeleton only. Do not call providers, read secrets, add provider SDKs, emit
runtime adapter events, or create live outputs. Add gate tests via
./scripts/test.
```

## Slice 7: gated real transport + metadata-only synthetic live eval

### Objective

After explicit approval, add adapter-internal gated real transport for a
synthetic metadata-only live eval and convert observations into redacted
aggregate summaries or synthetic fixtures only.

### Non-goals

- No production traffic.
- No real user input.
- No raw provider body retention.
- No provider output directly in Event Journal.
- No external side-effect tools.
- No new canonical events or architecture capability.
- No broad runtime default switch to live provider behavior.

### Likely files

- Modify: `src/voice_agent/adapters/lalm_thinker_skeleton.py`
- Create or modify: `src/voice_agent/adapters/lalm_thinker_transport.py`
- Modify: `scripts/lalm-thinker-live-eval`
- Create: `docs/implementation/lalm-thinker-live-eval-closeout.md`
- Modify or create focused tests under `tests/adapters/`

### Contract constraints

- Real transport is adapter-internal.
- Credentials are runtime-only opaque handles and must never appear in profiles,
  events, refs, exceptions, repr strings, diagnostics, fixtures, or docs.
- Provider request/response bodies are transient and must be discarded after
  parser/validator processing.
- Valid output still emits only normalized refs through
  `ThinkerAdapterContract`.
- Invalid output emits existing validation/failure/degraded metadata only.
- Replay of live-derived fixtures remains provider-free and synthetic/redacted.

### Tests / replay fixtures

- Provider-client boundary tests with fake credentials and fake transport.
- Secret non-serialization tests for events, exceptions, repr strings,
  diagnostics, and fixture summaries.
- Approved-command tests that use fake transport by default.
- Optional live eval run only after explicit human approval, using synthetic
  inputs and metadata-only outputs.
- Replay tests for synthetic fixtures derived from normalized metadata, never
  raw provider traces.
- Run focused tests before any approved eval:

```bash
./scripts/test tests/adapters/test_lalm_thinker_skeleton.py -q
./scripts/test tests/adapters/test_lalm_thinker_live_eval_gate.py -q
./scripts/test tests/adapters/test_mvp3_thinker_adapter_contract.py -q
```

### Definition of done

- Human approval packet is present and matches the command invocation.
- Real transport is unreachable without approval and runtime credential handle.
- Live eval uses synthetic inputs only.
- Output artifacts contain only aggregate metadata and safe refs.
- No raw provider body, full prompt, raw audio, raw trace, local replay cache,
  secret, or real user input is retained or committed.
- Closeout records provider alias, approval scope, commands run, metadata-only
  results, cleanup, and residual risks.

### Review checklist

- Is the provider client imported only by adapter-internal code?
- Are credentials never serialized, logged, or embedded in refs?
- Does live output stay metadata-only?
- Does replay remain deterministic and provider-free?
- Does the PR avoid defaulting production/runtime assembly to the live provider?
- Are all live eval artifacts either ignored local-only files or safe committed
  summaries?

### Suggested goal prompt for that slice

```text
After explicit human approval, implement gated adapter-internal LALM Thinker
real transport for synthetic metadata-only live eval. Do not change canonical
events, ownership boundaries, production defaults, or replay provider-free
behavior. Do not retain raw provider bodies, prompts, raw audio, traces, replay
cache, secrets, or real user input. Use ./scripts/test before any approved eval.
```
