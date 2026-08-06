/**
 * Check the CPU transcription of the VAD kernels against ONNX Runtime golden vectors.
 *
 * WebGPU is not available in Node, but the parts that actually break are the buffer
 * layouts and the int8 packing/indexing — not the GPU itself. kernel-sim.js re-implements
 * each kernel's index arithmetic exactly as the WGSL does, so a layout mistake fails here
 * rather than silently producing plausible-looking numbers in the browser.
 *
 * The GPU half of the story is validate.html, which runs both paths side by side.
 *
 * Run:  node frontend/webgpu/vad/kernel-sim.test.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { buildSimulator } from "./kernel-sim.js";

const WDIR = join(dirname(fileURLToPath(import.meta.url)), "weights");

const manifest = JSON.parse(readFileSync(join(WDIR, "vad-int8.json"), "utf8"));
const raw = readFileSync(join(WDIR, "vad-int8.bin"));
const blob = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
const golden = JSON.parse(readFileSync(join(WDIR, "golden.json"), "utf8"));

const sim = buildSimulator(manifest, blob);

let state = new Float32Array(2 * manifest.hidden);
let worstProb = 0;
let worstH = 0;
let worstC = 0;
let flips = 0;
const rows = [];

for (let i = 0; i < golden.frames.length; i++) {
  const { prob, stateOut } = sim.forward(Float32Array.from(golden.frames[i]), state);
  state = stateOut;

  const ref = golden.probs[i];
  const d = Math.abs(prob - ref);
  worstProb = Math.max(worstProb, d);
  if (prob > 0.5 !== ref > 0.5) flips++;

  const refState = golden.states[i];
  for (let j = 0; j < manifest.hidden; j++) {
    worstH = Math.max(worstH, Math.abs(stateOut[j] - refState[j]));
    worstC = Math.max(worstC, Math.abs(stateOut[manifest.hidden + j] - refState[manifest.hidden + j]));
  }

  rows.push({ frame: i, onnx: ref.toFixed(6), kernels: prob.toFixed(6), diff: d.toExponential(2) });
}

console.table(rows);

// Budgets are quantization budgets, not correctness budgets: a layout bug misses
// these by orders of magnitude, so there is no need to make them tight.
const TOL_PROB = 0.05; // measured 0.033 on real speech during export
const TOL_H = 0.3; // h is bounded to [-1, 1]
const TOL_C = 1.0; // c is unbounded; |c| reaches ~10 in these frames

console.log(`\nframes:         ${golden.frames.length}`);
console.log(`max |dprob|:    ${worstProb.toExponential(3)}  (tolerance ${TOL_PROB})`);
console.log(`max |dh|:       ${worstH.toExponential(3)}  (tolerance ${TOL_H})`);
console.log(`max |dc|:       ${worstC.toExponential(3)}  (tolerance ${TOL_C})`);
console.log(`decision flips: ${flips}`);

if (worstProb > TOL_PROB || worstH > TOL_H || worstC > TOL_C || flips > 0) {
  console.error("\nFAIL — kernel simulation does not match ONNX Runtime");
  process.exit(1);
}
console.log("\nPASS — kernel layouts and arithmetic match ONNX Runtime within int8 budget");
