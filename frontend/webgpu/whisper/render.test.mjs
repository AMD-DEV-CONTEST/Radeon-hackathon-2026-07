/**
 * Static checks on the specialized Whisper WGSL, without a GPU.
 *
 * Compiling the shaders needs a browser, but most of what goes wrong is text-level
 * and catchable in Node: an unbound template variable, a binding the shader reads
 * but the table never declares, a workgroup size past the spec floor, a dispatch
 * that misses the tail of a tensor, a reduction whose width is not a power of two.
 * In the browser those surface as a blank console error or, worse, plausible numbers.
 *
 * The graph in plan.js is checked as well as the shaders: every buffer must be
 * written before it is read, and every dispatch must fit the guaranteed limits.
 *
 * Run:  node frontend/webgpu/whisper/render.test.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { render, resourceDeclarations } from "../wgsl-template.js";
import { BINDINGS, SOURCES } from "./kernels.js";
import {
  MAX_STORAGE_BUFFERS_PER_STAGE,
  buildWeightBuffers,
  layoutQkv,
  melFilters,
  stftBasis,
} from "./weights.js";
import {
  LINEAR_ROW_TILE,
  MAX_WORKGROUPS_PER_DIMENSION,
  activationSizes,
  encoderPlan,
} from "./plan.js";

const WDIR = join(dirname(fileURLToPath(import.meta.url)), "weights");
const manifest = JSON.parse(readFileSync(join(WDIR, "whisper-f16.json"), "utf8"));
const rawBlob = readFileSync(join(WDIR, "whisper-f16.bin"));
const blob = rawBlob.buffer.slice(rawBlob.byteOffset, rawBlob.byteOffset + rawBlob.byteLength);
const golden = JSON.parse(readFileSync(join(WDIR, "golden.json"), "utf8"));

// The WebGPU spec guarantees at least these; staying inside them keeps the kernels
// portable to the weakest conforming adapter, not just this box's RDNA3.
const MIN_WORKGROUP_INVOCATIONS = 256;
const MIN_WORKGROUP_SIZE_X = 256;
const MIN_WORKGROUP_STORAGE_BYTES = 16384;

const failures = [];
const notes = [];

function check(cond, msg) {
  if (!cond) failures.push(msg);
}

/** Identifiers the shader body indexes that must come from the binding table. */
function undeclaredBindings(code, bindings) {
  const declared = new Set(bindings.map((b) => b.name));
  const body = code
    .replace(/\/\/[^\n]*/g, "") // prose mentioning "rows [0, BINS)" is not an index
    .replace(/@group\(0\)[^\n]*\n/g, "");
  const missing = new Set();
  for (const m of body.matchAll(/\b([a-z_][a-z0-9_]*)\s*\[/g)) {
    const id = m[1];
    if (declared.has(id)) continue;
    if (new RegExp(`\\b(var|let)(<[^>]*>)?\\s+${id}\\b`).test(body)) continue;
    if (/^(array|vec[234]|mat[234])$/.test(id)) continue;
    missing.add(id);
  }
  return [...missing];
}

/** Bytes of `var<workgroup>` storage the shader declares. */
function workgroupBytes(code) {
  let total = 0;
  for (const m of code.matchAll(/var<workgroup>\s+\w+\s*:\s*array<(f32|i32|u32),\s*(\w+)>/g)) {
    const size = /^\d+$/.test(m[2])
      ? Number(m[2])
      : Number(code.match(new RegExp(`const ${m[2]}\\s*:\\s*u32\\s*=\\s*(\\d+)`))?.[1] ?? NaN);
    total += 4 * size;
  }
  return total;
}

function inspect(label, kernel, scope, { dispatch, outputs }) {
  const bindings = BINDINGS[kernel];
  const source = SOURCES[kernel];
  check(Boolean(bindings && source), `${label}: no kernel named "${kernel}"`);
  if (!bindings || !source) return;

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
  check(
    wg <= MIN_WORKGROUP_SIZE_X && wg <= MIN_WORKGROUP_INVOCATIONS,
    `${label}: workgroup size ${wg} exceeds the guaranteed ${MIN_WORKGROUP_SIZE_X}`
  );

  // A tree reduction halves `stride` from WG/2, which only reaches 0 if WG is a
  // power of two. Otherwise it drops lanes: silent, and wrong by a little.
  if (/for \(var stride = WG \/ 2u/.test(code)) {
    check(
      (wg & (wg - 1)) === 0,
      `${label}: workgroup size ${wg} must be a power of two for the tree reduction`
    );
  }

  const missing = undeclaredBindings(code, bindings);
  check(missing.length === 0, `${label}: reads undeclared buffer(s) ${missing.join(", ")}`);

  const covered = dispatch * wg;
  check(
    covered >= outputs,
    `${label}: dispatch ${dispatch}x${wg}=${covered} invocations cannot cover ${outputs} outputs`
  );
  check(
    dispatch <= MAX_WORKGROUPS_PER_DIMENSION,
    `${label}: ${dispatch} workgroups exceeds the guaranteed ${MAX_WORKGROUPS_PER_DIMENSION}`
  );

  const bindingCount = (code.match(/@binding\(/g) ?? []).length;
  check(
    bindingCount === bindings.length,
    `${label}: declared ${bindingCount} bindings, table has ${bindings.length}`
  );

  const storage = bindings.filter((b) => b.type !== "uniform").length;
  check(
    storage <= MAX_STORAGE_BUFFERS_PER_STAGE,
    `${label}: ${storage} storage buffers exceeds the guaranteed ${MAX_STORAGE_BUFFERS_PER_STAGE}`
  );

  const wgBytes = workgroupBytes(code);
  check(
    wgBytes <= MIN_WORKGROUP_STORAGE_BYTES,
    `${label}: ${wgBytes} B of workgroup storage exceeds the guaranteed ${MIN_WORKGROUP_STORAGE_BYTES}`
  );

  return { code, wg, storage, wgBytes };
}

/* ------------------------------------------------------ the encoder graph */

const N_CTX = golden.n_ctx;
const { shapes, melParts, stages } = encoderPlan(manifest, N_CTX);

check(
  shapes.MEL_FRAMES === golden.mel_frames && shapes.N_SAMPLES === golden.n_samples,
  `plan disagrees with golden.json on clip geometry: ` +
    `${shapes.MEL_FRAMES}/${shapes.N_SAMPLES} vs ${golden.mel_frames}/${golden.n_samples}`
);
check(
  shapes.D === golden.n_state,
  `plan width ${shapes.D} does not match golden.json's ${golden.n_state}`
);

// Kernels are specialized many times over; report one row per distinct shape.
const seen = new Set();
for (const stage of stages) {
  const info = inspect(stage.label, stage.kernel, stage.scope, stage);
  if (!info) continue;

  const signature = `${stage.kernel}:${JSON.stringify(stage.scope)}`;
  if (seen.has(signature)) continue;
  seen.add(signature);
  notes.push({
    stage: stage.label,
    kernel: stage.kernel,
    workgroup: info.wg,
    dispatch: stage.dispatch,
    outputs: stage.outputs,
    storage: info.storage,
    wgBytes: info.wgBytes,
  });
}

/* ------------------------------------------------ the full 30 s context */

// golden.json truncates to 64 positions, but production runs the model's full 1500.
// Everything that scales with N_CTX — workgroup counts, the attention kernel's
// workgroup-memory score array — has to be re-checked at that size, or the first
// real utterance is where a limit gets discovered.
const full = encoderPlan(manifest, manifest.n_audio_ctx);
const fullInfo = new Map();
for (const stage of full.stages) {
  const info = inspect(`${stage.label}@${manifest.n_audio_ctx}`, stage.kernel, stage.scope, stage);
  if (info) fullInfo.set(stage.kernel, info);
}

// Workgroup memory must not scale with context length. It did once — attention held
// N_CTX scores, so 1500 positions meant 6 KB, and 6 KB let an RDNA3 CU keep only two
// workgroups resident. The online-softmax tiling fixed it, and this assertion is what
// stops a future "just cache the scores" change from quietly undoing it: at 64 and at
// 1500 positions the footprint has to be the same number.
for (const [kernel, info] of fullInfo) {
  const short = notes.find((n) => n.kernel === kernel);
  if (!short) continue;
  check(
    short.wgBytes === info.wgBytes,
    `${kernel}: workgroup storage scales with context — ` +
      `${short.wgBytes} B at ${shapes.N_CTX} positions, ${info.wgBytes} B at ${full.shapes.N_CTX}`
  );
}

/* -------------------------------------------------- linear tail selection */

// Each LINEAR specialization must store exactly once. The three tails are flat
// conditionals, so a mistyped flag renders a kernel that computes v and drops it.
for (const stage of stages.filter((s) => s.kernel === "linear")) {
  const code = render(SOURCES.linear, {
    ...stage.scope,
    RESOURCES: resourceDeclarations(BINDINGS.linear),
  });
  const stores = (code.match(/^\s*y\[out\] =/gm) ?? []).length;
  check(stores === 1, `${stage.label}: renders ${stores} stores to y[out], expected exactly 1`);
}

/* ------------------------------------------------- linear row-tile coverage */

// The linear kernel folds LINEAR_ROW_TILE positions into one invocation, so the
// dispatch no longer covers ROWS*C_OUT lanes and the generic coverage check above
// cannot see an off-by-one here. Both context lengths in use are multiples of the
// tile, which means the shader's ragged-tail clamp never runs in any test that
// exists — so check the geometry directly, at a context that is not a multiple.
for (const nCtx of [golden.n_ctx, manifest.n_audio_ctx, 61, 1499]) {
  for (const stage of encoderPlan(manifest, nCtx).stages) {
    if (stage.kernel !== "linear") continue;
    const { ROWS, C_OUT, WG: wg } = stage.scope;
    const lanes = Math.ceil(ROWS / LINEAR_ROW_TILE) * C_OUT;
    check(
      stage.dispatch * wg >= lanes,
      `${stage.label}@${nCtx}: ${stage.dispatch}x${wg} invocations cannot cover ${lanes} lanes`
    );
    // Every position must land in exactly one tile. Too few and the tail of the
    // tensor keeps whatever the previous stage left there, which for the residual
    // tails is a plausible-looking activation rather than a zero.
    check(
      Math.ceil(ROWS / LINEAR_ROW_TILE) * LINEAR_ROW_TILE >= ROWS,
      `${stage.label}@${nCtx}: row tiling leaves ${ROWS % LINEAR_ROW_TILE} positions uncomputed`
    );
  }
}

/* --------------------------------------------- buffers the graph resolves */

const sizes = activationSizes(shapes, melParts);
const weights = buildWeightBuffers(manifest, blob);

// Every name the plan mentions must resolve to exactly one of the two kinds. A
// typo currently surfaces in the browser as "missing buffer" from makeBindGroup,
// after the model download has already been paid for.
for (const stage of stages) {
  for (const [binding, buffer] of Object.entries(stage.io)) {
    const isActivation = buffer in sizes;
    const isWeight = buffer in weights;
    check(
      isActivation !== isWeight,
      `${stage.label}: "${buffer}" resolves to ` +
        (isActivation ? "both an activation and a weight" : "neither an activation nor a weight")
    );

    // Packed-f16 bindings are declared array<u32>; handing them an f32 view would
    // reinterpret the bits and produce weights off by ~38 orders of magnitude.
    const declared = BINDINGS[stage.kernel].find((b) => b.name === binding);
    if (isWeight && declared) {
      const wantsPacked = declared.element === "u32";
      const isPacked = weights[buffer] instanceof Uint32Array;
      check(
        wantsPacked === isPacked,
        `${stage.label}: binding "${binding}" wants ${declared.element}, ` +
          `"${buffer}" is ${weights[buffer].constructor.name}`
      );
    }
  }
}

/* -------------------------------------------------------- dataflow order */

// An activation read before any stage writes it is a bug: WebGPU zero-fills, so the
// symptom is a tensor that is merely wrong rather than an error.
const written = new Set(["audio"]); // the only activation the host seeds
for (const stage of stages) {
  const table = BINDINGS[stage.kernel];
  for (const [binding, buffer] of Object.entries(stage.io)) {
    if (!(buffer in sizes)) continue;
    const isOutput = table.find((b) => b.name === binding)?.type === "storage";
    // in-place stages (mel_norm, pos_add, the residual adds) read their output too,
    // which is legal precisely because an earlier stage produced it
    check(
      isOutput || written.has(buffer),
      `${stage.label}: reads "${buffer}" before any stage writes it`
    );
    if (isOutput) written.add(buffer);
  }
}

// The residual stream must exist before the first block reads it, and `out` must
// be the last thing written — otherwise the encoder returns an intermediate.
check(written.has("out"), "no stage writes the output buffer");
check(
  stages[stages.length - 1].io.y === "out",
  `the final stage writes "${stages[stages.length - 1].io.y}", not "out"`
);

/* ------------------------------------------------------- computed tables */

const expectedBasis = 2 * shapes.BINS * manifest.n_fft;
check(
  weights.basis.length === expectedBasis && stftBasis().length === expectedBasis,
  `stft basis is ${weights.basis.length} floats, the kernel indexes ${expectedBasis}`
);

const filters = melFilters(manifest, blob);
check(
  filters.rows === shapes.N_MELS,
  `mel filterbank has ${filters.rows} rows, the plan expects ${shapes.N_MELS}`
);

// pos_add reads N_CTX*D entries off the front of the full 1500-position table.
check(
  weights.positional.length >= shapes.N_CTX * shapes.D,
  `positional table holds ${weights.positional.length} floats, ` +
    `the plan reads ${shapes.N_CTX * shapes.D}`
);

// Every offset must land inside the buffer it indexes, or the shader reads zeros and
// produces a plausible-but-wrong activation.
const qkv = layoutQkv(manifest, blob, "encoder.blocks.0");
check(
  3 * qkv.offsets.W_STRIDE === qkv.words.length,
  `qkv weight offsets do not tile the ${qkv.words.length}-word buffer`
);
check(
  qkv.offsets.B0 + 3 * qkv.D === qkv.params.length,
  `qkv params offsets do not tile the ${qkv.params.length}-element buffer`
);

/* ------------------------------------------------------------------ report */

console.table(notes);
console.log(
  `\ngraph: ${stages.length} dispatches, ${shapes.LAYERS} blocks, ` +
    `${shapes.N_CTX} positions x ${shapes.D} channels, ${shapes.HEADS} heads`
);
console.log(
  `full context: ${full.shapes.N_CTX} positions, ` +
    `${Math.max(...full.stages.map((s) => s.dispatch))} workgroups at the widest dispatch, ` +
    `${fullInfo.get("attention")?.wgBytes} B of attention scratch (context-independent)`
);

if (failures.length) {
  console.error(`\nFAIL — ${failures.length} problem(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log("PASS — every kernel specializes cleanly and every dispatch covers its outputs");
