# MVP-4 Replay Fixtures

This directory contains GitHub-allowed MVP-4 replay fixtures only.

- Fixtures are synthetic, redacted, or hand-written minimal.
- Fixtures must not contain raw audio, raw transcript text, provider request or response bodies, prompt dumps, local diagnostics/traces/cache paths, unredacted real user input, or secrets.
- Deterministic replay must consume recorded events and refs only; it must not rerun ASR, Thinker, Slow LLM, TTS, tools, network, clock, random, or env reads.

Current fixtures:

- `000-provider-free-voice-e2e.fixture.json`: provider-free voice E2E replay covering fake ASR, fake Thinker, and Router FAST/SPAWN/PATCH decisions.
- `008-replay-safety.fixture.json`: minimal synthetic voice replay safety fixture with recorded ASR/Thinker refs and Router FAST_ONLY outcome.
