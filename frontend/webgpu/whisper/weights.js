/**
 * Weight and buffer layout for the WebGPU Whisper-tiny encoder.
 *
 * Shared by the GPU runtime and the CPU reference (kernel-sim.js) so both address
 * the blob identically. The oracle is the torch forward pass captured in
 * golden.json, so a shared indexing mistake makes both paths wrong together and
 * the comparison fails — which is the point.
 *
 * Two tensors are built here instead of downloaded, because the export script
 * deliberately omits them (see scripts/export_whisper_weights.py):
 *
 *   positionalTable()  1500x384 sinusoids — a closed form, 2.3 MB if shipped
 *   stftBasis()        201x400 windowed DFT rows — a closed form, 0.6 MB if shipped
 *
 * Both are materialized once at load, not per frame: recomputing them inline
 * would put a transcendental inside every multiply-accumulate.
 */

import {
  MAX_STORAGE_BUFFERS_PER_STAGE,
  concatF32,
  halfToFloat,
  packF16,
  tensorFrom,
  unpackF16,
} from "../blob.js";

export { MAX_STORAGE_BUFFERS_PER_STAGE, concatF32, halfToFloat, packF16, tensorFrom, unpackF16 };

/** Whisper's frontend constants. The weights assume them; they are not tunable. */
export const SAMPLE_RATE = 16000;
export const N_FFT = 400;
export const HOP_LENGTH = 160;
export const N_MELS = 80;
export const STFT_BINS = N_FFT / 2 + 1; // 201
export const LN_EPS = 1e-5;

/** Whisper's log-mel floor: everything more than 8 decades below the peak is clamped. */
export const MEL_DYNAMIC_RANGE = 8.0;

/**
 * Pull a float16 matrix and its bias, the matrix packed two halves per u32 word.
 *
 * `bias` is optional because Whisper's attention key projection has none — the
 * caller substitutes zeros so the shader stays branch-free.
 */
export function linearFrom(manifest, blob, name, { bias = `${name.replace(/\.weight$/, "")}.bias` } = {}) {
  const w = tensorFrom(manifest, blob, name);
  const b = manifest.tensors[bias] ? tensorFrom(manifest, blob, bias).data : null;
  return {
    words: packF16(w.data),
    bias: b ?? new Float32Array(w.shape[0]),
    shape: w.shape,
  };
}

/** LayerNorm gain and shift, both fp32 — narrowing them saves 3 KB and nothing else. */
export function layerNormFrom(manifest, blob, prefix) {
  return {
    gamma: tensorFrom(manifest, blob, `${prefix}.weight`).data,
    beta: tensorFrom(manifest, blob, `${prefix}.bias`).data,
  };
}

/**
 * Fuse the three attention projections into one weight buffer and one bias buffer.
 *
 * Unfused this is six tensors — three matrices and three biases — against a
 * guaranteed budget of eight storage buffers per stage, and that is before the input
 * and output. Concatenating turns the boundaries into compile-time offsets, which the
 * shader wants anyway.
 *
 * The key projection has no bias in the checkpoint; a zero vector is written in its
 * slot so the shader can index `B0 + part * D` without a special case.
 */
export function layoutQkv(manifest, blob, prefix) {
  const raw = (part) => tensorFrom(manifest, blob, `${prefix}.attn.${part}.weight`);
  const bias = (part) => {
    const name = `${prefix}.attn.${part}.bias`;
    return manifest.tensors[name] ? tensorFrom(manifest, blob, name).data : null;
  };

  const [q, k, v] = ["query", "key", "value"].map(raw);
  const D = q.shape[0];
  if (k.shape[0] !== D || v.shape[0] !== D) {
    throw new Error(`${prefix}: q/k/v projections disagree on width`);
  }

  return {
    words: packF16(q.data, k.data, v.data),
    params: concatF32(
      bias("query") ?? new Float32Array(D),
      bias("key") ?? new Float32Array(D), // absent in the checkpoint; zeros keep the shader flat
      bias("value") ?? new Float32Array(D)
    ),
    // f16 sections are D*D halves each, and D is even, so word offsets are exact
    offsets: { W_STRIDE: (D * D) / 2, B0: 0 },
    D,
  };
}

/**
 * The mel filterbank as three flat f32 buffers.
 *
 * Each of the 80 rows is one triangle: a contiguous run of non-zero weights over the
 * 201 STFT bins. Storing (start, length, values) instead of the dense 80x201 matrix
 * drops 16080 numbers to 391 — and, more usefully, turns the mel projection from a
 * dense matmul into a ~5-tap dot product per output.
 *
 * `start` and `length` come from the manifest; the offset into the shared value array
 * is the running sum, computed here so the shader does not have to scan.
 */
export function melFilters(manifest, blob) {
  const start = tensorFrom(manifest, blob, "mel_filters.start").data;
  const length = tensorFrom(manifest, blob, "mel_filters.length").data;
  const value = tensorFrom(manifest, blob, "mel_filters.value").data;

  const rows = start.length;
  const voff = new Float32Array(rows);
  let run = 0;
  for (let m = 0; m < rows; m++) {
    voff[m] = run;
    run += length[m];
  }
  if (run !== value.length) {
    throw new Error(`mel filter lengths sum to ${run}, value array holds ${value.length}`);
  }

  // One buffer, three sections: the kernel is already at five bindings.
  return { meta: concatF32(start, length, voff), value, rows };
}

/**
 * Windowed DFT basis: `hann[n] * cos(2*pi*b*n/N)` and `-hann[n] * sin(...)`.
 *
 * Laid out as the real rows followed by the imaginary rows, both (BINS, N_FFT), so
 * one bin's taps are contiguous. Accumulated in f64 terms — the angle is reduced
 * modulo the period before the trig call, because at bin 200 and n 399 the raw
 * argument is ~1.25e5 radians and f32 argument reduction there costs three digits.
 */
export function stftBasis({ nFft = N_FFT, bins = STFT_BINS } = {}) {
  const basis = new Float32Array(2 * bins * nFft);
  const hann = new Float64Array(nFft);
  for (let n = 0; n < nFft; n++) {
    // periodic Hann, matching torch.hann_window / np.hanning(N+1)[:-1]
    hann[n] = 0.5 - 0.5 * Math.cos((2 * Math.PI * n) / nFft);
  }
  const imagBase = bins * nFft;
  for (let b = 0; b < bins; b++) {
    for (let n = 0; n < nFft; n++) {
      const angle = (2 * Math.PI * ((b * n) % nFft)) / nFft;
      basis[b * nFft + n] = hann[n] * Math.cos(angle);
      basis[imagBase + b * nFft + n] = -hann[n] * Math.sin(angle);
    }
  }
  return basis;
}

/**
 * Whisper's sinusoidal positional embedding, as (length, channels) row-major.
 *
 * Mirrors `whisper.model.sinusoids` and the numpy copy in the export script. The
 * export verifies this formula against the checkpoint's stored table before
 * omitting it from the download, so the two cannot silently diverge.
 */
export function positionalTable(length, channels, maxTimescale = 10000) {
  const half = channels / 2;
  const logIncrement = Math.log(maxTimescale) / (half - 1);
  const table = new Float32Array(length * channels);
  for (let i = 0; i < half; i++) {
    const invTimescale = Math.exp(-logIncrement * i);
    for (let p = 0; p < length; p++) {
      const scaled = p * invTimescale;
      table[p * channels + i] = Math.sin(scaled);
      table[p * channels + half + i] = Math.cos(scaled);
    }
  }
  return table;
}

/**
 * Every weight buffer the plan names, as typed arrays ready to upload.
 *
 * Keyed by the logical names in plan.js rather than by checkpoint tensor names, so
 * the graph and the blob are joined in exactly one place. float16 tensors come out as
 * Uint32Array (two packed halves per word, matching `unpack2x16float`); everything
 * else is Float32Array.
 *
 * `basis` and `positional` are computed, not read — see the note at the top.
 */
export function buildWeightBuffers(manifest, blob) {
  const buffers = {};
  const filters = melFilters(manifest, blob);
  buffers.melMeta = filters.meta;
  buffers.melValue = filters.value;
  buffers.basis = stftBasis();
  buffers.positional = positionalTable(manifest.n_audio_ctx, manifest.n_state);

  const addLinear = (name, tensor) => {
    const w = tensorFrom(manifest, blob, `${tensor}.weight`);
    const biasName = `${tensor}.bias`;
    buffers[`${name}.w`] = packF16(w.data);
    buffers[`${name}.bias`] = manifest.tensors[biasName]
      ? tensorFrom(manifest, blob, biasName).data
      : new Float32Array(w.shape[0]);
  };

  const addLayerNorm = (name, tensor) => {
    const ln = layerNormFrom(manifest, blob, tensor);
    buffers[`${name}.gamma`] = ln.gamma;
    buffers[`${name}.beta`] = ln.beta;
  };

  addLinear("conv1", "encoder.conv1");
  addLinear("conv2", "encoder.conv2");

  for (let b = 0; b < manifest.n_layer; b++) {
    const prefix = `encoder.blocks.${b}`;
    const qkv = layoutQkv(manifest, blob, prefix);
    buffers[`b${b}.qkv_w`] = qkv.words;
    buffers[`b${b}.qkv_p`] = qkv.params;
    addLayerNorm(`b${b}.attn_ln`, `${prefix}.attn_ln`);
    addLayerNorm(`b${b}.mlp_ln`, `${prefix}.mlp_ln`);
    addLinear(`b${b}.out`, `${prefix}.attn.out`);
    addLinear(`b${b}.fc1`, `${prefix}.mlp.0`);
    addLinear(`b${b}.fc2`, `${prefix}.mlp.2`);
  }

  addLayerNorm("ln_post", "encoder.ln_post");
  return buffers;
}

/**
 * Every shape the kernels need, derived from the manifest and one clip length.
 *
 * Centralized because the conv stem's arithmetic is easy to get subtly wrong: conv2
 * strides by 2, so the number of encoder positions is half the mel frame count, and
 * a mel frame count that is not even silently drops a frame.
 */
export function encoderShapes(manifest, nCtx) {
  const melFrames = 2 * nCtx;
  const D = manifest.n_state;
  const heads = manifest.n_head;
  if (D % heads !== 0) throw new Error(`n_state ${D} is not divisible by n_head ${heads}`);
  return {
    N_CTX: nCtx,
    MEL_FRAMES: melFrames,
    N_SAMPLES: melFrames * HOP_LENGTH,
    N_MELS: manifest.n_mels,
    D,
    HEADS: heads,
    HEAD_DIM: D / heads,
    MLP: 4 * D,
    LAYERS: manifest.n_layer,
    BINS: STFT_BINS,
    // whisper splits 1/sqrt(head_dim) across q and k so the products stay in fp16 range
    QK_SCALE: (D / heads) ** -0.25,
  };
}
