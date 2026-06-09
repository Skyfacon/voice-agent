# Adapter Capability Profiles

Source of truth: ADR-011, ADR-012, ADR-015,
`docs/specs/model-adapter-capabilities.md`, and the MVP-3 readiness gates in
`src/voice_agent/adapters/profiles.py`.

This document defines the provider-agnostic MVP-3 Slice 1 profile contract for
ASR, Thinker, Slow LLM, and TTS adapters. Profiles are metadata only. They let
runtime assembly validate a capability snapshot before any real provider
integration exists.

## Purpose

MVP-3 replaces selected mock model adapters with real adapter behavior behind
existing adapter boundaries. Slice 1 does not select providers or call them; it
defines the profile shape future provider-backed adapters must satisfy.

The profile examples for this slice are synthetic and provider agnostic. Safe
refs look like `endpoint://synthetic/mvp3/asr` and
`config://synthetic/mvp3/asr`.

## Non-Goals

- No provider SDK dependency.
- No provider endpoint probe, healthcheck, or network call.
- No secret, cookie, credential, bearer value, or authorization header.
- No direct external model call outside adapters.
- No Tool Executor, SlowTask, Composer, frontend, or replay runtime behavior
  change.
- No real external side-effect tool.

## Common Profile Rules

Every profile must pass `validate_capability_matrix`.

MVP-3 runtime readiness must pass `validate_mvp3_adapter_profile_set` before
`assemble_runtime_adapters(stage="mvp3", ...)` builds the runtime capability
snapshot.

Every profile declares:

- identity fields from `docs/specs/model-adapter-capabilities.md`, including
  `adapter_id`, `adapter_type`, `provider`, `model_name`, `deployment_mode`,
  `endpoint`, `config_ref`, `capability_version`, policy refs, and
  `output_mode`;
- all required boolean capability fields;
- all required numeric capability fields;
- `mocked`, `mock_profile_ref`, `target_architecture_validation`, and
  `unsupported_capabilities`.

`output_mode` must be one of `real`, `mock`, `fallback`, or `degraded`.
MVP-3 required readiness counts only `output_mode=real` profiles for the
required adapter types `asr`, `thinker`, `slow_llm`, and `tts`.

For required real readiness, a profile must not use `provider=mock`,
`deployment_mode=mock`, a `mock://` endpoint, `mocked=true`, or
`mock_profile_ref`. It must declare `target_architecture_validation=true`.

Endpoint and config values must be safe refs, not credential-bearing URLs or
inline provider configuration. Credential-like refs fail closed before runtime
assembly and before trace exposure.

## Required MVP-3 Real Profiles

| adapter_type | Minimum required capabilities | Notes |
| --- | --- | --- |
| `asr` | `supports_audio_input`, `supports_structured_json` | Final transcript or equivalent text projection is sufficient for MVP-3. |
| `thinker` | `supports_structured_json` | Basic SemanticFrame-compatible output is sufficient; missing semantic close, directedness, emotion, or audio caption must degrade explicitly when required. |
| `slow_llm` | `supports_structured_json` | Structured SlowTask output must be schema-validated before downstream use. |
| `tts` | `supports_audio_output`, `supports_tts` | Basic audio synthesis is sufficient; missing truncate support must block or degrade barge-in target validation explicitly. |

## ASR Profile Template

The ASR profile uses `adapter_type=asr` and `output_mode=real` for MVP-3
required readiness. It must support audio input and structured JSON output for
a final transcript or equivalent text projection.

Allowed gaps for Slice 1 synthetic examples include streaming input, streaming
output, audio timestamps, emotion, audio caption, cancellation, and
assistant-directedness, but every unsupported boolean capability must be named
in `unsupported_capabilities`.

Safe refs:

- `endpoint://synthetic/mvp3/asr`
- `config://synthetic/mvp3/asr`

## Thinker Profile Template

The Thinker profile uses `adapter_type=thinker` and `output_mode=real` for
MVP-3 required readiness. It must support structured JSON for normalized,
SemanticFrame-compatible output.

Semantic close, assistant-directedness, emotion, and audio caption may be
unsupported in Slice 1 examples, but missing values must be explicit metadata
gaps and must become replay-visible degraded behavior in later runtime slices
when those capabilities are required.

Safe refs:

- `endpoint://synthetic/mvp3/thinker`
- `config://synthetic/mvp3/thinker`

## Slow LLM Profile Template

The Slow LLM profile uses `adapter_type=slow_llm` and `output_mode=real` for
MVP-3 required readiness. It must support structured JSON because SlowTask may
consume only validated normalized output.

Provider-native tool calling is not required for MVP-3 Slice 1. Tool execution
authority remains with Tool Executor, and provider-specific schemas must not
leak into SlowTask.

Safe refs:

- `endpoint://synthetic/mvp3/slow_llm`
- `config://synthetic/mvp3/slow_llm`

## TTS Profile Template

The TTS profile uses `adapter_type=tts` and `output_mode=real` for MVP-3
required readiness. It must support audio output and TTS synthesis.

`supports_tts_truncate` is not counted as a minimum Slice 1 readiness
capability. If truncate is unsupported, later TTS and barge-in slices must
block or degrade target validation explicitly. Pause/resume remains outside
MVP-3 scope.

Safe refs:

- `endpoint://synthetic/mvp3/tts`
- `config://synthetic/mvp3/tts`

## Fallback and Degraded Profiles

Fallback and degraded profiles are allowed as explicit metadata states. They
may pass `validate_capability_matrix`, but they never count toward required
MVP-3 real readiness.

Fallback and degraded profiles must:

- use `output_mode=fallback` or `output_mode=degraded`;
- document missing boolean capabilities through `unsupported_capabilities`;
- avoid mock-only readiness claims;
- produce replay-visible `ADAPTER_OUTPUT_DEGRADED`, validation failure, retry,
  or request failure events when used by later runtime slices.

## Validation Requirements

Slice 1 is complete when synthetic provider-agnostic ASR, Thinker, Slow LLM,
and TTS examples satisfy these checks:

- each example passes `validate_capability_matrix`;
- the required real profile set passes `validate_mvp3_adapter_profile_set`;
- the profile set passes `assemble_runtime_adapters(stage="mvp3", ...)`
  without provider probing;
- mock-only profiles fail MVP-3 real readiness;
- fallback and degraded profiles are explicit but do not satisfy required real
  readiness;
- credential-like endpoint and config refs fail closed;
- missing required capabilities fail closed;
- the runtime capability snapshot records adapter ids, adapter types,
  deployment modes, output modes, and capability version.

## Slice Alignment

This spec implements `MVP3-ADAPTER-PROFILE-001` from
`docs/specs/mvp3-acceptance-scenarios.md` and Slice 1 from
`docs/implementation/mvp3-backlog.md`.

It intentionally does not implement Slice 2 adapter health/error/degraded event
harness behavior, Slice 3 session startup events, or any real ASR, Thinker,
Slow LLM, or TTS provider behavior.
