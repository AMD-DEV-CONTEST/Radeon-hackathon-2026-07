/**
 * Silero VAD running entirely in the browser on WebGPU.
 *
 * Replaces the server round-trip in the always-listening path: the model is ~313 KiB
 * of int8 weights and runs once per 32 ms, so shipping every frame to the backend just
 * to learn "this is silence" is the single most wasteful thing the client does.
 *
 * Usage:
 *     const vad = await SileroVadWebGPU.load();
 *     const p = await vad.process(float32Chunk512);   // -> speech probability
 *     vad.reset();                                    // new utterance
 */

import { compileKernel, makeBindGroup, deviceProfile } from "../wgsl-template.js";
import { STFT_WGSL, CONV_WGSL, LSTM_HEAD_WGSL } from "./kernels.js";
import { ENCODER, tensorFrom, packI8, layoutLstm } from "./weights.js";
import { fetchCachedBlob } from "../model-cache.js";

const WEIGHTS_URL = new URL("./weights/vad-int8.bin", import.meta.url);
const MANIFEST_URL = new URL("./weights/vad-int8.json", import.meta.url);

const CACHE_KEY = "silero-vad-16k-int8";

/* ------------------------------------------------------------------- runtime */

export class SileroVadWebGPU {
  static isSupported() {
    return typeof navigator !== "undefined" && !!navigator.gpu;
  }

  static async load({ onProgress } = {}) {
    if (!SileroVadWebGPU.isSupported()) throw new Error("WebGPU is not available");

    const adapter = await navigator.gpu.requestAdapter({ powerPreference: "low-power" });
    if (!adapter) throw new Error("no WebGPU adapter");

    // subgroups/f16 are optional — the kernels work without them, and asking for
    // features the adapter lacks would reject the whole device request.
    const optional = ["shader-f16", "subgroups"].filter((f) => adapter.features.has(f));
    const device = await adapter.requestDevice({ requiredFeatures: optional });

    onProgress?.({ stage: "device", loaded: 1, total: 1 });

    const [manifest, blob] = await Promise.all([
      fetch(MANIFEST_URL).then((r) => {
        if (!r.ok) throw new Error(`failed to fetch VAD manifest: ${r.status}`);
        return r.json();
      }),
      fetchCachedBlob(WEIGHTS_URL, { key: CACHE_KEY, label: "VAD weights", onProgress }),
    ]);

    const vad = new SileroVadWebGPU(device, adapter, manifest, blob);
    await vad.#init(onProgress);
    return vad;
  }

  #device;
  #profile;
  #manifest;
  #blob;
  #buffers = {};
  #kernels = {};
  #bindGroups = {};
  #context; // 64-sample carry from the previous chunk
  #stateFront = 0;
  #readback;
  #destroyed = false;

  constructor(device, adapter, manifest, blob) {
    this.#device = device;
    this.#profile = deviceProfile(adapter, device);
    this.#manifest = manifest;
    this.#blob = blob;
    this.#context = new Float32Array(manifest.context);
    this.frameSize = manifest.frame; // 576
    this.hop = manifest.hop; // 512
  }

  get profile() {
    return this.#profile;
  }

  #tensor(name) {
    return tensorFrom(this.#manifest, this.#blob, name);
  }

  #upload(label, typed, usage = GPUBufferUsage.STORAGE) {
    const buf = this.#device.createBuffer({
      label,
      size: Math.max(typed.byteLength, 4),
      usage: usage | GPUBufferUsage.COPY_DST,
    });
    this.#device.queue.writeBuffer(buf, 0, typed);
    return buf;
  }

  #scratch(label, floats) {
    return this.#device.createBuffer({
      label,
      size: floats * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
    });
  }

  async #init(onProgress) {
    const dev = this.#device;
    const m = this.#manifest;
    const B = this.#buffers;

    const FRAMES = 4; // (576 + 64 pad - 256) / 128 + 1
    const BINS = m.stft.bins;

    // --- weights ---
    const basis = this.#tensor("stft.forward_basis_buffer");
    B.basis = this.#upload("stft.basis", packI8(basis.data));
    B.basis_scale = this.#upload("stft.scale", basis.scale);

    for (const layer of ENCODER) {
      const w = this.#tensor(`${layer.name}.reparam_conv.weight`);
      const b = this.#tensor(`${layer.name}.reparam_conv.bias`);
      B[`${layer.name}.w`] = this.#upload(`${layer.name}.w`, packI8(w.data));
      B[`${layer.name}.w_scale`] = this.#upload(`${layer.name}.scale`, w.scale);
      B[`${layer.name}.bias`] = this.#upload(`${layer.name}.bias`, b.data);
    }

    // int8 weights in one buffer, f32 scales/biases in another — see weights.js
    const lstm = layoutLstm(m, this.#blob);
    B.qw = this.#upload("lstm.qw", lstm.qw);
    B.qp = this.#upload("lstm.qp", lstm.qp);

    // --- activations ---
    B.audio = this.#scratch("audio", m.frame);
    B.spec = this.#scratch("spec", BINS * FRAMES);
    for (const layer of ENCODER) {
      B[`${layer.name}.out`] = this.#scratch(`${layer.name}.out`, layer.C_OUT * layer.L_OUT);
    }
    // ping-pong so the LSTM never reads and writes the same buffer
    B.state_a = this.#scratch("state_a", 2 * m.hidden);
    B.state_b = this.#scratch("state_b", 2 * m.hidden);
    B.prob = this.#scratch("prob", 1);

    this.#readback = dev.createBuffer({
      label: "readback",
      size: 4,
      usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
    });

    onProgress?.({ stage: "compile", loaded: 0, total: 1 + ENCODER.length + 1 });

    // --- kernels ---
    const stftBindings = [
      { name: "audio", type: "read-only-storage", element: "f32" },
      { name: "basis", type: "read-only-storage", element: "i32" },
      { name: "basis_scale", type: "read-only-storage", element: "f32" },
      { name: "spec", type: "storage", element: "f32" },
    ];
    this.#kernels.stft = await compileKernel(dev, {
      label: "vad.stft",
      source: STFT_WGSL,
      bindings: stftBindings,
      scope: {
        N_IN: m.frame,
        WIN: m.stft.win,
        HOP: m.stft.hop,
        BINS,
        FRAMES,
        WORDS_PER_ROW: m.stft.win / 4,
        WG: 64,
      },
    });
    this.#bindGroups.stft = makeBindGroup(dev, this.#kernels.stft, {
      audio: B.audio,
      basis: B.basis,
      basis_scale: B.basis_scale,
      spec: B.spec,
    });

    const convBindings = [
      { name: "x", type: "read-only-storage", element: "f32" },
      { name: "w", type: "read-only-storage", element: "i32" },
      { name: "w_scale", type: "read-only-storage", element: "f32" },
      { name: "bias", type: "read-only-storage", element: "f32" },
      { name: "y", type: "storage", element: "f32" },
    ];
    this.#kernels.conv = [];
    this.#bindGroups.conv = [];
    for (let i = 0; i < ENCODER.length; i++) {
      const layer = ENCODER[i];
      const kernel = await compileKernel(dev, {
        label: `vad.${layer.name}`,
        source: CONV_WGSL,
        bindings: convBindings,
        scope: { ...layer, RELU: true, WG: 64 },
      });
      this.#kernels.conv.push({ kernel, layer });
      this.#bindGroups.conv.push(
        makeBindGroup(dev, kernel, {
          x: i === 0 ? B.spec : B[`${ENCODER[i - 1].name}.out`],
          w: B[`${layer.name}.w`],
          w_scale: B[`${layer.name}.w_scale`],
          bias: B[`${layer.name}.bias`],
          y: B[`${layer.name}.out`],
        })
      );
      onProgress?.({ stage: "compile", loaded: 1 + i, total: 1 + ENCODER.length + 1 });
    }

    const lstmBindings = [
      { name: "x", type: "read-only-storage", element: "f32" },
      { name: "state_in", type: "read-only-storage", element: "f32" },
      { name: "qw", type: "read-only-storage", element: "i32" },
      { name: "qp", type: "read-only-storage", element: "f32" },
      { name: "state_out", type: "storage", element: "f32" },
      { name: "prob", type: "storage", element: "f32" },
    ];
    this.#kernels.lstm = await compileKernel(dev, {
      label: "vad.lstm_head",
      source: LSTM_HEAD_WGSL,
      bindings: lstmBindings,
      scope: { HIDDEN: m.hidden, IN_F: 128, WG: 128, ...lstm.offsets },
    });

    const shared = { x: B["encoder.3.out"], qw: B.qw, qp: B.qp, prob: B.prob };
    // two bind groups so state_in/state_out can swap each frame
    this.#bindGroups.lstm = [
      makeBindGroup(dev, this.#kernels.lstm, {
        ...shared,
        state_in: B.state_a,
        state_out: B.state_b,
      }),
      makeBindGroup(dev, this.#kernels.lstm, {
        ...shared,
        state_in: B.state_b,
        state_out: B.state_a,
      }),
    ];

    this.reset();
    onProgress?.({ stage: "ready", loaded: 1, total: 1 });
  }

  /** Clear LSTM state and the carried context. Call at the start of an utterance. */
  reset() {
    const zeros = new Float32Array(2 * this.#manifest.hidden);
    this.#device.queue.writeBuffer(this.#buffers.state_a, 0, zeros);
    this.#device.queue.writeBuffer(this.#buffers.state_b, 0, zeros);
    this.#context.fill(0);
    this.#stateFront = 0;
  }

  /**
   * Run one 512-sample chunk. The model actually consumes 576 samples — 64 of
   * carried context plus the 512 new ones — which this handles internally.
   *
   * @param {Float32Array} chunk 512 samples in [-1, 1]
   * @returns {Promise<number>} speech probability
   */
  async process(chunk) {
    if (this.#destroyed) throw new Error("VAD has been destroyed");
    if (chunk.length !== this.hop) {
      throw new Error(`expected ${this.hop} samples, got ${chunk.length}`);
    }

    const dev = this.#device;
    const ctx = this.#manifest.context;

    const frame = new Float32Array(this.frameSize);
    frame.set(this.#context, 0);
    frame.set(chunk, ctx);
    dev.queue.writeBuffer(this.#buffers.audio, 0, frame);

    const front = this.#stateFront;
    const enc = dev.createCommandEncoder({ label: "vad" });

    const pass = enc.beginComputePass({ label: "vad.forward" });

    pass.setPipeline(this.#kernels.stft.pipeline);
    pass.setBindGroup(0, this.#bindGroups.stft);
    pass.dispatchWorkgroups(4); // one workgroup per STFT frame

    for (let i = 0; i < this.#kernels.conv.length; i++) {
      const { kernel, layer } = this.#kernels.conv[i];
      pass.setPipeline(kernel.pipeline);
      pass.setBindGroup(0, this.#bindGroups.conv[i]);
      pass.dispatchWorkgroups(Math.ceil((layer.C_OUT * layer.L_OUT) / 64));
    }

    pass.setPipeline(this.#kernels.lstm.pipeline);
    pass.setBindGroup(0, this.#bindGroups.lstm[front]);
    pass.dispatchWorkgroups(1);

    pass.end();
    enc.copyBufferToBuffer(this.#buffers.prob, 0, this.#readback, 0, 4);
    dev.queue.submit([enc.finish()]);

    this.#stateFront = 1 - front;
    this.#context.set(chunk.subarray(chunk.length - ctx));

    await this.#readback.mapAsync(GPUMapMode.READ);
    const p = new Float32Array(this.#readback.getMappedRange().slice(0))[0];
    this.#readback.unmap();
    return p;
  }

  /**
   * Read back the LSTM state as [h(128), c(128)].
   *
   * Only used by the validation harness — comparing state against ONNX Runtime
   * catches drift in the encoder stack that a correct-looking probability can hide.
   */
  async readState() {
    const bytes = 2 * this.#manifest.hidden * 4;
    const dst = this.#device.createBuffer({
      label: "state-readback",
      size: bytes,
      usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
    });
    const src = this.#stateFront === 0 ? this.#buffers.state_a : this.#buffers.state_b;
    const enc = this.#device.createCommandEncoder();
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
    this.#readback?.destroy();
    this.#device.destroy();
  }
}

export default SileroVadWebGPU;
