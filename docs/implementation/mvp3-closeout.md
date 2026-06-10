# MVP-3 Closeout

## MVP-3 Slice 0-9 Coverage

MVP-3 closes with a provider-free acceptance runner over every scenario id in
`docs/specs/mvp3-acceptance-scenarios.md`.

- Slice 0: fixture/replay safety skeleton through `000-empty-mvp3-session.fixture.json`.
- Slice 1: adapter profile readiness gates and provider-agnostic capability snapshot metadata.
- Slice 2: adapter health, retry, failure, validation failure, and degraded event paths.
- Slice 3: runtime assembly startup snapshot without provider probes.
- Slice 4: ASR final transcript output contract with explicit mode labels and safe refs.
- Slice 5: Thinker normalized SemanticFrame-compatible output contract.
- Slice 6: Slow LLM structured output validation, fallback, and old-plan non-adoption.
- Slice 7: TTS normalized audio refs and truncate degradation.
- Slice 8: deterministic fallback/degraded replay with adapter health digest coverage.
- Slice 9: manifest runner and closeout safety gates.

## Non-Goals

This closeout does not connect a real provider, add provider SDK dependencies,
perform healthcheck or startup network probes, add external side-effect tools,
change Tool Executor, Composer, frontend behavior, add multi SlowTask support,
or introduce pause/resume.

## Remaining Risks

- Real provider integration still needs separate adapter-internal work and
  provider-specific privacy review.
- Latency SLOs remain development measurements until real provider endpoints
  exist.
- Production trace privacy, credential handling, and raw audio retention policy
  remain outside MVP-3.

## Verification Commands

- `./scripts/test tests/acceptance/test_mvp3_acceptance_scenarios.py -q`
- `./scripts/test tests/replay -q`
- `./scripts/test tests/adapters -q`
- `./scripts/test tests/events -q`
- `./scripts/test -q`

The acceptance runner uses committed synthetic/redacted/minimal fixtures and
recorded refs/events only. It rejects unsafe fixture flags, direct provider or
network refs, missing mode labels, weakened replay properties, and MVP scope
broadening.
