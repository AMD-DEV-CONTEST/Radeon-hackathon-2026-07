# AMD Radeon PRO W7900 / ROCm reproduction

This directory contains the public scripts used to install, serve, benchmark, and safely roll back YIJIAN model routes on a Radeon PRO W7900 (gfx1100). Model services listen on localhost only.

## Public Qwen3-14B base route

1. Create the pinned ROCm vLLM environment:

```bash
bash deploy/cloud/install_qwen3_14b_vllm.sh
```

2. Download the fixed base revision:

```bash
bash training/remote/download_qwen3_14b.sh
```

The expected revision is `40c069824f4251a91eefaf281ebe4c544efd3e18`, stored by default at `/workspace/yijian/qwen3-14b-bf16`.

3. Start the public BF16 service without a private adapter:

```bash
bash deploy/cloud/start_qwen3_14b_base.sh
curl -fsS http://127.0.0.1:8083/v1/models
```

Defaults: BF16, `gpu-memory-utilization=0.72`, `max-model-len=8192`, `max-num-seqs=2`, prefix caching enabled, and localhost-only port 8083.

## KataGo

KataGo 1.16.5 and its registered official network are configured separately. The Agent never treats language-model output as board truth: legal replay, captures, liberties, position hashes, candidates, PVs, win rate, and score lead come from the rules/KataGo evidence layer.

## Private authorized adapter route

`start_qwen3_14b_agent.sh` expects an authorized frozen adapter at `/persistent/yijian/models/yijian-lora-v3-frozen/adapter`. That adapter is not public because the creator-derived training authorization is competition-specific and non-commercial. The source, configuration, aggregate hashes, and evaluation evidence are public.

The three-profile coexistence matrix (`0.72`, `0.75`, `0.78`) overlaps KataGo 128-visit analysis with model generation for 30 cycles per profile. All v3 profiles completed 30/30 with zero OOM; the selected 0.72 profile achieved combined P95 10.3355 seconds and preserved the most KataGo headroom.

## Release and rollback

The 14B LoRA passed training and machine runtime gates but failed the anonymous human release gate. Do not promote it to the competition alias. The sealed-once set remains unopened and the stable 27B service is restored after every exclusive stage. The gate and rollback scripts preserve that decision on success, failure, or interruption.
