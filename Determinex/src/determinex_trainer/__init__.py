"""Determinex training pipeline.

LoRA fine-tune + Unsloth orchestration for the C1/C3/C7 model family.
Invoked as a subprocess by `ignite_loop.py`, `scripts/determinex_flywheel.py`,
and `scripts/tonight_launch.py`. Modules expose CLI entry points; importing
them as a package is supported but not required.

Key modules:
    dsl_finetune        - LoRA on Determinex DSL corpus (rank 4/8/16)
    train_unsloth       - Unsloth-accelerated training driver
    merge_lora_to_ollama - Merge a LoRA adapter into a base Ollama model
"""
