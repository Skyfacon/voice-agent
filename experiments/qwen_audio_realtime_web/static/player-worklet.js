const SOURCE_SAMPLE_RATE = 24_000;
const SOFT_CAPACITY_SECONDS = 12;
const SOFT_RECOVERY_RATIO = 0.75;
const HARD_CAPACITY_SECONDS = 60;
const UNDERFLOW_GRACE_MS = 20;
const TELEMETRY_INTERVAL_MS = 500;

class Pcm24kChunkPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sourceSampleRate = SOURCE_SAMPLE_RATE;
    this.softCapacity = this.sourceSampleRate * SOFT_CAPACITY_SECONDS;
    this.softRecovery = this.softCapacity * SOFT_RECOVERY_RATIO;
    this.capacity = this.sourceSampleRate * HARD_CAPACITY_SECONDS;
    this.chunks = [];
    this.headChunkIndex = 0;
    this.headSampleIndex = 0;
    this.available = 0;
    this.readPhase = 0;
    this.epoch = 0;
    this.playing = false;
    this.responseActive = false;
    this.hadAudioInResponse = false;
    this.emptyOutputFrames = 0;
    this.underflowLatched = false;
    this.softWatermarkLatched = false;
    this.outputFramesSinceTelemetry = 0;

    // Metadata-only counters. PCM never leaves this processor through the
    // message port, and clear() releases all queued ArrayBuffer references.
    this.highWaterSamples = 0;
    this.epochHighWaterSamples = 0;
    this.totalReceivedSamples = 0;
    this.totalRenderedSamples = 0;
    this.totalDroppedSamples = 0;
    this.totalLateDroppedSamples = 0;
    this.totalClearedSamples = 0;
    this.underflowCount = 0;
    this.softWatermarkCount = 0;
    this.softRecoveryCount = 0;

    this.port.onmessage = (event) => this.handleMessage(event.data || {});
  }

  handleMessage(message) {
    if (message.type === "clear") {
      const requestedEpoch = Number(message.epoch);
      if (Number.isInteger(requestedEpoch) && requestedEpoch >= this.epoch) {
        this.epoch = requestedEpoch;
        const clearedSamples = this.clearBuffer();
        this.port.postMessage({
          type: "cleared",
          epoch: this.epoch,
          token: message.token,
          cleared_samples: clearedSamples,
        });
        this.emitBufferStatus("clear");
      }
      return;
    }

    if (message.type === "response_state") {
      this.setResponseState(message.epoch, message.active === true);
      return;
    }

    if (message.type === "enqueue") {
      this.enqueue(message.epoch, message.pcm);
    }
  }

  setResponseState(rawEpoch, active) {
    const responseEpoch = Number(rawEpoch);
    if (!Number.isInteger(responseEpoch) || responseEpoch !== this.epoch) {
      return;
    }
    this.responseActive = active;
    this.emptyOutputFrames = 0;
    this.underflowLatched = false;
    if (active) {
      this.hadAudioInResponse = this.available > 0;
    } else {
      this.hadAudioInResponse = false;
    }
    this.emitBufferStatus(active ? "response_started" : "response_done");
  }

  clearBuffer() {
    const clearedSamples = this.available;
    this.totalClearedSamples += clearedSamples;
    this.chunks.length = 0;
    this.headChunkIndex = 0;
    this.headSampleIndex = 0;
    this.available = 0;
    this.readPhase = 0;
    this.epochHighWaterSamples = 0;
    this.responseActive = false;
    this.hadAudioInResponse = false;
    this.emptyOutputFrames = 0;
    this.underflowLatched = false;
    this.softWatermarkLatched = false;
    this.setPlaying(false);
    return clearedSamples;
  }

  enqueue(rawEpoch, rawPcm) {
    const frameEpoch = Number(rawEpoch);
    if (
      !Number.isInteger(frameEpoch)
      || !(rawPcm instanceof ArrayBuffer)
      || rawPcm.byteLength === 0
      || rawPcm.byteLength % 2 !== 0
    ) {
      return;
    }

    const pcm = new Int16Array(rawPcm);
    if (frameEpoch < this.epoch) {
      this.totalLateDroppedSamples += pcm.length;
      this.port.postMessage({
        type: "late_audio_dropped",
        epoch: frameEpoch,
        samples: pcm.length,
        total_late_dropped_samples: this.totalLateDroppedSamples,
      });
      return;
    }
    if (frameEpoch > this.epoch) {
      this.epoch = frameEpoch;
      this.clearBuffer();
    }

    // Preserve chronological audio at the hard bound. Rejecting the entire
    // incoming chunk lets the main thread cancel/advance the epoch cleanly;
    // deleting already queued speech would create arbitrary phoneme splices.
    if (pcm.length > this.capacity - this.available) {
      this.totalDroppedSamples += pcm.length;
      this.port.postMessage({
        type: "output_capacity_exceeded",
        epoch: this.epoch,
        samples: pcm.length,
        total_dropped_samples: this.totalDroppedSamples,
        buffered_samples: this.available,
        soft_capacity_samples: this.softCapacity,
        capacity_samples: this.capacity,
        epoch_high_water_samples: this.epochHighWaterSamples,
        total_received_samples: this.totalReceivedSamples,
      });
      this.emitBufferStatus("capacity_exceeded");
      return;
    }

    // Store the transferred PCM chunk without a sample-by-sample copy. The
    // render callback converts only the samples needed for the current quantum,
    // so a provider burst cannot monopolize the AudioWorklet message handler.
    this.chunks.push(pcm);
    this.available += pcm.length;
    this.totalReceivedSamples += pcm.length;
    this.epochHighWaterSamples = Math.max(this.epochHighWaterSamples, this.available);
    this.highWaterSamples = Math.max(this.highWaterSamples, this.available);
    if (this.responseActive) {
      this.hadAudioInResponse = true;
    }
    this.observeBacklogWatermark();
    this.emitBufferStatus("enqueue");
  }

  observeBacklogWatermark() {
    if (!this.softWatermarkLatched && this.available >= this.softCapacity) {
      this.softWatermarkLatched = true;
      this.softWatermarkCount += 1;
      this.port.postMessage({
        type: "output_backlog_high",
        epoch: this.epoch,
        buffered_samples: this.available,
        soft_capacity_samples: this.softCapacity,
        capacity_samples: this.capacity,
        epoch_high_water_samples: this.epochHighWaterSamples,
        total_received_samples: this.totalReceivedSamples,
        soft_watermark_count: this.softWatermarkCount,
      });
      return;
    }
    if (this.softWatermarkLatched && this.available < this.softRecovery) {
      this.softWatermarkLatched = false;
      this.softRecoveryCount += 1;
      this.port.postMessage({
        type: "output_backlog_recovered",
        epoch: this.epoch,
        buffered_samples: this.available,
        soft_capacity_samples: this.softCapacity,
        capacity_samples: this.capacity,
        epoch_high_water_samples: this.epochHighWaterSamples,
        total_received_samples: this.totalReceivedSamples,
        soft_recovery_count: this.softRecoveryCount,
      });
    }
  }

  peekSample(offset) {
    let chunkIndex = this.headChunkIndex;
    let sampleIndex = this.headSampleIndex + offset;
    while (chunkIndex < this.chunks.length) {
      const chunk = this.chunks[chunkIndex];
      if (chunk && sampleIndex < chunk.length) {
        return chunk[sampleIndex];
      }
      if (chunk) {
        sampleIndex -= chunk.length;
      }
      chunkIndex += 1;
    }
    return 0;
  }

  consumeSamples(rawCount) {
    let remaining = Math.min(Math.max(0, rawCount), this.available);
    const consumed = remaining;
    while (remaining > 0 && this.headChunkIndex < this.chunks.length) {
      const chunk = this.chunks[this.headChunkIndex];
      if (!chunk) {
        this.headChunkIndex += 1;
        this.headSampleIndex = 0;
        continue;
      }
      const inChunk = chunk.length - this.headSampleIndex;
      const step = Math.min(remaining, inChunk);
      this.headSampleIndex += step;
      remaining -= step;
      if (this.headSampleIndex === chunk.length) {
        this.chunks[this.headChunkIndex] = null;
        this.headChunkIndex += 1;
        this.headSampleIndex = 0;
      }
    }

    this.available -= consumed;
    this.totalRenderedSamples += consumed;
    if (this.available === 0) {
      this.chunks.length = 0;
      this.headChunkIndex = 0;
      this.headSampleIndex = 0;
      this.readPhase = 0;
    } else if (this.headChunkIndex >= 64 && this.headChunkIndex * 2 >= this.chunks.length) {
      this.chunks = this.chunks.slice(this.headChunkIndex);
      this.headChunkIndex = 0;
    }
    return consumed;
  }

  emitBufferStatus(reason) {
    this.port.postMessage({
      type: "buffer_status",
      epoch: this.epoch,
      reason,
      buffered_samples: this.available,
      capacity_samples: this.capacity,
      soft_capacity_samples: this.softCapacity,
      soft_watermark_latched: this.softWatermarkLatched,
      soft_watermark_count: this.softWatermarkCount,
      soft_recovery_count: this.softRecoveryCount,
      high_water_samples: this.highWaterSamples,
      epoch_high_water_samples: this.epochHighWaterSamples,
      total_received_samples: this.totalReceivedSamples,
      total_rendered_samples: this.totalRenderedSamples,
      total_dropped_samples: this.totalDroppedSamples,
      total_late_dropped_samples: this.totalLateDroppedSamples,
      total_cleared_samples: this.totalClearedSamples,
      underflow_count: this.underflowCount,
    });
  }

  setPlaying(value) {
    if (this.playing === value) {
      return;
    }
    this.playing = value;
    this.port.postMessage({
      type: value ? "playing" : "drained",
      epoch: this.epoch,
    });
  }

  observeUnderflow(rendered, outputFrames) {
    if (rendered > 0) {
      this.emptyOutputFrames = 0;
      this.underflowLatched = false;
      return;
    }
    if (!this.responseActive || !this.hadAudioInResponse) {
      this.emptyOutputFrames = 0;
      return;
    }

    this.emptyOutputFrames += outputFrames;
    const threshold = Math.max(1, Math.round(sampleRate * UNDERFLOW_GRACE_MS / 1_000));
    if (!this.underflowLatched && this.emptyOutputFrames >= threshold) {
      this.underflowLatched = true;
      this.underflowCount += 1;
      this.port.postMessage({
        type: "output_underflow",
        epoch: this.epoch,
        underflow_count: this.underflowCount,
        buffered_samples: this.available,
      });
      this.emitBufferStatus("underflow");
    }
  }

  process(_inputs, outputs) {
    const channels = outputs[0];
    if (!channels || channels.length === 0) {
      return true;
    }

    const primary = channels[0];
    primary.fill(0);
    const ratio = this.sourceSampleRate / sampleRate;
    let rendered = 0;

    for (let outputIndex = 0; outputIndex < primary.length; outputIndex += 1) {
      if (this.available === 0) {
        break;
      }
      const left = this.peekSample(0) / 0x8000;
      const right = (this.available > 1 ? this.peekSample(1) : this.peekSample(0)) / 0x8000;
      primary[outputIndex] = left * (1 - this.readPhase) + right * this.readPhase;

      const nextPhase = this.readPhase + ratio;
      const phaseConsumed = Math.floor(nextPhase);
      this.readPhase = nextPhase - phaseConsumed;
      this.consumeSamples(Math.min(phaseConsumed, this.available));
      rendered += 1;
    }

    for (let channelIndex = 1; channelIndex < channels.length; channelIndex += 1) {
      channels[channelIndex].set(primary);
    }
    this.observeBacklogWatermark();
    this.observeUnderflow(rendered, primary.length);
    this.setPlaying(rendered > 0);

    this.outputFramesSinceTelemetry += primary.length;
    const telemetryFrames = Math.max(1, Math.round(sampleRate * TELEMETRY_INTERVAL_MS / 1_000));
    if (this.outputFramesSinceTelemetry >= telemetryFrames) {
      this.outputFramesSinceTelemetry %= telemetryFrames;
      if (this.playing || this.available > 0 || this.responseActive) {
        this.emitBufferStatus("periodic");
      }
    }
    return true;
  }
}

registerProcessor("pcm24k-ring-player", Pcm24kChunkPlayerProcessor);
