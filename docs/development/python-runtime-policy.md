# Python Runtime and Concurrency Policy

## Status

implementation guidance.

This document records the project-level Python runtime policy for the MVP implementation. It does not replace accepted ADRs or `AGENTS.md`. If this document conflicts with accepted ADRs, `AGENTS.md`, or `stage_b_adr_register.md`, the ADR/governance rules win.

## Scope

MVP-0 / MVP-1 / MVP-2 should use Python for the system control plane:

- Event envelope, canonical registry validation, and append-only journal.
- Deterministic reducers, replay runner, state digest, and fixture assertions.
- Access Layer test harness, Interaction Controller, Router, and mock adapters.
- SlowTask mock, UserPatch evidence pipeline, stale result policy, and mock SemanticCommitment.
- Demo Tool Executor, demo backend sandbox, Composer/checker glue, and acceptance/eval runners.

Python is not required to own every future hot path. Realtime audio DSP, VAD/AEC, high-throughput model serving, embedding batches, and heavy eval workloads may later move to process workers, native extensions, sidecar services, or A100-hosted model services.

## Runtime Assumptions

- Assume standard CPython for MVP implementation.
- Do not depend on GIL-free / free-threaded Python for correctness, throughput, or safety.
- Treat Python threads as unsuitable for CPU parallelism in core runtime design.
- Use Python threads only for blocking I/O wrappers, third-party callbacks, or adapter glue that is isolated from critical state mutation.
- Use process-level isolation or sidecars for CPU-bound work that must use multiple cores.

## Concurrency Model

Preferred MVP concurrency shape:

```text
async session runtime
  -> serialized journal append boundary
  -> deterministic state reducers / replay
  -> async adapters for I/O
  -> process pool / worker / sidecar for CPU-heavy or blocking work
```

Rules:

- I/O concurrency should use `asyncio` or an explicit async boundary.
- Event Journal append must be serialized per session and must allocate `event_seq` in one place.
- Critical state transitions must not be advanced by racing Python threads.
- Interaction Controller and reducers should remain deterministic policy/state code.
- Replay must not depend on async task scheduling order.
- Blocking network calls, blocking file operations, provider calls, long CPU tasks, audio DSP, and heavy validation must not run directly inside the event loop.
- If a third-party SDK is blocking-only, wrap it behind an adapter and isolate it in a thread/process executor with timeout/error events.

## Event Journal Boundary

The Event Journal is the ordering and causality boundary:

- All critical runtime transitions must append canonical events before being considered valid for MVP slice completion.
- A single per-session append path owns `event_seq`.
- Async tasks, worker processes, and sidecars may propose events, but the session runtime must serialize accepted events.
- Journal append must enforce event envelope validation, canonical event names, redaction/secret blocking, and required context binding.
- Journal append must not store raw audio, raw traces, secrets, credential headers, or unredacted shareable fixture data.

## Replay and Reducer Determinism

Reducers and deterministic replay must be pure with respect to external systems:

- No network calls.
- No real model calls.
- No real tool execution.
- No clock reads for state decisions.
- No randomness.
- No fetching missing data-plane refs.
- No dependency on async scheduling order.

Replay consumes recorded events in `event_seq` order and produces the same state digest for the same event stream.

## Adapter and Sidecar Boundary

Python can orchestrate external capability, but it must not hide external behavior inside business modules:

- ASR, Thinker, Thinker-as-Composer, Slow LLM, TTS, Duplex model, Embedding/RAG must use adapters.
- Tools must use Tool Executor and tool adapters.
- Rust / Go / Java / C++ sidecars, if introduced, must emit or return normalized data through adapter-shaped interfaces.
- Sidecars must not directly mutate Python state, frontend UI state, SlowTask state, or event journal files.
- Sidecars must not introduce new MVP event names without ADR-002 / event registry updates.
- Sidecars must not perform real external side effects in MVP.

Good future sidecar candidates:

- VAD / AEC / realtime audio pre-processing.
- Playback reference and echo likelihood estimation.
- Local embedding batch jobs.
- Heavy eval runners.
- High-throughput model-serving clients.

Poor sidecar candidates:

- Interaction Controller ownership.
- Event Journal sequencing.
- SlowTask plan version ownership.
- Tool authorization gate.
- Composer fact boundary.

## Blocking and CPU-Heavy Work

Use explicit isolation for:

- Audio DSP, VAD, AEC, and waveform processing.
- Embedding computation and reranking.
- Batch replay/eval over large fixture sets.
- Large schema/eval checks.
- Blocking model SDKs.
- Blocking TTS/ASR clients.

Allowed isolation options:

- `asyncio.to_thread` or thread executor for short blocking I/O adapter glue.
- `ProcessPoolExecutor` / multiprocessing for CPU-bound Python code.
- Native extension when the implementation already releases the GIL and stays behind an adapter.
- Sidecar service when the component has independent lifecycle, resource needs, or deployment target.
- A100-hosted service for model inference.

Whenever an isolated worker affects runtime state, it must report results through canonical events or adapter output events. Late results must obey `plan_version` and stale evidence policy.

## Suggested MVP Tooling

These are recommendations, not hard governance rules:

- Use `pytest` for unit, replay, and acceptance tests.
- Use `pytest-asyncio` or equivalent if async tests are needed.
- Prefer small modules under `src/voice_agent/` following the MVP-0 backlog.
- Prefer dataclasses / TypedDict / lightweight validators for MVP-0 schemas unless stricter runtime validation is needed.
- Introduce Pydantic or another schema library only where it materially improves adapter/event validation.
- Keep fixtures synthetic, redacted, and minimal.
- Keep acceptance commands usable without real model services.

## Code Review Checklist

Flag any Python implementation that:

- Advances critical state without journal events.
- Allocates `event_seq` in multiple concurrent places for the same session.
- Lets threads mutate InteractionState, SlowTaskState, PlaybackState, or ToolExecutionState directly.
- Blocks the event loop with provider calls, file writes, CPU work, audio DSP, or long validation.
- Lets replay call a model, tool, network, clock, random source, or missing ref fetcher.
- Treats Python thread concurrency as CPU parallelism for runtime correctness.
- Introduces sidecars that bypass adapters, Tool Executor, Event Journal, or canonical events.
- Depends on free-threaded Python for MVP behavior.

## Migration Notes

The project may later split into:

```text
Python control plane
  -> Event Journal / Replay / Interaction / Router / SlowTask / Tool Executor

Realtime audio sidecar
  -> VAD / AEC / playback reference / Duplex candidates

Model services
  -> ASR / Thinker / Slow LLM / TTS

Demo frontend/backend
  -> UI state patches via Tool Executor
```

That split must preserve ADR ownership boundaries. Language changes are allowed only when they keep the event journal, adapter contracts, replay determinism, and MVP scope rules intact.
