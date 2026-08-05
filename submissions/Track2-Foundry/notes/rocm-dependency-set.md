# ROCm dependency set: what's established vs. unconfirmed (July 16, 2026)

One-liner: every GPU touchpoint in Foundry goes through two seams —
llama-server over HTTP and torch's device layer — and both are known to
work on ROCm; what's unconfirmed is the granted image, not the stack.

## Established (source: FOUNDRY.md verification of July 16 + today's checks)

- **llama.cpp ships official ROCm builds.** Release b10043 (checked today
  via GitHub API) includes `llama-b10043-bin-win-hip-radeon-x64.zip`
  alongside the CUDA builds; Linux ROCm is a documented build target
  (`-DGGML_HIP=ON`) and lemonade-sdk publishes prebuilt ROCm 7 builds.
  Teacher serving is llama-server on both devices — the swap is a config
  change (different binary path + GGUF), zero code.
- **PyTorch ROCm exposes HIP as `torch.cuda`.** Code written against
  `device="cuda"` runs unchanged on ROCm wheels (this is why one codebase
  works — the backend choice happens at wheel-install time, not import
  time). ROCm wheels are Linux-only; irrelevant locally (dev box is
  NVIDIA/Windows).
- **Unsloth has official AMD support** (May 2026): RDNA 2/3/4, ROCm ≥ 6.0,
  one-line installer that brings ROCm-optimized PyTorch + bitsandbytes.
  Known failure mode: HIP detection vs. the image's PyTorch build
  (unsloth issue #5180) — this is exactly what the week-1 gate tests.
- **peft LoRA (bf16, no 4-bit) is the portable trainer baseline.** For
  0.6B–1.7B students, full-precision-base LoRA fits in any plausible VRAM
  (0.6B bf16 ≈ 1.2GB weights), so **bitsandbytes is not on the critical
  path** — QLoRA is an optimization, not a requirement. This is a
  deliberate de-risk: the slice must not depend on 4-bit kernels working
  on the granted image.
- **GGUF conversion is pure Python** (gguf-py + safetensors) — no GPU, no
  ROCm dependency. Runs anywhere.
- **Teacher sizing:** Qwen3-30B-A3B-class Q4_K_M ≈ 17–18GB weights + KV
  cache — fits 24GB, comfortable at 32GB. ~150 tok/s tg on R9700-class
  ROCm HIP (FOUNDRY.md, verified July 16).

## Unconfirmed — cannot be resolved from here; needs GPU access or Discord

1. Cloud GPU model and VRAM (plan works at 24GB, comfortable at 32GB).
2. Credit quota and burn rate per instance-hour.
3. What the image ships: ROCm version, preinstalled PyTorch-ROCm, docker
   or bare, pip egress to PyPI/HuggingFace.
4. Whether Unsloth's AMD installer works on that specific image (gate
   test, first hours of access).
5. Whether bitsandbytes-ROCm works on the image (only matters for QLoRA
   upgrade, not for the baseline).
6. vLLM dedicated-endpoint mechanics for the 20-pt bonus (can we serve a
   custom fine-tuned GGUF/HF model on it?).

## Decision this note records

Trainer ladder: **Unsloth (first choice on Radeon) → transformers+peft
(portable baseline, what the local slice exercises) → torchtune (last
resort).** The peft path is the one the slice validates end-to-end on
CUDA today; Unsloth gets its verdict in the first hours of GPU access,
per the week-1 gate. Do not build anything that assumes Unsloth works
until that verdict is in.
