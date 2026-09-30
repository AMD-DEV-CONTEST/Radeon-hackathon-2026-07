# Caprigo — Track 2 Reproduction README

**Team:** Vibes-Coded · **b_Radford** · English

Judges should be able to reproduce scrap baseline evidence from public repos and the ROCm decode method from `docs/AMD.md`.

---

## A. Scrap baseline (RX 580 / Vulkan)

1. Clone https://github.com/doteyeso-ops/rx580-vulkan-agents — CSVs + lived proof.  
2. Clone https://github.com/doteyeso-ops/caprigo — install per upstream README.  
3. Point Caprigo at local Ollama (Vulkan):

```bash
export CAPRIGO_LEAN_TOOLS=1
export CAPRIGO_LLM_PROVIDER=ollama
export OLLAMA_URL=http://127.0.0.1:11434
```

4. Optional Session timing: `scripts/bench_agent_delta.ps1` in the lived-proof repo (scrap ~31 s lean path documented).

---

## B. ROCm Radeon Cloud (decode delta method)

1. AMD AI Developer Program member · same email on Radeon Cloud.  
2. Launch a ROCm vLLM-dev template (Navi / gfx1100 class).  
3. Serve and time:

```bash
/opt/venv/bin/vllm serve Qwen/Qwen2.5-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --gpu-memory-utilization 0.90 --max-model-len 8192

# POST /v1/chat/completions temperature=0 max_tokens=128
# tok/s = completion_tokens / wall_seconds
```

4. Compare to scrap 7B ~19 tok/s. Our captured result: **29.21 tok/s** (`artifacts/delta.csv`).

Helper:

```bash
python3 measure_vllm_toks.py --model Qwen/Qwen2.5-7B-Instruct --out /tmp/out.txt
# or from this packet:
python3 Caprigo/scripts/measure_vllm_toks.py --model Qwen/Qwen2.5-7B-Instruct
```

Contest GPU guide: [Radeon-Cloud-User Guide](../../Radeon-Cloud-User%20Guide/README.md)

---

## Dependencies

- Caprigo: Node monorepo (see upstream `package.json` / README)  
- Scrap inference: Ollama + Vulkan  
- Cloud inference: vLLM on ROCm image supplied by contest templates  
- No private keys required to evaluate public evidence
