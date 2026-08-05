# TC-S3B1-05 Candidate Quarantine

## Task ID and title

`TC-S3B1-05` — Candidate quarantine and ephemeral text/PCM ownership. Status:
`not-started`. Historical source: Slice 3B.1 master-plan Task 5.

## Goal

Implement two-stage candidate binding, exact response/item/content correlation,
bounded transcript and PCM assembly, immutable eligibility facts, and explicit
wipe/discard behavior without allowing payload material to cross the quarantine
boundary.

## Allowed write files

- Create: `src/voice_agent/adapters/qwen_realtime/quarantine.py`
- Create: `src/voice_agent/adapters/qwen_realtime/ephemeral_text_store.py`
- Create: `tests/adapters/qwen_realtime/test_candidate_quarantine.py`
- Create: `tests/adapters/qwen_realtime/test_candidate_quarantine_security.py`
- Create: `tests/adapters/qwen_realtime/test_ephemeral_text_store.py`

## Required read-only dependencies

- [TC-S3B1-03](TC-S3B1-03-protocol-and-transport.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`

## Exact ADR sections

- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Decision`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Commit Boundary Definition`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `ADR-018 Accepted Addendum`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md` — `Decision`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `Decision`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `ADR-018 Topology Compatibility Addendum`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Input is Card 03's typed response lifecycle and completion projection contract.
Output is `CandidateQuarantine`, `CommittedCandidateBinding`,
`CandidateDispositionV1`, `CandidatePCMManifestV1`, `WipeablePCMBuffer`,
`EphemeralTextStore`, `EphemeralTextRefV1`, and scoped
`SensitiveTextLease` resolution.

`CandidateQuarantine` exposes `open_response(...)`,
`accept_assistant_item(...)`, `accept_output_item(...)`,
`accept_content_part(...)`, `bind_committed_turn(...)`,
`append_transcript_delta(...)`, `append_pcm_delta(...)`,
`mark_transcript_done(...)`, `mark_audio_done(...)`,
`mark_content_done(...)`, `mark_output_item_done(...)`,
`mark_response_done(...)`, `transcript_completion()`, `completion()`, and
`discard(...)`.

`response.created` opens a provisional response without local turn authority.
Turn, utterance, and context bind exactly once after canonical commit. Candidate
transcript completion may precede full PCM/lifecycle completion, but both expose
the same opaque candidate ref and immutable transcript digest. Eligibility
contains only identities, digests, counts, format, duration, and terminals; it
contains no text, PCM, resolver, or mutable handle.

No `Regression test:` entries exist in this card's historical Files block. In
cards that do contain them, those entries are read-only verification inputs and
do not authorize edits.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-JOURNAL-01`
- `INV-PRIVACY-01`
- `INV-PRIVACY-02`
- `INV-FOREGROUND-02`
- `INV-FOREGROUND-03`
- `INV-CONCURRENCY-02`

## Non-goals

- No public PCM redemption API or native release in Slice 3B.1.
- No persistence or serialization of transcript text or PCM.
- No Router, candidate-safety, Gate, Talker, or playback decision.
- No unsupported guarantee about arbitrary provider delta loss or reordering.

## Implementation outline

1. Verify Card 03 and freeze legal two-stage completion projection types.
2. Join assistant item and output item in either legal order, then bind output
   and content indexes monotonically.
3. Store UTF-8 and PCM in wipeable bytearrays; resolve text only inside scoped
   leases and release all terminal paths explicitly.
4. Enforce one message/audio part, 80 Unicode scalars, 2,000 ms audio, bounded
   chunks/bytes, exact event identity, and complete terminals.
5. Parameterize every observable mismatch, stale/missing ref, overflow, extra
   output, function call, and post-terminal delta as fail-closed.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_candidate_quarantine.py tests/adapters/qwen_realtime/test_candidate_quarantine_security.py tests/adapters/qwen_realtime/test_ephemeral_text_store.py -q
git diff --check -- src/voice_agent/adapters/qwen_realtime/quarantine.py src/voice_agent/adapters/qwen_realtime/ephemeral_text_store.py tests/adapters/qwen_realtime/test_candidate_quarantine.py tests/adapters/qwen_realtime/test_candidate_quarantine_security.py tests/adapters/qwen_realtime/test_ephemeral_text_store.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

All legal partial orders produce stable transcript/full completion metadata.
Every detectable identity, lifecycle, bound, or ref failure produces one
terminal ineligible/discard disposition; every associated text and PCM handle
is wiped; no payload appears in repr, exceptions, results, fixtures, or journal.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop if payload escapes wipeable memory,
a mutable handle crosses the boundary, local binding can be changed, terminal
cleanup is implicit, or unsupported correlation coverage is claimed.

## Evidence and handoff

Record legal-order coverage, invalid-path counts, digest stability, explicit
wipe assertions, safe test results, and relative changed paths. Hand only
completion metadata, eligibility facts, and opaque refs to `TC-S3B1-06`,
`TC-S3B1-07`, and `TC-S3B1-08`.
