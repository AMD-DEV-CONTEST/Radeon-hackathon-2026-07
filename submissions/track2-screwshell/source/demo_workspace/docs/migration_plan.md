# ROCm Migration Plan — Project Helios

Status: draft v0.9 (internal, confidential)
Owner: Platform Team

## 1. Goal

Migrate the Helios inference cluster from CUDA-only nodes to AMD Radeon PRO
W7900 (48GB) nodes running ROCm 7.2, cutting inference cost per token by an
estimated 38% while keeping all data on-premises.

## 2. Scope

- Serving stack: PyTorch 2.10 + ROCm 7.2.4, bf16 inference
- Models: Qwen3.5-9B family (frozen base + LoRA adapters)
- Out of scope: training pipeline (phase 2), Windows clients

## 3. Timeline

| Phase | Window | Deliverable |
|---|---|---|
| P0 pilot | Aug W1 | single W7900 node serving shadow traffic |
| P1 rollout | Aug W2-W3 | 40% traffic on ROCm nodes |
| P2 full | Sep W1 | 100% traffic, CUDA nodes decommissioned |

## 4. Key Risks

1. **Kernel coverage risk**: hybrid-attention models (gated delta networks)
   rely on Triton kernels that historically lagged on ROCm. Mitigation:
   pin transformers >= 5.5 and run the GDN smoke suite on every driver bump.
2. **Memory fragmentation risk**: long-running bf16 serving on 48GB cards can
   fragment VRAM when adapters are loaded/unloaded frequently. Mitigation:
   keep the base model frozen and resident; hot-swap small LoRA adapters
   instead of reloading models.
3. **Operator fallback risk**: any silent CPU fallback erases the cost win.
   Mitigation: CI gate that fails when a op dispatches to CPU during the
   golden-path benchmark.
4. **Single-vendor tooling risk**: monitoring currently assumes nvidia-smi.
   Mitigation: migrate dashboards to rocm-smi exporters before P1.
5. **Rollback risk**: keep CUDA images warm for 30 days after P2.

## 5. Benchmark acceptance criteria

- tokens/s within 10% of the CUDA baseline at bf16
- adapter switch latency under 100 ms P99
- zero CPU-fallback ops on the golden path
