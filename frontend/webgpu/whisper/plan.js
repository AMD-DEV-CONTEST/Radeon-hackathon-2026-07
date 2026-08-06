/**
 * The Whisper encoder as a declarative dispatch graph.
 *
 * Every stage names its kernel, its specialization scope, its dispatch size, and
 * which logical buffer each binding reads or writes. Nothing here touches WebGPU,
 * which is the point: the graph can be checked in Node — shapes, coverage, binding
 * counts, buffer sizes, read-before-write — and the browser runtime becomes a loop
 * that allocates the named buffers and walks the list.
 *
 * The alternative, hand-writing 30-odd dispatches in the orchestrator, puts the
 * arithmetic somewhere a test cannot reach it. An off-by-one in a dispatch count
 * then shows up as a few zeroed rows at the end of a tensor, which looks like a
 * numerical problem rather than a bookkeeping one.
 */

import { LINEAR_TAILS } from "./kernels.js";
import { LN_EPS, MEL_DYNAMIC_RANGE, N_FFT, HOP_LENGTH, encoderShapes } from "./weights.js";

/**
 * Workgroup sizes. The four that feed a tree reduction — mel_log, mel_reduce,
 * layernorm, attention — must be powers of two; render.test.mjs enforces that.
 * `attention` is pinned to HEAD_DIM because its third phase assigns one output
 * channel per thread.
 */
export const WG = {
  stft_power: 64,
  mel_log: 64,
  mel_reduce: 256,
  mel_norm: 64,
  conv: 64,
  pos_add: 64,
  layernorm: 128,
  qkv: 64,
  linear: 64,
};

/** WebGPU's guaranteed ceiling on workgroups per dispatch dimension. */
export const MAX_WORKGROUPS_PER_DIMENSION = 65535;

/**
 * Keys per pass in the online-softmax attention kernel.
 *
 * This is the knob that decouples LDS from context length. The whole point of the
 * tiling is occupancy, so the tile wants to be small; but each tile costs two full
 * workgroup reductions, so too small and the barriers dominate. 256 keys is 1 KB of
 * scores — with the reduction scratch and the cached q row, 1.5 KB total, which lets
 * an RDNA3 CU hold ten of these workgroups instead of the two that 1500 scores allowed.
 *
 * A multiple of the workgroup size (64) so the scoring loop has no ragged tail except
 * at the very end of the context.
 */
export const ATTENTION_TILE = 256;

/**
 * Positions handled by one invocation of the linear kernel.
 *
 * A matvec per position gives the weight matrix no reuse: a thread reads a whole
 * input row to produce one scalar, so fc1 moved 1.8 GB to use 1.2 MB of weights.
 * Four positions share each loaded row, which is where the vec4 accumulator in
 * LINEAR_WGSL comes from — the shader is written for exactly this value, so it is
 * not a free parameter.
 */
export const LINEAR_ROW_TILE = 4;

const ceilDiv = (n, d) => Math.ceil(n / d);

/**
 * Build the full graph for one clip length.
 *
 * `nCtx` is the number of encoder positions, half the mel frame count. The real
 * model uses 1500 (30 s); golden.json uses 64, which exercises identical kernels
 * with a 24x smaller fixture.
 */
export function encoderPlan(manifest, nCtx) {
  const s = encoderShapes(manifest, nCtx);
  const stages = [];
  const push = (stage) => stages.push(stage);

  /* ------------------------------------------------------------ frontend */

  push({
    label: "stft_power",
    kernel: "stft_power",
    scope: {
      N_IN: s.N_SAMPLES,
      N_FFT,
      HOP: HOP_LENGTH,
      BINS: s.BINS,
      FRAMES: s.MEL_FRAMES,
      PAD: N_FFT / 2,
      WG: WG.stft_power,
    },
    // one workgroup per frame; its threads stride over the 201 bins
    dispatch: s.MEL_FRAMES,
    outputs: s.MEL_FRAMES,
    io: { audio: "audio", basis: "basis", power: "power" },
  });

  const melTotal = s.N_MELS * s.MEL_FRAMES;
  const melParts = ceilDiv(melTotal, WG.mel_log);

  push({
    label: "mel_log",
    kernel: "mel_log",
    scope: { ROWS: s.N_MELS, BINS: s.BINS, FRAMES: s.MEL_FRAMES, WG: WG.mel_log },
    dispatch: melParts,
    outputs: melTotal,
    io: {
      power: "power",
      filter_meta: "melMeta",
      filter_value: "melValue",
      log_spec: "logSpec",
      partial_max: "partialMax",
    },
  });

  push({
    label: "mel_reduce",
    kernel: "mel_reduce",
    scope: { PARTS: melParts, WG: WG.mel_reduce },
    dispatch: 1,
    outputs: 1,
    io: { partial_max: "partialMax", global_max: "globalMax" },
  });

  push({
    label: "mel_norm",
    kernel: "mel_norm",
    scope: { TOTAL: melTotal, RANGE: MEL_DYNAMIC_RANGE, WG: WG.mel_norm },
    dispatch: ceilDiv(melTotal, WG.mel_norm),
    outputs: melTotal,
    io: { global_max: "globalMax", log_spec: "logSpec" },
  });

  /* ----------------------------------------------------------- conv stem */

  const convStage = (label, layer, io) => {
    const outputs = layer.C_OUT * layer.L_OUT;
    push({
      label,
      kernel: "conv",
      scope: { ...layer, WG: WG.conv },
      dispatch: ceilDiv(outputs, WG.conv),
      outputs,
      io,
    });
  };

  convStage(
    "conv1",
    {
      C_IN: s.N_MELS,
      C_OUT: s.D,
      L_IN: s.MEL_FRAMES,
      L_OUT: s.MEL_FRAMES,
      K: 3,
      STRIDE: 1,
      PAD: 1,
      TRANSPOSE: false,
    },
    { x: "logSpec", w: "conv1.w", bias: "conv1.bias", y: "conv1" }
  );

  // conv2 strides by 2 and writes (position, channel): the transformer's layout.
  convStage(
    "conv2",
    {
      C_IN: s.D,
      C_OUT: s.D,
      L_IN: s.MEL_FRAMES,
      L_OUT: s.N_CTX,
      K: 3,
      STRIDE: 2,
      PAD: 1,
      TRANSPOSE: true,
    },
    { x: "conv1", w: "conv2.w", bias: "conv2.bias", y: "x" }
  );

  const stream = s.N_CTX * s.D;

  push({
    label: "pos_add",
    kernel: "pos_add",
    scope: { TOTAL: stream, WG: WG.pos_add },
    dispatch: ceilDiv(stream, WG.pos_add),
    outputs: stream,
    io: { positional: "positional", x: "x" },
  });

  /* -------------------------------------------------------------- blocks */

  const layerNorm = (label, prefix, target) =>
    push({
      label,
      kernel: "layernorm",
      scope: { D: s.D, EPS: LN_EPS, WG: WG.layernorm },
      dispatch: s.N_CTX, // one workgroup per position
      outputs: s.N_CTX,
      io: { x: "x", gamma: `${prefix}.gamma`, beta: `${prefix}.beta`, y: target },
    });

  const linear = (label, { C_IN, C_OUT, prefix, tail, from, to }) => {
    // One invocation per (position tile, output channel): the kernel reads a weight
    // row once and applies it to LINEAR_ROW_TILE positions, so the lane count — and
    // the dispatch — shrinks by that factor even though the output count does not.
    const lanes = ceilDiv(s.N_CTX, LINEAR_ROW_TILE) * C_OUT;
    push({
      label,
      kernel: "linear",
      scope: { C_IN, C_OUT, ROWS: s.N_CTX, WG: WG.linear, ...LINEAR_TAILS[tail] },
      dispatch: ceilDiv(lanes, WG.linear),
      outputs: lanes,
      io: { x: from, w: `${prefix}.w`, bias: `${prefix}.bias`, y: to },
    });
  };

  for (let b = 0; b < s.LAYERS; b++) {
    const p = `b${b}`;
    layerNorm(`${p}.attn_ln`, `${p}.attn_ln`, "h");

    const qkvOutputs = 3 * s.N_CTX * s.D;
    push({
      label: `${p}.qkv`,
      kernel: "qkv",
      scope: {
        D: s.D,
        N_CTX: s.N_CTX,
        W_STRIDE: (s.D * s.D) / 2,
        B0: 0,
        QK_SCALE: s.QK_SCALE,
        WG: WG.qkv,
      },
      dispatch: ceilDiv(qkvOutputs, WG.qkv),
      outputs: qkvOutputs,
      io: { h: "h", qkv_w: `${p}.qkv_w`, qkv_p: `${p}.qkv_p`, qkv: "qkv" },
    });

    push({
      label: `${p}.attention`,
      kernel: "attention",
      scope: {
        D: s.D,
        N_CTX: s.N_CTX,
        HEAD_DIM: s.HEAD_DIM,
        WG: s.HEAD_DIM, // the value pass gives each thread one output channel
        TILE: ATTENTION_TILE,
        K0: s.N_CTX * s.D,
        V0: 2 * s.N_CTX * s.D,
      },
      dispatch: s.HEADS * s.N_CTX, // one workgroup per (head, query)
      outputs: s.HEADS * s.N_CTX,
      io: { qkv: "qkv", attn: "attn" },
    });

    linear(`${p}.attn_out`, {
      C_IN: s.D,
      C_OUT: s.D,
      prefix: `${p}.out`,
      tail: "residual",
      from: "attn",
      to: "x",
    });

    layerNorm(`${p}.mlp_ln`, `${p}.mlp_ln`, "h");

    linear(`${p}.fc1`, {
      C_IN: s.D,
      C_OUT: s.MLP,
      prefix: `${p}.fc1`,
      tail: "gelu",
      from: "h",
      to: "mlp",
    });

    linear(`${p}.fc2`, {
      C_IN: s.MLP,
      C_OUT: s.D,
      prefix: `${p}.fc2`,
      tail: "residual",
      from: "mlp",
      to: "x",
    });
  }

  layerNorm("ln_post", "ln_post", "out");

  return { shapes: s, melParts, stages };
}

/**
 * Element counts for every activation buffer the plan names.
 *
 * Weight buffers are absent on purpose: their sizes come from the manifest, and
 * inventing a second source of truth for them is how a mismatched blob turns into
 * silently truncated weights. The STFT basis and the positional table count as
 * weights here even though nothing downloads them — they are uploaded once at load,
 * not produced per encode.
 */
export function activationSizes(shapes, melParts) {
  const { N_CTX, D, MLP, MEL_FRAMES, N_MELS, BINS, N_SAMPLES } = shapes;
  return {
    audio: N_SAMPLES,
    power: MEL_FRAMES * BINS,
    logSpec: N_MELS * MEL_FRAMES,
    partialMax: melParts,
    globalMax: 1,
    conv1: D * MEL_FRAMES,
    x: N_CTX * D,
    h: N_CTX * D,
    qkv: 3 * N_CTX * D,
    attn: N_CTX * D,
    mlp: N_CTX * MLP,
    out: N_CTX * D,
  };
}
