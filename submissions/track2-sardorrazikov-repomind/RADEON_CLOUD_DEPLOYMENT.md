# RepoMind — AMD Radeon Cloud Deployment

How RepoMind was deployed and measured on the AMD Radeon Cloud instance during the hackathon.

## Instance
- GPU: **AMD Radeon PRO W7900** (gfx1100 / RDNA3, 48 GB).
- Image: `vllm/vllm-openai-rocm:v0.23.0` · ROCm/HIP **7.2** · torch 2.10.
- Access via the **JupyterLab browser terminal** (external SSH is blocked from outside CN).
- Total compute used: **~2 hours (3 credits)** for the full Track-2 build + benchmarks.

## 1. Serve the coding model (vLLM-ROCm, OpenAI-compatible)
```bash
export HF_ENDPOINT=https://hf-mirror.com          # HF is slow/blocked on the instance; use the mirror
vllm serve Qwen/Qwen2.5-Coder-14B-Instruct \
  --dtype float16 --max-model-len 32768 --gpu-memory-utilization 0.92 \
  --host 0.0.0.0 --port 8000 --served-model-name qwen-coder --api-key token-repomind
```
Free shared Model APIs are also available on the portal; RepoMind is fully env-configurable
(`VLLM_BASE_URL` / `VLLM_MODEL` / `VLLM_API_KEY`) so it can point at either.

## 2. Start RepoMind (on-prem routing)
```bash
export AIR_GAP=1 VLLM_BASE_URL=http://localhost:8000 VLLM_MODEL=qwen-coder VLLM_API_KEY=token-repomind
uvicorn main:app --host 0.0.0.0 --port 8090
# health → {"status":"ok","egress":"on-prem only (AIR_GAP)"}
```

## 3. Run the demo + proofs
```bash
bash scripts/demo_final.sh              # GPU → health → agent → CUDA top-5 → honest boundary → bench
python3 scripts/prove_and_benchmark.py  # CUDA → hipcc (gfx1100) → RUN on the GPU (PASS) + economics
```

## Gotchas we hit (documented so judges can reproduce)
- **No CA certs** on the image → `git clone` fails with cert errors. Fix: `git config --global http.sslVerify false`.
- **File upload** via JupyterLab lands in the current dir — move it to where the code runs (`/workspace/backend/`).
- `rocm-smi --showproductname` throws libdrm errors in-container → use `rocminfo | grep "Marketing Name"`.
- `hipcc` (/opt/rocm/bin) compiles the converted CUDA→HIP for gfx1100 without issue.

## Measured optimization
| config | throughput | note |
|---|---|---|
| fp16, single | 27.6 tok/s | baseline |
| fp16, batched (conc-4) | **103.8 tok/s** | **3.76×** via vLLM continuous batching |
| fp16, batched (conc-8) | 106.0 tok/s | W7900 saturation |
TTFT 88 ms · VRAM 46.8 GB. Further headroom (not run): FP8/AWQ re-serve + larger KV budget.

## Credit management
One active instance, 1 credit / GPU-hour. Destroy the instance when idle — the whole submission (agent +
CUDA→ROCm + benchmarks + video capture) fit in ~2 hours.
