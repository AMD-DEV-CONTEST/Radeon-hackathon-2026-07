/**
 * CPU reference implementation of the VAD WGSL kernels.
 *
 * This is not a second model — it is a line-by-line transcription of the index
 * arithmetic in kernels.js: the same packed-i32 unpacking, the same row strides,
 * the same reflect-pad fold. Its purpose is to split one hard question into two
 * easy ones:
 *
 *   GPU vs this          — should agree to f32 rounding. Any real gap is a WGSL
 *                          or driver bug (bad binding order, wrong barrier, ...).
 *   this vs ONNX Runtime — should agree to the int8 quantization budget. Any gap
 *                          here is a quantization problem, not a kernel problem.
 *
 * Environment-free on purpose so both Node (kernel-sim.test.mjs) and the browser
 * (validate.html) can use it.
 */

import { ENCODER, tensorFrom, packI8, unpackI8, layoutLstm } from "./weights.js";

const sigmoid = (v) => 1 / (1 + Math.exp(-Math.max(-60, Math.min(60, v))));

/* ---------------------------------------------------------------- kernel 1 */

export function stftKernel(audio, basisWords, basisScale, { N_IN, BINS, FRAMES, HOP, WORDS_PER_ROW }) {
  const spec = new Float32Array(BINS * FRAMES);

  const sampleAt = (i) => (i < N_IN ? audio[i] : audio[2 * N_IN - i - 2]);

  for (let frame = 0; frame < FRAMES; frame++) {
    const base = frame * HOP;
    for (let bin = 0; bin < BINS; bin++) {
      const reRow = bin * WORDS_PER_ROW;
      const imRow = (bin + BINS) * WORDS_PER_ROW;
      let accRe = 0;
      let accIm = 0;
      for (let w = 0; w < WORDS_PER_ROW; w++) {
        const reWord = basisWords[reRow + w];
        const imWord = basisWords[imRow + w];
        for (let lane = 0; lane < 4; lane++) {
          const s = sampleAt(base + w * 4 + lane);
          accRe += unpackI8(reWord, lane) * s;
          accIm += unpackI8(imWord, lane) * s;
        }
      }
      const re = accRe * basisScale[bin];
      const im = accIm * basisScale[bin + BINS];
      spec[bin * FRAMES + frame] = Math.sqrt(re * re + im * im);
    }
  }
  return spec;
}

/* ---------------------------------------------------------------- kernel 2 */

export function convKernel(x, wWords, wScale, bias, layer, relu = true) {
  const { C_IN, C_OUT, L_IN, L_OUT, K, STRIDE, PAD } = layer;
  const y = new Float32Array(C_OUT * L_OUT);

  const weightAt = (oc, idx) => {
    const flat = oc * (C_IN * K) + idx;
    return unpackI8(wWords[flat >> 2], flat & 3);
  };

  for (let oc = 0; oc < C_OUT; oc++) {
    const scale = wScale[oc];
    for (let pos = 0; pos < L_OUT; pos++) {
      let acc = 0;
      for (let ci = 0; ci < C_IN; ci++) {
        const inRow = ci * L_IN;
        for (let k = 0; k < K; k++) {
          const src = pos * STRIDE + k - PAD;
          if (src >= 0 && src < L_IN) acc += weightAt(oc, ci * K + k) * x[inRow + src];
        }
      }
      const v = acc * scale + bias[oc];
      y[oc * L_OUT + pos] = relu ? Math.max(v, 0) : v;
    }
  }
  return y;
}

/* ---------------------------------------------------------------- kernel 3 */

export function lstmHeadKernel(x, stateIn, { qw, qp, offsets }, HIDDEN = 128, IN_F = 128) {
  const { W_HH_W0, HEAD_W0, S_IH, S_HH, B_IH, B_HH, HEAD_S, HEAD_B } = offsets;
  const stateOut = new Float32Array(2 * HIDDEN);
  const hNew = new Float32Array(HIDDEN);

  const wIhAt = (row, col) => {
    const flat = row * IN_F + col;
    return unpackI8(qw[flat >> 2], flat & 3);
  };
  const wHhAt = (row, col) => {
    const flat = row * HIDDEN + col;
    return unpackI8(qw[W_HH_W0 + (flat >> 2)], flat & 3);
  };

  const gate = (unit, g) => {
    const row = g * HIDDEN + unit;
    let acc = 0;
    for (let j = 0; j < IN_F; j++) acc += wIhAt(row, j) * x[j];
    let rec = 0;
    for (let j = 0; j < HIDDEN; j++) rec += wHhAt(row, j) * stateIn[j];
    return acc * qp[S_IH + row] + qp[B_IH + row] + rec * qp[S_HH + row] + qp[B_HH + row];
  };

  for (let unit = 0; unit < HIDDEN; unit++) {
    const i = sigmoid(gate(unit, 0));
    const f = sigmoid(gate(unit, 1));
    const g = Math.tanh(gate(unit, 2));
    const o = sigmoid(gate(unit, 3));
    const cNew = f * stateIn[HIDDEN + unit] + i * g;
    const hv = o * Math.tanh(cNew);
    hNew[unit] = hv;
    stateOut[unit] = hv;
    stateOut[HIDDEN + unit] = cNew;
  }

  let acc = 0;
  for (let unit = 0; unit < HIDDEN; unit++) {
    acc += unpackI8(qw[HEAD_W0 + (unit >> 2)], unit & 3) * Math.max(hNew[unit], 0);
  }
  return { prob: sigmoid(acc * qp[HEAD_S] + qp[HEAD_B]), stateOut };
}

/* ------------------------------------------------------------------ driver */

/**
 * Bind the weight blob once so callers can run frames in a loop.
 * Returns `{ forward(audio576, stateIn) -> { prob, stateOut } }`.
 */
export function buildSimulator(manifest, blob) {
  const t = (n) => tensorFrom(manifest, blob, n);

  const basis = t("stft.forward_basis_buffer");
  const basisWords = packI8(basis.data);

  const encoders = ENCODER.map((layer) => {
    const w = t(`${layer.name}.reparam_conv.weight`);
    return { layer, words: packI8(w.data), scale: w.scale, bias: t(`${layer.name}.reparam_conv.bias`).data };
  });

  const LW = layoutLstm(manifest, blob);

  const stftScope = {
    N_IN: manifest.frame,
    BINS: manifest.stft.bins,
    FRAMES: 4,
    HOP: manifest.stft.hop,
    WORDS_PER_ROW: manifest.stft.win / 4,
  };

  return {
    hidden: manifest.hidden,
    forward(audio, stateIn) {
      let h = stftKernel(audio, basisWords, basis.scale, stftScope);
      for (const e of encoders) h = convKernel(h, e.words, e.scale, e.bias, e.layer);
      return lstmHeadKernel(h, stateIn, LW, manifest.hidden, 128);
    },
  };
}
