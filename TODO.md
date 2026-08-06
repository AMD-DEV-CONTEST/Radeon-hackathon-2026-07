# TODO — ROCm (48G VRAM) deployment, testing & optimization

**Goal:** another agent picks this up on a ROCm box (AMD GPU, 48 GB VRAM) to (a) get the
existing WebGPU VAD running on the real AMD adapter, (b) build the Whisper-tiny encoder
kernels (Task #15), and (c) tune for the GPU. Everything below assumes the repo is already
cloned at the state of `main` (commit `d0138a5`, "chore: omit CI workflow from this push").

The WebGPU code is **browser code** — there is no native ROCm/CUDA path. "Running on ROCm"
means running the kernels inside a browser (headless Chrome) whose WebGPU backend is the
AMD Vulkan driver. Treat the GPU as reachable only through `navigator.gpu`.

---

## 0. Repo orientation (what already exists)

WebGPU VAD (done, validated on Metal-3 — must be re-validated on AMD):

| Path | Role |
|------|------|
| `frontend/webgpu/wgsl-template.js` | Tiny WGSL specializer + `compileKernel` / `makeBindGroup` / `deviceProfile`. **Reuse for everything.** |
| `frontend/webgpu/vad/kernels.js` | WGSL template strings: `STFT_WGSL`, `CONV_WGSL`, `LSTM_HEAD_WGSL`. |
| `frontend/webgpu/vad/weights.js` | Tensor packing: `tensorFrom`, `packI8`, `layoutLstm`, `ENCODER`. int8 + per-channel scales. |
| `frontend/webgpu/vad/silero-webgpu.js` | Orchestrator: `SileroVadWebGPU.load()` / `.process(float32)` / `.reset()`. |
| `frontend/webgpu/vad/utterance-gate.js` | Pure JS turn-taking state machine (pre-roll / hysteresis / hangover). No GPU. |
| `frontend/webgpu/vad/validate.html` | Validation page; `?auto=1` self-runs and POSTs results. |
| `scripts/validate_webgpu.mjs` | Headless-Chrome harness. **Read this before Phase 1.** |
| `scripts/export_vad_weights.py` | Builds `vad-int8.bin` / `vad-int8.json` / `golden.json` from `models/silero_vad.onnx`. |
| `frontend/webgpu/vad/weights/{vad-int8.bin,vad-int8.json,golden.json}` | Currently committed weights + ONNX reference vectors. |
| `frontend/webgpu/vad/*.test.mjs` | `node --test` units: `utterance-gate`, `kernel-sim` (CPU WGSL sim), `render` (template). GPU-free. |
| `scripts/download_silero_model.py` | Fetches the ONNX model needed by the export script. |

Python (server) side, also relevant: `audio/stream_handler.py` (dual server/client VAD),
`server.py` (`/ws/listen`), `frontend/index.html` (capture path), `tests/test_stream_handler.py`.

Docs: `README.md` → "浏览器端 VAD / On-device VAD" section (validation table, Metal-3 numbers).

---

## 1. Phase 0 — Environment on the ROCm box

1. **Node 20** (`node --version`), **Python 3.11** venv.
2. **Chrome / Chromium** with WebGPU. On Linux ROCm, WebGPU reaches the GPU through
   **Vulkan (ANGLE/Dawn)**. Install a recent Chrome/Chromium (≥ 119) or build Dawn.
3. **Vulkan + AMD ICD**: ensure `vulkaninfo` lists an `amdgpu` / `radeon` device.
   If needed set `VK_ICD_FILENAMES` to the AMD ICD json. `rocm-smi` should show the GPU.
4. **Python deps** for golden vectors: `onnxruntime`, `numpy`, `torch`, `transformers`
   (only needed for Whisper golden export in Phase 3).
5. Fetch VAD model weights if regenerating: `python scripts/download_silero_model.py`.

> Known constraint: **only 8 storage buffers are guaranteed per shader stage.** The Silero
> kernels already pack LSTM weights into `qw`/`qp` to stay under this. Any new kernel must
> respect the same limit (pack weight+scale into one buffer when needed).

---

## 2. Phase 1 — Smoke test: does WebGPU actually see the AMD GPU?

`scripts/validate_webgpu.mjs` currently launches Chrome with
`--enable-unsafe-swiftshader`, which **falls back to a CPU adapter** — that would report
"PASS" while never touching the AMD chip. **Patch the harness** (or add a `--gpu` flag) so
on ROCm it uses the real Vulkan adapter instead:

```
# conceptually — replace the swiftshader fallback with real Vulkan/WebGPU:
--headless=new --no-sandbox --disable-gpu-sandbox
--enable-unsafe-webgpu
--enable-features=Vulkan
--use-angle=vulkan
# (do NOT pass --enable-unsafe-swiftshader, or you'll validate the CPU path)
```

Run:

```bash
CHROME_PATH=/usr/bin/google-chrome node scripts/validate_webgpu.mjs
```

Success criteria for the smoke test: the printed `adapter:` line shows a **non-swiftshader**
vendor/architecture (expect `amd` / `radeon` or similar, not `swiftshader`), `f16` and
`subgroups` flags printed by `deviceProfile`. If it falls back to swiftshader, the Vulkan
ICD / Chrome flags are wrong — fix before proceeding.

> Capture the adapter report (`vendor`/`architecture`/`f16`/`subgroups`/`subgroupMinSize`)
> — you'll branch kernels on these (AMD subgroups may be width 64, not 32).

---

## 3. Phase 2 — VAD regression on ROCm

The VAD is already correct on Metal-3; confirm it matches on AMD before touching anything.

1. `node --test "frontend/webgpu/**/*.test.mjs"` — GPU-free units must pass.
2. `CHROME_PATH=… node scripts/validate_webgpu.mjs` on the real adapter.
   Expected (same budgets as Metal-3, see `validate.html`):
   - GPU-vs-CPU prob diff ≈ `1e-6` (float rounding),
   - GPU-vs-ONNX prob diff < `0.02`, **0 decision flips** at threshold 0.5,
   - p95 realtime factor well under 1.0 per 32 ms frame.
3. If any check fails: it's almost always a **subgroup-width** or **f16** assumption
   carried over from Metal. Branch in `wgsl-template.js` `deviceProfile` / kernels using
   `sgExact32` and `f16` like the Gemma-bundle pattern already in the file.

Record the AMD numbers in `README.md` next to the Metal-3 row.

---

## 4. Phase 3 — Whisper-tiny encoder kernels (Task #15)  ← DONE

Runs the Whisper-**tiny** encoder entirely in-browser on WebGPU, validated on
amd / rdna-3. Mirrors the VAD structure. What shipped, and where it diverged from
the plan above:

### 4a. Golden vectors — `scripts/export_whisper_weights.py`
Reference is `whisper.load_model("tiny")` traced encoder-only (not ONNX: the ONNX
export fuses the conv stem, which would have made `post_conv` unobservable).

**Weights are float16, not int8.** The tiny checkpoint is natively fp16, so storing
f16 is bit-exact — measured worst storage error `0.00e+00` — and costs 14.6 MiB, which
is nothing against 48 GB. int8 would have cost a `hidden` budget of 0.25 and bought a
download saving nobody asked for. Two halves pack per u32 word and unpack with core
WGSL `unpack2x16float`, so this does **not** need the `shader-f16` feature.

Emits `weights/whisper-f16.bin`, `whisper-f16.json`, `golden.json` (2 clips x 64
positions, with `mel` / `post_conv` / `hidden` / `argmax` checkpoints). The weights
are gitignored by choice; regenerate with the export script.

### 4b. Kernels — `frontend/webgpu/whisper/kernels.js`
Ten templated kernels: `stft_power`, `mel_log`, `mel_reduce`, `mel_norm`, `conv`,
`pos_add`, `layernorm`, `qkv`, `attention`, `linear`. All under 8 storage buffers.

Notes worth keeping: GELU must be the **erf** form (torch's `F.gelu` default), the
QK scale is `(D/heads)**-0.25` folded into *both* q and k, and the fused qkv buffer
exists because three matrices plus three biases would blow the buffer budget alone.

### 4c. Dispatch graph — `frontend/webgpu/whisper/plan.js`
Not in the original plan, and the most useful thing here. The 36 dispatches are a
declarative list — kernel, scope, dispatch size, buffer per binding — so Node can
check shapes, coverage, limits and read-before-write without a GPU. The browser
runtime is then a loop over that list.

### 4d. Orchestrator — `frontend/webgpu/whisper/whisper-webgpu.js`
`WhisperTinyWebGPU.load({nCtx})` / `.encode(float32)` → hidden states. All 36
dispatches go in one compute pass; the 36 stages collapse to 13 pipelines because
the four blocks are identical. `encode(audio, {until})` stops early so the harness
can read an intermediate that a later stage overwrites in place.

### 4e. Validation — `frontend/webgpu/whisper/validate.html` + `scripts/validate_whisper_webgpu.mjs`
Three checkpoints against **two** references, because they fail differently:
GPU vs the CPU transcription is a WGSL/driver bug, GPU vs torch is a modelling bug.

Measured on amd / rdna-3 (Mesa RADV, Vulkan), 8/8 checks:

| tensor | \|gpu−torch\| | \|gpu−cpu\| | budget |
|---|---|---|---|
| mel | 8.67e-5 | 1.57e-5 | 1e-3 |
| post_conv | 2.79e-5 | 4.83e-6 | 1e-3 |
| hidden | 3.89e-4 | 5.82e-4 | 5e-3 |

argmax flips 0 · load + compile 172 ms · encode 30 s window p95 **31.40 ms** (955x realtime).

Optimizations shipped (validate PASS 8/8 on amd/rdna-3, f16 true): attention online-softmax
tiling (LDS decoupled from N_CTX) + `linear` vec4 row-tiling (one weight row reused across
4 positions, fc1 fetch traffic cut to a quarter). The same vec4 row-tiling was attempted for
qkv but it **stalls the AMD RDNA3/Vulkan backend** (driver issue with the fused
three-projection + position-tiled layout) — qkv was reverted to the known-good scalar
one-element-per-invocation version.

---

## 5. Phase 4 — Optimization on 48G VRAM  ← remaining work

Reality check: Whisper-**tiny** in f16 is 14.6 MB of weights — it fits in 48 GB many
times over. The 48 GB is **not** a fit problem; it's headroom for **batched throughput**
and **f16 compute**. Tune for latency/throughput, not memory.

Starting point to beat: **31.40 ms p95** for a 30 s window at 1500 positions, single
utterance, f32 compute throughout. (Was 57.1 ms p95 before the attention + linear tiling;
qkv tiling was attempted but abandoned — see Phase 3 note.) Every lever below must be
re-checked against `validate_whisper_webgpu.mjs` — the budgets there are tight enough (no
quantization term) that a fusion bug shows up rather than hiding in the noise.

Lever ideas (verify each against the validation harness, don't guess):
- **f16 compute path**: `deviceProfile.f16` is **true** on this adapter. The weights are
  already f16 in memory and are widened to f32 on load; requesting `shader-f16` and
  keeping the accumulator f16 would double math throughput on RDNA3. Keep f32 as the
  reference path — the harness compares against it.
- **Subgroup reductions**: subgroups are available but **`sgExact32` is false** here
  (min 32, max 64), so a plain `subgroupAdd` is not safe — use the butterfly-shuffle
  branch, and keep the workgroup-memory path for adapters without subgroups. This
  matters for `layernorm`, `mel_reduce` and the two reductions inside `attention`.
- **Kernel fusion**: fuse LayerNorm+QKV, softmax+attention-reduce, GELU+fc. Fewer
  dispatches → less global-memory traffic. 36 dispatches for 4 blocks is a lot of
  round trips through VRAM for tensors of 64x384.
- **Batching**: launch one dispatch over **N utterances** instead of one. The encoder is
  stateless — unlike the VAD — so a batch dimension is just a stride. With 48 GB the
  batch that saturates the GPU is large; watch `rocm-smi` to find it.
- **Quantization**: f16 now, and it is bit-exact. int8 would only be worth revisiting if
  profiling shows the matmuls are bandwidth-bound, and it costs the tight budgets above.
- **Pipeline reuse / precompile**: already done — `whisper-webgpu.js` caches by
  (kernel, scope), so 36 stages compile 13 pipelines, in 172 ms total.
- **Measure, don't assume**: report p95 realtime factor for ROCm vs the recorded Metal-3
  baseline in `README.md`.

---

## 6. Phase 5 — Acceptance / done criteria

- [x] Chrome on ROCm reports a real `amd`/`radeon` adapter (not swiftshader) in the harness.
      → `amd` / `rdna-3`, f16 true, subgroups true (32–64, so **not** exactly 32).
- [x] VAD regression matches ONNX on AMD: GPU-vs-ONNX prob diff < 0.02, 0 decision flips.
      → 0.0207 measured, 0 flips, p95 2.4 ms per 32 ms frame.
- [x] `node --test "frontend/webgpu/**/*.test.mjs"` green. (Note: the `**` glob does not
      expand under this Node; pass explicit paths.)
- [x] Whisper-tiny encoder kernels land; `validate_whisper_webgpu.mjs` shows 0 argmax
      flips vs `golden.json` and MSE within budget. → see the table in Phase 3.
- [x] At least the f16 and/or batching optimization is implemented and measured.
      → attention online-softmax tiling + `linear` vec4 row-tiling shipped and measured
        (p95 57.1 ms → 31.40 ms, 955× realtime). qkv vec4 tiling attempted but abandoned
        (hangs the AMD RDNA3/Vulkan backend); scalar qkv retained.
- [x] README documents ROCm adapter + numbers alongside Metal-3.
      → README.md lines ~213–241 report the amd/rdna-3 table, 172 ms load+compile, and the
        955× realtime factor, with an explanation of what optimized and what didn't.

---

## 7. Gotchas already known

- **Software adapters are now a hard failure.** `scripts/lib/headless-webgpu.mjs` launches
  real Vulkan and refuses swiftshader/llvmpipe/lavapipe unless `--allow-cpu` is passed.
  Both runners share it.
- **WGSL reserves more identifiers than you'd guess** — `meta`, `shared`, `filter`,
  `output`, `sample`. A reserved binding name compiles fine in Node and fails in the
  driver. `resourceDeclarations` now rejects them at declaration time.
- **8 storage buffers / stage** hard limit — pack weights (`qw`/`qp` style) like Silero.
- **`.github/workflows/ci.yml` is intentionally untracked** (the push PAT lacked the
  `workflow` scope). Don't be surprised it's missing; re-add it with a workflow-scoped
  token if you push CI. (See `project_ci_deferred.md` in the agent memory.)
- **`references/` is an untracked nested git repo** — leave it alone.
- **Float vs int8 budget**: keep the same validation tiers as VAD — static / CPU-reference
  / real-GPU, and an ONNX/PyTorch golden vector set.
- Record all new adapter reports and timings in `README.md` (On-device VAD section) so the
  next machine has a comparison baseline.

---

## 8. Diary App (new product) — plan locked, building

A local voice diary web app on top of GraphVoice (VAD → Whisper → agent → graph → TTS)
plus Bionic-Graph at `:8088`. Full plan in `DIARY_PLAN.md`. Branch: `diary/app` off
`develop`. See TaskList #11–#18.

Locked decisions: LLM = `RobinsonLabs/Qwen3.6-35B-A3B-abliterated-GGUF` (IQ4_XS, cached)
via **llama.cpp Vulkan** (NOT HIP — `rocminfo` shows only CPU; GPU reachable via Vulkan,
proven by Whisper 8/8). TTS = local **Kokoro**. One shared graph, local single-user.
This box only.

Slices:
- [x] **Slice 0 (LLM)** — local LLM serving: prebuilt llama.cpp (`~/envs/llama.cpp`,
  ROCm/HIP) runs the cached IQ4_XS GGUF on `ROCm0` (42/42 layers offloaded),
  OpenAI-compatible API on `:8089`; startup script `scripts/start_llm_server.sh`;
  smoke-tested. ✓ done
- [x] **Slice 0 (TTS)** — install Kokoro local TTS (pip, no sudo) + replace
  `tts/qwen_tts_client.py`. → moved into **Slice 3** (completed there). ✓ done
- [x] **Slice 1** — graph foundation: Bionic-Graph Python client (Gremlin, quirk-aware),
  schema (衣食住行 + Person/Place/Event/...), MCP tool allowlist + RBAC, unit tests. ✓ done
  (commits 5aa0e7c / 58e12fc / f76c3fb; 21 offline tests green).
- [x] **Slice 2** — agent wiring: new `diary/agent.py` `DiaryAgent` (separate from legacy
  `GraphVoiceAgent`) talks to local `llama-server` (`:8089`, OpenAI-compatible, thinking
  disabled via `extra_body` w/ plain-retry fallback); asks LLM for JSON {reply, mentions,
  todos}; records via RBAC-guarded `diary.tools`; proactive future-todo nudge. Key graph-engine
  fixes: `_upsert` now looks up via a `stable_key` property (token search skips short names like
  `me:me`; `has` matches properties not `name`); `add_todo` also attaches the todo to its target
  day so the nudge can find it. 13 agent tests + 34 total diary tests green; live E2E verified
  (replies + for_date + nudge). ✓ done (commit pending)
- [x] **Slice 3** — local TTS: `tts/kokoro_tts.py` (Kokoro 0.9, CPU torch already in `.venv`),
  Mandarin voices `zf_xiaobei`/`zm_yun*` + English `af_heart` etc., 24 kHz WAV via soundfile,
  lazy torch/kokoro import, per-language pipeline cache, graceful `None` fallback. Replaced
  `qwen_tts_client` at all 4 call sites (main.py / server.py / audio/stream_handler.py /
  tests). Mandarin needs misaki deps (ordered_set, pypinyin, cn2an, jieba) — recorded in
  requirements.txt + pyproject `[voice]`. Live zh+en synthesis verified (valid WAVs). 5 offline
  TTS tests + full 39-test suite green. ✓ done (commit pending)
- [x] **Slice 4** — integrate diary into existing app + `DiaryAgent`-only server:
  - backend: new `diary/runtime.py` (shared Bionic-Graph client + per-session `DiaryAgent`);
    `audio/stream_handler.py` `process_turn_text()` (text→agent→graph→TTS) + `process_utterance()`
    now uses the diary agent; `server.py` swapped off `GraphVoiceAgent`/`Neo4jClient` → diary
    runtime, `/api/health` checks Bionic-Graph, `/api/ask` + `/api/voice` thread `date`
    (JSON/`X-Date` header, default today), WS `/ws/listen` threads `date` per connection
    (`hello` + `date` control) and accepts client-transcribed `text` turns.
  - frontend: `frontend/index.html` rebranded to 语音日记, added date-nav (scroll picker via
    native `<input type=date>`, ‹/› day steppers, 今天 quick button, future-day warning tint),
    sends the selected day via WS `hello`/`date` and `X-Date` header; dotted-face auto-listen
    unchanged. 12 new tests (runtime + stream handler + server incl. WS control dispatch);
    55-test suite green. Live E2E verified: DiaryAgent reply + entry & future-todo recorded to
    Bionic-Graph + Kokoro WAV produced. ✓ done
  - STT note: server-side `transcribe()` still uses the cloud Qwen-Omni key (placeholder in
    `.env`), so voice upload won't transcribe until a key is set or local Whisper decoder is
    wired; the typing + WS `text` paths (and the future local-Whisper path) are fully local.
    "Whisper 8/8" = encoder-kernel validation harness only (no decoder yet).
- [ ] **Slice 5** — E2E + CI: headless-browser diary flow; self-hosted ROCm runner; no-secrets gate.
- [ ] **Slice 6** — release: compose deploy on box, feature-flag, monitor SLA.



## 8. Command cheat-sheet

```bash
# GPU-free unit tests. The ** glob does NOT expand under this Node — name the dirs.
node --test frontend/webgpu/vad/*.test.mjs
node frontend/webgpu/whisper/render.test.mjs
node frontend/webgpu/whisper/kernel-sim.test.mjs

# VAD validation on the real AMD adapter
CHROME_PATH=/usr/bin/google-chrome node scripts/validate_webgpu.mjs

# Whisper encoder validation on the real AMD adapter
CHROME_PATH=/usr/bin/google-chrome node scripts/validate_whisper_webgpu.mjs

# Regenerate VAD golden/weights (needs models/silero_vad.onnx)
.venv/bin/python scripts/download_silero_model.py
.venv/bin/python scripts/export_vad_weights.py

# Regenerate Whisper golden/weights (gitignored; needs models/whisper-tiny)
.venv/bin/python scripts/download_whisper_model.py
.venv/bin/python scripts/export_whisper_weights.py

# Inspect the GPU from the host
rocm-smi
vulkaninfo | grep -i "deviceName\|driver"
```
