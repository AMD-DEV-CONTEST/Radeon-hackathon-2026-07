/**
 * AudioWorklet processor: Mic Capture
 * 
 * Captures microphone input at 48kHz, resamples to 16kHz mono,
 * applies optional noise gate, and posts Int16 PCM chunks to main thread.
 * 
 * Adapted from hf-realtime-voice reference implementation.
 */

const TARGET_RATE = 16000;
const DEFAULT_CHUNK_MS = 40;

class MicCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    
    const chunkMs = (options?.processorOptions?.chunkMs) || DEFAULT_CHUNK_MS;
    this._chunkSamples16k = Math.round(TARGET_RATE * chunkMs / 1000);  // 640 for 40ms
    this._inputRate = sampleRate;  // AudioContext sampleRate (typically 48000)
    this._ratio = this._inputRate / TARGET_RATE;
    
    // Scratch buffer: accumulates raw Float32 input
    this._scratch = new Float32Array(0);
    // Decimated buffer: resampled to 16kHz
    this._decimated = new Float32Array(this._chunkSamples16k * 2);
    
    // Noise gate state
    this._gateEnabled = false;
    this._gateThreshold = 0.001;  // linear (~ -60dBFS)
    this._gateGain = 0;
    this._holdFrames = 0;
    this._holdMax = Math.round(TARGET_RATE * 0.25);  // 250ms hold
    this._attackCoef = Math.exp(-1 / (TARGET_RATE * 0.005));   // 5ms attack
    this._releaseCoef = Math.exp(-1 / (TARGET_RATE * 0.08));   // 80ms release
    
    // Enable flag: when false, silently discard input
    this._enabled = true;
    
    this.port.onmessage = (e) => {
      const msg = e.data;
      if (msg.kind === 'enable') {
        this._enabled = !!msg.value;
      } else if (msg.kind === 'gate') {
        this._gateEnabled = !!msg.enabled;
        if (msg.thresholdDb !== undefined) {
          this._gateThreshold = Math.pow(10, (msg.thresholdDb || -60) / 20);
        }
      }
    };
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input.length) return true;
    
    const channel = input[0];
    if (!channel) return true;
    
    this._ingest(channel);
    return true;
  }

  _ingest(incoming) {
    // Append incoming samples to scratch buffer
    const combined = new Float32Array(this._scratch.length + incoming.length);
    combined.set(this._scratch);
    combined.set(incoming, this._scratch.length);
    this._scratch = combined;
    
    this._maybeEmit();
  }

  _maybeEmit() {
    // Need enough input samples to produce one chunk at 16kHz
    const needed = Math.ceil(this._chunkSamples16k * this._ratio);
    
    while (this._scratch.length >= needed) {
      // Decimate: simple boxcar average for integer ratios, linear interp otherwise
      this._decimate(this._scratch.subarray(0, needed), this._decimated, this._ratio);
      
      // Compute RMS from the full chunk
      let sumSq = 0;
      for (let i = 0; i < this._chunkSamples16k; i++) {
        const s = this._decimated[i];
        sumSq += s * s;
      }
      const rms = Math.sqrt(sumSq / this._chunkSamples16k);
      
      // Post RMS level (for UI meter)
      this.port.postMessage({ kind: 'level', rms });
      
      // Noise gate decision
      const wantOpen = !this._gateEnabled || rms > this._gateThreshold;
      if (wantOpen) {
        this._holdFrames = this._holdMax;
      } else if (this._holdFrames > 0) {
        this._holdFrames--;
      }
      const targetGain = (wantOpen || this._holdFrames > 0) ? 1 : 0;
      
      // Prepare Int16 output buffer
      const int16 = new Int16Array(this._chunkSamples16k);
      if (this._enabled) {
        for (let i = 0; i < this._chunkSamples16k; i++) {
          // Smooth gate gain
          const coef = (this._gateGain < targetGain) ? this._attackCoef : this._releaseCoef;
          this._gateGain = targetGain + coef * (this._gateGain - targetGain);
          
          let sample = this._decimated[i] * this._gateGain;
          sample = Math.max(-1, Math.min(1, sample));
          int16[i] = Math.round(sample * 32767);
        }
      }
      
      // Post Int16 buffer as transferable
      this.port.postMessage(int16.buffer, [int16.buffer]);
      
      // Shift scratch buffer
      this._scratch = this._scratch.subarray(needed);
    }
  }

  _decimate(input, output, ratio) {
    const outLen = this._chunkSamples16k;
    
    // Fast path: integer ratio (48k -> 16k = 3:1)
    if (Math.abs(ratio - 3) < 0.001) {
      for (let i = 0; i < outLen; i++) {
        const base = i * 3;
        output[i] = (input[base] + input[base + 1] + input[base + 2]) / 3;
      }
    } else {
      // General path: linear interpolation
      const step = ratio;
      for (let i = 0; i < outLen; i++) {
        const srcIdx = i * step;
        const idx0 = Math.floor(srcIdx);
        const idx1 = Math.min(idx0 + 1, input.length - 1);
        const frac = srcIdx - idx0;
        output[i] = input[idx0] * (1 - frac) + input[idx1] * frac;
      }
    }
  }
}

registerProcessor('mic-capture', MicCaptureProcessor);
