# TC-S3B1-02 Capabilities and Assembly

## Task ID and title

`TC-S3B1-02` — Provider-free capabilities and `slice3b1_mock` assembly.
Status: `not-started`. Historical source: Slice 3B.1 master-plan Task 2.

## Goal

Declare truthful role-specific Qwen, ASR, parallel-orchestrator, and Route
Evidence capabilities, then assemble a deterministic provider-free profile set
whose digest cannot authorize native PCM.

## Allowed write files

- Modify: `src/voice_agent/adapters/capabilities.py`
- Modify: `src/voice_agent/adapters/profiles.py`
- Modify: `src/voice_agent/adapters/asr_profile.py`
- Modify: `src/voice_agent/runtime/assembly.py`
- Modify: `src/voice_agent/runtime/adapter_callback_boundary.py`
- Create: `src/voice_agent/adapters/qwen_realtime/profile.py`
- Create: `src/voice_agent/adapters/parallel_fast_interaction_profile.py`
- Create: `src/voice_agent/adapters/route_evidence_profile.py`
- Create: `tests/adapters/qwen_realtime/test_capability_profile.py`
- Create: `tests/adapters/test_parallel_fast_interaction_profile.py`
- Create: `tests/adapters/test_route_evidence_profile.py`
- Create: `tests/runtime/test_slice3b1_adapter_assembly.py`
- Regression test: `tests/adapters/test_fast_interaction_capability.py`
- Regression test: `tests/adapters/test_asr_adapter_profile.py`
- Regression test: `tests/runtime/test_runtime_adapter_assembly.py`

## Required read-only dependencies

- [TC-S3B1-01](TC-S3B1-01-events-and-envelopes.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/adapter-capability-profiles.md`

## Exact ADR sections

- `docs/adr/ADR-011 Model Adapter Capability Contract.md` — `Decision`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md` — `ADR-018 Capability Addendum`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `Decision`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `ADR-018 Topology Compatibility Addendum`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Input is the accepted role/projection requirements plus Card 01's canonical
event and envelope boundary; Card 01 does not produce a capability snapshot.
Output includes `ADR018_BOOLEAN_CAPABILITY_FIELDS`,
`ADR018_SUPPORT_FACT_FIELDS`,
`build_qwen_realtime_fake_profile()`,
`build_qwen_realtime_asr_fake_profile()`,
`build_parallel_fast_interaction_orchestrator_profile()`, and
`build_route_evidence_fake_profile()`; plus
`validate_slice3b1_adapter_profile_set(...)` and assembly
`stage="slice3b1_mock"`.

Card 02 assembly creates the snapshot and adds a deterministic
`capability_matrix_digest` for this stage
without changing legacy snapshot shape. Documentation support, provider-free
test support, implementation support, and real-live support remain separate.
The authoritative Slice 3B.1 facts include `output_mode=mock`,
`real_live_support=false`, and `native_pcm_enabled=false`.

The historical `Regression test:` entries in Allowed write files are read-only
verification inputs; their verbatim presence is not authorization to edit them.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-ADAPTER-01`
- `INV-ADAPTER-02`
- `INV-JOURNAL-01`
- `INV-FOREGROUND-01`
- `INV-FOREGROUND-03`
- `INV-VERIFY-01`

## Non-goals

- No real provider transport, credentials, live qualification, or provider SDK.
- No native PCM enablement or release authority.
- No new model call inside the join-only orchestrator profile.
- No changes to legacy builders' strict required-input contracts.
- Only paths labeled `Create:` or `Modify:` above are writable. Rows labeled
  `Regression test:` are read-only verification surfaces and do not grant
  mutation authority.

## Implementation outline

1. Verify Card 01, then run profile/assembly tests against the current tree.
2. Add ADR-018 fields as backward-compatible facts, not universal legacy
   requirements.
3. Build separate role profiles with explicit mock/provider-free status and
   stable profile identifiers.
4. Validate the complete profile set before assembly and derive the digest from
   normalized facts, independent of input ordering.
5. Extend only adapter-owned callback event allowlists; Gate/output authority
   remains outside the adapter callback boundary.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_capability_profile.py tests/adapters/test_parallel_fast_interaction_profile.py tests/adapters/test_route_evidence_profile.py tests/runtime/test_slice3b1_adapter_assembly.py tests/adapters/test_fast_interaction_capability.py tests/adapters/test_asr_adapter_profile.py tests/runtime/test_runtime_adapter_assembly.py -q
git diff --check -- src/voice_agent/adapters/capabilities.py src/voice_agent/adapters/profiles.py src/voice_agent/adapters/asr_profile.py src/voice_agent/adapters/qwen_realtime/profile.py src/voice_agent/adapters/parallel_fast_interaction_profile.py src/voice_agent/adapters/route_evidence_profile.py src/voice_agent/runtime/assembly.py src/voice_agent/runtime/adapter_callback_boundary.py tests/adapters/qwen_realtime/test_capability_profile.py tests/adapters/test_parallel_fast_interaction_profile.py tests/adapters/test_route_evidence_profile.py tests/runtime/test_slice3b1_adapter_assembly.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

All profiles are strict, role-specific, deterministic, and truthful; the mock
assembly rejects real/live and native-release claims; digest changes track
capability changes; callback ownership remains correct; legacy profile and
assembly tests pass unchanged.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop if mock is presented as real/live,
native PCM becomes enabled, the legacy snapshot shape drifts, or a capability
boolean becomes caller-controlled release authority. Editing a
`Regression test:` path is write-set expansion and requires stopping.

## Evidence and handoff

Record tested profile IDs, output modes, deterministic digest evidence, safe
test counts, and relative changed paths. Hand the validated assembly result and
digest contract to `TC-S3B1-06`, `TC-S3B1-07`, and `TC-S3B1-08` without copying
capability bodies into canonical events.
