/**
 * Unit tests for the utterance gate.
 *
 * The gate is the piece that decides when the user stopped talking, and getting it
 * wrong is invisible in a probability plot but very obvious to a user whose sentence
 * got cut in half. Driving it with synthetic probability sequences is the only way to
 * cover the edges — a real microphone will not reliably produce a 400 ms mid-sentence
 * pause on demand.
 *
 * Run: node --test frontend/webgpu/vad/
 */

import test from "node:test";
import assert from "node:assert/strict";

import { UtteranceGate, GATE_DEFAULTS } from "./utterance-gate.js";

const HOP = GATE_DEFAULTS.hop;
const FRAME_MS = (HOP / GATE_DEFAULTS.sampleRate) * 1000; // 32

/** A frame whose samples all equal `id`, so we can trace which frames were kept. */
function frame(id) {
  return new Int16Array(HOP).fill(id);
}

/** Feed `n` frames at probability `prob`; return the first utterance emitted, if any. */
function feed(gate, n, prob, { from = 0 } = {}) {
  let out = null;
  for (let i = 0; i < n; i++) {
    const utt = gate.push(prob, frame(from + i));
    if (utt && !out) out = utt;
  }
  return out;
}

const frames = (ms) => Math.ceil(ms / FRAME_MS);

test("frame geometry matches the 16 kHz Silero hop", () => {
  const gate = new UtteranceGate();
  assert.equal(gate.frameMs, 32);
  assert.equal(gate.speaking, false);
  assert.equal(gate.bufferedMs, 0);
});

test("rejects an exit threshold above the entry threshold", () => {
  // Inverted hysteresis would make the gate stickier to enter than to hold, which
  // is the opposite of what it is for — fail loudly rather than behave oddly.
  assert.throws(() => new UtteranceGate({ threshold: 0.4, exitThreshold: 0.9 }), /exitThreshold/);
});

test("silence alone never opens an utterance", () => {
  const gate = new UtteranceGate();
  assert.equal(feed(gate, 200, 0.01), null);
  assert.equal(gate.speaking, false);
});

test("a short blip does not trigger", () => {
  const gate = new UtteranceGate();
  // One frame over threshold — a door slam, a key press.
  gate.push(0.95, frame(1));
  assert.equal(gate.speaking, false);
  feed(gate, 40, 0.0);
  assert.equal(gate.speaking, false);
});

test("sustained speech opens the gate after triggerMs", () => {
  const gate = new UtteranceGate();
  const need = frames(GATE_DEFAULTS.triggerMs);
  for (let i = 0; i < need - 1; i++) {
    gate.push(0.9, frame(i));
    assert.equal(gate.speaking, false, `opened early at frame ${i}`);
  }
  gate.push(0.9, frame(need - 1));
  assert.equal(gate.speaking, true);
});

test("the trigger requires *consecutive* frames", () => {
  const gate = new UtteranceGate();
  // Alternating speech/silence carries plenty of speech frames in total but never
  // enough in a row: this is the signature of impulsive noise, not a voice.
  for (let i = 0; i < 60; i++) gate.push(i % 2 === 0 ? 0.9 : 0.0, frame(i));
  assert.equal(gate.speaking, false);
});

test("pre-roll keeps the audio that preceded the trigger", () => {
  const gate = new UtteranceGate();
  // 100 frames of silence, then speech. The gate must hand back audio from *before*
  // the frames that tripped it, or STT loses the first word.
  feed(gate, 100, 0.0, { from: 0 });
  feed(gate, frames(GATE_DEFAULTS.triggerMs) + frames(600), 0.9, { from: 100 });
  assert.equal(gate.speaking, true);

  const utt = feed(gate, frames(GATE_DEFAULTS.hangoverMs) + 30, 0.0, { from: 900 });
  assert.ok(utt, "utterance should close");

  const prerollFrames = Math.ceil(
    (GATE_DEFAULTS.prerollMs + GATE_DEFAULTS.triggerMs) / FRAME_MS
  );
  const firstId = utt.pcm[0];
  const expectedFirst = 100 - (prerollFrames - frames(GATE_DEFAULTS.triggerMs));
  assert.equal(firstId, expectedFirst, "pre-roll should start before the trigger");
  assert.ok(
    utt.durationMs >= GATE_DEFAULTS.prerollMs + GATE_DEFAULTS.hangoverMs,
    "utterance should span pre-roll + speech + hangover"
  );
});

test("an intra-sentence pause does not split the utterance", () => {
  const gate = new UtteranceGate();
  feed(gate, frames(GATE_DEFAULTS.triggerMs), 0.9);
  assert.equal(gate.speaking, true);

  // 400 ms pause — normal between clauses, and shorter than the hangover.
  assert.equal(feed(gate, frames(400), 0.02), null);
  assert.equal(gate.speaking, true, "gate closed on a normal breath pause");

  assert.equal(feed(gate, frames(500), 0.9), null);
  assert.equal(gate.speaking, true);
});

test("hysteresis holds through frames between the two thresholds", () => {
  const gate = new UtteranceGate();
  feed(gate, frames(GATE_DEFAULTS.triggerMs), 0.9);
  // 0.42 is below the entry threshold but above the exit threshold: typical of an
  // unvoiced consonant. A single-threshold gate would start counting silence here.
  assert.equal(feed(gate, frames(2000), 0.42), null);
  assert.equal(gate.speaking, true);
});

test("hangover silence closes the utterance", () => {
  const gate = new UtteranceGate();
  feed(gate, frames(GATE_DEFAULTS.triggerMs) + frames(600), 0.9);

  const need = frames(GATE_DEFAULTS.hangoverMs);
  for (let i = 0; i < need - 1; i++) {
    assert.equal(gate.push(0.0, frame(i)), null, `closed early at silence frame ${i}`);
  }
  const utt = gate.push(0.0, frame(need));
  assert.ok(utt);
  assert.equal(utt.reason, "silence");
  assert.equal(gate.speaking, false, "gate must reset itself after emitting");
});

test("a cough is discarded even though it trips the trigger", () => {
  const gate = new UtteranceGate();
  // Just enough speech to open, far less than minVoicedMs of actual voice.
  feed(gate, frames(GATE_DEFAULTS.triggerMs), 0.9);
  assert.equal(gate.speaking, true);
  const utt = feed(gate, frames(GATE_DEFAULTS.hangoverMs) + 5, 0.0);
  assert.equal(utt, null, "short voiced content should be dropped, not transcribed");
  assert.equal(gate.speaking, false);
});

test("maxUtteranceMs caps a gate that never sees silence", () => {
  const gate = new UtteranceGate({ maxUtteranceMs: 2000 });
  feed(gate, frames(GATE_DEFAULTS.triggerMs), 0.9);
  const utt = feed(gate, frames(5000), 0.99);
  assert.ok(utt, "unbroken speech must still be flushed");
  assert.equal(utt.reason, "max-length");
  assert.ok(utt.durationMs >= 2000);
  assert.ok(utt.durationMs < 2500, `cap overshot: ${utt.durationMs}ms`);
});

test("emitted audio is contiguous and in order", () => {
  const gate = new UtteranceGate();
  feed(gate, 100, 0.0, { from: 0 });
  feed(gate, frames(GATE_DEFAULTS.triggerMs) + frames(600), 0.9, { from: 100 });
  const utt = feed(gate, frames(GATE_DEFAULTS.hangoverMs) + 2, 0.0, { from: 1000 });
  assert.ok(utt);
  assert.equal(utt.pcm.length % HOP, 0, "output should be a whole number of frames");

  // Every frame was filled with its own id, so the ids must increase by one per hop
  // wherever the source frames were consecutive.
  const ids = [];
  for (let i = 0; i < utt.pcm.length; i += HOP) ids.push(utt.pcm[i]);
  const speechStart = ids.indexOf(100);
  assert.ok(speechStart > 0, "speech frames should follow pre-roll frames");
  for (let i = 1; i < speechStart; i++) {
    assert.equal(ids[i], ids[i - 1] + 1, "pre-roll frames out of order");
  }
});

test("flush closes an open utterance and is a no-op when idle", () => {
  const gate = new UtteranceGate();
  assert.equal(gate.flush(), null);

  feed(gate, frames(GATE_DEFAULTS.triggerMs) + frames(600), 0.9);
  const utt = gate.flush();
  assert.ok(utt);
  assert.equal(utt.reason, "flush");
  assert.equal(gate.speaking, false);
  assert.equal(gate.flush(), null);
});

test("reset drops buffered audio and pre-roll", () => {
  const gate = new UtteranceGate();
  feed(gate, frames(GATE_DEFAULTS.triggerMs) + frames(600), 0.9);
  assert.ok(gate.bufferedMs > 0);
  gate.reset();
  assert.equal(gate.speaking, false);
  assert.equal(gate.bufferedMs, 0);
  // With pre-roll cleared, a fresh trigger carries only post-reset audio.
  feed(gate, frames(GATE_DEFAULTS.triggerMs) + frames(600), 0.9, { from: 7 });
  const utt = feed(gate, frames(GATE_DEFAULTS.hangoverMs) + 2, 0.0, { from: 900 });
  assert.ok(utt);
  assert.equal(utt.pcm[0], 7);
});

test("back-to-back utterances are emitted separately", () => {
  const gate = new UtteranceGate();
  const speak = () => feed(gate, frames(GATE_DEFAULTS.triggerMs) + frames(600), 0.9);
  const pause = () => feed(gate, frames(GATE_DEFAULTS.hangoverMs) + 2, 0.0);

  speak();
  const first = pause();
  assert.ok(first);
  speak();
  const second = pause();
  assert.ok(second, "the gate must keep working after the first turn");
  assert.equal(first.reason, "silence");
  assert.equal(second.reason, "silence");
});
