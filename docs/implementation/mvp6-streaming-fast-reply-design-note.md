# MVP6 Streaming Fast Reply Design Note

## Status

Design note only. MVP6.1 does not implement streaming fast reply, gated fast
answer generation, or a second foreground answer model call.

## Current Constraint

The current LALM Thinker live path requests a single
`lalm_thinker_semantic_frame_candidate.v1` JSON object. The adapter can only
emit useful normalized evidence after the full provider text is received,
parsed, validated, and converted into system refs/events.

That means the current JSON-only Thinker output cannot provide a true
time-to-first-token foreground reply. Any partial text before final validation
is untrusted provider output and must not be displayed as an answer.

## Possible Future Protocol

A future streaming protocol could split transport frames into three layers:

- `route_prelude`: early metadata-only evidence that the utterance appears
  likely foreground, complex task, patch, ambiguous, or non-assistant.
- `foreground_reply_delta`: tentative foreground reply text deltas for simple
  one-turn interactions.
- `final_evidence_json`: the complete validated evidence object that Router
  consumes for the final decision.

Router would still be the final route decision owner. The UI could buffer
foreground deltas but should display them only after Router confirms a
foreground route and safety gates pass. For complex task or patch routes, the
UI should discard buffered foreground deltas and use local progress templates
or SlowTask/Composer-owned output instead.

## Boundary Review Required

If a future Thinker stream includes a displayable reply candidate, it may
change the current Thinker evidence-only boundary. That requires ADR or
explicit boundary review before implementation, especially around:

- whether Thinker is still evidence-only or also a foreground composer;
- how Router gates display of any candidate reply;
- how Composer ownership and coverage/truthfulness checks interact with
  streamed text;
- how replay records final decisions without rerunning providers;
- how partial provider output is redacted and kept out of shareable fixtures.

## MVP6.1 Decision

MVP6.1 keeps FAST_ONLY as debug routing output only. It does not call a second
answer model, does not expose unvalidated Thinker deltas, and does not implement
the streaming protocol above.
