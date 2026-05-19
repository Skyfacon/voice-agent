# Duplex VAD Runs

This directory is documentation-only for the spike-local harness.

Do not commit generated raw audio, local traces, local replay cache, temporary
venvs, or large probe outputs here. Committed run summaries should be
metadata-only and should normally live under `docs/research/spikes/`.

Allowed committed content:

- small README files;
- schema notes;
- summarized metadata tables;
- synthetic, redacted, minimal examples.

Disallowed committed content:

- raw WAV/PCM/MP3 audio;
- real user recordings;
- local trace dumps;
- replay cache;
- credential-bearing logs;
- provider payloads.
