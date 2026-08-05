# Unsloth patches transformers globally — train and eval need separate processes

One-liner: importing unsloth monkey-patches transformers' model classes
process-wide (Qwen3Attention.forward → fast path expecting `apply_qkv`),
so any model loaded via vanilla `from_pretrained` in the same process
crashes at generate() with AttributeError: 'Qwen3Attention' object has
no attribute 'apply_qkv'. Not a ROCm bug.

Hit July 17, 2026 on the Radeon instance during Gate B: train stage
(unsloth) succeeded, then the in-process eval stage crashed loading the
base student. Fix: run stages as separate invocations —
`--stages train` then `--stages eval` — the eval process never imports
unsloth. Any future orchestrator/agent must spawn pipeline stages as
subprocesses when backend=unsloth (good VRAM hygiene anyway).

Other Gate B facts worth keeping (all on gfx1100, torch 2.10 rocm7.2.4,
unsloth 2026.6.9):
- Unsloth banner correctly detects "AMD gfx1100 GPU", 47.98 GB, bf16
  TRUE, Xformers None / FA2 False (attention falls back — fine at 0.6B).
- lora_dropout=0.05 disables unsloth's fast-path patching of LoRA
  matrices ("patched 28 layers with 0 QKV/0 O/0 MLP layers") — set
  dropout=0 to get the full speedup if we adopt unsloth.
- Final train loss matched peft on identical data/seed (0.1214 vs
  0.1193) — backend equivalence at the loss level.
- "Unsloth should be imported before transformers" warning: cosmetic
  for training here, but the global-patch behavior above is the real
  constraint it hints at.
