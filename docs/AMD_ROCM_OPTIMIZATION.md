# AMD Radeon / ROCm Optimization Notes

## Target Hardware

- AMD Radeon PRO W7900 (Radeon Cloud)
- Software stack: ROCm + PyTorch (HIP)

## Optimization Strategy

### 1. Dual-backend development loop
Use Radeon Cloud free Model APIs for agent logic iteration, then switch to `local_transformers` for private on-GPU inference demos. This reduces wasted GPU hours during debugging.

### 2. Smaller context via local RAG
Local MiniLM embeddings + Chroma retrieval keep only top-k chunks in the prompt, improving both latency and answer grounding.

### 3. FP16 inference
`configs/default.yaml` uses `dtype: float16` for local Transformers mode to improve throughput on Radeon GPUs.

### 4. Bounded agent steps
`agent.max_steps` defaults to 6, preventing runaway tool loops that burn GPU time.

### 5. Persistent storage on Radeon Cloud
When creating templates, choose **Persistent (PVC)** so model weights, embedding cache, and vector DB survive instance restarts.

### 6. Optional vLLM serving
For higher QPS demos, deploy a dedicated OpenAI-compatible endpoint with Radeon Cloud **vLLM Model API** template, then point `llm.base_url` to that endpoint while keeping the same agent code.

## Verification Commands

```bash
python scripts/verify_rocm.py
python scripts/ingest_sample.py
python app.py
```

Expected GPU check highlights:
- `torch.cuda.is_available() == True`
- HIP/ROCm version printed when available
- Device name contains Radeon

## Measured Demo Checklist (fill during recording)

Run on Radeon Cloud:

```bash
python scripts/verify_rocm.py
python scripts/bench_rocm.py
```

| Metric | Result |
|--------|--------|
| GPU model | _(from verify_rocm)_ |
| ROCm / HIP version | |
| Backend mode | local_transformers |
| Cold start / llm_load_s | |
| Avg LLM round latency | |
| FP16 matmul 2048 avg ms | |
| Peak VRAM GB | |

## Optimization levers used in this project

1. **FP16** weights/activations for Radeon throughput  
2. **RAG top-k** shrinks prompt → fewer generate tokens  
3. **Agent max_steps=6** caps tool loops  
4. **Smaller instruct model first** (1.5B) for stable live demos; scale to 3B/7B if VRAM allows  
5. **PVC / HF cache under /root** avoids re-download and workspace fill
