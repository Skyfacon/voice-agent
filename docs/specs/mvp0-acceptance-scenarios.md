# MVP-0 Acceptance Scenarios

Source of truth: frozen ADR Baseline v0.4. This document carries P1-B-005. It is a spec detail, derived from ADR baseline.

MVP-0 goal: prove event-driven live loop skeleton, module boundaries, interrupt/truncate, trace/replay, and mock capability labeling. [ADR-012]

MVP-0 explicitly excludes:

- real ASR requirement
- real TTS requirement
- real Qwen3-Omni requirement
- real GLM requirement
- real external tool
- real side-effect tool
- booking / payment / deletion
- full assistant-directedness
- full semantic_close
- pause / resume TTS

## Scenario MVP0-TEXT-INGRESS-001

| Field | Spec |
| --- | --- |
| scenario_id | `MVP0-TEXT-INGRESS-001` |
| goal | Verify text input enters through Access Layer and Interaction Controller before Router. [ADR-001, ADR-002, ADR-012] |
| non_goal | No Duplex, no synthetic audio span, no real model requirement, no SlowTask/tool execution. |
| initial_state | Session started; adapter capability snapshot recorded with mock ASR/Thinker/TTS; `InteractionState.turn_phase=IDLE`; `playback_phase=NOT_PLAYING`; no active SlowTask. |
| input_events | `SESSION_STARTED`; `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`; `TEXT_INPUT_RECEIVED(input_modality=text, text_span_id=TXT1, audio_span_id=null, directedness=ASSUMED_DIRECTED, semantic_close=ASSUMED_CLOSED)`. |
| expected_output_events | `TURN_OPENED(turn_id=T1, text_span_id=TXT1)`; `TURN_INGRESS_ACCEPTED(turn_id=T1)`; `TURN_INGRESS_COMMITTED(turn_id=T1, input_modality=text, text_span_id=TXT1, audio_span_id=null)`; `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)`; `ROUTER_DECISION_EMITTED`; optional mock fast response and playback events if demo loop includes response. |
| expected_state_changes | `InteractionState.current_text_span_id=TXT1`; `current_audio_span_id=null`; `directedness=ASSUMED_DIRECTED`; `semantic_close=ASSUMED_CLOSED`; `last_ingress_outcome=COMMITTED`; `turn_phase=TURN_COMMITTED`. |
| expected_trace_entries | Event envelope fields valid; causal link from `TEXT_INPUT_RECEIVED` to interaction events; redacted text or `text_ref`, not unredacted required. |
| replay_assertions | Deterministic replay reconstructs same InteractionState; Router has no decision before `TURN_INGRESS_COMMITTED`; no audio reducer state is created for text. |
| privacy_assertions | Shareable fixture may use synthetic/redacted text; no raw audio; no secrets. |
| pass_fail_criteria | Pass if event chain exactly includes text ingress through Interaction Controller and no synthetic `audio_span_id`; fail if Access Layer routes directly to Router or ASR/Thinker before commit. |

## Scenario MVP0-AUDIO-INGRESS-001

| Field | Spec |
| --- | --- |
| scenario_id | `MVP0-AUDIO-INGRESS-001` |
| goal | Verify audio input enters via audio span, Duplex speech detection, Interaction commit, then mock ASR/Thinker. [ADR-001, ADR-002, ADR-012] |
| non_goal | No real ASR, real Thinker, true semantic_close, true assistant-directedness, raw audio fixture, or SlowTask. |
| initial_state | Session started; mock adapter snapshot recorded; `InteractionState.turn_phase=IDLE`; no active playback. |
| input_events | `AUDIO_SPAN_STARTED(audio_span_id=A1, audio_sample_offset=0)`; `SPEECH_START_DETECTED(audio_span_id=A1)`; `AUDIO_SPAN_ENDED(audio_span_id=A1)`; `SPEECH_END_DETECTED(audio_span_id=A1, semantic policy acceptable by mock/rule policy)`. |
| expected_output_events | `TURN_OPENED(turn_id=T1, audio_span_id=A1, input_modality=audio)`; `TURN_INGRESS_ACCEPTED(turn_id=T1, audio_span_id=A1)`; `TURN_INGRESS_COMMITTED(turn_id=T1, utterance_id=U1, input_modality=audio, audio_span_id=A1)`; `MOCK_ASR_FRAME_EMITTED(output_mode=mock)`; `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)`; `ROUTER_DECISION_EMITTED`. |
| expected_state_changes | `InteractionState.turn_phase=COLLECTING_INPUT` after speech start; final `turn_phase=TURN_COMMITTED`; `current_audio_span_id=A1`; `last_ingress_outcome=COMMITTED`. |
| expected_trace_entries | Audio span events contain offsets and no raw audio; mock adapter output mode visible; causal chain from audio/Duplex events to commit. |
| replay_assertions | Replay reconstructs InteractionState; no ASR/Thinker frame exists before `TURN_INGRESS_COMMITTED`; SLO metrics can compute speech_start latency and first acknowledgement latency if response events are present. |
| privacy_assertions | Raw audio not required and not included in shareable fixture; fixture may include only audio metadata. |
| pass_fail_criteria | Pass if mock ASR/Thinker occur only after committed audio turn; fail if audio span is routed directly to ASR/Thinker or raw audio is required for deterministic replay. |

## Scenario MVP0-BARGE-IN-TRUNCATE-001

| Field | Spec |
| --- | --- |
| scenario_id | `MVP0-BARGE-IN-TRUNCATE-001` |
| goal | Verify truncate-only barge-in causal chain with distinct playback offsets. [ADR-003, ADR-012] |
| non_goal | No pause/resume, semantic-clause resume, multi-track recovery, real TTS model cancellation guarantee, or full duplex semantic model. |
| initial_state | Session started; mock TTS/Talker supports playback progress and truncate; `PlaybackState=PLAYING` for `playback_span_id=P1`; InteractionState playback phase is `PLAYING`. |
| input_events | `PLAYBACK_SPAN_STARTED(P1)`; `PLAYBACK_PROGRESS(P1, playback_offset_ms=900)`; `PLAYBACK_COMMITTED(P1, playback_offset_ms=850)`; `AUDIO_SPAN_STARTED(A2)`; `SPEECH_START_DETECTED(A2)`; `BARGE_IN_CANDIDATE(A2, P1, playback_offset_ms=910, echo_likelihood=low, vad_confidence=high, barge_in_confidence=high)`. |
| expected_output_events | `INTERRUPT_CANDIDATE(P1, playback_offset_ms=latest_known)`; `TTS_TRUNCATE_REQUESTED(P1, cutoff_playback_offset_ms=latest_known, interrupt_candidate_event_id=...)`; `TTS_TRUNCATED(P1, actual_stop_offset_ms=...)`; optional continued input collection and later turn commit if speech completes. |
| expected_state_changes | InteractionState `turn_phase=INTERRUPTING` during request; playback phase `TRUNCATE_REQUESTED` then `TRUNCATED`; PlaybackState for P1 terminal `TRUNCATED`. |
| expected_trace_entries | Candidate-time offset, request cutoff offset, and actual stop offset are separate fields; causal chain preserved by `caused_by_event_id` and request ids. |
| replay_assertions | Replay reconstructs candidate -> interrupt -> truncate request -> truncated chain; barge-in to truncate command latency can be computed and is <= 250ms for passing fixture; `PLAYBACK_COMMITTED` is not treated as semantic acknowledgement. |
| privacy_assertions | No raw mic or playback audio in shareable fixture; echo/barge confidence values are metadata. |
| pass_fail_criteria | Pass if truncate request and Talker confirmation exist with distinct offsets and matching `playback_span_id`; fail if no playback reference is present, if truncate is not journaled, or if pause/resume is required. |

## Scenario MVP0-MOCK-ADAPTER-CAPABILITY-001

| Field | Spec |
| --- | --- |
| scenario_id | `MVP0-MOCK-ADAPTER-CAPABILITY-001` |
| goal | Verify all MVP-0 mock adapters declare capability matrices and outputs are labeled mock. [ADR-011, ADR-012] |
| non_goal | No real provider health requirement, real endpoint requirement, or target validation of unsupported mocked capabilities. |
| initial_state | Empty session before startup. |
| input_events | `SESSION_STARTED`; adapter registry startup probe/config load. |
| expected_output_events | `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` containing ASR mock, Thinker mock, TTS/Talker mock, optional Slow Agent mock and Tool mock; later `MOCK_ASR_FRAME_EMITTED(output_mode=mock)` and `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)` when scenarios run. |
| expected_state_changes | AdapterHealthState stores capability snapshot refs, deployment modes, output modes, and missing/unsupported capabilities. |
| expected_trace_entries | Capability matrix includes required capability booleans and mock markers; no provider credentials or raw endpoint secrets. |
| replay_assertions | Replay reconstructs AdapterHealthState from snapshot without probing adapters; mock outputs remain distinguishable from real/fallback/degraded. |
| privacy_assertions | Endpoint/config refs do not include API keys, tokens, cookies, credentials, authorization headers, or session secrets. |
| pass_fail_criteria | Pass if startup snapshot is present and every mock output is labeled mock; fail if a mock claims real capability without `mocked=true` or if unsupported capability is used silently. |

## Scenario MVP0-LOCAL-TRACE-SAFETY-001

| Field | Spec |
| --- | --- |
| scenario_id | `MVP0-LOCAL-TRACE-SAFETY-001` |
| goal | Verify MVP-0 local trace defaults and shareable fixture boundaries. [ADR-010, ADR-015, ADR-012] |
| non_goal | No production privacy policy, no raw audio export, no real webSearch fixture, no repo governance implementation code. |
| initial_state | Session startup config: `local_debug_trace_enabled=true`; `raw_audio_enabled=false`; `credential_trace_policy=never`; shareable export gate available as spec behavior. |
| input_events | Representative text or audio ingress scenario plus a trace write operation; optional synthetic secret-like payload attempted in a controlled fixture. |
| expected_output_events | Normal event journal entries; if trace storage degrades, `TRACE_WRITE_DEGRADED`; if secret-like content is detected and removed, `TRACE_SECRET_REDACTION_APPLIED`; if it cannot be safely removed, `TRACE_WRITE_BLOCKED_SECRET_DETECTED`; replay emits `REPLAY_STARTED` and `REPLAY_COMPLETED`. |
| expected_state_changes | TracePrivacyState records raw audio disabled, no secrets stored, redaction/block counters if exercised, replay result status. |
| expected_trace_entries | Local debug trace can include event journal and mock outputs; shareable fixture contains only synthetic/redacted/minimal metadata and refs. |
| replay_assertions | Deterministic replay works without raw audio; state digest excludes raw audio, raw text, raw secret, and raw tool credential payloads. |
| privacy_assertions | No raw audio, raw debug trace, API key, token, cookie, credential, authorization header, session secret, unredacted real user input, or large raw web content appears in shareable/GitHub fixture. |
| pass_fail_criteria | Pass if local trace is useful for replay while raw audio is disabled by default and secret-like content is redacted/blocked before write/export; fail if raw audio or secrets are required for deterministic replay or appear in shareable fixture. |

## MVP-0 Completion Summary

MVP-0 is accepted only when all required scenarios pass:

- Text ingress through Interaction Controller.
- Audio ingress through Duplex and Interaction Controller.
- Truncate-only barge-in causal replay.
- Mock adapter capability snapshot and output mode labeling.
- Local trace safety and deterministic replay without raw audio.

All SLO measurements produced by these scenarios must be labeled mock/degraded/real as applicable. [ADR-012]
