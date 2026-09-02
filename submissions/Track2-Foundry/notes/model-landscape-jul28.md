# Model landscape survey (July 28) — Qwen3.6-35B-A3B is the named upgrade path; no swap pre-submission

One-liner: 4-angle survey (~70 sources) of the July-2026 open-weights
field: Qwen3.6-35B-A3B is the only candidate that beats our teacher
within all hard constraints (Apache 2.0, ~20GB Q4, 3B-active speed
class, in-window llama.cpp support, improved tool calling, GPQA ~86 vs
~70) — and we are NOT swapping before submission because it is not the
drop-in its name implies and our teacher is at measured ceiling.

Why no swap (decision record):
1. Qwen3.6 = new 248K tokenizer, new chat template (developer role,
   different thinking controls), hybrid Gated-DeltaNet arch with
   llama.cpp kernels reported 15-30% slower tg (MTP speculative
   decoding recovers some; unmeasured on gfx1100), and one field
   report of stray Chinese characters (JSON-reliability risk for a
   datagen teacher). Migration + full revalidation, not a config edit.
2. Teacher is at 1.00 policy-true on unambiguous cases — no headroom
   on the demo task; all submission numbers would need re-runs for
   zero measurable delta.
3. Freeze Aug 1. Charter scope rule applies.

Post-contest upgrade path (verified): flip teacher config to
Qwen3.6-35B-A3B GGUF once GDN kernels mature on ROCm; smoke-test
llama-server --jinja tool calling + JSON grammar mode + tg speed on the
target card first. Students: Qwen3.5-0.8B/2B (Mar 2026) are the
same-vendor student upgrades — better base benchmarks, but need
transformers-main + new LoRA target modules (GDN blocks); incumbent
students are at task ceiling, so only worth it for harder tasks.

Also-rans and why: Nemotron-Cascade-2-30B-A3B (IMO-gold reasoning at
A3B speed, but conditional NVIDIA license + Mamba2-on-ROCm untested);
Gemma 4 26B-A4B (Apache, fits, weaker structured output — best
non-Qwen fallback and a teacher-diversity option); Qwen3.5-35B-A3B
(superseded by 3.6 + documented broken tool template, llama.cpp
#19905); everything frontier-class (GLM-5.2 376GB, MiniMax M3 143GB,
Kimi K3 ~1.4TB, Llama 4 Scout 61GB) does not fit 48GB; dense 27Bs fail
datagen throughput (3-7x slower than A3B MoE on gfx1100).

Full structured results: July 28 workflow output in session artifacts.
