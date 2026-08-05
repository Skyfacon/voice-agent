"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const RENDER_QUANTUM = 128;

function loadProcessor(workletPath, expectedName, workletSampleRate) {
  const emitted = [];
  let Processor = null;

  class WorkletPort {
    constructor() {
      this.onmessage = null;
    }

    postMessage(message) {
      emitted.push(message);
    }
  }

  class AudioWorkletProcessor {
    constructor() {
      this.port = new WorkletPort();
    }
  }

  const context = vm.createContext({
    ArrayBuffer,
    AudioWorkletProcessor,
    Float32Array,
    Int16Array,
    Math,
    Number,
    sampleRate: workletSampleRate,
    registerProcessor(name, constructor) {
      assert.equal(name, expectedName);
      Processor = constructor;
    },
  });
  vm.runInContext(fs.readFileSync(workletPath, "utf8"), context, {
    filename: workletPath,
  });
  assert.ok(Processor, "worklet did not register a processor");
  return { processor: new Processor(), emitted };
}

function send(processor, data) {
  assert.equal(typeof processor.port.onmessage, "function");
  processor.port.onmessage({ data });
}

function pcm(samples, value) {
  const result = new Int16Array(samples);
  result.fill(value);
  return result.buffer;
}

function captureFrame(workletPath) {
  const { processor, emitted } = loadProcessor(
    workletPath,
    "qfs-pcm16-capture",
    48_000,
  );
  const input = new Float32Array(RENDER_QUANTUM);
  input.fill(0.25);
  for (let index = 0; index < 40; index += 1) {
    assert.equal(processor.process([[input]]), true);
    assert.ok(processor.carry.length <= 32, "resampler carry is not bounded");
  }

  const frames = emitted.filter((message) => message?.type === "pcm");
  assert.equal(frames.length, 1, "5,120 samples at 48 kHz should emit one 100 ms frame");
  assert.equal(frames[0].pcm.byteLength, 3_200);
  assert.ok(frames[0].level > 0);

  send(processor, { type: "active", active: false });
  assert.equal(processor.frameOffset, 0);
  assert.equal(processor.carry.length, 0);
  const before = emitted.length;
  assert.equal(processor.process([[input]]), true);
  assert.equal(emitted.length, before, "inactive capture emitted another PCM frame");
  return { emitted_frames: frames.length, frame_bytes: frames[0].pcm.byteLength };
}

function renderUntilDrained(processor, maximum = 20_000) {
  const rendered = [];
  let sawPlaying = false;
  for (let quantum = 0; quantum < maximum; quantum += 1) {
    const output = new Float32Array(RENDER_QUANTUM);
    assert.equal(processor.process([], [[output]]), true);
    for (const sample of output) {
      if (sample !== 0) {
        sawPlaying = true;
        rendered.push(sample);
      }
    }
    if (sawPlaying && processor.available === 0) return rendered;
  }
  assert.fail("player did not drain within bounded render budget");
}

function assertMetadataOnly(emitted) {
  for (const [index, message] of emitted.entries()) {
    assert.equal(message instanceof ArrayBuffer, false, `message[${index}] leaked audio`);
    assert.equal(ArrayBuffer.isView(message), false, `message[${index}] leaked audio view`);
    for (const [key, value] of Object.entries(message || {})) {
      assert.equal(key.toLowerCase().includes("pcm"), false, `${key} is raw-audio-shaped`);
      assert.equal(value instanceof ArrayBuffer, false, `${key} leaked audio`);
      assert.equal(ArrayBuffer.isView(value), false, `${key} leaked audio view`);
    }
  }
}

function playerEpoch(workletPath) {
  const { processor, emitted } = loadProcessor(
    workletPath,
    "qfs-pcm24k-player",
    48_000,
  );
  send(processor, { type: "enqueue", epoch: 1, pcm: pcm(2_400, 4_000) });
  send(processor, { type: "clear", epoch: 2, token: "clear-safe" });
  send(processor, { type: "enqueue", epoch: 1, pcm: pcm(2_400, 6_000) });
  send(processor, { type: "enqueue", epoch: 2, pcm: pcm(2_400, 8_000) });

  const late = emitted.find((message) => message?.type === "late_audio_dropped");
  assert.ok(late, "old epoch PCM was not rejected");
  assert.equal(late.epoch, 1);
  const rendered = renderUntilDrained(processor);
  assert.equal(rendered.length, 4_800);
  assert.ok(rendered.every((sample) => Math.abs(sample - 0.244140625) < 1e-7));
  assertMetadataOnly(emitted);
  return {
    epoch: processor.epoch,
    late_dropped_frames: processor.lateDroppedFrames,
    rendered_samples: rendered.length,
  };
}

function playerCapacity(workletPath) {
  const { processor, emitted } = loadProcessor(
    workletPath,
    "qfs-pcm24k-player",
    24_000,
  );
  send(processor, { type: "enqueue", epoch: 3, pcm: pcm(2_400, 2_000) });
  const capacity = 24_000 * 15;
  send(processor, { type: "enqueue", epoch: 3, pcm: pcm(capacity, 4_000) });

  const rejected = emitted.find((message) => message?.type === "output_capacity_exceeded");
  assert.ok(rejected, "hard capacity did not reject the new frame");
  assert.equal(rejected.samples, capacity);
  assert.equal(processor.available, 2_400, "existing FIFO should remain intact");
  const rendered = renderUntilDrained(processor);
  assert.equal(rendered.length, 2_400);
  assertMetadataOnly(emitted);
  return {
    capacity_samples: capacity,
    dropped_frames: processor.droppedFrames,
    rendered_samples: rendered.length,
  };
}

function main() {
  const scenario = process.argv[2];
  const path = process.argv[3];
  assert.ok(scenario && path, "usage: worklet_harness.js scenario path");
  const scenarios = {
    capture_frame: () => captureFrame(path),
    player_capacity: () => playerCapacity(path),
    player_epoch: () => playerEpoch(path),
  };
  assert.ok(Object.hasOwn(scenarios, scenario), `unknown scenario: ${scenario}`);
  const result = scenarios[scenario]();
  process.stdout.write(JSON.stringify({ status: "passed", scenario, ...result }));
}

main();
