class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
    this._target = 1600; // ~100ms at 16kHz
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0]; // Float32, already at 16kHz if AudioContext was created at 16000

    const pcm = new Int16Array(channel.length);
    for (let i = 0; i < channel.length; i++) {
      const s = Math.max(-1, Math.min(1, channel[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    this._buffer.push(pcm);

    let total = this._buffer.reduce((n, b) => n + b.length, 0);
    if (total >= this._target) {
      const out = new Int16Array(total);
      let offset = 0;
      for (const b of this._buffer) {
        out.set(b, offset);
        offset += b.length;
      }
      this._buffer = [];
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
