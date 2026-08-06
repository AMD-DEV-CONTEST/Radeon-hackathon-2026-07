/**
 * AudioWorklet processor: Audio Playback
 * 
 * Receives Float32 audio chunks from main thread, queues them in a ring buffer,
 * and plays them back with linear interpolation and fade-in/out.
 * Supports barge-in (clear) for cancelling playback when user starts speaking.
 * 
 * Adapted from hf-realtime-voice reference implementation.
 */

const FADE_FRAMES = 32;  // 32 samples = ~0.7ms at 48kHz

class AudioPlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    
    this._inputRate = 24000;          // default input rate
    this._outputRate = sampleRate;    // AudioContext sampleRate
    this._stepRatio = this._inputRate / this._outputRate;
    
    this._queue = [];         // FIFO of Float32Array chunks
    this._readIdx = 0;       // index within queue[0]
    this._fracPos = 0;       // fractional read position for interpolation
    this._lastSample = 0;    // last sample for underrun ramp
    this._fadeInFrame = 0;   // fade-in counter
    this._fadeOutFrame = 0;  // fade-out counter
    this._fadeOutTarget = 0; // target sample for fade-out ramp
    
    // Stats
    this._playedFrames = 0;
    this._statsInterval = Math.round(sampleRate * 0.25);  // every 250ms
    this._underrunReported = false;
    
    this.port.onmessage = (e) => {
      const msg = e.data;
      if (msg.kind === 'config') {
        this._inputRate = msg.inputRate || 24000;
        this._stepRatio = this._inputRate / this._outputRate;
      } else if (msg.kind === 'audio') {
        // Receive Float32Array (transferable), push to queue
        const samples = new Float32Array(msg.samples.length);
        samples.set(msg.samples);
        this._queue.push(samples);
        // Resume normal playback after a barge-in 'clear': without resetting the
        // fade-out state here, a clear left _fadeOutFrame > 0 forever and any new
        // audio that arrived was muted to silence.
        this._fadeInFrame = 0;
        this._fadeOutFrame = 0;
        this._underrunReported = false;
      } else if (msg.kind === 'clear') {
        // Barge-in: wipe buffer and start fading current output
        this._queue.length = 0;
        this._readIdx = 0;
        this._fracPos = 0;
        this._fadeOutTarget = this._lastSample;
        this._fadeOutFrame = 0;
      }
    };
  }

  process(_, outputs) {
    const output = outputs[0];
    if (!output?.length) return true;
    
    const channels = output.length;
    const frameCount = output[0].length;
    const hasQueue = this._queue.length > 0;
    
    for (let i = 0; i < frameCount; i++) {
      let sample = 0;
      
      if (hasQueue && this._fadeOutFrame === 0) {
        // Read interpolated sample from queue
        sample = this._readInterpolated();
        
        if (sample === null) {
          // End of queue - start fade-out
          this._fadeOutTarget = this._lastSample;
          this._fadeOutFrame = 0;
        }
      }
      
      if (this._fadeOutFrame > 0 || (sample === null && !hasQueue)) {
        // Fade-out: ramp last sample toward 0 or target
        const target = this._fadeOutFrame > 0 ? 0 : 0;
        const progress = Math.min(1, this._fadeOutFrame / FADE_FRAMES);
        sample = this._lastSample * (1 - progress) + target * progress;
        this._fadeOutFrame++;
        
        if (this._fadeOutFrame >= FADE_FRAMES && !this._underrunReported) {
          this.port.postMessage({ kind: 'underrun' });
          this._underrunReported = true;
        }
      }
      
      // Apply fade-in on new audio
      if (this._fadeInFrame < FADE_FRAMES && hasQueue && this._fadeOutFrame === 0) {
        const gain = Math.min(1, this._fadeInFrame / FADE_FRAMES);
        sample *= gain;
        this._fadeInFrame++;
      }
      
      this._lastSample = sample;
      
      // Write to all channels
      for (let ch = 0; ch < channels; ch++) {
        output[ch][i] = sample;
      }
    }
    
    // Stats reporting
    this._playedFrames += frameCount;
    if (this._playedFrames >= this._statsInterval) {
      const queuedMs = this._queuedSamples() / this._inputRate * 1000;
      this.port.postMessage({ kind: 'stats', queuedMs, played: this._playedFrames });
      this._playedFrames = 0;
    }
    
    return true;
  }

  _readInterpolated() {
    if (this._queue.length === 0) return null;
    
    const chunk = this._queue[0];
    const idx0 = this._readIdx;
    const idx1 = Math.min(idx0 + 1, chunk.length - 1);
    
    // Linear interpolation between two adjacent samples
    const frac = this._fracPos - Math.floor(this._fracPos);
    const sample = chunk[idx0] * (1 - frac) + chunk[idx1] * frac;
    
    // Advance fractional read position
    this._fracPos += this._stepRatio;
    while (this._fracPos >= 1) {
      this._fracPos -= 1;
      this._readIdx++;
      
      // Pop consumed chunks
      if (this._readIdx >= chunk.length) {
        this._queue.shift();
        this._readIdx = 0;
        
        // If queue is now empty, signal end
        if (this._queue.length === 0) {
          this._fracPos = 0;
          return sample;  // return last valid sample
        }
      }
    }
    
    return sample;
  }

  _queuedSamples() {
    let total = 0;
    for (const chunk of this._queue) {
      total += chunk.length;
    }
    return Math.max(0, total - this._readIdx);
  }
}

registerProcessor('audio-playback', AudioPlaybackProcessor);
