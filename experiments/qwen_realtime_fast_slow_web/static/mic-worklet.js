const TARGET_SAMPLE_RATE = 16_000;
const FRAME_SAMPLES = 1_600; // 100 ms at 16 kHz.
const MAX_CARRY_SAMPLES = 32;

class QfsPcm16CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / TARGET_SAMPLE_RATE;
    this.position = 0;
    this.carry = new Float32Array(0);
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.frameOffset = 0;
    this.energy = 0;
    this.energySamples = 0;
    this.active = true;

    this.port.onmessage = (event) => {
      const message = event.data || {};
      if (message.type === "reset") {
        this.reset();
      } else if (message.type === "active") {
        this.active = message.active === true;
        if (!this.active) this.reset();
      }
    };
  }

  reset() {
    this.position = 0;
    this.carry = new Float32Array(0);
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.frameOffset = 0;
    this.energy = 0;
    this.energySamples = 0;
  }

  process(inputs) {
    if (!this.active) return true;
    const channels = inputs[0];
    if (!channels || channels.length === 0 || channels[0].length === 0) return true;

    const length = channels[0].length;
    const mono = new Float32Array(length);
    for (let index = 0; index < length; index += 1) {
      let sum = 0;
      for (let channel = 0; channel < channels.length; channel += 1) {
        sum += Number.isFinite(channels[channel][index]) ? channels[channel][index] : 0;
      }
      const value = sum / channels.length;
      mono[index] = value;
      this.energy += value * value;
      this.energySamples += 1;
    }

    const source = new Float32Array(this.carry.length + mono.length);
    source.set(this.carry);
    source.set(mono, this.carry.length);

    while (this.position + 1 < source.length) {
      const left = Math.floor(this.position);
      const fraction = this.position - left;
      const value = source[left] * (1 - fraction) + source[left + 1] * fraction;
      const clipped = Math.max(-1, Math.min(1, value));
      this.frame[this.frameOffset] = clipped < 0
        ? Math.round(clipped * 0x8000)
        : Math.round(clipped * 0x7fff);
      this.frameOffset += 1;
      this.position += this.step;

      if (this.frameOffset === FRAME_SAMPLES) {
        const completed = this.frame;
        const level = this.energySamples > 0
          ? Math.min(1, Math.sqrt(this.energy / this.energySamples))
          : 0;
        this.port.postMessage(
          { type: "pcm", pcm: completed.buffer, level },
          [completed.buffer],
        );
        this.frame = new Int16Array(FRAME_SAMPLES);
        this.frameOffset = 0;
        this.energy = 0;
        this.energySamples = 0;
      }
    }

    const consumed = Math.min(Math.floor(this.position), Math.max(0, source.length - 1));
    const carryStart = Math.max(consumed, source.length - MAX_CARRY_SAMPLES);
    this.carry = source.slice(carryStart);
    this.position -= carryStart;
    return true;
  }
}

registerProcessor("qfs-pcm16-capture", QfsPcm16CaptureProcessor);
