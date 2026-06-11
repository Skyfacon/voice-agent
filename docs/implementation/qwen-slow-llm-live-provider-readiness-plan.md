# Qwen Slow LLM Live Provider Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare Qwen Slow LLM for a separately approved live-provider
integration without weakening MVP-3 adapter, trace, replay, SlowTask, or
secret-safety boundaries.

**Architecture:** Qwen remains a Slow LLM adapter-internal provider only.
Business modules may consume only validated normalized metadata emitted through
`SlowLLMStructuredOutputContract` and `AdapterCallbackAppendBoundary`; they may
not see provider SDK objects, request bodies, response bodies, headers, API
keys, cookies, tokens, or provider-specific schemas.

**Tech Stack:** Python control plane, existing adapter capability/profile
validators, existing Slow LLM structured output contract, existing adapter
callback append boundary, existing canonical adapter events, and
`./scripts/test` as the only Python test entrypoint.

---

## Scope

This plan is a post-MVP3 readiness plan. It does not approve live provider
execution by itself.

Allowed future implementation scope:

- Adapter-internal Qwen Slow LLM credential handle validation.
- Adapter-internal provider request construction and response parsing.
- Timeout, retry, request failure, validation failure, and degraded metadata
  mapped to existing canonical adapter events.
- Synthetic-only live eval harness after explicit human approval.
- Synthetic/redacted/minimal replay fixtures derived from normalized metadata
  only, never from raw provider traces.

Explicit non-goals:

- No DashScope/Qwen connection while writing this plan.
- No provider SDK import while writing this plan.
- No secret, token, cookie, credential, or environment secret read while
  writing this plan.
- No live eval while writing this plan.
- No new canonical event name.
- No ADR or spec modification unless a later slice identifies a concrete
  architecture or responsibility-boundary gap and pauses for approval.
- No Tool Executor, Composer, Checker, Playback, frontend, Router, or SlowTask
  ownership change.

## Current No-Live Skeleton Boundaries

The committed Qwen Slow LLM skeleton currently provides these provider-free
boundaries:

- `build_qwen_slow_llm_capability()` builds credential-free real-mode metadata
  for `adapter_type=slow_llm` without probing a provider.
- `QwenSlowLLMRequestBinding` binds `task_id`, `plan_version`,
  `observed_plan_version`, `interpreted_against_plan_version`,
  `task_event_seq`, `adapter_request_id`, and causal refs.
- `build_qwen_slow_llm_request_payload()` preserves task evidence refs and
  `UNTRUSTED_WEB_EVIDENCE` as evidence only, not instructions.
- `parse_qwen_slow_llm_evidence_json()` accepts exactly one JSON object and
  rejects prose wrappers, fenced markdown, and multiple objects.
- `validate_qwen_slow_llm_evidence()` requires the adapter-local
  `slow_llm_qwen_evidence_v1` schema, rejects binding mismatch, rejects
  boundary assertion failures, rejects ownership claims, rejects raw artifact
  retention, and marks validated output as evidence that may not advance the
  current task directly.
- `decide_qwen_slow_llm_repair()` models bounded local repair metadata with
  `max_repair_attempts=2`; it does not call a provider, construct raw prompts,
  or retain raw provider bodies.
- `classify_qwen_slow_llm_arrival()` classifies current, stale, terminal-late,
  and task-mismatch arrivals as metadata only.
- `emit_qwen_slow_llm_structured_output()` emits
  `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED` only after validation and only through
  `SlowLLMStructuredOutputContract`.

Current skeleton tests cover capability metadata, request evidence boundary,
strict parsing, validation failure mapping, bounded repair metadata, unsafe
payload rejection, forbidden ownership rejection, stale arrival classification,
and successful validated-only contract emission.

## Readiness Gates Before Any Live Provider Call

Live-provider work must not begin until all gates below pass with provider-free
tests:

1. **Credential handle gate:** Runtime code can accept an opaque credential
   handle or secret provider object without materializing the secret into
   profile metadata, event payloads, exception messages, failure reasons,
   repr strings, fixtures, or diagnostics.
2. **Provider client placement gate:** Only Qwen Slow LLM adapter-internal code
   may build provider requests or call the provider. SlowTask, Tool Executor,
   Composer, Checker, Playback, Router, replay, and runtime assembly may not
   import or call the provider client.
3. **Raw body retention gate:** Tests prove raw request bodies, raw response
   bodies, headers, provider SDK objects, cookies, bearer values, API keys,
   authorization values, diagnostics paths, traces paths, and replay cache paths
   are rejected before event or fixture exposure.
4. **Timeout/retry/failure gate:** Provider-independent fake transport tests
   map timeout and request failures to existing canonical adapter events only.
5. **Validation failure gate:** Malformed provider text maps to
   `ADAPTER_OUTPUT_VALIDATION_FAILED` and never emits
   `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED`.
6. **Degraded/fallback gate:** Unsupported or exhausted paths emit existing
   degraded/failure metadata and do not advance SlowTask state.
7. **Replay gate:** Recorded replay consumes safe refs and metadata only; replay
   does not call a provider, read credentials, inspect env secrets, or require
   raw provider output.
8. **Live eval approval gate:** A human must approve model alias, quota/cost,
   timeout limits, synthetic input set, output location, redaction policy, and
   cleanup policy before any live eval command exists or runs.

## Credential Injection Requirements

The credential path must be runtime-only and adapter-internal.

Requirements:

- Credentials must not be declared in capability profiles, endpoint refs,
  config refs, adapter events, replay fixtures, diagnostics, failure reasons,
  repr strings, snapshots, or logs.
- Tests must use fake credential handles, not real environment variables or
  real secret stores.
- The provider client may accept an opaque value only at call time, after all
  provider-free readiness gates pass.
- The first credential implementation must not read `os.environ` directly from
  business modules or shared runtime assembly.
- If environment-variable based local development is later approved, the read
  must happen in a small adapter-internal secret boundary with tests proving the
  value is never serialized.
- Any caught exception that may contain provider request metadata must be
  converted to safe failure categories before entering `failure_reasons`.

## Provider Client Boundary

The provider client may exist only behind the Qwen Slow LLM adapter boundary.

Allowed imports in business modules:

- `voice_agent.adapters.qwen_slow_llm_skeleton`
- Provider-neutral adapter contract classes.
- Provider-neutral capability/profile/runtime assembly helpers.

Forbidden imports in business modules:

- DashScope/Qwen provider SDK modules.
- HTTP transport modules dedicated to Qwen calls.
- Provider request/response classes.
- Credential loader modules that can return raw secret values.

Allowed provider-client output:

- A transient text candidate passed immediately to
  `parse_qwen_slow_llm_evidence_json()`.
- Safe request metadata such as adapter request id, output mode, retry count,
  timeout class, and redacted failure category.

Forbidden provider-client output:

- Raw provider request body.
- Raw provider response body.
- Raw headers.
- Provider SDK response object.
- Provider-specific tool-call schema.
- Secret-bearing endpoint or config values.

## Raw Provider Body Policy

Raw provider request and response bodies are local transient data only. They are
not repository artifacts and must not survive adapter call processing.

Forbidden storage targets:

- Event Journal payloads.
- Replay fixtures.
- `diagnostics/`.
- `traces/`.
- `replays/local/`.
- `audio/raw/`.
- Test golden files.
- Failure reasons.
- Debug logs committed to GitHub.

Allowed stored artifacts:

- Synthetic input fixtures that contain no real user input and no raw provider
  body.
- Redacted/minimal metadata fixtures with safe refs only.
- Aggregate live eval summaries such as counts, statuses, latency buckets, and
  redacted failure categories.

Required rejection markers include:

- `raw_provider_body`
- `raw_provider_request`
- `raw_provider_response`
- `raw_request_body`
- `raw_response_body`
- `raw_audio`
- `traces/`
- `diagnostics/`
- `replays/local`
- `api_key=`
- `authorization=`
- `Bearer`
- `token=`
- `password=`

## Canonical Event Mapping

No new canonical event names are needed for the next Qwen Slow LLM live-provider
readiness work. Future implementation must use only these existing events:

| Condition | Event |
| --- | --- |
| Retryable timeout or retryable provider failure | `ADAPTER_REQUEST_RETRYING` |
| Final timeout or final request failure | `ADAPTER_REQUEST_FAILED` |
| Provider text cannot parse or validate as Qwen evidence | `ADAPTER_OUTPUT_VALIDATION_FAILED` |
| Capability unsupported, fallback selected, or degraded behavior used | `ADAPTER_OUTPUT_DEGRADED` |
| Validated normalized Slow LLM refs are ready | `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED` |

Event rules:

- `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED` must be caused by an allowed SlowTask
  event: `PLANNING_STARTED`, `PLANNING_RESTARTED`, `EVIDENCE_REVIEWED`, or
  `AMBIGUITY_RESOLVED`.
- Adapter events must enter the journal through `AdapterCallbackAppendBoundary`.
- Adapter callback callers must not allocate `adapter_callback_seq`.
- `ADAPTER_OUTPUT_VALIDATION_FAILED.failure_reasons` must contain safe,
  redacted categories only.
- `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED` must contain safe refs only:
  `slow_llm_output_ref`, `structured_output_ref`, and `validation_result_ref`.
- Old-plan or terminal-late output may be recorded as safe metadata or stale
  evidence by SlowTask policy, but it must not advance the current task without
  explicit SlowTask adopt/rebase.

## Synthetic-Only Live Eval Approval Criteria

No live eval may run until a human approves a written eval packet containing:

- Qwen/DashScope model alias and re-pin date.
- Provider endpoint class and whether a provider SDK or direct HTTP transport
  is allowed.
- Credential source and local-only handling instructions.
- Maximum request count.
- Maximum cost or quota.
- Per-request timeout.
- Retry budget.
- Synthetic input set path.
- Output storage path under ignored local-only directories.
- Redaction policy.
- Cleanup policy.
- Whether aggregate metadata may be committed.
- Explicit statement that raw provider request/response bodies, raw trace,
  raw audio, generated audio, local replay cache, secrets, real user input, and
  large raw web content must not be committed.

The live eval runner must fail closed if any approval field is absent.

## Slice Plan

### Slice 0: Document And Baseline Lock

**Goal:** Preserve the no-live skeleton as the baseline for future provider
work.

**Files:**

- Create:
  `docs/implementation/qwen-slow-llm-live-provider-readiness-plan.md`
- Read:
  `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`
- Read:
  `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`

- [ ] Run baseline status.

  ```bash
  git status --short --branch
  ```

  Expected: branch is `codex/qwen-slow-llm-adapter-skeleton`; any changes are
  limited to this plan document.

- [ ] Run baseline tests.

  ```bash
  ./scripts/test -q
  ```

  Expected: all tests pass.

- [ ] Commit the plan document only after review.

  ```bash
  git add docs/implementation/qwen-slow-llm-live-provider-readiness-plan.md
  git commit -m "Document Qwen slow LLM live provider readiness plan"
  ```

### Slice 1: Credential Handle Readiness Gate

**Goal:** Add provider-free tests proving credential handles cannot leak into
events, failure reasons, repr strings, or fixtures.

**Files:**

- Modify: `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`
- Modify: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`

- [ ] Write failing tests for a fake credential handle object.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ```

  Expected before implementation: tests fail because no credential handle
  boundary exists.

- [ ] Implement the smallest adapter-local credential boundary.

  Required behavior:

  - accepts fake credential handles in tests;
  - refuses string serialization;
  - never includes credential values in metadata;
  - does not read `os.environ`;
  - does not import provider SDKs.

- [ ] Run focused and full tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test -q
  ```

  Expected: all tests pass.

### Slice 2: Provider Client Placement Gate

**Goal:** Create a provider-client interface shape that is adapter-internal and
provider-free.

**Files:**

- Modify: `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`
- Modify: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`

- [ ] Write failing tests that inspect imports and call boundaries.

  Required assertions:

  - business modules do not import Qwen transport code;
  - fake transport can be injected only through adapter-internal functions;
  - provider client returns transient text only, not provider objects.

- [ ] Implement a fake transport protocol with no network behavior.

  The fake transport is a test seam for later provider code; it must not open
  sockets, read credentials, or persist raw bodies.

- [ ] Run tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test -q
  ```

### Slice 3: Raw Body And Secret Safety Gate

**Goal:** Prove provider-like payloads cannot enter adapter events, fixtures, or
validation failure metadata.

**Files:**

- Modify: `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`
- Modify: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`
- Optionally modify replay safety tests only if a provider-like fixture safety
  test is needed: `tests/replay/test_fixture_safety.py`

- [ ] Write failing tests for raw request and raw response retention markers.

  Required markers:

  - `raw_provider_request`
  - `raw_provider_response`
  - `raw_request_body`
  - `raw_response_body`
  - `headers`
  - `authorization=`
  - `Bearer`
  - `api_key=`
  - `token=`
  - `password=`

- [ ] Implement or reuse fail-closed validators.

  Required behavior: unsafe values become safe failure categories or blocked
  writes, never serialized raw values.

- [ ] Run tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test tests/replay -q
  ./scripts/test -q
  ```

### Slice 4: Timeout, Retry, Failure, And Degraded Mapping

**Goal:** Map fake transport timeout/failure/degraded paths to existing
canonical adapter events through the append boundary.

**Files:**

- Modify: `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`
- Modify: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`

- [ ] Write failing tests for fake retryable timeout.

  Expected event: `ADAPTER_REQUEST_RETRYING`.

- [ ] Write failing tests for final fake request failure.

  Expected event: `ADAPTER_REQUEST_FAILED`.

- [ ] Write failing tests for degraded fallback metadata.

  Expected event: `ADAPTER_OUTPUT_DEGRADED`.

- [ ] Implement minimal event mapping with existing canonical events only.

  Required behavior:

  - no raw request/response body in event payloads;
  - no provider SDK objects in event payloads;
  - no new event names;
  - `adapter_callback_seq` allocated only by
    `AdapterCallbackAppendBoundary`.

- [ ] Run tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test tests/events -q
  ./scripts/test -q
  ```

### Slice 5: Provider Text Normalization Gate

**Goal:** Convert fake provider text into validated Qwen evidence and then into
safe Slow LLM structured-output refs.

**Files:**

- Modify: `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`
- Modify: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`

- [ ] Write failing tests for fake valid provider text.

  Expected path:

  1. parse exactly one JSON object;
  2. validate `slow_llm_qwen_evidence_v1`;
  3. build safe refs;
  4. emit `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED` through the contract.

- [ ] Write failing tests for fake malformed provider text.

  Expected path: `ADAPTER_OUTPUT_VALIDATION_FAILED` only.

- [ ] Implement minimal normalization orchestration.

  Required behavior: Qwen output remains evidence candidate only and may not
  authorize tools, patch UI, emit SemanticCommitment, emit SpokenPlan, emit
  checker verdicts, or trigger playback.

- [ ] Run tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test tests/adapters/test_mvp3_slow_llm_structured_output.py -q
  ./scripts/test -q
  ```

### Slice 6: Stale, Terminal, And Task-Mismatch Live Arrival Gate

**Goal:** Ensure delayed provider output cannot advance stale, terminal, or
wrong-task SlowTask state.

**Files:**

- Modify: `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`
- Modify: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`
- Optionally modify replay tests if a deterministic stale fixture is added:
  `tests/replay/`

- [ ] Write failing tests for old `plan_version`.

  Expected classification: `stale_old_plan_evidence`.

- [ ] Write failing tests for terminal task.

  Expected classification: `terminal_task_late_evidence`.

- [ ] Write failing tests for task mismatch.

  Expected classification: `task_mismatch_ignored`.

- [ ] Implement any missing metadata plumbing.

  Required behavior: only SlowTask can explicitly adopt/rebase stale evidence.

- [ ] Run tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test tests/replay -q
  ./scripts/test -q
  ```

### Slice 7: Synthetic Live Eval Approval Packet

**Goal:** Add an approval packet template and provider-free validation for a
future synthetic-only live eval.

**Files:**

- Create or modify:
  `docs/implementation/qwen-slow-llm-live-provider-eval-approval-template.md`
- Create or modify a provider-free test file only if the template is parsed by
  code: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`

- [ ] Write template text with all required approval fields.

  Required fields:

  - model alias and re-pin date;
  - provider transport allowance;
  - credential source;
  - request count;
  - cost/quota cap;
  - timeout;
  - retry budget;
  - synthetic input path;
  - output path;
  - redaction policy;
  - cleanup policy;
  - commit policy for aggregate metadata.

- [ ] Add parser/validation tests only if automation is introduced.

  Expected behavior: missing fields fail closed before any live eval command can
  run.

- [ ] Run tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test -q
  ```

### Slice 8: Separately Approved Live Provider Implementation

**Goal:** Implement the first real provider call only after Slice 1-7 pass and
human approval is recorded.

**Files:**

- Modify: `src/voice_agent/adapters/qwen_slow_llm_skeleton.py`, or split an
  adapter-internal module under `src/voice_agent/adapters/` if the file becomes
  too large.
- Modify: `tests/adapters/test_qwen_slow_llm_adapter_skeleton.py`
- Add ignored local artifacts only after checking `.gitignore`.

- [ ] Confirm approval packet exists and is complete.

  Do not proceed if any approval field is missing.

- [ ] Write failing provider-client tests with fake transport first.

  Expected: provider code path is exercised without network.

- [ ] Implement real transport behind the fake transport interface.

  Required behavior:

  - credential is provided only at call time;
  - timeout is explicit;
  - retry budget is explicit;
  - raw request/response bodies are not retained;
  - response text goes immediately into parser/validator;
  - failure paths map to existing canonical events.

- [ ] Run provider-free tests.

  ```bash
  ./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
  ./scripts/test -q
  ```

- [ ] Run live eval only with explicit human approval.

  The live eval command must not be added or run before approval.

## ADR And Spec Change Stop Conditions

Pause and request explicit human confirmation before changing `docs/adr/` or
`docs/specs/` if any future slice requires:

- a new canonical event name;
- a changed owner for SlowTask state, Tool Executor authorization, Composer,
  Checker, Playback, Router, or Event Journal append;
- direct provider calls outside adapters;
- a new task state, Router decision, TaskFocus value, or multi-active-SlowTask
  behavior;
- real external side-effect tools;
- production privacy or retention policy beyond the existing MVP rules;
- replay that calls providers, reads secrets, uses clocks/random/network, or
  consumes raw provider output;
- raw provider body retention for debugging;
- provider-native tool execution authority;
- a credential policy that serializes secrets into repo, trace, fixture,
  diagnostics, or event payloads.

At the time this plan is written, the next Qwen Slow LLM readiness work does
not require ADR or spec changes because existing ADR-002, ADR-004, ADR-011,
ADR-014, ADR-015, ADR-016, and MVP-3 specs already cover adapter boundaries,
canonical events, trace safety, stale policy, and no-direct-provider rules.

## Verification Matrix

Every future slice must use `./scripts/test`; direct `pytest` and dependency
auto-install attempts are not allowed.

Minimum commands by phase:

| Phase | Command |
| --- | --- |
| Qwen adapter focused tests | `./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q` |
| Slow LLM contract integration | `./scripts/test tests/adapters/test_mvp3_slow_llm_structured_output.py -q` |
| Adapter suite | `./scripts/test tests/adapters -q` |
| Replay safety | `./scripts/test tests/replay -q` |
| Event boundary safety | `./scripts/test tests/events -q` |
| Final verification | `./scripts/test -q` |

Completion evidence for each slice must include:

- changed files;
- focused test result;
- full test result;
- `git status --short --branch`;
- explicit statement that no unapproved live provider call ran;
- explicit statement that no secret was read or stored;
- explicit statement that no canonical event name was added.
