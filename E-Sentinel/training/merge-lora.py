#!/usr/bin/env python3
"""合并 LoRA adapter 到基础模型，输出独立合并权重。

用途：#170 量化对照的前置。合并后产出 stock 之外的 tuned 权重，
可供 vLLM 直接加载，或进一步做 GPTQ/INT8 量化。

用法（在 AMD 实例 /opt/vllm-env）：
  python training/merge-lora.py \
    --model /workspace/Qwen3-8B \
    --lora  /workspace/e-sentinel-lora \
    --out   /workspace/Qwen3-8B-tuned
"""

import argparse

from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/workspace/Qwen3-8B")
    ap.add_argument("--lora", default="/workspace/e-sentinel-lora")
    ap.add_argument("--out", default="/workspace/Qwen3-8B-tuned")
    args = ap.parse_args()

    print(f"[merge] 加载 base: {args.model}")
    base = AutoModelForCausalLM.from_pretrained(
        args.model, dtype="float16", device_map="auto", trust_remote_code=True
    )
    print(f"[merge] 加载 LoRA: {args.lora}")
    model = PeftModel.from_pretrained(base, args.lora)
    merged = model.merge_and_unload()
    merged.save_pretrained(args.out, safe_serialization=True)
    AutoTokenizer.from_pretrained(args.model).save_pretrained(args.out)
    print(f"[merge] 合并权重已保存: {args.out}")


if __name__ == "__main__":
    main()
