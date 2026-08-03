"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

/*
 * Reuse the minimal DOM implementation from the transcript harness without
 * changing that independently-owned test file.  Only its declarations are
 * evaluated; its command-line main is deliberately excluded.
 */
function loadDomHarness() {
  const helperPath = path.join(__dirname, "qwen_app_transcript_harness.js");
  const source = fs.readFileSync(helperPath, "utf8");
  const mainOffset = source.indexOf("async function main()");
  assert.ok(mainOffset > 0, "transcript harness main boundary was not found");
  const declarations = source.slice(0, mainOffset);
  const moduleStub = { exports: {} };
  const expose = new Function(
    "require",
    "module",
    "exports",
    "__filename",
    "__dirname",
    `${declarations}\nmodule.exports = { createEnvironment, dispatch, evaluate, turns, message };`,
  );
  expose(require, moduleStub, moduleStub.exports, helperPath, __dirname);
  return moduleStub.exports;
}

const {
  createEnvironment,
  dispatch,
  evaluate,
  turns,
  message,
} = loadDomHarness();

function installOpenSession(environment) {
  const sentControls = [];
  const playerMessages = [];
  const socket = {
    readyState: environment.WebSocketStub.OPEN,
    send(payload) { sentControls.push(JSON.parse(payload)); },
    close() { this.readyState = environment.WebSocketStub.CLOSED; },
  };
  const playerNode = {
    port: {
      postMessage(payload) { playerMessages.push(payload); },
    },
    disconnect() {},
  };
  environment.context.__capacitySocket = socket;
  environment.context.__capacityPlayerNode = playerNode;
  evaluate(
    environment,
    "state.socket = __capacitySocket; state.playerNode = __capacityPlayerNode;",
  );
  return { playerMessages, sentControls };
}

function openStreamingAssistant(environment, responseRef = "response-capacity") {
  dispatch(environment, "speech.started", { playback_epoch: 1 });
  dispatch(environment, "user.transcript.final", { transcript: "synthetic question" });
  dispatch(environment, "speech.stopped", { playback_epoch: 1 });
  dispatch(environment, "playback.started", {
    playback_epoch: 1,
    response_ref: responseRef,
  });
  dispatch(environment, "assistant.transcript.delta", {
    response_ref: responseRef,
    delta: "synthetic answer",
  });
  const assistant = message(turns(environment)[0], "assistant");
  assert.ok(assistant, "assistant bubble was not created");
  assert.equal(assistant.dataset.status, "streaming");
  return assistant;
}

function deliverPlayerMessage(environment, data) {
  environment.context.__capacityMessage = data;
  evaluate(environment, "handlePlayerMessage({ data: __capacityMessage })");
}

function timelineText(environment) {
  return environment.document.getElementById("timeline").textContent;
}

function softBacklog(appPath) {
  const environment = createEnvironment(appPath);
  const { playerMessages, sentControls } = installOpenSession(environment);
  const assistant = openStreamingAssistant(environment);
  const epochBefore = evaluate(environment, "state.currentEpoch");
  const clearCountBefore = playerMessages.filter((item) => item.type === "clear").length;

  deliverPlayerMessage(environment, {
    type: "output_backlog_high",
    epoch: epochBefore,
    buffered_samples: 300_000,
    soft_capacity_samples: 288_000,
    capacity_samples: 1_440_000,
    epoch_high_water_samples: 300_000,
    total_received_samples: 360_000,
  });

  assert.equal(evaluate(environment, "state.currentEpoch"), epochBefore);
  assert.equal(assistant.dataset.status, "streaming");
  assert.equal(sentControls.some((item) => item.type === "client.cancel"), false);
  assert.equal(
    playerMessages.filter((item) => item.type === "clear").length,
    clearCountBefore,
  );
  const timeline = timelineText(environment);
  assert.match(timeline, /flow\.output_backlog_high/);
  assert.match(timeline, /buffered_samples=300000/);
  assert.match(timeline, /capacity_samples=1440000/);
  assert.equal(
    environment.document.getElementById("playbackBuffer").textContent,
    "12500 / 12500 / 12000 / 60000 ms",
  );

  return {
    assistant_status: assistant.dataset.status,
    cancel_count: sentControls.filter((item) => item.type === "client.cancel").length,
    clear_delta: playerMessages.filter((item) => item.type === "clear").length - clearCountBefore,
    epoch: epochBefore,
    playback_buffer: environment.document.getElementById("playbackBuffer").textContent,
    quality: environment.document.getElementById("qualityBadge").textContent,
  };
}

function hardCapacity(appPath) {
  const environment = createEnvironment(appPath);
  const { playerMessages, sentControls } = installOpenSession(environment);
  const assistant = openStreamingAssistant(environment, "response-hard-capacity");
  const epochBefore = evaluate(environment, "state.currentEpoch");

  deliverPlayerMessage(environment, {
    type: "output_capacity_exceeded",
    epoch: epochBefore,
    samples: 9_600,
    total_dropped_samples: 9_600,
    buffered_samples: 1_435_000,
    soft_capacity_samples: 288_000,
    capacity_samples: 1_440_000,
    epoch_high_water_samples: 1_435_000,
    total_received_samples: 1_435_000,
  });

  const epochAfter = evaluate(environment, "state.currentEpoch");
  const cancels = sentControls.filter((item) => item.type === "client.cancel");
  const clears = playerMessages.filter((item) => item.type === "clear");
  assert.equal(epochAfter, epochBefore + 1);
  assert.equal(cancels.length, 1);
  assert.equal(cancels[0].playback_epoch, epochAfter);
  assert.ok(clears.some((item) => item.epoch === epochAfter));
  assert.equal(assistant.dataset.status, "error");
  assert.match(timelineText(environment), /flow\.output_capacity_exceeded/);
  assert.equal(
    environment.document.getElementById("outputDropCount").textContent,
    "9600 samples / 400 ms",
  );

  return {
    assistant_status: assistant.dataset.status,
    cancel_count: cancels.length,
    epoch_before: epochBefore,
    epoch_after: epochAfter,
    output_drop: environment.document.getElementById("outputDropCount").textContent,
  };
}

async function suspendedResponseResume(appPath) {
  const environment = createEnvironment(appPath);
  const { playerMessages } = installOpenSession(environment);
  let resumeCalls = 0;
  const playerContext = {
    state: "suspended",
    async resume() {
      resumeCalls += 1;
      this.state = "running";
    },
  };
  environment.context.__capacityPlayerContext = playerContext;
  evaluate(environment, "state.playerContext = __capacityPlayerContext");

  dispatch(environment, "speech.started", { playback_epoch: 1 });
  dispatch(environment, "playback.started", {
    playback_epoch: 1,
    response_ref: "response-resume",
  });
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(resumeCalls, 1);
  assert.equal(playerContext.state, "running");
  assert.ok(playerMessages.some((item) => item.type === "response_state" && item.active === true));
  return { context_state: playerContext.state, resume_calls: resumeCalls };
}

async function main() {
  const scenario = process.argv[2];
  const appPath = process.argv[3];
  assert.ok(scenario && appPath, "usage: harness scenario app.js");
  const scenarios = {
    hard_capacity: () => hardCapacity(appPath),
    soft_backlog: () => softBacklog(appPath),
    suspended_resume: () => suspendedResponseResume(appPath),
  };
  assert.ok(Object.hasOwn(scenarios, scenario), `unknown scenario: ${scenario}`);
  const metrics = await scenarios[scenario]();
  process.stdout.write(JSON.stringify({ status: "passed", scenario, ...metrics }));
}

main().catch((error) => {
  process.stderr.write(`${error?.stack || error}\n`);
  process.exitCode = 1;
});
