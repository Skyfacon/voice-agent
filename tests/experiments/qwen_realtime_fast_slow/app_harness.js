"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadDomHarness() {
  const helperPath = path.join(__dirname, "..", "qwen_app_transcript_harness.js");
  const source = fs.readFileSync(helperPath, "utf8");
  const boundary = source.indexOf("function conversation(environment)");
  assert.ok(boundary > 0, "shared DOM harness boundary was not found");
  const declarations = source.slice(0, boundary);
  const moduleStub = { exports: {} };
  const expose = new Function(
    "require",
    "module",
    "exports",
    "__filename",
    "__dirname",
    `${declarations}\nmodule.exports = { createEnvironment, evaluate };`,
  );
  expose(require, moduleStub, moduleStub.exports, helperPath, path.dirname(helperPath));
  return moduleStub.exports;
}

const { createEnvironment, evaluate } = loadDomHarness();

function environmentFor(appPath) {
  const environment = createEnvironment(appPath);
  environment.context.TextEncoder = TextEncoder;
  return environment;
}

function dispatch(environment, type, fields = {}) {
  environment.context.__qfsControl = JSON.stringify({
    type,
    protocol_version: 2,
    ...fields,
  });
  vm.runInContext("handleControlFrame(__qfsControl)", environment.context);
}

function quarantineVisibility(appPath) {
  const environment = environmentFor(appPath);
  const conversation = environment.document.getElementById("conversation");
  const timeline = environment.document.getElementById("timeline");
  const candidate = "QUARANTINED-CANDIDATE-MUST-NOT-BE-VISIBLE";

  dispatch(environment, "route.proposed", {
    scenario: "spawn",
    route_hint: "FAST_ONLY",
    task_focus_hint: "FOREGROUND_CHAT",
    foreground_act: "ANSWER",
    risk_class: "LOW",
    confidence: 0.99,
    reply_candidate: candidate,
    text: candidate,
    raw_audio: candidate,
  });
  dispatch(environment, "route.decided", {
    router_decision: "SPAWN_SLOW_TASK",
    task_focus: "NEW_TASK_CANDIDATE",
  });
  dispatch(environment, "gate.result", {
    gate_status: "discarded",
    failure_reason: "non_fast_route",
  });

  assert.equal(conversation.textContent.includes(candidate), false);
  assert.equal(timeline.textContent.includes(candidate), false);
  assert.equal(conversation.querySelectorAll(".message.assistant").length, 0);

  dispatch(environment, "transcript.assistant.done", {
    response_id: "controlled-ack",
    text: "已开始处理这个任务。",
  });
  assert.equal(conversation.querySelectorAll(".message.assistant").length, 1);
  assert.match(conversation.textContent, /已开始处理这个任务/);
  return { assistant_rows_before_authorized: 0, assistant_rows_after_authorized: 1 };
}

function taskStateAuthority(appPath) {
  const environment = environmentFor(appPath);
  const taskId = environment.document.getElementById("taskId");
  const planVersion = environment.document.getElementById("planVersion");
  const initialTask = taskId.textContent;
  const initialVersion = planVersion.textContent;

  dispatch(environment, "route.proposed", {
    route_hint: "PATCH_ACTIVE_SLOW_TASK",
    task_id: "provider-must-not-own-task",
    plan_version: 999,
  });
  assert.equal(taskId.textContent, initialTask);
  assert.equal(planVersion.textContent, initialVersion);

  dispatch(environment, "slowtask.state", {
    task_id: "task-safe-1",
    lifecycle: "WAITING_CONFIRMATION",
    plan_version: 1,
  });
  assert.equal(taskId.textContent, "task-safe-1");
  assert.equal(planVersion.textContent, "1");

  dispatch(environment, "userpatch.accepted", {
    status: "accepted",
    plan_version: 2,
  });
  assert.equal(planVersion.textContent, "2");
  return { task_id: taskId.textContent, plan_version: planVersion.textContent };
}

function boundedTimeline(appPath) {
  const environment = environmentFor(appPath);
  for (let index = 0; index < 140; index += 1) {
    dispatch(environment, "flow.changed", {
      dropped_input_frames: index,
      authorization: "Bearer secret must not render",
      raw_audio: "raw bytes must not render",
    });
  }
  const timeline = environment.document.getElementById("timeline");
  assert.ok(timeline.children.length <= 100);
  assert.equal(timeline.textContent.includes("Bearer"), false);
  assert.equal(timeline.textContent.includes("raw bytes"), false);
  return { timeline_rows: timeline.children.length };
}

function shadowProjectionIsolation(appPath) {
  const environment = environmentFor(appPath);
  const document = environment.document;
  const conversation = document.getElementById("conversation");
  const timeline = document.getElementById("timeline");
  const taskId = document.getElementById("taskId");
  const planVersion = document.getElementById("planVersion");
  const routerDecision = document.getElementById("routerDecision");
  const gateStatus = document.getElementById("gateStatus");
  const playbackEpoch = document.getElementById("playbackEpoch");
  const privateCandidate = "PRIVATE-SHADOW-CANDIDATE-MUST-NOT-RENDER";
  const privateTranscript = "PRIVATE-SHADOW-TRANSCRIPT-MUST-NOT-RENDER";

  dispatch(environment, "session.ready", {
    session_id: "session-ui-safe",
    provider_mode: "qwen",
    routing_mode: "shadow",
    audio_output: "qwen",
    shadow_control_mode: "dual_session_shadow",
    voice_session_status: "connected",
    shadow_control_session_status: "connected",
    output_mode: "real",
    playback_epoch: 0,
  });
  const initialAuthority = {
    task_id: taskId.textContent,
    plan_version: planVersion.textContent,
    router_decision: routerDecision.textContent,
    gate_status: gateStatus.textContent,
    playback_epoch: playbackEpoch.textContent,
  };
  dispatch(environment, "route.shadow.proposed", {
    provider_mode: "qwen",
    routing_mode: "shadow",
    safe_turn_ref: "turn-safe-ref-1",
    qwen_task_focus_hint: "NEW_TASK_CANDIDATE",
    qwen_route_hint: "SPAWN_SLOW_TASK",
    foreground_act: "ACK_SLOW",
    risk_class: "LOW",
    confidence: 0.875,
    reply_candidate_text: privateCandidate,
    transcript: privateTranscript,
    function_arguments: { raw: privateCandidate },
    provider_payload: { raw: privateTranscript },
    raw_audio: privateCandidate,
  });
  dispatch(environment, "route.shadow.validated", {
    schema_status: "valid",
    latency_ms: {
      asr_final_to_request: 12.5,
      function_call_first_delta: 31.25,
      function_call_done: 46.75,
    },
  });
  dispatch(environment, "route.shadow.compared", {
    local_router_decision: "SPAWN_SLOW_TASK",
    local_task_focus: "NEW_TASK_CANDIDATE",
    local_foreground_act: "ACK_SLOW",
    agreement: "yes",
    active_task_present: true,
    pending_confirmation_present: true,
    function_done_to_local_router_ms: 0.75,
    counters: {
      control_timeout: 1,
      error: 2,
      request_drop: 3,
      context_delete: 4,
      context_rebuild: 5,
    },
  });

  assert.equal(document.getElementById("shadowEvidenceMode").textContent, "real");
  assert.equal(document.getElementById("shadowProvider").textContent, "qwen");
  assert.equal(document.getElementById("shadowRouting").textContent, "shadow");
  assert.equal(document.getElementById("voiceSessionStatus").textContent, "connected");
  assert.equal(document.getElementById("shadowControlStatus").textContent, "connected");
  assert.equal(document.getElementById("shadowControlMode").textContent, "dual_session_shadow");
  assert.equal(document.getElementById("shadowAudioOutput").textContent, "qwen");
  assert.equal(document.getElementById("shadowSafeTurnRef").textContent, "turn-safe-ref-1");
  assert.equal(document.getElementById("shadowQwenFocus").textContent, "NEW_TASK_CANDIDATE");
  assert.equal(document.getElementById("shadowQwenRoute").textContent, "SPAWN_SLOW_TASK");
  assert.equal(document.getElementById("shadowForegroundAct").textContent, "ACK_SLOW");
  assert.equal(document.getElementById("shadowRisk").textContent, "LOW");
  assert.equal(document.getElementById("shadowConfidence").textContent, "0.875");
  assert.equal(document.getElementById("shadowSchema").textContent, "valid");
  assert.equal(document.getElementById("shadowLocalDecision").textContent, "SPAWN_SLOW_TASK");
  assert.equal(document.getElementById("shadowLocalFocus").textContent, "NEW_TASK_CANDIDATE");
  assert.equal(document.getElementById("shadowLocalForegroundAct").textContent, "ACK_SLOW");
  assert.equal(document.getElementById("shadowAgreement").textContent, "yes");
  assert.equal(document.getElementById("shadowActiveTaskContext").textContent, "present");
  assert.equal(document.getElementById("shadowPendingConfirmation").textContent, "present");
  assert.equal(document.getElementById("shadowAsrToRequest").textContent, "12.5 ms");
  assert.equal(document.getElementById("shadowRequestToFirstDelta").textContent, "31.3 ms");
  assert.equal(document.getElementById("shadowRequestToDone").textContent, "46.8 ms");
  assert.equal(document.getElementById("shadowDoneToLocal").textContent, "0.8 ms");
  assert.equal(document.getElementById("shadowTimeoutCount").textContent, "1");
  assert.equal(document.getElementById("shadowErrorCount").textContent, "2");
  assert.equal(document.getElementById("shadowDropCount").textContent, "3");
  assert.equal(document.getElementById("shadowContextDeleteCount").textContent, "4");
  assert.equal(document.getElementById("shadowContextRebuildCount").textContent, "5");

  assert.deepEqual({
    task_id: taskId.textContent,
    plan_version: planVersion.textContent,
    router_decision: routerDecision.textContent,
    gate_status: gateStatus.textContent,
    playback_epoch: playbackEpoch.textContent,
  }, initialAuthority);
  assert.equal(conversation.querySelectorAll(".message.assistant").length, 0);
  assert.equal(conversation.textContent.includes(privateCandidate), false);
  assert.equal(conversation.textContent.includes(privateTranscript), false);
  assert.equal(timeline.textContent.includes(privateCandidate), false);
  assert.equal(timeline.textContent.includes(privateTranscript), false);
  assert.equal(timeline.textContent.includes("function_arguments"), false);
  assert.equal(timeline.textContent.includes("provider_payload"), false);

  return {
    provider: document.getElementById("shadowProvider").textContent,
    routing: document.getElementById("shadowRouting").textContent,
    schema: document.getElementById("shadowSchema").textContent,
    agreement: document.getElementById("shadowAgreement").textContent,
    assistant_rows: conversation.querySelectorAll(".message.assistant").length,
  };
}

function shadowDegradedRedaction(appPath) {
  const environment = environmentFor(appPath);
  const document = environment.document;
  const conversation = document.getElementById("conversation");
  const timeline = document.getElementById("timeline");
  const credential = "Bearer PRIVATE-SHADOW-CREDENTIAL";
  const candidate = "PRIVATE-DEGRADED-CANDIDATE";

  dispatch(environment, "route.shadow.degraded", {
    output_mode: "real",
    shadow_control_session_status: "degraded",
    schema_status: "invalid",
    agreement: "not_available",
    control_timeout_count: 2,
    control_error_count: 4,
    shadow_drop_count: 6,
    authorization: credential,
    api_key: credential,
    transcript: candidate,
    reply_candidate_text: candidate,
    provider_payload: { authorization: credential },
    raw_audio: candidate,
  });

  assert.equal(document.getElementById("shadowEvidenceMode").textContent, "degraded");
  assert.equal(document.getElementById("shadowControlStatus").textContent, "degraded");
  assert.equal(document.getElementById("shadowSchema").textContent, "invalid");
  assert.equal(document.getElementById("shadowAgreement").textContent, "not_available");
  assert.equal(document.getElementById("shadowTimeoutCount").textContent, "2");
  assert.equal(document.getElementById("shadowErrorCount").textContent, "4");
  assert.equal(document.getElementById("shadowDropCount").textContent, "6");
  assert.equal(conversation.querySelectorAll(".message.assistant").length, 0);
  for (const marker of [credential, candidate, "authorization", "api_key", "provider_payload", "raw_audio"]) {
    assert.equal(timeline.textContent.toLowerCase().includes(marker.toLowerCase()), false);
    assert.equal(conversation.textContent.toLowerCase().includes(marker.toLowerCase()), false);
  }

  return {
    evidence_mode: document.getElementById("shadowEvidenceMode").textContent,
    control_status: document.getElementById("shadowControlStatus").textContent,
    schema: document.getElementById("shadowSchema").textContent,
    assistant_rows: conversation.querySelectorAll(".message.assistant").length,
  };
}

function enforcedControlZeroLeak(appPath) {
  const environment = environmentFor(appPath);
  const document = environment.document;
  const conversation = document.getElementById("conversation");
  const timeline = document.getElementById("timeline");
  const privateCandidate = "PRIVATE-ENFORCED-CANDIDATE-MUST-NOT-RENDER";
  const privateTranscript = "PRIVATE-VOICE-TRANSCRIPT-MUST-NOT-RENDER";
  const credential = "Bearer PRIVATE-ENFORCED-CREDENTIAL";

  dispatch(environment, "session.ready", {
    session_id: "session-enforced-safe",
    provider_mode: "qwen",
    routing_mode: "enforced",
    audio_output: "none",
    output: "text_only",
    slow_runtime_mode: "mock",
    control_topology: "dual_session_enforced_control",
    experimental: true,
    qwen_proposal_authority: "non_authoritative",
    local_router_authority: "authoritative",
    provider_native_audio_disabled: true,
    voice_session_status: "connected",
    shadow_control_session_status: "connected",
    output_mode: "mock",
    playback_epoch: 3,
  });

  assert.equal(document.getElementById("enforcedPanel").dataset.active, "true");
  assert.equal(document.getElementById("enforcedProvider").textContent, "qwen");
  assert.equal(document.getElementById("enforcedRouting").textContent, "enforced");
  assert.equal(document.getElementById("enforcedOutput").textContent, "text_only");
  assert.equal(document.getElementById("enforcedAudioOutput").textContent, "none");
  assert.equal(document.getElementById("enforcedSlowRuntime").textContent, "mock");
  assert.equal(document.getElementById("enforcedTopology").textContent, "dual_session_enforced_control");
  assert.equal(document.getElementById("enforcedExperimental").textContent, "yes");
  assert.equal(document.getElementById("enforcedProposalAuthority").textContent, "non_authoritative");
  assert.equal(document.getElementById("enforcedRouterAuthority").textContent, "authoritative");
  assert.equal(document.getElementById("enforcedProviderAudio").textContent, "disabled");

  dispatch(environment, "control.state", {
    safe_turn_ref: "turn-safe-enforced-1",
    qwen_task_focus_hint: "FOREGROUND_CHAT",
    qwen_route_hint: "FAST_ONLY",
    foreground_act: "ANSWER",
    risk_class: "LOW",
    confidence: 0.95,
    schema_status: "valid",
    local_router_decision: "FAST_ONLY",
    local_task_focus: "FOREGROUND_CHAT",
    local_foreground_act: "ANSWER",
    gate_status: "passed",
    output_mode: "mock",
    context_tainted: false,
    voice_context_tainted: false,
    voice_cancel_count: 1,
    voice_cancel_terminal_count: 1,
    voice_context_delete_count: 1,
    assistant_text_suppression_count: 3,
    audio_suppression_count: 4,
    binary_playback_frame_count: 0,
    reply_candidate_text: privateCandidate,
    transcript: privateTranscript,
    function_arguments: { candidate: privateCandidate },
    provider_payload: { transcript: privateTranscript },
    authorization: credential,
    raw_audio: privateCandidate,
  });
  dispatch(environment, "dispatch.result", {
    actual_dispatch: "fast_text",
    safe_turn_ref: "turn-safe-enforced-1",
    stale_status: "current",
    output_mode: "mock",
    task_id: "task-safe-ref",
    plan_version: 2,
    reply_candidate_text: privateCandidate,
    transcript: privateTranscript,
    authorization: credential,
  });

  // Voice text and any uncommitted/incorrectly attributed text never enter QA.
  for (const fields of [
    { response_id: "voice-1", text: privateTranscript, source: "qwen_voice_session" },
    { response_id: "candidate-1", text: privateCandidate, source: "control_candidate" },
    { response_id: "candidate-2", text: privateCandidate, source: "provider_candidate", server_committed: true, commit_ref: "commit-safe-2" },
    { response_id: "candidate-3", text: privateCandidate, source: "control_candidate", server_committed: true },
  ]) dispatch(environment, "transcript.assistant.done", fields);
  assert.equal(conversation.querySelectorAll(".message.assistant").length, 0);

  dispatch(environment, "transcript.assistant.done", {
    response_id: "candidate-committed",
    text: "Bounded committed control answer.",
    source: "control_candidate",
    server_committed: true,
    commit_ref: "commit-safe-fast-1",
  });
  dispatch(environment, "transcript.assistant.done", {
    response_id: "template-committed",
    text: "Controlled clarification.",
    source: "controlled_template",
    server_committed: true,
    committed_event_id: "commit-safe-clarify-1",
  });
  assert.equal(conversation.querySelectorAll(".message.assistant").length, 2);
  assert.match(conversation.textContent, /Bounded committed control answer/);
  assert.match(conversation.textContent, /Controlled clarification/);

  // Even a structurally valid binary frame is blocked before the player path.
  vm.runInContext("handleSocketMessage({ data: new ArrayBuffer(32) })", environment.context);
  assert.equal(document.getElementById("enforcedBinaryPlaybackCount").textContent, "0");
  assert.equal(document.getElementById("enforcedAudioSuppressionCount").textContent, "5");
  assert.equal(document.getElementById("enforcedActualDispatch").textContent, "fast_text");

  for (const marker of [
    privateCandidate,
    privateTranscript,
    credential,
    "function_arguments",
    "provider_payload",
    "raw_audio",
    "authorization",
  ]) {
    assert.equal(timeline.textContent.toLowerCase().includes(marker.toLowerCase()), false);
    assert.equal(conversation.textContent.toLowerCase().includes(marker.toLowerCase()), false);
  }

  return {
    topology: document.getElementById("enforcedTopology").textContent,
    dispatch: document.getElementById("enforcedActualDispatch").textContent,
    assistant_rows: conversation.querySelectorAll(".message.assistant").length,
    audio_suppressed: document.getElementById("enforcedAudioSuppressionCount").textContent,
    binary_played: document.getElementById("enforcedBinaryPlaybackCount").textContent,
  };
}

function main() {
  const scenario = process.argv[2];
  const appPath = process.argv[3];
  assert.ok(scenario && appPath, "usage: app_harness.js scenario app.js");
  const scenarios = {
    bounded_timeline: () => boundedTimeline(appPath),
    enforced_control_zero_leak: () => enforcedControlZeroLeak(appPath),
    quarantine_visibility: () => quarantineVisibility(appPath),
    shadow_degraded_redaction: () => shadowDegradedRedaction(appPath),
    shadow_projection_isolation: () => shadowProjectionIsolation(appPath),
    task_state_authority: () => taskStateAuthority(appPath),
  };
  assert.ok(Object.hasOwn(scenarios, scenario), `unknown scenario: ${scenario}`);
  const result = scenarios[scenario]();
  process.stdout.write(JSON.stringify({ status: "passed", scenario, ...result }));
}

main();
