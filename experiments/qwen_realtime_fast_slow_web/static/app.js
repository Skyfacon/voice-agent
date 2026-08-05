const PROTOCOL_VERSION = 2;
const OUTPUT_MAGIC = [0x51, 0x46, 0x53, 0x32]; // QFS2
const OUTPUT_HEADER_BYTES = 8;
const INPUT_FRAME_BYTES = 3_200;
const MAX_CONTROL_FRAME_BYTES = 16_384;
const MAX_OUTPUT_FRAME_BYTES = 256 * 1024;
const MAX_TRANSCRIPT_CHARS = 6_000;
const MAX_CONVERSATION_CHARS = 32_000;
const MAX_CONVERSATION_ROWS = 48;
const MAX_TIMELINE_ROWS = 100;
const MIC_QUEUE_LIMIT = 6;
const OUTPUT_DISPATCH_QUEUE_LIMIT = 16;
const WS_HIGH_WATER_BYTES = 64 * 1024;

const TIMELINE_KEYS = new Set([
  "scenario",
  "provider_mode",
  "routing_mode",
  "voice_session_status",
  "shadow_control_session_status",
  "shadow_control_status",
  "shadow_control_mode",
  "control_session_status",
  "control_topology",
  "slow_runtime_mode",
  "experimental",
  "qwen_proposal_authority",
  "local_router_authority",
  "provider_native_audio_disabled",
  "audio_output",
  "safe_turn_ref",
  "route_hint",
  "task_focus_hint",
  "qwen_route_hint",
  "qwen_task_focus_hint",
  "router_decision",
  "local_router_decision",
  "task_focus",
  "local_task_focus",
  "local_foreground_act",
  "foreground_act",
  "risk_class",
  "confidence",
  "schema_status",
  "schema_valid",
  "actual_dispatch",
  "stale_status",
  "agreement",
  "route_agreement",
  "task_focus_agreement",
  "foreground_act_agreement",
  "proposal_available",
  "asr_to_shadow_request_ms",
  "shadow_request_to_first_delta_ms",
  "shadow_request_to_done_ms",
  "function_done_to_local_router_ms",
  "asr_to_control_request_ms",
  "control_request_to_first_delta_ms",
  "control_request_to_done_ms",
  "router_gate_latency_ms",
  "control_cancel_count",
  "control_delete_count",
  "control_rebuild_count",
  "control_drop_count",
  "control_context_tainted",
  "voice_cancel_count",
  "voice_cancel_terminal_count",
  "cancel_terminal_outcome",
  "voice_cancel_terminal_outcome",
  "voice_cancel_terminal_timeout_count",
  "voice_unsafe_cancel_terminal_count",
  "voice_completed_after_cancel_count",
  "voice_failed_after_cancel_count",
  "voice_context_delete_count",
  "voice_context_rebuild_count",
  "voice_rebuild_pcm_drop_count",
  "voice_audio_send_failure_count",
  "voice_rebuild_coalesced_count",
  "voice_context_tainted",
  "assistant_text_suppression_count",
  "audio_suppression_count",
  "binary_playback_frame_count",
  "control_timeout_count",
  "control_error_count",
  "context_delete_count",
  "context_rebuild_count",
  "shadow_drop_count",
  "context_tainted",
  "degraded_code",
  "active_task_present",
  "pending_confirmation_present",
  "isolated_event_count",
  "gate_status",
  "failure_reason",
  "task_id",
  "lifecycle",
  "plan_version",
  "playback_epoch",
  "dropped_input_frames",
  "dropped_output_frames",
  "discarded_late_audio_frames",
  "clear_latency_ms",
  "output_mode",
  "degraded",
]);

const PROVIDER_MODES = new Set(["fake", "qwen"]);
const ROUTING_MODES = new Set(["shadow", "enforced"]);
const SESSION_STATUSES = new Set(["connected", "connecting", "ready", "disconnected", "degraded", "disabled", "not_available"]);
const SHADOW_CONTROL_MODES = new Set(["dual_session", "dual_session_shadow", "dual_session_enforced_control", "none", "not_available"]);
const CONTROL_TOPOLOGIES = new Set(["dual_session_enforced_control", "dual_session_shadow", "dual_session", "none", "not_available"]);
const AUDIO_OUTPUT_MODES = new Set(["qwen", "fake_pcm", "none", "not_available"]);
const FOREGROUND_OUTPUT_MODES = new Set(["text_only", "fake_pcm", "qwen", "none", "not_available"]);
const EVIDENCE_MODES = new Set(["real", "mock", "fake", "fallback", "degraded", "not_available"]);
const SLOW_RUNTIME_MODES = new Set(["mock", "not_available"]);
const PROPOSAL_AUTHORITIES = new Set(["non_authoritative", "none", "not_available"]);
const ROUTER_AUTHORITIES = new Set(["authoritative", "local_authoritative", "not_available"]);
const DISPATCH_STATUSES = new Set(["fast_text", "mock_slow_spawn", "user_patch", "ignore", "clarify", "degraded", "not_available"]);
const STALE_STATUSES = new Set([
  "current",
  "stale",
  "superseded",
  "discarded",
  "rebased_current_state",
  "failed_closed",
  "not_available",
]);
const CANCEL_TERMINAL_OUTCOMES = new Set([
  "cancelled_on_time",
  "cancelled_after_watchdog",
  "completed_after_cancel",
  "failed_after_cancel",
  "missing_terminal",
]);
const TASK_FOCUS_HINTS = new Set([
  "FOREGROUND_CHAT",
  "NEW_TASK_CANDIDATE",
  "ACTIVE_TASK_PATCH",
  "CANCEL_OR_PAUSE_CANDIDATE",
  "NON_ASSISTANT",
  "AMBIGUOUS",
  "not_available",
]);
const ROUTE_HINTS = new Set(["FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE", "not_available"]);
const FOREGROUND_ACTS = new Set(["ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY", "not_available"]);
const RISK_CLASSES = new Set(["LOW", "MEDIUM", "HIGH", "not_available"]);
const SCHEMA_STATUSES = new Set(["valid", "invalid", "not_available"]);
const AGREEMENT_STATUSES = new Set(["yes", "no", "not_available"]);

const SENSITIVE_MARKERS = [
  "authorization",
  "bearer",
  "cookie",
  "credential",
  "api_key",
  "apikey",
  "secret",
  "session_key",
  "token",
  "http://",
  "https://",
  "file://",
  "/users/",
  "\\users\\",
  ".env",
];

const ACTIVITY_NAMES = new Map([
  ["idle", "Idle"],
  ["connected", "Idle"],
  ["ready", "Idle"],
  ["listening", "Listening"],
  ["speech_started", "Listening"],
  ["routing", "Routing"],
  ["responding", "Responding"],
  ["slowtask", "SlowTask"],
  ["slow_task", "SlowTask"],
  ["interrupted", "Interrupted"],
  ["error", "Error"],
]);

const byId = (id) => document.getElementById(id);

const elements = {
  connectionBadge: byId("connectionBadge"),
  modeBadge: byId("modeBadge"),
  healthBadge: byId("healthBadge"),
  activityBadge: byId("activityBadge"),
  connectBtn: byId("connectBtn"),
  disconnectBtn: byId("disconnectBtn"),
  startMicBtn: byId("startMicBtn"),
  stopMicBtn: byId("stopMicBtn"),
  interruptBtn: byId("interruptBtn"),
  micStatus: byId("micStatus"),
  inputLevel: byId("inputLevel"),
  inputLevelText: byId("inputLevelText"),
  inputDropCount: byId("inputDropCount"),
  outputDropCount: byId("outputDropCount"),
  lateAudioDropCount: byId("lateAudioDropCount"),
  playbackEpoch: byId("playbackEpoch"),
  playbackBuffer: byId("playbackBuffer"),
  clearLatency: byId("clearLatency"),
  scenarioControls: byId("scenarioControls"),
  conversation: byId("conversation"),
  clearConversationBtn: byId("clearConversationBtn"),
  proposalRoute: byId("proposalRoute"),
  proposalFocus: byId("proposalFocus"),
  foregroundAct: byId("foregroundAct"),
  proposalRisk: byId("proposalRisk"),
  proposalConfidence: byId("proposalConfidence"),
  routerDecision: byId("routerDecision"),
  routerFocus: byId("routerFocus"),
  gateStatus: byId("gateStatus"),
  gateReason: byId("gateReason"),
  taskId: byId("taskId"),
  taskLifecycle: byId("taskLifecycle"),
  planVersion: byId("planVersion"),
  patchStatus: byId("patchStatus"),
  shadowEvidenceMode: byId("shadowEvidenceMode"),
  shadowProvider: byId("shadowProvider"),
  shadowRouting: byId("shadowRouting"),
  voiceSessionStatus: byId("voiceSessionStatus"),
  shadowControlStatus: byId("shadowControlStatus"),
  shadowControlMode: byId("shadowControlMode"),
  shadowAudioOutput: byId("shadowAudioOutput"),
  shadowSafeTurnRef: byId("shadowSafeTurnRef"),
  shadowActiveTaskContext: byId("shadowActiveTaskContext"),
  shadowPendingConfirmation: byId("shadowPendingConfirmation"),
  shadowQwenFocus: byId("shadowQwenFocus"),
  shadowQwenRoute: byId("shadowQwenRoute"),
  shadowForegroundAct: byId("shadowForegroundAct"),
  shadowRisk: byId("shadowRisk"),
  shadowConfidence: byId("shadowConfidence"),
  shadowSchema: byId("shadowSchema"),
  shadowLocalDecision: byId("shadowLocalDecision"),
  shadowLocalFocus: byId("shadowLocalFocus"),
  shadowLocalForegroundAct: byId("shadowLocalForegroundAct"),
  shadowAgreement: byId("shadowAgreement"),
  shadowAsrToRequest: byId("shadowAsrToRequest"),
  shadowRequestToFirstDelta: byId("shadowRequestToFirstDelta"),
  shadowRequestToDone: byId("shadowRequestToDone"),
  shadowDoneToLocal: byId("shadowDoneToLocal"),
  shadowTimeoutCount: byId("shadowTimeoutCount"),
  shadowErrorCount: byId("shadowErrorCount"),
  shadowDropCount: byId("shadowDropCount"),
  shadowContextDeleteCount: byId("shadowContextDeleteCount"),
  shadowContextRebuildCount: byId("shadowContextRebuildCount"),
  enforcedPanel: byId("enforcedPanel"),
  enforcedStatus: byId("enforcedStatus"),
  enforcedProvider: byId("enforcedProvider"),
  enforcedRouting: byId("enforcedRouting"),
  enforcedOutput: byId("enforcedOutput"),
  enforcedAudioOutput: byId("enforcedAudioOutput"),
  enforcedSlowRuntime: byId("enforcedSlowRuntime"),
  enforcedTopology: byId("enforcedTopology"),
  enforcedExperimental: byId("enforcedExperimental"),
  enforcedVoiceStatus: byId("enforcedVoiceStatus"),
  enforcedControlStatus: byId("enforcedControlStatus"),
  enforcedSafeTurnRef: byId("enforcedSafeTurnRef"),
  enforcedProposalAuthority: byId("enforcedProposalAuthority"),
  enforcedRouterAuthority: byId("enforcedRouterAuthority"),
  enforcedProviderAudio: byId("enforcedProviderAudio"),
  enforcedQwenFocus: byId("enforcedQwenFocus"),
  enforcedQwenRoute: byId("enforcedQwenRoute"),
  enforcedForegroundAct: byId("enforcedForegroundAct"),
  enforcedRisk: byId("enforcedRisk"),
  enforcedConfidence: byId("enforcedConfidence"),
  enforcedSchema: byId("enforcedSchema"),
  enforcedEvidenceMode: byId("enforcedEvidenceMode"),
  enforcedLocalDecision: byId("enforcedLocalDecision"),
  enforcedLocalFocus: byId("enforcedLocalFocus"),
  enforcedLocalForegroundAct: byId("enforcedLocalForegroundAct"),
  enforcedGateStatus: byId("enforcedGateStatus"),
  enforcedGateReason: byId("enforcedGateReason"),
  enforcedActualDispatch: byId("enforcedActualDispatch"),
  enforcedTaskRef: byId("enforcedTaskRef"),
  enforcedPlanVersion: byId("enforcedPlanVersion"),
  enforcedStaleStatus: byId("enforcedStaleStatus"),
  enforcedDispatchMode: byId("enforcedDispatchMode"),
  enforcedAsrToControl: byId("enforcedAsrToControl"),
  enforcedRequestToFirstDelta: byId("enforcedRequestToFirstDelta"),
  enforcedRequestToDone: byId("enforcedRequestToDone"),
  enforcedRouterGateLatency: byId("enforcedRouterGateLatency"),
  enforcedControlCancelCount: byId("enforcedControlCancelCount"),
  enforcedControlDeleteCount: byId("enforcedControlDeleteCount"),
  enforcedControlRebuildCount: byId("enforcedControlRebuildCount"),
  enforcedControlDropCount: byId("enforcedControlDropCount"),
  enforcedControlTainted: byId("enforcedControlTainted"),
  enforcedVoiceCancelCount: byId("enforcedVoiceCancelCount"),
  enforcedVoiceCancelTerminalCount: byId("enforcedVoiceCancelTerminalCount"),
  enforcedVoiceDeleteCount: byId("enforcedVoiceDeleteCount"),
  enforcedVoiceRebuildCount: byId("enforcedVoiceRebuildCount"),
  enforcedVoiceTainted: byId("enforcedVoiceTainted"),
  enforcedTextSuppressionCount: byId("enforcedTextSuppressionCount"),
  enforcedAudioSuppressionCount: byId("enforcedAudioSuppressionCount"),
  enforcedBinaryPlaybackCount: byId("enforcedBinaryPlaybackCount"),
  timeline: byId("timeline"),
  clearTimelineBtn: byId("clearTimelineBtn"),
};

const state = {
  socket: null,
  socketGeneration: 0,
  sessionReady: false,
  manualDisconnect: false,
  providerMode: "fake",
  routingMode: "enforced",
  audioOutput: "fake_pcm",
  providerAudioDisabled: false,
  outputMode: "fake",
  degraded: false,
  mic: null,
  micFrames: [],
  micFlushTimer: null,
  droppedInputFrames: 0,
  player: null,
  playerPromise: null,
  pendingAudioFrames: [],
  audioDrainActive: false,
  audioDispatchGeneration: 0,
  playbackEpoch: 0,
  droppedOutputFrames: 0,
  discardedLateAudioFrames: 0,
  shadowCounters: {
    control_timeout_count: 0,
    control_error_count: 0,
    shadow_drop_count: 0,
    context_delete_count: 0,
    context_rebuild_count: 0,
  },
  enforcedCounters: {
    control_cancel_count: 0,
    control_delete_count: 0,
    control_rebuild_count: 0,
    control_drop_count: 0,
    voice_cancel_count: 0,
    voice_cancel_terminal_count: 0,
    voice_context_delete_count: 0,
    voice_context_rebuild_count: 0,
    assistant_text_suppression_count: 0,
    audio_suppression_count: 0,
    binary_playback_frame_count: 0,
  },
  clearSequence: 0,
  clearRequests: new Map(),
  conversationRows: [],
  conversationSequence: 0,
};

function socketIsOpen() {
  return state.socket?.readyState === WebSocket.OPEN;
}

function finiteNumber(value, minimum = 0, maximum = Number.MAX_SAFE_INTEGER) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.min(maximum, Math.max(minimum, number));
}

function strictFiniteNumber(value, minimum = 0, maximum = Number.MAX_SAFE_INTEGER) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value >= minimum && value <= maximum ? value : null;
}

function boundedText(value, limit = MAX_TRANSCRIPT_CHARS) {
  if (typeof value !== "string") return "";
  const normalized = value.replace(/\u0000/g, "");
  return normalized.length <= limit ? normalized : normalized.slice(0, limit);
}

function safeToken(value, fallback = "—", limit = 128) {
  if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") {
    return fallback;
  }
  const normalized = String(value).replace(/[\u0000-\u001f\u007f]/g, "").trim();
  if (!normalized) return fallback;
  return normalized.slice(0, limit);
}

function safeCode(value, fallback = "internal_error") {
  if (typeof value !== "string") return fallback;
  const normalized = value.trim().toLowerCase();
  return /^[a-z0-9][a-z0-9_.:-]{0,95}$/.test(normalized)
    && !SENSITIVE_MARKERS.some((marker) => normalized.includes(marker))
    ? normalized
    : fallback;
}

function safeEnum(value, allowed, fallback = "not_available") {
  if (typeof value !== "string") return fallback;
  const normalized = value.trim();
  return allowed.has(normalized) ? normalized : fallback;
}

function safeOpaqueRef(value, fallback = "not_available") {
  if (typeof value !== "string") return fallback;
  const normalized = value.trim();
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}$/.test(normalized)) return fallback;
  return SENSITIVE_MARKERS.some((marker) => normalized.toLowerCase().includes(marker)) ? fallback : normalized;
}

function formatLatency(value) {
  const latency = strictFiniteNumber(value, 0, 600_000);
  return latency === null ? "not_available" : `${latency.toFixed(1)} ms`;
}

function setTone(element, tone) {
  if (!tone) element.removeAttribute("data-tone");
  else element.setAttribute("data-tone", tone);
}

function sessionTone(status) {
  if (["connected", "ready"].includes(status)) return "healthy";
  if (status === "degraded") return "degraded";
  if (status === "disconnected") return "error";
  return "";
}

function setShadowSessionStatus(element, value) {
  const status = safeEnum(value, SESSION_STATUSES);
  element.textContent = status;
  setTone(element, sessionTone(status));
}

function setShadowEvidenceMode(value) {
  const mode = safeEnum(value, EVIDENCE_MODES);
  elements.shadowEvidenceMode.textContent = mode;
  elements.shadowEvidenceMode.className = `badge ${mode === "degraded" ? "degraded" : mode === "real" ? "healthy" : mode === "mock" || mode === "fake" ? "fake" : "neutral"}`;
}

function setShadowPresence(element, value, complete) {
  if (value === undefined && !complete) return;
  const label = typeof value === "boolean" ? (value ? "present" : "absent") : "not_available";
  element.textContent = label;
  setTone(element, value === true ? "degraded" : value === false ? "healthy" : "");
}

function firstValue(source, keys, fallback = undefined) {
  for (const key of keys) {
    if (source && source[key] !== undefined && source[key] !== null) return source[key];
  }
  return fallback;
}

function qwenEnforcedMode() {
  return state.providerMode === "qwen" && state.routingMode === "enforced";
}

function setBooleanState(element, value, { trueLabel = "yes", falseLabel = "no" } = {}) {
  if (typeof value !== "boolean") {
    element.textContent = "not_available";
    setTone(element, "");
    return;
  }
  element.textContent = value ? trueLabel : falseLabel;
  setTone(element, value ? "healthy" : "degraded");
}

function setTaintState(element, value, complete = false) {
  if (value === undefined && !complete) return;
  if (typeof value !== "boolean") {
    element.textContent = "not_available";
    setTone(element, "");
    return;
  }
  element.textContent = value ? "tainted" : "clean";
  setTone(element, value ? "error" : "healthy");
}

function setConnection(text, variant = "neutral") {
  elements.connectionBadge.textContent = text;
  elements.connectionBadge.className = `badge ${variant}`;
}

function setActivity(rawActivity) {
  const key = safeToken(rawActivity, "idle").toLowerCase();
  const label = ACTIVITY_NAMES.get(key) || "Idle";
  elements.activityBadge.textContent = label;
  elements.activityBadge.className = `activity ${label.toLowerCase()}`;
}

function setOutputMode(rawMode, degraded = false) {
  const mode = safeCode(rawMode, "fake");
  state.outputMode = mode;
  state.degraded = state.degraded || degraded || mode === "degraded" || mode === "fallback";
  elements.modeBadge.textContent = mode === "fake" || mode === "mock" ? "Fake" : mode;
  const variant = state.degraded ? "degraded" : ["fake", "mock"].includes(mode) ? "fake" : "healthy";
  elements.modeBadge.className = `badge ${variant}`;
  elements.healthBadge.textContent = state.degraded ? "degraded" : "healthy";
  elements.healthBadge.className = `badge ${state.degraded ? "degraded" : "healthy"}`;
}

function markDegraded(reason = "degraded") {
  state.degraded = true;
  setOutputMode(state.outputMode, true);
  elements.healthBadge.textContent = safeCode(reason, "degraded");
}

function refreshButtons() {
  const connecting = state.socket?.readyState === WebSocket.CONNECTING;
  const open = socketIsOpen();
  elements.connectBtn.disabled = connecting || open;
  elements.disconnectBtn.disabled = !(connecting || open);
  elements.startMicBtn.disabled = !open || !state.sessionReady || Boolean(state.mic);
  elements.stopMicBtn.disabled = !state.mic;
  elements.interruptBtn.disabled = !open || !state.sessionReady;
  const fakeEnabled = open && state.sessionReady && state.providerMode === "fake";
  for (const button of elements.scenarioControls.querySelectorAll("button[data-scenario]")) {
    button.disabled = !fakeEnabled;
  }
}

function sanitizedTimelineMetadata(source) {
  const candidate = source && typeof source.metadata === "object" && source.metadata !== null
    ? source.metadata
    : source;
  const result = {};
  if (!candidate || typeof candidate !== "object") return result;
  for (const key of TIMELINE_KEYS) {
    const value = candidate[key];
    const sanitized = sanitizeTimelineValue(key, value);
    if (sanitized !== undefined) result[key] = sanitized;
  }
  const latency = candidate.latency_ms;
  if (latency && typeof latency === "object") {
    const aliases = {
      asr_to_shadow_request_ms: "asr_final_to_request",
      shadow_request_to_first_delta_ms: "function_call_first_delta",
      shadow_request_to_done_ms: "function_call_done",
      function_done_to_local_router_ms: "done_to_local_router",
    };
    for (const [target, alias] of Object.entries(aliases)) {
      if (result[target] !== undefined) continue;
      const sanitized = sanitizeTimelineValue(target, latency[alias]);
      if (sanitized !== undefined) result[target] = sanitized;
    }
  }
  const enforcedLatency = candidate.latencies;
  if (enforcedLatency && typeof enforcedLatency === "object") {
    const aliases = {
      asr_to_control_request_ms: "asr_final_to_request",
      control_request_to_first_delta_ms: "function_call_first_delta",
      control_request_to_done_ms: "function_call_done",
      router_gate_latency_ms: "router_gate",
    };
    for (const [target, alias] of Object.entries(aliases)) {
      if (result[target] !== undefined) continue;
      const sanitized = sanitizeTimelineValue(target, enforcedLatency[alias]);
      if (sanitized !== undefined) result[target] = sanitized;
    }
  }
  const counters = candidate.counters;
  if (counters && typeof counters === "object") {
    const aliases = {
      control_timeout_count: "control_timeout",
      control_error_count: "error",
      shadow_drop_count: "request_drop",
      context_delete_count: "context_delete",
      context_rebuild_count: "context_rebuild",
      control_cancel_count: "control_cancel",
      control_delete_count: "control_delete",
      control_rebuild_count: "control_rebuild",
      control_drop_count: "control_drop",
      voice_cancel_count: "voice_cancel",
      voice_cancel_terminal_count: "voice_cancel_terminal",
      voice_cancel_terminal_timeout_count: "cancel_terminal_timeout_count",
      voice_unsafe_cancel_terminal_count: "unsafe_cancel_terminal_count",
      voice_completed_after_cancel_count: "completed_after_cancel_count",
      voice_failed_after_cancel_count: "failed_after_cancel_count",
      voice_context_delete_count: "voice_context_delete",
      voice_context_rebuild_count: "voice_context_rebuild",
      voice_rebuild_pcm_drop_count: "rebuild_audio_drop_count",
      voice_audio_send_failure_count: "audio_send_failure_count",
      voice_rebuild_coalesced_count: "rebuild_coalesced_count",
      assistant_text_suppression_count: "assistant_text_suppression",
      audio_suppression_count: "audio_suppression",
      binary_playback_frame_count: "binary_playback_frame",
    };
    for (const [target, alias] of Object.entries(aliases)) {
      if (result[target] !== undefined) continue;
      const sanitized = sanitizeTimelineValue(target, counters[alias]);
      if (sanitized !== undefined) result[target] = sanitized;
    }
  }
  return result;
}

function sanitizeTimelineValue(key, value) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) {
    const maximum = key === "confidence" ? 1 : 1_000_000_000;
    return value >= 0 && value <= maximum ? value : undefined;
  }
  if (typeof value !== "string") return undefined;
  const enumFields = {
    provider_mode: PROVIDER_MODES,
    routing_mode: ROUTING_MODES,
    voice_session_status: SESSION_STATUSES,
    shadow_control_session_status: SESSION_STATUSES,
    shadow_control_status: SESSION_STATUSES,
    shadow_control_mode: SHADOW_CONTROL_MODES,
    control_topology: CONTROL_TOPOLOGIES,
    slow_runtime_mode: SLOW_RUNTIME_MODES,
    qwen_proposal_authority: PROPOSAL_AUTHORITIES,
    local_router_authority: ROUTER_AUTHORITIES,
    audio_output: AUDIO_OUTPUT_MODES,
    route_hint: ROUTE_HINTS,
    qwen_route_hint: ROUTE_HINTS,
    router_decision: ROUTE_HINTS,
    local_router_decision: ROUTE_HINTS,
    task_focus_hint: TASK_FOCUS_HINTS,
    qwen_task_focus_hint: TASK_FOCUS_HINTS,
    task_focus: TASK_FOCUS_HINTS,
    local_task_focus: TASK_FOCUS_HINTS,
    local_foreground_act: FOREGROUND_ACTS,
    foreground_act: FOREGROUND_ACTS,
    risk_class: RISK_CLASSES,
    schema_status: SCHEMA_STATUSES,
    agreement: AGREEMENT_STATUSES,
    route_agreement: AGREEMENT_STATUSES,
    task_focus_agreement: AGREEMENT_STATUSES,
    foreground_act_agreement: AGREEMENT_STATUSES,
    actual_dispatch: DISPATCH_STATUSES,
    stale_status: STALE_STATUSES,
    cancel_terminal_outcome: CANCEL_TERMINAL_OUTCOMES,
    voice_cancel_terminal_outcome: CANCEL_TERMINAL_OUTCOMES,
    output_mode: EVIDENCE_MODES,
  };
  if (enumFields[key]) {
    const normalized = safeEnum(value, enumFields[key], "");
    return normalized || undefined;
  }
  if (["safe_turn_ref", "task_id"].includes(key)) {
    const reference = safeOpaqueRef(value, "");
    return reference || undefined;
  }
  const normalized = safeCode(value, "");
  return normalized || undefined;
}

function appendTimeline(rawType, metadata = {}) {
  const type = safeCode(rawType, "protocol.event");
  const placeholder = elements.timeline.querySelector(".placeholder");
  if (placeholder) placeholder.remove();

  const item = document.createElement("li");
  const time = document.createElement("time");
  const name = document.createElement("span");
  const detail = document.createElement("code");
  time.textContent = new Date().toLocaleTimeString([], { hour12: false });
  name.className = "event-type";
  name.textContent = type;
  detail.textContent = JSON.stringify(sanitizedTimelineMetadata(metadata));
  item.append(time, name, detail);
  elements.timeline.append(item);
  while (elements.timeline.children.length > MAX_TIMELINE_ROWS) elements.timeline.firstElementChild?.remove();
  elements.timeline.scrollTop = elements.timeline.scrollHeight;
}

function clearTimeline() {
  elements.timeline.replaceChildren();
  const placeholder = document.createElement("li");
  placeholder.className = "placeholder";
  placeholder.textContent = "等待事件";
  elements.timeline.append(placeholder);
}

function resetShadowUi() {
  for (const key of Object.keys(state.shadowCounters)) state.shadowCounters[key] = 0;
  setShadowEvidenceMode("not_available");
  elements.shadowProvider.textContent = "not_available";
  elements.shadowRouting.textContent = "not_available";
  setShadowSessionStatus(elements.voiceSessionStatus, "not_available");
  setShadowSessionStatus(elements.shadowControlStatus, "not_available");
  elements.shadowControlMode.textContent = "not_available";
  elements.shadowAudioOutput.textContent = "not_available";
  elements.shadowSafeTurnRef.textContent = "not_available";
  setShadowPresence(elements.shadowActiveTaskContext, undefined, true);
  setShadowPresence(elements.shadowPendingConfirmation, undefined, true);
  elements.shadowQwenFocus.textContent = "not_available";
  elements.shadowQwenRoute.textContent = "not_available";
  elements.shadowForegroundAct.textContent = "not_available";
  elements.shadowRisk.textContent = "not_available";
  elements.shadowConfidence.textContent = "not_available";
  elements.shadowSchema.textContent = "not_available";
  elements.shadowLocalDecision.textContent = "not_available";
  elements.shadowLocalFocus.textContent = "not_available";
  elements.shadowLocalForegroundAct.textContent = "not_available";
  elements.shadowAgreement.textContent = "not_available";
  elements.shadowAsrToRequest.textContent = "not_available";
  elements.shadowRequestToFirstDelta.textContent = "not_available";
  elements.shadowRequestToDone.textContent = "not_available";
  elements.shadowDoneToLocal.textContent = "not_available";
  elements.shadowTimeoutCount.textContent = "0";
  elements.shadowErrorCount.textContent = "0";
  elements.shadowDropCount.textContent = "0";
  elements.shadowContextDeleteCount.textContent = "0";
  elements.shadowContextRebuildCount.textContent = "0";
  for (const element of [
    elements.shadowSchema,
    elements.shadowAgreement,
    elements.shadowQwenFocus,
    elements.shadowQwenRoute,
    elements.shadowForegroundAct,
    elements.shadowRisk,
    elements.shadowLocalDecision,
    elements.shadowLocalFocus,
    elements.shadowLocalForegroundAct,
  ]) setTone(element, "");
}

function resetEnforcedUi() {
  for (const key of Object.keys(state.enforcedCounters)) state.enforcedCounters[key] = 0;
  elements.enforcedPanel.dataset.active = "false";
  elements.enforcedStatus.textContent = "inactive";
  elements.enforcedStatus.className = "badge neutral";
  for (const element of [
    elements.enforcedProvider,
    elements.enforcedRouting,
    elements.enforcedOutput,
    elements.enforcedAudioOutput,
    elements.enforcedSlowRuntime,
    elements.enforcedTopology,
    elements.enforcedExperimental,
    elements.enforcedVoiceStatus,
    elements.enforcedControlStatus,
    elements.enforcedSafeTurnRef,
    elements.enforcedProposalAuthority,
    elements.enforcedRouterAuthority,
    elements.enforcedProviderAudio,
    elements.enforcedQwenFocus,
    elements.enforcedQwenRoute,
    elements.enforcedForegroundAct,
    elements.enforcedRisk,
    elements.enforcedConfidence,
    elements.enforcedSchema,
    elements.enforcedEvidenceMode,
    elements.enforcedLocalDecision,
    elements.enforcedLocalFocus,
    elements.enforcedLocalForegroundAct,
    elements.enforcedGateStatus,
    elements.enforcedGateReason,
    elements.enforcedActualDispatch,
    elements.enforcedTaskRef,
    elements.enforcedPlanVersion,
    elements.enforcedStaleStatus,
    elements.enforcedDispatchMode,
    elements.enforcedAsrToControl,
    elements.enforcedRequestToFirstDelta,
    elements.enforcedRequestToDone,
    elements.enforcedRouterGateLatency,
    elements.enforcedControlTainted,
    elements.enforcedVoiceTainted,
  ]) {
    element.textContent = "not_available";
    setTone(element, "");
  }
  for (const element of [
    elements.enforcedControlCancelCount,
    elements.enforcedControlDeleteCount,
    elements.enforcedControlRebuildCount,
    elements.enforcedControlDropCount,
    elements.enforcedVoiceCancelCount,
    elements.enforcedVoiceCancelTerminalCount,
    elements.enforcedVoiceDeleteCount,
    elements.enforcedVoiceRebuildCount,
    elements.enforcedTextSuppressionCount,
    elements.enforcedAudioSuppressionCount,
    elements.enforcedBinaryPlaybackCount,
  ]) element.textContent = "0";
}

function resetSessionUi() {
  state.sessionReady = false;
  state.degraded = false;
  state.providerMode = "fake";
  state.routingMode = "enforced";
  state.audioOutput = "fake_pcm";
  state.providerAudioDisabled = false;
  state.outputMode = "fake";
  state.playbackEpoch = 0;
  state.droppedInputFrames = 0;
  state.droppedOutputFrames = 0;
  state.discardedLateAudioFrames = 0;
  state.pendingAudioFrames.length = 0;
  state.audioDispatchGeneration += 1;
  state.clearRequests.clear();
  elements.inputDropCount.textContent = "0";
  elements.outputDropCount.textContent = "0";
  elements.lateAudioDropCount.textContent = "0";
  elements.playbackEpoch.textContent = "0";
  elements.playbackBuffer.textContent = "0 ms";
  elements.clearLatency.textContent = "—";
  elements.proposalRoute.textContent = "—";
  elements.proposalFocus.textContent = "—";
  elements.foregroundAct.textContent = "—";
  elements.proposalRisk.textContent = "—";
  elements.proposalConfidence.textContent = "—";
  elements.routerDecision.textContent = "—";
  elements.routerFocus.textContent = "—";
  elements.gateStatus.textContent = "—";
  elements.gateReason.textContent = "—";
  elements.taskId.textContent = "none";
  elements.taskLifecycle.textContent = "idle";
  elements.planVersion.textContent = "—";
  elements.patchStatus.textContent = "—";
  elements.micStatus.textContent = "not_requested";
  elements.inputLevel.value = 0;
  elements.inputLevelText.textContent = "0%";
  resetShadowUi();
  resetEnforcedUi();
  setOutputMode("fake");
  setActivity("idle");
  resetConversation();
  clearTimeline();
}

function resetConversation() {
  state.conversationRows.length = 0;
  state.conversationSequence = 0;
  elements.conversation.replaceChildren();
  const placeholder = document.createElement("p");
  placeholder.className = "placeholder";
  placeholder.textContent = "运行 Fake 场景或开始讲话后，服务器已提交的文本会显示在这里。";
  elements.conversation.append(placeholder);
}

function transcriptCorrelation(role, event) {
  const reference = firstValue(event, ["response_id", "turn_id", "utterance_id", "provider_item_id"]);
  if (reference !== undefined) return `${role}:${safeToken(reference, "anonymous", 96)}`;
  for (let index = state.conversationRows.length - 1; index >= 0; index -= 1) {
    const row = state.conversationRows[index];
    if (row.role === role && !row.final) return row.key;
  }
  state.conversationSequence += 1;
  return `${role}:local-${state.conversationSequence}`;
}

function ensureConversationRow(role, event) {
  const key = transcriptCorrelation(role, event);
  let row = state.conversationRows.find((candidate) => candidate.key === key);
  if (row) return row;

  elements.conversation.querySelector(".placeholder")?.remove();
  const node = document.createElement("article");
  const roleNode = document.createElement("span");
  const body = document.createElement("div");
  node.className = `message ${role} pending`;
  roleNode.className = "message-role";
  roleNode.textContent = role === "user" ? "User" : "Assistant";
  body.className = "message-body";
  node.append(roleNode, body);
  elements.conversation.append(node);
  row = { key, role, text: "", final: false, node, body };
  state.conversationRows.push(row);
  return row;
}

function pruneConversation() {
  const totalChars = () => state.conversationRows.reduce((sum, row) => sum + row.text.length, 0);
  while (
    state.conversationRows.length > MAX_CONVERSATION_ROWS
    || (state.conversationRows.length > 1 && totalChars() > MAX_CONVERSATION_CHARS)
  ) {
    const removed = state.conversationRows.shift();
    removed?.node.remove();
  }
}

function recordAssistantTextSuppression(reason = "assistant_text_not_committed") {
  const next = state.enforcedCounters.assistant_text_suppression_count + 1;
  state.enforcedCounters.assistant_text_suppression_count = next;
  elements.enforcedTextSuppressionCount.textContent = String(next);
  appendTimeline("assistant_text.suppressed", {
    assistant_text_suppression_count: next,
    degraded_code: safeCode(reason, "assistant_text_not_committed"),
  });
}

function qwenEnforcedAssistantCommitIsSafe(event) {
  if (!qwenEnforcedMode()) return true;
  if (event.server_committed !== true) return false;
  const source = safeEnum(event.source, new Set(["control_candidate", "controlled_template"]), "");
  if (!source) return false;
  return safeOpaqueRef(firstValue(event, ["commit_ref", "committed_event_id"]), "") !== "";
}

function handleTranscript(role, event, final) {
  // Deliberately called only for transcript.user.* / transcript.assistant.*.
  // Provider proposals and quarantined candidate fields never reach this path.
  if (role === "assistant" && !qwenEnforcedAssistantCommitIsSafe(event)) {
    recordAssistantTextSuppression("assistant_text_not_server_committed");
    return;
  }
  const row = ensureConversationRow(role, event);
  const fullText = boundedText(firstValue(event, ["text", "transcript"], ""));
  const delta = boundedText(firstValue(event, ["delta", "text_delta"], ""));
  if (final && fullText) row.text = fullText;
  else if (delta) row.text = boundedText(row.text + delta);
  else if (!final && fullText) row.text = boundedText(row.text + fullText);
  else if (!row.text && fullText) row.text = fullText;
  row.final = final;
  row.body.textContent = row.text;
  row.node.className = `message ${role}${final ? "" : " pending"}`;
  pruneConversation();
  elements.conversation.scrollTop = elements.conversation.scrollHeight;
}

function updateCounter(element, rawValue, current) {
  const value = strictFiniteNumber(rawValue, 0, 1_000_000_000);
  const next = value === null ? current : Math.max(current, Math.floor(value));
  element.textContent = String(next);
  return next;
}

function applyCounters(event) {
  const counters = event && typeof event.counters === "object" ? event.counters : event;
  state.droppedInputFrames = updateCounter(
    elements.inputDropCount,
    firstValue(counters, ["dropped_input_frames", "input_dropped_frames"]),
    state.droppedInputFrames,
  );
  state.droppedOutputFrames = updateCounter(
    elements.outputDropCount,
    firstValue(counters, ["dropped_output_frames", "output_dropped_frames"]),
    state.droppedOutputFrames,
  );
  state.discardedLateAudioFrames = updateCounter(
    elements.lateAudioDropCount,
    firstValue(counters, ["discarded_late_audio_frames", "late_audio_dropped_frames"]),
    state.discardedLateAudioFrames,
  );
}

function updateEpoch(rawEpoch) {
  const epoch = finiteNumber(rawEpoch, 0, 0xffff_ffff);
  if (epoch === null) return state.playbackEpoch;
  state.playbackEpoch = Math.floor(epoch);
  elements.playbackEpoch.textContent = String(state.playbackEpoch);
  return state.playbackEpoch;
}

function sendControl(type, payload = {}) {
  if (!socketIsOpen()) return false;
  const message = JSON.stringify({ type, protocol_version: PROTOCOL_VERSION, ...payload });
  if (new TextEncoder().encode(message).byteLength > MAX_CONTROL_FRAME_BYTES) return false;
  state.socket.send(message);
  return true;
}

function scheduleMicFlush(delayMs = 0) {
  if (state.micFlushTimer !== null) return;
  state.micFlushTimer = window.setTimeout(() => {
    state.micFlushTimer = null;
    flushMicFrames();
  }, delayMs);
}

function flushMicFrames() {
  if (!state.mic || !socketIsOpen()) {
    if (state.micFrames.length > 0) {
      state.droppedInputFrames += state.micFrames.length;
      state.micFrames.length = 0;
      elements.inputDropCount.textContent = String(state.droppedInputFrames);
    }
    return;
  }
  while (state.micFrames.length > 0 && state.socket.bufferedAmount <= WS_HIGH_WATER_BYTES) {
    state.socket.send(state.micFrames.shift());
  }
  if (state.micFrames.length > 0) scheduleMicFlush(20);
}

function handleMicMessage(event) {
  const message = event.data || {};
  if (message.type !== "pcm" || !(message.pcm instanceof ArrayBuffer)) return;
  const level = finiteNumber(message.level, 0, 1) ?? 0;
  elements.inputLevel.value = level;
  elements.inputLevelText.textContent = `${Math.round(level * 100)}%`;
  if (message.pcm.byteLength !== INPUT_FRAME_BYTES || !state.mic || !socketIsOpen()) {
    state.droppedInputFrames += 1;
    elements.inputDropCount.textContent = String(state.droppedInputFrames);
    return;
  }
  if (state.micFrames.length >= MIC_QUEUE_LIMIT) {
    state.droppedInputFrames += 1;
    elements.inputDropCount.textContent = String(state.droppedInputFrames);
    return;
  }
  state.micFrames.push(message.pcm);
  scheduleMicFlush();
}

async function startMicrophone() {
  if (state.mic || !socketIsOpen() || !state.sessionReady) return;
  elements.micStatus.textContent = "requesting";
  let pendingStream = null;
  let pendingContext = null;
  try {
    await resumePlayer();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    pendingStream = stream;
    if (!socketIsOpen()) {
      stream.getTracks().forEach((track) => track.stop());
      pendingStream = null;
      elements.micStatus.textContent = "disconnected";
      return;
    }
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass || !window.AudioWorkletNode) throw new Error("audio_worklet_unavailable");
    const context = new AudioContextClass({ latencyHint: "interactive" });
    pendingContext = context;
    await context.audioWorklet.addModule("/static/mic-worklet.js");
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, "qfs-pcm16-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    node.port.onmessage = handleMicMessage;
    source.connect(node);
    node.connect(silentGain);
    silentGain.connect(context.destination);
    await context.resume();
    state.mic = { stream, context, source, node, silentGain };
    pendingStream = null;
    pendingContext = null;
    elements.micStatus.textContent = "capturing";
    sendControl("microphone.start", {
      sample_rate_hz: 16_000,
      encoding: "pcm16le",
      channels: 1,
      frame_ms: 100,
    });
    setActivity("listening");
    appendTimeline("microphone.start");
  } catch (error) {
    pendingStream?.getTracks().forEach((track) => track.stop());
    await pendingContext?.close().catch(() => {});
    elements.micStatus.textContent = error?.name === "NotAllowedError" ? "denied" : "unavailable";
    markDegraded("microphone_unavailable");
    appendTimeline("safe_error", { degraded: true });
  } finally {
    refreshButtons();
  }
}

async function stopMicrophone({ notify = true } = {}) {
  const mic = state.mic;
  state.mic = null;
  if (notify) sendControl("microphone.stop");
  if (state.micFlushTimer !== null) {
    clearTimeout(state.micFlushTimer);
    state.micFlushTimer = null;
  }
  if (state.micFrames.length > 0) {
    state.droppedInputFrames += state.micFrames.length;
    state.micFrames.length = 0;
    elements.inputDropCount.textContent = String(state.droppedInputFrames);
  }
  if (mic) {
    mic.node.port.onmessage = null;
    mic.node.port.postMessage({ type: "active", active: false });
    try { mic.source.disconnect(); } catch (_error) { /* already disconnected */ }
    try { mic.node.disconnect(); } catch (_error) { /* already disconnected */ }
    try { mic.silentGain.disconnect(); } catch (_error) { /* already disconnected */ }
    mic.stream.getTracks().forEach((track) => track.stop());
    await mic.context.close().catch(() => {});
  }
  elements.micStatus.textContent = "stopped";
  elements.inputLevel.value = 0;
  elements.inputLevelText.textContent = "0%";
  refreshButtons();
}

function recordAudioSuppression(reason = "provider_audio_disabled") {
  const next = state.enforcedCounters.audio_suppression_count + 1;
  state.enforcedCounters.audio_suppression_count = next;
  elements.enforcedAudioSuppressionCount.textContent = String(next);
  // This counter is frames played, not received. The enforced client never
  // passes suppressed binary data to the AudioWorklet.
  state.enforcedCounters.binary_playback_frame_count = 0;
  elements.enforcedBinaryPlaybackCount.textContent = "0";
  appendTimeline("audio.suppressed", {
    audio_suppression_count: next,
    binary_playback_frame_count: 0,
    degraded_code: safeCode(reason, "provider_audio_disabled"),
  });
}

async function ensurePlayer() {
  if (state.providerAudioDisabled) return null;
  if (state.player) return state.player;
  if (state.playerPromise) return state.playerPromise;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass || !window.AudioWorkletNode) {
    markDegraded("playback_unavailable");
    return null;
  }
  state.playerPromise = (async () => {
    let context = null;
    try {
      context = new AudioContextClass({ latencyHint: "interactive" });
      await context.audioWorklet.addModule("/static/player-worklet.js");
      const node = new AudioWorkletNode(context, "qfs-pcm24k-player", {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      const gain = context.createGain();
      gain.gain.value = 1;
      node.port.onmessage = handlePlayerMessage;
      node.connect(gain);
      gain.connect(context.destination);
      state.player = { context, node, gain };
      node.port.postMessage({ type: "clear", epoch: state.playbackEpoch, token: "initial" });
      return state.player;
    } catch (_error) {
      await context?.close().catch(() => {});
      markDegraded("playback_unavailable");
      return null;
    } finally {
      state.playerPromise = null;
    }
  })();
  return state.playerPromise;
}

async function resumePlayer() {
  if (state.providerAudioDisabled) return null;
  const player = await ensurePlayer();
  if (player?.context.state === "suspended") await player.context.resume().catch(() => {});
  return player;
}

async function closePlayer() {
  if (state.playerPromise) await state.playerPromise.catch(() => null);
  const player = state.player;
  state.player = null;
  state.clearRequests.clear();
  if (!player) return;
  player.node.port.onmessage = null;
  try { player.node.disconnect(); } catch (_error) { /* already disconnected */ }
  try { player.gain.disconnect(); } catch (_error) { /* already disconnected */ }
  await player.context.close().catch(() => {});
}

function clearPlayback(reason, rawEpoch, serverLatency = null) {
  const epochValue = finiteNumber(rawEpoch, 0, 0xffff_ffff);
  const epoch = epochValue === null ? state.playbackEpoch : Math.floor(epochValue);
  if (epoch < state.playbackEpoch) return false;
  updateEpoch(epoch);
  state.audioDispatchGeneration += 1;
  if (state.pendingAudioFrames.length > 0) {
    state.droppedOutputFrames += state.pendingAudioFrames.length;
    state.pendingAudioFrames.length = 0;
    elements.outputDropCount.textContent = String(state.droppedOutputFrames);
  }
  const token = `clear-${++state.clearSequence}`;
  state.clearRequests.set(token, performance.now());
  state.player?.node.port.postMessage({ type: "clear", epoch, token });
  if (!state.player) {
    state.clearRequests.delete(token);
    elements.clearLatency.textContent = serverLatency === null ? "0 ms" : `${Math.round(serverLatency)} ms`;
  } else if (serverLatency !== null) {
    elements.clearLatency.textContent = `${Math.round(serverLatency)} ms server`;
  }
  setActivity("interrupted");
  appendTimeline("playback.clear", {
    playback_epoch: epoch,
    clear_latency_ms: serverLatency === null ? undefined : serverLatency,
  });
  return true;
}

function handlePlayerMessage(event) {
  const message = event.data || {};
  if (message.type === "cleared") {
    const startedAt = state.clearRequests.get(message.token);
    if (startedAt !== undefined) {
      const latency = Math.max(0, performance.now() - startedAt);
      state.clearRequests.delete(message.token);
      elements.clearLatency.textContent = `${latency.toFixed(1)} ms`;
    }
  } else if (message.type === "buffer_status") {
    const samples = finiteNumber(message.buffered_samples, 0, 24_000 * 15) ?? 0;
    elements.playbackBuffer.textContent = `${Math.round(samples / 24)} ms`;
    state.droppedOutputFrames = updateCounter(
      elements.outputDropCount,
      message.dropped_frames,
      state.droppedOutputFrames,
    );
    state.discardedLateAudioFrames = updateCounter(
      elements.lateAudioDropCount,
      message.late_dropped_frames,
      state.discardedLateAudioFrames,
    );
  } else if (message.type === "late_audio_dropped") {
    state.discardedLateAudioFrames = updateCounter(
      elements.lateAudioDropCount,
      message.late_dropped_frames,
      state.discardedLateAudioFrames + 1,
    );
    appendTimeline("playback.late_discard", {
      playback_epoch: state.playbackEpoch,
      discarded_late_audio_frames: state.discardedLateAudioFrames,
    });
  } else if (message.type === "output_capacity_exceeded") {
    state.droppedOutputFrames = updateCounter(
      elements.outputDropCount,
      message.dropped_frames,
      state.droppedOutputFrames + 1,
    );
    markDegraded("output_queue_bounded");
    appendTimeline("flow.changed", {
      playback_epoch: state.playbackEpoch,
      dropped_output_frames: state.droppedOutputFrames,
      degraded: true,
    });
  } else if (message.type === "epoch_advanced") {
    updateEpoch(message.epoch);
  }
}

async function handleAudioFrame(buffer, dispatchGeneration) {
  if (!state.sessionReady || dispatchGeneration !== state.audioDispatchGeneration) return;
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength <= OUTPUT_HEADER_BYTES) return;
  if (buffer.byteLength > MAX_OUTPUT_FRAME_BYTES || (buffer.byteLength - OUTPUT_HEADER_BYTES) % 2 !== 0) {
    state.droppedOutputFrames += 1;
    elements.outputDropCount.textContent = String(state.droppedOutputFrames);
    markDegraded("output_frame_rejected");
    return;
  }
  const bytes = new Uint8Array(buffer, 0, 4);
  if (!OUTPUT_MAGIC.every((value, index) => bytes[index] === value)) {
    state.droppedOutputFrames += 1;
    elements.outputDropCount.textContent = String(state.droppedOutputFrames);
    return;
  }
  const epoch = new DataView(buffer, 4, 4).getUint32(0, false);
  if (epoch < state.playbackEpoch) {
    state.discardedLateAudioFrames += 1;
    elements.lateAudioDropCount.textContent = String(state.discardedLateAudioFrames);
    appendTimeline("playback.late_discard", {
      playback_epoch: state.playbackEpoch,
      discarded_late_audio_frames: state.discardedLateAudioFrames,
    });
    return;
  }
  const player = await resumePlayer();
  if (dispatchGeneration !== state.audioDispatchGeneration) {
    state.droppedOutputFrames += 1;
    elements.outputDropCount.textContent = String(state.droppedOutputFrames);
    return;
  }
  if (!player) {
    state.droppedOutputFrames += 1;
    elements.outputDropCount.textContent = String(state.droppedOutputFrames);
    return;
  }
  if (epoch > state.playbackEpoch) clearPlayback("audio_epoch_advance", epoch);
  const pcm = buffer.slice(OUTPUT_HEADER_BYTES);
  player.node.port.postMessage({ type: "enqueue", epoch, pcm }, [pcm]);
}

function enqueueAudioFrame(data) {
  const byteLength = data instanceof ArrayBuffer ? data.byteLength : data instanceof Blob ? data.size : 0;
  if (
    byteLength <= OUTPUT_HEADER_BYTES
    || byteLength > MAX_OUTPUT_FRAME_BYTES
    || state.pendingAudioFrames.length >= OUTPUT_DISPATCH_QUEUE_LIMIT
  ) {
    state.droppedOutputFrames += 1;
    elements.outputDropCount.textContent = String(state.droppedOutputFrames);
    if (state.pendingAudioFrames.length >= OUTPUT_DISPATCH_QUEUE_LIMIT) markDegraded("output_dispatch_bounded");
    return;
  }
  state.pendingAudioFrames.push({ data, generation: state.audioDispatchGeneration });
  drainAudioFrames();
}

async function drainAudioFrames() {
  if (state.audioDrainActive) return;
  state.audioDrainActive = true;
  try {
    while (state.pendingAudioFrames.length > 0) {
      const queued = state.pendingAudioFrames.shift();
      try {
        const buffer = queued.data instanceof ArrayBuffer ? queued.data : await queued.data.arrayBuffer();
        await handleAudioFrame(buffer, queued.generation);
      } catch (_error) {
        state.droppedOutputFrames += 1;
        elements.outputDropCount.textContent = String(state.droppedOutputFrames);
        markDegraded("audio_frame_error");
      }
    }
  } finally {
    state.audioDrainActive = false;
    if (state.pendingAudioFrames.length > 0) drainAudioFrames();
  }
}

function shadowField(event, directKeys, nestedGroup = null, nestedKeys = []) {
  const direct = firstValue(event, directKeys);
  if (direct !== undefined) return direct;
  const nested = nestedGroup && event && typeof event[nestedGroup] === "object"
    ? event[nestedGroup]
    : null;
  return firstValue(nested, nestedKeys);
}

function setShadowEnum(element, rawValue, allowed, { complete = false, tone = "evidence" } = {}) {
  if (rawValue === undefined && !complete) return;
  const value = safeEnum(rawValue, allowed);
  element.textContent = value;
  setTone(element, value === "not_available" ? "" : tone);
}

function setShadowLatency(element, rawValue, complete) {
  if (rawValue === undefined && !complete) return;
  element.textContent = formatLatency(rawValue);
}

function setShadowCounter(name, element, rawValue, complete) {
  if (rawValue === undefined) {
    if (complete) element.textContent = "not_available";
    return;
  }
  const value = finiteNumber(rawValue, 0, 1_000_000_000);
  if (value === null) {
    element.textContent = "not_available";
    return;
  }
  const next = Math.max(state.shadowCounters[name], Math.floor(value));
  state.shadowCounters[name] = next;
  element.textContent = String(next);
}

// This is a display-only boundary. It cannot call the authoritative Router/Gate,
// mutate task state, append QA text, enqueue audio, or change playback epochs.
function handleShadowProjection(event, { complete = false, degraded = false } = {}) {
  const provider = firstValue(event, ["provider_mode", "provider"]);
  setShadowEnum(elements.shadowProvider, provider, PROVIDER_MODES, { complete });

  const routing = firstValue(event, ["routing_mode", "routing"]);
  setShadowEnum(elements.shadowRouting, routing, ROUTING_MODES, { complete });

  const voiceStatus = firstValue(event, ["voice_session_status", "voice_session_state"]);
  if (voiceStatus !== undefined || complete) setShadowSessionStatus(elements.voiceSessionStatus, voiceStatus);

  let controlStatus = firstValue(event, [
    "shadow_control_session_status",
    "shadow_control_status",
    "shadow_session_state",
  ]);
  if (event.context_tainted === true) controlStatus = "degraded";
  else if (degraded && controlStatus === undefined) controlStatus = "degraded";
  if (controlStatus !== undefined || complete) setShadowSessionStatus(elements.shadowControlStatus, controlStatus);

  const controlMode = firstValue(event, ["shadow_control_mode", "shadow_control"]);
  setShadowEnum(elements.shadowControlMode, controlMode, SHADOW_CONTROL_MODES, { complete });

  const audioOutput = firstValue(event, ["audio_output"]);
  setShadowEnum(elements.shadowAudioOutput, audioOutput, AUDIO_OUTPUT_MODES, { complete });

  const safeTurnRef = firstValue(event, ["safe_turn_ref"]);
  if (safeTurnRef !== undefined || complete) {
    elements.shadowSafeTurnRef.textContent = safeOpaqueRef(safeTurnRef);
  }
  setShadowPresence(elements.shadowActiveTaskContext, event.active_task_present, complete);
  setShadowPresence(elements.shadowPendingConfirmation, event.pending_confirmation_present, complete);

  setShadowEnum(
    elements.shadowQwenFocus,
    firstValue(event, ["qwen_task_focus_hint", "task_focus_hint"]),
    TASK_FOCUS_HINTS,
    { complete },
  );
  setShadowEnum(
    elements.shadowQwenRoute,
    firstValue(event, ["qwen_route_hint", "route_hint"]),
    ROUTE_HINTS,
    { complete },
  );
  setShadowEnum(elements.shadowForegroundAct, event.foreground_act, FOREGROUND_ACTS, { complete });
  const risk = event.risk_class;
  setShadowEnum(elements.shadowRisk, risk, RISK_CLASSES, { complete });
  if (risk !== undefined) {
    const normalizedRisk = safeEnum(risk, RISK_CLASSES);
    setTone(elements.shadowRisk, normalizedRisk === "HIGH" ? "error" : normalizedRisk === "MEDIUM" ? "degraded" : normalizedRisk === "LOW" ? "evidence" : "");
  }

  if (event.confidence !== undefined || complete) {
    const confidence = strictFiniteNumber(event.confidence, 0, 1);
    elements.shadowConfidence.textContent = confidence === null ? "not_available" : confidence.toFixed(3);
  }

  let schemaStatus = event.schema_status;
  if (schemaStatus === undefined && typeof event.schema_valid === "boolean") {
    schemaStatus = event.schema_valid ? "valid" : "invalid";
  }
  if (schemaStatus !== undefined || complete) {
    const value = safeEnum(schemaStatus, SCHEMA_STATUSES);
    elements.shadowSchema.textContent = value;
    setTone(elements.shadowSchema, value === "valid" ? "healthy" : value === "invalid" ? "error" : "");
  }

  setShadowEnum(
    elements.shadowLocalDecision,
    firstValue(event, ["local_router_decision", "router_decision"]),
    ROUTE_HINTS,
    { complete },
  );
  setShadowEnum(
    elements.shadowLocalFocus,
    firstValue(event, ["local_task_focus", "task_focus"]),
    TASK_FOCUS_HINTS,
    { complete },
  );
  setShadowEnum(
    elements.shadowLocalForegroundAct,
    event.local_foreground_act,
    FOREGROUND_ACTS,
    { complete },
  );

  let agreement = event.agreement;
  if (typeof agreement === "boolean") agreement = agreement ? "yes" : "no";
  if (agreement !== undefined || complete) {
    const value = safeEnum(agreement, AGREEMENT_STATUSES);
    elements.shadowAgreement.textContent = value;
    setTone(elements.shadowAgreement, value === "yes" ? "healthy" : value === "no" ? "degraded" : "");
  }

  setShadowLatency(
    elements.shadowAsrToRequest,
    shadowField(event, ["asr_to_shadow_request_ms"], "latency_ms", ["asr_final_to_request"]),
    complete,
  );
  setShadowLatency(
    elements.shadowRequestToFirstDelta,
    shadowField(event, ["shadow_request_to_first_delta_ms"], "latency_ms", ["function_call_first_delta"]),
    complete,
  );
  setShadowLatency(
    elements.shadowRequestToDone,
    shadowField(event, ["shadow_request_to_done_ms"], "latency_ms", ["function_call_done"]),
    complete,
  );
  setShadowLatency(
    elements.shadowDoneToLocal,
    shadowField(event, ["function_done_to_local_router_ms"], "latency_ms", ["done_to_local_router"]),
    complete,
  );

  setShadowCounter(
    "control_timeout_count",
    elements.shadowTimeoutCount,
    shadowField(event, ["control_timeout_count"], "counters", ["control_timeout"]),
    complete,
  );
  setShadowCounter(
    "control_error_count",
    elements.shadowErrorCount,
    shadowField(event, ["control_error_count"], "counters", ["error"]),
    complete,
  );
  setShadowCounter(
    "shadow_drop_count",
    elements.shadowDropCount,
    shadowField(event, ["shadow_drop_count"], "counters", ["request_drop", "late_discard"]),
    complete,
  );
  setShadowCounter(
    "context_delete_count",
    elements.shadowContextDeleteCount,
    shadowField(event, ["context_delete_count"], "counters", ["context_delete"]),
    complete,
  );
  setShadowCounter(
    "context_rebuild_count",
    elements.shadowContextRebuildCount,
    shadowField(event, ["context_rebuild_count"], "counters", ["context_rebuild"]),
    complete,
  );

  let evidenceMode = event.output_mode;
  if (degraded || event.context_tainted === true) evidenceMode = "degraded";
  if (evidenceMode !== undefined || complete) setShadowEvidenceMode(evidenceMode);
}

function enforcedField(event, directKeys, nestedGroups = [], nestedKeys = []) {
  const direct = firstValue(event, directKeys);
  if (direct !== undefined) return direct;
  for (const group of nestedGroups) {
    const nested = event && typeof event[group] === "object" ? event[group] : null;
    const value = firstValue(nested, nestedKeys);
    if (value !== undefined) return value;
  }
  return undefined;
}

function setEnforcedEnum(element, rawValue, allowed, { complete = false, tone = "evidence" } = {}) {
  if (rawValue === undefined && !complete) return;
  const value = safeEnum(rawValue, allowed);
  element.textContent = value;
  setTone(element, value === "not_available" ? "" : tone);
}

function setEnforcedCounter(name, element, rawValue, complete) {
  if (rawValue === undefined) {
    if (complete) element.textContent = "0";
    return;
  }
  const value = strictFiniteNumber(rawValue, 0, 1_000_000_000);
  if (value === null) return;
  const next = Math.max(state.enforcedCounters[name], Math.floor(value));
  state.enforcedCounters[name] = next;
  element.textContent = String(next);
}

function setEnforcedActive(active, degraded = false) {
  elements.enforcedPanel.dataset.active = active ? "true" : "false";
  elements.enforcedStatus.textContent = active ? (degraded ? "degraded" : "active") : "inactive";
  elements.enforcedStatus.className = `badge ${active ? (degraded ? "degraded" : "healthy") : "neutral"}`;
}

// Display-only projection for qwen+enforced metadata. It never appends QA text,
// releases candidate content, invokes Router/Gate, or mutates authoritative task state.
function handleEnforcedProjection(event, { complete = false, degraded = false, dispatch = false } = {}) {
  const topology = firstValue(event, ["control_topology", "topology"]);
  const active = qwenEnforcedMode() || topology === "dual_session_enforced_control";
  if (!active) return;
  setEnforcedActive(true, degraded || event.degraded === true);

  setEnforcedEnum(elements.enforcedProvider, firstValue(event, ["provider_mode", "provider"]), PROVIDER_MODES, { complete });
  setEnforcedEnum(elements.enforcedRouting, firstValue(event, ["routing_mode", "routing"]), ROUTING_MODES, { complete });
  setEnforcedEnum(elements.enforcedAudioOutput, event.audio_output, AUDIO_OUTPUT_MODES, { complete });
  setEnforcedEnum(elements.enforcedSlowRuntime, firstValue(event, ["slow_runtime_mode", "slow_runtime"]), SLOW_RUNTIME_MODES, { complete });
  setEnforcedEnum(elements.enforcedTopology, topology, CONTROL_TOPOLOGIES, { complete });

  const foregroundOutput = firstValue(event, ["foreground_output_mode", "foreground_output", "output"]);
  if (foregroundOutput !== undefined) {
    setEnforcedEnum(elements.enforcedOutput, foregroundOutput, FOREGROUND_OUTPUT_MODES);
  } else if (complete && typeof event.output_mode === "string") {
    setEnforcedEnum(elements.enforcedOutput, event.output_mode, FOREGROUND_OUTPUT_MODES, { complete: true });
  }
  if (event.experimental !== undefined || complete) {
    setBooleanState(elements.enforcedExperimental, event.experimental, { trueLabel: "yes", falseLabel: "no" });
  }

  const voiceStatus = firstValue(event, ["voice_ingress_session_status", "voice_session_status"]);
  if (voiceStatus !== undefined || complete) setShadowSessionStatus(elements.enforcedVoiceStatus, voiceStatus);
  const controlStatus = firstValue(event, ["control_session_status", "shadow_control_session_status", "control_status"]);
  if (controlStatus !== undefined || complete) setShadowSessionStatus(elements.enforcedControlStatus, controlStatus);

  const safeTurnRef = firstValue(event, ["safe_turn_ref", "current_safe_turn_ref"]);
  if (safeTurnRef !== undefined || complete) elements.enforcedSafeTurnRef.textContent = safeOpaqueRef(safeTurnRef);

  setEnforcedEnum(
    elements.enforcedProposalAuthority,
    event.qwen_proposal_authority,
    PROPOSAL_AUTHORITIES,
    { complete, tone: "degraded" },
  );
  setEnforcedEnum(
    elements.enforcedRouterAuthority,
    event.local_router_authority,
    ROUTER_AUTHORITIES,
    { complete, tone: "healthy" },
  );
  if (event.provider_native_audio_disabled !== undefined || complete) {
    const disabled = event.provider_native_audio_disabled;
    elements.enforcedProviderAudio.textContent = typeof disabled === "boolean"
      ? (disabled ? "disabled" : "enabled")
      : "not_available";
    setTone(elements.enforcedProviderAudio, disabled === true ? "healthy" : disabled === false ? "error" : "");
  }

  setEnforcedEnum(
    elements.enforcedQwenFocus,
    firstValue(event, ["qwen_task_focus_hint", "task_focus_hint"]),
    TASK_FOCUS_HINTS,
    { complete },
  );
  setEnforcedEnum(
    elements.enforcedQwenRoute,
    firstValue(event, ["qwen_route_hint", "route_hint"]),
    ROUTE_HINTS,
    { complete },
  );
  setEnforcedEnum(elements.enforcedForegroundAct, event.foreground_act, FOREGROUND_ACTS, { complete });
  const risk = event.risk_class;
  setEnforcedEnum(elements.enforcedRisk, risk, RISK_CLASSES, { complete });
  if (risk !== undefined) {
    const normalizedRisk = safeEnum(risk, RISK_CLASSES);
    setTone(elements.enforcedRisk, normalizedRisk === "HIGH" ? "error" : normalizedRisk === "MEDIUM" ? "degraded" : normalizedRisk === "LOW" ? "evidence" : "");
  }
  if (event.confidence !== undefined || complete) {
    const confidence = strictFiniteNumber(event.confidence, 0, 1);
    elements.enforcedConfidence.textContent = confidence === null ? "not_available" : confidence.toFixed(3);
  }
  let schemaStatus = event.schema_status;
  if (schemaStatus === undefined && typeof event.schema_valid === "boolean") schemaStatus = event.schema_valid ? "valid" : "invalid";
  if (schemaStatus !== undefined || complete) {
    const value = safeEnum(schemaStatus, SCHEMA_STATUSES);
    elements.enforcedSchema.textContent = value;
    setTone(elements.enforcedSchema, value === "valid" ? "healthy" : value === "invalid" ? "error" : "");
  }
  const evidenceMode = firstValue(event, ["proposal_output_mode", "evidence_output_mode"]);
  if (evidenceMode !== undefined) setEnforcedEnum(elements.enforcedEvidenceMode, evidenceMode, EVIDENCE_MODES);
  else if (event.type === "control.state" && event.output_mode !== undefined) {
    setEnforcedEnum(elements.enforcedEvidenceMode, event.output_mode, EVIDENCE_MODES);
  } else if (complete) {
    setEnforcedEnum(elements.enforcedEvidenceMode, undefined, EVIDENCE_MODES, { complete: true });
  }

  setEnforcedEnum(
    elements.enforcedLocalDecision,
    firstValue(event, ["local_router_decision", "router_decision"]),
    ROUTE_HINTS,
    { complete },
  );
  setEnforcedEnum(
    elements.enforcedLocalFocus,
    firstValue(event, ["local_task_focus", "task_focus"]),
    TASK_FOCUS_HINTS,
    { complete },
  );
  setEnforcedEnum(
    elements.enforcedLocalForegroundAct,
    event.local_foreground_act,
    FOREGROUND_ACTS,
    { complete },
  );
  if (event.gate_status !== undefined || complete) {
    const gateStatus = safeCode(event.gate_status, "not_available");
    elements.enforcedGateStatus.textContent = gateStatus;
    setTone(elements.enforcedGateStatus, gateStatus === "passed" ? "healthy" : ["failed", "discarded"].includes(gateStatus) ? "degraded" : "");
  }
  const gateReason = firstValue(event, ["gate_reason", "failure_reason"]);
  if (gateReason !== undefined || complete) elements.enforcedGateReason.textContent = safeCode(gateReason, "not_available");
  setEnforcedEnum(elements.enforcedActualDispatch, event.actual_dispatch, DISPATCH_STATUSES, { complete: dispatch, tone: "healthy" });

  const taskRef = firstValue(event, ["safe_task_ref", "task_id"]);
  if (taskRef !== undefined || dispatch) elements.enforcedTaskRef.textContent = safeOpaqueRef(taskRef);
  const planVersion = strictFiniteNumber(event.plan_version, 0, 1_000_000);
  if (event.plan_version !== undefined || dispatch) {
    elements.enforcedPlanVersion.textContent = planVersion === null ? "not_available" : String(Math.floor(planVersion));
  }
  let staleStatus = event.stale_status;
  if (staleStatus === undefined && event.superseded === true) staleStatus = "superseded";
  else if (staleStatus === undefined && event.stale === true) staleStatus = "stale";
  setEnforcedEnum(elements.enforcedStaleStatus, staleStatus, STALE_STATUSES, { complete: dispatch });
  if (dispatch) setEnforcedEnum(elements.enforcedDispatchMode, event.output_mode, EVIDENCE_MODES, { complete: true });

  const latencyGroups = ["latencies", "latency_ms"];
  setShadowLatency(
    elements.enforcedAsrToControl,
    enforcedField(event, ["asr_to_control_request_ms", "asr_final_to_request_ms", "asr_to_shadow_request_ms"], latencyGroups, ["asr_final_to_request", "asr_to_control_request"]),
    complete,
  );
  setShadowLatency(
    elements.enforcedRequestToFirstDelta,
    enforcedField(event, ["control_request_to_first_delta_ms", "shadow_request_to_first_delta_ms"], latencyGroups, ["function_call_first_delta", "request_to_first_delta"]),
    complete,
  );
  setShadowLatency(
    elements.enforcedRequestToDone,
    enforcedField(event, ["control_request_to_done_ms", "shadow_request_to_done_ms"], latencyGroups, ["function_call_done", "request_to_done"]),
    complete,
  );
  setShadowLatency(
    elements.enforcedRouterGateLatency,
    enforcedField(event, ["router_gate_latency_ms"], latencyGroups, ["router_gate"]),
    complete,
  );

  const counterGroups = ["counters"];
  const counterBindings = [
    ["control_cancel_count", elements.enforcedControlCancelCount, ["control_cancel_count", "provider_cancel_count"], ["control_cancel"]],
    ["control_delete_count", elements.enforcedControlDeleteCount, ["control_delete_count", "context_delete_count"], ["control_delete", "context_delete"]],
    ["control_rebuild_count", elements.enforcedControlRebuildCount, ["control_rebuild_count", "context_rebuild_count"], ["control_rebuild", "context_rebuild"]],
    ["control_drop_count", elements.enforcedControlDropCount, ["control_drop_count", "shadow_drop_count"], ["control_drop", "request_drop"]],
    ["voice_cancel_count", elements.enforcedVoiceCancelCount, ["voice_cancel_count"], ["voice_cancel"]],
    ["voice_cancel_terminal_count", elements.enforcedVoiceCancelTerminalCount, ["voice_cancel_terminal_count"], ["voice_cancel_terminal"]],
    ["voice_context_delete_count", elements.enforcedVoiceDeleteCount, ["voice_context_delete_count"], ["voice_context_delete"]],
    ["voice_context_rebuild_count", elements.enforcedVoiceRebuildCount, ["voice_context_rebuild_count"], ["voice_context_rebuild"]],
    ["assistant_text_suppression_count", elements.enforcedTextSuppressionCount, ["assistant_text_suppression_count"], ["assistant_text_suppression"]],
    ["audio_suppression_count", elements.enforcedAudioSuppressionCount, ["audio_suppression_count"], ["audio_suppression"]],
    ["binary_playback_frame_count", elements.enforcedBinaryPlaybackCount, ["binary_playback_frame_count"], ["binary_playback_frame"]],
  ];
  for (const [name, element, directKeys, nestedKeys] of counterBindings) {
    setEnforcedCounter(name, element, enforcedField(event, directKeys, counterGroups, nestedKeys), complete);
  }
  setTaintState(
    elements.enforcedControlTainted,
    firstValue(event, ["control_context_tainted", "context_tainted"]),
    complete,
  );
  setTaintState(elements.enforcedVoiceTainted, event.voice_context_tainted, complete);
}

function handleSessionReady(event) {
  state.sessionReady = true;
  setConnection("Connected", "healthy");
  state.providerMode = safeEnum(
    firstValue(event, ["provider_mode", "provider"], "fake"),
    PROVIDER_MODES,
    "fake",
  );
  state.routingMode = safeEnum(
    firstValue(event, ["routing_mode", "routing"], "enforced"),
    ROUTING_MODES,
    "enforced",
  );
  state.audioOutput = safeEnum(event.audio_output, AUDIO_OUTPUT_MODES, "not_available");
  state.providerAudioDisabled = event.provider_native_audio_disabled === true
    || (state.providerMode === "qwen" && state.routingMode === "enforced")
    || state.audioOutput === "none";
  const mode = firstValue(event, ["output_mode", "provider_mode", "provider", "mode"], "fake");
  setOutputMode(mode, event.degraded === true);
  if (state.routingMode === "shadow" || state.providerMode === "fake") {
    handleShadowProjection(event, { complete: true });
  } else {
    resetShadowUi();
  }
  handleEnforcedProjection(event, { complete: true, degraded: event.degraded === true });
  if (qwenEnforcedMode()) sendControl("session.configure", { playback_enabled: false });
  updateEpoch(firstValue(event, ["playback_epoch", "epoch"], 0));
  applyCounters(event);
  setActivity("idle");
  refreshButtons();
}

function handleRouteProposal(event) {
  // Evidence only. Never render reply_candidate/candidate/text/audio here.
  if (qwenEnforcedMode()) {
    for (const element of [
      elements.enforcedLocalDecision,
      elements.enforcedLocalFocus,
      elements.enforcedLocalForegroundAct,
      elements.enforcedGateStatus,
      elements.enforcedGateReason,
      elements.enforcedActualDispatch,
      elements.enforcedStaleStatus,
      elements.enforcedDispatchMode,
    ]) {
      element.textContent = "not_available";
      setTone(element, "");
    }
  }
  elements.proposalRoute.textContent = safeToken(firstValue(event, ["route_hint", "route"]));
  elements.proposalFocus.textContent = safeToken(firstValue(event, ["task_focus_hint", "task_focus"]));
  elements.foregroundAct.textContent = safeToken(firstValue(event, ["foreground_act", "act"]));
  elements.proposalRisk.textContent = safeToken(firstValue(event, ["risk_class", "risk"]));
  const confidence = finiteNumber(event.confidence, 0, 1);
  elements.proposalConfidence.textContent = confidence === null ? "—" : confidence.toFixed(3);
  handleEnforcedProjection(event);
  setActivity("routing");
}

function handleRouteDecision(event) {
  elements.routerDecision.textContent = safeToken(firstValue(event, ["router_decision", "decision", "route"]));
  elements.routerFocus.textContent = safeToken(firstValue(event, ["task_focus", "focus"]));
  if (firstValue(event, ["foreground_act", "act"]) !== undefined) {
    elements.foregroundAct.textContent = safeToken(firstValue(event, ["foreground_act", "act"]));
  }
  handleEnforcedProjection(event);
  setActivity("routing");
}

function handleGateResult(event) {
  let status = firstValue(event, ["gate_status", "status", "result"]);
  if (status === undefined && typeof event.passed === "boolean") status = event.passed ? "passed" : "failed";
  if (status === undefined && typeof event.allowed === "boolean") status = event.allowed ? "passed" : "failed";
  elements.gateStatus.textContent = safeToken(status);
  elements.gateReason.textContent = safeToken(firstValue(event, ["failure_reason", "reason"]));
  if (firstValue(event, ["foreground_act", "act"]) !== undefined) {
    elements.foregroundAct.textContent = safeToken(firstValue(event, ["foreground_act", "act"]));
  }
  handleEnforcedProjection(event);
  if (qwenEnforcedMode() && firstValue(event, ["failure_reason", "reason"]) === undefined) {
    elements.enforcedGateReason.textContent = "not_available";
    setTone(elements.enforcedGateReason, "");
  }
}

function handleSlowTaskState(event) {
  const task = event && typeof event.slowtask === "object" ? event.slowtask : event;
  elements.taskId.textContent = safeToken(firstValue(task, ["task_id", "id"]), "none", 96);
  const lifecycle = safeToken(firstValue(task, ["lifecycle", "state"]), "idle", 64);
  elements.taskLifecycle.textContent = lifecycle;
  const planVersion = finiteNumber(firstValue(task, ["plan_version", "version"]), 0, 1_000_000);
  elements.planVersion.textContent = planVersion === null ? "—" : String(Math.floor(planVersion));
  if (!["idle", "completed", "cancelled", "failed", "none"].includes(lifecycle.toLowerCase())) {
    setActivity("slowtask");
  }
  if (qwenEnforcedMode()) {
    const projection = task === event ? event : { ...event, ...task };
    handleEnforcedProjection(projection);
  }
}

function handleUserPatch(event) {
  elements.patchStatus.textContent = safeToken(firstValue(event, ["status", "result"], "accepted"));
  const planVersion = finiteNumber(event.plan_version, 0, 1_000_000);
  if (planVersion !== null) elements.planVersion.textContent = String(Math.floor(planVersion));
  handleEnforcedProjection(event);
}

function handlePlaybackBegin(event) {
  if (state.providerAudioDisabled) {
    recordAudioSuppression("playback_begin_blocked_text_only");
    markDegraded("provider_audio_blocked");
    return;
  }
  const epoch = updateEpoch(firstValue(event, ["playback_epoch", "epoch"], state.playbackEpoch));
  resumePlayer().then((player) => {
    player?.node.port.postMessage({ type: "response_state", epoch, active: true });
  });
  setActivity("responding");
}

function handlePlaybackEnd(event) {
  const epoch = finiteNumber(firstValue(event, ["playback_epoch", "epoch"], state.playbackEpoch), 0, 0xffff_ffff);
  if (epoch !== null && Math.floor(epoch) === state.playbackEpoch) {
    state.player?.node.port.postMessage({ type: "response_state", epoch: state.playbackEpoch, active: false });
  }
  if (state.mic) setActivity("listening");
  else setActivity("idle");
}

function handleSafeError(event) {
  const code = safeCode(event.code);
  elements.healthBadge.textContent = code;
  elements.healthBadge.className = "badge error";
  setActivity("error");
  if (event.terminal === true) state.sessionReady = false;
  refreshButtons();
}

function handleControlFrame(rawFrame) {
  if (typeof rawFrame !== "string" || new TextEncoder().encode(rawFrame).byteLength > MAX_CONTROL_FRAME_BYTES) {
    handleSafeError({ code: "control_frame_size_invalid" });
    return;
  }
  let event;
  try {
    event = JSON.parse(rawFrame);
  } catch (_error) {
    handleSafeError({ code: "control_json_invalid" });
    return;
  }
  if (!event || typeof event !== "object" || event.protocol_version !== PROTOCOL_VERSION) {
    handleSafeError({ code: "protocol_version_unsupported" });
    return;
  }
  const type = safeCode(event.type, "control_type_unsupported");

  if (type === "session.ready") handleSessionReady(event);
  else if (type === "state.changed") {
    const phase = firstValue(event, ["state", "phase", "status"], "idle");
    const reason = safeCode(firstValue(event, ["reason", "cause"], "state_changed"));
    const epoch = firstValue(event, ["playback_epoch", "epoch"], state.playbackEpoch);
    if (reason === "speech_started" || safeCode(phase, "idle") === "speech_started") {
      clearPlayback("speech_started", epoch);
    } else {
      updateEpoch(epoch);
      setActivity(phase);
    }
    applyCounters(event);
    handleEnforcedProjection(event);
  } else if (type === "transcript.user.delta") {
    // ASR deltas are transient ingress evidence in enforced mode. Only the
    // committed final transcript may enter the QA conversation.
    if (!qwenEnforcedMode()) handleTranscript("user", event, false);
  }
  else if (type === "transcript.user.final") handleTranscript("user", event, true);
  else if (type === "transcript.assistant.delta") handleTranscript("assistant", event, false);
  else if (type === "transcript.assistant.done") handleTranscript("assistant", event, true);
  else if (type === "route.proposed") handleRouteProposal(event);
  else if (type === "route.decided") handleRouteDecision(event);
  else if (type === "shadow.state") handleShadowProjection(event, { complete: true });
  else if (type === "route.shadow.proposed") handleShadowProjection(event);
  else if (type === "route.shadow.validated") handleShadowProjection(event);
  else if (type === "route.shadow.compared") handleShadowProjection(event);
  else if (type === "route.shadow.degraded") handleShadowProjection(event, { degraded: true });
  else if (type === "control.state") handleEnforcedProjection(event, { degraded: event.degraded === true });
  else if (type === "dispatch.result") handleEnforcedProjection(event, { dispatch: true });
  else if (type === "gate.result") handleGateResult(event);
  else if (type === "slowtask.state") handleSlowTaskState(event);
  else if (type === "userpatch.accepted") handleUserPatch(event);
  else if (type === "playback.begin") handlePlaybackBegin(event);
  else if (type === "playback.clear") {
    const latency = finiteNumber(event.clear_latency_ms, 0, 60_000);
    clearPlayback(
      safeCode(firstValue(event, ["reason", "cause"], "server_clear")),
      firstValue(event, ["playback_epoch", "epoch"], state.playbackEpoch),
      latency,
    );
  } else if (type === "playback.end") handlePlaybackEnd(event);
  else if (type === "degraded") {
    markDegraded(firstValue(event, ["code", "reason"], "degraded"));
    handleEnforcedProjection(event, { degraded: true });
  }
  else if (type === "safe_error") handleSafeError(event);
  else if (type === "flow.changed") {
    applyCounters(event);
    handleEnforcedProjection(event);
  }

  if (type === "timeline.metadata") {
    const projectedType = safeCode(firstValue(event, ["event_type", "name", "event"], "timeline.metadata"));
    appendTimeline(projectedType, event);
  } else {
    appendTimeline(type, event);
  }
}

function handleSocketMessage(event) {
  if (typeof event.data === "string") {
    handleControlFrame(event.data);
    return;
  }
  if (event.data instanceof ArrayBuffer || event.data instanceof Blob) {
    if (state.providerAudioDisabled || qwenEnforcedMode()) {
      recordAudioSuppression("binary_playback_blocked_text_only");
      markDegraded("provider_audio_blocked");
      return;
    }
    try {
      enqueueAudioFrame(event.data);
    } catch (_error) {
      state.droppedOutputFrames += 1;
      elements.outputDropCount.textContent = String(state.droppedOutputFrames);
      markDegraded("audio_frame_error");
    }
  }
}

function websocketUrl() {
  const url = new URL("/ws", window.location.href);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return url.href;
}

async function connect() {
  if (state.socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.socket.readyState)) return;
  state.manualDisconnect = false;
  await closePlayer();
  resetSessionUi();
  setConnection("Connecting", "neutral");
  refreshButtons();

  const generation = ++state.socketGeneration;
  const socket = new WebSocket(websocketUrl());
  socket.binaryType = "arraybuffer";
  state.socket = socket;
  socket.addEventListener("open", () => {
    if (generation !== state.socketGeneration) return;
    setConnection("Configuring", "neutral");
    sendControl("session.configure", {
      scenario: "fast",
      playback_enabled: true,
      input_audio: { encoding: "pcm16le", sample_rate_hz: 16_000, channels: 1, frame_ms: 100 },
      output_audio: { envelope: "QFS2", encoding: "pcm16le", sample_rate_hz: 24_000, channels: 1 },
      client_mode: "qa",
    });
    // Provider/output mode is unknown until session.ready; do not pre-label a
    // real Qwen session as Fake in the local metadata timeline.
    appendTimeline("session.configure", {});
    refreshButtons();
  });
  socket.addEventListener("message", handleSocketMessage);
  socket.addEventListener("error", () => {
    if (generation !== state.socketGeneration) return;
    handleSafeError({ code: "websocket_transport_error" });
  });
  socket.addEventListener("close", async () => {
    if (generation !== state.socketGeneration) return;
    state.socket = null;
    state.sessionReady = false;
    await stopMicrophone({ notify: false });
    clearPlayback("disconnect", state.playbackEpoch + 1);
    await closePlayer();
    setConnection("Disconnected", "neutral");
    setShadowSessionStatus(elements.voiceSessionStatus, "disconnected");
    setShadowSessionStatus(elements.shadowControlStatus, "disconnected");
    if (qwenEnforcedMode()) {
      setShadowSessionStatus(elements.enforcedVoiceStatus, "disconnected");
      setShadowSessionStatus(elements.enforcedControlStatus, "disconnected");
      setEnforcedActive(true, !state.manualDisconnect);
    }
    if (!state.manualDisconnect) markDegraded("provider_disconnected");
    setActivity(state.manualDisconnect ? "idle" : "error");
    appendTimeline("session.disconnected", { degraded: !state.manualDisconnect });
    refreshButtons();
  });
}

async function disconnect() {
  state.manualDisconnect = true;
  await stopMicrophone({ notify: true });
  const socket = state.socket;
  if (socket?.readyState === WebSocket.OPEN) sendControl("disconnect");
  if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, "client_disconnect");
  refreshButtons();
}

async function interrupt() {
  if (!socketIsOpen()) return;
  const requestedEpoch = Math.min(0xffff_ffff, state.playbackEpoch + 1);
  clearPlayback("interrupt_request", requestedEpoch);
  sendControl("interrupt.request", { playback_epoch: requestedEpoch });
  appendTimeline("interrupt.request", { playback_epoch: requestedEpoch });
}

async function runScenario(scenario) {
  if (!socketIsOpen() || !state.sessionReady) return;
  await resumePlayer();
  sendControl("synthetic.turn", { scenario });
  appendTimeline("synthetic.turn", { scenario });
}

function cleanupBeforeUnload() {
  state.manualDisconnect = true;
  if (state.micFlushTimer !== null) clearTimeout(state.micFlushTimer);
  state.micFrames.length = 0;
  const mic = state.mic;
  state.mic = null;
  if (mic) {
    mic.node.port.postMessage({ type: "active", active: false });
    mic.stream.getTracks().forEach((track) => track.stop());
    mic.context.close().catch(() => {});
  }
  if (socketIsOpen()) {
    sendControl("microphone.stop");
    sendControl("disconnect");
    state.socket.close(1000, "page_unload");
  }
  const player = state.player;
  state.player = null;
  if (player) player.context.close().catch(() => {});
}

elements.connectBtn.addEventListener("click", () => connect());
elements.disconnectBtn.addEventListener("click", () => disconnect());
elements.startMicBtn.addEventListener("click", () => startMicrophone());
elements.stopMicBtn.addEventListener("click", () => stopMicrophone());
elements.interruptBtn.addEventListener("click", () => interrupt());
elements.clearConversationBtn.addEventListener("click", resetConversation);
elements.clearTimelineBtn.addEventListener("click", clearTimeline);
elements.scenarioControls.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-scenario]");
  if (button) runScenario(button.dataset.scenario);
});
window.addEventListener("pagehide", cleanupBeforeUnload, { once: true });
window.addEventListener("beforeunload", cleanupBeforeUnload, { once: true });

resetShadowUi();
resetEnforcedUi();
setOutputMode("fake");
setActivity("idle");
refreshButtons();
