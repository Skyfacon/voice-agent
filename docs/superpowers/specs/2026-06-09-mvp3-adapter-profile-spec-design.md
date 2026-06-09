# MVP3 Adapter Profile Spec Design

**Goal:** Define the MVP3-0 adapter profile specification and contract tests so real adapter selection can start without provider-specific behavior leaking into runtime modules.

**Architecture:** MVP3-0 extends the existing adapter capability contract with provider-agnostic profile templates for ASR, Thinker, Slow LLM, and TTS. The profiles feed the already-merged runtime assembly gate and remain metadata-only: no provider probe, no API call, no secret-bearing endpoint, and no real adapter implementation.

**Tech Stack:** Python package under `src/voice_agent`, pytest through `./scripts/test`, Markdown specs under `docs/specs`.

**Slice status:** This design is now MVP-3 Slice 1. It should be implemented after the MVP-3 Slice 0 fixture/replay safety skeleton in `docs/implementation/mvp3-backlog.md`.

---

## Scope

MVP3-0 creates a profile spec and tests for capability profile examples. It does not connect any provider SDK, does not add endpoint credentials, does not create a frontend, and does not change SlowTask, Tool Executor, Composer, or replay runtime behavior.

The implementation should create `docs/specs/adapter-capability-profiles.md` and add tests under `tests/adapters/` that validate representative profile dictionaries against the current adapter capability validator and MVP3 runtime assembly gate.

## Components

### Adapter Profile Spec

`docs/specs/adapter-capability-profiles.md` should define profile templates for:

- ASR adapter
- Thinker adapter
- Slow LLM adapter
- TTS adapter

Each template must specify required identity fields, required capabilities, optional capabilities, unsupported capability handling, output mode rules, config reference rules, endpoint reference rules, and degraded/fallback behavior.

### Profile Examples

The tests should include synthetic provider-agnostic examples for the four required adapter types. These examples are not real providers. They must use safe refs such as `endpoint://synthetic/mvp3/asr` and `config://synthetic/mvp3/asr`, and they must not include API keys, bearer tokens, request headers, cookies, or raw provider URLs containing credentials.

### Contract Tests

The tests should verify:

- all four required adapter types are represented;
- examples pass `validate_capability_matrix`;
- examples pass `validate_mvp3_adapter_profile_set`;
- examples pass `assemble_runtime_adapters(stage="mvp3", ...)`;
- mock-only profiles are still rejected by the MVP3 gate;
- missing required capabilities fail with clear errors;
- credential-like endpoint/config refs fail before any trace exposure;
- fallback/degraded examples are allowed as explicit profiles but do not count as required real profiles.

## Data Flow

Profile examples are plain metadata dictionaries or `AdapterCapability` instances. Test code sends them through:

1. `validate_capability_matrix`
2. `validate_mvp3_adapter_profile_set`
3. `assemble_runtime_adapters`

The resulting capability snapshot must contain adapter ids, adapter types, deployment modes, output modes, and capability version. No test or spec step should perform network calls, provider healthchecks, filesystem secret reads, or replay execution.

## Error Handling

MVP3-0 should fail closed. Missing required profiles, mock-labeled real profiles, credential-like refs, missing required capabilities, unknown fields, and unsupported capability contradictions must raise validation errors.

Fallback and degraded modes are explicit metadata states. They are allowed as profile examples only when `output_mode` is `fallback` or `degraded`, the capability gap is documented, and the profile is not counted toward the MVP3 required real adapter set.

## Testing

Use `./scripts/test` as the canonical command. Targeted tests should live under `tests/adapters/` and should not require network access or dependency installation.

The implementation is complete when:

- `docs/specs/adapter-capability-profiles.md` exists and aligns with `docs/specs/model-adapter-capabilities.md`;
- synthetic ASR, Thinker, Slow LLM, and TTS profile examples pass the current MVP3 gates;
- negative cases prove mock-only, missing-capability, credential-like, and unsupported-capability profiles fail closed;
- full `./scripts/test -q` passes.

## Non-Goals

- No real ASR, Thinker, Slow LLM, or TTS provider integration.
- No provider SDK dependency.
- No HTTP/WebSocket runtime.
- No API key, token, cookie, authorization header, or credential handling.
- No changes to Tool Executor, demo backend, frontend, SlowTask lifecycle, Composer behavior, or replay runner behavior.

## Suggested Implementation Order

1. Write failing adapter profile spec tests under `tests/adapters/`.
2. Add `docs/specs/adapter-capability-profiles.md` with provider-agnostic profile templates and examples.
3. Reuse existing `validate_capability_matrix`, `validate_mvp3_adapter_profile_set`, and `assemble_runtime_adapters`; change production code only if tests expose a genuine contract gap.
4. Run targeted adapter tests.
5. Run full `./scripts/test -q`.
