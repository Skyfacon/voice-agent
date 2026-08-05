const SOURCE_SAMPLE_RATE = 24_000;
const SOFT_CAPACITY_SAMPLES = SOURCE_SAMPLE_RATE * 8;
const HARD_CAPACITY_SAMPLES = SOURCE_SAMPLE_RATE * 15;
const MAX_CHUNKS = 512;
const TELEMETRY_FRAMES = 24_000;

class QfsPcm24kPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.epoch = 0;
    this.chunks = [];
    this.headChunk = 0;
    this.headSample = 0;
    this.available = 0;
    this.phase = 0;
    this.playing = false;
    this.responseActive = false;
    this.framesSinceTelemetry = 0;
    this.droppedFrames = 0;
    this.lateDroppedFrames = 0;
    this.highWaterSamples = 0;

    this.port.onmessage = (event) => this.handleMessage(event.data || {});
  }

  handleMessage(message) {
    if (message.type === "clear") {
      const nextEpoch = Number(message.epoch);
      if (Number.isInteger(nextEpoch) && nextEpoch >= this.epoch) {
        this.epoch = nextEpoch;
        const clearedSamples = this.clearQueue();
        this.port.postMessage({
          type: "cleared",
          epoch: this.epoch,
          token: message.token,
          cleared_samples: clearedSamples,
        });
        this.emitStatus("clear");
      }
      return;
    }

    if (message.type === "response_state") {
      const epoch = Number(message.epoch);
      if (Number.isInteger(epoch) && epoch === this.epoch) {
        this.responseActive = message.active === true;
        this.emitStatus(this.responseActive ? "playback_begin" : "playback_end");
      }
      return;
    }

    if (message.type === "enqueue") this.enqueue(message.epoch, message.pcm);
  }

  clearQueue() {
    const clearedSamples = this.available;
    this.chunks.length = 0;
    this.headChunk = 0;
    this.headSample = 0;
    this.available = 0;
    this.phase = 0;
    this.responseActive = false;
    this.setPlaying(false);
    return clearedSamples;
  }

  enqueue(rawEpoch, rawPcm) {
    const epoch = Number(rawEpoch);
    if (
      !Number.isInteger(epoch)
      || epoch < 0
      || !(rawPcm instanceof ArrayBuffer)
      || rawPcm.byteLength === 0
      || rawPcm.byteLength % 2 !== 0
    ) return;

    const pcm = new Int16Array(rawPcm);
    if (epoch < this.epoch) {
      this.lateDroppedFrames += 1;
      this.port.postMessage({
        type: "late_audio_dropped",
        epoch,
        samples: pcm.length,
        late_dropped_frames: this.lateDroppedFrames,
      });
      return;
    }

    if (epoch > this.epoch) {
      this.epoch = epoch;
      this.clearQueue();
      this.port.postMessage({ type: "epoch_advanced", epoch });
    }

    const retainedChunks = this.chunks.length - this.headChunk;
    if (
      pcm.length > HARD_CAPACITY_SAMPLES - this.available
      || retainedChunks >= MAX_CHUNKS
    ) {
      this.droppedFrames += 1;
      this.port.postMessage({
        type: "output_capacity_exceeded",
        epoch: this.epoch,
        samples: pcm.length,
        dropped_frames: this.droppedFrames,
      });
      this.emitStatus("capacity_exceeded");
      return;
    }

    this.chunks.push(pcm);
    this.available += pcm.length;
    this.highWaterSamples = Math.max(this.highWaterSamples, this.available);
    if (this.available >= SOFT_CAPACITY_SAMPLES) {
      this.port.postMessage({
        type: "output_backlog_high",
        epoch: this.epoch,
        buffered_samples: this.available,
      });
    }
    this.emitStatus("enqueue");
  }

  peek(offset) {
    let chunkIndex = this.headChunk;
    let sampleIndex = this.headSample + offset;
    while (chunkIndex < this.chunks.length) {
      const chunk = this.chunks[chunkIndex];
      if (chunk && sampleIndex < chunk.length) return chunk[sampleIndex];
      if (chunk) sampleIndex -= chunk.length;
      chunkIndex += 1;
    }
    return 0;
  }

  consume(rawCount) {
    let remaining = Math.min(Math.max(0, rawCount), this.available);
    const consumed = remaining;
    while (remaining > 0 && this.headChunk < this.chunks.length) {
      const chunk = this.chunks[this.headChunk];
      const availableInChunk = chunk.length - this.headSample;
      const step = Math.min(remaining, availableInChunk);
      this.headSample += step;
      remaining -= step;
      if (this.headSample === chunk.length) {
        this.chunks[this.headChunk] = null;
        this.headChunk += 1;
        this.headSample = 0;
      }
    }
    this.available -= consumed;
    if (this.available === 0) {
      this.chunks.length = 0;
      this.headChunk = 0;
      this.headSample = 0;
      this.phase = 0;
    } else if (this.headChunk >= 64 && this.headChunk * 2 >= this.chunks.length) {
      this.chunks = this.chunks.slice(this.headChunk);
      this.headChunk = 0;
    }
  }

  setPlaying(value) {
    if (this.playing === value) return;
    this.playing = value;
    this.port.postMessage({
      type: value ? "playing" : "drained",
      epoch: this.epoch,
    });
  }

  emitStatus(reason) {
    this.port.postMessage({
      type: "buffer_status",
      reason,
      epoch: this.epoch,
      buffered_samples: this.available,
      high_water_samples: this.highWaterSamples,
      capacity_samples: HARD_CAPACITY_SAMPLES,
      soft_capacity_samples: SOFT_CAPACITY_SAMPLES,
      dropped_frames: this.droppedFrames,
      late_dropped_frames: this.lateDroppedFrames,
    });
  }

  process(_inputs, outputs) {
    const channels = outputs[0];
    if (!channels || channels.length === 0) return true;
    const primary = channels[0];
    primary.fill(0);
    const ratio = SOURCE_SAMPLE_RATE / sampleRate;
    let rendered = 0;

    for (let outputIndex = 0; outputIndex < primary.length; outputIndex += 1) {
      if (this.available === 0) break;
      const left = this.peek(0) / 0x8000;
      const right = (this.available > 1 ? this.peek(1) : this.peek(0)) / 0x8000;
      primary[outputIndex] = left * (1 - this.phase) + right * this.phase;
      const nextPhase = this.phase + ratio;
      const consumed = Math.floor(nextPhase);
      this.phase = nextPhase - consumed;
      this.consume(consumed);
      rendered += 1;
    }

    for (let channel = 1; channel < channels.length; channel += 1) {
      channels[channel].set(primary);
    }
    this.setPlaying(rendered > 0);

    this.framesSinceTelemetry += primary.length;
    if (this.framesSinceTelemetry >= TELEMETRY_FRAMES) {
      this.framesSinceTelemetry %= TELEMETRY_FRAMES;
      if (this.available > 0 || this.responseActive) this.emitStatus("periodic");
    }
    return true;
  }
}

registerProcessor("qfs-pcm24k-player", QfsPcm24kPlayerProcessor);
