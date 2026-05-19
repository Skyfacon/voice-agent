# ASR Qwen-ASR Streaming Eval Dry-Run Summary

## Status

dry_run_metadata_only

## Observation Count

- observations: 5
- unique cases: 5

## Capability Labels

- `prior_observed_degraded_client_timeout`: 1
- `prior_observed_degraded_non_speech_risk`: 1
- `prior_observed_real_filetrans_timestamps`: 1
- `prior_observed_real_final_transcript`: 1
- `prior_observed_real_response_streaming_output`: 1

## Case Results

| case | output mode | expected evidence label | chunks | first delta ms | timestamp status | failure |
| --- | --- | --- | ---: | ---: | --- | --- |
| short_command_nonstream_baseline | mock | prior_observed_real_final_transcript | 0 | None | degraded | None |
| streaming_output_delta_probe | mock | prior_observed_real_response_streaming_output | 4 | 1306 | unavailable | None |
| filetrans_timestamp_probe | mock | prior_observed_real_filetrans_timestamps | 0 | None | normalized | None |
| silence_non_speech_probe | mock | prior_observed_degraded_non_speech_risk | 0 | None | unavailable | None |
| client_timeout_probe | mock | prior_observed_degraded_client_timeout | 0 | None | unavailable | client_timeout |

## Boundary Notes

- Qwen-ASR is ASR text projection evidence, not turn ingress owner.
- ASR transcript output is not SemanticCommitment.
- Response streaming output does not prove true realtime microphone streaming input.
- Client close or timeout is not provider-confirmed cancellation.
- Deterministic replay consumes metadata or synthetic fixtures and does not rerun ASR.

## Privacy Notes

- No audio recordings are stored.
- No provider request or response bodies are stored.
- No local traces or replay caches are stored.
- No real user input is used.
