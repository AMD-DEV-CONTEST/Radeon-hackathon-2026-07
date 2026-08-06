/**
 * WGSL kernels for Silero VAD (16 kHz path).
 *
 * The whole model is four dispatches per 32 ms frame:
 *
 *   1. stft      reflect-pad + windowed conv (win 256, hop 128) + magnitude -> (129, 4)
 *   2. conv      int8 conv1d + bias + relu, specialized 4x for encoder.0..3
 *   3. lstm      fused LSTM cell (hidden 128) + relu + 1x1 conv + sigmoid head
 *
 * int8 weights are dequantized inside the accumulation loop and never materialized
 * as fp32 buffers. Weights are stored as i32 words holding 4 packed int8 values, so
 * a single load feeds four MACs.
 *
 * Every shape is a specialization constant — see wgsl-template.js.
 */

/**
 * Stage 1: STFT magnitude.
 *
 * One workgroup per output frame, one thread per frequency bin. Each thread walks the
 * 256-sample window once, accumulating the real and imaginary projections together so
 * the windowed samples are read a single time.
 *
 * Reflect padding is folded into the index math rather than materialized: the model
 * pads (0, 64) at the end, so sample index i >= N mirrors back to 2N - i - 2.
 */
export const STFT_WGSL = /* wgsl */ `
{{ RESOURCES }}

const N_IN: u32 = {{ N_IN | u32 }};          // 576 input samples
const WIN: u32 = {{ WIN | u32 }};            // 256
const HOP: u32 = {{ HOP | u32 }};            // 128
const BINS: u32 = {{ BINS | u32 }};          // 129
const FRAMES: u32 = {{ FRAMES | u32 }};      // 4
const WORDS_PER_ROW: u32 = {{ WORDS_PER_ROW | u32 }};  // 256/4 = 64
const WG: u32 = {{ WG | u32 }};

// Reflect-pad read: the graph pads (0, 64) so only the tail mirrors.
fn sample_at(i: u32) -> f32 {
  if (i < N_IN) {
    return audio[i];
  }
  // reflect without repeating the edge sample: N, N+1 -> N-2, N-3
  return audio[2u * N_IN - i - 2u];
}

// Unpack one int8 lane out of a packed i32 word.
fn unpack_i8(word: i32, lane: u32) -> f32 {
  let shifted = word << (24u - 8u * lane);
  return f32(shifted >> 24u);
}

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_id) lid: vec3<u32>) {
  let frame = wg.x;
  if (frame >= FRAMES) { return; }

  let base = frame * HOP;

  for (var bin = lid.x; bin < BINS; bin = bin + WG) {
    // rows [0, BINS) are the real basis, [BINS, 2*BINS) the imaginary basis
    let re_row = bin * WORDS_PER_ROW;
    let im_row = (bin + BINS) * WORDS_PER_ROW;
    let re_scale = basis_scale[bin];
    let im_scale = basis_scale[bin + BINS];

    var acc_re = 0.0;
    var acc_im = 0.0;

    for (var w = 0u; w < WORDS_PER_ROW; w = w + 1u) {
      let re_word = basis[re_row + w];
      let im_word = basis[im_row + w];
      let s0 = sample_at(base + w * 4u + 0u);
      let s1 = sample_at(base + w * 4u + 1u);
      let s2 = sample_at(base + w * 4u + 2u);
      let s3 = sample_at(base + w * 4u + 3u);

      acc_re = acc_re + unpack_i8(re_word, 0u) * s0 + unpack_i8(re_word, 1u) * s1
                     + unpack_i8(re_word, 2u) * s2 + unpack_i8(re_word, 3u) * s3;
      acc_im = acc_im + unpack_i8(im_word, 0u) * s0 + unpack_i8(im_word, 1u) * s1
                     + unpack_i8(im_word, 2u) * s2 + unpack_i8(im_word, 3u) * s3;
    }

    let re = acc_re * re_scale;
    let im = acc_im * im_scale;
    // output laid out (bin, frame) to match the conv's channel-major expectation
    spec[bin * FRAMES + frame] = sqrt(re * re + im * im);
  }
}
`;

/**
 * Stage 2: int8 conv1d + bias + relu, specialized per encoder layer.
 *
 * One thread per (out_channel, out_position). Input is channel-major (C, L) so the
 * K=3 taps for a given input channel are contiguous, and the weight row for an output
 * channel is walked linearly.
 *
 * Because K, C_IN, C_OUT, L_IN, L_OUT, STRIDE and PAD are all baked in, the compiler
 * fully unrolls the K loop and drops the padding branches on interior positions.
 */
export const CONV_WGSL = /* wgsl */ `
{{ RESOURCES }}

const C_IN: u32 = {{ C_IN | u32 }};
const C_OUT: u32 = {{ C_OUT | u32 }};
const L_IN: u32 = {{ L_IN | u32 }};
const L_OUT: u32 = {{ L_OUT | u32 }};
const K: u32 = {{ K | u32 }};
const STRIDE: u32 = {{ STRIDE | u32 }};
const PAD: i32 = {{ PAD }};
const WG: u32 = {{ WG | u32 }};

fn unpack_i8(word: i32, lane: u32) -> f32 {
  let shifted = word << (24u - 8u * lane);
  return f32(shifted >> 24u);
}

// weights are (C_OUT, C_IN, K) int8, packed 4-per-word along the flattened C_IN*K axis
fn weight_at(oc: u32, idx: u32) -> f32 {
  let flat = oc * (C_IN * K) + idx;
  let word = w[flat / 4u];
  return unpack_i8(word, flat % 4u);
}

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let total = C_OUT * L_OUT;
  let tid = gid.x;
  if (tid >= total) { return; }

  let oc = tid / L_OUT;
  let pos = tid % L_OUT;
  let scale = w_scale[oc];

  var acc = 0.0;
  for (var ci = 0u; ci < C_IN; ci = ci + 1u) {
    let in_row = ci * L_IN;
    for (var k = 0u; k < K; k = k + 1u) {
      let src = i32(pos * STRIDE + k) - PAD;
      if (src >= 0 && src < i32(L_IN)) {
        acc = acc + weight_at(oc, ci * K + k) * x[in_row + u32(src)];
      }
    }
  }

  let v = acc * scale + bias[oc];
{% if RELU %}
  y[oc * L_OUT + pos] = max(v, 0.0);
{% else %}
  y[oc * L_OUT + pos] = v;
{% endif %}
}
`;

/**
 * Stage 3: fused LSTM cell + decoder head.
 *
 * T == 1 for a 576-sample frame, so there is no sequence loop — this is a single
 * cell step. One workgroup of HIDDEN threads: each thread owns one hidden unit,
 * computes its four gate pre-activations, updates c and h, and writes the new state.
 *
 * The head (relu -> 1x1 conv -> sigmoid) is a dot product over the 128 hidden units,
 * so it is fused here as a workgroup reduction instead of a separate dispatch. Thread
 * 0 applies the bias and sigmoid and writes the single output probability.
 *
 * Gate row layout in the stored weights is PyTorch order [i, f, g, o], each HIDDEN wide.
 *
 * All int8 weights arrive in one buffer and all f32 scales/biases in another, split by
 * compile-time offsets. That is not a micro-optimization: WebGPU only guarantees eight
 * storage buffers per stage and the unfused form needs thirteen. See weights.js.
 */
export const LSTM_HEAD_WGSL = /* wgsl */ `
{{ RESOURCES }}

const HIDDEN: u32 = {{ HIDDEN | u32 }};
const IN_F: u32 = {{ IN_F | u32 }};
const WG: u32 = {{ WG | u32 }};

// section starts inside qw (i32 words) and qp (f32 elements)
const W_HH_W0: u32 = {{ W_HH_W0 | u32 }};
const HEAD_W0: u32 = {{ HEAD_W0 | u32 }};
const S_IH: u32 = {{ S_IH | u32 }};
const S_HH: u32 = {{ S_HH | u32 }};
const B_IH: u32 = {{ B_IH | u32 }};
const B_HH: u32 = {{ B_HH | u32 }};
const HEAD_S: u32 = {{ HEAD_S | u32 }};
const HEAD_B: u32 = {{ HEAD_B | u32 }};

var<workgroup> h_new: array<f32, HIDDEN>;
var<workgroup> partial: array<f32, WG>;

fn unpack_i8(word: i32, lane: u32) -> f32 {
  let shifted = word << (24u - 8u * lane);
  return f32(shifted >> 24u);
}

fn w_ih_at(row: u32, col: u32) -> f32 {
  let flat = row * IN_F + col;
  return unpack_i8(qw[flat / 4u], flat % 4u);
}

fn w_hh_at(row: u32, col: u32) -> f32 {
  let flat = row * HIDDEN + col;
  return unpack_i8(qw[W_HH_W0 + flat / 4u], flat % 4u);
}

fn sigmoid(v: f32) -> f32 {
  return 1.0 / (1.0 + exp(-clamp(v, -60.0, 60.0)));
}

// One gate pre-activation for one hidden unit and one gate block (0=i, 1=f, 2=g, 3=o).
fn gate(unit: u32, g: u32) -> f32 {
  let row = g * HIDDEN + unit;
  var acc = 0.0;
  for (var j = 0u; j < IN_F; j = j + 1u) {
    acc = acc + w_ih_at(row, j) * x[j];
  }
  var rec = 0.0;
  for (var j = 0u; j < HIDDEN; j = j + 1u) {
    rec = rec + w_hh_at(row, j) * state_in[j];
  }
  return acc * qp[S_IH + row] + qp[B_IH + row] + rec * qp[S_HH + row] + qp[B_HH + row];
}

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(local_invocation_id) lid: vec3<u32>) {
  let tid = lid.x;

  // --- LSTM cell (T == 1) ---
  for (var unit = tid; unit < HIDDEN; unit = unit + WG) {
    let i_g = sigmoid(gate(unit, 0u));
    let f_g = sigmoid(gate(unit, 1u));
    let g_g = tanh(gate(unit, 2u));
    let o_g = sigmoid(gate(unit, 3u));

    let c_prev = state_in[HIDDEN + unit];
    let c_new = f_g * c_prev + i_g * g_g;
    let hv = o_g * tanh(c_new);

    h_new[unit] = hv;
    state_out[unit] = hv;
    state_out[HIDDEN + unit] = c_new;
  }
  workgroupBarrier();

  // --- head: relu -> 1x1 conv -> sigmoid, as a workgroup dot product ---
  var acc = 0.0;
  for (var unit = tid; unit < HIDDEN; unit = unit + WG) {
    acc = acc + unpack_i8(qw[HEAD_W0 + unit / 4u], unit % 4u) * max(h_new[unit], 0.0);
  }
  partial[tid] = acc;
  workgroupBarrier();

  for (var stride = WG / 2u; stride > 0u; stride = stride >> 1u) {
    if (tid < stride) {
      partial[tid] = partial[tid] + partial[tid + stride];
    }
    workgroupBarrier();
  }

  if (tid == 0u) {
    prob[0] = sigmoid(partial[0] * qp[HEAD_S] + qp[HEAD_B]);
  }
}
`;
