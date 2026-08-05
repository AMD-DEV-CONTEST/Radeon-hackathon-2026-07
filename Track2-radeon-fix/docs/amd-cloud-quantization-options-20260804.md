# Radeon hardware decision record (2026-08-04)

The current instance is Radeon `gfx1100`. The fixed experiment uses the
official `Qwen3.6-35B-A3B-FP8` checkpoint, but the ROCm/vLLM stack rejects its
serialized block-scaled FP8 MoE layout on this device. The benchmark is
therefore stopped before any task is run.

## A possible Radeon-only alternative

The [public Radeon Cloud workshop for Hermes-Agent](https://radeon.anruicloud.com/templates/320/preview)
uses a command equivalent to:

```bash
vllm serve /models/Qwen3.6-35B-A3B-AWQ-4bit \
  --served-model-name qwen3.6 \
  --dtype float16 \
  --attention-backend TRITON_ATTN \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3
```

This is useful evidence that the Radeon image can support a Qwen3.6 AWQ/W4A16
runtime, but it is not an acceptable substitution for the current final
experiment: it changes the official FP8 checkpoint to a third-party AWQ
quantization and changes the inference backend configuration. No AWQ task
result is included in the Track 2 ranking unless the experiment specification
is explicitly revised first.

## Valid choices

1. Keep the fixed FP8 protocol and provide a Radeon image/GPU with a native
   FP8 MoE backend (for example an RDNA4 `gfx1201` environment that explicitly
   advertises support).
2. Explicitly revise the protocol to Qwen3.6 AWQ/W4A16 on the current Radeon,
   record the quantization as a separate experimental factor, and rerun the
   full acceptance gate before any SWE-bench task.

An [AMD Instinct MI300X](https://www.amd.com/en/developer/resources/technical-articles/2026/day-0-support-for-qwen3-6-on-amd-instinct-gpus.html)
is a technically viable FP8 host according to AMD's Qwen3.6 deployment
guidance, but it is not Radeon hardware and therefore is not sufficient
evidence for the Radeon Track 2 demo.
