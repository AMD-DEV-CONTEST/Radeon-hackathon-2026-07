/* AudioWorklet processor: accumulates mic samples on the audio thread and
 * posts 4096-sample Float32 blocks to the main thread for WS streaming.
 * More reliable than the deprecated ScriptProcessorNode, which some browsers
 * silently never fire. */
class PcmSender extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(4096);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || !ch.length) return true;
    let i = 0;
    while (i < ch.length) {
      const take = Math.min(ch.length - i, 4096 - this.n);
      this.buf.set(ch.subarray(i, i + take), this.n);
      this.n += take;
      i += take;
      if (this.n === 4096) {
        this.port.postMessage(this.buf.slice());
        this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor("pcm-sender", PcmSender);
