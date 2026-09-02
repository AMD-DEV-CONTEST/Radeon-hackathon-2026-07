# Radeon cloud instance: gfx1100, 48GB VRAM, bare Python — probed July 17, 2026

UPDATE Aug 5, 2026 — the instance image CHANGED. Fresh instance came up
with: ROCm **7.2.1** (was 7.2.4), /opt/venv present (training stack
incl. accelerate), but **NO prebuilt llama.cpp anywhere** (the old
image had b9766 at /opt/llama.cpp). Consequences, all verified live:
- `LLAMA_CPP_BUILD=1 bash scripts/up.sh` is now required on a fresh
  instance; the source build takes ~6-7 min on the 128-thread EPYC
  (a large chunk of it is the new llama.cpp webUI npm build).
- git clone on the instance routes through a gh-proxy.org wrapper
  (~880 KB/s for the 35MB shallow clone — slow but tolerable).
- The built tree lands in ~/llama.cpp; foundry's runtime resolution
  (llamacpp.py) finds it via LLAMA_CPP_HOME/`~/llama.cpp` even though
  configs still name /opt/llama.cpp — no config edit needed.
- Teacher now runs on llama.cpp MASTER, not pinned b9766. The
  content_to_text normalization absorbs the response-shape change;
  full pipeline compatibility on master confirmed only up to teacher
  serving (30B loaded, 24GB VRAM) — export/quant ran on master locally
  but watch the first full instance run.
- /workspace was empty on this fresh instance (no files from the
  Aug 4 session) — see bringup-speed note on the persistence question.

One-liner: the granted instance ("unsloth-vincent" workspace, image
unsloth_llama.cpp:latest) is a 48GB gfx1100 (RDNA3, W7900-class); the
full training stack is preinstalled but ONLY inside /opt/venv — system
Python is bare, so every command must use /opt/venv/bin/python.

Probe results (JupyterLab notebook, `!`-prefixed shell):

- GPU: gfx1100 (also exposes gfx11-generic), marketing "AMD Radeon
  Graphics", VRAM 51,522,830,336 B = 48 GiB → Radeon PRO W7900-class.
- Host: 2× AMD EPYC 9334 (128 threads), 503 GiB RAM, 3.5 TB overlay disk
  (2.9 TB free). Swap 0.
- Python 3.12.3, pip 24.0 (system, /usr/lib) — bare, no torch/unsloth.
- **/opt/venv** (probed July 17): torch 2.10.0+rocm7.2.4 (GPU: True,
  "AMD Radeon Graphics"), unsloth 2026.6.9 + unsloth_zoo 2026.6.7,
  peft 0.19.1, bitsandbytes 0.49.2, **transformers 5.5.0** (major ahead
  of local 4.x — watch for API drift), triton 3.6.0+rocm7.2.4,
  torchao 0.17.0, numpy 2.4.6.
- ROCm **7.2.4** at /opt/rocm. llama.cpp prebuilt at
  /opt/llama.cpp/build/bin/{llama-server,llama-cli,llama-bench},
  version b9766, GNU 13.3.0 Linux build (HIP assumed — verify GPU
  offload at first server start via rocm-smi VRAM).
- Outbound internet OK (HF HTTP/2 200). `unzip` NOT installed — use
  `python3 -m zipfile -e`. cloudflared present.
- Not yet checked: credit burn rate (Space tab), llama.cpp repo files
  (convert_hf_to_gguf.py / gguf-py) at /opt/llama.cpp.

Consequences:
- 30B teacher Q4_K_M (~18GB) fits with ~30GB headroom — can raise
  llama-server parallel slots well past 8, and KV cache is not a
  constraint. Could even consider Q5/Q6 teacher.
- gfx1100 is inside both official ROCm 7.2 support and Unsloth's AMD
  support matrix (RDNA3) — no architecture surprise.
- Python 3.12 (not 3.11): fine for our stack, but check wheel
  availability when installing torch-rocm.
- torch must be installed with the ROCm index URL matching the image's
  ROCm version — get /opt/rocm/.info/version BEFORE pip installing.
