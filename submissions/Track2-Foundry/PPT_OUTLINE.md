# PPT outline — Foundry (supplementary material, ~12 slides)

Rule: one idea per slide, the visual carries it, numbers only from
SUBMISSION_REPORT.md. Build at freeze with the pptx toolchain; this
outline is the content contract.

1. **Title.** Foundry: an autonomous model-distillation agent on a
   single AMD Radeon. Track 2, solo. Visual: product wordmark + the
   one-line pitch.
2. **The problem.** "Everyone wants small private models; the pipeline
   between 'I need X' and a model file is expert work." Visual: the
   pipeline as a wall of steps a human must do today.
3. **The product in one sentence.** Conversation in → model file out.
   Visual: UI screenshot — user message, agent plan, tool chips.
4. **Why it can't be an API wrapper.** Training needs local weights;
   datagen = tens of millions of tokens (free locally); seed docs never
   leave. Visual: three-line argument, no clutter.
5. **How it works.** The loop diagram: spec → generate (RAG on seed
   docs) → train → eval → diagnose → regenerate → export. Agent
   capabilities labeled in Track 2's own words.
6. **It runs on one Radeon.** Three workloads timesharing gfx1100
   48 GB: 30B teacher serving, LoRA training, student serving. Visual:
   rocm-smi/UI telemetry screenshot during a build.
7. **Headline result.** Base 0.15 → student **0.97 exact match**
   (n=100). Visual: the two-bar before/after — biggest number on any
   slide.
8. **The quant ladder.** bench_chart.png (Radeon run). Callout: "Q4
   costs 5 points; Q5 costs nothing."
9. **Student vs teacher.** 424 MB vs 17.7 GB; 283 vs 110 tok/s; 97%
   agreement — and against blind policy ground truth, student equals
   teacher (0.95 / 0.95; both 1.00 on unambiguous). Visual: size
   squares + speed bars — the 1/42 : 2.6× money shot.
   Sub-beats added July 28 (fold into this slide or split to 9b):
   - Right-sizing measured: 1.7B student = same accuracy, 3× size,
     25% slower → 0.6B is the measured pick, not a guess.
   - CPU deployability: 0.6B Q4 at 89.5 tok/s on a server CPU,
     64 tok/s on a laptop CPU — no GPU needed to serve the product.
   - Teacher A/B (report §4.6): swapped in benchmark-stronger
     Qwen3.6 via one config line; its student measured WORSE against
     ground truth (0.92 vs 0.95) at 2.4× slower datagen → "leaderboard
     rank doesn't decide distillation quality; a measured afternoon
     does." One line + tiny table, this is the judges' q&a killer.
10. **The improvement loop.** 0.667 → 0.833 exact after targeted
    regeneration on a frozen holdout. Visual: diagnose output → focused
    augment → delta.
11. **Generality + memory.** Second domain (expense routing) from a new
    policy doc, zero code changes; registry resumes builds across
    sessions. Visual: registry rail screenshot with both tasks.
12. **Close.** "Small models, made to order, on your Radeon." Repo,
    stack line (ROCm 7.2.4 · llama.cpp · PyTorch-ROCm · peft), thanks.

Assets needed at build time (all exist or are one screenshot away):
bench_chart.png (Radeon) ✓ · UI screenshots (capture during Radeon
Session 2 rehearsal) · before/after bar chart (generate from
eval_report.json) · loop diagram (draw once, reuse in video end card).
