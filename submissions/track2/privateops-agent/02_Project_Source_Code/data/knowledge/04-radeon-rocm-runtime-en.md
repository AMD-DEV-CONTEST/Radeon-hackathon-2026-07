# Radeon and ROCm Local Runtime

Competition mode runs `Qwen/Qwen2.5-7B-Instruct` through vLLM on AMD Radeon GPU and ROCm. PrivateOps and the model server run in the same Radeon Cloud instance. The only eligible endpoint is the same-instance loopback URL `http://127.0.0.1:8000/v1/chat/completions`.

The captured runtime used AMD Radeon Graphics with architecture `gfx1100`, ROCm 7.2.1, PyTorch 2.9.1 with HIP, and vLLM 0.16.1. `rocm-local` rejects remote endpoints and never silently falls back. The AMD shared HTTPS API is development-only and is not competition proof.
