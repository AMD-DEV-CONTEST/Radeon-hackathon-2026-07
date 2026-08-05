# Benchmark harness validated July 17 — quant ladder + tok/s + chart, 4060

One-liner: run_bench.py (and the agent's benchmark_quants tool) produce
the inference-speed rubric artifacts end to end: f16 convert →
llama-quantize ladder → llama-bench pp/tg tok/s per quant → served
holdout accuracy per quant (through llama-server, i.e. the deployed
artifact) → bench_report.json/md + bench_chart.png with the GPU named.

4060 numbers (mechanics validation ONLY — submission numbers come from
the Radeon; holdout n=12 so ±1 ticket = ±8.3%):

| Quant  | MB  | tg tok/s | exact |
|--------|-----|----------|-------|
| Q4_K_M | 378 | 255.5    | 0.750 |
| Q5_K_M | 424 | 238.4    | 0.833 |
| Q6_K   | 472 | 233.0    | 0.833 |
| Q8_0   | 610 | 224.1    | 0.750 |
| teacher (4B stand-in) | 2382 | 66.2 | (labels) |

Read: Q5_K_M is the sweet spot at this scale — full checkpoint accuracy,
3.6× the stand-in teacher's speed, 1/5.6 its size. Q8-below-Q5 accuracy
is single-ticket noise. Against the real 30B teacher on the Radeon the
speed/size ratios become the demo's closing numbers.

Mechanics notes:
- llama-bench -o json parses cleanly (avg_ts split by n_prompt/n_gen).
- Quantize from an f16 GGUF (student-f16.gguf kept in the run dir),
  not from Q8 — avoids double-quantization.
- Served accuracy MUST send chat_template_kwargs enable_thinking=false
  (see [[qwen3-thinking-template-serving]]).
- Device name auto-detected (nvidia-smi → rocminfo Marketing Name).
- Agent path: benchmark_quants stops/starts the teacher around the
  bench subprocess; summary lands in the registry.
- Radeon Session 1 (full rebuild + bench, ~75 min) is scripted in
  RADEON_RUNBOOK.md — the instance from the gate was destroyed, so the
  fast rebuild IS part of the demo story.
