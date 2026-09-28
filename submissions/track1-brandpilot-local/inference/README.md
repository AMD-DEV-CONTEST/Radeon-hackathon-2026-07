# Inference foundation

This directory defines the reusable contract for product analysis, concepts, advertisement images, campaign copy, device metrics, and health checks. `mock_pipeline.py` implements the contract without pretending that image generation or GPU work occurred.

Run `python device_check.py` for a safe inspection. It tolerates missing PyTorch, missing GPUs, unavailable ROCm, and Windows hosts. PyTorch commonly exposes AMD ROCm devices through `torch.cuda`, so `torch.version.hip` is essential context.

SDXL base image-to-image has been selected and verified in one controlled
Radeon Cloud run. The tested revision and settings are encoded in
`rocm_pipeline.py`; weights are not part of this repository. The web application
instantiates this pipeline only through the disabled-by-default experimental
worker. One authenticated loopback API job completed on Radeon Cloud. Session
2b verified the official browser transport but did not complete generation; a
fresh pod had to restore the previously measured ephemeral Diffusers stack.
Session 2c restored the exact pinned non-Torch stack and verified the cached
model revision and AMD device without replacing PyTorch. No model load or
generation ran because the official tunnel hostname did not resolve publicly.

`rocm_pipeline.py` is the explicit real-mode shell. It requires ROCm PyTorch,
Diffusers, a configured model, and a successful `load_model()` call. Missing
requirements raise clear errors and never select the mock implementation.

The verified baseline is `stabilityai/stable-diffusion-xl-base-1.0` revision
`462165984030d82259a11f4367a4eed129e94a7b`, fp16, 768 × 768, 15 steps,
strength 0.35, guidance 6.5, seed 20260725. IP-Adapter, ControlNet, masks,
warm-run performance, and production readiness are not yet validated.
