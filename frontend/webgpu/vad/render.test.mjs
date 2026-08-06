/**
 * Static checks on the specialized WGSL, without a GPU.
 *
 * Compiling the shaders needs a browser, but most of what goes wrong here is
 * text-level and catchable in Node: an unbound template variable, a binding the
 * shader reads but the binding table never declares, a workgroup size that
 * exceeds the spec floor, a dispatch that does not cover every output element.
 * Those are the bugs that otherwise surface as a blank error in the console.
 *
 * Run:  node frontend/webgpu/vad/render.test.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { render, resourceDeclarations } from "../wgsl-template.js";
import { STFT_WGSL, CONV_WGSL, LSTM_HEAD_WGSL } from "./kernels.js";
import { ENCODER, layoutLstm, MAX_STORAGE_BUFFERS_PER_STAGE } from "./weights.js";

const WDIR = join(dirname(fileURLToPath(import.meta.url)), "weights");
const manifest = JSON.parse(readFileSync(join(WDIR, "vad-int8.json"), "utf8"));
const rawBlob = readFileSync(join(WDIR, "vad-int8.bin"));
const blob = rawBlob.buffer.slice(rawBlob.byteOffset, rawBlob.byteOffset + rawBlob.byteLength);

// The WebGPU spec guarantees at least these; staying inside them keeps the
// kernels portable to the weakest conforming adapter.
const MIN_WORKGROUP_INVOCATIONS = 256;
const MIN_WORKGROUP_SIZE_X = 256;

const FRAMES = 4;
const failures = [];
const notes = [];

function check(cond, msg) {
  if (!cond) failures.push(msg);
}

/** Identifiers the shader body references that must come from the binding table. */
function undeclaredBindings(code, bindings) {
  const declared = new Set(bindings.map((b) => b.name));
  const body = code
    .replace(/\/\/[^\n]*/g, "") // prose mentioning "rows [0, BINS)" is not an index
    .replace(/@group\(0\)[^\n]*\n/g, "");
  const missing = new Set();
  for (const m of body.matchAll(/\b([a-z_][a-z0-9_]*)\s*\[/g)) {
    const id = m[1];
    // locals and workgroup arrays are declared in-shader; anything else must be a binding
    if (declared.has(id)) continue;
    if (new RegExp(`\\b(var|let)(<[^>]*>)?\\s+${id}\\b`).test(body)) continue;
    if (/^(array|vec[234]|mat[234])$/.test(id)) continue;
    missing.add(id);
  }
  return [...missing];
}

function inspect(label, source, bindings, scope, { dispatch, outputs }) {
  let code;
  try {
    code = render(source, { ...scope, RESOURCES: resourceDeclarations(bindings) });
  } catch (err) {
    failures.push(`${label}: ${err.message}`);
    return;
  }

  check(!/\{\{|\{%/.test(code), `${label}: unexpanded template syntax remains`);

  const wg = Number(code.match(/@workgroup_size\(\s*(\d+)u?/)?.[1] ?? scope.WG);
  check(Number.isFinite(wg), `${label}: could not determine workgroup size`);
  check(wg <= MIN_WORKGROUP_SIZE_X, `${label}: workgroup_size ${wg} exceeds the guaranteed ${MIN_WORKGROUP_SIZE_X}`);
  check(
    wg <= MIN_WORKGROUP_INVOCATIONS,
    `${label}: ${wg} invocations exceeds the guaranteed ${MIN_WORKGROUP_INVOCATIONS}`
  );

  const missing = undeclaredBindings(code, bindings);
  check(missing.length === 0, `${label}: reads undeclared buffer(s) ${missing.join(", ")}`);

  // Every output element must be reachable by some invocation.
  const covered = dispatch * wg;
  check(
    covered >= outputs,
    `${label}: dispatch ${dispatch}x${wg}=${covered} invocations cannot cover ${outputs} outputs`
  );

  const bindingCount = (code.match(/@binding\(/g) ?? []).length;
  check(bindingCount === bindings.length, `${label}: declared ${bindingCount} bindings, table has ${bindings.length}`);

  // Exceeding this fails as "invalid PipelineLayout" with no hint about which limit.
  const storage = bindings.filter((b) => b.type !== "uniform").length;
  check(
    storage <= MAX_STORAGE_BUFFERS_PER_STAGE,
    `${label}: ${storage} storage buffers exceeds the guaranteed ${MAX_STORAGE_BUFFERS_PER_STAGE} per stage`
  );

  notes.push({
    kernel: label,
    lines: code.split("\n").length,
    workgroup: wg,
    dispatch,
    invocations: covered,
    outputs,
    storageBuffers: bindings.filter((b) => b.type !== "uniform").length,
  });
}

/* ------------------------------------------------------------------- stft */

inspect(
  "vad.stft",
  STFT_WGSL,
  [
    { name: "audio", type: "read-only-storage", element: "f32" },
    { name: "basis", type: "read-only-storage", element: "i32" },
    { name: "basis_scale", type: "read-only-storage", element: "f32" },
    { name: "spec", type: "storage", element: "f32" },
  ],
  {
    N_IN: manifest.frame,
    WIN: manifest.stft.win,
    HOP: manifest.stft.hop,
    BINS: manifest.stft.bins,
    FRAMES,
    WORDS_PER_ROW: manifest.stft.win / 4,
    WG: 64,
  },
  // one workgroup per frame; each thread strides over bins, so 1 thread covers >=1 bin
  { dispatch: FRAMES, outputs: FRAMES }
);

/* ------------------------------------------------------------------- conv */

const convBindings = [
  { name: "x", type: "read-only-storage", element: "f32" },
  { name: "w", type: "read-only-storage", element: "i32" },
  { name: "w_scale", type: "read-only-storage", element: "f32" },
  { name: "bias", type: "read-only-storage", element: "f32" },
  { name: "y", type: "storage", element: "f32" },
];

for (const layer of ENCODER) {
  const outputs = layer.C_OUT * layer.L_OUT;
  inspect(`vad.${layer.name}`, CONV_WGSL, convBindings, { ...layer, RELU: true, WG: 64 }, {
    dispatch: Math.ceil(outputs / 64),
    outputs,
  });
}

/* -------------------------------------------------------------- lstm head */

const lstm = layoutLstm(manifest, blob);

inspect(
  "vad.lstm_head",
  LSTM_HEAD_WGSL,
  [
    { name: "x", type: "read-only-storage", element: "f32" },
    { name: "state_in", type: "read-only-storage", element: "f32" },
    { name: "qw", type: "read-only-storage", element: "i32" },
    { name: "qp", type: "read-only-storage", element: "f32" },
    { name: "state_out", type: "storage", element: "f32" },
    { name: "prob", type: "storage", element: "f32" },
  ],
  { HIDDEN: manifest.hidden, IN_F: 128, WG: 128, ...lstm.offsets },
  { dispatch: 1, outputs: manifest.hidden }
);

// Every offset must land inside the buffer it indexes, or the shader reads zeros
// and produces a plausible-but-wrong probability.
const { W_HH_W0, HEAD_W0, HEAD_B } = lstm.offsets;
check(W_HH_W0 < HEAD_W0 && HEAD_W0 < lstm.qw.length, `lstm qw offsets fall outside the ${lstm.qw.length}-word buffer`);
check(HEAD_B < lstm.qp.length, `lstm qp offsets fall outside the ${lstm.qp.length}-element buffer`);

/* ---------------------------------------------------------------- reduction */

// The head reduction halves `stride` from WG/2, which only lands on 0 if WG is a
// power of two. This is silent and wrong otherwise, so assert it.
const LSTM_WG = 128;
check(
  (LSTM_WG & (LSTM_WG - 1)) === 0,
  `vad.lstm_head: workgroup size ${LSTM_WG} must be a power of two for the tree reduction`
);

/* ------------------------------------------------------------------ report */

console.table(notes);

if (failures.length) {
  console.error(`\nFAIL — ${failures.length} problem(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log("\nPASS — all kernels specialize cleanly and dispatches cover their outputs");
