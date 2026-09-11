# Memloom — README (Submission)

> **Track 2: Development & Local Deployment of Private AI Agents**
> A two-way knowledge layer between people and AI Agents, running fully locally on AMD Radeon GPU.

Memloom turns every conversation between you and your Agent into a **reviewable, evolvable, reusable long-term knowledge asset**. The same knowledge serves both ends: helping **people** internalize understanding, and letting **Agents** inherit your confirmed background, preferences, and lessons learned — with all inference on a local AMD Radeon GPU.

---

## 1. Environment Requirements

| Component | Requirement | Notes |
|---|---|---|
| **OS** | Ubuntu 22.04+ / macOS / Windows | Verified on Ubuntu 22.04.5 LTS |
| **Python** | 3.10+ | Skills path uses pure stdlib — **no third-party deps** |
| **Node.js** | 20+ | Required for the desktop client and review UI |
| **AMD GPU** | RDNA3 (gfx1100) recommended | Verified: AMD Radeon 51.52 GB VRAM |
| **ROCm** | 7.2.x | Verified: ROCm 7.2.1 |
| **vLLM** | 0.16.x | Local inference engine (in `/opt/venv/`) |
| **PyTorch** | 2.9.x | ROCm build (`torch==2.9.1+gitff65f5b`) |

> **GPU note:** flash-attn is **not** installed (incompatible with ROCm). Install it and vLLM will fail — see `amd-radeon-gpu-inference-optimization.md` for the full fix.

---

## 2. Dependencies

```bash
# Desktop client (Electron + React + MUI + Vite + TypeScript)
cd zhiyi-desktop
npm install

# Skills path: no installation needed
#   five skills are pure Python stdlib; review UI uses Node built-ins only.
```

All data lives under `~/.memloom/` (`settings.json` / `secrets.bin` / `store/`), auto-created at startup.

---

## 3. Start the Local Model on AMD GPU (vLLM)

```bash
# Launch the local OpenAI-compatible endpoint (loopback only)
/opt/venv/bin/vllm serve Qwen2.5-14B-Instruct \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.95 \
  --enforce-eager \
  --tensor-parallel-size 1 \
  --host 127.0.0.1 --port 8000
```

- `--enforce-eager` bypasses the ROCm rotary-embedding bug.
- BF16 halves VRAM vs FP32; 14B models fit in ~27.7 GB of the 48 GB available.
- Expected performance (gfx1100, ROCm 7.2.1): TTFT ~0.9 s, ~22 tokens/s throughput (Qwen3-8B).

---

## 4. Start Memloom

### Path A — Desktop client (recommended for the demo)

```bash
cd zhiyi-desktop
npm run dist        # build + package an installer; output in release/

# or development mode (two terminals):
npm run dev                     # terminal A: renderer (127.0.0.1:5173)
npx tsc -p tsconfig.node.json   # terminal B: compile main process
npm run electron:dev            # terminal B: launch Electron
```

**First run:** open **Settings** → enter the model API key (or set `OPENAI_API_KEY`); Base URL defaults to `http://127.0.0.1:8000/v1` for the local vLLM endpoint. Click **Test connection** to verify. The knowledge base and review results stay on disk locally.

### Path B — Skills (lightweight CLI)

```bash
# 1. Symlink the six skills into the workspace
mkdir -p .agents/skills
for s in init distill merge review retrieve recall; do
  ln -s /path/to/Memloom/skills/$s .agents/skills/$s
done

# 2. Initialize the knowledge base
python3 .agents/skills/init/scripts/init.py \
  --workspace "$PWD" \
  --knowledge-dir "$PWD/knowledge"

# 3. Daily loop: distill → merge → review → (retrieve / recall)
node .agents/skills/review/scripts/review_server.js \
  --knowledge-dir "$PWD/knowledge" --host 127.0.0.1 --port 4177
# open http://127.0.0.1:4177 for the review UI
```

---

## 5. Quick Validation

| Check | Command | Expected |
|---|---|---|
| GPU visible | `rocm-smi --showmeminfo vram` | ~51.5 GB VRAM on gfx1100 |
| vLLM up | `curl http://127.0.0.1:8000/v1/models` | Returns the model JSON |
| App up | `npm test` (vitest) / `npm run typecheck` | All pass |

---

## 6. Repository Structure

```
.
├── skills/          # Path B: six knowledge-base skills (init/distill/merge/review/retrieve/recall)
├── zhiyi-desktop/   # Path A: Electron desktop client (extract/merge engine, capture/store/model/review/recap/delivery services)
├── evals/           # fixed chat inputs, human gold standards, model test reports
├── benchmarks/      # AMD Track 2 benchmark suites (v1 smoke / v2 stateful)
└── 产品文档/en/      # English submission materials (specification, architecture, optimization report)
```

Benchmark evidence: see `evals/reports/*.md` and `benchmarks/` — 13-model comparison, v2 five-dimension stateful suite, 90.5% extraction success (Qwen2.5-14B), TTFT 236× improvement after optimization.

---

© 2026 Memloom Team. Local-first · privacy-restrained · AMD Radeon GPU powered.
