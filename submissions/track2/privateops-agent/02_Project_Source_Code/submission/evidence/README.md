# Verified Radeon Cloud evidence

Captured on 2026-08-03 from Radeon Cloud instance `u-15477-db2e6f27`. Core inference and the PrivateOps application ran in the same instance and communicated only through `127.0.0.1`.

## Verified runtime

- GPU: AMD Radeon Graphics (`gfx1100`), 51,522,830,336 bytes VRAM reported by `rocm-smi`
- ROCm: 7.2.1; HIP runtime visible to PyTorch
- PyTorch: `2.9.1+gitff65f5b`, `torch.cuda.is_available() == True`
- vLLM: `0.16.1.dev0+g89a77b108.d20260317.rocm721`
- Model: `Qwen/Qwen2.5-7B-Instruct`
- Application mode: `rocm-local`; model endpoint `http://127.0.0.1:8000/v1/chat/completions`

## Measured run

- Direct loopback model latency: 1,511.072 ms
- Completion throughput: 32.427 tokens/s
- Prompt/completion tokens: 45 / 49
- Full Chinese Agent task latency: 18.384639 s, including retrieval, planning, model generation, audit persistence, and response assembly

The measured values are machine-generated. The source record is `rocm-verified/radeon-benchmark-run.json`; do not edit the numbers by hand.

## Independent reproduction on 2026-08-04

The Radeon Cloud profile was launched again and independently confirmed AMD Radeon Graphics (`gfx1100`), 48.0 GiB VRAM, ROCm 7.2.1, PyTorch/HIP, ROCm vLLM, Qwen2.5-7B-Instruct, and PrivateOps in `rocm-local` mode over `127.0.0.1:8000`. The fresh machine benchmark measured 1,513.115 ms and 32.384 completion tokens/s with 45 prompt and 49 completion tokens. A UI-contract request using `response_language=zh-CN` returned a real Chinese Agent answer and audit ID. All 101 tests and the 27-artifact submission validator passed inside the instance.

The reproduction is kept in `rocm-retest-20260804/` and does not replace the immutable primary capture.

## Files

- `rocm-verified/rocm-verified-diagnostics.txt`: ROCm SMI, HIP, PyTorch, vLLM, application status, and benchmark proof
- `rocm-verified/radeon-benchmark-run.json`: verified benchmark record
- `rocm-verified/rocm-agent-live-response-zh.json`: real Chinese Agent response, plan, evidence, metrics, and audit identifier
- `rocm-verified/rocm-audit-export.json`: exported audit ledger from the verified session
- `rocm-verified/cloud-retest.log`: cloud test run and submission validation log
- `rocm-verified/vllm.log`: model loading and server log
- `rocm-retest-20260804/`: independent diagnostics, benchmark, direct-Qwen response, Chinese Agent response, audit export, vLLM log, and cloud test logs from 2026-08-04
- `remote-retest-20260804.json`: sanitized evidence for a real AMD Cloud API development-mode response; no credential material is included
- Repository-only `privateops-rocm-evidence.zip`: unchanged downloaded evidence bundle with SHA-256 `02E9B7733FE941EB82BF053DF068258D638C6A23C6A8FE593A4E11AD74147111`. The final submission ZIP includes the expanded verified evidence files instead of nesting this archive.
