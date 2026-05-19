# MVP-2 Acceptance Scenarios

Source of truth: accepted ADR baseline, especially ADR-002, ADR-004, ADR-005, ADR-008, ADR-009, ADR-010, ADR-012, ADR-013, ADR-014, ADR-015, ADR-016, and the derived specs in `docs/specs/event-registry.md`, `docs/specs/state-reducers.md`, and `docs/specs/replay-spec.md`.

MVP-2 validates demo sandbox tools, progressive Tool Executor events, frontend/demo UI state patching, Thinker-as-Composer, coverage checks, progress truthfulness, and webSearch evidence boundary. It does not validate real external side effects, real model adapter quality, production privacy/auth, multi active SlowTask, or pause/resume.

Scenario ids are acceptance labels, not journal event names. Event chains below are causal sketches; committed fixtures must still include common envelope fields and required fields from `docs/specs/event-registry.md`.

All MVP-2 fixtures must be synthetic, redacted, and minimal.

## Scenario MVP2-TOOL-MANIFEST-001

| Field | Spec |
| --- | --- |
| purpose | Validate that Tool Executor records manifest loading for memo, alarm, flashlight, weather, and webSearch without executing tools. |
| initial state | Session started; mock capability snapshot recorded; no active tool call. |
| event chain | `TOOL_MANIFEST_LOADED(tool_name=memo)` -> `TOOL_MANIFEST_LOADED(tool_name=alarm)` -> `TOOL_MANIFEST_LOADED(tool_name=flashlight)` -> `TOOL_MANIFEST_LOADED(tool_name=weather)` -> `TOOL_MANIFEST_LOADED(tool_name=webSearch)`. |
| required assertions | Each manifest records `tool_adapter_id`, `tool_manifest_version`, `side_effect_class`, and optional `risk_class`; webSearch manifest marks external untrusted read category; no execution starts. |
| replay expectations | Deterministic replay reconstructs manifest state in `ToolExecutionState`. |
| forbidden behavior | No demo backend mutation, no `TOOL_EXECUTION_STARTED`, no real adapter or external service call. |
| fixture privacy requirements | Manifest refs contain no endpoint credentials or secrets. |

## Scenario MVP2-TOOL-ARGS-PARTIAL-001

| Field | Spec |
| --- | --- |
| purpose | Validate progressive argument collection when a tool request is missing required fields. |
| initial state | Active SlowTask has current `task_id`, `plan_version`, and proposed tool call with incomplete arguments. |
| event chain | `TOOL_MANIFEST_LOADED` -> `TOOL_CALL_STARTED` optional summary marker -> `TOOL_ARGUMENTS_PARTIAL(missing_fields=[...])`. |
| required assertions | Partial arguments bind `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `partial_arguments_ref`, and `missing_fields`; no execution starts. |
| replay expectations | Replay preserves missing fields and partial argument refs. |
| forbidden behavior | No guessed key argument, no `TOOL_ARGUMENTS_READY`, no `TOOL_EXECUTION_AUTHORIZED`, no `TOOL_EXECUTION_STARTED`. |
| fixture privacy requirements | Argument refs are synthetic/redacted. |

## Scenario MVP2-TOOL-BLOCKED-INSUFFICIENT-ARGS-001

| Field | Spec |
| --- | --- |
| purpose | Validate hard block when resolved arguments or provenance are insufficient. |
| initial state | Active SlowTask lacks current-plan `ARGUMENTS_RESOLVED` or required provenance for a tool. |
| event chain | `TOOL_MANIFEST_LOADED` -> optional `TOOL_ARGUMENTS_PARTIAL` -> `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS(blocking_fields=[...])`. |
| required assertions | Blocked event binds tool/task/plan sequence and `source_event_id`; blocked event is not a retryable tool failure. |
| replay expectations | Replay reconstructs blocked status and no execution state. |
| forbidden behavior | No demo backend call, no `TOOL_EXECUTION_STARTED`, no UI patch, no ToolResult success. |
| fixture privacy requirements | Blocking fields are safe metadata. |

## Scenario MVP2-MEMO-SANDBOX-WRITE-001

| Field | Spec |
| --- | --- |
| purpose | Validate memo tool creates or updates demo notes through sandbox write and UI patch. |
| initial state | Active SlowTask has current-plan resolved memo arguments and provenance. |
| event chain | `TOOL_MANIFEST_LOADED(tool_name=memo)` -> `TOOL_ARGUMENTS_READY` -> optional `TOOL_PREVIEW_AVAILABLE` -> `TOOL_EXECUTION_AUTHORIZED` -> `TOOL_EXECUTION_STARTED` -> `TOOL_PROGRESS_UPDATED` -> `TOOL_UI_STATE_PATCHED` -> `TOOL_RESULT_RECEIVED(trust_level=TRUSTED_DEMO_TOOL_RESULT)`. |
| required assertions | Memo state mutation is sandbox-only; UI patch uses stable `ui_patch_id`, `idempotency_key`, and `patch_ref`; ToolResult binds current plan. |
| replay expectations | Replay reconstructs memo demo state from `TOOL_UI_STATE_PATCHED` and result metadata. |
| forbidden behavior | No external write, no real note app, no model-text-driven UI mutation. |
| fixture privacy requirements | Note content is synthetic/redacted. |

## Scenario MVP2-ALARM-SANDBOX-SCHEDULE-001

| Field | Spec |
| --- | --- |
| purpose | Validate alarm tool creates or updates demo alarm state through sandbox schedule action. |
| initial state | Active SlowTask has resolved alarm time/timezone/label arguments with provenance. |
| event chain | `TOOL_MANIFEST_LOADED(tool_name=alarm)` -> `TOOL_ARGUMENTS_READY` -> `TOOL_PREVIEW_AVAILABLE` -> `TOOL_EXECUTION_AUTHORIZED` -> `TOOL_EXECUTION_STARTED` -> `TOOL_UI_STATE_PATCHED` -> `TOOL_RESULT_RECEIVED(trust_level=TRUSTED_DEMO_TOOL_RESULT)`. |
| required assertions | Alarm state is demo backend state only; no real OS alarm or external calendar is changed. |
| replay expectations | Replay reconstructs alarm list/state from UI patch refs. |
| forbidden behavior | No real scheduling app, no booking/payment, no external communication. |
| fixture privacy requirements | Alarm label/time are synthetic. |

## Scenario MVP2-FLASHLIGHT-DEMO-DEVICE-ACTION-001

| Field | Spec |
| --- | --- |
| purpose | Validate flashlight tool toggles simulated frontend device state through Tool Executor. |
| initial state | Active SlowTask has resolved flashlight target state. |
| event chain | `TOOL_MANIFEST_LOADED(tool_name=flashlight)` -> `TOOL_ARGUMENTS_READY` -> `TOOL_EXECUTION_AUTHORIZED` -> `TOOL_EXECUTION_STARTED` -> `TOOL_UI_STATE_PATCHED(patch_ref=flashlight_state)` -> `TOOL_RESULT_RECEIVED(trust_level=TRUSTED_DEMO_TOOL_RESULT)`. |
| required assertions | Only simulated demo UI state changes; the tool does not control real hardware. |
| replay expectations | Replay reconstructs flashlight on/off state from UI patch. |
| forbidden behavior | No real device control, no direct frontend mutation from model text. |
| fixture privacy requirements | Metadata only. |

## Scenario MVP2-WEATHER-READ-ONLY-001

| Field | Spec |
| --- | --- |
| purpose | Validate weather tool returns structured read-only mock/provider-style result. |
| initial state | Active SlowTask has resolved location/date arguments with provenance. |
| event chain | `TOOL_MANIFEST_LOADED(tool_name=weather)` -> `TOOL_ARGUMENTS_READY` -> `TOOL_EXECUTION_AUTHORIZED` -> `TOOL_EXECUTION_STARTED` -> optional `TOOL_PROGRESS_UPDATED` -> optional `TOOL_UI_STATE_PATCHED` for weather display -> `TOOL_RESULT_RECEIVED(source_type=READ_ONLY_EXTERNAL, trust_level=EXTERNAL_READ_PROVIDER_RESULT)`. |
| required assertions | Weather output is structured normalized fields, not free-form instruction text. Default weather execution returns read-only provider-style evidence without a UI patch; weather display patch is optional and must still use `TOOL_UI_STATE_PATCHED` if present. |
| replay expectations | Replay reconstructs weather result refs and optional display patch. |
| forbidden behavior | No external write, no untrusted free-form provider text entering instruction context. |
| fixture privacy requirements | Weather data is synthetic/mock unless real read-only API is explicitly approved later. |

## Scenario MVP2-WEBSEARCH-UNTRUSTED-EVIDENCE-001

| Field | Spec |
| --- | --- |
| purpose | Validate webSearch as a special Tool whose result is untrusted evidence only. |
| initial state | Active SlowTask has a current-plan read-only search query. |
| event chain | `TOOL_MANIFEST_LOADED(tool_name=webSearch)` -> `TOOL_ARGUMENTS_READY` -> `TOOL_EXECUTION_AUTHORIZED` -> `TOOL_EXECUTION_STARTED` -> `TOOL_PROGRESS_UPDATED(progress_type=searching)` -> `TOOL_RESULT_RECEIVED(source_type=EXTERNAL_READ_UNTRUSTED, trust_level=UNTRUSTED_WEB_EVIDENCE)` -> `EVIDENCE_REVIEWED`. |
| required assertions | Search result contains query, source refs, title/url/short synthetic snippet or summary, `redaction_status`, and trust label; content enters evidence, not instruction. |
| replay expectations | Replay reconstructs search query/result summary/source refs and evidence review chain. |
| forbidden behavior | No real web fetch by default, no raw large web content in fixture, no direct demo backend action from webSearch, no execution of webpage instructions. |
| fixture privacy requirements | Use mock/synthetic search result; no large raw web content. |

## Scenario MVP2-UI-STATE-PATCHED-001

| Field | Spec |
| --- | --- |
| purpose | Validate frontend/demo backend state is mutated only through `TOOL_UI_STATE_PATCHED`. |
| initial state | Tool execution has started and is authorized. |
| event chain | `TOOL_EXECUTION_STARTED` -> `TOOL_UI_STATE_PATCHED(ui_patch_id=..., patch_ref=...)` -> optional `TOOL_PROGRESS_UPDATED` -> `TOOL_RESULT_RECEIVED`. |
| required assertions | UI patch binds tool/task/plan sequence, idempotency key, and patch ref; frontend display is derived from recorded patch state. |
| replay expectations | Replay rebuilds demo UI state without calling a frontend or tool. |
| forbidden behavior | No direct frontend mutation source module; no model-text UI action; no patch without Tool Executor ownership. |
| fixture privacy requirements | Patch refs are synthetic/minimal. |

## Scenario MVP2-DEMO-DESTRUCTIVE-CONFIRMATION-001

| Field | Spec |
| --- | --- |
| purpose | Validate `DEMO_DESTRUCTIVE_ACTION` requires current-plan confirmation before execution starts. |
| initial state | Active SlowTask wants to delete a demo memo or cancel a demo alarm. |
| event chain | `CONFIRMATION_REQUIRED(confirmation_scope=DEMO_DESTRUCTIVE_ACTION)` -> `WAITING_FOR_USER_CONFIRMATION` -> confirmation turn through `USER_PATCH_RECEIVED` / `USER_PATCH_INTERPRETED` -> `USER_CONFIRMATION_RECEIVED` -> `CONFIRMATION_ACCEPTED` -> `TOOL_EXECUTION_AUTHORIZED(confirmation_id=...)` -> `TOOL_EXECUTION_STARTED` -> `TOOL_UI_STATE_PATCHED` -> `TOOL_RESULT_RECEIVED`. |
| required assertions | Missing, rejected, stale, or superseded confirmation blocks execution; accepted confirmation is current-plan. |
| replay expectations | Replay reconstructs confirmation state, authorization, execution, UI patch, and result. |
| forbidden behavior | No raw text shortcut, no real deletion, no execution before confirmation. |
| fixture privacy requirements | Confirmation prompt and user response are synthetic/redacted refs. |

## Scenario MVP2-STALE-TOOL-RESULT-PROGRESSIVE-001

| Field | Spec |
| --- | --- |
| purpose | Validate progressive Tool Executor result follows ADR-004 stale policy after plan advance. |
| initial state | `TOOL_EXECUTION_STARTED(tool_call_id=C1, plan_version=N)` recorded; UserPatch materially advances task to plan `N+1`. |
| event chain | `TOOL_EXECUTION_STARTED(plan_version=N)` -> `USER_PATCH_RECEIVED(plan_version=N)` -> `USER_PATCH_INTERPRETED(materially_changes_task=true)` -> `PLAN_VERSION_ADVANCED(to_plan_version=N+1)` -> optional `TOOL_EXECUTION_CANCEL_REQUESTED` -> `TOOL_RESULT_RECEIVED(plan_version=N)` -> `TOOL_RESULT_MARKED_STALE(current_plan_version=N+1)` -> `STALE_EVIDENCE_RECORDED` -> optional `STALE_EVIDENCE_ADOPTED`. |
| required assertions | Old ToolResult keeps original plan binding; no current-plan advancement without adoption; cancellation unsupported path cannot fake success. |
| replay expectations | Replay reconstructs stale evidence state with and without adoption. |
| forbidden behavior | No SemanticCommitment from old result unless adopted; no reused `task_event_seq`. |
| fixture privacy requirements | Tool result is synthetic/minimized. |

## Scenario MVP2-COMPOSER-SPOKEN-PLAN-001

| Field | Spec |
| --- | --- |
| purpose | Validate Thinker-as-Composer emits SpokenPlan from SemanticCommitment or grounded progress. |
| initial state | SlowTask has current-plan `SEMANTIC_COMMITMENT_EMITTED` or progress source event. |
| event chain | `SEMANTIC_COMMITMENT_EMITTED` or progress event -> `SPOKEN_PLAN_EMITTED`. |
| required assertions | SpokenPlan references source commitment/progress; it carries check-required flags and does not alter immutable facts or progress source ids. |
| replay expectations | Replay reconstructs commitment/progress to spoken plan causal link. |
| forbidden behavior | No unchecked playback, no fact rewrite, no direct model provider call outside adapter. |
| fixture privacy requirements | Spoken text is synthetic/redacted or referenced. |

## Scenario MVP2-COMMITMENT-COVERAGE-001

| Field | Spec |
| --- | --- |
| purpose | Validate CommitmentCoverageCheck gates SemanticCommitment-derived speech. |
| initial state | `SPOKEN_PLAN_EMITTED` references a `SEMANTIC_COMMITMENT_EMITTED`. |
| event chain | `SPOKEN_PLAN_EMITTED(coverage_check_required=true)` -> `COMMITMENT_COVERAGE_CHECK_PASSED` -> `PLAYBACK_SPAN_STARTED(approved_check_event_id=...)`. Failure branch: `COMMITMENT_COVERAGE_CHECK_FAILED` and no playback. |
| required assertions | must-say fields, immutable facts, risk warnings, confirmation state, demo/dry-run status, webSearch attribution, and stale evidence restrictions are checked. |
| replay expectations | Replay can prove playback only follows passed coverage check. |
| forbidden behavior | No playback after failed check; no self-attestation by Composer as coverage pass. |
| fixture privacy requirements | Check result refs contain no raw sensitive values. |

## Scenario MVP2-PROGRESS-TRUTHFULNESS-001

| Field | Spec |
| --- | --- |
| purpose | Validate progress speech is grounded in actual state events. |
| initial state | A progress source event exists, such as `PLANNING_STARTED`, `TOOL_PROGRESS_UPDATED`, `WAITING_FOR_TOOL`, `TOOL_UI_STATE_PATCHED`, `FINALIZING`, `SLOWTASK_FAILED`, or `SEMANTIC_COMMITMENT_EMITTED`. |
| event chain | progress source event -> `SPOKEN_PLAN_EMITTED(truthfulness_check_required=true)` -> `PROGRESS_TRUTHFULNESS_CHECK_PASSED` -> `PLAYBACK_SPAN_STARTED(approved_check_event_id=...)`. Failure branch: `PROGRESS_TRUTHFULNESS_CHECK_FAILED` and no playback. |
| required assertions | Spoken progress references source state event ids and uses allowed truthfulness level, such as `STATE_GROUNDED` or `STYLE_ONLY_ACK`. |
| replay expectations | Replay can verify progress text source events and playback gating. |
| forbidden behavior | No unsupported "already done" wording before ToolResult/UI patch/commitment; no playback after failed truthfulness check. |
| fixture privacy requirements | Spoken/progress refs are synthetic/redacted. |

## Scenario MVP2-ACCEPTANCE-SCOPE-SAFETY-001

| Field | Spec |
| --- | --- |
| purpose | Validate suite-level fixture safety and scope boundaries. |
| initial state | MVP-2 acceptance manifest is loaded. |
| event chain | `REPLAY_STARTED` -> deterministic fixture checks -> `REPLAY_COMPLETED`. |
| required assertions | Required scenario ids are present; fixture domain is `GITHUB_ALLOWED`; replay mode is deterministic; fixtures are synthetic/redacted/minimal; forbidden real side effects and direct UI mutation are absent. |
| replay expectations | Acceptance runner can report pass/fail without network/model/tool execution. |
| forbidden behavior | No raw audio, raw trace, secrets, unredacted real input, unredacted sensitive ToolResult, large raw web content, real adapters, real external side effects, direct frontend mutation. |
| fixture privacy requirements | All committed MVP-2 fixtures satisfy repo-safe replay policy. |

## MVP-2 Scenario Suite Requirements

- The acceptance runner must cover every scenario id in this document.
- Every scenario must replay deterministically from recorded events and refs.
- Every tool event must bind `tool_call_id`, `task_id`, `plan_version`, and `task_event_seq` where required by the registry.
- Tool execution must be owned by Tool Executor.
- Frontend/demo UI state changes must be represented by `TOOL_UI_STATE_PATCHED`.
- webSearch ToolResult must use `trust_level=UNTRUSTED_WEB_EVIDENCE` and evidence-only prompt placement.
- `DEMO_DESTRUCTIVE_ACTION` must require current-plan `CONFIRMATION_ACCEPTED`.
- Composer output must pass the relevant check before playback.
- Fixtures must fail safety checks if they contain raw audio, raw trace, secrets, unredacted real user input, unredacted sensitive ToolResult, or large raw web content.
- The suite must fail if a fixture introduces unregistered MVP-relevant journal event names.
