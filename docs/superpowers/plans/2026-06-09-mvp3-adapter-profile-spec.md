# MVP3 Adapter Profile Spec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-agnostic MVP3 adapter profile specification and contract tests for ASR, Thinker, Slow LLM, and TTS profiles.

**Architecture:** This plan keeps MVP3-0 metadata-only. It adds a spec document and adapter contract tests that reuse the existing `validate_capability_matrix`, `validate_mvp3_adapter_profile_set`, and `assemble_runtime_adapters` gates. No provider SDK, endpoint probe, secret handling, frontend, Tool Executor, SlowTask, Composer, or replay runtime behavior is added.

**Tech Stack:** Python 3.11, pytest through `./scripts/test`, Markdown specs under `docs/specs`.

---

## File Structure

- Create: `docs/specs/adapter-capability-profiles.md`
  - Defines provider-agnostic MVP3 profile templates, examples, degraded/fallback rules, and validation requirements.
- Create: `tests/adapters/test_mvp3_adapter_capability_profiles_spec.py`
  - Holds synthetic profile examples and contract tests for the spec.
- Modify only if tests expose a real contract gap: `src/voice_agent/adapters/profiles.py`
  - Existing MVP3 profile gate; should usually remain unchanged.

## Task 1: Add Failing Profile Contract Tests

**Files:**
- Create: `tests/adapters/test_mvp3_adapter_capability_profiles_spec.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from voice_agent.adapters.capabilities import (
    BOOLEAN_CAPABILITY_FIELDS,
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.adapters.mock_adapters import mvp0_mock_adapter_capabilities
from voice_agent.adapters.profiles import (
    AdapterProfileValidationError,
    MVP3_REQUIRED_REAL_ADAPTER_TYPES,
    validate_mvp3_adapter_profile_set,
)
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig, assemble_runtime_adapters


SPEC_PATH = Path("docs/specs/adapter-capability-profiles.md")


def unsupported_capabilities(profile: dict[str, object]) -> tuple[str, ...]:
    return tuple(field for field in BOOLEAN_CAPABILITY_FIELDS if profile[field] is False)


def mvp3_profile(adapter_type: str, output_mode: str = "real", **overrides: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "adapter_id": f"mvp3_{adapter_type}_{output_mode}",
        "adapter_type": adapter_type,
        "provider": "synthetic_provider",
        "model_name": f"synthetic_{adapter_type}_model",
        "deployment_mode": "remote_api",
        "endpoint": f"endpoint://synthetic/mvp3/{adapter_type}/{output_mode}",
        "health_status": "configured",
        "capability_version": "mvp3.profile.v1",
        "latency_class": "profile_contract",
        "error_model": "error-model://synthetic/mvp3/profile",
        "timeout_policy": "timeout-policy://synthetic/mvp3/profile",
        "retry_policy": "retry-policy://synthetic/mvp3/profile",
        "output_mode": output_mode,
        "config_ref": f"config://synthetic/mvp3/{adapter_type}/{output_mode}",
        "supports_streaming_input": False,
        "supports_streaming_output": False,
        "supports_audio_input": False,
        "supports_audio_output": False,
        "supports_audio_timestamps": False,
        "supports_structured_json": False,
        "supports_tool_calling": False,
        "supports_cancellation": False,
        "supports_emotion": False,
        "supports_audio_caption": False,
        "supports_tts": False,
        "supports_tts_truncate": False,
        "supports_tts_pause_resume": False,
        "supports_semantic_close": False,
        "supports_assistant_directedness": False,
        "max_audio_seconds": None,
        "max_context_tokens": 4096,
        "max_output_tokens": 1024,
        "expected_first_token_latency_ms": 600,
        "expected_first_audio_latency_ms": None,
        "mocked": False,
        "mock_profile_ref": "",
        "target_architecture_validation": True,
    }
    if adapter_type == "asr":
        profile.update(supports_audio_input=True, supports_structured_json=True, max_audio_seconds=30)
    elif adapter_type in {"thinker", "slow_llm"}:
        profile.update(supports_structured_json=True)
    elif adapter_type == "tts":
        profile.update(supports_audio_output=True, supports_tts=True, expected_first_audio_latency_ms=700)
    profile.update(overrides)
    profile["unsupported_capabilities"] = unsupported_capabilities(profile)
    return profile


def real_profiles() -> tuple[dict[str, object], ...]:
    return tuple(mvp3_profile(adapter_type) for adapter_type in MVP3_REQUIRED_REAL_ADAPTER_TYPES)


def test_adapter_profile_spec_exists_and_names_required_contracts() -> None:
    assert SPEC_PATH.exists()
    content = SPEC_PATH.read_text(encoding="utf-8")

    for required_text in (
        "ASR",
        "Thinker",
        "Slow LLM",
        "TTS",
        "validate_mvp3_adapter_profile_set",
        "assemble_runtime_adapters",
        "fallback",
        "degraded",
        "credential",
    ):
        assert required_text in content


def test_provider_agnostic_real_profiles_validate_against_existing_gates() -> None:
    profiles = real_profiles()

    matrices = tuple(validate_capability_matrix(profile) for profile in profiles)
    validated = validate_mvp3_adapter_profile_set(matrices)
    assembly = assemble_runtime_adapters(
        RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/profile-spec",
            capability_version="mvp3.profile.v1",
        ),
        validated,
    )

    assert [matrix["adapter_type"] for matrix in validated] == list(MVP3_REQUIRED_REAL_ADAPTER_TYPES)
    assert assembly.capability_snapshot["output_modes"] == ["real", "real", "real", "real"]


def test_fallback_and_degraded_profiles_are_explicit_but_do_not_satisfy_real_readiness() -> None:
    fallback = mvp3_profile("slow_llm", output_mode="fallback", provider="synthetic_fallback")
    degraded = mvp3_profile(
        "tts",
        output_mode="degraded",
        supports_tts_truncate=False,
        provider="synthetic_degraded",
    )

    assert validate_capability_matrix(fallback)["output_mode"] == "fallback"
    assert validate_capability_matrix(degraded)["output_mode"] == "degraded"

    with pytest.raises(AdapterProfileValidationError, match="real adapter profile"):
        validate_mvp3_adapter_profile_set((fallback, degraded))


def test_profile_examples_fail_closed_for_credentials_and_missing_required_capabilities() -> None:
    unsafe = deepcopy(mvp3_profile("asr"))
    unsafe["endpoint"] = "https://provider.example.test/v1?api_key=sk-synthetic"
    with pytest.raises(CapabilityValidationError, match="credential"):
        validate_capability_matrix(unsafe)

    missing_required = deepcopy(mvp3_profile("slow_llm"))
    missing_required["supports_structured_json"] = False
    missing_required["unsupported_capabilities"] = unsupported_capabilities(missing_required)
    with pytest.raises(AdapterProfileValidationError, match="supports_structured_json"):
        validate_mvp3_adapter_profile_set((*real_profiles()[:2], missing_required, real_profiles()[3]))


def test_mock_only_profiles_remain_outside_mvp3_real_readiness() -> None:
    with pytest.raises(AdapterProfileValidationError, match="real adapter profile"):
        validate_mvp3_adapter_profile_set(mvp0_mock_adapter_capabilities())
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./scripts/test tests/adapters/test_mvp3_adapter_capability_profiles_spec.py -q
```

Expected: fail because the test file references spec behavior before `docs/specs/adapter-capability-profiles.md` exists or because existing gates do not yet accept the test's dictionary inputs.

## Task 2: Add the Adapter Capability Profiles Spec

**Files:**
- Create: `docs/specs/adapter-capability-profiles.md`

- [ ] **Step 1: Write the spec**

Create a Markdown spec with these sections:

```markdown
# Adapter Capability Profiles / Adapter 能力 Profile

Source of truth: ADR-011, ADR-012, `docs/specs/model-adapter-capabilities.md`, and the MVP3 readiness gates in `src/voice_agent/adapters/profiles.py`.

## Purpose

This document defines provider-agnostic MVP3 profile templates for ASR, Thinker, Slow LLM, and TTS adapters. Profiles are metadata contracts used by runtime assembly before any real provider integration.

## Non-Goals

- No provider SDK selection.
- No API key, bearer token, cookie, credential, or authorization header.
- No provider healthcheck or network probe.
- No frontend, Tool Executor, SlowTask, Composer, or replay runtime change.

## Common Profile Rules

Every profile must pass `validate_capability_matrix`. MVP3 runtime readiness must pass `validate_mvp3_adapter_profile_set` before `assemble_runtime_adapters(stage="mvp3", ...)`.

Required output modes are `real`, `mock`, `fallback`, and `degraded`. MVP3 required readiness counts only `output_mode=real` profiles for `asr`, `thinker`, `slow_llm`, and `tts`.

Endpoint and config values must be refs, not credential-bearing URLs. Safe examples include `endpoint://synthetic/mvp3/asr` and `config://synthetic/mvp3/asr`.

## Required MVP3 Real Profiles

| adapter_type | Required capabilities | Notes |
| --- | --- | --- |
| `asr` | `supports_audio_input`, `supports_structured_json` | Final transcript or equivalent text projection is sufficient for MVP3. |
| `thinker` | `supports_structured_json` | Basic SemanticFrame-compatible output is sufficient. |
| `slow_llm` | `supports_structured_json` | Structured SlowTask output must be schema-validated. |
| `tts` | `supports_audio_output`, `supports_tts` | Basic audio synthesis is sufficient; missing truncate must degrade explicitly. |

## Fallback and Degraded Profiles

Fallback and degraded profiles are allowed as explicit metadata, but they never count toward required real readiness. They must document missing capabilities through `unsupported_capabilities` and must produce replay-visible `ADAPTER_OUTPUT_DEGRADED` or failure events when used at runtime.

## Validation Requirements

- Mock-only profile sets must fail MVP3 readiness.
- Credential-like endpoint/config refs must fail validation.
- Missing required real capabilities must fail validation.
- Unsupported capability contradictions must fail validation.
- Runtime assembly must record adapter ids/types, deployment modes, output modes, and capability version.
```

- [ ] **Step 2: Run the targeted test**

Run:

```bash
./scripts/test tests/adapters/test_mvp3_adapter_capability_profiles_spec.py -q
```

Expected: pass if existing production gates already satisfy the spec; otherwise fail on the smallest real contract gap.

## Task 3: Fix Any Genuine Contract Gap

**Files:**
- Modify only if needed: `src/voice_agent/adapters/profiles.py`
- Modify only if needed: `src/voice_agent/runtime/assembly.py`

- [ ] **Step 1: If targeted tests fail, inspect the failure**

Run:

```bash
./scripts/test tests/adapters/test_mvp3_adapter_capability_profiles_spec.py -q
```

Expected failure examples:

- dictionary profile inputs rejected where `Mapping[str, Any]` should be accepted;
- fallback/degraded profile validation too strict before MVP3 readiness counting;
- error message does not identify the missing required capability.

- [ ] **Step 2: Implement only the minimal fix**

Keep the current MVP3 gates strict:

- required real adapter types remain `asr`, `thinker`, `slow_llm`, `tts`;
- mock/fallback/degraded profiles do not satisfy real readiness;
- no provider probe is added;
- no secret-bearing fields are added.

- [ ] **Step 3: Re-run targeted tests**

Run:

```bash
./scripts/test tests/adapters/test_mvp3_adapter_capability_profiles_spec.py -q
```

Expected: pass.

## Task 4: Run Verification

**Files:**
- All changed files.

- [ ] **Step 1: Run adapter tests**

Run:

```bash
./scripts/test tests/adapters -q
```

Expected: all adapter tests pass.

- [ ] **Step 2: Run full suite**

Run:

```bash
./scripts/test -q
```

Expected: all tests pass.

- [ ] **Step 3: Check diff hygiene**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only MVP3-0 spec/test/necessary gate files are modified or added, plus pre-existing untracked local artifact directories if still present.
