# AMD Radeon cloud deployment

The final agent runs entirely inside the AMD Radeon instance. Only frozen
patches and leakage-safe trajectories are copied back to the Mac for the
official SWE-bench Docker evaluator, because the current cloud container does
not provide Docker.

## Fixed layout

```text
/workspace/radeon-code-agent                 source and small manifests
/root/models/Qwen3-14B-BF16                    BF16 checkpoint
/root/radeon-code-agent-venv                  isolated Python/vLLM env
/root/radeon-code-agent-work                  disposable task workspaces
```

Do not modify `/opt/venv`. Record `rocminfo`, `rocm-smi`, Python, ROCm,
PyTorch, vLLM, model file hashes, and the GPU identifier before running tasks.

## vLLM service

After the model and isolated environment are prepared, the reproducible
launcher is:

```bash
./scripts/cloud_start_vllm.sh
TRACK2_BASE_URL=http://127.0.0.1:8000/v1 \
TRACK2_API_KEY=local-vllm \
TRACK2_MODEL=Qwen3-14B-BF16 \
  /root/radeon-code-agent-venv/bin/python track2_cloud_acceptance.py \
  --output /root/radeon-cloud-acceptance.json
```

The launcher first runs `scripts/cloud_preflight.py`. It refuses to start the
server unless `rocminfo` exposes the expected `gfx1100` agent, the Qwen3 model
config is present, and ROCm PyTorch reports BF16 support.

The launcher writes only to the explicit PID/log paths and waits for
`/health`; it does not fall back to a hosted endpoint. The acceptance command
exits non-zero unless all 10 tool calls, 20 structured actions, and 30
stability requests pass.

The current isolated runtime is pinned to:

```text
torch 2.11 ROCm 7.2.2, vLLM 0.25.1, Transformers 5.5.4
```

If INT8 KV cache is rejected or the 32K profile runs out of memory, use the
fixed fallback profiles in `configs/qwen3_14b_bf16.json`. Never overwrite the
preinstalled environment and never fall back to the AMD hosted inference API
for final results.

The service is started on `127.0.0.1:8000/v1` with:

```text
--language-model-only
--reasoning-parser qwen3
--enable-auto-tool-choice
--tool-call-parser hermes
--dtype bfloat16
--kv-cache-dtype int8_per_token_head
--max-model-len 32768
--gpu-memory-utilization 0.90
--max-num-seqs 1
```

The baseline uses prefix caching off. A separate fixed 4K/16K input benchmark
compares caching off/on; it is enabled in the final demo only when output
correctness is unchanged and median TTFT improves.

The 2026-08-04 instance reached model-registry acceptance but stopped before
benchmarking: vLLM 0.25.1 has no native FP8 MoE kernel for the old checkpoint
on `gfx1100`. The exact backend attempts and logs are recorded in
[`amd-cloud-vllm-blocker-20260804.md`](amd-cloud-vllm-blocker-20260804.md).
The formal experiment intentionally uses Qwen3-14B BF16 on the same RadeonX
instance; the old FP8 result remains preliminary evidence only.

## Service acceptance

Before SWE-bench:

- execute 10 semantic tool cases;
- execute 20 J3 schema requests and require 20/20 valid envelopes;
- run normal chat, thinking, finish, and edit flows;
- complete 30 sequential requests without OOM or service restart;
- record TTFT, decode throughput, P50/P95 latency, VRAM, and GPU use.

## Agent and evaluator boundaries

Each task receives a clean checkout containing only repository identity,
`base_commit`, and the issue text. The agent never sees gold patch,
`test_patch`, `FAIL_TO_PASS`, or `PASS_TO_PASS`. Shell credentials are stripped;
network/package-install commands and absolute paths outside the workspace are
blocked. A dedicated non-root user runs tool commands. Pass
`--agent-env local` to the SWE-bench harness on this Docker-less instance;
the local backend is command-guarded and is not described as kernel-isolated.

After each batch, copy `run-config.json`, public manifests, trajectories,
patches, stderr, verifier reports, and GPU metrics to the Mac. Run the official
evaluator only after all candidates are frozen and never feed its output back
into a later agent call.
