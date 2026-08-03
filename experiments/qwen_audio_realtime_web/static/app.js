const AUDIO_HEADER_BYTES = 8;
const PLAYER_SOURCE_SAMPLE_RATE = 24_000;
const PLAYBACK_TELEMETRY_INTERVAL_MS = 1_000;
const MIC_QUEUE_LIMIT = 5;
const WS_HIGH_WATER_BYTES = 64 * 1024;
const MAX_TIMELINE_ROWS = 80;
const MAX_CONVERSATION_TURNS = 32;
const MAX_CONVERSATION_CHARS = 32_000;
const MAX_BUBBLE_CHARS = 6_000;
const CONVERSATION_BOTTOM_SLOP_PX = 48;
const HEARTBEAT_INTERVAL_MS = 15_000;

const byId = (id) => document.getElementById(id);

const elements = {
  connect: byId("connectBtn"),
  disconnect: byId("disconnectBtn"),
  startMic: byId("startMicBtn"),
  stopMic: byId("stopMicBtn"),
  cancel: byId("cancelBtn"),
  clearTimeline: byId("clearTimelineBtn"),
  provider: byId("providerSelect"),
  mode: byId("modeSelect"),
  modeNotice: byId("modeNotice"),
  connectionBadge: byId("connectionBadge"),
  outputModeBadge: byId("outputModeBadge"),
  qualityBadge: byId("qualityBadge"),
  activityBadge: byId("activityBadge"),
  micPermission: byId("micPermission"),
  inputLevel: byId("inputLevel"),
  inputLevelText: byId("inputLevelText"),
  dropCount: byId("dropCount"),
  conversationTranscript: byId("conversationTranscript"),
  conversationLatest: byId("conversationLatestBtn"),
  metricUserTranscript: byId("metricUserTranscript"),
  metricAssistantTranscript: byId("metricAssistantTranscript"),
  metricAudio: byId("metricAudio"),
  metricClear: byId("metricClear"),
  playbackBuffer: byId("playbackBuffer"),
  outputDropCount: byId("outputDropCount"),
  gatewayDropCount: byId("gatewayDropCount"),
  timeline: byId("timeline"),
};

const state = {
  socket: null,
  connecting: false,
  intentionallyClosedSockets: new WeakSet(),
  providerMode: null,
  providerSessionReady: false,
  flushTimer: null,
  heartbeatTimer: null,
  pendingMicFrames: [],
  localDroppedInput: 0,
  remoteDroppedInput: 0,
  remoteDroppedOutput: 0,
  playerBufferedSamples: 0,
  playerHighWaterSamples: 0,
  playerEpochHighWaterSamples: 0,
  playerSoftCapacitySamples: 0,
  playerDroppedOutputSamples: 0,
  playerUnderflowCount: 0,
  playerCapacitySamples: 0,
  playerBacklogHigh: false,
  lastPlaybackTelemetryAt: 0,
  micActive: false,
  micOperation: 0,
  mediaStream: null,
  micContext: null,
  micSource: null,
  micNode: null,
  silentGain: null,
  playerContext: null,
  playerNode: null,
  playbackActive: false,
  assistantResponding: false,
  currentEpoch: 0,
  pendingEpochAck: false,
  clearToken: 0,
  pendingClears: new Map(),
  lastAudioTimelineAt: 0,
  conversationTurns: [],
  conversationNodes: new Map(),
  conversationTurnId: 0,
  activeConversationTurnId: null,
  conversationAutoFollow: true,
  conversationFollowFrame: null,
  turn: {
    speechStartedAt: null,
    speechStoppedAt: null,
    firstUserTranscriptSeen: false,
    firstAssistantTranscriptSeen: false,
    firstAudioSeen: false,
    speechClearMeasured: false,
    speechSequence: 0,
  },
};

function socketIsOpen() {
  return state.socket?.readyState === WebSocket.OPEN;
}

function isSpeakerSafePaused() {
  return elements.mode.value === "speaker_safe"
    && (state.assistantResponding || state.playbackActive);
}

function boundedTail(value, limit) {
  if (value.length <= limit) {
    return value;
  }
  return `…${value.slice(-(limit - 1))}`;
}

function setConnectionBadge(text, variant) {
  elements.connectionBadge.textContent = text;
  elements.connectionBadge.className = `badge ${variant}`;
}

function setOutputMode(rawMode, degraded = false, capabilities = null) {
  const normalized = typeof rawMode === "string" ? rawMode.toLowerCase() : "";
  const capabilityProvider = typeof capabilities?.provider === "string"
    ? capabilities.provider.toLowerCase()
    : "";
  let providerMode = null;
  if (normalized === "mock" || normalized === "fake") {
    providerMode = "fake";
  } else if (normalized === "real") {
    providerMode = "real";
  } else if (capabilities?.mocked === true || capabilityProvider.includes("fake")) {
    providerMode = "fake";
  } else if (capabilities?.mocked === false || capabilityProvider.includes("aliyun")) {
    providerMode = "real";
  } else {
    providerMode = state.providerMode
      || (["fake", "real"].includes(elements.provider.value) ? elements.provider.value : "unknown");
  }

  const isDegraded = degraded || normalized === "degraded" || normalized === "fallback";
  state.providerMode = providerMode;
  elements.provider.value = providerMode;
  let label = providerMode;
  if (normalized === "mock" && !isDegraded) {
    label = "fake · mock";
  } else if (normalized === "fallback") {
    label = `${providerMode} · fallback`;
  } else if (isDegraded) {
    label = `${providerMode} · degraded`;
  }
  elements.outputModeBadge.textContent = label;
  elements.outputModeBadge.className = `badge ${isDegraded ? "degraded" : providerMode}`;
  if (isDegraded) {
    markDegraded();
  }
}

function markDegraded() {
  elements.qualityBadge.textContent = "degraded";
  elements.qualityBadge.className = "badge degraded";
}

function resetSessionUi() {
  state.providerMode = null;
  state.providerSessionReady = false;
  elements.provider.value = "unknown";
  state.localDroppedInput = 0;
  state.remoteDroppedInput = 0;
  state.remoteDroppedOutput = 0;
  state.playerBufferedSamples = 0;
  state.playerHighWaterSamples = 0;
  state.playerEpochHighWaterSamples = 0;
  state.playerSoftCapacitySamples = 0;
  state.playerDroppedOutputSamples = 0;
  state.playerUnderflowCount = 0;
  state.playerCapacitySamples = 0;
  state.playerBacklogHigh = false;
  state.lastPlaybackTelemetryAt = 0;
  state.currentEpoch = 0;
  state.pendingEpochAck = false;
  state.pendingClears.clear();
  state.lastAudioTimelineAt = 0;
  resetConversation();
  state.turn.speechStartedAt = null;
  state.turn.speechStoppedAt = null;
  state.turn.firstUserTranscriptSeen = false;
  state.turn.firstAssistantTranscriptSeen = false;
  state.turn.firstAudioSeen = false;
  state.turn.speechClearMeasured = false;
  state.turn.speechSequence = 0;
  elements.qualityBadge.textContent = "healthy";
  elements.qualityBadge.className = "badge healthy";
  elements.outputModeBadge.textContent = "awaiting server";
  elements.outputModeBadge.className = "badge neutral";
  elements.metricUserTranscript.textContent = "—";
  elements.metricAssistantTranscript.textContent = "—";
  elements.metricAudio.textContent = "—";
  elements.metricClear.textContent = "—";
  elements.micPermission.textContent = "not_requested";
  refreshDropCount();
  refreshPlaybackTelemetry();
  clearTimeline();
}

function setActivity(rawActivity) {
  const normalized = typeof rawActivity === "string" ? rawActivity.toLowerCase() : "idle";
  const mapping = {
    idle: ["Idle", "idle"],
    connected: ["Connected", "idle"],
    listening: ["Listening", "listening"],
    responding: ["Responding", "responding"],
    interrupted: ["Interrupted", "interrupted"],
    error: ["Error", "error"],
  };
  const [label, variant] = mapping[normalized] || mapping.connected;
  elements.activityBadge.textContent = label;
  elements.activityBadge.className = `activity ${variant}`;
}

function refreshButtons() {
  const connected = socketIsOpen();
  elements.connect.disabled = connected || state.connecting;
  elements.disconnect.disabled = !connected && !state.connecting;
  elements.startMic.disabled = !connected || !state.providerSessionReady || state.micActive;
  elements.stopMic.disabled = !state.micActive;
  elements.cancel.disabled = !connected;
  elements.provider.disabled = true;
}

function refreshModeNotice() {
  if (elements.mode.value === "speaker_safe") {
    elements.modeNotice.className = "notice speaker";
    elements.modeNotice.innerHTML = "<strong>音箱安全模式。</strong> assistant 正在响应或播放器仍有音频时，麦克风不会上传；该模式不支持播放期间打断，也不属于 full duplex。";
  } else {
    elements.modeNotice.className = "notice headset";
    elements.modeNotice.innerHTML = "<strong>请佩戴耳机。</strong> headset_full_duplex 会持续上传麦克风音频并支持插话；浏览器回声消除不等同于 playback-reference AEC。";
  }
  refreshMicPermissionLabel();
}

function refreshMicPermissionLabel() {
  if (!state.micActive) {
    return;
  }
  elements.micPermission.textContent = isSpeakerSafePaused()
    ? "active_paused_for_playback"
    : "active";
}

function safeReference(value) {
  if (typeof value !== "string" && typeof value !== "number") {
    return null;
  }
  const normalized = String(value);
  return /^[A-Za-z0-9_.:-]{1,64}$/.test(normalized) ? normalized : null;
}

function finiteNumber(value, minimum = 0, maximum = 3_600_000) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= minimum && parsed <= maximum ? parsed : null;
}

function timelineMetadata(source = {}) {
  const metadata = [];
  const byteLength = finiteNumber(source.byte_length ?? source.bytes, 0, 16 * 1024 * 1024);
  const epoch = finiteNumber(source.playback_epoch ?? source.epoch, 0, 0xffff_ffff);
  const latency = finiteNumber(source.latency_ms ?? source.latency, 0);
  const droppedInput = finiteNumber(source.dropped_input_frames, 0, Number.MAX_SAFE_INTEGER);
  const droppedOutputMessages = finiteNumber(
    source.dropped_output_messages,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const droppedAudioMessagesDelta = finiteNumber(
    source.dropped_audio_messages_delta,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const droppedControlMessagesDelta = finiteNumber(
    source.dropped_control_messages_delta,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const droppedOutputSamples = finiteNumber(
    source.total_dropped_samples ?? source.dropped_output_samples,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const droppedOutputMs = finiteNumber(source.dropped_output_ms, 0, Number.MAX_SAFE_INTEGER);
  const bufferedSamples = finiteNumber(source.buffered_samples, 0, Number.MAX_SAFE_INTEGER);
  const bufferedMs = finiteNumber(source.buffered_ms, 0, Number.MAX_SAFE_INTEGER);
  const highWaterSamples = finiteNumber(source.high_water_samples, 0, Number.MAX_SAFE_INTEGER);
  const epochHighWaterSamples = finiteNumber(
    source.epoch_high_water_samples,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const highWaterMs = finiteNumber(source.high_water_ms, 0, Number.MAX_SAFE_INTEGER);
  const softCapacitySamples = finiteNumber(
    source.soft_capacity_samples,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const hardCapacitySamples = finiteNumber(
    source.hard_capacity_samples ?? source.capacity_samples,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const sampleRate = finiteNumber(source.sample_rate, 1, 384_000);
  const totalReceivedSamples = finiteNumber(
    source.total_received_samples,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const underflowCount = finiteNumber(source.underflow_count, 0, Number.MAX_SAFE_INTEGER);
  const outputQueueDepth = finiteNumber(source.output_queue_depth, 0, Number.MAX_SAFE_INTEGER);
  const outputQueueHighWater = finiteNumber(
    source.output_queue_high_water,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const outputQueueCapacity = finiteNumber(
    source.output_queue_capacity,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const count = finiteNumber(source.count, 0, Number.MAX_SAFE_INTEGER);
  const safeRef = safeReference(source.response_ref ?? source.response_id ?? source.session_ref ?? source.session_id);
  const outputMode = safeReference(source.output_mode);
  const status = safeReference(source.status ?? source.state);
  const reason = safeReference(source.reason);

  if (byteLength !== null) metadata.push(`bytes=${Math.round(byteLength)}`);
  if (epoch !== null) metadata.push(`epoch=${Math.round(epoch)}`);
  if (latency !== null) metadata.push(`latency_ms=${Math.round(latency)}`);
  if (droppedInput !== null) metadata.push(`input_dropped=${Math.round(droppedInput)}`);
  if (droppedOutputMessages !== null) metadata.push(`gateway_output_dropped=${Math.round(droppedOutputMessages)}`);
  if (droppedAudioMessagesDelta !== null) metadata.push(`audio_drop_delta=${Math.round(droppedAudioMessagesDelta)}`);
  if (droppedControlMessagesDelta !== null) metadata.push(`control_drop_delta=${Math.round(droppedControlMessagesDelta)}`);
  if (droppedOutputSamples !== null) metadata.push(`player_dropped_samples=${Math.round(droppedOutputSamples)}`);
  if (droppedOutputMs !== null) metadata.push(`player_dropped_ms=${Math.round(droppedOutputMs)}`);
  if (bufferedSamples !== null) metadata.push(`buffered_samples=${Math.round(bufferedSamples)}`);
  if (bufferedMs !== null) metadata.push(`buffered_ms=${Math.round(bufferedMs)}`);
  if (highWaterSamples !== null) metadata.push(`high_water_samples=${Math.round(highWaterSamples)}`);
  if (epochHighWaterSamples !== null) metadata.push(`epoch_peak_samples=${Math.round(epochHighWaterSamples)}`);
  if (highWaterMs !== null) metadata.push(`high_water_ms=${Math.round(highWaterMs)}`);
  if (softCapacitySamples !== null) metadata.push(`soft_capacity_samples=${Math.round(softCapacitySamples)}`);
  if (hardCapacitySamples !== null) metadata.push(`hard_capacity_samples=${Math.round(hardCapacitySamples)}`);
  if (sampleRate !== null) metadata.push(`sample_rate=${Math.round(sampleRate)}`);
  if (totalReceivedSamples !== null) metadata.push(`received_samples=${Math.round(totalReceivedSamples)}`);
  if (underflowCount !== null) metadata.push(`underflows=${Math.round(underflowCount)}`);
  if (outputQueueDepth !== null) metadata.push(`queue_depth=${Math.round(outputQueueDepth)}`);
  if (outputQueueHighWater !== null) metadata.push(`queue_high_water=${Math.round(outputQueueHighWater)}`);
  if (outputQueueCapacity !== null) metadata.push(`queue_capacity=${Math.round(outputQueueCapacity)}`);
  if (count !== null) metadata.push(`count=${Math.round(count)}`);
  if (safeRef !== null) metadata.push(`ref=${safeRef}`);
  if (outputMode !== null) metadata.push(`output_mode=${outputMode}`);
  if (status !== null) metadata.push(`status=${status}`);
  if (reason !== null) metadata.push(`reason=${reason}`);
  return metadata.join(" ");
}

function appendTimeline(rawType, metadata = {}) {
  const type = safeReference(rawType) || "event";
  const placeholder = elements.timeline.querySelector(".placeholder");
  placeholder?.remove();

  const row = document.createElement("li");
  const time = document.createElement("time");
  const name = document.createElement("span");
  const details = document.createElement("span");
  time.textContent = new Date().toLocaleTimeString([], { hour12: false });
  name.textContent = type;
  details.textContent = timelineMetadata(metadata);
  details.className = "meta";
  row.append(time, name, details);
  elements.timeline.append(row);

  while (elements.timeline.children.length > MAX_TIMELINE_ROWS) {
    elements.timeline.firstElementChild?.remove();
  }
  elements.timeline.scrollTop = elements.timeline.scrollHeight;
}

function clearTimeline() {
  elements.timeline.replaceChildren();
  const placeholder = document.createElement("li");
  placeholder.className = "placeholder";
  placeholder.textContent = "等待事件";
  elements.timeline.append(placeholder);
}

function eventText(event) {
  for (const value of [event.delta, event.transcript, event.text]) {
    if (typeof value === "string") {
      return value.slice(0, 4_096);
    }
  }
  return "";
}

const MESSAGE_STATUS_LABELS = Object.freeze({
  listening: "聆听中",
  streaming: "实时生成",
  processing: "整理中",
  final: "已确认",
  unavailable: "无转写",
  waiting: "等待回复",
  text_done: "字幕完成",
  completed: "已完成",
  interrupt_pending: "中断中",
  cancel_pending: "取消中",
  interrupted: "已打断",
  cancelled: "已取消",
  error: "错误",
});

function resetConversation() {
  if (state.conversationFollowFrame !== null) {
    window.cancelAnimationFrame(state.conversationFollowFrame);
  }
  state.conversationTurns.length = 0;
  state.conversationNodes.clear();
  state.conversationTurnId = 0;
  state.activeConversationTurnId = null;
  state.conversationAutoFollow = true;
  state.conversationFollowFrame = null;
  elements.conversationTranscript.replaceChildren();
  const placeholder = document.createElement("p");
  placeholder.className = "conversation-placeholder";
  placeholder.textContent = "尚无对话。连接并开始讲话后，实时字幕会显示在这里。";
  elements.conversationTranscript.append(placeholder);
  elements.conversationLatest.hidden = true;
}

function conversationNearBottom() {
  const panel = elements.conversationTranscript;
  return panel.scrollHeight - panel.scrollTop - panel.clientHeight <= CONVERSATION_BOTTOM_SLOP_PX;
}

function updateConversationFollowUi() {
  elements.conversationLatest.hidden = state.conversationAutoFollow;
}

function scheduleConversationFollow() {
  if (!state.conversationAutoFollow || state.conversationFollowFrame !== null) {
    return;
  }
  state.conversationFollowFrame = window.requestAnimationFrame(() => {
    state.conversationFollowFrame = null;
    if (state.conversationAutoFollow) {
      elements.conversationTranscript.scrollTop = elements.conversationTranscript.scrollHeight;
    }
  });
}

function handleConversationScroll() {
  state.conversationAutoFollow = conversationNearBottom();
  updateConversationFollowUi();
}

function scrollConversationToLatest() {
  state.conversationAutoFollow = true;
  updateConversationFollowUi();
  elements.conversationTranscript.scrollTop = elements.conversationTranscript.scrollHeight;
}

function messageFallback(kind, status) {
  if (kind === "user") {
    if (status === "listening") return "正在聆听…";
    if (status === "processing") return "正在整理用户转写…";
    if (status === "unavailable") return "未收到可显示的用户转写。";
    return "等待用户转写…";
  }
  if (status === "interrupted" || status === "interrupt_pending") return "回复已因用户插话中止。";
  if (status === "cancelled" || status === "cancel_pending") return "回复已取消。";
  if (status === "error") return "本轮回复失败。";
  if (status === "completed" || status === "text_done") return "本轮没有可显示的助手字幕。";
  return "等待助手回复…";
}

function createMessageNode(kind) {
  const message = document.createElement("div");
  message.className = `message ${kind}`;
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const role = document.createElement("span");
  role.className = "message-role";
  role.textContent = kind === "user" ? "你" : "助手";
  const status = document.createElement("span");
  status.className = "message-status";
  const text = document.createElement("p");
  text.className = "message-text";
  meta.append(role, status);
  bubble.append(meta, text);
  message.append(bubble);
  return { message, status, text };
}

function ensureConversationNode(turn) {
  let nodes = state.conversationNodes.get(turn.id);
  if (nodes) {
    return nodes;
  }
  elements.conversationTranscript.querySelector(".conversation-placeholder")?.remove();
  const turnNode = document.createElement("article");
  turnNode.className = "conversation-turn";
  turnNode.dataset.turnId = String(turn.id);
  turnNode.dataset.turnSequence = String(turn.sequence);
  turnNode.setAttribute("aria-label", `对话第 ${turn.sequence} 轮`);
  const user = createMessageNode("user");
  const assistant = createMessageNode("assistant");
  turnNode.append(user.message, assistant.message);
  elements.conversationTranscript.append(turnNode);
  nodes = { turn: turnNode, user, assistant };
  state.conversationNodes.set(turn.id, nodes);
  return nodes;
}

function totalConversationChars() {
  return state.conversationTurns.reduce(
    (total, turn) => total + turn.user.text.length + turn.assistant.text.length,
    0,
  );
}

function pruneConversation() {
  const panel = elements.conversationTranscript;
  const beforeHeight = panel.scrollHeight;
  const beforeTop = panel.scrollTop;
  let removed = false;
  while (
    state.conversationTurns.length > MAX_CONVERSATION_TURNS
    || (state.conversationTurns.length > 1 && totalConversationChars() > MAX_CONVERSATION_CHARS)
  ) {
    const oldest = state.conversationTurns.shift();
    const nodes = state.conversationNodes.get(oldest.id);
    nodes?.turn.remove();
    state.conversationNodes.delete(oldest.id);
    removed = true;
  }
  if (removed && !state.conversationAutoFollow) {
    const removedHeight = Math.max(0, beforeHeight - panel.scrollHeight);
    panel.scrollTop = Math.max(0, beforeTop - removedHeight);
  }
}

function updateMessageNode(nodes, message, kind) {
  const status = MESSAGE_STATUS_LABELS[message.status] ? message.status : "error";
  nodes.message.dataset.status = status;
  const safeReason = safeReference(message.reason);
  nodes.status.textContent = safeReason
    ? `${MESSAGE_STATUS_LABELS[status]} · ${safeReason}`
    : MESSAGE_STATUS_LABELS[status];
  // Transcript content is always assigned with textContent. Provider text is
  // never interpreted as HTML, attributes, or CSS selectors.
  nodes.text.textContent = message.text || messageFallback(kind, status);
}

function renderConversationTurn(turn) {
  pruneConversation();
  if (!state.conversationTurns.includes(turn)) {
    return;
  }
  const nodes = ensureConversationNode(turn);
  updateMessageNode(nodes.user, turn.user, "user");
  updateMessageNode(nodes.assistant, turn.assistant, "assistant");
  scheduleConversationFollow();
}

function createConversationTurn(sequence = state.turn.speechSequence || 1) {
  const turn = {
    id: ++state.conversationTurnId,
    sequence: Math.max(1, Number.isInteger(sequence) ? sequence : 1),
    user: {
      text: "",
      status: "listening",
      textFrozen: false,
    },
    assistant: {
      text: "",
      status: "waiting",
      textFrozen: false,
      terminal: false,
      responseRef: null,
      epoch: null,
      reason: null,
    },
  };
  state.conversationTurns.push(turn);
  state.activeConversationTurnId = turn.id;
  renderConversationTurn(turn);
  return turn;
}

function conversationTurnById(id) {
  return state.conversationTurns.find((turn) => turn.id === id) || null;
}

function latestConversationTurn() {
  return state.conversationTurns.at(-1) || null;
}

function activeUserTurn() {
  const active = conversationTurnById(state.activeConversationTurnId);
  if (active && !active.user.textFrozen) {
    return active;
  }
  return [...state.conversationTurns].reverse().find((turn) => !turn.user.textFrozen) || null;
}

function ensureUserTurn() {
  return activeUserTurn() || createConversationTurn();
}

function responseRefFromEvent(event = {}) {
  return safeReference(event.response_ref ?? event.response_id);
}

function responseEpochFromEvent(event = {}) {
  return normalizeEpoch(
    event.response_epoch ?? event.playback_epoch ?? event.epoch,
  );
}

function findAssistantTurn(event = {}, { allowFallback = true } = {}) {
  const responseRef = responseRefFromEvent(event);
  const epoch = responseEpochFromEvent(event);
  const reversed = [...state.conversationTurns].reverse();
  if (responseRef) {
    const byRef = reversed.find((turn) => turn.assistant.responseRef === responseRef);
    if (byRef) return byRef;
  }
  if (epoch !== null) {
    const byEpoch = reversed.find((turn) => turn.assistant.epoch === epoch);
    if (byEpoch) return byEpoch;
  }
  if (!allowFallback) {
    return null;
  }
  const active = conversationTurnById(state.activeConversationTurnId);
  if (active && !active.assistant.terminal) {
    return active;
  }
  return reversed.find((turn) => !turn.assistant.terminal) || null;
}

function ensureAssistantTurn(event = {}) {
  const responseRef = responseRefFromEvent(event);
  const epoch = responseEpochFromEvent(event);
  let turn = findAssistantTurn(event, { allowFallback: false });
  let createdWithoutUserBoundary = false;
  if (!turn) {
    const candidate = findAssistantTurn(event);
    const boundToDifferentResponse = candidate?.assistant.responseRef
      && responseRef
      && candidate.assistant.responseRef !== responseRef;
    if (!candidate || candidate.assistant.terminal || boundToDifferentResponse) {
      turn = createConversationTurn(epoch ?? (state.turn.speechSequence || 1));
      createdWithoutUserBoundary = true;
    } else {
      turn = candidate;
    }
  }
  if (!turn.user.text && turn.user.status === "listening" && createdWithoutUserBoundary) {
    turn.user.status = "unavailable";
    turn.user.textFrozen = true;
  }
  if (responseRef && !turn.assistant.responseRef) turn.assistant.responseRef = responseRef;
  if (epoch !== null && turn.assistant.epoch === null) turn.assistant.epoch = epoch;
  state.activeConversationTurnId = turn.id;
  return turn;
}

function finalizeOpenUserTurn() {
  const turn = activeUserTurn();
  if (!turn) return;
  turn.user.textFrozen = true;
  turn.user.status = turn.user.text ? "final" : "unavailable";
  renderConversationTurn(turn);
}

function setAssistantStatus(turn, status, reason = null, { terminal = false } = {}) {
  if (!turn) return false;
  const assistant = turn.assistant;
  if (assistant.terminal) {
    // Duplicate response.done is idempotent. A late completed event must never
    // overwrite a previously observed interruption, cancellation, or error.
    return assistant.status === status;
  }
  if (assistant.status === "interrupted" && status === "cancelled") {
    assistant.terminal = true;
    assistant.textFrozen = true;
    renderConversationTurn(turn);
    return true;
  }
  assistant.status = MESSAGE_STATUS_LABELS[status] ? status : "error";
  assistant.reason = safeReference(reason);
  if (terminal) {
    assistant.terminal = true;
    assistant.textFrozen = true;
  }
  renderConversationTurn(turn);
  return true;
}

function markLatestOpenAssistant(status, reason, options = {}) {
  const turn = [...state.conversationTurns]
    .reverse()
    .find((candidate) => !candidate.assistant.terminal);
  if (!turn) return false;
  return setAssistantStatus(turn, status, reason, options);
}

function markAllOpenAssistants(status, reason) {
  for (const turn of state.conversationTurns) {
    if (!turn.assistant.terminal) {
      setAssistantStatus(turn, status, reason, { terminal: true });
    }
  }
}

function markAllOpenAssistantsError(reason = "transport_aborted") {
  markAllOpenAssistants("error", reason);
}

function addTranscriptDelta(kind, event) {
  if (kind === "user") {
    const turn = ensureUserTurn();
    if (turn.user.textFrozen) return;
    const confirmed = typeof event.delta === "string"
      ? event.delta.slice(0, MAX_BUBBLE_CHARS)
      : eventText(event);
    const hasStash = typeof event.stash === "string";
    const stash = hasStash ? event.stash.slice(0, MAX_BUBBLE_CHARS) : "";
    if (!confirmed && !stash) return;
    // Qwen user transcript events have no stable turn/item ref in this spike.
    // Their association is therefore spike-local temporal best effort.
    turn.user.text = hasStash
      ? boundedTail(confirmed + stash, MAX_BUBBLE_CHARS)
      : boundedTail(turn.user.text + confirmed, MAX_BUBBLE_CHARS);
    turn.user.status = "streaming";
    renderConversationTurn(turn);
    observeFirstUserTranscript();
    setMetric(elements.metricUserTranscript, event.latency_ms);
    return;
  }

  const delta = eventText(event);
  if (!delta) return;
  const turn = ensureAssistantTurn(event);
  if (turn.assistant.textFrozen || turn.assistant.terminal) return;
  turn.assistant.text = boundedTail(turn.assistant.text + delta, MAX_BUBBLE_CHARS);
  turn.assistant.status = "streaming";
  renderConversationTurn(turn);
  observeFirstAssistantTranscript();
  setMetric(elements.metricAssistantTranscript, event.latency_ms);
}

function commitTranscript(kind, event = {}) {
  const supplied = eventText(event);
  if (kind === "user") {
    const turn = ensureUserTurn();
    if (!turn.user.textFrozen) {
      if (supplied) turn.user.text = boundedTail(supplied, MAX_BUBBLE_CHARS);
      turn.user.textFrozen = true;
      turn.user.status = turn.user.text ? "final" : "unavailable";
      renderConversationTurn(turn);
    }
    observeFirstUserTranscript();
    setMetric(elements.metricUserTranscript, event.latency_ms);
    return turn;
  }

  const turn = ensureAssistantTurn(event);
  if (!turn.assistant.textFrozen && !turn.assistant.terminal) {
    if (supplied) turn.assistant.text = boundedTail(supplied, MAX_BUBBLE_CHARS);
    turn.assistant.textFrozen = true;
    turn.assistant.status = "text_done";
    renderConversationTurn(turn);
  }
  observeFirstAssistantTranscript();
  setMetric(elements.metricAssistantTranscript, event.latency_ms);
  return turn;
}

function setMetric(element, rawValue) {
  const value = finiteNumber(rawValue);
  if (value !== null) {
    element.textContent = `${Math.round(value)} ms`;
  }
}

function observeFirstUserTranscript() {
  if (state.turn.firstUserTranscriptSeen) {
    return;
  }
  state.turn.firstUserTranscriptSeen = true;
  if (state.turn.speechStartedAt !== null) {
    setMetric(elements.metricUserTranscript, performance.now() - state.turn.speechStartedAt);
  }
}

function observeFirstAssistantTranscript() {
  if (state.turn.firstAssistantTranscriptSeen) {
    return;
  }
  state.turn.firstAssistantTranscriptSeen = true;
  if (state.turn.speechStoppedAt !== null) {
    setMetric(elements.metricAssistantTranscript, performance.now() - state.turn.speechStoppedAt);
  }
}

function observeFirstAudio() {
  if (state.turn.firstAudioSeen) {
    return;
  }
  state.turn.firstAudioSeen = true;
  if (state.turn.speechStoppedAt !== null) {
    setMetric(elements.metricAudio, performance.now() - state.turn.speechStoppedAt);
  }
}

function applyMetrics(event) {
  const metrics = event.metrics && typeof event.metrics === "object" ? event.metrics : event;
  setMetric(
    elements.metricUserTranscript,
    metrics.first_user_transcript_ms
      ?? metrics.speech_started_to_first_user_transcript_ms
      ?? metrics.user_transcript_first_delta_ms,
  );
  setMetric(
    elements.metricAssistantTranscript,
    metrics.speech_stopped_to_first_assistant_transcript_ms
      ?? metrics.assistant_transcript_first_delta_ms,
  );
  setMetric(
    elements.metricAudio,
    metrics.speech_stopped_to_first_audio_ms
      ?? metrics.assistant_audio_first_delta_ms,
  );
  setMetric(
    elements.metricClear,
    metrics.speech_started_to_playback_cleared_ms
      ?? metrics.playback_clear_ms,
  );
}

function resetTurnAtSpeechStart(startedAt = performance.now()) {
  finalizeOpenUserTurn();
  state.turn.speechSequence += 1;
  state.turn.speechStartedAt = startedAt;
  state.turn.speechStoppedAt = null;
  state.turn.firstUserTranscriptSeen = false;
  state.turn.firstAssistantTranscriptSeen = false;
  state.turn.firstAudioSeen = false;
  state.turn.speechClearMeasured = false;
  createConversationTurn(state.turn.speechSequence);
}

function markSpeechStopped() {
  state.turn.speechStoppedAt = performance.now();
  state.turn.firstAssistantTranscriptSeen = false;
  state.turn.firstAudioSeen = false;
  const turn = activeUserTurn();
  if (turn && !turn.user.textFrozen) {
    turn.user.status = "processing";
    renderConversationTurn(turn);
  }
  if (state.micActive) {
    setActivity("listening");
  }
}

function normalizeEpoch(rawEpoch) {
  if (rawEpoch === null || rawEpoch === undefined || rawEpoch === "") {
    return null;
  }
  const parsed = Number(rawEpoch);
  return Number.isInteger(parsed) && parsed >= 0 && parsed <= 0xffff_ffff ? parsed : null;
}

function clearPlayback(reason, rawEpoch, options = {}) {
  const providedEpoch = normalizeEpoch(rawEpoch);
  if (providedEpoch !== null && providedEpoch < state.currentEpoch) {
    appendTimeline("playback.clear.stale", { epoch: providedEpoch });
    return false;
  }

  if (providedEpoch !== null) {
    state.currentEpoch = providedEpoch;
    state.pendingEpochAck = false;
  } else if (options.acknowledgesLocalAdvance && state.pendingEpochAck) {
    state.pendingEpochAck = false;
  } else {
    state.currentEpoch = (state.currentEpoch + 1) >>> 0;
    state.pendingEpochAck = Boolean(options.expectServerAck);
  }

  const startedAt = performance.now();
  const token = ++state.clearToken;
  state.pendingClears.set(token, {
    startedAt: finiteNumber(options.metricStartedAt, 0, Number.MAX_SAFE_INTEGER) ?? startedAt,
    measureSpeechClear: Boolean(options.measureSpeechClear),
    speechSequence: state.turn.speechSequence,
  });
  while (state.pendingClears.size > 8) {
    state.pendingClears.delete(state.pendingClears.keys().next().value);
  }

  if (state.playerNode) {
    state.playerNode.port.postMessage({
      type: "clear",
      epoch: state.currentEpoch,
      token,
    });
  } else {
    finishPlaybackClear(token, state.currentEpoch);
  }
  state.playbackActive = false;
  state.assistantResponding = false;
  refreshMicPermissionLabel();
  appendTimeline("playback.clear", {
    epoch: state.currentEpoch,
    status: safeReference(reason) || "clear",
  });
  return true;
}

function finishPlaybackClear(token, epoch) {
  const pending = state.pendingClears.get(token);
  if (!pending) {
    return;
  }
  state.pendingClears.delete(token);
  const latency = performance.now() - pending.startedAt;
  if (
    pending.measureSpeechClear
    && pending.speechSequence === state.turn.speechSequence
    && !state.turn.speechClearMeasured
  ) {
    setMetric(elements.metricClear, latency);
    state.turn.speechClearMeasured = true;
  }
  appendTimeline("playback.cleared.local", { epoch, latency_ms: latency });
}

function beginSpeechStarted(rawEpoch, receivedAt = performance.now()) {
  const providedEpoch = normalizeEpoch(rawEpoch);
  if (providedEpoch !== null && providedEpoch < state.currentEpoch) {
    clearPlayback("speech_started", providedEpoch);
    return false;
  }
  // Capture the old bubble before resetTurnAtSpeechStart creates the next
  // User -> Assistant group. Otherwise the clear could annotate the new
  // waiting assistant instead of the response being interrupted.
  const previousAssistantTurn = [...state.conversationTurns]
    .reverse()
    .find((turn) => !turn.assistant.terminal) || null;
  const interrupted = Boolean(previousAssistantTurn)
    && (state.assistantResponding || state.playbackActive || previousAssistantTurn.assistant.status !== "waiting");
  if (previousAssistantTurn) {
    setAssistantStatus(previousAssistantTurn, "interrupt_pending", "speech_started");
  }
  resetTurnAtSpeechStart(receivedAt);
  const accepted = clearPlayback("speech_started", rawEpoch, {
    expectServerAck: true,
    measureSpeechClear: true,
    metricStartedAt: receivedAt,
  });
  if (!accepted) {
    return false;
  }
  if (previousAssistantTurn) {
    setAssistantStatus(previousAssistantTurn, "interrupted", "speech_started", { terminal: true });
  }
  setActivity(interrupted ? "interrupted" : "listening");
  return true;
}

function beginAssistantResponse(event = {}) {
  const epoch = responseEpochFromEvent(event);
  if (epoch !== null && epoch < state.currentEpoch) {
    appendTimeline("playback.started.stale", { epoch });
    return;
  }
  if (epoch !== null && epoch > state.currentEpoch) {
    clearPlayback("response_epoch", epoch);
  } else if (epoch === null && !state.assistantResponding && !state.playbackActive) {
    clearPlayback("response_started", null);
  }
  void resumePlayerContextBestEffort("response_started");
  const turn = ensureAssistantTurn(event);
  if (!turn.assistant.textFrozen && !turn.assistant.terminal) {
    turn.assistant.status = "streaming";
  }
  state.activeConversationTurnId = turn.id;
  renderConversationTurn(turn);
  state.assistantResponding = true;
  setPlayerResponseState(true);
  setActivity("responding");
  refreshMicPermissionLabel();
  if (isSpeakerSafePaused()) {
    state.pendingMicFrames.length = 0;
  }
}

function finishAssistantResponse(event = {}) {
  const completionOnly = event.completion_only === true;
  const turn = findAssistantTurn(event, { allowFallback: !completionOnly });
  if (!turn) {
    return;
  }
  const wasTerminal = turn.assistant.terminal;
  if (!turn.assistant.textFrozen && !turn.assistant.terminal) {
    const supplied = eventText(event);
    if (supplied) turn.assistant.text = boundedTail(supplied, MAX_BUBBLE_CHARS);
    turn.assistant.textFrozen = true;
  }
  const rawStatus = String(event.status ?? event.state ?? "unknown").toLowerCase();
  let bubbleStatus = "error";
  if (rawStatus === "completed") {
    bubbleStatus = "completed";
  } else if (rawStatus === "cancelled") {
    bubbleStatus = ["interrupt_pending", "interrupted"].includes(turn.assistant.status)
      ? "interrupted"
      : "cancelled";
  } else if (rawStatus === "interrupted") {
    bubbleStatus = "interrupted";
  }
  setAssistantStatus(
    turn,
    bubbleStatus,
    event.reason ?? rawStatus,
    { terminal: true },
  );

  // A late completion from an old epoch must finalize its own bubble, but it
  // must not stop the current response or move the global activity badge.
  if (completionOnly || wasTerminal) {
    return;
  }
  state.assistantResponding = false;
  setPlayerResponseState(false);
  refreshMicPermissionLabel();
  if (rawStatus === "cancelled" || rawStatus === "interrupted") {
    setActivity("interrupted");
  } else if (rawStatus !== "completed") {
    setActivity("error");
  } else if (state.playbackActive) {
    setActivity("responding");
  } else if (state.micActive) {
    setActivity("listening");
  } else {
    setActivity("connected");
  }
}

function sendControl(type, payload = {}) {
  if (!socketIsOpen()) {
    return false;
  }
  state.socket.send(JSON.stringify({ type, ...payload }));
  return true;
}

function samplesToMs(samples) {
  return samples * 1_000 / PLAYER_SOURCE_SAMPLE_RATE;
}

function refreshPlaybackTelemetry() {
  const bufferedMs = samplesToMs(state.playerBufferedSamples);
  const epochHighWaterMs = samplesToMs(state.playerEpochHighWaterSamples);
  const softCapacityMs = state.playerSoftCapacitySamples > 0
    ? `${Math.round(samplesToMs(state.playerSoftCapacitySamples))}`
    : "—";
  const hardCapacityMs = state.playerCapacitySamples > 0
    ? `${Math.round(samplesToMs(state.playerCapacitySamples))}`
    : "—";
  if (elements.playbackBuffer) {
    elements.playbackBuffer.textContent = `${Math.round(bufferedMs)} / ${Math.round(epochHighWaterMs)} / ${softCapacityMs} / ${hardCapacityMs} ms`;
  }
  if (elements.outputDropCount) {
    const droppedMs = samplesToMs(state.playerDroppedOutputSamples);
    elements.outputDropCount.textContent = `${state.playerDroppedOutputSamples} samples / ${Math.round(droppedMs)} ms`;
  }
  if (elements.gatewayDropCount) {
    elements.gatewayDropCount.textContent = String(state.remoteDroppedOutput);
  }
}

function setPlayerResponseState(active) {
  state.playerNode?.port.postMessage({
    type: "response_state",
    epoch: state.currentEpoch,
    active: Boolean(active),
  });
}

function handlePlayerBufferStatus(message) {
  const epoch = normalizeEpoch(message.epoch);
  if (epoch === null || epoch !== state.currentEpoch) {
    return;
  }

  const bufferedSamples = finiteNumber(message.buffered_samples, 0, Number.MAX_SAFE_INTEGER);
  const highWaterSamples = finiteNumber(message.high_water_samples, 0, Number.MAX_SAFE_INTEGER);
  const epochHighWaterSamples = finiteNumber(
    message.epoch_high_water_samples,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const softCapacitySamples = finiteNumber(
    message.soft_capacity_samples,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const capacitySamples = finiteNumber(message.capacity_samples, 0, Number.MAX_SAFE_INTEGER);
  const droppedSamples = finiteNumber(message.total_dropped_samples, 0, Number.MAX_SAFE_INTEGER);
  const underflowCount = finiteNumber(message.underflow_count, 0, Number.MAX_SAFE_INTEGER);
  const reason = safeReference(message.reason) || "status";
  const previousDropped = state.playerDroppedOutputSamples;
  const previousUnderflows = state.playerUnderflowCount;

  if (bufferedSamples !== null) state.playerBufferedSamples = Math.round(bufferedSamples);
  if (highWaterSamples !== null) {
    state.playerHighWaterSamples = Math.max(state.playerHighWaterSamples, Math.round(highWaterSamples));
  }
  if (epochHighWaterSamples !== null) {
    state.playerEpochHighWaterSamples = Math.round(epochHighWaterSamples);
  }
  if (softCapacitySamples !== null) {
    state.playerSoftCapacitySamples = Math.round(softCapacitySamples);
  }
  if (capacitySamples !== null) state.playerCapacitySamples = Math.round(capacitySamples);
  if (droppedSamples !== null) {
    state.playerDroppedOutputSamples = Math.max(
      state.playerDroppedOutputSamples,
      Math.round(droppedSamples),
    );
  }
  if (underflowCount !== null) {
    state.playerUnderflowCount = Math.max(state.playerUnderflowCount, Math.round(underflowCount));
  }
  if (state.playerBacklogHigh && (reason === "clear" || state.playerBufferedSamples === 0)) {
    state.playerBacklogHigh = false;
  }
  refreshPlaybackTelemetry();

  if (state.playerUnderflowCount > previousUnderflows) {
    markDegraded();
    appendTimeline("flow.output_underflow", {
      epoch,
      count: state.playerUnderflowCount - previousUnderflows,
      underflow_count: state.playerUnderflowCount,
      buffered_samples: state.playerBufferedSamples,
      buffered_ms: samplesToMs(state.playerBufferedSamples),
    });
  }

  const now = performance.now();
  const important = state.playerDroppedOutputSamples > previousDropped
    || state.playerUnderflowCount > previousUnderflows
    || ["capacity_exceeded", "clear", "underflow"].includes(reason);
  if (important || now - state.lastPlaybackTelemetryAt >= PLAYBACK_TELEMETRY_INTERVAL_MS) {
    appendTimeline("playback.buffer", {
      epoch,
      reason,
      buffered_samples: state.playerBufferedSamples,
      buffered_ms: samplesToMs(state.playerBufferedSamples),
      high_water_samples: state.playerHighWaterSamples,
      high_water_ms: samplesToMs(state.playerHighWaterSamples),
      epoch_high_water_samples: state.playerEpochHighWaterSamples,
      epoch_high_water_ms: samplesToMs(state.playerEpochHighWaterSamples),
      soft_capacity_samples: state.playerSoftCapacitySamples,
      soft_capacity_ms: samplesToMs(state.playerSoftCapacitySamples),
      capacity_samples: state.playerCapacitySamples,
      hard_capacity_samples: state.playerCapacitySamples,
      hard_capacity_ms: samplesToMs(state.playerCapacitySamples),
      total_dropped_samples: state.playerDroppedOutputSamples,
      dropped_output_ms: samplesToMs(state.playerDroppedOutputSamples),
      underflow_count: state.playerUnderflowCount,
    });
    state.lastPlaybackTelemetryAt = now;
  }
}

function observePlayerBacklogHigh(message) {
  const epoch = normalizeEpoch(message.epoch);
  if (epoch === null || epoch !== state.currentEpoch) {
    return;
  }
  handlePlayerBufferStatus(message);
  const alreadyHigh = state.playerBacklogHigh;
  state.playerBacklogHigh = true;
  markDegraded();
  if (!alreadyHigh) {
    appendTimeline("flow.output_backlog_high", {
      epoch,
      reason: safeReference(message.reason) || "soft_capacity",
      buffered_samples: state.playerBufferedSamples,
      buffered_ms: samplesToMs(state.playerBufferedSamples),
      epoch_high_water_samples: state.playerEpochHighWaterSamples,
      soft_capacity_samples: state.playerSoftCapacitySamples,
      hard_capacity_samples: state.playerCapacitySamples,
      total_received_samples: message.total_received_samples,
    });
  }
}

function observePlayerBacklogRecovered(message) {
  const epoch = normalizeEpoch(message.epoch);
  if (epoch === null || epoch !== state.currentEpoch) {
    return;
  }
  handlePlayerBufferStatus(message);
  state.playerBacklogHigh = false;
  appendTimeline("playback.backlog_recovered", {
    epoch,
    reason: "soft_capacity_recovered",
    buffered_samples: state.playerBufferedSamples,
    buffered_ms: samplesToMs(state.playerBufferedSamples),
    epoch_high_water_samples: state.playerEpochHighWaterSamples,
    soft_capacity_samples: state.playerSoftCapacitySamples,
    hard_capacity_samples: state.playerCapacitySamples,
    total_received_samples: message.total_received_samples,
  });
}

function failCurrentPlaybackCapacity(message) {
  const epoch = normalizeEpoch(message.epoch);
  const dropped = finiteNumber(message.samples, 0, Number.MAX_SAFE_INTEGER) ?? 0;
  const total = finiteNumber(message.total_dropped_samples, 0, Number.MAX_SAFE_INTEGER);
  if (total !== null) {
    state.playerDroppedOutputSamples = Math.max(
      state.playerDroppedOutputSamples,
      Math.round(total),
    );
  } else {
    state.playerDroppedOutputSamples += Math.round(dropped);
  }
  refreshPlaybackTelemetry();
  markDegraded();
  appendTimeline("flow.output_capacity_exceeded", {
    epoch,
    dropped_output_samples: dropped,
    total_dropped_samples: state.playerDroppedOutputSamples,
    dropped_output_ms: samplesToMs(state.playerDroppedOutputSamples),
    buffered_samples: message.buffered_samples,
    soft_capacity_samples: message.soft_capacity_samples,
    capacity_samples: message.capacity_samples,
    hard_capacity_samples: message.hard_capacity_samples ?? message.capacity_samples,
  });

  // Fail coherently at the hard bound: advance the epoch, clear queued PCM and
  // cancel upstream instead of playing a response with arbitrary missing audio.
  if (epoch === state.currentEpoch && socketIsOpen()) {
    markLatestOpenAssistant("error", "output_capacity_exceeded", { terminal: true });
    clearPlayback("output_capacity_exceeded", null, { expectServerAck: true });
    sendControl("client.cancel", { playback_epoch: state.currentEpoch });
    setActivity("interrupted");
  }
}

async function ensurePlayer() {
  if (state.playerContext && state.playerNode) {
    if (state.playerContext.state === "suspended") {
      await state.playerContext.resume();
    }
    return;
  }

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass || !window.AudioWorkletNode) {
    throw new Error("audio_worklet_unavailable");
  }
  let context;
  try {
    context = new AudioContextClass({ latencyHint: "interactive", sampleRate: 24_000 });
  } catch (_error) {
    // The player worklet resamples its fixed 24 kHz source to the actual
    // AudioContext rate, so devices that reject a requested 24 kHz context
    // can safely use their native rate (commonly 44.1 or 48 kHz).
    context = new AudioContextClass({ latencyHint: "interactive" });
  }
  try {
    await context.audioWorklet.addModule("/static/player-worklet.js");
    const node = new AudioWorkletNode(context, "pcm24k-ring-player", {
      numberOfInputs: 0,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    node.port.onmessage = handlePlayerMessage;
    node.connect(context.destination);
    context.onstatechange = () => {
      if (state.playerContext === context) {
        observePlayerContextState(context, "statechange");
      }
    };
    await context.resume();
    state.playerContext = context;
    state.playerNode = node;
    node.port.postMessage({ type: "clear", epoch: state.currentEpoch, token: 0 });
    appendTimeline("player.ready", { status: `${Math.round(context.sampleRate)}hz` });
    observePlayerContextState(context, "ready");
  } catch (error) {
    context.onstatechange = null;
    await context.close().catch(() => {});
    throw error;
  }
}

function observePlayerContextState(context, reason) {
  appendTimeline("player.context_state", {
    status: safeReference(context?.state) || "unknown",
    reason: safeReference(reason) || "statechange",
    sample_rate: finiteNumber(context?.sampleRate, 1, 384_000),
  });
}

async function resumePlayerContextBestEffort(reason) {
  const context = state.playerContext;
  if (!context || context.state === "closed" || context.state === "running") {
    return context?.state === "running";
  }
  try {
    await context.resume();
    observePlayerContextState(context, reason);
    return context.state === "running";
  } catch (_error) {
    markDegraded();
    appendTimeline("player.context_resume_failed", {
      status: safeReference(context.state) || "unknown",
      reason: safeReference(reason) || "resume",
      sample_rate: finiteNumber(context.sampleRate, 1, 384_000),
    });
    return false;
  }
}

async function closePlayer() {
  const node = state.playerNode;
  const context = state.playerContext;
  state.playerNode = null;
  state.playerContext = null;
  state.playbackActive = false;
  state.pendingClears.clear();
  if (node) {
    node.port.onmessage = null;
    node.disconnect();
  }
  if (context && context.state !== "closed") {
    observePlayerContextState(context, "closing");
    context.onstatechange = null;
    await context.close().catch(() => {});
  } else if (context) {
    context.onstatechange = null;
  }
  refreshMicPermissionLabel();
}

function handlePlayerMessage(event) {
  const message = event.data || {};
  if (message.type === "cleared") {
    if (normalizeEpoch(message.epoch) === state.currentEpoch) {
      state.playerBufferedSamples = 0;
      state.playerEpochHighWaterSamples = 0;
      state.playerBacklogHigh = false;
      refreshPlaybackTelemetry();
    }
    finishPlaybackClear(message.token, message.epoch);
    return;
  }
  if (message.type === "playing" && normalizeEpoch(message.epoch) === state.currentEpoch) {
    state.playbackActive = true;
    setActivity("responding");
    refreshMicPermissionLabel();
    if (isSpeakerSafePaused()) {
      state.pendingMicFrames.length = 0;
    }
    return;
  }
  if (message.type === "drained" && normalizeEpoch(message.epoch) === state.currentEpoch) {
    state.playbackActive = false;
    state.playerBufferedSamples = 0;
    refreshPlaybackTelemetry();
    refreshMicPermissionLabel();
    if (!state.assistantResponding) {
      setActivity(state.micActive ? "listening" : socketIsOpen() ? "connected" : "idle");
    }
    return;
  }
  if (message.type === "buffer_status") {
    handlePlayerBufferStatus(message);
    return;
  }
  if (message.type === "output_backlog_high") {
    observePlayerBacklogHigh(message);
    return;
  }
  if (message.type === "output_backlog_recovered") {
    observePlayerBacklogRecovered(message);
    return;
  }
  if (message.type === "output_capacity_exceeded") {
    handlePlayerBufferStatus(message);
    failCurrentPlaybackCapacity(message);
    return;
  }
  if (message.type === "output_overflow") {
    // Compatibility with an older cached worklet: treat overflow as a hard
    // capacity failure so it cannot continue splicing current-epoch speech.
    failCurrentPlaybackCapacity(message);
    return;
  }
  if (message.type === "output_underflow") {
    const underflowCount = finiteNumber(message.underflow_count, 0, Number.MAX_SAFE_INTEGER);
    if (underflowCount !== null && underflowCount > state.playerUnderflowCount) {
      state.playerUnderflowCount = Math.round(underflowCount);
      markDegraded();
      appendTimeline("flow.output_underflow", {
        epoch: message.epoch,
        underflow_count: state.playerUnderflowCount,
        buffered_samples: message.buffered_samples,
      });
    }
    return;
  }
  if (message.type === "late_audio_dropped") {
    appendTimeline("playback.late_audio_dropped", {
      epoch: message.epoch,
      count: message.samples,
    });
  }
}

function handleMicMessage(event) {
  const message = event.data || {};
  if (message.type !== "pcm" || !(message.pcm instanceof ArrayBuffer)) {
    return;
  }
  const level = finiteNumber(message.level, 0, 1) ?? 0;
  elements.inputLevel.value = level;
  elements.inputLevelText.textContent = `${Math.round(level * 100)}%`;

  if (!state.micActive || !socketIsOpen() || isSpeakerSafePaused()) {
    return;
  }
  if (message.pcm.byteLength === 0 || message.pcm.byteLength > 6_400 || message.pcm.byteLength % 2 !== 0) {
    return;
  }
  if (state.pendingMicFrames.length >= MIC_QUEUE_LIMIT) {
    state.pendingMicFrames.shift();
    state.localDroppedInput += 1;
    refreshDropCount();
    markDegraded();
  }
  state.pendingMicFrames.push(message.pcm);
}

function flushMicFrames() {
  if (!socketIsOpen()) {
    state.pendingMicFrames.length = 0;
    return;
  }
  if (isSpeakerSafePaused()) {
    state.pendingMicFrames.length = 0;
    return;
  }

  let sent = 0;
  while (
    state.pendingMicFrames.length > 0
    && state.socket.bufferedAmount <= WS_HIGH_WATER_BYTES
    && sent < 2
  ) {
    const frame = state.pendingMicFrames.shift();
    state.socket.send(frame);
    sent += 1;
  }
}

function refreshDropCount() {
  elements.dropCount.textContent = String(state.localDroppedInput + state.remoteDroppedInput);
}

async function startMicrophone() {
  if (!socketIsOpen() || !state.providerSessionReady || state.micActive) {
    return;
  }
  const operation = ++state.micOperation;
  elements.micPermission.textContent = "requesting";
  elements.startMic.disabled = true;
  let stream = null;
  let context = null;

  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("media_devices_unavailable");
    }
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    if (operation !== state.micOperation || !socketIsOpen() || !state.providerSessionReady) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass || !window.AudioWorkletNode) {
      throw new Error("audio_worklet_unavailable");
    }
    context = new AudioContextClass({ latencyHint: "interactive" });
    await context.audioWorklet.addModule("/static/mic-worklet.js");
    if (operation !== state.micOperation || !socketIsOpen() || !state.providerSessionReady) {
      stream.getTracks().forEach((track) => track.stop());
      await context.close();
      return;
    }

    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, "pcm16-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      channelCount: 1,
      channelCountMode: "explicit",
    });
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    node.port.onmessage = handleMicMessage;
    source.connect(node);
    node.connect(silentGain);
    silentGain.connect(context.destination);
    await context.resume();
    if (operation !== state.micOperation || !socketIsOpen() || !state.providerSessionReady) {
      node.port.onmessage = null;
      source.disconnect();
      node.disconnect();
      silentGain.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      await context.close().catch(() => {});
      return;
    }

    state.mediaStream = stream;
    state.micContext = context;
    state.micSource = source;
    state.micNode = node;
    state.silentGain = silentGain;
    state.micActive = true;
    state.pendingMicFrames.length = 0;
    elements.micPermission.textContent = "active";
    setActivity("listening");
    sendControl("client.microphone", { active: true });
    appendTimeline("client.microphone", { status: "active" });
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    if (context && context.state !== "closed") {
      await context.close().catch(() => {});
    }
    const errorName = safeReference(error?.name) || safeReference(error?.message) || "unavailable";
    const denied = errorName === "NotAllowedError" || errorName === "PermissionDeniedError";
    elements.micPermission.textContent = denied ? "denied" : "unavailable";
    setActivity("error");
    appendTimeline(denied ? "microphone.permission_denied" : "microphone.unavailable");
  } finally {
    refreshButtons();
  }
}

async function stopMicrophone({ notify = true } = {}) {
  state.micOperation += 1;
  const wasActive = state.micActive;
  state.micActive = false;
  state.pendingMicFrames.length = 0;
  const stream = state.mediaStream;
  const context = state.micContext;
  const source = state.micSource;
  const node = state.micNode;
  const silentGain = state.silentGain;
  state.mediaStream = null;
  state.micContext = null;
  state.micSource = null;
  state.micNode = null;
  state.silentGain = null;

  if (node) {
    node.port.postMessage({ type: "reset" });
    node.port.onmessage = null;
  }
  source?.disconnect();
  node?.disconnect();
  silentGain?.disconnect();
  stream?.getTracks().forEach((track) => track.stop());
  if (context && context.state !== "closed") {
    await context.close().catch(() => {});
  }
  elements.inputLevel.value = 0;
  elements.inputLevelText.textContent = "0%";
  if (wasActive) {
    elements.micPermission.textContent = "stopped";
    if (notify) {
      sendControl("client.microphone", { active: false });
    }
    appendTimeline("client.microphone", { status: "inactive" });
  }
  if (!state.assistantResponding && !state.playbackActive) {
    setActivity(socketIsOpen() ? "connected" : "idle");
  }
  refreshButtons();
}

function startSocketTimers() {
  stopSocketTimers();
  state.flushTimer = window.setInterval(flushMicFrames, 20);
  state.heartbeatTimer = window.setInterval(() => {
    sendControl("client.ping", { client_ts_ms: Math.round(performance.now()) });
  }, HEARTBEAT_INTERVAL_MS);
}

function stopSocketTimers() {
  if (state.flushTimer !== null) window.clearInterval(state.flushTimer);
  if (state.heartbeatTimer !== null) window.clearInterval(state.heartbeatTimer);
  state.flushTimer = null;
  state.heartbeatTimer = null;
}

async function connect() {
  if (socketIsOpen() || state.connecting) {
    return;
  }
  state.connecting = true;
  resetSessionUi();
  setConnectionBadge("Connecting", "neutral");
  refreshButtons();

  try {
    await ensurePlayer();
    const url = new URL("/ws", window.location.href);
    url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("mode", elements.mode.value);
    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    state.socket = socket;

    socket.addEventListener("open", () => {
      if (state.socket !== socket) {
        state.intentionallyClosedSockets.add(socket);
        socket.close(1000, "superseded connection");
        return;
      }
      state.connecting = false;
      setConnectionBadge("Connected", "connected");
      setActivity("connected");
      sendControl("client.configure", { mode: elements.mode.value });
      startSocketTimers();
      appendTimeline("socket.open");
      refreshButtons();
    });
    socket.addEventListener("message", (event) => {
      if (state.socket === socket) {
        handleSocketMessage(event);
      }
    });
    socket.addEventListener("error", () => {
      if (state.socket !== socket) {
        return;
      }
      state.providerSessionReady = false;
      markAllOpenAssistantsError("transport_aborted");
      setConnectionBadge("Error", "error");
      setActivity("error");
      appendTimeline("socket.error");
      refreshButtons();
    });
    socket.addEventListener("close", (event) => {
      void handleSocketClosed(socket, event);
    });
  } catch (_error) {
    state.connecting = false;
    state.socket = null;
    state.providerSessionReady = false;
    markAllOpenAssistantsError("initialization_failed");
    setConnectionBadge("Error", "error");
    setActivity("error");
    appendTimeline("client.initialization_failed");
    await closePlayer();
    refreshButtons();
  }
}

async function disconnect() {
  state.connecting = false;
  state.providerSessionReady = false;
  refreshButtons();
  await stopMicrophone();
  stopSocketTimers();
  state.pendingMicFrames.length = 0;
  markAllOpenAssistants("cancelled", "client_disconnect");
  const socket = state.socket;
  if (socket) {
    state.intentionallyClosedSockets.add(socket);
  }
  if (socket?.readyState === WebSocket.OPEN) {
    sendControl("client.cancel", { playback_epoch: state.currentEpoch });
    state.socket = null;
    socket.close(1000, "client disconnect");
  } else if (socket) {
    state.socket = null;
    socket.close();
  }
  await closePlayer();
  setConnectionBadge("Disconnected", "neutral");
  setActivity("idle");
  refreshButtons();
}

async function handleSocketClosed(closedSocket, event) {
  if (state.socket !== closedSocket) {
    return;
  }
  const wasIntentional = state.intentionallyClosedSockets.has(closedSocket);
  state.socket = null;
  state.connecting = false;
  state.providerSessionReady = false;
  stopSocketTimers();
  state.pendingMicFrames.length = 0;
  if (!wasIntentional) {
    markAllOpenAssistantsError("transport_aborted");
  }
  await stopMicrophone({ notify: false });
  await closePlayer();
  setConnectionBadge("Disconnected", "neutral");
  setActivity(wasIntentional ? "idle" : "error");
  appendTimeline("socket.close", { status: event.code });
  refreshButtons();
}

function cancelResponse() {
  if (!socketIsOpen()) {
    return;
  }
  markLatestOpenAssistant("cancel_pending", "client_cancel");
  clearPlayback("client_cancel", null, {
    expectServerAck: true,
  });
  sendControl("client.cancel", { playback_epoch: state.currentEpoch });
  setActivity("interrupted");
}

function handleSocketMessage(event) {
  if (event.data instanceof ArrayBuffer) {
    handleAudioFrame(event.data);
    return;
  }
  if (typeof event.data === "string") {
    handleControlFrame(event.data);
    return;
  }
  appendTimeline("protocol.unsupported_frame");
}

function handleAudioFrame(frame) {
  if (frame.byteLength < AUDIO_HEADER_BYTES) {
    appendTimeline("protocol.invalid_audio_header", { byte_length: frame.byteLength });
    return;
  }
  const bytes = new Uint8Array(frame, 0, 4);
  if (bytes[0] !== 0x51 || bytes[1] !== 0x41 || bytes[2] !== 0x52 || bytes[3] !== 0x31) {
    appendTimeline("protocol.invalid_audio_magic", { byte_length: frame.byteLength });
    return;
  }
  const epoch = new DataView(frame).getUint32(4, false);
  const pcmBytes = frame.byteLength - AUDIO_HEADER_BYTES;
  if (pcmBytes === 0 || pcmBytes % 2 !== 0) {
    appendTimeline("protocol.invalid_audio_payload", { byte_length: pcmBytes, epoch });
    return;
  }
  if (epoch < state.currentEpoch) {
    appendTimeline("playback.late_audio_dropped", { byte_length: pcmBytes, epoch });
    return;
  }
  if (epoch > state.currentEpoch) {
    clearPlayback("audio_epoch_advance", epoch);
  }
  if (!state.playerNode) {
    appendTimeline("playback.audio_dropped_no_player", { byte_length: pcmBytes, epoch });
    return;
  }

  observeFirstAudio();
  state.playbackActive = true;
  setActivity("responding");
  refreshMicPermissionLabel();
  if (isSpeakerSafePaused()) {
    state.pendingMicFrames.length = 0;
  }
  const pcm = frame.slice(AUDIO_HEADER_BYTES);
  state.playerNode.port.postMessage({ type: "enqueue", epoch, pcm }, [pcm]);
  const now = performance.now();
  if (now - state.lastAudioTimelineAt >= 500) {
    appendTimeline("playback.audio", { byte_length: pcmBytes, epoch });
    state.lastAudioTimelineAt = now;
  }
}

function handleControlFrame(rawFrame) {
  let event;
  try {
    event = JSON.parse(rawFrame);
  } catch (_error) {
    appendTimeline("protocol.invalid_json");
    return;
  }
  if (!event || typeof event !== "object" || Array.isArray(event)) {
    appendTimeline("protocol.invalid_control");
    return;
  }
  const type = safeReference(event.type);
  if (!type) {
    appendTimeline("protocol.missing_type");
    return;
  }
  observeGatewayOutputDrops(event);

  if (type === "timeline.event") {
    const timelineType = safeReference(event.event_type ?? event.name ?? event.event) || type;
    appendTimeline(timelineType, event);
    observeTimelineMarker(timelineType);
    applyTimelineMetric(timelineType, event);
    return;
  }
  if (type === "flow.dropped") {
    handleFlowDropped(event);
    return;
  }
  if (type === "flow.gateway_output_dropped") {
    // observeGatewayOutputDrops already updated state and emitted the classified
    // metadata timeline row before this dispatch branch.
    return;
  }
  appendTimeline(type, event);

  if (type === "session.ready" || type === "session.created" || type === "session.updated") {
    handleSessionReady(event, type);
  } else if (type === "session.status") {
    handleSessionStatus(event);
  } else if (type === "user.transcript.delta") {
    addTranscriptDelta("user", event);
  } else if (type === "user.transcript.final") {
    commitTranscript("user", event);
  } else if (type === "assistant.transcript.delta") {
    addTranscriptDelta("assistant", event);
  } else if (type === "assistant.transcript.done") {
    commitTranscript("assistant", event);
  } else if (type === "playback.started" || type === "assistant.response.started") {
    beginAssistantResponse(event);
  } else if (type === "playback.clear") {
    handleServerPlaybackClear(event);
  } else if (type === "response.done" || type === "assistant.response.done") {
    finishAssistantResponse(event);
  } else if (type === "session.error" || type === "error") {
    handleSessionError(event);
  } else if (type === "input_audio.speech_started") {
    handleSpeechStartedControl(event);
  } else if (type === "speech.started") {
    handleSpeechStartedControl(event);
  } else if (type === "input_audio.speech_stopped" || type === "speech.stopped") {
    markSpeechStopped();
  } else if (type === "metrics") {
    applyMetrics(event);
  }
}

function observeGatewayOutputDrops(event) {
  const total = finiteNumber(event.dropped_output_messages, 0, Number.MAX_SAFE_INTEGER);
  if (total === null) {
    return;
  }
  const rounded = Math.round(total);
  if (rounded <= state.remoteDroppedOutput) {
    return;
  }
  const increment = rounded - state.remoteDroppedOutput;
  state.remoteDroppedOutput = rounded;
  refreshPlaybackTelemetry();
  markDegraded();
  appendTimeline("flow.gateway_output_dropped", {
    count: increment,
    dropped_output_messages: rounded,
    dropped_audio_messages_delta: event.dropped_audio_messages_delta,
    dropped_control_messages_delta: event.dropped_control_messages_delta,
    output_queue_depth: event.output_queue_depth,
    output_queue_high_water: event.output_queue_high_water,
    output_queue_capacity: event.output_queue_capacity,
    reason: safeReference(event.reason) || "gateway_output_queue",
  });
}

function handleSessionReady(event, eventType) {
  if (eventType === "session.created") {
    state.providerSessionReady = false;
  } else if (eventType === "session.updated") {
    state.providerSessionReady = true;
  }
  const outputMode = event.output_mode
    ?? event.capabilities?.output_mode
    ?? event.provider_mode
    ?? event.provider;
  const degraded = event.degraded === true || event.status === "degraded";
  setOutputMode(outputMode, degraded, event.capabilities);
  const epoch = normalizeEpoch(event.playback_epoch ?? event.epoch);
  if (epoch !== null && epoch >= state.currentEpoch) {
    state.currentEpoch = epoch;
  }
  setConnectionBadge("Connected", "connected");
  setActivity(state.micActive ? "listening" : "connected");
  refreshButtons();
}

function handleSessionStatus(event) {
  const outputMode = event.output_mode ?? event.provider_mode;
  if (outputMode) {
    setOutputMode(outputMode, event.degraded === true, event.capabilities);
  }
  applyMetrics(event);
  const status = String(event.status ?? event.state ?? event.activity ?? "").toLowerCase();
  if (status === "responding" || status === "playing") {
    state.assistantResponding = true;
    setActivity("responding");
  } else if (status === "interrupted") {
    if (state.turn.speechStartedAt === null) {
      resetTurnAtSpeechStart();
    }
    setActivity("interrupted");
  } else if (status === "listening" || status === "processing") {
    setActivity("listening");
  } else if (status === "error") {
    setActivity("error");
  } else if (status) {
    setActivity("connected");
  }
  refreshMicPermissionLabel();
}

function handleServerPlaybackClear(event) {
  const receivedAt = performance.now();
  const reason = safeReference(event.reason) || "server";
  const speechClear = reason.includes("speech_started") || reason === "barge_in" || reason === "interrupt";
  const interruptedClear = speechClear || reason === "client_cancel";
  const rawEpoch = event.playback_epoch ?? event.epoch;
  const providedEpoch = normalizeEpoch(rawEpoch);
  if (providedEpoch !== null && providedEpoch < state.currentEpoch) {
    clearPlayback(reason, providedEpoch);
    return;
  }
  const sameSpeechEpoch = providedEpoch === null || providedEpoch === state.currentEpoch;
  const recentSpeechStart = sameSpeechEpoch
    && state.turn.speechStartedAt !== null
    && receivedAt - state.turn.speechStartedAt < 1_000;
  let targetTurn = null;
  if (speechClear && !recentSpeechStart) {
    targetTurn = [...state.conversationTurns]
      .reverse()
      .find((turn) => !turn.assistant.terminal) || null;
    if (targetTurn) {
      setAssistantStatus(targetTurn, "interrupt_pending", reason);
    }
    resetTurnAtSpeechStart(receivedAt);
  } else if (reason === "client_cancel") {
    targetTurn = [...state.conversationTurns]
      .reverse()
      .find((turn) => !turn.assistant.terminal) || null;
    if (targetTurn) {
      setAssistantStatus(targetTurn, "cancel_pending", reason);
    }
  }
  const accepted = clearPlayback(reason, rawEpoch, {
    acknowledgesLocalAdvance: true,
    measureSpeechClear: speechClear,
    metricStartedAt: speechClear ? state.turn.speechStartedAt ?? receivedAt : undefined,
  });
  if (!accepted) {
    return;
  }
  if (speechClear && targetTurn) {
    setAssistantStatus(targetTurn, "interrupted", reason, { terminal: true });
  }
  setActivity(interruptedClear ? "interrupted" : state.micActive ? "listening" : "connected");
}

function handleFlowDropped(event) {
  const reason = safeReference(event.reason) || "unknown";
  if (reason === "input_backlog_drop_oldest") {
    const total = finiteNumber(event.dropped_input_frames, 0, Number.MAX_SAFE_INTEGER);
    const increment = finiteNumber(event.count, 0, Number.MAX_SAFE_INTEGER);
    if (total !== null) {
      state.remoteDroppedInput = Math.max(state.remoteDroppedInput, Math.round(total));
    } else if (increment !== null) {
      state.remoteDroppedInput += Math.round(increment);
    }
    refreshDropCount();
    markDegraded();
    appendTimeline("flow.input_dropped", {
      reason,
      dropped_input_frames: state.remoteDroppedInput,
    });
    return;
  }

  if (reason === "speaker_safe_suppressed") {
    appendTimeline("flow.speaker_safe_suppressed", {
      reason,
      count: event.speaker_safe_suppressed_frames,
    });
    return;
  }

  if (reason.startsWith("stale_response_")) {
    appendTimeline("flow.stale_event_dropped", {
      reason,
      count: event.stale_audio_frames,
      epoch: event.playback_epoch ?? event.epoch,
    });
    return;
  }

  markDegraded();
  appendTimeline("flow.dropped", {
    reason,
    dropped_output_messages: event.dropped_output_messages,
  });
}

function handleSessionError(event) {
  const code = safeReference(event.code ?? event.error_code) || "provider_error";
  setOutputMode(event.provider_mode ?? event.output_mode ?? "degraded", true);
  markDegraded();
  if (event.terminal === false) {
    if (event.turn_failed === true) {
      const turn = findAssistantTurn(event);
      setAssistantStatus(turn, "error", code, { terminal: true });
    }
    return;
  }
  markAllOpenAssistantsError("transport_aborted");
  state.providerSessionReady = false;
  setConnectionBadge("Error", "error");
  setActivity("error");
  state.assistantResponding = false;
  state.playbackActive = false;
  state.pendingMicFrames.length = 0;
  clearPlayback(code, event.playback_epoch ?? event.epoch, {
    acknowledgesLocalAdvance: true,
  });
  refreshMicPermissionLabel();
  refreshButtons();
}

function observeTimelineMarker(type) {
  if (type.endsWith("speech.started") || type.endsWith("speech_started")) {
    if (state.turn.speechStartedAt === null || performance.now() - state.turn.speechStartedAt > 1_000) {
      resetTurnAtSpeechStart();
    }
  } else if (type.endsWith("speech.stopped") || type.endsWith("speech_stopped")) {
    if (state.turn.speechStoppedAt === null || performance.now() - state.turn.speechStoppedAt > 1_000) {
      markSpeechStopped();
    }
  }
}

function applyTimelineMetric(type, event) {
  if (type.endsWith("user.transcript.delta") || type.endsWith("user.transcript.final")) {
    setMetric(elements.metricUserTranscript, event.latency_ms);
  } else if (type.endsWith("assistant.transcript.delta")) {
    setMetric(elements.metricAssistantTranscript, event.latency_ms);
  } else if (type.endsWith("response.audio.delta")) {
    setMetric(elements.metricAudio, event.latency_ms);
  }
}

function handleSpeechStartedControl(event) {
  const receivedAt = performance.now();
  const eventEpoch = normalizeEpoch(event.playback_epoch ?? event.epoch);
  const sameSpeechEpoch = eventEpoch === null || eventEpoch === state.currentEpoch;
  const recent = sameSpeechEpoch
    && state.turn.speechStartedAt !== null
    && receivedAt - state.turn.speechStartedAt < 1_000;
  if (recent) {
    if (elements.activityBadge.textContent !== "Interrupted") {
      setActivity("listening");
    }
    return;
  }
  beginSpeechStarted(event.playback_epoch ?? event.epoch, receivedAt);
}

function changeMode() {
  refreshModeNotice();
  if (elements.mode.value === "speaker_safe" && isSpeakerSafePaused()) {
    state.pendingMicFrames.length = 0;
  }
  sendControl("client.configure", { mode: elements.mode.value });
  appendTimeline("client.configure", { status: elements.mode.value });
}

function cleanupBeforeUnload() {
  state.providerSessionReady = false;
  stopSocketTimers();
  state.pendingMicFrames.length = 0;
  state.mediaStream?.getTracks().forEach((track) => track.stop());
  state.micNode?.disconnect();
  state.micSource?.disconnect();
  state.silentGain?.disconnect();
  state.playerNode?.disconnect();
  if (state.playerContext) {
    state.playerContext.onstatechange = null;
  }
  void state.micContext?.close();
  void state.playerContext?.close();
  if (socketIsOpen()) {
    sendControl("client.microphone", { active: false });
    state.socket.close(1000, "page unload");
  }
}

elements.connect.addEventListener("click", () => void connect());
elements.disconnect.addEventListener("click", () => void disconnect());
elements.startMic.addEventListener("click", () => void startMicrophone());
elements.stopMic.addEventListener("click", () => void stopMicrophone());
elements.cancel.addEventListener("click", cancelResponse);
elements.clearTimeline.addEventListener("click", clearTimeline);
elements.conversationLatest.addEventListener("click", scrollConversationToLatest);
elements.conversationTranscript.addEventListener("scroll", handleConversationScroll, { passive: true });
elements.mode.addEventListener("change", changeMode);
window.addEventListener("beforeunload", cleanupBeforeUnload);

resetConversation();
refreshModeNotice();
refreshButtons();
