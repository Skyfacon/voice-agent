"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const SOURCE_SAMPLE_RATE = 24_000;
const OBSERVED_CHUNK_SAMPLES = 9_600; // 19,200-byte PCM16 = 400 ms.
const OBSERVED_BURST_CHUNKS = 39; // 15.6 seconds from the physical-device run.
const RENDER_QUANTUM = 128;

function loadProcessor(workletPath, outputSampleRate) {
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
    sampleRate: outputSampleRate,
    registerProcessor(name, constructor) {
      assert.equal(name, "pcm24k-ring-player");
      Processor = constructor;
    },
  });
  vm.runInContext(fs.readFileSync(workletPath, "utf8"), context, {
    filename: workletPath,
  });
  assert.ok(Processor, "worklet did not register its processor");

  return { processor: new Processor(), emitted };
}

function pcmChunk(sampleCount, value) {
  assert.ok(Number.isInteger(value) && value > 0 && value <= 32_767);
  const samples = new Int16Array(sampleCount);
  samples.fill(value);
  return samples.buffer;
}

function send(processor, message) {
  assert.equal(typeof processor.port.onmessage, "function");
  processor.port.onmessage({ data: message });
}

function enqueue(processor, epoch, sampleCount, value) {
  send(processor, {
    type: "enqueue",
    epoch,
    pcm: pcmChunk(sampleCount, value),
  });
}

function renderQuanta(processor, quantumCount, rendered) {
  for (let index = 0; index < quantumCount; index += 1) {
    const primary = new Float32Array(RENDER_QUANTUM);
    assert.equal(processor.process([], [[primary]]), true);
    for (const sample of primary) {
      if (sample !== 0) rendered.push(sample);
    }
  }
}

function renderUntilDrained(processor, emitted, rendered, maxQuanta = 30_000) {
  let cursor = emitted.length;
  let sawPlaying = emitted.some((message) => message?.type === "playing");
  for (let index = 0; index < maxQuanta; index += 1) {
    renderQuanta(processor, 1, rendered);
    for (; cursor < emitted.length; cursor += 1) {
      if (emitted[cursor]?.type === "playing") sawPlaying = true;
      if (sawPlaying && emitted[cursor]?.type === "drained") return;
    }
  }
  assert.fail("player did not drain within the bounded render budget");
}

function latestMessage(emitted, type) {
  return [...emitted].reverse().find((message) => message?.type === type) ?? null;
}

function assertNoUnexpectedDrop(emitted) {
  const drops = emitted.filter((message) =>
    ["output_overflow", "output_capacity_exceeded"].includes(message?.type),
  );
  assert.deepEqual(drops, [], "accepted playback profile unexpectedly dropped output");
  const status = latestMessage(emitted, "buffer_status");
  assert.ok(status, "player must expose metadata-only buffer status");
  assert.equal(status.total_dropped_samples, 0);
}

function assertMetadataOnly(emitted) {
  const forbiddenKeys = new Set([
    "audio",
    "base64",
    "data",
    "delta",
    "payload",
    "pcm",
    "raw_audio",
  ]);

  function visit(value, path) {
    assert.equal(value instanceof ArrayBuffer, false, `${path} leaked an ArrayBuffer`);
    assert.equal(ArrayBuffer.isView(value), false, `${path} leaked a typed array`);
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      assert.equal(forbiddenKeys.has(key.toLowerCase()), false, `${path}.${key} is raw-audio-shaped`);
      visit(child, `${path}.${key}`);
    }
  }

  emitted.forEach((message, index) => visit(message, `message[${index}]`));
}

function assertTaggedSequence(rendered, chunkValues, samplesPerChunk) {
  const expectedSamples = chunkValues.length * samplesPerChunk;
  assert.equal(rendered.length, expectedSamples);
  let offset = 0;
  for (let chunkIndex = 0; chunkIndex < chunkValues.length; chunkIndex += 1) {
    const expectedCount = samplesPerChunk;
    const expected = chunkValues[chunkIndex] / 0x8000;
    for (let index = 0; index < expectedCount; index += 1) {
      assert.ok(
        Math.abs(rendered[offset] - expected) < 1e-7,
        `playback order changed at rendered sample ${offset}`,
      );
      offset += 1;
    }
  }
}

function observedBurst(workletPath) {
  const { processor, emitted } = loadProcessor(workletPath, SOURCE_SAMPLE_RATE);
  const values = Array.from(
    { length: OBSERVED_BURST_CHUNKS },
    (_unused, index) => (index + 1) * 700,
  );
  for (const value of values) {
    enqueue(processor, 7, OBSERVED_CHUNK_SAMPLES, value);
  }

  const afterEnqueue = latestMessage(emitted, "buffer_status");
  const totalSamples = OBSERVED_BURST_CHUNKS * OBSERVED_CHUNK_SAMPLES;
  assert.ok(afterEnqueue, "player did not report buffer occupancy");
  assert.equal(afterEnqueue.buffered_samples, totalSamples);
  assert.ok(afterEnqueue.capacity_samples >= totalSamples);
  assert.equal(afterEnqueue.soft_capacity_samples, SOURCE_SAMPLE_RATE * 12);
  assert.equal(afterEnqueue.capacity_samples, SOURCE_SAMPLE_RATE * 60);
  assert.ok(afterEnqueue.high_water_samples >= totalSamples);
  assert.ok(afterEnqueue.epoch_high_water_samples >= totalSamples);
  assert.equal(afterEnqueue.total_received_samples, totalSamples);
  assertNoUnexpectedDrop(emitted);

  let highEvents = emitted.filter((message) => message?.type === "output_backlog_high");
  assert.equal(highEvents.length, 1, "soft backlog warning must latch during one burst");
  assert.equal(highEvents[0].soft_capacity_samples, SOURCE_SAMPLE_RATE * 12);
  assert.equal(highEvents[0].capacity_samples, SOURCE_SAMPLE_RATE * 60);
  assert.ok(highEvents[0].buffered_samples >= highEvents[0].soft_capacity_samples);
  assert.equal(highEvents[0].epoch_high_water_samples, highEvents[0].buffered_samples);

  const rendered = [];
  renderUntilDrained(processor, emitted, rendered);
  assertTaggedSequence(rendered, values, OBSERVED_CHUNK_SAMPLES);
  const recoveredEvents = emitted.filter(
    (message) => message?.type === "output_backlog_recovered",
  );
  assert.equal(recoveredEvents.length, 1, "draining below the recovery level must rearm soft warning");
  assert.ok(
    recoveredEvents[0].buffered_samples < recoveredEvents[0].soft_capacity_samples * 0.75,
  );

  enqueue(processor, 7, SOURCE_SAMPLE_RATE * 12, 30_000);
  highEvents = emitted.filter((message) => message?.type === "output_backlog_high");
  assert.equal(highEvents.length, 2, "recovered soft warning must fire on a later crossing");
  renderUntilDrained(processor, emitted, rendered);
  assertMetadataOnly(emitted);
  return {
    buffered_peak_samples: afterEnqueue.high_water_samples,
    chunks: values.length,
    rendered_samples: totalSamples,
    soft_capacity_samples: afterEnqueue.soft_capacity_samples,
    capacity_samples: afterEnqueue.capacity_samples,
    soft_high_events_during_burst: 1,
    soft_high_events_after_rearm: highEvents.length,
    soft_recovery_events: recoveredEvents.length,
  };
}

function queueRotation(workletPath) {
  const { processor, emitted } = loadProcessor(workletPath, SOURCE_SAMPLE_RATE);
  const rendered = [];
  const values = Array.from({ length: 35 }, (_unused, index) => (index + 1) * 500);
  let next = 0;
  for (let round = 0; round < 5; round += 1) {
    for (let count = 0; count < 7; count += 1) {
      enqueue(processor, 9, OBSERVED_CHUNK_SAMPLES, values[next]);
      next += 1;
    }
    if (round < 4) {
      renderQuanta(
        processor,
        (4 * OBSERVED_CHUNK_SAMPLES) / RENDER_QUANTUM,
        rendered,
      );
    }
  }
  renderUntilDrained(processor, emitted, rendered);

  assertNoUnexpectedDrop(emitted);
  assertTaggedSequence(rendered, values, OBSERVED_CHUNK_SAMPLES);
  assertMetadataOnly(emitted);
  return { chunks: values.length, rendered_samples: rendered.length };
}

function clearAndLateEpoch(workletPath) {
  const { processor, emitted } = loadProcessor(workletPath, SOURCE_SAMPLE_RATE);
  enqueue(processor, 3, OBSERVED_CHUNK_SAMPLES, 1_111);
  enqueue(processor, 3, OBSERVED_CHUNK_SAMPLES, 2_222);
  enqueue(processor, 3, SOURCE_SAMPLE_RATE * 12, 2_500);
  assert.equal(
    emitted.filter((message) => message?.type === "output_backlog_high").length,
    1,
  );
  renderQuanta(processor, 10, []);

  send(processor, { type: "clear", epoch: 4, token: 73 });
  const cleared = latestMessage(emitted, "cleared");
  assert.deepEqual(
    { epoch: cleared?.epoch, token: cleared?.token },
    { epoch: 4, token: 73 },
  );
  const afterClear = latestMessage(emitted, "buffer_status");
  assert.ok(afterClear, "clear must publish the empty buffer state");
  assert.equal(afterClear.buffered_samples, 0);
  assert.equal(afterClear.epoch_high_water_samples, 0);
  assert.equal(afterClear.soft_watermark_latched, false);

  enqueue(processor, 3, OBSERVED_CHUNK_SAMPLES, 3_333);
  const late = latestMessage(emitted, "late_audio_dropped");
  assert.equal(late?.epoch, 3);
  enqueue(processor, 4, OBSERVED_CHUNK_SAMPLES, 4_444);

  const rendered = [];
  renderUntilDrained(processor, emitted, rendered);
  assertTaggedSequence(rendered, [4_444], OBSERVED_CHUNK_SAMPLES);
  assertMetadataOnly(emitted);
  return { epoch: 4, late_samples: late?.samples ?? OBSERVED_CHUNK_SAMPLES };
}

function sampleRatePath(workletPath, outputSampleRate) {
  const { processor, emitted } = loadProcessor(workletPath, outputSampleRate);
  enqueue(processor, 1, SOURCE_SAMPLE_RATE, 8_192);
  const rendered = [];
  renderUntilDrained(processor, emitted, rendered);

  const expectedCount = Math.ceil(
    SOURCE_SAMPLE_RATE * outputSampleRate / SOURCE_SAMPLE_RATE,
  );
  assert.equal(rendered.length, expectedCount);
  for (const sample of rendered) {
    assert.ok(Math.abs(sample - 0.25) < 1e-7);
  }
  assertNoUnexpectedDrop(emitted);
  assertMetadataOnly(emitted);
  return { output_sample_rate: outputSampleRate, rendered_samples: rendered.length };
}

function underflowAccounting(workletPath) {
  const { processor, emitted } = loadProcessor(workletPath, SOURCE_SAMPLE_RATE);
  send(processor, { type: "clear", epoch: 5, token: 91 });
  send(processor, { type: "response_state", epoch: 5, active: true });
  enqueue(processor, 5, RENDER_QUANTUM * 2, 6_000);
  renderUntilDrained(processor, emitted, []);
  renderQuanta(processor, 12, []);

  let underflows = emitted.filter((message) => message?.type === "output_underflow");
  assert.equal(underflows.length, 1, "one starvation interval must count once");
  assert.equal(underflows[0].underflow_count, 1);
  assert.equal(latestMessage(emitted, "buffer_status")?.underflow_count, 1);

  send(processor, { type: "response_state", epoch: 5, active: false });
  enqueue(processor, 5, RENDER_QUANTUM * 2, 7_000);
  renderUntilDrained(processor, emitted, []);
  renderQuanta(processor, 12, []);
  underflows = emitted.filter((message) => message?.type === "output_underflow");
  assert.equal(underflows.length, 1, "normal inactive drain must not count as starvation");
  assert.equal(latestMessage(emitted, "buffer_status")?.underflow_count, 1);
  assertMetadataOnly(emitted);
  return { active_underflows: 1, inactive_underflows: 0 };
}

function boundedCapacity(workletPath) {
  const { processor, emitted } = loadProcessor(workletPath, SOURCE_SAMPLE_RATE);
  enqueue(processor, 12, OBSERVED_CHUNK_SAMPLES, 1_234);
  const initialStatus = latestMessage(emitted, "buffer_status");
  assert.ok(initialStatus, "player did not expose a capacity");
  const capacity = initialStatus.capacity_samples;
  const softCapacity = initialStatus.soft_capacity_samples;
  assert.ok(Number.isSafeInteger(capacity));
  assert.equal(softCapacity, SOURCE_SAMPLE_RATE * 12);
  assert.equal(capacity, SOURCE_SAMPLE_RATE * 60);
  assert.ok(capacity >= OBSERVED_BURST_CHUNKS * OBSERVED_CHUNK_SAMPLES);
  assert.ok(capacity <= SOURCE_SAMPLE_RATE * 120, "player capacity is not meaningfully bounded");

  enqueue(processor, 12, capacity, 2_468);
  const overflow = latestMessage(emitted, "output_capacity_exceeded");
  assert.ok(overflow, "hard capacity must reject the new frame explicitly");
  assert.equal(overflow.samples, capacity);
  assert.equal(overflow.soft_capacity_samples, softCapacity);
  assert.equal(overflow.capacity_samples, capacity);
  assert.ok(overflow.total_dropped_samples >= capacity);

  const rendered = [];
  renderUntilDrained(processor, emitted, rendered);
  assertTaggedSequence(rendered, [1_234], OBSERVED_CHUNK_SAMPLES);
  assertMetadataOnly(emitted);
  return {
    capacity_samples: capacity,
    soft_capacity_samples: softCapacity,
    rejected_samples: overflow.samples,
    rendered_samples: rendered.length,
  };
}

function main() {
  const scenario = process.argv[2];
  const workletPath = process.argv[3];
  const sampleRate = Number(process.argv[4]);
  assert.ok(scenario && workletPath, "usage: harness scenario worklet [sample-rate]");

  const scenarios = {
    bounded_capacity: () => boundedCapacity(workletPath),
    clear_epoch: () => clearAndLateEpoch(workletPath),
    observed_burst: () => observedBurst(workletPath),
    queue_rotation: () => queueRotation(workletPath),
    sample_rate: () => sampleRatePath(workletPath, sampleRate),
    underflow: () => underflowAccounting(workletPath),
  };
  assert.ok(Object.hasOwn(scenarios, scenario), `unknown scenario: ${scenario}`);
  const metrics = scenarios[scenario]();
  process.stdout.write(JSON.stringify({ status: "passed", scenario, ...metrics }));
}

main();
