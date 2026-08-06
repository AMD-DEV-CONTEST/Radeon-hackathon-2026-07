/**
 * Check the CPU transcription of the Whisper kernels against the torch golden vectors.
 *
 * WebGPU is not available in Node, but the parts that actually break are the buffer
 * layouts and the f16 packing/indexing, not the GPU. kernel-sim.js re-implements each
 * kernel's index arithmetic exactly as the WGSL does and walks the same plan.js graph,
 * so a layout mistake fails here rather than producing plausible-looking numbers in a
 * browser where nothing can be stepped through.
 *
 * Three checkpoints are compared, not one. `hidden` alone cannot distinguish a broken
 * mel frontend from a broken attention block; `mel` and `post_conv` localize it.
 *
 * The GPU half of the story is validate.html, which runs both paths side by side.
 *
 * Run:  node frontend/webgpu/whisper/kernel-sim.test.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { attention as attentionSim, buildSimulator } from "./kernel-sim.js";

const WDIR = join(dirname(fileURLToPath(import.meta.url)), "weights");
const manifest = JSON.parse(readFileSync(join(WDIR, "whisper-f16.json"), "utf8"));
const raw = readFileSync(join(WDIR, "whisper-f16.bin"));
const blob = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
const golden = JSON.parse(readFileSync(join(WDIR, "golden.json"), "utf8"));

/**
 * Budgets, not correctness thresholds.
 *
 * There is no quantization term in any of these. The weights are float16 and the
 * checkpoint is float16, so the only differences left are f32 accumulation order and
 * golden.json's own 5-decimal rounding — about 5e-6 per stored value, amplified by
 * four residual blocks. That is why `hidden` is 5e-3 rather than the 0.25 an int8
 * build needed: with quantization gone, anything above the rounding floor is a bug.
 *
 * `argmax` is the check that a numerical budget cannot express: drift small enough to
 * pass an MSE test but large enough to reorder channels shows up here and nowhere else.
 */
const TOL = {
  mel: 1e-3, // measured 8.7e-5
  postConv: 1e-3, // measured 2.8e-5
  hidden: 5e-3, // measured 3.5e-4
};

const sim = buildSimulator(manifest, blob, golden.n_ctx);

function compare(actual, expected, label) {
  if (actual.length !== expected.length) {
    throw new Error(`${label}: ${actual.length} values, golden has ${expected.length}`);
  }
  let maxAbs = 0;
  let sumSq = 0;
  for (let i = 0; i < expected.length; i++) {
    const d = actual[i] - expected[i];
    maxAbs = Math.max(maxAbs, Math.abs(d));
    sumSq += d * d;
  }
  return { maxAbs, rmse: Math.sqrt(sumSq / expected.length) };
}

const rows = [];
let flips = 0;
const worst = { mel: 0, postConv: 0, hidden: 0 };

for (let c = 0; c < golden.clips.length; c++) {
  const clip = golden.clips[c];
  const out = sim.encode(Float32Array.from(clip.audio));

  const mel = compare(out.mel, clip.mel, `clip ${c} mel`);
  const postConv = compare(out.postConv, clip.post_conv, `clip ${c} post_conv`);
  const hidden = compare(out.hidden, clip.hidden, `clip ${c} hidden`);

  worst.mel = Math.max(worst.mel, mel.maxAbs);
  worst.postConv = Math.max(worst.postConv, postConv.maxAbs);
  worst.hidden = Math.max(worst.hidden, hidden.maxAbs);

  // Which channel dominates each position, recomputed from this run's hidden states.
  const { N_CTX, D } = sim.shapes;
  for (let p = 0; p < N_CTX; p++) {
    let best = 0;
    for (let d = 1; d < D; d++) {
      if (out.hidden[p * D + d] > out.hidden[p * D + best]) best = d;
    }
    if (best !== clip.argmax[p]) flips++;
  }

  rows.push({
    clip: c,
    "mel |d|": mel.maxAbs.toExponential(2),
    "post_conv |d|": postConv.maxAbs.toExponential(2),
    "hidden |d|": hidden.maxAbs.toExponential(2),
    "hidden rmse": hidden.rmse.toExponential(2),
  });
}

console.table(rows);

/* --------------------------------- the online softmax, across tile boundaries */

// golden.json is 64 positions and the attention tile is 256, so every comparison
// above ran in a single tile — the carry between tiles, which is the only part of
// the online softmax that can be wrong, was never executed. Run the same attention
// against the same inputs at several tile sizes: the result must not depend on how
// the keys were chunked, because the rescaling is algebraically a no-op.
//
// This is the check that would have caught rescaling the numerator but not the
// denominator, or exponentiating a tile against its own maximum instead of the
// running one. Both produce smooth, plausible, wrong attention.
{
  const { N_CTX, D, HEADS, HEAD_DIM } = sim.shapes;
  const K0 = N_CTX * D;
  const V0 = 2 * N_CTX * D;

  // Deterministic, and deliberately spread wide: a narrow range would keep every
  // tile's maximum nearly equal and the rescale factor nearly 1, which is the case
  // a broken implementation also passes.
  const qkv = new Float32Array(3 * N_CTX * D);
  let seed = 987654321;
  for (let i = 0; i < qkv.length; i++) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    qkv[i] = (seed / 0x3fffffff - 1) * 6;
  }

  const scope = (TILE) => ({ D, N_CTX, HEAD_DIM, TILE, K0, V0 });
  const run = (TILE) => {
    const attn = new Float32Array(N_CTX * D);
    attentionSim({ qkv, attn }, scope(TILE), HEADS);
    return attn;
  };

  const whole = run(N_CTX); // one tile: the plain, untiled softmax
  let worstTiling = 0;
  for (const TILE of [1, 7, 16, 63, 64, 65, N_CTX - 1]) {
    const tiled = run(TILE);
    let d = 0;
    for (let i = 0; i < whole.length; i++) d = Math.max(d, Math.abs(whole[i] - tiled[i]));
    worstTiling = Math.max(worstTiling, d);
  }

  // f64 accumulation in a different order; the algebra itself is exact.
  const TILING_TOL = 1e-12;
  console.log(
    `\ntile independence: max |d| ${worstTiling.toExponential(2)} over tiles ` +
      `1..${N_CTX} (tolerance ${TILING_TOL})`
  );
  if (worstTiling > TILING_TOL) {
    console.error("\nFAIL — attention output depends on the tile size");
    process.exit(1);
  }
}

const { N_CTX, D, LAYERS } = sim.shapes;
console.log(`\nclips:           ${golden.clips.length} x ${N_CTX} positions x ${D} channels`);
console.log(`dispatches:      ${sim.stages.length} over ${LAYERS} blocks`);
console.log(`max |dmel|:      ${worst.mel.toExponential(3)}  (tolerance ${TOL.mel})`);
console.log(`max |dpost_conv|:${worst.postConv.toExponential(3)}  (tolerance ${TOL.postConv})`);
console.log(`max |dhidden|:   ${worst.hidden.toExponential(3)}  (tolerance ${TOL.hidden})`);
console.log(`argmax flips:    ${flips}`);

const failed =
  worst.mel > TOL.mel ||
  worst.postConv > TOL.postConv ||
  worst.hidden > TOL.hidden ||
  flips > 0;

if (failed) {
  console.error("\nFAIL — kernel simulation does not match the torch reference");
  process.exit(1);
}
console.log("\nPASS — kernel layouts and arithmetic match torch to f32 rounding");
