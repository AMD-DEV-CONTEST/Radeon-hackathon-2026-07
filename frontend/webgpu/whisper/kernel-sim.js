/**
 * CPU reference implementation of the Whisper WGSL kernels.
 *
 * Not a second model — a line-by-line transcription of the index arithmetic in
 * kernels.js: the same packed-f16 unpacking, the same row strides, the same
 * reflect-pad fold, the same erf approximation. Its purpose is to split one hard
 * question into two easy ones:
 *
 *   GPU vs this      — should agree to f32 rounding. A real gap is a WGSL or driver
 *                      bug: wrong binding order, a missing barrier, a bad dispatch.
 *   this vs torch    — should agree to f32 rounding too, because f16 storage of a
 *                      float16 checkpoint is lossless. A gap here is a math problem.
 *
 * The stages are driven by the same plan.js graph the GPU walks, so the two paths
 * cannot execute different orders or different shapes. Environment-free on purpose,
 * so both Node (kernel-sim.test.mjs) and the browser (validate.html) can run it.
 */

import { unpackF16 } from "../blob.js";
import { activationSizes, encoderPlan } from "./plan.js";
import { buildWeightBuffers } from "./weights.js";

/* ------------------------------------------------------------ activations */

/** Abramowitz & Stegun 7.1.26, the same coefficients the shader uses. */
function erfApprox(x) {
  const a = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * a);
  const poly =
    t *
    (0.254829592 +
      t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
  return Math.sign(x) * (1 - poly * Math.exp(-a * a));
}

const gelu = (x) => 0.5 * x * (1 + erfApprox(x * 0.7071067811865476));

/* ---------------------------------------------------------------- kernels */

export function stftPower({ audio, basis, power }, { N_IN, N_FFT, HOP, BINS, FRAMES, PAD }) {
  const sampleAt = (i) => {
    let j = i;
    if (j < 0) j = -j;
    if (j >= N_IN) j = 2 * N_IN - j - 2;
    return audio[Math.min(Math.max(j, 0), N_IN - 1)];
  };

  for (let frame = 0; frame < FRAMES; frame++) {
    const base = frame * HOP - PAD;
    for (let bin = 0; bin < BINS; bin++) {
      const reRow = bin * N_FFT;
      const imRow = (bin + BINS) * N_FFT;
      let accRe = 0;
      let accIm = 0;
      for (let n = 0; n < N_FFT; n++) {
        const s = sampleAt(base + n);
        accRe += basis[reRow + n] * s;
        accIm += basis[imRow + n] * s;
      }
      power[frame * BINS + bin] = accRe * accRe + accIm * accIm;
    }
  }
}

export function melLog(
  { power, filter_meta: meta, filter_value: value, log_spec: logSpec, partial_max: partialMax },
  { ROWS, BINS, FRAMES, WG }
) {
  const total = ROWS * FRAMES;
  partialMax.fill(-3.0e38);

  for (let tid = 0; tid < total; tid++) {
    const row = Math.floor(tid / FRAMES);
    const frame = tid % FRAMES;

    const start = meta[row];
    const len = meta[ROWS + row];
    const voff = meta[2 * ROWS + row];

    let acc = 0;
    for (let j = 0; j < len; j++) {
      acc += value[voff + j] * power[frame * BINS + start + j];
    }

    const v = Math.log(Math.max(acc, 1e-10)) * 0.4342944819032518;
    logSpec[row * FRAMES + frame] = v;

    const wg = Math.floor(tid / WG);
    partialMax[wg] = Math.max(partialMax[wg], v);
  }
}

export function melReduce({ partial_max: partialMax, global_max: globalMax }, { PARTS }) {
  let m = -3.0e38;
  for (let i = 0; i < PARTS; i++) m = Math.max(m, partialMax[i]);
  globalMax[0] = m;
}

export function melNorm({ global_max: globalMax, log_spec: logSpec }, { TOTAL, RANGE }) {
  const floor = globalMax[0] - RANGE;
  for (let i = 0; i < TOTAL; i++) logSpec[i] = (Math.max(logSpec[i], floor) + 4) / 4;
}

export function conv(
  { x, w, bias, y },
  { C_IN, C_OUT, L_IN, L_OUT, K, STRIDE, PAD, TRANSPOSE }
) {
  const weightAt = (oc, idx) => {
    const flat = oc * (C_IN * K) + idx;
    return unpackF16(w[flat >> 1], flat & 1);
  };

  for (let oc = 0; oc < C_OUT; oc++) {
    for (let pos = 0; pos < L_OUT; pos++) {
      let acc = 0;
      for (let ci = 0; ci < C_IN; ci++) {
        const inRow = ci * L_IN;
        for (let k = 0; k < K; k++) {
          const src = pos * STRIDE + k - PAD;
          if (src >= 0 && src < L_IN) acc += weightAt(oc, ci * K + k) * x[inRow + src];
        }
      }
      const v = gelu(acc + bias[oc]);
      y[TRANSPOSE ? pos * C_OUT + oc : oc * L_OUT + pos] = v;
    }
  }
}

export function posAdd({ positional, x }, { TOTAL }) {
  for (let i = 0; i < TOTAL; i++) x[i] += positional[i];
}

export function layerNorm({ x, gamma, beta, y }, { D, EPS }, rows) {
  for (let row = 0; row < rows; row++) {
    const base = row * D;
    let s = 0;
    let sq = 0;
    for (let i = 0; i < D; i++) {
      const v = x[base + i];
      s += v;
      sq += v * v;
    }
    const mean = s / D;
    const variance = Math.max(sq / D - mean * mean, 0);
    const inv = 1 / Math.sqrt(variance + EPS);
    for (let i = 0; i < D; i++) {
      y[base + i] = (x[base + i] - mean) * inv * gamma[i] + beta[i];
    }
  }
}

export function qkvProject(
  { h, qkv_w: qw, qkv_p: qp, qkv: out },
  { D, N_CTX, W_STRIDE, B0, QK_SCALE }
) {
  for (let tid = 0; tid < 3 * N_CTX * D; tid++) {
    const part = Math.floor(tid / (N_CTX * D));
    const rest = tid % (N_CTX * D);
    const pos = Math.floor(rest / D);
    const row = rest % D;

    const wBase = part * W_STRIDE;
    const inBase = pos * D;

    let acc = 0;
    for (let c = 0; c < D; c += 4) {
      const word = wBase + ((row * D + c) >> 1);
      acc +=
        unpackF16(qw[word], 0) * h[inBase + c] +
        unpackF16(qw[word], 1) * h[inBase + c + 1] +
        unpackF16(qw[word + 1], 0) * h[inBase + c + 2] +
        unpackF16(qw[word + 1], 1) * h[inBase + c + 3];
    }

    let v = acc + qp[B0 + part * D + row];
    if (part < 2) v *= QK_SCALE;
    out[tid] = v;
  }
}

/**
 * Online softmax, tiled exactly as the shader tiles it.
 *
 * The tiling is reproduced rather than simplified away, even though a plain softmax
 * would give the same answer to within f64 rounding. The rescale-on-new-maximum step
 * is the one piece of this kernel that is easy to get subtly wrong — rescaling the
 * numerator but not the denominator, or applying the old maximum to the new tile —
 * and each of those mistakes produces plausible, smoothly-varying, wrong numbers. If
 * the reference took the straight path, it would agree with a buggy shader on short
 * contexts and diverge only once a second tile appeared.
 */
export function attention({ qkv, attn }, { D, N_CTX, HEAD_DIM, TILE, K0, V0 }, heads) {
  const tileScores = new Float64Array(TILE);
  const acc = new Float64Array(HEAD_DIM);

  for (let wg = 0; wg < heads * N_CTX; wg++) {
    const head = Math.floor(wg / N_CTX);
    const pos = wg % N_CTX;
    const headOff = head * HEAD_DIM;
    const qBase = pos * D + headOff;

    let m = -3.0e38;
    let l = 0;
    acc.fill(0);

    for (let t0 = 0; t0 < N_CTX; t0 += TILE) {
      const hi = Math.min(t0 + TILE, N_CTX);

      let tileMax = -3.0e38;
      for (let key = t0; key < hi; key++) {
        const kBase = K0 + key * D + headOff;
        let dot = 0;
        for (let d = 0; d < HEAD_DIM; d++) dot += qkv[qBase + d] * qkv[kBase + d];
        tileScores[key - t0] = dot;
        tileMax = Math.max(tileMax, dot);
      }

      const mNew = Math.max(m, tileMax);
      const rescale = Math.exp(m - mNew);

      let tileSum = 0;
      for (let key = t0; key < hi; key++) {
        const e = Math.exp(tileScores[key - t0] - mNew);
        tileScores[key - t0] = e;
        tileSum += e;
      }

      for (let t = 0; t < HEAD_DIM; t++) {
        let tileAcc = 0;
        for (let key = t0; key < hi; key++) {
          tileAcc += tileScores[key - t0] * qkv[V0 + key * D + headOff + t];
        }
        acc[t] = acc[t] * rescale + tileAcc;
      }

      l = l * rescale + tileSum;
      m = mNew;
    }

    for (let t = 0; t < HEAD_DIM; t++) attn[pos * D + headOff + t] = acc[t] / l;
  }
}

export function linear(
  { x, w, bias, y },
  { C_IN, C_OUT, ROWS, TAIL_RESIDUAL, TAIL_GELU }
) {
  for (let pos = 0; pos < ROWS; pos++) {
    const inBase = pos * C_IN;
    for (let oc = 0; oc < C_OUT; oc++) {
      const wBase = oc * C_IN;
      let acc = 0;
      for (let c = 0; c < C_IN; c += 4) {
        const word = (wBase + c) >> 1;
        acc +=
          unpackF16(w[word], 0) * x[inBase + c] +
          unpackF16(w[word], 1) * x[inBase + c + 1] +
          unpackF16(w[word + 1], 0) * x[inBase + c + 2] +
          unpackF16(w[word + 1], 1) * x[inBase + c + 3];
      }
      const v = acc + bias[oc];
      const out = pos * C_OUT + oc;
      if (TAIL_RESIDUAL) y[out] += v;
      else if (TAIL_GELU) y[out] = gelu(v);
      else y[out] = v;
    }
  }
}

/* ------------------------------------------------------------------ driver */

// Stages whose dispatch geometry carries information the scope does not: the
// number of workgroups is the loop bound, not a rounding of the output count.
const KERNELS = {
  stft_power: (bufs, scope) => stftPower(bufs, scope),
  mel_log: (bufs, scope) => melLog(bufs, scope),
  mel_reduce: (bufs, scope) => melReduce(bufs, scope),
  mel_norm: (bufs, scope) => melNorm(bufs, scope),
  conv: (bufs, scope) => conv(bufs, scope),
  pos_add: (bufs, scope) => posAdd(bufs, scope),
  layernorm: (bufs, scope, stage) => layerNorm(bufs, scope, stage.dispatch),
  qkv: (bufs, scope) => qkvProject(bufs, scope),
  attention: (bufs, scope, stage) => attention(bufs, scope, stage.dispatch / scope.N_CTX),
  linear: (bufs, scope) => linear(bufs, scope),
};

/**
 * Bind the weight blob once so callers can encode clips in a loop.
 *
 * Returns `{ shapes, stages, encode(audio) }`. `encode` also hands back the two
 * intermediates golden.json records — a mismatch in the final hidden states alone
 * cannot tell a broken frontend from a broken transformer block.
 */
export function buildSimulator(manifest, blob, nCtx) {
  const { shapes, melParts, stages } = encoderPlan(manifest, nCtx);
  const weights = buildWeightBuffers(manifest, blob);
  const sizes = activationSizes(shapes, melParts);

  return {
    shapes,
    stages,
    weights,

    encode(audio) {
      const buffers = { ...weights };
      for (const [name, n] of Object.entries(sizes)) buffers[name] = new Float32Array(n);
      buffers.audio.set(audio.subarray(0, Math.min(audio.length, shapes.N_SAMPLES)));

      const captured = {};
      for (const stage of stages) {
        const bound = {};
        for (const [binding, name] of Object.entries(stage.io)) {
          const buf = buffers[name];
          if (!buf) throw new Error(`stage "${stage.label}": missing buffer "${name}"`);
          bound[binding] = buf;
        }
        KERNELS[stage.kernel](bound, stage.scope, stage);

        // conv2 is the last thing to touch the stream before the positional add,
        // which is exactly where golden.json takes its `post_conv` checkpoint.
        if (stage.label === "conv2") captured.postConv = buffers.x.slice();
        if (stage.label === "mel_norm") captured.mel = buffers.logSpec.slice();
      }

      return { ...captured, hidden: buffers.out };
    },
  };
}
