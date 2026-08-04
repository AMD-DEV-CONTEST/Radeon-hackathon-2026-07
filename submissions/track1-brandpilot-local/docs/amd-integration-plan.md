# AMD Radeon and ROCm integration plan

Radeon Cloud provided the first controlled validation environment on
2026-07-25. One AMD Radeon `gfx1100` GPU, PyTorch `2.9.1+gitff65f5b`, and HIP
`7.2.53211-e1a6bc5663` were verified. A direct fp16 SDXL image-to-image run
completed successfully with measured timing and memory. PyTorch exposes this
ROCm device through `torch.cuda`, so HIP metadata remains mandatory.

The experimental backend now connects the validated SDXL image-to-image path
to an authenticated, single-job FastAPI worker. One real integrated loopback
job completed in session 2. The browser transport portion remains open because
no verified temporary tunnel was available. The core generation workflow
cannot rely only on closed-source external APIs because the project’s privacy,
offline-control, reproducibility, and Radeon acceleration claims require a
real local path.

## Validation stages

- Review model, dataset, and dependency licenses.
- Verify Radeon device, ROCm, PyTorch, and model compatibility.
- Test preprocessing, inference precision, supported operators, and deterministic controls.
- Measure quality and output stability before optimization.
- Optimize batching, attention, precision, memory reuse, and model loading only with evidence.
- Record hardware/software configuration and repeat runs.

Session 1 evidence covers the standalone baseline. Session 2 verified the
authenticated FastAPI worker, persistence, and API review round-trip. Full
browser transport, throughput, warm-run consistency, product preservation, and
repeated-run stability remain future work. Mock remains the application default.
