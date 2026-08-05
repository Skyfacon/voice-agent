# AGENTS.md

## Authority and mode selection

Repository governance entry: follow `stage_b_adr_register.md` and `docs/adr/`.
Quick = local/reversible, one boundary, direct existing validation, no
ADR/architecture change. Any accepted-boundary touch uses a linked Task Card:
`docs/governance/codex-task-cards/slice3b1/index.md`. Work Package = dependencies
across multiple independent cards only. New architecture/scope: stop for
ADR/mode upgrade, not automatic Work Package. Cards link only; map:
`docs/governance/codex-context/invariant-map.md`.

## Stable invariants

### INV-ADR — ADR and scope governance

- INV-ADR-01: Accepted ADRs govern core boundaries; consult the register and never conflict.
- INV-ADR-02: ADR precedes capability/boundary/scope change. MVP0=live+interrupt/truncate/replay/module boundary; MVP1=SlowTask mock+UserPatch+plan_version+stale policy; MVP2=demo tools+progressive invocation+UI patch+Composer checks; MVP3=real ASR/Thinker/Slow-LLM/TTS adapter swaps only. Multi-active SlowTask, pause/resume, real side effects, and production privacy require later ADRs.
- INV-ADR-03: This repository governance entry applies the mode rules above.

### INV-ADAPTER — Adapters

- INV-ADAPTER-01: External ASR/Thinker/Fast Interaction/Composer/Slow-LLM/TTS/Duplex/Embedding-RAG I/O uses adapters; business code never calls providers.
- INV-ADAPTER-02: Each adapter has a truthful capability matrix for real/mock/fallback/degraded; trace/SLO labels match.

### INV-JOURNAL — Journal/replay

- INV-JOURNAL-01: Interaction Controller owns ingress; one append owner serializes `event_seq` in the per-session append-only journal. Unjournaled behavior fails verification; reducers/replay stay pure/deterministic without network/model/tool/clock/random/missing-ref/schedule dependency.
- INV-JOURNAL-02: Interrupt/truncate/UserPatch/tool/commitment/SpokenPlan/foreground/UI-patch are replayable ADR-002 events; new MVP events first update ADR/registry.

### INV-PLAN — Plan/lifecycle

- INV-PLAN-01: ToolCall, ToolResult, UserPatch, and SemanticCommitment bind `task_id`, `plan_version`, and `task_event_seq`.
- INV-PLAN-02: Old-plan ToolResult is `stale_evidence`; only explicit SlowTask adopt/rebase may reuse it.
- INV-PLAN-03: ADR-016 governs SlowTask lifecycle, confirmation, cancel/switch, tool authorization, and current-plan binding.

### INV-TOOL — Tools/evidence

- INV-TOOL-01: MVP tools use sandboxed Tool Executor; no real payment/booking/deletion/communication/external write.
- INV-TOOL-02: Frontend state changes only through Tool Executor and `TOOL_UI_STATE_PATCHED`, never model text.
- INV-TOOL-03: webSearch is `UNTRUSTED_WEB_EVIDENCE` only, never instruction or tool/confirmation/trace/repo/ADR-policy authority.
- INV-TOOL-04: ADR-016 gates confirmation/cancel/tool authorization; `DEMO_DESTRUCTIVE_ACTION` also requires current-plan approval.

### INV-COMMITMENT — Commitments

- INV-COMMITMENT-01: Composer realizes/styles speech only; never changes immutable facts, must-say fields, resolved args, tool status, risks, or confirmation.
- INV-COMMITMENT-02: Before playback, every SpokenPlan passes both CommitmentCoverageCheck and ProgressTruthfulnessCheck and never claims unrecorded completion.

### INV-PRIVACY — Privacy/artifacts

- INV-PRIVACY-01: No API key/token/cookie/credential/authorization header/session secret, PII, raw audio/trace/cache, or unredacted user/tool data enters trace/repo; redact/block captured adapter/tool results before any write.
- INV-PRIVACY-02: Raw audio/trace, replay cache, unredacted input, and large raw web evidence stay local.
- INV-PRIVACY-03: Only synthetic/redacted/minimal metadata replay fixtures in approved test-fixture directories may be committed.
- INV-PRIVACY-04: Before artifact directories exist, exclusions cover `diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`, `.env`, and `.env.*`.

### INV-CONCURRENCY — Concurrency

- INV-CONCURRENCY-01: MVP-0/1/2 control plane uses standard CPython; correctness never assumes free-threaded/GIL-free.
- INV-CONCURRENCY-02: I/O uses async boundaries; loops/controllers/reducers/replay contain no unisolated blocking or long CPU work.
- INV-CONCURRENCY-03: DSP, VAD/AEC, embedding, batch eval, and heavy checks run in process/native/sidecar services.
- INV-CONCURRENCY-04: Threads only wrap blocking I/O, callbacks, or adapter glue; neither threads nor async scheduling order advances critical state.
- INV-CONCURRENCY-05: One session append owner serializes critical transitions; reducers/replay stay pure and deterministic.
- INV-CONCURRENCY-06: Python/native/sidecar uses adapters, Tool Executor, Duplex events, or data refs; never bypasses controller/journal/tool/events.

### INV-FOREGROUND — Foreground/projection

- INV-FOREGROUND-01: Local Router/Gate is authoritative; Route Evidence/provider context is evidence, not routing/memory authority.
- INV-FOREGROUND-02: Candidate is quarantined until Gate issues the exact release token for its atomic low-risk fast-only binding; no early display/playback.
- INV-FOREGROUND-03: Audible/native PCM needs a promoted profile and exact online correlation/digests; no per-turn PCM back-transcription.
- INV-FOREGROUND-04: Qwen gets only bounded canonical trusted projection; reject stale, raw, or untrusted SlowTask material.
- INV-FOREGROUND-05: Delivered history keeps only the delivered assistant prefix, never an undelivered suffix.
- INV-FOREGROUND-06: ADR-017/018 Slice 3B stays single-session; no cross-session durable memory.

### INV-VERIFY — Verification

- INV-VERIFY-01: Use `VOICE_AGENT_PYTHON=/path/to/python ./scripts/test ...`, not direct `pytest`, `python -m pytest`, or `uv --with pytest`. Wrapper never downloads. Fetch needs human approval; slice threads never try multiple network install paths.
- INV-VERIFY-02: Every slice has replay/eval; trace and SLO results label mock/real/fallback/degraded.

## Verification and detailed checks

Run `scripts/codex-context-audit`; use map checks/ADRs.

## Scope reminder

See INV-ADR-02.
