# RepoMind — Project Spec (Track 2, Agentic AI)

## Background
Two markets share one pain. **Path A — locked out:** regulated enterprises (finance, healthcare, defense,
proprietary codebases) legally *cannot* send source code to a third-party LLM API, so cloud coding
assistants are off-limits — on-prem is the only option. **Path B — bleeding:** teams that *can* use the
cloud pay a fast-growing per-token bill. And separately, years of **CUDA** keep GPU teams locked to NVIDIA.

RepoMind is the on-prem **cost + trust + migration layer** that answers all three — on AMD.

## Target users & scenarios
- Regulated enterprises needing a **private** coding assistant that never sends code off the box.
- Teams wanting to **migrate CUDA workloads to AMD** (ROCm) without a painful manual port.
- Developer-productivity / enterprise-copilot / local-knowledge-assistant (RAG) use cases.

## System architecture (5 Track-2 capabilities)
```
Developer → RepoMind FastAPI
              ├─ Agent loop:  plan → tool → observe → answer   (multi-step planning)
              │     tools: list_files · grep_codebase · read_file · migrate_cuda_to_rocm  (tool-invocation)
              ├─ RAG over the cloned repo                        (RAG)
              ├─ Ed25519 tamper-evident audit trail             (multi-turn memory)
              └─ cost-router → vLLM-ROCm on AMD Radeon/MI300X    (privacy / on-prem, AIR_GAP=0 egress)
```

## Models & algorithms
| Component | Choice |
|---|---|
| Local coding model | Qwen2.5-Coder-14B-Instruct (open-weight), FP16 |
| Serving | vLLM-ROCm 0.23 (OpenAI-compatible), continuous batching |
| Agent | SC-TIR loop (plan/call/observe/answer), keyword+regex tool-arg parser |
| CUDA→ROCm | deterministic rule engine (includes, memory/stream/event APIs, kernel-launch `<<<>>>`→`hipLaunchKernelGGL`) |

## AMD Radeon GPU / ROCm adaptation
- All inference runs locally on a **Radeon PRO W7900 (gfx1100, RDNA3, 48 GB)** via vLLM-ROCm / HIP (ROCm 7.2).
- CUDA→ROCm output compiles with **hipcc** for `gfx1100` and **executes on the GPU** (verified, PASS).
- `AIR_GAP=1` forces every token on-prem — measured `{"egress":"on-prem only (AIR_GAP)"}`.
- Optimization: FP16 + vLLM continuous batching → **3.76×** aggregate throughput (measured).

## Measured results (on the provided Radeon W7900)
- Decode: **27.6 tok/s** single-stream → **103.8 tok/s** @ concurrency-4 (**3.76×**) → 106 @ conc-8.
- TTFT **88 ms** · VRAM **46.8 GB**.
- CUDA→ROCm compile-run: `vecAdd` **PASS** (kernel 0.71 ms) · `reduceSum` **PASS** (shared-mem + atomicAdd).
- CUDA coverage: of the top-10 patterns, **9 have an AMD path** (5 auto-port; 4 → hipBLAS/MIOpen/rocThrust/
  rocWMMA); only inline PTX is NVIDIA-only, and RepoMind flags it instead of faking a rename.

## Reproduction
```bash
export HF_ENDPOINT=https://hf-mirror.com
vllm serve Qwen/Qwen2.5-Coder-14B-Instruct --dtype float16 --max-model-len 32768 \
  --gpu-memory-utilization 0.92 --host 0.0.0.0 --port 8000 \
  --served-model-name qwen-coder --api-key token-repomind
export AIR_GAP=1 VLLM_BASE_URL=http://localhost:8000 VLLM_MODEL=qwen-coder VLLM_API_KEY=token-repomind
uvicorn main:app --host 0.0.0.0 --port 8090
bash scripts/demo_final.sh          # agent + CUDA top-5 + honest boundary + bench
python3 scripts/prove_and_benchmark.py   # CUDA→hipcc→RUN (PASS) + economics
```

## Demo video
https://youtu.be/6YkKYjP_it0

## Honesty note
Throughput/tok-s/PASS are **measured** on the provided W7900. Cost comparisons vs cloud APIs are **modeled**
from public prices and clearly labeled; on-prem's defensible edge is **privacy/air-gap**, not "cheapest".

## Team
Sardor Razikov (solo) — AMD Act I winner (AI Agents), AMD Featured Developer. GitHub @SRKRZ23.

## References
Project repo: https://github.com/SRKRZ23/repomind-amd-devmaster · Radeon deployment: `RADEON_CLOUD_DEPLOYMENT.md`.
