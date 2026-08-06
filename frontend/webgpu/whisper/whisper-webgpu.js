/**
 * Whisper-tiny's audio encoder running entirely in the browser on WebGPU.
 *
 * This class is deliberately thin. Everything that could be wrong about the encoder —
 * shapes, dispatch counts, binding names, execution order — lives in plan.js, where
 * Node can check it without a GPU. What is left here is the part that genuinely needs
 * a device: allocate the named buffers, compile the specialized shaders, and walk the
 * stage list.
 *
 * Two things are worth knowing about the walk:
 *
 *   - All 36 dispatches go into a single compute pass. WebGPU orders dispatches within
 *     a pass and makes each one's writes visible to the next, which is exactly the
 *     dependency structure a transformer has. Splitting them into passes would add
 *     synchronization the model does not need.
 *   - Pipelines are cached by (kernel, scope). The 36 stages collapse to 13 distinct
 *     specializations, because the four blocks are identical; compiling each one four
 *     times would triple the cold-start cost for nothing.
 *
 * Usage:
 *     const enc = await WhisperTinyWebGPU.load();
 *     const hidden = await enc.encode(float32Audio);   // (n_ctx, 384)
 */

import { compileKernel, deviceProfile, makeBindGroup } from "../wgsl-template.js";
import { fetchCachedBlob } from "../model-cache.js";
import { BINDINGS, SOURCES } from "./kernels.js";
import { activationSizes, encoderPlan } from "./plan.js";
import { buildWeightBuffers } from "./weights.js";

const WEIGHTS_URL = new URL("./weights/whisper-f16.bin", import.meta.url);
const MANIFEST_URL = new URL("./weights/whisper-f16.json", import.meta.url);

const CACHE_KEY = "whisper-tiny-encoder-f16";

export class WhisperTinyWebGPU {
  static isSupported() {
    return typeof navigator !== "undefined" && !!navigator.gpu;
  }

  /**
   * Fetch the weights, bring up a device, and compile the graph.
   *
   * `nCtx` is the number of encoder positions. The real model is 1500 (30 s of
   * audio); the validation harness passes 64 to match golden.json, which exercises
   * the identical kernels against a 24x smaller fixture.
   */
  static async load({ nCtx, onProgress } = {}) {
    if (!WhisperTinyWebGPU.isSupported()) throw new Error("WebGPU is not available");

    // High performance, unlike the VAD: the VAD runs every 32 ms and wants the
    // integrated GPU, this runs once per utterance and wants the discrete one.
    const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) throw new Error("no WebGPU adapter");

    // Requesting a feature the adapter lacks rejects the whole device request, so
    // ask only for what is there. Nothing below is required — `unpack2x16float` is
    // core WGSL — but the profile is reported so the harness can record it.
    const optional = ["shader-f16", "subgroups"].filter((f) => adapter.features.has(f));
    const device = await adapter.requestDevice({ requiredFeatures: optional });
    onProgress?.({ stage: "device", loaded: 1, total: 1 });

    const [manifest, blob] = await Promise.all([
      fetch(MANIFEST_URL).then((r) => {
        if (!r.ok) throw new Error(`failed to fetch Whisper manifest: ${r.status}`);
        return r.json();
      }),
      fetchCachedBlob(WEIGHTS_URL, {
        key: CACHE_KEY,
        label: "Whisper weights",
        onProgress,
      }),
    ]);

    const enc = new WhisperTinyWebGPU(device, adapter, manifest, nCtx ?? manifest.n_audio_ctx);
    await enc.#init(blob, onProgress);
    return enc;
  }

  #device;
  #profile;
  #manifest;
  #plan;
  #sizes;
  #buffers = {};
  #steps = []; // { pipeline, bindGroup, dispatch, label }
  #destroyed = false;

  constructor(device, adapter, manifest, nCtx) {
    this.#device = device;
    this.#profile = deviceProfile(adapter, device);
    this.#manifest = manifest;
    this.#plan = encoderPlan(manifest, nCtx);
    this.#sizes = activationSizes(this.#plan.shapes, this.#plan.melParts);
    this.shapes = this.#plan.shapes;
    this.sampleRate = manifest.sample_rate;
  }

  get profile() {
    return this.#profile;
  }

  /** Positions x channels of one encode, for callers sizing their own buffers. */
  get outputShape() {
    return [this.shapes.N_CTX, this.shapes.D];
  }

  async #init(blob, onProgress) {
    const dev = this.#device;
    const B = this.#buffers;

    // --- weights: uploaded once, read-only for the lifetime of the encoder ---
    const weights = buildWeightBuffers(this.#manifest, blob);
    for (const [name, typed] of Object.entries(weights)) {
      const buf = dev.createBuffer({
        label: `w:${name}`,
        size: Math.max(typed.byteLength, 4),
        usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
      });
      dev.queue.writeBuffer(buf, 0, typed);
      B[name] = buf;
    }

    // --- activations: rewritten every encode ---
    // COPY_SRC on all of them so the validation harness can read any intermediate.
    // It costs nothing on a discrete GPU and turns "the output is wrong" into a
    // question that can be answered stage by stage.
    for (const [name, elements] of Object.entries(this.#sizes)) {
      B[name] = dev.createBuffer({
        label: `a:${name}`,
        size: Math.max(elements * 4, 4),
        usage:
          GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
      });
    }

    // --- pipelines: one per distinct specialization, not per stage ---
    const { stages } = this.#plan;
    const cache = new Map();
    let compiled = 0;

    for (const stage of stages) {
      const key = `${stage.kernel}:${JSON.stringify(stage.scope)}`;
      let kernel = cache.get(key);
      if (!kernel) {
        kernel = await compileKernel(dev, {
          label: `whisper.${stage.label}`,
          source: SOURCES[stage.kernel],
          bindings: BINDINGS[stage.kernel],
          scope: stage.scope,
        });
        cache.set(key, kernel);
        onProgress?.({ stage: "compile", loaded: ++compiled, total: stages.length });
      }

      const bound = {};
      for (const [binding, name] of Object.entries(stage.io)) {
        const buf = B[name];
        if (!buf) throw new Error(`stage "${stage.label}": no buffer named "${name}"`);
        bound[binding] = buf;
      }

      this.#steps.push({
        label: stage.label,
        pipeline: kernel.pipeline,
        bindGroup: makeBindGroup(dev, kernel, bound),
        dispatch: stage.dispatch,
      });
    }

    this.pipelineCount = cache.size;
    onProgress?.({ stage: "ready", loaded: 1, total: 1 });
  }

  /**
   * Encode one clip.
   *
   * Audio shorter than the window is zero-padded, which is what Whisper's own
   * frontend does; audio longer than it is truncated, because the positional table
   * this instance uploaded only covers `N_CTX` positions.
   *
   * `until` stops the pass after the named stage and returns nothing; the caller then
   * reads whichever activation it wants with `read()`. This exists because most
   * intermediates are transient — `x` holds the conv stem's output for exactly one
   * dispatch before `pos_add` overwrites it in place — so a checkpoint like
   * golden.json's `post_conv` is unreachable once the full graph has run.
   *
   * @param {Float32Array} audio mono 16 kHz samples in [-1, 1]
   * @param {{until?: string}} [options] stage label to stop after
   * @returns {Promise<Float32Array|null>} hidden states, (N_CTX * D), row-major by position
   */
  async encode(audio, { until } = {}) {
    if (this.#destroyed) throw new Error("encoder has been destroyed");
    const { N_CTX, D, N_SAMPLES } = this.shapes;
    const dev = this.#device;

    const last = until ? this.#steps.findIndex((s) => s.label === until) : this.#steps.length - 1;
    if (last < 0) throw new Error(`no stage labelled "${until}"`);

    // The audio buffer persists between calls, so a short clip would otherwise be
    // encoded against the tail of the previous one.
    const frame = new Float32Array(N_SAMPLES);
    frame.set(audio.subarray(0, Math.min(audio.length, N_SAMPLES)));
    dev.queue.writeBuffer(this.#buffers.audio, 0, frame);

    const enc = dev.createCommandEncoder({ label: "whisper.encode" });
    const pass = enc.beginComputePass({ label: "whisper.encoder" });
    for (let i = 0; i <= last; i++) {
      const step = this.#steps[i];
      pass.setPipeline(step.pipeline);
      pass.setBindGroup(0, step.bindGroup);
      pass.dispatchWorkgroups(step.dispatch);
    }
    pass.end();
    dev.queue.submit([enc.finish()]);

    return until ? null : this.read("out", N_CTX * D);
  }

  /** Stage labels in execution order, for callers passing `until` to `encode`. */
  get stageLabels() {
    return this.#steps.map((s) => s.label);
  }

  /**
   * Copy an activation buffer back to the host.
   *
   * Public because the validation harness compares intermediates — `logSpec` is
   * golden.json's `mel`, and `x` after `encode(audio, { until: "conv2" })` is its
   * `post_conv` — and a mismatch in the final hidden states alone cannot say which
   * stage introduced it.
   */
  async read(name, elements = this.#sizes[name]) {
    const src = this.#buffers[name];
    if (!src) throw new Error(`no buffer named "${name}"`);

    const bytes = elements * 4;
    const dst = this.#device.createBuffer({
      label: `readback:${name}`,
      size: bytes,
      usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
    });
    const enc = this.#device.createCommandEncoder({ label: `readback:${name}` });
    enc.copyBufferToBuffer(src, 0, dst, 0, bytes);
    this.#device.queue.submit([enc.finish()]);

    await dst.mapAsync(GPUMapMode.READ);
    const out = new Float32Array(dst.getMappedRange().slice(0));
    dst.unmap();
    dst.destroy();
    return out;
  }

  destroy() {
    if (this.#destroyed) return;
    this.#destroyed = true;
    for (const b of Object.values(this.#buffers)) b.destroy?.();
    this.#device.destroy();
  }
}

export default WhisperTinyWebGPU;
