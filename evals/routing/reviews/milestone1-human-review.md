# Milestone 1 Human Review Gate

## Purpose

This gate turns the current 80-case draft corpus into a human-approved routing ontology baseline. It reviews product policy and gold labels, not model quality.

Review inputs:

- [prompt-dev manifest](../manifests/prompt-dev.jsonl)
- [routing labeling guide](../rubrics/routing-labeling-guide.md)
- [error-cost policy](../rubrics/error-cost-policy.md)
- [evaluation contract](../README.md)

The review packet is produced with `build_human_review_packet()` from `voice_agent.evals.routing.review_packet`. It includes every `high`, `AMBIGUOUS`, or `contrast_set` case, so all 80 current cases require human review. These 20 four-case families are not strict one-variable minimal pairs. Older manifests carrying the legacy `minimal_pair` tag are selected as contrast sets for backward compatibility only.

The packet must not contain model predictions, scores, provider payloads, prompt dumps, raw audio, local paths, secrets, or real-user data. Reviewers judge the proposed policy without seeing a system answer.

## Roles

Assign opaque, non-personal identifiers:

- `reviewer_a`: independently reviews every case.
- `reviewer_b`: independently reviews every case without seeing reviewer A's decisions.
- `adjudicator`: resolves disagreements and product-policy questions; must not be one of the two reviewers for that disputed case.
- `gate_owner`: verifies completion criteria and records the final Gate 1 decision.

One person may hold the gate-owner role and an adjudicator role, but may not adjudicate a case they reviewed initially.

## Generate the safe review packet

The simplest entrypoint renders the safe packet to standard output:

```bash
scripts/routing-eval review
```

The equivalent public APIs are shown below. Do not manually copy all manifest content into another document:

```python
from voice_agent.evals.routing.loader import load_routing_cases_jsonl
from voice_agent.evals.routing.review_packet import (
    build_human_review_packet,
    render_human_review_packet_markdown,
)

cases = load_routing_cases_jsonl(
    "evals/routing/manifests/prompt-dev.jsonl",
    expected_split="prompt_dev",
)
packet = build_human_review_packet(cases)
markdown = render_human_review_packet_markdown(packet)
```

Before distributing it, verify:

- `source_case_count == 80` and `review_case_count == 80`;
- all safety flags indicate that prohibited content is absent;
- the packet stays in an approved review location and is not augmented with runtime output;
- reviewers receive the same manifest version or content hash.

## Per-case review

For each case, review the following fields in order.

1. **Synthetic input**
   - Is the utterance natural enough to express the intended distinction?
   - Does it avoid real-person, credential, local-path, or other sensitive data?
   - Does it expose only information a runtime model would actually receive?

2. **Context**
   - Is the context template appropriate?
   - If an active task exists, do its summary, lifecycle phase, `plan_version`, and optional confirmation scope make the utterance interpretable?
   - Is the confirmation scope one of the ADR-016 canonical values?

3. **Task focus**
   - Does `task_focus_allowed` correctly distinguish `FOREGROUND_CHAT`, `NEW_TASK_CANDIDATE`, `ACTIVE_TASK_PATCH`, `CANCEL_OR_PAUSE_CANDIDATE`, `NON_ASSISTANT`, and `AMBIGUOUS`?
   - If multiple focus labels are allowed, is the ambiguity genuine rather than unresolved reviewer preference?

4. **Router policy**
   - Are `router_decisions_allowed` and `router_decisions_forbidden` disjoint and collectively exhaustive across all four Router decisions?
   - Does an active-task new-task candidate follow `PATCH_ACTIVE_SLOW_TASK` for switch evidence rather than spawning a second active task?
   - Does an ambiguous input avoid patching the active task?

5. **Foreground policy**
   - Is `ANSWER` restricted to low-risk `FAST_ONLY` behavior?
   - Do task, patch, ambiguous, and non-assistant cases use `ACK_SLOW`, `ACK_PATCH`, `CLARIFY`, or `SILENCE` consistently with the labeling guide?
   - Would the policy prevent a candidate answer from claiming tool, confirmation, task, or external-effect facts?

6. **Side-effect expectations**
   - Does `slow_task_created` match the permitted spawn behavior?
   - Does `user_patch_emitted` match the permitted patch behavior?
   - Is `external_side_effects` exactly `FORBIDDEN`?

7. **Rationale and severity**
   - Do the rationale tags identify the decisive boundary without leaking a model answer?
   - Is `criticality` appropriate for the consequence of misrouting?
   - Does the case form a meaningful contrast with other members of its `scenario_family_id`?

Each reviewer records one decision:

- `accept`: proposed gold and metadata are correct;
- `change`: supply a complete replacement for the disputed gold/metadata fields and a short policy rationale;
- `needs_product_policy`: the rubrics do not determine a safe answer;
- `reject_case`: the case is unsafe, redundant, internally inconsistent, or not reviewable.

## Decisions that require human judgment

Automation may validate schema, quotas, split isolation, canonical enums, safe fields, and packet projection. Humans must decide:

- the practical boundary between a brief answer and a SlowTask;
- when current information, tools, planning, tracking, risk, or artifact size requires `SPAWN_SLOW_TASK`;
- whether speech during an active task is side chat, a patch, a switch candidate, or a cancel/pause candidate;
- whether unclear directedness or ownership should produce `CLARIFY` or `SILENCE`;
- whether an allowed-set ambiguity is product-intentional;
- the relative harm and criticality of a misroute;
- whether Chinese phrasing and the contrast sets represent realistic user intent;
- whether the critical-violation and error-cost policies are acceptable for ontology v1.

An AI draft or automated agreement may assist triage but cannot change a case from `draft` to a human status.

## Review record

Keep decisions in a repository-safe structured ledger separate from the manifest until adjudication completes. One record per reviewer and case should contain only:

```json
{
  "case_id": "opaque_case_id",
  "manifest_version": "opaque_version_or_hash",
  "reviewer_id": "reviewer_a",
  "reviewer_role": "reviewer",
  "decision": "accept|change|needs_product_policy|reject_case",
  "proposed_fields": {},
  "rationale_tags": ["short_safe_tag"],
  "reviewed_at": "ISO-8601 timestamp"
}
```

For adjudication, add a separate record with:

- `reviewer_role=adjudicator`;
- references to both review records by safe ID;
- `decision=accept|change|reject_case`;
- the final complete field replacement when changed;
- short policy rationale tags;
- the ontology/rubric version used.

Use opaque reviewer IDs, not names or email addresses. Do not put utterance text, model output, audio, provider data, prompts, secrets, or local file paths in the ledger. The manifest remains the source of final case content.

After agreement:

- set `annotation_status=human_reviewed` when both reviewers agree and no adjudication was required;
- set `annotation_status=adjudicated` when an adjudicator resolved a disagreement;
- keep `annotation_status=draft` while `needs_product_policy` is unresolved;
- apply accepted field changes to the manifest in one reviewed change, then rerun schema and corpus audits.

## Disagreement and adjudication flow

1. Freeze the reviewed manifest version before independent review starts.
2. Collect both decisions without exposing either reviewer's answer to the other.
3. If both accept, mark the case `human_reviewed`.
4. If both propose the same complete change, the gate owner verifies it against the rubrics and marks the case `human_reviewed` after applying it.
5. Any other disagreement goes to the adjudicator with both rationales and the relevant scenario-family cases.
6. The adjudicator must choose a rubric-supported final label, reject the case, or declare a missing product policy.
7. A missing product policy is recorded as a rubric/ontology issue; the case stays `draft` and Gate 1 remains blocked.
8. After changes, both original reviewers verify that the contrast-set family still expresses the intended routing contrasts.

Do not resolve disagreement by consulting model predictions or choosing the label with the better model score.

## Passing criteria

Gate 1 passes only when all of the following are true:

- all 80 cases have two independent human review records;
- every disagreement has an adjudication record;
- no case remains `draft`, `needs_product_policy`, or `reject_case` in the accepted corpus;
- every accepted case is `human_reviewed` or `adjudicated`;
- all eight context templates remain covered;
- all 20 contrast-set families have at least two members and at least two meaningful routing outcomes;
- case IDs are unique and no `scenario_family_id` crosses a split;
- allowed/forbidden Router decisions partition all four decisions for every case;
- all confirmation scopes are canonical and all external side effects remain forbidden;
- the corpus audit passes with the approved Gate 1 policy;
- the gate owner signs off the labeling guide, critical violations, and error-cost policy as ontology v1;
- no model result, real-user data, raw audio, provider/prompt material, secret, or local path entered the review artifacts.

The gate decision record should contain the manifest version/hash, rubric versions, corpus-audit result reference, reviewer/adjudicator opaque IDs, decision (`passed` or `blocked`), and timestamp. It must not contain case text or runtime predictions.

Passing Gate 1 authorizes expansion of the human-approved ontology to the planned larger synthetic corpus. It does not claim model capability or production readiness.
