# Radeon runbook

> **Status July 17:** week-1 gate PASSED (both trainer backends; full 1K
> run done — see notes/). The gate sections below are kept for
> reference. The next paid GPU time is **Session 1: benchmarks** at the
> bottom of this file. ~5 credits remain — nothing runs unscripted.

## Radeon Session 1 — submission benchmark numbers (~75 min, scripted)

The gate instance was destroyed, so this session rebuilds at full scale
first (the factory is fast — that's the point), then benchmarks.

```bash
# 0. Launch the same workspace template (unsloth-vincent). Then:
cd ~ && python3 -m zipfile -e /workspace/foundry-transfer.tar.gz . 2>/dev/null || tar -xzf /workspace/foundry-transfer.tar.gz -C ~/foundry-project
cd ~/foundry-project
/opt/venv/bin/pip install --quiet requests sentencepiece protobuf matplotlib /opt/llama.cpp/gguf-py
/opt/venv/bin/hf download unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf --local-dir models/teacher/
/opt/venv/bin/hf download Qwen/Qwen3-0.6B --local-dir models/student/Qwen3-0.6B

# 1. Full-scale build (~20 min): 900/100 triage
/opt/venv/bin/python run_slice.py --config configs/cloud_radeon.toml

# 2. Benchmark ladder + teacher speed (~30-40 min; uses the run dir
#    printed by step 1)
/opt/venv/bin/python run_bench.py --config configs/cloud_radeon.toml --run-dir runs/slice-<TIMESTAMP>

# 3. rocm-smi screenshot during step 1 datagen and during step 2
#    (demo evidence of GPU execution)

# 4. Pull artifacts BEFORE destroying the instance:
tar --exclude "*.gguf" --exclude "merged" --exclude "adapter" -czf /workspace/radeon-runs2.tar.gz runs
# download via JupyterLab, then DESTROY THE INSTANCE.
```

---

## Radeon Session 1.5 — endpoint + screenshots + 1.7B ladder + EPYC CPU (~90 min)

Launch the unsloth-vincent workspace and upload a current
foundry-transfer tarball. To refresh it, extract the existing one to a
temp dir (it carries a hand-curated slim runs/), copy the changed code
over it, and re-tar — do NOT tar runs/ from the repo, it is 16GB.
On the instance, extract and run `bash scripts/up.sh` — it does deps,
accelerated parallel model downloads, UI start, and verification in one
shot (models cache in /workspace/foundry-models, so repeat sessions on
a rebuilt instance skip the 19GB of downloads):

```bash
# A. Setup (same as Session 1: extract, deps, models — plus 1.7B student)
mkdir -p ~/foundry-project && tar -xzf $(find / -maxdepth 4 -name "foundry-transfer.tar.gz" 2>/dev/null | head -1) -C ~/foundry-project && cd ~/foundry-project
/opt/venv/bin/pip install --quiet requests sentencepiece protobuf matplotlib flask /opt/llama.cpp/gguf-py
/opt/venv/bin/hf download unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf --local-dir models/teacher
/opt/venv/bin/hf download Qwen/Qwen3-0.6B --local-dir models/student/Qwen3-0.6B
/opt/venv/bin/hf download Qwen/Qwen3-1.7B --local-dir models/student/Qwen3-1.7B
```

```bash
# B. 1.7B student ladder: full build with the bigger student, then bench.
# (config edit: student.hf_path -> models/student/Qwen3-1.7B)
sed -i 's#models/student/Qwen3-0.6B#models/student/Qwen3-1.7B#' configs/cloud_radeon.toml
/opt/venv/bin/python run_slice.py --config configs/cloud_radeon.toml
RUN=$(ls -dt runs/slice-* | head -1) && /opt/venv/bin/python run_bench.py --config configs/cloud_radeon.toml --run-dir "$RUN"
```

```bash
# C. EPYC CPU numbers for the students (deployability line)
for q in q4_k_m q5_k_m q8_0; do /opt/llama.cpp/build/bin/llama-bench -m "$RUN/student-$q.gguf" -ngl 0 -t 32 -o json | /opt/venv/bin/python -c "import json,sys; [print('CPU', '$q', round(r['avg_ts'],1), 'tok/s') for r in json.load(sys.stdin) if r['n_gen']>0]"; done
```

**D. Endpoint attempt (browser, not terminal):** portal → Model APIs
tab → look for "deploy custom model" / dedicated endpoint creation. If
it accepts an upload or a HF/GGUF reference, deploy the 0.6B student
(q5_k_m from any run) and curl one request against it; save the
response. Screenshot every step either way — success or dead-end, §8 of
the report gets the truth.

**E. UI screenshots for the PPT:** serve the UI
(`/opt/venv/bin/python serve_ui.py --config configs/cloud_radeon.toml --port 8300`,
tunnel with `cloudflared tunnel --url http://localhost:8300` if needed),
resume a build, run one diagnose, screenshot: (1) chat + tool chips,
(2) GPU card during teacher activity, (3) registry rail.

**F. Before destroy:** `tar --exclude "*.gguf" --exclude merged --exclude adapter -czf /workspace/radeon-session15.tar.gz runs`
→ download → DESTROY INSTANCE.

# (Reference) Week-1 gate on the granted cloud instance — PASSED July 17

Goal: reproduce the vertical slice on the granted Radeon and decide the
trainer backend. Everything here is copy-paste; record outcomes in
notes/ as you go. Do not start a long stage without the cost estimate
step — instances burn credits until destroyed.

## What only you (the human) can do first

1. **Register the AMD AI Developer Program** — hard gate on prize
   eligibility, do this before anything else.
2. **Apply for Radeon cloud access** via the guide in
   github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07 (Radeon-Cloud-User
   Guide). Enable SSH if the template allows it.
3. **Join the hackathon Discord** and post the questions below.
4. When the instance is up: either give me a session on it (SSH details /
   JupyterLab terminal) or run the blocks below and paste outputs back.

## Discord questions (paste-ready)

> 1. Which GPU model and how much VRAM do the granted Radeon cloud
>    instances have? Are there multiple instance templates to choose from?
> 2. What credit quota do participants receive, what is the per-hour
>    burn rate per instance type, and can credits be topped up if they
>    run out before the deadline?
> 3. What is preinstalled on the instance image — ROCm version,
>    PyTorch-ROCm build? Is outbound internet available (pip/PyPI,
>    Hugging Face downloads)?
> 4. Is SSH available on all templates, or only specific ones?
> 5. Has anyone successfully run LoRA/QLoRA fine-tuning on these
>    instances (Unsloth, peft, or torchtune)? Any known-good setup?
> 6. For the Track 2 bonus ("core inference running using Radeon cloud
>    model API with quantization or distillation"): can we deploy our own
>    fine-tuned model as a dedicated vLLM endpoint, and in which format
>    (HF safetensors / GGUF)?
> 7. Are the free shared model endpoints (Qwen/DeepSeek) allowed as dev
>    conveniences only, or do they play any role in judging?

## Instance session 0 — probe (minutes, cheap)

```bash
# What is this machine?
rocminfo | grep -E "gfx|Marketing"; rocm-smi --showmeminfo vram
python3 --version; pip --version
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))" || echo "NO PYTORCH — install ROCm wheel"
nproc; free -h; df -h /
curl -sI https://huggingface.co | head -1   # outbound internet?
```

Record: gfx target, VRAM, ROCm version, preinstalled torch, internet.
**If VRAM < 24GB**: the 30B teacher won't fit at Q4 — fall back to
Qwen3-14B or Qwen3.5-class teacher; flag it and we re-plan.

## Session 1 — teacher serving (measure before you commit)

```bash
cd ~ && git clone <repo-or-rsync>   # get this repo onto the instance
# llama.cpp ROCm: try prebuilt first, else build (~10 min)
git clone https://github.com/ggml-org/llama.cpp tools/llama.cpp-src
cmake -S tools/llama.cpp-src -B tools/llama.cpp-rocm -DGGML_HIP=ON -DCMAKE_BUILD_TYPE=Release
cmake --build tools/llama.cpp-rocm --config Release -j$(nproc) --target llama-server llama-bench

# Teacher download (~18GB) — check disk first
pip install -U huggingface_hub
hf download unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf --local-dir models/teacher/

# Benchmark: this number goes in notes/ and eventually the submission
tools/llama.cpp-rocm/bin/llama-bench -m models/teacher/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf -ngl 99
```

## Session 2 — trainer gate (the decision this whole runbook exists for)

```bash
python3 -m venv .venv && source .venv/bin/activate
# torch: skip if image ships a working ROCm torch; else match image ROCm:
# pip install torch --index-url https://download.pytorch.org/whl/rocm<ver>
pip install transformers peft requests
pip install ./tools/llama.cpp-src/gguf-py

# GATE A (baseline must pass): tiny peft run — 100 examples, 1 epoch
# edit configs/cloud_radeon.toml: n_train=90, n_holdout=10, epochs=1
python run_slice.py --config configs/cloud_radeon.toml
# PASS = slice completes, eval_report.json shows tuned > base

# GATE B (first choice): unsloth
pip install unsloth   # use the AMD install path from unsloth.ai/docs/get-started/install/amd
# flip backend = "unsloth" in configs/cloud_radeon.toml, rerun train+eval:
python run_slice.py --config configs/cloud_radeon.toml --stages train,eval --run-dir runs/slice-<...>
# PASS = trains without HIP-detection errors and eval matches peft ± noise
```

Decision rule: if Gate B passes, backend = unsloth everywhere; if it
fails after ≤2 hours of fighting, backend = peft, write the failure into
notes/, move on. torchtune only if peft also breaks (it shouldn't — it's
plain torch).

## Cost discipline

Before the full 1K run: time the 100-example run, multiply by 10, add
teacher benchmark time, convert to credits at the burn rate from Discord
Q2. Write the estimate down. **Destroy the instance when done** —
Profile → Active Instance → Destroy.

## What success looks like

A `runs/slice-*/slice_summary.json` on the Radeon with all four stages,
`eval_report.json` showing tuned ≫ base, a served GGUF smoke test, and
three numbers for notes/: teacher tok/s, train wall-time, eval accuracy.
That is the week-1 gate passed, and week 2 (agentifying) starts on solid
ground.
