# RepoMind — On-Prem Agentic Coding Assistant + CUDA→ROCm (Track 2)

**AMD AI DevMaster Hackathon · Track 2 — Agentic AI**
**Team:** Sardor Razikov (solo) · GitHub [@SRKRZ23](https://github.com/SRKRZ23) · Tashkent, Uzbekistan
**AMD Dev Program email:** razikovs777@gmail.com

- 🎥 **Demo video:** https://youtu.be/6YkKYjP_it0
- 📂 **Project repo (code + raw proofs + reproduce scripts):** https://github.com/SRKRZ23/repomind-amd-devmaster

## One line
An on-prem AI coding agent that plans, uses tools, reads your repository, and migrates **CUDA → ROCm** —
running **100% on a single AMD Radeon PRO W7900** (ROCm), with **zero external egress** (`AIR_GAP`).

## Track-2 capabilities (needs ≥2 of 5 — RepoMind does all 5)
| Capability | How |
|---|---|
| RAG | clones + indexes the target repo, retrieves relevant files locally |
| Tool-invocation | `list_files`, `grep_codebase`, `read_file`, `migrate_cuda_to_rocm` |
| Multi-step planning | plan → tool → observe → answer loop (SC-TIR) |
| Multi-turn memory | Ed25519 tamper-evident audit trail of every step |
| Privacy / on-prem | `AIR_GAP=1` → all inference on the local Radeon, 0 egress |

## Judging-criteria mapping
- **Functional value (60):** agentic multi-step over a real repo (finds the exact file + fix) **+** a
  CUDA→ROCm migrator (`/cuda-to-rocm`) that ports the top-5 patterns fully and flags the hard 10% with the
  correct ROCm equivalent. Real CUDA → `hipcc` → **executed on the GPU, PASS**.
- **ROCm / Radeon optimization (40):** local inference on the W7900 via vLLM-ROCm — **measured** 27.6 tok/s
  single-stream → **103.8 tok/s (3.76×)** via continuous batching; TTFT 88 ms; 46.8 GB VRAM.

## Deliverables
- FastAPI agent + cost-router + CUDA→ROCm migrator (source in the project repo, `backend/`).
- Reproduce scripts: `demo_final.sh`, `prove_and_benchmark.py`, `cuda_top5.py`, `cuda_hard_cases.py`.
- Raw proofs: compiled HIP binaries, `.hip.cpp`, benchmark logs, SHA-256 sums, environment snapshot.

See `PROJECT_SPEC.md` (full spec) and `RADEON_CLOUD_DEPLOYMENT.md` (how it runs on Radeon).
Every number labeled **measured** is reproducible on the provided Radeon Cloud W7900.
