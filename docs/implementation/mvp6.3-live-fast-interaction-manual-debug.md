# MVP6.3 Live Fast Interaction Manual Debug Flow

## Status

Local-only manual debug instructions. Do not commit approval packets, raw audio,
provider request bodies, provider response bodies, local QA history, diagnostics,
secrets, or local replay cache.

## Acceptance Scenarios

- MVP6.3-LIVE-FAST-ANSWER-PASS-001
- MVP6.3-LIVE-FAST-TIMEOUT-FALLBACK-001
- MVP6.3-LIVE-SLOW-DISCARD-TEMPLATE-001
- MVP6.3-LIVE-PATCH-DISCARD-TEMPLATE-001
- MVP6.3-REPLAY-NO-PROVIDER-RERUN-001
- MVP6.3-SAFETY-EXPORT-001

## Approval Packet Shape

Audio-native primary Fast Interaction uses one provider call. Do not include ASR
in the primary approval packet unless the local run explicitly enables the
ASR-text fallback path.

```json
{
  "approval_id": "mvp6.3-live-fast-interaction-local",
  "live_provider_opt_in": true,
  "local_wav_opt_in": true,
  "metadata_only_output": true,
  "replay_reruns_provider": false,
  "provider_adapter_ids": [
    "mvp63_fast_interaction_runtime"
  ],
  "credential_env_var_name": "DASHSCOPE_API_KEY",
  "max_provider_calls": 1,
  "timeout_ms": 1500,
  "safe_output_ref": "summary://mvp6.3/live-fast-interaction/local"
}
```

For an explicit ASR-text fallback run, use
`provider_adapter_ids=["mvp5_asr_adapter","mvp63_fast_interaction_runtime"]`
and `max_provider_calls=2`, and verify metadata labels
`fast_interaction_input_mode=asr_text_fallback`.

## Run

```bash
scripts/mvp6-debug-console --approval-packet outputs/mvp6-debug-console/mvp6.3-approval.json
```

Open `http://127.0.0.1:8766`.

## Expected Metadata

- `fast_interaction_output_mode=real|degraded|fallback`
- `foreground_gate_decision=passed|failed|not_run`
- `foreground_output_basis=reply_candidate|template_ack|template_clarify|silence_policy`
- `fast_interaction_provider_http_ms`
- `fast_interaction_parse_validate_emit_ms`
- `fast_interaction_total_ms`
- `fast_interaction_timed_out`

## Safety Checks

The response and QA history must not include raw audio, raw prompt, provider
body, provider response, local paths, credentials, authorization headers,
diagnostics, traces, local replay cache, or unredacted real user input.

Deterministic replay must use recorded events and refs only. It must not rerun
ASR, Fast Interaction, Thinker, TTS, tools, or external providers.
