/**
 * Weight layout for the WebGPU VAD.
 *
 * Shared by the GPU runtime and the CPU reference so both address the blob the same
 * way. That is safe despite the shared code, because the oracle is ONNX Runtime: a
 * packing mistake makes both paths wrong together and the golden comparison fails.
 *
 * The LSTM stage exists because of a hard limit, not an optimization. WebGPU only
 * guarantees 8 storage buffers per shader stage; the fused LSTM+head needs weights,
 * scales and biases for four gate blocks plus the head, which is 13 tensors. So the
 * int8 tensors are concatenated into one buffer, the f32 tensors into another, and
 * the boundaries become compile-time offsets in the shader.
 */

import {
  MAX_STORAGE_BUFFERS_PER_STAGE,
  concatF32,
  packI8,
  tensorFrom,
  unpackI8,
} from "../blob.js";

// Re-exported so callers keep importing weight helpers from the model they are
// loading, not from a utility module they otherwise have no reason to know about.
export { MAX_STORAGE_BUFFERS_PER_STAGE, packI8, tensorFrom, unpackI8 };

export const ENCODER = [
  { name: "encoder.0", C_IN: 129, C_OUT: 128, L_IN: 4, L_OUT: 4, K: 3, STRIDE: 1, PAD: 1 },
  { name: "encoder.1", C_IN: 128, C_OUT: 64, L_IN: 4, L_OUT: 2, K: 3, STRIDE: 2, PAD: 1 },
  { name: "encoder.2", C_IN: 64, C_OUT: 64, L_IN: 2, L_OUT: 1, K: 3, STRIDE: 2, PAD: 1 },
  { name: "encoder.3", C_IN: 64, C_OUT: 128, L_IN: 1, L_OUT: 1, K: 3, STRIDE: 1, PAD: 1 },
];

/**
 * Build the two packed LSTM buffers plus the offsets the shader needs.
 *
 * Every int8 section starts on a word boundary because each is a whole number of
 * 4-byte groups (4*H*H and 4*H*I are multiples of 4, and the head is H=128 bytes),
 * so a section offset in words is just its byte offset / 4 with no rounding.
 */
export function layoutLstm(manifest, blob, { IN_F = 128 } = {}) {
  const H = manifest.hidden;
  const t = (n) => tensorFrom(manifest, blob, n);

  const wIh = t("decoder.rnn.weight_ih"); // (4H, IN_F)
  const wHh = t("decoder.rnn.weight_hh"); // (4H, H)
  const headW = t("decoder.decoder.2.weight"); // (1, H, 1)
  const bIh = t("decoder.rnn.bias_ih"); // (4H,)
  const bHh = t("decoder.rnn.bias_hh"); // (4H,)
  const headB = t("decoder.decoder.2.bias"); // (1,)

  const qw = packI8(wIh.data, wHh.data, headW.data);
  const qp = concatF32(wIh.scale, wHh.scale, bIh.data, bHh.data, headW.scale, headB.data);

  return {
    qw,
    qp,
    // int8 section starts, in words; f32 section starts, in elements
    offsets: {
      W_HH_W0: (4 * H * IN_F) / 4,
      HEAD_W0: (4 * H * IN_F + 4 * H * H) / 4,
      S_IH: 0,
      S_HH: 4 * H,
      B_IH: 8 * H,
      B_HH: 12 * H,
      HEAD_S: 16 * H,
      HEAD_B: 16 * H + 1,
    },
  };
}
