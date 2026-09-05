# MedGlass — Technical Breakdown (ROCm / AMD GPU Migration)

All numbers below were measured on this machine. Every inference component is
AMD-only — there is no CUDA anywhere in the stack.

## Hardware & ROCm stack

| | |
|---|---|
| GPU | AMD Radeon AI PRO R9700 (Navi 48 / RDNA4, `gfx1201`, PCI id `0x7551`) |
| VRAM | 32,686 MiB (31.9 GiB) via KFD framebuffer heap |
| Host | AMD Ryzen 5 7600 (6C/12T), Ubuntu 26.04 LTS, kernel 7.0.0-28-generic |
| System ROCm | HIP 7.1 (hipcc), hipBLAS, rocBLAS, rocminfo, rocm-smi (apt) |
| Runtime used by Ollama (unused now) | bundled ROCm 7.2 (`/usr/local/lib/ollama/rocm_v7_2`) |

The GPU was initially only reachable through Ollama's bundled ROCm runtime.
System ROCm (7.1) was installed from the Ubuntu archive so that **we build and
run our own HIP binaries** (no CUDA, no vendor runtime shim).

## Why the LLM changed (Qwen3.6 vision vs text GGUF)

The first LLM plan used the Qwen3.6:27B GGUF that Ollama had already pulled.
That blob is the **vision variant**: it carries `qwen35.vision.*` tensors and a
3-section multimodal RoPE, and upstream llama.cpp's `qwen35` loader is
text-only (it hard-codes `rope.dimension_sections` length 4), so `llama-cli`
rejects it:

```
llama_model_load: error loading model hyperparameters:
  key qwen35.rope.dimension_sections has wrong array length; expected 4, got 3
```

Resolution: use the **text-path** Qwen3.6-27B GGUF converted from the official
weights (`unsloth/Qwen3.6-27B-GGUF`, Q4_K_M, 16.8 GB) with llama.cpp **b9180+**
(master has MTP + `qwen35` text support). The model is dense 27B, 64 layers,
hybrid Gated DeltaNet + Gated Attention, 262K native context. This lets the
whole LLM pipeline run on our own HIP build with **no Ollama dependency**.

## Builds (native HIP)

```bash
# whisper.cpp
cmake -B vendor/whisper.cpp/build \
      -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 -DCMAKE_BUILD_TYPE=Release
cmake --build vendor/whisper.cpp/build -j12   # → build/bin/whisper-cli

# llama.cpp (requires b9180+ for Qwen3.6)
cmake -B vendor/llama.cpp/build \
      -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 -DCMAKE_BUILD_TYPE=Release
cmake --build vendor/llama.cpp/build -j12 --target llama-cli llama-server
```

Both `configure` logs confirm `HIP and hipBLAS found → Including HIP backend`.

## Measured GPU offload

**whisper.cpp** (`whisper-cli`, ggml-small.en):

```
whisper_backend_init_gpu: device 0: ROCm0 (type: 1)
Device 0: AMD Radeon AI PRO R9700, gfx1201, VRAM: 32624 MiB
system_info: ... ROCm : NO_VMM = 1 ...
```

**llama.cpp** (`llama-cli`, Qwen3.6-27B Q4_K_M):

```
llama_prepare_model_devices: using device ROCm0 (AMD Radeon AI PRO R9700) (0000:03:00.0) - 32550 MiB free
load_tensors: layer   0..63 assigned to device ROCm0
[ Prompt: 541.2 t/s | Generation: 27.9 t/s ]
```

100% of LLM layers run on the GPU. App `/health` reflects this live:
`backends: {whisper: whisper.cpp (ROCm), llm: CLILLM}`.

## CPU vs GPU benchmarks

Method: identical model, identical input; GPU = full offload, CPU = `--no-gpu`
(whisper) / `-ngl 0` (llama). Results in `benchmarks/cpu_vs_gpu.json`.

| Component | Input | CPU | GPU | Speedup |
|---|---|---|---|---|
| whisper.cpp small.en | 120 s audio | 6,653 ms (RTF 0.055) | 1,076 ms (RTF 0.009) | **6.2×** |
| llama.cpp Qwen3.6-27B Q4_K_M | SOAP note | 52,332 ms (8.7 tok/s) | 9,027 ms (51 tok/s) | **5.8×** |
| YOLOv8n-seg | 1 frame | 88.98 ms | unavailable¹ | — |

¹ ONNX Runtime `ROCMExecutionProvider` requires `libroctracer64.so.4`, which is
not shipped in the Ubuntu ROCm archive; YOLO currently runs on the ORT CPU EP.
The 6.2× / 5.8× speedups on the transcription and LLM stages — the two heavy
stages of the realtime loop — are the headline numbers. A direct `whisper-cli`
measurement of the same 120 s file (default flags) gives 17.3 s → 2.6 s (6.7×),
consistent with the app-path benchmark.

## Latency & concurrency notes

- whisper GPU: **111× realtime** (RTF 0.009) — ~1 s to transcribe 2 min of
  audio, leaving headroom for 5 s sliding-window processing.
- llama GPU: 28 t/s generation keeps SOAP notes interactive; the 16.8 GiB
  model loads into the 32 GiB heap in ~1.5 s per invocation.
- VRAM budget in `src/config.py` (`memory_budget_gb`, `whisper_vram_gb`,
  `yolo_vram_gb`, `llm_vram_gb`) keeps the full pipeline under the card's
  32 GiB.

## Monitor

```bash
rocm-smi --showuse --showmeminfo vram
# GPU[0] : GPU use (%) / VRAM Used (B) during concurrent inference
```

## Reproducibility

`bash setup.sh` installs the apt ROCm set and builds both HIP binaries, then
`python benchmarks/benchmark.py` regenerates `cpu_vs_gpu.json` and the summary
table above.
