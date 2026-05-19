# TTS CosyVoice Playback Eval Dry-Run Summary

## Status

dry_run_metadata_only

## Observation Count

- observations: 5
- unique cases: 5

## Capability Labels

- `prior_observed_degraded_client_close`: 1
- `prior_observed_real_basic_synthesis`: 1
- `prior_observed_real_streaming_audio`: 1
- `synthetic_playback_progress_shape`: 1
- `synthetic_truncate_chain_shape`: 1

## Case Results

| case | kind | output mode | expected evidence label | chunks | progress events | truncate requested | actual stop offset ms | stream end reason |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | --- |
| basic_short_synthesis | adapter_synthesis_observation | mock | prior_observed_real_basic_synthesis | 15 | 0 | False | None | task_finished |
| streaming_audio_probe | stream_chunk_summary | mock | prior_observed_real_streaming_audio | 23 | 0 | False | None | task_finished |
| playback_progress_probe | playback_event_observation | mock | synthetic_playback_progress_shape | 0 | 5 | False | None | not_applicable |
| truncate_mid_utterance_probe | truncate_event_observation | mock | synthetic_truncate_chain_shape | 0 | 4 | True | 1240 | not_applicable |
| client_close_during_stream_probe | adapter_failure_observation | degraded | prior_observed_degraded_client_close | 3 | 0 | False | None | client_closed |

## Boundary Notes

- CosyVoice/TTS is audio synthesis evidence, not turn ingress owner.
- TTS output and playback committed are not user acknowledgement.
- TTS output and playback committed are not SemanticCommitment.
- Talker/playback owns playback span state.
- Interaction Controller owns truncate request.
- TTS adapter only provides audio stream/file metadata.
- Client close or provider stream close is not TTS_TRUNCATED.
- TTS_TRUNCATED requires Talker-confirmed actual stop offset.
- Deterministic replay consumes metadata or synthetic fixtures and does not rerun TTS.

## Privacy Notes

- No generated audio is stored.
- No provider request or response bodies are stored.
- No local traces or replay caches are stored.
- No real user input is used.
