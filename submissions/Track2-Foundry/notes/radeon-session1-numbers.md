# Radeon Session 1 (July 18) — THE submission numbers, gfx1100 48GB

One-liner: full-scale factory run + complete benchmark ladder on the
granted Radeon; student hits **0.97 exact match** (n=100 holdout) and
the Q5_K_M student is **2.6× faster than its 30B teacher at 1/42 the
size** — instance run dir runs/slice-20260718-052618, artifacts in
radeon-session1.tar.gz.

Factory (spec-driven pipeline, specs/triage.json, backend peft):
- datagen: 1,000/1,010 = **99.0% acceptance**, classes balanced
  155–175, 1058.2s (~17.6 min) at 8 slots.
- train: 171 steps, final loss 0.0029, **175.1s**.
- eval n=100: base 0.15 → **tuned 0.97** exact match (category 0.97,
  priority 0.97, json_valid 1.0 both).
- export + served smoke: OK. Whole loop ≈ 21 min.

Benchmark ladder (llama-bench tg tok/s + accuracy served through
llama-server on the SAME holdout):

| Model    | Size     | tg tok/s | Exact match |
|----------|----------|----------|-------------|
| Q4_K_M   | 378 MB   | 284.9    | 0.920       |
| Q5_K_M   | 424 MB   | 283.4    | **0.970**   |
| Q6_K     | 472 MB   | 273.9    | 0.970       |
| Q8_0     | 610 MB   | 256.5    | 0.970       |
| Teacher 30B Q4_K_M | 17,697 MB | 110.2 | (source of labels) |

Headline lines for video/writeup (all verified above):
- "97% exact agreement with its teacher on held-out data."
- "2.6× the teacher's generation speed, 1/42 its size" (Q5_K_M).
- "Q4 costs 5 points of accuracy; Q5 costs nothing" — the quant ladder
  has a real story, not a flat line.
- Serving-path accuracy == checkpoint accuracy (0.97 == 0.97): the
  GGUF pipeline loses nothing.
- Teacher at 110 tok/s tg on gfx1100 (vs ~150 on R9700/RDNA4 per public
  benches) — consistent, credible.

Consistency note: second independent full-scale run (first was July 17:
0.95) — the factory reproduces within noise. Both runs' artifacts are
in the repo under runs/.

CPU deployability (measured July 26, laptop i7-14650HX, 8 threads,
llama-bench -ngl 0, identical-architecture local student GGUFs):
Q4_K_M 64.2 tok/s · Q5_K_M 41.7 · Q8_0 33.6. EPYC numbers pending
Session 1.5. Headline: the Q4 student on a laptop CPU runs at more
than half the 30B teacher's speed on a 48GB workstation GPU.
