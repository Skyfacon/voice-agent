"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const MAX_TURNS = 32;
const MAX_TOTAL_TEXT = 32_000;
const MAX_BUBBLE_TEXT = 6_000;

function dataKey(attribute) {
  return attribute
    .slice(5)
    .replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}

class ClassList {
  constructor(element) {
    this.element = element;
  }

  values() {
    return this.element.className.split(/\s+/).filter(Boolean);
  }

  contains(name) {
    return this.values().includes(name);
  }

  add(...names) {
    this.element.className = [...new Set([...this.values(), ...names])].join(" ");
  }

  remove(...names) {
    const removed = new Set(names);
    this.element.className = this.values().filter((name) => !removed.has(name)).join(" ");
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.contains(name) : Boolean(force);
    if (enabled) this.add(name);
    else this.remove(name);
    return enabled;
  }
}

function matchesCompound(element, rawToken) {
  const token = rawToken.replace(/^:scope/, "").trim();
  if (!token || token === "*") return true;
  const tag = token.match(/^[A-Za-z][A-Za-z0-9-]*/)?.[0];
  if (tag && element.tagName !== tag.toUpperCase()) return false;
  const id = token.match(/#([A-Za-z0-9_-]+)/)?.[1];
  if (id && element.id !== id) return false;
  for (const match of token.matchAll(/\.([A-Za-z0-9_-]+)/g)) {
    if (!element.classList.contains(match[1])) return false;
  }
  for (const match of token.matchAll(/\[([^\]=\s]+)(?:\s*=\s*["']?([^\]"']+)["']?)?\]/g)) {
    const [, attribute, expected] = match;
    const actual = element.getAttribute(attribute);
    if (actual === null) return false;
    if (expected !== undefined && actual !== expected) return false;
  }
  return true;
}

function matchesSelector(element, selector) {
  return selector.split(",").some((alternative) => {
    const tokens = alternative.trim().replace(/\s*>\s*/g, " ").split(/\s+/).filter(Boolean);
    if (tokens.length === 0 || !matchesCompound(element, tokens.at(-1))) return false;
    let ancestor = element.parentElement;
    for (let index = tokens.length - 2; index >= 0; index -= 1) {
      while (ancestor && !matchesCompound(ancestor, tokens[index])) {
        ancestor = ancestor.parentElement;
      }
      if (!ancestor) return false;
      ancestor = ancestor.parentElement;
    }
    return true;
  });
}

class ElementStub {
  constructor(tagName, ownerDocument, id = "") {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.id = id;
    this.parentElement = null;
    this.children = [];
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.writeLog = [];
    this._text = "";
    this._innerHTML = "";
    this.className = "";
    this.classList = new ClassList(this);
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.scrollTop = 0;
    this.clientHeight = 320;
    this.max = 1;
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._text = String(value ?? "");
    this._innerHTML = "";
    this.children.forEach((child) => { child.parentElement = null; });
    this.children = [];
    this.writeLog.push({ property: "textContent", value: this._text });
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(value) {
    this._innerHTML = String(value ?? "");
    this._text = "";
    this.children.forEach((child) => { child.parentElement = null; });
    this.children = [];
    this.writeLog.push({ property: "innerHTML", value: this._innerHTML });
  }

  get scrollHeight() {
    const textRows = Math.ceil(this.textContent.length / 80);
    return Math.max(this.clientHeight, this.children.length * 120 + textRows * 20);
  }

  get firstElementChild() {
    return this.children[0] ?? null;
  }

  get lastElementChild() {
    return this.children.at(-1) ?? null;
  }

  get childElementCount() {
    return this.children.length;
  }

  append(...nodes) {
    for (const node of nodes) {
      if (typeof node === "string") {
        this._text += node;
        continue;
      }
      if (!node) continue;
      node.remove();
      node.parentElement = this;
      this.children.push(node);
    }
  }

  appendChild(node) {
    this.append(node);
    return node;
  }

  prepend(...nodes) {
    for (const node of [...nodes].reverse()) {
      if (!node) continue;
      node.remove();
      node.parentElement = this;
      this.children.unshift(node);
    }
  }

  replaceChildren(...nodes) {
    this.children.forEach((child) => { child.parentElement = null; });
    this.children = [];
    this._text = "";
    this._innerHTML = "";
    this.append(...nodes);
  }

  remove() {
    if (!this.parentElement) return;
    const siblings = this.parentElement.children;
    const index = siblings.indexOf(this);
    if (index >= 0) siblings.splice(index, 1);
    this.parentElement = null;
  }

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some((child) => child.contains(candidate));
  }

  querySelectorAll(selector) {
    const matches = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (matchesSelector(child, selector)) matches.push(child);
        visit(child);
      }
    };
    visit(this);
    return matches;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }

  closest(selector) {
    let current = this;
    while (current) {
      if (matchesSelector(current, selector)) return current;
      current = current.parentElement;
    }
    return null;
  }

  setAttribute(name, value) {
    const normalized = String(value);
    this.attributes.set(name, normalized);
    if (name === "id") this.id = normalized;
    else if (name === "class") this.className = normalized;
    else if (name.startsWith("data-")) this.dataset[dataKey(name)] = normalized;
  }

  getAttribute(name) {
    if (name === "id") return this.id || null;
    if (name === "class") return this.className || null;
    if (name.startsWith("data-")) {
      const value = this.dataset[dataKey(name)];
      return value === undefined ? null : String(value);
    }
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name.startsWith("data-")) delete this.dataset[dataKey(name)];
  }

  toggleAttribute(name, force) {
    const enabled = force === undefined ? this.getAttribute(name) === null : Boolean(force);
    if (enabled) this.setAttribute(name, "");
    else this.removeAttribute(name);
    return enabled;
  }

  addEventListener(type, callback) {
    const callbacks = this.listeners.get(type) ?? [];
    callbacks.push(callback);
    this.listeners.set(type, callbacks);
  }

  dispatchEvent(event) {
    event.target ??= this;
    for (const callback of this.listeners.get(event.type) ?? []) callback(event);
    return true;
  }

  click() {
    this.dispatchEvent({ type: "click", target: this });
  }

  focus() {}
}

class DocumentStub {
  constructor() {
    this.elementsById = new Map();
    this.allElements = [];
    this.body = this.createElement("body");
  }

  createElement(tagName) {
    const element = new ElementStub(tagName, this);
    this.allElements.push(element);
    return element;
  }

  createDocumentFragment() {
    return this.createElement("fragment");
  }

  getElementById(id) {
    if (!this.elementsById.has(id)) {
      const tag = id.endsWith("Btn") ? "button"
        : id.endsWith("Select") ? "select"
          : id === "timeline" ? "ol"
            : "div";
      const element = new ElementStub(tag, this, id);
      this.allElements.push(element);
      this.elementsById.set(id, element);
      this.body.append(element);
    }
    return this.elementsById.get(id);
  }

  querySelector(selector) {
    return this.body.querySelector(selector);
  }

  querySelectorAll(selector) {
    return this.body.querySelectorAll(selector);
  }
}

function createEnvironment(appPath) {
  const document = new DocumentStub();
  const source = fs.readFileSync(appPath, "utf8");
  for (const match of source.matchAll(/byId\("([^"]+)"\)/g)) {
    document.getElementById(match[1]);
  }
  for (const id of ["conversationTranscript", "conversationLatestBtn"]) {
    document.getElementById(id);
  }
  document.getElementById("modeSelect").value = "headset_full_duplex";
  document.getElementById("providerSelect").value = "unknown";
  const placeholder = document.createElement("li");
  placeholder.className = "placeholder";
  placeholder.textContent = "等待事件";
  document.getElementById("timeline").append(placeholder);

  let clock = 1_000;
  let timer = 0;
  const windowListeners = new Map();
  const window = {
    document,
    location: { href: "http://127.0.0.1:8765/", protocol: "http:" },
    addEventListener(type, callback) {
      const callbacks = windowListeners.get(type) ?? [];
      callbacks.push(callback);
      windowListeners.set(type, callbacks);
    },
    setInterval() { timer += 1; return timer; },
    clearInterval() {},
    setTimeout(callback) { timer += 1; callback(); return timer; },
    clearTimeout() {},
    requestAnimationFrame(callback) { timer += 1; callback(clock); return timer; },
    cancelAnimationFrame() {},
  };
  window.window = window;

  class WebSocketStub {
    static OPEN = 1;
    static CLOSED = 3;
  }

  const context = vm.createContext({
    ArrayBuffer,
    AudioWorkletNode: class {},
    DataView,
    Date,
    document,
    Int16Array,
    JSON,
    Map,
    Math,
    navigator: { mediaDevices: {} },
    Number,
    performance: { now() { clock += 5; return clock; } },
    Promise,
    queueMicrotask,
    setTimeout: window.setTimeout,
    clearTimeout: window.clearTimeout,
    Uint8Array,
    URL,
    WeakSet,
    WebSocket: WebSocketStub,
    window,
  });
  vm.runInContext(source, context, { filename: appPath });

  return {
    context,
    document,
    window,
    WebSocketStub,
    advanceClock(milliseconds) { clock += milliseconds; },
  };
}

function dispatch(environment, type, fields = {}) {
  environment.context.__control = JSON.stringify({ type, ...fields });
  vm.runInContext("handleControlFrame(__control)", environment.context);
}

function evaluate(environment, source) {
  return vm.runInContext(source, environment.context);
}

function conversation(environment) {
  return environment.document.getElementById("conversationTranscript");
}

function turns(environment) {
  return conversation(environment).querySelectorAll(".conversation-turn");
}

function message(turn, role) {
  return turn.querySelector(`.message.${role}`);
}

function messageText(turn, role) {
  const row = message(turn, role);
  assert.ok(row, `missing ${role} message`);
  const text = row.querySelector(".message-text");
  assert.ok(text, `missing ${role} message text`);
  return text.textContent;
}

function assertFixedMessageOrder(turn) {
  const rows = turn.children.filter((child) => child.classList.contains("message"));
  assert.equal(rows.length, 2);
  assert.equal(rows[0].classList.contains("user"), true);
  assert.equal(rows[1].classList.contains("assistant"), true);
}

function startTurn(environment, sequence) {
  // Keep independent human turns outside the UI's duplicate speech marker
  // suppression window. Dedicated barge-in tests control their own cadence.
  environment.advanceClock(1_100);
  dispatch(environment, "speech.started", { playback_epoch: sequence });
}

function finishTurn(environment, sequence, userText, assistantParts) {
  const responseRef = `response-safe-${sequence}`;
  startTurn(environment, sequence);
  dispatch(environment, "user.transcript.final", { transcript: userText });
  dispatch(environment, "speech.stopped", { playback_epoch: sequence });
  dispatch(environment, "playback.started", {
    playback_epoch: sequence,
    response_ref: responseRef,
  });
  for (const delta of assistantParts) {
    dispatch(environment, "assistant.transcript.delta", { response_ref: responseRef, delta });
  }
  const assistantText = assistantParts.join("");
  dispatch(environment, "assistant.transcript.done", {
    response_ref: responseRef,
    transcript: assistantText,
  });
  dispatch(environment, "response.done", {
    response_ref: responseRef,
    response_epoch: sequence,
    status: "completed",
  });
  return { responseRef, assistantText };
}

function userProjection(appPath) {
  const environment = createEnvironment(appPath);
  startTurn(environment, 1);
  dispatch(environment, "user.transcript.delta", { delta: "你", stash: "好" });
  assert.equal(messageText(turns(environment)[0], "user"), "你好");
  dispatch(environment, "user.transcript.delta", { delta: "你好", stash: "世界" });
  assert.equal(messageText(turns(environment)[0], "user"), "你好世界");
  dispatch(environment, "user.transcript.final", { transcript: "你好世界" });

  const turn = turns(environment)[0];
  assert.equal(messageText(turn, "user"), "你好世界");
  assert.equal(message(turn, "user").dataset.status, "final");
  assertFixedMessageOrder(turn);
  return { turn_count: 1, user_text: messageText(turn, "user") };
}

function assistantProjection(appPath) {
  const environment = createEnvironment(appPath);
  startTurn(environment, 1);
  dispatch(environment, "user.transcript.final", { transcript: "问题" });
  dispatch(environment, "playback.started", { playback_epoch: 1, response_ref: "response-safe-1" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-safe-1", delta: "答" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-safe-1", delta: "案" });
  assert.equal(messageText(turns(environment)[0], "assistant"), "答案");
  assert.equal(message(turns(environment)[0], "assistant").dataset.status, "streaming");
  dispatch(environment, "assistant.transcript.done", {
    response_ref: "response-safe-1",
    transcript: "答案",
  });

  const turn = turns(environment)[0];
  assert.equal(messageText(turn, "assistant"), "答案");
  assert.equal(message(turn, "assistant").dataset.status, "text_done");
  return { assistant_text: messageText(turn, "assistant"), assistant_status: "text_done" };
}

function threeRounds(appPath) {
  const environment = createEnvironment(appPath);
  for (let sequence = 1; sequence <= 3; sequence += 1) {
    finishTurn(environment, sequence, `用户${sequence}`, [`助手`, String(sequence)]);
  }
  const visibleTurns = turns(environment);
  assert.equal(visibleTurns.length, 3);
  visibleTurns.forEach(assertFixedMessageOrder);
  assert.deepEqual(
    visibleTurns.map((turn) => [messageText(turn, "user"), messageText(turn, "assistant")]),
    [["用户1", "助手1"], ["用户2", "助手2"], ["用户3", "助手3"]],
  );
  assert.deepEqual(
    visibleTurns.map((turn) => Number(turn.dataset.turnSequence)),
    [1, 2, 3],
  );
  return { turn_count: 3 };
}

function assistantBoundary(appPath) {
  const environment = createEnvironment(appPath);
  startTurn(environment, 1);
  dispatch(environment, "user.transcript.delta", { delta: "尚未", stash: "确认" });
  dispatch(environment, "playback.started", { playback_epoch: 1, response_ref: "response-early" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-early", delta: "先到" });
  dispatch(environment, "user.transcript.final", { transcript: "迟到的用户 final" });
  let visibleTurns = turns(environment);
  assert.equal(visibleTurns.length, 1);
  assert.equal(messageText(visibleTurns[0], "user"), "迟到的用户 final");
  assert.equal(messageText(visibleTurns[0], "assistant"), "先到");

  dispatch(environment, "response.done", {
    response_ref: "response-early",
    response_epoch: 1,
    status: "completed",
  });
  dispatch(environment, "playback.started", { playback_epoch: 2, response_ref: "response-orphan" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-orphan", delta: "无用户边界" });
  visibleTurns = turns(environment);
  assert.equal(visibleTurns.length, 2);
  assert.equal(message(visibleTurns[1], "user").dataset.status, "unavailable");
  assert.equal(messageText(visibleTurns[1], "assistant"), "无用户边界");
  visibleTurns.forEach(assertFixedMessageOrder);
  return { turn_count: 2, orphan_user_status: "unavailable" };
}

function terminalStates(appPath) {
  const environment = createEnvironment(appPath);
  startTurn(environment, 1);
  dispatch(environment, "user.transcript.final", { transcript: "第一问" });
  dispatch(environment, "playback.started", { playback_epoch: 1, response_ref: "response-one" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-one", delta: "保留的半句" });
  environment.advanceClock(1_100);
  dispatch(environment, "playback.clear", {
    playback_epoch: 2,
    reason: "provider_speech_started",
  });
  dispatch(environment, "speech.started", { playback_epoch: 2 });
  let visibleTurns = turns(environment);
  assert.equal(messageText(visibleTurns[0], "assistant"), "保留的半句");
  assert.equal(message(visibleTurns[0], "assistant").dataset.status, "interrupted");

  dispatch(environment, "user.transcript.final", { transcript: "第二问" });
  dispatch(environment, "playback.started", { playback_epoch: 2, response_ref: "response-two" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-two", delta: "取消前" });
  dispatch(environment, "playback.clear", { playback_epoch: 3, reason: "client_cancel" });
  dispatch(environment, "response.done", {
    response_ref: "response-two",
    response_epoch: 2,
    status: "cancelled",
  });
  visibleTurns = turns(environment);
  assert.equal(messageText(visibleTurns[1], "assistant"), "取消前");
  assert.equal(message(visibleTurns[1], "assistant").dataset.status, "cancelled");

  dispatch(environment, "speech.started", { playback_epoch: 3 });
  dispatch(environment, "user.transcript.final", { transcript: "第三问" });
  dispatch(environment, "playback.started", { playback_epoch: 3, response_ref: "response-three" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-three", delta: "错误前" });
  dispatch(environment, "session.error", {
    code: "synthetic_provider_error",
    terminal: true,
    playback_epoch: 3,
  });
  visibleTurns = turns(environment);
  assert.equal(messageText(visibleTurns[2], "assistant"), "错误前");
  assert.equal(message(visibleTurns[2], "assistant").dataset.status, "error");
  assert.deepEqual(
    visibleTurns.map((turn) => messageText(turn, "assistant")),
    ["保留的半句", "取消前", "错误前"],
  );
  return { statuses: ["interrupted", "cancelled", "error"] };
}

function duplicateDone(appPath) {
  const environment = createEnvironment(appPath);
  startTurn(environment, 1);
  dispatch(environment, "user.transcript.final", { transcript: "只出现一次" });
  dispatch(environment, "playback.started", { playback_epoch: 1, response_ref: "response-dup" });
  dispatch(environment, "assistant.transcript.delta", { response_ref: "response-dup", delta: "唯一答案" });
  const done = { response_ref: "response-dup", transcript: "唯一答案" };
  dispatch(environment, "assistant.transcript.done", done);
  dispatch(environment, "assistant.transcript.done", done);
  const responseDone = {
    response_ref: "response-dup",
    response_epoch: 1,
    status: "completed",
  };
  dispatch(environment, "response.done", responseDone);
  dispatch(environment, "response.done", responseDone);
  dispatch(environment, "assistant.transcript.delta", {
    response_ref: "response-dup",
    delta: "不应复活",
  });

  const visibleTurns = turns(environment);
  assert.equal(visibleTurns.length, 1);
  assert.equal(messageText(visibleTurns[0], "assistant"), "唯一答案");
  assert.equal(message(visibleTurns[0], "assistant").dataset.status, "completed");
  return { turn_count: 1, assistant_text: "唯一答案" };
}

function boundedHistory(appPath) {
  const environment = createEnvironment(appPath);
  for (let sequence = 1; sequence <= 40; sequence += 1) {
    const suffix = String(sequence).padStart(2, "0");
    finishTurn(
      environment,
      sequence,
      `U${suffix}-${"u".repeat(900)}`,
      [`A${suffix}-`, "a".repeat(900)],
    );
  }
  const visibleTurns = turns(environment);
  const texts = visibleTurns.flatMap((turn) => [
    messageText(turn, "user"),
    messageText(turn, "assistant"),
  ]);
  assert.ok(visibleTurns.length <= MAX_TURNS);
  assert.ok(texts.every((text) => text.length <= MAX_BUBBLE_TEXT));
  assert.ok(texts.reduce((total, text) => total + text.length, 0) <= MAX_TOTAL_TEXT);
  assert.equal(texts.some((text) => text.startsWith("U01-")), false);
  assert.equal(texts.some((text) => text.startsWith("U40-")), true);
  assert.ok(environment.document.getElementById("timeline").children.length <= 80);
  return {
    turn_count: visibleTurns.length,
    total_text_chars: texts.reduce((total, text) => total + text.length, 0),
  };
}

function textContentSafety(appPath) {
  const environment = createEnvironment(appPath);
  const attack = '<img src=x onerror="globalThis.compromised=true">';
  finishTurn(environment, 1, attack, ["safe ", attack]);
  const turn = turns(environment)[0];
  assert.equal(messageText(turn, "user"), attack);
  assert.equal(messageText(turn, "assistant"), `safe ${attack}`);
  assert.equal(turn.querySelector("img"), null);

  const container = conversation(environment);
  const unsafeWrites = environment.document.allElements.filter(
    (element) => container.contains(element)
      && element.writeLog.some((write) => write.property === "innerHTML"),
  );
  assert.deepEqual(unsafeWrites, []);
  assert.equal(evaluate(environment, "globalThis.compromised === true"), false);
  return { inner_html_writes: 0 };
}

async function resetAndDisconnect(appPath) {
  const environment = createEnvironment(appPath);
  finishTurn(environment, 1, "保留问题", ["保留回答"]);
  startTurn(environment, 2);
  dispatch(environment, "user.transcript.final", { transcript: "未完成问题" });
  dispatch(environment, "playback.started", { playback_epoch: 2, response_ref: "response-open" });
  dispatch(environment, "assistant.transcript.delta", {
    response_ref: "response-open",
    delta: "未完成回答",
  });
  const beforeTexts = turns(environment).map((turn) => [
    messageText(turn, "user"),
    messageText(turn, "assistant"),
  ]);
  const sent = [];
  const socket = {
    readyState: environment.WebSocketStub.OPEN,
    send(payload) { sent.push(payload); },
    close() { this.readyState = environment.WebSocketStub.CLOSED; },
  };
  environment.context.__socket = socket;
  evaluate(environment, "state.socket = __socket");
  await evaluate(environment, "disconnect()");
  assert.deepEqual(
    turns(environment).map((turn) => [messageText(turn, "user"), messageText(turn, "assistant")]),
    beforeTexts,
  );
  assert.equal(turns(environment).length, 2);
  assert.equal(message(turns(environment)[0], "assistant").dataset.status, "completed");
  assert.equal(messageText(turns(environment)[1], "assistant"), "未完成回答");
  assert.equal(message(turns(environment)[1], "assistant").dataset.status, "cancelled");
  assert.ok(sent.some((payload) => JSON.parse(payload).type === "client.cancel"));

  evaluate(environment, "resetSessionUi()");
  assert.equal(turns(environment).length, 0);
  assert.equal(conversation(environment).textContent.includes("保留问题"), false);
  return { disconnect_preserved: true, disconnect_status: "cancelled", reset_turn_count: 0 };
}

async function main() {
  const scenario = process.argv[2];
  const appPath = process.argv[3];
  assert.ok(scenario && appPath, "usage: harness scenario app.js");
  const scenarios = {
    assistant_boundary: () => assistantBoundary(appPath),
    assistant_projection: () => assistantProjection(appPath),
    bounded_history: () => boundedHistory(appPath),
    duplicate_done: () => duplicateDone(appPath),
    reset_disconnect: () => resetAndDisconnect(appPath),
    terminal_states: () => terminalStates(appPath),
    text_content_safety: () => textContentSafety(appPath),
    three_rounds: () => threeRounds(appPath),
    user_projection: () => userProjection(appPath),
  };
  assert.ok(Object.hasOwn(scenarios, scenario), `unknown scenario: ${scenario}`);
  const metrics = await scenarios[scenario]();
  process.stdout.write(JSON.stringify({ status: "passed", scenario, ...metrics }));
}

main().catch((error) => {
  process.stderr.write(`${error?.stack || error}\n`);
  process.exitCode = 1;
});
