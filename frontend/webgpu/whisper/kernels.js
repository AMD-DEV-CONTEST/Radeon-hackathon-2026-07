/**
 * WGSL kernels for the Whisper-tiny encoder.
 *
 * One encode is nine kernel *templates*, specialized and dispatched in this order:
 *
 *   stft_power   windowed DFT power, (frames, 201)
 *   mel_log      sparse filterbank + log10, plus a per-workgroup maximum
 *   mel_reduce   those maxima to one global maximum          (1 workgroup)
 *   mel_norm     8-decade floor + affine, in place           -> (80, frames)
 *   conv         conv1d + bias + GELU, x2 (80->384, then 384->384 stride 2)
 *   pos_add      sinusoidal positional embedding             -> (n_ctx, 384)
 *   layernorm    \
 *   qkv          |  x4 blocks
 *   attention    |
 *   linear       /  projection, MLP fc1 (GELU), MLP fc2 (residual)
 *   layernorm    ln_post
 *
 * Conventions carried over from the VAD kernels:
 *
 *   - Every shape is a specialization constant, not a uniform. The driver unrolls
 *     and bounds-checks statically. See wgsl-template.js.
 *   - No kernel exceeds eight storage buffers, WebGPU's guaranteed floor.
 *
 * Where the VAD packs int8 weights four to a word, this model stores float16 two to
 * a word and widens them with `unpack2x16float` inside the accumulation loop. Whisper
 * ships a float16 checkpoint, so float16 storage is a round trip rather than a lossy
 * one, and the browser reproduces the reference model exactly instead of approximating
 * it. int8 was measured: it halves the download but costs max|d| 11.0 on hidden states
 * ranging +/-19 and reorders an argmax channel, most of it from `attn.out.weight`
 * alone. `unpack2x16float` is core WGSL — this needs no `shader-f16` feature, which
 * f16 *arithmetic* (a later optimization) would.
 *
 * The other thing that is not carried over is the activation. Silero uses ReLU;
 * Whisper uses the exact erf GELU, and the usual tanh approximation of it is off by
 * up to 3e-3 near |x|=2 — orders above the noise floor everything else here holds to.
 * So the shaders carry a real erf approximation instead.
 */

/**
 * Exact GELU, via Abramowitz & Stegun 7.1.26 (max |error| 1.5e-7 on erf).
 *
 * torch's `F.gelu` default is the erf form, and golden.json was captured from it.
 * Using the tanh approximation here would show up as a systematic bias that no
 * amount of staring at buffer layouts would explain.
 */
const GELU = /* wgsl */ `
fn erf_approx(x: f32) -> f32 {
  let a = abs(x);
  let t = 1.0 / (1.0 + 0.3275911 * a);
  let poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741
           + t * (-1.453152027 + t * 1.061405429))));
  return sign(x) * (1.0 - poly * exp(-a * a));
}

fn gelu(x: f32) -> f32 {
  return 0.5 * x * (1.0 + erf_approx(x * 0.7071067811865476));
}
`;

/* ========================================================== mel frontend == */

/**
 * Stage 1: windowed DFT power spectrum.
 *
 * One workgroup per frame, threads striding over the 201 bins. Each thread walks the
 * 400-sample window once and accumulates the real and imaginary projections together,
 * so the (reflect-padded, bounds-folded) sample read happens once per tap rather than
 * twice.
 *
 * `center=True` padding is folded into the index math instead of materialized: the
 * frontend reflect-pads N_FFT/2 on both ends, so a negative index mirrors to -i and an
 * index past the end mirrors to 2N-i-2. Neither repeats the edge sample, matching
 * numpy's `mode="reflect"`.
 *
 * Output is frame-major so the mel stage reads a frame's bins contiguously.
 */
export const STFT_POWER_WGSL = /* wgsl */ `
{{ RESOURCES }}

const N_IN: i32 = {{ N_IN }};              // audio samples
const N_FFT: u32 = {{ N_FFT | u32 }};      // 400
const HOP: u32 = {{ HOP | u32 }};          // 160
const BINS: u32 = {{ BINS | u32 }};        // 201
const FRAMES: u32 = {{ FRAMES | u32 }};
const PAD: i32 = {{ PAD }};                // N_FFT / 2
const WG: u32 = {{ WG | u32 }};

// Reflect-pad read, without repeating the edge sample.
fn sample_at(i: i32) -> f32 {
  var j = i;
  if (j < 0) { j = -j; }
  if (j >= N_IN) { j = 2 * N_IN - j - 2; }
  return audio[u32(clamp(j, 0, N_IN - 1))];
}

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_id) lid: vec3<u32>) {
  let frame = wg.x;
  if (frame >= FRAMES) { return; }

  let base = i32(frame * HOP) - PAD;

  for (var bin = lid.x; bin < BINS; bin = bin + WG) {
    let re_row = bin * N_FFT;
    let im_row = (bin + BINS) * N_FFT;

    var acc_re = 0.0;
    var acc_im = 0.0;
    for (var n = 0u; n < N_FFT; n = n + 1u) {
      let s = sample_at(base + i32(n));
      acc_re = acc_re + basis[re_row + n] * s;
      acc_im = acc_im + basis[im_row + n] * s;
    }

    power[frame * BINS + bin] = acc_re * acc_re + acc_im * acc_im;
  }
}
`;

/**
 * Stage 2: mel projection and log10, plus the running maximum.
 *
 * Each mel row is one triangle over a short contiguous run of bins, so this is a
 * ~5-tap dot product, not an 80x201 matmul. `filter_meta` holds three sections of
 * ROWS entries: bin start, run length, offset into the shared value array. (`meta`
 * would read better and is a WGSL reserved keyword.)
 *
 * The maximum is accumulated here rather than in a separate pass because the values
 * are already in registers. Whisper's floor is global — 8 decades below the loudest
 * bin *in the whole clip* — so it cannot be applied until every frame is known;
 * that is what mel_reduce and mel_norm are for.
 */
export const MEL_LOG_WGSL = /* wgsl */ `
{{ RESOURCES }}

const ROWS: u32 = {{ ROWS | u32 }};        // 80
const BINS: u32 = {{ BINS | u32 }};        // 201
const FRAMES: u32 = {{ FRAMES | u32 }};
const WG: u32 = {{ WG | u32 }};

var<workgroup> red: array<f32, WG>;

const NEG_INF: f32 = -3.0e38;

@compute @workgroup_size(WG, 1, 1)
fn main(
  @builtin(global_invocation_id) gid: vec3<u32>,
  @builtin(local_invocation_id) lid: vec3<u32>,
  @builtin(workgroup_id) wg: vec3<u32>,
) {
  let total = ROWS * FRAMES;
  let tid = gid.x;

  var value = NEG_INF;
  if (tid < total) {
    let row = tid / FRAMES;
    let frame = tid % FRAMES;

    let start = u32(filter_meta[row]);
    let len = u32(filter_meta[ROWS + row]);
    let voff = u32(filter_meta[2u * ROWS + row]);

    var acc = 0.0;
    for (var j = 0u; j < len; j = j + 1u) {
      acc = acc + filter_value[voff + j] * power[frame * BINS + start + j];
    }

    value = log(max(acc, 1e-10)) * 0.4342944819032518;  // log10, via the natural log
    log_spec[row * FRAMES + frame] = value;
  }

  red[lid.x] = value;
  workgroupBarrier();
  for (var stride = WG / 2u; stride > 0u; stride = stride >> 1u) {
    if (lid.x < stride) {
      red[lid.x] = max(red[lid.x], red[lid.x + stride]);
    }
    workgroupBarrier();
  }
  if (lid.x == 0u) {
    partial_max[wg.x] = red[0];
  }
}
`;

/**
 * Stage 3: the per-workgroup maxima down to one number.
 *
 * A single workgroup, because the input is at most a few thousand floats and a second
 * dispatch to save microseconds would cost a round trip. Kept separate from mel_norm
 * so that kernel can run at full width instead of having every workgroup redundantly
 * rescan the partials.
 */
export const MEL_REDUCE_WGSL = /* wgsl */ `
{{ RESOURCES }}

const PARTS: u32 = {{ PARTS | u32 }};
const WG: u32 = {{ WG | u32 }};

var<workgroup> red: array<f32, WG>;

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(local_invocation_id) lid: vec3<u32>) {
  var m = -3.0e38;
  for (var i = lid.x; i < PARTS; i = i + WG) {
    m = max(m, partial_max[i]);
  }
  red[lid.x] = m;
  workgroupBarrier();

  for (var stride = WG / 2u; stride > 0u; stride = stride >> 1u) {
    if (lid.x < stride) {
      red[lid.x] = max(red[lid.x], red[lid.x + stride]);
    }
    workgroupBarrier();
  }

  if (lid.x == 0u) {
    global_max[0] = red[0];
  }
}
`;

/**
 * Stage 4: dynamic-range floor and affine, in place.
 *
 * `(max(v, peak - 8) + 4) / 4`. In place because the buffer is about to be consumed
 * by conv1 in the same layout, and a copy of (80, frames) is pure bandwidth.
 */
export const MEL_NORM_WGSL = /* wgsl */ `
{{ RESOURCES }}

const TOTAL: u32 = {{ TOTAL | u32 }};
const RANGE: f32 = {{ RANGE | f32 }};      // 8 decades
const WG: u32 = {{ WG | u32 }};

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let i = gid.x;
  if (i >= TOTAL) { return; }
  let floor_v = global_max[0] - RANGE;
  log_spec[i] = (max(log_spec[i], floor_v) + 4.0) / 4.0;
}
`;

/* ============================================================= conv stem == */

/**
 * conv1d + bias + GELU, specialized per layer.
 *
 * One thread per (out_channel, out_position). Input is channel-major (C, L), so the K
 * taps for an input channel are contiguous and the weight row is walked linearly.
 *
 * conv2 sets TRANSPOSE: the transformer wants (position, channel) but conv wants
 * (channel, position), and writing the transpose costs nothing here — it is a
 * different store address, not a second pass over memory.
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
${GELU}

// weights are (C_OUT, C_IN, K) f16, packed 2-per-word along the flattened C_IN*K axis.
// K is odd (3), so a row's taps are not word-aligned and this reads one at a time.
fn weight_at(oc: u32, idx: u32) -> f32 {
  let flat = oc * (C_IN * K) + idx;
  return unpack2x16float(w[flat / 2u])[flat % 2u];
}

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let tid = gid.x;
  if (tid >= C_OUT * L_OUT) { return; }

  let oc = tid / L_OUT;
  let pos = tid % L_OUT;

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

  let v = gelu(acc + bias[oc]);
{% if TRANSPOSE %}
  y[pos * C_OUT + oc] = v;
{% else %}
  y[oc * L_OUT + pos] = v;
{% endif %}
}
`;

/**
 * Add the sinusoidal positional embedding, in place.
 *
 * A separate dispatch rather than a tail on conv2 so golden.json's `post_conv`
 * checkpoint stays observable: without it, a broken conv stem and a broken
 * positional table are the same symptom.
 */
export const POS_ADD_WGSL = /* wgsl */ `
{{ RESOURCES }}

const TOTAL: u32 = {{ TOTAL | u32 }};
const WG: u32 = {{ WG | u32 }};

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let i = gid.x;
  if (i >= TOTAL) { return; }
  x[i] = x[i] + positional[i];
}
`;

/* ========================================================== transformer == */

/**
 * LayerNorm over the channel axis, one workgroup per position.
 *
 * Sum and sum-of-squares in a single pass, then a tree reduction over both at once —
 * two barriers instead of four. The variance is the biased one, matching
 * `F.layer_norm`; using the unbiased estimator here would be wrong by a factor of
 * D/(D-1), small enough to look like noise and large enough to fail the golden check.
 */
export const LAYERNORM_WGSL = /* wgsl */ `
{{ RESOURCES }}

const D: u32 = {{ D | u32 }};
const EPS: f32 = {{ EPS }};
const WG: u32 = {{ WG | u32 }};

var<workgroup> red_sum: array<f32, WG>;
var<workgroup> red_sq: array<f32, WG>;

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_id) lid: vec3<u32>) {
  let row = wg.x * D;
  let tid = lid.x;

  var s = 0.0;
  var sq = 0.0;
  for (var i = tid; i < D; i = i + WG) {
    let v = x[row + i];
    s = s + v;
    sq = sq + v * v;
  }
  red_sum[tid] = s;
  red_sq[tid] = sq;
  workgroupBarrier();

  for (var stride = WG / 2u; stride > 0u; stride = stride >> 1u) {
    if (tid < stride) {
      red_sum[tid] = red_sum[tid] + red_sum[tid + stride];
      red_sq[tid] = red_sq[tid] + red_sq[tid + stride];
    }
    workgroupBarrier();
  }

  let mean = red_sum[0] / f32(D);
  let variance = max(red_sq[0] / f32(D) - mean * mean, 0.0);
  let inv = inverseSqrt(variance + EPS);

  for (var i = tid; i < D; i = i + WG) {
    y[row + i] = (x[row + i] - mean) * inv * gamma[i] + beta[i];
  }
}
`;

/**
 * The three attention projections in one dispatch.
 *
 * One thread per (position, output), where output indexes a 3D-wide concatenation of
 * q, k and v. Fused because it is the same input row read three times: splitting it
 * would triple the reads of `h` for no benefit.
 *
 * Whisper folds 1/sqrt(head_dim) into q and k as head_dim^-0.25 each, rather than
 * applying it once to the scores. That is an fp16 range trick from the original
 * model; it is reproduced exactly here so the comparison against golden.json is not
 * chasing a difference this code introduced.
 *
 * Output layout is [q | k | v], each (N_CTX, D).
 */
export const QKV_WGSL = /* wgsl */ `
{{ RESOURCES }}

const D: u32 = {{ D | u32 }};
const N_CTX: u32 = {{ N_CTX | u32 }};
const W_STRIDE: u32 = {{ W_STRIDE | u32 }};   // words per projection
const B0: u32 = {{ B0 | u32 }};               // biases, 3 x D
const QK_SCALE: f32 = {{ QK_SCALE }};
const WG: u32 = {{ WG | u32 }};

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let tid = gid.x;
  if (tid >= 3u * N_CTX * D) { return; }

  let part = tid / (N_CTX * D);      // 0 = query, 1 = key, 2 = value
  let rest = tid % (N_CTX * D);
  let pos = rest / D;
  let row = rest % D;

  let w_base = part * W_STRIDE;
  let in_base = pos * D;

  var acc = 0.0;
  for (var c = 0u; c < D; c = c + 4u) {
    let word = w_base + (row * D + c) / 2u;
    let lo = unpack2x16float(qkv_w[word]);
    let hi = unpack2x16float(qkv_w[word + 1u]);
    acc = acc + lo.x * h[in_base + c]
              + lo.y * h[in_base + c + 1u]
              + hi.x * h[in_base + c + 2u]
              + hi.y * h[in_base + c + 3u];
  }

  var v = acc + qkv_p[B0 + part * D + row];
  if (part < 2u) {
    v = v * QK_SCALE;
  }
  qkv[tid] = v;
}
`;

/**
 * Scaled dot-product attention with an online softmax, one workgroup per
 * (head, query position).
 *
 * The obvious implementation scores every key into workgroup memory, reduces, then
 * accumulates. It is correct, and it was the first version here, but it makes the
 * workgroup's LDS footprint scale with N_CTX: 1500 scores is 6 KB, and at 6 KB an
 * RDNA3 CU fits two workgroups — 128 of the ~1024 threads it can hold. Attention was
 * 44% of the encoder's runtime while starving the machine of occupancy.
 *
 * So the keys are processed in fixed TILE-sized chunks, carrying the softmax forward
 * between them (the FlashAttention accounting):
 *
 *     m  running maximum score
 *     l  running sum of exp(score - m)
 *     acc running weighted sum of values, one channel per thread
 *
 * When a tile raises the maximum, everything accumulated so far is rescaled by
 * exp(m_old - m_new) — algebraically a no-op, which is what makes this exact rather
 * than approximate. LDS is now TILE + WG + HEAD_DIM floats regardless of context
 * length, so occupancy no longer depends on how long the audio is.
 *
 * `q` is hoisted into LDS as well. It is the same HEAD_DIM values against every key,
 * and re-reading it from VRAM once per tile was 24 round trips at the full context.
 *
 * The maximum is not defensive bookkeeping: `exp` of an unshifted score overflows f32
 * well before the softmax would, and the result is a NaN row rather than a slightly
 * wrong one.
 *
 * No causal mask — this is the audio encoder, which attends bidirectionally.
 */
export const ATTENTION_WGSL = /* wgsl */ `
{{ RESOURCES }}

const D: u32 = {{ D | u32 }};
const N_CTX: u32 = {{ N_CTX | u32 }};
const HEAD_DIM: u32 = {{ HEAD_DIM | u32 }};
const WG: u32 = {{ WG | u32 }};               // == HEAD_DIM
const TILE: u32 = {{ TILE | u32 }};           // keys per pass, independent of N_CTX
const Q0: u32 = 0u;
const K0: u32 = {{ K0 | u32 }};
const V0: u32 = {{ V0 | u32 }};

var<workgroup> tile_scores: array<f32, TILE>;
var<workgroup> red: array<f32, WG>;
var<workgroup> q_cache: array<f32, HEAD_DIM>;

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_id) lid: vec3<u32>) {
  let head = wg.x / N_CTX;
  let pos = wg.x % N_CTX;
  let tid = lid.x;

  let head_off = head * HEAD_DIM;

  // WG == HEAD_DIM, so this is exactly one element per thread.
  q_cache[tid] = qkv[Q0 + pos * D + head_off + tid];
  workgroupBarrier();

  var m = -3.0e38;   // running maximum
  var l = 0.0;       // running denominator
  var acc = 0.0;     // running numerator for this thread's output channel

  for (var t0 = 0u; t0 < N_CTX; t0 = t0 + TILE) {
    let hi = min(t0 + TILE, N_CTX);

    // --- score this tile: thread per key, striding ---
    var local_max = -3.0e38;
    for (var key = t0 + tid; key < hi; key = key + WG) {
      let k_base = K0 + key * D + head_off;
      var dot = 0.0;
      for (var d = 0u; d < HEAD_DIM; d = d + 1u) {
        dot = dot + q_cache[d] * qkv[k_base + d];
      }
      tile_scores[key - t0] = dot;
      local_max = max(local_max, dot);
    }
    red[tid] = local_max;
    workgroupBarrier();
    for (var stride = WG / 2u; stride > 0u; stride = stride >> 1u) {
      if (tid < stride) { red[tid] = max(red[tid], red[tid + stride]); }
      workgroupBarrier();
    }
    let tile_max = red[0];
    workgroupBarrier();

    // --- exponentiate against the running maximum, not the tile's ---
    let m_new = max(m, tile_max);
    let rescale = exp(m - m_new);

    var local_sum = 0.0;
    for (var key = t0 + tid; key < hi; key = key + WG) {
      let e = exp(tile_scores[key - t0] - m_new);
      tile_scores[key - t0] = e;
      local_sum = local_sum + e;
    }
    red[tid] = local_sum;
    workgroupBarrier();
    for (var stride = WG / 2u; stride > 0u; stride = stride >> 1u) {
      if (tid < stride) { red[tid] = red[tid] + red[tid + stride]; }
      workgroupBarrier();
    }
    let tile_sum = red[0];
    workgroupBarrier();

    // --- accumulate values: thread per output channel, so this read coalesces ---
    var tile_acc = 0.0;
    for (var key = t0; key < hi; key = key + 1u) {
      tile_acc = tile_acc + tile_scores[key - t0] * qkv[V0 + key * D + head_off + tid];
    }

    acc = acc * rescale + tile_acc;
    l = l * rescale + tile_sum;
    m = m_new;

    // tile_scores is about to be overwritten by the next tile's scoring loop, and
    // the accumulation above reads every lane of it, not just this thread's.
    workgroupBarrier();
  }

  attn[pos * D + head_off + tid] = acc / l;
}
`;

/**
 * Matrix-vector per position: `y = f(W x + b)`, with the tail chosen at
 * specialization time.
 *
 * Covers three of the four linear layers in a block — attention output projection
 * (TAIL_RESIDUAL), MLP fc1 (TAIL_GELU) and MLP fc2 (TAIL_RESIDUAL) — because they
 * differ only in that tail. The residual adds into `y` in place, which is what makes
 * the skip connection free: the destination already holds x.
 *
 * Exactly one TAIL_ flag must be set. They are three flat conditionals rather than an
 * if/else chain because the template engine matches the nearest `{% endif %}`, so a
 * nested conditional would silently mis-parse. render.test.mjs asserts that each
 * specialization emits exactly one store.
 *
 * The C_IN loop steps four at a time — two word loads, four MACs, enough independent
 * work to hide the unpack latency. C_IN is 384 or 1536 here, both multiples of four,
 * so there is no remainder to handle and no row starts mid-word.
 *
 * Each invocation carries ROW_TILE positions rather than one. With one position per
 * thread the weight matrix has no reuse anywhere in the machine: a thread reads a
 * whole C_IN row to produce a single scalar, and the 1500 threads that want that same
 * row sit ROWS apart in the dispatch, so they run at unrelated times and each fetches
 * it again. fc1 was moving 1.8 GB per dispatch for a 1.2 MB weight matrix, and its
 * measured cost matched that traffic almost exactly. Reading the row once and applying
 * it to four positions divides the weight traffic by four.
 *
 * The four positions live in a vec4 accumulator, which is why ROW_TILE is spelled out
 * in the shader instead of templated — the arithmetic below only makes sense at 4.
 * Per output channel the accumulation order over C_IN is untouched, so the result is
 * bit-identical to the untiled kernel and the simulator needs no matching change.
 *
 * Activations are read four rows at a time, but every thread in a workgroup shares the
 * same four rows (C_OUT is a multiple of WG), so those loads broadcast out of cache.
 */
export const LINEAR_WGSL = /* wgsl */ `
{{ RESOURCES }}

const C_IN: u32 = {{ C_IN | u32 }};
const C_OUT: u32 = {{ C_OUT | u32 }};
const ROWS: u32 = {{ ROWS | u32 }};        // positions
const WG: u32 = {{ WG | u32 }};
const ROW_TILE: u32 = 4u;                  // positions per invocation; the vec4 assumes it
${GELU}

/**
 * Apply the tail and store, or drop the lane if a ragged last tile ran past the end.
 * One store site keeps the "exactly one tail" invariant checkable by render.test.mjs.
 */
fn emit(pos: u32, oc: u32, v: f32) {
  if (pos >= ROWS) { return; }
  let out = pos * C_OUT + oc;
{% if TAIL_RESIDUAL %}
  y[out] = y[out] + v;
{% endif %}
{% if TAIL_GELU %}
  y[out] = gelu(v);
{% endif %}
{% if TAIL_PLAIN %}
  y[out] = v;
{% endif %}
}

@compute @workgroup_size(WG, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let tid = gid.x;
  let tiles = (ROWS + ROW_TILE - 1u) / ROW_TILE;
  if (tid >= tiles * C_OUT) { return; }

  let oc = tid % C_OUT;
  let pos0 = (tid / C_OUT) * ROW_TILE;
  let w_base = oc * C_IN;

  // A ragged last tile clamps to the final row rather than reading out of bounds; the
  // duplicated lanes compute a real value and are dropped by emit().
  let last = ROWS - 1u;
  let b0 = min(pos0, last) * C_IN;
  let b1 = min(pos0 + 1u, last) * C_IN;
  let b2 = min(pos0 + 2u, last) * C_IN;
  let b3 = min(pos0 + 3u, last) * C_IN;

  var acc = vec4<f32>(0.0);
  for (var c = 0u; c < C_IN; c = c + 4u) {
    let word = (w_base + c) / 2u;
    let lo = unpack2x16float(w[word]);
    let hi = unpack2x16float(w[word + 1u]);
    acc = acc + lo.x * vec4<f32>(x[b0 + c], x[b1 + c], x[b2 + c], x[b3 + c])
              + lo.y * vec4<f32>(x[b0 + c + 1u], x[b1 + c + 1u], x[b2 + c + 1u], x[b3 + c + 1u])
              + hi.x * vec4<f32>(x[b0 + c + 2u], x[b1 + c + 2u], x[b2 + c + 2u], x[b3 + c + 2u])
              + hi.y * vec4<f32>(x[b0 + c + 3u], x[b1 + c + 3u], x[b2 + c + 3u], x[b3 + c + 3u]);
  }

  let b = bias[oc];
  emit(pos0, oc, acc.x + b);
  emit(pos0 + 1u, oc, acc.y + b);
  emit(pos0 + 2u, oc, acc.z + b);
  emit(pos0 + 3u, oc, acc.w + b);
}
`;

/**
 * The three mutually exclusive tails of LINEAR_WGSL, as scope fragments.
 *
 * Spelling them out here keeps the "exactly one" invariant in one place instead of
 * at each of the three call sites, where a typo in a flag name would render a kernel
 * that computes the right value and stores nothing.
 */
export const LINEAR_TAILS = {
  residual: { TAIL_RESIDUAL: true, TAIL_GELU: false, TAIL_PLAIN: false },
  gelu: { TAIL_RESIDUAL: false, TAIL_GELU: true, TAIL_PLAIN: false },
  plain: { TAIL_RESIDUAL: false, TAIL_GELU: false, TAIL_PLAIN: true },
};

/* ============================================================== bindings == */

/**
 * The binding table for each kernel, in `@binding(n)` order.
 *
 * Exported rather than written at the call site so the runtime and the static
 * checks cannot disagree: a test that declares its own table can pass while the
 * shader it is checking is dispatched against a different one. `makeBindGroup`
 * resolves buffers by these names, so the names are part of the contract too.
 */
const ro = (name, element = "f32") => ({ name, type: "read-only-storage", element });
const rw = (name, element = "f32") => ({ name, type: "storage", element });

export const BINDINGS = {
  stft_power: [ro("audio"), ro("basis"), rw("power")],
  mel_log: [ro("power"), ro("filter_meta"), ro("filter_value"), rw("log_spec"), rw("partial_max")],
  mel_reduce: [ro("partial_max"), rw("global_max")],
  mel_norm: [ro("global_max"), rw("log_spec")],
  conv: [ro("x"), ro("w", "u32"), ro("bias"), rw("y")],
  pos_add: [ro("positional"), rw("x")],
  layernorm: [ro("x"), ro("gamma"), ro("beta"), rw("y")],
  qkv: [ro("h"), ro("qkv_w", "u32"), ro("qkv_p"), rw("qkv")],
  attention: [ro("qkv"), rw("attn")],
  linear: [ro("x"), ro("w", "u32"), ro("bias"), rw("y")],
};

/** Kernel label -> WGSL template, so callers can iterate the set. */
export const SOURCES = {
  stft_power: STFT_POWER_WGSL,
  mel_log: MEL_LOG_WGSL,
  mel_reduce: MEL_REDUCE_WGSL,
  mel_norm: MEL_NORM_WGSL,
  conv: CONV_WGSL,
  pos_add: POS_ADD_WGSL,
  layernorm: LAYERNORM_WGSL,
  qkv: QKV_WGSL,
  attention: ATTENTION_WGSL,
  linear: LINEAR_WGSL,
};
