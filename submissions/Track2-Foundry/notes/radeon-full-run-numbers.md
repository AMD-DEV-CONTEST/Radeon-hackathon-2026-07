# Submission-grade full run on Radeon gfx1100 — July 17, 2026

One-liner: the headline number for the demo/writeup — student
base→tuned exact_match 0.15 → 0.95 on 100 held-out tickets, whole
factory loop in ~20 min on the granted 48GB gfx1100, backend peft.
Instance run dir: runs/slice-20260717-044950.

Dataset (30B teacher, Qwen3-30B-A3B-Instruct-2507 Q4_K_M, 8 slots):
- 1008 accepted / 1021 attempts = 98.7% acceptance (higher than the
  4060's 96.7% — severity facet + json_object mode paying off).
- categories balanced 167-170; priorities P1 203 / P2 275 / P3 361 /
  P4 169.

Eval (100 holdout, greedy):
- base Qwen3-0.6B: category 0.29, priority 0.21, exact 0.15
- tuned:           category 0.97, priority 0.96, exact 0.95
- json_valid 1.00 both (student always emits parseable JSON).

Timings (seconds): datagen 979.1, train 170.9 (171 steps, batch4×accum4,
final loss 0.0009), eval 9.6, export 11.2. Total ~19.5 min wall.
- Radeon train ≈ 1.0 s/step vs 4060 ≈ 4.9 s/step → ~5× on training.
- Radeon datagen ≈ 1.03 examples/s (llama.cpp b9766, gfx1100).

These are the numbers that go in the submission. GGUF is 610 MB Q8_0
(student is 1/29th the teacher's 17.3GB on disk). Not yet done:
per-class accuracy breakdown, quant ladder (Q4/Q5/Q6 vs eval), student
tok/s benchmark, teacher tok/s via llama-bench — all week-2 optimization
work, none blocking.
