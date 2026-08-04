# Demo Video Script (3–5 minutes)

Record on the Radeon instance with the console at `http://127.0.0.1:7860`.
Keep the terminal and the browser visible to prove real execution on the GPU.

## Shot list

### 0:00 – 0:25  Intro
- Title card: "RadeonPilot — multi-agent ROCm inference ops on AMD Radeon".
- One sentence: agents diagnose, deploy, benchmark, and optimize a local model
  endpoint, and every generation runs on the Radeon itself.

### 0:25 – 0:55  Prove the hardware
- Terminal: `rocm-smi --showproductname` (shows the Radeon + gfx target).
- Terminal: `cat /opt/rocm/.info/version` (ROCm 7.2.1).
- Terminal: `curl -s http://127.0.0.1:8000/v1/models` (endpoint is up).

### 0:55 – 1:40  Live diagnosis
- Browser: open the Ops Console. Click **Diagnose** -> GPU environment + endpoint
  status appear (real rocm-smi output).
- Chat: type "Diagnose the endpoint and report health." Show the five agent reports
  populating and the attestation badge turning **RADEON ATTESTED**.

### 1:40 – 2:30  Optimization with evidence
- Chat: type "Time-to-first-token feels high. What should I optimize?"
- Show the Optimization Analyst citing local knowledge (prefix caching / chunked
  prefill) and the gated action plan. Point out a hazardous step marked **blocked**.
- Terminal: run `python scripts/benchmark_vllm.py --profile baseline --runs 5`.
- Show the measured JSON written to `benchmarks/results/`.

### 2:30 – 3:15  Multi-turn memory
- Chat follow-up: "What changes if I double the concurrency?"
- Show the session replanning from memory (same session id) rather than restarting.

### 3:15 – 3:45  Quantized bonus
- Terminal: switch endpoint to `ENGINE=llama` (Q4_K_M GGUF) and re-run the quality
  gate `python scripts/run_quality_gate.py` showing `passed=true`.
- Show the quantized benchmark JSON side by side with the BF16 record.

### 3:45 – 4:10  Close
- `python scripts/verify_submission.py` -> RESULT: PASS.
- Recap: private, local, evidence-bound; optimization measured, not claimed.

## Recording tips

- Use a screen recorder at 1080p; keep the terminal font large.
- Do not edit out the attestation badge or the measured numbers.
- If a step stalls on camera, re-run it; authenticity matters more than speed.
