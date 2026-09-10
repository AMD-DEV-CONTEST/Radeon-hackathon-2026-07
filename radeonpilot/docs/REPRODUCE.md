# Reproduction Guide (Judge-facing)

Follow these steps on the AMD Radeon instance to reproduce the submitted results.
Each step ends with a checkpoint so you can verify progress.

## 0. Prerequisites

- AMD Radeon GPU with ROCm 7.2.1 (reference: gfx1100, 48 GB VRAM)
- Ubuntu 24.04, Python 3.11+, internet access for package download
- This repository cloned to the instance

```bash
git clone https://github.com/RongjieChen/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/radeonpilot
```

Checkpoint: `ls` shows `app.py`, `pi-bridge/`, `src/`, `scripts/`, `docs/`.

## 1. Bootstrap the environment

```bash
bash scripts/setup_server.sh
```

Installs Node 22, creates the Python venv, downloads Qwen3-8B (ModelScope), builds
llama.cpp with HIP for gfx1100, converts BF16 + Q4_K_M GGUF, and starts the vLLM
ROCm install in the background.

Checkpoint: `tail -1 /root/radeonpilot-setup/bootstrap.log` shows `bootstrap done`.
`ls /root/models/gguf/` shows both `.gguf` files once the pipeline finishes.

## 2. Start the model endpoint

```bash
bash scripts/start_endpoint.sh
```

(The verified engine is llama.cpp GGUF. `ENGINE=vllm` exists for a ROCm vLLM
source build, which is out of scope for quick reproduction.)

Checkpoint: `curl -s http://127.0.0.1:8000/v1/models` returns `qwen3-8b`.

Record the endpoint PID:

```bash
export VLLM_PID=$(pgrep -x llama-server | head -1)
```

Checkpoint: `amd-smi process --pid $VLLM_PID` lists the process (GPU-resident proof).

## 3. Install and start the Pi bridge

```bash
cd pi-bridge && npm ci && cd ..
export VLLM_BASE_URL=http://127.0.0.1:8000/v1
PI_NODE_BIN=node bash scripts/run_bridge.sh
```

Checkpoint: `curl -s http://127.0.0.1:8787/health | python3 -m json.tool` shows
`runtime.radeon_attested: true`.

## 4. Start the Gradio console

```bash
export RADEONPILOT_MODE=pi
bash scripts/run_app.sh
```

Checkpoint: open `http://127.0.0.1:7860`. In **Audit & Runtime**, the badge reads
**RADEON ATTESTED**.

## 5. Run an ops session

In the console chat, enter:

> Diagnose the endpoint and propose speed optimizations.

Checkpoint: the reply shows the five agent reports, an evidence list citing the local
knowledge corpus, and a gated action plan.

## 6. Capture benchmark evidence (optional but recommended)

```bash
export VLLM_PID=<pid-from-step-2>
python scripts/benchmark_vllm.py --profile baseline --runs 5
python scripts/benchmark_vllm.py --profile optimized --runs 5
```

Checkpoint: `benchmarks/results/baseline.json` and `optimized.json` exist and pass
`python scripts/verify_submission.py`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `rocm-smi not found` | Ensure ROCm 7.2.1 is installed and on PATH |
| Bridge reports `GPU UNATTESTED` | Confirm `VLLM_PID` matches the running endpoint; inside a container PID namespace the bridge falls back to amd-smi device occupancy automatically |
| Endpoint fails to load | Check `/root/radeonpilot-setup/llama-server.log`; lower `--ctx-size` if VRAM is tight |
| Empty agent replies | Ensure `--chat-template-kwargs '{"enable_thinking":false}'` is set (Qwen3 thinking consumes the output budget) |
| No Docker | Expected — this deployment intentionally uses venv/source builds |
