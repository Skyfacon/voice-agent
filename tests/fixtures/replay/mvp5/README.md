# MVP-5 Replay Fixtures

This directory starts as a metadata-only scaffold for MVP-5 Goal 1. It contains
no replay event fixture and no live-derived payload. The manifest maps every
MVP-5 scenario id to the current safety/prerequisite status so later runtime
goals cannot silently treat missing MVP-4 voice E2E prerequisites as complete.

Committed MVP-5 fixtures must be synthetic, redacted, or minimal before they
enter this directory. Live-derived material is allowed here only after review
has removed raw wav bytes, local wav paths, file names, raw transcripts,
provider request or response bodies, prompt dumps, diagnostics, traces, local
replay cache paths, unredacted real user input, and secrets.

Raw local audio remains local-only under ignored roots such as `audio/raw/`.
Local summaries, diagnostics, and replay cache remain under ignored roots such
as `outputs/`, `diagnostics/`, `traces/`, or `replays/local/`.

Replay must use recorded safe metadata and refs only. It must never rerun ASR,
Thinker, Slow LLM, TTS, tools, network, env secret reads, local wav reads,
clock, or random sources.
