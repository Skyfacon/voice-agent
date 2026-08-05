# TC-S3B1-01 Events and Envelopes

## Task ID and title

`TC-S3B1-01` — Canonical events, conditional envelopes, and safe authority
references. Status: `not-started`. Historical source: Slice 3B.1 master-plan
Task 1.

## Goal

Register the nine ADR-018 canonical additions, preserve legacy envelope
compatibility, and validate opaque release-token identifiers and references
without exposing credential-like values.

## Allowed write files

- Modify: `src/voice_agent/events/registry.py`
- Modify: `src/voice_agent/events/envelope.py`
- Modify: `src/voice_agent/privacy/redaction.py`
- Create: `tests/events/test_adr018_event_registry.py`
- Create: `tests/events/test_adr018_conditional_event_envelopes.py`
- Create: `tests/events/test_adr018_release_token_redaction.py`
- Create: `tests/qwen_slice3b1_support.py`
- Regression test: `tests/events/test_fast_foreground_event_registry.py`
- Regression test: `tests/events/test_event_envelope.py`

## Required read-only dependencies

- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`
- `docs/specs/event-registry.md`

This card has no Task Card predecessor. Existing dirty files are inputs to
preserve, never a reason to reset or restore them.

## Exact ADR sections

- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `Decision`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `Canonical MVP-0 Event Registry`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `ADR-018 Canonical Event Addendum`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md` — `Decision`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Input is the accepted ADR-018 event table plus the existing canonical registry,
envelope validator, and redaction boundary. Output is
`ADR018_EVENT_DEFINITIONS`, `ADR018_EVENT_NAMES`,
`ConditionalRequiredFields`, `AllOrNoneFields`, safe
`is_safe_release_token_id(...)` and `is_safe_release_token_ref(...)` validators,
and test-only builders `base_canonical_event(...)`,
`valid_adr018_event(...)`, `valid_asr_event(...)`,
`valid_legacy_candidate_event(...)`, `valid_parallel_fast_event(...)`,
`valid_parallel_candidate_event(...)`, and `parallel_journal()`.

Legacy required-field tuples remain byte-for-byte compatible in behavior.
Absent `fast_interaction_topology` continues to mean
`atomic_single_call`; parallel fields are required only when the declared
topology selects them. Canonical payloads carry bounded refs and metadata, not
provider bodies, raw text, PCM, or credentials.

The historical `Regression test:` entries in Allowed write files are read-only
verification inputs; their verbatim presence is not authorization to edit them.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-JOURNAL-01`
- `INV-JOURNAL-02`
- `INV-PRIVACY-01`
- `INV-FOREGROUND-02`
- `INV-VERIFY-01`

## Non-goals

- No provider-specific canonical event names.
- No runtime orchestration, Router, Gate, playback, or capability enablement.
- No weakening of historical ADR-017 fixtures or legacy envelope validation.
- No raw token, credential, transcript, provider body, or audio persistence.
- Only paths labeled `Create:` or `Modify:` above are writable. Rows labeled
  `Regression test:` are read-only verification surfaces and do not grant
  mutation authority.

## Implementation outline

1. Run the focused tests first and classify the current implementation as
   verified, incomplete, or regressed; file existence alone is not completion.
2. Freeze literal event names, owners, required fields, causal references,
   replay meanings, and conditional all-or-none groups from accepted authority.
3. Add only backward-compatible conditional envelope validation.
4. Keep safe release authority opaque and reject malformed or
   credential-looking values without echoing them in errors.
5. Re-run legacy registry/envelope coverage before handing off to capability,
   replay, or Gate cards.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events/test_adr018_event_registry.py tests/events/test_adr018_conditional_event_envelopes.py tests/events/test_adr018_release_token_redaction.py tests/events/test_fast_foreground_event_registry.py tests/events/test_event_envelope.py -q
git diff --check -- src/voice_agent/events/registry.py src/voice_agent/events/envelope.py src/voice_agent/privacy/redaction.py tests/events/test_adr018_event_registry.py tests/events/test_adr018_conditional_event_envelopes.py tests/events/test_adr018_release_token_redaction.py
```

No dependency-overlap command applies because this card is a DAG root.

## Pass criteria

Exactly the accepted ADR-018 additions validate; every conditional topology
case fails closed when incomplete; safe opaque release authority survives
sanitization; unsafe values fail without disclosure; all legacy event and
envelope tests pass.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event beyond accepted ADR-018, runtime/provider/network scope expansion,
sensitive artifact discovery, or focused/overlap test failure. Also stop for an
unregistered event, legacy schema drift, unsafe ref/token behavior, or any
proposal to fix a failure by weakening redaction. Editing a
`Regression test:` path is write-set expansion and requires stopping.

## Evidence and handoff

Record the focused command, pass/fail count, safe relative changed-file list,
and the preserved dirty-worktree baseline. Hand off the stable event names,
conditional-field definitions, and test-builder interfaces to `TC-S3B1-02`,
`TC-S3B1-06`, `TC-S3B1-08`, and `TC-S3B1-09`; do not include raw diffs or
matched sensitive values.
