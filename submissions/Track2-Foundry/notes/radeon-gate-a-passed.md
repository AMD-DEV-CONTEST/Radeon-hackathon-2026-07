# Gate A PASSED July 17: full slice on Radeon gfx1100, peft backend, 112s

One-liner: the vertical slice (30B teacher datagen → peft LoRA train →
eval → GGUF export → served smoke test) completed end-to-end on the
granted 48GB gfx1100 instance with zero code changes from the CUDA
version — run dir runs/slice-20260717-035902 on the instance.

Numbers (pilot scale: 74 accepted / 62 train / 12 holdout):
- datagen 74.6s ≈ 1 example/s with Qwen3-30B-A3B Q4_K_M, 8 parallel
  slots → full 1K dataset ≈ 17 min on Radeon.
- train 22.9s for 12 steps (~1.9 s/step at batch 4×accum 4; local 4060
  was ~4.9 s/step) on torch 2.10.0+rocm7.2.4.
- eval 3.4s, export+smoke 11.4s. Tuned exact_match 0.50 vs base 0.17 —
  weak absolute number is expected at 62 train examples; the 4060 run
  with 908 examples hit 0.94.
- VRAM check read 47.90 GiB free — teacher server was stopped before
  training, as designed.

Environment facts that mattered:
- transformers 5.5.0 ran our 4.x-written trainer/eval unchanged (one
  harmless warning about generation flags).
- Warning "Skipping import of cpp extensions... upgrade to torch >=
  2.11.0" appeared (torchao); harmless for peft. May be relevant to
  unsloth Gate B.
- convert_hf_to_gguf.py at /opt/llama.cpp worked against b9766 with
  gguf-py + sentencepiece pip-installed into /opt/venv.

Claim discipline: "core inference + training on Radeon" is now a
verified claim for the pilot scale. Full-scale (1K) Radeon run still
pending; do it after Gate B settles the backend.
