# Qwen Realtime Fast/Slow Slice 3A.1.3 Acceptance

> Historical caveat (2026-07-24): a later independent review found a
> stale-cleanup generation P1 after this provider-free record was written.
> The provider-free results below are preserved as historical evidence, but
> Slice 3A.2 real qualification could begin only after that P1 was closed.
> See `qwen-realtime-fast-slow-slice3a2-acceptance.md`; the original counts and
> conclusions below have not been removed or rewritten.

Date: 2026-07-24 (+0800)

Status: `executed_pass`. Provider-free implementation, adversarial tests,
replay validation, full regression, security checks, and independent review
completed on 2026-07-24. No open P0/P1 remains.

## Scope and authority

Slice 3A.1.3 closes the generation TOCTOU, bounded Voice-horizon, foreground
commit truth-table, current-state Gate, exact template-catalog, missing
candidate, replay cardinality, and digest gaps found by independent dynamic
review of Slice 3A.1.2.

The Local Router remains authoritative. Qwen Voice and Function Call output are
untrusted evidence only. Qwen candidate text stays quarantined and never enters
the Event Journal, metadata timeline, QA, playback, or a `reply_candidate`
commit. SlowTask and UserPatch remain mock/local canonical owners. Forced
Function Call is `unsupported_or_unverified`. The experiment remains dual
session with `audio_output=none`; provider-native audio is prohibited.

## Generation-fenced Voice result

Enforced Voice events capture an immutable provider/coordinator/session
authority token. A blocked browser transcript send observes generation
retirement and is cancelled; authority is checked again after awaited
boundaries before journal, Router, Gate, task, QA, playback, or control
mutation. Stale events increment only a content-free safe counter.
Missing or empty event `session_ref` fails closed. The real adapter freezes the
non-empty generation/session ref before awaiting provider receive, so rebuild
or concurrent close cannot erase the identity of a content-free stale event.

The input/provider-ID and response horizons permit the 64th item and fail
closed on the 65th. Taint schedules one coalesced Voice-only rebuild before
browser metadata, drains retired PCM, prevents rebuild storms, and leaves the
replacement generation usable for new input.

## Foreground delivery result

The versioned foreground template catalog is the only source of deterministic
template text, route, output basis/ref, fallback policy ref, and foreground
act. Exact validation rejects forged, stale-version, or cross-route refs.
Journal and browser metadata contain refs only; template text appears solely in
the intended user-visible browser delivery.

Missing, quarantined, risky, ambiguous, or otherwise unauthorized FAST output
commits and delivers `template_clarify`. `template_ack` is appended only after
a complete canonical SPAWN or PATCH mutation and its Event Journal sequence is
later than the mutation tail. Failed or partially reconciled mutation commits
and delivers clarification, never `ACK_SLOW` or `ACK_PATCH`. Candidate, Gate,
commit, output basis/ref, act, and visible delivery agree. Ambiguous browser
delivery retains at most one semantic response identity.

## Gate and replay result

Gate mappings must exactly equal their canonical journal events. Live authority
is derived from the current reducer/interaction state for the target
turn/Router/task/confirmation/plan/sequence refs. Interrupting, waiting,
terminal, unknown, stale, or mismatched authority fails closed.
An `active_task_context` without canonical SlowTask journal history cannot
route or mutate PATCH. Legal provider-free PATCH fixtures append canonical
SlowTask history and use the reducer-derived current plan/version/sequence;
the caller snapshot is only a consistency assertion.

Every `FAST_ONLY` route records one terminal Gate and one foreground commit,
including missing-candidate cases; no synthetic direct answer bypass remains.
Replay rejects duplicate Router, terminal Gate, foreground commit, SPAWN
initiation, and PATCH/UserPatch initiation per `(turn_id, utterance_id)`.
Replay digest includes stable Router/Gate/commit identities, output basis, and
output ref without raw text, network access, or provider reruns.

## Capability matrix

| Capability | Slice 3A.1.3 status |
| --- | --- |
| Fake/local Voice generation and horizon probes | provider-free only |
| Local Router/Gate/SlowTask/UserPatch | authoritative, mock/local |
| Qwen candidate output | quarantined only |
| Forced Function Call | `unsupported_or_unverified` |
| Real Voice cancel/delete/rebuild/correlation | `not_executed` |
| `real_live_verified` | `false` |
| Provider-native audio | prohibited |
| Real tools or external side effects | prohibited |

## Hard-gate verification

All Python tests must use the repository entrypoint:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test ...
```

Executed evidence:

- Slice 3A.1.3 generation/delivery/cardinality: `21 passed`;
- Gate/live runner/replay: `62 passed`;
- Qwen experiment suite: `380 passed, 13 skipped` (the skips are the
  standalone restricted-loopback cases);
- interaction/router/Gate/UserPatch/SlowTask: `104 passed`;
- acceptance/replay: `445 passed`;
- all experiments: `481 passed`;
- security suite: `8 passed`;
- final full repository: `2179 passed`;
- approved focused loopback server verification: `6 passed`; an earlier
  restricted run's five socket-bind `PermissionError`s were environmental and
  are not reported as product passes;
- `git diff --check`: passed;
- no tracked `diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`,
  `.env`, or `.env.*`; no new canonical event or accepted ADR/register change;
- credential files and real provider/microphone/audio were not accessed;
- final independent read-only review: PASS, no open P0/P1.

## Qualification verdict

`PASS — enter narrowly frozen Slice 3A.2`.

This verdict authorizes only the dual-session, provider-free closure's next
qualification step. It does not authorize provider-native audio, production
use, real tools, real external side effects, a single-stream architecture, or
acceptance of the proposed ADR. Slice 3B remains blocked on an accepted ADR and
separate single-stream/token/PCM/realtime qualification.
