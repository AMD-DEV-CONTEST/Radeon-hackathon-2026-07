/**
 * Weight-blob primitives shared by every model in this directory.
 *
 * The export scripts (`scripts/export_*_weights.py`) all emit the same shape: one
 * binary payload plus a manifest of `{ offset, bytes, dtype, scale_offset }`. The
 * readers below are the other half of that contract, so a change to the packing
 * has exactly one place to be made on each side.
 *
 * These live outside `vad/` and `whisper/` deliberately. Two copies of `packI8`
 * that drift apart would not fail loudly — they would produce weights that are
 * subtly wrong only in the model whose copy went stale.
 */

/**
 * WebGPU's guaranteed floor for storage buffers per shader stage.
 *
 * Not a performance number: exceeding it fails pipeline creation on conforming
 * adapters with nothing more useful than "invalid PipelineLayout". Kernels that
 * need more tensors than this concatenate them and index by compile-time offset.
 */
export const MAX_STORAGE_BUFFERS_PER_STAGE = 8;

/** Typed-array view for each dtype the export scripts can emit. */
const VIEWS = {
  int8: (blob, e) => new Int8Array(blob, e.offset, e.bytes),
  float16: (blob, e) => new Uint16Array(blob, e.offset, e.bytes / 2),
  float32: (blob, e) => new Float32Array(blob, e.offset, e.bytes / 4),
};

/**
 * Slice a tensor out of the packed blob according to the manifest.
 *
 * float16 comes back as raw `Uint16Array` bit patterns, not values. Nothing on this
 * side of the wire should widen them: they go to the GPU packed two-per-word and are
 * unpacked in the shader. `halfToFloat` exists only for the CPU reference.
 */
export function tensorFrom(manifest, blob, name) {
  const e = manifest.tensors[name];
  if (!e) throw new Error(`missing tensor "${name}" in manifest`);
  const view = VIEWS[e.dtype];
  if (!view) throw new Error(`tensor "${name}": unsupported dtype "${e.dtype}"`);
  const scale =
    e.scale_offset != null ? new Float32Array(blob, e.scale_offset, e.scale_count) : null;
  return { data: view(blob, e), scale, shape: e.shape };
}

/** Pack int8 lanes into i32 words, 4 per word, zero-padded to a word boundary. */
export function packI8(...chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const padded = new Int8Array(Math.ceil(total / 4) * 4);
  let off = 0;
  for (const c of chunks) {
    padded.set(c, off);
    off += c.length;
  }
  return new Int32Array(padded.buffer);
}

/** Mirror of the WGSL `unpack_i8`: arithmetic shift out of a packed word. */
export function unpackI8(word, lane) {
  const shifted = word << (24 - 8 * lane);
  return shifted >> 24;
}

/**
 * Pack float16 bit patterns into u32 words, 2 per word.
 *
 * Chunks must have even lengths. A chunk with an odd count would push every
 * subsequent tensor half a word out of alignment, and the shader — which indexes
 * `w[i / 2u]` — would read neighbouring weights with no error anywhere.
 */
export function packF16(...chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const odd = chunks.findIndex((c) => c.length % 2);
  if (odd >= 0) throw new Error(`packF16: chunk ${odd} has odd length ${chunks[odd].length}`);
  const flat = new Uint16Array(total);
  let off = 0;
  for (const c of chunks) {
    flat.set(c, off);
    off += c.length;
  }
  return new Uint32Array(flat.buffer);
}

/**
 * Mirror of the WGSL `unpack2x16float(word)[lane]`.
 *
 * Written out rather than using `DataView.getFloat16`, which landed too late to
 * assume, or `Float16Array`, which is later still.
 */
export function halfToFloat(h) {
  const sign = h & 0x8000 ? -1 : 1;
  const exp = (h >> 10) & 0x1f;
  const frac = h & 0x3ff;
  if (exp === 0) return sign * frac * 2 ** -24; // subnormal (and zero)
  if (exp === 31) return frac ? NaN : sign * Infinity;
  return sign * (frac + 1024) * 2 ** (exp - 25);
}

/** Read lane 0 or 1 out of a packed f16 word, as f32. */
export function unpackF16(word, lane) {
  return halfToFloat((word >>> (16 * lane)) & 0xffff);
}

/** Concatenate f32 chunks into one buffer, for kernels that are out of bindings. */
export function concatF32(...chunks) {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}
