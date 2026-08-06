/**
 * Turns a stream of per-frame speech probabilities into complete utterances.
 *
 * The VAD answers "is this 32 ms frame speech?"; turn-taking needs "has the user
 * finished talking?". That gap is what this fills, and it is deliberately free of
 * any GPU or DOM dependency so it can be unit-tested on plain arrays.
 *
 * Three details matter more than the thresholds themselves:
 *
 *   - Pre-roll. By the time enough frames have crossed the threshold to trust that
 *     speech started, those frames are already in the past. Without a ring buffer of
 *     the preceding audio the utterance starts mid-syllable and STT drops the first
 *     word.
 *   - Hysteresis. A single threshold makes the gate chatter on the boundary, cutting
 *     an utterance in half on a brief unvoiced consonant. Entering speech needs a
 *     higher probability than staying in it.
 *   - Hangover. Natural pauses inside a sentence run 200-500 ms, so the silence that
 *     ends a turn has to be clearly longer than that or the user gets interrupted.
 *
 * Usage:
 *     const gate = new UtteranceGate();
 *     const utt = gate.push(prob, int16Chunk);   // null until the turn ends
 *     if (utt) send(utt.pcm);
 */

export const GATE_DEFAULTS = {
  sampleRate: 16000,
  hop: 512, // samples per frame — 32 ms at 16 kHz
  /** Probability needed to declare a frame speech while idle. */
  threshold: 0.5,
  /** Lower bar to *stay* in speech — hysteresis, prevents mid-word cutoffs. */
  exitThreshold: 0.35,
  /** Sustained speech required to open an utterance. Rejects clicks and taps. */
  triggerMs: 160,
  /** Trailing silence that closes an utterance. Longer than an intra-sentence pause. */
  hangoverMs: 700,
  /** Audio retained before the trigger so the first phoneme survives. */
  prerollMs: 320,
  /** Minimum *voiced* time in an utterance. Measured on speech frames only, since
   *  every utterance also carries pre-roll and hangover silence. */
  minVoicedMs: 300,
  /** Hard cap so a stuck-open gate cannot buffer forever. */
  maxUtteranceMs: 20000,
};

function concatInt16(chunks, totalSamples) {
  const out = new Int16Array(totalSamples);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}

export class UtteranceGate {
  #opt;
  #frameMs;
  #prerollFrames;
  #speaking = false;
  #speechMs = 0;
  #silenceMs = 0;
  #voicedMs = 0;
  #buffer = [];
  #bufferedSamples = 0;
  #preroll = [];
  #prerollSamples = 0;

  constructor(options = {}) {
    const opt = { ...GATE_DEFAULTS, ...options };
    if (opt.exitThreshold > opt.threshold) {
      throw new Error("exitThreshold must not exceed threshold");
    }
    this.#opt = opt;
    this.#frameMs = (opt.hop / opt.sampleRate) * 1000;
    // Retain the pre-speech pad *and* the frames that caused the trigger; the latter
    // are already speech, so dropping them would clip just as badly.
    this.#prerollFrames = Math.ceil((opt.prerollMs + opt.triggerMs) / this.#frameMs);
  }

  get options() {
    return { ...this.#opt };
  }

  get frameMs() {
    return this.#frameMs;
  }

  /** True while an utterance is open — useful for UI state. */
  get speaking() {
    return this.#speaking;
  }

  /** Milliseconds buffered in the open utterance (0 when idle). */
  get bufferedMs() {
    return (this.#bufferedSamples / this.#opt.sampleRate) * 1000;
  }

  reset() {
    this.#speaking = false;
    this.#speechMs = 0;
    this.#silenceMs = 0;
    this.#voicedMs = 0;
    this.#buffer = [];
    this.#bufferedSamples = 0;
    this.#preroll = [];
    this.#prerollSamples = 0;
  }

  /**
   * Feed one frame.
   *
   * @param {number} prob speech probability for this frame
   * @param {Int16Array} chunk the PCM the probability was computed from
   * @returns {{pcm: Int16Array, durationMs: number, voicedMs: number, reason: string}|null}
   *          the finished utterance, or null if the turn is still in progress
   */
  push(prob, chunk) {
    if (this.#speaking) return this.#pushSpeaking(prob, chunk);
    return this.#pushIdle(prob, chunk);
  }

  #pushIdle(prob, chunk) {
    this.#preroll.push(chunk);
    this.#prerollSamples += chunk.length;
    while (this.#preroll.length > this.#prerollFrames) {
      this.#prerollSamples -= this.#preroll.shift().length;
    }

    if (prob >= this.#opt.threshold) {
      this.#speechMs += this.#frameMs;
    } else {
      this.#speechMs = 0;
    }

    if (this.#speechMs >= this.#opt.triggerMs) {
      this.#speaking = true;
      this.#buffer = this.#preroll;
      this.#bufferedSamples = this.#prerollSamples;
      this.#preroll = [];
      this.#prerollSamples = 0;
      this.#voicedMs = this.#speechMs; // the frames that triggered are speech too
      this.#speechMs = 0;
      this.#silenceMs = 0;
    }
    return null;
  }

  #pushSpeaking(prob, chunk) {
    this.#buffer.push(chunk);
    this.#bufferedSamples += chunk.length;

    if (prob >= this.#opt.exitThreshold) {
      this.#silenceMs = 0;
      this.#voicedMs += this.#frameMs;
    } else {
      this.#silenceMs += this.#frameMs;
      if (this.#silenceMs >= this.#opt.hangoverMs) return this.#close("silence");
    }

    if (this.bufferedMs >= this.#opt.maxUtteranceMs) return this.#close("max-length");
    return null;
  }

  /** Close an open utterance early — mic stopped, socket dropped, tab hidden. */
  flush() {
    if (!this.#speaking) {
      this.reset();
      return null;
    }
    return this.#close("flush");
  }

  #close(reason) {
    const samples = this.#bufferedSamples;
    const chunks = this.#buffer;
    const voicedMs = this.#voicedMs;
    const durationMs = (samples / this.#opt.sampleRate) * 1000;
    this.reset();

    if (voicedMs < this.#opt.minVoicedMs) return null;
    return { pcm: concatInt16(chunks, samples), durationMs, voicedMs, reason };
  }
}

export default UtteranceGate;
