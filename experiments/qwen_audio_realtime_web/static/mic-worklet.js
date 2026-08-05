class Pcm16CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16_000;
    this.chunkSamples = 1_600;
    this.samplesPerOutput = sampleRate / this.targetSampleRate;
    this.resamplePosition = 0;
    this.carry = new Float32Array(0);
    this.chunk = new Int16Array(this.chunkSamples);
    this.chunkOffset = 0;
    this.levelEnergy = 0;
    this.levelSamples = 0;

    this.port.onmessage = (event) => {
      if (event.data?.type === "reset") {
        this.resamplePosition = 0;
        this.carry = new Float32Array(0);
        this.chunk = new Int16Array(this.chunkSamples);
        this.chunkOffset = 0;
        this.levelEnergy = 0;
        this.levelSamples = 0;
      }
    };
  }

  process(inputs) {
    const channels = inputs[0];
    if (!channels || channels.length === 0 || channels[0].length === 0) {
      return true;
    }

    const frameLength = channels[0].length;
    const mono = new Float32Array(frameLength);
    if (channels.length === 1) {
      mono.set(channels[0]);
    } else {
      for (let index = 0; index < frameLength; index += 1) {
        let sum = 0;
        for (const channel of channels) {
          sum += channel[index] || 0;
        }
        mono[index] = sum / channels.length;
      }
    }

    for (let index = 0; index < mono.length; index += 1) {
      const value = mono[index];
      this.levelEnergy += value * value;
      this.levelSamples += 1;
    }

    const source = new Float32Array(this.carry.length + mono.length);
    source.set(this.carry);
    source.set(mono, this.carry.length);

    while (this.resamplePosition + 1 < source.length) {
      const leftIndex = Math.floor(this.resamplePosition);
      const fraction = this.resamplePosition - leftIndex;
      const value = source[leftIndex] * (1 - fraction) + source[leftIndex + 1] * fraction;
      const clipped = Math.max(-1, Math.min(1, value));
      this.chunk[this.chunkOffset] = clipped < 0
        ? Math.round(clipped * 0x8000)
        : Math.round(clipped * 0x7fff);
      this.chunkOffset += 1;
      this.resamplePosition += this.samplesPerOutput;

      if (this.chunkOffset === this.chunkSamples) {
        const pcm = this.chunk;
        const level = this.levelSamples > 0
          ? Math.min(1, Math.sqrt(this.levelEnergy / this.levelSamples))
          : 0;
        this.port.postMessage(
          { type: "pcm", pcm: pcm.buffer, level },
          [pcm.buffer],
        );
        this.chunk = new Int16Array(this.chunkSamples);
        this.chunkOffset = 0;
        this.levelEnergy = 0;
        this.levelSamples = 0;
      }
    }

    // Keep the final source sample as the left interpolation anchor for the
    // next render quantum. Consuming past it would reset the cross-quantum
    // phase (for example, 48 kHz input would drift above 16 kHz output).
    const consumed = Math.min(
      Math.floor(this.resamplePosition),
      source.length - 1,
    );
    this.carry = source.slice(consumed);
    this.resamplePosition -= consumed;
    return true;
  }
}

registerProcessor("pcm16-capture", Pcm16CaptureProcessor);
