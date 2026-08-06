# Final model service decision — P1 prefix cache

## Decision

The final local model service is **`P1-prefix-cache`**:

- `Qwen/Qwen3.5-9B`, immutable ModelScope revision
  `460979c3d11864dd16408d860ac930a360a2fac2`;
- BF16 on Radeon PRO W7900 through ROCm and vLLM 0.26;
- 20K application context, `max-num-seqs=2`, localhost bind;
- Qwen3 tool/reasoning parsers and `--enable-prefix-caching`;
- request-level thinking disabled by the Agent client.

Launch it with:

```bash
bash scripts/serve_final_vllm.sh
```

Rollback removes only the selected Stage 1 factor:

```bash
SERVING_PROFILE=S0 bash scripts/serve_final_vllm.sh
```

No schema, database, prompt, Runtime policy, Agent permission or public-network
change is part of this decision.

## Evidence and claim boundary

The selection uses two different evidence layers and does not combine their
measurement conditions:

1. **Stage 1 service evidence (selection basis).** Under its frozen 8K,
   `max-num-seqs=4` serving-screen contract, P1 ranked first with score
   `105.079709`, p95 TTFT `275.670 ms`, output TPS `16.308`, peak VRAM
   `40620 MiB`, quality `18.25/30`, and reliability `85%`. All nine hard gates
   passed. See PR #39 at benchmark commit
   `dc85e8c27f04c45213c324c1361ee62645818d2b`, evidence Manifest SHA-256
   `88d05076b449322664674e0469309dba35d41fec411ab896f8cca832b0d19678`,
   and score SHA-256
   `d4e149895ea318208b913790d63c8eb1c07167c66f160faff9d6da73646a73d7`.
2. **Stage 2 product evidence (compatibility gate).** Under the final 20K,
   `max-num-seqs=2` application configuration, the same complete synthetic
   Agent journey passed on S0 and P1 with no observed functional or safety
   regression. The P1 observation took `109.21 s`; its measured cache-hit rate
   was `0.0%`, so the one-run timing difference is not attributed to caching
   and is not a generalized latency claim. See
   [`STAGE2_MINIMAL_RESULT.md`](STAGE2_MINIMAL_RESULT.md).

The honest final claim is therefore: Stage 1 established P1 as the strongest
frozen serving Candidate, and Stage 2 established that it can run the complete
integrated product without an observed regression. S0 remains the immediate
rollback because P1's Stage 1 warm-up reliability was `85%`.

## Reproducible identity

- Machine-readable final Profile:
  `config/serving/final-p1-prefix-cache.json`.
- Model file manifest: `config/models/qwen3.5-9b.modelscope.json`.
- Final wrapper: `scripts/serve_final_vllm.sh`.
- Stage 2 sanitized evidence:
  `evidence/performance/stage2-minimal/20260806T124938Z/`.
- Raw Stage 1 and Stage 2 logs remain append-only under
  `/workspace/amd-track2-agent`; they are not copied into Git.

## Track 2 and submission impact

This closes the model-service selection needed for the final WebUI and E9 demo.
It supplies a reproducible local W7900/ROCm launch command, a bounded optimization
claim, and a one-command rollback. It does not claim model training,
fine-tuning, statistical application speedup or public service deployment.
