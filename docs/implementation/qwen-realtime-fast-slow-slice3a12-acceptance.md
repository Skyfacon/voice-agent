# Qwen Realtime Fast/Slow Slice 3A.1.2 Acceptance

Date: 2026-07-22 (+0800)

Status: `superseded_invalidated`. Independent dynamic review for Slice 3A.1.3
found generation TOCTOU, Voice-horizon rebuild, foreground commit truth-table,
current-state Gate binding, missing-candidate bypass, template-catalog, and
replay-cardinality gaps. This document is historical evidence only and no
longer authorizes entry into Slice 3A.2. A new authorization requires every
Slice 3A.1.3 hard gate to pass.

## Authority and safety result

The deterministic Local Router remains final routing authority. Qwen Function
Call output remains non-authoritative provider proposal/evidence. Arbitrary
Qwen candidate text remains quarantined and cannot enter QA, browser playback
or `reply_candidate` foreground commitment. Provider `risk_class=LOW`,
`risk_tags=["none"]`, confidence and valid schema cannot self-attest safety.

The immutable local `CandidatePolicyDecision` records policy version,
allow/quarantine decision, bounded reason code and provenance. Only explicit
trusted-synthetic fixtures or server-owned deterministic template refs may be
allowed. Provider provenance is structurally restricted to quarantine. No
candidate text is persisted in the policy or Gate metadata.

Live Gate callers bind `TURN_INGRESS_COMMITTED` and
`TASK_FOCUS_STATE_UPDATED` references from the journal, current SlowTask
identity/lifecycle and confirmation id/scope from local state, and output mode
from the capability snapshot. Missing, unknown or inconsistent authority fails
closed. Synthetic eval context is explicit and cannot authorize live provider
provenance.

## Closed P0/P1 findings

| Finding | Closure |
| --- | --- |
| Keyword-based candidate allow | Removed; arbitrary provider candidates are provenance-quarantined, with English/Chinese adversarial regression cases. |
| Optimistic live Gate defaults | Removed; live runner derives canonical state/focus and verifies active-task, confirmation and capability bindings. |
| Double semantic reply after ambiguous browser send | Delivery identity and semantic kind are recorded before send; attempted/started/terminal/ambiguous states prohibit a second fallback or response id. |
| Journal/runtime split after partial mutation | Spawn/Patch outcomes are explicit and runtime state is rebuilt through `SlowTaskState` after every partial append; partial or interpretation failure is never reported as success. |
| Candidate-less Gate replay failure | Slow no-candidate routes append a real local template candidate before the existing Gate chain; no fake ID, new event or replay-validator relaxation. |
| PCM crossing Voice rebuild | Queue frames bind coordinator/provider generations, rebuild fences before await and drains old frames, and dequeue checks again before provider send. |
| Terminal receiver hot loop | One receiver owns terminal, parks on the coalesced rebuild, and continues only with the replacement generation. |
| Browser metadata blocking recovery | Voice recovery is scheduled before best-effort metadata and background task exceptions are consumed. |
| Stale old-core events | Generation is carried and rechecked before processing; stale terminal, ASR and audio are discarded without current-state mutation. |
| Provider ID eviction/rebinding | IDs are retained for the physical generation; duplicate/reuse fails closed and the bounded horizon taints/rotates Voice rather than evicting. |

## Replay and delivery contract

Each enforced turn has at most one Router chain, one Gate terminal, one task
mutation and one semantic browser reply. A browser exception before/during/after
assistant delta, assistant done, dispatch metadata or timeline metadata cannot
change response identity or semantic kind. If delivery is ambiguous, recovery
is metadata-only.

SPAWN now records canonical creation and entry to `PLANNING`. Fault injection
after every SPAWN and PATCH append boundary verifies canonical counts,
`plan_version`, `task_event_seq`, confirmation state, runtime/replay equality,
non-success dispatch and no duplicate task/patch. Normal no-candidate SPAWN,
PATCH, IGNORE, degraded, quarantined FAST and local ACK journals replay twice
with identical ordering and digest.

## Voice lifecycle and bounded state

Rebuild/disconnect advances the local generation before transport awaits. Old
queued or in-flight PCM is counted and dropped without recording its bytes.
The receiver does not poll a dead core; after successful rebuild it consumes
only the new generation. Old terminal, transcript-final and audio events are
content-free discards. Reconnect never replays microphone PCM.

Provider input IDs, raw response IDs and output-item ownership are generation
scoped. Reuse or ambiguous ownership taints the Voice context. The adapter does
not evict IDs within a generation: the bounded horizon forces a Voice-only
rotation, trading an occasional reconnect for protection against stale ID
rebinding. Provider-free stress covers 320 turns and verifies bounded active
state/counters without retaining PCM, transcript, provider payload or secrets.

## Capability matrix and limitations

| Capability | Status |
| --- | --- |
| Fake + enforced Router/Gate/SlowTask/UserPatch | `provider_free_verified` |
| Arbitrary Qwen candidate delivery | quarantine only; not authorized |
| Qwen Voice/Control dual session | retained |
| Forced Function Call | `unsupported_or_unverified` |
| Real turn-level cancel/delete/rebuild/correlation | `not_executed` in this slice |
| `real_live_verified` | `false` |
| Provider-native foreground audio | prohibited / Slice 3B not started |
| Real SlowTask, real tools, external side effects | not enabled |
| Single-session Voice+Control | unverified and not recommended |

Connection success, `session.updated`, health readiness, schema validity or one
Function Call never promotes `real_live_verified`.

## Verification results

All commands used the repository entrypoint with
`VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python`.

- Qwen suite in sandbox: `361 passed, 13 skipped in 18.03s`; all skips were
  loopback-bind tests.
- The same Qwen suite with approved loopback binding: `374 passed in 18.23s`.
- Interaction/Router/Gate/UserPatch/SlowTask selection: `101 passed in 0.35s`.
- Related live-route/replay/acceptance/smoke selection: `45 passed in 0.38s`.
- All experiments: `462 passed in 20.97s`.
- Full repository in the restricted sandbox: `2106 passed, 23 skipped,
  5 failed in 27.61s`; the five failures were all pre-assertion
  `PermissionError` failures while the existing debug-console tests attempted
  to bind `127.0.0.1:0`.
- The same full repository suite with approved loopback binding:
  `2134 passed in 30.32s`.
- Dedicated Qwen security selection: `8 passed in 0.15s`.
- `git diff --check`: passed.

The Slice 3A.1.2 dedicated fault/replay module contains 67 passing cases within
the Qwen suite. No test was skipped or relaxed to match a historical count.

## Live-smoke boundary

Real provider connection smoke: `not_executed`. Real microphone/audio smoke:
`not_executed`. No credential file was opened or printed. This slice executed
no real Qwen candidate delivery, no Qwen playback, no real SlowTask, no real
tool and no external side effect.

Serializable journal, replay fixtures, timeline and browser metadata were
checked for API keys, Authorization headers, raw PCM, full provider payload,
complete Function Call arguments, unredacted transcript and full reply
candidate content. None is retained. Only safe counts and local opaque refs are
exported. The final repository check found no tracked files under
`diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`, `.env` or `.env.*`;
all remain covered by `.gitignore`. Static secret-pattern matches were limited
to deliberate dummy/redaction assertions and synthetic browser-harness test
credentials, never runtime output or committed live credentials.

## Slice 3A.2 admission and frozen handoff

Provider-free admission criteria are satisfied. Slice 3A.2 should remain:

- `provider=qwen`, `routing=enforced`, `audio_output=none`;
- dual Voice and Control sessions;
- Local Router authoritative, Qwen proposal non-authoritative;
- arbitrary Qwen candidate quarantine with local deterministic templates only;
- mock/local SlowTask and zero real external side effects;
- explicit human qualification records without automatic
  `real_live_verified` promotion.

Do not broaden Slice 3A.2 into provider-native audio, single-session control,
arbitrary model-text delivery, production privacy claims or real tools. Those
remain separate ADR/slice work.
