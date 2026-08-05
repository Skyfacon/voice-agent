# Qwen Slice 3B.1 Protocol-Faithful Provider-Free Fake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-free, protocol-faithful Qwen Audio Realtime control-plane demo in which one logical Connect session drives a scripted WebSocket-shaped event stream, independent route evidence, Local Router authority, a fail-closed Fast Foreground Gate, canonical journal/replay, and a stable CLI result without network, credentials, raw PCM persistence, or native playback claims.

**Architecture:** Add a focused `qwen_realtime` adapter package shared by the scripted Fake transport in Slice 3B.1 and the future Real transport in Slice 3B.2. A separate Session Runtime exclusively advances provider generations; one serialized sender and one receive Pump feed typed projections and Candidate Quarantine, while the existing Event Journal, Local Router, Gate, and replay remain the control authorities. The default runner fixes `output_mode=mock` and `native_pcm_enabled=false`; an isolated `mock_contract_only` suite validates the full release-token/outbox contract without playback or capability promotion.

**Tech Stack:** Python 3.11+, standard-library `asyncio`, frozen dataclasses and `Protocol`, existing in-memory Event Journal and deterministic replay, pytest through `./scripts/test`, Bash CLI wrapper, synthetic in-memory PCM only.

## Global Constraints

- Work only in `/Users/a123/voice-agent`.
- The accepted source of truth is `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`, together with accepted ADR-018 and the ADRs referenced by `AGENTS.md`.
- Before editing any currently modified file, inspect its current diff and preserve all user/earlier-slice changes. In particular, treat `src/voice_agent/replay/runner.py`, `src/voice_agent/replay/state_digest.py`, and `src/voice_agent/runtime/fast_foreground_gate.py` as overlap-sensitive.
- Do not create or switch a worktree or branch. Do not reset, checkout, restore, clean, stage, commit, push, or create a PR.
- External providers may only be reached through adapters. Slice 3B.1 must make zero network calls, import no provider SDK, and read no provider credential or environment secret.
- Session Runtime is the sole allocator/advancer of
  `provider_session_generation`; it advances the generation before every
  `open()`. The Interaction Controller is the sole owner of
  `playback_epoch`: initial Connect reads its current epoch, while rebuild
  synchronously asks it to advance to a strictly greater epoch before Adapter
  fencing or network-equivalent `open()`. Transport never sees or emits local
  generation, turn, utterance, playback epoch, context snapshot, route, or Gate
  authority.
- One logical Connect owns at most one active transport generation, one serialized sender, and one receive Pump. Critical journal appends remain per-session serialized.
- `session.created` defaults are not authority. Only an exact, matching `session.updated` echo moves provider context to `CLEAN`. Non-`CLEAN` microphone frames are dropped, counted, never buffered, and never replayed.
- Qwen Fake emits provider-shaped events only. It must never emit `route.proposed`, Router decisions, Gate decisions, local IDs, or local generation.
- Raw provider bodies, prompts, raw/unrestricted transcript text, raw PCM, secrets, credentials, authorization headers, real-user input, local paths, raw traces, and replay caches must not enter canonical events, fixtures, diagnostics, result objects, exception representations, or Git.
- Synthetic PCM is generated at runtime into wipeable memory, never stored as bytes/base64 in source or fixtures, and represented outside quarantine only by bounded safe metadata and digests.
- `wire_seq` is a Fake scheduler field only. Adapter correlation may use provider event ID and provider response/item/output/content identities, but must never use `wire_seq`.
- Missing provider ordinal/checksum means the implementation must not claim detection of arbitrary omitted or reordered PCM deltas. It may detect only event-ID, lifecycle, identity, terminal, overflow, disconnect, and terminal-manifest failures observable by the future Real transport.
- Local Router remains the only owner of `ROUTER_DECISION_EMITTED`; Route Evidence and the Qwen answer candidate are evidence only.
- Candidate release eligibility is capped at 80 Unicode scalar values and
  2,000 ms decoded audio. Quarantine enforces both limits before completion,
  and Gate requires recorded length, duration, terminal, and correlation checks.
- The normal Slice 3B.1 runner derives
  `native_pcm_enabled=false` from the validated `slice3b1_mock` assembly; no
  caller-provided boolean may enable it. It produces no release token or
  playback outbox item, calls no Talker, and cannot report native PCM success.
- `mock_contract_only` may validate exact release-token comparison and mock
  outbox insertion only through a test-only, non-exported contract harness. No
  runner, CLI, assembly, or production Gate dispatch may import that harness or
  reach an enabled branch. It may not alter capability profiles, call a Talker,
  or count as PCM qualification.
- Page C, Slow-to-Fast runtime behavior, Composer request variants, Real Qwen WebSocket transport, durable memory, native PCM qualification, and real playback belong to later slices.
- Every Python test command must use `VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test ...`. Do not call pytest directly and do not install dependencies.

## Locked File Map

### New provider/session boundary

- `src/voice_agent/adapters/qwen_realtime/protocol.py` — validated client/server tagged event types, session configuration, safe metadata projection.
- `src/voice_agent/adapters/qwen_realtime/transport.py` — the Fake/Real-shared `QwenRealtimeTransport` protocol.
- `src/voice_agent/adapters/qwen_realtime/scenarios.py` — provider-shaped wire scripts containing only safe templates and symbolic payload factories.
- `src/voice_agent/adapters/qwen_realtime/scripted_wire.py` — deterministic permit-driven Fake transport and virtual scheduler.
- `src/voice_agent/adapters/qwen_realtime/projections.py` — ordered, typed Adapter-to-control-plane projection frames.
- `src/voice_agent/adapters/qwen_realtime/ephemeral_text_store.py` — bounded,
  per-session, wipeable ASR/candidate text refs and resolver leases; no text is
  journaled or serialized.
- `src/voice_agent/adapters/qwen_realtime/quarantine.py` — two-stage candidate binding, PCM memory ownership, lifecycle validation, and immutable digests.
- `src/voice_agent/adapters/qwen_realtime/session_adapter.py` — handshake/readiness state, one sender, one Pump, ASR join, ambient/invalid handling, cancellation, and cleanup requests.
- `src/voice_agent/adapters/qwen_realtime/profile.py` — provider-free Qwen session and ASR logical-projection profiles.
- `src/voice_agent/adapters/parallel_fast_interaction_profile.py` — local
  join-only Fast Interaction Orchestrator capability profile.
- `src/voice_agent/adapters/qwen_realtime/__init__.py` — the small public adapter surface.
- `src/voice_agent/runtime/qwen_realtime_session.py` — sole provider-generation allocator and one-active-transport lifecycle owner.

### New independent evidence and Slice runner

- `src/voice_agent/adapters/route_evidence_contract.py` — immutable route and candidate-safety request/output schemas.
- `src/voice_agent/adapters/route_evidence_fake.py` — deterministic provider-free Route Evidence Adapter.
- `src/voice_agent/adapters/route_evidence_profile.py` — route/candidate-safety capability profile.
- `src/voice_agent/runtime/slice3b1/context_projection.py` — bounded immutable model-context projections from canonical state.
- `src/voice_agent/runtime/slice3b1/ingress.py` — safe provider
  speech-start/stop projection into canonical Duplex evidence, followed by the
  existing Interaction Controller authority.
- `src/voice_agent/runtime/slice3b1/orchestrator.py` — join-only parallel Fast Interaction Orchestrator.
- `src/voice_agent/runtime/slice3b1/contracts.py` — stable `Slice3B1RunV1` and safe JSON projection.
- `src/voice_agent/runtime/slice3b1/scenarios.py` — end-to-end scenario catalog combining wire steps, local actions, and evidence directives.
- `src/voice_agent/runtime/slice3b1/runner.py` — async core plus `run_slice3b1_scenario(...)`.
- `src/voice_agent/runtime/slice3b1/cli.py` — presentation-only CLI.
- `src/voice_agent/runtime/slice3b1/__init__.py` — stable runner/result exports.
- `src/voice_agent/runtime/slice3b1_release.py` — parallel Gate context, immutable release token, exact compare-and-authorize boundary, and memory-only mock outbox.
- `scripts/qwen-slice3b1` — repository-root CLI wrapper.

### Existing integration points

- `src/voice_agent/events/registry.py`, `src/voice_agent/events/envelope.py` — ADR-018 events and backward-compatible conditional fields.
- `src/voice_agent/events/journal.py` — synchronous prevalidated atomic batch
  append used by the release contract; legacy single append remains unchanged.
- `src/voice_agent/privacy/redaction.py` — narrow opaque release-token ID/ref handling.
- `src/voice_agent/adapters/capabilities.py`, `src/voice_agent/adapters/profiles.py`, `src/voice_agent/adapters/asr_profile.py` — role-specific Slice 3B capability facts without breaking old profiles.
- `src/voice_agent/runtime/assembly.py`, `src/voice_agent/runtime/adapter_callback_boundary.py` — explicit `slice3b1_mock` assembly and serialized canonical adapter callbacks.
- `src/voice_agent/router/router.py` — Route Evidence input branch while preserving legacy Thinker/Fast branches.
- `src/voice_agent/interaction/controller.py` — existing audio open/commit
  authority plus explicit rejected-audio-ingress and playback-epoch authority;
  the runner never appends turn authority or advances the epoch directly.
- `src/voice_agent/runtime/fast_foreground_gate.py` — a narrow topology dispatcher only; legacy Gate behavior remains intact.
- `src/voice_agent/state/qwen_parallel_state.py` — deterministic ADR-018 replay state.
- `src/voice_agent/state/adapter_health_state.py`, `src/voice_agent/replay/runner.py`, `src/voice_agent/replay/state_digest.py` — recorded evidence validation and digest.
- `tests/qwen_slice3b1_support.py` — deterministic test-only event, transport,
  journal, and fixture builders; it never stores raw PCM or production
  decisions.
- `tests/fixtures/replay/mvp6/slice3b1/` — two synthetic/redacted/minimal fixtures, never raw wire or PCM.
- `docs/implementation/qwen-slice3b1-provider-free-acceptance.md` — completed evidence and explicit non-claims.

---

### Task 1: Register ADR-018 events, conditional topology fields, and opaque release authority

**Files:**

- Modify: `src/voice_agent/events/registry.py`
- Modify: `src/voice_agent/events/envelope.py`
- Modify: `src/voice_agent/privacy/redaction.py`
- Create: `tests/events/test_adr018_event_registry.py`
- Create: `tests/events/test_adr018_conditional_event_envelopes.py`
- Create: `tests/events/test_adr018_release_token_redaction.py`
- Create: `tests/qwen_slice3b1_support.py`
- Regression test: `tests/events/test_fast_foreground_event_registry.py`
- Regression test: `tests/events/test_event_envelope.py`

**Interfaces:**

- Produces `ADR018_EVENT_DEFINITIONS`, `ADR018_EVENT_NAMES`, `ConditionalRequiredFields`, and `AllOrNoneFields`.
- Produces `is_safe_release_token_id(value: str) -> bool` and `is_safe_release_token_ref(value: str, *, allow_local: bool = True) -> bool`.
- Produces test-only builders
  `base_canonical_event(...)`, `valid_adr018_event(...)`,
  `valid_asr_event(...)`,
  `valid_legacy_candidate_event(...)`,
  `valid_parallel_fast_event(...)`,
  `valid_parallel_candidate_event(...)`, and `parallel_journal()`.
- Preserves every legacy required-field tuple. Missing `fast_interaction_topology` continues to mean `atomic_single_call`.

- [ ] **Step 0: Capture the dirty-worktree baseline without mutation**

Run:

```bash
git status --short
git diff --stat
git diff -- src/voice_agent/replay/runner.py src/voice_agent/replay/state_digest.py src/voice_agent/runtime/fast_foreground_gate.py src/voice_agent/interaction/controller.py src/voice_agent/events/journal.py
```

Keep the exact command outputs in the implementation task transcript. Later,
copy only the safe filename/status baseline and overlap notes into the
acceptance document—never raw diff payloads, text, credentials, or local
traces. At final verification, compare against this baseline and fail if a
pre-existing dirty file disappeared or was reset.

- [ ] **Step 1: Write failing tests for all nine canonical events**

Create a parameterized test whose expected map is literal and complete:

```python
ADR018_REQUIRED_FIELDS = {
    "ROUTE_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_id", "adapter_type", "adapter_request_id", "turn_id",
        "utterance_id", "final_asr_event_id", "context_projection_event_id",
        "route_hint", "task_focus_hint", "foreground_act_hint", "ack_kind",
        "risk_class", "risk_tags", "evidence_uncertainty", "confidence",
        "schema_name", "normalization_status", "output_mode",
    },
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_id", "adapter_type", "adapter_request_id", "turn_id",
        "utterance_id", "qwen_response_id", "candidate_transcript_digest",
        "context_projection_event_id", "decision", "semantic_categories",
        "prohibited_flags", "confidence", "schema_name",
        "normalization_status", "output_mode",
    },
    "MODEL_CONTEXT_PROJECTION_EMITTED": {
        "projection_id", "target_role", "source_event_ids",
        "context_snapshot_id", "source_event_seq",
        "provider_session_generation", "projection_ref", "policy_version",
        "redaction_status", "output_mode",
    },
    "SLOW_TO_FAST_HANDOFF_EMITTED": {
        "handoff_id", "kind", "delivery_mode", "task_id", "plan_version",
        "task_event_seq", "source_event_ids", "facts_ref",
        "must_say_fields_ref", "forbidden_claims_ref", "priority",
        "expiry_status", "redaction_status",
    },
    "SLOW_TO_FAST_HANDOFF_DISPOSITIONED": {
        "handoff_id", "disposition", "reason",
    },
    "RESPONSE_ARBITRATION_DECIDED": {
        "arbitration_id", "selected_source_type",
        "superseded_source_event_ids", "provider_session_generation",
        "playback_epoch", "interaction_state_version", "decision_reason",
    },
    "PROVIDER_CONTEXT_STATE_CHANGED": {
        "adapter_id", "provider_session_generation", "from_state", "to_state",
        "reason", "source_event_ids", "output_mode",
    },
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": {
        "adapter_id", "adapter_type", "adapter_request_id", "turn_id",
        "utterance_id", "qwen_response_id", "candidate_transcript_digest",
        "candidate_pcm_manifest_digest", "audio_format_ref",
        "decoded_duration_ms", "independent_transcript_ref",
        "normalized_transcript_digest", "exact_numbers_entities_units_match",
        "equivalence", "output_mode",
    },
    "ASSISTANT_DELIVERY_DISPOSITIONED": {
        "assistant_item_ref", "source_output_event_id", "from_status",
        "to_status", "delivery_offset_status",
        "provider_item_cleanup_status", "source_event_ids",
    },
}

def test_adr018_runtime_registry_has_exact_required_fields() -> None:
    assert ADR018_EVENT_NAMES == frozenset(ADR018_REQUIRED_FIELDS)
    for name, expected in ADR018_REQUIRED_FIELDS.items():
        assert set(get_event_definition(name).required_fields) == expected
```

Also freeze and assert these literal enum sets:

```python
ADR018_ENUM_FIELDS = {
    "ROUTE_EVIDENCE_OUTPUT_EMITTED": {
        "route_hint": frozenset({
            "FAST_ONLY", "SPAWN_SLOW_TASK",
            "PATCH_ACTIVE_SLOW_TASK", "IGNORE",
        }),
        "task_focus_hint": frozenset({
            "ACTIVE_TASK_PATCH", "FOREGROUND_CHAT", "NEW_TASK_CANDIDATE",
            "CANCEL_OR_PAUSE_CANDIDATE", "NON_ASSISTANT", "AMBIGUOUS",
        }),
        "foreground_act_hint": frozenset({
            "ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY",
        }),
        "ack_kind": frozenset({
            "CHAT", "SEARCH_ACCEPTED", "COMPARE_ACCEPTED", "PLAN_ACCEPTED",
            "PATCH_RECEIVED", "CLARIFY_NEEDED",
            "WAITING_CONFIRMATION", "SILENCE",
        }),
        "risk_class": frozenset({"LOW", "MEDIUM", "HIGH", "UNKNOWN"}),
        "evidence_uncertainty": frozenset({"LOW", "MEDIUM", "HIGH"}),
    },
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": {
        "decision": frozenset({"SAFE", "UNSAFE", "UNCERTAIN"}),
    },
    "MODEL_CONTEXT_PROJECTION_EMITTED": {
        "target_role": frozenset({
            "route_evidence", "candidate_safety",
            "fast_candidate", "composer",
        }),
    },
    "SLOW_TO_FAST_HANDOFF_EMITTED": {
        "kind": frozenset({
            "PROGRESS", "CLARIFICATION", "CONFIRMATION",
            "FINAL", "DEGRADED", "FAILED",
        }),
        "delivery_mode": frozenset({"CONTEXT_ONLY", "SPEAK_WHEN_IDLE"}),
        "expiry_status": frozenset({"CURRENT", "EXPIRED"}),
    },
    "SLOW_TO_FAST_HANDOFF_DISPOSITIONED": {
        "disposition": frozenset({
            "QUEUED", "COALESCED", "SELECTED", "STALE",
            "EXPIRED", "CANCELLED", "DISCARDED",
        }),
    },
    "RESPONSE_ARBITRATION_DECIDED": {
        "selected_source_type": frozenset({
            "user_fast", "confirmation", "clarification",
            "progress", "final", "none",
        }),
    },
    "PROVIDER_CONTEXT_STATE_CHANGED": {
        "from_state": frozenset({
            "CLEAN", "CLEANUP_PENDING", "TAINTED", "REBUILDING", "CLOSED",
        }),
        "to_state": frozenset({
            "CLEAN", "CLEANUP_PENDING", "TAINTED", "REBUILDING", "CLOSED",
        }),
    },
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": {
        "equivalence": frozenset({"MATCH", "MISMATCH", "UNCERTAIN"}),
    },
    "ASSISTANT_DELIVERY_DISPOSITIONED": {
        "from_status": frozenset({"PENDING"}),
        "to_status": frozenset({"FULL", "TRUNCATED", "NOT_STARTED"}),
        "delivery_offset_status": frozenset({
            "KNOWN", "UNKNOWN", "NOT_APPLICABLE",
        }),
        "provider_item_cleanup_status": frozenset({
            "NOT_REQUIRED", "ACKNOWLEDGED", "TAINTED",
        }),
    },
}
```

Freeze the canonical literals separately; required-field and enum tests alone
must not permit a forged adapter owner or unnormalized schema:

```python
ADR018_LITERAL_FIELDS = {
    "ROUTE_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_type": "route_evidence",
        "schema_name": "voice_agent.route_evidence.output.v1",
        "normalization_status": "normalized",
    },
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_type": "route_evidence",
        "schema_name": "voice_agent.candidate_safety.output.v1",
        "normalization_status": "normalized",
    },
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": {
        "adapter_type": "asr",
    },
    "ASSISTANT_DELIVERY_DISPOSITIONED": {
        "from_status": "PENDING",
    },
}

def test_adr018_runtime_registry_has_exact_literals() -> None:
    for name, expected in ADR018_LITERAL_FIELDS.items():
        assert get_event_definition(name).literal_fields == expected
```

Create the shared test builder with explicit signatures so later tasks do not
invent incompatible fixtures:

```python
def base_canonical_event(
    event_name: str,
    *,
    event_id: str,
    event_seq: int,
    caused_by_event_id: str | None,
    **fields: object,
) -> dict[str, object]: ...

def valid_adr018_event(event_name: str) -> dict[str, object]: ...
def valid_asr_event(*, qwen_backed: bool = False) -> dict[str, object]: ...
def valid_legacy_candidate_event() -> dict[str, object]: ...
def valid_parallel_fast_event() -> dict[str, object]: ...
def valid_parallel_candidate_event() -> dict[str, object]: ...
def parallel_journal() -> InMemoryEventJournal: ...
```

Every builder uses fixed synthetic IDs/refs, metadata-only redaction, and
integer virtual timestamps. None accepts transcript text or PCM.

- [ ] **Step 2: Run the registry test and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events/test_adr018_event_registry.py -q
```

Expected: collection/import fails because `ADR018_EVENT_NAMES` does not exist.

- [ ] **Step 3: Add generic conditional and all-or-none schema support**

Extend `EventDefinition` without changing legacy definitions:

```python
@dataclass(frozen=True)
class ConditionalRequiredFields:
    when_field: str
    when_value: object
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class AllOrNoneFields:
    fields: tuple[str, ...]


@dataclass(frozen=True)
class EventDefinition:
    event_name: str
    required_fields: tuple[str, ...]
    one_of_fields: tuple[tuple[str, ...], ...] = ()
    any_of_field_sets: tuple[tuple[str, ...], ...] = ()
    literal_fields: dict[str, object] = field(default_factory=dict)
    enum_fields: dict[str, frozenset[object]] = field(default_factory=dict)
    conditional_required_fields: tuple[ConditionalRequiredFields, ...] = ()
    all_or_none_fields: tuple[AllOrNoneFields, ...] = ()
    domain: str | None = None
    category: str | None = None
    is_root: bool = False
    caused_by_event_required: bool = True
```

In `validate_event_envelope`, validate enum membership, require a conditional set only when the trigger has the exact value, and require all members of an all-or-none group if any member is present. Do not infer or insert `fast_interaction_topology`.

- [ ] **Step 4: Register the nine events and parallel existing-event requirements**

Add `ADR018_EVENT_DEFINITIONS` from the exact field map in Step 1 and merge it into `EVENT_DEFINITIONS`.

Freeze these parallel composite/Gate field names:

```python
PARALLEL_FAST_OUTPUT_FIELDS = (
    "qwen_candidate_adapter_id",
    "qwen_candidate_adapter_request_id",
    "route_evidence_event_id",
    "route_evidence_adapter_request_id",
    "candidate_safety_evidence_event_id",
    "candidate_safety_adapter_request_id",
    "context_snapshot_id",
    "provider_session_generation",
)
PARALLEL_CANDIDATE_FIELDS = (
    "qwen_response_id",
    "qwen_output_item_id",
    "qwen_output_index",
    "qwen_content_index",
    "candidate_transcript_digest",
    "candidate_pcm_manifest_digest",
    "candidate_audio_format_ref",
    "candidate_audio_duration_ms",
    "provider_session_generation",
    "context_snapshot_id",
)
PARALLEL_GATE_FIELDS = (
    "candidate_check_policy_version",
    "candidate_length_check",
    "candidate_duration_check",
    "candidate_terminal_check",
    "native_pcm_capability_check",
    "generation_check",
    "context_snapshot_check",
    "route_evidence_check",
    "candidate_safety_check",
    "transcript_digest_check",
    "pcm_manifest_check",
    "correlation_check",
    "provider_session_generation",
    "context_snapshot_id",
    "route_evidence_event_id",
    "candidate_safety_evidence_event_id",
)
```

Apply them only when:

```text
fast_interaction_topology=speculative_candidate_parallel_route
```

Additionally:

- make the three Qwen ASR fields all-or-none:
  `provider_session_generation`, `qwen_input_item_ref`,
  `qwen_input_content_index`;
- when `PROVIDER_CONTEXT_STATE_CHANGED.to_state=REBUILDING`, require the
  Interaction Controller-owned `playback_epoch` and
  `interaction_state_version`; replay validates that initial Connect binds the
  current epoch and every later generation rebuild uses a strictly greater
  epoch;
- require `release_token_ref` on a parallel Gate pass;
- require unchanged `release_token_ref` when a parallel committed output uses
  `user_visible_channel=audio_pending`;
- when `PLAYBACK_SPAN_STARTED.release_token_ref` is present, require provider
  generation, response ID, output-item ID, output/content indexes, and
  playback epoch;
- keep release-token fields optional on playback commit/finish/truncate so old
  fixtures remain valid; replay will validate identity continuity.

- [ ] **Step 5: Write RED tests for conditional compatibility**

Test both sides explicitly:

```python
def test_parallel_candidate_requires_exact_provider_correlation() -> None:
    event = valid_parallel_candidate_event()
    event.pop("qwen_content_index")
    with pytest.raises(EventValidationError, match="qwen_content_index"):
        validate_event_envelope(event)


def test_legacy_candidate_without_topology_remains_valid() -> None:
    assert validate_event_envelope(valid_legacy_candidate_event())[
        "event_name"
    ] == "FOREGROUND_REPLY_CANDIDATE_EMITTED"


def test_qwen_asr_fields_are_all_or_none() -> None:
    event = valid_asr_event()
    event["provider_session_generation"] = 1
    with pytest.raises(EventValidationError, match="qwen_input_item_ref"):
        validate_event_envelope(event)


@pytest.mark.parametrize(
    ("event_name", "field", "forged"),
    (
        ("ROUTE_EVIDENCE_OUTPUT_EMITTED", "adapter_type", "duplex_model"),
        ("ROUTE_EVIDENCE_OUTPUT_EMITTED", "schema_name", "forged.v1"),
        (
            "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
            "normalization_status",
            "raw",
        ),
        (
            "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED",
            "adapter_type",
            "route_evidence",
        ),
    ),
)
def test_adr018_literals_fail_closed(
    event_name: str, field: str, forged: object
) -> None:
    event = valid_adr018_event(event_name)
    event[field] = forged
    with pytest.raises(EventValidationError, match=field):
        validate_event_envelope(event)
```

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events/test_adr018_conditional_event_envelopes.py -q
```

Expected: RED until the conditional definitions are wired into the registry.

- [ ] **Step 6: Add narrow, decode-resistant release-token privacy handling**

Do not broadly exempt keys containing `token`. Reuse the existing iterative URL
decode safety variants and accept only an internally derived, fixed-width
lowercase-hex ID. Percent-encoding is unnecessary for an opaque release
authority and is rejected even when it decodes to an otherwise safe value:

```python
SAFE_RELEASE_TOKEN_ID_PATTERN = re.compile(
    r"\Arelease_token_[0-9a-f]{32}\Z"
)
SAFE_RELEASE_TOKEN_REF_PATTERN = re.compile(
    r"\Arelease-token://"
    r"(?P<domain>synthetic|redacted|minimal|local)/"
    r"(?P<token_id>release_token_[0-9a-f]{32})\Z"
)

def is_safe_release_token_id(value: str) -> bool:
    if not SAFE_RELEASE_TOKEN_ID_PATTERN.fullmatch(value):
        return False
    return all(
        not SECRET_VALUE_PATTERN.search(candidate)
        and not LOCAL_ONLY_PATH_PATTERN.search(candidate)
        and not AUTHORIZATION_REF_CREDENTIAL_COMPONENT_PATTERN.search(candidate)
        for candidate in _authorization_ref_safety_variants(value)
    )

def is_safe_release_token_ref(value: str, *, allow_local: bool = True) -> bool:
    variants = _authorization_ref_safety_variants(value)
    if len(variants) != 1:
        return False
    match = SAFE_RELEASE_TOKEN_REF_PATTERN.fullmatch(value)
    if match is None:
        return False
    if match.group("domain") == "local" and not allow_local:
        return False
    return (
        is_safe_release_token_id(match.group("token_id"))
        and not SECRET_VALUE_PATTERN.search(value)
        and not LOCAL_ONLY_PATH_PATTERN.search(value)
        and not AUTHORIZATION_REF_QUERY_OR_FRAGMENT_PATTERN.search(value)
        and not AUTHORIZATION_REF_CREDENTIAL_COMPONENT_PATTERN.search(value)
    )
```

Route only exact keys `release_token_id` and `release_token_ref` through these
validators. Continue redacting or blocking every other token-like key. Derive
the 32 hex characters from the canonical safe binding digest; never accept a
provider- or caller-selected ID.

Add negative tests for:

```text
release_token_sk-secret
release-token://synthetic/release_token_sk-secret
release-token://synthetic/release_token_<valid>?token=secret
release-token://synthetic/release_token_<valid>%3Ftoken%3Dsecret
release-token://synthetic/release_token_<valid>%253Ftoken%253Dsecret
release-token://user:pass@synthetic/release_token_<valid>
release-token://synthetic/%2FUsers%2Fa123%2Fdiagnostics%2Fsecret
release-token://local/release_token_<valid> when allow_local=False
```

For each value, assert both direct validation and nested
`sanitize_event_payload(...)` fail without echoing the unsafe value in the
exception.

- [ ] **Step 7: Verify privacy and legacy GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events/test_adr018_event_registry.py tests/events/test_adr018_conditional_event_envelopes.py tests/events/test_adr018_release_token_redaction.py tests/events/test_fast_foreground_event_registry.py tests/events/test_event_envelope.py -q
```

Expected: all tests pass; safe opaque release authority survives unchanged,
credential-looking values fail, and legacy event definitions remain valid.

- [ ] **Step 8: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/events/registry.py src/voice_agent/events/envelope.py src/voice_agent/privacy/redaction.py tests/events/test_adr018_event_registry.py tests/events/test_adr018_conditional_event_envelopes.py tests/events/test_adr018_release_token_redaction.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 2: Add truthful role-specific capabilities and `slice3b1_mock` assembly

**Files:**

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

**Interfaces:**

- Produces `ADR018_BOOLEAN_CAPABILITY_FIELDS` and
  `ADR018_SUPPORT_FACT_FIELDS` without adding them to legacy builders' strict
  input requirement.
- Produces `build_qwen_realtime_fake_profile()`,
  `build_qwen_realtime_asr_fake_profile()`,
  `build_parallel_fast_interaction_orchestrator_profile()`, and
  `build_route_evidence_fake_profile()`.
- Produces `validate_slice3b1_adapter_profile_set(...)` and assembly
  `stage="slice3b1_mock"`.
- The Slice 3B.1 assembly result adds a deterministic
  `capability_matrix_digest` to its capability snapshot; legacy snapshot shape
  remains unchanged.

- [ ] **Step 1: Write the capability profile tests first**

Assert the non-negotiable profile facts:

```python
def test_qwen_slice3b1_profile_is_provider_free_and_native_pcm_disabled() -> None:
    matrix = build_qwen_realtime_fake_profile().to_dict()
    assert matrix["adapter_type"] == "duplex_model"
    assert matrix["status"] == "mock"
    assert matrix["output_mode"] == "mock"
    assert matrix["documentation_support"] is True
    assert matrix["provider_free_test_support"] is True
    assert matrix["real_live_support"] is False
    assert matrix["supports_smart_turn"] is True
    assert matrix["supports_streaming_asr"] is True
    assert matrix["supports_candidate_quarantine"] is True
    assert matrix["supports_provider_native_audio_release"] is False


def test_route_evidence_profile_claims_only_its_role_contract() -> None:
    matrix = build_route_evidence_fake_profile().to_dict()
    assert matrix["adapter_type"] == "route_evidence"
    assert matrix["supports_route_schema"] is True
    assert matrix["supports_candidate_safety_schema"] is True
    assert matrix["supports_prohibited_claim_detection"] is True
    assert matrix["supports_strict_json_validation"] is True
    assert matrix["supports_risk_tags"] is True
    assert matrix["supports_confidence"] is True
    assert matrix["real_live_support"] is False


def test_parallel_orchestrator_profile_is_local_join_only() -> None:
    matrix = build_parallel_fast_interaction_orchestrator_profile().to_dict()
    assert matrix["adapter_type"] == "fast_interaction"
    assert matrix["provider"] == "local_parallel_orchestrator"
    assert matrix["supports_fast_interaction_output"] is True
    assert matrix["supports_reply_candidate"] is True
    assert matrix["supports_reply_delta_streaming"] is False
    assert matrix["provider_free_test_support"] is True
    assert matrix["real_live_support"] is False
```

- [ ] **Step 2: Run the profile tests and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_capability_profile.py tests/adapters/test_parallel_fast_interaction_profile.py tests/adapters/test_route_evidence_profile.py -q
```

Expected: import failure because the profile modules and ADR-018 fields do not
exist.

- [ ] **Step 3: Add role-specific fields with legacy normalization**

Add these exact extension fields:

```python
ADR018_ROUTE_EVIDENCE_BOOLEAN_FIELDS = (
    "supports_route_schema",
    "supports_task_focus",
    "supports_foreground_act_hint",
    "supports_ack_kind",
    "supports_candidate_safety_schema",
    "supports_prohibited_claim_detection",
    "supports_strict_json_validation",
)
ADR018_ASR_BOOLEAN_FIELDS = (
    "supports_candidate_output_audio_shadow_verification",
)
ADR018_QWEN_SESSION_BOOLEAN_FIELDS = (
    "supports_smart_turn",
    "supports_streaming_asr",
    "supports_provider_response_cancellation",
    "supports_provider_item_create",
    "supports_provider_item_delete_ack",
    "supports_manual_response_while_idle",
    "supports_text_only_response_override",
    "supports_candidate_quarantine",
    "supports_provider_native_audio_release",
    "supports_provider_context_readiness",
    "supports_context_rebuild",
)
ADR018_SUPPORT_FACT_FIELDS = (
    "documentation_support",
    "provider_free_test_support",
    "real_live_support",
)
ADR018_BOOLEAN_CAPABILITY_FIELDS = (
    *ADR018_ROUTE_EVIDENCE_BOOLEAN_FIELDS,
    *ADR018_ASR_BOOLEAN_FIELDS,
    *ADR018_QWEN_SESSION_BOOLEAN_FIELDS,
    *ADR018_SUPPORT_FACT_FIELDS,
)
```

Rules:

- legacy matrices may omit every ADR-018 field; normalize omission to `False`;
- normalize missing/empty `status` to the existing `output_mode`;
- require new profiles to set support facts explicitly;
- keep the existing base false-capability explicitness rule;
- automatically append applicable false ADR-018 fields to canonical
  `unsupported_capabilities`, so old builders do not KeyError;
- only `route_evidence` may claim route fields plus shared
  `supports_risk_tags`/`supports_confidence`;
- only `asr` may claim shadow verification;
- only `duplex_model` may claim Qwen session fields;
- `status` must be one of `real|mock|fallback|degraded`, and neither
  `documentation_support` nor `provider_free_test_support` may imply
  `real_live_support`.

Append the ADR-018 fields to `AdapterCapability` with safe defaults so all
existing direct constructors remain source-compatible.

- [ ] **Step 4: Implement the four provider-free profiles**

Use `mock://`/synthetic refs, `mocked=True`, and no credential-bearing endpoint.
The Qwen session profile must declare:

```python
{
    "adapter_type": "duplex_model",
    "provider": "scripted_fake_qwen",
    "deployment_mode": "provider_free",
    "status": "mock",
    "output_mode": "mock",
    "supports_streaming_input": True,
    "supports_streaming_output": True,
    "supports_audio_input": True,
    "supports_audio_output": True,
    "supports_cancellation": True,
    "supports_smart_turn": True,
    "supports_streaming_asr": True,
    "supports_provider_response_cancellation": True,
    "supports_provider_item_create": False,
    "supports_provider_item_delete_ack": True,
    "supports_manual_response_while_idle": False,
    "supports_text_only_response_override": False,
    "supports_candidate_quarantine": True,
    "supports_provider_native_audio_release": False,
    "supports_provider_context_readiness": True,
    "supports_context_rebuild": True,
    "documentation_support": True,
    "provider_free_test_support": True,
    "real_live_support": False,
}
```

The local parallel orchestrator profile uses
`adapter_type=fast_interaction`, `provider=local_parallel_orchestrator`,
`output_mode=mock`, and declares only the join/output capabilities it actually
implements. It does not claim a model, transport, Router, Gate, or playback
capability.

The ASR logical projection profile may use `output_mode=mock` only when
`provider_free_test_support=True`, `mocked=True`, and `real_live_support=False`.
Do not globally add `mock` to real ASR readiness.

- [ ] **Step 5: Add the Slice 3B.1 profile-set validator and assembly stage**

Implement:

```python
def validate_slice3b1_adapter_profile_set(
    profiles: Iterable[AdapterCapability | Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    matrices = validate_adapter_profile_set(profiles)
    required_types = {
        "duplex_model", "asr", "route_evidence", "fast_interaction",
    }
    present_types = {str(matrix["adapter_type"]) for matrix in matrices}
    if not required_types <= present_types:
        raise AdapterProfileValidationError(
            f"Slice 3B.1 missing adapter types: {sorted(required_types - present_types)}"
        )
    for adapter_type in required_types:
        if sum(m["adapter_type"] == adapter_type for m in matrices) != 1:
            raise AdapterProfileValidationError(
                f"Slice 3B.1 requires exactly one {adapter_type} profile"
            )
    for matrix in matrices:
        if matrix["output_mode"] != "mock":
            raise AdapterProfileValidationError(
                "Slice 3B.1 profiles must use output_mode=mock"
            )
        if matrix["provider_free_test_support"] is not True:
            raise AdapterProfileValidationError(
                "Slice 3B.1 profiles require provider_free_test_support=true"
            )
        if matrix["real_live_support"] is not False:
            raise AdapterProfileValidationError(
                "Slice 3B.1 profiles require real_live_support=false"
            )
    qwen = next(m for m in matrices if m["adapter_type"] == "duplex_model")
    if qwen["supports_provider_native_audio_release"] is not False:
        raise AdapterProfileValidationError(
            "Slice 3B.1 native provider audio release must remain disabled"
        )
    return matrices
```

Route `RuntimeAdapterAssemblyConfig(stage="slice3b1_mock", ...)` through this
validator. Canonically encode the validated, sorted matrices and add a
SHA-256 `capability_matrix_digest` to the Slice 3B.1 snapshot only; do not put
capability bodies, endpoints, or booleans into the Journal event. Gate receives
the in-memory validated assembly result, recomputes the digest, compares it to
the recorded snapshot, and records its individual capability checks. This
binds authority without asking replay to infer booleans from the compact
snapshot.

Add Route Evidence and candidate-safety adapter events to
`ADAPTER_CALLBACK_EVENT_NAMES`; do not add Gate/output events because those
remain control-plane authority.

- [ ] **Step 6: Verify focused and legacy capabilities GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_capability_profile.py tests/adapters/test_parallel_fast_interaction_profile.py tests/adapters/test_route_evidence_profile.py tests/runtime/test_slice3b1_adapter_assembly.py tests/adapters/test_fast_interaction_capability.py tests/adapters/test_asr_adapter_profile.py tests/runtime/test_runtime_adapter_assembly.py -q
```

Expected: new mock profiles pass, `real_live_support=true` and native release
claims fail, the Slice 3B.1 snapshot digest is stable under input ordering and
changes when any capability fact changes, and all pre-Slice-3B profile tests
remain green.

- [ ] **Step 7: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/adapters/capabilities.py src/voice_agent/adapters/profiles.py src/voice_agent/adapters/asr_profile.py src/voice_agent/adapters/qwen_realtime/profile.py src/voice_agent/adapters/parallel_fast_interaction_profile.py src/voice_agent/adapters/route_evidence_profile.py src/voice_agent/runtime/assembly.py src/voice_agent/runtime/adapter_callback_boundary.py tests/adapters/qwen_realtime/test_capability_profile.py tests/adapters/test_parallel_fast_interaction_profile.py tests/adapters/test_route_evidence_profile.py tests/runtime/test_slice3b1_adapter_assembly.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 3: Define the typed Qwen protocol and Fake/Real-shared transport contract

**Files:**

- Create: `src/voice_agent/adapters/qwen_realtime/__init__.py`
- Create: `src/voice_agent/adapters/qwen_realtime/protocol.py`
- Create: `src/voice_agent/adapters/qwen_realtime/transport.py`
- Create: `src/voice_agent/adapters/qwen_realtime/projections.py`
- Create: `tests/adapters/qwen_realtime/test_protocol.py`
- Create: `tests/adapters/qwen_realtime/test_transport_contract.py`
- Create: `tests/adapters/qwen_realtime/transport_contract_suite.py`

**Interfaces:**

- Produces `QwenClientEvent`, `QwenServerEvent`,
  `QwenSessionConfiguration`, `encode_client_event(...)`,
  `parse_server_event(...)`, `safe_wire_metadata(...)`, and
  `QwenRealtimeTransport`.
- Produces `QwenProjectionFrameV1` and
  `QwenProjectionSink.accept(frame) -> Awaitable[None]`.
- Produces a factory-driven
  `exercise_qwen_transport_contract(factory, driver) -> None` test helper that
  Slice 3B.1 Fake and future Slice 3B.2 Real transport tests invoke unchanged.
- Neither wire type nor transport contains local generation, turn, utterance,
  playback epoch, context snapshot, route, or Gate fields.

- [ ] **Step 1: Write RED protocol tests for the exact allowlists**

Freeze the allowlists in the test:

```python
SLICE3B1_CLIENT_EVENT_TYPES = frozenset({
    "session.update",
    "input_audio_buffer.append",
    "response.cancel",
    "conversation.item.delete",
})
SLICE3B1_SERVER_EVENT_TYPES = frozenset({
    "session.created",
    "session.updated",
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.committed",
    "conversation.item.created",
    "conversation.item.deleted",
    "conversation.item.input_audio_transcription.delta",
    "conversation.item.input_audio_transcription.completed",
    "conversation.item.input_audio_transcription.failed",
    "conversation.item.ambient_audio_transcription.delta",
    "conversation.item.ambient_audio_transcription.completed",
    "response.created",
    "response.output_item.added",
    "response.content_part.added",
    "response.audio_transcript.delta",
    "response.audio.delta",
    "response.audio_transcript.done",
    "response.audio.done",
    "response.content_part.done",
    "response.output_item.done",
    "response.done",
    "error",
})
```

Assert unknown types, missing/empty `event_id`, malformed response/item/index
identity, and `speech_stopped` without a valid reason fail closed. Assert
`input_audio_buffer.commit`, `response.create`, and `conversation.item.create`
are outside 3B.1 conformance.

- [ ] **Step 2: Run protocol tests and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_protocol.py tests/adapters/qwen_realtime/test_transport_contract.py -q
```

Expected: import failure because the typed protocol does not exist.

- [ ] **Step 3: Implement immutable wire types and strict parsing**

Use frozen, slot-based dataclasses with payload-bearing fields marked
`repr=False`. The public union must be:

```python
QwenClientEvent = (
    SessionUpdateClientEvent
    | InputAudioBufferAppendClientEvent
    | ResponseCancelClientEvent
    | ConversationItemDeleteClientEvent
)

QwenServerEvent = (
    SessionCreatedServerEvent
    | SessionUpdatedServerEvent
    | SpeechStartedServerEvent
    | SpeechStoppedServerEvent
    | InputAudioCommittedServerEvent
    | ConversationItemCreatedServerEvent
    | ConversationItemDeletedServerEvent
    | InputTranscriptionDeltaServerEvent
    | InputTranscriptionCompletedServerEvent
    | InputTranscriptionFailedServerEvent
    | AmbientTranscriptionDeltaServerEvent
    | AmbientTranscriptionCompletedServerEvent
    | ResponseCreatedServerEvent
    | ResponseOutputItemAddedServerEvent
    | ResponseContentPartAddedServerEvent
    | ResponseAudioTranscriptDeltaServerEvent
    | ResponseAudioDeltaServerEvent
    | ResponseAudioTranscriptDoneServerEvent
    | ResponseAudioDoneServerEvent
    | ResponseContentPartDoneServerEvent
    | ResponseOutputItemDoneServerEvent
    | ResponseDoneServerEvent
    | ErrorServerEvent
)
```

`QwenSessionConfiguration` must compare an exact normalized echo of:

```text
turn_detection.type=smart_turn
modalities
voice
input_audio_transcription
tools
fast_role_profile
```

`safe_wire_metadata` returns only event type, opaque refs, indexes, terminal
enums, byte count, virtual offset, and output mode. It never returns transcript
or PCM values.

- [ ] **Step 4: Define the shared transport and ordered projection sink**

Use the accepted behavioral contract:

```python
@dataclass(frozen=True, slots=True)
class SpeechBoundaryProjectionV1:
    provider_session_generation: int
    boundary: Literal["STARTED", "STOPPED"]
    qwen_input_item_ref: str
    observed_audio_sample_offset: int
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FinalASRReadyProjectionV1:
    provider_session_generation: int
    qwen_input_item_ref: str
    qwen_input_content_index: int
    turn_id: str
    utterance_id: str
    transcript_ref: str
    transcript_digest: str
    transcript_unicode_scalar_count: int


@dataclass(frozen=True, slots=True)
class AmbientTerminalProjectionV1:
    provider_session_generation: int
    temporary_item_ref: str
    terminal_status: Literal["completed", "failed"]


@dataclass(frozen=True, slots=True)
class ProviderContextProjectionV1:
    provider_session_generation: int
    playback_epoch: int
    interaction_state_version: int
    from_state: str
    to_state: str
    reason: str
    dropped_audio_frame_count: int


@dataclass(frozen=True, slots=True)
class RebuildRequestedProjectionV1:
    provider_session_generation: int
    reason: str
    source_event_id_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateObservationProjectionV1:
    provider_session_generation: int
    candidate_id: str
    qwen_response_id: str
    observation: Literal[
        "OPENED", "DISCARDED", "CANCELLED",
    ]
    candidate_ref: str | None = None
    candidate_transcript_digest: str | None = None
    candidate_pcm_manifest_digest: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateEligibilityFactsV1:
    provider_session_generation: int
    qwen_response_id: str
    qwen_output_item_id: str
    qwen_output_index: int
    qwen_content_index: int
    candidate_id: str
    turn_id: str
    utterance_id: str
    context_snapshot_id: str
    bound_playback_epoch: int
    candidate_transcript_digest: str
    candidate_unicode_scalar_count: int
    candidate_pcm_manifest_digest: str
    candidate_audio_format_ref: str
    candidate_audio_duration_ms: int
    provider_terminal_status: Literal["completed"]


@dataclass(frozen=True, slots=True)
class CandidateTranscriptCompleteV1:
    provider_session_generation: int
    qwen_response_id: str
    candidate_id: str
    turn_id: str
    utterance_id: str
    context_snapshot_id: str
    candidate_ref: str = field(repr=False)
    candidate_transcript_digest: str
    candidate_unicode_scalar_count: int


@dataclass(frozen=True, slots=True)
class CandidateCompletionV1:
    candidate_ref: str = field(repr=False)
    eligibility_facts: CandidateEligibilityFactsV1


QwenProjectionFrameV1 = (
    SpeechBoundaryProjectionV1
    | FinalASRReadyProjectionV1
    | AmbientTerminalProjectionV1
    | ProviderContextProjectionV1
    | RebuildRequestedProjectionV1
    | CandidateObservationProjectionV1
    | CandidateTranscriptCompleteV1
    | CandidateCompletionV1
)


class QwenRealtimeTransport(Protocol):
    async def open(self) -> None: ...
    async def send(self, event: QwenClientEvent) -> None: ...
    async def recv(self) -> QwenServerEvent: ...
    async def close(self) -> None: ...


class QwenProjectionSink(Protocol):
    async def accept(self, frame: QwenProjectionFrameV1) -> None: ...
```

`open()` returns no server event. `session.created` must be obtained through
`recv()`. Reserve no generation field on the transport.

The completion frames are safe control-plane handoffs, not provider wire
events. They contain exact identities, refs, digests, bounds, and terminal
facts only—never transcript text, PCM, resolver objects, or handles. Task 5
imports these frozen types into Quarantine; Task 6 emits each through the
single ordered projection sink exactly once; Task 10 consumes them without
reaching into Adapter internals.

- [ ] **Step 5: Add leakage and transport-shape tests**

Use sentinel transcript and PCM values and assert:

```python
def test_payloads_are_absent_from_repr_and_safe_metadata() -> None:
    event = response_audio_delta(
        event_id="provider_evt_1",
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        pcm=bytearray(b"\x13\x37"),
    )
    assert "1337" not in repr(event)
    assert "pcm" not in repr(event).lower()
    assert "audio" not in safe_wire_metadata(event)
```

Also use a spy transport to prove `open()` returns `None` and the first
provider event arrives only through `recv()`.

Place transport behavior assertions in
`tests/adapters/qwen_realtime/transport_contract_suite.py`, parameterized by a
transport factory and a driver that supplies deterministic server events. It
must cover open/send/recv/close shape, allowed client events, typed server
events, terminal close behavior, and safe exception projection. The Task 3 spy
invokes the suite now; Task 4 invokes the exact same suite with
`ScriptedFakeQwenWire`. Slice 3B.2 must invoke it with the Real transport before
claiming protocol replacement.

- [ ] **Step 6: Verify protocol GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_protocol.py tests/adapters/qwen_realtime/test_transport_contract.py -q
```

Expected: all allowlist, schema, leakage, and reusable transport-contract tests
pass against the spy.

- [ ] **Step 7: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/adapters/qwen_realtime/__init__.py src/voice_agent/adapters/qwen_realtime/protocol.py src/voice_agent/adapters/qwen_realtime/transport.py src/voice_agent/adapters/qwen_realtime/projections.py tests/adapters/qwen_realtime/test_protocol.py tests/adapters/qwen_realtime/test_transport_contract.py tests/adapters/qwen_realtime/transport_contract_suite.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 4: Build the deterministic scripted Fake wire and virtual scheduler

**Files:**

- Create: `src/voice_agent/adapters/qwen_realtime/scenarios.py`
- Create: `src/voice_agent/adapters/qwen_realtime/scripted_wire.py`
- Create: `tests/adapters/qwen_realtime/test_scripted_wire.py`
- Create: `tests/adapters/qwen_realtime/test_scripted_wire_security.py`

**Interfaces:**

- Produces `WireStep`, `QwenWireScript`, `SyntheticPayloadKind`,
  `get_qwen_wire_script(scenario_id: str) -> QwenWireScript`,
  `ScriptedFakeQwenWire`, `release_next_server_event()`, and
  `safe_timeline()`.
- `ScriptedFakeQwenWire` satisfies `QwenRealtimeTransport`; Fake-only release
  controls are not added to the shared transport protocol.
- `test_scripted_wire.py` invokes the unchanged
  `exercise_qwen_transport_contract(...)` suite from Task 3 with a Fake factory
  and permit driver.
- Scenario definitions contain no PCM bytes/base64, prompt, credential,
  unrestricted transcript, real-user text, or local path.

- [ ] **Step 1: Write RED tests for deterministic permit-driven behavior**

Use `asyncio.run` rather than adding an async test dependency:

```python
def test_open_then_recv_yields_session_created_only_after_release() -> None:
    async def scenario() -> None:
        wire = ScriptedFakeQwenWire(
            get_qwen_wire_script("bootstrap_requires_session_update")
        )
        assert await wire.open() is None
        recv_task = asyncio.create_task(wire.recv())
        await asyncio.sleep(0)
        assert not recv_task.done()
        wire.release_next_server_event()
        assert (await recv_task).type == "session.created"
    asyncio.run(scenario())


def test_multiple_audio_appends_have_no_per_frame_ack() -> None:
    async def scenario() -> None:
        wire = await opened_ready_wire("multiple_audio_appends_without_ack")
        await wire.send(InputAudioBufferAppendClientEvent(
            pcm16le=bytearray(b"\x00\x00")
        ))
        await wire.send(InputAudioBufferAppendClientEvent(
            pcm16le=bytearray(b"\x01\x00")
        ))
        assert [row["direction"] for row in wire.safe_timeline()][-2:] == [
            "client", "client"
        ]
    asyncio.run(scenario())
```

Define the test-local readiness helper explicitly:

```python
async def opened_ready_wire(scenario_id: str) -> ScriptedFakeQwenWire:
    wire = ScriptedFakeQwenWire(get_qwen_wire_script(scenario_id))
    await wire.open()
    wire.release_next_server_event()
    created = await wire.recv()
    assert created.type == "session.created"
    await wire.send(SessionUpdateClientEvent(configuration=TEST_CONFIGURATION))
    wire.release_next_server_event()
    updated = await wire.recv()
    assert updated.type == "session.updated"
    return wire
```

Add deterministic rerun, strict next-client-step matching, no `route.proposed`,
no local IDs, and no wall-clock/sleep/random/environment/network tests.

- [ ] **Step 2: Run Fake tests and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_scripted_wire.py tests/adapters/qwen_realtime/test_scripted_wire_security.py -q
```

Expected: import failure because the Fake wire does not exist.

- [ ] **Step 3: Implement safe wire script types**

Use:

```python
@dataclass(frozen=True, slots=True)
class WireStep:
    wire_seq: int
    virtual_ms: int
    direction: Literal["client", "server"]
    event_template: ClientEventTemplate | ServerEventTemplate


@dataclass(frozen=True, slots=True)
class QwenWireScript:
    scenario_id: str
    steps: tuple[WireStep, ...]
    fixture_domain: Literal["GITHUB_ALLOWED"] = "GITHUB_ALLOWED"
    generated_from: Literal["synthetic"] = "synthetic"
    scenario_source: Literal["SYNTHETIC"] = "SYNTHETIC"
```

Templates carry symbolic `SyntheticPayloadKind`, safe opaque IDs, indexes,
byte counts, duration, and terminal enums. At release time, a private
materializer creates bounded synthetic transcript fragments and wipeable PCM
`bytearray` values in memory. No materialized payload is stored back into the
script.

- [ ] **Step 4: Implement `ScriptedFakeQwenWire`**

Required behavior:

```python
class ScriptedFakeQwenWire(QwenRealtimeTransport):
    async def open(self) -> None: ...
    async def send(self, event: QwenClientEvent) -> None: ...
    async def recv(self) -> QwenServerEvent: ...
    async def close(self) -> None: ...
    def release_next_server_event(self) -> int: ...
    def safe_timeline(self) -> tuple[dict[str, object], ...]: ...
```

- `send()` consumes and exactly matches the next client step;
- `recv()` blocks on an internal queue and has no timeout/sleep;
- `release_next_server_event()` advances directly to the step's `virtual_ms`
  and enqueues one materialized event;
- `session.updated` cannot be released before a matching `session.update`
  client step has been consumed;
- `close()` wakes a blocked `recv()` with a typed closed-transport error and
  wipes any queued PCM;
- safe timeline rows contain `wire_seq`, `virtual_ms`, direction, type, opaque
  refs, indexes, byte counts, terminal enums, and `output_mode=mock` only.

- [ ] **Step 5: Verify Fake GREEN and source safety**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_scripted_wire.py tests/adapters/qwen_realtime/test_scripted_wire_security.py -q
```

Expected: deterministic tests pass twice with identical timelines; the shared
transport conformance suite passes against Fake; security tests prove no
environment, socket, provider SDK, `asyncio.sleep`, raw audio fixture, or route
event is used.

- [ ] **Step 6: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/adapters/qwen_realtime/scenarios.py src/voice_agent/adapters/qwen_realtime/scripted_wire.py tests/adapters/qwen_realtime/test_scripted_wire.py tests/adapters/qwen_realtime/test_scripted_wire_security.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.
### Task 5: Implement two-stage Candidate Quarantine and wipeable PCM ownership

**Files:**

- Create: `src/voice_agent/adapters/qwen_realtime/quarantine.py`
- Create: `src/voice_agent/adapters/qwen_realtime/ephemeral_text_store.py`
- Create: `tests/adapters/qwen_realtime/test_candidate_quarantine.py`
- Create: `tests/adapters/qwen_realtime/test_candidate_quarantine_security.py`
- Create: `tests/adapters/qwen_realtime/test_ephemeral_text_store.py`

**Interfaces:**

- Produces `CandidateQuarantine`, `CommittedCandidateBinding`,
  `CandidateDispositionV1`, `CandidatePCMManifestV1`, and
  `WipeablePCMBuffer`; it consumes/re-exports the completion and eligibility
  projection types frozen in Task 3 rather than redefining them.
- Produces `EphemeralTextStore`, `EphemeralTextRefV1`, and a scoped
  `SensitiveTextLease` resolver for ASR and candidate text.
- `CandidateQuarantine` exposes
  `open_response(...)`, `accept_assistant_item(...)`,
  `accept_output_item(...)`, `accept_content_part(...)`,
  `bind_committed_turn(...)`, `append_transcript_delta(...)`,
  `append_pcm_delta(...)`, `mark_transcript_done(...)`,
  `mark_audio_done(...)`, `mark_content_done(...)`,
  `mark_output_item_done(...)`, `mark_response_done(...)`,
  `transcript_completion()`, `completion()`, and `discard(...)`.
- Quarantine opens at `response.created` without requiring a local turn. It
  binds `turn_id`, `utterance_id`, and `context_snapshot_id` exactly once only
  after canonical local commit.
- Transcript-complete and full-completion objects expose the same opaque
  `candidate_ref`, immutable digest, and Unicode scalar count. Candidate text
  resolves only through a scoped store lease. PCM remains owned inside
  Quarantine; completion returns metadata, never the PCM handle.

- [ ] **Step 1: Write RED tests for provisional and committed binding**

Start with the two legal item/output orders and both commit schedules:

```python
TEST_LIMITS = CandidateLimitsV1(
    max_transcript_unicode_scalars=80,
    max_pcm_bytes=4096,
    max_pcm_chunks=8,
    max_audio_duration_ms=2000,
)

def apply_provider_order(
    quarantine: CandidateQuarantine,
    provider_order: str,
) -> None:
    assistant = {
        "event_id": "provider_evt_assistant_item",
        "response_id": "resp_1",
        "item_id": "item_1",
        "item_type": "message",
        "role": "assistant",
    }
    output = {
        "event_id": "provider_evt_output_item",
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "item_type": "message",
    }
    if provider_order == "assistant_item_then_output_item":
        quarantine.accept_assistant_item(**assistant)
        quarantine.accept_output_item(**output)
    else:
        quarantine.accept_output_item(**output)
        quarantine.accept_assistant_item(**assistant)
    quarantine.accept_content_part(
        event_id="provider_evt_content",
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        content_type="audio",
    )

@pytest.mark.parametrize(
    "provider_order",
    ("assistant_item_then_output_item", "output_item_then_assistant_item"),
)
def test_response_can_start_before_commit_and_join_exactly_once(
    provider_order: str,
) -> None:
    quarantine = CandidateQuarantine(limits=TEST_LIMITS)
    quarantine.open_response(
        generation=1,
        response_id="resp_1",
        candidate_id="cand_1",
        playback_epoch=4,
        provisional_ingress_id="ingress_1",
        input_item_ref="qwen-input://synthetic/1",
    )
    apply_provider_order(quarantine, provider_order)
    quarantine.bind_committed_turn(
        CommittedCandidateBinding(
            turn_id="turn_1",
            utterance_id="utt_1",
            context_snapshot_id="context_1",
        )
    )
    with pytest.raises(CandidateQuarantineError, match="immutable"):
        quarantine.bind_committed_turn(
            CommittedCandidateBinding(
                turn_id="turn_2",
                utterance_id="utt_2",
                context_snapshot_id="context_2",
            )
        )
```

Add legal transcript/audio interleaving and require all terminal events plus
`response.done(status=completed)` before full completion freezes. Separately,
after transcript terminal plus local binding, assert
`transcript_completion()` returns one immutable digest while
`completion()` is still `None` until PCM/content/output/response terminals
arrive.

- [ ] **Step 2: Run the basic Quarantine test and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_candidate_quarantine.py -q
```

Expected: import failure because Quarantine does not exist.

- [ ] **Step 3: Implement immutable identities and wipeable memory**

Import the completion projection types frozen in Task 3; do not redefine them
inside Quarantine. Add only the local binding type:

```python
@dataclass(frozen=True, slots=True)
class CommittedCandidateBinding:
    turn_id: str
    utterance_id: str
    context_snapshot_id: str
```

`CandidateEligibilityFactsV1` contains only exact provider/local correlation,
digests, Unicode scalar count, decoded duration, audio format, and terminal
status. It contains no text, PCM, resolver, or mutable handle and is the only
Quarantine object accepted by Gate-context construction.

Quarantine retains the `WipeablePCMBuffer` until terminal discard or a future
reviewed native-release redemption API presents the exact release authority.
Slice 3B.1 defines no public redemption API because its authoritative
capability is disabled. The private mock-contract harness creates its own
synthetic wipeable handle; it never extracts Qwen candidate PCM.

`WipeablePCMBuffer` stores `bytearray`, returns no bytes from `repr`, and
overwrites every byte with zero in `release()`. Its destructor is only a
last-resort cleanup; all terminal paths and the runner `finally` must call
`release()` explicitly.

`EphemeralTextStore` is injected into both Session Adapter and Quarantine. It:

```python
class EphemeralTextStore:
    def put(
        self,
        *,
        kind: Literal["asr", "candidate"],
        ref: str,
        normalized_text: str,
        max_unicode_scalars: int,
    ) -> EphemeralTextRefV1: ...

    @contextmanager
    def resolve(
        self,
        ref: str,
        *,
        expected_kind: Literal["asr", "candidate"],
        expected_digest: str,
        max_unicode_scalars: int,
    ) -> Iterator[SensitiveTextLease]: ...

    def discard(self, ref: str) -> None: ...
    def close(self) -> None: ...
```

The store keeps UTF-8 in a wipeable `bytearray`, never returns text from
`repr`, diagnostics, exceptions, events, fixtures, or result serialization,
and overwrites storage on discard/close. A lease is valid only inside the
adapter call, checks kind/digest/bounds, and cannot be retained. The
provider-free runner assigns opaque `text-ref://synthetic/...` and
`candidate-ref://synthetic/...` refs when inserting the text; a future Real
runtime uses local-only refs. Shareable fixtures preserve the already-safe
synthetic refs without rewriting canonical events and never provide a
resolver.

`CandidateTranscriptCompleteV1` freezes exactly once after transcript terminal
and canonical local binding, even if PCM is still arriving. It permits
Candidate Safety to run in parallel with remaining PCM. It is not full
candidate eligibility; Quarantine emits `CandidateCompletionV1(candidate_ref,
eligibility_facts)` only after every audio, content, output-item, and response
terminal.

- [ ] **Step 4: Implement lifecycle and correlation validation**

The state machine must:

- require a non-empty, generation-unique provider `event_id` for every accepted
  frame;
- bind response, assistant item, output index, and content index monotonically
  and immutably;
- join assistant `conversation.item.created` and
  `response.output_item.added` by exact item ID in either order;
- accept exactly one assistant `message` output item and one `audio` content
  part;
- reject function calls, extra output/content, wrong
  generation/response/item/output/content identity, duplicate event ID,
  terminal mismatch, delta after terminal, missing terminal, and second
  response;
- assign local `pcm_chunk_seq` in observed Pump order only;
- compute transcript digest from the complete in-memory normalized transcript;
- compute PCM manifest digest from format, rate, channels, observed local chunk
  sequence, byte counts, duration, and rolling PCM content digest;
- never claim arbitrary provider-side missing/reorder detection;
- wipe and permanently disqualify on overflow or invalid correlation.

Freeze bounded defaults:

```python
CandidateLimitsV1(
    max_transcript_unicode_scalars=80,
    max_pcm_bytes=192_000,
    max_pcm_chunks=256,
    max_audio_duration_ms=2_000,
)
```

Count Unicode scalar values after the same normalization used for the digest
and reject unpaired surrogate code points. A limit larger than 80 is invalid,
including in test configuration. Text with 81 scalar values never yields
`CandidateTranscriptCompleteV1` or `CandidateCompletionV1`.

- [ ] **Step 5: Add the full fail-closed matrix**

Use a parameterized corruptor table with these exact case IDs:

```python
CORRELATION_FAILURE_CASES = (
    "wrong_response_id",
    "wrong_output_item_id",
    "wrong_output_index",
    "wrong_content_index",
    "duplicate_provider_audio_event_id",
    "audio_delta_after_audio_done",
    "cross_content_audio_delta",
    "extra_output_item",
    "extra_content_part",
    "function_call_output_ineligible",
    "response_done_output_item_mismatch",
    "missing_audio_done",
    "missing_response_terminal",
    "response_failed",
    "quarantine_overflow",
)
```

Add explicit `candidate_81_unicode_scalars` and stale/missing text-ref cases.
For every case assert: no `CandidateCompletionV1`, terminal disposition is
discarded/ineligible, the PCM handle is released, and no raw payload appears in
exception text or object `repr`.

- [ ] **Step 6: Verify Quarantine GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_candidate_quarantine.py tests/adapters/qwen_realtime/test_candidate_quarantine_security.py tests/adapters/qwen_realtime/test_ephemeral_text_store.py -q
```

Expected: all legal partial orders complete with stable digests and resolvable
scoped refs; every detectable invalid path fails closed and wipes PCM/text.

- [ ] **Step 7: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/adapters/qwen_realtime/quarantine.py src/voice_agent/adapters/qwen_realtime/ephemeral_text_store.py tests/adapters/qwen_realtime/test_candidate_quarantine.py tests/adapters/qwen_realtime/test_candidate_quarantine_security.py tests/adapters/qwen_realtime/test_ephemeral_text_store.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 6: Implement one serialized sender, one Pump, strict readiness, and runtime-owned generation

**Files:**

- Create: `src/voice_agent/adapters/qwen_realtime/session_adapter.py`
- Create: `src/voice_agent/runtime/qwen_realtime_session.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Create: `tests/adapters/qwen_realtime/test_session_adapter_handshake.py`
- Create: `tests/adapters/qwen_realtime/test_session_adapter_partial_order.py`
- Create: `tests/adapters/qwen_realtime/test_session_adapter_ambient_cancel.py`
- Create: `tests/interaction/test_playback_epoch_authority.py`
- Create: `tests/runtime/test_qwen_realtime_session.py`
- Regression test: `tests/interaction/test_barge_in_truncate.py`

**Interfaces:**

- Produces `QwenRealtimeSessionAdapter` and
  `QwenRealtimeSessionRuntime`.
- Adapter methods:

```python
def fence_for_generation(
    self, *, generation: int, playback_epoch: int
) -> None: ...
async def attach_open_transport(
    self, transport: QwenRealtimeTransport
) -> None: ...
async def stop_pump(self) -> None: ...
async def append_audio(self, pcm16le: bytes | bytearray | memoryview) -> bool: ...
async def cancel_active_response(self) -> bool: ...
async def delete_assistant_item(self, item_id: str) -> bool: ...
def bind_committed_turn(
    self,
    *,
    input_item_ref: str,
    binding: CommittedCandidateBinding,
) -> ASRJoinDispositionV1: ...
```

- Runtime methods:

```python
async def connect(self) -> int: ...
async def rebuild(self, *, reason: str) -> int: ...
async def close(self) -> None: ...
async def dispose_resources(self) -> None: ...
```

`close()` is a logical scenario action: it appends/transitions provider context
to canonical `CLOSED`, then disposes resources. `dispose_resources()` is
harness-only idempotent cleanup: it stops Pump/sender, closes the transport,
wipes Quarantine/text stores, and marks the Python object disposed without
appending events or changing the already-captured logical scenario result.

No Session Runtime API accepts a caller-supplied playback epoch. The injected,
long-lived `InteractionController` exposes:

```python
@dataclass(frozen=True, slots=True)
class InteractionEpochSnapshot:
    playback_epoch: int
    interaction_state_version: int

def current_epoch_snapshot(self) -> InteractionEpochSnapshot: ...

def advance_playback_epoch_for_provider_rebuild(
    self,
    *,
    provider_session_generation: int,
    reason: str,
) -> InteractionEpochSnapshot: ...
```

The controller is the only mutator. Every rebuild result must be strictly
greater in both epoch and state version than its predecessor.
`request_truncate_for_barge_in(...)` uses the same private epoch-advance
primitive before appending the existing interrupt/truncate chain and records
the resulting `playback_epoch` and `interaction_state_version` as additional
safe fields. Provider cancellation never advances the local epoch.

- `ASRJoinDispositionV1` is:

```python
@dataclass(frozen=True, slots=True)
class ASRJoinDispositionV1:
    status: Literal["WAITING_PROVIDER_FINAL", "READY", "REJECTED"]
    final_asr_projection: FinalASRReadyProjectionV1 | None
```

- Adapter emits ordered safe projection frames through one sink. It never
  appends raw provider events to the journal and never increments generation.
- Session Adapter receives the single session-scoped `CandidateQuarantine` and
  `EphemeralTextStore` by dependency injection. Quarantine remains the sole
  lifecycle/PCM owner; the Adapter emits its safe
  `CandidateTranscriptCompleteV1` and `CandidateCompletionV1` values through
  the same ordered `QwenProjectionSink` exactly once.

- [ ] **Step 1: Write RED generation-ownership tests**

Use a spy factory/transport:

```python
class LifecycleSpyAdapter:
    def __init__(self, observed: list[tuple[str, int]]) -> None:
        self.observed = observed
        self.generation = 0
        self.provider_context_state = "CLOSED"

    def fence_for_generation(
        self, *, generation: int, playback_epoch: int
    ) -> None:
        self.generation = generation
        self.provider_context_state = "REBUILDING"
        self.observed.append(("fence", generation))

    async def stop_pump(self) -> None:
        return None

    async def attach_open_transport(
        self, transport: QwenRealtimeTransport
    ) -> None:
        return None


class LifecycleSpyTransport:
    def __init__(
        self,
        observed: list[tuple[str, int]],
        adapter: LifecycleSpyAdapter,
        *,
        fail_open: bool = False,
    ) -> None:
        self.observed = observed
        self.adapter = adapter
        self.fail_open = fail_open

    async def open(self) -> None:
        self.observed.append(("open", self.adapter.generation))
        if self.fail_open:
            raise OSError("synthetic open failure")

    async def send(self, event: QwenClientEvent) -> None:
        raise AssertionError("lifecycle test does not send")

    async def recv(self) -> QwenServerEvent:
        raise AssertionError("lifecycle test does not receive")

    async def close(self) -> None:
        return None


def test_runtime_advances_generation_before_open() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(observed, adapter),
            interaction_controller=InteractionController(parallel_journal()),
        )
        generation = await runtime.connect()
        assert generation == 1
        assert observed[:2] == [("fence", 1), ("open", 1)]
    asyncio.run(scenario())


def test_open_failure_keeps_advanced_generation_non_clean() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, int]] = []
        adapter = LifecycleSpyAdapter(observed)
        runtime = QwenRealtimeSessionRuntime(
            adapter=adapter,
            transport_factory=lambda: LifecycleSpyTransport(
                observed, adapter, fail_open=True
            ),
            interaction_controller=InteractionController(parallel_journal()),
        )
        with pytest.raises(QwenSessionRuntimeError, match="open"):
            await runtime.connect()
        assert runtime.provider_session_generation == 1
        assert runtime.provider_context_state != "CLEAN"
    asyncio.run(scenario())
```

Add rebuild-before-open generation 2, at-most-one-active-handle, concurrent
rebuild serialization/coalescing, old Pump fencing, and recovery-audio
drop-never-replay assertions. A lifecycle spy must prove this exact rebuild
order:

```text
allocate generation 2
Interaction Controller advances epoch 0 -> 1 and state version 0 -> 1
append PROVIDER_CONTEXT_STATE_CHANGED(... to_state=REBUILDING,
  provider_session_generation=2, playback_epoch=1,
  interaction_state_version=1)
Adapter fence(generation=2, playback_epoch=1)
stop old Pump / close old transport
open new transport
```

Tests reject an unchanged, decreasing, externally supplied, or
Adapter-incremented epoch. Initial Connect binds
`InteractionController.current_epoch_snapshot()` without advancing it and
records that binding on `CLOSED -> REBUILDING`.

`tests/interaction/test_playback_epoch_authority.py` also proves that a local
barge-in increments epoch/state version before `INTERRUPT_CANDIDATE` and
`TTS_TRUNCATE_REQUESTED`, while `response.done(cancelled)` alone does not.
Legacy barge-in behavior and event names remain unchanged.

- [ ] **Step 2: Write RED handshake and single-Pump tests**

Cover:

```text
bootstrap_requires_session_update
session_created_defaults_not_authority
session_updated_session_id_mismatch
session_updated_configuration_mismatch
missing_or_duplicate_server_event_id
audio_append_before_clean_dropped
```

Use a transport spy that records maximum concurrent `recv()` and `send()`:

```python
assert spy.max_concurrent_recv == 1
assert spy.max_concurrent_send == 1
assert adapter.provider_context_state == "CLEAN"
```

Require exact full configuration echo before `CLEAN`; updated-before-created,
duplicate created, mismatch, or handshake `error` must move to `TAINTED` and
request serialized rebuild.

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/runtime/test_qwen_realtime_session.py tests/interaction/test_playback_epoch_authority.py tests/adapters/qwen_realtime/test_session_adapter_handshake.py -q
```

Expected: import failure because runtime and adapter do not exist.

- [ ] **Step 4: Implement the runtime lifecycle lock**

Within one `asyncio.Lock`:

```python
async def _replace_transport(self, *, reason: str, is_rebuild: bool) -> int:
    self._generation += 1
    generation = self._generation
    previous = self._interaction_controller.current_epoch_snapshot()
    epoch = (
        self._interaction_controller
        .advance_playback_epoch_for_provider_rebuild(
            provider_session_generation=generation,
            reason=reason,
        )
        if is_rebuild
        else previous
    )
    if is_rebuild and epoch.playback_epoch <= previous.playback_epoch:
        raise QwenSessionRuntimeError("playback epoch did not advance")
    self._append_provider_rebuilding(
        generation=generation,
        epoch=epoch,
        reason=reason,
    )
    self._adapter.fence_for_generation(
        generation=generation,
        playback_epoch=epoch.playback_epoch,
    )
    await self._adapter.stop_pump()
    if self._active_transport is not None:
        await self._active_transport.close()
    transport = self._transport_factory()
    self._active_transport = transport
    await transport.open()
    await self._adapter.attach_open_transport(transport)
    return generation
```

Advance and journal the Interaction Controller-owned epoch before Adapter
fencing, stopping, or opening. There is no `await` between the epoch mutation,
the canonical `REBUILDING` append, and Adapter fence. If the append fails, do
not fence or open. If close/open fails later, keep the new generation/epoch and
a non-`CLEAN` state; never restore or reuse queued microphone frames. Logical
`close()` moves to `CLOSED` and then delegates cleanup to
`dispose_resources()`. The harness calls `dispose_resources()` directly after
its result/replay snapshot; both methods close at most one handle and wipe
adapter-owned PCM and ephemeral text.

Tests prove: logical close emits exactly one `PROVIDER_CONTEXT_STATE_CHANGED`
to `CLOSED`; repeated resource disposal emits nothing; disposal after a
pre-close `CLEAN` result does not change the returned
`provider_context_terminal_state`; and an explicit close scenario snapshots
`CLOSED`.

- [ ] **Step 5: Implement handshake, sender, and Pump**

The adapter state transitions are:

```text
CLOSED
  -> fence/open
REBUILDING + AWAITING_CREATED
  -> recv session.created
REBUILDING + UPDATE_SENT
  -> serialized send session.update
  -> recv exact session.updated
CLEAN + READY

CLEAN -> CLEANUP_PENDING -> matching delete ack -> CLEAN
CLEANUP_PENDING -> missing/wrong ack -> TAINTED -> rebuild requested
any state -> close -> CLOSED
```

All sends use one `_send_lock` and monotonically allocate `wire_send_seq`.
Exactly one `_run_pump` calls `recv()` and monotonically allocates
`provider_event_seq`. A second Pump start raises. Every received event is
bound to the already-current generation, then parsed and projected; late
old-generation frames are dropped before state mutation.

- [ ] **Step 6: Implement ASR join, ambient, invalid turn, cancel, and cleanup**

Required behavior:

- hold provider transcription final until matching local
  `TURN_INGRESS_COMMITTED`, or hold local commit until the provider final;
- store the bounded normalized ASR text in the injected
  `EphemeralTextStore` with the route policy's 2,000-scalar ceiling, then emit
  one `FinalASRReadyProjectionV1` containing only its opaque ref, digest, scalar
  count, and correlation after both predecessors exist;
- allow response/quarantine progress before that join;
- after transcript terminal plus canonical binding, emit exactly one
  `CandidateTranscriptCompleteV1` projection; after all provider terminals,
  emit exactly one `CandidateCompletionV1` projection; duplicate polling or
  terminal frames cannot emit either value twice;
- ambient delta/completed uses a temporary item, never binds a local turn,
  conversation item, route, candidate, or output authority;
- `speech_stopped(reason=turn_invalid)` retracts ingress, cancels/deletes
  speculation, and emits no final-ASR authority;
- provider auto-cancel terminal reason is `turn_detected`;
- explicit cancel terminal reason is `client_cancelled`;
- auto/explicit race emits one local terminal;
- late invalid-request error after terminal is non-terminal;
- cancel does not close the transport or advance generation;
- late PCM after cancel is dropped;
- missing terminal/delete ack triggers bounded timeout projection and rebuild
  request without using wall-clock sleep in Fake tests.

- [ ] **Step 7: Add partial-order and cancellation matrix tests**

Cover:

```text
multiple_audio_appends_without_ack
valid_turn_asr_before_response
valid_turn_response_starts_before_asr_final
transcript_and_pcm_interleave
assistant_item_created_before_output_item
output_item_before_assistant_item_created
second_active_response_rejected
ambient_audio_no_committed_turn
ambient_delta_completed_temporary_item
turn_invalid_no_commit_no_route_no_release
precommit_turn_rejected_cancel_delete
barge_in_provider_auto_cancel
barge_in_explicit_cancel
auto_and_explicit_cancel_race
late_explicit_cancel_invalid_request_is_not_terminal
late_old_pcm_after_cancel
missing_cancel_terminal
delete_ack_missing_rebuild
old_generation_event_after_rebuild
recovery_audio_dropped_never_replayed
```

Each test advances the Fake one server event at a time and inserts local commit,
cancel, delete, or rebuild between releases. Never assert on `wire_seq` inside
Adapter correlation. A collecting projection sink asserts the runner-visible
order and full safe identities of transcript-complete/full-complete frames,
including response/item/output/content, binding, duration, and eligibility,
without accessing the Adapter's private Quarantine.

- [ ] **Step 8: Verify session lifecycle GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_session_adapter_handshake.py tests/adapters/qwen_realtime/test_session_adapter_partial_order.py tests/adapters/qwen_realtime/test_session_adapter_ambient_cancel.py tests/interaction/test_playback_epoch_authority.py tests/interaction/test_barge_in_truncate.py tests/runtime/test_qwen_realtime_session.py -q
```

Expected: all readiness, one-Pump, generation, ASR-join, ambient, cancellation,
cleanup, and rebuild tests pass deterministically.

- [ ] **Step 9: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/adapters/qwen_realtime/session_adapter.py src/voice_agent/runtime/qwen_realtime_session.py src/voice_agent/interaction/controller.py tests/adapters/qwen_realtime/test_session_adapter_handshake.py tests/adapters/qwen_realtime/test_session_adapter_partial_order.py tests/adapters/qwen_realtime/test_session_adapter_ambient_cancel.py tests/interaction/test_playback_epoch_authority.py tests/interaction/test_barge_in_truncate.py tests/runtime/test_qwen_realtime_session.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 7: Add bounded context, independent Route Evidence, Local Router input, and join-only orchestration

**Files:**

- Create: `src/voice_agent/adapters/route_evidence_contract.py`
- Create: `src/voice_agent/adapters/route_evidence_fake.py`
- Create: `src/voice_agent/runtime/slice3b1/context_projection.py`
- Create: `src/voice_agent/runtime/slice3b1/orchestrator.py`
- Modify: `src/voice_agent/router/router.py`
- Create: `tests/adapters/test_route_evidence_fake.py`
- Create: `tests/runtime/test_slice3b1_context_projection.py`
- Create: `tests/runtime/test_slice3b1_orchestrator.py`
- Create: `tests/router/test_adr018_route_evidence_router.py`
- Regression test: `tests/router/test_router_task_focus_mvp1.py`
- Regression test: `tests/runtime/test_mvp63_live_fast_interaction_evidence.py`

**Interfaces:**

- Produces:

```python
class RouteEvidenceAdapter(Protocol):
    async def classify_route(
        self, request: RouteEvidenceRequestV1
    ) -> RouteEvidenceOutputV1: ...
    async def classify_candidate_safety(
        self, request: CandidateSafetyRequestV1
    ) -> CandidateSafetyEvidenceV1: ...
```

- Produces `build_context_projection(...) -> ModelContextProjectionV1`.
- Extends `MVP1Router.emit_decision(...)` with optional
  `route_evidence_output_event`.
- Produces `ParallelFastInteractionOrchestrator.emit(...)` that joins recorded
  evidence but never calls a model, decides a route, or releases output.
- Candidate Safety consumes `CandidateTranscriptCompleteV1` while PCM may
  still be accumulating; the orchestrator waits for the later
  `CandidateCompletionV1`.

- [ ] **Step 1: Write RED contract and context-projection tests**

Lock the request boundary:

```python
@dataclass(frozen=True, slots=True)
class RouteEvidenceRequestV1:
    adapter_request_id: str
    turn_id: str
    utterance_id: str
    final_asr_event_id: str
    transcript_ref: str
    asr_confidence: float | None
    duplex_hints_ref: str | None
    qwen_semantic_hints_ref: str | None
    context_projection_event_id: str
    context_snapshot_id: str
    active_task_public_snapshot_ref: str | None
    last_assistant_act: str
    expected_user_response: str | None
    policy_version: str


@dataclass(frozen=True, slots=True)
class CandidateSafetyRequestV1:
    adapter_request_id: str
    turn_id: str
    utterance_id: str
    qwen_response_id: str
    candidate_ref: str = field(repr=False)
    candidate_transcript_digest: str
    context_projection_event_id: str
    context_snapshot_id: str
    route_evidence_event_id: str | None
    task_focus_state_ref: str
    active_task_public_snapshot_ref: str | None
    policy_version: str
```

Assert route input contains no Qwen candidate, candidate-safety input contains
the completed candidate only through an ephemeral bounded `candidate_ref`,
contains no PCM, and neither contains raw prompt/provider state/tool
result/private reasoning. The Route Evidence Adapter resolves
`transcript_ref`/`candidate_ref` only inside the call boundary. Resolved text
is never copied into any canonical event, diagnostic, result, or fixture.
Route/Candidate-Safety evidence output events do not repeat the refs.

Safe opaque synthetic refs are intentionally allowed only at their canonical
ownership points: ASR `text_ref` and
`FOREGROUND_REPLY_CANDIDATE_EMITTED.candidate_ref`. Provider-free fixtures
preserve those refs so replay can validate identity without a store. After
`EphemeralTextStore.close()`, replay treats them as non-resolvable identity
metadata and must never attempt resolution. Local-only Real refs are forbidden
from `GITHUB_ALLOWED` fixtures.

The request refs must be the exact refs returned by the shared
`EphemeralTextStore`: canonical ASR `text_ref` and
`CandidateTranscriptCompleteV1.candidate_ref`. Tests cover missing, wrong-kind,
stale, digest-mismatched, over-bound, and already-discarded refs. The adapter
uses a scoped `SensitiveTextLease` and cannot retain it after either
classification call.

For `MODEL_CONTEXT_PROJECTION_EMITTED`, assert the projection is bound to
`source_event_seq`, `provider_session_generation`, role, immutable
`context_snapshot_id`, policy version, redaction status, and bounded refs.

Freeze the route projection policy:

```python
ROUTE_CONTEXT_POLICY_V1 = ContextProjectionLimitsV1(
    current_transcript_chars=2_000,
    recent_committed_items=4,
    recent_dialogue_summary_chars=2_000,
    active_task_public_summary_chars=1_000,
    session_memory_hint_count=5,
    session_memory_hint_chars=1_000,
    total_serialized_chars=8_192,
)
```

Only current-session committed items are eligible. There is no durable or
cross-session memory in Slice 3B.1.

- [ ] **Step 2: Run the contract tests and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/test_route_evidence_fake.py tests/runtime/test_slice3b1_context_projection.py -q
```

Expected: import failure because the contracts and projection builder do not
exist.

- [ ] **Step 3: Implement strict fake evidence schemas**

`RouteEvidenceOutputV1` fields:

```text
route_hint
task_focus_hint
foreground_act_hint
ack_kind
risk_class
risk_tags
evidence_uncertainty
confidence
schema_name=voice_agent.route_evidence.output.v1
normalization_status=normalized
output_mode=mock
```

`CandidateSafetyEvidenceV1` fields:

```text
decision=SAFE|UNSAFE|UNCERTAIN
semantic_categories
prohibited_flags
confidence
candidate_transcript_digest
schema_name=voice_agent.candidate_safety.output.v1
normalization_status=normalized
output_mode=mock
```

Fake directives are symbolic enums, not model text. Timeout, malformed JSON,
unknown enum, oversized categories, low route confidence, prohibited risk,
candidate `UNSAFE`/`UNCERTAIN`, or candidate timeout/malformed output yields a
typed fail-closed outcome.

- [ ] **Step 4: Emit canonical projections and evidence through serialized boundaries**

The context builder appends `MODEL_CONTEXT_PROJECTION_EMITTED` from canonical
state only. Route classification starts only after canonical
`ASR_TRANSCRIPT_OUTPUT_EMITTED` and the route projection. Candidate-safety
classification starts only after `CandidateTranscriptCompleteV1` and its
candidate-safety projection, but does not wait for PCM terminal. Append
evidence through
`AdapterCallbackAppendBoundary`; never append raw request/output objects.

Canonical final ASR copies the opaque store ref into the existing `text_ref`
field; it never copies the resolved transcript. Route Evidence resolves that
ref only for the duration of `classify_route`. Candidate Safety similarly
resolves the candidate ref. The runner `finally` closes the store after all
model-equivalent calls and replay serialization finish.

For a multi-predecessor join, set `caused_by_event_id` to the last material
predecessor and store the other predecessor IDs in explicit fields. Replay
validates all refs.

- [ ] **Step 5: Extend Local Router with a mutually exclusive evidence branch**

Add:

```python
def emit_decision(
    self,
    *,
    turn_committed_event: Mapping[str, Any],
    asr_frame_event: Mapping[str, Any] | None = None,
    thinker_frame_event: Mapping[str, Any] | None = None,
    fast_interaction_output_event: Mapping[str, Any] | None = None,
    route_evidence_output_event: Mapping[str, Any] | None = None,
    router_context: RouterContext,
    event_id: str,
    task_focus_state_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> MVP1RouterDecisionResult: ...
```

Rules:

- Route Evidence requires the matching canonical final ASR;
- it must match committed turn/utterance and name that ASR event;
- it must be normalized `adapter_type=route_evidence`;
- it is mutually exclusive with Thinker and legacy Fast Interaction route
  authority for this call;
- Local Router derives/validates the final route and focus;
- `ROUTER_DECISION_EMITTED.caused_by_event_id` and
  `route_evidence_event_id` reference the evidence event;
- no candidate field is accepted by the Router.

The existing `_validate_understanding_output_mode(...)` gains one narrowly
scoped branch: `ASR_TRANSCRIPT_OUTPUT_EMITTED(output_mode=mock)` is accepted
only when this call uses the new Route Evidence branch, all three Qwen
correlation fields are present, the ASR adapter ID matches the assembled
provider-free Qwen ASR profile, and the Route Evidence event is normalized
`output_mode=mock`. Legacy Thinker/Fast paths continue to reject mock canonical
ASR. Add positive and negative tests for every predicate so the change cannot
globally relax real ASR readiness.

- [ ] **Step 6: Implement the join-only orchestrator**

Use:

```python
@dataclass(frozen=True, slots=True)
class ParallelFastInteractionEmissionV1:
    fast_interaction_output_event: dict[str, Any]
    candidate_event: dict[str, Any]


class ParallelFastInteractionOrchestrator:
    def emit(
        self,
        *,
        final_asr_event: Mapping[str, Any],
        route_evidence_event: Mapping[str, Any],
        candidate_safety_event: Mapping[str, Any],
        candidate: CandidateCompletionV1,
        event_ids: ParallelEmissionEventIds,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> ParallelFastInteractionEmissionV1: ...
```

It reads only `candidate.candidate_ref` and
`candidate.eligibility_facts`, verifies exact turn, utterance, generation,
context snapshot, response/item/output/content, and transcript digest equality,
requires
`candidate_unicode_scalar_count <= 80` and
`candidate_audio_duration_ms <= 2_000`, and copies the opaque
`candidate_ref` into the existing candidate-ref field; then emits parallel
`FAST_INTERACTION_OUTPUT_EMITTED` followed by
`FOREGROUND_REPLY_CANDIDATE_EMITTED`. It copies evidence/provenance and safe
digests only. It never calls Qwen/Route Evidence, emits RouterDecision, or
invokes Gate.

- [ ] **Step 7: Add ordering, authority, and fail-closed tests**

Test:

```text
route_before_candidate_complete
candidate_before_route_complete
route_fast_only -> FAST_ONLY
route_spawn_slow_task -> SPAWN_SLOW_TASK
route_patch_active_slow_task -> PATCH_ACTIVE_SLOW_TASK
route_ignore -> IGNORE
active-task foreground chat
active-task patch
active-task new-task
active-task cancel/confirmation
active-task ambiguity
Route Evidence timeout/malformed/low-confidence/prohibited-risk
Candidate Safety SAFE/UNSAFE/UNCERTAIN/timeout/malformed
```

Assert Router may finish before candidate safety/composite, but Gate cannot run
until the joined candidate exists. Assert Qwen Fake has no route output and
Route Evidence never consumes candidate text for route classification.

- [ ] **Step 8: Verify evidence, Router, and orchestrator GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/test_route_evidence_fake.py tests/runtime/test_slice3b1_context_projection.py tests/runtime/test_slice3b1_orchestrator.py tests/router/test_adr018_route_evidence_router.py tests/router/test_router_task_focus_mvp1.py tests/runtime/test_mvp63_live_fast_interaction_evidence.py -q
```

Expected: new parallel evidence path passes and every legacy Router path
remains green.

- [ ] **Step 9: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/adapters/route_evidence_contract.py src/voice_agent/adapters/route_evidence_fake.py src/voice_agent/runtime/slice3b1/context_projection.py src/voice_agent/runtime/slice3b1/orchestrator.py src/voice_agent/router/router.py tests/adapters/test_route_evidence_fake.py tests/runtime/test_slice3b1_context_projection.py tests/runtime/test_slice3b1_orchestrator.py tests/router/test_adr018_route_evidence_router.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 8: Add default fail-closed parallel Gate and isolated release-token/outbox contract

**Files:**

- Create: `src/voice_agent/runtime/slice3b1_release.py`
- Modify: `src/voice_agent/runtime/fast_foreground_gate.py`
- Modify: `src/voice_agent/events/journal.py`
- Modify: `tests/qwen_slice3b1_support.py`
- Create: `tests/events/test_event_journal_atomic_batch.py`
- Create: `tests/runtime/test_slice3b1_default_gate.py`
- Create: `tests/runtime/test_slice3b1_release_contract.py`
- Regression test: `tests/events/test_event_journal.py`
- Regression test: `tests/runtime/test_mvp63_fast_foreground_gate.py`
- Regression test: `tests/runtime/test_mvp63_fast_interaction_provenance.py`

**Interfaces:**

- Produces `ForegroundReleaseTokenV1`, `ParallelForegroundGateContextV1`,
  `PlaybackOutboxItemV1`, `InMemoryPlaybackOutbox`,
  `build_slice3b1_gate_context(...)`, and
  `run_parallel_fast_foreground_gate(...)`.
- Keeps `_compare_authorize_and_enqueue_contract_only(...)` private,
  absent from package `__all__`, and referenced only by its focused unit test.
- Adds `InMemoryEventJournal.append_atomic_batch(...)`; it fully sanitizes and
  validates all staged envelopes and intra-batch causal refs before mutating
  event storage or sequence state.
- Existing `run_fast_foreground_gate(...)` remains the legacy
  `atomic_single_call` branch.
- Default Slice 3B.1 context derives `native_pcm_enabled=False`,
  `output_mode=mock`, the capability-matrix digest, and snapshot event ID from
  the validated `slice3b1_mock` assembly. It accepts no enable boolean.
- The mock-contract-only test bypasses public Gate dispatch and exercises only
  the private atomic comparison primitive with synthetic bindings; no runner,
  CLI, or assembly path can select it.
- Extends test-only builders with
  `valid_fast_router_event()`, `valid_route_evidence_event()`,
  `valid_safe_candidate_evidence_event()`,
  `valid_default_parallel_context()`, and
  `gate_event_ids(case_id: str)`.

- [ ] **Step 1: Inspect the overlap-sensitive Gate diff**

Run:

```bash
git diff -- src/voice_agent/runtime/fast_foreground_gate.py tests/runtime/test_mvp63_fast_foreground_gate.py
```

Expected: identify and preserve all existing user/earlier-slice edits. Limit
the modification to a topology dispatcher/import; place new policy code in
`slice3b1_release.py`.

- [ ] **Step 2: Write RED default-runner Gate tests**

```python
def test_slice3b1_default_gate_fails_without_token_or_outbox() -> None:
    outbox = InMemoryPlaybackOutbox(max_items=4)
    result = run_parallel_fast_foreground_gate(
        journal=parallel_journal(),
        candidate_event=valid_parallel_candidate_event(),
        fast_interaction_output_event=valid_parallel_fast_event(),
        router_decision_event=valid_fast_router_event(),
        route_evidence_event=valid_route_evidence_event(),
        candidate_safety_event=valid_safe_candidate_evidence_event(),
        context=valid_default_parallel_context(),
        outbox=outbox,
        event_ids=gate_event_ids("default_disabled"),
        created_monotonic_ms=100,
        created_wall_clock_ms=1_700_000_000_100,
    )
    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == "native_pcm_disabled"
    assert result.release_token is None
    assert outbox.items() == ()
    assert result.committed_event is None
```

Also assert provider-generated candidates cannot pass through the legacy Gate.

- [ ] **Step 3: Define the complete immutable token and context**

`ForegroundReleaseTokenV1` must contain exactly:

```text
release_token_id
session_id
provider_session_generation
context_snapshot_id
source_event_seq
turn_id
utterance_id
qwen_response_id
qwen_output_item_id
qwen_output_index
qwen_content_index
candidate_id
candidate_transcript_digest
candidate_pcm_manifest_digest
candidate_audio_format_ref
candidate_audio_duration_ms
candidate_audio_shadow_verification_event_id optional
router_decision_event_id
route_evidence_event_id
candidate_safety_evidence_event_id
playback_epoch
gate_policy_version
```

`ParallelForegroundGateContextV1` carries the same live bindings plus:

```text
assembly_stage=slice3b1_mock
capability_snapshot_event_id
capability_matrix_digest
output_mode=mock
native_pcm_enabled=false (derived, not caller-settable)
provider_context_state
interaction_state
candidate_check_policy_version
candidate_unicode_scalar_count
candidate_length_check
candidate_duration_check
candidate_terminal_check
candidate_safety_decision
individual check results
```

Construct it only through `build_slice3b1_gate_context(...)`, which accepts the
validated assembly result and the recorded capability snapshot, recomputes the
matrix digest, consumes immutable `CandidateEligibilityFactsV1` for
length/duration/terminal results, requires exact adapter IDs/modes, and rejects
any claimed native release support. Its constructor is not part of the public
package surface. No raw candidate text or PCM crosses this boundary.

- [ ] **Step 4: Implement the normal fail-closed path**

`run_parallel_fast_foreground_gate(...)` first revalidates the assembly/snapshot
binding, topology, and exact evidence/candidate binding. In Slice 3B.1 the
authoritative capability check is always false. If it is false, candidate
length is over 80 Unicode scalar values, duration exceeds 2,000 ms, the
candidate terminal check is not `PASS`, context is non-`CLEAN`, route is not
`FAST_ONLY`, candidate safety is not `SAFE`, any digest/identity mismatches, an
interrupt/rebuild changed epoch/generation, or any check is missing, append one
`FOREGROUND_ACT_GATE_FAILED` and one terminal candidate discard disposition.
Create no token, no `FOREGROUND_OUTPUT_COMMITTED`, and no outbox item.

If a caller supplies an assembly stage other than `slice3b1_mock`, a snapshot
digest that does not match, `output_mode` other than mock, or any claimed
enabled capability, fail before constructing a Gate context. Slice 3B.2 must
add a separately reviewed public authority factory; it cannot activate this
slice by flipping a boolean.

Do not read `time.monotonic()` in the new deterministic path. Use the caller's
virtual offsets and exclude operational timing from authority/digest.

- [ ] **Step 5: Implement a private preflighted contract primitive**

`_compare_authorize_and_enqueue_contract_only(...)` is synchronous, excluded
from all production dispatch/import surfaces, and executes under one
release-authority lock:

1. re-read the supplied immutable current binding;
2. compare every token field exactly;
3. derive exactly one safe
   `release-token://synthetic/<release_token_id>` ref and reject any supplied
   ref that does not match it;
4. reserve/preflight outbox capacity and duplicate ID without mutation;
5. construct both complete `JournalAppendRequest` values, including the
   committed output's intra-batch cause/ref to the Gate pass;
6. call `journal.append_atomic_batch((gate_pass, output_commit))`;
7. commit the prevalidated, non-throwing memory-only
   `PlaybackOutboxItemV1` reservation.

Implement the general in-memory journal primitive:

```python
@dataclass(frozen=True, slots=True)
class JournalAppendRequest:
    event_name: str
    event_id: str
    source_module: str
    created_monotonic_ms: int
    created_wall_clock_ms: int
    trace_redaction_level: str
    caused_by_event_id: str | None = None
    supersedes_event_id: str | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)

def append_atomic_batch(
    self,
    requests: Sequence[JournalAppendRequest],
) -> tuple[dict[str, Any], ...]: ...
```

It stages assigned `event_seq`, sanitization/redaction metadata, complete
`validate_event_envelope(...)`, duplicate IDs, playback-span uniqueness, and
causal refs against a scratch view that recognizes earlier events in the same
batch. Only after every staged event and any redaction-audit companion is valid
does one synchronous commit update `_events`, `_event_ids`, and
`_next_event_seq`. Any validation/fault before commit leaves all three
unchanged. A blocked-secret audit may still be emitted as an explicit security
event, but no staged authority event may survive. The method has no `await` and
must run under the existing per-session serialized append/release boundary; it
does not claim cross-thread transaction support.

The outbox insertion after preflight is infallible and contains only the
opaque token ref, correlation, epoch, and an in-memory PCM handle. It has no
Talker method and never marks playback started. That handle is generated by the
test-only contract harness and is not obtained from CandidateQuarantine.
Both contract events carry
`authority_mode=mock_contract_only`, `output_mode=mock`, and
`qualification_status=not_qualification`; this mode is forbidden in committed
runner fixtures and success reporting.

Add an import-surface test that parses runtime/CLI modules and asserts none
references `_compare_authorize_and_enqueue_contract_only`; assert it is absent
from `voice_agent.runtime.slice3b1` exports. The focused contract test is the
only permitted reference outside its defining module.

- [ ] **Step 6: Write the exhaustive `mock_contract_only` mismatch suite**

Parameterize every field:

```python
TOKEN_BINDING_FIELDS = (
    "release_token_id",
    "session_id",
    "provider_session_generation",
    "context_snapshot_id",
    "source_event_seq",
    "turn_id",
    "utterance_id",
    "qwen_response_id",
    "qwen_output_item_id",
    "qwen_output_index",
    "qwen_content_index",
    "candidate_id",
    "candidate_transcript_digest",
    "candidate_pcm_manifest_digest",
    "candidate_audio_format_ref",
    "candidate_audio_duration_ms",
    "candidate_audio_shadow_verification_event_id",
    "router_decision_event_id",
    "route_evidence_event_id",
    "candidate_safety_evidence_event_id",
    "playback_epoch",
    "gate_policy_version",
)
```

For each independent mismatch assert no Gate pass, no committed output, no
outbox insertion, and released PCM on terminal discard. Also test barge-in or
rebuild between authorization input construction and outbox handoff. Add
`candidate_unicode_scalar_count=81`, failed length/duration/terminal checks,
forged capability snapshot digest, caller-claimed native enablement, and an
attempt to reach the private primitive from runner/CLI.

Add atomic-failure tests:

```text
second staged envelope malformed -> no Gate pass, no output commit, no outbox
fault injected while validating second staged envelope -> journal snapshot and
  next event_seq unchanged, outbox empty
duplicate/overflow outbox reservation -> batch is never called
valid batch -> Gate pass and output commit receive consecutive event_seq and
  the second caused_by_event_id resolves to the first
legacy append() behavior and secret-audit behavior unchanged
```

- [ ] **Step 7: Verify default and isolated Gate paths GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events/test_event_journal_atomic_batch.py tests/events/test_event_journal.py tests/runtime/test_slice3b1_default_gate.py tests/runtime/test_slice3b1_release_contract.py tests/runtime/test_mvp63_fast_foreground_gate.py tests/runtime/test_mvp63_fast_interaction_provenance.py -q
```

Expected: default path always fails closed with no token/outbox; isolated
contract path passes only exact bindings; all legacy Gate tests remain green.

- [ ] **Step 8: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/events/journal.py src/voice_agent/runtime/slice3b1_release.py src/voice_agent/runtime/fast_foreground_gate.py tests/events/test_event_journal_atomic_batch.py tests/events/test_event_journal.py tests/runtime/test_slice3b1_default_gate.py tests/runtime/test_slice3b1_release_contract.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 9: Make the full ADR-018 parallel chain deterministically replayable

**Files:**

- Create: `src/voice_agent/state/qwen_parallel_state.py`
- Modify: `src/voice_agent/state/adapter_health_state.py`
- Modify: `src/voice_agent/replay/runner.py`
- Modify: `src/voice_agent/replay/state_digest.py`
- Create: `tests/replay/test_adr018_parallel_replay.py`
- Create: `tests/state/test_qwen_parallel_state.py`
- Regression test: `tests/replay/test_mvp63_audio_native_fast_interaction_replay.py`
- Regression test: `tests/replay/test_mvp5_live_route_replay.py`
- Regression test: `tests/state/test_state_digest.py`

**Interfaces:**

- Produces `QwenParallelState.reduce_event(...)` and
  `QwenParallelState.to_digest_dict()`.
- Extends `ReplayResult` with `qwen_parallel_state`.
- Adds optional `qwen_parallel_state_hash` only when ADR-018 events are
  present; legacy replay digest shape remains unchanged.
- Replay consumes canonical events only and never reconstructs transcript,
  PCM, provider wire events, models, tools, or clocks.

- [ ] **Step 1: Inspect overlap-sensitive replay diffs**

Run:

```bash
git diff -- src/voice_agent/replay/runner.py src/voice_agent/replay/state_digest.py src/voice_agent/state/adapter_health_state.py
```

Expected: identify current user/earlier-slice logic and patch around it. Do not
rewrite existing validators or reformat these files.

- [ ] **Step 2: Write a RED minimal parallel replay test**

Construct an in-memory `GITHUB_ALLOWED` fixture containing:

```text
SESSION_STARTED
ADAPTER_CAPABILITY_SNAPSHOT_RECORDED (slice3b1_mock profiles)
PROVIDER_CONTEXT_STATE_CHANGED
  (CLOSED -> REBUILDING, generation 1, bound epoch/state version)
PROVIDER_CONTEXT_STATE_CHANGED
  (REBUILDING -> CLEAN, generation 1, same epoch/state version)
AUDIO_SPAN_STARTED
SPEECH_START_DETECTED
TURN_OPENED
AUDIO_SPAN_ENDED
SPEECH_END_DETECTED
TURN_INGRESS_ACCEPTED
TURN_INGRESS_COMMITTED
ASR_TRANSCRIPT_OUTPUT_EMITTED (Qwen correlation)
MODEL_CONTEXT_PROJECTION_EMITTED (route_evidence)
ROUTE_EVIDENCE_OUTPUT_EMITTED
ROUTER_DECISION_EMITTED
MODEL_CONTEXT_PROJECTION_EMITTED (candidate_safety)
CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED
FAST_INTERACTION_OUTPUT_EMITTED (parallel)
FOREGROUND_REPLY_CANDIDATE_EMITTED (parallel)
FOREGROUND_ACT_GATE_FAILED (native_pcm_disabled)
FOREGROUND_OUTPUT_DISCARDED
```

Use the exact causal IDs/audio-span ID from the Task 10 ingress projector so
existing audio replay validation sees
`SPEECH_START -> TURN_OPENED -> SPEECH_END -> ACCEPTED -> COMMITTED`; do not
fabricate a committed turn as the fixture's first ingress event.

Assert:

```python
first = run_replay_fixture(fixture)
second = run_replay_fixture(deepcopy(fixture))
assert first.state_digest == second.state_digest
assert first.qwen_parallel_state.provider_context_state == "CLEAN"
assert first.qwen_parallel_state.route_evidence_event_ids == (
    "evt_route_evidence",
)
assert first.qwen_parallel_state.candidate_dispositions["cand_1"] == "DISCARDED"
assert first.diagnostics["ignored_events"] == []
```

Add a second deterministic replay case for rejected smart-turn ingress:

```text
SESSION_STARTED
ADAPTER_CAPABILITY_SNAPSHOT_RECORDED
CLOSED -> REBUILDING -> CLEAN
AUDIO_SPAN_STARTED
SPEECH_START_DETECTED
TURN_OPENED
AUDIO_SPAN_ENDED
SPEECH_END_DETECTED (provider_stop_reason=turn_invalid)
TURN_INGRESS_REJECTED
```

Replay it twice and assert identical digests,
`interaction_state.turn_phase == "WAITING_USER"`,
`last_ingress_outcome == "REJECTED"`, and zero
`TURN_INGRESS_COMMITTED`, ASR, Route Evidence, Router, candidate, Gate, output,
release-token, or playback authority.

- [ ] **Step 3: Run replay tests and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/replay/test_adr018_parallel_replay.py tests/state/test_qwen_parallel_state.py -q
```

Expected: RED because ADR-018 events are ignored and no state owner exists.

- [ ] **Step 4: Implement `QwenParallelState`**

Track bounded, safe values only:

```python
@dataclass(frozen=True, slots=True)
class CandidateReplayIdentityV1:
    provider_session_generation: int
    context_snapshot_id: str
    qwen_response_id: str
    qwen_output_item_id: str
    qwen_output_index: int
    qwen_content_index: int
    candidate_transcript_digest: str
    candidate_pcm_manifest_digest: str


@dataclass
class QwenParallelState:
    provider_session_generation: int | None = None
    provider_context_state: str = "CLOSED"
    playback_epoch: int = 0
    interaction_state_version: int = 0
    dropped_audio_frame_count: int = 0
    context_projection_event_ids: tuple[str, ...] = ()
    route_evidence_event_ids: tuple[str, ...] = ()
    candidate_safety_event_ids: tuple[str, ...] = ()
    shadow_verification_event_ids: tuple[str, ...] = ()
    response_arbitration_event_ids: tuple[str, ...] = ()
    handoff_dispositions: dict[str, str] = field(default_factory=dict)
    candidate_identities: dict[str, CandidateReplayIdentityV1] = field(
        default_factory=dict
    )
    candidate_dispositions: dict[str, str] = field(default_factory=dict)
    assistant_delivery_dispositions: dict[str, str] = field(
        default_factory=dict
    )

    def reduce_event(self, event: Mapping[str, Any]) -> bool: ...
    def to_digest_dict(self) -> dict[str, Any]: ...
```

Validate provider-context transitions:

```text
CLOSED -> REBUILDING
REBUILDING -> CLEAN|TAINTED|CLOSED
CLEAN -> CLEANUP_PENDING|TAINTED|REBUILDING|CLOSED
CLEANUP_PENDING -> CLEAN|TAINTED|REBUILDING|CLOSED
TAINTED -> REBUILDING|CLOSED
```

Require non-decreasing generation and exactly one terminal candidate/delivery
disposition per identity. `CLOSED -> REBUILDING` on initial Connect binds the
current epoch/version. A later-generation transition to `REBUILDING` must carry
a strictly greater epoch and interaction-state version; a replayed unchanged
or decreasing rebuild fence is invalid. For an ADR-018 session, the reducer
also consumes `INTERRUPT_CANDIDATE`/`TTS_TRUNCATE_REQUESTED` when they carry
the Interaction Controller's epoch/version: the first must advance both, the
second must preserve the exact new pair. Legacy events without these optional
fields retain their old replay/digest shape.

- [ ] **Step 5: Add one isolated ADR-018 replay-chain validator**

Call `_validate_adr018_parallel_chain(...)` from
`_validate_and_order_events(...)` after base ASR validation and before reducers.
It validates:

- projection `source_event_seq` points to an existing prefix and snapshot refs
  remain immutable;
- committed turn → Qwen final ASR → Route Evidence → Router order;
- Route Evidence final-ASR/context refs exist and match turn/utterance;
- candidate transcript digest equals candidate-safety and candidate event;
- generation/context snapshot match across projection, composite, candidate,
  Gate, and any release ref chain;
- parallel Router may precede candidate/composite, unlike the legacy branch;
- one Router, one terminal Gate, one terminal candidate/output disposition per
  committed turn;
- provider-context transitions and generation fencing are legal;
- handoff/arbitration/disposition and assistant delivery terminals are unique;
- any native playback chain preserves the exact release-token ref and all
  provider correlation, even though the default 3B.1 fixture has no playback.

Keep legacy `_validate_post_commit_understanding_and_router_order(...)`
behavior for missing/atomic topology.

- [ ] **Step 6: Integrate state, adapter outcomes, refs, and conditional digest**

- instantiate/reduce `QwenParallelState` in `run_replay_fixture`;
- treat every `ADR018_EVENT_NAMES` event as reducer-owned, never ignored;
- add `projection_ref`, `facts_ref`, `must_say_fields_ref`,
  `forbidden_claims_ref`, and `independent_transcript_ref` to
  `DATA_PLANE_REF_FIELDS`;
- record Route Evidence, candidate safety, and shadow output modes in
  `AdapterHealthState`;
- allow mock ASR only for an explicitly provider-free Qwen parallel chain;
- add `qwen_parallel_state_hash` only when the state saw an ADR-018 event;
- narrow `SAFE_SENSITIVE_METADATA_KEYS` to preserve only
  `release_token_id`/`release_token_ref` as opaque authority metadata while
  continuing to drop all other token-like keys; preservation still calls
  `is_safe_release_token_id/ref`, so encoded or malformed values fail rather
  than bypassing the digest scrubber.

- [ ] **Step 7: Add replay mutation tests**

For each mutation, expect `ReplayValidationError`:

```text
route evidence before final ASR
route evidence points to another turn
Router points to candidate instead of route evidence
candidate/safety transcript digest mismatch
candidate/composite generation mismatch
candidate/Gate context snapshot mismatch
second Router for one committed turn
second terminal Gate
second candidate disposition
illegal provider-context transition
rebuild generation advances without a strictly newer playback epoch/version
parallel barge-in does not advance epoch before truncate
old-generation candidate after rebuild
release-token ref changes between Gate and output
delivery disposition duplicated
slow handoff SELECTED without matching arbitration
```

Also assert replay makes no adapter/Fake/network call by replacing those entry
points with functions that raise if invoked.

- [ ] **Step 8: Verify replay and legacy GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/replay/test_adr018_parallel_replay.py tests/state/test_qwen_parallel_state.py tests/replay/test_mvp63_audio_native_fast_interaction_replay.py tests/replay/test_mvp5_live_route_replay.py tests/state/test_state_digest.py -q
```

Expected: deterministic ADR-018 replay passes, all mutations fail closed, and
legacy replay digests retain their prior shape and behavior.

- [ ] **Step 9: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/state/qwen_parallel_state.py src/voice_agent/state/adapter_health_state.py src/voice_agent/replay/runner.py src/voice_agent/replay/state_digest.py tests/replay/test_adr018_parallel_replay.py tests/state/test_qwen_parallel_state.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 10: Assemble the full deterministic scenario runner and stable result schema

**Files:**

- Create: `src/voice_agent/runtime/slice3b1/__init__.py`
- Create: `src/voice_agent/runtime/slice3b1/contracts.py`
- Create: `src/voice_agent/runtime/slice3b1/scenarios.py`
- Create: `src/voice_agent/runtime/slice3b1/ingress.py`
- Create: `src/voice_agent/runtime/slice3b1/runner.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Create: `tests/runtime/test_slice3b1_result_schema.py`
- Create: `tests/runtime/test_slice3b1_ingress.py`
- Create: `tests/runtime/test_slice3b1_runner.py`
- Create: `tests/acceptance/test_slice3b1_acceptance_scenarios.py`
- Regression test: `tests/duplex/test_mock_audio_accept.py`

**Interfaces:**

- Produces:

```python
async def run_slice3b1_scenario_async(
    scenario_id: str,
) -> Slice3B1RunV1: ...

def run_slice3b1_scenario(
    scenario_id: str,
) -> Slice3B1RunV1: ...
```

- `Slice3B1RunV1.to_safe_dict()` is the sole public serialization boundary
  later consumed by CLI B and Page C.
- Produces `Slice3B1IngressProjector`, which is the only bridge from safe Qwen
  speech-boundary projections to canonical Duplex evidence and the existing
  Interaction Controller.
- Extends `InteractionController` with
  `resolve_audio_ingress(...) -> AudioIngressResolutionV1`; the controller,
  not the runner/projector, decides commit versus rejection from normalized
  smart-turn evidence and current provider readiness. Its private reject path
  validates the matching opened audio turn and appends canonical
  `TURN_INGRESS_REJECTED`.
- The runner implements `QwenProjectionSink`, consumes
  `CandidateTranscriptCompleteV1` and `CandidateCompletionV1` exactly once,
  and never reads Session Adapter or Quarantine private state.
- Invalid/fault scenarios return a safe terminal result; unexpected invariant
  or programmer errors raise `Slice3B1RunnerError` without raw payloads.

- [ ] **Step 1: Write the RED stable-schema snapshot test**

Define an immutable result with exactly these top-level fields:

```python
SLICE3B1_RESULT_FIELDS = (
    "schema_name",
    "scenario_id",
    "fixture_domain",
    "generated_from",
    "scenario_source",
    "output_mode",
    "wire_timeline_safe",
    "canonical_event_ids",
    "route_evidence_summary",
    "candidate_safety_summary",
    "router_decision",
    "gate_terminal",
    "candidate_disposition",
    "provider_context_terminal_state",
    "replay_status",
    "state_digest",
    "safety_flags",
)

def test_slice3b1_result_has_stable_safe_schema() -> None:
    result = run_slice3b1_scenario(
        "valid_turn_response_starts_before_asr_final"
    ).to_safe_dict()
    assert tuple(result) == SLICE3B1_RESULT_FIELDS
    assert result["schema_name"] == "voice_agent.slice3b1.run.v1"
    assert result["fixture_domain"] == "GITHUB_ALLOWED"
    assert result["generated_from"] == "synthetic"
    assert result["scenario_source"] == "SYNTHETIC"
    assert result["output_mode"] == "mock"
```

Assert no transport object, journal object, provider body, unsafe/unredacted
provider identifier, PCM handle/bytes, prompt, transcript text, credential, or
unrestricted exception is serializable. Validated opaque provider refs/indexes
may appear only in `wire_timeline_safe` or canonical correlation metadata, as
allowed by the accepted design.

- [ ] **Step 2: Run result tests and confirm RED**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/runtime/test_slice3b1_result_schema.py tests/runtime/test_slice3b1_ingress.py tests/runtime/test_slice3b1_runner.py -q
```

Expected: import failure because the result and runner do not exist.

- [ ] **Step 3: Implement the immutable result and safe nested projections**

Use:

```python
@dataclass(frozen=True, slots=True)
class SafeWireTimelineEntryV1:
    wire_seq: int
    virtual_ms: int
    direction: Literal["client", "server"]
    event_type: str
    safe_metadata: Mapping[str, object]
    output_mode: Literal["mock"] = "mock"


@dataclass(frozen=True, slots=True)
class SafeEvidenceSummaryV1:
    event_id: str
    schema_name: str
    decision: str
    confidence: float
    output_mode: Literal["mock"] = "mock"


@dataclass(frozen=True, slots=True)
class Slice3B1RunV1:
    schema_name: Literal["voice_agent.slice3b1.run.v1"]
    scenario_id: str
    fixture_domain: Literal["GITHUB_ALLOWED"]
    generated_from: Literal["synthetic"]
    scenario_source: Literal["SYNTHETIC"]
    output_mode: Literal["mock"]
    wire_timeline_safe: tuple[SafeWireTimelineEntryV1, ...]
    canonical_event_ids: tuple[str, ...]
    route_evidence_summary: SafeEvidenceSummaryV1 | None
    candidate_safety_summary: SafeEvidenceSummaryV1 | None
    router_decision: str | None
    gate_terminal: Literal["PASSED", "FAILED", "NOT_REACHED"]
    candidate_disposition: str
    provider_context_terminal_state: str
    replay_status: Literal["passed", "failed", "not_reached"]
    state_digest: Mapping[str, object]
    safety_flags: Mapping[str, bool]

    def to_safe_dict(self) -> dict[str, object]: ...
```

`SafeWireTimelineEntryV1` contains type, virtual offset, direction, safe opaque
refs, indexes, byte counts, terminal enums, and output mode only. Optional
human-readable synthetic text belongs to a separate
`SyntheticDisplayProjectionV1` and is not included in canonical events or the
default safe result.

- [ ] **Step 4: Freeze the end-to-end scenario catalog**

`SLICE3B1_SCENARIO_IDS` must contain:

```python
SLICE3B1_SCENARIO_IDS = (
    "bootstrap_requires_session_update",
    "session_created_defaults_not_authority",
    "session_updated_session_id_mismatch",
    "session_updated_configuration_mismatch",
    "missing_or_duplicate_server_event_id",
    "audio_append_before_clean_dropped",
    "multiple_audio_appends_without_ack",
    "valid_turn_asr_before_response",
    "valid_turn_response_starts_before_asr_final",
    "transcript_and_pcm_interleave",
    "assistant_item_created_before_output_item",
    "output_item_before_assistant_item_created",
    "route_before_candidate_complete",
    "candidate_before_route_complete",
    "second_active_response_rejected",
    "ambient_audio_no_committed_turn",
    "ambient_delta_completed_temporary_item",
    "turn_invalid_no_commit_no_route_no_release",
    "precommit_turn_rejected_cancel_delete",
    "wrong_response_id",
    "wrong_output_item_id",
    "wrong_output_index",
    "wrong_content_index",
    "duplicate_provider_audio_event_id",
    "audio_delta_after_audio_done",
    "cross_content_audio_delta",
    "extra_output_item",
    "extra_content_part",
    "function_call_output_ineligible",
    "response_done_output_item_mismatch",
    "missing_audio_done",
    "missing_response_terminal",
    "response_failed",
    "quarantine_overflow",
    "barge_in_provider_auto_cancel",
    "barge_in_explicit_cancel",
    "auto_and_explicit_cancel_race",
    "late_explicit_cancel_invalid_request_is_not_terminal",
    "late_old_pcm_after_cancel",
    "missing_cancel_terminal",
    "delete_ack_missing_rebuild",
    "old_generation_event_after_rebuild",
    "recovery_audio_dropped_never_replayed",
    "route_fast_only",
    "route_spawn_slow_task",
    "route_patch_active_slow_task",
    "route_ignore",
    "active_task_foreground_chat",
    "active_task_patch",
    "active_task_new_task",
    "active_task_cancel_or_confirmation",
    "active_task_ambiguity",
    "candidate_safety_safe",
    "candidate_safety_unsafe",
    "candidate_safety_uncertain",
    "candidate_safety_timeout",
    "candidate_safety_malformed",
    "candidate_81_unicode_scalars",
    "route_evidence_timeout",
    "route_evidence_malformed",
    "route_evidence_low_confidence",
    "route_evidence_prohibited_risk",
    "default_native_pcm_disabled",
)
```

Each catalog row combines a `QwenWireScript`, local commit/cancel/rebuild
actions keyed to release checkpoints, route/safety directives, expected
authority cardinality, and expected terminal summary. It stores no materialized
transcript or PCM.

- [ ] **Step 5: Implement the runner orchestration in canonical order**

First implement and test the ingress bridge:

```python
class Slice3B1IngressProjector:
    def on_speech_started(
        self, projection: SpeechBoundaryProjectionV1
    ) -> dict[str, Any]: ...

    def on_speech_stopped(
        self,
        projection: SpeechBoundaryProjectionV1,
        *,
        utterance_id: str,
    ) -> AudioIngressResolutionV1: ...
```

It appends safe canonical `SPEECH_START_DETECTED` and
`SPEECH_END_DETECTED` evidence, with the corresponding local
`AUDIO_SPAN_STARTED`/`AUDIO_SPAN_ENDED` lifecycle, using locally observed
sample offsets and a bounded
`detection_basis=provider_event_presence`; it never appends raw Qwen events or
claims that Qwen supplied a confidence score. The canonical numeric
`vad_confidence` represents certainty that the allowlisted provider boundary
event was observed, not a semantic speech score, and the basis makes that
meaning explicit. It calls `InteractionController.open_audio_turn(...)` at
start. On stop, it cannot select an outcome; it passes normalized evidence to
the controller:

```python
@dataclass(frozen=True, slots=True)
class SmartTurnIngressEvidenceV1:
    provider_session_generation: int
    provider_context_state: str
    provider_stop_reason: str
    qwen_input_item_ref: str
    observed_audio_sample_offset: int

def resolve_audio_ingress(
    self,
    speech_end_event: Mapping[str, Any],
    *,
    turn_id: str,
    utterance_id: str,
    evidence: SmartTurnIngressEvidenceV1,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> AudioIngressResolutionV1: ...
```

The projector is constructed with a read-only provider-context state reader
owned by Session Runtime; neither scenario nor runner supplies that state. The
controller validates the prior `TURN_OPENED` and applies the frozen local
policy: current `CLEAN` plus a valid smart-turn stop commits; `turn_invalid`,
non-`CLEAN`, held, unknown, or mismatched evidence rejects. Its private
rejection path appends:

```text
TURN_INGRESS_REJECTED
turn_id
audio_span_id
ingress_outcome=REJECTED
reject_reason=turn_invalid|ambient|held|provider_context_not_clean
```

`turn_invalid` produces end evidence plus rejection, never acceptance or
commit. Standalone ambient-transcription events do not open a local turn and
never call the controller. Tests prove the runner has no direct append site
for `TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_COMMITTED`, or
`TURN_INGRESS_REJECTED`; neither runner nor projector accepts a
caller-selectable `COMMIT`/`REJECT` flag or calls the commit/reject helpers.
Parameterize `CLEAN + valid -> COMMITTED`, `CLEAN + turn_invalid -> REJECTED`,
every non-`CLEAN` state -> `REJECTED`, mismatched generation/item -> rejected,
and unknown reason -> rejected. Assert the result enum is emitted by
`InteractionController.resolve_audio_ingress`, not present in scenario data.

For a valid committed turn:

1. assemble `slice3b1_mock` capabilities and append session/snapshot events;
2. connect runtime using the Interaction Controller's current playback epoch;
   append `CLOSED -> REBUILDING`, release created, send update, release matching
   updated, and append `REBUILDING -> CLEAN`;
3. append audio only while `CLEAN`;
4. drive provider speech/ASR/response events and local actions from scenario,
   invoking the ingress projector/Interaction Controller at the corresponding
   speech-boundary checkpoints;
5. never append turn-ingress authority directly from the runner;
6. consume one final-ASR join and append canonical Qwen ASR;
7. append route context projection and Route Evidence;
8. call Local Router once;
9. when the ordered sink receives `CandidateTranscriptCompleteV1`, append the
   safety projection and start Candidate Safety while PCM may continue;
10. when it receives `CandidateCompletionV1`, join its safe eligibility facts
    with recorded route/safety evidence; on discard/cancel observation, stop
    without inspecting Quarantine;
11. if full completion and safety evidence exist, emit composite/candidate;
12. build Gate context from the validated assembly/capability snapshot and call
    the default parallel Gate; the derived native capability is false;
13. append exactly one candidate/output disposition;
14. build a synthetic replay fixture from canonical journal events and call
    `run_replay_fixture`;
15. map only safe values into `Slice3B1RunV1`;
16. after the logical result/replay snapshot, call
    `runtime.dispose_resources()` in `finally` to wipe every PCM and
    ephemeral-text handle without emitting a logical close.

Steps 14–16 are universal, not committed-turn-only: every scenario that returns
a `Slice3B1RunV1` builds a fixture from whatever canonical events it validly
produced and runs `run_replay_fixture`. Invalid/ambient/rejected scenarios stop
before inapplicable ASR/route/candidate/Gate/output authorities, so those
individual result fields report `NOT_REACHED`; their `replay_status` must still
be `passed`. A canonical replay failure is an invariant error and cannot be
hidden as a normal invalid-turn result.

In particular, `turn_invalid_no_commit_no_route_no_release` and
`precommit_turn_rejected_cancel_delete` must include the complete
`AUDIO_SPAN_STARTED -> SPEECH_START -> TURN_OPENED -> AUDIO_SPAN_ENDED ->
SPEECH_END -> TURN_INGRESS_REJECTED` chain, replay it twice, and prove zero
commit/ASR/route/output authority. Standalone ambient scenarios replay their
session/provider-context/ambient-safe events without inventing a local turn.

`provider_context_terminal_state` means the logical scenario state at the
assertion/replay boundary, before harness-only resource teardown. `finally`
cleanup uses `dispose_resources()` and must not fabricate a canonical `CLOSED`
scenario event. A scenario that explicitly tests Connect close calls logical
`close()` before replay; ordinary resource disposal closes handles silently
after the result snapshot.

- [ ] **Step 6: Add cardinality, deterministic-rerun, and non-claim tests**

For every scenario:

```python
first = run_slice3b1_scenario(scenario_id)
second = run_slice3b1_scenario(scenario_id)
assert first.to_safe_dict() == second.to_safe_dict()
```

For committed valid scenarios assert at most/exactly as applicable:

```text
one ASR final
one Route Evidence
one RouterDecision
one terminal Gate
one candidate/output disposition
```

For ambient/invalid/rejected/stale/malformed cases assert zero consumable
route/candidate/output authority and `replay_status == "passed"`. For every
non-ambient ingress scenario assert replay sees exactly one committed or
rejected terminal, never neither/both. For every scenario assert:

```text
native_pcm_enabled=false
no release token
no playback outbox item
no PLAYBACK_SPAN_STARTED
no Talker call
no real/native-PCM-success claim
```

- [ ] **Step 7: Verify runner and acceptance matrix GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/runtime/test_slice3b1_result_schema.py tests/runtime/test_slice3b1_ingress.py tests/runtime/test_slice3b1_runner.py tests/acceptance/test_slice3b1_acceptance_scenarios.py tests/duplex/test_mock_audio_accept.py -q
```

Expected: every catalog scenario terminates deterministically with the expected
authority chain and safe result.

- [ ] **Step 8: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/runtime/slice3b1/__init__.py src/voice_agent/runtime/slice3b1/contracts.py src/voice_agent/runtime/slice3b1/scenarios.py src/voice_agent/runtime/slice3b1/ingress.py src/voice_agent/runtime/slice3b1/runner.py src/voice_agent/interaction/controller.py tests/runtime/test_slice3b1_result_schema.py tests/runtime/test_slice3b1_ingress.py tests/runtime/test_slice3b1_runner.py tests/acceptance/test_slice3b1_acceptance_scenarios.py tests/duplex/test_mock_audio_accept.py
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 11: Add CLI B, minimal replay fixtures, repository safety gates, and acceptance evidence

**Files:**

- Create: `src/voice_agent/runtime/slice3b1/cli.py`
- Create: `scripts/qwen-slice3b1`
- Create: `tests/runtime/test_slice3b1_cli.py`
- Create: `tests/replay/test_slice3b1_fixture_safety.py`
- Modify: `tests/replay/test_fixture_safety.py`
- Create: `tests/fixtures/replay/mvp6/slice3b1/README.md`
- Create: `tests/fixtures/replay/mvp6/slice3b1/manifest.index.json`
- Create: `tests/fixtures/replay/mvp6/slice3b1/000-provider-free-happy-path.fixture.json`
- Create: `tests/fixtures/replay/mvp6/slice3b1/008-replay-safety.fixture.json`
- Create: `docs/implementation/qwen-slice3b1-provider-free-acceptance.md`

**Interfaces:**

- CLI:

```text
scripts/qwen-slice3b1 --list-scenarios
scripts/qwen-slice3b1 --scenario <id>
scripts/qwen-slice3b1 --scenario <id> --json
```

- CLI serializes/renders the same `Slice3B1RunV1`; it contains no protocol,
  Router, Gate, or replay logic.
- Fixtures contain canonical events only, never raw provider wire events or
  PCM, and never rerun the Fake.

- [ ] **Step 1: Write RED CLI tests**

Test `main(argv)` and the wrapper:

```python
def test_json_cli_emits_the_stable_result(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([
        "--scenario",
        "valid_turn_response_starts_before_asr_final",
        "--json",
    ])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_name"] == "voice_agent.slice3b1.run.v1"
    assert payload["output_mode"] == "mock"
    assert payload["gate_terminal"] == "FAILED"
```

Assert unknown scenario exits 2 without a traceback/raw payload and
`--list-scenarios` exactly matches the catalog.

- [ ] **Step 2: Implement presentation-only CLI and wrapper**

Use `argparse`, `json.dumps(..., ensure_ascii=False, sort_keys=True)`, and a
concise default renderer. The wrapper follows repository style:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${VOICE_AGENT_PYTHON:-python3}"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m voice_agent.runtime.slice3b1.cli "$@"
```

Make only this new wrapper executable:

```bash
chmod +x scripts/qwen-slice3b1
```

Do not add `--native-pcm`, provider URL, API key, live, Talker, or Page C
options.

- [ ] **Step 3: Write the two minimal canonical fixtures**

`000-provider-free-happy-path.fixture.json` contains the canonical failed-Gate
chain from Task 9. `008-replay-safety.fixture.json` is the smallest canonical
chain that proves replay uses recorded refs/digests and no adapter/Fake.

Each manifest is:

```json
{
  "manifest_schema_version": "1.0",
  "replay_id": "replay_slice3b1_provider_free_happy_path",
  "source_trace_ref": "fixture://mvp6/slice3b1/provider-free-happy-path",
  "replay_mode": "deterministic",
  "event_schema_version_range": ["1.0"],
  "fixture_domain": "GITHUB_ALLOWED",
  "generated_from": "synthetic",
  "contains_raw_audio": false,
  "contains_raw_trace": false,
  "contains_real_user_input": false,
  "contains_secrets": false,
  "contains_unredacted_tool_result": false,
  "contains_large_raw_web_content": false,
  "allowed_re_eval_components": []
}
```

Do not store `wire_timeline_safe` in replay fixtures; replay fixtures are
canonical events, not provider-wire recordings.

- [ ] **Step 4: Add narrow fixture safety for release authority**

In the shared fixture safety helper, add exact safe keys only:

```python
ALLOWED_SAFE_REF_KEYS = {
    "authorization_ref",
    "release_token_ref",
}
ALLOWED_SAFE_AUTHORITY_ID_KEYS = {
    "release_token_id",
}
```

Route them through `is_safe_release_token_ref(..., allow_local=False)` and
`is_safe_release_token_id(...)`. Do not relax the general forbidden `token`
pattern. The committed default fixtures should not contain a token because
native PCM is disabled; the allowlist supports future canonical replay and is
covered by focused negative tests.

Existing safe data-plane-ref validation applies to ASR `text_ref` and candidate
`candidate_ref`; Slice 3B.1 fixtures allow only their synthetic/redacted
schemes. Tests reject local refs and prove replay never resolves either ref
after the ephemeral store has closed.

- [ ] **Step 5: Add fixture/index and zero-provider tests**

`manifest.index.json` must list:

- the full scenario IDs from Task 10 as parameterized runtime coverage;
- the two committed fixture checks;
- `output_mode=mock`;
- `provider_free_test_support=true`;
- `real_live_support=false`;
- `native_pcm_enabled=false`;
- `replay_reruns_provider=false`;
- no raw audio/provider body/prompt/secret/real-user input;
- no native playback success evidence.

In `test_slice3b1_fixture_safety.py`:

- run `assert_fixture_is_github_safe` on both fixtures;
- replay both twice and compare digests;
- monkeypatch adapter/Fake/network/environment entry points to raise and prove
  replay does not use them;
- recursively reject bytes/bytearray/base64-like audio, provider bodies,
  prompt fields, credential fields, unrestricted transcript fields, and local
  paths.

- [ ] **Step 6: Write the acceptance evidence document**

Use this exact outline:

```markdown
# Qwen Slice 3B.1 Provider-Free Acceptance

## Scope proved
## Architecture and authority chain
## Protocol and partial-order coverage
## Router, Gate, and replay evidence
## Security and artifact safety
## Explicit non-claims
## Commands and results
## Slice 3B.2 handoff
```

`Explicit non-claims` must state:

```text
no Real Qwen WebSocket was opened
no provider credential was read
no native PCM was authorized or played
mock_contract_only is not qualification
Page C is not implemented
Slow-to-Fast/Composer runtime is not implemented
Real transport remains Slice 3B.2
```

Fill command results only from commands actually run during implementation;
do not pre-mark them passed.

- [ ] **Step 7: Verify CLI, fixtures, and safety GREEN**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/runtime/test_slice3b1_cli.py tests/replay/test_slice3b1_fixture_safety.py tests/replay/test_fixture_safety.py -q
```

Then run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/qwen-slice3b1 --scenario valid_turn_response_starts_before_asr_final --json
```

Expected: tests pass; CLI emits one stable JSON result with
`output_mode=mock`, failed/default native Gate, deterministic replay, and all
safety flags false.

- [ ] **Step 8: Review the task without Git mutation**

Run:

```bash
git diff --check -- src/voice_agent/runtime/slice3b1/cli.py scripts/qwen-slice3b1 tests/runtime/test_slice3b1_cli.py tests/replay/test_slice3b1_fixture_safety.py tests/replay/test_fixture_safety.py tests/fixtures/replay/mvp6/slice3b1/README.md tests/fixtures/replay/mvp6/slice3b1/manifest.index.json tests/fixtures/replay/mvp6/slice3b1/000-provider-free-happy-path.fixture.json tests/fixtures/replay/mvp6/slice3b1/008-replay-safety.fixture.json docs/implementation/qwen-slice3b1-provider-free-acceptance.md
```

Expected: no whitespace errors. Checkpoint: do not stage or commit.

---

### Task 12: Run full verification, security scans, and independent review

**Files:**

- Verify all files created or modified by Tasks 1-11.
- Update only actual command results in:
  `docs/implementation/qwen-slice3b1-provider-free-acceptance.md`

**Interfaces:**

- Produces a fully tested, independently reviewed Slice 3B.1 implementation.
- Does not stage, commit, push, create a PR, enable native PCM, or start Slice
  3B.2/Page C.

- [ ] **Step 1: Run focused Slice 3B.1 verification**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events/test_adr018_event_registry.py tests/events/test_adr018_conditional_event_envelopes.py tests/events/test_adr018_release_token_redaction.py tests/events/test_event_journal_atomic_batch.py tests/adapters/qwen_realtime tests/adapters/test_parallel_fast_interaction_profile.py tests/adapters/test_route_evidence_fake.py tests/adapters/test_route_evidence_profile.py tests/duplex/test_mock_audio_accept.py tests/interaction/test_playback_epoch_authority.py tests/router/test_adr018_route_evidence_router.py tests/runtime/test_qwen_realtime_session.py tests/runtime/test_slice3b1_adapter_assembly.py tests/runtime/test_slice3b1_context_projection.py tests/runtime/test_slice3b1_orchestrator.py tests/runtime/test_slice3b1_default_gate.py tests/runtime/test_slice3b1_release_contract.py tests/runtime/test_slice3b1_result_schema.py tests/runtime/test_slice3b1_ingress.py tests/runtime/test_slice3b1_runner.py tests/runtime/test_slice3b1_cli.py tests/state/test_qwen_parallel_state.py tests/replay/test_adr018_parallel_replay.py tests/replay/test_slice3b1_fixture_safety.py tests/acceptance/test_slice3b1_acceptance_scenarios.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run overlap-area regressions**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events tests/adapters tests/router tests/interaction/test_barge_in_truncate.py tests/duplex/test_mock_audio_accept.py tests/runtime/test_runtime_adapter_assembly.py tests/runtime/test_mvp63_fast_foreground_gate.py tests/runtime/test_mvp63_fast_interaction_provenance.py tests/replay/test_mvp63_audio_native_fast_interaction_replay.py tests/replay/test_mvp5_live_route_replay.py tests/replay/test_fixture_safety.py tests/state/test_state_digest.py -q
```

Expected: all old event, capability, Router, Gate, replay, privacy, and digest
contracts remain green.

- [ ] **Step 3: Run the complete repository test suite**

Run:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test -q
```

Expected: full suite passes. If a failure is unrelated and pre-existing, record
the exact test and evidence in the acceptance document; do not weaken or skip
it silently.

- [ ] **Step 4: Scan for prohibited provider/network/credential use**

Run:

```bash
rg -n "DASHSCOPE_API_KEY|Authorization|Bearer|websockets|aiohttp|httpx|requests\\.|socket\\.|os\\.environ|getenv\\(" src/voice_agent/adapters/qwen_realtime src/voice_agent/runtime/slice3b1 src/voice_agent/runtime/qwen_realtime_session.py src/voice_agent/adapters/route_evidence_fake.py
```

Expected: no matches. Type names or negative-test strings belong in tests, not
runtime.

- [ ] **Step 5: Scan shareable artifacts for raw/sensitive material**

Run:

```bash
find tests/fixtures/replay/mvp6/slice3b1 -type f
```

Expected: only README, manifest index, and two JSON fixtures.

Run:

```bash
rg -n -i "raw_audio|raw_trace|provider_body|prompt_dump|authorization_header|api[_-]?key|bearer |credential|real_user|user_utterance|pcm_bytes|audio_base64|data:audio|\\.wav|\\.mp3|audio/raw|diagnostics/|traces/|replays/local/" tests/fixtures/replay/mvp6/slice3b1
```

Expected: only explicit false safety declarations or explanatory prohibition
text; no payload value, path, secret, or raw artifact.

- [ ] **Step 6: Scan implementation for placeholders and unsupported claims**

Run:

```bash
rg -n -i "TODO|TBD|FIXME|XXX|implement later|placeholder|native pcm (passed|qualified|enabled)|real qwen (passed|verified)" src/voice_agent/adapters/qwen_realtime src/voice_agent/adapters/route_evidence_contract.py src/voice_agent/adapters/route_evidence_fake.py src/voice_agent/runtime/qwen_realtime_session.py src/voice_agent/runtime/slice3b1 src/voice_agent/runtime/slice3b1_release.py tests/adapters/qwen_realtime tests/runtime/test_qwen_realtime_session.py tests/runtime/test_slice3b1*.py tests/replay/test_adr018_parallel_replay.py tests/acceptance/test_slice3b1_acceptance_scenarios.py docs/implementation/qwen-slice3b1-provider-free-acceptance.md
```

Expected: no placeholder or false promotion claim. Legitimate explicit
non-claims in the acceptance document may match only when they clearly say
`not`/`no`.

- [ ] **Step 7: Check formatting and current worktree scope**

First check only the planned tracked integration files; this does not attribute
unrelated baseline changes to Slice 3B.1:

```bash
git diff --check -- src/voice_agent/events/registry.py src/voice_agent/events/envelope.py src/voice_agent/events/journal.py src/voice_agent/privacy/redaction.py src/voice_agent/adapters/capabilities.py src/voice_agent/adapters/profiles.py src/voice_agent/adapters/asr_profile.py src/voice_agent/runtime/assembly.py src/voice_agent/runtime/adapter_callback_boundary.py src/voice_agent/router/router.py src/voice_agent/interaction/controller.py src/voice_agent/runtime/fast_foreground_gate.py src/voice_agent/state/adapter_health_state.py src/voice_agent/replay/runner.py src/voice_agent/replay/state_digest.py tests/replay/test_fixture_safety.py
```

Expected: no whitespace errors in the Slice 3B.1 hunks of planned tracked
files.

Then check every new/untracked implementation path directly:

```bash
rg -n "[[:blank:]]+$" src/voice_agent/adapters/qwen_realtime src/voice_agent/adapters/parallel_fast_interaction_profile.py src/voice_agent/adapters/route_evidence_contract.py src/voice_agent/adapters/route_evidence_fake.py src/voice_agent/adapters/route_evidence_profile.py src/voice_agent/runtime/qwen_realtime_session.py src/voice_agent/runtime/slice3b1 src/voice_agent/runtime/slice3b1_release.py src/voice_agent/state/qwen_parallel_state.py tests/qwen_slice3b1_support.py tests/adapters/qwen_realtime tests/adapters/test_parallel_fast_interaction_profile.py tests/adapters/test_route_evidence_fake.py tests/adapters/test_route_evidence_profile.py tests/events/test_adr018_event_registry.py tests/events/test_adr018_conditional_event_envelopes.py tests/events/test_adr018_release_token_redaction.py tests/events/test_event_journal_atomic_batch.py tests/interaction/test_playback_epoch_authority.py tests/router/test_adr018_route_evidence_router.py tests/runtime/test_qwen_realtime_session.py tests/runtime/test_slice3b1_adapter_assembly.py tests/runtime/test_slice3b1_context_projection.py tests/runtime/test_slice3b1_orchestrator.py tests/runtime/test_slice3b1_default_gate.py tests/runtime/test_slice3b1_release_contract.py tests/runtime/test_slice3b1_result_schema.py tests/runtime/test_slice3b1_ingress.py tests/runtime/test_slice3b1_runner.py tests/runtime/test_slice3b1_cli.py tests/state/test_qwen_parallel_state.py tests/replay/test_adr018_parallel_replay.py tests/replay/test_slice3b1_fixture_safety.py tests/acceptance/test_slice3b1_acceptance_scenarios.py tests/fixtures/replay/mvp6/slice3b1 docs/implementation/qwen-slice3b1-provider-free-acceptance.md
```

Expected: no trailing whitespace in new/untracked files.

Run the global check only as a diagnostic and compare any finding with the
Step 0 baseline:

```bash
git diff --check
```

Expected: no new Slice 3B.1 whitespace error. A pre-existing unrelated finding
must be recorded with its baseline evidence and left untouched; it is not a
reason to reset or rewrite user work.

Run:

```bash
git status --short
```

Expected: pre-existing dirty files from the Step 0 manifest remain present and
unreset; the Slice 3B.1 file set is visible; no raw
audio/trace/cache/secret artifact appears. Record the safe before/after
filename-status comparison in the acceptance document.

- [ ] **Step 8: Request an independent implementation review**

Give the reviewer:

```text
accepted design:
docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md

implementation plan:
docs/superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md

review priorities:
generation ownership; one sender/Pump; exact handshake; ASR join;
candidate two-stage binding; route authority; default Gate fail-close;
mock_contract_only isolation; canonical replay; privacy; deterministic output;
legacy compatibility; no unsupported PCM claims
```

Require separate spec-compliance and code-quality verdicts. Fix every P0/P1
and any load-bearing P2, rerun affected tests, and record the final verdict in
the acceptance document. Do not stage or commit.

- [ ] **Step 9: Final acceptance audit**

Confirm all 23 accepted design acceptance criteria map to passing tests or
recorded command evidence, especially:

```text
zero network and credentials
generation before open
one active transport and one Pump
matching session.updated before CLEAN
non-CLEAN audio dropped
ASR final/local commit exactly-once join
Interaction Controller adjudicates ingress from evidence
ambient/invalid zero authority with rejected-path replay
independent Route Evidence
candidate exact lifecycle/correlation
default native PCM disabled
no token/outbox/Talker in normal runner
isolated full-token contract with atomic journal batch only
canonical deterministic replay without PCM reconstruction
stable Slice3B1RunV1
safe synthetic fixtures/results
```

Update only the actual command/result table in the acceptance document.
Checkpoint: implementation is complete only when required tests and review are
green; do not stage, commit, push, or start Slice 3B.2/Page C.

---
