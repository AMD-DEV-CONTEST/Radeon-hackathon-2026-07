# Session 1.5 (July 28) — 1.7B ladder, CPU table, endpoint verdict

One-liner: second student size measured (1.7B: 0.95 exact — the task
SATURATES at 0.6B, right-sizing is a measurable feature), CPU
deployability table completed, and the 20-pt bonus endpoint resolved as
platform-unavailable (Model APIs category empty; evidence screenshot
filed).

1.7B full build (runs/slice-20260728-042020, 900/100, ~21 min loop):
- datagen 99.2% acceptance (third full run ≥99% — the pipeline is boringly reliable)
- train 264.5s (vs 175.1s for 0.6B); tuned 0.95 exact (cat 0.95 / pri 0.96)
- Ladder: Q4 1056MB/219.3 tok/s/0.900 · Q5 1200/213.3/0.950 ·
  Q6 1352/204.0/0.940 · Q8 1749/194.9/0.960
- vs 0.6B (Jul 18): 0.97 exact, Q5 424MB/283.4. **Bigger bought
  nothing on this task** — same accuracy band, 3× size, 25% slower.
  Demo/PPT line: "Foundry measures the right student size instead of
  guessing."

CPU tok/s (llama-bench -ngl 0):
| Student | Quant | Laptop i7-14650HX (8t) | EPYC 9334 (32t) |
|---|---|---|---|
| 0.6B | Q4_K_M | 64.2 | 89.5 |
| 0.6B | Q5_K_M | 41.7 | 82.3 |
| 0.6B | Q8_0   | 33.6 | — |
| 1.7B | Q4_K_M | — | 39.2 |
| 1.7B | Q5_K_M | — | 35.9 |
Headline: 0.6B Q4 at 89.5 tok/s on a server CPU ≈ 80% of the 30B
teacher's GPU speed. No GPU needed to serve what Foundry makes.

Endpoint (20-pt bonus line): portal → Model APIs = "No templates in
this category yet. 0 shown" (evidence/model-apis-empty-2026-07-28.png).
Dedicated endpoint deployment was not available to participants during
the contest window, despite the user guide describing it. Bonus case
rests on substance: distillation + quantization with ALL core
inference (teacher serve, LoRA train, student serve) on Radeon cloud
instances. Report §8 updated accordingly.

Credits: still 5 after the session (checked by user pattern last time —
re-verify at video day). UI screenshots deferred to video capture
frames (Session 2).
